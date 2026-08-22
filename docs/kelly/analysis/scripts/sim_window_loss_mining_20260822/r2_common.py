# -*- coding: utf-8 -*-
"""二轮挖掘公共引擎(2026-08-22)。
口径重大纠正(memory filter-backtest-position-fill-caliber):过滤器类规则回测一律用「补位口径」——
按 signal_date 分组 -> 组内剔除命中候选规则的信号 -> 按既有排序取 top-K -> 组内非空才成交。
删笔口径(一轮用法)仅作理想对照副列,不作筛选依据。
基座复用 sim_core.py(mode A + 8键降亏 + K1 + etf_def 费率,v1.1.4 弹窗口径)。
"""
import os, sys, json, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim_core import (load, build_mode_pool, passes_fade, active_month_mask,
                      DEFAULT_FILTERS, topk_by_date, calc_row, base_key, PRIN)

IDX_PNL = None  # 动态: len(fIdx)+3
IDX_SKEY = None

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../../../..'))

def prepare_rows(trades_path=None):
    if trades_path is None:
        trades_path = os.path.join(_ROOT, 'static-site/data/signal_kelly_trades.json')
    """pool(modeA) -> 8键 -> 预计算费后pnl与排序键。返回 (rows, fIdx)。"""
    tr, fIdx = load(trades_path)
    rows = build_mode_pool(tr, fIdx, 'A')
    filters = DEFAULT_FILTERS
    mm = active_month_mask(filters)
    mD, eD, rD = len(fIdx), len(fIdx) + 1, len(fIdx) + 2
    kept = [t for t in rows if passes_fade(t, fIdx, filters, mm, mD, eD, rD)]
    global IDX_PNL, IDX_SKEY
    IDX_PNL, IDX_SKEY = len(fIdx) + 3, len(fIdx) + 4
    RATING_RANK = {'high': 0, 'mid': 1, 'low': 2}
    SIG_RANK = {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3}
    for t in kept:
        t.append(calc_row(t, fIdx))  # IDX_PNL
        ts = float(t[fIdx['track_score']]) if t[fIdx['track_score']] not in (None, '') else float('inf')
        t.append((-ts,
                  RATING_RANK.get(str(t[fIdx['rating']] or ''), 3),
                  SIG_RANK.get(str(t[fIdx['signal']] or ''), 9),
                  str(t[fIdx['buy_date']] or '')))  # IDX_SKEY 与 sim_core.topk_by_date 同序
    return kept, fIdx

def _topk_group(grp, K):
    grp = sorted(grp, key=lambda t: t[IDX_SKEY])
    return grp[:K]

def eval_rule_fill(rows, rule_fn, K=1):
    """补位口径评估。rule_fn(t)->True=该笔被拦(时段级规则命中)。
    返回入选笔列表。"""
    bydate = {}
    for t in rows:
        bydate.setdefault(str(t[0] or ''), []).append(t)
    sel = []
    for sd in sorted(bydate):
        kept2 = [t for t in bydate[sd] if not rule_fn(t)]
        sel.extend(_topk_group(kept2, K))
    return sel

def eval_baseline(rows, K=1):
    return eval_rule_fill(rows, lambda t: False, K)

def eval_rule_del(rows, rule_fn, K=1):
    """删笔口径(理想对照): 先选topK再删。"""
    base = eval_baseline(rows, K)
    return [t for t in base if not rule_fn(t)]

def stats_of(sel):
    """总净额/胜率/持仓数(费后 pnl 已预计算)。"""
    tot = sum(t[IDX_PNL]['pnlYuan'] for t in sel)
    win = sum(1 for t in sel if t[IDX_PNL]['pnlYuan'] > 0)
    hold = sum(1 for t in sel if t[IDX_PNL]['isHolding'])
    return dict(n=len(sel), total=round(tot, 2), winRate=round(win / max(len(sel), 1) * 100, 1), holding=hold)

