#!/usr/bin/env python3
"""上证指数买卖点模拟回测 — 生成静态 HTML 报告。

三种推演路径：
  路径 A：固定 1 万进出（FIFO）— 每次买 1 万，卖 FIFO 卖最早一笔，最多同时 10 笔
  路径 B：全仓进出 — 一次只持有一笔，买用全部现金，卖清仓
  路径 C：买固定 1 万 + 卖清仓 — 每次买 1 万，卖点清仓全部

每种路径 x 三种信号场景：
  1. 主买+卖：仅 buy (C1 主买) + sell
  2. 辅买+卖：仅 buy_aux (B1 辅买) + sell
  3. 主买+辅买+卖：buy + buy_aux + sell 全部

用法：python scripts/simulate_trade.py [--output static-site/trade_sim.html]
"""

import sqlite3
import os
import sys
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sentiment.db")
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static-site", "trade_sim.html")

TOTAL_CAPITAL = 100_000   # 总资金池
POSITION_SIZE = 10_000    # 每次固定操作金额（路径 A / C）
MAX_POSITIONS = 10        # 最多同时持仓 10 笔


def get_signals(index_id="sh"):
    conn = sqlite3.connect(DB)
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


def _ledger(date, op, amount, cash, positions, close):
    """构建一条交易记录。"""
    holdings_cost = sum(POSITION_SIZE for _ in positions) if positions else 0.0
    hv = sum(s * close for _, _, s in positions) if positions else 0.0
    total = cash + hv
    return {
        "date": str(date),
        "op": op,
        "amount": round(amount, 2),
        "holdings_cost": round(holdings_cost, 2),
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

    rounds = []
    ledger = []
    buy_count = 0
    sell_count = 0
    skipped_full = 0
    skipped_no_cash = 0
    skipped_no_position = 0
    max_positions_ever = 0
    first_buy_date = None

    for date, sig, _, close in signals:
        is_buy = sig in buy_types
        is_sell = sig == "sell"

        if is_buy and cash >= POSITION_SIZE and len(positions) < MAX_POSITIONS:
            if first_buy_date is None:
                first_buy_date = date
            buy_count += 1
            shares = POSITION_SIZE / close
            positions.append((date, close, shares))
            cash -= POSITION_SIZE
            hv = sum(s * close for _, _, s in positions)
            if hv > max_holding:
                max_holding = hv
                max_holding_date = date
            ledger.append(_ledger(date, "买入", POSITION_SIZE, cash, positions, close))

        elif is_buy and len(positions) >= MAX_POSITIONS:
            skipped_full += 1
        elif is_buy and cash < POSITION_SIZE:
            skipped_no_cash += 1
        elif is_sell and positions:
            sell_count += 1
            buy_date, buy_close, shares = positions.pop(0)
            sell_amount = shares * close
            cash += sell_amount
            pct = (close - buy_close) / buy_close * 100
            profit = sell_amount - POSITION_SIZE
            rounds.append({
                "buy_date": str(buy_date), "buy_close": round(buy_close, 2),
                "sell_date": str(date), "sell_close": round(close, 2),
                "hold_days": _days_between(buy_date, date),
                "pct": round(pct, 2), "amount_in": POSITION_SIZE,
                "amount_out": round(sell_amount, 2), "profit": round(profit, 2),
            })
            ledger.append(_ledger(date, "卖出", sell_amount, cash, positions, close))

        elif is_sell and not positions:
            skipped_no_position += 1

        if len(positions) > max_positions_ever:
            max_positions_ever = len(positions)
        hv = sum(s * close for _, _, s in positions)
        total = cash + hv
        if total > total_assets_peak:
            total_assets_peak = total
            total_assets_peak_date = date

    holdings_value = sum(s * last_close for _, _, s in positions)
    final_total = cash + holdings_value

    return _build_result(
        scenario_name, cash, positions, rounds, ledger, last_close,
        first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
        max_holding, max_holding_date, buy_count, sell_count,
        skipped_full, skipped_no_cash, skipped_no_position, max_positions_ever,
        strategy_desc="固定 1 万进出（FIFO）",
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

    rounds = []
    ledger = []
    buy_count = 0
    sell_count = 0
    skipped_consecutive_buy = 0
    skipped_consecutive_sell = 0
    skipped_no_holding = 0
    first_buy_date = None
    last_signal = None

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
            last_signal = "buy"
            # 全仓买入的 ledger：持仓成本 = buy_amount
            entry = _ledger(date, "买入", buy_amount, 0.0, [(date, close, shares)], close)
            entry["holdings_cost"] = round(buy_amount, 2)
            ledger.append(entry)

        elif is_sell and holding is not None:
            if last_signal == "sell":
                skipped_consecutive_sell += 1
                continue
            sell_count += 1
            buy_date, buy_close, shares = holding
            sell_amount = shares * close
            cash = sell_amount
            pct = (close - buy_close) / buy_close * 100
            profit = sell_amount - (shares * buy_close)
            amount_in = round(shares * buy_close, 2)
            rounds.append({
                "buy_date": str(buy_date), "buy_close": round(buy_close, 2),
                "sell_date": str(date), "sell_close": round(close, 2),
                "hold_days": _days_between(buy_date, date),
                "pct": round(pct, 2), "amount_in": amount_in,
                "amount_out": round(sell_amount, 2), "profit": round(profit, 2),
            })
            holding = None
            last_signal = "sell"
            ledger.append(_ledger(date, "卖出", sell_amount, cash, [], close))

        elif is_sell and holding is None:
            skipped_no_holding += 1

        # 更新峰值
        hv = holding[2] * close if holding else 0.0
        total = cash + hv
        if total > total_assets_peak:
            total_assets_peak = total
            total_assets_peak_date = date

    holdings_value = holding[2] * last_close if holding else 0.0
    final_total = cash + holdings_value
    positions = [holding] if holding else []

    return _build_result(
        scenario_name, cash, positions, rounds, ledger, last_close,
        first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
        max_holding, max_holding_date, buy_count, sell_count,
        skipped_consecutive_buy, 0, skipped_no_holding, 1 if holding else 0,
        strategy_desc="全仓进出（一次一笔，买全部现金，卖清仓）",
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

    for date, sig, _, close in signals:
        is_buy = sig in buy_types
        is_sell = sig == "sell"

        if is_buy and cash >= POSITION_SIZE and len(positions) < MAX_POSITIONS:
            if first_buy_date is None:
                first_buy_date = date
            buy_count += 1
            shares = POSITION_SIZE / close
            positions.append((date, close, shares))
            cash -= POSITION_SIZE
            hv = sum(s * close for _, _, s in positions)
            if hv > max_holding:
                max_holding = hv
                max_holding_date = date
            last_signal = "buy"
            ledger.append(_ledger(date, "买入", POSITION_SIZE, cash, positions, close))

        elif is_buy and len(positions) >= MAX_POSITIONS:
            skipped_full += 1
        elif is_buy and cash < POSITION_SIZE:
            skipped_no_cash += 1
        elif is_sell and positions:
            if last_signal == "sell":
                continue
            sell_count += 1
            # 清仓全部
            sold = []
            total_amount_in = 0.0
            total_amount_out = 0.0
            total_profit = 0.0
            while positions:
                buy_date, buy_close, shares = positions.pop(0)
                sell_amount = shares * close
                cash += sell_amount
                total_amount_in += POSITION_SIZE
                total_amount_out += sell_amount
                total_profit += sell_amount - POSITION_SIZE
                sold.append({
                    "buy_date": str(buy_date), "buy_close": round(buy_close, 2),
                    "sell_date": str(date), "sell_close": round(close, 2),
                    "hold_days": _days_between(buy_date, date),
                    "pct": round((close - buy_close) / buy_close * 100, 2),
                    "amount_in": POSITION_SIZE,
                    "amount_out": round(sell_amount, 2),
                    "profit": round(sell_amount - POSITION_SIZE, 2),
                })
            rounds.append({
                "buy_date": sold[0]["buy_date"] if len(sold) == 1 else f"{sold[0]['buy_date']}~{sold[-1]['buy_date']}",
                "buy_close": round(sum(s["buy_close"] for s in sold) / len(sold), 2),
                "sell_date": str(date),
                "sell_close": round(close, 2),
                "hold_days": sum(s["hold_days"] for s in sold),
                "pct": round(total_profit / total_amount_in * 100, 2) if total_amount_in else 0,
                "amount_in": round(total_amount_in, 2),
                "amount_out": round(total_amount_out, 2),
                "profit": round(total_profit, 2),
                "_sub_rounds": sold,
            })
            last_signal = "sell"
            ledger.append(_ledger(date, "清仓卖出", total_amount_out, cash, [], close))

        elif is_sell and not positions:
            skipped_no_position += 1

        if len(positions) > max_positions_ever:
            max_positions_ever = len(positions)
        hv = sum(s * close for _, _, s in positions)
        total = cash + hv
        if total > total_assets_peak:
            total_assets_peak = total
            total_assets_peak_date = date

    holdings_value = sum(s * last_close for _, _, s in positions)
    final_total = cash + holdings_value

    return _build_result(
        scenario_name, cash, positions, rounds, ledger, last_close,
        first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
        max_holding, max_holding_date, buy_count, sell_count,
        skipped_full, skipped_no_cash, skipped_no_position, max_positions_ever,
        strategy_desc="买固定 1 万 + 卖清仓全部",
    )


# ============================================================
#  公共：构建结果 & 计算统计
# ============================================================
def _build_result(scenario_name, cash, positions, rounds, ledger, last_close,
                  first_buy_date, last_date, total_assets_peak, total_assets_peak_date,
                  max_holding, max_holding_date, buy_count, sell_count,
                  skip1, skip2, skip3, max_positions_ever, strategy_desc=""):
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
            "buy_date": str(buy_date), "buy_close": round(buy_close, 2),
            "shares": round(shares, 4),
            "current_value": round(shares * last_close, 2),
            "pct": round((last_close - buy_close) / buy_close * 100, 2),
            "profit": round(shares * last_close - POSITION_SIZE, 2),
        })

    # 流水描述
    flow_parts = [f"总资金 {TOTAL_CAPITAL:,} 元"]
    flow_parts.append(strategy_desc)
    if first_buy_date:
        flow_parts.append(f"{first_buy_date} 首笔买入")
    skip_parts = []
    if skip1:
        skip_parts.append(f"{skip1} 次跳过")
    if skip2:
        skip_parts.append(f"{skip2} 次跳过")
    if skip3:
        skip_parts.append(f"{skip3} 次跳过")
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
            "total_assets_peak_date": str(total_assets_peak_date) if total_assets_peak_date else "N/A",
            "max_holding": round(max_holding, 2),
            "max_holding_date": str(max_holding_date) if max_holding_date else "N/A",
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
            "flow_desc": flow_desc,
        },
    }


