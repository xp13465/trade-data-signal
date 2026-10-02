# -*- coding: utf-8 -*-
"""防前视时点穿越测试:截断到历史 t 重算 F4 分位,与全量逐位一致"""
import pandas as pd
import numpy as np
import json
from bt_core import df, f4pct

def recompute_f4(trunc_end):
    """截断到 trunc_end 重算 F4 分位"""
    amt = df['a_amount'].loc[:trunc_end]
    p = amt.rolling(120, min_periods=10).rank(pct=True) * 100
    return p

def check(trunc_end):
    sub_full = f4pct.loc[:trunc_end].dropna()
    recom = recompute_f4(trunc_end).dropna()
    common = sub_full.index.intersection(recom.index)
    diff = (sub_full[common] - recom[common]).abs().max()
    return dict([('trunc_end', trunc_end), ('common_n', len(common)),
                 ('max_abs_diff', float(diff)),
                 ('pass', bool(np.allclose(sub_full[common], recom[common], atol=1e-9)))])

results = []
for t in ['20220930', '20231229', '20250630']:
    r = check(t)
    results.append(r)
    print(r)
json.dump(results, open('/tmp/icepoint_bt/lookahead.json', 'w'), ensure_ascii=False, indent=1)
# 顺带验证整段 F4<=30 阈值判定穿越一致(3 截断点)
for t in ['20220930', '20231229', '20250630']:
    sub_full = (f4pct.loc[:t] <= 30)
    recom = (recompute_f4(t) <= 30)
    common = sub_full.dropna().index.intersection(recom.dropna().index)
    agree = (sub_full[common] == recom[common]).mean()
    print(t, 'boolean agree rate', round(float(agree) * 100, 4))