def window(sel, d1, d2=None):
    """signal_date ∈ [d1, d2] 子集(d2=None 到末尾)。"""
    out = [t for t in sel if str(t[0]) >= d1 and (d2 is None or str(t[0]) <= d2)]
    return out

def yearly_buckets(sel):
    by = {}
    for t in sel:
        y = str(t[0])[:4]
        by.setdefault(y, []).append(t[IDX_PNL]['pnlYuan'])
    return {y: round(sum(v), 2) for y, v in sorted(by.items())}

def diff_detail(base_sel, new_sel):
    """被拦/替补分解(按 base_key 对齐)。"""
    def keyset(sel):
        return {base_key(t, FIDX_GLOBAL): t for t in sel}
    b, n = keyset(base_sel), keyset(new_sel)
    blocked = [b[k] for k in b if k not in n]
    added = [n[k] for k in n if k not in b]
    bp = sum(t[IDX_PNL]['pnlYuan'] for t in blocked)
    ap = sum(t[IDX_PNL]['pnlYuan'] for t in added)
    return dict(blocked_n=len(blocked), blocked_pnl=round(bp, 2),
                added_n=len(added), added_pnl=round(ap, 2),
                net_improve=round(-bp + ap, 2))

FIDX_GLOBAL = None

def init(rows, fIdx):
    global FIDX_GLOBAL
    FIDX_GLOBAL = fIdx

# ---- 三道门(主判据=补位口径;blocked 类=基线入选且被规则命中的笔) ----
def three_gates(base_sel, new_sel, det):
    """门① blocked_n>=30;门② 2026双向(4月误伤>=-1500 且 5-8月改善>=+2500);
    门③ 前向2024-26 net_improve>=0 且 blocked类按年负占比>=55%。
    返回 dict(g1,g2,g3,pass_all, blocked_yearly_neg_ratio,...)"""
    apr_new = stats_of(window(new_sel, '20260401', '20260430'))
    may_aug_new = stats_of(window(new_sel, '20260501', '20260831'))
    apr_base = stats_of(window(base_sel, '20260401', '20260430'))
    may_aug_base = stats_of(window(base_sel, '20260501', '20260831'))
    apr_hurt = apr_new['total'] - apr_base['total']
    ma_impr = may_aug_base['total'] - may_aug_new['total']
    fwd = forward_2024_26(base_sel, new_sel)
    # blocked 按年桶
    def keyset(sel):
        return {base_key(t, FIDX_GLOBAL): t for t in sel}
    b, n = keyset(base_sel), keyset(new_sel)
    blocked = [b[k] for k in b if k not in n]
    byb = {}
    for t in blocked:
        y = str(t[0])[:4]
        byb.setdefault(y, []).append(t[IDX_PNL]['pnlYuan'])
    ysum = {y: round(sum(v), 2) for y, v in sorted(byb.items())}
    neg_years = sum(1 for v in ysum.values() if v < 0)
    ratio = neg_years / max(len(ysum), 1)
    g1 = det['blocked_n'] >= 30
    g2 = apr_hurt >= -1500 and ma_impr >= 2500
    g3 = fwd['net_improve'] >= 0 and ratio >= 0.55
    return dict(g1=g1, g2=g2, g3=g3, pass_all=bool(g1 and g2 and g3),
                apr_hurt=round(apr_hurt, 2), mayaug_improve=round(ma_impr, 2),
                forward=fwd, blocked_yearly=ysum, blocked_neg_ratio=round(ratio, 3))

def forward_2024_26(base_sel, new_sel):
    b24 = stats_of(window(base_sel, '20240101', '20261231'))
    n24 = stats_of(window(new_sel, '20240101', '20261231'))
    return dict(base=b24['total'], new=n24['total'], net_improve=round(n24['total'] - b24['total'], 2))


def calc_row_pub(t, fIdx):
    from sim_core import calc_row
    return calc_row(t, fIdx)

fIdx_global = None
