"""FX review regressions: real readers, signal computation/store and simulation.

All DB/cache roots are temporary; network, processes and notifications fail shut.
Only delivery-evidence wrappers are unwrapped to avoid writing repository data.
"""
import importlib.util
import inspect
import json
import socket
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

from app import db as dbmod
from app import fx_contract as fx

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location("fx_revision_" + name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def isolation(monkeypatch, tmp_path):
    for key in ("REPO", "GIT_REPO", "MAIN_REPO"):
        monkeypatch.setenv(key, str(tmp_path))
    def deny(*args, **kwargs):
        raise AssertionError("external action forbidden")
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(subprocess, "run", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    notify = types.ModuleType("notify")
    notify.send = deny
    monkeypatch.setitem(sys.modules, "notify", notify)
    with pytest.raises(AssertionError, match="external action forbidden"):
        socket.getaddrinfo("forbidden.invalid", 443)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    path = tmp_path / "sentiment.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(dbmod.SCHEMA)
    monkeypatch.setattr(dbmod, "DB_PATH", path)
    monkeypatch.setattr(dbmod, "_resolved_db_path", None)
    static = tmp_path / "static"
    static.mkdir()
    (static / "summary.json").write_text(json.dumps({"date": "20261110", "fx_contract": fx.SCORE_VERSION,
        "fear_greed_value": 99, "buy_count": 1, "sell_count": 0}))
    brief = script("gen_daily_brief")
    monkeypatch.setattr(brief, "ROOT", tmp_path)
    return path, static, brief


@pytest.mark.parametrize("raw", [667.24, 6.6724])
def test_daily_brief_legacy_fx_is_not_converted(runtime, raw):
    path, static, brief = runtime
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO daily_metric VALUES('20261110',?,?,?,'original')",
                         [("usdcnh", raw, "legacy"), ("gold", 720, "independent")])
    before = path.read_bytes()
    data = brief.load_data(static, path, "20261110")
    assert data["forex_commodity"]["gold"] == 720
    assert "usdcnh" not in data["forex_commodity"]
    assert data["fx_availability"]["active"] is False
    risk = brief.split_domains(data)["risk"]
    assert risk["fx_availability"]["status"] == "unavailable"
    assert "usdcnh" not in risk["forex_commodity"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("version", [None, fx.SCORE_VERSION])
def test_brief_each_cache_is_guarded_even_with_new_summary(runtime, version):
    path, static, brief = runtime
    alert = {"fx_contract": version, "high": {"score": 99, "level": "高危", "dims": [
        {"k": "H1", "name": "旧分", "score": 99, "hit": True}]}, "low": {"score": 98, "level": "机遇"}}
    overview = {"signals_today": [{"index_id": i, "name": i, "signal": "buy", "reason": "独立触发, 情绪分=99[过热]"}
        for i in ("g.usdcnh", "s.cross_market", "s.fear_greed", "sh")],
        "recent_freeze": [{"date": "20261110", "score_id": s} for s in (*fx.DEPENDENT_SCORES, "a_sentiment")]}
    stats = {i: {"buy": {"20d": {"win_rate": 1, "n": 20}}} for i in ("g.usdcnh", "s.cross_market", "s.fear_greed", "sh")}
    for name, value in (("alert", alert), ("overview", overview), ("signal_stats", stats)):
        (static / (name + ".json")).write_text(json.dumps(value))
    original = {p.name: p.read_bytes() for p in static.iterdir()}
    data = brief.load_data(static, path, "20261110")
    assert data["summary"]["fear_greed_value"] is None
    for side in ("high", "low"):
        assert data["alert"][side] == {"score": None, "level": "数据不足", "hit_dims": [], "availability": "unavailable"}
    assert [r["index_id"] for r in data["signals_today"]] == ["sh"]
    assert data["signals_today"][0]["reason"] == "独立触发"
    assert data["signals_today_count"] == 1 and data["name_map"] == {"sh": "sh"}
    assert data["recent_freeze"] == ["20261110"]  # independent A-share freeze remains
    assert [r["index_id"] for r in data["signal_stats_buy_top"]] == ["sh"]
    assert {p.name: p.read_bytes() for p in static.iterdir()} == original


@pytest.mark.parametrize("value", [0, 50, 99])
def test_flags_do_not_activate_real_readers(runtime, monkeypatch, value):
    from app import queries, alert_score
    from app.compute import normalize, signals
    path, static, brief = runtime
    monkeypatch.setattr(alert_score, "resolve_db_path", lambda: path)
    flags = {"_fx_contract": fx.SCORE_VERSION, "_fx_available": True}
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO score_daily VALUES('20261110',?,?,1,1,?,'original')",
                         [(s, value, json.dumps(flags)) for s in fx.DEPENDENT_SCORES])
        conn.execute("INSERT INTO score_daily VALUES('20261110','a_sentiment',0,1,0,'{}','original')")
    # get_conn intentionally enables WAL; establish that before byte comparison.
    dbmod.get_conn().close()
    before = path.read_bytes()
    conn = dbmod.get_conn()
    try:
        for sid in fx.DEPENDENT_SCORES:
            for cache in (None, {("score", sid): [{"date": "20261110", "value": value, "components": flags}]}):
                rows = queries.score_series(conn, sid, "20261110", "20261110", cache=cache)
                assert rows[0]["value"] is None and rows[0]["is_freeze"] is None
            assert normalize.load_score_value(sid).empty
            assert alert_score.load_score(sid).empty
        assert signals._load_cross_score().empty
        assert queries.score_series(conn, "a_sentiment", "20261110", "20261110")[0]["value"] == 0
        assert alert_score.load_score("a_sentiment").iloc[0] == 0
    finally:
        conn.close()
    data = brief.load_data(static, path, "20261110")
    assert data["scores"]["fear_greed"] is None and data["scores"]["a_sentiment"] == 0
    assert path.read_bytes() == before


def signal_runtime(monkeypatch):
    from app.compute import signals
    from app import history_audit
    monkeypatch.setattr(signals, "load_config", lambda: {"indices": [{"id": "sh", "enabled": True}], "metrics": []})
    monkeypatch.setattr(signals, "capture_loaded", lambda k, v, **kw: v)
    for name in ("capture_sql_rows", "capture_connection", "capture_event", "capture_signal_visibility"):
        monkeypatch.setattr(signals, name, lambda *a, **kw: None)
    monkeypatch.setattr(history_audit, "today_ymd", lambda: "20261111")
    monkeypatch.setattr(history_audit, "send_alert", lambda *a, **kw: pytest.fail("notification forbidden"))
    return signals, history_audit


def test_real_recompute_preserves_only_historical_fx_annotation(runtime, monkeypatch):
    path, static, brief = runtime
    signals, audit = signal_runtime(monkeypatch)
    days = pd.bdate_range("2026-02-02", periods=105).strftime("%Y%m%d")
    prices = [100.] * 65 + [100-2*(i+1) for i in range(20)] + [60+5*(i+1) for i in range(10)] + [110.] * 10
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO index_daily(date,index_id,open,high,low,close,pct_change,amount) VALUES(?,'sh',?,?,?,?,0,1000000)",
                         [(d, p, p*1.01, p*.99, p) for d, p in zip(days, prices)])
        conn.executemany("INSERT INTO score_daily VALUES(?,'cross_market',55,0,0,'{}','original')", [(d,) for d in days])
    with monkeypatch.context() as legacy:
        legacy.setattr(signals, "_load_cross_score", lambda: pd.Series(55., index=days))
        previous = inspect.unwrap(signals.compute)()
    current = inspect.unwrap(signals.compute)()
    assert len(current) == 3 and {r[:3] for r in current} == {r[:3] for r in previous}
    assert all("情绪分=55" in r[3] for r in previous)
    assert all("情绪分=" not in r[3] for r in current)
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO signal_daily VALUES(?,?,?,?)", previous)
        conn.execute("INSERT INTO signal_daily VALUES('20261110','g.usdcnh','sell','old FX')")
        original = conn.execute("SELECT * FROM signal_daily ORDER BY date,index_id,signal").fetchall()
        before = audit.snapshot_signal_daily_history(conn, "20261111")
        frozen = conn.execute("SELECT * FROM score_daily ORDER BY date").fetchall()
    for _ in range(2):
        inspect.unwrap(signals.store)(current)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT * FROM signal_daily ORDER BY date,index_id,signal").fetchall() == original
            assert conn.execute("SELECT * FROM score_daily ORDER BY date").fetchall() == frozen
            assert audit.audit_signal_daily_store(conn, before, audit.snapshot_signal_daily_history(conn, "20261111"), "20261111") == []
    from app import queries
    conn = dbmod.get_conn()
    try:
        visible = queries.signals(conn, None, days[0], "20261111")
        assert len(visible) == 3 and all("情绪分=" not in r["reason"] for r in visible)
    finally:
        conn.close()
    # Actual three simulation paths ignore the soft annotation; no archive write.
    sim = script("simulate_trade")
    monkeypatch.setattr(sim, "_load_index_etf_map", lambda: {})
    rows, last = sim.get_signals("sh")
    stripped = [(d, s, fx.without_cross_annotation(r), p) for d, s, r, p in rows]
    extreme = [(d, s, r.replace("55", "99999"), p) for d, s, r, p in rows]
    for simulate in (sim.simulate_fixed_1w, sim.simulate_all_in, sim.simulate_sell_all):
        run = lambda data: simulate("fixture", data, {"buy", "buy_aux", "buy_backup"}, *last)
        assert run(rows) == run(stripped) == run(extreme)
    for iid in ("g.usdcnh", "s.cross_market", "s.fear_greed"):
        with pytest.raises(ValueError, match="FX合同未验证"):
            sim.get_signals(iid)


