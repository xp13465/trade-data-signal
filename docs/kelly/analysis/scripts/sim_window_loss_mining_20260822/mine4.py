# -*- coding: utf-8 -*-
"""Part G: 牛主升桶内部决策树 + G模式历史回撤 + 全信号concept细分"""
import sys, json, math
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)

with open('/Users/linhuichen/code/trade/static-site/data/index/hs300-all.json') as f:
    hs = json.load(f)['ohlc']
dates = [r['date'] for r in hs]; closes = [r['close'] for r in hs]
n = len(hs)
ma20 = [None]*n; ma60 = [None]*n; dd252 = [None]*n; vol20 = [None]*n; chg20 = [None]*n
for i in range(n):
    if i >= 19: ma20[i] = sum(closes[i-19:i+1])/20
    if i >= 59: ma60[i] = sum(closes[i-59:i+1])/60
    if i >= 251: dd252[i] = closes[i]/max(closes[i-251:i+1]) - 1
    if i >= 20:
        rets = [closes[j]/closes[j-1]-1 for j in range(i-19, i+1)]
        vol20[i] = (sum(r*r for r in rets)/20) ** 0.5 * math.sqrt(252)
        chg20[i] = closes[i]/closes[i-20] - 1
def feat_at(d):
    if d < dates[0]: return None
    lo, hi = 0, n-1
    while lo < hi:
        mid = (lo+hi+1)//2
        if dates[mid] <= d: lo = mid
        else: hi = mid-1
    i = lo
    return dict(dd=dd252[i], vol=vol20[i], chg20=chg20[i], above_ma20=closes[i]>ma20[i] if ma20[i] else None, i=i)

def pnl(rows): return sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)

