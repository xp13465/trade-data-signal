#!/usr/bin/env python3
"""策略实验室配对交易模拟回测 -- 生成 lab_simulate.json

穷尽配对：8个买策略 × 8个卖策略 = 64组配对 × 2种交易模式 = 128组回测。
5窗口：全历史/近10年/近5年/近3年/近1年。

交易模式：
  - full_in（全仓进出）：买信号全仓买入，卖信号全仓卖出，本金复利滚动
  - fixed_10k（1万定额）：每次买信号买入1万元（最多10笔），卖信号清仓全部

控体积设计：
  - 配对去重：pairs 顶层字典以 "buy_key|sell_key" 组合键存一份（不再对称双存，体积减半）。
  - trades 全史存一份，各窗口存 [start,end) 切片索引（tw），前端按索引切片展示。
  - equity_curve 每窗口独立计算（从 INITIAL_CAPITAL 起算），采样后存储。结构为 dict {all,y10,y5,y3,y1}。
  - stats 每窗口独立计算（5窗口×7字段，体积可忽略）。

输出结构: 每个指数拆两文件，分阶段加载（推荐榜秒开，详情按需加载）

  1) lab_sim_{iid}_stats.json（小，~几百KB）：推荐榜/矩阵/配对卡片所需
  {
    generated_at, index_id, index_name, initial_capital,
    windows: [{k,l,s,e}, ...],
    strategies: {key: {side, partners}},
    pairs: {"buy_key|sell_key": {
      full_in:   {stats:{all,y10,y5,y3,y1}},
      fixed_10k: {stats:{all,y10,y5,y3,y1}}
    }}
  }

  2) lab_sim_{iid}_full.json（大，原大小）：详情/配对卡片用，按需加载
  {
    pairs: {"buy_key|sell_key": {
      full_in:   {equity_curve:{all,y10,y5,y3,y1}, trades, tw},
      fixed_10k: {equity_curve:{all,y10,y5,y3,y1}, trades, tw}
    }}
  }

  - tw: {window_key: [start_idx, end_exclusive_idx]}，指向同组 trades 数组。
  - equity_curve: {window_key: [{date,value},...]}，每窗口从 INITIAL_CAPITAL 独立起算，采样后存储。
  - 前端双向查找：给定策略A+伙伴B，若A.side=="buy"则pair_id=A+"|"+B，否则pair_id=B+"|"+A。
  - 前端先 fetch stats（秒开推荐榜+矩阵+配对卡片），点详情/弹窗时再 fetch full 合并入已缓存 stats。

输出: web/data/lab/ + static-site/data/lab/ 各两个文件 lab_sim_{iid}_stats.json / lab_sim_{iid}_full.json
"""
import bisect
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
# 多指数回测：每个指数独立跑128组配对×5窗口，输出 lab_simulate_{iid}.json
# 9个A股宽基指数：覆盖大盘/成长/价值/中小盘全谱系（含北证50，历史较短2022起）
SIM_INDEXES = [
    ('sh',      '上证指数'),
    ('sz',      '深证成指'),
    ('cyb',     '创业板指'),
    ('kc50',    '科创50'),
    ('bj50',    '北证50'),
    ('sz50',    '上证50'),
    ('hs300',   '沪深300'),
    ('csi500',  '中证500'),
    ('csi1000', '中证1000'),
]
INITIAL_CAPITAL = 100_000
POSITION_SIZE = 10_000
MAX_POSITIONS = 10
MAX_CURVE_POINTS = 100  # 全历史窗口净值曲线采样点数
MAX_CURVE_POINTS_WIN = 100  # 子窗口采样点数

# 5个回测窗口：(key, label, years_or_None)
WINDOW_DEFS = [
    ('all', '全历史', None),
    ('y10', '近10年', 10),
    ('y5',  '近5年',  5),
    ('y3',  '近3年',  3),
    ('y1',  '近1年',  1),
]

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


