# -*- coding: utf-8 -*-
"""二轮挖掘 mine24 新王牌全维度对比(mine24_compare,2026-08-23 主控令·补 mine23 §15.11 式全维度)。
背景: mine24_global_search 找到 8 个支配 A 方案的解;用户要求补齐与 mine23 §15.11 同口径的全维度对比表。
项目 7 个:
  P0=8键基线 / P1=9键(8+候选1,当前实测态) —— 叠加口径基座(mine23 同款复现)
  A_on9 / B_on9 / C_on9 —— mine23 §15.11 同款(cand1 OR 组合=叠加在 8+1 上)
  NEW = mine24 14键最小形态(domina­tors_of_A 中 net=+122,648.33/mdd=-4,178.01 键数最少者)
  NEW2 = +120,564.54/mdd=-4,083.63 的 18 键变体
口径诚实标注: NEW/NEW2 为**重构口径**(mode A 全池+黑名单=仅这 14/18 个键自身命中,不预设 8 默认键在场),
A/B/C 为**叠加口径**(8+1 键先过滤再叠加组合);两者对 P0/P1 的对照已显式分开标注。
维度(mine23 §15.11 全套): 全史总额/笔数/胜率/PF/空仓信号日/峰值持仓;六窗口(近1/2/3/5/10年+全史)+2026YTD;
四熊市(BEARS 复用);四牛市(2014-15/2019-20/2020-21/2025,含笔数,窗口用 mine23_bulls.json 数字复现验证);
大亏月 Top10 矩阵(按 P1 月度挑月,7 项目绝对值对照);近1年逐月摊开;2026 逐月+2-3月+5-8月合计;
K1-K4 绝对额;按年 16 年(total+n);回撤 trough/recover;九模式 A-I;
被拦/替补分解(vs P0 与 vs P1 双份);NEW 家族 8 解入选笔集合级等价核实。
锚点断言: P0=+66,530.38 / P1=+73,102.53 / A9+46,007 / B9+36,469 / C9+34,011(vs9键);
NEW=+122,648.33&mdd-4,178.01 / NEW2=+120,564.54&mdd-4,083.63;
NEW vs P0 交叉断言=mine24 robust 字段(blocked 829/-27,024.39、added 132/+29,093.56、前向+17,223.81、
K234、模式B-F、四熊、近1年+2,474.71)。
输出: data/mine24_compare.json
复现: python3 mine24_compare.py(依赖 mine10_features.json + mine20_pool.json(经 build_rules 间接) + signal_kelly_trades.json + mine24_global_search.json)
"""
import os, sys, json, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, calc_row, base_key
from mine18_detail import BEARS, FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2
from mine17_modes import prep_mode

OUT_PATH = os.path.join(BASE, 'data', 'mine24_compare.json')
M24_PATH = os.path.join(BASE, 'data', 'mine24_global_search.json')
BULLS23_PATH = os.path.join(BASE, 'data', 'mine23_bulls.json')

A_SUB = ('T1','Q1','M1','V1','R1','R2a','R2b','R2g')
B_SUB = ('T1','Q1','M1','R1','R2b','R2g')
C_SUB = ('N1','T1','D1','H1','M1','P1','R2b')

# ---- 四牛市窗口(还原 §15.11.4 文字定义;下方用 mine23_bulls.json 数字断言验证) ----
BULLS4 = [('牛市·2014-15杠杆牛上半场', '20140701', '20150614'),
          ('牛市·2019-20结构牛',       '20190101', '20200229'),
          ('牛市·2020-21核心资产牛',   '20200324', '20211231'),
          ('牛市·2025长牛',            '20250101', None)]

M24 = json.load(open(M24_PATH))
DOMS = M24['dominators_of_A']
NEW_KEYS = min((d for d in DOMS if abs(d['net'] - 122648.33) < 1), key=lambda d: len(d['keys']))['keys']
NEW2_KEYS = next(d['keys'] for d in DOMS if abs(d['net'] - 120564.54) < 1)