def _days_between(d1, d2):
    dt1 = datetime(int(d1[:4]), int(d1[4:6]), int(d1[6:8]))
    dt2 = datetime(int(d2[:4]), int(d2[4:6]), int(d2[6:8]))
    return (dt2 - dt1).days


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
def _scenario_panel(data):
    """构建单个场景的内容面板（卡片 → 交易记录清单 → 未平仓 → 回合表）。"""
    s = data["summary"]

    # --- 交易记录清单（时间轴） ---
    ledger_rows = ""
    for j, entry in enumerate(data.get("ledger", [])):
        op_class = "buy" if "买" in entry["op"] and "卖" not in entry["op"] else "sell"
        op_badge = f'<span class="ledger-op {op_class}">{entry["op"]}</span>'
        pct_str = f'{entry["return_pct"]:+.2f}%'
        pct_color = color_for_pct(entry["return_pct"])
        ledger_rows += f"""
        <tr>
          <td>{j + 1}</td>
          <td>{entry['date']}</td>
          <td>{op_badge}</td>
          <td>{format_num(entry['amount'])}</td>
          <td>{format_num(entry['holdings_cost'])}</td>
          <td>{format_num(entry['total_assets'])}</td>
          <td style="color:{pct_color};font-weight:600">{pct_str}</td>
        </tr>"""

    ledger_html = f"""
    <h3 style="margin: 20px 0 10px; font-size: 15px;">📒 交易记录清单（{s['ledger_count']} 笔，按时间轴）</h3>
    <div class="sim-table-wrap">
      <table>
        <thead><tr>
          <th>#</th><th>日期</th><th>操作</th><th>交易金额</th><th>当前持仓成本</th><th>当前总资产</th><th>累计收益率</th>
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
    cards = f"""
    <div class="sim-flow">{s['flow_desc']}</div>
    <div class="sim-cards">
      <div class="sim-card"><span class="k">总资产变化</span><span class="v">{format_num(s['total_capital'])} → {format_num(s['final_total'])} 元</span></div>
      <div class="sim-card"><span class="k">总收益</span><span class="v" style="color:{color_for_pct(s['total_return'])}">{format_num(s['total_return'])} 元（{s['total_return_pct']:+.2f}%）</span></div>
      <div class="sim-card"><span class="k">年化收益率</span><span class="v" style="color:{color_for_pct(s['annualized'])}">{s['annualized']:+.1f}%<div class="sub">首笔买入至今 {s['years']} 年</div></span></div>
      <div class="sim-card"><span class="k">总资产峰值</span><span class="v">{format_num(s['total_assets_peak'])} 元<div class="sub">{s['total_assets_peak_date']}</div></span></div>
      <div class="sim-card"><span class="k">最大持仓市值</span><span class="v">{format_num(s['max_holding'])} 元<div class="sub">{s['max_holding_date']}</div></span></div>
      <div class="sim-card"><span class="k">总操作</span><span class="v">{s['total_ops']} 次（{s['buy_count']}买/{s['sell_count']}卖 · {s['total_rounds']}回合 · {s['open_count']}笔未平仓）<div class="sub">跳过 {s['skipped_full'] + s['skipped_no_cash'] + s['skipped_no_position']} 次 · 峰值并发 {s['max_positions_ever']} 笔</div></span></div>
      <div class="sim-card"><span class="k">胜率</span><span class="v">{s['win_rate']}%（{s['win_count']}胜/{s['lose_count']}负）</span></div>
      <div class="sim-card"><span class="k">平均盈亏比</span><span class="v">{format_num(s['avg_pl_ratio'])}（均盈{format_num(s['avg_win_pct'])}% / 均亏{format_num(s['avg_loss_pct'])}%）</span></div>
    </div>"""

    # --- 已完成回合表 ---
    rows = ""
    for j, r in enumerate(data["rounds"]):
        sub_rows = ""
        if "_sub_rounds" in r and len(r["_sub_rounds"]) > 1:
            for sr in r["_sub_rounds"]:
                sub_rows += f"""
            <tr style="background:#fafbfc;font-size:11px;color:#646a73">
              <td colspan="2" style="padding-left:24px">└ {sr['buy_date']}</td>
              <td>{sr['buy_close']}</td>
              <td colspan="2"></td>
              <td>{sr['hold_days']} 天</td>
              <td style="color:{color_for_pct(sr['pct'])}">{sr['pct']:+.2f}%</td>
              <td>{format_num(sr['amount_in'])}</td>
              <td>{format_num(sr['amount_out'])}</td>
              <td style="color:{color_for_pct(sr['profit'])}">{sr['profit']:+.2f}</td>
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

    return cards + ledger_html + open_html + table


