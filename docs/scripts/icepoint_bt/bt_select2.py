# -*- coding: utf-8 -*-
"""平衡分析: n15-80, 综合 r60 超额 + 短周期 + 增量(1-overlap_rate)"""
import pandas as pd
import numpy as np
import json

ret = pd.read_pickle('/tmp/icepoint_bt/returns_multi.pkl')
bench = json.load(open('/tmp/icepoint_bt/bench_multi.json'))[1]
b = dict()
for ix in [1, 5, 10, 20, 60]:
    for idx in ['hs300', 'csi1000']:
        c = 'r' + str(ix) + '_' + idx
        b[c + '_mean'] = bench[c + '_mean']
        b[c + '_win'] = bench[c + '_win']

def score_row(r):
    n = r['n']
    e60 = r['r60_csi1000_mean'] - b['r60_csi1000_mean']
    e10 = r['r10_csi1000_mean'] - b['r10_csi1000_mean']
    inc = (1 - r['overlap_old'] / n) if n else 0   # 增量占比
    return e60, e10, inc

for tp in ['hard', 'main', 'double']:
    sub = ret[(ret['type'] == tp) & (ret['n'] >= 15) & (ret['n'] <= 80)].copy()
    if len(sub) == 0:
        continue
    sub['e60'] = sub.apply(lambda r: r['r60_csi1000_mean'] - b['r60_csi1000_mean'], axis=1)
    sub['e10'] = sub.apply(lambda r: r['r10_csi1000_mean'] - b['r10_csi1000_mean'], axis=1)
    sub['inc'] = sub.apply(lambda r: 1 - r['overlap_old'] / r['n'] if r['n'] else 0, axis=1)
    sub = sub.sort_values('e60', ascending=False)
    print('==', tp, 'n15-80 按e60排前10 ==')
    cols = ['k1', 'k2', 'k3', 'k4', 'n', 'overlap_old', 'r60_csi1000_mean', 'r60_csi1000_win',
            'r10_csi1000_mean', 'r10_csi1000_win', 'e60', 'e10', 'inc']
    print(sub[cols].head(10).to_string())
