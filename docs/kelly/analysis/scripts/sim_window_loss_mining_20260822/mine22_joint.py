# -*- coding: utf-8 -*-
"""二轮挖掘 补测⑦(2026-08-22 终轮):R2 三条(三轮替补族)并入 → N=14 → 2^14-1=16,383 全穷举。
R2 定义复用 round3 mine14_substitute_validate.py(9键边际已验:R2a +9,681 / R2b +8,254 / R2g +19,442):
  R2a = sig==buy & mktD==concept;R2b = sig==buy_special & mktD==global;
  R2g = rating=='low' & 月份∈{07,08,09} & track_score<75(空 ts 视为 999)。
新增: R2×11池 Jaccard 重合度矩阵(验证 sig×域类 与 宏观状态类 正交假设)。
排名: 效果8维 ε=1000 帕累托;三个代表位=全史王(ε前绝对值+ε后)/近端安全型/近端双正型;
前沿组补 K1-K4+五窗口+四熊市;R2 在最优组合 LOO。
口径纪律: 补位口径;9键锚点断言自检(+73,102.53)。
输出: data/mine22_joint.json
复现: python3 mine22_joint.py(依赖 mine10_features.json + mine20_pool.json + signal_kelly_trades.json)
"""
import os, sys, json, datetime
from itertools import combinations
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from mine18_detail import BEARS, FEATS_PATH
from mine17_modes import prep_mode
from mine21_bigtour import build_rules, max_dd

OUT_PATH = os.path.join(BASE, 'data', 'mine22_joint.json')

def build_r2(fIdx):
    mD = len(fIdx)
    iR = fIdx['rating']
    def r2a(t): return t[2] == 'buy' and (t[mD] or '') == 'concept'
    def r2b(t): return t[2] == 'buy_special' and (t[mD] or '') == 'global'
    def r2g(t):
        if t[iR] != 'low': return False
        if str(t[0])[4:6] not in ('07','08','09'): return False
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None,'') else 999.0
        return ts < 75
    return {'R2a': r2a, 'R2b': r2b, 'R2g': r2g}

