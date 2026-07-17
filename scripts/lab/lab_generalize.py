#!/usr/bin/env python3
"""策略实验室标的泛化测试 -- 验证 top 策略配对是否对个股/申万行业泛化,
还是只对 9 指数过拟合。

方法:
  1. 从 9 指数 stats JSON 聚合所有配对的 total_ret(全历史窗口),
     按 9 指数平均 total_ret 排序取 top 6 配对(原基准)。
  2. 个股泛化:从 mootdx_daily_raw 按 code 前缀(60/00/30/68)分散抽样 18 只,
     要求数据完整(>=3年 且 最新数据>=2024),对每只跑 top 6 配对 full_in 全历史。
  3. 申万行业泛化:31 个 sw_801xxx 行业指数,同样跑 top 6 配对。
  4. 额外:个股有 volume,测 Vol_breakout(指数无 vol 跑不了)× 2 个 sell,看个股专属策略是否有效。
  5. 对比 9指数/个股/申万行业的收益分布:mean/median/profitable_pct/std。
  6. 泛化评级:个股正收益占比>60% 且 行业正收益占比>60% = 强;40-60% = 中;<40% = 弱(过拟合指数)。

注意:
  - 只 import lab_simulate / backtest_strategies,不改它们。
  - mootdx_daily_raw 的 close 为未复权价,个股除权日会跳水,可能触发跌破类卖信号,
    全仓模拟收益会因此略有失真。但泛化性比较是相对的(同策略跨标的),不影响结论方向。
  - 申万行业指数用 load_index_data 读 index_daily(无 volume,同 9 指数口径)。

输出: static-site/data/lab_generalize.json
"""
import json
import os
import sys
import sqlite3

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A_STOCK_DIR = os.path.join(BASE, "a-stock-data")
sys.path.insert(0, A_STOCK_DIR)
sys.path.insert(0, os.path.join(BASE, "scripts", "lab"))

from lab_simulate import simulate_full_in, _build_stats, load_index_data  # noqa: E402
from backtest_strategies import gen_buy_signals, gen_sell_signals, load_stock_series  # noqa: E402

STOCK_DB = os.path.join(BASE, "data", "stock_daily.db")
STATS_DIR = os.path.join(BASE, "static-site", "data", "lab")
OUT_JSON = os.path.join(BASE, "static-site", "data", "lab_generalize.json")

SIM_IIDS = ['sh', 'sz', 'sz50', 'hs300', 'csi500', 'csi1000', 'cyb', 'bj50', 'kc50']
SIM_INAMES = {
    'sh': '上证指数', 'sz': '深证成指', 'sz50': '上证50', 'hs300': '沪深300',
    'csi500': '中证500', 'csi1000': '中证1000', 'cyb': '创业板指', 'bj50': '北证50',
    'kc50': '科创50',
}
# 31 个申万一级行业指数
SW_IIDS = [f'sw_801{i:03d}' for i in
           [10, 30, 40, 50, 80, 110, 120, 130, 140, 150, 160, 170, 180,
            200, 210, 230, 710, 720, 730, 740, 750, 760, 770, 780, 790,
            880, 890, 950, 960, 970, 980]]
SW_NAMES = {
    'sw_801010': '农林牧渔', 'sw_801030': '化工', 'sw_801040': '钢铁',
    'sw_801050': '有色金属', 'sw_801080': '电子', 'sw_801110': '家用电器',
    'sw_801120': '食品饮料', 'sw_801130': '纺织服饰', 'sw_801140': '轻工制造',
    'sw_801150': '医药生物', 'sw_801160': '公用事业', 'sw_801170': '交通运输',
    'sw_801180': '房地产', 'sw_801200': '商贸零售', 'sw_801210': '社会服务',
    'sw_801230': '综合', 'sw_801710': '建筑材料', 'sw_801720': '建筑装饰',
    'sw_801730': '电力设备', 'sw_801740': '国防军工', 'sw_801750': '计算机',
    'sw_801760': '传媒', 'sw_801770': '通信', 'sw_801780': '银行',
    'sw_801790': '非银金融', 'sw_801880': '汽车', 'sw_801890': '机械设备',
    'sw_801950': '煤炭', 'sw_801960': '石油石化', 'sw_801970': '环保',
    'sw_801980': '美容护理',
}

TOP_K = 6
SAMPLE_STOCKS = 18
SEED = 20260715


def log(msg):
    print(msg, flush=True)
    with open('/tmp/agent-progress-gen.md', 'a') as f:
        f.write(msg + '\n')


