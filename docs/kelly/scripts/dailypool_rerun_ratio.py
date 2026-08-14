# ============================================================
# 用途: 用途: 每日池 standalone 减亏比值 vs 页面 _kellyFadeFlagGroups 旧 ratio 对比
# 日期/来源: 2026-08-13 / tmp
# 结论: G 模式最优组合 去{greedy15,excludeAuxCross,r7}+a45; A/F 模式保持 AI宏7键; 详见 kelly-dailypool-exhaustive-rerun.md
# 依赖: kelly_combo_advice_analysis.py + kelly_posfilter_backtest.py
# 输入/输出: 读 signal_kelly_trades.json, 输出 /tmp 下各配置统计
# 复现: python3 dailypool_rerun_ratio.py
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
# -*- coding: utf-8 -*-
"""每日池口径 standalone 减亏比值 vs 页面 _kellyFadeFlagGroups 旧 ratio
比值 = 减亏% / 损盈% (与页面同口径)
- 基准: 每日池空filter K (先topK, 空filter金额=10000/当日保留数)
- toggle: 每日池 先toggle过滤再topK K
- 减亏% = (基准总亏损-过滤后总亏损)/基准总亏损
- 损盈% = (基准总盈利-过滤后总盈利)/基准总盈利
"""
import sys, math
from collections import defaultdict
sys.path.insert(0, '/tmp'); sys.path.insert(0, '/Users/linhuichen/code/trade')
from kelly_combo_advice_analysis import (passes_fade, fIdx, empty_filters, BUY_AMOUNT)
from kelly_posfilter_backtest import base_signals, get_by_date, base_key

