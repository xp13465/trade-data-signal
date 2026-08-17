# -*- coding: utf-8 -*-
"""第二部分: 各状态下买入信号的胜率/净收益区分度
对标 lab.js:9778 证据(牛市追关注 净+490万 胜率60.5% vs 熊市 净-16.3万 胜率41.7%)
用 signal_kelly_trades.json 逐笔交易(每笔1万), 按信号日 hs300 状态分组。
"""
import sqlite3, json
from collections import defaultdict

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
TRADES = "/Users/linhuichen/code/trade/data/signal_kelly_trades.json"

conn = sqlite3.connect(DB)
rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
dates = [r[0] for r in rows]
closes = [r[1] for r in rows]
n = len(dates)

def ma(arr, w, i):
    if i < w - 1: return None
    return sum(arr[i - w + 1: i + 1]) / w
ma20 = [ma(closes, 20, i) for i in range(n)]
ma60 = [ma(closes, 60, i) for i in range(n)]
ma120 = [ma(closes, 120, i) for i in range(n)]
ma200 = [ma(closes, 200, i) for i in range(n)]

# 日期 -> 索引
d2i = {d: i for i, d in enumerate(dates)}
# 交易日索引数组(用 bisect 向前找)
import bisect
def idx_of(signal_date):
    i = bisect.bisect_right(dates, signal_date) - 1
    return i if i >= 0 else None

def st_price_vs_ma60(i):
    if ma60[i] is None: return None
    return "牛(价>MA60)" if closes[i] > ma60[i] else "熊(价<MA60)"

def st_ma_align(i):
    if None in (ma20[i], ma60[i], ma120[i]): return None
    if ma20[i] > ma60[i] > ma120[i]: return "多头排列"
    if ma20[i] < ma60[i] < ma120[i]: return "空头排列"
    return "纠缠"

def st_price_vs_ma200(i):
    if ma200[i] is None: return None
    return "年线上" if closes[i] > ma200[i] else "年线下"

ST_DEFS = {
    "D1_MA60牛熊": st_price_vs_ma60,
    "D2_均线排列": st_ma_align,
    "D3_年线200": st_price_vs_ma200,
}

# 加载交易
d = json.load(open(TRADES))
q = d['quadrants']
SIG_MAP = {"sig_main": "主关注buy", "sig_aux": "辅关注buy_aux", "sig_special": "追关注buy_special", "sig_backup": "备关注buy_backup"}
# 合并 A 档(固定10天)交易: [sig_date, iid, signal, buy_date, ...], profit=字段14, return_pct=15
trades = []  # (signal_date, signal, profit)
for qk in ["sig_main","sig_aux","sig_special","sig_backup"]:
    for t in q[qk]["A"]:
        trades.append((t[0], t[2], t[14]))
print(f"A档(固定10天)总交易: {len(trades)} 笔")

def group_stats(items):
    """items: [(profit,)] 返回 (n, 胜率, 净利, 盈亏比)"""
    if not items: return None
    n_t = len(items)
    wins = [p for p in items if p > 0]
    losses = [p for p in items if p <= 0]
    wr = len(wins) / n_t * 100
    net = sum(items)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    plr = avg_win / abs(avg_loss) if avg_loss else float('inf')
    return (n_t, wr, net, plr)

print("\n" + "=" * 100)
print("【三】各状态下买入信号表现(A档固定10天, 每笔1万) — 全体买信号")
print("=" * 100)
for k, fn in ST_DEFS.items():
    by = defaultdict(list)
    for sd, sig, p in trades:
        i = idx_of(sd)
        if i is None: continue
        s = fn(i)
        if s is not None:
            by[s].append(p)
    print(f"\n--- {k} ---")
    for s in sorted(by, key=lambda x: -len(by[x])):
        g = group_stats(by[s])
        if g:
            print(f"  {s:12s} n={g[0]:6d} 胜率{g[1]:5.1f}% 净利{g[2]:+10,.0f} 盈亏比{g[3]:.2f}")

print("\n" + "=" * 100)
print("【四】追关注 buy_special 单类在各状态下的表现(A档) — 对标 lab.js:9778")
print("=" * 100)
spec = [t for t in trades if t[1] == "buy_special"]
print(f"追关注总交易: {len(spec)}")
for k, fn in ST_DEFS.items():
    by = defaultdict(list)
    for sd, sig, p in spec:
        i = idx_of(sd)
        if i is None: continue
        s = fn(i)
        if s is not None:
            by[s].append(p)
    print(f"\n--- {k} ---")
    for s in sorted(by, key=lambda x: -len(by[x])):
        g = group_stats(by[s])
        if g:
            print(f"  {s:12s} n={g[0]:6d} 胜率{g[1]:5.1f}% 净利{g[2]:+12,.0f} 盈亏比{g[3]:.2f}")
