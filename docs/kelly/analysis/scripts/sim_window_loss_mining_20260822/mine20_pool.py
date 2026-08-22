# -*- coding: utf-8 -*-
"""二轮挖掘 补测⑤(2026-08-22 用户指令升级):全候选池盘点——组合池从 5 条扩到全部。
盘点范围: 二轮 mine11 正增量特征族 + mine14 异源子群 top + 一轮落选/观察型/备选(候选2/候选3/下降期×备买)。
统一口径: 每条在 9键基线(8键+候选1)上重测补位口径边际增量,>0 且非被嵌套者入组合池。
嵌套检测: 规则命中集(hit set)两两子集关系,被完全包含者标注剔除(如 N2⊂N1)。
输出: data/mine20_pool.json
复现: python3 mine20_pool.py(依赖 mine10_features.json + signal_kelly_trades.json)
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from mine18_detail import build_cands, FEATS_PATH

OUT_PATH = os.path.join(BASE, 'data', 'mine20_pool.json')

def main():
    feats = json.load(open(FEATS_PATH))
    def qth(fname, p):
        vals = sorted(v for v in feats[fname].values() if v is not None)
        return vals[min(int(p*(len(vals)-1)), len(vals)-1)]
    rows, fIdx = R.prepare_rows(); R.init(rows, fIdx)
    mD = len(fIdx)
    def feat_rule(fname, direction, th):
        series = feats[fname]
        def fn(t, _f=fIdx):
            v = series.get(str(t[3]))
            if v is None: return False
            return v < th if direction == 'low' else v > th
        return fn
    def feat_cond(fname, direction, th, sig=None, tier=None, mkt=None):
        series = feats[fname] if fname else None
        def fn(t, _f=fIdx):
            if series is not None:
                v = series.get(str(t[3]))
                if v is None: return False
                b = v < th if direction == 'low' else v > th
                if not b: return False
            if sig is not None and t[2] != sig: return False
            if sigs is not None and t[2] not in sigs: return False
            if tier is not None and (t[_f['market_tier']] or '') != tier: return False
            if mkt is not None and (t[mD] or '') != mkt: return False
            return True
        sigs = [sig] if isinstance(sig, str) else sig
        if isinstance(sig, str): sig = None
        return fn
    c1 = lambda t: (t[2] in ('buy_aux','buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')
    base9 = R.eval_rule_fill(rows, c1, 1)

    # ---- 池子候选全集(编号, 定义, 规则fn) ----
    POOL = [
        ('N1', '北向20日净流入<q30(-58亿) 全停',            feat_rule('north_d20','low',qth('north_d20',0.30))),
        ('T1', '换手率分位<q30 × buy_special 全停',         feat_cond('turn_pct','low',qth('turn_pct',0.30),sig='buy_special')),
        ('D1', '股息率<q50(2.59) 全停',                    feat_rule('div_yield','low',qth('div_yield',0.50))),
        ('Q1', 'QVIX历史分位<q10 全停',                    feat_rule('qvix_pct','low',qth('qvix_pct',0.10))),
        ('N2', '北向<q30 × concept 全停',                  feat_cond('north_d20','low',qth('north_d20',0.30),mkt='concept')),
        ('H1', '波动放大(h_volchg>q30) × A股全停',          feat_cond('h_volchg','high',qth('h_volchg',0.30),mkt='a')),
        ('M1', '两融20日变化<q70 × 牛市·主升 全停',          feat_cond('margin_chg20','low',qth('margin_chg20',0.70),tier='牛市·主升')),
        ('D2', '股息率<q70 × 牛市·主升 全停',               feat_cond('div_yield','low',qth('div_yield',0.70),tier='牛市·主升')),
        ('P1', '股息率3年分位<q30 × buy_backup 全停',       feat_cond('div_pct','low',qth('div_pct',0.30),sig='buy_backup')),
        ('V1', '20日已实现波动>q90(30.7%) 全停',            feat_rule('h_vol20','high',qth('h_vol20',0.90))),
        ('V2', '一轮候选3: 20日已实现波动≥25% 全停',         feat_rule('h_vol20','high',25.0)),
        ('S1', 'A股情绪分<q20 全停',                       feat_rule('sent_a','low',qth('sent_a',0.20))),
        ('R1', '全市场量能萎缩(vol_ratio_all<q10) 全停',     feat_rule('vol_ratio_all','low',qth('vol_ratio_all',0.10))),
        ('S2', '沪深300情绪分<q20 全停',                    feat_rule('sent_hs300','low',qth('sent_hs300',0.20))),
        ('W1', '一轮观察型: 下降期×buy_backup 全停',          feat_cond(None,None,None,sig='buy_backup',tier='下降期')),
        ('A1', '一轮候选2激进版: 牛市·主升全类型 全停',        feat_cond(None,None,None,tier='牛市·主升')),
        ('V3', '20日已实现波动<q10(低波动) 全停',            feat_rule('h_vol20','low',qth('h_vol20',0.10))),
        ('AD1','AD线缺口>q70(宽度强) 全停',                 feat_rule('adline_gap','high',qth('adline_gap',0.70))),
    ]
    out = []
    hitsets = {}
    for code, desc, fn in POOL:
        both = lambda t, _f=fn: _f(t) or c1(t)
        ns = R.eval_rule_fill(rows, both, 1)
        det = R.diff_detail(base9, ns)
        g = R.three_gates(base9, ns, det)
        hit = {R.base_key(t, fIdx) for t in rows if fn(t)}
        hitsets[code] = hit
        out.append(dict(code=code, desc=desc, vs9_net=det['net_improve'],
                        blocked_n=det['blocked_n'], blocked_pnl=det['blocked_pnl'],
                        added_n=det['added_n'], added_pnl=det['added_pnl'],
                        hit_n=len(hit), gates=dict(g1=g['g1'], g2=g['g2'], g3=g['g3']),
                        apr_hurt=g['apr_hurt'], mayaug=g['mayaug_improve'],
                        fwd=g['forward']['net_improve']))
        print('%-4s %-36s vs9键增量=%+8.0f (拦%3d/替%2d) G1%s G2%s G3%s' % (
            code, desc[:34], det['net_improve'], det['blocked_n'], det['added_n'],
            g['g1'], g['g2'], g['g3']))
    # ---- 嵌套检测(hit 集子集关系) ----
    nested = {}
    codes = [c for c, _, _ in POOL]
    for a in codes:
        for b in codes:
            if a == b or not hitsets[a] or not hitsets[b]: continue
            if hitsets[a] < hitsets[b] or hitsets[a] == hitsets[b] and a != b:
                if hitsets[a] <= hitsets[b]:
                    nested.setdefault(a, []).append(b if hitsets[a] < hitsets[b] else b+'(相等)')
    for r in out:
        r['nested_in'] = nested.get(r['code'], [])
    # ---- 入池判定: vs9键边际>0 且不存在「同样入池的超集」----
    # (嵌套宿主本身落池时不连带剔——如 M1⊂A1 但 A1 负增量不入池, M1 与池内规则不冗余照常入池)
    pos_codes = [r['code'] for r in out if r['vs9_net'] > 0]
    pool_in = [c for c in pos_codes if not any(h in pos_codes for h in nested.get(c, []))]
    print('\n== 嵌套关系 ==')
    for a, bs in nested.items():
        print(' ', a, '⊂', bs)
    print('\n== 入组合池(vs9键边际>0 且未被嵌套): N =', len(pool_in))
    print(' ', pool_in)
    print('== 落池(vs9键边际<=0 或被嵌套):', [r['code'] for r in out if r['code'] not in pool_in])
    with open(OUT_PATH, 'w') as f:
        json.dump(dict(candidates=out, pool_in=pool_in, nested=nested), f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
