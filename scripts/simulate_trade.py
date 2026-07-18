#!/usr/bin/env python3
"""买卖点模拟回测 — 生成静态 HTML 报告。

三种推演路径：
  路径 A：固定 1 万进出（FIFO）— 每次买 1 万，卖 FIFO 卖最早一笔，最多同时 10 笔
  路径 B：全仓进出 — 一次只持有一笔，买用全部现金，卖清仓
  路径 C：买固定 1 万 + 卖清仓 — 每次买 1 万，卖点清仓全部

每种路径 x 三种信号场景：
  1. 主买+卖：仅 buy (C1 主买) + sell
  2. 辅买+卖：仅 buy_aux (B1 辅买) + sell
  3. 主买+辅买+卖：buy + buy_aux + sell 全部

用法：python scripts/simulate_trade.py [--index sh] [--output path]
"""

import argparse
import json
import sqlite3
import os
import sys
import yaml
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sentiment.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.db import get_conn
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static-site", "trade_sim.html")

TOTAL_CAPITAL = 100_000   # 总资金池
POSITION_SIZE = 10_000    # 每次固定操作金额（路径 A / C）
MAX_POSITIONS = 10        # 最多同时持仓 10 笔


def load_name_map():
    """从 indicators.yaml 加载 index_id → 中文名映射。"""
    indicators_yaml = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "indicators.yaml")
    name_map = {}
    if not os.path.exists(indicators_yaml):
        return name_map
    cfg = yaml.safe_load(open(indicators_yaml, encoding="utf-8")) or {}
    for idx in cfg.get("indices", []) or []:
        iid = idx.get("id")
        iname = idx.get("name")
        if iid and iname:
            name_map[iid] = iname
    return name_map


def get_signals(index_id="sh"):
    """获取信号和价格数据。对于 g.* 全球商品，从 JSON 文件读取价格数据。"""
    conn = get_conn()

    if index_id.startswith("g."):
        # 全球商品：从 signal_daily 取信号，从 JSON 文件取价格
        json_key = index_id[2:]  # g.gold -> gold
        base_dir = os.path.dirname(os.path.dirname(__file__))
        json_path = os.path.join(base_dir, "static-site", "data", "global-all.json")
        price_map = {}
        if os.path.exists(json_path):
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            extras = data.get("extras", {})
            records = extras.get(json_key, [])
            for rec in records:
                price_map[rec["date"]] = rec["value"]

        signal_rows = conn.execute(
            "SELECT date, signal, reason FROM signal_daily WHERE index_id=? ORDER BY date",
            (index_id,),
        ).fetchall()

        rows = []
        for date, signal, reason in signal_rows:
            close = price_map.get(date)
            if close is not None:
                rows.append((date, signal, reason, close))

        last_date, last_close = None, None
        if price_map:
            last_date = max(price_map.keys())
            last_close = price_map[last_date]

        conn.close()
        return rows, (last_date, last_close)

    rows = conn.execute(
        """SELECT s.date, s.signal, s.reason, d.close
           FROM signal_daily s
           JOIN index_daily d ON d.index_id = s.index_id AND d.date = s.date
           WHERE s.index_id = ?
           ORDER BY s.date""",
        (index_id,),
    ).fetchall()
    last = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? ORDER BY date DESC LIMIT 1",
        (index_id,),
    ).fetchone()
    conn.close()
    return rows, last


def _ledger(date, op, amount, cash, positions, close, prev_close=None, holdings_cost_before=None, shares_traded=0):
    """构建一条交易记录。

    prev_close: 上一条记录的上证收盘价（None=首条），用于计算指数涨跌
    holdings_cost_before: 交易前的持仓成本（None=首条）
    shares_traded: 本次交易的份额（正=买入，负=卖出）
    """
    holdings_cost = sum(POSITION_SIZE for _ in positions) if positions else 0.0
    total_shares = sum(s for _, _, s in positions) if positions else 0.0
    hv = sum(s * close for _, _, s in positions) if positions else 0.0
    total = cash + hv
    return {
        "date": _fmt_date(date),
        "close": round(close, 2),
        "prev_close": round(prev_close, 2) if prev_close else None,
        "index_chg_pct": round((close - prev_close) / prev_close * 100, 2) if prev_close else None,
        "op": op,
        "amount": round(amount, 2),
        "shares_traded": round(shares_traded, 4),
        "total_shares": round(total_shares, 4),
        "holdings_value": round(hv, 2),
        "holdings_cost_before": round(holdings_cost_before, 2) if holdings_cost_before is not None else None,
        "holdings_cost_after": round(holdings_cost, 2),
        "total_assets": round(total, 2),
        "return_pct": round((total - TOTAL_CAPITAL) / TOTAL_CAPITAL * 100, 2),
    }


# ============================================================
#  路径 A：固定 1 万进出（FIFO）
# ============================================================
def simulate_fixed_1w(scenario_name, signals, buy_types, last_date, last_close):
    cash = TOTAL_CAPITAL
    positions = []  # [(buy_date, buy_close, shares)]
    total_assets_peak = TOTAL_CAPITAL
    total_assets_peak_date = None
    max_holding = 0.0
    max_holding_date = None
    max_holding_total = 0.0
    drawdown_peak = TOTAL_CAPITAL
    max_drawdown = 0.0
    max_drawdown_date = None

    rounds = []
    ledger = []
    buy_count = 0
    sell_count = 0
    skipped_full = 0
    skipped_no_cash = 0
    skipped_no_position = 0
    max_positions_ever = 0
    first_buy_date = None
    prev_close = None  # 上一条 ledger 的上证收盘价

    for date, sig, _, close in signals:
        is_buy = sig in buy_types
        is_sell = sig == "sell"

        if is_buy and cash >= POSITION_SIZE and len(positions) < MAX_POSITIONS:
            if first_buy_date is None:
                first_buy_date = date
            buy_count += 1
            hc_before = sum(POSITION_SIZE for _ in positions)
            shares = POSITION_SIZE / close
            positions.append((date, close, shares))
            cash -= POSITION_SIZE
            hv = sum(s * close for _, _, s in positions)
            if hv > max_holding:
                max_holding = hv
                max_holding_date = date
                max_holding_total = cash + hv
            ledger.append(_ledger(date, "主买" if sig == "buy" else "辅买", POSITION_SIZE, cash, positions, close, prev_close, hc_before, shares_traded=shares))
            prev_close = close

        elif is_buy and len(positions) >= MAX_POSITIONS:
            skipped_full += 1
        elif is_buy and cash < POSITION_SIZE:
            skipped_no_cash += 1
        elif is_sell and positions:
            sell_count += 1
            hc_before = sum(POSITION_SIZE for _ in positions)
            buy_date, buy_close, shares = positions.pop(0)
            sell_amount = shares * close
            cash += sell_amount
            pct = (close - buy_close) / buy_close * 100
            profit = sell_amount - POSITION_SIZE
            rounds.append({
                "buy_date": _fmt_date(buy_date), "buy_close": round(buy_close, 2),
                "sell_date": _fmt_date(date), "sell_close": round(close, 2),
                "hold_days": _days_between(buy_date, date),
                "pct": round(pct, 2), "amount_in": POSITION_SIZE,
                "amount_out": round(sell_amount, 2), "profit": round(profit, 2),
            })
            ledger.append(_ledger(date, "卖出", sell_amount, cash, positions, close, prev_close, hc_before, shares_traded=-shares))
            prev_close = close

        elif is_sell and not positions:
            skipped_no_position += 1

        if len(positions) > max_positions_ever:
            max_positions_ever = len(positions)
        hv = sum(s * close for _, _, s in positions)
        total = cash + hv
        if total > total_assets_peak:
            total_assets_peak = total
            total_assets_peak_date = date
        # max drawdown
        if total > drawdown_peak:
            drawdown_peak = total
        else:
            dd = (drawdown_peak - total) / drawdown_peak * 100
            if dd > max_drawdown:
                max_drawdown = dd
                max_drawdown_date = date

    holdings_value = sum(s * last_close for _, _, s in positions)
    final_total = cash + holdings_value

    # 构建 price_map 计算回合回撤
    price_map = {s[0]: s[3] for s in signals}
    round_dds = _calc_round_drawdowns(rounds, price_map)

    return _build_result(
        scenario_name, cash, positions, rounds, ledger, last_close,
        first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
        max_holding, max_holding_date, max_holding_total, buy_count, sell_count,
        skipped_full, skipped_no_cash, skipped_no_position, max_positions_ever,
        strategy_desc="固定 1 万进出（FIFO）",
        max_drawdown=max_drawdown, max_drawdown_date=max_drawdown_date,
        skip1_label="仓位已满", skip2_label="现金不足", skip3_label="无持仓可卖",
        round_drawdowns=round_dds,
    )


