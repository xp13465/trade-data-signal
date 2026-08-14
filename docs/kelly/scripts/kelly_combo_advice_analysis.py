# ============================================================
# 用途: 凯利组合/信号过滤核心分析库(共享依赖, 被大量回测脚本 import)
# 日期/来源: 2026-08-12 / tmp
# 结论: 提供 passes_fade/fIdx/empty_filters/BUY_AMOUNT/compute_stats/to_row 等过滤与统计工具
# 依赖: 无(被其他脚本 import, 不依赖本目录其他脚本)
# 输入/输出: 函数库, 供 import; 自身不独立读输出
# 复现: 无需直接运行, 被 strategyAB_compare.py / dailypool_rerun_core.py 等 import
# 注意: 原文件含硬编码绝对路径 /tmp 与 /Users/linhuichen/code/trade, 如需重跑请确认路径或改相对路径
# ============================================================
#!/usr/bin/env python3
"""kelly-combo-advice: 复刻 lab.js _kellyPassesFadeFilters/_kellyComputeStats 管线,
在 static-site/data/signal_kelly_trades.json (21字段 9模式) 上跑 3 类分析:
①4组合全开评价  ②分投资习惯建议  ③全信号表(按年窗口增长)
只读, 不改任何生产文件。
"""
import json, math, sys, os
from datetime import date, datetime
from collections import defaultdict

DATA = 'static-site/data/signal_kelly_trades.json'

def load():
    d = json.load(open(DATA))
    return d

d = load()
fields = d['fields']
fIdx = {f: i for i, f in enumerate(fields)}
quads = d['quadrants']
PERIODS = {'y1': '近1年', 'y3': '近3年', 'y5': '近5年', 'y10': '近10年', 'all': '全部'}
CUTOFFS = d.get('period_cutoffs', {})
BUY_AMOUNT = d.get('buy_amount', 10000)

# ---------- dims map (replicate _kellyBuildTradeDims) ----------
def build_dims():
    dims = {}
    for qk, modes in quads.items():
        parts = qk.split('_')
        dimType = parts[0]  # rating/etf/sig/mkt
        dimVal = '_'.join(parts[1:])
        for mk, arr in modes.items():
            for t in arr:
                key = '|'.join([str(t[fIdx['signal_date']]), str(t[fIdx['index_id']]),
                                str(t[fIdx['signal']]), str(t[fIdx['buy_date']]),
                                str(t[fIdx['etf_code']]), str(t[fIdx['sell_date']])])
                e = dims.get(key)
                if e is None:
                    e = dims[key] = {}
                e[dimType] = dimVal
    return dims

DIMS = build_dims()

# ---------- features (replicate _kellyTradeFeatures) ----------
def weekday(bd):
    """Python weekday 0=Mon..6=Sun (replicate _kellyBuyWeekday)"""
    if not bd or len(bd) < 8:
        return -1
    return date(int(bd[0:4]), int(bd[4:6]), int(bd[6:8])).weekday()

def buyprice_bin(price):
    if price is None:
        return ""
    if price <= 0.841441: return "vlow"
    if price <= 1.015314: return "low"
    if price <= 1.194593: return "mid"
    if price <= 1.446645: return "high"
    return "vhigh"

def trade_features(t):
    bd = str(t[fIdx['buy_date']] or "")
    mm = bd[4:6] if len(bd) >= 6 else ""
    dd = int(bd[6:8]) if len(bd) >= 8 else 0
    sig = str(t[fIdx['signal']] or "") if fIdx['signal'] is not None else ""
    wd = weekday(bd)
    bpb = buyprice_bin(t[fIdx['buy_price']]) if fIdx['buy_price'] is not None else ""
    key = '|'.join([str(t[fIdx['signal_date']]), str(t[fIdx['index_id']]), sig,
                    bd, str(t[fIdx['etf_code']]), str(t[fIdx['sell_date']])])
    dim = DIMS.get(key, {})
    mktD = dim.get('mkt', "")
    ratD = dim.get('rating', "")
    ts = t[fIdx['track_score']] if fIdx['track_score'] is not None and t[fIdx['track_score']] is not None else 999
    etfD = str(t[fIdx['track_tier']] or "") if fIdx['track_tier'] is not None else ""
    q = math.ceil(int(mm) / 3) if mm else 0
    return {'mm': mm, 'dd': dd, 'sig': sig, 'wd': wd, 'bpb': bpb, 'mktD': mktD,
            'ratD': ratD, 'ts': ts, 'etfD': etfD, 'q': q, 'bd': bd}

