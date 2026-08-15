# -*- coding: utf-8 -*-
# 【次日分批挂单】结合版 K=1/2/3: 次日分批 × P≤3d, 与 当日收盘/次日开盘 全对比 (2026-08-15)
# 目的: 延伸验证 K=2/3 时「次日分批 × P≤3d」是否仍成立(结论: K 越大自然净差越小, P≤3d 下当日买入仍占优)。
# 输入: static-site/data/signal_kelly_trades.json(2026-08-15 02:38)。
# 依赖(同目录): kelly_ghi_g_scan.simulate_custom + exec 加载 kelly_combine_p3d2.py 的 items_* 函数 + dailypool_rerun_core.compute_scaled。
# 输出: stdout K=1/2/3 无cap净差 + P≤3d @13/@20万 三路对比(AI宏7键口径)。
# 复现: cd /Users/linhuichen/code/trade && python3 docs/kelly/scripts/kelly_combine_k2.py
# 数据版本: 2026-08-15 02:38。
"""结合版 K=1/2/3: 次日分批 × P≤3d, 与 当日收盘/次日开盘 全对比"""
import sys, contextlib, io
sys.path.insert(0,'docs/kelly/scripts'); sys.path.insert(0,'/Users/linhuichen/code/trade/scripts')
with contextlib.redirect_stdout(io.StringIO()):
    from kelly_ghi_g_scan import simulate_custom

exec(open('docs/kelly/scripts/kelly_combine_p3d2.py').read().split('MODE=')[0])
F=DEFAULT_NEW

def net(kept): return sum(t[0] for t in kept)

def run_all(tag, items, cap, P_N=3):
    kept, peak, sk, fo, na, td, fs, ac = simulate_custom(items, cap, 'P', 'b0', P_N=P_N)
    n=net(kept); ret=n/peak*100 if peak else 0
    kept1, peak1, sk1, fo1, na1, td1, fs1, ac1 = simulate_custom(items, cap, 'P', 'b1', P_N=P_N)
    n1=net(kept1); ret1=n1/peak1*100 if peak1 else 0
    print(f'  {tag}: b0净={n:+9.0f}/{ret:5.2f}% b1净={n1:+9.0f}/{ret1:5.2f}% 峰值={peak:.0f} 强平={fo}')

for K in [1,2,3]:
    ic = items_close_1w('G', F, K)
    io_ = items_nextday_open('G', F, K)
    ib = items_nextday_batch('G', F, K, 0.01)
    # 无cap净差(验证增量)
    from dailypool_rerun_core import compute_scaled
    sc = compute_scaled(ic); so = compute_scaled(io_); sb = compute_scaled(ib)
    print(f'\n===== K={K} 无cap: 当日净={sc["net"]:+9.0f} 次日开盘净={so["net"]:+9.0f} 次日分批净={sb["net"]:+9.0f} (分批vs开盘Δ={sb["net"]-so["net"]:+.0f}) =====')
    for cap in [130000, 200000]:
        print(f'--- P≤3d cap={cap//10000}万 ---')
        run_all(f'当日收盘买', ic, cap)
        run_all(f'次日开盘买', io_, cap)
        run_all(f'次日分批N=K兜底', ib, cap)
