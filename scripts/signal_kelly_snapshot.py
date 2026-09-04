#!/usr/bin/env python3
"""signal_kelly_snapshot.py - 信号凯利回测每日快照 + 演进序列 + 断链/突变告警

目的:
    每日回测产物(signal_kelly_backtest.json)生成后, 提取 16 象限×5 周期×10 模式
    关键指标子集 + max_signal_date(全部成交 signal_date 最大值, 直接观测"信号停滞")
    + 最近 10 笔成交摘要 + 版本号, 固化到
    static-site/data/signal_kelly_snapshots/YYYYMMDD.json(全量快照, 按日一个文件),
    并维护 index.json(迷你演进序列: 每日 max_signal_date + 每模式 all 周期 total_return/n),
    供 lab「演进」曲线 + 首页角标读取; --check 模式下扫描 index.json 序列做两类告警。
    2026-09-04 P0 断链根治配套: 本快照让「回测 max_signal_date 停更」(类 9/1-9/4 零成交
    事故)变成自动可见(停滞档告警), 而不再等用户/超时发现。

方法口径:
    - key metric subset = {n, win_rate, pl_ratio, mean_return, total_return,
      annualized_return}; 每 (quadrant, period, mode) 一个指标对象。
    - max_signal_date = 全部成交 signal_date 最大值; recent 10 = 按 signal_date 降序
      取全局最新 10 笔(compact 数组 + fields, 对齐 trades 产物结构)。
    - 突变告警阈值基准 = 滚动窗口(近 60 个快照日, 含昨天不含今天) mean±3.0×std,
      或单日 Δ>20pp 且 n≥20 且连续 2 个交易日同向。⚠️ 防前视 (§5.1⑥): 阈值只用
      t 之前(含 t-1)的数据计算, 绝不用全期分位/未来数据反推。
    - 发布日(快照 version 变化)豁免突变告警; 停滞档不设趋势门(缺失即告警)。
    - 告警走 scripts/notify.py send()(邮件+飞书同 body, §23.10), dedup-key+24h 防抖。

输入依赖:
    - static-site/data/signal_kelly_backtest.json (回测统计, export.py 生成)
    - static-site/data/signal_kelly_trades.json   (交易记录, 同批生成)
输出:
    - static-site/data/signal_kelly_snapshots/YYYYMMDD.json (全量快照)
    - static-site/data/signal_kelly_snapshots/index.json     (迷你演进序列)
关键参数(常量, 不可从外部配置):
    - SNAPSHOT_VERSION 常量: "1.0", bump 当日=发布日豁免突变告警
    - ROLLING_WINDOW=60(快照日), MUTATION_STD=3.0, MUTATION_PP=20,
      MIN_SAMPLES=5(窗口样本下限), MIN_N=20(样本门), LAG_ALERT_TD=2(交易日),
      DEDUP_WINDOW=86400(24h 防抖)
复现命令:
    # 生成今日快照 + 更新 index(export.py L1223 内部以 --data-dir DATA_DIR 调用, 写 trade-data 侧)
    python scripts/signal_kelly_snapshot.py --data-dir <DATA_DIR>
    # 只读模式告警检测(挂 backfill_metrics.sh 02:00/16:35/21:00 尾部,
    #   backfill 侧必须显式 --data-dir "$REPO/static-site/data" 与 export 写侧一致)
    python scripts/signal_kelly_snapshot.py --check --data-dir <DATA_DIR>
退出码语义(调用方依赖, 变更需同步 backfill_metrics.sh 快照段):
    0 = 快照成功 / --check 无告警
    1 = --check 检测到预期告警(停滞/突变; 正常路径, 非脚本错误, 不阻塞 backfill)
    2 = 脚本异常(非预期崩溃, 如产物缺失/读取失败; 区别于"有告警")
"""
import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = ROOT / "static-site" / "data"

# 阈值/参数常量区 —— 滚动窗基准, 非全期分位(§5.1⑥ 防前视)
SNAPSHOT_VERSION = "1.0"          # 发布日=version 变化当日, 豁免突变告警
ROLLING_WINDOW = 60               # 滚动窗快照日数(含昨天不含今天)
MUTATION_STD = 3.0                # 突变档: |today - 窗口均值| > k×std
MUTATION_PP = 20.0                # 突变档: 单日 |Δ| > 20pp(percentage points)
MIN_SAMPLES = 5                   # 窗口样本下限(不足跳过突变检测)
MIN_N = 20                        # 样本门: n<20 的模式不参与突变告警(小样本噪声大)
LAG_ALERT_TD = 2                  # 停滞档: max_signal_date 落后 ≥2 个交易日告警
DEDUP_WINDOW = 86400              # dedup 防抖窗口(24h)
LOG_TAG = "[sigkelly_snapshot]"


