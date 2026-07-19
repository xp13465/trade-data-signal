#!/usr/bin/env python3
"""策略实验室二次测试(回测切片) - 生成分年/样本外/极端行情回测结果

复用 lab_simulate.py 的信号生成 + 回测引擎,对⭐️综合分候选进行切片分析:
1. 分年回测:自然年(2016-2026)独立统计
2. 样本外:前70%训练(不动参数)/后30%测试回测
3. 极端行情:4个regime(股灾2015/熊市2018/疫情2020/反弹2024)

输出格式约定(lab.js:2208 注释 "ret/dd/win 为小数(0.xxxx)"):
  ret/win/dd 均为小数(0.xxxx),前端显示时 ×100 加 %
  null 用于无数据段
  pair_meta 含 strategy/window/score/n/dd/win

输出:
  static-site/data/lab/lab_retest_{iid}.json
"""
import json
import math
import os
import sys
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

# 复用 lab_simulate 的模块
BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(BASE, 'a-stock-data'))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from backtest_strategies import gen_buy_signals, gen_sell_signals
from fusion_signals import gen_fusion_candidates, gen_hardcoded_fusion_candidates
from lab_simulate import (
    load_index_data, _fmt_date, _days_between,
    simulate_full_in, simulate_fixed_10k, _build_stats,
    INITIAL_CAPITAL, SIM_INDEXES, BUY_KEYS, SELL_KEYS
)

# 极端行情regime定义 (start, end, key)
REGIMES = [
    ('2015-06-15', '2016-02-29', 'crash2015'),  # 股灾
    ('2018-01-29', '2019-01-04', 'bear2018'),   # 熊市
    ('2020-01-14', '2020-04-28', 'covid2020'),  # 疫情
    ('2024-01-22', '2024-09-30', 'rally2024'),  # 反弹
]


def _calc_risk_adj(annual_ret: float, max_drawdown: float) -> float:
    """计算风险调整收益(类Calmar) = annual_ret / max(max_drawdown, 2.0)。
    与 lab.js risk_adj 一致:分母 floor 2.0%(回撤极小时保守视作2%),消除原 999/-999
    哨兵(原哨兵使 min-max 归一化与 risk_adj≥门槛判定失真:微回撤+正年化恒给999必过门槛)。
    annual_ret/max_drawdown 均为百分数(20.0=20%)。"""
    return annual_ret / max(max_drawdown, 2.0)


def _winsorize(vals: List[float], lo: float = 0.01, hi: float = 0.99) -> List[float]:
    """截断前后1%极端值(P1-2抗离群点:实测SH有-88%收益/dd91%等极端拉偏min-max)。
    返回与vals等长的clamped列表;<4个样本时quantile不稳,原样返回。"""
    if len(vals) < 4:
        return list(vals)
    s = pd.Series(vals)
    lo_v, hi_v = float(s.quantile(lo)), float(s.quantile(hi))
    return [min(max(v, lo_v), hi_v) for v in vals]


def _compute_window_stats(df, buy_mask, sell_mask, first_date, last_date, window_years, sim_func=simulate_full_in):
    """计算滚动窗口的回测统计,返回stats dict(百分比单位)。
    window_years: 窗口年数(5=y5, 3=y3, 1=y1),从last_date往前截取
    sim_func: simulate_full_in(全仓复利) 或 simulate_fixed_10k(定额1万)
    实现:用w_start参数让simulate仅在该窗口内跑(非截取equity_curve),
    保证trades/equity_curve/stats三者在同一窗口内自洽"""
    w_start = last_date - pd.DateOffset(years=window_years)
    if w_start < first_date:
        w_start = first_date
    result = sim_func(df, buy_mask, sell_mask, w_start=w_start)
    years = _days_between(w_start, last_date) / 365.25
    return _build_stats(
        result['trades'], result['final_total'], last_date,
        result['equity_curve'], years=years
    )


