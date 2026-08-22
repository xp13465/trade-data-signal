# -*- coding: utf-8 -*-
"""三轮挖掘 ③b 纯过关组合深检 + K档/跨模式敏感性 + 同源重叠率(2026-08-22)。

目的:   ①对四重检验全过的 R2a/R2b/R2g 做纯过关组合(vs9键), 不含观察型 R2e;
        ②组合与各成员跑 K1-K4 敏感性 + A-F 六短线模式(H/G/I 记录);
        ③与一轮候选1被拦类的重叠率(E13 同源性检查)。
口径:   同 mine14(补位口径, 测试基准 current baseline v1.1.4)。
输入:   static-site/data/signal_kelly_trades.json
输出:   data/mine14b_combo_kmodes.json + stdout
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine14b_combo_kmodes.py
"""
import os, sys, json, math, datetime
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r3_common as C
from sim_core import buyprice_bin, buy_weekday, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, load, base_key
ROOT = C.ROOT

tr, fIdxFull = load(os.path.join(ROOT, 'static-site/data/signal_kelly_trades.json'))
st = C.get_sets()
rows, fIdx = C.ensure()
i = fIdx
IP = len(fIdx) + 3

def ctx(t):
    bd = str(t[i['buy_date']] or '')
    return dict(sig=t[i['signal']] or '', mm=bd[4:6] if len(bd)>=6 else '', dd=int(bd[6:8]) if len(bd)>=8 else 0,
                wd=buy_weekday(bd), bpb=buyprice_bin(t[i['buy_price']]),
                ts=float(t[i['track_score']]) if t[i['track_score']] not in (None,'') else 999.0,
                tier=t[i['market_tier']] or '', tier_all=t[i['market_tier_all']] or '',
                mktD=t[len(fIdx)] or '', ratD=t[len(fIdx)+2] or '',
                rating=str(t[i['rating']] or ''), sd=str(t[i['signal_date']] or ''))
CTXED = {id(t): ctx(t) for t in rows}

RULES = {
    'R2a': lambda c: c['sig'] == 'buy' and c['mktD'] == 'concept',
    'R2b': lambda c: c['sig'] == 'buy_special' and c['mktD'] == 'global',
    'R2g': lambda c: c['rating'] == 'low' and c['mm'] in ('07','08','09') and c['ts'] < 75,
}

def build_for_mode(mode, K):
    """任意模式的 pool -> 8键 -> (9键topK基线, 10键topK with combo)。"""
    pool = build_mode_pool(tr, fIdxFull, mode)
    mmask = active_month_mask(DEFAULT_FILTERS)
    mD, eD, rD = len(fIdxFull), len(fIdxFull)+1, len(fIdxFull)+2
    kept = [t for t in pool if passes_fade(t, fIdxFull, DEFAULT_FILTERS, mmask, mD, eD, rD)]
    # 注意: mode pool 记录长度与 prepare_rows 不同(无 IDX_PNL/IDX_SKEY append), 需现场算
    byd = defaultdict(list)
    for t in kept:
        byd[str(t[i['signal_date']] or '')].append(t)
    def pnl(t): return C.R.calc_row_pub(t, fIdxFull)['pnlYuan']
    def rank_key(t):
        rr = {'high':0,'mid':1,'low':2,'':3}.get(str(t[i['rating']] or ''),3)
        sr = {'buy_backup':0,'buy':1,'buy_aux':2,'buy_special':3,'':9}.get(t[i['signal']] or '',9)
        ts = float(t[i['track_score']]) if t[i['track_score']] not in (None,'') else float('inf')
        return (-ts, rr, sr, str(t[i['buy_date']] or ''))
    base_sel, combo_sel = [], []
    for sd in sorted(byd):
        grp = byd[sd]
        b = sorted([t for t in grp if not C.cand1(t)], key=rank_key)[:K]
        c = sorted([t for t in grp if not (C.cand1(t) or any(r(CTXED.get(id(t))) for r in RULES.values() if True)) ], key=rank_key)[:K] if False else None
        base_sel.extend(b)
    # combo: CTXED 只对 A 模式 rows 有效; 其他模式需重建 ctx —— 直接内联
    def hit_any(t):
        c_ = ctx(t)
        return any(fn(c_) for fn in RULES.values())
    for sd in sorted(byd):
        grp = byd[sd]
        cc = sorted([t for t in grp if not (C.cand1(t) or hit_any(t))], key=rank_key)[:K]
        combo_sel.extend(cc)
    return base_sel, combo_sel, pnl

