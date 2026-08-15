#!/usr/bin/env python3
# 【次日分批挂单】主矩阵 (2026-08-15)
# 用途: 穷举 K=买全部/1/2/3/4 × N=1/2/3 × (严格不补/严格+池内补/严格+降级补/兜底) 全矩阵
# 结论: 兜底模式(N=K)净利最高; 严格模式资金用不满(36-57%)净利大幅落后; 降级补资金分流到次优品种净利更低
# 输出: /tmp/kelly_batch_limit_matrix.json
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_matrix.py

"""分批挂单玩法 核心矩阵 (每日池, G模式, toggle关)"""
import sys, json
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import (run_close, run_nextday_open, run_batch, topk_keep,
    summarize, reco_F, empty_filters)

def show(label, s):
    print(f'  {label:<34s} n={s["n"]:5d} 净={s["net"]:+9.0f} 收益={s["ret"]:6.2f}% 峰值={s["peak_capital"]:8.0f} 回撤={s["dd_pct"]:5.2f}% 用满={s.get("fill_rate",100):6.1f}% 触达={s.get("touch_rate",100):5.1f}% 均价={s.get("avg_disc",1.0)*100-100:+6.2f}%')
    return s

results = {}
for k, lbl in [(None,'买全部'),(1,'K=1'),(2,'K=2'),(3,'K=3'),(4,'K=4')]:
    keep = topk_keep('G', k)
    print(f'\n===== {lbl} (每日池, G, toggle关) =====')
    # 基准
    s0 = summarize(run_close('G', keep=keep, F=None)[0]); show('收盘(基准)', s0)
    s1 = summarize(run_nextday_open('G', keep=keep, F=None)[0]); show('次日开盘直接买', s1)
    results[f'{lbl}_close'] = s0
    results[f'{lbl}_open'] = s1
    # 玩法: N=1..3
    for N in [1,2,3]:
        for mode_name, strict, fill in [('严格不补','strict','none'), ('严格+池内补','strict','pool'), ('严格+降级补','strict','outside'), ('兜底买入','nodnd','none')]:
            strict_bool = (strict=='strict')
            items, stats = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=strict_bool, fill_source=fill, amount_mode='daily_pool')
            s = summarize(items, stats)
            key = f'{lbl}_N{N}_{mode_name}'
            results[key] = s
            show(f'N={N} {mode_name}', s)

json.dump({k: {kk: vv for kk, vv in v.items() if isinstance(vv,(int,float))} for k,v in results.items()},
          open('/tmp/kelly_batch_limit_matrix.json','w'), indent=1)
print('\n[saved /tmp/kelly_batch_limit_matrix.json]')

