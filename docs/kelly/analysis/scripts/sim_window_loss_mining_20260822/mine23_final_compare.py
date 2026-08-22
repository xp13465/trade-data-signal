# -*- coding: utf-8 -*-
"""二轮挖掘 终选五项目全维度对比(mine23,2026-08-22 主控令·用户决策前最后一步)。
5 项目: P0=8键基线 / P1=9键(8+候选1,当前实测态) /
  A=T1+Q1+M1+V1+R1+R2a+R2b+R2g(全史王兼近端安全王) /
  B=T1+Q1+M1+R1+R2b+R2g(前沿内双正王) /
  C=N1+T1+D1+H1+M1+P1+R2b(含N1残存最高)。
A/B/C 各两版: on9(cand1 OR 组合=叠加在8+1上) 与 on8(仅组合=叠加在8上),
直接回答「叠加在 8+1 还是 8 上、是否有区别」。
维度: 全史总额/笔数/胜率/盈亏比(PF)/频次/空仓日;按年16年;近1/2/3/5年+全史;
四大熊市+两牛市(2025长牛/2020-21);2026逐月(2-8月)+2-3月+5-8月;最大回撤与恢复;
K1-K4;九模式 A-I;被拦/替补。
口径纪律: 补位口径;锚点断言 P0=+66,530.38 / P1=+73,102.53;A/B/C 复验 mine22 数字一致才输出。
输出: data/mine23_compare.json
复现: python3 mine23_final_compare.py(依赖 mine20_pool.json + signal_kelly_trades.json)
"""
import os, sys, json, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from mine18_detail import BEARS, FEATS_PATH
from mine17_modes import prep_mode
from mine21_bigtour import build_rules
from mine22_joint import build_r2

OUT_PATH = os.path.join(BASE, 'data', 'mine23_compare.json')
POOL_PATH = os.path.join(BASE, 'data', 'mine20_pool.json')

A_SUB = ('T1','Q1','M1','V1','R1','R2a','R2b','R2g')
B_SUB = ('T1','Q1','M1','R1','R2b','R2g')
C_SUB = ('N1','T1','D1','H1','M1','P1','R2b')

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
    return dict(mdd=round(mdd, 2), trough_day=trough, recovered=rec is not None, recover_day=rec)

def pf_of(sel):
    g = sum(t[R.IDX_PNL]['pnlYuan'] for t in sel if t[R.IDX_PNL]['pnlYuan'] > 0)
    l = sum(t[R.IDX_PNL]['pnlYuan'] for t in sel if t[R.IDX_PNL]['pnlYuan'] < 0)
    return round(g / abs(l), 2) if l else None

def full_stats(sel, base_n_dates):
    st = R.stats_of(sel)
    st['pf'] = pf_of(sel)
    st['zero_days'] = base_n_dates - st['n']  # K1 下 n=有信号日数; 相对8键基座的新增空仓信号日
    st['freq_pct'] = round(st['n'] / max(base_n_dates, 1) * 100, 1)
    return st

