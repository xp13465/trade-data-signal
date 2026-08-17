# -*- coding: utf-8 -*-
"""大盘状态研判 - 状态定义回测分析(只读, 不改项目任何文件)
数据源: data/sentiment.db index_daily(hs300) + data/signal_kelly_trades.json(逐笔买卖信号, 每笔1万)
目的: 对几种状态定义计算 ①历史占比 ②hs300 未来N日收益(天气预报有效性) ③各状态买入信号胜率/净利(区分度)
"""
import sqlite3, json, bisect
from collections import defaultdict

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
TRADES = "/Users/linhuichen/code/trade/data/signal_kelly_trades.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
dates = [r["date"] for r in rows]
closes = [r["close"] for r in rows]
n = len(dates)
print(f"hs300 日线: {n} 条, {dates[0]} ~ {dates[-1]}")

# ---------- 技术指标 ----------
def ma(arr, w, i):
    if i < w - 1: return None
    return sum(arr[i - w + 1: i + 1]) / w

ma20 = [ma(closes, 20, i) for i in range(n)]
ma60 = [ma(closes, 60, i) for i in range(n)]
ma120 = [ma(closes, 120, i) for i in range(n)]
ma200 = [ma(closes, 200, i) for i in range(n)]
ma250 = [ma(closes, 250, i) for i in range(n)]

# 状态定义函数: 输入 i(日期索引) 返回状态标签字符串
def st_price_vs_ma60(i):
    """D1: 价格 vs MA60(现熊市交叉定义)"""
    if ma60[i] is None: return None
    return "牛(价>MA60)" if closes[i] > ma60[i] else "熊(价<MA60)"

def st_ma_align(i):
    """D2: MA20>MA60>MA120 多头排列 / 空头排列 / 纠缠"""
    if None in (ma20[i], ma60[i], ma120[i]): return None
    if ma20[i] > ma60[i] > ma120[i]: return "多头排列"
    if ma20[i] < ma60[i] < ma120[i]: return "空头排列"
    return "纠缠"

def st_price_vs_ma200(i):
    """D3a: 价格 vs 年线 MA200"""
    if ma200[i] is None: return None
    return "年线上(MA200)" if closes[i] > ma200[i] else "年线下(MA200)"

def st_price_vs_ma250(i):
    """D3b: 价格 vs 年线 MA250"""
    if ma250[i] is None: return None
    return "年线上(MA250)" if closes[i] > ma250[i] else "年线下(MA250)"

def st_ma20_slope(i):
    """D4: MA20 斜率(5日前比较, 阈值±0.3%)"""
    if i < 5 or ma20[i] is None or ma20[i-5] is None: return None
    chg = (ma20[i] / ma20[i-5] - 1) * 100
    if chg > 0.3: return "MA20上升"
    if chg < -0.3: return "MA20下降"
    return "MA20走平"

def st_highlow20(i):
    """D5: 20日新高新低相对位置(收盘价在20日区间分位)"""
    if i < 20: return None
    win = closes[i-20:i+1]
    hi, lo = max(win), min(win)
    if hi == lo: return "20日区间无波动"
    pos = (closes[i] - lo) / (hi - lo)
    if pos >= 0.9: return "近20日高位(≥90分位)"
    if pos <= 0.1: return "近20日低位(≤10分位)"
    if pos >= 0.5: return "20日区间中上"
    return "20日区间中下"

ST_DEFS = {
    "D1_MA60牛熊": st_price_vs_ma60,
    "D2_均线排列": st_ma_align,
    "D3a_年线200": st_price_vs_ma200,
    "D3b_年线250": st_price_vs_ma250,
    "D4_MA20斜率": st_ma20_slope,
    "D5_20日高低位": st_highlow20,
}

# ---------- 1. 历史分布 + 未来N日收益(天气预报有效性) ----------
FUTURE = [5, 10, 20, 60]
print("\n" + "=" * 100)
print("【一】状态历史分布 + 未来N日 hs300 收益(天气预报有效性)")
print("=" * 100)
dist = {k: defaultdict(list) for k in ST_DEFS}
for i in range(n):
    for k, fn in ST_DEFS.items():
        s = fn(i)
        if s is None: continue
        for f in FUTURE:
            if i + f < n:
                dist[k][s].append(closes[i+f] / closes[i] - 1)

for k, fn in ST_DEFS.items():
    print(f"\n--- {k} ---")
    total_days = sum(len(v) for v in dist[k].values())
    for s, rets in sorted(dist[k].items(), key=lambda x: -len(x[1])):
        pct = len(rets) / total_days * 100
        up = sum(1 for r in rets if r > 0) / len(rets) * 100
        mean5 = sum(rets[i] for i, f in [(0,5)] for i in range(len(rets)) if i < len(rets) and False) # placeholder
        # 每档未来收益均值
        means = []
        for f in FUTURE:
            idxs = [i for i in range(len(dates) - f) if fn(i) == s]
            if idxs:
                m = sum(closes[j+f]/closes[j] - 1 for j in idxs) / len(idxs) * 100
                means.append(f"{f}d {m:+.2f}%")
        print(f"  {s:20s} 占比{pct:5.1f}% n={len(rets):5d} 未来20日上涨概率{up:5.1f}% | " + " ".join(means))

# ---------- 2. 各状态当前值 ----------
print("\n" + "=" * 100)
print("【二】当前(2026-08-17)各状态定义取值")
print("=" * 100)
i_last = n - 1
print(f"  hs300 close={closes[i_last]}, MA20={ma20[i_last]:.2f}, MA60={ma60[i_last]:.2f}, MA120={ma120[i_last]:.2f}, MA200={ma200[i_last]:.2f}, MA250={ma250[i_last]:.2f}")
for k, fn in ST_DEFS.items():
    print(f"  {k}: {fn(i_last)}")
