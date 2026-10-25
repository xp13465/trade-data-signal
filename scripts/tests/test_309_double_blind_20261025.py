# -*- coding: utf-8 -*-
"""#309 P1b 双盲假 OK 穷举(2026-10-25)。

铁律(任务书必修1): 只要 **stats 的 unit_exit 非 0** 或 **monitor live 码非 0**,
结论行不得为 `OK 所有任务按计划执行`; 若因去重不发邮件, 至少结论行或告警台账可见。

取用生产实现: `_unit_alert_events` / `_build_conclusion` 从 schedule_monitor.sh AST
提取(见 `_monitor_conclusion_309.py`), 测试不复制判定逻辑。全程 static-only:
只喂 dict, 不启 systemctl、不跑业务脚本、不触达 notify。

「是否发邮件」模拟 = alert_state 去重: 事件 key 不在 alert_state(或非 active)才发。
"""
import datetime

import pytest

import unit_truth as ut
from _monitor_conclusion_309 import namespace

TASK = "s06_snapshot"
UNIT = "trade-s06-snapshot.service"
NOW = datetime.datetime(2026, 10, 25, 21, 0)
REGISTRY = [{"unit": UNIT, "task": TASK, "include": True}]


# ---------------------------------------------------------------- 构造器

def _live(kind):
    """live unit 状态: ok0 / fail124 / fail1 / read_fail / no_record。"""
    if kind == "read_fail":
        return ut.derive_unit_state(UNIT, {})  # source=missing, code=None
    if kind == "no_record":
        return ut.derive_unit_state(UNIT, {"LoadState": "loaded", "Result": ""})
    base_kind = "fail124" if kind == "fail124_missed" else kind
    props = {
        "LoadState": "loaded",
        "Result": "success" if base_kind in ("ok0",) else "exit-code",
        "ExecMainCode": "1",
        "ExecMainStatus": "0" if base_kind == "ok0" else base_kind.replace("fail", ""),
        "ExecMainStartTimestamp": "2026-10-25 20:35:01",
        "ExecMainExitTimestamp": "2026-10-25 20:58:01",
        "InvocationID": "inv-live",
        "ActiveState": "inactive",
        "NextElapseUSecRealtime": ("2026-10-25 10:00:00" if kind == "fail124_missed"
                                   else "2026-10-26 20:35:00"),
        "LastTriggerUSec": "2026-10-25 20:35:01",
    }
    return ut.derive_unit_state(UNIT, props)


def _srow(source, unit_exit, *, health="ok", unit_start="2026-10-25 20:35:01",
          unit_exit_ts="2026-10-25 20:58:01", last_exit=None, last_run="2026-10-25 20:35",
          missed=False):
    """stats 行(形状与 gen_schedule_stats 输出一致)。source 决定哪些 unit 字段有值。"""
    row = {
        "task": TASK, "unit": UNIT,
        "last_exit": unit_exit if last_exit is None else last_exit,
        "unit_exit": unit_exit,
        "unit_exit_source": source if source in ("systemd", "ledger", "ledger-stale") else None,
        "unit_result": None if unit_exit in (None, 0) else "timeout",
        "unit_start": unit_start,
        "unit_exit_ts": unit_exit_ts,
        "unit_timer_health": health,
        "unit_missed": missed,
        "last_run": last_run,
        "last_exit_tier": None,
    }
    if source == "systemd":
        row["exit_source"] = "systemd"
    elif source in ("ledger", "ledger-stale"):
        # 生产 gen 的口径: 可信即写 systemd, ledger 只体现在 unit_exit_source
        row["exit_source"] = "systemd"
    else:
        row["exit_source"] = source
    if source == "running":
        row.update({"unit_exit": None, "unit_exit_source": None, "unit_start": None,
                    "unit_exit_ts": None, "unit_timer_health": "unknown",
                    "unit_result": None, "last_exit": None})
    return row


