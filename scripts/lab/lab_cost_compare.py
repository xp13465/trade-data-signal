#!/usr/bin/env python3
"""策略实验室成本压力测试 -- 手续费+滑点:毛收益 vs 净收益对比

复用 lab_simulate.py 的引擎(已加 commission_rate/slippage 参数),对每个指数
按 full_in 全历史 total_ret 取 top 10 策略配对,跑 3 档成本 × 2 模式 × 2 窗口,
输出净/毛对比表 + JSON,验证策略在真实交易成本下的表现。

成本档:
  - gross: commission=0, slippage=0 (毛收益基准,等同现状生产 JSON)
  - low:   commission=0.0003(万3), slippage=0.001(千1) -- 常规散户/ETF成本
  - high:  commission=0.0005(万5), slippage=0.002(千2) -- 小盘/高频更严苛

窗口:
  - all: 全历史(复利效应下成本会被放大,看长期影响)
  - y5:  近5年(交易较少,衰减更线性,看近期真实成本)

输出:
  static-site/data/lab_cost_compare.json (前端可读)
  web/data/lab_cost_compare.json (双版同步)
"""
import json
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(BASE, 'a-stock-data'))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from backtest_strategies import gen_buy_signals, gen_sell_signals
from lab_simulate import (
    load_index_data, simulate_full_in, simulate_fixed_10k, _build_stats,
    _days_between, _fmt_date, INITIAL_CAPITAL, SIM_INDEXES,
)

COST_PRESETS = [
    {'key': 'gross', 'commission': 0.0,    'slippage': 0.0,    'label': '毛收益(无成本)'},
    {'key': 'low',   'commission': 0.0003, 'slippage': 0.001,  'label': '万3手续费+千1滑点'},
    {'key': 'high',  'commission': 0.0005, 'slippage': 0.002,  'label': '万5手续费+千2滑点'},
]
TOP_N = 10
WINDOWS = ['all', 'y5']
LAB_DIR = os.path.join(BASE, 'static-site', 'data', 'lab')


def _decay_ratio(net_ret, gross_ret):
    """相对衰减% = (net-gross)/|gross|*100。负值=变差(收益缩水/亏损扩大)。gross=0 返回 None。"""
    if abs(gross_ret) < 1e-9:
        return None
    return round((net_ret - gross_ret) / abs(gross_ret) * 100, 2)


def _run_one(df, buy_mask, sell_mask, sim_func, commission, slippage, w_start, last_date, years):
    """跑单次回测,返回 stats dict。"""
    r = sim_func(df, buy_mask, sell_mask, w_start=w_start,
                 commission_rate=commission, slippage=slippage)
    return _build_stats(r['trades'], r['final_total'], last_date,
                        r['equity_curve'], years=years)


def _window_start(df, last_date, wk):
    """返回 (w_start, years)。"""
    if wk == 'all':
        return None, None
    wy = int(wk[1:])
    ws = last_date - pd.DateOffset(years=wy)
    first_date = df.index[0]
    if ws < first_date:
        ws = first_date
    return ws, _days_between(ws, last_date) / 365.25


