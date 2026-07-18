#!/usr/bin/env python3
"""策略实验室多空对称性测试 -- 做多(buy->sell) vs 做空(sell->buy)镜像对比

复用 lab_simulate.py 引擎(含新增 simulate_short 做空镜像函数)。对每个指数按 full_in
全历史 total_ret 取 top N 配对，分别跑：
  - long:  simulate_full_in(buy_mask, sell_mask)  买信号开多,卖信号平多
  - short: simulate_short(buy_mask, sell_mask)     卖信号开空,买信号平空

对称性度量：
  - symmetry_gap = long_ret + short_ret  (对称市场=0; >0=做多优势/做空劣势=A股长牛漂移)
  - symmetry_ratio = short_ret / long_ret (理想=-1; 越接近 0 或正值=不对称越严重)
  - long_short_both_pos: 做多做空同时盈利(趋势型,买卖信号在两端都踩对)
  - long_pos_short_neg:  做多盈利做空亏损(典型长牛漂移,卖信号不能反手做空)

输出:
  static-site/data/lab_short_symmetry.json (前端可读)

结论预期：A股长期向上漂移，做多结构性占优，做空普遍亏损，卖信号不具备对称的做空能力
(即卖信号只适合止盈多头，不适合反手开空)。
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
    load_index_data, simulate_full_in, simulate_short, _build_stats,
    _fmt_date, INITIAL_CAPITAL, SIM_INDEXES,
)

TOP_N = 8
LAB_DIR = os.path.join(BASE, 'static-site', 'data', 'lab')


def _symmetry_ratio(short_ret, long_ret):
    """short_ret/long_ret。long_ret 接近 0 返回 None。"""
    if abs(long_ret) < 1e-9:
        return None
    return round(short_ret / long_ret, 3)


def _window_start(df, last_date):
    """全历史窗口。"""
    return None, None


def run_index(iid, iname):
    """单指数：读 stats.json 取 topN，跑 long vs short 对比。"""
    stats_path = os.path.join(LAB_DIR, f'lab_sim_{iid}_stats.json')
    if not os.path.exists(stats_path):
        print(f'  SKIP {iid}: 无 stats.json')
        return None
    with open(stats_path, encoding='utf-8') as f:
        stats = json.load(f)

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

    print(f'\n[{iid}] {iname} top{TOP_N} long vs short:')
    df = load_index_data(iid)
    if df is None:
        print(f'  SKIP {iid}: 无法加载数据')
        return None
    last_date = df.index[-1]
    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)

    out_pairs = []
    for rank, (pid, long_ret_prod, n_prod) in enumerate(top, 1):
        buy_key, sell_key = pid.split('|', 1)
        bm = buy_signals.get(buy_key)
        sm = sell_signals.get(sell_key)
        if bm is None or sm is None:
            print(f'    SKIP {pid}: 信号缺失')
            continue

        # 做多
        r_long = simulate_full_in(df, bm, sm)
        st_long = _build_stats(r_long['trades'], r_long['final_total'], last_date,
                               r_long['equity_curve'], years=None)
        # 做空
        r_short = simulate_short(df, bm, sm)
        st_short = _build_stats(r_short['trades'], r_short['final_total'], last_date,
                                r_short['equity_curve'], years=None)

        long_ret = float(st_long['total_ret'])
        short_ret = float(st_short['total_ret'])
        gap = round(long_ret + short_ret, 2)
        ratio = _symmetry_ratio(short_ret, long_ret)
        both_pos = bool(long_ret > 0 and short_ret > 0)
        long_pos_short_neg = bool(long_ret > 0 and short_ret < 0)

        pair_out = {
            'rank': rank,
            'pair_id': pid,
            'buy_key': buy_key,
            'sell_key': sell_key,
            'long': {
                'total_ret': long_ret,
                'annual_ret': float(st_long['annual_ret']),
                'max_drawdown': float(st_long['max_drawdown']),
                'win_rate': float(st_long['win_rate']),
                'n_trades': int(st_long['n_trades']),
                'final_total': float(st_long['final_total']),
            },
            'short': {
                'total_ret': short_ret,
                'annual_ret': float(st_short['annual_ret']),
                'max_drawdown': float(st_short['max_drawdown']),
                'win_rate': float(st_short['win_rate']),
                'n_trades': int(st_short['n_trades']),
                'final_total': float(st_short['final_total']),
            },
            'symmetry_gap': gap,
            'symmetry_ratio': ratio,
            'both_positive': both_pos,
            'long_pos_short_neg': long_pos_short_neg,
        }
        out_pairs.append(pair_out)
        print(f'    {pid:46s} long={long_ret:+9.1f}% short={short_ret:+10.1f}% '
              f'gap={gap:+9.1f} ratio={ratio}')

    return {'index_id': iid, 'index_name': iname, 'pairs': out_pairs}


def build_summary(indexes):
    """跨指数汇总：平均 symmetry_gap，做多占优比例，做空盈利比例。"""
    records = []
    for idx in indexes:
        if not idx:
            continue
        for p in idx['pairs']:
            records.append({
                'index_id': idx['index_id'],
                'index_name': idx['index_name'],
                'pair_id': p['pair_id'],
                'long_ret': p['long']['total_ret'],
                'short_ret': p['short']['total_ret'],
                'symmetry_gap': p['symmetry_gap'],
                'symmetry_ratio': p['symmetry_ratio'],
                'both_positive': p['both_positive'],
                'long_pos_short_neg': p['long_pos_short_neg'],
            })

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    n = len(records)
    long_pos = sum(1 for r in records if r['long_ret'] > 0)
    short_pos = sum(1 for r in records if r['short_ret'] > 0)
    long_pos_short_neg = sum(1 for r in records if r['long_pos_short_neg'])
    both_pos = sum(1 for r in records if r['both_positive'])

    by_index = []
    for iid in sorted({r['index_id'] for r in records}):
        rs = [r for r in records if r['index_id'] == iid]
        by_index.append({
            'index_id': iid,
            'index_name': rs[0]['index_name'] if rs else iid,
            'avg_long_ret': avg([r['long_ret'] for r in rs]),
            'avg_short_ret': avg([r['short_ret'] for r in rs]),
            'avg_symmetry_gap': avg([r['symmetry_gap'] for r in rs]),
            'avg_symmetry_ratio': avg([r['symmetry_ratio'] for r in rs]),
            'long_positive_pct': round(long_pos_count(rs) / len(rs) * 100, 1) if rs else 0,
            'short_positive_pct': round(short_pos_count(rs) / len(rs) * 100, 1) if rs else 0,
            'n_pairs': len(rs),
        })

    # 最不对称（gap 最大=做多最占优）和最对称（gap 最接近 0）
    gap_sorted = sorted(records, key=lambda r: r['symmetry_gap'], reverse=True)
    most_asymmetric = [{
        'pair_id': r['pair_id'], 'index_name': r['index_name'],
        'long_ret': r['long_ret'], 'short_ret': r['short_ret'],
        'symmetry_gap': r['symmetry_gap'], 'symmetry_ratio': r['symmetry_ratio'],
    } for r in gap_sorted[:8]]
    most_symmetric = [{
        'pair_id': r['pair_id'], 'index_name': r['index_name'],
        'long_ret': r['long_ret'], 'short_ret': r['short_ret'],
        'symmetry_gap': r['symmetry_gap'], 'symmetry_ratio': r['symmetry_ratio'],
    } for r in sorted(records, key=lambda r: abs(r['symmetry_gap']))[:8]]

    return {
        'by_index': by_index,
        'most_asymmetric': most_asymmetric,
        'most_symmetric': most_symmetric,
        'total_pairs': n,
        'long_positive': long_pos,
        'short_positive': short_pos,
        'long_positive_pct': round(long_pos / n * 100, 1) if n else 0,
        'short_positive_pct': round(short_pos / n * 100, 1) if n else 0,
        'long_pos_short_neg': long_pos_short_neg,
        'both_positive': both_pos,
        'avg_symmetry_gap': avg([r['symmetry_gap'] for r in records]),
        'avg_symmetry_ratio': avg([r['symmetry_ratio'] for r in records]),
    }


def long_pos_count(rs):
    return sum(1 for r in rs if r['long_ret'] > 0)


def short_pos_count(rs):
    return sum(1 for r in rs if r['short_ret'] > 0)


def main():
    print('=== 策略实验室多空对称性测试 (做多 vs 做空镜像) ===')
    print(f'每指数 top{TOP_N} 配对, full_in 全历史窗口')
    total_start = pd.Timestamp.now()

    indexes = []
    for iid, iname in SIM_INDEXES:
        idx_out = run_index(iid, iname)
        if idx_out:
            indexes.append(idx_out)

    summary = build_summary(indexes)

    result = {
        'generated_at': _fmt_date(pd.Timestamp.now()),
        'desc': '多空对称性:做多(buy->sell) vs 做空(sell->buy)镜像对比(top8策略/指数)',
        'initial_capital': INITIAL_CAPITAL,
        'top_n': TOP_N,
        'indexes': indexes,
        'summary': summary,
    }

    out_path = os.path.join(BASE, 'static-site', 'data', 'lab_short_symmetry.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(out_path) / 1024
    print(f'[output] {out_path} ({size_kb:.1f} KB)')

    print('\n=== 汇总 ===')
    print(f"配对总数: {summary['total_pairs']}, "
          f"做多盈利: {summary['long_positive']}({summary['long_positive_pct']}%), "
          f"做空盈利: {summary['short_positive']}({summary['short_positive_pct']}%)")
    print(f"做多盈做空亏: {summary['long_pos_short_neg']}, 两端皆盈: {summary['both_positive']}")
    print(f"平均 symmetry_gap: {summary['avg_symmetry_gap']} (正值=做多占优/做空劣势)")
    print(f"平均 symmetry_ratio: {summary['avg_symmetry_ratio']} (理想=-1)")
    print('\n各指数:')
    for bi in summary['by_index']:
        print(f"  {bi['index_id']:8s} long_avg={bi['avg_long_ret']}% short_avg={bi['avg_short_ret']}% "
              f"gap={bi['avg_symmetry_gap']} ratio={bi['avg_symmetry_ratio']} "
              f"short_pos%={bi['short_positive_pct']}")

    elapsed = pd.Timestamp.now() - total_start
    print(f'\n=== 完成,总耗时 {elapsed.total_seconds():.1f}s ===')


if __name__ == '__main__':
    main()
