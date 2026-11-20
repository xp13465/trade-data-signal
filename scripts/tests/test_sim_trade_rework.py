# -*- coding: utf-8 -*-
"""2026-11-21 返工 F1/F2/F4/F5/F6/F3 红转绿单测(对应独立审查报告 F1-F6)。

每个用例修前红、修后绿:
  F1 settle 用 etf_daily 补写漏跑的买入成交(exec_date <= 结算日);
  F2 无有效买入成交时不写卖出指令/成交(只记事件);
  F4 同日异价重跑 → 新 provisional supersede 旧行, 结算后只剩 1 条有效成交;
  F5 实时价缺「数据日期」列 → fail-closed 返回 {} 不写假价;
  F6 回填默认库在 /tmp, 且库内已有 live 行时拒绝写入;
  F3 闸门静态层扫到 0 个 sim_trade_*.py 文件时 FAIL(防空转假绿)。
"""
import json
import sqlite3
import sys
import tempfile
import types
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import sim_trade_db as db  # noqa: E402
import sim_trade_backfill as bf  # noqa: E402
import sim_trade_trigger as trig  # noqa: E402
import check_sim_trade_append_only as gate  # noqa: E402

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
    (data / "prices_buy2.json").write_text(json.dumps({"510300": 4.05}), encoding="utf-8")
    (data / "prices_other.json").write_text(json.dumps({"999999": 9.99}), encoding="utf-8")
    (data / "prices_sell.json").write_text(json.dumps({"510300": 4.30}), encoding="utf-8")
    (data / "prices_sell2.json").write_text(json.dumps({"510300": 4.32}), encoding="utf-8")
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


def _q(a: Namespace, sql: str, params=()):
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# F1: settle 补写漏跑买入
# ---------------------------------------------------------------------------
def test_settle_backfills_missing_buy_fill(tmp_path):
    """09:50 取不到价 → 当晚 settle 用 etf_daily 开盘价补写 confirmed 买入(不是永久丢单)。"""
    a = _make_env(tmp_path)
    trig.run_signal(a)
    a.date, a.prices_json = "20260106", str(Path(a.data_dir) / "prices_other.json")
    b = trig.run_buy_fill(a)
    assert (b["fills"], b["fill_failed"]) == (0, 1), b

    a.prices_json = None
    t1 = trig.run_settle(a)
    assert t1["buy_backfilled"] == 1, t1
    t2 = trig.run_settle(a)
    assert (t2["buy_backfilled"], t2["buy_confirmed"]) == (0, 0), t2

    fills = _q(a, "SELECT fill_id, fill_date, price_raw, status, source FROM sim_trade_fill"
                  " WHERE side='buy'")
    assert len(fills) == 1, [dict(r) for r in fills]
    assert (fills[0]["fill_date"], fills[0]["price_raw"], fills[0]["status"], fills[0]["source"]) \
        == ("20260106", 4.02, "confirmed", "etf_daily")
    pos = _q(a, "SELECT buy_fill_id, buy_fill_kind, buy_shares_real, closed FROM v_sim_trade_position")
    assert len(pos) == 1 and pos[0]["buy_fill_id"] and pos[0]["closed"] == 0, dict(pos[0])


def test_settle_backfills_after_fully_missed_day(tmp_path):
    """buy_fill 整点漏跑(机器不在线): 之后任意一天跑 settle 也能按 etf_daily 补回该执行日买入。"""
    a = _make_env(tmp_path)
    trig.run_signal(a)
    a.date = "20260119"  # 执行日 20260106 当天没跑过任何阶段, 直到卖出日才跑 settle
    t = trig.run_settle(a)
    assert t["buy_backfilled"] == 1, t
    fills = _q(a, "SELECT fill_date, price_raw, status FROM sim_trade_fill WHERE side='buy'")
    assert len(fills) == 1
    assert (fills[0]["fill_date"], fills[0]["price_raw"], fills[0]["status"]) \
        == ("20260106", 4.02, "confirmed")


