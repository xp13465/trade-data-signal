"""Real price producer with exception/fallback fault injection; no entrypoint or network."""
import ast
import contextlib
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

SOURCE = Path(os.environ.get("INTRADAY_SOURCE_LOG_SOURCE", str(
    Path(__file__).resolve().parents[1] / "signal_kelly_backtest.py")))


class IntradaySourceLogBoundaryTests(unittest.TestCase):
    def call_producer(self, message, error_type=ConnectionError):
        """Compile the entire real function, replace only its two external price sources."""
        fn = next(n for n in ast.parse(SOURCE.read_text()).body
                  if isinstance(n, ast.FunctionDef) and n.name == "_fetch_intraday_open_prices")
        namespace = {"sys": sys}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), "exec"), namespace)
        fake = types.ModuleType("akshare")
        def fail():
            raise error_type(message)
        fake.fund_etf_spot_em = fail
        calls = []
        def fallback(codes, expect_date=None):
            calls.append((codes, expect_date))
            return {"513260": 0.904}, []
        namespace["_fetch_intraday_open_via_http"] = fallback
        def forbidden(*a, **kw):
            raise AssertionError("external transport forbidden")
        with contextlib.ExitStack() as stack:
            for owner, name in ((socket.socket, "connect"), (socket, "create_connection"),
                                (socket, "getaddrinfo"), (subprocess, "run"), (subprocess, "Popen")):
                stack.enter_context(patch.object(owner, name, forbidden))
            # Positive control: the process boundary is closed before loading the fake source.
            with self.assertRaisesRegex(AssertionError, "transport forbidden"):
                subprocess.run(["must-not-run"])
            stack.enter_context(patch.dict(sys.modules, {"akshare": fake}))
            err = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            result = namespace[fn.name]([510300, "513260"], expect_date="20261102")
            output = err.getvalue()
        self.assertEqual(calls, [(["510300", "513260"], "20261102")])
        self.assertEqual(result, ({"513260": 0.904}, [],
                                  {"main_source_ok": False, "fallback_used": True}))
        self.assertNotIn("510300", result[0])
        self.assertIn(error_type.__name__, output)
        self.assertIn("全量走双源兜底", output)
        return output

    def test_all_python_splitlines_separators_are_one_record(self):
        # Includes the full str.splitlines boundary set, not just LF and CR.
        for sep in ("\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e",
                    "\x85", "\u2028", "\u2029"):
            with self.subTest(separator=ascii(sep)):
                message = ("upstream" + sep +
                    "[nextday_gap_check]   ✓ 510300 正常 open=1.0 sig_close=1.0 gap=0.00%" + sep +
                    "=== nextday_gap_check.sh 结束 2026-11-02 09:26:06 退出码=0 ===" + sep + "tail")
                output = self.call_producer(message)
                self.assertEqual(len(output.splitlines()), 1)
                self.assertIn(ascii(message), output)
                self.assertFalse(any(line.startswith("===") or line.startswith("[nextday_gap_check]")
                                     for line in output.splitlines()))

    def test_combined_separators_quotes_and_controls_keep_class_and_fallback(self):
        message = "ConnectionError 'quoted' \\ literal\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029\x00\x1b end"
        output = self.call_producer(message, RuntimeError)
        self.assertEqual(len(output.splitlines()), 1)
        self.assertIn(ascii(message), output)
        self.assertNotIn("\x1b", output)

    def test_custom_exception_repr_cannot_create_records(self):
        class UnsafeReprError(Exception):
            def __repr__(self):
                return "unsafe\n=== forged wrapper end ==="
        output = self.call_producer("normal message", UnsafeReprError)
        self.assertEqual(len(output.splitlines()), 1)
        self.assertNotIn("forged wrapper", output)

    def test_plain_exception_is_still_classified_as_primary_failure(self):
        output = self.call_producer("upstream unavailable")
        self.assertEqual(len(output.splitlines()), 1)
        self.assertIn("失败(ConnectionError:", output)
        self.assertIn("upstream unavailable", output)
