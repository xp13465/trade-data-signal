#!/usr/bin/env python3
# 【次日分批挂单】均价平滑度分析 (2026-08-15)
# 结论: 兜底日均价折扣 K2 均值-0.367% 中位0% 标准差0.429% 有折扣天数724/1560;
#       严格模式恒-1%(资金用不满); 完整玩法-0.44~-0.58%
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_smooth.py

"""验证'更平滑': 每日实际买入均价折扣的分布 (兜底 N=K vs 严格 vs 完整)"""
import sys, statistics
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_batch, run_batch_user, run_batch_full, topk_keep, summarize

def daily_discount(items, stats):
    """每天实际买入折扣 = 加权买入折扣 (来自 stats disc_sum/disc_amt)"""
    ds = []
    for st in stats:
        if st['disc_amt'] > 0:
            ds.append(st['disc_sum']/st['disc_amt'] - 1)
    return ds

for k, N in [(1,1),(2,2),(3,3)]:
    keep = topk_keep('G', k)
    # 兜底
    items, stats = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    ds_dd = daily_discount(items, stats)
    # 严格+降级补
    items2, stats2 = run_batch('G', keep=keep, F=None, N=N, limit_pct=0.01, strict=True, fill_source='outside', amount_mode='daily_pool')
    ds_st = daily_discount(items2, stats2)
    # 完整玩法
    items3, stats3 = run_batch_full('G', keep=keep, F=None, N=N, limit_pct=0.01)
    ds_fl = daily_discount(items3, stats3)
    print(f'K={k} N={N}:')
    print(f'  兜底:  日均价折扣 均值={statistics.mean(ds_dd)*100:+.3f}% 中位={statistics.median(ds_dd)*100:+.3f}% 标准差={statistics.pstdev(ds_dd)*100:.3f}% 有折扣天数={sum(1 for d in ds_dd if d<0)}/{len(ds_dd)}')
    print(f'  严格+降级: 日均价折扣 均值={statistics.mean(ds_st)*100:+.3f}% 中位={statistics.median(ds_st)*100:+.3f}% 标准差={statistics.pstdev(ds_st)*100:.3f}%')
    print(f'  完整玩法: 日均价折扣 均值={statistics.mean(ds_fl)*100:+.3f}% 中位={statistics.median(ds_fl)*100:+.3f}% 标准差={statistics.pstdev(ds_fl)*100:.3f}%')