DAILY=10000.0; MODES=['A','B','C','D','E','F','G','H','I']
QUAL_RANK={'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}
RATING_RANK={'high':0,'mid':1,'low':2,'':3}
def full_sort_key(t):
    sc=t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    return (-sc, RATING_RANK.get(str(t[fIdx['rating']] or ''),3), QUAL_RANK.get(str(t[fIdx['signal']] or ''),9), str(t[fIdx['buy_date']] or ''))
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
            items.append(bp*(amt/BUY_AMOUNT))
    return items
def sums(items):
    P=sum(p for p in items if p>0); L=sum(-p for p in items if p<0)
    return P,L
def ratio_for(mode,F,K):
    base=daily_pool_items(mode,None,K); f=daily_pool_items(mode,F,K)
    Pb,Lb=sums(base); Pf,Lf=sums(f)
    cutL=(Lb-Lf)/Lb*100 if Lb>0 else 0
    cutP=(Pb-Pf)/Pb*100 if Pb>0 else 0
    r=cutL/cutP if cutP>0 else (999.0 if cutL>0 else 0)
    return cutL,cutP,r

TOGGLES=list(empty_filters().keys())
# 旧 ratio 从 lab.js _kellyFadeFlagGroups 摘录
OLD_RATIO = {
 'v4f':999,'v4m':115.56,'v4b':53.96,'v4i':27.04,'v4j':15.55,'v4d':12.20,'v4k':10.11,
 'n1MarTueHigh':10.06,'v4cSimple':7.84,'n2NovSpecialIndustry':6.63,'v4g':6.25,
 'a45NovMidLateSpecial':5.75,'a5NovMidSpecial':5.49,'n3NovSpecialMon':5.24,'janMidRating':4.71,
 'n4AMay':4.67,'janMidSpecial':4.49,'n5MayVlow':4.02,'n6MidMay':3.35,'r8PureNonMay':5.87,
 'r7MayReinforced':4.18,'r10May6NonMay':3.31,'greedy15':3.29,'greedy7':3.15,'greedy10':3.06,
 'excludeMonth':2.11,'excludeAuxCross':2.52,'excludeAux':1.38,'excludeRatingLow':1.14,
 'excludeSpecialBear':2.31,'marketTiming':1.24}
NAMES = {
 'n1MarTueHigh':'n1 3月+周三+高价','n2NovSpecialIndustry':'n2 11月+追+行业','r8PureNonMay':'r8 纯非5月',
 'n3NovSpecialMon':'n3 11月+追+周一','n4AMay':'n4 A股5月','r7MayReinforced':'r7 5月强化+3稳',
 'n5MayVlow':'n5 5月+超低价','n6MidMay':'n6 5月+中评级','r10May6NonMay':'r10 5月+6非5',
 'greedy7':'greedy7','greedy10':'greedy10','greedy15':'greedy15','v4cSimple':'v4c 3月+周三+辅',
 'v4b':'v4b 5月+追+关联','v4d':'v4d 12月+周二+辅','v4j':'v4j 5月+低价+追','v4i':'v4i 5月+追+概念+周一',
 'v4f':'v4f 6月+周三+主+关联','v4g':'v4g 全球Q1+辅+低评','v4m':'v4m 9月+周三+追','v4k':'v4k 1月+主+高价',
 'a5NovMidSpecial':'a5 11月中旬+追','a45NovMidLateSpecial':'a45 11月中下旬+追','janMidRating':'J1 1月中+中评',
 'janMidSpecial':'J2 1月中+追','excludeAuxCross':'auxCross 辅×3/5月','excludeAux':'excludeAux 辅',
 'excludeRatingLow':'excludeRatingLow 低评','excludeMonth':'excludeMonth 3/5月','excludeSpecialBear':'specBear 追×熊',
 'marketTiming':'marketTiming MA60','excludeAux':'excludeAux 辅'}

for scope in ['G','ALL9']:
    print('='*120)
    print('每日池 standalone 减亏比值 (口径: 减亏%%/损盈%%) — 基准 %s' % ('G模式' if scope=='G' else '9模式合计'))
    print('%-28s %8s | %8s %8s %8s %6s | %8s %8s %8s %6s | %s' % ('toggle','旧ratio','K1减亏%','K1损盈%','K1比值','K1净Δ','K2减亏%','K2损盈%','K2比值','K2净Δ','排序变化'))
    rows=[]
    for k in TOGGLES:
        F=empty_filters(); F[k]=True
        if scope=='G':
            c1=ratio_for('G',F,1); c2=ratio_for('G',F,2)
            n1=sum(daily_pool_items('G',None,1))-sum(daily_pool_items('G',F,1))
            n2=sum(daily_pool_items('G',None,2))-sum(daily_pool_items('G',F,2))
        else:
            base1=[daily_pool_items(m,None,1) for m in MODES]; f1=[daily_pool_items(m,F,1) for m in MODES]
            Pb=sum(sums(b)[0] for b in base1); Lb=sum(sums(b)[1] for b in base1)
            Pf=sum(sums(f)[0] for f in f1); Lf=sum(sums(f)[1] for f in f1)
            c1=( (Lb-Lf)/Lb*100 if Lb>0 else 0, (Pb-Pf)/Pb*100 if Pb>0 else 0,
                 ((Lb-Lf)/Lb*100/((Pb-Pf)/Pb*100)) if ((Pb-Pf)/Pb*100)>0 else (999.0 if (Lb-Lf)/Lb*100>0 else 0) )
            n1=sum(sum(b) for b in base1)-sum(sum(f) for f in f1)
            base2=[daily_pool_items(m,None,2) for m in MODES]; f2=[daily_pool_items(m,F,2) for m in MODES]
            Pb=sum(sums(b)[0] for b in base2); Lb=sum(sums(b)[1] for b in base2)
            Pf=sum(sums(f)[0] for f in f2); Lf=sum(sums(f)[1] for f in f2)
            c2=( (Lb-Lf)/Lb*100 if Lb>0 else 0, (Pb-Pf)/Pb*100 if Pb>0 else 0,
                 ((Lb-Lf)/Lb*100/((Pb-Pf)/Pb*100)) if ((Pb-Pf)/Pb*100)>0 else (999.0 if (Lb-Lf)/Lb*100>0 else 0) )
            n2=sum(sum(b) for b in base2)-sum(sum(f) for f in f2)
        old=OLD_RATIO.get(k,0)
        r1=round(c1[2],2) if c1[2]<999 else 999; r2=round(c2[2],2) if c2[2]<999 else 999
        # 排序跳变判断: 旧排序位置 vs K1排序位置 (仅对比有旧ratio的31键)
        rows.append((k, old, c1[0], c1[1], r1, n1, c2[0], c2[1], r2, n2, NAMES.get(k,k)))
    # 排序
    old_sorted=[r[0] for r in sorted(rows, key=lambda x:-x[1])]
    k1_sorted=[r[0] for r in sorted(rows, key=lambda x:-(x[4] if x[4]<900 else 999))] if False else [r[0] for r in sorted(rows, key=lambda x:-x[4])]
    for k,old,c1a,c1b,r1,n1,c2a,c2b,r2,n2,name in sorted(rows, key=lambda x:-(x[4])):
        jump=''
        if old>0 and r1<900:
            pi=old_sorted.index(k); pj=k1_sorted.index(k)
            if abs(pi-pj)>=5: jump='↑↓位次%02d→%02d'%(pi+1,pj+1)
        print('%-28s %8s | %8.2f %8.2f %8s %+8.0f | %8.2f %8.2f %8s %+8.0f | %s' % (
            name, old, c1a, c1b, r1, n1, c2a, c2b, r2, n2, jump))
