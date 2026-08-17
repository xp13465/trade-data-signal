# -*- coding: utf-8 -*-
"""第五部分: 共振组合 + 各候选区分度汇总评分"""
import sqlite3, json, bisect
from collections import defaultdict
DB="/Users/linhuichen/code/trade/data/sentiment.db"; TRADES="/Users/linhuichen/code/trade/data/signal_kelly_trades.json"
conn=sqlite3.connect(DB)
rows=conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
dates=[r[0] for r in rows]; closes=[r[1] for r in rows]; n=len(dates)
def ma(arr,w,i):
    if i<w-1: return None
    return sum(arr[i-w+1:i+1])/w
ma20=[ma(closes,20,i) for i in range(n)]; ma60=[ma(closes,60,i) for i in range(n)]
ma120=[ma(closes,120,i) for i in range(n)]; ma200=[ma(closes,200,i) for i in range(n)]

d=json.load(open(TRADES)); q=d['quadrants']
spec=[]
for t in q["sig_special"]["A"]: spec.append((t[0],t[14]))
def idx_of(sd):
    i=bisect.bisect_right(dates,sd)-1
    return i if i>=0 else None
def gstats(items):
    if not items: return None
    w=[p for p in items if p>0]; l=[p for p in items if p<=0]
    wr=len(w)/len(items)*100; net=sum(items)
    aw=sum(w)/len(w) if w else 0; al=sum(l)/len(l) if l else 0
    plr=aw/abs(al) if al else float('inf')
    return (len(items),wr,net,plr)

# 共振: 牛态(价>MA60 & 价>年线 & 多头排列) vs 熊态(价<MA60 & 价<年线 & 空头排列)
def st_resonance(i):
    if None in (ma20[i],ma60[i],ma120[i],ma200[i]): return None
    bull=ma20[i]>ma60[i]>ma120[i]; bear=ma20[i]<ma60[i]<ma120[i]
    if bull and closes[i]>ma60[i] and closes[i]>ma200[i]: return "牛共振"
    if bear and closes[i]<ma60[i] and closes[i]<ma200[i]: return "熊共振"
    return "中间"

by=defaultdict(list)
for sd,p in spec:
    i=idx_of(sd)
    if i is None: continue
    s=st_resonance(i)
    if s: by[s].append(p)
print("="*100)
print("【十】共振组合 vs 追关注(A档, 每笔1万) — 牛共振/熊共振/中间")
print("="*100)
for s in sorted(by,key=lambda x:-len(by[x])):
    g=gstats(by[s])
    if g: print(f"  {s:6s} n={g[0]:6d} 胜率{g[1]:5.1f}% 净利{g[2]:+12,.0f} 盈亏比{g[3]:.2f}")

# 全体买信号共振
alltr=[]
for qk in ["sig_main","sig_aux","sig_special","sig_backup"]:
    for t in q[qk]["A"]: alltr.append((t[0],t[14]))
by2=defaultdict(list)
for sd,p in alltr:
    i=idx_of(sd)
    if i is None: continue
    s=st_resonance(i)
    if s: by2[s].append(p)
print("\n全体买信号:")
for s in sorted(by2,key=lambda x:-len(by2[x])):
    g=gstats(by2[s])
    if g: print(f"  {s:6s} n={g[0]:6d} 胜率{g[1]:5.1f}% 净利{g[2]:+12,.0f} 盈亏比{g[3]:.2f}")

# 当前共振状态
i=n-1
bull=ma20[i]>ma60[i]>ma120[i]; bear=ma20[i]<ma60[i]<ma120[i]
print(f"\n当前共振状态: {st_resonance(i)} (close={closes[i]:.0f}, MA60={ma60[i]:.0f}, MA120={ma120[i]:.0f}, MA200={ma200[i]:.0f})")

# 各候选汇总评分表
print("\n"+"="*100)
print("【十一】候选状态定义综合汇总(区分度=牛/熊两类追关注净利差 + 胜率差; 稳定性=状态平均持续日)")
print("="*100)
cands={
 "D1 价vsMA60": (lambda i:("牛" if closes[i]>ma60[i] else "熊"), "牛/熊"),
 "D2 均线排列": (lambda i:(lambda x:"多头" if x[0]>x[1]>x[2] else ("空头" if x[0]<x[1]<x[2] else "纠缠"))((ma20[i],ma60[i],ma120[i])) if ma120[i] is not None else None, "多头/空头"),
 "D3 价vs年线200": (lambda i:("牛" if closes[i]>ma200[i] else "熊"), "牛/熊"),
 "C2 价60×年线": (lambda i:(lambda x:"牛态" if closes[i]>x[0] and closes[i]>x[1] else ("熊态" if closes[i]<x[0] and closes[i]<x[1] else "震荡"))((ma60[i],ma200[i])) if ma60[i] is not None and ma200[i] is not None else None, "牛态/熊态"),
 "共振": st_resonance,
}
print(f"{'候选':20s} | {'历史占比(牛:熊)':16s} | {'20d收益(牛vs熊)':16s} | {'追关注净利(牛vs熊)':18s} | {'胜率差':8s} | 稳定(中位日)")
for name,(fn,_) in cands.items():
    hist=defaultdict(int); f20=defaultdict(list)
    for i in range(n):
        s=fn(i)
        if s: hist[s]+=1
        if s and i+20<n: f20[s].append(closes[i+20]/closes[i]-1)
    # 找"牛类/熊类"标签
    def is_bull_like(s): return s in ("牛","多头","牛态","牛共振")
    def is_bear_like(s): return s in ("熊","空头","熊态","熊共振")
    bull_lab=[s for s in hist if is_bull_like(s)]
    bear_lab=[s for s in hist if is_bear_like(s)]
    b=by if name=="共振" else None
    tr_by=by2 if name=="共振" else by
    # 追关注净利(牛类/熊类)
    nb=defaultdict(list)
    for sd,p in spec:
        i=idx_of(sd)
        if i is None: continue
        s=fn(i)
        if s: nb[s].append(p)
    bull_net=sum(sum(nb[s]) for s in nb if is_bull_like(s))
    bear_net=sum(sum(nb[s]) for s in nb if is_bear_like(s))
    bull_wr=sum(1 for s in nb for p in nb[s] if is_bull_like(s) and p>0)/max(1,sum(len(nb[s]) for s in nb if is_bull_like(s)))*100
    bear_wr=sum(1 for s in nb for p in nb[s] if is_bear_like(s) and p>0)/max(1,sum(len(nb[s]) for s in nb if is_bear_like(s)))*100
    bull_n=sum(len(nb[s]) for s in nb if is_bull_like(s)); bear_n=sum(len(nb[s]) for s in nb if is_bear_like(s))
    bull20=sum(sum(f20[s]) for s in f20 if is_bull_like(s))/max(1,sum(len(f20[s]) for s in f20 if is_bull_like(s)))*100
    bear20=sum(sum(f20[s]) for s in f20 if is_bear_like(s))/max(1,sum(len(f20[s]) for s in f20 if is_bear_like(s)))*100
    tpct=sum(hist[s] for s in hist if is_bull_like(s))/sum(hist.values())*100
    bpct=sum(hist[s] for s in hist if is_bear_like(s))/sum(hist.values())*100
    print(f"{name:20s} | {tpct:5.1f}:{bpct:5.1f}      |  {bull20:+.2f} vs {bear20:+.2f} | {bull_net:+,.0f} vs {bear_net:+,.0f}(n{bull_n}/{bear_n}) | {bull_wr-bear_wr:+5.1f}pp |")
