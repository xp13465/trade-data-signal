# -*- coding: utf-8 -*-
"""#309 误报/漏报双向测试: 全绿轮次不得告警, 注入失败必须 SEVERE(E6, 2026-10-25)。

覆盖:
  - 过去 7 天全绿轮次(43 unit 全部 Result=success / exit=0) → 新通道①②都不得产事件,
    结论必须是 OK 且带 覆盖 43/43(防空转恒红 / 防「一改就全红」)
  - 注入一条 unit exit=1(stats 仍 0/未知) → 必然出现 `SEVERE: ... systemd 退出失败`,
    key = `{task}|unit_exit!=0|{code}`(证明不是永远 OK)
  - 去重: stats.last_exit 已是同一 code → 只出 dedup 事件, 不再 SEVERE(防重复告警)
  - timer 漏跑(超 10min 宽限) → `SEVERE: ... timer 漏跑`
  - 运行中(active/activating)即使 next_elapse 过期也不算漏跑

取用生产逻辑: `_unit_alert_events` 从 schedule_monitor.sh AST 提取(不复制)。
全程 static-only: 只喂 dict, 不启 systemctl、不跑业务脚本、不调用 notify。
"""
import datetime

import pytest

import unit_truth as ut
from _monitor_conclusion_309 import conclusion, unit_alert_events

DAY0 = datetime.date(2026, 10, 18)
BASE_START = "12:00:00"
BASE_EXIT = "12:05:00"


def _props(day: datetime.date, **kw):
    p = {
        "LoadState": "loaded", "Result": "success", "ExecMainCode": "1",
        "ExecMainStatus": "0",
        "ExecMainStartTimestamp": f"{day.isoformat()} {BASE_START}",
        "ExecMainExitTimestamp": f"{day.isoformat()} {BASE_EXIT}",
        "InvocationID": f"inv-{day.isoformat()}",
        "ActiveState": "inactive",
        "NextElapseUSecRealtime": f"{(day + datetime.timedelta(days=1)).isoformat()} 12:00:00",
        "LastTriggerUSec": f"{day.isoformat()} {BASE_START}",
    }
    p.update(kw)
    return p


def _states(day, overrides=None):
    """43 unit 的 derive_unit_state 结果(全绿, 可覆盖)。"""
    import gen_schedule_stats as gss

    overrides = overrides or {}
    return {
        r["unit"]: ut.derive_unit_state(r["unit"], _props(day, **overrides.get(r["unit"], {})))
        for r in gss.UNIT_REGISTRY
    }


def _stats_all_zero(day):
    """40 行统计: 全 0, 与全绿 unit 状态一致。"""
    import gen_schedule_stats as gss

    rows = []
    for r in gss.UNIT_REGISTRY:
        if not r.get("include"):
            continue
        rows.append({
            "task": r["task"], "unit": r["unit"], "last_exit": 0,
            "unit_exit": 0, "unit_result": "success", "exit_source": "systemd",
            "unit_missed": False, "next_elapse": _props(day)["NextElapseUSecRealtime"],
        })
    return rows


def _events(day, now, overrides=None):
    """跑生产判定: 返回事件列表 + stats 对照。"""
    states = _states(day, overrides)
    stats = _stats_all_zero(day)
    import gen_schedule_stats as gss

    return unit_alert_events()(gss.UNIT_REGISTRY, states,
                               {s["task"]: s for s in stats}, now), stats


@pytest.fixture(scope="module")
def NOW_BY_DAY():
    return {DAY0 + datetime.timedelta(days=i):
            datetime.datetime.combine(DAY0 + datetime.timedelta(days=i),
                                      datetime.time(21, 0))
            for i in range(7)}


@pytest.mark.parametrize("offset", range(7))
def test_seven_green_days_produce_no_events_and_ok(offset, NOW_BY_DAY):
    day = DAY0 + datetime.timedelta(days=offset)
    events, stats = _events(day, NOW_BY_DAY[day])
    assert events == [], f"{day} 全绿却产生事件: {events}"
    text = conclusion()(stats, NOW_BY_DAY[day], cfu_failed=0, alerts=0)
    assert text.startswith("OK 所有任务按计划执行")
    assert "覆盖 43/43(40 业务+基础, 3 自监控)" in text


def test_injected_unit_failure_emits_severe(NOW_BY_DAY):
    day = DAY0 + datetime.timedelta(days=3)
    events, stats = _events(day, NOW_BY_DAY[day], {"trade-lhb-backfill.service": {
        "Result": "exit-code", "ExecMainStatus": "1"}})
    asserts = [e for e in events if e["kind"] == "exit"]
    assert len(asserts) == 1
    e = asserts[0]
    assert e["msg"].startswith("SEVERE: lhb_backfill systemd 退出失败")
    assert e["key"] == "lhb_backfill|unit_exit!=0|1"
    assert e["keyword"] == "unit_exit=1"
    # 结论行不得再说 OK
    text = conclusion()(stats, NOW_BY_DAY[day], cfu_failed=0, alerts=len(asserts))
    assert "OK 所有任务" not in text


