# -*- coding: utf-8 -*-
"""近1年(20250901起)全档位触发与增量统计"""
import pandas as pd
import numpy as np
import json
from bt_core import df, F1_vals, F2_vals, F3_vals, F4_vals, combo_flags

yseg = (df.index >= '20250901') & (df.index <= '20260930')
old_y = (df['value'] < 20) & (df['value'].notna()) & yseg
rows = []
for k1 in F1_vals:
    for k2 in F2_vals:
        for k3 in F3_vals:
            for k4 in F4_vals:
                hard, main, dbl = combo_flags(k1, k2, k3, k4)
                for name, mask in [('hard', hard), ('main', main), ('double', dbl)]:
                    m = mask & yseg
                    n = int(m.sum())
                    ov = int((m & old_y).sum())
                    inc = n - ov
                    rows.append((k1, k2, k3, k4, name, n, ov, inc))

cols = ['k1', 'k2', 'k3', 'k4', 'type', 'n', 'ov', 'inc']
yf = pd.DataFrame(rows, columns=cols)
yf.to_pickle('/tmp/icepoint_bt/year_all.pkl')
print('old_y n =', int(old_y.sum()))
for tp in ['hard', 'main', 'double']:
    s = yf[yf['type'] == tp]
    print('==', tp, '近1年 n in 2..20:')
    print(s[(s['n'] >= 2) & (s['n'] <= 20)].sort_values(['n', 'inc'], ascending=[False, False]).head(12).to_string())