def log(msg: str) -> None:
    print(f"{LOG_TAG} {msg}", flush=True)


def _resolve_ro_frame(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = DEFAULT_DATA_DIR / path
    return path


def load_backtest(data_dir: Path) -> dict:
    p = data_dir / "signal_kelly_backtest.json"
    if not p.exists():
        raise FileNotFoundError(f"回测产物不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def load_trades(data_dir: Path) -> dict:
    p = data_dir / "signal_kelly_trades.json"
    if not p.exists():
        raise FileNotFoundError(f"交易记录不存在: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


KEY_METRICS = ("n", "win_rate", "pl_ratio", "mean_return", "total_return",
               "annualized_return")


def extract_quadrant_subset(quadrants: dict) -> dict:
    """16 象限 × 5 周期 × 10 模式 → key metric subset。"""
    out = {}
    for qname, qobj in quadrants.items():
        periods = qobj.get("periods", {}) if isinstance(qobj, dict) else {}
        qsub = {}
        for pname, pmodes in periods.items():
            if not isinstance(pmodes, dict):
                continue
            psub = {}
            for mode, mdata in pmodes.items():
                if not isinstance(mdata, dict):
                    continue
                psub[mode] = {k: mdata.get(k) for k in KEY_METRICS}
            qsub[pname] = psub
        out[qname] = qsub
    return out


def scan_trades(trades: dict) -> tuple[str, list]:
    """全象限成交里找 max_signal_date + 最近 10 笔(按 signal_date 降序)。
    trades.quadrants = {qname: {mode: [compact_trade_array, ...]}};
    compact_trade[0] = signal_date。返回 (max_signal_date, recent10)。
    """
    fields = trades.get("fields", [])
    qs = trades.get("quadrants", {})
    max_date = ""
    recent: list[list] = []
    for qname, modes in qs.items():
        for mode, trades_list in modes.items():
            if not isinstance(trades_list, list):
                continue
            for tr in trades_list:
                if not isinstance(tr, dict):  # compact 数组第一元素是 signal_date
                    sd = tr[0] if tr else ""
                else:
                    sd = tr.get("signal_date") or tr.get("date") or ""
                if not sd:
                    continue
                if sd > max_date:
                    max_date = sd
                recent.append(tr)
    # 最近 10 笔: 按 signal_date 降序, compact 优先
    def _sd(t) -> str:
        if isinstance(t, dict):
            return t.get("signal_date") or t.get("date") or ""
        return t[0] if t else ""

    recent.sort(key=_sd, reverse=True)
    return max_date, recent[:10]


def build_snapshot(data_dir: Path) -> dict:
    bt = load_backtest(data_dir)
    trades = load_trades(data_dir)
    quadrants = bt.get("quadrants", {})
    max_signal_date, recent10 = scan_trades(trades)
    snapshot = {
        "date": datetime.now().strftime("%Y%m%d"),
        "generated_at": bt.get("generated_at"),
        "version": SNAPSHOT_VERSION,
        "max_signal_date": max_signal_date or "",
        "quadrants": extract_quadrant_subset(quadrants),
        "recent_trades": {
            "fields": [f for f in trades.get("fields", [])],
            "trades": recent10,
        },
    }
    return snapshot


def snap_dir(data_dir: Path) -> Path:
    d = data_dir / "signal_kelly_snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_index(data_dir: Path) -> dict:
    p = snap_dir(data_dir) / "index.json"
    if not p.exists():
        return {"version": "", "updated_at": "", "days": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_index(data_dir: Path, index: dict) -> None:
    p = snap_dir(data_dir) / "index.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)


def save_snapshot(data_dir: Path, snapshot: dict) -> None:
    d = snap_dir(data_dir)
    p = d / f"{snapshot['date']}.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)


def append_to_index(index: dict, snapshot: dict) -> None:
    """把今日快照压成迷你演进行(每模式 all 周期 total_return/n), 去重覆盖同日。"""
    day_row = {"d": snapshot["date"], "m": snapshot["max_signal_date"],
               "v": snapshot["version"], "modes": {}}
    quadrants = snapshot.get("quadrants", {})
    for qname, periods in quadrants.items():
        all_p = periods.get("all", {})
        if not isinstance(all_p, dict):
            continue
        for mode, mdata in all_p.items():
            if not isinstance(mdata, dict):
                continue
            day_row["modes"].setdefault(mode, {})
            day_row["modes"][mode]["tr"] = mdata.get("total_return")
            day_row["modes"][mode]["n"] = mdata.get("n")
    days = index.get("days", [])
    # 去重: 同日覆盖
    for i, row in enumerate(days):
        if row.get("d") == snapshot["date"]:
            days[i] = day_row
            break
    else:
        days.append(day_row)
    days.sort(key=lambda r: r.get("d", ""))
    index["days"] = days
    index["version"] = SNAPSHOT_VERSION
    index["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def trading_days_lag(end_date: str, start_date: str) -> int:
    """交易日 lag = len(trading_days_between(start, end)) - 1。无数据返回 -1。"""
    try:
        sys.path.insert(0, str(ROOT))
        from app.calendar import trading_days_between
        days = trading_days_between(start_date, end_date)
        return max(len(days) - 1, 0) if days else -1
    except Exception as e:  # noqa: BLE001
        log(f"交易日计算失败(按自然日退化): {e}")
        try:
            d0 = datetime.strptime(end_date, "%Y%m%d")
            d1 = datetime.strptime(start_date, "%Y%m%d")
            return max((d0 - d1).days - 1, 0)
        except Exception:  # noqa: BLE001
            return -1


def _send_notify(subject: str, body: str, severe: bool, dry_run: bool,
                 dedup_key: str | None = None) -> None:
    import notify
    if dedup_key and not dry_run and notify.check_dedup(dedup_key, DEDUP_WINDOW):
        log(f"[dedup] suppress {dedup_key}(24h 内已告警)")
        return
    res = notify.send(subject, body, severe=severe, dry_run=dry_run)
    if dedup_key and not dry_run:
        ok = res and any(res.values())
        if ok:
            notify.update_dedup(dedup_key)


def detect_stagnation(index: dict, today_str: str) -> list[dict]:
    """停滞档: max_signal_date 落后最新交易日 ≥LAG_ALERT_TD 个交易日。"""
    days = index.get("days", [])
    if not days:
        return []
    newest = days[-1]["m"]
    if not newest:
        return [{"type": "stagnation", "detail": "max_signal_date 为空(产物异常)"}]
    lag = trading_days_lag(today_str, newest)
    if lag >= LAG_ALERT_TD:
        return [{"type": "stagnation", "detail": f"max_signal_date={newest} "
                f"落后今日{lag}个交易日(≥{LAG_ALERT_TD}告警)"}]
    return []


def detect_mutation(index: dict) -> list[dict]:
    """突变档: 今日 vs 滚动窗口(近 60 日, 含昨天不含今天)。"""
    days = index.get("days", [])
    if len(days) < 2:
        return []
    latest = days[-1]
    prevs = days[1 - ROLLING_WINDOW - 1:-1]  # 昨天及其前 59 日(不含今天)
    if not prevs:
        return []
    prev1 = prevs[-1]
    prev2 = prevs[-2] if len(prevs) >= 2 else None
    today_modes = latest.get("modes", {})
    alerts = []
    for mode, mdata in today_modes.items():
        today_tr = mdata.get("tr")
        today_n = mdata.get("n") or 0
        if today_tr is None or today_n < MIN_N:
            continue
        wins = [p["modes"][mode]["tr"] for p in prevs
                if isinstance(p.get("modes", {}).get(mode), dict)
                and isinstance(p["modes"][mode].get("tr"), (int, float))]
        if len(wins) < MIN_SAMPLES:
            continue
        mean = statistics.mean(wins)
        if len(wins) >= 2:
            std = statistics.stdev(wins)
        else:
            std = 0.0
        std_jump = std > 0 and abs(today_tr - mean) > MUTATION_STD * std
        day_delta = today_tr - prev1["modes"][mode]["tr"] if isinstance(
            prev1.get("modes", {}).get(mode), dict
        ) and isinstance(prev1["modes"][mode].get("tr"), (int, float)) else 0.0
        pp_jump = abs(day_delta) > MUTATION_PP
        dir_confirmed = False
        if prev2 is not None and isinstance(prev2.get("modes", {}).get(mode), dict) \
                and isinstance(prev2["modes"][mode].get("tr"), (int, float)):
            prev_delta = prev1["modes"][mode]["tr"] - prev2["modes"][mode]["tr"]
            if (day_delta > 0 and prev_delta > MUTATION_PP) or \
               (day_delta < 0 and prev_delta < -MUTATION_PP):
                dir_confirmed = True
        if (std_jump and pp_jump) or (pp_jump and dir_confirmed) or \
                (std_jump and abs(day_delta) > MUTATION_PP * 0.5):
            alerts.append({
                "type": "mutation", "mode": mode, "n": today_n,
                "today_tr": round(today_tr, 2), "mean": round(mean, 2),
                "std": round(std, 2) if std else 0,
                "day_delta": round(day_delta, 2),
                "detail": f"[{mode}] 今日 total_return={today_tr:.2f}, "
                          f"窗口均值={mean:.2f}, std={std:.2f}, 单日Δ={day_delta:+.2f}pp",
            })
    return alerts


def run_check(data_dir: Path, dry_run: bool) -> int:
    index = load_index(data_dir)
    days = index.get("days", [])
    if not days:
        log("index.json 无历史快照, 跳过告警检测")
        return 0
    today_str = datetime.now().strftime("%Y%m%d")
    alerts = []
    alerts += detect_stagnation(index, today_str)
    # 发布日豁免: 今日 version != 昨日 version
    prev_ver = index.get("days", [])[-2].get("v") if len(index.get("days", [])) >= 2 else ""
    latest_ver = index.get("days", [])[-1].get("v") if index.get("days", []) else ""
    if prev_ver and latest_ver and prev_ver != latest_ver:
        log("发布日(version 变化), 豁免突变告警")
    else:
        alerts += detect_mutation(index)
    if not alerts:
        log(f"告警检测通过: 最新快照天={days[-1].get('d')} "
            f"max_signal_date={days[-1].get('m')}")
        return 0
    for a in alerts:
        subject = "[告警] 信号凯利回测停滞" if a["type"] == "stagnation" else "[告警] 信号凯利回测指标突变"
        body_lines = [
            subject,
            f"判定档位: {a['type']}",
            a.get("detail", ""),
            f"数据截止日: {days[-1].get('d')} 快照 / max_signal_date={days[-1].get('m')}",
        ]
        if a["type"] == "mutation":
            body_lines.append(f"样本数 n={a.get('n')} (门 ≥{MIN_N})")
            body_lines.append("影响面提示: 回测 total_return 突变可能源于价格库数据缺口"
                              "(如 accum_nav 未补致信号跳单) 或真实市场风格切换, "
                              "建议查 check_data_integrity 信号滞后告警 + 最近 3 日成交明细。")
        body_lines.append("发版豁免: 今日为发布日则本突变告警属预期(已跳过突变检测)。")
        body = "\n".join(body_lines)
        dedup_key = f"sigkelly_snapshot_{a['type']}_{a.get('mode', '')}_{days[-1]['d']}"
        if dry_run:
            log(f"[dry-run] 将发告警: {subject} | {a.get('detail', '')}")
        else:
            _send_notify(subject, body, severe=(a["type"] == "mutation"),
                         dry_run=dry_run, dedup_key=dedup_key)
    return 1


def _main() -> int:
    ap = argparse.ArgumentParser(description="信号凯利回测快照/演进/告警")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                    help="回测产物所在 data 目录(默认 static-site/data)")
    ap.add_argument("--check", action="store_true",
                    help="只读告警检测模式(读 index.json, 不生成快照)")
    ap.add_argument("--dry-run", action="store_true", help="不写文件/不发通知")
    args = ap.parse_args()
    data_dir = _resolve_ro_frame(args.data_dir)
    if args.check:
        return run_check(data_dir, args.dry_run)
    index = load_index(data_dir)
    snapshot = build_snapshot(data_dir)
    if args.dry_run:
        log(f"[dry-run] 快照 date={snapshot['date']} "
            f"max_signal_date={snapshot['max_signal_date']} "
            f"quadrants={len(snapshot['quadrants'])}")
        return 0
    prev_max = index["days"][-1]["m"] if index["days"] else ""
    # 回测失败门(回退): max_signal_date 比昨日倒退 → SEVERE
    if prev_max and snapshot["max_signal_date"] and snapshot["max_signal_date"] < prev_max:
        subject = "[告警] 信号凯利回测 max_signal_date 倒退"
        body = (f"{subject}\n判定档位: 回测失败门(SEVERE)\n"
                f"昨日 {prev_max} → 今日 {snapshot['max_signal_date']}\n"
                f"回测产物可能损坏/数据源缺日, 建议查 export 日志与 accum_nav。")
        if not args.dry_run:
            _send_notify(subject, body, severe=True, dry_run=False,
                         dedup_key=f"sigkelly_snapshot_regress_{snapshot['date']}")
    save_snapshot(data_dir, snapshot)
    append_to_index(index, snapshot)
    save_index(data_dir, index)
    log(f"快照已生成: {snap_dir(data_dir) / (snapshot['date'] + '.json')}")
    log(f"index 共 {len(index['days'])} 个快照日, max_signal_date={snapshot['max_signal_date']}")
    return 0


def main() -> int:
    """入口。退出码语义(供调用方/backfill_metrics.sh 区分):
        0 = --check 无告警 / 快照生成成功
        1 = --check 检测到预期告警(停滞/突变, 正常路径, 非脚本错误)
        2 = 脚本异常(非预期崩溃, 如产物缺失/读取失败), 与"有告警"区分
    """
    try:
        return _main()
    except Exception as _e:  # noqa: BLE001
        log(f"脚本异常(非预期, 退出码 2): {_e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())