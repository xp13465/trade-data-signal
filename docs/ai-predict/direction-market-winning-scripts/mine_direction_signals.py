#!/usr/bin/env python3
"""方向胜率信号挖掘 - 用户方法论第①②步
目的:从历史数据挖「哪些信号在次日方向预判上胜率高」+「转向日是否更准」
方法:信号日 date -> 上证(sh) 下一交易日 pct_change 符号 = 次日方向
数据源:
  - index_daily (sentiment.db): sh 次日基准
  - futures_position (sentiment.db): 中信/国泰君安/top20 net_chg 636天
  - daily_metric (sentiment.db): lhb_inst_net/lhb_count/a_fund_north/a_fund_margin/a_amount/a_volume_ratio/a_up_down_ratio/a_ad_line/a_width_zt_count/a_width_dt_count/a_nhnl_52w/a_ma_bullish/a_ma_bearish
  - static-site/data/sentiment-1y.json: a_sentiment/fear_greed
输出:JSON 结果落盘 scripts/out/
数据截止:20260819 收盘(20260820 盘中当日无次日方向,排除)
"""
import json, sqlite3, os
from collections import OrderedDict

DB = 'file:/Users/linhuichen/code/trade-data/data/sentiment.db?mode=ro'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
os.makedirs(OUT, exist_ok=True)

c = sqlite3.connect(DB, uri=True)

# ---------- 1. 次日方向基准: sh ----------
sh_rows = c.execute("SELECT date, pct_change FROM index_daily WHERE index_id='sh' AND pct_change IS NOT NULL ORDER BY date").fetchall()
sh_dates = [r[0] for r in sh_rows]
sh_pct = {r[0]: r[1] for r in sh_rows}
sh_set = set(sh_dates)
sh_idx = {d: i for i, d in enumerate(sh_dates)}

def next_dir(date):
    """信号日date -> 次日 sh 方向. 返回 (direction:+1/-1, next_return, next_date) 或 None"""
    if date not in sh_idx: return None
    i = sh_idx[date]
    if i+1 >= len(sh_dates): return None
    nd = sh_dates[i+1]
    nr = sh_pct[nd]
    return (1 if nr > 0 else -1, nr, nd)

# ---------- 2. 信号加载 ----------
def load_futures():
    """futures_position -> {role: {variety: [(date, net_chg)]}} net_chg=long_chg-short_chg"""
    rows = c.execute("SELECT date, variety, role, long_chg, short_chg FROM futures_position ORDER BY date").fetchall()
    d = {}
    for date, var, role, lc, sc in rows:
        if lc is None or sc is None: continue
        d.setdefault(role, {}).setdefault(var, []).append((date, lc-sc))
    return d

def load_metric(metric_id):
    rows = c.execute("SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date", (metric_id,)).fetchall()
    return [(str(d), v) for d, v in rows]

def load_lhb():
    return load_metric('lhb_inst_net'), load_metric('lhb_count')

def load_sentiment_json():
    sj = json.load(open('/Users/linhuichen/code/trade/static-site/data/sentiment-1y.json'))
    a_sent = [(x['date'], x['value']) for x in sj['a_sentiment']]
    fg = [(x['date'], x['value']) for x in sj.get('fear_greed', [])]
    return a_sent, fg

# ---------- 3. 胜率统计 ----------
def winrate(pred_dirs, true_dirs):
    """pred_dirs/true_dirs: list of +1/-1 aligned. 返回 (n, 中, 胜率)"""
    n = len(pred_dirs)
    if n == 0: return (0, 0, None)
    hit = sum(1 for p, t in zip(pred_dirs, true_dirs) if p == t)
    return (n, hit, hit / n)