def max_dd_detail(sel, fIdx):
    bys = {}
    for t in sel:
        sd = str(t[fIdx['sell_date']] or '')
        if not sd: continue
        bys.setdefault(sd, 0.0); bys[sd] += t[R.IDX_PNL]['pnlYuan']
    cum = peak = 0.0; mdd = 0.0; trough = None; peak_at_trough = 0.0
    for sd in sorted(bys):
        cum += bys[sd]
        if cum > peak: peak = cum
        if cum - peak < mdd:
            mdd = cum - peak; trough = sd; peak_at_trough = peak
    rec = None
    if trough is not None:
        cum = 0.0; past = False
        for sd in sorted(bys):
            cum += bys[sd]
            if sd == trough: past = True
            if past and cum >= peak_at_trough:
                rec = sd; break
    return dict(mdd=round(mdd, 2), trough_day=trough, recovered=rec is not None, recover_day=rec,
                recover_days=(int(rec[:4])*365-int(trough[:4])*365)+(int(rec[4:6])-int(trough[4:6]))*30+(int(rec[6:])-int(trough[6:])) if rec else None)

def pf_of(sel):
    g = sum(t[R.IDX_PNL]['pnlYuan'] for t in sel if t[R.IDX_PNL]['pnlYuan'] > 0)
    l = sum(t[R.IDX_PNL]['pnlYuan'] for t in sel if t[R.IDX_PNL]['pnlYuan'] < 0)
    return round(g / abs(l), 2) if l else None

def peak_pos(sel, fIdx):
    """当日持仓峰值(sim_core.window_stats 先删后加同逻辑)。"""
    asc = sorted(sel, key=lambda t: str(t[fIdx['signal_date']] or ''))
    pk = 0; open_map = {}; gi = 0
    while gi < len(asc):
        sd = str(asc[gi][fIdx['signal_date']] or '')
        gj = gi
        while gj < len(asc) and str(asc[gj][fIdx['signal_date']] or '') == sd: gj += 1
        for ok in [k for k, v in open_map.items() if v and v <= sd]: del open_map[ok]
        for i in range(gi, gj):
            bd = str(asc[i][fIdx['buy_date']] or ''); sld = str(asc[i][fIdx['sell_date']] or '')
            if bd and bd <= sd and (sld == '' or sld > sd):
                open_map.setdefault(base_key(asc[i], fIdx), sld)
        if len(open_map) > pk: pk = len(open_map)
        gi = gj
    return pk

def full_stats(sel, base_n_dates, fIdx):
    st = R.stats_of(sel)
    st['pf'] = pf_of(sel)
    st['zero_days_vs_p0'] = base_n_dates - st['n']
    st['freq_pct_vs_p0'] = round(st['n'] / max(base_n_dates, 1) * 100, 1)
    st['peakPosN'] = peak_pos(sel, fIdx)
    return st

def month_sel(sel, ym):
    return [t for t in sel if str(t[0])[:6] == ym]

