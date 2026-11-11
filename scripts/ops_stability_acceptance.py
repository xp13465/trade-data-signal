#!/usr/bin/env python3
"""Offline two-account acceptance. Explicit inputs only; never collect or send.

The plan fixes slots/deadlines before observation. Native delivery receipts,
systemctl-show captures and retained public response bodies are checked, not a
hand-entered success flag. This validates supplied evidence, not its authenticity.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import alert_noise_count as noise
from delivery_evidence import _validate
from ops_business_evidence import OBJECTS, RULE
import ops_schedule_contract as schedule_contract

LIMIT = 32 * 1024 * 1024
POLICY = {"initial_calendar_days": 14, "initial_trading_days": 7,
          "weekly_natural_rounds": 2, "trend_calendar_days": 30}


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def read(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > LIMIT:
        raise ValueError("missing/nonregular/oversized input: " + str(path))
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("input exceeds limit")
    return data


def digest(value, length=64):
    return isinstance(value, str) and re.fullmatch("[a-f0-9]{%d}" % length, value) is not None


def identifiers(values):
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
        raise ValueError("nonempty identity list required")
    if len(values) != len(set(values)):
        raise ValueError("duplicate identity")
    return sorted(values)


def validate_plan(plan):
    if plan.get("schema") != "ops-stability-plan-v1" or plan.get("dataset") not in {"synthetic", "replay", "production", "unknown"}:
        raise ValueError("explicit plan schema/dataset required")
    start, end = stamp(plan["window_start"]), stamp(plan["window_end"])
    if start.utcoffset() != timedelta(hours=8) or end.utcoffset() != timedelta(hours=8):
        raise ValueError("native ledger calendar uses Asia/Shanghai (+08:00)")
    if not start < end or (end - start).days > 366 or start.timetz().replace(tzinfo=None) != datetime.min.time() or end.timetz().replace(tzinfo=None) != datetime.min.time():
        raise ValueError("bounded whole-calendar-day window required (1..366 days)")
    stamp(plan["generated_at"])
    if plan.get("status") != "draft":
        stamp(plan["frozen_at"])
    deployment = plan["deployment"]
    if not isinstance(deployment, dict):
        raise ValueError("deployment object required (unknown fields may be null in draft)")
    if not isinstance(plan.get("slots"), list) or not 1 <= len(plan["slots"]) <= schedule_contract.MAX_SLOTS:
        raise ValueError("predeclared slots required; empty denominator is unknown")
    identifiers([s["slot_id"] for s in plan["slots"]])
    scheduled = set()
    for slot in plan["slots"]:
        schedule_key = (slot["task_id"], stamp(slot["scheduled_at"]))
        if schedule_key in scheduled:
            raise ValueError("duplicate_task_slot")
        scheduled.add(schedule_key)
        if not start <= stamp(slot["scheduled_at"]) < stamp(slot["deadline"]) <= end:
            raise ValueError("slot schedule/deadline outside fixed window")
        datetime.strptime(slot["business_date"], "%Y-%m-%d")
        if not slot.get("task_id") or not slot.get("object_id") or slot.get("frequency") not in {"daily", "weekly", "monthly", "quarterly"}:
            raise ValueError("task/object/frequency required")
        members = identifiers(slot["coverage"]) if slot.get("coverage") else None
        if members and slot.get("coverage_sha256") != sha(canonical(members)):
            raise ValueError("coverage identity mismatch")
        for urls in (slot.get("public_targets") or {}).values():
            for url in identifiers(urls):
                parts = urlsplit(url)
                if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
                    raise ValueError("public HTTPS URL required")
    if not isinstance(plan["trading_dates"], list):
        raise ValueError("explicit trading_dates list required")
    if plan["trading_dates"]:
        identifiers(plan["trading_dates"])
    for day in plan["trading_dates"]:
        parsed = datetime.strptime(day, "%Y-%m-%d").date()
        if not start.date() <= parsed < end.date():
            raise ValueError("trading date outside window")
    identifiers([s["id"] for s in plan["notification_sources"]])
    for source in plan["notification_sources"]:
        identifiers(source["channels"])
    return start, end


def deadline_approved(slot, start):
    """A supplied approval claim, not an independent authentication of a SLA."""
    basis = slot.get("deadline_basis", {})
    try:
        return (basis.get("kind") == "business_contract" and bool(basis.get("source"))
                and stamp(basis["approved_at"]) <= start)
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def lifecycle_account(observed, root, start, end, as_of, account, sources):
    """Use existing alert_state snapshots; never infer lifecycle from subjects.

    Endpoints cannot prove every intervening schedule decision or detect all
    missed alerts. Unnotified active states are candidates, not invented SLAs.
    """
    snapshots, issues = {}, []
    for name in ("before", "after"):
        try:
            ref = observed["event_states"][name]
            at = stamp(ref["captured_at"])
            if (name == "before" and at > start) or (name == "after" and not min(as_of, end) <= at <= as_of):
                raise ValueError("snapshot_time_outside_boundary")
            path = root / ref["path"]
            raw = read(path)
            if sha(raw) != ref["sha256"]:
                raise ValueError("snapshot_hash_mismatch")
            sources[str(path)] = sha(raw)
            state = json.loads(raw)
            if not isinstance(state, dict) or any(not isinstance(v, dict) for v in state.values()):
                raise ValueError("native_alert_state_mapping_required")
            snapshots[name] = state
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            issues.append(name + ":" + str(exc))
    accepted = account["successful_event_deliveries"]
    paired, unpaired, candidates, boundary_duplicates = [], [], [], {}
    for item in accepted:
        prior = snapshots.get("before", {}).get(item["key"], {})
        if item["phase"] == "active" and prior.get("notified_event_id") == item["event_id"]:
            channels = prior.get("notified_channels") or {}
            attempt = prior.get("last_notification_attempt") or {}
            if isinstance(channels, dict) and channels.get(item["channel"]) is True:
                if (isinstance(attempt, dict) and attempt.get("phase") == "active"
                        and isinstance(attempt.get("attempt_id"), str) and attempt["attempt_id"]):
                    in_window = {x["attempt_id"] for x in accepted if x["event_id"] == item["event_id"]
                                 and x["channel"] == item["channel"] and x["phase"] == "active"}
                    if attempt["attempt_id"] not in in_window:
                        boundary_duplicates[(item["event_id"], item["channel"])] = {
                            "event_id": item["event_id"], "channel": item["channel"],
                            "before_attempt_id": attempt["attempt_id"], "window_attempt_ids": sorted(in_window),
                            "additional_excess_acceptances": 1}
                else:
                    issues.append("prior_active_attempt_identity_unknown:" + item["event_id"])
        if item["phase"] != "recovery":
            continue
        initial_match = (prior.get("notified_event_id") == item["event_id"]
                         and isinstance(prior.get("notified_channels"), dict)
                         and prior["notified_channels"].get(item["channel"]) is True)
        preceding = any(other["event_id"] == item["event_id"] and other["channel"] == item["channel"]
                        and other["phase"] in {"active", "escalation"}
                        and noise.parse_ts(other["ts"]) < noise.parse_ts(item["ts"]) for other in accepted)
        (paired if initial_match or preceding else unpaired).append(item)
    for key, state in snapshots.get("after", {}).items():
        if state.get("status") != "active" or state.get("requires_action") is not True:
            continue
        event_id = state.get("event_id")
        accepted_here = any(item["event_id"] == event_id and item["phase"] in {"active", "escalation"} for item in accepted)
        native_notified = (event_id and state.get("notified_event_id") == event_id
                           and isinstance(state.get("notified_channels"), dict)
                           and any(value is True for value in state["notified_channels"].values()))
        if not accepted_here and not native_notified:
            candidates.append({"key": key, "event_id": event_id, "source_run": state.get("source_run"),
                               "reason": "action_required_without_observed_acceptance; deadline/channel requirements unknown"})
    return {"boundary_status": "unknown" if issues else "observed", "issues": issues,
            "pre_window_duplicate_acceptances": list(boundary_duplicates.values()),
            "paired_recoveries": paired, "unpaired_recoveries": unpaired,
            "unnotified_actionable_candidates": candidates, "missed_alerts_status": "unknown",
            "caveat": "边界state仅核已知受理配对；不证明中途事件完整性/恢复业务事实/漏报为0，须schedule→state→refs全链证据。"}


def inspect_run(run, slot, plan, root, as_of, sources):
    """Read native receipt + actual-format show capture, retaining unknowns."""
    def load(relative, parse=True):
        path = root / relative
        data = read(path)
        if str(path) in sources and sources[str(path)] != sha(data):
            raise ValueError("input_changed_during_read:" + str(path))
        sources[str(path)] = sha(data)
        return json.loads(data) if parse else data
    result = {"run_id": None, "status": "unknown", "reasons": [], "origin": run.get("origin"),
              "manual_intervention": run.get("manual_intervention"), "upstream_failure": run.get("upstream_failure"),
              "root_cause_id": run.get("root_cause_id")}
    try:
        receipt = _validate(load(run["receipt"]))
        result.update(run_id=receipt["attempt_id"], receipt_id=receipt["receipt_id"],
                      evaluated_at=receipt["evaluated_at"], upstream_failure=run.get("upstream_failure"),
                      root_cause_id=run.get("root_cause_id"), origin=run.get("origin"),
                      manual_intervention=run.get("manual_intervention"))
        at = stamp(receipt["evaluated_at"])
        if at > as_of:
            raise ValueError("future_receipt")
        if slot["object_id"] not in OBJECTS:
            raise ValueError("business_receipt_interface_unavailable:" + slot["object_id"])
        if run.get("manual_intervention") is True or run.get("origin") == "manual":
            result.update(status="fail", reasons=["manual_remediation"])
            return result
        if (run.get("manual_intervention") is not False or run.get("origin") not in {"timer", "retry"}
                or type(run.get("upstream_failure")) is not bool):
            raise ValueError("execution_provenance_unknown")
        if receipt["chain_id"] != "ops_business" or receipt["object_id"] != slot["object_id"]:
            raise ValueError("receipt_object_mismatch")
        if receipt["stage"] != ("restore" if slot["object_id"].startswith("backup-") else "publish"):
            raise ValueError("receipt_stage_mismatch")
        if receipt["session_date"] != slot["business_date"]:
            raise ValueError("business_date_mismatch")
        if (receipt["code_identity"].get("sha") != plan["deployment"]["code_ref"] or
                receipt["config_identity"].get("sha256") != plan["deployment"]["config_sha256"] or
                receipt["config_identity"].get("sha256") != sha(RULE.encode())):
            raise ValueError("deployment_mismatch")
        if slot["object_id"] in ("public-fund", "fof-nav"):
            try:
                from .ops_fund_evidence import assessment
            except ImportError:
                from ops_fund_evidence import assessment
            _, fund_reason, result["fund_evidence"] = assessment(receipt)
        # Evaluation time is when a receipt was inspected, not when its task ran.
        # Retain execution order for failures too. An unorderable proved failure
        # remains a failure and cannot be cleared by a later poll of old success.
        times = receipt["producer_time"]
        try:
            begin, finish = stamp(times["started_at"]), stamp(times["completed_at"])
            if stamp(slot["scheduled_at"]) <= begin <= finish <= at:
                result["completed_at"] = times["completed_at"]
        except (KeyError, ValueError, TypeError, AttributeError):
            pass
        if receipt["stage_status"] == "failure":
            result.update(status="fail", reasons=["business_failure:" + receipt["reason"]])
            return result
        # Read the retained systemctl-show text, never invoke systemctl.
        journal = dict(line.split("=", 1) for line in load(run["journal"], False).decode().splitlines() if "=" in line)
        witness = receipt["consumer_witness"]
        if witness.get("rule_version") != RULE or witness.get("scope") != RULE:
            raise ValueError("receipt_rule_mismatch")
        invocation = witness.get("invocation_id")
        if not invocation or invocation == "unknown" or journal.get("InvocationID") != invocation:
            raise ValueError("invocation_mismatch_or_missing")
        if journal.get("ActiveState") == "failed" or journal.get("Result") not in {None, "success", ""}:
            result.update(status="fail", reasons=["invocation_failed"])
            return result
        if run.get("journal_complete") is not True:
            raise ValueError("journal_coverage_unknown")
        if journal.get("ActiveState") != "inactive" or journal.get("Result") != "success" or journal.get("ExecMainStatus") != "0":
            raise ValueError("completion_unverified")
        if "completed_at" not in result:
            raise ValueError("run_time_mismatch")
        if not finish <= stamp(witness["valid_until"]) <= begin + timedelta(hours=26):
            raise ValueError("invalid_receipt_validity")
        approved = deadline_approved(slot, stamp(plan["window_start"]))
        if approved and finish > stamp(slot["deadline"]):
            result.update(status="fail", reasons=["business_deadline_missed"])
            return result
        if slot["object_id"] in ("public-fund", "fof-nav"):
            raise ValueError(fund_reason)
        if receipt["stage_status"] != "success" or receipt["evidence_quality"] != "strong":
            raise ValueError("business_completion_unverified")
        if not slot.get("coverage"):
            raise ValueError("coverage_manifest_missing")
        members = identifiers(load(run["coverage"]))
        if sha(canonical(members)) != slot["coverage_sha256"]:
            result.update(status="fail", reasons=["coverage_set_mismatch"])
            return result
        expected = len(slot["coverage"])
        if receipt["counts"].get("expected") != expected or receipt["counts"].get("validated") != expected:
            result.update(status="fail", reasons=["coverage_count_mismatch"])
            return result
        def identities(rows):
            values = {}
            for value in rows:
                name = value.get("object_id")
                if (not isinstance(name, str) or not name or name in values or not digest(value.get("sha256"))
                        or type(value.get("size")) is not int or value["size"] < 0):
                    raise ValueError("invalid_output_identity")
                values[name] = (value["sha256"], value["size"])
            return values
        outputs = identities(receipt["outputs"])
        if not identities(receipt["inputs"]) or outputs != identities(witness.get("confirmed", [])):
            raise ValueError("input_output_confirmation_missing")
        backup = slot["object_id"].startswith("backup-")
        if backup:
            if not outputs or slot.get("public_targets"):
                raise ValueError("backup_restore_not_public_NAV_delivery")
            if not approved:
                raise ValueError("business_deadline_not_approved")
            result.update(status="consistent", reasons=[], evidence_type="native_backup_restore_only")
            return result
        if not slot.get("public_targets"):
            raise ValueError("public_manifest_missing")
        if set(outputs) != set(slot["public_targets"]):
            raise ValueError("output_set_mismatch")
        publication_run = witness.get("publication_run_id")
        if slot["object_id"] == "overfit" and not publication_run:
            raise ValueError("publication_generation_missing")
        publication_run = publication_run or receipt["attempt_id"]
        public = run.get("public_reads", [])
        expected_urls = {(name, url) for name, urls in slot["public_targets"].items() for url in urls}
        found = set()
        for check in public:
            key = (check["object_id"], check["url"])
            if key not in expected_urls or key in found:
                raise ValueError("public_target_mismatch_or_duplicate")
            if check.get("run_id") != publication_run or check.get("business_date") != slot["business_date"]:
                raise ValueError("public_run_or_date_mismatch")
            checked = stamp(check["checked_at"])
            if not begin <= checked <= finish:
                raise ValueError("public_check_outside_run")
            body = load(check["body"], False)
            if check.get("http_status") != 200 or (sha(body), len(body)) != outputs[key[0]]:
                result.update(status="fail", reasons=["public_bytes_mismatch"])
                return result
            found.add(key)
        if found != expected_urls:
            raise ValueError("public_evidence_missing")
        if not approved:
            raise ValueError("business_deadline_not_approved")
        result.update(status="consistent", reasons=[], coverage_sha256=slot["coverage_sha256"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result["reasons"].append(str(exc))
    return result


def assess(plan, observed, root, ledgers, legacy, as_of):
    start, end = validate_plan(plan)
    sources, input_problems = {}, []
    schedule = schedule_contract.reconcile(plan, root)
    sources.update(schedule["input_hashes"])
    # Legacy subset plans retain their evidence-only verdict. An explicitly
    # requested reconciliation cannot pass with missing/unknown contracts.
    if "schedule_contract" in plan and (schedule["denominator_completeness"] != "complete"
                                       or schedule["business_deadline_coverage"] != "complete"):
        input_problems.append("schedule_or_business_deadline_contract_incomplete")
    if observed.get("dataset") != plan["dataset"]:
        input_problems.append("dataset_mismatch")
    if plan["dataset"] == "unknown":
        input_problems.append("dataset_unknown")
    if observed.get("read_error"):
        input_problems.append(observed["read_error"])
    if plan.get("status") != "frozen" or not stamp(plan["generated_at"]) <= stamp(plan["frozen_at"]) <= start:
        input_problems.append("manifest_not_pre_frozen")
    deployment = plan["deployment"]
    if not digest(deployment.get("code_ref"), 40) or not digest(deployment.get("config_sha256")) or not digest(deployment.get("evidence_sha256")):
        input_problems.append("deployment_identity_or_evidence_unknown")
    try:
        if not stamp(deployment["verified_at"]) <= start:
            input_problems.append("deployment_not_verified_before_window")
    except (ValueError, TypeError, KeyError, AttributeError):
        input_problems.append("deployment_verification_time_unknown")
    try:
        deployment_path = root / observed["deployment_evidence"]
        sources[str(deployment_path)] = sha(read(deployment_path))
        if sources[str(deployment_path)] != plan["deployment"]["evidence_sha256"]:
            input_problems.append("deployment_evidence_hash_mismatch")
    except (KeyError, TypeError, OSError, ValueError) as exc:
        input_problems.append("deployment_evidence_missing:" + str(exc))
    days = [(start.date() + timedelta(days=i)).isoformat() for i in range((end.date() - start.date()).days)]
    if not days:
        raise ValueError("whole-day observation window required")
    if plan.get("frozen_at") and as_of < stamp(plan["frozen_at"]):
        input_problems.append("as_of_precedes_plan")
    if not plan["trading_dates"]:
        input_problems.append("trading_calendar_not_declared")
    results = []
    raw_runs = observed.get("runs", [])
    if not isinstance(raw_runs, list) or len(raw_runs) > 16384:
        raw_runs = []
        input_problems.append("runs_not_list")
    known_slots = {s["slot_id"] for s in plan["slots"]}
    for r in raw_runs:
        if not isinstance(r, dict) or r.get("slot_id") not in known_slots:
            input_problems.append("unassigned_run")
    for slot in plan["slots"]:
        if not deadline_approved(slot, start):
            input_problems.append("business_deadline_not_approved:" + slot["slot_id"])
        observations = [inspect_run(r, slot, plan, root, as_of, sources) for r in raw_runs
                        if isinstance(r, dict) and r.get("slot_id") == slot["slot_id"]]
        # A native run may have several polling receipts. Only its newest
        # observation is a state; attempts are NOT an increased slot denominator.
        latest, conflicts = {}, []
        def evaluated(r):
            try:
                return stamp(r["evaluated_at"])
            except (KeyError, ValueError, TypeError, AttributeError):
                return datetime.min.replace(tzinfo=timezone.utc)
        for i, r in enumerate(observations):
            key = r["run_id"] or "unidentified:" + str(i)
            prior = latest.get(key)
            if prior and r.get("evaluated_at") == prior.get("evaluated_at") and r != prior:
                conflicts.append(key)
            if not prior or evaluated(r) >= evaluated(prior):
                latest[key] = r
        def completed(r):
            try:
                return stamp(r["completed_at"])
            except (KeyError, ValueError, TypeError, AttributeError):
                return datetime.min.replace(tzinfo=timezone.utc)
        states = sorted(latest.values(), key=lambda r: (completed(r), evaluated(r)))
        state = states[-1]["status"] if states else "unknown" if as_of >= stamp(slot["deadline"]) else "pending"
        if conflicts or any("completed_at" not in r or r["status"] == "unknown" for r in states):
            state = "unknown"
        # Unknown/missing/newer polls cannot erase a proved failure. A later
        # complete native receipt may resolve a recoverable attempt in budget.
        failures = [r for r in observations if r["status"] == "fail"]
        if failures and (state != "consistent" or any("completed_at" not in r for r in failures)
                         or completed(states[-1]) <= max(map(completed, failures))):
            state = "fail"
        if any(set(r["reasons"]) & {"public_bytes_mismatch", "coverage_set_mismatch", "coverage_count_mismatch",
                                     "business_deadline_missed"} for r in failures):
            state = "fail"
        if any(r.get("manual_intervention") is True or r.get("origin") == "manual" for r in observations):
            state = "fail"
        results.append({"slot_id": slot["slot_id"], "task_id": slot["task_id"], "business_date": slot["business_date"],
                        "deadline": slot["deadline"], "frequency": slot["frequency"], "status": state,
                        "run_count": sum(r["run_id"] is not None for r in latest.values()),
                        "unidentified_observations": sum(r["run_id"] is None for r in observations),
                        "observations": observations, "conflicting_runs": conflicts,
                        "missing_evidence": not observations, "upstream_failure_observed": any(r.get("upstream_failure") is True for r in observations)})
    assigned_runs = {}
    for slot, result in zip(plan["slots"], results):
        for r in result["observations"]:
            if r["run_id"] is None:
                continue
            key = (slot["object_id"], r["run_id"])
            if key in assigned_runs and assigned_runs[key] != slot["slot_id"]:
                input_problems.append("run_reused_across_slots:" + r["run_id"])
            assigned_runs[key] = slot["slot_id"]
    paths = []
    for p in ledgers.values():
        try:
            sources[str(p)] = sha(read(p))
            paths.append(p)
        except (OSError, ValueError) as exc:
            input_problems.append(str(exc))
    notification = noise.all_groups_view(paths, days, cutoff=as_of.astimezone(start.tzinfo).replace(tzinfo=None))
    notification["observation_cutoff"] = as_of.isoformat()
    for p in paths:
        rows, _, _ = noise.load_records(p, all_groups=True)
        if any(noise.parse_ts(r.get("ts")) and noise.parse_ts(r["ts"]).replace(tzinfo=start.tzinfo) > as_of for r in rows):
            input_problems.append("notification_after_cutoff:" + str(p))
    coverage = observed.get("notification_coverage", {})
    for source in plan["notification_sources"]:
        name = source["id"]
        record = coverage.get(name, {}) if isinstance(coverage, dict) else {}
        try:
            if (name not in ledgers or record.get("complete") is not True or record.get("includes_failed_attempts") is not True
                    or sorted(record.get("channels", [])) != sorted(source["channels"])
                    or stamp(record["start"]) > start or stamp(record["end"]) < min(as_of, end)
                    or record.get("sha256") != sources.get(str(ledgers[name]))):
                raise ValueError("notification_coverage_incomplete:" + name)
        except (KeyError, TypeError, ValueError) as exc:
            input_problems.append(str(exc))
    if set(ledgers) != {s["id"] for s in plan["notification_sources"]}:
        input_problems.append("notification_source_set_mismatch")
    try:
        sources[str(legacy)] = sha(read(legacy))
        records, bad, bad_subject = noise.load_records(legacy)
    except (OSError, ValueError) as exc:
        records, bad, bad_subject = [], 0, 0
        input_problems.append(str(exc))
    legacy_report = noise.classify_rows(records, days)
    legacy_report.update(ledger=str(legacy), skipped_bad_lines=bad + bad_subject,
                         diverted=noise.count_diverted(records, days), contract="unchanged_alert_group_only")
    if not Path(legacy).is_file():
        input_problems.append("legacy_ledger_missing")
    strict = notification["outbound_account"]
    structural_unknowns = any(set(item["reasons"]) & {"unknown_or_missing_group", "unknown_or_missing_tier"}
                              for item in notification["uncertainties"])
    if strict["uncertainties"] or structural_unknowns or notification["coverage"]["skipped_bad_lines"] or notification["coverage"]["undated_rows"]:
        input_problems.append("notification_unknown_records")
    # Quietness is only proved for known routine/self-recovered observations.
    # Unknown kinds cannot be interpreted as zero routine sends or zero faults.
    routine_sent = sum(c["routine_declared_success_rows"] for c in strict["channels"].values())
    lifecycle = lifecycle_account(observed, root, start, end, as_of, strict, sources)
    if lifecycle["issues"] or lifecycle["unpaired_recoveries"] or lifecycle["unnotified_actionable_candidates"]:
        input_problems.append("notification_lifecycle_unknown")
    duplicate_acceptances = (sum(item["excess_acceptances"] for item in strict["duplicate_event_acceptances"])
                             + sum(item["additional_excess_acceptances"] for item in lifecycle["pre_window_duplicate_acceptances"]))
    # Explicit offline files must remain stable while statistics and hashes are
    # read. This detects ordinary concurrent changes, not forged provenance.
    for path, expected_hash in list(sources.items()):
        try:
            if sha(read(path)) != expected_hash:
                input_problems.append("input_changed_during_read:" + path)
        except (OSError, ValueError) as exc:
            input_problems.append(str(exc))
    counts = Counter(r["status"] for r in results)
    weekly = {}
    for s in plan["slots"]:
        if s["frequency"] == "weekly":
            weekly.setdefault(s["task_id"], set()).add(stamp(s["scheduled_at"]).date().isocalendar()[:2])
    mature = (as_of >= end and len(days) >= POLICY["initial_calendar_days"] and len(plan["trading_dates"]) >= POLICY["initial_trading_days"]
              and all(len(weeks) >= POLICY["weekly_natural_rounds"] for weeks in weekly.values()))
    verdict = ("FAIL" if counts["fail"] or routine_sent or duplicate_acceptances else "UNKNOWN" if input_problems or counts["unknown"] else
               "PENDING" if not mature or counts["pending"] else "REPLAY_OK" if plan["dataset"] in {"synthetic", "replay"} else "INPUTS_CONSISTENT")
    evidence_scope = observed.get("dataset", "unknown")
    if evidence_scope not in {"synthetic", "replay", "production", "unknown"}:
        evidence_scope = "unknown"
    return {"verdict": verdict, "dataset": plan["dataset"], "evidence_scope": evidence_scope,
            "verification_scope": "offline_input_contracts_references_hashes_statistics_only",
            "production_stability": "NOT_CERTIFIED", "independent_receipt_delivery": "unknown", "as_of": as_of.isoformat(),
            "manifest": {k: plan[k] for k in ("generated_at", "frozen_at", "window_start", "window_end", "deployment")},
            "business_account": {"expected_slots": len(results), "counts": {k: counts[k] for k in ("consistent", "fail", "pending", "unknown")},
                                 "input_consistency_fraction": counts["consistent"] / len(results), "slots": results},
            "legacy_alert_account": legacy_report, "notification_account": notification,
            "notification_lifecycle": lifecycle, "duplicate_event_channel_acceptances": duplicate_acceptances,
            "known_routine_channel_successes": routine_sent, "input_problems": input_problems, "input_hashes": sources,
            "window_mature": None, "window_maturity_scope": "not_certified; see elapsed_window_mature",
            "elapsed_window_mature": mature, "execution_coverage_satisfied": None,
            "denominator_completeness": schedule["denominator_completeness"],
            "declared_subset": schedule["denominator_completeness"] != "complete",
            "denominator_scope": "repository-declared; actual systemd deployment NOT_VERIFIED",
            "schedule_reconciliation": schedule,
            "proposed_policy": POLICY, "policy_is_production_evidence": False,
            "trend_review_pending": as_of < start + timedelta(days=POLICY["trend_calendar_days"]),
            "limitations": ["仅核验显式输入的内容一致性，未访问生产或证明证据真实性/独立收件。",
                            "日志完整性/人工来源/部署时间为外部提供的证据声明，需Claude复核原始采样。",
                            "合成/回放最多REPLAY_OK；生产输入最多INPUTS_CONSISTENT，不认证真实性或生产稳定。",
                            "预冻结、业务SLA批准及日志完整性仅检验外部声明的时间/引用，未独立认证。",
                            "elapsed_window_mature仅表示声明的时间跨度/频次条件；日程对账仅限repository-declared，window_mature/执行覆盖保持未知。",
                            "公募日更/FOF完整业务凭证尚无生产接口，保持UNKNOWN；backup不是NAV交付。",
                            "未纳入manifest的月季频任务不代表已自然验证；14/7/2/30为本轮建议。"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--legacy-ledger", required=True)
    parser.add_argument("--ledger", action="append", required=True, help="explicit source_id=path; repeatable")
    parser.add_argument("--as-of", required=True, help="fixed timezone-aware observation cutoff")
    args = parser.parse_args(argv)
    try:
        raw = read(args.manifest)
        if sha(raw) != args.manifest_sha256:
            raise ValueError("frozen_manifest_sha256_mismatch")
        plan = json.loads(raw)
        root = Path(args.observations).absolute().parent
        try:
            observed_raw = read(args.observations)
            observed = json.loads(observed_raw)
        except (OSError, ValueError) as exc:
            observed_raw = b""
            observed = {"dataset": plan.get("dataset"), "runs": [], "read_error": str(exc)}
        ledgers = {}
        for value in args.ledger:
            name, path = value.split("=", 1)
            if not name or name in ledgers:
                raise ValueError("duplicate_or_empty_source_id")
            ledgers[name] = Path(path)
        payload = assess(plan, observed, root, ledgers, Path(args.legacy_ledger), stamp(args.as_of))
        payload.update(manifest_sha256=sha(raw), observations_sha256=sha(observed_raw),
                       manifest_path=args.manifest, observations_path=args.observations)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        payload = {"verdict": "UNKNOWN", "dataset": "unknown", "evidence_scope": "unknown", "production_stability": "NOT_CERTIFIED",
                   "denominator_completeness": "unknown", "execution_coverage_satisfied": None,
                   "denominator_scope": "repository-declared; actual systemd deployment NOT_VERIFIED",
                   "input_error": str(exc), "business_account": {"expected_slots": None}}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if payload["verdict"] == "FAIL" else 0 if payload["verdict"] in {"REPLAY_OK", "INPUTS_CONSISTENT"} else 2


if __name__ == "__main__":
    sys.exit(main())
