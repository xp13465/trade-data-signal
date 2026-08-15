#!/usr/bin/env python3
# 【基建】K敏感性 + 完整排序key (full_sort_key) + keep_topk (2026-08-12)
# 用途: 全站回测统一排序: track_score DESC → rating(high>mid>low) → signal(backup>buy>aux>special) → buy_date ASC
# 依赖: kelly_combo_advice_analysis / kelly_posfilter_backtest
# 注意: 顶层有打印(import时输出), 供调试参考

"""K 值敏感性回测: 每日按 track_score 保留前 K 个信号, K=1/2/3/4/5
主口径 = G模式(推荐卖出法), 1万/笔, 与 kelly-position-filter-backtest.md 同口径
排序key(按报告 §6.1): track_score DESC → rating(high>mid>low) → signal类型(backup>buy>aux>special) → buy_date ASC
"""
import sys, json
from collections import defaultdict
sys.path.insert(0, '/tmp')
from kelly_combo_advice_analysis import (compute_stats, to_row, passes_fade, BUY_AMOUNT, fIdx)
from kelly_posfilter_backtest import (base_signals, get_by_date, base_key, sort_key_score, COMBO4, LIVE4)

ALL_MODES = ['A','B','C','D','E','F','G','H','I']

# ---- 完整排序 key (报告 §6.1) ----
QUAL_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3, '': 9}
RATING_RANK = {'high': 0, 'mid': 1, 'low': 2, '': 3}

def full_sort_key(t):
    sc = t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    rat = str(t[fIdx['rating']] or '')
    sig = str(t[fIdx['signal']] or '')
    bd = str(t[fIdx['buy_date']] or '')
    return (-sc, RATING_RANK.get(rat, 3), QUAL_RANK.get(sig, 9), bd)

def keep_topk(mode, k, keyf=full_sort_key):
    """按 signal_date 分组, 组内 keyf 排序, 保留前 k 个基笔"""
    kept = []
    for sd, rows in get_by_date(mode).items():
        srt = sorted(rows, key=keyf)
        kept.extend(srt[:k])
    return set(base_key(t) for t in kept)

def stats_for(base, kk):
    rows = [to_row(t) for t in base if base_key(t) in kk]
    return compute_stats(rows, 'all', BUY_AMOUNT)

G_BASE = base_signals('G')

# ---- K=1/2 用完整key复现 vs 报告(用简单key)对比 ----
print('=== 排序key 对比: 完整key(K敏感性用) vs 报告sort_key_score ===')
for k in [1, 2]:
    kk_full = keep_topk('G', k, full_sort_key)
    s_full = stats_for(G_BASE, kk_full)
    kk_old = keep_topk('G', k, sort_key_score)
    s_old = stats_for(G_BASE, kk_old)
    print('K=%d  完整key: n=%d 净=%+.0f 持仓=%d 收益率=%.2f%% | 报告key: n=%d 净=%+.0f 持仓=%d 收益率=%.2f%%' % (
        k, s_full['n'], s_full['total_profit'], s_full['max_concurrent'], s_full['return_pct_max_holding'],
        s_old['n'], s_old['total_profit'], s_old['max_concurrent'], s_old['return_pct_max_holding']))

print()
print('='*100)
print('=== ① K 敏感性全维度对比 (G模式, 主口径) ===')
print('%-6s %6s %12s %7s %7s %7s %8s %7s %9s %8s %8s' % ('K', 'n', '净盈亏', '胜率%', '盈亏比', '年化%', '最大持仓', '收益率%', '最大回撤%', '半凯利%', '9模式合计n'))
KVALUES = [1, 2, 3, 4, 5]
full_stats = {}
for k in KVALUES:
    kk = keep_topk('G', k, full_sort_key)
    s = stats_for(G_BASE, kk)
    full_stats[k] = s
    # 9模式合计 n
    totn = 0
    for m in ALL_MODES:
        kkm = keep_topk(m, k, full_sort_key)
        totn += len([t for t in base_signals(m) if base_key(t) in kkm])
    print('K=%d   %6d %12s %6.1f %7s %6.2f %8d %8.2f %8.2f %7.2f %10d' % (
        k, s['n'], format(s['total_profit'], ','), s['win_rate']*100,
        s['pl_ratio'] if s['pl_ratio'] else '-', s['annualized_return'],
        s['max_concurrent'], s['return_pct_max_holding'], s['max_drawdown_pct'], s['half_kelly'], totn))

# P0 基线参考
s0 = stats_for(G_BASE, set(base_key(t) for t in G_BASE))
print('%-6s %6d %12s %6.1f %7s %6.2f %8d %8.2f %8.2f %7.2f' % (
    'P0', s0['n'], format(s0['total_profit'], ','), s0['win_rate']*100,
    s0['pl_ratio'] if s0['pl_ratio'] else '-', s0['annualized_return'],
    s0['max_concurrent'], s0['return_pct_max_holding'], s0['max_drawdown_pct'], s0['half_kelly']))

