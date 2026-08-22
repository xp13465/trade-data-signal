# -*- coding: utf-8 -*-
"""三轮挖掘 ⑤历史主亏月检索 Top20 + R3/R4 假设四重检验(2026-08-22)。

目的:   ①9键补位基线按 signal_date 月桶聚合, Top20 亏损月检索 + 画像聚类(tier/季节/sig/域);
        ②R3 假设(来自2026年2-3月画像: special×concept / hk∪global 域 aux 收紧)与
          R4 假设(主亏月簇规则)统一过四重检验(同 mine14 口径);
        ③输出「10+键最终组合」对 2026 各月/主亏月段的净效果表。
口径:   补位口径(memory filter-backtest-position-fill-caliber);测试基准 current baseline(v1.1.4);9键基线=+73,102.53。
输入:   static-site/data/signal_kelly_trades.json
输出:   data/mine16_worstmonths_r34.json + stdout
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine16_worstmonths_r34.py
"""
import os, sys, json, math, datetime
from collections import Counter, defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r3_common as C
from sim_core import buyprice_bin, buy_weekday, base_key

st = C.get_sets()
rows, fIdx = C.ensure()
i = fIdx
IP = len(fIdx) + 3
BYDATE = defaultdict(list)
for t in rows:
    BYDATE[str(t[i['signal_date']] or '')].append(t)
BYDATE = dict(sorted(BYDATE.items()))
BASE_PF = st['pf_sel']
BASE_PNL = sum(t[IP]['pnlYuan'] for t in BASE_PF)
BSET = {base_key(t, fIdx) for t in BASE_PF}

def ctx(t):
    bd = str(t[i['buy_date']] or '')
    return dict(sig=t[i['signal']] or '', mm=bd[4:6] if len(bd)>=6 else '', dd=int(bd[6:8]) if len(bd)>=8 else 0,
                wd=buy_weekday(bd), bpb=buyprice_bin(t[i['buy_price']]),
                ts=float(t[i['track_score']]) if t[i['track_score']] not in (None,'') else 999.0,
                tier=t[i['market_tier']] or '', tier_all=t[i['market_tier_all']] or '',
                mktD=t[len(fIdx)] or '', ratD=t[len(fIdx)+2] or '',
                rating=str(t[i['rating']] or ''), sd=str(t[i['signal_date']] or ''))
CTXED = {id(t): ctx(t) for t in rows}

def eval10(rule_fns, K=1):
    sel = []
    for sd in sorted(BYDATE):
        grp = BYDATE[sd]
        kept2 = [t for t in grp if not (C.cand1(t) or any(fn(CTXED[id(t)]) for fn in rule_fns))]
        sel.extend(sorted(kept2, key=lambda t: t[len(fIdx)+4])[:K])
    return sel

def report(sel):
    p = sum(t[IP]['pnlYuan'] for t in sel)
    nset = {base_key(t, fIdx) for t in sel}
    blocked = [t for t in BASE_PF if base_key(t, fIdx) not in nset]
    bp = sum(t[IP]['pnlYuan'] for t in blocked)
    def win(lo, hi=None):
        return sum(t[IP]['pnlYuan'] for t in sel if lo <= str(t[0]) <= (hi or '99999999')) - \
               sum(t[IP]['pnlYuan'] for t in BASE_PF if lo <= str(t[0]) <= (hi or '99999999'))
    yr = defaultdict(float); yrb = defaultdict(float)
    for t in sel: yr[str(t[0])[:4]] += t[IP]['pnlYuan']
    for t in BASE_PF: yrb[str(t[0])[:4]] += t[IP]['pnlYuan']
    ydelta = {y: round(yr.get(y,0)-yrb.get(y,0),1) for y in sorted(set(yr)|set(yrb))}
    return dict(delta=round(p-BASE_PNL,2), total=round(p,2), blocked_n=len(blocked), blocked_pnl=round(bp,2),
                apr2026=round(win('20260401','20260430'),1),
                febmar26=round(win('20260201','20260331'),1),
                mayaug=round(win('20260501','20260831'),1),
                fwd2426=round(win('20240101'),1),
                y2025=ydelta.get('2025',0.0), neg_years=sum(1 for v in ydelta.values() if v < -0.5),
                yearly=ydelta,
                loyo_min=round(min((p-BASE_PNL)-v for v in ydelta.values()),1))

# ---------- ① Top20 主亏月 ----------
print('=' * 96)
print('⑤① 9键补位基线: 全史按月净额 Top20 亏损月')
print('=' * 96)
bym = defaultdict(list)
for t in BASE_PF:
    bym[str(t[i['signal_date']] or '')[:6]].append(t)
mstats = []
for m, ts_ in bym.items():
    pnl = sum(t[IP]['pnlYuan'] for t in ts_)
    mstats.append((pnl, m, ts_))
worst = sorted(mstats)[:20]
for pnl, m, ts_ in worst:
    sigs = Counter(t[i['signal']] or '' for t in ts_)
    tiers = Counter((t[i['market_tier']] or '(空)') for t in ts_)
    doms = Counter((t[len(fIdx)] or '(空)') for t in ts_)
    print(f"{m}: {pnl:+9.0f}元 ({len(ts_)}笔) sig={dict(sigs)} tier={dict(tiers)} 域={dict(doms)}")

