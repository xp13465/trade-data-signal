"""Offline native-format fixtures, never production stability evidence.

Run directly (stdlib unittest); every CLI child is guarded before execution.
The receipt adapter is also exercised with the actual existing metadata producer.
"""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_codex_alert_all_groups_20261106 import GUARD

SCRIPTS = Path(__file__).resolve().parents[1]
HEAD = "49fe9bea75d6b2106445a8686a36fc3d51005abc"
START, END = "2026-11-01T00:00:00+08:00", "2026-11-15T00:00:00+08:00"
FROZEN = "2026-10-31T00:00:00+08:00"
CHANNELS = ["email", "feishu", "telegram"]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def row(**extra):
    value = {"ts": "2026-11-01 12:00:00", "tree": "/fixture", "tier": "warning",
             "key": "native-dedup-key", "subject": "[告警] unit 异常", "source": "notify.py", "group": "alert",
             "channels": dict.fromkeys(CHANNELS, True), "attempt_id": "send-1", "attempted_channels": CHANNELS,
             "ops_event_refs": [{"key": "schedule/task/condition/run-1", "event_id": "episode-1", "phase": "active", "source_run": "run-1"}]}
    value.update(extra)
    return value


class AccountingCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sandbox = tempfile.TemporaryDirectory(prefix="quiet-accounting-")
        cls.base = Path(cls.sandbox.name).resolve()
        (cls.base / "sitecustomize.py").write_text(GUARD)
        cls.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(cls.base), "REPO": str(cls.base / "repo"),
                   "TMPDIR": str(cls.base), "PYTHONPATH": str(cls.base) + os.pathsep + str(SCRIPTS),
                   "PYTHONDONTWRITEBYTECODE": "1", "TEST_SANDBOX": str(cls.base), "LC_ALL": "C", "TZ": "UTC"}
        for code in ["import socket; socket.socket()", "import socket; socket.getaddrinfo('invalid.example',443)",
                     "import subprocess; subprocess.run(['forbidden'])", "import os; os.system('forbidden')",
                     "open('/forbidden/.env')", "open('/forbidden/output','w')"]:
            p = cls.child(["-c", code])
            if p.returncode != 97 or "EGRESS_TRAP:" not in p.stderr:
                raise AssertionError(p)
        print("EGRESS_POSITIVE_CONTROL: 6/6 blocked before accounting CLI", flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.sandbox.cleanup()

    @classmethod
    def child(cls, args):
        return subprocess.run([sys.executable, "-B", *args], cwd=cls.base, env=cls.env,
                              text=True, capture_output=True, timeout=12)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.base)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put("deployment.txt", b"offline retained deployment capture; synthetic\n")
        self.plan = {"schema": "ops-stability-plan-v1", "dataset": "synthetic", "status": "frozen",
                     "generated_at": FROZEN, "frozen_at": FROZEN, "window_start": START, "window_end": END,
                     "deployment": {"code_ref": HEAD, "config_sha256": sha(b"ops-business-v1"), "verified_at": FROZEN,
                                    "evidence_sha256": sha((self.root / "deployment.txt").read_bytes())},
                     "slots": [], "trading_dates": ["2026-11-%02d" % i for i in (2, 3, 4, 5, 6, 9, 10)],
                     "notification_sources": [{"id": "native", "channels": CHANNELS}]}
        self.obs = {"dataset": "synthetic", "deployment_evidence": "deployment.txt", "runs": [], "notification_coverage": {}}
        self.obs["event_states"] = {}
        for name, at in (("before", START), ("after", END)):
            path = self.put("alert-state-" + name + ".json", {})
            self.obs["event_states"][name] = {"path": path.name, "captured_at": at, "sha256": sha(path.read_bytes())}
        self.ledger([])
        self.put("legacy.jsonl", b"")
        for i in range(14):
            day = (date(2026, 11, 1) + timedelta(days=i)).isoformat()
            slot = {"slot_id": "overfit-" + day, "task_id": "trade-overfit-monitor", "object_id": "overfit",
                    "frequency": "daily", "business_date": day, "scheduled_at": day + "T08:00:00+08:00",
                    "deadline": day + "T09:00:00+08:00", "coverage": ["overfit_monitor.json", "overfit_monitor_ext.json"],
                    "deadline_basis": {"kind": "business_contract", "source": "fixture-only-approved-contract", "approved_at": FROZEN},
                    "public_targets": {name: ["https://fixture.invalid/" + name] for name in ("overfit_monitor.json", "overfit_monitor_ext.json")}}
            slot["coverage_sha256"] = sha(canonical(sorted(slot["coverage"])))
            self.plan["slots"].append(slot)
            run_id, invocation = "run-%d" % i, "invocation-%d" % i
            generation = "generation-%d" % i
            outputs, reads = [], []
            for name in slot["coverage"]:
                body_name = day + "-" + name
                body = canonical({"date": day, "publication_run_id": generation, "model": name})
                self.put(body_name, body)
                outputs.append({"object_id": name, "sha256": sha(body), "size": len(body)})
                reads.append({"object_id": name, "url": slot["public_targets"][name][0], "body": body_name,
                              "run_id": generation, "business_date": day, "checked_at": day + "T08:01:00+08:00", "http_status": 200})
            receipt = {"schema": "trade-delivery-receipt-v1", "receipt_id": "receipt-%d" % i,
                       "chain_id": "ops_business", "object_id": "overfit", "stage": "publish", "session_date": day,
                       "attempt_id": run_id, "batch_id": run_id, "stage_status": "success", "reason": "business_result",
                       "evaluated_at": day + "T08:03:00+08:00", "evidence_quality": "strong",
                       "producer_time": {"started_at": slot["scheduled_at"], "completed_at": day + "T08:02:00+08:00"},
                       "code_identity": {"sha": HEAD}, "config_identity": {"sha256": sha(b"ops-business-v1")},
                       "inputs": [{"object_id": "loaded_source", "sha256": sha(b"[]"), "size": 2, "identity_kind": "loaded_object"}],
                       "outputs": outputs, "counts": {"expected": 2, "validated": 2},
                       "consumer_witness": {"scope": "ops-business-v1", "rule_version": "ops-business-v1", "invocation_id": invocation,
                                            "valid_until": day + "T23:00:00+08:00", "confirmed": deepcopy(outputs), "publication_run_id": generation}}
            self.put(day + "-receipt.json", receipt)
            self.put(day + "-coverage.json", slot["coverage"])
            self.put(day + "-show.txt", ("InvocationID=" + invocation + "\nActiveState=inactive\nSubState=dead\nResult=success\nExecMainStatus=0\n").encode())
            self.obs["runs"].append({"slot_id": slot["slot_id"], "receipt": day + "-receipt.json", "journal": day + "-show.txt",
                                     "coverage": day + "-coverage.json", "origin": "timer", "manual_intervention": False,
                                     "upstream_failure": False, "journal_complete": True, "public_reads": reads})

    def put(self, name, value):
        path = self.root / name
        path.write_bytes(value if isinstance(value, bytes) else canonical(value))
        return path

    def ledger(self, rows, tail=b""):
        path = self.put("native.jsonl", b"".join(canonical(r) + b"\n" for r in rows) + tail)
        self.obs["notification_coverage"]["native"] = {"complete": True, "includes_failed_attempts": True, "channels": CHANNELS,
                                                       "start": START, "end": END, "sha256": sha(path.read_bytes())}
        return path

    def receipt(self, index=0):
        return json.loads((self.root / self.obs["runs"][index]["receipt"]).read_bytes())

    def save_receipt(self, r, index=0):
        self.put(self.obs["runs"][index]["receipt"], r)

    def cli(self, as_of=END, pin=None):
        if as_of != END and self.obs.get("event_states", {}).get("after", {}).get("captured_at") == END:
            self.obs["event_states"]["after"]["captured_at"] = as_of
        manifest = self.put("manifest.json", self.plan)
        obs = self.put("observations.json", self.obs)
        before = {str(p): sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        p = self.child([str(SCRIPTS / "ops_stability_acceptance.py"), "--manifest", str(manifest),
                        "--manifest-sha256", pin or sha(manifest.read_bytes()), "--observations", str(obs),
                        "--legacy-ledger", str(self.root / "legacy.jsonl"), "--ledger", "native=" + str(self.root / "native.jsonl"), "--as-of", as_of])
        self.assertNotIn("EGRESS_TRAP:", p.stderr)
        self.assertIn(p.returncode, (0, 1, 2), p.stderr)
        self.assertEqual(before, {str(p): sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()})
        result = json.loads(p.stdout)
        self.assertEqual(result["production_stability"], "NOT_CERTIFIED")
        return result

    def strict(self, rows):
        path = self.ledger(rows)
        p = self.child([str(SCRIPTS / "alert_noise_count.py"), "--ledger", str(path), "--date", "2026-11-01", "--json", "--all-groups"])
        self.assertNotIn("EGRESS_TRAP:", p.stderr)
        self.assertIn(p.returncode, (0, 2), p.stderr)
        return json.loads(p.stdout)["outbound_account"]

    def test_complete_synthetic_and_replay_never_production_acceptance(self):
        for dataset, verdict in [("synthetic", "REPLAY_OK"), ("replay", "REPLAY_OK"), ("production", "INPUTS_CONSISTENT"), ("unknown", "UNKNOWN")]:
            with self.subTest(dataset=dataset):
                self.plan["dataset"] = self.obs["dataset"] = dataset
                result = self.cli()
                self.assertEqual(result["verdict"], verdict, result.get("input_problems"))
                self.assertEqual(result["dataset"], dataset)
                self.assertEqual(result["business_account"]["counts"]["consistent"], 14)

    def test_no_receipts_or_boolean_success_keep_denominator_unknown(self):
        self.obs["runs"] = [{"slot_id": s["slot_id"], "success": True} for s in self.plan["slots"]]
        result = self.cli()
        self.assertEqual(result["verdict"], "UNKNOWN")
        self.assertEqual(result["business_account"]["expected_slots"], 14)
        self.assertEqual(result["business_account"]["counts"]["unknown"], 14)
        self.obs["runs"] = []
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_window_pending_but_proven_failure_early_fail(self):
        self.obs["runs"] = self.obs["runs"][:1]
        self.assertEqual(self.cli("2026-11-01T10:00:00+08:00")["verdict"], "PENDING")
        receipt = self.receipt(); receipt.update(stage_status="failure", reason="wrong_public_bytes")
        self.save_receipt(receipt)
        self.assertEqual(self.cli("2026-11-01T10:00:00+08:00")["verdict"], "FAIL")

    def test_prefreeze_and_hash_pin_negatives(self):
        self.assertEqual(self.cli(pin="0" * 64)["verdict"], "UNKNOWN")
        for key in ("generated_at", "frozen_at"):
            old = self.plan[key]
            self.plan[key] = "2026-11-01T01:00:00+08:00"
            self.assertEqual(self.cli()["verdict"], "UNKNOWN")
            self.plan[key] = old
        self.plan["status"] = "draft"
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.plan["slots"] = []
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_draft_or_process_limit_not_business_sla(self):
        for kind in ("process_limit", "draft"):
            self.plan["slots"][0]["deadline_basis"] = {"kind": kind, "source": "systemd RuntimeMaxSec=2100"}
            self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.plan.update(status="draft", frozen_at=None, trading_dates=[],
                         deployment={"code_ref": None, "config_sha256": None, "evidence_sha256": None, "verified_at": None})
        self.obs["runs"] = []
        p = self.cli()
        self.assertEqual((p["verdict"], p["business_account"]["expected_slots"]), ("UNKNOWN", 14))

    def test_native_fund_interface_missing_and_backup_not_nav(self):
        for object_id in ("public_fund_daily", "fof_nav"):
            self.plan["slots"][0]["object_id"] = object_id
            r = self.receipt(); r.update(object_id="backup-public_fund", stage="restore")
            self.save_receipt(r)
            self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.plan["slots"][0].update(coverage=None, public_targets=None)
        self.assertEqual(self.cli()["business_account"]["expected_slots"], 14)

    def test_missing_native_evidence_matrix(self):
        original = deepcopy(self.obs["runs"][0])
        for field in ("receipt", "journal", "coverage", "public_reads", "origin", "manual_intervention", "upstream_failure", "journal_complete"):
            with self.subTest(field=field):
                self.obs["runs"][0] = deepcopy(original)
                del self.obs["runs"][0][field]
                self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_identity_date_generation_and_rule_mismatches(self):
        original = self.receipt()
        mutations = [("object_id", "turnover"), ("session_date", "2026-10-31"), ("code_identity", {"sha": "a" * 40}),
                     ("config_identity", {"sha256": "b" * 64}), ("stage", "restore")]
        for key, value in mutations:
            with self.subTest(key=key):
                r = deepcopy(original); r[key] = value; self.save_receipt(r)
                self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        for key, value in [("invocation_id", "other"), ("rule_version", "future"), ("publication_run_id", None), ("valid_until", FROZEN)]:
            r = deepcopy(original); r["consumer_witness"][key] = value; self.save_receipt(r)
            self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.save_receipt(original)
        self.obs["runs"][0]["public_reads"][0]["run_id"] = original["attempt_id"]
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")  # overfit publication_run_id != attempt_id

    def test_coverage_output_and_public_negative_controls(self):
        coverage = self.obs["runs"][0]["coverage"]
        self.put(coverage, ["unexpected.json"])
        self.assertEqual(self.cli()["verdict"], "FAIL")
        self.put(coverage, self.plan["slots"][0]["coverage"])
        r = self.receipt(); r["counts"]["validated"] = 1; self.save_receipt(r)
        self.assertEqual(self.cli()["verdict"], "FAIL")
        r["counts"]["validated"] = 2; self.save_receipt(r)
        self.put(self.obs["runs"][0]["public_reads"][0]["body"], b"WRONG PUBLIC BODY")
        self.assertEqual(self.cli()["verdict"], "FAIL")

    def test_late_manual_and_upstream_not_removed(self):
        r = self.receipt(); r["producer_time"]["completed_at"] = "2026-11-01T09:01:00+08:00"
        r["evaluated_at"] = "2026-11-01T09:02:00+08:00"; self.save_receipt(r)
        self.assertEqual(self.cli()["verdict"], "FAIL")
        self.obs["runs"][0]["manual_intervention"] = True
        self.obs["runs"][0]["upstream_failure"] = True
        result = self.cli()
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["business_account"]["expected_slots"], 14)
        self.assertTrue(result["business_account"]["slots"][0]["upstream_failure_observed"])

    def test_same_run_poll_dedup_and_retry_retains_failure_evidence(self):
        good = self.receipt()
        failure = deepcopy(good); failure.update(receipt_id="earlier-failure", stage_status="failure", reason="upstream_failure", evaluated_at="2026-11-01T08:01:00+08:00")
        failure["producer_time"]["completed_at"] = "2026-11-01T08:01:00+08:00"
        self.put("earlier.json", failure)
        old = deepcopy(self.obs["runs"][0]); old.update(receipt="earlier.json", upstream_failure=True)
        self.obs["runs"].insert(0, old)
        result = self.cli()
        slot = result["business_account"]["slots"][0]
        self.assertEqual((result["verdict"], slot["run_count"], len(slot["observations"])), ("REPLAY_OK", 1, 2))
        self.assertTrue(slot["upstream_failure_observed"])
        failure["attempt_id"] = failure["batch_id"] = "prior-distinct-run"
        self.put("earlier.json", failure)
        result = self.cli()
        self.assertEqual(result["business_account"]["slots"][0]["run_count"], 2)
        self.assertEqual(result["business_account"]["expected_slots"], 14)
        # A newer unknown observation cannot erase an earlier proved failure.
        good["stage_status"] = "unknown"; self.put(self.obs["runs"][1]["receipt"], good)
        self.assertEqual(self.cli()["verdict"], "FAIL")

    def test_reobserved_old_success_cannot_clear_new_failed_invocation(self):
        good = self.receipt()
        good["evaluated_at"] = "2026-11-01T08:30:00+08:00"
        self.save_receipt(good)
        failure = deepcopy(good)
        failure.update(receipt_id="later-failure", attempt_id="later-run", batch_id="later-run",
                       stage_status="failure", reason="upstream_failure", evaluated_at="2026-11-01T08:13:00+08:00")
        failure["producer_time"] = {"started_at": "2026-11-01T08:10:00+08:00", "completed_at": "2026-11-01T08:12:00+08:00"}
        self.put("later-failure.json", failure)
        observation = deepcopy(self.obs["runs"][0]); observation["receipt"] = "later-failure.json"
        self.obs["runs"].append(observation)
        result = self.cli()
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["business_account"]["expected_slots"], 14)

    def test_duplicate_conflict_and_manual_not_hidden(self):
        duplicate = deepcopy(self.obs["runs"][0]); duplicate["journal_complete"] = False
        self.obs["runs"].append(duplicate)
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        duplicate["manual_intervention"] = True
        self.assertEqual(self.cli()["verdict"], "FAIL")

    def test_weekly_two_natural_rounds_and_missing_evidence(self):
        self.plan["slots"][0]["frequency"] = "weekly"
        self.assertEqual(self.cli()["verdict"], "PENDING")
        self.plan["slots"][7]["frequency"] = "weekly"
        self.assertEqual(self.cli()["verdict"], "REPLAY_OK")
        self.obs["runs"][7]["receipt"] = "missing.json"
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_declared_subset_never_certifies_schedule_coverage(self):
        self.plan["slots"] = self.plan["slots"][:1]
        self.obs["runs"] = self.obs["runs"][:1]
        result = self.cli()
        self.assertEqual(result["business_account"]["expected_slots"], 1)
        self.assertEqual(result["verdict"], "REPLAY_OK")
        self.assertTrue(result["elapsed_window_mature"])
        self.assertIsNone(result["window_mature"])
        self.assertIsNone(result["execution_coverage_satisfied"])
        self.assertEqual(result["denominator_completeness"], "unknown")
        self.assertTrue(result["declared_subset"])

    def test_same_week_duplicate_slot_and_cross_slot_reused_run(self):
        self.plan["slots"][1]["frequency"] = self.plan["slots"][2]["frequency"] = "weekly"
        self.assertEqual(self.cli()["verdict"], "PENDING")
        for s in self.plan["slots"]:
            s["frequency"] = "daily"
        duplicate = deepcopy(self.plan["slots"][0]); duplicate["slot_id"] = "duplicate"
        self.plan["slots"].append(duplicate)
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.plan["slots"].pop()
        r = self.receipt(1); r["attempt_id"] = r["batch_id"] = self.receipt()["attempt_id"]
        self.save_receipt(r, 1)
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_public_corruption_survives_newer_success_and_draft(self):
        earlier = deepcopy(self.obs["runs"][0]); good = self.receipt()
        earlier["public_reads"][0]["body"] = "corrupt-body.json"
        self.put("corrupt-body.json", b"corrupt")
        self.obs["runs"].insert(0, earlier)
        good.update(receipt_id="retry", attempt_id="retry", batch_id="retry", evaluated_at="2026-11-01T08:04:00+08:00")
        self.put("retry.json", good); self.obs["runs"][1]["receipt"] = "retry.json"
        self.assertEqual(self.cli()["verdict"], "FAIL")
        self.plan["status"] = "draft"
        self.assertEqual(self.cli()["verdict"], "FAIL")

    def test_manual_with_no_receipt_cannot_be_unknown_or_green(self):
        self.obs["runs"][0].update(receipt="missing", origin="manual", manual_intervention=True)
        self.assertEqual(self.cli()["verdict"], "FAIL")

    def test_deployment_capture_missing_or_tampered(self):
        self.put("deployment.txt", b"tampered")
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        del self.obs["deployment_evidence"]
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_future_ledger_unknown_severity_conflict_and_unknown_group(self):
        self.ledger([row(ts="2026-11-16 12:00:00")])
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.ledger([row(group=None)])
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.ledger([row(tier="critical", noise_class="routine_notice")])
        p = self.cli()
        self.assertEqual((p["verdict"], p["known_routine_channel_successes"]), ("UNKNOWN", 0))

    def test_bad_shapes_stay_unknown(self):
        for value in ([], True, "bad"):
            self.obs["runs"] = value
            self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        strict = self.strict([row(ops_event_refs=[None, {"key": [], "event_id": "id"}], attempted_channels=[[]], channels=None)])
        self.assertTrue(strict["uncertainties"])

    def test_notification_coverage_no_zero_fault_pass(self):
        self.obs["notification_coverage"] = {}
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.ledger([], b"bad-json\n[]\n")
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.ledger([row(ts="bad timestamp")])
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.ledger([]); (self.root / "native.jsonl").unlink()
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_all_group_routing_does_not_reduce_all_channel_account(self):
        for group in ("alert", "report", "follow", "agent_done"):
            self.ledger([row(group=group, tier="notice", noise_class="routine_notice", channels={"email": True, "telegram": True, "feishu": False}, attempted_channels=["email", "telegram"])])
            result = self.cli()
            self.assertEqual((result["verdict"], result["known_routine_channel_successes"]), ("FAIL", 2))
            self.assertIsNone(result["legacy_alert_account"]["totals"]["pass"])

    def test_sent_deferred_and_info_logged_are_not_outbound(self):
        # Captured native result shapes: baseline-notify-results.json initial/healthy.
        for metadata in ({"deferred": True, "defer_status": "enqueued", "tier": "warning"}, {"info_logged": True, "tier": "info"}):
            channels = dict.fromkeys(CHANNELS, False); channels.update(metadata)
            strict = self.strict([row(status="sent", channels=channels, attempted_channels=[])])
            self.assertEqual(sum(c["declared_success_rows"] for c in strict["channels"].values()), 0)
            self.assertEqual(set(strict["channels"]), set(CHANNELS))
            self.assertIsNone(strict["independently_received"])

    def test_old_fields_unknown_refs_and_attempts_remain_unknown(self):
        cases = [{"attempt_id": None}, {"ops_event_refs": [{"key": "k", "event_id": "e", "phase": "future", "source_run": "r"}]},
                 {"ops_event_refs": [{"key": "k", "phase": "recovery", "source_run": "r"}]}, {"attempted_channels": None},
                 {"attempted_channels": ["deferred"]}]
        for extra in cases:
            with self.subTest(extra=extra):
                strict = self.strict([row(**extra)])
                self.assertTrue(strict["uncertainties"])
                self.assertIsNone(strict["pass"])
        old = row(); [old.pop(k) for k in ("attempt_id", "attempted_channels", "ops_event_refs")]
        self.ledger([old])
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_active_nullable_run_and_legacy_open_contract(self):
        strict = self.strict([row()])
        self.assertEqual(strict["uncertainties"], [])
        r = row(); r["ops_event_refs"][0]["source_run"] = None
        strict = self.strict([r])
        self.assertEqual(strict["known_event_ids"], ["episode-1"])
        self.assertEqual(strict["uncertainties"][0]["reasons"], ["source_run_unknown"])
        r["ops_event_refs"][0].update(phase="open", source_run="run1")
        self.assertIn("unknown_event_phase", self.strict([r])["uncertainties"][0]["reasons"])

    def test_distinct_attempt_duplicate_first_fails_not_duplicate_ledger_or_new_event(self):
        first = row()
        self.ledger([first, deepcopy(first)])
        p = self.cli()
        self.assertEqual((p["verdict"], p["duplicate_event_channel_acceptances"]), ("REPLAY_OK", 0))
        second = row(attempt_id="another-attempt")
        self.ledger([first, second])
        p = self.cli()
        self.assertEqual((p["verdict"], p["duplicate_event_channel_acceptances"]), ("FAIL", 3))
        second["ops_event_refs"][0]["event_id"] = "independent-event"
        self.ledger([first, second])
        p = self.cli()
        self.assertEqual((p["verdict"], p["duplicate_event_channel_acceptances"]), ("REPLAY_OK", 0))
        recurrence = p["notification_account"]["outbound_account"]["root_cause_recurrence"]
        self.assertEqual(recurrence["coverage"], "unknown")
        self.assertEqual(len(recurrence["unlabelled_event_ids"]), 2)
        first["root_cause_id"] = second["root_cause_id"] = "known-fixed-root-cause"
        strict = self.strict([first, second])
        self.assertEqual(strict["root_cause_recurrence"]["known_recurrences"][0]["recurrences"], 1)

    def test_recovery_needs_first_acceptance_and_window_state(self):
        recovery = row(ts="2026-11-01 13:00:00", attempt_id="recovery-1")
        recovery["ops_event_refs"][0]["phase"] = "recovery"
        self.ledger([recovery])
        p = self.cli()
        self.assertEqual(p["verdict"], "UNKNOWN")
        self.assertEqual(len(p["notification_lifecycle"]["unpaired_recoveries"]), 3)
        self.ledger([row(), recovery])
        self.assertEqual(len(self.cli()["notification_lifecycle"]["paired_recoveries"]), 3)
        del self.obs["event_states"]["before"]
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")
        self.ledger([])
        p = self.cli()
        self.assertEqual(p["verdict"], "UNKNOWN")
        self.assertEqual(p["notification_lifecycle"]["missed_alerts_status"], "unknown")

    def test_existing_before_state_pairs_recovery_but_only_notified_channel(self):
        recovery = row(attempt_id="recovery-1")
        recovery["ops_event_refs"][0]["phase"] = "recovery"
        self.ledger([recovery])
        state = {recovery["ops_event_refs"][0]["key"]: {"event_id": "episode-1", "status": "active", "requires_action": True,
                 "notified_event_id": "episode-1", "notified_channels": {"email": True, "feishu": False, "telegram": False}}}
        path = self.put("alert-state-before.json", state)
        self.obs["event_states"]["before"]["sha256"] = sha(path.read_bytes())
        p = self.cli()
        self.assertEqual(p["verdict"], "UNKNOWN")
        self.assertEqual(len(p["notification_lifecycle"]["paired_recoveries"]), 1)
        self.assertEqual(len(p["notification_lifecycle"]["unpaired_recoveries"]), 2)

    def test_prior_window_distinct_attempt_first_acceptance(self):
        r = row(); self.ledger([r, row(attempt_id="send-2")])
        state = {r["ops_event_refs"][0]["key"]: {"event_id": "episode-1", "status": "active", "requires_action": True,
                 "notified_event_id": "episode-1", "notified_channels": dict.fromkeys(CHANNELS, True),
                 "last_notification_attempt": {"phase": "active", "attempt_id": "before-window"}}}
        path = self.put("alert-state-before.json", state)
        self.obs["event_states"]["before"]["sha256"] = sha(path.read_bytes())
        p = self.cli()
        self.assertEqual((p["verdict"], p["duplicate_event_channel_acceptances"]), ("FAIL", 6))
        self.ledger([r])
        state[r["ops_event_refs"][0]["key"]]["last_notification_attempt"]["attempt_id"] = r["attempt_id"]
        path = self.put("alert-state-before.json", state)
        self.obs["event_states"]["before"]["sha256"] = sha(path.read_bytes())
        self.assertEqual(self.cli()["duplicate_event_channel_acceptances"], 0)

    def test_actionable_without_acceptance_is_unknown_not_zero_missed(self):
        state = {"task|condition": {"event_id": "new-event", "status": "active", "requires_action": True, "source_run": "run-1"}}
        path = self.put("alert-state-after.json", state)
        self.obs["event_states"]["after"]["sha256"] = sha(path.read_bytes())
        p = self.cli()
        self.assertEqual(p["verdict"], "UNKNOWN")
        self.assertEqual(len(p["notification_lifecycle"]["unnotified_actionable_candidates"]), 1)

    def test_update_all_precise_old_noise_but_business_completion_retained(self):
        old = row(subject="[完成] update_all 4min 11-01 12:00", tier="notice")
        for key in ("ops_event_refs", "attempt_id", "attempted_channels"):
            old.pop(key)
        strict = self.strict([old])
        self.assertEqual(strict["populations"].get("operations"), 1)
        self.assertEqual(sum(c["routine_declared_success_rows"] for c in strict["channels"].values()), 3)
        self.ledger([old]); self.assertEqual(self.cli()["verdict"], "FAIL")
        for subject in ("[完成] agent review", "[完成] update_all business report", "[完成] 日报已生成"):
            r = dict(old, subject=subject)
            strict = self.strict([r])
            self.assertEqual(strict["populations"].get("business"), 1)
        r = row(subject="[完成] ordinary business title", tier="notice")
        strict = self.strict([r])
        self.assertEqual(strict["populations"].get("operations"), 1)
        self.assertEqual(strict["uncertainties"], [])

    def test_multi_event_attempt_counts_failures_duplicates_and_conflicts(self):
        r = row()
        r["ops_event_refs"].append(dict(r["ops_event_refs"][0], event_id="second-event"))
        failed = row(attempt_id="send-2", channels=dict.fromkeys(CHANNELS, False))
        strict = self.strict([r, deepcopy(r), failed])
        self.assertEqual((len(strict["known_event_ids"]), len(strict["known_attempt_ids"])), (2, 2))
        self.assertEqual(strict["populations"]["repeated_attempt_rows"], 1)
        for c in strict["channels"].values():
            self.assertEqual((c["declared_success_rows"], c["distinct_known_successful_attempts"], c["distinct_known_attempts"], c["failed_attempt_rows"]), (2, 1, 2, 1))
        strict = self.strict([r, dict(r, channels=dict.fromkeys(CHANNELS, False))])
        self.assertIn("conflicting_attempt_id", strict["uncertainties"][0]["reasons"])

    def test_additional_declared_channel_and_missing_channel_not_zero(self):
        r = row(channels={"email": False, "feishu": False, "telegram": False, "webhook": True}, attempted_channels=["webhook"])
        strict = self.strict([r, dict(r, attempt_id="next-send")])
        self.assertEqual(strict["channels"]["webhook"]["declared_success_rows"], 2)
        self.assertEqual(strict["duplicate_event_acceptances"][0]["channel"], "webhook")
        self.assertEqual(strict["dataset"], "unknown")
        strict = self.strict([row(channels={"email": True, "feishu": True}, attempted_channels=["email", "feishu"])])
        self.assertEqual(strict["channels"]["telegram"]["result_unknown_rows"], 1)

    def test_native_ops_tier_and_unknown_transport_result(self):
        record = row(tier="ops", ops_category="operations")
        self.ledger([record])
        self.assertEqual(self.cli()["verdict"], "REPLAY_OK")
        record["channels"]["email"] = None
        strict = self.strict([record])
        email = strict["channels"]["email"]
        self.assertEqual(email["result_unknown_rows"], 1)
        self.assertEqual(email["failed_attempt_rows"], 0)
        self.assertEqual(email["declared_success_rows"], 0)
        self.ledger([record])
        self.assertEqual(self.cli()["verdict"], "UNKNOWN")

    def test_actual_metadata_producer_emits_adapter_compatible_receipt(self):
        # Actual record_result -> emit_receipt -> read_receipt; only temporary metadata.
        args = self.receipt()
        self.put("producer-args.json", args)
        code = '''import json, pathlib
from datetime import datetime
import ops_business_evidence as b
p = pathlib.Path(__import__('sys').argv[1]); r=json.loads((p/'producer-args.json').read_text())
b.now = lambda: datetime.fromisoformat(r['evaluated_at'])
b.evidence_enabled = lambda: True
import os
os.environ['OPS_DELIVERY_EVIDENCE_ENABLED']='1'
w=r['consumer_witness']
result=b.record_result(p, r['object_id'],run_id=r['attempt_id'],started_at=r['producer_time']['started_at'],
status=r['stage_status'],reason=r['reason'],inputs=r['inputs'],outputs=r['outputs'],confirmed=w['confirmed'],
expected=2,observed=2,business_date=r['session_date'],invocation_id=w['invocation_id'],code=r['code_identity']['sha'],
finished_at=r['producer_time']['completed_at'],valid_until=w['valid_until'],publication_run_id=w['publication_run_id'])
print(json.dumps(result))
'''
        p = self.child(["-c", code, str(self.root)])
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("EGRESS_TRAP:", p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "written", p.stdout)
        receipts = list((self.root / "data/ops_delivery/receipts/2026-11-01/ops_business").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        self.obs["runs"][0]["receipt"] = str(receipts[0])
        self.assertEqual(self.cli()["verdict"], "REPLAY_OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
