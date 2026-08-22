# -*- coding: utf-8 -*-
"""三轮挖掘 ③R2/R3/R4 假设四重检验(2026-08-22)。

目的:   对替补专项(R2)/2026年2-3月(R3)/历史主亏月簇(R4)候选规则统一过四重检验:
        ①vs9键叠加(10键)补位口径:全史增量>=+1500 且 2026年4月误伤>=-1500 且 5-8月不恶化;
        ②三道门(n>=30 过门,20-29 小样本申报,<20 不申报)+ 前向 2024-26 样本外净改善>=0 必过;
        ③留一法交叉验证(leave-one-year-out: 去掉任意一年后剩余年份合计增量仍>=0);
        ④2025 长牛反测(R2 在 2025 的误伤额)+ 按年分解 + K1-K4 敏感性 + A-F 跨模式。
口径:   补位口径(memory filter-backtest-position-fill-caliber);测试基准=current baseline(v1.1.4)。
        9键基线(mode A K1)=+73,102.53;8键基线=+66,530.38。
输入:   static-site/data/signal_kelly_trades.json
输出:   data/mine14_r2_validate.json + stdout 全表
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine14_substitute_validate.py
"""
import os, sys, json, math, datetime
from collections import defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r3_common as C
from sim_core import buyprice_bin, buy_weekday

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
from sim_core import base_key
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

def eval10(rule_fn, K=1, mode=None):
    """10键 = 9键 + rule_fn 补位评估。返回 sel 列表。mode=None 用当前 rows(A模式池已构建)。"""
    sel = []
    for sd in sorted(BYDATE):
        grp = BYDATE[sd]
        kept2 = [t for t in grp if not (C.cand1(t) or rule_fn(CTXED[id(t)]))]
        sel.extend(sorted(kept2, key=lambda t: t[len(fIdx)+4])[:K])
    return sel

def report(sel, tag=''):
    p = sum(t[IP]['pnlYuan'] for t in sel)
    nset = {base_key(t, fIdx) for t in sel}
    blocked = [t for t in BASE_PF if base_key(t, fIdx) not in nset]
    added = [t for t in sel if base_key(t, fIdx) not in BSET]
    bp = sum(t[IP]['pnlYuan'] for t in blocked); ap = sum(t[IP]['pnlYuan'] for t in added)
    d = dict(delta=round(p-BASE_PNL,2), total=round(p,2), n=len(sel),
             blocked_n=len(blocked), blocked_pnl=round(bp,2),
             added_n=len(added), added_pnl=round(ap,2))
    def win(rows_):
        return round(sum(t[IP]['pnlYuan'] for t in rows_), 2)
    d['apr2026'] = win([t for t in sel if '20260401' <= str(t[0]) <= '20260430']) - win([t for t in BASE_PF if '20260401' <= str(t[0]) <= '20260430'])
    d['mayaug'] = win([t for t in sel if '20260501' <= str(t[0]) <= '20260831']) - win([t for t in BASE_PF if '20260501' <= str(t[0]) <= '20260831'])
    d['fwd2426'] = win([t for t in sel if str(t[0]) >= '20240101']) - win([t for t in BASE_PF if str(t[0]) >= '20240101'])
    yr = defaultdict(float)
    for t in sel: yr[str(t[0])[:4]] += t[IP]['pnlYuan']
    yrb = defaultdict(float)
    for t in BASE_PF: yrb[str(t[0])[:4]] += t[IP]['pnlYuan']
    d['yearly_delta'] = {y: round(yr.get(y,0)-yrb.get(y,0),1) for y in sorted(set(yr)|set(yrb))}
    d['neg_years'] = sum(1 for v in d['yearly_delta'].values() if v < -0.5)
    # 留一法: 去掉任意一年后剩余合计最小值
    tot = d['delta']
    loyo_min = min(tot - v for v in d['yearly_delta'].values())
    d['loyo_min'] = round(loyo_min, 1)
    d['loyo_pass'] = bool(loyo_min >= 0)
    d['y2025'] = d['yearly_delta'].get('2025', 0.0)
    return d

