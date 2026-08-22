# -*- coding: utf-8 -*-
"""首页「模拟回测」弹窗口径 1:1 移植(app.js L2464-3395)。
口径: mode=A 基笔池(跨16子域去重+聚合维度) -> 8键降亏 -> K档top-K -> signal_date切片 -> 费后重算(etf_def默认档)。
费率 etf_def: comm万3/min5/slip千1/transfer万0.1/stamp万5(卖出单边)。本金每笔10000。
"""
import json, datetime

FIELDS_CACHE = None

def load(path='static-site/data/signal_kelly_trades.json'):
    global FIELDS_CACHE
    with open(path) as f:
        tr = json.load(f)
    fIdx = {f: i for i, f in enumerate(tr['fields'])}
    FIELDS_CACHE = tr['fields']
    return tr, fIdx

def qk_dim(qk):
    if qk.startswith('mkt_'): return ('mkt', qk[4:])
    if qk.startswith('etf_'): return ('etf', qk[4:])
    if qk.startswith('sig_'): return ('sig', qk[4:])
    if qk.startswith('rating_'): return ('rating', qk[7:])
    return None

def base_key(t, fIdx):
    return (t[fIdx['signal_date']] or '') + '|' + (t[fIdx['index_id']] or '') + '|' + (t[fIdx['signal']] or '') + '|' + (t[fIdx['buy_date']] or '') + '|' + (t[fIdx['etf_code']] or '')

def build_mode_pool(tr, fIdx, mode):
    seen = {}
    records = []
    for qk in tr['quadrants']:
        dim = qk_dim(qk)
        arr = (tr['quadrants'][qk] or {}).get(mode) or []
        for orig in arr:
            bk = base_key(orig, fIdx)
            rec = seen.get(bk)
            if rec is None:
                rec = list(orig); rec.append(''); rec.append(''); rec.append('')
                # 追加 _mktD/_etfD/_ratD 于末尾 idx = len(fields)+0/1/2
                seen[bk] = rec
                records.append(rec)
            if dim:
                base = len(fIdx)
                if dim[0] == 'mkt':
                    if not rec[base]: rec[base] = dim[1]
                elif dim[0] == 'etf':
                    if not rec[base+1]: rec[base+1] = dim[1]
                elif dim[0] == 'rating':
                    if not rec[base+2]: rec[base+2] = dim[1]
    return records

def mk_idx(fIdx):
    """返回 (普通字段idx函数, _mktD/_etfD/_ratD idx)"""
    base = len(fIdx)
    return base, base+1, base+2

WEEKDAY_CACHE = {}
def buy_weekday(s):
    # 与 _simBuyWeekday 同: (jsDay+6)%7 == python weekday()
    if not s or len(str(s)) < 8: return -1
    s = str(s)
    y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    return datetime.date(y, m, d).weekday()

def buyprice_bin(price):
    if price is None: return ''
    if price <= 0.841441: return 'vlow'
    if price <= 1.015314: return 'low'
    if price <= 1.194593: return 'mid'
    if price <= 1.446645: return 'high'
    return 'vhigh'

DEFAULT_FILTERS = {
    'excludeAux': False, 'marketTiming': False, 'excludeMonth': False, 'excludeRatingLow': False,
    'excludeAuxCross': True, 'excludeSpecialBear': True, 'excludeMonthDummy': False,
    'n1MarTueHigh': False, 'n2NovSpecialIndustry': True, 'r8PureNonMay': False,
    'n3NovSpecialMon': False, 'n4AMay': False, 'r7MayReinforced': True,
    'n5MayVlow': False, 'n6MidMay': False, 'r10May6NonMay': False,
    'v4cSimple': False, 'v4b': False, 'greedy7': False, 'greedy10': False,
    'v4d': False, 'v4j': False, 'v4i': False, 'greedy15': True, 'v4f': False, 'v4g': False, 'v4m': False, 'v4k': False,
    'janMidRating': True, 'janMidSpecial': True,
    'k2c5HkChase': True, 'k3ConceptBuy': False,
    'legacyMa60Special': False, 'declinePhaseSpecial': False, 'excludeSpecialBearCyb': False,
    'a5NovMidSpecial': False, 'a45NovMidLateSpecial': False,
}

