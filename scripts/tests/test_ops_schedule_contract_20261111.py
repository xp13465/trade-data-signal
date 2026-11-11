"""Offline behavior controls. Fixture schedules are synthetic, never deployed."""
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys

import pytest

import ops_schedule_contract as sc
import ops_stability_acceptance as acceptance

REAL_ROOT = sc.ROOT
START = "2026-11-02T00:00:00+08:00"
END = "2026-11-16T00:00:00+08:00"
FROZEN = "2026-11-01T00:00:00+08:00"


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else sc.canonical(value))
    return {"path": str(path), "sha256": sc.sha(path.read_bytes())}


def pins(root):
    return {"schema": "ops-schedule-contract-v1", "scope": "repository-declared", "timezone": "Asia/Shanghai",
            "source": {"path": sc.SOURCE.as_posix(), "sha256": sc.sha((root / sc.SOURCE).read_bytes())},
            "registry": {"path": sc.REGISTRY.as_posix(), "sha256": sc.sha((root / sc.REGISTRY).read_bytes()),
                         "entries_sha256": sc.sha(sc.canonical(sc.registry.UNIT_REGISTRY))}}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    specs = {"alpha": "Mon..Fri *-*-* 08:00:00", "beta": "Sun *-*-* 03:00:00",
             "gamma": "*-*-15 02:33:00", "delta": "*-01,04,07,10-01 04:00:00"}
    rows = [{"task": name, "unit": "trade-" + name + ".service", "include": name != "delta"} for name in specs]
    blocks = []
    for name, expr in specs.items():
        blocks.append(f"`trade-{name}.timer`:\n```ini\n[Timer]\nOnCalendar={expr}\n```\n")
        blocks.append(f"`trade-{name}.service`:\n```ini\n[Service]\nTimeoutStartSec=600\n```\n")
    put(tmp_path / sc.SOURCE, "\n".join(blocks).encode())
    put(tmp_path / sc.REGISTRY, b"# synthetic registry source for fixture\n")
    monkeypatch.setattr(sc, "ROOT", tmp_path)
    monkeypatch.setattr(sc.registry, "UNIT_REGISTRY", rows)
    monkeypatch.setattr(sc, "REGISTRY_LOADED_SHA256", sc.sha((tmp_path / sc.REGISTRY).read_bytes()))
    contract = pins(tmp_path)
    trading = ["2026-10-30"] + [f"2026-11-{n:02d}" for n in (2, 3, 4, 5, 6, 10, 11, 12, 13)]
    contract["calendar"] = put(tmp_path / "calendar.json", {
        "schema": "ops-trading-calendar-v1", "source": "synthetic holiday fixture, NOT exchange evidence",
        "timezone": "Asia/Shanghai", "coverage_start": "2026-10-30", "coverage_end": "2026-11-16", "trading_dates": trading})
    contract["tasks"] = {task: {"eligibility": "calendar", "business_date_rule": "scheduled_date"} for task in specs}
    contract["tasks"]["alpha"] = {"eligibility": "trading", "business_date_rule": "previous_trading_date"}
    # Independent oracle: explicit fixture days; do not ask the implementation to construct its own expected answer.
    slots = []
    for task, dates, clock in (("alpha", trading[1:], "08:00:00"),
                               ("beta", ["2026-11-08", "2026-11-15"], "03:00:00"),
                               ("gamma", ["2026-11-15"], "02:33:00")):
        for d in dates:
            at = sc.stamp(d + "T" + clock + "+08:00")
            slots.append({"task_id": task, "slot_id": task + d, "scheduled_at": at.isoformat(),
                          "business_date": trading[trading.index(d) - 1] if task == "alpha" else d,
                          "deadline": (at + timedelta(hours=1)).isoformat(), "object_id": "fixture", "frequency": "daily"})
    plan = {"window_start": START, "window_end": END, "generated_at": FROZEN, "frozen_at": FROZEN,
            "status": "frozen", "schedule_contract": contract, "slots": slots, "trading_dates": trading[1:]}
    return plan, tmp_path


def check(fixture):
    return sc.reconcile(*fixture)


