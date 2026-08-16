# -*- coding: utf-8 -*-
"""
目的: 量化「样本外榜『低过拟合』维度 min-max 归一化被极端离群值压平」的影响面
口径: 复刻 static-site/lab.js _labRetestRankRows(L3906-4040):
  overfit = |train_ret - test_ret|(oos 前70%训练/后30%验证切片, 小数)
  低过拟合 = 1 - minmax(overfit)  (across 全部9指数154行: full_in 77 + fixed_10k 77)
  样本外分 oos = 0.4*testRet + 0.4*(1-overfitN) + 0.2*testWin
  综合分 score = 0.3*整体 + 0.25*分年 + 0.25*oos + 0.2*极端
输入: static-site/data/lab/lab_retest_{sh,sz,bj50,csi500,csi1000,cyb,hs300,kc50,sz50}.json
      static-site/data/lab/lab_sim_{idx}_stats.json (整体4维取 y5 stats)
输出: stdout 打印分布/失真占比/排序对照
复现(从项目根): python3 docs/scripts/analyze_oos_normalization_bias.py
     (脚本 BASE 自动回退到 static-site/data/lab,支持从项目根或 docs/scripts/ 直接跑)
数据: lab_retest_*.json 生成于 2026-08-14 19:00(scripts/lab/lab_retest.py), 与线上 R2 同源
背景: 对应报告 docs/lab-out-of-sample-normalization-bias.md;本次修复 = 95%分位截断(p95≈61.85)
"""
import json, os, glob, math, statistics

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
if not os.path.isdir(BASE):  # 支持从项目根调用
    BASE = 'static-site/data/lab'
retest_files = sorted([f for f in glob.glob(os.path.join(BASE, 'lab_retest_*.json')) if 'honors' not in f])

def load_sim(idx):
    try: return json.load(open(os.path.join(BASE, 'lab_sim_%s_stats.json' % idx)))
    except Exception: return None

def _labGetPair(simData, bk, sk):
    return simData and simData.get('pairs', {}).get(bk + '|' + sk)

def extract(meta, pk, mode, m, sd):
    ret = meta.get('ret') or 0; win = meta.get('win') or 0
    dd = meta.get('dd') or 0; n = meta.get('n') or 0
    annualRet = 0.0
    if sd and meta.get('strategy'):
        parts = meta['strategy'].split('|')
        pd2 = _labGetPair(sd, parts[0], parts[1]) if len(parts) == 2 else None
        s = pd2 and pd2.get(mode) and pd2.get(mode).get('stats', {}).get('y5')
        if s:
            ret = s.get('total_ret', 0) / 100; win = s.get('win_rate', 0) / 100
            dd = s.get('max_drawdown', 0) / 100; n = s.get('n_trades', 0)
            annualRet = s.get('annual_ret', 0)
    risk_adj = annualRet / max(dd * 100, 2.0)
    yearly = m.get('yearly', {}) or {}
    yKeys = sorted(yearly.keys())
    yearRets = [yearly[yr]['ret'] for yr in yKeys if yearly.get(yr) and yearly[yr].get('ret') is not None]
    minYearRet = min(yearRets) if yearRets else 0
    profitYearRatio = sum(1 for v in yearRets if v > 0) / len(yearRets) if yearRets else 0
    yearVol = 0.0
    if len(yearRets) > 1:
        mean = sum(yearRets) / len(yearRets)
        yearVol = math.sqrt(sum((v - mean) ** 2 for v in yearRets) / len(yearRets))
    oos = m.get('oos', {}) or {}
    tr = oos.get('train', {}) or {}; te = oos.get('test', {}) or {}
    testRet = te.get('ret') if te.get('ret') is not None else 0
    overfit = abs(tr['ret'] - te['ret']) if (tr.get('ret') is not None and te.get('ret') is not None) else 0.0
    testWin = te.get('win') if te.get('win') is not None else 0
    regimes = m.get('regimes', {}) or {}
    crash = regimes.get('crash2015'); bear = regimes.get('bear2018')
    rally = regimes.get('rally2024'); covid = regimes.get('covid2020')
    return dict(ret=ret, win=win, dd=dd, n=n, risk_adj=risk_adj, minYearRet=minYearRet,
                profitYearRatio=profitYearRatio, yearVol=yearVol, testRet=testRet, overfit=overfit,
                testWin=testWin, crashDd=crash.get('dd') if crash else None,
                bearDd=bear.get('dd') if bear else None, rallyRet=rally.get('ret') if rally else None,
                covidDd=covid.get('dd') if covid else None, covidNull=not covid)

