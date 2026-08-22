# -*- coding: utf-8 -*-
"""Part F: 牛主升全停 · 全历史穷举验证(按年/分半/前向) + 对照线 + G/H/I 定性"""
import sys, json
sys.path.insert(0, '/tmp/simbt')
import simcore as S

tr, fIdx = S.load('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json')
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)

def pnl(rows):
    return sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)

print('=' * 70)
print('Part F1: 「A股类·牛市主升全停」全历史穷举(K1 口径基线上叠加)')
print('=' * 70)
results = {}
for mode in 'ABCDEFGHI':
    pool = S.build_mode_pool(tr, fIdx, mode)
    fade = [t for t in pool if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
    k1 = S.topk_by_date(fade, fIdx, 1)
    stopped = [t for t in k1 if (t[fIdx['market_tier']] or '') == '牛市·主升']
    kept = [t for t in k1 if (t[fIdx['market_tier']] or '') != '牛市·主升']
    results[mode] = dict(k1=k1, kept=kept, stopped=stopped,
                         base=pnl(k1), kept_pnl=pnl(kept), cut=pnl(stopped))
    print(f'模式{mode}: K1全历史={pnl(k1):>+10.0f} | 停牛主升后={pnl(kept):>+10.0f} | 被砍掉的牛主升笔={pnl(stopped):>+10.0f}(n={len(stopped)})')

print()
print('-- mode A: 牛主升全停 按年分解(被砍净额, 正=当年少亏或多赚) --')
k1A = results['A']['k1']
years = sorted(set((t[fIdx['signal_date']] or '')[:4] for t in k1A))
print('年份    基线净额      停后净额      被砍牛主升(n)   边际改善')
for y in years:
    base_y = pnl([t for t in k1A if (t[fIdx['signal_date']] or '').startswith(y)])
    kept_y = pnl([t for t in results['A']['kept'] if (t[fIdx['signal_date']] or '').startswith(y)])
    cut_y = pnl([t for t in results['A']['stopped'] if (t[fIdx['signal_date']] or '').startswith(y)])
    n_cut = len([t for t in results['A']['stopped'] if (t[fIdx['signal_date']] or '').startswith(y)])
    flag = '✓' if cut_y < 0 else ('≈' if abs(cut_y) < 500 else '✗误伤')
    print(f'{y}  {base_y:>+10.0f}   {kept_y:>+10.0f}   {cut_y:>+9.0f}({n_cut:>3})   {cut_y:>+8.0f} {flag}')
tot_base = sum(pnl([t for t in k1A if (t[fIdx['signal_date']] or '').startswith(y)]) for y in years)
tot_kept = sum(pnl([t for t in results['A']['kept'] if (t[fIdx['signal_date']] or '').startswith(y)]) for y in years)
print(f'合计  {tot_base:>+10.0f}   {tot_kept:>+10.0f}')

print()
print('-- 分半稳定性(mode A): 2011-2018 vs 2019-2026 --')
for lo, hi, tag in [('2011', '2018', '前半 2011-2018'), ('2019', '2026', '后半 2019-2026')]:
    cut = pnl([t for t in results['A']['stopped'] if lo <= (t[fIdx['signal_date']] or '')[:4] <= hi])
    base = pnl([t for t in k1A if lo <= (t[fIdx['signal_date']] or '')[:4] <= hi])
    print(f'  {tag}: 基线={base:+.0f} 被砍={cut:+.0f} 边际改善={-cut:+.0f}')

print()
print('-- 前向测试(样本外): 用 2011-2023 定规则, 2024-2026 检验 --')
for lo, hi, tag in [('2011','2023','定规则期 2011-2023'), ('2024','2026','前向检验 2024-2026')]:
    cut = pnl([t for t in results['A']['stopped'] if lo <= (t[fIdx['signal_date']] or '')[:4] <= hi])
    base = pnl([t for t in k1A if lo <= (t[fIdx['signal_date']] or '')[:4] <= hi])
    print(f'  {tag}: 基线={base:+.0f} 被砍={cut:+.0f} 边际改善={-cut:+.0f}')

print()
print('=' * 70)
print('Part F2: 用户对照线 —— 「4月末利润落袋后空仓」(mode A + K1)')
print('=' * 70)
m26 = {}
for t in k1A:
    if (t[fIdx['signal_date']] or '').startswith('2026'):
        m26.setdefault((t[fIdx['signal_date']])[:6], []).append(t)
cum = 0
print('月份     当月净额    累积(继续操作)   空仓线(4月末落袋)')
for mm in sorted(m26):
    p = pnl(m26[mm]); cum += p
    anchor = f'{cum:>10.0f}' + (' ←4月末锚点' if mm=='202604' else '')
    line = f'{mm}   {p:>+9.0f}    {anchor:>18}'
    if mm > '202604':
        line += f'   (+10792 固定)'
    print(line)

print()
print('=' * 70)
print('Part F3: G/H/I 长线定性(2026逐月见Part A; 这里给当前持仓与回撤)')
print('=' * 70)
for mode in ['G', 'H', 'I']:
    k1m = results[mode]['k1']
    rows26 = [t for t in k1m if (t[fIdx['signal_date']] or '').startswith('2026')]
    holding = [t for t in rows26 if not str(t[fIdx['sell_date']] or '')]
    hold_pnl = pnl(holding)
    # 2026 累积曲线峰值 vs 现在
    asc = sorted(rows26, key=lambda t: str(t[fIdx['signal_date']] or ''))
    c = 0; peak = 0
    for t in asc:
        c += S.calc_row(t, fIdx)['pnlYuan']
        peak = max(peak, c)
    print(f'模式{mode}: 2026全年={pnl(rows26):+.0f}元 | 当前持仓中={len(holding)}笔(浮盈亏{hold_pnl:+.0f}) | 2026年内累积峰值={peak:+.0f} 现值={c:+.0f} 回撤={c-peak:+.0f}')
    # 已卖出的 2026 笔(实现部分)
    sold = [t for t in rows26 if str(t[fIdx['sell_date']] or '')]
    print(f'         已卖{n_}:={len(sold)}笔 实现盈亏={pnl(sold):+.0f}元' if True else '')

print()
print('=' * 70)
print('Part F4: A-F 短线组 vs G-I 长线组 2026 结论行')
print('=' * 70)
for mode in 'ABCDEFGHI':
    r = results[mode]
    rows26 = [t for t in r['k1'] if (t[fIdx['signal_date']] or '').startswith('2026')]
    m58 = [t for t in rows26 if '20260500' <= (t[fIdx['signal_date']] or '') < '20260900']
    grp = '短线组' if mode in 'ABCDEF' else '长线组'
    print(f"{mode}({grp}): 2026全年={pnl(rows26):>+8.0f} | 5-8月={pnl(m58):>+8.0f} | 全历史={r['base']:>+9.0f}")
