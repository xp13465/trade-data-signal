# -*- coding: utf-8 -*-
"""四档凯利接入 - R1_lag 滞后带豁免变体 + 四口径全表对比(基线/R1_all/V4d_all/R1_lag)
口径: v1.1.0 基准 8键 K=1 每日池等分;G 13万 P≤3d b0 / H hold7万 / I hold15万 / A-F 每日池+top-K
R1_lag = R1_all(关excludeSpecialBear, 四档熊+降×buy_special×全市场剔) + 滞后带恢复剔除
         (滞后带=价<MA60且价>MA200 的 A股 buy_special 恢复 MA60 老判定剔除)
数据: /tmp/ms_bt/signal_kelly_trades_pinned.json(固化 2026-08-17 21:58)+ data/sentiment.db hs300
输出: ../data/results_4tier_lagexempt.json + 打印
复现: python3 kelly_4tier_lagexempt.py
"""
import sys, os, json
from collections import defaultdict, Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap, BUY_AMOUNT

__file__ = os.path.abspath(__file__)
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kelly_4tier_main.py')).read().split('if __name__')[0])

BASE8 = dict(AI_MACRO); BASE8_EXCL = set(K2)
excl_r1all = state_excl(("熊市·主跌","下降期"), ("buy_special",), None)
excl_v4d   = state_excl(("下降期",), ("buy_special",), None)
# R1_lag 额外: A股 buy_special 滞后带(MA60熊 且 四档牛/上升期)恢复剔除
lag_extra = mk_excl(lambda a: a['sig']=='buy_special' and a['mkt'] in A_STOCK and a['s60']=='熊' and a['s4'] in ('牛市·主升','上升期'))
excl_r1lag = set(excl_r1all) | set(lag_extra)
f_r1 = dict(BASE8); f_r1['excludeSpecialBear'] = False
print('剔除集 n: R1_all=%d  V4d_all=%d  R1_lag=%d(=四档坏%d+滞后带A股%d)' % (len(excl_r1all), len(excl_v4d), len(excl_r1lag), len(excl_r1all), len(lag_extra)))

def mode_recomputed_st(m, filters, exclude_keys):
    arr = eng._all_by_mode[m]
    pool = eng.collect_base_pool(filters, exclude_keys)
    kept = eng._kept_keys(pool, filters.get('positionCapK', 1)) if filters.get('positionCap') else None
    day_counts = eng._day_counts(kept) if kept else {}
    out = []
    for t in arr:
        if not eng.passes_fade(t, filters): continue
        if exclude_keys and eng.base_key(t) in exclude_keys: continue
        if kept is not None and eng.base_key(t) not in kept: continue
        sd = str(t[fi['signal_date']] or '')
        amt = BUY_AMOUNT / day_counts.get(sd, 1) if day_counts else BUY_AMOUNT
        p, rp, fee = eng.recompute(t, amt)
        out.append({'profit': p, 'return_pct': rp, 'fee_cost': fee,
                    'buy_date': str(t[fi['buy_date']] or ''), 'sell_date': str(t[fi['sell_date']] or ''),
                    'hold_days': t[fi['hold_days']] or 0, 'amount': amt,
                    'st4': st4_of_date(sd), 's60': st60_of_date(sd), 'sd': sd})
    return out

def build_rec(filters, exclude_keys):
    return {m: mode_recomputed_st(m, filters, exclude_keys) for m in MODES}

def mode_stat(m, rp):
    if m == 'G':
        kt, peak = p3d_cap(rp, 130000, model='b0')
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), profit=round(tp*10000)/10000, peak=peak)
    if m in ('H','I'):
        cap = 70000 if m=='H' else 150000
        kt, peak = hold_cap(rp, cap)
        tp = sum(k['profit'] for k in kt)
        return dict(n=len(kt), profit=round(tp*10000)/10000, peak=peak)
    tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in rp]
    st = eng.compute_stats(tuples)
    return dict(n=st['n'], profit=st['total_profit'], peak=st['max_concurrent_capital'])

def bucket_stats(rec, bucket_fn, buckets):
    return {bk: {m: mode_stat(m, [t for t in rec[m] if bucket_fn(t) == bk]) for m in MODES} for bk in buckets}

