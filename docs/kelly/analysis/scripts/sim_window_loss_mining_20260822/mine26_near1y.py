# -*- coding: utf-8 -*-
"""mine26 近1年窗口「最强+最平稳」双榜穷举回测(mine26_near1y,2026-08-23 主控令)。
背景: 全史结论已定=NEW 最强最稳(mine24_compare.json 权威);用户追问只看近1年(约 2025-08~2026-08)
      谁最强、谁最平稳(「月月赚钱 而不是起伏特别大的」)。
项目 8 行: P0_8键(基准行)/P1_9键/A_on9/B_on9/C_on9/NEW_14键/NEW2_18键。
口径(§5.4 钉死): 测试基准=current baseline v1.1.2,mode A + etf_def 费后,K1 补位口径
      (signal_date 分组→剔除命中→排序取 top-K→组内非空才成交,memory filter-backtest-position-fill-caliber);
      P0/P1/A/B/C 叠加口径(8/8+1 键先过滤再叠加),NEW/NEW2 重构口径(mode A 全池+仅自身键命中黑名单),
      与 mine24_compare 完全同构。锚点断言不过=中断不往下。
近1年两口径(诚实标注):
      主口径 = 最近12个自然月逐月(trades 截止日 dd0=max(signal_date)=20260820 → 2025-09~2026-08,含当月);
      对照口径 = 滚动365天 [dd0-365, dd0](= mine24_compare windows.近1年,速查卡「近1年」列同源)。
维度(§5.1⑤): ①近1年净利排名 ②逐月盈亏表(正月份占比/最差月/最好月/月度样本标准差/最大连续亏损月数,
      严格<0 口径为主,≤0 口径并列)③平稳榜(主标尺=正月份占比↓+最差月亏幅↑,辅助=月度std;
      双维综合分=收益名次+平稳名次,小者强,方法学同 mine25 §11.6)④窗口内回撤(sell_date 日聚合 cum pnl,
      窗口按 signal_date 过滤,跨窗卖出少量存在=诚实标注)⑤靠个别月撑起检验(ex_best=剔除最大盈利月后合计,
      top1 月占合计比)⑥与全史榜对照翻转分析。
输入依赖: static-site/data/signal_kelly_trades.json + data/mine10_features.json +
      data/mine24_global_search.json(NEW/NEW2 键集)+ data/mine24_compare.json(锚点)。
输出: data/mine26_near1y.json
复现: cd /Users/linhuichen/code/trade/docs/kelly/analysis/scripts/sim_window_loss_mining_20260822 && python3 mine26_near1y.py
"""
import os, sys, json, datetime, statistics
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, calc_row, base_key
from mine18_detail import FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2

OUT_PATH = os.path.join(BASE, 'data', 'mine26_near1y.json')
ANCHOR_PATH = os.path.join(BASE, 'data', 'mine24_compare.json')

# mine24_compare 模块级常量(键集与组合定义,复用不重造;模块级代码仅读 json,无副作用)
from mine24_compare import A_SUB, B_SUB, C_SUB, NEW_KEYS, NEW2_KEYS, max_dd_detail

