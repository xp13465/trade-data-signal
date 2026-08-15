# -*- coding: utf-8 -*-
"""全维度子群扫描: 找亏损/负边际子群(2.0挖掘核心)
口径: 子群自身净利 = 该子群交易在 AI宏7键+positionCap K1 每日池下的保留交易净利(与卡片同口径)
对每个候选子群再算剔除边际(重跑全信号 positionCap)
"""
import sys, json, itertools
sys.path.insert(0, '/tmp')
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from collections import defaultdict

MODES = ['A','B','C','D','E','F','G','H','I']
MKT_LABELS = {'a':'A股宽基','hk':'港股','global':'全球/国债','industry':'申万行业','concept':'概念/主题'}
SIG_LABELS = {'buy':'主关注','buy_aux':'辅关注','buy_special':'追关注','buy_backup':'备关注'}
ETF_LABELS = {'strong':'强关联','related':'相关','approx':'近似','none':'无/弱跟踪'}
RAT_LABELS = {'high':'高评级','mid':'中评级','low':'低评级'}

td = load_trades()
eng = KellyEngine(td)
fi = eng.fIdx

def trade_attrs(t):
    """返回 (signal, etf_tier, rating, market, month, year)"""
    dk = eng._dim_key(t)
    mkt = eng._dims.get(dk, {}).get('mkt', '')
    return (str(t[fi['signal']] or ''), str(t[fi['track_tier']] or ''), str(t[fi['rating']] or ''),
            mkt, str(t[fi['buy_date']] or '')[4:6], str(t[fi['buy_date']] or '')[0:4])

# 预处理全信号各模式交易的属性缓存(仅 A 模式全周期用于子群自身净利)
attr_cache = {}
def attr_of(t):
    bk = eng.base_key(t)
    if bk not in attr_cache:
        attr_cache[bk] = trade_attrs(t)
    return attr_cache[bk]

def subgroup_stats(all_trades, pred, period='all', exclude_keys=None):
    """在 AI宏+poscapK1 下, 筛 pred(t) 的子群净利"""
    # 复用 compute_quad_stats 但传入自定义交易集合
    # 构造一个假的 quad 结构
    quad_trades = {mk: [t for t in all_trades if pred(t)] for mk in MODES}
    st = eng.compute_quad_stats(quad_trades, exclude_keys=exclude_keys, periods=(period,))
    return st[period]

def subgroup_profit_self(pred, period='all'):
    """子群自身净利: 9模式合计"""
    quad_trades = {mk: [t for t in eng._all_by_mode[mk] if pred(t)] for mk in MODES}
    st = eng.compute_quad_stats(quad_trades, periods=(period,))
    n9 = sum(st[period][m]['n'] for m in MODES)
    p9 = sum(st[period][m]['total_profit'] for m in MODES)
    return n9, p9

# ========== 1. 单维度分解(y1 + all) ==========
print("=" * 100)
print("1. 单维度子群自身净利(AI宏 K1 每日池, 9模式合计)")
print("=" * 100)
dims = {
    '信号类型': lambda a: SIG_LABELS.get(a[0], a[0]),
    'ETF属性': lambda a: ETF_LABELS.get(a[1], a[1]),
    '评级': lambda a: RAT_LABELS.get(a[2], a[2]),
    '市场': lambda a: MKT_LABELS.get(a[3], a[3]),
    '月份': lambda a: a[4] + '月',
    '年份': lambda a: a[5] + '年',
}
single_res = {}
for dim_name, fn in dims.items():
    groups = defaultdict(list)
    for t in eng._all_by_mode['A']:
        groups[fn(attr_of(t))].append(t)
    print(f"\n--- {dim_name} ---")
    for g, ts in sorted(groups.items()):
        pred = lambda t, g=g: fn(attr_of(t)) == g
        n9y, p9y = subgroup_profit_self(pred, 'y1')
        n9a, p9a = subgroup_profit_self(pred, 'all')
        flag = '  <-- y1亏' if p9y < 0 else ''
        print(f"  {g:<12} y1净利={p9y:>+10,.0f} (n={n9y:>5}) | 全周期净利={p9a:>+12,.0f} (n={n9a:>5}){flag}")
        single_res[(dim_name, g)] = dict(y1=p9y, y1n=n9y, all=p9a, alln=n9a)

# ========== 2. 二维交叉扫描(找 y1 亏损密集子群) ==========
print()
print("=" * 100)
print("2. 二维交叉子群 y1 自身净利(找亏损密集区, 只显示 y1 亏或接近0的组合)")
print("=" * 100)
cross_defs = [
    ('信号x市场', lambda a: (SIG_LABELS.get(a[0],a[0]), MKT_LABELS.get(a[3],a[3]))),
    ('信号xETF', lambda a: (SIG_LABELS.get(a[0],a[0]), ETF_LABELS.get(a[1],a[1]))),
    ('评级x市场', lambda a: (RAT_LABELS.get(a[2],a[2]), MKT_LABELS.get(a[3],a[3]))),
    ('ETFx市场', lambda a: (ETF_LABELS.get(a[1],a[1]), MKT_LABELS.get(a[3],a[3]))),
    ('信号x评级', lambda a: (SIG_LABELS.get(a[0],a[0]), RAT_LABELS.get(a[2],a[2]))),
]
cross_res = {}
for name, fn in cross_defs:
    groups = defaultdict(list)
    for t in eng._all_by_mode['A']:
        groups[fn(attr_of(t))].append(t)
    print(f"\n--- {name}(y1) ---")
    rows = []
    for g, ts in groups.items():
        pred = lambda t, g=g: fn(attr_of(t)) == g
        n9y, p9y = subgroup_profit_self(pred, 'y1')
        n9a, p9a = subgroup_profit_self(pred, 'all')
        rows.append((g, p9y, n9y, p9a, n9a))
    # 按 y1 净利升序
    rows.sort(key=lambda r: r[1])
    for g, p9y, n9y, p9a, n9a in rows:
        flag = '  <-- y1亏' if p9y < 0 else ''
        print(f"  {str(g):<22} y1={p9y:>+10,.0f} (n={n9y:>4}) | all={p9a:>+12,.0f} (n={n9a:>5}){flag}")
        cross_res[(name, str(g))] = dict(y1=p9y, y1n=n9y, all=p9a, alln=n9a)

with open('/tmp/kelly_subgroup_scan.json', 'w') as f:
    json.dump(dict(single=single_res, cross=cross_res), f, ensure_ascii=False, indent=1, default=str)
print("\nsaved /tmp/kelly_subgroup_scan.json")