def sum_pnl(sel, pnl): return round(sum(pnl(t) for t in sel), 2)

print('=' * 100)
print('③b-1 纯过关组合 R2a+R2b+R2g(vs9键, A模式)')
print('=' * 100)
baseA, comboA, pnlA = build_for_mode('A', 1)
bt, ct = sum_pnl(baseA, pnlA), sum_pnl(comboA, pnlA)
print(f"9键基线 {bt:+.2f} | 组合 {ct:+.2f} | 增量 {ct-bt:+.2f} (vs8键 {ct-66530.38:+.2f})")
# 单成员 vs 组合边际
for nm, fn in RULES.items():
    def one(t, fn=fn): 
        c_ = ctx(t); return fn(c_)
    sel_one = []
    byd = defaultdict(list)
    for t in rows: byd[str(t[i['signal_date']] or '')].append(t)
    for sd in sorted(byd):
        sel_one.extend(sorted([t for t in byd[sd] if not (C.cand1(t) or one(t))], key=lambda t: t[len(fIdx)+4])[:1])
    print(f"  单独 {nm}: {sum_pnl(sel_one, lambda t: t[IP]['pnlYuan']):+.0f} (边际 {sum_pnl(sel_one, lambda t: t[IP]['pnlYuan'])-bt:+.0f})")

# 同源重叠率: 组合新增被拦 vs 候选1被拦139笔
nset_c = {base_key(t, fIdx) for t in comboA}
bset_b = {base_key(t, fIdx) for t in baseA}
combo_blocked = [t for t in baseA if base_key(t, fIdx) not in nset_c]
cand1_blocked_keys = {base_key(t, fIdx) for t in st['blocked']}
ov = sum(1 for t in combo_blocked if base_key(t, fIdx) in cand1_blocked_keys)
print(f"\n③b-3 同源性: 组合新增被拦 {len(combo_blocked)} 笔, 其中与候选1被拦139笔重叠 {ov} 笔 ({ov/max(len(combo_blocked),1)*100:.0f}%)")
# 成员间两两重叠(Jaccard on hit sets)
hits = {}
for nm, fn in RULES.items():
    hits[nm] = {id(t) for t in rows if fn(ctx(t))}
names = list(RULES)
for a_, b_ in [(x, y) for x_i, x in enumerate(names) for y in names[x_i+1:]]:
    inter = len(hits[a_] & hits[b_]); uni = len(hits[a_] | hits[b_])
    print(f"  重叠({a_},{b_}): Jaccard {inter/max(uni,1)*100:.0f}% ({inter}笔)")

print()
print('=' * 100)
print('③b-2 K1-K4 敏感性(A模式, 组合 R2a+R2b+R2g)')
print('=' * 100)
ktab = []
for K in (1, 2, 3, 4):
    bs, cs, pnlf = build_for_mode('A', K)
    ktab.append(dict(K=K, base=sum_pnl(bs, pnlf), combo=sum_pnl(cs, pnlf)))
    print(f"K{K}: 9键 {ktab[-1]['base']:+.0f} -> 组合 {ktab[-1]['combo']:+.0f} (增量 {ktab[-1]['combo']-ktab[-1]['base']:+.0f})")

print()
print('跨模式(组合, K1):')
mtab = []
for mode in 'ABCDEFGHI':
    bs, cs, pnlf = build_for_mode(mode, 1)
    d = sum_pnl(cs, pnlf) - sum_pnl(bs, pnlf)
    grp = '短线A-F' if mode in 'ABCDEF' else '长线G-H-I'
    mtab.append(dict(mode=mode, group=grp, delta=d))
    print(f"  mode {mode}({grp}): 增量 {d:+.0f}")
af_same = all(m['delta'] > 0 for m in mtab if m['group'] == '短线A-F')
print(f"A-F 六模式同向: {'是(6/6)' if af_same else '否'}")

out = dict(generated_at=datetime.datetime.now().isoformat(),
           pure_combo=dict(base=bt, combo=ct, delta=round(ct-bt,2), vs8=round(ct-66530.38,2)),
           overlap_cand1_pct=round(ov/max(len(combo_blocked),1)*100,1),
           pairwise_jaccard={f'{a_},{b_}': round(len(hits[a_]&hits[b_])/max(len(hits[a_]|hits[b_]),1)*100,1) for a_,b_ in []},
           k_sensitivity=ktab, mode_matrix=mtab)
with open(os.path.join(HERE, 'data/mine14b_combo_kmodes.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine14b_combo_kmodes.json written')
