# -*- coding: utf-8 -*-
"""mine25 九模式(A-I)可操作口径方案对比(2026-08-23 主控令;原长线 G/H/I 版扩展为全九模式)。
背景: §15.13.7 九模式表 G/I 绝对额(+595,916/+410,235)为不可实操口径(SELL_MODES G/H/I 无卖出信号
则持有至回测结束, 未平仓浮盈当已实现计入、并发无上限、资金占用百万级=136倍本金不可操作, L32)。
本脚本在「可操作约束」下重跑 A-I 全九模式 × 6 方案对比(A-F 短线纳入=统一排序对比+cap 咬合交叉验证:
A-F 为固定持有期(5/10/15 天,SELL_MODES A=固定10天/B/C/D=10天止盈/E=5天/F=15天)资金滚动释放,
K1 下峰值持仓有限 → cap20/cap50 应完全不咬合、数字==no-cap 权威值,若咬合即停):
  可操作口径:
   ①并发持仓上限 cap ∈ {10, 20, 50}(默认 20 笔≈20 万本金, 对齐 kelly-operability-20x-principal
     的 20 倍本金硬控);新信号到达时在途持仓已满 cap → 该信号跳过不买(按 signal_date 升序重放,
     先删后加: sell_date<=当日 的持仓先释放腾位, 与 sim_core.window_stats/peak_pos 同逻辑);
   ②未平仓单独列: 回测结束仍持有的笔按 current_price 快照 mark-to-market(calc_row 费后口径,
     含模拟卖出费), 计入 unrealized_pnl, 不混入 realized_pnl;
   ③realized/unrealized/total_merged 三列全报;回撤给两口径:
       mdd_realized = 已实现现金流(sell_date 聚合)曲线回撤;
       mdd_merged_terminal = 同曲线 + 全部未实现浮盈集中挂数据截止日(因 trades.json 无逐日盯市价,
         真正逐日合并净值不可得, 此为可计算的最接近口径, 诚实标注);
   ④峰值占用金额 = 峰值并发笔数 × 10000 本金口径(无逐日市值价, 不报市值占用)。
  项目 6 个: P0_8键 / P1_9键 / A_on9 / B_on9 / C_on9 / NEW_mine24_14键。
  池构造与选择逻辑与 mine24_compare.py 完全一致(叠加口径 P0/P1/A/B/C; 重构口径 NEW;
  G/H/I 上 NEW 叠在该模式 8 默认过滤池上、无候选1), 仅新增 cap 重放层。
锚点断言(必过):
  mode A: P0=+66,530.38 / P1=+73,102.53 / A9 vs9键=+46,007 / B9=+36,469 / C9=+34,011 /
          NEW14=+122,648.33 & mdd=-4,178.01;
  no-cap crosscheck: A-I × 6 项目 no-cap 总额 == mine24_compare.json modes[m] 权威数字(<0.5),54 断言。
  短线咬合校验: A-F × 6 项目 cap20/cap50 必须 n_skipped=0 且合计额==no-cap(cap10 允许轻度咬合仅记录)。
输出: data/mine25_longline_operable.json
复现: python3 mine25_longline_operable.py
依赖: signal_kelly_trades.json(generated_at=2026-08-23 05:09) + mine10_features.json +
      mine24_global_search.json + mine24_compare.json(no-cap 交叉断言用)。
关键口径一句话: 补位 top-K1(K1 默认)选信号 → 按 signal_date 重放加 cap 并发上限 → 已实现/未实现(MTM)分列。
"""
import os, sys, json, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, calc_row, base_key, PRIN
from mine18_detail import BEARS, FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2

OUT_PATH = os.path.join(BASE, 'data', 'mine25_longline_operable.json')
M24GS_PATH = os.path.join(BASE, 'data', 'mine24_global_search.json')
M24CMP_PATH = os.path.join(BASE, 'data', 'mine24_compare.json')

A_SUB = ('T1','Q1','M1','V1','R1','R2a','R2b','R2g')
B_SUB = ('T1','Q1','M1','R1','R2b','R2g')
C_SUB = ('N1','T1','D1','H1','M1','P1','R2b')
CAPS = [10, 20, 50]
PROJECTS = ['P0_8键', 'P1_9键', 'A_on9', 'B_on9', 'C_on9', 'NEW_mine24_14键']
MODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
MODE_LABEL = {'A': '固定10天', 'B': '3%止盈(10天上限)', 'C': '5%止盈(10天上限)', 'D': '7%止盈(10天上限)',
              'E': '持有5天', 'F': '持有15天', 'G': '卖出信号', 'H': '卖出+追止损', 'I': '追关注加追止损'}

