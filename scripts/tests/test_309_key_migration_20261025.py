# -*- coding: utf-8 -*-
"""#309 P2 键迁移假恢复回归(2026-10-25)。

审查场景: 云上 `s06_snapshot|exit!=0|124` 仍 active; 新口径下该 stats 行被 unit 通道
接管(`{task}|unit_exit!=0|124`), 旧键不会进 seen_keys_this_run ⇒ 恢复环误发
「已恢复」, 而同轮新键首报 SEVERE。用户会同时收到「故障」+「已恢复」(事实相反)。

取用生产实现:
  - `_migrate_unit_owned_keys` 从 heredoc AST 提取
  - 恢复检测循环整段 AST 提取(与生产同一份代码, 不复制判定)
全程 static-only: 只喂 dict, 不跑业务脚本、不触达 notify。
"""
import ast
import datetime
import textwrap
import types

from _monitor_conclusion_309 import heredoc_source, namespace

NOW = datetime.datetime(2026, 10, 25, 21, 0)
TASK = "s06_snapshot"
OLD = f"{TASK}|exit!=0|124"
NEW = f"{TASK}|unit_exit!=0|124"


def _active(key):
    return {"status": "active", "keyword": "unit_exit", "tier": "severe",
            "first_seen": "2026-10-24 00:00:01", "last_alerted": "2026-10-24 00:00:01"}


def _recovery_loop():
    """提取恢复检测 for 块(depends: seen_keys_this_run / alert_state / recoveries)。"""
    src = heredoc_source()
    tree = ast.parse(src)
    segs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            seg = ast.get_source_segment(src, node) or ""
            if "recoveries.append" in seg and "_key not in seen_keys_this_run" in seg:
                segs.append(textwrap.dedent(" " * node.col_offset + seg))
    assert segs, "schedule_monitor.sh 恢复检测循环被重命名/重构了? 本测试锚点需同步"
    return max(segs, key=len)


def _run_recovery(alert_state, seen):
    ns = {
        "alert_state": alert_state,
        "seen_keys_this_run": seen,
        "recoveries": [],
        "in_progress_tasks": set(),
        "NOW": NOW,
        "adr": types.SimpleNamespace(
            MERGE_PREFIX="merge|",
            R2_CONGESTION_SUMMARY_KEY_PREFIX="r2_pipeline_congestion|",
            DUR_BUFFER_KEY_MARK="|dur_buffer|",
        ),
        "_recovery_cooldown_ok": lambda _k, _i: True,
        "RECOVERY_COOLDOWN": datetime.timedelta(hours=6),
        # #309 F2(2026-10-26): 恢复环新增跳过前缀(取生产常量, 不复制字面量)
        "CONCLUSION_STATUS_KEY_PREFIX": namespace()["CONCLUSION_STATUS_KEY_PREFIX"],
        "print": lambda *a, **k: None,
    }
    exec(_recovery_loop(), ns)  # noqa: S102
    return ns["recoveries"]


def _register_new_key(alert_state, seen):
    """模拟同轮 unit 通道首报新键(alert_state 无该键 → 发 SEVERE + 记 active)。"""
    state = alert_state
    state[NEW] = _active(NEW)
    seen.add(NEW)
    return state


def test_old_key_active_plus_new_key_first_report_has_no_recovery():
    state = {OLD: _active(OLD)}
    seen = set()
    moved = namespace()["_migrate_unit_owned_keys"](
        TASK, 124, 124, state, seen, NOW.strftime("%Y-%m-%d %H:%M:%S"))
    _register_new_key(state, seen)
    recoveries = _run_recovery(state, seen)

    assert recoveries == [], recoveries
    assert moved == [OLD]
    assert state[OLD]["status"] == "recovered"
    assert state[OLD]["recovery_reason"] == "migrated_to_unit_key"
    assert state[NEW]["status"] == "active"


def test_without_migration_the_same_state_would_send_false_recovery():
    """反向对照(判别力): 不迁移 → 恢复环必发 1 条假恢复, 证明用例有牙。"""
    state = {OLD: _active(OLD)}
    seen = set()
    _register_new_key(state, seen)
    recoveries = _run_recovery(state, seen)
    assert len(recoveries) == 1
    assert recoveries[0]["task"] == TASK


def test_old_key_with_different_code_is_retired_not_recovered_email():
    old1 = f"{TASK}|exit!=0|1"
    state = {old1: _active(old1)}
    seen = set()
    moved = namespace()["_migrate_unit_owned_keys"](
        TASK, 124, 1, state, seen, NOW.strftime("%Y-%m-%d %H:%M:%S"))
    _register_new_key(state, seen)
    recoveries = _run_recovery(state, seen)
    assert recoveries == []
    assert moved == [old1]
    assert state[old1]["recovery_reason"] == "superseded_by_new_code"


def test_failure_without_event_still_marked_seen():
    """ledger-stale: stats 有非 0 码但本轮不发事件; 新键若已 active 不许被误恢复。"""
    state = {OLD: _active(OLD), NEW: _active(NEW)}
    seen = set()
    namespace()["_migrate_unit_owned_keys"](
        TASK, 124, 124, state, seen, NOW.strftime("%Y-%m-%d %H:%M:%S"))
    # 本轮不登记任何事件(模拟 ledger-stale 不发 SEVERE)
    recoveries = _run_recovery(state, seen)
    assert recoveries == []
    assert state[NEW]["status"] == "active"
    assert state[OLD]["status"] == "recovered"