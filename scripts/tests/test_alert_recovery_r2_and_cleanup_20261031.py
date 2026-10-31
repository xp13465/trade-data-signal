# -*- coding: utf-8 -*-
"""2026-10-31 P1/P2 回归: 恢复环 R2 白名单化 + 跨日一次性状态键清理。

P1 背景(云上实证, alert_state.json 202 条):
  `r2_consistency|exit!=0|1`(first_seen 10-21, last_alerted 10-22)与
  `r2_consistency|unit_exit!=0|124`(first_seen 10-26, last_alerted 10-27)长期 active,
  而 trade-r2-consistency.service 自 10-27 起每天 Finished successfully。
  根因 = 恢复环 `_key.startswith("r2_")` 一刀切跳过(本意只放过 R2 块 inline 自管的
  r2_unreachable / r2_overview_lag / r2_intraday_lag), 它同时吃掉了**任务名本身以 r2_
  开头**的普通告警键; 这两个键没有任何 inline 恢复点 ⇒ 永远不翻 recovered。

取用生产实现(防第二份实现漂移, memory repro-script-second-implementation-drift):
  恢复环整段从 `scripts/schedule_monitor.sh` 的 python heredoc **AST 提取**(同
  test_309_key_migration_20261025.py 手法); 判定函数取 `alert_denoise_rules` 真实函数。
  static-only: 只喂 dict, 不跑业务脚本、不触碰 notify / 网络。
"""
import ast
import datetime
import functools
import textwrap

import alert_denoise_rules as adr
from _monitor_conclusion_309 import heredoc_source, namespace

NOW = datetime.datetime(2026, 10, 31, 9, 0)
EXIT_KEY = "r2_consistency|exit!=0|1"
UNIT_KEY = "r2_consistency|unit_exit!=0|124"


def _active(key, first_seen="2026-10-26 23:45:01"):
    return {"status": "active", "keyword": key.rsplit("|", 1)[-1],
            "first_seen": first_seen, "last_alerted": first_seen}


@functools.lru_cache(maxsize=None)
def _recovery_loop_src():
    """提取恢复检测 for 块(与生产同一份代码; 锚点缺失即失败, 不静默跳过)。"""
    src = heredoc_source()
    tree = ast.parse(src)
    lines = src.split("\n")
    segs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        span = "\n".join(lines[node.lineno - 1: node.end_lineno or node.lineno])
        if "recoveries.append" not in span or "_key not in seen_keys_this_run" not in span:
            continue
        seg = ast.get_source_segment(src, node) or ""
        if "recoveries.append" in seg and "_key not in seen_keys_this_run" in seg:
            segs.append(textwrap.dedent(" " * node.col_offset + seg))
    assert segs, "schedule_monitor.sh 恢复检测循环找不到了? 本测试锚点需同步"
    return max(segs, key=len)


def _run_recovery(state, seen):
    """跑生产恢复环, 返回 (recoveries, state)。"""
    ns = {
        "alert_state": state,
        "seen_keys_this_run": set(seen),
        "recoveries": [],
        "in_progress_tasks": set(),
        "NOW": NOW,
        "adr": adr,  # 真实模块(MERGE_PREFIX / R2_CONGESTION_SUMMARY_KEY_PREFIX /
                     # DUR_BUFFER_KEY_MARK / is_r2_inline_managed_key 全部就位)
        "_recovery_cooldown_ok": lambda _k, _i: True,
        "RECOVERY_COOLDOWN": datetime.timedelta(hours=6),
        "CONCLUSION_STATUS_KEY_PREFIX": namespace()["CONCLUSION_STATUS_KEY_PREFIX"],
        "print": lambda *a, **k: None,
    }
    exec(_recovery_loop_src(), ns)  # noqa: S102
    return ns["recoveries"], state


# ══════════════ P1: 陈旧 active key 服务恢复后必须翻 recovered ══════════════

def test_stale_exit_key_flips_recovered_when_service_ok():
    state = {EXIT_KEY: _active(EXIT_KEY, "2026-10-21 00:00:01")}
    recoveries, state = _run_recovery(state, seen=set())
    assert state[EXIT_KEY]["status"] == "recovered", state[EXIT_KEY]
    assert state[EXIT_KEY]["last_recovered"] == NOW.strftime("%Y-%m-%d %H:%M:%S")
    # 状态翻转是本任务目标; 邮件是否发由尾部 r2_ 抑制策略单独决定(见报告)
    assert [r["task"] for r in recoveries] == ["r2_consistency"]


def test_stale_unit_exit_key_flips_recovered_when_service_ok():
    state = {UNIT_KEY: _active(UNIT_KEY)}
    _, state = _run_recovery(state, seen=set())
    assert state[UNIT_KEY]["status"] == "recovered", state[UNIT_KEY]


# ══════════════ V3: 真故障绝不误标(防恢复到假阳性) ══════════════

def test_real_failures_stay_active():
    """真实失败每轮都会被通道写进 seen_keys_this_run ⇒ 恢复环不许动它。"""
    true_unit = "r2_consistency|unit_exit!=0|124"
    true_exit = "update_all|exit!=0|1"
    state = {true_unit: _active(true_unit), true_exit: _active(true_exit)}
    _, state = _run_recovery(state, seen={true_unit, true_exit})
    assert state[true_unit]["status"] == "active"
    assert state[true_exit]["status"] == "active"


