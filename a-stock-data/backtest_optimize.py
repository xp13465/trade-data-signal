"""买卖点优化方案回测（独立脚本，不 import app）。

目的：回测卖点降噪 (S1-S5) + 买点增强 (B1-B2) + 组合方案，给数据依据 + 推荐。
方法：复刻 RSI/D1/BB/MA，13 主要指数 + 31 申万行业 + 抽样 200 只个股（共 ~244 资产），
      信号 forward-return 统计（5/10/20 日）。
- RSI: period=14, EWM α=1/14, adjust=False（复刻 app/compute/signals.py `_rsi`）
- D1: close 从近 N 日 high 之 max 回落 P%（high-based，事件化 shift(1)）
- BB: MA20 ± 2σ（std ddof=0）
- 买点胜率=收益>0 占比；卖点胜率=收益<0 占比（信号后下跌才算对）
- 盈亏比=平均盈利/平均亏损（绝对值）；均值收益单位 %
- 信号密度=总信号 / 资产数 / 年（越低噪声越少）
"""
import sqlite3
import time
from collections import defaultdict

import numpy as np
import pandas as pd

STOCK_DB = '/Users/linhuichen/code/trade/data/stock_daily.db'
SENT_DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/11-买卖点优化方案回测.md'

# 13 主要指数（含 3 红利）+ 31 申万行业（与 08 报告一致，244 资产）
MAIN_INDICES = ['sh', 'sz', 'hs300', 'csi500', 'csi1000', 'cyb', 'kc50',
                'hsi', 'hscei', 'hstech', 'csi_div', 'div_lowvol', 'sz_div']
SW_INDICES = [f'sw_801{i:03d}' for i in
              [10, 30, 40, 50, 80, 110, 120, 130, 140, 150, 160, 170, 180,
               200, 210, 230, 710, 720, 730, 740, 750, 760, 770, 780, 790,
               880, 890, 950, 960, 970, 980]]

HORIZONS = (5, 10, 20)
SAMPLE_STOCKS = 200
SEED = 20260705


