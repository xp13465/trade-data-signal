#!/usr/bin/env python3
"""ETF→权重龙头个股 回测脚本(import wrapper 模式, ~300行差异层)。

目的: 对比"买ETF本身(A臂)" vs "买ETF持仓龙头个股(B1/B2/B3臂)"的回测表现,
     验证龙头个股是否比ETF本身收益更高/更稳定。

依赖(只读,不写生产):
  - scripts/signal_kelly_backtest.py(导入可复用函数+常量)
  - static-site/data/board_etf_map.json(指数→ETF映射)
  - static-site/data/signal_stats.json(信号评级)
  - data/sentiment.db(买卖信号)
  - data/stock_top_weights.db stock_top_daily 表(个股前复权日线)
  - docs/kelly/backtest-ai/etf-weight-leader/data/etf_hold_collect_progress.json(ETF季度持仓TOP1-3)

输出(全落隔离目录,不碰生产):
  - docs/kelly/backtest-ai/etf-weight-leader/data/signal_kelly_backtest_stock.json
  - docs/kelly/backtest-ai/etf-weight-leader/data/signal_kelly_stock_trades.json

复现命令:
  cd /Users/linhuichen/code/trade
  PYTHONPATH=scripts:.venv/bin/python docs/kelly/backtest-ai/etf-weight-leader/scripts/signal_kelly_backtest_stock.py
"""
import argparse
import bisect
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────────────────────
PROJ_ROOT = Path(__file__).absolute().parent.parent.parent.parent.parent.parent  # trade/
SCRIPTS_DIR = PROJ_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(PROJ_ROOT))

# 从基脚本导入可复用函数+常量
from signal_kelly_backtest import (  # noqa: E402
    BUY_AMOUNT, BUY_SIGNALS, SELL_MODES, HOLD_DAYS,
    RATING_HIGH, RATING_MID, QUADRANT_META, SIG_QUAD_MAP, MARKET_QUAD_MAP,
    A_STOCK_MARKETS,
    _load_signal_stats, _load_board_etf_map, _resolve_etf,
    _batch_load_etf_prices,
    _backtest_signal_sell, _compute_stats, _guidance,
    _load_market_map, _load_market_state, _load_market_tiers,
    _is_market_bull, _market_tier_at,
    COMMISSION_RATE, SLIPPAGE, MIN_COMMISSION, TRANSFER_FEE_RATE_SH,
    _KELLY_FEE_CONFIG,
)
from simulate_trade import _buy_with_fees, _sell_with_fees  # noqa: E402

# ── 路径常量 ──────────────────────────────────────────────────────────────────
DATA_DIR = PROJ_ROOT / "docs" / "kelly" / "backtest-ai" / "etf-weight-leader" / "data"
PROGRESS_PATH = DATA_DIR / "etf_hold_collect_progress.json"
STOCK_DB_PATH = PROJ_ROOT / "data" / "stock_top_weights.db"

# 个股版费率: 印花税万5(卖出) + 过户费万0.1 + 佣金万3(min5) + 滑点千1
STOCK_FEE_CONFIG = {
    'commission_rate': COMMISSION_RATE, 'commission_mode': 'fixed',
    'commission_rate2': COMMISSION_RATE, 'commission_mode2': 'fixed',
    'stamp_tax': 0.0005, 'stamp_tax_mode': 'sell',
    'transfer_fee': TRANSFER_FEE_RATE_SH, 'transfer_fee_mode': 'sh',
    'slippage': SLIPPAGE, 'slippage_mode': 'fixed',
    'slippage_sigma': 0.0, 'min_commission': MIN_COMMISSION,
}

ARMS = ("A", "B1", "B2", "B3")
ARM_LABELS = {
    "A": "ETF本身(基准)", "B1": "第一ETF-TOP1个股",
    "B2": "前3ETF各TOP1去重", "B3": "前3ETF各TOP1-3去重等权(每信号总资金¥10000,N只股等权分)",
}

FOREIGN_KEYS = {"hsi", "hstech", "hscei", "us_dji", "us_spx", "us_ndx",
                "us_ixic", "nikkei225", "dax", "cac40"}


# ── 数据加载 ──────────────────────────────────────────────────────────────────

