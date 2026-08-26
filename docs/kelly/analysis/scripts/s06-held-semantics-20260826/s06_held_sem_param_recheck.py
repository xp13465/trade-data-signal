#!/usr/bin/env python3
"""s06_held_sem_param_recheck.py - S06 冻结参数在新 held 语义下的稳定性复核(codex008 F2 配套独立件, 2026-08-26)

【目的】q30(th=-3.524224785046781)/cd15/minhold10 是旧 held 语义(held 只在命中日递增)下选出的冻结参数。
held 语义修复为「a9 生效交易日数(进入当日计 1)」后, 用同引擎(mine28.simulate + build_struct_features
size_spread)在新语义下重跑 q×cd 敏感性全网格, 回答三问:
  ①现冻结参数(q30/cd15)在新语义选段排名是否仍稳;
  ②新旧语义各自的网格最优组合是什么、是否漂移;
  ③现生产参数(minhold=10 与网格派生值 cd//2=7 不同)单独口径的验证段表现。
⚠只出数据不动参数: 参数是否变更另行拍板(§23.7 冻结契约), 本脚本结论不自动改 THRESHOLD/CONFIRM_DAYS。
【方法口径】完全参照 codex 冻结骨架 /tmp/codex-auto/s06_grid_selection_freeze.py: qs=[.2,.25,.3,.4,.5,.6]
  × cd=[10,15,20,25,30], minhold=max(cd//2,5); 阈值=2016-2020 选段 trailing 分位(非全史/验段, 防前视 §5.1⑥);
  选段 SEL=20160101~20201231 排序(selection_total 降序, switches 升序), 验证段 VAL=20210101 起。
【输入依赖】signal_kelly_trades.json / mine28_regime_rotation(docs/kelly/analysis/scripts/
  sim_window_loss_mining_20260822/) / external_factor_v6*.py(/tmp/codex-auto/, codex 工作副本,
  落档副本见同目录 external_factor_v6_copy_20260826/);
【输出】data/s06_held_sem_param_recheck.json + stdout 摘要
【复现命令】python3 scripts/s06_held_sem_param_recheck.py
【数据截止】signal_kelly_trades.json 与 csi1000/hs300-all.json 截至 2026-08-26; 结果数字随数据更新会漂移
  (S06 动态回测特性, 见 gen_kelly_mode_s06_state.py 头部锚点漂移标注)。
"""
import sys, json, inspect

sys.path.insert(0, '/tmp/codex-auto')
MINE = '/Users/linhuichen/code/trade/docs/kelly/analysis/scripts/sim_window_loss_mining_20260822'
sys.path.insert(0, MINE)
import mine28_regime_rotation as m
import external_factor_v6 as e
import external_factor_v6b as b
from r2_common import _ROOT
from sim_core import load, build_mode_pool, passes_fade, active_month_mask, DEFAULT_FILTERS, base_key
import r2_common as R
from mine18_detail import FEATS_PATH
from mine21_bigtour import build_rules
from mine22_joint import build_r2

SEL = ('20160101', '20201231'); VAL = ('20210101', '20261231')
QS = [.2, .25, .3, .4, .5, .6]; CDS = [10, 15, 20, 25, 30]


def sticky_array_sem(cal, F, pred, new_sem, on='A', off='NEW', confirm=15, minhold=10):
    """与 gen/check 同源的 sticky 状态机; new_sem=True=codex008 F2 新语义(held=生效日数),
    False=旧语义(held 只在命中日+1, 对照用)。"""
    out = []; cur = 'NEW'; broken = 0; held = 0; prev = None
    for d in cal:
        if prev is None:
            ex = off
        else:
            p = pred(F, prev)
            if cur == on:
                if p:
                    broken = 0
                else:
                    broken += 1
                if new_sem:
                    held += 1
                elif p:
                    held += 1
                stay = (broken < confirm) or (held < minhold)
                ex = on if stay else off
                if not stay:
                    held = 0
            else:
                ex = on if p else off
                if ex == on:
                    held = 1 if new_sem else 0
                    broken = 0
        cur = ex; out.append(ex); prev = d
    return out


