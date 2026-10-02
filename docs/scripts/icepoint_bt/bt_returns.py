# -*- coding: utf-8 -*-
"""收益验证:全组合(1200)收益统计 + 基准对照"""
import pandas as pd
import numpy as np
import json
from bt_core import df, F1_vals, F2_vals, F3_vals, F4_vals
from bt_core import sig_date_range, combo_flags, win_metrics_offline, summarize_returns

full_win_start, full_win_end = sig_date_range()
old = (df['value'] < 20) & (df['value'].notna()) & (df.index >= full_win_start)
tot_days = int((df.index >= full_win_start).sum())

rdf = win_metrics_offline()
bench_rows = []
summarize_returns(rdf, pd.Series(True, index=df.index), 'bench_all', bench_rows)
full_mask = pd.Series(True, index=df.index) & (df.index >= full_win_start) & (df.index <= full_win_end)
summarize_returns(rdf, full_mask, 'bench_window', bench_rows)
json.dump(bench_rows, open('/tmp/icepoint_bt/bench.json', 'w'), ensure_ascii=False, indent=1)

combos_df = pd.read_pickle('/tmp/icepoint_bt/combos.pkl')
rows = []
for _, r in combos_df.iterrows():
    k1 = int(r['k1']); k2 = int(r['k2']); k3 = int(r['k3']); k4 = int(r['k4'])
    hard, main, dbl = combo_flags(k1, k2, k3, k4)
    name = r['type']
    if name == 'hard':
        mask = hard
    elif name == 'main':
        mask = main
    else:
        mask = dbl
    m = mask & (df.index >= full_win_start)
    stats = []
    summarize_returns(rdf, m, 'x', stats)
    s = stats[0]
    row = dict([('k1', k1), ('k2', k2), ('k3', k3), ('k4', k4), ('type', name),
                ('n', int(r['n'])), ('overlap_old', int(r['overlap_old']))])
    for c in rdf.columns:
        row[c + '_n'] = s[c + '_n']
        row[c + '_mean'] = s[c + '_mean']
        row[c + '_med'] = s[c + '_med']
        row[c + '_win'] = s[c + '_win']
        row[c + '_worst'] = s[c + '_worst']
    rows.append(row)

ret_df = pd.DataFrame(rows)
ret_df.to_pickle('/tmp/icepoint_bt/returns.pkl')
print('returns total', len(ret_df))
print('bench', json.dumps(bench_rows, ensure_ascii=False))
# 草案档 F1=4 F2=40 F3=15 F4=30
draft = ret_df[(ret_df['type'] == 'hard') & (ret_df['k1'] == 4) & (ret_df['k2'] == 40) & (ret_df['k3'] == 15) & (ret_df['k4'] == 30)]
print('DRAFT hard(4,40,15,30):')
print(draft.to_string())
draftm = ret_df[(ret_df['type'] == 'main') & (ret_df['k1'] == 4) & (ret_df['k2'] == 40) & (ret_df['k3'] == 15) & (ret_df['k4'] == 30)]
print('DRAFT main(4,40,15,30):')
print(draftm.to_string())
