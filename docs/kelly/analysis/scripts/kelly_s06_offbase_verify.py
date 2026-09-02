# -*- coding: utf-8 -*-
# 复现 lab.js 高评级信号(rating_high)卡片前端真实口径
# 管线: S06 per-date 基座(a9/new15) -> _kellyPassesFadeFilters 逐键判定(legacy specs + T1 spec)
#        -> basePool(rating三区×10模式, passFn过滤, baseKey去重) -> K=1 kept(每日排序取前1)
#        -> 每笔金额=10000/当日保留数(每日资金池等分) -> 费率重算(etf_main) -> total_profit
#
# [2026-09-02 归档] 来源: reviewer 兜底态验证脚本(原 /tmp/kelly_s06_offbase_verify.py, 与
#   trade-method-final-repro.mjs 配套交叉验证)。用途: 验证「S06 覆盖期外=默认兜底态(off_base)」修复下
#   K=1 全史各模式净利方向(Δ 为正 PASS)与 off_base 字段实际读取。
#   注意: 本脚本为「第二份实现」(Python 复刻前端), 硬编码 A9/NEW15/NEW14 键集 + 读主树快照;
#   ⚠️ 权威口径数字以 trade-method-final-repro.mjs(切片 common.js/lab.js 单源, 读快照 off_base 字段)为准,
#   本脚本只作方向/量级交叉验证, 不作报告权威数字来源。
# 复现命令: python3 docs/kelly/analysis/scripts/kelly_s06_offbase_verify.py
# 依赖: static-site/data/signal_kelly_trades.json + signal_kelly_backtest.json + kelly_loss_features.json + kelly_mode_s06_state.json
import json, math

ROOT='/Users/linhuichen/code/trade/static-site/data/'
TD=json.load(open(ROOT+'signal_kelly_trades.json'))
BT=json.load(open(ROOT+'signal_kelly_backtest.json'))
FEAT=json.load(open(ROOT+'kelly_loss_features.json'))
S06=None; s06byDate={}
def set_s06(path):
    global S06, s06byDate
    S06=json.load(open(path))
    s06byDate={}
    for r in S06['daily']:
        s06byDate[str(r['date'])]=r.get('effective_mode')

fields=TD['fields']; fIdx={f:i for i,f in enumerate(fields)}
BUY_AMT=TD['buy_amount'] or 10000
perio=BT['config']['periods']; cutoffs=BT['config']['period_cutoffs']
sellModes=BT['config']['sell_modes']
quads=TD['quadrants']

# ---- S06 快照: date->effective_mode(set_s06 注入) ----
def s06base(dateStr):
    return s06byDate.get(str(dateStr))

# ---- 58 键全集 + 预设键集 ----
FRONT=['excludeAux','marketTiming','excludeMonth','excludeRatingLow','excludeAuxCross',
 'excludeSpecialBear','legacyMa60Special','declinePhaseSpecial','excludeSpecialBearCyb','bullAuxBackupStop']
GATE=['n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay',
 'r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay',
 'v4cSimple','v4b','greedy7','v4d','v4j','v4i','greedy10','v4f','v4g','v4m','v4k','greedy15',
 'a5NovMidSpecial','a45NovMidLateSpecial','janMidRating','janMidSpecial','k2c5HkChase','k3ConceptBuy']
T1KEYS=['r2gLowRatingQ3','n1NorthOutflow','t1LowTurnSpecial','d1LowDivYield','q1QvixLowPct',
 'h1VolChgHighA','m1MarginDownBull','d2LowDivBull','p1LowDivBackup','v1HighVol20',
 's1SentALow','r1VolRatioLow','r2bSpecialGlobal','n2NorthOutConcept','v2Vol20Gt25',
 's2SentHs300Low','w1BackupDecline','a1BullAllStop','v3Vol20LowPct','ad1AdlineHot','excludeTierNone']