def repin_calendar(fixture, **changes):
    plan, root = fixture
    path = Path(plan["schedule_contract"]["calendar"]["path"])
    calendar = json.loads(path.read_bytes())
    calendar.update(changes)
    plan["schedule_contract"]["calendar"] = put(path, calendar)


def change_source(fixture, old, new):
    plan, root = fixture
    path = root / sc.SOURCE
    path.write_text(path.read_text().replace(old, new))
    plan["schedule_contract"]["source"]["sha256"] = sc.sha(path.read_bytes())


def add_deadlines(fixture):
    plan, root = fixture
    plan["schedule_contract"]["deadlines"] = put(root / "deadlines.json", {
        "schema": "ops-business-deadlines-v1", "kind": "business_contract", "source": "synthetic approved SLA fixture",
        "approved_at": FROZEN, "after_seconds_by_task": dict.fromkeys(plan["schedule_contract"]["tasks"], 3600)})


def test_whole_inventory_holiday_previous_date_and_no_timeout_sla(fixture):
    result = check(fixture)
    assert result["denominator_completeness"] == "complete", result
    assert result["expected_slot_count"] == 12
    assert result["registry_tasks"] == result["timer_units"] == 4
    assert {t["task_id"]: t["expected_slots"] for t in result["tasks"]} == {"alpha": 9, "beta": 2, "gamma": 1, "delta": 0}
    assert result["business_deadline_coverage"] == "unknown"
    assert all(s["deadline"] is None for s in result["expected_slots"])
    assert result["expected_slots"][0]["business_date"] == "2026-10-30"
    assert result["scope"] == "repository-declared"
    assert result["actual_systemd_deployment"] == "NOT_VERIFIED"
    assert result["execution_coverage_satisfied"] is None
    assert result["input_hashes"] and result["contract_sha256"]


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "duplicate_id", "wrong_date", "shifted_time", "wrong_task", "wrong_offset", "bad_date", "missing_id", "empty"])
def test_slot_negative_controls(fixture, mutation):
    slots = fixture[0]["slots"]
    if mutation == "missing":
        slots.pop()
    elif mutation == "extra":
        slots.append(dict(slots[0], slot_id="holiday", scheduled_at="2026-11-09T08:00:00+08:00"))
    elif mutation == "duplicate":
        slots.append(dict(slots[0], slot_id="different-id-same-trigger"))
    elif mutation == "duplicate_id":
        slots[1]["slot_id"] = slots[0]["slot_id"]
    elif mutation == "wrong_date":
        slots[0]["business_date"] = "2026-11-02"
    elif mutation == "shifted_time":
        slots[0]["scheduled_at"] = "2026-11-02T08:01:00+08:00"
    elif mutation == "wrong_task":
        slots[0]["task_id"] = "invented"
    elif mutation == "wrong_offset":
        slots[0]["scheduled_at"] = "2026-11-02T08:00:00+00:00"
    elif mutation == "bad_date":
        slots[0]["business_date"] = "20261030"
    elif mutation == "missing_id":
        del slots[0]["slot_id"]
    else:
        slots.clear()
    result = check(fixture)
    assert result["denominator_completeness"] != "complete", result
    assert result["business_deadline_coverage"] == "unknown"
    assert any(result[k] for k in ("issues", "missing_slots", "extra_slots", "duplicate_slots", "mismatched_slots"))


@pytest.mark.parametrize("mutation", ["missing", "tampered", "short_coverage", "duplicate", "outside", "missing_source", "wrong_schema", "plan_omits", "plan_extra", "plan_duplicate", "no_previous_date"])
def test_calendar_negative_controls(fixture, mutation):
    plan, root = fixture
    if mutation == "missing":
        (root / "calendar.json").unlink()
    elif mutation == "tampered":
        (root / "calendar.json").write_text("{}")
    elif mutation == "short_coverage":
        repin_calendar(fixture, coverage_end="2026-11-15")
    elif mutation == "duplicate":
        repin_calendar(fixture, trading_dates=plan["trading_dates"] * 2)
    elif mutation == "outside":
        repin_calendar(fixture, trading_dates=["2027-01-01"])
    elif mutation == "missing_source":
        repin_calendar(fixture, source="")
    elif mutation == "wrong_schema":
        repin_calendar(fixture, schema="raw-list")
    elif mutation == "plan_omits":
        plan["trading_dates"].pop()
    elif mutation == "plan_extra":
        plan["trading_dates"].append("2026-11-09")
    elif mutation == "plan_duplicate":
        plan["trading_dates"].append(plan["trading_dates"][0])
    else:
        repin_calendar(fixture, trading_dates=plan["trading_dates"])
    assert check(fixture)["denominator_completeness"] == "unknown"


