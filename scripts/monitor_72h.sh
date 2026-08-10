#!/bin/bash
# monitor_72h.sh - 72h 持续监控（独立脚本，不碰 schedule_monitor.sh 生产脚本）
#
# 覆盖 5 类缺口（schedule_monitor 每15min 已覆盖的 9 任务漏跑/退出/log异常/耗时/launchctl加载
# /ETF耗时/overview时效/R2可达性 不重复）：
#   1) 采集补充：public_fund 系列 10 个 plist 漏跑检查（launchctl 加载 + 日频任务 log 时效）
#   2) 上传 R2：index/industry/trade_sim/public_fund/signal_kelly 各前缀代表性文件 200 + 非空
#   3) 发布 push main：git log origin/main 时效 + 线上 sw.js CACHE_VERSION vs 本地一致 + overview date 一致
#   4) 功能稳定性：P0 smoke 8 项 curl JSON 数据层（overview/intraday/index etfs/board_etf_map/alert/boot/trade_sim/notifications）
#   5) 功能及时性：signal_kelly annualized_return 口径（<100% = OK，>100% = 旧 258% 公式 SEVERE）+ 日频数据时效
#
# 72h 超时自停：启动时写 /tmp/monitor_72h_start 时间戳，每次跑检查 elapsed>72h 则 launchctl bootout 自卸载 + notify。
# 告警：复用 notify.py + alert_state.json（key 前缀 72h_ 避免与 schedule_monitor 冲突）。
# 频率：launchd 每30min（Minute=10/40），与 schedule_monitor(0/15/30/45) + self_heal(7/22/37/52) 错开。
# 安全：只读 curl + launchctl + git log + 本地文件检查，不 push main 不写 DB 不跑采集，零生产风险。
#
# launchd plist: ~/Library/LaunchAgents/com.trade.monitor-72h.plist（临时72h，不 commit git）
set -uo pipefail
REPO="${REPO:-/Users/linhuichen/code/trade-data}"
cd "$REPO"
export REPO

START_FILE="/tmp/monitor_72h_start"
HEARTBEAT_FILE="/tmp/monitor_72h_heartbeat.txt"
PLIST_PATH="$HOME/Library/LaunchAgents/com.trade.monitor-72h.plist"

# --- 72h 超时自停检查 ---
if [ ! -f "$START_FILE" ]; then
  date '+%Y-%m-%d %H:%M:%S' > "$START_FILE"
