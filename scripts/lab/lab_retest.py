#!/usr/bin/env python3
"""策略实验室二次测试(回测切片) - 生成分年/样本外/极端行情回测结果

复用 lab_simulate.py 的信号生成 + 回测引擎,对⭐️综合分候选进行切片分析:
1. 分年回测:自然年(2016-2026)独立统计
2. 样本外:前70%训练(不动参数)/后30%测试回测
3. 极端行情:4个regime(股灾2015/熊市2018/疫情2020/反弹2024)

输出:
  web/data/lab/lab_retest_{iid}.json
  static-site/data/lab/lab_retest_{iid}.json
"""
import bisect
import json
import os
import sys
from datetime import datetime
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

# 回测指数列表 (仅包含有融合数据的指数)
RETEST_INDEXES = SIM_INDEXES


def _calc_risk_adj(stats: Dict[str, Any]) -> float:
    """计算风险调整收益 = total_ret / (max_drawdown + 10)"""
    ret = stats.get('total_ret', 0)
    dd = stats.get('max_drawdown', 0)
    if dd <= 0:
        return 999.0
    return ret / dd


def _is_star_candidate(stats_y5: Dict[str, Any]) -> bool:
    """判断是否为⭐️综合分候选(仅用y5窗口筛选):
    score>=0.6 && n>=30 && dd<=50 或 win>=55 或 risk_adj>=1.0
    (score计算:40%ret + 30%win + 20%dd + 10%n,此处简化判断条件)
    """
    n = stats_y5.get('n_trades', 0)
    dd = stats_y5.get('max_drawdown', 999)
    win = stats_y5.get('win_rate', 0)
    risk_adj = _calc_risk_adj(stats_y5)
    # 简化版:只要满足基本条件即可
    return (n >= 30 and dd <= 50) or (win >= 55) or (risk_adj >= 1.0)


def _slice_by_date_range(df: pd.DataFrame, start_str: str, end_str: str) -> pd.DataFrame:
    """按日期范围切片DataFrame"""
    mask = (df.index >= start_str) & (df.index <= end_str)
    return df[mask].copy()


def _slice_buy_sell_masks(
    buy_mask: pd.Series, sell_mask: pd.Series, df_slice: pd.DataFrame,
    original_df: pd.DataFrame
) -> Tuple[pd.Series, pd.Series]:
    """按df_slice的日期范围切片买卖信号,索引与df_slice对齐"""
    # 获取切片的日期范围
    start_date = df_slice.index[0]
    end_date = df_slice.index[-1]

    # 在原始mask中找到对应范围
    sliced_buy = buy_mask.loc[start_date:end_date].copy()
    sliced_sell = sell_mask.loc[start_date:end_date].copy()

    # 确保索引与df_slice一致
    sliced_buy = sliced_buy.reindex(df_slice.index, fill_value=False)
    sliced_sell = sliced_sell.reindex(df_slice.index, fill_value=False)

    return sliced_buy, sliced_sell


def _calc_slice_stats(
    df: pd.DataFrame, buy_mask: pd.Series, sell_mask: pd.Series,
    mode: str = 'full_in'
) -> Optional[Dict[str, Any]]:
    """在切片范围内计算回测统计(复用simulate函数)"""
    if mode == 'full_in':
        result = simulate_full_in(df, buy_mask, sell_mask)
    else:
        result = simulate_fixed_10k(df, buy_mask, sell_mask)

    trades = result['trades']
    if not trades:
        return None

    # 计算统计(使用实际交易日范围)
    first_date = df.index[0]
    last_date = df.index[-1]
    years = _days_between(first_date, last_date) / 365.25

    stats = _build_stats(
        trades, result['final_total'], last_date,
        result['equity_curve'], years=years
    )
    return stats


def _fmt_stats_for_output(stats: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """格式化统计为输出格式(ret保留4位,win保留2位,dd保留2位)"""
    if stats is None:
        return None
    return {
        'ret': round(stats.get('total_ret', 0) / 100, 4) if stats.get('total_ret') is not None else None,
        'win': round(stats.get('win_rate', 0), 2) if stats.get('win_rate') is not None else None,
        'dd': round(stats.get('max_drawdown', 0), 2) if stats.get('max_drawdown') is not None else None,
        'n': stats.get('n_trades', 0)
    }


def _run_yearly_retest(
    df: pd.DataFrame, buy_mask: pd.Series, sell_mask: pd.Series,
    mode: str = 'full_in'
) -> Dict[str, Optional[Dict[str, Any]]]:
    """分年回测:自然年(2016-2026)独立统计"""
    result = {}
    years = list(range(2016, 2027))

    for year in years:
        start_str = f'{year}-01-01'
        end_str = f'{year}-12-31'
        df_slice = _slice_by_date_range(df, start_str, end_str)
        if len(df_slice) < 30:
            result[str(year)] = None
            continue

        # 切片信号(与df_slice索引对齐)
        sliced_buy, sliced_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_slice, df)

        stats = _calc_slice_stats(df_slice, sliced_buy, sliced_sell, mode)
        result[str(year)] = _fmt_stats_for_output(stats)

    return result


