# -*- coding: utf-8 -*-
# 【次日分批挂单】A/F/G 主矩阵快速验证 (2026-08-15)
# 目的: 将 SOP §四 主矩阵从「仅 G」扩展为 A/F/G 三模式(空filter口径), 并对照 AI宏7键口径。
# 结论: 空filter 下 A 峰值 9万(9倍)、F 峰值 14万(14倍), 天然 ≤20 倍可操作; G 峰值 162-173倍不可操作。
#       参考值(A K1): 次日开盘 +45,706 / 兜底 +104,281 / Δ+58,575 / 收益 115.87% / 峰值9万 / 9倍 / 触达37.4%。
# 输入: static-site/data/signal_kelly_trades.json(2026-08-15 02:38, 基笔7598) + trade-data DB 行情。
# 依赖: docs/kelly/scripts/kelly_batch_limit_engine.py, dailypool_rerun_core.py(同目录)。
# 输出: stdout 三模式 K=1..5 主矩阵表(空filter + AI宏7键两组)。
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_af_matrix_verify.py
# 数据版本: 2026-08-15 02:38 (signal_kelly_trades.json 重新生成批)。
"""A/F/G 主矩阵快速验证: 两种 F 口径对比, 确认 A K1 +104,281/115.87% 对应哪种"""
import sys, contextlib, io
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/Users/linhuichen/code/trade/scripts')
from kelly_batch_limit_engine import run_close, run_nextday_open, run_batch, topk_keep, summarize
from dailypool_rerun_core import DEFAULT_NEW

def show(mode, k, F, lbl):
    keep = topk_keep(mode, k)
    try:
        items, stats = run_batch(mode, keep=keep, F=F, N=k, limit_pct=0.01, strict=False, fill_source='none', amount_mode='daily_pool')
        s = summarize(items, stats)
        items_o, _ = run_nextday_open(mode, keep=keep, F=F, amount_mode='daily_pool')
        so = summarize(items_o)
        print(f'{lbl} {mode} K{k}: 开盘净={so["net"]:+9.0f} 兜底净={s["net"]:+9.0f} Δ={s["net"]-so["net"]:+7.0f} 收益={s["ret"]:6.2f}% 峰值={s["peak_capital"]:8.0f} x{s["peak_capital"]/10000:.0f} 触达={s.get("any_touch_rate",0):.1f}% 均价={s.get("avg_disc",1.0)*100-100:+.3f}%')
    except Exception as e:
        print(f'{lbl} {mode} K{k}: ERROR {e}')

for F, lbl in [(None,'空filter'), (DEFAULT_NEW,'AI宏7键')]:
    for mode in ['A','F','G']:
        for k in [1,2,3,4,5]:
            show(mode, k, F, lbl)
