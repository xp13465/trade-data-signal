#!/bin/bash
# self_heal.sh - 计划任务自愈(P0 稳定性 2026-07-20;2026-10-22 每任务配额+结果校验)
#
# 设计原则(白名单 + 限流 + audit)：
#   1) 白名单动作：只 force 重跑失败任务，禁止 force push/删文件/改代码（绝不破坏代码或数据）
#   2) 配额(2026-10-22 起)：**每任务**每日 3 次(独立计数) + 全站总上限 12 次/日。
#      旧版是全局共享 3 次，单个反复失败的任务会吃光全站额度(评估报告 §4)。
#      计数/校验逻辑在 scripts/self_heal_core.py(纯函数，pytest 可打桩)，本脚本只做 IO。
#   3) audit log：每动作(HEAL/SKIP/LIMIT/FAIL/VERIFY/ESCALATE)写 data/logs/self_heal_audit.log；
#      heal 之后下一轮校验结果(PASS/FAIL + 校验依据)也写这里(旧版只记触发不记结果)。
#   4) 任务在跑跳过：launchctl state 含 running 时跳过（不误杀正在跑的任务）
#   5) 旧问题不 heal：last_run 距今 >24h 的失败任务跳过（旧问题等下次任务跑更新 stats）
#   6) 连续 heal 失败 ≥2 次 → 走 notify.py 升级告警(--tier warning，按任务 6h 去重；
#      warning 级只发邮件/飞书，不写 data/alerts/latest.md —— 那是 critical 专属)
#
# 决策逻辑：
#   读 schedule_stats.json -> 对每个任务 last_exit!=0(或 log_anomaly) 且 last_run 24h 内
#   -> 检查 launchctl state 不是 running + 任务脚本进程不在跑(pgrep) -> 每任务配额内后台
#      触发 HEAL_ACTIONS force 重跑 -> 记 pending
#   -> 下一轮按「<task>_heal.log 与 launchd 日志里 heal 之后**开始**的运行记录 + 产物新鲜度」
#      判 PASS/FAIL(重跑进行中不判 FAIL)
#
# 触发：systemd trade-self-heal.timer 每15分钟(云上 Minute=7/22/37/52，错开 schedule_monitor
#   的 0/15/30/45，让 monitor 先告警 self_heal 后自愈，避免撞 deploy.lock)。
# 告警链路：复用 scripts/notify.py(升级告警 tier=warning → 邮件 + 飞书；warning 级不写
#   data/alerts/latest.md，那是 critical 专属；达每日上限的 info 只落 dashboard)。
# 自测桩：SELF_HEAL_NOTIFY_DRYRUN=1 时所有 notify.py 调用追加 --dry-run(零外发)，仅供测试。
set -uo pipefail
# ── REPO/GIT_REPO 单点解析(#195 批2):共享 lib(env 优先零改写 > $0 双布局推导 > fail-loud)──
# 去掉写死的 mac 默认值(原靠 unit 的 Environment= 兜住,env 一丢即静默坏);原 export
# 语义逐字节保留(python 子进程可见性与迁移前一致)。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
cd "$REPO"
export REPO GIT_REPO

