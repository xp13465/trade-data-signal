# -*- coding: utf-8 -*-
# 【次日分批挂单】空filter口径: 当日收盘 vs 次日开盘 vs 次日分批 三路 P≤3d 完整对照 (2026-08-15)
# 目的: 生成 SOP §六.9 核心表的空filter口径(主表)数据——可操作 G 下三路买入法 P≤3d 对比。
# 结论(@13万): 当日收盘 b0 172.19% > 次日分批N1兜底 170.89% > 次日开盘 157.55%;@20万: 次日分批 152.48% 最优。
# 输入: static-site/data/signal_kelly_trades.json(2026-08-15 02:38)。
# 依赖(同目录): kelly_ghi_g_scan.simulate_custom + exec 加载 kelly_combine_p3d2.py 的 items_* 函数。
# 输出: stdout 空filter G K=1 三路 P≤3d 对照表(@13万/@20万)。
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_p3d_open_ef.py
# 数据版本: 2026-08-15 02:38。
"""空filter口径: 当日收盘 vs 次日开盘 vs 次日分批 三路 P≤3d 完整对照"""
import sys, contextlib, io
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/Users/linhuichen/code/trade/scripts')
with contextlib.redirect_stdout(io.StringIO()):
    from kelly_ghi_g_scan import simulate_custom

exec(open('docs/kelly/scripts/kelly_combine_p3d2.py').read().split('MODE=')[0])
def net(kept): return sum(t[0] for t in kept)

F = None
ic = items_close_1w('G', F, 1)
io_ = items_nextday_open('G', F, 1)
ib = items_nextday_batch('G', F, 1, 0.01)
print('===== 空filter G K=1 三路 P≤3d 对照 =====')
for cap in [130000, 200000]:
    print(f'--- P≤3d cap={cap//10000}万 ---')
    for tag, items in [('当日收盘买', ic), ('次日开盘买', io_), ('次日分批N1兜底', ib)]:
        kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, cap, 'P', 'b0', P_N=3)
        n=net(kept); ret=n/peak*100 if peak else 0
        kept1, peak1, sk1, fo1, na1, td1, fs1, ac1 = simulate_custom(items, cap, 'P', 'b1', P_N=3)
        n1=net(kept1); ret1=n1/peak1*100 if peak1 else 0
        print(f'  {tag}: b0净={n:+9.0f}/{ret:5.2f}% b1净={n1:+9.0f}/{ret1:5.2f}% 峰值={peak:.0f} 强平={fo}')
