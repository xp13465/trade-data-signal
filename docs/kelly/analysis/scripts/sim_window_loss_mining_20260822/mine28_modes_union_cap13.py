# -*- coding: utf-8 -*-
"""mine28 「NEW14∪8键」并集组合逐模式拆解(A-I × V2回补躺平 + cap13)(2026-08-23 主控追加问②)。
目的:
  验证「躺平实质最优组合=NEW14∪8键(+142,390/mdd -6,622)」这一 G 模式结论是否跨交易模式成立:
  A-I 九模式 × 4 变体(RAW无过滤 / P0_8键 / NEW14单用 / NEW14叠8键)× V2回补 + cap13(13万档)
  → 净利/最大回撤/年操作次数/近1年,看并集优势跨模式成立性、在哪些模式反转。
方法口径:
  - 机具/重放层/统计层全部复用 mine27(finish_pool/replay3/stats_ext),引擎=mine25(sim_core 口径
    K1 补位、每笔固定本金 PRIN=10000,E23:K=1 时每笔1万 ≡ 每日池等分);
  - 「NEW14∪8键」实现=两段式(hist 层并集 passes_fade 8默认键 + NEW14 黑名单 hits_on),
    单调合取下数学等价于键集并集;
  - 跨度/近1年切点沿用 mine27 meta(span_years/near1y_cutoff),保证同口径可比;
  - G 模式行同时作跨脚本自检锚点:RAW cap13V2 与 NEW14叠8键 cap13V2 必须咬合 mine27 内联补算值。
交叉断言(必过才往下):
  每模式 no-cap:P0_8键 == mine24_compare.modes[m].base8;NEW14叠8键 == modes[m].NEW(<0.5);
  G 模式 cap13V2:RAW==+109,828 / NEW14单用==+139,891 / NEW14叠8键==+142,390(mine27 已算,<1)。
输出:data/mine28_modes_union_cap13_v2.json
复现:python3 mine28_modes_union_cap13.py
依赖:static-site/data/signal_kelly_trades.json + data/mine10_features.json + data/mine24_compare.json +
     data/mine27_g_exhaustive_simplified.json(仅读 meta 同口径+G 锚点)。
关键口径一句话:A-I 各自模式池 × 4 过滤变体 × V2 回补(满仓跳过/自然卖出释放后再买)× 并发上限 13 笔
              (=13 万档,K1 补位)→ 已实现+未实现合计净利/mdd/年操作/近1年窗。
"""
import os, sys, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import r2_common as R
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, PRIN, base_key
from mine21_bigtour import build_rules
from mine22_joint import build_r2
import mine25_longline_operable as M25
import mine27_g_exhaustive_simplified as M27

OUT_PATH = os.path.join(BASE, 'data', 'mine28_modes_union_cap13_v2.json')
MODES = list('ABCDEFGHI')
VARIANTS = ['RAW无过滤', 'P0_8键', 'NEW14单用', 'NEW14叠8键']
CAP = 13
# mine27 内联补算的 G cap13 V2 值(跨脚本咬合锚点)
G_ANCHOR = {'RAW无过滤': 109828.00, 'P0_8键': 125542.00, 'NEW14单用': 139891.00, 'NEW14叠8键': 142390.00}


