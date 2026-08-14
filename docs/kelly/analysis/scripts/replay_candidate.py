# -*- coding: utf-8 -*-
"""
归档注释块(2026-08-14,从 /tmp 归档至 docs/kelly/analysis/scripts/)
--------------------------------------------------------------------------------
日期      : 2026-08-14
结论      : #25(commit 8e6e14cad, _bt_in_universe 入样宇宙过滤)后, 量化"空数组/无key/港行行业标的"
           修复前错进首页 AI 建议候选的历史次数 + 验证修复后干净。
           核心结论: 814 债类 bug(cgb_10y_etf self ETF -> 档1)修复前错进候选 882 条/748 交易日;
           空数组(31 key)/无key(8个)在默认档位筛选(1-4)下错进=0, 仅"清空筛选/全档位"时错进
           (空数组 10252 条/3130 交易日 + 无key 6895 条/3668 交易日);
           修复后目标类别错进=0, 今日 overview 172 条 signals_today mismatch=0。
依赖      : sentiment.db(signal_daily) + board_etf_map.json + config/indicators.yaml(均读 ROOT)
复现命令  : python3 replay_candidate.py   (cwd 可访问 ROOT = /Users/linhuichen/code/trade)
           输出: 目标类别全历史分布 / 修复前默认档位候选 / 全档位候选 / 修复后错进 / 近15日窗口 / K=1 top1 分析
报告      : docs/kelly/analysis/kelly-ai-suggestion-wrong-entry-quantify.md
--------------------------------------------------------------------------------
"""
"""回放「#25修复前」首页 AI 建议候选构建逻辑, 统计目标类别(空数组/债类/港股行业)错进候选历史次数。
只读 sentiment.db + board_etf_map.json + indicators.yaml, 不改任何文件。
修复前候选判定(来自 #25 diff 前 app.js _dayItems + overview 链路):
  1. index_id 非 s.* (overview() 已排除情绪分)
  2. signal != "band_hold" (修复前 _dayItems 显式排除)
  3. 默认 ETF 档位筛选 sigEtfFilterSet=["1","2","3","4"] (app.js state 初始值):
       _signalTiers(it)= etfs 空 -> 5; 否则 min(_etfTier)
       _etfTier: match_method=self -> 1; track_tier strong=1/related=2/approx=3/none|null=4; undefined 回退 grade
  etfs 注入(overview 链路): 优先 _self_etf_for(func=fund_etf_hist_sina 且有 symbol -> self ETF), 否则 etf_for(board_etf_map)
  #25 修复后判定: 上述基础上再要求 _bt_in_universe = any(etf.track_score is not None)
"""
import sqlite3, json, yaml, sys
from pathlib import Path
ROOT = Path('/Users/linhuichen/code/trade')
conn = sqlite3.connect(str(ROOT/'data/sentiment.db')); conn.row_factory = sqlite3.Row
board = json.load(open(ROOT/'data/board_etf_map.json'))
ind = yaml.safe_load(open(ROOT/'config/indicators.yaml'))
indices = {i['id']: i for i in ind.get('indices', []) if i.get('enabled', True)}

def etfs_state(iid):
    """返回 (etfs非空?, self注入?, 档位 or None) 近似当前映射的 etfs 注入结果"""
    # 优先 self 注入
    ic = indices.get(iid)
    if ic and ic.get('func') == 'fund_etf_hist_sina' and ic.get('symbol'):
        return ('self', 1)
    raw = board.get(iid)
    if isinstance(raw, list) and len(raw) == 0:
        return ('empty', None)   # 空数组
    if not isinstance(raw, list):
        return ('nokey', None)   # 无 key
    # 有 key 且非空: 档位 = min(_etfTier)
    tiers = []
    for e in raw:
        if not isinstance(e, dict): continue
        t = e.get('track_tier')
        if t == 'strong': tiers.append(1)
        elif t == 'related': tiers.append(2)
        elif t == 'approx': tiers.append(3)
        elif t in ('none', None): tiers.append(4)
        else:  # undefined -> 回退 grade
            g = e.get('grade')
            tiers.append(1 if g == 'excellent' else (2 if g == 'good' and e.get('match_method') != 'manual_fallback' else 4))
    return ('key', min(tiers) if tiers else 4)

CATS = {'empty': '空数组标的(ftse100/kospi等)', 'nokey': '无key标的(cgb_idx/hk_等)', 'self': 'self-ETF债类(cgb_10y_etf)'}