MONTH_MASK = {
    'a5NovMidSpecial': 1 << 10, 'a45NovMidLateSpecial': 1 << 10,
    'n1MarTueHigh': 1 << 2, 'n2NovSpecialIndustry': 1 << 10, 'r8PureNonMay': (1 << 2) | (1 << 10),
    'n3NovSpecialMon': 1 << 10, 'n4AMay': 1 << 4, 'r7MayReinforced': (1 << 4) | (1 << 2) | (1 << 10),
    'n5MayVlow': 1 << 4, 'n6MidMay': 1 << 4, 'r10May6NonMay': (1 << 4) | (1 << 2) | (1 << 10),
    'v4cSimple': 1 << 2, 'v4b': 1 << 4, 'greedy7': 0x1FFF, 'v4d': 1 << 11, 'v4j': 1 << 4, 'v4i': 1 << 4,
    'greedy10': 0x1FFF, 'v4f': 1 << 5, 'v4g': (1 << 0) | (1 << 1) | (1 << 2), 'v4m': 1 << 8, 'v4k': 1 << 0,
    'greedy15': 0x1FFF, 'janMidRating': 1 << 0, 'janMidSpecial': 1 << 0,
    'k2c5HkChase': 0x1FFF, 'k3ConceptBuy': 0x1FFF,
}

def active_month_mask(filters):
    mask = 0
    for k, v in MONTH_MASK.items():
        if filters.get(k): mask |= v
    return mask

