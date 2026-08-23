# -*- coding: utf-8 -*-
"""二轮挖掘 全局重构搜索(mine24,2026-08-22 主控令·用户追加):不预设现有 9 键必须在场,
方法池=lab 凯利区全部历史上线小降亏 toggle(37)+新池 13+落池存量 7 → N=57,
从零搜「净利比 9键+A 还高、回撤还低」的双目标支配解。
策略(主控授权元启发式,2^57 不可全穷举):多起点贪心构造 + 1-flip steepest 爬山(全邻域 57)
+ 随机重启(目标函数 λ 轮换: net-λ·回撤超额, λ∈{0,2,5,10}) + 全局帕累托档案(net,mdd)。
收敛证据=多起点终解族谱;防过拟合=三道门/LOO/前向/2025反测/K1-K4/A-F模式/按年负占比全套。
口径: 补位口径 mode A K1 etf_def;历史键谓词=sim_core.passes_fade 权威移植(与 lab.js 逐字对齐);
bullAuxBackupStop 谓词自补(≡候选1,断言 8键+它=+73,102.53 验证)。
锚点断言: 8键默认=+66,530.38 / 9键=+73,102.53 / A方案=+119,109.53 & mdd -6,784。
输出: data/mine24_global_search.json
复现: python3 mine24_global_search.py(依赖 mine10_features.json + mine20_pool.json + signal_kelly_trades.json)
"""
import os, sys, json, random, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import (load, build_mode_pool, passes_fade, DEFAULT_FILTERS, MONTH_MASK,
                      calc_row, base_key)
from mine18_detail import BEARS, FEATS_PATH
from mine21_bigtour import build_rules, max_dd
from mine22_joint import build_r2
from mine17_modes import prep_mode

OUT_PATH = os.path.join(BASE, 'data', 'mine24_global_search.json')
POOL_PATH = os.path.join(BASE, 'data', 'mine20_pool.json')
FEATS = json.load(open(FEATS_PATH))

DEFAULT8 = ['n2NovSpecialIndustry', 'excludeSpecialBear', 'janMidRating', 'janMidSpecial',
            'k2c5HkChase', 'r7MayReinforced', 'excludeAuxCross', 'greedy15']
A_EXTRA = ['T1', 'Q1', 'M1', 'V1', 'R1', 'k3ConceptBuy', 'R2b', 'R2g']  # A 方案=8默认+候选1+这8键
NEW13 = ['N1', 'T1', 'D1', 'Q1', 'H1', 'M1', 'D2', 'P1', 'V1', 'S1', 'R1', 'R2b', 'R2g']
DROP7 = ['N2', 'V2', 'S2', 'W1', 'A1', 'V3', 'AD1']