# ---------------------------------------------------------------------------
# F2: 无买入成交不写卖出
# ---------------------------------------------------------------------------
def test_sell_order_skips_position_without_buy_fill(tmp_path):
    """无买入成交的持仓: sell_order 只记 sell_skipped_no_fill 事件, 不写卖出指令/成交。"""
    a = _make_env(tmp_path)
    trig.run_signal(a)
    a.date, a.prices_json = "20260106", str(Path(a.data_dir) / "prices_other.json")
    trig.run_buy_fill(a)
    a.date, a.prices_json = "20260119", str(Path(a.data_dir) / "prices_sell.json")
    s = trig.run_sell_order(a)
    assert (s["orders"], s["fills"], s["skipped"]) == (0, 0, 1), s
    assert _q(a, "SELECT COUNT(*) AS n FROM sim_trade_order WHERE side='sell'")[0]["n"] == 0
    assert _q(a, "SELECT COUNT(*) AS n FROM sim_trade_fill WHERE side='sell'")[0]["n"] == 0
    ev = _q(a, "SELECT COUNT(*) AS n FROM sim_trade_event WHERE event_type='sell_skipped_no_fill'")
    assert ev[0]["n"] >= 1
    pos = _q(a, "SELECT buy_fill_id, sell_fill_id, closed FROM v_sim_trade_position")
    assert len(pos) == 1 and pos[0]["buy_fill_id"] is None and pos[0]["closed"] == 0, dict(pos[0])


def test_settle_refuses_sell_without_buy_fill(tmp_path):
    """settle 对无有效买入成交的持仓拒绝结算(不写 0 份额假卖出)。"""
    a = _make_env(tmp_path)
    trig.run_signal(a)
    # 造历史脏态: 执行日 etf_daily 缺 bar(补写无价) + 已存在卖出指令(旧代码会写假卖出)
    con = sqlite3.connect(a.etf_db)
    con.execute("DELETE FROM etf_daily WHERE etf_code='510300' AND date='20260106'")
    con.commit()
    con.close()
    trig.run_buy_fill(a)
    sid = _q(a, "SELECT signal_id FROM sim_trade_signal")[0]["signal_id"]
    con = sqlite3.connect(a.db)
    con.execute(
        "INSERT INTO sim_trade_order (order_id, signal_id, side, action, etf_code, qty_plan,"
        " intended_at, triggered_at, trigger_source, initial_status, created_at)"
        " VALUES ('legacy_sell', ?, 'sell', 'close', '510300', 0, '14:55', 'x', 'legacy',"
        " 'submitted', 'x')", (sid,))
    con.commit()
    con.close()

    a.date = "20260119"
    t = trig.run_settle(a)
    assert t["sell_settled"] == 0, t
    assert _q(a, "SELECT COUNT(*) AS n FROM sim_trade_fill WHERE side='sell'")[0]["n"] == 0
    ev = _q(a, "SELECT COUNT(*) AS n FROM sim_trade_event WHERE event_type='sell_skipped_no_fill'")
    assert ev[0]["n"] >= 1