def bsum(d): return sum(d[m]['profit'] for m in MODES)

print('构建 rec(基线/R1_all/V4d_all/R1_lag)...')
rec = {name: build_rec(f, e) for name, f, e in [
    ('base', BASE8, BASE8_EXCL),
    ('r1',   f_r1, BASE8_EXCL | excl_r1all),
    ('v4d',  BASE8, BASE8_EXCL | excl_v4d),
    ('r1lag', f_r1, BASE8_EXCL | excl_r1lag)]}
# 基线复现断言
_full = bucket_stats(rec['base'], lambda t: True, [True])
assert abs(bsum(_full[True]) - 910466) < 3000, f'基线未复现 {bsum(_full[True])}'

# ============ 1) 四口径 × 9 模式全周期 ============
print('\n=== 1) 四口径 × 9 模式全周期 ===')
f_b = bucket_stats(rec['base'], lambda t: True, [True])[True]
f_r = bucket_stats(rec['r1'],   lambda t: True, [True])[True]
f_v = bucket_stats(rec['v4d'],  lambda t: True, [True])[True]
f_l = bucket_stats(rec['r1lag'],lambda t: True, [True])[True]
print(f"{'模式':<4}{'基线':>11}{'R1_all':>11}{'V4d_all':>11}{'R1_lag':>11}{'ΔR1':>9}{'ΔV4d':>9}{'ΔLag':>9}{'ΔLag-R1':>9}")
rows9 = []
for m in MODES:
    b2, r2, v2, l2 = f_b[m]['profit'], f_r[m]['profit'], f_v[m]['profit'], f_l[m]['profit']
    rows9.append(dict(mode=m, base=b2, r1=r2, v4d=v2, r1lag=l2))
    print(f"{m:<4}{b2:>+11,.0f}{r2:>+11,.0f}{v2:>+11,.0f}{l2:>+11,.0f}{r2-b2:>+9,.0f}{v2-b2:>+9,.0f}{l2-b2:>+9,.0f}{l2-r2:>+9,.0f}")
sbase = sum(r['base'] for r in rows9); sr1 = sum(r['r1'] for r in rows9); sv4d = sum(r['v4d'] for r in rows9); slag = sum(r['r1lag'] for r in rows9)
print(f"{'合计':<4}{sbase:>+11,.0f}{sr1:>+11,.0f}{sv4d:>+11,.0f}{slag:>+11,.0f}{sr1-sbase:>+9,.0f}{sv4d-sbase:>+9,.0f}{slag-sbase:>+9,.0f}{slag-sr1:>+9,.0f}")

# ============ 2) 极端窗口 + 2026 滞后带专项(三口径: 基线/R1_all/R1_lag) ============
WINDOWS = [
    ("2015股灾", "20150601", "20160131"),
    ("2018单边熊", "20180101", "20181231"),
    ("2020疫情闪崩", "20200201", "20200331"),
    ("2022大熊", "20220101", "20221231"),
    ("2024小微盘", "20240101", "20240229"),
]
seen = set(); all_bs = []
for mk in MODES:
    for t in eng._all_by_mode[mk]:
        a = attr_of(t)
        if a['sig'] != 'buy_special' or a['mkt'] not in A_STOCK: continue
        bk = eng.base_key(t)
        if bk in seen: continue
        seen.add(bk); all_bs.append((t, a))
print('\n=== 2) 极端窗口(全史 buy_special×A股 基笔 %d, signal_date 落窗; 窗口内剔除归属三口径) ===' % len(all_bs))
def in_r1lag(t, a):
    """R1_lag 剔除判定(buy_special 且 (四档坏全市场 或 A股滞后带))"""
    if a['sig'] != 'buy_special': return False
    if a['s4'] in ('熊市·主跌','下降期'): return True
    if a['mkt'] in A_STOCK and a['s60']=='熊' and a['s4'] in ('牛市·主升','上升期'): return True
    return False
def in_r1(t, a):
    return a['sig']=='buy_special' and a['s4'] in ('熊市·主跌','下降期')
def in_base(t, a):
    return a['sig']=='buy_special' and a['mkt'] in A_STOCK and a['s60']=='熊'
