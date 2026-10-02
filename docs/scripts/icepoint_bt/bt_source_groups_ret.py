# -*- coding: utf-8 -*-
"""三源分组收益:仅老算法 / 仅上海炒家 / 重叠(2026-10-02 补跑)

复用 bt_core 的数据加载/F4分位/组合函数/收益函数,不重写第二份实现(§5.4⑦)。
口径(与 icepoint-incremental-backtest-20261002.md §5 完全一致):
  老算法 = score_daily.a_sentiment < 20(回补后口径)
  main  = combo_flags(4,40,15,30)[1]: 楼层≤4 ∧ (涨停≤40 ∨ 跌停≥15) ∧ 地量分位≤30
分组(互斥且完备):
  A 仅老算法 = old ∧ ¬main ; B 仅上海炒家 = main ∧ ¬old ; C 重叠 = old ∧ main
收益: T 日收盘已知判定,T+1 开盘买入,持有 1/3/5/10/20/60 交易日(shift(-1) 开盘价)
窗口: 完整 20210901~20260930; 近1年 20250901~20260930
输出: /tmp/icepoint_bt/source_groups_ret.json + 打印关键表
"""
import pandas as pd
import numpy as np
import json
from bt_core import df, combo_flags, win_metrics_multi

rdf = win_metrics_multi()

def to_series(mask):
    if isinstance(mask, pd.Series):
        return mask
    return pd.Series(mask, index=df.index)

old = (df['value'] < 20) & (df['value'].notna())
hard, main, dbl = combo_flags(4, 40, 15, 30)

wseg = pd.Series((df.index >= '20210901') & (df.index <= '20260930'), index=df.index)
yseg = pd.Series((df.index >= '20250901') & (df.index <= '20260930'), index=df.index)

A = old & (~main)
B = main & (~old)
C = old & main

# ---- 自校验(完整窗口) ----
Aw = A & wseg; Bw = B & wseg; Cw = C & wseg
union_w = (A | B | C) & wseg
nA, nB, nC, nUnion = int(Aw.sum()), int(Bw.sum()), int(Cw.sum()), int(union_w.sum())
assert nA + nB + nC == nUnion, f"互斥完备校验失败 A+B+C={nA+nB+nC} != 并集 {nUnion}"
assert nB == 72, f"B 组(仅上海炒家)应为 72 天,实得 {nB}"

ov = json.load(open('/tmp/icepoint_bt/overlap_window.json'))
main_ov = [o for o in ov if 'main' in o['label']][0]
b_dates = set(Bw.index[Bw])
assert b_dates == set(main_ov['only_new_dates']), "B 组日期与报告增量日清单不一致"

old_w = (old & wseg); main_w = (main & wseg)
cross = dict(old_n=int(old_w.sum()), main_n=int(main_w.sum()),
             both_n=int(Cw.sum()), only_old_n=int(Aw.sum()), only_new_n=int(Bw.sum()))
assert (cross['old_n'], cross['main_n'], cross['both_n'],
        cross['only_old_n'], cross['only_new_n']) == (70, 117, 45, 25, 72), cross

Ay = A & yseg; By = B & yseg; Cy = C & yseg
old_y = old & yseg; main_y = main & yseg
cross_y = dict(old_n=int(old_y.sum()), main_n=int(main_y.sum()),
               both_n=int(Cy.sum()), only_old_n=int(Ay.sum()), only_new_n=int(By.sum()))
assert (cross_y['old_n'], cross_y['main_n'], cross_y['both_n'],
        cross_y['only_old_n'], cross_y['only_new_n']) == (10, 9, 5, 5, 4), cross_y

print('[自校验 PASS] 完整窗口 老70/main117/重叠45/仅老25/仅上海72; 近1年 老10/main9/重叠5/仅老5/仅上海4; B组72天与报告逐位对齐')

# ---- 收益统计 ----
HORIZONS = [1, 5, 10, 20, 60]
IDX = ['csi1000', 'hs300']

def win_stats(s):
    s = s.dropna()
    n = len(s)
    if n == 0:
        return None
    return dict(n=n, mean=round(s.mean(), 3), win=round((s > 0).mean() * 100, 1))

def group_table(mask, rdf_=rdf, horizons=HORIZONS, idxs=IDX):
    sub = rdf_[to_series(mask).fillna(False)]
    out = {}
    for h in horizons:
        out[h] = {}
        for ix in idxs:
            out[h][ix] = win_stats(sub['r%d_%s' % (h, ix)])
    return out

def bench_table(seg):
    sub = rdf[seg.fillna(False)]
    out = {}
    for h in HORIZONS:
        out[h] = {}
        for ix in IDX:
            out[h][ix] = win_stats(sub['r%d_%s' % (h, ix)])
    return out
res = {"cross_window": cross, "cross_year": cross_y}
res = {'cross_window': cross, 'cross_year': cross_y}
seg_full = pd.Series(True, index=df.index)
res['full_window'] = {
    'A_only_old': group_table(Aw),
    'B_only_new': group_table(Bw),
    'C_both': group_table(Cw),
    'bench_all': bench_table(seg_full),
    'bench_window': bench_table(wseg),
}
res['year1'] = {
    'A_only_old': group_table(Ay),
    'B_only_new': group_table(By),
    'C_both': group_table(Cy),
    'bench': bench_table(yseg),
}

