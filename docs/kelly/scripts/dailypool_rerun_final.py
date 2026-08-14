# ============================================================
# 用途: 用途: 每日池最优配置矩阵 AI宏7键±greedy15/exclAuxCross±a45/a5, A/F/G x K1-4
# 日期/来源: 2026-08-13 / tmp
# 结论: G 模式最优组合 去{greedy15,excludeAuxCross,r7}+a45; A/F 模式保持 AI宏7键; 详见 kelly-dailypool-exhaustive-rerun.md
# 依赖: kelly_combo_advice_analysis.py + kelly_posfilter_backtest.py
# 输入/输出: 读 signal_kelly_trades.json, 输出 /tmp 下各配置统计
# 复现: python3 dailypool_rerun_final.py
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
"""最终最优配置矩阵: AI宏7键 ± greedy15/exclAuxCross ± a45/a5, A/F/G x K1-4 (每日池)"""
import sys, math
from collections import defaultdict
sys.path.insert(0, '/tmp'); sys.path.insert(0, '/Users/linhuichen/code/trade')
from kelly_combo_advice_analysis import (passes_fade, fIdx, empty_filters, BUY_AMOUNT)
from kelly_posfilter_backtest import base_signals, get_by_date, base_key

DAILY = 10000.0
QUAL_RANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}
RATING_RANK = {'high':0,'mid':1,'low':2,'':3}
def full_sort_key(t):
    sc = t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    return (-sc, RATING_RANK.get(str(t[fIdx['rating']] or ''),3), QUAL_RANK.get(str(t[fIdx['signal']] or ''),9), str(t[fIdx['buy_date']] or ''))

DEFAULT_NEW = {k: True for k in ['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial','r7MayReinforced','excludeAuxCross','greedy15']}
FULL_AUDIT = {k: True for k in ['excludeSpecialBear','n2NovSpecialIndustry','janMidRating','janMidSpecial','n3NovSpecialMon','v4d','r8PureNonMay','greedy15']}

def _peak_capital(items):
    SENTINEL="99999999"; ev=defaultdict(int)
    for t in items: ev[t[2] or SENTINEL]+=t[5]; ev[t[3] or SENTINEL]-=t[5]
    peak=0; cur=0
    for dt in sorted(ev): cur+=ev[dt]; peak=max(peak,cur)
    return peak
def _years_from(dates):
    from datetime import datetime
    try:
        dd1=datetime.strptime(min(dates),"%Y%m%d"); dd2=datetime.strptime(max(dates),"%Y%m%d")
        return max(int((dd2-dd1).total_seconds()/86400)/365.25, 1/365.25)
    except: return 1.0
def compute_scaled(items):
    n=len(items)
    if n==0: return {'n':0,'net':0,'ret':0,'peak':0,'dd':0}
    wc=len([t for t in items if t[0]>0]); lc=n-wc
    winRate=wc/n
    avgWin=sum(t[1] for t in items if t[0]>0)/wc if wc else 0
    avgLossAbs=abs(sum(t[1] for t in items if t[0]<=0)/lc) if lc else 0
    pl=avgWin/avgLossAbs if (lc>0 and avgLossAbs>0) else (999.0 if (wc>0 and lc==0) else None)
    totInv=sum(t[5] for t in items); net=sum(t[0] for t in items)
    peak=_peak_capital(items); ret=net/peak*100 if peak>0 else 0
    yrs=_years_from([t[2] for t in items])
    ann=(math.pow(1+ret/100,1/yrs)-1)*100 if yrs>0 and ret>-100 else 0
    srt=sorted(items,key=lambda x:x[3] or "99999999"); cum=0; pc=0; mdd=0
    for t in srt: cum+=t[0]; pc=max(pc,cum); mdd=max(mdd,pc-cum)
    dd=mdd/totInv*100 if totInv>0 else 0
    return {'n':n,'net':net,'ret':round(ret,2),'peak':peak,'dd':round(dd,2),'calmar':round(ann/dd,2) if dd>0 else 0,'win':winRate*100,'pl':pl}
def daily_pool_items(mode,F,K):
    bd=get_by_date(mode); day_pool={}
    if F:
        for sd,rows in bd.items():
            fr=[t for t in rows if passes_fade(t,F)]
            if fr: day_pool[sd]=fr
    else:
        day_pool={sd:rows for sd,rows in bd.items() if rows}
    kept=set(); dc={}
    for sd,rows in day_pool.items():
        srt=sorted(rows,key=full_sort_key)[:K] if K and K>0 else rows
        dc[sd]=len(srt)
        for t in srt: kept.add(base_key(t))
    items=[]
    for sd,rows in day_pool.items():
        nn=dc.get(sd,0)
        if nn==0: continue
        amt=DAILY/nn
        for t in rows:
            if base_key(t) not in kept: continue
            bp=t[fIdx['profit']] or 0; rp=t[fIdx['return_pct']] or 0
            items.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items
def ev(m,F,K): return compute_scaled(daily_pool_items(m,F,K))
def mk(adds=(),removes=()):
    F=empty_filters()
    for k in DEFAULT_NEW: F[k]=True
    for k in adds: F[k]=True
    for k in removes: F[k]=False
    return F

CFGS = [
    ('AI宏7键(现状默认)', DEFAULT_NEW),
    ('AI7去greedy15', mk(removes=('greedy15',))),
    ('AI7去g15去auxX', mk(removes=('greedy15','excludeAuxCross'))),
    ('AI7去g15+a45', mk(adds=('a45NovMidLateSpecial',), removes=('greedy15',))),
    ('AI7去g15+a45+a5', mk(adds=('a45NovMidLateSpecial','a5NovMidSpecial'), removes=('greedy15',))),
    ('4组合全开(对比)', FULL_AUDIT),
]
print('最终最优配置矩阵 (每日池口径, A/F/G x K1-4)')
print('%-24s %-3s | %9s %11s %8s %6s %6s' % ('配置','K','模式','收益率%','净利','持仓','回撤%'))
for K in [1,2,3,4]:
    for m in ['A','F','G']:
        for cname,F in CFGS:
            s=ev(m,F,K)
            print('%-24s %-3s %-3s | %8.2f %+11.0f %8.0f %6.2f' % (cname, K, m, s['ret'], s['net'], s['peak'], s['dd']))
        print()
