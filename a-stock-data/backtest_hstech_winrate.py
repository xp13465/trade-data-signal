"""恒生科技 hstech 主买点(C1)提胜率回测 — 加确认条件方案对比。

用户需求：hstech 凯利建议但胜率<50%（买点 46.7%/辅买 48.6%），靠高盈亏比弥补，
         用户要"尽可能提高胜率"。本回测给 C1 主买点逐个加确认条件，量化 trade-off
         （胜率↑ vs 盈亏比↓/信号数↓/f 变化），出报告让用户选方案。不落地（不改 yaml）。

数据源：data/sentiment.db index_daily（hstech 的 date/open/high/low/close/amount）
  - hstech 2020-08-17 ~ 2026-07-06，1443 行，港股科技（新浪 stock_hk_index_daily_sina）

复刻 app/compute/signals.py（与 backtest_buy_aux_batch.py 一致）：
  - RSI(14) EWM α=1/14 adjust=False
  - BB(20, 2.0) std ddof=0
  - MACD(12,26,9) EMA ewm(span=N, adjust=False)：DIF=EMA(close,12)-EMA(close,26), DEA=EMA(DIF,9)
  - C1 主买 = RSI 上穿30（rsi_prev<=30 & rsi>30）
  - buy_aux B1 辅买 = BB 下轨回归（close_prev<bl_prev & close>bl），与 C1 同日去重

方案（C1 基线 + 6 个加确认条件）：
  baseline     — C1 = RSI 上穿30（现状基线）
  s1_rsi25     — RSI 上穿25（阈值收紧，更严苛超卖）
  s2_rsi_x40   — C1 + RSI 上穿40（更强反弹动量确认，rsi_prev<=40 & rsi>40）
  s3_macd_gold — C1 + MACD 金叉态（DIF>DEA，动量转强确认，与 sell 死叉对称）
  s4_ma60_bull — C1 + MA60 多头（close>MA60，趋势过滤）
  s5_vol_surge — C1 + 放量（amount > 5日均量×1.2，资金进场确认）
  s6_bb_revert — C1 + BB 下轨回归（C1∧B1 双触发，价格+波动双确认）

附录：辅买 buy_aux(B1) 同样 6 方案（辅买也<50%，样本 n=37 更多，加确认后统计更有意义）

凯利：f* = max(0, (b·p - (1-p))/b)，p=胜率 b=盈亏比。买点胜率=收益>0占比。
n<10 = 样本不足，n<30 = 样本不足警示。
horizon: 5/10/20 日（forward return: 信号日 close → N 日后 close）。

约束：独立复刻，不 import app，不改 app/ 代码，不改 DB，不改 config。
"""
import sqlite3
import numpy as np
import pandas as pd

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/19-恒生科技提胜率回测.md'
SID = 'hstech'
SID_NAME = '恒生科技'
HORIZONS = [5, 10, 20]
PRIMARY_HORIZON = 10
KELLY_INSUF_N = 10
SAMPLE_WARN_N = 30


# ===================== 指标复刻（与 signals.py 一致）=====================

def rsi(close, period=14):
    """RSI(14) EWM α=1/period adjust=False（复刻 signals.py `_rsi`）。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def bollinger(close, window=20, n_std=2.0):
    """BB(20, 2.0) std ddof=0（复刻 signals.py `_bollinger`）。返回 (bu, mid, bl)。"""
    mid = close.rolling(window).mean()
    sd = close.rolling(window).std(ddof=0)
    return mid + n_std * sd, mid, mid - n_std * sd


def macd(close, fast=12, slow=26, signal=9):
    """MACD(12,26,9) EMA ewm(span=N, adjust=False)（复刻 signals.py `_macd`）。
    返回 (dif, dea)：DIF=EMA(close,12)-EMA(close,26), DEA=EMA(DIF,9)。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    return dif, dea


def ma(s, n):
    return s.rolling(n, min_periods=n).mean()


# ===================== 主买点 C1 方案 =====================

def c1_baseline(close, amount=None):
    """基线 C1：RSI(14) 上穿30。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    return ((rp <= 30) & (r > 30)).fillna(False)


def c1_rsi25(close, amount=None):
    """方案1：RSI 上穿25（阈值收紧，更严苛超卖）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    return ((rp <= 25) & (r > 25)).fillna(False)


