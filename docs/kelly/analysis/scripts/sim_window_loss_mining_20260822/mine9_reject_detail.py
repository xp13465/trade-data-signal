# -*- coding: utf-8 -*-
"""§12 落选候选数据明细展开(用户要求 2026-08-22)

目的:   三个落选降亏候选的完整数据明细,与主推候选(§6.4候选1)同规格,不让用户只信总结:
        A = 「vol≥20%(20日已实现波动年化)全停」: 2026双向检验 + 全史按年桶分布(vol≥20%/vol≥25%两表)
        B = 「hs300回撤>5%全停」(距252日收盘最高回撤, 与前序§6.2/mine2同口径): 2026双向检验 + 被砍4月笔明细 + 全史按年桶分布
            附「hs300非多头排列全停」对照(任务引用的4月3笔+1,923实为该口径, 澄清用)
        C = 「下降期×备买 全停」(market_tier=下降期 & signal=buy_backup): 全史总净额核实 + 按年分布 + 2026年5-8月/8月占比 + 近年倾向
口径:   与 run_all.py / mine8_windows.py 完全一致: mode A 基笔池 + AI降亏8键 + K1 top-K + etf_def费率,
        每笔本金1万, 持仓中笔按 current_price 计浮盈; 大盘特征按 buy_date 取
        (dd = close/max(过去252日收盘)-1; vol = 20日日收益标准差×√252 年化), 与 mine2.py/run_all.py 同源。
输入:   static-site/data/signal_kelly_trades.json (v1.1.4)
        static-site/data/index/hs300-all.json (2010起日线)
输出:   data/mine9_reject_detail.json + stdout 全部表格
复现:   python3 docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/mine9_reject_detail.py
"""
import sys, os, json, math, bisect, datetime
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
k1A = S.topk_by_date(fadeA, fIdx, 1)   # 基线 8键 K1
BASE_ALL = sum(S.calc_row(t, fIdx)['pnlYuan'] for t in k1A)
print(f'数据 generated_at={tr.get("generated_at")} | 交叉校验: 基线全史={BASE_ALL:+.2f}(期望+66530.38)')

def sd_of(t): return str(t[fIdx['signal_date']] or '')
def bd_of(t): return str(t[fIdx['buy_date']] or '')
def pnl(rows): return sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)
def wr(rows):
    if not rows: return None
    w = sum(1 for t in rows if S.calc_row(t, fIdx)['pnlYuan'] > 0)
    return w / len(rows) * 100

# ---- hs300 特征(与 run_all.py L36-46 同源) ----
with open(os.path.join(ROOT, 'static-site/data/index/hs300-all.json')) as f:
    hs = json.load(f)['ohlc']
dates = [r['date'] for r in hs]; closes = [r['close'] for r in hs]; n = len(hs)
ma = {p: [None]*n for p in (20, 60, 120)}
for p in (20, 60, 120):
    for i in range(p-1, n):
        ma[p][i] = sum(closes[i-p+1:i+1]) / p
dd252 = [None]*n; vol20 = [None]*n
for i in range(n):
    if i >= 251: dd252[i] = closes[i]/max(closes[i-251:i+1]) - 1
    if i >= 20:
        rets = [closes[j]/closes[j-1]-1 for j in range(i-19, i+1)]
        vol20[i] = (sum(r*r for r in rets)/20) ** 0.5 * math.sqrt(252)
def feat_at(d):
    if d < dates[0]: return None
    i = bisect.bisect_right(dates, d) - 1
    return dict(dd=dd252[i], vol=vol20[i],
                ma_bull=(ma[20][i] > ma[60][i] > ma[120][i]) if all(ma[p][i] is not None for p in (20, 60, 120)) else None)

FT = {}
def ft_of(t):
    k = bd_of(t)
    if k not in FT: FT[k] = feat_at(k)
    return FT[k]

# 空仓对照线 = 4月末累积(signal_date<=20260430 的 K1 净额)
APR = [t for t in k1A if sd_of(t).startswith('202604')]
M58 = [t for t in k1A if '20260500' <= sd_of(t) < '20260900']
M08 = [t for t in k1A if sd_of(t).startswith('202608')]
Y26 = [t for t in k1A if sd_of(t).startswith('2026')]
Q1_26 = [t for t in k1A if '20260101' <= sd_of(t) < '20260401']
IDLE_LINE = pnl(Q1_26) + pnl(APR)
print(f'锚点: 4月基线={len(APR)}笔 {pnl(APR):+.0f} | 5-8月基线={len(M58)}笔 {pnl(M58):+.0f} | 空仓对照线(4月末累积)={IDLE_LINE:+.0f}')

OUT = dict(generated_at=datetime.datetime.now().isoformat(), data_generated_at=tr.get('generated_at'),
           base_all=BASE_ALL, apr_base=dict(n=len(APR), pnl=pnl(APR)), m58_base=dict(n=len(M58), pnl=pnl(M58)),
           idle_line=IDLE_LINE)

