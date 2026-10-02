# -*- coding: utf-8 -*-
"""档位穷举主逻辑"""
import pandas as pd
import numpy as np
import json
from bt_core import df, F1_vals, F2_vals, F3_vals, F4_vals
from bt_core import sig_date_range, combo_flags

full_win_start, full_win_end = sig_date_range()
old = (df['value'] < 20) & (df['value'].notna()) & (df.index >= full_win_start)
tot_days = int((df.index >= full_win_start).sum())
rows = []

def ev1(k1, k2, k3, k4, name, mask):
    m = mask & (df.index >= full_win_start)
    n = int(m.sum())
    ov = int((m & old).sum())
    freq = round(n / tot_days * 100, 2) if n else 0
    ovr = round(ov / n * 100, 1) if n else None
    return (k1, k2, k3, k4, name, n, freq, ov, ovr)

for k1 in F1_vals:
    for k2 in F2_vals:
        for k3 in F3_vals:
            for k4 in F4_vals:
                hard, main, dbl = combo_flags(k1, k2, k3, k4)
                rows.append(ev1(k1, k2, k3, k4, 'hard', hard))
                rows.append(ev1(k1, k2, k3, k4, 'main', main))
                rows.append(ev1(k1, k2, k3, k4, 'double', dbl))

cols = ['k1', 'k2', 'k3', 'k4', 'type', 'n', 'freq', 'overlap_old', 'overlap_rate']
combos_df = pd.DataFrame(rows, columns=cols)
combos_df.to_pickle('/tmp/icepoint_bt/combos.pkl')
print('combos total', len(combos_df), 'tot_days', tot_days)
print('window', full_win_start, full_win_end)
h = combos_df[combos_df['type'] == 'hard'].sort_values('n')
print('hard 触发最少 6 档:')
print(h.head(6).to_string())
print('hard 触发最多 6 档:')
print(h.sort_values('n', ascending=False).head(6).to_string())
