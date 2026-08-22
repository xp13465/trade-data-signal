# -*- coding: utf-8 -*-
"""Part H: 二维组合规则穷举(时段级优先) + 防过拟合三道门 + K档敏感性"""
import sys, json, math, itertools
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)

with open('/Users/linhuichen/code/trade/static-site/data/index/hs300-all.json') as f:
    hs = json.load(f)['ohlc']
dates = [r['date'] for r in hs]; closes = [r['close'] for r in hs]
n = len(hs)
dd252=[None]*n; vol20=[None]*n
for i in range(n):
    if i >= 251: dd252[i] = closes[i]/max(closes[i-251:i+1]) - 1
    if i >= 20:
        rets=[closes[j]/closes[j-1]-1 for j in range(i-19,i+1)]
        vol20[i]=(sum(r*r for r in rets)/20)**0.5*math.sqrt(252)
def feat_at(d):
    if d < dates[0]: return None
    lo, hi=0,n-1
    while lo<hi:
        mid=(lo+hi+1)//2
        if dates[mid]<=d: lo=mid
        else: hi=mid-1
    i=lo
    return dict(dd=dd252[i], vol=vol20[i])

def pnl(rows): return sum(S.calc_row(t,fIdx)['pnlYuan'] for t in rows)
def build(mode):
    pool=S.build_mode_pool(tr,fIdx,mode)
    fade=[t for t in pool if S.passes_fade(t,fIdx,filters,mmask,mD,eD,rD)]
    return fade, S.topk_by_date(fade,fIdx,1)

fadeA, k1A = build('A')

# 特征取值函数(全部可作时段级判定——买入日前可知)
def ft_of(t):
    f = feat_at(str(t[fIdx['buy_date']] or ''))
    return f
DIM = {
    'tier': lambda t: t[fIdx['market_tier']] or '(非A股)',
    'sig': lambda t: t[fIdx['signal']],
    'mkt': lambda t: t[mD] or '(空)',
    'rating': lambda t: t[rD] or t[fIdx['rating']],
    'hsDD': lambda t: ('贴新高≤3%' if (f:=ft_of(t)) and f['dd'] is not None and f['dd']>=-0.03 else '回撤3-10%' if f and f['dd'] is not None and f['dd']>=-0.10 else '回撤>10%' if f and f['dd'] is not None else None),
    'hsVol': lambda t: ('vol<15%' if (f:=ft_of(t)) and f['vol'] is not None and f['vol']<0.15 else 'vol15-25%' if f and f['vol'] is not None and f['vol']<0.25 else 'vol≥25%' if f and f['vol'] is not None else None),
}
def cond_dim_vals(spec):
    """spec: list of (dim, val) => 谓词: 所有维度命中指定值"""
    dims = [(d, DIM[d], v) for d, v in spec]
    def pred(t):
        for _, fn, v in dims:
            if fn(t) != v: return False
        return True
    return pred

def eval_rule(pred, name):
    """返回规则评估: 被砍笔的各期净额(负=好)"""
    cut = [t for t in k1A if pred(t)]
    kept26 = [t for t in k1A if not pred(t)]
    cut_58 = pnl([t for t in cut if '20260500' <= (t[fIdx['signal_date']] or '') < '20260900'])
    cut_apr = pnl([t for t in cut if (t[fIdx['signal_date']] or '').startswith('202604')])
    cut_all = pnl(cut)
    years = {}
    for t in cut:
        y = (t[fIdx['signal_date']] or '')[:4]
        years.setdefault(y, 0.0); years[y] += S.calc_row(t, fIdx)['pnlYuan']
    neg_years = sum(1 for v in years.values() if v < 0)
    # 前向: 2011-2023 定(看是否≥0即历史上不亏钱才敢停), 2024-2026 验
    cut_f = pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4] <= '2023'])
    cut_o = pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4] >= '2024'])
    return dict(name=name, n=len(cut), cut_all=cut_all, cut_58=cut_58, cut_apr=cut_apr,
                neg_years=f'{neg_years}/{len(years)}', fwd_in=cut_f, fwd_out=cut_o)

