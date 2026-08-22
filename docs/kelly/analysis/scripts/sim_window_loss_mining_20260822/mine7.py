# -*- coding: utf-8 -*-
"""Part J: 2026 周度分解(mode A K1 双口径) + 历史连亏段恢复触发器"""
import sys, json, datetime
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)
def pnl(rows): return sum(S.calc_row(t,fIdx)['pnlYuan'] for t in rows)

poolA = S.build_mode_pool(tr, fIdx, 'A')
fadeA = [t for t in poolA if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
k1A = S.topk_by_date(fadeA, fIdx, 1)

print('=== 2026 周度分解(mode A, ISO 周): 全信号 vs K1 ===')
def isoyearweek(d):
    dt = datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    y, w, _ = dt.isocalendar()
    return f'{y}W{w:02d}'
wk_all = {}; wk_k1 = {}
for t in poolA:
    sd = str(t[fIdx['signal_date']] or '')
    if sd >= '20260101':
        wk = isoyearweek(sd)
        wk_all.setdefault(wk, []).append(t)
for t in k1A:
    sd = str(t[fIdx['signal_date']] or '')
    if sd >= '20260101':
        wk = isoyearweek(sd)
        wk_k1.setdefault(wk, []).append(t)
print(f'{"周":<9}{"全信号n":>6}{"全信号净":>10}{"K1n":>5}{"K1净":>9}')
for wk in sorted(set(list(wk_all)+list(wk_k1))):
    a = pnl(wk_all.get(wk, [])); b = pnl(wk_k1.get(wk, []))
    print(f'{wk:<9}{len(wk_all.get(wk,[])):>6}{a:>+10.0f}{len(wk_k1.get(wk,[])):>5}{b:>+9.0f}')

print()
print('=== 历史连亏段(mode A K1)结束时的 hs300 状态 ===')
ser = {}
for t in k1A:
    m = (t[fIdx['signal_date']] or '')[:6]
    ser[m] = ser.get(m, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
months_all = sorted(ser)
segs=[]; cur=[]
for m in months_all:
    if ser[m]<0: cur.append(m)
    else:
        if len(cur)>=3: segs.append(cur)
        cur=[]
if len(cur)>=3: segs.append(cur)
with open('/Users/linhuichen/code/trade/static-site/data/market_tier_history.json') as f:
    hist = json.load(f)
tier_dates = [h['date'] for h in hist]; tier_vals=[h['tier'] for h in hist]
def tier_at(d):
    import bisect
    i = bisect.bisect_right(tier_dates, d)-1
    return tier_vals[i] if i>=0 else None
print('连亏段(月末视角) | 段末下一个月首日 tier | 段后3个月净额 | 段后6个月净额')
for sg in segs:
    end_i = months_all.index(sg[-1])
    nxt = months_all[end_i+1] if end_i+1 < len(months_all) else None
    nt = tier_at(nxt+'01') if nxt else '-'
    a3 = sum(ser[m] for m in months_all[end_i+1:end_i+4]) if end_i+3 < len(months_all) else None
    a6 = sum(ser[m] for m in months_all[end_i+1:end_i+7]) if end_i+6 < len(months_all) else None
    print(f'{sg[0]}~{sg[-1]}({len(sg)}月,{sum(ser[m] for m in sg):+.0f}) | {nt} | {("+" if a3>=0 else "")+format(a3,".0f") if a3 is not None else "-"} | {("+" if a6>=0 else "")+format(a6,".0f") if a6 is not None else "-"}')
print(f'\n当前(2026-08) tier={tier_at("20260821")}; 当前段: 5/6亏 7正 8亏(未满连亏定义)')
