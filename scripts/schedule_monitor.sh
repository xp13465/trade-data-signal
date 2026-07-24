#!/bin/bash
# schedule_monitor.sh - 计划任务执行监控（方案B：独立监控脚本 + launchd 每15分钟触发）
#
# 8 个 launchd 计划任务：update_all / backfill_evening / intraday_snapshot /
# futures_backfill / lhb_backfill / rzhb_backfill / etf_national_team / lab_auto。
# 每个任务的计划时点表来自 ~/Library/LaunchAgents/com.trade.*.plist 的 StartCalendarInterval。
#
# 检查项：
#   1) 漏跑：当前时间落在某任务计划时点 + 30min 容忍窗口内，但 last_run < 计划时点 = 漏跑告警
#   2) 退出失败：schedule_stats.json 中 last_exit 非 0（非 null，null=进行中/无数据不算失败）
#
# 告警链路：复用 scripts/notify.py（邮件 + data/alerts/latest.md），告警不阻塞、不重试。
# launchd 每15分钟(Minute=0,15,30,45)由 com.trade.schedule-monitor.plist 触发。
set -uo pipefail
REPO="${REPO:-/Users/linhuichen/code/trade}"
cd "$REPO"

# 注：launchd plist 设 REPO=/Users/linhuichen/code/trade-data，trade-data/scripts 是
# trade/scripts 的 symlink，trade-data/data/logs 与 trade/data/logs 同 inode（hard link）。
# 故 $REPO/data/logs/*_launchd.log 路径在 trade-data 下也可读到正确日志。
export REPO

# 用 python heredoc 处理日期解析 + JSON 读取（bash 处理太繁琐易错）
"$REPO/.venv/bin/python" <<'PYEOF' 2>&1
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(os.environ["REPO"])
LOG_DIR = REPO / "data" / "logs"
STATS_FILE = REPO / "static-site" / "data" / "schedule_stats.json"
MONITOR_LOG = LOG_DIR / "schedule_monitor_launchd.log"

NOW = datetime.now()
TOLERANCE = timedelta(minutes=30)  # 30min 容忍窗口

# 8 任务计划时点表（与 ~/Library/LaunchAgents/com.trade.*.plist StartCalendarInterval 对齐）
# 字段：task | launchd log 文件名 | 计划时点列表（HH:MM）
TASKS = [
    {"task": "update_all",          "log": "update_all_launchd.log",
     "schedules": ["17:50"]},
    {"task": "backfill_evening",    "log": "backfill_evening_launchd.log",
     "schedules": ["02:00", "16:35", "20:00"]},
    {"task": "intraday_snapshot",   "log": "intraday_snapshot_launchd.log",
     "schedules": ["09:35", "10:05", "10:35", "11:05", "11:30",
                   "13:05", "13:35", "14:05", "14:35", "15:05", "15:35"]},
    {"task": "futures_backfill",    "log": "futures_backfill_launchd.log",
     "schedules": ["20:05", "21:00"]},
    {"task": "lhb_backfill",        "log": "lhb_backfill_launchd.log",
     "schedules": ["18:30", "19:30"]},
    {"task": "rzhb_backfill",       "log": "rzhb_backfill_launchd.log",
     "schedules": ["23:00"]},
    {"task": "etf_national_team",   "log": "etf_national_team_launchd.log",
     "schedules": ["20:07", "21:30"]},
    {"task": "lab_auto",            "log": "update_lab_launchd.log",
     "schedules": ["19:00"]},
]

