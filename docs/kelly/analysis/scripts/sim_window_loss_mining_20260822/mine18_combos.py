# -*- coding: utf-8 -*-
"""二轮挖掘 补测②③(2026-08-22 用户质疑补跑):5 候选 31 非空子集组合协同矩阵(vs9键)。
每组合: 全史增量/近1年增量/2026双向(apr_hurt,mayaug)/三道门过门数/协同比(combo增量÷单条增量之和)。
被拦重合度: 单条新增被拦集合(相对9键)两两 Jaccard。
Top3 推荐: 榜A=全史增量;榜B=稳健性(过门数,平手看全史增量);Top 组合跑 A-F 六模式。
口径: 补位口径不变;基线=9键(8键+候选1),mode A K1 etf_def。
输出: data/mine18_combos.json
复现: python3 mine18_combos.py(依赖 mine10_features.json + signal_kelly_trades.json)
"""
import os, sys, json, datetime
from itertools import combinations
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from mine18_detail import build_cands, FEATS_PATH

OUT_PATH = os.path.join(BASE, 'data', 'mine18_combos.json')

def main():
    feats = json.load(open(FEATS_PATH))
    cands = build_cands(feats)
    names = [n for n, _ in cands]
    rules = [r for _, r in cands]
    rows, fIdx = R.prepare_rows(); R.init(rows, fIdx)
    dmax = max(str(t[0]) for t in rows)
    dd = datetime.date(int(dmax[:4]), int(dmax[4:6]), int(dmax[6:]))
    near1 = (dd - datetime.timedelta(days=365)).strftime('%Y%m%d')
    c1 = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')
    base9 = R.eval_rule_fill(rows, c1, 1)
    base9_keys = {R.base_key(t, fIdx) for t in base9}
    base9_1y = R.stats_of(R.window(base9, near1))['total']

    def keyset(sel):
        return {R.base_key(t, fIdx) for t in sel}

    # ---- 单条:全史 det + 近1年 + 新增被拦集合 ----
    single = {}
    for i, (nm, rule) in enumerate(cands):
        both = lambda t, _r=rule: _r(t, fIdx) or c1(t)
        ns = R.eval_rule_fill(rows, both, 1)
        det = R.diff_detail(base9, ns)
        n1 = R.stats_of(R.window(ns, near1))['total']
        single[i] = dict(name=nm, net=det['net_improve'], blocked_n=det['blocked_n'],
                         blocked_pnl=det['blocked_pnl'], added_n=det['added_n'], added_pnl=det['added_pnl'],
                         near1=round(n1 - base9_1y, 2),
                         blocked_keys=keyset(base9) - keyset(ns))
        print(f"单条 {nm}: 全史{det['net_improve']:+,.0f} 近1年{single[i]['near1']:+,.0f} 被拦{det['blocked_n']}")

    # ---- 31 非空子集 ----
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
            n1 = R.stats_of(R.window(ns, near1))['total']
            ssum = sum(single[i]['net'] for i in idxs)
            syn = round(det['net_improve'] / ssum, 3) if ssum > 0 else None
            gp = int(g['g1']) + int(g['g2']) + int(g['g3'])
            combos.append(dict(subset=[names[i].split()[0] for i in idxs], idxs=list(idxs),
                               net=det['net_improve'], near1=round(n1 - base9_1y, 2),
                               apr_hurt=g['apr_hurt'], mayaug=g['mayaug_improve'],
                               g1=g['g1'], g2=g['g2'], g3=g['g3'], gates_pass=gp,
                               sum_single=round(ssum, 2), synergy=syn,
                               blocked_n=det['blocked_n'], added_n=det['added_n']))
    combos.sort(key=lambda x: -x['net'])
    print("\n== 31 组合(按全史增量降序,前12)==")
    for c in combos[:12]:
        print(f"  {'+'.join(c['subset']):16s} 全史{c['net']:+8,.0f} 近1年{c['near1']:+8,.0f} 4月{c['apr_hurt']:+7,.0f} 5-8月{c['mayaug']:+7,.0f} 门{c['gates_pass']}/3 协同比{c['synergy'] if c['synergy'] is not None else 'n/a'}")

    # ---- 被拦重合度 Jaccard 矩阵 ----
    jac = {}
    for a, b in combinations(range(5), 2):
        A, B = single[a]['blocked_keys'], single[b]['blocked_keys']
        u = A | B
        jac[f"{names[a].split()[0]}~{names[b].split()[0]}"] = dict(
            inter=len(A & B), union=len(u), jaccard=round(len(A & B) / len(u), 3) if u else None,
            nA=len(A), nB=len(B))
    print("\n== 被拦重合度(Jaccard)==")
    for kk, v in jac.items():
        print(f"  {kk:10s} 交{v['inter']:4d} 并{v['union']:5d} J={v['jaccard']}")

    # ---- Top3 双榜 + 六模式 ----
    boardA = combos[:3]
    boardB = sorted(combos, key=lambda x: (-x['gates_pass'], -x['net']))[:3]
    top_set = {}
    for c in boardA + boardB:
        top_set[tuple(c['idxs'])] = c
    modes_out = {}
    from mine17_modes import prep_mode
    for mode in ['A','B','C','D','E','F']:
        rows_m, fIdx_m = prep_mode(mode)
        R.init(rows_m, fIdx_m)
        c1m = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx_m['market_tier']] or '') == '牛市·主升')
        b9m = R.eval_rule_fill(rows_m, c1m, 1)
        line = {}
        for idxs in top_set:
            rs = [rules[i] for i in idxs]
            def fn_m(t, _rs=rs):
                if c1m(t): return True
                return any(r(t, fIdx_m) for r in _rs)
            ns = R.eval_rule_fill(rows_m, fn_m, 1)
            line['+'.join(names[i].split()[0] for i in idxs)] = round(
                R.stats_of(ns)['total'] - R.stats_of(b9m)['total'], 2)
        modes_out[mode] = dict(base9=R.stats_of(b9m)['total'], improve=line)
        print(f"mode {mode}: base9={modes_out[mode]['base9']:+,.0f} " +
              ' '.join(f"{k}={v:+,.0f}" for k, v in line.items()))

    out = dict(single={names[i].split()[0]: dict(net=single[i]['net'], near1=single[i]['near1'],
                                                 blocked_n=single[i]['blocked_n'], blocked_pnl=single[i]['blocked_pnl'],
                                                 added_n=single[i]['added_n'], added_pnl=single[i]['added_pnl'])
                      for i in range(5)},
               combos=combos, jaccard=jac,
               boardA=[c['subset'] for c in boardA], boardB=[c['subset'] for c in boardB],
               modes=modes_out, near1_anchor=near1, baseline9_full=R.stats_of(base9)['total'])
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
