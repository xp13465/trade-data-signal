#!/usr/bin/env python3
"""上证指数买卖点模拟回测 — 生成静态 HTML 报告。

三种场景：
  1. 主买+卖：仅 buy (C1 主买) + sell
  2. 辅买+卖：仅 buy_aux (B1 辅买) + sell
  3. 主买+辅买+卖：buy + buy_aux + sell 全部

交易逻辑：配对模式，全仓进出。
  - 起始资金 10,000 元
  - 买点触发：全仓买入（按当日 close 价）
  - 卖点触发：全部卖出
  - 连续同向信号跳过（已持仓/已空仓）
  - 末尾未平仓买入按最后交易日 close 估价

用法：python scripts/simulate_trade.py [--output static-site/trade_sim.html]
"""

import sqlite3
import json
import os
import sys
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sentiment.db")
OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static-site", "trade_sim.html")


def get_signals(index_id="sh"):
    """获取某指数的信号 + close 价格，按日期排序。"""
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """SELECT s.date, s.signal, s.reason, d.close
           FROM signal_daily s
           JOIN index_daily d ON d.index_id = s.index_id AND d.date = s.date
           WHERE s.index_id = ?
           ORDER BY s.date""",
        (index_id,),
    ).fetchall()
    # 获取最后交易日 close（用于估值未平仓）
    last = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? ORDER BY date DESC LIMIT 1",
        (index_id,),
    ).fetchone()
    conn.close()
    return rows, last


def simulate(scenario_name, signals, buy_types, last_date, last_close):
    """
    模拟交易。

    buy_types: set of signal types to treat as buy (e.g. {'buy'}, {'buy_aux'}, {'buy','buy_aux'})
    返回 {
        'rounds': [{buy_date, buy_close, sell_date, sell_close, hold_days, pct, amount_in, amount_out, profit}],
        'summary': {total_invested, total_return, total_return_pct, max_holding, max_holding_date,
                    min_cash, min_cash_date, buy_count, sell_count, win_count, lose_count,
                    win_rate, avg_win_pct, avg_loss_pct, final_cash, final_status}
    }
    """
    INITIAL = 10000.0
    cash = INITIAL
    holdings_cost = 0.0      # 持仓成本（买入金额）
    buy_price = 0.0          # 买入时的 close
    buy_date = None
    total_invested = 0.0     # 累计投入（所有买入金额之和）
    max_holding = 0.0        # 最大持仓金额
    max_holding_date = None
    min_holding = float("inf")  # 最少持仓金额（0=空仓，或最低持仓值）
    min_holding_date = None

    rounds = []
    buy_count = 0
    sell_count = 0

    for date, sig, reason, close in signals:
        is_buy = sig in buy_types
        is_sell = sig == "sell"

        if is_buy and cash > 0:
            # 买入
            buy_count += 1
            buy_price = close
            buy_date = date
            holdings_cost = cash
            total_invested += cash
            cash = 0.0
            if holdings_cost > max_holding:
                max_holding = holdings_cost
                max_holding_date = date
            if holdings_cost < min_holding:
                min_holding = holdings_cost
                min_holding_date = date

        elif is_sell and holdings_cost > 0:
            # 卖出
            sell_count += 1
            sell_amount = holdings_cost * (close / buy_price)
            pct = (close - buy_price) / buy_price * 100
            profit = sell_amount - holdings_cost
            cash = sell_amount
            # 卖出后持仓=0，记录空仓状态
            if 0 < min_holding:
                min_holding = 0.0
                min_holding_date = date

            hold_days = _days_between(buy_date, date)
            rounds.append({
                "buy_date": str(buy_date),
                "buy_close": round(buy_price, 2),
                "sell_date": str(date),
                "sell_close": round(close, 2),
                "hold_days": hold_days,
                "pct": round(pct, 2),
                "amount_in": round(holdings_cost, 2),
                "amount_out": round(sell_amount, 2),
                "profit": round(profit, 2),
            })
            holdings_cost = 0.0
            buy_price = 0.0
            buy_date = None

    # 末尾未平仓：按最后交易日 close 估值
    final_status = "空仓"
    if holdings_cost > 0:
        final_value = holdings_cost * (last_close / buy_price)
        final_status = f"持仓（按{last_date}收盘{last_close:.2f}估值{final_value:.0f}元）"
        cash = final_value
        # 把未平仓买入也记录为一轮（无卖出）
        rounds.append({
            "buy_date": str(buy_date),
            "buy_close": round(buy_price, 2),
            "sell_date": f"{last_date}(估值)",
            "sell_close": round(last_close, 2),
            "hold_days": _days_between(buy_date, last_date),
            "pct": round((last_close - buy_price) / buy_price * 100, 2),
            "amount_in": round(holdings_cost, 2),
            "amount_out": round(final_value, 2),
            "profit": round(final_value - holdings_cost, 2),
        })

    total_return = cash - INITIAL
    total_return_pct = total_return / INITIAL * 100

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
        "summary": {
            "scenario": scenario_name,
            "initial": INITIAL,
            "total_invested": round(total_invested, 2),
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "final_cash": round(cash, 2),
            "max_holding": round(max_holding, 2),
            "max_holding_date": str(max_holding_date) if max_holding_date else "N/A",
            "min_holding": round(min_holding, 2) if min_holding != float("inf") else 0.0,
            "min_holding_date": str(min_holding_date) if min_holding_date else "N/A",
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_rounds": len(rounds),
            "win_count": win_count,
            "lose_count": lose_count,
            "win_rate": round(win_rate, 1),
            "avg_win_pct": round(avg_win_pct, 2),
            "avg_loss_pct": round(avg_loss_pct, 2),
            "avg_pl_ratio": round(avg_pl_ratio, 2),
            "final_status": final_status,
        },
    }


