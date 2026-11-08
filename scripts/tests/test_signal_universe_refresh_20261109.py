"""Actual parser/writer + temporary real SQLite. No production entrypoint or network."""
import ast
import contextlib
from datetime import datetime
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import types

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("SIGNAL_UNIVERSE_WRITER_SOURCE", str(ROOT / "app/collector/intraday_snapshot.py")))
DAY = "20261104"
IID = "csi_000102"


def definitions(path, names=(), prefix=None, namespace=None):
    ns = {} if namespace is None else namespace
    nodes = []
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.FunctionDef) and (node.name in names or prefix and node.name.startswith(prefix)):
            node.decorator_list = []  # instrumentation only; retain complete real function bodies
            nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return ns


def schema_and_migrate(conn, legacy=False):
    tree = ast.parse((ROOT / "app/db.py").read_text())
    schema = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "SCHEMA" for t in n.targets))
    if legacy:
        schema = "\n".join(line for line in schema.splitlines() if "intraday_quote_at TEXT" not in line)
    conn.executescript(schema)
    definitions(ROOT / "app/db.py", ("_migrate",), namespace={"sqlite3": sqlite3})["_migrate"](conn)
    conn.commit()


def raw_quote(code="sz399102", stamp=DAY + "093000", price=100, op=100, high=100, low=100):
    v = [""] * 88
    for i, value in {0: 51, 1: "sample", 3: price, 4: 100, 5: op, 30: stamp,
                     31: 0, 32: 0, 33: high, 34: low}.items():
        v[i] = str(value)
    return 'v_' + code + '="' + '~'.join(v) + '";'


class Clock(datetime):
    current = datetime(2026, 11, 4, 9, 35)
    @classmethod
    def now(cls, tz=None):
        return cls.current.replace(tzinfo=tz) if tz else cls.current


class Harness:
    def __init__(self, db, monkeypatch):
        self.db = db
        self.requests = []
        self.body = ""
        self.on_request = None
        self.trading = True
        fake = types.ModuleType("app.calendar")
        fake.is_trading_day = lambda day: self.trading
        monkeypatch.setitem(__import__("sys").modules, "app.calendar", fake)
        def blocked(*a, **kw):
            raise AssertionError("real egress forbidden")
        for owner, name in ((socket.socket, "connect"), (socket, "getaddrinfo"),
                            (subprocess, "run"), (subprocess, "Popen")):
            monkeypatch.setattr(owner, name, blocked)
        with pytest.raises(AssertionError, match="egress forbidden"):
            subprocess.run(["must-not-run"])
        pct_tree = ast.parse((ROOT / "app/collector/index_pct.py").read_text())
        pct = next(ast.literal_eval(n.value) for n in pct_tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "PCT_CHANGE_PRESERVE_SQL" for t in n.targets))
        self.ns = definitions(SOURCE, ("_parse_tencent", "_backfill_signal_universe_tencent"),
            prefix="_signal_universe_", namespace={"__package__": "app.collector", "datetime": Clock,
                "get_conn": self.connect, "throttle": lambda: None, "_safe_get": self.get,
                "UA": "isolated", "PCT_CHANGE_PRESERVE_SQL": pct,
                "_SIGNAL_UNIVERSE_TENCENT_MAP": {IID: "sz399102"}})
        with self.connect() as conn:
            schema_and_migrate(conn)
            conn.execute("INSERT INTO signal_daily(date,index_id,signal) VALUES('20261103',?,'buy')", (IID,))

    def connect(self):
        conn = sqlite3.connect(self.db, timeout=2)
        conn.row_factory = sqlite3.Row
        return conn

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.on_request:
            self.on_request()
        return types.SimpleNamespace(content=self.body.encode("gbk"))

    def run(self, body, now="2026-11-04 09:35:00", day=DAY):
        Clock.current = datetime.fromisoformat(now)
        self.body = body
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            count = self.ns["_backfill_signal_universe_tencent"](day)
        return count, out.getvalue()

    def row(self, iid=IID, day=DAY):
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM index_daily WHERE date=? AND index_id=?", (day, iid)).fetchone()
            return dict(r) if r else None