# ---------- toggle predicates (replicate _kellyPassesFadeFilters) ----------
def passes_fade(t, F):
    bd = str(t[fIdx['buy_date']] or "")
    sig = str(t[fIdx['signal']] or "") if fIdx['signal'] is not None else ""
    if F.get('excludeAux') and sig == "buy_aux":
        return False
    if F.get('marketTiming') and fIdx['market_state'] is not None and t[fIdx['market_state']] is not True:
        return False
    if F.get('excludeMonth') and len(bd) >= 6:
        mm_ = bd[4:6]
        if mm_ in ("03", "05"):
            return False
    if F.get('excludeRatingLow') and fIdx['rating'] is not None and t[fIdx['rating']] == "low":
        return False
    if F.get('excludeAuxCross') and sig == "buy_aux" and len(bd) >= 6:
        m = bd[4:6]
        if m in ("03", "05"):
            return False
    if F.get('excludeSpecialBear') and sig == "buy_special" and fIdx['market_state'] is not None and t[fIdx['market_state']] is False:
        return False

    # month mask (replicate _kellyMonthMask + _kellyActiveMonthMask)
    month_mask = {
        'a5NovMidSpecial': 1 << 10, 'a45NovMidLateSpecial': 1 << 10,
        'n1MarTueHigh': 1 << 2, 'n2NovSpecialIndustry': 1 << 10, 'r8PureNonMay': (1 << 2) | (1 << 10),
        'n3NovSpecialMon': 1 << 10, 'n4AMay': 1 << 4, 'r7MayReinforced': (1 << 4) | (1 << 2) | (1 << 10),
        'n5MayVlow': 1 << 4, 'n6MidMay': 1 << 4, 'r10May6NonMay': (1 << 4) | (1 << 2) | (1 << 10),
        'v4cSimple': 1 << 2, 'v4b': 1 << 4,
        'greedy7': (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5),
        'v4d': 1 << 11, 'v4j': 1 << 4, 'v4i': 1 << 4,
        'greedy10': (1 << 4) | (1 << 10) | (1 << 2) | (1 << 0) | (1 << 3) | (1 << 5) | (1 << 11),
        'v4f': 1 << 5, 'v4g': (1 << 0) | (1 << 1) | (1 << 2), 'v4m': 1 << 8, 'v4k': 1 << 0,
        'greedy15': (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 8) | (1 << 10) | (1 << 11),
        'janMidRating': 1 << 0, 'janMidSpecial': 1 << 0,
    }
    active = [k for k, v in F.items() if v and k in month_mask]
    mm_on = 0
    for k in active:
        mm_on |= month_mask[k]

    v3on = any(F.get(k) for k in ['n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay','r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay'])
    v4on = any(F.get(k) for k in ['greedy7','greedy10','greedy15','v4cSimple','v4b','v4d','v4j','v4i','v4f','v4g','v4m','v4k'])
    r3on = any(F.get(k) for k in ['a5NovMidSpecial','a45NovMidLateSpecial'])
    jan_on = any(F.get(k) for k in ['janMidRating','janMidSpecial'])
    if v3on or v4on or r3on or jan_on:
        mm_ = bd[4:6] if len(bd) >= 6 else ""
        mm_int = int(mm_) if mm_ else 0
        if mm_int and not (mm_on & (1 << (mm_int - 1))):
            return True  # 月门控: 不在任何活跃toggle月集合内, 直接通过
        f = trade_features(t)
        mm3, dd3, sig3, wd3, bpb3 = f['mm'], f['dd'], f['sig'], f['wd'], f['bpb']
        mktD3, ratD3, ts3, etfD3, q3 = f['mktD'], f['ratD'], f['ts'], f['etfD'], f['q']
        if v3on:
            if F.get('n1MarTueHigh') and mm3 == "03" and wd3 == 2 and bpb3 == "high": return False
            if F.get('n2NovSpecialIndustry') and sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry": return False
            if F.get('r8PureNonMay') and ((mm3 == "03" and wd3 == 2 and bpb3 == "high") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or (sig3 == "buy_special" and mm3 == "11" and wd3 == 0)): return False
            if F.get('n3NovSpecialMon') and sig3 == "buy_special" and mm3 == "11" and wd3 == 0: return False
            if F.get('n4AMay') and mktD3 == "a" and mm3 == "05": return False
            if F.get('r7MayReinforced') and ((mktD3 == "a" and mm3 == "05") or (ratD3 == "mid" and mm3 == "05") or (mm3 == "05" and bpb3 == "vlow") or (mm3 == "03" and wd3 == 2 and bpb3 == "high") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or (sig3 == "buy_special" and mm3 == "11" and wd3 == 0)): return False
            if F.get('n5MayVlow') and mm3 == "05" and bpb3 == "vlow": return False
            if F.get('n6MidMay') and ratD3 == "mid" and mm3 == "05": return False
            if F.get('r10May6NonMay') and (mm3 == "05" or (mm3 == "03" and wd3 == 2 and bpb3 == "high") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or (sig3 == "buy_special" and mm3 == "11" and wd3 == 0) or (sig3 == "buy_special" and mm3 == "11" and bpb3 == "low") or (sig3 == "buy_special" and mm3 == "03" and mktD3 == "industry") or (mm3 == "03" and wd3 == 2 and sig3 == "buy_aux")): return False
        if v4on:
            if F.get('v4cSimple') and mm3 == "03" and wd3 == 2 and sig3 == "buy_aux": return False
            if F.get('v4b') and mktD3 == "a" and mm3 == "05" and sig3 == "buy_special" and etfD3 == "related": return False
            if F.get('greedy7') and (
                (sig3 == "buy_special" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "03") or (sig3 == "buy_aux" and mm3 == "01") or
                (q3 == 2 and bpb3 == "vlow" and sig3 == "buy_aux" and mktD3 == "concept") or
                (sig3 == "buy" and mm3 == "01") or (mm3 == "03" and wd3 == 2 and mktD3 == "concept" and ratD3 == "low")): return False
            if F.get('v4d') and mm3 == "12" and wd3 == 1 and sig3 == "buy_aux" and ts3 < 50: return False
            if F.get('v4j') and mm3 == "05" and bpb3 == "vlow" and sig3 == "buy_special": return False
            if F.get('v4i') and sig3 == "buy_special" and mm3 == "05" and mktD3 == "concept" and wd3 == 0: return False
            if F.get('greedy10') and (
                (sig3 == "buy_special" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "03") or (sig3 == "buy_aux" and mm3 == "01") or
                (q3 == 2 and bpb3 == "vlow" and sig3 == "buy_aux" and mktD3 == "concept") or
                (sig3 == "buy" and mm3 == "01") or (mm3 == "03" and wd3 == 2 and mktD3 == "concept" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "12" and ts3 < 50) or (mm3 == "06" and bpb3 == "vlow" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "05")): return False
            if F.get('v4f') and sig3 == "buy" and mm3 == "06" and wd3 == 2 and etfD3 == "related": return False
            if F.get('v4g') and mktD3 == "global" and q3 == 1 and sig3 == "buy_aux" and ratD3 == "low": return False
            if F.get('v4m') and sig3 == "buy_special" and mm3 == "09" and wd3 == 2: return False
            if F.get('v4k') and sig3 == "buy" and mm3 == "01" and bpb3 == "high": return False
            if F.get('greedy15') and (
                (sig3 == "buy_special" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "03") or (sig3 == "buy_aux" and mm3 == "01") or
                (q3 == 2 and bpb3 == "vlow" and sig3 == "buy_aux" and mktD3 == "concept") or
                (sig3 == "buy" and mm3 == "01") or (mm3 == "03" and wd3 == 2 and mktD3 == "concept" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "12" and ts3 < 50) or (mm3 == "06" and bpb3 == "vlow" and ratD3 == "low") or
                (sig3 == "buy_aux" and mm3 == "05") or (sig3 == "buy_special" and mm3 == "11" and mktD3 == "industry") or
                (mm3 == "04" and wd3 == 1 and mktD3 == "concept" and ts3 < 50) or
                (mktD3 == "global" and q3 == 1 and sig3 == "buy_aux" and ratD3 == "low") or
                (mm3 == "01" and bpb3 == "low" and sig3 == "buy_special" and mktD3 == "concept") or
                (sig3 == "buy_special" and mm3 == "09" and wd3 == 2)): return False
        if r3on:
            if F.get('a5NovMidSpecial') and sig3 == "buy_special" and mm3 == "11" and dd3 >= 11 and dd3 <= 20: return False
            if F.get('a45NovMidLateSpecial') and sig3 == "buy_special" and mm3 == "11" and dd3 >= 11: return False
        if jan_on:
            if F.get('janMidRating') and mm3 == "01" and dd3 >= 11 and dd3 <= 20 and ratD3 == "mid": return False
            if F.get('janMidSpecial') and sig3 == "buy_special" and mm3 == "01" and dd3 >= 11 and dd3 <= 20: return False
    return True

