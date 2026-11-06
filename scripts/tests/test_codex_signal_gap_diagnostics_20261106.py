"""Task B: source-only contracts, temporary SQLite, no business entrypoint imports.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s scripts/tests
     -p test_codex_signal_gap_diagnostics_20261106.py -v
Optional SIGNALDIAG_BASELINE_SOURCE supplies a previously exported base blob.
"""
from __future__ import annotations

import ast
import contextlib
import gzip
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
from datetime import datetime, timedelta
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_data_gap_alerts.py"
NOW = datetime(2026, 9, 8, 22, 35)
DAYS = ["20260902", "20260903", "20260904", "20260907", "20260908"]


def source_module(path, assignments=(), functions=None):
    """Compile definitions and explicit literal constants; never run entrypoints/imports."""
    tree = ast.parse(Path(path).read_text())
    nodes = [n for n in tree.body if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and
                                      (functions is None or n.name in functions)) or
             (isinstance(n, (ast.Assign, ast.AnnAssign)) and
              any(isinstance(t, ast.Name) and t.id in assignments
                  for t in (n.targets if isinstance(n, ast.Assign) else [n.target])))]
    mod = types.ModuleType("isolated_gap_source")
    mod.__dict__.update(Path=Path, datetime=datetime, timedelta=timedelta,
                        sqlite3=sqlite3, json=json, os=os, sys=sys, gzip=gzip,
                        subprocess=subprocess, tempfile=tempfile, __file__=str(path))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), mod.__dict__)
    return mod


CONSTANTS = ("KELLY_TRADES_FILE", "KELLY_FREEZE_FILE", "KELLY_COVERAGE_KEY", "KELLY_STALE_KEY",
             "KELLY_COVERAGE_BACK", "KELLY_SEVERE_BACK", "KELLY_DIAG_PRICE_LIMIT", "NAV_REAL_WHERE",
             "_TRADES_CACHE", "_UNIVERSE_CACHE", "SEV_ORDER")


