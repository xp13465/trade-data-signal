# -*- coding: utf-8 -*-
"""Part A-D: 9模式矩阵 / 三口径 / 画像 / 历史连亏段"""
import sys, json, datetime
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)

def month_of(t): return str(t[fIdx['signal_date']] or '')[:6]

def month_series(rows):
    """月度净额序列(dict yyyymm -> cumYuan), 与弹窗一致(signal_date 归月)"""
    out = {}
    for t in rows:
        m = month_of(t)
        out[m] = out.get(m, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
    return out

print('=' * 70)
print('Part A: 9 模式 × 2026 逐月(AI过滤+K1 口径, 净额元; 弹窗默认=A)')
print('=' * 70)
mode_pools = {}
for mode in 'ABCDEFGHI':
    pool = S.build_mode_pool(tr, fIdx, mode)
    kept_fade = [t for t in pool if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
    kept_k1 = S.topk_by_date(kept_fade, fIdx, 1)
    mode_pools[mode] = dict(pool=pool, fade=kept_fade, k1=kept_k1)

hdr = ['月份'] + [f'{m}(n)' for m in 'ABCDEFGHI']
print('月份      ' + ''.join(f'{m:>12}' for m in 'ABCDEFGHI'))
for mth in [f'2026{mm:02d}' for mm in range(1, 9)]:
    line = f'2026-{mth[4:]} '
    for mode in 'ABCDEFGHI':
        rows = [t for t in mode_pools[mode]['k1'] if month_of(t) == mth]
        pnl = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)
        line += f"{pnl:>9.0f}({len(rows):<2})"
    print(line)
# 5-8 月合计 + 全历史
print('-' * 70)
for tag, months in [('2026 5-8月合计', ['202605','202606','202607','202608']), ('2026全年', [f'2026{mm:02d}' for mm in range(1,9)])]:
    line = f'{tag}: '
    for mode in 'ABCDEFGHI':
        rows = [t for t in mode_pools[mode]['k1'] if month_of(t) in months]
        pnl = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)
        line += f'{pnl:>10.0f}'
    print(line)
line = '全历史累计: '
for mode in 'ABCDEFGHI':
    rows = mode_pools[mode]['k1']
    pnl = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)
    line += f'{pnl:>10.0f}'
print(line)

print()
print('=' * 70)
print('Part B: mode A 三口径分解(全信号 / AI过滤+K1 / 被滤掉)')
print('=' * 70)
poolA = mode_pools['A']['pool']; k1A = mode_pools['A']['k1']; fadeA = mode_pools['A']['fade']
k1_keys = set(S.base_key(t, fIdx) for t in k1A)
fade_keys = set(S.base_key(t, fIdx) for t in fadeA)
removed_by_fade = [t for t in poolA if S.base_key(t, fIdx) not in fade_keys]     # 降亏剔除
removed_by_k = [t for t in fadeA if S.base_key(t, fIdx) not in k1_keys]          # K档未选中
def seg(tag, rows, start=''):
    sub = [t for t in rows if (not start or month_of(t) >= start[:6])]
    st = S.window_stats(sub, fIdx)
    print(f"{tag:<28} n={st['n']:>5} 净额={st['cumYuan']:>+11.0f}元 胜率={st['winRate']:5.1f}% 持仓中={st['holding']}")
for w in ['20260401', '20260501']:
    print(f'-- 窗口 {w} 至今 --')
    seg('①全信号(不过滤)', poolA, w)
    seg('②AI过滤+K1(用户视角)', k1A, w)
    seg('③被降亏滤掉', removed_by_fade, w)
    seg('③b被K档未选中', removed_by_k, w)

print()
print('=' * 70)
print('Part C: mode A · 4月暴赚构成 + 5-8月亏损画像(K1 口径)')
print('=' * 70)
SIG_CN = {'buy': '主买', 'buy_aux': '辅买', 'buy_special': '追买', 'buy_backup': '备买'}
def profile(rows, field_fn, title):
    agg = {}
    for t in rows:
        k = field_fn(t)
        agg.setdefault(k, []).append(t)
    print(f'-- {title} --')
    items = []
    for k, rs in agg.items():
        pnl = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rs)
        wins = sum(1 for t in rs if S.calc_row(t, fIdx)['pnlYuan'] > 0)
        items.append((pnl, k, len(rs), wins))
    items.sort(reverse=True)
    for pnl, k, n, w in items:
        print(f'   {str(k):<24} n={n:>4} 净={pnl:>+10.0f}元 胜率={w/max(n,1)*100:5.1f}%')

apr = [t for t in k1A if month_of(t) == '202604']
profile(apr, lambda t: SIG_CN.get(t[fIdx['signal']], t[fIdx['signal']]), '2026-04 盈利构成×信号类型')
profile(apr, lambda t: t[mD] or '(空)', '2026-04 盈利构成×市场大类')
profile(apr, lambda t: (t[fIdx['market_tier']] or '(非A股)'), '2026-04 盈利构成×四档')
lossm = [t for t in k1A if month_of(t) in ('202605','202606','202607','202608')]
print(f'\n5-8月 K1 共 {len(lossm)} 笔, 净额 {sum(S.calc_row(t,fIdx)["pnlYuan"] for t in lossm):+.0f} 元')
profile(lossm, lambda t: SIG_CN.get(t[fIdx['signal']], t[fIdx['signal']]), '5-8月亏损×信号类型')
profile(lossm, lambda t: t[mD] or '(空)', '5-8月亏损×市场大类')
profile(lossm, lambda t: (t[fIdx['market_tier']] or '(非A股)'), '5-8月亏损×四档')
profile(lossm, lambda t: month_of(t), '5-8月亏损×月份')
# 全信号口径同样画像(样本大更稳)
lossall = [t for t in poolA if month_of(t) in ('202605','202606','202607','202608')]
profile(lossall, lambda t: SIG_CN.get(t[fIdx['signal']], t[fIdx['signal']]), '5-8月亏损×信号类型(全信号)')
profile(lossall, lambda t: (t[fIdx['market_tier']] or '(非A股)'), '5-8月亏损×四档(全信号)')

print()
print('=' * 70)
print('Part D: 历史连亏段检索(mode A + AI过滤K1 口径, 2011-2026 月度净额)')
print('=' * 70)
ser = month_series(k1A)
months_all = sorted(ser.keys())
vals = [(m, ser[m]) for m in months_all]
# 连续负段(≥3)
segs = []
cur = []
for m, v in vals:
    if v < 0:
        cur.append((m, v))
    else:
        if len(cur) >= 3: segs.append(cur)
        cur = []
if len(cur) >= 3: segs.append(cur)
print(f'总月数={len(vals)}, 连续≥3负月段数={len(segs)}')
for sg in segs:
    tot = sum(v for _, v in sg)
    # 段后恢复: 之后6个月净额
    end_i = months_all.index(sg[-1][0])
    after6 = [ser[m] for m in months_all[end_i+1:end_i+7]]
    after12 = [ser[m] for m in months_all[end_i+1:end_i+13]]
    a6 = sum(after6) if after6 else None
    a12 = sum(after12) if len(after12) == 12 else None
    print(f"  {sg[0][0][:4]}.{sg[0][0][4:]} ~ {sg[-1][0][:4]}.{sg[-1][0][4:]} ({len(sg)}个月连亏) 段内累计={tot:+.0f}元 | 后6月={a6:+.0f}" if a6 is not None else f"  {sg[0][0]}~{sg[-1][0]} 累计={tot:+.0f} | 后6月数据不足")
