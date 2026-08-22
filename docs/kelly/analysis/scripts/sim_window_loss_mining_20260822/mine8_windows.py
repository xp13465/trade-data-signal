# -*- coding: utf-8 -*-
"""§11 全窗口成绩对照(用户质疑维度补跑 2026-08-22)

目的:   候选1「A股牛市·主升×(辅买∪备买)全停」的全窗口成绩对照,回答用户三问:
        ①近1/2/3/5年+全史窗口 8键基线 vs 9键(8键+候选1)
        ②四大熊市专项窗口(2015股灾熔断/2018全年熊/2022熊/2024Q1微盘灾)
        ③2011-2026 逐年完整表  ④全史回撤与修复天数(累积金额曲线口径)
口径:   与 sim_core.py 完全一致(mode A 基笔池 + AI降亏8键 + K1 top-K + etf_def费率,
        signal_date 闭区间切片, 每笔本金1万, 持仓中笔按 current_price 计浮盈);
        9键 = 基线上叠加候选1, 判据与 run_all.py best_pred 逐字一致:
        (market_tier=='牛市·主升') and signal in ('buy_aux','buy_backup')
        (market_tier 为空者均为 hk/global 类, 天然不在命中范围 = A股限定)
输入:   static-site/data/signal_kelly_trades.json (v1.1.4, generated 2026-08-22 16:58)
输出:   data/mine8_windows.json + stdout 全部表格
复现:   python3 docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/mine8_windows.py
"""
import sys, os, json, datetime
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE)))))
sys.path.insert(0, HERE)
import sim_core as S  # noqa

tr, fIdx = S.load(os.path.join(ROOT, 'static-site/data/signal_kelly_trades.json'))
mD, eD, rD = S.mk_idx(fIdx)
filters = S.DEFAULT_FILTERS
mmask = S.active_month_mask(filters)