# 单项指标失败自动重采(2026-07-31 自动修复机制,在任务级 force-heal 之前轻量重采):
# 读 collect_log 当日 error 项,对每个 error 指标调 collect_snapshot/collect_direct 重采。
# 复用 fetchers.collect_snapshot(含 zt_pool 交叉验证:跌停池空+涨停池有数据=真0跌停,写0+ok)。
# 不受下方每任务配额限制(轻量重采,不像 force 重跑整个 update_all);失败保留 error下次再试。
# 场景:17:50 update_all 跌停池空 error -> 18:07 本脚本重采交叉验证涨停池有数据 -> 写0+ok,collect_health 变 ok。
echo "=== retry_failed_metrics 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$REPO/data/logs/self_heal_audit.log"
# 2026-10-01 #132 并发双通知修复: 经 with_lock.py --nb 进程互斥(复用仓内既有机制,
# 与 intraday_snapshot/update_all/turnover_backfill 同"重复跑跳过"惯例), 防止两个并发
# self_heal 同时读到 n=2 双双跨阈值发两次通知。互斥失败语义 = 跳过本轮: retry 是每 15min
# 一轮的轻量重采(秒级), 锁被占=另一实例正在跑, 本轮跳过让下一轮(15min 后)再试即可,
# 失败指标本就处于 error 态, 晚 15min 无害; 排队阻塞反而拖住 self_heal 的任务级 heal。
# 锁随进程退出自动释放(fcntl.flock), 无残留锁风险。锁跳过时 with_lock stderr 会打进 audit 日志。
"$REPO/.venv/bin/python" "$REPO/scripts/with_lock.py" --nb /tmp/trade_retry_failed_metrics.lock \
    "$REPO/.venv/bin/python" "$REPO/scripts/retry_failed_metrics.py" 2>&1 | tee -a "$REPO/data/logs/self_heal_audit.log" || echo "⚠ retry_failed_metrics.py 失败(不阻塞,继续任务级 heal)" | tee -a "$REPO/data/logs/self_heal_audit.log"
echo "=== retry_failed_metrics 结束 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$REPO/data/logs/self_heal_audit.log"

# 用 python heredoc 做 IO 适配(决策逻辑在 scripts/self_heal_core.py)
"$REPO/.venv/bin/python" <<'PYEOF' 2>&1
import json
import os
import re
import shutil
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

sys.path.insert(0, str(REPO / "scripts"))
import self_heal_core as core  # noqa: E402

NOW = datetime.now()