def test_non_fx_corrections_and_event_changes_retain_existing_store_policy(runtime, monkeypatch):
    path, _, _ = runtime
    signals, audit = signal_runtime(monkeypatch)
    changes_seen = []
    original_audit = audit.audit_signal_daily_store
    def capture(conn, before, after, run_date):
        changes = original_audit(conn, before, after, run_date)
        changes_seen.extend(changes)
        return changes
    monkeypatch.setattr(audit, "audit_signal_daily_store", capture)
    # Audit notification transport is stubbed; actual diff and table write run.
    monkeypatch.setattr(audit, "send_alert", lambda *a, **kw: True)
    with sqlite3.connect(path) as conn:
        conn.executemany("INSERT INTO signal_daily VALUES(?,?,?,?)", [
            ("20261109", "sh", "buy", "RSI=30, 情绪分=55[中性]"),
            ("20261109", "sz", "buy", "old event"),
            ("20261111", "sh", "buy", "RSI=30, 情绪分=55[中性]")])
    inspect.unwrap(signals.store)([("20261109", "sh", "buy", "RSI=35"),
        ("20261109", "sz", "sell", "corrected event"), ("20261111", "sh", "buy", "RSI=30")])
    with sqlite3.connect(path) as conn:
        stored = conn.execute("SELECT * FROM signal_daily ORDER BY date,index_id,signal").fetchall()
    assert stored == [("20261109", "sh", "buy", "RSI=35"),
        ("20261109", "sz", "sell", "corrected event"), ("20261111", "sh", "buy", "RSI=30")]
    assert {(c["kind"], c["index_id"], c["signal"]) for c in changes_seen} == {
        ("disappeared", "sz", "buy"), ("appeared", "sz", "sell")}
