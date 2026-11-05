"""QVIX source isolation: full modules/three callers, synthetic SQLite, no external I/O.

Fixtures copy current source (not historical git or /tmp research artifacts). All patches,
including env, sys.path and imported module names, are restored by monkeypatch.
"""
import builtins
import datetime as dt
import importlib.util
import io
import os
from pathlib import Path
import shutil
import smtplib
import socket
import sqlite3
import subprocess
import sys
import threading
import types

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TARGET = "20261104"
METRICS = ("a_qvix_300", "a_qvix_1000")
ROUTES = ("runner", "series_backfill", "history_gap")
SEED = [("20261028", 20, "akshare"), ("20261029", 10, "rv_local"),
        ("20261030", 30, "manual"), ("20261101", 40, "legacy-unclassified"),
        ("20261102", 50, None)]
PRIMARY = [("20261028", 21), ("20261029", 22), ("20261103", 23)]
RV = [(date, i + 1) for i, (date, _, _) in enumerate(SEED)] + [("20261103", 6)]


class Blocked(AssertionError):
    """Fail before any network/process/production DB/repository write side effect."""


class Adapter:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, *args):
        return self.conn.execute(*args)

    def executemany(self, *args):
        return self.conn.executemany(*args)

    def commit(self):
        self.conn.commit()

    def close(self):
        pass  # Fixture owns the connection; each actual writer still calls close().


