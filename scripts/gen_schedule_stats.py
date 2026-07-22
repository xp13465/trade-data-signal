#!/usr/bin/env python3
# gen_schedule_stats.py - 解析 data/logs/*_launchd.log 统计各计划任务执行情况
#
# 输出 static-site/data/schedule_stats.json，前端"数据更新规则"弹窗读取展示
# "预估耗时"(近10次有效平均) + "最后执行"(最近一次开始时间+退出码) 两列。
#
# 由 scripts/deploy.sh 在 export.py 后调用（部署时刷新，deploy 锁内安全，省去改各任务脚本）。
#
# 日志格式（标准 .sh 任务，跨天 append 累积）:
#   === update_all.sh 开始 2026-07-15 17:50:06 ===
#   === update_all.sh 结束 2026-07-15 18:06:01 ===              # update_all 无退出码
#   === update_all.sh 结束（非交易日）2026-07-11 15:33:19 ===   # 非交易日变体
#   === intraday_snapshot.sh 结束 2026-07-15 15:35:36 退出码=0 ===
#   === lhb_backfill.sh 结束 2026-07-15 18:30:45 deploy=0 ===   # lhb 带 deploy=
# etf_nt 任务日志格式不同:
#   [etf_nt] daily 开始 2026-07-15 20:07:05
#   [etf_nt] daily 完成 68.4s: ohlc=72 ...                       # 完成行无时间戳，耗时直接给出
#
# 配对：开始后紧接的结束算一次运行；耗时>3h 视为错位丢弃。只匹配外层任务脚本名，
# 内嵌的 deploy.sh/check_signals.sh 不计（避免嵌套干扰）。
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent  # 不用 .resolve()：trade-data/scripts 是 trade/scripts 的 symlink，resolve() 会跳回 trade 导致读旧日志。保留 symlink 路径让 REPO=实际调用方(trade-data)
LOG_DIR = REPO / "data" / "logs"
OUT = REPO / "static-site" / "data" / "schedule_stats.json"
MAX_GAP_SEC = 3 * 3600  # >3h 视为错位，丢弃

# 外层脚本名只匹配任务自身，内嵌 deploy.sh/check_signals.sh 不会误配
TASKS = [
    {"task": "update_all", "name": "收盘全量", "script": "update_all.sh",
     "schedule": "17:50", "log": "update_all_launchd.log", "mode": "standard"},
    {"task": "backfill_evening", "name": "指数补采兜底", "script": r"backfill_(indices|metrics)\.sh",
     "schedule": "16:35 / 20:00 / 02:00", "log": "backfill_evening_launchd.log", "mode": "standard"},
    {"task": "intraday_snapshot", "name": "盘中快照", "script": "intraday_snapshot.sh",
     "schedule": "盘中 09:35-15:35", "log": "intraday_snapshot_launchd.log", "mode": "standard"},
    {"task": "futures_backfill", "name": "期货机构持仓", "script": "futures_backfill.sh",
     "schedule": "20:05 + 21:00(兜底)", "log": "futures_backfill_launchd.log", "mode": "standard"},
    {"task": "lhb_backfill", "name": "龙虎榜", "script": "lhb_backfill.sh",
     "schedule": "18:30 + 19:30(兜底)", "log": "lhb_backfill_launchd.log", "mode": "standard"},
    {"task": "rzhb_backfill", "name": "两融", "script": "rzhb_backfill.sh",
     "schedule": "23:00", "log": "rzhb_backfill_launchd.log", "mode": "standard"},
    {"task": "etf_national_team", "name": "ETF国家队", "script": "etf_nt",
     "schedule": "20:07 + 21:30(兜底)", "log": "etf_national_team_launchd.log", "mode": "etf_nt"},
]

_TS = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
# 开始:=== xxx.sh 开始 <ts> ===
START_RE = re.compile(r'=== (\S+\.sh) 开始 ' + _TS + r' ===')
# 结束:=== xxx.sh 结束 [(非交易日)] <ts> [退出码=N | deploy=N] ===  (退出码可选)
END_RE = re.compile(r'=== (\S+\.sh) 结束.*?' + _TS + r'(?:.*?退出码=(\d+))?')
# etf_nt
ETF_START_RE = re.compile(r'\[etf_nt\] daily 开始 ' + _TS)
ETF_DONE_RE = re.compile(r'\[etf_nt\] daily 完成 (\d+\.?\d*)s')


