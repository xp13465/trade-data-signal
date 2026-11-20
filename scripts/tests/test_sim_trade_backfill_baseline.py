# -*- coding: utf-8 -*-
"""历史回填对账: 双口径双写 / 幂等重跑 / reconcile 与手工计算一致 / 视图口径列。"""
import json
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sim_trade_backfill as bf  # noqa: E402
import kelly_posrating as kp  # noqa: E402

FIELDS = ["signal_date", "etf_code", "etf_name", "index_id", "signal", "track_score",
          "rating", "track_tier", "buy_price", "sell_price", "shares", "profit",
          "real_buy_date", "real_buy_price", "current_price", "sell_date"]


class FakeResolver:
    def base_for_date(self, date):
        return True, "new14", "test"


def _row(sig, exec_d, buy, sell, sell_date, shares, profit, cur=None, code="510300"):
    v = {"signal_date": sig, "etf_code": code, "etf_name": "沪深300ETF",
         "index_id": "IDX", "signal": "buy", "track_score": 90.0, "rating": "high",
         "track_tier": "t1", "buy_price": buy, "sell_price": sell, "shares": shares,
         "profit": profit, "real_buy_date": exec_d, "real_buy_price": buy,
         "current_price": cur, "sell_date": sell_date}
    return [v[k] for k in FIELDS]


def _make_env(tmp_path: Path, rows: list[list]) -> Namespace:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "signal_kelly_trades.json").write_text(json.dumps({}), encoding="utf-8")
    (data / "signal_kelly_backtest.json").write_text(json.dumps({}), encoding="utf-8")
    (data / "kelly_mode_s06_state.json").write_text(json.dumps(
        {"generated_at": "2026-01-01T00:00:00", "coverage_end": "20261231", "daily": []}),
        encoding="utf-8")
    (data / "kelly_loss_features.json").write_text(json.dumps({}), encoding="utf-8")
    (data / "trade_dates.txt").write_text("\n".join([
        "20260105", "20260106", "20260107", "20260108", "20260109",
        "20260112", "20260113", "20260114", "20260115", "20260116",
        "20260119", "20260120", "20260121", "20260122", "20260123"]) + "\n", encoding="utf-8")
    etf_db = tmp_path / "etf.db"
    con = sqlite3.connect(etf_db)
    con.execute("CREATE TABLE etf_daily (etf_code TEXT, etf_name TEXT, date TEXT, open REAL,"
                " close REAL, accum_nav REAL, PRIMARY KEY(etf_code, date))")
    con.executemany("INSERT INTO etf_daily VALUES (?,?,?,?,?,?)", [
        ("510300", "沪深300ETF", "20260105", 3.98, 4.00, 4.00),
        ("510300", "沪深300ETF", "20260106", 4.01, 4.05, 4.05),
        ("510300", "沪深300ETF", "20260107", 4.00, 4.05, 4.05),
        ("510300", "沪深300ETF", "20260108", 4.02, 4.08, 4.08),
        ("510300", "沪深300ETF", "20260119", 4.28, 4.30, 4.30),
        ("510300", "沪深300ETF", "20260120", 3.88, 3.90, 3.90),
    ])
    con.commit()
    con.close()
    fIdx = {k: i for i, k in enumerate(FIELDS)}
    env = Namespace(db=str(tmp_path / "sim.db"), data_dir=str(data), etf_db=str(etf_db),
                    trade_dates=str(data / "trade_dates.txt"), pool="k1", fee="backtest",
                    asof="20260107", from_date=None, mark_open=False, reconcile=True)
    return env, rows, fIdx


def _patch(monkeypatch, rows, fIdx):
    monkeypatch.setattr(bf, "build_kept", lambda *_a, **_k: (rows, fIdx, FakeResolver()))


def test_backfill_backtest_caliber(tmp_path, monkeypatch):
    """backtest 口径: profit 直接取回测产物字段; 两笔平仓 → reconcile 可与手工数字逐位对账。"""
    rows = [
        _row("20260105", "20260106", 4.00, 4.30, "20260119", 2400, 600),
        _row("20260106", "20260107", 4.00, 3.90, "20260120", 2400, -100),
    ]
    env, rows, fIdx = _make_env(tmp_path, rows)
    _patch(monkeypatch, rows, fIdx)

    s1 = bf.backfill(env)
    assert (s1["signals"], s1["fills"], s1["marks"]) == (2, 4, 0), s1
    rec = s1["reconcile"]
    assert rec["n"] == 2
    assert rec["total_profit"] == 500.0, rec        # 600 + (-100), 直接取 profit 字段
    assert rec["max_concurrent_capital"] == 20000.0, rec  # 两笔信号日 05/06 均未平仓 → 重叠
    assert abs(rec["rmh"] - 500.0 / 20000.0 * 100) < 1e-9, rec

    s2 = bf.backfill(env)
    assert (s2["signals"], s2["orders"], s2["fills"], s2["marks"]) == (0, 0, 0, 0), s2