# ============================================================
#  路径 B：全仓进出（一次一笔，买用全部现金，卖清仓）
# ============================================================
def simulate_all_in(scenario_name, signals, buy_types, last_date, last_close):
    """全仓进出：买→清仓→买→清仓，跳过连续同向信号。"""
    cash = TOTAL_CAPITAL
    holding = None  # (buy_date, buy_close, shares) or None
    total_assets_peak = TOTAL_CAPITAL
    total_assets_peak_date = None
    max_holding = 0.0
    max_holding_date = None
    max_holding_total = 0.0
    drawdown_peak = TOTAL_CAPITAL
    max_drawdown = 0.0
    max_drawdown_date = None

    rounds = []
    ledger = []
    buy_count = 0
    sell_count = 0
    skipped_consecutive_buy = 0
    skipped_consecutive_sell = 0
    skipped_no_holding = 0
    first_buy_date = None
    last_signal = None
    prev_close = None

    for date, sig, _, close in signals:
        is_buy = sig in buy_types
        is_sell = sig == "sell"

        if is_buy and holding is None:
            if last_signal == "buy":
                skipped_consecutive_buy += 1
                continue
            if first_buy_date is None:
                first_buy_date = date
            buy_count += 1
            shares = cash / close
            holding = (date, close, shares)
            buy_amount = cash  # all-in
            cash = 0.0
            hv = shares * close
            if hv > max_holding:
                max_holding = hv
                max_holding_date = date
                max_holding_total = cash + hv
            last_signal = "buy"
            entry = _ledger(date, "主买" if sig == "buy" else "辅买", buy_amount, 0.0, [(date, close, shares)], close, prev_close, 0.0, shares_traded=shares)
            entry["holdings_cost_after"] = round(buy_amount, 2)
            ledger.append(entry)
            prev_close = close

        elif is_sell and holding is not None:
            if last_signal == "sell":
                skipped_consecutive_sell += 1
                continue
            sell_count += 1
            buy_date, buy_close, shares = holding
            hc_before = round(shares * buy_close, 2)
            sell_amount = shares * close
            cash = sell_amount
            pct = (close - buy_close) / buy_close * 100
            profit = sell_amount - (shares * buy_close)
            amount_in = round(shares * buy_close, 2)
            rounds.append({
                "buy_date": _fmt_date(buy_date), "buy_close": round(buy_close, 2),
                "sell_date": _fmt_date(date), "sell_close": round(close, 2),
                "hold_days": _days_between(buy_date, date),
                "pct": round(pct, 2), "amount_in": amount_in,
                "amount_out": round(sell_amount, 2), "profit": round(profit, 2),
            })
            holding = None
            last_signal = "sell"
            ledger.append(_ledger(date, "卖出", sell_amount, cash, [], close, prev_close, hc_before, shares_traded=-shares))
            prev_close = close

        elif is_sell and holding is None:
            skipped_no_holding += 1

        # 更新峰值 & drawdown
        hv = holding[2] * close if holding else 0.0
        total = cash + hv
        if total > total_assets_peak:
            total_assets_peak = total
            total_assets_peak_date = date
        if total > drawdown_peak:
            drawdown_peak = total
        else:
            dd = (drawdown_peak - total) / drawdown_peak * 100
            if dd > max_drawdown:
                max_drawdown = dd
                max_drawdown_date = date

    holdings_value = holding[2] * last_close if holding else 0.0
    final_total = cash + holdings_value
    positions = [holding] if holding else []

    # 构建 price_map 计算回合回撤
    price_map = {s[0]: s[3] for s in signals}
    round_dds = _calc_round_drawdowns(rounds, price_map)

    return _build_result(
        scenario_name, cash, positions, rounds, ledger, last_close,
        first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
        max_holding, max_holding_date, max_holding_total, buy_count, sell_count,
        skipped_consecutive_buy, 0, skipped_no_holding, 1 if holding else 0,
        strategy_desc="全仓进出（一次一笔，买全部现金，卖清仓）",
        max_drawdown=max_drawdown, max_drawdown_date=max_drawdown_date,
        skip1_label="连续同向买入", skip2_label="", skip3_label="无持仓可卖",
        round_drawdowns=round_dds,
    )


# ============================================================
#  路径 C：买固定 1 万 + 卖清仓
# ============================================================
def simulate_sell_all(scenario_name, signals, buy_types, last_date, last_close):
    """每次买 1 万（最多 10 笔），出现卖点则清仓全部。"""
    cash = TOTAL_CAPITAL
    positions = []  # [(buy_date, buy_close, shares)]
    total_assets_peak = TOTAL_CAPITAL
    total_assets_peak_date = None
    max_holding = 0.0
    max_holding_date = None
    max_holding_total = 0.0
    drawdown_peak = TOTAL_CAPITAL
    max_drawdown = 0.0
    max_drawdown_date = None

    rounds = []
    ledger = []
    buy_count = 0
    sell_count = 0
    skipped_full = 0
    skipped_no_cash = 0
    skipped_no_position = 0
    max_positions_ever = 0
    first_buy_date = None
    last_signal = None
    prev_close = None

    for date, sig, _, close in signals:
        is_buy = sig in buy_types
        is_sell = sig == "sell"

        if is_buy and cash >= POSITION_SIZE and len(positions) < MAX_POSITIONS:
            if first_buy_date is None:
                first_buy_date = date
            buy_count += 1
            hc_before = sum(POSITION_SIZE for _ in positions)
            shares = POSITION_SIZE / close
            positions.append((date, close, shares))
            cash -= POSITION_SIZE
            hv = sum(s * close for _, _, s in positions)
            if hv > max_holding:
                max_holding = hv
                max_holding_date = date
                max_holding_total = cash + hv
            last_signal = "buy"
            ledger.append(_ledger(date, "主买" if sig == "buy" else "辅买", POSITION_SIZE, cash, positions, close, prev_close, hc_before, shares_traded=shares))
            prev_close = close

        elif is_buy and len(positions) >= MAX_POSITIONS:
            skipped_full += 1
        elif is_buy and cash < POSITION_SIZE:
            skipped_no_cash += 1
        elif is_sell and positions:
            if last_signal == "sell":
                continue
            sell_count += 1
            hc_before = sum(POSITION_SIZE for _ in positions)
            # 清仓全部
            sold = []
            total_amount_in = 0.0
            total_amount_out = 0.0
            total_profit = 0.0
            total_shares_sold = 0.0
            while positions:
                buy_date, buy_close, shares = positions.pop(0)
                total_shares_sold += shares
                sell_amount = shares * close
                cash += sell_amount
                total_amount_in += POSITION_SIZE
                total_amount_out += sell_amount
                total_profit += sell_amount - POSITION_SIZE
                sold.append({
                    "buy_date": _fmt_date(buy_date), "buy_close": round(buy_close, 2),
                    "sell_date": _fmt_date(date), "sell_close": round(close, 2),
                    "hold_days": _days_between(buy_date, date),
                    "pct": round((close - buy_close) / buy_close * 100, 2),
                    "amount_in": POSITION_SIZE,
                    "amount_out": round(sell_amount, 2),
                    "profit": round(sell_amount - POSITION_SIZE, 2),
                })
            rounds.append({
                "buy_date": sold[0]["buy_date"] if len(sold) == 1 else f"{sold[0]['buy_date']}~{sold[-1]['buy_date']}",
                "buy_close": round(sum(s["buy_close"] for s in sold) / len(sold), 2),
                "sell_date": _fmt_date(date),
                "sell_close": round(close, 2),
                "hold_days": sum(s["hold_days"] for s in sold),
                "pct": round(total_profit / total_amount_in * 100, 2) if total_amount_in else 0,
                "amount_in": round(total_amount_in, 2),
                "amount_out": round(total_amount_out, 2),
                "profit": round(total_profit, 2),
                "_sub_rounds": sold,
            })
            last_signal = "sell"
            ledger.append(_ledger(date, "清仓卖出", total_amount_out, cash, [], close, prev_close, hc_before, shares_traded=-total_shares_sold))
            prev_close = close

        elif is_sell and not positions:
            skipped_no_position += 1

        if len(positions) > max_positions_ever:
            max_positions_ever = len(positions)
        hv = sum(s * close for _, _, s in positions)
        total = cash + hv
        if total > total_assets_peak:
            total_assets_peak = total
            total_assets_peak_date = date
        # max drawdown
        if total > drawdown_peak:
            drawdown_peak = total
        else:
            dd = (drawdown_peak - total) / drawdown_peak * 100
            if dd > max_drawdown:
                max_drawdown = dd
                max_drawdown_date = date

    holdings_value = sum(s * last_close for _, _, s in positions)
    final_total = cash + holdings_value

    # 构建 price_map 计算回合回撤
    price_map = {s[0]: s[3] for s in signals}
    round_dds = _calc_round_drawdowns(rounds, price_map)

    return _build_result(
        scenario_name, cash, positions, rounds, ledger, last_close,
        first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
        max_holding, max_holding_date, max_holding_total, buy_count, sell_count,
        skipped_full, skipped_no_cash, skipped_no_position, max_positions_ever,
        strategy_desc="买固定 1 万 + 卖清仓全部",
        max_drawdown=max_drawdown, max_drawdown_date=max_drawdown_date,
        skip1_label="仓位已满", skip2_label="现金不足", skip3_label="无持仓可卖",
        round_drawdowns=round_dds,
    )


