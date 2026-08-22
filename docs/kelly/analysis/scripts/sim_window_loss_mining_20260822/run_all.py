# -*- coding: utf-8 -*-
"""首页「模拟回测」弹窗亏损结构挖掘 · 一键复现入口(2026-08-22)

目的:   复现用户弹窗观察(4/1正/5月起亏) + 三口径分解 + 历史连亏段 + 时段级空仓候选穷举
口径:   弹窗默认 = mode A + AI降亏8键 + K1 top-K + etf_def费率(万3/min5/滑千1/过户万0.1/印花万5),
        数据 v1.1.4(信号次日开盘买入), 与 static-site/app.js L2464-3395 _simRender 链路 1:1
输入:   static-site/data/signal_kelly_trades.json (generated_at=2026-08-22 16:58)
        static-site/data/index/hs300-all.json (大盘特征)
        static-site/data/market_tier_history.json (四档历史)
输出:   data/results.json (全量数字产物)
复现:   python3 docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/run_all.py
"""
import sys, os, json, math, datetime, bisect

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, HERE)
import sim_core as S  # noqa

OUT = dict(generated_at=datetime.datetime.now().isoformat(), data_file=None)

tr, fIdx = S.load(os.path.join(ROOT, 'static-site/data/signal_kelly_trades.json'))
OUT['data_file'] = dict(generated_at=tr.get('generated_at'), buy_amount=tr.get('buy_amount'))
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)
def pnl(rows): return sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)
def build(mode):
    pool = S.build_mode_pool(tr, fIdx, mode)
    fade = [t for t in pool if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
    return pool, fade, S.topk_by_date(fade, fIdx, 1)

# hs300 特征
with open(os.path.join(ROOT, 'static-site/data/index/hs300-all.json')) as f:
    hs = json.load(f)['ohlc']
dates=[r['date'] for r in hs]; closes=[r['close'] for r in hs]; n=len(hs)
dd252=[None]*n; vol20=[None]*n; chg20=[None]*n
for i in range(n):
    if i>=251: dd252[i]=closes[i]/max(closes[i-251:i+1])-1
    if i>=20:
        rets=[closes[j]/closes[j-1]-1 for j in range(i-19,i+1)]
        vol20[i]=(sum(r*r for r in rets)/20)**0.5*math.sqrt(252); chg20[i]=closes[i]/closes[i-20]-1
def feat_at(d):
    if d<dates[0]: return None
    i=bisect.bisect_right(dates,d)-1
    return dict(dd=dd252[i],vol=vol20[i],chg20=chg20[i])
with open(os.path.join(ROOT, 'static-site/data/market_tier_history.json')) as f:
    hist=json.load(f)
tdates=[h['date'] for h in hist]; tvals=[h['tier'] for h in hist]
def tier_at(d):
    i=bisect.bisect_right(tdates,d)-1
    return tvals[i] if i>=0 else None

# ===== 1. 复现窗口 =====
poolA, fadeA, k1A = build('A')
repro={}
for start in ('20260401','20260501'):
    repro[start]={}
    for tag,rows in [('all',poolA),('k1',k1A)]:
        sub=[t for t in rows if str(t[fIdx['signal_date']] or '')>=start]
        st=S.window_stats(sub,fIdx); repro[start][tag]=st
OUT['repro']=repro

# ===== 2. 9模式×逐月 =====
modes={}
for mode in 'ABCDEFGHI':
    _,fade,k1=build(mode)
    mm={}
    for t in k1:
        sd=str(t[fIdx['signal_date']] or '')
        if sd.startswith('2026'): mm.setdefault(sd[:6],[]).append(t)
    modes[mode]=dict(full_hist=pnl(k1), m2026={m:pnl(rs) for m,rs in sorted(mm.items())},
                     m58=pnl([t for m,rs in mm.items() if '202605'<=m<='202608' for t in rs]))
OUT['modes']=modes

# ===== 3. 三口径 =====
k1_keys=set(S.base_key(t,fIdx) for t in k1A); fade_keys=set(S.base_key(t,fIdx) for t in fadeA)
three={}
for w in ('20260401','20260501'):
    three[w]={
      'all': S.window_stats([t for t in poolA if str(t[fIdx['signal_date']] or '')>=w],fIdx)['cumYuan'],
      'k1': S.window_stats([t for t in k1A if str(t[fIdx['signal_date']] or '')>=w],fIdx)['cumYuan'],
      'removed_fade': pnl([t for t in poolA if S.base_key(t,fIdx) not in fade_keys and str(t[fIdx['signal_date']] or '')>=w]),
      'removed_k': pnl([t for t in fadeA if S.base_key(t,fIdx) not in k1_keys and str(t[fIdx['signal_date']] or '')>=w]),
    }
OUT['three_caliber']=three

# ===== 4. 历史连亏段(mode A K1) =====
ser={}
for t in k1A:
    m=(t[fIdx['signal_date']] or '')[:6]; ser[m]=ser.get(m,0.0)+S.calc_row(t,fIdx)['pnlYuan']
months_all=sorted(ser); segs=[]; cur=[]
for m in months_all:
    if ser[m]<0: cur.append(m)
    else:
        if len(cur)>=3: segs.append(cur)
        cur=[]
if len(cur)>=3: segs.append(cur)
seg_out=[]
for sg in segs:
    ei=months_all.index(sg[-1])
    a3=sum(ser[m] for m in months_all[ei+1:ei+4]) if ei+3<len(months_all) else None
    a6=sum(ser[m] for m in months_all[ei+1:ei+7]) if ei+6<len(months_all) else None
    nt=tier_at(months_all[ei+1]+'01') if ei+1<len(months_all) else None
    seg_out.append(dict(start=sg[0],end=sg[-1],n_months=len(sg),loss=sum(ser[m] for m in sg),after3=a3,after6=a6,tier_after=nt))
OUT['loss_segments']=seg_out
OUT['monthly_2026']={
  'baseline': {mm:sum(S.calc_row(t,fIdx)['pnlYuan'] for t in k1A if (t[fIdx['signal_date']] or '').startswith(mm)) for mm in [f'2026{int(i):02d}' for i in range(1,9)]},
}

# ===== 5. 时段级规则穷举(一维+二维,三道门) =====
DIM={
 'tier': lambda t: t[fIdx['market_tier']] or '(非A股)',
 'sig': lambda t: t[fIdx['signal']],
 'mkt': lambda t: t[mD] or '(空)',
 'rating': lambda t: t[rD] or t[fIdx['rating']],
 'hsDD': lambda t: ('贴新高≤3%' if (f:=feat_at(str(t[fIdx['buy_date']] or ''))) and f['dd'] is not None and f['dd']>=-0.03 else '回撤3-10%' if f and f['dd'] is not None and f['dd']>=-0.10 else '回撤>10%' if f and f['dd'] is not None else None),
 'hsVol': lambda t: ('vol<15%' if (f:=feat_at(str(t[fIdx['buy_date']] or ''))) and f['vol'] is not None and f['vol']<0.15 else 'vol15-25%' if f and f['vol'] is not None and f['vol']<0.25 else 'vol≥25%' if f and f['vol'] is not None else None),
}
def mk_pred(spec):
    dims=[(DIM[d],v) for d,v in spec]
    def pred(t):
        for fn,v in dims:
            if fn(t)!=v: return False
        return True
    return pred
vals={k:sorted(set(fn(t) for t in k1A if fn(t) is not None)) for k,fn in DIM.items()}
rules=[]
specs=[[(d,v)] for d,vs in vals.items() for v in vs]
pairs=[('tier','sig'),('tier','mkt'),('mkt','sig'),('hsDD','mkt'),('tier','hsVol'),('sig','hsVol'),('hsDD','tier'),('hsDD','sig'),('hsVol','mkt')]
for d1,d2 in pairs:
    specs += [[(d1,v1),(d2,v2)] for v1 in vals[d1] for v2 in vals[d2]]
for spec in specs:
    pred=mk_pred(spec)
    cut=[t for t in k1A if pred(t)]
    years={}
    for t in cut:
        y=(t[fIdx['signal_date']] or '')[:4]; years.setdefault(y,0.0); years[y]+=S.calc_row(t,fIdx)['pnlYuan']
    neg=sum(1 for v in years.values() if v<0)
    c58=pnl([t for t in cut if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900'])
    capr=pnl([t for t in cut if (t[fIdx['signal_date']] or '').startswith('202604')])
    cf=pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4]<='2023'])
    co=pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4]>='2024'])
    name=' & '.join(f'{d}={v}' for d,v in spec)
    rules.append(dict(name=name,n=len(cut),cut_all=pnl(cut),cut_58=c58,cut_apr=capr,
                      neg_years=f'{neg}/{len(years)}',fwd_in=cf,fwd_out=co,
                      passed=bool(len(cut)>=30 and c58<=-2500 and capr>=-1500 and co<=0 and neg/max(len(years),1)>=0.55)))