ALLKEYS=FRONT+GATE+T1KEYS
A9KEYS=['excludeSpecialBear','n2NovSpecialIndustry','janMidRating','janMidSpecial','k2c5HkChase','r7MayReinforced','excludeAuxCross','greedy15','bullAuxBackupStop','t1LowTurnSpecial','q1QvixLowPct','m1MarginDownBull','v1HighVol20','r1VolRatioLow','k3ConceptBuy','r2bSpecialGlobal','r2gLowRatingQ3']
NEW15KEYS=['r10May6NonMay','greedy15','janMidSpecial','k2c5HkChase','k3ConceptBuy','declinePhaseSpecial','n1NorthOutflow','t1LowTurnSpecial','d1LowDivYield','q1QvixLowPct','h1VolChgHighA','m1MarginDownBull','p1LowDivBackup','r2bSpecialGlobal','excludeTierNone']
NEW14KEYS=[k for k in NEW15KEYS if k!='excludeTierNone']  # new14 = NEW15 去 excludeTierNone(与 common.js _KELLY_FADE_MODE_PRESETS new14 键集逐位一致)
def filtersForBase(base):
    f={k:False for k in ALLKEYS}
    keys=A9KEYS if base=='a9' else NEW14KEYS if base=='new14' else NEW15KEYS if base=='new15' else []
    for k in keys: f[k]=True
    return f

