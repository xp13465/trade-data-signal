# -*- coding: utf-8 -*-
"""H档「带帽回本等待」参数谱穷举回测(h-ext 侧, Task#11 延伸)。

【目的】cc 侧报告 §十.3 留尾:「延长上限 N(td)+到期强制卖」的受限版未跑。本脚本补测该混合档
    (用户称 H 档=带帽回本等待卖出, 与引擎 G/H/I 卖出信号的"H 模式(sell+追止损)"完全不同义):
    亏损单(基线10td到期 pnl<0)在窗口内等净回本(net>=PRIN)收盘卖, 超帽日无条件卖。
    参数谱 {H15,H20,H30,H60 交易日} × 三降亏模式 {S06 动态, A(on9), NEW14+1(15键)} × cap13 组合重放。

【方法口径】(与 cc_hold_ext_backtest.py 全同, 仅出场规则不同)
  - 框架复用: import cc_hold_ext_backtest(CC), 复用 Engine 选笔 / Extender 价格与成交 / occupancy /
    replay_pack(mine27.replay3 'v2回补极简' + stats_ext) / dist_stats / dd_of。
  - 变体定义(仅改基线亏损单出场, 盈利单与尾持单保持基线):
      HT15/20/30/60(主口径): 总持有帽, 帽位=基线卖日在ETF自身nav日序列的索引 + (H-10)个交易日;
      HX15/20/30/60(对照): 延长帽, 帽位=基线卖日 + H个交易日;
      INF(交叉验证列): 无帽纯回本等待, 直接调 CC.Extender.find_v1, 与 cc_matrix.json 的 V1 对照咬合;
      HT10(机检列): extra=0 退化校验, 期望逐位等于 BASE(差异仅可能来自基线卖日不在nav序列的罕见笔)。
  - 回本判定: 当日 accum_nav 收盘 sell_with_fees(shares,nav).net >= PRIN=10000 (收盘可知可执行, 无前视);
    窗口 [基线卖日+1, 帽位] 逐日扫描, nav 缺失日跳过; 帽日无 nav 则顺延至其后首个有 nav 日(机械执行顺延);
    帽位超出价格数据尾部 → censored 尾日估值(镜像 cc V1)。
【输入依赖】与 cc 相同: static-site/data/signal_kelly_trades.json + static-site/data/kelly_mode_s06_state.json
    + docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/(sim_core/r2_common/mine2x + data json)
    + data/sentiment.db(signal_daily 只读) + trade-data/data/etf_national_team.db(etf_daily 只读)
【输出】本目录 h_anchors.json(锚点+基线复现) / h_variants.json(亏损单逐笔明细) / h_matrix.json(全聚合)
【复现命令】python3 docs/kelly/backtest-ai/hold-ext-pk-20260827/h-ext/h_ext_backtest.py --anchors
            python3 docs/kelly/backtest-ai/hold-ext-pk-20260827/h-ext/h_ext_backtest.py --all
【数据截止】trades generated_at 运行时打印; 关键口径一句话: modeA去重池×三模式选笔(K1补位)→
    基线10td固定卖 vs 亏单带帽回本等待{HT总持有帽/HX延长帽×15/20/30/60} 费后 FP_DEF K1 账本 +
    cap13/15/20/nocap 重放全维度对比, 另 INF/HT10 两机检列。
"""
import os, sys, json, bisect, datetime, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '../../../../../'))
CC_DIR = os.path.join(REPO, 'docs/kelly/backtest-ai/hold-ext-pk-20260827/cc')
M21 = os.path.join(REPO, 'docs/kelly/analysis/scripts/sim_window_loss_mining_20260822')
for p in (CC_DIR, M21, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import cc_hold_ext_backtest as CC  # noqa: E402  (复用 Engine/Extender/occupancy/replay_pack)
from sim_core import PRIN  # noqa: E402
import r2_common as R  # noqa: E402
import mine27_g_exhaustive_simplified as M27  # noqa: E402

OUT_DIR = HERE
CAPS = [13, 15, 20, None]
HT_SPECS = [('HT15', 15, 'total'), ('HT20', 20, 'total'), ('HT30', 30, 'total'), ('HT60', 60, 'total'),
            ('HX15', 15, 'ext'), ('HX20', 20, 'ext'), ('HX30', 30, 'ext'), ('HX60', 60, 'ext'),
            ('HT10', 10, 'total'), ('INF', None, 'inf')]
VARIANTS = ['BASE'] + [n for n, _, _ in HT_SPECS]
MODES_ALL = ['s06', 'a9', 'new15']
ANCHOR_MODES = ['p0', 'p1', 'a9', 'new14', 'new15', 's06']
GT20_LINE_N = 20   # 20倍本金线(20万 / 1万本金)
GT13_LINE_N = 13   # cap13 容量参照线

_GEN_AT = None


def day_diff(d1, d2):
    return max((datetime.date(int(d2[:4]), int(d2[4:6]), int(d2[6:8])) -
                datetime.date(int(d1[:4]), int(d1[4:6]), int(d1[6:8]))).days, 0)


def find_h(ext, t, sd, H, kind):
    """帽型回本等待出场。返回 (exit_date, exit_nav, how)。
    kind: total=帽位=i0+(H-10) | ext=帽位=i0+H | inf=无限等(退化为 CC.find_v1)。"""
    if kind == 'inf':
        d, ok = ext.find_v1(t, sd)
        return (d, ext.nav[t[ext.fi['etf_code']]][d], 'recovered_inf') if ok else (None, None, 'censored')
    code = t[ext.fi['etf_code']] or ''
    ds = ext.sdates.get(code) or []
    if not ds:
        return None, None, 'censored'
    i0 = bisect.bisect_left(ds, sd)
    extra = (H - 10) if kind == 'total' else H
    cap_pos = i0 + extra
    last = len(ds) - 1
    if cap_pos > last:
        for j in range(i0 + 1, last + 1):
            nt = ext.net_at(t, ds[j])
            if nt is not None and nt >= PRIN:
                return ds[j], ext.nav[code][ds[j]], 'recovered'
        return None, None, 'censored'
    for j in range(i0 + 1, cap_pos + 1):
        d = ds[j]
        nt = ext.net_at(t, d)
        if nt is not None and nt >= PRIN:
            return d, ext.nav[code][d], 'recovered'
    j = cap_pos
    while j <= last:
        if ext.nav[code].get(ds[j]) is not None:
            return ds[j], ext.nav[code][ds[j]], ('forced_ontime' if j == cap_pos else 'forced_delayed')
        j += 1
    return None, None, 'censored'


def build_h_variants(ext, sel):
    """返回 (variants dict, meta, detail, deltas)。结构镜像 CC.build_variants。"""
    fi = ext.fi
    res = {'BASE': list(sel)}
    pos_of = {id(t): i for i, t in enumerate(sel)}
    tails = 0
    plans = []
    for t in sel:
        sd = str(t[fi['sell_date']] or '')
        if not sd:
            tails += 1
            continue
        if t[R.IDX_PNL]['pnlYuan'] < 0:
            plans.append((t, t[R.IDX_PNL]['pnlYuan'], sd))
    for name, _, _ in HT_SPECS:
        res[name] = list(sel)
    detail = {v: [] for v, _, _ in HT_SPECS}
    ext_days_map = {v: [] for v, _, _ in HT_SPECS}
    delay_days = {v: [] for v, _, _ in HT_SPECS}
    how_cnt = {v: {} for v, _, _ in HT_SPECS}
    censor_cnt = {v: 0 for v, _, _ in HT_SPECS}
    deltas = {v: [] for v, _, _ in HT_SPECS}
    for t, p0, sd in plans:
        for name, H, kind in HT_SPECS:
            d, nv, how = find_h(ext, t, sd, H, kind)
            row, c = (ext.make_row(t, sell_d=d, sell_nav=nv) if d else ext.make_row(t, censor=True))
            res[name][pos_of[id(t)]] = row
            if not d:
                censor_cnt[name] += 1
            how_cnt[name][how] = how_cnt[name].get(how, 0) + 1
            deltas[name].append((c['pnlYuan'] - p0) if c else 0.0)
            ext_td = None
            if d:
                code = t[fi['etf_code']]
                ds = ext.sdates.get(code) or []
                i0 = bisect.bisect_left(ds, sd)
                i1 = bisect.bisect_left(ds, d)
                ext_td = max(i1 - i0, 0)
                ext_days_map[name].append(ext_td)
                if how.startswith('forced_delay'):
                    cap_i = i0 + ((H - 10) if kind == 'total' else H)
                    delay_days[name].append(max(i1 - cap_i, 0))
            detail[name].append(dict(sd=str(t[0]), etf=t[fi['etf_code']], base_pnl=round(p0, 2),
                                     exit=d, how=how, ext_td=ext_td,
                                     pnl=round(c['pnlYuan'], 2) if c else None))
    meta = dict(n_loser_plans=len(plans), n_tail_holding=tails, censor_counts=censor_cnt,
                how_counts=how_cnt,
                ext_days={k: CC.dist_stats(v) for k, v in ext_days_map.items()},
                delay_days={k: CC.dist_stats(v) for k, v in delay_days.items()},
                delta={k: CC.delta_stats(v) for k, v in deltas.items()})
    return res, meta, detail, deltas


def occupancy_dist(rows_base, rows_var, today_str):
    """账本层逐日持仓水平 sweep(扩展 CC.occupancy): 额外并发分布 p50/p95/max + 破线天数/段数。"""
    buy_i, sell_i = CC.FI_BUY, CC.FI_SELL

    def intervals(rows):
        out = []
        for t in rows:
            b = str(t[buy_i] or '')
            e = str(t[sell_i] or '') or today_str
            if b and e > b:
                out.append((b, e))
        return out

    def series(ivs):
        delta = {}
        for b, e in ivs:
            delta[b] = delta.get(b, 0) + 1
            delta[e] = delta.get(e, 0) - 1
        pts = sorted(delta)
        cur, prev, curve = 0, None, []
        for p in pts:
            if prev is not None and cur > 0:
                curve.append((prev, p, cur))
            cur += delta[p]
            prev = p
        if cur > 0 and prev is not None:
            curve.append((prev, today_str, cur))
        return curve

    cb = series(intervals(rows_base))
    cv = series(intervals(rows_var))
    starts = sorted({s for s, _e, _c in cb} | {s for s, _e, _c in cv})

    def level(curve, x):
        for s, e, c in curve:
            if s <= x < e:
                return c
        return 0

    seg_days = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else today_str
        seg_days.append((s, e, level(cv, s), level(cb, s)))
    opens = [v for _s, _e, v, _b in seg_days]

    def days_above(thr):
        tot = 0
        for s, e, v, _b in seg_days:
            if v > thr:
                tot += day_diff(s, e)
        return tot

    def pct(xs, p):
        xs2 = sorted(xs)
        if not xs2:
            return 0
        return xs2[min(int(p * (len(xs2) - 1)), len(xs2) - 1)]

    extras = [max(v - b, 0) for _s, _e, v, b in seg_days]
    max_open = max(opens) if opens else 0
    area_extra_ydays = sum(day_diff(seg[0], seg[1]) * ex for seg, ex in zip(seg_days, extras))
    return dict(open_n=dict(p50=pct(opens, 0.5), p95=pct(opens, 0.95), max=max_open),
                extra_n=dict(p50=pct(extras, 0.5), p95=pct(extras, 0.95),
                             max=max(extras) if extras else 0, segments_gt0=sum(1 for e in extras if e > 0)),
                days_open_above_20w_cal=days_above(GT20_LINE_N),
                segments_open_above_20w=sum(1 for v in opens if v > GT20_LINE_N),
                days_open_above_13w_cal=days_above(GT13_LINE_N),
                extra_area_wan_yuan_days=round(area_extra_ydays * PRIN / 10000),
                note='段=事件轴上水平区间; 天数按日历日加权; 账本层(无cap并发约束)口径; '
                     'extra_area与cc.occupancy同单位(万元·日)')


def recovery_stats(bys, today_str):
    """累计曲线(事件散点轴, 与 CC.dd_of 同轴)的最长修复期(日历日); 期末未修复计 still_unrecovered。"""
    days = sorted(bys)
    if not days:
        return dict(max_recovery_days=0, n_recoveries=0, still_unrecovered_days=0)
    cum, peak = 0.0, None
    dd_start = None
    spans = []
    for d in days:
        cum += bys[d]
        if peak is not None and cum >= peak and dd_start is not None:
            spans.append(day_diff(dd_start, d))
            dd_start = None
        if peak is None or cum > peak:
            peak = cum
        elif cum < peak and dd_start is None:
            dd_start = d
    unrec = day_diff(dd_start, today_str) if dd_start else 0
    return dict(max_recovery_days=max(spans) if spans else 0, n_recoveries=len(spans),
                still_unrecovered_days=unrec)


def ledger_recovery(rows, fi, today_str):
    bys = {}
    for t in rows:
        d = str(t[fi['sell_date']] or '')
        if d:
            bys[d] = bys.get(d, 0.0) + t[R.IDX_PNL]['pnlYuan']
    mdd, trough = CC.dd_of(bys)
    out = dict(mdd_realized=mdd, mdd_trough=trough)
    out.update(recovery_stats(bys, today_str))
    return out


def merged_curve_recover(ext_unused, rows, fi, today_str):
    """组合层(账本重放口径近似=无 cap 全持有 merged 曲线, 含尾持尾日估值)回撤+恢复。"""
    bys = {}
    u_pnl = 0.0
    last_day = None
    for t in rows:
        d = str(t[fi['sell_date']] or '')
        if d:
            bys[d] = bys.get(d, 0.0) + t[R.IDX_PNL]['pnlYuan']
            last_day = max(last_day or d, d)
        else:
            u_pnl += t[R.IDX_PNL]['pnlYuan']
    ref = max([x for x in (last_day, today_str) if x]) if (last_day or today_str) else None
    if u_pnl and ref:
        bys[ref] = bys.get(ref, 0.0) + u_pnl
    mdd, trough = CC.dd_of(bys)
    out = dict(mdd_merged=mdd, mdd_trough=trough)
    out.update(recovery_stats(bys, today_str))
    return out


def replay_full(rows, fi, cap, span_years, near_cut, today_str):
    """M27.replay3 + stats_ext(全字段) + 组合层恢复期(cap 重放曲线)。"""
    day_sel = {}
    for t in rows:
        day_sel[str(t[0])] = t
    rp = M27.replay3(day_sel, fi, cap, 'v2回补极简')
    budget = cap * PRIN if cap else 0
    st = M27.stats_ext(rp, fi, cap, budget, span_years, near_cut)
    alive = [t for t in rp['bought'] if id(t) not in rp['victim_ids']]
    bys = {}
    last_day = None
    for t in alive:
        d = str(t[fi['sell_date']] or '')
        if d:
            bys[d] = bys.get(d, 0.0) + t[R.IDX_PNL]['pnlYuan']
            last_day = max(last_day or d, d)
    u = sum(t[R.IDX_PNL]['pnlYuan'] for t in alive if not str(t[fi['sell_date']] or ''))
    refs = [x for x in (last_day, today_str) if x]
    if u and refs:
        ref = max(refs)
        bys[ref] = bys.get(ref, 0.0) + u
    st['recovery'] = recovery_stats(bys, today_str)
    return st


def halves_by_plan(plans, deltas, variants):
    """plans=[(t,p0,sd)] 与 deltas[name](list 同序)。按信号日中位切两半样本。"""
    if not plans:
        return {}
    sds = sorted(str(t[0]) for t, _p, _sd in plans)
    mid = sds[len(sds) // 2]
    out = {}
    for name in variants:
        if name not in deltas:
            out_note = dict(split_date=mid, S1=dict(n=0, net_delta=0.0), S2=dict(n=0, net_delta=0.0),
                            direction_consistent=True, note='BASE baseline, delta identically 0')
            out[name] = out_note
            continue
        dl = deltas[name]
        s1 = [x for x, (t, _p, _sd) in zip(dl, plans) if str(t[0]) < mid]
        s2 = [x for x, (t, _p, _sd) in zip(dl, plans) if str(t[0]) >= mid]
        net1, net2 = round(sum(s1), 2), round(sum(s2), 2)
        out[name] = dict(split_date=mid,
                         S1=dict(n=len(s1), net_delta=net1), S2=dict(n=len(s2), net_delta=net2),
                         direction_consistent=bool(net1 > 0 and net2 > 0))
    return out


def run_anchors(eng):
    sel = {m: eng.select(m) for m in ANCHOR_MODES}
    res = {}
    for m, s in sel.items():
        st = R.stats_of(s)
        row = dict(n=st['n'], total=st['total'], holding=st['holding'])
        if m == 'new14':
            bys = {}
            for t in s:
                d = str(t[eng.fi['sell_date']] or '')
                if d:
                    bys[d] = bys.get(d, 0.0) + t[R.IDX_PNL]['pnlYuan']
            mdd, tr = CC.dd_of(bys)
            row['mdd_realized'] = mdd
            row['mdd_trough'] = tr
        if m == 'a9':
            row['margin_vs_p1'] = round(st['total'] - R.stats_of(sel['p1'])['total'], 2)
        if m == 's06':
            row.update(getattr(eng, 's06_day_stats', {}))
        res[m] = row
        print(f'[anchors] {m}: n={row["n"]} total={row["total"]:+,.2f}', flush=True)
    ht_n = sum(1 for t in eng.pool if (t[eng.fi['track_tier']] is None or str(t[eng.fi['track_tier']]) == 'none'))
    checks = dict(
        p0_total=float(res['p0']['total']), anchor_p0=CC.ANCHOR['P0'],
        p1_total=float(res['p1']['total']), anchor_p1=CC.ANCHOR['P1'],
        new14_total=float(res['new14']['total']), anchor_new14=CC.ANCHOR['NEW14'],
        new14_mdd=float(res['new14'].get('mdd_realized', 0)), anchor_mdd=CC.ANCHOR['NEW14_MDD'],
        a9_margin=float(res['a9']['margin_vs_p1']), published_margin=CC.A9_MARG_PUBLISHED,
        has_track_none_null_n=ht_n, anchor_has_track_n=1982)
    drift = {}
    for k, pub in [('p0_total', 'anchor_p0'), ('p1_total', 'anchor_p1'),
                   ('new14_total', 'anchor_new14'), ('new14_mdd', 'anchor_mdd'),
                   ('a9_margin', 'published_margin')]:
        obs, anc = checks[k], checks[pub]
        rel = abs(obs - anc) / max(abs(anc), 1e-9)
        drift[k] = dict(observed=obs, published=anc, drift_pct=round(rel * 100, 3), PASS=bool(rel <= 0.01))
    drift['has_track_none_null_n'] = dict(observed=ht_n, published=1982, PASS=bool(ht_n == 1982))
    cc_cmp = {}
    cc_anchor_path = os.path.join(CC_DIR, 'cc_anchors.json')
    if os.path.exists(cc_anchor_path):
        with open(cc_anchor_path) as f:
            cca = json.load(f)
        for m, fields in [('p0', ['total']), ('p1', ['total']),
                          ('new14', ['total', 'mdd_realized', 'mdd_trough']),
                          ('a9', ['total', 'margin_vs_p1']), ('new15', ['total']), ('s06', ['total'])]:
            for fld in fields:
                a_val, b_val = res[m].get(fld), (cca.get('observed', {}).get(m, {}) or {}).get(fld)
                if a_val is not None and b_val is not None:
                    same = (abs(float(a_val) - float(b_val)) < 0.01) if fld != 'mdd_trough' else (a_val == b_val)
                    cc_cmp[f'{m}.{fld}'] = dict(h_ext=a_val, cc=b_val, match=bool(same))
        cc_cmp['pool_track_tier_none'] = dict(h_ext=ht_n, cc=cca.get('pool_track_tier_none'),
                                              match=bool(ht_n == cca.get('pool_track_tier_none')))
    all_pass = all(v['PASS'] for v in drift.values())
    out = dict(generated_at=eng.gen_at, published_anchors=CC.ANCHOR, observed=res,
               drift_checks=drift, anchors_all_pass=all_pass, cc_cross_check=cc_cmp,
               note='发布锚点=memory test-baseline-v112-anchor(v1.1.6, 2026-08-23/24时点); 产物每日重生致<0.25%漂移属预期')
    with open(os.path.join(OUT_DIR, 'h_anchors.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('[anchors] ALL_PASS =', all_pass, flush=True)
    print('[anchors] cc双实现对照 match计数:',
          f"{sum(1 for v in cc_cmp.values() if isinstance(v, dict) and v.get('match'))}/{sum(1 for v in cc_cmp.values() if isinstance(v, dict))}",
          flush=True)
    return sel


def main():
    global _GEN_AT
    ap = argparse.ArgumentParser()
    ap.add_argument('--anchors', action='store_true')
    ap.add_argument('--all', action='store_true')
    a = ap.parse_args()
    eng = CC.Engine()
    _GEN_AT = eng.gen_at
    fi = eng.fi
    print(f'data generated_at={eng.gen_at} poolA_n={len(eng.pool)} rows8_n={len(eng.rows8)} '
          f'range={min(str(t[0]) for t in eng.pool)}~{max(str(t[0]) for t in eng.pool)} '
          f'track_none_or_null={sum(1 for t in eng.pool if (t[fi["track_tier"]] is None or str(t[fi["track_tier"]]) == "none"))}',
          flush=True)
    sel = run_anchors(eng)
    if not a.all:
        return

    CC.FI_BUY = fi['buy_date']
    CC.FI_SELL = fi['sell_date']
    ext = CC.Extender(eng)

    today_str = ext.today_str
    pool_dates = [str(t[0]) for t in eng.pool]
    first_sd, last_sd = min(pool_dates), max(pool_dates)
    span_years = round((datetime.date(int(last_sd[:4]), int(last_sd[4:6]), int(last_sd[6:])) -
                        datetime.date(int(first_sd[:4]), int(first_sd[4:6]), int(first_sd[6:]))).days / 365.25, 2)
    near_cut = (datetime.date(int(last_sd[:4]), int(last_sd[4:6]), int(last_sd[6:]))
                - datetime.timedelta(days=365)).strftime('%Y%m%d')

    # cc_matrix.json 对照引用(报告咬合用)
    cc_ref = {}
    with open(os.path.join(CC_DIR, 'cc_matrix.json')) as f:
        ccm = json.load(f)
    for m in MODES_ALL:
        cc_ref[m] = {}
        for vn in ['BASE', 'V1', 'V2', 'V2G']:
            if vn in ccm.get('ledger', {}).get(m, {}):
                occ_cc = ccm.get('occupancy', {}).get(m, {}).get(vn, {})
                cc_ref[m][vn] = dict(
                    ledger_total=ccm['ledger'][m][vn].get('total'),
                    rep13=ccm.get('replay_cap13', {}).get(m, {}).get(vn, {}).get('total_merged'),
                    occupancy_peak=occ_cc.get('peak_open_n'),
                    extra_area=occ_cc.get('extra_area_wan_yuan_days'))
    del ccm

    matrix = dict(
        meta=dict(executor='Claude Code(h-ext侧)', generated_at=eng.gen_at, today_str=today_str,
                  span_years=span_years, near1y_cutoff=near_cut,
                  fee='FP_DEF etf_def 佣万3/min5+滑千1+沪过户万0.1+卖印花万5, PRIN=10000(K1账本)',
                  replay_method="mine27.replay3 'v2回补极简' cap13/15/20/nocap",
                  variant_defs=dict(
                      HT='总持有帽: 帽位=基线卖日+(H-10)个ETF交易日(H=15/20/30/60, 主口径)',
                      HX='延长帽: 帽位=基线卖日+H个交易日(对照)',
                      INF='无帽纯回本等待(=cc V1, 交叉验证列)', HT10='机检列: 退化=BASE'),
                  recover_rule='窗口[基线卖日+1,帽位]首个net>=PRIN收盘日卖; 否则帽日强卖(帽日无nav顺延至下个有价日)',
                  naming_warning='本报告 HT/HX 系列=带帽回本等待; 与 cc 对照列 V2(sell+sell_stop_loss=引擎卖出模式H)'
                                 '完全不同义, 防混淆'),
        ledger={}, replay={}, occ_base={}, occ_dist={}, yearly_delta={}, extension_meta={},
        halves={}, bears={}, near1y={}, checks={}, cc_reference=cc_ref)

    detail_out = {}
    for m in MODES_ALL:
        base_rows = sel[m]
        var_rows, meta, detail, deltas = build_h_variants(ext, base_rows)
        plans = [(t, t[R.IDX_PNL]['pnlYuan'], str(t[fi['sell_date']] or ''))
                 for t in base_rows
                 if str(t[fi['sell_date']] or '') and t[R.IDX_PNL]['pnlYuan'] < 0]
        matrix['ledger'][m] = {}
        matrix['replay'][m] = {}
        matrix['occ_base'][m] = CC.occupancy(base_rows, base_rows, today_str, ext.sdates)
        matrix['occ_dist'][m] = {}
        matrix['yearly_delta'][m] = {}
        matrix['bears'][m] = {}
        matrix['near1y'][m] = {}
        matrix['checks'][m] = {}
        matrix['halves'][m] = halves_by_plan(plans, deltas, VARIANTS)
        print(f'[mode {m}] losers={meta["n_loser_plans"]} tails={meta["n_tail_holding"]} 计算 {len(VARIANTS)} 变体 ...',
              flush=True)
        for vn in VARIANTS:
            rows = var_rows[vn]
            matrix['ledger'][m][vn] = CC.ledger_stats(rows, fi)
            matrix['ledger'][m][vn]['recovery'] = ledger_recovery(rows, fi, today_str)
            matrix['ledger'][m][vn]['merged_recovery_ledgercurve'] = merged_curve_recover(ext, rows, fi, today_str)
            matrix['replay'][m][vn] = {('nocap' if c is None else f'cap{c}'): replay_full(
                rows, fi, c, span_years, near_cut, today_str) for c in CAPS}
            try:
                matrix['occ_dist'][m][vn] = occupancy_dist(base_rows, rows, today_str)
            except Exception as ex:
                matrix['occ_dist'][m][vn] = dict(error=str(ex))
            yy = {}
            yb = {}
            for t in base_rows:
                yb[str(t[0])[:4]] = yb.get(str(t[0])[:4], 0.0) + t[R.IDX_PNL]['pnlYuan']
            for t in rows:
                y = str(t[0])[:4]
                yy[y] = yy.get(y, 0.0) + t[R.IDX_PNL]['pnlYuan']
            matrix['yearly_delta'][m][vn] = {y: dict(base=round(yb.get(y, 0.0), 2), var=round(yy.get(y, 0.0), 2),
                                                     delta=round(yy.get(y, 0.0) - yb.get(y, 0.0), 2))
                                             for y in sorted(set(yb) | set(yy))}
            br = {}
            for lab, w1, w2 in M27.BEARS26:
                wb = [t for t in base_rows if w1 <= str(t[0]) <= (w2 or '99999999')]
                wv = [t for t in rows if w1 <= str(t[0]) <= (w2 or '99999999')]
                br[lab] = dict(n=len(wv), base=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in wb), 2),
                               var=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in wv), 2),
                               delta=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in wv) -
                                           sum(t[R.IDX_PNL]['pnlYuan'] for t in wb), 2))
            matrix['bears'][m][vn] = br
            nw = [t for t in rows if str(t[0]) >= near_cut]
            nb = [t for t in base_rows if str(t[0]) >= near_cut]
            matrix['near1y'][m][vn] = dict(cutoff=near_cut, n=len(nw),
                                           base=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in nb), 2),
                                           var=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in nw), 2),
                                           delta=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in nw) -
                                                       sum(t[R.IDX_PNL]['pnlYuan'] for t in nb), 2))
        # 机检①: HT10 退化校验(日期层必须逐位=BASE; 金额层残差=价格源效应测量)
        h10 = var_rows['HT10']
        plans_map = {i: (t, bt) for i, (t, bt) in enumerate(zip(h10, base_rows))}
        n_same_exit = n_diff_exit = 0
        amt_resid = 0.0
        sample_resid = []
        for i, (vt, bt) in plans_map.items():
            bd = str(bt[fi['sell_date']] or '')
            vd = str(vt[fi['sell_date']] or '')
            rb = bt[R.IDX_PNL]['pnlYuan']
            rv = vt[R.IDX_PNL]['pnlYuan']
            is_plan = bool(bd) and rb < 0
            if not is_plan:
                continue
            if vd == bd:
                n_same_exit += 1
            else:
                n_diff_exit += 1
                sample_resid.append(dict(sd=str(bt[0]), etf=bt[fi['etf_code']],
                                         base_sell=bd, ht10_exit=vd))
            amt_resid += rv - rb
        # 机检④: 参数等价性 HT30 ≡ HX20(同为额外等待K=20td), 独立两次计算应逐位一致
        pdiff = max(abs(va[R.IDX_PNL]['pnlYuan'] - vb[R.IDX_PNL]['pnlYuan'])
                    for va, vb in zip(var_rows['HT30'], var_rows['HX20']))
        matrix['checks'][m]['HT30_eq_HX20_identity'] = dict(max_abs_pnl_diff=round(pdiff, 6),
                                                           PASS=bool(pdiff < 1e-6))
        matrix['checks'][m]['HT10_degenerate_vs_BASE'] = dict(
            n_plans=len(plans),
            n_exit_same=n_same_exit, n_exit_diff=n_diff_exit,
            exit_identity_rate_pct=round(n_same_exit / max(n_same_exit + n_diff_exit, 1) * 100, 2),
            amount_residual_yuan=round(amt_resid, 2),
            residual_note='金额残差=纯价格源效应(trades.sell_price 引擎价 vs etf_daily.accum_nav 重构价, '
                          '与 cc make_row 口径一致的系统性微差, 非逻辑错); 各H档净差的adjusted读法=raw减此残差',
            sample_exit_diffs=sample_resid[:5],
            PASS=(n_diff_exit == 0))
        matrix['extension_meta'][m] = meta
        detail_out[m] = detail
        led = matrix['ledger'][m]
        rp13 = matrix['replay'][m]
        print(f"[mode {m}] ledger B={led['BASE']['total']:+,.0f} INF={led['INF']['total']:+,.0f} "
              f"HT15={led['HT15']['total']:+,.0f} HT20={led['HT20']['total']:+,.0f} "
              f"HT30={led['HT30']['total']:+,.0f} HT60={led['HT60']['total']:+,.0f}", flush=True)
        print(f"[mode {m}] rep13 B={rp13['BASE']['cap13']['total_merged']:+,.0f} "
              f"INF={rp13['INF']['cap13']['total_merged']:+,.0f} "
              f"HT15={rp13['HT15']['cap13']['total_merged']:+,.0f} "
              f"HT20={rp13['HT20']['cap13']['total_merged']:+,.0f} "
              f"HT30={rp13['HT30']['cap13']['total_merged']:+,.0f} "
              f"HT60={rp13['HT60']['cap13']['total_merged']:+,.0f}", flush=True)

    # adjusted 口径: 各变体账本净差(vs BASE)减去价格源残差(HT10 测得)
    for m in MODES_ALL:
        resid = matrix['checks'][m]['HT10_degenerate_vs_BASE']['amount_residual_yuan']
        adj = {}
        for vn in VARIANTS:
            if vn == 'BASE':
                continue
            raw_d = round(matrix['ledger'][m][vn]['total'] - matrix['ledger'][m]['BASE']['total'], 2)
            rp13d = round(matrix['replay'][m][vn]['cap13']['total_merged'] -
                          matrix['replay'][m]['BASE']['cap13']['total_merged'], 2)
            adj[vn] = dict(raw_ledger_delta=raw_d, adjusted_ledger_delta=round(raw_d - resid, 2),
                           raw_rep13_delta=rp13d)
        matrix['checks'][m].setdefault('price_source_adjusted', {})
        matrix['checks'][m]['price_source_adjusted'] = dict(residual=resid, variants=adj)

    # 机检②: INF 对齐 cc V1(逐模式对照)
    inf_check = {}
    for m in MODES_ALL:
        a_inf = matrix['ledger'][m]['INF']['total']
        b_v1 = cc_ref[m]['V1']['ledger_total']
        inf_check[m] = dict(h_ext_INF=a_inf, cc_V1=b_v1,
                            abs_diff=round(abs(a_inf - float(b_v1)), 2),
                            PASS=bool(abs(a_inf - float(b_v1)) < max(abs(float(b_v1)) * 0.01, 200)))
    matrix['checks']['INF_vs_ccV1'] = inf_check

    with open(os.path.join(OUT_DIR, 'h_variants.json'), 'w') as f:
        json.dump(dict(meta=dict(generated_at=eng.gen_at,
                                 note='带帽回本等待变体亏损单逐笔明细(exit/how/ext_td/pnl)'),
                       modes=detail_out), f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, 'h_matrix.json'), 'w') as f:
        json.dump(matrix, f, ensure_ascii=False, indent=1)
    print('saved h_variants/h_matrix json; checks:', json.dumps(matrix['checks'], ensure_ascii=False)[:800],
          flush=True)


if __name__ == '__main__':
    main()
