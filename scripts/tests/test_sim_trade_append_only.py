# -*- coding: utf-8 -*-
"""模拟交易账本 append-only 硬约束(4 表 × UPDATE/DELETE/REPLACE 全拦截 + 闸门自检)。"""
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sim_trade_db as db  # noqa: E402
import check_sim_trade_append_only as gate  # noqa: E402

TABLES = ("sim_trade_signal", "sim_trade_order", "sim_trade_fill", "sim_trade_event")


def _seed(con):
    now = db.now_iso()
    con.execute(
        "INSERT INTO sim_trade_signal (signal_id, signal_date, exec_date, sell_due_date, index_id,"
        " etf_code, source, frozen_at, trigger_source, created_at)"
        " VALUES ('s1','20260105','20260106','20260119','IDX','510300','log',?, 'test', ?)", (now, now))
    con.execute(
        "INSERT INTO sim_trade_order (order_id, signal_id, side, action, etf_code, intended_at,"
        " triggered_at, trigger_source, created_at)"
        " VALUES ('o1','s1','buy','open','510300','09:30',?,'test',?)", (now, now))
    con.execute(
        "INSERT INTO sim_trade_fill (fill_id, order_id, side, fill_date, price_kind, price_raw,"
        " source, created_at) VALUES ('f1','o1','buy','20260106','open',4.0,'test',?)", (now,))
    con.execute(
        "INSERT INTO sim_trade_event (event_id, order_id, signal_id, event_type, event_at, created_at)"
        " VALUES ('e1','o1','s1','trigger_run',?,?)", (now, now))
    con.commit()


@pytest.fixture()
def con(tmp_path):
    c = db.init_db(tmp_path / "sim.db")
    _seed(c)
    yield c
    c.close()


def test_structure_ok(tmp_path):
    c = db.init_db(tmp_path / "sim.db")
    try:
        info = db.check_db(c)
        assert info["ok"] is True
        assert info["trigger_count"] == 8
        assert info["integrity_check"] == "ok"
    finally:
        c.close()


def test_update_delete_replace_abort(con):
    pks = {"sim_trade_signal": "signal_id", "sim_trade_order": "order_id",
           "sim_trade_fill": "fill_id", "sim_trade_event": "event_id"}
    for table, pk in pks.items():
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(f"UPDATE {table} SET {pk}={pk} WHERE {pk} IS NOT NULL")
        con.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(f"DELETE FROM {table} WHERE {pk} IS NOT NULL")
        con.rollback()
    # INSERT OR REPLACE 的内部 DELETE 也必须被拦(依赖 recursive_triggers=ON)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT OR REPLACE INTO sim_trade_signal (signal_id, signal_date, exec_date,"
            " sell_due_date, index_id, etf_code, source, frozen_at, trigger_source, created_at)"
            " VALUES ('s1','20260105','20260106','20260119','IDX','510300','log','x','test','x')")
    con.rollback()
    assert con.execute("SELECT COUNT(*) FROM sim_trade_signal").fetchone()[0] == 1


def test_commit_runs_no_rollback():
    """闸门自身: 静态扫描 0 命中 + 临时库动态 ABORT + integrity ok。"""
    out = gate.run(SCRIPTS)
    assert out["static_forbidden_hits"] == []
    assert out["structure_ok"] is True
    assert out["trigger_count"] == 8
    assert out["pass"] is True
    assert all(v == "ABORT" for v in out["aborts"].values()), out["aborts"]
