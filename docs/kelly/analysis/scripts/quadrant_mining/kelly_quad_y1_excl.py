# -*- coding: utf-8 -*-
"""y1(近1年)口径剔除边际贡献"""
import sys, json
sys.path.insert(0, '/tmp')
from kelly_engine import KellyEngine, load_trades, AI_MACRO

QUAD_LABELS = {
    'rating_high': '高评级', 'rating_mid': '中评级', 'rating_low': '低评级',
    'etf_strong': '强关联ETF', 'etf_related': '相关ETF', 'etf_approx': '近似ETF', 'etf_has_track': '有跟踪ETF',
    'sig_main': '主关注', 'sig_aux': '辅关注', 'sig_special': '追关注', 'sig_backup': '备关注',
    'mkt_a': 'A股宽基', 'mkt_hk': '港股', 'mkt_global': '全球/国债', 'mkt_industry': '申万行业', 'mkt_concept': '概念/主题',
}
MODES = ['A','B','C','D','E','F','G','H','I']

td = load_trades()
eng = KellyEngine(td)

# 各象限 baseKey 集合
quad_keysets = {}
for qk in QUAD_LABELS:
    keyset = set()
    for mk, arr in eng._quad_trades[qk].items():
        for t in arr:
            keyset.add(eng.base_key(t))
    quad_keysets[qk] = keyset

# y1 基线
base = eng.compute_quad_stats(eng._all_by_mode, periods=('y1',))
bA = base['y1']['A']; bG = base['y1']['G']
b9n = sum(base['y1'][m]['n'] for m in MODES)
b9p = sum(base['y1'][m]['total_profit'] for m in MODES)
print(f"y1 基线 all: A净利={bA['total_profit']:+,.0f} 收益率={bA['return_pct_max_holding']:.2f}% n={bA['n']} | "
      f"G净利={bG['total_profit']:+,.0f} 收益率={bG['return_pct_max_holding']:.2f}% n={bG['n']} | 9模式合计净利={b9p:+,.0f}")
print("-" * 100)
print(f"{'剔除象限':<10} {'A净利Δ':>12} {'A收益率Δ':>10} | {'G净利Δ':>12} {'G收益率Δ':>10} | {'9模式Δ':>12}")
print("-" * 100)
for qk, label in QUAD_LABELS.items():
    excl = quad_keysets[qk]
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=excl, periods=('y1',))
    sA = st['y1']['A']; sG = st['y1']['G']
    n9 = sum(st['y1'][m]['n'] for m in MODES)
    p9 = sum(st['y1'][m]['total_profit'] for m in MODES)
    dA = sA['total_profit'] - bA['total_profit']
    dG = sG['total_profit'] - bG['total_profit']
    d9 = p9 - b9p
    print(f"{label:<10} {dA:>+12,.0f} {sA['return_pct_max_holding']-bA['return_pct_max_holding']:>+10.2f}% | "
          f"{dG:>+12,.0f} {sG['return_pct_max_holding']-bG['return_pct_max_holding']:>+10.2f}% | {d9:>+12,.0f}")

# 用户点名的 4 个象限组合剔除
user_keys = ['etf_approx','etf_has_track','rating_high','mkt_hk']
print()
print("组合剔除(用户点名4象限 = 近似ETF+有跟踪ETF+高评级+港股):")
for combo_name, keys in [('用户4象限', user_keys), ('etf弱跟踪2象限', ['etf_approx','etf_has_track'])]:
    excl = set()
    for k in keys: excl |= quad_keysets[k]
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=excl, periods=('y1','all'))
    for pk in ('y1','all'):
        sA = st[pk]['A']; sG = st[pk]['G']
        b_ = eng.compute_quad_stats(eng._all_by_mode, periods=(pk,))[pk]
        dA = sA['total_profit'] - b_['A']['total_profit']
        dG = sG['total_profit'] - b_['G']['total_profit']
        print(f"  {combo_name} {pk}: A净利 {sA['total_profit']:+,.0f}(Δ{dA:+,.0f}) 收益{sA['return_pct_max_holding']:.2f}% | "
              f"G净利 {sG['total_profit']:+,.0f}(Δ{dG:+,.0f}) 收益{sG['return_pct_max_holding']:.2f}% | 剔除n={sA['n']}")

out = dict(baseline_y1=dict(A=bA, G=bG, n9=b9n, p9=b9p))
with open('/tmp/kelly_quad_y1_excl.json', 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print("saved /tmp/kelly_quad_y1_excl.json")