def _normalize_and_score(all_stats: List[Dict[str, Any]]) -> List[float]:
    """对全部候选的y5统计做 winsorize+min-max 归一化后算综合分。
    与 lab.js _labRankAggregate score 公式一致(P1-1/P1-2/P2-1):
      score = 0.35*nRet + 0.25*nWin + 0.15*nDd + 0.15*nRisk + 0.1*nConcaveN
    - nRet/nWin/nDd/nRisk: winsorize(前后1%截断)后 min-max 归一化到[0,1](P1-2抗极端值)
    - nDd 用 -max_drawdown 归一化(回撤越小分越高)
    - nRisk = risk_adj(annual_ret/max(dd,2.0)) 作第5因子(P1-1,原4因子无risk_adj)
    - nConcaveN = 1-exp(-n/30) 凹函数替代线性(P2-1:边际递减,30笔0.63/60笔0.87,
      抗大样本线性通胀;非cohort归一,绝对变换,权重0.1小故影响有限)
    返回与 all_stats 等长的 score 列表(0-1)。
    """
    if not all_stats:
        return []

    rets = [s.get('total_ret', 0) for s in all_stats]
    wins = [s.get('win_rate', 0) for s in all_stats]
    dds = [s.get('max_drawdown', 0) for s in all_stats]
    ns = [s.get('n_trades', 0) for s in all_stats]
    annuals = [s.get('annual_ret', 0) for s in all_stats]
    risks = [_calc_risk_adj(a, d) for a, d in zip(annuals, dds)]

    def mm(vals):
        wv = _winsorize(vals)  # winsorize 后取 min/max(P1-2)
        mn, mx = min(wv), max(wv)
        if mx == mn:
            return [0.5] * len(vals)
        rng = mx - mn
        return [max(0.0, min(1.0, (v - mn) / rng)) for v in vals]

    n_rets = mm(rets)
    n_wins = mm(wins)
    n_dds = mm([-d for d in dds])  # -dd: 回撤越小值越大
    n_risks = mm(risks)
    n_ns = [1 - math.exp(-n / 30) for n in ns]  # 凹函数(P2-1)

    scores = []
    for i in range(len(all_stats)):
        s = (0.35 * n_rets[i] + 0.25 * n_wins[i] + 0.15 * n_dds[i]
             + 0.15 * n_risks[i] + 0.1 * n_ns[i])
        scores.append(s)
    return scores


def _is_star_candidate(score, windows):
    """判断是否为⭐️综合分候选(P1-3 收紧:多窗口dd稳健门 + AND质量门):
    y5_dd<=10% && y3_dd<=10% && y1_dd<=10% && n>=10  (基础稳健+样本下限门,不变)
    且 score>=0.6 && win>=55 && risk_adj>=1.5          (AND质量门,原OR三分支收紧为AND)
    说明:原 OR=(score>=0.6&&n>=30)||win>=55||risk_adj>=1.0 放入42个含大量弱候选
    (低score仅靠win>=55单分支混入)。收紧为AND后仅保留score/win/risk三者皆强的候选。
    n>=30 不纳入质量门(5年窗口交易数普遍10-27,n>=30仅2/42可达,数据不可行),
    保留原 n>=10 作样本下限。risk_adj门槛 1.0->1.5(任务硬性要求)。
    score/n/dd/win/risk_adj 取 y5 全仓(百分比单位:dd=10表10%)
    windows: {y5:stats, y3:stats, y1:stats} 各为_build_stats返回的dict
    """
    y5 = windows.get('y5') or {}
    n = y5.get('n_trades', 0)
    dd = y5.get('max_drawdown', 999)
    win = y5.get('win_rate', 0)
    annual_ret = y5.get('annual_ret', 0)
    risk_adj = _calc_risk_adj(annual_ret, dd)
    y3 = windows.get('y3') or {}
    y1 = windows.get('y1') or {}
    y3_dd = y3.get('max_drawdown', 999)
    y1_dd = y1.get('max_drawdown', 999)
    dd_ok = dd <= 10 and y3_dd <= 10 and y1_dd <= 10
    n_ok = n >= 10
    quality = (score >= 0.6) and (win >= 55) and (risk_adj >= 1.5)
    return dd_ok and n_ok and quality


def _slice_by_date_range(df, start_str, end_str):
    """按日期范围切片DataFrame"""
    mask = (df.index >= start_str) & (df.index <= end_str)
    return df[mask].copy()


