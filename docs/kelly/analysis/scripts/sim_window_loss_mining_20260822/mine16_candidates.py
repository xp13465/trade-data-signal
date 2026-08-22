# -*- coding: utf-8 -*-
"""二轮挖掘 正式候选完整检验(vs 9键)(2026-08-22)。
对叠加测试中「真实增量」存在的异源候选,按一轮同规格出全维度:
  - vs9键 三道门(blocked_n>=30 / 2026双向 / 前向2024-26+按年负占比)
  - 新增被拦类按年桶分布 + 替补盈亏分解
  - K1-K4 敏感性 + A-F 跨模式(mode A-F 各自基笔池)
输出:data/mine16_candidates.json
复现:python3 mine16_candidates.py(依赖 mine10_features.json)
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS

FEATS_PATH = os.path.join(BASE, 'data', 'mine10_features.json')
OUT_PATH = os.path.join(BASE, 'data', 'mine16_candidates.json')

def cand1_fn(fIdx):
    def fn(t):
        return (t[2] in ('buy_aux', 'buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')
    return fn

def build_rows_for_mode(mode):
    tr, fIdx = load()
    rows = build_mode_pool(tr, fIdx, mode)
    mm = active_month_mask(DEFAULT_FILTERS)
    mD, eD, rD = len(fIdx), len(fIdx)+1, len(fIdx)+2
    kept = [t for t in rows if passes_fade(t, fIdx, DEFAULT_FILTERS, mm, mD, eD, rD)]
    RATING_RANK = {'high':0,'mid':1,'low':2}; SIG_RANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3}
    for t in kept:
        t.append(None); t.append(None)
    # 复用 calc_row/skey 结构(与 prepare_rows 一致的追加索引)
    for t in kept:
        t[len(fIdx)+3] = R.calc_row_pub(t, fIdx)
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None,'') else float('inf')
        t[len(fIdx)+4] = (-ts, RATING_RANK.get(str(t[fIdx['rating']] or ''),3),
                          SIG_RANK.get(str(t[fIdx['signal']] or ''),9), str(t[fIdx['buy_date']] or ''))
    return kept, fIdx

def main():
    feats = json.load(open(FEATS_PATH))
    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p*(len(vals)-1)), len(vals)-1)]

    def make_rule(fname=None, direction=None, th=None, sig=None, tier=None, mkt=None):
        series = feats[fname] if fname else None
        def fn(t, fIdx):
            if fname is not None:
                v = series.get(str(t[3]))
                if v is None: return False
                b = v < th if direction == 'low' else v > th
                if not b: return False
            if sig is not None and t[2] != sig: return False
            if tier is not None and (t[fIdx['market_tier']] or '') != tier: return False
            if mkt is not None and (t[len(fIdx)] or '') != mkt: return False
            return True
        return fn

    CANDS = [
        ('N1 北向20日净流入<q30(-58亿)全停',   make_rule('north_d20','low',qth('north_d20',0.30))),
        ('T1 低换手分位(<q30)×追买全停',       make_rule('turn_pct','low',qth('turn_pct',0.30),sig='buy_special')),
        ('D1 股息率<q50(2.59)全停',           make_rule('div_yield','low',qth('div_yield',0.50))),
        ('Q1 QVIX历史分位<q10 全停',           make_rule('qvix_pct','low',qth('qvix_pct',0.10))),
        ('N2 北向<q30×concept 全停',           make_rule('north_d20','low',qth('north_d20',0.30),mkt='concept')),
    ]

    results = []
    for name, rule in CANDS:
        res = dict(name=name)
        # --- 主口径:mode A K1 vs 9键 ---
        rows, fIdx = R.prepare_rows(); R.init(rows, fIdx)
        c1 = cand1_fn(fIdx)
        base9 = R.eval_rule_fill(rows, c1, 1)
        both = lambda t, _r=rule: _r(t, fIdx) or c1(t)
        new_sel = R.eval_rule_fill(rows, both, 1)
        det = R.diff_detail(base9, new_sel)
        gates = R.three_gates(base9, new_sel, det)
        # 新增被拦类按年桶
        def keyset(sel): return {R.base_key(t, fIdx): t for t in sel}
        b9, bn = keyset(base9), keyset(new_sel)
        newly_blocked = [b9[k] for k in b9 if k not in bn]
        byb = {}
        for t in newly_blocked:
            byb.setdefault(str(t[0])[:4], []).append(t[R.IDX_PNL]['pnlYuan'])
        ysum = {y: round(sum(v),2) for y,v in sorted(byb.items())}
        res['fill'] = dict(det, new_total=R.stats_of(new_sel)['total'])
        res['gates'] = gates
        res['newly_blocked_yearly'] = ysum
        res['newly_blocked_neg_years'] = sum(1 for v in ysum.values() if v<0)
        res['newly_blocked_total_years'] = len(ysum)
        # --- K1-K4 敏感性 ---
        kk = {}
        for K in (1,2,3,4):
            b_k = R.eval_rule_fill(rows, c1, K)
            n_k = R.eval_rule_fill(rows, both, K)
            kk[f'K{K}'] = dict(base=R.stats_of(b_k)['total'], new=R.stats_of(n_k)['total'],
                               improve=round(R.stats_of(n_k)['total']-R.stats_of(b_k)['total'],2))
        res['k_sensitivity'] = kk
        results.append(res)
        g = gates
        print(f"== {name}")
        print(f"   vs9键增量={det['net_improve']:+.0f} (新增被拦 {det['blocked_n']}笔 {det['blocked_pnl']:+.0f} / 替补 {det['added_n']}笔 {det['added_pnl']:+.0f})")
        print(f"   三道门 G1(n={det['blocked_n']}>=30:{g['g1']}) G2(4月误伤{g['apr_hurt']:+.0f}/5-8月改善{g['mayaug_improve']:+.0f}:{g['g2']}) "
              f"G3(前向{g['forward']['net_improve']:+.0f}/负占比{res['newly_blocked_neg_years']}/{res['newly_blocked_total_years']}={gates['blocked_neg_ratio']:.0%}:{g['g3']})")
        print(f"   按年桶(新增被拦): {ysum}")
        print(f"   K敏感性: " + ' '.join(f"{k}:{v['improve']:+.0f}" for k,v in kk.items()))
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(results=results), f, ensure_ascii=False, default=str)

if __name__ == '__main__':
    main()