# ---- legacy specs(common.js _KELLY_FADE_LEGACY_SPECS) ----
import copy
LEGACY={
 'excludeAux':{'gate':0,'any':[{'sig':'buy_aux'}]},
 'marketTiming':{'gate':0,'any':[{'mstateNotTrue':1}]},
 'excludeMonth':{'gate':0,'any':[{'mmIn':('03','05')}]},
 'excludeRatingLow':{'gate':0,'any':[{'ratingIsLow':1}]},
 'excludeAuxCross':{'gate':0,'any':[{'sig':'buy_aux','mmIn':('03','05')}]},
 'excludeSpecialBear':{'gate':0,'any':[{'sig':'buy_special','tierIn':('熊市·主跌','下降期')}]},
 'legacyMa60Special':{'gate':0,'any':[{'sig':'buy_special','mstateFalse':1}]},
 'declinePhaseSpecial':{'gate':0,'any':[{'sig':'buy_special','tierAll':'下降期'}]},
 'excludeSpecialBearCyb':{'gate':0,'any':[{'sig':'buy_special','tierCybIn':('熊市·主跌','下降期')}]},
 'bullAuxBackupStop':{'gate':0,'any':[{'sigIn':('buy_aux','buy_backup'),'tier':'牛市·主升'}]},
 'n1MarTueHigh':{'gate':1,'any':[{'mm':'03','wd':2,'bpb':'high'}]},
 'n2NovSpecialIndustry':{'gate':1,'any':[{'sig':'buy_special','mm':'11','mkt':'industry'}]},
 'r8PureNonMay':{'gate':1,'any':[{'mm':'03','wd':2,'bpb':'high'},{'sig':'buy_special','mm':'11','mkt':'industry'},{'sig':'buy_special','mm':'11','wd':0}]},
 'n3NovSpecialMon':{'gate':1,'any':[{'sig':'buy_special','mm':'11','wd':0}]},
 'n4AMay':{'gate':1,'any':[{'mkt':'a','mm':'05'}]},
 'r7MayReinforced':{'gate':1,'any':[{'mkt':'a','mm':'05'},{'rat':'mid','mm':'05'},{'mm':'05','bpb':'vlow'},{'mm':'03','wd':2,'bpb':'high'},{'sig':'buy_special','mm':'11','mkt':'industry'},{'sig':'buy_special','mm':'11','wd':0}]},
 'n5MayVlow':{'gate':1,'any':[{'mm':'05','bpb':'vlow'}]},
 'n6MidMay':{'gate':1,'any':[{'rat':'mid','mm':'05'}]},
 'r10May6NonMay':{'gate':1,'any':[{'mm':'05'},{'mm':'03','wd':2,'bpb':'high'},{'sig':'buy_special','mm':'11','mkt':'industry'},{'sig':'buy_special','mm':'11','wd':0},{'sig':'buy_special','mm':'11','bpb':'low'},{'sig':'buy_special','mm':'03','mkt':'industry'},{'mm':'03','wd':2,'sig':'buy_aux'}]},
 'v4cSimple':{'gate':1,'any':[{'mm':'03','wd':2,'sig':'buy_aux'}]},
 'v4b':{'gate':1,'any':[{'mkt':'a','mm':'05','sig':'buy_special','etf':'related'}]},
 'greedy7':{'gate':1,'any':[{'sig':'buy_special','mm':'05'},{'sig':'buy_special','mm':'11','mkt':'concept'},{'sig':'buy_special','mm':'03'},{'sig':'buy_aux','mm':'01'},{'q':2,'bpb':'vlow','sig':'buy_aux','mkt':'concept'},{'sig':'buy','mm':'01'},{'mm':'03','wd':2,'mkt':'concept','rat':'low'}]},
 'v4d':{'gate':1,'any':[{'mm':'12','wd':1,'sig':'buy_aux','tsMax':50}]},
 'v4j':{'gate':1,'any':[{'mm':'05','bpb':'vlow','sig':'buy_special'}]},
 'v4i':{'gate':1,'any':[{'sig':'buy_special','mm':'05','mkt':'concept','wd':0}]},
 'greedy10':{'gate':1,'any':[{'sig':'buy_special','mm':'05'},{'sig':'buy_special','mm':'11','mkt':'concept'},{'sig':'buy_special','mm':'03'},{'sig':'buy_aux','mm':'01'},{'q':2,'bpb':'vlow','sig':'buy_aux','mkt':'concept'},{'sig':'buy','mm':'01'},{'mm':'03','wd':2,'mkt':'concept','rat':'low'},{'sig':'buy_aux','mm':'12','tsMax':50},{'mm':'06','bpb':'vlow','rat':'low'},{'sig':'buy_aux','mm':'05'}]},
 'v4f':{'gate':1,'any':[{'sig':'buy','mm':'06','wd':2,'etf':'related'}]},
 'v4g':{'gate':1,'any':[{'mkt':'global','q':1,'sig':'buy_aux','rat':'low'}]},
 'v4m':{'gate':1,'any':[{'sig':'buy_special','mm':'09','wd':2}]},
 'v4k':{'gate':1,'any':[{'sig':'buy','mm':'01','bpb':'high'}]},
 'greedy15':{'gate':1,'any':[{'sig':'buy_special','mm':'05'},{'sig':'buy_special','mm':'11','mkt':'concept'},{'sig':'buy_special','mm':'03'},{'sig':'buy_aux','mm':'01'},{'q':2,'bpb':'vlow','sig':'buy_aux','mkt':'concept'},{'sig':'buy','mm':'01'},{'mm':'03','wd':2,'mkt':'concept','rat':'low'},{'sig':'buy_aux','mm':'12','tsMax':50},{'mm':'06','bpb':'vlow','rat':'low'},{'sig':'buy_aux','mm':'05'},{'sig':'buy_special','mm':'11','mkt':'industry'},{'mm':'04','wd':1,'mkt':'concept','tsMax':50},{'mkt':'global','q':1,'sig':'buy_aux','rat':'low'},{'mm':'01','bpb':'low','sig':'buy_special','mkt':'concept'},{'sig':'buy_special','mm':'09','wd':2}]},
 'a5NovMidSpecial':{'gate':1,'any':[{'sig':'buy_special','mm':'11','ddMin':11,'ddMax':20}]},
 'a45NovMidLateSpecial':{'gate':1,'any':[{'sig':'buy_special','mm':'11','ddMin':11}]},
 'janMidRating':{'gate':1,'any':[{'mm':'01','ddMin':11,'ddMax':20,'rat':'mid'}]},
 'janMidSpecial':{'gate':1,'any':[{'sig':'buy_special','mm':'01','ddMin':11,'ddMax':20}]},
 'k2c5HkChase':{'gate':1,'any':[{'sigIn':('buy_special','buy_backup'),'mkt':'hk'}]},
 'k3ConceptBuy':{'gate':1,'any':[{'sig':'buy','mkt':'concept'}]},
}
def specHit(key, c):
    sp=LEGACY.get(key)
    if not sp: return False
    for p in sp['any']:
        ok=True
        for cond_key,val in p.items():
            if cond_key=='sig' and c['sig']!=val: ok=False; break
            if cond_key=='sigIn' and c['sig'] not in val: ok=False; break
            if cond_key=='mm' and c['mm']!=val: ok=False; break
            if cond_key=='mmIn' and c['mm'] not in val: ok=False; break
            if cond_key=='ddMin' and not (c['dd']>=val): ok=False; break
            if cond_key=='ddMax' and not (c['dd']<=val): ok=False; break
            if cond_key=='wd' and c['wd']!=val: ok=False; break
            if cond_key=='bpb' and c['bpb']!=val: ok=False; break
            if cond_key=='q' and c['q']!=val: ok=False; break
            if cond_key=='tsMax' and not (float(c['ts'])<val): ok=False; break
            if cond_key=='mkt' and c['mktD']!=val: ok=False; break
            if cond_key=='etf' and c['etfD']!=val: ok=False; break
            if cond_key=='rat' and c['ratD']!=val: ok=False; break
            if cond_key=='tier' and c.get('tier','')!=val: ok=False; break
            if cond_key=='tierIn' and c.get('tier','') not in val: ok=False; break
            if cond_key=='tierAll' and c.get('tierAll','')!=val: ok=False; break
            if cond_key=='tierCybIn' and c.get('tierCyb','') not in val: ok=False; break
            if cond_key=='ratingIsLow' and c['rating']!='low': ok=False; break
            if cond_key=='mstateNotTrue' and c['mstate'] is True: ok=False; break
            if cond_key=='mstateFalse' and c['mstate'] is not False: ok=False; break
        if ok: return True
    return False

