#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目的:修正 a-to-h-rollover-design 报告测试基础 —— 从「全量有评级信号 7,598 笔」改为
      「S06 过滤 + K=1 前提下平台实际推荐/入账的信号集合」。
方法口径:
  1) 逐笔重放 queries.py _ai_macro_hit_filters(生产 overview 注入 ai_macro.filters 同源, 已对账 103/105 逐位一致)
  2) S06 过滤: 按信号日读 kelly_mode_s06_state.json effective_mode(a9/new14) → 套对应键集,
     filters∩键集非空 或 (基座a9 且 bullAuxBackupStop 命中: buy_aux/buy_backup×hs300四档=牛市·主升) → 剔除
  3) K=1: 存活信号按日分组, 排序=track_score DESC→rating(high>mid>low)→signal(buy_backup>buy>buy_aux>buy_special)
     →buy_date ASC, 每日取 top-1(与 app.js _posCapSortedFn L6178/lab.js L7791 逐位一致)
  4) 阶段2: 在入账集合上重算 A 第10日亏损画像 / 混合proxy / A vs H 基线
输入依赖: static-site/data/signal_kelly_trades.json(7,598 有评级∩入样信号)
          static-site/data/kelly_mode_s06_state.json(S06 逐日基座)
          static-site/data/market_tier_history.json(hs300 四档, tier/ma60 判定源)
          static-site/data/kelly_loss_features.json(特征类键, 覆盖至 20260824)
          config/indicators.yaml(index→market) + app/queries.py + scripts/loss_rules.py
