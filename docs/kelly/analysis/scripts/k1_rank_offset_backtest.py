# -*- coding: utf-8 -*-
"""
k=1 取值名次偏移对比回测(TASKS #21)
目的: 验证用户命题「k=1 取当天第1名信号未必最优」。
  基线(K=1 取第1名) vs 模式2/3/4(K=1 但优先取当天第2/3/4 名, 当天不足则逐级回退到最高可用顺位)。
方法口径: 完全复用前端凯利区真实链路(与 kelly_s06k1_matrix.py 同源):
  S06 per-date 基座(a9/new15 按日切, kelly_mode_s06_state.json) -> _kellyPassesFadeFilters 逐键判定
  -> basePool(rating 三区×10模式, passFn 过滤, baseKey 去重) -> 每 signal_date 排序
     (track_score DESC -> rating high>mid>low -> 信号类型 buy_backup>buy>buy_aux>buy_special -> buy_date ASC)
  -> 模式 m: 取当日排序第 min(m, 当日信号数) 名(不足回退到最高可用顺位) -> 每日保留 1 笔(K=1 语义)
  -> 每笔金额 = 10000/当日保留数(每日池等分, K=1 时=10000) -> 费率重算(etf_main: 佣金万5 min0.1 + 滑点千1 + 沪市过户费万1)
输入依赖: static-site/data/signal_kelly_trades.json + signal_kelly_backtest.json + kelly_loss_features.json + kelly_mode_s06_state.json
输出: stdout(报告数据表)
重跑: python3 docs/kelly/analysis/scripts/k1_rank_offset_backtest.py
数据截止: signal_kelly_trades.json generated_at 见下方输出; 基准 = v1.1.7 S06 动态默认档
"""
import json, math, sys
from collections import defaultdict

ROOT = '/Users/linhuichen/code/trade/static-site/data/'
TD = json.load(open(ROOT + 'signal_kelly_trades.json'))
BT = json.load(open(ROOT + 'signal_kelly_backtest.json'))
FEAT = json.load(open(ROOT + 'kelly_loss_features.json'))
S06 = json.load(open(ROOT + 'kelly_mode_s06_state.json'))

fields = TD['fields']; fIdx = {f: i for i, f in enumerate(fields)}
BUY_AMT = TD['buy_amount'] or 10000
cutoffs = BT['config']['period_cutoffs']
sellModes = BT['config']['sell_modes']
quads = TD['quadrants']

# ---- S06 快照: date->effective_mode ----
s06byDate = {}
for r in S06['daily']:
    s06byDate[str(r['date'])] = r.get('effective_mode')
def s06base(dateStr):
    return s06byDate.get(str(dateStr))

# ---- 58 键全集 + 预设键集(与 common.js _KELLY_FADE_MODE_PRESETS 对齐) ----
FRONT = ['excludeAux','marketTiming','excludeMonth','excludeRatingLow','excludeAuxCross',
 'excludeSpecialBear','legacyMa60Special','declinePhaseSpecial','excludeSpecialBearCyb','bullAuxBackupStop']
GATE = ['n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay',
 'r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay',
 'v4cSimple','v4b','greedy7','v4d','v4j','v4i','greedy10','v4f','v4g','v4m','v4k','greedy15',
 'a5NovMidSpecial','a45NovMidLateSpecial','janMidRating','janMidSpecial','k2c5HkChase','k3ConceptBuy']
T1KEYS = ['r2gLowRatingQ3','n1NorthOutflow','t1LowTurnSpecial','d1LowDivYield','q1QvixLowPct',
 'h1VolChgHighA','m1MarginDownBull','d2LowDivBull','p1LowDivBackup','v1HighVol20',
 's1SentALow','r1VolRatioLow','r2bSpecialGlobal','n2NorthOutConcept','v2Vol20Gt25',
 's2SentHs300Low','w1BackupDecline','a1BullAllStop','v3Vol20LowPct','ad1AdlineHot','excludeTierNone']
ALLKEYS = FRONT + GATE + T1KEYS
A9KEYS = ['excludeSpecialBear','n2NovSpecialIndustry','janMidRating','janMidSpecial','k2c5HkChase','r7MayReinforced','excludeAuxCross','greedy15','bullAuxBackupStop','t1LowTurnSpecial','q1QvixLowPct','m1MarginDownBull','v1HighVol20','r1VolRatioLow','k3ConceptBuy','r2bSpecialGlobal','r2gLowRatingQ3']
NEW15KEYS = ['r10May6NonMay','greedy15','janMidSpecial','k2c5HkChase','k3ConceptBuy','declinePhaseSpecial','n1NorthOutflow','t1LowTurnSpecial','d1LowDivYield','q1QvixLowPct','h1VolChgHighA','m1MarginDownBull','p1LowDivBackup','r2bSpecialGlobal','excludeTierNone']
def filtersForBase(base):
    f = {k: False for k in ALLKEYS}
    keys = A9KEYS if base == 'a9' else NEW15KEYS if base == 'new15' else []
    for k in keys: f[k] = True
    return f

