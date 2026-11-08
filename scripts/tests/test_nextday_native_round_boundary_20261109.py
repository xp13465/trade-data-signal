"""R1外层未闭合与真实native重启边界：实际parser、row、真实main日志，零外发。"""
from datetime import datetime
import json
from pathlib import Path
import socket
import subprocess

import pytest
import gen_schedule_stats as gss
from test_nextday_fallback_mode_boundaries_20261109 import produce

SERVICE = "trade-nextday-gap-check.service"
RAW = json.loads((Path(__file__).parent / "fixtures/nextday_fallback/r1-nested-close-then-new-start.json").read_text())["log"]


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    def deny(*a, **kw):
        pytest.fail("轮次测试禁止网络/子进程")
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def state(start_value, end_value, **changes):
    props = {"LoadState": "loaded", "Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0",
             "ExecMainStartTimestamp": start_value, "ExecMainExitTimestamp": end_value,
             "InvocationID": "native-" + start_value, "ActiveState": "inactive"}
    native = gss.ut.derive_unit_state(SERVICE, props)
    native.update(changes)
    return native


def scan(tmp_path, text, **kw):
    p = tmp_path / "nextday.log"
    p.write_text(text)
    return gss.scan_log_anomaly(p, "nextday_gap_check.sh", "standard", last_exit=0, **kw)[0]


def row(tmp_path, text, native=None, mode="log"):
    task = next(t for t in gss.TASKS if t["task"] == "nextday_gap_check")
    reg = next(t for t in gss.UNIT_REGISTRY if t["task"] == "nextday_gap_check")
    (tmp_path / task["log"]).write_text(text)
    return gss._build_log_task_row(reg, task, tmp_path, datetime(2026, 11, 5, 12), native, mode)


def crash(day="2026-11-02", time="09:25:00"):
    return f"=== nextday_gap_check.sh 开始 {day} {time} ===\nFATAL outer persistence failed\n"


def test_r1_raw_nested_closed_then_start_retains_outer_fatal(tmp_path):
    got = scan(tmp_path, RAW)
    assert got and got["keyword"] == "FATAL"


def test_r1_real_row_retains_outer_fatal(tmp_path):
    actual = row(tmp_path, RAW)
    assert actual["log_anomaly"] is True and actual["log_anomaly_keyword"] == "FATAL"


def test_r1_clean_inner_without_primary_still_retains_outer_fatal(tmp_path):
    text = "\n".join(l for l in RAW.splitlines() if "主源 fund_etf_spot_em" not in l) + "\n"
    assert scan(tmp_path, text)["keyword"] == "FATAL"


@pytest.mark.parametrize("native", [None, state("2026-11-02 09:24:59", "2026-11-02 09:26:07")], ids=["unknown", "same-native-round"])
def test_inner_end_never_clears_current_outer_fatal(tmp_path, native):
    kw = {"nextday_native": native} if native else {}
    assert scan(tmp_path, RAW, **kw)["keyword"] == "FATAL"


@pytest.mark.parametrize("old_day,old_time,new_day", [("2026-11-02", "09:25:00", "20261102"), ("2026-11-01", "09:26:00", "20261102"), ("2026-10-15", "09:26:00", "20261103")], ids=["same-day-retry", "next-day", "many-days"])
def test_real_native_restart_can_recover_old_unfinished_crash(tmp_path, monkeypatch, old_day, old_time, new_day):
    healthy, rc = produce(tmp_path, monkeypatch, day=new_day)
    assert rc == 0
    text = crash(old_day, old_time) + healthy
    d = datetime.strptime(new_day, "%Y%m%d").strftime("%Y-%m-%d")
    native = state(d + " 09:25:59", d + " 09:26:07")
    assert scan(tmp_path, text, nextday_native=native) is None
    actual = row(tmp_path, text, native, "systemd")
    assert actual["last_exit"] == 0 and actual["log_anomaly"] is False
    assert scan(tmp_path, text) is not None  # 无native，不能猜测旧轮次已经终止。


def test_native_current_outer_cannot_be_replaced_by_later_inner(tmp_path):
    native = state("2026-11-02 09:24:59", "2026-11-02 09:26:07")
    actual = row(tmp_path, RAW, native, "systemd")
    assert actual["log_anomaly_keyword"] == "FATAL"


