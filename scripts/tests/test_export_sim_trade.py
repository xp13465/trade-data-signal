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


def _fill(con, fid, oid, side, date, price, shares, kind="open", status="confirmed",
          net=10043.0, real_net=None, real_gross=None, fee_config=None):
    """种子成交。net = 表内 calc 费率净额; real_net/real_gross = fee_config.real 段。

    两张口径必须给**可分辨**的不同值(D4): 否则 review(calc)==review(real),
    「导出结果与 review 逐口径一致」用例零判别力(变异成恒用 calc 也能过)。
    """
    if fee_config is None:
        cfg = json.loads(FEE_JSON)
        if real_net is not None:
            cfg["real"]["net"] = real_net
        if real_gross is not None:
            cfg["real"]["gross"] = real_gross
        fee_config = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
    con.execute(
        "INSERT INTO sim_trade_fill (fill_id, order_id, side, fill_date, price_kind,"
        " price_raw, shares_real, net, fee_config, source, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (fid, oid, side, date, kind, price, shares, net, fee_config,
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
    # D4: 卖出 calc 净额 10600 vs real 净额 10595 ⇒ profit_calc=557, profit_real=552
    # (可分辨差 5 元; 任何「real 面板误用 calc 数」的变异都会被抓到)。
    _fill(con, "f_closed_sell", "o_closed_sell", "sell", "20260120", 5.30, 2000.0,
          kind="close", net=10600.0, real_net=10595.0, real_gross=10610.0)
    db.record_event(con, "trigger_run", payload={"stage": "signal", "signal_date": "20260105",
                                                 "inserted": 1, "ignored": 0},
                    event_at="2026-01-05T22:45:00+08:00")
    con.commit()
    con.close()


def test_missing_db_still_writes_legal_json(tmp_path):
    out = tmp_path / "simtrade.json"
    code = exp.main(["--db", str(tmp_path / "nope.db"), "--out", str(out),
                     "--log-dir", str(tmp_path / "logs"),
                     "--etf-db", str(tmp_path / "no-etf.db")])
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
    code = exp.main(["--db", str(blank), "--out", str(out),
                     "--etf-db", str(tmp_path / "no-etf.db"),
                     "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["status"] == "empty"
    assert code == 0  # empty = 正常空态, 不许当失败


def test_corrupt_db_reports_error_not_empty(tmp_path):
    """损坏账本必须报 error, 不能伪装成「等待数据」——否则巡检查不出账本坏了。"""
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite database")
    out = tmp_path / "simtrade.json"
    code = exp.main(["--db", str(bad), "--out", str(out),
                     "--etf-db", str(tmp_path / "no-etf.db"),
                     "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["status"] == "error"
    assert code == 2  # D5: 账本坏了必须非零退出, 发布脚本/systemd 才能记 failed 发告警
    assert payload["source"]["note"].startswith("账本无法读取")
    assert payload["positions"] == []


def test_atomic_write_leaves_no_tmp(tmp_path):
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(tmp_path / "nope.db"), "--out", str(out),
              "--etf-db", str(tmp_path / "no-etf.db"),
              "--log-dir", str(tmp_path / "logs")])
    assert out.exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_seeded_ledger_sections_and_review_consistency(tmp_path):
    ledger = tmp_path / "sim.db"
    _seed(ledger)
    out = tmp_path / "simtrade.json"
    # 显式钉死价源 + 日志目录: 用例不依赖运行目录里恰好有没有 data/etf_national_team.db
    # 或 data/logs(生产发布脚本 simtrade_export_publish.sh 本来也是显式传的)。
    # 历史上曾靠 CLI 隐式回退读该库 ⇒ 主仓(有库)取到真实价、干净 worktree 为 None, 红绿随环境漂移。
    exp.main(["--db", str(ledger), "--out", str(out), "--log-dir", str(tmp_path / "logs"),
              "--etf-db", str(tmp_path / "no-etf.db")])
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
    # 累计双口径与 sim_trade_review 同构(直接复用同一实现), 且**逐口径**逐字段对账。
    # D4 判别力: 两口径种子不同(calc 557 / real 552) ⇒ 若导出误把 real 面板填 calc 数,
    # calc 断言仍绿但 real 断言必红。
    con = db.connect(ledger)
    try:
        refs = {c: review_mod.review(con, c, "signal", False) for c in ("calc", "real")}
    finally:
        con.close()
    assert refs["calc"]["total_profit"] == 557.0
    assert refs["real"]["total_profit"] == 552.0
    assert refs["calc"]["total_profit"] != refs["real"]["total_profit"]
    for caliber in ("calc", "real"):
        ref = refs[caliber]
        got = payload["summary"][caliber]
        for key in ("n", "win_rate", "avg_win", "avg_loss", "payoff_ratio",
                    "total_profit", "max_concurrent_capital", "rmh", "dd_pct",
                    "annualized_pct", "span_days"):
            assert got[key] == ref[key], f"{caliber}.{key}: {got[key]} != {ref[key]}"
        assert got["n"] == ref["n"] == 1
    assert payload["summary"]["calc"]["total_profit"] != payload["summary"]["real"]["total_profit"]
    # D6: 公开 JSON 不得泄服务器绝对路径
    raw = out.read_text(encoding="utf-8")
    assert str(tmp_path) not in raw and "/home/" not in raw
    assert payload["source"]["db"] == "sim.db"
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
              "--backfill-db", str(ledger), "--etf-db", str(tmp_path / "no-etf.db")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    dates = {r["date"]: r for r in payload["runs"]}
    assert "20260106" in dates
    stage = {s["stage"]: s for s in dates["20260106"]["stages"]}
    assert stage["buy_fill"]["ran"] is True and stage["buy_fill"]["source"] == "log"
    assert payload["backfill"]["available"] is True
    assert payload["backfill"]["real"]["n_total_signals"] == 2


def _etf_db(path: Path, rows):
    import sqlite3
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE etf_daily (etf_code TEXT, date TEXT, close REAL)")
    con.executemany("INSERT INTO etf_daily VALUES (?,?,?)", rows)
    con.commit()
    con.close()


def test_no_implicit_etf_price_fallback(tmp_path, monkeypatch):
    """防重犯: 不传 --etf-db 时不得隐式读运行目录 ROOT/data/etf_national_team.db。

    历史缺陷: main() 在该文件存在时自动取价 ⇒ 主仓(有库)取到真实价、干净 worktree 取不到,
    同一用例红绿随运行环境漂移。用 monkeypatch 把 ROOT 指到 tmp_path 并放一个"诱饵" etf 库,
    若隐式 fallback 复活, latest_price 会变成 4.152, 本用例必红(有判别力)。
    """
    ledger = tmp_path / "sim.db"
    _seed(ledger)
    decoy = tmp_path / "data" / "etf_national_team.db"
    decoy.parent.mkdir()
    _etf_db(decoy, [("510300", "20260121", 4.152)])
    monkeypatch.setattr(exp, "ROOT", tmp_path)
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(ledger), "--out", str(out), "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["positions"][0]["latest_price"] is None
    assert payload["positions"][0]["price_source"] == "unavailable"


def test_open_position_latest_price_and_profit_from_etf_daily(tmp_path):
    """O9/D4: 未平仓估值分支(etf 最新价)锁死行为: 市值/浮盈/浮盈%。

    种子: 买入 shares_real=2400, calc net=10043(表内), real net=10043(费率段);
    最新价 4.25 ⇒ 市值 10200, 浮盈 10200-10043=157, 比例 157/10000=1.57%。
    """
    ledger = tmp_path / "sim.db"
    _seed(ledger)
    etf = tmp_path / "etf.db"
    _etf_db(etf, [("510300", "20260121", 4.25)])
    out = tmp_path / "simtrade.json"
    # 显式钉死价源 + 日志目录, 不依赖运行目录里的 data/ 是否恰好有库/日志
    exp.main(["--db", str(ledger), "--out", str(out), "--etf-db", str(etf),
              "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    pos = next(p for p in payload["positions"] if p["etf_code"] == "510300")
    assert (pos["latest_price"], pos["latest_date"]) == (4.25, "20260121")
    assert pos["price_source"] == "etf_daily"
    assert pos["market_value"] == 10200.0
    assert pos["profit"] == 157.0 and pos["profit_pct"] == 1.57


def test_open_position_mark_branch_uses_estimated_profit(tmp_path):
    """O5/O9/D4: mark 估值分支 —— 利润取回填估值(profit_mark), 不被 etf 价覆盖。"""
    ledger = tmp_path / "sim.db"
    con = db.init_db(ledger)
    _signal(con, "s_mark")
    _order(con, "o_mark_buy", "s_mark", "buy")
    _fill(con, "f_mark_buy", "o_mark_buy", "buy", "20260106", 4.02, 2400.0)
    _order(con, "o_mark_sell", "s_mark", "sell")
    _fill(con, "f_mark_sell", "o_mark_sell", "sell", "20260107", 4.10, 2400.0,
          kind="mark", fee_config=json.dumps({"mark": True, "profit": 123.4}))
    con.close()
    out = tmp_path / "simtrade.json"
    # 显式给不存在的 etf 库 ⇒ 无最新价, price_source 落到 mark
    exp.main(["--db", str(ledger), "--out", str(out),
              "--etf-db", str(tmp_path / "no-etf.db"),
              "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    pos = next(p for p in payload["positions"] if p["etf_code"] == "510300")
    assert pos["price_source"] == "mark"
    assert pos["latest_price"] is None and pos["market_value"] is None
    assert pos["profit"] == 123.4 and pos["profit_pct"] == 1.23
    assert pos["mark_profit"] == 123.4
    # mark 行不是真实成交, 不进流水
    assert all(t["status"] != "mark" for t in payload["trades"])
    assert payload["trade_meta"]["total"] == 1


def test_output_has_no_absolute_server_path(tmp_path):
    """D6: 公开 JSON 任何时候都不许出现绝对路径(源库/回填库都只留文件名)。"""
    ledger = tmp_path / "sim.db"
    _seed(ledger)
    out = tmp_path / "simtrade.json"
    exp.main(["--db", str(ledger), "--out", str(out), "--backfill-db", str(ledger),
              "--etf-db", str(tmp_path / "no-etf.db"),
              "--log-dir", str(tmp_path / "logs")])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["source"]["db"] == "sim.db"
    assert payload["backfill"]["db"] == "sim.db"
    raw = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in raw and "/home/" not in raw
