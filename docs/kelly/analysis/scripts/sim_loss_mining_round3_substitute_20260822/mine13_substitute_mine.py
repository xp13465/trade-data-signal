# -*- coding: utf-8 -*-
"""三轮挖掘 ②替补亏损子群穷举(2026-08-22)。

目的:   找「替补中亏损子群」的稳定特征规则 R2——在 9 键(8键+候选1)之上叠加,补位口径评估。
方法:   A. 结构化候选优先(S1 候选1全域版 tier_all / S2 k2c5扩sig至aux / S3 global域special /
           S4 buy×concept=k3ConceptBuy现成键 / S5 rating=low全停(excludeRatingLow) 及其变体);
        B. 通用穷举:原子谓词单维 + 二维 + 三维合取(top二维种子),vs9键增量排序。
口径:   补位口径(memory filter-backtest-position-fill-caliber):组内剔(CAND1 ∪ R2) → topK(K=1)。
        测试基准=current baseline(v1.1.4 弹窗口径 mode A+8键+K1+etf_def);9键基线全史=+73,102.53。
输入:   static-site/data/signal_kelly_trades.json
输出:   data/mine13_substitute_mine.json(structured + brute 结果全量)
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine13_substitute_mine.py
"""
import os, sys, json, math, datetime, itertools
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r3_common as C
from sim_core import buyprice_bin, buy_weekday

st = C.get_sets()
rows, fIdx = C.ensure()
i = fIdx
IP = len(fIdx) + 3          # r2_common IDX_PNL
BYDATE = defaultdict(list)
for t in rows:
    BYDATE[str(t[i['signal_date']] or '')].append(t)
BYDATE = dict(sorted(BYDATE.items()))
BASE_PF = st['pf_sel']       # 9键补位基线(K1)
BASE_PNL = sum(t[IP]['pnlYuan'] for t in BASE_PF)

def ctx(t):
    bd = str(t[i['buy_date']] or '')
    return dict(sig=t[i['signal']] or '', mm=bd[4:6] if len(bd)>=6 else '', dd=int(bd[6:8]) if len(bd)>=8 else 0,
                wd=buy_weekday(bd), bpb=buyprice_bin(t[i['buy_price']]),
                ts=float(t[i['track_score']]) if t[i['track_score']] not in (None,'') else 999.0,
                tier=t[i['market_tier']] or '', tier_all=t[i['market_tier_all']] or '',
                tier_cyb=t[i['market_tier_cyb']] or '',
                mktD=t[len(fIdx)] or '', ratD=t[len(fIdx)+2] or '',
                rating=str(t[i['rating']] or ''))

def eval_rule(rule_fn, K=1):
    """9键+R2 补位: 返回(sel, blocked_by_r2, added_by_r2, pnl)"""
    sel = []
    r2_blocked_pnl = 0.0; r2_blocked_n = 0
    added_pnl = 0.0; added_n = 0
    bs_keys = set()
    for sd, grp in BYDATE.items():
        kept2 = [t for t in grp if not (C.cand1(t) or rule_fn(ctx(t)))]
        top = sorted(kept2, key=lambda t: t[len(fIdx)+4])[:K]
        sel.extend(top)
    return sel

def delta_of(sel):
    p = sum(t[IP]['pnlYuan'] for t in sel)
    # diff vs BASE_PF
    bk = set()
    from sim_core import base_key
    bset = {base_key(t, fIdx) for t in BASE_PF}
    nset = {base_key(t, fIdx) for t in sel}
    blocked = [t for t in BASE_PF if base_key(t, fIdx) not in nset]
    added = [t for t in sel if base_key(t, fIdx) not in bset]
    bp = sum(t[IP]['pnlYuan'] for t in blocked); ap = sum(t[IP]['pnlYuan'] for t in added)
    return dict(delta=round(p - BASE_PNL, 2), new_total=round(p, 2),
                blocked_n=len(blocked), blocked_pnl=round(bp, 2),
                added_n=len(added), added_pnl=round(ap, 2))

# ---------- A. 结构化候选 ----------
print('=' * 96)
print('②A 结构化候选(vs9键补位, K1, 全史)')
print('=' * 96)
STRUCT = {
    'S1 候选1全域版: tier_all=牛主升×(aux|backup)': lambda c: c['tier_all'] == '牛市·主升' and c['sig'] in ('buy_aux', 'buy_backup'),
    'S1b 候选1全域增强: tier_all=牛主升×(aux|backup|special)': lambda c: c['tier_all'] == '牛市·主升' and c['sig'] in ('buy_aux', 'buy_backup', 'buy_special'),
    'S2 k2c5扩sig: hk域×aux': lambda c: c['mktD'] == 'hk' and c['sig'] == 'buy_aux',
    'S2b hk域×aux|buy(全域hk买入收紧)': lambda c: c['mktD'] == 'hk' and c['sig'] in ('buy_aux', 'buy'),
    'S3 global域×special': lambda c: c['mktD'] == 'global' and c['sig'] == 'buy_special',
    'S3b global域×(special|aux)': lambda c: c['mktD'] == 'global' and c['sig'] in ('buy_special', 'buy_aux'),
    'S4 buy×concept (=k3ConceptBuy现成键)': lambda c: c['sig'] == 'buy' and c['mktD'] == 'concept',
    'S5 rating=low全停 (=excludeRatingLow现成键)': lambda c: c['rating'] == 'low',
    'S5b rating∈{low}×非high评分信号': lambda c: c['ratD'] == 'low',
}
struct_out = {}
for name, fn in STRUCT.items():
    d = delta_of(eval_rule(fn))
    struct_out[name] = d
    print(f"{name:<46} 增量{d['delta']:>+9.0f} (新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f} / 替补进{d['added_n']}笔{d['added_pnl']:+.0f})")