def _load_stock_prices(codes, start=None, end=None):
    """从 stock_top_weights.db 批量加载个股前复权日线。"""
    if not codes or not os.path.exists(STOCK_DB_PATH):
        print(f"  ⚠ 个股DB不存在: {STOCK_DB_PATH}", file=sys.stderr)
        return {}, {}
    price_map = {c: {} for c in codes}
    conn = sqlite3.connect(str(STOCK_DB_PATH), timeout=30.0)
    try:
        codes_list = list(codes)
        for i in range(0, len(codes_list), 500):
            batch = codes_list[i:i + 500]
            ph = ",".join("?" * len(batch))
            sql = f"SELECT code, date, open, high, low, close, volume FROM stock_top_daily WHERE code IN ({ph}) AND close IS NOT NULL"
            params = list(batch)
            if start:
                sql += " AND date >= ?"; params.append(start)
            if end:
                sql += " AND date <= ?"; params.append(end)
            sql += " ORDER BY code, date"
            for code, date, o, h, l, c, v in conn.execute(sql, params).fetchall():
                price_map[code][date] = {"open": o, "high": h, "low": l, "close": c, "volume": v or 0}
    finally:
        conn.close()
    sorted_dates = {c: sorted(price_map[c].keys()) for c in codes}
    return price_map, sorted_dates


def _load_etf_holdings():
    """加载 etf_hold_collect_progress.json, 解析为 {etf_code: [snapshot, ...]}。

    每个 snapshot 含 top_stocks: [(code, name, weight_pct), ...] (按 weight 降序, 过滤 ETF 代码后取前3)。
    """
    import re
    if not os.path.exists(PROGRESS_PATH):
        print(f"  持仓文件不存在: {PROGRESS_PATH}", file=sys.stderr)
        return {}
    with open(PROGRESS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    holdings = {}
    q_end = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}
    # "2025年4季度股票投资明细" -> (2025, 4)
    qpat = re.compile(r"(\d{4})年(\d)季度")
    for etf_code, years in data.items():
        if not etf_code:
            continue
        snapshots = []
        for year_str, quarters in years.items():
            for qk, stocks in quarters.items():
                if not isinstance(stocks, list) or not stocks:
                    continue
                m = qpat.search(qk)
                if not m:
                    continue
                year, q = int(m.group(1)), int(m.group(2))
                if q < 1 or q > 4:
                    continue
                qe = f"{year}{q_end[q]}"
                avail = f"{year + 1}0401" if q == 4 else f"{year}{'0501' if q == 1 else '0901' if q == 2 else '1101'}"
                # 过滤 ETF 代码(1/5开头6位=ETF), 只留 A 股个股(0/3/6开头)
                valid = [s for s in stocks
                         if len(s.get("stock_code", "")) == 6
                         and s["stock_code"][0] in ("0", "3", "6")]
                valid.sort(key=lambda x: x.get("weight_pct") or 0, reverse=True)
                top = [(s["stock_code"], s.get("stock_name", ""), s.get("weight_pct", 0))
                       for s in valid[:3]]
                if top:
                    snapshots.append({"quarter_end": qe, "available_from": avail,
                                      "top_stocks": top})
        snapshots.sort(key=lambda x: x["available_from"])
        holdings[etf_code] = snapshots
    return holdings


def _pick_holding_at_date(holdings, etf_code, signal_date):
    """找 <=D 且已披露的最近一期持仓。返回 top_stocks: [(code, name, weight), ...] 或空列表。"""
    snaps = holdings.get(etf_code, [])
    if not snaps:
        return []
    lo, hi, best = 0, len(snaps) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if snaps[mid]["available_from"] <= signal_date:
            best = snaps[mid]; lo = mid + 1
        else:
            hi = mid - 1
    return best["top_stocks"] if best else []


# ── 选股 ──────────────────────────────────────────────────────────────────────

def _build_best_etf_for_stock(etf_map):
    """每指数取 track_score 最高 ETF。"""
    best = {}
    for iid, cands in etf_map.items():
        if iid == "_meta" or not isinstance(cands, list):
            continue
        scored = [c for c in cands if c.get("track_score") is not None]
        if not scored:
            continue
        top = max(scored, key=lambda c: c["track_score"])
        best[iid] = {"code": top["code"], "track_tier": top.get("track_tier", "none"),
                     "name": top.get("name", ""), "track_score": top.get("track_score"),
                     "match_method": top.get("match_method"),
                     "track_low_confidence": top.get("track_low_confidence")}
    return best


def _build_best_etf_topn(etf_map, n=3):
    """每指数取 track_score 前 N 名 ETF(去重)。"""
    result = {}
    for iid, cands in etf_map.items():
        if iid == "_meta" or not isinstance(cands, list):
            continue
        scored = [c for c in cands if c.get("track_score") is not None]
        if not scored:
            continue
        scored.sort(key=lambda c: c["track_score"], reverse=True)
        seen, top_n = set(), []
        for c in scored:
            if c["code"] not in seen:
                seen.add(c["code"]); top_n.append(c)
                if len(top_n) >= n:
                    break
        result[iid] = top_n
    return result