关键参数: BUY 白名单 4 信号; a9=17键/new14=14键(common.js L812/L818 逐位一致); K=1; 排序第一键=track_score
数据截止: 2026-09-04(最近信号日); S06 快照 current=new14(since 20260831)
复现命令: /Users/linhuichen/code/trade/.venv/bin/python docs/kelly/analysis/scripts/a_to_h_s06k1_caliber.py
"""
# (本文件由 s06k1_repro.py + s06k1_stage2.py 合并, 同构对账证据见 a-to-h-s06k1-caliber-fix-20260908.md §阶段1对账节)
import json, sys, collections
sys.path.insert(0, '/Users/linhuichen/code/trade')
import app.queries as q
import yaml

TRADES = '/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json'
S06 = '/Users/linhuichen/code/trade/static-site/data/kelly_mode_s06_state.json'
TIERS = '/Users/linhuichen/code/trade/static-site/data/market_tier_history.json'
IND = '/Users/linhuichen/code/trade/config/indicators.yaml'
LOSS_FEAT = '/Users/linhuichen/code/trade/static-site/data/kelly_loss_features.json'

# ---- S06 键集(a9/new14, 与 common.js/_AI_CONSENSUS_PRESETS 逐位一致) ----
A9_KEYS = set(q._AI_CONSENSUS_PRESETS["a9"]["keys"])
NEW14_KEYS = set(q._AI_CONSENSUS_PRESETS["new14"]["keys"])

# ---- 加载 ----
trades = json.load(open(TRADES))
s06 = json.load(open(S06))
tiers = {r['date']: r for r in json.load(open(TIERS))}
cfg = yaml.safe_load(open(IND))
market_map = {i['id']: f"mkt_{i['market']}" for i in cfg.get('indices', []) if i.get('id') and i.get('market')}
# 特征
import scripts.loss_rules as lr
feats = lr.load_features(LOSS_FEAT) if __import__('os').path.exists(LOSS_FEAT) else None
feat_at = lr.make_feat_at(feats)

F = trades['fields']
rows = [dict(zip(F, r)) for qd in trades['quadrants'].values() for r in qd['A']]
# 去重(同一信号 date|index_id|signal 只保留一次, 跨象限重复)
uniq = {}
for rd in rows:
    k = (rd['signal_date'], rd['index_id'], rd['signal'])
    uniq.setdefault(k, rd)
rows = list(uniq.values())
print(f"唯一信号(有评级∩入样): {len(rows)}")

# 逐笔重放 filters
out = []
for rd in rows:
    d = rd['signal_date']
    mkt = market_map.get(rd['index_id'], "")
    sig = {"date": d, "index_id": rd['index_id'], "signal": rd['signal'],
           "etfs": [{"track_score": rd['track_score'], "track_tier": rd['track_tier']}]}
    t = tiers.get(d, {}).get('tier', "")
    m60 = bool(tiers.get(d, {}).get('ma60_bull', False))
    ctx = {
        "rating_of": lambda _s, rd=rd: rd['rating'],
        "market_of": lambda _iid, mkt=mkt: mkt,
        "track_score_of": lambda _s, rd=rd: rd['track_score'],
        "tier_of": lambda _dd, t=t: t,
        "ma60_bull_of": lambda _dd, m60=m60: m60,
        "cyb_tier_of": lambda _dd, rd=rd: rd['market_tier_cyb'],
    }
    ctx["feat_at"] = feat_at
    filters = q._ai_macro_hit_filters(sig, ctx)
    # 每笔按日期算 S06 基座
    s06d = s06['daily']  # list of dict
    # 找 d 的 effective_mode
    mode = None
    # binary search
    import bisect
    dates_arr = [r_['date'] for r_ in s06d]
    i = bisect.bisect_right(dates_arr, d) - 1
    if i >= 0:
        mode = s06d[i]['effective_mode']
    if mode is None:
        mode = s06.get('off_base', 'new14')  # 覆盖外兜底
    keys = A9_KEYS if mode == 'a9' else NEW14_KEYS
    # S06 过滤
    fade_hit = any(fk in keys for fk in filters)
    # bullAuxBackupStop 特判(仅 a9 基座)
    bull_hit = False
    if mode == 'a9' and rd['signal'] in ('buy_aux', 'buy_backup') and t == '牛市·主升':
        bull_hit = True
    kept = not (fade_hit or bull_hit)
    out.append({
        'date': d, 'index_id': rd['index_id'], 'signal': rd['signal'],
        'rating': rd['rating'], 'ts': rd['track_score'], 'mode': mode,
        'filters': filters, 'fade_hit': fade_hit, 'bull_hit': bull_hit,
        'kept': kept, 'market_tier': rd['market_tier'],
    })

# 统计
total = len(out)
kept_all = [o for o in out if o['kept']]
faded = [o for o in out if not o['kept']]
print(f"全量: {total} 笔; S06 过滤后存活(未K): {len(kept_all)} 笔; 被过滤: {len(faded)} 笔 ({len(faded)/total*100:.1f}%)")

# K=1: 每日排序取 top1(排序=track_score DESC→rating high>mid>low→signal backup>buy>aux>special→date ASC)
RC = {'high':0, 'mid':1, 'low':2, '':3}
SC = {'buy_backup':0, 'buy':1, 'buy_aux':2, 'buy_special':3, '':9}
by_day = collections.defaultdict(list)
for o in kept_all:
    by_day[o['date']].append(o)

def sort_key(o):
    return (-(o['ts'] if o['ts'] is not None else -1),
            RC.get(o['rating'], 3),
            SC.get(o['signal'], 9),
            o['date'])
k1_kept = []
for d, lst in by_day.items():
    lst.sort(key=sort_key)
    for i, o in enumerate(lst):
        o['k1_rank'] = i + 1
        o['k1_kept'] = (i == 0)
        if i == 0:
            k1_kept.append(o)
# 被 K1 挤掉(存活但非 top1)
non_top1 = [o for o in kept_all if not o.get('k1_kept', True)]
print(f"K=1 后实际入账: {len(k1_kept)} 笔; 存活但被 K1 挤掉: {len(non_top1)} 笔")

# 分年
def yr(rows_):
    c = collections.Counter(r['date'][:4] for r in rows_)
    return dict(sorted(c.items()))
print("全量分年:", yr(out))
print("S06过滤后分年:", yr(kept_all))
print("S06+K1入账分年:", yr(k1_kept))
print()
print("被过滤模式分布:", dict(collections.Counter((o['mode'], o['rating']) for o in faded).most_common(10)))
# 保存中间产物
json.dump({o['date']+'|'+o['index_id']+'|'+o['signal']: o for o in out},
          open('/tmp/s06k1_sig_filters.json','w'), ensure_ascii=False)
print("已存 /tmp/s06k1_sig_filters.json")
import json, sys, collections
sys.path.insert(0, '/Users/linhuichen/code/trade')

trades = json.load(open('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json'))
F = trades['fields']
fidx = {k: i for i, k in enumerate(F)}

# 全量 A/H 单索引: (date,index_id,signal) -> 记录
a_rows = {}; h_rows = {}
for qd in trades['quadrants'].values():
    for r in qd['A']:
        rd = dict(zip(F, r)); a_rows[(rd['signal_date'], rd['index_id'], rd['signal'])] = rd
    for r in qd['H']:
        rd = dict(zip(F, r)); h_rows.setdefault((rd['signal_date'], rd['index_id'], rd['signal']), rd)

# 读取复现的入账集合(541)
sigf = json.load(open('/tmp/s06k1_sig_filters.json'))
k1 = {k: v for k, v in sigf.items() if v['kept'] and v.get('k1_kept', False)}
print(f"S06+K1 入账集合: {len(k1)} 笔")
rating_ct = collections.Counter(v['rating'] for v in k1.values())
print("评级分布:", dict(rating_ct))
yr_ct = collections.Counter(v['date'][:4] for v in k1.values())
print("年度分布:", dict(sorted(yr_ct.items())))

# 周期截断(同 backtest period_cutoffs: y1=20250908, y3=20230909, y5=20210909)
def in_period(d, cutoff):
    if cutoff == '0': return True
    return d < cutoff  # 注意: backtest 是 signal_date >= cutoff 是"近N年"
# 实际上 period_cutoffs 定义: y1 cutoff='20250908' 表示 近1年 = signal_date >= 20250908
# 原报告 y1 用 signal_kelly_backtest.json, 这里 trades 自己算: y1 = signal_date >= 20250908
cutoffs = {'y1': '20250908', 'y3': '20230909', 'y5': '20210909', 'all': '0'}
def per(tag):
    c = cutoffs[tag]
    return [v for v in k1.values() if (True if c=='0' else v['date'] >= c)]

for tag in ('all','y1','y3','y5'):
    rows = per(tag)
    rc = collections.Counter(v['rating'] for v in rows)
    print(f"  {tag}: {len(rows)} 笔, rating={dict(rc)}")

# ---- §1.6: A 第10日亏损单画像 ----
print("\n===== §1.6 A 第10日亏损单画像(S06+K1 口径) =====")
print("| 象限 | 笔数 | 第10日亏损(profit<=0) | 占比 | 转H合计盈亏 | 转盈笔数 |")
for rating in ('high','mid','low'):
    rows = [v for v in k1.values() if v['rating'] == rating]
    n = len(rows)
    bad = []
    for v in rows:
        key = (v['date'], v['index_id'], v['signal'])
        a = a_rows.get(key)
        if a is None: continue
        if a['profit'] <= 0:
            h = h_rows.get(key)
            hprof = h['profit'] if h else None
            bad.append((a, h, hprof))
    nbad = len(bad)
    pct = nbad/n*100 if n else 0
    hsum = sum(b[2] for b in bad if b[2] is not None)
    hwin = sum(1 for b in bad if b[2] is not None and b[2] > 0)
    print(f"| rating_{rating} | {n} | {nbad} | {pct:.1f}% | {hsum:+,.0f} | {hwin}/{nbad} |")

# ---- §1.7: 混合 proxy ----
print("\n===== §1.7 混合 proxy(S06+K1 口径) =====")
print("口径: 每笔 A第10日盈利→保留A; 亏损→套H出场")
for tag in ('all','y1','y3','y5'):
    rows = per(tag)
    tot_a = 0.0; tot_h = 0.0; tot_mix = 0.0; win = 0; tot = 0
    for v in rows:
        key = (v['date'], v['index_id'], v['signal'])
        a = a_rows.get(key); h = h_rows.get(key)
        if a is None: continue
        tot_a += a['profit']
        if h is not None: tot_h += h['profit']
        if a['profit'] <= 0:
            if h is not None:
                tot_mix += h['profit']
                tot += 1
                if h['profit'] > 0: win += 1
            else:
                tot_mix += a['profit']; tot += 1
                if a['profit'] > 0: win += 1
        else:
            tot_mix += a['profit']
            tot += 1
            if a['profit'] > 0: win += 1
    wr = win/tot*100 if tot else 0
    print(f"  {tag}: n={len(rows)}, A净利={tot_a:+,.0f}, H净利={tot_h:+,.0f}, 混合proxy={tot_mix:+,.0f}, 混合胜率={wr:.1f}%")

# ---- A vs H 基线对照 ----
print("\n===== A vs H 基线(S06+K1 口径) =====")
for tag in ('all','y1'):
    rows = per(tag)
    sa=sh=0.0; wa=wh=0
    for v in rows:
        key = (v['date'], v['index_id'], v['signal'])
        a = a_rows.get(key); h = h_rows.get(key)
        if a: sa+=a['profit']; wa += 1 if a['profit']>0 else 0
        if h: sh+=h['profit']; wh += 1 if h['profit']>0 else 0
    print(f"  {tag}: A净利={sa:+,.0f} 胜率={wa/len(rows)*100:.1f}% | H净利={sh:+,.0f} 胜率={wh/len(rows)*100:.1f}%")

# ===== 阶段2b: H 出场分布 + 峰并发 =====
print("\n===== H 单出场分布(S06+K1 入账集合) =====")
from datetime import datetime
for tag in ('all', 'y1'):
    c = cutoffs[tag]
    rows = [v for v in k1.values() if (c == '0' or v['date'] >= c)]
    ct = collections.Counter(); days = []
    for v in rows:
        h = h_rows.get((v['date'], v['index_id'], v['signal']))
        if h:
            ct[h['sell_reason']] += 1
            days.append(h['hold_days'])
    print(f"  {tag} (n={len(rows)}): {dict(ct)}; avg_hold={sum(days)/len(days):.1f}日")
print("\n===== 峰并发(扫描线, 同日先卖后买保守) =====")
def _scan(rows, use_a, use_h):
    evts = []
    for v in rows:
        key = (v['date'], v['index_id'], v['signal'])
        a = a_rows.get(key); h = h_rows.get(key)
        if use_h and h is not None:
            sd = datetime.strptime(v['date'], '%Y%m%d')
            ed = datetime.strptime(h['sell_date'], '%Y%m%d') if h.get('sell_date') else sd
        else:
            if a is None: continue
            sd = datetime.strptime(v['date'], '%Y%m%d')
            ed = datetime.strptime(a['sell_date'], '%Y%m%d') if a.get('sell_date') else sd
        if ed < sd: ed = sd
        evts.append((sd, 1)); evts.append((ed, -1))
    evts.sort(key=lambda x: (x[0], -x[1])); cur = 0; mx = 0
    for _t, d in evts:
        cur += d; mx = max(mx, cur)
    return mx
def _mix_intervals(rows):
    evts = []
    for v in rows:
        key = (v['date'], v['index_id'], v['signal'])
        a = a_rows.get(key); h = h_rows.get(key)
        sd = datetime.strptime(v['date'], '%Y%m%d')
        if a['profit'] <= 0 and h is not None:
            ed = datetime.strptime(h['sell_date'], '%Y%m%d') if h.get('sell_date') else sd
        else:
            ed = datetime.strptime(a['sell_date'], '%Y%m%d') if a.get('sell_date') else sd
        if ed < sd: ed = sd
        evts.append((sd, 1)); evts.append((ed, -1))
    evts.sort(key=lambda x: (x[0], -x[1])); cur = 0; mx = 0
    for _t, d in evts:
        cur += d; mx = max(mx, cur)
    return mx
for rating in ('high', 'mid', 'low'):
    rows = [v for v in k1.values() if v['rating'] == rating]
    if not rows: continue
    print(f"  rating_{rating} n={len(rows)}: A峰并发={_scan(rows,True,False)}, H峰并发={_scan(rows,False,True)}, 混合proxy峰并发={_mix_intervals(rows)}")