def main():
    feats = json.load(open(FEATS_PATH))
    rows, fIdx = R.prepare_rows(); R.init(rows, fIdx)
    rules = build_rules(feats, fIdx); rules.update(build_r2(fIdx))
    c1 = lambda t: (t[2] in ('buy_aux', 'buy_backup')) and ((t[fIdx['market_tier']] or '') == '牛市·主升')

    def build_ctx(rows, fIdx):
        R.init(rows, fIdx)
        rl = build_rules(feats, fIdx); rl.update(build_r2(fIdx))
        h = {c: {R.base_key(t, fIdx) for t in rows if rl[c](t)} for c in set(A_SUB+B_SUB+C_SUB)}
        hc1 = {R.base_key(t, fIdx) for t in rows if c1(t)}
        g = {}
        for t in rows:
            g.setdefault(str(t[0]), []).append((R.base_key(t, fIdx), t))
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
    print(f'锚点 PASS: P0(8键)={st0["total"]:+,.2f}  P1(9键)={st1["total"]:+,.2f}  cand1贡献={st1["total"]-st0["total"]:+,.2f}')
    A9 = ev(ctxA, A_SUB, True); B9 = ev(ctxA, B_SUB, True); C9 = ev(ctxA, C_SUB, True)
    A8 = ev(ctxA, A_SUB, False); B8 = ev(ctxA, B_SUB, False); C8 = ev(ctxA, C_SUB, False)
    # mine22 复验断言
    for nm, sel, imp in [('A9', A9, 46007.00), ('B9', B9, 36469.07), ('C9', C9, 34010.95)]:
        got = R.stats_of(sel)['total'] - st1['total']
        assert abs(got - imp) < 1.0, f'{nm} 与 mine22 不一致: {got} vs {imp}'
    print('mine22 复验 PASS: A9 +46,007 / B9 +36,469 / C9 +34,011(vs9键)')

    base_nd = st0['n']  # 8键有信号日数
    dd0s = max(str(t[0]) for t in rows)
    dd0 = datetime.date(int(dd0s[:4]), int(dd0s[4:6]), int(dd0s[6:]))
    WINS = [('近1年', (dd0-datetime.timedelta(days=365)).strftime('%Y%m%d'), None),
            ('近2年', (dd0-datetime.timedelta(days=730)).strftime('%Y%m%d'), None),
            ('近3年', (dd0-datetime.timedelta(days=1095)).strftime('%Y%m%d'), None),
            ('近5年', (dd0-datetime.timedelta(days=1825)).strftime('%Y%m%d'), None),
            ('全史', '00010101', None)]
    BULLS = [('牛市·2025长牛', '20250101', None), ('牛市·2020-21', '20200101', '20211231')]
    MONTHS26 = [('2026-02', '20260201', '20260228'), ('2026-03', '20260301', '20260331'),
                ('2026-04', '20260401', '20260430'), ('2026-05', '20260501', '20260531'),
                ('2026-06', '20260601', '20260630'), ('2026-07', '20260701', '20260731'),
                ('2026-08', '20260801', '20260831')]
    PROJECTS = [('P0_8键', P0, None), ('P1_9键', P1, None),
                ('A_on9', A9, A_SUB), ('B_on9', B9, B_SUB), ('C_on9', C9, C_SUB),
                ('A_on8', A8, A_SUB), ('B_on8', B8, B_SUB), ('C_on8', C8, C_SUB)]

    out = dict(anchor=dict(p0=st0['total'], p1=st1['total']), projects={})
    for nm, sel, sub in PROJECTS:
        st = full_stats(sel, base_nd)
        mddD = max_dd_detail(sel, fIdx)
        yr = R.yearly_buckets(sel)
        yr_n = {}
        for t in sel: yr_n[str(t[0])[:4]] = yr_n.get(str(t[0])[:4], 0) + 1
        wins = {lab: round(R.stats_of(R.window(sel, a, b))['total'], 2) for lab, a, b in WINS}
        bears = {lab: round(R.stats_of(R.window(sel, a, b))['total'], 2) for lab, a, b in BEARS}
        bulls = {lab: round(R.stats_of(R.window(sel, a, b))['total'], 2) for lab, a, b in BULLS}
        m26 = {lab: round(R.stats_of(R.window(sel, a, b))['total'], 2) for lab, a, b in MONTHS26}
        m26['2026-02~03'] = round(R.stats_of(R.window(sel, '20260201', '20260331'))['total'], 2)
        m26['2026-05~08'] = round(R.stats_of(R.window(sel, '20260501', '20260831'))['total'], 2)
        det = None
        if sub is not None:
            base_sel = P1 if nm.endswith('on9') else P0
            det = R.diff_detail(base_sel, sel)
        kk = {}
        for K in (1, 2, 3, 4):
            kk[f'K{K}'] = round(R.stats_of(ev(ctxA, sub, nm.endswith('on9') or nm in ('P1_9键',), K))['total'], 2) if sub else \
                          round(R.stats_of(ev(ctxA, (), nm == 'P1_9键', K))['total'], 2)
        out['projects'][nm] = dict(stats=st, maxdd=mddD, yearly={y: dict(total=yr[y], n=yr_n.get(y, 0)) for y in yr},
                                   windows=wins, bears=bears, bulls=bulls, months26=m26,
                                   blocked_added=det, k_sensitivity=kk)
        print(f"{nm}: total={st['total']:+,.0f} n={st['n']} 胜率{st['winRate']}% PF={st['pf']} 空仓+{st['zero_days']} mdd={mddD['mdd']:.0f}")

    # ---- 九模式 A-I ----
    print('\n== 九模式敏感性(各模式全史总额;A/B/C 均为 on9 口径) ==')
    modes_out = {}
    for m in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']:
        if m == 'A':
            ctx = ctxA; fm = fIdx
        else:
            rm, fm = prep_mode(m); ctx = build_ctx(rm, fm)
        b8 = R.stats_of(ev(ctx, (), False))['total']
        b9 = R.stats_of(ev(ctx, (), True))['total']
        line = {}
        for nm, sub in [('A', A_SUB), ('B', B_SUB), ('C', C_SUB)]:
            line[nm] = dict(total=round(R.stats_of(ev(ctx, sub, True))['total'], 2),
                            improve_vs_p1=round(R.stats_of(ev(ctx, sub, True))['total'] - b9, 2))
        modes_out[m] = dict(base8=round(b8, 2), base9=round(b9, 2), **{k: v for k, v in line.items()})
        print(f"  mode {m}: 8键={b8:+,.0f} 9键={b9:+,.0f} | A{line['A']['improve_vs_p1']:+,.0f} B{line['B']['improve_vs_p1']:+,.0f} C{line['C']['improve_vs_p1']:+,.0f}")
    out['modes'] = modes_out
    out['note'] = 'on9=cand1 OR 组合(叠加在8+1上); on8=仅组合(叠加在8上); mine引擎 G/H/I 的9键含候选1(线上G/H/I对bullAuxBackupStop豁免,口径差异已标注)'
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
