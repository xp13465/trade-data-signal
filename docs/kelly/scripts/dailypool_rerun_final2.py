# ============================================================
# 用途: 用途: 每日池最优穷举(演进版 final2, 与报告 kelly-dailypool-exhaustive-rerun.md §0.2 对应)
# 日期/来源: 2026-08-13 / tmp
# 结论: G 模式最优组合 去{greedy15,excludeAuxCross,r7}+a45; A/F 模式保持 AI宏7键; 详见 kelly-dailypool-exhaustive-rerun.md
# 依赖: kelly_combo_advice_analysis.py + kelly_posfilter_backtest.py
# 输入/输出: 读 signal_kelly_trades.json, 输出 /tmp 下各配置统计
# 复现: python3 dailypool_rerun_final2.py
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
import sys, math
from collections import defaultdict
sys.path.insert(0, '/tmp'); sys.path.insert(0, '/Users/linhuichen/code/trade')
from kelly_combo_advice_analysis import (passes_fade, fIdx, empty_filters, BUY_AMOUNT)
from kelly_posfilter_backtest import base_signals, get_by_date, base_key
DAILY=10000.0
QUAL_RANK={'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}
RATING_RANK={'high':0,'mid':1,'low':2,'':3}
def full_sort_key(t):
    sc=t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    return (-sc, RATING_RANK.get(str(t[fIdx['rating']] or ''),3), QUAL_RANK.get(str(t[fIdx['signal']] or ''),9), str(t[fIdx['buy_date']] or ''))
DEFAULT_NEW={k:True for k in ['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial','r7MayReinforced','excludeAuxCross','greedy15']}
def _peak_capital(items):
    SENTINEL="99999999"; ev=defaultdict(int)
    for t in items: ev[t[2] or SENTINEL]+=t[5]; ev[t[3] or SENTINEL]-=t[5]
    peak=0; cur=0
    for dt in sorted(ev): cur+=ev[dt]; peak=max(peak,cur)
    return peak
def _years_from(dates):
    from datetime import datetime
    try:
        d1=datetime.strptime(min(dates),"%Y%m%d"); d2=datetime.strptime(max(dates),"%Y%m%d")
        return max(int((d2-d1).total_seconds()/86400)/365.25, 1/365.25)
    except: return 1.0
def compute_scaled(items):
    n=len(items)
    if n==0: return {'n':0,'net':0,'ret':0,'peak':0,'dd':0}
    wc=len([t for t in items if t[0]>0]); lc=n-wc
    winRate=wc/n
    avgWin=sum(t[1] for t in items if t[0]>0)/wc if wc else 0
    avgLossAbs=abs(sum(t[1] for t in items if t[0]<=0)/lc) if lc else 0
    totInv=sum(t[5] for t in items); net=sum(t[0] for t in items)
    peak=_peak_capital(items); ret=net/peak*100 if peak>0 else 0
    yrs=_years_from([t[2] for t in items])
    ann=(math.pow(1+ret/100,1/yrs)-1)*100 if yrs>0 and ret>-100 else 0
    srt=sorted(items,key=lambda x:x[3] or "99999999"); cum=0; pc=0; mdd=0
    for t in srt: cum+=t[0]; pc=max(pc,cum); mdd=max(mdd,pc-cum)
    dd=mdd/totInv*100 if totInv>0 else 0
    return {'n':n,'net':net,'ret':round(ret,2),'peak':peak,'dd':round(dd,2),'calmar':round(ann/dd,2) if dd>0 else 0}
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
def mk(removes=(),adds=()):
    F=empty_filters()
    for k in DEFAULT_NEW: F[k]=True
    for k in removes: F[k]=False
    for k in adds: F[k]=True
    return F
REMS=['greedy15','excludeAuxCross','r7MayReinforced']
ADDS=['a45NovMidLateSpecial','a5NovMidSpecial']
for K in [1,2,3,4]:
    best_ret=None; best_net=None
    for rmask in range(8):
        rem=[REMS[i] for i in range(3) if rmask>>i & 1]
        for amask in range(4):
            add=[ADDS[i] for i in range(2) if amask>>i & 1]
            F=mk(removes=tuple(rem), adds=tuple(add))
            s=ev('G',F,K)
            tag='AI7'+(''.join('去'+r for r in rem))+(''.join('+'+a for a in add) if add else '')
            if best_ret is None or s['ret']>best_ret[1]['ret']: best_ret=(tag,s)
            if best_net is None or s['net']>best_net[1]['net']: best_net=(tag,s)
    print('K=%d 收益率最优: %-34s 净=%+.0f 收益率=%.2f%%' % (K, best_ret[0], best_ret[1]['net'], best_ret[1]['ret']))
    print('   净利最优:   %-34s 净=%+.0f 收益率=%.2f%%' % (best_net[0], best_net[1]['net'], best_net[1]['ret']))
print()
print('G模式 K=1 全32配置 top10 (按收益率)')
cfgs=[]
for rmask in range(8):
    rem=[REMS[i] for i in range(3) if rmask>>i & 1]
    for amask in range(4):
        add=[ADDS[i] for i in range(2) if amask>>i & 1]
        F=mk(removes=tuple(rem), adds=tuple(add))
        s=ev('G',F,1)
        tag='AI7'+(''.join('去'+r for r in rem))+(''.join('+'+a for a in add) if add else '')
        cfgs.append((tag,s))
cfgs.sort(key=lambda x:-x[1]['ret'])
for tag,s in cfgs[:10]:
    print('%-36s 净=%+.0f 收益率=%.2f%%' % (tag, s['net'], s['ret']))
print()
print('A/F 模式 greedy15 贡献确认 (AI宏7键 vs 去greedy15)')
for K in [1,2,3,4]:
    for m in ['A','F']:
        s1=ev(m,DEFAULT_NEW,K); s2=ev(m,mk(removes=('greedy15',)),K)
        print('K=%d %s: AI7=%.2f%%(净%+.0f) | 去g15=%.2f%%(净%+.0f) Δret=%+.2fpt' % (
            K,m,s1['ret'],s1['net'],s2['ret'],s2['net'],s2['ret']-s1['ret']))
