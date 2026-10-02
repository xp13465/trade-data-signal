# -*- coding: utf-8 -*-
"""候选档完整画像:草案三档 + 2个推荐候选, 各周期收益"""
import pandas as pd
import numpy as np
import json
from bt_core import df, combo_flags, win_metrics_multi

full_win_start, full_win_end = '20210901', '20260930'
rdf = win_metrics_multi()

def to_series(mask):
    if isinstance(mask, pd.Series):
        return mask
    return pd.Series(mask, index=df.index)

def profile(mask, label, seg=None):
    m = to_series(mask).fillna(False)
    if seg is not None:
        m = m & seg
    sub = rdf[m]
    row = dict([('label', label), ('n', int(sub['r60_csi1000'].notna().sum()))])
    for ix in [1, 3, 5, 10, 20, 60]:
        for idx in ['hs300', 'csi1000']:
            c = 'r' + str(ix) + '_' + idx
            s = sub[c].dropna()
            if len(s) == 0:
                row[c + '_n'] = 0; row[c + '_mean'] = None; row[c + '_win'] = None; row[c + '_worst'] = None
            else:
                row[c + '_n'] = len(s); row[c + '_mean'] = round(s.mean(), 3); row[c + '_win'] = round((s > 0).mean() * 100, 1); row[c + '_worst'] = round(s.min(), 2)
    return row

old = (df['value'] < 20) & (df['value'].notna())
k1 = 4; k2 = 40; k3 = 15; k4 = 30
hard, main, dbl = combo_flags(k1, k2, k3, k4)
wseg = pd.Series(True, index=df.index) & (df.index >= full_win_start) & (df.index <= full_win_end)

cands = [('old_w', old), ('hard_w', hard), ('main_w', main), ('double_w', dbl),
         ('hard_5_45_25_35', combo_flags(5, 45, 25, 35)[0]),
         ('double_4_40_25_20', combo_flags(4, 40, 25, 20)[2]),
         ('hard_4_40_10_20', combo_flags(4, 40, 10, 20)[0])]
rows = []
for label, m in cands:
    rows.append(profile(m & wseg, label))
json.dump(rows, open('/tmp/icepoint_bt/profile.json', 'w'), ensure_ascii=False, indent=1)
for r in rows:
    print(r['label'], 'n=', r['n'])
    print('  hs300: r1', r['r1_hs300_mean'], 'r5', r['r5_hs300_mean'], 'r10', r['r10_hs300_mean'],
          'r20', r['r20_hs300_mean'], 'r60', r['r60_hs300_mean'], 'win60', r['r60_hs300_win'])
    print('  csi1000: r1', r['r1_csi1000_mean'], 'r5', r['r5_csi1000_mean'], 'r10', r['r10_csi1000_mean'],
          'r20', r['r20_csi1000_mean'], 'r60', r['r60_csi1000_mean'], 'win60', r['r60_csi1000_win'])

yseg = pd.Series(True, index=df.index) & (df.index >= '20250901') & (df.index <= '20260930')
yrows = []
for label, m in [('old_y', old), ('hard_y', hard), ('main_y', main), ('double_y', dbl),
                 ('hard_5_45_25_35_y', combo_flags(5, 45, 25, 35)[0]),
                 ('hard_4_40_10_20_y', combo_flags(4, 40, 10, 20)[0])]:
    yrows.append(profile(m & yseg, label))
json.dump(yrows, open('/tmp/icepoint_bt/profile_year.json', 'w'), ensure_ascii=False, indent=1)
for r in yrows:
    print(r['label'], 'n=', r['n'])
    print('  hs300: r5', r['r5_hs300_mean'], 'r20', r['r20_hs300_mean'], 'r60', r['r60_hs300_mean'], 'win60', r['r60_hs300_win'])
    print('  csi1000: r5', r['r5_csi1000_mean'], 'r20', r['r20_csi1000_mean'], 'r60', r['r60_csi1000_mean'], 'win60', r['r60_csi1000_win'])
