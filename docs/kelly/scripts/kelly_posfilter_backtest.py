# ============================================================
# 用途: 凯利仓位过滤回测共享依赖(被大量脚本 import)
# 日期/来源: 2026-08-12 / tmp
# 结论: 提供 base_signals/get_by_date/base_key 等基笔信号/按日分组/键构造工具
# 依赖: 无(被其他脚本 import)
# 输入/输出: 函数库; 基笔来自 signal_kelly_trades.json
# 复现: 无需直接运行, 被 strategyAB_compare.py / dailypool_rerun_core.py 等 import
# 注意: 原文件含硬编码绝对路径, 如需重跑请确认路径或改相对路径
# ============================================================
#!/usr/bin/env python3
"""回测: 单日重复信号过滤(仓位控制过滤)候选规则
主口径 = G模式(推荐卖出法) 7414去重基笔, 1万/笔
候选: P0基线 / P1每日top1(score) / P2每日top2 / P3每日top1(质量序) / P4质量过滤(无日上限)
叠加: COMBO4(4组合) / COMBO4+live4
复用 kelly_combo_advice_analysis.compute_stats
"""
import sys, json
from collections import defaultdict
sys.path.insert(0, '/tmp')
from kelly_combo_advice_analysis import (load, compute_stats, to_row, filter_trades,
    full_signal_trades, empty_filters, LIVE4, COMBO_ALL, BUY_AMOUNT, fIdx)

d = load(); quads = d['quadrants']
ALL_MODES = ['A','B','C','D','E','F','G','H','I']

def base_key(t):
    return '|'.join([str(t[fIdx['signal_date']]), str(t[fIdx['index_id']]), str(t[fIdx['signal']]),
                     str(t[fIdx['buy_date']]), str(t[fIdx['etf_code']])])

# COMBO4 = 4组合(不含live4)
COMBO4 = {k: False for k in LIVE4}
for k in ['n2NovSpecialIndustry','n3NovSpecialMon','v4d','r8PureNonMay','greedy15','janMidRating','janMidSpecial']:
    COMBO4[k] = True

# ---- 候选规则 ----
def quality_priority():
    # 基于挖掘: signal类型胜率序 buy_backup>buy>buy_aux>buy_special
    return {'buy_backup': 0, 'buy': 1, 'buy_aux': 2, 'buy_special': 3, '': 9}

QUAL_RANK = quality_priority()
RATING_RANK = {'high': 0, 'mid': 1, 'low': 2, '': 3}

def sort_key(t):
    """选优排序: quality(类型) -> rating -> score desc"""
    sig = str(t[fIdx['signal']] or '')
    rat = str(t[fIdx['rating']] or '')
    sc = t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    return (QUAL_RANK.get(sig, 9), RATING_RANK.get(rat, 3), -sc)

def sort_key_score(t):
    sc = t[fIdx['track_score']] if t[fIdx['track_score']] is not None else -1
    rat = str(t[fIdx['rating']] or '')
    return (-sc, RATING_RANK.get(rat, 3))

def apply_rule(base_by_date, rule):
    """返回保留的基笔集合. rule: ('topK', k, keyf) / ('quality', min_rank)"""
    kept = []
    kind = rule[0]
    if kind == 'topK':
        _, k, keyf = rule
        for sd, rows in base_by_date.items():
            srt = sorted(rows, key=keyf)
            kept.extend(srt[:k])
    elif kind == 'quality':
        _, max_rank = rule
        for sd, rows in base_by_date.items():
            for r in rows:
                if QUAL_RANK.get(str(r[fIdx['signal']] or ''), 9) <= max_rank:
                    kept.append(r)
    return kept

# 收集各模式全部基笔 (去重)
def base_signals(mode):
    seen = {}
    for qk in ['rating_high','rating_mid','rating_low']:
        for t in quads[qk][mode]:
            k = base_key(t)
            if k not in seen:
                seen[k] = t
    return list(seen.values())

by_date_cache = {}
def get_by_date(mode):
    if mode not in by_date_cache:
        bd = defaultdict(list)
        for t in base_signals(mode):
            bd[str(t[fIdx['signal_date']])].append(t)
        by_date_cache[mode] = bd
    return by_date_cache[mode]

RULES = {
    'P0_基线': ('topK', 9999, sort_key),
    'P1_每日top1(score)': ('topK', 1, sort_key_score),
    'P2_每日top2(score)': ('topK', 2, sort_key_score),
    'P3_每日top1(质量序)': ('topK', 1, sort_key),
    'P4_质量过滤(仅buy/backup)': ('quality', 1),
}