def _build_stats(trades, final_total, last_date, equity_curve, years=None):
    """计算统计指标。years=None 时从首笔交易日算，指定时用窗口年限。"""
    total_ret = (final_total - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    if years is None:
        if trades:
            first_buy_date = pd.Timestamp(trades[0]['bd'])
            years = _days_between(first_buy_date, last_date) / 365.25
        else:
            years = 0
    if years > 0 and final_total > 0:
        annual_ret = ((final_total / INITIAL_CAPITAL) ** (1 / years) - 1) * 100
    else:
        annual_ret = 0.0

    win_trades = [t for t in trades if t['ret'] > 0]
    win_rate = len(win_trades) / len(trades) * 100 if trades else 0.0

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


def simulate_full_in(df, buy_mask, sell_mask, w_start=None):
    """全仓进出模式：买信号全仓买入，卖信号全仓卖出。
    w_start: 窗口起始(Timestamp)，None=全历史。指定时只处理 >= w_start 的事件，
    equity 从 INITIAL_CAPITAL 起算。返回未采样 equity_curve + trades + final_total。"""
    close = df['close']
    dates = df.index

    buy_dates = dates[buy_mask]
    sell_dates = dates[sell_mask]
    if w_start is not None:
        buy_dates = buy_dates[buy_dates >= w_start]
        sell_dates = sell_dates[sell_dates >= w_start]

    events = [(d, 'buy') for d in buy_dates.tolist()] + \
             [(d, 'sell') for d in sell_dates.tolist()]
    events.sort(key=lambda x: x[0])

    cash = float(INITIAL_CAPITAL)
    holding = None  # (buy_date, buy_close, shares)
    trades = []
    # equity 起点：全历史用 dates[0]，子窗口用 >= w_start 的首个交易日
    if w_start is not None:
        si = dates.searchsorted(w_start)
        start_dt = dates[si] if si < len(dates) else dates[-1]
    else:
        start_dt = dates[0]
    equity_curve = [{'date': _fmt_date(start_dt), 'value': round(cash, 2)}]

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
            account_total = cash
            cum_profit = account_total - INITIAL_CAPITAL
            trades.append({
                'bd': _fmt_date(buy_date),
                'bp': round(buy_close, 2),
                'sd': _fmt_date(date),
                'sp': round(close_val, 2),
                'ret': round(ret_pct, 2),
                'hd': hold_days,
                'at': round(account_total, 2),
                'cp': round(cum_profit, 2),
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

    return {
        'equity_curve': equity_curve,
        'trades': trades,
        'final_total': final_total,
        'last_date': last_date,
    }


def simulate_fixed_10k(df, buy_mask, sell_mask, w_start=None):
    """1万定额模式：每次买信号买入1万元（最多10笔），卖信号清仓全部。
    w_start: 窗口起始(Timestamp)，None=全历史。指定时只处理 >= w_start 的事件，
    equity 从 INITIAL_CAPITAL 起算。返回未采样 equity_curve + trades + final_total。"""
    close = df['close']
    dates = df.index

    buy_dates = dates[buy_mask]
    sell_dates = dates[sell_mask]
    if w_start is not None:
        buy_dates = buy_dates[buy_dates >= w_start]
        sell_dates = sell_dates[sell_dates >= w_start]

    events = [(d, 'buy') for d in buy_dates.tolist()] + \
             [(d, 'sell') for d in sell_dates.tolist()]
    events.sort(key=lambda x: x[0])

    cash = float(INITIAL_CAPITAL)
    positions = []  # [(buy_date, buy_close, shares)]
    trades = []
    if w_start is not None:
        si = dates.searchsorted(w_start)
        start_dt = dates[si] if si < len(dates) else dates[-1]
    else:
        start_dt = dates[0]
    equity_curve = [{'date': _fmt_date(start_dt), 'value': round(cash, 2)}]

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
            account_total = cash
            cum_profit = account_total - INITIAL_CAPITAL
            trades.append({
                'bd': _fmt_date(first_buy_date),
                'bp': round(avg_buy_price, 2),
                'sd': _fmt_date(date),
                'sp': round(close_val, 2),
                'ret': round(ret_pct, 2),
                'hd': hold_days,
                'at': round(account_total, 2),
                'cp': round(cum_profit, 2),
            })
            equity_curve.append({'date': _fmt_date(date), 'value': round(cash, 2)})

    # 期末估值
    last_date = dates[-1]
    last_close = close.iloc[-1]
    hv = sum(s * last_close for _, _, s in positions)
    final_total = cash + hv
    if positions or equity_curve[-1]['date'] != _fmt_date(last_date):
        equity_curve.append({'date': _fmt_date(last_date), 'value': round(final_total, 2)})

    return {
        'equity_curve': equity_curve,
        'trades': trades,
        'final_total': final_total,
        'last_date': last_date,
    }


def build_pair_result(df, buy_mask, sell_mask, last_date, first_date):
    """每窗口独立模拟：从 INITIAL_CAPITAL 起算该窗口的净值曲线。

    - all: 全历史模拟（同原逻辑，equity 从 dates[0] 起算）
    - y10/y5/y3/y1: 窗口内独立模拟，起点资金=INITIAL_CAPITAL
    - trades: 全史共享一份，tw 存各窗口切片索引
    - equity_curve: 每窗口独立一份 dict {all,y10,y5,y3,y1}，采样后存储
    - stats: 每窗口独立计算（从未采样 equity_curve 算 max_dd，精度不丢）
    """
    out = {}
    for mode, sim_func in (('full_in', simulate_full_in), ('fixed_10k', simulate_fixed_10k)):
        win_eq = {}      # {window_key: sampled equity_curve}
        win_stats = {}
        all_trades = None

        for wk, _wl, wy in WINDOW_DEFS:
            if wk == 'all':
                w_start = None
                actual_years = None   # 从首笔交易日算
            else:
                w_start = last_date - pd.DateOffset(years=wy)
                if w_start < first_date:
                    w_start = first_date
                actual_years = _days_between(w_start, last_date) / 365.25

            raw = sim_func(df, buy_mask, sell_mask, w_start=w_start)
            eq_sampled = sample_curve(
                raw['equity_curve'],
                MAX_CURVE_POINTS if wk == 'all' else MAX_CURVE_POINTS_WIN,
            )
            stats = _build_stats(
                raw['trades'], raw['final_total'], raw['last_date'],
                raw['equity_curve'], years=actual_years,
            )

            win_eq[wk] = eq_sampled
            win_stats[wk] = stats
            if wk == 'all':
                all_trades = raw['trades']

        # tw: trades 窗口切片索引（指向全史 trades 数组）
        trades = all_trades
        trade_sds = [t['sd'] for t in trades]
        tw = {}
        for wk, _wl, wy in WINDOW_DEFS:
            if wk == 'all':
                tw[wk] = [0, len(trades)]
                continue
            w_start = last_date - pd.DateOffset(years=wy)
            if w_start < first_date:
                w_start = first_date
            w_start_str = _fmt_date(w_start)
            w_end_str = _fmt_date(last_date)
            ts = bisect.bisect_left(trade_sds, w_start_str)
            te = bisect.bisect_right(trade_sds, w_end_str)
            tw[wk] = [ts, te]

        out[mode] = {
            'stats': win_stats,
            'equity_curve': win_eq,
            'trades': trades,
            'tw': tw,
        }
    return out


def run_index(iid, iname):
    """单指数回测：128组配对×2模式×5窗口，输出 lab_simulate_{iid}.json。"""
    print(f"\n[load] {iid} ({iname}) from {DB}")
    df = load_index_data(iid)
    if df is None:
        print(f"  ERROR: 无法加载 {iid} 数据，跳过")
        return
    first_date = df.index[0]
    last_date = df.index[-1]
    print(f"  数据: {len(df)} 条, {first_date.date()} ~ {last_date.date()}")

    # 构建窗口元数据
    windows = []
    for wk, wl, wy in WINDOW_DEFS:
        if wy is None:
            ws = first_date
        else:
            ws = last_date - pd.DateOffset(years=wy)
            if ws < first_date:
                ws = first_date
        windows.append({'k': wk, 'l': wl, 's': _fmt_date(ws), 'e': _fmt_date(last_date)})
    print(f"[windows] {len(windows)} 个: {', '.join(w['k'] for w in windows)}")

    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    print(f"[signals] buy策略={len(buy_signals)}, sell策略={len(sell_signals)}")

    # 初始化结果结构
    result = {
        'generated_at': _fmt_date(last_date),
        'index_id': iid,
        'index_name': iname,
        'initial_capital': INITIAL_CAPITAL,
        'windows': windows,
        'strategies': {},
        'pairs': {},
    }

    # 为每个策略初始化（只存 side + partners 列表，不再存 pairs 数据）
    all_keys = BUY_KEYS + SELL_KEYS
    for key in all_keys:
        result['strategies'][key] = {
            'side': 'buy' if key in BUY_KEYS else 'sell',
            'partners': [],
        }

    # 穷尽配对：每个买策略 × 每个卖策略（去重存储，只在 pairs 顶层字典存一份）
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

            # 构建最终结构（5窗口各自独立模拟，equity 从 INITIAL_CAPITAL 起算）
            pair_id = f"{buy_key}|{sell_key}"
            pair_data = build_pair_result(df, buy_mask, sell_mask, last_date, first_date)
            result['pairs'][pair_id] = pair_data

            # 伙伴关系（双向，用于前端查找 pair_id）
            result['strategies'][buy_key]['partners'].append(sell_key)
            result['strategies'][sell_key]['partners'].append(buy_key)

            n_pairs += 1
            fi = pair_data['full_in']['stats']['all']
            fk = pair_data['fixed_10k']['stats']['all']
            print(f"  {buy_key:22s} x {sell_key:22s}  "
                  f"full_in: {fi['n_trades']:3d}笔 ret={fi['total_ret']:+7.1f}%  "
                  f"fixed_10k: {fk['n_trades']:3d}笔 ret={fk['total_ret']:+7.1f}%")

    print(f"\n[配对] {n_pairs} 组 × 2模式 × 5窗口 = {n_pairs * 2 * 5} 组窗口回测")

    # 拆分输出：stats（小，推荐榜/矩阵/配对卡片用）+ full（大，详情trades/equity_curve用）
    stats_result = {
        'generated_at': result['generated_at'],
        'index_id': iid,
        'index_name': iname,
        'initial_capital': INITIAL_CAPITAL,
        'windows': result['windows'],
        'strategies': result['strategies'],
        'pairs': {},
    }
    full_result = {'index_id': iid, 'pairs': {}}
    for pk, pv in result['pairs'].items():
        stats_result['pairs'][pk] = {}
        full_result['pairs'][pk] = {}
        for mode in ('full_in', 'fixed_10k'):
            mpv = pv[mode]
            stats_result['pairs'][pk][mode] = {'stats': mpv['stats']}
            full_result['pairs'][pk][mode] = {
                'equity_curve': mpv['equity_curve'],
                'trades': mpv['trades'],
                'tw': mpv['tw'],
            }

    # 写入双版（per-index 拆两文件：stats 小秒开，full 大按需）
    out_files = [
        (f'lab_sim_{iid}_stats.json', stats_result),
        (f'lab_sim_{iid}_full.json', full_result),
    ]
    for fname, data in out_files:
        for base_dir in ('web', 'static-site'):
            p = os.path.join(BASE, base_dir, 'data', 'lab', fname)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
            size_kb = os.path.getsize(p) / 1024
            print(f"[output] {p} ({size_kb:.1f} KB)")

    print(f"完成: {iid} ({iname}) - {n_pairs} 组配对, {len(all_keys)} 个策略, 5窗口")


def main():
    print(f"=== 策略实验室多指数回测 ===")
    print(f"指数: {[i[0] for i in SIM_INDEXES]}")
    total_start = pd.Timestamp.now()
    for iid, iname in SIM_INDEXES:
        run_index(iid, iname)
    elapsed = pd.Timestamp.now() - total_start
    print(f"\n=== 全部完成: {len(SIM_INDEXES)} 个指数, 总耗时 {elapsed.total_seconds():.1f}s ===")


if __name__ == '__main__':
    main()
