#!/usr/bin/env python3
"""策略实验室配对交易模拟回测 -- 生成 lab_simulate.json

穷尽配对：8个买策略 × 8个卖策略 = 64组配对 × 2种交易模式 = 128组回测。

交易模式：
  - full_in（全仓进出）：买信号全仓买入，卖信号全仓卖出，本金复利滚动
  - fixed_10k（1万定额）：每次买信号买入1万元（最多10笔），卖信号清仓全部

输出结构:
  {
    strategies: {
      key: {
        side: "buy"/"sell",
        pairs: {
          paired_key: {
            full_in:   {stats, equity_curve, trades},
            fixed_10k: {stats, equity_curve, trades}
          }
        }
      }
    }
  }

输出: web/data/lab/lab_simulate.json + static-site/data/lab/lab_simulate.json
"""
import json
import os
import sys
import sqlite3
import pandas as pd

A_STOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "a-stock-data")
sys.path.insert(0, A_STOCK_DIR)
from backtest_strategies import gen_buy_signals, gen_sell_signals

BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DB = os.path.join(BASE, "data", "sentiment.db")
INDEX_ID = "sh"
INDEX_NAME = "上证指数"
INITIAL_CAPITAL = 100_000
POSITION_SIZE = 10_000
MAX_POSITIONS = 10
MAX_CURVE_POINTS = 100  # 净值曲线最多保留点数（从200降至100，为trades新增账户快照字段腾体积）
MAX_TRADES_STORED = 40  # 每组交易记录最多存储笔数（从50降至40，前端分页每页20条够2页；stats.n_trades 保留完整笔数）

# 8个买策略（候选7 + 生产1）
BUY_KEYS = [
    'BB_lower_revert', 'Supertrend_buy', 'Donchian20_up', 'Donchian55_up',
    'MA_golden_5_20', 'MA_golden_10_60', 'MACD_golden', 'C1_RSI30',
]
# 8个卖策略（候选7 + 生产1）
SELL_KEYS = [
    'BB_upper_revert', 'MA_death_5_20', 'BB_middle_break', 'Donchian10_down',
    'Donchian20_down', 'MACD_death', 'ATR_trail_stop', 'D1_high20_drop5',
]


def load_index_data(iid):
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close FROM index_daily "
        "WHERE index_id=? ORDER BY date", conn, params=(iid,),
        parse_dates=['date'])
    conn.close()
    if len(df) < 60:
        return None
    df = df.set_index('date').astype(float)
    return df[['open', 'high', 'low', 'close']]


def _fmt_date(dt):
    if isinstance(dt, pd.Timestamp):
        return dt.strftime('%Y-%m-%d')
    return str(dt)[:10]


def _days_between(d1, d2):
    if isinstance(d1, str):
        d1 = pd.Timestamp(d1)
    if isinstance(d2, str):
        d2 = pd.Timestamp(d2)
    return abs((d2 - d1).days)


def sample_curve(curve, max_points=MAX_CURVE_POINTS):
    """均匀采样净值曲线，保留首尾点。"""
    if len(curve) <= max_points:
        return curve
    step = len(curve) / max_points
    indices = sorted(set(int(i * step) for i in range(max_points)))
    if indices[-1] != len(curve) - 1:
        indices.append(len(curve) - 1)
    return [curve[i] for i in indices]


