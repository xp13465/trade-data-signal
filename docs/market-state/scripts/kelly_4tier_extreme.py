# -*- coding: utf-8 -*-
"""四档 vs MA60 极端行情窗口验证 + 9模式明细(用户质疑「救误杀会不会放真熊」)
口径: v1.1.0 基准 8键 K=1 每日池等分, G 13万 P≤3d b0, H/I hold 7/15万
     R1_all = 替换 excludeSpecialBear 为四档(熊市·主跌+下降期)×buy_special×全市场
     V4d_all = 新增键「下降期×buy_special×全市场」(excludeSpecialBear 保持 on)
数据: /tmp/ms_bt/signal_kelly_trades_pinned.json(固化 2026-08-17 21:58)+ data/sentiment.db hs300
输出: ../data/results_4tier_extreme.json + 打印摘要
复现: python3 kelly_4tier_extreme.py
"""
import sys, os, json, bisect, sqlite3
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kelly_engine import KellyEngine, load_trades, AI_MACRO
from kelly_opg_engine import OpgEngine, MODES, p3d_cap, hold_cap

__file__ = os.path.abspath(__file__)
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kelly_4tier_main.py')).read().split('if __name__')[0])

DB = "/Users/linhuichen/code/trade/data/sentiment.db"
_conn = sqlite3.connect(DB)
_rows = _conn.execute("SELECT date, close FROM index_daily WHERE index_id='hs300' AND close IS NOT NULL ORDER BY date").fetchall()
_DATES = [r[0] for r in _rows]; _CLOSES = [r[1] for r in _rows]; _N = len(_DATES)
def _ma(arr, w, i):
    if i < w - 1: return None
    return sum(arr[i-w+1:i+1]) / w
_MA20 = [_ma(_CLOSES,20,i) for i in range(_N)]; _MA60 = [_ma(_CLOSES,60,i) for i in range(_N)]
_MA120 = [_ma(_CLOSES,120,i) for i in range(_N)]; _MA200 = [_ma(_CLOSES,200,i) for i in range(_N)]

def st4_i(i):
    if _MA200[i] is None: return None
    bull = _CLOSES[i] > _MA200[i]
    m_align = (_MA20[i] > _MA60[i] > _MA120[i]) if (_MA20[i] is not None and _MA60[i] is not None and _MA120[i] is not None) else False
    b_align = (_MA20[i] < _MA60[i] < _MA120[i]) if (_MA20[i] is not None and _MA60[i] is not None and _MA120[i] is not None) else False
    if bull and m_align: return "牛市·主升"
    if bull and not m_align: return "上升期"
    if not bull and not b_align: return "下降期"
    return "熊市·主跌"

def idx_of(dstr):
    return bisect.bisect_right(_DATES, dstr) - 1

def st4_of(dstr):
    i = idx_of(dstr)
    if i < 0: return None
    return st4_i(i)

def st60_of(dstr):
    i = idx_of(dstr)
    if i < 0 or _MA60[i] is None: return None
    return "牛" if _CLOSES[i] > _MA60[i] else "熊"

def lag_state(dstr):
    """滞后带: 价<MA60 且 价>MA200 = 四档年线仍牛(滞后放行带)"""
    i = idx_of(dstr)
    if i < 0 or _MA60[i] is None or _MA200[i] is None: return None
    below60 = _CLOSES[i] < _MA60[i]
    above200 = _CLOSES[i] > _MA200[i]
    if below60 and above200: return "滞后带(价<MA60且价>MA200)"
    if below60: return "双熊(价<MA60且价<MA200)"
    return "双牛(价>MA60)"

# ============ 1) 9模式明细表 ============
BASE8 = dict(AI_MACRO); BASE8_EXCL = set(K2)
excl_r1all = state_excl(("熊市·主跌","下降期"), ("buy_special",), None)   # R1_all 全市场替换剔除集
excl_v4d   = state_excl(("下降期",), ("buy_special",), None)              # V4d_all 全市场下降期剔除集
f_r1 = dict(BASE8); f_r1['excludeSpecialBear'] = False

base = compute(BASE8, BASE8_EXCL)
r1   = compute(f_r1, BASE8_EXCL | excl_r1all)
v4d  = compute(BASE8, BASE8_EXCL | excl_v4d)

assert abs(base['all']['G']['total_profit'] - 203450.53) < 2000, f"基线未复现 {base['all']['G']}"

rows9 = []
for m in MODES:
    b = base['all'][m]; r = r1['all'][m]; v = v4d['all'][m]
    rows9.append(dict(mode=m,
        base=b['total_profit'], r1=r['total_profit'], v4d=v['total_profit'],
        d_r1=r['total_profit']-b['total_profit'], d_v4d=v['total_profit']-b['total_profit'],
        base_ret=b['return_pct_max_holding'], r1_ret=r['return_pct_max_holding'], v4d_ret=v['return_pct_max_holding'],
        base_n=b['n'], r1_n=r['n'], v4d_n=v['n']))

print("=== 9模式明细(全周期) ===")
print(f"{'模式':<4}{'基线':>11}{'R1_all':>11}{'V4d_all':>11}{'ΔR1':>9}{'ΔV4d':>9}{'基收益':>8}{'R1收益':>8}{'V4d收益':>8}")
for r in rows9:
    print(f"{r['mode']:<4}{r['base']:>+11,.0f}{r['r1']:>+11,.0f}{r['v4d']:>+11,.0f}{r['d_r1']:>+9,.0f}{r['d_v4d']:>+9,.0f}{r['base_ret']:>7.2f}%{r['r1_ret']:>7.2f}%{r['v4d_ret']:>7.2f}%")

