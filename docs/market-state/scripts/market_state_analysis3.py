# -*- coding: utf-8 -*-
"""第三部分: 组合状态体系(多条件) + 按年稳定性
候选综合状态:
  C1 三态: 牛态(多头排列 & 价>MA60) / 熊态(空头排列 & 价<MA60) / 震荡(其余)
  C2 三态: 牛态(价>MA60 & 价>年线200) / 熊态(价<MA60 & 价<年线200) / 震荡(其余)
  C3 四态(带年线兜底): 强牛(多头排列 & 价>年线) / 弱牛(价>年线但非多头) / 弱熊 / 强熊(空头 & 价<年线)
"""
import sqlite3, json, bisect
from collections import defaultdict

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
TRADES = "/Users/linhuichen/code/trade/data/signal_kelly_trades.json"
conn = sqlite3.connect(DB)
rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
dates = [r[0] for r in rows]; closes = [r[1] for r in rows]; n = len(dates)
def ma(arr,w,i):
    if i < w-1: return None
    return sum(arr[i-w+1:i+1])/w
ma20=[ma(closes,20,i) for i in range(n)]; ma60=[ma(closes,60,i) for i in range(n)]
ma120=[ma(closes,120,i) for i in range(n)]; ma200=[ma(closes,200,i) for i in range(n)]

def st_c1(i):
    if None in (ma20[i],ma60[i],ma120[i]): return None
    if closes[i]>ma60[i] and ma20[i]>ma60[i]>ma120[i]: return "牛态"
    if closes[i]<ma60[i] and ma20[i]<ma60[i]<ma120[i]: return "熊态"
    return "震荡"

def st_c2(i):
    if ma60[i] is None or ma200[i] is None: return None
    if closes[i]>ma60[i] and closes[i]>ma200[i]: return "牛态"
    if closes[i]<ma60[i] and closes[i]<ma200[i]: return "熊态"
    return "震荡"

def st_c3(i):
    if ma200[i] is None or None in (ma20[i],ma60[i],ma120[i]): return None
    bull_align = ma20[i]>ma60[i]>ma120[i]
    bear_align = ma20[i]<ma60[i]<ma120[i]
    if bull_align and closes[i]>ma200[i]: return "强牛"
    if closes[i]>ma200[i]: return "弱牛"
    if bear_align and closes[i]<ma200[i]: return "强熊"
    return "弱熊"

ST = {"C1_排列×价60": st_c1, "C2_价60×年线": st_c2, "C3_排列×年线四态": st_c3}

# 历史分布 + 未来收益
print("="*110)
print("【五】组合状态体系: 历史占比 + 未来N日 hs300 收益(天气预报)")
print("="*110)
for k, fn in ST.items():
    by = defaultdict(list)
    for i in range(n):
        s = fn(i)
        if s: by[s].append(i)
    total = sum(len(v) for v in by.values())
    print(f"\n--- {k} ---")
    for s in sorted(by, key=lambda x:-len(by[x])):
        idxs = by[s]
        pct = len(idxs)/total*100
        means=[]; up20=None
        for f in [5,10,20,60]:
            js = [j for j in idxs if j+f<n]
            if js:
                m = sum(closes[j+f]/closes[j]-1 for j in js)/len(js)*100
                means.append(f"{f}d {m:+.2f}%")
                if f==20: up20 = sum(1 for j in js if closes[j+20]>closes[j])/len(js)*100
        print(f"  {s:6s} 占比{pct:5.1f}% n={len(idxs):6d} 20d上涨概率{up20:5.1f}% | "+" ".join(means))

# 交易按组合状态分组(追关注 + 全体)
d=json.load(open(TRADES)); q=d['quadrants']
trades=[]
for qk in ["sig_main","sig_aux","sig_special","sig_backup"]:
    for t in q[qk]["A"]:
        trades.append((t[0], t[2], t[14]))
def idx_of(sd):
    i=bisect.bisect_right(dates,sd)-1
    return i if i>=0 else None
def gstats(items):
    if not items: return None
    w=[p for p in items if p>0]; l=[p for p in items if p<=0]
    wr=len(w)/len(items)*100; net=sum(items)
    plr=(sum(w)/len(w))/(abs(sum(l)/len(l))) if l else float('inf')
    return (len(items), wr, net, plr)

print("\n"+"="*110)
print("【六】组合状态 vs 追关注 buy_special(A档, 每笔1万, 全史)")
print("="*110)
spec=[t for t in trades if t[1]=="buy_special"]
for k,fn in ST.items():
    by=defaultdict(list)
    for sd,sig,p in spec:
        i=idx_of(sd)
        if i is None: continue
        s=fn(i)
        if s: by[s].append(p)
    print(f"\n--- {k} ---")
    for s in sorted(by,key=lambda x:-len(by[x])):
        g=gstats(by[s])
        if g: print(f"  {s:6s} n={g[0]:6d} 胜率{g[1]:5.1f}% 净利{g[2]:+12,.0f} 盈亏比{g[3]:.2f}")

print("\n"+"="*110)
print("【七】按年分解稳定性: 追关注 年线上/年线下(A档)")
print("="*110)
for k,fn in [("D3_年线200", lambda i:(lambda x:"年线上" if closes[i]>x else "年线下")(ma200[i]))]:
    by=defaultdict(lambda: defaultdict(list))
    for sd,sig,p in spec:
        i=idx_of(sd)
        if i is None: continue
        s=fn(i)
        if s: by[s][sd[:4]].append(p)
    print("年   | 年线上(n/胜率/净利)            | 年线下(n/胜率/净利)")
    years = sorted(set(sd[:4] for sd,_,_ in spec))
    for y in years:
        row=[]
        for s in ["年线上","年线下"]:
            g=gstats(by[s].get(y,[]))
            row.append(f"{g[0] if g else 0:4d}/{g[1] if g else 0:4.0f}%/{g[2] if g else 0:+10,.0f}")
        print(f"{y} | {row[0]:<28} | {row[1]}")