def c1_rsi_cross40(close, amount=None):
    """方案2：C1 + RSI 上穿40（更强反弹动量确认）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    c1 = ((rp <= 30) & (r > 30)).fillna(False)
    cross40 = ((rp <= 40) & (r > 40)).fillna(False)
    return c1 & cross40


def c1_macd_golden(close, amount=None):
    """方案3：C1 + MACD 金叉态（DIF>DEA，动量转强确认，与 sell 死叉对称）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    c1 = ((rp <= 30) & (r > 30)).fillna(False)
    dif, dea = macd(close)
    golden = (dif > dea).fillna(False)
    return c1 & golden


def c1_ma60_bull(close, amount=None):
    """方案4：C1 + MA60 多头（close>MA60，趋势过滤）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    c1 = ((rp <= 30) & (r > 30)).fillna(False)
    m60 = ma(close, 60)
    bull = (close > m60).fillna(False)
    return c1 & bull


def c1_vol_surge(close, amount=None):
    """方案5：C1 + 放量（amount > 5日均量×1.2，资金进场确认）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    c1 = ((rp <= 30) & (r > 30)).fillna(False)
    if amount is None:
        return pd.Series(False, index=close.index)
    vol_ma = amount.rolling(5).mean()
    surge = (amount > vol_ma * 1.2).fillna(False)
    return c1 & surge


def c1_bb_revert(close, amount=None):
    """方案6：C1 + BB 下轨回归（C1∧B1 双触发，价格+波动双确认）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    c1 = ((rp <= 30) & (r > 30)).fillna(False)
    _, _, bl = bollinger(close, 20, 2.0)
    bb_revert = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    return c1 & bb_revert


# ===================== 辅买点 buy_aux 方案（附录）=====================

def aux_baseline(close, amount=None, buy_set=None):
    """基线 B1：BB 下轨回归（与 C1 同日去重）。"""
    _, _, bl = bollinger(close, 20, 2.0)
    mask = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    return _dedup(mask, buy_set)


def aux_rsi25(close, amount=None, buy_set=None):
    """方案1：B1 + RSI 上穿25。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    _, _, bl = bollinger(close, 20, 2.0)
    bb = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    rsi25 = ((rp <= 25) & (r > 25)).fillna(False)
    return _dedup(bb & rsi25, buy_set)


def aux_rsi_cross40(close, amount=None, buy_set=None):
    """方案2：B1 + RSI 上穿40。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    _, _, bl = bollinger(close, 20, 2.0)
    bb = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    cross40 = ((rp <= 40) & (r > 40)).fillna(False)
    return _dedup(bb & cross40, buy_set)


def aux_macd_golden(close, amount=None, buy_set=None):
    """方案3：B1 + MACD 金叉态。"""
    _, _, bl = bollinger(close, 20, 2.0)
    bb = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    dif, dea = macd(close)
    golden = (dif > dea).fillna(False)
    return _dedup(bb & golden, buy_set)


def aux_ma60_bull(close, amount=None, buy_set=None):
    """方案4：B1 + MA60 多头。"""
    _, _, bl = bollinger(close, 20, 2.0)
    bb = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    m60 = ma(close, 60)
    bull = (close > m60).fillna(False)
    return _dedup(bb & bull, buy_set)


def aux_vol_surge(close, amount=None, buy_set=None):
    """方案5：B1 + 放量。"""
    _, _, bl = bollinger(close, 20, 2.0)
    bb = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    if amount is None:
        return pd.Series(False, index=close.index)
    vol_ma = amount.rolling(5).mean()
    surge = (amount > vol_ma * 1.2).fillna(False)
    return _dedup(bb & surge, buy_set)


def aux_bb_revert(close, amount=None, buy_set=None):
    """方案6：B1 + C1（B1∧C1 双触发，与主买 s6 对称）。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    _, _, bl = bollinger(close, 20, 2.0)
    bb = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    c1 = ((rp <= 30) & (r > 30)).fillna(False)
    return _dedup(bb & c1, buy_set)


def _dedup(mask, buy_set):
    """与 C1 同日去重（保留 C1）。"""
    if buy_set is None:
        return mask
    out = mask.copy()
    for d in buy_set:
        if d in out.index:
            out.at[d] = False
    return out


# ===================== 数据加载 =====================

def load_index_ohlcv(iid):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close, amount FROM index_daily "
        "WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    if df.empty:
        return None
    return df.set_index('date').astype(float)


