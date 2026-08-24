# -*- coding: utf-8 -*-
"""bj50 兜底残留「宇宙感知剪枝」影响面对比分析(2026-08-24 主控令,只读模拟,不改任何产物)。

目的:
  根修计划 = signal_kelly_backtest.py 加宇宙感知剪枝(重放时冻结值属已排除类别→不入样)。
  本脚本在活产物 trades 上内存模拟该剪枝(index_id=bj50 全部行剔除),量化其统计影响面,
  供用户在"剪枝 vs 保留残留"间拍板。只出数据,不做方向推荐(结果好坏≠口径正确性,报告诚实标注)。

输入依赖(全部只读):
  1. static-site/data/signal_kelly_trades.json   活产物(gen=2026-08-24 19:31, 274,284 行, 16象限×9卡)
  2. data/signal_kelly_trades.json               8-09 旧版残留(gen=2026-08-09 19:21, 177,096 行, 6卡)
                                                 —— 仅用于钉死审计报告"738 笔"口径,不参与剔除模拟
  3. data/signal_kelly_etf_freeze.json           冻结表(28,121 键, bj50=72 键)
  4. data/board_etf_map.json                     bj50=[] 空数组(无正式收录)
  5. config/universe_rules.yaml                  empty_array 声明现状
  6. sim_window_loss_mining_20260822 引擎(sim_core/r2_common/mine25/mine27 等,NEW14 组合管线复用)

输出:
  docs/kelly/analysis/data/bj50-prune-impact-20260824.json(机器可读全量结果)
  stdout 摘要(供报告摘录)

关键口径(一句话):
  剔除模拟 = 从每模式去重池(build_mode_pool+finish_pool, 与首页模拟回测弹窗同源)中删 index_id=bj50
  的全部交易后走同一管线;静态展示层口径 = trades 各象限各卡直接减 bj50 行。
  AI 宏观过滤默认组合 = v1.1.5 NEW14 十四键(common.js _KELLY_FADE_DEFAULT_MODE 单源),
  锚点断言 NEW14=+122,648.33 / mdd -4,178.01(mine30 同款, 必过才往下)。
  补位口径: K1 top-K 前黑名单过滤(ev_new_on), 被剔信号腾出的名额由同日次优信号补位——
  与 memory filter-backtest-position-fill-caliber 一致; diff_detail 给被剔/替补盈亏分解。

测试基准声明(§5.4②):
  current baseline = v1.1.5(NEW14 十四键默认, git tag v1.1.5@04144b269)。
  本分析为「活产物上的剔除模拟」= 非标准口径实验(标准基准不动产物), 结论仅用于影响面评估。

复现:
  python3 docs/kelly/analysis/scripts/bj50_prune_impact_20260824.py
  (约 1~2 分钟, 无网络依赖; 数据截止 = trades generated_at 2026-08-24 19:31)
"""
import os, sys, json, collections

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(BASE, '..', '..', '..', '..'))
MINE = os.path.join(ROOT, 'docs/kelly/analysis/scripts/sim_window_loss_mining_20260822')
sys.path.insert(0, MINE)

from sim_core import load, build_mode_pool, base_key
import r2_common as R
import mine25_longline_operable as M25
import mine27_g_exhaustive_simplified as M27   # noqa: F401  (import 即加载 FEATS/NEW14_KEYS)
from mine25_longline_operable import hits_on, ev_new_on, dd_of
from mine27_g_exhaustive_simplified import finish_pool, _curve

TRADES_LIVE = os.path.join(ROOT, 'static-site/data/signal_kelly_trades.json')
TRADES_OLD = os.path.join(ROOT, 'data/signal_kelly_trades.json')
FREEZE = os.path.join(ROOT, 'data/signal_kelly_etf_freeze.json')
MAP_PATH = os.path.join(ROOT, 'data/board_etf_map.json')
YAML_PATH = os.path.join(ROOT, 'config/universe_rules.yaml')
OUT_JSON = os.path.join(BASE, '..', 'data', 'bj50-prune-impact-20260824.json')

BJ = 'bj50'
out = {'generated_by': os.path.basename(__file__), 'trades_live_generated_at': None}


def sec(t):
    print(f'\n===== {t} =====')


