#!/usr/bin/env python3
# 【基建】每日资金池等分口径 (2026-08-12)
# 用途: 每日总投资恒10000, 当日N信号每笔=10000/N; compute_scaled 统一计算 stats(net/ret/peak/dd/half_kelly)
# 注意: 顶层有打印(import时输出), 供调试参考

"""每日资金池等分口径: 每日总投资额恒 10000, 当日 N 信号则每笔 = 10000/N
对比旧口径(每笔1万): 旧口径最大持仓 1218*10000 = 1218万(1218倍杠杆), 不现实
复用 kelly_posfilter_backtest 的基笔/分组/排序管线
"""
import sys, math
from collections import defaultdict
from datetime import datetime
sys.path.insert(0, '/tmp')
from kelly_combo_advice_analysis import (to_row, passes_fade, fIdx, empty_filters, LIVE4, BUY_AMOUNT)
from kelly_posfilter_backtest import base_signals, get_by_date, base_key, sort_key_score
from kelly_ksens import keep_topk, full_sort_key

G_BASE = base_signals('G')
DAILY = 10000.0

def _date_diff_days(d1, d2):
    try:
        dd1 = datetime.strptime(d1, "%Y%m%d"); dd2 = datetime.strptime(d2, "%Y%m%d")
        return max(int((dd2 - dd1).total_seconds() / 86400), 0)
    except (ValueError, TypeError):
        return 0

def _years_from(dates):
    if not dates:
        return 1.0
    dMin = min(dates); dMax = max(dates)
    days = _date_diff_days(dMin, dMax)
    return max(days / 365.25, 1.0 / 365.25)

def _kelly(winRate, plRatio):
    p = winRate; q = 1 - p; b = plRatio if (plRatio and plRatio > 0) else 0
    fStar = (p - q / b) if b > 0 else 0
    fStar = max(0, min(1, fStar))
    halfKelly = max(0, min(90, fStar / 2 * 100))
    return round(halfKelly * 100) / 100

def _peak_capital(items):
    """items: (profit, rpct, buy_date, sell_date, hold, amount). 峰值持仓资本(元)"""
    SENTINEL = "99999999"
    ev = defaultdict(int)
    for t in items:
        bd = t[2] or SENTINEL
        sd = t[3] or SENTINEL
        ev[bd] += t[5]
        ev[sd] -= t[5]
    peak = 0; cur = 0
    for dt in sorted(ev):
        cur += ev[dt]
        peak = max(peak, cur)
    return peak

def compute_scaled(items):
    """items: list of (profit, return_pct, buy_date, sell_date, hold_days, amount)"""
    n = len(items)
    if n == 0:
        return {'n':0,'net':0,'win':0,'pl':None,'annualized':0,'peak_capital':0,'ret':0,'dd_pct':0,'half_kelly':0,'total_invest':0,'n_days':0}
    wins = [t for t in items if t[0] > 0]
    losses = [t for t in items if t[0] <= 0]
    wc = len(wins); lc = len(losses); winRate = wc/n
    avgWin = sum(t[1] for t in wins)/wc if wc else 0
    avgLossAbs = abs(sum(t[1] for t in losses)/lc) if lc else 0
    plRatio = avgWin/avgLossAbs if (lc>0 and avgLossAbs>0) else (999.0 if (wc>0 and lc==0) else None)
    totalInvest = sum(t[5] for t in items)
    totalProfit = sum(t[0] for t in items)
    totalReturnPct = totalProfit/totalInvest*100 if totalInvest>0 else 0
    peak = _peak_capital(items)
    ret = totalProfit/peak*100 if peak>0 else 0
    dates = [t[2] for t in items]
    years = _years_from(dates)
    annualized = (math.pow(1+ret/100, 1/years)-1)*100 if years>0 and ret > -100 else 0
    # max drawdown (cumulative profit by sell date)
    srt = sorted(items, key=lambda x: x[3] or "99999999")
    cum=0; peakc=0; maxDd=0
    for t in srt:
        cum += t[0]
        peakc = max(peakc, cum)
        maxDd = max(maxDd, peakc-cum)
    dd_pct = maxDd/totalInvest*100 if totalInvest>0 else 0
    return {'n':n,'net':totalProfit,'win':winRate*100,'pl':round(plRatio,2) if plRatio else None,
            'annualized':round(annualized,2),'peak_capital':peak,'ret':round(ret,2),
            'dd_pct':round(dd_pct,2),'half_kelly':_kelly(winRate,plRatio),'total_invest':totalInvest,
            'n_days':len(set(t[2] for t in items))}