# ---------------------------------------------------------------------------
# F4: 同日异价重跑只剩一条有效成交
# ---------------------------------------------------------------------------
def test_rerun_with_different_price_keeps_single_effective_fill(tmp_path):
    a = _make_env(tmp_path)
    trig.run_signal(a)
    a.date, a.prices_json = "20260106", str(Path(a.data_dir) / "prices_buy.json")
    b1 = trig.run_buy_fill(a)
    assert b1["fills"] == 1 and b1["superseded"] == 0, b1
    a.prices_json = str(Path(a.data_dir) / "prices_buy2.json")
    b2 = trig.run_buy_fill(a)
    assert (b2["fills"], b2["superseded"]) == (1, 1), b2

    a.prices_json = None
    t = trig.run_settle(a)
    assert t["buy_confirmed"] == 1, t

    rows = _q(a, "SELECT f.fill_id, f.status, f.price_raw, f.supersedes_fill_id FROM sim_trade_fill f"
                  " JOIN sim_trade_order o ON o.order_id=f.order_id"
                  " WHERE f.side='buy' ORDER BY f.created_at, f.fill_id")
    assert len(rows) == 3, [dict(r) for r in rows]
    eff = _q(a, "SELECT f.fill_id, f.status, f.price_raw FROM v_sim_fill_effective f"
                 " JOIN sim_trade_order o ON o.order_id=f.order_id WHERE f.side='buy'")
    assert len(eff) == 1 and eff[0]["status"] == "confirmed", [dict(r) for r in eff]
    # supersede 链: 新 provisional(4.05) → 旧 provisional(4.02), confirmed → 新 provisional
    provs = [r for r in rows if r["status"] == "provisional"]
    assert len(provs) == 2, [dict(r) for r in provs]
    old = [r for r in provs if r["price_raw"] == 4.02][0]
    new = [r for r in provs if r["price_raw"] == 4.05][0]
    confirmed = [r for r in rows if r["status"] == "confirmed"][0]
    assert new["supersedes_fill_id"] == old["fill_id"]
    assert confirmed["supersedes_fill_id"] == new["fill_id"]
    assert old["supersedes_fill_id"] is None


def test_sell_rerun_with_different_price_keeps_single_effective_fill(tmp_path):
    """F4 同类面核查(卖出侧): 14:55 重跑不会留两条有效卖出成交。

    卖出侧没有 09:50 buy_fill 那种「同日可重跑补价」的场景: 第一笔 provisional 卖出成交
    就让 v_sim_trade_position.closed=1, 重跑扫不到该持仓(positions=0)。本用例把这条不变量
    钉住, 防将来改 closed 判据时静默退化出双有效卖出; 结算复核的 supersede 链单列断言。
    """
    a = _make_env(tmp_path)
    trig.run_signal(a)
    a.date, a.prices_json = "20260106", str(Path(a.data_dir) / "prices_buy.json")
    trig.run_buy_fill(a)
    a.prices_json = None
    trig.run_settle(a)  # 买入 confirmed(过期 provisional 复核), 此时还没到卖出日

    a.date, a.prices_json = "20260119", str(Path(a.data_dir) / "prices_sell.json")
    s1 = trig.run_sell_order(a)
    assert (s1["positions"], s1["fills"]) == (1, 1), s1
    a.prices_json = str(Path(a.data_dir) / "prices_sell2.json")
    s2 = trig.run_sell_order(a)
    assert (s2["positions"], s2["fills"]) == (0, 0), s2

    eff_before = _q(a, "SELECT fill_id, price_raw, status FROM v_sim_fill_effective"
                       " WHERE side='sell'")
    assert len(eff_before) == 1 and eff_before[0]["status"] == "provisional", \
        [dict(r) for r in eff_before]

    a.prices_json = None
    t = trig.run_settle(a)
    assert t["sell_settled"] == 1, t
    eff = _q(a, "SELECT fill_id, status FROM v_sim_fill_effective WHERE side='sell'")
    assert len(eff) == 1 and eff[0]["status"] == "confirmed", [dict(r) for r in eff]
    sells = _q(a, "SELECT fill_id, status, supersedes_fill_id FROM sim_trade_fill"
                  " WHERE side='sell' ORDER BY created_at, fill_id")
    assert len(sells) == 2, [dict(r) for r in sells]
    prov = [r for r in sells if r["status"] == "provisional"][0]
    confirmed = [r for r in sells if r["status"] == "confirmed"][0]
    assert confirmed["supersedes_fill_id"] == prov["fill_id"]
    assert prov["supersedes_fill_id"] is None