@pytest.fixture
def case(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    real_open, real_io_open = builtins.open, io.open

    def deny(*args, **kwargs):
        raise Blocked("blocked business exit")

    def local_connect(path, *args, **kwargs):
        if str(path) != ":memory:" and not Path(path).resolve().is_relative_to(tmp_path):
            return deny()
        return real_connect(path, *args, **kwargs)

    def guarded_open(original):
        def checked(file, mode="r", *args, **kwargs):
            if any(c in mode for c in "wax+") and not isinstance(file, int):
                if not Path(file).resolve().is_relative_to(tmp_path):
                    return deny()
            return original(file, mode, *args, **kwargs)
        return checked

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(smtplib, "SMTP", deny)
    monkeypatch.setattr(smtplib, "SMTP_SSL", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(os, "system", deny)
    monkeypatch.setattr(sqlite3, "connect", local_connect)
    monkeypatch.setattr(builtins, "open", guarded_open(real_open))
    monkeypatch.setattr(io, "open", guarded_open(real_io_open))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    # etf_national_team inserts its scripts path on import; restore the original list.
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setenv("GIT_REPO", str(tmp_path))
    # Positive controls must pass BEFORE any business module is imported.
    for attempt in (socket.socket, lambda: socket.create_connection(("invalid.example", 443)),
                    lambda: socket.getaddrinfo("invalid.example", 443), smtplib.SMTP,
                    smtplib.SMTP_SSL, lambda: subprocess.run(["forbidden"]),
                    lambda: os.system("forbidden"),
                    lambda: sqlite3.connect(ROOT / "data/forbidden-test.db"),
                    lambda: (ROOT / ".forbidden-qvix-test").write_text("never")):
        with pytest.raises(Blocked):
            attempt()

    source = tmp_path / "app/collector"
    source.mkdir(parents=True)
    for name in ("fetchers", "runner", "index_backfill", "etf_national_team", "mootdx_daily"):
        shutil.copyfile(ROOT / f"app/collector/{name}.py", source / f"{name}.py")
    (tmp_path / "config").mkdir()
    namespace = "_codex_qvix_test"
    state = types.SimpleNamespace(primary=pd.DataFrame(PRIMARY, columns=["date", "close"]),
                                  sse=None, rv=list(RV), logs=[], db=None, connections=[])

    def module(name, **attrs):
        result = types.ModuleType(name)
        result.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    module(namespace, __path__=[str(tmp_path / "app")])
    package = module(namespace + ".collector", __path__=[str(source)])
    module(namespace + ".db", get_conn=lambda: Adapter(state.db))
    module(namespace + ".calendar", last_trading_day=lambda *a: TARGET,
           is_trading_day=lambda *a: True)
    module(namespace + ".collector.base", safe_call=lambda fn, *a, **kw: fn(*a, **kw),
           log_collect=lambda *a, **kw: state.logs.append(a), em_get=lambda *a, **kw: None,
           throttle=lambda *a, **kw: None)
    module(namespace + ".collector.index_pct", PCT_CHANGE_PRESERVE_SQL="",
           fill_first_pct=lambda *a: None, fill_row_pct=lambda *a: None)
    module(namespace + ".collector.multisource",
           sse_qvix_series=lambda *a, **kw: (state.sse, "fixture SSE"))
    module(namespace + ".collector.fapi_fallback", try_fallback=lambda *a: (None, ""))
    ak = module("akshare")
    for fn in ("index_option_300etf_qvix", "index_option_50etf_qvix", "stock_margin_sse",
               "stock_margin_szse", "bond_zh_us_rate"):
        setattr(ak, fn, lambda *a, **kw: state.primary)

    def load(name):
        fullname = namespace + ".collector." + name
        spec = importlib.util.spec_from_file_location(fullname, source / f"{name}.py")
        result = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fullname, result)
        monkeypatch.setattr(package, name, result, raising=False)
        spec.loader.exec_module(result)
        return result

    f, r, b = (load(name) for name in ("fetchers", "runner", "index_backfill"))
    real_rv = f._qvix_rv_series
    monkeypatch.setattr(f, "_guarded_by_func", lambda *a, **kw: state.primary)
    monkeypatch.setattr(f, "_qvix_latest_trading_date", lambda: TARGET)
    monkeypatch.setattr(f, "_qvix_rv_series", lambda *a, **kw: state.rv)

    def new_db(mid, rows=SEED, path=":memory:"):
        conn = sqlite3.connect(path)
        state.connections.append(conn)
        conn.execute("CREATE TABLE daily_metric(date TEXT,metric_id TEXT,value REAL,"
                     "source TEXT,updated_at TEXT,PRIMARY KEY(date,metric_id))")
        conn.execute("CREATE TABLE index_daily(date TEXT,index_id TEXT)")
        conn.executemany("INSERT INTO daily_metric VALUES(?,?,?,?,?)",
                         [(d, mid, v, src, "old") for d, v, src in rows])
        conn.commit()
        state.db = conn
        return conn

    def metric(mid):
        return dict(id=mid, func="index_option_300etf_qvix" if mid.endswith("300")
                    else "index_option_50etf_qvix", column="close", enabled=True,
                    type="simple", drop_zero=True)

    def route(route_name, mid):
        m = metric(mid)
        (tmp_path / "config/indicators.yaml").write_text(
            yaml.safe_dump(dict(indices=[], metrics=[m])), encoding="utf-8")
        if route_name == "runner":
            return r._collect_one_metric(m, TARGET)
        if route_name == "series_backfill":
            return b.backfill_series_metrics(TARGET)
        return b.backfill_history_gaps(TARGET, verbose=False)

    def values():
        return {d: (v, src) for d, v, src in state.db.execute(
            "SELECT date,value,source FROM daily_metric ORDER BY date")}

    def actual_etf():
        module("util_atomic", atomic_write_json=lambda *a, **kw: None)
        module(namespace + ".collector.nav_placeholder_defense",
               is_placeholder_row=lambda *a: False, trading_gap_between=lambda *a: 0)
        class Quotes:
            @staticmethod
            def factory(*args, **kwargs):
                raise ConnectionError("offline TDX fixture")
        module("mootdx", __path__=[])
        module("mootdx.quotes", Quotes=Quotes)
        td = load("mootdx_daily")
        monkeypatch.setattr(td, "_probe", lambda *a, **kw: False)
        etf = load("etf_national_team")
        monkeypatch.setattr(ak, "fund_etf_hist_sina", lambda *a, **kw: None, raising=False)
        monkeypatch.setattr(f, "_qvix_rv_series", real_rv)
        return etf

    yield types.SimpleNamespace(f=f, r=r, b=b, state=state, new_db=new_db, metric=metric,
                                route=route, values=values, load=load, module=module,
                                ak=ak, actual_etf=actual_etf, root=tmp_path,
                                monkeypatch=monkeypatch)
    for conn in state.connections:
        conn.close()


def assert_primary(case):
    got = case.values()
    assert got["20261028"] == (21, "akshare")
    assert got["20261029"] == (22, "akshare")
    assert got["20261103"] == (23, "akshare")
    for date, value, source in SEED[2:]:
        assert got[date] == (value, source)


@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("scenario", ("mixed_sse", "mixed_rv", "missing_target", "wrongday",
                                     "full_outage", "primary_correct"))
def test_three_actual_writers(case, mid, route, scenario):
    case.new_db(mid)
    if scenario == "mixed_sse":
        case.state.sse = [(TARGET, 24)]
    if scenario in ("mixed_rv", "full_outage", "primary_correct"):
        case.state.rv.append((TARGET, 7))
    if scenario == "wrongday":
        case.state.sse = [("20261103", 24)]
    if scenario == "full_outage":
        case.state.primary = None
    if scenario == "primary_correct":
        case.state.primary = pd.DataFrame(PRIMARY + [("20261102", 19.27)], columns=["date", "close"])
        case.state.db.execute("UPDATE daily_metric SET source='sse',value=22.44 WHERE date='20261102'")
        case.state.db.commit()
    result = case.route(route, mid)
    got = case.values()
    if scenario == "full_outage":
        for date, value, source in SEED:
            assert got[date] == (value, source)
        assert got[TARGET] == (7, "rv_local")
        assert got["20261103"] == (6, "rv_local")
    else:
        if scenario == "primary_correct":
            assert got["20261102"] == (19.27, "akshare")
            assert got["20261028"] == (21, "akshare")
            assert got["20261029"] == (22, "akshare")
            assert got["20261030"] == (30, "manual")
        else:
            assert_primary(case)
        if scenario == "mixed_sse":
            assert got[TARGET] == (24, "sse")
        elif scenario in ("mixed_rv", "primary_correct"):
            assert got[TARGET] == (7, "rv_local")
        else:
            assert TARGET not in got
            assert "qvix_aux_unavailable:" in str(case.state.logs)
            if route == "series_backfill":
                assert result == (1, False)


PAYLOADS = ("rv_exception", "sse_exception", "rv_bad_tuple", "rv_none", "rv_nan", "rv_inf", "rv_zero",
            "rv_negative", "sse_nan", "sse_inf", "sse_none", "sse_zero", "sse_negative",
            "empty", "wrongday", "rv_partial")


@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("payload", PAYLOADS)
def test_aux_failure_and_payload_isolation(case, mid, route, payload):
    case.new_db(mid)
    valid = {"rv_zero": (0., "rv_local"), "rv_negative": (-1., "rv_local"),
             "sse_zero": (0., "sse"), "sse_negative": (-1., "sse"),
             "rv_partial": (7., "rv_local")}
    if payload == "rv_exception":
        def broken(*args):
            raise RuntimeError("fixture auxiliary failure")
        case.monkeypatch.setattr(case.f, "_qvix_rv_series", broken)
    elif payload == "sse_exception":
        def broken_sse(*args, **kwargs):
            raise ConnectionError("fixture SSE failure")
        case.monkeypatch.setattr(sys.modules[case.f.__package__ + ".multisource"],
                                "sse_qvix_series", broken_sse)
    elif payload == "rv_bad_tuple":
        case.state.rv = [("broken",)]
    elif payload == "rv_partial":
        case.state.rv = [(TARGET, None), (TARGET, 7)]
    elif payload.startswith(("rv_", "sse_")):
        value = dict(none=None, nan=float("nan"), inf=float("inf"), zero=0., negative=-1.)[
            payload.split("_")[1]]
        setattr(case.state, "rv" if payload.startswith("rv_") else "sse", [(TARGET, value)])
    elif payload == "wrongday":
        case.state.sse = [("20261103", 24)]
    result = case.route(route, mid)
    assert_primary(case)
    if payload in valid:
        assert case.values()[TARGET] == valid[payload]
        if payload == "rv_partial":
            assert "rejected=1" in str(case.state.logs)
    else:
        assert TARGET not in case.values()
        assert "qvix_aux_unavailable:" in str(case.state.logs)
        if route == "series_backfill":
            assert result == (1, False)


@pytest.mark.parametrize("mid", METRICS)
def test_batches_keep_primary_history_dates_scale_and_no_legacy_bypass(case, mid):
    m = dict(case.metric(mid), scale=2)
    case.state.sse = [("20261103", 99), (TARGET, 12), ("20261105", 88)]
    parts = case.f.collect_series_batches(m)
    assert parts[0] == ([(d, v * 2) for d, v in PRIMARY], "ok", "akshare")
    assert parts[1][0] == [(TARGET, 24)] and parts[1][2] == "sse"
    with pytest.raises(ValueError, match="requires collect_series_batches"):
        case.f.collect_series(m)
    # Every just_date branch (SSE success or RV fallback) returns ONLY that date.
    for sse in (case.state.sse, None, [("20261103", 2)]):
        case.state.sse = sse
        case.state.rv = list(RV) + [(TARGET, 7), ("20261105", 8)]
        source, rows, _ = case.f._qvix_fallback(m, just_date=TARGET)
        assert rows == [(TARGET, 24 if source == "sse" else 14)]
    case.state.rv = list(RV)
    case.state.sse = None
    assert case.f._qvix_fallback(m, just_date=TARGET)[1] == []


@pytest.mark.parametrize("writer", ("single", "batch"))
@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("fallback", ("rv_local", "sse"))
@pytest.mark.parametrize("existing", ("akshare", "rv_local", "sse", "manual", "legacy", None))
def test_atomic_writers_preserve_all_existing_sources(case, writer, mid, fallback, existing):
    case.new_db(mid, [("20261102", 22.44, existing)])
    if writer == "single":
        case.r.upsert_metric("20261102", mid, 1, source=fallback)
        case.r.upsert_metric(TARGET, mid, 0, source=fallback)
    else:
        case.r.upsert_metrics_many(mid, [("20261102", 1), (TARGET, 0)], source=fallback)
    assert case.values()["20261102"] == (22.44, existing)
    assert case.values()[TARGET] == (0, fallback)


@pytest.mark.parametrize("writer", ("single", "batch"))
@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("fallback", ("rv_local", "sse"))
def test_atomic_competing_connection_cannot_clobber_authority(case, writer, mid, fallback):
    path = case.root / "race.db"
    case.new_db(mid, [], path=path)
    ready, proceed = threading.Event(), threading.Event()
    errors = []

    class RaceConn(Adapter):
        def execute(self, sql, args):
            ready.set()
            assert proceed.wait(3), "race release timed out"
            return super().execute(sql, args)

        def executemany(self, sql, args):
            ready.set()
            assert proceed.wait(3), "race release timed out"
            return super().executemany(sql, args)

        def close(self):
            self.conn.close()

    case.monkeypatch.setattr(case.r, "get_conn", lambda: RaceConn(sqlite3.connect(path, timeout=3)))

    def fallback_job():
        try:
            if writer == "single":
                case.r.upsert_metric(TARGET, mid, 1, source=fallback)
            else:
                case.r.upsert_metrics_many(mid, [(TARGET, 1)], source=fallback)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=fallback_job, daemon=True)
    worker.start()
    try:
        assert ready.wait(3), "fallback did not reach atomic SQL"
        case.state.db.execute("INSERT INTO daily_metric VALUES(?,?,?,?,?)",
                              (TARGET, mid, 99, "akshare", "authority"))
        case.state.db.commit()
    finally:
        proceed.set()
        worker.join(4)
    assert not worker.is_alive() and not errors, errors
    assert case.values()[TARGET] == (99, "akshare")


