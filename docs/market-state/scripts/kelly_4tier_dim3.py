# -*- coding: utf-8 -*-
"""维度3: 按年分解(基线 vs V4 剔buy_special vs R1 替换exBear)"""
import sys, os, json
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap, BUY_AMOUNT

exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'kelly_4tier_main.py')).read().split("if __name__")[0])

BASE8 = dict(AI_MACRO)
BASE8_EXCL = set(K2)

def mode_recomputed_all(m, filters, exclude_keys):
    arr = eng._all_by_mode[m]
    pool = eng.collect_base_pool(filters, exclude_keys)
    kept = eng._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
    day_counts = eng._day_counts(kept) if kept else {}
    out = []
    for t in arr:
        if not eng.passes_fade(t, filters): continue
        if exclude_keys and eng.base_key(t) in exclude_keys: continue
        if kept is not None and eng.base_key(t) not in kept: continue
        amt = BUY_AMOUNT / day_counts.get(str(t[fi['signal_date']]), 1) if day_counts else BUY_AMOUNT
        p, rp, fee = eng.recompute(t, amt)
        out.append({'profit': p, 'return_pct': rp, 'fee_cost': fee,
                    'buy_date': str(t[fi['buy_date']] or ''), 'sell_date': str(t[fi['sell_date']] or ''),
                    'hold_days': t[fi['hold_days']] or 0, 'amount': amt})
    return out

def yearly_profit(mode, filters, exclude_keys, g_model='b0'):
    """按 buy_date 年份分组统计各模式净利"""
    rec = mode_recomputed_all(mode, filters, exclude_keys)
    by_year = defaultdict(list)
    for t in rec:
        y = t['buy_date'][:4] if t['buy_date'] else '?'
        by_year[y].append(t)
    res = {}
    for y, rp in sorted(by_year.items()):
        if mode == 'G':
            kt, peak = p3d_cap(rp, 130000, model=g_model)
            tp = sum(k['profit'] for k in kt)
            res[y] = dict(n=len(kt), profit=round(tp*10000)/10000, peak=peak)
        elif mode in ('H','I'):
            cap = 70000 if mode=='H' else 150000
            kt, peak = hold_cap(rp, cap)
            tp = sum(k['profit'] for k in kt)
            res[y] = dict(n=len(kt), profit=round(tp*10000)/10000, peak=peak)
        else:
            tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in rp]
            st = eng.compute_stats(tuples)
            res[y] = dict(n=st['n'], profit=st['total_profit'], peak=st['max_concurrent_capital'])
    return res

def yearly_table(mode, label, configs, out):
    out.append(f"### {label} (模式 {mode})")
    years = sorted({y for cfg in configs for y in cfg['data']})
    # 列 = 各配置
    out.append(f"{'年份':<6} " + " ".join(f"{cfg['name']:>12}" for cfg in configs))
    for y in years:
        row = [f"{y:<6}"]
        for cfg in configs:
            d = cfg['data'].get(y)
            row.append(f"{d['profit']:>+12,.0f}" if d else " " * 12)
        out.append(" ".join(row))
    # 合计
    row = [f"{'合计':<6}"]
    for cfg in configs:
        tot = sum(d['profit'] for d in cfg['data'].values())
        row.append(f"{tot:>+12,.0f}")
    out.append(" ".join(row))
    out.append("")

if __name__ == '__main__':
    # 配置: 基线 / V4(剔buy_special) / V4_all(全市场剔buy_special) / R1(替换exBear)
    cfg_base = {'name': '基线', 'filters': BASE8, 'excl': BASE8_EXCL}
    v4 = state_excl(('熊市·主跌','下降期'), ('buy_special',), A_STOCK)
    cfg_v4 = {'name': 'V4剔追', 'filters': BASE8, 'excl': BASE8_EXCL | v4}
    v4all = state_excl(('熊市·主跌','下降期'), ('buy_special',), None)
    cfg_v4all = {'name': 'V4全市场', 'filters': BASE8, 'excl': BASE8_EXCL | v4all}
    r1excl = state_excl(('熊市·主跌','下降期'), ('buy_special',), A_STOCK)
    f_r1 = dict(BASE8); f_r1['excludeSpecialBear'] = False
    cfg_r1 = {'name': 'R1替换exBear', 'filters': f_r1, 'excl': BASE8_EXCL | r1excl}

    out = []
    for mode in ('A', 'F', 'G', 'H', 'I'):
        configs = []
        for cfg in (cfg_base, cfg_v4, cfg_v4all, cfg_r1):
            d = yearly_profit(mode, cfg['filters'], cfg['excl'])
            configs.append({'name': cfg['name'], 'data': d})
        yearly_table(mode, '维度3 按年分解', configs, out)
    print('\n'.join(out))
