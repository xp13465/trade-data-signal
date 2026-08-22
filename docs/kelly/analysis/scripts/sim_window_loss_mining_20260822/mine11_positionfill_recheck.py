# -*- coding: utf-8 -*-
"""§14 补位口径复验(用户质疑回测严谨性 2026-08-22)

目的:   第一轮候选1穷举筛选用「删笔不补位」口径(topK 后直接删命中笔, L39 变体, 不可操作),
        本脚本以「补位口径」(= 前端 app.js _simRender/_isAiFadeHit 真实链路: 先滤后选 top-K)
        为权威, 全面复验候选1「A股牛市·主升×(辅买∪备买)全停」全部结论。
口径定义(权威):
  补位口径 = pool(A基笔池) -> 8键 passesFade -> 组内剔除 CAND1 命中笔 -> top-K 切片(组空则无成交)
           (app.js L3767-3770: filter(!_isAiFadeHit) 在 slice(0,K) 之前, 先滤后选=替补自动顶上)
  删笔口径(旧报告对照) = 基线 topK 结果上直接删除命中笔, 不补位(理想对照附注)
  CAND1(t) = (market_tier=='牛市·主升') and signal in ('buy_aux','buy_backup')
           (与 run_all.py best_pred / mine8_windows.py k1B 判据逐字一致; tier 空=hk/global 天然不命中)
输入:   static-site/data/signal_kelly_trades.json (v1.1.4, generated 2026-08-22 16:58)
输出:   data/mine11_positionfill.json + stdout 全部表格
        内容: ①替补盈亏专项分解(全史+5-8月) ②2026双向检验 ③三道门(补位重定标)
        ④K1-K4敏感性+A-F/H模式同向性(补位版) ⑤五窗口/大熊市/逐年/回撤 对照(主列补位副列删笔)
复现:   python3 docs/kelly/analysis/scripts/sim_window_loss_mining_20260822/mine11_positionfill_recheck.py
锚点:   基线8键全史须=+66530.38; 补位全史≈+73103(implementer 双端对账值); 删笔全史=+76425.75
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

CAND1 = lambda t: (t[fIdx['market_tier']] or '') == '牛市·主升' and t[fIdx['signal']] in ('buy_aux', 'buy_backup')

def build_pf(mode, K):
    """返回 (pool, fade, base_k, pf_k): base_k=基线topK, pf_k=补位topK(topK前剔CAND1)"""
    pool = S.build_mode_pool(tr, fIdx, mode)
    fade = [t for t in pool if S.passes_fade(t, fIdx, filters, mmask, mD, eD, rD)]
    kept = [t for t in fade if not CAND1(t)]
    return pool, fade, S.topk_by_date(fade, fIdx, K), S.topk_by_date(kept, fIdx, K)

def pnl(rows): return sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows)
def sd_of(t): return str(t[fIdx['signal_date']] or '')
def bkey(t): return S.base_key(t, fIdx)

# ============ 交叉校验锚点 ============
_, _, k1A, k1PF = build_pf('A', 1)
k1B_del = [t for t in k1A if not CAND1(t)]   # 删笔口径(旧报告)
base_full = pnl(k1A); pf_full = pnl(k1PF); del_full = pnl(k1B_del)
print(f'交叉校验: 基线全史={base_full:+.2f}(期望+66530.38) | 补位全史={pf_full:+.2f}(期望≈+73103) | 删笔全史={del_full:+.2f}(期望+76425.75)')
assert abs(base_full - 66530.38) < 0.5, '基线锚点不符!'

OUT = dict(generated_at=datetime.datetime.now().isoformat(),
           anchors=dict(base_full=base_full, positionfill_full=pf_full, delete_full=del_full))

# ============ ① 替补盈亏专项分解(用户第一问) ============
def fill_decomp(base_k, pf_k, tag):
    """逐日对比基线 vs 补位: 被拦笔(基线选中且命中CAND1) vs 替补笔(补位新顶上)。"""
    byd_b, byd_p = {}, {}
    for t in base_k: byd_b.setdefault(sd_of(t), []).append(t)
    for t in pf_k: byd_p.setdefault(sd_of(t), []).append(t)
    blocked, filled, empty_days = [], [], []   # empty_days=被拦且无替补
    for sd, rows in byd_b.items():
        hit = [t for t in rows if CAND1(t)]
        if not hit: continue
        blocked += hit
        rep = byd_p.get(sd, [])
        if rep: filled += [t for t in rep if bkey(t) not in set(bkey(x) for x in rows)]
        else: empty_days.append((sd, hit))
    # 内部一致性: 补位-删笔 = 替补净额
    stat = dict(tag=tag,
        blocked_n=len(blocked), blocked_pnl=pnl(blocked),
        filled_days=len(filled) , filled_n=len(filled), filled_pnl=pnl(filled),
        filled_win_days=sum(1 for t in filled if S.calc_row(t, fIdx)['pnlYuan'] > 0),
        filled_lose_days=sum(1 for t in filled if S.calc_row(t, fIdx)['pnlYuan'] <= 0),
        empty_days=len(empty_days), empty_blocked_pnl=pnl([t for _, hs in empty_days for t in hs]),
        consistency_check=pf_full - del_full)
    stat['net_improvement_pf'] = -stat['blocked_pnl'] + stat['filled_pnl']
    stat['net_improvement_del'] = -stat['blocked_pnl']
    return stat, blocked, filled, empty_days

def decomp_print(st):
    print(f"  被拦 {st['blocked_n']}笔 净{st['blocked_pnl']:+.0f}元 | 有替补 {st['filled_days']}天/{st['filled_n']}笔 "
          f"替补净{st['filled_pnl']:+.0f}元(赚{st['filled_win_days']}天/亏{st['filled_lose_days']}天) | 空仓 {st['empty_days']}天(被拦部分净{st['empty_blocked_pnl']:+.0f}元)")
    print(f"  补位改善={st['net_improvement_pf']:+.0f}元 vs 删笔改善={st['net_improvement_del']:+.0f}元 | 一致性校验: 补位全史-删笔全史={st['consistency_check']:+.2f} 应=替补净额")

print()
print('=' * 78)
print('① 替补盈亏专项分解(K1, mode A): 用户问「替补是不是毒药」')
print('=' * 78)
st_all, blocked_all, filled_all, empty_all = fill_decomp(k1A, k1PF, '全史2011-2026')
print('【全史】'); decomp_print(st_all)
sub_b58 = [t for t in k1A if '20260500' <= sd_of(t) < '20260900']
sub_p58 = [t for t in k1PF if '20260500' <= sd_of(t) < '20260900']
st_58, blk58, fil58, emp58 = fill_decomp(sub_b58, sub_p58, '2026年5-8月')
print('【5-8月窗口】'); decomp_print(st_58)
# 替补画像(sig分布)
from collections import Counter
sig_cnt = Counter((t[fIdx['signal']] or '') for t in filled_all)
rat_cnt = Counter(str(t[fIdx['rating']] or '') for t in filled_all)
tier_cnt = Counter((t[fIdx['market_tier']] or '(空)') for t in filled_all)
yr_cnt = Counter(sd_of(t)[:4] for t in filled_all)
print(f"  替补笔画像: sig={dict(sig_cnt)} rating={dict(rat_cnt)} tier={dict(tier_cnt)}")
print(f"  替补按年: {dict(sorted(yr_cnt.items()))}")
# 替补逐笔明细(5-8月窗口, 数量少直接列)
print('  【5-8月替补逐笔】')
for t in sorted(fil58, key=sd_of):
    c = S.calc_row(t, fIdx)
    print(f"    {sd_of(t)} {t[fIdx['signal']]:<12} {t[fIdx['index_id']]} rating={t[fIdx['rating']]} tier={t[fIdx['market_tier']]} pnl={c['pnlYuan']:+.0f}元")
# 全史替补 top 盈亏各5笔
print('  【全史替补盈Top5】')
for t in sorted(filled_all, key=lambda x: -S.calc_row(x, fIdx)['pnlYuan'])[:5]:
    print(f"    {sd_of(t)} {t[fIdx['signal']]:<12} {t[fIdx['index_id']]} pnl={S.calc_row(t,fIdx)['pnlYuan']:+.0f}元")
print('  【全史替补亏Top5】')
for t in sorted(filled_all, key=lambda x: S.calc_row(x, fIdx)['pnlYuan'])[:5]:
    print(f"    {sd_of(t)} {t[fIdx['signal']]:<12} {t[fIdx['index_id']]} pnl={S.calc_row(t,fIdx)['pnlYuan']:+.0f}元")
OUT['fill_decomp'] = dict(all=st_all, w58=st_58, filled_sig=dict(sig_cnt), filled_rating=dict(rat_cnt),
                          filled_year=dict(sorted(yr_cnt.items())))

# ============ ② 2026 双向检验(补位 vs 删笔 vs 基线) ============
print()
print('=' * 78)
print('② 2026 双向检验: 4月保利润 / 5-8月砍亏 / 全年')
print('=' * 78)
W26 = [('2026年4月', '20260331', '20260501'), ('2026年5-8月', '20260500', '20260900'), ('2026全年(至08-20)', '20251231', '99999999')]
out26 = []
for tag, lo, hi in W26:
    def sub(rows): return [t for t in rows if lo < sd_of(t) < hi]
    b, p, d = sub(k1A), sub(k1PF), sub(k1B_del)
    sb, sp, sdd = S.window_stats(b, fIdx), S.window_stats(p, fIdx), S.window_stats(d, fIdx)
    print(f"{tag}: 基线 {sb['cumYuan']:+.0f}({sb['n']}笔) -> 补位 {sp['cumYuan']:+.0f}({sp['n']}笔, 改善{sp['cumYuan']-sb['cumYuan']:+.0f}) | 删笔对照 {sdd['cumYuan']:+.0f}({sdd['n']}笔, 改善{sdd['cumYuan']-sb['cumYuan']:+.0f})")
    out26.append(dict(tag=tag, base=sb['cumYuan'], base_n=sb['n'], pf=sp['cumYuan'], pf_n=sp['n'],
                      dele=sdd['cumYuan'], dele_n=sdd['n']))
OUT['test_2026'] = out26

# ============ ③ 三道门(补位口径重新定标) ============
print()
print('=' * 78)
print('③ 三道门(补位口径): 门1 n>=30 | 门2 2026效果(5-8月改善>=+3000 且 4月误伤>=-1500) | 门3 前向2024-26样本外<=0 且 按年负占比>=55%')
print('=' * 78)
# 毒性指标(被拦笔自身, 与第一轮删笔门槛同义可比; 被拦集合与删笔口径完全相同)
blocked_tox_yr = {}
for t in blocked_all:
    y = sd_of(t)[:4]
    blocked_tox_yr[y] = blocked_tox_yr.get(y, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
neg_tox_years = sum(1 for v in blocked_tox_yr.values() if v < 0)
fwd_blocked = sum(v for y, v in blocked_tox_yr.items() if y >= '2024')
# 补位真实效果(净改善 = 替补 - 被拦): 效果层单独评估
improve_yr = {}
for t in blocked_all:
    y = sd_of(t)[:4]
    improve_yr[y] = improve_yr.get(y, 0.0) - S.calc_row(t, fIdx)['pnlYuan']
for t in filled_all:
    y = sd_of(t)[:4]
    improve_yr[y] = improve_yr.get(y, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
fwd_improve = sum(v for y, v in improve_yr.items() if y >= '2024')
g1 = st_all['blocked_n'] >= 30
imp58 = out26[1]['pf'] - out26[1]['base']; hurt4 = out26[0]['pf'] - out26[0]['base']
g2 = imp58 >= 3000 and hurt4 >= -1500
g3a = fwd_blocked <= 0                      # 毒性: 被拦笔样本外为亏毒
g3b = neg_tox_years / max(len(blocked_tox_yr), 1) >= 0.55   # 毒性: 被拦按年多数为亏毒
g3c = fwd_improve >= 0                      # 补位特有: 叠加后样本外真实不变差
g3 = g3a and g3b and g3c
print(f"门1: 被拦 {st_all['blocked_n']}笔 >=30 -> {'PASS' if g1 else 'FAIL'}")
print(f"门2: 5-8月改善 {imp58:+.0f} (>=+3000?) | 4月误伤 {hurt4:+.0f} (>=-1500?) -> {'PASS' if g2 else 'FAIL'}")
print(f"门3a 毒性·前向: 被拦笔2024-26自身净额 {fwd_blocked:+.0f} (<=0?) -> {'PASS' if g3a else 'FAIL'}")
print(f"门3b 毒性·按年: 被拦按年<0占比 {neg_tox_years}/{len(blocked_tox_yr)}={neg_tox_years/max(len(blocked_tox_yr),1)*100:.0f}% (>=55%?) -> {'PASS' if g3b else 'FAIL'}")
print(f"门3c 补位效果·前向: 样本外净改善 {fwd_improve:+.0f} (>=0 不变差?) -> {'PASS' if g3c else 'FAIL'} -> 门3 {'PASS' if g3 else 'FAIL'}")
print(f"  补位净改善按年明细(正=叠加后当年变好): {dict(sorted(((y, round(v)) for y, v in improve_yr.items())))}")
print(f"  被拦笔毒性按年(与第一轮删笔口径同值): {dict(sorted(((y, round(v)) for y, v in blocked_tox_yr.items())))}")
ALL_PASS = g1 and g2 and g3
print(f"==> 候选1在补位口径下: {'三道门全过, 结论依然成立' if ALL_PASS else '存在 FAIL 项(见上)'}")
OUT['three_gates'] = dict(gate1_pass=g1, gate2_pass=g2, gate3_pass=g3,
                          gate3a_fwd_blocked_le0=g3a, gate3b_neg_year_ratio=g3b, gate3c_fwd_improve_ge0=g3c,
                          all_pass=ALL_PASS, imp58=imp58, hurt_apr=hurt4,
                          fwd_blocked=fwd_blocked, fwd_improve=fwd_improve,
                          tox_neg_ratio=f'{neg_tox_years}/{len(blocked_tox_yr)}',
                          yearly_improve=dict(sorted(((y, round(v, 1)) for y, v in improve_yr.items()))),
                          yearly_blocked_toxicity=dict(sorted(((y, round(v, 1)) for y, v in blocked_tox_yr.items()))))

# ============ ④ K1-K4 敏感性 + A-F/H 模式同向性(补位) ============
print()
print('=' * 78)
print('④a K档敏感性(K1-K4 × 基线|补位|删笔, 5-8月 / 2026全年 / 全史)')
print('=' * 78)
ktab = []
for K in (1, 2, 3, 4):
    _, _, bk, pk = build_pf('A', K)
    dk = [t for t in bk if not CAND1(t)]
    def w(rows, lo=None, hi='99999999'):
        subr = [t for t in rows if (lo is None or sd_of(t) >= lo) and sd_of(t) < hi]
        return pnl(subr), len(subr)
    row = dict(K=K)
    for wtag, lo, hi in [('w58', '20260501', '20260900'), ('y2026', '20260101', '20260900'), ('full', None, '99999999')]:
        bb = w(bk, lo, hi); pp = w(pk, lo, hi); dd = w(dk, lo, hi)
        row[wtag] = dict(base=bb[0], pf=pp[0], dele=dd[0], pf_imp=pp[0]-bb[0], del_imp=dd[0]-bb[0])
    print(f"K{K}: 5-8月 基线{row['w58']['base']:+.0f} 补位{row['w58']['pf']:+.0f}(改善{row['w58']['pf_imp']:+.0f}) 删笔{row['w58']['dele']:+.0f}(改善{row['w58']['del_imp']:+.0f})"
          f" | 2026 基线{row['y2026']['base']:+.0f} 补位{row['y2026']['pf']:+.0f}({row['y2026']['pf_imp']:+.0f}) | 全史 基线{row['full']['base']:+.0f} 补位{row['full']['pf']:+.0f}({row['full']['pf_imp']:+.0f})")
    ktab.append(row)
OUT['k_sensitivity'] = ktab

print()
print('=' * 78)
print('④b A-F 六短线模式 + H 同向性(补位口径, 全史改善 + 按年负占比); G/I 长线仅记录')
print('=' * 78)
mtab = []
for mode in 'ABCDEFGHI':
    _, _, bk, pk = build_pf(mode, 1)
    bb, pp = pnl(bk), pnl(pk)
    # 按年净改善(替补-被拦)
    bl, fl = {}, {}
    byd_b = {}
    for t in bk: byd_b.setdefault(sd_of(t), []).append(t)
    byd_p = {}
    for t in pk: byd_p.setdefault(sd_of(t), []).append(t)
    yrs = {}
    for sd, rows in byd_b.items():
        for t in rows:
            if CAND1(t):
                y = sd[:4]; yrs[y] = yrs.get(y, 0.0) - S.calc_row(t, fIdx)['pnlYuan']
    for sd, rows in byd_p.items():
        bset = set(bkey(x) for x in byd_b.get(sd, []))
        for t in rows:
            if bkey(t) not in bset:
                y = sd[:4]; yrs[y] = yrs.get(y, 0.0) + S.calc_row(t, fIdx)['pnlYuan']
    neg = sum(1 for v in yrs.values() if v < -0.5); tot = len(yrs)
    grp = '短线A-F' if mode in 'ABCDEF' else '长线G-H-I'
    print(f"mode {mode}({grp}): 全史基线 {bb:+.0f} -> 补位 {pp:+.0f} (改善 {pp-bb:+.0f}) | 按年负占比 {neg}/{tot}"
          f"{' ⚠长线不适配仅记录' if mode in 'GI' else ''}")
    mtab.append(dict(mode=mode, group=grp, base=bb, pf=pp, improve=pp-bb, neg_years=neg, tot_years=tot))
OUT['mode_matrix'] = mtab
af_bad = [r['mode'] for r in mtab if r['group'] == '短线A-F' and r['improve'] <= 0]
af_same = not af_bad
print(f"A-F 六模式补位口径同向(改善>0): {'是(6/6)' if af_same else f'否({6-len(af_bad)}/6, 反向: {af_bad})'}")

# ============ ⑤ 五窗口 + 大熊市 + 逐年 + 回撤(主列补位, 副列删笔) ============
def three_col(lo=None, hi=None):
    def sub(rows): return [t for t in rows if (lo is None or sd_of(t) >= lo) and (hi is None or sd_of(t) <= hi)]
    sb, sp, sdd = S.window_stats(sub(k1A), fIdx), S.window_stats(sub(k1PF), fIdx), S.window_stats(sub(k1B_del), fIdx)
    return sb, sp, sdd

print()
print('=' * 78)
print('⑤ 五窗口对照(signal_date>=起点; 主列=补位口径, 副列=删笔对照)')
print('=' * 78)
wins_out = []
for tag, lo in [('近1年(2025-08-22起)', '20250822'), ('近2年(2024-08-22起)', '20240822'),
                ('近3年(2023-08-22起)', '20230822'), ('近5年(2021-08-22起)', '20210822'), ('全史', None)]:
    sb, sp, sdd = three_col(lo=lo)
    dp = sp['cumYuan'] - sb['cumYuan']; dd = sdd['cumYuan'] - sb['cumYuan']
    print(f"{tag}: 基线 {sb['cumYuan']:+.0f}/{sb['n']}笔/{sb['winRate']:.1f}% -> 补位 {sp['cumYuan']:+.0f}/{sp['n']}笔/{sp['winRate']:.1f}% (改善{dp:+.0f}, 占峰值本金{dp/(max(sb['peakPosN'],1)*10000)*100:+.2f}%)"
          f" | 删笔 {sdd['cumYuan']:+.0f}/{sdd['n']}笔 ({dd:+.0f})")
    wins_out.append(dict(tag=tag, base=dict(n=sb['n'], cumYuan=sb['cumYuan'], winRate=sb['winRate']),
                         pf=dict(n=sp['n'], cumYuan=sp['cumYuan'], winRate=sp['winRate'], peakPosN=sp['peakPosN']),
                         dele=dict(n=sdd['n'], cumYuan=sdd['cumYuan'], winRate=sdd['winRate']), diff_pf=dp, diff_del=dd))
OUT['five_windows'] = wins_out

print()
print('大熊市专项窗口(闭区间, 补位口径):')
bear_out = []
for tag, lo, hi in [('2015股灾+熔断', '20150615', '20160131'), ('2018全年熊', '20180101', '20181231'),
                    ('2022熊(1-4月)', '20220101', '20220430'), ('2024Q1微盘灾', '20240101', '20240229')]:
    sb, sp, sdd = three_col(lo=lo, hi=hi)
    print(f"{tag}: 基线 {sb['cumYuan']:+.0f}({sb['n']}笔) -> 补位 {sp['cumYuan']:+.0f}({sp['n']}笔, 差{sp['cumYuan']-sb['cumYuan']:+.0f}) | 删笔 {sdd['cumYuan']:+.0f}({sdd['n']}笔)")
    bear_out.append(dict(tag=tag, base=sb['cumYuan'], base_n=sb['n'], pf=sp['cumYuan'], pf_n=sp['n'],
                         dele=sdd['cumYuan'], dele_n=sdd['n']))
OUT['bear_windows'] = bear_out

print()
print('逐年完整表(基线 | 补位(差) | 删笔(差)):')
years = sorted(set(sd_of(t)[:4] for t in k1A))
yr_out = []
for y in years:
    def yy(rows): return sum(S.calc_row(t, fIdx)['pnlYuan'] for t in rows if sd_of(t)[:4] == y)
    nb = len([t for t in k1A if sd_of(t)[:4] == y]); npf = len([t for t in k1PF if sd_of(t)[:4] == y])
    ndl = len([t for t in k1A if sd_of(t)[:4] == y]) - len([t for t in k1B_del if sd_of(t)[:4] == y])
    b, p, d = yy(k1A), yy(k1PF), yy(k1B_del)
    print(f"{y}: 基线{b:+9.0f}({nb}笔) 补位{p:+9.0f}({npf}笔, {p-b:+7.0f}) 删笔{d:+9.0f}({ndl}笔, {d-b:+7.0f})")
    yr_out.append(dict(year=y, base=b, base_n=nb, pf=p, pf_n=npf, dele=d, dele_n=ndl))
OUT['yearly'] = yr_out

print()
print('全史回撤与修复(补位口径, 同 mine8 口径):')
def drawdown(rows, tag):
    asc = sorted(rows, key=sd_of)
    daily = {}
    for t in asc:
        daily[sd_of(t)] = daily.get(sd_of(t), 0.0) + S.calc_row(t, fIdx)['pnlYuan']
    dates = sorted(daily)
    peak_pos_n = S.window_stats(rows, fIdx)['peakPosN']
    cum = 0.0; peak = 0.0; peak_date = dates[0]
    mdd = 0.0; mdd_pk = mdd_tr = None
    cur_trough = 0.0; cur_trough_date = None
    segs = []
    for dt in dates:
        cum += daily[dt]
        if cum >= peak - 1e-9:
            if cum > peak + 1e-9 and peak_date != dt and cur_trough_date is not None and peak - cur_trough > 1e-9:
                segs.append(dict(peak_date=peak_date, trough_date=cur_trough_date,
                                 recov_days=(datetime.date(int(dt[:4]), int(dt[4:6]), int(dt[6:8])) - datetime.date(int(peak_date[:4]), int(peak_date[4:6]), int(peak_date[6:8]))).days))
            if cum > peak or cur_trough_date is None:
                peak = cum; peak_date = dt; cur_trough = cum; cur_trough_date = dt
        else:
            if peak - cum > (peak - cur_trough):
                cur_trough = cum; cur_trough_date = dt
            if peak - cum > mdd:
                mdd = peak - cum; mdd_pk = peak_date; mdd_tr = dt
    open_seg = None
    if cur_trough_date is not None and peak - cur_trough > 1e-9:
        d1 = datetime.date(int(dates[-1][:4]), int(dates[-1][4:6]), int(dates[-1][6:8]))
        open_seg = dict(peak_date=peak_date, trough_date=cur_trough_date, recov_days=(d1 - datetime.date(int(peak_date[:4]), int(peak_date[4:6]), int(peak_date[6:8]))).days)
    all_segs = segs + ([open_seg] if open_seg else [])
    longest = max(all_segs, key=lambda s: s['recov_days']) if all_segs else None
    denom = max(peak_pos_n, 1) * 10000.0
    print(f"[{tag}] 终值={cum:+.0f} | 最大回撤 {mdd:+.0f}元({mdd/denom*100:.2f}%峰值本金, {mdd_pk}->{mdd_tr}) | 最长修复 {longest['recov_days']}天({longest['peak_date']}高点)" if longest else f"[{tag}] 无回撤段")
    return dict(final=cum, maxDD=mdd, maxDD_pct=mdd/denom*100, maxDD_peak=mdd_pk, maxDD_trough=mdd_tr,
                longest_recov_days=longest['recov_days'] if longest else None, longest_peak=longest['peak_date'] if longest else None)
OUT['drawdown'] = dict(base=drawdown(k1A, '基线8键'), pf=drawdown(k1PF, '补位9键'))

with open(os.path.join(HERE, 'data/mine11_positionfill.json'), 'w') as f:
    json.dump(OUT, f, ensure_ascii=False, indent=1, default=float)
print('\nmine11_positionfill.json written')
