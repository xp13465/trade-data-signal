#!/usr/bin/env python3
"""策略实验室多周期回测矩阵 -- 生成 lab_backtest_{index}.json

按指数拆分生成 22策略 × 5窗口 × 4horizon 矩阵数据，供前端矩阵指数切换。
复用 a-stock-data/backtest_strategies.py 的信号生成与统计函数。

输出: web/data/lab/ + static-site/data/lab/ 各一份 lab_backtest_{iid}.json
"""
import json
import os
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A_STOCK_DIR = os.path.join(BASE, "a-stock-data")
sys.path.insert(0, A_STOCK_DIR)
from backtest_strategies import (
    gen_buy_signals, gen_sell_signals, stats_block, load_index_series,
    STRATEGY_DESC,
)
from fusion_signals import gen_fusion_candidates, gen_hardcoded_fusion_candidates

BUY_ORDER = ['C1_RSI30', 'Donchian20_up', 'Donchian55_up', 'BB_lower_revert',
             'BB_upper_break', 'Supertrend_buy', 'MA_golden_5_20',
             'MA_golden_10_60', 'MACD_golden', 'KDJ_golden_oversold', 'Vol_breakout']
SELL_ORDER = ['B0_RSI70', 'D1_high20_drop5', 'Donchian10_down', 'Donchian20_down',
              'BB_upper_revert', 'BB_middle_break', 'Supertrend_sell',
              'MA_death_5_20', 'MACD_death', 'ATR_trail_stop', 'KDJ_death_overbought']

SENT_DB = os.path.join(BASE, "data", "sentiment.db")
sys.path.insert(0, BASE)
from app.db import get_conn
HORIZONS = (5, 10, 20, 60)
PERIODS_JSON = [('全史', None), ('近10年', 'y10'), ('近5年', 'y5'),
                ('近3年', 'y3'), ('近1年', 'y1')]

SIM_INDEXES = [
    ('sh',      '上证指数'),
    ('sz',      '深证成指'),
    ('cyb',     '创业板指'),
    ('kc50',    '科创50'),
    ('bj50',    '北证50'),
    ('sz50',    '上证50'),
    ('hs300',   '沪深300'),
    ('csi500',  '中证500'),
    ('csi1000', '中证1000'),
]


