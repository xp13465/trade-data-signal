# -*- coding: utf-8 -*-
"""mine27 G 模式交易方式全穷举 + 「买满躺平」极简手法量化(2026-08-23 主控令)。
目的:
  ①多了 AI 过滤后,G 的最佳交易方式是否变化(过滤 8 种 × 并发上限/资金档全穷举,全史+近1年双窗,净利+回撤双维);
  ②用户极简「买满躺平」手法 vs 现行推荐(v1.1.2 基准 G=13万 P≤3d「先卖年轻仓」b0 强平)损失多少、省多少操作。
  用户本意主口径=V2 回补型(有卖后有闲钱后才再关注买信号);V1 一轮型=附录对照(mission 补充令 2026-08-23)。
方法口径:
  - 引擎复用 mine25(sim_core 口径 1:1 前端模拟回测弹窗;K1 补位;每笔固定本金 PRIN=10000;
    E23 已证 K=1 时每笔1万 ≡ 每日池等分净利逐位相同)→ 资金档 N 万 = 并发上限 cap=N 笔(峰值占用≤N 万)。
  - 三手法全部参数化在同一重放层 replay3,不另写引擎:
      p3d现行 = 容量满时强平「≤3 日历天年轻仓中买日最早者」,无年轻仓则 FIFO 最老,b0 强平记 0 利
                (逻辑逐位对齐 quadrant_mining/kelly_opg_engine.p3d_cap ↔ 前端 lab.js _kellyAihlineP3dCap);
      v2回补  = 满仓跳过该日信号不买,自然卖出释放后可再买(=mine25 replay_cap 原样语义,自检断言等值);
      v1一轮  = 累计买入笔数达 cap 后永不再买,卖出照常、资金沉淀(附录对照)。
  - 过滤 8 种:RAW无过滤 / P0_8键 / P1_9键 / A_on9 / B_on9 / C_on9 / NEW14独立重构 / NEW18独立重构。
    NEW14/NEW18 用独立重构口径(原始模式池+黑名单,mode A 权威锚点 +122,648.33/+120,564.54);
    叠加口径(G 上叠 8 键池)另测作敏感性附表;键清单从 mine24_compare.json new_keys/new2_keys 程序化读取防手抄错。
锚点断言(必过才往下):
  mode A:P0 +66,530.38 / P1 +73,102.53 / A9vs9键 +46,007 / B9 +36,469 / C9 +34,011 /
         NEW14独立 +122,648.33 & mdd -4,178.01 / NEW18独立 +120,564.54 & mdd -4,083.63;
  G no-cap 交叉:P0/P1/A/B/C/NEW14叠 == mine24_compare.modes.G 权威(<0.5)6 断言。
输出:data/mine27_g_exhaustive_simplified.json
复现:python3 mine27_g_exhaustive_simplified.py
依赖:static-site/data/signal_kelly_trades.json(generated_at=2026-08-23 05:09)+ data/mine10_features.json +
     data/mine24_global_search.json + data/mine24_compare.json(权威交叉断言)。
关键口径一句话:G 模式池 × 8 过滤 × K1 补位 → 同一重放层跑 p3d/v2/v1 三手法 × cap{10,13,20,50,nocap}
              (每笔固定 1 万,资金档=cap×1 万)→ 已实现/未实现(b0 强平记 0 利)分列+操作计数+按年+压力窗+近 1 年窗。
"""
import os, sys, json, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, calc_row, base_key, PRIN
from mine18_detail import BEARS, FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2
import mine25_longline_operable as M25

OUT_PATH = os.path.join(BASE, 'data', 'mine27_g_exhaustive_simplified.json')
M24CMP = json.load(open(M25.M24CMP_PATH))
M25_NOCAP_G = M24CMP['modes']['G']

# 过滤 8 种(顺序即展示顺序)
FILTERS = ['RAW无过滤', 'P0_8键', 'P1_9键', 'A_on9', 'B_on9', 'C_on9', 'NEW14', 'NEW18']
CAPS = [10, 13, 20, 50]
METHODS = ['p3d现行13万P3d', 'v2回补极简', 'v1一轮型']
BEARS26 = list(BEARS) + [('2026年2-3月压力窗', '20260201', '20260331')]

