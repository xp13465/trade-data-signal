# -*- coding: utf-8 -*-
"""mine30 「NEW14 设默认」三点实操质疑核实 + 信号枯竭结构性风险(2026-08-24 主控令,编号接 mine26-29)。
背景: v1.1.5 定稿在即(mine28 判决=AUTO 轮动证伪,维持单模式),主控建议 NEW14 设默认,用户以近期实盘视角反驳。
用户三断言(逐一真伪钉死):
  ① 「A 不止 2026-04 强,5 月至今也是正的,而 NEW14 是负的」→ A_on9 vs NEW14 2026-05~08 逐月+累计对照;
  ② 「NEW 最近信号过滤得太少,7/2 后就只有 720 一个信号」→ NEW14 口径 2026-06-01 至今全部放行买入信号清单
     (K1 入选=模拟回测弹窗实际显示买入)+ 裸信号池(mode A RAW 与 G RAW 双对照)同期量 +
     「市场本身没信号」vs「被 NEW14 拦光」逐日分类 + 被拦信号的键归属分布(哪个键拦得最狠);
  ③ 「NEW14 近 4 个月没一个月赚钱」→ 近 4 个月逐月盈亏表核实「零个正月份」。
结构性分析:
  ④ 全历史「连续无放行信号 ≥20/≥40/≥60 个交易日」次数/时长/恢复后 3 个月盈亏(交易日历=a-stock-all 上证日线,
     非信号日期代理);八键(P0)同表对照——回答"这次枯竭是常态还是异常";
  ⑤ 月月赚钱记分板:近 12 个月 A-I 九模式 RAW + NEW14 + 八键 逐月盈亏矩阵(V2 回补 cap13 重放后 bought 集),
     正月份个数/最长连亏月数/最差月/月度 std 重排座次;附 A-I × P0_8键 叠加矩阵(JSON);
  ⑥ v1.1.5 决策增量:A 近期强势性质分解(剔除 2025-12/2026-04 两事件月后的领先余额+2026-07 归因明细)、
     NEW14 逐键 leave-one-out 放宽敏感性(近期放行增量 vs 全史净利/mdd 代价)、NEW14∪8键 并集对照、
     枯竭提示阈值的历史形态依据。只列数据依据不预设推荐。
口径与纪律(§5.4/§5.1):
  - 测试基准=current baseline v1.1.2 八键(memory test-baseline-v112-anchor);主对象 NEW14=v1.1.5 候选(非基准默认,
    显式声明);两列都给。
  - 引擎=mode A 权威锚点池(sim_core)+ K1 补位(top-K 前黑名单过滤,被拦不占名额,memory
    filter-backtest-position-fill-caliber)+ V2 回补型重放(mine27 replay3)+ cap13(每笔固定 1 万×13 档)+
    费后 etf_def(calc_row)。mode A 池 K1 每日≤1 笔+A 固定卖出 → cap13 不绑定(n_skipped=0 断言),
    故选择层与重放层逐位一致,与 mine26 选择层逐月表可互相咬合(脚本内断言 <0.5)。
  - 锚点断言(必过才往下): P0=66,530.38 / P1=73,102.53 / A_on9=119,109.53 / NEW14=122,648.33(mdd -4,178.01)/
    mode A RAW cap13v2=5,904.42 / mode G RAW cap13v2=109,828.49 / G P0=125,541.58(mine24/28 咬合)。
  - 防前视声明: 本轮全部为纯历史静态统计与静态过滤组合评估,无任何时变状态判定/切换规则;leave-one-out 与并集
    变体为统一施加于全历史的静态键集,不含未来信息;「恢复后 3 个月盈亏」是事后度量(描述性统计),非可交易规则。
输入依赖: static-site/data/signal_kelly_trades.json(generated_at=2026-08-23 21:15,max sd=20260820)+
     static-site/data/a-stock-all.json(上证日线=交易日历)+ data/mine10_features.json +
     data/mine24_compare.json(NEW14 键单源/A_SUB)+ data/mine26_near1y.json(逐月咬合锚点)+
     data/mine28_modes_union_cap13_v2.json(RAW/G 锚点)。
输出: data/mine30_new14_default_challenge.json
复现: cd docs/kelly/analysis/scripts/sim_window_loss_mining_20260822 && python3 mine30_new14_default_challenge.py
关键口径一句话: mode A 权威池 × {A_on9/P0/P1/NEW14} 黑名单补位 K1 → V2 回补 cap13 费后重放 → 逐月盈亏/
     放行清单/枯竭 streak(真实交易日历)/九模式记分板/逐键放宽敏感性。
"""
import os, sys, json, datetime, calendar as calmod, statistics
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, base_key, PRIN
from mine18_detail import FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2
import mine25_longline_operable as M25
import mine27_g_exhaustive_simplified as M27
from mine24_compare import A_SUB