# ---------- stats (replicate _kellyComputeStats) ----------
def _compute_kelly(winRate, plRatio):
    p = winRate; q = 1 - p; b = plRatio if (plRatio and plRatio > 0) else 0
    fStar = (p - q / b) if b > 0 else 0
    fStar = max(0, min(1, fStar))
    halfKelly = fStar / 2 * 100
    halfKelly = max(0, min(90, halfKelly))
    tier = "保守" if halfKelly < 30 else ("均衡" if halfKelly < 60 else "激进")
    return round(fStar * 10000) / 10000, round(halfKelly * 100) / 100, tier

def _date_diff_days(d1, d2):
    try:
        dd1 = datetime.strptime(d1, "%Y%m%d"); dd2 = datetime.strptime(d2, "%Y%m%d")
        return max(int((dd2 - dd1).total_seconds() / 86400), 0)
    except (ValueError, TypeError):
        return 0

def _years_from_trades(trades):
    if not trades:
        return 1.0
    dates = [t[2] for t in trades]
    dMin = min(dates); dMax = max(dates)
    days = _date_diff_days(dMin, dMax)
    return max(days / 365.25, 1.0 / 365.25)

def _max_concurrent(trades):
    if not trades:
        return 0
    SENTINEL = "99999999"
    deltas = {}; dates = []
    for bd, sd, profit in trades:
        if bd not in deltas: deltas[bd] = {'b': 0, 's': 0}; dates.append(bd)
        deltas[bd]['b'] += 1
        sd = sd or SENTINEL
        if sd not in deltas: deltas[sd] = {'b': 0, 's': 0}; dates.append(sd)
        deltas[sd]['s'] += 1
    dates.sort()
    cur = 0; maxConc = 0
    for dt in dates:
        cur += deltas[dt]['b']
        if cur > maxConc: maxConc = cur
        cur -= deltas[dt]['s']
    return maxConc

