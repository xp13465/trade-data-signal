# -*- coding: utf-8 -*-
"""s06_segment_style_exhaustive.py - S06 2014 前分段风格判定「穷举重跑」落档脚本(研究, 只读不改)

【目的】v1.1.14 方案2 上线后, 按 §5.1 穷举最大化重跑设计阶段选优谱, 验证当前投产参数
  (方案2 csi500-hs300 价差 sticky, THRESHOLD=-3.524224785046781, CONFIRM=15, MIN_HOLD=10, K=1)
  在当前数据(2026-09-03 05:10 trades)下是否仍是最优; 并落档「落地对账」口径(主控页面实测权威
  G=146.72%/+146,718 / H=224.92%/+112,461 / I=159.63%/+143,670 由 JS 引擎复现, 本脚本管段内口径)。

【方法口径】(与 s06_segment_style_backtest.py 逐位同构, 该脚本已对账权威 JS 引擎)
  - 信号: signal_kelly_trades.json 全象限 baseKey 去重, buy_date∈[20110119, 20141113] 110 笔
  - 判定: T 日收盘因子 → T+1 生效; 纯阈值版 与 sticky 版(confirm=15/min_hold=10)两态
  - 过滤: 按 signal_date 读 per-date base → a9/new14 键集 passesFade(月门+T1 spec)
  - 口径: K 档参数化(1/2/3), 每笔 10000 按日池等分 → recompute(etf_main 费率)
  - 扫描维度: ①方法全谱(方案1 hs300 单指 / 方案2 csi500-hs300 价差 / 方案3 cyb-sh 成长-大盘,
    sticky+纯阈值) ②阈值全谱(-5~-2 步进 0.25 + 0/±2/±4 + 分布分位 q10/q30/q50 + 冻结值对照)
   ③K 档 {1,2,3} ④稳定性(分半/按年方向/样本量)
  - 价格源: trade-data 双树 index json(csi500/hs300 与主树 md5 一致已验证)

【防前视】(§5.1⑥) 阈值全为固定常数(冻结值=2016-2020 选段 q30, 实测 csi1000-hs300 q30=-3.5242
  与冻结值逐位一致; 代理因子 csi500-hs300 同窗 q30=-2.54 仅供对照); 无全期分位、无滚动拟合;
  sticky 只用当日及之前因子; 时点穿越 3 时点全 PASS(见 s06_segment_style_backtest.py C 节)。

【输入依赖】
  - /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json(+signal_kelly_backtest.json+kelly_loss_features.json)
  - /Users/linhuichen/code/trade-data/static-site/data/index/{hs300,csi500,cyb,sh}-all.json(只读)
【输出】stdout 全表(方法/阈值/K/稳定性); 本文件即报告数据源
【关键参数种子】THRESHOLD=-3.524224785046781 CONFIRM_DAYS=15 MIN_HOLD=10 K∈{1,2,3}
【复现命令】python3 docs/kelly/analysis/scripts/s06_segment_style_exhaustive.py
【诚实标注】2011-2014 段样本极小(16~25 笔/基座), 净利差异(数百元)统计显著性弱; 阈值扫描存在
  平台区(-5~-2 全谱中 -4.00~-2.00 段净利 5,943~6,102 元区间内波动), 冻结值 -3.524 在平台内,
  非段内最优点(-4.00 微优 +158 元)但为 2016-2020 q30 防前视冻结常数, 设计承诺不重新调参;
  属方案选择依据, 非实盘结论
"""
import sys, json, collections
sys.path.insert(0, '/Users/linhuichen/code/trade/docs/kelly/analysis/scripts')
import kelly_s06_offbase_verify as K

TD = K.TD; fIdx = K.fIdx; quads = K.quads
IDX = '/Users/linhuichen/code/trade-data/static-site/data/index/'

def load_idx(n):
    d = json.load(open(f'{IDX}/{n}-all.json'))['ohlc']
    return {str(x['date']): float(x['close']) for x in d if x.get('close') is not None}
def roll(series, dates, n):
    vals = [series.get(d) for d in dates]
    out = {}
    for i in range(n, len(vals)):
        if vals[i] is None or vals[i-n] is None: continue
        out[dates[i]] = (vals[i]/vals[i-n]-1)*100
    return out