def _run(row, live_kind, alert_state=None):
    """跑生产判定 + 模拟 alert_state 去重登记。返回 (events, emails, state, conclusion)。"""
    ns = namespace()
    events = ns["_unit_alert_events"](REGISTRY, {UNIT: _live(live_kind)},
                                      {TASK: row}, NOW)
    state = alert_state if alert_state is not None else {}
    emails = []
    for ev in events:
        key = ev["key"]
        cur = state.get(key)
        if cur is None or cur.get("status") != "active":
            emails.append(ev["msg"])
            state[key] = {"status": "active", "keyword": ev.get("keyword")}
        else:
            cur["last_alerted"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
    live_fails = [{"task": e["task"], "unit": e.get("unit"), "code": e.get("code"),
                   "source": e.get("source")}
                  for e in events if e["kind"] == "exit"]
    text = ns["_build_conclusion"]([row], NOW, cfu_failed=0, alerts=len(emails),
                                   unit_failures=live_fails, stats_refresh_ok=True)
    return events, emails, state, text


def _truth(s):
    return s.get("unit_exit_source") or s.get("exit_source")


# ---------------------------------------------------------------- 穷举表(审查 12 行 + 扩展)

CASES = [
    # id, stats_source, stats_unit_exit, live, health, 同码 active 旧 key, 期望邮件, 期望OK
    # 1 基线全绿
    ("1 systemd 全绿", "systemd", 0, "ok0", "ok", None, False, True),
    # 2 stats 124 + live 读失败 ⇒ 旧行为结论失败但零邮件(通道互相让位); 现在 stats 兜底必发
    ("2 stats124/liveNone", "systemd", 124, "read_fail", "ok", None, True, False),
    # 3 stats 124 + live 0 ⇒ live 更新(上一轮已成功): 不邮件, 结论仍不得 OK(偏保守)
    ("3 stats124/live0", "systemd", 124, "ok0", "ok", None, False, False),
    # 4 新 P1: stats running/None/unknown + live 124 ⇒ 必须发 + 不得 OK
    ("4 running/live124", "running", None, "fail124", "unknown", None, True, False),
    # 5 running + live 0 ⇒ 正常在跑/刚成功, OK
    ("5 running/live0", "running", None, "ok0", "unknown", None, False, True),
    # 6 双未知(running + live 读不到)⇒ 不邮件, 结论不判失败(stats 明确 running)
    ("6 running/liveNone", "running", None, "read_fail", "unknown", None, False, True),
    # 7 新 P1: stats log/None/unknown + live 124 ⇒ 必须发 + 不得 OK
    ("7 logNone/live124", "log", None, "fail124", "unknown", None, True, False),
    # 8 log/0 + live 124 ⇒ 必须发 + 不得 OK
    ("8 log0/live124", "log", 0, "fail124", "unknown", None, True, False),
    # 9 log/0 + live 0 ⇒ OK
    ("9 log0/live0", "log", 0, "ok0", "unknown", None, False, True),
    # 10a 账本新鲜补位 + live 读失败 ⇒ stats 兜底发邮件 + 不得 OK
    ("10a ledger/liveNone", "ledger", 1, "read_fail", "ok", None, True, False),
    # 10b 账本补位码新鲜度未确认(ledger-stale)⇒ 不发 SEVERE, 结论行必须标注(可见性兜底)
    ("10b ledger-stale/liveNone", "ledger-stale", 1, "read_fail", "ok", None, False, False),
    # 11 live 124 + 同码 key 已 active ⇒ 去重不发, 但结论行仍不得 OK
    ("11 live124/same-key", "systemd", 0, "fail124", "ok",
     f"{TASK}|unit_exit!=0|124", False, False),
    # 12 live 124 + 旧 key 是别的码 ⇒ 新码一律发
    ("12 live124/other-key", "systemd", 0, "fail124", "ok",
     f"{TASK}|unit_exit!=0|1", True, False),
    # 13 stats 0 + live 124 ⇒ 必须发 + 不得 OK
    ("13 stats0/live124", "systemd", 0, "fail124", "ok", None, True, False),
    # 14 stats 124 + live 124 + 同码 active ⇒ 不重发, 结论不得 OK
    ("14 stats124/live124/dedup", "systemd", 124, "fail124", "ok",
     f"{TASK}|unit_exit!=0|124", False, False),
    # 15 timer 漏跑(stats unknown 也不许抑制漏跑)
    ("15 live missed", "log", None, "fail124_missed", "unknown", None, True, False),
]


@pytest.mark.parametrize(
    "cid,src,code,live,health,old_key,expect_email,expect_ok", CASES,
    ids=[c[0] for c in CASES])
def test_hard_invariant_never_ok_when_failure_known(cid, src, code, live, health,
                                                    old_key, expect_email, expect_ok):
    row = _srow(src, code, health=health)
    alert_state = {}
    if old_key:
        alert_state[old_key] = {"status": "active", "keyword": "unit_exit",
                                "first_seen": "2026-10-24 00:00:01"}
    events, emails, state, text = _run(row, live, alert_state)

    live_state = _live(live)
    live_code = live_state.get("code")
    live_is_live_failure = (live_code not in (None, 0)
                            and live_state.get("source") != "ledger-stale")
    stats_failure = code not in (None, 0)
    if stats_failure or live_is_live_failure:
        # 硬不变式: 任一已知失败都不得打 OK
        assert "OK 所有任务" not in text, (cid, text, events)
        # 可见性: 邮件 or 结论行写明 or 告警台账留下 active 记录
        visible = (bool(emails) or "退出失败" in text or "失败" in text
                   or any(v.get("status") == "active" for v in state.values()))
        assert visible, (cid, text, events)
    assert bool(emails) is expect_email, (cid, emails, events)
    assert text.startswith("OK 所有任务") is expect_ok, (cid, text, events)


def test_ledger_stale_no_email_but_annotated_in_conclusion():
    """P3#1: ledger-stale 不据此发 SEVERE, 必须在结论行标注「新鲜度未确认」。"""
    row = _srow("ledger-stale", 1, unit_exit_ts="2026-10-20 20:58:01",
                unit_start="2026-10-20 20:35:01", last_run="2026-10-20 20:35")
    events, emails, _state, text = _run(row, "read_fail")
    assert events == [] and emails == []
    assert "账本补位码, 新鲜度未确认" in text
    assert "OK 所有任务" not in text


def test_old_ledger_filled_code_does_not_email_but_stays_visible():
    """P3#1: 重启后用账本补位的旧非 0 码, 不许发 SEVERE, 但结论行必须可见。"""
    no_record = ut.derive_unit_state(UNIT, {"LoadState": "loaded", "Result": ""})
    live = ut.merge_ledger_state(
        no_record,
        {"code": 1, "result": "exit-code", "exit": "2026-10-20 20:58:01",
         "invocation_id": "old-inv"}, NOW)
    assert live["source"] == "ledger-stale"
    row = _srow("ledger-stale", 1, unit_exit_ts="2026-10-20 20:58:01",
                unit_start="2026-10-20 20:35:01", last_run="2026-10-20 20:35")
    ns = namespace()
    events = ns["_unit_alert_events"](REGISTRY, {UNIT: live}, {TASK: row}, NOW)
    assert [e for e in events if e["kind"] == "exit"] == []
    text = ns["_build_conclusion"]([row], NOW, cfu_failed=0, alerts=0,
                                   unit_failures=[], stats_refresh_ok=True)
    assert "OK 所有任务" not in text
    assert "账本补位码" in text


def test_missed_not_suppressed_by_stats_unknown():
    """漏跑与 stats 真值可信度无关, 不许被 _row_unknown 一并抑制(#7 同族)。"""
    row = _srow("log", None, health="unknown")
    live = _live("ok0")
    live["next_elapse"] = NOW - datetime.timedelta(hours=3)  # 早于宽限 → missed
    ns = namespace()
    events = ns["_unit_alert_events"](REGISTRY, {UNIT: live}, {TASK: row}, NOW)
    missed = [e for e in events if e["kind"] == "missed"]
    assert len(missed) == 1
    assert missed[0]["key"] == f"{TASK}|unit_missed"


def test_stats_refresh_failure_blocks_ok():
    """stats 刷新失败(读旧快照)⇒ 结论不得打 OK, 必须写明原因。"""
    ns = namespace()
    text = ns["_build_conclusion"]([_srow("systemd", 0)], NOW, cfu_failed=0, alerts=0,
                                   stats_refresh_ok=False)
    assert "OK 所有任务" not in text
    assert "stats 刷新失败" in text


def test_stats_refresh_failure_log_mode_blocks_x6_ok():
    ns = namespace()
    text = ns["_build_conclusion"]([_srow("log", 0)], NOW, mode="log",
                                   systemd_available=False, stats_refresh_ok=False)
    assert not text.startswith("OK")


def test_conclusion_does_not_truncate_unknown_when_failure_present():
    """P3#2: 有失败时也必须显示「退出码未知 N 个」, 不许提前 return 吞掉。"""
    ns = namespace()
    stats = [_srow("systemd", 124)]
    stats.append(dict(_srow("systemd", None), task="other_task",
                      unit="trade-other.service", exit_source="unknown"))
    text = ns["_build_conclusion"](stats, NOW, cfu_failed=0, alerts=0)
    assert "1 个任务退出失败" in text
    assert "退出码未知 1 个(无法确认成功)" in text


def test_different_code_new_key_always_alerts():
    """方案 b: 只有同码 active 才允许去重; 任何新码一律报。"""
    row = _srow("systemd", 0)
    _ev, emails, state, text = _run(
        row, "fail124", {f"{TASK}|unit_exit!=0|1": {"status": "active"}})
    assert len(emails) == 1
    assert state[f"{TASK}|unit_exit!=0|124"]["status"] == "active"
    assert "OK 所有任务" not in text