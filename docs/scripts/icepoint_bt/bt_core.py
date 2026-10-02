# -*- coding: utf-8 -*-
"""四因子冰点回测:纯定义模块(无顶层副作用)"""
import pandas as pd
import numpy as np
import json

df = pd.read_pickle('/tmp/icepoint_bt/merged.pkl')
amt = df['a_amount']
f4pct = amt.rolling(120, min_periods=10).rank(pct=True) * 100
df['f4pct'] = f4pct

F1_vals = [2, 3, 4, 5]
F2_vals = [30, 35, 40, 45, 50]
F3_vals = [10, 15, 20, 25]
F4_vals = [20, 25, 30, 35, 40]

def sig_date_range():
    return df['a_width_max_lianban'].dropna().index.min(), df['a_width_max_lianban'].dropna().index.max()

def combo_flags(k1, k2, k3, k4):
    f1 = df['a_width_max_lianban'].le(k1) & df['a_width_max_lianban'].notna()
    f2 = df['a_width_zt_count'].le(k2) & df['a_width_zt_count'].notna()
    f3 = df['a_width_dt_count'].ge(k3) & df['a_width_dt_count'].notna()
    f4 = (f4pct <= k4)
    hard = f1 & f2 & f3 & f4
    main = f1 & (f2 | f3) & f4
    double = main & main.shift(1, fill_value=False)
    return hard, main, double

def win_metrics_offline(horizon_list=(1, 3, 5, 10, 20, 60)):
    res = {}
    for ix in horizon_list:
        buy = df['open_hs300'].shift(-1)
        sell = df['close_hs300'].shift(-(ix + 1))
        res['r' + str(ix)] = (sell / buy - 1) * 100
    return pd.DataFrame(res, index=df.index)

def summarize_returns(rdf, mask, label, out):
    sub = rdf[mask.fillna(False)]
    d = dict([('label', label)])
    for c in rdf.columns:
        s = sub[c].dropna()
        d[c + '_n'] = len(s)
        if len(s) > 0:
            d[c + '_mean'] = round(s.mean(), 3)
            d[c + '_med'] = round(s.median(), 3)
            d[c + '_win'] = round((s > 0).mean() * 100, 1)
            d[c + '_worst'] = round(s.min(), 2)
        else:
            d[c + '_mean'] = None
            d[c + '_med'] = None
            d[c + '_win'] = None
            d[c + '_worst'] = None
    out.append(d)

IDX_LIST = ['hs300', 'csi500', 'csi1000']

def win_metrics_multi(horizon_list=(1, 3, 5, 10, 20, 60)):
    """多指数: T日信号 -> T+1 开盘买 -> T+ix 收盘卖, 列 r{ix}_{idx}"""
    res = {}
    for ix in horizon_list:
        for idx in IDX_LIST:
            buy = df['open_' + idx].shift(-1)
            sell = df['close_' + idx].shift(-(ix + 1))
            res['r' + str(ix) + '_' + idx] = (sell / buy - 1) * 100
    return pd.DataFrame(res, index=df.index)