def _iter_lines(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def parse_standard(path: Path, script: str):
    """标准 .sh 任务:返回 (pairs, pending_start)
    pairs=[(start_dt, end_dt, exit_code, duration_sec), ...]
    pending_start=进行中任务的 start_dt(有 start 无 end),用于 last_run 显示"进行中"
    (exit_code=null/duration=null),根治 intraday_snapshot.sh 在 push 前调本脚本时
    日志只有开始行无结束行致 last_run 停留昨天的时序竞态。
    """
    starts, ends = [], []
    for line in _iter_lines(path):
        m = START_RE.search(line)
        if m and re.fullmatch(script, m.group(1)):
            starts.append(datetime.strptime(m.group(2), "%Y-%m-%d %H:%M:%S"))
            continue
        m = END_RE.search(line)
        if m and re.fullmatch(script, m.group(1)):
            ts = datetime.strptime(m.group(2), "%Y-%m-%d %H:%M:%S")
            code = int(m.group(3)) if m.group(3) is not None else 0
            ends.append((ts, code))
    # 双指针配对:每个 start 找首个未消耗的 end>=start 且 gap<=3h
    pairs, ei, pending_start = [], 0, None
    for s in starts:
        while ei < len(ends) and ends[ei][0] < s:
            ei += 1  # 跳过早于该 start 的孤儿 end
        if ei >= len(ends):
            pending_start = s  # 记录进行中的 start(有 start 无 end),break 退出
            break
        e_ts, e_code = ends[ei]
        dur = (e_ts - s).total_seconds()
        if 0 <= dur <= MAX_GAP_SEC:
            pairs.append((s, e_ts, e_code, dur))
            ei += 1
        # dur>MAX_GAP_SEC:错位，丢弃该 start 不配对（不消耗 end）
    return pairs, pending_start


def parse_etf_nt(path: Path):
    """etf_nt:完成行无时间戳，耗时直接给出。last_run 用开始时间。
    返回 (pairs, pending_start)，pending_start=开始但未完成的进行中任务。
    """
    pairs, pending = [], None
    for line in _iter_lines(path):
        m = ETF_START_RE.search(line)
        if m:
            pending = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            continue
        m = ETF_DONE_RE.search(line)
        if m and pending is not None:
            dur = float(m.group(1))
            pairs.append((pending, pending, 0, dur))  # end=start(无结束ts), exit=0
            pending = None
    return pairs, pending


def est_text(pairs):
    """近10次有效平均: <60s 显'约N秒', ≥60s 显'约N分钟'"""
    durs = [p[3] for p in pairs][-10:]
    if not durs:
        return "—"
    avg = sum(durs) / len(durs)
    if avg < 60:
        return f"约{round(avg)}秒"
    return f"约{round(avg / 60)}分钟"


def build():
    result = []
    for t in TASKS:
        log_path = LOG_DIR / t["log"]
        if not log_path.exists():
            result.append({**{k: t[k] for k in ("task", "name", "schedule")},
                           "est_text": "—", "last_run": None, "last_exit": None,
                           "last_duration_sec": None})
            continue
        if t["mode"] == "etf_nt":
            pairs, pending_start = parse_etf_nt(log_path)
        else:
            pairs, pending_start = parse_standard(log_path, t["script"])
        last_run, code, last_dur = None, None, None
        if pairs:
            s, e, code, dur = pairs[-1]
            last_run = s.strftime("%Y-%m-%d %H:%M")
            last_dur = round(dur)
        # 进行中任务(有 start 无 end):若比最近配对更晚,覆盖为"进行中"
        # exit_code/duration 留 null,前端 last_exit=null 不显示 ⚠️(任务还在跑或异常退出)
        if pending_start is not None:
            if last_run is None or pending_start > pairs[-1][0]:
                last_run = pending_start.strftime("%Y-%m-%d %H:%M")
                code = None
                last_dur = None
        result.append({
            "task": t["task"], "name": t["name"], "schedule": t["schedule"],
            "est_text": est_text(pairs), "last_run": last_run,
            "last_exit": code, "last_duration_sec": last_dur,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {OUT.relative_to(REPO)} ({len(result)} tasks)")
    for r in result:
        print(f"  {r['name']:8s} {r['schedule']:22s} est={r['est_text']:8s} "
              f"last={r['last_run']} exit={r['last_exit']} dur={r['last_duration_sec']}s")
    return result


if __name__ == "__main__":
    build()