# ============ 2) 极端行情窗口 ============
WINDOWS = [
    ("2015股灾", "20150601", "20160131"),
    ("2018单边熊", "20180101", "20181231"),
    ("2020疫情闪崩", "20200201", "20200331"),
    ("2022大熊", "20220101", "20221231"),
    ("2024小微盘", "20240101", "20240229"),
]
# 全史 buy_special×A股 基笔(去重)
seen = set(); all_bs = []
for mk in MODES:
    for t in eng._all_by_mode[mk]:
        a = attr_of(t)
        if a['sig'] != 'buy_special' or a['mkt'] not in A_STOCK: continue
        bk = eng.base_key(t)
        if bk in seen: continue
        seen.add(bk)
        all_bs.append((t, a))
print(f"\n=== 极端窗口(全史 buy_special×A股 基笔 {len(all_bs)}, signal_date 落窗) ===")
win_rows = []
for wn, ws, we in WINDOWS:
    win = [r for r in all_bs if ws <= str(r[0][fi['signal_date']] or '') <= we]
    rescue = [r for r in win if r[1]['s60']=='熊' and r[1]['s4'] not in ('熊市·主跌','下降期')]
    leak   = [r for r in win if r[1]['s60']=='牛' and r[1]['s4'] in ('熊市·主跌','下降期')]
    inter  = [r for r in win if r[1]['s60']=='熊' and r[1]['s4'] in ('熊市·主跌','下降期')]
    # 滞后敞口日: 窗口内 hs300 交易日 价<MA60且价>MA200 天数
    lag_days = 0
    for d in _DATES:
        if ws <= d <= we:
            if lag_state(d) == "滞后带(价<MA60且价>MA200)": lag_days += 1
    def net(rs):
        return round(sum(t[fi['profit']] for t,a in rs),1), len(rs)
    w = dict(name=wn, ws=ws, we=we, n=len(win),
             ma60_bear=sum(1 for t,a in win if a['s60']=='熊'),
             four_bad=sum(1 for t,a in win if a['s4'] in ('熊市·主跌','下降期')),
             rescue_net=net(rescue)[0], rescue_n=net(rescue)[1], rescue_detail=[dict(sd=str(t[fi['signal_date']]), bd=str(t[fi['buy_date']]), etf=str(t[fi['etf_name']]), profit=round(t[fi['profit']],1), s4=a['s4'], s60=a['s60'], mkt=a['mkt'], lag=lag_state(str(t[fi['signal_date']]))) for t,a in rescue],
             leak_net=net(leak)[0], leak_n=net(leak)[1],
             inter_n=len(inter), lag_days=lag_days)
    win_rows.append(w)
    print(f"\n[{wn}] {ws}~{we}: 窗口内基笔 n={w['n']} | MA60熊 {w['ma60_bear']} | 四档坏 {w['four_bad']} | 交集 {w['inter_n']}")
    print(f"  救回单(MA60熊四档放行): {w['rescue_n']} 笔 净 {w['rescue_net']:+,.1f} | 明细: {w['rescue_detail']}")
    print(f"  漏剔单(MA60牛四档剔): {w['leak_n']} 笔 净 {w['leak_net']:+,.1f}")
    print(f"  滞后敞口日(价<MA60且价>MA200): {w['lag_days']} 交易日")

# ============ 3) 救回单全史明细(94笔) ============
rescue_all = [r for r in all_bs if r[1]['s60']=='熊' and r[1]['s4'] not in ('熊市·主跌','下降期')]
lag_n = sum(1 for t,a in rescue_all if lag_state(str(t[fi['signal_date']])) == "滞后带(价<MA60且价>MA200)")
lag_profit = sum(t[fi['profit']] for t,a in rescue_all if lag_state(str(t[fi['signal_date']])) == "滞后带(价<MA60且价>MA200)")
print(f"\n=== 全史救回单 94 笔明细(净 {sum(t[fi['profit']] for t,a in rescue_all):+,.1f}) ===")
print(f"其中判定日在「滞后带(价<MA60且价>MA200)」: {lag_n} 笔 净 {lag_profit:+,.1f} <- 四档年线滞后放行核心证据")
det = []
for t,a in sorted(rescue_all, key=lambda r: str(r[0][fi['signal_date']])):
    d = dict(sd=str(t[fi['signal_date']]), bd=str(t[fi['buy_date']]), sd2=str(t[fi['sell_date']] or ''), etf=str(t[fi['etf_name']]), profit=round(t[fi['profit']],1), s4=a['s4'], mkt=a['mkt'], lag=lag_state(str(t[fi['signal_date']])))
    det.append(d)
    print(f"  {d['sd']} b{d['bd']} s{d['sd2']} {d['etf']} 净{d['profit']:+.1f} {d['s4']}/{d['lag']}")

# 亏损的救回单
loss_rescue = [r for r in rescue_all if t[fi['profit']] < 0]
loss_rescue = [r for r in rescue_all if r[0][fi['profit']] < 0]
print(f"\n救回单中亏损笔: {len(loss_rescue)} 笔 合计 {sum(t[fi['profit']] for t,a in loss_rescue):+,.1f}")

out = dict(generated_at=td.get('generated_at'), rows9=rows9, windows=win_rows,
           rescue_all_n=len(rescue_all), rescue_all_net=round(sum(t[fi['profit']] for t,a in rescue_all),1),
           lag_rescue_n=lag_n, lag_rescue_net=round(lag_profit,1),
           rescue_detail=det)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'results_4tier_extreme.json'), 'w') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"\n[写盘] ../data/results_4tier_extreme.json")