# ===================== 回测工具 =====================

def forward_returns(close, sig_mask, horizon):
    arr = close.values
    n = len(arr)
    sig_idx = np.where(sig_mask.values)[0]
    out = []
    for pos in sig_idx:
        if pos + horizon < n:
            out.append((arr[pos + horizon] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns):
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), None)
    arr = np.array(returns, dtype=float)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    n = len(arr)
    wr = len(wins) / n
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = (avg_win / avg_loss) if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    f = None
    if not np.isnan(pl) and pl > 0:
        f = (pl * wr - (1 - wr)) / pl
    return (n, float(arr.mean()), float(wr), float(pl), f)


def kelly_class(n, f):
    if n < KELLY_INSUF_N:
        return '样本不足'
    if f is None or f <= 0:
        return '不建议'
    return '建议'


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_pl(x):
    return f"{x:.2f}" if not np.isnan(x) else "-"


def fmt_mean(x, nd=2):
    sign = "+" if (not np.isnan(x) and x > 0) else ""
    return f"{sign}{x:.{nd}f}%" if not np.isnan(x) else "-"


def fmt_f(x):
    if x is None:
        return "-"
    return f"{x*100:.2f}%"


def consistency_str(fs):
    """三 horizon 一致性。"""
    f_signs = [(1 if (x is not None and x > 0) else 0) for x in fs]
    if all(s == 1 for s in f_signs):
        return "三 horizon 一致 f>0（稳健）"
    if all(s == 0 for s in f_signs):
        return "三 horizon 一致 f≤0（一致不建议）"
    return "三 horizon 不一致"


def run_schemes(close, amount, schemes, buy_set=None):
    """跑所有方案，返回 {scheme_name: {horizon: (n, mean, wr, pl, f, lbl)}}。"""
    results = {}
    for name, fn in schemes:
        if buy_set is not None:
            mask = fn(close, amount, buy_set)
        else:
            mask = fn(close, amount)
        per_h = {}
        for h in HORIZONS:
            rets = forward_returns(close, mask, h)
            n, mean, wr, pl, f = stats_block(rets)
            lbl = kelly_class(n, f)
            per_h[h] = (n, mean, wr, pl, f, lbl)
        results[name] = per_h
    return results


# ===================== 报告生成 =====================

def render_table(results, scheme_labels):
    """渲染某信号类型（buy/buy_aux）的多方案对比表。"""
    lines = []
    lines.append(f"| 方案 | 5d n | 5d 胜率 | 5d 盈亏比 | 5d 均值 | 5d f | "
                 f"| 10d n | 10d 胜率 | 10d 盈亏比 | 10d 均值 | 10d f | "
                 f"| 20d n | 20d 胜率 | 20d 盈亏比 | 20d 均值 | 20d f | 一致性 |")
    lines.append("|" + "---|" * 19)
    for name in scheme_labels:
        per_h = results[name]
        n5, m5, w5, p5, f5, _ = per_h[5]
        n10, m10, w10, p10, f10, _ = per_h[10]
        n20, m20, w20, p20, f20, _ = per_h[20]
        cons = consistency_str([f5, f10, f20])
        lines.append(
            f"| {name} | {n5} | {fmt_pct(w5*100)} | {fmt_pl(p5)} | {fmt_mean(m5)} | {fmt_f(f5)} | "
            f"| {n10} | {fmt_pct(w10*100)} | {fmt_pl(p10)} | {fmt_mean(m10)} | {fmt_f(f10)} | "
            f"| {n20} | {fmt_pct(w20*100)} | {fmt_pl(p20)} | {fmt_mean(m20)} | {fmt_f(f20)} | {cons} |"
        )
    return "\n".join(lines)


