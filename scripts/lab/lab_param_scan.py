#!/usr/bin/env python3
"""策略实验室参数敏感扫描 -- 网格扫描验证策略不过拟合

复刻 gen_buy_signals / gen_sell_signals 的信号生成逻辑，暴露底层指标参数（RSI period/threshold、
Donchian period、Bollinger n/k、Supertrend period/mult、D1 period/drop），对每个策略做网格扫描，
paired with 固定生产基线 partner（买侧扫描配 D1 卖，卖侧扫描配 C1 买），输出 ret/dd/n_trades，
评估默认参数是否处于稳定高原（stable plateau）而非孤立尖峰（overfit risk）。

不动 backtest_strategies.py，只 import 公开指标函数（rsi/ma/macd/bollinger/donchian/supertrend/
_cross_up/_cross_down），在本脚本内参数化复刻信号生成。

稳定性判定：
  - neighbors = 与默认参数在某一维相差 1 步的参数组合
  - stable_plateau: 默认 ret>0 且 neighbor_avg >= 0.7*default（默认处于高原）
  - sharp_peak: best ret > 1.5*neighbor_avg 且 best≠default（孤立尖峰，过拟合风险）
  - robust_profitable: >50% 组合 ret>0（参数不敏感，稳健盈利）
  - flat_negative: 默认及多数组合 ret<=0

输出:
  static-site/data/lab_param_scan.json
  web/data/lab_param_scan.json (双版同步)
"""
import json
import os
import sys
from itertools import product

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(BASE, 'a-stock-data'))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from backtest_strategies import (
    rsi, ma, macd, bollinger, donchian, supertrend,
    _cross_up, _cross_down,
)
from lab_simulate import (
    load_index_data, simulate_full_in, _build_stats,
    _fmt_date, INITIAL_CAPITAL,
)

SCAN_INDEXES = [
    ('sh',  '上证指数'),
    ('hs300', '沪深300'),
    ('cyb', '创业板指'),
]


# ============ 参数化信号生成（复刻 backtest_strategies，暴露参数）============
def buy_C1_RSI30(df, rsi_period=14, threshold=30):
    r = rsi(df['close'], rsi_period); rp = r.shift(1)
    return _cross_up(r, rp, threshold).fillna(False).astype(bool)


def buy_BB_lower_revert(df, n=20, k=2.0):
    close = df['close']
    _, _, bl = bollinger(close, n, k)
    return ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False).astype(bool)


def buy_Donchian20_up(df, period=20):
    close, high = df['close'], df['high']
    du = high.rolling(period, min_periods=period).max().shift(1)
    return ((close > du) & (close.shift(1) <= du.shift(1))).fillna(False).astype(bool)


def buy_Supertrend(df, period=10, mult=3.0):
    st, _, _ = supertrend(df['high'], df['low'], df['close'], period, mult)
    return ((st.shift(1) == -1) & (st == 1)).fillna(False).astype(bool)


def sell_D1_high20_drop5(df, period=20, drop=0.95):
    close, high = df['close'], df['high']
    hh = high.rolling(period, min_periods=period).max()
    th = hh * drop
    return ((close.shift(1) >= th.shift(1)) & (close < th)).fillna(False).astype(bool)


def sell_BB_upper_revert(df, n=20, k=2.0):
    close = df['close']
    bu, _, _ = bollinger(close, n, k)
    return ((close.shift(1) > bu.shift(1)) & (close < bu)).fillna(False).astype(bool)


def sell_Donchian10_down(df, period=10):
    close, low = df['close'], df['low']
    dl = low.rolling(period, min_periods=period).min().shift(1)
    return ((close < dl) & (close.shift(1) >= dl.shift(1))).fillna(False).astype(bool)


# ============ 扫描定义 ============
# 每个: (strategy_key, side, gen_func, param_dims[(name, [values])], default{param:val})
SCAN_DEFS = [
    ('C1_RSI30', 'buy', buy_C1_RSI30,
     [('rsi_period', [7, 10, 14, 21, 28]), ('threshold', [20, 25, 30, 35, 40])],
     {'rsi_period': 14, 'threshold': 30}),
    ('BB_lower_revert', 'buy', buy_BB_lower_revert,
     [('n', [10, 15, 20, 30]), ('k', [1.5, 2.0, 2.5, 3.0])],
     {'n': 20, 'k': 2.0}),
    ('Donchian20_up', 'buy', buy_Donchian20_up,
     [('period', [10, 15, 20, 25, 30, 40, 55])],
     {'period': 20}),
    ('Supertrend_buy', 'buy', buy_Supertrend,
     [('period', [7, 10, 14, 20]), ('mult', [2.0, 2.5, 3.0, 3.5, 4.0])],
     {'period': 10, 'mult': 3.0}),
    ('D1_high20_drop5', 'sell', sell_D1_high20_drop5,
     [('period', [10, 15, 20, 30]), ('drop', [0.90, 0.93, 0.95, 0.97])],
     {'period': 20, 'drop': 0.95}),
    ('BB_upper_revert', 'sell', sell_BB_upper_revert,
     [('n', [10, 15, 20, 30]), ('k', [1.5, 2.0, 2.5, 3.0])],
     {'n': 20, 'k': 2.0}),
    ('Donchian10_down', 'sell', sell_Donchian10_down,
     [('period', [5, 10, 15, 20])],
     {'period': 10}),
]

