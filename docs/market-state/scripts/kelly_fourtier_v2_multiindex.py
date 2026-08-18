# ============================================================
# 用途: 四档升级版验证(大盘+各指数四档/综合四档) — v1.1.2 宇宙基座穷举回测
# 日期/来源: 2026-08-18 / 本任务调研
# 结论: ①现 hs300 四档键在 G 模式负边际(-3,765), 综合/多指数判定源升级有效
#      ②最优口径=单指数 cyb(创业板)四档作为 excludeSpecialBear 判定源, 排除{熊市·主跌,下降期},
#        G 模式 +16,720(+12.86pp), 9 模式 8 正 1 小负(H -2,049), cap/分半/按年稳健
#      ③次优=投票 core8 最差(G +15,504), 但 A/B/C/D/F 短持模式负, 不如 cyb 稳健
#      ④排除力度「熊市+下降期」对 cyb/core8 均为最优(与现 hs300 一致, 只需换判定源)
# 依赖: static-site/data/signal_kelly_trades.json(2026-08-18 09:14) + trade-data/data/sentiment.db(index_daily)
#       docs/kelly/scripts/{kelly_combo_advice_analysis,kelly_posfilter_backtest,dailypool_rerun_core,kelly_ghi_g_scan}.py
# 输出: stdout 各步骤关键表 + data/results_fourtier_v2.json
# 复现: python3 docs/market-state/scripts/kelly_fourtier_v2_multiindex.py
# 关键口径: v1.1.2 基准 = 8键(n2/excludeSpecialBear四档/janMidRating/janMidSpecial/k2c5HkChase/r7/excludeAuxCross/greedy15)
#       + 每日资金池等分 + 当日 top1 + G 用 P≤3d 13万 b0(强平记0利); 收益率=净利÷仿真峰值
# ============================================================
# -*- coding: utf-8 -*-
import sys, contextlib, io, sqlite3, bisect, math, json, os
from collections import defaultdict, Counter
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

# ---------- 多指数四档构建 ----------
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
    """归一化等权合成综合指数 → 四档"""
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

# ---------- 过滤谓词(v1.1.2 八键, excludeSpecialBear 判定源可换) ----------
def make_passes(tier_fn, excl_set=EXCL_SET):
    def passes(t, F):
        F2 = dict(F); F2.pop('excludeSpecialBear', None); F2.pop('k2c5HkChase', None)
        if not passes_fade(t, F2): return False
        sig = str(t[fIdx['signal']] or '')
        if F.get('excludeSpecialBear') and sig == 'buy_special':
            if tier_fn is None:  # 无键
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
        return len(items), st
    else:
        st = compute_scaled(items)
        return len(items), st

# ---------- 档位区分度 ----------
def analyze_tier(trades, tier_fn, label):
    groups = defaultdict(list)
    for t in trades:
        tr = tier_fn(t)
        if tr in TIER_RANK: groups[tr].append(t)
    out = {}
    for tr, grp in groups.items():
        n = len(grp)
        wins = sum(1 for t in grp if (t[fIdx['profit']] or 0) > 0)
        out[tr] = {'n': n, 'win': round(wins/n*100, 2), 'avg_p': round(sum(t[fIdx['profit']] or 0 for t in grp)/n)}
    return out

