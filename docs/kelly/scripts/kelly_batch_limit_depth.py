#!/usr/bin/env python3
# 【次日分批挂单】挂单深度敏感性 (2026-08-15)
# 用途: 挂单价=次日开盘-0.5%/-1%/-1.5%/-2%/-3% 对比 (每日池 G, 兜底)
# 结论: -1% 数据最优(净利增量最大); 挂太深(-2%)触达率骤降净利回落; -0.5%触达率虽高但折扣浅净利略低
# 输出: /tmp/kelly_batch_limit_depth.json
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_depth.py

"""挂单深度敏感性: 兜底模式 每日池 K=N, 限价 -0.5%/-1%/-1.5%/-2%"""
import sys, json
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_batch, topk_keep, summarize, run_nextday_open

print('=== 挂单深度敏感性 (每日池, G, 兜底模式, K=N) ===')
res = {}
for k in [1,2,3,4]:
    keep = topk_keep('G', k)
    # 基准 次日开盘
    s0 = summarize(run_nextday_open('G', keep=keep, F=None)[0])
    print(f'K={k} 次日开盘: 净={s0["net"]:+.0f} 收益={s0["ret"]:.2f}% 峰值={s0["peak_capital"]:.0f}')
    for pct, lbl in [(0.005,'-0.5%'),(0.01,'-1%'),(0.015,'-1.5%'),(0.02,'-2%'),(0.03,'-3%')]:
        items, stats = run_batch('G', keep=keep, F=None, N=k, limit_pct=pct, strict=False, fill_source='none', amount_mode='daily_pool')
        s = summarize(items, stats)
        d = s['net'] - s0['net']
        print(f'  {lbl:6s} 兜底: 净={s["net"]:+.0f} (Δ{s["net"]-s0["net"]:+8.0f}) 收益={s["ret"]:.2f}% 峰值={s["peak_capital"]:8.0f} 均价={s.get("avg_disc",1)*100-100:+.3f}% 至少一单触达={s.get("any_touch_rate",0):.1f}%')
        res[f'K{k}_{lbl}'] = s

json.dump({k: {kk: vv for kk, vv in v.items() if isinstance(vv,(int,float))} for k,v in res.items()},
          open('/tmp/kelly_batch_limit_depth.json','w'), indent=1)