print()
print('=== ② 每 K 与基线 P0 差值 ===')
print('%-6s %14s %12s %14s %12s %14s' % ('K', 'Δ收益率(pt)', 'Δ净利(元)', 'Δ净利%', 'Δ持仓(笔)', 'Δ持仓%'))
for k in KVALUES:
    s = full_stats[k]
    dret = s['return_pct_max_holding'] - s0['return_pct_max_holding']
    dnet = s['total_profit'] - s0['total_profit']
    dnetp = dnet / s0['total_profit'] * 100
    dhold = s['max_concurrent'] - s0['max_concurrent']
    dholdp = (s['max_concurrent'] - s0['max_concurrent']) / s0['max_concurrent'] * 100
    print('K=%d   %+12.2f %+12.0f %+12.1f%% %+12d %+10.1f%%' % (k, dret, dnet, dnetp, dhold, dholdp))

print()
print('=== ③ 叠加4组合 (COMBO4) 边际: 每 K ===')
print('%-6s %18s %6s %12s %7s %8s %8s' % ('K', '场景', 'n', '净盈亏', '胜率%', '最大持仓', '收益率%'))
combo4_only = [t for t in G_BASE if passes_fade(t, COMBO4)]
sc4 = compute_stats([to_row(t) for t in combo4_only], 'all', BUY_AMOUNT)
print('%-6s %-18s %6d %12s %6.1f %8d %8.2f' % ('-', 'COMBO4单独', sc4['n'], format(sc4['total_profit'],','), sc4['win_rate']*100, sc4['max_concurrent'], sc4['return_pct_max_holding']))
for k in KVALUES:
    kk = keep_topk('G', k, full_sort_key)
    rows2 = [t for t in G_BASE if base_key(t) in kk and passes_fade(t, COMBO4)]
    s2 = compute_stats([to_row(t) for t in rows2], 'all', BUY_AMOUNT)
    print('K=%d   +COMBO4       %6d %12s %6.1f %8d %8.2f' % (k, s2['n'], format(s2['total_profit'],','), s2['win_rate']*100, s2['max_concurrent'], s2['return_pct_max_holding']))

print()
print('=== ④ 按年分解 (K=1/2/3/4, G模式) ===')
YEARS = ['2011','2012','2013','2014','2015','2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026']
year_cache = {k: {} for k in KVALUES}
for k in KVALUES:
    kk = keep_topk('G', k, full_sort_key)
    base = [t for t in G_BASE if base_key(t) in kk]
    by_year = defaultdict(list)
    for t in base:
        by_year[str(t[fIdx['signal_date']])[:4]].append(t)
    year_cache[k] = {y: stats_for_by_year(by_year[y]) if False else compute_stats([to_row(t) for t in by_year[y]], 'all', BUY_AMOUNT) for y in by_year}

# 也取 P0 按年
by_year0 = defaultdict(list)
for t in G_BASE:
    by_year0[str(t[fIdx['signal_date']])[:4]].append(t)
year_cache['P0'] = {y: compute_stats([to_row(t) for t in by_year0[y]], 'all', BUY_AMOUNT) for y in by_year0}

hdr = '%-5s %10s |' % ('年', 'P0净')
for k in KVALUES:
    hdr += ' %8s净 %5s %5s |' % ('K%d'%k, 'n', '胜率%')
print(hdr)
for y in YEARS:
    if y not in year_cache['P0']:
        continue
    row = '%-5s %+10.0f |' % (y, year_cache['P0'][y]['total_profit'])
    for k in KVALUES:
        if y in year_cache[k]:
            s = year_cache[k][y]
            row += ' %+8.0f %5d %5.1f |' % (s['total_profit'], s['n'], s['win_rate']*100)
        else:
            row += ' %8s %5s %5s |' % ('-', '-', '-')
    print(row)

print()
print('=== ⑤ 9模式敏感性: 每 K 下各模式收益率(净/峰值持仓) → 基线 ===')
print('%-3s' % '模式', end='')
for k in KVALUES:
    print(' %9s' % ('K=%d'%k), end='')
print(' %9s' % 'P0')
mode_ret = {m: {} for m in ALL_MODES}
for m in ALL_MODES:
    base_m = base_signals(m)
    s_m0 = compute_stats([to_row(t) for t in base_m], 'all', BUY_AMOUNT)
    mode_ret[m]['P0'] = s_m0
    for k in KVALUES:
        kk = keep_topk(m, k, full_sort_key)
        s = stats_for(base_m, kk)
        mode_ret[m][k] = s
for m in ALL_MODES:
    line = '%-3s' % m
    for k in KVALUES:
        line += ' %8.2f%%' % mode_ret[m][k]['return_pct_max_holding']
    line += ' %8.2f%%' % mode_ret[m]['P0']['return_pct_max_holding']
    print(line)

print()
print('=== ⑤b 9模式敏感性: 每 K 下各模式净盈亏 (标转负) ===')
print('%-3s' % '模式', end='')
for k in KVALUES:
    print(' %10s' % ('K=%d'%k), end='')
print(' %10s' % 'P0')
for m in ALL_MODES:
    line = '%-3s' % m
    for k in KVALUES:
        line += ' %+9.0f' % mode_ret[m][k]['total_profit']
    line += ' %+9.0f' % mode_ret[m]['P0']['total_profit']
    print(line)