# ---- month mask(lab.js _kellyMonthMask) ----
MMASK={
 'a5NovMidSpecial':1<<10,'a45NovMidLateSpecial':1<<10,'n1MarTueHigh':1<<2,'n2NovSpecialIndustry':1<<10,
 'r8PureNonMay':(1<<2)|(1<<10),'n3NovSpecialMon':1<<10,'n4AMay':1<<4,'r7MayReinforced':(1<<4)|(1<<2)|(1<<10),
 'n5MayVlow':1<<4,'n6MidMay':1<<4,'r10May6NonMay':(1<<4)|(1<<2)|(1<<10),
 'v4cSimple':1<<2,'v4b':1<<4,'greedy7':(1<<4)|(1<<10)|(1<<2)|(1<<0)|(1<<3)|(1<<5),
 'v4d':1<<11,'v4j':1<<4,'v4i':1<<4,'greedy10':(1<<4)|(1<<10)|(1<<2)|(1<<0)|(1<<3)|(1<<5)|(1<<11),
 'v4f':1<<5,'v4g':(1<<0)|(1<<1)|(1<<2),'v4m':1<<8,'v4k':1<<0,
 'greedy15':(1<<0)|(1<<1)|(1<<2)|(1<<3)|(1<<4)|(1<<5)|(1<<8)|(1<<10)|(1<<11),
 'janMidRating':1<<0,'janMidSpecial':1<<0,'k2c5HkChase':0x1FFF
}

# ---- _kellyBuildTradeDims(全象限 key->mkt/rating) ----
tradedims={}
for qk,md in quads.items():
    parts=qk.split('_'); dimType=parts[0]; dimVal='_'.join(parts[1:])
    for mk,arr in md.items():
        for t in arr:
            key='|'.join([str(t[fIdx['signal_date']] or ''),str(t[fIdx['index_id']] or ''),str(t[fIdx['signal']] or ''),str(t[fIdx['buy_date']] or ''),str(t[fIdx['etf_code']] or ''),str(t[fIdx['sell_date']] or '')])
            td=tradedims.setdefault(key,{})
            td[dimType]=dimVal

