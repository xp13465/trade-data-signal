#!/bin/bash
# schedule_monitor.sh - 计划任务执行监控（方案B：独立监控脚本 + launchd 每15分钟触发）
#
# 9 个 launchd 计划任务：update_all / backfill_evening / intraday_snapshot /
# futures_backfill / lhb_backfill / rzhb_backfill / etf_national_team / lab_auto /
# us_stock_morning。
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
import hashlib
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
TOLERANCE = timedelta(minutes=30)  # 漏跑检查容忍窗口（适用所有任务，与采集频率无关）
# 产物时效检查阈值（intraday 15min 频率 + 5min buffer = 20min）：
#   intraday 15min 推一次 overview.json，下一轮 sch+15min 已推新版，留 5min buffer 给
#   采集+push 耗时（任务2优化后 <7min），超过 20min 即为线上滞后（push 失败或卡死）。
LAG_TOLERANCE = timedelta(minutes=20)

# 8 任务计划时点表（与 ~/Library/LaunchAgents/com.trade.*.plist StartCalendarInterval 对齐）
# 字段：task | launchd log 文件名 | 计划时点列表（HH:MM）
TASKS = [
    {"task": "update_all",          "log": "update_all_launchd.log",
     "schedules": ["17:50"]},
    {"task": "backfill_evening",    "log": "backfill_evening_launchd.log",
     "schedules": ["02:00", "16:35"]},  # 2026-07-24 B4 Top2 去重：删 20:00 槽（plist 已删，监控配置同步）
    {"task": "intraday_snapshot",   "log": "intraday_snapshot_launchd.log",
     "schedules": [  # 2026-07-28 plist 10m(26次)+15:35/20:35 收盘后(intraday-close ETF 预估修复), 共28时点
         "09:25", "09:35", "09:45", "09:55", "10:05", "10:15", "10:25", "10:35", "10:45", "10:55",
         "11:05", "11:15", "11:25",
         "13:05", "13:15", "13:25", "13:35", "13:45", "13:55",
         "14:05", "14:15", "14:25", "14:35", "14:45", "14:55", "15:05",
         "15:35", "20:35"]},
    {"task": "futures_backfill",    "log": "futures_backfill_launchd.log",
     "schedules": ["20:05", "21:00"]},
    {"task": "lhb_backfill",        "log": "lhb_backfill_launchd.log",
     "schedules": ["18:30", "19:30"]},
    {"task": "rzhb_backfill",       "log": "rzhb_backfill_launchd.log",
     "schedules": ["19:15"]},  # 2026-07-24 23:00->19:15 紧跟数据发布(18:00-19:00)，避开 lhb 19:30
    {"task": "etf_national_team",   "log": "etf_national_team_launchd.log",
     "schedules": ["20:07", "21:30"]},
    {"task": "lab_auto",            "log": "update_lab_launchd.log",
     "schedules": ["19:00"]},
    {"task": "us_stock_morning",    "log": "us_stock_morning_launchd.log",
     "schedules": ["05:00"]},  # 2026-07-29 新增：美股04:00收盘后1h采集+deploy，原监控盲区补齐
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
recoveries = []  # 异常恢复通知(log_anomaly 从 true 变 false)

# 告警去重/抑制机制(2026-07-20): 同一异常持续不重复发邮件,异常消失发恢复邮件
# state 文件不进 git(与 sentiment.db 同级),丢失时 24h stale 降级兜底
ALERT_STATE_FILE = REPO / "data" / "alert_state.json"


def load_alert_state():
    """读 alert_state.json,不存在/异常返回 {}"""
    if not ALERT_STATE_FILE.exists():
        return {}
    try:
        with open(ALERT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[warn] 读 alert_state.json 失败(按空 state 处理): {e}", file=sys.stderr)
        return {}


def save_alert_state(state):
    """写 alert_state.json(目录不存在自动创建)"""
    try:
        ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[warn] 写 alert_state.json 失败: {e}", file=sys.stderr)


alert_state = load_alert_state()
seen_keys_this_run = set()  # 本次运行仍存在的异常 key(防误报恢复)

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
#    去重(2026-07-25)：exit!=0 但 last_run 距今 >24h 的旧告警不重复 SEVERE。
#    根因场景：etf_national_team 7/24 20:07 collector crash last_exit=143(假告警)，
#    根因已闭环(bba5ecaa deploy根治 + 6824a43c 真实exit code + c1921857 ProcessPool修crash)，
#    但 stats 旧记录未清(周末不跑，周一 20:07 跑才更新)，schedule_monitor 每15min读到
#    exit=143 非0 -> 持续 SEVERE 告警邮件约192封。
#    规则：last_run 距今 >24h 且 exit!=0 = 旧问题(任务超1天没跑)，等下次任务跑更新
#    stats 自动清除，降级 log INFO 不重复 SEVERE；最近 24h 内 exit!=0 仍 SEVERE(新问题不漏报)。
# 2026-07-25: 跑前刷新 schedule_stats.json(保证读最新,不读滞后旧值)。
# 根因:schedule_monitor 每15min跑,但 schedule_stats.json 只在各任务脚本结尾刷新,
# 若任务没跑(如周末),json 滞后旧值(如 etf 143 假告警),schedule_monitor 持续读旧值误告警。
# 跑前调 gen_schedule_stats.py 重生成(读最新 launchd.log),保证读到当前真实状态。
try:
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_schedule_stats.py")],
        capture_output=True, text=True, timeout=60,
    )
except Exception as e:
    print(f"[warn] gen_schedule_stats 刷新失败(读旧 schedule_stats.json): {e}", file=sys.stderr)

STALE_EXIT_THRESHOLD = timedelta(hours=24)
if STATS_FILE.exists():
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            stats = json.load(f)
        for s in stats:
            exit_code = s.get("last_exit")
            # null=进行中/无数据不算失败；非0=退出失败
            if exit_code is not None and exit_code != 0:
                last_run_str = s.get("last_run") or ""
                is_stale = False
                if last_run_str:
                    try:
                        # last_run 格式 "2026-07-24 20:05"（无秒，gen_schedule_stats 写入）
                        last_run_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M")
                        age = NOW - last_run_dt
                        if age > STALE_EXIT_THRESHOLD:
                            is_stale = True
                    except ValueError:
                        print(f"[warn] {s.get('task')} last_run 格式异常: {last_run_str}", file=sys.stderr)
                if is_stale:
                    # 旧告警已过期(任务>24h没跑)，等下次任务跑更新 stats 自动清除，不重复 SEVERE
                    print(
                        f"[info] {s['task']} 退出失败 last_exit={exit_code} "
                        f"last_run={last_run_str} 距今>{int(STALE_EXIT_THRESHOLD.total_seconds()//3600)}h, "
                        f"旧告警已过期,等下次任务跑更新(不重复 SEVERE)"
                    )
                else:
                    alerts.append(
                        f"SEVERE: {s['task']} 退出失败 last_exit={exit_code} "
                        f"last_run={last_run_str}"
                    )
            # 第4盲区修复: log 异常关键词检查(脚本吞异常 exit=0 漏报)
            # 即使 last_exit=0(异常被 try/except 吞),log 里有 Traceback/异常类名也算失败
            # 复用 24h stale 去重(与 exit!=0 同逻辑, 旧告警不重复 SEVERE)
            if s.get("log_anomaly"):
                keyword = s.get("log_anomaly_keyword") or "?"
                line = (s.get("log_anomaly_line") or "")[:120]
                line_sample = line[:80]
                # 去重 key: task|keyword|line前80字符md5前8位
                dedup_key = (
                    f"{s['task']}|{keyword}|"
                    f"{hashlib.md5(line_sample.encode('utf-8', errors='replace')).hexdigest()[:8]}"
                )
                # 标记本次仍存在(防误报恢复),无论 stale 与否
                seen_keys_this_run.add(dedup_key)
                last_run_str_a = s.get("last_run") or ""
                is_stale_a = False
                if last_run_str_a:
                    try:
                        last_run_dt_a = datetime.strptime(last_run_str_a, "%Y-%m-%d %H:%M")
                        if NOW - last_run_dt_a > STALE_EXIT_THRESHOLD:
                            is_stale_a = True
                    except ValueError:
                        pass
                if is_stale_a:
                    # 24h stale 兜底(state 丢失时仍不轰炸)
                    print(
                        f"[info] {s['task']} log异常 keyword={keyword} "
                        f"last_run={last_run_str_a} 距今>"
                        f"{int(STALE_EXIT_THRESHOLD.total_seconds()//3600)}h, "
                        f"旧告警已过期,等下次任务跑更新(不重复 SEVERE)"
                    )
                else:
                    existing = alert_state.get(dedup_key)
                    if existing is None or existing.get("status") != "active":
                        # 首次发现 或 恢复后再次出现 = 发 SEVERE + 写 state
                        alerts.append(
                            f"SEVERE: {s['task']} log异常关键词<{keyword}> "
                            f"exit={exit_code}(可能被try/except吞) "
                            f"last_run={last_run_str_a} 行: {line}"
                        )
                        alert_state[dedup_key] = {
                            "status": "active",
                            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": keyword,
                            "line_sample": line_sample,
                        }
                    else:
                        # 已 active = 抑制不重发,只 log
                        print(
                            f"[suppress] {s['task']} {keyword} 异常持续中, "
                            f"last_alerted={existing.get('last_alerted')}, 不重发"
                        )
    except Exception as e:
        print(f"[warn] 解析 schedule_stats.json 失败: {e}", file=sys.stderr)

# 恢复检测: state 里 active 但本次未 seen = 异常已消失,发恢复邮件
# (gen_schedule_stats 每任务只记首个命中,故每 task 至多1个 active key)
for _key, _info in list(alert_state.items()):
    if _info.get("status") == "active" and _key not in seen_keys_this_run:
        _task = _key.split("|", 1)[0] if "|" in _key else _key
        _kw = _info.get("keyword", "?")
        recoveries.append({
            "task": _task,
            "keyword": _kw,
            "first_seen": _info.get("first_seen", "?"),
        })
        _info["status"] = "recovered"
        _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[recovery] {_task} 异常关键词 {_kw} 已消失 "
            f"(首次发现: {_info.get('first_seen')})"
        )