def eval_signal(name, signal_series, pred_fn, sample_start=None):
    """signal_series: [(date, value)]; pred_fn(value, prev_value)-> +1/-1/0(排除). 
    返回 stats + 转向分析(信号值相对前值方向翻转)"""
    preds, trues, dates = [], [], []
    prev = None
    # 转向点统计
    turn_preds, turn_trues = [], []
    non_preds, non_trues = [], []
    prev_sig_dir = None
    for date, val in signal_series:
        if sample_start and date < sample_start: 
            prev = val; continue
        nd = next_dir(date)
        if nd is None: prev = val; continue
        sig_dir, pred = pred_fn(val, prev)
        if pred == 0: prev = val; continue
        preds.append(pred); trues.append(nd[0]); dates.append(date)
        if prev_sig_dir is not None and sig_dir != prev_sig_dir:
            turn_preds.append(pred); turn_trues.append(nd[0])
        else:
            non_preds.append(pred); non_trues.append(nd[0])
        prev_sig_dir = sig_dir
        prev = val
    base = winrate(preds, trues)
    turn = winrate(turn_preds, turn_trues)
    non = winrate(non_preds, non_trues)
    return {
        'signal': name, 'n': base[0], 'hit': base[1], 'winrate': base[2],
        'turn_n': turn[0], 'turn_hit': turn[1], 'turn_winrate': turn[2],
        'non_n': non[0], 'non_hit': non[1], 'non_winrate': non[2],
        'sample_start': signal_series[0][0] if signal_series else None,
        'sample_end': signal_series[-1][0] if signal_series else None,
    }

# ---------- 4. 穷举信号 ----------
results = []

# --- 期货类: net_chg 符号 -> 次日 ---
fut = load_futures()
for role in ['中信期货', '国泰君安', 'top20']:
    for var in ['综合', 'IH', 'IF', 'IC', 'IM']:
        if var not in fut.get(role, {}): continue
        series = fut[role][var]
        # 正向: net_chg>0(加多)-> 预测涨; net_chg<0(加空)-> 预测跌
        def mk_pred(series, contrarian=False):
            def pred(val, prev):
                if val is None: return 0, 0
                d = 1 if val > 0 else -1
                p = -d if contrarian else d
                return d, p
            return pred
        r1 = eval_signal(f'{role} {var} net_chg 正向', series, mk_pred(series))
        r2 = eval_signal(f'{role} {var} net_chg 逆向', series, mk_pred(series, contrarian=True))
        results.append(r1); results.append(r2)

# --- 龙虎榜 ---
lhb_inst, lhb_cnt = load_lhb()
results.append(eval_signal('龙虎榜机构净买 lhb_inst_net>0涨', lhb_inst,
    lambda v, p: (1 if v>0 else -1, 1 if v>0 else -1)))
results.append(eval_signal('龙虎榜机构净买 lhb_inst_net>0跌(逆向)', lhb_inst,
    lambda v, p: (1 if v>0 else -1, -1 if v>0 else 1)))

# --- 北向/两融增量 ---
north = load_metric('a_fund_north')
margin = load_metric('a_fund_margin')
def inc_pred(v, p):
    if p is None: return 0, 0
    dv = v - p
    d = 1 if dv > 0 else -1
    return d, d
results.append(eval_signal('北向 a_fund_north 增量>0涨', north, inc_pred))
results.append(eval_signal('北向 a_fund_north 增量>0跌(逆向)', north, 
    lambda v, p: (1 if (v-p)>0 else -1, -1 if (v-p)>0 else 1) if p is not None else (0,0)))
results.append(eval_signal('两融 a_fund_margin 增量>0涨', margin, inc_pred))
results.append(eval_signal('两融 a_fund_margin 增量>0跌(逆向)', margin,
    lambda v, p: (1 if (v-p)>0 else -1, -1 if (v-p)>0 else 1) if p is not None else (0,0)))

# --- 量能 ---
amount = load_metric('a_amount')
vr = load_metric('a_volume_ratio')
# 量比分位: 用滚动(前60日)分位
def quantile_signal(series, q_hi=80, q_lo=20, contrarian=False):
    """量比等: 高>80分位预测跌(量能过热), 低<20分位预测涨"""
    vals = [x[1] for x in series]
    import statistics
    out = []
    for i, (d, v) in enumerate(series):
        if i < 60: out.append((d, v, None)); continue
        win = vals[i-60:i]
        q80 = sorted(win)[int(len(win)*0.8)-1]
        q20 = sorted(win)[int(len(win)*0.2)]
        if v >= q80: out.append((d, v, -1))   # 高量比 -> 预测跌
        elif v <= q20: out.append((d, v, 1))  # 低量比 -> 预测涨
        else: out.append((d, v, 0))
    return out