REF_BUY_KEY = 'C1_RSI30'
REF_SELL_KEY = 'D1_high20_drop5'


def _params_key(params, dims):
    """生成参数组合的可读键，如 'p14_t30'。"""
    parts = []
    for name, _ in dims:
        v = params[name]
        if isinstance(v, float):
            parts.append(f'{name[0]}{v}')
        else:
            parts.append(f'{name[0]}{v}')
    return '_'.join(parts)


def _is_neighbor(p1, p2, dims):
    """p1/p2 是否在恰好一维上相差 1 步。"""
    diff_dims = 0
    for name, vals in dims:
        i1 = vals.index(p1[name])
        i2 = vals.index(p2[name])
        if i1 != i2:
            if abs(i1 - i2) == 1:
                diff_dims += 1
            else:
                return False  # 相差>1步不算邻居
    return diff_dims == 1


def _verdict(default_ret, neighbor_avg, best_ret, best_is_default, pos_frac):
    """判定稳定性类型。"""
    if default_ret <= 0 and pos_frac < 0.3:
        return 'flat_negative'
    if pos_frac > 0.5 and default_ret > 0:
        if neighbor_avg is not None and default_ret > 0 and neighbor_avg >= 0.7 * default_ret:
            return 'robust_profitable'
        return 'robust_profitable'
    if default_ret > 0 and neighbor_avg is not None and neighbor_avg >= 0.7 * default_ret:
        return 'stable_plateau'
    if best_ret is not None and not best_is_default and neighbor_avg is not None \
            and best_ret > 0 and best_ret > 1.5 * neighbor_avg:
        return 'sharp_peak'
    if default_ret > 0:
        return 'moderate'
    return 'flat_negative'


def run_scan(strategy_key, side, gen_func, dims, default_params):
    """对单个策略跑跨指数参数扫描。"""
    from backtest_strategies import gen_buy_signals, gen_sell_signals

    # 生成所有参数组合
    dim_names = [d[0] for d in dims]
    dim_vals = [d[1] for d in dims]
    all_combos = [dict(zip(dim_names, vals)) for vals in product(*dim_vals)]

    per_index = []
    for iid, iname in SCAN_INDEXES:
        df = load_index_data(iid)
        if df is None:
            continue
        last_date = df.index[-1]
        # 固定 partner
        if side == 'buy':
            partner_mask = gen_sell_signals(df).get(REF_SELL_KEY)
        else:
            partner_mask = gen_buy_signals(df).get(REF_BUY_KEY)
        if partner_mask is None:
            continue
        partner_mask = partner_mask.fillna(False).astype(bool)

        combo_results = []
        for params in all_combos:
            sig_mask = gen_func(df, **params)
            if not sig_mask.any():
                combo_results.append({
                    'params': params, 'total_ret': None, 'n_trades': 0,
                    'max_drawdown': None, 'win_rate': None, 'annual_ret': None,
                })
                continue
            if side == 'buy':
                bm, sm = sig_mask, partner_mask
            else:
                bm, sm = partner_mask, sig_mask
            r = simulate_full_in(df, bm, sm, w_start=None)
            st = _build_stats(r['trades'], r['final_total'], last_date,
                              r['equity_curve'], years=None)
            combo_results.append({
                'params': params,
                'total_ret': float(st['total_ret']),
                'annual_ret': float(st['annual_ret']),
                'max_drawdown': float(st['max_drawdown']),
                'win_rate': float(st['win_rate']),
                'n_trades': int(st['n_trades']),
            })

        # 默认参数结果
        default_combo = next(c for c in combo_results if c['params'] == default_params)
        default_ret = default_combo['total_ret'] if default_combo['total_ret'] is not None else 0.0

        # 最佳参数
        valid = [c for c in combo_results if c['total_ret'] is not None]
        best_combo = max(valid, key=lambda c: c['total_ret']) if valid else None
        best_ret = best_combo['total_ret'] if best_combo else None
        best_is_default = (best_combo is not None and best_combo['params'] == default_params)

        # 邻居平均
        neighbor_rets = []
        for c in combo_results:
            if c['total_ret'] is None:
                continue
            if _is_neighbor(c['params'], default_params, dims):
                neighbor_rets.append(c['total_ret'])
        neighbor_avg = round(sum(neighbor_rets) / len(neighbor_rets), 2) if neighbor_rets else None

        pos_count = sum(1 for c in valid if c['total_ret'] > 0)
        pos_frac = pos_count / len(valid) if valid else 0

        verdict = _verdict(default_ret, neighbor_avg, best_ret, best_is_default, pos_frac)

        per_index.append({
            'index_id': iid,
            'index_name': iname,
            'default_params': default_params,
            'default_ret': default_ret,
            'best_params': best_combo['params'] if best_combo else None,
            'best_ret': best_ret,
            'best_is_default': best_is_default,
            'worst_ret': min(c['total_ret'] for c in valid) if valid else None,
            'neighbor_avg_ret': neighbor_avg,
            'n_combos': len(all_combos),
            'n_profitable': pos_count,
            'profitable_frac': round(pos_frac, 3),
            'verdict': verdict,
            'combos': combo_results,
        })
        print(f'    [{iid}] default={default_ret:+8.1f}% best={best_ret:+8.1f}% '
              f'neighbor_avg={neighbor_avg} verdict={verdict} pos={pos_count}/{len(valid)}')

    # 跨指数汇总 verdict
    verdicts = [pi['verdict'] for pi in per_index]
    from collections import Counter
    vc = Counter(verdicts)
    overall = vc.most_common(1)[0][0] if vc else 'unknown'

    return {
        'strategy_key': strategy_key,
        'side': side,
        'param_dims': [{'name': d[0], 'values': d[1]} for d in dims],
        'default_params': default_params,
        'partner': REF_SELL_KEY if side == 'buy' else REF_BUY_KEY,
        'per_index': per_index,
        'overall_verdict': overall,
        'verdict_counts': dict(vc),
    }


