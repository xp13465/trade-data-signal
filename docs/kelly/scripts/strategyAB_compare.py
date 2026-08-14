# ============================================================
# 用途: 策略A(固定拆K: 每笔恒 DAILY/K) vs 策略B(现状: 每日池等分 DAILY/当日保留信号数) 穷举对比
# 日期/来源: 2026-08-14 / tmp
# 结论: 净利 B 恒优于 A(K=1 A≡B; G K=4 A 收益率微高为机制假象——A 每笔固定 DAILY/K 砍量导致持仓更小分母更小)
# 依赖: kelly_combo_advice_analysis.py + kelly_posfilter_backtest.py + dailypool_rerun_core.py 管线
# 输入/输出: 读 signal_kelly_trades.json, 输出 A/B 各 K 档净利/收益率/持仓对比
# 复现: python3 strategyAB_compare.py
# 注意: 原文件含硬编码绝对路径 /tmp 与 /Users/linhuichen/code/trade, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
"""策略A(固定拆K: 每笔恒 DAILY/K) vs 策略B(现状: 每日资金池等分 DAILY/当日保留信号数) 穷举对比
复用 /tmp/dailypool_rerun_core.py 管线(daily_pool_items 加 amt_mode)
口径: AI宏7键默认过滤 + topK + 每日资金池(顺序 = 先toggle过滤 -> 再topK, 与前端 lab.js 一致)
只读, 不改业务代码, 可写 /tmp
"""
import sys, math
from collections import defaultdict
sys.path.insert(0, '/tmp')
sys.path.insert(0, '/Users/linhuichen/code/trade')
from kelly_combo_advice_analysis import (passes_fade, fIdx, empty_filters, BUY_AMOUNT, compute_stats, to_row)
from kelly_posfilter_backtest import base_signals, get_by_date, base_key

ALL_MODES = ['A','B','C','D','E','F','G','H','I']
DAILY = 10000.0

QUAL_RANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}
RATING_RANK = {'high':0,'mid':1,'low':2,'':3}
def full_sort_key(t):
    sc = t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    rat = str(t[fIdx['rating']] or '')
    sig = str(t[fIdx['signal']] or '')
    bd = str(t[fIdx['buy_date']] or '')
    return (-sc, RATING_RANK.get(rat,3), QUAL_RANK.get(sig,9), bd)

# AI宏7键 = 当前页面默认推荐(lab.js:7253 _kellyDefaultFilters), 与既有报告一致
DEFAULT_NEW = {k: True for k in ['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial',
                                 'r7MayReinforced','excludeAuxCross','greedy15']}

def _date_diff_days(d1, d2):
    from datetime import datetime
    try:
        dd1 = datetime.strptime(d1, "%Y%m%d"); dd2 = datetime.strptime(d2, "%Y%m%d")
        return max(int((dd2 - dd1).total_seconds() / 86400), 0)
    except (ValueError, TypeError):
        return 0
def _years_from(dates):
    if not dates: return 1.0
    dMin = min(dates); dMax = max(dates)
    days = _date_diff_days(dMin, dMax)
    return max(days / 365.25, 1.0 / 365.25)
def _peak_capital(items):
    SENTINEL = "99999999"
    ev = defaultdict(int)
    for t in items:
        bd = t[2] or SENTINEL; sd = t[3] or SENTINEL
        ev[bd] += t[5]; ev[sd] -= t[5]
    peak = 0; cur = 0
    for dt in sorted(ev):
        cur += ev[dt]; peak = max(peak, cur)
    return peak
