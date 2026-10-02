# -*- coding: utf-8 -*-
"""阈值漂移分析:2023 原文阈值 vs 2025-26 现市场"""
import pandas as pd
import numpy as np
import json
from bt_core import df

def year_stats(y):
    seg = (df.index >= str(y) + '0101') & (df.index <= str(y) + '1231')
    out = dict([('year', y)])
    for m in ['a_width_zt_count', 'a_width_dt_count', 'a_width_max_lianban']:
        s = df[m][seg].dropna()
        if len(s) == 0:
            out[m + '_p50'] = None; out[m + '_p90'] = None; out[m + '_p10'] = None
        else:
            out[m + '_p50'] = float(s.median())
            out[m + '_p90'] = float(s.quantile(0.9))
            out[m + '_p10'] = float(s.quantile(0.1))
    return out

rows = [year_stats(y) for y in [2021, 2022, 2023, 2024, 2025, 2026]]
yy = pd.DataFrame(rows)
json.dump(rows, open('/tmp/icepoint_bt/drift.json', 'w'), ensure_ascii=False, indent=1)
print(yy.to_string())
