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
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent  # 不用 .resolve()：trade-data/scripts 是 trade/scripts 的 symlink，resolve() 会跳回 trade 导致读旧日志。保留 symlink 路径让 REPO=实际调用方(trade-data)
LOG_DIR = REPO / "data" / "logs"
OUT = REPO / "static-site" / "data" / "schedule_stats.json"
MAX_GAP_SEC = 3 * 3600  # >3h 视为错位，丢弃
# Bug1 修复(2026-08-15): pending_crash_retry 判定用时间间隔隔离历史残留码。
# 只有"上一轮配对运行 crash(exit!=0) 且距本 pending_start < CRASH_RETRY_GAP_SEC"
# (同一调度时槽/crash 后 6h 内立刻重启=真重试)才算，跨天残留(如 8/12 deploy=1 污染 8/13)
# 不关联本 pending,不再误报。
CRASH_RETRY_GAP_SEC = 6 * 3600

# 外层脚本名只匹配任务自身，内嵌 deploy.sh/check_signals.sh 不会误配
TASKS = [
    {"task": "update_all", "name": "收盘全量", "script": "update_all.sh",
     "schedule": "17:50", "log": "update_all_launchd.log", "mode": "standard"},
    {"task": "backfill_evening", "name": "指数补采兜底", "script": r"backfill_(indices|metrics)\.sh",
     "schedule": "16:35 / 21:00 / 02:00", "log": "backfill_evening_launchd.log", "mode": "standard"},
    {"task": "intraday_snapshot", "name": "盘中快照", "script": "intraday_snapshot.sh",
     "schedule": "盘中 09:35-15:35", "log": "intraday_snapshot_launchd.log", "mode": "standard"},
    {"task": "futures_backfill", "name": "期货机构持仓", "script": "futures_backfill.sh",
     "schedule": "20:05 + 21:00(兜底)", "log": "futures_backfill_launchd.log", "mode": "standard"},
    {"task": "lhb_backfill", "name": "龙虎榜", "script": "lhb_backfill.sh",
     "schedule": "18:30 + 19:30(兜底)", "log": "lhb_backfill_launchd.log", "mode": "standard"},
    {"task": "rzhb_backfill", "name": "两融", "script": "rzhb_backfill.sh",
     "schedule": "T+1 08:00", "log": "rzhb_backfill_launchd.log", "mode": "standard"},
    # us_stock_morning: 2026-07-29 新增美股早采 05:00(commit 4425366c schedule_monitor已加监控，
    # 此处补齐 gen_schedule_stats 漏同步)。日志格式标准 .sh 开始/结束，mode=standard 可解析。
    {"task": "us_stock_morning", "name": "美股早采", "script": "us_stock_morning.sh",
     "schedule": "05:00", "log": "us_stock_morning_launchd.log", "mode": "standard"},
    {"task": "etf_national_team", "name": "ETF汪汪队", "script": "etf_nt",
     "schedule": "20:07 + 21:30(兜底)", "log": "etf_national_team_launchd.log", "mode": "etf_nt"},
    # lab-auto: 2026-07-23 补入监控范围。launchd com.trade.lab-auto 19:00 跑 update_lab.sh
    # (策略实验室全量回测+上传 R2)。日志格式标准 .sh 开始/结束(结束带"耗时 Ns"后缀，
    # END_RE 的 .*? 可吃掉，退出码组 None 默认 0)。schedule_monitor.sh 已先一步收录 lab_auto
    # (硬编码 TASKS L43-61)，但前端 schedule_stats.json 仍漏显示，此处补齐。
    {"task": "lab_auto", "name": "策略实验室", "script": "update_lab.sh",
     "schedule": "19:00", "log": "update_lab_launchd.log", "mode": "standard"},
]

_TS = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
# 开始:=== xxx.sh 开始 <ts> ===
START_RE = re.compile(r'=== (\S+\.sh) 开始 ' + _TS + r' ===')
# 结束:=== xxx.sh 结束 [(非交易日)] <ts> [退出码=N | deploy=N] ===  (退出码可选)
END_RE = re.compile(r'=== (\S+\.sh) 结束.*?' + _TS + r'(?:.*?退出码=(\d+))?')
# etf_nt
ETF_START_RE = re.compile(r'\[etf_nt\] daily 开始 ' + _TS)
# 2026-07-25: 兼容 collector crash 的 fallback "失败 exit=N" 行
# (collector 撞 libmini_racer FATAL 等不写 "完成" 行, shell 脚本补 "失败 exit=N",
#  否则 gen_stats 启发式标 143 假 SIGTERM, 与 shell 正常结束矛盾)
ETF_DONE_RE = re.compile(r'\[etf_nt\] daily (完成|失败)(?:\s+(\d+\.?\d*)s)?(?:.*?exit=(\d+))?')