def test_backfill_etf_main_double_caliber_and_mark(tmp_path, monkeypatch):
    """etf_main 口径: 表内 net=calc 口径 + fee_config 双段; 未平仓写 provisional 估值标记。"""
    rows = [
        _row("20260105", "20260106", 4.00, 4.30, "20260119", 2400, 600),
        _row("20260107", "20260108", 4.00, 0, "", 2400, 300, cur=4.20),
    ]
    env, rows, fIdx = _make_env(tmp_path, rows)
    env.fee, env.mark_open = "etf_main", True
    _patch(monkeypatch, rows, fIdx)

    s1 = bf.backfill(env)
    assert (s1["signals"], s1["fills"], s1["marks"]) == (2, 3, 1), s1
    # reconcile 的 total_profit = 逐笔 _recompute_trade 独立复算之和(不是 coder 自己给的 profit)
    expect = sum(float(kp._recompute_trade(t, fIdx, kp.FEE_ETF_MAIN, 10000)["profit"]) for t in rows)
    assert abs(s1["reconcile"]["total_profit"] - expect) < 1e-6, (s1["reconcile"], expect)
    assert abs(s1["reconcile"]["total_profit"] - 900) > 1e-6  # 证明确实重算而非直取 600+300

    con = sqlite3.connect(env.db)
    con.row_factory = sqlite3.Row
    try:
        f = con.execute("SELECT fee_config, net, price_raw, price_equiv FROM sim_trade_fill"
                        " WHERE side='buy' ORDER BY created_at LIMIT 1").fetchone()
        cfg = json.loads(f["fee_config"])
        assert cfg["real"]["preset"] == "etf_main" and cfg["calc"]["preset"] == "backtest"
        assert cfg["real"]["quote"] != cfg["calc"]["quote"]
        assert abs(f["net"] - cfg["calc"]["net"]) < 1e-9  # 表内 net 列 = calc 口径
        assert f["price_raw"] > 0 and f["price_equiv"] > 0

        pos = {r["signal_date"]: r for r in con.execute("SELECT * FROM v_sim_trade_position")}
        assert len(pos) == 2
        c1 = pos["20260105"]
        assert c1["closed"] == 1 and c1["sell_fill_kind"] == "close"
        assert c1["profit_calc"] is not None and c1["profit_real"] is not None
        # calc 口径 = 表内 net 差(买入 net=含着费 10000, 卖出 net=10000+页面 profit)
        assert abs(c1["profit_calc"] - (c1["sell_proceeds"] - c1["buy_cost"])) < 1e-9
        # etf_main 口径按 _recompute_trade 重算(不是产物里的 profit=600), 逐位对齐
        assert abs(c1["profit_calc"]
                   - float(kp._recompute_trade(rows[0], fIdx, kp.FEE_ETF_MAIN, 10000)["profit"])) < 1e-6
        # real 口径 = fee_config real 段净额差, 与 calc 不同源(费率档不同 ⇒ 数值不同)
        assert abs(c1["profit_real"] - c1["profit_calc"]) > 1e-6
        c2 = pos["20260107"]
        assert c2["closed"] == 0 and c2["sell_fill_kind"] == "mark"
        assert c2["profit_calc"] is None and c2["profit_real"] is None
        # 估值标记利润(按 etf_main 重算)只进 profit_mark, 不进已实现口径
        assert abs(c2["profit_mark"]
                   - float(kp._recompute_trade(rows[1], fIdx, kp.FEE_ETF_MAIN, 10000)["profit"])) < 1e-6
        assert con.execute("SELECT COUNT(*) FROM sim_trade_signal WHERE source='backfill'"
                           ).fetchone()[0] == 2
        assert con.execute("SELECT status FROM sim_trade_fill WHERE price_kind='mark'"
                           ).fetchone()[0] == "provisional"
    finally:
        con.close()

    # 幂等重跑
    s2 = bf.backfill(env)
    assert (s2["signals"], s2["orders"], s2["fills"], s2["marks"]) == (0, 0, 0, 0), s2


def test_real_sell_uses_lot_shares_not_fractional(tmp_path, monkeypatch):
    """真实口径卖出必须用整手买入份额; 回测 trades.shares 是分数份额(高价 ETF 可差十倍),
    直接拿来乘价会让真实盈亏虚高十几倍(云上实测 159943 单笔 17 万, 根因即此)。"""
    rows = [_row("20260105", "20260106", 12.856, 14.906, "20260119", 11759.868851, 3000, code="159943")]
    env, rows, fIdx = _make_env(tmp_path, rows)
    env.fee, env.mark_open = "etf_main", False
    _patch(monkeypatch, rows, fIdx)
    con = sqlite3.connect(env.etf_db)
    con.executemany("INSERT OR REPLACE INTO etf_daily VALUES (?,?,?,?,?,?)", [
        ("159943", "深证100ETF", "20260105", 12.8, 12.856, 12.856),
        ("159943", "深证100ETF", "20260106", 12.856, 13.0, 13.0),
        ("159943", "深证100ETF", "20260119", 14.9, 14.906, 14.906),
    ])
    con.commit()
    con.close()

    bf.backfill(env)
    con = sqlite3.connect(env.db)
    con.row_factory = sqlite3.Row
    try:
        b = con.execute("SELECT shares_real FROM sim_trade_fill WHERE side='buy'").fetchone()
        s = con.execute("SELECT shares_real, shares_calc FROM sim_trade_fill WHERE side='sell'").fetchone()
        pos = con.execute("SELECT * FROM v_sim_trade_position").fetchone()
    finally:
        con.close()
    assert b["shares_real"] == 700.0            # 10000/12.856 → 整手 700 股
    assert s["shares_real"] == 700.0            # 卖出同样 700 股, 不是 11759.87
    assert s["shares_calc"] == 11759.868851     # calc 口径保留分数份额
    # 真实盈亏 = 700 股 × 价差 ≈ 1435 元量级, 绝不能是十几万
    assert 0 < pos["profit_real"] < 3000, pos["profit_real"]
