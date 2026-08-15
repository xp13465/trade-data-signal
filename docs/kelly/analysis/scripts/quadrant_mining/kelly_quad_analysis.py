# -*- coding: utf-8 -*-
"""凯利象限分析: 16 象限自身净利 + 剔除边际贡献(默认 AI宏7键 + positionCap K1 每日池)"""
import sys, json
sys.path.insert(0, '/tmp')
from kelly_engine import KellyEngine, load_trades, AI_MACRO, FIELDS

QUAD_LABELS = {
    'rating_high': '高评级', 'rating_mid': '中评级', 'rating_low': '低评级',
    'etf_strong': '强关联ETF', 'etf_related': '相关ETF', 'etf_approx': '近似ETF', 'etf_has_track': '有跟踪ETF',
    'sig_main': '主关注', 'sig_aux': '辅关注', 'sig_special': '追关注', 'sig_backup': '备关注',
    'mkt_a': 'A股宽基', 'mkt_hk': '港股', 'mkt_global': '全球/国债', 'mkt_industry': '申万行业', 'mkt_concept': '概念/主题',
}
MODES = ['A','B','C','D','E','F','G','H','I']

td = load_trades()
eng = KellyEngine(td)

def sum_modes(stats_per_mode):
    """9 模式合计净利/样本"""
    n = sum(stats_per_mode[m]['n'] for m in MODES)
    p = sum(stats_per_mode[m]['total_profit'] for m in MODES)
    return n, p

# ========== A. 16 象限自身统计(默认 AI宏 K1 每日池) ==========
print("=" * 110)
print("A. 16 象限自身统计(默认 AI宏7键 + positionCap K1 每日池, 数据 2026-08-15 02:38)")
print("=" * 110)
header = f"{'象限':<10} {'全周期9模式合计净利':>14} {'全周期n':>8} {'y1净利':>12} {'y1 n':>6} | {'A全周期':>12} {'A y1':>10} {'A n':>6} | {'G全周期':>12} {'G y1':>10} {'G n':>6}"
print(header)
print("-" * 110)
results = {}
for qk, label in QUAD_LABELS.items():
    quad_trades = eng._quad_trades[qk]
    stats_all = eng.compute_quad_stats(quad_trades, periods=('all','y1'))
    s_all = stats_all['all']; s_y1 = stats_all['y1']
    n9, p9 = sum_modes(s_all)
    n9y, p9y = sum_modes(s_y1)
    a_all = s_all['A']; a_y1 = s_y1['A']
    g_all = s_all['G']; g_y1 = s_y1['G']
    results[qk] = dict(label=label, p9=p9, n9=n9, p9y=p9y, n9y=n9y,
                       a_all=a_all['total_profit'], a_y1=a_y1['total_profit'], a_n=a_all['n'],
                       g_all=g_all['total_profit'], g_y1=g_y1['total_profit'], g_n=g_all['n'])
    print(f"{label:<10} {p9:>14,.0f} {n9:>8} {p9y:>12,.0f} {n9y:>6} | {a_all['total_profit']:>12,.0f} {a_y1['total_profit']:>10,.0f} {a_all['n']:>6} | {g_all['total_profit']:>12,.0f} {g_y1['total_profit']:>10,.0f} {g_all['n']:>6}")

# ========== B. 剔除象限边际贡献 ==========
print()
print("=" * 110)
print("B. 剔除各象限后全信号(all)的净利/收益率变化(默认 AI宏 K1 每日池, 全周期)")
print("=" * 110)
# 基线: 全信号 all
base_all = eng.compute_quad_stats(eng._all_by_mode, periods=('all',))
base_A = base_all['all']['A']; base_G = base_all['all']['G']
print(f"基线全信号 all: A 净利={base_A['total_profit']:+,.0f} 峰收益率={base_A['return_pct_max_holding']:.2f}% n={base_A['n']} | "
      f"G 净利={base_G['total_profit']:+,.0f} 峰收益率={base_G['return_pct_max_holding']:.2f}% n={base_G['n']}")
print("-" * 110)
print(f"{'剔除象限':<10} {'A净利Δ':>12} {'A净利':>12} {'A收益率':>9} | {'G净利Δ':>12} {'G净利':>12} {'G收益率':>9} | {'剔除n(A)':>8}")
print("-" * 110)

# 各象限的 baseKey 集合
quad_keysets = {}
for qk in QUAD_LABELS:
    keyset = set()
    for mk, arr in eng._quad_trades[qk].items():
        for t in arr:
            keyset.add(eng.base_key(t))
    quad_keysets[qk] = keyset

excl_results = {}
for qk, label in QUAD_LABELS.items():
    excl = quad_keysets[qk]
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=excl, periods=('all',))
    sA = st['all']['A']; sG = st['all']['G']
    dA = sA['total_profit'] - base_A['total_profit']
    dG = sG['total_profit'] - base_G['total_profit']
    excl_results[qk] = dict(label=label, dA=dA, sA=sA, dG=dG, sG=sG)
    print(f"{label:<10} {dA:>+12,.0f} {sA['total_profit']:>12,.0f} {sA['return_pct_max_holding']:>8.2f}% | "
          f"{dG:>+12,.0f} {sG['total_profit']:>12,.0f} {sG['return_pct_max_holding']:>8.2f}% | {sA['n']:>8}")

# 保存结果
out = dict(base_A=base_A, base_G=base_G, quad_self=results, excl=excl_results)
with open('/tmp/kelly_quad_basic.json', 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print("\n已保存 /tmp/kelly_quad_basic.json")
