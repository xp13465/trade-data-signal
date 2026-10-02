# -*- coding: utf-8 -*-
"""收益验证(多指数):全部组合的 hs300/csi500/csi1000 收益"""
import pandas as pd
import numpy as np
import json
from bt_core import df, sig_date_range, combo_flags, win_metrics_multi

full_win_start, full_win_end = sig_date_range()
rdf = win_metrics_multi()
bench_rows = []
cols_all = rdf.columns
full_mask = (df.index >= full_win_start) & (df.index <= full_win_end)


def to_series(mask):
    if isinstance(mask, pd.Series):
        return mask
    return pd.Series(mask, index=df.index)

def summarize2(rdf, mask, label):
    sub = rdf[to_series(mask).fillna(False)]
    d = dict([('label', label)])
    for c in rdf.columns:
        s = sub[c].dropna()
        d[c + '_n'] = len(s)
        if len(s) > 0:
            d[c + '_mean'] = round(s.mean(), 3)
            d[c + '_med'] = round(s.median(), 3)
            d[c + '_win'] = round((s > 0).mean() * 100, 1)
            d[c + '_worst'] = round(s.min(), 2)
        else:
            d[c + '_mean'] = None
            d[c + '_med'] = None
            d[c + '_win'] = None
            d[c + '_worst'] = None
    return d

summarize2(rdf, pd.Series(True, index=df.index), 'bench_all')
b1 = summarize2(rdf, pd.Series(True, index=df.index), 'bench_all')
b2 = summarize2(rdf, full_mask, 'bench_window')
json.dump([b1, b2], open('/tmp/icepoint_bt/bench_multi.json', 'w'), ensure_ascii=False, indent=1)
print('bench done')

combos_df = pd.read_pickle('/tmp/icepoint_bt/combos.pkl')
rows = []
for _, r in combos_df.iterrows():
    k1 = int(r['k1']); k2 = int(r['k2']); k3 = int(r['k3']); k4 = int(r['k4'])
    hard, main, dbl = combo_flags(k1, k2, k3, k4)
    name = r['type']
    if name == 'hard':
        mask = hard
    elif name == 'main':
        mask = main
    else:
        mask = dbl
    m = mask & (df.index >= full_win_start)
    d = summarize2(rdf, m, 'x')
    row = dict([('k1', k1), ('k2', k2), ('k3', k3), ('k4', k4), ('type', name),
                ('n', int(r['n'])), ('overlap_old', int(r['overlap_old']))])
    for c in rdf.columns:
        row[c + '_n'] = d[c + '_n']
        row[c + '_mean'] = d[c + '_mean']
        row[c + '_med'] = d[c + '_med']
        row[c + '_win'] = d[c + '_win']
        row[c + '_worst'] = d[c + '_worst']
    rows.append(row)
ret_df = pd.DataFrame(rows)
ret_df.to_pickle('/tmp/icepoint_bt/returns_multi.pkl')
print('returns_multi total', len(ret_df))
print('bench_window r10_hs300_mean', b2['r10_hs300_mean'])
