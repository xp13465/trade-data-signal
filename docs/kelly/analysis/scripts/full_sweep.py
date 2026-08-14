# -*- coding: utf-8 -*-
"""
归档注释块(2026-08-14,从 /tmp 归档至 docs/kelly/analysis/scripts/)
--------------------------------------------------------------------------------
日期      : 2026-08-14
结论      : signal_daily 全部 index_id 按 board_etf_map/self 分类, 回放修复前/后候选错进。
           与 replay_candidate.py 互补(全类别清扫 vs 目标类别回放)。
依赖      : sentiment.db(signal_daily) + board_etf_map.json + config/indicators.yaml(均读 ROOT)
复现命令  : python3 full_sweep.py   (cwd 可访问 ROOT = /Users/linhuichen/code/trade)
           输出: 全历史按类别分布 / 修复前默认档位候选 / 修复后 _bt_in_universe 候选 / 空数组标的清单
报告      : docs/kelly/analysis/kelly-ai-suggestion-wrong-entry-quantify.md
--------------------------------------------------------------------------------
"""
"""全量清扫: signal_daily 全部 index_id 按 board_etf_map/self 分类, 回放修复前/后候选错进。"""
import sqlite3, json, yaml
from pathlib import Path
from collections import defaultdict
ROOT = Path('/Users/linhuichen/code/trade')
conn = sqlite3.connect(str(ROOT/'data/sentiment.db')); conn.row_factory = sqlite3.Row
board = json.load(open(ROOT/'data/board_etf_map.json'))
ind = yaml.safe_load(open(ROOT/'config/indicators.yaml'))
indices = {i['id']: i for i in ind.get('indices', []) if i.get('enabled', True)}

def classify(iid):
    if iid.startswith('s.'): return 's.*情绪分'
    if iid.startswith('g.'): return 'g.指标'
    ic = indices.get(iid)
    if ic and ic.get('func')=='fund_etf_hist_sina': return 'self-ETF'
    v = board.get(iid)
    if v is None: return '无key'
    if isinstance(v,list) and len(v)==0: return '空数组'
    has_ts = any(isinstance(e,dict) and e.get('track_score') is not None for e in v)
    return '有key有track' if has_ts else '有key无track'

rows = conn.execute("SELECT date, index_id, signal FROM signal_daily WHERE index_id NOT LIKE 's.%'").fetchall()
clsn = defaultdict(int); pre = defaultdict(lambda: {'n':0,'dates':set()}); post = defaultdict(lambda: {'n':0,'dates':set()})
for r in rows:
    iid=r['index_id']; sig=r['signal']; c=classify(iid)
    clsn[c]+=1
    if sig=='band_hold': continue
    # 默认档位筛选: self->1, 有key->(有track?4:4), 空数组/无key->档5排除
    if c=='self-ETF':
        pre[c]['n']+=1; pre[c]['dates'].add(r['date'])
    elif c in ('有key有track','有key无track'):
        pre[c]['n']+=1; pre[c]['dates'].add(r['date'])
    # 修复后: 有key有track 才 _bt_in_universe=true
    if c=='有key有track':
        post[c]['n']+=1; post[c]['dates'].add(r['date'])
print('=== signal_daily(非s.*) 全历史按类别分布 ===')
for c in ['空数组','无key','self-ETF','有key有track','有key无track','g.指标']:
    print(f'  {c:12s} 信号条数={clsn[c]:6d}')
print()
print('=== 修复前候选(默认档位筛选)会进候选的类别(非band_hold) ===')
for c in ['空数组','无key','self-ETF','有key有track','有key无track']:
    if pre[c]['n']:
        print(f'  {c:12s} 条数={pre[c]["n"]:6d} 去重交易日={len(pre[c]["dates"])}')
print()
print('=== 修复后 _bt_in_universe=true 的信号(即 AI建议候选宇宙, 默认筛选) ===')
for c in ['有key有track']:
    print(f'  {c:12s} 条数={post[c]["n"]:6d} 去重交易日={len(post[c]["dates"])}')
print()
print('=== 空数组标的在 signal_daily 的 index_id 清单(除 ftse100/kospi) ===')
empty_ids = [k for k,v in board.items() if isinstance(v,list) and len(v)==0]
emptysig = defaultdict(int)
for r in rows:
    if r['index_id'] in set(empty_ids): emptysig[r['index_id']]+=1
for iid in sorted(emptysig, key=lambda x:-emptysig[x]):
    print(f'  {iid:16s} {emptysig[iid]:5d} 条')
if not emptysig: print('  (空数组标的在 signal_daily 无信号)')
# 确认: 空数组标的修复前全部档位时候选
pre_empty_all=0; pre_empty_dates=set()
for r in rows:
    if r['index_id'] in set(empty_ids) and r['signal']!='band_hold':
        pre_empty_all+=1; pre_empty_dates.add(r['date'])
print(f'  空数组标的(31个key) 修复前"全部档位"时进候选: {pre_empty_all} 条 / {len(pre_empty_dates)} 交易日')
