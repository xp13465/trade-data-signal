#!/bin/bash
# self_heal.sh - 计划任务自愈（P0 稳定性 2026-07-20）
#
# 设计原则（白名单 + 限流 + audit）：
#   1) 白名单动作：只 force 重跑失败任务，禁止 force push/删文件/改代码（绝不破坏代码或数据）
#   2) 每日 3 次上限：self_heal_state.json 记每日计数，超上限发 SEVERE 邮件停止（防失控连环重跑）
#   3) audit log：每动作（HEAL/SKIP/LIMIT/FAIL）写 data/logs/self_heal_audit.log
#   4) 任务在跑跳过：launchctl state 含 running 时跳过（不误杀正在跑的任务）
#   5) 旧问题不 heal：last_run 距今 >24h 的失败任务跳过（旧问题等下次任务跑更新 stats）
#
# 决策逻辑（P0 只实现模式1：force 重跑失败任务）：
#   读 schedule_stats.json -> 对每个任务 last_exit!=0 且 last_run 24h 内
#   -> 检查 launchctl state 不是 running -> 后台触发 HEAL_ACTIONS force 重跑
#
# 触发：launchd com.trade.self-heal 每15分钟（Minute=7/22/37/52，错开 schedule_monitor
#   的 0/15/30/45，让 monitor 先告警 self_heal 后自愈，避免撞 deploy.lock）。
# 告警链路：复用 scripts/notify.py（邮件 + alerts/latest.md），达到上限时发 SEVERE。
set -uo pipefail
REPO="${REPO:-/Users/linhuichen/code/trade}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
cd "$REPO"
export REPO GIT_REPO

# 用 python heredoc 做决策 + 触发（bash 处理 JSON/launchctl 太繁琐易错）
"$REPO/.venv/bin/python" <<'PYEOF' 2>&1
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(os.environ["REPO"])
GIT_REPO = Path(os.environ["GIT_REPO"])
LOG_DIR = REPO / "data" / "logs"
STATS_FILE = REPO / "static-site" / "data" / "schedule_stats.json"
STATE_FILE = LOG_DIR / "self_heal_state.json"
AUDIT_LOG = LOG_DIR / "self_heal_audit.log"
MONITOR_LOG = LOG_DIR / "self_heal_launchd.log"

NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")
DAILY_LIMIT = 3
STALE_THRESHOLD_SEC = 24 * 3600  # last_run 超 24h 不 heal（旧问题等下次任务跑更新）

# task -> force 重跑命令（force 参数仅加给支持 force 的脚本）
# grep 确认 force 支持：update_all/intraday_snapshot/futures_backfill/lhb_backfill/
# rzhb_backfill/etf_national_team_backfill 支持；backfill_metrics/update_lab 不支持。
HEAL_ACTIONS = {
    "update_all":          ["bash", "scripts/update_all.sh", "force"],
    "backfill_evening":    ["bash", "scripts/backfill_metrics.sh"],
    "intraday_snapshot":   ["bash", "scripts/intraday_snapshot.sh", "force"],
    "futures_backfill":    ["bash", "scripts/futures_backfill.sh", "force"],
    "lhb_backfill":        ["bash", "scripts/lhb_backfill.sh", "force"],
    "rzhb_backfill":       ["bash", "scripts/rzhb_backfill.sh", "force"],
    "etf_national_team":   ["bash", "scripts/etf_national_team_backfill.sh", "force"],
    "lab_auto":            ["bash", "scripts/update_lab.sh"],
}
# task -> launchctl label（与 gen_schedule_stats.py LABEL_MAP 同步）
LABELS = {
    "update_all": "com.trade.update-all",
    "backfill_evening": "com.trade.backfill-evening",
    "intraday_snapshot": "com.trade.intraday-snapshot",
    "futures_backfill": "com.trade.futures-backfill",
    "lhb_backfill": "com.trade.lhb-backfill",
    "rzhb_backfill": "com.trade.rzhb-backfill",
    "etf_national_team": "com.trade.etf-national-team",
    "lab_auto": "com.trade.lab-auto",
}


