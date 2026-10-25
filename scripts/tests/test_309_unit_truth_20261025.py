# -*- coding: utf-8 -*-
"""#309 W1 回归测试: systemd unit 真值读取与纯映射(E1, 2026-10-25)。

覆盖(全部 static-only: 不启任何 `systemctl`, 也不跑业务脚本):
  - derive_exit_code 映射表 7 项: success / exit-code / timeout / signal /
    not-found / never-ran / 重启后空 —— 逐项相等
  - **not-found 陷阱**: `systemctl show 不存在 unit` 实际返回 rc=0 + Result=success +
    ExecMainStatus=0, 必须映射为 (None, "missing"), 绝不能当成功 0(方案 §2.1 S1 / §6.1 B14)
  - never-ran / 重启后空(no-record)同样返回 None, 不猜 0
  - timer_health: 漏跑(超 10min 宽限) / 正常 / 运行中不算漏跑 / 读不到算 unknown
  - ledger 补位: no-record 用账本补, missing 不补(防拼错 unit 名被历史账本永久掩盖),
    LastTrigger 晚于 exit 标 ledger-stale
  - exit_source_mode 开关: 默认 systemd / log 一键回滚 / 非法值不静默变 log

反向对照(判别力自证, 由主控/审查复跑): 把 timeout 期望从 124 改成 0 → 本文件必红;
把 not-found 期望改成 (0, "systemd") → 本文件必红。
"""
import datetime
import json

import pytest

import unit_truth as ut


# ---------------------------------------------------------------- 7 项映射表

def _props(**kw):
    base = {"LoadState": "loaded", "Result": "success", "ExecMainCode": "1",
            "ExecMainStatus": "0", "ExecMainStartTimestamp": "Sat 2026-10-25 16:00:01 CST",
            "ExecMainExitTimestamp": "Sat 2026-10-25 16:10:01 CST",
            "InvocationID": "abc123", "ActiveState": "inactive",
            "NextElapseUSecRealtime": "2026-10-26 16:00:00",
            "LastTriggerUSec": "2026-10-25 16:00:01"}
    base.update(kw)
    return base


@pytest.mark.parametrize(
    "props,expect",
    [
        # 1 success
        (_props(), (0, "systemd")),
        # 2 exit-code → ExecMainStatus
        (_props(Result="exit-code", ExecMainStatus="1"), (1, "systemd")),
        # 3 timeout → 124(合成码, 与 coreutils timeout 同码; 写死字面量, 不许用常量自证)
        (_props(Result="timeout", ExecMainCode="2", ExecMainStatus="15"), (124, "systemd")),
        # 4 signal → 128 + signal(15 → 143, 对齐 launchd SIGTERM)
        (_props(Result="signal", ExecMainCode="2", ExecMainStatus="15"), (143, "systemd")),
        # 4b core-dump 同 signal 口径
        (_props(Result="core-dump", ExecMainCode="2", ExecMainStatus="11"), (139, "systemd")),
        # 5 not-found: 真实 systemctl 返回 rc=0 + 默认 success/0, 这里必须 None
        ({"LoadState": "not-found", "Result": "success", "ExecMainStatus": "0"},
         (None, "missing")),
        # 6 never-ran: 已加载 + 默认 success + 无 start + 无 invocation
        ({"LoadState": "loaded", "Result": "success", "ExecMainStatus": "0"},
         (None, "never-ran")),
        # 7 重启后空: Result 被清空
        ({"LoadState": "loaded", "Result": "", "ExecMainStatus": "0"}, (None, "no-record")),
    ],
)
def test_derive_exit_code_table(props, expect):
    assert ut.derive_exit_code(props) == expect


def test_not_found_is_never_zero():
    """单列一条硬断言: not-found 不允许被当成成功 0(B14 陷阱回归)。"""
    code, source = ut.derive_exit_code({"LoadState": "not-found", "Result": "success",
                                        "ExecMainStatus": "0"})
    assert code is None and code != 0
    assert source == "missing"


def test_unknown_result_is_honest_none():
    code, source = ut.derive_exit_code(_props(Result="watchdog", ExecMainCode="0",
                                              ExecMainStatus="0"))
    assert code is None and source == "unknown-result"


# ---------------------------------------------------------------- timer 漏跑

NOW = datetime.datetime(2026, 10, 25, 16, 15)


def _state(props):
    return ut.derive_unit_state("trade-x.service", props)


def test_timer_health_ok():
    assert ut.timer_health(_state(_props(NextElapseUSecRealtime="2026-10-25 16:05:00")), NOW) == "ok"


def test_timer_health_missed_after_grace():
    # 16:04 到点 + 10min 宽限 = 16:14; now=16:15 > 16:14 → missed
    assert ut.timer_health(_state(_props(NextElapseUSecRealtime="2026-10-25 16:04:00")), NOW) == "missed"


def test_timer_health_exact_boundary_not_missed():
    # 16:05 + 10min = 16:15; 「>」不含等号 → 边界不算漏跑
    assert ut.timer_health(_state(_props(NextElapseUSecRealtime="2026-10-25 16:05:00")), NOW) == "ok"


@pytest.mark.parametrize("active", ["active", "activating", "reloading"])
def test_timer_health_running_not_missed(active):
    st = _state(_props(ActiveState=active, NextElapseUSecRealtime="2026-10-20 16:00:00"))
    assert ut.timer_health(st, NOW) == "running"