# 三道门: n>=30; 2026效果(5-8月砍<=-2500 且 4月砍>=-1500); 稳定性(fwd_out<=0 即近三年也成立 + 按年负占比>=55%)
results = []
vals = {k: sorted(set(fn(t) for t in k1A if fn(t) is not None)) for k, fn in DIM.items()}
# 一维
for d, vs in vals.items():
    for v in vs:
        p = cond_dim_vals([(d, v)])
        results.append(eval_rule(p, f'{d}={v}'))
# 二维组合(tier×sig / tier×mkt / mkt×sig / hsDD×mkt / tier×hsVol / sig×hsVol)
pairs = [('tier','sig'),('tier','mkt'),('mkt','sig'),('hsDD','mkt'),('tier','hsVol'),('sig','hsVol'),('hsDD','tier'),('hsDD','sig'),('hsVol','mkt')]
for d1, d2 in pairs:
    for v1 in vals[d1]:
        for v2 in vals[d2]:
            p = cond_dim_vals([(d1,v1),(d2,v2)])
            results.append(eval_rule(p, f'{d1}={v1} & {d2}={v2}'))

print('=' * 100)
print('Part H: 规则穷举(一维+二维, mode A K1 基线上叠加). 被砍净额负=规则有效')
print('三道门: ①n>=30 ②2026效果: 5-8月砍<=-2500 且 4月误伤>=-1500 ③前向2024-26被砍<=0 且 按年负占比>=55%')
print('=' * 100)
passed = [r for r in results if r['n']>=30 and r['cut_58']<=-2500 and r['cut_apr']>=-1500 and r['fwd_out']<=0 and int(r['neg_years'].split('/')[0])/max(int(r['neg_years'].split('/')[1]),1)>=0.55]
results.sort(key=lambda r: r['cut_58'])
print(f'{"规则":<44} {"n":>4} {"全史砍":>9} {"26年5-8月":>9} {"26年4月":>8} {"按年负占比":>8} {"23前":>8} {"24-26":>8} 门')
for r in results[:25]:
    ok = r in passed
    print(f"{r['name']:<44} {r['n']:>4} {r['cut_all']:>+9.0f} {r['cut_58']:>+9.0f} {r['cut_apr']:>+8.0f} {r['neg_years']:>8} {r['fwd_in']:>+8.0f} {r['fwd_out']:>+8.0f} {'PASS' if ok else ''}")
print(f'\n过三道门规则数: {len(passed)}')
for r in passed:
    print(f"  PASS -> {r['name']}")

# K 档敏感性: 牛市主升全停 & concept停 在 K1-K4 下 2026 5-8 月效果
print()
print('=' * 90)
print('Part H2: K 档敏感性(K1-K4, mode A): 2026全年/5-8月, 基线 vs 叠加候选')
print('=' * 90)
for K in (1,2,3,4):
    kx = S.topk_by_date(fadeA, fIdx, K)
    for tag, pred in [('基线', lambda t: False), ('停A股牛主升', lambda t: (t[fIdx['market_tier']] or '')=='牛市·主升'), ('停concept', lambda t: (t[mD] or '')=='concept'), ('停牛主升&concept', lambda t: (t[fIdx['market_tier']] or '')=='牛市·主升' or (t[mD] or '')=='concept')]:
        rows = [t for t in kx if not pred(t)]
        r26 = [t for t in rows if (t[fIdx['signal_date']] or '').startswith('2026')]
        m58 = [t for t in r26 if '20260500' <= (t[fIdx['signal_date']] or '') < '20260900']
        print(f'  K={K} {tag:<18} | 2026全年={pnl(r26):>+8.0f} | 5-8月={pnl(m58):>+8.0f}')