def main():
    feats = json.load(open(FEATS_PATH))
    pool = json.load(open(POOL_PATH := os.path.join(BASE, 'data', 'mine20_pool.json')))
    codes11 = pool['pool_in']
    ALL = codes11 + ['R2a','R2b','R2g']
    print('联合池(14):', ALL)
    all_combos = [c for k in range(1, 15) for c in combinations(ALL, k)]
    print('子集数:', len(all_combos))

    mode_ctx = {}
    for m in ['A','B','C','D','E','F']:
        rows_m, fIdx_m = R.prepare_rows() if m == 'A' else prep_mode(m)
        R.init(rows_m, fIdx_m)
        rules_m = build_rules(feats, fIdx_m); rules_m.update(build_r2(fIdx_m))
        c1m = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx_m['market_tier']] or '') == '牛市·主升')
        hits_c1 = {R.base_key(t, fIdx_m) for t in rows_m if c1m(t)}
        hits = {c: {R.base_key(t, fIdx_m) for t in rows_m if rules_m[c](t)} for c in ALL}
        groups = {}
        for t in rows_m:
            groups.setdefault(str(t[0]), []).append((R.base_key(t, fIdx_m), t))
        for sd in groups:
            groups[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
        mode_ctx[m] = dict(rows=rows_m, fIdx=fIdx_m, hits=hits, hits_c1=hits_c1,
                           groups=groups, sds=sorted(groups))
        print(f'mode {m} 预建完成')

    def eval_subset(ctx, subset, K=1):
        blk = set(ctx['hits_c1'])
        for c in subset:
            blk |= ctx['hits'][c]
        sel = []
        for sd in ctx['sds']:
            n = 0
            for key, t in ctx['groups'][sd]:
                if key not in blk:
                    sel.append(t); n += 1
                    if n >= K: break
        return sel

    ctxA = mode_ctx['A']
    base9_A = eval_subset(ctxA, ())
    tot9 = R.stats_of(base9_A)['total']
    assert abs(tot9 - 73102.53) < 0.5, f'9键锚点不符: {tot9}'
    print(f'锚点自检 PASS: {tot9:+,.2f}')

    # R2 三条 vs9键边际复验(与 round3 报告数字对照)
    for c in ('R2a','R2b','R2g'):
        ns = eval_subset(ctxA, (c,))
        det = R.diff_detail(base9_A, ns)
        print(f'  {c} vs9键边际复验: {det["net_improve"]:+,.0f} (拦{det["blocked_n"]}/替{det["added_n"]})')

    # R2×11 Jaccard
    jac = {}
    hA = ctxA['hits']
    for rc in ('R2a','R2b','R2g'):
        for c in codes11:
            A_, B_ = hA[rc], hA[c]
            u = A_ | B_
            jac[f'{rc}~{c}'] = dict(inter=len(A_ & B_), union=len(u),
                                    jaccard=round(len(A_ & B_)/len(u), 3) if u else None,
                                    nR2=len(A_), n11=len(B_))
    r2_pair = {f'R2a~R2b': round(len(hA['R2a']&hA['R2b'])/max(len(hA['R2a']|hA['R2b']),1),3),
               'R2a~R2g': round(len(hA['R2a']&hA['R2g'])/max(len(hA['R2a']|hA['R2g']),1),3),
               'R2b~R2g': round(len(hA['R2b']&hA['R2g'])/max(len(hA['R2b']|hA['R2g']),1),3)}
    print('\n== R2×11 Jaccard(应≈0=正交)==')
    for k, v in jac.items():
        print('  %-10s 交%d 并%d J=%.3f' % (k, v['inter'], v['union'], v['jaccard']))
    print('  R2 内部:', r2_pair)

    dmax = max(str(t[0]) for t in ctxA['rows'])
    dd0 = datetime.date(int(dmax[:4]), int(dmax[4:6]), int(dmax[6:]))
    w1 = (dd0 - datetime.timedelta(days=365)).strftime('%Y%m%d')
    w3 = (dd0 - datetime.timedelta(days=1095)).strftime('%Y%m%d')
    st_base = R.stats_of(base9_A)
    mdd_base = max_dd(base9_A, ctxA['fIdx'])
    base_win = {lab: R.stats_of(R.window(base9_A, a, b))['total'] for lab, a, b in
                [('近1年',w1,None),('近3年',w3,None)] + [(lab,a,b) for lab,a,b in BEARS]}

    combos = []
    for idx, sub in enumerate(all_combos):
        ns_A = eval_subset(ctxA, sub)
        det = R.diff_detail(base9_A, ns_A)
        g = R.three_gates(base9_A, ns_A, det)
        st = R.stats_of(ns_A)
        mdd_new = max_dd(ns_A, ctxA['fIdx'])
        bears = {lab: round(R.stats_of(R.window(ns_A, a, b))['total'] - base_win[lab], 2) for lab, a, b in BEARS}
        nmodes = 1
        for m in ['B','C','D','E','F']:
            cm = mode_ctx[m]
            imp = R.stats_of(eval_subset(cm, sub))['total'] - R.stats_of(eval_subset(cm, ()))['total']
            nmodes += imp > 0
        ns_keys = {R.base_key(t, ctxA['fIdx']) for t in ns_A}
        nb_years = {}
        for t in base9_A:
            if R.base_key(t, ctxA['fIdx']) not in ns_keys:
                nb_years.setdefault(str(t[0])[:4], 0.0)
                nb_years[str(t[0])[:4]] += t[R.IDX_PNL]['pnlYuan']
        neg_ratio = sum(1 for v in nb_years.values() if v < 0) / max(len(nb_years),1) if nb_years else None
        combos.append(dict(
            subset='+'.join(sub), n_rules=len(sub),
            d_full=det['net_improve'],
            d_1y=round(R.stats_of(R.window(ns_A, w1))['total'] - base_win['近1年'], 2),
            d_3y=round(R.stats_of(R.window(ns_A, w3))['total'] - base_win['近3年'], 2),
            d_mayaug=g['mayaug_improve'], d_apr=-g['apr_hurt'],
            d_dd_impr=round(mdd_base - mdd_new, 2),
            d_negyear=-neg_ratio if neg_ratio is not None else -1.0,
            d_bear_sum=round(sum(bears.values()), 2), bears=bears,
            d_modes=nmodes, gates_pass=int(g['g1'])+int(g['g2'])+int(g['g3']),
            g1=g['g1'], g2=g['g2'], g3=g['g3'],
            blocked_n=det['blocked_n'], blocked_pnl=det['blocked_pnl'],
            added_n=det['added_n'], added_pnl=det['added_pnl'],
            freq_drop_pct=round(det['blocked_n']/st_base['n']*100, 1),
            new_total=st['total'], zero_trigger=det['blocked_n'] == 0, mdd_new=mdd_new))
        if (idx+1) % 4000 == 0: print(f'  ... {idx+1}/{len(all_combos)}')
    combos.sort(key=lambda x: -x['d_full'])
    print('\n== Top8(全史)==')
    for c in combos[:8]:
        print('  {:<34s} 全史{:+9,.0f} 近1年{:+8,.0f} 门{}/3 模式{}/6 拦{}'.format(
            c['subset'], c['d_full'], c['d_1y'], c['gates_pass'], c['d_modes'], c['blocked_n']))

    KEYS = ['d_full','d_1y','d_3y','d_mayaug','d_apr','d_dd_impr','d_bear_sum','d_modes']
    EPS = 1000.0
    def dominates(a, b):
        return all(a[k2] >= b[k2] - EPS for k2 in KEYS) and any(a[k2] > b[k2] for k2 in KEYS)
    frontier, dominated_list = [], []
    for i, a in enumerate(combos):
        dom_by = None
        for j, b in enumerate(combos):
            if i == j: continue
            if dominates(b, a):
                dom_by = b['subset']; break
        (dominated_list if dom_by else frontier).append((a, dom_by))
    frontier.sort(key=lambda x: -x[0]['d_full'])
    print(f'\n== 帕累托前沿 {len(frontier)} 非劣 / {len(dominated_list)} 被支配;头部:==')
    for a, _ in frontier[:8]:
        print('  {:<34s} 全史{:+9,.0f} 近1年{:+8,.0f} 近3年{:+9,.0f} 5-8月{:+7,.0f} 4月保{:+7,.0f} 回撤{:+9,.0f} 熊合{:+9,.0f} 模式{}/6'.format(
            a['subset'], a['d_full'], a['d_1y'], a['d_3y'], a['d_mayaug'], a['d_apr'],
            a['d_dd_impr'], a['d_bear_sum'], a['d_modes']))

    # 三代表位
    abs_top = combos[0]
    safe = sorted([c for c in combos if c['d_1y'] > 0], key=lambda x: -x['d_full'])[:3]
    dual = sorted([c for c in combos if c['d_1y'] > 0 and c['d_mayaug'] > 0 and c['d_apr'] >= -250], key=lambda x: -x['d_full'])[:3]
    reps = {'abs_top': abs_top['subset'], 'safe_top3': [c['subset'] for c in safe], 'dual_top3': [c['subset'] for c in dual]}
    print('\n代表位: 全史王=', abs_top['subset'], ' 近端安全top3=', [c['subset'] for c in safe])
    print('  近端双正top3=', [c['subset'] for c in dual])

    # 前沿组补检(K1-K4 + 五窗口 + 四熊市)
    detail = {}
    for a, _ in frontier:
        sub = tuple(a['subset'].split('+'))
        kk = {}
        for K in (1,2,3,4):
            kk[f'K{K}'] = round(R.stats_of(eval_subset(ctxA, sub, K))['total'] - R.stats_of(eval_subset(ctxA, (), K))['total'], 2)
        ns_A = eval_subset(ctxA, sub)
        wins = {}
        for lab, a_, b_ in [('近1年',w1,None),('近2年',(dd0-datetime.timedelta(days=730)).strftime('%Y%m%d'),None),
                            ('近3年',w3,None),('近5年',(dd0-datetime.timedelta(days=1825)).strftime('%Y%m%d'),None),('全史','00010101',None)]:
            wins[lab] = round(R.stats_of(R.window(ns_A, a_, b_))['total'] - R.stats_of(R.window(base9_A, a_, b_))['total'], 2)
        detail[a['subset']] = dict(k_sensitivity=kk, windows=wins, bears=a['bears'])

    # R2 在绝对Top组合的 LOO + R2 单独加入 11池最优的 delta
    loo = {}
    top_sub = tuple(abs_top['subset'].split('+'))
    for c in top_sub:
        sub_wo = tuple(x for x in top_sub if x != c)
        loo[c] = round(abs_top['d_full'] - (R.stats_of(eval_subset(ctxA, sub_wo))['total'] - st_base['total']), 2)
    print('绝对王 LOO:', {k: round(v) for k, v in loo.items()})
    # 11池最优(不含R2) + R2 各条加上的 delta
    best11 = next(c for c in combos if 'R2' not in c['subset'])
    b11_sub = tuple(best11['subset'].split('+'))
    r2_add = {}
    for rc in ('R2a','R2b','R2g'):
        imp = R.stats_of(eval_subset(ctxA, b11_sub + (rc,)))['total'] - st_base['total']
        r2_add[rc] = round(imp - best11['d_full'], 2)
    print(f"11池最优(无R2)={best11['subset']} +{best11['d_full']:,.0f};逐条加R2 delta:", r2_add)

    out = dict(baseline=dict(n=st_base['n'], total=st_base['total'], maxdd=mdd_base, anchor=tot9),
               pool14=ALL, r2_solo={c: round(R.diff_detail(base9_A, eval_subset(ctxA,(c,)))['net_improve'],2) for c in ('R2a','R2b','R2g')},
               jaccard_r2_11=jac, jaccard_r2_internal=r2_pair,
               combos=combos, frontier=[dict(a) for a,_ in frontier],
               dominated=[dict(c, dominated_by=db) for c, db in dominated_list],
               frontier_detail=detail, reps=reps, loo_top=loo, r2_add_to_best11=r2_add,
               dims_doc=['d_full','d_1y','d_3y','d_mayaug','d_apr','d_dd_impr','d_bear_sum','d_modes'],
               pareto_note='效果8维 ε=1000;代价类画像列')
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