def run_index(iid, iname):
    """单指数:读 stats.json 取 top10,重新 gen 信号跑 3 档成本对比。"""
    stats_path = os.path.join(LAB_DIR, f'lab_sim_{iid}_stats.json')
    if not os.path.exists(stats_path):
        print(f'  SKIP {iid}: 无 stats.json')
        return None
    with open(stats_path, encoding='utf-8') as f:
        stats = json.load(f)

    # 按 full_in all total_ret 降序取 top N
    pair_items = []
    for pid, pv in stats['pairs'].items():
        try:
            ret = pv['full_in']['stats']['all']['total_ret']
            n = pv['full_in']['stats']['all']['n_trades']
        except (KeyError, TypeError):
            continue
        pair_items.append((pid, ret, n))
    pair_items.sort(key=lambda x: x[1], reverse=True)
    top = pair_items[:TOP_N]

    print(f'\n[{iid}] {iname} top{TOP_N} by full_in all total_ret:')
    for pid, ret, n in top:
        print(f'    {pid:46s} ret={ret:+10.1f}% n={n}')

    df = load_index_data(iid)
    if df is None:
        print(f'  SKIP {iid}: 无法加载数据')
        return None
    last_date = df.index[-1]
    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)

    out_pairs = []
    for rank, (pid, gross_ret_prod, n_prod) in enumerate(top, 1):
        buy_key, sell_key = pid.split('|', 1)
        bm = buy_signals.get(buy_key)
        sm = sell_signals.get(sell_key)
        if bm is None or sm is None:
            print(f'    SKIP {pid}: 信号缺失')
            continue

        pair_out = {
            'rank': rank,
            'pair_id': pid,
            'buy_key': buy_key,
            'sell_key': sell_key,
            'full_in': {},
            'fixed_10k': {},
        }
        for mode, sim_func in (('full_in', simulate_full_in), ('fixed_10k', simulate_fixed_10k)):
            mode_out = {}
            for wk in WINDOWS:
                w_start, years = _window_start(df, last_date, wk)
                win_out = {}
                for cp in COST_PRESETS:
                    st = _run_one(df, bm, sm, sim_func,
                                  cp['commission'], cp['slippage'],
                                  w_start, last_date, years)
                    win_out[cp['key']] = {
                        'total_ret': float(st['total_ret']),
                        'annual_ret': float(st['annual_ret']),
                        'final_total': float(st['final_total']),
                        'n_trades': int(st['n_trades']),
                        'win_rate': float(st['win_rate']),
                    }
                g = win_out['gross']['total_ret']
                mode_out[wk] = {
                    'gross_ret': float(g),
                    'low_ret': float(win_out['low']['total_ret']),
                    'high_ret': float(win_out['high']['total_ret']),
                    'low_decay_pts': round(win_out['low']['total_ret'] - g, 2),
                    'high_decay_pts': round(win_out['high']['total_ret'] - g, 2),
                    'low_decay_ratio': _decay_ratio(win_out['low']['total_ret'], g),
                    'high_decay_ratio': _decay_ratio(win_out['high']['total_ret'], g),
                    'n_trades': int(win_out['gross']['n_trades']),
                    'low_net_positive': bool(win_out['low']['total_ret'] > 0),
                    'high_net_positive': bool(win_out['high']['total_ret'] > 0),
                    'detail': win_out,
                }
            pair_out[mode] = mode_out
        out_pairs.append(pair_out)
        fi = pair_out['full_in']['all']
        print(f'    -> {pid:46s} gross={fi["gross_ret"]:+9.1f}% low={fi["low_ret"]:+9.1f}% '
              f'high={fi["high_ret"]:+9.1f}% low_dec={fi["low_decay_ratio"]}%%')

    return {'index_id': iid, 'index_name': iname, 'pairs': out_pairs}


def build_summary(indexes):
    """跨指数汇总:平均衰减、最敏感/最稳健策略。"""
    # 收集所有 (pair, mode=all) 的衰减数据
    records = []
    for idx in indexes:
        if not idx:
            continue
        for p in idx['pairs']:
            for mode in ('full_in', 'fixed_10k'):
                w = p[mode].get('all', {})
                if not w:
                    continue
                records.append({
                    'index_id': idx['index_id'],
                    'index_name': idx['index_name'],
                    'pair_id': p['pair_id'],
                    'mode': mode,
                    'gross_ret': w['gross_ret'],
                    'low_ret': w['low_ret'],
                    'high_ret': w['high_ret'],
                    'low_decay_ratio': w['low_decay_ratio'],
                    'high_decay_ratio': w['high_decay_ratio'],
                    'n_trades': w['n_trades'],
                    'low_net_positive': w['low_net_positive'],
                })

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    # 按指数平均衰减(full_in all,低成本档)
    by_index = []
    for iid in sorted({r['index_id'] for r in records}):
        rs = [r for r in records if r['index_id'] == iid and r['mode'] == 'full_in']
        by_index.append({
            'index_id': iid,
            'index_name': rs[0]['index_name'] if rs else iid,
            'avg_low_decay_ratio': avg([r['low_decay_ratio'] for r in rs]),
            'avg_high_decay_ratio': avg([r['high_decay_ratio'] for r in rs]),
            'n_pairs': len(rs),
        })

    # 最敏感(低档衰减比例最负,即收益缩水/亏损扩大最严重),仅看毛收益>0的
    pos = [r for r in records if r['gross_ret'] > 0 and r['mode'] == 'full_in']
    pos_sorted = sorted(pos, key=lambda r: (r['low_decay_ratio'] if r['low_decay_ratio'] is not None else 0))
    most_sensitive = [{
        'pair_id': r['pair_id'], 'index_name': r['index_name'],
        'gross_ret': r['gross_ret'], 'low_ret': r['low_ret'],
        'low_decay_ratio': r['low_decay_ratio'], 'n_trades': r['n_trades'],
    } for r in pos_sorted[:8]]

    # 最稳健(低档衰减比例最接近0,即成本影响最小)
    most_robust = [{
        'pair_id': r['pair_id'], 'index_name': r['index_name'],
        'gross_ret': r['gross_ret'], 'low_ret': r['low_ret'],
        'low_decay_ratio': r['low_decay_ratio'], 'n_trades': r['n_trades'],
    } for r in pos_sorted[-8:][::-1]]

    # 低档成本下仍盈利的比例
    pos_total = len(pos)
    pos_still_pos = len([r for r in pos if r['low_net_positive']])
    survival_rate = round(pos_still_pos / pos_total * 100, 1) if pos_total else 0

    return {
        'by_index': by_index,
        'most_sensitive_low_cost': most_sensitive,
        'most_robust_low_cost': most_robust,
        'positive_pairs': pos_total,
        'still_positive_after_low_cost': pos_still_pos,
        'survival_rate_pct': survival_rate,
    }


