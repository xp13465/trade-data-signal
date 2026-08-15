# -*- coding: utf-8 -*-
"""K1 追关注×港股×1月下旬 验证: 剔除边际 + 按年稳定性 + 港股卡翻正"""
import sys, json
sys.path.insert(0, '/tmp')
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from collections import defaultdict

MODES = ['A','B','C','D','E','F','G','H','I']
td = load_trades()
eng = KellyEngine(td)
fi = eng.fIdx

def t_attrs(t):
    dk = eng._dim_key(t)
    mkt = eng._dims.get(dk, {}).get('mkt', '')
    return dict(sig=str(t[fi['signal']] or ''), etf=str(t[fi['track_tier']] or ''),
                rat=str(t[fi['rating']] or ''), mkt=mkt, bd=str(t[fi['buy_date']] or ''))
attr_cache = {}
def attr_of(t):
    bk = eng.base_key(t)
    if bk not in attr_cache: attr_cache[bk] = t_attrs(t)
    return attr_cache[bk]

# K1: buy_special + hk + 01月21-31
def pred_k1(a):
    return a['sig']=='buy_special' and a['mkt']=='hk' and a['bd'][4:6]=='01' and int(a['bd'][6:8])>=21
def pred_k2(a):
    return a['sig']=='buy_special' and a['mkt']=='hk'
def pred_k2c5(a):
    return a['sig'] in ('buy_special','buy_backup') and a['mkt']=='hk'

KS = {}
for name, pred in (('K1',pred_k1),('K2',pred_k2),('K2C5',pred_k2c5)):
    ks = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(attr_of(t)): ks.add(eng.base_key(t))
    KS[name] = ks
    print(f"{name}: 基笔 {len(ks)}")

base = eng.compute_quad_stats(eng._all_by_mode, periods=('all','y1'))
b = dict(A_all=base['all']['A']['total_profit'], G_all=base['all']['G']['total_profit'],
         A_y1=base['y1']['A']['total_profit'], G_y1=base['y1']['G']['total_profit'])
print(f"\n基线: A_all={b['A_all']:+,.0f} G_all={b['G_all']:+,.0f} | A_y1={b['A_y1']:+,.0f} G_y1={b['G_y1']:+,.0f}")

print("\n=== 剔除边际 ===")
for name in ('K1','K2','K2C5'):
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=KS[name], periods=('all','y1'))
    dA_all = st['all']['A']['total_profit'] - b['A_all']; dG_all = st['all']['G']['total_profit'] - b['G_all']
    dA_y1 = st['y1']['A']['total_profit'] - b['A_y1']; dG_y1 = st['y1']['G']['total_profit'] - b['G_y1']
    print(f"  {name:<6} all AΔ={dA_all:>+8,.0f} GΔ={dG_all:>+8,.0f} | y1 AΔ={dA_y1:>+8,.0f} GΔ={dG_y1:>+8,.0f}")

# K1 按年稳定性
print("\n=== K1(追关注×港股×1月下旬)按年 ===")
pool = eng.collect_base_pool(AI_MACRO)
kept = eng._kept_keys(pool, 1)
day_counts = eng._day_counts(kept)
yr = defaultdict(lambda: dict(n=0, p=0.0))
for mk in MODES:
    for t in eng._all_by_mode[mk]:
        if not pred_k1(attr_of(t)): continue
        if not eng.passes_fade(t, AI_MACRO): continue
        if eng.base_key(t) not in kept: continue
        amt = 10000 / day_counts.get(str(t[fi['signal_date']]), 1)
        p, rp, fee = eng.recompute(t, amt)
        y = str(t[fi['buy_date']] or '')[0:4]
        yr[y]['n'] += 1; yr[y]['p'] += p
for y in sorted(yr):
    print(f"  {y}: 净利{yr[y]['p']:>+9,.0f} (n={yr[y]['n']})")

# K1 剔除后 16 象限 y1(港股卡翻正?)
print("\n=== K1 剔除后 16 象限 y1 自身净利 ===")
QUAD_LABELS = {'rating_high':'高评级','rating_mid':'中评级','rating_low':'低评级',
    'etf_strong':'强关联ETF','etf_related':'相关ETF','etf_approx':'近似ETF','etf_has_track':'有跟踪ETF',
    'sig_main':'主关注','sig_aux':'辅关注','sig_special':'追关注','sig_backup':'备关注',
    'mkt_a':'A股宽基','mkt_hk':'港股','mkt_global':'全球/国债','mkt_industry':'申万行业','mkt_concept':'概念/主题'}
for qk, label in QUAD_LABELS.items():
    quad_trades = eng._quad_trades[qk]
    st0 = eng.compute_quad_stats(quad_trades, periods=('y1',))
    st1 = eng.compute_quad_stats(quad_trades, exclude_keys=KS['K1'], periods=('y1',))
    p0 = sum(st0['y1'][m]['total_profit'] for m in MODES)
    p1 = sum(st1['y1'][m]['total_profit'] for m in MODES)
    mark = ' <== 翻正!' if (p0<0 and p1>0) else ''
    print(f"  {label:<10} y1: {p0:>+9,.0f} → {p1:>+9,.0f} (Δ{p1-p0:>+7,.0f}){mark}")