def _slice_buy_sell_masks(buy_mask, sell_mask, df_slice, original_df):
    """按df_slice的日期范围切片买卖信号,索引与df_slice对齐"""
    start_date = df_slice.index[0]
    end_date = df_slice.index[-1]
    sliced_buy = buy_mask.loc[start_date:end_date].copy()
    sliced_sell = sell_mask.loc[start_date:end_date].copy()
    sliced_buy = sliced_buy.reindex(df_slice.index, fill_value=False)
    sliced_sell = sliced_sell.reindex(df_slice.index, fill_value=False)
    return sliced_buy, sliced_sell


def _calc_slice_stats(df, buy_mask, sell_mask, sim_func=simulate_full_in):
    """在切片范围内计算回测统计,返回stats dict或None。
    sim_func: simulate_full_in 或 simulate_fixed_10k"""
    result = sim_func(df, buy_mask, sell_mask)
    trades = result['trades']
    if not trades:
        return None
    first_date = df.index[0]
    last_date = df.index[-1]
    years = _days_between(first_date, last_date) / 365.25
    return _build_stats(
        trades, result['final_total'], last_date,
        result['equity_curve'], years=years
    )


def _fmt_stats_decimal(stats):
    """格式化统计为输出格式:ret/win/dd 均为小数(0.xxxx),n为整数。
    无交易时返回 {ret:null,win:null,dd:null,n:0}"""
    if stats is None:
        return {'ret': None, 'win': None, 'dd': None, 'n': 0}
    return {
        'ret': round(stats.get('total_ret', 0) / 100, 4),
        'win': round(stats.get('win_rate', 0) / 100, 4),
        'dd': round(stats.get('max_drawdown', 0) / 100, 4),
        'n': stats.get('n_trades', 0)
    }


def _fmt_window_stats(stats, score):
    """格式化窗口统计为输出格式(与pair_meta top-level一致:小数单位)。
    用于 pair_meta.windows.{y5,y3,y1},含score(归一化综合分,基于y5)。"""
    if stats is None or not stats:
        return {'ret': None, 'win': None, 'dd': None, 'n': 0, 'score': round(score, 2)}
    return {
        'ret': round(stats.get('total_ret', 0) / 100, 4),
        'win': round(stats.get('win_rate', 0) / 100, 4),
        'dd': round(stats.get('max_drawdown', 0) / 100, 4),
        'n': stats.get('n_trades', 0),
        'score': round(score, 2)
    }


def _run_yearly_retest(df, buy_mask, sell_mask, sim_func=simulate_full_in):
    """分年回测:自然年(2016-2026)独立统计"""
    result = {}
    for year in range(2016, 2027):
        df_slice = _slice_by_date_range(df, f'{year}-01-01', f'{year}-12-31')
        if len(df_slice) < 30:
            result[str(year)] = None
            continue
        sliced_buy, sliced_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_slice, df)
        stats = _calc_slice_stats(df_slice, sliced_buy, sliced_sell, sim_func)
        result[str(year)] = _fmt_stats_decimal(stats)
    return result


def _run_oos_retest(df, buy_mask, sell_mask, sim_func=simulate_full_in):
    """样本外回测:前70%训练/后30%测试"""
    total_len = len(df)
    split_idx = int(total_len * 0.7)
    if split_idx < 60 or (total_len - split_idx) < 30:
        return {'train': None, 'test': None}
    df_train = df.iloc[:split_idx].copy()
    train_buy, train_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_train, df)
    stats_train = _calc_slice_stats(df_train, train_buy, train_sell, sim_func)
    df_test = df.iloc[split_idx:].copy()
    test_buy, test_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_test, df)
    stats_test = _calc_slice_stats(df_test, test_buy, test_sell, sim_func)
    return {
        'train': _fmt_stats_decimal(stats_train),
        'test': _fmt_stats_decimal(stats_test)
    }


