# -*- coding: utf-8 -*-
"""四档凯利接入 - 分周期窗口对比(基线 vs R1_all替换 vs V4d_all新增)
口径: v1.1.0 基准 8键 K=1 每日池等分;G 13万 P≤3d b0 / H hold7万 / I hold15万 / A-F 每日池+top-K
切分: ①四档状态段(按 signal_date 判定,全史)②年度(buy_date[:4])③大阶段(buy_date)
数据: /tmp/ms_bt/signal_kelly_trades_pinned.json(固化 2026-08-17 21:58)+ data/sentiment.db hs300
输出: ../data/results_4tier_period.json + 打印
复现: python3 kelly_4tier_period.py
"""
import sys, os, json
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap, BUY_AMOUNT

__file__ = os.path.abspath(__file__)
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kelly_4tier_main.py')).read().split('if __name__')[0])

BASE8 = dict(AI_MACRO); BASE8_EXCL = set(K2)
excl_r1all = state_excl(("熊市·主跌","下降期"), ("buy_special",), None)
excl_v4d   = state_excl(("下降期",), ("buy_special",), None)
f_r1 = dict(BASE8); f_r1['excludeSpecialBear'] = False

def mode_recomputed_st(m, filters, exclude_keys):
    """同 OpgEngine._mode_recomputed, 每条额外带 st4(signal_date 判定)与 buy_date"""
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
                    'st4': st4_of_date(sd), 'sd': sd})
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
    """返回 {bucket: {mode: stat}}, 桶内净利求和 = 全周期(每条只属一桶)"""
    out = {}
    for bk in buckets:
        out[bk] = {}
        for m in MODES:
            out[bk][m] = mode_stat(m, [t for t in rec[m] if bucket_fn(t) == bk])
    return out

def bucket_sum(d):
    return sum(d[m]['profit'] for m in MODES)

print('构建 rec(基线/R1/V4d)...')
base_rec = build_rec(BASE8, BASE8_EXCL)
r1_rec   = build_rec(f_r1, BASE8_EXCL | excl_r1all)
v4d_rec  = build_rec(BASE8, BASE8_EXCL | excl_v4d)
# 基线复现断言(套 cap 后 9 模式合计 ≈ +910,466)
_full = bucket_stats(base_rec, lambda t: True, [True])
assert abs(bucket_sum(_full[True]) - 910466) < 3000, f'基线未复现 {bucket_sum(_full[True])}'

# ============ 1) 按四档状态段切分(signal_date 判定) ============
STATES = ['牛市·主升','上升期','下降期','熊市·主跌']
s_base = bucket_stats(base_rec, lambda t: t['st4'], STATES)
s_r1   = bucket_stats(r1_rec,   lambda t: t['st4'], STATES)
s_v4d  = bucket_stats(v4d_rec,  lambda t: t['st4'], STATES)
print('\n=== 1) 按四档状态段切分(全史, signal_date 判定; G/H/I 分桶套cap有伪差) ===')
print(f"{'状态段':<8}{'基线合计':>11}{'R1合计':>11}{'V4d合计':>11}{'ΔR1':>9}{'ΔV4d':>9}{'基线A':>9}{'R1A':>9}{'V4dA':>9}{'基线F':>9}{'R1F':>9}{'V4dF':>9}{'基线G':>9}{'R1G':>9}{'V4dG':>9}{'基线H':>9}{'R1H':>9}{'V4dH':>9}{'n基线':>6}")
state_rows = []
for s in STATES:
    b, r, v = s_base[s], s_r1[s], s_v4d[s]
    row = dict(state=s,
        base_sum=bucket_sum(b), r1_sum=bucket_sum(r), v4d_sum=bucket_sum(v),
        baseA=b['A']['profit'], r1A=r['A']['profit'], v4dA=v['A']['profit'],
        baseF=b['F']['profit'], r1F=r['F']['profit'], v4dF=v['F']['profit'],
        baseG=b['G']['profit'], r1G=r['G']['profit'], v4dG=v['G']['profit'],
        baseH=b['H']['profit'], r1H=r['H']['profit'], v4dH=v['H']['profit'],
        n=b['A']['n'])
    state_rows.append(row)
    print(f"{s:<8}{row['base_sum']:>+11,.0f}{row['r1_sum']:>+11,.0f}{row['v4d_sum']:>+11,.0f}{row['r1_sum']-row['base_sum']:>+9,.0f}{row['v4d_sum']-row['base_sum']:>+9,.0f}{row['baseA']:>+9,.0f}{row['r1A']:>+9,.0f}{row['v4dA']:>+9,.0f}{row['baseF']:>+9,.0f}{row['r1F']:>+9,.0f}{row['v4dF']:>+9,.0f}{row['baseG']:>+9,.0f}{row['r1G']:>+9,.0f}{row['v4dG']:>+9,.0f}{row['baseH']:>+9,.0f}{row['r1H']:>+9,.0f}{row['v4dH']:>+9,.0f}{row['n']:>6}")