# ---- legacy specs(common.js _KELLY_FADE_LEGACY_SPECS) ----
LEGACY = {
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
    sp = LEGACY.get(key)
    if not sp: return False
    for p in sp['any']:
        ok = True
        for ck, val in p.items():
            if ck=='sig' and c['sig']!=val: ok=False; break
            if ck=='sigIn' and c['sig'] not in val: ok=False; break
            if ck=='mm' and c['mm']!=val: ok=False; break
            if ck=='mmIn' and c['mm'] not in val: ok=False; break
            if ck=='ddMin' and not (c['dd']>=val): ok=False; break
            if ck=='ddMax' and not (c['dd']<=val): ok=False; break
            if ck=='wd' and c['wd']!=val: ok=False; break
            if ck=='bpb' and c['bpb']!=val: ok=False; break
            if ck=='q' and c['q']!=val: ok=False; break
            if ck=='tsMax' and not (float(c['ts'])<val): ok=False; break
            if ck=='mkt' and c['mktD']!=val: ok=False; break
            if ck=='etf' and c['etfD']!=val: ok=False; break
            if ck=='rat' and c['ratD']!=val: ok=False; break
            if ck=='tier' and c.get('tier','')!=val: ok=False; break
            if ck=='tierIn' and c.get('tier','') not in val: ok=False; break
            if ck=='tierAll' and c.get('tierAll','')!=val: ok=False; break
            if ck=='tierCybIn' and c.get('tierCyb','') not in val: ok=False; break
            if ck=='ratingIsLow' and c['rating']!='low': ok=False; break
            if ck=='mstateNotTrue' and c['mstate'] is True: ok=False; break
            if ck=='mstateFalse' and c['mstate'] is not False: ok=False; break
        if ok: return True
    return False

# ---- month mask ----
MMASK = {
 'a5NovMidSpecial':1<<10,'a45NovMidLateSpecial':1<<10,'n1MarTueHigh':1<<2,'n2NovSpecialIndustry':1<<10,
 'r8PureNonMay':(1<<2)|(1<<10),'n3NovSpecialMon':1<<10,'n4AMay':1<<4,'r7MayReinforced':(1<<4)|(1<<2)|(1<<10),
 'n5MayVlow':1<<4,'n6MidMay':1<<4,'r10May6NonMay':(1<<4)|(1<<2)|(1<<10),
 'v4cSimple':1<<2,'v4b':1<<4,'greedy7':(1<<4)|(1<<10)|(1<<2)|(1<<0)|(1<<3)|(1<<5),
 'v4d':1<<11,'v4j':1<<4,'v4i':1<<4,'greedy10':(1<<4)|(1<<10)|(1<<2)|(1<<0)|(1<<3)|(1<<5)|(1<<11),
 'v4f':1<<5,'v4g':(1<<0)|(1<<1)|(1<<2),'v4m':1<<8,'v4k':1<<0,
 'greedy15':(1<<0)|(1<<1)|(1<<2)|(1<<3)|(1<<4)|(1<<5)|(1<<8)|(1<<10)|(1<<11),
 'janMidRating':1<<0,'janMidSpecial':1<<0,'k2c5HkChase':0x1FFF
}

# ---- trade dims(全象限 key->mkt/rating) ----
tradedims = {}
for qk, md in quads.items():
    parts = qk.split('_'); dimType = parts[0]; dimVal = '_'.join(parts[1:])
    for mk, arr in md.items():
        for t in arr:
            key = '|'.join([str(t[fIdx['signal_date']] or ''),str(t[fIdx['index_id']] or ''),str(t[fIdx['signal']] or ''),str(t[fIdx['buy_date']] or ''),str(t[fIdx['etf_code']] or ''),str(t[fIdx['sell_date']] or '')])
            td = tradedims.setdefault(key, {})
            td[dimType] = dimVal

def buyWeekday(s):
    if not s or len(s)<8: return -1
    import datetime
    y,m,d = int(s[:4]),int(s[4:6]),int(s[6:8])
    jsDay = datetime.date(y,m,d).weekday()
    return (jsDay+6)%7

def buypriceBin(p):
    if p is None: return ""
    if p<=0.841441: return "vlow"
    if p<=1.015314: return "low"
    if p<=1.194593: return "mid"
    if p<=1.446645: return "high"
    return "vhigh"

def tradeFeatures(t):
    bd = str(t[fIdx['buy_date']] or ''); mm = bd[4:6]; dd = int(bd[6:8] or 0)
    sig = str(t[fIdx['signal']] or '')
    wd = buyWeekday(bd); bpb = buypriceBin(t[fIdx['buy_price']])
    dk = '|'.join([str(t[fIdx['signal_date']] or ''),str(t[fIdx['index_id']] or ''),sig,bd,str(t[fIdx['etf_code']] or ''),str(t[fIdx['sell_date']] or '')])
    dims = tradedims.get(dk,{})
    ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] is not None else 999
    etfD = str(t[fIdx['track_tier']] or '')
    q = math.ceil(int(mm)/3) if mm else 0
    return {'mm':mm,'dd':dd,'sig':sig,'wd':wd,'bpb':bpb,'mktD':dims.get('mkt',''),'ratD':dims.get('rating',''),'ts':ts,'etfD':etfD,'q':q}

