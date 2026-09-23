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
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent  # 不用 .resolve()：trade-data/scripts 是 trade/scripts 的 symlink，resolve() 会跳回 trade 导致读旧日志。保留 symlink 路径让 REPO=实际调用方(trade-data)
sys.path.insert(0, str(Path(__file__).parent))
from util_atomic import atomic_write_json  # noqa: E402  (原子写公共模块, 2026-09-22 非 kelly 链路统一)
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
    # overfit-monitor: 2026-08-25 监控盲区收尾批补入(用户拍板)。launchd
    # com.trade.overfit-monitor 交易日 21:40 跑 overfit_monitor.sh(AI监控卡每日打点+预警)。
    # 此前打点 rc!=0 无任何自动消费方(上报链盲区, filtered 键事故同款「校验存在≠校验生效」)。
    # 配套: overfit_monitor.sh 日志同批从 STAMP 多文件改固定 append + 标准开始/结束行,
    # standard 模式零特殊逻辑直读; schedule_monitor.sh TASKS 同步加漏跑检查条目。
    {"task": "overfit_monitor", "name": "过拟合监控", "script": "overfit_monitor.sh",
     "schedule": "21:40", "log": "overfit_monitor_launchd.log", "mode": "standard"},
    # s06-snapshot: 2026-08-26 补入(S06 快照每日盘后重生链路, 切全站默认前置)。
    # launchd com.trade.s06-snapshot 交易日 20:35 跑 s06_snapshot.sh(gen→check→R2 三段)。
    # 日志固定 append + 标准开始/结束行, standard 模式零特殊逻辑直读;
    # schedule_monitor.sh TASKS 同步加漏跑检查条目(同 overfit_monitor 先例)。
    {"task": "s06_snapshot", "name": "S06快照重生", "script": "s06_snapshot.sh",
     "schedule": "20:35", "log": "s06_snapshot_launchd.log", "mode": "standard"},
    # check-data-gap: 2026-08-27 补入(采集数据缺口/停更告警检测器, 告警兜底批 #103 方案A+S2)。
    # launchd com.trade.check-data-gap 交易日 22:35 跑 check_data_gap_alerts.sh
    # (四检查器: 北向深缺口/北向停更/accum_nav 窗外缺口/宽度族保鲜; 数据级告警由
    # 检测器自身走 notify.py 出口)。日志固定 append + 标准开始/结束行, standard 直读;
    # schedule_monitor.sh TASKS 同步加漏跑检查条目。
    {"task": "check_data_gap", "name": "数据缺口检测", "script": "check_data_gap_alerts.sh",
     "schedule": "22:35", "log": "check_data_gap_launchd.log", "mode": "standard"},
    # turnover_backfill: 2026-09-09 补入(#82 C6: turnover 摘出 update_all 主链独立延后跑)。
    # launchd com.trade.turnover-backfill 交易日 21:10 跑 turnover_backfill.sh
    # (baostock 增量 + cleanup_d3d2 算 a_turnover_* 入 daily_metric + 增量重导 overview/a-stock 传 R2)。
    # 日志固定 append + 标准开始/结束行, standard 模式可解析;
    # schedule_monitor.sh TASKS 已同步收录漏跑检查(同 s06_snapshot 先例)。
    # ⚠️ 时点 21:10 为默认建议值, 最终以主控 merge 时确认的 launchd 部署时点为准。
    {"task": "turnover_backfill", "name": "换手率独立延后", "script": "turnover_backfill.sh",
     "schedule": "21:10", "log": "turnover_backfill_launchd.log", "mode": "standard"},
    # nextday_plan: 2026-09-10 补入(PRD 阶段一次日买入计划生成器, F1 机检链收编;
    # 与 schedule_monitor.sh TASKS + check_data_integrity.nextday_plan 三处同步注册)。
    # launchd com.trade.nextday-plan 交易日 22:30 跑 nextday_plan.sh
    # (读 4 产物 → K=1 top1 → 写 data/nextday_plan.json + 两树 + R2 + 通知; 空计划合法)。
    # 日志固定 append + 标准开始/结束行, standard 模式直读;
    # schedule_monitor.sh TASKS 已同步加漏跑检查条目(同 s06_snapshot 先例)。
    {"task": "nextday_plan", "name": "次日买入计划", "script": "nextday_plan.sh",
     "schedule": "22:30", "log": "nextday_plan_launchd.log", "mode": "standard"},
    # nextday_gap_check: 2026-09-17 补入(#45 伪跳空二次剔除, F3 机检链收编;
    # 与 schedule_monitor.sh TASKS 同步注册, 同 nextday_plan 先例)。
    # systemd trade-nextday-gap-check.timer 交易日 09:26 跑 nextday_gap_check.sh
    # (拉 akshare 当日开盘价, 对 buy_date==today 买入行做伪跳空二次剔除; standard 模式零特殊逻辑直读)。
    {"task": "nextday_gap_check", "name": "次日买入计划伪跳空剔除", "script": "nextday_gap_check.sh",
     "schedule": "09:26", "log": "nextday_gap_check_launchd.log", "mode": "standard"},
]