rules.sort(key=lambda r:r['cut_58'])
OUT['rules_top']=rules[:40]
OUT['rules_passed']=[r['name'] for r in rules if r['passed']]

# ===== 6. 主候选跨模式验证 =====
best_pred=lambda t:(t[fIdx['market_tier']] or '')=='牛市·主升' and t[fIdx['signal']] in ('buy_aux','buy_backup')
cross={}
for mode in 'ABCDEFGHI':
    _,_,k1=build(mode)
    cut=[t for t in k1 if best_pred(t)]
    years={}
    for t in cut:
        y=(t[fIdx['signal_date']] or '')[:4]; years.setdefault(y,0.0); years[y]+=S.calc_row(t,fIdx)['pnlYuan']
    neg=sum(1 for v in years.values() if v<0)
    cross[mode]=dict(cut_all=pnl(cut),cut_58=pnl([t for t in cut if '20260500'<=(t[fIdx['signal_date']] or '')<'20260900']),
                     fwd_out=pnl([t for t in cut if (t[fIdx['signal_date']] or '')[:4]>='2024']),neg_years=f'{neg}/{len(years)}',
                     base_full=pnl(k1))
OUT['candidate_cross_modes']=cross
kept26={}
for t in k1A:
    if not best_pred(t):
        sd=str(t[fIdx['signal_date']] or '')
        if sd.startswith('2026'): kept26.setdefault(sd[:6],[]).append(t)
OUT['after_candidate_2026']={m:pnl(rs) for m,rs in sorted(kept26.items())}
OUT['after_candidate_full']=pnl([t for t in k1A if not best_pred(t)])

with open(os.path.join(HERE,'data/results.json'),'w') as f:
    json.dump(OUT,f,ensure_ascii=False,indent=1,default=float)
print('results.json written:', os.path.join(HERE,'data/results.json'))
print('repro 4/1 k1 cumYuan=', round(repro['20260401']['k1']['cumYuan'],0), '| 5/1 k1 cumYuan=', round(repro['20260501']['k1']['cumYuan'],0))
print('passed rules:', OUT['rules_passed'])
print('after candidate 2026:', {k:round(v) for k,v in OUT['after_candidate_2026'].items()})
print('full hist baseline -> after candidate:', round(pnl(k1A)), '->', round(OUT['after_candidate_full']))
