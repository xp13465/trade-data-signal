# -*- coding: utf-8 -*-
"""四档大盘状态接入凯利过滤 - 穷举回测(维度1/2/3)
口径: v1.1.0 基准 = 8键(基础5+核心3含K2C5) + 每日池等分 K=1 + G 13万 P≤3d b0 / H=hold7万 / I=hold15万 / A-F=每日池+top-K
数据: signal_kelly_trades.json 批 2026-08-17 21:58(报告数字基于固化副本 /tmp/ms_bt/signal_kelly_trades_pinned.json;复现时改本脚本 TRADES_IN)
依赖: 同目录 kelly_engine.py + kelly_opg_engine.py
"""
import sys, os, json, itertools, bisect, sqlite3
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
_conn = sqlite3.connect(DB)
_rows = _conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
_DATES = [r[0] for r in _rows]; _CLOSES = [r[1] for r in _rows]; _N = len(_DATES)
def _ma(arr, w, i):
    if i < w - 1: return None
    return sum(arr[i-w+1:i+1]) / w
_MA20 = [_ma(_CLOSES,20,i) for i in range(_N)]; _MA60 = [_ma(_CLOSES,60,i) for i in range(_N)]
_MA120 = [_ma(_CLOSES,120,i) for i in range(_N)]; _MA200 = [_ma(_CLOSES,200,i) for i in range(_N)]
def st4_idx(i):
    if _MA200[i] is None: return None
    bull = _CLOSES[i] > _MA200[i]
    m_align = (_MA20[i] > _MA60[i] > _MA120[i]) if (_MA20[i] is not None and _MA60[i] is not None and _MA120[i] is not None) else False
    b_align = (_MA20[i] < _MA60[i] < _MA120[i]) if (_MA20[i] is not None and _MA60[i] is not None and _MA120[i] is not None) else False
    if bull and m_align: return "牛市·主升"
    if bull and not m_align: return "上升期"
    if not bull and not b_align: return "下降期"
    return "熊市·主跌"
def st4_of_date(dstr):
    i = bisect.bisect_right(_DATES, dstr) - 1
    if i < 0: return None
    return st4_idx(i)
def st60_of_date(dstr):
    i = bisect.bisect_right(_DATES, dstr) - 1
    if i < 0 or _MA60[i] is None: return None
    return "牛" if _CLOSES[i] > _MA60[i] else "熊"

TRADES_IN = '/tmp/ms_bt/signal_kelly_trades_pinned.json'  # 固化副本(2026-08-17 21:58),复现报告数字用它;想跑最新数据改为 static-site/data/signal_kelly_trades.json
td = load_trades(TRADES_IN)
oeng = OpgEngine(td); eng = oeng.eng; fi = eng.fIdx
print('数据批:', td.get('generated_at'))

_attr_cache = {}
def attr_of(t):
    bk = eng.base_key(t)
    if bk not in _attr_cache:
        sd = str(t[fi['signal_date']] or "")
        dk = eng._dim_key(t)
        mkt = eng._dims.get(dk, {}).get('mkt', '')
        sig = str(t[fi['signal']] or "")
        _attr_cache[bk] = dict(s4=st4_of_date(sd), s60=st60_of_date(sd), mkt=mkt, sig=sig)
    return _attr_cache[bk]

A_STOCK = ('a', 'concept', 'industry')
ALL_SIGS = ('buy', 'buy_aux', 'buy_special', 'buy_backup')

def mk_excl(pred):
    ks = set()
    for mk in MODES:
        for t in eng._all_by_mode[mk]:
            a = attr_of(t)
            if pred(a): ks.add(eng.base_key(t))
    return ks

K2 = mk_excl(lambda a: a['sig'] in ('buy_special', 'buy_backup') and a['mkt'] == 'hk')

def compute(filters, exclude_keys, g_model='b0', state_factor=None, periods=('all',)):
    rec = {m: oeng._mode_recomputed(m, filters, exclude_keys) for m in MODES}
    cutoffs = eng.period_cutoffs
    res = {}
    for pk in periods:
        cutoff = cutoffs.get(pk, '0')
        res[pk] = {}
        for m in MODES:
            rp = [t for t in rec[m] if cutoff == '0' or t['buy_date'] >= cutoff]
            if state_factor:
                rp2 = []
                for t in rp:
                    a = attr_of(t)
                    f = state_factor.get(a['s4'], 1.0)
                    if f <= 0: continue
                    t2 = dict(t)
                    t2['amount'] = round(t['amount'] * f, 2)
                    t2['profit'] = round(t['profit'] * f, 2)
                    t2['fee_cost'] = round(t['fee_cost'] * f, 2)
                    rp2.append(t2)
                rp = rp2
            if m == 'G':
                kt, peak = p3d_cap(rp, 130000, model=g_model)
                tp = sum(k['profit'] for k in kt)
                res[pk][m] = dict(n=len(kt), total_profit=round(tp*10000)/10000,
                                  return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak > 0 else 0,
                                  max_concurrent_capital=peak)
            elif m in ('H', 'I'):
                cap = 70000 if m == 'H' else 150000
                kt, peak = hold_cap(rp, cap)
                tp = sum(k['profit'] for k in kt)
                res[pk][m] = dict(n=len(kt), total_profit=round(tp*10000)/10000,
                                  return_pct_max_holding=round(tp/peak*100*10000)/10000 if peak > 0 else 0,
                                  max_concurrent_capital=peak)
            else:
                tuples = [(k['profit'], k['return_pct'], k['fee_cost'], k['buy_date'], k['sell_date'], k['hold_days'], k['amount']) for k in rp]
                res[pk][m] = eng.compute_stats(tuples)
    return res