save_alert_state(alert_state)

# 3) ETF 国家队耗时阈值检查（B4 稳定性 2026-07-24）
#    daily 正常 ~140s(2.3min), >300s(5min)告警(进程池退化信号, 如 2026-07-23 2032s 事故)
#    backfill 全量正常 ~15min, >1800s(30min)告警
#    只检查最近 2 小时内的完成行(避免旧超时重复告警, schedule_monitor 每15min跑)
ETF_DAILY_THRESHOLD = 300  # 5min
ETF_BACKFILL_THRESHOLD = 1800  # 30min
ETF_DUR_RE = re.compile(r"\[etf_nt\] (daily|backfill) 完成 (\d+\.?\d*)s")
ETF_DAILY_START_RE = re.compile(r"\[etf_nt\] daily 开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
ETF_BACKFILL_START_RE = re.compile(r"\[etf_nt\] backfill 开始 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
etf_log = LOG_DIR / "etf_national_team_launchd.log"
if etf_log.exists():
    try:
        etf_lines = etf_log.read_text(encoding="utf-8", errors="replace").splitlines()
        # 反向找最后一行完成行(只查最近一次跑的耗时)
        for i in range(len(etf_lines) - 1, -1, -1):
            m = ETF_DUR_RE.search(etf_lines[i])
            if m:
                mode, dur = m.group(1), float(m.group(2))
                # 反向找该完成行之前最近的同 mode 开始行
                start_re = ETF_DAILY_START_RE if mode == "daily" else ETF_BACKFILL_START_RE
                start_dt = None
                for j in range(i - 1, -1, -1):
                    m2 = start_re.search(etf_lines[j])
                    if m2:
                        start_dt = datetime.strptime(m2.group(1), "%Y-%m-%d %H:%M:%S")
                        break
                # 只检查最近 2 小时内的(避免旧超时重复告警)
                if start_dt and NOW - start_dt <= timedelta(hours=2):
                    threshold = ETF_DAILY_THRESHOLD if mode == "daily" else ETF_BACKFILL_THRESHOLD
                    if dur > threshold:
                        alerts.append(
                            f"SEVERE: etf_national_team {mode} 耗时 {dur:.0f}s 超阈值 {threshold}s "
                            f"(进程池退化信号) start<{start_dt.strftime('%Y-%m-%d %H:%M:%S')}>"
                        )
                break  # 只查最后一行完成行
    except Exception as e:
        print(f"[warn] ETF 耗时检查失败: {e}", file=sys.stderr)

# 4) 产物时效检查：线上 overview.json collected_at vs NOW
#    intraday push 失败就是线上滞后（schedule_stats 只看任务跑了没，不查产物上线=盲区）。
#    仅交易日盘中 09:50-15:30 检查（intraday 每15min推一次，首次 09:35 完成于 ~09:42），
#    09:50 起检避开开盘空窗期 overview.json 仍是凌晨旧版导致的误报；避免非交易时段误报。
#    多域名容错：依次试 ss.fx8.store/sss.sugas.site/s.sugas.site，任一不 lag 即 OK，
#    规避 CF Workers cache 滞后单域名误报。滞后 > 20min（3域名全 lag）告警 SEVERE
#    （intraday 15min 频率 + 5min buffer；2026-07-24 从 30min 改 20min 适配 15min 频率）。
#    curl 超时 8s（subprocess timeout 12s 兜底）不阻塞 launchd 15min 周期。
#    用 /usr/bin/curl 而非 urllib：venv python 缺系统 CA 证书会 SSL 校验失败，curl 走系统证书更稳。
try:
    from app.calendar import is_trading_day
    now_hm = NOW.strftime("%H%M")
    # 0950 起检：intraday 第一次 09:35，dur 约 7min（任务2优化后），09:42 才完成 push。
    # 0930-0942 开盘空窗期 overview.json 必然是凌晨 02:38 旧版，必触发误报。
    # 0950 检查避开空窗，覆盖盘中其余时点（intraday 每 15min 推一次）。
    # 1130-1315 排除午休窗口：A股午休 11:30-13:00 无交易，overview.json collected_at
    # 停在上午 11:30 快照(完成于 ~11:37)，直到 13:05 快照完成(~13:12)才更新。
    # 此窗口内 lag 必然 >20min 但属正常(午休没交易)，排除避免误报。
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
            status = "ok" if lag <= LAG_TOLERANCE else "lag"
            lag_results.append((base, collected_at, lag_min, status))
            if lag <= LAG_TOLERANCE:
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
                f"threshold<20min> now<{now_full}> 详情: {detail}"
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

# 恢复邮件(独立于 SEVERE,异常消失即发,不加 --severe 前缀)
if recoveries:
    print(f"[{now_str}] 检测到 {len(recoveries)} 个异常恢复:")
    for r in recoveries:
        print(f"  [恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失")
    if len(recoveries) == 1:
        r0 = recoveries[0]
        subject = f"[恢复] {r0['task']} 异常关键词 {r0['keyword']} 已消失"
    else:
        subject = f"[恢复] {len(recoveries)}个计划任务异常已消失"
    rec_lines = [
        f"[恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失 "
        f"(首次发现: {r['first_seen']}, 恢复时间: {now_str})"
        for r in recoveries
    ]
    body = "<br>".join(
        l.replace("<", "&lt;").replace(">", "&gt;") for l in rec_lines
    )
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            subject,
            body,
            "--alert-issue", "计划任务监控恢复",
            "--alert-log", str(MONITOR_LOG),
        ],
        check=False,
    )

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