def eval_quantile(name, series, contrarian=False):
    qs = quantile_signal(series)
    preds, trues = [], []
    for d, v, pred in qs:
        if pred == 0: continue
        nd = next_dir(d)
        if nd is None: continue
        p = (-pred if contrarian else pred) if pred is not None else 0
        preds.append(p); trues.append(nd[0])
    n, hit, wr = winrate(preds, trues)
    return {'signal': name, 'n': n, 'hit': hit, 'winrate': wr, 'sample_start': series[0][0], 'sample_end': series[-1][0]}

results.append(eval_quantile('量比 a_volume_ratio 高分位>跌/低分位>涨', vr))
results.append(eval_quantile('量比 a_volume_ratio 逆向', vr, contrarian=True))
results.append(eval_quantile('成交额 a_amount 高分位>跌/低分位>涨', amount))
results.append(eval_quantile('成交额 a_amount 逆向', amount, contrarian=True))

# --- 涨跌比/AD线 ---
udr = load_metric('a_up_down_ratio')
adl = load_metric('a_ad_line')
results.append(eval_quantile('涨跌比 a_up_down_ratio 高>跌/低>涨', udr))
results.append(eval_quantile('涨跌比 a_up_down_ratio 逆向', udr, contrarian=True))
# AD线增量: 正增量->涨
results.append(eval_signal('AD线 a_ad_line 增量>0涨', adl, inc_pred))
results.append(eval_signal('AD线 a_ad_line 增量>0跌(逆向)', adl,
    lambda v, p: (1 if (v-p)>0 else -1, -1 if (v-p)>0 else 1) if p is not None else (0,0)))

# --- 宽度 ---
zt = load_metric('a_width_zt_count')
dt = load_metric('a_width_dt_count')
upc = load_metric('a_width_up_count')
results.append(eval_quantile('涨停数 a_width_zt_count 高>跌/低>涨', zt))
results.append(eval_quantile('涨停数 a_width_zt_count 逆向', zt, contrarian=True))
results.append(eval_quantile('跌停数 a_width_dt_count 高>跌/低>涨', dt))
results.append(eval_quantile('上涨家数 a_width_up_count 高>跌/低>涨', upc))

# --- 新高新低比 ---
nhnl = load_metric('a_nhnl_52w')
results.append(eval_quantile('新高新低比 a_nhnl_52w 高>跌/低>涨', nhnl))
results.append(eval_quantile('新高新低比 a_nhnl_52w 逆向', nhnl, contrarian=True))

# --- 均线 ---
ma_bull = load_metric('a_ma_bullish')
ma_bear = load_metric('a_ma_bearish')
results.append(eval_signal('均线多头 a_ma_bullish 当日>0涨', ma_bull, 
    lambda v, p: (1 if v>0 else -1, 1 if v>0 else -1)))
results.append(eval_signal('均线空头 a_ma_bearish 当日>0跌', ma_bear,
    lambda v, p: (1 if v>0 else -1, -1 if v>0 else 1)))

# --- 情绪分 ---
a_sent, fg = load_sentiment_json()
results.append(eval_quantile('情绪分 a_sentiment 高>跌/低>涨', a_sent))
results.append(eval_quantile('情绪分 a_sentiment 逆向', a_sent, contrarian=True))
results.append(eval_quantile('恐贪 fear_greed 高>跌/低>涨', fg))
results.append(eval_quantile('恐贪 fear_greed 逆向', fg, contrarian=True))

# ---------- 5. 输出 ----------
results.sort(key=lambda r: (r['winrate'] if r['winrate'] is not None else 0), reverse=True)
print(f"{'信号':<44} {'n':>4} {'中':>3} {'胜率':>6} {'转向n':>5} {'转向率':>6} {'非转向n':>5} {'非转率':>6}")
for r in results:
    wr = f"{r['winrate']*100:.1f}%" if r['winrate'] is not None else '-'
    twr = f"{r['turn_winrate']*100:.1f}%" if r.get('turn_winrate') is not None else '-'
    nwr = f"{r['non_winrate']*100:.1f}%" if r.get('non_winrate') is not None else '-'
    print(f"{r['signal']:<44} {r['n']:>4} {r['hit']:>3} {wr:>6} {r.get('turn_n','-'):>5} {twr:>6} {r.get('non_n','-'):>5} {nwr:>6}")

with open(os.path.join(OUT, 'signal_winrates.json'), 'w') as fp:
    json.dump(results, fp, ensure_ascii=False, indent=1)
print('\nSaved:', os.path.join(OUT, 'signal_winrates.json'))