@pytest.fixture
def h(tmp_path, monkeypatch):
    return Harness(tmp_path / "sample.db", monkeypatch)


def test_same_source_refreshes_then_older_quote_cannot_revert_after_reload(h):
    assert h.run(raw_quote())[0] == 1
    assert h.row()["close"] == 100
    newer = raw_quote(stamp=DAY+"150000", price=110, high=111, low=99)
    assert h.run(newer, "2026-11-04 15:35:00")[0] == 1  # old writer fails here
    assert [h.row()[k] for k in ("open", "high", "low", "close")] == [100, 111, 99, 110]
    # Recompile functions to prove the watermark is in the DB, not a process cache.
    h.ns = definitions(SOURCE, ("_parse_tencent", "_backfill_signal_universe_tencent"),
                       prefix="_signal_universe_", namespace=h.ns.copy())
    assert h.run(raw_quote(stamp=DAY+"140000", price=105, high=111, low=99),
                 "2026-11-04 15:36:00")[0] == 0
    assert h.row()["close"] == 110


@pytest.mark.parametrize("stamp", ["", "20261103093000", "20261105093000", DAY+"092500",
                                   DAY+"151000", DAY+"123000", DAY+"250000", DAY+"0930"])
def test_missing_stale_premarket_non_session_or_malformed_time_is_not_written(h, stamp):
    assert h.run(raw_quote(stamp=stamp))[0] == 0
    assert h.row() is None


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", 0, -1, "bad"])
@pytest.mark.parametrize("field", ["price", "op", "high", "low"])
def test_invalid_ohlc_is_not_written(h, field, bad):
    assert h.run(raw_quote(**{field: bad}))[0] == 0
    assert h.row() is None


def test_historical_target_cannot_write_live_quote(h):
    assert h.run(raw_quote(), now="2026-11-05 10:00:00", day=DAY)[0] == 0
    assert h.requests == []
    assert h.row() is None


def test_stronger_source_survives_while_request_is_in_flight(h):
    def concurrent_collect():
        with h.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO index_daily(date,index_id,open,high,low,close,source) "
                         "VALUES(?,?,100,115,98,113,'collect')", (DAY, IID))
    h.on_request = concurrent_collect
    h.run(raw_quote(stamp=DAY+"150000", price=110, high=111, low=99), "2026-11-04 15:35:00")
    assert h.row()["source"] == "collect"
    assert h.row()["close"] == 113


def test_equal_timestamp_conflict_is_visible_and_not_overwritten(h):
    h.run(raw_quote())
    count, log = h.run(raw_quote(price=101, high=101))
    assert count == 0
    assert h.row()["close"] == 100
    assert "同一报价时点" in log


def test_real_flat_quote_is_valid_and_idempotent(h):
    assert h.run(raw_quote())[0] == 1
    assert h.row()["intraday_quote_at"] == DAY+"093000"
    assert h.run(raw_quote())[0] == 0


def test_stronger_existing_row_not_requested_and_other_sources_not_overwritten(h):
    with h.connect() as conn:
        conn.execute("INSERT INTO index_daily(date,index_id,close,source) VALUES(?,?,109,'collect')", (DAY, IID))
    assert h.run(raw_quote())[0] == 0
    assert h.requests == []
    assert h.row()["close"] == 109


