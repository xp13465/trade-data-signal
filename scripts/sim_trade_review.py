#!/usr/bin/env python3
"""sim_trade_review.py - 模拟交易账本复盘: 两组盈亏口径 + 页面卡同口径指标。

读取 data/sim_trade.db 的 v_sim_trade_position(append-only 账本的有效成交视图),
按 --caliber 选择盈亏口径:
  calc = profit_calc(回测等价口径: 表内 net 列 = calc 费率净额, 买入含费总花费 / 卖出扣费净回款)
  real = profit_real(真实口径: fill.fee_config JSON 的 real 段净额, 真实价 × 100 份整手 - 真实费率)
未平仓估值标记(price_kind='mark')默认不计; --include-marks 时按估值利润计入(与页面 K 档卡同 n)。

指标(与 signal_kelly_trades 页面卡同源):
  n / 胜率 / 盈亏比 / total_profit / max_concurrent_capital / rmh(峰值资金收益率) / dd_pct / 年化 / 最近 50 笔
资金占用起点默认 signal_date(与 kelly_posrating._compute_stats 锚点同源, 可 --capital-from exec 切换)。

用法:
  python3 scripts/sim_trade_review.py --db data/sim_trade.db --caliber calc
  python3 scripts/sim_trade_review.py --db data/sim_trade.db --caliber real --json-out /tmp/x.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sim_trade_db as db  # noqa: E402
import kelly_posrating as kp  # noqa: E402


def _row_profit(r, caliber: str) -> float:
    """已平仓: calc=表内 net(calc 费率)差 / real=fee_config real 段净额差。
    未平仓估值标记(price_kind='mark'): 两口径都用回填时的估值利润(与页面卡 n 口径对账)。"""
    if r["sell_fill_kind"] == "mark":
        return float(r["profit_mark"] or 0)
    v = r["profit_calc"] if caliber == "calc" else r["profit_real"]
    return float(v or 0)


def _days_between(a: str, b: str) -> int:
    try:
        return (datetime.strptime(b, "%Y%m%d") - datetime.strptime(a, "%Y%m%d")).days
    except (TypeError, ValueError):
        return 0


def review(con, caliber: str = "calc", capital_from: str = "signal",
           include_marks: bool = False) -> dict:
    rows = con.execute(
        "SELECT * FROM v_sim_trade_position ORDER BY signal_date, etf_code").fetchall()
    closed = [r for r in rows if r["closed"]]
    # --include-marks: 把未平仓估值标记也计入(与页面 K 档卡 n/ret 同口径), 默认只算已实现
    counted = closed + ([r for r in rows if r["sell_fill_kind"] == "mark"] if include_marks else [])
    counted.sort(key=lambda r: (r["signal_date"], r["etf_code"]))
    trades = []
    for r in counted:
        trades.append({
            "profit": _row_profit(r, caliber),
            "amount": float(r["amount"] or 10000),
            "buy_date": str(r["signal_date"] if capital_from == "signal" else r["exec_date"]),
            "sell_date": str(r["sell_fill_date"] or r["sell_due_date"] or ""),
        })
    st = kp._compute_stats(trades, 10000) if trades else {
        "n": 0, "total_profit": 0.0, "max_concurrent_capital": 0.0,
        "return_pct_max_holding": 0.0, "max_drawdown": 0.0}
    wins = [t["profit"] for t in trades if t["profit"] > 0]
    losses = [t["profit"] for t in trades if t["profit"] < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    dd_pct = round(st["max_drawdown"] / st["max_concurrent_capital"] * 100, 4) if st["max_concurrent_capital"] else 0.0
    dates = [t["buy_date"] for t in trades if t["buy_date"]]
    end_dates = [t["sell_date"] for t in trades if t["sell_date"]]
    span_days = _days_between(min(dates), max(end_dates)) if dates and end_dates else 0
    annual = (st["total_profit"] / st["max_concurrent_capital"] * 100 * 365 / span_days) if span_days and st["max_concurrent_capital"] else 0.0
    recent = []
    for r in rows[:0:-1][:50]:
        recent.append({
            "signal_date": r["signal_date"], "exec_date": r["exec_date"], "etf_code": r["etf_code"],
            "etf_name": r["etf_name"], "closed": bool(r["closed"]),
            "profit_calc": r["profit_calc"], "profit_real": r["profit_real"],
            "buy_price_raw": r["buy_price_raw"], "sell_price_raw": r["sell_price_raw"],
            "sell_kind": r["sell_fill_kind"],
            "source": r["signal_source"],
        })
    return {
        "caliber": caliber,
        "capital_from": capital_from,
        "include_marks": include_marks,
        "n": st["n"], "n_total_signals": len(rows), "n_open": len(rows) - len(closed),
        "marks": sum(1 for r in rows if r["sell_fill_kind"] == "mark"),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "payoff_ratio": round(avg_win / avg_loss, 4) if avg_loss else None,
        "total_profit": st["total_profit"],
        "max_concurrent_capital": st["max_concurrent_capital"],
        "rmh": st["return_pct_max_holding"], "dd_pct": dd_pct,
        "annualized_pct": round(annual, 2), "span_days": span_days,
        "recent_50": recent,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="模拟交易账本复盘(calc/real 双口径)")
    ap.add_argument("--db", default="data/sim_trade.db")
    ap.add_argument("--caliber", default="calc", choices=("calc", "real"))
    ap.add_argument("--capital-from", default="signal", choices=("signal", "exec"))
    ap.add_argument("--include-marks", action="store_true",
                    help="未平仓估值标记也计入(与页面 K 档卡口径对账; 默认为 0=只算已实现)")
    ap.add_argument("--recent", type=int, default=50)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    if not Path(args.db).exists():
        raise SystemExit(f"账本不存在: {args.db}")
    con = db.connect(args.db)
    try:
        out = review(con, args.caliber, args.capital_from, args.include_marks)
        if args.recent:
            out["recent_50"] = out["recent_50"][:args.recent]
    finally:
        con.close()
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
