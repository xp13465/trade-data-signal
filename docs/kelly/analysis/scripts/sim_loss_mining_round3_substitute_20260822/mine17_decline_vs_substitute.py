# -*- coding: utf-8 -*-
"""三轮挖掘 ⑥「下降期盲区补强」vs「替补专项」优先级对比(2026-08-22)。

目的:   用户问「类似激进版但其他方向」。本轮以同口径(补位, vs9键)重测下降期方向全部候选:
        候选C(下降期×备买, 一轮观察型)/ R2e(tierAll=下降期×Q3, 本轮新) / 下降期全停变体,
        与替补专项组合(R2a+R2b+R2g)做数据对比, 给优先级判断。
口径:   补位口径;测试基准 current baseline(v1.1.4);9键基线=+73,102.53。
输入:   static-site/data/signal_kelly_trades.json
输出:   data/mine17_decline_vs_substitute.json + stdout
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine17_decline_vs_substitute.py
"""
import os, sys, json, datetime
from collections import defaultdict
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
BASE_PF = st['pf_sel']; BASE_PNL = sum(t[IP]['pnlYuan'] for t in BASE_PF)

def ctx(t):
    bd = str(t[i['buy_date']] or '')
    return dict(sig=t[i['signal']] or '', mm=bd[4:6] if len(bd)>=6 else '',
                ts=float(t[i['track_score']]) if t[i['track_score']] not in (None,'') else 999.0,
                tier=t[i['market_tier']] or '', tier_all=t[i['market_tier_all']] or '',
                mktD=t[len(fIdx)] or '', rating=str(t[i['rating']] or ''))
CTXED = {id(t): ctx(t) for t in rows}

def eval10(rule_fns):
    sel = []
    for sd in sorted(BYDATE):
        grp = BYDATE[sd]
        kept2 = [t for t in grp if not (C.cand1(t) or any(fn(CTXED[id(t)]) for fn in rule_fns))]
        sel.extend(sorted(kept2, key=lambda t: t[len(fIdx)+4])[:1])
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
    yd = {y: round(yr.get(y,0)-yrb.get(y,0),1) for y in sorted(set(yr)|set(yrb))}
    after24 = sum(v for y, v in yd.items() if y >= '2024')
    return dict(delta=round(p-BASE_PNL,2), total=round(p,2), blocked_n=len(blocked), blocked_pnl=round(bp,2),
                apr2026=round(win('20260401','20260430'),1), mayaug=round(win('20260501','20260831'),1),
                aug26=round(win('20260801','20260831'),1),
                fwd2426=round(win('20240101'),1), after24=round(after24,1),
                y2025=yd.get('2025',0.0), neg_years=sum(1 for v in yd.values() if v < -0.5),
                yearly=yd, loyo_min=round(min((p-BASE_PNL)-v for v in yd.values()),1))

print('=' * 100)
print('⑥ 下降期方向候选(vs9键补位, K1)——与替补专项同口径对比')
print('=' * 100)
CANDS = {
    'D-a 候选C: A股下降期×备买(一轮观察型)': lambda c: c['tier'] == '下降期' and c['sig'] == 'buy_backup',
    'D-b 下降期×备买全域版(tierAll)': lambda c: c['tier_all'] == '下降期' and c['sig'] == 'buy_backup',
    'D-c 下降期全信号(A股tier)': lambda c: c['tier'] == '下降期',
    'D-d 下降期全信号全域版(tierAll)': lambda c: c['tier_all'] == '下降期',
    'D-e R2e: tierAll下降期×Q3': lambda c: c['tier_all'] == '下降期' and c['mm'] in ('07','08','09'),
}
out = {}
for name, fn in CANDS.items():
    d = report(eval10([fn]))
    out[name] = d
    print(f"\n◆ {name}: 全史增量{d['delta']:+.0f} 新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f}")
    print(f"  2026双向: 4月{d['apr2026']:+.0f} 5-8月{d['mayaug']:+.0f} | 其中8月{d['aug26']:+.0f}(用户主亏月)")
    print(f"  前向2024-26 {d['fwd2426']:+.0f} | 2024后合计{d['after24']:+.0f} | 2025:{d['y2025']:+.0f} | 负贡献年:{d['neg_years']}/16 | 留一法min:{d['loyo_min']:+.0f}")

# 对照: 替补专项组合
R2 = [
    lambda c: c['sig'] == 'buy' and c['mktD'] == 'concept',
    lambda c: c['sig'] == 'buy_special' and c['mktD'] == 'global',
    lambda c: c['rating'] == 'low' and c['mm'] in ('07','08','09') and c['ts'] < 75,
]
d = report(eval10(R2))
out['对照: 替补专项组合R2(a+b+g)'] = d
print(f"\n◆ 对照 替补专项组合R2(a+b+g): 全史增量{d['delta']:+.0f} 新拦{d['blocked_n']}笔{d['blocked_pnl']:+.0f}")
print(f"  2026双向: 4月{d['apr2026']:+.0f} 5-8月{d['mayaug']:+.0f} | 8月{d['aug26']:+.0f}")
print(f"  前向{d['fwd2426']:+.0f} | 2024后{d['after24']:+.0f} | 2025:{d['y2025']:+.0f} | 负贡献年:{d['neg_years']}/16 | 留一法min:{d['loyo_min']:+.0f}")

with open(os.path.join(HERE, 'data/mine17_decline_vs_substitute.json'), 'w') as f:
    json.dump(dict(generated_at=datetime.datetime.now().isoformat(), candidates=out), f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine17_decline_vs_substitute.json written')