def test_unit_channel_is_single_hop_across_stats_refresh(NOW_BY_DAY):
    """P2-3: stats 刷新失败→恢复两轮, 同一故障只允许一个告警 key(一跳)。"""
    day = DAY0 + datetime.timedelta(days=2)
    states = _states(day, {"trade-lhb-backfill.service": {
        "Result": "exit-code", "ExecMainStatus": "1"}})
    import gen_schedule_stats as gss
    from _monitor_conclusion_309 import namespace

    owns = namespace()["_unit_channel_owns_row"]

    # 第 1 轮: stats 仍是旧的 0(刷新失败), unit 真值 1 → unit 通道报
    stats_round1 = _stats_all_zero(day)
    ev1 = unit_alert_events()(gss.UNIT_REGISTRY, states,
                              {s["task"]: s for s in stats_round1}, NOW_BY_DAY[day])
    assert [e["kind"] for e in ev1] == ["exit"]
    assert ev1[0]["key"] == "lhb_backfill|unit_exit!=0|1"

    # 第 2 轮: stats 已合并同一 code, exit 通道必须让位(否则第二次告警)
    stats_round2 = _stats_all_zero(day)
    for s in stats_round2:
        if s["task"] == "lhb_backfill":
            s.update({"last_exit": 1, "unit_exit": 1, "exit_source": "systemd"})
    ev2 = unit_alert_events()(gss.UNIT_REGISTRY, states,
                              {s["task"]: s for s in stats_round2}, NOW_BY_DAY[day])
    row2 = next(s for s in stats_round2 if s["task"] == "lhb_backfill")
    assert owns(row2, True) is True
    assert [e["key"] for e in ev2] == ["lhb_backfill|unit_exit!=0|1"]

    # 反向对照: 日志口径(非 systemd 真值)行不由 unit 通道负责, exit 通道照常报
    row_log = dict(row2, exit_source="log-deploy", unit_exit=0, last_exit=1)
    assert owns(row_log, True) is False
    assert owns(row2, False) is False


def test_untrusted_stats_row_does_not_hide_live_failure(NOW_BY_DAY):
    """P1b 反向对照: stats 行判「不可信」≠ monitor live 码是假的, 不许拿它一起置 None。

    旧行为(`_row_unknown`)把 live 真实非 0 码也压成 None ⇒ 双盲假 OK(#4/#7)。
    新行为: live 非 0 一律出事件; 同码重复靠 alert_state 的 key 去重(不在本纯函数内)。
    """
    day = DAY0 + datetime.timedelta(days=6)
    states = _states(day, {"trade-lhb-backfill.service": {
        "Result": "exit-code", "ExecMainStatus": "1",
        "NextElapseUSecRealtime": f"{day.isoformat()} 09:25:00"}})
    stats = _stats_all_zero(day)
    for s in stats:
        if s["task"] == "lhb_backfill":
            s.update({"unit_exit": None, "unit_start": None,
                      "unit_timer_health": "unknown", "unit_missed": False})
    import gen_schedule_stats as gss

    events = unit_alert_events()(gss.UNIT_REGISTRY, states,
                                 {s["task"]: s for s in stats}, NOW_BY_DAY[day])
    exits = [e for e in events if e["task"] == "lhb_backfill" and e["kind"] == "exit"]
    assert len(exits) == 1, events
    assert exits[0]["key"] == "lhb_backfill|unit_exit!=0|1"
    assert exits[0]["source"] == "systemd"


def test_missed_timer_emits_severe(NOW_BY_DAY):
    day = DAY0 + datetime.timedelta(days=4)
    events, stats = _events(day, NOW_BY_DAY[day], {"trade-gold-night.service": {
        "NextElapseUSecRealtime": f"{day.isoformat()} 09:25:00"}})
    missed = [e for e in events if e["kind"] == "missed"]
    assert len(missed) == 1
    assert missed[0]["msg"].startswith("SEVERE: gold_night timer 漏跑")
    assert missed[0]["key"] == "gold_night|unit_missed"
    text = conclusion()(stats, NOW_BY_DAY[day], cfu_failed=0, alerts=len(missed))
    assert "OK 所有任务" not in text and "漏跑 0" not in text


@pytest.mark.parametrize("active", ["active", "activating", "reloading"])
def test_running_timer_is_not_missed(active, NOW_BY_DAY):
    day = DAY0 + datetime.timedelta(days=5)
    events, _stats = _events(day, NOW_BY_DAY[day], {"trade-gold-night.service": {
        "ActiveState": active,
        "ExecMainStartTimestamp": "",
        "ExecMainExitTimestamp": "",
        "InvocationID": "",
        "NextElapseUSecRealtime": f"{day.isoformat()} 09:25:00"}})
    assert [e for e in events if e["kind"] == "missed"] == []