raw = []; allpairs = []; simmap = {}
for f in retest_files:
    rd = json.load(open(f)); idx = rd.get('index_id')
    if idx not in simmap: simmap[idx] = load_sim(idx)
    sd = simmap[idx]
    for pk, pd in rd.get('pairs', {}).items():
        meta = pd.get('pair_meta', {}) or {}
        allpairs.append((idx, rd.get('index_name'), pk, pd))
        for mode, m in [('full_in', pd), ('fixed_10k', pd.get('fixed_10k'))]:
            if m is None: continue
            d = extract(meta, pk, mode, m, sd)
            d.update(index=idx, index_name=rd.get('index_name'), pk=pk, mode=mode,
                     substitute=bool(pd.get('substitute')))
            raw.append(d)

def pctile(vals, p):
    s = sorted(vals); k = (len(s) - 1) * p / 100.0; f = math.floor(k); c = math.ceil(k)
    return s[int(k)] if f == c else s[f] + (s[c] - s[f]) * (k - f)

overfits = [r['overfit'] for r in raw]
print('配对(全9指数): %d  | raw 行: %d (full_in=%d fixed_10k=%d)' % (
    len(allpairs), len(raw), sum(1 for r in raw if r['mode'] == 'full_in'),
    sum(1 for r in raw if r['mode'] == 'fixed_10k')))
print('⭐️主候选(pair): %d  🔵替补(pair): %d' % (
    len(allpairs) - sum(1 for p in allpairs if p[3].get('substitute')),
    sum(1 for p in allpairs if p[3].get('substitute'))))

def minmax_factory(vals):
    mn, mx = min(vals), max(vals); rng = mx - mn
    return (lambda v: 0.5 if rng == 0 else (v - mn) / rng), mn, mx

def low_overfit_stats(transform=None):
    vals = overfits if transform is None else [transform(v) for v in overfits]
    f, mn, mx = minmax_factory(vals)
    lo = [1 - f(v) for v in vals]
    ge95 = sum(1 for v in lo if v >= 0.95); ge99 = sum(1 for v in lo if v >= 0.99)
    return lo, ge95, ge99, mn, mx

print('\n=== 当前归一化(全部行 min-max, max=%.2f) ===' % max(overfits))
lo, ge95, ge99, _, _ = low_overfit_stats()
print('低过拟合 >=0.95: %d/%d (%.1f%%) | >=0.99: %d (%.1f%%) | median=%.4f' % (
    ge95, len(raw), 100.0 * ge95 / len(raw), ge99, 100.0 * ge99 / len(raw), statistics.median(lo)))
for mode in ['full_in', 'fixed_10k']:
    sub = [1 - minmax_factory(overfits)[0](r['overfit']) for r in raw if r['mode'] == mode]
    print('  [%s] >=0.95: %d/%d (%.1f%%) median=%.4f' % (
        mode, sum(1 for v in sub if v >= 0.95), len(sub),
        100.0 * sum(1 for v in sub if v >= 0.95) / len(sub), statistics.median(sub)))

for p in [99, 95]:
    cut = pctile(overfits, p)
    lo2, ge2, _, _, _ = low_overfit_stats(lambda v: min(v, cut))
    print('\n=== 截断重算(p%d=%s) ===' % (p, round(cut, 2)))
    print('低过拟合 >=0.95: %d/%d (%.1f%%) | median=%.4f' % (
        ge2, len(raw), 100.0 * ge2 / len(raw), statistics.median(lo2)))
    for mode in ['full_in', 'fixed_10k']:
        f, _, _ = minmax_factory([min(v, cut) for v in overfits])
        sub = [1 - f(min(r['overfit'], cut)) for r in raw if r['mode'] == mode]
        print('  [%s] >=0.95: %d/%d (%.1f%%) median=%.4f' % (
            mode, sum(1 for v in sub if v >= 0.95), len(sub),
            100.0 * sum(1 for v in sub if v >= 0.95) / len(sub), statistics.median(sub)))

print('\n=== 离群 top8 (按 overfit) ===')
for r in sorted(raw, key=lambda r: -r['overfit'])[:8]:
    print('overfit=%8.2f train=%9.2f test=%7.3f testN=%s mode=%s idx=%s pk=%s' % (
        r['overfit'], r['overfit'] + (r.get('testRet') or 0) - (r.get('testRet') or 0), r['testRet'],
        (r.get('testN') or {}).get('n') if isinstance(r.get('testN'), dict) else '?',
        r['mode'], r['index'], r['pk']))
