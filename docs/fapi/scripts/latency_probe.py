#!/usr/bin/env python3
"""P2 盘中延迟实测采样脚本(2026-09-02, 一次性研究工具, 非生产).

目的: 测 FAPI snapshot 数据就绪延迟 + 与腾讯秒级真值价格逐位一致率.
口径: FAPI /api/a-share/prices/snapshot 的 data.timestamp(ms) vs 本机采样时刻(ms);
      价格对比 FAPI last_price vs 腾讯 qt.gtimg.cn 同 tick last_price.
方法: 每 ROUND_SECONDS 秒一轮, 盘中连续采样; 落 JSONL 到输出目录;
      --stats 对已采 jsonl 计算 p50/p90/p99 延迟分位 + 价格一致率.
关键口径一句话: 延迟 = FAPI data.timestamp - 本机采样时刻(ms); 价差 = |FAPI last - 腾讯 last|;
      判据见 docs/fapi/fapi-integration-plan-20260901.md §6.3 (<5s 秒级/5-60s 分钟级/分钟级/ >5min).
输入依赖: trade/.env 或 trade-data/.env 的 HITHINK_FINANCE_API_KEY; 腾讯行情接口公网可用.
输出: {OUT}/latency_samples_{YYYYMMDD}.jsonl(每行一轮采样) + --stats 时 {OUT}/latency_stats_{YYYYMMDD}.json
重跑: python docs/fapi/scripts/latency_probe.py --run [--out /tmp/fapi_probe_out]
      python docs/fapi/scripts/latency_probe.py --stats --out /tmp/fapi_probe_out
关键参数: THSCODES(默认 600519.SH,000001.SZ,300750.SZ), ROUND_SECONDS=60, 盘中窗口 09:30-11:30/13:00-15:00.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "app"))
from collector.fapi_daily import BASE, load_key  # noqa: E402

THSCODES = ["600519.SH", "000001.SZ", "300750.SZ"]
TX_MAP = {"600519.SH": "sh600519", "000001.SZ": "sz000001", "300750.SZ": "sz300750"}
# 腾讯返回的 txcode 是纯代码(如 600519), 这里反查回 THSCODE, 与 FAPI/全脚本 key 口径统一
REV_TX = {v[2:]: k for k, v in TX_MAP.items()}
ROUND_SECONDS = 60
TIMEOUT = 15.0
CN_TZ = dt.timezone(dt.timedelta(hours=8))


def _now() -> int:
    return int(time.time() * 1000)


def _fapi_snapshot() -> tuple[dict | None, int]:
    """返回 (price_by_thscode, fapi_timestamp_ms); 失败 (None, -1)."""
    try:
        r = requests.get(f"{BASE}/api/a-share/prices/snapshot",
                         headers={"X-api-key": load_key()},
                         params={"thscodes": ",".join(THSCODES)}, timeout=TIMEOUT)
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            return None, -1
        d = j.get("data") or {}
        items = d.get("item") or d.get("items") or []
        prices = {it.get("thscode"): it.get("last_price") for it in items}
        return prices, int(d.get("timestamp") or -1)
    except Exception:  # noqa: BLE001
        return None, -1


def _tencent_prices() -> dict[str, tuple[float, int]]:
    """腾讯 qt.gtimg.cn 秒级参考真值: {txcode: (last_price, timestamp_ms)}; 失败 {}."""
    q = ",".join(TX_MAP[t] for t in THSCODES)
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={q}", timeout=TIMEOUT)
        r.raise_for_status()
        txt = r.content.decode("gbk", errors="replace")
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for line in txt.strip().split(";"):
        line = line.strip()
        if not line.startswith("v_"):
            continue
        try:
            payload = line.split('="', 1)[1].rstrip('"')
            f = payload.split("~")
            txcode = REV_TX.get(f[2])
            if txcode is None:
                continue
            last = float(f[3])
            ts_str = f[30] if len(f) > 30 else ""
            ts_ms = 0
            if len(ts_str) == 14:
                ts_ms = int(dt.datetime.strptime(ts_str, "%Y%m%d%H%M%S")
                            .replace(tzinfo=CN_TZ).timestamp() * 1000)
            out[txcode] = (last, ts_ms)
        except (ValueError, IndexError):
            continue
    return out


def _in_trading(now_dt: dt.datetime) -> bool:
    t = now_dt.time()
    return (dt.time(9, 30) <= t <= dt.time(11, 30)) or (dt.time(13, 0) <= t <= dt.time(15, 0))


def run(out_dir: Path, rounds: int | None, force: bool = False) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    today = dt.datetime.now(CN_TZ).strftime("%Y%m%d")
    jsonl = out_dir / f"latency_samples_{today}.jsonl"
    count = 0
    while True:
        now_dt = dt.datetime.now(CN_TZ)
        if not force:
            if now_dt.time() > dt.time(15, 0):
                print(f"[{now_dt:%H:%M:%S}] 已收盘, 退出", flush=True)
                break
            if now_dt.time() < dt.time(9, 30):
                print(f"[{now_dt:%H:%M:%S}] 开盘前, 等待...", flush=True)
                time.sleep(30)
                continue
            if dt.time(11, 30) < now_dt.time() < dt.time(13, 0):
                print(f"[{now_dt:%H:%M:%S}] 午休, 等待 13:00...", flush=True)
                time.sleep(30)
                continue
        ts_local = _now()
        fapi_prices, fapi_ts = _fapi_snapshot()
        tx_prices = _tencent_prices()
        row = {
            "ts_local": ts_local,
            "local_time": now_dt.strftime("%H:%M:%S"),
            "fapi_timestamp": fapi_ts,
            "latency_ms": (fapi_ts - ts_local) if fapi_ts > 0 else None,
            "fapi_prices": fapi_prices or {},
            "tencent_prices": {k: v[0] for k, v in tx_prices.items()},
            "tencent_ts_ms": {k: v[1] for k, v in tx_prices.items()},
        }
        with open(jsonl, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        count += 1
        _log_round(row)
        if rounds and count >= rounds:
            break
        time.sleep(ROUND_SECONDS)
    print(f"采样完成: {count} 轮 → {jsonl}", flush=True)
    return 0


def _log_round(row: dict) -> None:
    f = row.get("fapi_prices") or {}
    t = row.get("tencent_prices") or {}
    diffs = []
    for tc in THSCODES:
        if tc in f and tc in t:
            diffs.append(f"{tc}:{f[tc]} vs {t[tc]}")
    print(f"[{row['local_time']}] latency={row['latency_ms']}ms " + " ".join(diffs), flush=True)


def stats(out_dir: Path) -> int:
    today = dt.datetime.now(CN_TZ).strftime("%Y%m%d")
    jsonl = out_dir / f"latency_samples_{today}.jsonl"
    if not jsonl.exists():
        print(f"无样本文件 {jsonl}", file=sys.stderr)
        return 1
    rows = [json.loads(l) for l in jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    lats = sorted(r["latency_ms"] for r in rows if r.get("latency_ms") is not None)
    if not lats:
        print("无有效延迟样本(全部 FAPI 失败?)", file=sys.stderr)
        return 1
    n = len(lats)
    def pct(p):
        return lats[min(n - 1, int(n * p))] if n else None
    # 价格一致率: 每轮三标的与腾讯同轮同值率(价差<=0.001)
    same = total = 0
    per_symbol = {tc: [0, 0] for tc in THSCODES}  # [same, total]
    for r in rows:
        f = r.get("fapi_prices") or {}
        # 历史样本 tencent key 是腾讯纯代码(600519), 新样本已统一 THSCODE; 这里标准化兼容两种
        t = {REV_TX.get(k, k): v for k, v in (r.get("tencent_prices") or {}).items()}
        for tc in THSCODES:
            if tc in f and tc in t and f[tc] is not None and t[tc] is not None:
                total += 1
                is_same = abs(f[tc] - t[tc]) <= 0.001
                if is_same:
                    same += 1
                per_symbol[tc][1] += 1
                if is_same:
                    per_symbol[tc][0] += 1
    out = {
        "date": today,
        "n_rounds": len(rows),
        "n_valid_latency": n,
        "latency_ms": {"p50": pct(0.5), "p90": pct(0.9), "p99": pct(0.99), "min": lats[0], "max": lats[-1]},
        "price_consistency": {"same_tick_rate": same / total if total else None,
                              "n_pairs": total, "n_same": same,
                              "per_symbol": {tc: (per_symbol[tc][0] / per_symbol[tc][1]
                                                  if per_symbol[tc][1] else None) for tc in THSCODES}},
        "samples_file": str(jsonl),
    }
    stat_file = out_dir / f"latency_stats_{today}.json"
    stat_file.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"统计落盘 → {stat_file}", flush=True)
    return 0


def main():
    ap = argparse.ArgumentParser(description="P2 盘中延迟实测")
    ap.add_argument("--run", action="store_true", help="盘中连续采样(默认每60s一轮)")
    ap.add_argument("--stats", action="store_true", help="对已采 jsonl 计算统计")
    ap.add_argument("--out", type=Path, default=Path("/tmp/fapi_probe_out"))
    ap.add_argument("--rounds", type=int, default=None, help="采样轮数上限(默认跑到非盘中)")
    ap.add_argument("--force", action="store_true", help="盘前自测: 强制采一轮(验通路, 分析时去掉)")
    args = ap.parse_args()
    if args.stats:
        return stats(args.out)
    if args.run:
        return run(args.out, args.rounds, force=args.force)
    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