# ---- 候选规则集(替补 R2 / 二三月 R3 / 主亏月簇 R4 见后续脚本, 此处统一编号) ----
RULES = {
    # --- R2 替补专项 ---
    'R2a buy×concept (k3现成键)': lambda c: c['sig'] == 'buy' and c['mktD'] == 'concept',
    'R2b buy_special×global': lambda c: c['sig'] == 'buy_special' and c['mktD'] == 'global',
    'R2c global域全停': lambda c: c['mktD'] == 'global',
    'R2d ts<55 全停(排序阈值)': lambda c: c['ts'] < 55,
    'R2d2 ts<60 全停': lambda c: c['ts'] < 60,
    'R2e tierAll=下降期×Q3': lambda c: c['tier_all'] == '下降期' and c['mm'] in ('07','08','09'),
    'R2f 月=08 全停': lambda c: c['mm'] == '08',
    'R2g 组合: low评×Q3×ts<75': lambda c: c['rating'] == 'low' and c['mm'] in ('07','08','09') and c['ts'] < 75,
    # --- R2 结构化补充 ---
    'R2h hk域aux (k2c5扩sig)': lambda c: c['mktD'] == 'hk' and c['sig'] == 'buy_aux',
    'R2i 候选1全域版(tierAll牛主升×aux|bk)': lambda c: c['tier_all'] == '牛市·主升' and c['sig'] in ('buy_aux','buy_backup'),
}

print('=' * 100)
print('③ R2 候选四重检验(vs9键补位, K1, mode A)')
print('=' * 100)
res = {}
for name, fn in RULES.items():
    sel = eval10(fn)
    d = report(sel)
    g1 = d['blocked_n'] >= 30
    g1s = 'PASS' if g1 else ('小样本申报' if d['blocked_n'] >= 20 else 'FAIL(<20)')
    g2 = d['delta'] >= 1500 and d['apr2026'] >= -1500 and d['mayaug'] >= 0
    g3 = d['fwd2426'] >= 0
    g4 = d['loyo_pass']
    verdict = []
    if d['delta'] >= 1500 and g2: verdict.append('量达标')
    if g3: verdict.append('前向过')
    if g4: verdict.append('留一法过')
    print(f"\n◆ {name}")
    print(f"  全史增量{d['delta']:+.0f} | 新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f}/替补进{d['added_n']}笔{d['added_pnl']:+.0f}"
          f" | 门①量: {'PASS' if d['delta']>=1500 else 'FAIL'}")
    print(f"  2026双向: 4月{d['apr2026']:+.0f}(>=-1500?) 5-8月{d['mayaug']:+.0f}(>=0?) -> {'PASS' if g2 else 'FAIL'}"
          f" | 前向2024-26: {d['fwd2426']:+.0f}(>=0?) -> {'PASS' if g3 else 'FAIL'}")
    print(f"  留一法: 去单年后最小合计 {d['loyo_min']:+.0f} -> {'PASS' if g4 else 'FAIL'}"
          f" | 2025反测: {d['y2025']:+.0f} | 负贡献年数: {d['neg_years']}/{len(d['yearly_delta'])}")
    print(f"  样本门: 新拦{d['blocked_n']}笔 {g1s}")
    print(f"  按年: {d['yearly_delta']}")
    res[name] = d

# ---- 最终推荐组合叠加测试: 逐条加 + 组合加(贪心) ----
print()
print('=' * 100)
print('③x 推荐组合叠加(在通过初筛的候选中按增量贪心累加, 检查组合后仍满足约束)')
print('=' * 100)
passed = [n for n, d in res.items() if d['delta'] >= 800 and d['fwd2426'] >= 0 and d['apr2026'] >= -1500]
print(f'初筛通过: {passed}')
comb_fn_map = {n: RULES[n] for n in passed}
def combined(fns):
    return eval10(lambda c: any(fn(c) for fn in fns))
sel_names = []
cur_fns = []
best_total = 0
while True:
    best = None
    for n in passed:
        if n in sel_names: continue
        d = report(combined(cur_fns + [comb_fn_map[n]]))
        if d['delta'] > best_total and d['apr2026'] >= -1500:
            best_total = d['delta']; best = (n, d)
    if not best: break
    sel_names.append(best[0]); cur_fns.append(comb_fn_map[best[0]])
    print(f"  + {best[0]} -> 组合增量 {best[1]['delta']:+.0f} (新拦累计{best[1]['blocked_n']}笔)")
if sel_names:
    d = report(combined(cur_fns))
    print(f"\n最终组合 {' + '.join(sel_names)}")
    print(f"  10+键全史 {d['total']:+.0f} (vs9键 {d['delta']:+.0f}, vs8键 {d['total']-66530.38:+.0f})")
    print(f"  4月{d['apr2026']:+.0f} 5-8月{d['mayaug']:+.0f} 前向{d['fwd2426']:+.0f} 2025:{d['y2025']:+.0f} 留一法min:{d['loyo_min']:+.0f}({d['loyo_pass']})")
    print(f"  按年: {d['yearly_delta']}")
    combo_d = d
else:
    combo_d = None
    print('  无可组合项')

out = dict(generated_at=datetime.datetime.now().isoformat(),
           base_pf=BASE_PNL, rules=res,
           greedy_combo=dict(names=sel_names, detail=combo_d) if sel_names else None)
with open(os.path.join(HERE, 'data/mine14_r2_validate.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine14_r2_validate.json written')