# ---------- Part1 残留画像 ----------
sec('Part1 残留画像')
tr, fIdx = load(TRADES_LIVE)
gen_at = tr.get('generated_at')
out['trades_live_generated_at'] = gen_at
q = tr['quadrants']
i_idx, i_sig, i_sd, i_bd, i_etfc, i_etfn = (fIdx[k] for k in
    ('index_id', 'signal', 'signal_date', 'buy_date', 'etf_code', 'etf_name'))
total_rows = sum(len(rows) for qv in q.values() for rows in qv.values())
n_cards = len(next(iter(q.values())))

bj_quad_card = {}
uniq_keys = set()          # (sd,index,sig) 信号级
uniq_trades = set()        # + buy_date 交易级(单模式内)
bd_list, sd_list = [], []
for qk, qv in q.items():
    for ck, rows in qv.items():
        n = sum(1 for r in rows if r[i_idx] == BJ)
        if n:
            bj_quad_card.setdefault(qk, {})[ck] = n
        for r in rows:
            if r[i_idx] == BJ:
                uniq_keys.add((r[i_sd], r[i_idx], r[i_sig]))
                uniq_trades.add((r[i_sd], r[i_idx], r[i_sig], r[i_bd]))
                bd_list.append(r[i_bd]); sd_list.append(r[i_sd])
print(f"活产物 gen={gen_at} 总行={total_rows} 卡数={n_cards}")
print(f"bj50 展示行合计={sum(sum(c.values()) for c in bj_quad_card.values())} 分布象限={len(bj_quad_card)}")
print(f"bj50 唯一信号键={len(uniq_keys)} 唯一交易(sd,idx,sig,buy)={len(uniq_trades)}")
yr = collections.Counter(str(d)[:4] for d in bd_list)
per_signal = collections.Counter()
for sd, _, sig, bd in uniq_trades:
    per_signal[str(sd)[:4]] += 1
print(f"bj50 buy_date 行级按年={dict(sorted(yr.items()))}")
print(f"bj50 信号级按年(去重)={dict(sorted(per_signal.items()))}")
mo = collections.Counter(str(d)[:6] for d in sd_list)
print(f"bj50 signal_date 按月(去重信号)top8={mo.most_common(8)}")
etfs = set()
for qk, qv in list(q.items()):
    for ck, rows in qv.items():
        for r in rows:
            if r[i_idx] == BJ:
                etfs.add((r[i_etfc], r[i_etfn]))
print(f"bj50 结算 ETF 集合={sorted(etfs)}")
sig_types = collections.Counter(sig for _, _, sig in uniq_keys)
print(f"bj50 信号类型分布={dict(sig_types)}")

out['part1'] = {
    'trades_gen': gen_at, 'total_rows': total_rows,
    'bj_rows_total': sum(sum(c.values()) for c in bj_quad_card.values()),
    'bj_by_quadrant_per_card': {qk: sorted(set(c.values()))[0] if c else 0 for qk, c in bj_quad_card.items()},
    'unique_signal_keys': len(uniq_keys), 'unique_trades': len(uniq_trades),
    'rows_level_year': dict(sorted(yr.items())),
    'signal_level_year': dict(sorted(per_signal.items())),
    'settle_etfs': [list(e) for e in sorted(etfs)],
    'signal_type_dist': dict(sig_types),
}

# freeze 72 键 vs trades 41 键
fz = json.load(open(FREEZE))
fz_bj = {k: v for k, v in fz.items() if f'|{BJ}|' in k}
fz_dates = sorted(k.split('|')[0] for k in fz_bj)
tr_keyset = {k[0] + '|' + BJ + '|' + k[2] for k in uniq_keys}
missing = sorted(set(fz_bj) - tr_keyset)
print(f"\nfreeze bj50 键={len(fz_bj)} (日期范围 {fz_dates[0]}~{fz_dates[-1]}, score 集合="
      f"{sorted(set(v.get('track_score') for v in fz_bj.values()))}, frozen_at 集合="
      f"{sorted(set(v.get('frozen_at') for v in fz_bj.values()))})")
print(f"freeze 有而 trades 未成交的键={len(missing)}")
if missing:
    md = [k.split('|')[0] for k in missing]
    print(f"  未成交键日期范围 {min(md)}~{max(md)}, 全部早于首笔成交日({min(str(d) for d in sd_list)}): "
          f"{all(d < min(str(d) for d in sd_list) for d in md)}")
