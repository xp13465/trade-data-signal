#!/usr/bin/env python3
"""FAPI 试点探针(一次性调研脚本,2026-09-02)。

目的:验证同花顺 FAPI 接入方案的端点可用性与字段(只读,不碰生产数据)。
用法:
  python probe_fapi.py dump10d   # 全市场10交易日 dump URL→下载→schema/唯一性/日期范围/对照mootdx
  python probe_fapi.py zt        # 涨停/跌停/炸板池 vs daily_metric(东财口径)
  python probe_fapi.py lhb       # 龙虎榜 vs daily_metric(东财口径)
  python probe_fapi.py index     # THS指数目录/白酒概念/上证综指历史K
  python probe_fapi.py snapshot  # 快照 vs mootdx 收盘
  python probe_fapi.py all
依赖:requests, pyarrow(pip install pyarrow)
输出:/tmp/fapi_probe_out/ (不入 git)
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import requests

BASE = "https://fuyao.aicubes.cn"
OUT = Path("/tmp/fapi_probe_out")
OUT.mkdir(parents=True, exist_ok=True)
REPO = Path("/Users/linhuichen/code/trade")


def load_key() -> str:
    """从 .env 读 HITHINK_FINANCE_API_KEY,绝不打印明文。"""
    for cand in (REPO / ".env", Path("/Users/linhuichen/code/trade-data/.env")):
        if cand.exists():
            for line in cand.read_text().splitlines():
                if line.startswith("HITHINK_FINANCE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("HITHINK_FINANCE_API_KEY not found in .env")


KEY = load_key()
H = {"X-api-key": KEY, "Content-Type": "application/json"}


def _api(path: str, params: dict | None = None) -> dict:
    r = requests.get(f"{BASE}{path}", headers=H, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _check(j: dict, tag: str) -> dict:
    assert j.get("code") == 0, f"[{tag}] code={j.get('code')} msg={j.get('message')}"
    return j["data"]


def _date_ms(yyyymmdd: str) -> int:
    d = dt.datetime.strptime(yyyymmdd, "%Y%m%d").replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return int(d.timestamp() * 1000)


def _ms_to_date(ms: int) -> str:
    return (dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d"))


def cmd_dump10d():
    print("=== dump daily-k-10d ===", flush=True)
    data = _check(_api("/api/dump/market-dumps/daily-k-10d/download-url"), "dump10d")
    print("data keys:", sorted(data.keys()), flush=True)
    url = (data.get("download_url") or data.get("presigned_url") or data.get("url"))
    assert url, f"no url in data: {data}"
    assert "thsi" in url or "s3" in url or "storage" in url, "url 形态可疑(非预签名?): " + url[:120]
    print("presigned url 形态:", url[:150], "…", flush=True)
    # 下载(预签名 URL 短时效,立即用)
    local = OUT / "daily-k-10d.parquet"
    with requests.get(url, timeout=300, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        with open(local, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    print(f"下载完成 {local.name} {local.stat().st_size/1e6:.1f} MB", flush=True)
    import pyarrow.parquet as pq
    t = pq.read_table(local)
    print("schema:", [(f.name, str(f.type)) for f in t.schema], flush=True)
    n = t.num_rows
    print(f"行数: {n}", flush=True)
    df = t.to_pandas()
    # 唯一性
    dup = df.duplicated(subset=["thscode", "date_ms"]).sum()
    print(f"(thscode,date_ms) 重复行: {dup}", flush=True)
    dates = sorted(df["date_ms"].unique())
    print(f"交易日数: {len(dates)}; 最早 {_ms_to_date(dates[0])} 最新 {_ms_to_date(dates[-1])}", flush=True)
    n_code = df["thscode"].nunique()
    print(f"thscode 数: {n_code}", flush=True)
    latest = df[df["date_ms"] == dates[-1]]
    print(f"最新交易日(={_ms_to_date(dates[-1])})行数: {len(latest)}", flush=True)
    # 覆盖 vs 本地 mootdx
    out_rows = json.dump({"n": n, "dup": int(dup), "n_codes": int(n_code),
                           "dates": [_ms_to_date(x) for x in dates],
                           "latest_rows": int(len(latest)),
                           "mbytes": round(local.stat().st_size / 1e6, 1)},
                          open(OUT / "dump10d_summary.json", "w"), ensure_ascii=False, indent=1)
    # 茅台对照
    row = df[(df["thscode"] == "600519.SH") & (df["date_ms"] == dates[-1])]
    if len(row):
        r0 = row.iloc[0]
        print(f"600519.SH@{_ms_to_date(dates[-1])} close={r0['close_price']} vol={r0['volume']}", flush=True)
    else:
        print("600519.SH 不在 dump(检查后缀/覆盖)", flush=True)


def cmd_zt():
    print("=== limit pools vs 东财(20260901) ===", flush=True)
    # 与本地 daily_metric 比较
    conn = sqlite3.connect(REPO / "data/sentiment.db")
    for mid in ("a_width_zt_count", "a_width_dt_count", "a_width_zhaban_rate", "a_width_max_lianban"):
        cur = conn.execute("SELECT value, source FROM daily_metric WHERE metric_id=? AND date='20260901'", (mid,))
        row = cur.fetchone()
        print(f"  daily_metric {mid} 20260901 = {row[0] if row else None} (src={row[1] if row else '-'})", flush=True)
    conn.close()

    for tag, path in (("涨停池", "limit-up-pool"), ("跌停池", "limit-down-pool"),
                      ("炸板池", "limit-break-pool")):
        data = _check(_api(f"/api/a-share/special-data/{path}",
                           {"date_ms": _date_ms("20260901"), "page": 1, "size": 200}), path)
        pag = data["pagination"]
        print(f"  FAPI {tag}: total={pag['total']} pages={pag['pages']} ts={_ms_to_date(data['timestamp'])}", flush=True)
        items = data["item"]
        if items:
            it = items[0]
            print(f"    首条: {it.get('name')} {it.get('thscode')} "
                  f"连板={it.get('continue_day_text') or it.get('first_limit_time')}", flush=True)
    print("  [注] 炸板池再取一页确认 total 是否=东财炸板数口径", flush=True)


def cmd_lhb():
    print("=== dragon-tiger-list ===", flush=True)
    data = _check(_api("/api/a-share/special-data/dragon-tiger-list",
                       {"board_type": "all", "date": "2026-09-01"}), "lhb")
    print(f"trade_date={data['trade_date']} count={data['count']} stock_count={data['stock_count']}", flush=True)
    its = data["stock_items"]
    if its:
        for it in its[:3]:
            print(f"  {it['name']} {it['thscode']} net={it.get('net_value')} range={it.get('range_days')} "
                  f"org_net={it.get('org_net_value')}", flush=True)
    conn = sqlite3.connect(REPO / "data/sentiment.db")
    for mid in ("lhb_count", "lhb_inst_net"):
        row = conn.execute("SELECT value, source FROM daily_metric WHERE metric_id=? AND date='20260901'", (mid,)).fetchone()
        print(f"  daily_metric {mid} 20260901 = {row[0] if row else None} (src={row[1] if row else '-'})", flush=True)
    conn.close()


def cmd_index():
    print("=== THS index catalog ===", flush=True)
    for tag, tag_name in (("cn_concept", "概念"), ("industry", "行业")):
        data = _check(_api("/api/a-share-index/catalog/ths-index-list", {"tag": tag}), f"idx-{tag}")
        n = len(data["item"])
        names = [x["name"] for x in data["item"]]
        print(f"  {tag_name}指数数: {n}", flush=True)
        hit = [nm for nm in names if "白酒" in nm or "机器人" in nm][:5]
        print(f"    含白酒/机器人: {hit}", flush=True)
    # 白酒概念历史K(默认 886042.TI,契约示例)
    data = _check(_api("/api/a-share-index/catalog/ths-index-list", {"tag": "cn_concept"}), "idx")
    white = next((x for x in data["item"] if x["name"] == "白酒概念" or "白酒" in x["name"]), None)
    if not white:
        print("  找不到白酒概念,结束指数K验证", flush=True)
        return
    ts = white["thscode"]
    print(f"  白酒概念 thscode={ts} name={white['name']}", flush=True)
    end = _date_ms("20260901")
    start = _date_ms("20260801")
    data = _check(_api("/api/a-share-index/prices/historical",
                       {"thscode": ts, "interval": "1d", "start": start, "end": end}), "idx-hist")
    items = data["item"]
    print(f"  历史K 条数={len(items)} 末条={_ms_to_date(items[-1]['date_ms'])} "
          f"close={items[-1]['close_price']}", flush=True)
    # 对照 akshare stock_board_concept_index_ths 同概念(找 885908 等白酒) 略:本地无缓存的同花顺概念K,只做可达性


def cmd_snapshot():
    print("=== snapshot vs mootdx ===", flush=True)
    data = _check(_api("/api/a-share/prices/snapshot", {"thscodes": "600519.SH,000001.SZ"}), "snap")
    print(f"snapshot ts={data.get('timestamp')} total={data.get('total')}", flush=True)
    conn = sqlite3.connect(REPO / "data/stock_daily.db")
    for it in data["item"]:
        code = it["thscode"]
        row = conn.execute("SELECT close, volume, amount FROM mootdx_daily_raw WHERE code=? AND date='20260901'",
                           (code,)).fetchone()
        row_bs = conn.execute("SELECT close, turnover FROM baostock_daily_raw WHERE code=? AND date='20260901'",
                              (code,)).fetchone()
        print(f"  {code} FAPI last={it['last_price']} vol={it['volume']} amt={it['turnover']}", flush=True)
        print(f"    mootdx 20260901 close={row[0] if row else None} vol={row[1] if row else None} amt={row[2] if row else None}", flush=True)
        print(f"    baostock 20260901 close={row_bs[0] if row_bs else None} turnover={row_bs[1] if row_bs else None}", flush=True)
        print(f"    收盘一致性: FAPI last vs mootdx close 差="
              f"{abs(it['last_price'] - row[0]) if row else 'n/a'}", flush=True)
    conn.close()


CMDS = {"dump10d": cmd_dump10d, "zt": cmd_zt, "lhb": cmd_lhb, "index": cmd_index, "snapshot": cmd_snapshot}


def main():
    args = sys.argv[1:] or ["all"]
    if args == ["all"]:
        for fn in CMDS.values():
            fn()
            print(flush=True)
        return
    for name in args:
        fn = CMDS.get(name)
        if fn is None:
            print(f"未知命令 {name};可选 {list(CMDS)}", file=sys.stderr)
            raise SystemExit(2)
        fn()


if __name__ == "__main__":
    main()
