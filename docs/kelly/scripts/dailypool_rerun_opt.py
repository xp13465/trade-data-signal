# ============================================================
# 用途: 用途: 每日池最优组合穷举(LOO+单加+双加)+按年分解+B模式验证
# 日期/来源: 2026-08-13 / tmp
# 结论: G 模式最优组合 去{greedy15,excludeAuxCross,r7}+a45; A/F 模式保持 AI宏7键; 详见 kelly-dailypool-exhaustive-rerun.md
# 依赖: kelly_combo_advice_analysis.py + kelly_posfilter_backtest.py
# 输入/输出: 读 signal_kelly_trades.json, 输出 /tmp 下各配置统计
# 复现: python3 dailypool_rerun_opt.py
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
"""任务3: 最优组合穷举(LOO+单加+双加) | 任务5: 按年分解 | 任务6: B模式验证
主基准 = AI宏7键默认推荐, 每日池口径
"""
import sys, math
from collections import defaultdict
sys.path.insert(0, '/tmp'); sys.path.insert(0, '/Users/linhuichen/code/trade')
from kelly_combo_advice_analysis import (passes_fade, fIdx, empty_filters, BUY_AMOUNT, to_row)
from kelly_posfilter_backtest import base_signals, get_by_date, base_key

DAILY = 10000.0
QUAL_RANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}
RATING_RANK = {'high':0,'mid':1,'low':2,'':3}
def full_sort_key(t):
    sc = t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    return (-sc, RATING_RANK.get(str(t[fIdx['rating']] or ''),3), QUAL_RANK.get(str(t[fIdx['signal']] or ''),9), str(t[fIdx['buy_date']] or ''))

DEFAULT_NEW = {k: True for k in ['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial',
                                 'r7MayReinforced','excludeAuxCross','greedy15']}
FULL_AUDIT = {k: True for k in ['excludeSpecialBear','n2NovSpecialIndustry','janMidRating','janMidSpecial',
                                'n3NovSpecialMon','v4d','r8PureNonMay','greedy15']}

def _date_diff_days(d1, d2):
    from datetime import datetime
    try:
        dd1 = datetime.strptime(d1, "%Y%m%d"); dd2 = datetime.strptime(d2, "%Y%m%d")
        return max(int((dd2 - dd1).total_seconds() / 86400), 0)
    except (ValueError, TypeError): return 0
def _years_from(dates):
    if not dates: return 1.0
    days = _date_diff_days(min(dates), max(dates))
    return max(days / 365.25, 1.0 / 365.25)
def _peak_capital(items):
    SENTINEL = "99999999"; ev = defaultdict(int)
    for t in items:
        ev[t[2] or SENTINEL] += t[5]; ev[t[3] or SENTINEL] -= t[5]
    peak=0; cur=0
    for dt in sorted(ev): cur += ev[dt]; peak = max(peak, cur)
    return peak
def compute_scaled(items):
    n = len(items)
    if n == 0: return {'n':0,'net':0,'ret':0,'peak_capital':0,'dd_pct':0,'calmar':0}
    wins=[t for t in items if t[0]>0]; losses=[t for t in items if t[0]<=0]
    wc=len(wins); lc=len(losses); winRate=wc/n
    avgWin=sum(t[1] for t in wins)/wc if wc else 0
    avgLossAbs=abs(sum(t[1] for t in losses)/lc) if lc else 0
    totalInvest=sum(t[5] for t in items); totalProfit=sum(t[0] for t in items)
    peak=_peak_capital(items); ret=totalProfit/peak*100 if peak>0 else 0
    years=_years_from([t[2] for t in items])
    annualized=(math.pow(1+ret/100,1/years)-1)*100 if years>0 and ret>-100 else 0
    srt=sorted(items,key=lambda x:x[3] or "99999999"); cum=0; peakc=0; maxDd=0
    for t in srt: cum+=t[0]; peakc=max(peakc,cum); maxDd=max(maxDd,peakc-cum)
    dd_pct=maxDd/totalInvest*100 if totalInvest>0 else 0
    calmar=round(annualized/dd_pct,2) if dd_pct and dd_pct>0 else 0
    return {'n':n,'net':totalProfit,'ret':round(ret,2),'peak_capital':peak,'dd_pct':round(dd_pct,2),'calmar':calmar}

def daily_pool_items(mode, F, K):
    bd = get_by_date(mode)
    day_pool = {}
    if F:
        for sd, rows in bd.items():
            fr = [t for t in rows if passes_fade(t, F)]
            if fr: day_pool[sd] = fr
    else:
        day_pool = {sd: rows for sd, rows in bd.items() if rows}
    kept_keys=set(); day_counts={}
    for sd, rows in day_pool.items():
        srt = sorted(rows, key=full_sort_key)[:K] if K and K>0 else rows
        day_counts[sd]=len(srt)
        for t in srt: kept_keys.add(base_key(t))
    items=[]
    for sd, rows in day_pool.items():
        n=day_counts.get(sd,0)
        if n==0: continue
        amt=DAILY/n
        for t in rows:
            if base_key(t) not in kept_keys: continue
            bp=t[fIdx['profit']] or 0; rp=t[fIdx['return_pct']] or 0
            items.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items
def eval_daily(mode, F, K): return compute_scaled(daily_pool_items(mode, F, K))

