"""Isolated hooks/SQLite/IO only. Synthetic controls are not production benefit."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import delivery_evidence as de
from scripts import r2_export_proof as rp
from scripts.util_atomic import atomic_write_text, atomic_write_json

ROOT = Path(__file__).absolute().parents[2]


def function_ast(path, names, namespace):
    """Load original functions without importing business modules/entrypoints."""
    tree = ast.parse((ROOT / path).read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / path), "exec"), namespace)
    return namespace


def receipt_pairs(root):
    return [(hashlib.sha256(p.read_bytes()).hexdigest(), de.read_receipt(p))
            for p in (root / "data/ops_delivery/receipts").glob("*/*/*.json")]


def build_hook_fixture(root, empty=False):
    """Real original backtest main AST -> real proof -> real isolated reader.

    Raw engine inputs and stats are synthetic; IO, hooks, schema, projection,
    byte proof, immutable publication, and normalizer are the actual functions.
    No business module imports, source DB, external command, notify or network.
    """
    from ops.monitoring.tests.test_benefits import fixture
    control, _ = fixture()
    session = datetime.now(timezone.utc).astimezone(de.ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    data = root / "static-site/data"
    data.mkdir(parents=True)
    ns = dict(__name__="isolated_backtest", ROOT=str(root), os=os, sys=sys, json=json,
              argparse=argparse, datetime=datetime, timedelta=de.__dict__.get("timedelta"),
              evidence_stage=de.evidence_stage, capture_loaded=de.capture_loaded,
              capture_event=de.capture_event, capture_write=de.capture_write,
              validate_backtest_outputs=de.validate_backtest_outputs,
              atomic_write_text=atomic_write_text,
              _etf_daily_today_ready=lambda: (True, session.replace("-", ""), 1.0),
              KELLY_UNIQUE_EXPORT=False, KELLY_BUY_NEXTDAY=1, BUY_AMOUNT=10000, HOLD_DAYS=5,
              SELL_MODES={"A": {}, "B": {}}, PERIODS={"all": {"label": "all", "cutoff": "0"}},
              RATING_HIGH=60, RATING_MID=40, COMMISSION_RATE=0.0, SLIPPAGE=0.0,
              MIN_COMMISSION=0.0, TRANSFER_FEE_RATE_SH=0.0, BUY_SIGNALS=["buy"],
              SIG_QUAD_MAP={}, MARKET_QUAD_MAP={}, QUADRANT_META={"q": {"label": "q", "desc": "q"}},
              TRADE_FIELDS=["signal_date", "index_id", "real_buy_date"],
              _guidance=lambda *a: "fixture", _compute_stats=lambda rows, period: {"n": len(rows), "half_kelly": 0, "win_rate": 0})
    function_ast("scripts/signal_kelly_backtest.py", {"main", "_build_outputs"}, ns)
    quadrants = {"q": {"A": [{"signal_date": session.replace("-", ""), "index_id": "fixture", "real_buy_date": "unknown"}], "B": []}}
    if empty:
        quadrants["q"]["A"] = []
    ns["compute"] = lambda: ns["_build_outputs"](quadrants)
    # Binding explicitly simulates a reviewed installation; no fake production SHA.
    binding = {"schema": "trade-producer-identity-v1", "reviewed": True, "code_sha": "a" * 40,
               "loaded_module_sha256": [de.loaded_code_identity(ns["main"].__wrapped__, root)["module_sha256"],
                                        de.loaded_code_identity(rp.write_run_proof.__wrapped__, root)["module_sha256"],
                                        de.loaded_code_identity(de.verify_local_backtest_consumer, root)["module_sha256"]]}
    private = root / "data/ops_delivery"
    private.mkdir(parents=True, mode=0o700)
    manifest = private / "producer-identity.json"
    manifest.write_text(json.dumps(binding))
    manifest.chmod(0o600)
    with patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1", "REPO": str(root)}), \
         patch.object(sys, "argv", ["backtest", "--output", str(data / "signal_kelly_backtest.json"), "--skip-parts"]), \
         redirect_stdout(io.StringIO()):
        ns["main"]()
        producer_path = next(p for p in private.glob("receipts/*/*/*.json") if de.read_receipt(p)["stage"] == "backtest")
        outputs = {name: rp.output_record((data / name).read_bytes()) for name in
                   ("signal_kelly_backtest.json", "signal_kelly_trades.json")}
        rp.write_run_proof(root / "proof.json", "fixture-export-run", root / "static-site", outputs)
        publication_path = next(p for p in private.glob("receipts/*/*/*.json") if de.read_receipt(p)["stage"] == "publish")
        de.verify_local_backtest_consumer(data_root=root, producer_receipt=producer_path,
                                         publication_receipt=publication_path,
                                         artifact_paths={name: data / name for name in outputs}, session_date=session)
    pairs = receipt_pairs(root)
    by_stage = {r["stage"]: r for _, r in pairs}
    chain = "backtest_publish_consume"
    policy = {"inventory_complete": True, "inventory_id": "fixture-local-delivery",
              "code_sha": "a" * 40, "config_sha": "b" * 64,
              "deadline_at": de.utc_now(), "batches": [f"{chain}:{session}"],
              "required": [], "edges": []}
    for stage, oid, inputs in [("backtest", "backtest_parts_and_consumer", ["backtest_input"]),
                               ("publish", "publication_proof_and_pending", ["signal_kelly_trades.json"]),
                               ("consumer", "backtest_parts_and_consumer", ["signal_kelly_trades.json"])]:
        req = {"stage": stage, "object_id": oid, "inputs": inputs,
               "outputs": ["signal_kelly_backtest.json", "signal_kelly_trades.json"],
               "config_sha": by_stage[stage]["config_identity"]["sha256"], "allow_empty": False}
        if stage == "consumer":
            req["consumer_scope"] = "isolated_local_reader"
        policy["required"].append(req)
    for a, b in zip(policy["required"], policy["required"][1:]):
        policy["edges"].append({"from": [a["stage"], a["object_id"]], "to": [b["stage"], b["object_id"]],
                                "object_id": "signal_kelly_trades.json"})
    # Normalize takes already-validated control, so replace only its synthetic session policy.
    control["sessions"] = [{"date": session, "chains": {chain: policy}}]
    control["calendar"]["trading_days"] = [session]
    control["calendar"]["sha256"] = hashlib.sha256(json.dumps([session], separators=(',', ':')).encode()).hexdigest()
    return control, pairs, session, policy


class DeliveryEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # Unconditional traps: tests must never send notifications or touch network.
        self.addCleanup(patch.stopall)
        patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")).start()
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess/notify forbidden")).start()
        patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "0"}).start()

    def emit(self, **kwargs):
        defaults = dict(data_root=self.root, stage="plan", chain_id="market_signal_freeze_plan",
                        object_id="nextday_plan", session_date="20261106", enabled=True,
                        evaluated_at="2026-11-06T13:00:00+00:00", receipt_id="same")
        defaults.update(kwargs)
        return de.emit_receipt(**defaults)

    def test_disabled_does_not_examine_values_or_write(self):
        self.assertEqual(self.emit(enabled=None, inputs=object()), {"status": "disabled"})
        self.assertFalse((self.root / "data").exists())

    def test_private_atomic_idempotent_and_conflict(self):
        first = self.emit()
        self.assertEqual(first["status"], "written")
        path = next(self.root.glob("data/ops_delivery/receipts/*/*/*.json"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.emit()["status"], "idempotent")
        before = path.read_bytes()
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.emit(reason="different")["status"], "metadata_failure")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(de.read_receipt(path)["batch_id"], "market_signal_freeze_plan:2026-11-06")

    def test_concurrent_exclusive_publication(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _: self.emit()["status"], range(16)))
        self.assertEqual(statuses.count("written"), 1)
        self.assertEqual(statuses.count("idempotent"), 15)

    def test_interrupt_before_publish_leaves_no_final(self):
        with patch.object(de.os, "link", side_effect=OSError("interrupted")), redirect_stderr(io.StringIO()):
            self.assertEqual(self.emit()["status"], "metadata_failure")
        self.assertEqual(list(de.iter_receipts(self.root)), [])
        self.assertEqual(list(self.root.glob("data/ops_delivery/receipts/*/*/.receipt-*")), [])

    def test_oversize_and_symlink_rejected(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(self.emit(reason="x" * de.MAX_BYTES)["status"], "metadata_failure")
        self.assertFalse((self.root / "data").exists())
        self.emit()
        path = next(self.root.glob("data/ops_delivery/receipts/*/*/*.json"))
        dest = self.root / "other"
        dest.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(dest)
        with self.assertRaises(OSError):
            de.read_receipt(path)

    def test_loaded_identity_is_actual_value_not_post_read_file(self):
        path = self.root / "input.json"
        path.write_text('{"x":1}')
        loaded = json.loads(path.read_bytes())
        identity = de.identity_for_loaded("input", loaded)
        path.write_text('{"x":2}')
        self.assertEqual(identity, dict(identity, sha256=de.identity_for_loaded("input", loaded)["sha256"]))
        self.assertNotEqual(identity["sha256"], de.identity_for_loaded("input", json.loads(path.read_bytes()))["sha256"])

    def test_work_budget_and_exception_semantics(self):
        marker = RuntimeError("original")
        @de.evidence_stage(data_root=lambda: self.root, stage="signal", chain_id="market_signal_freeze_plan", object_id="signal_daily")
        def run(raises=False):
            for _ in range(300):
                de.capture_loaded("same", {"x": 1})
            if raises:
                raise marker
            return 123
        with patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1"}), redirect_stderr(io.StringIO()):
            self.assertEqual(run(), 123)
            with self.assertRaises(RuntimeError) as caught:
                run(True)
        self.assertIs(caught.exception, marker)
        self.assertTrue(all(r["stage_status"] == "unknown" for r in de.iter_receipts(self.root)))

    def test_same_object_different_reads_is_weak_not_duplicate(self):
        @de.evidence_stage(data_root=lambda: self.root, stage="signal", chain_id="market_signal_freeze_plan", object_id="signal_daily")
        def run():
            de.capture_loaded("index_daily", [1], query_scope="a")
            de.capture_loaded("index_daily", [2], query_scope="b")
        with patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1"}):
            run()
        receipt = next(de.iter_receipts(self.root))
        self.assertEqual(len(receipt["inputs"]), 1)
        self.assertEqual(receipt["inputs"][0]["quality"], "weak")

    def test_sqlite_logical_rows_see_wal_snapshot(self):
        path = self.root / "fixture.db"
        db = sqlite3.connect(path)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE t(k PRIMARY KEY,v)")
        db.commit()
        db.execute("INSERT INTO t VALUES(1,'wal-only')")
        db.commit()
        rows = db.execute("SELECT * FROM t ORDER BY k").fetchall()
        before = de.identity_for_loaded("t", rows)
        db.execute("UPDATE t SET v='different'")
        db.commit()
        self.assertNotEqual(before["sha256"], de.identity_for_loaded("t", db.execute("SELECT * FROM t").fetchall())["sha256"])
        db.close()

    def test_original_freeze_guard_fallback_and_legal_new(self):
        ns = dict(__name__="isolated_freeze", _PRUNED_UNIVERSE_N=0, _FROZEN_MISSING_EVENTS=set(),
                  _iid_in_excluded_category=lambda i: False, _signal_key=lambda d,i,s: f"{d}|{i}|{s}",
                  _freeze_fallback=lambda f,d,i: next((v for k,v in f.items() if k.startswith(f"{d}|{i}|")), None),
                  capture_event=de.capture_event)
        function_ast("scripts/signal_kelly_backtest.py", {"_resolve_etf"}, ns)
        freeze = {"20261105|i|buy": {"code": "old"}}
        be = {"i": {"code": "new"}}
        self.assertEqual(ns["_resolve_etf"]("20261105", "i", "buy_aux", be, freeze, "20261106"), ({"code": "old"}, True))
        self.assertEqual(ns["_resolve_etf"]("20261104", "i", "buy", be, freeze, "20261106"), (None, False))
        self.assertNotIn("20261104|i|buy", freeze)
        self.assertEqual(ns["_resolve_etf"]("20261106", "i", "buy", be, freeze, "20261106")[0]["code"], "new")

    def test_real_hooks_normalizer_success_missing_consumer_and_stale_writer(self):
        from ops.monitoring import benefits
        control, pairs, session, policy = build_hook_fixture(self.root)
        now = datetime.now(timezone.utc)
        chain = "backtest_publish_consume"
        batch = f"{chain}:{session}"
        outcome, reason, _ = benefits.batch_outcome(pairs, policy, batch, chain, session, now)
        self.assertEqual((outcome, reason), ("success", "verified_delivery"))
        normalized = benefits.normalize(control, pairs, chain, session, now)
        self.assertEqual(normalized["evidence"]["success"], 1)
        self.assertEqual(normalized["evidence"]["strength"], "verified")
        self.assertEqual(normalized["measurement_kind"], "synthetic")
        self.assertFalse(normalized["real_benefit_claim"])
        without_consumer = [(h,r) for h,r in pairs if r["stage"] != "consumer"]
        self.assertEqual(benefits.batch_outcome(without_consumer, policy, batch, chain, session, now)[0], "unknown")
        bad = json.loads(json.dumps(pairs))
        for _, r in bad:
            if r["stage"] == "publish":
                next(v for v in r["inputs"] if v["object_id"] == "signal_kelly_trades.json")["sha256"] = "0" * 64
        self.assertEqual(benefits.batch_outcome(bad, policy, batch, chain, session, now)[0], "unknown")

    def test_closed_stderr_cannot_override_result_or_original_exception(self):
        class Closed:
            def write(self, value):
                raise BrokenPipeError("closed")
            def flush(self):
                pass
        marker = ValueError("original")
        @de.evidence_stage(data_root=lambda: self.root, stage="signal", chain_id="market_signal_freeze_plan", object_id="signal_daily")
        def run(raise_original=False):
            if raise_original:
                raise marker
            return 17
        path = self.root / "data/ops_delivery"
        path.mkdir(parents=True, mode=0o755)
        with patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1"}), redirect_stderr(Closed()):
            self.assertEqual(run(), 17)
            with self.assertRaises(ValueError) as caught:
                run(True)
        self.assertIs(caught.exception, marker)

    def test_loaded_code_binding_stable_and_unreviewed_unknown(self):
        fn = de.verify_local_backtest_consumer
        first = de.loaded_code_identity(fn, self.root)
        self.assertEqual(first, de.loaded_code_identity(fn, self.root))
        self.assertEqual(first["sha"], "unknown")

    def test_fifo_identity_and_receipt_do_not_block_business(self):
        private = self.root / "data/ops_delivery"
        private.mkdir(parents=True, mode=0o700)
        os.mkfifo(private / "producer-identity.json", 0o600)
        @de.evidence_stage(data_root=lambda: self.root, stage="signal", chain_id="market_signal_freeze_plan", object_id="signal_daily")
        def run():
            return 73
        with patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1"}):
            self.assertEqual(run(), 73)
        fifo = self.root / "not-receipt.json"
        os.mkfifo(fifo, 0o600)
        with self.assertRaises(ValueError):
            de.read_receipt(fifo)

    def test_original_signal_store_allows_recompute_and_legal_empty(self):
        path = self.root / "signals.db"
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE signal_daily(date,index_id,signal,reason, PRIMARY KEY(date,index_id,signal))")
        con.execute("INSERT INTO signal_daily VALUES('20261105','i','buy','old')")
        con.commit()
        con.close()
        audit = types.ModuleType("app.history_audit")
        audit.today_ymd = lambda: "20261106"
        audit.snapshot_signal_daily_history = lambda c,d: set(c.execute("SELECT date,index_id,signal FROM signal_daily WHERE date<?", (d,)).fetchall())
        audit.audit_signal_daily_store = lambda *a: None
        ns = dict(__name__="isolated_signals", __package__="app.compute",
                  __file__=str(self.root / "app/compute/signals.py"), Path=Path,
                  evidence_stage=de.evidence_stage, capture_loaded=de.capture_loaded,
                  capture_event=de.capture_event, capture_signal_visibility=de.capture_signal_visibility,
                  capture_connection=de.capture_connection,
                  get_conn=lambda: sqlite3.connect(path))
        function_ast("app/compute/signals.py", {"store"}, ns)
        with patch.dict(sys.modules, {"app.history_audit": audit}), patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1"}):
            self.assertEqual(ns["store"]([("20261105", "i", "buy_aux", "recomputed")]), 1)
            con = sqlite3.connect(path)
            self.assertEqual(con.execute("SELECT signal FROM signal_daily").fetchall(), [("buy_aux",)])
            con.close()
            self.assertEqual(ns["store"]([]), 0)
            con = sqlite3.connect(path)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM signal_daily").fetchone()[0], 0)
            con.close()
        self.assertEqual(len(list(de.iter_receipts(self.root))), 2)

    def test_real_hook_legal_empty_and_consumer_content_conflict(self):
        from ops.monitoring import benefits
        control, pairs, session, policy = build_hook_fixture(self.root, empty=True)
        batch = f"backtest_publish_consume:{session}"
        self.assertEqual(benefits.batch_outcome(pairs, policy, batch, "backtest_publish_consume", session, datetime.now(timezone.utc))[0], "success")
        paths = {r["stage"]: p for p in self.root.glob("data/ops_delivery/receipts/*/*/*.json") for r in [de.read_receipt(p)]}
        data = self.root / "static-site/data"
        (data / "signal_kelly_trades.json").write_text('{"fields":[],"quadrants":{}}')
        with patch.dict(os.environ, {"OPS_DELIVERY_EVIDENCE_ENABLED": "1"}):
            result = de.verify_local_backtest_consumer(data_root=self.root, producer_receipt=paths["backtest"],
                        publication_receipt=paths["publish"], artifact_paths={n: data / n for n in
                        ("signal_kelly_backtest.json", "signal_kelly_trades.json")}, session_date=session)
        receipt = de.read_receipt(next(self.root.glob("data/ops_delivery/receipts/*/*/" + result["receipt_id"] + ".json")))
        self.assertEqual(receipt["stage_status"], "failure")
        self.assertGreater(receipt["counts"]["failed"], 0)


if __name__ == "__main__":
    unittest.main()
