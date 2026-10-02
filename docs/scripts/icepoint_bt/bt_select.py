# -*- coding: utf-8 -*-
"""推荐档位筛选:频率 8-60 天窗口 + r60csi1000 超额 + 稳定"""
import pandas as pd
import numpy as np
import json

ret = pd.read_pickle('/tmp/icepoint_bt/returns_multi.pkl')
combos = pd.read_pickle('/tmp/icepoint_bt/combos.pkl')
bench = json.load(open('/tmp/icepoint_bt/bench_multi.json'))[1]
b60 = bench['r60_csi1000_mean']  # 0.69

# hard 档,窗口触发 8~80 天
h = ret[(ret['type'] == 'hard') & (ret['n'] >= 8) & (ret['n'] <= 80)].copy()
h['excess60'] = h['r60_csi1000_mean'] - b60
h = h.sort_values('excess60', ascending=False)
print('hard 档 n8-80 按 r60_csi1000 超额排序 top15:')
cols = ['k1', 'k2', 'k3', 'k4', 'n', 'overlap_old',
        'r60_csi1000_mean', 'r60_csi1000_win', 'excess60']
print(h[cols].head(15).to_string())
