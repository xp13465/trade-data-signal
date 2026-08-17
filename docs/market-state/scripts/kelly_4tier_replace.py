# -*- coding: utf-8 -*-
"""四档 vs MA60 二进制: 替换 excludeSpecialBear 对比 + 重叠度分析"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap

exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'kelly_4tier_main.py')).read().split("if __name__")[0])

BASE8 = dict(AI_MACRO)
BASE8_EXCL = set(K2)

def compute2(filters, exclude_keys, periods=('all',)):
    rec = {m: oeng._mode_recomputed(m, filters, exclude_keys) for m in MODES}
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

def dump_table(name, res, base, out):
    out.append(f"### {name}")
    out.append(f"{'模式':<4} {'默认净利':>10} {'叠加净利':>10} {'Δ净利':>9} {'默认收益':>8} {'叠加收益':>8} {'Δ收益':>7} {'Δ笔数':>6}")
    for m in MODES:
        b = base['all'][m]; s = res['all'][m]
        d = s['total_profit'] - b['total_profit']
        dr = s['return_pct_max_holding'] - b['return_pct_max_holding']
        out.append(f"{m:<4} {b['total_profit']:>+10,.0f} {s['total_profit']:>+10,.0f} {d:>+9,.0f} {b['return_pct_max_holding']:>7.2f}% {s['return_pct_max_holding']:>7.2f}% {dr:>+6.2f}pp {s['n']-b['n']:>+6}")
    out.append("")

if __name__ == '__main__':
    out = []
    # 基线(8键, excludeSpecialBear=MA60二进制 on)
    base = compute2(BASE8, BASE8_EXCL)
    print(f"[基线] G b0 = {base['all']['G']['total_profit']:+,.2f}")
    out.append("## 替换测试: 四档(年线MA200锚) vs 现 excludeSpecialBear(MA60 二进制)")
    out.append("")

    # 各变体: 关掉 excludeSpecialBear, 用四档版本替代
    # R1: 熊市·主跌+下降期 × buy_special × A股
    # R1b: 熊市·主跌 × buy_special × A股
    # R1c: 下降期 × buy_special × A股
    variants = [
        ("R1_四档熊下降替代exBear", ("熊市·主跌","下降期")),
        ("R1b_四档熊主跌替代exBear", ("熊市·主跌",)),
        ("R1c_四档仅下降期替代exBear", ("下降期",)),
    ]
    for name, states in variants:
        f = dict(BASE8); f['excludeSpecialBear'] = False
        excl = state_excl(states, ("buy_special",), A_STOCK)
        r = compute2(f, BASE8_EXCL | excl)
        dump_table(name, r, base, out)
        print(name, "替换剔除n=", len(excl))
        for m in ('A','F','G','H','I'):
            d = r['all'][m]['total_profit'] - base['all'][m]['total_profit']
            print(f"   {m}: {d:+,.0f}")

    # 重叠度分析: excludeSpecialBear(MA60) 与 四档 的 buy_special×A股 集合
    print("\n## 重叠度: 现excludeSpecialBear(MA60熊) vs 四档(熊市·主跌+下降期) 对 buy_special×A股")
    set_ma60 = mk_excl(lambda a: a['sig']=='buy_special' and a['mkt'] in A_STOCK and a['s60']=='熊')
    set_4bad = mk_excl(lambda a: a['sig']=='buy_special' and a['mkt'] in A_STOCK and a['s4'] in ('熊市·主跌','下降期'))
    set_4main = mk_excl(lambda a: a['sig']=='buy_special' and a['mkt'] in A_STOCK and a['s4']=='熊市·主跌')
    set_4down = mk_excl(lambda a: a['sig']=='buy_special' and a['mkt'] in A_STOCK and a['s4']=='下降期')
    print(f"  excludeSpecialBear(MA60熊) 剔除 buy_special×A股: n={len(set_ma60)}")
    print(f"  四档(熊市·主跌+下降期) 剔除 buy_special×A股: n={len(set_4bad)}")
    print(f"    - 熊市·主跌: n={len(set_4main)}, 下降期: n={len(set_4down)}")
    inter = set_ma60 & set_4bad
    only_ma60 = set_ma60 - set_4bad   # MA60剔但四档不剔(四档放行的, 即 MA60 误杀?)
    only_4bad = set_4bad - set_ma60   # 四档剔但MA60不剔(四档多剔的)
    print(f"  交集: {len(inter)}")
    print(f"  仅MA60剔(四档放行): {len(only_ma60)}")
    print(f"  仅四档剔(MA60放行): {len(only_4bad)}")
    # 仅MA60剔 的 四档状态分布
    from collections import Counter
    c_only60 = Counter(); c_only4 = Counter()
    for bk in only_ma60:
        # 找对应交易的属性
        for mk in MODES:
            for t in eng._all_by_mode[mk]:
                if eng.base_key(t) == bk:
                    c_only60[attr_of(t)['s4']] += 1
                    break
    for bk in only_4bad:
        for mk in MODES:
            for t in eng._all_by_mode[mk]:
                if eng.base_key(t) == bk:
                    c_only4[attr_of(t)['s60']] += 1
                    break
    print(f"  仅MA60剔 的 四档状态分布(MA60误杀区): {dict(c_only60)}")
    print(f"  仅四档剔 的 MA60状态分布(四档多剔区): {dict(c_only4)}")
    # 误杀区与多剔区的盈亏(每笔1万原始 profit)
    def net_of(keys):
        tot = 0.0; n = 0
        seen = set()
        for mk in MODES:
            for t in eng._all_by_mode[mk]:
                bk = eng.base_key(t)
                if bk in keys and bk not in seen:
                    seen.add(bk)
                    tot += t[fi['profit']]; n += 1
        return tot, n
    net_only60, n_only60 = net_of(only_ma60)
    net_only4, n_only4 = net_of(only_4bad)
    print(f"  仅MA60剔(四档放行) 的净利(每笔1万原始): {net_only60:+,.0f} (n={n_only60})  <- MA60多剔的\"误杀\"")
    print(f"  仅四档剔(MA60放行) 的净利(每笔1万原始): {net_only4:+,.0f} (n={n_only4})  <- 四档多剔的\"新增降亏\"")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data','results_4tier_replace.json'),'w') as f:
        json.dump({'replace': {}, 'overlap': {'ma60_n': len(set_ma60), 'four_n': len(set_4bad), 'inter': len(inter), 'only_ma60': len(only_ma60), 'only_4bad': len(only_4bad)}}, f, ensure_ascii=False, indent=1)