# ---- T1 spec ----
specmap = {r['key']: r for r in FEAT.get('meta',{}).get('rules',[])}
feat_series = {k:v for k,v in FEAT.get('features',{}).items()}
def lossRuleHit(key, ctx):
    spec = specmap.get(key)
    if not spec: return False
    if spec.get('feature'):
        series = feat_series.get(spec['feature'])
        v = series.get(str(ctx['date'] or '')) if series else None
        if v is None: return False
        if spec.get('direction')=='low':
            if not (v<spec['threshold']): return False
        else:
            if not (v>spec['threshold']): return False
    if spec.get('sig') is not None and str(ctx['sig'] or '')!=spec['sig']: return False
    if spec.get('tier') is not None and str(ctx['tier'] or '')!=spec['tier']: return False
    if spec.get('mkt') is not None and str(ctx['mkt'] or '')!=spec['mkt']: return False
    if spec.get('track_tier') is not None:
        tt = str(ctx['track_tier'] or '')
        if isinstance(spec['track_tier'], list):
            if tt not in spec['track_tier']: return False
        else:
            if tt!=spec['track_tier']: return False
    if spec.get('rating') is not None:
        if str(ctx['rating'] or '')!=spec['rating']: return False
        tv = 999 if (ctx['ts'] is None or ctx['ts']=='') else float(ctx['ts'])
        if not (tv<spec['max_ts']): return False
        if str(ctx['smonth'] or '') not in spec['months']: return False
    return True

def activeMonthMask(f):
    mask = 0
    for k,v in MMASK.items():
        if f.get(k): mask |= v
    return mask

# ---- _kellyPassesFadeFilters ----
def passesFade(t, filters, monthMask):
    fc = None
    for k in FRONT:
        if not filters[k]: continue
        if fc is None:
            fc = {'sig':str(t[fIdx['signal']] or ''),'mm':str(t[fIdx['buy_date']] or '')[4:6],
                  'rating':str(t[fIdx['rating']] or ''),'tier':str(t[fIdx['market_tier']] or ''),
                  'tierAll':str(t[fIdx['market_tier_all']] or ''),'tierCyb':str(t[fIdx['market_tier_cyb']] or ''),
                  'mstate':t[fIdx['market_state']]}
        if specHit(k,fc): return False
    v3on = any(filters[k] for k in ['n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay','r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay'])
    v4on = any(filters[k] for k in ['greedy7','greedy10','greedy15','v4cSimple','v4b','v4d','v4j','v4i','v4f','v4g','v4m','v4k'])
    r3on = any(filters[k] for k in ['a5NovMidSpecial','a45NovMidLateSpecial'])
    janOn = any(filters[k] for k in ['janMidRating','janMidSpecial'])
    k2on = any(filters[k] for k in ['k2c5HkChase','k3ConceptBuy'])
    if v3on or v4on or r3on or janOn or k2on:
        mmStr = str(t[fIdx['buy_date']] or '')[4:6]
        mmInt = int(mmStr) if mmStr else 0
        if mmInt and not (monthMask & (1<<(mmInt-1))): return True
        feats = tradeFeatures(t)
        for k in GATE:
            if filters[k] and specHit(k,feats): return False
    m20on = any(filters[k] for k in T1KEYS)
    if m20on:
        bd20 = str(t[fIdx['buy_date']] or '')
        sd20 = str(t[fIdx['signal_date']] or '')
        sig20 = str(t[fIdx['signal']] or '')
        dk20 = '|'.join([sd20,str(t[fIdx['index_id']] or ''),sig20,bd20,str(t[fIdx['etf_code']] or ''),str(t[fIdx['sell_date']] or '')])
        mkt20 = (tradedims.get(dk20,{}) or {}).get('mkt','')
        tt_v = t[fIdx['track_tier']]
        tt = 'null' if tt_v is None else ('' if tt_v is None else str(tt_v))
        ctx20 = {'sig':sig20,'mkt':mkt20,'tier':str(t[fIdx['market_tier']] or ''),
                 'track_tier':tt,'date':bd20,'smonth':sd20[4:6],
                 'rating':str(t[fIdx['rating']] or ''),'ts':t[fIdx['track_score']]}
        for k in T1KEYS:
            if filters[k] and lossRuleHit(k,ctx20): return False
    return True