def test_same_task_new_failure_code_not_recovered():
    """同任务换了新失败码: 新码 key 在 seen 里 ⇒ active; 旧码 key 不在 seen ⇒ 才允许恢复。"""
    new_key = "r2_consistency|unit_exit!=0|137"
    state = {UNIT_KEY: _active(UNIT_KEY), new_key: _active(new_key)}
    _, state = _run_recovery(state, seen={new_key})
    assert state[new_key]["status"] == "active"
    assert state[UNIT_KEY]["status"] == "recovered"


# ══════════════ R2 inline 自管键仍必须被跳过(防每 15min 假恢复) ══════════════

def test_inline_managed_keys_still_skipped():
    state = {
        "r2_unreachable": _active("r2_unreachable"),
        "r2_overview_lag": _active("r2_overview_lag"),
        "r2_intraday_lag|buffer|20261031": {
            "status": "pending", "consecutive_count": 1},
        "overview_lag_3domain": _active("overview_lag_3domain"),
        EXIT_KEY: _active(EXIT_KEY),
    }
    _, state = _run_recovery(state, seen=set())
    assert state["r2_unreachable"]["status"] == "active"
    assert state["r2_overview_lag"]["status"] == "active"
    assert state["r2_intraday_lag|buffer|20261031"]["status"] == "pending"
    assert state["overview_lag_3domain"]["status"] == "active"
    # 对照: 同为 r2_ 文本前缀的「任务名」key 必须被恢复检测接管
    assert state[EXIT_KEY]["status"] == "recovered"


def test_inline_whitelist_truth_table():
    for k in ("r2_unreachable", "r2_overview_lag", "r2_intraday_lag",
              "r2_intraday_lag|buffer|20260929",
              "r2_overview_lag|buffer|20261028"):
        assert adr.is_r2_inline_managed_key(k) is True, k
    for k in (EXIT_KEY, UNIT_KEY, "r2_consistency", "update_all|exit!=0|1",
              "", None, 123):
        assert adr.is_r2_inline_managed_key(k) is False, k


def test_recovery_loop_source_no_blanket_r2_prefix():
    """源码形状守卫: 恢复环不得再出现一刀切 `startswith("r2_")`(P1 根因)。"""
    src = _recovery_loop_src()
    assert "adr.is_r2_inline_managed_key(_key)" in src
    assert '_key.startswith("r2_")' not in src


# ══════════════ P2: 跨日一次性状态键清理 ══════════════

def test_cleanup_deletes_past_day_buffers_keeps_today():
    state = {
        "r2_intraday_lag|buffer|20260929": {"status": "pending", "consecutive_count": 1},
        "overview_lag_3domain|buffer|20261016": {"status": "alerted", "consecutive_count": 2},
        "r2_overview_lag|buffer|20261028": {"status": "recovered", "consecutive_count": 0},
        "overview_lag_3domain|buffer|20261031": {"status": "pending", "consecutive_count": 1},
    }
    removed = adr.stale_dated_state_cleanup(state, NOW)
    assert sorted(removed) == [
        "overview_lag_3domain|buffer|20261016",
        "r2_intraday_lag|buffer|20260929",
        "r2_overview_lag|buffer|20261028",
    ]
    assert list(state) == ["overview_lag_3domain|buffer|20261031"]


def test_cleanup_deletes_past_day_congestion_keeps_today():
    state = {
        "r2_pipeline_congestion|20261001": {"phenomena": [], "summary_sent": False},
        "r2_pipeline_congestion|20261031": {"phenomena": ["x"], "summary_sent": False},
    }
    removed = adr.stale_dated_state_cleanup(state, NOW)
    assert removed == ["r2_pipeline_congestion|20261001"]
    assert "r2_pipeline_congestion|20261031" in state


def test_cleanup_deletes_zeroed_skip_counter_keeps_active_chain():
    state = {
        "fetch_news|r2_skip_rounds": {"skip_rounds": 0, "first_seen": "2026-09-24 12:00:01"},
        "intraday_snapshot|r2_skip_rounds": {"skip_rounds": 2, "first_seen": "2026-10-30 09:30:00"},
        "intraday_snapshot|r2_skip_alert": _active("intraday_snapshot|r2_skip_alert"),
    }
    removed = adr.stale_dated_state_cleanup(state, NOW)
    assert removed == ["fetch_news|r2_skip_rounds"]
    assert "intraday_snapshot|r2_skip_rounds" in state
    assert "intraday_snapshot|r2_skip_alert" in state


def test_cleanup_never_touches_active_alerts():
    state = {
        EXIT_KEY: _active(EXIT_KEY),
        UNIT_KEY: _active(UNIT_KEY),
        "overfit_monitor|✗ R2_UPLOAD_TIMEOUT|38e63da2": _active("x"),
        "monitor_recovery|pending": {"status": "pending", "items": []},
        "72h_sw_version": _active("72h_sw_version"),
    }
    before = dict(state)
    assert adr.stale_dated_state_cleanup(state, NOW) == []
    assert state == before


def test_cleanup_is_idempotent():
    state = {"r2_intraday_lag|buffer|20260929": {"status": "pending"},
             "fetch_news|r2_skip_rounds": {"skip_rounds": 0}}
    assert len(adr.stale_dated_state_cleanup(state, NOW)) == 2
    assert adr.stale_dated_state_cleanup(state, NOW) == []