# P0 稳定性(2026-07-20): task -> launchctl label 映射，用于 launchctl_last_exit 读真实退出码
# 消除 pending_start 启发式 143(假 SIGTERM)漏报/误报：崩在结束行前的任务，
# launchd 仍记录真实 last exit code，比日志启发式准。
LABEL_MAP = {
    "update_all": "com.trade.update-all",
    "backfill_evening": "com.trade.backfill-evening",
    "intraday_snapshot": "com.trade.intraday-snapshot",
    "futures_backfill": "com.trade.futures-backfill",
    "lhb_backfill": "com.trade.lhb-backfill",
    "rzhb_backfill": "com.trade.rzhb-backfill",
    "us_stock_morning": "com.trade.us-stock-morning",
    "etf_national_team": "com.trade.etf-national-team",
    "lab_auto": "com.trade.lab-auto",
}

# launchctl print "last exit code = N" 行（N 可为 143/0/1/None，None 显 "last exit code = (none)"）
_LAUNCHCTL_LAST_EXIT_RE = re.compile(r'last exit code = \(?(-?\d+|none)\)?', re.IGNORECASE)

# 第4盲区修复(2026-07-27): log 异常关键词扫描
# 根因: intraday_snapshot.py _export_affected_json 抛 AttributeError 被 try/except 吞,
# 脚本 exit=0,监控只看 exit code 漏报 3 天。log 里有 Traceback/异常类名痕迹,
# 关键词扫描能抓到。
# 关键词设计原则: 精确匹配,避免"失败""Error"宽泛误报:
#   - Python Traceback 标志行(每次未捕获异常必带)
#   - Python 异常类名 + 冒号(标准打印格式 "ExceptionName: msg"),
#     \b 词边界 + \s*: 确保 "Exception handler" 等正常文本不误配
#   - 系统级致命错误(FATAL/panic/segfault/core dumped,libmini_racer crash 场景)
#   - bash/git 明确失败标志(精确字符串,非泛化"失败")
ANOMALY_RE = re.compile(
    r'Traceback \(most recent call last\)'
    r'|\b(?:AttributeError|TypeError|ValueError|KeyError|IndexError|ImportError|'
    r'ModuleNotFoundError|NameError|SyntaxError|RuntimeError|StopIteration|'
    r'ZeroDivisionError|RecursionError|FileNotFoundError|PermissionError|'
    r'OSError|IOError|NotImplementedError|OverflowError|MemoryError|SystemError|'
    r'UnicodeError|UnicodeDecodeError|UnicodeEncodeError|ConnectionError|TimeoutError|'
    r'JSONDecodeError|Exception)\s*:'
    r'|FATAL\b|panic:|Segmentation fault|core dumped'
)

# 第4盲区修复补丁(2026-07-29): push 失败类关键词单独处理,避免 deploy.sh 内置
# fetch+rebase+重试机制自愈后仍误报。
# 根因: deploy.sh push 失败 -> rebase origin/main -> 重试 push 成功 打
#   "✓ rebase + 重试 push 成功"(deploy.sh L288)或"✓ push 成功"(L303)。
#   旧逻辑 ANOMALY_RE 含 "error: failed to push" 命中即报,不认后续成功标记,
#   致 lab_auto 7-28 19:02 自愈后仍 log_anomaly=True 误报 active 至今。
# 修复: push 失败命中后,若同窗口出现成功标记,判已恢复不报;无成功标记才报真实失败。
# (futures_backfill 7-28 21:00 rebase abort 无成功标记,仍报 True=正确)
PUSH_FAIL_RE = re.compile(
    r'error: failed to push'
    r'|error: cannot rebase'
    r'|!\s*\[remote rejected\]'
)
# deploy.sh / update_lab.sh 的 push 成功标记(同运行窗口出现即判 push 失败已恢复)
PUSH_SUCCESS_RE = re.compile(
    r'✓ rebase \+ 重试 push 成功'
    r'|✓ push 成功'
    r'|✓ git push'
    r'|视为幂等成功'
)