def main():
    tr, fIdx = load(os.path.join(R._ROOT, 'static-site/data/signal_kelly_trades.json'))
    m27 = json.load(open(M27.OUT_PATH))['meta']
    span_years, near_cut = m27['span_years'], m27['near1y_cutoff']
    rl = build_rules(M27.FEATS, fIdx); rl.update(build_r2(fIdx))
    mm = active_month_mask(DEFAULT_FILTERS)
    mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2

    runs, xcheck, overlaps = {}, {}, {}
    for mo in MODES:
        pool_raw = M27.finish_pool(build_mode_pool(tr, fIdx, mo), fIdx)
        kept = [t for t in build_mode_pool(tr, fIdx, mo)
                if passes_fade(t, fIdx, DEFAULT_FILTERS, mm, mD, eD, rD)]
        pool_8 = M27.finish_pool(kept, fIdx)
        R.init(pool_raw, fIdx)
        hits_raw = M25.hits_on(pool_raw, fIdx, M27.NEW14_KEYS, rl)
        R.init(pool_8, fIdx)
        hits_8 = M25.hits_on(pool_8, fIdx, M27.NEW14_KEYS, rl)
        ctx8 = M25.build_ctx(pool_8, fIdx)
        sels = {
            'RAW无过滤': M25.ev_new_on(pool_raw, fIdx, set()),
            'P0_8键': M25.ev(ctx8, (), False),
            'NEW14单用': M25.ev_new_on(pool_raw, fIdx, hits_raw),
            'NEW14叠8键': M25.ev_new_on(pool_8, fIdx, hits_8),
        }
        # ---- no-cap 交叉断言(mine24_compare 权威)----
        auth = M27.M24CMP['modes'][mo]
        xc = {}
        for vj, ak in [('P0_8键', 'base8'), ('NEW14叠8键', 'NEW')]:
            R.init(sels[vj], fIdx)
            tot = round(R.stats_of(sels[vj])['total'], 2)
            av = auth[ak] if isinstance(auth[ak], (int, float)) else auth[ak]['total']
            ok = abs(tot - av) < 0.5
            xc[vj] = dict(no_cap_total=tot, authoritative=av, match=ok)
            assert ok, (mo, vj, tot, av)
        xcheck[mo] = xc

        # ---- 拦截集重叠度(机制证据: 8键整体被拦集 vs NEW14 黑名单)----
        blk8 = {base_key(t, fIdx) for t in pool_raw
                if not passes_fade(t, fIdx, DEFAULT_FILTERS, mm, mD, eD, rD)}
        inter, uni = len(blk8 & hits_raw), len(blk8 | hits_raw)
        overlaps[mo] = dict(pool_n=len(pool_raw), blk8_n=len(blk8), blk14_n=len(hits_raw),
                            inter_n=inter, union_n=uni,
                            jaccard=round(inter / uni, 3) if uni else None,
                            new14_only_n=len(hits_raw - blk8), blk8_only_n=len(blk8 - hits_raw))

        # ---- cap13 V2 回补重放 ----
        runs[mo] = {}
        for vj in VARIANTS:
            sel = sels[vj]
            R.init(sel, fIdx)
            day_sel = {str(t[0]): t for t in sel}
            rp = M27.replay3(day_sel, fIdx, CAP, 'v2回补极简')
            st = M27.stats_ext(rp, fIdx, CAP, CAP * PRIN, span_years, near_cut)
            runs[mo][vj] = st
            if mo == 'G':
                got, exp = st['total_merged'], G_ANCHOR[vj]
                assert abs(got - exp) < 1.0, ('G anchor', vj, got, exp)

    # ---- 汇总表 ----
    print('mode | ' + ' | '.join('%s:净利/mdd/年op/近1年' % v for v in VARIANTS))
    for mo in MODES:
        cells = []
        for vj in VARIANTS:
            s = runs[mo][vj]
            cells.append('%+.0f/%.0f/%.1f/%+.0f' % (s['total_merged'], s['mdd_merged_terminal']['mdd'],
                                                    s['ops_per_year'], s['near1y']['total_merged']))
        print(mo + ' | ' + ' | '.join(cells))

    out = dict(
        meta=dict(
            title='NEW14∪8键 并集组合逐模式拆解(A-I × V2回补 + cap13)',
            date='2026-08-23', cap=CAP, method='v2回补极简', prin_yuan=PRIN,
            budget_yuan=CAP * PRIN, span_years=span_years, near1y_cutoff=near_cut,
            variants=VARIANTS, union_def='两段式=hist层并集(passes_fade 8默认键)+NEW14黑名单(hits_on),单调合取≡键集并集',
            data_generated_at=tr.get('generated_at'),
            deps=['static-site/data/signal_kelly_trades.json', 'data/mine10_features.json',
                  'data/mine24_compare.json', 'data/mine27_g_exhaustive_simplified.json'],
            repro='python3 mine28_modes_union_cap13.py',
        ),
        xcheck_no_cap=xcheck,
        block_overlap=overlaps,
        runs=runs,
    )
    with open(OUT_PATH, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('saved ->', OUT_PATH)


if __name__ == '__main__':
    main()