def _run_regime_retest(df, buy_mask, sell_mask, sim_func=simulate_full_in):
    """极端行情回测:4个regime独立统计,仅输出ret和dd(小数)"""
    result = {}
    for start_str, end_str, key in REGIMES:
        df_slice = _slice_by_date_range(df, start_str, end_str)
        if len(df_slice) < 10:
            result[key] = None
            continue
        sliced_buy, sliced_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_slice, df)
        stats = _calc_slice_stats(df_slice, sliced_buy, sliced_sell, sim_func)
        if stats is None:
            result[key] = None
        else:
            result[key] = {
                'ret': round(stats.get('total_ret', 0) / 100, 4),
                'dd': round(stats.get('max_drawdown', 0) / 100, 4)
            }
    return result


def run_retest_for_index(iid, iname):
    """单个指数的二次测试"""
    print(f'\n[retest] {iid} ({iname})')

    df = load_index_data(iid)
    if df is None:
        print(f'  ERROR:无法加载数据')
        return

    first_date = df.index[0]
    last_date = df.index[-1]
    print(f'  数据范围: {_fmt_date(first_date)} ~ {_fmt_date(last_date)} ({len(df)}天)')

    # 候选集与 lab_simulate 的 fusion_stats 完全对齐(145):91融合 + 6 F_硬编码 + 48 F_×partner
    # 补 F_硬编码 + partner 后,融合榜(F_+同向共振)才有候选进⭐️二次测试(原仅91无F_,0融合过⭐️)
    candidates = gen_fusion_candidates(df) + gen_hardcoded_fusion_candidates(df)
    # 6 硬编码 F_ × 8 反向 partner(48组):F_融合信号当主策略配反向单信号partner
    # pair_id: 买侧F_ -> "F_xxx|sell_partner"; 卖侧F_ -> "buy_partner|F_xxx"(与lab_simulate:780-828一致)
    buy_signals = gen_buy_signals(df)
    sell_signals = gen_sell_signals(df)
    hardcoded = [c for c in candidates if c['pair_type'].startswith('hardcoded')]
    for c in hardcoded:
        fkey = c['pair_id']
        side = 'buy' if c['pair_type'] == 'hardcoded_buy' else 'sell'
        if side == 'buy':
            fusion_mask = c['buy_mask']
            partners = SELL_KEYS
        else:
            fusion_mask = c['sell_mask']
            partners = BUY_KEYS
        if fusion_mask is None or fusion_mask.sum() == 0:
            continue
        for pkey in partners:
            if side == 'buy':
                bm = fusion_mask.fillna(False).astype(bool)
                sm_raw = sell_signals.get(pkey)
                if sm_raw is None:
                    continue
                sm = sm_raw.fillna(False).astype(bool)
                pid = f'{fkey}|{pkey}'
            else:
                bm_raw = buy_signals.get(pkey)
                if bm_raw is None:
                    continue
                bm = bm_raw.fillna(False).astype(bool)
                sm = fusion_mask.fillna(False).astype(bool)
                pid = f'{pkey}|{fkey}'
            if bm.sum() == 0 or sm.sum() == 0:
                continue
            candidates.append({
                'pair_id': pid,
                'pair_type': f'partner_{side}',
                'buy_mask': bm,
                'sell_mask': sm,
                'components': c['components'],
                'ref_side': c['ref_side'],
            })
    print(f'  融合候选: {len(candidates)}个(91融合+6 F_+{len(candidates)-97} partner)')

    # 两趟计算:
    # 第一趟:计算全部候选的y5/y3/y1三窗口统计 + score(归一化,score仍基于y5)
    all_windows = []
    for cand in candidates:
        if cand['buy_mask'] is None or cand['sell_mask'] is None:
            all_windows.append({})
            continue
        y5_stats = _compute_window_stats(df, cand['buy_mask'], cand['sell_mask'], first_date, last_date, 5)
        y3_stats = _compute_window_stats(df, cand['buy_mask'], cand['sell_mask'], first_date, last_date, 3)
        y1_stats = _compute_window_stats(df, cand['buy_mask'], cand['sell_mask'], first_date, last_date, 1)
        all_windows.append({'y5': y5_stats, 'y3': y3_stats, 'y1': y1_stats})

    scores = _normalize_and_score([w.get('y5', {}) for w in all_windows])

    # 第二趟:筛选⭐️候选,运行3种切片回测
    output = {
        'index_id': iid,
        'index_name': iname,
        'generated_at': _fmt_date(last_date),
        'pairs': {}
    }

    star_count = 0
    for i, cand in enumerate(candidates):
        pair_id = cand['pair_id']
        windows = all_windows[i]
        score = scores[i] if i < len(scores) else 0.0

        if not windows:
            continue
        if not _is_star_candidate(score, windows):
            continue

        star_count += 1
        buy_mask = cand['buy_mask']
        sell_mask = cand['sell_mask']
        y5_stats = windows['y5']

        # pair_meta: strategy=pk, window=y5, score=0.xx, n/dd/win/ret 均为小数
        # top-level 保持 full_in y5 (向后兼容:前端未改前读旧字段不报错)
        # windows: y5/y3/y1 三窗口统计(收紧进入判定用)
        pair_data = {
            'pair_meta': {
                'strategy': pair_id,
                'window': 'y5',
                'mode': 'full_in',
                'score': round(score, 2),
                'n': y5_stats.get('n_trades', 0),
                'dd': round(y5_stats.get('max_drawdown', 0) / 100, 4),
                'win': round(y5_stats.get('win_rate', 0) / 100, 4),
                'ret': round(y5_stats.get('total_ret', 0) / 100, 4),
                'windows': {
                    'y5': _fmt_window_stats(windows.get('y5'), score),
                    'y3': _fmt_window_stats(windows.get('y3'), score),
                    'y1': _fmt_window_stats(windows.get('y1'), score),
                }
            },
            'yearly': _run_yearly_retest(df, buy_mask, sell_mask, simulate_full_in),
            'oos': _run_oos_retest(df, buy_mask, sell_mask, simulate_full_in),
            'regimes': _run_regime_retest(df, buy_mask, sell_mask, simulate_full_in)
        }

        # fixed_10k 模式:定额1万(每次买1万最多10笔,卖信号清仓)
        # 与 full_in 同一对策略候选,仅仓位管理不同,用于横向对比
        fk_y5_stats = _compute_window_stats(
            df, buy_mask, sell_mask, first_date, last_date, 5, simulate_fixed_10k
        )
        pair_data['fixed_10k'] = {
            'pair_meta': {
                'strategy': pair_id,
                'window': 'y5',
                'mode': 'fixed_10k',
                'score': round(score, 2),
                'n': fk_y5_stats.get('n_trades', 0),
                'dd': round(fk_y5_stats.get('max_drawdown', 0) / 100, 4),
                'win': round(fk_y5_stats.get('win_rate', 0) / 100, 4),
                'ret': round(fk_y5_stats.get('total_ret', 0) / 100, 4)
            },
            'yearly': _run_yearly_retest(df, buy_mask, sell_mask, simulate_fixed_10k),
            'oos': _run_oos_retest(df, buy_mask, sell_mask, simulate_fixed_10k),
            'regimes': _run_regime_retest(df, buy_mask, sell_mask, simulate_fixed_10k)
        }
        output['pairs'][pair_id] = pair_data

    print(f'  ⭐️候选数: {star_count}')

    # 写入 static-site
    for base_dir in ('static-site',):
        out_path = os.path.join(BASE, base_dir, 'data', 'lab', f'lab_retest_{iid}.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = os.path.getsize(out_path) / 1024
        print(f'  [output] {out_path} ({size_kb:.1f} KB)')


def main():
    print('=== 策略实验室二次测试(回测切片) ===')
    total_start = pd.Timestamp.now()
    # 支持单指数测试: python3 lab_retest.py 0  (0=上证, 1=深证, ...)
    if len(sys.argv) > 1:
        idx = int(sys.argv[1])
        if 0 <= idx < len(SIM_INDEXES):
            iid, iname = SIM_INDEXES[idx]
            run_retest_for_index(iid, iname)
        else:
            print(f'ERROR: 索引 {idx} 超出范围(0-{len(SIM_INDEXES)-1})')
            sys.exit(1)
    else:
        for iid, iname in SIM_INDEXES:
            run_retest_for_index(iid, iname)
    elapsed = pd.Timestamp.now() - total_start
    print(f'\n=== 全部完成,总耗时 {elapsed.total_seconds():.1f}s ===')


if __name__ == '__main__':
    main()