@pytest.mark.parametrize("mutation", ["source_hash", "registry_hash", "entries_hash", "alternate_source", "duplicate_title", "missing_block", "extra_service", "target", "conditional", "relative", "unsupported", "unknown_policy", "conditional_policy", "missing_task", "extra_task", "business_date_rule", "draft", "late_freeze"])
def test_source_and_unknown_policy_controls(fixture, mutation):
    plan, root = fixture
    contract = plan["schedule_contract"]
    if mutation in {"source_hash", "registry_hash"}:
        contract[mutation.split("_")[0]]["sha256"] = "0" * 64
    elif mutation == "entries_hash":
        contract["registry"]["entries_sha256"] = "0" * 64
    elif mutation == "alternate_source":
        contract["source"]["path"] = "/tmp/selected-subset.md"
    elif mutation == "duplicate_title":
        path = root / sc.SOURCE
        path.write_text(path.read_text() + "\n`trade-alpha.timer`:\n```ini\n[Timer]\nOnCalendar=*-*-* 08:00:00\n```\n")
        contract["source"]["sha256"] = sc.sha(path.read_bytes())
    elif mutation == "missing_block":
        change_source(fixture, "```ini", "```text")
    elif mutation == "extra_service":
        path = root / sc.SOURCE
        path.write_text(path.read_text() + "\n`trade-extra.service`:\n```ini\n[Service]\nType=oneshot\n```\n")
        contract["source"]["sha256"] = sc.sha(path.read_bytes())
    elif mutation == "target":
        change_source(fixture, "[Timer]", "[Timer]\nUnit=trade-wrong.service")
    elif mutation == "conditional":
        change_source(fixture, "[Service]", "[Unit]\nConditionPathExists=/fictional\n[Service]")
    elif mutation == "relative":
        change_source(fixture, "[Timer]", "[Timer]\nOnBootSec=15min")
    elif mutation == "unsupported":
        change_source(fixture, "Mon..Fri *-*-* 08:00:00", "*-*-* 08:00:00 UTC")
    elif mutation in {"unknown_policy", "conditional_policy"}:
        contract["tasks"]["alpha"]["eligibility"] = mutation.split("_")[0]
    elif mutation == "missing_task":
        del contract["tasks"]["delta"]  # zero slots this window still cannot disappear
    elif mutation == "extra_task":
        contract["tasks"]["not-registered"] = contract["tasks"]["alpha"]
    elif mutation == "business_date_rule":
        contract["tasks"]["alpha"]["business_date_rule"] = "guess-latest"
    elif mutation == "draft":
        plan["status"] = "draft"
    else:
        plan["frozen_at"] = END
    assert check(fixture)["denominator_completeness"] == "unknown"


def test_explicit_deadline_contract_and_mismatched_deadline(fixture):
    add_deadlines(fixture)
    result = check(fixture)
    assert result["denominator_completeness"] == result["business_deadline_coverage"] == "complete"
    assert all(s["deadline"] for s in result["expected_slots"])
    fixture[0]["slots"][0]["deadline"] = "2026-11-02T08:10:00+08:00"  # equals TimeoutStartSec, not the SLA
    result = check(fixture)
    assert result["denominator_completeness"] == "incomplete"
    assert result["mismatched_slots"][0]["fields"] == ["deadline"]