def daily_pool_items(keep_keys=None, amount_mode='all'):
    """按 signal_date 分组. 每笔金额 = 10000/当日信号数(买全部) 或 10000/K(topK)"""
    items = []
    for sd, rows in get_by_date('G').items():
        if keep_keys is None:
            day_rows = rows
            k = len(rows)
        else:
            day_rows = [r for r in rows if base_key(r) in keep_keys]
            k = len(keep_topk_by_date_cache[sd]) if False else None
        if not day_rows:
            continue
        if amount_mode == 'all':
            amt = DAILY / len(rows)      # 买全部: 当日全部信号等分
        else:
            amt = DAILY / len(day_rows)  # topK: 当日保留K个等分
        for t in day_rows:
            base_profit = t[fIdx['profit']] or 0
            rpct = t[fIdx['return_pct']] or 0
            profit_scaled = base_profit * (amt / BUY_AMOUNT)
            items.append((profit_scaled, rpct, str(t[fIdx['buy_date']] or ''),
                          str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items

keep_topk_by_date_cache = {}
def topk_keys(k, keyf=full_sort_key):
    """返回 (kept_keys_set, 每日期望K)"""
    kept = []
    day_k = {}
    for sd, rows in get_by_date('G').items():
        srt = sorted(rows, key=keyf)[:k]
        day_k[sd] = len(srt)
        kept.extend(srt)
    return set(base_key(t) for t in kept), day_k

def topk_items(k):
    kk, day_k = topk_keys(k)
    items = []
    for sd, rows in get_by_date('G').items():
        day_rows = [r for r in rows if base_key(r) in kk]
        if not day_rows:
            continue
        amt = DAILY / len(day_rows)
        for t in day_rows:
            base_profit = t[fIdx['profit']] or 0
            rpct = t[fIdx['return_pct']] or 0
            profit_scaled = base_profit * (amt / BUY_AMOUNT)
            items.append((profit_scaled, rpct, str(t[fIdx['buy_date']] or ''),
                          str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items

def combo4_items(items):
    """在 items 上叠加 COMBO4 过滤(保留原金额口径: 仍按当日保留数等分)"""
    # 重新生成: 对每个信号日期, 只保留通过 COMBO4 的信号, 金额=10000/通过数
    out = []
    for sd, rows in get_by_date('G').items():
        day_rows = [r for r in rows if passes_fade(r, COMBO4)]
        if not day_rows:
            continue
        amt = DAILY / len(day_rows)
        for t in day_rows:
            base_profit = t[fIdx['profit']] or 0
            rpct = t[fIdx['return_pct']] or 0
            profit_scaled = base_profit * (amt / BUY_AMOUNT)
            out.append((profit_scaled, rpct, str(t[fIdx['buy_date']] or ''),
                        str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return out

# COMBO4 定义
from kelly_posfilter_backtest import COMBO4
print('=== ① 每日资金池等分口径: 每日池买全部 (每笔=10000/当日信号数) ===')
items_all = daily_pool_items(amount_mode='all')
s = compute_scaled(items_all)
print('n=%d 净=+%.0f 胜率=%.1f%% 盈亏比=%s 年化=%.2f%% 最大持仓(元)=%.0f 收益率=%.2f%% 回撤=%.2f%% 半凯利=%.1f%% 总投资=%.0f' % (
    s['n'], s['net'], s['win'], s['pl'], s['annualized'], s['peak_capital'], s['ret'], s['dd_pct'], s['half_kelly'], s['total_invest']))
print('  (对比旧口径 P0: 每笔1万 最大持仓 1218万 / 收益率32.27%)')

print()
print('=== ② 每日资金池 + top-K (每笔=10000/K) ===')
print('%-5s %6s %12s %6s %7s %8s %10s %8s %8s %8s' % ('K','n','净盈亏','胜率%','盈亏比','年化%','最大持仓(元)','收益率%','回撤%','半凯利%'))
pool_stats = {}
for k in [1,2,3,4,5]:
    items = topk_items(k)
    s = compute_scaled(items)
    pool_stats[k] = s
    print('K=%d  %6d %+11.0f %5.1f %7s %8.2f %10.0f %8.2f %8.2f %8.1f' % (
        k, s['n'], s['net'], s['win'], s['pl'] if s['pl'] else '-', s['annualized'],
        s['peak_capital'], s['ret'], s['dd_pct'], s['half_kelly']))

print()
print('=== ③ 每日池 + topK + COMBO4 (叠加4组合) ===')
print('%-5s %18s %6s %12s %6s %10s %8s %8s' % ('K','场景','n','净盈亏','胜率%','最大持仓(元)','收益率%','Δ vs 单独'))
combo_all_items = combo4_items(items_all)
sc = compute_scaled(combo_all_items)
print('%-5s %-18s %6d %+11.0f %5.1f %10.0f %8.2f %s' % ('-','每日池买全部+COMBO4', sc['n'], sc['net'], sc['win'], sc['peak_capital'], sc['ret'], ''))
for k in [1,2,3,4,5]:
    kk, _ = topk_keys(k)
    out = []
    for sd, rows in get_by_date('G').items():
        day_rows = [r for r in rows if base_key(r) in kk and passes_fade(r, COMBO4)]
        if not day_rows: continue
        amt = DAILY / len(day_rows)
        for t in day_rows:
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            out.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    s2 = compute_scaled(out)
    base = pool_stats[k]
    dret = s2['ret'] - base['ret']
    print('K=%d  +COMBO4       %6d %+11.0f %5.1f %10.0f %8.2f %+7.2f' % (k, s2['n'], s2['net'], s2['win'], s2['peak_capital'], s2['ret'], dret))

print()
print('=== ④ 每日池 + topK + live4 (警告) ===')
for k in [1,2,3,4]:
    kk, _ = topk_keys(k)
    out = []
    for sd, rows in get_by_date('G').items():
        day_rows = [r for r in rows if base_key(r) in kk and passes_fade(r, LIVE4)]
        if not day_rows: continue
        amt = DAILY / len(day_rows)
        for t in day_rows:
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            out.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    s2 = compute_scaled(out)
    print('K=%d +live4: n=%d 净=%+.0f 收益率=%.2f%% 最大持仓=%.0f' % (k, s2['n'], s2['net'], s2['ret'], s2['peak_capital']))

print()
print('=== ⑤ 每日池 + topK + 最优降亏toggle (a45NovMidLateSpecial) ===')
for k in [1,2,3,4]:
    kk, _ = topk_keys(k)
    F = empty_filters(); F['a45NovMidLateSpecial'] = True
    out = []
    for sd, rows in get_by_date('G').items():
        day_rows = [r for r in rows if base_key(r) in kk and passes_fade(r, F)]
        if not day_rows: continue
        amt = DAILY / len(day_rows)
        for t in day_rows:
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            out.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    s2 = compute_scaled(out)
    base = pool_stats[k]
    print('K=%d +A45: n=%d 净=%+.0f (Δ%+.0f) 收益率=%.2f%% (Δ%+.2f) 最大持仓=%.0f' % (
        k, s2['n'], s2['net'], s2['net']-base['net'], s2['ret'], s2['ret']-base['ret'], s2['peak_capital']))