def build_html(groups):
    """构建两级 Tab 页面。"""
    path_labels = list(groups.keys())
    sig_labels = list(next(iter(groups.values())).keys())

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
            panel = _scenario_panel(data)
            sub_panels += f'<div class="sim-scenario {active_sub}" data-path="{pi}" data-sig="{si}">{panel}</div>\n'

        groups_html += f"""
        <div class="sim-path-group {active_grp}" data-path="{pi}">
          <div class="sim-sub-tabs">{sub_tabs}</div>
          {sub_panels}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>上证指数 · 买卖点模拟回测</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f6f8; color: #1f2329; padding: 24px; max-width: 1200px; margin: 0 auto; }}
h1 {{ font-size: 20px; margin-bottom: 4px; }}
.subtitle {{ color: #8f959e; font-size: 13px; margin-bottom: 20px; }}

.sim-main-tabs {{ display: flex; gap: 0; margin-bottom: 0; border-bottom: 2px solid #e5e6eb; }}
.sim-main-tab {{ padding: 10px 20px; border: none; background: none; cursor: pointer; font-size: 14px; color: #646a73; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all .2s; }}
.sim-main-tab.active {{ color: #1f2329; font-weight: 600; border-bottom-color: #3370ff; }}
.sim-main-tab:hover {{ color: #1f2329; }}

.sim-path-group {{ display: none; }}
.sim-path-group.active {{ display: block; }}

.sim-sub-tabs {{ display: flex; gap: 4px; padding: 10px 0 12px; background: #fff; border-bottom: 1px solid #e5e6eb; margin-bottom: 16px; }}
.sim-sub-tab {{ padding: 6px 14px; border: 1px solid #d9dce0; background: #fff; border-radius: 6px; cursor: pointer; font-size: 13px; color: #4e5969; transition: all .2s; }}
.sim-sub-tab.active {{ background: #165dff; color: #fff; border-color: #165dff; }}
.sim-sub-tab:hover:not(.active) {{ background: #f2f3f5; }}

.sim-scenario {{ display: none; }}
.sim-scenario.active {{ display: block; }}
.sim-flow {{ background: #fff; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 14px; color: #1f2329; box-shadow: 0 1px 3px rgba(0,0,0,.06); border-left: 3px solid #3370ff; }}
.sim-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.sim-card {{ background: #fff; border-radius: 8px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.sim-card .k {{ display: block; font-size: 12px; color: #8f959e; margin-bottom: 4px; }}
.sim-card .v {{ display: block; font-size: 16px; font-weight: 600; }}
.sim-card .sub {{ font-size: 11px; color: #8f959e; font-weight: 400; margin-top: 2px; }}
.sim-table-wrap {{ overflow-x: auto; background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); padding: 8px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #f5f6f8; padding: 10px 12px; text-align: left; font-weight: 600; color: #646a73; white-space: nowrap; border-bottom: 1px solid #e5e6eb; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #f2f3f5; white-space: nowrap; }}
tr:hover td {{ background: #f5f6f8; }}

/* 交易记录操作标签 */
.ledger-op {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; color: #fff; }}
.ledger-op.buy {{ background: #e6492e; }}
.ledger-op.sell {{ background: #2e8b57; }}

.footer {{ margin-top: 24px; font-size: 12px; color: #8f959e; }}
.footer a {{ color: #3370ff; }}
</style>
</head>
<body>
<h1>上证指数 · 买卖点模拟回测</h1>
<p class="subtitle">总资金 10 万 · 按信号当日收盘价成交 · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
<div class="sim-main-tabs">{main_tabs}</div>
{groups_html}
<div class="footer">
  <p>模拟说明：三种策略路径 × 三种信号组合，共 9 个场景。总资金 10 万元。固定 1 万进出（FIFO，最多同时 10 笔）；全仓进出（一次一笔，买全部现金，卖清仓）；买固定 1 万 + 卖清仓全部。连续同向信号跳过（避免重复操作）。此为历史模拟，非未来收益保证。</p>
  <p><a href="./">← 返回看板</a></p>
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
</body>
</html>"""


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else OUTPUT
    signals, (last_date, last_close) = get_signals("sh")

    SIG_LABELS = ["主买+卖", "辅买+卖", "主买+辅买+卖"]
    SIG_TYPES = [{"buy"}, {"buy_aux"}, {"buy", "buy_aux"}]

    groups = {}

    groups["固定1万进出（FIFO）"] = {}
    for label, btypes in zip(SIG_LABELS, SIG_TYPES):
        groups["固定1万进出（FIFO）"][label] = simulate_fixed_1w(label, signals, btypes, last_date, last_close)

    groups["全仓进出"] = {}
    for label, btypes in zip(SIG_LABELS, SIG_TYPES):
        groups["全仓进出"][label] = simulate_all_in(label, signals, btypes, last_date, last_close)

    groups["买固定1万+卖清仓"] = {}
    for label, btypes in zip(SIG_LABELS, SIG_TYPES):
        groups["买固定1万+卖清仓"][label] = simulate_sell_all(label, signals, btypes, last_date, last_close)

    html = build_html(groups)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {output} ({len(html)} bytes)")

    web_output = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "trade_sim.html")
    with open(web_output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Copied to: {web_output}")

    for path_label, sig_map in groups.items():
        for sig_label, data in sig_map.items():
            s = data["summary"]
            print(f"\n{'='*50}")
            print(f"  [{path_label}] {sig_label}")
            print(f"  总资产 {s['total_capital']:,} → {s['final_total']:,.0f}（+{s['total_return_pct']:.2f}%）")
            print(f"  总收益 {s['total_return']:,.0f} | 年化 {s['annualized']:.1f}%（{s['years']} 年）")
            print(f"  总资产峰值 {s['total_assets_peak']:,.0f}（{s['total_assets_peak_date']}）")
            print(f"  最大持仓 {s['max_holding']:,.0f}（{s['max_holding_date']}）")
            print(f"  {s['buy_count']}买/{s['sell_count']}卖 | {s['total_rounds']}回合 | {s['open_count']}笔未平仓 | 峰值并发{s['max_positions_ever']}笔")
            print(f"  交易记录 {s['ledger_count']} 笔")
            print(f"  胜率{s['win_rate']}% | 均盈{s['avg_win_pct']}% / 均亏{s['avg_loss_pct']}% | 盈亏比{s['avg_pl_ratio']}")


if __name__ == "__main__":
    main()