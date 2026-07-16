"""买卖点配对回测：C1 买入 → 下一个 D1 卖出（或持有期上限止损）→ 算完整回合收益。

背景：外部验证报告 BUG-H 指出"分别看买/卖统计不够，缺'C1 买入 → 下一个 D1 卖出'的
完整回合回测（持有期收益/最大回撤/年化）"。本脚本补该缺口。

独立脚本，不 import app，自复刻 RSI(14) + D1 high-based 20 日回落 5%（与
app/compute/signals.py + a-stock-data/backtest_sell.py 一致）。

配对逻辑（按指数独立，按 date 升序遍历信号）：
  - 状态机 flat/holding。flat 遇 buy → 以 buy 日 close 入场（持有）；holding 遇 buy → 忽略
    （已持仓，不加仓不平仓）。
  - holding 遇 sell → 以 sell 日 close 出场，结算回合。
  - holding 超 MAX_HOLD 交易日 → 以当日 close 时间止损出场。
  - flat 遇 sell → 忽略（无仓位可卖）。
  - 数据结束仍 holding → 以最后日 close 强平（右截断，标注 unclosed）。

回合指标：持有期收益 %、持有天数、持有期最大回撤 %（盘内峰到谷，用 high/low）。
总体指标：回合数、均值/中位收益、胜率（收益>0）、平均持有天数、最大单回合回撤、
        年化（持有期复利 × 252/总持有天数）、累计复利。
对比：独立买点（C1 后 10 日）/ 独立卖点（D1 后 10 日，win=收益<0）/ 配对回合。

数据源：data/sentiment.db index_daily（13 主要指数，全历史）。
"""
import sqlite3
import sys
import numpy as np
import pandas as pd

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/10-买卖点配对回测.md'

INDICES = ['sh', 'sz', 'hs300', 'csi500', 'csi1000', 'cyb', 'kc50',
           'hsi', 'hscei', 'hstech', 'csi_div', 'div_lowvol', 'sz_div']

MAX_HOLD = 60          # 持有期上限（交易日），超时强平
CUTOFF_2016 = pd.Timestamp('2016-01-01')
TRADING_DAYS_PER_YEAR = 252