def buyWeekday(s):
    if not s or len(s)<8: return -1
    import datetime
    y,m,d=int(s[:4]),int(s[4:6]),int(s[6:8])
    jsDay=datetime.date(y,m,d).weekday()  # 0=Mon..6=Sun
    return (jsDay+6)%7  # Python:0=Mon; JS (jsDay+6)%7 0=Mon

def buypriceBin(p):
    if p is None: return ""
    if p<=0.841441: return "vlow"
    if p<=1.015314: return "low"
    if p<=1.194593: return "mid"
    if p<=1.446645: return "high"
    return "vhigh"

def tradeFeatures(t):
    bd=str(t[fIdx['buy_date']] or ''); mm=bd[4:6]; dd=int(bd[6:8] or 0)
    sig=str(t[fIdx['signal']] or '')
    wd=buyWeekday(bd); bpb=buypriceBin(t[fIdx['buy_price']])
    dk='|'.join([str(t[fIdx['signal_date']] or ''),str(t[fIdx['index_id']] or ''),sig,bd,str(t[fIdx['etf_code']] or ''),str(t[fIdx['sell_date']] or '')])
    dims=tradedims.get(dk,{})
    ts=float(t[fIdx['track_score']]) if t[fIdx['track_score']] is not None else 999
    etfD=str(t[fIdx['track_tier']] or '')
    q=math.ceil(int(mm)/3) if mm else 0
    return {'mm':mm,'dd':dd,'sig':sig,'wd':wd,'bpb':bpb,'mktD':dims.get('mkt',''),'ratD':dims.get('rating',''),'ts':ts,'etfD':etfD,'q':q}

# ---- T1 spec(kelly_loss_features meta.rules)+features ----
specmap={r['key']:r for r in FEAT.get('meta',{}).get('rules',[])}
feat_series={k:v for k,v in FEAT.get('features',{}).items()}
def lossRuleHit(key, ctx):
    spec=specmap.get(key)
    if not spec: return False
    if spec.get('feature'):
        series=feat_series.get(spec['feature'])
        v=series.get(str(ctx['date'] or '')) if series else None
        if v is None: return False
        if spec.get('direction')=='low':
            if not (v<spec['threshold']): return False
        else:
            if not (v>spec['threshold']): return False
    if spec.get('sig') is not None and str(ctx['sig'] or '')!=spec['sig']: return False
    if spec.get('tier') is not None and str(ctx['tier'] or '')!=spec['tier']: return False
    if spec.get('mkt') is not None and str(ctx['mkt'] or '')!=spec['mkt']: return False
    if spec.get('track_tier') is not None:
        tt=str(ctx['track_tier'] or '')
        if isinstance(spec['track_tier'],list):
            if tt not in spec['track_tier']: return False
        else:
            if tt!=spec['track_tier']: return False
    if spec.get('rating') is not None:
        if str(ctx['rating'] or '')!=spec['rating']: return False
        tv=999 if (ctx['ts'] is None or ctx['ts']=='') else float(ctx['ts'])
        if not (tv<spec['max_ts']): return False
        if str(ctx['smonth'] or '') not in spec['months']: return False
    return True

def activeMonthMask(f):
    mask=0
    for k,v in MMASK.items():
        if f.get(k): mask|=v
    return mask

