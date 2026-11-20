# -*- coding: utf-8 -*-
"""防前视硬约束: 截断不产生晚于截断日信号 / exec_date 必须晚于 signal_date /
成交日不得早于信号日(全库不变式)。"""
import json
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sim_trade_trigger as trig  # noqa: E402

DATES = ["20260105", "20260106", "20260107", "20260108", "20260109",
         "20260112", "20260113", "20260114", "20260115", "20260116",
         "20260119", "20260120", "20260121", "20260122", "20260123"]


def _make_env(tmp_path: Path, plan: list[dict]) -> Namespace:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "nextday_plan.json").write_text(json.dumps({
        "date": "20260105", "today": "20260105", "is_trading_day": True,
        "next_trading_day": "20260106", "plan": plan,
    }, ensure_ascii=False), encoding="utf-8")
    (data / "trade_dates.txt").write_text("\n".join(DATES) + "\n", encoding="utf-8")
    (data / "prices_buy.json").write_text(json.dumps({"510300": 4.02}), encoding="utf-8")
    (data / "prices_sell.json").write_text(json.dumps({"510300": 4.30}), encoding="utf-8")
    etf_db = tmp_path / "etf.db"
    con = sqlite3.connect(etf_db)
    con.execute("CREATE TABLE etf_daily (etf_code TEXT, etf_name TEXT, date TEXT, open REAL,"
                " close REAL, accum_nav REAL, PRIMARY KEY(etf_code, date))")
    con.executemany("INSERT INTO etf_daily VALUES (?,?,?,?,?,?)", [
        ("510300", "沪深300ETF", "20260105", 3.98, 4.00, 4.00),
        ("510300", "沪深300ETF", "20260106", 4.02, 4.05, 4.05),
        ("510300", "沪深300ETF", "20260119", 4.28, 4.30, 4.30),
    ])
    con.commit()
    con.close()
    return Namespace(
        date="20260105", db=str(tmp_path / "sim.db"), data_dir=str(data),
        plan_json=str(data / "nextday_plan.json"), s06_json=str(data / "kelly_mode_s06_state.json"),
        etf_db=str(etf_db), trade_dates=str(data / "trade_dates.txt"),
        log_dir=str(tmp_path / "logs"), prices_json=None, truncate_to=None,
        dry_run=False, force=True, stage="signal",
    )


def _item(sig: str, buy: str) -> dict:
    return {"etf_code": "510300", "etf_name": "沪深300ETF", "prev_close": 4.00,
            "amount": 10000, "signal": "buy", "track_score": 90.0,
            "signal_date": sig, "buy_date": buy, "rating": "high"}


def test_truncate_to_skips_future_signals(tmp_path):
    """--truncate-to=D 时, signal_date 或 exec_date 晚于 D 的计划一律不落库。"""
    a = _make_env(tmp_path, [_item("20260105", "20260106"), _item("20260106", "20260107")])
    a.truncate_to = "20260106"
    st = trig.run_signal(a)
    assert st["rows"] == 2
    assert st["inserted"] == 1 and st["skipped"] == 1, st
    con = sqlite3.connect(a.db)
    try:
        rows = con.execute("SELECT signal_date, exec_date FROM sim_trade_signal").fetchall()
    finally:
        con.close()
    assert rows == [("20260105", "20260106")]
    assert all(max(r) <= "20260106" for r in rows)


def test_exec_date_not_after_signal_rejected(tmp_path):
    """exec_date <= signal_date 属于前视(当天买当天信息), 必须 SystemExit 拒绝。"""
    a = _make_env(tmp_path, [_item("20260105", "20260105")])
    with pytest.raises(SystemExit) as ei:
        trig.run_signal(a)
    assert "防前视" in str(ei.value)


def test_no_fill_before_signal_date(tmp_path):
    """四阶段全跑完后: 信号 exec_date > signal_date, 且任何成交日都不早于信号日。"""
    a = _make_env(tmp_path, [_item("20260105", "20260106")])
    trig.run_signal(a)
    a.date, a.prices_json = "20260106", str(Path(a.data_dir) / "prices_buy.json")
    trig.run_buy_fill(a)
    a.date, a.prices_json = "20260119", str(Path(a.data_dir) / "prices_sell.json")
    trig.run_sell_order(a)
    a.prices_json = None
    trig.run_settle(a)

    con = sqlite3.connect(a.db)
    try:
        # 不变式 1: 信号 exec_date 严格晚于 signal_date
        bad_sig = con.execute(
            "SELECT COUNT(*) FROM sim_trade_signal WHERE exec_date <= signal_date").fetchone()[0]
        # 不变式 2: 成交日早于信号日 = 0 行(前视)
        bad_fill = con.execute(
            "SELECT COUNT(*) FROM sim_trade_fill f JOIN sim_trade_order o ON o.order_id=f.order_id"
            " JOIN sim_trade_signal s ON s.signal_id=o.signal_id"
            " WHERE f.fill_date <= s.signal_date").fetchone()[0]
        # 不变式 3: 买入成交日必须 == exec_date(不许提前用信号日价)
        bad_buy = con.execute(
            "SELECT COUNT(*) FROM sim_trade_fill f JOIN sim_trade_order o ON o.order_id=f.order_id"
            " JOIN sim_trade_signal s ON s.signal_id=o.signal_id"
            " WHERE f.side='buy' AND f.fill_date <> s.exec_date").fetchone()[0]
        n_fills = con.execute("SELECT COUNT(*) FROM sim_trade_fill").fetchone()[0]
    finally:
        con.close()
    assert n_fills >= 3, "四阶段至少应有 买入/14:55卖出/D+10结算 三条成交"
    assert (bad_sig, bad_fill, bad_buy) == (0, 0, 0)