out['part1']['freeze'] = {
    'keys': len(fz_bj), 'date_range': [fz_dates[0], fz_dates[-1]],
    'scores': sorted(set(v.get('track_score') for v in fz_bj.values())),
    'not_traded_keys': len(missing),
    'not_traded_all_before_first_trade': bool(all(d < min(str(d) for d in sd_list) for d in md)) if missing else None,
}

# 738 vs 1476: 旧版产物结构对照
old_profile = None
if os.path.exists(TRADES_OLD):
    tro, fo = load(TRADES_OLD)
    qo = tro['quadrants']
    o_total = sum(len(rows) for qv in qo.values() for rows in qv.values())
    o_cards = len(next(iter(qo.values())))
    o_bj, o_uniq = 0, set()
    o_quad = collections.Counter()
    for qk, qv in qo.items():
        for ck, rows in qv.items():
            n = sum(1 for r in rows if r[fo['index_id']] == BJ)
            o_bj += n
            if n:
                o_quad[qk] += n
            for r in rows:
                if r[fo['index_id']] == BJ:
                    o_uniq.add((r[fo['signal_date']], r[fo['buy_date']]))
    old_profile = {'generated_at': tro.get('generated_at'), 'total_rows': o_total, 'cards': o_cards,
                   'bj_rows': o_bj, 'bj_unique_trades': len(o_uniq),
                   'by_quadrant': dict(o_quad)}
    print(f"\n旧版产物 gen={tro.get('generated_at')} 总行={o_total} 卡数={o_cards}")
    print(f"  bj50 行={o_bj} 唯一交易={len(o_uniq)} 象限分布={dict(o_quad)}")
    # 每信号出现的象限组数: mkt_a + rating其一 + sig其一 (+ 新版 etf_has_track) —— 组内互斥拆分
    o_groups = 1 + 1 + 1          # 旧版: mkt_a / rating(mid|low) / sig(main|aux|special|backup)
    n_groups = 1 + 1 + 1 + 1      # 新版: + etf_has_track(track_tier=null 归入 has_track 展示)
    print(f"  口径换算: 旧=41交易×{o_groups}象限组×{o_cards}卡={len(o_uniq)*o_groups*o_cards}; "
          f"新=41×{n_groups}组×{n_cards}卡={len(uniq_trades)*n_groups*n_cards}")
    # 审计口径交叉复算(universe_fallback_value_audit.py T2A 同款: 全部行 profit 字段直接求和)
    flds = tro['fields']
    pf, rf = flds.index('profit'), flds.index('return_pct')
    ob, op, ow = [], [], 0
    for qk, qv in qo.items():
        for ck, rows in qv.items():
            for r in rows:
                if r[fo['index_id']] == BJ:
                    ob.append(r); op.append(r[pf]); ow += 1 if r[rf] > 0 else 0
    audit_repro = {'n': len(ob), 'winrate_pct': round(ow / max(len(ob), 1) * 100, 2),
                   'avg_ret_pct': round(sum(r[rf] for r in ob) / max(len(ob), 1), 3),
                   'total_profit_yuan': round(sum(op), 0)}
    print(f"  审计口径交叉复算(行级 profit 直接求和): {audit_repro} (审计原值 n=738/-0.14%/-10329)")
    old_profile['audit_caliber_repro'] = audit_repro
out['part1']['old_version_738_caliber'] = old_profile

# ---------- Part4 受影响面(先算, Part2 要用) ----------
sec('Part4 受影响面')
bmap = json.load(open(MAP_PATH))
bj_entry = bmap.get(BJ, '<absent>')
yaml_txt = open(YAML_PATH).read() if os.path.exists(YAML_PATH) else ''
empty_decl = [ln.strip() for ln in yaml_txt.splitlines() if 'ftse100' in ln or 'kospi' in ln or BJ in ln]
affected_days = sorted({str(bd) for bd in bd_list})
print(f"board_etf_map[{BJ}] = {bj_entry!r} (空数组=无正式收录跟踪ETF)")
print(f"universe_rules.yaml 中 bj50/ftse100/kospi 相关声明行: {empty_decl if empty_decl else '无 bj50 声明'}")
print(f"受影响交易日(buy_date unique)={len(affected_days)} ({min(affected_days)}~{max(affected_days)})")
print(f"受影响信号键={len(uniq_keys)}; 正确归属判定依据: map 无正式收录→宇宙感知剪枝后不入样(无其他可匹配ETF)")
out['part4'] = {
    'map_bj50': bj_entry, 'yaml_decl_lines': empty_decl,
    'affected_buy_days': len(affected_days), 'affected_day_range': [min(affected_days), max(affected_days)],
    'affected_signal_keys': len(uniq_keys),
    'correct_assignment': 'board_etf_map bj50=[] 空数组 → 无正式收录 → 剪枝后该 41 信号全部不入样',
}