def _build_best_stock(index_key, signal_date, best_etf_topn, holdings):
    """四臂选股: A/B1/B2/B3。境外/债类 fallback A。

    B1: 第一ETF TOP1 (单只)
    B2: 前3 ETF 各 TOP1 去重等权 (最多3只)
    B3: 前3 ETF 各 TOP1-3 去重等权 (最多9只)
    """
    arms = {}
    etfs = best_etf_topn.get(index_key, [])
    if not etfs:
        return arms
    arms["A"] = {"code": etfs[0]["code"], "name": etfs[0].get("name", ""), "source": "etf"}
    is_foreign = index_key in FOREIGN_KEYS
    is_debt = any(index_key.startswith(p) for p in ("cgb",))
    if is_foreign or is_debt:
        arms["B1"] = arms["B2"] = arms["B3"] = arms["A"]
        return arms

    # B1: 第一ETF TOP1 (单只)
    h1_stocks = _pick_holding_at_date(holdings, etfs[0]["code"], signal_date)
    if h1_stocks:
        arms["B1"] = {"code": h1_stocks[0][0], "name": h1_stocks[0][1],
                       "source": f"etf:{etfs[0]['code']}"}
    else:
        arms["B1"] = arms["A"]

    # B2: 前3 ETF 各 TOP1 去重(每ETF只取第1只)
    b2_stocks = {}
    for etf in etfs[:3]:
        stocks = _pick_holding_at_date(holdings, etf["code"], signal_date)
        if stocks and stocks[0][0] not in b2_stocks:
            b2_stocks[stocks[0][0]] = (stocks[0][1], etf["code"])
    if b2_stocks:
        fc = list(b2_stocks.keys())[0]
        arms["B2"] = {"code": fc, "name": b2_stocks[fc][0],
                       "stocks": list(b2_stocks.keys()),
                       "source": f"multi_etf:{','.join(v[1] for v in b2_stocks.values())}"}
    else:
        arms["B2"] = arms["A"]

    # B3: 前3 ETF 各 TOP1-3 去重(每ETF取前3只, 覆盖面更广)
    b3_stocks = {}
    for etf in etfs[:3]:
        stocks = _pick_holding_at_date(holdings, etf["code"], signal_date)
        for scode, sname, sweight in stocks:
            if scode not in b3_stocks:
                b3_stocks[scode] = (sname, etf["code"])
    if b3_stocks:
        fc = list(b3_stocks.keys())[0]
        arms["B3"] = {"code": fc, "name": b3_stocks[fc][0],
                       "stocks": list(b3_stocks.keys()),
                       "source": f"multi_etf:{','.join(v[1] for v in b3_stocks.values())}"}
    else:
        arms["B3"] = arms["A"]

    return arms


# ── 个股回测 ──────────────────────────────────────────────────────────────────

def _stock_trade_dict(signal_date, index_id, signal, sell_date, code, name,
                       track_tier, track_score, match_method, track_low_confidence,
                       buy_price, sell_price, shares, profit, return_pct, hold_days,
                       sell_reason, current_price, market_state, market_tier,
                       market_tier_all, market_tier_cyb, rating, arm, source_etf,
                       buy_amount=BUY_AMOUNT):
    return {
        "signal_date": signal_date, "index_id": index_id, "signal": signal,
        "buy_date": signal_date, "sell_date": sell_date,
        "etf_code": code, "etf_name": name,
        "track_tier": track_tier, "track_score": track_score,
        "match_method": match_method, "track_low_confidence": track_low_confidence,
        "buy_price": round(buy_price, 6), "sell_price": round(sell_price, 6) if sell_price else 0,
        "shares": round(shares, 6), "profit": round(profit, 4),
        "return_pct": round(return_pct, 4), "hold_days": hold_days,
        "sell_reason": sell_reason,
        "current_price": round(current_price, 6) if current_price else 0,
        "market_state": market_state, "market_tier": market_tier,
        "market_tier_all": market_tier_all, "market_tier_cyb": market_tier_cyb,
        "rating": rating, "_arm": arm, "_source_etf": source_etf or "",
        "_buy_amount": buy_amount,
    }