BASE8 = dict(AI_MACRO)
BASE8_EXCL = set(K2)

def state_excl(states, sigs=None, scope=None):
    return mk_excl(lambda a: a['s4'] in states and (sigs is None or a['sig'] in sigs) and (scope is None or a['mkt'] in scope))

def fmt_row(base, s, m):
    d = s['total_profit'] - base['total_profit']
    dr = s['return_pct_max_holding'] - base['return_pct_max_holding']
    return (m, base['total_profit'], s['total_profit'], d, base['return_pct_max_holding'],
            s['return_pct_max_holding'], dr, s['n'] - base['n'])

def dump_table(name, res, base, out):
    out.append(f"### {name}")
    out.append(f"{'模式':<4} {'默认净利':>10} {'叠加净利':>10} {'Δ净利':>9} {'默认收益':>8} {'叠加收益':>8} {'Δ收益':>7} {'Δ笔数':>6}")
    for m in MODES:
        r = fmt_row(base['all'][m], res['all'][m], m)
        out.append(f"{r[0]:<4} {r[1]:>+10,.0f} {r[2]:>+10,.0f} {r[3]:>+9,.0f} {r[4]:>7.2f}% {r[5]:>7.2f}% {r[6]:>+6.2f}pp {r[7]:>+6}")
    out.append("")

# 维度1 变体定义
VARIANTS = [
    # (名称, 说明, 状态集, 信号集, 市场范围)
    ("V1_熊主跌剔除全部", "熊市·主跌 剔除全部买类(A股)", ("熊市·主跌",), None, A_STOCK),
    ("V2_熊主跌下降期剔除全部", "熊市·主跌+下降期 剔除全部买类(A股)", ("熊市·主跌", "下降期"), None, A_STOCK),
    ("V3_仅下降期剔除全部", "仅下降期 剔除全部买类(A股)", ("下降期",), None, A_STOCK),
    ("V4_熊下降剔除追关注", "熊市·主跌+下降期 剔除 buy_special(A股)", ("熊市·主跌", "下降期"), ("buy_special",), A_STOCK),
    ("V5_熊下降剔除追+辅", "熊市·主跌+下降期 剔除 buy_special+buy_aux(A股)", ("熊市·主跌", "下降期"), ("buy_special", "buy_aux"), A_STOCK),
    ("V6_熊下降剔除追+备", "熊市·主跌+下降期 剔除 buy_special+buy_backup(A股)", ("熊市·主跌", "下降期"), ("buy_special", "buy_backup"), A_STOCK),
    ("V7_熊下降剔除主关注", "熊市·主跌+下降期 剔除 buy(A股)", ("熊市·主跌", "下降期"), ("buy",), A_STOCK),
    ("V8_黄金区剔除全部_反向", "牛市·主升+上升期 剔除全部买类(A股,反向证明黄金区不能剔)", ("牛市·主升", "上升期"), None, A_STOCK),
    ("V9_熊主跌剔除追关注", "仅熊市·主跌 剔除 buy_special(A股,最接近excludeSpecialBear口径)", ("熊市·主跌",), ("buy_special",), A_STOCK),
    ("V2_all_熊下降剔除全部", "熊市·主跌+下降期 剔除全部买类(全部市场)", ("熊市·主跌", "下降期"), None, None),
    ("V4_all_熊下降剔除追", "熊市·主跌+下降期 剔除 buy_special(全部市场)", ("熊市·主跌", "下降期"), ("buy_special",), None),
]

if __name__ == '__main__':
    out = []
    base = compute(BASE8, BASE8_EXCL)
    g = base['all']['G']
    print(f"[基线] 8键 G b0 all = {g['total_profit']:+,.2f} / {g['return_pct_max_holding']:.2f}%")
    out.append(f"# 四档大盘状态回测输出(数据批 {td.get('generated_at')})")
    out.append("")
    out.append("## 0. 基线(v1.1.0 8键)")
    for m in MODES:
        s = base['all'][m]
        out.append(f"{m}: 净利={s['total_profit']:+,.0f} 收益={s['return_pct_max_holding']:.2f}% 峰持仓={s['max_concurrent_capital']/10000:.1f}万 n={s['n']}")
    out.append("")

    results = {'generated_at': td.get('generated_at'), 'baseline': {m: base['all'][m] for m in MODES}, 'variants': {}}

    # ===== 维度1: 叠加边际 =====
    out.append("## 维度1: 状态×过滤组合叠加边际(A股范围, 如无特别标注)")
    for name, desc, states, sigs, scope in VARIANTS:
        excl = state_excl(states, sigs, scope)
        r = compute(BASE8, BASE8_EXCL | excl)
        results['variants'][name] = {'desc': desc, 'excl_n': len(excl), 'all': {m: r['all'][m] for m in MODES}}
        out.append(f"[{name}] 剔除 {len(excl)} 笔 | {desc}")
        dump_table(name, r, base, out)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','data','results_4tier_variants.json'), 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print('\n'.join(out))
