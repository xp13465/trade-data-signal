# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '/tmp/simbt')
import simcore as S
tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS; mmask = S.active_month_mask(filters)
def pnl(rows): return sum(S.calc_row(t,fIdx)['pnlYuan'] for t in rows)
poolA=S.build_mode_pool(tr,fIdx,'A')
fadeA=[t for t in poolA if S.passes_fade(t,fIdx,filters,mmask,mD,eD,rD)]
k1A=S.topk_by_date(fadeA,fIdx,1)
best=lambda t:(t[fIdx['market_tier']] or '')=='牛市·主升' and t[fIdx['signal']] in ('buy_aux','buy_backup')

# 2025 误伤拆解
cut25=[t for t in k1A if best(t) and (t[fIdx['signal_date']] or '').startswith('2025')]
cut25_aux=[t for t in cut25 if t[fIdx['signal']]=='buy_aux']; cut25_bk=[t for t in cut25 if t[fIdx['signal']]=='buy_backup']
print(f'2025年被砍: 合计{len(cut25)}笔 {pnl(cut25):+.0f}元 (辅买{pnl(cut25_aux):+.0f} 备买{pnl(cut25_bk):+.0f})')

# 叠加后 5-8 月精确
kept=[t for t in k1A if not best(t)]
m58k=pnl([t for t in kept if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900'])
m58b=pnl([t for t in k1A if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900'])
print(f'5-8月: 基线={m58b:+.0f} -> 叠加后={m58k:+.0f}')

# 8月亏损构成(K1, 叠加后剩余)
aug=[t for t in kept if (t[fIdx['signal_date']] or '').startswith('202608')]
agg={}
for t in aug:
    k=f"{t[fIdx['signal']]}@{t[mD] or '?'}|tier={(t[fIdx['market_tier']] or '非A股')}"
    agg.setdefault(k,[]).append(t)
print('8月叠加后剩余亏损构成:')
for k in sorted(agg,key=lambda x:pnl(agg[x])):
    print(f'   {k:<52} n={len(agg[k])} {pnl(agg[k]):+.0f}元')

# K3/K4 下 5-8 月基线(用户可能用更高K档)
for K in (2,3,4):
    kx=S.topk_by_date(fadeA,fIdx,K)
    m=pnl([t for t in kx if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900'])
    y=pnl([t for t in kx if (t[fIdx['signal_date']] or '').startswith('2026')])
    print(f'K={K} 基线: 5-8月={m:+.0f} 2026全年={y:+.0f}')