# ---------- Part2/3/5: 九模式 RAW 池 剔除前后 ----------
sec('Part2 九模式 RAW 池剔除前后(费后, K1 补位)')
MODES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']
mode_tbl = {}
bj_share = {}
for mode in MODES:
    pool = finish_pool(build_mode_pool(tr, fIdx, mode), fIdx)
    R.init(pool, fIdx)
    base_sel = ev_new_on(pool, fIdx, set())               # RAW = 无黑名单, K1 补位选择
    st_b = R.stats_of(base_sel)
    dd_b = dd_of(*_curve(base_sel, fIdx))
    pool_p = [t for t in pool if t[i_idx] != BJ]
    R.init(pool_p, fIdx)
    prune_sel = ev_new_on(pool_p, fIdx, set())
    st_p = R.stats_of(prune_sel)
    dd_p = dd_of(*_curve(prune_sel, fIdx))
    det = R.diff_detail(base_sel, prune_sel)              # 被剔/替补分解
    hd_b = [t[fIdx['hold_days']] for t in base_sel if t[fIdx['hold_days']] is not None]
    hd_p = [t[fIdx['hold_days']] for t in prune_sel if t[fIdx['hold_days']] is not None]
    st_b['avg_hold_days'] = round(sum(hd_b) / len(hd_b), 2) if hd_b else None
    st_p['avg_hold_days'] = round(sum(hd_p) / len(hd_p), 2) if hd_p else None
    # blocked 明细: 被剔入选笔是哪天/为何当选(当日候选数)
    blk_keys = {base_key(t, fIdx) for t in base_sel} - {base_key(t, fIdx) for t in prune_sel}
    byday = collections.Counter(str(t[i_sd]) for t in pool)
    blk_detail = [{'signal_date': str(t[i_sd]), 'buy_date': str(t[i_bd]),
                   'pnlYuan': round(t[R.IDX_PNL]['pnlYuan'], 2),
                   'candidates_that_day': byday.get(str(t[i_sd]), 0)} for t in base_sel
                  if base_key(t, fIdx) in blk_keys]
    # bj50 自身在该模式的池内表现
    bj_rows = [t for t in pool if t[i_idx] == BJ]
    bj_pnl = sum(t[R.IDX_PNL]['pnlYuan'] for t in bj_rows)
    bj_win = sum(1 for t in bj_rows if t[R.IDX_PNL]['pnlYuan'] > 0)
    hd = [t[fIdx['hold_days']] for t in bj_rows if t[fIdx['hold_days']] is not None]
    mode_tbl[mode] = {
        'base': {**st_b, 'mdd': round(dd_b['mdd'], 2)},
        'pruned': {**st_p, 'mdd': round(dd_p['mdd'], 2)},
        'delta_total': round(st_p['total'] - st_b['total'], 2),
        'delta_n': st_p['n'] - st_b['n'],
        'bj_in_pool': {'n': len(bj_rows), 'pnl': round(bj_pnl, 2),
                       'winrate_pct': round(bj_win / max(len(bj_rows), 1) * 100, 1),
                       'avg_hold_days': round(sum(hd) / len(hd), 1) if hd else None},
        'diff_detail': det, 'blocked_detail': blk_detail,
    }
    bj_share[mode] = round(bj_pnl, 2)
    b = mode_tbl[mode]['base']; p = mode_tbl[mode]['pruned']
    print(f"mode {mode}: n {b['n']}→{p['n']} | 净利 {b['total']:+,.0f}→{p['total']:+,.0f} "
          f"(Δ{p['total']-b['total']:+,.0f}) | 胜率 {b['winRate']}%→{p['winRate']}% | mdd {b['mdd']:,.0f}→{p['mdd']:,.0f} "
          f"| bj50自身 n={len(bj_rows)} pnl={bj_pnl:+,.0f}")
