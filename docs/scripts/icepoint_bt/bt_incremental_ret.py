# -*- coding: utf-8 -*-
"""被补盲区日(仅上海炒家)收益验证 + 各档增量日画像"""
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

old = (df['value'] < 20) & (df['value'].notna())
k1 = 4; k2 = 40; k3 = 15; k4 = 30
hard, main, dbl = combo_flags(k1, k2, k3, k4)
wseg = (df.index >= full_win_start) & (df.index <= full_win_end)

inc_hard = hard & (~old) & wseg
inc_main = main & (~old) & wseg
inc_dbl = dbl & (~old) & wseg

out = []
for label, m in [('hard_only_new', inc_hard), ('main_only_new', inc_main), ('double_only_new', inc_dbl)]:
    sub = rdf[to_series(m).fillna(False)]
    d = dict([('label', label), ('n', int(m.sum()))])
    for ix in [5, 10, 20, 60]:
        for idx in ['hs300', 'csi1000']:
            c = 'r' + str(ix) + '_' + idx
            s = sub[c].dropna()
            if len(s) == 0:
                d[c + '_mean'] = None; d[c + '_win'] = None
            else:
                d[c + '_mean'] = round(s.mean(), 3); d[c + '_win'] = round((s > 0).mean() * 100, 1)
    out.append(d)
json.dump(out, open('/tmp/icepoint_bt/incremental_ret.json', 'w'), ensure_ascii=False, indent=1)
for d in out:
    print(d['label'], 'n=', d['n'],
          'csi1000 r5', d['r5_csi1000_mean'], 'r20', d['r20_csi1000_mean'], 'r60', d['r60_csi1000_mean'], 'win60', d['r60_csi1000_win'])
