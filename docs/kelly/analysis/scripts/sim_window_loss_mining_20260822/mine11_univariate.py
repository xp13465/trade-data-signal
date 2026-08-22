# -*- coding: utf-8 -*-
"""二轮挖掘 单维阈值扫描(2026-08-22)。
对每个特征 × 分位阈值(10..90) × 双方向(低拦/高拦)生成时段级停做规则,
一律用补位口径(eval_rule_fill);删笔口径并列作理想对照副列。
三道门:g1 blocked_n>=30;g2 2026双向(4月误伤>=-1500 且 5-8月改善>=+2500);
g3 前向2024-26净改善>=0 且 blocked类按年负占比>=55%。
输出:data/mine11_univariate.json(全部规则,含落选)
复现:python3 mine11_univariate.py(依赖 mine10_features.json 先生成)
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R

FEATS_PATH = os.path.join(BASE, 'data', 'mine10_features.json')
OUT_PATH = os.path.join(BASE, 'data', 'mine11_univariate.json')

QUANTILES = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]

def main():
    rows, fIdx = R.prepare_rows()
    R.init(rows, fIdx)
    base = R.eval_baseline(rows, 1)
    feats = json.load(open(FEATS_PATH))
    results = []
    for fname, series in sorted(feats.items()):
        vals = sorted(v for v in series.values() if v is not None)
        if len(vals) < 200:
            continue
        import bisect
        def q(p):
            i = min(int(p * (len(vals) - 1)), len(vals) - 1)
            return vals[i]
        for p in QUANTILES:
            th = q(p)
            for direction in ('low', 'high'):
                def rule_fn(t, _f=fname, _s=series, _th=th, _d=direction):
                    bd = str(t[3] or '')  # buy_date idx=3
                    v = _s.get(bd)
                    if v is None:
                        return False  # 缺数据不拦(诚实口径)
                    return (v < _th) if _d == 'low' else (v > _th)
                new_sel = R.eval_rule_fill(rows, rule_fn, 1)
                det = R.diff_detail(base, new_sel)
                if det['blocked_n'] == 0 and det['added_n'] == 0:
                    continue
                gates = R.three_gates(base, new_sel, det)
                st_new = R.stats_of(new_sel)
                # 删笔口径对照
                del_sel = R.eval_rule_del(rows, rule_fn, 1)
                det_del = R.diff_detail(base, del_sel)
                results.append(dict(
                    feat=fname, direction=direction, threshold=round(th, 4), quantile=p,
                    fill=dict(det, new_total=st_new['total']),
                    gates=gates,
                    delmode=dict(blocked_n=det_del['blocked_n'], net_improve_delmode=det_del['net_improve']),
                    yearly_new=R.yearly_buckets(new_sel),
                ))
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(n_rules=len(results), baseline=R.stats_of(base), rules=results), f, ensure_ascii=False)
    passed = [r for r in results if r['gates']['pass_all']]
    print(f"total rules evaluated: {len(results)}, pass all three gates: {len(passed)}")
    for r in sorted(passed, key=lambda x: -x['fill']['net_improve']):
        g = r['gates']
        print(f"[PASS] {r['feat']} {r['direction']} th={r['threshold']} q={r['quantile']:.0%} "
              f"net_impr={r['fill']['net_improve']:+.0f} (blocked {r['fill']['blocked_pnl']:+.0f}/n{r['fill']['blocked_n']}, "
              f"added {r['fill']['added_pnl']:+.0f}/n{r['fill']['added_n']}) "
              f"aprHurt={g['apr_hurt']:+.0f} maAugImpr={g['mayaug_improve']:+.0f} fwd={g['forward']['net_improve']:+.0f} negRatio={g['blocked_neg_ratio']:.0%}")

if __name__ == '__main__':
    main()