def test_timer_health_unknown_without_next_or_missing():
    assert ut.timer_health(_state(_props(NextElapseUSecRealtime="")), NOW) == "unknown"
    assert ut.timer_health(_state({"LoadState": "not-found"}), NOW) == "unknown"


# ---------------------------------------------------------------- ledger 补位

def test_merge_ledger_fills_no_record():
    st = _state({"LoadState": "loaded", "Result": "", "ExecMainStatus": "0"})
    entry = {"result": "exit-code", "code": 124, "invocation_id": "old",
             "start": "2026-10-23 20:35:01", "exit": "2026-10-23 20:58:01",
             "consecutive": 2, "first_bad_at": "2026-10-22 20:58:01"}
    merged = ut.merge_ledger_state(st, entry)
    assert merged["code"] == 124 and merged["source"] == "ledger"
    assert merged["ledger_consecutive"] == 2


def test_merge_ledger_does_not_fill_missing():
    """unit 真不存在(拼错名)不许被账本永久掩盖成上次成功。"""
    st = _state({"LoadState": "not-found"})
    merged = ut.merge_ledger_state(st, {"code": 0, "result": "success"})
    assert merged["code"] is None and merged["source"] == "missing"


def test_merge_ledger_stale_flag():
    st = _state({"LoadState": "loaded", "Result": "",
                 "LastTriggerUSec": "2026-10-25 15:00:00"})
    entry = {"code": 1, "result": "exit-code", "exit": "2026-10-23 20:58:01"}
    merged = ut.merge_ledger_state(st, entry)
    assert merged["source"] == "ledger-stale" and merged["code"] == 1


def test_merge_ledger_does_not_override_live_truth():
    st = _state(_props(Result="exit-code", ExecMainStatus="1"))
    assert ut.merge_ledger_state(st, {"code": 0})["code"] == 1


# ---------------------------------------------------------------- 账本持久化(W5)

def test_ledger_load_missing_or_corrupt_is_empty(tmp_path):
    assert ut.load_ledger(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert ut.load_ledger(bad) == {}
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    assert ut.load_ledger(bad) == {}


def test_ledger_save_roundtrip_atomic(tmp_path):
    """原子写: 落盘是完整 JSON(version + units), 读回逐值一致, 无残留 tmp 文件。"""
    p = tmp_path / "ledger.json"
    rec = {"a.service": {"unit": "a.service", "code": 1, "result": "exit-code",
                         "consecutive": 2, "start": None, "exit": None}}
    ut.save_ledger_atomic(p, rec, now=NOW)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["version"] == ut.LEDGER_VERSION and raw["updated_at"] == "2026-10-25 16:15:00"
    assert ut.load_ledger(p) == rec
    assert not [n for n in p.parent.iterdir() if ".tmp" in n.name]


def test_update_ledger_consecutive_and_first_bad():
    """连续失败累加 consecutive, first_bad_at 只记第一次; 成功清零。"""
    st = ut.derive_unit_state("a.service", _props(Result="exit-code", ExecMainStatus="1"))
    l1 = ut.update_ledger_records({"a.service": st}, {}, NOW)
    assert l1["a.service"]["consecutive"] == 1
    assert l1["a.service"]["first_bad_at"] == "2026-10-25 16:15:00"
    l2 = ut.update_ledger_records({"a.service": st}, l1, NOW + datetime.timedelta(minutes=5))
    assert l2["a.service"]["consecutive"] == 2
    assert l2["a.service"]["first_bad_at"] == "2026-10-25 16:15:00"
    ok = ut.derive_unit_state("a.service", _props())
    l3 = ut.update_ledger_records({"a.service": ok}, l2, NOW)
    assert l3["a.service"]["consecutive"] == 0 and l3["a.service"]["first_bad_at"] is None


def test_update_ledger_ignores_unknown_and_keeps_old_units():
    """code=None(未知)不许覆盖已知记录; 本轮没观测到的旧 unit 保留(只增不删)。"""
    prev = {"old.service": {"unit": "old.service", "code": 0, "consecutive": 0},
            "a.service": {"unit": "a.service", "code": 2, "consecutive": 1}}
    unknown = ut.derive_unit_state("a.service", {"LoadState": "loaded", "Result": ""})
    out = ut.update_ledger_records({"a.service": unknown}, prev, NOW)
    assert out["a.service"]["code"] == 2  # 未知不覆盖
    assert out["old.service"] == prev["old.service"]  # 未观测保留


# ---------------------------------------------------------------- 读取注入 / 开关

def test_read_unit_states_uses_injected_runner_only():
    calls = []

    def runner(unit):
        calls.append(unit)
        return {"LoadState": "loaded", "Result": "success"}

    out = ut.read_unit_states(["a.service", "b.service"], runner=runner)
    assert calls == ["a.service", "b.service"]
    assert out["a.service"]["Result"] == "success"


def test_read_unit_states_runner_exception_becomes_empty():
    def runner(_unit):
        raise RuntimeError("boom")

    assert ut.read_unit_states(["a.service"], runner=runner) == {"a.service": {}}


@pytest.mark.parametrize("raw,expect", [(None, "systemd"), ("systemd", "systemd"),
                                        ("log", "log"), ("LOG", "log"),
                                        ("garbage", "systemd"), ("", "systemd")])
def test_exit_source_mode(monkeypatch, raw, expect):
    if raw is None:
        monkeypatch.delenv("MONITOR_EXIT_SOURCE", raising=False)
    else:
        monkeypatch.setenv("MONITOR_EXIT_SOURCE", raw)
    assert ut.exit_source_mode() == expect