@pytest.mark.parametrize("legacy", [False, True])
def test_schema_initialization_and_idempotent_migration(tmp_path, legacy):
    db = tmp_path / "migration.db"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        schema_and_migrate(conn, legacy=legacy)
        conn.execute("INSERT INTO index_daily(date,index_id,close,source) VALUES(?,?,100,'intraday_snapshot')", (DAY, IID))
        conn.commit()
        migrate = definitions(ROOT / "app/db.py", ("_migrate",), namespace={"sqlite3": sqlite3})["_migrate"]
        migrate(conn); migrate(conn)
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(index_daily)")]
        assert columns[-2:] == ["source", "intraday_quote_at"]
        assert columns.count("intraday_quote_at") == 1
        assert conn.execute("SELECT intraday_quote_at FROM index_daily").fetchone()[0] is None
        # Existing API/history-audit/compute readers project named columns, not SELECT * tuples.
        assert tuple(conn.execute("SELECT date,open,high,low,close,pct_change,amount FROM index_daily").fetchone()) == (DAY,None,None,None,100,None,None)


def test_legacy_same_source_unknown_time_is_not_fabricated(h):
    with h.connect() as conn:
        conn.execute("INSERT INTO index_daily(date,index_id,open,high,low,close,source) "
                     "VALUES(?,?,100,100,100,100,'intraday_snapshot')", (DAY,IID))
    assert h.row()["intraday_quote_at"] is None
    count, log = h.run(raw_quote(stamp=DAY+"150000",price=110,high=111,low=99), "2026-11-04 15:35:00")
    assert count == 1
    assert "旧报价时点unknown" in log
    assert h.row()["intraday_quote_at"] == DAY+"150000"


@pytest.mark.parametrize("stamp", [DAY+"093501", DAY+"150000"])
def test_future_quote_is_rejected(h, stamp):
    assert h.run(raw_quote(stamp=stamp))[0] == 0
    assert h.row() is None


def test_valid_price_decrease_is_not_mistaken_for_time_regression(h):
    h.run(raw_quote(stamp=DAY+"100000",price=110,high=111,low=99), "2026-11-04 10:05:00")
    assert h.run(raw_quote(stamp=DAY+"110000",price=101,high=111,low=98), "2026-11-04 11:05:00")[0] == 1
    assert h.row()["close"] == 101


@pytest.mark.parametrize("kwargs", [{"high":99}, {"low":101}, {"op":102}, {"high":101,"low":99,"price":102},
    {"price":105,"high":110,"low":99}, {"price":105,"high":111,"low":100},
    {"op":101,"price":110,"high":111,"low":99}])
def test_inconsistent_or_cumulative_ohlc_regression_is_rejected(h, kwargs):
    h.run(raw_quote(stamp=DAY+"100000",price=110,high=111,low=99), "2026-11-04 10:05:00")
    count, _ = h.run(raw_quote(stamp=DAY+"110000", **kwargs), "2026-11-04 11:05:00")
    assert count == 0
    assert h.row()["close"] == 110


@pytest.mark.parametrize("source", ["collect", "calc", None, "other"])
def test_only_own_source_is_refreshable(h, source):
    with h.connect() as conn:
        conn.execute("INSERT INTO index_daily(date,index_id,close,source) VALUES(?,?,109,?)", (DAY,IID,source))
    assert h.run(raw_quote())[0] == 0
    assert not h.requests
    assert h.row()["source"] == source


def test_duplicate_timestamp_conflict_inside_one_response_is_rejected(h):
    count, log = h.run(raw_quote()+raw_quote(price=101,high=101))
    assert count == 0
    assert h.row() is None
    assert "同一报价时点" in log


def test_latest_valid_duplicate_wins_and_equal_identical_is_safe(h):
    body = raw_quote()+raw_quote(stamp=DAY+"100000",price=105,high=105,low=99)+raw_quote()
    assert h.run(body,"2026-11-04 10:05:00")[0] == 1
    assert h.row()["close"] == 105


