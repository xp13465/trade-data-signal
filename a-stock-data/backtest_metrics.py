#!/usr/bin/env python3
"""独立回测脚本：全球指标 + 情绪分数 买卖点规则回测。

不 import app，自复刻 RSI（period=14, EWM α=1/14, adjust=False，与
app/compute/signals.py `_rsi` 完全一致）。

数据源：data/sentiment.db
  - daily_metric (global 组): cn10y/us10y/wti_oil/comex_silver/gold/oil/
    usdcnh/a_qvix_300/a_qvix_1000/cn_us_spread
  - score_daily: cross_market / a_sentiment

规则（基于 value，无 high/low/open/close）：
  买点: RSI(value,14) 上穿 X (X ∈ {25,30,35})  —— 超卖反弹事件化
  卖点 A: value 从近 20 日最高回落 N% (N ∈ {3,5,8})  —— 仅适用 value 恒正序列
  卖点 B: value 从近 20 日最高回落 k×std(20) (k ∈ {1.5,2.0,2.5})  —— 适用全部序列
         (cn_us_spread 含负数，% 回落无意义，只用 std 规则)

信号后收益：信号日 value vs N 交易日后 value 的 raw 变化 (value_{t+N}-value_t)。
  买点正确 = 变化>0 (涨)；卖点正确 = 变化<0 (跌)。
  胜率 = 正确数/样本；盈亏比 = 平均盈利/平均亏损(绝对值)。

输出：
  - 控制台打印各序列最佳规则摘要
  - 写 markdown 报告到 /Users/linhuichen/code/trade/09-指标买卖点回测.md
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB = Path("/Users/linhuichen/code/trade/data/sentiment.db")
REPORT = Path("/Users/linhuichen/code/trade/09-指标买卖点回测.md")

# 序列分组（与 cfg["indices"] 区分：这些是 global 组指标 + 综合分）
METRIC_IDS = [
    "cn10y", "us10y", "wti_oil", "comex_silver", "gold", "oil",
    "usdcnh", "a_qvix_300", "a_qvix_1000", "cn_us_spread",
]
SCORE_IDS = ["cross_market", "a_sentiment"]

# 序列语义备注（量级 / 是否含负数 / 单位）
META = {
    "cn10y":         ("收益率%",    False, "中国10年国债收益率，百分点"),
    "us10y":         ("收益率%",    False, "美国10年国债收益率，百分点"),
    "wti_oil":       ("价格$",      False, "WTI原油价格"),
    "comex_silver":  ("价格$",      False, "COMEX白银价格"),
    "gold":          ("价格$",      False, "黄金价格"),
    "oil":           ("指数",       False, "原油指数(布伦特系)"),
    "usdcnh":        ("汇率×100",   False, "离岸人民币汇率×100，窄幅680-722"),
    "a_qvix_300":    ("波动率指数", False, "A股300波动率指数"),
    "a_qvix_1000":   ("波动率指数", False, "A股1000波动率指数"),
    "cn_us_spread":  ("利差百分点", True,  "cn10y-us10y，可正可负"),
    "cross_market":  ("情绪分0-100", False, "跨市场综合情绪分"),
    "a_sentiment":   ("情绪分0-100", False, "A股情绪分"),
}

BUY_THRESHOLDS = [25, 30, 35]
SELL_PCT = [3, 5, 8]
SELL_STD = [1.5, 2.0, 2.5]
HORIZONS = [5, 10, 20]
MIN_N = 10  # 样本下限，低于此标记"样本不足"


# ---------- 核心算法（复刻 signals.py _rsi） ----------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI(14)：EWM α=1/period, adjust=False。与 app/compute/signals.py 一致。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


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
    # 去重（以防万一）
    return s[~s.index.duplicated(keep="last")]


def load_all() -> dict[str, pd.Series]:
    out = {}
    for m in METRIC_IDS:
        out[m] = load_series("daily_metric", "metric_id", m)
    for s in SCORE_IDS:
        out[s] = load_series("score_daily", "score_id", s)
    return out


# ---------- 信号生成 ----------
def buy_signals(value: pd.Series, x: float) -> pd.Series:
    """买点：RSI(14) 上穿 X（前一日≤X 且 当日>X）。事件化，fillna(False)。"""
    r = rsi(value, 14)
    rp = r.shift(1)
    sig = ((rp <= x) & (r > x)).fillna(False)
    return sig


def sell_signals_pct(value: pd.Series, pct: float) -> pd.Series:
    """卖点 A：value 从近 20 日最高回落 N%。
    thresh = hh20 * (1 - pct/100)；触发 = prev>=thresh_prev 且 curr<thresh。
    仅适用 value 恒正序列（调用方负责判断）。
    """
    hh20 = value.rolling(20).max()
    thresh = hh20 * (1 - pct / 100.0)
    sig = ((value.shift(1) >= thresh.shift(1)) & (value < thresh)).fillna(False)
    return sig


def sell_signals_std(value: pd.Series, k: float) -> pd.Series:
    """卖点 B：value 从近 20 日最高回落 k×std(20)。
    thresh = hh20 - k*rolling_std(20)；触发同上。适用全部序列（含负数）。
    """
    hh20 = value.rolling(20).max()
    std20 = value.rolling(20).std()
    thresh = hh20 - k * std20
    sig = ((value.shift(1) >= thresh.shift(1)) & (value < thresh)).fillna(False)
    return sig


# ---------- 统计 ----------
def stats_for(sig: pd.Series, value: pd.Series, direction: str,
             horizons=HORIZONS) -> dict:
    """计算信号后 N 日收益统计。
    direction='buy': 正确=fwd>0 (涨)；'sell': 正确=fwd<0 (跌)。
    返回 {h: {n, win, plr, mean}} —— mean 为方向调整后的均值(>0=平均正确)。
    """
    sig_dates = sig[sig].index
    out = {}
    for h in horizons:
        fwd = (value.shift(-h) - value).reindex(sig_dates).dropna()
        if direction == "sell":
            fwd = -fwd  # 翻转：卖点正确(跌) → fwd>0
        n = len(fwd)
        if n == 0:
            out[h] = {"n": 0, "win": np.nan, "plr": np.nan, "mean": np.nan}
            continue
        wins = fwd[fwd > 0]
        losses = fwd[fwd <= 0]
        win_rate = len(wins) / n
        avg_gain = wins.mean() if len(wins) else np.nan
        avg_loss = -losses.mean() if len(losses) else np.nan
        if pd.notna(avg_gain) and pd.notna(avg_loss) and avg_loss > 0:
            plr = avg_gain / avg_loss
        else:
            plr = np.nan
        out[h] = {"n": n, "win": win_rate, "plr": plr, "mean": fwd.mean()}
    return out


def fmt_pct(x):
    return f"{x*100:.1f}%" if pd.notna(x) else "—"


def fmt_plr(x):
    return f"{x:.2f}" if pd.notna(x) else "—"


def fmt_mean(x):
    # 保留 3 位有效，单位为序列原生单位
    if not pd.notna(x):
        return "—"
    if abs(x) >= 100:
        return f"{x:+.1f}"
    if abs(x) >= 1:
        return f"{x:+.2f}"
    return f"{x:+.3f}"


def composite(stats_h10):
    """综合评分：胜率 × min(盈亏比,2)。要求样本>=MIN_N 才返回有效分。"""
    s = stats_h10
    if s["n"] < MIN_N:
        return np.nan
    plr = s["plr"] if pd.notna(s["plr"]) else 0
    return s["win"] * min(plr, 2.0)


# ---------- 回测主循环 ----------
def backtest_series(name: str, value: pd.Series) -> dict:
    """对单序列回测所有规则，返回结果 dict。"""
    value = value.dropna()
    has_negative = (value.min() <= 0)
    n_total = len(value)

    results = {
        "name": name,
        "n_total": n_total,
        "has_negative": has_negative,
        "buy": [],   # list of {rule, sig_count, stats{5,10,20}}
        "sell_pct": [],
        "sell_std": [],
    }

    # 买点
    for x in BUY_THRESHOLDS:
        sig = buy_signals(value, x)
        sc = int(sig.sum())
        st = stats_for(sig, value, "buy")
        results["buy"].append({
            "rule": f"RSI上穿{x}", "x": x, "sig_count": sc, "stats": st,
        })

    # 卖点 A (% 回落) —— 仅 value 恒正序列
    if not has_negative:
        for p in SELL_PCT:
            sig = sell_signals_pct(value, p)
            sc = int(sig.sum())
            st = stats_for(sig, value, "sell")
            results["sell_pct"].append({
                "rule": f"20日高回落{p}%", "p": p, "sig_count": sc, "stats": st,
            })

    # 卖点 B (std 回落) —— 全部序列
    for k in SELL_STD:
        sig = sell_signals_std(value, k)
        sc = int(sig.sum())
        st = stats_for(sig, value, "sell")
        results["sell_std"].append({
            "rule": f"20日高回落{k}σ", "k": k, "sig_count": sc, "stats": st,
        })

    return results


def pick_best(rule_list):
    """选综合分最高的规则；返回 (rule_dict, score, note)。
    优先在样本数>=MIN_N 的规则中选综合分最高；
    若全部样本不足但有非零信号，按样本数选；
    若全部 0 信号（如 a_sentiment 买规则），标注"规则无效"。
    """
    # 全部 0 信号 → 规则在序列上无效（如 RSI 结构性不达阈值）
    if all(r["sig_count"] == 0 for r in rule_list):
        return rule_list[0], np.nan, "规则无效(0信号)"
    best = None
    best_score = -1
    for r in rule_list:
        sc = composite(r["stats"][10])
        if pd.notna(sc) and sc > best_score:
            best_score = sc
            best = r
    if best is None:
        # 全部样本不足，退而选样本最多的
        best = max(rule_list, key=lambda r: r["sig_count"])
        return best, np.nan, "样本不足，按样本数选"
    return best, best_score, None


# ---------- 报告生成 ----------
def build_report(all_data: dict, all_results: dict) -> str:
    lines = []
    lines.append("# 09 全球指标 + 情绪分数 买卖点规则回测\n")
    lines.append("> 独立回测脚本 `a-stock-data/backtest_metrics.py` 生成。"
                 "RSI 复刻 `app/compute/signals.py _rsi` (period=14, EWM α=1/14, adjust=False)。"
                 "不改 app 代码。\n")

    # §1 序列概览
    lines.append("## 1. 序列概览（value 范围 + 量级）\n")
    lines.append("| 序列 | 类型 | 含负数 | 样本数 | min | max | mean | 起始 | 结束 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for name in METRIC_IDS + SCORE_IDS:
        v = all_data[name]
        scale, has_neg, note = META[name]
        if len(v) == 0:
            lines.append(f"| {name} | {scale} | — | 0 | — | — | — | — | — | {note} |")
            continue
        lines.append(
            f"| {name} | {scale} | {'是' if v.min()<=0 else '否'} | {len(v)} | "
            f"{v.min():.4g} | {v.max():.4g} | {v.mean():.4g} | "
            f"{v.index[0].strftime('%Y-%m-%d')} | {v.index[-1].strftime('%Y-%m-%d')} | {note} |"
        )
    lines.append("")
    lines.append("量级分布：价格类(gold/silver/wti_oil/oil) 10-1250；收益率%(cn10y/us10y) 0.5-5；"
                 "波动率指数(a_qvix) 12-46；汇率×100(usdcnh) 680-722 窄幅；"
                 "利差(cn_us_spread) -3.14~2.49 **含负数**（% 回落不适用）；"
                 "情绪分(cross_market/a_sentiment) 0-100。\n")

    # §2 各序列回测结果
    lines.append("## 2. 各序列回测结果\n")
    lines.append("统计口径：信号日 value vs N 交易日后 value 的 raw 变化。"
                 "买点正确=涨；卖点正确=跌。胜率=正确数/样本；"
                 "盈亏比=平均盈利/平均亏损(绝对值)；mean=方向调整后均值(>0=平均正确)。"
                 "样本<%d 标记 †（不足）。\n" % MIN_N)

    summary_rows = []  # for §3

    for name in METRIC_IDS + SCORE_IDS:
        res = all_results[name]
        v = all_data[name]
        if len(v) == 0:
            lines.append(f"### {name}\n（无数据）\n")
            continue
        lines.append(f"### {name}  （样本 {res['n_total']}，"
                     f"{'含负数' if res['has_negative'] else '恒正'}）\n")

        # 买点表
        lines.append("**买点（RSI 上穿 X）**\n")
        lines.append("| 规则 | 信号数 | 5日胜率 | 5日盈亏比 | 10日胜率 | 10日盈亏比 | 20日胜率 | 20日盈亏比 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in res["buy"]:
            s = r["stats"]
            mark = "†" if s[10]["n"] < MIN_N else ""
            lines.append(
                f"| {r['rule']} | {r['sig_count']}{mark} | "
                f"{fmt_pct(s[5]['win'])} | {fmt_plr(s[5]['plr'])} | "
                f"{fmt_pct(s[10]['win'])} | {fmt_plr(s[10]['plr'])} | "
                f"{fmt_pct(s[20]['win'])} | {fmt_plr(s[20]['plr'])} |"
            )
        lines.append("")

        # 卖点 A (% 回落)
        if res["sell_pct"]:
            lines.append("**卖点 A（20日高回落 N%，仅恒正序列）**\n")
            lines.append("| 规则 | 信号数 | 5日胜率 | 5日盈亏比 | 10日胜率 | 10日盈亏比 | 20日胜率 | 20日盈亏比 |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for r in res["sell_pct"]:
                s = r["stats"]
                mark = "†" if s[10]["n"] < MIN_N else ""
                lines.append(
                    f"| {r['rule']} | {r['sig_count']}{mark} | "
                    f"{fmt_pct(s[5]['win'])} | {fmt_plr(s[5]['plr'])} | "
                    f"{fmt_pct(s[10]['win'])} | {fmt_plr(s[10]['plr'])} | "
                    f"{fmt_pct(s[20]['win'])} | {fmt_plr(s[20]['plr'])} |"
                )
            lines.append("")
        else:
            lines.append("**卖点 A（% 回落）：N/A（序列含负数，% 回落无意义）**\n")

        # 卖点 B (std 回落)
        lines.append("**卖点 B（20日高回落 kσ，适用全部序列）**\n")
        lines.append("| 规则 | 信号数 | 5日胜率 | 5日盈亏比 | 10日胜率 | 10日盈亏比 | 20日胜率 | 20日盈亏比 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in res["sell_std"]:
            s = r["stats"]
            mark = "†" if s[10]["n"] < MIN_N else ""
            lines.append(
                f"| {r['rule']} | {r['sig_count']}{mark} | "
                f"{fmt_pct(s[5]['win'])} | {fmt_plr(s[5]['plr'])} | "
                f"{fmt_pct(s[10]['win'])} | {fmt_plr(s[10]['plr'])} | "
                f"{fmt_pct(s[20]['win'])} | {fmt_plr(s[20]['plr'])} |"
            )
        lines.append("")

        # 选最佳
        best_buy, buy_score, buy_note = pick_best(res["buy"])
        sell_pool = res["sell_pct"] + res["sell_std"]
        best_sell, sell_score, sell_note = pick_best(sell_pool)
        summary_rows.append({
            "name": name, "best_buy": best_buy, "buy_score": buy_score,
            "buy_note": buy_note,
            "best_sell": best_sell, "sell_score": sell_score,
            "sell_note": sell_note,
        })

    # §3 推荐
    lines.append("## 3. 推荐规则（数据驱动）\n")
    lines.append("评选口径：在样本数≥%d 的规则中，综合分 = 10日胜率 × min(10日盈亏比, 2.0)，"
                 "取最高。买/卖各选一条。所有规则均样本不足时按样本数选并标注。\n" % MIN_N)
    lines.append("| 序列 | 推荐买点 | 买点信号数 | 买10日胜率 | 买10日盈亏比 | 推荐卖点 | 卖点信号数 | 卖10日胜率 | 卖10日盈亏比 | 备注 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in summary_rows:
        b = row["best_buy"]; s = row["best_sell"]
        bs = b["stats"][10]; ss = s["stats"][10]
        note = ""
        if row["buy_note"]:
            note += "买:" + row["buy_note"] + " "
        if row["sell_note"]:
            note += "卖:" + row["sell_note"]
        lines.append(
            f"| {row['name']} | {b['rule']} | {b['sig_count']} | "
            f"{fmt_pct(bs['win'])} | {fmt_plr(bs['plr'])} | "
            f"{s['rule']} | {s['sig_count']} | "
            f"{fmt_pct(ss['win'])} | {fmt_plr(ss['plr'])} | {note.strip()} |"
        )
    lines.append("")

    # 落地建议
    lines.append("## 4. 落地建议（signals.py 扩展方式）\n")
    lines.append("### 4.1 扩展范围\n")
    lines.append("当前 `compute()` 只遍历 `cfg['indices']`（指数，有 close/high）。"
                 "扩展为 additionally 遍历：\n")
    lines.append("- `cfg['metrics']` 中 `group='global'` 的指标（daily_metric 表）："
                 "cn10y/us10y/wti_oil/comex_silver/gold/oil/usdcnh/a_qvix_300/a_qvix_1000/cn_us_spread；\n")
    lines.append("- `score_daily` 表的 cross_market / a_sentiment。\n")
    lines.append("这些序列只有 value（无 high/low/open/close），用下面适配规则。\n")

    lines.append("### 4.2 适配规则\n")
    lines.append("```python\n")
    lines.append("# 买点（与指数 C1 一致，value 当 close 用）\n")
    lines.append("rsi = _rsi(value, 14)\n")
    lines.append("buy = ((rsi.shift(1) <= 30) & (rsi > 30)).fillna(False)\n")
    lines.append("\n")
    lines.append("# 卖点（value 无 high，用 value 自身 rolling max 作 hh20）\n")
    lines.append("# 恒正序列：用 % 回落（与指数 D1 一致，thresh = hh20*0.95）\n")
    lines.append("# 含负数序列(cn_us_spread)：用 std 回落 thresh = hh20 - k*std(20)\n")
    lines.append("hh20 = value.rolling(20).max()\n")
    lines.append("if value.min() > 0:\n")
    lines.append("    thresh = hh20 * 0.95            # 20日高回落5%\n")
    lines.append("else:\n")
    lines.append("    std20 = value.rolling(20).std()\n")
    lines.append("    thresh = hh20 - 2.0 * std20     # 20日高回落2σ\n")
    lines.append("sell = ((value.shift(1) >= thresh.shift(1)) & (value < thresh)).fillna(False)\n")
    lines.append("```\n")
    lines.append("注：买点阈值默认 30（与指数 C1 一致）。卖点恒正用 5%（与指数 D1 一致），"
                 "含负数用 2σ。具体阈值可按本回测 §3 推荐表逐序列调优，但为保持代码简洁建议先统一默认，"
                 "再按需覆盖。\n")

    lines.append("### 4.3 落地注意事项\n")
    lines.append("1. **value 当 close**：RSI 与 hh20 都直接用 value 序列，无需 high。"
                 "signals.py 现有 `_rsi` 可直接复用，无需改算法。\n")
    lines.append("2. **cn_us_spread 含负数**：% 回落会失效（hh20 可能 <0，乘 0.95 反而升高），"
                 "必须走 std 分支。落地时按 `value.min()>0` 判断分支即可。\n")
    lines.append("3. **usdcnh 窄幅（680-722）**：% 回落 5% ≈ 35 点，触发可能偏少；"
                 "若信号不足可改 std 规则（回测见 §2）。\n")
    lines.append("4. **score_daily 0-100 情绪分**：RSI 上穿 30 = 情绪分动量触底反弹（情绪修复信号）。"
                 "语义上 RSI 量化的是 score 的动量，而非 score 本身高低；可作为情绪转折提示。\n")
    lines.append("5. **信号存储**：现有 `signal_daily` 表 (date, index_id, signal, reason)。"
                 "扩展时 index_id 字段可复用为 metric_id/score_id（如 'g.cn10y' / 's.cross_market'），"
                 "或新增 `kind` 列区分 index/metric/score。前者改动小，前端按前缀过滤即可。\n")
    lines.append("6. **cfg 扩展**：在 config.yaml 的 metrics 项里加 `signals: true` 开关，"
                 "compute() 据此决定是否对 metric 算信号；score_daily 默认开启。\n")
    lines.append("7. **方案 B vs前买 标注**：value 序列同样维护 last_buy_value 游标，"
                 "卖点 reason 附 `vs前买{±X.XX%}[止盈/买点失败]`。pct = (value-last_buy_value)/|last_buy_value|，"
                 "用绝对值作分母以兼容负数序列。\n")

    lines.append("### 4.4 风险提示\n")
    lines.append("- 卖点胜率普遍难超 50%（与指数 D1 一致，signals.py 注释已说明），"
                 "value 序列同此规律。卖点定位为止盈/转弱提示，非做空信号。\n")
    lines.append("- **a_sentiment 买规则失效（重要）**：a_sentiment 是高度平滑的复合情绪分，"
                 "其 RSI(14) 结构性 ≥40（实测 min=39.99，std 仅 3.73，长期贴 50 中枢），"
                 "RSI 上穿 25/30/35 全部产生 **0 个买信号**。cross_market 同为 0-100 情绪分但"
                 "波动更原始（RSI min=19.5，153 次 <35），买规则正常。**a_sentiment 不适用 RSI 买规则**，"
                 "若需买点建议改用 value 本身阈值（如 value<20 后反弹）或直接复用 cross_market 买信号。\n")
    lines.append("- 情绪分(cross_market/a_sentiment)样本长(2008+)但语义特殊，"
                 "RSI 上穿 30 量化的是 score 动量而非 score 高低，落地后需观察信号频率与语义匹配度。\n")
    lines.append("- a_qvix_1000 样本仅 807 行（2022 起），回测统计置信度偏低，标记 †。\n")
    lines.append("- usdcnh 窄幅（680-722）致 % 回落 3/5/8% 全部 0 信号（5%≈35 点超出全程波幅），"
                 "买规则胜率也偏低（28.6%），RSI 在窄幅序列上噪声大。usdcnh 建议仅用 std 卖规则，买规则慎用。\n")

    return "\n".join(lines) + "\n"


def main():
    print("加载数据...")
    all_data = load_all()
    for name, s in all_data.items():
        print(f"  {name}: {len(s)} rows, range [{s.min():.4g}, {s.max():.4g}]"
              if len(s) else f"  {name}: EMPTY")

    print("\n回测各序列...")
    all_results = {}
    for name in METRIC_IDS + SCORE_IDS:
        all_results[name] = backtest_series(name, all_data[name])

    print("\n生成报告...")
    md = build_report(all_data, all_results)
    REPORT.write_text(md, encoding="utf-8")
    print(f"  报告已写入: {REPORT}")

    # 控制台摘要
    print("\n=== 推荐规则摘要 ===")
    print(f"{'序列':<16}{'推荐买点':<14}{'买10胜率':<10}{'推荐卖点':<18}{'卖10胜率':<10}")
    for name in METRIC_IDS + SCORE_IDS:
        res = all_results[name]
        if not res["buy"]:
            continue
        best_buy, _, _ = pick_best(res["buy"])
        best_sell, _, _ = pick_best(res["sell_pct"] + res["sell_std"])
        bw = best_buy["stats"][10]["win"]
        sw = best_sell["stats"][10]["win"]
        print(f"{name:<16}{best_buy['rule']:<14}{fmt_pct(bw):<10}"
              f"{best_sell['rule']:<18}{fmt_pct(sw):<10}")


if __name__ == "__main__":
    main()
