"""Actual CLI controls; only explicit temporary synthetic files, no business imports."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.tests.test_delivery_evidence_20261107 import ROOT, build_hook_fixture
from scripts import delivery_evidence as de


class DeliveryEvidenceCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-delivery-cli-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, _, self.session, _ = build_hook_fixture(self.root)
        # Selection is the test's explicit setup, never the CLI's responsibility.
        self.paths = {r["stage"]: p for p in self.root.glob("data/ops_delivery/receipts/*/*/*.json")
                      for r in [de.read_receipt(p)]}

    def pin(self, stage):
        return hashlib.sha256(self.paths[stage].read_bytes()).hexdigest()

    def arguments(self):
        return ["verify-local-backtest", "--data-root", str(self.root), "--session-date", self.session,
                "--producer-receipt", str(self.paths["backtest"]), "--producer-sha256", self.pin("backtest"),
                "--publication-receipt", str(self.paths["publish"]), "--publication-sha256", self.pin("publish"),
                "--stats", str(self.root / "static-site/data/signal_kelly_backtest.json"),
                "--trades", str(self.root / "static-site/data/signal_kelly_trades.json")]

    def run_cli(self, arguments, enabled="1", script=False):
        command = ([sys.executable, str(ROOT / "scripts/delivery_evidence.py")] if script else
                   [sys.executable, "-m", "scripts.delivery_evidence"])
        env = {"OPS_DELIVERY_EVIDENCE_ENABLED": enabled, "PYTHONDONTWRITEBYTECODE": "1",
               "PATH": os.defpath, "LC_ALL": "C"}
        return subprocess.run(command + arguments, cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=10)

    def test_default_disabled_does_not_read_explicit_missing_paths(self):
        args = self.arguments()
        args[args.index("--producer-receipt") + 1] = str(self.root / "absent.json")
        before = set(self.root.glob("data/ops_delivery/receipts/*/*/*.json"))
        result = self.run_cli(args, enabled="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "disabled"})
        self.assertEqual(before, set(self.root.glob("data/ops_delivery/receipts/*/*/*.json")))

    def test_real_cli_scope_success_and_ignores_latest_decoy(self):
        decoy = self.paths["backtest"].parent / "latest.json"
        decoy.write_text("not a receipt")
        result = self.run_cli(self.arguments())
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertEqual(body["stage_status"], "success")
        self.assertEqual(body["consumer_scope"], "isolated_local_reader")
        self.assertEqual(body["evidence_quality"], "strong")
        path = self.paths["backtest"].parent / (body["receipt_id"] + ".json")
        receipt = de.read_receipt(path)
        self.assertEqual(receipt["consumer_witness"]["producer_receipt_id"], self.paths["backtest"].stem)

    def test_direct_script_namespace_matches_actual_binding(self):
        result = self.run_cli(self.arguments(), script=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["consumer_scope"], "isolated_local_reader")

    def test_bad_content_pin_and_relative_path_not_accepted(self):
        args = self.arguments()
        args[args.index("--producer-sha256") + 1] = "0" * 64
        before = set(self.root.glob("data/ops_delivery/receipts/*/*/*.json"))
        result = self.run_cli(args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "unknown")
        self.assertEqual(before, set(self.root.glob("data/ops_delivery/receipts/*/*/*.json")))
        args = self.arguments()
        args[args.index("--stats") + 1] = "relative.json"
        result = self.run_cli(args)
        self.assertEqual(result.returncode, 2)
        self.assertIn("absolute path", result.stderr)

    def test_missing_publication_and_unknown_code_are_not_success(self):
        args = self.arguments()
        args[args.index("--publication-receipt") + 1] = str(self.root / "absent.json")
        result = self.run_cli(args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "unknown")
        (self.root / "data/ops_delivery/producer-identity.json").unlink()
        result = self.run_cli(self.arguments())
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["stage_status"], "unknown")

    def test_actual_content_conflict_and_wrong_artifact_scope(self):
        trades = self.root / "static-site/data/signal_kelly_trades.json"
        trades.write_text('{"fields":[],"quadrants":{}}')
        result = self.run_cli(self.arguments())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["stage_status"], "failure")
        args = self.arguments()
        args[args.index("--trades") + 1] = str(self.root / "signal_kelly_trades_sdc.json")
        result = self.run_cli(args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "unknown")

    def test_binding_candidate_is_unreviewed_read_only_and_pinned(self):
        private = self.root / "data/ops_delivery"
        approved = private / "producer-identity.json"
        before = approved.read_bytes()
        result = self.run_cli(["binding-candidate", "--data-root", str(self.root), "--code-sha", "a" * 40,
                               "--receipt", str(self.paths["backtest"]), self.pin("backtest"),
                               "--receipt", str(self.paths["consumer"]), self.pin("consumer")])
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(result.stdout)
        self.assertFalse(body["reviewed"])
        self.assertEqual(body["schema"], "trade-producer-identity-v1")
        self.assertEqual(set(body["loaded_module_sha256"]),
                         {de.read_receipt(self.paths[s])["code_identity"]["module_sha256"] for s in ("backtest", "consumer")})
        self.assertEqual(approved.read_bytes(), before)
        result = self.run_cli(["binding-candidate", "--data-root", str(self.root), "--code-sha", "a" * 40,
                               "--receipt", str(self.paths["backtest"]), "0" * 64])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(approved.read_bytes(), before)

    def test_fifo_input_is_unknown_without_blocking(self):
        fifo = self.root / "fifo.json"
        os.mkfifo(fifo, 0o600)
        args = self.arguments()
        args[args.index("--producer-receipt") + 1] = str(fifo)
        result = self.run_cli(args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