def yearly_table(rows, tag):
    """按 signal_date 年分桶: 年, n, 净额, 胜率; <10笔标样本不足"""
    by = {}
    for t in rows:
        by.setdefault(sd_of(t)[:4], []).append(t)
    out = []
    print(f'  -- {tag} 按年分布 --')
    print(f'  {"年份":<6}{"n笔":>5}{"净额元":>12}{"胜率":>8}  标注')
    neg = pos = 0
    for y in sorted(by):
        rs = by[y]; p = pnl(rs); w = wr(rs)
        flag = '⚠样本不足' if len(rs) < 10 else ''
        if p < 0: neg += 1
        elif p > 0: pos += 1
        print(f'  {y:<6}{len(rs):>5}{p:>+12.0f}{w:>7.1f}%  {flag}')
        out.append(dict(year=y, n=len(rs), pnl=p, winRate=w, insufficient=len(rs) < 10))
    tot_n = len(rows); tot_p = pnl(rows)
    print(f'  {"合计":<6}{tot_n:>5}{tot_p:>+12.0f}  正年{pos} 负年{neg}')
    return dict(rows=out, total_n=tot_n, total_pnl=tot_p, pos_years=pos, neg_years=neg)

def dual_check(name, cond, cut_rows_extra=None):
    """双向检验: 4月/5-8月/4-8月/2026全年 保留 vs 基线; 附被砍4月笔明细"""
    cut_apr = [t for t in APR if cond(t)]
    cut_58 = [t for t in M58 if cond(t)]
    keep_apr = [t for t in APR if not cond(t)]
    keep_58 = [t for t in M58 if not cond(t)]
    keep_all = [t for t in k1A if not cond(t)]
    r = dict(name=name,
             apr_keep=dict(n=len(keep_apr), pnl=pnl(keep_apr)),
             apr_cut=dict(n=len(cut_apr), pnl=pnl(cut_apr)),
             m58_keep=dict(n=len(keep_58), pnl=pnl(keep_58)),
             m58_cut=dict(n=len(cut_58), pnl=pnl(cut_58)),
             w58_2026=dict(n=len([t for t in keep_all if sd_of(t) >= '20260401']),
                           pnl=pnl([t for t in keep_all if sd_of(t) >= '20260401'])),
             full2026=dict(n=len([t for t in keep_all if sd_of(t).startswith('2026')]),
                           pnl=pnl([t for t in keep_all if sd_of(t).startswith('2026')])),
             full_hist=dict(n=len(keep_all), pnl=pnl(keep_all)))
    print(f'  [{name}]')
    print(f'    4月: 保留{r["apr_keep"]["n"]}笔 {r["apr_keep"]["pnl"]:>+8.0f} (砍{r["apr_cut"]["n"]}笔 {r["apr_cut"]["pnl"]:>+8.0f}) | 基线17笔 {pnl(APR):>+8.0f}')
    print(f'    5-8月: 保留{r["m58_keep"]["n"]}笔 {r["m58_keep"]["pnl"]:>+8.0f} (砍{r["m58_cut"]["n"]}笔 {r["m58_cut"]["pnl"]:>+8.0f}) | 基线50笔 {pnl(M58):>+8.0f}')
    print(f'    4/1至今: {r["w58_2026"]["pnl"]:>+8.0f} | 2026全年: {r["full2026"]["pnl"]:>+8.0f} | 全史: {r["full_hist"]["pnl"]:>+8.0f} | 空仓线={IDLE_LINE:+.0f}')
    if cut_apr:
        print(f'    被砍4月笔明细({len(cut_apr)}笔):')
        for t in sorted(cut_apr, key=sd_of):
            c = S.calc_row(t, fIdx)
            print(f'      {sd_of(t)} | {t[fIdx["index_id"]]} | {t[fIdx["signal"]]:<12} | {(t[mD] or "(空)"):<8} | tier={t[fIdx["market_tier"]] or "(空)"} | '
                  f'dd={ft_of(t)["dd"]*100 if ft_of(t)["dd"] is not None else float("nan"):+.1f}% vol={ft_of(t)["vol"]*100 if ft_of(t)["vol"] is not None else float("nan"):+.1f}% | {c["pnlYuan"]:+.0f}元')
    return r, cut_apr, cut_58

# ================= 候选A: vol>=20% 全停 =================
print()
print('=' * 78)
print('候选A: 「vol≥20%(20日已实现波动年化)全停」')
print('=' * 78)
OUT['candA'] = {}
rA, cutA_apr, cutA_58 = dual_check('vol≥20% 全停', lambda t: (ft_of(t)['vol'] or 0) >= 0.20)
OUT['candA']['dual'] = rA
OUT['candA']['cut_apr_detail'] = [dict(sd=sd_of(t), idx=t[fIdx['index_id']], sig=t[fIdx['signal']],
                                       pnl=S.calc_row(t, fIdx)['pnlYuan']) for t in cutA_apr]
print()
OUT['candA']['yearly_v20'] = yearly_table([t for t in k1A if (ft_of(t)['vol'] or 0) >= 0.20], 'vol≥20% 桶(K1全史)')
print()
OUT['candA']['yearly_v25'] = yearly_table([t for t in k1A if (ft_of(t)['vol'] or 0) >= 0.25], 'vol≥25% 桶(K1全史, 前序§6.4候选3)')

