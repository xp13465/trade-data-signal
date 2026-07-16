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
  web/data/lab/lab_retest_{iid}.json
  static-site/data/lab/lab_retest_{iid}.json
"""
import json
import os
import sys
from typing import Dict, List, Any, Optional, Tuple

import pandas as pd

# 复用 lab_simulate 的模块
BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(BASE, 'a-stock-data'))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from backtest_strategies import gen_buy_signals, gen_sell_signals
from fusion_signals import gen_fusion_candidates
from lab_simulate import (
    load_index_data, _fmt_date, _days_between,
    simulate_full_in, simulate_fixed_10k, _build_stats,
    INITIAL_CAPITAL, SIM_INDEXES
)

# 极端行情regime定义 (start, end, key)
REGIMES = [
    ('2015-06-15', '2016-02-29', 'crash2015'),  # 股灾
    ('2018-01-29', '2019-01-04', 'bear2018'),   # 熊市
    ('2020-01-14', '2020-04-28', 'covid2020'),  # 疫情
    ('2024-01-22', '2024-09-30', 'rally2024'),  # 反弹
]


def _calc_risk_adj(annual_ret: float, max_drawdown: float) -> float:
    """计算风险调整收益(类Calmar) = annual_ret / max_drawdown。
    与 lab.js:2120 一致: dd>0.5% 时用比值,否则年化为正给999,为负给-999。"""
    if max_drawdown > 0.5:
        return annual_ret / max_drawdown
    return 999.0 if annual_ret > 0 else -999.0


def _compute_y5_stats(df, buy_mask, sell_mask, first_date, last_date, sim_func=simulate_full_in):
    """计算y5窗口的回测统计,返回stats dict(百分比单位)。
    sim_func: simulate_full_in(全仓复利) 或 simulate_fixed_10k(定额1万)"""
    y5_start = last_date - pd.DateOffset(years=5)
    if y5_start < first_date:
        y5_start = first_date
    y5_result = sim_func(df, buy_mask, sell_mask, w_start=y5_start)
    y5_years = _days_between(y5_start, last_date) / 365.25
    return _build_stats(
        y5_result['trades'], y5_result['final_total'], last_date,
        y5_result['equity_curve'], years=y5_years
    )


def _normalize_and_score(all_stats: List[Dict[str, Any]]) -> List[float]:
    """对全部候选的y5统计做min-max归一化后算综合分。
    与 lab.js:2125-2136 一致:
      score = 0.4*nRet + 0.3*nWin + 0.2*nDd + 0.1*nN
      nDd 用 -max_drawdown 归一化(回撤越小分越高)
    返回与 all_stats 等长的 score 列表(0-1)。
    """
    if not all_stats:
        return []

    rets = [s.get('total_ret', 0) for s in all_stats]
    wins = [s.get('win_rate', 0) for s in all_stats]
    dds = [s.get('max_drawdown', 0) for s in all_stats]
    ns = [s.get('n_trades', 0) for s in all_stats]

    def mm(vals):
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return [0.5] * len(vals)
        return [(v - mn) / (mx - mn) for v in vals]

    n_rets = mm(rets)
    n_wins = mm(wins)
    n_dds = mm([-d for d in dds])  # -dd: 回撤越小值越大
    n_ns = mm(ns)

    scores = []
    for i in range(len(all_stats)):
        s = 0.4 * n_rets[i] + 0.3 * n_wins[i] + 0.2 * n_dds[i] + 0.1 * n_ns[i]
        scores.append(s)
    return scores


def _is_star_candidate(score, stats_y5):
    """判断是否为⭐️综合分候选(与 lab.js:2138 一致):
    (score>=0.6 && n>=30 && dd<=50) || win>=55 || risk_adj>=1.0
    此处 score/n/dd/win/risk_adj 均用百分比单位(stats原始值)
    """
    n = stats_y5.get('n_trades', 0)
    dd = stats_y5.get('max_drawdown', 999)
    win = stats_y5.get('win_rate', 0)
    annual_ret = stats_y5.get('annual_ret', 0)
    risk_adj = _calc_risk_adj(annual_ret, dd)
    return (score >= 0.6 and n >= 30 and dd <= 50) or (win >= 55) or (risk_adj >= 1.0)


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

    candidates = gen_fusion_candidates(df)
    print(f'  融合候选: {len(candidates)}个')

    # 两趟计算:
    # 第一趟:计算全部候选的y5统计 + score(归一化)
    all_y5_stats = []
    for cand in candidates:
        if cand['buy_mask'] is None or cand['sell_mask'] is None:
            all_y5_stats.append({})
            continue
        stats = _compute_y5_stats(df, cand['buy_mask'], cand['sell_mask'], first_date, last_date)
        all_y5_stats.append(stats)

    scores = _normalize_and_score(all_y5_stats)

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
        y5_stats = all_y5_stats[i]
        score = scores[i] if i < len(scores) else 0.0

        if not y5_stats:
            continue
        if not _is_star_candidate(score, y5_stats):
            continue

        star_count += 1
        buy_mask = cand['buy_mask']
        sell_mask = cand['sell_mask']

        # pair_meta: strategy=pk, window=y5, score=0.xx, n/dd/win/ret 均为小数
        # top-level 保持 full_in (向后兼容:前端未改前读旧字段不报错)
        pair_data = {
            'pair_meta': {
                'strategy': pair_id,
                'window': 'y5',
                'mode': 'full_in',
                'score': round(score, 2),
                'n': y5_stats.get('n_trades', 0),
                'dd': round(y5_stats.get('max_drawdown', 0) / 100, 4),
                'win': round(y5_stats.get('win_rate', 0) / 100, 4),
                'ret': round(y5_stats.get('total_ret', 0) / 100, 4)
            },
            'yearly': _run_yearly_retest(df, buy_mask, sell_mask, simulate_full_in),
            'oos': _run_oos_retest(df, buy_mask, sell_mask, simulate_full_in),
            'regimes': _run_regime_retest(df, buy_mask, sell_mask, simulate_full_in)
        }

        # fixed_10k 模式:定额1万(每次买1万最多10笔,卖信号清仓)
        # 与 full_in 同一对策略候选,仅仓位管理不同,用于横向对比
        fk_y5_stats = _compute_y5_stats(
            df, buy_mask, sell_mask, first_date, last_date, simulate_fixed_10k
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

    # 写入双版
    for base_dir in ('web', 'static-site'):
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