def run_frame(mode, rule, extra_filter=None):
    base = base_signals(mode)
    if rule is not None:
        kept = apply_rule(get_by_date(mode), RULES[rule])
        kept_keys = set(base_key(t) for t in kept)
        rows = [to_row(t) for t in base if base_key(t) in kept_keys]
    else:
        rows = [to_row(t) for t in base]
    if extra_filter is not None:
        # extra_filter 在基笔上应用 (passes_fade)
        ft = [t for t in base if passes_filter(base_by_key(t), extra_filter)]
        fk = set(base_key(t) for t in ft)
        rows = [r for r, t in zip(rows, base) if base_key(t) in fk]
    return compute_stats(rows, 'all', BUY_AMOUNT)

# passes_fade 需要原行数组, 从 base_signals 拿
base_by_key = {}
for m in ALL_MODES:
    for t in base_signals(m):
        base_by_key.setdefault(base_key(t), t)
def passes_filter(t, F):
    from kelly_combo_advice_analysis import passes_fade
    return passes_fade(t, F)

if __name__ == '__main__':
    mode = 'G'
    print('=== 主口径: %s模式, 去重基笔 %d, 1万/笔 ===' % (mode, len(base_signals(mode))))
    print('%-22s %6s %12s %7s %7s %7s %8s %7s %9s %9s' % ('规则', 'n', '净盈亏', '胜率%', '盈亏比', '年化%', '最大持仓', '收益率%', '回撤%', '半凯利%'))
    results = {}
    for name in RULES:
        s = run_frame(mode, name)
        results[name] = s
        print('%-22s %6d %12s %6.1f %7s %6.2f %8d %8.2f %8.2f %9.2f' % (
            name, s['n'], format(s['total_profit'], ','), s['win_rate'], 
            s['pl_ratio'] if s['pl_ratio'] is not None else '-', s['annualized_return'],
            s['max_concurrent'], s['return_pct_max_holding'], s['max_drawdown_pct'], s['half_kelly']))
    print('\n(收益率=净盈亏/峰值持仓资本; 回撤为净额占总投资比例)')

    print('\n=== 叠加边际 (G模式): 候选规则 + COMBO4(4组合) / +live4 ===')
    print('%-22s %6s %12s %7s %7s %8s %7s' % ('场景', 'n', '净盈亏', '胜率%', '盈亏比', '最大持仓', '收益率%'))
    base_all = base_signals(mode)
    # 组合过滤在基笔上
    for name in ['P0_基线', 'P1_每日top1(score)', 'P3_每日top1(质量序)']:
        rule = RULES[name]
        kept = apply_rule(get_by_date(mode), rule)
        kk = set(base_key(t) for t in kept)
        # standalone (rule only)
        rows = [to_row(t) for t in base_all if base_key(t) in kk]
        s = compute_stats(rows, 'all', BUY_AMOUNT)
        print('%-22s %6d %12s %6.1f %7s %8d %7.2f' % (name, s['n'], format(s['total_profit'],','), s['win_rate'], s['pl_ratio'] if s['pl_ratio'] else '-', s['max_concurrent'], s['return_pct_max_holding']))
        # rule + COMBO4
        rows2 = [to_row(t) for t in base_all if base_key(t) in kk and passes_filter(t, COMBO4)]
        s2 = compute_stats(rows2, 'all', BUY_AMOUNT)
        print('  +COMBO4    %6d %12s %6.1f %7s %8d %7.2f' % (s2['n'], format(s2['total_profit'],','), s2['win_rate'], s2['pl_ratio'] if s2['pl_ratio'] else '-', s2['max_concurrent'], s2['return_pct_max_holding']))
        # rule + COMBO4 + live4
        rows3 = [to_row(t) for t in base_all if base_key(t) in kk and passes_filter(t, COMBO4) and passes_filter(t, LIVE4)]
        s3 = compute_stats(rows3, 'all', BUY_AMOUNT)
        print('  +COMBO4+live4 %4d %12s %6.1f %7s %8d %7.2f' % (s3['n'], format(s3['total_profit'],','), s3['win_rate'], s3['pl_ratio'] if s3['pl_ratio'] else '-', s3['max_concurrent'], s3['return_pct_max_holding']))

    print('\n=== COMBO4 单独 (无仓位过滤, 参考) ===')
    rows = [to_row(t) for t in base_all if passes_filter(t, COMBO4)]
    s = compute_stats(rows, 'all', BUY_AMOUNT)
    print('%-22s %6d %12s %6.1f %7s %8d %7.2f' % ('COMBO4', s['n'], format(s['total_profit'],','), s['win_rate'], s['pl_ratio'] if s['pl_ratio'] else '-', s['max_concurrent'], s['return_pct_max_holding']))
    rows = [to_row(t) for t in base_all if passes_filter(t, COMBO4) and passes_filter(t, LIVE4)]
    s = compute_stats(rows, 'all', BUY_AMOUNT)
    print('%-22s %6d %12s %6.1f %7s %8d %7.2f' % ('COMBO4+live4', s['n'], format(s['total_profit'],','), s['win_rate'], s['pl_ratio'] if s['pl_ratio'] else '-', s['max_concurrent'], s['return_pct_max_holding']))
