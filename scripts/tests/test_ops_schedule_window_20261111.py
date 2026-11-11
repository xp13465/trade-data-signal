"""Cross-window SLA regression controls; all evidence is offline/synthetic."""
from datetime import timedelta

import pytest

import ops_schedule_contract as sc
import ops_stability_acceptance as acc
from test_ops_schedule_contract_20261111 import fixture, add_deadlines, change_source  # noqa: F401


def cross_window_plan(fixture):
    plan, _ = fixture
    add_deadlines(fixture)
    change_source(fixture, "*-*-15 02:33:00", "*-*-15 23:45:00")
    tail = next(s for s in plan["slots"] if s["task_id"] == "gamma")
    tail.update(scheduled_at="2026-11-15T23:45:00+08:00", deadline="2026-11-16T00:45:00+08:00")
    plan.update(schema="ops-stability-plan-v1", dataset="synthetic", deployment={},
                notification_sources=[{"id": "native", "channels": ["email"]}])
    return plan, tail


def test_reconciled_final_slot_keeps_full_sla_without_extending_window(fixture):
    plan, tail = cross_window_plan(fixture)
    before = sc.canonical(plan)
    reconciliation = sc.reconcile(*fixture)
    assert reconciliation["denominator_completeness"] == reconciliation["business_deadline_coverage"] == "complete"
    assert reconciliation["expected_slot_count"] == 12
    assert acc.validate_plan(plan) == (sc.stamp(plan["window_start"]), sc.stamp(plan["window_end"]))
    assert tail["deadline"] == "2026-11-16T00:45:00+08:00"
    assert sc.canonical(plan) == before  # no clipping SLA, deleting tail or extending window


@pytest.mark.parametrize("mutation", ["before_start", "at_end", "after_end", "zero_budget", "negative_budget", "excess_budget"])
def test_slot_membership_and_budget_bounds_still_enforced(fixture, mutation):
    plan, tail = cross_window_plan(fixture)
    if mutation == "before_start":
        tail["scheduled_at"] = "2026-11-01T23:59:59+08:00"
    elif mutation == "at_end":
        tail["scheduled_at"] = plan["window_end"]
    elif mutation == "after_end":
        tail["scheduled_at"] = "2026-11-16T00:00:01+08:00"
    else:
        seconds = {"zero_budget": 0, "negative_budget": -1, "excess_budget": sc.MAX_DEADLINE_SECONDS + 1}[mutation]
        tail["deadline"] = (sc.stamp(tail["scheduled_at"]) + timedelta(seconds=seconds)).isoformat()
    with pytest.raises(ValueError, match="slot schedule outside|slot deadline must follow"):
        acc.validate_plan(plan)


def test_max_supported_relative_sla_remains_full(fixture):
    plan, tail = cross_window_plan(fixture)
    tail["deadline"] = (sc.stamp(tail["scheduled_at"]) + timedelta(seconds=sc.MAX_DEADLINE_SECONDS)).isoformat()
    acc.validate_plan(plan)
    assert sc.stamp(tail["deadline"]) - sc.stamp(tail["scheduled_at"]) == timedelta(days=366)
    # This new value does not match the fixed 3600-second contract; accepting
    # the timestamp shape cannot bypass the independent contract check.
    assert sc.reconcile(*fixture)["denominator_completeness"] == "incomplete"


@pytest.fixture
def accounting():
    from test_ops_quiet_accounting_20261111 import AccountingCLI
    AccountingCLI.setUpClass()  # existing egress/write traps and their six positive controls
    case = AccountingCLI()
    try:
        case.setUp()
        slot = case.plan["slots"][-1]
        end = sc.stamp(case.plan["window_end"])
        slot.update(scheduled_at=(end - timedelta(minutes=15)).isoformat(),
                    deadline=(end + timedelta(minutes=45)).isoformat())
        yield case
    finally:
        case.doCleanups()
        AccountingCLI.tearDownClass()