def _max_drawdown(trades, buy_amount):
    if not trades:
        return {'abs': 0, 'pct': 0}
    srt = sorted(trades, key=lambda x: x[3] or "99999999")
    cum = 0; peak = 0; maxDd = 0
    for _pr, _rp, _bd, sd, _hd in srt:
        cum += _pr
        if cum > peak: peak = cum
        dd = peak - cum
        if dd > maxDd: maxDd = dd
    total_invest = len(trades) * buy_amount
    pct = maxDd / total_invest * 100 if total_invest > 0 else 0
    return {'abs': round(maxDd * 10000) / 10000, 'pct': round(pct * 10000) / 10000}

def _annualized(returnPctMaxHolding, periodKey, trades):
    r = returnPctMaxHolding / 100
    if r <= -1:
        return 0
    if periodKey == "y1": return round(returnPctMaxHolding * 10000) / 10000
    if periodKey == "y3": return round((math.pow(1 + r, 1 / 3) - 1) * 100 * 10000) / 10000
    if periodKey == "y5": return round((math.pow(1 + r, 1 / 5) - 1) * 100 * 10000) / 10000
    if periodKey == "y10": return round((math.pow(1 + r, 1 / 10) - 1) * 100 * 10000) / 10000
    years = _years_from_trades(trades)
    if years <= 0: return round(returnPctMaxHolding * 10000) / 10000
    return round((math.pow(1 + r, 1 / years) - 1) * 100 * 10000) / 10000