OUT_PATH = os.path.join(BASE, 'data', 'mine30_new14_default_challenge.json')
M24CMP_PATH = M25.M24CMP_PATH


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    mm = m % 12 + 1
    dd = min(d.day, calmod.monthrange(y, mm)[1])
    return datetime.date(y, mm, dd)


def d2s(d):
    return d.strftime('%Y%m%d')


def month_grid(end_ym, n_months):
    y, m = int(end_ym[:4]), int(end_ym[4:])
    out = []
    for _ in range(n_months):
        out.append(f'{y}{m:02d}')
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def monthly_by_signal(rows, months):
    """signal_date 月归属盈亏(bought/selection 集,含 holding 按现价标记;与 mine26 同款)。"""
    mp = {ym: 0.0 for ym in months}
    cnt = {ym: 0 for ym in months}
    idx = R.IDX_PNL
    for t in rows:
        ym = str(t[0])[:6]
        if ym in mp:
            mp[ym] += t[idx]['pnlYuan']
            cnt[ym] += 1
    return {f'{y[:4]}-{y[4:]}': round(v, 2) for y, v in mp.items()}, \
           {f'{y[:4]}-{y[4:]}': v for y, v in cnt.items()}


def monthly_by_sellmonth(bought, fi, asof):
    """realized 按 sell_date 月聚合 + holding 浮盈挂 asof 月(asof=数据末日 d_max;
    ⚠不可用 bought 内最后活动日代替: 长持满仓模式(G/I)买入早停会把全部浮盈灌进错误月份)。"""
    idx = R.IDX_PNL
    mom = {}
    for t in bought:
        sld = str(t[fi['sell_date']] or '') or asof
        ym = sld[:4] + '-' + sld[4:6]
        mom[ym] = mom.get(ym, 0.0) + t[idx]['pnlYuan']
    return {k: round(v, 2) for k, v in sorted(mom.items())}


def month_metrics(vals_dict, months_keys):
    vals = [vals_dict[k] for k in months_keys]
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    zero = sum(1 for v in vals if abs(v) < 0.005)

    def streak(pred):
        best = cur = 0
        for v in vals:
            if pred(v):
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best
    return dict(pos_months=pos, zero_months=zero, neg_months=neg,
                total=round(sum(vals), 2), worst_month=min(vals), best_month=max(vals),
                std_sample=round(statistics.stdev(vals), 2) if len(vals) > 1 else 0.0,
                max_consec_neg_strict=streak(lambda v: v < 0),
                max_consec_le0=streak(lambda v: v <= 0))


def replay_cap13(sel, fi, cap=13):
    day_sel = {str(t[0]): t for t in sel}
    R.init(sel, fi)
    rp = M27.replay3(day_sel, fi, cap, 'v2回补极简')
    return rp


def mdd_merged_of(bought, fi):
    idx = R.IDX_PNL
    bys, hold = {}, []
    for t in bought:
        sld = str(t[fi['sell_date']] or '')
        if sld:
            bys[sld] = bys.get(sld, 0.0) + t[idx]['pnlYuan']
        else:
            hold.append(t)
    last = max([*bys.keys(), *[str(t[0]) for t in bought]]) if bought else None
    if hold and last:
        bys[last] = bys.get(last, 0.0) + sum(t[idx]['pnlYuan'] for t in hold)
    return M25.dd_of(sorted(bys), bys)


def trade_brief(t, fi):
    idx = R.IDX_PNL
    return dict(date=str(t[0]), index_id=str(t[1] or ''), signal=str(t[2] or ''),
                buy_date=str(t[fi['buy_date']] or ''),
                etf=f"{t[fi['etf_code']] or ''} {t[fi['etf_name']] or ''}".strip(),
                rating=str(t[fi['rating']] or ''), track_score=t[fi['track_score']],
                pnl=round(t[idx]['pnlYuan'], 2),
                sell_date=str(t[fi['sell_date']] or ''))