def passesFadeNoBull(t, filters, monthMask):
    f2 = dict(filters); f2['bullAuxBackupStop'] = False
    return passesFade(t, f2, monthMask)

# ---- 费率重算(etf_main) ----
def isShEtf(ec): return ec.startswith('51') or ec.startswith('58')
def recompute(t, feeParams, buyAmount):
    bp = t[fIdx['buy_price']] or 0
    sp = t[fIdx['sell_price']] or 0
    cp = t[fIdx['current_price']] or 0
    ec = str(t[fIdx['etf_code']] or '')
    sellDate = str(t[fIdx['sell_date']] or '')
    if bp<=0: return {'profit':0,'return_pct':0}
    closeBuy = bp/(1+0.001)
    closeSell = (sp/(1-0.001)) if sellDate else cp
    c = feeParams['commission_rate']; s = feeParams['slippage']; minC = feeParams['min_commission']
    sh = feeParams['transfer_fee_rate_sh'] if isShEtf(ec) else 0
    stamp = feeParams['stamp_duty_rate']
    buyPriceNew = closeBuy*(1+s)
    if buyPriceNew<=0: return {'profit':0,'return_pct':0}
    sharesNew = buyAmount/(buyPriceNew*(1+c+sh))
    grossNew = sharesNew*buyPriceNew
    commBuy = grossNew*c
    if commBuy<minC:
        sharesNew = (buyAmount-minC)/(buyPriceNew*(1+sh))
        grossNew = sharesNew*buyPriceNew
        commBuy = minC
    sellPriceNew = closeSell*(1-s)
    sellAmountNew = sharesNew*sellPriceNew
    commSell = max(sellAmountNew*c, minC)
    transferFeeSell = sellAmountNew*sh
    stampDuty = sellAmountNew*stamp
    netNew = sellAmountNew-commSell-transferFeeSell-stampDuty
    profitNew = netNew-buyAmount
    return {'profit':round(profitNew*10000)/10000,'return_pct':round(profitNew/buyAmount*100*10000)/10000}

ETFDEF = {'commission_rate':0.00005,'min_commission':0.1,'slippage':0.001,'transfer_fee_rate_sh':0.00001,'stamp_duty_rate':0}

def baseKey(t):
    return '|'.join([str(t[fIdx['signal_date']] or ''),str(t[fIdx['index_id']] or ''),str(t[fIdx['signal']] or ''),str(t[fIdx['buy_date']] or ''),str(t[fIdx['etf_code']] or '')])

# ---- 排序与名次(与前端 _kellyPositionCapKeptKeys 同源) ----
RRANK = {'high':0,'mid':1,'low':2,'':3}
SRANK = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}

def sortRows(rows):
    rows.sort(key=lambda x: (
        -(float(x[fIdx['track_score']]) if x[fIdx['track_score']] is not None else -1000),
        RRANK.get(str(x[fIdx['rating']] or ''),3),
        SRANK.get(str(x[fIdx['signal']] or ''),9),
        str(x[fIdx['buy_date']] or '')))
    return rows

def collectBasePool(passFn):
    pool = []; seen = {}
    rks = ['rating_high','rating_mid','rating_low']
    for rk in rks:
        for mk in sellModes:
            arr = quads.get(rk,{}).get(mk,[]) or []
            for t in arr:
                if passFn and not passFn(t): continue
                bk = baseKey(t)
                if bk not in seen:
                    seen[bk] = 1; pool.append(t)
    return pool

