#!/usr/bin/env python3
"""融合 P2 回测：生产链路 vs 回测链路 信号一致性验证。

目标(§28.8.8)：验证生产环境实际触发的信号(signal_daily 表)与回测引擎独立算的
信号 mask 日期集合一致，坐实「生产链路 = 回测链路」(回测可信)。

认知纠正：signal_daily 表 signal 字段只有 buy/buy_aux/sell 3 值，不存融合信号。
但生产 sell 本身 = D1_high20_drop5 & MA60_bull & MACD_below_signal = 融合策略 F_D1_S1_MACD；
生产 buy = RSI 上穿30 = C1_RSI30；生产 buy_aux = BB 下轨回归 = BB_lower_revert。

映射(生产 signal -> 回测 mask)：
  buy     -> C1_RSI30
  buy_aux -> BB_lower_revert
  sell    -> F_D1_S1_MACD(= D1_high20_drop5 & MA60_bull & MACD_below_signal)

已知 3 个差异来源(非 bug，配置/语义差异)：
  1. per-index filter：kc50 buy=rsi_cross_25(上穿25 vs 回测30)；csi1000/cyb buy_aux=rsi_cross_40(多一层过滤)
  2. 去重：生产 buy_aux_set = buy_aux - buy_set(C1 同日优先，不发 buy_aux)；回测 BB_lower_revert 不去重
  3. sell：无 per-index 无去重，预期完全一致

输出：static-site/data/lab_fusion_p2.json
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A_STOCK_DIR = os.path.join(BASE, "a-stock-data")
sys.path.insert(0, A_STOCK_DIR)
sys.path.insert(0, BASE)

from app.db import get_conn
from backtest_strategies import gen_buy_signals, gen_sell_signals, rsi
from fusion_signals import _gen_filter_masks

# 9 A股宽基指数(与 lab_simulate SIM_INDEXES 一致)
INDICES = [
    ('sh', '上证指数'), ('sz', '深成指'), ('cyb', '创业板指'), ('kc50', '科创50'),
    ('bj50', '北证50'), ('sz50', '上证50'), ('hs300', '沪深300'),
    ('csi500', '中证500'), ('csi1000', '中证1000'),
]

# per-index filter 配置(来自 indicators.yaml，影响生产信号触发阈值)
# buy_filter: kc50=rsi_cross_25(其余默认 rsi_cross_30)
# buy_aux_filter: csi1000/cyb=rsi_cross_40(其余无)
PER_INDEX_BUY_FILTER = {'kc50': 'rsi_cross_25'}
PER_INDEX_BUY_AUX_FILTER = {'csi1000': 'rsi_cross_40', 'cyb': 'rsi_cross_40'}

# 生产 signal -> 回测 mask 映射
MAPPING = [
    ('buy', 'C1_RSI30'),
    ('buy_aux', 'BB_lower_revert'),
    ('sell', 'F_D1_S1_MACD'),
]


def fmt_date(d):
    """Timestamp 或 'YYYYMMDD' 字符串 -> 'YYYY-MM-DD'。"""
    if isinstance(d, pd.Timestamp):
        return d.strftime('%Y-%m-%d')
    s = str(d)
    if len(s) == 8 and '-' not in s:
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def load_prod_signals(conn, iid):
    """signal_daily 表 -> {buy/buy_aux/sell: set('YYYY-MM-DD')}。"""
    rows = conn.execute(
        "SELECT signal, date FROM signal_daily WHERE index_id=? ORDER BY date",
        (iid,),
    ).fetchall()
    sets = {'buy': set(), 'buy_aux': set(), 'sell': set()}
    for sig, date in rows:
        if sig in sets:
            sets[sig].add(fmt_date(date))
    return sets


def load_index_df(conn, iid):
    """index_daily -> df(index=date Timestamp, cols open/high/low/close)。与 lab_simulate.load_index_data 同源。"""
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close FROM index_daily WHERE index_id=? ORDER BY date",
        conn, params=(iid,), parse_dates=['date'])
    if len(df) < 60:
        return None
    return df.set_index('date').astype(float)[['open', 'high', 'low', 'close']]


def compute_lab_masks(df):
    """回测算 C1_RSI30/BB_lower_revert/F_D1_S1_MACD mask -> {key: set('YYYY-MM-DD')}。

    用 backtest_strategies + fusion_signals 同款实现(与 lab_simulate --fusion 同源)。
    F_D1_S1_MACD = D1_high20_drop5 & MA60_bull & MACD_below_signal(同日 AND)。
    """
    buy_sigs = gen_buy_signals(df)
    sell_sigs = gen_sell_signals(df)
    fmasks = _gen_filter_masks(df)
    c1 = buy_sigs['C1_RSI30']
    bb = buy_sigs['BB_lower_revert']
    f_d1_s1_macd = sell_sigs['D1_high20_drop5'] & fmasks['MA60_bull'] & fmasks['MACD_below_signal']
    return {
        'C1_RSI30': {fmt_date(d) for d in c1[c1].index},
        'BB_lower_revert': {fmt_date(d) for d in bb[bb].index},
        'F_D1_S1_MACD': {fmt_date(d) for d in f_d1_s1_macd[f_d1_s1_macd].index},
    }, buy_sigs, sell_sigs, fmasks


def compare(prod_set, lab_set, prod_max_date, prod_buy_dates=None):
    """对比生产/回测日期集合，区分差异类型。

    prod_max_date: 生产最大日期('YYYY-MM-DD')，用于区分 lab_only 的「生产滞后未算」vs「真实差异」。
    prod_buy_dates: 生产 buy 日期集合，用于 buy_aux 差异的「去重」归因
        (生产 buy_aux_set = buy_aux - buy_set，同日有 buy 则不发 buy_aux；用生产 buy 日期最准)。
    """
    common = prod_set & lab_set
    prod_only = sorted(prod_set - lab_set)       # 生产有回测无
    lab_only = sorted(lab_set - prod_set)        # 回测有生产无
    # lab_only 拆分：>prod_max = 生产滞后未算(非差异)；<=prod_max = 真实差异
    lab_only_lag = [d for d in lab_only if prod_max_date and d > prod_max_date]
    lab_only_diff = [d for d in lab_only if not (prod_max_date and d > prod_max_date)]
    # lab_only_diff 归因：同日在生产 buy 里 -> 去重(生产该日发buy不发buy_aux, 仅 buy_aux 有意义)
    dedup = []
    other = []
    if prod_buy_dates is not None:
        for d in lab_only_diff:
            if d in prod_buy_dates:
                dedup.append(d)
            else:
                other.append(d)
    else:
        other = lab_only_diff
    union = prod_set | lab_set
    consistency = len(common) / len(union) * 100 if union else 100.0
    # 生产口径一致率(生产信号里有多少被回测覆盖)
    prod_cover = len(common) / len(prod_set) * 100 if prod_set else 100.0
    return {
        'prod_n': len(prod_set),
        'lab_n': len(lab_set),
        'common_n': len(common),
        'consistency_pct': round(consistency, 1),      # 交集/并集
        'prod_cover_pct': round(prod_cover, 1),         # 交集/生产(生产信号被回测覆盖率)
        'prod_only': prod_only,                          # 生产有回测无(疑似回测漏算/算法差)
        'lab_only_dedup': dedup,                         # 回测有生产无-去重导致(同日C1)
        'lab_only_other': other,                         # 回测有生产无-其他(per-index filter/算法差)
        'lab_only_lag': lab_only_lag,                    # 回测有生产无-生产滞后未算
    }


def main():
    conn = get_conn()
    results = {}
    for iid, iname in INDICES:
        prod = load_prod_signals(conn, iid)
        df = load_index_df(conn, iid)
        if df is None:
            print(f"[skip] {iid} 数据不足60行")
            continue
        lab, buy_sigs, sell_sigs, fmasks = compute_lab_masks(df)
        all_prod = prod['buy'] | prod['buy_aux'] | prod['sell']
        prod_max = max(all_prod) if all_prod else None

        idx_result = {
            'index_id': iid, 'index_name': iname,
            'prod_max_date': prod_max,
            'buy_filter': PER_INDEX_BUY_FILTER.get(iid, 'rsi_cross_30(默认)'),
            'buy_aux_filter': PER_INDEX_BUY_AUX_FILTER.get(iid, '无'),
        }
        for prod_sig, lab_key in MAPPING:
            r = compare(prod[prod_sig], lab[lab_key], prod_max,
                        prod_buy_dates=prod['buy'] if prod_sig == 'buy_aux' else None)
            r['lab_mask'] = lab_key
            idx_result[prod_sig] = r
        results[iid] = idx_result

        # 控制台打印
        print(f"\n[{iid}] {iname}  prod_max={prod_max}  buy_filter={idx_result['buy_filter']}  buy_aux_filter={idx_result['buy_aux_filter']}")
        for prod_sig, lab_key in MAPPING:
            r = idx_result[prod_sig]
            print(f"  {prod_sig:8s}({r['prod_n']:3d}) vs {lab_key:16s}({r['lab_n']:3d})  "
                  f"一致{r['common_n']:3d} 一致率{r['consistency_pct']:5.1f}% 生产覆盖{r['prod_cover_pct']:5.1f}%  "
                  f"prod_only={len(r['prod_only'])} 去重={len(r['lab_only_dedup'])} 其他={len(r['lab_only_other'])} 滞后={len(r['lab_only_lag'])}")
    conn.close()

    # 汇总
    summary = {}
    for prod_sig, lab_key in MAPPING:
        tot_prod = sum(results[i][prod_sig]['prod_n'] for i in results)
        tot_lab = sum(results[i][prod_sig]['lab_n'] for i in results)
        tot_common = sum(results[i][prod_sig]['common_n'] for i in results)
        tot_union = sum(results[i][prod_sig]['prod_n'] + len(results[i][prod_sig]['lab_only_dedup'])
                        + len(results[i][prod_sig]['lab_only_other']) + len(results[i][prod_sig]['lab_only_lag'])
                        for i in results)
        summary[prod_sig] = {
            'lab_mask': lab_key,
            'total_prod': tot_prod, 'total_lab': tot_lab, 'total_common': tot_common,
            'consistency_pct': round(tot_common / tot_union * 100, 1) if tot_union else 100.0,
        }

    out = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'desc': '融合P2: 生产链路(signal_daily) vs 回测链路(backtest_strategies+fusion_signals)信号一致性验证',
        'mapping': {'buy': 'C1_RSI30', 'buy_aux': 'BB_lower_revert', 'sell': 'F_D1_S1_MACD(=D1&MA60_bull&MACD_below_signal)'},
        'diff_sources': [
            'per-index filter: kc50 buy=rsi_cross_25(上穿25); csi1000/cyb buy_aux=rsi_cross_40',
            '去重: 生产 buy_aux 去掉与 C1 同日的(C1优先); 回测 BB_lower_revert 不去重',
            'sell: 无 per-index 无去重, 预期完全一致',
        ],
        'summary': summary,
        'indices': results,
    }
    out_path = os.path.join(BASE, 'static-site', 'data', 'lab_fusion_p2.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[输出] {out_path}")
    print("[汇总]")
    for prod_sig, s in summary.items():
        print(f"  {prod_sig:8s} -> {s['lab_mask']:16s} 一致率{s['consistency_pct']}% (生产{s['total_prod']}/回测{s['total_lab']}/共同{s['total_common']})")


if __name__ == '__main__':
    main()
