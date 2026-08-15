# -*- coding: utf-8 -*-
"""K2C5 港股追涨剔除 × 核心3键 全组合交互穷举 (2026-08-15)
目的: 补 K2C5(剔除 signal∈{buy_special,buy_backup}×港股)与核心3键(r7MayReinforced/excludeAuxCross/greedy15)
      的「全组合交互穷举」验证——确认 8键(7键+K2C5)是否全局最优、K2C5 与各核心键有无交互冲突、
      有无 K2C5 取代某核心键后更优。基础4(excludeSpecialBear/n2NovSpecialIndustry/janMidRating/janMidSpecial)固定开
      (理由=穷举v2 已定死基础4, 本次只交互核心3+K2C5)。
口径: v1.0.0 推荐最优组合(§5.4): 基础4+核心3 + positionCap K1 每日资金池等分 + K=1
      + G 用 13万 P≤3d「先卖年轻仓」b0(保守权威口径, 前端 b1 附列) + H=满仓不买@7万 + I=满仓不买@15万 + A-F=每日池+top-K
      K2C5 剔除键 = signal∈{buy_special,buy_backup} × 市场=港股(mkt=hk), 159 基笔(本批)
      收益率口径 = 峰值资金收益率 = 最终盈亏 / 峰值同时持仓资金 × 100(对齐前端 return_pct_max_holding)
输入: static-site/data/signal_kelly_trades.json (2026-08-15 21:41 批)
依赖: 同目录 kelly_engine.py / kelly_opg_engine.py(副本, 原版 docs/kelly/analysis/scripts/quadrant_mining/)
输出: ../data/kelly-k2c5-exhaust-interaction.json (16组合全模式净利+收益率 + K2C5边际 + 核心键边际 + 替代对比 + 最优判定)
复现: python3 kelly_k2c5_exhaust_interaction.py
"""
import sys, os, json, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'kelly-k2c5-exhaust-interaction.json')

# 基础4 固定开
BASE4 = dict(excludeSpecialBear=True, n2NovSpecialIndustry=True, janMidRating=True, janMidSpecial=True)
# 核心3 交互键
CORE3 = ['r7MayReinforced', 'excludeAuxCross', 'greedy15']
CORE3_LABEL = {'r7MayReinforced': 'r7', 'excludeAuxCross': 'aux', 'greedy15': 'g15'}

G_CAP, H_CAP, I_CAP = 130000, 70000, 150000

def mode_stats_any(mode, rec, g_model):
    """套模式可操作口径: A-F 裸 / G=P3d13万(g_model b0/b1) / H=hold7万 / I=hold15万"""
    if mode == 'G':
        kt, peak = p3d_cap(rec, G_CAP, model=g_model)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp*10000)/10000,
                    return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak>0 else 0,
                    max_concurrent_capital=peak), peak
    if mode in ('H', 'I'):
        cap = H_CAP if mode == 'H' else I_CAP
        kt, peak = hold_cap(rec, cap)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp*10000)/10000,
                    return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak>0 else 0,
                    max_concurrent_capital=peak), peak
    tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in rec]
    st = eng.compute_stats(tuples)
    return st, st['max_concurrent_capital']

def compute_combo(filters, exclude_keys, g_model='b0'):
    """组合全模式 all 周期 stats + G b1 附列"""
    cutoffs = eng.period_cutoffs
    rec_by_mode = {m: oeng._mode_recomputed(m, filters, exclude_keys) for m in MODES}
    res = {}
    for pk in ('all', 'y1'):
        cutoff = cutoffs.get(pk, '0')
        res[pk] = {}
        for m in MODES:
            rp = [t for t in rec_by_mode[m] if cutoff == '0' or t['buy_date'] >= cutoff]
            st, peak = mode_stats_any(m, rp, g_model)
            res[pk][m] = dict(st, _peak=peak)
        # G b1 附列
        rp_g = [t for t in rec_by_mode['G'] if cutoff == '0' or t['buy_date'] >= cutoff]
        st1, peak1 = mode_stats_any('G', rp_g, 'b1')
        res[pk]['G_b1'] = dict(st1, _peak=peak1)
    return res

def combo_name(core_on, k2c5):
    s = '+'.join([CORE3_LABEL[k] for k in CORE3 if k in core_on]) or '0'
    if k2c5: s += '+k2'
    return s