FEATS = json.load(open(FEATS_PATH))
NEW14_KEYS = list(M24CMP['new_keys'])
NEW18_KEYS = list(M24CMP['new2_keys'])


def finish_pool(rows, fi):
    """同 M25 Part1 poolA 处理:追加 calc_row(pnl) 与排序键。"""
    R.IDX_PNL, R.IDX_SKEY = len(fi) + 3, len(fi) + 4
    RATING_RANK = {'high': 0, 'mid': 1, 'low': 2}
    SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in rows:
        t.append(calc_row(t, fi))
        ts = float(t[fi['track_score']]) if t[fi['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RATING_RANK.get(str(t[fi['rating']] or ''), 3),
                  SIG_RANK.get(str(t[fi['signal']] or ''), 9), str(t[fi['buy_date']] or '')))
    return rows


def pool_g_filtered(tr, fi):
    """8键过滤池(与 M25.prep_mode_local 同语义,但基于独立 build 防行对象共享突变)。"""
    rows = build_mode_pool(tr, fi, 'G')
    mm = active_month_mask(DEFAULT_FILTERS)
    mD, eD, rD = len(fi), len(fi) + 1, len(fi) + 2
    kept = [t for t in rows if passes_fade(t, fi, DEFAULT_FILTERS, mm, mD, eD, rD)]
    return finish_pool(kept, fi)


def cal_span(bd, sd):
    if not bd or not sd or sd < bd: return 0
    d1 = datetime.date(int(bd[:4]), int(bd[4:6]), int(bd[6:8]))
    d2 = datetime.date(int(sd[:4]), int(sd[4:6]), int(sd[6:8]))
    return max((d2 - d1).days, 0)


def replay3(day_sel, fi, cap=None, method='v2'):
    """统一重放层(三手法)。返回 dict(bought, forced, skipped, peak_n, n_natural_sell)。
    容量单位=笔数(cap×PRIN≈资金档预算);先删后加(自然卖出 sell_date<=当日 先释放)。"""
    open_map, bought, forced, skipped = {}, [], [], []
    victim_ids = set()
    total_buys, peak_n = 0, 0
    for sd in sorted(day_sel):
        for k in [k for k, v in open_map.items()
                  if str(v[fi['sell_date']] or '') and str(v[fi['sell_date']]) <= sd]:
            del open_map[k]
        t = day_sel[sd]
        is_p3d, is_v1 = method.startswith('p3d'), method.startswith('v1')
        if is_v1 and cap is not None and total_buys >= cap:
            skipped.append(t); continue
        if cap is not None and len(open_map) >= cap:
            if is_p3d:
                # 强平至能容纳当日 1 笔:p3d 选年轻仓(≤3 日历天)中买日最早,无年轻仓 FIFO 最老;b0 记 0 利
                while len(open_map) >= cap:
                    sel_k, sel_bd = None, None
                    for k, v in open_map.items():
                        bd = str(v[fi['buy_date']] or '')
                        if cal_span(bd, sd) <= 3 and (sel_bd is None or bd < sel_bd):
                            sel_k, sel_bd = k, bd
                    if sel_k is None:
                        for k, v in open_map.items():
                            bd = str(v[fi['buy_date']] or '')
                            if sel_bd is None or bd < sel_bd:
                                sel_k, sel_bd = k, bd
                    ft = open_map.pop(sel_k)
                    ftc = list(ft)  # 浅拷贝防突变共享行对象(同池多 run 复用)
                    ftc[R.IDX_PNL] = dict(ft[R.IDX_PNL], pnlYuan=0.0, pnlPct=0.0, forced=True,
                                          natural_sell_date=str(ft[fi['sell_date']] or ''),
                                          forced_day=sd)
                    forced.append(ftc)
                    victim_ids.add(id(ft))
            else:  # v2 / v1: 满仓跳过该日信号
                skipped.append(t); continue
        open_map[base_key(t, fi)] = t
        bought.append(t); total_buys += 1
        if len(open_map) > peak_n: peak_n = len(open_map)
    return dict(bought=bought, forced=forced, skipped=skipped, peak_n=peak_n, victim_ids=victim_ids)