# P1-1/P1-2 消费补口(2026-09-24, r2-false-success-rootfix P1-1+P1-2):
# 下两任务不在 TASKS 表——它们无标准 `=== xxx.sh 开始/结束 ===` 行,塞不进 scan_log_anomaly
# 的窗口切分(取尾部窗口专门扫)。gen_daily_brief(daily_brief.log,每天20:40,deploy外生成器)
# 与 fetch_news(fetch_news_launchd.log,盘中7:30-21:00每30min)的
#   ✗ R2_UPLOAD_TIMEOUT / ✗ [fetch_news] R2/staticdata 同步超时 标记此前悬空
# (ANOMALY_RE 能匹配但日志不参与扫描 → 无自动消费方,连续异常无法自动发现)。
# 修法: EXTRA_MARKER_SCANS 尾部窗口扫描 → log_anomaly/r2_skip_count 输出进 schedule_stats.json,
# schedule_monitor 每次跑前调本脚本重生成 + 全量遍历 stats 自动消费(L427 log_anomaly 告警 +
# 本批新增 r2_skip_count 消费),标记即有真正自动消费方。
EXTRA_MARKER_SCANS = [
    {
        "task": "gen_daily_brief", "name": "AI每日速递",
        "schedule": "每日 20:40", "log": "daily_brief.log",
        # 部署外生成器日志无标准开始/结束行。轮次作用域(2026-09-24 P1-A/P1-B 收口):
        #   以每轮必打的「开始生成」行为本轮起点, 窗口=[最后开始生成行, 文件末尾)
        #   = 最近一轮完整运行段, 标记滞留问题根治(旧尾部窗口 600 行 < 每日1轮则
        #   覆盖 1 轮, 无滞留问题, 但为统一机制仍走 round_start_re)。
        # round_start_re: daily_brief.log 每轮必打 `[run_daily_brief] schedule_enabled=true,开始生成 <ts>`
        "tail_lines": 600,
        "round_start_re": r'\[run_daily_brief\] schedule_enabled=true,开始生成 ',
    },
    {
        "task": "fetch_news", "name": "新闻采集",
        "schedule": "7:30-21:00 每30min", "log": "fetch_news_launchd.log",
        # P1-A/P1-B(2026-09-24 r2 终审收口): 尾部 400 行窗口滞留 ~10-20h(30min 一轮,
        #   每轮 4-6 行), ⚠/SKIPPED_LOCKED 滞留=「窗口存在」≠「本轮发生」。改为轮次
        #   作用域: 每轮必打 `[fetch_news] 已写 ... date=...` 行(采集成功写盘后), 以最后
        #   一个「已写」行为本轮起点, 窗口=[已写行, 文件末尾) = 最近一轮完整同步段。
        #   下一轮成功时新「已写」行把旧标记挤出窗口 → log_anomaly/计数自动对应当本轮。
        "tail_lines": 400,
        "round_start_re": r'\[fetch_news\] 已写 ',
    },
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
    "overfit_monitor": "com.trade.overfit-monitor",
    "s06_snapshot": "com.trade.s06-snapshot",
    "check_data_gap": "com.trade.check-data-gap",
    "turnover_backfill": "com.trade.turnover-backfill",
    "nextday_plan": "com.trade.nextday-plan",
    # nextday_gap_check: 2026-09-17 补入(#45), 云上 trade-nextday-gap-check.service
    # (2026-09-22 补: 云上 Linux 用 systemctl 读真实码, unit 映射靠 com.trade. -> trade- 规则,
    #  缺此项则 standard 模式读不到真实码 -> 回退启发式猜 143 误报, 与本次治误报同根因)。
    "nextday_gap_check": "com.trade.nextday-gap-check",
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
    r'|✗\s*R2_UPLOAD_TIMEOUT'
    r'|✗\s*R2 上传(?:失败|异常)'
    r'|✗\s*\[fetch_news\]\s*(?:R2/staticdata 同步超时|同步上线异常)'
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

# Fix A(2026-09-23): multiprocessing 子进程正常退出时清理 semaphore 的噪音。
# 现象: backfill_evening 日志出现 "Exception ignored in: <Finalize object, dead>"
#   + Traceback + "FileNotFoundError: [Errno 2]"(进程已退出、sem 已被回收的正常清理),
#   任务本身成功,但被 ANOMALY_RE 的 Traceback/FileNotFoundError 命中 → 每天假告警。
# 判定: ANOMALY 命中行向上回溯,若存在 "Exception ignored in: <Finalize object, dead>"
#   行且其间只有 Traceback/缩进帧/异常类名行(无普通日志) → 属该噪音块,不报。
# 注意口子不开大: 真实 Traceback / 真实 FileNotFoundError(非清理链)仍报。
FINALIZER_NOISE_START_RE = re.compile(r'Exception ignored in: <Finalize object, dead>')

# Fix B(2026-09-23): nextday_gap_check 内置 300s 重试成功自愈。
# 根因: 9:26 首拉 ConnectionError -> 内置重试 -> 9:31 成功(exit=0);旧逻辑命中即报
#   不认后续成功, nextday_gap_check|ConnectionError 卡 active 至今。
# 自愈判定: 同窗口出现重试成功标记(显式 "✓ 重试成功" / 逐 ETF "✓ xxx 正常 open=" /
#   "执行日 {today} 全部 {N} 笔无伪跳空, 无标记", 后两者仅重试拿到开盘价才会走到) →
#   ConnectionError/TimeoutError 命中且命中行属于 _fetch_opens 重试链(含「拉开盘价失败」,
#   重试链 ConnectionError 只在 "⚠ 第 N 次拉开盘价失败: {last_err}" 这行出现) → 自愈不报;
#   重试也失败(exit=2、无成功标记)照报; 后续 R2 上传失败的 ConnectionError(真实失败)
#   文案不含「拉开盘价失败」→ 不抑制, 照报(P2-2, reviewer S8 场景)。
GAP_RETRY_SUCCESS_RE = re.compile(
    r'\[nextday_gap_check\] ✓ 重试成功'
    r'|\[nextday_gap_check\] +✓ \d+ 正常 open='
    r'|\[nextday_gap_check\] 执行日 \S+ 全部 \d+ 笔无伪跳空, 无标记'
)
TRANSIENT_NET_ERR_RE = re.compile(r'\b(?:ConnectionError|TimeoutError)\s*:')


def launchctl_last_exit(label: str | None) -> int | None:
    """读任务最近一次运行的**真实退出码**(平台分支 mac/linux)。

    云上(systemd timer)没有 launchctl, 旧代码调 launchctl 必然失败返回 None,
    回退 L491 启发式「pending_start age>3h 猜 exit=143」→ 所有跑超 3h 任务误报
    143 假 SIGTERM。而云上 systemd TimeoutStartSec=0 根本不杀(journal 实证
    `Deactivated successfully`, 退出码 0)。2026-09-22 治误报(根因修)。

    - macOS: 调 `launchctl print gui/UID/label` 读真实 last exit code。
    - Linux(systemd): 调 `systemctl show` 读 ExecMainCode/ExecMainStatus:
        LoadState != "loaded"(unit 不存在) -> None(未知, 不猜)
        ExecMainCode=1(CLD_EXITED)      -> ExecMainStatus=真实退出码
        ExecMainCode=2/3(信号杀/dump)    -> 128+ExecMainStatus(对齐 launchd 143=SIGTERM 15)
        其他(从未跑/调用失败)            -> None(降级为「未知」, 不猜 143)

    返回 int 退出码(0=成功,非0=失败如 143=SIGTERM, 1=脚本异常)。
    label 为 None/空、读不到真实码、任务从没跑过(ExecMainCode=0 或 None)时返回 None。
    用途: pending_start(有 start 无 end, 崩在结束行前)时 systemd/launchd 记录真实退出码
    (含 143 / exit=1 / exit=0), 优先用真实码消除误报(云上跑超3h 正常退出被猜 143)。
    """
    if not label:
        return None
    if sys.platform.startswith("linux"):
        return _systemd_last_exit(label)
    # macOS: launchctl print
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


def _label_to_systemd_unit(label: str) -> str | None:
    """launchd label -> systemd unit 名(云上实际 unit, 与 self_heal.sh 同映射)。

    规律: launchd label `com.trade.update-all` -> 云上 systemd unit `trade-update-all.service`。
    映射失败(不以 com.trade. 开头)返回 None(视为无法定位, 降级「未知」不猜 143)。
    """
    if not label or not label.startswith("com.trade."):
        return None
    return label.replace("com.trade.", "trade-", 1) + ".service"


def _systemd_last_exit(label: str) -> int | None:
    """systemd 读真实退出码(Linux 分支)。unit 不存在/从未跑/读不到 -> None(未知)。"""
    unit = _label_to_systemd_unit(label)
    if not unit:
        return None
    try:
        # 一次 get-properties 抓三属性(带属性名前缀 key=value, 免 --value 输出顺序依赖)
        r = subprocess.run(
            ["systemctl", "show", unit, "-p", "LoadState", "-p", "ExecMainCode",
             "-p", "ExecMainStatus"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    props = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    if props.get("LoadState") != "loaded":
        return None  # unit 不存在: 降级「未知」, 不猜 143
    code, status = props.get("ExecMainCode"), props.get("ExecMainStatus")
    try:
        ec = int(code) if code not in (None, "") else None
        es = int(status) if status not in (None, "") else None
    except ValueError:
        return None
    if ec == 1 and es is not None:   # CLD_EXITED: 真实退出码
        return es
    if ec in (2, 3) and es is not None:  # CLD_KILLED/CLD_DUMPED: 128+signal 对齐 launchd 143
        return 128 + es
    return None  # 从未跑(ec=0)/缺字段: 未知


def _finalizer_noise_ranges(lines: list, lo: int, hi: int) -> list:
    """在 [lo, hi) 行区间内找所有 multiprocessing finalizer 清理噪音块(Fix A)。

    噪音块结构(约 8 行, 实证 2026-09-22 backfill_evening):
        Exception ignored in: <Finalize object, dead>
        Traceback (most recent call last):
          File ".../multiprocessing/util.py", line 227, in __call__
            ...
          File ".../multiprocessing/synchronize.py", line 87, in _cleanup
            sem_unlink(name)
        FileNotFoundError: [Errno 2] No such file or directory
    切块方式(精确, 不回溯, 防噪音块后紧跟真实异常被误吞):
      起点 = "Exception ignored in: <Finalize object, dead>" 行;
      向后吃 Traceback/缩进帧/代码行(这些行本身非 ANOMALY 命中, 但属于块结构);
      吃到第一个异常类型行(无缩进 "FileNotFoundError: ...")为块结束(该行也属于块);
      额外要求块内至少一帧含 "multiprocessing/" —— 证明是清理链而非普通真实异常
      (真实异常帧路径如 intraday_snapshot.py 不含)。
    返回 [(start_idx, end_idx_exclusive), ...]。
    """
    ranges = []
    i = lo
    while i < hi:
        if FINALIZER_NOISE_START_RE.search(lines[i]):
            start = i
            i += 1
            # 向后吃 Traceback / 缩进帧 / 缩进代码行
            while i < hi:
                lk = lines[i]
                if lk.startswith((" ", "\t")) or lk.strip().startswith("Traceback"):
                    i += 1
                    continue
                break
            # i 应指向异常类型行(无缩进 "FileNotFoundError: ...")
            if i < hi and re.match(r"^[A-Za-z_][A-Za-z0-9_.]*Error:", lines[i].strip()):
                block = lines[start:i + 1]
                # 块内含 multiprocessing 帧 = 确认是清理链, 才算噪音块
                if any("multiprocessing/" in b for b in block):
                    ranges.append((start, i + 1))
                    i += 1
                    continue
            # 不构成噪音块(非清理链/结构不符): 从起点后一行继续找
            i = start + 1
        else:
            i += 1
    return ranges


def _in_finalizer_noise(ranges: list, idx: int) -> bool:
    """命中行 idx 是否落在任一 finalizer 清理噪音块区间内(Fix A)。"""
    return any(a <= idx < b for a, b in ranges)


def scan_log_anomaly(log_path: Path, script: str, mode: str,
                     last_exit: int | None = None) -> dict | None:
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
        last_exit: 本轮最终退出码(None=进行中/读不到)。2026-08-24 push 冲突降噪用:
          push 失败类命中时仅 last_exit 非 0 才报——deploy.sh 内置 fetch+rebase+重试
          自愈后 exit=0,但成功标记文案随脚本演化漂移(PUSH_SUCCESS_RE 四个串不含
          backfill 实际输出「[backfill] ✓ 补采+重算+推送完成」,2026-08-05~08-10
          16 条 self-healed 假警报实证),exit code 是权威判据。

    Returns:
        ({"keyword": ..., "line": ...}|None, skip_count): 二元组。
        skip_count = 该运行窗口内 SKIPPED_LOCKED(R2 上传锁被占用跳过本轮)出现次数,
        独立于 log_anomaly 标注——skip 是设计让路(下轮/兜底链重试), 不算失败不上 SEVERE,
        但给出独立计数供 schedule_stats 前端/巡检观察(2026-09-24 P2-2 硬化)。
    """
    if not log_path.exists():
        return None, 0
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return None, 0

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
        return None, 0  # log 里无 start 行,无法切窗口

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
    # P2-2(2026-09-24): SKIPPED_LOCKED 独立计数——skip=设计让路(锁忙下轮重试)不上 SEVERE,
    # 但命中次数需可观察(intraday 每轮都可能撞 deploy 锁, 连 skip 多轮=收盘版可能上不了 R2)。
    skip_count = sum(1 for _l in window_lines if "SKIPPED_LOCKED" in _l)
    has_push_success = any(PUSH_SUCCESS_RE.search(l) for l in window_lines)
    has_gap_retry_success = any(GAP_RETRY_SUCCESS_RE.search(l) for l in window_lines)
    finalizer_ranges = _finalizer_noise_ranges(lines, last_start_idx, end_idx)
    for i in range(last_start_idx, end_idx):
        # 优先扫非 push 失败类异常(Traceback/异常类名/FATAL):命中即报,不抑制
        m = ANOMALY_RE.search(lines[i])
        if m:
            # Fix A(2026-09-23): multiprocessing finalizer 清理噪音块内命中不报
            # (进程正常退出的清理,偶然语气=异常实际非任务失败)
            if _in_finalizer_noise(finalizer_ranges, i):
                print(f"[finalizer-noise] {log_path.name} 命中行属于 multiprocessing "
                      f"清理噪音, 不报")
                continue
            # Fix B(2026-09-23): nextday_gap_check 内置重试成功 -> 瞬时网络异常自愈不报
            # (9:26 ConnectionError -> 9:31 重试成功 exit=0; 重试也失败无成功标记照报)
            # P2-2(2026-09-23): 抑制仅限 _fetch_opens 重试链的 ConnectionError(命中行含
            # 「拉开盘价失败」)。同窗口重试成功后、尾部 R2 上传失败的真实 ConnectionError
            # 文案不含「拉开盘价失败」→ 不抑制, 照报(reviewer S8 场景, exit=1 必须报)。
            if (has_gap_retry_success and TRANSIENT_NET_ERR_RE.search(lines[i])
                    and "拉开盘价失败" in lines[i]):
                print(f"[retry-self-heal] {log_path.name} 重试链瞬时网络异常命中但同窗口 "
                      f"有重试成功标记, 不报")
                continue
            return {
                "keyword": m.group(0),
                "line": lines[i].strip()[:200],
            }, skip_count
        # push 失败类:同窗口有成功标记=已恢复,跳过;无成功标记但最终 exit==0/None 也跳过
        # (2026-08-24 降噪:仅最终 exit!=0 才报。16 条 self-healed 假警报根因=成功标记文案
        # 漂移,exit code 是权威——rebase 自愈成功 exit 必为 0;真失败 exit!=0 照报;
        # None=进行中未定论,等下轮任务结束再判,不提前轰炸)
        mp = PUSH_FAIL_RE.search(lines[i])
        if mp:
            if has_push_success:
                continue  # 已恢复,不报
            if last_exit is None or last_exit == 0:
                print(f"[push-noise] {log_path.name} push 失败关键词命中但最终 "
                      f"last_exit={last_exit}(自愈成功/进行中), 不报")
                continue
            return {
                "keyword": mp.group(0),
                "line": lines[i].strip()[:200],
            }, skip_count
    return None, skip_count


# P1-2 闭环修正(2026-09-24, r2-false-success-rootfix): 真实标记形态核实。
# fetch_news.py 实际打印是 ⚠ 前缀(fetch_news.py L725/732/735: `⚠ [fetch_news] 同步上线异常`、
#   `⚠ [fetch_news] R2 上传 rc=...`、`⚠ [fetch_news] staticdata 同步 rc=...`),gen_daily_brief.py
#   L3089/3091 是 `⚠ R2 上传 rc=...` / `⚠ R2 上传异常`——全是 ⚠ 无 ✗[fetch_news] 前缀。
# 上一轮 EXTRA_MARKER_SCANS 引用全局 ANOMALY_RE(✗\s*\[fetch_news\]...三支)对真实日志
#   grep=0 命中(实测 fetch_news_launchd.log 含 ⚠ [fetch_news] 117 行, ✗ [fetch_news] 0 行),
#   连续异常仍无消费方(悬空未解)。修正: 专属 MARKER_ANOMALY_RE 匹配真实 ⚠ 形态,
#   全局 ANOMALY_RE 保持不动(TASKS 表内任务误报面不扩大)。
MARKER_ANOMALY_RE = re.compile(
    r'⚠\s*\[fetch_news\]\s*(?:同步上线异常|R2 上传 rc|staticdata 同步 rc)'
    r'|⚠\s*R2 上传 rc=\S+|⚠\s*R2 上传异常'
    r'|✗\s*\[fetch_news\]\s*(?:R2|staticdata)(?: 同步超时|同步上线异常)?|同步上线异常'
    r'|R2_UPLOAD_TIMEOUT'
)


def scan_marker_log(log_path: Path, tail_lines: int, round_start_re: re.Pattern | None = None) -> tuple:
    """轮次作用域扫描 deploy 外生成器日志(gen_daily_brief/fetch_news, P1-1/P1-2 消费补口)。

    这两个任务不在 TASKS 表、无标准 `=== xxx.sh 开始/结束 ===` 行,scan_log_anomaly 窗口
    切不出来返回 (None,0) → 其 R2 上传失败/同步异常标记此前无自动消费方,连续异常无法
    自动发现。此处扫描专属 MARKER_ANOMALY_RE(fetch_news/gen_daily_brief 真实 ⚠/✗ 标记
    形态) + 独立计 SKIPPED_LOCKED 次数。

    【P1-A/P1-B 轮次作用域(2026-09-24 r2 终审收口)】: 旧尾部行数窗口(tail_lines)对
    低频任务滞留严重——fetch_news 30min 一轮每轮约 4-6 行,tail 400 行 ≈ 覆盖 20-40 轮
    ≈ 10-20 小时;标记行一旦滞留窗口内,「窗口里存在该行」就不再等价「本轮发生」:
      ① P1-A: ⚠ [fetch_news] 同步上线异常(设计内降级标记)滞留 → log_anomaly 恒 True,
         monitor 对非瞬时桶任务首次即 SEVERE → 上线即告警、永不恢复(等着随窗口滚出)。
      ② P1-B: SKIPPED_LOCKED 语义=「本轮让路、下轮自愈」,但窗口滞留把「窗口里攒了
         N 行」当「N 轮连续 skip」→ 一次 15min 锁忙 45min 后必 SEVERE、挂 1-2 天。
    → 改为**轮次作用域**: 传入 round_start_re(本轮运行起点标志正则,要求每轮必打),
      从文件末尾反向找最后一个 round_start 命中行,窗口=[该行, 文件末尾) = 最近一轮
      完整运行段。窗口里有标记 ≈ 本轮发生了标记;下一轮成功时新的起点行把旧标记
      挤出窗口,log_anomaly 自动恢复 False(本轮自愈语义)。

    Args:
        log_path: log 文件路径
        tail_lines: 兜底尾部窗口行数(round_start_re 找不到本轮起点时回退使用)
        round_start_re: 本轮起点正则(fetch_news=每轮必打的「已写」行,
            gen_daily_brief=每轮必打的「开始生成」行)。None=纯尾部窗口(旧行为)。

    Returns:
        (anomaly_dict|None, skip_count): 二元组, 与 scan_log_anomaly 同构。
        anomaly_dict 含 keyword/line 字段(与现有 log_anomaly_keyword/line 同构)。
        last_run 由调用方(EXTRA_MARKER_SCANS 循环)按 mtime/行内时间戳补充。
    """
    if not log_path.exists():
        return None, 0
    lines = _read_tail_lines(log_path)
    window = None
    if round_start_re is not None:
        for i in range(len(lines) - 1, -1, -1):
            if round_start_re.search(lines[i]):
                window = lines[i:]
                break
    if window is None:
        window = lines[-tail_lines:] if tail_lines and tail_lines > 0 else lines
    skip_count = sum(1 for _l in window if "SKIPPED_LOCKED" in _l)
    for _l in window:
        m = MARKER_ANOMALY_RE.search(_l)
        if m:
            # P1-A(2026-09-24 r2 终审): ⚠ [fetch_news] 同步上线异常 / ⚠ R2 上传 rc / ⚠
            # staticdata 同步 rc 是设计内降级标记(日志原文自带「不阻塞」/「兜底」), 不该
            # 首次即 SEVERE → 返回 severity=degrade, monitor 消费端走连续 N 轮缓冲;
            # ✗ 前缀 / R2_UPLOAD_TIMEOUT 是真异常(非静默/超时), severity=critical
            # 维持首次即 SEVERE。
            _sev = "degrade" if _l.strip().startswith("⚠") else "critical"
            return {"keyword": m.group(0), "line": _l.strip()[:200],
                    "severity": _sev}, skip_count
    return None, skip_count


def _compile_rsre(pattern: str | None) -> re.Pattern | None:
    """把 EXTRA_MARKER_SCANS 的 round_start_re 字符串编译为正则(None=纯尾部窗口)。"""
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None  # 配置写错不崩, 回退尾部窗口


# P2(2026-09-24 r2 终审): 日志无限增长性能债——fetch_news_launchd.log 已 205KB 且每日
# append, read_text 全量读每次 gen_schedule_stats 都扫整文件(O(n) 线性增长)。改为只读
# 尾部 _TAIL_READ_BYTES 字节(覆盖最近一轮完整运行段足够: fetch_news 每轮 4-6 行,
# 512KB ≈ 数万行 ≈ 数百轮; gen_daily_brief 每日 1 轮日志 12KB, 512KB 覆盖近 40 天)。
_TAIL_READ_BYTES = 512 * 1024


def _read_tail_lines(path: Path, n_bytes: int = _TAIL_READ_BYTES) -> list[str]:
    """只读文件尾部至多 n_bytes 字节并拆行(空文件/异常返回 [])。

    边界处理: 若尾部截断落在某行中间, 该行首部不完整——从最后一条完整换行后截断,
    丢弃不完整头行(不影响轮次作用域找「已写/开始生成」等完整标志行)。
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []
            start = max(0, size - n_bytes)
            f.seek(start)
            chunk = f.read()
    except Exception:
        return []
    text = chunk.decode("utf-8", errors="replace")
    if start > 0:
        # 截断可能落在行中: 从第一个换行之后开始, 丢不完整头行
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1:]
    return text.splitlines()


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
                           "log_anomaly_line": None,
                           # P2-2(2026-09-24): 无日志分支也补 r2_skip_count,17 条字段一致
                           # (schedule_monitor 消费 + 前端渲染需字段在位)
                           "r2_skip_count": 0})
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
                # [Bug1 补修·路径B, 2026-08-15] 与路径A(CRASH_RETRY_GAP_SEC=6h)同口径。
                # 上一轮(b1a5111b5)只修了 pending_crash_retry 标注(路径A), 此处
                # `code = real_exit` 一字未动 -> last_exit 仍被 launchctl 无时间戳残留码
                # (如 8/12 deploy exit=1 污染 8/13 17:50 正常在跑)污染, 致 schedule_monitor
                # L304"退出失败 last_exit=1" + 前端 last_exit!=0 弹窗"上次执行异常"双误报。
                # launchctl 真实码无时间戳, 不能无条件采信。仅当确属"同槽 crash-retry"
                # (上一轮配对 exit!=0 且距本 pending_start < CRASH_RETRY_GAP_SEC) 才显
                # launchctl 真实码; 否则 pending 在跑期间 last_exit 保持 null
                # (进行中不算失败, 与路径A同口径: 跨天残留码与本次 pending 无关联)。
                _prev_crash_code = None
                if pairs and pairs[-1][1] is not None:
                    _pe, _pc = pairs[-1][1], pairs[-1][2]
                    _retry_gap = (pending_start - _pe).total_seconds()
                    if _pc != 0 and 0 <= _retry_gap <= CRASH_RETRY_GAP_SEC:
                        _prev_crash_code = _pc
                # [Bug1 复审FAIL补修·恢复被杀/卡死检测, 2026-08-15] 上轮(4784f0326)把
                # real_exit 有值时一律采 None(残留码不采信),修好了 8/13 在跑误报,但把
                # 2026-07-23/07-24 建立的「被杀/崩溃检测」弄坏: 上次配对 exit=0 的任务本轮
                # 被 SIGTERM 杀(launchctl 码 143, age>3h)时,last_exit 从 143 变 null,
                # 前端弹窗 + monitor "退出失败" 双漏报。
                # 判定分层(见下方每分支注释): ①同槽 crash-retry ②被杀/卡死(age>3h 强信号,
                # launchctl 码可信) ③在跑(age<=3h, 残留码不采信——8/13 误报的根本)。
                if real_exit is not None and _prev_crash_code is not None:
                    code = real_exit  # 同槽 crash-retry(场景C): launchctl 真实码(0/143/133/1)
                elif real_exit is not None and age > MAX_GAP_SEC:
                    code = real_exit  # 被杀/卡死(场景A, age>3h): launchctl 码可信 — 恢复 07-23/07-24 检测
                elif real_exit is not None:
                    code = None  # 在跑(场景B/D, age<=3h): 残留码不采信, last_exit=null
                elif t["mode"] == "etf_nt":
                    code = None  # etf_nt 不启发式标 143(launchctl 读不到才 None)
                elif sys.platform.startswith("linux"):
                    # 云上 systemd(TimeoutStartSec=0 不杀, journal 实证 Deactivated successfully
                    # 退出码 0)读不到真实码 = 未知(None), 绝不回退猜 143 —— 2026-09-22 治误报根因:
                    # 旧逻辑 launchctl 在 Linux 必然失败 -> 启发式 age>3h 猜 143, 所有跑超 3h 任务误报。
                    code = None
                else:
                    code = 143 if age > MAX_GAP_SEC else None  # macOS launchd 回退启发式(ExitTimeOut 真杀)
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
        # (2026-08-24: 传 last_exit=code,push 失败类仅最终 exit!=0 才报)
        anomaly, r2_skip_count = scan_log_anomaly(log_path, t["script"], t["mode"], last_exit=code)
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
            # P2-2(2026-09-24): R2 上传锁 skip 次数独立计数(schedule_monitor 不升级 SEVERE,
            # 前端"执行统计"可见; 连续 skip 多轮=上传缺口信号需人工关注)
            "r2_skip_count": r2_skip_count,
        })
    # P1-1/P1-2(2026-09-24, r2-false-success-rootfix): 补扫 deploy 外生成器日志
    # (gen_daily_brief/fetch_news)。这两个任务不在 TASKS 表, 无标准开始/结束行,
    # 此前 ✗ R2_UPLOAD_TIMEOUT / ✗ [fetch_news] 标记悬空无自动消费方。尾部窗口扫描
    # 结果并入 schedule_stats.json, schedule_monitor 全量遍历自动消费
    # (log_anomaly→SEVERE 告警 / r2_skip_count→连续跳过计数, 见 schedule_monitor.sh)。
    for m in EXTRA_MARKER_SCANS:
        log_path = LOG_DIR / m["log"]
        anomaly, skip_count = scan_marker_log(log_path, m["tail_lines"],
                                              round_start_re=_compile_rsre(m.get("round_start_re")))
        # last_run = 文件最后写入时刻(近似最近运行时刻; 无标准开始行可解析时间戳)
        _mtime = None
        try:
            if log_path.exists():
                _mtime = datetime.fromtimestamp(log_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError):
            _mtime = None
        result.append({
            "task": m["task"], "name": m["name"], "schedule": m["schedule"],
            "est_text": "-", "last_run": _mtime, "last_exit": None,
            "last_duration_sec": None,
            "log_anomaly": bool(anomaly),
            "log_anomaly_keyword": anomaly["keyword"] if anomaly else None,
            "log_anomaly_line": anomaly["line"] if anomaly else None,
            # P1-A(2026-09-24 r2 终审): ⚠ 降级标记(不阻塞/兜底)标注 severity=degrade,
            # schedule_monitor 对 EXTRA 任务走连续 N 轮缓冲不首报 SEVERE(见 monitor 消费端)
            "log_anomaly_severity": anomaly.get("severity") if anomaly else None,
            "r2_skip_count": skip_count,
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(OUT, result, indent=2)
    print(f"✓ {OUT.relative_to(REPO)} ({len(result)} tasks)")
    for r in result:
        flag = " ⚠ANOMALY" if r.get("log_anomaly") else ""
        print(f"  {r['name']:8s} {r['schedule']:22s} est={r['est_text']:8s} "
              f"last={r['last_run']} exit={r['last_exit']} dur={r['last_duration_sec']}s{flag}")
    return result


if __name__ == "__main__":
    build()