def _backtest_stock_one(signal_date, stock_prices, stock_sorted_dates, code, name,
                        stop_profit, sell_mode, sell_signals, today=None,
                        hold_days=HOLD_DAYS, index_id=None, signal=None,
                        track_tier=None, track_score=None, match_method=None,
                        track_low_confidence=None, market_state=None, rating=None,
                        market_tier=None, market_tier_all=None, market_tier_cyb=None,
                        arm="B1", source_etf=None, buy_amount=None):
    """个股版单笔回测: 信号日收盘买N元, 按模式卖出。"""
    buy_amount = buy_amount or BUY_AMOUNT
    prices = stock_prices.get(code, {})
    dates = stock_sorted_dates.get(code, [])
    if not prices or not dates:
        return None
    buy_nav = prices.get(signal_date, {}).get("close")
    if buy_nav is None or buy_nav <= 0:
        return None
    buy_price, shares, _, _ = _buy_with_fees(buy_amount, buy_nav, code, STOCK_FEE_CONFIG)
    if shares <= 0:
        return None

    if sell_mode in ("G", "H", "I"):
        return _backtest_stock_signal_sell(
            signal_date, prices, dates, code, name, sell_mode, signal,
            sell_signals, today, index_id, track_tier, track_score,
            match_method, track_low_confidence, market_state, rating,
            buy_price, shares, market_tier, market_tier_all, market_tier_cyb,
            arm=arm, source_etf=source_etf, buy_amount=buy_amount)

    idx = bisect.bisect_right(dates, signal_date)
    future_dates = dates[idx:idx + hold_days]

    if len(future_dates) < hold_days:
        ref_today = today if today else (dates[-1] if dates else None)
        cur = prices.get(ref_today) if ref_today else None
        pdate = ref_today
        if cur is None and dates:
            cur = prices.get(dates[-1]); pdate = dates[-1]
        if cur is None or cur["close"] <= 0:
            return None
        _, _, _, _, net, _ = _sell_with_fees(shares, cur["close"], code, STOCK_FEE_CONFIG)
        profit = net - buy_amount
        rpct = profit / buy_amount * 100
        try:
            hold = future_dates.index(pdate) + 1
        except ValueError:
            hold = 0
        return _stock_trade_dict(signal_date, index_id, signal, "", code, name,
            track_tier, track_score, match_method, track_low_confidence,
            buy_price, 0, shares, profit, rpct, hold, "持有中", cur["close"],
            market_state, market_tier, market_tier_all, market_tier_cyb, rating,
            arm, source_etf, buy_amount=buy_amount)

    sell_date = future_dates[-1]
    sd = prices.get(sell_date)
    if not sd or sd["close"] <= 0:
        return None
    _, _, _, _, net, _ = _sell_with_fees(shares, sd["close"], code, STOCK_FEE_CONFIG)
    profit = net - buy_amount
    rpct = profit / buy_amount * 100
    try:
        hold = dates.index(sell_date) - dates.index(signal_date)
    except ValueError:
        hold = len(future_dates)
    return _stock_trade_dict(signal_date, index_id, signal, sell_date, code, name,
        track_tier, track_score, match_method, track_low_confidence,
        buy_price, sd["close"], shares, profit, rpct, hold,
        "到期卖出" if stop_profit is None else "止盈/到期", 0,
        market_state, market_tier, market_tier_all, market_tier_cyb, rating,
        arm, source_etf, buy_amount=buy_amount)


def _backtest_stock_signal_sell(signal_date, prices, dates, code, name, sell_mode,
                                 signal, sell_signals, today, index_id,
                                 track_tier, track_score, match_method,
                                 track_low_confidence, market_state, rating,
                                 buy_price, shares, market_tier, market_tier_all,
                                 market_tier_cyb, arm="B1", source_etf=None,
                                 buy_amount=None):
    """G/H/I 信号驱动卖出(个股版)。"""
    buy_amount = buy_amount or BUY_AMOUNT
    mode_def = SELL_MODES[sell_mode]
    special_types = mode_def.get("special_sell_types")
    sell_types = special_types if signal == "buy_special" and special_types else mode_def.get("sell_types") or ("sell",)
    sell_date, sell_reason = None, None
    for d, sig in (sell_signals or []):
        if d <= signal_date or sig not in sell_types:
            continue
        if prices.get(d):
            sell_date = d; sell_reason = "追止损卖出" if sig == "sell_stop_loss" else "卖出信号"; break

    if sell_date is None:
        ref_today = today if today else (dates[-1] if dates else None)
        cur = prices.get(ref_today) if ref_today else None
        pdate = ref_today
        if cur is None and dates:
            cur = prices.get(dates[-1]); pdate = dates[-1]
        if cur is None or cur["close"] <= 0:
            return None
        _, _, _, _, net, _ = _sell_with_fees(shares, cur["close"], code, STOCK_FEE_CONFIG)
        profit = net - buy_amount; rpct = profit / buy_amount * 100
        try:
            hold = dates.index(pdate) - dates.index(signal_date)
        except ValueError:
            hold = 0
        return _stock_trade_dict(signal_date, index_id, signal, "", code, name,
            track_tier, track_score, match_method, track_low_confidence,
            buy_price, 0, shares, profit, rpct, hold, "持有中", cur["close"],
            market_state, market_tier, market_tier_all, market_tier_cyb, rating,
            arm, source_etf, buy_amount=buy_amount)

    sd = prices.get(sell_date)
    if not sd or sd["close"] <= 0:
        return None
    _, _, _, _, net, _ = _sell_with_fees(shares, sd["close"], code, STOCK_FEE_CONFIG)
    profit = net - buy_amount; rpct = profit / buy_amount * 100
    try:
        hold = dates.index(sell_date) - dates.index(signal_date)
    except ValueError:
        hold = 1
    return _stock_trade_dict(signal_date, index_id, signal, sell_date, code, name,
        track_tier, track_score, match_method, track_low_confidence,
        buy_price, sd["close"], shares, profit, rpct, hold, sell_reason, 0,
        market_state, market_tier, market_tier_all, market_tier_cyb, rating,
        arm, source_etf, buy_amount=buy_amount)