def stats_ext(rp, fi, cap, budget_yuan, span_years, near_cut):
    idx = R.IDX_PNL
    bought, forced, skipped = rp['bought'], rp['forced'], rp['skipped']
    vid = rp['victim_ids']
    alive = [t for t in bought if id(t) not in vid]   # 被强平者不再参与任何盈亏聚合(b0 记 0 利已单列)
    real = [t for t in alive if str(t[fi['sell_date']] or '')]
    hold = [t for t in alive if not str(t[fi['sell_date']] or '')]
    r_pnl = sum(t[idx]['pnlYuan'] for t in real)
    u_pnl = sum(t[idx]['pnlYuan'] for t in hold)
    win = sum(1 for t in real if t[idx]['pnlYuan'] > 0)
    bys = {}
    for t in real:
        sd = str(t[fi['sell_date']])
        bys[sd] = bys.get(sd, 0.0) + t[idx]['pnlYuan']
    days = sorted(bys)
    mdd_real = M25.dd_of(days, bys)
    all_days = set(days) | {str(t[0]) for t in bought}
    last_day = max(all_days) if all_days else None
    bys_m = dict(bys)
    if last_day is not None and hold:
        bys_m[last_day] = bys_m.get(last_day, 0.0) + u_pnl
    mdd_merged = M25.dd_of(sorted(bys_m), bys_m)
    total = r_pnl + u_pnl
    out = dict(
        n_bought=len(bought), n_forced_liq=len(forced), n_skipped=len(skipped),
        n_natural_sell=len(real), n_holding_end=len(hold),
        realized_pnl=round(r_pnl, 2), unrealized_pnl=round(u_pnl, 2), total_merged=round(total, 2),
        realized_winrate=round(win / max(len(real), 1) * 100, 1),
        peak_pos_n=rp['peak_n'], peak_occupancy_yuan=rp['peak_n'] * PRIN,
        budget_yuan=budget_yuan, ret_on_budget_pct=round(total / budget_yuan * 100, 2) if budget_yuan else None,
        ops_total=len(bought) + len(real) + len(forced),
        ops_per_year=round((len(bought) + len(real) + len(forced)) / span_years, 2),
        skipped_mtm_if_bought=round(sum(t[idx]['pnlYuan'] for t in skipped), 2),
        mdd_realized=mdd_real, mdd_merged_terminal=mdd_merged,
    )
    yearly = {}
    for t in alive:
        y = str(t[0])[:4]; yearly.setdefault(y, 0.0); yearly[y] += t[idx]['pnlYuan']
    out['yearly_total_merged'] = {y: round(v, 2) for y, v in sorted(yearly.items())}
    out['bears_total_merged'] = {lab: round(R.stats_of(R.window(alive, a, b))['total'], 2)
                                 for lab, a, b in BEARS26}
    near = R.window(alive, near_cut)
    out['near1y'] = dict(cutoff=near_cut, total_merged=round(R.stats_of(near)['total'], 2),
                         n=len(near))
    return out


