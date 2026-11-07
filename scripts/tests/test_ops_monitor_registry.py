"""Offline canonical/registry integration; imports no collector or business entrypoint."""
import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import check_unit_registry_drift as drift
import gen_schedule_stats as gss
import gen_systemd_units as gsu
from _monitor_conclusion_309 import conclusion, namespace

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / gsu.MD_REL_PATH
FIX = Path(__file__).parent / "fixtures" / "309"
OPS = "trade-ops-monitor.service"
TIMER = "trade-ops-monitor.timer"
SELF = {"trade-schedule-monitor.service", "trade-self-heal.service",
        "trade-check-monitor-heartbeat.service"}


def test_registry_is_exact_original_44_plus_ops_monitor():
    historic_sets = []
    for name in ("x1_units.json", "x2_units.json", "x3_units.json"):
        units = json.loads((FIX / name).read_text())
        old = {u for u in units if u.endswith(".service")}
        assert len(old) == 44 and OPS not in old
        historic_sets.append(old)
    assert historic_sets[0] == historic_sets[1] == historic_sets[2]
    rows = gss.UNIT_REGISTRY
    assert len(rows) == len({r["unit"] for r in rows}) == 45
    assert {r["unit"] for r in rows} == historic_sets[0] | {OPS}
    assert next(r for r in rows if r["unit"] == OPS) == {
        "unit": OPS, "task": "ops_monitor", "name": "运行架构监测",
        "display": "运行架构监测", "kind": "business", "include": True,
    }
    assert {r["unit"] for r in rows if not r["include"]} == SELF
    assert {r["unit"] for r in rows if r["kind"] == "self_monitor"} == SELF
    assert sum(r["include"] for r in rows) == 42
    ns = namespace()
    assert ns["COVERAGE_BUSINESS_TOTAL"] == 42
    assert ns["COVERAGE_SELF_MONITOR"] == 3
    assert ns["LOG_CALIBER_COVERAGE"] == 17


def test_canonical_all_pairs_and_install_byte_parity(tmp_path):
    order, units = gsu.parse_units(str(DOC))
    titles = [m.group(1) for line in DOC.read_text().splitlines()
              if (m := gsu.TITLE_RE.match(line.strip()))]
    assert len(titles) == len(set(titles)) == len(order) == 90
    services = {u for u in order if u.endswith(".service")}
    timers = {u for u in order if u.endswith(".timer")}
    assert services == {r["unit"] for r in gss.UNIT_REGISTRY}
    assert timers == {u.removesuffix(".service") + ".timer" for u in services}
    assert gsu.write_units(str(tmp_path), order, units) == 90
    for name in (OPS, TIMER):
        expected = gsu.render_unit(units[name]).encode()
        assert (tmp_path / name).read_bytes() == expected
        assert (ROOT / "ops/monitoring/install" / name).read_bytes() == expected


def test_dynamic_parser_matches_canonical_registry_without_systemctl(monkeypatch):
    order, _ = gsu.parse_units(str(DOC))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="\n".join(
            [f"{u} enabled enabled" for u in order]
            + ["unrelated.service enabled enabled", "trade-readme.txt disabled -"]))

    monkeypatch.setattr(drift.shutil, "which", lambda _: "/fake/systemctl")
    monkeypatch.setattr(drift.subprocess, "run", fake_run)
    dynamic = drift._dynamic_real_units()
    assert dynamic == set(order)
    assert {u for u in dynamic if u.endswith(".service")} == drift._load_registry_services()
    assert drift._static_real_services() == drift._load_registry_services()
    assert calls == [(["systemctl", "list-unit-files", "--no-legend", "--no-pager"], {
        "capture_output": True, "text": True, "timeout": 15, "check": False})]


def test_real_static_drift_gate_and_missing_extra_negative_controls(monkeypatch, capsys):
    monkeypatch.setattr(drift, "_dynamic_real_units", lambda: set())
    assert drift.check_drift(quiet=True) == 0
    static = drift._static_real_services()
    for changed, expected in ((static - {OPS}, OPS),
                              (static | {"trade-unregistered.service"},
                               "trade-unregistered.service")):
        monkeypatch.setattr(drift, "_static_real_services", lambda: changed)
        assert drift.check_drift(quiet=True) == 2
        captured = capsys.readouterr()
        assert expected in captured.out + captured.err


@pytest.mark.parametrize("state", ["success", "failed", "missing"])
def test_actual_build_and_conclusion_observe_new_unit(tmp_path, monkeypatch, state):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    units = json.loads((FIX / "x3_units.json").read_text())
    # Explicit simulated extension; the dated fixture itself remains unmodified.
    if state != "missing":
        for suffix in ("service", "timer"):
            units[f"trade-ops-monitor.{suffix}"] = dict(
                units[f"trade-ab-direction-anchor.{suffix}"],
                InvocationID=f"synthetic-ops-{suffix}")
        if state == "failed":
            units[OPS].update(Result="exit-code", ExecMainStatus="1")
    rows = gss.build(log_dir=tmp_path, out=tmp_path / "stats.json",
                     now=datetime.datetime(2026, 10, 24, 21),
                     unit_reader=lambda unit: units.get(unit, {}),
                     ledger_path=tmp_path / "ledger.json")
    row = next(r for r in rows if r["task"] == "ops_monitor")
    assert len(rows) == 42
    assert json.loads((tmp_path / "stats.json").read_text()) == rows
    text = conclusion()(rows, datetime.datetime(2026, 10, 24, 21))
    assert "覆盖 45/45(42 业务+基础, 3 自监控)" in text
    if state == "success":
        assert (row["last_exit"], row["exit_source"]) == (0, "systemd")
        assert text.startswith("OK 所有任务")
    elif state == "failed":
        assert (row["last_exit"], row["exit_source"]) == (1, "systemd")
        assert "ops-monitor" in text and "1 个任务退出失败" in text
        assert "OK 所有任务" not in text
    else:
        assert row["last_exit"] is None and row["exit_source"] == "missing"
        assert "退出码未知 1 个" in text and "OK 所有任务" not in text
