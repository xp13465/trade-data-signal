#!/usr/bin/env python3
# 【次日分批挂单】用户原话版对比 (2026-08-15)
# 用途: run_batch_user(固定top-N额度 + 缺额补挂) 池内补 vs 降级补
# 结论: 池内补≈基础兜底(K1相同, K2略优+2,013); 降级补大幅降低净利(K1 -13.8万, 资金分流到次优品种)
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_user.py

import sys
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_nextday_open, run_batch, run_batch_user, topk_keep, summarize
print('=== 用户原话版 (固定top-N + 缺额补挂 + 兜底) ===')
for k in [1,2,3,4]:
    keep = topk_keep('G', k)
    s_open = summarize(run_nextday_open('G', keep=keep, F=None)[0])
    for fill in ['pool','outside']:
        items, stats = run_batch_user('G', keep=keep, F=None, N=k, limit_pct=0.01, fill_source=fill)
        s = summarize(items, stats)
        print(f'K={k} 用户版{fill:7s}: 净={s["net"]:+9.0f} (Δ{s["net"]-s_open["net"]:+8.0f}) 收益={s["ret"]:5.2f}% 峰值={s["peak_capital"]:9.0f} 均价={(s.get("avg_disc",1)-1)*100:+.3f}% 至少1触达={s.get("any_touch_rate",0):5.1f}% 用满={s.get("fill_rate",100):5.1f}%')
    items, stats = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s = summarize(items, stats)
    print(f'K={k} 兜底N=K     : 净={s["net"]:+9.0f} (Δ{s["net"]-s_open["net"]:+8.0f}) 收益={s["ret"]:5.2f}% 峰值={s["peak_capital"]:9.0f} 均价={(s.get("avg_disc",1)-1)*100:+.3f}% 至少1触达={s.get("any_touch_rate",0):5.1f}% 用满={s.get("fill_rate",100):5.1f}%')