# ================= 候选B: hs300 回撤>5% 全停 =================
print()
print('=' * 78)
print('候选B: 「hs300回撤>5%全停」(距252日收盘最高回撤 dd<-5%, 与前序§6.2/mine2同口径)')
print('=' * 78)
OUT['candB'] = {}
rB, cutB_apr, cutB_58 = dual_check('hs300回撤>5% 全停', lambda t: (ft_of(t)['dd'] is not None) and ft_of(t)['dd'] < -0.05)
OUT['candB']['dual'] = rB
OUT['candB']['cut_apr_detail'] = [dict(sd=sd_of(t), idx=t[fIdx['index_id']], sig=t[fIdx['signal']], mkt=t[mD] or '',
                                       tier=t[fIdx['market_tier']] or '', dd=ft_of(t)['dd'], vol=ft_of(t)['vol'],
                                       pnl=S.calc_row(t, fIdx)['pnlYuan']) for t in cutB_apr]
print()
print('  -- 对照: 「hs300非多头排列全停」(任务引用的4月3笔+1,923实为该口径; 非多头=MA20≤MA60或MA60≤MA120) --')
rB2, _, _ = dual_check('hs300非多头排列 全停', lambda t: ft_of(t)['ma_bull'] is not True)
OUT['candB']['dual_mabull'] = rB2
print()
OUT['candB']['yearly_dd5'] = yearly_table([t for t in k1A if ft_of(t)['dd'] is not None and ft_of(t)['dd'] < -0.05],
                                          'dd<-5% 桶(K1全史) = 「回调后反弹修复段」买入')
# 2026年4月被砍的笔在全史同类时段的定位: dd<-5% 桶内盈利笔的年度分布
dd5 = [t for t in k1A if ft_of(t)['dd'] is not None and ft_of(t)['dd'] < -0.05]
win_by_year = {}
for t in dd5:
    y = sd_of(t)[:4]
    win_by_year.setdefault(y, dict(n=0, win=0, pnl=0.0))
    c = S.calc_row(t, fIdx)['pnlYuan']
    win_by_year[y]['n'] += 1; win_by_year[y]['pnl'] += c
    if c > 0: win_by_year[y]['win'] += 1
OUT['candB']['dd5_win_by_year'] = win_by_year

# ================= 候选C: 下降期×备买 全停 =================
print()
print('=' * 78)
print('候选C: 「下降期×备买 全停」(market_tier=下降期 & signal=buy_backup)')
print('=' * 78)
OUT['candC'] = {}
cC = [t for t in k1A if (t[fIdx['market_tier']] or '') == '下降期' and t[fIdx['signal']] == 'buy_backup']
print(f'  全史被砍类总净额 = {pnl(cC):+.2f} 元, n={len(cC)} (results.json cut_all=+2157.92 核实)')
OUT['candC']['total'] = dict(n=len(cC), pnl=pnl(cC))
OUT['candC']['yearly'] = yearly_table(cC, '下降期×备买 桶(K1全史)')
c58 = [t for t in cC if '20260500' <= sd_of(t) < '20260900']
c08 = [t for t in cC if sd_of(t).startswith('202608')]
y24p = [t for t in cC if sd_of(t) >= '20240101']
y23p = [t for t in cC if '20230101' <= sd_of(t) < '20240101']
OUT['candC']['m58'] = dict(n=len(c58), pnl=pnl(c58))
OUT['candC']['m08'] = dict(n=len(c08), pnl=pnl(c08))
OUT['candC']['since2024'] = dict(n=len(y24p), pnl=pnl(y24p))
OUT['candC']['y2023'] = dict(n=len(y23p), pnl=pnl(y23p))
m08_base = pnl(M08)
print(f'  5-8月该桶: {len(c58)}笔 {pnl(c58):+.0f} 元 | 8月该桶: {len(c08)}笔 {pnl(c08):+.0f} 元 (8月基线 {m08_base:+.0f}, 占比 {abs(pnl(c08))/abs(m08_base)*100 if m08_base else 0:.0f}%)')
print(f'  近年倾向: 2024至今 {len(y24p)}笔 {pnl(y24p):+.0f} | 2023 {len(y23p)}笔 {pnl(y23p):+.0f}')
if c08:
    print('  2026-08 被砍类明细:')
    for t in sorted(c08, key=sd_of):
        c = S.calc_row(t, fIdx)
        print(f'    {sd_of(t)} | {t[fIdx["index_id"]]} | {(t[mD] or "(空)"):<8} | track_score={t[fIdx["track_score"]]} | {c["pnlYuan"]:+.0f}元')
OUT['candC']['m08_detail'] = [dict(sd=sd_of(t), idx=t[fIdx['index_id']], mkt=t[mD] or '',
                                   ts=t[fIdx['track_score']], pnl=S.calc_row(t, fIdx)['pnlYuan']) for t in c08]

with open(os.path.join(HERE, 'data/mine9_reject_detail.json'), 'w') as f:
    json.dump(OUT, f, ensure_ascii=False, indent=1, default=float)
print('\nmine9_reject_detail.json written')
