#!/usr/bin/env python3
# 【次日分批挂单】综合汇总 (权威数据源) (2026-08-15)
# 用途: 汇总 dailypool_fallback_NK/Nsens/depth_sens/strict/user_play/fixed_1w/toggle_a45eb/9mode 全部关键数据
# 输出: docs/kelly/position/data/kelly_nextday_batch_limit_data.json (报告引用数据源)
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_all.py

import sys, json
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import *
from kelly_posfilter_backtest import base_key
from kelly_combo_advice_analysis import fIdx
from collections import defaultdict
R = {}
R['dailypool_fallback_NK'] = {}
for k in [1,2,3,4,5]:
    keep = topk_keep('G', k)
    s_o = summarize(run_nextday_open('G', keep=keep, F=None)[0])
    items, stats = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s = summarize(items, stats)
    R['dailypool_fallback_NK'][f'K{k}'] = dict(open_net=s_o['net'], fallback_net=s['net'], delta=s['net']-s_o['net'], ret=s['ret'], peak=s['peak_capital'], dd=s['dd_pct'], avg_disc=(s['avg_disc']-1)*100, any_touch=s['any_touch_rate'], fill=s['fill_rate'], n=s['n'])
R['dailypool_fallback_Nsens'] = {}
keep = topk_keep('G', 3)
for N in [1,2,3]:
    items, stats = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s = summarize(items, stats)
    R['dailypool_fallback_Nsens'][f'N{N}'] = dict(net=s['net'], ret=s['ret'], peak=s['peak_capital'], avg_disc=(s['avg_disc']-1)*100, any_touch=s['any_touch_rate'])
R['depth_sens'] = {}
for k in [1,2,3]:
    keep = topk_keep('G', k)
    for pct, lbl in [(0.005,'m05'),(0.01,'m1'),(0.015,'m15'),(0.02,'m2')]:
        items, stats = run_batch('G', keep=keep, F=None, N=k, limit_pct=pct, strict=False, fill_source='none', amount_mode='daily_pool')
        s = summarize(items, stats)
        R['depth_sens'][f'K{k}_{lbl}'] = dict(net=s['net'], ret=s['ret'], avg_disc=(s['avg_disc']-1)*100, any_touch=s['any_touch_rate'])
R['strict'] = {}
for k in [1,2,3]:
    keep = topk_keep('G', k)
    for N in [1,2,3]:
        for fill in ['none','pool','outside']:
            items, stats = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=True, fill_source=fill, amount_mode='daily_pool')
            s = summarize(items, stats)
            R['strict'][f'K{k}_N{N}_{fill}'] = dict(net=s['net'], ret=s['ret'], fill=s['fill_rate'], avg_disc=(s['avg_disc']-1)*100)
R['user_play'] = {}
for k in [1,2,3,4]:
    keep = topk_keep('G', k)
    for fill in ['pool','outside']:
        items, stats = run_batch_user('G', keep=keep, F=None, N=k, limit_pct=0.01, fill_source=fill)
        s = summarize(items, stats)
        R['user_play'][f'K{k}_{fill}'] = dict(net=s['net'], ret=s['ret'], peak=s['peak_capital'], avg_disc=(s['avg_disc']-1)*100, any_touch=s['any_touch_rate'])
R['fixed_1w'] = {}
for k in [1,2,3]:
    keep = topk_keep('G', k)
    s_o = summarize(run_nextday_open('G', keep=keep, F=None, amount_mode='fixed_1w')[0])
    items, stats = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='fixed_1w')
    s = summarize(items, stats)
    R['fixed_1w'][f'K{k}'] = dict(open_net=s_o['net'], fallback_net=s['net'], delta=s['net']-s_o['net'], ret=s['ret'], peak=s['peak_capital'])
F = reco_F()
R['toggle_a45eb'] = {}
for k in [1,2,3]:
    keep = topk_keep('G', k)
    s_o = summarize(run_nextday_open('G', keep=keep, F=F)[0])
    items, stats = run_batch('G', keep=keep, F=F, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s = summarize(items, stats)
    R['toggle_a45eb'][f'K{k}'] = dict(open_net=s_o['net'], fallback_net=s['net'], delta=s['net']-s_o['net'], ret=s['ret'], peak=s['peak_capital'])
R['9mode'] = {}
for m in ['A','B','C','D','E','F','G','H','I']:
    s_c = summarize(run_close(m, keep=None, F=None)[0])
    s_o = summarize(run_nextday_open(m, keep=None, F=None)[0])
    items, stats = run_batch(m, keep=None, F=None, N=3, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s = summarize(items, stats)
    R['9mode'][m] = dict(close=s_c['net'], open=s_o['net'], fb3=s['net'], delta=s['net']-s_o['net'], ret=s['ret'])
json.dump(R, open('/tmp/kelly_batch_all.json','w'), indent=1, ensure_ascii=False)
print('saved /tmp/kelly_batch_all.json')
for k in ['K1','K2','K3','K4']:
    v = R['dailypool_fallback_NK'][k]
    print(k, 'delta', v['delta'], 'ret', v['ret'], 'avg_disc', v['avg_disc'], 'any_touch', v['any_touch'])

