# -*- coding: utf-8 -*-
"""fixed 口径对照 + 月份细分 + 象限卡片影响验证"""
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

CAND = {
    'C1主关注×概念': lambda a: a['sig']=='buy' and a['mkt']=='concept',
    'C2追关注×港股': lambda a: a['sig']=='buy_special' and a['mkt']=='hk',
    'C5备关注×港股': lambda a: a['sig']=='buy_backup' and a['mkt']=='hk',
    'C2+C5港股追涨': lambda a: a['sig'] in ('buy_special','buy_backup') and a['mkt']=='hk',
}
KS = {k: set() for k in CAND}
for mk in MODES:
    for t in eng._all_by_mode[mk]:
        a = attr_of(t)
        for k, pred in CAND.items():
            if pred(a): KS[k].add(eng.base_key(t))

# 1. fixed 口径对照(每笔1万, 保留 kept 过滤但不重分配金额)
base_fixed = eng.compute_quad_stats_fixed(eng._all_by_mode, periods=('all','y1'))
print("=== fixed 口径(每笔1万)剔除边际 ===")
print(f"基线 fixed: A_all={base_fixed['all']['A']['total_profit']:+,.0f} G_all={base_fixed['all']['G']['total_profit']:+,.0f} | "
      f"A_y1={base_fixed['y1']['A']['total_profit']:+,.0f} G_y1={base_fixed['y1']['G']['total_profit']:+,.0f}")
for name in ('C1主关注×概念','C2追关注×港股','C2+C5港股追涨'):
    st = eng.compute_quad_stats_fixed(eng._all_by_mode, exclude_keys=KS[name], periods=('all','y1'))
    dA_all = st['all']['A']['total_profit'] - base_fixed['all']['A']['total_profit']
    dG_all = st['all']['G']['total_profit'] - base_fixed['all']['G']['total_profit']
    dA_y1 = st['y1']['A']['total_profit'] - base_fixed['y1']['A']['total_profit']
    dG_y1 = st['y1']['G']['total_profit'] - base_fixed['y1']['G']['total_profit']
    print(f"  {name:<18} all AΔ={dA_all:>+9,.0f} GΔ={dG_all:>+9,.0f} | y1 AΔ={dA_y1:>+9,.0f} GΔ={dG_y1:>+9,.0f}")

# 2. C1/C2 月份细分
print("\n=== 月份细分(9模式合计保留交易, 全周期) ===")
for name in ('C1主关注×概念','C2追关注×港股'):
    pool = eng.collect_base_pool(AI_MACRO)
    kept = eng._kept_keys(pool, 1)
    day_counts = eng._day_counts(kept)
    monthly = defaultdict(lambda: dict(n=0, p=0.0))
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            bk = eng.base_key(t)
            if bk not in KS[name]: continue
            if not eng.passes_fade(t, AI_MACRO): continue
            if bk not in kept: continue
            amt = 10000 / day_counts.get(str(t[fi['signal_date']]), 1)
            p, rp, fee = eng.recompute(t, amt)
            mm = str(t[fi['buy_date']] or '')[4:6]
            monthly[mm]['n'] += 1; monthly[mm]['p'] += p
    print(f"\n{name}:")
    for mm in sorted(monthly):
        m = monthly[mm]
        print(f"  {mm}月: 净利{m['p']:>+9,.0f} (n={m['n']:>3})", end='')
        if mm == '12': print()
    print()

# 3. 象限卡片影响: C2+C5 剔除后 16 象限 y1 自身净利
print("=== 剔除 C2+C5 港股追涨后, 16象限 y1 自身净利变化 ===")
QUAD_LABELS = {'rating_high':'高评级','rating_mid':'中评级','rating_low':'低评级',
    'etf_strong':'强关联ETF','etf_related':'相关ETF','etf_approx':'近似ETF','etf_has_track':'有跟踪ETF',
    'sig_main':'主关注','sig_aux':'辅关注','sig_special':'追关注','sig_backup':'备关注',
    'mkt_a':'A股宽基','mkt_hk':'港股','mkt_global':'全球/国债','mkt_industry':'申万行业','mkt_concept':'概念/主题'}
excl = KS['C2+C5港股追涨']
for qk, label in QUAD_LABELS.items():
    quad_trades = eng._quad_trades[qk]
    st0 = eng.compute_quad_stats(quad_trades, periods=('y1','all'))
    st1 = eng.compute_quad_stats(quad_trades, exclude_keys=excl, periods=('y1','all'))
    p0y = sum(st0['y1'][m]['total_profit'] for m in MODES)
    p1y = sum(st1['y1'][m]['total_profit'] for m in MODES)
    p0a = sum(st0['all'][m]['total_profit'] for m in MODES)
    p1a = sum(st1['all'][m]['total_profit'] for m in MODES)
    print(f"  {label:<10} y1: {p0y:>+9,.0f} → {p1y:>+9,.0f} (Δ{p1y-p0y:>+7,.0f}) | all: {p0a:>+10,.0f} → {p1a:>+10,.0f}")