@pytest.mark.parametrize("mutation", ["timeout", "late_approval", "missing_task", "bool_budget", "tamper", "no_source"])
def test_invalid_sla_never_certified(fixture, mutation):
    add_deadlines(fixture)
    path = fixture[1] / "deadlines.json"
    value = json.loads(path.read_bytes())
    if mutation == "timeout":
        value["kind"] = "TimeoutStartSec"
    elif mutation == "late_approval":
        value["approved_at"] = END
    elif mutation == "missing_task":
        del value["after_seconds_by_task"]["alpha"]
    elif mutation == "bool_budget":
        value["after_seconds_by_task"]["alpha"] = True
    elif mutation == "no_source":
        value["source"] = ""
    if mutation == "tamper":
        path.write_text("{}")
    else:
        fixture[0]["schedule_contract"]["deadlines"] = put(path, value)
    assert check(fixture)["business_deadline_coverage"] == "unknown"


@pytest.mark.parametrize("expr,count", [("Mon..Fri *-*-* 08:00:00", 10), ("Sun 22:30:00", 2),
                                          ("*-*-* *:00/15:00", 1344), ("*-*-* *:01,45:00", 672),
                                          ("*-*-15 02:33:00", 1), ("*-01,04,07,10-01 04:00:00", 0),
                                          ("2026-11-02 01..02:00:00", 2)])
def test_calendar_subset_expansion(expr, count):
    assert len(sc.expand(expr, sc.stamp(START), sc.stamp(END))) == count


@pytest.mark.parametrize("expr", ["daily", "Mon..XYZ 08:00:00", "Sun..Mon 08:00:00", "*-*-* 08:00:00 UTC",
                                  "*-*-* *:00/0:00", "*-*-* 24:00:00", "*-13-* 01:00:00", "*-*-* *:*:*", "garbage"])
def test_unsupported_or_unbounded_expressions_fail_closed(expr):
    with pytest.raises(ValueError):
        sc.expand(expr, sc.stamp(START), sc.stamp(END))


def test_repeated_overlap_and_reset_not_duplicate_slots(fixture):
    change_source(fixture, "OnCalendar=Mon..Fri *-*-* 08:00:00", "OnCalendar=Mon..Fri *-*-* 08:00:00\nOnCalendar=Mon *-*-* 08:00:00")
    assert check(fixture)["expected_slot_count"] == 12
    assert check(fixture)["denominator_completeness"] == "complete"
    change_source(fixture, "OnCalendar=Sun *-*-* 03:00:00", "OnCalendar=*-*-* 04:00:00\nOnCalendar=\nOnCalendar=Sun *-*-* 03:00:00")
    assert check(fixture)["denominator_completeness"] == "complete"


def test_real_repository_inventory_preserves_conditionals_and_no_sla(tmp_path, monkeypatch):
    # No collectors or subprocess/systemctl may be invoked during reconciliation.
    def blocked(*args, **kwargs):
        raise AssertionError("outbound/subprocess forbidden")
    monkeypatch.setattr(subprocess, "run", blocked)
    import socket
    monkeypatch.setattr(socket, "create_connection", blocked)
    contract = pins(REAL_ROOT)
    contract["tasks"] = {r["task"]: {"eligibility": "calendar", "business_date_rule": "scheduled_date"} for r in sc.registry.UNIT_REGISTRY}
    contract["calendar"] = put(tmp_path / "calendar.json", {
        "schema": "ops-trading-calendar-v1", "source": "synthetic fixture, not production calendar", "timezone": "Asia/Shanghai",
        "coverage_start": "2026-11-02", "coverage_end": "2026-11-16", "trading_dates": []})
    result = sc.reconcile({"window_start": START, "window_end": END, "generated_at": FROZEN, "frozen_at": FROZEN,
                           "status": "frozen", "slots": [], "trading_dates": [], "schedule_contract": contract}, tmp_path)
    assert result["registry_tasks"] == result["timer_units"] == len(sc.registry.UNIT_REGISTRY) == 45
    unknown = {r["task_id"] for r in result["tasks"] if r["status"] == "unknown"}
    assert unknown == {"check_monitor_heartbeat", "r2_consistency", "cloud_unit_patrol"}
    assert result["denominator_completeness"] == result["business_deadline_coverage"] == "unknown"
    assert result["expected_slot_count"] > 4096  # full 14-day inventory exceeds the old plan bound
    assert all(s["deadline"] is None for s in result["expected_slots"])