def compute_scaled(items):
    n = len(items)
    if n == 0:
        return {'n':0,'net':0,'win':0,'pl':None,'annualized':0,'peak_capital':0,'ret':0,'dd_pct':0,'calmar':0,'half_kelly':0,'total_invest':0,'n_days':0}
    wins = [t for t in items if t[0] > 0]; losses = [t for t in items if t[0] <= 0]
    wc = len(wins); lc = len(losses); winRate = wc/n
    avgWin = sum(t[1] for t in wins)/wc if wc else 0
    avgLossAbs = abs(sum(t[1] for t in losses)/lc) if lc else 0
    plRatio = avgWin/avgLossAbs if (lc>0 and avgLossAbs>0) else (999.0 if (wc>0 and lc==0) else None)
    totalInvest = sum(t[5] for t in items)
    totalProfit = sum(t[0] for t in items)
    peak = _peak_capital(items)
    ret = totalProfit/peak*100 if peak>0 else 0
    dates = [t[2] for t in items]
    years = _years_from(dates)
    annualized = (math.pow(1+ret/100, 1/years)-1)*100 if years>0 and ret > -100 else 0
    srt = sorted(items, key=lambda x: x[3] or "99999999")
    cum=0; peakc=0; maxDd=0
    for t in srt:
        cum += t[0]; peakc = max(peakc, cum); maxDd = max(maxDd, peakc-cum)
    dd_pct = maxDd/totalInvest*100 if totalInvest>0 else 0
    calmar = round(annualized/dd_pct, 2) if dd_pct and dd_pct>0 else 0
    p = winRate; q = 1 - p; b = plRatio if (plRatio and plRatio > 0) else 0
    fStar = (p - q / b) if b > 0 else 0; fStar = max(0, min(1, fStar))
    halfKelly = max(0, min(90, fStar / 2 * 100))
    return {'n':n,'net':totalProfit,'win':winRate*100,'pl':round(plRatio,2) if plRatio else None,
            'annualized':round(annualized,2),'peak_capital':peak,'ret':round(ret,2),
            'dd_pct':round(dd_pct,2),'calmar':calmar,'half_kelly':round(halfKelly,1),'total_invest':totalInvest,
            'n_days':len(set(t[2] for t in items))}

def daily_pool_items(mode, F, K, amt_mode='B'):
    """amt_mode: 'B'=现状(DAILY/当日保留数), 'A'=固定拆K(DAILY/K)
    返回 (items, idle_info), idle_info = {'active_days':, 'idle_days':, 'idle_amt':, 'idle_pct':}"""
    bd = get_by_date(mode)
    day_pool = {}
    if F:
        for sd, rows in bd.items():
            fr = [t for t in rows if passes_fade(t, F)]
            if fr: day_pool[sd] = fr
    else:
        day_pool = {sd: rows for sd, rows in bd.items() if rows}
    kept_keys = set(); day_counts = {}
    for sd, rows in day_pool.items():
        srt = sorted(rows, key=full_sort_key)[:K] if K and K>0 else rows
        day_counts[sd] = len(srt)
        for t in srt: kept_keys.add(base_key(t))
    items = []
    active_days = 0; idle_days = 0; idle_amt = 0.0
    for sd, rows in day_pool.items():
        n = day_counts.get(sd, 0)
        if n == 0: continue
        active_days += 1
        if amt_mode == 'A':
            amt = DAILY / K   # 固定拆K: 每笔恒 DAILY/K
            if n < K:
                idle_days += 1
                idle_amt += (K - n) * amt
        else:
            amt = DAILY / n   # 现状: 按当日保留数等分凑满
        for t in rows:
            if base_key(t) not in kept_keys: continue
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            items.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    idle_pct = (idle_amt / (DAILY * active_days) * 100) if active_days else 0.0
    return items, {'active_days': active_days, 'idle_days': idle_days, 'idle_amt': idle_amt, 'idle_pct': idle_pct}

def eval_strategy(mode, F, K, amt_mode):
    items, idle = daily_pool_items(mode, F, K, amt_mode)
    s = compute_scaled(items)
    s['idle_days'] = idle['idle_days']; s['idle_amt'] = idle['idle_amt']
    s['active_days'] = idle['active_days']; s['idle_pct'] = idle['idle_pct']
    return s

def fmt(s):
    return {'n':s['n'], 'net':round(s['net'],0), 'peak':round(s['peak_capital'],0),
            'ret':s['ret'], 'dd':s['dd_pct'], 'idle_days':s['idle_days'],
            'idle_amt':round(s['idle_amt'],0), 'active_days':s['active_days']}