# ---- 按年分解(csi1000 r60) ----
def yearly_table(mask, years=('2022', '2023', '2024', '2025', '2026')):
    out = {}
    sub = rdf[to_series(mask).fillna(False)]
    for y in years:
        ys = sub[sub.index.str.startswith(y)]
        s = ys['r60_csi1000']
        out[y] = win_stats(s)
    return out

res['yearly'] = {
    'A_only_old': yearly_table(Aw),
    'B_only_new': yearly_table(Bw),
    'C_both': yearly_table(Cw),
}

# ---- 分半(20240320 中点,csi1000 r60) ----
def half_table(mask):
    sub = rdf[to_series(mask).fillna(False)]
    s = sub['r60_csi1000']
    return {'before_20240320': win_stats(s[s.index < '20240320']),
            'after_20240320': win_stats(s[s.index >= '20240320'])}

res['half'] = {
    'A_only_old': half_table(Aw),
    'B_only_new': half_table(Bw),
    'C_both': half_table(Cw),
}

# ---- 置换检验(重叠 vs 仅老, 重叠 vs 仅上海; 各 horizon) ----
def perm_test(a, b, n_perm=30000, seed=42):
    a = np.asarray(a, float).ravel(); b = np.asarray(b, float).ravel()
    if len(a) == 0 or len(b) == 0:
        return None
    combined = np.concatenate([a, b])
    na = len(a)
    obs = a.mean() - b.mean()
    rng = np.random.default_rng(seed)
    cnt = 0
    for _ in range(n_perm):
        idx = rng.permutation(na + len(b))
        d = combined[idx[:na]].mean() - combined[idx[na:]].mean()
        if abs(d) >= abs(obs):
            cnt += 1
    return round(obs, 3), round((cnt + 1) / (n_perm + 1), 4)

def perm_block(maskX, maskY, seg, horizons=HORIZONS, idx='csi1000'):
    sx = rdf[to_series(maskX & seg).fillna(False)]
    sy = rdf[to_series(maskY & seg).fillna(False)]
    out = {}
    for h in horizons:
        ax = sx['r%d_%s' % (h, idx)].dropna()
        by = sy['r%d_%s' % (h, idx)].dropna()
        out[h] = perm_test(ax, by)
    return out

res['perm_full_window_csi1000'] = {
    'C_both_vs_A_only_old': perm_block(C, A, wseg),
    'C_both_vs_B_only_new': perm_block(C, B, wseg),
    'B_only_new_vs_A_only_old': perm_block(B, A, wseg),
}
res['perm_full_window_hs300'] = {
    'C_both_vs_A_only_old': perm_block(C, A, wseg, idx='hs300'),
}

json.dump(res, open('/tmp/icepoint_bt/source_groups_ret.json', 'w'), ensure_ascii=False, indent=1)

def fmt(st):
    if st is None:
        return 'n/a       '
    return 'n=%d m=%+.3f w=%5.1f%%' % (st['n'], st['mean'], st['win'])

print('=== 完整窗口 csi1000 ===')
for h in HORIZONS:
    row = 'r%-3d | A仅老 %s | B仅上海 %s | C重叠 %s' % (
        h, fmt(res['full_window']['A_only_old'][h]['csi1000']),
        fmt(res['full_window']['B_only_new'][h]['csi1000']),
        fmt(res['full_window']['C_both'][h]['csi1000']))
    print(row)
print('基准(窗口内全部交易日):', {h: res['full_window']['bench_window'][h]['csi1000']['mean'] for h in HORIZONS})
print('基准(全样本):', {h: res['full_window']['bench_all'][h]['csi1000']['mean'] for h in HORIZONS})

print('=== 近1年 csi1000 ===')
for h in HORIZONS:
    row = 'r%-3d | A仅老 %s | B仅上海 %s | C重叠 %s' % (
        h, fmt(res['year1']['A_only_old'][h]['csi1000']),
        fmt(res['year1']['B_only_new'][h]['csi1000']),
        fmt(res['year1']['C_both'][h]['csi1000']))
    print(row)
print('基准(近1年):', {h: res['year1']['bench'][h]['csi1000']['mean'] for h in HORIZONS})

print('=== 按年 r60 csi1000 ===')
for y in ('2022', '2023', '2024', '2025', '2026'):
    print('%s | %s | %s | %s' % (y, fmt(res['yearly']['A_only_old'][y]),
                                 fmt(res['yearly']['B_only_new'][y]), fmt(res['yearly']['C_both'][y])))

print('=== 分半 r60 csi1000(20240320 中点)===')
for segk in ('before_20240320', 'after_20240320'):
    print('%s | %s | %s | %s' % (segk, fmt(res['half']['A_only_old'][segk]),
                                 fmt(res['half']['B_only_new'][segk]), fmt(res['half']['C_both'][segk])))

print('=== 置换检验 p 值(完整窗口 csi1000,obs=前者均值-后者均值)===')
for k, v in res['perm_full_window_csi1000'].items():
    print(k, {h: v[h] for h in HORIZONS})
print('hs300 重叠vs仅老:', res['perm_full_window_hs300']['C_both_vs_A_only_old'])