# 全历史目标类别信号: ftse100/kospi/cgb_*/hk_* (非 s.*)
rows = conn.execute(
    "SELECT date, index_id, signal, reason FROM signal_daily "
    "WHERE index_id NOT LIKE 's.%' AND (index_id LIKE 'ftse%' OR index_id LIKE 'kospi%' "
    "OR index_id LIKE 'cgb%' OR index_id LIKE 'hk_%') ORDER BY date, index_id").fetchall()
print(f'目标类别信号全历史总条数: {len(rows)}')

# 按类别分组的修复前/后候选判定
from collections import defaultdict
st = defaultdict(lambda: {'cat':'', 'idx':set(), 'dates':set(), 'n':0, 'after_wrong':0})
for r in rows:
    iid = r['index_id']; sig = r['signal']
    if 'ftse' in iid or 'kospi' in iid:
        cat = 'empty'
    elif iid.startswith('cgb'):
        cat = 'self' if (indices.get(iid) or {}).get('func') == 'fund_etf_hist_sina' else 'nokey'
    elif iid.startswith('hk_'):
        cat = 'nokey'
    else:
        cat = 'other'
    st[iid]['cat'] = cat
    st[iid]['idx'].add(iid); st[iid]['n'] += 1
    st[iid]['dates'].add(r['date'])

for iid in sorted(st):
    d = st[iid]
    print(f"  {iid:18s} {CATS[d['cat']]:28s} 条数={d['n']:5d} 交易日={len(d['dates']):5d}")

# 修复前候选判定(逐信号): 非band_hold 且 档位∈[1,2,3,4](默认筛选) -> 进候选
print()
print('=== 修复前候选判定(默认档位筛选 ["1","2","3","4"]) ===')
pre = defaultdict(lambda: {'n':0, 'dates':set(), 'idx':set(), 'by_sig':defaultdict(int)})
for r in rows:
    iid = r['index_id']; sig = r['signal']
    if sig == 'band_hold':
        continue
    state_kind, tier = etfs_state(iid)
    if tier is not None and 1 <= tier <= 4:   # 默认筛选保留
        key = state_kind
        pre[key]['n'] += 1
        pre[key]['dates'].add(r['date'])
        pre[key]['idx'].add(iid)
        pre[key]['by_sig'][sig] += 1
for k in ['self','key','empty','nokey']:
    if pre[k]['n']:
        print(f"  {CATS[k]:32s} 进候选信号条数={pre[k]['n']:5d} 去重交易日={len(pre[k]['dates']):5d} index_id={sorted(pre[k]['idx'])}")
        print(f"      signal 分布: {dict(pre[k]['by_sig'])}")
print()
print('=== 修复前候选判定(全部档位=用户清空筛选时, 档5也保留) ===')
pre_all = defaultdict(lambda: {'n':0, 'dates':set(), 'idx':set()})
for r in rows:
    iid = r['index_id']; sig = r['signal']
    if sig == 'band_hold':
        continue
    state_kind, tier = etfs_state(iid)
    pre_all[state_kind]['n'] += 1
    pre_all[state_kind]['dates'].add(r['date'])
    pre_all[state_kind]['idx'].add(iid)
for k in ['self','key','empty','nokey']:
    if pre_all[k]['n']:
        print(f"  {CATS[k]:32s} 进候选信号条数={pre_all[k]['n']:5d} 去重交易日={len(pre_all[k]['dates']):5d} index_id={sorted(pre_all[k]['idx'])}")

# 修复后判定: 上述 + _bt_in_universe=any(track_score is not None)
print()
print('=== 修复后判定(默认筛选 + _bt_in_universe) 目标类别错进 ===')
after = {'n':0, 'dates':set()}
for r in rows:
    iid = r['index_id']; sig = r['signal']
    if sig == 'band_hold':
        continue
    state_kind, tier = etfs_state(iid)
    if tier is not None and 1 <= tier <= 4:
        # 修复后还要 track_score 非空; 目标类别中仅 self-ETF 会有 etfs, 但 track_score=None
        has_ts = False
        ic = indices.get(iid)
        if ic and ic.get('func') == 'fund_etf_hist_sina':
            has_ts = False  # self ETF 无 track_score
        else:
            raw = board.get(iid)
            has_ts = isinstance(raw, list) and any(isinstance(e, dict) and e.get('track_score') is not None for e in raw)
        if has_ts:
            after['n'] += 1
            after['dates'].add(r['date'])