def launchctl_state(label):
    """返回 launchctl state（如 'running'/'not running'），失败返回 None。"""
    if not label:
        return None
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"^\s*state = (.+)$", r.stdout, re.MULTILINE)
    return m.group(1).strip() if m else None


def load_state():
    """读 self_heal_state.json：{"date":"2026-07-20","count":2,"healed":[...]}。
    跨天自动重置计数。
    """
    if not STATE_FILE.exists():
        return {"date": TODAY, "count": 0, "healed": []}
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if s.get("date") != TODAY:
            return {"date": TODAY, "count": 0, "healed": []}
        return s
    except Exception:
        return {"date": TODAY, "count": 0, "healed": []}


def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def audit(msg):
    """append 写 audit log。"""
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = NOW.strftime("%Y-%m-%d %H:%M:%S")
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def notify_severe(subject, body):
    """复用 notify.py 发 SEVERE 邮件 + 写 alerts/latest.md。"""
    try:
        subprocess.run(
            [sys.executable, str(REPO / "scripts" / "notify.py"),
             subject, body, "--severe",
             "--alert-issue", "自愈脚本达到每日上限停止",
             "--alert-log", str(AUDIT_LOG)],
            check=False, capture_output=True, text=True, timeout=60,
        )
    except Exception as e:
        print(f"[self_heal] notify 失败(不阻塞): {e}", file=sys.stderr)


# 1) 读 schedule_stats.json
if not STATS_FILE.exists():
    print(f"[self_heal] {STATS_FILE} 不存在，无可 heal 任务，退出", file=sys.stderr)
    sys.exit(0)
try:
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
except Exception as e:
    print(f"[self_heal] stats 解析失败: {e}", file=sys.stderr)
    sys.exit(0)

# 2) 读计数 state，达上限停止 + 发 SEVERE
state = load_state()
if state["count"] >= DAILY_LIMIT:
    msg = (f"已达每日上限 {DAILY_LIMIT} 次停止自愈。今日 healed: "
           f"{json.dumps(state['healed'], ensure_ascii=False)}")
    print(f"[self_heal] {msg}", file=sys.stderr)
    audit(f"LIMIT 达上限 count={state['count']}: {msg}")
    notify_severe("自愈脚本达到每日上限停止", msg)
    sys.exit(0)

# 3) 筛选需 heal 的任务：last_exit!=0 且 last_run 24h 内 且 launchctl state 不是 running
to_heal = []
for s in stats:
    task = s.get("task")
    exit_code = s.get("last_exit")
    last_run_str = s.get("last_run")
    log_anomaly = s.get("log_anomaly", False)
    # null/0 且无 log_anomaly 不 heal（null=进行中/无数据，0=成功）
    # 第4盲区修复: log_anomaly=true 时即使 exit=0 也 heal（脚本吞异常场景）
    if (exit_code is None or exit_code == 0) and not log_anomaly:
        continue
    # last_run 时效检查
    if not last_run_str:
        continue
    try:
        last_run_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M")
    except ValueError:
        print(f"[self_heal] {task} last_run 格式异常: {last_run_str}", file=sys.stderr)
        continue
    age_sec = (NOW - last_run_dt).total_seconds()
    if age_sec > STALE_THRESHOLD_SEC:
        print(f"[self_heal] {task} last_run={last_run_str} 距今>"
              f"{int(STALE_THRESHOLD_SEC//3600)}h，旧问题等下次任务跑，不 heal")
        audit(f"SKIP_STALE {task} last_run={last_run_str} age={int(age_sec//3600)}h last_exit={exit_code}")
        continue
    # launchctl state 检查（在跑跳过，不误杀）
    label = LABELS.get(task)
    st = launchctl_state(label)
    if st and "running" in st:
        print(f"[self_heal] {task} launchctl state={st}（在跑），跳过避免误杀")
        audit(f"SKIP_RUNNING {task} state={st} last_exit={exit_code}")
        continue
    to_heal.append((task, exit_code, last_run_str, st, log_anomaly))