out['part2_modes_raw'] = mode_tbl

sec('Part2b has_track 等象限静态 n 变化(展示层)')
quad_static = {}
for qk, qv in q.items():
    rows_a = qv.get('A') or []
    n_bj = sum(1 for r in rows_a if r[i_idx] == BJ)
    quad_static[qk] = {'n_per_card_before': len(rows_a), 'n_bj': n_bj,
                       'n_per_card_after': len(rows_a) - n_bj}
    if n_bj:
        print(f"{qk}: {len(rows_a)} → {len(rows_a)-n_bj} (每卡, -{n_bj})")
out['part2_quadrant_static'] = quad_static

# ---------- Part6 NEW14 默认组合 ----------
sec('Part6 AI宏观过滤默认组合(NEW14) 前/后')
rules = dict(M27.__dict__.get('_rules_cache', {})) if False else None
from mine21_bigtour import build_rules
from mine22_joint import build_r2
from sim_core import passes_fade, active_month_mask, DEFAULT_FILTERS
FEATS_PATH2 = os.path.join(MINE, 'data', 'mine10_features.json')
M24CMP = json.load(open(os.path.join(MINE, 'data', 'mine24_compare.json')))
NEW14_KEYS = list(M24CMP['new_keys'])
feats = json.load(open(FEATS_PATH2))
rls = build_rules(feats, fIdx)
rls.update(build_r2(fIdx))

poolA = finish_pool(build_mode_pool(tr, fIdx, 'A'), fIdx)
R.init(poolA, fIdx)
blk14 = hits_on(poolA, fIdx, NEW14_KEYS, rls)
sel14 = ev_new_on(poolA, fIdx, blk14)
st14 = R.stats_of(sel14); dd14 = dd_of(*_curve(sel14, fIdx))
assert abs(st14['total'] - 122648.33) < 1.0 and abs(dd14['mdd'] - (-4178.01)) < 1.5, (st14, dd14)
print(f"锚点 PASS: NEW14 基线 total={st14['total']:,.2f} mdd={dd14['mdd']:,.2f}")

poolA_p = [t for t in poolA if t[i_idx] != BJ]
R.init(poolA_p, fIdx)
sel14p = ev_new_on(poolA_p, fIdx, blk14)
st14p = R.stats_of(sel14p); dd14p = dd_of(*_curve(sel14p, fIdx))
det14 = R.diff_detail(sel14, sel14p)
bj_kept = [t for t in sel14 if t[i_idx] == BJ]
print(f"NEW14 剪枝后 total={st14p['total']:,.2f} mdd={dd14p['mdd']:,.2f} "
      f"(Δ {st14p['total']-st14['total']:+,.2f})")
print(f"基线中 bj50 入选笔数={len(bj_kept)} pnl={sum(t[R.IDX_PNL]['pnlYuan'] for t in bj_kept):+,.2f}")
print(f"补位分解: 被剔 n={det14['blocked_n']} pnl={det14['blocked_pnl']:+,.2f} | "
      f"替补 n={det14['added_n']} pnl={det14['added_pnl']:+,.2f} | 净改善={det14['net_improve']:+,.2f}")

# P0 八键对照档
poolP0, fia = R.prepare_rows()
R.init(poolP0, fIdx)
P0 = [t for t in poolP0]   # prepare_rows 已含八键 passes_fade; P0 选择=K1
P0sel = ev_new_on(sorted(P0, key=lambda t: str(t[0])), fia, set())
stP0 = R.stats_of(P0sel)
assert abs(stP0['total'] - 66530.38) < 0.5, stP0
print(f"锚点 PASS: P0 八键对照 total={stP0['total']:,.2f}")
P0p = [t for t in P0 if t[fia['index_id']] != BJ]
R.init(P0p, fia)
P0psel = ev_new_on(P0p, fia, set())
stP0p = R.stats_of(P0psel)
print(f"P0 剪枝后 total={stP0p['total']:,.2f} (Δ {stP0p['total']-stP0['total']:+,.2f})")

