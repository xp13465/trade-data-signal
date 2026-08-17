# -*- coding: utf-8 -*-
"""维度2: 状态作为仓位/建议维度(调仓位, 不剔除)"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap, BUY_AMOUNT

exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'kelly_4tier_main.py')).read().split("if __name__")[0])

BASE8 = dict(AI_MACRO)
BASE8_EXCL = set(K2)

def compute_pos(filters, exclude_keys, state_factor, periods=('all',)):
    """按状态缩放仓位(基于原始交易, 缩放 amount/profit/fee)"""
    rec = {}
    for m in MODES:
        arr = eng._all_by_mode[m]
        pool = eng.collect_base_pool(filters, exclude_keys)
        kept = eng._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
        day_counts = eng._day_counts(kept) if kept else {}
        out = []
        for t in arr:
            if not eng.passes_fade(t, filters): continue
            if exclude_keys and eng.base_key(t) in exclude_keys: continue
            if kept is not None and eng.base_key(t) not in kept: continue
            a = attr_of(t)
            f = state_factor.get(a['s4'], 1.0)
            if f <= 0: continue
            amt = BUY_AMOUNT / day_counts.get(str(t[fi['signal_date']]), 1) if day_counts else BUY_AMOUNT
            amt = round(amt * f, 2)
            p, rp, fee = eng.recompute(t, amt)
            out.append({'profit': p, 'return_pct': rp, 'fee_cost': fee,
                        'buy_date': str(t[fi['buy_date']] or ''), 'sell_date': str(t[fi['sell_date']] or ''),
                        'hold_days': t[fi['hold_days']] or 0, 'amount': amt})
        rec[m] = out
    cutoffs = eng.period_cutoffs
    res = {}
    for pk in periods:
        cutoff = cutoffs.get(pk, '0')
        res[pk] = {}
        for m in MODES:
            rp = [t for t in rec[m] if cutoff == '0' or t['buy_date'] >= cutoff]
            if m == 'G':
                kt, peak = p3d_cap(rp, 130000, model='b0')
                tp = sum(k['profit'] for k in kt)
                res[pk][m] = dict(n=len(kt), total_profit=round(tp*10000)/10000,
                                  return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak > 0 else 0,
                                  max_concurrent_capital=peak)
            elif m in ('H','I'):
                cap = 70000 if m=='H' else 150000
                kt, peak = hold_cap(rp, cap)
                tp = sum(k['profit'] for k in kt)
                res[pk][m] = dict(n=len(kt), total_profit=round(tp*10000)/10000,
                                  return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak > 0 else 0,
                                  max_concurrent_capital=peak)
            else:
                tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in rp]
                res[pk][m] = eng.compute_stats(tuples)
    return res

POS_PLANS = {
    "D2a_熊下降5折":  {"熊市·主跌": 0.5, "下降期": 0.5},
    "D2b_熊下降3折":  {"熊市·主跌": 0.3, "下降期": 0.3},
    "D2c_熊下降0折":  {"熊市·主跌": 0.0, "下降期": 0.0},
    "D2d_熊主跌3折_下降5折": {"熊市·主跌": 0.3, "下降期": 0.5},
    "D2e_黄金区1.2倍": {"牛市·主升": 1.2, "上升期": 1.2},
    "D2f_熊下降3折+黄金1.2": {"熊市·主跌": 0.3, "下降期": 0.3, "牛市·主升": 1.2, "上升期": 1.2},
    "D2g_熊下降5折+黄金1.2": {"熊市·主跌": 0.5, "下降期": 0.5, "牛市·主升": 1.2, "上升期": 1.2},
}

if __name__ == '__main__':
    base = compute(BASE8, BASE8_EXCL)
    print(f"[基线] G b0 = {base['all']['G']['total_profit']:+,.2f}")
    hdr = f"{'方案':<20} {'A净利':>9} {'A收益':>7} {'F净利':>9} {'F收益':>7} {'G净利b0':>9} {'G收益':>7} {'H净利':>9} {'I净利':>9} {'G峰持仓':>7}"
    print(hdr)
    a = base['all']['A']; f = base['all']['F']; g = base['all']['G']; h = base['all']['H']; i = base['all']['I']
    print(f"{'基线(全1.0)':<20} {a['total_profit']:>+9,.0f} {a['return_pct_max_holding']:>6.2f}% {f['total_profit']:>+9,.0f} {f['return_pct_max_holding']:>6.2f}% {g['total_profit']:>+9,.0f} {g['return_pct_max_holding']:>6.2f}% {h['total_profit']:>+9,.0f} {i['total_profit']:>+9,.0f} {g['max_concurrent_capital']/10000:>6.1f}万")
    for name, sf in POS_PLANS.items():
        r = compute_pos(BASE8, BASE8_EXCL, sf)
        a = r['all']['A']; f = r['all']['F']; g = r['all']['G']; h = r['all']['H']; i = r['all']['I']
        print(f"{name:<20} {a['total_profit']:>+9,.0f} {a['return_pct_max_holding']:>6.2f}% {f['total_profit']:>+9,.0f} {f['return_pct_max_holding']:>6.2f}% {g['total_profit']:>+9,.0f} {g['return_pct_max_holding']:>6.2f}% {h['total_profit']:>+9,.0f} {i['total_profit']:>+9,.0f} {g['max_concurrent_capital']/10000:>6.1f}万")