print()
print('主亏月按「季节×结构」聚类:')
clus = defaultdict(lambda: dict(months=[], pnl=0.0))
for pnl, m, ts_ in worst:
    q = math.ceil(int(m[4:6])/3)
    dom_main = Counter((t[len(fIdx)] or '(空)') for t in ts_).most_common(1)[0][0]
    key = f'Q{q}·主域{dom_main}'
    clus[key]['months'].append(f'{m}({pnl:+.0f})'); clus[key]['pnl'] += pnl
for k, v in sorted(clus.items(), key=lambda kv: kv[1]['pnl']):
    print(f"  {k}: {len(v['months'])}个月 合计{v['pnl']:+.0f} -> {', '.join(v['months'])}")

# ---------- ② R3/R4 假设四重检验 ----------
print()
print('=' * 96)
print('⑤② R3/R4 假设四重检验(vs9键补位)')
print('=' * 96)
R34 = {
    'R3a special×concept 全停': lambda c: c['sig'] == 'buy_special' and c['mktD'] == 'concept',
    'R3b hk|global域×aux 全停(全域aux收紧)': lambda c: c['mktD'] in ('hk','global') and c['sig'] == 'buy_aux',
    'R3c special×(concept|global) 合并': lambda c: c['sig'] == 'buy_special' and c['mktD'] in ('concept', 'global'),
}
r34_out = {}
for name, fn in R34.items():
    d = report(eval10([fn]))
    g2 = d['apr2026'] >= -1500 and d['mayaug'] >= 0
    g3 = d['fwd2426'] >= 0
    g4 = d['loyo_min'] >= 0
    print(f"\n◆ {name}")
    print(f"  全史增量{d['delta']:+.0f} 新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f} | 4月{d['apr2026']:+.0f} 5-8月{d['mayaug']:+.0f} -> 门② {'PASS' if g2 else 'FAIL'}")
    print(f"  前向{d['fwd2426']:+.0f} -> {'PASS' if g3 else 'FAIL'} | 留一法min {d['loyo_min']:+.0f} -> {'PASS' if g4 else 'PASS' if False else ('FAIL' if not g4 else 'PASS')} | 2025:{d['y2025']:+.0f} 负贡献年:{d['neg_years']}/16")
    print(f"  2-3月改善: {d['febmar26']:+.0f}")
    print(f"  按年: {d['yearly']}")
    r34_out[name] = d

# ---------- ③ 最终组合(纯过关全家福): R2a+R2b+R2g (+R3 若过关) ----------
print()
print('=' * 96)
print('⑤③ 最终组合测试')
print('=' * 96)
R2 = {
    'R2a': lambda c: c['sig'] == 'buy' and c['mktD'] == 'concept',
    'R2b': lambda c: c['sig'] == 'buy_special' and c['mktD'] == 'global',
    'R2g': lambda c: c['rating'] == 'low' and c['mm'] in ('07','08','09') and c['ts'] < 75,
}
combos = {
    '纯过关 R2(a+b+g)': list(R2.values()),
    'R2 + R3a': list(R2.values()) + [R34['R3a special×concept 全停']],
    'R2 + R3a + R3b': list(R2.values()) + [R34['R3a special×concept 全停'], R34['R3b hk|global域×aux 全停(全域aux收紧)']],
}
final_out = {}
for nm, fns in combos.items():
    d = report(eval10(fns))
    final_out[nm] = d
    g_all = d['delta'] >= 1500 and d['apr2026'] >= -1500 and d['mayaug'] >= 0 and d['fwd2426'] >= 0 and d['loyo_min'] >= 0
    print(f"\n◆ {nm}: 全史{d['total']:+.0f} vs9键{d['delta']:+.0f} vs8键{d['total']-66530.38:+.0f}")
    print(f"  4月{d['apr2026']:+.0f} | 5-8月{d['mayaug']:+.0f} | 2-3月{d['febmar26']:+.0f} | 前向{d['fwd2426']:+.0f} | 2025:{d['y2025']:+.0f} | 留一法min{d['loyo_min']:+.0f} | 四重{'ALL PASS' if g_all else '存在FAIL'}")
    print(f"  2026逐月增量: " + str({m: round(v,0) for m, v in d['yearly'].items() if m == '2026'}))
    # 2026 逐月明细
    sel = eval10(fns)
    bym2 = defaultdict(float); bymb = defaultdict(float)
    for t in sel:
        if str(t[0]).startswith('2026'): bym2[str(t[0])[:6]] += t[IP]['pnlYuan']
    for t in BASE_PF:
        if str(t[0]).startswith('2026'): bymb[str(t[0])[:6]] += t[IP]['pnlYuan']
    print('  2026逐月(基线->组合): ' + ' '.join(f"{m}:{bymb.get(m,0):+.0f}->{bym2.get(m,0):+.0f}" for m in sorted(set(bym2)|set(bymb))))

out = dict(generated_at=datetime.datetime.now().isoformat(),
           worst_months=[dict(month=m, pnl=round(p,1), n=len(ts_)) for p, m, ts_ in worst],
           clusters={k: dict(v) for k, v in clus.items()},
           r34=r34_out, final_combos=final_out)
with open(os.path.join(HERE, 'data/mine16_worstmonths_r34.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine16_worstmonths_r34.json written')