print(f'  修复后仍错进(标 true)的目标类别信号条数={after["n"]} 去重交易日={len(after["dates"])}')

# ===== 近15交易日窗口(当前用户可见)修复前错进 =====
print()
print('=== 近15交易日窗口(20260727~20260814) 修复前错进 ===')
wrows = conn.execute(
    "SELECT date, index_id, signal FROM signal_daily "
    "WHERE index_id NOT LIKE 's.%' AND (index_id LIKE 'ftse%' OR index_id LIKE 'kospi%' "
    "OR index_id LIKE 'cgb%' OR index_id LIKE 'hk_%') "
    "AND date >= '20260727' ORDER BY date, index_id").fetchall()
from collections import defaultdict
w_pre = defaultdict(lambda: {'n':0,'dates':set(),'idx':set()})
w_pre_all = defaultdict(lambda: {'n':0,'dates':set(),'idx':set()})
for r in wrows:
    iid=r['index_id']; sig=r['signal']
    if sig=='band_hold': continue
    state_kind, tier = etfs_state(iid)
    if tier is not None and 1<=tier<=4:
        w_pre[state_kind]['n']+=1; w_pre[state_kind]['dates'].add(r['date']); w_pre[state_kind]['idx'].add(iid)
    w_pre_all[state_kind]['n']+=1; w_pre_all[state_kind]['dates'].add(r['date']); w_pre_all[state_kind]['idx'].add(iid)
print('  [默认档位筛选] 进候选:')
for k in ['self','key','empty','nokey']:
    if w_pre[k]['n']: print(f"    {CATS[k]:30s} 条数={w_pre[k]['n']} 交易日={sorted(w_pre[k]['dates'])} idx={sorted(w_pre[k]['idx'])}")
print('  [全部档位] 进候选:')
for k in ['self','key','empty','nokey']:
    if w_pre_all[k]['n']: print(f"    {CATS[k]:30s} 条数={w_pre_all[k]['n']} 交易日数={len(w_pre_all[k]['dates'])} idx={sorted(w_pre_all[k]['idx'])}")

# ===== top-K 增强(K=1): 修复前 cgb_10y_etf 有多少真正进 AI建议 top1 =====
# 排序: _posCapSortedFn 按 track_score DESC(无则 -1) -> 评级 -> 类型 -> 买入日
# 该日窗口内候选若只有 cgb_10y_etf 或全无 track_score, 则它进 top1
print()
print('=== 修复前 K=1 口径: 每个交易日窗口内 cgb_10y_etf 是否排进 AI建议 top1 ===')
# 取全历史日期, 对每个日期 dt 构造窗口(前15交易日) -> 但这里简化为: cgb_10y_etf 某信号日
# 当日候选(同 dt 非band_hold 且默认档位保留)里是否只有它 -> 近似: 统计 cgb_10y_etf 进候选的
# 交易日中, 当日同窗口其他候选也多为 cgb_10y_etf 自身(多信号同日)
# 直接按信号日回放: 对每条 cgb_10y_etf 候选, 检查"它被渲染的窗口内"其 top1 概率
# 简化近似: 计算 cgb_10y_etf 进候选的信号日中, 当日仅此类别进候选的天数
day_has = defaultdict(set)
for r in rows:
    iid=r['index_id']; sig=r['signal']
    if sig=='band_hold': continue
    state_kind, tier = etfs_state(iid)
    if tier is not None and 1<=tier<=4:
        day_has[r['date']].add(state_kind)
cgb_days = sorted({r['date'] for r in rows if r['index_id']=='cgb_10y_etf' and r['signal']!='band_hold' and etfs_state('cgb_10y_etf')[1] in (1,2,3,4)})
only_cgb = [d for d in cgb_days if day_has.get(d)=={'self'}]
both = [d for d in cgb_days if day_has.get(d)!= {'self'} and day_has.get(d)]
print(f'  cgb_10y_etf 进候选交易日共 {len(cgb_days)} 天')
print(f'  其中当日仅 cgb_10y_etf 一种候选(必进 top1): {len(only_cgb)} 天, 如 {only_cgb[:5]}...')
print(f'  当日还有其他候选(track_score=-1 垫底, 可能被挤出 top1): {len(both)} 天')