def main():
    anchor = json.load(open(ANCHOR_PATH))
    feats = json.load(open(FEATS_PATH))
    tr, fIdx = load(R._ROOT + '/static-site/data/signal_kelly_trades.json')
    print(f'data generated_at={tr.get("generated_at")}')

    # ================= 叠加口径上下文(mine24_compare.main 同构复刻) =================
    rows, fIdxP = R.prepare_rows()
    assert len(fIdxP) == len(fIdx)
    R.init(rows, fIdxP)
    rules = build_rules(feats, fIdx); rules.update(build_r2(fIdx))
    c1 = lambda t: (t[2] in ('buy_aux', 'buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')

    def build_ctx(rws, fi):
        R.init(rws, fi)
        rl = build_rules(feats, fi); rl.update(build_r2(fi))
        h = {c: {R.base_key(t, fi) for t in rws if rl[c](t)} for c in set(A_SUB+B_SUB+C_SUB)}
        hc1 = {R.base_key(t, fi) for t in rws if c1(t)}
        g = {}
        for t in rws:
            g.setdefault(str(t[0]), []).append((R.base_key(t, fi), t))
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

    ctxA = build_ctx(rows, fIdx)
    P0 = ev(ctxA, (), False); P1 = ev(ctxA, (), True)
    st0, st1 = R.stats_of(P0), R.stats_of(P1)
    # ---- 锚点断言①: vs mine24_compare.json(mine23/mine24 同款三段) ----
    a = anchor['anchor']
    assert abs(st0['total'] - a['p0']) < 0.5, ('P0 锚点不符', st0['total'], a['p0'])
    assert abs(st1['total'] - a['p1']) < 0.5, ('P1 锚点不符', st1['total'], a['p1'])
    print(f'锚点 PASS: P0={st0["total"]:+,.2f}  P1={st1["total"]:+,.2f}(vs mine24_compare)')
    A9 = ev(ctxA, A_SUB, True); B9 = ev(ctxA, B_SUB, True); C9 = ev(ctxA, C_SUB, True)
    exp_imp = {'A9': (anchor['projects']['A_on9']['stats']['total'], 46007.00),
               'B9': (anchor['projects']['B_on9']['stats']['total'], 36469.07),
               'C9': (anchor['projects']['C_on9']['stats']['total'], 34010.95)}
    for nm, sel in [('A9', A9), ('B9', B9), ('C9', C9)]:
        tot = R.stats_of(sel)['total']; got = tot - st1['total']
        assert abs(tot - exp_imp[nm][0]) < 0.5, (nm, tot, exp_imp[nm][0])
        assert abs(got - exp_imp[nm][1]) < 1.0, (nm, got, exp_imp[nm][1])
    print('锚点 PASS: A9/B9/C9 绝对额+vs9键改进 双重一致(vs mine24_compare + mine22)')

    # ================= 重构口径上下文(mine24 复刻: 全池+HITS) =================
    pool = build_mode_pool(tr, fIdx, 'A')
    mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2
    R.IDX_PNL, R.IDX_SKEY = len(fIdx) + 3, len(fIdx) + 4
    RATING_RANK = {'high': 0, 'mid': 1, 'low': 2}; SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in pool:
        t.append(calc_row(t, fIdx))
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RATING_RANK.get(str(t[fIdx['rating']] or ''), 3),
                  SIG_RANK.get(str(t[fIdx['signal']] or ''), 9), str(t[fIdx['buy_date']] or '')))
    R.init(pool, fIdx)
    hist_keys = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
    HITS = {}
    for c in sorted(set(NEW_KEYS + NEW2_KEYS)):
        if c in hist_keys:
            f = {kk: False for kk in DEFAULT_FILTERS}; f[c] = True
            HITS[c] = {base_key(t, fIdx) for t in pool if not passes_fade(t, fIdx, f, active_month_mask(f), mD, eD, rD)}
        else:
            HITS[c] = {base_key(t, fIdx) for t in pool if rules[c](t)}
    groups = {}
    for t in pool:
        groups.setdefault(str(t[0]), []).append((base_key(t, fIdx), t))
    for sd in groups: groups[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
    sds = sorted(groups)

    def ev_new(keys, K=1):
        blk = set()
        for c in keys: blk |= HITS[c]
        sel = []
        for sd in sds:
            n = 0
            for key, t in groups[sd]:
                if key not in blk:
                    sel.append(t); n += 1
                    if n >= K: break
        return sel

    NEW = ev_new(NEW_KEYS); NEW2 = ev_new(NEW2_KEYS)
    ksN = frozenset(base_key(t, fIdx) for t in NEW); ksN2 = frozenset(base_key(t, fIdx) for t in NEW2)
    ksN_w = frozenset(base_key(t, fIdx) for t in NEW if str(t[0]) >= '20250901')
    ksN2_w = frozenset(base_key(t, fIdx) for t in NEW2 if str(t[0]) >= '20250901')
    print(f'NEW vs NEW2 入选集合: 全史 diff={len(ksN ^ ksN2)}笔, 近1年(>=20250901) diff={len(ksN_w ^ ksN2_w)}笔')
    stN, stN2 = R.stats_of(NEW), R.stats_of(NEW2)
    mddN = max_dd_detail(NEW, fIdx)['mdd']; mddN2 = max_dd_detail(NEW2, fIdx)['mdd']
    assert abs(stN['total'] - a['new_net']) < 1.0, ('NEW 锚点不符', stN['total'], a['new_net'])
    assert abs(stN2['total'] - a['new2_net']) < 1.0, ('NEW2 锚点不符', stN2['total'], a['new2_net'])
    assert abs(mddN - a['new_mdd']) < 5.0 and abs(mddN2 - a['new2_mdd']) < 5.0, (mddN, mddN2)
    print(f'锚点 PASS: NEW={stN["total"]:+,.2f}(mdd {mddN:,.2f})  NEW2={stN2["total"]:+,.2f}(mdd {mddN2:,.2f})')

    # ================= 近1年双口径 + 月度全维度 =================
    dd0s = max(str(t[0]) for t in pool)
    dd0 = datetime.date(int(dd0s[:4]), int(dd0s[4:6]), int(dd0s[6:]))
    w1b_roll = (dd0 - datetime.timedelta(days=365)).strftime('%Y%m%d')   # 滚动365 起点(=mine24 windows.近1年)
    yy, mm = dd0.year, dd0.month
    months = []
    for _ in range(12):
        months.append(f'{yy}{mm:02d}')
        mm -= 1
        if mm == 0: yy, mm = yy - 1, 12
    months = sorted(months)                                              # 最近12个自然月(含当月)
    m_start = months[0] + '01'
    print(f'数据截止 signal_date={dd0s} | 主口径12自然月={months[0][:4]}-{months[0][4:]}~{months[-1][:4]}-{months[-1][4:]} | 对照滚动365=[{w1b_roll},{dd0s}]')

    PROJECTS = [('P0_8键', P0), ('P1_9键', P1), ('A_on9', A9), ('B_on9', B9), ('C_on9', C9),
                ('NEW_14键', NEW), ('NEW2_18键', NEW2)]

    def month_stats(sel):
        mp = {}
        for t in sel:
            ym = str(t[0])[:6]
            mp.setdefault(ym, 0.0); mp[ym] += t[R.IDX_PNL]['pnlYuan']
        vals = [round(mp.get(ym, 0.0), 2) for ym in months]              # 0交易月按0计
        ns = [sum(1 for t in sel if str(t[0])[:6] == ym) for ym in months]
        pos = sum(1 for v in vals if v > 0); zero = sum(1 for v in vals if v == 0); neg = sum(1 for v in vals if v < 0)
        # 最大连续亏损月数: 严格<0 为主口径(0 打断);≤0 并列口径(0 延续)
        def streak(pred):
            best = cur = 0
            for v in vals:
                if pred(v): cur += 1; best = max(best, cur)
                else: cur = 0
            return best
        tot = round(sum(vals), 2)
        mx = max(vals); mn = min(vals)
        return dict(months={f'{y[:4]}-{y[4:]}': v for y, v in zip(months, vals)},
                    month_n=dict(zip([f'{y[:4]}-{y[4:]}' for y in months], ns)),
                    total=tot, pos_months=pos, zero_months=zero, neg_months=neg,
                    worst_month=mn, best_month=mx,
                    std_sample=round(statistics.stdev(vals), 2) if len(vals) > 1 else 0.0,
                    max_consec_neg_strict=streak(lambda v: v < 0),
                    max_consec_le0=streak(lambda v: v <= 0),
                    ex_best_total=round(tot - mx, 2),
                    top1_month_share=round(mx / tot, 3) if tot > 0 else None)

    out = dict(data_generated_at=tr.get('generated_at'),
               data_cutoff_signal_date=dd0s,
               window_def=dict(main='最近12个自然月 %s-%s ~ %s-%s(含当月,与逐月表一致)' % (months[0][:4], months[0][4:], months[-1][:4], months[-1][4:]),
                               roll365='[%s, %s](滚动365天,=mine24 windows.近1年/速查卡列)' % (w1b_roll, dd0s)),
               caliber='v1.1.2 基准 mode A + etf_def 费后 + K1 补位口径;P0/P1/A/B/C 叠加口径,NEW/NEW2 重构口径(同 mine24_compare)',
               projects={})

    rows_out = []
    for nm, sel in PROJECTS:
        ms = month_stats(sel)
        roll_tot = R.stats_of(R.window(sel, w1b_roll, None))['total']
        win_sel = R.window(sel, m_start, None)
        wst = R.stats_of(win_sel)
        ddx = max_dd_detail(win_sel, fIdx)
        # 窗口内回撤的跨窗卖出诚实标注: 窗内入选但 sell_date 落在窗外的笔
        cross = sum(1 for t in win_sel if str(t[fIdx['sell_date']] or '') > dd0s or str(t[fIdx['buy_date']] or '') < m_start)
        row = dict(name=nm, stats_all=R.stats_of(sel),
                   near1y_main=ms, near1y_roll365=roll_tot,
                   window_stats=wst, window_maxdd=ddx, cross_window_sells=cross)
        rows_out.append(row)
        out['projects'][nm] = row
        zl = ','.join(k for k, v in ms['months'].items() if v == 0) or '无'
        print(f"{nm}: 12月合计{ms['total']:+,.0f}(滚动365 {roll_tot:+,.0f}) 正月{ms['pos_months']}/12 最差{ms['worst_month']:+,.0f} "
              f"std{ms['std_sample']:,.0f} 连亏{ms['max_consec_neg_strict']}月 窗内mdd{ddx['mdd']:,.0f} 0元月[{zl}]")

    # ================= 排名: 收益榜 + 平稳榜 + 双维综合分(mine25 §11.6 名次法) =================
    order = [r['name'] for r in rows_out]
    gain_rank = sorted(order, key=lambda n: -out['projects'][n]['near1y_main']['total'])     # 收益名次(主口径12自然月)
    stab_rank = sorted(order, key=lambda n: (-out['projects'][n]['near1y_main']['pos_months'],
                                             -out['projects'][n]['near1y_main']['worst_month'],
                                             out['projects'][n]['near1y_main']['std_sample']))
    out['ranking'] = dict(
        note='收益名次=12自然月合计降序;平稳名次=主标尺(正月份数降序→最差月亏幅升序即少亏优先)→辅助(月度样本std升序),硬排名次(mine25 §11.6 同款);双维综合分=收益名次+平稳名次,越小越强',
        gain_rank=gain_rank,
        stability_rank=stab_rank,
        composite={n: dict(gain=gain_rank.index(n) + 1, stab=stab_rank.index(n) + 1,
                           sum=gain_rank.index(n) + 1 + stab_rank.index(n) + 1) for n in order})
    print('\n收益榜:', ' > '.join(f'{n}({out["projects"][n]["near1y_main"]["total"]:+,.0f})' for n in gain_rank))
    print('平稳榜:', ' > '.join(n for n in stab_rank))
    print('双维综合分:', {n: out['ranking']['composite'][n]['sum'] for n in sorted(order, key=lambda x: out['ranking']['composite'][x]['sum'])})

    # ================= 全史对照(翻转分析素材) =================
    all_hist = {n: out['projects'][n]['stats_all']['total'] for n in order}
    hist_rank = sorted(order, key=lambda n: -all_hist[n])
    out['full_history_ref'] = dict(net=all_hist, rank=hist_rank,
                                   note='全史净利与名次(本轮重算,锚点已对 mine24_compare 逐位验证)')
    print('全史榜:', ' > '.join(f'{n}({all_hist[n]:+,.0f})' for n in hist_rank))

    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
