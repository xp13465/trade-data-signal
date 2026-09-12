#!/usr/bin/env python3
#!/usr/bin/env python3
"""生成 accum_nav 历史缺价完整清单(2026-09-06)
目的: gap 法扫描主库 etf_daily, 输出缺价日清单(etf_code, date, 形态)供抽样/全量实测
口径: gap = 该ETF前后均有 accum_nav、中间某交易日无, 且当日全市场覆盖数>=5 视为真实交易日
输入依赖: /Users/linhuichen/code/trade-data/data/etf_national_team.db(表 etf_daily)
输出: /tmp/accum_nav_gap_rows.json + 分层统计(stdout)
复现命令: python3 accum_nav_gap_list.py
数据截止: 20260904
"""

"""输出 accum_nav 2081 缺价完整清单(etf_code, date, 形态) 供抽样"""
import sqlite3, json, collections, sys

DB = '/Users/linhuichen/code/trade-data/data/etf_national_team.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("SELECT date, COUNT(*) FROM etf_daily GROUP BY date")
day_cov = dict(cur.fetchall())
trade_days = sorted(d for d, n in day_cov.items() if n >= 5)
td_idx = {d: i for i, d in enumerate(trade_days)}

cur.execute("SELECT etf_code, date FROM etf_daily WHERE accum_nav IS NOT NULL ORDER BY etf_code, date")
has_nav = collections.defaultdict(set)
for code, d in cur.fetchall():
    has_nav[code].add(d)

cur.execute("SELECT etf_code, date, close FROM etf_daily WHERE accum_nav IS NULL ORDER BY etf_code, date")
nav_null_rows = collections.defaultdict(list)
for code, d, close in cur.fetchall():
    nav_null_rows[code].append((d, close))

# gap 段 -> 展开成每条缺价日
gaps = []  # (etf_code, gap_start, gap_end, n_days)
for code, dates in has_nav.items():
    idxs = sorted(td_idx[d] for d in dates if d in td_idx)
    if len(idxs) < 2:
        continue
    for a, b in zip(idxs, idxs[1:]):
        if b - a <= 1:
            continue
        gaps.append((code, trade_days[a+1], trade_days[b-1], b-a-1))

# 所有 etf_daily 行
cur.execute("SELECT etf_code, date FROM etf_daily")
all_rows = set((r[0], r[1]) for r in cur.fetchall())

rows = []  # (code, date, 形态)
for code, gs, ge, nd in gaps:
    gd = sorted(d for d in trade_days if gs <= d <= ge)
    for d in gd:
        key = (code, d)
        if key in nav_null_rows and any(c[0] == d for c in nav_null_rows[code]):
            # 该日有行且 accum_nav NULL
            rows.append((code, d, 'row_nav_null'))
        elif key in all_rows:
            rows.append((code, d, 'row_no_nav'))
        else:
            rows.append((code, d, 'no_row'))

print(f"total gap days: {len(rows)}")
by_kind = collections.Counter(r[2] for r in rows)
print("by kind:", dict(by_kind))

# 按年月分布
by_ym = collections.Counter(r[1][:6] for r in rows)
print("by ym:", dict(sorted(by_ym.items())))

# 输出清单
with open('/tmp/accum_nav_gap_rows.json', 'w') as f:
    json.dump(rows, f)
print("wrote /tmp/accum_nav_gap_rows.json")

# 抽样建议:按时间段分层
import random
random.seed(42)
# 每半年取 up to 8 条
strata = collections.defaultdict(list)
for code, d, kind in rows:
    strata[(d[:6], kind)].append((code, d, kind))
print(f"\nstrata count: {len(strata)}")