def _backtest_etf_one(signal_date, prices, dates, etf_code, etf_name, stop_profit,
                       index_id, signal, tier, track_score, match_method,
                       track_low_confidence, today, hold_days, market_state,
                       rating, sell_mode, sell_signals, market_tier, market_tier_all,
                       market_tier_cyb, arm="A"):
    """A臂: 买ETF本身(复用基脚本 _backtest_one 逻辑, 加 arm 字段)。"""
    if not prices:
        return None
    buy_nav = prices.get(signal_date)
    if buy_nav is None or buy_nav <= 0:
        return None
    buy_price, shares, _, _ = _buy_with_fees(BUY_AMOUNT, buy_nav, etf_code, _KELLY_FEE_CONFIG)
    if shares <= 0:
        return None

    if sell_mode in ("G", "H", "I"):
        r = _backtest_signal_sell(signal_date, prices, dates, etf_code, sell_mode,
            signal, sell_signals, today, index_id, etf_name, tier, track_score,
            match_method, track_low_confidence, market_state, rating, buy_price,
            shares, market_tier, market_tier_all, market_tier_cyb)
        if r:
            r["_arm"] = arm; r["_source_etf"] = etf_code
        return r

    idx = bisect.bisect_right(dates, signal_date)
    future_dates = dates[idx:idx + hold_days]

    if len(future_dates) < hold_days:
        ref_today = today if today else (dates[-1] if dates else None)
        cur = prices.get(ref_today) if ref_today else None
        pdate = ref_today
        if cur is None and dates:
            cur = prices.get(dates[-1]); pdate = dates[-1]
        if cur is None or cur <= 0:
            return None
        _, _, _, _, net, _ = _sell_with_fees(shares, cur, etf_code, _KELLY_FEE_CONFIG)
        profit = net - BUY_AMOUNT; rpct = profit / BUY_AMOUNT * 100
        try:
            hold = future_dates.index(pdate) + 1
        except ValueError:
            hold = 0
        return {
            "signal_date": signal_date, "index_id": index_id, "signal": signal,
            "buy_date": signal_date, "sell_date": "", "etf_code": etf_code,
            "etf_name": etf_name, "track_tier": tier, "track_score": track_score,
            "match_method": match_method, "track_low_confidence": track_low_confidence,
            "buy_price": round(buy_price, 6), "sell_price": 0,
            "shares": round(shares, 6), "profit": round(profit, 4),
            "return_pct": round(rpct, 4), "hold_days": hold, "sell_reason": "持有中",
            "current_price": round(cur, 6), "market_state": market_state,
            "market_tier": market_tier, "market_tier_all": market_tier_all,
            "market_tier_cyb": market_tier_cyb, "rating": rating,
            "_arm": arm, "_source_etf": etf_code,
        }

    sell_date = future_dates[-1]
    sell_nav = prices.get(sell_date)
    if sell_nav is None or sell_nav <= 0:
        return None
    _, _, _, _, net, _ = _sell_with_fees(shares, sell_nav, etf_code, _KELLY_FEE_CONFIG)
    profit = net - BUY_AMOUNT; rpct = profit / BUY_AMOUNT * 100
    try:
        hold = dates.index(sell_date) - dates.index(signal_date)
    except ValueError:
        hold = len(future_dates)
    return {
        "signal_date": signal_date, "index_id": index_id, "signal": signal,
        "buy_date": signal_date, "sell_date": sell_date, "etf_code": etf_code,
        "etf_name": etf_name, "track_tier": tier, "track_score": track_score,
        "match_method": match_method, "track_low_confidence": track_low_confidence,
        "buy_price": round(buy_price, 6), "sell_price": round(sell_nav, 6),
        "shares": round(shares, 6), "profit": round(profit, 4),
        "return_pct": round(rpct, 4), "hold_days": hold,
        "sell_reason": "到期卖出" if stop_profit is None else "止盈/到期",
        "current_price": 0, "market_state": market_state,
        "market_tier": market_tier, "market_tier_all": market_tier_all,
        "market_tier_cyb": market_tier_cyb, "rating": rating,
        "_arm": arm, "_source_etf": etf_code,
    }


# ── 象限归入辅助 ──────────────────────────────────────────────────────────────