# ---------- B. 原子谓词 ----------
ATOMS = {}
for s in ['buy_aux', 'buy_backup', 'buy_special', 'buy']:
    ATOMS[f'sig={s}'] = (lambda s_: lambda c: c['sig'] == s_)(s)
for r in ['low', 'mid', 'high']:
    ATOMS[f'rating={r}'] = (lambda r_: lambda c: c['rating'] == r_)(r)
    ATOMS[f'ratD={r}'] = (lambda r_: lambda c: c['ratD'] == r_)(r)
for m in ['concept', 'industry', 'a', 'hk', 'global', '']:
    ATOMS[f'mktD={m or "空"}'] = (lambda m_: lambda c: c['mktD'] == m_)(m)
for tv in ['牛市·主升', '震荡市', '下降期', '熊市·主跌', '牛市·启动']:
    ATOMS[f'tier={tv}'] = (lambda t_: lambda c: c['tier'] == t_)(tv)
    ATOMS[f'tierAll={tv}'] = (lambda t_: lambda c: c['tier_all'] == t_)(tv)
for thr in [45, 50, 55, 60, 65, 70, 75, 80]:
    ATOMS[f'ts<{thr}'] = (lambda h: lambda c: c['ts'] < h)(thr)
    ATOMS[f'ts>={thr}'] = (lambda h: lambda c: c['ts'] >= h)(thr)
for b in ['vlow', 'low', 'mid', 'high', 'vhigh']:
    ATOMS[f'bpb={b}'] = (lambda b_: lambda c: c['bpb'] == b_)(b)
for m in [f'{x:02d}' for x in range(1, 13)]:
    ATOMS[f'月={m}'] = (lambda m_: lambda c: c['mm'] == m_)(m)
for q, name in [(1, 'Q1'), (2, 'Q2'), (3, 'Q3'), (4, 'Q4')]:
    ATOMS[f'{name}季'] = (lambda q_: lambda c: math.ceil(int(c['mm'])/3) == q_ if c['mm'] else False)(q)
for wd in range(5):
    ATOMS[f'周{"一二三四五"[wd]}买'] = (lambda w_: lambda c: c['wd'] == w_)(wd)
ATOMS['上旬'] = lambda c: 1 <= c['dd'] <= 10
ATOMS['中旬'] = lambda c: 11 <= c['dd'] <= 20
ATOMS['下旬'] = lambda c: c['dd'] >= 21

# 快速评估缓存: 每原子先算命中集合
def hit_sets(atoms):
    out = {}
    for nm, fn in atoms.items():
        out[nm] = frozenset(id(t) for t in rows if fn(ctx(t)))
    return out
print()
print(f'原子数 {len(ATOMS)}, 计算命中集...')
HITS = hit_sets(ATOMS)
ID2T = {id(t): t for t in rows}

def fast_delta(hit_fs, K=1):
    """hit_fs: frozenset(id) 本规则新增拦截集(不含CAND1)。返回 delta dict 或 None(无拦截)。"""
    if not hit_fs: return None
    sel = []
    for sd, grp in BYDATE.items():
        kept2 = [t for t in grp if not (C.cand1(t) or id(t) in hit_fs)]
        top = sorted(kept2, key=lambda t: t[len(fIdx)+4])[:K]
        sel.extend(top)
    return delta_of(sel)

print('②B1 单原子扫描(vs9键):')
single = []
for nm, fs in HITS.items():
    d = fast_delta(fs)
    if d and d['delta'] > 0:
        single.append((d['delta'], nm, d))
single.sort(reverse=True)
for dv, nm, d in single[:20]:
    print(f"  {nm:<26} 增量{dv:>+9.0f} (新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f})")

# 二维合取
print()
print(f'②B2 二维合取({len(ATOMS)}选2 组合, 仅保留 delta>0):')
names = list(ATOMS.keys())
pairs = []
for a, b in itertools.combinations(names, 2):
    inter = HITS[a] & HITS[b]
    if not inter: continue
    d = fast_delta(inter)
    if d and d['delta'] > 500:
        pairs.append((d['delta'], f'{a} & {b}', d, inter))
pairs.sort(key=lambda x: -x[0])
for dv, nm, d, _ in pairs[:25]:
    print(f"  {nm:<52} 增量{dv:>+9.0f} (新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f})")

# 三维: 从二维 top 种子扩
print()
print('②B3 三维合取(二维top40种子×剩余原子):')
seed = [(nm, fs) for _, nm, _, fs in pairs[:40]]
triple = []
seen3 = set()
for nmA, fsA in seed:
    for nmB in names:
        key = tuple(sorted((nmA, nmB)))
        if key in seen3 or nmB in nmA: continue
        seen3.add(key)
        inter = fsA & HITS[nmB]
        if not inter: continue
        d = fast_delta(inter)
        if d and d['delta'] > 800:
            triple.append((d['delta'], f'{nmA} & {nmB}', d))
triple.sort(key=lambda x: -x[0])
for dv, nm, d in triple[:25]:
    print(f"  {nm:<70} 增量{dv:>+9.0f} (新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f})")

out = dict(generated_at=datetime.datetime.now().isoformat(),
           base_pf_full=BASE_PNL,
           structured=struct_out,
           single=[dict(name=nm, **d) for dv, nm, d in single],
           pairs=[dict(name=nm, **d) for dv, nm, d, _ in pairs],
           triple=[dict(name=nm, **d) for dv, nm, d in triple])
with open(os.path.join(HERE, 'data/mine13_substitute_mine.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine13_substitute_mine.json written')
