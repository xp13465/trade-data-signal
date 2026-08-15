#!/usr/bin/env python3
# 【次日分批挂单】扩展1: 每笔固定1万 + 降亏toggle a45+exclBear (2026-08-15)
# 结论: 每笔固定1万 K2兜底净+130.8万但峰值持仓296万=296倍本金(不可操作, 教训L32);
#       toggle a45+exclBear 每日池 K1兜底净+86.3万/收益55.70% (delta vs 次日开盘 +5.4万)
# 输出: /tmp/kelly_batch_limit_ext1.json
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_ext1.py

"""扩展1: 每笔固定1万口径 + 降亏toggle(a45+exclBear) 核心玩法"""
import sys, json
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_close, run_nextday_open, run_batch, topk_keep, summarize, reco_F

def show(label, s):
    print(f'  {label:<30s} n={s["n"]:5d} 净={s["net"]:+10.0f} 收益={s["ret"]:6.2f}% 峰值={s["peak_capital"]:9.0f} 用满={s.get("fill_rate",100):6.1f}% 均价={s.get("avg_disc",1)*100-100:+6.3f}%')
    return s

# ===== 每笔固定 1 万口径 (每日投入 = 挂单数×1万) =====
print('===== 每笔固定 1 万口径 (G, toggle关) =====')
res = {}
for k, lbl in [(1,'K=1'),(2,'K=2'),(3,'K=3')]:
    keep = topk_keep('G', k)
    print(f'--- {lbl} (每笔固定1万) ---')
    s0 = summarize(run_close('G', keep=keep, F=None, amount_mode='fixed_1w')[0]); show('收盘(基准)', s0)
    s1 = summarize(run_nextday_open('G', keep=keep, F=None, amount_mode='fixed_1w')[0]); show('次日开盘直接买', s1)
    res[f'{lbl}_close'] = s0; res[f'{lbl}_open'] = s1
    for N in [1,2,3]:
        for mode_name, strict, fill in [('严格不补','strict','none'),('严格+降级补','strict','outside'),('兜底买入','nodnd','none')]:
            items, stats = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=(strict=='strict'), fill_source=fill, amount_mode='fixed_1w')
            s = summarize(items, stats)
            res[f'{lbl}_N{N}_{mode_name}'] = s
            show(f'N={N} {mode_name}', s)

# ===== toggle a45+exclBear (每日池, 兜底模式, K=N) =====
print('\n===== 每日池 + toggle a45+exclBear (兜底模式, K=N) =====')
F = reco_F()
res2 = {}
for k, lbl in [(1,'K=1'),(2,'K=2'),(3,'K=3')]:
    keep = topk_keep('G', k)
    s0 = summarize(run_nextday_open('G', keep=keep, F=F)[0]); show(f'{lbl} 次日开盘+a45EB', s0)
    res2[f'{lbl}_open'] = s0
    for N in [1,2,3]:
        items, stats = run_batch('G', keep=keep, F=F, N=N, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
        s = summarize(items, stats)
        res2[f'{lbl}_N{N}'] = s
        show(f'{lbl} N={N} 兜底', s)

json.dump({'fixed_1w': {k:{kk:vv for kk,vv in v.items() if isinstance(vv,(int,float))} for k,v in res.items()},
           'daily_pool_a45eb': {k:{kk:vv for kk,vv in v.items() if isinstance(vv,(int,float))} for k,v in res2.items()}},
          open('/tmp/kelly_batch_limit_ext1.json','w'), indent=1)
print('\n[saved]')

