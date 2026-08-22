# -*- coding: utf-8 -*-
"""三轮降亏挖掘·替补专项 公共引擎(2026-08-22)。

目的:   在「候选1(牛市·主升×辅买∪备买全停)= 第9键」的补位口径下,提取三类笔集:
        blocked(基线选中且被候选1拦)/ filled(替补=补位后新顶上)/ shadow(被拦日组内未顶上的其余候选),
        供盲区地图(mine12)/子群穷举(mine13)/R2四重检验(mine14)复用。
口径:   与 r2_common.py 逐字一致(mode A + 8键 + 组内剔CAND1 + topK + etf_def 费率),测试基准=current baseline(v1.1.4 弹窗口径)。
输入:   static-site/data/signal_kelly_trades.json(generated_at 2026-08-22 17:58)
输出:   get_sets() 五元组;直接运行本脚本=锚点自检+导出 data/r3_sets.json(三类笔集全字段明细)
锚点:   基线8键全史=+66530.38 | 9键补位全史=+73102.53 | blocked 139笔/-9895.37 | filled 45天45笔/-3323.22 | empty_days 94
复现:   python3 docs/kelly/analysis/scripts/sim_loss_mining_round3_substitute_20260822/r3_common.py
"""
import os, sys, json, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '../../../../..'))
R2_DIR = os.path.join(ROOT, 'docs/kelly/analysis/scripts/sim_window_loss_mining_20260822')
sys.path.insert(0, R2_DIR)

import r2_common as R  # noqa  (其内部 _ROOT 基于自身文件位置, 指向 trade 根)
from sim_core import base_key, calc_row  # noqa

ROWS = FIDX = None

def ensure():
    global ROWS, FIDX
    if ROWS is None:
        ROWS, FIDX = R.prepare_rows()
        R.init(ROWS, FIDX)
    return ROWS, FIDX

CAND1_TIER = '牛市·主升'
def cand1(t):
    _, fIdx = ensure()
    return (t[fIdx['market_tier']] or '') == CAND1_TIER and t[fIdx['signal']] in ('buy_aux', 'buy_backup')

def get_sets():
    """返回 dict(base_sel, pf_sel, blocked, filled, empty_days, shadow, day_map)
    day_map[sd] = dict(base_hit=[CAND1命中且基线选中], nonhit=[该日组内非命中全部], filled=[替补])"""
    rows, fIdx = ensure()
    bydate = {}
    for t in rows:
        bydate.setdefault(str(t[0] or ''), []).append(t)
    base_sel, pf_sel = [], []
    day_map = {}
    for sd in sorted(bydate):
        grp = bydate[sd]
        hit = [t for t in grp if cand1(t)]
        nonhit = [t for t in grp if not cand1(t)]
        b1 = R._topk_group(grp, 1)
        p1 = R._topk_group(nonhit, 1)
        base_sel.extend(b1); pf_sel.extend(p1)
        bh = [t for t in b1 if cand1(t)]
        if bh:
            dm = day_map.setdefault(sd, dict(base_hit=bh, nonhit=nonhit, filled=[]))
            dm['nonhit'] = nonhit
            if p1:
                dm['filled'] = p1
    keyset = lambda sel: {base_key(t, FIDX) for t in sel}
    bs, ps = keyset(base_sel), keyset(pf_sel)
    blocked = [t for t in base_sel if base_key(t, FIDX) not in ps and cand1(t)]
    # blocked 精确口径: 基线选中且命中CAND1(= 补位后消失的命中笔)
    blocked = [t for t in base_sel if cand1(t)]
    filled = [t for t in pf_sel if base_key(t, FIDX) not in bs]
    shadow = []
    for sd, dm in day_map.items():
        fk = {base_key(t, FIDX) for t in dm['filled']}
        shadow += [t for t in dm['nonhit'] if base_key(t, FIDX) not in fk]
    empty_days = [sd for sd, dm in day_map.items() if not dm['filled']]
    return dict(rows=rows, base_sel=base_sel, pf_sel=pf_sel, blocked=blocked,
                filled=filled, shadow=shadow, empty_days=empty_days, day_map=day_map)

def pnl_of(t):
    _, fIdx = ensure()
    return R.calc_row_pub(t, FIDX)['pnlYuan']

def brief(t):
    _, fIdx = ensure()
    i = fIdx
    c = R.calc_row_pub(t, i)
    return dict(signal_date=t[i['signal_date']], index_id=t[i['index_id']], signal=t[i['signal']],
                rating=str(t[i['rating']] or ''), track_score=t[i['track_score']], track_tier=t[i['track_tier']],
                match_method=t[i['match_method']], low_conf=t[i['track_low_confidence']],
                buy_date=t[i['buy_date']], buy_price=t[i['buy_price']],
                market_tier=t[i['market_tier']] or '', market_tier_all=t[i['market_tier_all']] or '',
                market_tier_cyb=t[i['market_tier_cyb']] or '', market_state=t[i['market_state']],
                sell_date=t[i['sell_date']] or '', hold_days=t[i['hold_days']],
                sell_reason=t[i['sell_reason']] or '', pnl=round(c['pnlYuan'], 2), holding=c['isHolding'])

if __name__ == '__main__':
    st = get_sets()
    bp = sum(pnl_of(t) for t in st['blocked'])
    fp = sum(pnl_of(t) for t in st['filled'])
    sp = sum(pnl_of(t) for t in st['shadow'])
    base_p = sum(pnl_of(t) for t in st['base_sel'])
    pf_p = sum(pnl_of(t) for t in st['pf_sel'])
    print(f"自检: 基线8键全史={base_p:+.2f}(期望+66530.38)")
    print(f"     9键补位全史={pf_p:+.2f}(期望+73102.53)")
    print(f"     blocked={len(st['blocked'])}笔/{bp:+.2f}(期望139/-9895.37) filled={len(st['filled'])}笔/{fp:+.2f}(期望45/-3323.22)")
    print(f"     empty_days={len(st['empty_days'])}(期望94) shadow(未顶上候选)={len(st['shadow'])}笔/{sp:+.2f}")
    assert abs(base_p - 66530.38) < 0.5 and abs(pf_p - 73102.53) < 0.5
    assert len(st['blocked']) == 139 and abs(bp - (-9895.37)) < 0.5
    assert len(st['filled']) == 45 and abs(fp - (-3323.22)) < 0.5
    out = dict(generated_at=datetime.datetime.now().isoformat(),
               anchors=dict(base_full=base_p, pf_full=pf_p, blocked_n=len(st['blocked']), blocked_pnl=bp,
                            filled_n=len(st['filled']), filled_pnl=fp, empty_days=len(st['empty_days']),
                            shadow_n=len(st['shadow']), shadow_pnl=sp),
               blocked=[brief(t) for t in sorted(st['blocked'], key=lambda x: str(x[0]))],
               filled=[brief(t) for t in sorted(st['filled'], key=lambda x: str(x[0]))],
               shadow=[brief(t) for t in sorted(st['shadow'], key=lambda x: str(x[0]))],
               empty_days=st['empty_days'])
    with open(os.path.join(HERE, 'data/r3_sets.json'), 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('data/r3_sets.json written')