def _build_stats(trades, final_total, last_date, equity_curve):
    """计算统计指标。"""
    total_ret = (final_total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    if trades:
        first_buy_date = pd.Timestamp(trades[0]['buy_date'])
        years = _days_between(first_buy_date, last_date) / 365.25
        if years > 0 and final_total > 0:
            annual_ret = ((final_total / INITIAL_CAPITAL) ** (1 / years) - 1) * 100
        else:
            annual_ret = 0.0
    else:
        years = 0
        annual_ret = 0.0

    win_trades = [t for t in trades if t['ret'] > 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0.0

    # 最大回撤（用 equity_curve 补算）
    vals = [e['value'] for e in equity_curve]
    max_dd = 0.0
    if len(vals) > 1:
        pk = vals[0]
        for v in vals[1:]:
            if v > pk:
                pk = v
            dd = (pk - v) / pk * 100 if pk > 0 else 0
            if dd > max_dd:
                max_dd = dd

    return {
        'total_ret': round(total_ret, 2),
        'annual_ret': round(annual_ret, 1),
        'max_drawdown': round(max_dd, 1),
        'win_rate': round(win_rate, 1),
        'n_trades': len(trades),
        'final_total': round(final_total, 2),
        'years': round(years, 1),
    }


def simulate_full_in(df, buy_mask, sell_mask):
    """全仓进出模式：买信号全仓买入，卖信号全仓卖出。"""
    close = df['close']
    dates = df.index

    events = [(d, 'buy') for d in dates[buy_mask].tolist()] + \
             [(d, 'sell') for d in dates[sell_mask].tolist()]
    events.sort(key=lambda x: x[0])

    cash = float(INITIAL_CAPITAL)
    holding = None  # (buy_date, buy_close, shares)
    trades = []
    equity_curve = [{'date': _fmt_date(dates[0]), 'value': round(cash, 2)}]

    for date, sig_type in events:
        close_val = close.loc[date]

        if sig_type == 'buy' and holding is None:
            shares = cash / close_val
            holding = (date, close_val, shares)
            cash = 0.0

        elif sig_type == 'sell' and holding is not None:
            buy_date, buy_close, shares = holding
            sell_amount = shares * close_val
            ret_pct = (close_val - buy_close) / buy_close * 100
            hold_days = _days_between(buy_date, date)
            cash = sell_amount
            holding = None
            # 卖出后账户快照（全仓模式：全部现金，无持仓）
            account_total = cash
            cum_profit = account_total - INITIAL_CAPITAL
            cum_return = cum_profit / INITIAL_CAPITAL * 100
            trades.append({
                'buy_date': _fmt_date(buy_date),
                'buy_price': round(buy_close, 2),
                'sell_date': _fmt_date(date),
                'sell_price': round(close_val, 2),
                'ret': round(ret_pct, 2),
                'hold_days': hold_days,
                'account_total': round(account_total, 2),
                'cumulative_profit': round(cum_profit, 2),
                'cumulative_return': round(cum_return, 2),
            })
            equity_curve.append({'date': _fmt_date(date), 'value': round(cash, 2)})

    # 期末估值
    last_date = dates[-1]
    last_close = close.iloc[-1]
    if holding is not None:
        final_total = cash + holding[2] * last_close
        equity_curve.append({'date': _fmt_date(last_date), 'value': round(final_total, 2)})
    else:
        final_total = cash
        if equity_curve[-1]['date'] != _fmt_date(last_date):
            equity_curve.append({'date': _fmt_date(last_date), 'value': round(final_total, 2)})

    stats = _build_stats(trades, final_total, last_date, equity_curve)
    return {
        'stats': stats,
        'equity_curve': sample_curve(equity_curve),
        'trades': trades[:MAX_TRADES_STORED],
    }


def simulate_fixed_10k(df, buy_mask, sell_mask):
    """1万定额模式：每次买信号买入1万元（最多10笔），卖信号清仓全部。"""
    close = df['close']
    dates = df.index

    events = [(d, 'buy') for d in dates[buy_mask].tolist()] + \
             [(d, 'sell') for d in dates[sell_mask].tolist()]
    events.sort(key=lambda x: x[0])

    cash = float(INITIAL_CAPITAL)
    positions = []  # [(buy_date, buy_close, shares)]
    trades = []
    equity_curve = [{'date': _fmt_date(dates[0]), 'value': round(cash, 2)}]

    for date, sig_type in events:
        close_val = close.loc[date]

        if sig_type == 'buy' and cash >= POSITION_SIZE and len(positions) < MAX_POSITIONS:
            shares = POSITION_SIZE / close_val
            positions.append((date, close_val, shares))
            cash -= POSITION_SIZE

        elif sig_type == 'sell' and positions:
            total_cost = POSITION_SIZE * len(positions)
            total_shares = sum(s for _, _, s in positions)
            sell_amount = total_shares * close_val
            first_buy_date = positions[0][0]
            avg_buy_price = total_cost / total_shares
            ret_pct = (close_val - avg_buy_price) / avg_buy_price * 100
            hold_days = _days_between(first_buy_date, date)
            cash += sell_amount
            positions = []
            # 卖出后账户快照（定额模式：现金+持仓市值，此时持仓已清仓=纯现金）
            account_total = cash
            cum_profit = account_total - INITIAL_CAPITAL
            cum_return = cum_profit / INITIAL_CAPITAL * 100
            trades.append({
                'buy_date': _fmt_date(first_buy_date),
                'buy_price': round(avg_buy_price, 2),
                'sell_date': _fmt_date(date),
                'sell_price': round(close_val, 2),
                'ret': round(ret_pct, 2),
                'hold_days': hold_days,
                'account_total': round(account_total, 2),
                'cumulative_profit': round(cum_profit, 2),
                'cumulative_return': round(cum_return, 2),
            })
            equity_curve.append({'date': _fmt_date(date), 'value': round(cash, 2)})

    # 期末估值
    last_date = dates[-1]
    last_close = close.iloc[-1]
    hv = sum(s * last_close for _, _, s in positions)
    final_total = cash + hv
    if positions or equity_curve[-1]['date'] != _fmt_date(last_date):
        equity_curve.append({'date': _fmt_date(last_date), 'value': round(final_total, 2)})

    stats = _build_stats(trades, final_total, last_date, equity_curve)
    return {
        'stats': stats,
        'equity_curve': sample_curve(equity_curve),
        'trades': trades[:MAX_TRADES_STORED],
    }


def main():
    print(f"[load] {INDEX_ID} ({INDEX_NAME}) from {DB}")
    df = load_index_data(INDEX_ID)
    if df is None:
        print(f"ERROR: 无法加载 {INDEX_ID} 数据", file=sys.stderr)
        sys.exit(1)
    print(f"  数据: {len(df)} 条, {df.index[0].date()} ~ {df.index[-1].date()}")

    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    print(f"[signals] buy策略={len(buy_signals)}, sell策略={len(sell_signals)}")

    # 初始化结果结构
    result = {
        'generated_at': _fmt_date(df.index[-1]),
        'index_id': INDEX_ID,
        'index_name': INDEX_NAME,
        'initial_capital': INITIAL_CAPITAL,
        'strategies': {}
    }

    # 为每个策略初始化
    all_keys = BUY_KEYS + SELL_KEYS
    for key in all_keys:
        result['strategies'][key] = {
            'side': 'buy' if key in BUY_KEYS else 'sell',
            'pairs': {}
        }

    # 穷尽配对：每个买策略 × 每个卖策略
    n_pairs = 0
    for buy_key in BUY_KEYS:
        buy_mask = buy_signals.get(buy_key)
        if buy_mask is None or buy_mask.sum() == 0:
            print(f"  SKIP buy {buy_key}: 无信号")
            continue

        for sell_key in SELL_KEYS:
            sell_mask = sell_signals.get(sell_key)
            if sell_mask is None or sell_mask.sum() == 0:
                print(f"  SKIP sell {sell_key}: 无信号")
                continue

            # 两种交易模式
            full_in = simulate_full_in(df, buy_mask, sell_mask)
            fixed_10k = simulate_fixed_10k(df, buy_mask, sell_mask)

            pair_data = {'full_in': full_in, 'fixed_10k': fixed_10k}

            # 存到买策略的 pairs（key=sell_key）
            result['strategies'][buy_key]['pairs'][sell_key] = pair_data
            # 存到卖策略的 pairs（key=buy_key）
            result['strategies'][sell_key]['pairs'][buy_key] = pair_data

            n_pairs += 1
            fi = full_in['stats']
            fk = fixed_10k['stats']
            print(f"  {buy_key:22s} x {sell_key:22s}  "
                  f"full_in: {fi['n_trades']:3d}笔 ret={fi['total_ret']:+7.1f}%  "
                  f"fixed_10k: {fk['n_trades']:3d}笔 ret={fk['total_ret']:+7.1f}%")

    print(f"\n[配对] {n_pairs} 组配对 × 2模式 = {n_pairs * 2} 组回测")

    # 写入双版
    out_paths = [
        os.path.join(BASE, 'web', 'data', 'lab', 'lab_simulate.json'),
        os.path.join(BASE, 'static-site', 'data', 'lab', 'lab_simulate.json'),
    ]
    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # 紧凑序列化（无缩进 + 最短分隔符），体积约为 indent=2 的 45%
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = os.path.getsize(p) / 1024
        print(f"[output] {p} ({size_kb:.1f} KB)")

    print(f"\n完成: {n_pairs} 组配对, {len(all_keys)} 个策略")


if __name__ == '__main__':
    main()