def passes_fade(t, fIdx, filters, monthMask, mD, eD, rD):
    sd_ = t[fIdx['signal_date']]; sig = t[fIdx['signal']] or ''
    bd = t[fIdx['buy_date']] or ''
    mm = bd[4:6] if len(bd) >= 6 else ''
    dd = int(bd[6:8]) if len(bd) >= 8 else 0
    wd = buy_weekday(bd)
    bpb = buyprice_bin(t[fIdx['buy_price']])
    ts = float(t[fIdx['track_score']]) if fIdx.get('track_score') is not None and t[fIdx['track_score']] not in (None, '') else 999.0
    mt = t[fIdx['market_tier']] or '' if fIdx.get('market_tier') is not None else ''
    if filters.get('excludeAux') and sig == 'buy_aux': return False
    if filters.get('marketTiming') and t[fIdx['market_state']] is not True: return False
    if filters.get('excludeMonth') and mm in ('03', '05'): return False
    if filters.get('excludeRatingLow') and t[fIdx['rating']] == 'low': return False
    if filters.get('excludeAuxCross') and sig == 'buy_aux' and mm in ('03', '05'): return False
    if filters.get('excludeSpecialBear') and sig == 'buy_special' and fIdx.get('market_tier') is not None:
        if mt in ('熊市·主跌', '下降期'): return False
    if filters.get('legacyMa60Special') and sig == 'buy_special' and t[fIdx['market_state']] is False: return False
    if filters.get('declinePhaseSpecial') and sig == 'buy_special' and (t[fIdx['market_tier_all']] or '') == '下降期': return False
    if filters.get('excludeSpecialBearCyb') and sig == 'buy_special' and fIdx.get('market_tier_cyb') is not None:
        if (t[fIdx['market_tier_cyb']] or '') in ('熊市·主跌', '下降期'): return False
    v3on = any(filters.get(k) for k in ['n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay','r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay'])
    v4on = any(filters.get(k) for k in ['greedy7','greedy10','greedy15','v4cSimple','v4b','v4d','v4j','v4i','v4f','v4g','v4m','v4k'])
    r3on = any(filters.get(k) for k in ['a5NovMidSpecial','a45NovMidLateSpecial'])
    janon = any(filters.get(k) for k in ['janMidRating','janMidSpecial'])
    k2on = any(filters.get(k) for k in ['k2c5HkChase','k3ConceptBuy'])
    if v3on or v4on or r3on or janon or k2on:
        if monthMask:
            mmInt = int(mm) if mm else 0
            if mmInt and not (monthMask & (1 << (mmInt - 1))): return True  # 门控外=直接通过
        q = (int(mm) // 4 + 1) if mm else 0   # ceil(month/3); JS Math.ceil(m/3): m=4->ceil(0.8)=1? 注意!
        # 上行错误, 单独算: q = math.ceil(int(mm)/3)
        import math
        q = math.ceil(int(mm) / 3) if mm else 0
        mktD = t[mD] or ''; etfD = t[eD] or ''; ratD = t[rD] or ''
        if v3on:
            if filters.get('n1MarTueHigh') and mm == '03' and wd == 2 and bpb == 'high': return False
            if filters.get('n2NovSpecialIndustry') and sig == 'buy_special' and mm == '11' and mktD == 'industry': return False
            if filters.get('r8PureNonMay') and ((mm == '03' and wd == 2 and bpb == 'high') or (sig == 'buy_special' and mm == '11' and mktD == 'industry') or (sig == 'buy_special' and mm == '11' and wd == 0)): return False
            if filters.get('n3NovSpecialMon') and sig == 'buy_special' and mm == '11' and wd == 0: return False
            if filters.get('n4AMay') and mktD == 'a' and mm == '05': return False
            if filters.get('r7MayReinforced') and ((mktD == 'a' and mm == '05') or (ratD == 'mid' and mm == '05') or (mm == '05' and bpb == 'vlow') or (mm == '03' and wd == 2 and bpb == 'high') or (sig == 'buy_special' and mm == '11' and mktD == 'industry') or (sig == 'buy_special' and mm == '11' and wd == 0)): return False
            if filters.get('n5MayVlow') and mm == '05' and bpb == 'vlow': return False
            if filters.get('n6MidMay') and ratD == 'mid' and mm == '05': return False
            if filters.get('r10May6NonMay') and (mm == '05' or (mm == '03' and wd == 2 and bpb == 'high') or (sig == 'buy_special' and mm == '11' and mktD == 'industry') or (sig == 'buy_special' and mm == '11' and wd == 0) or (sig == 'buy_special' and mm == '11' and bpb == 'low') or (sig == 'buy_special' and mm == '03' and mktD == 'industry') or (mm == '03' and wd == 2 and sig == 'buy_aux')): return False
        if v4on:
            if filters.get('v4cSimple') and mm == '03' and wd == 2 and sig == 'buy_aux': return False
            if filters.get('v4b') and mktD == 'a' and mm == '05' and sig == 'buy_special' and etfD == 'related': return False
            if filters.get('greedy7') and ((sig == 'buy_special' and mm == '05') or (sig == 'buy_special' and mm == '11' and mktD == 'concept') or (sig == 'buy_special' and mm == '03') or (sig == 'buy_aux' and mm == '01') or (q == 2 and bpb == 'vlow' and sig == 'buy_aux' and mktD == 'concept') or (sig == 'buy' and mm == '01') or (mm == '03' and wd == 2 and mktD == 'concept' and ratD == 'low')): return False
            if filters.get('v4d') and mm == '12' and wd == 1 and sig == 'buy_aux' and ts < 50: return False
            if filters.get('v4j') and mm == '05' and bpb == 'vlow' and sig == 'buy_special': return False
            if filters.get('v4i') and sig == 'buy_special' and mm == '05' and mktD == 'concept' and wd == 0: return False
            if filters.get('greedy10') and ((sig == 'buy_special' and mm == '05') or (sig == 'buy_special' and mm == '11' and mktD == 'concept') or (sig == 'buy_special' and mm == '03') or (sig == 'buy_aux' and mm == '01') or (q == 2 and bpb == 'vlow' and sig == 'buy_aux' and mktD == 'concept') or (sig == 'buy' and mm == '01') or (mm == '03' and wd == 2 and mktD == 'concept' and ratD == 'low') or (sig == 'buy_aux' and mm == '12' and ts < 50) or (mm == '06' and bpb == 'vlow' and ratD == 'low') or (sig == 'buy_aux' and mm == '05')): return False
            if filters.get('v4f') and sig == 'buy' and mm == '06' and wd == 2 and etfD == 'related': return False
            if filters.get('v4g') and mktD == 'global' and q == 1 and sig == 'buy_aux' and ratD == 'low': return False
            if filters.get('v4m') and sig == 'buy_special' and mm == '09' and wd == 2: return False
            if filters.get('v4k') and sig == 'buy' and mm == '01' and bpb == 'high': return False
            if filters.get('greedy15') and ((sig == 'buy_special' and mm == '05') or (sig == 'buy_special' and mm == '11' and mktD == 'concept') or (sig == 'buy_special' and mm == '03') or (sig == 'buy_aux' and mm == '01') or (q == 2 and bpb == 'vlow' and sig == 'buy_aux' and mktD == 'concept') or (sig == 'buy' and mm == '01') or (mm == '03' and wd == 2 and mktD == 'concept' and ratD == 'low') or (sig == 'buy_aux' and mm == '12' and ts < 50) or (mm == '06' and bpb == 'vlow' and ratD == 'low') or (sig == 'buy_aux' and mm == '05') or (sig == 'buy_special' and mm == '11' and mktD == 'industry') or (mm == '04' and wd == 1 and mktD == 'concept' and ts < 50) or (mktD == 'global' and q == 1 and sig == 'buy_aux' and ratD == 'low') or (mm == '01' and bpb == 'low' and sig == 'buy_special' and mktD == 'concept') or (sig == 'buy_special' and mm == '09' and wd == 2)): return False
        if r3on:
            if filters.get('a5NovMidSpecial') and sig == 'buy_special' and mm == '11' and 11 <= dd <= 20: return False
            if filters.get('a45NovMidLateSpecial') and sig == 'buy_special' and mm == '11' and dd >= 11: return False
        if janon:
            if filters.get('janMidRating') and mm == '01' and 11 <= dd <= 20 and ratD == 'mid': return False
            if filters.get('janMidSpecial') and sig == 'buy_special' and mm == '01' and 11 <= dd <= 20: return False
        if k2on:
            if filters.get('k2c5HkChase') and sig in ('buy_special', 'buy_backup') and mktD == 'hk': return False
            if filters.get('k3ConceptBuy') and sig == 'buy' and mktD == 'concept': return False
    return True

RATING_RANK = {'high': 0, 'mid': 1, 'low': 2, '_d': 3}
SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3, '_d': 9}

