# -*- coding: utf-8 -*-
"""Part E: 市场状态时间线 + 大盘特征(hs300)时段级空仓候选"""
import sys, json, datetime, math
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)
poolA = S.build_mode_pool(tr, fIdx, 'A')
fadeA = [t for t in poolA if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
k1A = S.topk_by_date(fadeA, fIdx, 1)

# ---- hs300 日线特征 ----
with open('/Users/linhuichen/code/trade/static-site/data/index/hs300-all.json') as f:
    hs = json.load(f)['ohlc']
dates = [r['date'] for r in hs]
closes = [r['close'] for r in hs]
n = len(hs)
ma = {p: [None]*n for p in (20, 60, 120, 200)}
for p in (20, 60, 120, 200):
    for i in range(p-1, n):
        ma[p][i] = sum(closes[i-p+1:i+1]) / p
dd252 = [None]*n  # 距过去252日收盘最高回撤
vol20 = [None]*n  # 20日已实现波动年化
for i in range(n):
    if i >= 251:
        hi = max(closes[i-251:i+1])
        dd252[i] = closes[i]/hi - 1
    if i >= 20:
        rets = [closes[j]/closes[j-1]-1 for j in range(i-19, i+1)]
        vol20[i] = (sum(r*r for r in rets)/20) ** 0.5 * math.sqrt(252)
def feat_at(d):
    # 二分找 <=d 最近交易日
    lo, hi = 0, n-1
    if d < dates[0]: return None
    while lo < hi:
        mid = (lo+hi+1)//2
        if dates[mid] <= d: lo = mid
        else: hi = mid-1
    i = lo
    return dict(close=closes[i], above_ma200=closes[i]>ma[200][i] if ma[200][i] else None,
                ma_bull=(ma[20][i]>ma[60][i]>ma[120][i]) if all(ma[p][i] is not None for p in (20,60,120)) else None,
                dd=dd252[i], vol=vol20[i], date_used=dates[i])

print('=== 5-8月 hs300 四档时间线(trades 自带 market_tier, 按 buy_date) ===')
tiers_by_month = {}
for t in fadeA:
    bd = str(t[fIdx['buy_date']] or '')
    if '20260500' <= bd < '20260900':
        tiers_by_month.setdefault(bd[:6], {}).setdefault(t[fIdx['market_tier']] or '(非A股)', 0)
        tiers_by_month[bd[:6]][t[fIdx['market_tier']] or '(非A股)'] += 1
for m in sorted(tiers_by_month): print(' ', m, tiers_by_month[m])

# tier 转换点: market_tier_history 2026 年
with open('/Users/linhuichen/code/trade/static-site/data/market_tier_history.json') as f:
    hist = json.load(f)
prev = None
print('\n=== 2026 年四档切换点 ===')
for h in hist:
    if h['date'] >= '20260101':
        if h['tier'] != prev:
            print(f"  {h['date']} -> {h['tier']}")
            prev = h['tier']

# ---- 时段级候选: 按 hs300 特征分桶的盈亏(K1 口径 + 全历史) ----
def bucket_rows(rows, fn, title):
    agg = {}
    for t in rows:
        ft = feat_at(str(t[fIdx['buy_date']] or ''))
        if ft is None: continue
        k = fn(ft)
        if k is None: continue
        agg.setdefault(k, []).append(t)
    print(f'-- {title} --')
    items = []
    for k, rs in agg.items():
        pnl = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rs)
        wins = sum(1 for t in rs if S.calc_row(t, fIdx)['pnlYuan'] > 0)
        items.append((k, len(rs), pnl, wins/max(len(rs),1)*100))
    items.sort(key=lambda x: str(x[0]))
    for k, nn, pnl, wr in items:
        print(f'   {str(k):<32} n={nn:>5} 净={pnl:>+11.0f}元 胜率={wr:5.1f}%')