class SignalGapDiagnostics(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.hits = []

        def blocked(*args, **kwargs):
            self.hits.append("egress")
            raise AssertionError("external transport blocked")

        for owner, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                            (socket, "create_connection"), (socket, "getaddrinfo"),
                            (subprocess, "run"), (subprocess, "Popen"), (os, "system"), (os, "popen")):
            self.stack.enter_context(patch.object(owner, name, blocked))
        # Positive controls occur BEFORE any business source is loaded/executed.
        with socket.socket() as sock, self.assertRaisesRegex(AssertionError, "transport blocked"):
            sock.connect(("127.0.0.1", 9))
        with self.assertRaisesRegex(AssertionError, "transport blocked"):
            subprocess.run(["must-never-execute"])
        with self.assertRaisesRegex(AssertionError, "transport blocked"):
            socket.getaddrinfo("must-not-resolve.invalid", 443)
        self.hits.clear()
        self.mod = self.load(CHECKER)
        self.repo = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="signaldiag-test-")))
        (self.repo / "data").mkdir()
        (self.repo / "static-site/data").mkdir(parents=True)
        (self.repo / "data/trade_dates.txt").write_text("\n".join(DAYS))
        self.seed()

    def tearDown(self):
        self.assertEqual(self.hits, [], "unexpected external transport attempt")

    def load(self, path):
        mod = source_module(path, CONSTANTS)
        # Existing helper source is stdlib-only, loaded with no top-level imports.
        atom = source_module(ROOT / "scripts/util_atomic.py")
        import random
        atom._random = random
        mod.atomic_write_json = atom.atomic_write_json
        mod.notify_sent = source_module(ROOT / "scripts/notify_sent.py").notify_sent
        return mod

    def write_json(self, relative, obj):
        (self.repo / relative).write_text(json.dumps(obj))

    def seed(self, n=1, freeze=True, current_nav=1.2, current_open=1.1):
        db = self.repo / "data/sentiment.db"
        with sqlite3.connect(db) as conn:
            conn.execute("DROP TABLE IF EXISTS signal_daily")
            conn.execute("CREATE TABLE signal_daily(date TEXT,index_id TEXT,signal TEXT, PRIMARY KEY(date,index_id))")
            conn.executemany("INSERT INTO signal_daily VALUES(?,?,?)",
                             [("20260904", f"idx{i}", "buy_aux") for i in range(n)] +
                             [("20260908", "today", "sell")])
        with sqlite3.connect(self.repo / "data/etf_national_team.db") as conn:
            conn.execute("DROP TABLE IF EXISTS etf_daily")
            conn.execute("CREATE TABLE etf_daily(etf_code TEXT,date TEXT,etf_name TEXT,"
                         "accum_nav REAL,open REAL,close REAL,PRIMARY KEY(etf_code,date))")
            # Current candidate price ready; historical frozen ETF has no signal-day NAV or next-day open.
            conn.executemany("INSERT INTO etf_daily VALUES(?,?,?,?,?,?)", [
                ("510300", "20260907", "New ETF", current_nav, current_open, 1.1),
                ("159001", "20260904", "Old ETF", None, 1.0, 1.0),
                ("159001", "20260907", "Old ETF", 1.0, None, 1.0)])
        self.write_json("static-site/data/board_etf_map.json",
                        {f"idx{i}": [{"code": "510300", "name": "New ETF", "track_score": 90}] for i in range(n)})
        self.write_json("static-site/data/signal_kelly_etf_freeze.json",
                        {f"20260904|idx{i}|buy_aux": {"code": "159001", "name": "Old ETF"}
                         for i in range(n)} if freeze else {})
        self.write_json("static-site/data/signal_kelly_trades.json",
                        {"fields": ["signal_date", "index_id", "signal"],
                         "quadrants": {"sig_main": {"A": [["20260902", "other", "buy"]]}}})
        self.mod._TRADES_CACHE.clear()
        self.mod._UNIVERSE_CACHE.clear()

    def coverage(self, mod=None):
        return (mod or self.mod).check_kelly_coverage(self.repo, NOW)

    def archive(self):
        paths = list((self.repo / "data/audit/signal_gap_diagnostics").glob("*.json"))
        self.assertEqual(len(paths), 1)
        return paths[0], json.loads(paths[0].read_text())

    def test_changed_candidate_cannot_prove_historical_trade(self):
        findings = self.coverage()
        self.assertEqual([(f.key, f.level) for f in findings], [("data_gap:kelly_coverage", "severe")])
        path, payload = self.archive()
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        record = payload["records"][0]
        self.assertEqual(record["resolved_freeze_key"], "20260904|idx0|buy_aux")
        self.assertEqual(record["frozen_etf"], "159001")
        self.assertEqual(record["current_candidate_etf"], "510300")
        self.assertEqual(record["current_candidate_next_price"]["values"]["open"], 1.1)
        rows = record["frozen_price_observations"]["rows"]
        self.assertIsNone(rows["signal_day"]["values"]["accum_nav"])
        self.assertIsNone(rows["window_next_day"]["values"]["open"])
        self.assertEqual(record["historical_should_trade"], "unknown")
        self.assertTrue(all(v == "unknown" for v in payload["fingerprints"].values()))
        self.assertIn("不能证明历史应成交", findings[0].detail)

    def test_true_resolver_exact_and_fallback_one_hop(self):
        producer = source_module(ROOT / "scripts/signal_kelly_backtest.py",
                                 ("_SIG_RANK", "_FREEZE_DI_IDX", "_FREEZE_DI_IDX_LEN"),
                                 ("_signal_key", "_build_freeze_di_idx", "_freeze_fallback", "_resolve_etf"))
        producer._iid_in_excluded_category = lambda iid: False
        producer._PRUNED_UNIVERSE_N = 0
        producer._FROZEN_MISSING_EVENTS = set()
        freeze = {"20260904|idx0|buy": {"code": "159001"},
                  "20260904|idx0|buy_backup": {"code": "159002"}}
        be, frozen = producer._resolve_etf("20260904", "idx0", "buy_aux", {}, freeze, "20260908")
        self.assertTrue(frozen)
        self.assertEqual(be["code"], "159002")
        # checker deliberately cannot claim that key without resolver context.
        diag = self.mod._signal_gap_evidence("20260904", "idx0", "buy_aux", "510300", freeze)
        self.assertEqual(diag["frozen_etf"], "unknown")
        self.assertEqual(diag["resolved_freeze_key"], "unknown")
        freeze["20260904|idx0|buy_aux"] = {"code": "159003"}
        be, _ = producer._resolve_etf("20260904", "idx0", "buy_aux", {}, freeze, "20260908")
        self.assertEqual(be["code"], "159003")
        self.assertEqual(self.mod._signal_gap_evidence("20260904", "idx0", "buy_aux", "510300", freeze)
                         ["frozen_etf"], be["code"])

    def test_missing_freeze_rating_and_db_remain_unknown(self):
        self.seed(freeze=False)
        (self.repo / "data/etf_national_team.db").unlink()
        findings = self.coverage()
        record = self.archive()[1]["records"][0]
        self.assertEqual(record["frozen_etf"], "unknown")
        self.assertEqual(record["current_candidate_next_price"]["status"], "unknown")
        self.assertIn("unknown", record["rating_evidence"])
        self.assertIn("仅当前候选", findings[0].detail)

    def test_all_detected_retained_beyond_price_and_preview_budget(self):
        self.seed(n=37)
        findings = self.coverage()
        payload = self.archive()[1]
        self.assertEqual(payload["detected_count"], 37)
        self.assertEqual(len(payload["records"]), 37)
        self.assertTrue(payload["records_complete"])
        self.assertEqual(payload["price_enriched_count"], 32)
        self.assertEqual(payload["records"][-1]["frozen_etf"], "159001")
        self.assertEqual(payload["records"][-1]["frozen_price_observations"]["status"],
                         "unknown_or_budget_exhausted")
        self.assertEqual(findings[0].detail.count("&quot;signal_key&quot;"), 10)

    def test_no_composite_point_index_no_history_scan(self):
        with sqlite3.connect(self.repo / "data/etf_national_team.db") as conn:
            conn.execute("ALTER TABLE etf_daily RENAME TO old")
            conn.execute("CREATE TABLE etf_daily AS SELECT * FROM old")
            conn.execute("CREATE INDEX code_only ON etf_daily(etf_code)")
            conn.execute("DROP TABLE old")
        self.coverage()
        self.assertEqual(self.archive()[1]["records"][0]["frozen_price_observations"]["status"],
                         "unknown_no_point_index")

    def test_bad_close_schema_diagnostic_failure_preserves_original(self):
        with sqlite3.connect(self.repo / "data/etf_national_team.db") as conn:
            conn.execute("ALTER TABLE etf_daily DROP COLUMN close")
        findings = self.coverage()
        self.assertEqual(findings[0].level, "severe")
        self.assertEqual(self.archive()[1]["records"][0]["frozen_price_observations"]["status"],
                         "unknown_query_error")

    def test_placeholder_rows_are_not_evidence_of_real_prices(self):
        with sqlite3.connect(self.repo / "data/etf_national_team.db") as conn:
            conn.execute("UPDATE etf_daily SET etf_name=etf_code WHERE etf_code='159001'")
        self.coverage()
        rows = self.archive()[1]["records"][0]["frozen_price_observations"]["rows"]
        self.assertEqual(rows["signal_day"]["status"], "absent_or_placeholder")
        self.assertEqual(rows["window_next_day"]["status"], "absent_or_placeholder")

    def test_archive_atomic_unique_and_nooverwrite(self):
        real_link = os.link
        calls = []

        def observe_link(src, dst):
            obj = json.loads(Path(src).read_text())
            self.assertTrue(obj["records_complete"])
            self.assertEqual(Path(src).stat().st_mode & 0o777, 0o600)
            self.assertFalse(Path(dst).exists())
            calls.append(dst)
            real_link(src, dst)

        with patch.object(os, "link", side_effect=observe_link):
            self.coverage()
            self.coverage()
        self.assertEqual(len(set(calls)), 2)
        first = Path(calls[0]).read_bytes()
        audit = Path(calls[0]).parent
        import uuid
        fixed = types.SimpleNamespace(hex=Path(calls[0]).stem)
        with patch.object(uuid, "uuid4", return_value=fixed), contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.coverage()[0].level, "severe")
        self.assertIn("FileExistsError", err.getvalue())
        self.assertEqual(Path(calls[0]).read_bytes(), first)
        self.assertFalse(list(audit.glob(".pending-*")))

    def test_archive_failures_leave_alert_unchanged(self):
        # Missing write permission is deterministic via explicit EACCES even when runner is root.
        for operation in ("mkdir", "atomic", "link"):
            with self.subTest(operation=operation), contextlib.ExitStack() as stack:
                target = {"mkdir": (Path, "mkdir"), "atomic": (self.mod, "atomic_write_json"),
                          "link": (os, "link")}[operation]
                stack.enter_context(patch.object(*target, side_effect=PermissionError("denied")))
                stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
                f = self.coverage()[0]
                self.assertEqual((f.key, f.level), ("data_gap:kelly_coverage", "severe"))
                self.assertIn("archive failed", f.detail)

    def test_original_notify_transport_success_failure_dedup_and_recovery(self):
        f = self.coverage()
        expected_subject = f"[严重][数据缺口] {f[0].title} 09-08 22:35"
        calls = []

        def transport(cmd, **kwargs):
            self.assertEqual(cmd[1], str(self.repo / "scripts/notify.py"))
            self.assertIn("--severe", cmd)
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "[notify] 汇总：全部渠道未发出")

        # Keep original _notify and run_alerts, replace only its subprocess transport.
        with patch.object(subprocess, "run", side_effect=transport):
            self.mod.run_alerts(self.repo, f, False, now=NOW)
        state_path = self.repo / "data/alerts/data_gap_alert_state.json"
        self.assertNotIn(f[0].key, json.loads(state_path.read_text()))
        self.assertEqual(calls[0][2], expected_subject)
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "已发出 email", "")) as send:
            self.mod.run_alerts(self.repo, f, False, now=NOW)
            self.mod.run_alerts(self.repo, f, False, now=NOW)
            self.assertEqual(send.call_count, 1)
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "已发出 email", "")) as send:
            self.mod.run_alerts(self.repo, [], False, now=NOW)
            self.assertIn("[恢复][数据缺口]", send.call_args.args[0][2])
        self.assertEqual(json.loads(state_path.read_text()), {})

    def test_same_candidate_freeze_and_first_day_downgrade(self):
        self.write_json("static-site/data/signal_kelly_etf_freeze.json",
                        {"20260904|idx0|buy_aux": {"code": "510300"}})
        self.assertEqual(self.coverage()[0].level, "warn")  # original C-class exact-freeze downgrade
        self.seed(freeze=False, current_nav=None)
        with sqlite3.connect(self.repo / "data/sentiment.db") as conn:
            conn.execute("UPDATE signal_daily SET date='20260907' WHERE index_id='idx0'")
        self.assertEqual(self.coverage()[0].level, "warn")  # original T-1 explainable downgrade

    def test_malformed_freeze_and_unknown_values_are_not_fabricated(self):
        for entry in (None, {}, "bad", {"code": None}, {"code": True}, {"code": 510300},
                      {"code": ["510300"]}, {"code": ""}, {"code": "NEW"},
                      {"code": "１２３４５６"}, {"code": "51030x"}):
            with self.subTest(entry=entry):
                diag = self.mod._signal_gap_evidence("20260904", "idx0", "buy_aux", "510300",
                                                     {"20260904|idx0|buy_aux": entry})
                self.assertTrue(diag["exact_freeze_key_present"])
                self.assertEqual(diag["frozen_etf"], "unknown")
                self.assertEqual(diag["resolved_freeze_key"], "unknown")
                self.assertTrue(diag["producer_resolution"].startswith("unknown"))
                self.assertEqual(diag["historical_should_trade"], "unknown")

    def test_non_json_sqlite_value_cannot_suppress_original_alert(self):
        # SQLite accepts BLOB in a REAL-affinity column; original checker only checks NULL.
        with sqlite3.connect(self.repo / "data/etf_national_team.db") as conn:
            conn.execute("UPDATE etf_daily SET open=? WHERE etf_code='510300'", (b"bad-price",))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            f = self.coverage()[0]
        self.assertEqual((f.key, f.level), ("data_gap:kelly_coverage", "severe"))
        self.assertIn("archive failed", f.detail)
        self.assertIn("preview serialization failed", f.detail)
        self.assertIn("TypeError", err.getvalue())

    def test_empty_detection_no_archive(self):
        self.write_json("static-site/data/signal_kelly_trades.json",
                        {"quadrants": {"sig_main": {"A": [["20260904", "idx0", "buy_aux"]]}}})
        self.assertEqual(self.coverage(), [])
        self.assertFalse((self.repo / "data/audit").exists())

    def test_read_only_connections_and_bounded_query_count(self):
        self.seed(n=37)
        real_connect = sqlite3.connect
        queries = []

        def connect(database, **kwargs):
            self.assertIn("mode=ro", database)
            self.assertTrue(kwargs["uri"])
            conn = real_connect(database, **kwargs)
            conn.set_trace_callback(queries.append)
            return conn

        with patch.object(sqlite3, "connect", side_effect=connect):
            self.coverage()
        price_queries = [q for q in queries if "SELECT accum_nav, open, close" in q]
        self.assertEqual(len(price_queries), 64)
        self.assertFalse(any(q.startswith(("INSERT", "UPDATE", "DELETE", "CREATE")) for q in queries))

    def test_optional_baseline_semantic_parity(self):
        path = os.environ.get("SIGNALDIAG_BASELINE_SOURCE")
        baseline = self.load(path) if path else None
        if baseline:
            original_tree = ast.parse(Path(path).read_text())
            current_tree = ast.parse(CHECKER.read_text())
            for name in ("_kelly_missing_candidates", "_freeze_hit", "check_kelly_stale",
                         "_notify", "run_alerts", "run"):
                original = next(n for n in original_tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
                current = next(n for n in current_tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
                self.assertEqual(ast.dump(original), ast.dump(current), name)
        for freeze, nav, op in ((True, 1.2, 1.1), (False, 1.2, 1.1), (False, None, 1.1),
                                (False, 1.2, None)):
            with self.subTest(freeze=freeze, nav=nav, op=op):
                self.seed(freeze=freeze, current_nav=nav, current_open=op)
                after = self.coverage()
                self.assertEqual(after[0].key, "data_gap:kelly_coverage")
                self.assertEqual(after[0].level, "severe")
                if baseline:
                    baseline._TRADES_CACHE.clear()
                    baseline._UNIVERSE_CACHE.clear()
                    before = baseline.check_kelly_coverage(self.repo, NOW)
                    self.assertEqual([(f.key, f.level, f.title) for f in before],
                                     [(f.key, f.level, f.title) for f in after])
                # Original reason and original blocked semantics must be bit-for-bit equivalent.
                be = {"code": "510300", "name": "New ETF"}
                observed = self.mod._missing_reason(self.repo, "20260904", "idx0", be, DAYS)
                self.assertEqual(observed[1], nav is None or op is None)
                if baseline:
                    self.assertEqual(baseline._missing_reason(self.repo, "20260904", "idx0", be, DAYS), observed)


if __name__ == "__main__":
    unittest.main()