@pytest.mark.parametrize("change", [{"source": "ledger"}, {"source": "ledger-stale"}, {"source": "missing"}, {"invocation_id": None}, {"unit": "trade-other.service"}, {"load_state": "not-found"}, {"exit": None}, {"start": None}, {"start": datetime(2026, 11, 2, 9, 26, 7)}, {"active_state": "active"}, {"code": None}, {"result": "timeout"}, {"exec_code": 0}, {"exec_status": 2}])
def test_unverified_native_cannot_discard_old_error(tmp_path, monkeypatch, change):
    healthy, rc = produce(tmp_path, monkeypatch)
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07", **change)
    assert scan(tmp_path, crash() + healthy, nextday_native=native) is not None


def test_same_second_native_has_multiple_candidates_is_ambiguous(tmp_path, monkeypatch):
    healthy, rc = produce(tmp_path, monkeypatch)
    native = state("2026-11-02 09:26:00", "2026-11-02 09:26:07")
    assert scan(tmp_path, crash(time="09:26:00") + healthy, nextday_native=native)["keyword"] == "FATAL"


def test_closed_ambiguous_outer_needs_native_to_prove_next_run(tmp_path, monkeypatch):
    healthy, rc = produce(tmp_path, monkeypatch)
    prefix = RAW[:RAW.index("=== nextday_gap_check.sh 开始 2026-11-02 09:26:00 ===")]
    text = prefix + "=== nextday_gap_check.sh 结束 2026-11-02 09:25:30 退出码=1 ===\n" + healthy
    # 同名嵌套后无法认证每条END归属；native可证明C确是新进程，不能只数END猜测。
    assert scan(tmp_path, text) is not None
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    assert row(tmp_path, text, native, "systemd")["log_anomaly"] is False


def test_normal_closed_previous_failure_can_recover_without_native(tmp_path, monkeypatch):
    healthy, rc = produce(tmp_path, monkeypatch)
    text = crash() + "=== nextday_gap_check.sh 结束 2026-11-02 09:25:30 退出码=1 ===\n" + healthy
    assert scan(tmp_path, text) is None


@pytest.mark.parametrize("end_time", ["09:25:20", "09:25:30"])
def test_extra_inner_end_cannot_erase_nested_ambiguity(tmp_path, monkeypatch, end_time):
    healthy, rc = produce(tmp_path, monkeypatch)
    prefix = RAW[:RAW.index("=== nextday_gap_check.sh 开始 2026-11-02 09:26:00 ===")]
    text = prefix + f"=== nextday_gap_check.sh 结束 2026-11-02 {end_time} 退出码=0 ===\n" + healthy
    assert scan(tmp_path, text)["keyword"] == "FATAL"
    current_outer = state("2026-11-02 09:24:59", "2026-11-02 09:26:07")
    assert row(tmp_path, text, current_outer, "systemd")["log_anomaly_keyword"] == "FATAL"


@pytest.mark.parametrize("extra", ["FATAL late failure", "ConnectionError: real persistence failure", "Traceback (most recent call last):"])
def test_error_after_inner_end_remains_in_open_outer_window(tmp_path, extra):
    marker = "=== nextday_gap_check.sh 结束 2026-11-02 09:25:20 退出码=0 ==="
    # 移去原外层FATAL，真错误位于内层END之后，不能再只扫描首个END以前。
    text = RAW.replace("FATAL outer persistence failed\n", "").replace(marker, marker + "\n" + extra)
    assert scan(tmp_path, text) is not None


@pytest.mark.parametrize("mutation", ["missing-end", "dry-run", "partial", "unrelated-error"])
def test_native_restart_still_requires_current_run_health(tmp_path, monkeypatch, mutation):
    flags = ["--dry-run"] if mutation == "dry-run" else []
    targets = {"513260": 0.9, "510300": 1.0} if mutation == "partial" else None
    healthy, rc = produce(tmp_path, monkeypatch, args=flags, targets=targets)
    if mutation == "missing-end":
        healthy = healthy.rsplit("=== nextday_gap_check.sh 结束 ", 1)[0]
    elif mutation == "unrelated-error":
        healthy = healthy.replace("=== nextday_gap_check.sh 结束 ", "FATAL new round failure\n=== nextday_gap_check.sh 结束 ")
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    assert scan(tmp_path, crash() + healthy, nextday_native=native) is not None