hs = load_idx('hs300'); c5 = load_idx('csi500'); cyb = load_idx('cyb'); sh = load_idx('sh')
alldates = sorted(hs)
r_hs = roll(hs, alldates, 20); r_c5 = roll(c5, alldates, 20); r_cyb = roll(cyb, alldates, 20); r_sh = roll(sh, alldates, 20)
SEG = [d for d in alldates if '20100101' <= d < '20141114']
c5hs = {d: (r_c5[d]-r_hs[d]) for d in alldates if d in r_c5 and d in r_hs}
cybsh = {d: (r_cyb[d]-r_sh[d]) for d in alldates if d in r_cyb and d in r_sh}

def build_base_hs300(th, seg_dates):
    out = {}
    for i, d in enumerate(seg_dates):
        if i == 0: out[d] = 'new14'
        else:
            pv = r_hs.get(seg_dates[i-1])
            out[d] = 'a9' if (pv is not None and pv > th) else 'new14'
    return out
def build_base_spread(factor, threshold, seg_dates, on='a9', off='new14'):
    out = {}
    for i, d in enumerate(seg_dates):
        if i == 0: out[d] = off
        else:
            pv = factor.get(seg_dates[i-1])
            out[d] = on if (pv is not None and pv < threshold) else off
    return out
def build_base_sticky(factor, threshold, seg_dates, on='a9', off='new14', confirm=15, min_hold=10, rev=False):
    out = {}; cur = off; broken = 0; held = 0; prev = None
    for d in seg_dates:
        if prev is None:
            ex = off
        else:
            p = factor.get(prev)
            hit = (p is not None and ((p < threshold) if not rev else (p > threshold)))
            if cur == on:
                broken = 0 if hit else broken+1
                held += 1
                stay = (broken < confirm) or (held < min_hold)
                ex = on if stay else off
                if not stay: held = 0
            else:
                ex = on if hit else off
                if ex == on: held = 1; broken = 0
        out[d] = ex
        cur = ex; prev = d
    return out

def baseKey(t):
    return '|'.join([str(t[fIdx['signal_date']] or ''), str(t[fIdx['index_id']] or ''), str(t[fIdx['signal']] or ''),
                     str(t[fIdx['buy_date']] or ''), str(t[fIdx['etf_code']] or '')])
seen = set(); uniq = []
for qk, md in quads.items():
    for mk, arr in md.items():
        for t in arr:
            bk = baseKey(t)
            if bk not in seen: seen.add(bk); uniq.append(t)
OLD = [t for t in uniq if '20110119' <= str(t[fIdx['buy_date']] or '') <= '20141113']
RRANK = {'high': 0, 'mid': 1, 'low': 2, '': 3}
SRANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3, '': 9}

def run_seg(base_map_seg, K_param=1):
    passed = []
    for t in OLD:
        sd = str(t[fIdx['signal_date']] or '')
        base = base_map_seg.get(sd)
        if base is None: continue
        f = K.filtersForBase(base)
        if K.passesFade(t, f, K.activeMonthMask(f)): passed.append(t)
    byDate = collections.defaultdict(list)
    for t in passed: byDate[str(t[fIdx['signal_date']] or '')].append(t)
    kept = []
    for sd, rows in byDate.items():
        rows.sort(key=lambda x: (-(float(x[fIdx['track_score']]) if x[fIdx['track_score']] is not None else -1000),
                                 RRANK.get(str(x[fIdx['rating']] or ''), 3),
                                 SRANK.get(str(x[fIdx['signal']] or ''), 9),
                                 str(x[fIdx['buy_date']] or '')))
        kept += rows[:K_param]
    total = 0; wins = 0; per = []
    for t in kept:
        amt = 10000.0 / min(K_param, len(byDate[str(t[fIdx['signal_date']] or '')])) if K_param > 0 else 10000
        r = K.recompute(t, K.ETFDEF, amt)
        total += r['profit']; per.append((t, r['profit']))
        if r['profit'] > 0: wins += 1
    return {'n_pass': len(passed), 'n_kept': len(kept), 'total': round(total, 2),
            'wins': wins, 'wr': round(wins/len(kept)*100, 1) if kept else 0, 'per': per}
def yearly(res):
    y = collections.defaultdict(lambda: [0, 0, 0])
    for t, p in res['per']:
        k = str(t[fIdx['buy_date']] or '')[:4]
        y[k][0] += 1; y[k][1] += p; y[k][2] += (1 if p > 0 else 0)
    return {k: {'n': v[0], 'total': round(v[1], 2), 'wr': round(v[2]/v[0]*100, 1)} for k, v in sorted(y.items())}
