#!/usr/bin/env python3
# 【次日分批挂单】按年分解 (修复版) (2026-08-15)
# 用途: 按 next_date 前4位直接分组(不依赖stats, 修掉ext2的zip错位bug), 每日池G 兜底N=K vs 次日开盘
# 结论: 2011-2026 所有年份兜底相对次日开盘都是正改善, K1 Δ+395~+8,272; 2021年改善最大(+8,272)
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_batch_limit_yearly.py

"""按年分解 (每日池, 兜底 N=K vs 次日开盘) - 修复版: 直接用 items 的 next_date 分组"""
import sys
sys.path.insert(0,'/tmp')
from kelly_batch_limit_engine import run_nextday_open, run_batch, topk_keep, summarize
from collections import defaultdict

YEARS = ['2011','2012','2013','2014','2015','2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026']

for k in [1,2,3]:
    keep = topk_keep('G', k)
    items_o, _ = run_nextday_open('G', keep=keep, F=None)
    byo = defaultdict(list)
    for it in items_o: byo[it[2][:4]].append(it)
    items_b, stats_b = run_batch('G', keep=keep, F=None, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
    byb = defaultdict(list)
    for it in items_b: byb[it[2][:4]].append(it)  # 直接用 next_date, 不依赖 stats
    print(f'--- K={k}: 年 | 次日开盘净 | N={k}兜底净 | Δ | 兜底均价% ---')
    for y in YEARS:
        if y not in byo: continue
        so = summarize(byo[y])
        if y in byb:
            sb = summarize(byb[y])
            print(f'{y}: 开盘{so["net"]:+9.0f} 兜底{sb["net"]:+9.0f} Δ{sb["net"]-so["net"]:+8.0f} 均价{(sb.get("avg_disc",1)-1)*100:+.3f}%')
        else:
            print(f'{y}: 开盘{so["net"]:+9.0f} (无兜底样本)')

