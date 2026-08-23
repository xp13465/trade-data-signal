# -*- coding: utf-8 -*-
"""二轮挖掘 补测⑥(2026-08-22 开工令):N=11 全子集穷举(2^11-1=2047)。
池子 = mine20_pool.json pool_in(N1/T1/D1/Q1/H1/M1/D2/P1/V1/S1/R1,全部 vs9键边际>0 且无池内超集)。
每子集全维: 全史/近1年/近3年增量、5-8月改善(new−base)、4月改善(负=误伤)、回撤改善、按年负占比、四大熊市合计、
跨模式同向数(A-F 逐组合实跑)、过门数、被拦/替补分解、频次降幅、零触发标注、协同比。
排名: 效果8维 ε=1000 帕累托支配(mine19 同口径);前沿组补 K1-K4 敏感性+五窗口+四熊市专项。
落池 7 条(mine20)补「单独无用/协同无用」定性(强加进前沿最优组合测增量变化)。
口径纪律: 补位口径不变;9键基线锚点断言自检(mode A 全史=+73,102.53)。
输出: data/mine21_tour.json
复现: python3 mine21_bigtour.py(依赖 mine10_features.json + mine20_pool.json + signal_kelly_trades.json)
"""
import os, sys, json, datetime
from itertools import combinations
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from mine18_detail import BEARS, FEATS_PATH
from mine17_modes import prep_mode

OUT_PATH = os.path.join(BASE, 'data', 'mine21_tour.json')
POOL_PATH = os.path.join(BASE, 'data', 'mine20_pool.json')

def build_rules(feats, fIdx):
    """池子 11 条规则工厂(与 mine20_pool.py 逐字同阈值)。"""
    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p*(len(vals)-1)), len(vals)-1)]
    mD = len(fIdx)
    def FR(fname, direction, th, sig=None, tier=None, mkt=None):
        series = feats[fname] if fname else None
        def fn(t):
            if series is not None:
                v = series.get(str(t[3]))
                if v is None: return False
                if not (v < th if direction == 'low' else v > th): return False
            if sig is not None and t[2] != sig: return False
            if tier is not None and (t[fIdx['market_tier']] or '') != tier: return False
            if mkt is not None and (t[mD] or '') != mkt: return False
            return True
        return fn
    return {
        # 落池 7 条(供协同定性强加测试)
        'N2': FR('north_d20','low',qth('north_d20',0.30),mkt='concept'),
        'V2': FR('h_vol20','high',25.0),
        'S2': FR('sent_hs300','low',qth('sent_hs300',0.20)),
        'W1': FR(None,None,None,sig='buy_backup',tier='下降期'),
        'A1': FR(None,None,None,tier='牛市·主升'),
        'V3': FR('h_vol20','low',qth('h_vol20',0.10)),
        'AD1': FR('adline_gap','high',qth('adline_gap',0.70)),
        # 池内 11 条
        'N1': FR('north_d20','low',qth('north_d20',0.30)),
        'T1': FR('turn_pct','low',qth('turn_pct',0.30),sig='buy_special'),
        'D1': FR('div_yield','low',qth('div_yield',0.50)),
        'Q1': FR('qvix_pct','low',qth('qvix_pct',0.10)),
        'H1': FR('h_volchg','high',qth('h_volchg',0.30),mkt='a'),
        'M1': FR('margin_chg20','low',qth('margin_chg20',0.70),tier='牛市·主升'),
        'D2': FR('div_yield','low',qth('div_yield',0.70),tier='牛市·主升'),
        'P1': FR('div_pct','low',qth('div_pct',0.30),sig='buy_backup'),
        'V1': FR('h_vol20','high',qth('h_vol20',0.90)),
        'S1': FR('sent_a','low',qth('sent_a',0.20)),
        'R1': FR('vol_ratio_all','low',qth('vol_ratio_all',0.10)),
    }

def max_dd(sel, fIdx):
    bys = {}
    for t in sel:
        sd = str(t[fIdx['sell_date']] or '')
        if not sd: continue
        bys.setdefault(sd, 0.0); bys[sd] += t[R.IDX_PNL]['pnlYuan']
    cum = peak = 0.0; mdd = 0.0
    for sd in sorted(bys):
        cum += bys[sd]; peak = max(peak, cum); mdd = min(mdd, cum - peak)
    return round(mdd, 2)

