"""Bounded, isolated regressions; execute producer definitions, never its entrypoint."""
import ast
import contextlib
import copy
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_codex_signal_gap_diagnostics_20261106 as isolated

SOURCE = Path(__file__).resolve().parents[1] / "signal_kelly_backtest.py"


class FrozenInputContextTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.mod = isolated.source_module(SOURCE, ("_SIG_RANK", "_FREEZE_DI_IDX", "_FREEZE_DI_IDX_LEN"),
            ("_signal_key", "_build_freeze_di_idx", "_freeze_fallback", "_resolve_etf",
             "_frozen_input_identity", "_frozen_missing_context", "_archive_frozen_missing_diagnostics",
             "_etf_freeze_path"))
        compute = next(n for n in ast.parse(SOURCE.read_text()).body
                       if isinstance(n, ast.FunctionDef) and n.name == "compute")
        compute.decorator_list = []  # instrumentation wrapper is outside this orchestration test
        exec(compile(ast.Module(body=[compute], type_ignores=[]), str(SOURCE), "exec"), self.mod.__dict__)
        m = self.mod
        m.ROOT = str(self.root)
        m.ETF_FREEZE_PATH_ENV = "SIGNAL_KELLY_ETF_FREEZE_PATH"
        self.stack.enter_context(patch.dict(os.environ, {m.ETF_FREEZE_PATH_ENV: str(self.root / "freeze.json")}))
        atomic = isolated.source_module(SOURCE.parent / "util_atomic.py")
        atomic._random = random
        m.atomic_write_json = atomic.atomic_write_json
        m.KELLY_BUY_NEXTDAY = 1
        m._iid_in_excluded_category = lambda iid: False
        m.capture_event = lambda *a, **k: None
        m._PRUNED_UNIVERSE_N = 0
        m._FROZEN_MISSING_EVENTS = set()

    def test_identity_is_before_in_memory_additions_and_disk_replacement(self):
        m = self.mod
        freeze = {}
        best = {"idx": {"code": "510300", "name": "then", "track_tier": "strong"}}
        rows = [("20261106", "idx", "buy")]
        rating = {"idx": {"buy": {"10d": {"score": 0.4}}}}
        ctx = m._frozen_missing_context(rows, best, freeze, rating, "20261106")
        expected = copy.deepcopy(ctx)
        m._resolve_etf(*rows[0], best, freeze, "20261106")
        self.assertTrue(freeze)
        best["idx"]["code"] = "159001"
        (self.root / "freeze.json").write_text('{"replaced_on_disk":true}')
        m._archive_frozen_missing_diagnostics([("20261105", "idx", "buy")], [], ctx)
        archive, = (self.root / "data/audit/frozen_missing").glob("*.json")
        d = json.loads(archive.read_text())
        self.assertEqual(d["input_counts"]["freeze"], 0)
        self.assertEqual(d["hashes"]["freeze_input_sha256"], hashlib.sha256(b"{}").hexdigest())
        self.assertEqual(d["hashes"]["map_input_sha256"], expected["hashes"]["map_input_sha256"])
        self.assertEqual(d["latest_signal_date"], "20261106")
        self.assertIn("resolved best_etf", d["input_scopes"]["map"])
        self.assertEqual((self.root / "freeze.json").read_text(), '{"replaced_on_disk":true}')

    def test_context_failure_is_unknown_without_releasing_guard(self):
        m = self.mod
        with contextlib.redirect_stderr(io.StringIO()):
            ctx = m._frozen_missing_context([], {"bad": object()}, {}, {}, None)
        self.assertIsNone(ctx)
        freeze = {}
        self.assertEqual(m._resolve_etf("20261105", "idx", "buy", {"idx": {"code": "510300"}},
                                        freeze, "20261106"), (None, False))
        self.assertFalse(freeze)
        m._archive_frozen_missing_diagnostics(sorted(m._FROZEN_MISSING_EVENTS), [], ctx)
        d = json.loads(next((self.root / "data/audit/frozen_missing").glob("*.json")).read_text())
        self.assertEqual(d["hashes"]["freeze_input_sha256"], "unknown")
        self.assertEqual(d["latest_signal_date"], "unknown")

    def run_compute(self, fail_save=False):
        """Real compute orchestration + resolver, with in-memory SQLite and finite loaders."""
        m = self.mod
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE signal_daily(date TEXT,index_id TEXT,signal TEXT)")
        c.executemany("INSERT INTO signal_daily VALUES(?,?,?)", [
            ("20261105", "old", "buy"), ("20261106", "new", "buy")])
        freeze = {}
        m.PERIODS = {k: {} for k in ("y1", "y3", "y5", "y10")}
        m.BUY_SIGNALS = ("buy",)
        m.FREEZE_UNION_ENV = "TEST_FREEZE_UNION_DISABLED"
        self.stack.enter_context(patch.dict(os.environ, {m.FREEZE_UNION_ENV: "0"}))
        m._load_signal_stats = lambda: {}
        m._load_board_etf_map = lambda: {}
        m._build_best_etf = lambda _: {i: {"code": "510300", "name": "ETF"} for i in ("old", "new")}
        m._load_etf_freeze = lambda: freeze
        m._load_market_map = lambda: {}
        m.get_conn = lambda: c
        m._load_market_state = lambda conn: ({}, [])
        m._load_market_tiers = lambda conn, **kw: {}
        m.capture_loaded = lambda *a, **kw: None
        m.capture_sql_rows = lambda *a, **kw: None
        m._KELLY_FEE_CONFIG = {}
        m.KELLY_ASOF = ""
        m.SELL_MODES = {}
        m._detect_freeze_orphan_buy_events = lambda *a: []
        m._load_freeze_backfill_registry = lambda: set()
        m._split_registered_orphans = lambda *a: ([], 0)
        m._alert_freeze_orphans = lambda *a, **kw: None
        m._union_freeze_backfill_rows = lambda rows, *a: rows
        m._etf_daily_today_ready = lambda: (True, "20261106", 1)
        m._batch_load_etf_prices = lambda codes: ({}, {}, {}, {})
        m._classify_buy_rows = lambda *a: ({}, dict(classified=0, skipped_no_etf=1,
            skipped_no_score=1, skipped_no_price=0, frozen_used=0))
        def save(obj):
            if fail_save:
                raise PermissionError("injected failure")
            m.atomic_write_json(self.root / "freeze.json", obj)
        m._save_etf_freeze = save
        captured = []
        def alert(events, context):
            captured.append((copy.deepcopy(events), copy.deepcopy(context)))
            m._archive_frozen_missing_diagnostics(sorted(events), [], context)
        m._alert_frozen_missing = alert
        m._build_outputs = lambda q: ({"same_output": True}, {})
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.compute(), ({"same_output": True}, {}))
        return captured[0]

    def test_compute_wires_actual_context_and_save_success(self):
        events, ctx = self.run_compute()
        self.assertEqual(events, {("20261105", "old", "buy")})
        self.assertEqual(ctx["input_counts"]["freeze"], 0)
        self.assertEqual(ctx["freeze_persistence"], {"status": "saved", "count": 1})
        self.assertEqual(ctx["latest_signal_date"], "20261106")
        saved = json.loads((self.root / "freeze.json").read_text())
        self.assertEqual(list(saved), ["20261106|new|buy"])

    def test_compute_save_failure_is_recorded_and_does_not_hide_missing(self):
        events, ctx = self.run_compute(fail_save=True)
        self.assertEqual(events, {("20261105", "old", "buy")})
        self.assertEqual(ctx["freeze_persistence"], {"status": "failed", "error_type": "PermissionError"})
        self.assertFalse((self.root / "freeze.json").exists())

    def test_map_recovery_exposes_old_events_without_freezing_them(self):
        m = self.mod
        for cutoff in ("20261009", "20261028", "20261104"):
            with self.subTest(cutoff=cutoff):
                event = (cutoff, "ths", "buy")
                freeze = {}
                self.assertEqual(m._resolve_etf(*event, {}, freeze, cutoff), (None, False))
                self.assertNotIn(event, m._FROZEN_MISSING_EVENTS)
                self.assertEqual(m._resolve_etf(*event, {"ths": {"code": "510300"}}, freeze,
                                                "20261106"), (None, False))
                self.assertIn(event, m._FROZEN_MISSING_EVENTS)
                self.assertFalse(freeze)
                m._FROZEN_MISSING_EVENTS.clear()


class GapAttributionTests(unittest.TestCase):
    def test_unverified_candidates_remain_visible_without_acceptance_claim(self):
        case = isolated.SignalGapDiagnostics("test_changed_candidate_cannot_prove_historical_trade")
        case.setUp()
        try:
            case.seed(freeze=False)
            findings = case.coverage()
            self.assertEqual((findings[0].key, findings[0].level), ("data_gap:kelly_coverage", "severe"))
            self.assertIn("当前映射候选", findings[0].title)
            self.assertIn("当前映射候选信号", findings[0].detail)
            self.assertIn("不能用当前候选ETF补冻", findings[0].detail)
            self.assertNotIn("属已知接受缺口", findings[0].detail)
            self.assertNotIn("手动补 etf_daily 再重跑", findings[0].detail)
            self.assertEqual(case.archive()[1]["records"][0]["historical_should_trade"], "unknown")
        finally:
            case.tearDown()
            case.doCleanups()
