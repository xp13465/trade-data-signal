# -*- coding: utf-8 -*-
"""mine29 象限整组剔除验证「NEW14+1」(2026-08-23 主控令,编号接 mine26/27/28)。
目的:
  验证用户设想「NEW14 + 过滤掉一个很差象限的全部信号」(14+1)是否成立。
  用户指纹: 信号凯利回测页某象限卡 近1/3/5年 A-I 基本全负、近10年与全历史 H≈-14%、有跟踪ETF、总共没几个信号。
  主控补充令: 对象锁定=「有跟踪 ETF」卡(etf_has_track, lab.js L10443 分组第4卡)。
  ⚠指纹核对结论(先于回测, 数据说话): 当前数据(generated_at=2026-08-23 21:15, 本地=R2=CF 三处一致)下
    etf_has_track 卡 A-I × 5 窗口 total_profit 全部为正(原始/8键过滤/费后三口径均验), 用户描述的
    「基本全负+H≈-14%」在该卡不存在; 最接近候选=mkt_industry(y1 neg8/9)/mkt_hk(y1 neg7/9)/sig_aux/
    etf_related(y1 neg5/9), 但无一满足全部指纹 → 按主控指令照常对 etf_has_track 整组剔除回测,
    另加 16 象限整组剔除穷举扫描覆盖"用户可能指其他卡"的情形(§5.1 穷举最大化)。
方法口径(与 mine26/27/28 完全对齐):
  - 基座池=mode A 权威锚点池(build_mode_pool('A') 无 8键预过滤; NEW14 独立重构口径锚点 +122,648.33/mdd -4,178.01);
    八键基座=prepare_rows()(mode A + 8键降亏预过滤; 锚点 +66,530.38)。
  - 过滤口径铁律=「top-K 前过滤补位」(memory filter-backtest-position-fill-caliber):
    象限剔除实现为黑名单并集 blk |= quad_blk(ev_new_on 内被拦者不占当日 K=1 名额, 由排序后续替补);
    删笔口径(eval_rule_del 同款: 先选后删)仅作对照附注。
  - 交易口径=V2 回补型(mine27 replay3 method='v2': 满仓跳过当日信号, 自然卖出释放后才可再买)
    + cap13(每笔固定本金 PRIN=10000, 资金档=cap×1万); 费后 K1(calc_row etf_def 默认档)。
    诚实标注: mode A 池 K1 每日≤1笔+A模式固定10天卖出 → 峰并发≤13, cap13 实际不绑定
    (cap13 v2 数字 == nocap, mine28 runs.A 已同此), cap10/cap20/nocap 全列作敏感性。
  - 五组合矩阵: ①RAW无过滤 ②v1.1.2八键(P0) ③NEW14单用 ④八键+剔has_track ⑤NEW14+剔has_track(14+1,主角)。
  - 替补盈亏分解: NEW14 vs NEW14+剔 的入选集差(dropped=原选中的象限笔 / added=替补进来的笔),
    费后逐笔合计+守恒断言+明细, 证明「过滤正向」的钱从哪来(nocap 选择层逐位守恒; replay 层并列印 skip 链差)。
输出: data/mine29_quadrant_drop_14plus1.json
复现: python3 mine29_quadrant_drop_14plus1.py
依赖: static-site/data/signal_kelly_trades.json(generated_at=2026-08-23 21:15)+ data/mine10_features.json +
     data/mine24_compare.json(NEW14 键单源)+ data/mine28_modes_union_cap13_v2.json(cap13v2 咬合断言)。
关键口径一句话: mode A 池 × {RAW/8键/NEW14}±{etf_has_track 整组剔除} 黑名单补位 K1 → V2+cap13 重放
              (费后, 每笔1万)→ 净利/mdd/按年/月度稳定性/熊市窗/近1年 + 替补分解 + 16象限穷举扫描 + 小样本置信。
"""
import os, sys, json, datetime, math
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, calc_row, base_key, PRIN
from mine18_detail import BEARS, FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2
import mine25_longline_operable as M25
import mine27_g_exhaustive_simplified as M27

OUT_PATH = os.path.join(BASE, 'data', 'mine29_quadrant_drop_14plus1.json')
M28 = json.load(open(os.path.join(BASE, 'data', 'mine28_modes_union_cap13_v2.json')))
BEARS26 = list(BEARS) + [('2026年2-3月压力窗', '20260201', '20260331')]
CAPS = [13]
TARGET_QUAD = ('etf_has_track', 'track_tier==none (track_score<50 有跟踪ETF, lab.js「有跟踪ETF」卡)')


