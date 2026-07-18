#!/usr/bin/env python3
"""策略实验室二次测试 - 荣誉共享标注预计算

为 retest 维度榜生成"荣誉表" lab_retest_honors.json：每个策略配对(pairKey)
在 9指数 × 5窗口(all/y10/y5/y3/y1) 下，按"综合分(二次测试)"排名，记录其
排进 Top3(第1/2/3) 的所有(指数,窗口)组合。前端在 retest 排行榜每行用小徽章
标注该策略在"其他"条件下的排名荣誉(当前选中条件不重复标)，多层次定位好排名策略。

排名口径与前端 _labRetestRankRows(static-site/lab.js) 逐字一致：
  score = 0.3*wholeScore + 0.25*yearlyScore + 0.25*oosScore + 0.2*regimeScore
  wholeScore = 0.4*retN + 0.3*winN + 0.2*(1-ddN) + 0.1*nN   (ret/win/dd/n 取自
              lab_sim_<idx>_stats.json 的 stats[win]，随窗口变，权重30%)
  yearly/oos/regime 综合分 取自 lab_retest_<idx>.json 的切片(与窗口无关)
  min-max 归一化 across 该指数全部 pair 的(全仓+定额10%)双模式行
  pairKey 的代表分 = 其双模式 score 的较大值(策略最佳表现)，据此降序排名

输入(均已由 lab_retest.py / lab_simulate.py 生成，读 static-site/data/lab/):
  lab_retest_<idx>.json        9 个指数
  lab_sim_<idx>_stats.json     9 个指数(供 wholeScore 5窗口切换)
输出(与 lab_retest.py 一致):
  static-site/data/lab/lab_retest_honors.json
  结构: { pairKey: [ {idx, win, rank}, ... ], ... }   # rank<=3 的全部荣誉, 按 rank 升序
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from lab_simulate import SIM_INDEXES  # 9 指数 [(id,name),...]

# 与前端 LAB_WIN_DEFS(static-site/lab.js:792) 一致的 5 窗口
LAB_WIN_DEFS = ['all', 'y10', 'y5', 'y3', 'y1']


def _minmax(rows, key):
    """min-max 归一化工厂：返回 fn(v)->0~1。None 返回 0.5(中性，与前端 _labRetestMinMax 一致)。
    min/max 仅在非 None 值上算；全 None 或恒定值时返回恒 0.5。"""
    vals = [r.get(key) for r in rows if r.get(key) is not None]
    if not vals:
        return lambda v: 0.5
    mn, mx = min(vals), max(vals)
    rng = mx - mn
    if rng == 0:
        return lambda v: 0.5
    return lambda v: 0.5 if v is None else (v - mn) / rng


def _extract(pk, data, mode, sim_data, win_key):
    """从单个 pair 的 data(top-level=full_in 或 fixed_10k)提取一行原始指标。
    与前端 _labRetestRankRows.extract(static-site/lab.js:2977) 逐字一致。
    simData stats 为百分数(10.87)，pair_meta 为小数(0.1087)，统一为小数。"""
    meta = data.get('pair_meta') or {}
    ret = meta.get('ret') if meta.get('ret') is not None else 0
    win_rate = meta.get('win') if meta.get('win') is not None else 0
    dd = meta.get('dd') if meta.get('dd') is not None else 0
    n = meta.get('n') if meta.get('n') is not None else 0
    strat = meta.get('strategy') or pk
    if sim_data and strat:
        parts = strat.split('|')
        pd2 = (sim_data.get('pairs') or {}).get(parts[0] + '|' + parts[1])
        if pd2:
            md = pd2.get(mode) or {}
            stats = md.get('stats') or {}
            s = stats.get(win_key)
            if s:
                ret = s.get('total_ret', 0) / 100
                win_rate = s.get('win_rate', 0) / 100
                dd = s.get('max_drawdown', 0) / 100
                n = s.get('n_trades', 0)
    yearly = data.get('yearly') or {}
    y_keys = sorted(yearly.keys())
    year_rets = [yearly[y]['ret'] for y in y_keys
                 if yearly.get(y) and yearly[y].get('ret') is not None]
    min_year_ret = min(year_rets) if year_rets else 0
    profit_years = sum(1 for v in year_rets if v > 0)
    profit_year_ratio = profit_years / len(year_rets) if year_rets else 0
    year_vol = 0.0
    if len(year_rets) > 1:
        mean = sum(year_rets) / len(year_rets)
        year_vol = (sum((v - mean) ** 2 for v in year_rets) / len(year_rets)) ** 0.5
    oos = data.get('oos') or {}
    tr = oos.get('train') or {}
    te = oos.get('test') or {}
    test_ret = te.get('ret') if te.get('ret') is not None else 0
    overfit = (abs(tr.get('ret', 0) - te.get('ret', 0))
               if (tr.get('ret') is not None and te.get('ret') is not None) else 0)
    test_win = te.get('win') if te.get('win') is not None else 0
    regimes = data.get('regimes') or {}
    crash = regimes.get('crash2015')
    bear = regimes.get('bear2018')
    rally = regimes.get('rally2024')
    covid = regimes.get('covid2020')
    return {
        'pk': pk, 'mode': mode, 'strategy': strat,
        'ret': ret, 'win': win_rate, 'dd': dd, 'n': n,
        'minYearRet': min_year_ret, 'profitYearRatio': profit_year_ratio, 'yearVol': year_vol,
        'testRet': test_ret, 'overfit': overfit, 'testWin': test_win,
        'crashDd': crash['dd'] if crash else None,
        'bearDd': bear['dd'] if bear else None,
        'rallyRet': rally['ret'] if rally else None,
        'covidDd': covid['dd'] if covid else None,
        'covidNull': not covid,
    }


def _compute_rows(rd, sim_data, win_key):
    """聚合 retest pairs -> 行(双模式)，算8维综合分 score。
    与前端 _labRetestRankRows(static-site/lab.js:2971) 逐字一致。"""
    pks = list((rd.get('pairs') or {}).keys())
    raw = []
    for pk in pks:
        pd = rd['pairs'].get(pk) or {}
        raw.append(_extract(pk, pd, 'full_in', sim_data, win_key))
        if pd.get('fixed_10k'):
            raw.append(_extract(pk, pd['fixed_10k'], 'fixed_10k', sim_data, win_key))
    if not raw:
        return []
    ret_n = _minmax(raw, 'ret')
    win_n = _minmax(raw, 'win')
    dd_n = _minmax(raw, 'dd')
    n_n = _minmax(raw, 'n')
    min_year_ret_n = _minmax(raw, 'minYearRet')
    year_vol_n = _minmax(raw, 'yearVol')
    test_ret_n = _minmax(raw, 'testRet')
    overfit_n = _minmax(raw, 'overfit')
    test_win_n = _minmax(raw, 'testWin')
    crash_dd_n = _minmax(raw, 'crashDd')
    bear_dd_n = _minmax(raw, 'bearDd')
    rally_ret_n = _minmax(raw, 'rallyRet')
    covid_dd_n = _minmax(raw, 'covidDd')
    out = []
    for r in raw:
        whole = 0.4 * ret_n(r['ret']) + 0.3 * win_n(r['win']) + 0.2 * (1 - dd_n(r['dd'])) + 0.1 * n_n(r['n'])
        yearly_s = (0.4 * min_year_ret_n(r['minYearRet']) + 0.4 * r['profitYearRatio']
                    + 0.2 * (1 - year_vol_n(r['yearVol'])))
        oos_s = (0.4 * test_ret_n(r['testRet']) + 0.4 * (1 - overfit_n(r['overfit']))
                 + 0.2 * test_win_n(r['testWin']))
        crash_norm = 1 - crash_dd_n(r['crashDd'])
        bear_norm = 1 - bear_dd_n(r['bearDd'])
        rally_norm = rally_ret_n(r['rallyRet'])
        if r['covidNull']:
            regime_s = 0.3 * crash_norm + 0.3 * bear_norm + 0.4 * rally_norm
        else:
            covid_norm = 1 - covid_dd_n(r['covidDd'])
            regime_s = 0.25 * crash_norm + 0.25 * bear_norm + 0.25 * rally_norm + 0.25 * covid_norm
        score = 0.3 * whole + 0.25 * yearly_s + 0.25 * oos_s + 0.2 * regime_s
        r2 = dict(r)
        r2['score'] = score
        out.append(r2)
    return out


def build_honors(lab_dir):
    """遍历9指数×5窗口，算每个 pairKey 的 Top3 荣誉。返回 {pairKey:[{idx,win,rank},...]}。"""
    honors = {}
    for iid, iname in SIM_INDEXES:
        retest_path = os.path.join(lab_dir, f'lab_retest_{iid}.json')
        sim_path = os.path.join(lab_dir, f'lab_sim_{iid}_stats.json')
        if not os.path.exists(retest_path):
            print(f'  [skip] {iid}: 缺 {retest_path}')
            continue
        with open(retest_path, encoding='utf-8') as f:
            rd = json.load(f)
        sim_data = None
        if os.path.exists(sim_path):
            with open(sim_path, encoding='utf-8') as f:
                sim_data = json.load(f)
        else:
            print(f'  [warn] {iid}: 缺 {sim_path}，wholeScore 将回退 pair_meta(y5)')
        pks_order = list((rd.get('pairs') or {}).keys())
        n_pairs = len(pks_order)
        for win in LAB_WIN_DEFS:
            rows = _compute_rows(rd, sim_data, win)
            if not rows:
                continue
            # pairKey 代表分 = 双模式 score 较大值(策略最佳表现)
            best = {}
            for r in rows:
                pk = r['pk']
                if pk not in best or r['score'] > best[pk]:
                    best[pk] = r['score']
            # 降序排名；并列按 pks_order 插入序稳定(Python sorted 稳定)
            ranked = sorted(pks_order, key=lambda pk: -best[pk])
            for rank, pk in enumerate(ranked, 1):
                if rank <= 3:
                    honors.setdefault(pk, []).append({'idx': iid, 'win': win, 'rank': rank})
        print(f'  [ok] {iid} ({iname}): {n_pairs} pairs')
    # 每个 pair 的荣誉按 rank 升序排
    for pk in honors:
        honors[pk].sort(key=lambda h: h['rank'])
    return honors


def main():
    print('=== 策略实验室二次测试 荣誉表预计算 ===')
    lab_dir = os.path.join(BASE, 'static-site', 'data', 'lab')
    if not os.path.isdir(lab_dir):
        print(f'ERROR: lab 目录不存在 {lab_dir}')
        sys.exit(1)
    honors = build_honors(lab_dir)
    n_pairs = len(honors)
    n_honors = sum(len(v) for v in honors.values())
    print(f'\n荣誉表: {n_pairs} 个 pair, 共 {n_honors} 条 Top3 荣誉')
    # 写入 static-site(与 lab_retest.py 一致)
    for base_dir in ('static-site',):
        out_path = os.path.join(BASE, base_dir, 'data', 'lab', 'lab_retest_honors.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(honors, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = os.path.getsize(out_path) / 1024
        print(f'  [output] {out_path} ({size_kb:.2f} KB)')
    # 抽样验收
    print('\n抽样验收(前若干 pair 的荣誉):')
    for pk in list(honors.keys())[:3]:
        print(f'  {pk}: {honors[pk]}')
    print('=== 完成 ===')


if __name__ == '__main__':
    main()