# 标准任务开始行：=== xxx.sh 开始 YYYY-MM-DD HH:MM:SS ===
START_RE = re.compile(r"开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# etf_nt 任务开始行：[etf_nt] daily 开始 YYYY-MM-DD HH:MM:SS
ETF_START_RE = re.compile(r"\[etf_nt\] daily 开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def parse_last_run(log_path: Path):
    """从 launchd log 解析最近一次开始时间作为 last_run（含 etf_nt 变体）"""
    if not log_path.exists():
        return None
    last = None
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = START_RE.search(line) or ETF_START_RE.search(line)
                if m:
                    last = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"[warn] 解析 {log_path.name} 失败: {e}", file=sys.stderr)
    return last


def today_schedule(hm: str) -> datetime:
    """今天 HH:MM 的 datetime（second=0）"""
    h, m = hm.split(":")
    return NOW.replace(hour=int(h), minute=int(m), second=0, microsecond=0)


alerts = []

# 1) 漏跑检查：对每个任务的每个计划时点，若 now 落在 [sch, sch+30min] 窗口内
#    且 last_run < sch（任务在该计划时点之后没跑过）= 漏跑
for t in TASKS:
    log_path = LOG_DIR / t["log"]
    last_run = parse_last_run(log_path)
    last_run_str = last_run.strftime("%Y-%m-%d %H:%M:%S") if last_run else "无"

    for sch_hm in t["schedules"]:
        sch = today_schedule(sch_hm)
        # 下界 +60s buffer：launchd StartCalendarInterval 整点触发后，任务脚本有
        # caffeinate + with_lock.py 包装 + mkdir/cd 等启动开销，"开始"行通常延后 3-8s
        # 写入日志。schedule_monitor 同样整点触发(cron Minute=0,15,30,45)，若下界=sch，
        # 读 log 时任务的"开始"行可能还没写入，last_run 解析到上一轮，误报漏跑。
        # 2026-07-23 事故：rzhb/futures/etf 多次整点竞态误报(21:00 futures/21:30 etf/
        # 23:00 rzhb)，下一个 15min 周期自愈 OK。+60s 下界根治：sch+60s <= NOW 才检查，
        # 给任务 1 分钟启动 buffer，覆盖 launchd 启动+写"开始"行的延迟。
        if sch + timedelta(seconds=60) <= NOW <= sch + TOLERANCE:
            # now 在容忍窗口内，检查任务是否在 sch 之后跑过
            if last_run is None or last_run < sch:
                alerts.append(
                    f"SEVERE: {t['task']} 漏跑 计划<{sch_hm}> toler<30min> "
                    f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> last_run<{last_run_str}>"
                )

# 2) 退出失败检查：从 schedule_stats.json 读 last_exit（非 null 且非 0 = 失败）
if STATS_FILE.exists():
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            stats = json.load(f)
        for s in stats:
            exit_code = s.get("last_exit")
            # null=进行中/无数据不算失败；非0=退出失败
            if exit_code is not None and exit_code != 0:
                alerts.append(
                    f"SEVERE: {s['task']} 退出失败 last_exit={exit_code} "
                    f"last_run={s.get('last_run')}"
                )
    except Exception as e:
        print(f"[warn] 解析 schedule_stats.json 失败: {e}", file=sys.stderr)

# 3) 产物时效检查：线上 overview.json collected_at vs NOW
#    intraday push 失败就是线上滞后（schedule_stats 只看任务跑了没，不查产物上线=盲区）。
#    仅交易日盘中 09:50-15:30 检查（intraday 每30min推一次，首次 09:35 完成于 ~09:45），
#    09:50 起检避开开盘空窗期 overview.json 仍是凌晨旧版导致的误报；避免非交易时段误报。
#    多域名容错：依次试 ss.fx8.store/sss.sugas.site/s.sugas.site，任一不 lag 即 OK，
#    规避 CF Workers cache 滞后单域名误报。滞后 > 30min（3域名全 lag）告警 SEVERE。
#    curl 超时 8s（subprocess timeout 12s 兜底）不阻塞 launchd 15min 周期。
#    用 /usr/bin/curl 而非 urllib：venv python 缺系统 CA 证书会 SSL 校验失败，curl 走系统证书更稳。
try:
    from app.calendar import is_trading_day
    now_hm = NOW.strftime("%H%M")
    # 0950 起检：intraday 第一次 09:35，dur 约 10min，09:45 才完成 push。
    # 0930-0945 开盘空窗期 overview.json 必然是凌晨 02:38 旧版，必触发误报。
    # 0950 检查避开空窗，覆盖盘中其余时点（intraday 每 30min 推一次）。
    # 1130-1315 排除午休窗口：A股午休 11:30-13:00 无交易，overview.json collected_at
    # 停在上午 11:30 快照(完成于 ~11:40)，直到 13:05 快照完成(~13:15)才更新。
    # 此窗口内 lag 必然 >30min 但属正常(午休没交易)，排除避免误报。
    # 2026-07-24 12:30 误报事故根因：午休未排除，12:15 起 lag>30min 触发 SEVERE。
    # 非交易日已由 is_trading_day() 排除（周末/节假日 overview 滞后正常）。
    if is_trading_day() and "0950" <= now_hm <= "1530" and not ("1130" <= now_hm < "1315"):
        # 多域名容错：CF Workers Static Assets 靠部署自动 purge，但 intraday push
        # main 不触发 CF wrangler redeploy，ss.fx8.store cache 可能滞后；依次试 3 域名，
        # 任一 collected_at 在 30min 内即 OK（不 lag），都滞后才告警。
        domains = [
            "https://ss.fx8.store",
            "https://sss.sugas.site",
            "https://s.sugas.site",
        ]
        lag_results = []  # [(domain, collected_at, lag_min, status)]
        all_lag = True
        for base in domains:
            url = f"{base}/data/overview.json"
            try:
                result = subprocess.run(
                    ["/usr/bin/curl", "-sS", "--max-time", "8", url],
                    capture_output=True, text=True, timeout=12,
                )
            except subprocess.TimeoutExpired:
                lag_results.append((base, None, None, "timeout"))
                continue
            if result.returncode != 0:
                lag_results.append((base, None, None, f"curl rc={result.returncode}"))
                continue
            try:
                ov = json.loads(result.stdout)
            except json.JSONDecodeError as e:
                lag_results.append((base, None, None, f"json parse fail: {e}"))
                continue
            collected_at = ov.get("collected_at") or ""
            try:
                collected_dt = datetime.strptime(collected_at, "%Y%m%d %H:%M:%S")
            except ValueError:
                lag_results.append((base, collected_at, None, "collected_at 格式异常"))
                continue
            lag = NOW - collected_dt
            lag_min = int(lag.total_seconds() // 60)
            status = "ok" if lag <= TOLERANCE else "lag"
            lag_results.append((base, collected_at, lag_min, status))
            if lag <= TOLERANCE:
                all_lag = False
                print(f"[ok] 线上 overview collected_at={collected_at} lag={lag_min}min (via {base})")
                break
        if all_lag:
            now_full = NOW.strftime("%Y-%m-%d %H:%M:%S")
            detail = "; ".join(
                f"{b}={ca or 'N/A'} lag={lm if lm is not None else '?'}min [{st}]"
                for b, ca, lm, st in lag_results
            )
            alerts.append(
                f"SEVERE: 线上 overview.json 时效滞后(3域名全lag) "
                f"threshold<30min> now<{now_full}> 详情: {detail}"
            )
except Exception as e:
    print(f"[warn] 线上 overview.json 时效检查失败: {e}", file=sys.stderr)

# 输出 + 告警
now_str = NOW.strftime("%Y-%m-%d %H:%M:%S")
if alerts:
    print(f"[{now_str}] 检测到 {len(alerts)} 个告警:")
    for a in alerts:
        print(a)
    # 复用 notify.py 发邮件 + 写 alerts/latest.md（--severe 加 [需Claude排查] 前缀）
    body = "<br>".join(
        a.replace("<", "&lt;").replace(">", "&gt;") for a in alerts
    )
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            "SEVERE: 计划任务监控告警",
            body,
            "--severe",
            "--alert-issue", "计划任务监控告警",
            "--alert-log", str(MONITOR_LOG),
        ],
        check=False,
    )
else:
    print(f"[{now_str}] OK 所有任务按计划执行，无漏跑，无退出失败")

# Heartbeat：每次完整跑完都更新时间戳（主控 Claude Code cron 读此文件，
# 超过 30 分钟未更新 = launchd 层可能挂了，立即提示用户）。
# 文件含时间戳 + 告警数，便于主控层判断"在跑但有告警" vs "完全没跑"。
try:
    heartbeat_path = Path("/tmp/schedule-monitor-heartbeat.txt")
    heartbeat_path.write_text(
        f"{NOW.strftime('%Y-%m-%d %H:%M:%S')}\nalerts={len(alerts)}\n",
        encoding="utf-8",
    )
except Exception as e:
    print(f"[warn] heartbeat 写入失败: {e}", file=sys.stderr)
PYEOF

# 总是 exit 0：告警已发邮件，避免 launchd 因非0退出重试
exit 0