# task -> force 重跑命令（force 参数仅加给支持 force 的脚本）
# grep 确认 force 支持：update_all/intraday_snapshot/futures_backfill/lhb_backfill/
# rzhb_backfill/etf_national_team_backfill/update_lab 支持（update_lab.sh:76-83 的 force
# 绕过「非交易日跳过」闸门，这正是 M3 要的：否则周末 heal 跑完也不刷新产物 = 假 FAIL）；
# backfill_metrics.sh 无 force 参数（不需要：它没有交易日闸门）。
# ⚠️ 收录边界（#196 §22 登记点判定，2026-10-05）：**只收「自动重跑能真正解除故障」的任务**。
#    只读巡检/监控类（cloud_unit_patrol / r2_consistency / check_data_gap / overfit_monitor /
#    schedule_monitor 自身）**故意不登记**：它们失败时重跑无意义（漂移/一致性问题重跑一遍还是
#    那个结果），且登记进来会把「人工确认」降级成「自动重跑」，反而掩盖真问题。
#    它们"死了没人知"的问题由 #196 的 check_failed_units.py（failed-unit + timer 存活 +
#    脚本存在性）与注册漏跑两条通道兜住，不靠自愈。
#    ⇒ 自愈白名单 ⊂ gen_schedule_stats.TASKS（机检：test_registry_selfheal_subset_of_gen）。
HEAL_ACTIONS = {
    "update_all":          ["bash", "scripts/update_all.sh", "force"],
    "backfill_evening":    ["bash", "scripts/backfill_metrics.sh"],
    "intraday_snapshot":   ["bash", "scripts/intraday_snapshot.sh", "force"],
    "futures_backfill":    ["bash", "scripts/futures_backfill.sh", "force"],
    "lhb_backfill":        ["bash", "scripts/lhb_backfill.sh", "force"],
    "rzhb_backfill":       ["bash", "scripts/rzhb_backfill.sh", "force"],
    "etf_national_team":   ["bash", "scripts/etf_national_team_backfill.sh", "force"],
    "lab_auto":            ["bash", "scripts/update_lab.sh", "force"],
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
    """返回任务运行状态（macOS launchctl / Linux systemctl），失败返回 None。
    条件兼容：检测到 systemctl 用 `systemctl is-active <label>.service`，active→'running'；
    否则走 macOS launchctl print（state = running/not running）。
    调用方 `"running" in st` 判断在跑跳过。
    """
    if not label:
        return None
    if shutil.which("systemctl"):
        # Linux: systemd unit 名 = launchd label 把 com.trade. 前缀映射成 trade-（云上实际 unit 名）
        unit = label.replace("com.trade.", "trade-", 1) + ".service"
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return None
        st = (r.stdout or "").strip()
        if not st:
            return None
        # oneshot 服务运行中 is-active=activating(非 active),同样视为在跑,避免误判重跑误杀
        return "running" if st in ("active", "activating") else st
    # macOS: launchctl print
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


def _lookup_run(task):
    """取该任务最近一次运行的证据(逻辑在 core.lookup_run_from_logs,双源:heal.log+定时日志)。"""
    try:
        import gen_schedule_stats as g
    except Exception as e:
        print(f"[self_heal] 载入 gen_schedule_stats 失败(无法校验结果): {e}", file=sys.stderr)
        return None
    spec = next((t for t in g.TASKS if t.get("task") == task), None)
    if spec is None:
        return None
    try:
        return core.lookup_run_from_logs(task, spec, LOG_DIR, g)
    except Exception as e:
        print(f"[self_heal] 解析 {task} 日志失败: {e}", file=sys.stderr)
        return None


# 任务 → 进程特征(pgrep -f 正则,M4)。触发前查:任务脚本/上一次 heal 的重跑仍在跑 → 不重复触发。
# `[x]` 写法让正则匹配 "update_all.sh" 但**不匹配 pgrep 自己的命令行**(经典 -f 自匹配坑)。
PGREP_PATTERNS = {
    "update_all":        r"[u]pdate_all\.sh",
    "backfill_evening":  r"[b]ackfill_(metrics|indices)\.sh",
    "intraday_snapshot": r"[i]ntraday_snapshot\.sh",
    "futures_backfill":  r"[f]utures_backfill\.sh",
    "lhb_backfill":      r"[l]hb_backfill\.sh",
    "rzhb_backfill":     r"[r]zhb_backfill\.sh",
    "etf_national_team": r"[e]tf_national_team_backfill\.sh",
    "lab_auto":          r"[u]pdate_lab\.sh",
}


def task_process_running(task):
    """任务脚本进程是否在跑(查不到 pgrep/异常 → 按「未运行」处理,不阻塞自愈)。"""
    pat = PGREP_PATTERNS.get(task)
    if not pat:
        return False
    try:
        r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=10)
    except Exception as e:
        print(f"[self_heal] pgrep 检查 {task} 失败(按未运行处理): {e}", file=sys.stderr)
        return False
    return any(pid.strip().isdigit() for pid in (r.stdout or "").splitlines())


def _trigger(task, cmd):
    """后台触发重跑：nohup + & detach(self_heal 退出不杀重跑任务)。"""
    cmd_str = " ".join(cmd)
    log_file = LOG_DIR / f"{task}_heal.log"
    full_cmd = f"nohup {cmd_str} >> {log_file} 2>&1 &"
    try:
        subprocess.run(full_cmd, shell=True, cwd=str(REPO), timeout=5)
        return True, ""
    except Exception as e:
        return False, str(e)


_DRYRUN = os.environ.get("SELF_HEAL_NOTIFY_DRYRUN") == "1"


def _notify(args):
    """调用 scripts/notify.py(不改 notify.py 本身);失败只告警不阻塞自愈主流程。"""
    cmd = [sys.executable, str(REPO / "scripts" / "notify.py")] + args
    if _DRYRUN:
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print(f"[self_heal] notify rc={r.returncode}: {(r.stderr or '')[-300:]}",
                  file=sys.stderr)
        return r.returncode == 0
    except Exception as e:
        print(f"[self_heal] notify 失败(不阻塞): {e}", file=sys.stderr)
        return False


def _notify_info(subject, body):
    """达每日上限=正常状态, 只落 dashboard(info), 不推送邮件/飞书(2026-09-24 降噪口径)。"""
    return _notify([subject, body, "--tier", "info"])