print('\n=== 全历史(2011-2026) K1 口径 × hs300 特征分桶 ===')
bucket_rows(k1A, lambda ft: ('距前高回撤≤5%' if ft['dd']>=-0.05 else '回撤5-10%' if ft['dd']>=-0.10 else '回撤10-15%' if ft['dd']>=-0.15 else '回撤>15%'), '距252日前高回撤')
bucket_rows(k1A, lambda ft: ('vol<15%' if ft['vol']<0.15 else 'vol15-20%' if ft['vol']<0.20 else 'vol20-25%' if ft['vol']<0.25 else 'vol≥25%'), '20日已实现波动率')
bucket_rows(k1A, lambda ft: ('价>MA200' if ft['above_ma200'] else '价<MA200'), 'hs300 价vs MA200')
bucket_rows(k1A, lambda ft: ('多头排列' if ft['ma_bull'] else '非多头'), 'hs300 MA 多头排列')

print('\n=== 仅 2026 年 1-8 月 × 同样特征(K1) ===')
k1_26 = [t for t in k1A if (t[fIdx['signal_date']] or '') >= '20260101']
bucket_rows(k1_26, lambda ft: ('距前高回撤≤5%' if ft['dd']>=-0.05 else '回撤5-10%' if ft['dd']>=-0.10 else '回撤10-15%' if ft['dd']>=-0.15 else '回撤>15%'), '2026 距前高回撤')
bucket_rows(k1_26, lambda ft: ('vol<15%' if ft['vol']<0.15 else 'vol15-20%' if ft['vol']<0.20 else 'vol20-25%' if ft['vol']<0.25 else 'vol≥25%'), '2026 波动率')
bucket_rows(k1_26, lambda ft: ('多头排列' if ft['ma_bull'] else '非多头'), '2026 MA多头排列')

# 4月利润是否会被这些规则误伤: 4月 K1 笔的特征分布
apr = [t for t in k1A if (t[fIdx['signal_date']] or '').startswith('202604')]
m58 = [t for t in k1A if '20260500' <= (t[fIdx['signal_date']] or '') < '20260900']
print('\n=== 候选规则×(4月利润, 5-8月亏损) 双向检验(K1) ===')
rules = [
    ('hs300回撤>10%全停', lambda ft: ft['dd'] < -0.10),
    ('hs300回撤>5%全停', lambda ft: ft['dd'] < -0.05),
    ('hs300非多头排列全停', lambda ft: not ft['ma_bull']),
    ('hs300价<MA200全停', lambda ft: not ft['above_ma200']),
    ('vol≥20%全停', lambda ft: (ft['vol'] or 0) >= 0.20),
    ('vol≥25%全停', lambda ft: (ft['vol'] or 0) >= 0.25),
]
for name, cond in rules:
    kept_apr = [t for t in apr if not cond(feat_at(str(t[fIdx['buy_date']] or '')))]
    kept_58 = [t for t in m58 if not cond(feat_at(str(t[fIdx['buy_date']] or '')))]
    pa = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in kept_apr)
    p58 = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in kept_58)
    print(f'   {name:<22} | 4月留{len(kept_apr):>2}/17笔 净{pa:>+8.0f} | 5-8月留{len(kept_58):>2}/50笔 净{p58:>+8.0f}')

# trades 自带 market_tier 规则
print('\n=== trades 自带 A股四档/market_state 规则双向检验(K1) ===')
tr_rules = [
    ('A股类·牛市主升全停', lambda t: (t[fIdx['market_tier']] or '') == '牛市·主升'),
    ('A股类·上升期全停', lambda t: (t[fIdx['market_tier']] or '') == '上升期'),
    ('A股类·(牛主升+上升期)全停', lambda t: (t[fIdx['market_tier']] or '') in ('牛市·主升','上升期')),
]
for name, cond in tr_rules:
    kept_apr = [t for t in apr if not cond(t)]
    kept_58 = [t for t in m58 if not cond(t)]
    pa = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in kept_apr)
    p58 = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in kept_58)
    print(f'   {name:<26} | 4月留{len(kept_apr):>2}/17笔 净{pa:>+8.0f} | 5-8月留{len(kept_58):>2}/50笔 净{p58:>+8.0f}')