def main():
    d = load()
    data_fields = d['fields']
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
        '基准 hs300四档': lambda t: t[fIdx['market_tier']] or '',
        '单指数 sh': lambda t: tier_at(index_tiers['sh'], dates_by_id['sh'], str(t[sd_i])),
        '单指数 sz': lambda t: tier_at(index_tiers['sz'], dates_by_id['sz'], str(t[sd_i])),
        '单指数 sz50': lambda t: tier_at(index_tiers['sz50'], dates_by_id['sz50'], str(t[sd_i])),
        '单指数 csi500': lambda t: tier_at(index_tiers['csi500'], dates_by_id['csi500'], str(t[sd_i])),
        '单指数 csi1000': lambda t: tier_at(index_tiers['csi1000'], dates_by_id['csi1000'], str(t[sd_i])),
        '单指数 cyb': lambda t: tier_at(index_tiers['cyb'], dates_by_id['cyb'], str(t[sd_i])),
        '单指数 kc50': lambda t: tier_at(index_tiers['kc50'], dates_by_id['kc50'], str(t[sd_i])),
        '综合指数core5': lambda t: tier_at(synth_core5, sorted(synth_core5.keys()), str(t[sd_i])),
        '投票core5_最差': agg(core5, 'worst'),
        '投票core5_均值': agg(core5, 'mean'),
        '投票core5_均值上取': agg(core5, 'mean_up'),
        '投票core5_最好': agg(core5, 'best'),
        '投票core8_最差': agg(core8, 'worst'),
        '投票core8_次差': agg(core8, '2nd_worst' if False else 'worst'),  # 见下方单独
        '无excludeSpecialBear': None,
    }
    # 次差单独定义
    def agg2nd(ids):
        def fn(t):
            sd = str(t[sd_i]); ranks = []
            for iid in ids:
                tr = tier_at(index_tiers.get(iid, {}), dates_by_id.get(iid, []), sd)
                if tr in TIER_RANK: ranks.append(TIER_RANK[tr])
            if not ranks: return ''
            if len(ranks) < 2: return RANK_TIER[max(ranks)]
            return RANK_TIER[sorted(ranks)[-2]]
        return fn
    variants['投票core8_次差'] = agg2nd(core8)

    print("="*70)
    print("步骤0: 基准复现(v1.1.2 八键四档, G 每日池K1 + P≤3d 13万 b0)")
    n0, s0 = run_backtest('G', make_passes(variants['基准 hs300四档']), F8)
    print(f"  基准 = +{s0['net']:,.0f} / {s0['ret']:.2f}% (items={n0})")
    RESULT['baseline'] = {'net': s0['net'], 'ret': s0['ret'], 'items': n0}

    print("="*70)
    print("步骤1: 判定源敏感性叠加回测(G 每日池K1 + P≤3d 13万 b0)")
    res1 = {}
    for label, fn in variants.items():
        n, st = run_backtest('G', make_passes(fn), F8)
        res1[label] = {'net': st['net'], 'ret': st['ret'], 'items': n,
                       'dnet': st['net']-s0['net'], 'dret': round(st['ret']-s0['ret'], 2)}
        print(f"  {label:<18} items={n:>5} net={st['net']:>10,.0f} ret={st['ret']:>7.2f}% Δnet={st['net']-s0['net']:>+9,.0f} Δret={st['ret']-s0['ret']:>+6.2f}pp")
    RESULT['variant_overlay'] = res1

    print("="*70)
    print("步骤2: 排除力度敏感性(cyb / core8最差 × 排除档位组合)")
    strength = {'熊市': {'熊市·主跌'}, '熊市+下降期': {'熊市·主跌','下降期'}, '熊市+下降期+上升期': {'熊市·主跌','下降期','上升期'}}
    for sname, sfn in [('cyb', variants['单指数 cyb']), ('core8最差', variants['投票core8_最差'])]:
        row = f"  {sname}: "
        for ename, eset in strength.items():
            n, st = run_backtest('G', make_passes(sfn, eset), F8)
            row += f"[{ename} {st['net']:,.0f}/{st['ret']:.1f}%] "
        print(row)
    RESULT['strength'] = {k: None for k in strength}

    print("="*70)
    print("步骤3: 9模式全矩阵(hs300 vs cyb vs core8最差)")
    modes = ['A','B','C','D','E','F','G','H','I']
    res3 = {}
    for mode in modes:
        nets = {}
        for label, fn in [('hs300', variants['基准 hs300四档']), ('cyb', variants['单指数 cyb']), ('core8w', variants['投票core8_最差'])]:
            n, st = run_backtest(mode, make_passes(fn), F8)
            nets[label] = {'net': st['net'], 'ret': st['ret'], 'items': n}
        res3[mode] = nets
        print(f"  {mode}: hs300={nets['hs300']['net']:>9,.0f} cyb={nets['cyb']['net']:>9,.0f}(Δ{nets['cyb']['net']-nets['hs300']['net']:+,.0f}) core8w={nets['core8w']['net']:>9,.0f}(Δ{nets['core8w']['net']-nets['hs300']['net']:+,.0f})")
    RESULT['mode_matrix'] = res3

    print("="*70)
    print("步骤4: 稳健性(cap 13/15/20万 + 分半测试, G 模式)")
    res4 = {}
    for cap in [130000, 150000, 200000]:
        row = {}
        for label, fn in [('hs300', variants['基准 hs300四档']), ('cyb', variants['单指数 cyb']), ('core8w', variants['投票core8_最差'])]:
            n, st = run_backtest('G', make_passes(fn), F8, cap=cap)
            row[label] = {'net': st['net'], 'ret': st['ret']}
        res4[f'cap{int(cap/10000)}'] = row
        print(f"  cap{int(cap/10000)}万: " + " ".join(f"{k}={v['net']:,.0f}/{v['ret']:.1f}%" for k,v in row.items()))
    for seg, (stt, end) in [('前段2011-2018', ('20110101','20181231')), ('后段2019-2026', ('20190101','20261231'))]:
        row = {}
        for label, fn in [('hs300', variants['基准 hs300四档']), ('cyb', variants['单指数 cyb']), ('core8w', variants['投票core8_最差'])]:
            n, st = run_backtest('G', make_passes(fn), F8, start=stt, end=end)
            row[label] = {'net': st['net'], 'ret': st['ret']}
        res4[seg] = row
        print(f"  {seg}: " + " ".join(f"{k}={v['net']:,.0f}/{v['ret']:.1f}%" for k,v in row.items()))
    RESULT['robust'] = res4

    print("="*70)
    print("步骤5: 逐日档位不一致率(展示差异, 2011-2026 信号日)")
    bd = get_by_date('G')
    all_dates = sorted(set(str(t[sd_i]) for rows in bd.values() for t in rows))
    hs_dates = dates_by_id['hs300']
    vw5 = agg(core5, 'worst'); vw8 = agg(core8, 'worst')
    dummy = [None]*len(fIdx)
    diff5 = diff8 = 0
    for sd in all_dates:
        dummy[sd_i] = sd
        th = tier_at(index_tiers['hs300'], hs_dates, sd)
        if vw5(dummy) != th: diff5 += 1
        if vw8(dummy) != th: diff8 += 1
    print(f"  信号日 {len(all_dates)}: core5最差 vs hs300 不一致 {diff5/len(all_dates)*100:.1f}%; core8最差 vs hs300 {diff8/len(all_dates)*100:.1f}%")
    RESULT['display_diff'] = {'n_dates': len(all_dates), 'core5_pct': round(diff5/len(all_dates)*100,1), 'core8_pct': round(diff8/len(all_dates)*100,1)}


    print("="*70)
    print("步骤6: 按年拆分(cyb vs hs300, G 模式)")
    res6 = {}
    years = sorted(set(str(t[fIdx['buy_date']] or '')[:4] for rows in get_by_date('G').values() for t in rows))
    for y in years:
        ys, ye = y+'0101', y+'1231'
        row = {}
        for label, fn in [('hs300', variants['基准 hs300四档']), ('cyb', variants['单指数 cyb'])]:
            n, st = run_backtest('G', make_passes(fn), F8, start=ys, end=ye)
            row[label] = {'net': st['net'], 'ret': st['ret']}
        res6[y] = row
        print(f"  {y}: hs300={row['hs300']['net']:>8,.0f} cyb={row['cyb']['net']:>8,.0f} Δ={row['cyb']['net']-row['hs300']['net']:>+8,.0f}")
    RESULT['yearly'] = res6
    out_path = os.path.join(ROOT, '..', 'data', 'results_fourtier_v2.json')
    with open(out_path, 'w') as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=1)
    print(f"\n结果已写入: {os.path.abspath(out_path)}")

if __name__ == '__main__':
    main()