def main():
    # 引擎 runtime(去锚点断言, 同冻结骨架)
    src = inspect.getsource(m.build_schemes)
    stale = "assert abs(got[m] - exp[m]) < 1.0, ('anchor FAIL', m, got[m], exp[m])"
    exec(src.replace(stale, 'pass'), m.__dict__)
    _, top1, meta = m.build_schemes(); m.fIdxG = meta['fIdx']
    F, cal = b.build_struct_features()

    # 选段 trailing 分位阈值(防前视: 只用 2016-2020 数据)
    ds = sorted(d for d in cal if d in F['size_spread'] and '20160101' <= d <= '20201231')
    vs = [F['size_spread'][d] for d in ds]
    ths = {q: sorted(vs)[int(len(vs) * q)] for q in QS}
    print('thresholds:', {f'q{int(q*100)}': round(t, 6) for q, t in ths.items()}, flush=True)

    out = {'method': {'engine': 'mine28.simulate + build_struct_features size_spread',
                      'grid': 'qs=.2/.25/.3/.4/.5/.6 x cd=10/15/20/25/30, minhold=max(cd//2,5)',
                      'sem_note': 'codex008 F2: NEW=held生效交易日数(进入当日计1); OLD=held只命中日计数',
                      'rerun_date': '2026-08-26'}, 'thresholds': {str(q): t for q, t in ths.items()},
            'results': {}}
    for sem_name, ns in [('OLD_sem', False), ('NEW_sem', True)]:
        rows = []
        for q, th in zip(QS, ths.values()):
            pred = lambda f, d, t=th: f['size_spread'].get(d, -999) < t
            for cd in CDS:
                arr = sticky_array_sem(cal, F, pred, ns, confirm=cd, minhold=max(cd // 2, 5))
                s = m.simulate(arr, cal, top1, SEL)
                rows.append({'q': f'q{int(q*100)}', 'threshold': round(th, 6), 'confirm': cd,
                             'selection_total': round(s['total'], 2), 'selection_mdd': round(s['mdd'], 2),
                             'switches_per_yr': s['switches_per_yr']})
        rows.sort(key=lambda r: (r['selection_total'], -r['switches_per_yr']), reverse=True)
        best = rows[0]
        # 最优组合验证段
        bq = float(best['q'][1:]) / 100; bcd = best['confirm']
        bth = ths[bq]; bns = ns
        pred_b = lambda f, d, t=bth: f['size_spread'].get(d, -999) < t
        arr_b = sticky_array_sem(cal, F, pred_b, bns, confirm=bcd, minhold=max(bcd // 2, 5))
        val_b = m.simulate(arr_b, cal, top1, VAL)
        # 现冻结参数(q30/cd15, 网格派生 minhold=7)验证段
        pred_f = lambda f, d: f['size_spread'].get(d, -999) < ths[.3]
        arr_f = sticky_array_sem(cal, F, pred_f, bns, confirm=15, minhold=max(15 // 2, 5))
        val_frozen_grid = m.simulate(arr_f, cal, top1, VAL)
        rank_q30_cd15 = next(i + 1 for i, r in enumerate(rows) if r['q'] == 'q30' and r['confirm'] == 15)
        out['results'][sem_name] = {
            'best': best, 'best_validation': e.compact(val_b),
            'q30_cd15_rank_of_30': rank_q30_cd15,
            'q30_cd15_validation_minhold7': e.compact(val_frozen_grid),
            'top10': rows[:10], 'all': rows}
        print(f"[{sem_name}] BEST={best} rank(q30,cd15)={rank_q30_cd15}/30", flush=True)
        print(f"  best_val={e.compact(val_b)}", flush=True)
        print(f"  q30cd15_val={e.compact(val_frozen_grid)}", flush=True)

    # 现生产参数精确口径: q30/cd15/minhold10 新语义验证段(与快照引擎逐位同构)
    pred_p = lambda f, d: f['size_spread'].get(d, -999) < ths[.3]
    arr_p = sticky_array_sem(cal, F, pred_p, True, confirm=15, minhold=10)
    val_prod = m.simulate(arr_p, cal, top1, VAL)
    forced_prod = m.simulate(arr_p, cal, top1, VAL, cost='forced')
    out['results']['NEW_sem_production_minhold10'] = {
        'note': 'q30/cd15/minhold10(生产冻结值, minhold≠网格派生7)',
        'validation': e.compact(val_prod), 'forced': e.compact(forced_prod)}
    print('PROD(minhold10) NEW val=', e.compact(val_prod), flush=True)

    with open('/tmp/s06_held_sem_param_recheck.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('saved /tmp/s06_held_sem_param_recheck.json')


if __name__ == '__main__':
    main()