def main():
    print('=== 策略实验室参数敏感扫描 (网格扫描验证不过拟合) ===')
    print(f'指数: {[i[0] for i in SCAN_INDEXES]}')
    total_start = pd.Timestamp.now()

    scans = []
    for strategy_key, side, gen_func, dims, default_params in SCAN_DEFS:
        print(f'\n[scan] {strategy_key} ({side}) dims={[d[0] for d in dims]} '
              f'default={default_params}')
        scan_out = run_scan(strategy_key, side, gen_func, dims, default_params)
        scans.append(scan_out)

    # 汇总
    summary = []
    for s in scans:
        for pi in s['per_index']:
            summary.append({
                'strategy': s['strategy_key'],
                'index_id': pi['index_id'],
                'default_ret': pi['default_ret'],
                'best_ret': pi['best_ret'],
                'best_is_default': pi['best_is_default'],
                'neighbor_avg_ret': pi['neighbor_avg_ret'],
                'profitable_frac': pi['profitable_frac'],
                'verdict': pi['verdict'],
            })

    result = {
        'generated_at': _fmt_date(pd.Timestamp.now()),
        'desc': '参数敏感扫描:7策略网格扫描,验证默认参数处于稳定高原而非孤立尖峰(过拟合)',
        'initial_capital': INITIAL_CAPITAL,
        'indexes': [i[0] for i in SCAN_INDEXES],
        'scans': scans,
        'summary': summary,
    }

    out_path = os.path.join(BASE, 'static-site', 'data', 'lab_param_scan.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(out_path) / 1024
    print(f'\n[output] {out_path} ({size_kb:.1f} KB)')

    print('\n=== 汇总: 各策略 overall verdict ===')
    for s in scans:
        print(f"  {s['strategy_key']:20s} overall={s['overall_verdict']:16s} "
              f"counts={s['verdict_counts']}")
    print('\n各策略默认 vs 最佳(3指数):')
    for s in scans:
        for pi in s['per_index']:
            flag = '*' if pi['best_is_default'] else ' '
            print(f"  {flag} {s['strategy_key']:20s} {pi['index_id']:6s} "
                  f"default={pi['default_ret']:+8.1f}% best={pi['best_ret']:+8.1f}% "
                  f"n_avg={pi['neighbor_avg_ret']} verdict={pi['verdict']}")

    elapsed = pd.Timestamp.now() - total_start
    print(f'\n=== 完成,总耗时 {elapsed.total_seconds():.1f}s ===')


if __name__ == '__main__':
    main()