def run_index(iid, iname):
    print(f"\n[load] {iid} ({iname})")
    con = get_conn()
    df = load_index_series(con, iid)
    con.close()
    if df is None or len(df) < 60:
        print(f"  ERROR: 无法加载 {iid} 数据，跳过")
        return

    max_date = df.index.max()
    cutoffs = {
        'y10': max_date - pd.Timedelta(days=365 * 10),
        'y5':  max_date - pd.Timedelta(days=365 * 5),
        'y3':  max_date - pd.Timedelta(days=365 * 3),
        'y1':  max_date - pd.Timedelta(days=365),
    }

    close = df['close']
    idx = close.index
    fwd = {h: (close.shift(-h) / close - 1.0) * 100.0 for h in HORIZONS}

    buys = gen_buy_signals(df)
    sells = gen_sell_signals(df)

    all_strats = [('buy', s) for s in BUY_ORDER] + [('sell', s) for s in SELL_ORDER]
    from collections import defaultdict
    qual = defaultdict(list)

    for side, sname in all_strats:
        masks = buys if side == 'buy' else sells
        mask = masks.get(sname)
        if mask is None or mask.sum() == 0:
            continue
        sig_dates = idx[mask]
        for pname, pkey in PERIODS_JSON:
            if pkey is not None:
                sd = sig_dates[sig_dates > cutoffs[pkey]]
            else:
                sd = sig_dates
            if len(sd) == 0:
                continue
            for h in HORIZONS:
                r = fwd[h].reindex(sd).dropna().values
                if len(r):
                    qual[(side, sname, h, pname)].extend(r.tolist())

    lab = {
        "generated_at": str(max_date.date()),
        "data_cutoff": str(max_date.date()),
        "index_id": iid,
        "index_name": iname,
        "periods": [p[0] for p in PERIODS_JSON],
        "horizons": [f"{h}d" for h in HORIZONS],
        "strategies": {},
    }
    for side, sname in all_strats:
        is_sell = (side == 'sell')
        strat_obj = {
            "side": side,
            "desc": STRATEGY_DESC.get(sname, sname),
            "periods": {},
        }
        for pname, _ in PERIODS_JSON:
            strat_obj["periods"][pname] = {}
            for h in HORIZONS:
                n, m, _med, wr, pl = stats_block(
                    qual.get((side, sname, h, pname), []), is_sell)
                strat_obj["periods"][pname][f"{h}d"] = {
                    "win": round(float(wr), 4) if not np.isnan(wr) else None,
                    "pl": round(float(pl), 3) if not np.isnan(pl) else None,
                    "n": int(n),
                    "mean": round(float(m) / 100.0, 5) if not np.isnan(m) else None,
                }
        lab["strategies"][sname] = strat_obj

    fname = f"lab_backtest_{iid}.json"
    for base_dir in ('web', 'static-site'):
        p = os.path.join(BASE, base_dir, 'data', 'lab', fname)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(lab, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = os.path.getsize(p) / 1024
        print(f"[output] {p} ({size_kb:.1f} KB)")


def run_fusion_matrix(iid, iname):
    """融合策略多周期矩阵 -- 生成 lab_backtest_fusion_{iid}.json

    对 97 融合候选(91候选 + 6硬编码),按 side 取信号 mask,统计 5窗口×4horizon
    forward return(单次操作统计,非配对交易)。side 由 pair_type 决定:
      buy_sell/buy_buy/hardcoded_buy -> buy(用 buy_mask);
      sell_sell/hardcoded_sell -> sell(用 sell_mask)。
    strategies 以 pair_id 为 key,前端融合弹窗矩阵按 pair_id 取值(不再 chartBaseKey 代理)。
    """
    print(f"\n[fusion-matrix load] {iid} ({iname})")
    con = get_conn()
    df = load_index_series(con, iid)
    con.close()
    if df is None or len(df) < 60:
        print(f"  ERROR: 无法加载 {iid} 数据，跳过")
        return

    max_date = df.index.max()
    cutoffs = {
        'y10': max_date - pd.Timedelta(days=365 * 10),
        'y5':  max_date - pd.Timedelta(days=365 * 5),
        'y3':  max_date - pd.Timedelta(days=365 * 3),
        'y1':  max_date - pd.Timedelta(days=365),
    }

    close = df['close']
    idx = close.index
    fwd = {h: (close.shift(-h) / close - 1.0) * 100.0 for h in HORIZONS}

    candidates = gen_fusion_candidates(df) + gen_hardcoded_fusion_candidates(df)
    print(f"[fusion-matrix] {len(candidates)} 个候选")

    def _side_of(pt):
        return 'sell' if pt in ('sell_sell', 'hardcoded_sell') else 'buy'

    from collections import defaultdict
    qual = defaultdict(list)
    for c in candidates:
        side = _side_of(c['pair_type'])
        mask = c['buy_mask'] if side == 'buy' else c['sell_mask']
        if mask is None or mask.sum() == 0:
            continue
        pair_id = c['pair_id']
        sig_dates = idx[mask]
        for pname, pkey in PERIODS_JSON:
            if pkey is not None:
                sd = sig_dates[sig_dates > cutoffs[pkey]]
            else:
                sd = sig_dates
            if len(sd) == 0:
                continue
            for h in HORIZONS:
                r = fwd[h].reindex(sd).dropna().values
                if len(r):
                    qual[(pair_id, side, h, pname)].extend(r.tolist())

    lab = {
        "generated_at": str(max_date.date()),
        "data_cutoff": str(max_date.date()),
        "index_id": iid,
        "index_name": iname,
        "periods": [p[0] for p in PERIODS_JSON],
        "horizons": [f"{h}d" for h in HORIZONS],
        "strategies": {},
    }
    for c in candidates:
        pair_id = c['pair_id']
        side = _side_of(c['pair_type'])
        is_sell = (side == 'sell')
        strat_obj = {
            "side": side,
            "desc": c['pair_type'],
            "pair_type": c['pair_type'],
            "components": c['components'],
            "ref_side": c['ref_side'],
            "periods": {},
        }
        for pname, _ in PERIODS_JSON:
            strat_obj["periods"][pname] = {}
            for h in HORIZONS:
                n, m, _med, wr, pl = stats_block(
                    qual.get((pair_id, side, h, pname), []), is_sell)
                strat_obj["periods"][pname][f"{h}d"] = {
                    "win": round(float(wr), 4) if not np.isnan(wr) else None,
                    "pl": round(float(pl), 3) if not np.isnan(pl) else None,
                    "n": int(n),
                    "mean": round(float(m) / 100.0, 5) if not np.isnan(m) else None,
                }
        lab["strategies"][pair_id] = strat_obj

    fname = f"lab_backtest_fusion_{iid}.json"
    for base_dir in ('web', 'static-site'):
        p = os.path.join(BASE, base_dir, 'data', 'lab', fname)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(lab, f, ensure_ascii=False, separators=(',', ':'))
        size_kb = os.path.getsize(p) / 1024
        print(f"[output] {p} ({size_kb:.1f} KB)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='策略实验室多周期矩阵（按指数拆分）')
    parser.add_argument('--fusion', action='store_true',
                        help='跑融合策略矩阵（97候选 × 9指数），'
                             '输出 lab_backtest_fusion_{iid}.json')
    args = parser.parse_args()

    if args.fusion:
        print(f"=== 策略实验室融合策略多周期矩阵（按指数拆分）===")
        t0 = time.time()
        for iid, iname in SIM_INDEXES:
            run_fusion_matrix(iid, iname)
        print(f"\n=== 融合矩阵全部完成: {len(SIM_INDEXES)} 个指数, 总耗时 {time.time()-t0:.1f}s ===")
    else:
        print(f"=== 策略实验室多周期矩阵（按指数拆分）===")
        t0 = time.time()
        for iid, iname in SIM_INDEXES:
            run_index(iid, iname)
        print(f"\n=== 全部完成: {len(SIM_INDEXES)} 个指数, 总耗时 {time.time()-t0:.1f}s ===")


if __name__ == '__main__':
    main()