if not to_heal:
    print(f"[{NOW.strftime('%Y-%m-%d %H:%M:%S')}] OK 无需 heal 的任务"
          f"（无失败/失败任务在跑/旧问题）")
    sys.exit(0)

# 4) 执行 heal（每日上限内，逐个后台触发重跑，不阻塞 self_heal 退出）
healed_now = []
for task, exit_code, last_run_str, st, log_anomaly in to_heal:
    if state["count"] >= DAILY_LIMIT:
        msg = (f"执行中达到每日上限 {DAILY_LIMIT} 次，剩余任务跳过。"
               f"已 heal: {json.dumps(state['healed'], ensure_ascii=False)}")
        print(f"[self_heal] {msg}", file=sys.stderr)
        audit(f"LIMIT {msg}")
        notify_severe("自愈脚本达到每日上限停止", msg)
        break
    cmd = HEAL_ACTIONS.get(task)
    if not cmd:
        print(f"[self_heal] {task} 无 HEAL_ACTIONS 配置，跳过", file=sys.stderr)
        continue
    # 盘中保护（§8）：update_all 的 force = 全量 export+deploy，交易日盘中
    # (09:30-15:30) 跳过避免撞 intraday-snapshot 定时任务推 main 致互相覆盖事故。
    # 其他任务（backfill/futures/lhb/rzhb/etf_nt）不涉及全量 export，盘中可跑不加保护。
    # 节假日未严格判断（盘中跳过即使节假日也无害，只是少跑一次自愈，收盘后/次日正常触发）。
    if task == "update_all":
        hhmm = int(NOW.strftime("%H%M"))
        is_weekday = NOW.isoweekday() <= 5  # 1-5 周一到周五（等价 date +%u 1-5）
        if is_weekday and 930 <= hhmm <= 1530:
            audit(f"SKIP_INTRADAY {task} reason=intraday_skip "
                  f"now={NOW.strftime('%H:%M')} §8 盘中不跑全量，收盘后自愈 "
                  f"last_exit={exit_code} last_run={last_run_str} log_anomaly={log_anomaly}")
            state.setdefault("skipped", []).append({
                "task": task, "time": NOW.strftime("%H:%M:%S"),
                "reason": "intraday_skip",
                "last_exit": exit_code, "last_run": last_run_str,
                "log_anomaly": log_anomaly,
            })
            save_state(state)
            print(f"[self_heal] {task} 盘中跳过 update_all force（§8 盘中不跑全量），"
                  f"收盘后自愈。now={NOW.strftime('%H:%M')}", file=sys.stderr)
            continue
    # 后台触发重跑：nohup + & 让子进程 detach（self_heal 退出不杀重跑任务）
    cmd_str = " ".join(cmd)
    log_file = LOG_DIR / f"{task}_heal.log"
    full_cmd = f"nohup {cmd_str} >> {log_file} 2>&1 &"
    try:
        subprocess.run(full_cmd, shell=True, cwd=str(REPO), timeout=5)
    except Exception as e:
        print(f"[self_heal] {task} 触发失败: {e}", file=sys.stderr)
        audit(f"FAIL {task} 触发失败: {e}")
        continue
    state["count"] += 1
    state["healed"].append({
        "task": task, "time": NOW.strftime("%H:%M:%S"),
        "exit": exit_code, "last_run": last_run_str,
        "log_anomaly": log_anomaly,
    })
    healed_now.append(task)
    reason = "log_anomaly" if (log_anomaly and (exit_code is None or exit_code == 0)) else f"exit={exit_code}"
    audit(f"HEAL {task} reason={reason} last_exit={exit_code} last_run={last_run_str} "
          f"log_anomaly={log_anomaly} state={st} -> 触发 {cmd_str} (log={log_file.name})")

save_state(state)
print(f"[{NOW.strftime('%Y-%m-%d %H:%M:%S')}] HEAL 触发 {len(healed_now)} 个任务: {healed_now}")
print(f"[self_heal] 今日已 heal {state['count']}/{DAILY_LIMIT} 次")
PYEOF

# 总是 exit 0：自愈动作已后台触发，避免 launchd 因非0退出重试
exit 0
