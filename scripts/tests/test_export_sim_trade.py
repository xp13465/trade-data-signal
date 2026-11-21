# -*- coding: utf-8 -*-
"""export_sim_trade.py 单测: 空库合法 JSON / 有数据区块 / 双口径与 review 一致 / 原子写 / 运行状态。

对应用户需求: admin 工作台「模拟交易」tab 展示持仓、成交流水、累计双口径、运行状态。
空库(timer 刚装、账本还没数据)必须产出合法 JSON, 前端不白屏。
"""
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import export_sim_trade as exp  # noqa: E402
import sim_trade_db as db  # noqa: E402
import sim_trade_review as review_mod  # noqa: E402

FEE_JSON = json.dumps({
    "real": {"preset": "etf_main", "gross": 10050.0, "net": 10043.0,
             "commission": 5.0, "transfer_fee": 0.1, "stamp_tax": 0.0,
             "quote": {"slippage": 0.001}},
    "calc": {"preset": "backtest", "gross": 10060.0, "net": 10055.0,
             "quote": {"slippage": 0.001}},
}, ensure_ascii=False, sort_keys=True)


def _signal(con, sid, code="510300", sig="20260105", exe="20260106", due="20260119"):
    con.execute(
        "INSERT INTO sim_trade_signal (signal_id, signal_date, exec_date, sell_due_date,"
        " index_id, etf_code, etf_name, source, frozen_at, trigger_source, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, sig, exe, due, "idx", code, "沪深300ETF", "log",
         "2026-01-05T22:45:00+08:00", "nextday_plan.json", "2026-01-05T22:45:00+08:00"))
    con.commit()


def _order(con, oid, sid, side, code="510300"):
    con.execute(
        "INSERT INTO sim_trade_order (order_id, signal_id, side, action, etf_code,"
        " intended_at, triggered_at, trigger_source, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (oid, sid, side, "open" if side == "buy" else "close", code,
         "2026-01-06T09:50:00+08:00", "2026-01-06T09:50:00+08:00", "timer",
         "2026-01-06T09:50:00+08:00"))
    con.commit()


def _fill(con, fid, oid, side, date, price, shares, kind="open", status="confirmed"):
    con.execute(
        "INSERT INTO sim_trade_fill (fill_id, order_id, side, fill_date, price_kind,"
        " price_raw, shares_real, net, fee_config, source, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (fid, oid, side, date, kind, price, shares, 10043.0, FEE_JSON,
         "etf_daily", status, date + "T09:50:00+08:00"))
    con.commit()


def _seed(path: Path):
    con = db.init_db(path)
    _signal(con, "s_open")
    _order(con, "o_open", "s_open", "buy")
    _fill(con, "f_open_buy", "o_open", "buy", "20260106", 4.02, 2400.0)
    _signal(con, "s_closed", code="510500", sig="20260106", exe="20260107", due="20260120")
    _order(con, "o_closed_buy", "s_closed", "buy", "510500")
    _order(con, "o_closed_sell", "s_closed", "sell", "510500")
    _fill(con, "f_closed_buy", "o_closed_buy", "buy", "20260107", 5.00, 2000.0)
    _fill(con, "f_closed_sell", "o_closed_sell", "sell", "20260120", 5.30, 2000.0, kind="close")
    db.record_event(con, "trigger_run", payload={"stage": "signal", "signal_date": "20260105",
                                                 "inserted": 1, "ignored": 0},
                    event_at="2026-01-05T22:45:00+08:00")
    con.commit()
    con.close()


def test_missing_db_still_writes_legal_json(tmp_path):
    out = tmp_path / "simtrade.json"
    code = exp.main(["--db", str(tmp_path / "nope.db"), "--out", str(out),
                     "--log-dir", str(tmp_path / "logs")])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["status"] == "missing"
    assert payload["positions"] == [] and payload["trades"] == [] and payload["runs"] == []
    assert payload["backfill"]["available"] is False
    assert payload["generated_at"]


def test_empty_db_file_reports_empty(tmp_path):
    """0 字节库 = 尚未初始化 -> empty, 与损坏库的 error 区分开。"""
    blank = tmp_path / "blank.db"
    blank.write_bytes(b"")
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(blank), "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["status"] == "empty"


def test_corrupt_db_reports_error_not_empty(tmp_path):
    """损坏账本必须报 error, 不能伪装成「等待数据」——否则巡检查不出账本坏了。"""
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite database")
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(bad), "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["status"] == "error"
    assert payload["source"]["note"].startswith("账本无法读取")
    assert payload["positions"] == []


def test_atomic_write_leaves_no_tmp(tmp_path):
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(tmp_path / "nope.db"), "--out", str(out)])
    assert out.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_seeded_ledger_sections_and_review_consistency(tmp_path):
    ledger = tmp_path / "sim.db"
    _seed(ledger)
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(ledger), "--out", str(out), "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["status"] == "ok"
    # 持仓: 只有未平仓那一笔; 最新价无 etf 库时为空但不崩
    assert [p["etf_code"] for p in payload["positions"]] == ["510300"]
    assert payload["positions"][0]["latest_price"] is None
    assert payload["positions"][0]["price_source"] == "unavailable"
    # 流水: 3 条真实成交(不含 mark)
    assert payload["trade_meta"]["total"] == 3
    assert payload["trade_meta"]["shown"] == 3
    sides = sorted(t["side"] for t in payload["trades"])
    assert sides == ["buy", "buy", "sell"]
    assert all("fee" in t and "slippage_est" in t for t in payload["trades"])
    # 累计双口径与 sim_trade_review 同构(直接复用同一实现)
    con = db.connect(ledger)
    try:
        for caliber in ("calc", "real"):
            ref = review_mod.review(con, caliber, "signal", False)
            got = payload["summary"][caliber]
            assert got["n"] == ref["n"] == 1
            assert got["total_profit"] == ref["total_profit"]
            assert got["rmh"] == ref["rmh"] and got["dd_pct"] == ref["dd_pct"]
    finally:
        con.close()
    assert payload["summary"]["counts"] == {"signals": 2, "closed": 1, "open": 1, "no_fill": 0}
    # 运行状态: 事件 payload 里的 signal 阶段被识别
    assert payload["runs"] and payload["runs"][0]["date"] == "20260105"
    stage = {s["stage"]: s for s in payload["runs"][0]["stages"]}
    assert stage["signal"]["ran"] is True and stage["signal"]["inserted"] == 1
    assert stage["buy_fill"]["ran"] is False


def test_log_runs_and_backfill(tmp_path):
    ledger = tmp_path / "sim.db"
    _seed(ledger)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sim_trade_run_20260106.jsonl").write_text(
        json.dumps({"stage": "buy_fill", "inserted": 1, "ignored": 0}) + "\n", encoding="utf-8")
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(ledger), "--out", str(out), "--log-dir", str(logs),
              "--backfill-db", str(ledger)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    dates = {r["date"]: r for r in payload["runs"]}
    assert "20260106" in dates
    stage = {s["stage"]: s for s in dates["20260106"]["stages"]}
    assert stage["buy_fill"]["ran"] is True and stage["buy_fill"]["source"] == "log"
    assert payload["backfill"]["available"] is True
    assert payload["backfill"]["real"]["n_total_signals"] == 2