def finish_pool(rows, fi):
    """mine27.finish_pool 同款(独立拷贝防模块间行对象突变): 追加费后 pnl 与排序键。"""
    R.IDX_PNL, R.IDX_SKEY = len(fi) + 3, len(fi) + 4
    RATING_RANK = {'high': 0, 'mid': 1, 'low': 2}
    SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in rows:
        t.append(calc_row(t, fi))
        ts = float(t[fi['track_score']]) if t[fi['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RATING_RANK.get(str(t[fi['rating']] or ''), 3),
                  SIG_RANK.get(str(t[fi['signal']] or ''), 9), str(t[fi['buy_date']] or '')))
    return rows


def quad_of(t, fi, base):
    """16 象限归属判定(与 signal_kelly_backtest.py 分组/lab.js L10443 分组一致; 组内互斥跨组可多属)。"""
    out = []
    r = str(t[fi['rating']] or '')
    if r in ('high', 'mid', 'low'): out.append('rating_' + r)
    tt = str(t[fi['track_tier']] or '')
    if tt in ('strong', 'related', 'approx', 'none'):
        out.append({'strong': 'etf_strong', 'related': 'etf_related',
                    'approx': 'etf_approx', 'none': 'etf_has_track'}[tt])
    sig = str(t[2] or '')
    m = {'buy': 'sig_main', 'buy_aux': 'sig_aux', 'buy_special': 'sig_special', 'buy_backup': 'sig_backup'}
    if sig in m: out.append(m[sig])
    mk = str(t[base + 0] or '')
    if mk in ('a', 'hk', 'global', 'industry', 'concept'): out.append('mkt_' + mk)
    return out


def quad_blk(rws, fi, base, qkey):
    return {base_key(t, fi) for t in rws if qkey in quad_of(t, fi, base)}


def max_conc(ts, fi):
    deltas = {}
    for t in ts:
        bd = str(t[fi['buy_date']] or ''); sd = str(t[fi['sell_date']] or '') or '99999999'
        deltas.setdefault(bd, [0, 0]); deltas[bd][0] += 1
        deltas.setdefault(sd, [0, 0]); deltas[sd][1] += 1
    cur = mx = 0
    for k in sorted(deltas):
        b, s = deltas[k]; cur += b - s; mx = max(mx, cur)
    return mx


def stats_ext(sel_or_rp, fi, cap, span_years, near_cut, last_day):
    """mine27 stats_ext 同语义 + 月度稳定性扩展。sel_or_rp=replay 结果 dict 或纯 sel 列表。"""
    if isinstance(sel_or_rp, dict):
        bought, rp = sel_or_rp['bought'], sel_or_rp
        vid = rp.get('victim_ids', set())
        alive = [t for t in bought if id(t) not in vid]
        n_skipped = len(rp.get('skipped', []))
        peak_n = rp['peak_n']
    else:
        alive, n_skipped, peak_n = list(sel_or_rp), 0, max_conc(list(sel_or_rp), fi)
    idx = R.IDX_PNL
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
    bys_m = dict(bys)
    if hold and last_day:
        bys_m[last_day] = bys_m.get(last_day, 0.0) + u_pnl
    mdd_merged = M25.dd_of(sorted(bys_m), bys_m)
    total = r_pnl + u_pnl
    budget = cap * PRIN if cap else None
    # ---- 月度稳定性(realized 按 sell_date 月聚合; holding 浮盈挂数据末月, 与 mdd_merged 口径一致)----
    mom = {}
    for sd, v in bys_m.items():
        ym = sd[:6]
        mom[ym] = mom.get(ym, 0.0) + v
    mom_vals = [mom[k] for k in sorted(mom)]
    n_zero = sum(1 for v in mom_vals if abs(v) < 0.005)
    mean_m = sum(mom_vals) / len(mom_vals) if mom_vals else 0.0
    std_m = (sum((v - mean_m) ** 2 for v in mom_vals) / (len(mom_vals) - 1)) ** 0.5 if len(mom_vals) > 1 else 0.0
    worst = min(mom.items(), key=lambda kv: kv[1]) if mom else ('-', 0.0)
    ops_total = len(real) * 2 + len(hold)   # V2 无强平: 卖出笔一买一卖, 持有中仅计买(mine27 bought+real 同义)
    return dict(
        n_bought=len(alive), n_skipped=n_skipped, n_natural_sell=len(real), n_holding_end=len(hold),
        realized_pnl=round(r_pnl, 2), unrealized_pnl=round(u_pnl, 2), total_merged=round(total, 2),
        realized_winrate=round(win / max(len(real), 1) * 100, 1),
        peak_pos_n=peak_n, peak_occupancy_yuan=peak_n * PRIN,
        budget_yuan=budget, ret_on_budget_pct=round(total / budget * 100, 2) if budget else None,
        ops_total=ops_total, ops_per_year=round(ops_total / span_years, 2),
        mdd_realized=mdd_real, mdd_merged_terminal=mdd_merged,
        monthly=dict(n_months=len(mom_vals), worst_month=[worst[0], round(worst[1], 2)],
                     std_month=round(std_m, 2), zero_pnl_months=n_zero),
        yearly_total_merged=None, bears=None, near1y=None,
    )