def _run_oos_retest(
    df: pd.DataFrame, buy_mask: pd.Series, sell_mask: pd.Series,
    mode: str = 'full_in'
) -> Dict[str, Optional[Dict[str, Any]]]:
    """样本外回测:前70%训练/后30%测试"""
    total_len = len(df)
    split_idx = int(total_len * 0.7)
    if split_idx < 60 or (total_len - split_idx) < 30:
        return {'train': None, 'test': None}

    # 训练集
    df_train = df.iloc[:split_idx].copy()
    train_buy, train_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_train, df)
    stats_train = _calc_slice_stats(df_train, train_buy, train_sell, mode)

    # 测试集
    df_test = df.iloc[split_idx:].copy()
    test_buy, test_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_test, df)
    stats_test = _calc_slice_stats(df_test, test_buy, test_sell, mode)

    return {
        'train': _fmt_stats_for_output(stats_train),
        'test': _fmt_stats_for_output(stats_test)
    }


def _run_regime_retest(
    df: pd.DataFrame, buy_mask: pd.Series, sell_mask: pd.Series,
    mode: str = 'full_in'
) -> Dict[str, Optional[Dict[str, Any]]]:
    """极端行情回测:4个regime独立统计"""
    result = {}

    for start_str, end_str, key in REGIMES:
        df_slice = _slice_by_date_range(df, start_str, end_str)
        if len(df_slice) < 10:
            result[key] = None
            continue

        # 切片信号(与df_slice索引对齐)
        sliced_buy, sliced_sell = _slice_buy_sell_masks(buy_mask, sell_mask, df_slice, df)

        stats = _calc_slice_stats(df_slice, sliced_buy, sliced_sell, mode)
        # 仅输出ret和dd
        if stats is None:
            result[key] = None
        else:
            result[key] = {
                'ret': round(stats.get('total_ret', 0) / 100, 4) if stats.get('total_ret') is not None else None,
                'dd': round(stats.get('max_drawdown', 0), 2) if stats.get('max_drawdown') is not None else None
            }

    return result


def run_retest_for_index(iid: str, iname: str):
    """单个指数的二次测试"""
    print(f'\n[retest] {iid} ({iname})')

    df = load_index_data(iid)
    if df is None:
        print(f'  ERROR:无法加载数据')
        return

    first_date = df.index[0]
    last_date = df.index[-1]
    print(f'  数据范围: {_fmt_date(first_date)} ~ {_fmt_date(last_date)} ({len(df)}天)')

    # 生成融合信号候选
    candidates = gen_fusion_candidates(df)
    print(f'  融合候选: {len(candidates)}个')

    # 输出结构
    output = {
        'index_id': iid,
        'index_name': iname,
        'generated_at': _fmt_date(last_date),
        'pairs': {}
    }

    # 对每个候选进行回测切片
    star_count = 0
    for cand in candidates:
        pair_id = cand['pair_id']
        buy_mask = cand['buy_mask']
        sell_mask = cand['sell_mask']

        # 先用full_in模式的y5窗口筛选⭐️候选
        # 模拟build_pair_result中的y5窗口
        y5_start = last_date - pd.DateOffset(years=5)
        if y5_start < first_date:
            y5_start = first_date
        y5_result = simulate_full_in(df, buy_mask, sell_mask, w_start=y5_start)
        y5_years = _days_between(y5_start, last_date) / 365.25
        y5_stats = _build_stats(
            y5_result['trades'], y5_result['final_total'], last_date,
            y5_result['equity_curve'], years=y5_years
        )

        # 仅处理⭐️候选
        if not _is_star_candidate(y5_stats):
            continue

        star_count += 1
        print(f'  [{star_count}] {pair_id}')

        # 三种切片回测
        pair_data = {
            'pair_meta': {
                'score': None,  # 前端已有,此处省略详细计算
                'n': y5_stats.get('n_trades', 0),
                'dd': round(y5_stats.get('max_drawdown', 0), 2),
                'win': round(y5_stats.get('win_rate', 0), 2),
                'ret': round(y5_stats.get('total_ret', 0) / 100, 4) if y5_stats.get('total_ret') is not None else None
            },
            'yearly': _run_yearly_retest(df, buy_mask, sell_mask, mode='full_in'),
            'oos': _run_oos_retest(df, buy_mask, sell_mask, mode='full_in'),
            'regimes': _run_regime_retest(df, buy_mask, sell_mask, mode='full_in')
        }

        output['pairs'][pair_id] = pair_data

    print(f'  ⭐️候选数: {star_count}')

    # 写入双版
    out_files = [
        os.path.join(BASE, 'web', 'data', 'lab', f'lab_retest_{iid}.json'),
        os.path.join(BASE, 'static-site', 'data', 'lab', f'lab_retest_{iid}.json')
    ]

    for out_path in out_files:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = os.path.getsize(out_path) / 1024
        print(f'  [output] {out_path} ({size_kb:.1f} KB)')


def main():
    print('=== 策略实验室二次测试(回测切片) ===')
    total_start = pd.Timestamp.now()

    for iid, iname in RETEST_INDEXES:
        run_retest_for_index(iid, iname)

    elapsed = pd.Timestamp.now() - total_start
    print(f'\n=== 全部完成,总耗时 {elapsed.total_seconds():.1f}s ===')


if __name__ == '__main__':
    main()