# 模式 m: 每日期取排序第 min(m, n) 名(n=当日信号数); K=1 语义=每日只保留 1 笔
def rankOffsetKept(pool, m):
    kept = {}
    byDate = {}
    for x in pool:
        sd = str(x[fIdx['signal_date']] or '')
        if not sd: continue
        byDate.setdefault(sd, []).append(x)
    for sd, rows in byDate.items():
        sortRows(rows)
        n = len(rows)
        idx = min(m, n) - 1   # 第 m 名, 不足回退到最高可用顺位(0-based)
        kept[baseKey(rows[idx])] = True
    return kept

def dayCounts(kept):
    m = {}
    for k in kept:
        sd = str(k).split('|')[0]
        if sd: m[sd] = m.get(sd,0)+1
    return m

def perTradeAmount(sd, dc):
    if dc and dc>0: return BUY_AMT/dc
    return BUY_AMT

MODES = ['A','B','C','D','E','F','J','G','H','I']
def isLong(mk): return mk in ('G','H','I')
PERIODS = ['y1','y3','y5','y10','all']
PERIOD_LABEL = {'y1':'近1年','y3':'近3年','y5':'近5年','y10':'近10年','all':'全部'}

# ---- 每日期信号数分布(通过过滤的基笔数, 全池) ----
def daySignalCounts(pool):
    c = defaultdict(int)
    for x in pool:
        c[str(x[fIdx['signal_date']] or '')] += 1
    return c

def drawdown(rows):
    if not rows: return 0,0,'',0
    sr = sorted(rows, key=lambda r: r['sd_s'] or '99999999')
    cum=0; peak=0; maxDd=0; valley=''; vp=0
    for r in sr:
        cum += r['profit']
        if cum>peak: peak = cum
        d = peak-cum
        if d>maxDd: maxDd=d; valley=r['sd_s'] or ''; vp=peak
    ti = sum(r['amount'] for r in rows)
    pct = round(maxDd/ti*100,4) if ti>0 else 0
    return round(maxDd*10000)/10000, pct, valley, 0

def yearsDetail(rows):
    ys = {}
    for r in rows:
        y = r['bd'][:4]
        v = ys.setdefault(y, {'n':0,'p':0,'a':0,'w':0})
        v['n']+=1; v['p']+=r['profit']; v['a']+=r['amount']
        if r['profit']>0: v['w']+=1
    return {y:{'n':v['n'],'p':round(v['p']*10000)/10000,
               'r':round(v['p']/v['a']*100,4) if v['a']>0 else 0,
               'wr':round(v['w']/v['n']*100,2) if v['n']>0 else 0}
            for y,v in sorted(ys.items())}

def statsByWindow(rows, pks):
    res = {}
    for pk in pks:
        co = cutoffs[pk]
        w = [r for r in rows if co=='0' or (r['bd']>=co)]
        n=len(w); p=sum(r['profit'] for r in w)
        ti=sum(r['amount'] for r in w)
        rh = round(p/ti*100,4) if ti>0 else 0
        ddA,ddP,dl,_ = drawdown(w)
        wi=sum(1 for r in w if r['profit']>0)
        sd_days = len(set(r['sd'] for r in w))
        res[pk] = {'n':n,'p':round(p*10000)/10000,'rh':rh,'ti':round(ti*10000)/10000,
                   'wr':round(wi/n*100,2) if n>0 else 0,
                   'dd_a':ddA,'dd_p':ddP,'valley':dl,'days':sd_days,
                   'years':yearsDetail(w)}
    return res

def buildRows(kept, keptNB, dcounts, dcountsNB, rks):
    """按前端口径逐卖出模式产出行: A-F 用全池 kept, G/H/I 用 NoBull kept。"""
    rows = []
    for mk in MODES:
        lg = isLong(mk)
        kp = keptNB if lg else kept
        dc = dcountsNB if lg else dcounts
        for rk in rks:
            for t in (quads.get(rk,{}).get(mk,[]) or []):
                bk = baseKey(t)
                if bk not in kp: continue
                sd = str(t[fIdx['signal_date']] or '')
                amt = perTradeAmount(sd, dc.get(sd) if dc else None)
                r = recompute(t, ETFDEF, amt)
                rows.append({'mk':mk,'sd':sd,'bd':str(t[fIdx['buy_date']] or ''),
                             'sd_s':str(t[fIdx['sell_date']] or ''),
                             'profit':r['profit'],'amount':amt,
                             'bk':bk,'rat':str(t[fIdx['rating']] or ''),
                             'sig':str(t[fIdx['signal']] or ''),
                             'ts':t[fIdx['track_score']]})
    return rows

