# -*- coding: utf-8 -*-
"""候选子群按年稳定性分解 + 最优组合完整效果"""
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

def keyset_for(pred):
    ks = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(attr_of(t)): ks.add(eng.base_key(t))
    return ks

CAND = {
    'C1主关注×概念': lambda a: a['sig']=='buy' and a['mkt']=='concept',
    'C2追关注×港股': lambda a: a['sig']=='buy_special' and a['mkt']=='hk',
    'C5备关注×港股': lambda a: a['sig']=='buy_backup' and a['mkt']=='hk',
}
KS = {k: keyset_for(v) for k, v in CAND.items()}

# 按年分解: 每个候选在 AI宏+poscapK1 下保留交易的按年净利(9模式合计, 全周期)
print("候选子群保留交易的按年净利(9模式合计, 默认 AI宏 K1 每日池):")
print("-" * 90)
for name, ks in KS.items():
    # 计算 positionCap kept(全局)
    pool = eng.collect_base_pool(AI_MACRO)
    kept = eng._kept_keys(pool, 1)
    day_counts = eng._day_counts(kept)
    # 该子群保留交易按年
    yearly = defaultdict(lambda: dict(n=0, p=0.0))
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            bk = eng.base_key(t)
            if bk not in ks: continue
            if not eng.passes_fade(t, AI_MACRO): continue
            if bk not in kept: continue
            amt = 10000 / day_counts.get(str(t[fi['signal_date']]), 1)
            p, rp, fee = eng.recompute(t, amt)
            yr = str(t[fi['buy_date']] or '')[0:4]
            yearly[yr]['n'] += 1
            yearly[yr]['p'] += p
    yrs = sorted(yearly)
    print(f"\n{name} (基笔 {len(ks)}):")
    parts = []
    for yr in yrs:
        y = yearly[yr]
        parts.append(f"  {yr}: 净利{y['p']:+,.0f}(n={y['n']})")
    print(''.join(parts))
    # 按 y1 期(>=20250815)
    y1p = sum(v['p'] for yr, v in yearly.items() if yr >= '2025' and v['n'])
    # 计算2026
    p2026 = yearly.get('2026', {}).get('p', 0)
    allp = sum(v['p'] for v in yearly.values())
    print(f"  → 全周期合计 {allp:+,.0f} | 2026年占比 {p2026/allp*100 if allp else 0:.0f}% | 2026净利 {p2026:+,.0f}")

# 最优组合完整效果
print("\n" + "=" * 90)
print("最优组合 C1+C2+C5 剔除后全信号完整效果(每日池 K1):")
combo_ks = KS['C1主关注×概念'] | KS['C2追关注×港股'] | KS['C5备关注×港股']
st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=combo_ks, periods=('all','y1'))
for pk in ('all','y1'):
    for m in ('A','G'):
        s = st[pk][m]
        print(f"  {pk} {m}: 净利={s['total_profit']:+,.0f} 收益率={s['return_pct_max_holding']:.2f}% "
              f"峰持仓={s['max_concurrent_capital']/10000:.1f}万 n={s['n']} 胜率={s['win_rate']*100:.1f}%")

# 基线对比
base = eng.compute_quad_stats(eng._all_by_mode, periods=('all','y1'))
print("\n基线:")
for pk in ('all','y1'):
    for m in ('A','G'):
        s = base[pk][m]
        print(f"  {pk} {m}: 净利={s['total_profit']:+,.0f} 收益率={s['return_pct_max_holding']:.2f}% "
              f"峰持仓={s['max_concurrent_capital']/10000:.1f}万 n={s['n']} 胜率={s['win_rate']*100:.1f}%")

with open('/tmp/kelly_yearly.json','w') as f:
    json.dump(dict(combo_ks=len(combo_ks)), f)