def compute_stats(trades_, period_key, buy_amount):
    """trades_: list of (profit, return_pct, buy_date, sell_date, hold_days)."""
    n = len(trades_)
    if n == 0:
        return {'n': 0, 'win_rate': 0, 'pl_ratio': None, 'mean_return': 0, 'total_return': 0,
                'avg_hold_days': 0, 'kelly_f': 0, 'half_kelly': 0, 'kelly_tier': "保守",
                'max_single_win': 0, 'max_single_loss': 0, 'win_streak_max': 0, 'lose_streak_max': 0,
                'total_invest': 0, 'total_profit': 0, 'total_return_pct': 0, 'max_concurrent': 0,
                'max_concurrent_capital': 0, 'return_pct_max_holding': 0, 'annualized_return': 0,
                'sharpe': 0, 'max_drawdown': 0, 'max_drawdown_pct': 0, 'calmar': 0,
                'holding_count': 0, 'holding_capital': 0, 'win_count': 0, 'lose_count': 0, 'total_fee_cost': 0}
    wins = [t for t in trades_ if t[0] > 0]
    losses = [t for t in trades_ if t[0] <= 0]
    winCount = len(wins); loseCount = len(losses); winRate = winCount / n
    avgWin = sum(t[1] for t in wins) / winCount if winCount else 0
    avgLossAbs = abs(sum(t[1] for t in losses) / loseCount) if loseCount else 0
    if loseCount > 0 and avgLossAbs > 0:
        plRatio = avgWin / avgLossAbs
    elif winCount > 0 and loseCount == 0:
        plRatio = 999.0
    else:
        plRatio = None
    meanReturn = sum(t[1] for t in trades_) / n
    totalReturn = sum(t[0] for t in trades_) / buy_amount * 100
    avgHold = sum(t[4] for t in trades_) / n
    kelly_f, half_kelly, tier = _compute_kelly(winRate, plRatio)
    maxWin = max(t[1] for t in trades_)
    maxLoss = min(t[1] for t in trades_)
    srt = sorted(trades_, key=lambda t: t[2])
    winStreak = loseStreak = maxWinStreak = maxLoseStreak = 0
    for t in srt:
        if t[0] > 0:
            winStreak += 1; loseStreak = 0; maxWinStreak = max(maxWinStreak, winStreak)
        else:
            loseStreak += 1; winStreak = 0; maxLoseStreak = max(maxLoseStreak, loseStreak)
    totalInvest = n * buy_amount
    totalProfit = round(sum(t[0] for t in trades_) * 10000) / 10000
    totalReturnPct = round(totalProfit / totalInvest * 100 * 10000) / 10000 if totalInvest > 0 else 0
    maxConc = _max_concurrent([(t[2], t[3], t[0]) for t in trades_])
    maxConcurrentCapital = maxConc * buy_amount
    returnPctMaxHolding = round(totalProfit / maxConcurrentCapital * 100 * 10000) / 10000 if maxConcurrentCapital > 0 else 0
    annualized = _annualized(returnPctMaxHolding, period_key, trades_)
    returns = [t[1] for t in trades_]
    sharpe = 0
    if n > 1:
        mean = sum(returns) / n
        var = sum((x - mean) ** 2 for x in returns) / (n - 1)
        std = math.sqrt(var)
        sharpe = round(mean / std * 10000) / 10000 if std > 0 else 0
    dd = _max_drawdown(trades_, buy_amount)
    calmar = round(annualized / dd['pct'] * 10000) / 10000 if dd['pct'] > 0 else 0
    holdingCount = len([t for t in trades_ if not t[3]])
    return {
        'n': n, 'win_count': winCount, 'lose_count': loseCount, 'win_rate': round(winRate * 10000) / 10000,
        'pl_ratio': round(plRatio * 100) / 100 if plRatio is not None else None,
        'mean_return': round(meanReturn * 10000) / 10000, 'total_return': round(totalReturn * 10000) / 10000,
        'avg_hold_days': round(avgHold * 100) / 100, 'kelly_f': kelly_f, 'half_kelly': half_kelly, 'kelly_tier': tier,
        'max_single_win': round(maxWin * 10000) / 10000, 'max_single_loss': round(maxLoss * 10000) / 10000,
        'win_streak_max': maxWinStreak, 'lose_streak_max': maxLoseStreak,
        'total_invest': totalInvest, 'total_profit': totalProfit, 'total_return_pct': totalReturnPct,
        'max_concurrent': maxConc, 'max_concurrent_capital': maxConcurrentCapital,
        'return_pct_max_holding': returnPctMaxHolding, 'annualized_return': annualized, 'sharpe': sharpe,
        'max_drawdown': dd['abs'], 'max_drawdown_pct': dd['pct'], 'calmar': calmar,
        'holding_count': holdingCount, 'holding_capital': holdingCount * buy_amount,
    }

