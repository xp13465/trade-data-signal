# -*- coding: utf-8 -*-
"""三轮挖掘 ④2026年2-3月亏损笔画像(R3)(2026-08-22)。

目的:   用户实测反馈「候选1对5-6/7/8月减亏有效, 但2026年2/3月的亏损好像没怎么过滤到」
        (K1基线 2月-3,160 / 3月-982)。本脚本逐笔画像 2026 年 2-3 月亏损主体,
        回答「候选1为何没覆盖」, 与替补45笔画像对照, 并产出 R3 过滤假设(交 mine16 统一检验)。
口径:   主口径=9键补位基线(pf_sel, 用户当前主推版); 附 8键基线对照。
输入:   static-site/data/signal_kelly_trades.json
输出:   data/mine15_febmar_profile.json + stdout
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/mine15_febmar_profile.py
"""
import os, sys, json, datetime
from collections import Counter, defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import r3_common as C

st = C.get_sets()
rows, fIdx = C.ensure()
i = fIdx
IP = len(fIdx) + 3

def month_rows(sel, ym):
    return [t for t in sel if str(t[i['signal_date']] or '').startswith(ym)]

for tag, sel in [('8键K1基线', st['base_sel']), ('9键补位基线', st['pf_sel'])]:
    print('=' * 96)
    print(f'④ {tag}: 2026年逐月净额')
    print('=' * 96)
    bym = defaultdict(float); byn = defaultdict(int)
    for t in sel:
        sd = str(t[i['signal_date']] or '')
        if sd.startswith('2026'):
            bym[sd[:6]] += t[IP]['pnlYuan']; byn[sd[:6]] += 1
    for m in sorted(bym):
        mark = ' <-- 用户点名' if m in ('202602', '202603') else ''
        print(f"  {m}: {bym[m]:+9.0f}元 ({byn[m]}笔){mark}")

print()
print('=' * 96)
print('④a 9键基线下 2026年2-3月 入选笔逐笔明细(亏损主体)')
print('=' * 96)

def brief(t):
    c = C.R.calc_row_pub(t, fIdx)
    bd = str(t[i['buy_date']] or '')
    return dict(sd=str(t[i['signal_date']]), index_id=t[i['index_id']], sig=t[i['signal']],
                rating=str(t[i['rating']] or ''), ts=t[i['track_score']], tier=t[i['market_tier']] or '',
                tier_all=t[i['market_tier_all']] or '', mktD=t[len(fIdx)] or '',
                buy_date=bd, pnl=round(c['pnlYuan'], 2), holding=c['isHolding'],
                sell_reason=t[i['sell_reason']] or '')

febmar = [brief(t) for t in sorted(month_rows(st['pf_sel'], '202602') + month_rows(st['pf_sel'], '202603'),
                                   key=lambda x: str(x[i['signal_date']] or ''))]
losers_feb = [r for r in febmar if r['sd'].startswith('202602')]
losers_mar = [r for r in febmar if r['sd'].startswith('202603')]
for r in febmar:
    print(f"  {r['sd']} {r['sig']:<12} {r['index_id']:<14} rat={r['rating']:<4} ts={r['ts']} tier={r['tier']:<6} all={r['tier_all']:<6} 域={r['mktD']:<8} pnl={r['pnl']:+7.0f} {'持有中' if r['holding'] else r['sell_reason']}")

fm_pnl = sum(r['pnl'] for r in febmar)
print(f"\n2-3月合计 {len(febmar)} 笔 {fm_pnl:+.0f}元 | 2月 {sum(r['pnl'] for r in losers_feb):+.0f}({len(losers_feb)}笔) 3月 {sum(r['pnl'] for r in losers_mar):+.0f}({len(losers_mar)}笔)")
print(f"  sig分布: {dict(Counter(r['sig'] for r in febmar))}")
print(f"  rating分布: {dict(Counter(r['rating'] for r in febmar))}")
print(f"  档位分布: {dict(Counter(r['tier'] or '(空)' for r in febmar))}")
print(f"  域分布: {dict(Counter(r['mktD'] or '(空)' for r in febmar))}")
neg = [r for r in febmar if r['pnl'] < 0]
print(f"  亏损笔 {len(neg)} 笔合计 {sum(r['pnl'] for r in neg):+.0f} | 亏损笔sig: {dict(Counter(r['sig'] for r in neg))} | 亏损笔rating: {dict(Counter(r['rating'] for r in neg))}")

# 与替补45笔画像对照
print()
print('④b 与替补45笔画像对照:')
filled_brief = [brief(t) for t in st['filled']]
print(f"  替补45笔 sig: {dict(Counter(r['sig'] for r in filled_brief))} | rating: {dict(Counter(r['rating'] for r in filled_brief))}")
print(f"  2-3月笔 sig: {dict(Counter(r['sig'] for r in febmar))} | rating: {dict(Counter(r['rating'] for r in febmar))}")

# 候选1为何没覆盖: 2-3月亏损笔是否命中CAND1?
hit_cand1 = sum(1 for t in month_rows(st['pf_sel'], '202602') + month_rows(st['pf_sel'], '202603') if C.cand1(t))
print(f"  2-3月入选笔中命中候选1(牛主升×aux|bk): {hit_cand1} 笔(=0 即候选1结构上无法覆盖该段)")

out = dict(generated_at=datetime.datetime.now().isoformat(),
           febmar_rows=febmar,
           feb_total=round(sum(r['pnl'] for r in losers_feb), 2),
           mar_total=round(sum(r['pnl'] for r in losers_mar), 2),
           sig_dist=dict(Counter(r['sig'] for r in febmar)),
           rating_dist=dict(Counter(r['rating'] for r in febmar)))
with open(os.path.join(HERE, 'data/mine15_febmar_profile.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=float)
print('\ndata/mine15_febmar_profile.json written')
