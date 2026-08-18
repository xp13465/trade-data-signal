# ============================================================
# 用途: 四档升级版补测(稳定/回撤/历史年份/大熊市/不同周期/哪个亏最少) — v1.1.2 宇宙基座
# 日期/来源: 2026-08-18 / 四档报告补测(用户反馈「不能只看盈利前3,补稳定和回撤」)
# 结论: ①cyb/kc50 总量领先主要靠 2014/2015+2019-2025 结构, 非 2026 单年撑起(2026 按年 cyb=hs300 持平)
#      ②剔除 2026 后 2011-2025 全史 cyb 仍 +16,512 领先; kc50 数据起点 2020, 前段等同无键
#      ③回撤: hs300 基准最大回撤金额最浅(-42,9xx), cyb -49,2xx, 见步骤3; 大熊市窗口 cyb 2015/2018/2022 亏损更少
#      ④稳定性: cyb 按年正 11 年/负 5 年(hs300 正 10/负 6), 大熊市专项 2015股灾/2018/2022 窗口 cyb 均更优
# 依赖: static-site/data/signal_kelly_trades.json(2026-08-18 09:14) + trade-data/data/sentiment.db(index_daily)
#       docs/kelly/scripts/{kelly_combo_advice_analysis,kelly_posfilter_backtest,dailypool_rerun_core,kelly_ghi_g_scan}.py
# 输出: stdout 各步骤关键表 + data/results_fourtier_v2_stability.json
# 复现: python3 docs/market-state/scripts/kelly_fourtier_v2_stability.py
# 关键口径: v1.1.2 基准 = 8键(判定源可换 excludeSpecialBear) + 每日资金池等分 + K1 + G 用 P≤3d 13万 b0(强平记0利)
#      收益率=净利÷仿真峰值; 回撤=累计已实现利润曲线峰谷差(相对峰值占用资本% 为主口径)
#      函数与 kelly_fourtier_v2_multiindex.py 同源复制(防分叉, 补测独立落档)
# ============================================================
# -*- coding: utf-8 -*-
import sys, contextlib, io, sqlite3, bisect, math, json, os
from collections import defaultdict
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/Users/linhuichen/code/trade/scripts')
ROOT = os.path.dirname(os.path.abspath(__file__))
with contextlib.redirect_stdout(io.StringIO()):
    from kelly_combo_advice_analysis import passes_fade, fIdx, BUY_AMOUNT, trade_features, load, fields
    from kelly_posfilter_backtest import get_by_date, base_key
    from dailypool_rerun_core import full_sort_key, DAILY, compute_scaled
    from kelly_ghi_g_scan import simulate_custom

TIER_RANK = {'牛市·主升': 0, '上升期': 1, '下降期': 2, '熊市·主跌': 3}
RANK_TIER = {0: '牛市·主升', 1: '上升期', 2: '下降期', 3: '熊市·主跌'}
EXCL_SET = {'熊市·主跌','下降期'}
RESULT = {}

# ---------- 与主脚本同源: 多指数四档构建 ----------
def build_index_tiers(conn, idx_ids):
    out = {}
    for iid in idx_ids:
        rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date", (iid,)).fetchall()
        if not rows: continue
        dates = [r[0] for r in rows]; closes = [r[1] for r in rows]
        n = len(dates)
        def _ma(w, i):
            if i < w - 1: return None
            return sum(closes[i-w+1:i+1])/w
        tiers = {}
        for i in range(200-1, n):
            c = closes[i]
            m20,m60,m120,m200 = _ma(20,i),_ma(60,i),_ma(120,i),_ma(200,i)
            if None in (m20,m60,m120,m200): continue
            bull = m20>m60>m120; bear = m20<m60<m120
            if c>m200 and bull: tier='牛市·主升'
            elif c>m200: tier='上升期'
            elif c<m200 and bear: tier='熊市·主跌'
            elif c<m200: tier='下降期'
            else: tier='上升期'
            tiers[dates[i]] = tier
        out[iid] = tiers
    return out

def tier_at(tiers, dates, sd):
    if not tiers: return ''
    idx = bisect.bisect_right(dates, sd) - 1
    while idx >= 0:
        d = dates[idx]
        if d in tiers: return tiers[d]
        idx -= 1
    return ''