def main():
    feats = json.load(open(FEATS_PATH))
    pool = json.load(open(POOL_PATH))
    codes = pool['pool_in']
    assert len(codes) == 11, codes
    dropped = [c['code'] for c in pool['candidates'] if c['code'] not in codes]
    print('池子(11):', codes, ' 落池(7):', dropped)

    dmax_ref = None
    all_combos = list(combinations(codes, 0)) 
    all_combos = [c for k in range(1, 12) for c in combinations(codes, k)]
    print('子集数:', len(all_combos))

    # ---- 六模式预建 + 缓存化 eval ----
    mode_ctx = {}
    for m in ['A','B','C','D','E','F']:
        if m == 'A':
            rows_m, fIdx_m = R.prepare_rows()
        else:
            rows_m, fIdx_m = prep_mode(m)
        R.init(rows_m, fIdx_m)
        rules_m = build_rules(feats, fIdx_m)
        c1m = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx_m['market_tier']] or '') == '牛市·主升')
        hits_c1 = {R.base_key(t, fIdx_m) for t in rows_m if c1m(t)}
        hits = {c: {R.base_key(t, fIdx_m) for t in rows_m if rules_m[c](t)} for c in codes}
        groups = {}
        for t in rows_m:
            groups.setdefault(str(t[0]), []).append((R.base_key(t, fIdx_m), t))
        for sd in groups:
            groups[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
        sds = sorted(groups)
        mode_ctx[m] = dict(rows=rows_m, fIdx=fIdx_m, hits=hits, hits_c1=hits_c1,
                           groups=groups, sds=sds, c1=c1m)
        if m == 'A':
            dmax_ref = max(str(t[0]) for t in rows_m)
        print(f'mode {m} 预建完成 rows={len(rows_m)}')

    def eval_subset(ctx, subset, K=1):
        blk = set(ctx['hits_c1'])
        for c in subset:
            blk |= ctx['hits'][c]
        sel = []
        for sd in ctx['sds']:
            n = 0
            for key, t in ctx['groups'][sd]:
                if key not in blk:
                    sel.append(t)
                    n += 1
                    if n >= K: break
        return sel

    # 断言自检: 9键基线锚点
    ctxA = mode_ctx['A']
    base9_A = eval_subset(ctxA, ())
    tot9 = R.stats_of(base9_A)['total']
    assert abs(tot9 - 73102.53) < 0.5, f'9键基线锚点不符: {tot9}'
    print(f'锚点自检 PASS: mode A 9键基线 = {tot9:+,.2f} (期望 +73,102.53)')

    dd0 = datetime.date(int(dmax_ref[:4]), int(dmax_ref[4:6]), int(dmax_ref[6:]))
    w1 = (dd0 - datetime.timedelta(days=365)).strftime('%Y%m%d')
    w3 = (dd0 - datetime.timedelta(days=1095)).strftime('%Y%m%d')
    st_base = R.stats_of(base9_A)
    mdd_base = max_dd(base9_A, ctxA['fIdx'])
    base_win = {lab: R.stats_of(R.window(base9_A, a, b))['total'] for lab, a, b in
                [('近1年',w1,None),('近3年',w3,None)] +
                [(lab,a,b) for lab,a,b in BEARS]}
    print('基线: n=%d 全史%+.2f 回撤%.0f 近1年%+.0f' % (st_base['n'], st_base['total'], mdd_base, base_win['近1年']))

    # ---- 2047 子集 × 六模式 ----
    combos = []
    for idx, sub in enumerate(all_combos):
        ns_A = eval_subset(ctxA, sub)
        det = R.diff_detail(base9_A, ns_A)
        g = R.three_gates(base9_A, ns_A, det)
        st = R.stats_of(ns_A)
        mdd_new = max_dd(ns_A, ctxA['fIdx'])
        bears = {lab: round(R.stats_of(R.window(ns_A, a, b))['total'] - base_win[lab], 2) for lab, a, b in BEARS}
        # 跨模式同向
        nmodes = 1  # A 已知
        for m in ['B','C','D','E','F']:
            cm = mode_ctx[m]
            imp = R.stats_of(eval_subset(cm, sub))['total'] - R.stats_of(eval_subset(cm, ()))['total']
            nmodes += imp > 0
        # 新增被拦按年负占比
        ns_keys = {R.base_key(t, ctxA['fIdx']) for t in ns_A}
        nb_years = {}
        for t in base9_A:
            if R.base_key(t, ctxA['fIdx']) not in ns_keys:
                nb_years.setdefault(str(t[0])[:4], 0.0)
                nb_years[str(t[0])[:4]] += t[R.IDX_PNL]['pnlYuan']
        neg_ratio = sum(1 for v in nb_years.values() if v < 0) / max(len(nb_years), 1) if nb_years else None
        combos.append(dict(
            subset='+'.join(sub), n_rules=len(sub),
            d_full=det['net_improve'],
            d_1y=round(R.stats_of(R.window(ns_A, w1))['total'] - base_win['近1年'], 2),
            d_3y=round(R.stats_of(R.window(ns_A, w3))['total'] - base_win['近3年'], 2),
            d_mayaug=g['mayaug_improve'], d_apr=g['apr_hurt'],
            d_dd_impr=round(mdd_base - mdd_new, 2),
            d_negyear=-neg_ratio if neg_ratio is not None else -1.0,
            d_bear_sum=round(sum(bears.values()), 2), bears=bears,
            d_modes=nmodes, gates_pass=int(g['g1'])+int(g['g2'])+int(g['g3']),
            g1=g['g1'], g2=g['g2'], g3=g['g3'],
            blocked_n=det['blocked_n'], blocked_pnl=det['blocked_pnl'],
            added_n=det['added_n'], added_pnl=det['added_pnl'],
            freq_drop_pct=round(det['blocked_n']/st_base['n']*100, 1),
            new_total=st['total'], zero_trigger=det['blocked_n'] == 0,
            mdd_new=mdd_new))
        if (idx+1) % 500 == 0: print(f'  ... {idx+1}/{len(all_combos)}')
    combos.sort(key=lambda x: -x['d_full'])
    print('\n== Top10(全史增量)==')
    for c in combos[:10]:
        print('  {:<28s} 全史{:+8,.0f} 近1年{:+7,.0f} 门{}/3 模式{}/6 拦{}(-{}%)'.format(
            c['subset'] or '(空)', c['d_full'], c['d_1y'], c['gates_pass'], c['d_modes'],
            c['blocked_n'], c['freq_drop_pct']))

    # ---- 帕累托(效果8维 ε=1000,mine19 同口径) ----
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
    print(f'\n== 帕累托前沿({len(frontier)} 非劣 / {len(dominated_list)} 被支配)==')
    for a, _ in frontier[:12]:
        print('  {:<28s} 全史{:+8,.0f} 近1年{:+7,.0f} 近3年{:+8,.0f} 5-8月{:+7,.0f} 4月改善{:+7,.0f} 回撤{:+8,.0f} 熊合{:+8,.0f} 模式{}/6'.format(
            a['subset'], a['d_full'], a['d_1y'], a['d_3y'], a['d_mayaug'], a['d_apr'],
            a['d_dd_impr'], a['d_bear_sum'], a['d_modes']))

    # ---- 前沿组补充检验: K1-K4 + 五窗口 + 四熊市明细 ----
    detail = {}
    for a, _ in frontier:
        sub = tuple(a['subset'].split('+')) if a['subset'] else ()
        kk = {}
        for K in (1,2,3,4):
            imp = R.stats_of(eval_subset(ctxA, sub, K))['total'] - R.stats_of(eval_subset(ctxA, (), K))['total']
            kk[f'K{K}'] = round(imp, 2)
        ns_A = eval_subset(ctxA, sub)
        wins = {}
        for lab, a_, b_ in [('近1年',w1,None),('近2年',(dd0-datetime.timedelta(days=730)).strftime('%Y%m%d'),None),
                            ('近3年',w3,None),('近5年',(dd0-datetime.timedelta(days=1825)).strftime('%Y%m%d'),None),
                            ('全史','00010101',None)]:
            bw = R.stats_of(R.window(base9_A, a_, b_))['total']
            nw = R.stats_of(R.window(ns_A, a_, b_))['total']
            wins[lab] = round(nw - bw, 2)
        detail[a['subset']] = dict(k_sensitivity=kk, windows=wins, bears=a['bears'])
        print('  前沿补检 %-24s K=%s 窗=%s' % (a['subset'], kk, wins))

    # ---- 落池 7 条协同定性: 强加进全史最优组合 ----
    best = combos[0]
    best_sub = tuple(best['subset'].split('+')) if best['subset'] else ()
    qual = {}
    for code in dropped:
        rows_p, fIdx_p = R.prepare_rows(); R.init(rows_p, fIdx_p)
        rules_p = build_rules(feats, fIdx_p)
        c1p = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx_p['market_tier']] or '') == '牛市·主升')
        hits_c1p = {R.base_key(t, fIdx_p) for t in rows_p if c1p(t)}
        hit_p = {R.base_key(t, fIdx_p) for t in rows_p if rules_p[code](t)}
        grp = {}
        for t in rows_p:
            grp.setdefault(str(t[0]), []).append((R.base_key(t, fIdx_p), t))
        for sd in grp: grp[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
        def ev(blk, K=1):
            sel = []
            for sd in sorted(grp):
                n = 0
                for key, t in grp[sd]:
                    if key not in blk:
                        sel.append(t); n += 1
                        if n >= K: break
            return sel
        base_p = ev(hits_c1p)
        with_p = ev(hits_c1p | hit_p | {R.base_key(t, fIdx_p) for t in rows_p
                   for c in best_sub if (rules_p[c](t))} | set())
        # 上面写法复杂,直接: 组合+落池候选
        blk_best = set(hits_c1p)
        for c in best_sub:
            blk_best |= {R.base_key(t, fIdx_p) for t in rows_p if rules_p[c](t)}
        blk_with = blk_best | hit_p
        imp_best = R.stats_of(ev(blk_best))['total'] - R.stats_of(base_p)['total']
        imp_with = R.stats_of(ev(blk_with))['total'] - R.stats_of(base_p)['total']
        delta = round(imp_with - imp_best, 2)
        solo = next(c['vs9_net'] for c in pool['candidates'] if c['code'] == code)
        qual[code] = dict(solo_vs9=solo, add_to_best_delta=delta,
                         verdict=('协同有用(加入最优组合再+%d,应回池复检)' % delta if delta > 500 else
                                  '协同无用(加入最优组合变化 %+.0f,维持落池)' % delta if delta > -500 else
                                  '协同有害(加入最优组合 %+.0f)' % delta))
        print('  落池定性 {:<4s} solo={:+7,.0f} 强加进最优组合 delta={:+7,.0f} -> {}'.format(code, solo, delta, qual[code]['verdict'][:24]))

    # ---- 池内 leave-one-out(最优组合成员贡献) ----
    loo = {}
    for c in best_sub:
        sub_wo = tuple(x for x in best_sub if x != c)
        imp_wo = R.stats_of(eval_subset(ctxA, sub_wo))['total'] - st_base['total']
        loo[c] = round(best['d_full'] - imp_wo, 2)
    print('  最优组合 leave-one-out 边际贡献:', loo)

    out = dict(baseline=dict(n=st_base['n'], total=st_base['total'], maxdd=mdd_base, anchor_check=tot9),
               pool=codes, dropped=dropped, combos=combos,
               frontier=[dict(a) for a, _ in frontier],
               dominated=[dict(c, dominated_by=db) for c, db in dominated_list],
               frontier_detail=detail, dropped_qual=qual, loo=loo,
               dims_doc=['d_full全史','d_1y近1年','d_3y近3年','d_mayaug 5-8月改善(new−base)','d_apr 4月改善(负=误伤)',
                         'd_dd_impr回撤改善','d_bear_sum四熊合计','d_modes跨模式同向数/6'],
               pareto_note='效果8维 ε=1000 容差支配;代价类(拦笔数/负占比)为画像列不参与支配')
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
