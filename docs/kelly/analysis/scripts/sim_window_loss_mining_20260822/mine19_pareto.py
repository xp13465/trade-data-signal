# -*- coding: utf-8 -*-
"""二轮挖掘 补测④(2026-08-22 用户追加质疑):31 组合全维画像 + 帕累托前沿。
维度清单(先列后跑,方向统一为越大越好):
  d1 全史增量 / d2 近1年增量 / d3 近3年增量 / d4 5-8月减亏 / d5 4月保利润(=-apr_hurt)
  d6 回撤改善(vs9键最大回撤差额) / d7 新增被拦按年负占比取负 / d8 四大熊市合计净改善
  d9 跨模式同向数(A-F 六模式 improve>0) / d10 操作性代价取负(-新增被拦笔数)
支配判定用效果 8 维(d_full/d_1y/d_3y/d_mayaug/d_apr/d_dd_impr/d_bear_sum/d_modes);
d_cost/d_negyear 与画像附注(被拦/替补分解、各熊市明细、频次降幅、零触发)不参与支配——
代价类维度与收益天然负相关,纳入会把非劣集撑到无区分度(首跑实测 23 个非劣)。
口径: 补位口径不变;基线=9键(8键+候选1),mode A K1 etf_def。
输出: data/mine19_pareto.json
复现: python3 mine19_pareto.py(依赖 mine10_features.json + signal_kelly_trades.json)
"""
import os, sys, json, datetime
from itertools import combinations
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from mine18_detail import build_cands, BEARS, FEATS_PATH
from mine17_modes import prep_mode

OUT_PATH = os.path.join(BASE, 'data', 'mine19_pareto.json')

def max_dd(sel, fIdx):
    """已实现日度净值最大回撤(金额,<=0)。持有中笔无 sell_date 不计入(两侧同规)。"""
    bys = {}
    for t in sel:
        sd = str(t[fIdx['sell_date']] or '')
        if not sd: continue
        bys.setdefault(sd, 0.0)
        bys[sd] += t[R.IDX_PNL]['pnlYuan']
    cum = peak = 0.0; mdd = 0.0
    for sd in sorted(bys):
        cum += bys[sd]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return round(mdd, 2)