# ===================== 指标复刻（与 signals.py / backtest_sell.py 一致）=====================

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI（EWM α=1/period, adjust=False）。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def buy_signal(close: pd.Series) -> pd.Series:
    """C1 买点：RSI(14) 上穿 30（前一日 ≤30 且当日 >30）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    return ((rp <= 30) & (r > 30)).fillna(False)


def sell_signal(close: pd.Series, high: pd.Series) -> pd.Series:
    """D1 卖点：close 从近 20 日 high 之 max 回落 5%（high-based）。"""
    hh20 = high.rolling(20).max()
    thresh = hh20 * 0.95
    return ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)


# ===================== 数据加载 =====================

def load_ohl(iid: str) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close FROM index_daily "
        "WHERE index_id=? ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    return df.set_index('date').astype(float)


# ===================== 配对回合引擎 =====================

def pair_rounds(close: pd.Series, high: pd.Series, low: pd.Series,
                max_hold: int = MAX_HOLD):
    """返回回合列表 [(entry_date, exit_date, entry_close, exit_close, holding_days, max_dd_pct, exit_reason)]。

    exit_reason: 'sell' / 'time_stop' / 'end_of_data'

    配对逻辑（_scan_rounds）：遍历每个 C1 买点开仓 → 在 [entry+1, entry+max_hold] 内找第一个
    D1 卖点平仓；无则时间止损（entry+max_hold 处 close）；超出数据则 end_of_data 强平。
    跳过在前一回合持有期内的买点（不重入）。
    """
    buy = buy_signal(close)
    sell = sell_signal(close, high)
    return _scan_rounds(close, high, low, buy, sell, max_hold)


def _close_round(idx, closes, highs, lows, entry_i, exit_i, entry_close, exit_close, reason):
    holding_days = exit_i - entry_i
    # 持有期最大回撤（盘内峰到谷，含 entry 日，不含 exit 日——exit 日为出场点）
    # high/low 可能含 NaN（如 div_lowvol 649 行 NULL），用 nan-aware 算法跳过缺失日
    if exit_i > entry_i + 1:
        seg_high = highs[entry_i:exit_i]
        seg_low = lows[entry_i:exit_i]
        valid = ~(np.isnan(seg_high) | np.isnan(seg_low))
        if valid.any():
            sh = seg_high[valid]
            sl = seg_low[valid]
            peaks = np.maximum.accumulate(sh)
            drawdowns = (peaks - sl) / peaks
            max_dd = float(np.max(drawdowns)) * 100.0 if len(drawdowns) else 0.0
        else:
            max_dd = 0.0
    else:
        max_dd = 0.0
    return (idx[entry_i], idx[exit_i], entry_close, exit_close,
            holding_days, max_dd, reason)


def _scan_rounds(close, high, low, buy, sell, max_hold):
    """更稳健的配对：遍历每个 buy 信号，在 [entry+1, entry+max_hold] 内找第一个 sell；
    若无则时间止损（entry+max_hold 处 close）；若超出数据则 end_of_data。
    跳过在前一回合持有期内的 buy（不重入）。
    """
    idx = close.index
    closes = close.values
    highs = high.values
    lows = low.values
    n = len(closes)
    buy_idx = np.where(buy.values)[0]
    sell_idx = np.where(sell.values)[0]
    sell_set = set(sell_idx.tolist())

    rounds = []
    last_exit_i = -1  # 上一个回合出场 position，新开仓必须 > last_exit_i
    for bi in buy_idx:
        if bi <= last_exit_i:
            continue  # 该买点落在上一回合持有期内，跳过（不重入）
        entry_i = bi
        entry_close = float(closes[entry_i])
        # 在 (entry_i, entry_i+max_hold] 内找第一个 sell
        upper = min(entry_i + max_hold, n - 1)
        exit_i = None
        exit_reason = None
        for j in range(entry_i + 1, upper + 1):
            if j in sell_set:
                exit_i = j
                exit_reason = 'sell'
                break
        if exit_i is None:
            # 时间止损或数据结束
            if upper >= n - 1 and entry_i + max_hold >= n:
                exit_i = n - 1
                exit_reason = 'end_of_data'
            else:
                exit_i = upper  # entry_i + max_hold（时间止损）
                exit_reason = 'time_stop'
        exit_close = float(closes[exit_i])
        rounds.append(_close_round(idx, closes, highs, lows,
                                   entry_i, exit_i, entry_close, exit_close, exit_reason))
        last_exit_i = exit_i
    return rounds


# ===================== 统计工具 =====================

def forward_returns(close: pd.Series, sig_mask: pd.Series, horizon: int = 10):
    arr = close.values
    n = len(arr)
    out = []
    for pos in np.where(sig_mask.values)[0]:
        if pos + horizon < n:
            out.append((arr[pos + horizon] - arr[pos]) / arr[pos] * 100.0)
    return out


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_mean(x, nd=2):
    sign = "+" if (not np.isnan(x) and x > 0) else ""
    return f"{sign}{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_days(x, nd=1):
    return f"{x:.{nd}f}" if not np.isnan(x) else "-"


def aggregate(rounds):
    """回合列表 → 统计 dict。"""
    if not rounds:
        return {'n': 0}
    rets = np.array([(r[3] - r[2]) / r[2] * 100.0 for r in rounds], dtype=float)
    days = np.array([r[4] for r in rounds], dtype=float)
    dds = np.array([r[5] for r in rounds], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    pl = abs(avg_win) / abs(avg_loss) if avg_loss != 0 else float('nan')
    # 年化：持有期复利 × 252 / 总持有天数（仅持有期占用资金，忽略 flat 间隙）
    compound = float(np.prod(1 + rets / 100.0))
    total_days = float(days.sum())
    annualized = (compound ** (TRADING_DAYS_PER_YEAR / total_days) - 1) * 100.0 if total_days > 0 else float('nan')
    reasons = {}
    for r in rounds:
        reasons[r[6]] = reasons.get(r[6], 0) + 1
    return {
        'n': len(rounds),
        'mean_ret': float(rets.mean()),
        'median_ret': float(np.median(rets)),
        'win_rate': float(len(wins) / len(rets)),
        'pl_ratio': float(pl),
        'avg_days': float(days.mean()),
        'median_days': float(np.median(days)),
        'max_dd': float(np.nanmax(dds)) if len(dds) else 0.0,   # 最大单回合回撤（nan-aware，div_lowvol 等缺 high/low 不污染）
        'avg_dd': float(np.nanmean(dds)) if len(dds) else 0.0,
        'compound': compound,
        'annualized': annualized,
        'total_days': total_days,
        'reasons': reasons,
    }


def independent_stats(close, sig_mask, is_sell=False, horizon=10):
    """独立信号 forward N 日收益统计。卖点 win=收益<0。"""
    rets = forward_returns(close, sig_mask, horizon)
    if not rets:
        return {'n': 0}
    arr = np.array(rets, dtype=float)
    if is_sell:
        wins = arr[arr < 0]
        losses = arr[arr >= 0]
    else:
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
    avg_win = np.abs(wins).mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = avg_win / avg_loss if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    return {
        'n': len(arr),
        'mean': float(arr.mean()),
        'median': float(np.median(arr)),
        'win_rate': float(len(wins) / len(arr)),
        'pl': float(pl),
    }


# ===================== 主流程 =====================

def main():
    print("加载数据 + 计算信号...")
    data = {iid: load_ohl(iid) for iid in INDICES}
    max_date = max(d.index.max() for d in data.values())
    cutoff_1y = max_date - pd.Timedelta(days=365)
    cutoff_3y = max_date - pd.Timedelta(days=365 * 3)
    print(f"数据截止: {max_date.date()}  近1年>{cutoff_1y.date()}  近3年>{cutoff_3y.date()}")

    # 每指数配对回合
    all_rounds = {}     # iid -> list of rounds (full history)
    for iid in INDICES:
        df = data[iid]
        all_rounds[iid] = pair_rounds(df['close'], df['high'], df['low'], MAX_HOLD)
        print(f"  {iid:<10} 买/卖/回合: "
              f"{buy_signal(df['close']).sum()}/{sell_signal(df['close'], df['high']).sum()}/"
              f"{len(all_rounds[iid])}")

    # 窗口切分函数：回合 entry_date 落在窗口内
    def window_rounds(iid, lo=None):
        rs = all_rounds[iid]
        if lo is None:
            return rs
        return [r for r in rs if r[0] >= lo]

    # ===================== 生成报告 =====================
    L = []
    A = L.append
    A("# 买卖点配对回测报告（C1 买入 → 下一个 D1 卖出）\n")
    A(f"- 生成日期：2026-07-07（外部验证报告 BUG-H 修复）")
    A(f"- 数据截止：{max_date.date()}（数据源 sentiment.db index_daily）")
    A(f"- 标的：13 主要指数 ({', '.join(INDICES)})")
    A(f"- 买点 C1：RSI(14) 上穿 30（前一日 ≤30 且当日 >30，EWM α=1/14 adjust=False）")
    A(f"- 卖点 D1：close 从近 20 日 high 之 max 回落 5%（high-based，thresh=hh20×0.95）")
    A(f"- 持有期上限：{MAX_HOLD} 交易日（超时时间止损；与信号复刻 a-stock-data/backtest_sell.py 一致）")
    A(f"- 配对逻辑：每个 C1 买点开仓 → 持有至下一个 D1 卖点平仓；持有超 {MAX_HOLD} 日时间止损；数据结束右截断强平")
    A(f"- 回合收益 = (exit_close − entry_close) / entry_close × 100（不计交易成本/滑点）")
    A(f"- 持有期最大回撤 = 盘内峰(high)到谷(low)的最大跌幅（含入场日，不含出场日）")
    A(f"- 年化 = 持有期复利^(252/总持有天数) − 1（仅持有期占用资金，忽略 flat 间隙）")
    A(f"- 窗口：全史 / 2016+ / 近3年 / 近1年\n")

    # ---- 1. 总体对比：独立买 / 独立卖 / 配对回合 ----
    A("## 1. 总体对比：独立买点 vs 独立卖点 vs 配对回合（全史，13 指数汇总）\n")
    A("验证报告 BUG-H 核心：分别看买/卖统计不够，需看「买→卖」完整回合。下表对比三种视角。\n")
    A("| 视角 | 样本 | 胜率 | 盈亏比 | 均值收益 | 中位收益 | 周期 |")
    A("|---|---:|---:|---:|---:|---:|---|")

    # 独立买点（C1 后 10 日，win=收益>0）
    buy_rets_all = []
    sell_rets_all = []
    for iid in INDICES:
        df = data[iid]
        buy_rets_all.extend(forward_returns(df['close'], buy_signal(df['close']), 10))
        sell_rets_all.extend(forward_returns(df['close'], sell_signal(df['close'], df['high']), 10))
    buy_arr = np.array(buy_rets_all, dtype=float)
    sell_arr = np.array(sell_rets_all, dtype=float)
    buy_wins = buy_arr[buy_arr > 0]; buy_losses = buy_arr[buy_arr <= 0]
    sell_wins = sell_arr[sell_arr < 0]; sell_losses = sell_arr[sell_arr >= 0]
    buy_wr = len(buy_wins) / len(buy_arr) if len(buy_arr) else float('nan')
    sell_wr = len(sell_wins) / len(sell_arr) if len(sell_arr) else float('nan')
    buy_pl = abs(buy_wins.mean()) / abs(buy_losses.mean()) if len(buy_losses) and buy_losses.mean() != 0 else float('nan')
    sell_pl = abs(sell_wins.mean()) / abs(sell_losses.mean()) if len(sell_losses) and sell_losses.mean() != 0 else float('nan')
    A(f"| 独立买点（C1 后 10 日，win=涨） | {len(buy_arr)} | {fmt_pct(buy_wr*100)} | {buy_pl:.2f} | {fmt_mean(buy_arr.mean())} | {fmt_mean(np.median(buy_arr))} | 10 日 |")
    A(f"| 独立卖点（D1 后 10 日，win=跌） | {len(sell_arr)} | {fmt_pct(sell_wr*100)} | {sell_pl:.2f} | {fmt_mean(sell_arr.mean())} | {fmt_mean(np.median(sell_arr))} | 10 日 |")

    # 配对回合（全史）
    all_rs = [r for iid in INDICES for r in all_rounds[iid]]
    agg_all = aggregate(all_rs)
    A(f"| **配对回合（买→卖完整回合）** | {agg_all['n']} | {fmt_pct(agg_all['win_rate']*100)} | {agg_all['pl_ratio']:.2f} | {fmt_mean(agg_all['mean_ret'])} | {fmt_mean(agg_all['median_ret'])} | 均 {fmt_days(agg_all['avg_days'])} 日 |")
    A("")
    A(f"> **关键发现**：独立买点 C1 后 10 日均值 {fmt_mean(buy_arr.mean())}（胜率 {fmt_pct(buy_wr*100)}，正期望）；"
      f"独立卖点 D1 后 10 日均值 {fmt_mean(sell_arr.mean())}（胜率 {fmt_pct(sell_wr*100)}，接近随机）；"
      f"**配对回合均值 {fmt_mean(agg_all['mean_ret'])}、胜率 {fmt_pct(agg_all['win_rate']*100)}、年化 {fmt_mean(agg_all['annualized'])}**。"
      f"配对回合的真实收益由「买点正期望 − 卖点摩擦」决定，远低于独立买点的 10 日 forward 收益——独立 forward 收益不是可实现的策略收益。\n")

    # ---- 2. 各指数配对回合明细（全史）----
    A(f"## 2. 各指数配对回合明细（全史）\n")
    A("| 指数 | 回合数 | 胜率 | 盈亏比 | 均值收益 | 中位收益 | 平均持有(日) | 最大回撤 | 年化 | 平仓原因(sell/stop/eod) |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for iid in INDICES:
        g = aggregate(all_rounds[iid])
        if g['n'] == 0:
            A(f"| {iid} | 0 | - | - | - | - | - | - | - | - |")
            continue
        rs = g['reasons']
        reason_str = f"{rs.get('sell',0)}/{rs.get('time_stop',0)}/{rs.get('end_of_data',0)}"
        A(f"| {iid} | {g['n']} | {fmt_pct(g['win_rate']*100)} | {g['pl_ratio']:.2f} | "
          f"{fmt_mean(g['mean_ret'])} | {fmt_mean(g['median_ret'])} | {fmt_days(g['avg_days'])} | "
          f"{fmt_pct(g['max_dd'])} | {fmt_mean(g['annualized'])} | {reason_str} |")
    A("")
    A("> 平仓原因列：sell=D1 卖点平仓 / stop=持有超 {} 日时间止损 / eod=数据结束右截断强平。".format(MAX_HOLD))
    A("> 年化假设仅持有期占用资金（忽略 flat 间隙），未计交易成本/滑点/印花税。\n")

    # ---- 3. 窗口对比（2016+ / 近3年 / 近1年）----
    A("## 3. 配对回合窗口对比（13 指数汇总）\n")
    A("| 窗口 | 回合数 | 胜率 | 盈亏比 | 均值收益 | 中位收益 | 平均持有(日) | 最大回撤 | 年化 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    windows = [
        ('全史', None),
        ('2016+', CUTOFF_2016),
        ('近3年', cutoff_3y),
        ('近1年', cutoff_1y),
    ]
    for wname, lo in windows:
        rs = [r for iid in INDICES for r in window_rounds(iid, lo)]
        g = aggregate(rs)
        if g['n'] == 0:
            A(f"| {wname} | 0 | - | - | - | - | - | - | - |")
            continue
        A(f"| {wname} | {g['n']} | {fmt_pct(g['win_rate']*100)} | {g['pl_ratio']:.2f} | "
          f"{fmt_mean(g['mean_ret'])} | {fmt_mean(g['median_ret'])} | {fmt_days(g['avg_days'])} | "
          f"{fmt_pct(g['max_dd'])} | {fmt_mean(g['annualized'])} |")
    A("")

    # ---- 4. 持有期分布 ----
    A("## 4. 持有期分布与平仓方式（全史，13 指数汇总）\n")
    all_days = np.array([r[4] for r in all_rs], dtype=float)
    all_reasons = [r[6] for r in all_rs]
    A(f"- 回合数：{len(all_rs)}")
    A(f"- 持有天数：均值 {all_days.mean():.1f} / 中位 {np.median(all_days):.0f} / "
      f"P25 {np.percentile(all_days, 25):.0f} / P75 {np.percentile(all_days, 75):.0f} / "
      f"max {int(all_days.max())}")
    from collections import Counter
    rc = Counter(all_reasons)
    total = len(all_rs)
    A(f"- 平仓方式：D1 卖点 {rc.get('sell',0)} ({rc.get('sell',0)/total*100:.1f}%) / "
      f"时间止损 {rc.get('time_stop',0)} ({rc.get('time_stop',0)/total*100:.1f}%) / "
      f"数据结束 {rc.get('end_of_data',0)} ({rc.get('end_of_data',0)/total*100:.1f}%)")
    # 卖点平仓 vs 时间止损 收益对比
    sell_rets = [(r[3]-r[2])/r[2]*100 for r in all_rs if r[6]=='sell']
    stop_rets = [(r[3]-r[2])/r[2]*100 for r in all_rs if r[6]=='time_stop']
    if sell_rets:
        sa = np.array(sell_rets)
        A(f"- D1 卖点平仓回合：n={len(sa)} / 均值 {fmt_mean(sa.mean())} / 胜率 {fmt_pct((sa>0).mean()*100)} / 平均持有 {np.mean([r[4] for r in all_rs if r[6]=='sell']):.1f} 日")
    if stop_rets:
        sa = np.array(stop_rets)
        A(f"- 时间止损回合：n={len(sa)} / 均值 {fmt_mean(sa.mean())} / 胜率 {fmt_pct((sa>0).mean()*100)} / 平均持有 {np.mean([r[4] for r in all_rs if r[6]=='time_stop']):.1f} 日")
    A("")

    # ---- 5. 买→卖 vs 买→持有的对照 ----
    A("## 5. 配对策略 vs 买入持有基准（全史，13 指数汇总）\n")
    # 买入持有：每个指数首日 close → 末日 close 年化
    bh_anns = []
    for iid in INDICES:
        df = data[iid]
        if len(df) < 30:
            continue
        c0, c1 = float(df['close'].iloc[0]), float(df['close'].iloc[-1])
        ndays = len(df)
        bh_ann = (c1 / c0) ** (TRADING_DAYS_PER_YEAR / ndays) - 1
        bh_anns.append(bh_ann * 100)
    bh_arr = np.array(bh_anns)
    A(f"- 买入持有年化（各指数等权平均）：{bh_arr.mean():.2f}%（中位 {np.median(bh_arr):.2f}%，范围 {bh_arr.min():.2f}%~{bh_arr.max():.2f}%）")
    A(f"- 配对回合年化（持有期复利）：{fmt_mean(agg_all['annualized'])}")
    A(f"- 配对回合累计复利（仅持有期）：{(agg_all['compound']-1)*100:.2f}%")
    A("")
    A("> 注：买入持有是「全程满仓」，配对回合是「仅持有期在场」。两者年化口径不同——"
      "配对年化假设资金只在持有期占用（忽略 flat 间隙），若按全程资金占用计算，配对年化会显著低于上表。"
      "故该对比仅作「信号能否跑赢单纯持有」的定性参考，非严格策略对比。\n")

    # ---- 6. 结论 ----
    A("## 6. 结论\n")
    A(f"1. **买点 C1 是正向 alpha 来源**：独立买点后 10 日均值 {fmt_mean(buy_arr.mean())}、胜率 {fmt_pct(buy_wr*100)}，"
      f"呈轻度均值回归正期望，与验证报告 6.4 节（均值 +1.62% / 胜率 61.8%）一致方向。")
    A(f"2. **卖点 D1 接近随机**：独立卖点后 10 日均值 {fmt_mean(sell_arr.mean())}、胜率 {fmt_pct(sell_wr*100)}（win=跌），"
      f"印证「D1 是止盈减仓提示非高胜率卖点」的定位（详见 REQUIREMENTS.md §7.2、ruleBar 文案）。")
    A(f"3. **配对回合收益远低于独立买点 forward 收益**：配对均值 {fmt_mean(agg_all['mean_ret'])} / 胜率 {fmt_pct(agg_all['win_rate']*100)} / 年化 {fmt_mean(agg_all['annualized'])}。"
      f"原因：① 持有至 D1 卖点常意味着「等到趋势转弱才走」，回吐部分买点浮盈（D1 平仓回合均值见下节）；② 独立 forward 收益含「持有满 10 日不管信号」，不是可实现策略；③ 配对回合混合了「D1 平仓（弱）」与「时间止损（强）」两类，整体均值被 D1 平仓回合拉低。")
    A(f"4. **持有期分布与平仓方式分化显著**：平均持有 {fmt_days(agg_all['avg_days'])} 日，D1 卖点平仓 {rc.get('sell',0)/total*100:.1f}% / 时间止损 {rc.get('time_stop',0)/total*100:.1f}%。"
      f"**关键分化**：D1 卖点平仓回合均值 {fmt_mean(np.mean(sell_rets) if sell_rets else float('nan'))} / 胜率 {fmt_pct((np.array(sell_rets)>0).mean()*100 if sell_rets else 0)}（弱——趋势转弱已回吐浮盈）；"
      f"时间止损回合均值 {fmt_mean(np.mean(stop_rets) if stop_rets else float('nan'))} / 胜率 {fmt_pct((np.array(stop_rets)>0).mean()*100 if stop_rets else 0)}（强——趋势持续未触发 D1，持有满上限兑现大段涨幅）。"
      f"即：策略收益主要由「未触发 D1 的强势回合」贡献，D1 卖点的作用是「在转弱时止损/止盈避免更大亏损」而非「抓住赢家」。")
    A(f"5. **回撤风险**：最大单回合回撤 {fmt_pct(agg_all['max_dd'])}，平均回撤 {fmt_pct(agg_all['avg_dd'])}。"
      f"配对策略的回撤主要来自「持有期内的盘中波动」，D1 卖点的反应型特性使其无法避开日内深调。")
    A(f"6. **定位建议**：买点 C1 可作「超卖拐点提示」轻度参考；卖点 D1 不可作为独立卖出指令（胜率≈随机），"
      f"配对策略整体年化 {fmt_mean(agg_all['annualized'])} 不可作「稳赚策略」宣传。本回测诚实呈现配对结果，"
      f"供用户审慎参考，非投资建议。详见 `07-卖点对策回测.md`（独立卖点 12 方案对比）+ `09-指标买卖点回测.md`。\n")
    A("---")
    A(f"\n**方法学坦白**：① 未计交易成本（指数级影响小，扩展到个股须扣印花税+佣金+冲击成本）；"
      f"② 幸存者偏差（用现存主要指数，未含已退市/改规则标的）；"
      f"③ 时间止损上限 {MAX_HOLD} 日为人为设定，调小会提高换手降低单回合收益、调大会增加回撤；"
      f"④ 持有期最大回撤用 high/low 算盘内峰谷（保守估计，比 close-to-close 大）；"
      f"⑤ 年化口径「仅持有期占用资金」会高估全程资金回报率，按全程占用计算应乘以持仓时间占比。")

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))

    # ===================== 控制台汇总 =====================
    print("=" * 90)
    print(f"{'指数':<10} {'回合':>4} {'胜率':>6} {'盈亏比':>6} {'均值':>7} {'中位':>7} {'持有日':>6} {'最大回撤':>8} {'年化':>7}")
    print("-" * 90)
    for iid in INDICES:
        g = aggregate(all_rounds[iid])
        if g['n'] == 0:
            print(f"{iid:<10} {'0':>4} {'-':>6} {'-':>6} {'-':>7} {'-':>7} {'-':>6} {'-':>8} {'-':>7}")
            continue
        print(f"{iid:<10} {g['n']:>4} {fmt_pct(g['win_rate']*100):>6} {g['pl_ratio']:>6.2f} "
              f"{fmt_mean(g['mean_ret']):>7} {fmt_mean(g['median_ret']):>7} "
              f"{fmt_days(g['avg_days']):>6} {fmt_pct(g['max_dd']):>8} {fmt_mean(g['annualized']):>7}")
    print("-" * 90)
    print(f"{'总体':<10} {agg_all['n']:>4} {fmt_pct(agg_all['win_rate']*100):>6} {agg_all['pl_ratio']:>6.2f} "
          f"{fmt_mean(agg_all['mean_ret']):>7} {fmt_mean(agg_all['median_ret']):>7} "
          f"{fmt_days(agg_all['avg_days']):>6} {fmt_pct(agg_all['max_dd']):>8} {fmt_mean(agg_all['annualized']):>7}")
    print("=" * 90)
    print(f"独立买点(C1,10d): n={len(buy_arr)} 胜率={fmt_pct(buy_wr*100)} 均值={fmt_mean(buy_arr.mean())}")
    print(f"独立卖点(D1,10d): n={len(sell_arr)} 胜率={fmt_pct(sell_wr*100)} 均值={fmt_mean(sell_arr.mean())}")
    print(f"报告已写入: {REPORT}")


if __name__ == '__main__':
    main()
