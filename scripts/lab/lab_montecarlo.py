#!/usr/bin/env python3
"""策略实验室蒙特卡洛扰动测试 -- 验证策略稳健性

对 top 策略配对施加两类随机扰动,多次重跑回测,检验收益是否稳定:
  方式A(信号翻转):对 buy_mask/sell_mask 每个位置以概率 k% 翻转布尔值
    (True->False 漏信号 / False->True 假信号),k=5/10/20%。
    测"信号时点容错":若少量信号时点偏差,收益是否稳定。
  方式B(价格噪声):对 df.close 加高斯噪声 N(0,sigma) 后重新生成信号,
    再在【原始 df】上执行回测。sigma=0.5%/1%。
    测"价格噪声下信号还出不出":指标受价格微扰影响时信号偏移的后果。
    用原始 df 执行,避免噪声价格自身涨跌混淆收益归因。

聚合指标:mean/std/p5/p25/p50/p75/p95 分位数 + 正收益占比 + max_dd 均值/std。
稳健性评级(基于 5% 信号翻转档):
  Robust    : profitable_pct>80% 且 std/|mean|<0.5
  Moderate  : 50%<=profitable_pct<=80%
  Fragile   : profitable_pct<50% 或 std>|mean|

不改动 lab_simulate.py / backtest_strategies.py,仅 import。
输出: static-site/data/lab_montecarlo.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(BASE, 'a-stock-data'))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'lab'))

from backtest_strategies import gen_buy_signals, gen_sell_signals  # noqa: E402
from lab_simulate import (  # noqa: E402
    load_index_data, simulate_full_in, _build_stats, INITIAL_CAPITAL,
)

PROG_FILE = '/tmp/agent-progress-monte.md'

# ---- 配置 ----
TARGET_INDEXES = [('sh', '上证指数'), ('cyb', '创业板指'), ('kc50', '科创50')]
TOP_N = 8
M_SIGNAL = 200      # 信号翻转重跑次数(每次仅 simulate,快)
M_PRICE = 100       # 价格噪声重跑次数(每次需重算信号,慢,减半)
K_LEVELS = [5, 10, 20]           # 信号翻转 %
SIGMA_LEVELS = [0.005, 0.01]     # 价格噪声 sigma(0.5%, 1%)
SEED = 42
LAB_DIR = os.path.join(BASE, 'static-site', 'data', 'lab')
OUT_PATH = os.path.join(BASE, 'static-site', 'data', 'lab_montecarlo.json')


def echo(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(PROG_FILE, 'a') as f:
        f.write(line + '\n')


def load_top_pairs(iid):
    """从 stats JSON 读 top N 配对(按 full_in all total_ret 降序)。返回 (index_name, [(pid,total_ret,max_dd),...])"""
    p = os.path.join(LAB_DIR, f'lab_sim_{iid}_stats.json')
    d = json.load(open(p))
    pairs = []
    for pid, pv in d['pairs'].items():
        s = pv['full_in']['stats']['all']
        pairs.append((pid, s['total_ret'], s['max_drawdown'], s['n_trades']))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return d['index_name'], pairs[:TOP_N]


def flip_mask(mask, k_pct, rng):
    """每个位置以 k% 概率翻转布尔值(True<->False)。"""
    arr = mask.values.astype(bool).copy()
    flip = rng.random(len(arr)) < (k_pct / 100.0)
    arr[flip] = ~arr[flip]
    return pd.Series(arr, index=mask.index)


def compute_ret_dd(df, bm, sm):
    """跑一次 simulate_full_in,返回 (total_ret, max_dd) 百分比。"""
    r = simulate_full_in(df, bm, sm)
    stats = _build_stats(r['trades'], r['final_total'], r['last_date'], r['equity_curve'])
    return stats['total_ret'], stats['max_drawdown']


def perturb_price_signals(df, buy_key, sell_key, sigma, rng):
    """扰动 close 后重算信号,mask reindex 回原始 df.index。返回 (bm, sm) 或 (None,None)。"""
    dfn = df.copy()
    dfn['close'] = df['close'] * (1.0 + rng.normal(0, sigma, len(df)))
    bsn = gen_buy_signals(dfn)
    ssn = gen_sell_signals(dfn)
    bm = bsn.get(buy_key)
    sm = ssn.get(sell_key)
    if bm is None or sm is None:
        return None, None
    bm = bm.reindex(df.index, fill_value=False).astype(bool)
    sm = sm.reindex(df.index, fill_value=False).astype(bool)
    if bm.sum() == 0 or sm.sum() == 0:
        return None, None
    return bm, sm


def aggregate(rets, dds):
    """聚合多次重跑结果。"""
    rets = np.array(rets, dtype=float)
    dds = np.array(dds, dtype=float)
    mean = float(rets.mean()) if len(rets) else 0.0
    std = float(rets.std()) if len(rets) else 0.0
    return {
        'mean_ret': round(mean, 2),
        'std_ret': round(std, 2),
        'p5': round(float(np.percentile(rets, 5)), 2) if len(rets) else 0.0,
        'p25': round(float(np.percentile(rets, 25)), 2) if len(rets) else 0.0,
        'p50': round(float(np.percentile(rets, 50)), 2) if len(rets) else 0.0,
        'p75': round(float(np.percentile(rets, 75)), 2) if len(rets) else 0.0,
        'p95': round(float(np.percentile(rets, 95)), 2) if len(rets) else 0.0,
        'profitable_pct': round(float((rets > 0).mean() * 100), 1) if len(rets) else 0.0,
        'mean_dd': round(float(dds.mean()), 2) if len(dds) else 0.0,
        'std_dd': round(float(dds.std()), 2) if len(dds) else 0.0,
        'n': len(rets),
    }


def rate_robustness(base_ret, agg_5pct):
    """基于 5% 信号翻转档评级。基线亏损则标 N/A。"""
    if base_ret <= 0:
        return 'N/A(基线亏损)'
    prof = agg_5pct['profitable_pct']
    mean = agg_5pct['mean_ret']
    std = agg_5pct['std_ret']
    cv = std / abs(mean) if abs(mean) > 1e-6 else 999.0
    if prof > 80 and cv < 0.5:
        return 'Robust'
    elif prof >= 50:
        return 'Moderate'
    else:
        return 'Fragile'


def run():
    rng = np.random.default_rng(SEED)
    t_total = time.time()
    echo(f"开始蒙特卡洛扰动测试 seed={SEED} M_signal={M_SIGNAL} M_price={M_PRICE}")

    result = {
        'generated_at': time.strftime('%Y-%m-%d'),
        'config': {
            'top_n': TOP_N,
            'm_signal': M_SIGNAL,
            'm_price': M_PRICE,
            'k_levels': K_LEVELS,
            'sigma_levels': SIGMA_LEVELS,
            'seed': SEED,
            'modes': {
                'signal_flip': '每个信号位置以k%概率翻转(True<->False)',
                'price_noise': 'close加高斯噪声N(0,sigma)后重算信号,原始df执行回测',
            },
        },
        'indexes': {},
    }

    for iid, _ in TARGET_INDEXES:
        t_idx = time.time()
        iname, top_pairs = load_top_pairs(iid)
        echo(f"[{iid}] {iname} top{TOP_N}配对: " +
             ", ".join(f"{p[0]}={p[1]:+.0f}%" for p in top_pairs[:4]) + " ...")
        df = load_index_data(iid)
        if df is None:
            echo(f"[{iid}] 无法加载数据,跳过")
            continue
        bs = gen_buy_signals(df)
        ss = gen_sell_signals(df)

        idx_res = {'index_name': iname, 'pairs': {}}
        for pi, (pid, _base_tr_json, _base_dd_json, n_tr_json) in enumerate(top_pairs):
            buy_key, sell_key = pid.split('|')
            bm0 = bs.get(buy_key)
            sm0 = ss.get(sell_key)
            if bm0 is None or sm0 is None or bm0.sum() == 0 or sm0.sum() == 0:
                echo(f"[{iid}] {pid} 信号缺失,跳过")
                continue

            t_pair = time.time()
            b_ret, b_dd = compute_ret_dd(df, bm0, sm0)
            pair_res = {
                'buy_key': buy_key,
                'sell_key': sell_key,
                'baseline': {
                    'total_ret': round(b_ret, 2),
                    'max_dd': round(b_dd, 2),
                    'n_buy_signals': int(bm0.sum()),
                    'n_sell_signals': int(sm0.sum()),
                },
                'signal_flip': {},
                'price_noise': {},
            }

            # 方式A 信号翻转
            for k in K_LEVELS:
                rets, dds = [], []
                for _ in range(M_SIGNAL):
                    pbm = flip_mask(bm0, k, rng)
                    psm = flip_mask(sm0, k, rng)
                    r, d = compute_ret_dd(df, pbm, psm)
                    rets.append(r)
                    dds.append(d)
                pair_res['signal_flip'][f'{k}pct'] = aggregate(rets, dds)

            # 方式B 价格噪声(重算信号)
            for sigma in SIGMA_LEVELS:
                rets, dds = [], []
                for _ in range(M_PRICE):
                    pbm, psm = perturb_price_signals(df, buy_key, sell_key, sigma, rng)
                    if pbm is None:
                        continue
                    r, d = compute_ret_dd(df, pbm, psm)
                    rets.append(r)
                    dds.append(d)
                key = f'sigma{int(sigma * 1000)}bps'
                pair_res['price_noise'][key] = aggregate(rets, dds)

            pair_res['robustness'] = rate_robustness(b_ret, pair_res['signal_flip']['5pct'])
            idx_res['pairs'][pid] = pair_res
            echo(f"[{iid}] ({pi+1}/{TOP_N}) {pid} baseline={b_ret:+.1f}% "
                 f"5%flip:mean={pair_res['signal_flip']['5pct']['mean_ret']:+.1f}% "
                 f"prof={pair_res['signal_flip']['5pct']['profitable_pct']:.0f}% "
                 f"-> {pair_res['robustness']} "
                 f"({time.time()-t_pair:.1f}s)")

        result['indexes'][iid] = idx_res
        echo(f"[{iid}] 完成 {len(idx_res['pairs'])} 配对,耗时 {time.time()-t_idx:.1f}s")
        # 增量写盘(防中途失败丢全部)
        with open(OUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    echo(f"全部完成,总耗时 {time.time()-t_total:.1f}s,输出 {OUT_PATH}")


if __name__ == '__main__':
    run()
