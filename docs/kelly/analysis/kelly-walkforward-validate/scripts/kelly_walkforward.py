#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凯利组合 Walk-forward 滚动验证(样本外, 2026-08-16)
目的: 用 t-1 段选 toggle、t 段验证, 模拟真实前向, 验证 v1.1.0 推荐最优组合(基础5+核心3 = 8键+1类)
      在样本外(不参与选择的年份)是否依然优于「选段最优组合」与「基线(无过滤)」。
方法口径:
  - 测试基准 = v1.1.0 推荐最优组合(§5.4): 基础4[excludeSpecialBear/n2NovSpecialIndustry/janMidRating/janMidSpecial]
    + 核心3[r7MayReinforced/excludeAuxCross/greedy15] + K2C5(剔除 signal∈{buy_special,buy_backup}×港股, 159基笔)
    + positionCap K1 每日池等分 + G 用 13万 P≤3d「先卖年轻仓」b0 / H 满仓不买@7万 / I 满仓不买@15万 / A-F 每日池+top-K
  - 分段口径: 段内 buy_date 年份 ∈ [y0,y1] 的交易才进入该段的 pool/kept/trades(模拟段内实际运行)
  - 选段选最优: 基础4 固定开, 核心3 三键 × K2C5 共 2^4=16 组合全扫, 按 9模式合计净利选最优
  - 验段评估: 选段最优 / v1.1.0 当前推荐(8键全开) / 基线(无toggle) 三者在验段的表现
  - 分年稳定性: 8键全开 与 leave-one-out(去r7/去aux/去g15/去k2)逐年 A 净利与 9模式合计边际
输入依赖: static-site/data/signal_kelly_trades.json (2026-08-16 08:51 批, buy_amount=10000, period_cutoffs.all=0)
输出: data/kelly-walkforward.json (全量结果)
复现: cd docs/kelly/analysis/kelly-walkforward-validate/scripts && python3 kelly_walkforward.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, BUY_AMOUNT
from kelly_opg_engine import OpgEngine, MODES, OPG_STRATS, p3d_cap, hold_cap

TRADES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../../../', 'static-site/data/signal_kelly_trades.json')
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/kelly-walkforward.json')

BASE4 = dict(excludeSpecialBear=True, n2NovSpecialIndustry=True, janMidRating=True, janMidSpecial=True)
CORE = ['r7MayReinforced', 'excludeAuxCross', 'greedy15']
CORE_SHORT = {'r7MayReinforced': 'r7', 'excludeAuxCross': 'aux', 'greedy15': 'g15'}
K2C5_PRED = lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk'

def mk_filters(core_keys):
    f = dict(BASE4, positionCap=True, positionCapK=1)
    for k in core_keys: f[k] = True
    return f

class WfEngine:
    """walk-forward 引擎: pool/kept 一次构建, 9模式复用(段内口径)"""
    def __init__(self, td):
        self.oeng = OpgEngine(td)
        self.eng = self.oeng.eng
        self.fi = self.eng.fIdx
        self.k2_keys = self.oeng.excl_keys(K2C5_PRED)

    def seg_compute(self, filters, exclude_keys, y0, y1):
        fi = self.fi
        eng = self.eng
        pool, seen = [], set()
        for rk in ('rating_high', 'rating_mid', 'rating_low'):
            for mk, arr in eng._quad_trades[rk].items():
                for t in arr:
                    if not eng.passes_fade(t, filters): continue
                    bk = eng.base_key(t)
                    if bk in seen: continue
                    if exclude_keys and bk in exclude_keys: continue
                    bd = str(t[fi['buy_date']] or '')
                    if not bd or len(bd) < 4: continue
                    y = int(bd[:4])
                    if y < y0 or y > y1: continue
                    seen.add(bk); pool.append(t)
        kept = eng._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
        day_counts = eng._day_counts(kept) if kept else {}
        res = {}
        for m in MODES:
            out = []
            for t in eng._all_by_mode[m]:
                if not eng.passes_fade(t, filters): continue
                if exclude_keys and eng.base_key(t) in exclude_keys: continue
                if kept is not None and eng.base_key(t) not in kept: continue
                bd = str(t[fi['buy_date']] or '')
                if not bd or len(bd) < 4: continue
                y = int(bd[:4])
                if y < y0 or y > y1: continue
                amt = BUY_AMOUNT / day_counts.get(str(t[fi['signal_date']]), 1) if day_counts else BUY_AMOUNT
                p, rp, fee = eng.recompute(t, amt)
                out.append({'profit': p, 'return_pct': rp, 'fee_cost': fee,
                            'buy_date': str(t[fi['buy_date']] or ''), 'sell_date': str(t[fi['sell_date']] or ''),
                            'hold_days': t[fi['hold_days']] or 0, 'amount': amt})
            if m in OPG_STRATS:
                kind, cap, model = OPG_STRATS[m]
                kt, peak = p3d_cap(out, cap, model) if kind == 'p3d' else hold_cap(out, cap)
                tp = sum(k['profit'] for k in kt)
                st = dict(n=len(kt), total_profit=round(tp * 10000) / 10000,
                          return_pct_max_holding=round(tp / peak * 100 * 10000) / 10000 if peak > 0 else 0,
                          max_concurrent_capital=peak, _peak=peak)
            else:
                tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in out]
                st0 = eng.compute_stats(tuples)
                st = dict(st0, _peak=st0['max_concurrent_capital'])
            res[m] = st
        return res

    def tot(self, res):
        return sum(res[m]['total_profit'] for m in MODES)

    def scan_select(self, y0, y1, metric='tot'):
        """选段 16 组合全扫, 按 metric 排序, 返回排序表"""
        table = []
        for mask in range(16):
            ck = [CORE[i] for i in range(3) if mask & (1 << i)]
            k2 = bool(mask & 8)
            f = mk_filters(ck)
            ex = self.k2_keys if k2 else None
            r = self.seg_compute(f, ex, y0, y1)
            table.append(dict(mask=mask, core_keys=ck, k2=k2, tot=self.tot(r), af=r['A']['total_profit'] + r['F']['total_profit'], res=r))
        table.sort(key=lambda x: -x[metric])
        return table