print('=== 策略A(固定拆K) vs 策略B(现状等分) 逐位对比 — AI宏7键默认过滤 ===')
print('数据源: static-site/data/signal_kelly_trades.json (唯一基笔 7,597)')
print('策略A: 每笔恒 DAILY/K = %d/K, 当日保留数<K 时资金闲置' % DAILY)
print('策略B: 每笔 = DAILY/当日保留数, 每日凑满 %d' % DAILY)
print('='*150)
KS = [1,2,3,4]
for m in ['A','F','G']:
    print()
    print('----- 模式 %s -----' % m)
    print('%-3s %-14s %-14s %10s %10s %10s %8s %8s %10s | %-14s %-10s %10s %10s' % (
        'K','B净利','A净利','Δ净利(B-A)','B收益率%','A收益率%','B回撤%','A回撤%','B持仓元','A峰值持仓','A闲置天数','A闲置金额','A闲置率%'))
    # B=现状等分(参考), A=固定拆K
    for K in KS:
        sB = eval_strategy(m, DEFAULT_NEW, K, 'B')
        sA = eval_strategy(m, DEFAULT_NEW, K, 'A')
        dnet = sB['net'] - sA['net']
        print('K=%d  %+12.0f %+12.0f %+10.0f %10.2f %10.2f %8.2f %8.2f %10.0f | %-14.0f %-14s %9d %10.0f %9.2f' % (
            K, sB['net'], sA['net'], dnet, sB['ret'], sA['ret'], sB['dd_pct'], sA['dd_pct'], sB['peak_capital'],
            sA['peak_capital'], '', sA['idle_days'], sA['idle_amt'], sA['idle_pct']))

# 汇总: 合计 (ΣA+F+G)
print()
print('='*150)
print('合计(Σ A+F+G, 净利/持仓直接相加, 收益率=Σ净利/Σ持仓)')
print('%-3s %-14s %-14s %10s %10s %10s %10s | %-14s %-14s %10s %10s' % (
    'K','B净利Σ','A净利Σ','Δ净利','B收益率Σ','A收益率Σ','Δ收益率','B持仓Σ','A持仓Σ','A闲置天数Σ','A闲置金额Σ'))
for K in KS:
    b_net = b_peak = a_net = a_peak = 0.0; a_idle_days = 0; a_idle_amt = 0.0
    for m in ['A','F','G']:
        sB = eval_strategy(m, DEFAULT_NEW, K, 'B')
        sA = eval_strategy(m, DEFAULT_NEW, K, 'A')
        b_net += sB['net']; b_peak += sB['peak_capital']
        a_net += sA['net']; a_peak += sA['peak_capital']
        a_idle_days += sA['idle_days']; a_idle_amt += sA['idle_amt']
    print('K=%d  %+12.0f %+12.0f %+10.0f %10.2f %10.2f %10.2f | %-14.0f %-14.0f %9d %10.0f' % (
        K, b_net, a_net, b_net-a_net,
        b_net/b_peak*100 if b_peak else 0, a_net/a_peak*100 if a_peak else 0,
        (b_net/b_peak*100 if b_peak else 0) - (a_net/a_peak*100 if a_peak else 0),
        b_peak, a_peak, a_idle_days, a_idle_amt))

# K=1 自检: A≡B 逐位相同
print()
print('=== K=1 脚本正确性自检: A 与 B 应逐位相同 ===')
for m in ['A','F','G']:
    sB = eval_strategy(m, DEFAULT_NEW, 1, 'B')
    sA = eval_strategy(m, DEFAULT_NEW, 1, 'A')
    same = (abs(sB['net']-sA['net'])<1e-6 and abs(sB['peak_capital']-sA['peak_capital'])<1e-6 and abs(sB['ret']-sA['ret'])<1e-9)
    print('K=1 %s: B净=%+.2f A净=%+.2f B持仓=%.2f A持仓=%.2f A闲置天数=%d -> %s' % (
        m, sB['net'], sA['net'], sB['peak_capital'], sA['peak_capital'], sA['idle_days'], '一致OK' if same else '不一致FAIL'))

# 与既有报告对账(B策略基线, K=1/2/3/4 G模式)
print()
print('=== 对账: 策略B(现状) 与既有报告 kelly-dailypool-exhaustive-rerun.md §2 数值 ===')
print('%-3s %-3s | %s %s %s' % ('K','模式','本脚本净利','报告净利','本脚本收益率%'))
expect = {(1,'A'):(86603,86.60),(1,'F'):(118064,78.71),(1,'G'):(642184,47.22),
          (2,'A'):(74931,74.93),(2,'F'):(106865,71.24),(2,'G'):(611153,42.00),
          (3,'A'):(78905,78.91),(3,'F'):(110510,73.67),(3,'G'):(597280,40.86),
          (4,'A'):(79963,79.96),(4,'F'):(112463,74.98),(4,'G'):(595961,40.34)}
for K in KS:
    for m in ['A','F','G']:
        sB = eval_strategy(m, DEFAULT_NEW, K, 'B')
        e = expect.get((K,m), (None,None))
        print('K=%d %-3s | %+10.0f %s %10.2f %s' % (K, m, sB['net'], str(e[0]) if e[0] else '?', sB['ret'], str(e[1]) if e[1] else '?'))