def finish_tail(case, seconds, evaluated_seconds=None):
    slot = case.plan["slots"][-1]
    start = sc.stamp(slot["scheduled_at"])
    finished = start + timedelta(seconds=seconds)
    evaluated = start + timedelta(seconds=evaluated_seconds if evaluated_seconds is not None else seconds + 1)
    receipt = case.receipt(-1)
    receipt.update(evaluated_at=evaluated.isoformat(),
                   producer_time={"started_at": start.isoformat(), "completed_at": finished.isoformat()})
    receipt["consumer_witness"]["valid_until"] = (start + timedelta(hours=2)).isoformat()
    case.save_receipt(receipt, -1)
    for check in case.obs["runs"][-1]["public_reads"]:
        check["checked_at"] = finished.isoformat()
    return evaluated.isoformat()


@pytest.mark.parametrize("seconds_after_end,state,verdict", [(0, "pending", "PENDING"), (2699, "pending", "PENDING"),
                                                           (2700, "unknown", "UNKNOWN"), (3600, "unknown", "UNKNOWN")])
def test_missing_tail_evidence_uses_true_deadline_and_as_of(accounting, seconds_after_end, state, verdict):
    case = accounting
    case.obs["runs"].pop()
    end = sc.stamp(case.plan["window_end"])
    result = case.cli((end + timedelta(seconds=seconds_after_end)).isoformat())
    assert result["verdict"] == verdict, result.get("input_problems")
    assert result["business_account"]["expected_slots"] == 14
    assert result["business_account"]["slots"][-1]["status"] == state
    assert result["business_account"]["slots"][-1]["deadline"] == case.plan["slots"][-1]["deadline"]
    windows = result["observation_windows"]
    assert windows["slot_membership"]["end"] == case.plan["window_end"]
    assert windows["business_evidence"]["post_window_deadline_slots"] == 1
    assert windows["business_evidence"]["deadline_horizon_elapsed"] is (seconds_after_end >= 2700)
    assert windows["notification_account"]["cutoff"] == case.plan["window_end"]
    assert result["elapsed_window_mature"] is True  # calendar span, not SLA expiry or execution proof
    assert result["execution_coverage_satisfied"] is None


@pytest.mark.parametrize("seconds,status,verdict", [(1800, "consistent", "REPLAY_OK"), (3600, "consistent", "REPLAY_OK"),
                                                   (3601, "fail", "FAIL")])
def test_native_receipt_actual_completion_across_window(accounting, seconds, status, verdict):
    case = accounting
    as_of = finish_tail(case, seconds)
    result = case.cli(as_of)
    assert result["verdict"] == verdict, result.get("input_problems")
    tail = result["business_account"]["slots"][-1]
    assert tail["status"] == status
    assert tail["observations"][0]["completed_at"] > case.plan["window_end"]
    assert tail["deadline"] == case.plan["slots"][-1]["deadline"]
    if seconds > 3600:
        assert tail["observations"][0]["reasons"] == ["business_deadline_missed"]
    assert result["production_stability"] == "NOT_CERTIFIED"


def test_late_poll_does_not_turn_on_time_completion_into_late_business(accounting):
    as_of = finish_tail(accounting, 1800, evaluated_seconds=7200)
    result = accounting.cli(as_of)
    assert result["verdict"] == "REPLAY_OK", result.get("input_problems")
    assert result["observation_windows"]["business_evidence"]["deadline_horizon_elapsed"] is True


def test_finished_early_does_not_need_to_wait_for_unexpired_deadline(accounting):
    finish_tail(accounting, 300)
    result = accounting.cli(accounting.plan["window_end"])
    assert result["verdict"] == "REPLAY_OK", result.get("input_problems")
    assert result["observation_windows"]["business_evidence"]["deadline_horizon_elapsed"] is False
    assert result["business_account"]["counts"]["consistent"] == 14


def test_future_cross_window_receipt_cannot_be_used_at_earlier_cutoff(accounting):
    finish_tail(accounting, 1800)
    result = accounting.cli(accounting.plan["window_end"])
    assert result["verdict"] == "UNKNOWN"
    assert result["business_account"]["slots"][-1]["observations"][0]["reasons"] == ["future_receipt"]


def test_missing_sla_is_not_timeout_or_proven_lateness(accounting):
    as_of = finish_tail(accounting, 3601)
    accounting.plan["slots"][-1]["deadline_basis"]["kind"] = "process_limit"
    result = accounting.cli(as_of)
    assert result["verdict"] == "UNKNOWN"
    assert result["business_account"]["slots"][-1]["observations"][0]["reasons"] == ["business_deadline_not_approved"]