def main():
    print('=== 策略实验室成本压力测试 (手续费+滑点) ===')
    print(f'成本档: {[(c["key"], c["commission"], c["slippage"]) for c in COST_PRESETS]}')
    print(f'窗口: {WINDOWS}, 每指数 top{TOP_N}')
    total_start = pd.Timestamp.now()

    indexes = []
    for iid, iname in SIM_INDEXES:
        idx_out = run_index(iid, iname)
        if idx_out:
            indexes.append(idx_out)

    summary = build_summary(indexes)

    result = {
        'generated_at': _fmt_date(pd.Timestamp.now()),
        'desc': '手续费+滑点成本压力测试:毛收益 vs 净收益对比(top10策略/指数 × 3成本档 × 2窗口)',
        'initial_capital': INITIAL_CAPITAL,
        'cost_presets': COST_PRESETS,
        'windows': WINDOWS,
        'top_n': TOP_N,
        'indexes': indexes,
        'summary': summary,
    }

    # 输出(任务约束:仅 static-site/data/)
    out_path = os.path.join(BASE, 'static-site', 'data', 'lab_cost_compare.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(out_path) / 1024
    print(f'[output] {out_path} ({size_kb:.1f} KB)')

    # 打印汇总
    print('\n=== 汇总: 各指数 top10 平均衰减(full_in all, 低成本档万3+千1) ===')
    for bi in summary['by_index']:
        print(f"  {bi['index_id']:8s} {bi['index_name']:8s} avg_decay={bi['avg_low_decay_ratio']}%% "
              f"(严苛档={bi['avg_high_decay_ratio']}%%) n={bi['n_pairs']}")
    print(f"\n毛收益>0配对: {summary['positive_pairs']}个, "
          f"低成本后仍盈利: {summary['still_positive_after_low_cost']}个 "
          f"(存活率 {summary['survival_rate_pct']}%)")
    print('\n最敏感(低成本衰减最严重,仅毛收益>0):')
    for m in summary['most_sensitive_low_cost'][:5]:
        print(f"  {m['pair_id']:46s} {m['index_name']:8s} gross={m['gross_ret']:+9.1f}% "
              f"low={m['low_ret']:+9.1f}% dec={m['low_decay_ratio']}%% n={m['n_trades']}")
    print('\n最稳健(低成本衰减最小):')
    for m in summary['most_robust_low_cost'][:5]:
        print(f"  {m['pair_id']:46s} {m['index_name']:8s} gross={m['gross_ret']:+9.1f}% "
              f"low={m['low_ret']:+9.1f}% dec={m['low_decay_ratio']}%% n={m['n_trades']}")

    elapsed = pd.Timestamp.now() - total_start
    print(f'\n=== 完成,总耗时 {elapsed.total_seconds():.1f}s ===')


if __name__ == '__main__':
    main()