# ---------------------------------------------------------------------------
# F5: 实时价缺「数据日期」列 fail-closed
# ---------------------------------------------------------------------------
def test_fetch_last_prices_fail_closed_without_quote_date(monkeypatch):
    pd = pytest.importorskip("pandas")
    fake = types.ModuleType("akshare")
    monkeypatch.setitem(sys.modules, "akshare", fake)

    fake.fund_etf_spot_em = lambda: pd.DataFrame({"代码": ["510300"], "最新价": [4.20]})
    assert trig.fetch_last_prices(["510300"], "20260119") == {}

    fake.fund_etf_spot_em = lambda: pd.DataFrame(
        {"代码": ["510300"], "最新价": [4.20], "数据日期": ["2026-01-18"]})
    assert trig.fetch_last_prices(["510300"], "20260119") == {}

    fake.fund_etf_spot_em = lambda: pd.DataFrame(
        {"代码": ["510300"], "最新价": [4.20], "数据日期": ["2026-01-19"]})
    assert trig.fetch_last_prices(["510300"], "20260119") == {"510300": 4.20}


# ---------------------------------------------------------------------------
# F6: 回填默认库 / 混库拒绝
# ---------------------------------------------------------------------------
class _FakeResolver:
    def base_for_date(self, date):
        return True, "new14", "test"


def _backfill_env(tmp_path: Path) -> Namespace:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "signal_kelly_trades.json").write_text(json.dumps({}), encoding="utf-8")
    (data / "signal_kelly_backtest.json").write_text(json.dumps({}), encoding="utf-8")
    (data / "kelly_mode_s06_state.json").write_text(json.dumps(
        {"generated_at": "2026-01-01T00:00:00", "coverage_end": "20261231", "daily": []}),
        encoding="utf-8")
    (data / "kelly_loss_features.json").write_text(json.dumps({}), encoding="utf-8")
    (data / "trade_dates.txt").write_text("\n".join(DATES) + "\n", encoding="utf-8")
    return Namespace(db=str(tmp_path / "sim.db"), data_dir=str(data),
                     etf_db=str(tmp_path / "etf.db"), trade_dates=str(data / "trade_dates.txt"),
                     pool="k1", fee="backtest", asof=None, from_date=None,
                     mark_open=False, reconcile=True)


def test_backfill_default_db_is_tmp_not_production():
    ap = bf.build_parser()
    args = ap.parse_args(["--data-dir", "x"])
    assert args.db == bf.DEFAULT_DB
    assert args.db != "data/sim_trade.db"
    assert Path(args.db).parent == Path(tempfile.gettempdir())


def test_backfill_refuses_db_with_live_rows(tmp_path, monkeypatch):
    env = _backfill_env(tmp_path)
    monkeypatch.setattr(bf, "build_kept", lambda *_a, **_k: ([], {}, _FakeResolver()))
    con = db.init_db(env.db)
    con.execute(
        "INSERT INTO sim_trade_signal (signal_id, signal_date, exec_date, sell_due_date, index_id,"
        " etf_code, source, frozen_at, trigger_source, created_at)"
        " VALUES ('live_sig','20260105','20260106','20260119','IDX','510300','log','x','nextday_plan.json','x')")
    con.commit()
    con.close()

    with pytest.raises(SystemExit) as ei:
        bf.backfill(env)
    assert "live" in str(ei.value), ei.value
    assert _q(env, "SELECT COUNT(*) AS n FROM sim_trade_signal WHERE source='backfill'")[0]["n"] == 0


# ---------------------------------------------------------------------------
# F3: 闸门静态层空转 fail-closed
# ---------------------------------------------------------------------------
def test_gate_static_layer_fails_when_no_target_files(tmp_path):
    out = gate.run(tmp_path)
    assert out["static_files_scanned"] == 0
    assert out["pass"] is False
    assert out["static_forbidden_hits"], out


def test_gate_static_layer_really_scans_scripts():
    out = gate.run(SCRIPTS)
    assert out["static_files_scanned"] >= 4, out["static_files_scanned"]
    assert out["static_forbidden_hits"] == []
    assert out["pass"] is True
