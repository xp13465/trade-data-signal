# -*- coding: utf-8 -*-
"""Part I: 候选规则跨模式验证 + 合并 + 2025vs2026状态线 + G/H/I叠加"""
import sys, json
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)
def pnl(rows): return sum(S.calc_row(t,fIdx)['pnlYuan'] for t in rows)

with open('/Users/linhuichen/code/trade/static-site/data/market_tier_history.json') as f:
    hist = json.load(f)
print('=== 2025-2026 四档切换点对照 ===')
prev=None
for h in hist:
    if '20250101' <= h['date'] <= '20260821':
        if h['tier'] != prev:
            print(f"  {h['date']} -> {h['tier']}")
            prev=h['tier']

CANDS = {
    '停 牛主升×辅买': lambda t: (t[fIdx['market_tier']] or '')=='牛市·主升' and t[fIdx['signal']]=='buy_aux',
    '停 牛主升×备买': lambda t: (t[fIdx['market_tier']] or '')=='牛市·主升' and t[fIdx['signal']]=='buy_backup',
    '停 牛主升×(辅买∪备买)': lambda t: (t[fIdx['market_tier']] or '')=='牛市·主升' and t[fIdx['signal']] in ('buy_aux','buy_backup'),
}
print()
print('=' * 100)
print('Part I1: 候选规则 × 9 模式(mode A-I, K1 口径基线上叠加). 被砍净额负=好')
print(f"{'模式':<6}{'候选':<24}{'全史砍':>9}{'按年负占比':>9}{'23前':>9}{'24-26前向':>10}{'26年5-8月砍':>11}{'26年4月误伤':>11}")
for mode in 'ABCDEFGHI':
    pool=S.build_mode_pool(tr,fIdx,mode)
    fade=[t for t in pool if S.passes_fade(t,fIdx,filters,mmask,mD,eD,rD)]
    k1=S.topk_by_date(fade,fIdx,1)
    for name,pred in CANDS.items():
        cut=[t for t in k1 if pred(t)]
        years={}
        for t in cut:
            y=(t[fIdx['signal_date']] or '')[:4]; years.setdefault(y,0.0); years[y]+=S.calc_row(t,fIdx)['pnlYuan']
        neg=sum(1 for v in years.values() if v<0)
        c58=pnl([t for t in cut if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900'])
        capr=pnl([t for t in cut if (t[fIdx['signal_date']] or '').startswith('202604')])
        cf=pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4]<='2023'])
        co=pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4]>='2024'])
        print(f"{mode:<6}{name:<24}{pnl(cut):>+9.0f}{f'{neg}/{len(years)}':>9}{cf:>+9.0f}{co:>+10.0f}{c58:>+11.0f}{capr:>+11.0f}")

print()
print('=' * 100)
print('Part I2: 最优候选叠加后 · mode A K1 · 2026 逐月 + 对照线对比')
print('=' * 100)
pool=S.build_mode_pool(tr,fIdx,'A')
fade=[t for t in pool if S.passes_fade(t,fIdx,filters,mmask,mD,eD,rD)]
k1=S.topk_by_date(fade,fIdx,1)
best=CANDS['停 牛主升×(辅买∪备买)']
kept=[t for t in k1 if not best(t)]
m26={}; m26k={}
for t in k1:
    if (t[fIdx['signal_date']] or '').startswith('2026'):
        m26.setdefault((t[fIdx['signal_date']])[:6],[]).append(t)
for t in kept:
    if (t[fIdx['signal_date']] or '').startswith('2026'):
        m26k.setdefault((t[fIdx['signal_date']])[:6],[]).append(t)
print('月份     基线净额   叠加后净额')
c1=c2=0
for mm in sorted(m26):
    a=pnl(m26[mm]); b=pnl(m26k.get(mm,[]))
    c1+=a; c2+=b
    print(f'{mm}   {a:>+9.0f}   {b:>+9.0f}')
print(f'2026合计 {c1:>+9.0f}   {c2:>+9.0f}   (4月末空仓锚点=+10792)')
st_k=S.window_stats(k1,fIdx); st_b=S.window_stats([t for t in kept if True],fIdx)
print(f'全历史: 基线={pnl(k1):+.0f} -> 叠加后={pnl(kept):+.0f}')

print()
print('=' * 100)
print('Part I3: G/H/I 长线组 · 候选叠加(它们持仓中浮亏大, 时段规则对长线意义)')
print('=' * 100)
for mode in 'GHI':
    pool=S.build_mode_pool(tr,fIdx,mode)
    fade=[t for t in pool if S.passes_fade(t,fIdx,filters,mmask,mD,eD,rD)]
    k1=S.topk_by_date(fade,fIdx,1)
    r26=[t for t in k1 if (t[fIdx['signal_date']] or '').startswith('2026')]
    hold=[t for t in r26 if not str(t[fIdx['sell_date']] or '')]
    print(f'模式{mode}: 2026基线={pnl(r26):>+8.0f}(其中持仓中{len(hold)}笔={pnl(hold):>+8.0f})', end='')
    # 牛主升×辅备买 在长线的贡献
    cut=[t for t in k1 if best(t)]
    c58=pnl([t for t in cut if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900'])
    print(f' | 候选被砍全史={pnl(cut):>+9.0f}(n={len(cut)}) 5-8月砍={c58:>+8.0f}')
