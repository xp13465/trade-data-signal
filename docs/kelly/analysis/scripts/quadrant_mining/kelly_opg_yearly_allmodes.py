# -*- coding: utf-8 -*-
"""K2C5 港股追涨剔除边际全模式按年分解(v1.0.0 口径, 9模式 A-I)
目的: 派单「K2C5 港股追涨剔除边际完整矩阵」——每个交易方法(A-I)各自按年(2011-2026)的剔除边际净利 Δ,
      以及每个方法 all/y1 汇总。回答「K2C5 剔除在哪个模式是正贡献/负贡献、是否多年稳定还是单年主导」。
口径: 测试基准 = v1.0.0 推荐最优组合(§5.4):
      AI宏4+3+1(排除Special熊/n2NovSpecialIndustry/janMidRating/janMidSpecial/r7MayReinforced/excludeAuxCross/greedy15)
      + 每日资金池等分(每笔=10000/当日保留数) + positionCap K=1
      + G=13万 P≤3d「先卖年轻仓」b0 可操作口径(超仓先卖持有≤3天年轻仓, 无年轻仓才卖最老, 强平记0利)
      + H=满仓不买@7万 / I=满仓不买@15万(手段A, 无强平)
      + A-F = 每日池+top-K 裸(峰持仓≤20万天然可操作)
      仿真内核与前端 lab.js _kellyAihlineP3dCap/_kellyAihlineHoldCap node 逐位对齐。
      K2C5 剔除键 = signal∈{buy_special,buy_backup} 且 市场=港股(mkt=hk), 共 159 基笔。
      剔除边际 Δ = 剔除后该年净利 - 基线该年净利(按 buy_date 年份聚合)。
      基线校验: G all 净利 +205,746 / 158.27% 必须复现(opg-data baseline 一致), 复现不上就停。
输入: static-site/data/signal_kelly_trades.json (2026-08-15 19:08 批, generated_at)
依赖: kelly_opg_engine.py(OpgEngine/p3d_cap/hold_cap/OPG_STRATS/MODES/load_trades/AI_MACRO)
输出: 打印 9模式×16年 Δ 矩阵 + all/y1 汇总 + 正负年份统计;
      json -> docs/kelly/analysis/data/kelly-k2c5-mode-yearly.json
复现: python3 docs/kelly/analysis/scripts/quadrant_mining/kelly_opg_yearly_allmodes.py
"""
import sys, os, json
from collections import defaultdict

_THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS)
_REPO = os.path.abspath(os.path.join(_THIS, '..', '..', '..', '..', '..'))
sys.path.insert(0, _REPO)

from kelly_opg_engine import (OpgEngine, MODES, load_trades, AI_MACRO, p3d_cap, hold_cap, OPG_STRATS)

_Y1_CUTOFF = '20250815'  # period_cutoffs.y1, buy_date >= 此日期计入 y1


def mode_yearly_profit(mode, exclude_keys=None, cutoff='0'):
    """单模式按年净利: A-F 直接聚合 recomputed; G/H/I 先做 cap 仿真再按 buy_date 年聚合。
    cutoff 非 '0' 时只统计 buy_date >= cutoff 的交易(用于 y1)。"""
    rec = oeng._mode_recomputed(mode, AI_MACRO, exclude_keys)
    if cutoff != '0':
        rec = [t for t in rec if t['buy_date'] >= cutoff]
    if mode in OPG_STRATS:
        kind, cap, model = OPG_STRATS[mode]
        kt, _ = p3d_cap(rec, cap, model) if kind == 'p3d' else hold_cap(rec, cap)
    else:
        kt = rec
    ymap = defaultdict(float)
    for k in kt:
        ymap[k['buy_date'][0:4]] += k['profit']
    return dict(ymap)


def excl_keys(pred):
    cache = {}
    ks = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(oeng.attr_of(t, cache)):
                ks.add(eng.base_key(t))
    return ks


