#!/usr/bin/env python3
# 【次日分批挂单】扩展2: 9模式 + 按市场/信号类型 (2026-08-15)
# 结论: 9模式全正改善(A-F Δ+9.9万~+10.0万, G/H/I Δ+12.1万~+12.7万);
#       按市场(K=1 N=1兜底): concept Δ+2.9万 / a Δ+1.5万 / industry Δ+1.0万 / hk Δ+0.4万 / global Δ+0.2万
# 注意: 本脚本"按年分解"段有 zip(items, stats) 错位bug(部分年份负delta为假象), 按年以
#       kelly_batch_limit_yearly.py(修复版)为准; 9模式段+按市场段可信
# 输出: /tmp/kelly_batch_limit_ext2.json
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_ext2.py

"""扩展2: 9模式敏感性 + 按年分解 + 按市场/信号类型"""
import sys, json
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_close, run_nextday_open, run_batch, topk_keep, summarize, clean_base, buy_info
from kelly_posfilter_backtest import base_key
from kelly_combo_advice_analysis import fIdx

# ===== 9 模式 (每日池, 买全部, 兜底 N=3 vs 次日开盘) =====
print('===== 9 模式敏感性 (每日池, 买全部) =====')
print(f'{"模式":<3s} {"收盘净":>9s} {"次日开盘净":>10s} {"N=3兜底净":>10s} {"Δ兜底vs开盘":>10s}')
modes_res = {}
for m in ['A','B','C','D','E','F','G','H','I']:
    s0 = summarize(run_close(m, keep=None, F=None)[0])
    s1 = summarize(run_nextday_open(m, keep=None, F=None)[0])
    items, stats = run_batch(m, keep=None, F=None, N=3, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s2 = summarize(items, stats)
    d = s2['net'] - s1['net']
    modes_res[m] = {'close': s0['net'], 'open': s1['net'], 'nd3': s2['net'], 'd': d, 'ret': s2['ret']}
    print(f'{m:<3s} {s0["net"]:+9.0f} {s1["net"]:+10.0f} {s2["net"]:+10.0f} {d:+10.0f} (收益{s2["ret"]:.2f}%)')

# ===== 按年分解 (每日池, K=1/2/3, 兜底 N=K vs 次日开盘) =====
print('\n===== 按年分解 (每日池, 兜底 N=K vs 次日开盘) =====')
from collections import defaultdict
YEARS = ['2011','2012','2013','2014','2015','2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026']

def by_year(items, stats):
    out = defaultdict(dict)
    for it, st in zip(items, stats):
        y = st['sd'][:4]
        out[y].setdefault('items', []).append(it)
        out[y].setdefault('st', []).append(st)
    res = {}
    for y in YEARS:
        if y not in out: continue
        s = summarize(out[y]['items'], out[y]['st'])
        res[y] = s
    return res

for k in [1,2,3]:
    keep = topk_keep('G', k)
    items_o, _ = run_nextday_open('G', keep=keep, F=None)
    # 按年分 open
    byo = defaultdict(list)
    for it in items_o: byo[it[2][:4]].append(it)
    items_b, stats_b = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    byb = defaultdict(list)
    for it, st in zip(items_b, stats_b): byb[st['sd'][:4]].append((it, st))
    print(f'--- K={k}: 年 | 次日开盘净 | N={k}兜底净 | Δ | 兜底均价% ---')
    for y in YEARS:
        if y not in byo: continue
        so = summarize(byo[y])
        if y in byb:
            its = [i for i,_ in byb[y]]; sts = [s for _,s in byb[y]]
            sb = summarize(its, sts)
            print(f'{y}: 开盘{so["net"]:+9.0f} 兜底{sb["net"]:+9.0f} Δ{sb["net"]-so["net"]:+8.0f} 均价{(sb.get("avg_disc",1)-1)*100:+.3f}%')
        else:
            print(f'{y}: 开盘{so["net"]:+9.0f}')

# ===== 按市场类型 (每日池, K=1, 兜底 N=1 vs 次日开盘) =====
print('\n===== 按市场类型 (每日池, K=1, 兜底 N=1 vs 次日开盘) =====')
from kelly_combo_advice_analysis import build_dims
DIMS = build_dims()
def mkt_of(t):
    key = '|'.join([str(t[fIdx['signal_date']]), str(t[fIdx['index_id']]), str(t[fIdx['signal']]),
                    str(t[fIdx['buy_date']]), str(t[fIdx['etf_code']]), str(t[fIdx['sell_date']])])
    dim = DIMS.get(key, {})
    return dim.get('mkt', 'unknown')

keep = topk_keep('G', 1)
# 收集每笔的 market
items_o, _ = run_nextday_open('G', keep=keep, F=None)
items_b, stats_b = run_batch('G', keep=keep, F=None, N=1, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
# 重建 day->rows 映射用于 mkt
from kelly_batch_limit_engine import build_day_pool
day_pool = build_day_pool('G', keep, None)
mkt_items = {}
for sd, (rows_in, _o) in day_pool.items():
    for t in rows_in:
        mkt_items[base_key(t)] = mkt_of(t)
mkts = defaultdict(lambda: {'o':[], 'b':[]})
for it in items_o:
    # items_o 没有 base_key... 需要用 next_date+code 匹配? 简单: 按 (buy_date) 近似
    pass
# 改用 per-trade 方式: 直接对每笔算
print('  (按市场类型需要 base_key 映射, 用 fill_trade 逐笔重算)')
mkts2 = defaultdict(lambda: {'close':0.0,'open':0.0,'batch':0.0,'n':0})
G = clean_base('G')
for t in G:
    bk = base_key(t)
    if bk not in mkt_items: continue
    mk = mkt_items[bk]
    amt = 10000.0  # K=1 每日池 per_slot=10000
    from kelly_batch_limit_engine import fill_trade
    r0 = fill_trade(t, amt, 0.0, False, mode='G')
    r1 = fill_trade(t, amt, 0.01, False, mode='G')
    if r0 is not None and r1 is not None:
        mkts2[mk]['open'] += r0[0]
        mkts2[mk]['batch'] += r1[0]
        mkts2[mk]['n'] += 1
for mk in sorted(mkts2):
    g = mkts2[mk]
    if g['n']:
        print(f'  {mk:10s} n={g["n"]:5d} 开盘净={g["open"]:+9.0f} N=1兜底净={g["batch"]:+9.0f} Δ={g["batch"]-g["open"]:+8.0f}')

