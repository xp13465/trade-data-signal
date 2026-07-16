"""RSI 买卖点阈值方案回测（独立脚本，不 import app）。

C1 框架：买=RSI 上穿 X，卖=RSI 下穿 Y，cross 不做硬门槛，事件化 shift(1)。
复刻 app/compute/signals.py 的 _rsi（period=14, EWM α=1/14, adjust=False）。
数据源：data/sentiment.db index_daily.close（13 主要指数）。
"""
import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict

DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/06-买卖点参数回测.md'

INDICES = ['sh', 'sz', 'hs300', 'csi500', 'csi1000', 'cyb', 'kc50',
           'hsi', 'hscei', 'hstech', 'csi_div', 'div_lowvol', 'sz_div']

# 方案：买阈值 X / 卖阈值 Y
SCHEMES = {
    '25/75': (25, 75),
    '28/72': (28, 72),
    '30/70': (30, 70),  # 基准 E1
    '35/65': (35, 65),
    '40/60': (40, 60),
}
HORIZONS = (5, 10, 20)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """复刻 signals._rsi：EWM α=1/period, adjust=False。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def load_close(iid: str) -> pd.Series:
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        f"SELECT date, close FROM index_daily WHERE index_id=? ORDER BY date",
        con, params=(iid,), parse_dates=['date'])
    con.close()
    return df.set_index('date')['close'].astype(float)


def gen_signals(close: pd.Series, buy_x: int, sell_y: int):
    """事件化穿越。返回 (buy_dates, sell_dates) 为 DatetimeIndex。"""
    r = rsi(close, 14)
    rp = r.shift(1)
    buy = ((rp <= buy_x) & (r > buy_x)).fillna(False)
    sell = ((rp >= sell_y) & (r < sell_y)).fillna(False)
    return close.index[buy], close.index[sell]


def forward_returns(close: pd.Series, sig_dates, horizons=HORIZONS):
    """信号日 close → N 交易日后 close 收益率(%)。无 N 日后数据则跳过。"""
    arr = close.values
    idx_to_pos = {d: i for i, d in enumerate(close.index)}
    out = {h: [] for h in horizons}
    n = len(arr)
    for d in sig_dates:
        pos = idx_to_pos.get(d)
        if pos is None:
            continue
        for h in horizons:
            if pos + h < n:
                out[h].append((arr[pos + h] - arr[pos]) / arr[pos] * 100.0)
    return out


def stats_block(returns, is_sell=False):
    """返回 (n, mean, median, win_rate, pl_ratio)。"""
    if not returns:
        return (0, float('nan'), float('nan'), float('nan'), float('nan'))
    arr = np.array(returns, dtype=float)
    if is_sell:
        wins = arr[arr < 0]      # 跌 = 卖点对
        losses = arr[arr >= 0]
    else:
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
    win_rate = len(wins) / len(arr) if len(arr) else float('nan')
    avg_win = np.abs(wins).mean() if len(wins) else 0.0
    avg_loss = np.abs(losses).mean() if len(losses) else float('nan')
    pl = avg_win / avg_loss if (not np.isnan(avg_loss) and avg_loss > 0) else float('nan')
    return (len(arr), arr.mean(), np.median(arr), win_rate, pl)


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


def main():
    # ---- 预加载 close ----
    closes = {iid: load_close(iid) for iid in INDICES}
    max_date = max(c.index.max() for c in closes.values())
    cutoff_1y = max_date - pd.Timedelta(days=365)
    cutoff_3y = max_date - pd.Timedelta(days=365 * 3)

    # ---- 结构: scheme -> side -> horizon -> list[returns] (全指数汇总) ----
    qual = {s: {'buy': defaultdict(list), 'sell': defaultdict(list)} for s in SCHEMES}
    # 信号计数: scheme -> side -> window -> {iid: count}
    cnt = {s: {'buy': {'1y': {}, '3y': {}, 'all': {}},
              'sell': {'1y': {}, '3y': {}, 'all': {}}} for s in SCHEMES}
    # 按年分布: scheme -> year -> {'buy':n,'sell':n}
    yearly = {s: defaultdict(lambda: {'buy': 0, 'sell': 0}) for s in SCHEMES}
    # 每指数信号日期(全史) 用于按年
    per_index_dates = {s: {'buy': {}, 'sell': {}} for s in SCHEMES}

    for iid in INDICES:
        close = closes[iid]
        for sname, (bx, sy) in SCHEMES.items():
            bdates, sdates = gen_signals(close, bx, sy)
            per_index_dates[sname]['buy'][iid] = bdates
            per_index_dates[sname]['sell'][iid] = sdates
            # 计数窗口
            cnt[sname]['buy']['1y'][iid] = int((bdates > cutoff_1y).sum())
            cnt[sname]['buy']['3y'][iid] = int((bdates > cutoff_3y).sum())
            cnt[sname]['buy']['all'][iid] = len(bdates)
            cnt[sname]['sell']['1y'][iid] = int((sdates > cutoff_1y).sum())
            cnt[sname]['sell']['3y'][iid] = int((sdates > cutoff_3y).sum())
            cnt[sname]['sell']['all'][iid] = len(sdates)
            # 质量汇总
            br = forward_returns(close, bdates)
            sr = forward_returns(close, sdates)
            for h in HORIZONS:
                qual[sname]['buy'][h].extend(br[h])
                qual[sname]['sell'][h].extend(sr[h])
            # 按年
            for d in bdates:
                yearly[sname][d.year]['buy'] += 1
            for d in sdates:
                yearly[sname][d.year]['sell'] += 1

    # ===================== 生成报告 =====================
    lines = []
    L = lines.append
    L("# 买卖点 RSI 阈值方案回测报告\n")
    L(f"- 生成日期：2026-07-05")
    L(f"- 数据截止：{max_date.date()}（数据源 sentiment.db index_daily）")
    L(f"- 标的：13 主要指数 ({', '.join(INDICES)})")
    L(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 app/compute/signals.py `_rsi`）")
    L(f"- 信号定义（C1 框架）：买=RSI 上穿 X（prev≤X 且 当日>X），卖=RSI 下穿 Y（prev≥Y 且 当日<Y），事件化 shift(1)")
    L(f"- 信号质量：信号日 close → N 交易日后 close 收益率(%)；买点胜率=涨幅>0占比，卖点胜率=跌幅<0占比")
    L(f"- 盈亏比=平均盈利/平均亏损（绝对值）")
    L(f"- 窗口：近1年(>{cutoff_1y.date()}) / 近3年(>{cutoff_3y.date()}) / 全史\n")

    # ---- 1. 信号数对比 ----
    L("## 1. 各方案信号数对比（13 指数总计）\n")
    L("| 方案 | 近1年买 | 近1年卖 | 近3年买 | 近3年卖 | 全史买 | 全史卖 | 全史合计 |")
    L("|---|---:|---:|---:|---:|---:|---:|---:|")
    for sname in SCHEMES:
        b1 = sum(cnt[sname]['buy']['1y'].values()); s1 = sum(cnt[sname]['sell']['1y'].values())
        b3 = sum(cnt[sname]['buy']['3y'].values()); s3 = sum(cnt[sname]['sell']['3y'].values())
        ba = sum(cnt[sname]['buy']['all'].values()); sa = sum(cnt[sname]['sell']['all'].values())
        L(f"| {sname} | {b1} | {s1} | {b3} | {s3} | {ba} | {sa} | {ba+sa} |")
    L("")

    # ---- 1b. 每指数全史信号数 ----
    L("## 2. 各方案分指数信号数（全史）\n")
    for sname in SCHEMES:
        L(f"### 方案 {sname}\n")
        L("| 指数 | 全史买 | 全史卖 | 合计 |")
        L("|---|---:|---:|---:|")
        tb = ts = 0
        for iid in INDICES:
            b = cnt[sname]['buy']['all'][iid]; s = cnt[sname]['sell']['all'][iid]
            tb += b; ts += s
            L(f"| {iid} | {b} | {s} | {b+s} |")
        L(f"| **合计** | **{tb}** | **{ts}** | **{tb+ts}** |")
        L("")

    # ---- 2. 信号质量对比 ----
    L("## 3. 各方案信号质量对比（全史，13 指数汇总）\n")
    L("### 买点质量\n")
    L("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 | 中位收益 |")
    L("|---|---|---:|---:|---:|---:|---:|")
    for sname in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual[sname]['buy'][h], is_sell=False)
            L(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {pl:.2f} | {fmt_pct(m)} | {fmt_pct(med)} |")
    L("")
    L("### 卖点质量\n")
    L("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 | 中位收益 |")
    L("|---|---|---:|---:|---:|---:|---:|")
    for sname in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual[sname]['sell'][h], is_sell=True)
            L(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {pl:.2f} | {fmt_pct(m)} | {fmt_pct(med)} |")
    L("")
    L("> 卖点均值收益：负=下跌（卖点正确方向）；胜率=收益<0占比。\n")

    # ---- 3. 近3年质量（补充，反映近年市场结构）----
    L("## 4. 各方案信号质量（近3年，13 指数汇总）\n")
    # 重算近3年质量
    qual3 = {s: {'buy': defaultdict(list), 'sell': defaultdict(list)} for s in SCHEMES}
    for iid in INDICES:
        close = closes[iid]
        for sname, (bx, sy) in SCHEMES.items():
            bdates = per_index_dates[sname]['buy'][iid]
            sdates = per_index_dates[sname]['sell'][iid]
            b3 = bdates[bdates > cutoff_3y]
            s3 = sdates[sdates > cutoff_3y]
            br = forward_returns(close, b3)
            sr = forward_returns(close, s3)
            for h in HORIZONS:
                qual3[sname]['buy'][h].extend(br[h])
                qual3[sname]['sell'][h].extend(sr[h])
    L("### 买点质量（近3年）\n")
    L("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 |")
    L("|---|---|---:|---:|---:|---:|")
    for sname in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual3[sname]['buy'][h], is_sell=False)
            L(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {pl:.2f} | {fmt_pct(m)} |")
    L("")
    L("### 卖点质量（近3年）\n")
    L("| 方案 | 周期 | 样本 | 胜率 | 盈亏比 | 均值收益 |")
    L("|---|---|---:|---:|---:|---:|")
    for sname in SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual3[sname]['sell'][h], is_sell=True)
            L(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {pl:.2f} | {fmt_pct(m)} |")
    L("")

    # ---- 4. 按年分布 ----
    L("## 5. 信号按年分布（13 指数合计，买+卖）\n")
    all_years = sorted({y for s in SCHEMES for y in yearly[s].keys()})
    hdr = "| 年份 | " + " | ".join(f"{s}买 | {s}卖" for s in SCHEMES) + " |"
    sep = "|---|" + "---:|" * (len(SCHEMES) * 2)
    L(hdr); L(sep)
    for y in all_years:
        cells = []
        for s in SCHEMES:
            b = yearly[s].get(y, {'buy': 0})['buy']
            s_ = yearly[s].get(y, {'sell': 0})['sell']
            cells.append(str(b)); cells.append(str(s_))
        L(f"| {y} | " + " | ".join(cells) + " |")
    L("")

    # ---- 5. 推荐 ----
    L("## 6. 推荐最优 RSI 阈值\n")
    L("（见正文分析）\n")

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    # ---- 控制台汇总 ----
    print("=" * 70)
    print("信号数总计（全史）:")
    for sname in SCHEMES:
        ba = sum(cnt[sname]['buy']['all'].values()); sa = sum(cnt[sname]['sell']['all'].values())
        b3 = sum(cnt[sname]['buy']['3y'].values()); s3 = sum(cnt[sname]['sell']['3y'].values())
        b1 = sum(cnt[sname]['buy']['1y'].values()); s1 = sum(cnt[sname]['sell']['1y'].values())
        print(f"  {sname}: 全史买{ba} 卖{sa} | 近3年买{b3} 卖{s3} | 近1年买{b1} 卖{s1}")
    print()
    print("买点质量（全史, 10日）:")
    for sname in SCHEMES:
        n, m, med, wr, pl = stats_block(qual[sname]['buy'][10], is_sell=False)
        print(f"  {sname}: n={n} 胜率={wr*100:.1f}% 盈亏比={pl:.2f} 均值={m:.2f}%")
    print()
    print("卖点质量（全史, 10日）:")
    for sname in SCHEMES:
        n, m, med, wr, pl = stats_block(qual[sname]['sell'][10], is_sell=True)
        print(f"  {sname}: n={n} 胜率={wr*100:.1f}% 盈亏比={pl:.2f} 均值={m:.2f}%")
    print()
    print(f"报告已写入: {REPORT}")


if __name__ == '__main__':
    main()