def run(m):
    """模式 m: 返回 {rks_label: statsByWindow}。"""
    allF = {k: False for k in ALLKEYS}
    passFnCache = {}
    def getF6(dateStr):
        base = s06base(dateStr)
        if base not in passFnCache:
            passFnCache[base] = filtersForBase(base)
        return passFnCache[base]
    def pfFull(t):
        f6 = getF6(str(t[fIdx['signal_date']] or ''))
        if not f6: return True
        return passesFade(t, f6, activeMonthMask(f6))
    def pfNB(t):
        f6 = getF6(str(t[fIdx['signal_date']] or ''))
        if not f6: return True
        return passesFadeNoBull(t, f6, activeMonthMask(f6))
    basePool = collectBasePool(pfFull)
    kept = rankOffsetKept(basePool, m)
    dcounts = dayCounts(kept)
    basePoolNB = collectBasePool(pfNB)
    keptNB = rankOffsetKept(basePoolNB, m)
    dcountsNB = dayCounts(keptNB)
    out = {}
    for rks_label, rks in [('all',['rating_high','rating_mid','rating_low']),
                           ('rating_high',['rating_high']),
                           ('rating_mid',['rating_mid']),
                           ('rating_low',['rating_low'])]:
        rows = buildRows(kept, keptNB, dcounts, dcountsNB, rks)
        out[rks_label] = rows
    return out, basePool, kept

# ========== 报告输出(追加段2: 干净版) ==========
PERIOD_LABEL = {'y1':'近1年','y3':'近3年','y5':'近5年','y10':'近10年','all':'全部'}

def stats_by_window(rows, pks):
    res = {}
    for pk in pks:
        co = cutoffs[pk]
        w = [r for r in rows if co=='0' or (r['bd']>=co)]
        n = len(w); p = sum(r['profit'] for r in w)
        ti = sum(r['amount'] for r in w)
        rh = round(p/ti*100,4) if ti>0 else 0
        ddA, ddP, dl, _ = drawdown(w)
        wi = sum(1 for r in w if r['profit']>0)
        yd = years_detail(w)
        res[pk] = {'n':n,'p':round(p*10000)/10000,'rh':rh,'ti':round(ti*10000)/10000,
                   'wr':round(wi/n*100,2) if n>0 else 0,
                   'dd_a':ddA,'dd_p':ddP,'valley':dl,'days':len(set(r['sd'] for r in w)),
                   'years':yd}
    return res

def years_detail(rows):
    ys = {}
    for r in rows:
        y = r['bd'][:4]
        v = ys.setdefault(y, {'n':0,'p':0,'a':0,'w':0})
        v['n']+=1; v['p']+=r['profit']; v['a']+=r['amount']
        if r['profit']>0: v['w']+=1
    return {y:{'n':v['n'],'p':round(v['p']*10000)/10000,
               'r':round(v['p']/v['a']*100,4) if v['a']>0 else 0,
               'wr':round(v['w']/v['n']*100,2) if v['n']>0 else 0}
            for y,v in sorted(ys.items())}

def drawdown(rows):
    if not rows: return 0,0,'',0
    sr = sorted(rows, key=lambda r: r['sd_s'] or '99999999')
    cum=0; peak=0; maxDd=0; valley=''; vp=0
    for r in sr:
        cum += r['profit']
        if cum>peak: peak = cum
        d = peak-cum
        if d>maxDd: maxDd=d; valley=r['sd_s'] or ''; vp=peak
    ti = sum(r['amount'] for r in rows)
    pct = round(maxDd/ti*100,4) if ti>0 else 0
    return round(maxDd*10000)/10000, pct, valley, 0

def run4modes():
    """4 模式各跑一遍, 返回 (stats, rows_by_mode, day_n)。"""
    from collections import defaultdict
    stats = {}
    rows_by_mode = {}
    day_n = None
    for m in [1,2,3,4]:
        out, basePool, kept, dN = run_full(m)
        rows_by_mode[m] = out
        stats[m] = {}
        for rkl, rows in out.items():
            stats[m][rkl] = stats_by_window(rows, PERIODS)
        if m == 1:
            day_n = dN
    return stats, rows_by_mode, day_n