if __name__ == '__main__':
    oeng = OpgEngine(load_trades())
    eng = oeng.eng

    # --- 0) 基线校验: G all 净利必须复现 +205,746 ---
    base_g = oeng.compute_opg(AI_MACRO)['all']['G']
    assert abs(base_g['total_profit'] - 205745.9424) < 1, f"G baseline 复现失败: {base_g['total_profit']}"
    print(f"[校验] G all 基线复现: 净利={base_g['total_profit']:+,.0f} 收益={base_g['return_pct_max_holding']:.2f}% 峰持仓={base_g['max_concurrent_capital']/10000:.1f}万")

    # --- 1) K2C5 剔除键 ---
    ks = excl_keys(lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk')
    print(f"[K2C5] 剔除基笔数 n={len(ks)} (opg-data candidates.n=159 应一致)")
    assert len(ks) == 159, f"K2C5 n 不一致: {len(ks)} != 159"

    years = [str(y) for y in range(2011, 2027)]
    matrix = {}   # mode -> {year: delta}
    baseline_y = {}  # mode -> {year: profit}
    summary = {}
    for mode in MODES:
        base_all = mode_yearly_profit(mode, None, '0')
        excl_all = mode_yearly_profit(mode, ks, '0')
        base_y1 = mode_yearly_profit(mode, None, _Y1_CUTOFF)
        excl_y1 = mode_yearly_profit(mode, ks, _Y1_CUTOFF)
        delta = {y: round(excl_all.get(y, 0.0) - base_all.get(y, 0.0), 2) for y in years}
        matrix[mode] = delta
        baseline_y[mode] = {y: round(base_all.get(y, 0.0), 2) for y in years}
        pos_y = [y for y in years if delta[y] > 0]
        neg_y = [y for y in years if delta[y] < 0]
        zero_y = [y for y in years if delta[y] == 0]
        summary[mode] = {
            'all_delta': round(sum(delta.values()), 2),
            'y1_delta': round(sum(excl_y1.values()) - sum(base_y1.values()), 2),
            'n_pos_years': len(pos_y), 'pos_years': pos_y,
            'n_neg_years': len(neg_y), 'neg_years': neg_y,
            'n_zero_years': len(zero_y), 'zero_years': zero_y,
            'pos_sum': round(sum(delta[y] for y in pos_y), 2),
            'neg_sum': round(sum(delta[y] for y in neg_y), 2),
        }

    # --- 2) 打印矩阵 ---
    print("\n=== K2C5 港股追涨剔除边际 Δ(全模式按年, v1.0.0 可操作口径) ===")
    hdr = f"{'年':<5}" + "".join(f"{m:>9}" for m in MODES)
    print(hdr)
    for y in years:
        row = f"{y:<5}" + "".join(f"{matrix[m][y]:>+9,.0f}" for m in MODES)
        print(row)
    row_all = f"{'all':<5}" + "".join(f"{summary[m]['all_delta']:>+9,.0f}" for m in MODES)
    print(row_all)
    row_y1 = f"{'y1':<5}" + "".join(f"{summary[m]['y1_delta']:>+9,.0f}" for m in MODES)
    print(row_y1)

    print("\n=== 每模式读法(正/负/零年份数 + 正负金额合计) ===")
    for m in MODES:
        s = summary[m]
        print(f"{m}: all={s['all_delta']:+,.0f} y1={s['y1_delta']:+,.0f} | 正{s['n_pos_years']}年({','.join(s['pos_years'])} +{s['pos_sum']:,.0f}) 负{s['n_neg_years']}年({','.join(s['neg_years'])} {s['neg_sum']:,.0f}) 零{s['n_zero_years']}年")

    # --- 3) 落 json ---
    out = {
        'data_version': '2026-08-15 19:08',
        'basis': 'v1.0.0: AI宏4+3+1 + 每日池等分 + K=1 + G=13万P≤3d b0 / H=满仓不买@7万 / I=满仓不买@15万 / A-F=每日池+top-K',
        'k2c5_key': 'signal in (buy_special,buy_backup) and mkt=hk',
        'k2c5_n': len(ks),
        'y1_cutoff': _Y1_CUTOFF,
        'years': years,
        'yearly_delta': matrix,
        'yearly_baseline_profit': baseline_y,
        'summary': summary,
    }
    out_path = os.path.join(os.path.dirname(_THIS), '..', 'data', 'kelly-k2c5-mode-yearly.json')
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n[json] -> {out_path}")
