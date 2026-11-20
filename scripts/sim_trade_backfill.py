#!/usr/bin/env python3
"""sim_trade_backfill.py - 历史种子回填(K=1 两组口径)到 append-only 模拟交易账本。

⚠️ 默认 `--db` = /tmp/sim_trade_backfill.db(2026-11-21 F6): 写生产账本必须显式传 --db;
   目标库内若已有 live 信号(source<>'backfill')直接拒绝写入(防回填 supersede 压掉实盘行)。

回填池(与 docs/auto-trade/scripts/nextday_buy_full_loop_backtest.py::build_kept 同款):
  signal_kelly_trades.json + signal_kelly_backtest.json + kelly_mode_s06_state.json
  + kelly_loss_features.json
  → kelly_posrating._collect_base_pool + _position_cap_kept_keys(K=1)

参数化(该旧脚本硬编码本地路径; 本脚本全部路径显式传入):
  --data-dir 必须指向与锚点同日期快照的产物目录(本地列表见 memory prod-fact-must-use-cloud-authoritative-db,
  生产事实以云上为准)。

两组口径:
  --fee backtest  → 545 笔 PRD S0 口径(万3/最低5), profit 直接取回测 trade.profit(锚点 +158,397/158.40%)
  --fee etf_main  → 585 笔页面 K=1 卡口径(万0.5/最低0.1), 用 kelly_posrating._recompute_trade 重算
  --mark-open     未平仓笔追加 provisional 估值标记 fill(仅 etf_main 页面口径需要, 便于对账;
                  真实账本里未平仓不计已实现盈亏)。

用法:
  python3 scripts/sim_trade_backfill.py --db /tmp/sim_trade_k1_backtest.db \\
      --data-dir <DATA_DIR> --etf-db <etf.db> --trade-dates data/trade_dates.txt \\
      --fee backtest --asof 20260910 --reconcile
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sim_trade_db as db  # noqa: E402
import sim_trade_trigger as trig  # noqa: E402
import kelly_posrating as kp  # noqa: E402

# 回填默认写 /tmp 临时库(2026-11-21 F6): data/sim_trade.db 是 live 触发器专用账本,
# 回填必须显式 --db 指定, 绝不默认落到生产路径。
DEFAULT_DB = str(Path(tempfile.gettempdir()) / "sim_trade_backfill.db")


def build_kept(trades_doc: dict, backtest_doc: dict, s06_doc: dict, feat_doc: dict):
    """与 nextday_buy_full_loop_backtest.py::build_kept 同构(逐位一致)。"""
    fields = trades_doc["fields"]
    fIdx = {f: i for i, f in enumerate(fields)}
    quads = trades_doc["quadrants"]
    sell_modes = backtest_doc["config"]["sell_modes"]
    pos_raw = []
    for rk in ("rating_high", "rating_mid", "rating_low"):
        pos_raw += (quads.get(rk) or {}).get("A") or []
    trade_dims = kp._trade_dims(quads, fIdx)
    spec_map = {r["key"]: r for r in ((feat_doc.get("meta") or {}).get("rules") or [])
                if isinstance(r, dict) and r.get("key")}
    feats = feat_doc.get("features") or {}
    feat_at = lambda name, date: (feats.get(name) or {}).get(str(date))  # noqa: E731
    s06 = kp.S06Resolver(s06_doc)
    passes_fade = kp.make_passes_fade(fIdx, trade_dims, spec_map, feat_at, s06)
    base_pool = kp._collect_base_pool(quads, sell_modes, fIdx, passes_fade)
    kept = kp._position_cap_kept_keys(base_pool, fIdx, 1)
    out = [tb for tb in pos_raw if passes_fade(tb) and kept.get(kp._base_key(tb, fIdx))]
    return out, fIdx, s06


def trade_profit(t: list, fIdx: dict, fee: str) -> float:
    """所选口径的单笔盈亏: backtest=回测产物 profit; etf_main=页面 K 档费率重算。"""
    if fee == "backtest":
        return float(t[fIdx["profit"]] or 0)
    r = kp._recompute_trade(t, fIdx, kp.FEE_ETF_MAIN, 10000)
    return float(r["profit"] or 0)


def reconcile(rows: list, fIdx: dict, fee: str) -> dict:
    """锚点复算: n / total_profit / 峰值资金收益率 rmh / 峰值资金回撤 dd。"""
    trs = []
    for t in rows:
        trs.append({
            "profit": trade_profit(t, fIdx, fee),
            "amount": 10000,
            "buy_date": str(t[fIdx["signal_date"]] or ""),  # 与 _compute_stats 锚点同源(信号日占资金)
            "sell_date": str(t[fIdx["sell_date"]] or ""),
        })
    st = kp._compute_stats(trs, 10000)
    dd = round(st["max_drawdown"] / st["max_concurrent_capital"] * 100, 4) if st["max_concurrent_capital"] else 0
    return {"n": st["n"], "total_profit": st["total_profit"],
            "max_concurrent_capital": st["max_concurrent_capital"],
            "rmh": st["return_pct_max_holding"], "dd_pct": dd}


def _etf_bar(con, code: str, date: str) -> dict | None:
    row = con.execute(
        "SELECT date, open, close, accum_nav FROM etf_daily WHERE etf_code=? AND date=?",
        (code, date)).fetchone()
    return dict(row) if row else None


def backfill(args) -> dict:
    data_dir = Path(args.data_dir)
    trades_doc = json.load(open(data_dir / "signal_kelly_trades.json", encoding="utf-8"))
    bt_doc = json.load(open(data_dir / "signal_kelly_backtest.json", encoding="utf-8"))
    s06_path = data_dir / "kelly_mode_s06_state.json"
    feat_path = data_dir / "kelly_loss_features.json"
    s06_doc = json.load(open(s06_path, encoding="utf-8")) if s06_path.exists() else None
    feat_doc = json.load(open(feat_path, encoding="utf-8")) if feat_path.exists() else {}
    if not s06_doc:
        raise SystemExit("kelly_mode_s06_state.json 缺失: 回填必须带 S06 快照(禁止 fail-open 残缺池)")
    rows, fIdx, resolver = build_kept(trades_doc, bt_doc, s06_doc, feat_doc)
    if args.asof:
        rows = [t for t in rows if str(t[fIdx["signal_date"]]) <= args.asof]
    if args.from_date:
        rows = [t for t in rows if str(t[fIdx["signal_date"]]) >= args.from_date]
    dates = trig.load_trade_dates(args.trade_dates)
    s06_sha = db.file_sha256(s06_path)
    con = db.init_db(args.db)
    # 防混口径: 一份账本只装一种回填口径(signal_id 不含 fee, 混跑只会被幂等吞掉旧口径行,
    # 账面一半 backtest 一半 etf_main 且静默 → 直接拒绝, 要求换独立 --db)
    note_tag = f"backfill fee={args.fee}"
    conflict = con.execute(
        "SELECT COUNT(*) FROM sim_trade_signal WHERE source='backfill' AND COALESCE(note,'')<>?",
        (note_tag,)).fetchone()[0]
    if conflict:
        con.close()
        raise SystemExit(f"账本 {args.db} 已有 {conflict} 行其他口径回填, 本次 fee={args.fee} 拒绝混口径;"
                         f" 请换独立 --db")
    # 防 live/backfill 混库(2026-11-21 F6): 库里有 live 信号(source<>'backfill')时,
    # 回填的 plan_hash 不同可能通过 supersede 语义压掉 live 信号 ⇒ 直接拒绝, 回填必须独立库。
    live_rows = con.execute(
        "SELECT COUNT(*) FROM sim_trade_signal WHERE source<>'backfill'").fetchone()[0]
    if live_rows:
        con.close()
        raise SystemExit(f"账本 {args.db} 已有 {live_rows} 行 live 信号(source<>'backfill'),"
                         f" 回填拒绝写入混库; 回填请换独立临时库(默认 {DEFAULT_DB})")
    etf = trig.open_etf_ro(args.etf_db)
    stats = {"stage": "backfill", "fee": args.fee, "asof": args.asof, "rows": len(rows),
             "signals": 0, "orders": 0, "fills": 0, "marks": 0, "skipped": 0}
    try:
        for t in rows:
            sig_date = str(t[fIdx["signal_date"]] or "")
            code = str(t[fIdx["etf_code"]] or "")
            real_buy_date = str(t[fIdx["real_buy_date"]] or "") if "real_buy_date" in fIdx else ""
            exec_date = real_buy_date if real_buy_date and real_buy_date > sig_date else trig.next_trading_day(dates, sig_date)
            if not exec_date:
                stats["skipped"] += 1
                continue
            sell_date = str(t[fIdx["sell_date"]] or "")
            sell_due = sell_date or trig.nth_trading_day_after(dates, sig_date, 10) or ""
            ok, base, _reason = resolver.base_for_date(sig_date)
            mode = base if ok else None
            bar = _etf_bar(etf, code, sig_date) if etf else None
            plan_hash = db.stable_id("backfill", sig_date, exec_date, code,
                                     t[fIdx["buy_price"]], t[fIdx["sell_price"]])
            signal_id = db.stable_id("A", sig_date, exec_date, code, plan_hash)
            sig_row = {
                "signal_id": signal_id, "schema_version": db.SCHEMA_VERSION, "strategy": "A",
                "signal_date": sig_date, "exec_date": exec_date, "sell_due_date": sell_due,
                "index_id": str(t[fIdx["index_id"]] or ""), "etf_code": code,
                "etf_name": t[fIdx["etf_name"]], "signal": t[fIdx["signal"]],
                "track_score": t[fIdx["track_score"]], "rating": t[fIdx["rating"]],
                "bk_ts": None, "track_tier": t[fIdx["track_tier"]], "late": 0,
                "source": "backfill", "s06_effective_mode": mode, "s06_decision_date": None,
                "s06_state_generated_at": s06_doc.get("generated_at"), "s06_state_sha256": s06_sha,
                "fade_mode": "s06", "fade_keyset_hash": trig.fade_keyset_hash(mode),
                "universe_pass": 1, "fade_pass": 1, "k_cap": 1, "k_rank": 1, "amount": 10000,
                "plan_prev_close": None, "signal_accum_nav": (bar or {}).get("accum_nav"),
                "signal_close_raw": (bar or {}).get("close"), "plan_hash": plan_hash,
                "day_snapshot_hash": None, "frozen_at": db.now_iso(),
                "trigger_source": "backfill", "supersedes_signal_id": None, "revision": 1,
                "note": f"backfill fee={args.fee}", "created_at": db.now_iso(),
            }
            if db.insert_or_ignore(con, "sim_trade_signal", sig_row):
                stats["signals"] += 1
            # 买入指令 + 成交
            buy_pure = (float(t[fIdx["buy_price"]] or 0) / (1 + trig.FEE_PRESETS["backtest"]["slippage"]))
            shares_calc = float(t[fIdx["shares"]] or 0)
            raw_open = None
            if etf:
                eb = _etf_bar(etf, code, exec_date)
                raw_open = (eb or {}).get("open")
            raw_open = raw_open or float(t[fIdx["real_buy_price"]] or 0) or None
            order_id = db.stable_id(signal_id, "buy", "0930", 10000, "market", None)
            if db.insert_or_ignore(con, "sim_trade_order", {
                "order_id": order_id, "signal_id": signal_id, "strategy": "A", "side": "buy",
                "action": "open", "etf_code": code, "etf_name": t[fIdx["etf_name"]],
                "qty_plan": float(int(10000 / (raw_open or 1) / 100) * 100), "qty_unit": "share",
                "amount": 10000, "price_type": "market", "limit_price": None, "intended_at": "09:30",
                "triggered_at": db.now_iso(), "trigger_source": "backfill",
                "broker_account": None, "broker_order_id": None, "request_payload": None,
                "response_payload": None, "initial_status": "submitted", "created_at": db.now_iso(),
            }):
                stats["orders"] += 1
            real_shares = None  # 真实口径的整手买入份额(卖出必须用它, 不能用回测分数份额 shares_calc)
            if raw_open and raw_open > 0 and buy_pure > 0:
                real = trig.real_buy(10000, raw_open, code, trig.FEE_PRESETS[trig.REAL_FEE_PRESET])
                real_shares = real.get("shares") or None
                calc = trig.calc_buy(10000, buy_pure, code, trig.FEE_PRESETS[trig.CALC_FEE_PRESET])
                fill_id = db.stable_id(order_id, exec_date, "backfill", round(raw_open, 6), round(shares_calc, 6))
                if db.insert_or_ignore(con, "sim_trade_fill", {
                    "fill_id": fill_id, "order_id": order_id, "side": "buy", "fill_date": exec_date,
                    "fill_time": "09:30", "price_kind": "open", "price_raw": raw_open,
                    "price_equiv": buy_pure, "accum_nav_ref": (bar or {}).get("accum_nav"),
                    "raw_close_ref": (bar or {}).get("close"), "raw_ref_date": sig_date,
                    "shares_calc": shares_calc, "shares_real": real["shares"],
                    "gross": calc["gross"], "commission": calc["commission"],
                    "transfer_fee": calc["transfer_fee"], "stamp_tax": calc["stamp_tax"],
                    "net": calc["net"], "fee_preset": trig.CALC_FEE_PRESET,
                    "fee_config": trig.fee_config_json(real, calc, trig.REAL_FEE_PRESET, trig.CALC_FEE_PRESET),
                    "source": "backfill", "source_ts": db.now_iso(), "quote_date": exec_date,
                    "status": "confirmed", "supersedes_fill_id": None,
                    "correction_reason": None, "created_at": db.now_iso(),
                }):
                    stats["fills"] += 1
            else:
                db.record_event(con, "fill_failed", order_id=order_id, signal_id=signal_id,
                                payload={"stage": "backfill", "reason": "no_raw_open",
                                         "exec_date": exec_date, "etf_code": code}, source="sim_trade_backfill")
                stats["skipped"] += 1
            # 卖出指令 + 成交(已平仓) / 估值标记(未平仓, 仅 etf_main)
            sell_order_id = db.stable_id(signal_id, "sell", "1455", shares_calc, "market", None)
            if sell_date:
                db.insert_or_ignore(con, "sim_trade_order", {
                    "order_id": sell_order_id, "signal_id": signal_id, "strategy": "A", "side": "sell",
                    "action": "close", "etf_code": code, "etf_name": t[fIdx["etf_name"]],
                    "qty_plan": shares_calc, "qty_unit": "share", "amount": None,
                    "price_type": "market", "limit_price": None, "intended_at": "14:55",
                    "triggered_at": db.now_iso(), "trigger_source": "backfill",
                    "broker_account": None, "broker_order_id": None, "request_payload": None,
                    "response_payload": None, "initial_status": "submitted", "created_at": db.now_iso(),
                })
            sell_pure = (float(t[fIdx["sell_price"]] or 0) / (1 - trig.FEE_PRESETS["backtest"]["slippage"])) if float(t[fIdx["sell_price"]] or 0) > 0 else 0
            raw_close = None
            if etf and sell_date:
                sb = _etf_bar(etf, code, sell_date)
                raw_close = (sb or {}).get("close")
            if sell_date and raw_close and raw_close > 0 and sell_pure > 0:
                profit = trade_profit(t, fIdx, args.fee)
                calc = trig.calc_sell(shares_calc, sell_pure, code, trig.FEE_PRESETS[trig.CALC_FEE_PRESET])
                # 真实口径卖出用整手买入份额(回测 trades.shares 是分数份额, 直接乘价会虚高十几倍)
                real_sh = real_shares or shares_calc
                real = trig.real_sell(real_sh, raw_close, code, trig.FEE_PRESETS[trig.REAL_FEE_PRESET])
                fill_id = db.stable_id(sell_order_id, sell_date, "backfill", round(raw_close, 6), round(shares_calc, 6))
                if db.insert_or_ignore(con, "sim_trade_fill", {
                    "fill_id": fill_id, "order_id": sell_order_id, "side": "sell", "fill_date": sell_date,
                    "fill_time": "22:45", "price_kind": "close", "price_raw": raw_close,
                    "price_equiv": sell_pure, "accum_nav_ref": (sb or {}).get("accum_nav"),
                    "raw_close_ref": raw_close, "raw_ref_date": sell_date,
                    "shares_calc": shares_calc, "shares_real": real_sh,
                    "gross": calc["gross"], "commission": calc["commission"],
                    "transfer_fee": calc["transfer_fee"], "stamp_tax": calc["stamp_tax"],
                    "net": round(10000 + profit, 4), "fee_preset": trig.CALC_FEE_PRESET,
                    "fee_config": trig.fee_config_json(real, {**calc, "profit": profit},
                                                      trig.REAL_FEE_PRESET, trig.CALC_FEE_PRESET),
                    "source": "backfill", "source_ts": db.now_iso(), "quote_date": sell_date,
                    "status": "confirmed", "supersedes_fill_id": None,
                    "correction_reason": f"backfill profit={args.fee}", "created_at": db.now_iso(),
                }):
                    stats["fills"] += 1
            elif args.mark_open and not sell_date and args.fee == "etf_main":
                profit = trade_profit(t, fIdx, args.fee)
                mark_date = args.asof or str(trades_doc.get("asof") or "")
                if not mark_date:
                    mark_date = str(max(str(x[fIdx["signal_date"]]) for x in rows))
                if db.insert_or_ignore(con, "sim_trade_order", {
                    "order_id": sell_order_id, "signal_id": signal_id, "strategy": "A", "side": "sell",
                    "action": "close", "etf_code": code, "etf_name": t[fIdx["etf_name"]],
                    "qty_plan": shares_calc, "qty_unit": "share", "amount": None,
                    "price_type": "market", "limit_price": None, "intended_at": "22:45",
                    "triggered_at": db.now_iso(), "trigger_source": "backfill_mark",
                    "broker_account": None, "broker_order_id": None, "request_payload": None,
                    "response_payload": None, "initial_status": "submitted", "created_at": db.now_iso(),
                }):
                    stats["orders"] += 1
                fill_id = db.stable_id(sell_order_id, mark_date, "backfill_mark", profit, shares_calc)
                if db.insert_or_ignore(con, "sim_trade_fill", {
                    "fill_id": fill_id, "order_id": sell_order_id, "side": "sell", "fill_date": mark_date,
                    "fill_time": "22:45", "price_kind": "mark", "price_raw": float(t[fIdx["current_price"]] or 0),
                    "price_equiv": None, "accum_nav_ref": None, "raw_close_ref": None,
                    "raw_ref_date": mark_date, "shares_calc": shares_calc,
                    "shares_real": real_shares or shares_calc,
                    "gross": None, "commission": None, "transfer_fee": None, "stamp_tax": None,
                    "net": round(10000 + profit, 4), "fee_preset": trig.CALC_FEE_PRESET,
                    "fee_config": json.dumps({"mark": True, "profit": profit}, ensure_ascii=False),
                    "source": "backfill_mark", "source_ts": db.now_iso(), "quote_date": mark_date,
                    "status": "provisional", "supersedes_fill_id": None,
                    "correction_reason": "未平仓估值标记(非真实卖出)", "created_at": db.now_iso(),
                }):
                    stats["marks"] += 1
        db.record_event(con, "trigger_run", payload=stats, source="sim_trade_backfill")
        con.commit()
    finally:
        if etf:
            etf.close()
        con.close()
    stats["reconcile"] = reconcile(rows, fIdx, args.fee)
    return stats


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="模拟交易账本历史回填(K=1 两组口径)")
    ap.add_argument("--db", default=DEFAULT_DB,
                    help=f"回填目标库(默认 {DEFAULT_DB}; 写生产账本请显式传路径)")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--etf-db", default="data/etf_national_team.db")
    ap.add_argument("--trade-dates", default="data/trade_dates.txt")
    ap.add_argument("--pool", default="k1", choices=("k1",), help="回填池(第一阶段只 K=1)")
    ap.add_argument("--fee", default="backtest", choices=("backtest", "etf_main"))
    ap.add_argument("--asof", default=None, help="只回填 signal_date <= asof(锚点同日期口径)")
    ap.add_argument("--from-date", default=None)
    ap.add_argument("--mark-open", action="store_true", help="未平仓笔追加估值标记(页面口径对账)")
    ap.add_argument("--reconcile", action="store_true", help="打印锚点复算(缺省也打印)")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    stats = backfill(args)
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