def test_log_mode_does_not_use_native_to_clear_history(tmp_path, monkeypatch):
    healthy, rc = produce(tmp_path, monkeypatch)
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    assert row(tmp_path, crash() + healthy, native, "log")["log_anomaly"] is True


@pytest.mark.parametrize("case", ["native-too-old", "native-future", "native-no-current-start", "later-start-after-native-end"])
def test_native_cannot_hide_history_when_round_mapping_is_unknown(tmp_path, monkeypatch, case):
    healthy, rc = produce(tmp_path, monkeypatch)
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    if case == "native-too-old":
        native = state("2026-11-02 09:24:59", "2026-11-02 09:25:30")
    elif case == "native-future":
        native = state("2026-11-06 09:25:59", "2026-11-06 09:26:07")
    elif case == "native-no-current-start":
        healthy = healthy.split("\n", 1)[1]
    elif case == "later-start-after-native-end":
        healthy += "=== nextday_gap_check.sh 开始 2026-11-02 09:27:00 ===\nFATAL newer run failed\n"
    assert row(tmp_path, crash() + healthy, native, "systemd")["log_anomaly"] is True


def test_native_never_hides_error_in_the_new_round(tmp_path, monkeypatch):
    healthy, rc = produce(tmp_path, monkeypatch)
    healthy = healthy.replace("[nextday_gap_check] 执行模式=live", "FATAL new invocation failed\n[nextday_gap_check] 执行模式=live")
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    actual = row(tmp_path, crash() + healthy, native, "systemd")
    assert actual["log_anomaly"] is True and actual["log_anomaly_keyword"] == "FATAL"
    assert actual["log_anomaly_line"] == "FATAL new invocation failed"


def test_real_build_passes_existing_systemd_round_to_nextday_only(tmp_path, monkeypatch):
    healthy, rc = produce(tmp_path, monkeypatch)
    (tmp_path / "nextday_gap_check_launchd.log").write_text(crash() + healthy)
    monkeypatch.setattr(gss.ut, "exit_source_mode", lambda: "systemd")
    monkeypatch.setattr(gss, "_systemd_last_exit", lambda label: None)
    monkeypatch.setattr(gss, "_unit_active_state", lambda label: None)
    def reader(unit):
        if unit == SERVICE:
            return {"LoadState": "loaded", "Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0", "InvocationID": "real-shape-native-new", "ExecMainStartTimestamp": "2026-11-02 09:25:59", "ExecMainExitTimestamp": "2026-11-02 09:26:07", "ActiveState": "inactive"}
        return {"LoadState": "not-found"}
    rows = gss.build(log_dir=tmp_path, out=tmp_path / "stats.json", now=datetime(2026, 11, 2, 9, 30), unit_reader=reader, ledger_path=tmp_path / "ledger.json")
    actual = next(r for r in rows if r["task"] == "nextday_gap_check")
    assert actual["log_anomaly"] is False and actual["last_exit"] == 0
    assert actual["exit_source"] == "systemd" and actual["unit_start"] == "2026-11-02 09:25:59"


def test_other_task_ignores_optional_nextday_native_boundary(tmp_path):
    p = tmp_path / "upload.log"
    p.write_text(RAW.replace("nextday_gap_check.sh", "upload.sh"))
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    old = gss.scan_log_anomaly(p, "upload.sh", "standard", last_exit=0)
    assert gss.scan_log_anomaly(p, "upload.sh", "standard", last_exit=0, nextday_native=native) == old


@pytest.mark.parametrize("old_days", [["2026-11-02", "2026-11-02"], ["2026-10-20", "2026-11-01", "2026-11-02"]], ids=["two-same-day-crashes", "many-days-crashes"])
def test_real_native_retry_after_multiple_unfinished_runs(tmp_path, monkeypatch, old_days):
    healthy, rc = produce(tmp_path, monkeypatch)
    text = "".join(crash(day, f"09:{20 + i}:00") for i, day in enumerate(old_days)) + healthy
    native = state("2026-11-02 09:25:59", "2026-11-02 09:26:07")
    assert row(tmp_path, text, native, "systemd")["log_anomaly"] is False
    assert scan(tmp_path, text)["keyword"] == "FATAL"