def run_full(m):
    """模式 m 完整跑: 返回 ({rks_label: rows}, basePool, kept, {sd: 当日信号数})。"""
    from collections import defaultdict
    passFnCache = {}
    def getF6(dateStr):
        base = s06base(dateStr)
        if base not in passFnCache:
            passFnCache[base] = filtersForBase(base)
        return passFnCache[base]
    def pfFull(t):
        f6 = getF6(str(t[fIdx['signal_date']] or ''))
        if not f6: return True
        return passesFade(t, f6, activeMonthMask(f6))
    def pfNB(t):
        f6 = getF6(str(t[fIdx['signal_date']] or ''))
        if not f6: return True
        return passesFadeNoBull(t, f6, activeMonthMask(f6))
    basePool = collectBasePool(pfFull)
    kept = rankOffsetKept(basePool, m)
    dcounts = dayCounts(kept)
    basePoolNB = collectBasePool(pfNB)
    keptNB = rankOffsetKept(basePoolNB, m)
    dcountsNB = dayCounts(keptNB)
    dayN = defaultdict(int)
    for x in basePool:
        dayN[str(x[fIdx['signal_date']] or '')] += 1
    out = {}
    for rks_label, rks in [('all',['rating_high','rating_mid','rating_low']),
                           ('rating_high',['rating_high']),
                           ('rating_mid',['rating_mid']),
                           ('rating_low',['rating_low'])]:
        rows = build_rows(kept, keptNB, dcounts, dcountsNB, rks)
        out[rks_label] = rows
    return out, basePool, kept, dict(dayN)

def build_rows(kept, keptNB, dcounts, dcountsNB, rks):
    """前端口径逐卖出模式产出行: A-F 用全池 kept, G/H/I 用 NoBull kept。"""
    rows = []
    for mk in MODES:
        lg = isLong(mk)
        kp = keptNB if lg else kept
        dc = dcountsNB if lg else dcounts
        for rk in rks:
            for t in (quads.get(rk,{}).get(mk,[]) or []):
                bk = baseKey(t)
                if bk not in kp: continue
                sd = str(t[fIdx['signal_date']] or '')
                amt = perTradeAmount(sd, dc.get(sd) if dc else None)
                r = recompute(t, ETFDEF, amt)
                rows.append({'mk':mk,'sd':sd,'bd':str(t[fIdx['buy_date']] or ''),
                             'sd_s':str(t[fIdx['sell_date']] or ''),
                             'profit':r['profit'],'amount':amt,
                             'bk':bk,'rat':str(t[fIdx['rating']] or ''),
                             'sig':str(t[fIdx['signal']] or ''),
                             'ts':t[fIdx['track_score']]})
    return rows