def select_top_pairs(k=TOP_K):
    """从 9 指数 stats JSON 聚合 pair total_ret(all 窗口),按平均 total_ret 排序取 top k。
    返回 [(pair_id, mean_ret, median_ret, per_index{iid:total_ret})]。"""
    agg = {}  # pair_id -> {iid: total_ret}
    for iid in SIM_IIDS:
        p = os.path.join(STATS_DIR, f'lab_sim_{iid}_stats.json')
        with open(p) as f:
            d = json.load(f)
        for pid, pv in d['pairs'].items():
            tr = pv['full_in']['stats']['all']['total_ret']
            agg.setdefault(pid, {})[iid] = tr
    ranked = []
    for pid, per in agg.items():
        if len(per) < 6:
            continue
        vals = list(per.values())
        ranked.append((pid, float(np.mean(vals)), float(np.median(vals)), per))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:k]


def sample_stock_codes(con, k=SAMPLE_STOCKS):
    """按 code 前缀(60/00/30/68)分散抽样,要求数据完整(>=3年 且 max>=2024)。
    分配:60→6, 00→6, 30→3, 68→3。返回 [(code, name_or_code)]。"""
    df = pd.read_sql_query(
        "SELECT code, COUNT(*) c, MAX(date) mx FROM mootdx_daily_raw "
        "GROUP BY code HAVING c >= 750 AND mx >= '20240101'", con)
    rng = np.random.default_rng(SEED)
    alloc = {'60': 6, '00': 6, '30': 3, '68': 3}
    picked = []
    for prefix, n in alloc.items():
        pool = df[df['code'].str.startswith(prefix)]['code'].tolist()
        if len(pool) < n:
            log(f"  WARN: {prefix} 前缀候选不足 {n}, 只取 {len(pool)}")
            picked.extend(pool)
            continue
        idx = rng.choice(len(pool), size=n, replace=False)
        picked.extend(pool[i] for i in sorted(idx))
    return picked


def run_pair(df, buy_key, sell_key):
    """对 df 跑 buy|sell full_in 全历史,返回 stats dict 或 None(信号不足/数据不足)。"""
    if df is None or len(df) < 60:
        return None
    bs = gen_buy_signals(df)
    ss = gen_sell_signals(df)
    bm = bs.get(buy_key)
    sm = ss.get(sell_key)
    if bm is None or sm is None:
        return None
    bm = bm.fillna(False).astype(bool)
    sm = sm.fillna(False).astype(bool)
    if bm.sum() == 0 or sm.sum() == 0:
        return None
    raw = simulate_full_in(df, bm, sm, w_start=None)
    last_date = df.index[-1]
    stats = _build_stats(raw['trades'], raw['final_total'], last_date,
                         raw['equity_curve'], years=None)
    return stats


def summarize(per_target):
    """per_target: {tid: stats or None}. 返回 {mean_ret, median_ret, profitable_pct, std_ret, n_valid}。"""
    rets = []
    for tid, st in per_target.items():
        if st is None:
            continue
        rets.append(st['total_ret'])
    if not rets:
        return {'mean_ret': None, 'median_ret': None, 'profitable_pct': None,
                'std_ret': None, 'n_valid': 0}
    arr = np.array(rets)
    return {
        'mean_ret': round(float(arr.mean()), 2),
        'median_ret': round(float(np.median(arr)), 2),
        'profitable_pct': round(float((arr > 0).mean() * 100), 1),
        'std_ret': round(float(arr.std()), 2),
        'n_valid': int(len(arr)),
    }


def grade(stock_pct, sw_pct):
    """泛化评级:个股正收益占比 & 行业正收益占比。
    强>60%, 中40-60%, 弱<40%。"""
    lo = min(stock_pct if stock_pct is not None else 0,
             sw_pct if sw_pct is not None else 0)
    if lo > 60:
        return '强泛化'
    elif lo >= 40:
        return '中泛化'
    else:
        return '弱泛化(过拟合指数)'


