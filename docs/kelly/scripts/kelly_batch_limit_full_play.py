#!/usr/bin/env python3
# 【次日分批挂单】完整玩法对比 (2026-08-15)
# 用途: run_batch_full(严格优先-1% + 降级补 + 最终开盘兜底) vs 基础兜底 vs 严格
# 结论: 完整玩法均价更深(-0.44~-0.58%)但净利低于基础兜底(资金从top品种分流到降级品种)
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_full_play.py

"""完整玩法对比: 严格优先+降级补+最终兜底 vs 兜底N=K vs 次日开盘 vs 严格+降级补"""
import sys
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_nextday_open, run_batch, run_batch_full, topk_keep, summarize

print('=== 完整玩法(严格优先-1% + 降级补 + 最终开盘兜底) vs 兜底N=K vs 开盘 ===')
print(f'{"K":<3s}{"玩法":<28s} {"净利":>9s} {"vs开盘Δ":>9s} {"收益":>6s} {"峰值":>9s} {"均价":>7s} {"至少1触达":>7s} {"用满":>5s}')
for k in [1,2,3,4]:
    keep = topk_keep('G', k)
    s_open = summarize(run_nextday_open('G', keep=keep, F=None)[0])
    # 完整玩法 N=K
    items, stats = run_batch_full('G', keep=keep, F=None, N=k, limit_pct=0.01)
    s = summarize(items, stats)
    print(f'K={k} {"完整玩法N=K":<28s} {s["net"]:+9.0f} {s["net"]-s_open["net"]:+9.0f} {s["ret"]:5.2f}% {s["peak_capital"]:9.0f} {(s.get("avg_disc",1)-1)*100:+.3f}% {s.get("any_touch_rate",0):5.1f}% {s.get("fill_rate",100):5.1f}%')
    # 兜底 N=K
    items2, stats2 = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    s2 = summarize(items2, stats2)
    print(f'   {"兜底N=K":<28s} {s2["net"]:+9.0f} {s2["net"]-s_open["net"]:+9.0f} {s2["ret"]:5.2f}% {s2["peak_capital"]:9.0f} {(s2.get("avg_disc",1)-1)*100:+.3f}% {s2.get("any_touch_rate",0):5.1f}% {s2.get("fill_rate",100):5.1f}%')

print()
print('=== 完整玩法 N 敏感性 (K=3, 每日池) ===')
keep = topk_keep('G', 3)
s_open = summarize(run_nextday_open('G', keep=keep, F=None)[0])
for N in [1,2,3]:
    items, stats = run_batch_full('G', keep=keep, F=None, N=N, limit_pct=0.01)
    s = summarize(items, stats)
    print(f'N={N}: 净={s["net"]:+9.0f} (Δ{s["net"]-s_open["net"]:+8.0f}) 收益={s["ret"]:.2f}% 峰值={s["peak_capital"]:.0f} 均价={(s.get("avg_disc",1)-1)*100:+.3f}% 至少1触达={s.get("any_touch_rate",0):.1f}% 用满={s.get("fill_rate",100):.1f}%')

print()
print('=== 完整玩法 挂单深度敏感性 (K=2, 每日池) ===')
keep = topk_keep('G', 2)
s_open = summarize(run_nextday_open('G', keep=keep, F=None)[0])
for pct, lbl in [(0.005,'-0.5%'),(0.01,'-1%'),(0.015,'-1.5%'),(0.02,'-2%')]:
    items, stats = run_batch_full('G', keep=keep, F=None, N=2, limit_pct=pct)
    s = summarize(items, stats)
    print(f'{lbl}: 净={s["net"]:+9.0f} (Δ{s["net"]-s_open["net"]:+8.0f}) 收益={s["ret"]:.2f}% 均价={(s.get("avg_disc",1)-1)*100:+.3f}% 至少1触达={s.get("any_touch_rate",0):.1f}%')