def launchctl_last_exit(label: str | None) -> int | None:
    """调 `launchctl print gui/UID/label` 读真实 last exit code。

    返回 int 退出码（0=成功，非0=失败如 143=SIGTERM 超时被杀，1=脚本异常）。
    label 为 None/空、launchctl 调用失败、解析不到、或值为 "none"（任务从没跑过）时返回 None。

    用途：pending_start（有 start 无 end，崩在结束行前）时，日志启发式只能 age>3h 猜 143，
    launchctl 记录真实退出码（含 SIGTERM=143 / 脚本异常 exit=1 / 正常 exit=0），
    优先用真实码消除漏报（exit=1 漏报为 None）和误报（exit=0 误报为 143）。
    """
    if not label:
        return None
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    m = _LAUNCHCTL_LAST_EXIT_RE.search(result.stdout)
    if not m:
        return None
    val = m.group(1).lower()
    if val == "none":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def scan_log_anomaly(log_path: Path, script: str, mode: str) -> dict | None:
    """扫描 log 文件最近一次运行窗口内的异常关键词(第4盲区修复)。

    根因场景: intraday_snapshot.py 的 _export_affected_json 抛 AttributeError 被
    try/except 吞掉,脚本仍 exit=0,监控只看 exit code 漏报 3 天。log 里有
    Traceback/异常类名痕迹,关键词扫描能抓到。

    切窗口方式(避免历史 Error 误报): 找最后一个 start 行行号 -> 找其后第一个
    end 行行号 -> 扫 [start_line, end_line) 之间所有行。只扫本次运行时段的 log,
    不依赖行内时间戳(中间过程行多无时间戳,靠 start/end 标记切窗口最稳)。
    若无 end(进行中或被 SIGTERM 杀),扫到文件末尾(本次运行的所有输出)。

    Args:
        log_path: log 文件路径
        script: standard 模式的脚本名 regex(如 "intraday_snapshot.sh")
        mode: "standard" 或 "etf_nt"

    Returns:
        {"keyword": "AttributeError", "line": "AttributeError: '...' ..."} 或 None。
        line 截断到 200 字符避免 JSON 过大;keyword 为正则命中的字符串。
    """
    if not log_path.exists():
        return None
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None

    # 找最后一个 start 行(standard 用 START_RE+fullmatch script, etf_nt 用 ETF_START_RE)
    last_start_idx = None
    if mode == "etf_nt":
        for i in range(len(lines) - 1, -1, -1):
            if ETF_START_RE.search(lines[i]):
                last_start_idx = i
                break
    else:
        for i in range(len(lines) - 1, -1, -1):
            m = START_RE.search(lines[i])
            if m and re.fullmatch(script, m.group(1)):
                last_start_idx = i
                break
    if last_start_idx is None:
        return None  # log 里无 start 行,无法切窗口

    # 找 start 后第一个 end 行(限定本次运行窗口,避免扫到下一轮 start 之间)
    # 若无 end(进行中或被杀),扫到文件末尾
    end_idx = len(lines)
    if mode == "etf_nt":
        for i in range(last_start_idx + 1, len(lines)):
            if ETF_DONE_RE.search(lines[i]):
                end_idx = i + 1
                break
    else:
        for i in range(last_start_idx + 1, len(lines)):
            m = END_RE.search(lines[i])
            if m and re.fullmatch(script, m.group(1)):
                end_idx = i + 1
                break

    # 扫描 [last_start_idx, end_idx) 之间所有行,返回首个命中
    # 2026-07-29 修复: push 失败类(error: failed to push / error: cannot rebase /
    #   ! [remote rejected]) 特殊处理--deploy.sh 内置 fetch+rebase+重试机制,
    #   push 失败后 rebase 重试成功会打 "✓ rebase + 重试 push 成功" / "✓ push 成功"
    #   等标记。若同窗口出现成功标记,判已恢复不报;无成功标记才报真实失败。
    #   其他关键词(Traceback/异常类名/FATAL)逻辑不变,命中即报。
    window_lines = lines[last_start_idx:end_idx]
    has_push_success = any(PUSH_SUCCESS_RE.search(l) for l in window_lines)
    for i in range(last_start_idx, end_idx):
        # 优先扫非 push 失败类异常(Traceback/异常类名/FATAL):命中即报,不抑制
        m = ANOMALY_RE.search(lines[i])
        if m:
            return {
                "keyword": m.group(0),
                "line": lines[i].strip()[:200],
            }
        # push 失败类:同窗口有成功标记=已恢复,跳过;无成功标记=真实失败,报
        mp = PUSH_FAIL_RE.search(lines[i])
        if mp:
            if has_push_success:
                continue  # 已恢复,不报
            return {
                "keyword": mp.group(0),
                "line": lines[i].strip()[:200],
            }
    return None