@pytest.mark.parametrize("mid,fn", (("a_fund_margin", "stock_margin_sse"),
                                   ("a_fund_margin_sz", "stock_margin_szse"),
                                   ("us10y", "bond_zh_us_rate")))
def test_non_qvix_legacy_and_batch_compatibility(case, mid, fn):
    m = dict(id=mid, func=fn, column="close", enabled=True, type="simple", params={})
    expected = ([(d, float(v)) for d, v in PRIMARY], "ok", "akshare")
    assert case.f.collect_series(m) == expected
    assert case.f.collect_series_batches(m) == [expected]
    case.new_db(mid, [("20261028", 4, "akshare"), ("20261030", 8, "manual")])
    case.r.upsert_metrics_many(mid, [("20261028", 3), ("20261030", 1)], source="sse")
    case.r.upsert_metric(TARGET, mid, 6, source="rv_local")
    assert case.values() == {"20261028": (3, "sse"), "20261030": (8, "manual"),
                             TARGET: (6, "rv_local")}


@pytest.mark.parametrize("mid,fn", (("a_fund_margin", "stock_margin_sse"),
                                   ("a_fund_margin_sz", "stock_margin_szse"),
                                   ("us10y", "bond_zh_us_rate")))
@pytest.mark.parametrize("route", ROUTES)
def test_non_qvix_actual_three_routes(case, mid, fn, route):
    case.new_db(mid)
    config = case.root / "config/indicators.yaml"
    m = dict(id=mid, func=fn, column="close", enabled=True, type="simple", params={})
    config.write_text(yaml.safe_dump(dict(indices=[], metrics=[m])), encoding="utf-8")
    if route == "runner":
        case.r._collect_one_metric(m, TARGET)
    elif route == "series_backfill":
        assert case.b.backfill_series_metrics(TARGET) == (1, False)
    else:
        assert case.b.backfill_history_gaps(TARGET, verbose=False) == 1
    assert_primary(case)
    assert TARGET not in case.values()
    assert "qvix_" not in str(case.state.logs)