win_out = []
for wn, ws, we in WINDOWS:
    win = [r for r in all_bs if ws <= str(r[0][fi['signal_date']] or '') <= we]
    c_base = [r for r in win if in_base(r[0], r[1])]
    c_r1   = [r for r in win if in_r1(r[0], r[1])]
    c_lag  = [r for r in win if in_r1lag(r[0], r[1])]
    def net(rs): return round(sum(t[fi['profit']] for t,a in rs),1), len(rs)
    row = dict(name=wn, n=len(win),
               base=net(c_base), r1=net(c_r1), r1lag=net(c_lag))
    win_out.append(row)
    print(f"[{wn}] n={len(win):3d} | 基线剔(MA60熊A股): {row['base'][1]:3d}笔净{row['base'][0]:+9,.1f} | R1_all剔(四档坏全市场): {row['r1'][1]:3d}笔净{row['r1'][0]:+9,.1f} | R1_lag剔(+滞后带): {row['r1lag'][1]:3d}笔净{row['r1lag'][0]:+9,.1f}")

# 2026 滞后带专项
lag26 = [r for r in all_bs if str(r[0][fi['signal_date']] or '').startswith('2026') and r[1]['s60']=='熊' and r[1]['s4'] in ('牛市·主升','上升期')]
lag25 = [r for r in all_bs if str(r[0][fi['signal_date']] or '').startswith('2025') and r[1]['s60']=='熊' and r[1]['s4'] in ('牛市·主升','上升期')]
lag21 = [r for r in all_bs if str(r[0][fi['signal_date']] or '').startswith('2021') and r[1]['s60']=='熊' and r[1]['s4'] in ('牛市·主升','上升期')]
def net(rs): return round(sum(t[fi['profit']] for t,a in rs),1), len(rs)
print('\n2026 滞后带 A股 buy_special(R1_all 放行 / R1_lag 剔回): {} 笔 净 {:+,.1f}'.format(net(lag26)[1], net(lag26)[0]))
closed = [r for r in lag26 if r[0][fi['sell_date']]]
openn = [r for r in lag26 if not r[0][fi['sell_date']]]
print('  已卖出实亏: {} 笔 {:+,.1f} | 未卖出浮亏: {} 笔 {:+,.1f}'.format(len(closed), net(closed)[0], len(openn), net(openn)[0]))
print('牛年滞后带剔回代价(全周期看方向): 2025 {} 笔 净 {:+,.1f} | 2021 {} 笔 净 {:+,.1f}'.format(net(lag25)[1], net(lag25)[0], net(lag21)[1], net(lag21)[0]))

# ============ 3) 分周期: 状态段 / 大阶段 / 年度 ============
STATES = ['牛市·主升','上升期','下降期','熊市·主跌']
s_b = bucket_stats(rec['base'], lambda t: t['st4'], STATES)
s_r1 = bucket_stats(rec['r1'],   lambda t: t['st4'], STATES)
s_v4d = bucket_stats(rec['v4d'], lambda t: t['st4'], STATES)
s_lag = bucket_stats(rec['r1lag'], lambda t: t['st4'], STATES)
print('\n=== 3a) 按四档状态段(9模式合计, 四口径) ===')
print(f"{'状态段':<8}{'基线':>11}{'R1_all':>11}{'V4d_all':>11}{'R1_lag':>11}{'ΔR1':>9}{'ΔV4d':>9}{'ΔLag':>9}{'ΔLag-R1':>9}")
state_rows = []
for s in STATES:
    b, r, v, l = bsum(s_b[s]), bsum(s_r1[s]), bsum(s_v4d[s]), bsum(s_lag[s])
    state_rows.append(dict(state=s, base=b, r1=r, v4d=v, lag=l))
    print(f"{s:<8}{b:>+11,.0f}{r:>+11,.0f}{v:>+11,.0f}{l:>+11,.0f}{r-b:>+9,.0f}{v-b:>+9,.0f}{l-b:>+9,.0f}{l-r:>+9,.0f}")

STAGES = [('2015-2018','20150101','20181231'), ('2019-2021','20190101','20211231'),
          ('2022-2024','20220101','20241231'), ('2025-2026','20250101','20261231')]