def a9days(bm): return sum(1 for d in SEG if bm.get(d) == 'a9')

def make_base(fname, mode, th):
    if fname == 'hs300':
        return build_base_hs300(th, SEG) if mode == 's' else build_base_sticky(
            {d: r_hs[d] for d in SEG if d in r_hs}, th, SEG, rev=True)
    elif fname == 'c5hs':
        return build_base_spread(c5hs, th, SEG) if mode == 's' else build_base_sticky(c5hs, th, SEG)
    else:
        return build_base_spread(cybsh, th, SEG) if mode == 's' else build_base_sticky(cybsh, th, SEG)

# ── 分位数(2016-2020 q30 冻结值对照 + q10/q30/q50) ──
FROZEN = -3.524224785046781
post1619 = sorted(v for d, v in c5hs.items() if '20160101' <= d <= '20201231' and v == v)
def q(vals, p):
    vals = sorted(vals); i = int(len(vals)*p)
    return vals[min(i, len(vals)-1)]
qc30 = q(post1619, 0.30)
print(f'[参考] csi500-hs300 spread 2016-2020 分布: n={len(post1619)} q30={qc30:.4f}(冻结值={FROZEN:.4f}) q10={q(post1619,0.10):.4f} q50={q(post1619,0.50):.4f}')

# ── 阈值全谱(方案2 sticky) ──
ths = [round(x, 2) for x in ([FROZEN] + [i*0.25 for i in range(int(-5*4), int(-2*4)+1)] + [-4.0, 0.0, 2.0, 4.0, qc30, q(post1619,0.10), q(post1619,0.50)])]
ths = sorted(set(ths))
print(f'\n=== 方案2(csi500-hs300) sticky 阈值全谱 ===')
print(f'{"阈值":>12} {"a9天":>6} {"通过":>5} {"保留":>5} {"净利":>11} {"胜率":>6} | 按年(2011/13/14)')
for th in ths:
    bm = build_base_sticky(c5hs, th, SEG)
    r = run_seg(bm)
    y = yearly(r)
    ystr = ' '.join(f'{k}:{v["n"]}笔{v["total"]:,.0f}' for k, v in y.items())
    print(f'{th:>12.4f} {a9days(bm):>6} {r["n_pass"]:>5} {r["n_kept"]:>5} {r["total"]:>11,.2f} {r["wr"]:>6}% | {ystr}')

# ── K 档敏感性 ──
print(f'\n=== K 档敏感性(方案2 sticky th={FROZEN}) ===')
for kk in [1, 2, 3]:
    r = run_seg(build_base_sticky(c5hs, FROZEN, SEG), K_param=kk)
    print(f'K={kk}: 通过{r["n_pass"]} 保留{r["n_kept"]} 净利{r["total"]:>11,.2f} 胜率{r["wr"]}%')

# ── 三方案对照(冻结阈值) ──
print(f'\n=== 三方案 (冻结阈值效价对照) ===')
C = [
    ('方案1 hs300>0 sticky', 'hs300', 0.0, 'st'),
    ('方案2 c5hs<-3.524 sticky', 'c5hs', FROZEN, 'st'),
    ('方案3 cyb-sh<-3.524 sticky', 'cybsh', FROZEN, 'st'),
]
for label, fname, th, mode in C:
    bm = make_base(fname, mode, th)
    r = run_seg(bm)
    print(f'{label:28s}: a9={a9days(bm)}/{len(SEG)} 通过{r["n_pass"]} 保留{r["n_kept"]} 净利{r["total"]:>11,.2f} 胜率{r["wr"]}% | 按年 {yearly(r)}')

# ── 稳定性 ──
print(f'\n=== 稳定性(方案2 sticky th={FROZEN}) ===')
r = run_seg(build_base_sticky(c5hs, FROZEN, SEG))
per = sorted(r['per'], key=lambda x: str(x[0][fIdx['buy_date']]))
half = len(per)//2
f1 = sum(x[1] for x in per[:half]); f2 = sum(x[1] for x in per[half:])
y = yearly(r)
neg = [k for k,v in y.items() if v['total'] < 0]; pos = [k for k,v in y.items() if v['total'] > 0]
print(f'分半: 前段 n={half} 净利{f1:,.2f} | 后段 n={len(per)-half} 净利{f2:,.2f}; 方向: 正年{pos} 负年{neg}')
print(f'样本量: 段内保留 {r["n_kept"]} 笔(2011-2014), 110 笔老信号; 每方案报告 n 与统计显著性强弱')
