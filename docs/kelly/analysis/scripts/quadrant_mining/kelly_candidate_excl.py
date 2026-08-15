# -*- coding: utf-8 -*-
"""候选降亏子群剔除边际贡献验证(2.0挖掘核心)
对每个候选子群: 从全信号排除其全部交易 -> 重跑 positionCap K1 每日池 -> 对比全信号净利/收益率
"""
import sys, json
sys.path.insert(0, '/tmp')
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from collections import defaultdict

MODES = ['A','B','C','D','E','F','G','H','I']

td = load_trades()
eng = KellyEngine(td)
fi = eng.fIdx

def t_attrs(t):
    dk = eng._dim_key(t)
    mkt = eng._dims.get(dk, {}).get('mkt', '')
    return dict(sig=str(t[fi['signal']] or ''), etf=str(t[fi['track_tier']] or ''),
                rat=str(t[fi['rating']] or ''), mkt=mkt, mm=str(t[fi['buy_date']] or '')[4:6])

attr_cache = {}
def attr_of(t):
    bk = eng.base_key(t)
    if bk not in attr_cache:
        attr_cache[bk] = t_attrs(t)
    return attr_cache[bk]

# 候选子群定义(谓词)
CANDIDATES = [
    ('追关注×港股', lambda a: a['sig']=='buy_special' and a['mkt']=='hk'),
    ('有跟踪ETF×全球/国债', lambda a: a['etf']=='none' and a['mkt']=='global'),
    ('有跟踪ETF×概念/主题', lambda a: a['etf']=='none' and a['mkt']=='concept'),
    ('有跟踪ETF(整组)', lambda a: a['etf']=='none'),
    ('高评级(整组)', lambda a: a['rat']=='high'),
    ('近似ETF(整组)', lambda a: a['etf']=='approx'),
    ('港股(整组)', lambda a: a['mkt']=='hk'),
    ('追关注×申万行业', lambda a: a['sig']=='buy_special' and a['mkt']=='industry'),
    ('低评级×港股', lambda a: a['rat']=='low' and a['mkt']=='hk'),
    ('相关×申万行业', lambda a: a['etf']=='related' and a['mkt']=='industry'),
    ('追关注×全球/国债', lambda a: a['sig']=='buy_special' and a['mkt']=='global'),
    ('备关注×申万行业', lambda a: a['sig']=='buy_backup' and a['mkt']=='industry'),
    ('有跟踪ETF×申万行业', lambda a: a['etf']=='none' and a['mkt']=='industry'),
    ('近似×全球/国债', lambda a: a['etf']=='approx' and a['mkt']=='global'),
    ('主关注×概念/主题', lambda a: a['sig']=='buy' and a['mkt']=='concept'),
    ('备关注×中评级', lambda a: a['sig']=='buy_backup' and a['rat']=='mid'),
]

# 基线
base_all = eng.compute_quad_stats(eng._all_by_mode, periods=('all','y1'))
bA_all = base_all['all']['A']; bG_all = base_all['all']['G']
bA_y1 = base_all['y1']['A']; bG_y1 = base_all['y1']['G']

print(f"基线 all: A净利={bA_all['total_profit']:+,.0f} 收益={bA_all['return_pct_max_holding']:.2f}% | G净利={bG_all['total_profit']:+,.0f} 收益={bG_all['return_pct_max_holding']:.2f}%")
print(f"基线 y1: A净利={bA_y1['total_profit']:+,.0f} 收益={bA_y1['return_pct_max_holding']:.2f}% | G净利={bG_y1['total_profit']:+,.0f} 收益={bG_y1['return_pct_max_holding']:.2f}%")
print()

# 子群自身 y1/all 净利(9模式合计, 在 AI宏+poscapK1 保留后)
print("子群自身净利(9模式合计, 保留后):")
self_res = {}
for name, pred in CANDIDATES:
    quad_trades = {mk: [t for t in eng._all_by_mode[mk] if pred(attr_of(t))] for mk in MODES}
    for pk in ('y1','all'):
        st = eng.compute_quad_stats(quad_trades, periods=(pk,))[pk]
        self_res.setdefault(name, {})[pk] = dict(n=sum(st[m]['n'] for m in MODES), p=sum(st[m]['total_profit'] for m in MODES))
    r = self_res[name]
    print(f"  {name:<22} y1={r['y1']['p']:>+10,.0f}(n={r['y1']['n']:>4}) | all={r['all']['p']:>+12,.0f}(n={r['all']['n']:>5})")
print()

# 剔除边际贡献
print("=" * 110)
print("剔除候选子群后全信号变化(重跑 positionCap K1 每日池)")
print("=" * 110)
header = f"{'候选子群':<22} {'y1 AΔ':>10} {'y1 GΔ':>10} | {'all AΔ':>11} {'all GΔ':>11} | {'all A收益':>9} {'all G收益':>9} | {'剔除基笔':>8}"
print(header)
print("-" * 110)
excl_res = {}
for name, pred in CANDIDATES:
    # 该子群全周期全模式的 baseKey 集合
    keyset = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            if pred(attr_of(t)):
                keyset.add(eng.base_key(t))
    st = eng.compute_quad_stats(eng._all_by_mode, exclude_keys=keyset, periods=('all','y1'))
    sA_all = st['all']['A']; sG_all = st['all']['G']
    sA_y1 = st['y1']['A']; sG_y1 = st['y1']['G']
    dAy1 = sA_y1['total_profit'] - bA_y1['total_profit']
    dGy1 = sG_y1['total_profit'] - bG_y1['total_profit']
    dAall = sA_all['total_profit'] - bA_all['total_profit']
    dGall = sG_all['total_profit'] - bG_all['total_profit']
    excl_res[name] = dict(keyset_n=len(keyset), dAy1=dAy1, dGy1=dGy1, dAall=dAall, dGall=dGall,
                          sA_all=sA_all, sG_all=sG_all, sA_y1=sA_y1, sG_y1=sG_y1)
    print(f"{name:<22} {dAy1:>+10,.0f} {dGy1:>+10,.0f} | {dAall:>+11,.0f} {dGall:>+11,.0f} | "
          f"{sA_all['return_pct_max_holding']:>8.2f}% {sG_all['return_pct_max_holding']:>8.2f}% | {len(keyset):>8}")

with open('/tmp/kelly_candidate_excl.json', 'w') as f:
    json.dump(dict(baseline=dict(A_all=bA_all, G_all=bG_all, A_y1=bA_y1, G_y1=bG_y1), self_res=self_res, excl=excl_res), f, ensure_ascii=False, indent=1, default=str)
print("\nsaved /tmp/kelly_candidate_excl.json")