def main():
    print("="*90)
    print("k=1 取值名次偏移对比回测(TASKS #21)  基准=v1.1.7 S06动态默认档")
    print(f"数据: signal_kelly_trades.json generated_at={TD.get('generated_at')}  s06 coverage_end={S06.get('coverage_end')}")
    print("模式1=取第1名(现状) | 模式2=取第2名(不足回退) | 模式3=取第3名 | 模式4=取第4名")
    print("每笔金额=10000/当日保留数(K=1 每日保留1笔 -> 每笔恒1万)")
    print("="*90)

    stats, rows_by_mode, day_n = run4modes()

    # 1) 基线验证
    print("\n### 基线复现验证(模式1 全三象限):")
    for pk in PERIODS:
        s = stats[1]['all'][pk]
        print(f"  {PERIOD_LABEL[pk]}: 净利={s['p']:>+12,.0f} 笔数={s['n']:>5} 收益率={s['rh']:>6.2f}% 样本日={s['days']}")
    print("  锚点(s06p1_report 2026-08-29): 全部+1,950,519/6241笔; 近1年+292,928/848笔 (数据截止早3天)")
    print("  最新同数据锚点(kelly_s06k1_matrix 同数据): 全部+1,947,467/6241笔; 近1年+290,839/838笔")

    # 2) 模式对比 全三象限
    print("\n### 模式对比: 全三象限(净利/笔数/收益率)  全部窗口")
    hdr = f"{'窗口':<5} |" + " |".join([f"{'模式'+str(m):>16}" for m in [1,2,3,4]])
    print(hdr)
    print("-"*len(hdr))
    for pk in PERIODS:
        cells = []
        for m in [1,2,3,4]:
            s = stats[m]['all'][pk]
            cells.append(f"{s['p']:>+10,.0f}/{s['n']:>4}笔/{s['rh']:>5.2f}%")
        print(f"{PERIOD_LABEL[pk]:<5} | " + " | ".join(cells))

    # 3) Δ vs 模式1
    print("\n### Δ vs 模式1(净利差值): 全三象限")
    for pk in PERIODS:
        cells = []
        for m in [2,3,4]:
            dp = stats[m]['all'][pk]['p'] - stats[1]['all'][pk]['p']
            cells.append(f"{dp:>+12,.0f}")
        print(f"  {PERIOD_LABEL[pk]:<5} | " + " | ".join(cells))

    # 4) 象限分解
    for rkl, rkl_label in [('rating_high','高评级'), ('rating_mid','中评级'), ('rating_low','低评级')]:
        print(f"\n### {rkl_label}象限({rkl}) 全部: 净利/笔数/收益率")
        cells = []
        for m in [1,2,3,4]:
            s = stats[m][rkl]['all']
            cells.append(f"{s['p']:>+10,.0f}/{s['n']:>4}笔/{s['rh']:>5.2f}%")
        print("  " + " | ".join([f"模式{m}: {c}" for m,c in zip([1,2,3,4],cells)]))

    # 5) 高评级近1年(用户主场景)全窗口
    print("\n### 高评级象限 各窗口: 净利(4模式横向)")
    for pk in PERIODS:
        cells = [f"{stats[m]['rating_high'][pk]['p']:>+9,.0f}/{stats[m]['rating_high'][pk]['n']:>3}笔" for m in [1,2,3,4]]
        print(f"  {PERIOD_LABEL[pk]:<5} | " + " | ".join([f"模式{m}: {c}" for m,c in zip([1,2,3,4],cells)]))

    # 6) 按年分解 高评级
    print("\n### 高评级象限 按年分解(净利):")
    all_years = sorted(set().union(*[set(stats[m]['rating_high']['all']['years'].keys()) for m in [1,2,3,4]]))
    print(f"{'年份':<6} | " + " | ".join([f"{'模式'+str(m):>10}" for m in [1,2,3,4]]))
    for y in all_years:
        cells = [f"{stats[m]['rating_high']['all']['years'].get(y,{}).get('p',0):>+9,.0f}" for m in [1,2,3,4]]
        print(f"{y:<6} | " + " | ".join(cells))

    # 7) 全三象限按年 Δ
    print("\n### 全三象限 按年 Δ(模式2/3/4 - 模式1):")
    all_years = sorted(set().union(*[set(stats[m]['all']['all']['years'].keys()) for m in [1,2,3,4]]))
    print(f"{'年份':<6} | " + " | ".join([f"{'Δ模式'+str(m):>10}" for m in [2,3,4]]))
    for y in all_years:
        c1 = stats[1]['all']['all']['years'].get(y,{}).get('p',0)
        cells = [f"{stats[m]['all']['all']['years'].get(y,{}).get('p',0)-c1:>+9,.0f}" for m in [2,3,4]]
        print(f"{y:<6} | " + " | ".join(cells))

    # 8) 当日信号数分组
    print("\n### 当日信号数分组对比(全三象限, 全部):")
    from collections import defaultdict
    grp = {m: defaultdict(float) for m in [1,2,3,4]}
    grp_n = {m: defaultdict(int) for m in [1,2,3,4]}
    for m in [1,2,3,4]:
        for r in rows_by_mode[m]['all']:
            nd = day_n.get(r['sd'], 0)
            g = 'n1' if nd<=1 else 'n2' if nd==2 else 'n3' if nd==3 else 'n4p'
            grp[m][g] += r['profit']
            grp_n[m][g] += 1
    print(f"{'组':<6} | " + " | ".join([f"{'模式'+str(m):>14}" for m in [1,2,3,4]]))
    for g in ['n1','n2','n3','n4p']:
        cells = [f"{grp[m][g]:>+12,.0f}/{grp_n[m][g]:>4}笔" for m in [1,2,3,4]]
        print(f"{g:<6} | " + " | ".join(cells))

    # 9) 模式差异日数
    print("\n### 保留交易日数(各模式):")
    for m in [1,2,3,4]:
        print(f"  模式{m}: {len(set(r['sd'] for r in rows_by_mode[m]['all']))} 日")

    # 存档 json
    import json as _json
    with open('/tmp/k1_rank_offset_results.json','w') as f:
        out_pickle = {'stats': for_serialize(stats)}
        _json.dump(out_pickle, f, ensure_ascii=False)
    print("\n已存档 /tmp/k1_rank_offset_results.json")

def for_serialize(stats):
    import copy
    s2 = {}
    for m, rkls in stats.items():
        s2[m] = {}
        for rkl, pks in rkls.items():
            s2[m][rkl] = {}
            for pk, v in pks.items():
                s2[m][rkl][pk] = {kk: vv for kk, vv in v.items() if kk != 'years'}
                s2[m][rkl][pk]['years'] = {y: dict(yv) for y, yv in v['years'].items()}
    return s2

if __name__ == '__main__':
    main()