def mergeF(baseF, adds=(), removes=()):
    F = empty_filters()
    for k in baseF: F[k] = True
    for k in adds: F[k] = True
    for k in removes: F[k] = False
    return F

TOGGLES_27 = [k for k in empty_filters() if k not in ['excludeAux','marketTiming','excludeMonth','excludeRatingLow']]
AI_KEYS = list(DEFAULT_NEW.keys())
CAND_ADD = [k for k in TOGGLES_27 if k not in AI_KEYS]

# ============ 任务3: G模式寻优 (AI宏7键 LOO + 单加 + 双加) ============
print('='*120)
print('任务3a: G模式 AI宏7键 寻优 — LOO(去1) + 单加 + 双加 (每日池)')
for K in [1,2,3,4]:
    s_base = eval_daily('G', DEFAULT_NEW, K)
    print('--- K=%d AI宏7键基线: 净=%+.0f 收益率=%.2f%% 持仓=%.0f ---' % (K, s_base['net'], s_base['ret'], s_base['peak_capital']))
    # LOO
    loo = []
    for k in AI_KEYS:
        F = mergeF(DEFAULT_NEW, removes=(k,))
        s = eval_daily('G', F, K)
        loo.append((k, s, s['net']-s_base['net'], s['ret']-s_base['ret']))
    loo.sort(key=lambda x:-x[3])
    print('  LOO(去1) 按收益率Δ排序:')
    for k,s,dnet,dret in loo:
        print('    去%-24s 净=%+.0f(Δ%+.0f) 收益率=%6.2f%%(Δ%+.2f)' % (k, s['net'], dnet, s['ret'], dret))
    # 单加
    add1 = []
    for k in CAND_ADD:
        F = mergeF(DEFAULT_NEW, adds=(k,))
        s = eval_daily('G', F, K)
        add1.append((k, s, s['net']-s_base['net'], s['ret']-s_base['ret']))
    add1.sort(key=lambda x:-x[3])
    print('  单加(加1) 按收益率Δ排序 top5:')
    for k,s,dnet,dret in add1[:5]:
        print('    +%-24s 净=%+.0f(Δ%+.0f) 收益率=%6.2f%%(Δ%+.2f)' % (k, s['net'], dnet, s['ret'], dret))
    # 单加 top5 双加组合
    top5_add = [r[0] for r in add1[:5]]
    print('  双加(top5 两两):')
    best = (None, s_base, 0)
    for i in range(len(top5_add)):
        for j in range(i+1, len(top5_add)):
            F = mergeF(DEFAULT_NEW, adds=(top5_add[i], top5_add[j]))
            s = eval_daily('G', F, K)
            if s['ret'] > best[1]['ret']: best = (top5_add[i]+'+'+top5_add[j], s, s['ret']-s_base['ret'])
    if best[0]:
        print('    最优双加: +%s 净=%+.0f 收益率=%.2f%%(Δ%+.2f)' % (best[0], best[1]['net'], best[1]['ret'], best[2]))
    else:
        print('    无双加优于基线')

# ============ 任务3b: A/F模式 最优配置验证 ============
print()
print('='*120)
print('任务3b: A/F 模式 — AI宏7键 vs 4组合全开 vs AI宏7键+正边际 (每日池)')
print('%-3s %-3s | %-22s %12s %9s %9s' % ('K','模式','配置','净利','收益率%','持仓'))
for K in [1,2,3,4]:
    for m in ['A','F']:
        for cname, F in [('AI宏7键',DEFAULT_NEW),('4组合全开',FULL_AUDIT),('AI7+a45',mergeF(DEFAULT_NEW,adds=('a45NovMidLateSpecial',)))]:
            s = eval_daily(m, F, K)
            print('K=%d %-3s | %-22s %+11.0f %9.2f %9.0f' % (K, m, cname, s['net'], s['ret'], s['peak_capital']))
        print()

# ============ 任务5: 按年分解 (每日池, AI宏7键 G模式) ============
print()
print('='*120)
print('任务5: 按年分解 (每日池口径, AI宏7键 G模式 K1-4 vs 每笔1万对照)')
for K in [1,2,3,4]:
    items = daily_pool_items('G', DEFAULT_NEW, K)
    by = defaultdict(list)
    for it in items: by[it[2][:4]].append(it)
    print('--- K=%d AI宏7键 每日池 按年 ---' % K)
    yrs = sorted(by.keys())
    for y in yrs:
        s = compute_scaled(by[y])
        print('  %s: 净=%+.0f 收益率=%6.2f%% 持仓=%9.0f' % (y, s['net'], s['ret'], s['peak_capital']))

# ============ 任务6: B模式验证 ============
print()
print('='*120)
print('任务6: B模式(3%止盈) 每日池口径 全负复核 — 空filter vs AI宏7键 vs 4组合全开')
print('%-3s %-14s | %12s %9s %9s' % ('K','配置','净利','收益率%','持仓'))
for K in [0,1,2,3,4]:
    for cname, F in [('空filter',None),('AI宏7键',DEFAULT_NEW),('4组合全开',FULL_AUDIT)]:
        s = eval_daily('B', F, K)
        print('K=%s %-14s | %+11.0f %9.2f %9.0f' % (str(K) if K else '全部', cname, s['net'], s['ret'], s['peak_capital']))
    print()
