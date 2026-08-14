#!/bin/bash
# schedule_monitor.sh - 计划任务执行监控（方案B：独立监控脚本 + launchd 每15分钟触发）
#
# 9 个 launchd 计划任务：update_all / backfill_evening / intraday_snapshot /
# futures_backfill / lhb_backfill / rzhb_backfill / etf_national_team / lab_auto /
# us_stock_morning。
# 每个任务的计划时点表来自 ~/Library/LaunchAgents/com.trade.*.plist 的 StartCalendarInterval。
#
# 检查项（6 维度, R2迁移后72h监控 2026-08-08 扩展）：
#   1) 漏跑：当前时间落在某任务计划时点 + 30min 容忍窗口内，但 last_run < 计划时点 = 漏跑告警
#   2) 退出失败：schedule_stats.json 中 last_exit 非 0（非 null，null=进行中/无数据不算失败）
#   2b) log异常关键词：scan_log_anomaly 抓 Traceback/异常类名/FATAL（exit=0 不可信, 脚本吞异常漏报）
#   3) 执行耗时：last_duration_sec 超阈值告警（intraday>10min/update_all>30min/backfill>30min）
#   4) launchctl 加载：11 个 com.trade label 未加载 = launchd 层挂了
#   5) 产物时效（Worker路径）：线上 overview.json collected_at vs NOW, 3域名容错, 盘中<20min
#   6) R2直连时效：ssd.fx8.store overview/intraday collected_at 时效 + R2可达性
#      （R2直连stale+Worker stale=upload_r2断; R2直连fresh+Worker stale=CF cache purge失效）
#
# 告警链路：复用 scripts/notify.py（邮件 + data/alerts/latest.md），告警不阻塞、不重试。
# 阶段3 R2上传失败 notify 已接入: intraday_snapshot.sh upload-index/upload-intraday 失败发
#   notify --severe --dedup-key; deploy.sh upload-all-data 等失败收集 R2_FAIL 发 notify --severe。
#
# 修复闭环: 告警邮件 -> 主控 Claude Code cron 定期查 alert_state.json(活跃告警)/
#   schedule_stats.json(任务状态) -> 派 agent 修正 -> 修正后任务跑新版 exit=0/时效恢复 ->
#   schedule_monitor 检测恢复发恢复邮件。launchd 持久(schedule_monitor/self_heal 不依赖会话)。
# launchd 每15分钟(Minute=0,15,30,45)由 com.trade.schedule-monitor.plist 触发。
#
# 2026-08-14 告警邮件优化:
#   A1 新增"进行中超时检测"(任务 dur=null 未完成, 超计划时点+阈值+缓冲仍不结束 = 疑似卡死
#      告警, 如 update_all 17:50 卡死 54min 无告警的 8-14 事故); 修复 null dur 误恢复
#      (进行中任务 key 保持 active, 不判"已消失"发恢复邮件)。
#   A3 恢复邮件最小静默窗口: 同 key 上次恢复(last_recovered) <30min 不重复发恢复邮件
#      (防 8-12 振荡), 状态仍置 recovered。
#   B2 告警正文模板化: 每项 4 行 [严重度]任务 异常类型 / 影响 / 日志 / 建议;
#      恢复邮件尾加"无需操作,已自动恢复"提示。
set -uo pipefail
REPO="${REPO:-/Users/linhuichen/code/trade-data}"
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
    # trading_day_only: 非交易日跳过漏跑检查(避免周末误报)。
    #   etf 非交易日脚本不启动 last_run 停周五 < 周末时点 = 误报(必需);
    #   intraday/update_all/backfill 非交易日启动写"开始"行 last_run 更新不误报,
    #   但加 trading_day_only=True 额外保险 + 减少无意义检查。
    #   us_stock_morning 无交易日闸门每天跑(美股周末虽休但脚本仍启动采旧数据) = False。
    {"task": "update_all",          "log": "update_all_launchd.log",
     "trading_day_only": True,
     "schedules": ["17:50"]},
    {"task": "backfill_evening",    "log": "backfill_evening_launchd.log",
     "trading_day_only": True,
     "schedules": ["02:00", "16:35", "21:00"]},  # 2026-07-29 加 21:00 槽：csi_div/div_lowvol T日晚发布，21:00 提前采(原仅 02:00 兜底)
    {"task": "intraday_snapshot",   "log": "intraday_snapshot_launchd.log",
     "trading_day_only": True,
     "schedules": [  # 2026-07-29 plist 盘中28次(10m节奏+11:32上午收盘收尾/13:01下午开盘首采/15:02收盘收尾)+15:35/20:35收盘后, 共30时点
         "09:25", "09:35", "09:45", "09:55", "10:05", "10:15", "10:25", "10:35", "10:45", "10:55",
         "11:05", "11:15", "11:25", "11:32",
         "13:01", "13:05", "13:15", "13:25", "13:35", "13:45", "13:55",
         "14:05", "14:15", "14:25", "14:35", "14:45", "14:55", "15:02",
         "15:35", "20:35"]},
    {"task": "futures_backfill",    "log": "futures_backfill_launchd.log",
     "trading_day_only": True,
     "schedules": ["20:05", "21:00"]},
    {"task": "lhb_backfill",        "log": "lhb_backfill_launchd.log",
     "trading_day_only": True,
     "schedules": ["18:30", "19:30"]},
    {"task": "rzhb_backfill",       "log": "rzhb_backfill_launchd.log",
     "trading_day_only": True,
     "schedules": ["08:00"]},  # 2026-07-29 19:15->T+1 08:00：SSE官方T+1早晨发布T日(非误判18-19点)，19:15连续采不到T日
    {"task": "etf_national_team",   "log": "etf_national_team_launchd.log",
     "trading_day_only": True,  # 非交易日脚本不启动(无"开始"行), 必需跳过漏跑检查避免周末误报
     "schedules": ["20:07", "21:30"]},
    {"task": "lab_auto",            "log": "update_lab_launchd.log",
     "trading_day_only": True,
     "schedules": ["19:00"]},
    {"task": "us_stock_morning",    "log": "us_stock_morning_launchd.log",
     "trading_day_only": False,  # 无交易日闸门, 每天跑(美股周末休但脚本仍启动采旧数据 exit=0)
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
# 2026-08-14 告警优化 A1: 进行中(未完成)任务集合。dur=null + exit=null = 任务仍在跑。
# 用于: ①进行中超时检测(卡死/异常慢) ②恢复检测跳过进行中任务的 key(防 8-14 误恢复)。
in_progress_tasks = set()

# 2026-08-14 告警优化 A3: 恢复邮件最小静默窗口。同 key 上次恢复(last_recovered)距今
# <30min 则不重复发恢复邮件(防 8-12 振荡: active->recovered->active 快速交替轰炸)。
# 状态仍置 recovered(异常确已消失), 仅抑制恢复邮件。
RECOVERY_COOLDOWN = timedelta(minutes=30)


def _recovery_cooldown_ok(_key, _info):
    """A3: 同 key 上次恢复(last_recovered)距今 <30min 返回 False(不重复发恢复邮件)。"""
    _lr = _info.get("last_recovered")
    if not _lr:
        return True
    try:
        _lr_dt = datetime.strptime(_lr, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return True
    return NOW - _lr_dt >= RECOVERY_COOLDOWN

# 通知分级(2026-08-10): 自愈类(not_loaded/r2_unreachable 等可被 self_heal.sh/网络自愈)
# 连续N次仍异常才通知, 严重类(漏跑/exit失败/数据错)首次即通知。N=2 = 30min(15min频率×2)。
SELF_HEAL_THRESHOLD = 2

# 1) 漏跑检查：对每个任务的每个计划时点，若 now 落在 [sch, sch+30min] 窗口内
#    且 last_run < sch（任务在该计划时点之后没跑过）= 漏跑
#    非交易日跳过 trading_day_only 任务(避免周末误报: etf 等非交易日脚本不启动,
#    last_run 停周五 < 周末时点 = 误报漏跑)。
#    漏跑 suppress(2026-08-01): 同 task 同 sch 同日首次发 SEVERE, 30min 窗口内
#    后续 suppress 不重发(避免 15:15/15:30 两周期重复 2 封邮件, 2026-08-01 intraday
#    15:05 schedules 表写错致误报 2 封事故)。key 含日期每天独立; 不走恢复检测(漏跑
#    补跑不发恢复邮件, 跨日静默清理)。新时点漏跑是不同 key 仍发 SEVERE(不 suppress 新时点)。
try:
    from app.calendar import is_trading_day as _is_trading_day
    _is_today_trading = _is_trading_day()
except Exception as _e:
    print(f"[warn] is_trading_day 判断失败(按交易日处理不跳过): {_e}", file=sys.stderr)
    _is_today_trading = True  # 降级: 按交易日处理(不跳过检查), 避免漏报
for t in TASKS:
    # 非交易日跳过交易日任务的漏跑检查(避免周末误报)
    if t.get("trading_day_only") and not _is_today_trading:
        continue
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
                # 漏跑 suppress: key 含日期, 每天每时点独立(不 suppress 新时点)
                missed_key = f"missed|{t['task']}|{sch_hm}|{NOW.strftime('%Y-%m-%d')}"
                seen_keys_this_run.add(missed_key)  # 标记本次仍存在(防误恢复)
                _existing = alert_state.get(missed_key)
                if _existing is None or _existing.get("status") != "active":
                    # 首次发现 或 恢复后再次出现 = 发 SEVERE + 写 state
                    alerts.append(
                        f"SEVERE: {t['task']} 漏跑 计划<{sch_hm}> toler<30min> "
                        f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> last_run<{last_run_str}>"
                    )
                    alert_state[missed_key] = {
                        "status": "active",
                        "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "keyword": f"missed<{sch_hm}>",
                        "line_sample": f"last_run<{last_run_str}>",
                    }
                else:
                    # 已 active = suppress 不重发, 只 log
                    print(
                        f"[suppress] {t['task']} 漏跑 计划<{sch_hm}> 持续中, "
                        f"last_alerted={_existing.get('last_alerted')}, 不重发"
                    )

# 2) 退出失败检查：从 schedule_stats.json 读 last_exit（非 null 且非 0 = 失败）
#    去重(2026-07-25)：exit!=0 但 last_run 距今 >24h 的旧告警不重复 SEVERE。
#    根因场景：etf_national_team 7/24 20:07 collector crash last_exit=143(假告警)，
#    根因已闭环(bba5ecaa deploy根治 + 6824a43c 真实exit code + c1921857 ProcessPool修crash)，
#    但 stats 旧记录未清(周末不跑，周一 20:07 跑才更新)，schedule_monitor 每15min读到
#    exit=143 非0 -> 持续 SEVERE 告警邮件约192封。
#    去重2(2026-07-30)：exit!=0 走 alert_state.json suppress(与 log异常关键词路径对称)。
#    根因场景：etf_national_team 7/29 21:30 exit=1(deploy rebase失败,a4f48c26修复前),
#    24h 内 schedule_monitor 每15min读到 exit=1 -> 持续 SEVERE 邮件约50封(轰炸用户)。
#    根因:exit!=0 路径只做24h stale去重,没走 alert_state suppress(每15min append SEVERE)。
#    修复:同task同exit_code首次发SEVERE+写state active,持续suppress,exit变0/null发恢复邮件。
#    规则：last_run 距今 >24h 且 exit!=0 = 旧问题(任务超1天没跑)，等下次任务跑更新
#    stats 自动清除，降级 log INFO 不重复 SEVERE；最近 24h 内 exit!=0 首次发SEVERE+suppress(不重发)。
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

# 执行耗时阈值(R2迁移72h监控 2026-08-08): 移到循环外避免每次迭代重建(L2)
DUR_THRESHOLDS = {
    "intraday_snapshot": 600,   # 10min
    "update_all": 1800,         # 30min
    "backfill_evening": 1800,   # 30min
    "us_stock_morning": 900,    # 15min
}
# stats 初始化(2026-08-14 A1 补): A1 进行中检测块引用 stats, 须保证 STATS_FILE 不存在/
#   解析失败时 stats 仍为 [] 而非 NameError(否则进行中检测整块崩溃)。
stats = []
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
                # 去重 key: task|exit!=0|exit_code (与 log异常关键词路径结构对称)
                # 标记本次仍存在(防误报恢复),无论 stale 与否(与 log关键词路径 L250-251 同逻辑)
                dedup_key = f"{s['task']}|exit!=0|{exit_code}"
                seen_keys_this_run.add(dedup_key)
                if is_stale:
                    # 旧告警已过期(任务>24h没跑)，等下次任务跑更新 stats 自动清除，不重复 SEVERE
                    # state 保持 active(stale 不触发误恢复),等任务真正跑 exit=0/null 才恢复
                    print(
                        f"[info] {s['task']} 退出失败 last_exit={exit_code} "
                        f"last_run={last_run_str} 距今>{int(STALE_EXIT_THRESHOLD.total_seconds()//3600)}h, "
                        f"旧告警已过期,等下次任务跑更新(不重复 SEVERE)"
                    )
                else:
                    existing = alert_state.get(dedup_key)
                    if existing is None or existing.get("status") != "active":
                        # 首次发现 或 恢复后再次出现 = 发 SEVERE + 写 state
                        alerts.append(
                            f"SEVERE: {s['task']} 退出失败 last_exit={exit_code} "
                            f"last_run={last_run_str}"
                        )
                        alert_state[dedup_key] = {
                            "status": "active",
                            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": f"exit={exit_code}",
                            "line_sample": f"last_run={last_run_str}",
                        }
                    else:
                        # 已 active = 抑制不重发,只 log
                        print(
                            f"[suppress] {s['task']} 退出失败(exit={exit_code}) 持续中, "
                            f"last_alerted={existing.get('last_alerted')}, 不重发"
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
            # 维度③: 执行耗时阈值检查（R2迁移72h监控 2026-08-08）
            # schedule_stats.json 的 last_duration_sec 字段,超阈值告警(进程退化/卡死信号)。
            # intraday ~7min正常 >600s(10min)告警(重叠下一10min槽=下轮读旧数据);
            # update_all ~11min正常 >1800s(30min)告警; backfill ~22min >1800s(30min)告警;
            # us_stock_morning ~10min >900s(15min)告警。
            # 只检查最近 24h 内完成的任务(stale 不重复告警,同 exit/log_anomaly 逻辑)。
            # 恢复检测: dur 降回阈值内 -> key 未 seen -> L476 恢复循环自动发恢复邮件。
            _dur = s.get("last_duration_sec")
            _dur_task = s.get("task")
            # 2026-08-14 告警优化 A1: 进行中任务收集到 in_progress_tasks。
            # "进行中"信号 = last_duration_sec 为 None(有 start 无 end, gen_schedule_stats
            #   写 null)。注意 last_exit 是"上一次退出码", 卡死/在跑时仍可能为 0(上次成功),
            #   不能用 exit is None 判定(8-14 update_all 卡死 exit=0 dur=None 实测)。
            #   排除 exit!=0(失败/被杀, 已由退出检查告警, 防重复)。
            # 用途: ①进行中超时检测(A1新增块) ②恢复检测循环跳过该任务的 key
            #   (防 8-14 误恢复: update_all 卡死 dur=null, 未 seen -> 误判"已消失")。
            if _dur is None and _dur_task in DUR_THRESHOLDS and s.get("last_exit") in (None, 0):
                in_progress_tasks.add(_dur_task)
            if _dur is not None and _dur_task in DUR_THRESHOLDS:
                _dur_thresh = DUR_THRESHOLDS[_dur_task]
                if _dur > _dur_thresh:
                    _dur_lr = s.get("last_run") or ""
                    _dur_stale = False
                    if _dur_lr:
                        try:
                            _dur_lr_dt = datetime.strptime(_dur_lr, "%Y-%m-%d %H:%M")
                            if NOW - _dur_lr_dt > STALE_EXIT_THRESHOLD:
                                _dur_stale = True
                        except ValueError:
                            pass
                    if not _dur_stale:
                        _dur_key = f"{_dur_task}|dur>{_dur_thresh}s"
                        seen_keys_this_run.add(_dur_key)
                        _ex_dur = alert_state.get(_dur_key)
                        if _ex_dur is None or _ex_dur.get("status") != "active":
                            alerts.append(
                                f"SEVERE: {_dur_task} 执行耗时 {_dur}s 超阈值 {_dur_thresh}s "
                                f"last_run<{_dur_lr}> (进程退化/卡死信号)"
                            )
                            alert_state[_dur_key] = {
                                "status": "active",
                                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                                "keyword": f"dur>{_dur_thresh}s",
                                "line_sample": f"dur={_dur}s last_run={_dur_lr}",
                            }
                        else:
                            print(f"[suppress] {_dur_task} 耗时超阈值持续中, "
                                  f"last_alerted={_ex_dur.get('last_alerted')}, 不重发")
    except Exception as e:
        print(f"[warn] 解析 schedule_stats.json 失败: {e}", file=sys.stderr)

# A1 进行中超时检测（2026-08-14 告警优化）: 任务卡死/异常慢(未完成)检测。
# 背景: 原 dur 检查只查"已完成"任务(last_duration_sec 非 null), 任务进行中超时
#   (未完成, dur=null)完全不检查 -> 8-14 update_all 17:50 卡死 54min+ 无超时告警;
#   同时 dur=null 时 key 未 seen, 恢复检测循环误判"异常已消失"发恢复邮件。
# 规则: 对每个进行中任务(dur=null + exit=null, 已收集 in_progress_tasks), 取今日
#   最近一次已到计划时点 sch, 若 last_run >= sch(任务确在该时点启动) 且
#   NOW > sch + 耗时阈值 + 缓冲 -> 超时告警。缓冲(IN_PROGRESS_BUFFER)防正常偏慢误报
#   (update_all +20min / backfill +15min, 对齐主控要求 update_all+50min/backfill+45min)。
# 超时 key 进 seen_keys_this_run(防误恢复), 已 active 则 suppress 不重发。
IN_PROGRESS_BUFFER = {
    "update_all": 20,          # 计划17:50 +30min阈值 +20min缓冲 = 18:40 未完成告警
    "backfill_evening": 15,    # +30min +15min = 45min
    "intraday_snapshot": 10,
    "us_stock_morning": 10,
}
_task_sched_map = {t["task"]: t["schedules"] for t in TASKS}
_stats_by_task = {s.get("task"): s for s in stats if isinstance(s, dict)}
for _ip_task in sorted(in_progress_tasks):
    _ip_scheds = _task_sched_map.get(_ip_task, [])
    _ip_dur_thresh = DUR_THRESHOLDS[_ip_task]
    _ip_buffer = IN_PROGRESS_BUFFER.get(_ip_task, 0)
    # 今日最近一次已到计划时点(<= NOW)
    _sch_dts = []
    for _h in _ip_scheds:
        _st = today_schedule(_h)
        if _st <= NOW:
            _sch_dts.append(_st)
    if not _sch_dts:
        continue
    _latest_sch = max(_sch_dts)
    _ip_stats = _stats_by_task.get(_ip_task, {})
    _ip_lr = _ip_stats.get("last_run") or ""
    _ip_started_at_sch = False
    if _ip_lr:
        try:
            _ip_lr_dt = datetime.strptime(_ip_lr, "%Y-%m-%d %H:%M")
            if _ip_lr_dt >= _latest_sch:
                _ip_started_at_sch = True
        except ValueError:
            pass
    if not _ip_started_at_sch:
        continue
    _timeout_at = _latest_sch + timedelta(seconds=_ip_dur_thresh) + timedelta(minutes=_ip_buffer)
    if NOW <= _timeout_at:
        continue
    _run_min = int((NOW - _latest_sch).total_seconds() // 60)
    _ip_key = f"{_ip_task}|in_progress_timeout"
    seen_keys_this_run.add(_ip_key)
    _ex_ip = alert_state.get(_ip_key)
    if _ex_ip is None or _ex_ip.get("status") != "active":
        alerts.append(
            f"SEVERE: {_ip_task} 超时未完成 已运行{_run_min}min "
            f"(计划<{_latest_sch.strftime('%H:%M')}> + 阈值{_ip_dur_thresh}s + 缓冲{_ip_buffer}min"
            f"=<{_timeout_at.strftime('%H:%M')}> 仍未完成, 疑似卡死/异常慢) last_run<{_ip_lr}>"
        )
        alert_state[_ip_key] = {
            "status": "active",
            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "keyword": "in_progress_timeout",
            "line_sample": f"run={_run_min}min last_run={_ip_lr}",
        }
    else:
        print(f"[suppress] {_ip_task} 进行中超时持续中, "
              f"last_alerted={_ex_ip.get('last_alerted')}, 不重发")

# 5) launchctl 加载检查（2026-07-20 补缺口，方案D）
#    11个 com.trade label（9监控任务 + self-heal，不含 schedule-monitor 自己防递归）。
#    未加载（plist 手动 unload / bootstrap 失败 / 系统重启后未恢复）= launchd 层挂了，
#    下游 schedule_stats/漏跑检查/退出检查全失效（任务根本不会跑），靠 launchctl print 探测。
#    复用 self_heal.sh L73 launchctl_state 逻辑：returncode!=0 或无 `state = ` 行 = 未加载。
#    调用失败（timeout/异常）保守视为未加载（告警），避免 launchctl 故障漏报。
#    alert_state 去重（与 exit!=0 / log_anomaly 路径对称）：
#      key=`{label}|not_loaded`，首次发 SEVERE + 写 state active + seen_keys_this_run 标记，
#      已 active = suppress 不重发，恢复（seen 但 not_loaded 消失）发恢复邮件。
#    插入位置选在恢复检测(L476)之前：alert_state 修改需在 L509 save 之前完成，
#    seen_keys_this_run 标记需在 L476 恢复检测之前完成（否则 launchctl key 未 seen 被误报恢复）。
LAUNCHCTL_LABELS = [
    "com.trade.update-all",
    "com.trade.backfill-evening",
    "com.trade.intraday-snapshot",
    "com.trade.futures-backfill",
    "com.trade.lhb-backfill",
    "com.trade.rzhb-backfill",
    "com.trade.us-stock-morning",
    "com.trade.etf-national-team",
    "com.trade.lab-auto",
    "com.trade.self-heal",
    # 不含 com.trade.schedule-monitor 自己（防递归，靠 heartbeat 兜底）
]


def launchctl_loaded(label):
    """检查 launchd label 是否已加载（复用 self_heal.sh L73 launchctl_state 逻辑）。
    returncode!=0 或无 `state = ` 行 = 未加载。调用失败（timeout/异常）保守视为未加载（告警）。
    """
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return False  # 调用失败保守视为未加载（告警）
    if r.returncode != 0:
        return False
    return bool(re.search(r"^\s*state = .+$", r.stdout, re.MULTILINE))


for _label in LAUNCHCTL_LABELS:
    if launchctl_loaded(_label):
        continue  # 已加载，不 add seen（让恢复检测处理 active/pending->recovered）
    dedup_key = f"{_label}|not_loaded"
    seen_keys_this_run.add(dedup_key)
    _existing = alert_state.get(dedup_key)
    # 通知分级(2026-08-10): not_loaded 可被 self_heal.sh 自动恢复, 连续N次才通知
    if _existing is None or _existing.get("status") == "recovered":
        alert_state[dedup_key] = {
            "status": "pending",
            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "last_alerted": None,
            "consecutive_count": 1,
            "keyword": "not_loaded",
            "line_sample": f"launchctl print gui/{os.getuid()}/{_label} 未加载",
            "tier": "self_heal",
        }
        print(f"[self_heal pending] {_label} 未加载(自愈类), 连续1/{SELF_HEAL_THRESHOLD}, 暂不通知")
    elif _existing.get("status") == "pending":
        _nl_count = _existing.get("consecutive_count", 0) + 1
        if _nl_count >= SELF_HEAL_THRESHOLD:
            alerts.append(
                f"SEVERE: {_label} 未加载，需 launchctl bootstrap "
                f"~/Library/LaunchAgents/{_label}.plist 恢复"
            )
            _existing["status"] = "active"
            _existing["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            _existing["consecutive_count"] = _nl_count
            print(f"[self_heal escalated] {_label} 连续{_nl_count}次未加载, 发送告警")
        else:
            _existing["consecutive_count"] = _nl_count
            print(f"[self_heal pending] {_label} 连续{_nl_count}/{SELF_HEAL_THRESHOLD}次未加载, 暂不通知")
    elif _existing.get("status") == "active":
        # 已 active = 抑制不重发,只 log
        print(
            f"[suppress] {_label} 未加载持续中, "
            f"last_alerted={_existing.get('last_alerted')}, 不重发"
        )

# 恢复检测: state 里 active 但本次未 seen = 异常已消失,发恢复邮件
# (gen_schedule_stats 每任务只记首个命中,故每 task 至多1个 active key)
# 漏跑 key(missed|...) 特殊处理: 不发恢复邮件(漏跑补跑不需通知, 任务补跑 stats
# 自更新), 跨日(日期<今天)静默清理(昨天漏跑 key 今天不检查了)。
# 同日窗口外未 seen 保持 active(任务可能真漏跑未补, 等 next day 跨日清理)。
for _key, _info in list(alert_state.items()):
    # 通知分级(2026-08-10): pending(自愈类未通知) 未 seen = 静默恢复(不发恢复邮件)
    if _info.get("status") == "pending":
        # r2_/72h_ 有自己的 inline 恢复检测, 不在此处理
        if _key.startswith("r2_") or _key.startswith("72h_"):
            continue
        if _key not in seen_keys_this_run:
            _info["status"] = "recovered"
            _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
            print(f"[silent recovery] {_key} 自愈类异常已消失(未通知过)")
        continue
    if _info.get("status") != "active":
        continue
    if _key == "overview_lag_3domain" or _key.startswith("r2_") or _key.startswith("72h_"):
        # overview 时效滞后的去重+恢复由 overview 检查块内联处理
        # （该块在恢复检测循环之后运行，不能复用此循环，否则未 seen 被误报恢复）
        # R2 keys(r2_unreachable/r2_overview_lag/r2_intraday_lag)同理: R2检查块在
        # 恢复循环之后运行, 由 R2块内联处理恢复(C1修复: 否则每15min 2封邮件)
        # 72h_ keys 由 monitor_72h.sh 独立管理(自己的恢复检测循环 L689-705),
        # schedule_monitor 不检查 72h 条件(sw_version/S5/stale_alert), 不应对其做
        # 恢复检测 -- 否则 72h_ active key 不在 seen_keys_this_run 被误判"已恢复"
        # -> :15/:45 误恢复 + :10/:40 72h重报 = 振荡(2026-08-10 修复)
        continue
    # 2026-08-14 告警优化 A1: 任务仍在进行中(dur=null + exit=null)时, 其历史异常 key
    # 不能判"已恢复" -> 防 8-14 误恢复(update_all 卡死 dur=null 未 seen 被误判异常已消失,
    # 18:00 误发 [恢复] update_all)。保持 active, 等任务真正完成(exit 非0/耗时超/或进行中
    # 超时告警)后再走恢复逻辑。
    if "|" in _key and _key.split("|", 1)[0] in in_progress_tasks:
        print(f"[hold] {_key} 任务仍在进行中(dur=null), 不判恢复(保持 active)")
        continue
    if _key not in seen_keys_this_run:
        if _key.startswith("missed|"):
            # 漏跑 key: 不发恢复邮件, 检查是否跨日静默清理
            # key 格式: missed|{task}|{sch_hm}|{YYYY-MM-DD}
            parts = _key.split("|")
            if len(parts) == 4 and parts[3] < NOW.strftime("%Y-%m-%d"):
                _info["status"] = "recovered"
                _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[cleanup] 漏跑 key {_key} 跨日清理(不发恢复邮件)")
            # 同日: 保持 active(窗口外未 seen, 任务可能真漏跑未补)
            continue
        _task = _key.split("|", 1)[0] if "|" in _key else _key
        _kw = _info.get("keyword", "?")
        # A3: 静默窗口检查须在覆盖 last_recovered 之前(用旧值判断)
        _emit = _recovery_cooldown_ok(_key, _info)
        _info["status"] = "recovered"
        _info["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
        if _emit:
            recoveries.append({
                "task": _task,
                "keyword": _kw,
                "first_seen": _info.get("first_seen", "?"),
            })
        else:
            print(
                f"[cooldown] {_task} 恢复邮件静默(上次恢复 <{RECOVERY_COOLDOWN} 前), "
                f"状态已置 recovered 但不发邮件 (首次发现: {_info.get('first_seen')})"
            )
        print(
            f"[recovery] {_task} 异常关键词 {_kw} 已消失 "
            f"(首次发现: {_info.get('first_seen')})"
        )
save_alert_state(alert_state)

# 3) ETF 汪汪队耗时阈值检查（B4 稳定性 2026-07-24）
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
#    仅交易日盘中 09:50-15:05 检查（intraday 每10min推一次，盘中最后 15:02，盘后 15:35/20:35），
#    09:50 起检避开开盘空窗期 overview.json 仍是凌晨旧版导致的误报；避免非交易时段误报。
#    15:05 上限：15:05 时 intraday 15:02 刚推完（完成~15:05）lag≈0-3min 安全；15:15/15:30 是
#    intraday 空窗期（15:02 已推、15:35 未推）检查必误报，故窗口不含 15:15/15:30。
#    2026-07-20 15:30 误报事故根因：窗口含 15:30，overview 停在 15:02 lag=27min>20min 阈值必报。
#    多域名容错：依次试 ss.fx8.store/sss.sugas.site/s.sugas.site，任一不 lag 即 OK，
#    规避 CF Workers cache 滞后单域名误报。滞后 > 20min（3域名全 lag）告警 SEVERE
#    （intraday 10min 频率 + 10min buffer；2026-07-24 从 30min 改 20min 适配 10min 频率）。
#    curl 超时 8s（subprocess timeout 12s 兜底）不阻塞 launchd 15min 周期。
#    用 /usr/bin/curl 而非 urllib：venv python 缺系统 CA 证书会 SSL 校验失败，curl 走系统证书更稳。
try:
    from app.calendar import is_trading_day
    now_hm = NOW.strftime("%H%M")
    # 0950 起检：intraday 第一次 09:35，dur 约 7min（任务2优化后），09:42 才完成 push。
    # 0930-0942 开盘空窗期 overview.json 必然是凌晨 02:38 旧版，必触发误报。
    # 0950 检查避开空窗，覆盖盘中其余时点（intraday 每 10min 推一次）。
    # 1130-1315 排除午休窗口：A股午休 11:30-13:00 无交易，overview.json collected_at
    # 停在上午 11:30 快照(完成于 ~11:37)，直到 13:05 快照完成(~13:12)才更新。
    # 此窗口内 lag 必然 >20min 但属正常(午休没交易)，排除避免误报。
    # 2026-07-24 12:30 误报事故根因：午休未排除，12:15 起 lag>30min 触发 SEVERE。
    # 非交易日已由 is_trading_day() 排除（周末/节假日 overview 滞后正常）。
    if is_trading_day() and "0950" <= now_hm <= "1505" and not ("1130" <= now_hm < "1315"):
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
        dedup_key = "overview_lag_3domain"
        if all_lag:
            seen_keys_this_run.add(dedup_key)
            now_full = NOW.strftime("%Y-%m-%d %H:%M:%S")
            detail = "; ".join(
                f"{b}={ca or 'N/A'} lag={lm if lm is not None else '?'}min [{st}]"
                for b, ca, lm, st in lag_results
            )
            _existing = alert_state.get(dedup_key)
            if _existing is None or _existing.get("status") != "active":
                # 首次发现 或 恢复后再次出现 = 发 SEVERE + 写 state
                alerts.append(
                    f"SEVERE: 线上 overview.json 时效滞后(3域名全lag) "
                    f"threshold<20min> now<{now_full}> 详情: {detail}"
                )
                alert_state[dedup_key] = {
                    "status": "active",
                    "first_seen": now_full,
                    "last_alerted": now_full,
                    "keyword": "overview_lag",
                    "line_sample": detail,
                }
            else:
                # 已 active = 抑制不重发, 只 log
                print(
                    f"[suppress] overview 时效滞后持续中, "
                    f"last_alerted={_existing.get('last_alerted')}, 不重发"
                )
        else:
            # 时效恢复: was active -> resolved, 发恢复邮件(内联, 不复用 L476 恢复循环
            # 因 overview 检查在恢复循环之后运行, 复用会被误报恢复)
            _existing = alert_state.get(dedup_key)
            if _existing is not None and _existing.get("status") == "active":
                # A3: 静默窗口(用旧 last_recovered 判断)
                _emit = _recovery_cooldown_ok(dedup_key, _existing)
                _existing["status"] = "recovered"
                _existing["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                if _emit:
                    recoveries.append({
                        "task": "overview_lag",
                        "keyword": "overview_lag",
                        "first_seen": _existing.get("first_seen", "?"),
                    })
                else:
                    print(f"[cooldown] overview 时效恢复邮件静默(上次恢复<30min前), 状态已置 recovered")
                print(
                    f"[recovery] overview 时效滞后已恢复 "
                    f"(首次发现: {_existing.get('first_seen')})"
                )
        # overview 检查在 save_alert_state(L509) 之后运行, 需补存防状态丢失
        save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] 线上 overview.json 时效检查失败: {e}", file=sys.stderr)

# 6) R2 直连时效检查（维度⑥，R2迁移后72h监控 2026-08-08）
#    R2 公开桶(ssd.fx8.store)是前端大文件 + Worker /data/rewrite 的唯一数据源。
#    upload_r2 失败/遗漏 -> R2 数据滞后 -> Worker 60s TTL 过期后仍读 R2 旧版 = 线上滞后。
#    此检查直连 R2 验证 upload_r2 链路:
#    - overview.json collected_at 时效(交易日盘中<20min, 非交易时段<24h防周末断链)
#    - intraday_snapshot.json collected_at 时效(交易日盘中<15min)
#    - R2 可达性(ssd.fx8.store 200响应, R2桶/网络故障告警)
#    告警走 alert_state.json 去重(key=r2_overview_lag/r2_intraday_lag/r2_unreachable),
#    与现有 overview_lag_3domain(Worker路径 ss.fx8.store) 对称, 两层独立检查:
#      R2直连stale + Worker路径stale = upload_r2 断(根因在R2上传)
#      R2直连fresh + Worker路径stale = CF cache purge 失效(根因在Worker缓存)
#    恢复检测: 内联处理(此块在 L476 恢复循环之后运行, 不能复用该循环)。
try:
    R2_BASE = "https://ssd.fx8.store"

    def _parse_flexible_ts(ts_str):
        """解析 overview(YYYYMMDD HH:MM:SS) 或 intraday(ISO T+microsec) 格式时间戳"""
        if not ts_str:
            return None
        for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        return None

    def _curl_r2_json(filename, timeout=8):
        """curl R2 直连获取 JSON body, 返回 (data_dict, error_str)"""
        url = f"{R2_BASE}/data/{filename}"
        try:
            result = subprocess.run(
                ["/usr/bin/curl", "-sS", "--max-time", str(timeout), url],
                capture_output=True, text=True, timeout=timeout + 4,
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
        if result.returncode != 0:
            return None, f"curl rc={result.returncode}"
        try:
            return json.loads(result.stdout), None
        except json.JSONDecodeError as e:
            return None, f"json parse fail: {e}"

    now_hm_r2 = NOW.strftime("%H%M")
    is_r2_trading_window = (
        _is_today_trading and "0950" <= now_hm_r2 <= "1505"
        and not ("1130" <= now_hm_r2 < "1315")
    )

    # --- R2 可达性 + overview 时效 ---
    ov_data_r2, ov_err_r2 = _curl_r2_json("overview.json")
    if ov_err_r2:
        # R2 不可达（网络/R2桶故障/upload_r2 完全断）
        _r2_key = "r2_unreachable"
        seen_keys_this_run.add(_r2_key)
        _ex_r2 = alert_state.get(_r2_key)
        if _ex_r2 is None or _ex_r2.get("status") == "recovered":
            alert_state[_r2_key] = {
                "status": "pending",
                "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                "last_alerted": None,
                "consecutive_count": 1,
                "keyword": "r2_unreachable",
                "line_sample": ov_err_r2,
                "tier": "self_heal",
            }
            print(f"[self_heal pending] R2 直连不可达(自愈类), 连续1/{SELF_HEAL_THRESHOLD}, 暂不通知")
        elif _ex_r2.get("status") == "pending":
            _r2_count = _ex_r2.get("consecutive_count", 0) + 1
            if _r2_count >= SELF_HEAL_THRESHOLD:
                alerts.append(
                    f"SEVERE: R2 直连不可达 ssd.fx8.store/data/overview.json "
                    f"error<{ov_err_r2}> now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> "
                    f"(R2桶/网络故障, upload_r2 链路断)"
                )
                _ex_r2["status"] = "active"
                _ex_r2["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                _ex_r2["consecutive_count"] = _r2_count
                print(f"[self_heal escalated] R2 直连不可达连续{_r2_count}次, 发送告警")
            else:
                _ex_r2["consecutive_count"] = _r2_count
                print(f"[self_heal pending] R2 直连不可达, 连续{_r2_count}/{SELF_HEAL_THRESHOLD}, 暂不通知")
        elif _ex_r2.get("status") == "active":
            print(f"[suppress] R2 直连不可达持续中, "
                  f"last_alerted={_ex_r2.get('last_alerted')}, 不重发")
    else:
        # R2 可达 -> 恢复检测(r2_unreachable)
        _ex_r2u = alert_state.get("r2_unreachable")
        if _ex_r2u is not None:
            if _ex_r2u.get("status") == "active":
                # A3: 静默窗口
                _emit = _recovery_cooldown_ok("r2_unreachable", _ex_r2u)
                _ex_r2u["status"] = "recovered"
                _ex_r2u["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                if _emit:
                    recoveries.append({
                        "task": "r2_unreachable", "keyword": "r2_unreachable",
                        "first_seen": _ex_r2u.get("first_seen", "?"),
                    })
                else:
                    print(f"[cooldown] r2_unreachable 恢复邮件静默(上次恢复<30min前)")
                print(f"[recovery] R2 直连不可达已恢复 "
                      f"(首次发现: {_ex_r2u.get('first_seen')})")
            elif _ex_r2u.get("status") == "pending":
                _ex_r2u["status"] = "recovered"
                _ex_r2u["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[silent recovery] R2 直连不可达已恢复(未通知过)")

        # overview collected_at 时效 (M1: 非交易日跳过, 对齐 overview_lag_3domain 只交易日;
        # 原非交易时段24h阈值致周五20:35->周六24h+1min误报持续到周一)
        ov_collected_r2 = ov_data_r2.get("collected_at") or ""
        ov_dt_r2 = _parse_flexible_ts(ov_collected_r2)
        if ov_dt_r2 and _is_today_trading:
            ov_lag_r2 = NOW - ov_dt_r2
            ov_lag_min_r2 = int(ov_lag_r2.total_seconds() // 60)
            # 交易日盘中 20min(同 overview_lag_3domain), 交易日非盘中 24h(防盘后断链)
            ov_thresh_r2 = timedelta(minutes=20) if is_r2_trading_window else timedelta(hours=24)
            if ov_lag_r2 > ov_thresh_r2:
                _r2_ov_key = "r2_overview_lag"
                seen_keys_this_run.add(_r2_ov_key)
                _ex_r2ov = alert_state.get(_r2_ov_key)
                if _ex_r2ov is None or _ex_r2ov.get("status") != "active":
                    _thresh_min = int(ov_thresh_r2.total_seconds() // 60)
                    alerts.append(
                        f"SEVERE: R2 overview.json 时效滞后 "
                        f"collected_at<{ov_collected_r2}> lag={ov_lag_min_r2}min "
                        f"threshold<{_thresh_min}min> "
                        f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> (upload_r2 未推新版)"
                    )
                    alert_state[_r2_ov_key] = {
                        "status": "active",
                        "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                        "keyword": "r2_overview_lag",
                        "line_sample": f"lag={ov_lag_min_r2}min collected_at={ov_collected_r2}",
                    }
                else:
                    print(f"[suppress] R2 overview 滞后持续中, "
                          f"last_alerted={_ex_r2ov.get('last_alerted')}, 不重发")
            else:
                # 恢复检测
                _ex_r2ov = alert_state.get("r2_overview_lag")
                if _ex_r2ov is not None and _ex_r2ov.get("status") == "active":
                    # A3: 静默窗口
                    _emit = _recovery_cooldown_ok("r2_overview_lag", _ex_r2ov)
                    _ex_r2ov["status"] = "recovered"
                    _ex_r2ov["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                    if _emit:
                        recoveries.append({
                            "task": "r2_overview_lag", "keyword": "r2_overview_lag",
                            "first_seen": _ex_r2ov.get("first_seen", "?"),
                        })
                    else:
                        print(f"[cooldown] r2_overview_lag 恢复邮件静默(上次恢复<30min前)")
                    print(f"[recovery] R2 overview 时效滞后已恢复 "
                          f"(首次发现: {_ex_r2ov.get('first_seen')})")

    # --- intraday_snapshot 时效（仅交易日盘中, 同 overview 窗口）---
    if is_r2_trading_window:
        id_data_r2, id_err_r2 = _curl_r2_json("intraday_snapshot.json")
        if id_err_r2:
            print(f"[warn] R2 intraday_snapshot 不可达: {id_err_r2} "
                  f"(盘中才检查, 非致命)", file=sys.stderr)
        elif id_data_r2:
            id_collected_r2 = id_data_r2.get("collected_at") or ""
            id_dt_r2 = _parse_flexible_ts(id_collected_r2)
            if id_dt_r2:
                id_lag_r2 = NOW - id_dt_r2
                id_lag_min_r2 = int(id_lag_r2.total_seconds() // 60)
                id_thresh_r2 = timedelta(minutes=15)
                if id_lag_r2 > id_thresh_r2:
                    _r2_id_key = "r2_intraday_lag"
                    seen_keys_this_run.add(_r2_id_key)
                    _ex_r2id = alert_state.get(_r2_id_key)
                    if _ex_r2id is None or _ex_r2id.get("status") != "active":
                        alerts.append(
                            f"SEVERE: R2 intraday_snapshot.json 时效滞后 "
                            f"collected_at<{id_collected_r2}> lag={id_lag_min_r2}min "
                            f"threshold<15min> "
                            f"now<{NOW.strftime('%Y-%m-%d %H:%M:%S')}> "
                            f"(upload-intraday 未推新版)"
                        )
                        alert_state[_r2_id_key] = {
                            "status": "active",
                            "first_seen": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_alerted": NOW.strftime("%Y-%m-%d %H:%M:%S"),
                            "keyword": "r2_intraday_lag",
                            "line_sample": f"lag={id_lag_min_r2}min collected_at={id_collected_r2}",
                        }
                    else:
                        print(f"[suppress] R2 intraday 滞后持续中, "
                              f"last_alerted={_ex_r2id.get('last_alerted')}, 不重发")
                else:
                    # 恢复检测
                    _ex_r2id = alert_state.get("r2_intraday_lag")
                    if _ex_r2id is not None and _ex_r2id.get("status") == "active":
                        # A3: 静默窗口
                        _emit = _recovery_cooldown_ok("r2_intraday_lag", _ex_r2id)
                        _ex_r2id["status"] = "recovered"
                        _ex_r2id["last_recovered"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
                        if _emit:
                            recoveries.append({
                                "task": "r2_intraday_lag", "keyword": "r2_intraday_lag",
                                "first_seen": _ex_r2id.get("first_seen", "?"),
                            })
                        else:
                            print(f"[cooldown] r2_intraday_lag 恢复邮件静默(上次恢复<30min前)")
                        print(f"[recovery] R2 intraday 时效滞后已恢复 "
                              f"(首次发现: {_ex_r2id.get('first_seen')})")

    # R2 检查在 save_alert_state(L509/L660) 之后运行, 需补存防状态丢失
    save_alert_state(alert_state)
except Exception as e:
    print(f"[warn] R2 直连时效检查失败: {e}", file=sys.stderr)

# B2 告警正文模板化（2026-08-14 告警优化）: 原正文=纯 SEVERE 行列表, 改为每项 4 行模板
#   [严重度] 任务 异常类型 / 影响:XX / 日志:路径 / 建议:XX。按任务写对应影响与建议。
_IMPACT_MAP = {
    "update_all": "全站 overview/评分/预警/ETF清单等数据可能过期或未更新, 前端读到旧版",
    "backfill_evening": "回填数据(指数/分红等)可能缺失或未更新, 前端对应指标读旧",
    "intraday_snapshot": "盘中 overview/intraday 快照可能过期, 前端分时/实时数据读旧",
    "futures_backfill": "期货数据可能缺失或未更新, 前端期货指标读旧",
    "lhb_backfill": "龙虎榜数据可能缺失或未更新, 前端对应展示读旧",
    "rzhb_backfill": "两融数据可能缺失或未更新, 前端对应展示读旧",
    "etf_national_team": "汪汪队 ETF 数据可能过期或未更新, 前端 ETF 板块读旧",
    "lab_auto": "策略实验室回测数据可能未更新, 前端实验室读旧",
    "us_stock_morning": "美股数据可能缺失或未更新, 前端美股指标读旧",
    "overview": "线上 overview.json 时效滞后, 前端首页可能读到旧数据",
    "R2": "R2 存储(ssd.fx8.store)不可达或数据未推新版, 前端大文件/rewrite 数据源断或读旧",
}
_SUGGEST_MAP = {
    "update_all": "自动恢复中; 若持续(超时告警)请人工查 update_all 进程/卡死点",
    "backfill_evening": "自动恢复中; 若持续请人工检查回填进程",
    "intraday_snapshot": "自动恢复中; 若持续请人工检查盘中采集/push 链路",
    "etf_national_team": "自动恢复中; 若持续(进程池退化)请人工检查",
    "overview": "自动恢复中; 若持续请人工查 intraday/push 链路",
    "R2": "自动恢复中; 若持续请人工查 upload_r2/网络/R2 桶",
}
_LOG_MAP = {t["task"]: str(LOG_DIR / t["log"]) for t in TASKS}


def _format_alert_item(line):
    """B2: 单条 SEVERE 告警行 -> 4 行模板 HTML。"""
    _text = line[8:] if line.startswith("SEVERE: ") else line  # "SEVERE: "=8字符
    _first = _text.split(" ", 1)[0] if " " in _text else _text
    _task = _first
    if _first.startswith("com.trade."):
        _task = _first.replace("com.trade.", "").replace("-", "_")
    elif _first == "线上":
        _task = "overview"
    _impact = _IMPACT_MAP.get(_task, "对应任务数据可能过期或未更新, 前端可能读到旧数据")
    _sugg = _SUGGEST_MAP.get(_task, "自动恢复中; 若持续异常请人工介入检查")
    _log = _LOG_MAP.get(_task, str(MONITOR_LOG))
    _esc = lambda s: str(s).replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    return (
        f"<b>[SEVERE] {_esc(_text)}</b><br>"
        f"影响: {_esc(_impact)}<br>"
        f"日志: {_esc(_log)}<br>"
        f"建议: {_esc(_sugg)}"
    )


# 输出 + 告警
now_str = NOW.strftime("%Y-%m-%d %H:%M:%S")
if alerts:
    print(f"[{now_str}] 检测到 {len(alerts)} 个告警:")
    for a in alerts:
        print(a)
    # 复用 notify.py 发邮件 + 写 alerts/latest.md（subject 统一模板 [告警] ... MM-DD HH:MM）
    # --from-prefix "[告警]" -> 发件人名 "[告警] 信号实验室"
    # B2(2026-08-14): 正文由纯 SEVERE 行列表改为每项 4 行模板(严重度/影响/日志/建议)
    body = "<br><br>".join(_format_alert_item(a) for a in alerts)
    _sm_time = NOW.strftime("%m-%d %H:%M")
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            f"[告警] {len(alerts)}项计划任务异常 {_sm_time}",
            body,
            "--severe",
            "--from-prefix", "[告警]",
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
        subject = f"[恢复] {r0['task']} {r0['keyword']} {NOW.strftime('%m-%d %H:%M')}"
    else:
        subject = f"[恢复] {len(recoveries)}项异常恢复 {NOW.strftime('%m-%d %H:%M')}"
    rec_lines = [
        f"[恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失 "
        f"(首次发现: {r['first_seen']}, 恢复时间: {now_str})"
        for r in recoveries
    ]
    # B2(2026-08-14): 恢复邮件尾加"无需操作,已自动恢复"提示
    rec_lines.append("— 无需操作, 异常已自动恢复 —")
    body = "<br>".join(
        l.replace("<", "&lt;").replace(">", "&gt;") for l in rec_lines
    )
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            subject,
            body,
            "--from-prefix", "[恢复]",
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