poolA = S.build_mode_pool(tr, fIdx, 'A')
fadeA = [t for t in poolA if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
k1A = S.topk_by_date(fadeA, fIdx, 1)          # 基线 8键 K1
CAND1 = lambda t: (t[fIdx['market_tier']] or '') == '牛市·主升' and t[fIdx['signal']] in ('buy_aux', 'buy_backup')
k1B = [t for t in k1A if not CAND1(t)]         # 9键 = 8键 + 候选1

MAXD = max(str(t[fIdx['signal_date']] or '') for t in k1A)
print(f'数据边界: signal_date 最大={MAXD} | K1基线 {len(k1A)}笔 -> 9键 {len(k1B)}笔(砍{len(k1A)-len(k1B)}笔)')
# 交叉校验锚点(须与 run_all.py results.json 一致)
print(f'交叉校验: 基线全史={sum(S.calc_row(t,fIdx)["pnlYuan"] for t in k1A):+.2f}(期望+66530.38) | 9键全史={sum(S.calc_row(t,fIdx)["pnlYuan"] for t in k1B):+.2f}(期望+76425.75)')

def sd_of(t): return str(t[fIdx['signal_date']] or '')

def two_col(rows_base, rows_9, tag, lo=None, hi=None):
    """一个窗口的两列统计: 基线 vs 9键。样本<10笔标样本不足。"""
    def sub(rows):
        return [t for t in rows if (lo is None or sd_of(t) >= lo) and (hi is None or sd_of(t) <= hi)]
    b, n9 = sub(rows_base), sub(rows_9)
    sb, s9 = S.window_stats(b, fIdx), S.window_stats(n9, fIdx)
    def fmt(s):
        insuf = ' ⚠样本不足' if s['n'] < 10 else ''
        return f"{s['cumYuan']:>+10.0f}元 | {s['n']:>4}笔 | 胜率{s['winRate']:>5.1f}% | 峰值持仓{s['peakPosN']:>3}笔{insuf}"
    d = s9['cumYuan'] - sb['cumYuan']
    print(f'{tag}')
    print(f'  基线8键: {fmt(sb)}')
    print(f'  9键叠加: {fmt(s9)}')
    print(f'  差值(9键-基线): {d:+.0f}元 ({d/(max(sb["peakPosN"],1)*10000)*100:+.2f}%峰值本金) {"改善" if d>0 else ("持平" if abs(d)<1 else "变差")}')
    return dict(tag=tag, base=dict(n=sb['n'], cumYuan=sb['cumYuan'], cumPct=sb['cumPct'], peakPosN=sb['peakPosN'], winRate=sb['winRate']),
                after=dict(n=s9['n'], cumYuan=s9['cumYuan'], cumPct=s9['cumPct'], peakPosN=s9['peakPosN'], winRate=s9['winRate']),
                diffYuan=d, cut_n=len(b)-len(n9))

OUT = dict(generated_at=datetime.datetime.now().isoformat(), data_max_signal_date=MAXD)

print()
print('=' * 78)
print('表1: 滚动窗口成绩对照(signal_date >= 起点, 弹窗同口径切片)')
print('=' * 78)
WINS = [
    ('近1年(2025-08-22 起)', '20250822'),
    ('近2年(2024-08-22 起)', '20240822'),
    ('近3年(2023-08-22 起)', '20230822'),
    ('近5年(2021-08-22 起)', '20210822'),
    ('全史(2011-2026)', None),
]
OUT['windows'] = []
for tag, lo in WINS:
    OUT['windows'].append(two_col(k1A, k1B, tag, lo=lo))

print()
print('=' * 78)
print('表2: 大熊市专项窗口(signal_date 闭区间切片)')
print('=' * 78)
BEARS = [
    ('2015股灾+熔断(2015-06-15~2016-01-31)', '20150615', '20160131'),
    ('2018全年熊(2018-01-01~2018-12-31)', '20180101', '20181231'),
    ('2022熊(2022-01-01~2022-04-30)', '20220101', '20220430'),
    ('2024Q1微盘灾(2024-01-01~2024-02-29)', '20240101', '20240229'),
]
OUT['bear_windows'] = []
for tag, lo, hi in BEARS:
    OUT['bear_windows'].append(two_col(k1A, k1B, tag, lo=lo, hi=hi))

print()
print('=' * 78)
print('表3: 2011-2026 逐年完整表(净额元; 差值=9键-基线, 正=候选1改善)')
print('=' * 78)
years = sorted(set(sd_of(t)[:4] for t in k1A))
OUT['yearly'] = []
print(f'{"年份":<6}{"基线8键":>12}{"9键叠加":>12}{"差值":>10}{"被砍笔":>8}  方向')
worse_years = []
for y in years:
    b = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in k1A if sd_of(t)[:4] == y)
    a = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in k1B if sd_of(t)[:4] == y)
    nb = len([t for t in k1A if sd_of(t)[:4] == y]); na = len([t for t in k1B if sd_of(t)[:4] == y])
    d = a - b
    direction = '改善' if d > 0.5 else ('变差' if d < -0.5 else '≈0')
    if d < -0.5: worse_years.append((y, round(d)))
    print(f'{y:<6}{b:>+12.0f}{a:>+12.0f}{d:>+10.0f}{"("+str(nb-na)+"笔)":>8}  {direction}')
    OUT['yearly'].append(dict(year=y, base=b, after=a, diff=d, cut_n=nb-na, direction=direction))
tb = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in k1A); ta = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in k1B)
print(f'{"合计":<6}{tb:>+12.0f}{ta:>+12.0f}{ta-tb:>+10.0f}')
print(f'9键变差年份: {worse_years}')

print()
print('=' * 78)
print('表4: 全史回撤与修复(累积金额曲线, 按 signal_date 日聚合阶梯; 弹窗"累积盈亏%"分母=全窗口峰值持仓×1万)')
print('=' * 78)

