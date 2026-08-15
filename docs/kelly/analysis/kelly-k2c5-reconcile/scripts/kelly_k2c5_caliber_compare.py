# -*- coding: utf-8 -*-
"""K2C5 前端 vs 报告口径对账脚本 (2026-08-15)
目的: 对账「前端 K2C5 toggle 显示」vs「报告 §7 剔除边际」的 G 模式分歧。
发现: 前端 GIH on 显示 = b1 乐观口径(强平按持有时间线性实现利润), 报告 §7 = b0 保守口径(强平记 0 利)。
口径A「简单剔除」: 仅排除 K2C5 子群交易, 不重跑 P3d 强平仿真(G/H/I 也用裸 stats) — 排除(≠前端)
口径B_b0「重跑 P3d b0」: 报告 §7 权威口径(G p3d13万 b0) — G Δ -2,256
口径B_b1「重跑 P3d b1」: 前端 GIH on 显示口径(G p3d13万 b1) — G Δ +11,755 ≈ 页面 +11,779
口径: v1.0.0 基准(AI宏4+3+1 + 每日池等分 + K=1 + G 用 13万 P≤3d), 与 kelly_opg_engine.py 同源。
输入: static-site/data/signal_kelly_trades.json (2026-08-15 21:14 批)
依赖: 同目录 kelly_engine.py/kelly_opg_engine.py(副本, 原版在 docs/kelly/analysis/scripts/quadrant_mining/)
输出: data/k2c5-caliber-compare.json (基线+三口径 K2C5 剔除Δ 9模式 all+y1)
复现: python3 kelly_k2c5_caliber_compare.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'k2c5-caliber-compare.json')

def mode_stats_raw(mode, recomputed, eng):
    """口径A: 全部模式(含 G/H/I)用裸 compute_stats, 不套 P3d/hold 仿真"""
    tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in recomputed]
    st = eng.compute_stats(tuples)
    return st, st['max_concurrent_capital']

def opg_mode_stats_b0(mode, recomputed, eng):
    """口径B_b0: G 用 p3d13万 b0, H/I 用 hold. 报告 §7 权威"""
    if mode == 'G':
        kt, peak = p3d_cap(recomputed, 130000, model='b0')
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp*10000)/10000,
                    return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak>0 else 0,
                    max_concurrent_capital=peak), peak
    if mode in ('H','I'):
        cap = 70000 if mode=='H' else 150000
        kt, peak = hold_cap(recomputed, cap)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp*10000)/10000,
                    return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak>0 else 0,
                    max_concurrent_capital=peak), peak
    tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in recomputed]
    st = eng.compute_stats(tuples)
    return st, st['max_concurrent_capital']

def opg_mode_stats_b1(mode, recomputed, eng):
    """口径B_b1: G 用 p3d13万 b1(乐观), H/I 用 hold. 前端 GIH on 显示口径"""
    if mode == 'G':
        kt, peak = p3d_cap(recomputed, 130000, model='b1')
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp*10000)/10000,
                    return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak>0 else 0,
                    max_concurrent_capital=peak), peak
    if mode in ('H','I'):
        cap = 70000 if mode=='H' else 150000
        kt, peak = hold_cap(recomputed, cap)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp*10000)/10000,
                    return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak>0 else 0,
                    max_concurrent_capital=peak), peak
    tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in recomputed]
    st = eng.compute_stats(tuples)
    return st, st['max_concurrent_capital']

def compute(oeng, eng, stat_fn, exclude_keys=None):
    cutoffs = eng.period_cutoffs
    rec_by_mode = {m: oeng._mode_recomputed(m, AI_MACRO, exclude_keys) for m in MODES}
    res = {}
    for pk in ('all','y1'):
        cutoff = cutoffs.get(pk,'0')
        res[pk] = {}
        for m in MODES:
            rp = [t for t in rec_by_mode[m] if cutoff=='0' or t['buy_date']>=cutoff]
            st,_ = stat_fn(m, rp, eng)
            res[pk][m] = st['total_profit']
    return res

if __name__ == '__main__':
    oeng = OpgEngine(load_trades())
    eng = oeng.eng
    k2 = oeng.excl_keys(lambda a: a['sig'] in ('buy_special','buy_backup') and a['mkt']=='hk')

    out = {'data_batch': load_trades().get('generated_at'), 'k2c5_excl_n': len(k2), 'calibers': {}}
    for name, fn in [('A_simple_excl', mode_stats_raw), ('B_b0_report', opg_mode_stats_b0), ('B_b1_frontend', opg_mode_stats_b1)]:
        base = compute(oeng, eng, fn)
        excl = compute(oeng, eng, fn, k2)
        out['calibers'][name] = {}
        for pk in ('all','y1'):
            out['calibers'][name][pk] = {}
            for m in MODES:
                out['calibers'][name][pk][m] = {'baseline': round(base[pk][m],0), 'excl': round(excl[pk][m],0), 'delta': round(excl[pk][m]-base[pk][m],0)}
    with open(OUT, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("written:", OUT)
    print(json.dumps(out, ensure_ascii=False, indent=1))