@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("writer", ("single", "batch"))
def test_primary_large_history_corrects_proxy_and_known_primary(case, mid, writer):
    dates = [(dt.date(2020, 1, 1) + dt.timedelta(days=i)).strftime("%Y%m%d")
             for i in range(600)]
    case.new_db(mid, [(d, 10, ("rv_local", "sse", "akshare")[i % 3])
                     for i, d in enumerate(dates)])
    rows = [(d, 19.27) for d in dates]
    if writer == "batch":
        case.r.upsert_metrics_many(mid, rows, source="akshare")
    else:
        for d, v in rows:
            case.r.upsert_metric(d, mid, v, source="akshare")
    assert len(case.values()) == 600
    assert set(case.values().values()) == {(19.27, "akshare")}


@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("route", ROUTES)
def test_real_etf_tdx_dual_source_failure_keeps_primary(case, mid, route):
    case.new_db(mid)
    case.actual_etf()  # Real fetch_etf_ohlc -> real tdx_client -> real RV; network edges only stubbed.
    result = case.route(route, mid)
    assert_primary(case)
    assert TARGET not in case.values()
    assert "qvix_aux_unavailable:" in str(case.state.logs)
    assert "error=" in str(case.state.logs)
    if route == "series_backfill":
        assert result == (1, False)


@pytest.mark.parametrize("mid", METRICS)
@pytest.mark.parametrize("raw_close,expected", ((100., (0., "rv_local")), (float("inf"), None)))
def test_actual_etf_and_rv_zero_vs_nonfinite(case, mid, raw_close, expected):
    case.new_db(mid)
    case.actual_etf()
    frame = pd.DataFrame([dict(date=(dt.date(2026, 10, 11) + dt.timedelta(days=i)).strftime("%Y%m%d"),
                               open=raw_close, high=raw_close, low=raw_close, close=raw_close, amount=1)
                          for i in range(25)])
    # Reverse raw ETF order: unchanged RV formula sorts by effective date before computing.
    case.monkeypatch.setattr(case.ak, "fund_etf_hist_sina", lambda *a, **kw: frame.iloc[::-1])
    case.route("runner", mid)
    assert_primary(case)
    assert case.values().get(TARGET) == expected
    if expected is None:
        assert "rejected=" in str(case.state.logs)