def _notify_escalate(task, streak, basis):
    """同一任务连续 heal 失败 ≥2 次 → 升级告警。

    四元组(#264 件F):tier=warning / dedup 21600s / 域=collect(self_heal_repeat_fail_<task>)
    / 首报=连败达到 ≥2 即尝试发送,靠 6h 去重窗压成每 6h 最多一条;发送失败由 core
    记 escalate_pending,下一轮补发(仍受 6h 窗约束)。
    ⚠️ 不带 --alert-issue:notify.py 只在 tier=critical 时写 data/alerts/latest.md
    (notify.py:3167),warning 级带这个参数是死参数,会误导值班以为 latest.md 有记录。
    """
    subject = f"[告警] 自愈连续失败 {task} 累计 {streak} 次"
    body = (f"任务 {task} 连续 {streak} 次自愈后校验结果仍为 FAIL。\n"
            f"最近一次校验依据: {basis}\n"
            f"说明:自愈只是自动重跑;连续失败通常代表重跑解决不了(部署闸门/外部源/口径),"
            f"请人工排查,避免继续消耗配额。")
    return _notify([
        subject, body,
        "--tier", "warning",
        "--dedup-key", f"self_heal_repeat_fail_{task}",
        "--dedup-window", str(core.NOTIFY_DEDUP_WINDOW_SEC),
        "--from-prefix", "[告警]",
    ])


def _intraday_skip(task, now):
    """§8 盘中保护:update_all 的 force = 全量 export+deploy,交易日盘中跳过。

    其他任务(backfill/futures/lhb/rzhb/etf_nt)不涉及全量 export,盘中可跑不加保护。
    节假日未严格判断(盘中跳过即使节假日也无害,只是少跑一次自愈,收盘后/次日正常触发)。
    """
    if task != "update_all":
        return False
    hhmm = int(now.strftime("%H%M"))
    return now.isoweekday() <= 5 and 930 <= hhmm <= 1530


def _probe(task, heal_at):
    return core.probe_artifact(REPO, task, heal_at)


# 1) 读 schedule_stats.json
if not STATS_FILE.exists():
    print(f"[self_heal] {STATS_FILE} 不存在，无可 heal 任务，退出", file=sys.stderr)
    sys.exit(0)
try:
    stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
except Exception as e:
    print(f"[self_heal] stats 解析失败: {e}", file=sys.stderr)
    sys.exit(0)

# 2) 一轮决策(校验上一轮 heal → 升级连续失败 → 每任务配额内触发)
summary = core.run_cycle(
    repo=REPO, stats=stats, state_path=STATE_FILE, audit_path=AUDIT_LOG, now=NOW,
    heal_actions=HEAL_ACTIONS, labels=LABELS, launch_state=launchctl_state,
    trigger=_trigger, notify_info=_notify_info, notify_escalate=_notify_escalate,
    lookup_run=_lookup_run, artifact_probe=_probe, intraday_skip=_intraday_skip,
    task_running=task_process_running,
)

ts = NOW.strftime("%Y-%m-%d %H:%M:%S")
if summary["verified"]:
    print(f"[{ts}] VERIFY {len(summary['verified'])} 次: " + ", ".join(
        f"{e['task']}={e['result']}" for e in summary["verified"]))
if summary["escalated"]:
    print("[self_heal] ESCALATE: " + ", ".join(
        f"{e['task']}x{e['streak']}({'SENT' if e['sent'] else 'FAILED'})"
        for e in summary["escalated"]))
if summary["healed"]:
    print(f"[{ts}] HEAL 触发 {len(summary['healed'])} 个任务: {summary['healed']}")
elif not summary["verified"]:
    print(f"[{ts}] OK 无需 heal 的任务（无失败/失败任务在跑/旧问题/配额已用尽）")
state = core.load_state(STATE_FILE, NOW.strftime("%Y-%m-%d"))
print(f"[self_heal] 今日已 heal {state['count']}/{core.TOTAL_DAILY_LIMIT} 次"
      f"（每任务上限 {core.PER_TASK_DAILY_LIMIT}）")
PYEOF

# 总是 exit 0：自愈动作已后台触发，避免 systemd/launchd 因非0退出重试
exit 0