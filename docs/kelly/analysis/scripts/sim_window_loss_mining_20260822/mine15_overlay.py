# -*- coding: utf-8 -*-
"""二轮挖掘 与一轮主推叠加测试 + 同源度检查(2026-08-22)。
一轮主推(候选1)= tier==牛市·主升 & signal∈{buy_aux,buy_backup}(补位口径下也是组内剔除规则)。
本脚本:各维度 top 候选在 9键(8键+候选1)之上测真实增量;输出同源度(被拦笔与候选1被拦笔重叠率)。
输出:data/mine15_overlay.json
复现:python3 mine15_overlay.py(依赖 mine11/13/14 的 json 或内置规则定义)
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R

OUT_PATH = os.path.join(BASE, 'data', 'mine15_overlay.json')
FEATS_PATH = os.path.join(BASE, 'data', 'mine10_features.json')

def cand1_fn(t):
    return (t[2] in ('buy_aux', 'buy_backup')) and ((t[R.fIdx_global['market_tier']] or '') == '牛市·主升')

def main():
    rows, fIdx = R.prepare_rows()
    R.init(rows, fIdx)
    R.fIdx_global = fIdx
    feats = json.load(open(FEATS_PATH))
    base8 = R.eval_baseline(rows, 1)
    base9 = R.eval_rule_fill(rows, cand1_fn, 1)
    print('8键基线:', R.stats_of(base8))
    print('9键基线(8键+一轮候选1):', R.stats_of(base9))

    # 候选规则集(各维度代表:过g3或top改善者)
    def feat_rule(fname, direction, th):
        series = feats[fname]
        def fn(t):
            v = series.get(str(t[3]))
            if v is None: return False
            return v < th if direction == 'low' else v > th
        return fn

    def feat_sig_tier(fname, direction, th, sig=None, tier=None, mkt=None):
        series = feats[fname]
        mD = len(fIdx)
        def fn(t):
            v = series.get(str(t[3]))
            if v is None: return False
            b = v < th if direction == 'low' else v > th
            if not b: return False
            if sig is not None and t[2] != sig: return False
            if tier is not None and (t[fIdx['market_tier']] or '') != tier: return False
            if mkt is not None and (t[mD] or '') != mkt: return False
            return True
        return fn

    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p * (len(vals) - 1)), len(vals) - 1)]

    cands = [
        ('mine11: div_yield<q50 全停',            feat_rule('div_yield', 'low', qth('div_yield', 0.50))),
        ('mine11: north_d20<q30 全停',            feat_rule('north_d20', 'low', qth('north_d20', 0.30))),
        ('mine11: qvix_pct<q10 全停',             feat_rule('qvix_pct', 'low', qth('qvix_pct', 0.10))),
        ('mine12: eqma20',                        None),  # equity 族路径依赖,单独处理
        ('mine13: cny_pre5 全停',                 lambda t: _in_cny_pre(str(t[3]), 5)),
        ('mine14: north_d20L0&mkt=concept',       feat_sig_tier('north_d20', 'low', qth('north_d20', 0.30), mkt='concept')),
        ('mine14: turn_pctL0&sig=buy_special',    feat_sig_tier('turn_pct', 'low', qth('turn_pct', 0.30), sig='buy_special')),
        ('mine14: h_volchgH1&mkt=a',              feat_sig_tier('h_volchg', 'high', qth('h_volchg', 0.30), mkt='a')),
        ('mine14: margin_chg20L1&tier=牛主升',     feat_sig_tier('margin_chg20', 'low', qth('margin_chg20', 0.70), tier='牛市·主升')),
        ('mine14: div_yieldL1&tier=牛主升',        feat_sig_tier('div_yield', 'low', qth('div_yield', 0.70), tier='牛市·主升')),
        ('mine14: div_pctL0&sig=buy_backup',      feat_sig_tier('div_pct', 'low', qth('div_pct', 0.30), sig='buy_backup')),
        ('mine14: h_ret20H0&sig=backup&tier=牛主升', feat_sig_tier('h_ret20', 'high', qth('h_ret20', 0.30), sig='buy_backup', tier='牛市·主升')),
    ]

    def _in_cny_pre(ds, n):
        import datetime
        CNY = {2011:'20110203',2012:'20120123',2013:'20130210',2014:'20140131',2015:'20150219',2016:'20160208',
               2017:'20170128',2018:'20180216',2019:'20190205',2020:'20200125',2021:'20210212',2022:'20220201',
               2023:'20230122',2024:'20240210',2025:'20250129',2026:'20260217'}
        dd = datetime.date(int(ds[:4]), int(ds[4:6]), int(ds[6:]))
        for y, hol in CNY.items():
            h = datetime.date(y, int(hol[4:6]), int(hol[6:]))
            if h - datetime.timedelta(days=n) <= dd <= h:
                return True
        return False

    out = []
    for name, fn in cands:
        if fn is None:
            continue  # equity 族在 mine12 已证伪,不叠加
        # 同源度:该规则被拦笔 vs 候选1被拦笔
        solo_sel = R.eval_rule_fill(rows, fn, 1)
        det_solo = R.diff_detail(base8, solo_sel)
        # 叠加:9键之上
        both_fn = lambda t, _f=fn: cand1_fn(t) or _f(t)
        both_sel = R.eval_rule_fill(rows, both_fn, 1)
        det_both = R.diff_detail(base9, both_sel)   # 相对9键的增量
        det_both8 = R.diff_detail(base8, both_sel)  # 相对8键的总效果
        # 同源度
        def keyset(sel): return {R.base_key(t, fIdx) for t in sel}
        b1 = keyset(base8) - keyset(solo_sel)
        b2 = keyset(base8) - keyset(base9)
        overlap = len(b1 & b2) / max(len(b1), 1)
        out.append(dict(name=name, solo=dict(det_solo), overlay_vs9=dict(det_both),
                        total_vs8=dict(det_both8), overlap_with_cand1=round(overlap, 3)))
        print(f"{name:42s} soloNet={det_solo['net_improve']:+7.0f} | 叠加后vs9键增量={det_both['net_improve']:+7.0f} "
              f"(blk新增{det_both['blocked_n']},{det_both['blocked_pnl']:+.0f}; add替补{det_both['added_n']},{det_both['added_pnl']:+.0f}) "
              f"| vs8键总={det_both8['net_improve']:+7.0f} | 与候选1被拦重叠率={overlap:.0%}")
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(base8=R.stats_of(base8), base9=R.stats_of(base9), results=out), f, ensure_ascii=False)

if __name__ == '__main__':
    main()
