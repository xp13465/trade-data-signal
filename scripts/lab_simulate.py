#!/usr/bin/env python3
"""策略实验室配对交易模拟回测 -- 生成 lab_simulate.json

对每个非排除策略（16个），在上证指数(sh)上做配对实战模拟：
  - 买策略：策略买入信号 -> 全仓买入，D1卖出信号 -> 全仓卖出
  - 卖策略：C1买入信号 -> 全仓买入，策略卖出信号 -> 全仓卖出
  - 本金10万，全仓复利滚动（卖所得为新本金）
  - 末尾未平仓按最后收盘价计
  - 指标：总收益率/年化/最大回撤/胜率/交易次数 + 净值曲线 + 交易记录

输出: web/data/lab_simulate.json + static-site/data/lab_simulate.json
"""
import json
import os
import sys
import sqlite3
import pandas as pd
import numpy as np

# 导入 backtest_strategies 的信号生成函数
A_STOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "a-stock-data")
sys.path.insert(0, A_STOCK_DIR)
from backtest_strategies import gen_buy_signals, gen_sell_signals, STRATEGY_DESC

BASE = os.path.dirname(os.path.dirname(__file__))
DB = os.path.join(BASE, "data", "sentiment.db")
INDEX_ID = "sh"
INDEX_NAME = "上证指数"
INITIAL_CAPITAL = 100_000