def _put_trade(trade, quadrants, etf_quad, sig_quad, mkt_quad):
    """将 trade 归入各象限。mode_key 由 compute 循环传入。"""
    mode_key = trade.pop("_mode_key", "A")
    if mode_key not in SELL_MODES:
        mode_key = "A"
    rating = trade.get("rating", "low")
    quadrants[f"rating_{rating}"][mode_key].append(trade)
    if etf_quad:
        quadrants[f"etf_{etf_quad}"][mode_key].append(trade)
    if sig_quad:
        quadrants[sig_quad][mode_key].append(trade)
    if mkt_quad:
        quadrants[mkt_quad][mode_key].append(trade)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def compute():
    from datetime import timedelta
    today = datetime.now()
    PERIODS = {
        "y1":  {"label": "近1年",  "cutoff": (today - timedelta(days=365)).strftime("%Y%m%d")},
        "y3":  {"label": "近3年",  "cutoff": (today - timedelta(days=365*3)).strftime("%Y%m%d")},
        "y5":  {"label": "近5年",  "cutoff": (today - timedelta(days=365*5)).strftime("%Y%m%d")},
        "y10": {"label": "近10年", "cutoff": (today - timedelta(days=365*10)).strftime("%Y%m%d")},
        "all": {"label": "全部",   "cutoff": "0"},
    }

    print("-> 加载数据 ...", flush=True)
    signal_stats = _load_signal_stats()
    etf_map = _load_board_etf_map()
    best_etf = _build_best_etf_for_stock(etf_map)
    best_etf_topn = _build_best_etf_topn(etf_map, n=3)
    holdings = _load_etf_holdings()
    market_map = _load_market_map()
    print(f"   {len(signal_stats)} signals, {len(best_etf)} best_etf, {len(holdings)} holdings")

    print("-> 读信号 ...", flush=True)
    from app.db import get_conn
    conn = get_conn()
    buy_rows = conn.execute(
        f"SELECT date, index_id, signal FROM signal_daily "
        f"WHERE signal IN ({','.join('?' * len(BUY_SIGNALS))}) ORDER BY date",
        BUY_SIGNALS).fetchall()
    sell_rows = conn.execute(
        "SELECT date, index_id, signal FROM signal_daily "
        "WHERE signal IN ('sell','sell_stop_loss') ORDER BY index_id, date").fetchall()
    sell_timeline = {}
    for _d, _iid, _sig in sell_rows:
        sell_timeline.setdefault(_iid, []).append((_d, _sig))
    market_state, market_dates = _load_market_state(conn)
    market_tiers = _load_market_tiers(conn)
    cyb_tiers = _load_market_tiers(conn, index_id='cyb')
    conn.close()
    print(f"   {len(buy_rows)} buy signals")

    # 收集需要的代码
    needed_stocks, needed_etfs = set(), set()
    stock_map_cache = {}
    for date, iid, sig in buy_rows:
        be, _ = _resolve_etf(date, iid, sig, best_etf, {})
        if not be:
            continue
        needed_etfs.add(be["code"])
        arms = _build_best_stock(iid, date, best_etf_topn, holdings)
        for ak in ("B1", "B2", "B3"):
            av = arms.get(ak)
            if not av or av.get("source") == "etf":
                continue
            # B2/B3 可能有 stocks 列表(多只), B1 只有 code(单只)
            if "stocks" in av:
                for sc in av["stocks"]:
                    needed_stocks.add(sc)
            else:
                needed_stocks.add(av["code"])
        stock_map_cache[(date, iid, sig)] = arms

    print(f"-> 加载价格: {len(needed_etfs)} ETF + {len(needed_stocks)} 个股 ...", flush=True)
    etf_pm, etf_sd = _batch_load_etf_prices(needed_etfs)
    stock_pm, stock_sd = _load_stock_prices(needed_stocks)
    print(f"   {sum(len(v) for v in stock_pm.values())} stock price rows")

    all_dates = set()
    for ds in list(etf_sd.values()) + list(stock_sd.values()):
        if ds:
            all_dates.add(ds[-1])
    today_str = max(all_dates) if all_dates else None
    if today_str:
        print(f"   today={today_str}")

    # 回测
    quadrants = {a: {qk: {mk: [] for mk in SELL_MODES} for qk in QUADRANT_META} for a in ARMS}
    skipped_no_etf = skipped_no_score = skipped_no_price = fallback_count = classified = 0
    etf_quad_map = {"strong": "strong", "related": "related", "approx": "approx", "none": "has_track"}

    for date, iid, sig in buy_rows:
        be, _ = _resolve_etf(date, iid, sig, best_etf, {})
        if not be:
            skipped_no_etf += 1; continue
        etf_code, tier = be["code"], be["track_tier"]
        stats_entry = signal_stats.get(iid, {}).get(sig, {})
        score_10d = stats_entry.get("10d", {}).get("score") if isinstance(stats_entry, dict) else None
        if score_10d is None:
            skipped_no_score += 1; continue
        rating = "high" if score_10d >= RATING_HIGH else ("mid" if score_10d >= RATING_MID else "low")
        etf_quad = etf_quad_map.get(tier)
        market = market_map.get(iid)
        ms = _is_market_bull(date, market_state, market_dates) if market in A_STOCK_MARKETS else True
        mt_all = _market_tier_at(date, market_tiers, market_dates)
        mt = mt_all if market in A_STOCK_MARKETS else ""
        mt_cyb = _market_tier_at(date, cyb_tiers, market_dates)
        mt_cyb = mt_cyb if market in A_STOCK_MARKETS else ""
        sell_sigs = sell_timeline.get(iid, [])
        sig_quad = SIG_QUAD_MAP.get(sig)
        mkt_quad = MARKET_QUAD_MAP.get(market)
        arms = stock_map_cache.get((date, iid, sig), {})

        any_valid = False
        for arm_key in ARMS:
            av = arms.get(arm_key)
            if not av:
                continue
            if arm_key == "A":
                prices, sdates = etf_pm.get(etf_code, {}), etf_sd.get(etf_code, [])
                for mk, md in SELL_MODES.items():
                    r = _backtest_etf_one(date, prices, sdates, etf_code, be.get("name",""),
                        md["stop_profit"], iid, sig, tier, be.get("track_score"),
                        be.get("match_method"), be.get("track_low_confidence"),
                        today=today_str, hold_days=md["hold_days"], market_state=ms,
                        rating=rating, sell_mode=mk, sell_signals=sell_sigs,
                        market_tier=mt, market_tier_all=mt_all, market_tier_cyb=mt_cyb, arm="A")
                    if r is not None:
                        r["_mode_key"] = mk; any_valid = True
                        _put_trade(r, quadrants[arm_key], etf_quad, sig_quad, mkt_quad)
            else:
                # B2/B3 可能有多只股票(stocks 列表), B1 只有 code(单只)
                stock_codes = av.get("stocks", [av["code"]])
                # B3: 每信号总资金¥10000, N只股等权分; B1/B2: 单只股=¥10000
                per_stock_buy = BUY_AMOUNT / len(stock_codes) if arm_key == "B3" else BUY_AMOUNT
                etf_fallback_used = False
                for scode in stock_codes:
                    if scode not in stock_pm:
                        fallback_count += 1
                        continue
                    for mk, md in SELL_MODES.items():
                        r = _backtest_stock_one(date, stock_pm, stock_sd, scode, av.get("name",""),
                            md["stop_profit"], mk, sell_sigs, today=today_str, hold_days=md["hold_days"],
                            index_id=iid, signal=sig, track_tier=tier, track_score=be.get("track_score"),
                            match_method=be.get("match_method"), track_low_confidence=be.get("track_low_confidence"),
                            market_state=ms, rating=rating, market_tier=mt, market_tier_all=mt_all,
                            market_tier_cyb=mt_cyb, arm=arm_key, source_etf=av.get("source",""),
                            buy_amount=per_stock_buy)
                        if r is not None:
                            r["_mode_key"] = mk; any_valid = True
                            _put_trade(r, quadrants[arm_key], etf_quad, sig_quad, mkt_quad)
                    etf_fallback_used = True  # 至少有一只有价格数据
                # 所有股票都没价格数据时 fallback 到 ETF
                if not etf_fallback_used:
                    prices, sdates = etf_pm.get(etf_code, {}), etf_sd.get(etf_code, [])
                    for mk, md in SELL_MODES.items():
                        r = _backtest_etf_one(date, prices, sdates, etf_code, be.get("name",""),
                            md["stop_profit"], iid, sig, tier, be.get("track_score"),
                            be.get("match_method"), be.get("track_low_confidence"),
                            today=today_str, hold_days=md["hold_days"], market_state=ms,
                            rating=rating, sell_mode=mk, sell_signals=sell_sigs,
                            market_tier=mt, market_tier_all=mt_all, market_tier_cyb=mt_cyb, arm=arm_key)
                        if r is not None:
                            r["_mode_key"] = mk; any_valid = True
                            _put_trade(r, quadrants[arm_key], etf_quad, sig_quad, mkt_quad)
        if any_valid:
            classified += 1
        else:
            skipped_no_price += 1

    print(f"   classified={classified}, skip: no_etf={skipped_no_etf} no_score={skipped_no_score} no_price={skipped_no_price} fallback={fallback_count}")

    # 聚合统计
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "type": "etf_weight_leader_stock_backtest",
        "arms": {a: {"label": ARM_LABELS[a]} for a in ARMS},
        "config": {
            "buy_amount": BUY_AMOUNT, "hold_days": HOLD_DAYS, "sell_modes": SELL_MODES,
            "periods": {k: v["label"] for k, v in PERIODS.items()},
            "period_cutoffs": {k: v["cutoff"] for k, v in PERIODS.items()},
            "fee_config": {"commission": COMMISSION_RATE, "stamp_tax": 0.0005,
                           "transfer_fee": TRANSFER_FEE_RATE_SH, "slippage": SLIPPAGE,
                           "min_commission": MIN_COMMISSION},
        },
        "arms_stats": {},
    }
    TRADE_FIELDS = ["signal_date","index_id","signal","buy_date","sell_date",
        "etf_code","etf_name","track_tier","track_score","match_method",
        "track_low_confidence","buy_price","sell_price","shares","profit",
        "return_pct","hold_days","sell_reason","current_price","market_state",
        "market_tier","market_tier_all","market_tier_cyb","rating","_arm","_source_etf"]
    for arm_key in ARMS:
        arm_stats = {}
        for qk, qm in QUADRANT_META.items():
            qd = {"label": qm["label"], "desc": qm["desc"], "periods": {}, "guidance": {}}
            for mk in SELL_MODES:
                qd["guidance"][mk] = _guidance(qk, mk)
            for pk, pd in PERIODS.items():
                cutoff = pd["cutoff"]
                pdata = {}
                for mk in SELL_MODES:
                    all_t = quadrants[arm_key][qk][mk]
                    pt = [t for t in all_t if t["buy_date"] >= cutoff] if cutoff and cutoff != "0" else list(all_t)
                    # 从交易记录取实际 buy_amount(B3 每只股资金不同)
                    ba = pt[0].get("_buy_amount", BUY_AMOUNT) if pt else BUY_AMOUNT
                    pdata[mk] = _compute_stats(pt, pk, buy_amount=ba)
                qd["periods"][pk] = pdata
            arm_stats[qk] = qd
        output["arms_stats"][arm_key] = arm_stats

    # trades: 每臂×每模式存 all 周期全量(列式), 不按象限拆分(防16x膨胀)
    trades_output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "type": "etf_weight_leader_stock_trades",
        "buy_amount": BUY_AMOUNT,
        "period_cutoffs": {k: v["cutoff"] for k, v in PERIODS.items()},
        "fields": TRADE_FIELDS, "arms_trades": {},
    }

    for arm_key in ARMS:
        arm_trades = {}
        for mk in SELL_MODES:
            # 收集该臂该模式所有象限的交易(去重, 因同一交易可归多象限)
            seen = set()
            all_t = []
            for qk in QUADRANT_META:
                for t in quadrants[arm_key][qk][mk]:
                    key = (t["signal_date"], t["index_id"], t["signal"], t.get("buy_price",0))
                    if key not in seen:
                        seen.add(key); all_t.append(t)
            arm_trades[mk] = [[t.get(f, "") for f in TRADE_FIELDS] for t in all_t]
        trades_output["arms_trades"][arm_key] = arm_trades

    # 汇总
    print("\n=== 四臂回测结果(all周期, rating_high) ===")
    for ak in ARMS:
        pd = output["arms_stats"][ak].get("rating_high", {}).get("periods", {}).get("all", {})
        na = pd.get("A", {}).get("n", 0); wr = pd.get("A", {}).get("win_rate", 0)
        hk = pd.get("A", {}).get("half_kelly", 0); tp = pd.get("A", {}).get("total_profit", 0)
        print(f"  {ak:3s}({ARM_LABELS[ak][:8]:8s}): n={na:5d} wr={wr:.3f} hk={hk:.1f}% profit={tp:.0f}")

    return output, trades_output