def main():
    feats = json.load(open(FEATS_PATH))
    cands = build_cands(feats)
    names = [n.split()[0] for n, _ in cands]
    rules = [r for _, r in cands]
    rows, fIdx = R.prepare_rows(); R.init(rows, fIdx)
    dmax = max(str(t[0]) for t in rows)
    dd = datetime.date(int(dmax[:4]), int(dmax[4:6]), int(dmax[6:]))
    w1 = (dd - datetime.timedelta(days=365)).strftime('%Y%m%d')
    w3 = (dd - datetime.timedelta(days=1095)).strftime('%Y%m%d')
    c1 = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')
    base9 = R.eval_rule_fill(rows, c1, 1)
    base9_keys = {R.base_key(t, fIdx) for t in base9}
    st_base = R.stats_of(base9)
    mdd_base = max_dd(base9, fIdx)

    # 六模式预建(mode A 复用上面 rows)
    mode_rows = {}
    for m in ['B','C','D','E','F']:
        mode_rows[m] = prep_mode(m)
    def eval_modes(idxs):
        rs = [rules[i] for i in idxs]
        cnt = 0; detail = {}
        # A
        def fnA(t):
            if c1(t): return True
            return any(r(t, fIdx) for r in rs)
        imp = R.stats_of(R.eval_rule_fill(rows, fnA, 1))['total'] - st_base['total']
        detail['A'] = round(imp, 2); cnt += imp > 0
        for m in ['B','C','D','E','F']:
            rm, fm = mode_rows[m]
            R.init(rm, fm)
            c1m = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fm['market_tier']] or '') == '牛市·主升')
            b9m = R.eval_rule_fill(rm, c1m, 1)
            def fnm(t, _fm=fm):
                if c1m(t): return True
                return any(r(t, _fm) for r in rs)
            im = R.stats_of(R.eval_rule_fill(rm, fnm, 1))['total'] - R.stats_of(b9m)['total']
            detail[m] = round(im, 2); cnt += im > 0
        R.init(rows, fIdx)
        return cnt, detail

    combos = []
    for k in range(1, 6):
        for idxs in combinations(range(5), k):
            rs = [rules[i] for i in idxs]
            def combo_fn(t, _rs=rs):
                if c1(t): return True
                return any(r(t, fIdx) for r in _rs)
            ns = R.eval_rule_fill(rows, combo_fn, 1)
            det = R.diff_detail(base9, ns)
            g = R.three_gates(base9, ns, det)
            ns_keys = {R.base_key(t, fIdx) for t in ns}
            newly = list(base9_keys - ns_keys)
            nb_years = {}
            for t in [tt for tt in base9 if R.base_key(tt, fIdx) not in ns_keys]:
                nb_years.setdefault(str(t[0])[:4], 0.0)
                nb_years[str(t[0])[:4]] += t[R.IDX_PNL]['pnlYuan']
            neg_ratio = (sum(1 for v in nb_years.values() if v < 0) / max(len(nb_years),1)) if nb_years else None
            bears = {}
            for lab, a, b in BEARS:
                bw = R.stats_of(R.window(base9, a, b))['total']
                nw = R.stats_of(R.window(ns, a, b))['total']
                bears[lab] = round(nw - bw, 2)
            mdd_new = max_dd(ns, fIdx)
            nmode, mdetail = eval_modes(idxs)
            sub = '+'.join(names[i] for i in idxs)
            combos.append(dict(
                subset=sub,
                d_full=det['net_improve'],
                d_1y=round(R.stats_of(R.window(ns, w1))['total'] - R.stats_of(R.window(base9, w1))['total'], 2),
                d_3y=round(R.stats_of(R.window(ns, w3))['total'] - R.stats_of(R.window(base9, w3))['total'], 2),
                d_mayaug=g['mayaug_improve'], d_apr=-g['apr_hurt'],
                d_dd_impr=round(mdd_base - mdd_new, 2), mdd_base=mdd_base, mdd_new=mdd_new,
                d_negyear=-neg_ratio if neg_ratio is not None else -1.0,
                d_bear_sum=round(sum(bears.values()), 2),
                d_modes=nmode, modes_detail=mdetail,
                d_cost=-det['blocked_n'],
                blocked_n=det['blocked_n'], added_n=det['added_n'],
                blocked_pnl=det['blocked_pnl'], added_pnl=det['added_pnl'],
                freq_drop_pct=round(det['blocked_n'] / st_base['n'] * 100, 1),
                bears=bears, zero_trigger=det['blocked_n'] == 0,
                gates=dict(g1=g['g1'], g2=g['g2'], g3=g['g3'])))
    print(f"基线9键: n={st_base['n']} 全史{st_base['total']:+,.0f} 最大回撤{mdd_base:,.0f}")
    # ---- 帕累托前沿 ----
    KEYS = ['d_full','d_1y','d_3y','d_mayaug','d_apr','d_dd_impr','d_bear_sum','d_modes']
    EPS = 1000.0  # ε-容差支配: 差值<EPS 视为持平(总增量7万量级,千元级差异无实操意义)
    def dominates(a, b):
        ge = all(a[k2] >= b[k2] - EPS for k2 in KEYS)
        gt = any(a[k2] > b[k2] for k2 in KEYS)
        return ge and gt
    # N2 嵌套冗余: 含N1的组合再加N2 零新增拦截(Jaccard 0.377, OR后逐维全等), 直接标冗余
    n2_redundant = set()
    for i, a in enumerate(combos):
        ss = a['subset'].split('+')
        if 'N2' in ss and 'N1' in ss:
            parent = '+'.join(x for x in ss if x != 'N2')
            for j, b in enumerate(combos):
                if b['subset'] == parent:
                    if all(abs(a[k2] - b[k2]) <= 1e-6 for k2 in KEYS):
                        n2_redundant.add(i)
    frontier = []
    dominated_list = []
    for i, a in enumerate(combos):
        dom_by = None
        if i in n2_redundant:
            dom_by = a['subset'].replace('+N2', '') + '(N2嵌套冗余)'
        else:
            for j, b in enumerate(combos):
                if i == j or j in n2_redundant: continue
                if dominates(b, a):
                    dom_by = b['subset']; break
        (dominated_list if dom_by else frontier).append((a, dom_by))
    frontier.sort(key=lambda x: -x[0]['d_full'])
    print(f"\n== 帕累托前沿({len(frontier)}个非劣)==")
    for a, _ in frontier:
        print(f"  {a['subset']:16s} 全史{a['d_full']:+8,.0f} 近1年{a['d_1y']:+7,.0f} 近3年{a['d_3y']:+8,.0f} "
              f"5-8月{a['d_mayaug']:+7,.0f} 4月保{a['d_apr']:+7,.0f} 回撤改善{a['d_dd_impr']:+7,.0f} "
              f"熊合{a['d_bear_sum']:+8,.0f} 模式{a['d_modes']}/6 拦{a['blocked_n']}笔(-{a['freq_drop_pct']}%)")
    out = dict(baseline=dict(n=st_base['n'], total=st_base['total'], maxdd=mdd_base),
               dims_doc=['d_full全史增量','d_1y近1年增量','d_3y近3年增量','d_mayaug 5-8月减亏',
                         'd_apr 4月保利润(=-apr_hurt)','d_dd_impr回撤改善','d_negyear 负的按年负占比',
                         'd_bear_sum四大熊市合计','d_modes跨模式同向数/6','d_cost负的被拦笔数'],
               frontier=[dict(a) for a, _ in frontier],
               dominated=[dict(c, dominated_by=db) for c, db in dominated_list])
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print(f"\n被支配淘汰 {len(dominated_list)} 个:")
    for c, db in sorted(dominated_list, key=lambda x: x[1] or ''):
        print(f"  {c['subset']:16s} <- 被 {db} 支配")
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
