# -*- coding: utf-8 -*-
# 【次日分批挂单】结合版 v2: 次日分批挂单买入 × P≤3d (2026-08-15)
# 目的: 生成 SOP §六.9「次日分批 × P≤3d 结合版」核心表(空filter 口径, AI宏7键对照在后)。
# 结论: 可操作 G 下(13万): 当日收盘买 b0 172.19% > 次日分批N1兜底 170.89% > 次日开盘 157.55%。
#       AI宏7键 @13万: 当日 +202,836/156.03%、次日分批 +169,288/130.22%、次日开盘 +155,103/119.31%(宇宙更小 n=1091、强平比例更高)。
# 输入: static-site/data/signal_kelly_trades.json(2026-08-15 02:38)。
# 依赖(同目录): kelly_ghi_g_scan.simulate_custom, kelly_batch_limit_engine.fill_trade, kelly_combo_advice_analysis,
#                kelly_posfilter_backtest, kelly_ksens, dailypool_rerun_core, + scripts/simulate_trade.py。
# 输出: stdout A/B/C 三路(当日收盘/次日开盘/次日分批)× P≤3d run_case 表。
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_combine_p3d2.py
# 数据版本: 2026-08-15 02:38。
"""结合版 v2: 次日分批挂单买入 × P≤3d —— 对齐 g-mode-recheck 口径
宇宙: 先 F(DEFAULT_NEW/AI宏7键) 过滤基笔 -> 按 signal_date 分组 -> 组内 full_sort_key 排序 -> 取 top1
      (与 dailypool_rerun_core.daily_pool_items 完全一致, lab.js 同口径)
买入侧: engine fill_trade 次日分批挂单兜底(N=1, 每日池)
对照: 当日收盘买 / 次日开盘买, 同宇宙
卖出侧: simulate_custom(method='P', P_N=3, cap) / FIFO('B') 对照
"""
import sys, contextlib, io
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/Users/linhuichen/code/trade/scripts')
with contextlib.redirect_stdout(io.StringIO()):
    from kelly_combo_advice_analysis import passes_fade, fIdx, BUY_AMOUNT
    from kelly_posfilter_backtest import get_by_date, base_key, base_signals
    from kelly_ksens import full_sort_key
    from dailypool_rerun_core import DEFAULT_NEW, DAILY
    from kelly_batch_limit_engine import fill_trade, clean_base
    from kelly_ghi_g_scan import simulate_custom

def build_topk_keys(mode, F, K):
    """先F过滤 -> 按signal_date分组 -> 组内排序 -> topK -> 返回 key 集合 (与 daily_pool_items 一致)"""
    bd = get_by_date(mode)
    keys = set()
    day_n = {}
    for sd, rows in bd.items():
        fr = [t for t in rows if (F is None) or passes_fade(t, F)]
        if not fr: continue
        srt = sorted(fr, key=full_sort_key)
        pick = srt[:K] if K else srt
        day_n[sd] = len(pick)
        for t in pick: keys.add(base_key(t))
    return keys, day_n

def items_close_1w(mode, F, K):
    """当日收盘买: profit=记录利润*(amt/BUY_AMOUNT), 每日池"""
    keys, day_n = build_topk_keys(mode, F, K)
    bd = get_by_date(mode)
    items = []
    for sd, rows in bd.items():
        if sd not in day_n: continue
        n = day_n[sd]; amt = DAILY/n if n else 0
        for t in rows:
            if base_key(t) not in keys: continue
            bp = t[fIdx['profit']] or 0; rp = t[fIdx['return_pct']] or 0
            items.append((bp*(amt/BUY_AMOUNT), rp, str(t[fIdx['buy_date']] or ''), str(t[fIdx['sell_date']] or ''), t[fIdx['hold_days']] or 0, amt))
    return items

def items_nextday_batch(mode, F, K, limit_pct=0.01):
    """次日分批挂单兜底(N=K): 对 topK 每笔 fill_trade(兜底), 每笔 amt=10000/K"""
    keys, day_n = build_topk_keys(mode, F, K)
    bd = get_by_date(mode)
    items = []
    for sd, rows in bd.items():
        if sd not in day_n: continue
        n = day_n[sd]
        if n == 0: continue
        amt = DAILY/n
        # 只取 topK 笔, 按排序取前 n
        fr = [t for t in rows if (F is None) or passes_fade(t, F)]
        srt = sorted(fr, key=full_sort_key)[:n]
        for t in srt:
            r = fill_trade(t, amt, limit_pct, False, mode=mode)  # strict=False 兜底
            if r is not None:
                # (profit, rpct, next_date, sell_date, hold, amount, touched, buy_ratio)
                items.append(r[:6])
    return items

def items_nextday_open(mode, F, K):
    """次日开盘直接买: fill_trade(limit=0 → 开盘成交), 每日池"""
    keys, day_n = build_topk_keys(mode, F, K)
    bd = get_by_date(mode)
    items = []
    for sd, rows in bd.items():
        if sd not in day_n: continue
        n = day_n[sd]
        if n == 0: continue
        amt = DAILY/n
        fr = [t for t in rows if (F is None) or passes_fade(t, F)]
        srt = sorted(fr, key=full_sort_key)[:n]
        for t in srt:
            r = fill_trade(t, amt, 0.0, False, mode=mode)
            if r is not None:
                items.append(r[:6])
    return items

def net(kept): return sum(t[0] for t in kept)

def run_case(tag, items, cap, P_N=3):
    print(f'  [{tag}] n={len(items)}')
    for mdl in ['b0','b1']:
        kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, cap, 'P', mdl, P_N=P_N)
        n = net(kept); ret = n/peak*100 if peak else 0
        wins = sum(1 for t in kept if t[0]>0); wr = wins/len(kept)*100 if kept else 0
        print(f'    P≤{P_N}d {mdl}: 净={n:+10.0f} 收益={ret:6.2f}% 峰值={peak:8.0f} x{peak/10000:.0f} 强平={fo} 自然={na} 胜率={wr:.1f}%')
    kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, cap, 'B', 'b0')
    print(f'    FIFO b0:     净={net(kept):+10.0f} 收益={net(kept)/peak*100:6.2f}% 峰值={peak:8.0f} 强平={fo}')

MODE='G'; F=DEFAULT_NEW; K=1

# 0. 口径验证: 当日买入宇宙应复现 dailypool_rerun_core (n=1203, FIFO20b0≈96.24%)
ic = items_close_1w(MODE, F, K)
kept, peak, sk, fo, na, td, fs, ac = simulate_custom(ic, 200000, 'B', 'b0')
print(f'口径验证: 当日买入 n={len(ic)} FIFO20b0 净={net(kept):+.0f} 收益={net(kept)/peak*100:.2f}% (报告 95.66%)')

print('\n########## A. 当日收盘买 × P≤3d (对照 g-mode-recheck) ##########')
for cap in [130000,150000,200000]: run_case('当日收盘买', ic, cap)

io_ = items_nextday_open(MODE, F, K)
print('\n########## B. 次日开盘直接买 × P≤3d ##########')
for cap in [130000,200000]: run_case('次日开盘买', io_, cap)

ib = items_nextday_batch(MODE, F, K)
print('\n########## C. 次日分批挂单兜底 N=1 × P≤3d (本任务核心) ##########')
for cap in [130000,150000,200000]: run_case('次日分批N1兜底', ib, cap)
