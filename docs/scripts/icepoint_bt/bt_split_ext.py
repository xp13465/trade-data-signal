# -*- coding: utf-8 -*-
"""分半稳定性 + 极端年专项(收益r60)"""
import pandas as pd
import numpy as np
import json
from bt_core import df, sig_date_range, combo_flags, win_metrics_multi

full_win_start, full_win_end = sig_date_range()
dts = [x for x in df.index if x >= full_win_start and x <= full_win_end]
n = len(dts)
half = dts[n // 2]
print('window', full_win_start, full_win_end, 'n', n, 'half_point', half)

rdf = win_metrics_multi()
k1 = 4; k2 = 40; k3 = 15; k4 = 30
hard, main, dbl = combo_flags(k1, k2, k3, k4)

def to_series(mask):
    if isinstance(mask, pd.Series):
        return mask
    return pd.Series(mask, index=df.index)

def r60_stats(mask, seg):
    sub = rdf['r60_csi1000'][to_series(mask).fillna(False) & seg]
    s = sub.dropna()
    if len(s) == 0:
        return None
    return dict([('n', len(s)), ('mean', round(s.mean(), 3)),
                 ('win', round((s > 0).mean() * 100, 1))])

half_mask = pd.Series(True, index=df.index) & (df.index < half)
half2_mask = pd.Series(True, index=df.index) & (df.index >= half)
res = {}
for name, mask in [('hard', hard), ('main', main), ('double', dbl)]:
    res[name + '_h1'] = r60_stats(mask, half_mask)
    res[name + '_h2'] = r60_stats(mask, half2_mask)
json.dump(res, open('/tmp/icepoint_bt/split60.json', 'w'), ensure_ascii=False, indent=1)
print('split r60 csi1000:')
for k, v in res.items():
    print(' ', k, v)

ext = {}
for y in ['2022', '2023', '2024', '2025', '2026']:
    seg = pd.Series(True, index=df.index) & (df.index >= y + '0101') & (df.index <= y + '1231')
    ext[y + '_hard'] = r60_stats(hard, seg)
    ext[y + '_main'] = r60_stats(main, seg)
    ext[y + '_old'] = r60_stats((df['value'] < 20) & (df['value'].notna()), seg)
json.dump(ext, open('/tmp/icepoint_bt/extreme_year.json', 'w'), ensure_ascii=False, indent=1)
print('extreme year r60 csi1000:')
for k, v in ext.items():
    print(' ', k, v)
