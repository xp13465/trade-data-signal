# ============================================================
# 用途: 每日池口径穷举重跑核心(08-13 权威基线, 与报告 kelly-dailypool-exhaustive-rerun.md 对应)
# 日期/来源: 2026-08-13 / tmp
# 结论: 主基准=当前页面 AI宏7键默认推荐; 每日池 A/F/G x K1-4 收益率表; G 模式 47.22%→40.34%
# 依赖: kelly_combo_advice_analysis.py + kelly_posfilter_backtest.py
# 输入/输出: 读 signal_kelly_trades.json, 输出 /tmp 下各配置统计
# 复现: python3 dailypool_rerun_core.py
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
"""每日池口径穷举重跑 — 核心脚本(干净版)
主基准 = 当前页面 AI宏7键默认推荐(lab.js _kellyDefaultFilters 2026-08-13)
对比项 = 4组合全开(过时基准, 仅对比)
前端一致口径(lab.js:7558/7520): 先 toggle 过滤基笔池 -> 按 signal_date topK -> 每笔=10000/当日保留数
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

# ---- 基准定义 ----
# AI宏7键 = 当前页面默认推荐(基础4 + 核心3), 见 lab.js:7251 _kellyDefaultFilters
DEFAULT_NEW = {k: True for k in ['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial',
                                 'r7MayReinforced','excludeAuxCross','greedy15']}
# 4组合全开(过时基准, 审计口径) = AI(base: exclSpecialBear/n2/J1/J2) + n3+v4d+r8+greedy15
FULL_AUDIT = {k: True for k in ['excludeSpecialBear','n2NovSpecialIndustry','janMidRating','janMidSpecial',
                                'n3NovSpecialMon','v4d','r8PureNonMay','greedy15']}

# ---- 每日池统计 ----
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

def daily_pool_items(mode, F, K):
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
    for sd, rows in day_pool.items():
        n = day_counts.get(sd, 0)
        if n == 0: continue
        amt = DAILY / n
        for t in rows:
            if base_key(t) not in kept_keys: continue
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            items.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items

def eval_daily(mode, F, K):
    return compute_scaled(daily_pool_items(mode, F, K))

def eval_per1w(mode, F, K):
    bd = get_by_date(mode)
    day_pool = {}
    if F:
        for sd, rows in bd.items():
            fr = [t for t in rows if passes_fade(t, F)]
            if fr: day_pool[sd] = fr
    else:
        day_pool = {sd: rows for sd, rows in bd.items() if rows}
    kept_keys = set()
    for sd, rows in day_pool.items():
        srt = sorted(rows, key=full_sort_key)[:K] if K and K>0 else rows
        for t in srt: kept_keys.add(base_key(t))
    rows = [to_row(t) for t in base_signals(mode) if base_key(t) in kept_keys]
    return compute_stats(rows, 'all', BUY_AMOUNT)

# ============ 基线对账 ============
print('=== 基线对账: 每笔1万 4组合全开(审计) vs AI宏7键 ===')
for K in [1,2,3,4]:
    for m in ['A','F','G']:
        s1 = eval_per1w(m, FULL_AUDIT, K)
        s2 = eval_per1w(m, DEFAULT_NEW, K)
        print('K=%d %s | 4组合: 收益=%.2f%% 净=%+.0f | AI宏7键: 收益=%.2f%% 净=%+.0f' % (
            K, m, s1['return_pct_max_holding'], s1['total_profit'], s2['return_pct_max_holding'], s2['total_profit']))

print()
print('=== 基线对账: 每日池 空filter K=1 G 旧报告 48.88%/+787,016 ===')
for K in [1,2]:
    s = eval_daily('G', None, K)
    print('K=%d: 净=%+.0f 收益率=%.2f%% 持仓=%.0f' % (K, s['net'], s['ret'], s['peak_capital']))

# ============ 任务1: 主基准 AI宏7键 A/F/G x K1-4 每日池(主) vs 每笔1万 ============
print()
print('='*120)
print('任务1(主): 当前页面默认推荐 AI宏7键 + positionCap K1-4, 每日池口径(主) vs 每笔1万')
print('%-3s %-3s | %14s %12s %9s %8s %7s | %12s %12s %9s' % ('K','模式','池收益率%','池净利','池持仓','池回撤%','池calmar','1w收益率%','1w净利','1w持仓'))
for K in [1,2,3,4]:
    for m in ['A','F','G']:
        sd = eval_daily(m, DEFAULT_NEW, K)
        sp = eval_per1w(m, DEFAULT_NEW, K)
        print('K=%d %-3s | %13.2f %+11.0f %9.0f %8.2f %7.2f | %11.2f %+11.0f %9.0f' % (
            K, m, sd['ret'], sd['net'], sd['peak_capital'], sd['dd_pct'], sd['calmar'], sp['return_pct_max_holding'], sp['total_profit'], sp['max_concurrent_capital']))

# ============ 任务1b: 对比项 4组合全开(过时基准) 每日池口径 ============
print()
print('='*120)
print('任务1b(对比): 4组合全开(过时基准, 仅对比) 每日池口径 A/F/G x K1-4')
print('%-3s %-3s | %14s %12s %9s %8s %7s' % ('K','模式','池收益率%','池净利','池持仓','池回撤%','池calmar'))
for K in [1,2,3,4]:
    for m in ['A','F','G']:
        sd = eval_daily(m, FULL_AUDIT, K)
        print('K=%d %-3s | %13.2f %+11.0f %9.0f %8.2f %7.2f' % (K, m, sd['ret'], sd['net'], sd['peak_capital'], sd['dd_pct'], sd['calmar']))

# ============ 任务2a: 27 toggle 单键边际 (每日池, 空filter base) ============
print()
print('='*120)
print('任务2a: 27 toggle 单键边际 (每日池口径, 空filter base, G模式) — 复核§0.3')
TOGGLES_27 = [k for k in empty_filters() if k not in ['excludeAux','marketTiming','excludeMonth','excludeRatingLow']]
for K in [1,2]:
    s0 = eval_daily('G', None, K)
    print('--- K=%d 每日池 standalone(空filter): 净=%+.0f 收益率=%.2f%% 持仓=%.0f ---' % (K, s0['net'], s0['ret'], s0['peak_capital']))
    rows=[]
    for name in TOGGLES_27:
        F = empty_filters(); F[name]=True
        s = eval_daily('G', F, K)
        rows.append((name, s, s['net']-s0['net'], s['ret']-s0['ret']))
    rows.sort(key=lambda x:-x[2])
    pos = [r for r in rows if r[2]>0]; neg = [r for r in rows if r[2]<0]
    print('  正边际 %d 个:' % len(pos))
    for name,s,dnet,dret in pos:
        print('    %-24s 净=%+.0f(Δ%+.0f) 收益率=%6.2f%%(Δ%+.2f)' % (name, s['net'], dnet, s['ret'], dret))
    print('  负边际 %d 个:' % len(neg))
    for name,s,dnet,dret in neg:
        print('    %-24s 净=%+.0f(Δ%+.0f) 收益率=%6.2f%%(Δ%+.2f)' % (name, s['net'], dnet, s['ret'], dret))

# ============ 任务2b: AI宏7键 vs 4组合全开 边际 (每日池) ============
print()
print('='*120)
print('任务2b: AI宏7键(主基准) vs 4组合全开(对比) — 每日池 K=1/2/3/4')
for K in [1,2,3,4]:
    sd = eval_daily('G', DEFAULT_NEW, K)
    sf = eval_daily('G', FULL_AUDIT, K)
    print('K=%d  AI宏7键:   净=%+.0f 收益率=%.2f%% | 4组合全开: 净=%+.0f(Δ%+.0f) 收益率=%.2f%%(Δ%+.2f)' % (
        K, sd['net'], sd['ret'], sf['net'], sf['net']-sd['net'], sf['ret'], sf['ret']-sd['ret']))

# ============ 任务4: 口径转换对比 ============
print()
print('='*120)
print('任务4: 口径转换对比 — 同配置 每笔1万 vs 每日池 (G模式)')
print('%-3s %-12s | %-13s %-13s %-12s | %-13s %-13s %-12s %s' % ('K','配置','1w收益率%','1w净利','1w持仓','池收益率%','池净利','池持仓','判定'))
for K in [1,2,3,4]:
    for cfgname, F in [('空filter',None),('AI宏7键',DEFAULT_NEW),('4组合全开',FULL_AUDIT)]:
        sp = eval_per1w('G', F, K)
        sd = eval_daily('G', F, K)
        eq = '≈等价' if abs(sp['return_pct_max_holding']-sd['ret'])<0.5 and abs(sp['total_profit']-sd['net'])<1 else ''
        print('K=%d  %-12s | %11.2f %+13.0f %11.0f | %11.2f %+13.0f %11.0f %s' % (
            K, cfgname, sp['return_pct_max_holding'], sp['total_profit'], sp['max_concurrent_capital'], sd['ret'], sd['net'], sd['peak_capital'], eq))
