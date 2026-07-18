#!/usr/bin/env python3
"""策略实验室信号叠加消融测试 -- 6 硬编码融合策略的 N-1 子集贡献分析

对每个硬编码融合策略 F（多信号同日 AND 取交集），生成 N-1 子集（逐一去掉一个组件），
对比 full fusion vs 各 ablated 子集的回测 stats，量化每个组件的贡献：

  - contribution_i = stats(full) - stats(ablated without component_i)
    正值=该组件提升收益(信号叠加有效)；负值=该组件拖累(过滤过严/漏信号)
  - 单组件基线：2 组件融合去掉一个=单信号，直接对比融合 vs 单信号增益

6 硬编码融合（fusion_signals.HARDCODED_FUSIONS）：
  - F_D1_S1_MACD (3组件,卖): D1_high20_drop5 & MA60_bull & MACD_below_signal
  - F_D1_S1     (2组件,卖): D1_high20_drop5 & MA60_bull
  - F_B1_RSI40  (2组件,买): BB_lower_revert & RSI_cross_40
  - F_B1_rebound2pct(2,买): BB_lower_revert & close_above_bl_2pct
  - F_C1_MACD_golden(2,买): C1_RSI30 & MACD_golden
  - F_D1_MA_death(2,卖): D1_high20_drop5 & MA_death_5_20

不动 backtest_strategies.py，只 import 公开 helper(gen_buy/sell_signals) +
fusion_signals 的 _gen_filter_masks / HARDCODED_FUSIONS。

输出:
  static-site/data/lab_ablation.json
"""
import json
import os
import sys
from itertools import combinations

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(BASE, 'a-stock-data'))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from backtest_strategies import gen_buy_signals, gen_sell_signals
from fusion_signals import _gen_filter_masks, HARDCODED_FUSIONS, REF_BUY, REF_SELL
from lab_simulate import (
    load_index_data, simulate_full_in, _build_stats,
    _fmt_date, INITIAL_CAPITAL,
)

# 3 代表指数（与蒙特卡洛同，兼顾大盘/成长/科创，控制运行时间）
ABLATION_INDEXES = [
    ('sh',    '上证指数'),
    ('hs300', '沪深300'),
    ('cyb',   '创业板指'),
]


def _mask(m):
    return m.fillna(False).astype(bool) if m is not None else None


def _and_masks(masks):
    """对一组 bool Series 取交集(AND)，返回 bool Series。"""
    result = masks[0]
    for m in masks[1:]:
        result = result & m
    return result


def _run_sim(df, buy_mask, sell_mask, last_date):
    """跑 full_in 全历史回测，返回 stats dict。"""
    r = simulate_full_in(df, buy_mask, sell_mask, w_start=None)
    return _build_stats(r['trades'], r['final_total'], last_date,
                        r['equity_curve'], years=None)


def _stats_subset(stats):
    """提取关键指标子集。"""
    return {
        'total_ret': float(stats['total_ret']),
        'annual_ret': float(stats['annual_ret']),
        'max_drawdown': float(stats['max_drawdown']),
        'win_rate': float(stats['win_rate']),
        'n_trades': int(stats['n_trades']),
        'final_total': float(stats['final_total']),
    }


def run_ablation_index(iid, iname):
    """单指数：对 6 硬编码融合做消融。"""
    df = load_index_data(iid)
    if df is None:
        print(f'  SKIP {iid}: 无法加载数据')
        return None
    last_date = df.index[-1]

    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    filter_masks = _gen_filter_masks(df)
    all_masks = {**buy_signals, **sell_signals, **filter_masks}

    ref_buy_mask = _mask(buy_signals.get(REF_BUY))
    ref_sell_mask = _mask(sell_signals.get(REF_SELL))

    out_fusions = []
    for pair_id, side, fusion_keys, ref_side in HARDCODED_FUSIONS:
        comp_masks = []
        for k in fusion_keys:
            m = all_masks.get(k)
            if m is None:
                print(f'    SKIP {pair_id}: 组件 {k} 缺失')
                comp_masks = None
                break
            comp_masks.append(_mask(m))
        if comp_masks is None:
            continue

        full_mask = _and_masks(comp_masks)
        if not full_mask.any():
            print(f'    SKIP {pair_id}: full fusion 无信号')
            continue

        # 另一侧固定基线
        if side == 'buy':
            base_other = ref_sell_mask
            full_buy, full_sell = full_mask, base_other
        else:
            base_other = ref_buy_mask
            full_buy, full_sell = base_other, full_mask
        if base_other is None or not base_other.any():
            print(f'    SKIP {pair_id}: ref_side {ref_side} 无信号')
            continue

        # full fusion 回测
        full_stats = _run_sim(df, full_buy, full_sell, last_date)

        # N-1 ablated 子集
        ablations = []
        for drop_idx in range(len(fusion_keys)):
            kept_keys = [fusion_keys[i] for i in range(len(fusion_keys)) if i != drop_idx]
            kept_masks = [comp_masks[i] for i in range(len(fusion_keys)) if i != drop_idx]
            ablated_mask = _and_masks(kept_masks) if len(kept_masks) > 1 else kept_masks[0]
            if not ablated_mask.any():
                ablations.append({
                    'dropped': fusion_keys[drop_idx],
                    'kept': kept_keys,
                    'n_signals': 0,
                    'stats': None,
                    'ret_contribution': None,
                })
                continue
            if side == 'buy':
                ab_buy, ab_sell = ablated_mask, base_other
            else:
                ab_buy, ab_sell = base_other, ablated_mask
            ab_stats = _run_sim(df, ab_buy, ab_sell, last_date)
            ret_contrib = round(full_stats['total_ret'] - ab_stats['total_ret'], 2)
            ablations.append({
                'dropped': fusion_keys[drop_idx],
                'kept': kept_keys,
                'n_signals': int(ablated_mask.sum()),
                'stats': _stats_subset(ab_stats),
                'ret_contribution': ret_contrib,
            })

        fusion_out = {
            'pair_id': pair_id,
            'side': side,
            'components': fusion_keys,
            'ref_side': ref_side,
            'n_full_signals': int(full_mask.sum()),
            'full_stats': _stats_subset(full_stats),
            'ablations': ablations,
        }
        out_fusions.append(fusion_out)
        full_ret = full_stats['total_ret']
        contribs = [a['ret_contribution'] for a in ablations if a['ret_contribution'] is not None]
        print(f'    {pair_id:20s} full={full_ret:+8.1f}% n={int(full_mask.sum()):4d}  '
              f'contribs={[c for c in contribs]}')

    return {'index_id': iid, 'index_name': iname, 'fusions': out_fusions}


