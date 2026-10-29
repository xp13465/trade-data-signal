# -*- coding: utf-8 -*-
"""#309 审查补测: monitor 内联分支(2026-10-25, P2-1/P2-2/P2-4)。

两个分支此前零覆盖(独立审查指出的「机制 C 无测试」):
  1. `schedule_monitor.sh` 的 deploy warning 分支(`--tier warning --dedup-key
     {task}|deploy_warn`): 必须通知为 warning, 不许当 severe, 且不进 alerts。
  2. launchctl/ systemd `is-active=failed` 循环:
     - label 在 stats 里但 stats 仍 0/未知 → `{label}|failed_no_exit` SEVERE(通道失效兜底)
     - unit 真值通道已拿到非 0 码 → 本通道 defer, 同轮只留 unit 一条(P2-4)
     - 不在 stats 的自监控 label(如 self-heal)且 unit 码读不到 → 仍发 `{label}|failed`
       (降级告警, 防自愈失效完全静默)

取用方式: 从 `schedule_monitor.sh` 的 python heredoc **ast 提取真实代码块**后 exec
(不复制逻辑, 防第二份实现漂移)。**全程 static-only**: `launchctl_loaded` /
`subprocess.run` / `notify` 全部打桩, 只记录调用次数; 不启 systemctl、不跑业务脚本、
不触达真实 notify/邮件/飞书。
"""
import ast
import functools
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from _monitor_conclusion_309 import heredoc_source

MONITOR = Path(__file__).absolute().parent.parent.parent / "scripts" / "schedule_monitor.sh"


def _source():
    return heredoc_source()


@functools.lru_cache(maxsize=None)
def _candidate_segments(kind, needles):
    """按(节点类型, 必要子串)缓存源码段, 同一组合只提取一次。

    性能(#357): `ast.get_source_segment` 每次调用都要把整份源码切一遍行,
    对 393 个 If 逐个取曾要 8.6s, 整文件 35s。于是:
      1. 先 isinstance 筛类型;
      2. 再用 `needles` 做**必要条件预筛**——节点所在行的整段文本是精确
         源码段的超集(精确段只在行内按列裁剪), 超集里都不含该子串 ⇒ 精确段
         必然不含, 可以跳过, 不必真去取段;
      3. 结果缓存, 22 个用例重复取同一代码块只算一次。
    `needles` 只做预筛, 最终是否入选仍由调用方的 `pred(精确段)` 判定, 语义不变。
    """
    src = _source()
    tree = ast.parse(src)
    lines = src.split("\n")
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, kind):
            continue
        span = "\n".join(lines[node.lineno - 1: node.end_lineno or node.lineno])
        if any(n not in span for n in needles):
            continue
        out.append((node, ast.get_source_segment(src, node) or ""))
    return tuple(out)


def _segment(pred, *, kind=ast.If, pick="smallest", needles=()):
    """取代码块并抹平原始缩进(首行无缩进、续行带原缩进, 需要按 col_offset 对齐)。"""
    segs = []
    for node, seg in _candidate_segments(kind, tuple(needles)):
        if pred(seg):
            # 给首行补回 col_offset 个空格后统一 dedent, 续行缩进才与首行同基准
            segs.append(textwrap.dedent(" " * node.col_offset + seg))
    assert segs, "schedule_monitor.sh 里找不到目标代码块: 被重命名/重构了? 本测试锚点需同步"
    return min(segs, key=len) if pick == "smallest" else max(segs, key=len)


# ---------------------------------------------------------------- P2-2 deploy warning

def _run_deploy_branch(row, calls):
    seg = _segment(lambda s: "deploy_warn" in s, needles=("deploy_warn",))
    ns = {
        "s": row,
        "exit_code": row.get("last_exit"),
        "subprocess": SimpleNamespace(
            run=lambda cmd, **kw: (calls.append(list(cmd)), SimpleNamespace(returncode=0))[1]),
        "sys": sys,
        "REPO": Path("/nonexistent-repo"),
        "seen_keys_this_run": set(),
        "alerts": [],
        "alert_state": {},
        "print": lambda *a, **k: None,
    }
    # 分支体可能含 continue(不同版本), 包一层假循环保证可 exec
    exec("for _once in (0,):\n" + "\n".join("    " + ln for ln in seg.splitlines()), ns)  # noqa: S102
    return ns


def _warn_row(**kw):
    row = {
        "task": "lhb_backfill", "last_exit": 1, "last_exit_tier": "warning",
        "last_run": "2026-10-20 18:31", "log_deploy": 1, "log_collect": 0,
    }
    row.update(kw)
    return row


