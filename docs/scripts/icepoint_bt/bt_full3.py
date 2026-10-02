# -*- coding: utf-8 -*-
"""全史三因子(不含楼层):档位穷举 + 老算法重叠 + 触发频次"""
import pandas as pd
import numpy as np
from bt_core import df, f4pct, F2_vals, F3_vals, F4_vals

old_all = (df['value'] < 20) & (df['value'].notna())
tot = int((df.index >= '20160115').sum())
rows = []
for k2 in F2_vals:
    for k3 in F3_vals:
        for k4 in F4_vals:
            f2 = df['a_width_zt_count'].le(k2) & df['a_width_zt_count'].notna()
            f3 = df['a_width_dt_count'].ge(k3) & df['a_width_dt_count'].notna()
            f4 = (f4pct <= k4)
            hard = f2 & f3 & f4
            main = (f2 | f3) & f4
            dbl = main & main.shift(1, fill_value=False)
            for name, mask in [('hard', hard), ('main', main), ('double', dbl)]:
                m = mask & (df.index >= '20160115')
                n = int(m.sum())
                ov = int((m & old_all).sum())
                freq = round(n / tot * 100, 2) if n else 0
                ovr = round(ov / n * 100, 1) if n else None
                rows.append((k2, k3, k4, name, n, freq, ov, ovr))

cols = ['k2', 'k3', 'k4', 'type', 'n', 'freq', 'overlap_old', 'overlap_rate']
cf = pd.DataFrame(rows, columns=cols)
cf.to_pickle('/tmp/icepoint_bt/full3.pkl')
print('full3 total', len(cf), 'tot(2016起)', tot)
h = cf[cf['type'] == 'hard'].sort_values('n')
print('hard n>=5 且 <=60:')
print(h[(h['n'] >= 5) & (h['n'] <= 60)].to_string())
m2 = cf[cf['type'] == 'main'].sort_values('n')
print('main n>=30 且 <=150:')
print(m2[(m2['n'] >= 30) & (m2['n'] <= 150)].to_string())
