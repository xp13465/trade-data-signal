# -*- coding: utf-8 -*-
"""全史三因子收益验证:hard 档关键组合 vs 老算法 vs 基准"""
import pandas as pd
import numpy as np
import json
from bt_core import df, f4pct, win_metrics_multi

def to_series(mask):
    if isinstance(mask, pd.Series):
        return mask
    return pd.Series(mask, index=df.index)

def stats(rdf, mask):
    sub = rdf[to_series(mask).fillna(False)]
    d = dict([('n', int(sub['r60_csi1000'].notna().sum()))])
    for ix in [1, 5, 10, 20, 60]:
        for idx in ['hs300', 'csi1000']:
            c = 'r' + str(ix) + '_' + idx
            s = sub[c].dropna()
            if len(s) == 0:
                d[c + '_mean'] = None
                d[c + '_win'] = None
            else:
                d[c + '_mean'] = round(s.mean(), 3)
                d[c + '_win'] = round((s > 0).mean() * 100, 1)
    return d

rdf = win_metrics_multi()
old_all = (df['value'] < 20) & (df['value'].notna())
all_mask = pd.Series(True, index=df.index)
results = dict()
results['bench_all'] = stats(rdf, all_mask)
results['old_all'] = stats(rdf, old_all)

combos = [(40, 15, 30), (40, 20, 30), (35, 15, 30), (45, 15, 30),
          (40, 15, 25), (40, 15, 35), (30, 20, 30), (50, 20, 25)]
for (k2, k3, k4) in combos:
    f2 = df['a_width_zt_count'].le(k2) & df['a_width_zt_count'].notna()
    f3 = df['a_width_dt_count'].ge(k3) & df['a_width_dt_count'].notna()
    f4 = (f4pct <= k4)
    hard = f2 & f3 & f4
    m = hard & (df.index >= '20160115')
    results['hard_' + str(k2) + '_' + str(k3) + '_' + str(k4)] = stats(rdf, m)
json.dump(results, open('/tmp/icepoint_bt/full3_ret.json', 'w'), ensure_ascii=False, indent=1)
for k, v in results.items():
    print(k, 'n=', v['n'],
          'r60_hs m=', v['r60_hs300_mean'], 'w=', v['r60_hs300_win'],
          'r60_1000 m=', v['r60_csi1000_mean'], 'w=', v['r60_csi1000_win'])