def build(mode):
    pool = S.build_mode_pool(tr, fIdx, mode)
    fade = [t for t in pool if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
    return pool, fade, S.topk_by_date(fade, fIdx, 1)
poolA, fadeA, k1A = build('A')

def enrich(rows):
    out = []
    for t in rows:
        ft = feat_at(str(t[fIdx['buy_date']] or ''))
        out.append((t, ft))
    return out

print('=' * 70)
print('G1: 牛主升桶(mode A K1)按年盈亏 + 2025 vs 2026 特征对比')
print('=' * 70)
bull = [(t, feat_at(str(t[fIdx['buy_date']] or ''))) for t in k1A if (t[fIdx['market_tier']] or '') == '牛市·主升']
byyear = {}
for t, ft in bull:
    y = (t[fIdx['signal_date']] or '')[:4]
    byyear.setdefault(y, []).append((t, ft))
for y in sorted(byyear):
    rs = byyear[y]
    p = pnl([t for t, _ in rs])
    print(f'  {y}: n={len(rs):>3} 净={p:>+9.0f}')

print('\n-- 2025(赚+13103) vs 2026(亏-6140) 牛主升笔特征对比 --')
for y in ('2025', '2026'):
    rs = byyear.get(y, [])
    if not rs: continue
    dds = [ft['dd'] for t, ft in rs if ft and ft['dd'] is not None]
    vols = [ft['vol'] for t, ft in rs if ft and ft['vol'] is not None]
    chgs = [ft['chg20'] for t, ft in rs if ft and ft['chg20'] is not None]
    print(f'  {y}: n={len(rs)} 距前高中位={sorted(dds)[len(dds)//2]*100:.1f}% 20日涨幅中位={sorted(chgs)[len(chgs)//2]*100:+.1f}% 波动率中位={sorted(vols)[len(vols)//2]*100:.1f}%')
    # 月份分布
    mm = {}
    for t, _ in rs: mm.setdefault((t[fIdx['signal_date']] or '')[:6], 0); mm[(t[fIdx['signal_date']] or '')[:6]] += 1
    print(f'       月份分布: {dict(sorted(mm.items()))}')

print('\n-- 牛主升桶内二级切分(全历史 2011-2026, mode A K1) --')
def split_report(rows, fn, title):
    agg = {}
    for t, ft in rows:
        if ft is None: continue
        k = fn(t, ft)
        if k is None: continue
        agg.setdefault(k, []).append((t, ft))
    print(f'  -- {title} --')
    for k in sorted(agg, key=str):
        rs = agg[k]
        p = pnl([t for t, _ in rs])
        wins = sum(1 for t, _ in rs if S.calc_row(t, fIdx)['pnlYuan'] > 0)
        print(f'     {str(k):<30} n={len(rs):>3} 净={p:>+9.0f} 胜率={wins/len(rs)*100:5.1f}%')
split_report(bull, lambda t, ft: ('20日涨幅<8%' if ft['chg20']<0.08 else '20日涨幅8-15%' if ft['chg20']<0.15 else '20日涨幅≥15%'), '按买入日 hs300 近20日涨幅')
split_report(bull, lambda t, ft: ('距前高>3%' if ft['dd']<-0.03 else '距前高≤3%(贴着新高)'), '按距252日前高')
split_report(bull, lambda t, ft: (t[mD] or '(空)'), '按市场大类')
split_report(bull, lambda t, ft: t[fIdx['signal']], '按信号类型')

print()
print('=' * 70)
print('G2: G/H/I 模式 2026 持仓与历史回撤(修 bug 重跑)')
print('=' * 70)
for mode in ['G', 'H', 'I']:
    _, _, k1m = build(mode)
    rows26 = [t for t in k1m if (t[fIdx['signal_date']] or '').startswith('2026')]
    holding = [t for t in rows26 if not str(t[fIdx['sell_date']] or '')]
    asc = sorted(rows26, key=lambda t: str(t[fIdx['signal_date']] or ''))
    c = 0; peak = 0
    for t in asc:
        c += S.calc_row(t, fIdx)['pnlYuan']; peak = max(peak, c)
    sold = [t for t in rows26 if str(t[fIdx['sell_date']] or '')]
    print(f'模式{mode}: 2026全年={pnl(rows26):+.0f} | 已卖{len(sold)}笔实现={pnl(sold):+.0f} | 持仓中{len(holding)}笔浮盈亏={pnl(holding):+.0f} | 年内峰值={peak:+.0f} 现值={c:+.0f} 回撤={c-peak:+.0f}')
# G 全历史逐月连亏段(粗)
_, _, k1G = build('G')
ser = {}
for t in k1G:
    m = (t[fIdx['signal_date']] or '')[:6]
    ser[m] = ser.get(m, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
months_all = sorted(ser)
segs = []; cur = []
for m in months_all:
    if ser[m] < 0: cur.append(m)
    else:
        if len(cur) >= 3: segs.append(cur)
        cur = []
if len(cur) >= 3: segs.append(cur)
print(f'\n模式G 连续≥3负月段: {len(segs)} 次')
for sg in segs:
    print(f"   {sg[0]}~{sg[-1]} ({len(sg)}个月) 累计={sum(ser[m] for m in sg):+.0f}元")

print()
print('=' * 70)
print('G3: 全信号口径 5-8月 concept 细分 + 2026 vs 2025 全年对照(mode A)')
print('=' * 70)
lossall = [t for t in poolA if '20260500' <= (t[fIdx['signal_date']] or '') < '20260900']
agg = {}
for t in lossall:
    k = t[mD] or '(空)'
    agg.setdefault(k, []).append(t)
print('-- 5-8月全信号 × 市场大类 --')
for k in sorted(agg, key=lambda x: -len(agg[x])):
    print(f'   {k:<12} n={len(agg[k]):>4} 净={pnl(agg[k]):>+10.0f}')
# concept 内部
conc = [t for t in lossall if (t[mD] or '') == 'concept']
agg2 = {}
for t in conc:
    k = t[fIdx['signal']]
    agg2.setdefault(k, []).append(t)
print('-- 5-8月全信号 concept × 信号类型 --')
for k in sorted(agg2, key=lambda x: -len(agg2[x])):
    print(f'   {k:<14} n={len(agg2[k]):>4} 净={pnl(agg2[k]):>+10.0f}')
# 2025 全年对照
y25 = [t for t in poolA if (t[fIdx['signal_date']] or '').startswith('2025')]
y26 = [t for t in poolA if (t[fIdx['signal_date']] or '').startswith('2026')]
print(f'2025全年全信号={pnl(y25):+.0f}元(n={len(y25)}) | 2026全年全信号={pnl(y26):+.0f}元(n={len(y26)})')