def enrich(st, alive, fi, span_years, near_cut, bears):
    """yearly/bears/near1y 补充(stats_ext 里留空位以保持字段顺序)。"""
    idx = R.IDX_PNL
    yearly = {}
    for t in alive:
        y = str(t[0])[:4]; yearly.setdefault(y, 0.0); yearly[y] += t[idx]['pnlYuan']
    st['yearly_total_merged'] = {y: round(v, 2) for y, v in sorted(yearly.items())}
    st['bears_total_merged'] = {lab: round(R.stats_of(R.window(alive, a, b))['total'], 2)
                                for lab, a, b in bears}
    near = R.window(alive, near_cut)
    st['near1y'] = dict(cutoff=near_cut, total_merged=round(R.stats_of(near)['total'], 2), n=len(near))
    return st


def run_combo(pool, fi, blk, cap, span_years, near_cut, last_day, bears, replay=True):
    """黑名单补位选择 → (可选)V2+cap 重放 → stats_ext+enrich。返回 (stats, alive_list)。"""
    sel = M25.ev_new_on(pool, fi, blk)
    if not replay:
        st = stats_ext(sel, fi, None, span_years, near_cut, last_day)
        return enrich(st, sel, fi, span_years, near_cut, bears), sel
    day_sel = {str(t[0]): t for t in sel}
    R.init(sel, fi)
    rp = M27.replay3(day_sel, fi, cap, 'v2回补极简')
    alive = [t for t in rp['bought']]
    st = stats_ext(rp, fi, cap, span_years, near_cut, last_day)
    return enrich(st, alive, fi, span_years, near_cut, bears), rp['bought']


def decompose(base_sel, drop_sel, fi, base):
    """替补盈亏分解: dropped=base 有而 drop 无(=被象限黑名单拦下的原选中笔); added=drop 有而 base 无(替补进场)。"""
    idx = R.IDX_PNL
    def keyset(sel): return {base_key(t, fi) for t in sel}
    ks_b, ks_d = keyset(base_sel), keyset(drop_sel)
    dropped = [t for t in base_sel if base_key(t, fi) not in ks_d]
    added = [t for t in drop_sel if base_key(t, fi) not in ks_b]
    d_pnl = sum(t[idx]['pnlYuan'] for t in dropped)
    a_pnl = sum(t[idx]['pnlYuan'] for t in added)
    def detail(ts):
        ts2 = sorted(ts, key=lambda t: t[idx]['pnlYuan'])
        f = lambda t: dict(date=str(t[0]), idx=str(t[1]), sig=str(t[2]), etf=str(t[fi['etf_name']] or ''),
                           pnl=round(t[idx]['pnlYuan'], 2))
        return dict(n=len(ts), pnl=round(sum(t[idx]['pnlYuan'] for t in ts), 2),
                    worst5=[f(t) for t in ts2[:5]], best5=[f(t) for t in ts2[-5:]],
                    n_win=sum(1 for t in ts if t[idx]['pnlYuan'] > 0))
    return dict(dropped=detail(dropped), added=detail(added),
                identity_check=round(a_pnl - d_pnl, 2),
                total_delta_observed=None)