def main():
    feats = json.load(open(FEATS_PATH))
    tr, fIdx = load(R._ROOT + '/static-site/data/signal_kelly_trades.json')
    print(f'data generated_at={tr.get("generated_at")}')

    # ================= 叠加口径上下文(mine23 复刻) =================
    rows, fIdxP = R.prepare_rows()
    assert len(fIdxP) == len(fIdx)
    R.init(rows, fIdx)
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
    assert abs(st0['total'] - 66530.38) < 0.5, st0['total']
    assert abs(st1['total'] - 73102.53) < 0.5, st1['total']
    print(f'锚点 PASS: P0(8键)={st0["total"]:+,.2f}  P1(9键)={st1["total"]:+,.2f}')
    A9 = ev(ctxA, A_SUB, True); B9 = ev(ctxA, B_SUB, True); C9 = ev(ctxA, C_SUB, True)
    for nm, sel, imp in [('A9', A9, 46007.00), ('B9', B9, 36469.07), ('C9', C9, 34010.95)]:
        got = R.stats_of(sel)['total'] - st1['total']
        assert abs(got - imp) < 1.0, f'{nm} vs mine22 不一致: {got} vs {imp}'
    print('mine22 复验 PASS: A9 +46,007 / B9 +36,469 / C9 +34,011(vs9键)')

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
    need_keys = sorted(set(k for d in DOMS for k in d['keys']))  # 覆盖全部 8 解(供等价核实)
    HITS = {}
    hist_keys = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
    for c in need_keys:
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

    def sel_keyset(sel):
        return frozenset(R.base_key(t, fIdx) for t in sel)

    NEW = ev_new(NEW_KEYS); NEW2 = ev_new(NEW2_KEYS)
    stN, stN2 = R.stats_of(NEW), R.stats_of(NEW2)
    mddN, mddN2 = max_dd_detail(NEW, fIdx)['mdd'], max_dd_detail(NEW2, fIdx)['mdd']
    assert abs(stN['total'] - 122648.33) < 1.0, stN['total']
    assert abs(mddN - (-4178.01)) < 5.0, mddN
    assert abs(stN2['total'] - 120564.54) < 1.0, stN2['total']
    assert abs(mddN2 - (-4083.63)) < 5.0, mddN2
    print(f'锚点 PASS: NEW(14键)={stN["total"]:+,.2f}(mdd {mddN:,.2f})  NEW2(18键)={stN2["total"]:+,.2f}(mdd {mddN2:,.2f})')

    # ---- mine24 robust 交叉断言(NEW vs P0) ----
    detN_vsP0 = R.diff_detail(P0, NEW)
    assert detN_vsP0['blocked_n'] == 829 and abs(detN_vsP0['blocked_pnl'] - (-27024.39)) < 1.0, detN_vsP0
    assert detN_vsP0['added_n'] == 132 and abs(detN_vsP0['added_pnl'] - 29093.56) < 1.0, detN_vsP0
    dd0s = max(str(t[0]) for t in rows)
    dd0 = datetime.date(int(dd0s[:4]), int(dd0s[4:6]), int(dd0s[6:]))
    w1b = (dd0 - datetime.timedelta(days=365)).strftime('%Y%m%d')
    d1y = R.stats_of(R.window(NEW, w1b, None))['total'] - R.stats_of(R.window(P0, w1b, None))['total']
    dall = stN['total'] - st0['total']
    assert abs(d1y - 2474.71) < 1.0 and abs(dall - 56117.95) < 1.0, (d1y, dall)
    bearsN = {lab: round(R.stats_of(R.window(NEW, a, b))['total'] - R.stats_of(R.window(P0, a, b))['total'], 2) for lab, a, b in BEARS}
    exp_bears = {'2015股灾~熔断': 3543.78, '2018贸易战熊市': 1645.34, '2022单边熊': 16155.05, '2024Q1小微盘流动性危机': -2118.57}
    for lab, v in exp_bears.items():
        assert abs(bearsN[lab] - v) < 1.0, (lab, bearsN[lab], v)
    # K 敏感性的 mine24 口径=vs 8默认键同 K(全池 blk=DEFAULT8);单独重建
    HITS_D8 = {}
    for c in ['n2NovSpecialIndustry', 'excludeSpecialBear', 'janMidRating', 'janMidSpecial', 'k2c5HkChase', 'r7MayReinforced', 'excludeAuxCross', 'greedy15']:
        f = {kk: False for kk in DEFAULT_FILTERS}; f[c] = True
        HITS_D8[c] = {base_key(t, fIdx) for t in pool if not passes_fade(t, fIdx, f, active_month_mask(f), mD, eD, rD)}
    D8_SET = set().union(*HITS_D8.values())
    def ev_d8(K):
        sel = []
        for sd in sds:
            n = 0
            for key, t in groups[sd]:
                if key not in D8_SET:
                    sel.append(t); n += 1
                    if n >= K: break
        return sel
    for K in (2, 3, 4):
        got = R.stats_of(ev_new(NEW_KEYS, K))['total'] - R.stats_of(ev_d8(K))['total']
        exp = {'K2': 73871.89, 'K3': 59530.96, 'K4': 46106.48}[f'K{K}']
        assert abs(got - exp) < 1.0, (K, got, exp)
    print('mine24 robust 交叉断言 PASS: blocked 829(-27,024)/added 132(+29,094)/近1年+2,475/K234/四熊 全一致')

    # ---- 四牛市窗口端点验证(仅用无 on8/on9 歧义的 P0/P1/C@2014-15 对照 mine23_bulls.json;
    #      A/B 不作断言——审计发现 mine23_bulls.json 的 A/B 为 on8 混口径,详见 out['bulls23_audit']) ----
    bulls23 = json.load(open(BULLS23_PATH))
    name_map = {'P0': P0, 'P1': P1}
    short = [('2014-15杠杆牛上半场', '牛市·2014-15杠杆牛上半场'), ('2019-20结构牛', '牛市·2019-20结构牛'),
             ('2020-21核心资产牛', '牛市·2020-21核心资产牛'), ('2025长牛', '牛市·2025长牛')]
    for lab23, lab4 in short:
        a_, b_ = next((x[1], x[2]) for x in BULLS4 if x[0] == lab4)
        for pj, sel in name_map.items():
            exp = bulls23[lab23][pj]['total']
            got = R.stats_of(R.window(sel, a_, b_))['total']
            assert abs(got - exp) < 0.5, f'牛市窗口 {lab23}/{pj}: {got} vs {exp}'
    # C 的 2014-15 恰好 on8=on9(该段候选1拦截笔不在 C 选择集),亦可用于端点验证
    got_c = R.stats_of(R.window(C9, '20140701', '20150614'))['total']
    assert abs(got_c - bulls23['2014-15杠杆牛上半场']['C']['total']) < 0.5
    print('四牛市窗口端点验证 PASS(P0/P1/C 三序列与 mine23_bulls.json 逐位一致;A/B 为 on8 混口径不入断言,见 audit)')

    # ================= 全维度跑 7 项目 =================
    base_nd = st0['n']
    WINS = [('近1年', w1b, None),
            ('近2年', (dd0 - datetime.timedelta(days=730)).strftime('%Y%m%d'), None),
            ('近3年', (dd0 - datetime.timedelta(days=1095)).strftime('%Y%m%d'), None),
            ('近5年', (dd0 - datetime.timedelta(days=1825)).strftime('%Y%m%d'), None),
            ('近10年', (dd0 - datetime.timedelta(days=3650)).strftime('%Y%m%d'), None),
            ('2026YTD', '20260101', None),
            ('全史', '00010101', None)]
    MONTHS26 = [(f'2026-{m:02d}', f'20260{m:02d}' if m <= 9 else '', None) for m in range(2, 9)]

    # 大亏月 Top10(按 P1 月度 pnl 升序挑 10 个月)
    mp1 = {}
    for t in P1:
        ym = str(t[0])[:6]
        mp1.setdefault(ym, 0.0); mp1[ym] += t[R.IDX_PNL]['pnlYuan']
    worst10 = sorted(mp1, key=lambda y: mp1[y])[:10]

    PROJECTS = [('P0_8键', P0), ('P1_9键', P1), ('A_on9', A9), ('B_on9', B9), ('C_on9', C9),
                ('NEW_mine24_14键', NEW), ('NEW2_18键变体', NEW2)]
    out = dict(anchor=dict(p0=st0['total'], p1=st1['total'],
                           new_net=stN['total'], new_mdd=mddN, new2_net=stN2['total'], new2_mdd=mddN2),
               data_generated_at=tr.get('generated_at'),
               new_keys=NEW_KEYS, new2_keys=NEW2_KEYS, projects={}, note=None)

    sels = dict(P0=P0, P1=P1, A=A9, B=B9, C=C9, NEW=NEW, NEW2=NEW2)
    stats_cache = {}
    for nm, sel in PROJECTS:
        st = full_stats(sel, base_nd, fIdx)
        mddD = max_dd_detail(sel, fIdx)
        yr = R.yearly_buckets(sel)
        yr_n = {}
        for t in sel: yr_n[str(t[0])[:4]] = yr_n.get(str(t[0])[:4], 0) + 1
        wins = {lab: round(R.stats_of(R.window(sel, a, b))['total'], 2) for lab, a, b in WINS}
        bears = {lab: round(R.stats_of(R.window(sel, a, b))['total'], 2) for lab, a, b in BEARS}
        bulls = {}
        for lab4, a_, b_ in BULLS4:
            ws = R.stats_of(R.window(sel, a_, b_))
            bulls[lab4] = dict(total=round(ws['total'], 2), n=ws['n'])
        m26 = {}
        for m in range(2, 9):
            m26[f'2026-{m:02d}'] = round(R.stats_of(month_sel(sel, f'2026{m:02d}'))['total'], 2)
        m26['2026-02~03'] = round(R.stats_of(R.window(sel, '20260201', '20260331'))['total'], 2)
        m26['2026-05~08'] = round(R.stats_of(R.window(sel, '20260501', '20260831'))['total'], 2)
        m26['2026全年'] = wins['2026YTD']
        wm = {ym: round(R.stats_of(month_sel(sel, ym))['total'], 2) for ym in worst10}
        recent = []
        cur = (dd0.year, dd0.month)
        yy, mm_ = cur
        for _ in range(12):
            recent.append(f'{yy}{mm_:02d}')
            mm_ -= 1
            if mm_ == 0: yy, mm_ = yy - 1, 12
        recent = sorted(recent)
        r12 = {f'{y[:4]}-{y[4:]}': round(R.stats_of(month_sel(sel, y))['total'], 2) for y in recent}
        kk = {}
        for K in (1, 2, 3, 4):
            if nm == 'P0_8键':
                kk[f'K{K}'] = round(R.stats_of(ev(ctxA, (), False, K))['total'], 2)
            elif nm in ('P1_9键', 'A_on9', 'B_on9', 'C_on9'):
                sub = {'P1_9键': (), 'A_on9': A_SUB, 'B_on9': B_SUB, 'C_on9': C_SUB}[nm]
                kk[f'K{K}'] = round(R.stats_of(ev(ctxA, sub, True, K))['total'], 2)
            elif nm == 'NEW_mine24_14键':
                kk[f'K{K}'] = round(R.stats_of(ev_new(NEW_KEYS, K))['total'], 2)
            else:
                kk[f'K{K}'] = round(R.stats_of(ev_new(NEW2_KEYS, K))['total'], 2)
        det = {}
        if nm not in ('P0_8键',):
            base_sel = P1 if nm in ('P1_9键', 'A_on9', 'B_on9', 'C_on9') else P0
            det['vs_P1' if nm in ('P1_9键', 'A_on9', 'B_on9', 'C_on9') else 'vs_P0'] = R.diff_detail(base_sel, sel)
        if nm in ('NEW_mine24_14键', 'NEW2_18键变体'):
            det['vs_P0'] = R.diff_detail(P0, sel)
            det['vs_P1'] = R.diff_detail(P1, sel)
        out['projects'][nm] = dict(stats=st, maxdd=mddD,
                                   yearly={y: dict(total=yr[y], n=yr_n.get(y, 0)) for y in yr},
                                   windows=wins, bears=bears, bulls=bulls, months26=m26,
                                   worst_months_top10=wm, recent_12months=r12,
                                   blocked_added=det, k_sensitivity=kk)
        stats_cache[nm] = sel
        print(f"{nm}: total={st['total']:+,.0f} n={st['n']} 胜率{st['winRate']}% PF={st['pf']} 空仓+{st['zero_days_vs_p0']} 峰持{st['peakPosN']} mdd={mddD['mdd']:.0f} 谷{mddD['trough_day']}→复{mddD['recover_day']}")

    # ---- mine23_bulls.json 口径审计(on9 权威 vs 该文件标注值;§15.11.4 表历史遗留证据) ----
    audit = {}
    for lab23, lab4 in short:
        a_, b_ = next((x[1], x[2]) for x in BULLS4 if x[0] == lab4)
        row = {}
        for pj, sel in [('A_on9', A9), ('B_on9', B9), ('C_on9', C9)]:
            got = round(R.stats_of(R.window(sel, a_, b_))['total'], 2)
            jv = bulls23[lab23][pj[0]]['total']
            row[pj] = dict(authoritative_on9=got, bulls_json_labeled=jv,
                           match=abs(got - jv) < 0.5)
        audit[lab23] = row
    out['bulls23_audit'] = dict(
        detail=audit,
        conclusion=('mine23_bulls.json(§15.11.4 四牛市表数据源)的 A/B 列为 on8 口径数字被标为 on9:'
                    'A 2014-15 json=+5,853.92 恰等于 A_on8(on9 权威=+5,120.18,差 2 笔 buy_aux/buy_backup'
                    '正是候选1拦截类型);A 2025长牛 json=+40,496.94 恰等于备份 mine23_compare.json A_on8 '
                    '(on9 权威=+42,688.04);2019-20/2020-21 与 on8/on9 均不完全吻合且生成脚本未落盘无法复现。'
                    '本表(mine24_compare)四牛市一律用 on9 权威口径重算,§15.13 引用时以此为准;'
                    '旧报告 §15.11.4 是否修正待用户确认,本脚本不擅改。'))

    # ---- 大亏月 Top10 汇总行(便于直接成表) ----
    out['worst10_months'] = worst10

    # ---- 九模式 A-I(P0/P1/A/B/C=mine23 on9 口径;NEW/NEW2=叠在该模式 8 默认过滤池上、无候选1,mine24 modes_af 同款) ----
    print('\n== 九模式敏感性(各模式全史总额) ==')
    modes_out = {}
    for m in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']:
        if m == 'A':
            ctx = ctxA; fm = fIdx; rm = rows
        else:
            rm, fm = prep_mode(m); ctx = build_ctx(rm, fm)
        b8 = R.stats_of(ev(ctx, (), False))['total']
        b9 = R.stats_of(ev(ctx, (), True))['total']
        line = {}
        for nm, sub in [('A', A_SUB), ('B', B_SUB), ('C', C_SUB)]:
            line[nm] = dict(total=round(R.stats_of(ev(ctx, sub, True))['total'], 2))
        # NEW/NEW2 在该模式: prep_mode 行=该模式 8 默认过滤后的池;blk 仅 NEW 键命中(无候选1),mine24 modes_af 同款
        R.init(rm, fm)
        rl = build_rules(feats, fm); rl.update(build_r2(fm))
        hk = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
        md_, ed_, rd_ = len(fm), len(fm) + 1, len(fm) + 2
        for tag, keys in [('NEW', NEW_KEYS), ('NEW2', NEW2_KEYS)]:
            blk = set()
            for c in keys:
                if c in hk:
                    f = {kk2: False for kk2 in DEFAULT_FILTERS}; f[c] = True
                    blk |= {R.base_key(t, fm) for t in rm if not passes_fade(t, fm, f, active_month_mask(f), md_, ed_, rd_)}
                else:
                    blk |= {R.base_key(t, fm) for t in rm if rl[c](t)}
            gm = {}
            for t in rm:
                gm.setdefault(str(t[0]), []).append((R.base_key(t, fm), t))
            for sd in gm: gm[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
            osel = []
            for sd in sorted(gm):
                n = 0
                for key, t in gm[sd]:
                    if key not in blk:
                        osel.append(t); n += 1
                        if n >= 1: break
            line[tag] = dict(total=round(R.stats_of(osel)['total'], 2), improve_vs_mode8=round(R.stats_of(osel)['total'] - b8, 2))
        modes_out[m] = dict(base8=round(b8, 2), base9=round(b9, 2),
                            **{k: (v if isinstance(v, dict) else v) for k, v in line.items()})
        print(f"  mode {m}: 8键={b8:+,.0f} 9键={b9:+,.0f} | A={line['A']['total']:+,.0f} B={line['B']['total']:+,.0f} C={line['C']['total']:+,.0f} NEW={line['NEW']['total']:+,.0f}(vs模式8键{line['NEW']['improve_vs_mode8']:+,.0f}) NEW2={line['NEW2']['total']:+,.0f}")
    out['modes'] = modes_out
    # ---- mine24 robust.modes_af 口径审计与断言 ----
    # 审计结论: mine24_global_search.py L235 b8sel=[t for t in rm if not passes_fade(...)] 取的是
    # 「被拦行」,而 rm 已是 8 默认过滤后的池(幂等) -> b8sel=空集 -> b8tot=0 ->
    # robust.modes_af[md_] = NEW 组合在该模式池的 top1 绝对总额(并非「vs 各模式 8键」增量)。
    # 断言: 本脚本 NEW 各模式绝对额 == robust.modes_af(逐位复现其数字并澄清含义)。
    rb14 = M24['robust']['+'.join(NEW_KEYS)]
    af_check = {}
    for md_ in ['B', 'C', 'D', 'E', 'F']:
        got_abs = modes_out[md_]['NEW']['total']
        assert abs(got_abs - rb14['modes_af'][md_]) < 1.0, (md_, got_abs, rb14['modes_af'][md_])
        af_check[md_] = dict(new_absolute_total=got_abs,
                             true_improve_vs_mode8_top1=modes_out[md_]['NEW']['improve_vs_mode8'],
                             mine24_labeled_vs_mode8=rb14['modes_af'][md_])
    print('NEW 跨模式 B-F 断言 PASS: mine24 robust.modes_af 数字=NEW 各模式绝对总额(b8tot 空集致减数为 0),真实增量见 true_improve_vs_mode8')
    out['modes_af_audit'] = dict(
        detail=af_check,
        conclusion=('mine24 §15.12.4「跨模式 B-F(vs 各模式 8键)」列的数字实为 NEW 组合在该模式池的'
                    'top1 绝对总额(mine24_global_search.py b8sel 误取被拦空集致 b8tot=0);'
                    '真实增量(vs 该模式 8 键 top1 基线)为 B +43,776/C +52,178/D +48,243/E +48,738/F +46,544,'
                    '方向仍全正,原「✅ 全正」结论不变,但数值含义需按本审计澄清。旧报告是否修正待用户确认。'))

    # ---- NEW 家族 8 解入选笔集合级等价核实 ----
    print('\n== 支配 A 的 8 解等价核实(入选笔 base_key 集合 vs NEW14) ==')
    fam = []
    ref = sel_keyset(NEW)
    for i, d in enumerate(DOMS):
        s = ev_new(d['keys'])
        ks = sel_keyset(s)
        same = ks == ref
        fam.append(dict(idx=i, n_keys=len(d['keys']), net=d['net'], mdd=d['mdd'],
                        same_selection_as_NEW=same,
                        diff_n=len(ks ^ ref)))
        print(f"  #{i} 键{len(d['keys']):2d} net={d['net']:+,.2f} mdd={d['mdd']:,.2f} 入选集合与NEW14相同={same} 差异笔数={len(ks ^ ref)}")
    out['dominators_equivalence_check'] = fam

    out['note'] = ('口径诚实标注: '
                   '①全程补位口径(mode 分组内剔除命中→按 track_score/rating/signal/buy_date 排序取 top-K→组内非空才成交,K1 默认);'
                   '②P0/P1/A/B/C 为叠加口径(8 或 8+1 键先过滤,A/B/C 组合 OR 叠加其上,on9=叠在 8+1 上);'
                   '③NEW/NEW2 为重构口径(mode A 全池出发,黑名单=仅 NEW 14/18 键自身命中,不预设 8 默认键在场——'
                   '故其与 P0/P1 的对照是「整套换装」而非「在原基础上叠加」,mine24 §15.12 已声明);'
                   '④九模式表中 NEW/NEW2 为叠在该模式 8 默认过滤池上(无候选1),与 mine24 robust.modes_af 同款,modes A-F 断言一致;'
                   '⑤G/H/I 长线模式豁免口径沿用 §15.11.8 标注;'
                   '⑥数据版本 signal_kelly_trades generated_at=' + str(tr.get('generated_at')) +
                   '(较 mine23/mine24 跑时更新;P0/P1/A/B/C/NEW/NEW2 全部锚点在新版逐位复现才继续);'
                   '⑦空仓信号日=vs P0(8键基座)被清零的 signal_date 日数;峰值持仓=当日并发持仓峰值(先删后加);'
                   '⑧回撤按 sell_date 日聚合 cum pnl 计算谷日/恢复日。')
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