fi
START_TIME=$(cat "$START_FILE")
ELAPSED=$("$REPO/.venv/bin/python" -c "
from datetime import datetime
try:
    start = datetime.strptime('$START_TIME', '%Y-%m-%d %H:%M:%S')
    print(int((datetime.now() - start).total_seconds()))
except Exception:
    print(0)
")
if [ "$ELAPSED" -gt 259200 ]; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [72h监控] 已运行${ELAPSED}s 超72h，自动停止" >> "$REPO/data/logs/monitor_72h.log"
  # 通知主控 72h 到期
  "$REPO/.venv/bin/python" "$REPO/scripts/notify.py" \
    "[72h监控] 到期停止 $(date '+%m-%d %H:%M')" \
    "72h 持续监控已运行 ${ELAPSED}s 超72h，自动 launchctl bootout 停止。如需继续请重新加载 plist。" \
    --from-prefix "[72h监控]" \
    --alert-issue "72h监控到期停止" \
    --alert-log "$REPO/data/logs/monitor_72h.log" \
    2>/dev/null || true
  launchctl bootout "gui/$(id -u)" "$PLIST_PATH" 2>/dev/null || true
  rm -f "$START_FILE"
  exit 0
fi

# --- 主检查逻辑（python heredoc，同 schedule_monitor.sh 模式）---
"$REPO/.venv/bin/python" <<'PYEOF' 2>&1
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, date
from pathlib import Path

REPO = Path(os.environ["REPO"])
LOG_DIR = REPO / "data" / "logs"
MONITOR_LOG = LOG_DIR / "monitor_72h.log"
SS_DATA = REPO / "static-site" / "data"
DATA_DIR = REPO / "data"
ALERT_STATE_FILE = DATA_DIR / "alert_state.json"

NOW = datetime.now()
NOW_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")
TODAY = NOW.strftime("%Y%m%d")
TODAY_ISO = NOW.date().isoformat()

# 交易日判断（复用 app.calendar，降级按交易日处理不跳过检查）
# 移到 LAST_TRADING_DAY 之前，因盘前判断依赖 _is_today_trading
try:
    from app.calendar import is_trading_day as _is_trading_day
    _is_today_trading = _is_trading_day()
except Exception as _e:
    print(f"[warn] is_trading_day 判断失败(按交易日处理不跳过): {_e}", file=sys.stderr)
    _is_today_trading = True

# 最近交易日（周末取周五；法定假日人工判断，非交易日 overview.date=最近交易日不算FAIL）
# 交易日盘前(09:25前)：市场未开盘，数据仍为上一交易日，LAST_TRADING_DAY 取上一交易日
_td = NOW.date()
_now_hm_calc = NOW.strftime("%H%M")
_is_before_open = _is_today_trading and _now_hm_calc < "0925"
if _td.weekday() == 5:      # 周六 -> 周五
    LAST_TRADING_DAY = (_td - timedelta(days=1)).strftime("%Y%m%d")
elif _td.weekday() == 6:    # 周日 -> 周五
    LAST_TRADING_DAY = (_td - timedelta(days=2)).strftime("%Y%m%d")
elif _is_before_open:
    # 交易日盘前(09:25前)：数据仍为上一交易日
    # 周一盘前 -> 上周五, 周二-周五盘前 -> 昨日
    _offset = 3 if _td.weekday() == 0 else 1
    LAST_TRADING_DAY = (_td - timedelta(days=_offset)).strftime("%Y%m%d")
else:
    LAST_TRADING_DAY = TODAY

# alert.json 仅 17:50 update_all 更新，交易日17:50前是上一交易日数据（正常）
# 周一盘前 alert.json=周五 但 09:25后 LAST_TRADING_DAY=TODAY(周一) -> 需单独判断
# 否则 S5/stale_alert 检查误报(alert.json date=周五 非 TODAY/LAST_TRADING_DAY)
_is_before_update_all = _is_today_trading and _now_hm_calc < "1750"
if _is_before_update_all:
    # 交易日17:50前：alert.json date 应为上一交易日
    _prev_offset = 3 if _td.weekday() == 0 else 1
    ALERT_EXPECTED_DATE = (_td - timedelta(days=_prev_offset)).strftime("%Y%m%d")
else:
    # 17:50后 or 非交易日：alert.json date 应为最近交易日
    ALERT_EXPECTED_DATE = LAST_TRADING_DAY

alerts = []
recoveries = []
alert_state = {}
seen_keys_this_run = set()


# ==================== 告警去重/恢复机制（复用 schedule_monitor 模式，key 前缀 72h_） ====================

def load_alert_state():
    if not ALERT_STATE_FILE.exists():
        return {}
    try:
        with open(ALERT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[warn] 读 alert_state.json 失败(按空 state 处理): {e}", file=sys.stderr)
        return {}


def save_alert_state(state):
    try:
        ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[warn] 写 alert_state.json 失败: {e}", file=sys.stderr)


alert_state = load_alert_state()


def check_and_alert(dedup_key, message, keyword="", line_sample=""):
    """检查异常并去重告警。key 自动加 72h_ 前缀避免与 schedule_monitor 冲突。
    首次发现/恢复后再次出现 = 发 SEVERE + 写 state active；
    已 active = suppress 不重发。返回 True 表示新告警（需发通知）。"""
    full_key = f"72h_{dedup_key}"
    seen_keys_this_run.add(full_key)
    existing = alert_state.get(full_key)
    if existing is None or existing.get("status") != "active":
        alerts.append(f"SEVERE: {message}")
        alert_state[full_key] = {
            "status": "active",
            "first_seen": NOW_STR,
            "last_alerted": NOW_STR,
            "keyword": keyword or dedup_key,
            "line_sample": line_sample,
        }
        return True
    else:
        print(f"[suppress] {dedup_key} 持续中, last_alerted={existing.get('last_alerted')}, 不重发")
        return False


def check_recovery(dedup_key):
    """检查异常是否恢复。返回 True 表示刚恢复（需发通知）。"""
    full_key = f"72h_{dedup_key}"
    existing = alert_state.get(full_key)
    if existing is not None and existing.get("status") == "active":
        recoveries.append({
            "task": dedup_key,
            "keyword": existing.get("keyword", dedup_key),
            "first_seen": existing.get("first_seen", "?"),
        })
        existing["status"] = "recovered"
        existing["last_recovered"] = NOW_STR
        print(f"[recovery] {dedup_key} 异常已消失 (首次发现: {existing.get('first_seen')})")
        return True
    return False


# ==================== 检查1：采集补充 - public_fund 系列 launchctl 加载 + 日频 log 时效 ====================

PF_LABELS = [
    "com.trade.public-fund-daily",
    "com.trade.public-fund-estimation",
    "com.trade.public-fund-full",
    "com.trade.public-fund-quarterly",
    "com.trade.pf-stage0-manager",
    "com.trade.pf-stage0-nav",
    "com.trade.pf-stage0-overview",
    "com.trade.pf-stage0-risk",
    "com.trade.pf-score-daily",
    "com.trade.pf-score-weekly",
]


def launchctl_loaded(label):
    """检查 launchd label 是否已加载（复用 schedule_monitor 逻辑）。"""
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return False
    if r.returncode != 0:
        return False
    return bool(re.search(r"^\s*state = .+$", r.stdout, re.MULTILINE))


for _label in PF_LABELS:
    _short = _label.replace("com.trade.", "")
    _dedup = f"pf_not_loaded|{_short}"
    if launchctl_loaded(_label):
        check_recovery(_dedup)
        continue
    check_and_alert(
        _dedup,
        f"public_fund 任务 {_label} 未加载，需 launchctl bootstrap 恢复",
        keyword="not_loaded",
        line_sample=f"launchctl print gui/{os.getuid()}/{_label} 未加载",
    )

# 日频 public_fund 任务 log 时效检查（仅交易日检查，非交易日跳过避免误报）
# public_fund_daily: 交易日 16:30/17:00，log 文件 public_fund_daily_{YYYYMMDD}_{HHMM}.log
# public_fund_estimation: 交易日 10:00/11:00/13:30/14:30，log 文件 public_fund_estimation_{YYYYMMDD}_{HHMM}.log
# pf-score-daily: 每天 16:00，log 文件 pf-score-daily-launchd.log（检查最近"开始"行）
# pf-stage0-*/pf-score-weekly: weekly/monthly，只检查加载（已上面覆盖），不检查日频 log
if _is_today_trading:
    _pf_daily_schedules = [
        ("public_fund_daily", ["1630", "1700"]),
        ("public_fund_estimation", ["1000", "1100", "1330", "1430"]),
    ]
    _now_hm = NOW.strftime("%H%M")
    for _task_name, _scheds in _pf_daily_schedules:
        for _hm in _scheds:
            # 当前时间超过计划时点+30min 才检查（给任务启动+完成 buffer）
            if _now_hm < _hm:
                continue  # 还没到计划时点
            _log_file = LOG_DIR / f"{_task_name}_{TODAY}_{_hm}.log"
            _dedup = f"pf_missed|{_task_name}|{_hm}|{TODAY}"
            if not _log_file.exists():
                # 当前时间在计划时点+30min 内才算漏跑（超过30min 可能是其他原因，schedule_monitor 模式）
                _scheduled_dt = datetime.strptime(f"{TODAY}{_hm}", "%Y%m%d%H%M")
                if NOW - _scheduled_dt <= timedelta(minutes=30):
                    check_and_alert(
                        _dedup,
                        f"public_fund 任务 {_task_name} 漏跑 计划<{_hm}> toler<30min> "
                        f"now<{NOW_STR}> log<{_log_file.name} 不存在>",
                        keyword=f"missed<{_hm}>",
                        line_sample=f"log not found: {_log_file.name}",
                    )
                else:
                    # 超过30min窗口：标记 seen 防误恢复，但不发新告警（schedule_monitor 模式）
                    seen_keys_this_run.add(f"72h_{_dedup}")
            else:
                check_recovery(_dedup)

    # pf-score-daily log 时效（每天16:00跑，检查 launchd log 最近"开始"行含今日）
    _pf_score_log = LOG_DIR / "pf-score-daily-launchd.log"
    if _pf_score_log.exists() and _now_hm >= "1630":
        try:
            _content = _pf_score_log.read_text(encoding="utf-8", errors="replace")
            _has_today = TODAY in _content or TODAY_ISO in _content
            _dedup = f"pf_missed|pf-score-daily|1600|{TODAY}"
            if _has_today:
                check_recovery(_dedup)
            else:
                _scheduled_dt = datetime.strptime(f"{TODAY}1600", "%Y%m%d%H%M")
                if NOW - _scheduled_dt <= timedelta(minutes=30):
                    check_and_alert(
                        _dedup,
                        f"pf-score-daily 漏跑 计划<16:00> toler<30min> "
                        f"now<{NOW_STR}> log 无今日开始行",
                        keyword="missed<1600>",
                        line_sample="pf-score-daily-launchd.log 无今日记录",
                    )
                else:
                    seen_keys_this_run.add(f"72h_{_dedup}")
        except Exception as e:
            print(f"[warn] pf-score-daily log 检查失败: {e}", file=sys.stderr)


# ==================== 检查2：上传 R2 各前缀代表性文件 ====================

def curl_json(url, timeout=8):
    """curl 获取 JSON，返回 (data_dict, error_str)。"""
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


def curl_text(url, timeout=8):
    """curl 获取纯文本（如 sw.js），返回 (text_str, error_str)。"""
    try:
        result = subprocess.run(
            ["/usr/bin/curl", "-sS", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 4,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if result.returncode != 0:
        return None, f"curl rc={result.returncode}"
    return result.stdout, None


def _safe_load(path):
    """安全加载本地 JSON 文件，返回 (data, error)。"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


R2_BASE = "https://ssd.fx8.store"
R2_CHECKS = [
    # (prefix, url, dedup_key, content_check_description, content_check_fn)
    ("index", f"{R2_BASE}/index/sh-all.json", "r2_prefix_index_fail",
     "etfs 非空", lambda d: bool(d.get("etfs"))),
    ("industry", f"{R2_BASE}/industry/industry-3m.json", "r2_prefix_industry_fail",
     "concepts 非空", lambda d: bool(d.get("concepts"))),
    ("trade_sim", f"{R2_BASE}/trade_sim_data/trade_sim_sh_stats.json", "r2_prefix_trade_sim_fail",
     "keys 非空", lambda d: len(d) > 0 if isinstance(d, dict) else len(d) > 0),
    ("public_fund", f"{R2_BASE}/public_fund/public_fund_summary.json", "r2_prefix_public_fund_fail",
     "200 OK", lambda d: True),
    ("signal_kelly", f"{R2_BASE}/data/signal_kelly_backtest.json", "r2_prefix_signal_kelly_fail",
     "quadrants 非空", lambda d: bool(d.get("quadrants"))),
]

for _prefix, _url, _dedup, _desc, _check_fn in R2_CHECKS:
    _data, _err = curl_json(_url)
    if _err:
        check_and_alert(
            _dedup,
            f"R2 前缀 {_prefix} 上传检查失败 url<{_url}> error<{_err}> "
            f"now<{NOW_STR}> (upload_r2 链路可能断)",
            keyword=f"r2_{_prefix}_fail",
            line_sample=_err,
        )
    elif not _check_fn(_data):
        check_and_alert(
            _dedup,
            f"R2 前缀 {_prefix} 内容异常（{_desc} 失败）url<{_url}> "
            f"now<{NOW_STR}>",
            keyword=f"r2_{_prefix}_empty",
            line_sample=f"content check failed: {_desc}",
        )
    else:
        check_recovery(_dedup)
        print(f"[ok] R2 {_prefix} OK ({_desc})")


# ==================== 检查3：发布 push main + 线上版本最新 ====================

# 3a. git push main 时效（交易日盘后检查，非交易日跳过）
# 注意：REPO(trade-data) 不是 git 仓库，git 命令用 GIT_REPO(trade)
_GIT_REPO = os.environ.get("GIT_REPO", str(REPO.parent / "trade"))
if _is_today_trading:
    try:
        _r = subprocess.run(
            ["git", "-C", _GIT_REPO, "log", "origin/main", "-1", "--format=%ci"],
            capture_output=True, text=True, timeout=10,
        )
        if _r.returncode == 0 and _r.stdout.strip():
            _last_push_str = _r.stdout.strip()
            try:
                _last_push_dt = datetime.strptime(_last_push_str[:19], "%Y-%m-%d %H:%M:%S")
                _push_age = NOW - _last_push_dt
                _push_age_hours = _push_age.total_seconds() / 3600
                # 交易日盘后(15:30后)检查：上次 push >4h = 可能 push 失败
                _now_h = NOW.hour
                if _now_h >= 16 and _push_age_hours > 4:
                    _dedup = "push_main_stale"
                    check_and_alert(
                        _dedup,
                        f"git push main 时效滞后 last_push<{_last_push_str}> "
                        f"age<{_push_age_hours:.1f}h> threshold<4h> now<{NOW_STR}> "
                        f"(deploy push 可能失败)",
                        keyword="push_main_stale",
                        line_sample=f"last_push={_last_push_str} age={_push_age_hours:.1f}h",
                    )
                else:
                    check_recovery("push_main_stale")
            except ValueError:
                print(f"[warn] git log origin/main 时间解析失败: {_last_push_str}", file=sys.stderr)
        else:
            print(f"[warn] git log origin/main 失败: rc={_r.returncode}", file=sys.stderr)
    except Exception as e:
        print(f"[warn] git push 时效检查失败: {e}", file=sys.stderr)

# 3b. 线上 sw.js CACHE_VERSION vs 本地一致
try:
    _local_sw = SS_DATA.parent / "sw.js"  # static-site/sw.js
    _local_version = None
    if _local_sw.exists():
        _m = re.search(r"CACHE_VERSION\s*=\s*'([^']+)'", _local_sw.read_text(encoding="utf-8"))
        if _m:
            _local_version = _m.group(1)

    _online_sw_data, _online_sw_err = curl_text("https://ss.fx8.store/sw.js")
    _online_version = None
    if _online_sw_err is None and _online_sw_data:
        _m2 = re.search(r"CACHE_VERSION\s*=\s*'([^']+)'", _online_sw_data)
        if _m2:
            _online_version = _m2.group(1)

    _dedup = "sw_version_mismatch"
    if _local_version and _online_version:
        if _local_version != _online_version:
            check_and_alert(
                _dedup,
                f"线上 sw.js 版本滞后 local<{_local_version}> online<{_online_version}> "
                f"now<{NOW_STR}> (push 失败或 CF cache 未 purge)",
                keyword="sw_version_mismatch",
                line_sample=f"local={_local_version} online={_online_version}",
            )
        else:
            check_recovery(_dedup)
            print(f"[ok] sw.js 版本一致: {_local_version}")
    else:
        print(f"[warn] sw.js 版本检查不完整: local={_local_version} online_err={_online_sw_err}", file=sys.stderr)
except Exception as e:
    print(f"[warn] sw.js 版本检查失败: {e}", file=sys.stderr)

# 3c. 线上 overview.json date vs 本地一致
try:
    _local_ov, _ = _safe_load(SS_DATA / "overview.json")
    _online_ov, _ov_err = curl_json("https://ss.fx8.store/data/overview.json")
    _dedup = "overview_date_mismatch"
    if _local_ov and _online_ov and not _ov_err:
        _local_date = _local_ov.get("date")
        _online_date = _online_ov.get("date")
        if _local_date and _online_date and _local_date != _online_date:
            check_and_alert(
                _dedup,
                f"线上 overview date 滞后 local<{_local_date}> online<{_online_date}> "
                f"now<{NOW_STR}> (线上数据滞后)",
                keyword="overview_date_mismatch",
                line_sample=f"local_date={_local_date} online_date={_online_date}",
            )
        else:
            check_recovery(_dedup)
            print(f"[ok] overview date 一致: local={_local_date} online={_online_date}")
except Exception as e:
    print(f"[warn] overview date 一致性检查失败: {e}", file=sys.stderr)


# ==================== 检查4：功能稳定性 P0 smoke 8 项 ====================

# S1: overview.json date + 9 scores 非null
_ov_online, _ov_err_s1 = curl_json("https://ss.fx8.store/data/overview.json")
_dedup_s1 = "p0_smoke_s1_overview"
if _ov_err_s1 or not _ov_online:
    check_and_alert(_dedup_s1, f"P0-S1 overview.json 不可达/解析失败 err<{_ov_err_s1}>",
                    keyword="p0_s1_fail", line_sample=str(_ov_err_s1))
else:
    _s1_fails = []
    if _ov_online.get("date") not in (TODAY, LAST_TRADING_DAY):
        _s1_fails.append(f"date={_ov_online.get('date')} 非{TODAY}/{LAST_TRADING_DAY}")
    _scores = _ov_online.get("today", {}).get("scores", {})
    _need = ["a_sentiment","cross_market","fear_greed","sentiment_csi1000","sentiment_csi500",
             "sentiment_cyb","sentiment_hs300","sentiment_kc50","sentiment_sz50"]
    _miss = [k for k in _need if not _scores.get(k)]
    if _miss:
        _s1_fails.append(f"scores 缺 {_miss}")
    if _s1_fails:
        check_and_alert(_dedup_s1, f"P0-S1 overview 异常: {'; '.join(_s1_fails)}",
                        keyword="p0_s1_fail", line_sample="; ".join(_s1_fails))
    else:
        check_recovery(_dedup_s1)
        print("[ok] P0-S1 overview OK")

# S2: intraday_snapshot collected_at 含今日 + indices len>=17
_id_online, _id_err_s2 = curl_json("https://ss.fx8.store/data/intraday_snapshot.json")
_dedup_s2 = "p0_smoke_s2_intraday"
if _id_err_s2 or not _id_online:
    check_and_alert(_dedup_s2, f"P0-S2 intraday_snapshot 不可达/解析失败 err<{_id_err_s2}>",
                    keyword="p0_s2_fail", line_sample=str(_id_err_s2))
else:
    _s2_fails = []
    _ca = str(_id_online.get("collected_at", ""))
    # 盘前/非交易日允许 collected_at 含最近交易日
    _ca_compact = _ca.replace("-", "")
    if TODAY not in _ca_compact and LAST_TRADING_DAY not in _ca_compact:
        _s2_fails.append(f"collected_at={_ca} 不含今日/最近交易日")
    _idx = _id_online.get("indices", [])
    if not isinstance(_idx, list) or len(_idx) < 17:
        _s2_fails.append(f"indices len={len(_idx) if isinstance(_idx, list) else 'N/A'} <17")
    if _s2_fails:
        check_and_alert(_dedup_s2, f"P0-S2 intraday 异常: {'; '.join(_s2_fails)}",
                        keyword="p0_s2_fail", line_sample="; ".join(_s2_fails))
    else:
        check_recovery(_dedup_s2)
        print("[ok] P0-S2 intraday OK")

# S3: index sh-all.json etfs 非空 (R2)
_idx_online, _idx_err_s3 = curl_json(f"{R2_BASE}/index/sh-all.json")
_dedup_s3 = "p0_smoke_s3_index_etfs"
if _idx_err_s3 or not _idx_online:
    check_and_alert(_dedup_s3, f"P0-S3 index sh-all.json 不可达 err<{_idx_err_s3}>",
                    keyword="p0_s3_fail", line_sample=str(_idx_err_s3))
else:
    _etfs = _idx_online.get("etfs", [])
    if not _etfs:
        check_and_alert(_dedup_s3, "P0-S3 index sh-all.json etfs 为空（全部无ETF根因）",
                        keyword="p0_s3_fail", line_sample="etfs empty")
    else:
        check_recovery(_dedup_s3)
        print(f"[ok] P0-S3 index etfs OK (len={len(_etfs) if isinstance(_etfs, list) else 'N/A'})")

# S4: board_etf_map.json 空数组占比<30% (本地文件，线上不暴露)
_bem, _bem_err = _safe_load(DATA_DIR / "board_etf_map.json")
_dedup_s4 = "p0_smoke_s4_board_etf_map"
if _bem_err or not _bem:
    check_and_alert(_dedup_s4, f"P0-S4 board_etf_map.json 读取失败 err<{_bem_err}>",
                    keyword="p0_s4_fail", line_sample=str(_bem_err))
else:
    _keys = list(_bem.keys()) if isinstance(_bem, dict) else []
    _empty = [k for k in _keys if not _bem.get(k)]
    _pct = len(_empty) / len(_keys) * 100 if _keys else 100
    if _pct >= 30:
        check_and_alert(_dedup_s4, f"P0-S4 board_etf_map 空数组 {_pct:.1f}% >=30% ({len(_empty)}/{len(_keys)}) 全部无ETF根因",
                        keyword="p0_s4_fail", line_sample=f"{len(_empty)}/{len(_keys)}={_pct:.1f}%")
    else:
        check_recovery(_dedup_s4)
        print(f"[ok] P0-S4 board_etf_map OK ({_pct:.1f}% empty)")

# S5: alert.json date + high.score 非 null
_al_online, _al_err_s5 = curl_json("https://ss.fx8.store/data/alert.json")
_dedup_s5 = "p0_smoke_s5_alert"
if _al_err_s5 or not _al_online:
    check_and_alert(_dedup_s5, f"P0-S5 alert.json 不可达 err<{_al_err_s5}>",
                    keyword="p0_s5_fail", line_sample=str(_al_err_s5))
else:
    _s5_fails = []
    # 盘后 date 应今日，盘中可能昨日(正常)
    # alert.json 仅17:50 update_all 更新，交易日17:50前是上一交易日数据（正常）
    _al_date = str(_al_online.get("date", ""))
    _yesterday = (NOW.date() - timedelta(days=1)).strftime("%Y%m%d")
    if _al_date not in (TODAY, LAST_TRADING_DAY, _yesterday, ALERT_EXPECTED_DATE):
        _s5_fails.append(f"date={_al_date} 非今日/昨日/最近交易日/预期alert日期")
    if _al_online.get("high", {}).get("score") is None:
        _s5_fails.append("high.score 为 null")
    if _s5_fails:
        check_and_alert(_dedup_s5, f"P0-S5 alert 异常: {'; '.join(_s5_fails)}",
                        keyword="p0_s5_fail", line_sample="; ".join(_s5_fails))
    else:
        check_recovery(_dedup_s5)
        print("[ok] P0-S5 alert OK")

# S6: boot.json overview.date + missing==[]
_boot_online, _boot_err_s6 = curl_json("https://ss.fx8.store/data/boot.json")
_dedup_s6 = "p0_smoke_s6_boot"
if _boot_err_s6 or not _boot_online:
    check_and_alert(_dedup_s6, f"P0-S6 boot.json 不可达 err<{_boot_err_s6}>",
                    keyword="p0_s6_fail", line_sample=str(_boot_err_s6))
else:
    _s6_fails = []
    _boot_ov = _boot_online.get("overview", {})
    if isinstance(_boot_ov, dict) and _boot_ov.get("date") not in (TODAY, LAST_TRADING_DAY):
        _s6_fails.append(f"boot.overview.date={_boot_ov.get('date')} 非今日/最近交易日")
    _missing = _boot_online.get("_meta", {}).get("missing", [])
    if _missing:
        _s6_fails.append(f"boot._meta.missing={_missing}")
    if _s6_fails:
        check_and_alert(_dedup_s6, f"P0-S6 boot 异常: {'; '.join(_s6_fails)}",
                        keyword="p0_s6_fail", line_sample="; ".join(_s6_fails))
    else:
        check_recovery(_dedup_s6)
        print("[ok] P0-S6 boot OK")

# S7: trade_sim_indices.json len>=100
_tsi_online, _tsi_err_s7 = curl_json("https://ss.fx8.store/data/trade_sim_indices.json")
_dedup_s7 = "p0_smoke_s7_trade_sim"
if _tsi_err_s7 or not _tsi_online:
    check_and_alert(_dedup_s7, f"P0-S7 trade_sim_indices.json 不可达 err<{_tsi_err_s7}>",
                    keyword="p0_s7_fail", line_sample=str(_tsi_err_s7))
else:
    _tsi_len = len(_tsi_online) if isinstance(_tsi_online, list) else 0
    if _tsi_len < 100:
        check_and_alert(_dedup_s7, f"P0-S7 trade_sim_indices len={_tsi_len} <100 策略实验室入口空",
                        keyword="p0_s7_fail", line_sample=f"len={_tsi_len}")
    else:
        check_recovery(_dedup_s7)
        print(f"[ok] P0-S7 trade_sim_indices OK (len={_tsi_len})")

# S8: notifications.json date==今日
_ntf_online, _ntf_err_s8 = curl_json("https://ss.fx8.store/data/notifications.json")
_dedup_s8 = "p0_smoke_s8_notifications"
if _ntf_err_s8 or not _ntf_online:
    check_and_alert(_dedup_s8, f"P0-S8 notifications.json 不可达 err<{_ntf_err_s8}>",
                    keyword="p0_s8_fail", line_sample=str(_ntf_err_s8))
else:
    if _ntf_online.get("date") not in (TODAY, LAST_TRADING_DAY):
        check_and_alert(_dedup_s8, f"P0-S8 notifications.date={_ntf_online.get('date')} != 今日/最近交易日({TODAY}/{LAST_TRADING_DAY})",
                        keyword="p0_s8_fail", line_sample=f"date={_ntf_online.get('date')}")
    else:
        check_recovery(_dedup_s8)
        print("[ok] P0-S8 notifications OK")


# ==================== 检查5：功能及时性 - signal_kelly 口径 + 日频数据时效 ====================

# 5a. signal_kelly_backtest 口径：y1/A annualized_return < 100（旧 258% 公式 = SEVERE）
_sk_online = _idx_online  # reuse? no, fetch signal_kelly
_sk_data, _sk_err = curl_json(f"{R2_BASE}/data/signal_kelly_backtest.json")
_dedup_sk = "signal_kelly_stale_formula"
if _sk_err or not _sk_data:
    check_and_alert(_dedup_sk, f"signal_kelly_backtest.json 不可达 err<{_sk_err}>",
                    keyword="sk_unreachable", line_sample=str(_sk_err))
else:
    _quadrants = _sk_data.get("quadrants", {})
    _rh = _quadrants.get("rating_high", {}) if isinstance(_quadrants, dict) else {}
    _periods = _rh.get("periods", {}) if isinstance(_rh, dict) else {}
    _y1 = _periods.get("y1", {}) if isinstance(_periods, dict) else {}
    _y1_A = _y1.get("A", {}) if isinstance(_y1, dict) else {}
    _ar = _y1_A.get("annualized_return")
    if _ar is None:
        check_and_alert(_dedup_sk, "signal_kelly y1/A annualized_return 字段缺失（结构异常）",
                        keyword="sk_field_missing", line_sample="annualized_return not found")
    elif _ar > 100:
        check_and_alert(_dedup_sk,
                        f"signal_kelly y1/A annualized_return={_ar} >100 疑似旧258%口径 "
                        f"(应为 return_pct_max_holding 峰值资金收益率，y1≈3%合理)",
                        keyword="sk_stale_formula", line_sample=f"annualized_return={_ar}")
    else:
        check_recovery(_dedup_sk)
        print(f"[ok] signal_kelly 口径 OK (y1/A annualized_return={_ar})")

# 5b. 日频数据时效
# overview.json date 滞后（交易日>1天=SEVERE）
if _ov_online and not _ov_err_s1:
    _ov_date = str(_ov_online.get("date", ""))
    _dedup_ov = "stale_overview_date"
    if _ov_date and _ov_date not in (TODAY, LAST_TRADING_DAY):
        check_and_alert(_dedup_ov, f"overview.json date={_ov_date} 滞后(非{TODAY}/{LAST_TRADING_DAY})",
                        keyword="stale_overview", line_sample=f"date={_ov_date}")
    else:
        check_recovery(_dedup_ov)

# alert.json date 滞后（>3天=SEVERE，盘中可能昨日正常；盘前/非交易日 LAST_TRADING_DAY 不算滞后）
# alert.json 仅17:50 update_all 更新，交易日17:50前是上一交易日数据（正常，周一盘前周五=3天不算滞后）
if _al_online and not _al_err_s5:
    _al_date_str = str(_al_online.get("date", ""))
    _dedup_al = "stale_alert_date"
    if _al_date_str in (LAST_TRADING_DAY, ALERT_EXPECTED_DATE):
        check_recovery(_dedup_al)
    else:
        try:
            _al_dt = datetime.strptime(_al_date_str, "%Y%m%d")
            _al_age = (NOW.date() - _al_dt.date()).days
            # 周末跨度大（周五->周一=3天），>3天才算真滞后
            if _al_age > 3:
                check_and_alert(_dedup_al, f"alert.json date={_al_date_str} 滞后{_al_age}天(>3天)",
                                keyword="stale_alert", line_sample=f"date={_al_date_str} age={_al_age}d")
            else:
                check_recovery(_dedup_al)
        except ValueError:
            print(f"[warn] alert.json date 格式异常: {_al_date_str}", file=sys.stderr)

# ad_line.json 最后日期滞后（>3天=SEVERE）
_ad_online, _ad_err = curl_json("https://ss.fx8.store/data/ad_line.json")
_dedup_ad = "stale_ad_line"
if _ad_err or not _ad_online:
    check_and_alert(_dedup_ad, f"ad_line.json 不可达 err<{_ad_err}>",
                    keyword="ad_unreachable", line_sample=str(_ad_err))
else:
    _ad_data = _ad_online.get("data", [])
    if isinstance(_ad_data, list) and _ad_data:
        _ad_last_date = str(_ad_data[-1].get("date", "")) if isinstance(_ad_data[-1], dict) else ""
        try:
            _ad_dt = datetime.strptime(_ad_last_date, "%Y%m%d")
            _ad_age = (NOW.date() - _ad_dt.date()).days
            if _ad_age > 3:
                check_and_alert(_dedup_ad, f"ad_line.json 最后日期={_ad_last_date} 滞后{_ad_age}天(>3天)",
                                keyword="stale_ad_line", line_sample=f"last_date={_ad_last_date} age={_ad_age}d")
            else:
                check_recovery(_dedup_ad)
        except ValueError:
            print(f"[warn] ad_line date 格式异常: {_ad_last_date}", file=sys.stderr)
    else:
        check_and_alert(_dedup_ad, "ad_line.json data 为空",
                        keyword="ad_empty", line_sample="data list empty")


# ==================== 恢复检测：state 里 active 但本次未 seen = 异常已恢复 ====================

for _key, _info in list(alert_state.items()):
    if not _key.startswith("72h_"):
        continue  # 只处理 72h 前缀的 key，不碰 schedule_monitor 的
    if _info.get("status") != "active":
        continue
    if _key not in seen_keys_this_run:
        # 未 seen = 异常已消失，发恢复邮件
        _short_key = _key.replace("72h_", "")
        _kw = _info.get("keyword", _short_key)
        recoveries.append({
            "task": _short_key,
            "keyword": _kw,
            "first_seen": _info.get("first_seen", "?"),
        })
        _info["status"] = "recovered"
        _info["last_recovered"] = NOW_STR
        print(f"[recovery] {_short_key} 异常已消失 (首次发现: {_info.get('first_seen')})")

save_alert_state(alert_state)


# ==================== 输出 + 告警 ====================

if alerts:
    print(f"[{NOW_STR}] 检测到 {len(alerts)} 个告警:")
    for a in alerts:
        print(a)
    _body = "<br>".join(
        a.replace("<", "&lt;").replace(">", "&gt;") for a in alerts
    )
    _time_str = NOW.strftime("%m-%d %H:%M")
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            f"[72h监控] {len(alerts)}项异常 {_time_str}",
            _body,
            "--severe",
            "--from-prefix", "[72h监控]",
            "--alert-issue", "72h持续监控告警",
            "--alert-log", str(MONITOR_LOG),
        ],
        check=False,
    )
else:
    print(f"[{NOW_STR}] PASS 所有检查正常（5类覆盖: 采集/R2/发布/稳定性/及时性）")

# 恢复邮件
if recoveries:
    print(f"[{NOW_STR}] 检测到 {len(recoveries)} 个异常恢复:")
    for r in recoveries:
        print(f"  [恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失")
    if len(recoveries) == 1:
        r0 = recoveries[0]
        _subject = f"[72h恢复] {r0['task']} {r0['keyword']} {NOW.strftime('%m-%d %H:%M')}"
    else:
        _subject = f"[72h恢复] {len(recoveries)}项异常恢复 {NOW.strftime('%m-%d %H:%M')}"
    _rec_lines = [
        f"[恢复] {r['task']} 异常关键词<{r['keyword']}> 已消失 "
        f"(首次发现: {r['first_seen']}, 恢复时间: {NOW_STR})"
        for r in recoveries
    ]
    _body = "<br>".join(
        l.replace("<", "&lt;").replace(">", "&gt;") for l in _rec_lines
    )
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts" / "notify.py"),
            _subject,
            _body,
            "--from-prefix", "[72h恢复]",
            "--alert-issue", "72h持续监控恢复",
            "--alert-log", str(MONITOR_LOG),
        ],
        check=False,
    )

# Heartbeat
try:
    Path("/tmp/monitor_72h_heartbeat.txt").write_text(
        f"{NOW_STR}\nalerts={len(alerts)}\nrecoveries={len(recoveries)}\n",
        encoding="utf-8",
    )
except Exception as e:
    print(f"[warn] heartbeat 写入失败: {e}", file=sys.stderr)
PYEOF

# 总是 exit 0：告警已发邮件，避免 launchd 因非0退出重试
exit 0