# 16个非排除策略（buy zone 7 + sell zone 7 + prod zone 2）
LAB_STRATEGIES = {
    # 买策略 -> 配对 D1_high20_drop5 卖
    'BB_lower_revert':       {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'Supertrend_buy':       {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'Donchian20_up':        {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'Donchian55_up':        {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'MA_golden_5_20':       {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'MA_golden_10_60':      {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'MACD_golden':          {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    'C1_RSI30':             {'side': 'buy',  'pair_sell': 'D1_high20_drop5'},
    # 卖策略 -> 配对 C1_RSI30 买
    'BB_upper_revert':      {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'MA_death_5_20':        {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'BB_middle_break':      {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'Donchian10_down':      {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'Donchian20_down':      {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'MACD_death':           {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'ATR_trail_stop':       {'side': 'sell', 'pair_buy':  'C1_RSI30'},
    'D1_high20_drop5':      {'side': 'sell', 'pair_buy':  'C1_RSI30'},
}


def load_index_data(iid):
    """从 sentiment.db index_daily 读 OHLC，返回 DataFrame。"""
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
    """将 pandas Timestamp 或 datetime 格式化为 YYYY-MM-DD。"""
    if isinstance(dt, pd.Timestamp):
        return dt.strftime('%Y-%m-%d')
    return str(dt)[:10]


def _days_between(d1, d2):
    """两个日期间的天数（d1, d2 为 pandas Timestamp）。"""
    if isinstance(d1, str):
        d1 = pd.Timestamp(d1)
    if isinstance(d2, str):
        d2 = pd.Timestamp(d2)
    return abs((d2 - d1).days)


def simulate_paired(df, buy_mask, sell_mask):
    """配对交易模拟（全仓进出，一次一笔）。

    buy_mask / sell_mask: bool Series 对齐 df.index
    返回: {stats, equity_curve, trades}
    """
    close = df['close']
    dates = df.index

    buy_dates = dates[buy_mask].tolist()
    sell_dates = dates[sell_mask].tolist()

    # 合并所有信号按时间排序
    events = [(d, 'buy') for d in buy_dates] + [(d, 'sell') for d in sell_dates]
    events.sort(key=lambda x: x[0])

    cash = float(INITIAL_CAPITAL)
    holding = None  # (buy_date, buy_close, shares)
    trades = []
    equity_curve = [{'date': _fmt_date(dates[0]), 'value': round(cash, 2)}]

    peak = cash
    max_dd = 0.0

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
            trades.append({
                'buy_date': _fmt_date(buy_date),
                'buy_price': round(buy_close, 2),
                'sell_date': _fmt_date(date),
                'sell_price': round(close_val, 2),
                'ret': round(ret_pct, 2),
                'hold_days': hold_days,
            })
            cash = sell_amount
            holding = None
            equity_curve.append({'date': _fmt_date(date), 'value': round(cash, 2)})

        # 更新总资产 & 回撤
        hv = holding[2] * close_val if holding else 0.0
        total = cash + hv
        if total > peak:
            peak = total
        else:
            dd = (peak - total) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

    # 期末估值
    last_date = dates[-1]
    last_close = close.iloc[-1]
    if holding is not None:
        hv = holding[2] * last_close
        final_total = cash + hv
        equity_curve.append({'date': _fmt_date(last_date), 'value': round(final_total, 2)})
    else:
        final_total = cash
        if equity_curve[-1]['date'] != _fmt_date(last_date):
            equity_curve.append({'date': _fmt_date(last_date), 'value': round(final_total, 2)})

    # 统计
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

    # 补充回撤计算（如果上面循环中没有捕获到，用 equity_curve 补算）
    if max_dd == 0 and len(equity_curve) > 1:
        vals = [e['value'] for e in equity_curve]
        pk = vals[0]
        for v in vals[1:]:
            if v > pk:
                pk = v
            dd = (pk - v) / pk * 100 if pk > 0 else 0
            if dd > max_dd:
                max_dd = dd

    return {
        'stats': {
            'total_ret': round(total_ret, 2),
            'annual_ret': round(annual_ret, 1),
            'max_drawdown': round(max_dd, 1),
            'win_rate': round(win_rate, 1),
            'n_trades': len(trades),
            'final_total': round(final_total, 2),
            'years': round(years, 1),
        },
        'equity_curve': equity_curve,
        'trades': trades,
    }


def main():
    print(f"[load] {INDEX_ID} ({INDEX_NAME}) from {DB}")
    df = load_index_data(INDEX_ID)
    if df is None:
        print(f"ERROR: 无法加载 {INDEX_ID} 数据", file=sys.stderr)
        sys.exit(1)
    print(f"  数据: {len(df)} 条, {df.index[0].date()} ~ {df.index[-1].date()}")

    # 生成全部买卖信号
    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    print(f"[signals] buy策略={len(buy_signals)}, sell策略={len(sell_signals)}")

    # 检查 Vol_breakout 是否存在（指数无 volume 可能不生成）
    if 'Vol_breakout' in buy_signals:
        print("  注意: Vol_breakout 存在（但属于排除区，不模拟）")

    result = {
        'generated_at': _fmt_date(df.index[-1]),
        'index_id': INDEX_ID,
        'index_name': INDEX_NAME,
        'initial_capital': INITIAL_CAPITAL,
        'strategies': {}
    }

    for key, cfg in LAB_STRATEGIES.items():
        side = cfg['side']
        if side == 'buy':
            strat_mask = buy_signals.get(key)
            pair_mask = sell_signals.get(cfg['pair_sell'])
            pair_name = cfg['pair_sell']
        else:
            strat_mask = sell_signals.get(key)
            pair_mask = buy_signals.get(cfg['pair_buy'])
            pair_name = cfg['pair_buy']

        if strat_mask is None or pair_mask is None:
            print(f"  SKIP {key}: 信号缺失")
            result['strategies'][key] = {
                'side': side,
                'pair_with': pair_name,
                'stats': None,
                'equity_curve': [],
                'trades': [],
            }
            continue

        if strat_mask.sum() == 0:
            print(f"  SKIP {key}: 无信号 ({strat_mask.sum()} 买/卖信号)")
            result['strategies'][key] = {
                'side': side,
                'pair_with': pair_name,
                'stats': None,
                'equity_curve': [],
                'trades': [],
            }
            continue

        # 买策略: strat_mask=买信号, pair_mask=卖信号
        # 卖策略: pair_mask=买信号, strat_mask=卖信号
        sim = simulate_paired(df, strat_mask if side == 'buy' else pair_mask,
                              pair_mask if side == 'buy' else strat_mask)
        sim['side'] = side
        sim['pair_with'] = pair_name
        result['strategies'][key] = sim
        s = sim['stats']
        print(f"  {key:22s} side={side:4s} pair={pair_name:18s} "
              f"trades={s['n_trades']:3d} ret={s['total_ret']:+7.1f}% "
              f"annual={s['annual_ret']:+5.1f}% dd={s['max_drawdown']:5.1f}% "
              f"win={s['win_rate']:4.1f}%")

    # 写入双版
    out_paths = [
        os.path.join(BASE, 'web', 'data', 'lab_simulate.json'),
        os.path.join(BASE, 'static-site', 'data', 'lab_simulate.json'),
    ]
    for p in out_paths:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        size_kb = os.path.getsize(p) / 1024
        print(f"[output] {p} ({size_kb:.1f} KB)")

    n_with_data = sum(1 for v in result['strategies'].values() if v.get('stats'))
    print(f"\n完成: {n_with_data}/{len(LAB_STRATEGIES)} 个策略有配对交易数据")


if __name__ == '__main__':
    main()