def main():
    log(f"\n=== 策略实验室标的泛化测试 {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')} ===")

    # 1. 选 top 6 配对
    top = select_top_pairs(TOP_K)
    log(f"[top] 9指数平均 total_ret top {TOP_K} 配对:")
    for pid, m, med, per in top:
        log(f"  {pid:46s} mean={m:+9.1f}% median={med:+8.1f}%")

    pairs = [(pid, pid.split('|')[0], pid.split('|')[1]) for pid, _, _, _ in top]

    # 2. 9 指数基准(从 stats JSON 已有,per 是 {iid: total_ret} float dict)
    baseline = {}
    for pid, m, med, per in top:
        rets = list(per.values())
        arr = np.array(rets)
        baseline[pid] = {
            'mean_ret': round(float(arr.mean()), 2),
            'median_ret': round(float(np.median(arr)), 2),
            'profitable_pct': round(float((arr > 0).mean() * 100), 1),
            'std_ret': round(float(arr.std()), 2),
            'n_valid': int(len(arr)),
            'per_index': per,
        }

    result = {
        'generated_at': pd.Timestamp.now().strftime('%Y-%m-%d'),
        'method': {
            'top_k': TOP_K,
            'selection': '9指数 stats JSON 的 full_in all 窗口 total_ret 平均值排序',
            'sample_stocks': SAMPLE_STOCKS,
            'note': '个股 close 为未复权价,除权日可能触发假卖出信号,全仓模拟收益略失真;泛化性为相对比较,结论方向不受影响',
            'grade_rule': 'min(个股正收益占比, 行业正收益占比): >60%强, 40-60%中, <40%弱(过拟合指数)',
        },
        'top_pairs': [{'pair_id': pid, 'mean_ret_9idx': round(m, 2),
                       'median_ret_9idx': round(med, 2)} for pid, m, med, _ in top],
        'baseline_9indexes': baseline,
        'stocks': {},
        'sw_industries': {},
        'vol_breakout_stocks': {},
        'grades': {},
    }

    # 3. 申万行业泛化(用 load_index_data,同 9 指数口径)
    log(f"\n[sw] 加载 {len(SW_IIDS)} 个申万行业指数...")
    sw_dfs = {}
    for iid in SW_IIDS:
        df = load_index_data(iid)
        if df is not None:
            sw_dfs[iid] = df
    log(f"[sw] 成功加载 {len(sw_dfs)}/{len(SW_IIDS)} 个行业")

    for pid, bk, sk in pairs:
        per = {}
        for iid, df in sw_dfs.items():
            st = run_pair(df, bk, sk)
            per[iid] = st
        result['sw_industries'][pid] = {
            **summarize(per),
            'per_industry': {tid: (st['total_ret'] if st else None) for tid, st in per.items()},
        }
        s = result['sw_industries'][pid]
        log(f"  [sw] {pid:46s} valid={s['n_valid']:2d} mean={s['mean_ret']} median={s['median_ret']} "
            f"profit={s['profitable_pct']}%")

    # 4. 个股泛化
    log(f"\n[stock] 连接 stock_daily.db 抽样 {SAMPLE_STOCKS} 只个股...")
    scon = sqlite3.connect(STOCK_DB)
    codes = sample_stock_codes(scon, SAMPLE_STOCKS)
    log(f"[stock] 抽样: {codes}")

    stock_dfs = {}
    for code in codes:
        df = load_stock_series(scon, code)
        if df is not None:
            stock_dfs[code] = df
    scon.close()
    log(f"[stock] 成功加载 {len(stock_dfs)}/{len(codes)} 只")

    for pid, bk, sk in pairs:
        per = {}
        for code, df in stock_dfs.items():
            st = run_pair(df, bk, sk)
            per[code] = st
        result['stocks'][pid] = {
            **summarize(per),
            'per_stock': {tid: (st['total_ret'] if st else None) for tid, st in per.items()},
        }
        s = result['stocks'][pid]
        log(f"  [stock] {pid:46s} valid={s['n_valid']:2d} mean={s['mean_ret']} median={s['median_ret']} "
            f"profit={s['profitable_pct']}%")

    # 5. 额外:个股 Vol_breakout × 2 sell(指数无 vol 跑不了)
    log(f"\n[vol] 个股 Vol_breakout × (MACD_death, ATR_trail_stop)...")
    for sk in ['MACD_death', 'ATR_trail_stop']:
        per = {}
        for code, df in stock_dfs.items():
            st = run_pair(df, 'Vol_breakout', sk)
            per[code] = st
        pid = f'Vol_breakout|{sk}'
        result['vol_breakout_stocks'][pid] = {
            **summarize(per),
            'per_stock': {tid: (st['total_ret'] if st else None) for tid, st in per.items()},
        }
        s = result['vol_breakout_stocks'][pid]
        log(f"  [vol] {pid:46s} valid={s['n_valid']:2d} mean={s['mean_ret']} median={s['median_ret']} "
            f"profit={s['profitable_pct']}%")

    # 6. 泛化评级
    log(f"\n[grade] 泛化评级...")
    for pid, _, _ in pairs:
        sp = result['stocks'][pid].get('profitable_pct')
        wp = result['sw_industries'][pid].get('profitable_pct')
        g = grade(sp, wp)
        result['grades'][pid] = g
        log(f"  {pid:46s} stock_profit={sp}% sw_profit={wp}% -> {g}")

    # 写出
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, separators=(',', ':'))
    size_kb = os.path.getsize(OUT_JSON) / 1024
    log(f"\n[output] {OUT_JSON} ({size_kb:.1f} KB)")
    log(f"=== 泛化测试完成 ===")


if __name__ == '__main__':
    main()