# ============================================================
#  公共：构建结果 & 计算统计
# ============================================================
def _build_result(scenario_name, cash, positions, rounds, ledger, last_close,
                  first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
                  max_holding, max_holding_date, max_holding_total, buy_count, sell_count,
                  skip1, skip2, skip3, max_positions_ever, strategy_desc="",
                  max_drawdown=0.0, max_drawdown_date=None,
                  skip1_label="跳过", skip2_label="跳过", skip3_label="跳过",
                  round_drawdowns=None):
    holdings_value = sum(s * last_close for _, _, s in positions)
    final_total = cash + holdings_value
    total_return = final_total - TOTAL_CAPITAL
    total_return_pct = total_return / TOTAL_CAPITAL * 100

    if first_buy_date:
        years = _days_between(first_buy_date, last_date) / 365.25
        annualized = ((final_total / TOTAL_CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0
    else:
        years = 0
        annualized = 0

    # 未平仓
    open_positions = []
    for buy_date, buy_close, shares in positions:
        open_positions.append({
            "buy_date": _fmt_date(buy_date), "buy_close": round(buy_close, 2),
            "shares": round(shares, 4),
            "current_value": round(shares * last_close, 2),
            "pct": round((last_close - buy_close) / buy_close * 100, 2),
            "profit": round(shares * last_close - POSITION_SIZE, 2),
        })

    # 流水描述
    flow_parts = [f"总资金 {TOTAL_CAPITAL:,} 元"]
    flow_parts.append(strategy_desc)
    if first_buy_date:
        flow_parts.append(f"{_fmt_date(first_buy_date)} 首笔买入")
    skip_parts = []
    if skip1:
        skip_parts.append(f"{skip1_label} {skip1} 次")
    if skip2:
        skip_parts.append(f"{skip2_label} {skip2} 次")
    if skip3:
        skip_parts.append(f"{skip3_label} {skip3} 次")
    if skip_parts:
        flow_parts.append("跳过: " + " · ".join(skip_parts))
    if positions:
        flow_parts.append(f"→ 经 {len(rounds)} 轮买卖 + {len(positions)} 笔未平仓")
        flow_parts.append(f"→ 期末总资产 {final_total:,.0f} 元（现金 {cash:,.0f} + 持仓 {holdings_value:,.0f}）")
    else:
        flow_parts.append(f"→ 经 {len(rounds)} 轮买卖 → 期末空仓，总资产 {final_total:,.0f} 元")
    flow_desc = " · ".join(flow_parts)

    # 胜率统计
    win_rounds = [r for r in rounds if r["profit"] > 0]
    lose_rounds = [r for r in rounds if r["profit"] < 0]
    win_count = len(win_rounds)
    lose_count = len(lose_rounds)
    win_rate = win_count / len(rounds) * 100 if rounds else 0
    avg_win_pct = sum(r["pct"] for r in win_rounds) / win_count if win_count else 0
    avg_loss_pct = sum(r["pct"] for r in lose_rounds) / lose_count if lose_count else 0
    avg_pl_ratio = abs(avg_win_pct / avg_loss_pct) if avg_loss_pct != 0 else float("inf")

    # 最长连胜/连败
    max_win_streak = 0
    max_lose_streak = 0
    cur_win = 0
    cur_lose = 0
    for r in rounds:
        if r["profit"] > 0:
            cur_win += 1
            cur_lose = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif r["profit"] < 0:
            cur_lose += 1
            cur_win = 0
            max_lose_streak = max(max_lose_streak, cur_lose)
        else:
            cur_win = 0
            cur_lose = 0

    # 回撤中位数 & 去极值回撤均值
    median_dd = 0.0
    trimmed_mean_dd = 0.0
    if round_drawdowns and len(round_drawdowns) > 0:
        sorted_dds = sorted(round_drawdowns)
        n = len(sorted_dds)
        # 中位数
        if n % 2 == 1:
            median_dd = sorted_dds[n // 2]
        else:
            median_dd = (sorted_dds[n // 2 - 1] + sorted_dds[n // 2]) / 2
        # 去极值均值（去掉顶部10%和底部10%）
        trim_n = max(1, int(n * 0.1))
        if n > 2 * trim_n:
            trimmed = sorted_dds[trim_n:n - trim_n]
            trimmed_mean_dd = sum(trimmed) / len(trimmed)
        else:
            trimmed_mean_dd = sum(sorted_dds) / n

    return {
        "rounds": rounds,
        "ledger": ledger,
        "open_positions": open_positions,
        "summary": {
            "scenario": scenario_name,
            "strategy": strategy_desc,
            "total_capital": TOTAL_CAPITAL,
            "position_size": POSITION_SIZE,
            "total_ops": buy_count + sell_count,
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "final_total": round(final_total, 2),
            "final_cash": round(cash, 2),
            "final_holdings": round(holdings_value, 2),
            "total_assets_peak": round(total_assets_peak, 2),
            "total_assets_peak_date": _fmt_date(total_assets_peak_date) if total_assets_peak_date else "N/A",
            "max_holding": round(max_holding, 2),
            "max_holding_date": _fmt_date(max_holding_date) if max_holding_date else "N/A",
            "max_holding_total": round(max_holding_total, 2),
            "max_holding_pct": round(max_holding / max_holding_total * 100, 1) if max_holding_total > 0 else 0,
            "max_drawdown": round(max_drawdown, 2),
            "max_drawdown_date": _fmt_date(max_drawdown_date) if max_drawdown_date else "N/A",
            "max_win_streak": max_win_streak,
            "max_lose_streak": max_lose_streak,
            "buy_count": buy_count,
            "sell_count": sell_count,
            "skipped_full": skip1,
            "skipped_no_cash": skip2,
            "skipped_no_position": skip3,
            "max_positions_ever": max_positions_ever,
            "total_rounds": len(rounds),
            "open_count": len(positions),
            "ledger_count": len(ledger),
            "years": round(years, 1),
            "annualized": round(annualized, 1),
            "win_count": win_count,
            "lose_count": lose_count,
            "win_rate": round(win_rate, 1),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "avg_pl_ratio": round(avg_pl_ratio, 2),
            "median_drawdown": round(median_dd, 2),
            "trimmed_mean_drawdown": round(trimmed_mean_dd, 2),
            "flow_desc": flow_desc,
        },
    }


def _calc_round_drawdowns(rounds, price_map):
    """计算每个回合的回合内最大回撤。
    price_map: {date_str_YYYYMMDD: close_price}
    返回: list of drawdown percentages (float)
    """
    dds = []
    for r in rounds:
        buy_date = r["buy_date"].replace("-", "")  # 2024-01-15 → 20240115
        sell_date = r["sell_date"].replace("-", "")
        # 取区间内所有价格
        prices = [close for d, close in price_map.items() if buy_date <= d <= sell_date]
        if len(prices) < 2:
            dds.append(0.0)
            continue
        # 找到峰值到谷底的最大回撤
        peak = prices[0]
        max_dd = 0.0
        for p in prices[1:]:
            if p > peak:
                peak = p
            dd = (peak - p) / peak * 100
            if dd > max_dd:
                max_dd = dd
        dds.append(round(max_dd, 2))
    return dds


def _days_between(d1, d2):
    dt1 = datetime(int(d1[:4]), int(d1[4:6]), int(d1[6:8]))
    dt2 = datetime(int(d2[:4]), int(d2[4:6]), int(d2[6:8]))
    return (dt2 - dt1).days


def _fmt_date(d):
    """Convert YYYYMMDD to YYYY-MM-DD."""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _equity_svg(ledger, chart_id=0):
    """Generate a mini SVG equity curve from ledger data with title, values, and labels."""
    if len(ledger) < 2:
        return ""
    values = [e["total_assets"] for e in ledger]
    y_min = min(min(values), TOTAL_CAPITAL) * 0.95
    y_max = max(max(values), TOTAL_CAPITAL) * 1.05
    height = 160
    width = 800
    margin_left = 80
    margin_right = 10
    margin_top = 5
    margin_bottom = 24
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    n = len(values)

    def scale_y(v):
        return margin_top + plot_height - (v - y_min) / (y_max - y_min) * plot_height if y_max > y_min else margin_top + plot_height / 2

    def scale_x(i):
        return margin_left + i / (n - 1) * plot_width if n > 1 else margin_left

    baseline_y = scale_y(TOTAL_CAPITAL)
    final_val = values[-1]
    peak_val = max(values)
    peak_idx = values.index(peak_val)
    min_val = min(values)
    min_idx = values.index(min_val)

    points = []
    for i, v in enumerate(values):
        x = scale_x(i)
        y = scale_y(v)
        points.append(f"{x:.1f},{y:.1f}")

    area_points = " ".join(points)
    area_points += f" {scale_x(n-1):.1f},{margin_top + plot_height:.1f} {scale_x(0):.1f},{margin_top + plot_height:.1f}"

    # Y-axis labels: 起始, 最低, 峰值, 期末
    def fmt_val(v):
        if v >= 10000:
            return f"{v/10000:.1f}万"
        return f"{v:.0f}"

    y_labels = []
    for label, val, color in [
        ("起始", TOTAL_CAPITAL, "var(--text-3)"),
        ("最低", min_val, "#e6492e"),
        ("峰值", peak_val, "#2e8b57"),
        ("期末", final_val, "#3370ff"),
    ]:
        y = scale_y(val)
        y_labels.append(f'<text x="{margin_left - 4}" y="{y:.1f}" text-anchor="end" font-size="10" fill="{color}" dominant-baseline="middle">{label} {fmt_val(val)}</text>')

    # 峰值 marker
    peak_marker = f'<circle cx="{scale_x(peak_idx):.1f}" cy="{scale_y(peak_val):.1f}" r="3" fill="#2e8b57" stroke="#fff" stroke-width="1"/>'
    # 期末 marker
    final_marker = f'<circle cx="{scale_x(n-1):.1f}" cy="{scale_y(final_val):.1f}" r="3" fill="#3370ff" stroke="#fff" stroke-width="1"/>'

    # X-axis time labels: evenly spaced year-month labels
    x_labels = []
    dates = [e["date"] for e in ledger]
    # pick ~5-7 evenly spaced ticks
    tick_count = min(7, max(3, n // 2))
    step = (n - 1) / (tick_count - 1) if tick_count > 1 else 1
    for k in range(tick_count):
        i = min(int(round(k * step)), n - 1)
        if i >= n:
            i = n - 1
        date_str = dates[i]  # format: YYYY-MM-DD
        label = date_str[:7]  # YYYY-MM
        x = scale_x(i)
        x_labels.append(f'<text x="{x:.1f}" y="{height - 4:.1f}" text-anchor="middle" font-size="9" fill="var(--text-3)">{label}</text>')

    return f'''
    <svg width="100%" height="150" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" style="display:block;margin-top:8px;border-radius:6px;background:var(--bg-hover)">
      <defs>
        <linearGradient id="equityGrad{chart_id}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#3370ff" stop-opacity="0.12"/>
          <stop offset="100%" stop-color="#3370ff" stop-opacity="0.01"/>
        </linearGradient>
      </defs>
      <line x1="{margin_left}" y1="{baseline_y:.1f}" x2="{scale_x(n-1):.1f}" y2="{baseline_y:.1f}" stroke="var(--border)" stroke-dasharray="6,4" stroke-width="1"/>
      <polygon points="{area_points}" fill="url(#equityGrad{chart_id})"/>
      <polyline points="{' '.join(points)}" fill="none" stroke="#3370ff" stroke-width="1.5" stroke-linejoin="round"/>
      {' '.join(y_labels)}
      {peak_marker}
      {final_marker}
      {' '.join(x_labels)}
    </svg>'''


def color_for_pct(pct):
    if pct > 0:
        return "#e6492e"
    elif pct < 0:
        return "#2e8b57"
    return "#9e9e9e"


def format_num(n):
    if n is None or n == float("inf"):
        return "-"
    return f"{n:,.2f}"


# ============================================================
#  HTML 构建（两级 Tab：外层策略路径，内层信号组合）
# ============================================================
def _scenario_panel(data, index_name="上证指数"):
    """构建单个场景的内容面板（卡片 → SVG曲线 → 交易记录清单 → 未平仓 → 回合表）。"""
    s = data["summary"]

    # --- 资产曲线 SVG 迷你图 ---
    equity_svg = f'<h3 style="margin: 20px 0 2px; font-size: 15px;">📈 资产变化曲线</h3><p style="margin:0 0 4px;font-size:11px;color:var(--text-3)">虚线 = 初始资金 {TOTAL_CAPITAL:,} 元 · 蓝色 = 期末 · 绿色 = 峰值 · 红色 = 最低</p>' + _equity_svg(data.get("ledger", []))

    # --- 交易记录清单（时间轴） ---
    ledger_rows = ""
    for j, entry in enumerate(data.get("ledger", [])):
        op_class = "sell" if "卖" in entry["op"] else ("buy_aux" if "辅买" in entry["op"] else "buy")
        op_badge = f'<span class="ledger-op {op_class}">{entry["op"]}</span>'
        pct_str = f'{entry["return_pct"]:+.2f}%'
        pct_color = color_for_pct(entry["return_pct"])
        # 收盘价
        close_str = f'{entry["close"]:.2f}'
        # 较上条涨跌
        idx_chg = entry.get("index_chg_pct")
        if idx_chg is not None:
            idx_chg_color = color_for_pct(idx_chg)
            idx_chg_str = f'<span style="color:{idx_chg_color};font-weight:600">{idx_chg:+.2f}%</span>'
        else:
            idx_chg_str = '<span style="color:var(--text-3)">—</span>'
        # 份额变动
        shares_trd = entry.get("shares_traded", 0)
        if shares_trd > 0:
            shares_str = f'<span style="color:#e6492e;font-weight:600">+{shares_trd:.2f}</span>'
        elif shares_trd < 0:
            shares_str = f'<span style="color:#2e8b57;font-weight:600">{shares_trd:.2f}</span>'
        else:
            shares_str = '<span style="color:var(--text-3)">—</span>'
        # 持仓份额
        total_sh = entry.get("total_shares", 0)
        total_sh_str = f'{total_sh:.2f}' if total_sh > 0 else '<span style="color:var(--text-3)">0</span>'
        # 持仓市值
        hv = entry.get("holdings_value", 0)
        hv_str = format_num(hv) if hv > 0 else '<span style="color:var(--text-3)">0</span>'
        # 交易金额 + 份额关系标注
        amt = entry["amount"]
        if shares_trd > 0:
            amt_str = f'{format_num(amt)} <span style="font-size:10px;color:var(--text-3)">(←{shares_trd:.2f}股)</span>'
        elif shares_trd < 0:
            amt_str = f'{format_num(amt)} <span style="font-size:10px;color:var(--text-3)">({abs(shares_trd):.2f}股→)</span>'
        else:
            amt_str = format_num(amt)
        ledger_rows += f"""
        <tr>
          <td>{j + 1}</td>
          <td>{entry['date']}</td>
          <td style="white-space:nowrap">{close_str}</td>
          <td>{idx_chg_str}</td>
          <td>{op_badge}</td>
          <td>{amt_str}</td>
          <td>{shares_str}</td>
          <td>{total_sh_str}</td>
          <td>{hv_str}</td>
          <td>{format_num(entry['total_assets'])}</td>
          <td style="color:{pct_color};font-weight:600">{pct_str}</td>
        </tr>"""

    ledger_html = f"""
    <h3 style="margin: 20px 0 2px; font-size: 15px;">📒 交易记录清单（{s['ledger_count']} 笔，按时间轴）</h3>
    <p style="margin:0 0 8px;font-size:11px;color:var(--text-3)">💡 买入：固定金额 → 得份额；卖出：卖份额 → 得市值（金额 ≠ 买入成本）。份额变动 +红/-绿，持仓市值 = 份额 × {index_name}收盘价。</p>
    <div class="sim-table-wrap">
      <table>
        <thead><tr>
          <th>#</th><th>日期</th><th>{index_name}收盘</th><th>较上条涨跌</th><th>操作</th><th>交易金额</th><th>份额变动</th><th>持仓份额</th><th>持仓市值</th><th>当前总资产</th><th>累计收益率</th>
        </tr></thead>
        <tbody>{ledger_rows}</tbody>
      </table>
    </div>"""

    # --- 未平仓列表 ---
    open_html = ""
    if data["open_positions"]:
        open_rows = ""
        for j, op in enumerate(data["open_positions"]):
            open_rows += f"""
            <tr>
              <td>{j + 1}</td>
              <td>{op['buy_date']}</td>
              <td>{op['buy_close']}</td>
              <td>{op['shares']}</td>
              <td style="color:{color_for_pct(op['pct'])};font-weight:600">{op['pct']:+.2f}%</td>
              <td>{format_num(op['current_value'])}</td>
              <td style="color:{color_for_pct(op['profit'])};font-weight:600">{op['profit']:+.2f}</td>
            </tr>"""
        open_html = f"""
        <h3 style="margin: 20px 0 10px; font-size: 15px;">📌 未平仓持仓（{s['open_count']} 笔，按最后交易日收盘价估值）</h3>
        <div class="sim-table-wrap">
          <table>
            <thead><tr><th>#</th><th>买入日期</th><th>买入价</th><th>份额</th><th>浮动盈亏%</th><th>当前市值</th><th>浮动盈亏</th></tr></thead>
            <tbody>{open_rows}</tbody>
          </table>
        </div>"""

    # --- 摘要卡片 ---
    dd_str = f"{s['max_drawdown']:.1f}%"
    dd_date = s.get("max_drawdown_date", "N/A")
    cards = f"""
    <div class="sim-flow">{s['flow_desc']}</div>
    <div class="sim-cards">
      <div class="sim-card"><span class="k">总资产变化</span><span class="v">{format_num(s['total_capital'])} → {format_num(s['final_total'])} 元<div class="sub" style="font-size:11px;color:var(--text-3);">期末持仓 {format_num(s['final_holdings'])} 元</div></span></div>
      <div class="sim-card"><span class="k">最大持仓</span><span class="v">{format_num(s['max_holding'])} 元（{s['max_holding_pct']}%）<div class="sub">{s['max_holding_date']}</div></span></div>
      <div class="sim-card"><span class="k">总收益</span><span class="v" style="color:{color_for_pct(s['total_return'])}">{format_num(s['total_return'])} 元（{s['total_return_pct']:+.2f}%）</span></div>
      <div class="sim-card"><span class="k">年化收益率</span><span class="v" style="color:{color_for_pct(s['annualized'])}">{s['annualized']:+.1f}%<div class="sub">首笔买入至今 {s['years']} 年</div></span></div>
      <div class="sim-card"><span class="k">总资产峰值</span><span class="v">{format_num(s['total_assets_peak'])} 元<div class="sub">{s['total_assets_peak_date']}</div></span></div>
      <div class="sim-card"><span class="k">最大回撤</span><span class="v" style="color:{color_for_pct(-s['max_drawdown'])}">{dd_str}<div class="sub">{dd_date}</div></span></div>
      <div class="sim-card"><span class="k">回撤中位数 / 回撤去极均值</span><span class="v" style="color:{color_for_pct(-s['median_drawdown'])}">{s['median_drawdown']:.1f}% / {s['trimmed_mean_drawdown']:.1f}%</span></div>
      <div class="sim-card"><span class="k">总操作</span><span class="v">{s['buy_count']}买/{s['sell_count']}卖（{s['buy_count'] + s['sell_count']}次）<div class="sub">共 {s['total_ops'] + s['skipped_full'] + s['skipped_no_cash'] + s['skipped_no_position']} 次信号 · <span title="仓位已满/现金不足/无持仓可卖时跳过不执行">跳过 {s['skipped_full'] + s['skipped_no_cash'] + s['skipped_no_position']} 次</span> · <span title="同时持有的最大未平仓笔数">峰值并发 {s['max_positions_ever']} 笔</span></div></span></div>
      <div class="sim-card"><span class="k">胜率</span><span class="v">{s['win_rate']}%（{s['win_count']}胜/{s['lose_count']}负）</span></div>
      <div class="sim-card"><span class="k">最长连胜/连败</span><span class="v">{s['max_win_streak']} 轮 / {s['max_lose_streak']} 轮</span></div>
      <div class="sim-card"><span class="k">平均盈亏比</span><span class="v">{format_num(s['avg_pl_ratio'])}（均盈{format_num(s['avg_win_pct'])}% / 均亏{format_num(s['avg_loss_pct'])}%）</span></div>
      <div class="sim-card"><span class="k">配对情况</span><span class="v">{s['total_rounds']}笔成对 · {s['open_count']}笔未平仓</span></div>
    </div>"""

    # --- 已完成回合表 ---
    rows = ""
    for j, r in enumerate(data["rounds"]):
        sub_rows = ""
        if "_sub_rounds" in r and len(r["_sub_rounds"]) > 1:
            for sr in r["_sub_rounds"]:
                sub_rows += f"""
            <tr style="background:var(--bg-hover);font-size:11px;color:var(--text-2)">
              <td colspan="2" style="padding-left:20px;border-left:3px solid var(--border-strong)">└ {sr['buy_date']}</td>
              <td>{sr['buy_close']}</td>
              <td colspan="2"></td>
              <td>{sr['hold_days']} 天</td>
              <td style="color:{color_for_pct(sr['pct'])};font-weight:600">{sr['pct']:+.2f}%</td>
              <td>{format_num(sr['amount_in'])}</td>
              <td>{format_num(sr['amount_out'])}</td>
              <td style="color:{color_for_pct(sr['profit'])};font-weight:600">{sr['profit']:+.2f}</td>
            </tr>"""
        rows += f"""
        <tr>
          <td>{j + 1}</td>
          <td>{r['buy_date']}</td>
          <td>{r['buy_close']}</td>
          <td>{r['sell_date']}</td>
          <td>{r['sell_close']}</td>
          <td>{r['hold_days']} 天</td>
          <td style="color:{color_for_pct(r['pct'])};font-weight:600">{r['pct']:+.2f}%</td>
          <td>{format_num(r['amount_in'])}</td>
          <td>{format_num(r['amount_out'])}</td>
          <td style="color:{color_for_pct(r['profit'])};font-weight:600">{r['profit']:+.2f}</td>
        </tr>{sub_rows}"""

    table = f"""
    <h3 style="margin: 20px 0 10px; font-size: 15px;">📋 已完成回合（{s['total_rounds']} 轮）</h3>
    <div class="sim-table-wrap">
      <table>
        <thead><tr>
          <th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th>
          <th>持有时长</th><th>盈亏%</th><th>投入</th><th>回收</th><th>净利润</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>"""

    return cards + equity_svg + ledger_html + open_html + table


def build_html(groups, index_id="sh", index_name="上证指数", signal_first_date=None, signal_last_date=None):
    """构建两级 Tab 页面。"""
    path_labels = list(groups.keys())
    sig_labels = list(next(iter(groups.values())).keys())

    # --- 九场景全局对比表 ---
    comparison_rows = []
    for path_label in path_labels:
        for sig_label in sig_labels:
            s = groups[path_label][sig_label]["summary"]
            comparison_rows.append({
                "path": path_label,
                "sig": sig_label,
                "final_total": s["final_total"],
                "total_return_pct": s["total_return_pct"],
                "annualized": s["annualized"],
                "max_drawdown": s.get("max_drawdown", 0),
                "median_drawdown": s.get("median_drawdown", 0),
                "trimmed_mean_drawdown": s.get("trimmed_mean_drawdown", 0),
                "win_rate": s["win_rate"],
                "total_ops": s["total_ops"],
            })

    # 计算每列最优值
    best_final = max(r["final_total"] for r in comparison_rows)
    best_return = max(r["total_return_pct"] for r in comparison_rows)
    best_annual = max(r["annualized"] for r in comparison_rows)
    best_dd = min(r["max_drawdown"] for r in comparison_rows)
    best_median_dd = min(r["median_drawdown"] for r in comparison_rows)
    best_trimmed_dd = min(r["trimmed_mean_drawdown"] for r in comparison_rows)
    best_win = max(r["win_rate"] for r in comparison_rows)
    best_ops = max(r["total_ops"] for r in comparison_rows)

    # 计算每列最差值（回撤类 worst=max，其余 worst=min；与 best 语义对称）
    worst_final = min(r["final_total"] for r in comparison_rows)
    worst_return = min(r["total_return_pct"] for r in comparison_rows)
    worst_annual = min(r["annualized"] for r in comparison_rows)
    worst_dd = max(r["max_drawdown"] for r in comparison_rows)
    worst_median_dd = max(r["median_drawdown"] for r in comparison_rows)
    worst_trimmed_dd = max(r["trimmed_mean_drawdown"] for r in comparison_rows)
    worst_win = min(r["win_rate"] for r in comparison_rows)
    worst_ops = min(r["total_ops"] for r in comparison_rows)

    def cmp_cell(val, best, worst, fmt=".2f", is_pct=False, suffix="", signed=False):
        """渲染策略对比单元格。
        最好=金底加粗(var(--bg-best)跟主题)，最坏=灰底加粗(var(--bg-worst)跟主题)，最好优先(列内全同标金底)。
        signed=True 时字色按正红负绿0灰(正=#e6492e 负=#2e8b57 0=#9e9e9e)；signed=False 黑字。
        底色与字色不冲突：底色高亮最好/最坏，字色留给正负。"""
        is_best = abs(val - best) < 0.001
        is_worst = abs(val - worst) < 0.001
        style_parts = []
        if is_best:
            style_parts.append("background:var(--bg-best);font-weight:700")
        elif is_worst:
            style_parts.append("background:var(--bg-worst);font-weight:700")
        if signed:
            if val > 0:
                style_parts.append("color:#e6492e")
            elif val < 0:
                style_parts.append("color:#2e8b57")
            else:
                style_parts.append("color:#9e9e9e")
        style_attr = f' style="{";".join(style_parts)}"' if style_parts else ""
        if is_pct:
            return f'<span{style_attr}>{val:+.2f}%</span>'
        return f'<span{style_attr}>{val:{fmt}}{suffix}</span>'

    cmp_table_rows = ""
    for r in comparison_rows:
        cmp_table_rows += f"""
        <tr>
          <td>{r['path']}</td>
          <td>{r['sig']}</td>
          <td>{cmp_cell(r['final_total'], best_final, worst_final, ',.0f', suffix=' 元')}</td>
          <td>{cmp_cell(r['total_return_pct'], best_return, worst_return, '.2f', is_pct=True, signed=True)}</td>
          <td>{cmp_cell(r['annualized'], best_annual, worst_annual, '.1f', is_pct=True, signed=True)}</td>
          <td>{cmp_cell(r['max_drawdown'], best_dd, worst_dd, '.1f', is_pct=True)}</td>
          <td>{cmp_cell(r['median_drawdown'], best_median_dd, worst_median_dd, '.1f', is_pct=True)}</td>
          <td>{cmp_cell(r['trimmed_mean_drawdown'], best_trimmed_dd, worst_trimmed_dd, '.1f', is_pct=True)}</td>
          <td>{cmp_cell(r['win_rate'], best_win, worst_win, '.1f', is_pct=True)}</td>
          <td>{cmp_cell(r['total_ops'], best_ops, worst_ops, '.0f', suffix=' 次')}</td>
        </tr>"""

    comparison_table = f"""
    <div class="sim-cmp-table">
      <table>
        <thead><tr>
          <th>策略</th><th>信号</th><th>最终资产</th><th>总收益率</th><th>年化</th><th>最大回撤</th><th>回撤中位数</th><th>回撤去极均值</th><th>胜率</th><th>交易笔数</th>
        </tr></thead>
        <tbody>{cmp_table_rows}</tbody>
      </table>
    </div>"""

    # --- 回测区间 ---
    backtest_info = ""
    if signal_first_date and signal_last_date:
        first_fmt = _fmt_date(signal_first_date)
        last_fmt = _fmt_date(signal_last_date)
        bt_years = _days_between(signal_first_date, signal_last_date) / 365.25
        backtest_info = f" · 回测区间：{first_fmt} ~ {last_fmt}（{bt_years:.1f} 年）"

    main_tabs = ""
    for pi, plabel in enumerate(path_labels):
        active = "active" if pi == 0 else ""
        main_tabs += f'<button class="sim-main-tab {active}" data-path="{pi}">{plabel}</button>\n'

    groups_html = ""
    for pi, plabel in enumerate(path_labels):
        active_grp = "active" if pi == 0 else ""
        sub_tabs = ""
        sub_panels = ""
        sub_scenarios = groups[plabel]
        for si, slabel in enumerate(sig_labels):
            active_sub = "active" if si == 0 else ""
            sub_tabs += f'<button class="sim-sub-tab {active_sub}" data-path="{pi}" data-sig="{si}">{slabel}</button>\n'
            data = sub_scenarios[slabel]
            panel = _scenario_panel(data, index_name)
            sub_panels += f'<div class="sim-scenario {active_sub}" data-path="{pi}" data-sig="{si}">{panel}</div>\n'

        groups_html += f"""
        <div class="sim-path-group {active_grp}" data-path="{pi}">
          <div class="sim-sub-tabs">{sub_tabs}</div>
          {sub_panels}
        </div>"""

    # 主题变量 CSS（与父页面 static-site/style.css 一致；iframe 是独立文档，需自带变量定义）
    THEME_CSS = """
:root {
  --bg-page: #f5f6f8; --bg-card: #fff; --bg-hover: #f7f8fa; --bg-active: #f0f5ff;
  --border: #e5e6eb; --border-strong: #d9dce0;
  --text-1: #1f2329; --text-2: #4e5969; --text-3: #86909c; --text-4: #c9cdd4;
  --primary: #165dff; --primary-hover: #0e42d2; --primary-bg: #f0f5ff;
  --shadow: rgba(0,0,0,0.04); --shadow-strong: rgba(0,0,0,0.12);
  --bg-best: #fff8e1; --bg-worst: #f5f5f5;
}
[data-theme="dark"] {
  --bg-page: #0d1117; --bg-card: #161b22; --bg-hover: #21262d; --bg-active: #1c2333;
  --border: #30363d; --border-strong: #484f58;
  --text-1: #e6edf3; --text-2: #b1bac4; --text-3: #7d8590; --text-4: #484f58;
  --primary: #58a6ff; --primary-hover: #79b8ff; --primary-bg: #1c2536;
  --shadow: rgba(0,0,0,0.3); --shadow-strong: rgba(0,0,0,0.5);
  --bg-best: rgba(240,185,11,0.16); --bg-worst: rgba(255,255,255,0.06);
}
[data-theme="redgold"] {
  --bg-page: #1a1d29; --bg-card: #252836; --bg-hover: #2d3142; --bg-active: #3a2e1a;
  --border: #3a3d4d; --border-strong: #545767;
  --text-1: #f0e6c4; --text-2: #c4b896; --text-3: #8a7f5e; --text-4: #5c5444;
  --primary: #f0b90b; --primary-hover: #ffc933; --primary-bg: #2a2410;
  --shadow: rgba(0,0,0,0.3); --shadow-strong: rgba(0,0,0,0.5);
  --bg-best: rgba(240,185,11,0.22); --bg-worst: rgba(0,0,0,0.20);
}
[data-theme="morandi"] {
  --bg-page: #f5f1ec; --bg-card: #fffaf3; --bg-hover: #ede7df; --bg-active: #e6e9ed;
  --border: #d9d3cb; --border-strong: #c2bbb0;
  --text-1: #3d3a35; --text-2: #6b665e; --text-3: #9a948a; --text-4: #b8b2a6;
  --primary: #6b7c93; --primary-hover: #5a6b82; --primary-bg: #e6e9ed;
  --shadow: rgba(120,110,90,0.06); --shadow-strong: rgba(120,110,90,0.14);
  --bg-best: #e8dcc4; --bg-worst: #e0dad0;
}
"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{index_name} · 买卖点模拟回测</title>
<style>
{THEME_CSS}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: var(--bg-page); color: var(--text-1); padding: 24px; max-width: 1200px; margin: 0 auto; }}
h1 {{ font-size: 20px; margin-bottom: 4px; }}
.subtitle {{ color: var(--text-3); font-size: 13px; margin-bottom: 20px; }}

/* 全局对比表 */
.sim-cmp-table {{ margin-bottom: 20px; background: var(--bg-card); border-radius: 8px; box-shadow: 0 1px 3px var(--shadow); padding: 8px; overflow-x: auto; }}
.sim-cmp-table table {{ font-size: 12px; width: 100%; border-collapse: collapse; }}
.sim-cmp-table th {{ background: var(--bg-hover); padding: 6px 10px; text-align: left; font-weight: 600; color: var(--text-2); white-space: nowrap; border-bottom: 1px solid var(--border); }}
.sim-cmp-table td {{ padding: 5px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
.sim-cmp-table tr:hover td {{ background: var(--bg-hover); }}

.sim-main-tabs {{ display: flex; gap: 0; margin-bottom: 0; border-bottom: 2px solid var(--border); }}
.sim-main-tab {{ padding: 10px 20px; border: none; background: none; cursor: pointer; font-size: 14px; color: var(--text-2); border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all .2s; }}
.sim-main-tab.active {{ color: var(--text-1); font-weight: 600; border-bottom-color: var(--primary); }}
.sim-main-tab:hover {{ color: var(--text-1); }}

.sim-path-group {{ display: none; }}
.sim-path-group.active {{ display: block; }}

.sim-sub-tabs {{ display: flex; gap: 4px; padding: 10px 0 12px; background: var(--bg-card); border-bottom: 1px solid var(--border); margin-bottom: 16px; }}
.sim-sub-tab {{ padding: 6px 14px; border: 1px solid var(--border-strong); background: var(--bg-card); border-radius: 6px; cursor: pointer; font-size: 13px; color: var(--text-2); transition: all .2s; }}
.sim-sub-tab.active {{ background: var(--primary); color: #fff; border-color: var(--primary); }}
.sim-sub-tab:hover:not(.active) {{ background: var(--bg-hover); }}

.sim-scenario {{ display: none; }}
.sim-scenario.active {{ display: block; }}
.sim-flow {{ background: var(--bg-card); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 14px; color: var(--text-1); box-shadow: 0 1px 3px var(--shadow); border-left: 3px solid var(--primary); }}
.sim-cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
.sim-card {{ background: var(--bg-card); border-radius: 8px; padding: 14px 16px; box-shadow: 0 1px 3px var(--shadow); }}
.sim-card .k {{ display: block; font-size: 12px; color: var(--text-3); margin-bottom: 4px; }}
.sim-card .v {{ display: block; font-size: 16px; font-weight: 600; }}
.sim-card .sub {{ font-size: 11px; color: var(--text-3); font-weight: 400; margin-top: 2px; }}
.sim-table-wrap {{ overflow-x: auto; background: var(--bg-card); border-radius: 8px; box-shadow: 0 1px 3px var(--shadow); padding: 8px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: var(--bg-hover); padding: 10px 12px; text-align: left; font-weight: 600; color: var(--text-2); white-space: nowrap; border-bottom: 1px solid var(--border); }}
td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }}
tr:nth-child(even) td {{ background: var(--bg-hover); }}
tr:hover td {{ background: var(--bg-hover); }}

/* 交易记录操作标签（涨红/辅买紫/卖出绿为数据语义色，保持硬编码）*/
.ledger-op {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; color: #fff; }}
.ledger-op.buy {{ background: #e6492e; }}
.ledger-op.buy_aux {{ background: #d63384; }}
.ledger-op.sell {{ background: #2e8b57; }}

.footer {{ margin-top: 24px; font-size: 12px; color: var(--text-3); }}
.footer a {{ color: var(--primary); }}

/* 移动端适配（iframe 在 H5 浮层窄屏打开时）：边距缩、卡片 2 列、tab 横滚、表格紧凑 */
@media (max-width: 768px) {{
  body {{ padding: 12px; max-width: 100%; }}
  h1 {{ font-size: 17px; }}
  .subtitle {{ font-size: 12px; margin-bottom: 12px; }}
  .sim-cmp-table, .sim-table-wrap {{ padding: 6px; margin-bottom: 12px; }}
  .sim-cmp-table table {{ font-size: 11px; }}
  .sim-main-tabs {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  .sim-main-tab {{ padding: 8px 14px; font-size: 13px; white-space: nowrap; flex-shrink: 0; }}
  .sim-sub-tabs {{ overflow-x: auto; -webkit-overflow-scrolling: touch; padding: 8px 0 10px; }}
  .sim-sub-tab {{ padding: 5px 12px; font-size: 12px; white-space: nowrap; flex-shrink: 0; }}
  .sim-cards {{ grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 16px; }}
  .sim-card {{ padding: 10px 12px; }}
  .sim-card .v {{ font-size: 15px; }}
  .sim-flow {{ padding: 10px 12px; font-size: 13px; margin-bottom: 12px; }}
  table {{ font-size: 12px; }}
  th, td {{ padding: 6px 8px; }}
  .footer {{ font-size: 11px; margin-top: 16px; }}
}}
</style>
<script>
// 主题跟随父页面：URL hash 优先(iframe 传入) + localStorage + 首次默认redgold + postMessage 动态切换
(function(){{
  var t = '';
  var h = location.hash.replace(/^#/,'');
  try {{ h = decodeURIComponent(h); }} catch(e) {{}}
  if (h) t = h;
  else {{
    try {{
      var v = localStorage.getItem('trade-theme');
      t = (v === null) ? 'redgold' : (v || '');
    }} catch(e) {{ t = 'redgold'; }}
  }}
  if (t) document.documentElement.setAttribute('data-theme', t);
  window.addEventListener('message', function(e){{
    if (e.data && e.data.type === 'set-theme'){{
      if (e.data.theme) document.documentElement.setAttribute('data-theme', e.data.theme);
      else document.documentElement.removeAttribute('data-theme');
    }}
  }});
}})();
</script>
</head>
<body>
<h1>{index_name} · 买卖点模拟回测</h1>
<p class="subtitle">总资金 10 万 · 按信号当日收盘价成交{backtest_info} · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
{comparison_table}
<div class="sim-main-tabs">{main_tabs}</div>
{groups_html}
<div class="footer">
  <p><a href="./">← 返回看板</a></p>
  <details style="margin-top: 12px; font-size: 12px; color: var(--text-3);">
    <summary style="cursor: pointer; margin-bottom: 8px;">📖 模拟说明</summary>
    <p>模拟说明：三种策略路径 × 三种信号组合，共 9 个场景。总资金 10 万元。买固定 1 万 + 卖清仓全部；全仓进出（一次一笔，买全部现金，卖清仓）；固定 1 万进出（FIFO，最多同时 10 笔）。主买=红色，辅买=紫色，卖出=绿色。连续同向信号跳过（避免重复操作）。此为历史模拟，非未来收益保证。</p>
  </details>
</div>
<script>
(function() {{
  let currentPath = 0, currentSig = 0;

  function show() {{
    document.querySelectorAll('.sim-main-tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sim-path-group').forEach(g => g.classList.remove('active'));
    document.querySelectorAll('.sim-sub-tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sim-scenario').forEach(s => s.classList.remove('active'));
    document.querySelector('.sim-main-tab[data-path="' + currentPath + '"]').classList.add('active');
    document.querySelector('.sim-path-group[data-path="' + currentPath + '"]').classList.add('active');
    document.querySelector('.sim-sub-tab[data-path="' + currentPath + '"][data-sig="' + currentSig + '"]').classList.add('active');
    document.querySelector('.sim-scenario[data-path="' + currentPath + '"][data-sig="' + currentSig + '"]').classList.add('active');
  }}

  document.querySelectorAll('.sim-main-tab').forEach(btn => {{
    btn.onclick = () => {{
      currentPath = parseInt(btn.dataset.path);
      currentSig = 0;
      show();
    }};
  }});

  document.querySelectorAll('.sim-sub-tab').forEach(btn => {{
    btn.onclick = () => {{
      currentPath = parseInt(btn.dataset.path);
      currentSig = parseInt(btn.dataset.sig);
      show();
    }};
  }});
}})();
</script>
<script>
(function(){{
    var bp = document.createElement('script');
    var curProtocol = window.location.protocol.split(':')[0];
    if (curProtocol === 'https'){{
        bp.src = 'https://zz.bdstatic.com/linksubmit/push.js';
    }} else {{
        bp.src = 'http://push.zhanzhang.baidu.com/push.js';
    }}
    var s = document.getElementsByTagName("script")[0];
    s.parentNode.insertBefore(bp, s);
}})();
</script>
</body>
</html>"""


def _generate_one(index_id, name_map, out_dir_static, output=None):
    """生成单个品种的回测 HTML。

    output 非 None 时只写该路径；否则写 static-site/ 一份。
    返回 True 成功；无数据（signals 为空或 last 为 None）时返回 False 不写文件。
    """
    index_name = name_map.get(index_id, index_id)
    signals, last = get_signals(index_id)
    if not signals or last is None:
        return False
    last_date, last_close = last

    SIG_LABELS = ["主买+卖", "辅买+卖", "主买+辅买+卖"]
    SIG_TYPES = [{"buy"}, {"buy_aux"}, {"buy", "buy_aux"}]

    groups = {}

    groups["买固定1万+卖清仓"] = {}
    for label, btypes in zip(SIG_LABELS, SIG_TYPES):
        groups["买固定1万+卖清仓"][label] = simulate_sell_all(label, signals, btypes, last_date, last_close)

    groups["全仓进出"] = {}
    for label, btypes in zip(SIG_LABELS, SIG_TYPES):
        groups["全仓进出"][label] = simulate_all_in(label, signals, btypes, last_date, last_close)

    groups["固定1万进出（FIFO）"] = {}
    for label, btypes in zip(SIG_LABELS, SIG_TYPES):
        groups["固定1万进出（FIFO）"][label] = simulate_fixed_1w(label, signals, btypes, last_date, last_close)

    signal_first_date = signals[0][0] if signals else None
    signal_last_date = signals[-1][0] if signals else None
    html = build_html(groups, index_id, index_name, signal_first_date, signal_last_date)

    if output:
        outputs = [output]
    else:
        outputs = [
            os.path.join(out_dir_static, f"trade_sim_{index_id}.html"),
        ]
    for out in outputs:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
    return True


def main():
    parser = argparse.ArgumentParser(description="买卖点模拟回测")
    parser.add_argument("--index", help="品种 index_id（默认 sh）")
    parser.add_argument("--all", action="store_true", help="批量生成所有品种（写 static-site）")
    parser.add_argument("--output", help="自定义输出路径（仅单品种，只写该路径）")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(__file__))
    out_dir_static = os.path.join(base_dir, "static-site")
    name_map = load_name_map()

    if args.all:
        ids = list(name_map.keys())
        ok = 0; skip = 0; fail = 0
        for index_id in ids:
            try:
                if _generate_one(index_id, name_map, out_dir_static):
                    ok += 1
                else:
                    skip += 1
                    print(f"SKIP（无数据）: {index_id}", file=sys.stderr)
            except Exception as e:
                fail += 1
                print(f"FAIL: {index_id} - {e}", file=sys.stderr)
        print(f"完成: 成功 {ok} / 跳过 {skip} / 失败 {fail} / 共 {len(ids)}")
        return

    index_id = args.index or "sh"
    index_name = name_map.get(index_id, index_id)
    if _generate_one(index_id, name_map, out_dir_static, output=args.output):
        target = args.output if args.output else "static-site"
        print(f"Generated: {index_name} -> {target}")
    else:
        print(f"无数据: {index_id}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()