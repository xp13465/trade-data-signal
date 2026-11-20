# -*- coding: utf-8 -*-
"""模拟交易账本四阶段端到端幂等: signal → buy_fill → sell_order → settle 重跑不新增行。"""
import json
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sim_trade_db as db  # noqa: E402
import sim_trade_trigger as trig  # noqa: E402

DATES = ["20260105", "20260106", "20260107", "20260108", "20260109",
         "20260112", "20260113", "20260114", "20260115", "20260116",
         "20260119", "20260120", "20260121", "20260122", "20260123"]


def _make_env(tmp_path: Path) -> Namespace:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "nextday_plan.json").write_text(json.dumps({
        "date": "20260105", "today": "20260105", "is_trading_day": True,
        "next_trading_day": "20260106",
        "plan": [{"etf_code": "510300", "etf_name": "沪深300ETF", "prev_close": 4.00,
                  "amount": 10000, "signal": "buy", "track_score": 90.0,
                  "signal_date": "20260105", "buy_date": "20260106", "rating": "high"}],
    }, ensure_ascii=False), encoding="utf-8")
    (data / "trade_dates.txt").write_text("\n".join(DATES) + "\n", encoding="utf-8")
    (data / "prices_buy.json").write_text(json.dumps({"510300": 4.02}), encoding="utf-8")
    (data / "prices_sell.json").write_text(json.dumps({"510300": 4.30}), encoding="utf-8")
    etf_db = tmp_path / "etf.db"
    con = sqlite3.connect(etf_db)
    con.execute("CREATE TABLE etf_daily (etf_code TEXT, etf_name TEXT, date TEXT, open REAL,"
                " close REAL, accum_nav REAL, PRIMARY KEY(etf_code, date))")
    # 信号日 20260105: close/accum_nav = 4.00;执行日 20260106: open=4.02;卖出日 20260119: close=4.30
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


def _counts(path) -> dict:
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in db.TRIGGER_TABLES}
    finally:
        con.close()


def test_four_stage_twice(tmp_path):
    a = _make_env(tmp_path)

    # signal 定格(两次 → 只 1 行)
    r1 = trig.run_signal(a)
    r2 = trig.run_signal(a)
    assert (r1["inserted"], r2["inserted"], r2["ignored"]) == (1, 0, 1)

    # T+1 09:50 买入(两次 → 只 1 个 buy fill)
    a.date, a.prices_json = "20260106", str(Path(a.data_dir) / "prices_buy.json")
    b1 = trig.run_buy_fill(a)
    b2 = trig.run_buy_fill(a)
    assert b1["fills"] == 1 and b2["fills"] == 0
    con = sqlite3.connect(a.db)
    try:
        assert con.execute("SELECT COUNT(*) FROM sim_trade_fill WHERE side='buy'").fetchone()[0] == 1
        assert con.execute("SELECT status FROM sim_trade_fill WHERE side='buy'").fetchone()[0] == "provisional"
    finally:
        con.close()

    # D+10 14:55 卖出单(provisional 实时价)
    a.date, a.prices_json = "20260119", str(Path(a.data_dir) / "prices_sell.json")
    s1 = trig.run_sell_order(a)
    s2 = trig.run_sell_order(a)
    assert s1["fills"] == 1 and s2["fills"] == 0

    # 22:45 结算:当天买入转 confirmed + D+10 收盘结算(即使已有 provisional 14:55 成交也必须结算)
    a.prices_json = None
    t1 = trig.run_settle(a)
    t2 = trig.run_settle(a)
    assert t1["buy_confirmed"] == 0  # 买入复核只在 exec_date 当天执行, 此处 date=卖出日
    assert t1["sell_settled"] == 1, t1
    assert t2["sell_settled"] == 0, t2

    counts = _counts(a.db)
    # 信号 1 / 买卖各 1 order / 买入 provisional 1 + 卖出 provisional 1 + 卖出 confirmed 1 = 3 fills
    assert counts["sim_trade_signal"] == 1
    assert counts["sim_trade_order"] == 2
    assert counts["sim_trade_fill"] == 3
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    try:
        pos = con.execute("SELECT * FROM v_sim_trade_position").fetchone()
        assert pos["closed"] == 1
        assert pos["sell_fill_kind"] == "close"  # 有效成交取 confirmed(close), 不是 14:55 intraday
        assert pos["sell_price_raw"] == 4.30
        # 追加审计: 8 条触发器仍有, 无 UPDATE/DELETE 痕迹
        assert len(db.trigger_names(con)) == 8
    finally:
        con.close()

    # 买入日期当天复核: 另跑一次 settle(exec_date=20260106) 验证 provisional→confirmed
    a2 = _make_env(tmp_path / "case2")
    trig.run_signal(a2)
    a2.date, a2.prices_json = "20260106", str(Path(a2.data_dir) / "prices_buy.json")
    trig.run_buy_fill(a2)
    a2.prices_json = None
    c1 = trig.run_settle(a2)
    c2 = trig.run_settle(a2)
    assert c1["buy_confirmed"] == 1 and c2["buy_confirmed"] == 0
    con = sqlite3.connect(a2.db)
    try:
        rows = con.execute("SELECT status, fill_id, supersedes_fill_id FROM sim_trade_fill"
                           " WHERE side='buy' ORDER BY created_at").fetchall()
        assert [r[0] for r in rows] == ["provisional", "confirmed"]
        assert rows[1][2] == rows[0][1]  # confirmed 指向旧 provisional
    finally:
        con.close()