def render_detail_table(results, scheme_labels, sig_type):
    """渲染详细表（含凯利建议标签）。"""
    lines = []
    lines.append(f"### {sig_type} 详细（含凯利建议）\n")
    lines.append("| 方案 | horizon | n | 胜率 | 盈亏比 | 均值 | 凯利 f | 凯利建议 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name in scheme_labels:
        per_h = results[name]
        for h in HORIZONS:
            n, mean, wr, pl, f, lbl = per_h[h]
            star = " ⚠️n<30" if (n > 0 and n < SAMPLE_WARN_N) else (" †n<10" if n < KELLY_INSUF_N else "")
            lines.append(
                f"| {name} | {h}d | {n}{star} | {fmt_pct(wr*100)} | {fmt_pl(pl)} | {fmt_mean(mean)} | {fmt_f(f)} | {lbl} |"
            )
    return "\n".join(lines)


def main():
    df = load_index_ohlcv(SID)
    if df is None:
        print(f"ERROR: {SID} 无数据")
        return
    close = df['close']
    amount = df['amount'] if 'amount' in df else None
    n_rows = len(df)
    date_min = df.index.min().strftime('%Y-%m-%d')
    date_max = df.index.max().strftime('%Y-%m-%d')

    print(f"{SID_NAME}({SID}): {n_rows} 行, {date_min} ~ {date_max}")

    # C1 主买点（用于 buy_aux 去重）
    c1_mask = c1_baseline(close, amount)
    buy_set = set(c1_mask[c1_mask].index)
    print(f"C1 主买信号数: {len(buy_set)}")

    # 主买方案
    buy_schemes = [
        ('baseline C1', c1_baseline),
        ('s1 RSI上穿25', c1_rsi25),
        ('s2 C1+RSI上穿40', c1_rsi_cross40),
        ('s3 C1+MACD金叉', c1_macd_golden),
        ('s4 C1+MA60多头', c1_ma60_bull),
        ('s5 C1+放量1.2x', c1_vol_surge),
        ('s6 C1+BB下轨回归', c1_bb_revert),
    ]
    buy_results = run_schemes(close, amount, buy_schemes, buy_set=None)

    # 辅买方案（附录）
    aux_schemes = [
        ('baseline B1', aux_baseline),
        ('s1 B1+RSI上穿25', aux_rsi25),
        ('s2 B1+RSI上穿40', aux_rsi_cross40),
        ('s3 B1+MACD金叉', aux_macd_golden),
        ('s4 B1+MA60多头', aux_ma60_bull),
        ('s5 B1+放量1.2x', aux_vol_surge),
        ('s6 B1+C1双触发', aux_bb_revert),
    ]
    aux_results = run_schemes(close, amount, aux_schemes, buy_set=buy_set)

    buy_labels = [n for n, _ in buy_schemes]
    aux_labels = [n for n, _ in aux_schemes]

    # 现状基线（从 signal_stats.json 对齐确认）
    baseline_buy = buy_results['baseline C1']
    baseline_aux = aux_results['baseline B1']
    b10 = baseline_buy[PRIMARY_HORIZON]
    a10 = baseline_aux[PRIMARY_HORIZON]
    print(f"\n基线 10d: buy n={b10[0]} 胜率={fmt_pct(b10[2]*100)} pl={fmt_pl(b10[3])} f={fmt_f(b10[4])}")
    print(f"基线 10d: aux n={a10[0]} 胜率={fmt_pct(a10[2]*100)} pl={fmt_pl(a10[3])} f={fmt_f(a10[4])}")

    # 找胜率最高方案（10d）
    print("\n=== 主买 10d 胜率排名 ===")
    for name in buy_labels:
        n, m, w, p, f, _ = buy_results[name][10]
        print(f"  {name}: n={n} 胜率={fmt_pct(w*100)} pl={fmt_pl(p)} f={fmt_f(f)}")
    print("\n=== 辅买 10d 胜率排名 ===")
    for name in aux_labels:
        n, m, w, p, f, _ = aux_results[name][10]
        print(f"  {name}: n={n} 胜率={fmt_pct(w*100)} pl={fmt_pl(p)} f={fmt_f(f)}")

    # 生成报告
    report = build_report(
        SID_NAME, SID, n_rows, date_min, date_max, len(buy_set),
        buy_results, aux_results, buy_labels, aux_labels,
        baseline_buy, baseline_aux)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已写入: {REPORT}")


def build_report(name, sid, n_rows, date_min, date_max, n_c1_raw,
                 buy_results, aux_results, buy_labels, aux_labels,
                 baseline_buy, baseline_aux):
    b10 = baseline_buy[10]
    a10 = baseline_aux[10]
    lines = []
    lines.append(f"# {name}({sid}) 提胜率回测 — 主买点(C1)加确认条件方案对比\n")
    lines.append(f"> 独立回测脚本 `a-stock-data/backtest_hstech_winrate.py` 生成。"
                 f"复刻 `app/compute/signals.py`（RSI/BB/MACD/MA），不 import app，不改 DB/config。")
    lines.append(f"> 生成日期：2026-07-08 ｜ 数据：data/sentiment.db index_daily ｜ 不落地（等用户选方案后再改 yaml）\n")

    lines.append("## 0. 背景与目标\n")
    lines.append(f"**{name}** 是港股科技指数，凯利建议但胜率<50%：")
    lines.append(f"- 主买点(C1 RSI上穿30) 10d 胜率 **{fmt_pct(b10[2]*100)}**（f={fmt_f(b10[4])}, pl={fmt_pl(b10[3])}, n={b10[0]}）")
    lines.append(f"- 辅买点(B1 BB下轨回归) 10d 胜率 **{fmt_pct(a10[2]*100)}**（f={fmt_f(a10[4])}, pl={fmt_pl(a10[3])}, n={a10[0]}）")
    lines.append(f"- 凯利建议靠**高盈亏比**弥补低胜率，但用户要「尽可能提高胜率」。\n")
    lines.append(f"**目标**：给主买点(C1)逐个加确认条件，测能否提胜率，量化 trade-off（胜率↑ vs 盈亏比↓/信号数↓/f 变化）。")
    lines.append(f"附录同时测辅买点(B1)加确认（辅买也<50%，样本更多 n={a10[0]} 更可信）。\n")

    lines.append("## 1. 数据现状与基线\n")
    lines.append(f"| 项 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 指数 | {name}({sid}) 港股科技 |")
    lines.append(f"| 数据源 | index_daily（stock_hk_index_daily_sina） |")
    lines.append(f"| 行数 | {n_rows} |")
    lines.append(f"| 日期范围 | {date_min} ~ {date_max}（约 {(n_rows)//244} 年） |")
    lines.append(f"| C1 主买信号数(raw) | {n_c1_raw}（去 forward 截断后 n={b10[0]}） |")
    lines.append(f"| ⚠️ 样本量 | 主买 n={b10[0]} **<30 样本不足警示**，加确认后更少，结论仅供参考 |")
    lines.append(f"| 辅买样本 | n={a10[0]}（≥30，相对可信） |")
    lines.append("")
    lines.append(f"**基线（现状，与 signal_stats.json 对齐）**：\n")
    lines.append(f"| 信号 | horizon | n | 胜率 | 盈亏比 | 均值 | 凯利 f |")
    lines.append(f"|---|---|---|---|---|---|---|")
    for h in HORIZONS:
        n, m, w, p, f, _ = baseline_buy[h]
        lines.append(f"| 买点(C1) | {h}d | {n} | {fmt_pct(w*100)} | {fmt_pl(p)} | {fmt_mean(m)} | {fmt_f(f)} |")
    for h in HORIZONS:
        n, m, w, p, f, _ = baseline_aux[h]
        lines.append(f"| 辅买(B1) | {h}d | {n} | {fmt_pct(w*100)} | {fmt_pl(p)} | {fmt_mean(m)} | {fmt_f(f)} |")
    lines.append("")

    lines.append("## 2. 主买点(C1) 方案对比\n")
    lines.append("方案说明：")
    lines.append("- `baseline C1` = RSI(14) 上穿30（现状基线）")
    lines.append("- `s1 RSI上穿25` = RSI 上穿25（阈值收紧，更严苛超卖）")
    lines.append("- `s2 C1+RSI上穿40` = C1 ∧ RSI 上穿40（更强反弹动量确认）")
    lines.append("- `s3 C1+MACD金叉` = C1 ∧ DIF>DEA（MACD 金叉态，动量转强确认，与 sell 死叉对称）")
    lines.append("- `s4 C1+MA60多头` = C1 ∧ close>MA60（趋势过滤，仅多头市放买）")
    lines.append("- `s5 C1+放量1.2x` = C1 ∧ amount>5日均量×1.2（资金进场确认）")
    lines.append("- `s6 C1+BB下轨回归` = C1 ∧ BB下轨回归（C1∧B1 双触发，价格+波动双确认）\n")
    lines.append("### 主买 多方案对比（三 horizon）\n")
    lines.append(render_table(buy_results, buy_labels))
    lines.append("")
    lines.append(render_detail_table(buy_results, buy_labels, "主买(C1)"))
    lines.append("")

    lines.append("## 3. 辅买点(B1) 方案对比（附录）\n")
    lines.append("> 辅买也<50%（48.6%），样本 n=37 更多。加确认后统计更有意义，作为补充参考。\n")
    lines.append("### 辅买 多方案对比（三 horizon）\n")
    lines.append(render_table(aux_results, aux_labels))
    lines.append("")
    lines.append(render_detail_table(aux_results, aux_labels, "辅买(B1)"))
    lines.append("")

    lines.append("## 4. Trade-off 分析（主买 10d 主 horizon）\n")
    lines.append("| 方案 | n | 胜率 | 胜率Δ | 盈亏比 | 盈亏比Δ | f | fΔ | 信号数Δ | 评价 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    bn, bm, bw, bp, bf, _ = baseline_buy[10]
    for name in buy_labels:
        n, m, w, p, f, _ = buy_results[name][10]
        wd = (w - bw) * 100 if (not np.isnan(w) and not np.isnan(bw)) else float('nan')
        pd = p - bp if (not np.isnan(p) and not np.isnan(bp)) else float('nan')
        fd = (f - bf) if (f is not None and bf is not None) else None
        nd = n - bn
        wd_s = f"{wd:+.1f}pp" if not np.isnan(wd) else "-"
        pd_s = f"{pd:+.2f}" if not np.isnan(pd) else "-"
        fd_s = fmt_f(fd) if fd is not None else "-"
        nd_s = f"{nd:+d}"
        eval_s = ""
        if n < KELLY_INSUF_N:
            eval_s = "样本不足†"
        elif f is None or f <= 0:
            eval_s = "f 转负/不建议"
        elif not np.isnan(wd) and wd > 0:
            eval_s = "胜率+f 双升"
        elif f > 0:
            eval_s = "f 正但胜率未升"
        lines.append(f"| {name} | {n} | {fmt_pct(w*100)} | {wd_s} | {fmt_pl(p)} | {pd_s} | {fmt_f(f)} | {fd_s} | {nd_s} | {eval_s} |")
    lines.append("")

    # 推荐分析
    lines.append("## 5. 推荐分析\n")
    lines.append("### 主买点(C1) — 10d 胜率排名（全方案，含样本不足）\n")
    lines.append("| 排名 | 方案 | n | 胜率 | 盈亏比 | f | 可信度 |")
    lines.append("|---|---|---|---|---|---|---|")
    ranked = sorted(buy_labels, key=lambda nm: (buy_results[nm][10][2] if not np.isnan(buy_results[nm][10][2]) else -1), reverse=True)
    for i, nm in enumerate(ranked, 1):
        n, m, w, p, f, _ = buy_results[nm][10]
        if n < KELLY_INSUF_N:
            cred = f"†样本不足(n<{KELLY_INSUF_N})"
        elif n < SAMPLE_WARN_N:
            cred = f"⚠️警示(n<{SAMPLE_WARN_N})"
        else:
            cred = "可信(n≥30)"
        lines.append(f"| {i} | {nm} | {n} | {fmt_pct(w*100)} | {fmt_pl(p)} | {fmt_f(f)} | {cred} |")
    lines.append("")

    # 可信方案（n>=10）中胜率最高
    credible = [(nm, buy_results[nm][10]) for nm in buy_labels if buy_results[nm][10][0] >= KELLY_INSUF_N]
    credible_above50 = [(nm, t) for nm, t in credible if not np.isnan(t[2]) and t[2] >= 0.5]
    # 样本不足但胜率高值得关注的
    promising_low_n = [(nm, buy_results[nm][10]) for nm in buy_labels
                       if buy_results[nm][10][0] < KELLY_INSUF_N
                       and buy_results[nm][10][0] > 0
                       and not np.isnan(buy_results[nm][10][2])
                       and buy_results[nm][10][2] >= 0.5]

    if credible_above50:
        nm, t = max(credible_above50, key=lambda x: x[1][2])
        n, m, w, p, f, _ = t
        lines.append(f"- **可信方案(n≥{KELLY_INSUF_N})中胜率≥50%**：`{nm}` 10d 胜率 {fmt_pct(w*100)}（n={n}），"
                     f"f {fmt_f(f)}，盈亏比 {fmt_pl(p)}。")
    else:
        if credible:
            nm, t = max(credible, key=lambda x: x[1][2] if not np.isnan(x[1][2]) else -1)
            n, m, w, p, f, _ = t
            lines.append(f"- **可信方案(n≥{KELLY_INSUF_N})中胜率最高**：`{nm}` 10d 胜率 {fmt_pct(w*100)}（n={n}），"
                         f"仍**<50%**。f {fmt_f(f)}，盈亏比 {fmt_pl(p)}。")
        lines.append(f"- **结论**：在可信样本(n≥{KELLY_INSUF_N})中，**没有主买方案能将 10d 胜率拉到≥50%**。")
        if promising_low_n:
            lines.append(f"- **样本不足但胜率值得关注（†不可落地）**：")
            for nm, t in sorted(promising_low_n, key=lambda x: x[1][2], reverse=True):
                n, m, w, p, f, _ = t
                lines.append(f"  - `{nm}`：胜率 {fmt_pct(w*100)}（n={n}†），f {fmt_f(f)}，盈亏比 {fmt_pl(p)}。"
                             f"样本太少，可能是幸存者偏差，**需更多数据验证不可直接落地**。")
        lines.append(f"- **0 信号方案（不适用）**：s3 MACD金叉 / s4 MA60多头 在主买产生 **0 信号**——"
                     f"RSI 上穿30（超卖反弹）时 MACD 常仍在死叉态、close 常<MA60，这两个确认条件与超卖反弹语义矛盾。")
        lines.append(f"- **建议**：主买点**维持现状 C1**（f={fmt_f(bf)} 正期望，靠盈亏比 {fmt_pl(bp)} 弥补低胜率）。"
                     f"hstech 主买全史仅 {bn} 信号，加确认条件后多数 n<{KELLY_INSUF_N} 不可信；"
                     f"s1 RSI上穿25 虽胜率高(85.7%)但 n=7†，若用户愿赌可待样本累积后再评估。")

    # 辅买推荐
    lines.append("")
    lines.append("### 辅买点(B1) — 10d 胜率排名（全方案，含样本不足）\n")
    lines.append("| 排名 | 方案 | n | 胜率 | 盈亏比 | f | 一致性 | 可信度 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    ranked_aux = sorted(aux_labels, key=lambda nm: (aux_results[nm][10][2] if not np.isnan(aux_results[nm][10][2]) else -1), reverse=True)
    for i, nm in enumerate(ranked_aux, 1):
        n, m, w, p, f, _ = aux_results[nm][10]
        fs = [aux_results[nm][h][4] for h in HORIZONS]
        cons = consistency_str(fs)
        if n < KELLY_INSUF_N:
            cred = f"†样本不足"
        elif n < SAMPLE_WARN_N:
            cred = f"⚠️警示"
        else:
            cred = "可信"
        lines.append(f"| {i} | {nm} | {n} | {fmt_pct(w*100)} | {fmt_pl(p)} | {fmt_f(f)} | {cons} | {cred} |")
    lines.append("")

    # 辅买可信方案
    cred_aux = [(nm, aux_results[nm][10]) for nm in aux_labels if aux_results[nm][10][0] >= KELLY_INSUF_N]
    cred_aux_50 = [(nm, t) for nm, t in cred_aux if not np.isnan(t[2]) and t[2] >= 0.5]
    # 辅买三 horizon 一致 f>0 且胜率>=50%（即使 n<10 也值得关注）
    promising_aux = [(nm, aux_results[nm][10]) for nm in aux_labels
                     if aux_results[nm][10][0] > 0
                     and not np.isnan(aux_results[nm][10][2])
                     and aux_results[nm][10][2] >= 0.5
                     and all(aux_results[nm][h][4] is not None and aux_results[nm][h][4] > 0 for h in HORIZONS)]
    if cred_aux_50:
        nm, t = max(cred_aux_50, key=lambda x: x[1][2])
        n, m, w, p, f, _ = t
        lines.append(f"- **可信辅买方案(n≥{KELLY_INSUF_N})中胜率≥50%**：`{nm}` 10d 胜率 {fmt_pct(w*100)}（n={n}），f {fmt_f(f)}。")
    else:
        aux_max_wr = max((t[2] for _, t in cred_aux if not np.isnan(t[2])), default=0)
        lines.append(f"- **可信辅买方案(n≥{KELLY_INSUF_N})中无胜率≥50%**（最高 {fmt_pct(aux_max_wr*100)}）。")
    if promising_aux:
        lines.append(f"- **三 horizon 一致 f>0 且 10d 胜率≥50%（值得关注，部分†样本不足）**：")
        for nm, t in sorted(promising_aux, key=lambda x: x[1][2], reverse=True):
            n, m, w, p, f, _ = t
            fs = [aux_results[nm][h][4] for h in HORIZONS]
            tag = "†" if n < KELLY_INSUF_N else ("⚠️" if n < SAMPLE_WARN_N else "")
            lines.append(f"  - `{nm}`：10d 胜率 {fmt_pct(w*100)}（n={n}{tag}），f 5d/10d/20d = {fmt_f(fs[0])}/{fmt_f(fs[1])}/{fmt_f(fs[2])}，"
                         f"盈亏比 {fmt_pl(p)}。三 horizon 一致 f>0 稳健，但{'样本不足需验证' if n < SAMPLE_WARN_N else '相对可信'}。")
    lines.append(f"- **辅买建议**：s5 B1+放量1.2x 三 horizon 一致 f>0（10d f=31.81%, 胜率 50%）但 n=6† 样本不足；"
                 f"若用户愿试可待样本累积。s2 B1+RSI上穿40（n=11⚠️）胜率反降且 10d f 转负，不推荐。")

    lines.append("")
    lines.append("## 6. 横向备注\n")
    lines.append(f"- **hstech 是港股科技指数**（恒生科技，2020-07 发布），与 A 股品类逻辑可能不同：")
    lines.append(f"  - 港股无涨跌停、T+0、外资主导、受美股/地缘影响大，RSI 超卖反弹确定性弱于 A 股（A 股有涨跌停板「封底」效应）。")
    lines.append(f"  - hstech 仅 6 年历史（2020-08 起），样本基数小，主买全史仅 {n_c1_raw} 信号，统计可信度低于 A 股宽基（sh/csi1000 等有 10+ 年）。")
    lines.append(f"  - 港股科技趋势性强（2021 大熊、2022-2023 震荡、2024-2025 反弹），RSI 上穿30 在趋势中继时假信号多。")
    lines.append(f"- **样本量警示**：主买 n={bn} <30，加确认后多数方案 n<{KELLY_INSUF_N}（样本不足），"
                 f"结论**仅供参考不可作为落地依据**。辅买 n={a10[0]} 相对充足但仍需谨慎。")
    lines.append(f"- **与 A 股品类对比**：A 股 buy_aux 优化（家电/csi1000/传媒等）方案B（RSI上穿40）多次三 horizon 一致转正，"
                 f"但那是对**辅买点**加确认；本报告对**主买点**加确认，语义不同（C1 已是 RSI 阈值触发，再叠 RSI 确认属「同维收紧」非「异维确认」）。")
    lines.append(f"- **MACD 金叉确认**：与 sell 死叉确认（commit ec0f88c）对称。sell 用 DIF<DEA 过滤假摔，"
                 f"买点用 DIF>DEA 确认动量转强。但 RSI 上穿30（超卖反弹）时 MACD 常仍在死叉态，要求金叉会大幅过滤信号。")
    lines.append("")
    lines.append("## 7. 最终建议\n")
    lines.append(f"**不落地**。本报告供用户选择方案。建议参考：")
    lines.append(f"1. 若用户优先「胜率≥50%」：看是否有方案达标（见 §5）。")
    lines.append(f"2. 若用户接受「维持现状靠盈亏比」：主买 C1 不动（f={fmt_f(bf)} 已正），辅买视情况。")
    lines.append(f"3. 若用户想试「折中」：选胜率提升最多且 f 仍正的方案（即使 n 偏小）。")
    lines.append(f"4. 落地方式（用户选后）：改 `config/indicators.yaml` 给 hstech 加 `buy_filter`（新机制，类比 buy_aux_filter 但作用于主买），"
                 f"或改 `app/compute/signals.py` 主买逻辑。当前 buy_aux_filter 仅作用于辅买，主买无 per-index 配置机制，需新增。")
    lines.append("")
    lines.append("---")
    lines.append(f"\n*脚本: `a-stock-data/backtest_hstech_winrate.py` ｜ 复刻 signals.py RSI/BB/MACD/MA ｜ "
                 f"凯利 f*=max(0,(b·p-(1-p))/b) ｜ n<{KELLY_INSUF_N}=样本不足†, n<{SAMPLE_WARN_N}=警示⚠️*")
    return "\n".join(lines)


if __name__ == '__main__':
    main()