# ============ 2) 按年度(2016-2026 + ~2015 合并) ============
YEARS = ['2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026']
def year_fn(t):
    y = t['buy_date'][:4] if t['buy_date'] else '?'
    return y
y_base = bucket_stats(base_rec, year_fn, YEARS + ['2011','2012','2013','2014','2015'])
y_r1   = bucket_stats(r1_rec,   year_fn, YEARS + ['2011','2012','2013','2014','2015'])
y_v4d  = bucket_stats(v4d_rec,  year_fn, YEARS + ['2011','2012','2013','2014','2015'])
# 2015 及之前合并为 ~2015
def merge_pre2016(d):
    pre = {'A': dict(n=0,profit=0), 'B': dict(n=0,profit=0), 'C': dict(n=0,profit=0), 'D': dict(n=0,profit=0),
           'E': dict(n=0,profit=0), 'F': dict(n=0,profit=0), 'G': dict(n=0,profit=0), 'H': dict(n=0,profit=0), 'I': dict(n=0,profit=0)}
    for y in ('2011','2012','2013','2014','2015'):
        for m in MODES:
            if y in d: pre[m]['profit'] += d[y][m]['profit']; pre[m]['n'] += d[y][m]['n']
    return pre
pre_base, pre_r1, pre_v4d = merge_pre2016(y_base), merge_pre2016(y_r1), merge_pre2016(y_v4d)
print('\n=== 2) 按年度(基线 vs R1_all vs V4d_all; 2011-2015 合并为 ~2015; G/H/I 分年套cap伪差) ===')
print('  [A 模式按年]')
print(f"{'年份':<8}{'基线':>10}{'R1':>10}{'V4d':>10}{'ΔR1':>9}{'ΔV4d':>9}")
yr_rows = {'A': [], 'G': [], 'H': [], 'I': [], 'SUM': []}
for label, yb, yr, yv in [('~2015', pre_base, pre_r1, pre_v4d)] + [(y, y_base[y], y_r1[y], y_v4d[y]) for y in YEARS]:
    for m in ('A','G','H','I'):
        yr_rows[m].append(dict(y=label, base=yb[m]['profit'], r1=yr[m]['profit'], v4d=yv[m]['profit'],
                               n=yb[m]['n']))
    yr_rows['SUM'].append(dict(y=label, base=bucket_sum(yb), r1=bucket_sum(yr), v4d=bucket_sum(yv), n=yb['A']['n']))
for m in ('A','G','H','I'):
    print(f'  [{m}]')
    for r in yr_rows[m]:
        print(f"    {r['y']:<8}{r['base']:>+10,.0f}{r['r1']:>+10,.0f}{r['v4d']:>+10,.0f}{r['r1']-r['base']:>+9,.0f}{r['v4d']-r['base']:>+9,.0f}")
print('  [合计]')
for r in yr_rows['SUM']:
    print(f"    {r['y']:<8}{r['base']:>+10,.0f}{r['r1']:>+10,.0f}{r['v4d']:>+10,.0f}{r['r1']-r['base']:>+9,.0f}{r['v4d']-r['base']:>+9,.0f}")

# ============ 3) 按大阶段 ============
STAGES = [('2015-2018','20150101','20181231'), ('2019-2021','20190101','20211231'),
          ('2022-2024','20220101','20241231'), ('2025-2026','20250101','20261231')]
def stage_fn(t):
    bd = t['buy_date'] or ''
    for name, ws, we in STAGES:
        if ws <= bd <= we: return name
    return '~2014'
stg_base = bucket_stats(base_rec, stage_fn, [s[0] for s in STAGES] + ['~2014'])
stg_r1   = bucket_stats(r1_rec,   stage_fn, [s[0] for s in STAGES] + ['~2014'])
stg_v4d  = bucket_stats(v4d_rec,  stage_fn, [s[0] for s in STAGES] + ['~2014'])
print('\n=== 3) 按大阶段(9模式合计; G/H/I 分阶段套cap伪差) ===')
print(f"{'阶段':<10}{'基线合计':>11}{'R1合计':>11}{'V4d合计':>11}{'ΔR1':>9}{'ΔV4d':>9}{'n基线':>7}")
stg_rows = []
for name, ws, we in STAGES:
    b, r, v = stg_base[name], stg_r1[name], stg_v4d[name]
    row = dict(stage=name, base=bucket_sum(b), r1=bucket_sum(r), v4d=bucket_sum(v), n=b['A']['n'])
    stg_rows.append(row)
    print(f"{name:<10}{row['base']:>+11,.0f}{row['r1']:>+11,.0f}{row['v4d']:>+11,.0f}{row['r1']-row['base']:>+9,.0f}{row['v4d']-row['base']:>+9,.0f}{row['n']:>7}")

out = dict(generated_at=td.get('generated_at'),
           state=state_rows,
           yearly={'A': yr_rows['A'], 'G': yr_rows['G'], 'H': yr_rows['H'], 'I': yr_rows['I'], 'SUM': yr_rows['SUM']},
           stages=stg_rows)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'results_4tier_period.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print('\n[写盘] ../data/results_4tier_period.json')