out['part6_ai_macro_default'] = {
    'caliber': 'v1.1.5 NEW14 十四键默认(common.js _KELLY_FADE_DEFAULT_MODE), mode A 池, K1 补位, 费后',
    'anchor_check': {'expected_total': 122648.33, 'actual_total': st14['total'],
                     'expected_mdd': -4178.01, 'actual_mdd': dd14['mdd']},
    'baseline': {**st14, 'mdd': round(dd14['mdd'], 2)},
    'pruned': {**st14p, 'mdd': round(dd14p['mdd'], 2)},
    'delta_total': round(st14p['total'] - st14['total'], 2),
    'bj_in_baseline_selection': {'n': len(bj_kept),
                                 'pnl': round(sum(t[R.IDX_PNL]['pnlYuan'] for t in bj_kept), 2)},
    'fill_decomposition': det14,
    'p0_reference': {'baseline_total': stP0['total'], 'pruned_total': stP0p['total'],
                     'delta': round(stP0p['total'] - stP0['total'], 2)},
}

# ---------- Part5 按年分解 ----------
sec('Part5 按年分解(mode A 池, RAW 与 NEW14 双口径)')
def yearly(sel):
    d = collections.defaultdict(float)
    n = collections.Counter()
    for t in sel:
        d[str(t[0])[:4]] += t[R.IDX_PNL]['pnlYuan']
        n[str(t[0])[:4]] += 1
    return {y: {'pnl': round(v, 2), 'n': n[y]} for y, v in sorted(d.items())}

R.init(poolA, fIdx)
raw_base_y = yearly(ev_new_on(poolA, fIdx, set()))
R.init(poolA_p, fIdx)
raw_prune_y = yearly(ev_new_on(poolA_p, fIdx, set()))
R.init(poolA, fIdx)
n14_base_y = yearly(sel14)
n14_prune_y = yearly(sel14p)
bj_year = yearly([t for t in poolA if t[i_idx] == BJ])
years = sorted(set(raw_base_y) | set(raw_prune_y))
print("年 | RAW基线 | RAW剪枝后 | Δ | bj50自身pnl | NEW14基线 | NEW14剪枝后")
tbl = {}
for y in years:
    rb = raw_base_y.get(y, {'pnl': 0, 'n': 0}); rp = raw_prune_y.get(y, {'pnl': 0, 'n': 0})
    nb = n14_base_y.get(y, {'pnl': 0, 'n': 0}); np_ = n14_prune_y.get(y, {'pnl': 0, 'n': 0})
    bjy = bj_year.get(y, {'pnl': 0, 'n': 0})
    tbl[y] = {'raw_base': rb, 'raw_pruned': rp, 'new14_base': nb, 'new14_pruned': np_, 'bj50_alone': bjy}
    print(f"{y} | {rb['pnl']:+,.0f}(n={rb['n']}) | {rp['pnl']:+,.0f}(n={rp['n']}) | "
          f"{rp['pnl']-rb['pnl']:+,.0f} | {bjy['pnl']:+,.0f}(n={bjy['n']}) | {nb['pnl']:+,.0f} | {np_['pnl']:+,.0f}")
out['part5_yearly'] = tbl

# ---------- Part3 被剔样本画像 + 诚实标注 ----------
sec('Part3 被剔样本自身画像')
a_row = out['part2_modes_raw']['A']
share_note = {
    a_row['bj_in_pool']['n'],
}
bjp = a_row['bj_in_pool']
raw_total_a = out['part2_modes_raw']['A']['base']['total']
ratio = abs(bjp['pnl']) / abs(raw_total_a) * 100 if raw_total_a else None
print(f"被剔样本(mode A 池口径): n={bjp['n']} 总pnl={bjp['pnl']:+,.2f} 胜率={bjp['winrate_pct']}% "
      f"均持仓={bjp['avg_hold_days']}天 | 占RAW全史净利|比|={ratio:.2f}%")
honest = ('诚实标注: 若剔除后指标变好(净利上升/胜率上升), 该改善 ≠ 剪枝正确。'
          '判断标准是口径正确性(map 空数组=无正式收录→本不应有可交易标的), 而非回测数字变好;'
          '反之若某年变差也不构成保留兜底的理由。本表只量化影响面大小。')
print(honest)
out['part3_removed_sample'] = {
    'mode_A_pool': bjp, 'pct_of_raw_total_abs': round(ratio, 2) if ratio else None,
    'per_mode_bj_pnl': bj_share, 'honest_note': honest,
}

json.dump(out, open(OUT_JSON, 'w'), ensure_ascii=False, indent=1)
print(f"\n已落盘: {os.path.normpath(OUT_JSON)}")
