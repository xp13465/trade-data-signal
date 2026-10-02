# -*- coding: utf-8 -*-
"""全史三因子(2016起)重叠矩阵:老算法 vs 三因子 hard/main"""
import pandas as pd
import numpy as np
import json
from bt_core import df, f4pct

old_all = (df['value'] < 20) & (df['value'].notna())
old_hist = old_all[(old_all.index >= '20160115') & (old_all.index <= '20260930')]

def build(k2, k3, k4):
    f2 = df['a_width_zt_count'].le(k2) & df['a_width_zt_count'].notna()
    f3 = df['a_width_dt_count'].ge(k3) & df['a_width_dt_count'].notna()
    f4 = (f4pct <= k4)
    hard = f2 & f3 & f4
    main = (f2 | f3) & f4
    hard = hard[(hard.index >= '20160115') & (hard.index <= '20260930')]
    main = main[(main.index >= '20160115') & (main.index <= '20260930')]
    return hard, main

def classify(o, n):
    both = o & n
    only_old = o & (~n)
    only_new = n & (~o)
    d = dict([('old_n', int(o.sum())), ('new_n', int(n.sum())),
              ('both_n', int(both.sum())), ('only_old_n', int(only_old.sum())),
              ('only_new_n', int(only_new.sum()))])
    d['only_new_dates'] = [str(x) for x in only_new[only_new].index]
    d['both_dates'] = [str(x) for x in both[both].index]
    return d

for (k2, k3, k4) in [(40, 15, 30), (40, 20, 30), (35, 15, 30)]:
    hard, main = build(k2, k3, k4)
    res = dict([('hard', classify(old_hist, hard)), ('main', classify(old_hist, main))])
    json.dump(res, open('/tmp/icepoint_bt/full3_overlap_' + str(k2) + '_' + str(k3) + '_' + str(k4) + '.json', 'w'), ensure_ascii=False, indent=1)
    print('== 三因子', k2, k3, k4)
    for tp, v in res.items():
        print(' ', tp, 'old', v['old_n'], 'new', v['new_n'], 'both', v['both_n'],
              'only_old', v['only_old_n'], 'only_new', v['only_new_n'])