def test_deploy_warning_branch_notifies_warning_not_severe():
    calls = []
    ns = _run_deploy_branch(_warn_row(), calls)
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1].endswith("notify.py")
    assert cmd[cmd.index("--tier") + 1] == "warning"
    assert "--severe" not in cmd
    assert cmd[cmd.index("--dedup-key") + 1] == "lhb_backfill|deploy_warn"
    assert "lhb_backfill|deploy_warn" in ns["seen_keys_this_run"]
    # warning 聚合不进本轮 alerts(否则会被当 SEVERE 汇总发)
    assert ns["alerts"] == []


def test_deploy_branch_does_nothing_for_zero_exit():
    calls = []
    _run_deploy_branch(_warn_row(last_exit=0, last_exit_tier=None), calls)
    assert calls == []


def test_deploy_branch_does_nothing_for_non_warning_tier():
    """tier 不是 warning ⇒ 不走本分支(分级由口径决定, 不许 warning 分支兜所有失败)。"""
    calls = []
    _run_deploy_branch(_warn_row(last_exit=0, last_exit_tier=None), calls)
    assert calls == []


# ---------------------------------------------------------------- P2-1/P2-4 failed 循环

FAILED_LOOP_PRED = lambda s: "LAUNCHCTL_LABELS" in s and "failed_no_exit" in s


def _run_failed_loop(label, state, *, stats_row=None, unit_code=None,
                     systemd_on=True, alert_state=None, unit_source="systemd",
                     registry_units=None):
    seg = _segment(FAILED_LOOP_PRED, kind=ast.For,
                   needles=("LAUNCHCTL_LABELS", "failed_no_exit"))
    notify_calls = []
    funit = label.replace("com.trade.", "trade-", 1) + ".service"
    from _monitor_conclusion_309 import namespace
    ns = {
        "LAUNCHCTL_LABELS": [label],
        "launchctl_loaded": lambda _l: state,
        "notify": lambda *a, **k: notify_calls.append((a, k)),
        "_schedule_stats_labels": {label} if stats_row is not None else set(),
        "_unit_stats_by_task": {"lhb_backfill": stats_row} if stats_row is not None else {},
        "UNIT_STATES": {funit: {"code": unit_code, "source": unit_source}},
        "UNIT_REGISTRY_UNITS": ({funit} if registry_units is None else registry_units),
        "SYSTEMD_TRUTH_ON": systemd_on,
        "NOW": __import__("datetime").datetime(2026, 10, 20, 18, 45),
        "alert_state": alert_state if alert_state is not None else {},
        "alerts": [],
        "seen_keys_this_run": set(),
        "_active_escalate": lambda *a, **k: None,
        "not_loaded_help": lambda _l: ("probe", "recover"),
        "SELF_HEAL_THRESHOLD": 3,
        "print": lambda *a, **k: None,
        # P2(2026-10-25): defer/_fcovered 判据本身也从生产 AST 取, 不复制。
        "_unit_channel_will_register": namespace()["_unit_channel_will_register"],
        "_stats_failure_covered": namespace()["_stats_failure_covered"],
    }
    exec(seg, ns)  # noqa: S102
    ns["notify_calls"] = notify_calls
    return ns


def test_failed_no_exit_raises_when_stats_channel_blind():
    """stats 仍 0/未知 + unit 码读不到 ⇒ 通道失效兜底 SEVERE, 且只有这一条。"""
    ns = _run_failed_loop(
        "com.trade.lhb-backfill", "failed",
        stats_row={"task": "lhb_backfill", "last_exit": 0, "unit_exit": 0},
        unit_code=None,
    )
    assert len(ns["alerts"]) == 1
    assert "通道失效" in ns["alerts"][0]
    assert "com.trade.lhb-backfill|failed_no_exit" in ns["alert_state"]
    assert ns["seen_keys_this_run"] == {"com.trade.lhb-backfill|failed_no_exit"}
    assert ns["notify_calls"] == []  # 本分支只登记 alerts, 不自己发通知


def test_failed_no_exit_defers_to_unit_channel():
    """P2-4: unit 真值通道已拿到 exit=1 ⇒ 本通道不重复登记(同轮只留 unit 一条)。"""
    ns = _run_failed_loop(
        "com.trade.self-heal", "failed",
        stats_row=None, unit_code=1, systemd_on=True,
    )
    assert ns["alerts"] == []
    assert ns["alert_state"] == {}
    assert ns["seen_keys_this_run"] == set()


def test_self_heal_without_unit_truth_still_alerts():
    """反向对照(不许静默): systemd 真值读不到时, 自监控 failed 仍降级发 SEVERE。"""
    ns = _run_failed_loop(
        "com.trade.self-heal", "failed",
        stats_row=None, unit_code=None, systemd_on=True,
    )
    assert len(ns["alerts"]) == 1
    assert "self-heal" in ns["alerts"][0]
    assert "com.trade.self-heal|failed" in ns["alert_state"]
    assert ns["notify_calls"] == []