def run():
    td = load_trades(TRADES_PATH)
    wf = WfEngine(td)
    out = {}

    # ---- 0. 基线对账(断言) ----
    base_all = wf.seg_compute(mk_filters(CORE), wf.k2_keys, 2011, 2026)
    assert abs(wf.tot(base_all) - 904147) < 1000, f"基线对账失败: {wf.tot(base_all)}"
    out['baseline_all_8key'] = {m: {k: v for k, v in base_all[m].items() if k != '_peak'} for m in MODES}
    out['baseline_all_8key_tot'] = wf.tot(base_all)

    # ---- 1. 单次切分: 选 2011-2020 / 验 2021-2026 ----
    sel_table = wf.scan_select(2011, 2020)
    best_tot = sel_table[0]
    best_af = max(sel_table, key=lambda x: x['af'])
    seg = {
        'select_years': [2011, 2020], 'verify_years': [2021, 2026],
        'select_table_16': [{k: (v if k != 'res' else None) for k, v in row.items()} for row in sel_table],
        'best_by_tot': dict(mask=best_tot['mask'], core_keys=best_tot['core_keys'], k2=best_tot['k2'],
                            sel_tot=best_tot['tot'], sel_af=best_tot['af']),
        'best_by_af': dict(mask=best_af['mask'], core_keys=best_af['core_keys'], k2=best_af['k2'],
                           sel_tot=best_af['tot'], sel_af=best_af['af']),
    }
    # 验段评估: 8键全开 / 选段9模式最优 / 选段A+F最优 / 基线
    evals = [
        ('v110_8key', 'v1.1.0当前推荐(8键全开)', mk_filters(CORE), wf.k2_keys),
        ('sel_best_tot', '选段9模式最优', mk_filters(best_tot['core_keys']), wf.k2_keys if best_tot['k2'] else None),
        ('sel_best_af', '选段A+F最优', mk_filters(best_af['core_keys']), wf.k2_keys if best_af['k2'] else None),
        ('baseline', '基线(无toggle)', dict(positionCap=True, positionCapK=1), None),
    ]
    seg['verify'] = {}
    for key, name, f, ex in evals:
        vr = wf.seg_compute(f, ex, 2021, 2026)
        sr = wf.seg_compute(f, ex, 2011, 2020)
        seg['verify'][key] = dict(name=name,
                                  verify={m: {k: v for k, v in vr[m].items() if k != '_peak'} for m in MODES},
                                  verify_tot=wf.tot(vr),
                                  select={m: {k: v for k, v in sr[m].items() if k != '_peak'} for m in MODES},
                                  select_tot=wf.tot(sr),
                                  decay_A_ret=round(sr['A']['return_pct_max_holding'] - vr['A']['return_pct_max_holding'], 2))
    out['single_split'] = seg

    # ---- 2. 滚动扩展窗口 ----
    windows = [(2011, 2020, 2021, 2022), (2011, 2022, 2023, 2024), (2011, 2024, 2025, 2026)]
    out['rolling'] = []
    for sy0, sy1, vy0, vy1 in windows:
        tbl = wf.scan_select(sy0, sy1)
        best = tbl[0]
        sf = mk_filters(best['core_keys'])
        sex = wf.k2_keys if best['k2'] else None
        v_sel = wf.seg_compute(sf, sex, vy0, vy1)
        v_8 = wf.seg_compute(mk_filters(CORE), wf.k2_keys, vy0, vy1)
        v_base = wf.seg_compute(dict(positionCap=True, positionCapK=1), None, vy0, vy1)
        s_sel = wf.seg_compute(sf, sex, sy0, sy1)
        s_8 = wf.seg_compute(mk_filters(CORE), wf.k2_keys, sy0, sy1)
        mask_num = sum(1 << CORE.index(k) for k in best['core_keys']) + (8 if best['k2'] else 0)
        out['rolling'].append(dict(
            select_years=[sy0, sy1], verify_years=[vy0, vy1],
            sel_best=dict(mask=mask_num, core_keys=best['core_keys'], k2=best['k2'],
                          sel_tot=wf.tot(s_sel), sel_A_ret=s_sel['A']['return_pct_max_holding']),
            verify_sel_best=dict(tot=wf.tot(v_sel), A_ret=v_sel['A']['return_pct_max_holding'], A_n=v_sel['A']['n']),
            verify_8key=dict(tot=wf.tot(v_8), A_ret=v_8['A']['return_pct_max_holding'], A_n=v_8['A']['n']),
            verify_baseline=dict(tot=wf.tot(v_base), A_ret=v_base['A']['return_pct_max_holding'], A_n=v_base['A']['n']),
            select_8key=dict(tot=wf.tot(s_8), A_ret=s_8['A']['return_pct_max_holding']),
        ))

    # ---- 3. 分年稳定性 ----
    YEARS = list(range(2012, 2027))
    FULL = mk_filters(CORE)
    variants = {
        '去r7': (mk_filters(['excludeAuxCross', 'greedy15']), wf.k2_keys),
        '去aux': (mk_filters(['r7MayReinforced', 'greedy15']), wf.k2_keys),
        '去g15': (mk_filters(['r7MayReinforced', 'excludeAuxCross']), wf.k2_keys),
        '去k2': (mk_filters(CORE), None),
        '基线(无键)': (dict(positionCap=True, positionCapK=1), None),
    }
    yearly = {}
    for y in YEARS:
        yr = {'full': wf.seg_compute(FULL, wf.k2_keys, y, y)}
        for vn, (vf, vex) in variants.items():
            yr[vn] = wf.seg_compute(vf, vex, y, y)
        yearly[str(y)] = {k: {m: {kk: vv for kk, vv in v[m].items() if kk != '_peak'} for m in MODES} for k, v in yr.items()}
    out['yearly'] = yearly
    # 边际统计
    out['yearly_margin_stats'] = {}
    for vn in ['去r7', '去aux', '去g15', '去k2']:
        posA = sum(1 for y in YEARS if yearly[str(y)]['full']['A']['total_profit'] - yearly[str(y)][vn]['A']['total_profit'] > 0)
        negA = sum(1 for y in YEARS if yearly[str(y)]['full']['A']['total_profit'] - yearly[str(y)][vn]['A']['total_profit'] < 0)
        posT = sum(1 for y in YEARS if wf.tot(yearly[str(y)]['full']) - wf.tot(yearly[str(y)][vn]) > 0)
        negT = sum(1 for y in YEARS if wf.tot(yearly[str(y)]['full']) - wf.tot(yearly[str(y)][vn]) < 0)
        out['yearly_margin_stats'][vn] = dict(A_pos=posA, A_neg=negA, A_pos_ratio=round(posA / (posA + negA) * 100, 1),
                                              tot_pos=posT, tot_neg=negT, tot_pos_ratio=round(posT / (posT + negT) * 100, 1))

    out['meta'] = dict(data_batch=td.get('generated_at'), k2_base_trades=len(wf.k2_keys),
                       baseline_all_8key_tot=wf.tot(base_all))
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"✅ 完成, 结果落盘 {OUT_PATH}")
    print(f"   K2C5 基笔={len(wf.k2_keys)}, 8键全开 all 9模式合计={out['baseline_all_8key_tot']:+,.0f}")
    print(f"   单次切分: 选段9模式最优={out['single_split']['best_by_tot']['core_keys']}+{'k2' if out['single_split']['best_by_tot']['k2'] else 'no k2'}")
    for segrow in out['rolling']:
        b = segrow['sel_best']
        print(f"   滚动验段{segrow['verify_years'][0]}-{segrow['verify_years'][1]}: 选段最优={b['core_keys']}+{'k2' if b['k2'] else 'no k2'} | 验段8键={segrow['verify_8key']['tot']:+,.0f} 选段最优={segrow['verify_sel_best']['tot']:+,.0f} 基线={segrow['verify_baseline']['tot']:+,.0f}")

if __name__ == '__main__':
    run()
