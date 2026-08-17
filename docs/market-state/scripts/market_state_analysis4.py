# -*- coding: utf-8 -*-
"""第四部分: 按年稳定性 + 状态持续天数 + 当前状态组合取值"""
import sqlite3, json, bisect
from collections import defaultdict

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
TRADES = "/Users/linhuichen/code/trade/data/signal_kelly_trades.json"
conn = sqlite3.connect(DB)
rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
dates=[r[0] for r in rows]; closes=[r[1] for r in rows]; n=len(dates)
def ma(arr,w,i):
    if i<w-1: return None
    return sum(arr[i-w+1:i+1])/w
ma20=[ma(closes,20,i) for i in range(n)]; ma60=[ma(closes,60,i) for i in range(n)]
ma120=[ma(closes,120,i) for i in range(n)]; ma200=[ma(closes,200,i) for i in range(n)]

def st_c2(i):
    if ma60[i] is None or ma200[i] is None: return None
    if closes[i]>ma60[i] and closes[i]>ma200[i]: return "牛态"
    if closes[i]<ma60[i] and closes[i]<ma200[i]: return "熊态"
    return "震荡"
def st_c3(i):
    if ma200[i] is None or None in (ma20[i],ma60[i],ma120[i]): return None
    bull=ma20[i]>ma60[i]>ma120[i]; bear=ma20[i]<ma60[i]<ma120[i]
    if bull and closes[i]>ma200[i]: return "强牛"
    if closes[i]>ma200[i]: return "弱牛"
    if bear and closes[i]<ma200[i]: return "强熊"
    return "弱熊"

def gstats(items):
    if not items: return None
    w=[p for p in items if p>0]; l=[p for p in items if p<=0]
    wr=len(w)/len(items)*100; net=sum(items)
    avg_w=sum(w)/len(w) if w else 0; avg_l=sum(l)/len(l) if l else 0
    plr=avg_w/abs(avg_l) if avg_l else float('inf')
    return (len(items),wr,net,plr)

d=json.load(open(TRADES)); q=d['quadrants']
spec=[]
for t in q["sig_special"]["A"]:
    spec.append((t[0], t[14]))
def idx_of(sd):
    i=bisect.bisect_right(dates,sd)-1
    return i if i>=0 else None

print("="*110)
print("【七】按年分解: 追关注 C2牛态/熊态 + D3年线上/年线下(A档, 每笔1万)")
print("="*110)
for k,fn,labels in [("C2_价60×年线", st_c2, ["牛态","熊态"]),
                    ("D3_年线200", lambda i:("年线上" if closes[i]>ma200[i] else "年线下"), ["年线上","年线下"])]:
    by=defaultdict(lambda: defaultdict(list))
    for sd,p in spec:
        i=idx_of(sd)
        if i is None: continue
        s=fn(i)
        if s: by[s][sd[:4]].append(p)
    print(f"\n--- {k} ---")
    years=sorted(set(sd[:4] for sd,_ in spec))
    hdr="年   | "+" | ".join(f"{lb:^22}" for lb in labels)
    print(hdr)
    for y in years:
        row=[]
        for lb in labels:
            g=gstats(by[lb].get(y,[]))
            if g and g[0]>0:
                row.append(f"n={g[0]:4d} 胜{g[1]:4.0f}% 净{g[2]:+9,.0f}")
            else:
                row.append("--")
        print(f"{y} | "+" | ".join(f"{r:^22}" for r in row))

print("\n"+"="*110)
print("【八】状态切换稳定性: 各状态平均持续交易日(切换=状态定义变化)")
print("="*110)
for k,fn in [("D1_MA60牛熊", lambda i:("牛" if closes[i]>ma60[i] else "熊")),
             ("D2_均线排列", lambda i:(lambda x:"多头" if x[0]>x[1]>x[2] else ("空头" if x[0]<x[1]<x[2] else "纠缠"))( (ma20[i],ma60[i],ma120[i]) ) if ma120[i] is not None else None),
             ("C2_价60×年线", st_c2),
             ("C3_四态", st_c3)]:
    runs=defaultdict(list)
    cur=None; start=0
    seq=[]
    for i in range(n):
        s=fn(i)
        seq.append(s)
    for i in range(n):
        s=seq[i]
        if s!=cur:
            if cur is not None:
                runs[cur].append(i-start)
            cur=s; start=i
    runs[cur].append(n-start)
    print(f"--- {k} ---")
    for s in sorted(runs, key=lambda x:-len(runs[x])):
        lens=runs[s]
        print(f"  {s:8s} 出现{len(lens):4d}次 平均持续{sum(lens)/len(lens):6.1f}交易日 中位{sorted(lens)[len(lens)//2]:5d} 最长{max(lens):5d}")

print("\n"+"="*110)
print("【九】当前(2026-08-17)各组合状态")
print("="*110)
i_last=n-1
print(f"  close={closes[i_last]}")
print(f"  C1 排列×价60: ", end="")
ma_a,ma_b,ma_c=ma20[i_last],ma60[i_last],ma120[i_last]
if closes[i_last]>ma_a and ma_a>ma_b>ma_c: print("牛态")
elif closes[i_last]<ma_a and ma_a<ma_b<ma_c: print("熊态")
else: print("震荡")
print(f"  C2 价60×年线: {st_c2(i_last)}")
print(f"  C3 四态: {st_c3(i_last)}")
