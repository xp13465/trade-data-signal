#!/usr/bin/env python3
"""#240② 方向感知判定: 用今日(2026-10-09)真实巡检集合序列做「改造前→改造后」对照仿真。

static-only: 只 import 纯函数模块, 不执行任何生产脚本/网络/通知。
数据来源: 云上 schedule_monitor_launchd.log 逐轮 CHECK_FAILED_UNITS_FAIL 集合(已字节安全重建)。
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import alert_denoise_rules as adr  # noqa: E402

P = "trade-"
S = ".service"
# 今日(2026-10-09)集合**变更**序列(变更点; 中间轮集合不变)。成员按 systemctl 名序。
SEQ = [
    ("2026-10-09 00:00", ["etf-national-team", "fapi-daily", "futures-backfill",
                          "kelly-intraday-rerun", "lhb-backfill", "public-fund-daily", "r2-consistency"]),
    ("2026-10-09 08:15", ["etf-national-team", "fapi-daily", "futures-backfill",
                          "kelly-intraday-rerun", "lhb-backfill", "public-fund-daily"]),
    ("2026-10-09 09:30", ["etf-national-team", "fapi-daily", "futures-backfill",
                          "lhb-backfill", "nextday-gap-check", "public-fund-daily", "r2-consistency"]),
    ("2026-10-09 16:15", ["etf-national-team", "fapi-daily", "futures-backfill",
                          "lhb-backfill", "nextday-gap-check", "r2-consistency"]),
    ("2026-10-09 16:30", ["etf-national-team", "fapi-daily", "futures-backfill",
                          "lhb-backfill", "nextday-gap-check", "public-fund-daily", "r2-consistency"]),
    ("2026-10-09 16:45", ["etf-national-team", "fapi-daily", "futures-backfill",
                          "lhb-backfill", "nextday-gap-check", "r2-consistency"]),
    ("2026-10-09 18:00", ["etf-national-team", "futures-backfill",
                          "lhb-backfill", "nextday-gap-check", "r2-consistency"]),
    ("2026-10-09 18:15", ["etf-national-team", "futures-backfill",
                          "nextday-gap-check", "r2-consistency"]),
    ("2026-10-09 20:00", ["nextday-gap-check", "r2-consistency"]),
]


def members_to_problem(ms):
    return "云上 failed unit: " + ", ".join(P + m + S for m in ms)


def sig_of(ms):
    return adr.failed_units_signature([members_to_problem(ms)])


def old_judge(state, sig, today):
    """改造前逻辑(#240 原始, alert_denoise_rules.py:111-127 语义)。"""
    if not sig:
        return False, "empty"
    if state.get("signature") != sig:
        return True, "changed"
    if state.get("last_alert_date") != today:
        return True, "daily-first"
    return False, "same-set-same-day"


def run(judge_new):
    """state 初值 = 昨夜(10-08)收尾集合(与 00:00 同集合), last_alert_date=10-08。"""
    init_items = [P + m + S for m in SEQ[0][1]]
    state = {"signature": sig_of(SEQ[0][1]), "prev_signature": sig_of(SEQ[0][1]),
             "items": init_items, "last_alert_date": "2026-10-08",
             "last_added_signature": "", "last_added_at": ""}
    sends, rows = 0, []
    for ts, ms in SEQ:
        today = ts[:10]
        now = datetime.strptime(ts, "%Y-%m-%d %H:%M")
        sig = sig_of(ms)
        ident = [P + m + S for m in ms]
        if judge_new:
            send, reason = adr.failed_units_daily_judge(state, sig, ident, today, now)
        else:
            send, reason = old_judge(state, sig, today)
        if send:
            sends += 1
        rows.append((ts, len(ms), reason, "SEND" if send else "silent"))
        # 复刻 check_failed_units._write_sig_state 的状态流转
        new = {"signature": sig if send else state["signature"],
               "prev_signature": sig, "items": ident,
               "last_alert_date": today if send else state["last_alert_date"],
               "last_added_signature": state["last_added_signature"],
               "last_added_at": state["last_added_at"]}
        if send and reason in ("added", "changed"):
            new["last_added_signature"] = sig
            new["last_added_at"] = ts + ":00"
        state = new
    return sends, rows


for label, is_new in (("改造前(#240 对称 changed)", False), ("改造后(方向感知 added/shrunk)", True)):
    n, rows = run(is_new)
    print(f"\n=== {label} ===  发送条数 = {n}")
    for ts, cnt, reason, act in rows:
        print(f"  {ts}  n={cnt}  reason={reason:<18} {act}")