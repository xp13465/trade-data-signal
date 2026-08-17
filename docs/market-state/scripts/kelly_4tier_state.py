# -*- coding: utf-8 -*-
"""四档大盘状态: 分布/稳定性/与现 MA60 二进制对比"""
import sqlite3, bisect, json
from collections import defaultdict

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
conn = sqlite3.connect(DB)
rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
dates = [r[0] for r in rows]
closes = [r[1] for r in rows]
n = len(dates)
print(f"hs300 日线: {n} 条 {dates[0]}~{dates[-1]}")

def ma(arr, w, i):
    if i < w - 1: return None
    return sum(arr[i-w+1:i+1]) / w

ma20 = [ma(closes,20,i) for i in range(n)]
ma60 = [ma(closes,60,i) for i in range(n)]
ma120 = [ma(closes,120,i) for i in range(n)]
ma200 = [ma(closes,200,i) for i in range(n)]

def st4(i):
    """四档: 牛市·主升/上升期/下降期/熊市·主跌"""
    if ma200[i] is None: return None
    bull = closes[i] > ma200[i]
    if ma20[i] is not None and ma60[i] is not None and ma120[i] is not None:
        m_align = ma20[i] > ma60[i] > ma120[i]
        b_align = ma20[i] < ma60[i] < ma120[i]
    else:
        m_align = b_align = False
    if bull and m_align: return "牛市·主升"
    if bull and not m_align: return "上升期"
    if not bull and not b_align: return "下降期"
    return "熊市·主跌"

def st_ma60_binary(i):
    if ma60[i] is None: return None
    return "牛" if closes[i] > ma60[i] else "熊"

# 1) 分布
dist = defaultdict(int)
for i in range(n):
    s = st4(i)
    if s: dist[s] += 1
print("\n【四档状态分布】")
total = sum(dist.values())
for s in sorted(dist, key=lambda x: -dist[x]):
    print(f"  {s}: {dist[s]} 日, 占比 {dist[s]/total*100:.1f}%")

# 2) 稳定性: 平均持续天数/切换次数
# 连续同状态段
segs = []
cur_s, cur_start = None, 0
for i in range(n):
    s = st4(i)
    if s is None: s = "NA"
    if s != cur_s:
        if cur_s is not None:
            segs.append((cur_s, cur_start, i-1))
        cur_s, cur_start = s, i
segs.append((cur_s, cur_start, n-1))
lens = defaultdict(list)
for s, a, b in segs:
    if s != "NA": lens[s].append(b - a + 1)
print("\n【四档稳定性: 平均持续交易日】")
for s in lens:
    L = lens[s]
    print(f"  {s}: 平均 {sum(L)/len(L):.1f} 日, 中位 {sorted(L)[len(L)//2]} 日, 段数 {len(L)}, 最长 {max(L)} 日")
print(f"  切换次数(含NA): {len(segs)-1}")

# 3) MA60 二进制稳定性对比
segs60 = []
cur_s, cur_start = None, 0
for i in range(n):
    s = st_ma60_binary(i)
    if s is None: s = "NA"
    if s != cur_s:
        if cur_s is not None:
            segs60.append((cur_s, cur_start, i-1))
        cur_s, cur_start = s, i
segs60.append((cur_s, cur_start, n-1))
lens60 = defaultdict(list)
for s, a, b in segs60:
    if s != "NA": lens60[s].append(b - a + 1)
print("\n【MA60 二进制稳定性】")
for s in lens60:
    L = lens60[s]
    print(f"  {s}: 平均 {sum(L)/len(L):.1f} 日, 中位 {sorted(L)[len(L)//2]} 日, 段数 {len(L)}, 最长 {max(L)} 日")
print(f"  切换次数(含NA): {len(segs60)-1}")

# 4) 当前状态
print("\n【当前(2026-08-17)】")
print(f"  close={closes[-1]:.0f} MA20={ma20[-1]:.0f} MA60={ma60[-1]:.0f} MA120={ma120[-1]:.0f} MA200={ma200[-1]:.0f}")
print(f"  四档: {st4(n-1)} | MA60二进制: {st_ma60_binary(n-1)}")

# 5) 四档 vs MA60二进制 重叠度(熊侧)
print("\n【四档 vs MA60二进制 重叠度(日线级)】")
quad = {"熊市·主跌": 0, "下降期": 0, "上升期": 0, "牛市·主升": 0}
m60_bear_cross = {"熊市·主跌": 0, "下降期": 0, "上升期": 0, "牛市·主升": 0}
for i in range(n):
    s4 = st4(i); s60 = st_ma60_binary(i)
    if s4 is None or s60 is None: continue
    quad[s4] += 1
    if s60 == "熊":
        m60_bear_cross[s4] += 1
print("  MA60熊市中, 四档分布:")
for s in quad:
    if quad[s]:
        print(f"    {s}: MA60熊 {m60_bear_cross[s]} 日 / 总 {quad[s]} 日 = {m60_bear_cross[s]/quad[s]*100:.1f}%")
# 反向: 四档熊侧在 MA60 熊中的占比
total_m60_bear = sum(m60_bear_cross.values())
print(f"  MA60熊总日数 {total_m60_bear}")
