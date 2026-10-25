# -*- coding: utf-8 -*-
"""#309 P2-7: unit-only 行运行态 guard + 诊断源保留(E7, 2026-10-25)。

问题(独立审 P2-7): 任务正在跑时 systemd 的 Result 还是上一轮/默认 success,
ExecMainExitTimestamp 为空或仍是旧值。旧实现照常采信 → 「exit=0 + 旧 start」,
严重时 duration 为负(`exit < start`), 结论层可能把运行中任务当已完成/失败。

本文件锁三件事:
  1. active/activating/reloading(ut.RUNNING_STATES) → last_exit=None、
     exit_source=running、duration=None, unit_* 字段不外泄、不算漏跑。
  2. 终态不可确认(never-ran / no-record / missing / unknown-result)保留诊断标签,
     不抹成笼统 unknown(结论层靠该标签阻断 OK)。
  3. 已完成行照常出 exit/duration(guard 不能一刀切把正常行也变成 running)。

static-only: 直接喂 `_build_unit_only_row` 纯函数 dict, 不启 systemctl。
"""
import datetime

import pytest

import gen_schedule_stats as gss
import unit_truth as ut

NOW = datetime.datetime(2026, 10, 20, 18, 45, 0)
ROW = {"task": "gold_night", "name": "黄金夜盘", "unit": "trade-gold-night.service"}


def _state(**kw):
    """derive_unit_state 的真实输出形状(字段名与 unit_truth 一致)。"""
    st = {
        "unit": ROW["unit"], "load_state": "loaded", "active_state": "inactive",
        "result": "success", "code": 0, "source": "systemd",
        "start": NOW - datetime.timedelta(minutes=5),
        "exit": NOW - datetime.timedelta(minutes=4),
        "last_trigger": NOW - datetime.timedelta(minutes=5),
        "next_elapse": NOW + datetime.timedelta(hours=1),
    }
    st.update(kw)
    return st


@pytest.mark.parametrize("active", list(ut.RUNNING_STATES))
def test_running_unit_only_row_has_no_exit_and_no_duration(active):
    # 旧实现的陷阱输入: start 比 exit 晚 ⇒ 无 guard 时 duration 为负
    st = _state(
        active_state=active,
        start=NOW - datetime.timedelta(minutes=1),
        exit=NOW - datetime.timedelta(minutes=30),
        last_trigger=NOW - datetime.timedelta(minutes=1),
        next_elapse=NOW - datetime.timedelta(hours=1),  # 即使过期也不许判漏跑
    )
    r = gss._build_unit_only_row(ROW, NOW, st, "systemd")
    assert r["exit_source"] == "running"
    assert r["last_exit"] is None
    assert r["last_duration_sec"] is None
    assert r["last_run"] == (NOW - datetime.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    # 运行中不外泄 unit 真值(否则前端/结论层会把旧码当本轮结果)
    assert r["unit_exit"] is None and r["unit_result"] is None
    assert r["unit_start"] is None and r["unit_exit_ts"] is None
    assert r["unit_missed"] is False and r["unit_timer_health"] == "unknown"


def test_running_row_recovers_after_finish():
    """反向对照: 同一 unit 结束后(active→inactive, exit 晚于 start)必须照常出 exit。"""
    st = _state(active_state="inactive",
                start=NOW - datetime.timedelta(minutes=2),
                exit=NOW - datetime.timedelta(minutes=1),
                next_elapse=NOW + datetime.timedelta(hours=1))
    r = gss._build_unit_only_row(ROW, NOW, st, "systemd")
    assert r["exit_source"] == "systemd"
    assert r["last_exit"] == 0
    assert r["last_duration_sec"] == 60


@pytest.mark.parametrize("src", ["never-ran", "no-record", "missing", "unknown-result"])
def test_diagnostic_sources_survive_for_ok_blocking(src):
    st = _state(active_state="inactive", result="", code=None, source=src,
                start=None, exit=None, last_trigger=None)
    r = gss._build_unit_only_row(ROW, NOW, st, "systemd")
    assert r["exit_source"] == src, "诊断标签被抹成 unknown, 结论层无法区分故障类型"
    assert r["last_exit"] is None and r["last_duration_sec"] is None


def test_log_mode_untouched_by_running_guard():
    """一行回滚: log 口径不读 systemd, 运行态也不得产出 running(保持旧 unknown)。"""
    st = _state(active_state="active")
    r = gss._build_unit_only_row(ROW, NOW, st, "log")
    assert r["exit_source"] == "unknown"
    assert r["last_exit"] is None and r["last_duration_sec"] is None