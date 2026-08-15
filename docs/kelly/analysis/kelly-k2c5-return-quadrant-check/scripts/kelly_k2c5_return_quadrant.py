# -*- coding: utf-8 -*-
"""K2C5 港股追涨剔除 · 两维度校验脚本 (2026-08-15)
目的: 补 K2C5(港股追涨剔除)的两个校验维度, 用数据说话校验用户手动观察:
  ① 全模式收益率维度: 9 模式(A-I)K2C5 剔除前/后的「净利 + 峰值资金收益率」all 周期 Δ 表
     —— 校验用户判断「除 G 外的其他玩法, 无论净利还是收益率都利大于弊」
  ② 16 象限卡片对比: 16 象限卡(评级3+ETF4+信号类型4+指数大类5)剔除前/后各自「最终盈亏 + 收益率」all 周期 Δ 表
     —— 校验用户「各象限卡片手动粗看也是盈利巨多」
口径: v1.0.0 推荐最优组合(§5.4): AI宏4+3+1 + 每日资金池等分 + K=1
      + G 用 13万 P≤3d「先卖年轻仓」(b0 保守 / b1 乐观双口径) + H=满仓不买@7万 + I=满仓不买@15万 + A-F=每日池+top-K
      K2C5 剔除键 = signal∈{buy_special,buy_backup} × 市场=港股(mkt=hk), 159 基笔
      收益率口径 = 峰值资金收益率 = 最终盈亏 / 峰值同时持仓资金 × 100(对齐前端 _renderSigKellyCard 的 return_pct_max_holding)
输入: static-site/data/signal_kelly_trades.json (2026-08-15 21:14 批)
依赖: 同目录 kelly_engine.py / kelly_opg_engine.py(副本, 原版 docs/kelly/analysis/scripts/quadrant_mining/)
输出: data/kelly-k2c5-return-quadrant.json (维度1 全模式净利+收益率Δ + 维度2 16象限卡片对比 + 正负统计)
复现: python3 kelly_k2c5_return_quadrant.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO, BUY_AMOUNT
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', 'data', 'kelly-k2c5-return-quadrant.json')

# 16 象限键(与前端 data.quadrants 顺序一致)
QUADS = ['rating_high', 'rating_mid', 'rating_low',
         'etf_strong', 'etf_related', 'etf_approx', 'etf_has_track',
         'sig_main', 'sig_aux', 'sig_special', 'sig_backup',
         'mkt_a', 'mkt_hk', 'mkt_global', 'mkt_industry', 'mkt_concept']
QUAD_LABEL = {
    'rating_high': '评级-高', 'rating_mid': '评级-中', 'rating_low': '评级-低',
    'etf_strong': 'ETF-强跟踪', 'etf_related': 'ETF-相关', 'etf_approx': 'ETF-近似', 'etf_has_track': 'ETF-有跟踪',
    'sig_main': '信号-主关注', 'sig_aux': '信号-辅关注', 'sig_special': '信号-追关注', 'sig_backup': '信号-备关注',
    'mkt_a': '市场-A股', 'mkt_hk': '市场-港股', 'mkt_global': '市场-全球', 'mkt_industry': '市场-行业', 'mkt_concept': '市场-概念',
}
G_CAP = 130000
H_CAP, I_CAP = 70000, 150000


def recompute_quad_mode(eng, qk, mode, exclude_keys, ctx):
    """象限 qk 的 mode 交易 -> 应用 AI宏4+3+1 过滤 + exclude_keys + 全局 positionCap(K=1) + 每日池金额, 返回 recomputed 列表"""
    fi = eng.fIdx
    kept, day_counts = ctx
    arr = eng._quad_trades.get(qk, {}).get(mode, [])
    out = []
    for t in arr:
        if not eng.passes_fade(t, AI_MACRO):
            continue
        if exclude_keys and eng.base_key(t) in exclude_keys:
            continue
        if kept is not None and eng.base_key(t) not in kept:
            continue
        amt = BUY_AMOUNT / day_counts.get(str(t[fi['signal_date']]), 1) if day_counts else BUY_AMOUNT
        p, rp, fee = eng.recompute(t, amt)
        out.append({'profit': p, 'return_pct': rp, 'fee_cost': fee,
                    'buy_date': str(t[fi['buy_date']] or ''), 'sell_date': str(t[fi['sell_date']] or ''),
                    'hold_days': t[fi['hold_days']] or 0, 'amount': amt})
    return out


def mode_stats(mode, rec, g_model='b0'):
    """套模式可操作口径: A-F 裸 / G=P3d13万(b0或b1) / H=hold7万 / I=hold15万. 返回 (stats, peak)"""
    if mode == 'G':
        kt, peak = p3d_cap(rec, G_CAP, model=g_model)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp * 10000) / 10000,
                    return_pct_max_holding=round(tp / peak * 100 * 10000) / 10000 if peak > 0 else 0,
                    max_concurrent_capital=peak), peak
    if mode in ('H', 'I'):
        cap = H_CAP if mode == 'H' else I_CAP
        kt, peak = hold_cap(rec, cap)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), total_profit=round(tp * 10000) / 10000,
                    return_pct_max_holding=round(tp / peak * 100 * 10000) / 10000 if peak > 0 else 0,
                    max_concurrent_capital=peak), peak
    tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount'])
              for k in rec]
    st = eng.compute_stats(tuples)
    return st, st['max_concurrent_capital']


def build_ctx(eng, exclude_keys):
    """全局 positionCap 上下文(kept 集合 + 日资金池计数), 基线与剔除各算一次复用"""
    pool = eng.collect_base_pool(AI_MACRO, exclude_keys)
    kept = eng._kept_keys(pool, AI_MACRO.get('positionCapK', 1)) if AI_MACRO.get('positionCap') else None
    day_counts = eng._day_counts(kept) if kept else {}
    return kept, day_counts


def quad_card(eng, qk, exclude_keys, ctx, g_model='b0'):
    """单象限卡: 9 模式各自 最终盈亏+收益率+n. 返回 {mode: stats}"""
    card = {}
    for m in MODES:
        rec = recompute_quad_mode(eng, qk, m, exclude_keys, ctx)
        st, _ = mode_stats(m, rec, g_model)
        card[m] = {'n': st['n'], 'net': round(st['total_profit'] * 10000) / 10000,
                   'ret_pct': round(st['return_pct_max_holding'] * 10000) / 10000,
                   'peak': st['max_concurrent_capital']}
    return card


if __name__ == '__main__':
    oeng = OpgEngine(load_trades())
    eng = oeng.eng
    fi = eng.fIdx
    k2 = oeng.excl_keys(lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk')
    print('K2C5 剔除基笔 n =', len(k2), flush=True)

    # ===== 维度 0: 全局基线校验(对账 reconcile 报告) =====
    base_global = oeng.compute_opg(AI_MACRO)
    # G b1 全局
    rec_g = oeng._mode_recomputed('G', AI_MACRO, None)
    st_g_b1, _ = mode_stats('G', rec_g, 'b1')
    base_global['all']['G_b1'] = {'n': st_g_b1['n'], 'total_profit': st_g_b1['total_profit'],
                                  'return_pct_max_holding': st_g_b1['return_pct_max_holding'],
                                  'max_concurrent_capital': st_g_b1['max_concurrent_capital']}
    print('全局基线 G b0=+%.2f (%.2f%%)  G b1=+%.2f (%.2f%%)' % (
        base_global['all']['G']['total_profit'], base_global['all']['G']['return_pct_max_holding'],
        st_g_b1['total_profit'], st_g_b1['return_pct_max_holding']), flush=True)
    # 断言复现 reconcile: G b0 all ≈ +203,594
    assert abs(base_global['all']['G']['total_profit'] - 203594.19) < 5, 'G b0 基线未复现'

    # ===== 维度 1: 9 模式净利 + 峰值资金收益率 Δ(all 周期, G 双口径) =====
    excl_global = oeng.compute_opg(AI_MACRO, exclude_keys=k2)
    rec_g_x = oeng._mode_recomputed('G', AI_MACRO, k2)
    st_g_b1_x, _ = mode_stats('G', rec_g_x, 'b1')
    excl_global['all']['G_b1'] = {'n': st_g_b1_x['n'], 'total_profit': st_g_b1_x['total_profit'],
                                  'return_pct_max_holding': st_g_b1_x['return_pct_max_holding'],
                                  'max_concurrent_capital': st_g_b1_x['max_concurrent_capital']}
    dim1 = {}
    for m in MODES:
        b, e = base_global['all'][m], excl_global['all'][m]
        dim1[m] = {
            'baseline_net': round(b['total_profit'] * 10000) / 10000,
            'baseline_ret_pct': round(b['return_pct_max_holding'] * 10000) / 10000,
            'baseline_n': b['n'], 'baseline_peak': b['max_concurrent_capital'],
            'excl_net': round(e['total_profit'] * 10000) / 10000,
            'excl_ret_pct': round(e['return_pct_max_holding'] * 10000) / 10000,
            'excl_n': e['n'], 'excl_peak': e['max_concurrent_capital'],
            'delta_net': round((e['total_profit'] - b['total_profit']) * 10000) / 10000,
            'delta_ret_pct': round((e['return_pct_max_holding'] - b['return_pct_max_holding']) * 10000) / 10000,
        }
    # G 双口径单独列(b0 已在上面, b1 单独)
    dim1['G'] = {
        'b0': dim1['G'],  # 上面 G 即 b0
        'b1': {
            'baseline_net': round(st_g_b1['total_profit'] * 10000) / 10000,
            'baseline_ret_pct': round(st_g_b1['return_pct_max_holding'] * 10000) / 10000,
            'baseline_n': st_g_b1['n'], 'baseline_peak': st_g_b1['max_concurrent_capital'],
            'excl_net': round(st_g_b1_x['total_profit'] * 10000) / 10000,
            'excl_ret_pct': round(st_g_b1_x['return_pct_max_holding'] * 10000) / 10000,
            'excl_n': st_g_b1_x['n'], 'excl_peak': st_g_b1_x['max_concurrent_capital'],
            'delta_net': round((st_g_b1_x['total_profit'] - st_g_b1['total_profit']) * 10000) / 10000,
            'delta_ret_pct': round((st_g_b1_x['return_pct_max_holding'] - st_g_b1['return_pct_max_holding']) * 10000) / 10000,
        },
    }
    print('维度1 done.', flush=True)

    # ===== 维度 2: 16 象限卡片对比(G 双口径) =====
    ctx_base = build_ctx(eng, None)
    ctx_excl = build_ctx(eng, k2)
    dim2 = {}
    for qk in QUADS:
        cb0 = quad_card(eng, qk, None, ctx_base, 'b0')
        cb1 = quad_card(eng, qk, None, ctx_base, 'b1')
        ce0 = quad_card(eng, qk, k2, ctx_excl, 'b0')
        ce1 = quad_card(eng, qk, k2, ctx_excl, 'b1')
        card = {'baseline_b0': {}, 'baseline_b1': {}, 'excl_b0': {}, 'excl_b1': {}, 'delta_b0': {}, 'delta_b1': {}}
        for m in MODES:
            card['baseline_b0'][m] = cb0[m]
            card['baseline_b1'][m] = cb1[m]
            card['excl_b0'][m] = ce0[m]
            card['excl_b1'][m] = ce1[m]
            card['delta_b0'][m] = {'delta_net': round((ce0[m]['net'] - cb0[m]['net']) * 10000) / 10000,
                                   'delta_ret_pct': round((ce0[m]['ret_pct'] - cb0[m]['ret_pct']) * 10000) / 10000,
                                   'n_base': cb0[m]['n'], 'n_excl': ce0[m]['n']}
            card['delta_b1'][m] = {'delta_net': round((ce1[m]['net'] - cb1[m]['net']) * 10000) / 10000,
                                   'delta_ret_pct': round((ce1[m]['ret_pct'] - cb1[m]['ret_pct']) * 10000) / 10000,
                                   'n_base': cb1[m]['n'], 'n_excl': ce1[m]['n']}
        dim2[qk] = card
    print('维度2 done.', flush=True)

    # ===== 汇总统计 =====
    def _pos_neg(stats_by_quad_mode):
        pos = neg = zero = tot = 0
        for qk in QUADS:
            for m in MODES:
                v = stats_by_quad_mode[qk][m]
                tot += 1
                if v > 0.5: pos += 1
                elif v < -0.5: neg += 1
                else: zero += 1
        return {'pos': pos, 'neg': neg, 'zero': zero, 'total': tot}

    # 维度2 汇总(以 b0 口径为主统计, b1 附加)
    b0_net_base = {qk: {m: dim2[qk]['baseline_b0'][m]['net'] for m in MODES} for qk in QUADS}
    b0_net_excl = {qk: {m: dim2[qk]['excl_b0'][m]['net'] for m in MODES} for qk in QUADS}
    b0_ret_base = {qk: {m: dim2[qk]['baseline_b0'][m]['ret_pct'] for m in MODES} for qk in QUADS}
    b0_ret_excl = {qk: {m: dim2[qk]['excl_b0'][m]['ret_pct'] for m in MODES} for qk in QUADS}
    summary = {
        'dim1': dim1,
        'dim2_b0_net_posneg_baseline': _pos_neg(b0_net_base),
        'dim2_b0_net_posneg_excl': _pos_neg(b0_net_excl),
        'dim2_b0_ret_posneg_baseline': _pos_neg(b0_ret_base),
        'dim2_b0_ret_posneg_excl': _pos_neg(b0_ret_excl),
        'dim2_delta_direction_b0': {},
    }
    for qk in QUADS:
        up = down = same = 0
        for m in MODES:
            d = dim2[qk]['delta_b0'][m]['delta_net']
            if abs(d) < 0.5: same += 1
            elif d > 0: up += 1
            else: down += 1
        summary['dim2_delta_direction_b0'][qk] = {'up': up, 'down': down, 'same': same,
                                                   'sum_delta_net': round(sum(dim2[qk]['delta_b0'][m]['delta_net'] for m in MODES) * 10000) / 10000}
    # 除港股外方向
    nonhk = {qk: summary['dim2_delta_direction_b0'][qk] for qk in QUADS if qk != 'mkt_hk'}
    summary['dim2_nonhk_sum_delta_net'] = round(sum(v['sum_delta_net'] for v in nonhk.values()) * 10000) / 10000
    summary['dim2_nonhk_up_count'] = sum(v['up'] for v in nonhk.values())
    summary['dim2_nonhk_down_count'] = sum(v['down'] for v in nonhk.values())

    out = {
        'data_batch': load_trades().get('generated_at'),
        'basis': 'v1.0.0: AI宏4+3+1 + 每日池等分 + K=1 + G=13万P≤3d(b0/b1), H=满仓不买@7万, I=满仓不买@15万, A-F=每日池+top-K',
        'k2c5_excl_n': len(k2),
        'ret_caliber': '峰值资金收益率 = 最终盈亏 / 峰值同时持仓资金 × 100',
        'baseline_verify': {'G_b0_all': base_global['all']['G']['total_profit'],
                            'G_b1_all': st_g_b1['total_profit'],
                            'A_all': base_global['all']['A']['total_profit'],
                            'F_all': base_global['all']['F']['total_profit'],
                            'H_all': base_global['all']['H']['total_profit'],
                            'I_all': base_global['all']['I']['total_profit']},
        'dim1': dim1,
        'dim2': dim2,
        'summary': summary,
    }
    with open(OUT, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('written:', OUT)

    # ===== 打印摘要 =====
    print('\n===== 维度1: 9模式净利+收益率 Δ (all, G 双口径) =====')
    print(f'{"模式":<4} {"基线净利":>10} {"剔后净利":>10} {"Δ净利":>9} {"基线收益":>8} {"剔后收益":>8} {"Δ收益":>7}')
    for m in MODES:
        d = dim1[m] if m != 'G' else dim1[m]['b0']
        print(f'{m:<4} {d["baseline_net"]:>+10,.0f} {d["excl_net"]:>+10,.0f} {d["delta_net"]:>+9,.0f} '
              f'{d["baseline_ret_pct"]:>7.2f}% {d["excl_ret_pct"]:>7.2f}% {d["delta_ret_pct"]:>+6.2f}pp')
    d = dim1['G']['b1']
    print(f'G1 {d["baseline_net"]:>+10,.0f} {d["excl_net"]:>+10,.0f} {d["delta_net"]:>+9,.0f} '
          f'{d["baseline_ret_pct"]:>7.2f}% {d["excl_ret_pct"]:>7.2f}% {d["delta_ret_pct"]:>+6.2f}pp')

    print('\n===== 维度2: 16象限 净利正负统计(b0) =====')
    for key, name in [('dim2_b0_net_posneg_baseline', '基线'), ('dim2_b0_net_posneg_excl', '剔除后')]:
        s = summary[key]
        print(f'{name}: 正盈亏 {s["pos"]}/{s["total"]} 负 {s["neg"]} 零 {s["zero"]}')
    print('剔除Δ方向(净利,b0): 各象限 up/down/same + 象限Δ合计')
    for qk in QUADS:
        d = summary['dim2_delta_direction_b0'][qk]
        print(f'  {QUAD_LABEL[qk]:<10} up={d["up"]} down={d["down"]} same={d["same"]}  Δ净利合计={d["sum_delta_net"]:+,.0f}')
    print(f'除港股外 15 象限: up总={summary["dim2_nonhk_up_count"]} down总={summary["dim2_nonhk_down_count"]} Δ净利合计={summary["dim2_nonhk_sum_delta_net"]:+,.0f}')