def drawdown(rows, tag):
    asc = sorted(rows, key=sd_of)
    daily = {}
    for t in asc:
        d = sd_of(t)
        daily[d] = daily.get(d, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
    dates = sorted(daily)
    peak_pos_n = S.window_stats(rows, fIdx)['peakPosN']
    denom = max(peak_pos_n, 1) * 10000.0
    cum = 0.0; peak = 0.0; peak_date = dates[0]
    mdd = 0.0; mdd_pk = mdd_tr = None; trough = 0.0
    segs = []  # (peak_date, trough_date, trough_val, recov_date, recov_days, dd_yuan)
    cur_trough = 0.0; cur_trough_date = None
    for d in dates:
        cum += daily[d]
        if cum >= peak - 1e-9:
            if cum > peak + 1e-9 and peak_date != d and cur_trough_date is not None:
                segs.append(dict(peak_date=peak_date, trough_date=cur_trough_date, trough_val=cur_trough,
                                 recov_date=d, recov_days=(datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])) - datetime.date(int(peak_date[:4]), int(peak_date[4:6]), int(peak_date[6:8]))).days,
                                 dd_yuan=peak - cur_trough))
            if cum > peak or cur_trough_date is None:
                peak = cum; peak_date = d
                cur_trough = cum; cur_trough_date = d
        else:
            if peak - cum > (peak - cur_trough):
                cur_trough = cum; cur_trough_date = d
            if peak - cum > mdd:
                mdd = peak - cum; mdd_pk = peak_date; mdd_tr = d
    # 末段未修复
    open_seg = None
    if cur_trough_date is not None and (mdd > 0 or cum < peak):
        if peak - cur_trough > 1e-9:
            d0 = datetime.date(int(peak_date[:4]), int(peak_date[4:6]), int(peak_date[6:8]))
            d1 = datetime.date(int(dates[-1][:4]), int(dates[-1][4:6]), int(dates[-1][6:8]))
            open_seg = dict(peak_date=peak_date, trough_date=cur_trough_date, trough_val=cur_trough,
                            recov_date=None, recov_days=(d1 - d0).days, dd_yuan=peak - cur_trough)
    all_segs = segs + ([open_seg] if open_seg else [])
    mddseg = max(all_segs, key=lambda s: s['dd_yuan']) if all_segs else None
    longest = max(all_segs, key=lambda s: s['recov_days']) if all_segs else None
    print(f'[{tag}] 终值={cum:+.0f}元 | 峰值持仓={peak_pos_n}笔(分母{denom:.0f}元)')
    print(f'  最大回撤: {mdd:+.0f}元 = 占峰值持仓本金 {mdd/denom*100:+.2f}% (高点{mdd_pk} -> 谷底{mdd_tr})')
    if mddseg:
        rec = '未修复(至数据末尾)' if mddseg['recov_date'] is None else f"{mddseg['recov_date']}修复, {mddseg['recov_days']}天"
        print(f'  最大回撤段修复: {rec}')
    if longest:
        rec = '未修复(至数据末尾)' if longest['recov_date'] is None else f"{longest['recov_days']}天({longest['peak_date']}高点->{longest['recov_date']}收复)"
        print(f'  全史最长回撤修复: {rec}')
    print(f'  回撤段总数(回撤>0且创新高间隔): {len(all_segs)}')
    return dict(final=cum, peakPosN=peak_pos_n, denom=denom, maxDD=mdd, maxDDpct=mdd/denom*100,
                maxDD_peak=mdd_pk, maxDD_trough=mdd_tr, mdd_seg=mddseg, longest_seg=longest, n_segs=len(all_segs))

OUT['drawdown'] = {'base': drawdown(k1A, '基线8键'), 'after': drawdown(k1B, '9键叠加')}
print()
print('口径诚实标注: ①曲线=按 signal_date 日聚合的已实现+浮盈阶梯(同弹窗逐行累积, 同日内顺序无关); ②"累积盈亏%"分母=全窗口峰值持仓×1万(常数, 同弹窗列逻辑); ③窗口切片按 signal_date, 整笔盈亏(含窗口外卖出部分)归入信号日窗口, 与弹窗一致; ④持仓中笔按 current_price 计浮盈, 数据末尾(2026-08-20后)的未平仓笔盈亏会随后续行情变化。')

with open(os.path.join(HERE, 'data/mine8_windows.json'), 'w') as f:
    json.dump(OUT, f, ensure_ascii=False, indent=1, default=float)
print('\nmine8_windows.json written')
