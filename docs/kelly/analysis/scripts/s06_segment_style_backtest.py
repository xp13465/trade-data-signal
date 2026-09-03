# -*- coding: utf-8 -*-
"""s06_segment_style_backtest.py - S06 快照「2014 前分段风格判定」候选方案回测(研究, 只读不改)

【目的】S06 快照覆盖期 20141114 起(csi1000 最早 20141017, 去 20 日 LOOKBACK), 2011-2014 段 110 笔
老信号(20110119~20141113, unique base, 全 rating_low)现按 off_base(NEW14)永久兜底过滤。本脚本回测
「2014 前用其他有历史指数的源判进攻/防守」候选方案, 数据说话选最优, 消灭 110 笔永久兜底。

【方法口径】(前端同构, 复用 docs/kelly/analysis/scripts/kelly_s06_offbase_verify.py 的 passesFade/
activeMonthMask/filtersForBase/recompute 逐位口径; 该脚本已与权威 trade-method-final-repro.mjs 对账,
2011/2012/2013 段数字逐位一致 504.04/1013.19/1626.51)
  - 信号: signal_kelly_trades.json 全象限按 baseKey 去重, 窗口 buy_date∈[20110119, 20141113]
  - 判定: T 日收盘因子 → T+1 生效; 纯阈值版(spread<th→a9)与 sticky 版(同现快照
    CONFIRM_DAYS=15/MIN_HOLD=10)两种
  - 过滤: 按 signal_date(==buy_date)读 per-date base → a9/new14 键集 passesFade(月门+T1 spec)
  - 口径: K=1 每日池等分(每笔 10000) → recompute(etf_main 费率) → 净利/胜率/按年
  - 候选: 方案1 hs300_ret20(单指数, 用户点名); 方案2 csi500_ret20-hs300_ret20(与现因子同构);
          方案3 cyb_ret20-sh_ret20(成长-大盘); 阈值沿用现冻结 -3.524(方案2/3)或按分布扫描(方案1)
【防前视】阈值全为固定常数(2016-2020 q30 冻结值 / 或 0、±2、±4 扫描值, 均不依赖未来数据);
  sticky 状态机只用当日及之前因子; 时点穿越测试(截断重算)3 时点全 PASS(见输出)
【输入依赖】
  - /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json(+signal_kelly_backtest.json+kelly_loss_features.json)
  - /Users/linhuichen/code/trade/static-site/data/kelly_mode_s06_state.json(现快照, 2014 后段基准)
  - /Users/linhuichen/code/trade-data/static-site/data/index/{hs300,csi500,cyb,sh}-all.json(只读)
【输出】stdout 全表(候选方案清单+回测数据表); 本文件即报告数据源
【关键参数种子】THRESHOLD=-3.524224785046781(现冻结值) CONFIRM_DAYS=15 MIN_HOLD=10 K=1
【复现命令】python3 docs/kelly/analysis/scripts/s06_segment_style_backtest.py
【诚实标注】2011-2014 段样本极小(16~25 笔), 净利差异(数百元)统计显著性弱; 方案2 改进集中在
  2013-2014(+698), 2011-2012 反而 -357; 属方案选择依据, 非实盘结论
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

def main():
    print(f'SEG {len(SEG)} 天 (20110104~20141113); 110 笔老信号 {len(OLD)}')
    print('=' * 104)
    print('A. 极端对照(无分段)')
    for base in ['a9', 'new14']:
        r = run_seg({d: base for d in SEG})
        print(f'  全段 {base:5s}: 通过{r["n_pass"]} K=1保留{r["n_kept"]} 净利{r["total"]:>11,.2f} 胜率{r["wr"]}% | 按年 {yearly(r)}')
    print('=' * 104)
    print('B. 候选方案(2014前动态; sticky 参数 15/10 同现快照; 阈值沿用 -3.524 或扫描)')
    C = [
        ('方案1 hs300_ret20>0  纯', 'hs300', 0.0, 's'),
        ('方案1 hs300_ret20>0  sticky', 'hs300', 0.0, 'st'),
        ('方案1 hs300_ret20>-2 纯', 'hs300', -2.0, 's'),
        ('方案1 hs300_ret20>-4 纯', 'hs300', -4.0, 's'),
        ('方案2 csi500-hs300<-3.524 纯', 'c5hs', -3.524224785046781, 's'),
        ('方案2 csi500-hs300<-3.524 sticky', 'c5hs', -3.524224785046781, 'st'),
        ('方案2 csi500-hs300<-2  纯', 'c5hs', -2.0, 's'),
        ('方案2 csi500-hs300<-5  纯', 'c5hs', -5.0, 's'),
        ('方案2 sticky th=-4.0(微调)', 'c5hs', -4.0, 'st'),
        ('方案3 cyb-sh<-3.524 纯', 'cybsh', -3.524224785046781, 's'),
        ('方案3 cyb-sh<-3.524 sticky', 'cybsh', -3.524224785046781, 'st'),
        ('方案3 cyb-sh<0    纯', 'cybsh', 0.0, 's'),
    ]
    for label, fname, th, mode in C:
        if fname == 'hs300':
            bm = build_base_hs300(th, SEG) if mode == 's' else build_base_sticky(
                {d: r_hs[d] for d in SEG if d in r_hs}, th, SEG, rev=True)
        elif fname == 'c5hs':
            fs = {d: c5hs[d] for d in SEG if d in c5hs}
            bm = build_base_spread(fs, th, SEG) if mode == 's' else build_base_sticky(fs, th, SEG)
        else:
            fs = {d: cybsh[d] for d in SEG if d in cybsh}
            bm = build_base_spread(fs, th, SEG) if mode == 's' else build_base_sticky(fs, th, SEG)
        r = run_seg(bm); ad = a9days(bm)
        print(f'  {label:32s}: a9={ad}/{len(SEG)} ({ad/len(SEG)*100:.0f}%) 通过{r["n_pass"]} 保留{r["n_kept"]} '
              f'净利{r["total"]:>11,.2f} 胜率{r["wr"]}% | 按年 {yearly(r)}')
    print('=' * 104)
    print('C. 防前视时点穿越测试(截断重算 vs 全量逐位一致)')
    for t in ['20111231', '20130628', '20140331']:
        dates = sorted(d for d in SEG if d <= t)
        tr = build_base_sticky(c5hs, -3.524224785046781, dates)
        fu = build_base_sticky(c5hs, -3.524224785046781, SEG)
        mism = sum(1 for d in tr if d in fu and tr[d] != fu[d])
        print(f'  截断到 {t}: 重算 {len(tr)} 天, 不一致 {mism} -> {"PASS" if mism == 0 else "FAIL"}')

if __name__ == '__main__':
    main()