def _days_between(d1, d2):
    """计算两个日期字符串之间的日历天数。"""
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


def build_html(scenarios):
    """构建完整静态 HTML 页面。"""
    tabs_html = ""
    content_html = ""
    for i, (name, data) in enumerate(scenarios.items()):
        s = data["summary"]
        active = "active" if i == 0 else ""
        tabs_html += f'<button class="sim-tab {active}" data-tab="{i}">{name}</button>\n'
        # 摘要卡片
        cards = f"""
        <div class="sim-cards">
          <div class="sim-card"><span class="k">初始资金</span><span class="v">{format_num(s['initial'])} 元</span></div>
          <div class="sim-card"><span class="k">总投入</span><span class="v">{format_num(s['total_invested'])} 元</span></div>
          <div class="sim-card"><span class="k">最终资金</span><span class="v">{format_num(s['final_cash'])} 元</span></div>
          <div class="sim-card"><span class="k">总收益</span><span class="v" style="color:{color_for_pct(s['total_return'])}">{format_num(s['total_return'])} 元（{s['total_return_pct']:+.2f}%）</span></div>
          <div class="sim-card"><span class="k">最大持仓</span><span class="v">{format_num(s['max_holding'])} 元<div class="sub">{s['max_holding_date']}</div></span></div>
          <div class="sim-card"><span class="k">最少持仓金额</span><span class="v">{format_num(s['min_holding'])} 元<div class="sub">{s['min_holding_date']}</div></span></div>
          <div class="sim-card"><span class="k">执行买/卖</span><span class="v">{s['buy_count']} 次买 / {s['sell_count']} 次卖（{s['total_rounds']} 回合）</span></div>
          <div class="sim-card"><span class="k">胜率</span><span class="v">{s['win_rate']}%（{s['win_count']}胜/{s['lose_count']}负）</span></div>
          <div class="sim-card"><span class="k">平均盈亏比</span><span class="v">{format_num(s['avg_pl_ratio'])}（均盈{format_num(s['avg_win_pct'])}% / 均亏{format_num(s['avg_loss_pct'])}%）</span></div>
          <div class="sim-card"><span class="k">状态</span><span class="v">{s['final_status']}</span></div>
        </div>"""

        # 详细回合表
        rows = ""
        for j, r in enumerate(data["rounds"]):
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
            </tr>"""

        table = f"""
        <div class="sim-table-wrap">
          <table>
            <thead><tr>
              <th>#</th><th>买入日期</th><th>买入价</th><th>卖出日期</th><th>卖出价</th>
              <th>持有时长</th><th>盈亏%</th><th>投入金额</th><th>回收金额</th><th>净利润</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

        content_html += f'<div class="sim-scenario {"active" if i == 0 else ""}" data-idx="{i}">{cards}{table}</div>\n'

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
.sim-tabs {{ display: flex; gap: 0; margin-bottom: 20px; border-bottom: 2px solid #e5e6eb; }}
.sim-tab {{ padding: 8px 20px; border: none; background: none; cursor: pointer; font-size: 14px; color: #646a73; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all .2s; }}
.sim-tab.active {{ color: #1f2329; font-weight: 600; border-bottom-color: #3370ff; }}
.sim-tab:hover {{ color: #1f2329; }}
.sim-scenario {{ display: none; }}
.sim-scenario.active {{ display: block; }}
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
.footer {{ margin-top: 24px; font-size: 12px; color: #8f959e; }}
.footer a {{ color: #3370ff; }}
</style>
</head>
<body>
<h1>上证指数 · 买卖点模拟回测</h1>
<p class="subtitle">初始资金 10,000 元 · 全仓进出 · 配对模式 · 按信号当日收盘价成交 · 生成于 {datetime.now().strftime("%Y-%m-%d %H:%M")}</p>
<div class="sim-tabs">{tabs_html}</div>
{content_html}
<div class="footer">
  <p>模拟说明：买入=信号日收盘价全仓买入；卖出=信号日收盘价全部卖出。连续同向信号跳过（已持仓/已空仓）。末尾未平仓按最后交易日收盘价估值。此为历史模拟，非未来收益保证。</p>
  <p><a href="./">← 返回看板</a></p>
</div>
<script>
document.querySelectorAll('.sim-tab').forEach(btn => {{
  btn.onclick = () => {{
    document.querySelectorAll('.sim-tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sim-scenario').forEach(s => s.classList.remove('active'));
    btn.classList.add('active');
    document.querySelector('.sim-scenario[data-idx="' + btn.dataset.tab + '"]').classList.add('active');
  }};
}});
</script>
</body>
</html>"""


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else OUTPUT
    signals, (last_date, last_close) = get_signals("sh")

    scenarios = {}
    # 场景1：主买+卖
    scenarios["主买+卖"] = simulate("主买+卖", signals, {"buy"}, last_date, last_close)
    # 场景2：辅买+卖
    scenarios["辅买+卖"] = simulate("辅买+卖", signals, {"buy_aux"}, last_date, last_close)
    # 场景3：主买+辅买+卖
    scenarios["主买+辅买+卖"] = simulate("主买+辅买+卖", signals, {"buy", "buy_aux"}, last_date, last_close)

    html = build_html(scenarios)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {output} ({len(html)} bytes)")
    # 同时复制到 web/ 目录，供动态版（localhost:8000）访问
    web_output = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "trade_sim.html")
    with open(web_output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Copied to: {web_output}")

    # 打印摘要到控制台
    for name, data in scenarios.items():
        s = data["summary"]
        print(f"\n{'='*50}")
        print(f"  {name}")
        print(f"  初始 {s['initial']:,.0f} → 最终 {s['final_cash']:,.0f}（{s['total_return_pct']:+.2f}%）")
        print(f"  总投入 {s['total_invested']:,.0f} | 总收益 {s['total_return']:,.0f}")
        print(f"  最大持仓 {s['max_holding']:,.0f}（{s['max_holding_date']}）")
        print(f"  最少持仓金额 {s['min_holding']:,.0f}（{s['min_holding_date']}）")
        print(f"  {s['buy_count']}买/{s['sell_count']}卖 | {s['total_rounds']}回合 | 胜率{s['win_rate']}%")
        print(f"  均盈{s['avg_win_pct']}% / 均亏{s['avg_loss_pct']}% | 盈亏比{s['avg_pl_ratio']}")
        print(f"  状态: {s['final_status']}")


if __name__ == "__main__":
    main()