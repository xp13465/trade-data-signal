# -*- coding: utf-8 -*-
"""按年分解 + 分半稳定性 + 极端年"""
import pandas as pd
import numpy as np
import json
from bt_core import df, sig_date_range, combo_flags

full_win_start, full_win_end = sig_date_range()
old_all = (df['value'] < 20) & (df['value'].notna())
k1 = 4; k2 = 40; k3 = 15; k4 = 30
hard, main, dbl = combo_flags(k1, k2, k3, k4)

years = sorted(set(x[:4] for x in df.index if x >= full_win_start and x <= full_win_end))
rows = []
for y in years:
    seg = (df.index >= y + '0101') & (df.index <= y + '1231') & (df.index >= full_win_start) & (df.index <= full_win_end)
    rows.append(dict([('year', y),
                      ('old', int(old_all[seg].sum())),
                      ('hard', int(hard[seg].sum())),
                      ('main', int(main[seg].sum())),
                      ('double', int(dbl[seg].sum())),
                      ('hard_both', int((old_all & hard)[seg].sum())),
                      ('hard_only_new', int((hard & (~old_all))[seg].sum()))]))
yr_df = pd.DataFrame(rows)
yr_df.to_pickle('/tmp/icepoint_bt/yearly.pkl')
print(yr_df.to_string())