def build_synth_index(conn, idx_ids):
    closes_map = {}
    for iid in idx_ids:
        rows = conn.execute("SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date", (iid,)).fetchall()
        if rows: closes_map[iid] = {r[0]: r[1] for r in rows}
    common = None
    for iid in idx_ids:
        ds = set(closes_map.get(iid, {}).keys())
        if common is None: common = ds
        else: common &= ds
    common = sorted(common)
    if len(common) < 300: return {}
    norm = {}
    for iid in idx_ids:
        cm = closes_map.get(iid)
        if not cm: continue
        base = cm[common[0]]
        norm[iid] = {d: cm[d]/base for d in common}
    closes = []
    for d in common:
        closes.append(sum(norm[iid][d] for iid in norm)/len(norm))
    n = len(closes)
    def _ma(w, i):
        if i < w-1: return None
        return sum(closes[i-w+1:i+1])/w
    out = {}
    for i in range(200-1, n):
        c = closes[i]
        m20,m60,m120,m200 = _ma(20,i),_ma(60,i),_ma(120,i),_ma(200,i)
        if None in (m20,m60,m120,m200): continue
        bull = m20>m60>m120; bear = m20<m60<m120
        if c>m200 and bull: tier='牛市·主升'
        elif c>m200: tier='上升期'
        elif c<m200 and bear: tier='熊市·主跌'
        elif c<m200: tier='下降期'
        else: tier='上升期'
        out[common[i]] = tier
    return out

def make_passes(tier_fn, excl_set=EXCL_SET):
    def passes(t, F):
        F2 = dict(F); F2.pop('excludeSpecialBear', None); F2.pop('k2c5HkChase', None)
        if not passes_fade(t, F2): return False
        sig = str(t[fIdx['signal']] or '')
        if F.get('excludeSpecialBear') and sig == 'buy_special':
            if tier_fn is None:
                return True
            mt = tier_fn(t)
            if mt in excl_set: return False
        if F.get('k2c5HkChase'):
            f = trade_features(t)
            if f['sig'] in ('buy_special','buy_backup') and f['mktD'] == 'hk': return False
        return True
    return passes

def get_items(mode, passes, F, K=1, start=None, end=None):
    bd = get_by_date(mode)
    keys, day_n = set(), {}
    for sd, rows in bd.items():
        if start and sd < start: continue
        if end and sd > end: continue
        fr = [t for t in rows if passes(t, F)]
        if not fr: continue
        srt = sorted(fr, key=full_sort_key)
        pick = srt[:K] if K else srt
        day_n[sd] = len(pick)
        for t in pick: keys.add(base_key(t))
    items = []
    for sd, rows in bd.items():
        if sd not in day_n: continue
        n = day_n[sd]; amt = DAILY/n if n else 0
        for t in rows:
            if base_key(t) not in keys: continue
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            items.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items

def run_backtest(mode, passes, F, cap=130000, P_N=3, model='b0', K=1, start=None, end=None):
    items = get_items(mode, passes, F, K=K, start=start, end=end)
    if mode in ('G','H','I'):
        kept, peak, skipped, forced, nat, traded, fs, avg_cur = simulate_custom(items, cap, 'P', model, P_N=P_N)
        st = compute_scaled(kept)
        return len(items), st, kept, peak
    else:
        st = compute_scaled(items)
        return len(items), st, None, None

# ---------- 回撤分析(累计已实现利润曲线) ----------
def nat_days(a, b):
    from datetime import datetime
    if not a or not b: return None
    try:
        d1 = datetime.strptime(a, '%Y%m%d'); d2 = datetime.strptime(b, '%Y%m%d')
        return max((d2 - d1).days, 0)
    except (ValueError, TypeError): return None

