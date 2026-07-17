#!/usr/bin/env python3
"""§35 buy_aux（BB 下轨回归辅买点）独立回测脚本。

背景
----
- signal_stats.json 已含 g.cn10y buy_aux 前向统计（app/compute/signal_stats.py 基于
  生产 signal_daily 表已记录的信号日期算），前端 tips 显示。
- a-stock-data/backtest_metrics.py（公开项目，不可改）只覆盖 C1 主买（RSI 上穿）
  + 卖点参数网格，**未覆盖 buy_aux**。
- 本脚本补齐 buy_aux 回测：自复刻 signals.py 的 buy_aux 生成逻辑（BB 下轨回归 +
  C1 去重 + per-index filter），对全部 global 指标 / 情绪分跑参数网格，出胜率 /
  盈亏比 / 收益率，并与 C1 主买、signal_stats.json 生产统计对比。

约束
----
- 不动 a-stock-data/（公开项目）、不改 backtest_strategies.py。
- 自复刻 RSI / Bollinger（ddof=0，与 app/compute/signals.py 完全一致），不 import
  a-stock-data，保证脚本独立可移植。
- 数据源：data/sentiment.db（daily_metric / score_daily），只读。

信号定义（复刻 app/compute/signals.py）
---------------------------------------
- Bollinger: mid=close.rolling(20).mean(), sd=close.rolling(20).std(ddof=0),
  bu=mid+2σ, bl=mid-2σ。
- buy_aux 基线（B1）: 前一日 value<下轨 且 当日 value>下轨（从超卖回归）。
- buy_aux + rsi_cross_40: 基线 ∧ RSI(14) 上穿 40（前一日≤40 且 当日>40）。
- buy_aux + close_above_bl_2pct: 基线 ∧ 当日 value>下轨×1.02（反弹 2% 确认）。
- C1 主买（对比）: RSI(14) 上穿 30（前一日≤30 且 当日>30）。
- C1 与 buy_aux 同日去重：保留 C1 主买，buy_aux 去掉与 C1 同日的（与生产一致）。

收益统计
--------
- 百分比收益: fwd_pct = (value.shift(-h) / value - 1) * 100  （与 signal_stats.py 一致）
- 绝对值收益: fwd_abs = value.shift(-h) - value               （与 backtest_metrics.py 一致）
- 买信号正确 = 收益>0（涨）；胜率=wins/n；盈亏比=mean(|wins|)/mean(|losses|)。
- horizon = 5 / 10 / 20 交易日。

输出
----
- 控制台：cn10y 及各序列 buy_aux 最佳参数摘要 + 与 C1/signal_stats 对比。
- markdown 报告：/Users/linhuichen/code/trade/NOTES.md §35（由调用方追加，本脚本打印结论块）。
- JSON：/Users/linhuichen/code/trade/static-site/data/buy_aux_backtest.json（可推上线）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB = Path("/Users/linhuichen/code/trade/data/sentiment.db")
OUT_JSON = Path("/Users/linhuichen/code/trade/static-site/data/buy_aux_backtest.json")

# ---------- 序列分组（与 backtest_metrics.py / signal_stats.py 对齐） ----------
METRIC_IDS = [
    "cn10y", "us10y", "wti_oil", "brent", "comex_silver", "gold", "oil",
    "usdcnh", "a_qvix_300", "a_qvix_1000", "cn_us_spread",
]
SCORE_IDS = ["cross_market", "a_sentiment"]

HORIZONS = [5, 10, 20]
N_STD_GRID = [1.5, 2.0, 2.5]
FILTERS = ["none", "rsi_cross_40", "close_above_bl_2pct"]
MIN_N = 10  # 样本下限


# ---------- 核心算法（复刻 app/compute/signals.py，ddof=0） ----------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI(14)：EWM α=1/period, adjust=False。与 signals.py _rsi 一致。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def bollinger(close: pd.Series, window: int = 20, n_std: float = 2.0):
    """布林带：mid=MA(window), sd=std(ddof=0), bu=mid+n_std*sd, bl=mid-n_std*sd。
    与 signals.py _bollinger 一致。返回 (bu, mid, bl)。"""
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    bu = mid + n_std * sd
    bl = mid - n_std * sd
    return bu, mid, bl


def gen_buy_aux(value: pd.Series, n_std: float, filt: str) -> pd.Series:
    """生成 buy_aux 信号（BB 下轨回归 + 可选 filter）。返回 bool Series。"""
    _, _, bl = bollinger(value, 20, n_std)
    base = ((value.shift(1) < bl.shift(1)) & (value > bl)).fillna(False)
    if filt == "none":
        return base
    if filt == "rsi_cross_40":
        r = rsi(value, 14)
        cross40 = ((r.shift(1) <= 40) & (r > 40)).fillna(False)
        return base & cross40
    if filt == "close_above_bl_2pct":
        return base & (value > bl * 1.02)
    raise ValueError(f"unknown filter: {filt}")


def gen_c1_buy(value: pd.Series, x: float = 30.0) -> pd.Series:
    """C1 主买：RSI(14) 上穿 x（前一日≤x 且 当日>x）。"""
    r = rsi(value, 14)
    return ((r.shift(1) <= x) & (r > x)).fillna(False)


# ---------- 数据加载 ----------
def load_series(table: str, id_col: str, id_val: str) -> pd.Series:
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        f"SELECT date, value FROM {table} WHERE {id_col}=? ORDER BY date",
        conn, params=(id_val,),
    )
    conn.close()
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    s = df.set_index("date")["value"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def load_all() -> dict[str, pd.Series]:
    out = {}
    for m in METRIC_IDS:
        out[f"g.{m}"] = load_series("daily_metric", "metric_id", m)
    for s in SCORE_IDS:
        out[f"s.{s}"] = load_series("score_daily", "score_id", s)
    return out


# ---------- 统计 ----------
def stats_for(sig: pd.Series, value: pd.Series, horizons=HORIZONS) -> dict:
    """计算 buy 信号后 N 日收益统计（买正确=收益>0）。
    同时报百分比（pct，与 signal_stats 一致）和绝对值（abs，与 backtest_metrics 一致）。
    """
    sig_dates = sig[sig].index
    out = {}
    for h in horizons:
        fwd_pct = (value.shift(-h) / value - 1.0) * 100.0
        fwd_abs = value.shift(-h) - value
        p = fwd_pct.reindex(sig_dates).dropna()
        a = fwd_abs.reindex(sig_dates).dropna()
        n = len(p)
        if n == 0:
            out[f"{h}d"] = {"n": 0, "win_rate": None, "pl": None,
                            "mean_pct": None, "mean_abs": None}
            continue
        wins = p[p > 0]
        losses = p[p <= 0]
        win_rate = len(wins) / n
        mean_win = wins.abs().mean() if len(wins) else 0.0
        mean_loss = losses.abs().mean() if len(losses) else None
        pl = (mean_win / mean_loss) if (mean_loss is not None and mean_loss > 0) else None
        out[f"{h}d"] = {
            "n": n,
            "win_rate": round(win_rate, 4),
            "pl": round(pl, 4) if pl is not None else None,
            "mean_pct": round(float(p.mean()), 4),
            "mean_abs": round(float(a.mean()), 4),
        }
    return out


def composite(stats_h10: dict) -> float:
    """综合评分：胜率 × min(盈亏比,2)。样本<MIN_N 返回 NaN。"""
    if stats_h10["n"] < MIN_N:
        return np.nan
    pl = stats_h10["pl"] if stats_h10["pl"] is not None else 0
    return stats_h10["win_rate"] * min(pl, 2.0)


# ---------- 回测主循环 ----------
def backtest_series(name: str, value: pd.Series) -> dict:
    """对单序列回测 buy_aux 参数网格 + C1 主买对比。"""
    value = value.dropna()
    n_total = len(value)
    results = {
        "name": name, "n_total": n_total,
        "buy_aux": [],  # {n_std, filter, sig_count, stats, score}
        "c1_buy": None,  # C1 主买对比基线
    }

    # C1 主买（RSI 上穿 30）
    c1 = gen_c1_buy(value, 30.0)
    c1_dates = set(c1[c1].index)
    results["c1_buy"] = {
        "rule": "RSI上穿30 (C1主买)", "sig_count": int(c1.sum()),
        "stats": stats_for(c1, value),
    }

    # buy_aux 参数网格
    for n_std in N_STD_GRID:
        for filt in FILTERS:
            aux = gen_buy_aux(value, n_std, filt)
            # C1 去重：去掉与 C1 同日的（保留 C1 主买，与生产 signals.py 一致）
            aux_mask = aux & ~aux.index.to_series().isin(c1_dates)
            sc = int(aux_mask.sum())
            st = stats_for(aux_mask, value)
            results["buy_aux"].append({
                "n_std": n_std, "filter": filt, "sig_count": sc,
                "stats": st, "score": composite(st["10d"]),
            })
    return results


def pick_best(aux_list: list) -> dict | None:
    """选综合分最高的 buy_aux 参数；样本不足则按样本数选。"""
    valid = [r for r in aux_list if r["score"] == r["score"]]  # non-NaN
    if valid:
        return max(valid, key=lambda r: r["score"])
    nonzero = [r for r in aux_list if r["sig_count"] > 0]
    if nonzero:
        return max(nonzero, key=lambda r: r["sig_count"])
    return None


# ---------- 报告 ----------
def fmt(x, nd=4):
    if x is None:
        return "-"
    return f"{x:.{nd}f}"


def print_summary(results: dict, signal_stats: dict):
    """打印各序列 buy_aux 最佳参数 + 与 C1/signal_stats 对比。"""
    print("\n" + "=" * 92)
    print(f"{'序列':<16} {'最佳buy_aux参数':<28} {'n':>4} {'10d胜率':>8} {'10d盈亏比':>10} "
          f"{'C1胜率':>8} {'C1盈亏比':>9} {'生产10d胜率':>12}")
    print("-" * 92)
    for name, res in results.items():
        best = pick_best(res["buy_aux"])
        c1 = res["c1_buy"]["stats"]["10d"]
        # 生产 signal_stats 对比
        prod = signal_stats.get(name, {}).get("buy_aux", {}).get("10d", {})
        prod_wr = prod.get("win_rate")
        if best:
            s10 = best["stats"]["10d"]
            param = f"σ{best['n_std']}+{best['filter']}"
            print(f"{name:<16} {param:<28} {s10['n']:>4} {fmt(s10['win_rate']):>8} "
                  f"{fmt(s10['pl']):>10} {fmt(c1['win_rate']):>8} {fmt(c1['pl']):>9} "
                  f"{fmt(prod_wr):>12}")
        else:
            print(f"{name:<16} {'(无信号)':<28} {0:>4} {'-':>8} {'-':>10} "
                  f"{fmt(c1['win_rate']):>8} {fmt(c1['pl']):>9} {fmt(prod_wr):>12}")


def build_json(results: dict) -> dict:
    """构建上线 JSON：每序列 buy_aux 最佳参数 + C1 对比 + 全网格。"""
    out = {"_updated_at": pd.Timestamp.now().strftime("%Y%m%d_%H:%M"), "series": {}}
    for name, res in results.items():
        best = pick_best(res["buy_aux"])
        out["series"][name] = {
            "n_total": res["n_total"],
            "c1_buy": res["c1_buy"],
            "buy_aux_best": best,
            "buy_aux_grid": res["buy_aux"],
        }
    return out


def main():
    print("=== buy_aux（BB 下轨回归辅买点）回测 ===")
    print(f"DB: {DB}")
    all_series = load_all()
    print(f"加载 {len(all_series)} 个序列：{list(all_series.keys())}")

    # 生产 signal_stats 对比基线
    ss_path = Path("/Users/linhuichen/code/trade/data/signal_stats.json")
    signal_stats = json.loads(ss_path.read_text()) if ss_path.exists() else {}

    results = {}
    for name, s in all_series.items():
        if len(s) < 60:
            print(f"  跳过 {name}（样本不足 {len(s)}）")
            continue
        results[name] = backtest_series(name, s)

    print_summary(results, signal_stats)

    # cn10y 详细对比（验证复刻是否对齐生产 signal_stats）
    if "g.cn10y" in results:
        print("\n" + "=" * 92)
        print("【cn10y 详细】buy_aux 参数网格 vs C1 主买 vs 生产 signal_stats")
        print("-" * 92)
        cn = results["g.cn10y"]
        print(f"  C1 主买 (RSI上穿30): n={cn['c1_buy']['stats']['10d']['n']}, "
              f"10d 胜率={fmt(cn['c1_buy']['stats']['10d']['win_rate'])}, "
              f"盈亏比={fmt(cn['c1_buy']['stats']['10d']['pl'])}")
        prod = signal_stats.get("g.cn10y", {})
        for sig in ("buy", "buy_aux"):
            p = prod.get(sig, {}).get("10d", {})
            print(f"  生产 signal_stats {sig:8s}: n={p.get('n')}, "
                  f"10d 胜率={fmt(p.get('win_rate'))}, 盈亏比={fmt(p.get('pl'))}, "
                  f"均值={fmt(p.get('mean'))}")
        print("  --- buy_aux 参数网格（本脚本自生成信号）---")
        print(f"  {'参数':<26} {'n':>4} {'5d胜率':>8} {'5d盈亏比':>9} "
              f"{'10d胜率':>8} {'10d盈亏比':>10} {'20d胜率':>8} {'20d盈亏比':>9}")
        for r in sorted(cn["buy_aux"], key=lambda x: (x["n_std"], x["filter"])):
            s5, s10, s20 = r["stats"]["5d"], r["stats"]["10d"], r["stats"]["20d"]
            print(f"  σ{r['n_std']}+{r['filter']:<18} {s10['n']:>4} "
                  f"{fmt(s5['win_rate']):>8} {fmt(s5['pl']):>9} "
                  f"{fmt(s10['win_rate']):>8} {fmt(s10['pl']):>10} "
                  f"{fmt(s20['win_rate']):>8} {fmt(s20['pl']):>9}")

    # 写 JSON
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = build_json(results)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nJSON 已写: {OUT_JSON}")
    print("=== 完成 ===")


if __name__ == "__main__":
    main()