# ---- _kellyPassesFadeFilters(t, filters) ----
def passesFade(t, filters, monthMask):
    fc=None
    for k in FRONT:
        if not filters[k]: continue
        if fc is None:
            fc={'sig':str(t[fIdx['signal']] or ''),'mm':str(t[fIdx['buy_date']] or '')[4:6],
                'rating':str(t[fIdx['rating']] or ''),'tier':str(t[fIdx['market_tier']] or ''),
                'tierAll':str(t[fIdx['market_tier_all']] or ''),'tierCyb':str(t[fIdx['market_tier_cyb']] or ''),
                'mstate':t[fIdx['market_state']]}
        if specHit(k,fc): return False
    v3on=any(filters[k] for k in ['n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay','r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay'])
    v4on=any(filters[k] for k in ['greedy7','greedy10','greedy15','v4cSimple','v4b','v4d','v4j','v4i','v4f','v4g','v4m','v4k'])
    r3on=any(filters[k] for k in ['a5NovMidSpecial','a45NovMidLateSpecial'])
    janOn=any(filters[k] for k in ['janMidRating','janMidSpecial'])
    k2on=any(filters[k] for k in ['k2c5HkChase','k3ConceptBuy'])
    if v3on or v4on or r3on or janOn or k2on:
        mmStr=str(t[fIdx['buy_date']] or '')[4:6]
        mmInt=int(mmStr) if mmStr else 0
        if mmInt and not (monthMask & (1<<(mmInt-1))): return True
        feats=tradeFeatures(t)
        for k in GATE:
            if filters[k] and specHit(k,feats): return False
    m20on=any(filters[k] for k in T1KEYS)
    if m20on:
        bd20=str(t[fIdx['buy_date']] or '')
        sd20=str(t[fIdx['signal_date']] or '')
        sig20=str(t[fIdx['signal']] or '')
        dk20='|'.join([sd20,str(t[fIdx['index_id']] or ''),sig20,bd20,str(t[fIdx['etf_code']] or ''),str(t[fIdx['sell_date']] or '')])
        mkt20=(tradedims.get(dk20,{}) or {}).get('mkt','')
        tt_v=t[fIdx['track_tier']]
        tt='null' if tt_v is None else ('' if tt_v is None else str(tt_v))
        ctx20={'sig':sig20,'mkt':mkt20,'tier':str(t[fIdx['market_tier']] or ''),
               'track_tier':tt,'date':bd20,'smonth':sd20[4:6],
               'rating':str(t[fIdx['rating']] or ''),'ts':t[fIdx['track_score']]}
        for k in T1KEYS:
            if filters[k] and lossRuleHit(k,ctx20): return False
    return True

# ---- 费率重算(lab.js _kellyRecomputeTrade, KELLY_ORIG_SLIPPAGE=0.001) ----
def isShEtf(ec): return ec.startswith('51') or ec.startswith('58')
def recompute(t, feeParams, buyAmount):
    bp=t[fIdx['buy_price']] or 0
    sp=t[fIdx['sell_price']] or 0
    cp=t[fIdx['current_price']] or 0
    ec=str(t[fIdx['etf_code']] or '')
    sellDate=str(t[fIdx['sell_date']] or '')
    if bp<=0: return {'profit':0,'return_pct':0}
    closeBuy=bp/(1+0.001)
    closeSell=(sp/(1-0.001)) if sellDate else cp
    c=feeParams['commission_rate']; s=feeParams['slippage']; minC=feeParams['min_commission']
    sh=feeParams['transfer_fee_rate_sh'] if isShEtf(ec) else 0
    stamp=feeParams['stamp_duty_rate']
    buyPriceNew=closeBuy*(1+s)
    if buyPriceNew<=0: return {'profit':0,'return_pct':0}
    sharesNew=buyAmount/(buyPriceNew*(1+c+sh))
    grossNew=sharesNew*buyPriceNew
    commBuy=grossNew*c
    if commBuy<minC:
        sharesNew=(buyAmount-minC)/(buyPriceNew*(1+sh))
        grossNew=sharesNew*buyPriceNew
        commBuy=minC
    sellPriceNew=closeSell*(1-s)
    sellAmountNew=sharesNew*sellPriceNew
    commSell=max(sellAmountNew*c,minC)
    transferFeeSell=sellAmountNew*sh
    stampDuty=sellAmountNew*stamp
    netNew=sellAmountNew-commSell-transferFeeSell-stampDuty
    profitNew=netNew-buyAmount
    return {'profit':round(profitNew*10000)/10000,'return_pct':round(profitNew/buyAmount*100*10000)/10000}