if __name__ == '__main__':
    td = load_trades()
    oeng = OpgEngine(td)
    eng = oeng.eng
    k2 = oeng.excl_keys(lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk')
    print('K2C5 剔除基笔 n =', len(k2), flush=True)
    print('数据批:', td.get('generated_at'), flush=True)

    # ===== 0) 基线复现断言: v1.0.0 7键 all G b0 = +203,594 =====
    base7 = compute_combo(AI_MACRO, None, 'b0')
    print('7键基线 G b0 all = %+0.2f' % base7['all']['G']['total_profit'], flush=True)
    assert abs(base7['all']['G']['total_profit'] - 203594.19) < 5, 'G b0 基线未复现(§5.4③), 停止'

    # ===== 1) 16 组合穷举: 核心3 8 种 × K2C5 2 种 =====
    combos = {}
    core_subsets = []
    for r in range(0, len(CORE3) + 1):
        for combo in itertools.combinations(CORE3, r):
            core_subsets.append(set(combo))
    for k2c5 in (False, True):
        for core_on in core_subsets:
            filters = dict(BASE4)
            for k in CORE3:
                filters[k] = k in core_on
            filters['positionCap'] = True
            filters['positionCapK'] = 1
            excl = k2 if k2c5 else None
            name = combo_name(core_on, k2c5)
            st = compute_combo(filters, excl, 'b0')
            combos[name] = {
                'core3_on': sorted(core_on), 'k2c5': k2c5,
                'all': {m: {'net': st['all'][m]['total_profit'],
                            'ret_pct': st['all'][m]['return_pct_max_holding'],
                            'n': st['all'][m]['n'], 'peak': st['all'][m]['_peak']} for m in MODES},
                'all_G_b1_net': st['all']['G_b1']['total_profit'],
                'all_G_b1_ret_pct': st['all']['G_b1']['return_pct_max_holding'],
                'y1': {m: st['y1'][m]['total_profit'] for m in MODES},
            }
    print('16 组合穷举 done.', flush=True)

    # ===== 2) 关键汇总表 =====
    # A/F/G(b0) 净利 + 收益率
    print('\n===== 16 组合 all 周期 A/F/G 净利+收益率(b0, G 附 b1) =====')
    print(f'{"组合":<18} {"A净利":>9} {"A收益":>7} {"F净利":>9} {"F收益":>7} {"G净利b0":>9} {"G收益b0":>7} {"G净利b1":>9} {"G收益b1":>7}')
    for name, c in sorted(combos.items(), key=lambda x: -x[1]['all']['A']['net']):
        a, f, g = c['all']['A'], c['all']['F'], c['all']['G']
        print(f'{name:<18} {a["net"]:>+9,.0f} {a["ret_pct"]:>6.2f}% {f["net"]:>+9,.0f} {f["ret_pct"]:>6.2f}% {g["net"]:>+9,.0f} {g["ret_pct"]:>6.2f}% {c["all_G_b1_net"]:>+9,.0f} {c["all_G_b1_ret_pct"]:>6.2f}%')

    # ===== 3) K2C5 边际(同核心3下 on-off) =====
    print('\n===== K2C5 边际 = 同核心3组合 K2C5 on - off(all, b0) =====')
    print(f'{"核心3":<12} {"AΔ":>8} {"FΔ":>8} {"GΔb0":>8} {"GΔb1":>8} {"HΔ":>8} {"IΔ":>8} {"合计Δ(非G)":>10}')
    for core_on in sorted(core_subsets, key=lambda s: (len(s), sorted(s))):
        off = combo_name(core_on, False)
        on = combo_name(core_on, True)
        co, cn = combos[off], combos[on]
        da = cn['all']['A']['net'] - co['all']['A']['net']
        df = cn['all']['F']['net'] - co['all']['F']['net']
        dg = cn['all']['G']['net'] - co['all']['G']['net']
        dg1 = cn['all_G_b1_net'] - co['all_G_b1_net']
        dh = cn['all']['H']['net'] - co['all']['H']['net']
        di = cn['all']['I']['net'] - co['all']['I']['net']
        non_g = sum(cn['all'][m]['net'] - co['all'][m]['net'] for m in MODES if m != 'G')
        label = '+'.join([CORE3_LABEL[k] for k in CORE3 if k in core_on]) or '0'
        print(f'{label:<12} {da:>+8,.0f} {df:>+8,.0f} {dg:>+8,.0f} {dg1:>+8,.0f} {dh:>+8,.0f} {di:>+8,.0f} {non_g:>+10,.0f}')

    # ===== 4) 核心键边际(同 K2C5 下, 各核心键 on-off; 其它核心键固定 off) =====
    print('\n===== 核心键单键边际(其它核心键 off): K2C5 off vs on 对比 =====')
    print(f'{"键":<6} {"K2C5":<5} {"AΔ":>8} {"FΔ":>8} {"GΔb0":>8} {"GΔb1":>8} {"HΔ":>8} {"IΔ":>8}')
    for k in CORE3:
        for k2c5 in (False, True):
            core_off = set()
            core_on = {k}
            off_n = combo_name(core_off, k2c5)
            on_n = combo_name(core_on, k2c5)
            co, cn = combos[off_n], combos[on_n]
            da = cn['all']['A']['net'] - co['all']['A']['net']
            df = cn['all']['F']['net'] - co['all']['F']['net']
            dg = cn['all']['G']['net'] - co['all']['G']['net']
            dg1 = cn['all_G_b1_net'] - co['all_G_b1_net']
            dh = cn['all']['H']['net'] - co['all']['H']['net']
            di = cn['all']['I']['net'] - co['all']['I']['net']
            print(f'{CORE3_LABEL[k]:<6} {"on" if k2c5 else "off":<5} {da:>+8,.0f} {df:>+8,.0f} {dg:>+8,.0f} {dg1:>+8,.0f} {dh:>+8,.0f} {di:>+8,.0f}')

    # ===== 5) 替代对比: K2C5 替代某核心键 vs 7键基线 =====
    print('\n===== 替代对比(all, b0): 7键基线 vs K2C5替代某核心键 =====')
    base = combos[combo_name(set(CORE3), False)]  # 7键
    print(f'7键基线: A={base["all"]["A"]["net"]:+,.0f} F={base["all"]["F"]["net"]:+,.0f} G={base["all"]["G"]["net"]:+,.0f} Gb1={base["all_G_b1_net"]:+,.0f} H={base["all"]["H"]["net"]:+,.0f} I={base["all"]["I"]["net"]:+,.0f}')
    for drop in CORE3:
        keep = set(CORE3) - {drop}
        name = combo_name(keep, True)  # K2C5 on, 缺 drop
        c = combos[name]
        print(f'K2C5替代{drop}: A={c["all"]["A"]["net"]:+,.0f} F={c["all"]["F"]["net"]:+,.0f} G={c["all"]["G"]["net"]:+,.0f} Gb1={c["all_G_b1_net"]:+,.0f} H={c["all"]["H"]["net"]:+,.0f} I={c["all"]["I"]["net"]:+,.0f}')

    # ===== 6) 8键全开 vs 各组合 最优判定 =====
    full8 = combo_name(set(CORE3), True)
    c8 = combos[full8]
    print('\n===== 最优判定(all, b0) =====')
    for m in ('A', 'F', 'G', 'H', 'I'):
        best_name = max(combos, key=lambda x: combos[x]['all'][m]['net'])
        best = combos[best_name]
        is8 = best_name == full8
        print(f'{m}: 最优={best_name} 净利={best["all"][m]["net"]:+,.0f} 收益={best["all"][m]["ret_pct"]:.2f}%  (8键={c8["all"][m]["net"]:+,.0f}/{c8["all"][m]["ret_pct"]:.2f}%) {"==8键" if is8 else ""}')
    # 合计净利(9模式, 非G; G 单独因 b0/b1 口径)
    best_sum = max(combos, key=lambda x: sum(combos[x]['all'][m]['net'] for m in MODES if m != 'G'))
    print(f'9模式合计(含G b0): 最优={best_sum} 合计={sum(combos[best_sum]["all"][m]["net"] for m in MODES):+,.0f}')
    best_sum8 = sum(c8['all'][m]['net'] for m in MODES)
    print(f'8键全开 9模式合计(含G b0) = {best_sum8:+,.0f}')

    out = {
        'data_batch': td.get('generated_at'),
        'basis': 'v1.0.0: 基础4(excludeSpecialBear/n2NovSpecialIndustry/janMidRating/janMidSpecial)+核心3+positionCap K1每日池等分, G=13万P≤3d(b0权威/b1附列), H=7万, I=15万, A-F=每日池+top-K',
        'k2c5_excl_n': len(k2),
        'base7_verify': {'G_b0_all': base7['all']['G']['total_profit'], 'A_all': base7['all']['A']['total_profit'],
                         'F_all': base7['all']['F']['total_profit'], 'H_all': base7['all']['H']['total_profit'],
                         'I_all': base7['all']['I']['total_profit']},
        'combos': combos,
    }
    with open(OUT, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\nwritten:', OUT)