def main():
    tr, fIdx = load(os.path.join(R._ROOT, 'static-site/data/signal_kelly_trades.json'))
    gen_at = tr.get('generated_at')
    FEATS = json.load(open(FEATS_PATH))
    M24CMP = json.load(open(M24CMP_PATH))
    M26 = json.load(open(os.path.join(BASE, 'data', 'mine26_near1y.json')))
    M28 = json.load(open(os.path.join(BASE, 'data', 'mine28_modes_union_cap13_v2.json')))
    NEW14_KEYS = list(M24CMP['new_keys'])
    rules = build_rules(FEATS, fIdx)
    rules.update(build_r2(fIdx))

    # ================= Part0 锚点复现(必过才往下) =================
    poolA = M27.finish_pool(build_mode_pool(tr, fIdx, 'A'), fIdx)
    R.init(poolA, fIdx)
    hist_keys = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
    mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2
    perkey = {}
    for c in NEW14_KEYS:
        if c in hist_keys:
            f = {kk: False for kk in DEFAULT_FILTERS}
            f[c] = True
            perkey[c] = {base_key(t, fIdx) for t in poolA
                         if not passes_fade(t, fIdx, f, active_month_mask(f), mD, eD, rD)}
        else:
            perkey[c] = {base_key(t, fIdx) for t in poolA if rules[c](t)}
    blkN14 = set().union(*perkey.values())
    selN14 = M25.ev_new_on(poolA, fIdx, blkN14)
    stN = R.stats_of(selN14)
    ddN = M25.dd_of(*M27._curve(selN14, fIdx))
    assert abs(stN['total'] - 122648.33) < 1.0 and abs(ddN['mdd'] - (-4178.01)) < 1.5, (stN, ddN)
    print(f"锚点 PASS: NEW14={stN['total']:+,.2f}/mdd{ddN['mdd']:,.2f}")

    rows8, fia = R.prepare_rows()
    R.init(rows8, fia)
    ctx8 = M25.build_ctx(rows8, fia)
    P0 = M25.ev(ctx8, (), False)
    P1 = M25.ev(ctx8, (), True)
    A9 = M25.ev(ctx8, A_SUB, True)
    assert abs(R.stats_of(P0)['total'] - 66530.38) < 0.5
    assert abs(R.stats_of(P1)['total'] - 73102.53) < 0.5
    a9t = R.stats_of(A9)['total']
    assert abs(a9t - M24CMP['projects']['A_on9']['stats']['total']) < 0.5, a9t
    print(f"锚点 PASS: P0={R.stats_of(P0)['total']:+,.2f} P1={R.stats_of(P1)['total']:+,.2f} A_on9={a9t:+,.2f}")

    # V2 回补 cap13 重放(mode A 不绑定断言)
    rpN = replay_cap13(selN14, fIdx)
    rpA9 = replay_cap13(A9, fia)
    rpP0 = replay_cap13(P0, fia)
    rpP1 = replay_cap13(P1, fia)
    for nm, rp, sel in [('NEW14', rpN, selN14), ('A_on9', rpA9, A9), ('P0', rpP0, P0), ('P1', rpP1, P1)]:
        tot_sel = R.stats_of(sel)['total']
        tot_rp = sum(t[R.IDX_PNL]['pnlYuan'] for t in rp['bought'])
        assert len(rp['skipped']) == 0, (nm, len(rp['skipped']))
        assert abs(tot_rp - tot_sel) < 0.5, (nm, tot_rp, tot_sel)
    print('锚点 PASS: mode A 四方案 cap13V2 不绑定(skipped=0,重放层==选择层,逐位一致)')

    # G 模式机具咬合(mine27/28 锚点)
    poolG = M27.finish_pool(build_mode_pool(tr, fIdx, 'G'), fIdx)
    R.init(poolG, fIdx)
    selG_raw = M25.ev_new_on(poolG, fIdx, set())
    rpG = replay_cap13(selG_raw, fIdx)
    totG = round(sum(t[R.IDX_PNL]['pnlYuan'] for t in rpG['bought']), 2)
    assert abs(totG - 109828.49) < 1.0, totG
    keptG8 = [t for t in build_mode_pool(tr, fIdx, 'G')
              if passes_fade(t, fIdx, DEFAULT_FILTERS, active_month_mask(DEFAULT_FILTERS), mD, eD, rD)]
    keptG8 = M27.finish_pool(keptG8, fIdx)
    R.init(keptG8, fIdx)
    selG8 = M25.ev_new_on(keptG8, fIdx, set())
    rpG8 = replay_cap13(selG8, fIdx)
    totG8 = round(sum(t[R.IDX_PNL]['pnlYuan'] for t in rpG8['bought']), 2)
    assert abs(totG8 - 125541.58) < 1.0, totG8
    print(f'锚点 PASS: G RAW cap13v2={totG:+,.2f} G P0={totG8:+,.2f}(mine27/28 咬合)')

    # 数据跨度/窗口(交易日历=a-stock-all 上证日线,非信号日期代理)
    idx_all = json.load(open(os.path.join(R._ROOT, 'static-site/data/a-stock-all.json')))
    cal_full = [d['date'] for d in idx_all['indices']['sh']['data']]
    all_sd = sorted({str(t[0]) for t in poolA})
    d_min, d_max = all_sd[0], all_sd[-1]
    CAL = [d for d in cal_full if d_min <= d <= d_max]
    months12 = month_grid(d_max[:6], 12)
    mk = [f'{y[:4]}-{y[4:]}' for y in months12]
    print(f'数据跨度 {d_min}~{d_max} | 近12自然月 {mk[0]}~{mk[-1]}')

    PROJ = [('P0_8键', P0, fia), ('P1_9键', P1, fia), ('A_on9', A9, fia), ('NEW14', selN14, fIdx)]

    # ================= Part1 断言①③: A_on9 vs NEW14 逐月对照 =================
    part1 = {}
    print('\n===== Part1 逐月盈亏(signal_date 月归属,费后,V2cap13 重放后 bought 集)===')
    hdr = ' | '.join(mk)
    print('方案 | ' + hdr + ' | 5-8月累计')
    for nm, sel, fi in PROJ:
        bought = replay_cap13(sel, fi)['bought']
        mm, nn = monthly_by_signal(bought, months12)
        met = month_metrics(mm, mk)
        may_aug = round(sum(mm[f'{y}-{m:02d}'] for y, m in [(2026, 5), (2026, 6), (2026, 7), (2026, 8)]), 2)
        part1[nm] = dict(months=mm, month_n=nn, metrics=met, may_aug_cum=may_aug,
                         months_by_sellmonth=monthly_by_sellmonth(bought, fi, d_max))
        print(f"{nm} | " + ' | '.join(f"{mm[k]:+,.0f}" for k in mk) + f" | {may_aug:+,.0f}")
        # 咬合断言: mine26 near1y_main.months(12自然月同窗)逐位一致(<0.5)
        key_map = {'P0_8键': 'P0_8键', 'P1_9键': 'P1_9键', 'A_on9': 'A_on9', 'NEW14': 'NEW_14键'}
        m26 = M26['projects'][key_map[nm]]['near1y_main']['months']
        bad = {k: (mm[k], m26[k]) for k in mk if abs(mm[k] - m26[k]) >= 0.5}
        assert not bad, (nm, bad)
    print('咬合 PASS: 四方案 12 个月逐月值 == mine26_near1y.json(逐位 <0.5)')

    # 断言①专项: A vs NEW 2026-05~08
    may_aug_months = ['2026-05', '2026-06', '2026-07', '2026-08']
    a_m = part1['A_on9']['months']; n_m = part1['NEW14']['months']; p_m = part1['P0_8键']['months']
    assertion1 = dict(
        user_claim='A 不止 2026-04 强,5 月至今也是正的,而 NEW14 是负的',
        months={k: {'A_on9': a_m[k], 'NEW14': n_m[k], 'P0_8键': p_m[k],
                    'diff_A_minus_NEW': round(a_m[k] - n_m[k], 2)} for k in may_aug_months},
        cum_may_to_now={'A_on9': part1['A_on9']['may_aug_cum'],
                        'NEW14': part1['NEW14']['may_aug_cum'],
                        'P0_8键': part1['P0_8键']['may_aug_cum'],
                        'diff_A_minus_NEW': round(part1['A_on9']['may_aug_cum'] - part1['NEW14']['may_aug_cum'], 2)},
        verdict=None)  # 报告层填
    # 断言③专项: NEW14 近 4 个月零正月份?
    assertion3 = dict(
        user_claim='NEW14 近 4 个月没一个月整的(没一个月赚钱)',
        new14_last4={k: n_m[k] for k in may_aug_months},
        positive_month_count_last4=sum(1 for k in may_aug_months if n_m[k] > 0),
        note_zero_months='2026-05 与 2026-08 为 0 元月(当月无放行买入信号),见 Part2',
        verdict=None)

    # A 领先集中度(事件月分解)
    diffs = {k: round(a_m[k] - n_m[k], 2) for k in mk}
    lead_total = round(sum(diffs.values()), 2)
    ev_months = ['2025-12', '2026-04']
    ex_ev = round(sum(v for k, v in diffs.items() if k not in ev_months), 2)
    ev_share = round(1 - ex_ev / lead_total, 3) if lead_total else None
    # 2026-07 归因明细
    jul_detail = {}
    for nm, sel, fi in [('A_on9', A9, fia), ('NEW14', selN14, fIdx)]:
        ts = [t for t in sel if str(t[0])[:6] == '202607']
        ts.sort(key=lambda t: t[R.IDX_PNL]['pnlYuan'])
        jul_detail[nm] = dict(n=len(ts), pnl=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in ts), 2),
                              trades=[trade_brief(t, fi) for t in ts])
    part1['lead_decomposition'] = dict(a_minus_new_by_month=diffs, lead_total_12m=lead_total,
                                       ex_event_months=ex_ev, event_months=ev_months,
                                       event_month_share=ev_share, july2026_detail=jul_detail)

    # ================= Part2 断言②: 放行清单 + 裸池对照 + 键归属分布 =================
    W0 = '20260601'
    pool_by_day = {}
    for t in poolA:
        pool_by_day.setdefault(str(t[0]), []).append(t)
    win_days = [d for d in CAL if W0 <= d <= d_max]   # 日历全口径: 含无原始信号的交易日
    sel_keys = {}
    sel_by_day = {}
    for t in selN14:
        sel_by_day.setdefault(str(t[0]), []).append(t)
    admitted_list = []
    daily_cls = []
    key_block_top1 = {c: 0 for c in NEW14_KEYS}
    key_block_any = {c: 0 for c in NEW14_KEYS}
    sole_blocker = {c: 0 for c in NEW14_KEYS}
    blocked_win_rows = []
    raw_n_total = surv_n_total = 0
    for sd in win_days:
        rows = sorted(pool_by_day.get(sd, []), key=lambda t: t[R.IDX_SKEY])
        raw_n = len(rows)
        raw_n_total += raw_n
        surv = [t for t in rows if base_key(t, fIdx) not in blkN14]
        surv_n_total += len(surv)
        sel_today = sel_by_day.get(sd, [])
        top1_blocked = bool(rows) and base_key(rows[0], fIdx) in blkN14
        if top1_blocked:
            hits = [c for c in NEW14_KEYS if base_key(rows[0], fIdx) in perkey[c]]
            for c in hits:
                key_block_top1[c] += 1
        admitted_list.extend(trade_brief(t, fIdx) for t in sel_today)
        for t in rows:
            bk = base_key(t, fIdx)
            if bk in blkN14:
                blocked_win_rows.append(t)
                hits = [c for c in NEW14_KEYS if bk in perkey[c]]
                for c in hits:
                    key_block_any[c] += 1
                if len(hits) == 1:
                    sole_blocker[hits[0]] += 1
        daily_cls.append(dict(date=sd, raw_n=raw_n, survivor_n=len(surv), admitted=bool(sel_today),
                              raw_top1=(str(rows[0][1] or '') + '/' + str(rows[0][2] or '')) if rows else '',
                              raw_top1_blocked=top1_blocked,
                              selected=(trade_brief(sel_today[0], fIdx) if sel_today else None)))
    empty_days = [d for d in daily_cls if not d['admitted']]
    market_empty = [d for d in empty_days if d['raw_n'] == 0]
    filter_starved = [d for d in empty_days if d['raw_n'] > 0]

    # G 模式裸池对照(同窗)
    poolG_rows = build_mode_pool(tr, fIdx, 'G')  # 未 finish(仅计数用)
    keysA = {base_key(t, fIdx) for t in poolA}
    keysG = {base_key(t, fIdx) for t in poolG_rows}
    g_win = sum(1 for t in poolG_rows if W0 <= str(t[0]) <= d_max)

    last_adm = max((d['date'] for d in daily_cls if d['admitted']), default=None)
    assertion2 = dict(
        window=[W0, d_max],
        user_claim='NEW 最近信号过滤得太少,7/2 后就只有 720 有一个信号了',
        admitted_trades=admitted_list,
        admitted_day_count=len([d for d in daily_cls if d['admitted']]),
        window_trading_days_with_pool=len(win_days),
        calendar_days_in_window=None,  # Part3 用日历补
        last_admitted_signal_date=last_adm,
        empty_day_classification=dict(no_admit_days=len(empty_days),
                                      market_no_signal_days=len(market_empty),
                                      filter_starved_days=len(filter_starved),
                                      filter_starved_dates=[d['date'] for d in filter_starved]),
        calendar_view=dict(window_trading_days_calendar=len(win_days),
                           days_with_admitted=len([d for d in daily_cls if d['admitted']]),
                           days_zero_raw_candidate=len(market_empty),
                           days_raw_but_all_blocked=len(filter_starved),
                           note='win_days=日历交易日;market_no_signal=当日原始候选 0;filter_starved=有候选但全被 NEW14 黑名单拦光'),
        raw_vs_survivor=dict(raw_candidates=raw_n_total, survivors=surv_n_total,
                             blocked=raw_n_total - surv_n_total,
                             block_rate_pct=round((raw_n_total - surv_n_total) / max(raw_n_total, 1) * 100, 1)),
        key_attribution_window=dict(blocked_candidates=len(blocked_win_rows),
                                    hits_per_key=dict(sorted(key_block_any.items(), key=lambda kv: -kv[1])),
                                    sole_blocker_per_key=dict(sorted(sole_blocker.items(), key=lambda kv: -kv[1])),
                                    blocked_raw_top1_per_key=dict(sorted(key_block_top1.items(), key=lambda kv: -kv[1]))),
        full_history_key_hits={c: len(perkey[c]) for c in sorted(perkey, key=lambda c: -len(perkey[c]))},
        raw_pool_compare=dict(modeA_raw_window=sum(d['raw_n'] for d in daily_cls),
                              modeG_raw_window=g_win,
                              universe_keyset_equal=(keysA == keysG),
                              universe_diff_n=len(keysA ^ keysG)),
        verdict=None)
    print(f"\nPart2 窗口[{W0},{d_max}]: 放行 {len(admitted_list)} 笔 / 最后放行日 {last_adm}")
    print(f"  无放行日 {len(empty_days)}(其中市场本身无原始信号 {len(market_empty)} 天 / 池有信号但被拦光 {len(filter_starved)} 天)")
    print(f"  原始候选 {raw_n_total} → 幸存 {surv_n_total}(拦 {(raw_n_total-surv_n_total)/max(raw_n_total,1)*100:.1f}%)")
    print(f"  键拦截分布(any): {sorted(key_block_any.items(), key=lambda kv:-kv[1])[:5]}")
    print(f"  拦掉每日第一顺位(top1): {sorted(key_block_top1.items(), key=lambda kv:-kv[1])[:5]}")
    print(f"  裸池对照: modeA 窗内 {sum(d['raw_n'] for d in daily_cls)} 条 vs modeG 窗内 {g_win} 条;宇宙一致={keysA==keysG}(diff {len(keysA^keysG)})")

    # P0 八键同窗放行清单(决策对照列)
    p0_by_day = {}
    for t in P0:
        p0_by_day.setdefault(str(t[0]), []).append(t)
    p0_list = [trade_brief(p0_by_day[sd][0], fia) for sd in sorted(p0_by_day) if W0 <= sd <= d_max]

    # ================= Part3 断言④: 枯竭历史类比(真实交易日历) =================
    idx_all = json.load(open(os.path.join(R._ROOT, 'static-site/data/a-stock-all.json')))
    cal_full = [d['date'] for d in idx_all['indices']['sh']['data']]
    CAL = [d for d in cal_full if d_min <= d <= d_max]
    def drought_profile(admitted_dates, label):
        adm = set(admitted_dates)
        streaks = []
        cur_start = None
        for d in CAL:
            if d not in adm:
                if cur_start is None:
                    cur_start = d
            else:
                if cur_start is not None:
                    streaks.append((cur_start, d, CAL.index(d) - CAL.index(cur_start)))
                    cur_start = None
        if cur_start is not None:
            streaks.append((cur_start, None, len(CAL) - CAL.index(cur_start)))  # 进行中(截至数据末)
        recs = []
        for st, en, ln in streaks:
            if ln >= 20:
                rec_d = en  # en=恢复日(首个放行日);进行中则 None
                nxt = dict(pnl=None, n=None)
                if rec_d:
                    end3 = add_months(datetime.date(int(rec_d[:4]), int(rec_d[4:6]), int(rec_d[6:8])), 3)
                    wsel = [t for t in selN14 if rec_d <= str(t[0]) <= d2s(end3)]
                    nxt = dict(pnl=round(sum(t[R.IDX_PNL]['pnlYuan'] for t in wsel), 2), n=len(wsel))
                recs.append(dict(start=st, recover=en, length_td=ln, next3m=nxt))
        all_len = [ln for _, _, ln in streaks]
        per_year = {}
        for st, en, ln in streaks:
            if ln >= 20:
                y = st[:4]
                per_year[y] = per_year.get(y, 0) + 1
        return dict(label=label, n_streaks_ge20=len(recs), n_ge40=sum(1 for r in recs if r['length_td'] >= 40),
                    n_ge60=sum(1 for r in recs if r['length_td'] >= 60),
                    max_streak_td=max(all_len) if all_len else 0,
                    median_streak_td=statistics.median(all_len) if all_len else 0,
                    drought_day_share_pct=round(sum(l for l in all_len if l >= 1) / len(CAL) * 100, 1),
                    ge20_events=recs, ge20_per_year=dict(sorted(per_year.items())),
                    ongoing_tail=dict(start=streaks[-1][0], length_asof_data_end=streaks[-1][2])
                    if streaks and streaks[-1][1] is None else None)
    profN = drought_profile([str(t[0]) for t in selN14], 'NEW14')
    profP = drought_profile([str(t[0]) for t in P0], 'P0_8键')
    profRaw = drought_profile(sorted({str(t[0]) for t in poolA}), 'RAW裸池')
    print(f"\nPart3 NEW14 枯竭: ≥20交易日 {profN['n_streaks_ge20']} 次 / ≥40 {profN['n_ge40']} / ≥60 {profN['n_ge60']} "
          f"| 最长 {profN['max_streak_td']} 交易日 | 枯竭日占比 {profN['drought_day_share_pct']}%")
    print(f"  P0 对照: ≥20 {profP['n_streaks_ge20']} / ≥40 {profP['n_ge40']} / ≥60 {profP['n_ge60']} | 最长 {profP['max_streak_td']} | 占比 {profP['drought_day_share_pct']}%")
    print(f"  RAW 对照: ≥20 {profRaw['n_streaks_ge20']} 次 / 最长 {profRaw['max_streak_td']} | "
          f"NEW14 进行中枯竭 tail={profN['ongoing_tail']}")

    # ================= Part4 记分板: A-I 九模式 RAW + NEW14 + 八键(V2cap13) =================
    MODES = list('ABCDEFGHI')
    board = {}
    sup_matrix = {}
    for mo in MODES:
        pm = M27.finish_pool(build_mode_pool(tr, fIdx, mo), fIdx)
        R.init(pm, fIdx)
        variants = {'RAW': M25.ev_new_on(pm, fIdx, set())}
        kept8 = [t for t in build_mode_pool(tr, fIdx, mo)
                 if passes_fade(t, fIdx, DEFAULT_FILTERS, active_month_mask(DEFAULT_FILTERS), mD, eD, rD)]
        kept8 = M27.finish_pool(kept8, fIdx)
        R.init(kept8, fIdx)
        variants['P0_8键'] = M25.ev_new_on(kept8, fIdx, set())
        for vn, sel in variants.items():
            rp = replay_cap13(sel, fIdx)
            bought = rp['bought']
            mm, nn = monthly_by_signal(bought, months12)
            met = month_metrics(mm, mk)
            tot = round(sum(t[R.IDX_PNL]['pnlYuan'] for t in bought), 2)
            near1y = round(sum(t[R.IDX_PNL]['pnlYuan'] for t in bought if str(t[0]) >= '20250820'), 2)
            msm = monthly_by_sellmonth(bought, fIdx, d_max)
            met_sm = month_metrics({k: msm.get(k, 0.0) for k in mk}, mk)
            rec = dict(total_all=tot, mdd_merged=mdd_merged_of(bought, fIdx), n_skipped=len(rp['skipped']),
                       peak_pos_n=rp['peak_n'], near1y_total=near1y, months=mm, month_n=nn, metrics=met,
                       months_by_sellmonth=msm,
                       metrics_by_sellmonth_note='realized 按 sell_date 月聚合+holding 浮盈挂数据末日 d_max(长持模式诚实并列;'
                                                 '含历史月份,metrics 仅统计近12月窗内交集)',
                       metrics_by_sellmonth_12m=met_sm)
            assert abs(sum(msm.values()) - tot) < 1.0, (mo, vn, sum(msm.values()), tot)
            if vn == 'RAW':
                board[f'mode_{mo}_RAW'] = rec
            else:
                sup_matrix[mo] = rec
    # 主角两行(叠加口径 A_on9 与重构口径 NEW14、基准 P0)
    for nm, sel, fi in [('NEW14', selN14, fIdx), ('P0_8键', P0, fia), ('P1_9键', P1, fia), ('A_on9', A9, fia)]:
        bought = replay_cap13(sel, fi)['bought']
        mm, nn = monthly_by_signal(bought, months12)
        met = month_metrics(mm, mk)
        tot = round(sum(t[R.IDX_PNL]['pnlYuan'] for t in bought), 2)
        near1y = round(sum(t[R.IDX_PNL]['pnlYuan'] for t in bought if str(t[0]) >= '20250820'), 2)
        rp2 = replay_cap13(sel, fi)
        msm = monthly_by_sellmonth(rp2['bought'], fi, d_max)
        assert abs(sum(msm.values()) - tot) < 1.0, (nm, sum(msm.values()), tot)
        board[nm] = dict(total_all=tot, mdd_merged=mdd_merged_of(rp2['bought'], fi), n_skipped=0,
                         peak_pos_n=rp2['peak_n'], near1y_total=near1y,
                         months=mm, month_n=nn, metrics=met, months_by_sellmonth=msm,
                         metrics_by_sellmonth_12m=month_metrics({k: msm.get(k, 0.0) for k in mk}, mk))
    # 座次: 正月份↓ → 最差月亏幅↑(少亏优先) → std↑小优先;收益榜另列
    names = list(board)
    stab_rank = sorted(names, key=lambda n: (-board[n]['metrics']['pos_months'],
                                             -board[n]['metrics']['worst_month'],
                                             board[n]['metrics']['std_sample']))
    gain_rank = sorted(names, key=lambda n: -board[n]['near1y_total'])
    gain_rank_all = sorted(names, key=lambda n: -board[n]['total_all'])
    print('\n===== Part4 记分板(近12月,V2cap13)=====')
    print('名次(月月赚维度) 方案 | 正月 | 连亏 | 最差月 | std | 近1年净利 | 全史净利')
    for i, n in enumerate(stab_rank, 1):
        b = board[n]; m = b['metrics']
        print(f"{i}. {n} | {m['pos_months']}/12 | {m['max_consec_neg_strict']} | {m['worst_month']:+,.0f} | "
              f"{m['std_sample']:,.0f} | {b['near1y_total']:+,.0f} | {b['total_all']:+,.0f}")

    # ================= Part5 决策增量: 逐键放宽敏感性 + 并集对照 =================
    base_recent_n = len([t for t in selN14 if str(t[0]) >= W0])
    loo = {}
    for c in NEW14_KEYS:
        blk2 = blkN14 - perkey[c]
        sel2 = M25.ev_new_on(poolA, fIdx, blk2)
        R.init(sel2, fIdx)
        st2 = R.stats_of(sel2)
        dd2 = M25.dd_of(*M27._curve(sel2, fIdx))
        recent_n = len([t for t in sel2 if str(t[0]) >= W0])
        m12 = monthly_by_signal(sel2, months12)[0]
        loo[c] = dict(recent_added_signals_jun_on=recent_n - base_recent_n,
                      net_all_delta=round(st2['total'] - stN['total'], 2),
                      mdd=dd2['mdd'], total_all=st2['total'],
                      may_aug_delta=round(sum(m12.get(k, 0.0) for k in ['2026-05', '2026-06', '2026-07', '2026-08']) -
                                          sum(n_m[k] for k in ['2026-05', '2026-06', '2026-07', '2026-08']), 2))
    loo_order = sorted(loo.items(), key=lambda kv: -kv[1]['recent_added_signals_jun_on'])
    print('\nPart5 逐键放宽(leave-one-out,近期放行增量排序):')
    for c, v in loo_order:
        print(f"  去掉 {c}: 近期多放行 {v['recent_added_signals_jun_on']:+d} 笔 | 全史净利 Δ{v['net_all_delta']:+,.0f} | mdd {v['mdd']:,.0f}")

    # NEW14∪8键 并集(两段式,mine28 同构)
    keptA8 = rows8  # prepare_rows 即 mode A 8键池(已 finish)
    R.init(keptA8, fIdx)
    blkU = M25.hits_on(keptA8, fIdx, NEW14_KEYS, rules)
    selU = M25.ev_new_on(keptA8, fIdx, blkU)
    stU = R.stats_of(selU)
    ddU = M25.dd_of(*M27._curve(selU, fIdx))
    mmU = monthly_by_signal(selU, months12)[0]
    union_rec = dict(total_all=stU['total'], mdd=ddU['mdd'],
                     near1y=round(R.stats_of(R.window(selU, '20250820'))['total'], 2),
                     recent_n_jun_on=len([t for t in selU if str(t[0]) >= W0]),
                     may_aug=round(sum(mmU.get(k, 0.0) for k in ['2026-05', '2026-06', '2026-07', '2026-08']), 2))
    print(f"  NEW14∪8键(mode A): 全史 {stU['total']:+,.0f} mdd {ddU['mdd']:,.0f} 近期放行 {union_rec['recent_n_jun_on']} 笔")

    # ================= 输出 =================
    out = dict(
        meta=dict(script='mine30_new14_default_challenge.py', date='2026-08-24',
                  data_generated_at=gen_at, data_span=[d_min, d_max], max_signal_date=d_max,
                  caliber=dict(base_declare='测试基准=current baseline v1.1.2 八键(P0);主对象 NEW14=v1.1.5 候选(非基准默认,显式声明)',
                               engine='mode A 权威锚点池 + K1 补位(top-K 前黑名单过滤)+ V2 回补型重放(mine27 replay3)+ cap13 + 费后 etf_def',
                               cap13_note='mode A 池 K1 每日≤1笔+A 固定卖出 → cap13 不绑定(skipped=0 已断言),选择层==重放层',
                               month_attr='主口径=signal_date 月归属(mine26 同款可比);realized 按 sell_date 月聚合并列于 JSON'),
                  no_lookahead='纯历史静态统计与静态过滤组合,无时变状态判定/切换;LOO 与并集为全史统一静态键集;'
                               '「恢复后3个月盈亏」为事后描述性统计非可交易规则;交易日历取自上证日线(a-stock-all),非信号日期代理',
                  deps=['static-site/data/signal_kelly_trades.json', 'static-site/data/a-stock-all.json',
                        'data/mine10_features.json', 'data/mine24_compare.json', 'data/mine26_near1y.json',
                        'data/mine28_modes_union_cap13_v2.json'],
                  repro='cd docs/kelly/analysis/scripts/sim_window_loss_mining_20260822 && python3 mine30_new14_default_challenge.py',
                  new14_keys=NEW14_KEYS),
        anchors=dict(new14_total=stN['total'], new14_mdd=ddN['mdd'], p0=R.stats_of(P0)['total'],
                     p1=R.stats_of(P1)['total'], a_on9=a9t, modeA_raw_cap13v2=M28['runs']['A']['RAW无过滤']['total_merged'],
                     g_raw_cap13v2=totG, g_p0_cap13v2=totG8),
        part1_assertion1_and_3=part1, assertion1=assertion1, assertion3=assertion3,
        part2_assertion2=dict(list_p0_same_window_for_contrast=p0_list, **assertion2),
        daily_classification=daily_cls,
        part3_drought=dict(calendar_days=len(CAL), calendar_range=[CAL[0], CAL[-1]],
                           NEW14=profN, P0_8键=profP, RAW裸池=profRaw),
        part4_scoreboard=dict(board=board, stability_rank=stab_rank, gain_rank_near1y=gain_rank,
                              gain_rank_allhistory=gain_rank_all,
                              rank_rule='正月份↓→最差月亏幅↑→月度std↑;收益榜独立列,不混合',
                              supplement_modes_x_P0=sup_matrix),
        part5_decision=dict(leave_one_key_out=loo, loo_order=[c for c, _ in loo_order],
                            union_new14_plus_8keys=union_rec,
                            lead_decomposition=part1['lead_decomposition']),
    )
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False)
    print('saved ->', OUT_PATH)


if __name__ == '__main__':
    main()