def main():
    parser = argparse.ArgumentParser(description="ETF→权重龙头个股 回测")
    parser.add_argument("--output", default=str(DATA_DIR / "signal_kelly_backtest_stock.json"))
    parser.add_argument("--trades-output", default=str(DATA_DIR / "signal_kelly_stock_trades.json"))
    args = parser.parse_args()

    print("=" * 60)
    print("ETF→权重龙头个股 回测: 4臂 x 9模式 x 5周期")
    print(f"ROOT = {PROJ_ROOT}")
    print(f"输出 = {args.output}")
    print("=" * 60)

    data, trades_data = compute()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    sz = os.path.getsize(args.output)
    print(f"\n✓ 输出: {args.output} ({sz} bytes = {sz/1024:.1f} KB)")

    with open(args.trades_output, "w", encoding="utf-8") as f:
        json.dump(trades_data, f, ensure_ascii=False, separators=(",", ":"))
    tsz = os.path.getsize(args.trades_output)
    tt = sum(len(v) for aq in trades_data.get("arms_trades", {}).values() for v in aq.values())
    print(f"✓ 交易记录: {args.trades_output} ({tsz} bytes = {tsz/1024:.1f} KB, {tt} 笔)")

    import gzip
    for p in [args.output, args.trades_output]:
        gz = p + ".gz"
        with open(p, "rb") as src, gzip.open(gz, "wb") as dst:
            dst.write(src.read())
        print(f"✓ gzip: {gz} ({os.path.getsize(gz)} bytes)")


if __name__ == "__main__":
    main()