ETFDEF={'commission_rate':0.00005,'min_commission':0.1,'slippage':0.001,'transfer_fee_rate_sh':0.00001,'stamp_duty_rate':0}

def baseKey(t):
    return '|'.join([str(t[fIdx['signal_date']] or ''),str(t[fIdx['index_id']] or ''),str(t[fIdx['signal']] or ''),str(t[fIdx['buy_date']] or ''),str(t[fIdx['etf_code']] or '')])

def positionCapKeptKeys(pool,K):
    kept={}
    if not K or K<=0 or not pool: return kept
    RRANK={'high':0,'mid':1,'low':2,'':3}
    SRANK={'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}
    byDate={}
    for x in pool:
        sd=str(x[fIdx['signal_date']] or '')
        if not sd: continue
        byDate.setdefault(sd,[]).append(x)
    for sd,rows in byDate.items():
        # 与 JS Array.sort 同源: track_score DESC -> rating(high>mid>low) -> signal(buy_backup>buy>buy_aux>buy_special) -> buy_date ASC
        # Python sorted 稳定(同 key 保持注入顺序=pool 收集序=rating_high/mid/low 顺序), 与 JS 稳定 sort 语义等价
        rows.sort(key=lambda x: (
            -(float(x[fIdx['track_score']]) if x[fIdx['track_score']] is not None else -1000),
            RRANK.get(str(x[fIdx['rating']] or ''),3),
            SRANK.get(str(x[fIdx['signal']] or ''),9),
            str(x[fIdx['buy_date']] or '')))
        # 注意: track_score is None 时 JS 用 -1, 但 None 数据极少且 rating_high 无; 用 -1000 尾部等价
        n=min(K,len(rows))
        for j in range(n): kept[baseKey(rows[j])]=True
    return kept

def collectBasePool(passFn):
    pool=[]; seen={}
    rks=['rating_high','rating_mid','rating_low']
    for rk in rks:
        for mk in sellModes:
            arr=quads.get(rk,{}).get(mk,[]) or []
            for t in arr:
                if passFn and not passFn(t): continue
                bk=baseKey(t)
                if bk not in seen:
                    seen[bk]=1; pool.append(t)
    return pool

def dayCounts(kept):
    m={}
    for k in kept:
        sd=str(k).split('|')[0]
        if sd: m[sd]=m.get(sd,0)+1
    return m

def perTradeAmount(sd,dc):
    if dc and dc>0: return BUY_AMT/dc
    return BUY_AMT

def passesFadeNoBull(t, filters, monthMask):
    f2=dict(filters); f2['bullAuxBackupStop']=False
    return passesFade(t,f2,monthMask)

MODES=['A','B','C','D','E','F','J','G','H','I']
def isLong(mk): return mk in ('G','H','I')
PERIODS=['y1','y3','y5','y10','all']
PERIOD_LABEL={'y1':'近1年','y3':'近3年','y5':'近5年','y10':'近10年','all':'全部'}

def run(S06ON, K):
    # 构建 per-date filters
    allF={k:False for k in ALLKEYS}
    if S06ON:
        passFnCache={}
        def getF6(dateStr):
            base=s06base(dateStr)
            if base not in passFnCache:
                passFnCache[base]=filtersForBase(base)
            return passFnCache[base]
        def pfFull(t):
            f6=getF6(str(t[fIdx['signal_date']] or ''))
            if not f6: return True  # fail-open
            return passesFade(t,f6,activeMonthMask(f6))
        def pfNB(t):
            f6=getF6(str(t[fIdx['signal_date']] or ''))
            if not f6: return True
            return passesFadeNoBull(t,f6,activeMonthMask(f6))
    else:
        def pfFull(t): return True
        def pfNB(t): return True
    # basePool 两份
    basePool=collectBasePool(pfFull)
    kept=positionCapKeptKeys(basePool,K)
    dcounts=dayCounts(kept) if K>0 else None
    basePoolNB=collectBasePool(pfNB)
    keptNB=positionCapKeptKeys(basePoolNB,K)
    dcountsNB=dayCounts(keptNB) if K>0 else None
    result={}
    RKS=['rating_high','rating_mid','rating_low']
    for mk in MODES:
        raw=[]
        for _rk in RKS:
            raw += (quads.get(_rk,{}).get(mk,[]) or [])
        pf=pfNB if isLong(mk) else pfFull
        kp=keptNB if isLong(mk) else kept
        dc= dcountsNB if isLong(mk) else dcounts
        toggled=[]
        for t in raw:
            if not pf(t): continue
            if K>0 and baseKey(t) not in kp: continue
            toggled.append(t)
        res={}
        for pk in PERIODS:
            co=cutoffs[pk]
            if co and co!='0': trades=[t for t in toggled if str(t[fIdx['buy_date']] or '')>=co]
            else: trades=toggled
            total=0; n=0; wins=0
            per=[]
            for t in trades:
                amt=perTradeAmount(str(t[fIdx['signal_date']] or ''), dc.get(str(t[fIdx['signal_date']] or '')) if dc else None)
                r=recompute(t,ETFDEF,amt)
                total+=r['profit']; n+=1
                if r['profit']>0: wins+=1
            res[pk]={'profit':round(total*10000)/10000,'n':n,'wins':wins,'wr':round(wins/n*100,2) if n else 0}
        result[mk]=res
    return result

# ---- SANITY: 原始(无过滤, 固定1万/笔, 费后) ----

if __name__ == '__main__':
    import sys; sys.stdout.flush()
    # current = 生产快照(off=new15, trade 主仓 09-01 20:35 定时链)
    set_s06('/Users/linhuichen/code/trade/static-site/data/kelly_mode_s06_state.json')
    print(f'=== current: off_base={S06.get("off_base")} coverage_end={S06.get("coverage_end")} ===')
    cur=run(S06ON=True,K=1)
    # offNEW14 = 新快照(off=new14, worktree 重跑)
    set_s06('/Users/linhuichen/code/trade/.claude/worktrees/s06-offbase-new14/static-site/data/kelly_mode_s06_state.json')
    print(f'=== offNEW14: off_base={S06.get("off_base")} coverage_end={S06.get("coverage_end")} ===')
    new=run(S06ON=True,K=1)

    print()
    print('========== K=1 各窗口净利对比(mode A) ==========')
    for pk in PERIODS:
        c=cur['A'][pk]; n=new['A'][pk]
        d=n['profit']-c['profit']
        print(f'  {PERIOD_LABEL[pk]}: current={c["profit"]:>12,.2f} (n={c["n"]}) | offNEW14={n["profit"]:>12,.2f} (n={n["n"]}) | Δ={d:+,.2f}')
    print()
    print('========== K=1 all 各模式净利对比(前端同构口径) ==========')
    for mk in MODES:
        c=cur[mk]['all']; n=new[mk]['all']
        d=n['profit']-c['profit']
        print(f'  mode {mk}: current={c["profit"]:>12,.2f} (n={c["n"]}) | offNEW14={n["profit"]:>12,.2f} (n={n["n"]}) | Δ={d:+,.2f}')
    print()
    k1all_c=cur['A']['all']['profit']; k1all_n=new['A']['all']['profit']
    print(f'[验收核] K=1 全史 mode A: current={k1all_c:,.2f} -> offNEW14={k1all_n:,.2f} Δ={k1all_n-k1all_c:+,.2f}')
    print('[参考] 08-29 主引擎blocklist口径: current=+155,683.40 -> offNEW14=+160,314.15 Δ=+4,630.75; 前端同构mode A 单孔位 Δ 同 +4,630.75')
    print(f'[判定] Δ 方向:', '为正 PASS' if k1all_n-k1all_c>0 else '为负/零 FAIL')