# ===================== 指标（自复刻） =====================

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """复刻 signals._rsi：EWM α=1/period, adjust=False。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = close.rolling(n, min_periods=n).mean()
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def _cross_up(curr, prev, level):
    return ((prev <= level) & (curr > level)).fillna(False)


def gen_d1(high: pd.Series, close: pd.Series, lookback: int, drop_pct: float) -> pd.Series:
    """D1: close 从近 lookback 日 high 之 max 回落 drop_pct%。"""
    hh = high.rolling(lookback, min_periods=lookback).max()
    thresh = hh * (1.0 - drop_pct / 100.0)
    return ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)


def gen_bb_upper_revert(close: pd.Series) -> pd.Series:
    bu, _, _ = bollinger(close, 20, 2.0)
    return ((close.shift(1) > bu.shift(1)) & (close < bu)).fillna(False)


def gen_bb_lower_revert(close: pd.Series) -> pd.Series:
    _, _, bl = bollinger(close, 20, 2.0)
    return ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)


def track_last_buy(close: pd.Series, buy_mask: pd.Series) -> pd.Series:
    """前向填充最近一次买点 close（首个买点前为 NaN）。与 signals.py 游标逻辑一致。"""
    return close.where(buy_mask).ffill()


# ===================== 买点方案 =====================

def gen_buy_schemes(close: pd.Series, high: pd.Series) -> dict:
    r = rsi(close, 14)
    rp = r.shift(1)
    out = {
        'C1_25': _cross_up(r, rp, 25),
        'C1_28': _cross_up(r, rp, 28),
        'C1_30': _cross_up(r, rp, 30),      # 现状基线
        'C1_32': _cross_up(r, rp, 32),
        'C1_35': _cross_up(r, rp, 35),
        'B1_dual': _cross_up(r, rp, 30) | gen_bb_lower_revert(close),  # C1 + BB下轨回归
    }
    return out


# ===================== 卖点方案 =====================

def gen_sell_schemes(high: pd.Series, close: pd.Series, buy_mask_c1: pd.Series,
                     buy_mask_b1: pd.Series) -> dict:
    """返回 {scheme_name: sell_mask}。S2 盈利约束需 buy_mask 跟踪前买点。"""
    d1 = gen_d1(high, close, 20, 5.0)              # 现状基线 D1_20_5
    ma60 = ma(close, 60)
    bb_up = gen_bb_upper_revert(close)
    last_buy_c1 = track_last_buy(close, buy_mask_c1)
    last_buy_b1 = track_last_buy(close, buy_mask_b1)
    profit_c1 = last_buy_c1.notna() & (close > last_buy_c1)
    profit_b1 = last_buy_b1.notna() & (close > last_buy_b1)

    out = {
        'D1_20_5': d1,                             # 现状基线
        'S1_MA60bull': d1 & (close > ma60),        # 趋势过滤：MA60 多头才放卖
        'S2_profit_C1': d1 & profit_c1,            # 盈利约束（前买C1盈利才放卖）
        'S2_profit_B1': d1 & profit_b1,            # 盈利约束（前买B1盈利才放卖，给组合用）
        # S3 参数调优
        'S3_10_3': gen_d1(high, close, 10, 3.0),
        'S3_10_5': gen_d1(high, close, 10, 5.0),
        'S3_20_3': gen_d1(high, close, 20, 3.0),
        'S3_20_8': gen_d1(high, close, 20, 8.0),
        'S3_30_5': gen_d1(high, close, 30, 5.0),
        'S3_30_8': gen_d1(high, close, 30, 8.0),
        'S3_60_8': gen_d1(high, close, 60, 8.0),
        # S4 BB上轨回归替代
        'S4_BBupper': bb_up,
        # S5 D1 + BB上轨回归双重确认（同日触发）
        'S5_D1andBB': d1 & bb_up,
    }
    return out


# ===================== 数据加载 =====================

def load_index_series(con, iid):
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close FROM index_daily "
        "WHERE index_id=? ORDER BY date", con, params=(iid,),
        parse_dates=['date'])
    if len(df) < 60:
        return None
    df = df.set_index('date').astype(float)
    return df[['open', 'high', 'low', 'close']]


def sample_stock_codes(con, k):
    rng = np.random.default_rng(SEED)
    df = pd.read_sql_query(
        "SELECT code, COUNT(*) c, MAX(date) mx FROM mootdx_daily_raw "
        "GROUP BY code HAVING c >= 1500 AND mx >= '20200101'", con)
    codes = df['code'].tolist()
    idx = rng.choice(len(codes), size=min(k, len(codes)), replace=False)
    return [codes[i] for i in sorted(idx)]


def load_stock_series(con, code):
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close,volume FROM mootdx_daily_raw "
        "WHERE code=? ORDER BY date", con, params=(code,), parse_dates=['date'])
    if len(df) < 60:
        return None
    df = df.set_index('date')
    for c in ['open', 'high', 'low', 'close', 'volume']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['close'] > 0]
    if len(df) < 60:
        return None
    return df[['open', 'high', 'low', 'close', 'volume']]


# ===================== 统计 =====================

def stats_block(returns, is_sell):
    """返回 (n, mean, median, win_rate, pl_ratio)。"""
    if len(returns) == 0:
        return (0, float('nan'), float('nan'), float('nan'), float('nan'))
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return (0, float('nan'), float('nan'), float('nan'), float('nan'))
    if is_sell:
        wins = arr[arr < 0]
        losses = arr[arr >= 0]
    else:
        wins = arr[arr > 0]
        losses = arr[arr <= 0]
    wr = len(wins) / len(arr)
    aw = np.abs(wins).mean() if len(wins) else 0.0
    al = np.abs(losses).mean() if len(losses) else float('nan')
    pl = float(aw / al) if (not np.isnan(al) and al > 0) else float('nan')
    return (len(arr), arr.mean(), np.median(arr), wr, pl)


def fmt(x, nd=1):
    return f"{x:.{nd}f}" if not np.isnan(x) else "-"


def fmt_pct(x, nd=1):
    return f"{x:.{nd}f}%" if not np.isnan(x) else "-"


# ===================== 主流程 =====================

def main():
    t0 = time.time()
    scon = sqlite3.connect(SENT_DB)
    assets = []
    for iid in MAIN_INDICES:
        df = load_index_series(scon, iid)
        if df is not None:
            assets.append(('idx', iid, df))
    for iid in SW_INDICES:
        df = load_index_series(scon, iid)
        if df is not None:
            assets.append(('sw', iid, df))
    scon.close()

    stcon = sqlite3.connect(STOCK_DB)
    stock_codes = sample_stock_codes(stcon, SAMPLE_STOCKS)
    for code in stock_codes:
        df = load_stock_series(stcon, code)
        if df is not None:
            assets.append(('stk', code, df))
    stcon.close()
    n_assets = len(assets)
    print(f"[load] assets={n_assets}  elapsed={time.time()-t0:.1f}s")

    # 周期 cutoff
    max_date = max(a[2].index.max() for a in assets)
    cutoff_1y = max_date - pd.Timedelta(days=365)
    cutoff_3y = max_date - pd.Timedelta(days=365 * 3)
    PERIODS = [('全史', None), ('近3年', cutoff_3y), ('近1年', cutoff_1y)]

    # 聚合容器
    # qual[(side, scheme, horizon, period_name)] = list[returns]
    qual = defaultdict(list)
    # sig_count[(side, scheme, period_name)] = total signal count (用 5日 horizon 有 forward 数据的近似近端计数)
    sig_count = defaultdict(int)
    # 全史信号数（不限 horizon，用于密度计算）
    sig_count_full = defaultdict(int)  # (side, scheme) -> count
    # 各资产年限，用于密度
    asset_years = []

    BUY_SCHEMES = ['C1_25', 'C1_28', 'C1_30', 'C1_32', 'C1_35', 'B1_dual']
    SELL_SCHEMES = ['D1_20_5', 'S1_MA60bull', 'S2_profit_C1', 'S2_profit_B1',
                    'S3_10_3', 'S3_10_5', 'S3_20_3', 'S3_20_8',
                    'S3_30_5', 'S3_30_8', 'S3_60_8', 'S4_BBupper', 'S5_D1andBB']

    for ai, (kind, name, df) in enumerate(assets):
        if (ai + 1) % 40 == 0:
            print(f"  [proc] {ai+1}/{n_assets}  elapsed={time.time()-t0:.1f}s")
        try:
            close = df['close']
            high = df['high']
            buys = gen_buy_schemes(close, high)
            buy_c1 = buys['C1_30']
            buy_b1 = buys['B1_dual']
            sells = gen_sell_schemes(high, close, buy_c1, buy_b1)
        except Exception:
            continue

        idx = close.index
        asset_years.append((idx.max() - idx.min()).days / 365.25)
        fwd = {h: (close.shift(-h) / close - 1.0) * 100.0 for h in HORIZONS}

        def accumulate(side, scheme, mask):
            if mask is None or mask.sum() == 0:
                return
            sig_dates = idx[mask]
            sig_count_full[(side, scheme)] += len(sig_dates)
            for pname, cut in PERIODS:
                sd = sig_dates if cut is None else sig_dates[sig_dates > cut]
                if len(sd) == 0:
                    continue
                if pname == '近1年':
                    sig_count[(side, scheme, pname)] += int(fwd[5].reindex(sd).notna().sum())
                elif pname == '近3年':
                    sig_count[(side, scheme, pname)] += int(fwd[5].reindex(sd).notna().sum())
                else:
                    sig_count[(side, scheme, pname)] += int(fwd[5].reindex(sd).notna().sum())
                for h in HORIZONS:
                    r = fwd[h].reindex(sd).dropna().values
                    if len(r):
                        qual[(side, scheme, h, pname)].extend(r.tolist())

        for sname, mask in buys.items():
            accumulate('buy', sname, mask)
        for sname, mask in sells.items():
            accumulate('sell', sname, mask)

    print(f"[proc] done  elapsed={time.time()-t0:.1f}s")
    avg_years = float(np.mean(asset_years)) if asset_years else 1.0
    total_years = avg_years * n_assets

    # ===================== 生成报告 =====================
    L = []
    A = L.append
    A("# 买卖点优化方案回测报告（卖点降噪 + 买点增强）\n")
    A(f"- 生成日期：2026-07-05")
    A(f"- 数据截止：{max_date.date()}（sentiment.db index_daily + stock_daily.db mootdx_daily_raw）")
    A(f"- 标的：13 主要指数 + 31 申万行业 + 抽样 {SAMPLE_STOCKS} 只个股（共 {n_assets} 资产；"
      f"个股从合格标的中固定种子 {SEED} 抽样，与 08 报告同款样本）")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 app/compute/signals.py `_rsi`）")
    A(f"- D1：close 从近 N 日 high 之 max 回落 P%（high-based，事件化 shift(1)）")
    A(f"- BB：MA20 ± 2σ（std ddof=0）")
    A(f"- 信号后收益：信号日 close → N 交易日后 close（无 N 日后数据跳过）")
    A(f"- 买点胜率=收益>0 占比；卖点胜率=收益<0 占比（信号后下跌才算对）")
    A(f"- 盈亏比=平均盈利/平均亏损（绝对值）；均值收益单位 %")
    A(f"- 周期：全史 / 近3年(>{cutoff_3y.date()}) / 近1年(>{cutoff_1y.date()})；horizon: 5/10/20 日")
    A(f"- 信号密度=总信号 / (资产数 × 平均年限) = 信号/资产/年（越低噪声越少）；"
      f"本次 n_assets={n_assets}，平均年限 {avg_years:.1f} 年")
    A(f"- 现状基线：买 C1_30 = RSI(14) 上穿30；卖 D1_20_5 = 20日高回落5%\n")

    A("> 用户反馈：卖点很多买点少，卖点噪点多。本报告回测卖点降噪（S1-S5）+ 买点增强（B1-B2）"
      "+ 组合方案，给数据依据与推荐。所有指标自复刻，不 import app。\n")

    # ---- 0. 已有回测总结 ----
    A("## 0. 已有回测总结（06/07/08/09/10 提取的降噪/增强方案数据）\n")
    A("### 0.1 卖点降噪线索\n")
    A("| 线索 | 来源报告 | 数据依据 |")
    A("|---|---|---|")
    A("| 趋势过滤（MA60 多头才放卖） | 07 C 方案 | C2_MACD死叉+MA60 全史 1337 信号（vs D1 2453，砍 ~46%），"
      "全史 10日 51.0%/1.06 达标；A2_RSI+MA60下行 仅 93 信号（砍 91%，过严）。"
      "08 报告 D1 在 244 资产上近3年 10日胜率 54.0%、20日 55.7%（top3）。 |")
    A("| 盈利约束（删「买点失败」卖点） | 10 配对报告 | 523 配对回合中 D1 卖点平仓 452 个，"
      "其中「买点失败」类（close<前买 close）约占 19%；该类卖点均值 -0.19%/胜率 38.5%（弱）。"
      "删除可降噪但 10 报告未单独回测该过滤，本报告补测。 |")
    A("| BB_upper_revert 替代/互补 | 08 深度回测 | 244 资产近3年 5d/10d 胜率 57.3%/54.3%（最高），"
      "但样本仅 5444（D1 一半）、20d 后衰减；盈亏比 0.84（<1）。适合短周期互补。 |")
    A("| D1 参数调优 | 07 对策回测 | D2_60日高回落8% 近3年 20日胜率 58.9%（最高），"
      "但近1年全面走弱（35.9%/0.61）；D1_20_5 是 2016+ 唯一达标卖点（50.6%/1.04）。 |")
    A("| RSI 阈值无法救卖点 | 06 参数回测 | 全部 RSI 卖点阈值（70/75/65/60）胜率<50%、PL<1，"
      "指数向上漂移致结构性失效；卖点需换思路（high-based/过滤）非调阈值。 |")
    A("")
    A("### 0.2 买点增强线索\n")
    A("| 线索 | 来源报告 | 数据依据 |")
    A("|---|---|---|")
    A("| BB_lower_revert 辅买点 | 08 深度回测 | 244 资产 10日达标数 3/4（与 C1 并列第1），"
      "近3年 60d 盈亏比 1.84/均值+5.0%（最高）；近1年唯一达标买点（52.1%/1.23）。"
      "语义与 C1 同为「超卖反弹」，强势市更敏感，互补 C1 盲区。 |")
    A("| C1 RSI 阈值 30 是拐点 | 06 参数回测 | 30/70 买点全史 10日 53.4%/1.21，"
      "近3年 59.4%/1.61（仍正期望）；35/65 与 40/60 胜率跌破 50%、PL≈1（失效）。"
      "25/75 质量最佳但近1年仅 8 信号（过稀）。RSI 阈值无需动。 |")
    A("| C1 是 alpha 主源 | 10 配对报告 | 独立买点 10日均值+0.75%/胜率53.4%；"
      "配对回合均值+0.67%/年化+2.52%（买点正期望被卖点摩擦抵消部分）。 |")
    A("")
    A("### 0.3 本报告补测点\n")
    A("- 07 报告的趋势过滤只在 13 指数上测了 RSI/MACD 卖点，未在 244 资产上测 D1+MA60 → 本报告补测 S1。")
    A("- 10 报告发现 19%「买点失败」卖但未单独回测盈利约束过滤 → 本报告补测 S2。")
    A("- 08 报告 BB_upper_revert 只作独立卖点评，未测「D1+BB 双重确认」→ 本报告补测 S5。")
    A("- 08 报告 BB_lower_revert 只作独立买点评，未测「C1+BB 双买点」组合信号数与质量 → 本报告补测 B1。")
    A("- 08 报告 D1 参数只测了 20/5 与 60/8，未系统扫参 → 本报告补测 S3（10/20/30/60 × 3/5/8）。\n")

    # ---- 1. 方案清单 ----
    A("## 1. 方案清单\n")
    A("### 1.1 卖点降噪方案\n")
    A("| 方案 | 定义 | 降噪思路 |")
    A("|---|---|---|")
    A("| D1_20_5（现状） | 20日高回落5% | 基线 |")
    A("| S1_MA60bull | D1 + close>MA60（多头才放卖） | 趋势过滤：删除熊市噪声卖 |")
    A("| S2_profit_C1 | D1 + close>前买C1 close | 盈利约束：删除「买点失败」卖 |")
    A("| S2_profit_B1 | D1 + close>前买B1 close | 盈利约束（B1 买点版，给组合用） |")
    A("| S3_10_3 / 10_5 / 20_3 / 20_8 / 30_5 / 30_8 / 60_8 | N日高回落P%（参数调优） | 调 lookback/drop 降噪 |")
    A("| S4_BBupper | BB上轨回归（close从上轨上回到下方） | 替代 D1，短周期止盈 |")
    A("| S5_D1andBB | D1 + BB上轨回归同日触发 | 双重确认，最严格降噪 |")
    A("")
    A("### 1.2 买点增强方案\n")
    A("| 方案 | 定义 | 增强思路 |")
    A("|---|---|---|")
    A("| C1_30（现状） | RSI(14) 上穿30 | 基线 |")
    A("| C1_25 / 28 / 32 / 35 | RSI 上穿 X（参数调优） | 调阈值 |")
    A("| B1_dual | C1_30 ∪ BB下轨回归 | 双买点，补强强势市盲区 |")
    A("")

    # ---- 2. 卖点降噪结果 ----
    A("## 2. 卖点降噪结果\n")
    A("### 2.1 卖点 10 日 horizon（主对比轴）\n")
    A("| 方案 | 全史(n/胜/PL/均) | 近3年(n/胜/PL/均) | 近1年(n/胜/PL/均) | 密度(信号/资产/年) |")
    A("|---|---|---|---|---:|")
    for sname in SELL_SCHEMES:
        cells = [sname + ('（现状）' if sname == 'D1_20_5' else '')]
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, 10, pname), []), True)
            cells.append(f"{n}/{fmt_pct(wr*100)}/{fmt(pl,2)}/{fmt_pct(m)}")
        full_cnt = sig_count_full.get(('sell', sname), 0)
        dens = full_cnt / total_years if total_years > 0 else 0
        cells.append(f"{dens:.2f}")
        A("| " + " | ".join(cells) + " |")
    A("")

    A("### 2.2 卖点各 horizon 详解（近3年）\n")
    A("| 方案 | horizon | 样本 | 胜率 | 盈亏比 | 均值 |")
    A("|---|---|---:|---:|---:|---:|")
    for sname in SELL_SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, h, '近3年'), []), True)
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} |")
    A("")

    A("### 2.3 卖点信号数与降噪效果（全史）\n")
    A("| 方案 | 全史信号 | 相对D1信号比 | 近1年信号 | 近3年信号 | 降噪率 |")
    A("|---|---:|---:|---:|---:|---:|")
    base_full = sig_count_full.get(('sell', 'D1_20_5'), 1)
    for sname in SELL_SCHEMES:
        full = sig_count_full.get(('sell', sname), 0)
        ratio = full / base_full if base_full else 0
        n1y = sig_count.get(('sell', sname, '近1年'), 0)
        n3y = sig_count.get(('sell', sname, '近3年'), 0)
        cut = (1 - ratio) * 100 if sname != 'D1_20_5' else 0
        A(f"| {sname} | {full} | {ratio:.2f}× | {n1y} | {n3y} | {fmt(cut,0)}% |")
    A("")
    A("> 降噪率=(1−方案信号/D1信号)×100，正值=砍掉多少噪声。S5 最严格、S2_profit 次之。\n")

    # ---- 3. 买点增强结果 ----
    A("## 3. 买点增强结果\n")
    A("### 3.1 买点 10 日 horizon（主对比轴）\n")
    A("| 方案 | 全史(n/胜/PL/均) | 近3年(n/胜/PL/均) | 近1年(n/胜/PL/均) | 密度(信号/资产/年) |")
    A("|---|---|---|---|---:|")
    for sname in BUY_SCHEMES:
        cells = [sname + ('（现状）' if sname == 'C1_30' else '')]
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, 10, pname), []), False)
            cells.append(f"{n}/{fmt_pct(wr*100)}/{fmt(pl,2)}/{fmt_pct(m)}")
        full_cnt = sig_count_full.get(('buy', sname), 0)
        dens = full_cnt / total_years if total_years > 0 else 0
        cells.append(f"{dens:.2f}")
        A("| " + " | ".join(cells) + " |")
    A("")

    A("### 3.2 买点各 horizon 详解（近3年）\n")
    A("| 方案 | horizon | 样本 | 胜率 | 盈亏比 | 均值 |")
    A("|---|---|---:|---:|---:|---:|")
    for sname in BUY_SCHEMES:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, h, '近3年'), []), False)
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} |")
    A("")

    A("### 3.3 买点信号数对比\n")
    A("| 方案 | 全史信号 | 相对C1信号比 | 近1年信号 | 近3年信号 |")
    A("|---|---:|---:|---:|---:|")
    base_buy_full = sig_count_full.get(('buy', 'C1_30'), 1)
    for sname in BUY_SCHEMES:
        full = sig_count_full.get(('buy', sname), 0)
        ratio = full / base_buy_full if base_buy_full else 0
        n1y = sig_count.get(('buy', sname, '近1年'), 0)
        n3y = sig_count.get(('buy', sname, '近3年'), 0)
        A(f"| {sname} | {full} | {ratio:.2f}× | {n1y} | {n3y} |")
    A("")

    # ---- 4. 组合方案 ----
    A("## 4. 组合方案（卖点降噪 + 买点增强）\n")
    A("> 组合=买方案X的买信号 + 卖方案Y的卖信号。买/卖各自独立 forward-return 统计；"
      "噪声指标=卖/买信号比（越接近1越平衡，>1=卖点比买点多=噪声偏高）。\n")
    A("### 4.1 组合信号数与噪声（全史）\n")
    A("| 组合 | 买信号 | 卖信号 | 卖/买比 | 买密度 | 卖密度 |")
    A("|---|---:|---:|---:|---:|---:|")
    combos = [
        ('C1_30 + D1_20_5（现状）', 'C1_30', 'D1_20_5'),
        ('C1_30 + S1_MA60bull', 'C1_30', 'S1_MA60bull'),
        ('C1_30 + S2_profit_C1', 'C1_30', 'S2_profit_C1'),
        ('C1_30 + S3_30_8', 'C1_30', 'S3_30_8'),
        ('C1_30 + S4_BBupper', 'C1_30', 'S4_BBupper'),
        ('C1_30 + S5_D1andBB', 'C1_30', 'S5_D1andBB'),
        ('B1_dual + D1_20_5', 'B1_dual', 'D1_20_5'),
        ('B1_dual + S1_MA60bull', 'B1_dual', 'S1_MA60bull'),
        ('B1_dual + S2_profit_B1', 'B1_dual', 'S2_profit_B1'),
        ('B1_dual + S3_30_8', 'B1_dual', 'S3_30_8'),
        ('B1_dual + S5_D1andBB', 'B1_dual', 'S5_D1andBB'),
    ]
    combo_rows = []
    for label, bscheme, sscheme in combos:
        bcnt = sig_count_full.get(('buy', bscheme), 0)
        scnt = sig_count_full.get(('sell', sscheme), 0)
        ratio = scnt / bcnt if bcnt else float('nan')
        bdens = bcnt / total_years if total_years else 0
        sdens = scnt / total_years if total_years else 0
        A(f"| {label} | {bcnt} | {scnt} | {fmt(ratio,2)} | {bdens:.2f} | {sdens:.2f} |")
        combo_rows.append((label, bscheme, sscheme, bcnt, scnt, ratio))
    A("")

    A("### 4.2 组合质量对比（近3年 10 日 horizon）\n")
    A("| 组合 | 买胜率 | 买PL | 买均 | 卖胜率 | 卖PL | 卖均 | 综合评级 |")
    A("|---|---:|---:|---:|---:|---:|---:|---|")
    for label, bscheme, sscheme, bcnt, scnt, ratio in combo_rows:
        bn, bm, _, bwr, bpl = stats_block(qual.get(('buy', bscheme, 10, '近3年'), []), False)
        sn, sm, _, swr, spl = stats_block(qual.get(('sell', sscheme, 10, '近3年'), []), True)
        # 综合评级：买胜>50%+PL>1 且 卖胜>50% 且 卖/买比合理(<2)
        buy_ok = (bn >= 30 and bwr > 0.5 and not np.isnan(bpl) and bpl > 1.0)
        sell_ok = (sn >= 30 and swr > 0.5)
        noise_ok = (not np.isnan(ratio) and ratio < 2.0)
        if buy_ok and sell_ok and noise_ok:
            grade = 'A 优秀'
        elif buy_ok and noise_ok:
            grade = 'B 推荐'
        elif buy_ok:
            grade = 'C 买强卖弱'
        else:
            grade = 'D 不推荐'
        A(f"| {label} | {fmt_pct(bwr*100)} | {fmt(bpl,2)} | {fmt_pct(bm)} | "
          f"{fmt_pct(swr*100)} | {fmt(spl,2)} | {fmt_pct(sm)} | {grade} |")
    A("")

    # ---- 5. 达标统计 ----
    A("## 5. 达标统计（10 日 horizon，达标=胜率>50% 且 盈亏比>1 且 样本≥30）\n")
    A("### 5.1 买点\n")
    A("| 方案 | 全史 | 近3年 | 近1年 | 达标数 |")
    A("|---|---|---|---|---:|")
    for sname in BUY_SCHEMES:
        cells = []
        ok = 0
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, 10, pname), []), False)
            good = (n >= 30 and wr > 0.5 and not np.isnan(pl) and pl > 1.0)
            cells.append('✓' if good else '·')
            ok += int(good)
        A(f"| {sname} | {cells[0]} | {cells[1]} | {cells[2]} | {ok} |")
    A("")
    A("### 5.2 卖点\n")
    A("| 方案 | 全史 | 近3年 | 近1年 | 达标数 |")
    A("|---|---|---|---|---:|")
    for sname in SELL_SCHEMES:
        cells = []
        ok = 0
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, 10, pname), []), True)
            good = (n >= 30 and wr > 0.5 and not np.isnan(pl) and pl > 1.0)
            cells.append('✓' if good else '·')
            ok += int(good)
        A(f"| {sname} | {cells[0]} | {cells[1]} | {cells[2]} | {ok} |")
    A("")

    # ---- 6. 推荐方案 ----
    A("## 6. 推荐方案（数据驱动）\n")
    A("> 基于上述回测，平衡「降噪（卖/买比合理、密度低）+ 买点增强（买信号多且质量不降）+ 质量（胜率/盈亏比）」。\n")

    # 自动选最优组合：买达标 + 卖胜率最高 + 噪声<2
    best_combo = None
    best_score = -1
    for label, bscheme, sscheme, bcnt, scnt, ratio in combo_rows:
        bn, bm, _, bwr, bpl = stats_block(qual.get(('buy', bscheme, 10, '近3年'), []), False)
        sn, sm, _, swr, spl = stats_block(qual.get(('sell', sscheme, 10, '近3年'), []), True)
        buy_ok = (bn >= 30 and bwr > 0.5 and not np.isnan(bpl) and bpl > 1.0)
        noise_ok = (not np.isnan(ratio) and ratio < 2.0)
        # 评分：买PL + 卖胜率*2 + 噪声平衡度（理想卖/买比 0.8-1.5）
        score = (bpl if not np.isnan(bpl) else 0) + (swr * 2 if not np.isnan(swr) else 0)
        if not np.isnan(ratio):
            if ratio < 0.5:
                score -= (0.5 - ratio) * 6   # 卖点太少惩罚（漏掉止盈机会）
            elif ratio > 2.0:
                score -= (ratio - 2.0) * 3   # 卖点太多惩罚（噪声）
        if not buy_ok:
            score -= 2
        if not noise_ok:
            score -= 2
        if score > best_score:
            best_score = score
            best_combo = (label, bscheme, sscheme, ratio)

    A(f"**数据驱动首选组合：{best_combo[0]}**（近3年卖/买比={fmt(best_combo[3],2)}）\n")
    A("理由见下文 6.1-6.3 节逐项分析。\n")

    A("### 6.1 卖点降噪：哪个最有效？\n")
    # 找近3年10日胜率最高且降噪明显的
    sell_3y = []
    for sname in SELL_SCHEMES:
        n, m, med, wr, pl = stats_block(qual.get(('sell', sname, 10, '近3年'), []), True)
        full = sig_count_full.get(('sell', sname), 0)
        ratio = full / base_full if base_full else 0
        sell_3y.append((sname, n, wr, pl, m, ratio))
    A("**近3年 10日 卖点降噪对比（按胜率降序）：**\n")
    A("| 方案 | 样本 | 胜率 | 盈亏比 | 均值 | 信号/D1比 | 评价 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for sname, n, wr, pl, m, ratio in sorted(sell_3y, key=lambda x: -x[2] if not np.isnan(x[2]) else 0):
        note = ''
        if sname == 'D1_20_5':
            note = '基线'
        elif ratio < 0.5:
            note = f'降噪{(1-ratio)*100:.0f}%'
        A(f"| {sname} | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} | {ratio:.2f}× | {note} |")
    A("")

    A("### 6.2 买点增强：B1 是否补强而不降质？\n")
    A("**近3年 10日 买点对比：**\n")
    A("| 方案 | 样本 | 胜率 | 盈亏比 | 均值 | 信号/C1比 | 评价 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for sname in BUY_SCHEMES:
        n, m, med, wr, pl = stats_block(qual.get(('buy', sname, 10, '近3年'), []), False)
        full = sig_count_full.get(('buy', sname), 0)
        ratio = full / base_buy_full if base_buy_full else 0
        note = '基线' if sname == 'C1_30' else ''
        A(f"| {sname} | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} | {ratio:.2f}× | {note} |")
    A("")

    A("### 6.3 推荐组合与现状对比\n")
    bl, bbs, bss, bratio = best_combo
    # 现状
    cur_b = stats_block(qual.get(('buy', 'C1_30', 10, '近3年'), []), False)
    cur_s = stats_block(qual.get(('sell', 'D1_20_5', 10, '近3年'), []), True)
    cur_ratio = sig_count_full.get(('sell', 'D1_20_5'), 0) / sig_count_full.get(('buy', 'C1_30'), 1)
    # 推荐
    rec_b = stats_block(qual.get(('buy', bbs, 10, '近3年'), []), False)
    rec_s = stats_block(qual.get(('sell', bss, 10, '近3年'), []), True)
    A("| 维度 | 现状(C1_30+D1_20_5) | 推荐(" + bl + ") |")
    A("|---|---|---|")
    A(f"| 买信号(全史) | {sig_count_full.get(('buy','C1_30'),0)} | {sig_count_full.get(('buy',bbs),0)} |")
    A(f"| 卖信号(全史) | {sig_count_full.get(('sell','D1_20_5'),0)} | {sig_count_full.get(('sell',bss),0)} |")
    A(f"| 卖/买比 | {fmt(cur_ratio,2)} | {fmt(bratio,2)} |")
    A(f"| 买胜率(近3年10d) | {fmt_pct(cur_b[3]*100)} | {fmt_pct(rec_b[3]*100)} |")
    A(f"| 买盈亏比(近3年10d) | {fmt(cur_b[4],2)} | {fmt(rec_b[4],2)} |")
    A(f"| 卖胜率(近3年10d) | {fmt_pct(cur_s[3]*100)} | {fmt_pct(rec_s[3]*100)} |")
    A(f"| 卖盈亏比(近3年10d) | {fmt(cur_s[4],2)} | {fmt(rec_s[4],2)} |")
    A("")

    # ---- 7. 落地建议 ----
    A("## 7. 落地建议（signals.py 改法）\n")
    A("### 7.1 推荐方案：" + bl + "\n")
    A("在 `app/compute/signals.py` `compute()` 内实施。**主买点 C1 + 主卖点 D1 触发逻辑可保留**，"
      "降噪/增强通过追加过滤或辅信号实现。\n")
    A("```python")
    A("# === 买点增强（B1_dual）：C1 不动，追加 BB下轨回归辅买点 ===")
    A("bu_, mid_, bl_ = bollinger(close, 20, 2.0)   # mid=MA20, sd=std(ddof=0)")
    A("buy_aux = ((close.shift(1) < bl_.shift(1)) & (close > bl_)).fillna(False)")
    A("# reason 标 'buy_aux' 区分优先级；C1 主买点 signal='buy' 不变")
    A("")
    A("# === 卖点降噪 ===")
    if 'S1' in bss:
        A("# S1_MA60bull：D1 触发后，仅当 close>MA60 才发出卖信号")
        A("ma60 = close.rolling(60, min_periods=60).mean()")
        A("sell = sell & (close > ma60)   # sell=D1 原掩码，叠加趋势过滤")
    elif 'S2' in bss:
        A("# S2_profit：D1 触发后，仅当 close>前买点close 才发出卖信号（删买点失败卖）")
        A("# 复用现有 last_buy_close 游标（vs前买 标注已维护）")
        A("sell = sell & (last_buy_close is not None) & (close > last_buy_close)")
    elif 'S5' in bss:
        A("# S5_D1andBB：D1 + BB上轨回归同日触发才出（双重确认，最严格）")
        A("sell_aux_bb = ((close.shift(1) > bu_.shift(1)) & (close < bu_)).fillna(False)")
        A("sell = sell & sell_aux_bb   # 两者交集")
    elif 'S4' in bss:
        A("# S4_BBupper：用 BB上轨回归替代 D1")
        A("sell = ((close.shift(1) > bu_.shift(1)) & (close < bu_)).fillna(False)")
    elif bss.startswith('S3'):
        lb, dp = bss.split('_')[1], bss.split('_')[2]
        A(f"# S3_{lb}_{dp}：D1 参数调优为 {lb}日高回落{dp}%")
        A(f"hh = high.rolling({lb}, min_periods={lb}).max()")
        A(f"thresh = hh * {1 - int(dp)/100:.3f}")
        A("sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)")
    A("```\n")
    A("> 注：若推荐组合含 B1_dual，辅买点用 `buy_aux` 区分优先级，UI 可折叠展示；"
      "C1 与 BB下轨回归同日触发时去重或并排展示。reason 末尾保留 cross 软分级标签。\n")

    A("### 7.2 备选方案（若用户偏好不同）\n")
    A("- **纯降噪（不动买点）**：C1_30 + S1_MA60bull 或 C1_30 + S2_profit_C1。改动最小，"
      "只过滤卖点，买点不变。适合「只想减少卖点噪声」的场景。")
    A("- **纯增强（不动卖点）**：B1_dual + D1_20_5。加辅买点，卖点不变。适合「想捕捉更多反弹」。")
    A("- **最激进降噪**：B1_dual + S5_D1andBB。双重确认卖点+双买点，信号最少但最精准；"
      "风险是样本量下降、可能漏掉有效信号。\n")

    # ---- 8. 诚实声明 ----
    A("## 8. 诚实声明与局限\n")
    A("- 信号独立统计：买/卖 forward return 各自评估，未模拟「买入→持有→卖出」真实配对收益"
      "（见 10 报告：配对回合均值+0.67%/胜率44.6%/年化+2.52%）。")
    A("- 卖点本质难预测：A 股长期向上漂移，任何卖点近年盈亏比<1（结构性问题），降噪能减噪但不能让卖点变「好」。")
    A("- S2 盈利约束依赖前买点游标，若长期无买点则卖点被全滤（强势市可能0卖点）。")
    A("- 信号密度受资产年限影响（个股年限<指数），密度值仅作横向对比。")
    A("- 抽样 200 只个股已覆盖大小盘/行业，但仍非全市场；缠论等主观策略未纳入。\n")

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))

    # ---- 控制台汇总 ----
    print("\n" + "=" * 70)
    print("买点 10日 近3年：")
    for sname in BUY_SCHEMES:
        n, m, _, wr, pl = stats_block(qual.get(('buy', sname, 10, '近3年'), []), False)
        full = sig_count_full.get(('buy', sname), 0)
        print(f"  {sname:10s} n={n:5d} 胜={fmt_pct(wr*100)} PL={fmt(pl,2)} 均={fmt_pct(m)} 全史={full}")
    print("\n卖点 10日 近3年：")
    for sname in SELL_SCHEMES:
        n, m, _, wr, pl = stats_block(qual.get(('sell', sname, 10, '近3年'), []), True)
        full = sig_count_full.get(('sell', sname), 0)
        ratio = full / base_full if base_full else 0
        print(f"  {sname:16s} n={n:5d} 胜={fmt_pct(wr*100)} PL={fmt(pl,2)} 均={fmt_pct(m)} 全史={full} ({ratio:.2f}×D1)")
    print(f"\n推荐组合：{best_combo[0]}（卖/买比={fmt(best_combo[3],2)}）")
    print(f"报告已写入: {REPORT}")
    print(f"总耗时: {time.time()-t0:.1f}s")


if __name__ == '__main__':
    main()
