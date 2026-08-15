# -*- coding: utf-8 -*-
"""候选子群组合剔除测试: 1-3个候选并集剔除的叠加边际"""
import sys, json, itertools
sys.path.insert(0, '/tmp')
from kelly_engine import KellyEngine, load_trades, AI_MACRO

MODES = ['A','B','C','D','E','F','G','H','I']
td = load_trades()
eng = KellyEngine(td)
fi = eng.fIdx

def t_attrs(t):
    dk = eng._dim_key(t)
    mkt = eng._dims.get(dk, {}).get('mkt', '')
    return dict(sig=str(t[fi['signal']] or ''), etf=str(t[fi['track_tier']] or ''),
                rat=str(t[fi['rating']] or ''), mkt=mkt)
attr_cache = {}
def attr_of(t):
    bk = eng.base_key(t)
    if bk not in attr_cache: attr_cache[bk] = t_attrs(t)
    return attr_cache[bk]

CAND = {
    'C1主关注×概念': lambda a: a['sig']=='buy' and a['mkt']=='concept',
    'C2追关注×港股': lambda a: a['sig']=='buy_special' and a['mkt']=='hk',
    'C3高评级×A股': lambda a: a['rat']=='high' and a['mkt']=='a',
    'C4高评级×概念': lambda a: a['rat']=='high' and a['mkt']=='concept',
    'C5备关注×港股': lambda a: a['sig']=='buy_backup' and a['mkt']=='hk',
    'C6弱无ETF×概念': lambda a: a['etf']=='none' and a['mkt']=='concept',
}

# 预计算每个候选的 keyset
keysets = {}
for name, pred in CAND.items():
    ks = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(attr_of(t)): ks.add(eng.base_key(t))
    keysets[name] = ks
    print(f"{name}: 基笔 {len(ks)}")

base = eng.compute_quad_stats(eng._all_by_mode, periods=('all','y1'))
b = dict(A_all=base['all']['A']['total_profit'], G_all=base['all']['G']['total_profit'],
         A_y1=base['y1']['A']['total_profit'], G_y1=base['y1']['G']['total_profit'])
print(f"\n基线: A_all={b['A_all']:+,.0f} G_all={b['G_all']:+,.0f} | A_y1={b['A_y1']:+,.0f} G_y1={b['G_y1']:+,.0f}")
print(f"\n{'组合':<30} {'n':>6} | {'all AΔ':>10} {'all GΔ':>10} | {'y1 AΔ':>9} {'y1 GΔ':>9}")

def eval_combo(names):
    excl = set()
    for n in names: excl |= keysets[n]
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=excl, periods=('all','y1'))
    return dict(dA_all=st['all']['A']['total_profit']-b['A_all'], dG_all=st['all']['G']['total_profit']-b['G_all'],
                dA_y1=st['y1']['A']['total_profit']-b['A_y1'], dG_y1=st['y1']['G']['total_profit']-b['G_y1'],
                n=len(excl))

# 单个
print("--- 单个 ---")
for name in CAND:
    m = eval_combo([name])
    print(f"{name:<30} {m['n']:>6} | {m['dA_all']:>+10,.0f} {m['dG_all']:>+10,.0f} | {m['dA_y1']:>+9,.0f} {m['dG_y1']:>+9,.0f}")

# 两两
print("--- 两两 ---")
names = list(CAND.keys())
rows2 = []
for a, b2 in itertools.combinations(names, 2):
    m = eval_combo([a, b2])
    rows2.append((f"{a}+{b2}", m))
rows2.sort(key=lambda r: r[1]['dA_all']+r[1]['dG_all'], reverse=True)
for name, m in rows2[:12]:
    print(f"{name:<30} {m['n']:>6} | {m['dA_all']:>+10,.0f} {m['dG_all']:>+10,.0f} | {m['dA_y1']:>+9,.0f} {m['dG_y1']:>+9,.0f}")

# 三三
print("--- 三三(top) ---")
rows3 = []
for comb in itertools.combinations(names, 3):
    m = eval_combo(list(comb))
    rows3.append(("+".join(c[1:3] for c in comb), m))
rows3.sort(key=lambda r: r[1]['dA_all']+r[1]['dG_all'], reverse=True)
for name, m in rows3[:10]:
    print(f"{name:<30} {m['n']:>6} | {m['dA_all']:>+10,.0f} {m['dG_all']:>+10,.0f} | {m['dA_y1']:>+9,.0f} {m['dG_y1']:>+9,.0f}")

# 全部组合
m = eval_combo(names)
print(f"\n--- 全6候选并集 ---")
print(f"{'+'.join(c[1:3] for c in names):<30} {m['n']:>6} | {m['dA_all']:>+10,.0f} {m['dG_all']:>+10,.0f} | {m['dA_y1']:>+9,.0f} {m['dG_y1']:>+9,.0f}")
