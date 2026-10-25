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
from pathlib import Path

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

def test_read_unit_states_reads_service_and_same_name_timer():
    """P1-1: service 读 8 属性 + 同名 timer 读 NextElapse/LastTrigger, 一次合并。"""
    calls = []
    payload = {
        "a.service": {
            "LoadState": "loaded", "Result": "exit-code", "ExecMainCode": "1",
            "ExecMainStatus": "1", "ExecMainStartTimestamp": "2026-10-25 16:00:01",
            "ExecMainExitTimestamp": "2026-10-25 16:10:01",
            "InvocationID": "inv-a", "ActiveState": "inactive",
        },
        "a.timer": {
            "LoadState": "loaded", "ActiveState": "active",
            "NextElapseUSecRealtime": "2026-10-26 16:00:00",
            "LastTriggerUSec": "2026-10-25 16:00:01",
            "Result": "success", "ExecMainStatus": "0",
        },
    }

    def runner(unit):
        calls.append(unit)
        return payload.get(unit, {})

    out = ut.read_unit_states(["a.service"], runner=runner)
    # 每个任务读两个 unit: 自己的 service + 同名 timer
    assert calls == ["a.service", "a.timer"]
    merged = out["a.service"]
    # service 侧属性(退出码以 service 为准)
    assert ut.derive_exit_code(merged) == (1, "systemd")
    assert merged["ActiveState"] == "inactive"
    # timer 侧属性来自 timer
    assert merged["NextElapseUSecRealtime"] == "2026-10-26 16:00:00"
    assert merged["LastTriggerUSec"] == "2026-10-25 16:00:01"


def test_timer_result_never_leaks_into_service_truth():
    """P1-1 核心防回归: timer 的 Result=success/ExecMainStatus=0 绝不许洗白失败的 service。"""

    def runner(unit):
        if unit.endswith(".timer"):
            return {"LoadState": "loaded", "ActiveState": "active",
                    "Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0"}
        return {"LoadState": "loaded", "Result": "exit-code", "ExecMainCode": "1",
                "ExecMainStatus": "7", "ExecMainStartTimestamp": "2026-10-25 16:00:01",
                "ExecMainExitTimestamp": "2026-10-25 16:01:01", "InvocationID": "x",
                "ActiveState": "inactive"}

    merged = ut.read_unit_states(["a.service"], runner=runner)["a.service"]
    assert merged["Result"] == "exit-code"
    assert merged["ExecMainStatus"] == "7"
    assert ut.derive_exit_code(merged) == (7, "systemd")


def test_service_props_cannot_smuggle_timer_attrs():
    """P1-1 形状白名单: 即使假 systemctl 把 timer 属性塞进 service 块, 也只认 timer 块的值。"""

    def runner(unit):
        if unit.endswith(".timer"):
            return {"LoadState": "loaded", "NextElapseUSecRealtime": "2026-10-26 09:00:00",
                    "LastTriggerUSec": "2026-10-25 09:00:00"}
        return {"LoadState": "loaded", "Result": "success",
                "NextElapseUSecRealtime": "1999-01-01 00:00:00",
                "LastTriggerUSec": "1999-01-01 00:00:00"}

    merged = ut.read_unit_states(["a.service"], runner=runner)["a.service"]
    assert merged["NextElapseUSecRealtime"] == "2026-10-26 09:00:00"
    assert merged["LastTriggerUSec"] == "2026-10-25 09:00:00"


def _parse_multi(raw):
    return ut._parse_multi(raw)


def test_parse_multi_real_systemctl_shape():
    """真实形状(2026-10-25 云上实测): 块间空行分隔, Id 可能排在中部, timer 块也带 Result。"""
    raw = (
        "Result=success\n"
        "ExecMainStatus=0\n"
        "Id=trade-gold-night.service\n"
        "LoadState=loaded\n"
        "\n"
        "NextElapseUSecRealtime=Mon 2026-10-26 02:40:00 CST\n"
        "LastTriggerUSec=Sun 2026-10-25 02:40:01 CST\n"
        "Result=success\n"
        "Id=trade-gold-night.timer\n"
        "LoadState=loaded\n"
    )
    parsed = _parse_multi(raw)
    assert set(parsed) == {"trade-gold-night.service", "trade-gold-night.timer"}
    assert parsed["trade-gold-night.service"]["Result"] == "success"
    assert "NextElapseUSecRealtime" not in parsed["trade-gold-night.service"]
    assert parsed["trade-gold-night.timer"]["NextElapseUSecRealtime"].startswith("Mon 2026-10-26")


# 真实 systemd 属性白名单(2026-10-25 云上 `systemctl show` 实测, 硬编码不引用
# unit_truth.SERVICE_PROPS: 生产常量若被误改成含 timer 属性, 本守卫必须仍然红)
REAL_SERVICE_KEYS = {"LoadState", "Result", "ExecMainCode", "ExecMainStatus",
                     "ExecMainStartTimestamp", "ExecMainExitTimestamp",
                     "InvocationID", "ActiveState"}
REAL_TIMER_KEYS = {"LoadState", "ActiveState", "NextElapseUSecRealtime",
                   "LastTriggerUSec"}
FIXTURES_309 = sorted((Path(__file__).absolute().parent / "fixtures" / "309")
                      .glob("x*_units.json"))


@pytest.mark.parametrize("path", FIXTURES_309, ids=lambda p: p.name)
def test_fixture_service_timer_shape_matches_real_systemd(path):
    """防假样本养绿(L49): fixture 的 `.service` 键不得含 timer 专属属性, 反之亦然。

    若 `.service` 上出现 `NextElapseUSecRealtime`/`LastTriggerUSec`(现实中不存在),
    读取层会「碰巧」从 service 块拿到值, 真机却拿不到 ⇒ 用例全绿但生产漏跑全盲。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    svc = sorted(k for k in data if k.endswith(".service"))
    tmr = sorted(k for k in data if k.endswith(".timer"))
    assert len(svc) == len(tmr) == 43, f"{path.name}: service/timer 不是 43+43"
    assert {k[:-len(".service")] for k in svc} == {k[:-len(".timer")] for k in tmr}, \
        f"{path.name}: 存在没有同名 timer 的 service(漏跑检测会瞎)"
    for k in svc:
        extra = set(data[k]) - REAL_SERVICE_KEYS
        assert not extra, (
            f"{path.name}:{k} 含真实 .service 不存在的属性 {sorted(extra)}"
            " —— 假样本会把读取层 bug 养绿(L49)"
        )
    for k in tmr:
        extra = set(data[k]) - REAL_TIMER_KEYS
        assert not extra, f"{path.name}:{k} 含真实 .timer 不存在的属性 {sorted(extra)}"
    assert "NextElapseUSecRealtime" not in data[svc[0]]
    assert "Result" not in data[tmr[0]], "真实 .timer 的 Result 恒 success, 不许作为任务结果"


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