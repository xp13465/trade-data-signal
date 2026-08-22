# -*- coding: utf-8 -*-
"""二轮挖掘 子群组合规则(2026-08-22)。
方法来源:method-survey A6(pysubgroup 式 beam/穷举合取规则;sklearn/pysubgroup 未装,手写穷举)。
特征空间:二轮 22 个数值特征按全史 30/50/70 分位二值化(low/high)× 一轮信号属性(signal/tier/mktD)。
规则形式(合取):
  f_bool & sig==s / f_bool & tier==x / f_bool & mktD==m / f_bool & sig==s & tier==x
补位口径主判据 + 三道门;含信号属性 -> 存在真实替补效应(added 可>0)。
输出:data/mine14_subgroup.json(全部规则含落选)
复现:python3 mine14_subgroup.py(依赖 mine10_features.json)
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R

FEATS_PATH = os.path.join(BASE, 'data', 'mine10_features.json')
OUT_PATH = os.path.join(BASE, 'data', 'mine14_subgroup.json')
QS = (0.30, 0.50, 0.70)

def binarize_feats(feats):
    """返回 [(name, q, direction, series, th)]"""
    out = []
    for fname in sorted(feats):
        series = feats[fname]
        vals = sorted(v for v in series.values() if v is not None)
        if len(vals) < 200: continue
        for p in QS:
            th = vals[min(int(p * (len(vals) - 1)), len(vals) - 1)]
            out.append((fname, p, 'low', series, th))
            out.append((fname, p, 'high', series, th))
    return out

def main():
    rows, fIdx = R.prepare_rows()
    R.init(rows, fIdx)
    base = R.eval_baseline(rows, 1)
    feats = json.load(open(FEATS_PATH))
    bools = binarize_feats(feats)
    SIGS = ('buy', 'buy_aux', 'buy_special', 'buy_backup')
    TIERS = ('牛市·主升', '上升期', '下降期', '熊市·主跌')
    MKTS = ('a', 'concept', 'industry', 'hk', 'global')

    def fb(t, item):
        _, _, drc, series, th = item
        v = series.get(str(t[3]))
        if v is None: return False
        return v < th if drc == 'low' else v > th

    results = []
    def run(name, fn):
        new_sel = R.eval_rule_fill(rows, fn, 1)
        det = R.diff_detail(base, new_sel)
        if det['blocked_n'] == 0 and det['added_n'] == 0:
            return
        gates = R.three_gates(base, new_sel, det)
        st_new = R.stats_of(new_sel)
        del_sel = R.eval_rule_del(rows, fn, 1)
        det_del = R.diff_detail(base, del_sel)
        results.append(dict(rule=name, fill=dict(det, new_total=st_new['total']), gates=gates,
                            delmode=dict(blocked_n=det_del['blocked_n'], net_improve_delmode=det_del['net_improve'])))
        if gates['pass_all']:
            g = gates
            print(f"[PASS] {name} net={det['net_improve']:+.0f} blk({det['blocked_n']},{det['blocked_pnl']:+.0f}) add({det['added_n']},{det['added_pnl']:+.0f}) "
                  f"aprH={g['apr_hurt']:+.0f} maA={g['mayaug_improve']:+.0f} fwd={g['forward']['net_improve']:+.0f} nr={g['blocked_neg_ratio']:.0%}")

    n2 = 0
    for item in bools:
        nm, p, drc, _, th = item
        tag = f"{nm}{drc[0].upper()}{p:.0f}"
        for s in SIGS:
            run(f"{tag}&sig={s}", lambda t, _i=item, _s=s: fb(t, _i) and t[2] == _s)
            n2 += 1
        for x in TIERS:
            run(f"{tag}&tier={x}", lambda t, _i=item, _x=x: fb(t, _i) and (t[fIdx['market_tier']] or '') == _x)
            n2 += 1
        for m in MKTS:
            mD = len(fIdx)
            run(f"{tag}&mkt={m}", lambda t, _i=item, _m=m: fb(t, _i) and (t[mD] or '') == _m)
            n2 += 1
        for s in SIGS:
            for x in TIERS:
                run(f"{tag}&sig={s}&tier={x}", lambda t, _i=item, _s=s, _x=x: fb(t, _i) and t[2] == _s and (t[fIdx['market_tier']] or '') == _x)
                n2 += 1
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(n_rules=len(results), baseline=R.stats_of(base), rules=results), f, ensure_ascii=False)
    passed = [r for r in results if r['gates']['pass_all']]
    print(f"combos evaluated(with trades hit): {len(results)} / generated {n2}, pass all: {len(passed)}")
    for r in sorted(passed, key=lambda x: -x['fill']['net_improve'])[:20]:
        g = r['gates']
        print(f"  {r['rule']:44s} net={r['fill']['net_improve']:+7.0f} blk({r['fill']['blocked_n']:>3d},{r['fill']['blocked_pnl']:+7.0f}) "
              f"add({r['fill']['added_n']:>2d},{r['fill']['added_pnl']:+6.0f}) aprH={g['apr_hurt']:+6.0f} maA={g['mayaug_improve']:+6.0f} "
              f"fwd={g['forward']['net_improve']:+7.0f} nr={g['blocked_neg_ratio']:.0%}")

if __name__ == '__main__':
    main()