def _iter_lines(path: Path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def parse_standard(path: Path, script: str):
    """标准 .sh 任务:返回 (pairs, pending_start)
    pairs=[(start_dt, end_dt, exit_code, duration_sec), ...]
    pending_start=最新一个"有 start 无 end"的 start_dt(进行中或被 SIGTERM 杀)。

    2026-07-23 修复(根治 schedule 超时被杀致 last_run 错乱):
    1) 不再 break 于首个 pending_start,改 continue 遍历所有 start 取最新 pending。
       (旧 bug:15:05 被杀 + 15:35 在跑,旧逻辑取首个 15:05 当 last_run;
        新逻辑 continue 到 15:35 取最新)
    2) next_start 检测:若首个 end>=start 实际 >= 下一次 start(即 end 属于下一轮),
       说明本次 start 被杀(未写结束行就被 SIGTERM 终止),判为孤儿 pending,
       不消耗该 end(留给下一轮配对)。(旧 bug:被杀 start 偷下一轮 end 致配对错位)
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
    # 双指针配对:每个 start 找首个未消耗的 end>=start 且 end<next_start 且 gap<=3h
    pairs, ei, pending_start = [], 0, None
    for i, s in enumerate(starts):
        next_s = starts[i + 1] if i + 1 < len(starts) else None
        while ei < len(ends) and ends[ei][0] < s:
            ei += 1  # 跳过早于该 start 的孤儿 end
        if ei >= len(ends):
            pending_start = s  # 无 end:进行中或被杀,continue 取最新
            continue
        e_ts, e_code = ends[ei]
        # end 属于下一轮(e_ts >= next_start) -> 本次 start 被杀(孤儿),不消耗 end
        if next_s is not None and e_ts >= next_s:
            pending_start = s
            continue
        dur = (e_ts - s).total_seconds()
        if 0 <= dur <= MAX_GAP_SEC:
            pairs.append((s, e_ts, e_code, dur))
            ei += 1
        # dur>MAX_GAP_SEC:错位，丢弃该 start 不配对（不消耗 end）
    return pairs, pending_start


def parse_etf_nt(path: Path):
    """etf_nt:完成行无时间戳，耗时直接给出。last_run 用开始时间。
    返回 (pairs, pending_start)，pending_start=开始但未完成的进行中任务。
    2026-07-25: 兼容 "失败 exit=N" fallback 行(collector crash 时 shell 补写),
    解析真实 exit code 而非启发式 143。
    2026-07-25: 同一 pending 内多个 DONE 行取最后一个(覆盖),支持 backfill.sh 在
    collector 完成行后补写最终 DONE 行(带综合 exit code),让 gen_stats 记录真实
    backfill.sh 退出码而非 collector 的 exit=0(collector 成功+deploy 失败场景)。
    """
    pairs, pending, last_done = [], None, None
    for line in _iter_lines(path):
        m = ETF_START_RE.search(line)
        if m:
            # 上一个 pending 有 DONE -> 入 pairs(取最后一个 DONE,覆盖 collector 完成行)
            if pending is not None and last_done is not None:
                pairs.append((pending, pending, last_done[0], last_done[1]))
            pending = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            last_done = None
            continue
        m = ETF_DONE_RE.search(line)
        if m and pending is not None:
            # group(1)=完成/失败, group(2)=duration(可选), group(3)=exit(可选,默认0)
            # 不立即 append,记录最后一个 DONE(覆盖),让 backfill.sh 最终 DONE 行生效
            dur = float(m.group(2)) if m.group(2) else 0
            code = int(m.group(3)) if m.group(3) else 0
            last_done = (code, dur)
    # 处理最后一个 pending
    pending_start = None
    if pending is not None:
        if last_done is not None:
            pairs.append((pending, pending, last_done[0], last_done[1]))
        else:
            pending_start = pending  # 无 DONE:进行中或被杀
    return pairs, pending_start


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
                           "est_text": "-", "last_run": None, "last_exit": None,
                           "last_duration_sec": None,
                           "log_anomaly": False, "log_anomaly_keyword": None,
                           "log_anomaly_line": None})
            continue
        if t["mode"] == "etf_nt":
            pairs, pending_start = parse_etf_nt(log_path)
        else:
            pairs, pending_start = parse_standard(log_path, t["script"])
        last_run, code, last_dur = None, None, None
        pending_crash_retry = False  # P1(2026-07-29): pending_start + last_exit!=0 (crash重试中)
        if pairs:
            s, e, code, dur = pairs[-1]
            last_run = s.strftime("%Y-%m-%d %H:%M")
            last_dur = round(dur)
        # 进行中/被杀任务(有 start 无 end):若比最近配对更晚,覆盖 last_run
        # 区分 pending_start 性质:
        #   距今 >MAX_GAP_SEC(3h) = 被 SIGTERM 杀(launchd ExitTimeOut 超时),
        #     标 exit_code=143(128+SIGTERM15),前端显 ⚠️"退出码=143"提示异常;
        #   否则为进行中(刚启动未结束),exit=null 不显⚠️
        # (2026-07-23 修复:旧逻辑被杀任务 exit=null 与"进行中"混同,前端不显⚠️看不出异常)
        if pending_start is not None:
            if last_run is None or pending_start > pairs[-1][0]:
                last_run = pending_start.strftime("%Y-%m-%d %H:%M")
                age = (datetime.now() - pending_start).total_seconds()
                # P1 稳定性(2026-07-29): 所有模式(含 etf_nt)pending_start 都读 launchctl_last_exit
                # 真实退出码,不读 None(7-24 ETF SIGTRAP 退出码133被 None 掩盖 crash)。
                # etf_nt 仍不回退启发式 143(假 SIGTERM 告警代价大),launchctl 读不到才 None;
                # standard 模式 launchctl 读不到回退原启发式(143 if age>3h else None)。
                # backfill.sh 保证写最终 DONE 行(带真实 exit),无 DONE = 极端(SIGKILL 整个脚本),
                # 真问题靠漏跑检查/耗时检查/launchd err log + launchctl 真实码。
                real_exit = launchctl_last_exit(LABEL_MAP.get(t["task"]))
                if real_exit is not None:
                    code = real_exit  # 0=成功, 143=SIGTERM超时, 133=SIGTRAP, 1=脚本异常
                elif t["mode"] == "etf_nt":
                    code = None  # etf_nt 不启发式标 143(launchctl 读不到才 None)
                else:
                    code = 143 if age > MAX_GAP_SEC else None  # standard 回退启发式
                # P1(2026-07-29): pending_start(当前在跑) + 上次运行确实 crash = 重试中,
                # 标记 pending_crash_retry 供后续 log_anomaly 标注。
                # 2026-08-15 Bug1 修复(运维告警误报根因): 判定依据从 launchctl 历史残留码
                # 改为 [日志最近一次完整配对运行的退出码 + 时间间隔]。
                #   旧: launchctl_last_exit 是"任务上一次整体运行"的退出码(无时间戳)，
                #       8/12 deploy 残留 exit=1 污染 8/13 全天正常在跑任务 -> 误报 5 条。
                #   新: 只有"上一轮配对运行 exit!=0 且 其结束时间距本 pending_start < 6h"
                #       (同一调度时槽内崩溃后立刻重启) 才判真 crash-retry；
                #       跨天/跨调度周期的历史残留码不关联本 pending,不再误报。
                if pairs and pairs[-1][1] is not None:
                    _prev_end, _prev_code = pairs[-1][1], pairs[-1][2]
                    _retry_gap = (pending_start - _prev_end).total_seconds()
                    if _prev_code != 0 and 0 <= _retry_gap <= CRASH_RETRY_GAP_SEC:
                        pending_crash_retry = True
                last_dur = None
        # 第4盲区修复: 扫最近一次运行窗口的 log 找异常关键词,
        # 即使 exit=0(异常被 try/except 吞)也能抓到告警
        anomaly = scan_log_anomaly(log_path, t["script"], t["mode"])
        # P1 稳定性(2026-07-29): pending_start + last_exit!=0 = 上次crash现在重试中,
        # log_anomaly 标注 "pending但上次exit非0"(不覆盖 log 关键词扫描已发现的 anomaly)
        if not anomaly and pending_crash_retry:
            anomaly = {
                "keyword": "pending但上次exit非0",
                "line": f"pending_start={pending_start.strftime('%Y-%m-%d %H:%M')} last_exit={code}",
            }
        result.append({
            "task": t["task"], "name": t["name"], "schedule": t["schedule"],
            "est_text": est_text(pairs), "last_run": last_run,
            "last_exit": code, "last_duration_sec": last_dur,
            "log_anomaly": bool(anomaly),
            "log_anomaly_keyword": anomaly["keyword"] if anomaly else None,
            "log_anomaly_line": anomaly["line"] if anomaly else None,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {OUT.relative_to(REPO)} ({len(result)} tasks)")
    for r in result:
        flag = " ⚠ANOMALY" if r.get("log_anomaly") else ""
        print(f"  {r['name']:8s} {r['schedule']:22s} est={r['est_text']:8s} "
              f"last={r['last_run']} exit={r['last_exit']} dur={r['last_duration_sec']}s{flag}")
    return result


if __name__ == "__main__":
    build()