def drawdown_analysis(kept, cap=130000, peak_cap=0):
    """kept: [(profit, rp, bd, sd, hd, amt)]; 按卖出日(sd)累计已实现利润, 算回撤
    主口径: max_dd_amt(元) + max_dd_pct_cap(相对 cap 本金池%) + 相对峰值占用资本%(参考)
    同时算最长回撤期(峰→谷自然日)与最长恢复时长(谷→新高自然日, 未恢复=None)"""
    settled = [t for t in kept if t[3] != '99999999']
    pts = sorted(settled, key=lambda t: t[3])
    cum = 0.0; peak_cum = 0.0; peak_sd = None
    segments = []
    seg_peak_sd = None; seg_peak_cum = 0.0; seg_valley_sd = None; seg_valley_cum = 0.0
    in_dd = False
    for t in pts:
        sd = t[3]; cum += t[0]
        if cum > peak_cum:
            if in_dd and seg_valley_sd is not None:
                segments.append((seg_peak_sd, seg_valley_sd, seg_peak_cum, seg_valley_cum, sd))
            peak_cum = cum; peak_sd = sd
            seg_peak_sd = sd; seg_peak_cum = cum; seg_valley_sd = sd; seg_valley_cum = cum
            in_dd = False
        else:
            in_dd = True
            if seg_valley_sd is None or cum < seg_valley_cum:
                seg_valley_cum = cum; seg_valley_sd = sd
    if in_dd and seg_valley_sd is not None:
        segments.append((seg_peak_sd, seg_valley_sd, seg_peak_cum, seg_valley_cum, None))
    max_dd_amt = 0.0; max_dd_peak_sd = None; max_dd_valley_sd = None; max_dd_recover = None
    longest_span = 0; longest_span_key = None
    longest_recover = 0; longest_recover_key = None
    for (ps, vs, pc, vc, rs) in segments:
        amt = pc - vc
        if amt > max_dd_amt:
            max_dd_amt = amt; max_dd_peak_sd = ps; max_dd_valley_sd = vs; max_dd_recover = rs
        sp = nat_days(ps, vs) or 0
        if sp > longest_span:
            longest_span = sp; longest_span_key = (ps, vs)
        if rs:
            rc = nat_days(vs, rs) or 0
            if rc > longest_recover:
                longest_recover = rc; longest_recover_key = (vs, rs)
    pc_use = peak_cap if peak_cap > 0 else cap
    return dict(
        n_settled=len(settled), n_open=len(kept)-len(settled),
        final_cum=round(cum,1),
        max_dd_amt=round(max_dd_amt,0),
        max_dd_pct_cap=round(max_dd_amt/pc_use*100, 2) if pc_use > 0 else None,
        max_dd_pct_peak_profit=round(max_dd_amt/seg_peak_cum*100, 2) if seg_peak_cum > 0 else None,
        max_dd_peak_sd=max_dd_peak_sd, max_dd_valley_sd=max_dd_valley_sd,
        max_dd_recover_sd=max_dd_recover, max_dd_recovered=(max_dd_recover is not None),
        longest_dd_days=longest_span, longest_dd_window=longest_span_key,
        longest_recover_days=longest_recover, longest_recover_window=longest_recover_key,
    )