def test_failed_loop_loaded_state_is_silent():
    ns = _run_failed_loop("com.trade.update-all", "loaded")
    assert ns["alerts"] == [] and ns["alert_state"] == {}
    assert ns["notify_calls"] == []


def test_self_heal_alerts_again_when_unit_channel_rolled_back():
    """一行回滚(MONITOR_EXIT_SOURCE=log): unit 通道关掉后 failed 必须回到本通道,
    不许因新增 defer 而彻底静默(self-heal 失效是最需要人接管的故障)。"""
    ns = _run_failed_loop(
        "com.trade.self-heal", "failed",
        stats_row=None, unit_code=1, systemd_on=False,
    )
    assert len(ns["alerts"]) == 1
    assert "com.trade.self-heal|failed" in ns["alert_state"]


# ---------------------------------------------------------------- P2 defer 判据一致性

def _stats_row(**kw):
    row = {"task": "lhb_backfill", "last_exit": 1, "unit_exit": 1,
           "unit_exit_source": "systemd", "last_run": "2026-10-20 18:31",
           "unit_exit_ts": "2026-10-20 18:31:02", "unit_start": "2026-10-20 18:30:02"}
    row.update(kw)
    return row


def test_ledger_stale_live_code_does_not_silence_failed_loop():
    """live 码是 ledger-stale(新鲜度未确认)⇒ unit 通道不会登记 ⇒ 本通道必须报。"""
    ns = _run_failed_loop(
        "com.trade.lhb-backfill", "failed",
        stats_row=_stats_row(unit_exit_source="ledger-stale"), unit_code=1,
        unit_source="ledger-stale",
    )
    assert len(ns["alerts"]) == 1
    assert "通道失效" in ns["alerts"][0]
    assert "com.trade.lhb-backfill|failed_no_exit" in ns["alert_state"]


def test_unit_outside_registry_does_not_defer():
    """unit 不在 43 行注册表 ⇒ 新通道根本不遍历它 ⇒ 本通道不许 defer。"""
    ns = _run_failed_loop(
        "com.trade.self-heal", "failed", unit_code=1, registry_units=set())
    assert len(ns["alerts"]) == 1
    assert "com.trade.self-heal|failed" in ns["alert_state"]


def test_stale_stats_failure_is_not_covered_by_exit_channel():
    """24h 前的旧非 0 码会被 exit 通道 stale 降级(不发) ⇒ 不许当已覆盖。"""
    ns = _run_failed_loop(
        "com.trade.lhb-backfill", "failed",
        stats_row=_stats_row(last_run="2026-10-15 18:31",
                             unit_exit_ts="2026-10-15 18:31:02"),
        unit_code=None,
    )
    assert len(ns["alerts"]) == 1
    assert "通道失效" in ns["alerts"][0]


def test_fresh_stats_failure_is_covered_reverse_control():
    """反向对照: 同一形状但码新鲜 ⇒ 真被覆盖, 本通道不重复报。"""
    ns = _run_failed_loop(
        "com.trade.lhb-backfill", "failed", stats_row=_stats_row(), unit_code=None)
    assert ns["alerts"] == []
    assert ns["alert_state"] == {}


NOW_H = __import__("datetime").datetime(2026, 10, 20, 18, 45)


@pytest.mark.parametrize(
    "unit_code,unit_source,stats_row,systemd_on,registry,expect",
    [
        (124, "systemd", None, True, "in", True),                # live 非0, 注册表内
        (124, "ledger-stale", None, True, "in", False),          # 账本旧码不登记
        (None, "missing", None, True, "in", False),              # live 读不到且无 stats
        (None, "missing", _stats_row(), True, "in", True),       # stats 兜底(新鲜)
        (None, "missing", _stats_row(unit_exit_ts="2026-10-15 18:31:02"),
         True, "in", False),                                    # stats 太旧不兜底
        (None, "missing", _stats_row(unit_exit_source="ledger"), True, "in", True),
        (None, "missing", _stats_row(unit_exit_source="ledger-stale"),
         True, "in", False),
        (124, "systemd", None, False, "in", False),              # 通道关
        (124, "systemd", None, True, "out", False),              # 不在注册表
        (0, "systemd", _stats_row(), True, "in", False),         # live 0, stats 旧码不采信
    ],
)
def test_unit_channel_will_register_matches_real_registration(
        unit_code, unit_source, stats_row, systemd_on, registry, expect):
    """defer 判据必须与 `_unit_alert_events` 的实际登记条件逐项一致。"""
    from _monitor_conclusion_309 import namespace
    fn = namespace()["_unit_channel_will_register"]
    states = {"u.service": {"code": unit_code, "source": unit_source}}
    units = {"u.service"} if registry == "in" else set()
    assert fn("u.service", states, systemd_on, units, stats_row, NOW_H) is expect