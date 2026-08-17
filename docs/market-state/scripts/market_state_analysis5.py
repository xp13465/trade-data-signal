# -*- coding: utf-8 -*-
"""状态切换稳定性 + 当前状态 + 状态历史沿革"""
import sqlite3
from collections import defaultdict
DB="/Users/linhuichen/code/trade/data/sentiment.db"
conn=sqlite3.connect(DB)
rows=conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
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
def st_d1(i):
    if ma60[i] is None: return None
    return "牛" if closes[i]>ma60[i] else "熊"
def st_d2(i):
    if ma120[i] is None or ma20[i] is None or ma60[i] is None: return None
    if ma20[i]>ma60[i]>ma120[i]: return "多头"
    if ma20[i]<ma60[i]<ma120[i]: return "空头"
    return "纠缠"

print("="*110)
print("【八】状态切换稳定性: 平均持续交易日(定义变化=切换)")
print("="*110)
for k,fn in [("D1_MA60牛熊",st_d1),("D2_均线排列",st_d2),("C2_价60×年线",st_c2),("C3_四态",st_c3)]:
    seq=[fn(i) for i in range(n)]
    runs=defaultdict(list)
    cur=None; start=0
    for i in range(n):
        s=seq[i]
        if s!=cur:
            if cur is not None and cur is not None:
                runs[cur].append(i-start)
            cur=s; start=i
    if cur is not None: runs[cur].append(n-start)
    print(f"--- {k} ---")
    for s in sorted(runs,key=lambda x:-len(runs[x])):
        l=runs[s]; m=sorted(l)[len(l)//2]
        print(f"  {s:6s} 出现{len(l):4d}次 平均{sum(l)/len(l):6.1f}交易日 中位{m:5d} 最长{max(l):5d}")

print("\n"+"="*110)
print("【九】当前状态 + 最近60交易日状态演变")
print("="*110)
i=n-1
print(f"close={closes[i]:.1f} MA20={ma20[i]:.1f} MA60={ma60[i]:.1f} MA120={ma120[i]:.1f} MA200={ma200[i]:.1f}")
print(f"D1: {st_d1(i)} | D2: {st_d2(i)} | C2: {st_c2(i)} | C3: {st_c3(i)}")
# 最近60日演变
print("\n近40交易日 C2/C3 演变(每4日取1):")
print(" 日期       close   MA60    C2    C3")
for j in range(i-40, i+1, 4):
    print(f" {dates[j]} {closes[j]:8.1f} {ma60[j]:8.1f}  {str(st_c2(j)):4s}  {str(st_c3(j)):4s}")
print(f" {dates[i]} {closes[i]:8.1f} {ma60[i]:8.1f}  {str(st_c2(i)):4s}  {str(st_c3(i)):4s}")

# 牛态/熊态最长持续历史(判断状态粘性)
print("\nC2 状态最长持续段(近5年, 每次切换记录):")
last=None; start=None
segs=[]
for j in range(n):
    s=st_c2(j)
    if s!=last:
        if last is not None:
            segs.append((dates[start],dates[j-1],last,j-start))
        last=s; start=j
segs.append((dates[start],dates[n-1],last,n-start))
for a,b,s,l in segs[-18:]:
    print(f"  {a}~{b} {s} 持续{l}日")