def main():
    d = load()
    conn = sqlite3.connect('/Users/linhuichen/code/trade-data/data/sentiment.db')
    idx_ids = ['sh','sz','hs300','sz50','csi500','csi1000','cyb','kc50']
    index_tiers = build_index_tiers(conn, idx_ids)
    dates_by_id = {iid: sorted(t.keys()) for iid, t in index_tiers.items()}
    core5 = ['sh','sz','hs300','csi500','cyb']
    core8 = ['sh','sz','hs300','csi500','cyb','sz50','csi1000','kc50']
    synth_core5 = build_synth_index(conn, core5)
    conn.close()
    sd_i = fIdx['signal_date']
    F8 = {k: True for k in ['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial',
                            'k2c5HkChase','r7MayReinforced','excludeAuxCross','greedy15']}

    def agg(ids, method):
        def fn(t):
            sd = str(t[sd_i]); ranks = []
            for iid in ids:
                tr = tier_at(index_tiers.get(iid, {}), dates_by_id.get(iid, []), sd)
                if tr in TIER_RANK: ranks.append(TIER_RANK[tr])
            if not ranks: return ''
            if method == 'worst': return RANK_TIER[max(ranks)]
            if method == 'best': return RANK_TIER[min(ranks)]
            if method == 'mean': return RANK_TIER[round(sum(ranks)/len(ranks))]
            if method == 'mean_up': return RANK_TIER[min(3, math.ceil(sum(ranks)/len(ranks)))]
        return fn

    variants = {
        'hs300': lambda t: t[fIdx['market_tier']] or '',
        'cyb': lambda t: tier_at(index_tiers['cyb'], dates_by_id['cyb'], str(t[sd_i])),
        'kc50': lambda t: tier_at(index_tiers['kc50'], dates_by_id['kc50'], str(t[sd_i])),
        'sh': lambda t: tier_at(index_tiers['sh'], dates_by_id['sh'], str(t[sd_i])),
        'core5_synth': lambda t: tier_at(synth_core5, sorted(synth_core5.keys()), str(t[sd_i])),
        'core5_mean_up': agg(core5, 'mean_up'),
        'core8_worst': agg(core8, 'worst'),
        'none': None,
    }
    LABELS = {'hs300':'基准hs300','cyb':'cyb','kc50':'kc50','sh':'sh','core5_synth':'core5合成','core5_mean_up':'core5均值上取','core8_worst':'core8最差','none':'无键'}
    FOCUS = ['hs300','cyb','kc50','core8_worst','core5_mean_up','none']  # 全维度聚焦6源
    EXTRA = ['sh','core5_synth']  # 部分维度加测

    def bt_all(keys, start=None, end=None, cap=130000, P_N=3):
        out = {}
        for k in keys:
            n, st, kept, peak = run_backtest('G', make_passes(variants[k]), F8, cap=cap, P_N=P_N, start=start, end=end)
            out[k] = {'n': n, 'net': st['net'], 'ret': st['ret'], 'win': st['win'], 'peak_cap': st['peak_capital'],
                      'kept': kept, 'peak': peak}
        return out

    print("="*70)
    print("步骤0: 基准复现(v1.1.2 八键四档 G 每日池K1 P≤3d 13万 b0)")
    n0, s0, k0, p0 = run_backtest('G', make_passes(variants['hs300']), F8)
    print(f"  基准 = +{s0['net']:,.0f} / {s0['ret']:.2f}% (items={n0})")
    RESULT['baseline'] = {'net': s0['net'], 'ret': s0['ret'], 'items': n0}

    print("="*70)
    print("步骤1: 按年分解(2011-2026, 每年独立 13万 cap, 判定源全史)")
    years = sorted(set(str(t[fIdx['buy_date']] or '')[:4] for rows in get_by_date('G').values() for t in rows))
    ALLKEYS = FOCUS + EXTRA
    yearly = {}
    for y in years:
        ys, ye = y+'0101', y+'1231'
        row = {}
        for k in ALLKEYS:
            n, st, _, _ = run_backtest('G', make_passes(variants[k]), F8, start=ys, end=ye)
            row[k] = {'n': n, 'net': st['net'], 'ret': st['ret'], 'win': st['win']}
        yearly[y] = row
        hdr = f"  {y}: "
        cells = []
        for k in ALLKEYS:
            r = row[k]
            cells.append(f"{LABELS[k]}={r['net']:>7,.0f}/{r['win']:.0f}%")
        print(hdr + " | ".join(cells))
    RESULT['yearly'] = yearly

    print("="*70)
    print("步骤2: 剔除2026/分半/cap 敏感性(全史各段, G 模式)")
    segs = {
        '剔除2026(2011-2025)': ('20110101','20251231'),
        '全史(2011-2026)': ('20110101','20261231'),
        '前段2011-2018': ('20110101','20181231'),
        '后段2019-2026': ('20190101','20261231'),
    }
    res2 = {}
    for sname, (stt, end) in segs.items():
        row = {}
        for k in ALLKEYS:
            n, st, _, _ = run_backtest('G', make_passes(variants[k]), F8, start=stt, end=end)
            row[k] = {'n': n, 'net': st['net'], 'ret': st['ret'], 'win': st['win']}
        res2[sname] = row
        print(f"  {sname}: " + " ".join(f"{LABELS[k]}={row[k]['net']:>8,.0f}/{row[k]['ret']:.1f}%" for k in ALLKEYS))
    caprow = {}
    for cap in [130000, 150000, 200000]:
        row = {}
        for k in ALLKEYS:
            n, st, _, _ = run_backtest('G', make_passes(variants[k]), F8, cap=cap)
            row[k] = {'net': st['net'], 'ret': st['ret']}
        caprow[f'cap{int(cap/10000)}'] = row
        print(f"  cap{int(cap/10000)}万: " + " ".join(f"{LABELS[k]}={row[k]['net']:>8,.0f}/{row[k]['ret']:.1f}%" for k in ALLKEYS))
    res2['cap'] = caprow
    RESULT['segments'] = res2

    print("="*70)
    print("步骤3: 回撤分析(全史 G 模式, 累计已实现利润曲线, 主口径=回撤金额相对本金池%)")
    res3 = {}
    for k in ALLKEYS:
        n, st, kept, peak = run_backtest('G', make_passes(variants[k]), F8)
        dd = drawdown_analysis(kept, cap=130000, peak_cap=st['peak_capital'])
        res3[k] = {'net': st['net'], 'ret': st['ret'], 'n': st['n'], 'win': st['win'],
                   'peak_cap': st['peak_capital'], **dd}
        print(f"  {LABELS[k]:<12} net={st['net']:>9,.0f} ret={st['ret']:>7.2f}% 峰占用={st['peak_capital']:>8,.0f} "
              f"maxDD={dd['max_dd_amt']:>8,.0f}元({dd['max_dd_pct_cap']:.2f}%本金) 谷日={dd['max_dd_valley_sd']} 恢复={dd['max_dd_recover_sd'] or '未恢复'} "
              f"最长回撤期={dd['longest_dd_days']}d 恢复={dd['longest_recover_days']}d")
    RESULT['drawdown'] = res3

    print("="*70)
    print("步骤4: 大熊市窗口专项(窗口内独立模拟, 各判定源)")
    wins = {
        '2015股灾': ('20150601','20160229'),
        '2018熊全年': ('20180101','20181231'),
        '2022下跌': ('20220101','20221231'),
        '2023-24创业板阴跌': ('20230101','20240930'),
        '2024下半年反弹(牛,对比)': ('20240901','20241231'),
    }
    res4 = {}
    for wname, (stt, end) in wins.items():
        row = {}
        for k in ALLKEYS:
            n, st, _, _ = run_backtest('G', make_passes(variants[k]), F8, start=stt, end=end)
            row[k] = {'n': n, 'net': st['net'], 'ret': st['ret'], 'win': st['win']}
        res4[wname] = row
        print(f"  {wname}: " + " ".join(f"{LABELS[k]}={row[k]['net']:>7,.0f}/{row[k]['win']:.0f}%" for k in ALLKEYS))
    RESULT['bear_windows'] = res4

    print("="*70)
    print("步骤5: 不同周期(9模式矩阵扩展 kc50 + G 模式 P 档位变体)")
    modes = ['A','B','C','D','E','F','G','H','I']
    res5 = {}
    mrow = {}
    for mode in modes:
        r = {}
        for k in ['hs300','cyb','kc50','core8_worst']:
            n, st, _, _ = run_backtest(mode, make_passes(variants[k]), F8)
            r[k] = {'net': st['net'], 'ret': st['ret']}
        mrow[mode] = r
        print(f"  {mode}: " + " ".join(f"{LABELS[k]}={r[k]['net']:>8,.0f}" for k in ['hs300','cyb','kc50','core8_worst']))
    res5['mode_matrix'] = mrow
    prow = {}
    for PN in [3, 5, 10, 20]:
        r = {}
        for k in ['hs300','cyb']:
            n, st, _, _ = run_backtest('G', make_passes(variants[k]), F8, P_N=PN)
            r[k] = {'net': st['net'], 'ret': st['ret']}
        prow[f'P<={PN}d'] = r
        h = r['hs300']['net']; c = r['cyb']['net']
        print(f"  P<={PN}d: hs300={h:>8,.0f} cyb={c:>8,.0f} (Δ{c-h:+,.0f})")
    res5['p_variants'] = prow
    RESULT['periods'] = res5

    out_path = os.path.join(ROOT, '..', 'data', 'results_fourtier_v2_stability.json')
    # 去掉 kept(大对象)再落盘
    def _clean(o):
        if isinstance(o, dict):
            return {k: (_clean(v) if k != 'kept' else None) for k, v in o.items()}
        if isinstance(o, list): return [_clean(x) for x in o]
        return o
    with open(out_path, 'w') as f:
        json.dump(_clean(RESULT), f, ensure_ascii=False, indent=1)
    print(f"\n结果已写入: {os.path.abspath(out_path)}")

if __name__ == '__main__':
    main()
