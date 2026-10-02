# -*- coding: utf-8 -*-
"""三源重叠矩阵:老算法 vs 上海炒家四因子"""
import pandas as pd
import numpy as np
import json
from bt_core import df, f4pct, sig_date_range, combo_flags

full_win_start, full_win_end = sig_date_range()

# 老算法 a_sentiment < 20 (全史)
old_all = (df['value'] < 20) & (df['value'].notna())

# 上海炒家草案: hard(4,40,15,30) 与 main(4,40,15,30)
k1 = 4; k2 = 40; k3 = 15; k4 = 30
hard, main, dbl = combo_flags(k1, k2, k3, k4)

def three_class(oldm, newm, label):
    w = full_win_start
    e = full_win_end
    o = oldm[(oldm.index >= w) & (oldm.index <= e)]
    nn = newm[(newm.index >= w) & (newm.index <= e)]
    both = o & nn
    only_old = o & (~nn)
    only_new = nn & (~o)
    out = dict([('label', label), ('old_n', int(o.sum())), ('new_n', int(nn.sum())),
                ('both_n', int(both.sum())), ('only_old_n', int(only_old.sum())),
                ('only_new_n', int(only_new.sum()))])
    return out

def date_list(mask):
    idx = mask[mask].index
    return [str(x) for x in idx]

def three_class_dates(oldm, newm, label):
    rr = three_class(oldm, newm, label)
    both = oldm & newm
    only_old = oldm & (~newm)
    only_new = newm & (~oldm)
    rr['only_new_dates'] = date_list(only_new)
    rr['only_old_dates'] = date_list(only_old)
    rr['both_dates'] = date_list(both)
    return rr

old_all = (df['value'] < 20) & (df['value'].notna())
k1 = 4; k2 = 40; k3 = 15; k4 = 30
hard, main, dbl = combo_flags(k1, k2, k3, k4)

results = []
results.append(three_class_dates(old_all, hard, 'window_hard_4_40_15_30'))
results.append(three_class_dates(old_all, main, 'window_main_4_40_15_30'))
results.append(three_class_dates(old_all, dbl, 'window_double_4_40_15_30'))
json.dump(results, open('/tmp/icepoint_bt/overlap_window.json', 'w'), ensure_ascii=False, indent=1)
for r in results:
    print(r['label'])
    print('  old', r['old_n'], 'new', r['new_n'], 'both', r['both_n'],
          'only_old', r['only_old_n'], 'only_new', r['only_new_n'])
    print('  only_new:', r['only_new_dates'])

# 近 1 年口径: 20250901 ~ 20260930 (完整窗口尾部一年)
year_start = '20250901'
year_end = '20260930'
old_year = old_all[(old_all.index >= year_start) & (old_all.index <= year_end)]
hard_y = hard[(hard.index >= year_start) & (hard.index <= year_end)]
main_y = main[(main.index >= year_start) & (main.index <= year_end)]
dbl_y = dbl[(dbl.index >= year_start) & (dbl.index <= year_end)]

yres = []
yres.append(three_class_dates(old_year, hard_y, 'year_hard_4_40_15_30'))
yres.append(three_class_dates(old_year, main_y, 'year_main_4_40_15_30'))
yres.append(three_class_dates(old_year, dbl_y, 'year_double_4_40_15_30'))
json.dump(yres, open('/tmp/icepoint_bt/overlap_year.json', 'w'), ensure_ascii=False, indent=1)
for r in yres:
    print(r['label'])
    print('  old', r['old_n'], 'new', r['new_n'], 'both', r['both_n'],
          'only_old', r['only_old_n'], 'only_new', r['only_new_n'])
    print('  only_new:', r['only_new_dates'])

# 全史三因子(不含楼层)重叠: zt<=40, dt>=15, F4<=30
def three_full(k2, k3, k4):
    f2 = df['a_width_zt_count'].le(k2) & df['a_width_zt_count'].notna()
    f3 = df['a_width_dt_count'].ge(k3) & df['a_width_dt_count'].notna()
    f4 = (f4pct <= k4)
    hard3 = f2 & f3 & f4
    main3 = (f2 | f3) & f4
    return hard3, main3

h3, m3 = three_full(40, 15, 30)
r_all = []
r_all.append(three_class_dates(old_all, h3, 'full3_hard_40_15_30'))
r_all.append(three_class_dates(old_all, m3, 'full3_main_40_15_30'))
json.dump(r_all, open('/tmp/icepoint_bt/overlap_full3.json', 'w'), ensure_ascii=False, indent=1)
for r in r_all:
    print(r['label'])
    print('  old', r['old_n'], 'new', r['new_n'], 'both', r['both_n'],
          'only_old', r['only_old_n'], 'only_new', r['only_new_n'])
    print('  only_new n', len(r['only_new_dates']), '前12', r['only_new_dates'][:12])
