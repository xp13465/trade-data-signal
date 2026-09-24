#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""r2_skip 告警误报修正验证 harness(2026-09-24, r2skip-alert-fix 复现段)。

同构保证: OLD/NEW 消费块**直接从 git 对象与 worktree 文件逐字节提取**(非手写副本),
dedent 后包成 consume_* 函数——被测逻辑 = 上线代码逻辑, 杜绝第二份实现漂移
(§5.4⑦ repro-script-second-implementation-drift)。

场景:
  ① 每日一轮任务单次 skip(overfit_monitor 21:40 撞锁, r2_skip_count=1 滞留到次日):
     OLD(改前) 连续 6 轮逐轮 +1 -> 第 3 轮达阈值 3 必误报 SEVERE; NEW(改后) 仅前 2 轮
     last_run 在 30min 观察窗口内被计数(最大 2 < 3), 之后判滞留清零, 永不 SEVERE。
  ② 高频任务连续 skip(intraday_snapshot 每轮 fresh last_run): OLD/NEW 都第 3 轮 SEVERE
     (证明真告警一条没被削弱)。
  ③ 恢复场景: 高频任务 skip 停止(r2_skip_count=0) -> OLD/NEW 计数都清零(无回归)。

用法(在 worktree 根): python3 docs/ops/scripts/verify_r2skip_fix.py
"""
import re
import subprocess
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

HEAD_BLOCK_START = "            _r2_skip_cnt = s.get(\"r2_skip_count\")"
BLOCK_END_COMMENT = "# P2(2026-09-24 r2 终审): EXTRA 任务停摆漏跑告警。"


def extract_block(source_lines: list[str]) -> str:
    start = None
    for i, ln in enumerate(source_lines):
        if ln == HEAD_BLOCK_START:
            start = i
            break
    if start is None:
        raise SystemExit("找不到消费块起点")
    for j in range(start, len(source_lines)):
        if "P2(2026-09-24 r2 终审): EXTRA 任务停摆漏跑告警。" in source_lines[j]:
            end = j
            break
    else:
        raise SystemExit("找不到消费块终点")
    return "\n".join(source_lines[start:end])


def build_consume(block: str, obs_window: timedelta | None) -> str:
    """把消费块(12 空格基础缩进)dedent 成函数体, 注入 consume_ 函数外壳。"""
    body = textwrap.dedent(block)
    head = (
        "def consume(s, alert_state, seen_keys_this_run, alerts, NOW, "
        "R2_SKIP_CONTINUOUS_THRESHOLD=3, R2_SKIP_OBS_WINDOW=None):\n"
        "    from datetime import datetime\n"
        "    if R2_SKIP_OBS_WINDOW is None:\n"
        "        R2_SKIP_OBS_WINDOW = __import__('datetime').timedelta(minutes=30)\n"
    )
    return head + "\n".join("    " + l if l.strip() else "" for l in body.splitlines())


def get_old_block() -> str:
    out = subprocess.run(
        ["git", "show", "HEAD:scripts/schedule_monitor.sh"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    return extract_block(out)


def get_new_block() -> str:
    p = Path("scripts/schedule_monitor.sh").read_text(encoding="utf-8").splitlines()
    return extract_block(p)


def run_scenario(name: str, fn, rounds: list[tuple[datetime, dict]]):
    alert_state = {}
    seen_keys_this_run = set()
    alerts = []
    for now, entry in rounds:
        seen_keys_this_run.clear()
        alerts_prev = len(alerts)
        fn(entry, alert_state, seen_keys_this_run, alerts, now)
        if len(alerts) > alerts_prev:
            print(f"    {now:%H:%M} SEVERE 触发! alerts={alerts[-1]}")
    task = rounds[0][1]["task"]
    cnt_key = f"{task}|r2_skip_rounds"
    print(f"  [{name}] 共触发 SEVERE {len(alerts)} 条, 计数 key 终值: "
          f"{alert_state.get(cnt_key, {}).get('skip_rounds')}")


def scenario_daily(fn, tag):
    """每日一轮任务单次 skip: last_run 恒 21:40(次日新一轮前不再运行), r2_skip_count=1 滞留。"""
    entry = {"task": "overfit_monitor", "r2_skip_count": 1, "last_run": "2026-09-24 21:40"}
    base = datetime(2026, 9, 24, 21, 40)
    rounds = [(base + timedelta(minutes=m), dict(entry)) for m in (5, 20, 35, 50, 65, 80)]
    print(f"== {tag} 每日一轮单次 skip(last_run 恒 21:40, r2_skip_count=1 滞留 6 轮) ==")
    run_scenario("每日一轮", fn, rounds)


def scenario_highfreq(fn, tag):
    """高频任务连续 skip: 每轮 last_run 恒新鲜(5min 前), r2_skip_count=1 每轮新发生。"""
    base = datetime(2026, 9, 24, 10, 0)
    entry0 = {"task": "intraday_snapshot", "r2_skip_count": 1, "last_run": "2026-09-24 09:55"}
    rounds = []
    for m in (0, 15, 30, 45, 60):
        lr = (base + timedelta(minutes=m - 5)).strftime("%Y-%m-%d %H:%M")
        rounds.append((base + timedelta(minutes=m), dict(entry0, last_run=lr)))
    print(f"== {tag} 高频任务连续 skip(intraday_snapshot 每轮 fresh last_run, 连续 5 轮) ==")
    run_scenario("高频连续", fn, rounds)


def scenario_recovery(fn, tag):
    """高频任务 skip 停止(第 3 轮 r2_skip_count=0) -> 计数清零。"""
    base = datetime(2026, 9, 24, 10, 0)
    rounds = []
    for m in (0, 15, 30, 45):
        lr = (base + timedelta(minutes=m - 5)).strftime("%Y-%m-%d %H:%M")
        cnt = 0 if m >= 30 else 1  # 30 起 skip 停止
        rounds.append((base + timedelta(minutes=m),
                       {"task": "intraday_snapshot", "r2_skip_count": cnt, "last_run": lr}))
    print(f"== {tag} 高频任务 skip 第 3 轮停止 -> 计数清零 ==")
    run_scenario("恢复", fn, rounds)


def scenario_live_transition(fn, tag):
    """存量误报过渡: 线上 9-24 已挂 overfit_monitor|r2_skip_alert active(改前误报),
    改后 NEW 消费滞留 skip -> 计数清零 + 告警 key 不 seen(主恢复循环据此发恢复邮件),
    不重发 SEVERE、不振荡。"""
    base = datetime(2026, 9, 24, 22, 15)
    alert_state = {
        "overfit_monitor|r2_skip_alert": {
            "status": "active", "first_seen": "2026-09-24 21:45:00",
            "last_alerted": "2026-09-24 22:15:00", "keyword": "r2_skip_continuous",
            "line_sample": "r2_skip_count=1 连续4轮",
        },
        "overfit_monitor|r2_skip_rounds": {"skip_rounds": 4,
                                            "first_seen": "2026-09-24 21:45:00"},
    }
    seen = set()
    alerts = []
    entry = {"task": "overfit_monitor", "r2_skip_count": 1, "last_run": "2026-09-24 21:40"}
    print(f"== {tag} 存量误报过渡(alert key 已 active, 改后消费滞留 skip) ==")
    fn(entry, alert_state, seen, alerts, base)
    alert_key_seen = "overfit_monitor|r2_skip_alert" in seen
    rounds_now = (alert_state.get("overfit_monitor|r2_skip_rounds") or {}).get("skip_rounds")
    print(f"  新 SEVERE: {len(alerts)} 条 | 计数清零后值: {rounds_now} | "
          f"告警 key 本轮 seen: {alert_key_seen}(False=主恢复循环将判消失发恢复邮件)")
    assert len(alerts) == 0 and rounds_now == 0 and not alert_key_seen, "存量误报过渡失败"


def main():
    old_ns = {}
    exec(build_consume(get_old_block(), None), old_ns)
    new_ns = {}
    exec(build_consume(get_new_block(), timedelta(minutes=30)), new_ns)
    consume_old = old_ns["consume"]
    consume_new = new_ns["consume"]

    scenario_daily(consume_old, "OLD(改前)")
    scenario_daily(consume_new, "NEW(改后)")
    scenario_highfreq(consume_old, "OLD(改前)")
    scenario_highfreq(consume_new, "NEW(改后)")
    scenario_recovery(consume_old, "OLD(改前)")
    scenario_recovery(consume_new, "NEW(改后)")
    scenario_live_transition(consume_new, "NEW(改后)")


if __name__ == "__main__":
    main()