def main():
    tr, fIdx = load(os.path.join(R._ROOT, 'static-site/data/signal_kelly_trades.json'))
    gen_at = tr.get('generated_at')
    print(f'data generated_at={gen_at} NEW14={len(NEW14_KEYS)}键 NEW18={len(NEW18_KEYS)}键')
    assert abs(M24CMP['anchor']['new2_net'] - 120564.54) < 0.5
    assert abs(M24CMP['anchor']['p0'] - 66530.38) < 0.5

    rules_full = build_rules(FEATS, fIdx); rules_full.update(build_r2(fIdx))

    # ================= Part0 锚点复现(mode A 全套 + NEW18 新锚点)=================
    rows_a, fia = R.prepare_rows()
    assert len(fia) == len(fIdx)
    R.init(rows_a, fia)
    rl_a = build_rules(FEATS, fia); rl_a.update(build_r2(fia))
    ctxA = M25.build_ctx(rows_a, fia)
    st0 = R.stats_of(M25.ev(ctxA, (), False)); st1 = R.stats_of(M25.ev(ctxA, (), True))
    assert abs(st0['total'] - 66530.38) < 0.5, st0['total']
    assert abs(st1['total'] - 73102.53) < 0.5, st1['total']
    imp = {}
    for nm, sub, e in [('A9', M25.A_SUB, 46007.00), ('B9', M25.B_SUB, 36469.07), ('C9', M25.C_SUB, 34010.95)]:
        got = R.stats_of(M25.ev(ctxA, sub, True))['total'] - st1['total']
        assert abs(got - e) < 1.0, (nm, got); imp[nm] = round(got, 2)
    poolA = finish_pool(build_mode_pool(tr, fia, 'A'), fia)
    R.init(poolA, fia)
    selN14 = M25.ev_new_on(poolA, fia, M25.hits_on(poolA, fia, NEW14_KEYS, rl_a))
    stN14 = R.stats_of(selN14)
    assert abs(stN14['total'] - 122648.33) < 1.0, stN14['total']
    ddN14 = M25.dd_of(*_curve(selN14, fia))
    selN18 = M25.ev_new_on(poolA, fia, M25.hits_on(poolA, fia, NEW18_KEYS, rl_a))
    stN18 = R.stats_of(selN18)
    assert abs(stN18['total'] - 120564.54) < 1.0, stN18['total']
    ddN18 = M25.dd_of(*_curve(selN18, fia))
    assert abs(ddN14['mdd'] - (-4178.01)) < 1.5, ddN14
    assert abs(ddN18['mdd'] - (-4083.63)) < 1.5, ddN18
    print(f"Part0 modeA锚点 PASS: P0={st0['total']:+,.2f} P1={st1['total']:+,.2f} "
          f"A/B/C vs9键={imp} NEW14={stN14['total']:+,.2f}/mdd{ddN14['mdd']:,.2f} "
          f"NEW18={stN18['total']:+,.2f}/mdd{ddN18['mdd']:,.2f}")

    # ================= Part1 G 模式池构建 + no-cap 交叉断言 =================
    pool_raw = finish_pool(build_mode_pool(tr, fIdx, 'G'), fIdx)   # 无过滤基础池
    pool_8 = pool_g_filtered(tr, fIdx)                             # 8键过滤池
    R.init(pool_8, fIdx)
    rl_g = build_rules(FEATS, fIdx); rl_g.update(build_r2(fIdx))
    ctxG = M25.build_ctx(pool_8, fIdx)
    sels = {
        'RAW无过滤': M25.ev_new_on(pool_raw, fIdx, set()),
        'P0_8键': M25.ev(ctxG, (), False),
        'P1_9键': M25.ev(ctxG, (), True),
        'A_on9': M25.ev(ctxG, M25.A_SUB, True),
        'B_on9': M25.ev(ctxG, M25.B_SUB, True),
        'C_on9': M25.ev(ctxG, M25.C_SUB, True),
        'NEW14': M25.ev_new_on(pool_raw, fIdx, M25.hits_on(pool_raw, fIdx, NEW14_KEYS, rl_g)),
        'NEW14叠8键': M25.ev_new_on(pool_8, fIdx, M25.hits_on(pool_8, fIdx, NEW14_KEYS, rl_g)),
        'NEW18': M25.ev_new_on(pool_raw, fIdx, M25.hits_on(pool_raw, fIdx, NEW18_KEYS, rl_g)),
        'NEW18叠8键': M25.ev_new_on(pool_8, fIdx, M25.hits_on(pool_8, fIdx, NEW18_KEYS, rl_g)),
    }
    xcheck = {}
    auth_map = {'P0_8键': M25_NOCAP_G['base8'], 'P1_9键': M25_NOCAP_G['base9'],
                'A_on9': M25_NOCAP_G['A']['total'], 'B_on9': M25_NOCAP_G['B']['total'],
                'C_on9': M25_NOCAP_G['C']['total'], 'NEW14叠8键': M25_NOCAP_G['NEW']['total']}
    for pj, auth in auth_map.items():
        tot = round(R.stats_of(sels[pj])['total'], 2)
        ok = abs(tot - auth) < 0.5
        xcheck[pj] = dict(no_cap_total=tot, authoritative=auth, match=ok)
        assert ok, (pj, tot, auth)
    print('Part1 G no-cap 交叉断言 6/6 PASS:', {k: v['no_cap_total'] for k, v in xcheck.items()})

    # 数据跨度/近1年切点
    all_sd = sorted({str(t[0]) for t in pool_raw})
    d_min, d_max = all_sd[0], all_sd[-1]
    span_years = (datetime.date(int(d_max[:4]), int(d_max[4:6]), int(d_max[6:8]))
                  - datetime.date(int(d_min[:4]), int(d_min[4:6]), int(d_min[6:8]))).days / 365.25
    cut_dt = (datetime.date(int(d_max[:4]), int(d_max[4:6]), int(d_max[6:8])) - datetime.timedelta(days=365))
    near_cut = cut_dt.strftime('%Y%m%d')
    print(f'数据跨度 {d_min}~{d_max} ({span_years:.1f}年);近1年窗 cutoff={near_cut}')

    # ================= Part2 全穷举主矩阵 =================
    runs = {}   # runs[filter][method][cap_key] = stats_ext
    for pj in FILTERS:
        sel = sels[pj]
        day_sel = {str(t[0]): t for t in sel}
        runs[pj] = {}
        for cap in CAPS + [None]:
            ck = 'nocap' if cap is None else f'cap{cap}'
            budget = None if cap is None else cap * PRIN
            if cap is None:   # 老口径对照: 仅 v2(=无限并发, p3d/v1 退化为同格)
                R.init(sel, fIdx)
                rp = replay3(day_sel, fIdx, None, 'v2回补极简')
                runs[pj][ck] = {'v2回补极简': stats_ext(rp, fIdx, None, None, span_years, near_cut)}
                continue
            runs[pj][ck] = {}
            for meth in METHODS:
                R.init(sel, fIdx)
                rp = replay3(day_sel, fIdx, cap, meth)
                # 自检: v2 必须与 mine25 已验证 replay_cap 等值
                if meth == 'v2回补极简':
                    b2, s2, p2 = M25.replay_cap(dict(day_sel), fIdx, cap)
                    assert len(b2) == len(rp['bought']) and p2 == rp['peak_n'], (pj, ck)
                    assert abs(sum(t[R.IDX_PNL]['pnlYuan'] for t in b2) -
                               sum(t[R.IDX_PNL]['pnlYuan'] for t in rp['bought'])) < 0.005, (pj, ck)
                runs[pj][ck][meth] = stats_ext(rp, fIdx, cap, budget, span_years, near_cut)
        parts = []
        for ck in [f'cap{c}' for c in CAPS] + ['nocap']:
            seg = ', '.join(f"{m.split(' ')[0]}{v['total_merged']:+,.0f}(操{v['ops_total']})"
                            for m, v in runs[pj][ck].items())
            parts.append(f'{ck}: {seg}')
        print(f'{pj}: ' + ' | '.join(parts))

    # ================= Part3 排名与结论数据(全史+近1年,净利+回撤双维)=================
    def ranks_within(method, cap_key, dim):
        items = []
        for pj in FILTERS:
            st = runs[pj][cap_key].get(method)
            if st is None: continue
            v = st['total_merged'] if dim == 'net' else -abs(st['mdd_merged_terminal']['mdd'])
            items.append((v, pj))
        items.sort(reverse=True)
        return [{ 'rank': i + 1, 'filter': pj, 'value': round(v, 2)} for i, (v, pj) in enumerate(items)]

    rank_tables = {}
    for method in ['p3d现行13万P3d', 'v2回补极简']:
        for ck in ['cap10', 'cap13']:
            rank_tables[f'{method}|{ck}|net|all'] = ranks_within(method, ck, 'net')
            rank_tables[f'{method}|{ck}|mdd|all'] = ranks_within(method, ck, 'mdd')
    # 近1年净利排名(v2/p3d × cap13/cap20)
    near_rank = {}
    for method in ['p3d现行13万P3d', 'v2回补极简']:
        for ck in ['cap10', 'cap13', 'cap20']:
            items = sorted(((runs[pj][ck][method]['near1y']['total_merged'], pj) for pj in FILTERS), reverse=True)
            near_rank[f'{method}|{ck}'] = [{'rank': i + 1, 'filter': pj, 'near1y_net': round(v, 2)}
                                           for i, (v, pj) in enumerate(items)]

    # 极简 vs 现行 直接对比(同过滤同 cap)
    compare_v2_vs_p3d = {}
    for pj in FILTERS:
        for c in CAPS:
            ck = f'cap{c}'
            a, b = runs[pj][ck]['p3d现行13万P3d'], runs[pj][ck]['v2回补极简']
            compare_v2_vs_p3d[f'{pj}|{ck}'] = dict(
                delta_total=round(b['total_merged'] - a['total_merged'], 2),
                delta_pct_of_budget=round((b['total_merged'] - a['total_merged']) / (c * PRIN) * 100, 2),
                p3d_ops=a['ops_total'], v2_ops=b['ops_total'], ops_saved=a['ops_total'] - b['ops_total'],
                forced_saved=a['n_forced_liq'], buys_diff=b['n_bought'] - a['n_bought'],
                p3d_total=a['total_merged'], v2_total=b['total_merged'])

    out = dict(
        meta=dict(
        script='mine27_g_exhaustive_simplified.py', generated_at_data=gen_at,
        filters=FILTERS, caps=CAPS, methods=METHODS, new14_keys=NEW14_KEYS, new18_keys=NEW18_KEYS,
        data_span=[d_min, d_max], span_years=round(span_years, 2), near1y_cutoff=near_cut,
        caliber=dict(
            engine='复用 mine25/sim_core 口径(前端模拟回测弹窗 1:1,K1 补位,每笔固定本金 10000 元;'
                   'E23: K=1 时每笔1万≡每日池等分净利逐位相同)',
            money='资金档 N 万 = 并发上限 cap N 笔(峰值占用≤N 万,占用=本金口径非市值)',
            methods=dict(
                p3d='现行推荐=v1.1.2 基准 G:13万 P≤3d「先卖年轻仓」b0 强平(容量满时强平≤3日历天年轻仓中买日最早者,'
                    '无年轻仓 FIFO 最老,强平记 0 利保守;对齐 kelly_opg_engine.p3d_cap ↔ lab.js _kellyAihlineP3dCap)',
                v2='极简回补型(用户本意主口径):满仓跳过该日信号不买,自然卖出信号释放资金/仓位后才可再买,无任何主动换仓/强平',
                v1='一轮型(附录对照):累计买入达 cap 后永不再买,卖出照常,资金沉淀'),
            filters_note='NEW14/NEW18=独立重构口径(原始模式池+黑名单,mode A 权威锚点已验);'
                         '「叠8键」变体=G 上叠 8 键池再上黑名单(mine25 §11 同款)作敏感性附表',
            drawdown='mdd_realized=已实现现金流曲线;mdd_merged_terminal=同曲线+未实现浮盈挂数据截止日(近似口径,同 mine25)'),
        bears_windows=[list(b) for b in BEARS26],
        anchor=dict(modeA=dict(p0=st0['total'], p1=st1['total'], **imp,
                               new14_net=stN14['total'], new14_mdd=ddN14['mdd'],
                               new18_net=stN18['total'], new18_mdd=ddN18['mdd']),
                    g_nocap_crosscheck=xcheck),
        nocap_totals={pj: runs[pj]['nocap']['v2回补极简']['total_merged'] for pj in FILTERS},
        runs=runs, rank_tables_all=rank_tables, near1y_rank=near_rank,
        compare_v2_vs_p3d=compare_v2_vs_p3d,
    ))
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    print('saved ->', OUT_PATH)


def _curve(sel, fi):
    """sel 的已实现现金流聚合曲线 → (days, cum_by_day)(供 dd_of)。"""
    idx = R.IDX_PNL
    bys = {}
    for t in sel:
        if str(t[fi['sell_date']] or ''):
            sd = str(t[fi['sell_date']])
            bys[sd] = bys.get(sd, 0.0) + t[idx]['pnlYuan']
    return sorted(bys), bys


if __name__ == '__main__':
    main()