def topk_by_date(rows, fIdx, K):
    bydate = {}
    for t in rows:
        bydate.setdefault(str(t[fIdx['signal_date']] or ''), []).append(t)
    out = []
    for sd in bydate:
        rows2 = bydate[sd]
        def rk(r): return RATING_RANK.get(str(r[fIdx['rating']] or ''), 3)
        def sk(s): return SIG_RANK.get(str(s[fIdx['signal']] or ''), 9)
        rows2.sort(key=lambda a: (
            -float(a[fIdx['track_score']]) if a[fIdx['track_score']] not in (None, '') else float('inf'),
            rk(a), sk(a), str(a[fIdx['buy_date']] or '')))
        out.extend(rows2[:K])
    return out

# ---- 费率(默认档 etf_def) ----
FP_DEF = dict(commission_rate=0.0003, min_commission=5.0, slippage=0.001, transfer_fee_rate_sh=0.00001, stamp_duty_rate=0.0005)

def buy_with_fees(budget, close, etf_code, fp):
    buy_price = close * (1 + fp['slippage'])
    if buy_price <= 0: return dict(shares=0, commission=0, transferFee=0, buyPrice=0)
    sh = fp['transfer_fee_rate_sh'] if etf_code else 0
    shares = budget / (buy_price * (1 + fp['commission_rate'] + sh))
    gross = shares * buy_price
    comm = gross * fp['commission_rate']
    if comm < fp['min_commission']:
        shares = (budget - fp['min_commission']) / (buy_price * (1 + sh))
        gross = shares * buy_price
        comm = fp['min_commission']
    transfer_fee = gross * sh
    return dict(shares=shares, commission=comm, transferFee=transfer_fee, buyPrice=buy_price)