def test_cli_manifest_hash_is_required_and_read_only(tmp_path):
    path = tmp_path / "plan.json"
    raw = sc.canonical({"window_start": START, "window_end": END})
    path.write_bytes(raw)
    for digest in (sc.sha(raw), "0" * 64):
        proc = subprocess.run([sys.executable, "-B", str(REAL_ROOT / "scripts/ops_schedule_contract.py"),
                               "--manifest", str(path), "--manifest-sha256", digest, "--evidence-root", str(tmp_path)],
                              text=True, capture_output=True, timeout=10)
        assert proc.returncode == 2
        value = json.loads(proc.stdout)
        assert value["denominator_completeness"] == "unknown"
        assert value["actual_systemd_deployment"] == "NOT_VERIFIED"
    assert list(tmp_path.iterdir()) == [path]


def test_acceptance_coverage_output_keeps_legacy_unknown_and_inspect_run_untouched():
    # Exercise the real acceptance entrypoint through its existing offline fixture.
    from test_ops_quiet_accounting_20261111 import AccountingCLI
    AccountingCLI.setUpClass()
    case = AccountingCLI()
    try:
        case.setUp()
        result = case.cli()
        assert result["verdict"] == "REPLAY_OK"
        assert result["denominator_completeness"] == "unknown"
        assert result["schedule_reconciliation"]["actual_systemd_deployment"] == "NOT_VERIFIED"
        case.plan["schedule_contract"] = {"schema": "invalid"}
        result = case.cli()
        assert result["verdict"] == "UNKNOWN"
        assert "schedule_or_business_deadline_contract_incomplete" in result["input_problems"]
    finally:
        case.doCleanups()
        AccountingCLI.tearDownClass()


def test_registry_changed_after_import_cannot_repin_old_values(fixture):
    plan, root = fixture
    path = root / sc.REGISTRY
    path.write_text("# new registry version after import\n")
    plan["schedule_contract"]["registry"]["sha256"] = sc.sha(path.read_bytes())
    result = check(fixture)
    assert result["denominator_completeness"] == "unknown"
    assert "registry_code_changed_since_import" in result["issues"]


def test_parser_input_changed_while_reading_stays_unknown(fixture, monkeypatch):
    parser = sc.units_parser.parse_units
    def parse_and_change(path):
        parsed = parser(path)
        with Path(path).open("a") as stream:
            stream.write("\n# concurrent edit\n")
        return parsed
    monkeypatch.setattr(sc.units_parser, "parse_units", parse_and_change)
    result = check(fixture)
    assert result["denominator_completeness"] == "unknown"
    assert any("input_changed_during_read" in issue for issue in result["issues"])


def test_acceptance_reconciled_denominator_does_not_certify_execution(fixture):
    plan, root = fixture
    add_deadlines(fixture)
    plan.update(schema="ops-stability-plan-v1", dataset="synthetic", deployment={},
                notification_sources=[{"id": "native", "channels": ["email"]}])
    ledger = root / "empty.jsonl"
    ledger.write_text("")
    result = acceptance.assess(plan, {"dataset": "synthetic", "runs": []}, root, {"native": ledger}, ledger, sc.stamp(END))
    assert result["denominator_completeness"] == "complete"
    assert result["declared_subset"] is False
    assert result["schedule_reconciliation"]["business_deadline_coverage"] == "complete"
    assert result["business_account"]["counts"]["unknown"] == 12
    assert result["verdict"] == "UNKNOWN"
    assert result["execution_coverage_satisfied"] is None
    assert result["production_stability"] == "NOT_CERTIFIED"
    assert result["input_hashes"][str(root / "calendar.json")]


def test_large_inventory_plan_validation_exceeds_old_4096_bound(fixture):
    plan, _ = fixture
    plan.update(schema="ops-stability-plan-v1", dataset="synthetic", deployment={},
                notification_sources=[{"id": "native", "channels": ["email"]}])
    original = plan["slots"][0]
    begin = sc.stamp(START)
    plan["slots"] = [dict(original, slot_id=str(i), scheduled_at=(begin + timedelta(minutes=i)).isoformat(),
                          deadline=(begin + timedelta(minutes=i + 1)).isoformat()) for i in range(4097)]
    assert acceptance.validate_plan(plan) == (sc.stamp(START), sc.stamp(END))