def test_request_budget_stays_batched_and_stronger_rows_are_filtered(h):
    h.ns["_SIGNAL_UNIVERSE_TENCENT_MAP"] = {f"idx{i}":f"sz{i:06d}" for i in range(61)}
    with h.connect() as conn:
        conn.executemany("INSERT INTO signal_daily(date,index_id,signal) VALUES('20261103',?,'buy')",[(f"idx{i}",) for i in range(61)])
    body = ''.join(raw_quote(code=f"sz{i:06d}") for i in range(61))
    assert h.run(body)[0] == 61
    assert len(h.requests) == 3
    assert all(len(url.split('q=')[1].split(',')) <= 30 and kw['timeout']==10 for url,kw in h.requests)


def test_nontrading_day_does_not_request_or_write(h):
    h.trading = False
    assert h.run(raw_quote())[0] == 0
    assert not h.requests


def test_hk_source_time_normalization_and_session(h):
    h.ns["_SIGNAL_UNIVERSE_TENCENT_MAP"] = {IID:"r_hkHSCCI"}
    assert h.run(raw_quote(code="r_hkHSCCI",stamp="2026/11/04 15:30:00"), "2026-11-04 15:35:00")[0] == 1
    assert h.row()["intraday_quote_at"] == DAY+"153000"


def signal_compute(h):
    source = ROOT / "app/compute/signals.py"
    ns = {"pd":pd, "get_conn":h.connect, "capture_loaded":lambda name,value,**kw:value,
          "capture_sql_rows":lambda *a,**kw:None}
    # Reuse literal production constants; only the input universe is limited to one index.
    for n in ast.parse(source.read_text()).body:
        if isinstance(n,ast.Assign):
            try:value=ast.literal_eval(n.value)
            except (ValueError,TypeError):continue
            for target in n.targets:
                if isinstance(target,ast.Name):ns[target.id]=value
    ns.update(GLOBAL_METRIC_IDS=(), SCORE_IDS=(),
              load_config=lambda:{"indices":[{"id":IID,"enabled":True}]},
              _load_cross_score=lambda:pd.Series(dtype=float))
    names=("_rsi","_bollinger","_macd","_load_index_ohlc_amount","_atr","_supertrend","_cross_tag",
           "_load_buy_aux_filters","_load_buy_filters","_load_sell_no_trend_filters","compute")
    definitions(source,names,namespace=ns)
    return ns["compute"]()


def test_real_index_daily_and_unchanged_signal_engine_update_on_the_same_day(h):
    days=pd.bdate_range(end="2026-11-03",periods=80)
    with h.connect() as conn:
        conn.executemany("INSERT INTO index_daily(date,index_id,open,high,low,close,source) VALUES(?,?,?,?,?,?,'collect')",
            [(d.strftime("%Y%m%d"),IID,120-i*.25,121-i*.25,119-i*.25,120-i*.25) for i,d in enumerate(days)])
    h.run(raw_quote())
    before=signal_compute(h)
    assert not any(d==DAY and sig=='buy' for d,i,sig,reason in before)
    assert h.run(raw_quote(stamp=DAY+"150000",price=110,high=111,low=99), "2026-11-04 15:35:00")[0]==1
    after=signal_compute(h)
    assert any(d==DAY and sig=='buy' and 'RSI上穿30' in reason for d,i,sig,reason in after)
    assert [r for r in before if r[0]<DAY] == [r for r in after if r[0]<DAY]
    # No next-day collect or price row was needed to create the single-day signal.
    with h.connect() as conn:
        assert conn.execute("SELECT MAX(date) FROM index_daily").fetchone()[0]==DAY


@pytest.mark.parametrize("quote", [raw_quote(stamp="20261103150000"), raw_quote(price="nan"),
                                    raw_quote(stamp=""), raw_quote(stamp=DAY+"160000")])
def test_bad_or_stale_quote_after_good_data_cannot_degrade_it(h, quote):
    h.run(raw_quote(stamp=DAY+"150000",price=110,high=111,low=99), "2026-11-04 15:35:00")
    before=h.row()
    assert h.run(quote,"2026-11-04 15:36:00")[0]==0
    assert h.row()==before