def sell_with_fees(shares, close, etf_code, fp):
    sell_price = close * (1 - fp['slippage'])
    sell_amount = shares * sell_price
    comm = max(sell_amount * fp['commission_rate'], fp['min_commission'])
    sh = fp['transfer_fee_rate_sh'] if etf_code else 0
    transfer_fee = sell_amount * sh
    stamp = sell_amount * (fp['stamp_duty_rate'] or 0)
    net = sell_amount - comm - transfer_fee - stamp
    return dict(net=net, commission=comm, transferFee=transfer_fee, stampDuty=stamp)

PRIN = 10000

def calc_row(t, fIdx, fp=None):
    if fp is None: fp = FP_DEF
    bp = float(t[fIdx['buy_price']] or 0)
    is_holding = not str(t[fIdx['sell_date']] or '')
    if is_holding:
        cp = float(t[fIdx['current_price']] or 0)
        eff_sp = cp if cp > 0 else 0
    else:
        eff_sp = float(t[fIdx['sell_price']] or 0)
    code = t[fIdx['etf_code']] or ''
    br = buy_with_fees(PRIN, bp, code, fp)
    buy_fee = br['commission'] + br['transferFee']
    if is_holding and not (eff_sp > 0):
        pnl = 0.0
        sell_fee = 0.0
    else:
        sr = sell_with_fees(br['shares'], eff_sp, code, fp)
        sell_fee = sr['commission'] + sr['transferFee'] + sr['stampDuty']
        pnl = sr['net'] - PRIN
    return dict(isHolding=is_holding, pnlYuan=pnl, pnlPct=pnl / PRIN * 100, buyFee=buy_fee, sellFee=sell_fee)

def window_stats(rows, fIdx, fp=None):
    """与 _simRenderTable 同口径: 正序扫描 cumYuan, peakPosN 分母"""
    if fp is None: fp = FP_DEF
    asc = sorted(rows, key=lambda t: str(t[fIdx['signal_date']] or ''))
    # 当日持仓峰值(先删后加)
    peak_pos_n = 0
    open_map = {}
    gi = 0
    while gi < len(asc):
        sd = str(asc[gi][fIdx['signal_date']] or '')
        gj = gi
        while gj < len(asc) and str(asc[gj][fIdx['signal_date']] or '') == sd: gj += 1
        for ok in [k for k, v in open_map.items() if v and v <= sd]:
            del open_map[ok]
        for i in range(gi, gj):
            bd = str(asc[i][fIdx['buy_date']] or '')
            sld = str(asc[i][fIdx['sell_date']] or '')
            if bd and bd <= sd and (sld == '' or sld > sd):
                open_map.setdefault(base_key(asc[i], fIdx), sld)
        posN = len(open_map)
        if posN > peak_pos_n: peak_pos_n = posN
        gi = gj
    cum_yuan = 0.0; right = 0; wrong = 0; holding = 0
    for t in asc:
        c = calc_row(t, fIdx, fp)
        if c['isHolding']: holding += 1
        cum_yuan += c['pnlYuan']
        if c['pnlYuan'] > 0: right += 1
        else: wrong += 1
    n = len(asc)
    return dict(n=n, cumYuan=cum_yuan, cumPct=cum_yuan / (max(peak_pos_n, 1) * PRIN) * 100,
                peakPosN=peak_pos_n, right=right, wrong=wrong, holding=holding,
                winRate=right / max(right + wrong, 1) * 100)