# ---------- helpers ----------
def filter_trades(all_trades, F):
    """all_trades: list of trade arrays. Returns filtered list."""
    return [t for t in all_trades if passes_fade(t, F)]

def to_row(t):
    profit = t[fIdx['profit']]
    return (profit, t[fIdx['return_pct']], str(t[fIdx['buy_date']] or ""),
            str(t[fIdx['sell_date']] or ""), t[fIdx['hold_days']] or 0)

def full_signal_trades(mode):
    """all signals fused (dedup): rating_high+mid+low for a mode (non-overlapping partition)."""
    out = []
    for qk in ['rating_high', 'rating_mid', 'rating_low']:
        out.extend(quads[qk][mode])
    return out

ALL_MODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']

# default filters (all false = baseline)
def empty_filters():
    return {k: False for k in ['excludeAux', 'marketTiming', 'excludeMonth', 'excludeRatingLow',
                               'excludeAuxCross', 'excludeSpecialBear',
                               'n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon',
                               'n4AMay','r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay',
                               'greedy7','greedy10','greedy15','v4cSimple','v4b','v4d','v4j','v4i',
                               'v4f','v4g','v4m','v4k','a5NovMidSpecial','a45NovMidLateSpecial',
                               'janMidRating','janMidSpecial']}

LIVE4 = {'excludeAux': True, 'marketTiming': True, 'excludeMonth': True, 'excludeRatingLow': True}
# 4组合全开 = yearEnd(n2,n3,v4d) ∪ stableCore(r8) ∪ maxLossCut(greedy15) ∪ janAdjust(J1,J2)
COMBO_ALL = dict(LIVE4)
COMBO_ALL.update({'n2NovSpecialIndustry': True, 'n3NovSpecialMon': True, 'v4d': True,
                  'r8PureNonMay': True, 'greedy15': True, 'janMidRating': True, 'janMidSpecial': True})

# 各组合 standalone (仅组合成员, 不开 live4)
COMBO_STANDALONE = {
    'yearEnd': {'n2NovSpecialIndustry': True, 'n3NovSpecialMon': True, 'v4d': True},
    'stableCore': {'r8PureNonMay': True},
    'maxLossCut': {'greedy15': True},
    'janAdjust': {'janMidRating': True, 'janMidSpecial': True},
}

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'A'
    F = empty_filters()
    trades = full_signal_trades(mode)
    print('mode', mode, 'all-signal trades:', len(trades))

    # 口径自验: 与 docs 基准对比 (全数据 = 无过滤)
    rows = [to_row(t) for t in trades]
    s = compute_stats(rows, 'all', BUY_AMOUNT)
    print('baseline all: n=%d 净=%+.0f 胜率=%.1f%% 盈亏比=%s 年化=%.2f%%' % (s['n'], s['total_profit'], s['win_rate']*100, s['pl_ratio'], s['annualized_return']))

    # 自验 live4
    ft = filter_trades(trades, LIVE4)
    rows = [to_row(t) for t in ft]
    s = compute_stats(rows, 'all', BUY_AMOUNT)
    print('live4 all: n=%d 净=%+.0f' % (s['n'], s['total_profit']))

    # 自验 combo all
    ft = filter_trades(trades, COMBO_ALL)
    rows = [to_row(t) for t in ft]
    s = compute_stats(rows, 'all', BUY_AMOUNT)
    print('combo_all(4组合全开): n=%d 净=%+.0f' % (s['n'], s['total_profit']))
