# -*- coding: utf-8 -*-
"""第一步: 复现用户观察(弹窗默认口径 mode=A + 降亏开 + K1 + etf_def 费率)"""
import sys, json, time
sys.path.insert(0, '/tmp/simbt')
import simcore as S

t0 = time.time()
tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
print('generated_at:', tr.get('generated_at'), '| buy_amount:', tr.get('buy_amount'), '| period_cutoffs:', tr.get('period_cutoffs'))
pool = S.build_mode_pool(tr, fIdx, 'A')
print('mode=A 基笔池(去重后):', len(pool), '笔, load sec', round(time.time()-t0, 1))

mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mm = S.active_month_mask(filters)
kept_fade = [t for t in pool if S.passes_fade(t, fIdx, filters, mm, mD, eD, rD)]
kept_k1 = S.topk_by_date(kept_fade, fIdx, 1)
print('降亏后:', len(kept_fade), '-> K1后:', len(kept_k1))

def show(tag, rows):
    st = S.window_stats(rows, fIdx)
    print(f"{tag}: n={st['n']} 累积金额={st['cumYuan']:.0f}元 累积盈亏%={st['cumPct']:.2f}% 峰值持仓={st['peakPosN']}笔 对错={st['right']}/{st['wrong']}({st['winRate']:.1f}%) 持仓中={st['holding']}")

for start in ['20260401', '20260501', '', ]:
    for tag, rows in [('全信号', pool), ('AI过滤+K1', kept_k1)]:
        sub = [t for t in rows if (not start or str(t[fIdx['signal_date']] or '') >= start)]
        show(f"[{start or '全历史'}] {tag}", sub)
    print()

# 逐月 2026 双口径
print('=== 2026 逐月(按 signal_date 归月) ===')
print('月份 | 全信号: n/净额元 | AI过滤+K1: n/净额元')
for mth in range(1, 9):
    lo = f'2026{mth:02d}00'; hi = f'2026{mth:02d}32'
    a = [t for t in pool if lo <= str(t[fIdx['signal_date']] or '') < hi]
    b = [t for t in kept_k1 if lo <= str(t[fIdx['signal_date']] or '') < hi]
    sa = S.window_stats(a, fIdx); sb = S.window_stats(b, fIdx)
    print(f"2026-{mth:02d} | 全:{sa['n']:4d}笔 {sa['cumYuan']:+10.0f}元 | 过滤K1:{sb['n']:3d}笔 {sb['cumYuan']:+10.0f}元")