def stage_fn(t):
    bd = t['buy_date'] or ''
    for name, ws, we in STAGES:
        if ws <= bd <= we: return name
    return '~2014'
stg_b = bucket_stats(rec['base'], stage_fn, [s[0] for s in STAGES]+['~2014'])
stg_r1 = bucket_stats(rec['r1'], stage_fn, [s[0] for s in STAGES]+['~2014'])
stg_v4d = bucket_stats(rec['v4d'], stage_fn, [s[0] for s in STAGES]+['~2014'])
stg_lag = bucket_stats(rec['r1lag'], stage_fn, [s[0] for s in STAGES]+['~2014'])
print('\n=== 3b) 按大阶段(9模式合计, 四口径) ===')
print(f"{'阶段':<10}{'基线':>11}{'R1_all':>11}{'V4d_all':>11}{'R1_lag':>11}{'ΔR1':>9}{'ΔV4d':>9}{'ΔLag':>9}{'ΔLag-R1':>9}")
stg_rows = []
for name, ws, we in STAGES:
    b, r, v, l = bsum(stg_b[name]), bsum(stg_r1[name]), bsum(stg_v4d[name]), bsum(stg_lag[name])
    stg_rows.append(dict(stage=name, base=b, r1=r, v4d=v, lag=l))
    print(f"{name:<10}{b:>+11,.0f}{r:>+11,.0f}{v:>+11,.0f}{l:>+11,.0f}{r-b:>+9,.0f}{v-b:>+9,.0f}{l-b:>+9,.0f}{l-r:>+9,.0f}")

YEARS = ['2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026']
def year_fn(t): return (t['buy_date'] or '')[:4]
yb = bucket_stats(rec['base'], year_fn, YEARS)
yr1 = bucket_stats(rec['r1'], year_fn, YEARS)
yv4d = bucket_stats(rec['v4d'], year_fn, YEARS)
ylag = bucket_stats(rec['r1lag'], year_fn, YEARS)
print('\n=== 3c) 按年度(合计 + F 模式; 2016 前略, 四口径) ===')
print(f"{'年份':<6}{'基合计':>10}{'R1合计':>10}{'V4d合计':>10}{'Lag合计':>10}{'ΔR1':>9}{'ΔV4d':>9}{'ΔLag':>9}{'ΔLag-R1':>9}{'基F':>9}{'R1F':>9}{'V4dF':>9}{'LagF':>9}")
yr_rows = []
for y in YEARS:
    b, r, v, l = bsum(yb[y]), bsum(yr1[y]), bsum(yv4d[y]), bsum(ylag[y])
    yr_rows.append(dict(year=y, base=b, r1=r, v4d=v, lag=l,
                        baseF=yb[y]['F']['profit'], r1F=yr1[y]['F']['profit'], v4dF=yv4d[y]['F']['profit'], lagF=ylag[y]['F']['profit']))
    print(f"{y:<6}{b:>+10,.0f}{r:>+10,.0f}{v:>+10,.0f}{l:>+10,.0f}{r-b:>+9,.0f}{v-b:>+9,.0f}{l-b:>+9,.0f}{l-r:>+9,.0f}{yr_rows[-1]['baseF']:>+9,.0f}{yr_rows[-1]['r1F']:>+9,.0f}{yr_rows[-1]['v4dF']:>+9,.0f}{yr_rows[-1]['lagF']:>+9,.0f}")

out = dict(generated_at=td.get('generated_at'), excl_n=dict(r1=len(excl_r1all), v4d=len(excl_v4d), r1lag=len(excl_r1lag), lag_extra=len(lag_extra)),
           rows9=rows9, s9=dict(base=sbase, r1=sr1, v4d=sv4d, r1lag=slag),
           windows=win_out,
           lag26=dict(n=net(lag26)[1], net=net(lag26)[0], closed_n=len(closed), closed_net=net(closed)[0], open_n=len(openn), open_net=net(openn)[0]),
           lag_extra_by_year={'2021': dict(n=net(lag21)[1], net=net(lag21)[0]), '2025': dict(n=net(lag25)[1], net=net(lag25)[0])},
           state=state_rows, stages=stg_rows, yearly=yr_rows)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'results_4tier_lagexempt.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print('\n[写盘] ../data/results_4tier_lagexempt.json')