def build_summary(indexes):
    """跨指数汇总：各组件平均贡献，融合是否增益。"""
    # component -> list of ret_contribution across fusions/indices
    comp_contrib = {}
    fusion_gain = []  # (fusion, index, full_ret, best_single_ret, gain)
    for idx in indexes:
        if not idx:
            continue
        for f in idx['fusions']:
            full_ret = f['full_stats']['total_ret']
            # 2组件融合: ablated 即单信号基线,取最好的单信号作对比
            single_rets = [a['stats']['total_ret'] for a in f['ablations']
                           if a['stats'] is not None]
            best_single = max(single_rets) if single_rets else None
            gain = round(full_ret - best_single, 2) if best_single is not None else None
            fusion_gain.append({
                'fusion': f['pair_id'],
                'index_id': idx['index_id'],
                'full_ret': full_ret,
                'best_single_ret': best_single,
                'fusion_gain_over_best_single': gain,
            })
            for a in f['ablations']:
                if a['ret_contribution'] is not None:
                    comp_contrib.setdefault(a['dropped'], []).append(a['ret_contribution'])

    comp_summary = []
    for comp, vals in sorted(comp_contrib.items()):
        comp_summary.append({
            'component': comp,
            'avg_contribution': round(sum(vals) / len(vals), 2),
            'n_samples': len(vals),
            'positive_count': sum(1 for v in vals if v > 0),
            'positive_pct': round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1),
        })

    n_gain = sum(1 for g in fusion_gain if g['fusion_gain_over_best_single'] is not None
                 and g['fusion_gain_over_best_single'] > 0)
    n_total = sum(1 for g in fusion_gain if g['fusion_gain_over_best_single'] is not None)

    return {
        'component_contributions': comp_summary,
        'fusion_gain': fusion_gain,
        'fusion_gain_positive_pct': round(n_gain / n_total * 100, 1) if n_total else 0,
        'n_fusion_index_pairs': n_total,
    }


def main():
    print('=== 策略实验室信号叠加消融测试 (6硬编码融合 N-1 子集) ===')
    print(f'指数: {[i[0] for i in ABLATION_INDEXES]}')
    total_start = pd.Timestamp.now()

    indexes = []
    for iid, iname in ABLATION_INDEXES:
        idx_out = run_ablation_index(iid, iname)
        if idx_out:
            indexes.append(idx_out)

    summary = build_summary(indexes)

    result = {
        'generated_at': _fmt_date(pd.Timestamp.now()),
        'desc': '信号叠加消融:6硬编码融合策略的N-1子集贡献分析(逐一去组件对比)',
        'initial_capital': INITIAL_CAPITAL,
        'indexes': indexes,
        'summary': summary,
    }

    out_path = os.path.join(BASE, 'static-site', 'data', 'lab_ablation.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(out_path) / 1024
    print(f'[output] {out_path} ({size_kb:.1f} KB)')

    print('\n=== 汇总: 各组件平均贡献 ===')
    for c in summary['component_contributions']:
        print(f"  {c['component']:24s} avg_contrib={c['avg_contribution']:+8.2f} "
              f"positive={c['positive_pct']}% n={c['n_samples']}")
    n_gain_total = summary['n_fusion_index_pairs']
    n_gain_pos = sum(1 for g in summary['fusion_gain']
                     if g['fusion_gain_over_best_single'] is not None
                     and g['fusion_gain_over_best_single'] > 0)
    print(f"\n融合增益(优于最佳单信号): {summary['fusion_gain_positive_pct']}% "
          f"({n_gain_pos}/{n_gain_total})")
    print('\n各融合增益明细:')
    for g in summary['fusion_gain']:
        if g['fusion_gain_over_best_single'] is not None:
            print(f"  {g['fusion']:20s} {g['index_id']:6s} full={g['full_ret']:+8.1f}% "
                  f"best_single={g['best_single_ret']:+8.1f}% gain={g['fusion_gain_over_best_single']:+8.2f}")

    elapsed = pd.Timestamp.now() - total_start
    print(f'\n=== 完成,总耗时 {elapsed.total_seconds():.1f}s ===')


if __name__ == '__main__':
    main()
