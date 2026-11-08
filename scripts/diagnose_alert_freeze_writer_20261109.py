#!/usr/bin/env python3
"""Isolated writer counterexample. No network, production DB, entrypoint or collection.

Exit 1: first-fill-only writer retained opening quote after a newer quote was offered.
Exit 0: sample refreshed to the closing quote. This is evidence, not a data repair.
"""
import ast
import contextlib
from datetime import datetime
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import types
from unittest.mock import patch


def reproduce():
    source = Path(__file__).resolve().parents[1] / "app/collector/intraday_snapshot.py"
    tree = ast.parse(source.read_text())
    writer = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_backfill_signal_universe_tencent")
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("_signal_universe_")]
    class Clock(datetime):
        current = datetime(2026, 11, 4, 9, 35)
        @classmethod
        def now(cls, tz=None):
            return cls.current.replace(tzinfo=tz) if tz else cls.current
    calendar = types.ModuleType("app.calendar")
    calendar.is_trading_day = lambda day: True
    with tempfile.TemporaryDirectory(prefix="alert-freeze-writer-sample-") as td, \
            patch.dict("sys.modules", {"app.calendar": calendar}):
        db = Path(td) / "sample.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE signal_daily(index_id TEXT)")
            conn.execute("INSERT INTO signal_daily VALUES('csi_000102')")
            # Same row metadata as app/db.py; no new production DB or persistent state.
            conn.execute("CREATE TABLE index_daily(date TEXT,index_id TEXT,open REAL,high REAL,"
                         "low REAL,close REAL,pct_change REAL,amount REAL,source TEXT,intraday_quote_at TEXT,PRIMARY KEY(date,index_id))")
        quote = dict(code="sz399102", price=100, open=100, high=100, low=100,
                     datetime="20261104093000", pct_change=0, amount=None)
        calls = []
        def fixture_get(*args, **kwargs):
            calls.append("fixture_only")
            return types.SimpleNamespace(content=b"fixture")
        def connect():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            return conn
        scope = dict(__package__="app.collector", datetime=Clock,
                     get_conn=connect,
                     _SIGNAL_UNIVERSE_TENCENT_MAP={"csi_000102": "sz399102"},
                     throttle=lambda: None, UA="isolated", _safe_get=fixture_get,
                     _parse_tencent=lambda text: [dict(quote)],
                     PCT_CHANGE_PRESERVE_SQL="pct_change=excluded.pct_change")
        exec(compile(ast.Module(body=helpers + [writer], type_ignores=[]), str(source), "exec"), scope)
        with contextlib.redirect_stdout(io.StringIO()):
            first = scope[writer.name]("20261104")
            Clock.current = datetime(2026, 11, 4, 15, 35)
            quote.update(price=110, high=111, low=99, datetime="20261104150000")
            second = scope[writer.name]("20261104")
        with sqlite3.connect(db) as conn:
            observed = conn.execute("SELECT open,high,low,close,source FROM index_daily").fetchone()
        return dict(source=str(source), function=writer.name, first_writes=first,
                    second_writes=second, fixture_fetch_calls=len(calls),
                    observed_ohlc=list(observed[:4]), observed_source=observed[4],
                    offered_closing_ohlc=[100, 111, 99, 110],
                    refreshed=observed[:4] == (100, 111, 99, 110),
                    limitation="Writer mechanism only; historical source attribution requires backups/logs.")


if __name__ == "__main__":
    result = reproduce()
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["refreshed"] else 1)
