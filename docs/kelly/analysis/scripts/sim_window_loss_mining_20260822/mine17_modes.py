# -*- coding: utf-8 -*-
"""二轮挖掘 正式候选跨模式敏感性(mode A-F)(2026-08-22)。
对 mine16 的 5 个正式候选,在 B/C/D/E/F 模式下重测 vs9键增量(A 档已在 mine16)。
输出:data/mine17_modes.json
复现:python3 mine17_modes.py(依赖 mine10_features.json)
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS

FEATS_PATH = os.path.join(BASE, 'data', 'mine10_features.json')
OUT_PATH = os.path.join(BASE, 'data', 'mine17_modes.json')

def prep_mode(mode):
    tr, fIdx = load(R._ROOT + '/static-site/data/signal_kelly_trades.json')
    rows = build_mode_pool(tr, fIdx, mode)
    mm = active_month_mask(DEFAULT_FILTERS)
    mD, eD, rD = len(fIdx), len(fIdx)+1, len(fIdx)+2
    kept = [t for t in rows if passes_fade(t, fIdx, DEFAULT_FILTERS, mm, mD, eD, rD)]
    RATING_RANK = {'high':0,'mid':1,'low':2}; SIG_RANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3}
    from sim_core import calc_row
    R.IDX_PNL, R.IDX_SKEY = len(fIdx)+3, len(fIdx)+4
    for t in kept:
        t.append(calc_row(t, fIdx))
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None,'') else float('inf')
        t.append((-ts, RATING_RANK.get(str(t[fIdx['rating']] or ''),3),
                  SIG_RANK.get(str(t[fIdx['signal']] or ''),9), str(t[fIdx['buy_date']] or '')))
    return kept, fIdx

def main():
    feats = json.load(open(FEATS_PATH))
    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p*(len(vals)-1)), len(vals)-1)]
    def make_rule(fname, direction, th, sig=None, tier=None, mkt=None):
        series = feats[fname]
        def fn(t, fIdx):
            v = series.get(str(t[3]))
            if v is None: return False
            if not (v < th if direction == 'low' else v > th): return False
            if sig is not None and t[2] != sig: return False
            if tier is not None and (t[fIdx['market_tier']] or '') != tier: return False
            if mkt is not None and (t[len(fIdx)] or '') != mkt: return False
            return True
        return fn
    CANDS = [
        ('N1 北向<q30全停',      make_rule('north_d20','low',qth('north_d20',0.30))),
        ('T1 低换手×追买全停',    make_rule('turn_pct','low',qth('turn_pct',0.30),sig='buy_special')),
        ('D1 股息率<q50全停',     make_rule('div_yield','low',qth('div_yield',0.50))),
        ('Q1 QVIX分位<q10全停',   make_rule('qvix_pct','low',qth('qvix_pct',0.10))),
        ('N2 北向<q30×concept',  make_rule('north_d20','low',qth('north_d20',0.30),mkt='concept')),
    ]
    out = {}
    for mode in ['A','B','C','D','E','F']:
        rows, fIdx = prep_mode(mode)
        R.init(rows, fIdx)
        c1 = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx['market_tier']] or '')=='牛市·主升')
        base9 = R.eval_rule_fill(rows, c1, 1)
        line = {}
        for name, rule in CANDS:
            both = lambda t, _r=rule: _r(t, fIdx) or c1(t)
            new_sel = R.eval_rule_fill(rows, both, 1)
            det = R.diff_detail(base9, new_sel)
            line[name] = det['net_improve']
        out[mode] = dict(base9=R.stats_of(base9)['total'], improve=line)
        print(f"mode {mode}: base9={out[mode]['base9']:+.0f} " + ' '.join(f"{n.split()[0]}={v:+.0f}" for n,v in line.items()))
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)

if __name__ == '__main__':
    main()
