#!/usr/bin/env python3
"""s06_newsem_vs_14plus1.py - S06 held 新语义(codex008 F2)同引擎回测对照(2026-08-26)

【目的】held 语义修复(a9 生效交易日数, 进入当日计 1)后, 用与 s06_vs_14plus1_same_engine.py
完全相同的引擎(mine28.simulate + top1_combined A/P14PLUS1)重跑新旧两种语义的验证段对照,
产出新公示锚点数字(净利/mdd/强平), 并与旧语义同日重跑值对比(分年差诚实标注)。
【方法口径】唯一变量=sticky_array 的 held 语义; 其余(top1/交易日历/费率/VAL 段)逐位同构。
【输入依赖】signal_kelly_trades.json / mine28_regime_rotation.py(docs/kelly/analysis/scripts/
  sim_window_loss_mining_20260822/) / external_factor_v6*.py(/tmp/codex-auto/, codex 工作副本)
【输出】data/s06_newsem_vs_results.json + stdout 摘要
【复现命令】python3 /tmp/s06_newsem_vs_14plus1.py
"""
import sys, json, inspect

import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))  # 落档: 同目录 external_factor_v6*.py 副本(原 /tmp/codex-auto)
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

VAL = ('20210101', '20261231')


def sticky_array_sem(cal, F, pred, new_sem, on='A', off='NEW', confirm=15, minhold=10):
    """new_sem=True: codex008 F2 新语义(held=生效交易日数, 进入当日计 1, 每交易日递增无论命中);
       new_sem=False: 旧语义(held 只在命中日 +1, codex 定性 P0 锁死缺陷, 对照用)。"""
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


def build_14plus1():
    tr, fIdx = load(_ROOT + '/static-site/data/signal_kelly_trades.json')
    R.FIDX_CACHE = fIdx; R.IDX_PNL, R.IDX_SKEY = len(fIdx) + 3, len(fIdx) + 4
    RR = {'high': 0, 'mid': 1, 'low': 2}; SR = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    pool = build_mode_pool(tr, fIdx, 'A')
    for t in pool:
        t.append(R.calc_row(t, fIdx))
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None, '') else float('inf')
        t.append((-ts, RR.get(str(t[fIdx['rating']] or ''), 3), SR.get(str(t[fIdx['signal']] or ''), 9), str(t[fIdx['buy_date']] or '')))
    feats = json.load(open(FEATS_PATH)); rules = build_rules(feats, fIdx); rules.update(build_r2(fIdx))
    m24 = json.load(open(MINE + '/data/mine24_compare.json')); keys = list(m24['new_keys'])
    hist = [k for k in DEFAULT_FILTERS if k != 'excludeMonthDummy']; mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2
    blk = set()
    for c in keys:
        if c in hist:
            f = {kk: False for kk in DEFAULT_FILTERS}; f[c] = True
            blk |= {base_key(t, fIdx) for t in pool if not passes_fade(t, fIdx, f, active_month_mask(f), mD, eD, rD)}
        else:
            blk |= {base_key(t, fIdx) for t in pool if rules[c](t)}
    blk |= {base_key(t, fIdx) for t in pool if str(t[fIdx['track_tier']] or '') == 'none'}
    g = {}
    for t in pool:
        g.setdefault(str(t[0]), []).append((base_key(t, fIdx), t))
    for sd in g:
        g[sd].sort(key=lambda kt: kt[1][R.IDX_SKEY])
    top1 = {}
    for sd in sorted(g):
        n = 0
        for key, t in g[sd]:
            if key not in blk:
                top1.setdefault('P14PLUS1', {})[sd] = t; n += 1
            if n >= 1:
                break
    return top1


def metrics(top1, arr, label):
    full = m.simulate(arr, cal, top1, VAL); forced = m.simulate(arr, cal, top1, VAL, cost='forced')
    return {'label': label,
            'validation': {k: full[k] for k in ['total', 'n', 'win_rate', 'mdd', 'trough', 'years_pos', 'pos_month_share', 'worst_month', 'peak_pos', 'switches_per_yr']},
            'yearly': full['yearly'],
            'forced': {k: forced[k] for k in ['total', 'mdd', 'win_rate', 'switches_per_yr']}}


# Runtime
src = inspect.getsource(m.build_schemes)
stale = "assert abs(got[m] - exp[m]) < 1.0, ('anchor FAIL', m, got[m], exp[m])"
exec(src.replace(stale, 'pass'), m.__dict__)
_, top1_base, meta = m.build_schemes(); m.fIdxG = meta['fIdx']
top1_plus = build_14plus1()
F, cal = b.build_struct_features(); th = -3.524224785046781
top1_combined = {**top1_base, **top1_plus}

pred = lambda f, d: f['size_spread'].get(d, -999) < th
out = {'method': {'engine': 'mine28.simulate same engine as s06_vs_14plus1_same_engine.py',
                  'sem_change': 'codex-claude2codex-20260826-008 F2: held=a9生效交易日数(进入当日计1)',
                  'rerun_date': '2026-08-26'}, 'results': {}}
for name, ns in [('OLD_sem_held_hitonly', False), ('NEW_sem_held_effective_days', True)]:
    s06 = sticky_array_sem(cal, F, pred, ns, confirm=15, minhold=10)
    s06_on_plus = ['A' if mode == 'A' else 'P14PLUS1' for mode in s06]
    out['results'][name] = metrics(top1_combined, s06_on_plus, name)

json.dump(out, open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'data', 's06_newsem_vs_results.json'), 'w'), ensure_ascii=False, indent=2)
old_v = out['results']['OLD_sem_held_hitonly']; new_v = out['results']['NEW_sem_held_effective_days']
print('OLD val', old_v['validation']['total'], 'mdd', old_v['validation']['mdd'], 'forced', old_v['forced']['total'])
print('NEW val', new_v['validation']['total'], 'mdd', new_v['validation']['mdd'], 'forced', new_v['forced']['total'])
print('yearly diff (NEW-OLD):')
for y in sorted(new_v['yearly']):
    print(' ', y, round(new_v['yearly'][y] - old_v['yearly'].get(y, 0), 2),
          f"(old={old_v['yearly'].get(y, 0)}, new={new_v['yearly'][y]})")
