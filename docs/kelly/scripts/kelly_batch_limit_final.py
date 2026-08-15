#!/usr/bin/env python3
# 【次日分批挂单】兜底 N=K 完整表 (2026-08-15)
# 结论: K=1 N=1 净+861,375/收益53.17%/峰值162万/均价-0.374%/至少1触达37.4%;
#       K=2 N=2 净+751,937/45.71%; K=3 N=3 净+738,380/43.61%; K=4 N=4 净+725,058/42.24%; K=5 N=5 净+714,439/41.22%
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_final.py

"""最终汇总: 兜底模式 N=K 完整表(含至少一单触达) + 深度表 + 每笔固定对照"""
import sys, json
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_nextday_open, run_batch, topk_keep, summarize, run_close

print('=== 兜底模式 N=K 完整表 (每日池, G, toggle关) ===')
print(f'{"K":<4s}{"N":<3s} {"净利":>9s} {"vs开盘Δ":>9s} {"收益":>6s} {"峰值":>9s} {"回撤":>6s} {"均价":>7s} {"至少1单触达":>8s} {"预算用满":>6s}')
res={}
for k in [1,2,3,4,5]:
    keep = topk_keep('G', k)
    s_open = summarize(run_nextday_open('G', keep=keep, F=None)[0])
    for N in [k]:
        items, stats = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
        s = summarize(items, stats)
        d = s['net'] - s_open['net']
        print(f'K={k} N={N}  {s["net"]:+9.0f} {d:+9.0f} {s["ret"]:5.2f}% {s["peak_capital"]:9.0f} {s["dd_pct"]:5.2f}% {(s.get("avg_disc",1)-1)*100:+.3f}% {s.get("any_touch_rate",0):5.1f}% {s.get("fill_rate",100):5.1f}%')
        res[f'K{k}'] = s
    # 开盘基准
    res[f'K{k}_open'] = s_open

print('\n=== 次日开盘基准 (每日池, G, toggle关) ===')
for k in [1,2,3,4,5]:
    keep = topk_keep('G', k)
    s = summarize(run_nextday_open('G', keep=keep, F=None)[0])
    print(f'K={k} 开盘: n={s["n"]} 净={s["net"]:+.0f} 收益={s["ret"]:.2f}% 峰值={s["peak_capital"]:.0f}')

print('\n=== 收盘基准 (每日池, G, toggle关) ===')
for k in [None,1,2,3,4]:
    keep = topk_keep('G', k)
    s = summarize(run_close('G', keep=keep, F=None)[0])
    print(f'{"买全部" if k is None else "K="+str(k)}: n={s["n"]} 净={s["net"]:+.0f} 收益={s["ret"]:.2f}% 峰值={s["peak_capital"]:.0f}')

json.dump({k:{kk:vv for kk,vv in v.items() if isinstance(vv,(int,float))} for k,v in res.items()},
          open('/tmp/kelly_batch_limit_final.json','w'), indent=1)
print('\n[saved]')

