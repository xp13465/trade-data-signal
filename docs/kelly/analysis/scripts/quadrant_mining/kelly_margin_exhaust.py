# -*- coding: utf-8 -*-
"""穷举: signal×mkt / etf×mkt / rat×mkt 全组合剔除边际(双周期 all+y1, A/G 模式)"""
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
                rat=str(t[fi['rating']] or ''), mkt=mkt, mm=str(t[fi['buy_date']] or '')[4:6])

attr_cache = {}
def attr_of(t):
    bk = eng.base_key(t)
    if bk not in attr_cache:
        attr_cache[bk] = t_attrs(t)
    return attr_cache[bk]

# 基线
base = eng.compute_quad_stats(eng._all_by_mode, periods=('all','y1'))
b = dict(A_all=base['all']['A']['total_profit'], G_all=base['all']['G']['total_profit'],
         A_y1=base['y1']['A']['total_profit'], G_y1=base['y1']['G']['total_profit'])
print(f"基线: A_all={b['A_all']:+,.0f} G_all={b['G_all']:+,.0f} | A_y1={b['A_y1']:+,.0f} G_y1={b['G_y1']:+,.0f}")
print()

SIGS = ['buy','buy_aux','buy_special','buy_backup']
MKTS = ['a','hk','global','industry','concept']
ETFS = ['strong','related','approx','none']
RATS = ['high','mid','low']

def excl_margin(pred):
    keyset = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(attr_of(t)):
                keyset.add(eng.base_key(t))
    if not keyset: return None
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=keyset, periods=('all','y1'))
    return dict(dA_all=st['all']['A']['total_profit']-b['A_all'], dG_all=st['all']['G']['total_profit']-b['G_all'],
                dA_y1=st['y1']['A']['total_profit']-b['A_y1'], dG_y1=st['y1']['G']['total_profit']-b['G_y1'],
                n=len(keyset))

results = {}

def report(group, combos, label_fn):
    print(f"\n===== {group} =====")
    rows = []
    for combo in combos:
        pred = lambda a, c=combo: all(attr == a[key] for key, attr in c.items())
        m = excl_margin(pred)
        if m is None: continue
        rows.append((label_fn(combo), m))
    # 按 all A+G 双模式边际和排序
    rows.sort(key=lambda r: (r[1]['dA_all'] + r[1]['dG_all']), reverse=True)
    print(f"{'子群':<22} {'n':>6} | {'all AΔ':>10} {'all GΔ':>10} | {'y1 AΔ':>9} {'y1 GΔ':>9} | 双周期双正?")
    for name, m in rows:
        both_pos = (m['dA_all']>0 and m['dG_all']>0 and m['dA_y1']>0 and m['dG_y1']>0)
        flag = '✓✓' if both_pos else ('✓' if (m['dA_all']>0 and m['dG_all']>0) else '')
        print(f"{name:<22} {m['n']:>6} | {m['dA_all']:>+10,.0f} {m['dG_all']:>+10,.0f} | {m['dA_y1']:>+9,.0f} {m['dG_y1']:>+9,.0f} | {flag}")
        results[(group, name)] = m

sig_label = {'buy':'主','buy_aux':'辅','buy_special':'追','buy_backup':'备'}
mkt_label = {'a':'A股','hk':'港股','global':'全球','industry':'申万','concept':'概念'}
etf_label = {'strong':'强','related':'相关','approx':'近似','none':'弱/无'}
rat_label = {'high':'高','mid':'中','low':'低'}

report('信号×市场', [dict(sig=s, mkt=m) for s in SIGS for m in MKTS],
       lambda c: f"{sig_label[c['sig']]}关注×{mkt_label[c['mkt']]}")
report('ETF×市场', [dict(etf=e, mkt=m) for e in ETFS for m in MKTS],
       lambda c: f"{etf_label[c['etf']]}ETF×{mkt_label[c['mkt']]}")
report('评级×市场', [dict(rat=r, mkt=m) for r in RATS for m in MKTS],
       lambda c: f"{rat_label[c['rat']]}评级×{mkt_label[c['mkt']]}")
report('信号×ETF', [dict(sig=s, etf=e) for s in SIGS for e in ETFS],
       lambda c: f"{sig_label[c['sig']]}关注×{etf_label[c['etf']]}ETF")

with open('/tmp/kelly_margin_exhaust.json', 'w') as f:
    json.dump(dict(baseline=b, results={f"{k[0]}|{k[1]}": v for k, v in results.items()}), f, ensure_ascii=False, indent=1, default=str)
print("\nsaved /tmp/kelly_margin_exhaust.json")
