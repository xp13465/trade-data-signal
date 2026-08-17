# -*- coding: utf-8 -*-
"""构建交易→四档状态映射工具模块"""
import sqlite3, bisect, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
conn = sqlite3.connect(DB)
rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
DATES = [r[0] for r in rows]
CLOSES = [r[1] for r in rows]
N = len(DATES)

def ma(arr, w, i):
    if i < w - 1: return None
    return sum(arr[i-w+1:i+1]) / w

MA20 = [ma(CLOSES,20,i) for i in range(N)]
MA60 = [ma(CLOSES,60,i) for i in range(N)]
MA120 = [ma(CLOSES,120,i) for i in range(N)]
MA200 = [ma(CLOSES,200,i) for i in range(N)]

def st4_idx(i):
    if MA200[i] is None: return None
    bull = CLOSES[i] > MA200[i]
    m_align = MA20[i] > MA60[i] > MA120[i] if (MA20[i] is not None and MA60[i] is not None and MA120[i] is not None) else False
    b_align = MA20[i] < MA60[i] < MA120[i] if (MA20[i] is not None and MA60[i] is not None and MA120[i] is not None) else False
    if bull and m_align: return "牛市·主升"
    if bull and not m_align: return "上升期"
    if not bull and not b_align: return "下降期"
    return "熊市·主跌"

def st4_of_date(dstr):
    """信号日 -> 四档状态; 无数据(缺日期)返回 None"""
    i = bisect.bisect_right(DATES, dstr) - 1
    if i < 0: return None
    return st4_idx(i)

def st_ma60_of_date(dstr):
    i = bisect.bisect_right(DATES, dstr) - 1
    if i < 0 or MA60[i] is None: return None
    return "牛" if CLOSES[i] > MA60[i] else "熊"

def state_map_for_trades(eng, tlist):
    """tlist: 交易列表 -> {base_key: state}"""
    out = {}
    fi = eng.fIdx
    for t in tlist:
        sd = str(t[fi['signal_date']] or "")
        out[eng.base_key(t)] = st4_of_date(sd)
    return out

# 统计基笔池(8键过滤后)各状态分布
td = load_trades()
eng = KellyEngine(td)
oeng = None
# 直接用 collect_base_pool
pool = eng.collect_base_pool(AI_MACRO)
from collections import defaultdict
st_dist = defaultdict(int); st_mkt = defaultdict(lambda: defaultdict(int))
fi = eng.fIdx
for t in pool:
    sd = str(t[fi['signal_date']] or "")
    s = st4_of_date(sd)
    if s is None: s = "无状态"
    st_dist[s] += 1
    dk = eng._dim_key(t)
    mkt = eng._dims.get(dk, {}).get('mkt', '')
    st_mkt[s][mkt] += 1
print("基笔池(8键过滤后, 去重) n =", len(pool))
print("\n【基笔池四档状态分布】")
for s in sorted(st_dist, key=lambda x: -st_dist[x]):
    print(f"  {s}: {st_dist[s]}")
print("\n【各状态×市场分布】")
for s in sorted(st_mkt, key=lambda x: -st_dist[x]):
    print(f"  {s}: {dict(st_mkt[s])}")