def test_newer_legitimate_flat_quote_updates_its_time(h):
    h.run(raw_quote())
    assert h.run(raw_quote(stamp=DAY+"100000"),"2026-11-04 10:05:00")[0]==1
    assert h.row()["close"]==100
    assert h.row()["intraday_quote_at"]==DAY+"100000"


@pytest.mark.parametrize("stamp", ["unknown", "20261103150000", "20261105150000", "20261104999999"])
def test_invalid_existing_time_is_conservative_and_visible(h,stamp):
    h.run(raw_quote())
    with h.connect() as conn:
        conn.execute("UPDATE index_daily SET intraday_quote_at=? WHERE index_id=?",(stamp,IID))
    count,log=h.run(raw_quote(stamp=DAY+"150000",price=110,high=111,low=99),"2026-11-04 15:35:00")
    assert count==0
    assert h.row()["close"]==100
    assert "旧报价时点元数据无效" in log


@pytest.mark.parametrize("legacy", [False,True])
def test_actual_get_conn_initializes_new_and_migrates_old_database(tmp_path,legacy):
    import importlib.util
    db=tmp_path/"get-conn.db"
    if legacy:
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE index_daily(date TEXT,index_id TEXT,open REAL,high REAL,low REAL,"
                         "close REAL,pct_change REAL,amount REAL,net_inflow REAL,source TEXT,PRIMARY KEY(date,index_id))")
            conn.execute("INSERT INTO index_daily(date,index_id,close,source) VALUES(?,?,100,'intraday_snapshot')",(DAY,IID))
    spec=importlib.util.spec_from_file_location("isolated_signal_quote_db",ROOT/"app/db.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.DB_PATH=db  # explicit temporary DB; real path resolver and production DB are never used
    conn=module.get_conn()
    try:
        columns=[r["name"] for r in conn.execute("PRAGMA table_info(index_daily)")]
        assert columns[-2:]==["source","intraday_quote_at"]
        if legacy:
            row=conn.execute("SELECT close,source,intraday_quote_at FROM index_daily").fetchone()
            assert tuple(row)==(100,"intraday_snapshot",None)
    finally:conn.close()
    conn=module.get_conn();conn.close()  # repeated real entry remains idempotent



def test_standalone_diagnostic_replays_refreshed_writer_without_production(h):
    import runpy
    result=runpy.run_path(str(ROOT/"scripts/diagnose_alert_freeze_writer_20261109.py"))["reproduce"]()
    assert result["refreshed"] is True
    assert result["first_writes"]==result["second_writes"]==1
    assert result["observed_ohlc"]==[100,111,99,110]



def test_failed_update_does_not_advance_ohlc_or_time(h):
    h.run(raw_quote())
    before=h.row()
    with h.connect() as conn:
        conn.execute("CREATE TRIGGER fail_quote BEFORE UPDATE ON index_daily BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError,match='injected'):
        h.run(raw_quote(stamp=DAY+'150000',price=110,high=111,low=99),'2026-11-04 15:35:00')
    assert h.row()==before
    with h.connect() as conn:conn.execute('DROP TRIGGER fail_quote')
    assert h.run(raw_quote(stamp=DAY+'150000',price=110,high=111,low=99),'2026-11-04 15:35:00')[0]==1


def test_actual_get_conn_migrates_pre_source_schema(tmp_path):
    import importlib.util
    db=tmp_path/'old-no-source.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE index_daily(date TEXT,index_id TEXT,open REAL,high REAL,low REAL,close REAL,pct_change REAL,amount REAL,PRIMARY KEY(date,index_id))')
        conn.execute('INSERT INTO index_daily(date,index_id,close) VALUES(?,?,100)',(DAY,IID))
    spec=importlib.util.spec_from_file_location('isolated_legacy_quote_db',ROOT/'app/db.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.DB_PATH=db
    conn=module.get_conn()
    try:assert tuple(conn.execute('SELECT close,source,intraday_quote_at FROM index_daily').fetchone())==(100,None,None)
    finally:conn.close()