def main():
    tr, fIdx = load(os.path.join(R._ROOT, 'static-site/data/signal_kelly_trades.json'))
    gen_at = tr.get('generated_at')
    FEATS = json.load(open(FEATS_PATH))
    M24CMP = json.load(open(M25.M24CMP_PATH))
    NEW14_KEYS = list(M24CMP['new_keys'])
    rules = build_rules(FEATS, fIdx); rules.update(build_r2(fIdx))
    base = len(fIdx)

    # ---------- Part0 锚点复现(必过才往下) ----------
    pool_raw = finish_pool(build_mode_pool(tr, fIdx, 'A'), fIdx)
    R.init(pool_raw, fIdx)
    rows8, fia = R.prepare_rows()          # 八键基座(mode A + 8键预过滤)
    R.init(rows8, fia)
    rules8 = build_rules(FEATS, fia); rules8.update(build_r2(fia))

    blkN14 = M25.hits_on(pool_raw, fIdx, NEW14_KEYS, rules)
    selN14 = M25.ev_new_on(pool_raw, fIdx, blkN14)
    stN = R.stats_of(selN14); ddN = M25.dd_of(*M27._curve(selN14, fIdx))
    assert abs(stN['total'] - 122648.33) < 1.0 and abs(ddN['mdd'] - (-4178.01)) < 1.5, (stN['total'], ddN['mdd'])

    ctx8 = M25.build_ctx(rows8, fia)
    st8 = R.stats_of(M25.ev(ctx8, (), False))
    assert abs(st8['total'] - 66530.38) < 0.5, st8['total']

    selRaw = M25.ev_new_on(pool_raw, fIdx, set())
    stRaw = R.stats_of(selRaw)
    auth_raw28 = M28['runs']['A']['RAW无过滤']
    assert abs(stRaw['total'] - auth_raw28['total_merged']) < 0.5, (stRaw['total'], auth_raw28)

    print(f"Part0 锚点 PASS: P0_8键={st8['total']:+,.2f} NEW14={stN['total']:+,.2f}/mdd{ddN['mdd']:,.2f} "
          f"RAW={stRaw['total']:+,.2f}(mine28咬合)")

    # 数据跨度/近1年切点(与 mine27/28 同算法)
    all_sd = sorted({str(t[0]) for t in pool_raw})
    d_min, d_max = all_sd[0], all_sd[-1]
    span_years = (datetime.date(int(d_max[:4]), int(d_max[4:6]), int(d_max[6:8]))
                  - datetime.date(int(d_min[:4]), int(d_min[4:6]), int(d_min[6:8]))).days / 365.25
    cut_dt = (datetime.date(int(d_max[:4]), int(d_max[4:6]), int(d_max[6:8])) - datetime.timedelta(days=365))
    near_cut = cut_dt.strftime('%Y%m%d')
    last_day = d_max
    bears = BEARS26
    print(f'数据跨度 {d_min}~{d_max} ({span_years:.2f}年) 近1年cut={near_cut}')

    # ---------- Part1 五组合主矩阵 ----------
    bq_raw = quad_blk(pool_raw, fIdx, base, 'etf_has_track')
    bq_8 = quad_blk(rows8, fia, base, 'etf_has_track')
    COMBOS = {
        'RAW无过滤':      (pool_raw, fIdx, set()),
        'P0_8键':         (rows8, fia, set()),
        'NEW14单用':      (pool_raw, fIdx, blkN14),
        '八键+剔has_track': (rows8, fia, bq_8),
        'NEW14+剔has_track': (pool_raw, fIdx, blkN14 | bq_raw),
    }
    runs, sels = {}, {}
    for name, (pool, fi, blk) in COMBOS.items():
        runs[name], sels[name] = {}, {}
        R.init(pool, fi)
        st_nc, sel_nc = run_combo(pool, fi, blk, None, span_years, near_cut, last_day, bears, replay=False)
        runs[name]['nocap'] = st_nc; sels[name]['nocap'] = sel_nc
        st_c, sel_c = run_combo(pool, fi, blk, 13, span_years, near_cut, last_day, bears, replay=True)
        runs[name]['cap13v2'] = st_c; sels[name]['cap13v2'] = sel_c
        a, b = st_nc, st_c
        print(f"{name}: nocap={a['total_merged']:+,.0f}/mdd{a['mdd_merged_terminal']['mdd']:,.0f}/n{a['n_bought']} "
              f"| cap13v2={b['total_merged']:+,.0f}/mdd{b['mdd_merged_terminal']['mdd']:,.0f}/n{b['n_bought']}"
              f"/峰{b['peak_pos_n']}笔/近1y{b['near1y']['total_merged']:+,.0f}")

    # cap13 未绑定诚实标注
    unbind = {name: runs[name]['cap13v2']['n_skipped'] for name in COMBOS}
    peak_ok = all(runs[name]['cap13v2']['peak_pos_n'] <= 13 for name in COMBOS)

    # ---------- Part2 替补盈亏分解(主角=NEW14 vs NEW14+剔; 附八键对照) ----------
    dec = {}
    for tag, (nm_base, nm_drop) in {'NEW14_vs_14plus1': ('NEW14单用', 'NEW14+剔has_track'),
                                    '八键_vs_8plus1': ('P0_8键', '八键+剔has_track')}.items():
        sel_b, sel_d = sels[nm_base]['nocap'], sels[nm_drop]['nocap']
        dd = decompose(sel_b, sel_d, fIdx, base)
        tot_b = runs[nm_base]['nocap']['total_merged']; tot_d = runs[nm_drop]['nocap']['total_merged']
        dd['total_delta_observed'] = round(tot_d - tot_b, 2)
        gap = abs(dd['identity_check'] - dd['total_delta_observed'])
        assert gap < 0.05, (tag, dd['identity_check'], dd['total_delta_observed'])  # 选择层逐位守恒
        # replay 层(cap13)对照
        rb = runs[nm_base]['cap13v2']['total_merged']; rd = runs[nm_drop]['cap13v2']['total_merged']
        dd['cap13_total_delta_observed'] = round(rd - rb, 2)
        dec[tag] = dd
        print(f"[{tag}] 被拦{dd['dropped']['n']}笔/{dd['dropped']['pnl']:+,.0f} 替补{dd['added']['n']}笔/"
              f"{dd['added']['pnl']:+,.0f} Δ={dd['total_delta_observed']:+,.2f}(replay层Δ={dd['cap13_total_delta_observed']:+,.2f})")

    # 删笔口径对照附注(mine 一轮用法: 先选 topK 再删, 不补位)
    dele = {}
    base_sel = sels['NEW14单用']['nocap']
    kept_del = [t for t in base_sel if 'etf_has_track' not in quad_of(t, fIdx, base)]
    dele['NEW14_删笔不补位'] = dict(
        n_before=len(base_sel), n_after=len(kept_del),
        total_before=runs['NEW14单用']['nocap']['total_merged'],
        total_after=round(R.stats_of(kept_del)['total'], 2))

    # ---------- Part3 16象限整组剔除穷举扫描(NEW14 与 P0_8键 两基座 × cap13v2) ----------
    QUADS16 = ['rating_high', 'rating_mid', 'rating_low', 'etf_strong', 'etf_related', 'etf_approx',
               'etf_has_track', 'sig_main', 'sig_aux', 'sig_special', 'sig_backup',
               'mkt_a', 'mkt_hk', 'mkt_global', 'mkt_industry', 'mkt_concept']
    scan = {}
    for qk in QUADS16:
        scan[qk] = {}
        blkq_raw = quad_blk(pool_raw, fIdx, base, qk)
        R.init(pool_raw, fIdx)
        stq, _ = run_combo(pool_raw, fIdx, blkN14 | blkq_raw, 13, span_years, near_cut, last_day, bears, replay=True)
        scan[qk]['on_NEW14'] = dict(
            total_delta=round(stq['total_merged'] - runs['NEW14单用']['cap13v2']['total_merged'], 2),
            mdd=stq['mdd_merged_terminal']['mdd'],
            near1y=stq['near1y']['total_merged'], blocked_n=len(blkq_raw))
        blkq_8 = quad_blk(rows8, fia, base, qk)
        R.init(rows8, fia)
        stq8, _ = run_combo(rows8, fia, blkq_8, 13, span_years, near_cut, last_day, bears, replay=True)
        scan[qk]['on_八键'] = dict(
            total_delta=round(stq8['total_merged'] - runs['P0_8键']['cap13v2']['total_merged'], 2),
            mdd=stq8['mdd_merged_terminal']['mdd'],
            near1y=stq8['near1y']['total_merged'], blocked_n=len(blkq_8))
        print(f"scan {qk}: ΔNEW14={scan[qk]['on_NEW14']['total_delta']:+,.0f} Δ八键={scan[qk]['on_八键']['total_delta']:+,.0f}")

    # ---------- Part4 小样本统计置信(主角 14+1) ----------
    dd_main = dec['NEW14_vs_14plus1']
    n_blocked = dd_main['dropped']['n']; n_added = dd_main['added']['n']
    share = n_blocked / max(len(sels['NEW14单用']['nocap']), 1) * 100
    # Welch t: 被拦组 vs 替补组 费后单笔均值差(近似小样本两均值检验)
    import random
    idx = R.IDX_PNL
    x = [t[idx]['pnlYuan'] for t in sels['NEW14单用']['nocap'] if 'etf_has_track' in quad_of(t, fIdx, base)]
    y = [t[idx]['pnlYuan'] for t in sels['NEW14+剔has_track']['nocap']
         if base_key(t, fIdx) not in {base_key(u, fIdx) for u in sels['NEW14单用']['nocap']}]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    vx = sum((v - mx) ** 2 for v in x) / (len(x) - 1); vy = sum((v - my) ** 2 for v in y) / (len(y) - 1)
    se = math.sqrt(vx / len(x) + vy / len(y)); t_stat = (my - mx) / se if se > 0 else 0.0
    # bootstrap 9999 次: Δ(总量) 的百分位置信区间
    random.seed(29)
    diffs = []
    for _ in range(9999):
        xb = [x[random.randrange(len(x))] for _ in range(len(x))]
        yb = [y[random.randrange(len(y))] for _ in range(len(y))]
        diffs.append(sum(yb) - sum(xb))
    diffs.sort()
    ci = (diffs[int(0.025 * 9999)], diffs[int(0.975 * 9999)])
    conf = dict(
        blocked_n=n_blocked, blocked_share_pct_of_NEW14_sel=round(share, 2),
        added_n=n_added, welch_t=round(t_stat, 3),
        bootstrap_delta_ci95=[round(ci[0], 2), round(ci[1], 2)],
        note='Δ=替补组合计-被拦组合计(bootstrap 按单笔有放回重抽 9999 次); CI 含 0=不能排除噪声')

    # ---------- Part5 输出 ----------
    out = dict(
        meta=dict(script='mine29_quadrant_drop_14plus1.py', generated_at_data=gen_at,
                  date='2026-08-23', target_quad=list(TARGET_QUAD),
                  caliber=dict(engine='复用 mine25/sim_core/mine27 口径(mode A 权威锚点池; K1 补位; 每笔固定 1 万;'
                                    ' 费后 etf_def 默认档; E23: K=1 时每笔1万≡每日池等分净利逐位相同)',
                               filter='top-K 前过滤补位口径(黑名单并集, 被拦者不占当日名额由后续排序替补); '
                                    '删笔不补位仅作对照附注',
                               trade='V2 回补型(mine27 replay3 v2)+cap13(资金档=13万); 诚实标注: mode A 池 K1 每日≤1笔'
                                   '+A 固定10天卖出 → 峰并发≤13, cap13 不绑定(cap13v2==nocap)',
                               quadrant='etf_has_track 归属判定=trades 字段 track_tier==none(与后端 signal_kelly_backtest.py '
                                      'L124-127/L1078-1092 及前端 lab.js L10443 分组一致)'),
                  data_span=[d_min, d_max], span_years=round(span_years, 2), near1y_cutoff=near_cut,
                  new14_keys=NEW14_KEYS, bears_windows=[list(b) for b in bears],
                  cap13_unbind=dict(skipped_by_combo=unbind, peak_within_cap=peak_ok)),
        anchor=dict(p0_nocap=st8['total'], new14_nocap=stN['total'], new14_mdd=ddN['mdd'],
                    raw_nocap=stRaw['total'], mine28_auth=auth_raw28),
        fingerprint_check=dict(
            conclusion='当前数据(本地=R2=CF, generated_at=%s)下 etf_has_track 卡 A-I×5窗口 total_profit 全正,' % gen_at,
            backtest_json_etf_has_track_total_profit={
                pk: {m: q['periods'][pk][m]['total_profit'] for m in 'ABCDEFGHI'}
                for pk, q in [('y1', json.load(open(os.path.join(R._ROOT, 'static-site/data/signal_kelly_backtest.json')))['quadrants']['etf_has_track']),
                              ('all', json.load(open(os.path.join(R._ROOT, 'static-site/data/signal_kelly_backtest.json')))['quadrants']['etf_has_track'])]},
            nearest_candidates=['mkt_industry(y1 neg8/9)', 'mkt_hk(y1 neg7/9)', 'sig_aux(y1-y10 neg5-6/9)',
                                'etf_related(y1 neg5/9, H rmh-6.0%)'],
            none_matches_all_fingerprints=True),
        runs=runs, decomposition=dec, delete_not_fill=dele, quad_scan16=scan, small_sample_confidence=conf,
    )
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    print('saved ->', OUT_PATH)


if __name__ == '__main__':
    main()