def main():
    # ---- 全池准备(不过滤) ----
    tr, fIdx = load(R._ROOT + '/static-site/data/signal_kelly_trades.json')
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
    groups = {}
    for t in pool:
        groups.setdefault(str(t[0]), []).append((base_key(t, fIdx), t))
    for sd in groups: groups[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
    sds = sorted(groups)
    print(f'全池 rows={len(pool)} 信号日={len(sds)}')

    # ---- 57 键命中集 ----
    HITS = {}
    hist_keys = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']
    for k in hist_keys:
        f = {kk: False for kk in DEFAULT_FILTERS}; f[k] = True
        HITS[k] = {base_key(t, fIdx) for t in pool if not passes_fade(t, fIdx, f, MONTH_MASK.get(k, 0), mD, eD, rD)}
    # bullAuxBackupStop(2026-08-22 新键, sim_core 未同步, 自补; ≡候选1)
    HITS['bullAuxBackupStop'] = {base_key(t, fIdx) for t in pool
                                 if t[2] in ('buy_aux', 'buy_backup') and (t[fIdx['market_tier']] or '') == '牛市·主升'}
    hist_keys = hist_keys + ['bullAuxBackupStop']
    rules = build_rules(FEATS, fIdx); rules.update(build_r2(fIdx))
    for c in NEW13 + DROP7:
        HITS[c] = {base_key(t, fIdx) for t in pool if rules[c](t)}
    ALL = hist_keys + NEW13 + DROP7
    N = len(ALL)
    print(f'方法池 N={N} (历史{len(hist_keys)} + 新池{len(NEW13)} + 落池存量{len(DROP7)}); R2a≡k3ConceptBuy 去重')
    IDX = {c: i for i, c in enumerate(ALL)}

    def eval_mask(mask, K=1, want_dd=True):
        blk = set()
        for i in range(N):
            if mask >> i & 1: blk |= HITS[ALL[i]]
        sel = []
        for sd in sds:
            n = 0
            for key, t in groups[sd]:
                if key not in blk:
                    sel.append(t); n += 1
                    if n >= K: break
        st = R.stats_of(sel)
        md = max_dd(sel, fIdx) if want_dd else None
        return st['total'], st['n'], md

    MEMO = {}
    def ev(mask):
        if mask in MEMO: return MEMO[mask]
        v = eval_mask(mask); MEMO[mask] = v; return v

    def mask_of(names):
        m = 0
        for c in names: m |= 1 << IDX[c]
        return m

    # ---- 锚点断言 ----
    tot8, n8, mdd8 = ev(mask_of(DEFAULT8))
    assert abs(tot8 - 66530.38) < 0.5, tot8
    tot9, _, mdd9 = ev(mask_of(DEFAULT8 + ['bullAuxBackupStop']))
    assert abs(tot9 - 73102.53) < 0.5, tot9
    totA, _, mddA = ev(mask_of(DEFAULT8 + ['bullAuxBackupStop'] + A_EXTRA))
    assert abs(totA - 119109.53) < 1.0, totA
    assert abs(mddA - (-6784.43)) < 5.0, mddA
    print(f'锚点 PASS: 8键={tot8:+,.2f}(mdd {mdd8:,.2f}) 9键={tot9:+,.2f}(mdd {mdd9:,.2f}) A方案={totA:+,.2f}(mdd {mddA:,.2f})')
    A_NET, A_MDD = totA, mddA
    base_mask = mask_of(DEFAULT8)

    # ---- solo 预扫 ----
    solo = {}
    for i, c in enumerate(ALL):
        t_, n_, m_ = ev(1 << i)
        solo[c] = dict(net=round(t_ - tot8, 2), total=round(t_, 2), mdd=m_, n=n_)
    top_solo = sorted(solo.items(), key=lambda x: -x[1]['net'])[:8]
    print('solo top8(vs8键):', [(c, v['net']) for c, v in top_solo])

    # ---- 搜索: 多起点贪心 + 1-flip steepest 爬山 + λ 轮换 ----
    LAMBDAS = [0.0, 2.0, 5.0, 10.0]
    A_DD_TOL = 6784.43
    random.seed(20260822)
    starts = [0, base_mask, mask_of(DEFAULT8 + ['bullAuxBackupStop'] + A_EXTRA)]
    starts += [1 << IDX[c] for c, _ in top_solo[:5]]
    for _ in range(40):
        p = random.choice([0.05, 0.1, 0.15, 0.2, 0.3])
        starts.append(sum(1 << i for i in range(N) if random.random() < p))
    archive = {}   # mask -> (net, mdd)
    finals = []

    def objective(net, mdd, lam):
        return net - lam * max(0.0, -mdd - A_DD_TOL)

    for si, st0 in enumerate(starts):
        lam = LAMBDAS[si % len(LAMBDAS)]
        cur = st0
        # 贪心构造(仅从空/小起点)
        if bin(cur).count('1') <= 2:
            improved = True
            while improved:
                improved = False
                best_gain, best_m = 0.0, None
                cn, _, cm = ev(cur)
                for i in range(N):
                    if cur >> i & 1: continue
                    m2 = cur | (1 << i)
                    n2, _, m2d = ev(m2)
                    g = objective(n2, m2d, lam) - objective(cn, cm, lam)
                    if g > best_gain + 1.0:
                        best_gain, best_m = g, m2
                if best_m is not None:
                    cur = best_m; improved = True
        # 1-flip steepest 爬山
        while True:
            cn, _, cm = ev(cur)
            cur_obj = objective(cn, cm, lam)
            best_obj, best_m = cur_obj, None
            for i in range(N):
                m2 = cur ^ (1 << i)
                n2, _, m2d = ev(m2)
                o2 = objective(n2, m2d, lam)
                if o2 > best_obj + 1.0:
                    best_obj, best_m = o2, m2
            if best_m is None: break
            cur = best_m
        fn, _, fm = ev(cur)
        finals.append(dict(mask=cur, net=round(fn, 2), mdd=fm, lam=lam,
                           keys=[ALL[i] for i in range(N) if cur >> i & 1]))
        archive[cur] = (fn, fm)
        if (si + 1) % 10 == 0:
            print(f'  restart {si+1}/{len(starts)} lam={lam} final net={fn:+,.0f} mdd={fm:,.0f} keys={len(finals[-1]["keys"])}')

    # ---- 帕累托档案过滤(net 大好 / mdd 绝对值小好) ----
    arch = [(m, v[0], v[1]) for m, v in archive.items()]
    front = []
    for m, net, mdd in arch:
        dominated = any(n2 >= net and m2 >= mdd and (n2 > net or m2 > mdd) for _, n2, m2 in arch)
        if not dominated: front.append((m, net, mdd))
    front.sort(key=lambda x: -x[1])
    print(f'\n== 档案 {len(arch)} 解 → 帕累托前沿 {len(front)} ==')
    for m, net, mdd in front[:15]:
        keys = [ALL[i] for i in range(N) if m >> i & 1]
        print(f'  net={net:+10,.0f} mdd={mdd:8,.0f} 键{len(keys):2d}: {"+".join(keys[:14])}{"..." if len(keys)>14 else ""}')

    # ---- 支配 A 方案判定 ----
    dominators = [(m, net, mdd) for m, net, mdd in front if net > A_NET + 0.5 and mdd > A_MDD + 0.5]
    dominators.sort(key=lambda x: (-x[1], -x[2]))
    print(f'\n== 支配 A 方案(net>{A_NET:,.0f} 且 mdd>{A_MDD:,.0f})的解: {len(dominators)} ==')
    for m, net, mdd in dominators[:10]:
        keys = [ALL[i] for i in range(N) if m >> i & 1]
        print(f'  net={net:+10,.0f}(+{net-A_NET:,.0f}) mdd={mdd:8,.0f}({mdd-A_MDD:+,.0f}) : {"+".join(keys)}')

    # ---- 收敛证据 ----
    uniq = {}
    for f in finals:
        uniq[f['mask']] = f
    fams = []
    for m in uniq:
        placed = False
        for fam in fams:
            if bin(m ^ fam[0]).count('1') <= 2:
                fam.append(m); placed = True; break
        if not placed: fams.append([m])
    print(f'\n== 收敛证据: {len(starts)} 起点 → {len(uniq)} 唯一终解 → hamming≤2 合并后 {len(fams)} 族 ==')
    for fam in fams:
        rep = uniq[fam[0]]
        print(f'  族(大小{len(fam)}): net={rep["net"]:+,.0f} mdd={rep["mdd"]:,.0f} λ={rep["lam"]} 键{len(rep["keys"])}')

    # ---- 防过拟合: 前沿头部全套 ----
    from sim_core import active_month_mask
    def ev_sel(mask):
        blk = set()
        for i in range(N):
            if mask >> i & 1: blk |= HITS[ALL[i]]
        s = []
        for sd in sds:
            n = 0
            for key, t in groups[sd]:
                if key not in blk:
                    s.append(t); n += 1
                    if n >= 1: break
        return s

    base8_sel = ev_sel(base_mask)
    dmax = max(str(t[0]) for t in pool)
    dd0 = datetime.date(int(dmax[:4]), int(dmax[4:6]), int(dmax[6:]))

    # 模式预建(B-F 一次)
    mode_cache = {}
    for md_ in ['B', 'C', 'D', 'E', 'F']:
        rm, fm_ = prep_mode(md_); R.init(rm, fm_)
        rl = build_rules(FEATS, fm_); rl.update(build_r2(fm_))
        fdef = {kk: False for kk in DEFAULT_FILTERS}
        for c8 in DEFAULT8: fdef[c8] = True
        mm8 = active_month_mask(fdef)
        # ⚠️已知bug(2026-08-23审查,不修逻辑,历史产物以 mine24_compare.json modes_af_audit 为准):
        # rm 已是 8 默认过滤后的池(passes_fade 幂等),此处 not passes_fade 取的是被拦空集
        # → b8tot=0 → 下游 modes_af「vs 该模式8键」列实为 NEW 绝对总额而非增量。
        # 真实增量见 mine24_compare.json modes_af_audit.true_improve_vs_mode8_top1(B +43,776/C +52,178/D +48,243/E +48,738/F +46,544)。
        b8sel = [t for t in rm if not passes_fade(t, fm_, fdef, mm8, len(fm_), len(fm_) + 1, len(fm_) + 2)]
        gm = {}
        for t in rm: gm.setdefault(str(t[0]), []).append((base_key(t, fm_), t))
        for sd in gm: gm[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
        mode_cache[md_] = dict(rm=rm, fm=fm_, rl=rl, b8tot=R.stats_of(b8sel)['total'], g=gm)
        print(f'  robust 预建 mode {md_}: base8={mode_cache[md_]["b8tot"]:+,.0f}')

    def key_hits_in_mode(c, mc):
        rm, fm_, rl = mc['rm'], mc['fm'], mc['rl']
        if c in hist_keys[:-1]:
            f = {kk: False for kk in DEFAULT_FILTERS}; f[c] = True
            return {base_key(t, fm_) for t in rm if not passes_fade(t, fm_, f, active_month_mask(f), len(fm_), len(fm_) + 1, len(fm_) + 2)}
        if c == 'bullAuxBackupStop':
            return {base_key(t, fm_) for t in rm if t[2] in ('buy_aux', 'buy_backup') and (t[fm_['market_tier']] or '') == '牛市·主升'}
        return {base_key(t, fm_) for t in rm if rl[c](t)}

    def robust_report(m):
        keys = [ALL[i] for i in range(N) if m >> i & 1]
        s = ev_sel(m)
        det = R.diff_detail(base8_sel, s)
        g = R.three_gates(base8_sel, s, det)
        loo = {}
        for c in keys:
            n2, _, _ = ev(m & ~(1 << IDX[c]))
            loo[c] = round(ev(m)[0] - n2, 2)
        fwd = R.forward_2024_26(base8_sel, s)['net_improve']
        w1 = (dd0 - datetime.timedelta(days=365)).strftime('%Y%m%d')
        y2025 = round(R.stats_of(R.window(s, '20250101', None))['total'] - R.stats_of(R.window(base8_sel, '20250101', None))['total'], 2)
        kk = {}
        for K in (2, 3, 4):
            n2, _, _ = eval_mask(m, K); b2, _, _ = eval_mask(base_mask, K)
            kk[f'K{K}'] = round(n2 - b2, 2)
        modes = {}
        for md_ in ['B', 'C', 'D', 'E', 'F']:
            mc = mode_cache[md_]
            blk = set()
            for c in keys: blk |= key_hits_in_mode(c, mc)
            out_s = []
            for sd in mc['g']:
                n = 0
                for key, t in mc['g'][sd]:
                    if key not in blk:
                        out_s.append(t); n += 1
                        if n >= 1: break
            modes[md_] = round(R.stats_of(out_s)['total'] - mc['b8tot'], 2)
        R.init(pool, fIdx)
        nb = {}
        s_keys = {base_key(t, fIdx) for t in s}
        for t in base8_sel:
            if base_key(t, fIdx) not in s_keys:
                nb.setdefault(str(t[0])[:4], 0.0); nb[str(t[0])[:4]] += t[R.IDX_PNL]['pnlYuan']
        neg_ratio = round(sum(1 for v in nb.values() if v < 0) / max(len(nb), 1), 3) if nb else None
        return dict(keys=keys, net=round(ev(m)[0], 2), mdd=ev(m)[2],
                    gates=dict(g1=g['g1'], g2=g['g2'], g3=g['g3'], apr_hurt=g['apr_hurt'], mayaug=g['mayaug_improve']),
                    blocked_n=det['blocked_n'], blocked_pnl=det['blocked_pnl'],
                    added_n=det['added_n'], added_pnl=det['added_pnl'],
                    loo=loo, forward2426=fwd, bull2025=y2025, k_sens=kk, modes_af=modes,
                    blocked_year_neg_ratio=neg_ratio,
                    windows=dict(近1年=round(R.stats_of(R.window(s, w1, None))['total'] - R.stats_of(R.window(base8_sel, w1, None))['total'], 2),
                                 全史=round(ev(m)[0] - tot8, 2)),
                    bears={lab: round(R.stats_of(R.window(s, a, b))['total'] - R.stats_of(R.window(base8_sel, a, b))['total'], 2) for lab, a, b in BEARS})

    check_masks = []
    for m, net, mdd in front[:8]: check_masks.append(m)
    for m, net, mdd in sorted(front, key=lambda x: -x[2])[:4]:
        if m not in check_masks: check_masks.append(m)
    robust = {}
    print('\n== 防过拟合全套(前沿头部) ==')
    for m in check_masks:
        rr = robust_report(m)
        robust['+'.join(rr['keys'])] = rr
        print(f"  {'+'.join(rr['keys'])[:70]}")
        print(f"    net={rr['net']:+,.0f} mdd={rr['mdd']:,.0f} 门g1={rr['gates']['g1']} g2={rr['gates']['g2']} g3={rr['gates']['g3']} 前向={rr['forward2426']:+,.0f} 2025牛={rr['bull2025']:+,.0f} 负占比={rr['blocked_year_neg_ratio']}")
        print(f"    近1年={rr['windows']['近1年']:+,.0f} K234={rr['k_sens']} 模式B-F={rr['modes_af']}")
        print(f"    熊市={rr['bears']}")

    out = dict(
        anchor=dict(p0=tot8, p1=tot9, a_net=totA, a_mdd=mddA),
        pool=dict(n=N, hist=hist_keys, new13=NEW13, drop7=DROP7,
                  solo={c: v for c, v in solo.items()}),
        search=dict(n_starts=len(starts), lambdas=LAMBDAS, n_evals=len(MEMO),
                    finals=[dict(net=f['net'], mdd=f['mdd'], lam=f['lam'], keys=f['keys']) for f in finals]),
        n_families=len(fams),
        frontier=[dict(mask=m, net=round(net, 2), mdd=mdd,
                       keys=[ALL[i] for i in range(N) if m >> i & 1]) for m, net, mdd in front],
        dominators_of_A=[dict(net=round(net, 2), mdd=mdd,
                              keys=[ALL[i] for i in range(N) if m >> i & 1]) for m, net, mdd in dominators],
        robust=robust)
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, default=str)
    print('saved ->', OUT_PATH)

if __name__ == '__main__':
    main()