M24 = json.load(open(M24GS_PATH))
DOMS = M24['dominators_of_A']
NEW_KEYS = min((d for d in DOMS if abs(d['net'] - 122648.33) < 1), key=lambda d: len(d['keys']))['keys']


def prep_mode_local(tr, fIdx, mode):
    """mine17_modes.prep_mode 同款, 但复用已加载 tr(免重复 load 64MB)。返回 (kept_rows, fIdx)。"""
    rows = build_mode_pool(tr, fIdx, mode)
    mm = active_month_mask(DEFAULT_FILTERS)
    mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2
    kept = [t for t in rows if passes_fade(t, fIdx, DEFAULT_FILTERS, mm, mD, eD, rD)]
    from sim_core import calc_row as _cr
    R.IDX_PNL, R.IDX_SKEY = len(fIdx) + 3, len(fIdx) + 4
    RATING_RANK = {'high': 0, 'mid': 1, 'low': 2}
    SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in kept:
        t.append(_cr(t, fIdx))
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RATING_RANK.get(str(t[fIdx['rating']] or ''), 3),
                  SIG_RANK.get(str(t[fIdx['signal']] or ''), 9),
                  str(t[fIdx['buy_date']] or '')))
    return kept, fIdx


def build_ctx(rws, fi):
    """mine24_compare.build_ctx 同款。"""
    R.init(rws, fi)
    rl = build_rules(FEATS, fi); rl.update(build_r2(fi))
    h = {c: {base_key(t, fi) for t in rws if rl[c](t)} for c in set(A_SUB + B_SUB + C_SUB)}
    hc1 = {base_key(t, fi) for t in rws if (t[2] in ('buy_aux', 'buy_backup')) and ((t[fi['market_tier']] or '') == '牛市·主升')}
    g = {}
    for t in rws:
        g.setdefault(str(t[0]), []).append((base_key(t, fi), t))
    for sd in g: g[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
    return dict(h=h, hc1=hc1, g=g, sds=sorted(g))


def ev(ctx, sub, with_c1, K=1):
    blk = set(ctx['hc1']) if with_c1 else set()
    for c in sub: blk |= ctx['h'][c]
    sel = []
    for sd in ctx['sds']:
        n = 0
        for key, t in ctx['g'][sd]:
            if key not in blk:
                sel.append(t); n += 1
                if n >= K: break
    return sel


def hits_on(rws, fi, keys, rules_local):
    """mine24_compare NEW-on-mode 同款: hist 键=单键 passes_fade 被拦集; 新规则键=rl[c] 命中集。"""
    hist_keys = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
    mD, eD, rD = len(fi), len(fi) + 1, len(fi) + 2
    blk = set()
    for c in keys:
        if c in hist_keys:
            f = {kk: False for kk in DEFAULT_FILTERS}; f[c] = True
            blk |= {base_key(t, fi) for t in rws if not passes_fade(t, fi, f, active_month_mask(f), mD, eD, rD)}
        else:
            blk |= {base_key(t, fi) for t in rws if rules_local[c](t)}
    return blk


def ev_new_on(rws, fi, blk, K=1):
    g = {}
    for t in rws:
        g.setdefault(str(t[0]), []).append((base_key(t, fi), t))
    for sd in g: g[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
    sel = []
    for sd in sorted(g):
        n = 0
        for key, t in g[sd]:
            if key not in blk:
                sel.append(t); n += 1
                if n >= K: break
    return sel


def replay_cap(day_sel, fi, cap):
    """可操作核心: 按 signal_date 升序重放, 先删后加(sell_date<=sd 释放), 在途>=cap 则跳过该日信号。
    返回 (bought, skipped, peak_n)。cap=None = 不设限(老口径对照)。"""
    open_map = {}
    bought, skipped = [], []
    peak_n = 0
    for sd in sorted(day_sel):
        for k in [k for k, v in open_map.items()
                  if str(v[fi['sell_date']] or '') and str(v[fi['sell_date']]) <= sd]:
            del open_map[k]
        if cap is not None and len(open_map) >= cap:
            skipped.append(day_sel[sd]); continue
        t = day_sel[sd]
        open_map[base_key(t, fi)] = t
        bought.append(t)
        if len(open_map) > peak_n: peak_n = len(open_map)
    return bought, skipped, peak_n


def dd_of(curve_days, cum_by_day):
    """cum 曲线 → dict(mdd, trough_day, recovered, recover_day)。"""
    cum = peak = 0.0; mdd = 0.0; trough = None; pat = 0.0
    for d in curve_days:
        cum += cum_by_day[d]
        if cum > peak: peak = cum
        if cum - peak < mdd:
            mdd = cum - peak; trough = d; pat = peak
    rec = None
    if trough is not None:
        cum = 0.0; past = False
        for d in curve_days:
            cum += cum_by_day[d]
            if d == trough: past = True
            if past and cum >= pat:
                rec = d; break
    return dict(mdd=round(mdd, 2), trough_day=trough, recovered=rec is not None, recover_day=rec)


def operable_stats(bought, skipped, peak_n, fi):
    idx = R.IDX_PNL
    real = [t for t in bought if str(t[fi['sell_date']] or '')]
    hold = [t for t in bought if not str(t[fi['sell_date']] or '')]
    r_pnl = sum(t[idx]['pnlYuan'] for t in real)
    u_pnl = sum(t[idx]['pnlYuan'] for t in hold)
    win_r = sum(1 for t in real if t[idx]['pnlYuan'] > 0)
    # 已实现现金流曲线(sell_date 聚合)
    bys = {}
    for t in real:
        sd = str(t[fi['sell_date']])
        bys[sd] = bys.get(sd, 0.0) + t[idx]['pnlYuan']
    days = sorted(bys)
    mdd_real = dd_of(days, bys)
    # merged terminal 曲线: 全部未实现浮盈挂最后事件日(诚实标注: 无逐日盯市价的近似)
    all_days = set(days)
    for t in bought: all_days.add(str(t[0]))
    last_day = max(all_days) if all_days else None
    bys_m = dict(bys)
    if last_day is not None and hold:
        bys_m[last_day] = bys_m.get(last_day, 0.0) + u_pnl
    mdd_merged = dd_of(sorted(bys_m), bys_m)
    sk_pnl = sum(t[idx]['pnlYuan'] for t in skipped)
    out = dict(
        n_bought=len(bought), n_realized=len(real), n_holding=len(hold), n_skipped=len(skipped),
        realized_pnl=round(r_pnl, 2), unrealized_pnl=round(u_pnl, 2), total_merged=round(r_pnl + u_pnl, 2),
        realized_winrate=round(win_r / max(len(real), 1) * 100, 1),
        peak_pos_n=peak_n, peak_occupancy_yuan=peak_n * PRIN,
        end_open_n=len(hold),
        skipped_mtm_pnl_if_bought=round(sk_pnl, 2),
        mdd_realized=mdd_real, mdd_merged_terminal=mdd_merged,
    )
    yearly = {}
    for t in bought:
        y = str(t[0])[:4]
        yearly.setdefault(y, 0.0); yearly[y] += t[idx]['pnlYuan']
    out['yearly_total_merged'] = {y: round(v, 2) for y, v in sorted(yearly.items())}
    out['bears_total_merged'] = {lab: round(R.stats_of(R.window(bought, a, b))['total'], 2) for lab, a, b in BEARS}
    return out


FEATS = json.load(open(FEATS_PATH))

def main():
    tr, fIdx = load(R._ROOT + '/static-site/data/signal_kelly_trades.json')
    gen_at = tr.get('generated_at')
    R.FIDX_CACHE = fIdx
    print(f'data generated_at={gen_at}  NEW_KEYS={len(NEW_KEYS)}键')
    m24cmp = json.load(open(M24CMP_PATH))
    assert abs(m24cmp['anchor']['p0'] - 66530.38) < 0.5

    # ================= Part1: mode A 锚点复现 =================
    rows, fIdxP = R.prepare_rows()
    assert len(fIdxP) == len(fIdx)
    R.init(rows, fIdx)
    rules = build_rules(FEATS, fIdx); rules.update(build_r2(fIdx))
    ctxA = build_ctx(rows, fIdx)
    st0 = R.stats_of(ev(ctxA, (), False)); st1 = R.stats_of(ev(ctxA, (), True))
    assert abs(st0['total'] - 66530.38) < 0.5, st0['total']
    assert abs(st1['total'] - 73102.53) < 0.5, st1['total']
    A9 = ev(ctxA, A_SUB, True); B9 = ev(ctxA, B_SUB, True); C9 = ev(ctxA, C_SUB, True)
    for nm, sel, imp in [('A9', A9, 46007.00), ('B9', B9, 36469.07), ('C9', C9, 34010.95)]:
        got = R.stats_of(sel)['total'] - st1['total']
        assert abs(got - imp) < 1.0, (nm, got, imp)
    poolA = build_mode_pool(tr, fIdx, 'A')
    R.IDX_PNL, R.IDX_SKEY = len(fIdx) + 3, len(fIdx) + 4
    RATING_RANK = {'high': 0, 'mid': 1, 'low': 2}
    SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in poolA:
        t.append(calc_row(t, fIdx))
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RATING_RANK.get(str(t[fIdx['rating']] or ''), 3),
                  SIG_RANK.get(str(t[fIdx['signal']] or ''), 9), str(t[fIdx['buy_date']] or '')))
    R.init(poolA, fIdx)
    blkA = hits_on(poolA, fIdx, NEW_KEYS, rules)
    NEW_A = ev_new_on(poolA, fIdx, blkA)
    stN = R.stats_of(NEW_A)
    assert abs(stN['total'] - 122648.33) < 1.0, stN['total']
    print(f'锚点 PASS: modeA P0={st0["total"]:+,.2f} P1={st1["total"]:+,.2f} '
          f'A9/B9/C9 vs9键=+46,007/+36,469/+34,011 NEW14={stN["total"]:+,.2f}')

    # ================= Part2: 九模式 A-I 可实操口径 =================
    runs = {}       # runs[mode][project][cap_key] = operable_stats
    xcheck = {}     # no-cap vs mine24_compare.modes
    delta_vs_p0 = {}  # [mode][cap_key][project] = total_merged 差(vs P0 同 cap)
    for m in MODES:
        rws, fm = prep_mode_local(tr, fIdx, m)
        assert len(fm) == len(fIdx)
        R.init(rws, fm)
        rl = build_rules(FEATS, fm); rl.update(build_r2(fm))
        ctx = build_ctx(rws, fm)
        sels = {
            'P0_8键': ev(ctx, (), False),
            'P1_9键': ev(ctx, (), True),
            'A_on9': ev(ctx, A_SUB, True),
            'B_on9': ev(ctx, B_SUB, True),
            'C_on9': ev(ctx, C_SUB, True),
            'NEW_mine24_14键': ev_new_on(rws, fm, hits_on(rws, fm, NEW_KEYS, rl)),
        }
        runs[m] = {}; xcheck[m] = {}; delta_vs_p0[m] = {}
        auth = m24cmp['modes'][m]
        base_map = {'P0_8键': auth['base8'], 'P1_9键': auth['base9'], 'A_on9': auth['A']['total'],
                    'B_on9': auth['B']['total'], 'C_on9': auth['C']['total'],
                    'NEW_mine24_14键': auth['NEW']['total']}
        for pj in PROJECTS:
            sel = sels[pj]
            tot_nc = round(R.stats_of(sel)['total'], 2)
            ok = abs(tot_nc - base_map[pj]) < 0.5
            xcheck[m][pj] = dict(no_cap_total=tot_nc, mine24_authoritative=base_map[pj], match=ok)
            assert ok, (m, pj, tot_nc, base_map[pj])
            dd = {}
            for cap in CAPS + [None]:
                ck = 'nocap' if cap is None else str(cap)
                day_sel = {str(t[0]): t for t in sel}
                bought, skipped, peak_n = replay_cap(day_sel, fm, cap)
                dd[ck] = operable_stats(bought, skipped, peak_n, fm)
                print(f"  {m}/{pj}/cap{ck}: 已实现{dd[ck]['realized_pnl']:+,.0f} 未实现{dd[ck]['unrealized_pnl']:+,.0f} "
                      f"合计{dd[ck]['total_merged']:+,.0f} 买{dd[ck]['n_bought']}跳{dd[ck]['n_skipped']} "
                      f"峰持{dd[ck]['peak_pos_n']} 占用峰值{dd[ck]['peak_occupancy_yuan']:,.0f} "
                      f"mdd_real{dd[ck]['mdd_realized']['mdd']:,.0f}")
            runs[m][pj] = dd
        for ck in [str(c) for c in CAPS] + ['nocap']:
            delta_vs_p0[m][ck] = {pj: round(runs[m][pj][ck]['total_merged'] - runs[m]['P0_8键'][ck]['total_merged'], 2)
                                  for pj in PROJECTS}
        print(f'mode {m}: no-cap 交叉断言 6/6 PASS; cap 敏感性 vs P0 增量: ' +
              ' | '.join(f'cap{ck}: ' + ', '.join(f"{pj.split('_')[0]}{delta_vs_p0[m][ck][pj]:+,.0f}" for pj in PROJECTS[1:])
                         for ck in ['10', '20', '50']))

    # ================= Part3: 短线 A-F cap 咬合校验(预期: 固定持有期<=15天 → cap20/50 不咬合) =================
    shortline_check = {}
    for m in ['A', 'B', 'C', 'D', 'E', 'F']:
        per = {}
        for pj in PROJECTS:
            r = runs[m][pj]
            nc_tot = r['nocap']['total_merged']
            per[pj] = dict(
                nocap_peak_pos_n=r['nocap']['peak_pos_n'],
                caps={ck: dict(n_skipped=r[ck]['n_skipped'],
                               total_eq_nocap=abs(r[ck]['total_merged'] - nc_tot) < 0.005)
                      for ck in ['10', '20', '50']})
            # 预期校验硬断言: 主推档 cap20 与宽档 cap50 必须不咬合(n_skipped=0 且合计额==no-cap)
            for ck in ['20', '50']:
                assert per[pj]['caps'][ck]['n_skipped'] == 0 and per[pj]['caps'][ck]['total_eq_nocap'], ('短线下cap意外咬合停手上报', m, pj, ck)

        bind10 = {pj: per[pj]['caps']['10']['n_skipped'] for pj in PROJECTS if per[pj]['caps']['10']['n_skipped']}
        shortline_check[m] = dict(label=MODE_LABEL[m], projects=per, cap10_bind_projects=bind10,
                                  conclusion=(f"{MODE_LABEL[m]}: cap20/cap50 六项目全不咬合(合计==no-cap 权威); "
                                              f"cap10 咬合={bind10 if bind10 else '无'}"))
        print('咬合校验:', shortline_check[m]['conclusion'])

    out = dict(
        meta=dict(
            modes=MODES, mode_label=MODE_LABEL,script='mine25_longline_operable.py', generated_at_data=gen_at,
                  caps=CAPS, projects=PROJECTS, new_keys=NEW_KEYS,
                  caliber=dict(
                      cap_skip='按 signal_date 升序重放, 先删后加(sell_date<=当日先释放), 在途>=cap 该日信号跳过不买',
                      mtm='未平仓按 current_price 快照(数据生成时最新价)费后 MTM(calc_row 含模拟卖出费), 非未来真实卖价',
                      occupancy='峰值占用金额=峰值并发笔数×10000 每笔固定本金口径(非市值)',
                      drawdown='mdd_realized=已实现现金流曲线回撤; mdd_merged_terminal=同曲线+全部浮盈挂数据截止日(trades 无逐日盯市价, 近似口径)',
                      selection='池构造与选择逻辑与 mine24_compare.py 一致(P0/P1/A/B/C 叠加口径; NEW 重构口径; G/H/I 上 NEW 叠该模式 8 默认池、无候选1); K1 补位',
                      diff_vs_frontend='cap-skip 为本研究新增约束层, 生产引擎(signal_kelly_backtest.py SELL_MODES G/H/I)与前端模拟回测弹窗均无并发上限概念; 跳过判定不含 T+1 资金可用时差')),
        anchor=dict(p0=st0['total'], p1=st1['total'],
                    a9_vs_p1=round(R.stats_of(A9)['total'] - st1['total'], 2),
                    b9_vs_p1=round(R.stats_of(B9)['total'] - st1['total'], 2),
                    c9_vs_p1=round(R.stats_of(C9)['total'] - st1['total'], 2),
                    new_net=stN['total']),
        nocap_crosscheck=xcheck,
        runs=runs,
        delta_vs_p0=delta_vs_p0,
        shortline_cap_bind_check=shortline_check,
        note='no-cap 行即 §15.13.7/mine24 老口径数字(逐位复现), 仅作对照不作主推; 主推口径=cap20。'
             'A-F 短线纳入目的: ①与 G/H/I 同框架出九模式统一排序; ②交叉验证 cap 层在固定持有期模式下'
             '不咬合(shortline_cap_bind_check), 即短线的 cap 口径数字==既有 no-cap 权威(mine24_compare.modes)。'
             '注意 mode A 的 NEW 在本框架=叠在模式 8 默认过滤池上(no-cap=117,797.87, 与 mine24_compare.modes.A.NEW 一致),'
             '区别于独立重构口径全池版锚点 +122,648.33(mine24 anchor.new_net), 两口径并存已诚实标注。',
    )
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    print('saved ->', OUT_PATH)


if __name__ == '__main__':
    main()
