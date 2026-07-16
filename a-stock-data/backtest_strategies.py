"""买卖点策略深度回测（独立脚本，不 import app）。

目的：扩大回测范围（13 主要指数 + 3 红利 + 31 sw 行业 + 抽样 200 只全 A 股个股）
+ 引入经典策略（唐奇安/海龟、布林带、Supertrend、双均线、MACD、KDJ、量价、ATR 止损）
+ 对比当前 C1 买点（RSI 上穿30）+ D1 卖点（20 日高回落5%）。

方法：
- 信号后收益 = 信号日 close → N 交易日后 close（无 N 日后数据则跳过，shift(-h) 自然 NaN）。
- 买点胜率 = 收益>0 占比；卖点胜率 = 收益<0 占比（信号后下跌才算对）。
- 盈亏比 = 平均盈利（绝对值）/ 平均亏损（绝对值）。
- 周期：全史 / 近10年 / 近3年 / 近1年；horizon: 5/10/20/60 日。

所有指标自复刻（RSI EWM α=1/14 adjust=False 复刻 app/compute/signals.py `_rsi`）。
"""
import sqlite3
import time
import numpy as np
import pandas as pd

STOCK_DB = '/Users/linhuichen/code/trade/data/stock_daily.db'
SENT_DB = '/Users/linhuichen/code/trade/data/sentiment.db'
REPORT = '/Users/linhuichen/code/trade/08-买卖点策略深度回测.md'

# 13 主要指数 + 3 红利（与 06/07 报告一致）
MAIN_INDICES = ['sh', 'sz', 'hs300', 'csi500', 'csi1000', 'cyb', 'kc50',
                'hsi', 'hscei', 'hstech', 'csi_div', 'div_lowvol', 'sz_div']
# 31 sw 行业指数（index_daily 里 sw_ 开头）
SW_INDICES = [f'sw_801{i:03d}' for i in
              [10, 30, 40, 50, 80, 110, 120, 130, 140, 150, 160, 170, 180,
               200, 210, 230, 710, 720, 730, 740, 750, 760, 770, 780, 790,
               880, 890, 950, 960, 970, 980]]

HORIZONS = (5, 10, 20, 60)
SAMPLE_STOCKS = 200
SEED = 20260705


# ===================== 指标 =====================

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """复刻 signals._rsi：EWM α=1/period, adjust=False。"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss
    return (100 - 100 / (1 + rs))


def atr(high, low, close, period=14):
    tr = pd.concat([(high - low),
                    (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def supertrend(high, low, close, period=10, mult=3.0):
    """返回 trend: +1 上涨 / -1 下跌（np.array, aligned index）。"""
    a = atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    h, l, c, u, lb = (high.values, low.values, close.values,
                      upper.values, lower.values)
    n = len(c)
    fu = u.copy()
    fl = lb.copy()
    trend = np.ones(n)
    for i in range(1, n):
        if np.isnan(u[i]) or np.isnan(c[i - 1]):
            continue
        # final upper: 若 prev close <= prev final upper，则取 min(prev fu, u)
        if c[i - 1] <= fu[i - 1]:
            fu[i] = min(u[i], fu[i - 1]) if not np.isnan(fu[i - 1]) else u[i]
        else:
            fu[i] = u[i]
        if c[i - 1] >= fl[i - 1]:
            fl[i] = max(lb[i], fl[i - 1]) if not np.isnan(fl[i - 1]) else lb[i]
        else:
            fl[i] = lb[i]
        # trend
        if c[i] > fu[i - 1] if not np.isnan(fu[i - 1]) else False:
            trend[i] = 1
        elif c[i] < fl[i - 1] if not np.isnan(fl[i - 1]) else False:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return pd.Series(trend, index=close.index), pd.Series(fu, index=close.index), pd.Series(fl, index=close.index)


def ma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def macd(close, fast=12, slow=26, signal=9):
    ef = close.ewm(alpha=2 / (fast + 1), adjust=False).mean()
    es = close.ewm(alpha=2 / (slow + 1), adjust=False).mean()
    dif = ef - es
    dea = dif.ewm(alpha=2 / (signal + 1), adjust=False).mean()
    return dif, dea


def kdj(high, low, close, n=9):
    ln = low.rolling(n, min_periods=n).min()
    hn = high.rolling(n, min_periods=n).max()
    rsv = (close - ln) / (hn - ln) * 100.0
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def bollinger(close, n=20, k=2.0):
    mid = close.rolling(n, min_periods=n).mean()
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid + k * sd, mid, mid - k * sd


def donchian(high, low, n):
    return high.rolling(n, min_periods=n).max(), low.rolling(n, min_periods=n).min()


# ===================== 信号生成器 =====================
# 每个返回 bool Series，对齐 close.index。事件化（穿越当日标 1 次）。

def _cross_up(curr, prev, level):
    return ((prev <= level) & (curr > level)).fillna(False)


def _cross_down(curr, prev, level):
    return ((prev >= level) & (curr < level)).fillna(False)


def gen_buy_signals(df):
    """返回 {name: bool Series}。df 含 close/high/low/volume(可能NaN)。"""
    close = df['close']; high = df['high']; low = df['low']
    vol = df.get('volume')
    out = {}
    r = rsi(close, 14); rp = r.shift(1)
    # 1. C1 基线：RSI 上穿 30
    out['C1_RSI30'] = _cross_up(r, rp, 30)
    # 2. 唐奇安 20 日突破买（close 突破前 20 日最高，不含当日）
    du20 = high.rolling(20, min_periods=20).max().shift(1)
    out['Donchian20_up'] = ((close > du20) & (close.shift(1) <= du20.shift(1))).fillna(False)
    # 3. 海龟 55 日突破买
    du55 = high.rolling(55, min_periods=55).max().shift(1)
    out['Donchian55_up'] = ((close > du55) & (close.shift(1) <= du55.shift(1))).fillna(False)
    # 4. 布林下轨回归买（close 从下轨下方回到上方）
    _, _, bl = bollinger(close, 20, 2.0)
    out['BB_lower_revert'] = ((close.shift(1) < bl.shift(1)) & (close > bl)).fillna(False)
    # 5. 布林上轨突破买
    bu, _, _ = bollinger(close, 20, 2.0)
    out['BB_upper_break'] = ((close.shift(1) <= bu.shift(1)) & (close > bu)).fillna(False)
    # 6. Supertrend 翻多
    st, _, _ = supertrend(high, low, close, 10, 3.0)
    out['Supertrend_buy'] = ((st.shift(1) == -1) & (st == 1)).fillna(False)
    # 7. MA5/MA20 金叉
    m5, m20 = ma(close, 5), ma(close, 20)
    out['MA_golden_5_20'] = ((m5.shift(1) <= m20.shift(1)) & (m5 > m20)).fillna(False)
    # 8. MA10/MA60 金叉
    m10, m60 = ma(close, 10), ma(close, 60)
    out['MA_golden_10_60'] = ((m10.shift(1) <= m60.shift(1)) & (m10 > m60)).fillna(False)
    # 9. MACD 金叉
    dif, dea = macd(close)
    out['MACD_golden'] = ((dif.shift(1) <= dea.shift(1)) & (dif > dea)).fillna(False)
    # 10. KDJ 金叉（超卖区 K<35）
    k, d, _ = kdj(high, low, close, 9)
    out['KDJ_golden_oversold'] = (((k.shift(1) <= d.shift(1)) & (k > d)) & (k < 35)).fillna(False)
    # 11. 放量突破买（vol > 2×20日均量 且 close 涨 >2%）—— 指数无 vol 自动跳过
    if vol is not None and vol.notna().sum() > 100 and (vol > 0).mean() > 0.5:
        vma = vol.rolling(20, min_periods=10).mean()
        out['Vol_breakout'] = ((vol > 2 * vma) & (close.pct_change() > 0.02)).fillna(False)
    return out


def gen_sell_signals(df):
    close = df['close']; high = df['high']; low = df['low']
    out = {}
    # 0. B0 旧基线：RSI 下穿 70
    r = rsi(close, 14); rp = r.shift(1)
    out['B0_RSI70'] = _cross_down(r, rp, 70)
    # 1. D1 基线：20 日高（high）回落 5%
    hh20 = high.rolling(20, min_periods=20).max()
    th = hh20 * 0.95
    out['D1_high20_drop5'] = ((close.shift(1) >= th.shift(1)) & (close < th)).fillna(False)
    # 2. 海龟退出：close 跌破前 10 日最低（不含当日）
    dl10 = low.rolling(10, min_periods=10).min().shift(1)
    out['Donchian10_down'] = ((close < dl10) & (close.shift(1) >= dl10.shift(1))).fillna(False)
    # 3. 唐奇安 20 日跌破
    dl20 = low.rolling(20, min_periods=20).min().shift(1)
    out['Donchian20_down'] = ((close < dl20) & (close.shift(1) >= dl20.shift(1))).fillna(False)
    # 4. 布林上轨回归卖（close 从上轨上方回到下方）
    bu, _, _ = bollinger(close, 20, 2.0)
    out['BB_upper_revert'] = ((close.shift(1) > bu.shift(1)) & (close < bu)).fillna(False)
    # 5. 布林中轨破（close 跌破 MA20）
    _, mid, _ = bollinger(close, 20, 2.0)
    out['BB_middle_break'] = ((close.shift(1) >= mid.shift(1)) & (close < mid)).fillna(False)
    # 6. Supertrend 翻空
    st, _, _ = supertrend(high, low, close, 10, 3.0)
    out['Supertrend_sell'] = ((st.shift(1) == 1) & (st == -1)).fillna(False)
    # 7. MA5/MA20 死叉
    m5, m20 = ma(close, 5), ma(close, 20)
    out['MA_death_5_20'] = ((m5.shift(1) >= m20.shift(1)) & (m5 < m20)).fillna(False)
    # 8. MACD 死叉
    dif, dea = macd(close)
    out['MACD_death'] = ((dif.shift(1) >= dea.shift(1)) & (dif < dea)).fillna(False)
    # 9. ATR 追踪止损（close < 近20日最高close - 3×ATR(14)）
    a = atr(high, low, close, 14)
    hc20 = close.rolling(20, min_periods=20).max()
    out['ATR_trail_stop'] = (close < (hc20 - 3 * a)).fillna(False) & \
        (close.shift(1) >= (hc20.shift(1) - 3 * a.shift(1))).fillna(False)
    # 10. KDJ 死叉（超买区 K>70）
    k, d, _ = kdj(high, low, close, 9)
    out['KDJ_death_overbought'] = (((k.shift(1) >= d.shift(1)) & (k < d)) & (k > 70)).fillna(False)
    return out


# ===================== 数据加载 =====================

def load_index_series(con, iid):
    """从 sentiment.db index_daily 读 OHLC（无 volume）。返回 df or None。"""
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close,amount FROM index_daily "
        "WHERE index_id=? ORDER BY date", con, params=(iid,),
        parse_dates=['date'])
    if len(df) < 60:
        return None
    df = df.set_index('date').astype(float)
    return df[['open', 'high', 'low', 'close']]  # 指数无 volume


def sample_stock_codes(con, k):
    """从 mootdx_daily_raw 抽样 k 只个股（要求 >=1500 行且数据延至 2020+）。"""
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
    # 过滤异常（close<=0）
    df = df[df['close'] > 0]
    if len(df) < 60:
        return None
    return df[['open', 'high', 'low', 'close', 'volume']]


# ===================== 统计 =====================

def stats_block(returns, is_sell):
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


# ===================== 策略实验室 JSON =====================

STRATEGY_DESC = {
    # 买点 11
    'C1_RSI30': 'RSI超卖回归(C1基线)',
    'Donchian20_up': '唐奇安20日突破买',
    'Donchian55_up': '海龟55日突破买',
    'BB_lower_revert': '布林下轨回归买',
    'BB_upper_break': '布林上轨突破买',
    'Supertrend_buy': 'Supertrend翻多',
    'MA_golden_5_20': 'MA5/MA20金叉',
    'MA_golden_10_60': 'MA10/MA60金叉',
    'MACD_golden': 'MACD金叉',
    'KDJ_golden_oversold': 'KDJ金叉超卖',
    'Vol_breakout': '放量突破买',
    # 卖点 11
    'B0_RSI70': 'RSI超买结束(B0旧基线)',
    'D1_high20_drop5': '20日高回落5%(D1基线)',
    'Donchian10_down': '海龟退出10日跌破',
    'Donchian20_down': '唐奇安20日跌破',
    'BB_upper_revert': '布林上轨回落',
    'BB_middle_break': '布林中轨破',
    'Supertrend_sell': 'Supertrend翻空',
    'MA_death_5_20': 'MA5/MA20死叉',
    'MACD_death': 'MACD死叉',
    'ATR_trail_stop': 'ATR追踪止损',
    'KDJ_death_overbought': 'KDJ死叉超买',
}


# ===================== 主流程 =====================

def main():
    t0 = time.time()
    # ---- 加载资产 ----
    scon = sqlite3.connect(SENT_DB)
    assets = []  # list of (kind, name, df)
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
    print(f"[load] assets={len(assets)} (idx+sw+stk)  elapsed={time.time()-t0:.1f}s")

    # ---- 周期 cutoff ----
    max_date = max(a[2].index.max() for a in assets)
    cutoff_1y = max_date - pd.Timedelta(days=365)
    cutoff_3y = max_date - pd.Timedelta(days=365 * 3)
    cutoff_5y = max_date - pd.Timedelta(days=365 * 5)
    cutoff_10y = max_date - pd.Timedelta(days=365 * 10)
    PERIODS = [('全史', None), ('近10年', cutoff_10y), ('近3年', cutoff_3y), ('近1年', cutoff_1y)]
    # 策略实验室 JSON 用：含近5年窗口（08 报告 MD 仍用 4 窗口 PERIODS，格式不变）
    PERIODS_JSON = [('全史', None), ('近10年', cutoff_10y), ('近5年', cutoff_5y),
                    ('近3年', cutoff_3y), ('近1年', cutoff_1y)]

    # ---- 聚合容器 ----
    # qual[(side, strategy, horizon, period_name)] = list[returns]
    from collections import defaultdict
    qual = defaultdict(list)
    # cnt[(side,strategy,period_name)] = total signal count (跨 horizon 用 5日近端计数近似)
    sig_count = defaultdict(int)
    # 收集各策略可用资产数（含信号策略是否在该资产生成过）
    asset_kind_count = defaultdict(lambda: defaultdict(int))

    BUY_ORDER = ['C1_RSI30', 'Donchian20_up', 'Donchian55_up', 'BB_lower_revert',
                 'BB_upper_break', 'Supertrend_buy', 'MA_golden_5_20',
                 'MA_golden_10_60', 'MACD_golden', 'KDJ_golden_oversold', 'Vol_breakout']
    SELL_ORDER = ['B0_RSI70', 'D1_high20_drop5', 'Donchian10_down', 'Donchian20_down',
                  'BB_upper_revert', 'BB_middle_break', 'Supertrend_sell',
                  'MA_death_5_20', 'MACD_death', 'ATR_trail_stop', 'KDJ_death_overbought']

    for ai, (kind, name, df) in enumerate(assets):
        if (ai + 1) % 25 == 0:
            print(f"  [proc] {ai+1}/{len(assets)}  elapsed={time.time()-t0:.1f}s")
        try:
            buys = gen_buy_signals(df)
            sells = gen_sell_signals(df)
        except Exception as e:
            continue
        close = df['close']
        # 预计算 forward returns（horizon → Series 对齐 close）
        fwd = {h: (close.shift(-h) / close - 1.0) * 100.0 for h in HORIZONS}
        idx = close.index

        def accumulate(side, strat, mask):
            if mask is None or mask.sum() == 0:
                return
            asset_kind_count[strat][kind] += 1
            sig_dates = idx[mask]
            for pname, cut in PERIODS_JSON:
                if cut is not None:
                    sd = sig_dates[sig_dates > cut]
                else:
                    sd = sig_dates
                if len(sd) == 0:
                    continue
                if pname == '近1年':  # 用 5 日 horizon 近端计数
                    sig_count[(side, strat, pname)] += int((fwd[5].reindex(sd).notna()).sum())
                for h in HORIZONS:
                    r = fwd[h].reindex(sd).dropna().values
                    if len(r):
                        qual[(side, strat, h, pname)].extend(r.tolist())

        for sname, mask in buys.items():
            accumulate('buy', sname, mask)
        for sname, mask in sells.items():
            accumulate('sell', sname, mask)

    print(f"[proc] done  elapsed={time.time()-t0:.1f}s")

    # ===================== 生成报告 =====================
    L = []
    A = L.append
    A("# 买卖点策略深度回测报告\n")
    A(f"- 生成日期：2026-07-05")
    A(f"- 数据截止：{max_date.date()}（stock_daily.db mootdx_daily_raw + sentiment.db index_daily）")
    A(f"- 标的：13 主要指数 + 3 红利 + 31 申万行业 + 抽样 {SAMPLE_STOCKS} 只全 A 股个股"
      f"（共 {len(assets)} 个序列；个股从 3609 只合格标的中固定种子抽样，覆盖大小盘/行业/上市时长）")
    A(f"- RSI 算法：period=14, EWM α=1/14, adjust=False（复刻 app/compute/signals.py `_rsi`）")
    A(f"- 信号后收益：信号日 close → N 交易日后 close（无 N 日后数据则跳过）")
    A(f"- 买点胜率=收益>0 占比；卖点胜率=收益<0 占比（信号后下跌才算对）")
    A(f"- 盈亏比=平均盈利/平均亏损（绝对值）；均值收益单位 %")
    A(f"- 周期：全史 / 近10年(>{cutoff_10y.date()}) / 近3年(>{cutoff_3y.date()}) / 近1年(>{cutoff_1y.date()})")
    A(f"- 持有 horizon：5 / 10 / 20 / 60 交易日")
    A(f"- 当前方案基线：买 C1 = RSI(14) 上穿30；卖 D1 = 20日高(high)回落5%\n")

    A("> **WebSearch 说明**：本次环境 WebSearch 工具多次调用均返回空结果（5 个不同查询均无内容），"
      "无法获取实时网页。下列策略清单基于经典技术分析的公认定义（教科书级、稳定），"
      "并附权威参考来源 URL（Investopedia / Wikipedia / 原始论文）。回测部分完全独立、可复现。\n")

    # ---- 1. 策略清单 ----
    A("## 1. 经典买卖点策略清单\n")
    A("| 策略 | 类型 | 买卖点定义 | 参考来源 |")
    A("|---|---|---|---|")
    catalog = [
        ('RSI 超卖回归 (C1 基线)', '买', 'RSI(14) 前日≤30 且 当日>30（超卖结束）',
         'https://www.investopedia.com/terms/r/rsi.asp'),
        ('唐奇安通道突破 20日', '买/卖', '买=close 突破近20日最高价；卖=close 跌破近10/20日最低价',
         'https://www.investopedia.com/terms/d/donchianchannels.asp'),
        ('海龟交易法 55日', '买/卖', '买=close 突破55日高；退出=close 跌破10日低（System 2）',
         'https://en.wikipedia.org/wiki/Turtle_trading'),
        ('布林带 回归/突破', '买/卖', '下轨回归买=close 从下轨下回到上方；上轨突破买=破上轨；上轨回归卖=从上轨上回到下方',
         'https://www.investopedia.com/terms/b/bollingerbands.asp'),
        ('Supertrend', '买/卖', 'ATR(10)×3 趋势线翻多=买、翻空=卖（追踪止损型）',
         'https://www.investopedia.com/terms/s/supertrend.asp'),
        ('双均线交叉', '买/卖', 'MA5/MA20、MA10/MA60 金叉=买、死叉=卖',
         'https://www.investopedia.com/terms/g/goldencross.asp'),
        ('MACD 金叉/死叉', '买/卖', 'DIF 上穿 DEA=金叉买；DIF 下穿 DEA=死叉卖',
         'https://www.investopedia.com/terms/m/macd.asp'),
        ('KDJ 超买超卖', '买/卖', '金叉且 K<35=买；死叉且 K>70=卖',
         'https://www.investopedia.com/terms/s/stochasticoscillator.asp'),
        ('ATR 追踪止损', '卖', 'close < 近20日最高close − 3×ATR(14)',
         'https://www.investopedia.com/terms/a/atr.asp'),
        ('放量突破', '买', 'volume > 2×20日均量 且 当日 close 涨幅>2%',
         'https://www.investopedia.com/terms/v/volume.asp'),
        ('RSI 超买结束 (B0 旧基线)', '卖', 'RSI(14) 前日≥70 且 当日<70',
         'https://www.investopedia.com/terms/r/rsi.asp'),
        ('20日高回落5% (D1 基线)', '卖', 'close 从近20日最高 high 回落 5%（前日≥阈 且 当日<阈）',
         '本仓库 07-卖点对策回测.md'),
    ]
    for row in catalog:
        A(f"| {row[0]} | {row[1]} | {row[2]} | [{row[3]}]({row[3]}) |")
    A("")
    A("> 未纳入：缠论买卖点（一买二买三买）—— 定义主观、需分笔/中枢识别，独立脚本难以可靠复刻，"
      "且社区实现差异大；ATR 固定止损（非追踪）—— 与追踪止损同类，已用 ATR_trail_stop 覆盖。\n")

    # ---- 2. 资产覆盖 ----
    A("## 2. 资产覆盖与样本分布\n")
    nidx = sum(1 for a in assets if a[0] == 'idx')
    nsw = sum(1 for a in assets if a[0] == 'sw')
    nstk = sum(1 for a in assets if a[0] == 'stk')
    A(f"- 指数（13主要+3红利）：{nidx} 个；申万行业：{nsw} 个；个股：{nstk} 个")
    A(f"- 个股抽样覆盖：从 3609 只合格标的（≥1500 行且数据至 2020+）中固定种子抽样 {SAMPLE_STOCKS} 只，覆盖大小盘/行业/上市时长")
    A(f"- 指数/行业无 volume 字段 → Vol_breakout 仅在个股上计算\n")

    # ---- 3. 买点结果 ----
    A("## 3. 买点回测结果\n")
    A("### 3.1 买点 10 日 horizon（主对比轴）\n")
    A("| 策略 | 全史(样本/胜率/盈亏比/均值) | 近10年 | 近3年 | 近1年 |")
    A("|---|---|---|---|---|")
    for sname in BUY_ORDER:
        cells = [sname]
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, 10, pname), []), False)
            cells.append(f"{n}/{fmt_pct(wr*100)}/{fmt(pl,2)}/{fmt_pct(m)}")
        A("| " + " | ".join(cells) + " |")
    A("")

    A("### 3.2 买点 各 horizon 详解（全史）\n")
    A("| 策略 | horizon | 样本 | 胜率 | 盈亏比 | 均值 | 中位 |")
    A("|---|---|---:|---:|---:|---:|---:|")
    for sname in BUY_ORDER:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, h, '全史'), []), False)
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} | {fmt_pct(med)} |")
    A("")

    A("### 3.3 买点 各 horizon 详解（近3年）\n")
    A("| 策略 | horizon | 样本 | 胜率 | 盈亏比 | 均值 |")
    A("|---|---|---:|---:|---:|---:|")
    for sname in BUY_ORDER:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, h, '近3年'), []), False)
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} |")
    A("")

    # ---- 4. 卖点结果 ----
    A("## 4. 卖点回测结果\n")
    A("### 4.1 卖点 10 日 horizon（主对比轴）\n")
    A("| 策略 | 全史(样本/胜率/盈亏比/均值) | 近10年 | 近3年 | 近1年 |")
    A("|---|---|---|---|---|")
    for sname in SELL_ORDER:
        cells = [sname]
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, 10, pname), []), True)
            cells.append(f"{n}/{fmt_pct(wr*100)}/{fmt(pl,2)}/{fmt_pct(m)}")
        A("| " + " | ".join(cells) + " |")
    A("")
    A("> 卖点均值收益：负=下跌（卖点正确方向）；胜率>50% 且 盈亏比>1 为有效。\n")

    A("### 4.2 卖点 各 horizon 详解（全史）\n")
    A("| 策略 | horizon | 样本 | 胜率 | 盈亏比 | 均值 | 中位 |")
    A("|---|---|---:|---:|---:|---:|---:|")
    for sname in SELL_ORDER:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, h, '全史'), []), True)
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} | {fmt_pct(med)} |")
    A("")

    A("### 4.3 卖点 各 horizon 详解（近3年）\n")
    A("| 策略 | horizon | 样本 | 胜率 | 盈亏比 | 均值 |")
    A("|---|---|---:|---:|---:|---:|")
    for sname in SELL_ORDER:
        for h in HORIZONS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, h, '近3年'), []), True)
            A(f"| {sname} | {h}日 | {n} | {fmt_pct(wr*100)} | {fmt(pl,2)} | {fmt_pct(m)} |")
    A("")

    # ---- 5. 达标统计 ----
    A("## 5. 达标统计（10 日 horizon）\n")
    A("达标 = 胜率>50% 且 盈亏比>1 且 样本≥30。统计每个策略在 4 个窗口的达标数。\n")
    A("### 买点\n")
    A("| 策略 | 全史 | 近10年 | 近3年 | 近1年 | 达标数 |")
    A("|---|---|---|---|---|---:|")
    for sname in BUY_ORDER:
        cells = []; ok = 0
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('buy', sname, 10, pname), []), False)
            good = (n >= 30 and wr > 0.5 and (not np.isnan(pl)) and pl > 1.0)
            cells.append("✓" if good else "·")
            ok += int(good)
        A(f"| {sname} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {ok} |")
    A("")
    A("### 卖点\n")
    A("| 策略 | 全史 | 近10年 | 近3年 | 近1年 | 达标数 |")
    A("|---|---|---|---|---|---:|")
    for sname in SELL_ORDER:
        cells = []; ok = 0
        for pname, _ in PERIODS:
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, 10, pname), []), True)
            good = (n >= 30 and wr > 0.5 and (not np.isnan(pl)) and pl > 1.0)
            cells.append("✓" if good else "·")
            ok += int(good)
        A(f"| {sname} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {ok} |")
    A("")

    # ---- 6. 推荐组合 ----
    # 注：本节数值基于本次回测（固定种子 20260705，数据截止 2026-07-06，244 资产）。
    A("## 6. 推荐买卖点组合（数据驱动）\n")
    A("> 以下基于独立信号 forward-return 统计。配对交易（买入后至下一个卖出信号）的实战收益")
    A("> 需另立脚本模拟；此处以「买点未来上涨概率高 + 卖点未来下跌概率高」为组合原则。")
    A("> 数值基于本次回测（固定种子 20260705，数据截止 2026-07-06，244 资产）。\n")

    A("### 6.1 买点结论：C1 仍是最优，BB_lower_revert 是最佳互补\n")
    A("**10 日 horizon 达标统计（达标=胜率>50% 且 盈亏比>1 且 样本≥30）：**\n")
    A("| 买点策略 | 全史 | 近10年 | 近3年 | 近1年 | 达标数 |")
    A("|---|---|---|---|---|---:|")
    buy_pass_rows = [
        ('C1_RSI30（现状）', True),
        ('BB_lower_revert', True),
        ('Supertrend_buy', False),
        ('Donchian20_up / 55_up', False),
        ('MA_golden_10_60', False),
        ('MA_golden_5_20 / MACD_golden', False),
        ('BB_upper_break / KDJ_golden_oversold / Vol_breakout', False),
    ]
    # 用实际达标数据填充前两行，其余汇总
    def pass_mark(side, sname, pname):
        n, m, med, wr, pl = stats_block(qual.get((side, sname, 10, pname), []), side == 'sell')
        return (n >= 30 and wr > 0.5 and (not np.isnan(pl)) and pl > 1.0)
    for label, detail in [('C1_RSI30', 'C1_RSI30（现状）'), ('BB_lower_revert', 'BB_lower_revert')]:
        marks = ['✓' if pass_mark('buy', label, p) else '·' for p, _ in PERIODS]
        A(f"| {detail} | {marks[0]} | {marks[1]} | {marks[2]} | {marks[3]} | {marks.count('✓')} |")
    # Supertrend_buy 单独一行
    marks = ['✓' if pass_mark('buy', 'Supertrend_buy', p) else '·' for p, _ in PERIODS]
    A(f"| Supertrend_buy | {marks[0]} | {marks[1]} | {marks[2]} | {marks[3]} | {marks.count('✓')} |")
    A("| Donchian20_up / 55_up / MA_golden_10_60 | ≤2 | | | | ≤2 |")
    A("| MA_golden_5_20 / MACD_golden | ≤1 | | | | ≤1 |")
    A("| BB_upper_break / KDJ_golden_oversold / Vol_breakout | · | · | · | · | 0 |")
    A("")
    A("- **C1_RSI30 与 BB_lower_revert 并列达标数第 1（3/4 窗口）**，但 C1 在全史/近3年胜率更高")
    A("  （52.2%/52.5% vs 49.7%/51.1%），BB_lower_revert 在近1年（强势单边市）反而最优。")
    A("- **C1 在近3年所有 horizon 胜率均 >50%**（5d 55.5% / 10d 52.5% / 20d 55.6% / 60d 53.8%），")
    A("  盈亏比随 horizon 单调上升（1.26→1.12→1.50→1.63），60 日均值 +4.6%——**结构最稳健**。")
    A("- **BB_lower_revert（布林下轨回归买）**：近3年 60d 盈亏比 1.84、均值 +5.0%（最高），")
    A("  近1年是唯一达标买点（52.1%/1.23）。语义与 C1 同为「超卖反弹」，但在强势市更敏感。")
    A("- **Supertrend_buy（趋势跟踪买）**：近3年盈亏比 1.43、均值 +1.3%（10日最高），")
    A("  全 horizon 胜率≥50%。语义与 C1 正交（趋势启动 vs 超卖反弹），适合做互补买点。")
    A("- **明确排除**：BB_upper_break / KDJ_golden_oversold / Vol_breakout（0/4 达标，胜率长期 <50%）。")
    A("  Vol_breakout 近3年胜率仅 42.6%——放量突破在 A 股个股上反而是反向指标（追高被套）。\n")

    A("### 6.2 卖点结论：无完美方案，D1 仍是\"最不坏\"，BB_upper_revert 可作短周期互补\n")
    A("**10 日 horizon 达标统计：所有卖点在近3年/近10年/近1年达标数均为 0**（盈亏比全 <1，")
    A("结构性问题：A 股长期向上漂移，任何卖点都难有正期望）。仅 Supertrend_sell 在全史达标（52.0%/1.01）。\n")
    A("**近3年卖点方向准确率（胜率）排名——这是卖点选型的核心指标：**\n")
    A("| 卖点策略 | 5日胜率 | 10日胜率 | 20日胜率 | 60日胜率 | 10日盈亏比 | 10日均值 | 近3年样本 |")
    A("|---|---:|---:|---:|---:|---:|---:|---:|")
    sell_rank = ['BB_upper_revert', 'D1_high20_drop5', 'MA_death_5_20', 'BB_middle_break',
                 'Donchian10_down', 'B0_RSI70', 'Supertrend_sell', 'KDJ_death_overbought']
    for sname in sell_rank:
        cells = [sname + ('（现状）' if sname == 'D1_high20_drop5' else ('（旧）' if sname == 'B0_RSI70' else ''))]
        for h in (5, 10, 20, 60):
            n, m, med, wr, pl = stats_block(qual.get(('sell', sname, h, '近3年'), []), True)
            cells.append(fmt_pct(wr * 100))
        n10, m10, _, wr10, pl10 = stats_block(qual.get(('sell', sname, 10, '近3年'), []), True)
        n5 = stats_block(qual.get(('sell', sname, 5, '近3年'), []), True)[0]
        cells += [fmt(pl10, 2), fmt_pct(m10), str(n5)]
        A("| " + " | ".join(cells) + " |")
    A("")
    A("- **D1（20日高回落5%）**：20 日胜率 55.7%（并列最高）、样本量最大（9873，统计最稳）、")
    A("  10 日均值 -0.0%（方向正确）。**盈亏比 0.86（<1）但在所有卖点中 PL 仍属前列**，")
    A("  且 20 日维度方向性最强。维持现状合理。")
    A("- **D1 在 244 资产上 PL=0.89/0.86（全史/近3年），低于 07 报告 13 指数的 1.04**——")
    A("  原因是个股波动远大于指数，回落5%后反弹概率更高。但 D1 胜率仍 top3，且样本最大，")
    A("  \"最不坏\"地位不变。")
    A("- **BB_upper_revert（布林上轨回归卖）**：5d/10d 胜率最高（57.3%/54.3%），")
    A("  短周期止盈最强；但样本仅 5444（D1 一半）、20d 后衰减。适合做 D1 的**短周期互补**。")
    A("- **MA_death_5_20**：20d 胜率 56.3%（最高），均值 -0.1%（方向正确），但 5d/10d 偏弱。")
    A("- **Supertrend_sell**：全史唯一 PL≥1（1.01），但近3年全面走弱（48.9%/0.92），近年失效，不推荐。")
    A("- **明确排除**：B0_RSI70（旧基线，PL 0.81，最差）、KDJ_death_overbought（胜率 46.3%）、")
    A("  Supertrend_sell（近年失效）。\n")

    A("### 6.3 候选组合（2-3 个供选）\n")
    A("| 候选 | 买点 | 卖点 | 数据依据 | 改动量 | 适用场景 |")
    A("|---|---|---|---|---|---|")
    A("| **A 推荐（维持现状）** | C1_RSI30 | D1_high20_drop5 | C1 买点达标数并列第1；D1 卖点胜率top3+样本最大 | 0（已实施） | 通用，震荡/下跌市止盈 |")
    A("| **B 买点增强** | C1_RSI30 + BB_lower_revert（双买点） | D1_high20_drop5 | BB_lower_revert 近1年唯一达标买点，补强 C1 在强势市的盲区 | 中（加辅买点） | 想捕捉更多反弹机会 |")
    A("| **C 卖点增强** | C1_RSI30 | D1_high20_drop5 + BB_upper_revert（双卖点/双重确认） | BB_upper_revert 5d/10d 胜率最高，与 D1（20d 最强）时间维度互补 | 中（加辅卖点） | 想要更灵敏的短周期止盈 |")
    A("")
    A("**首选建议：候选 A（维持现状）**。理由：")
    A("1. C1 在 244 资产、35 年、4 窗口上再次验证为最优买点之一（3/4 达标，近3年全 horizon 正期望）；")
    A("   06 报告（13 指数）结论在更大样本上得到确认——**无需改买点**。")
    A("2. D1 在 244 资产上虽 PL<1（个股波动更大所致），但**胜率仍 top3、样本最大、20d 方向最强**，")
    A("   \"最不坏\"地位不变；07 报告结论稳固——**无需改卖点**。")
    A("3. 卖点本质难预测（任何方案近年 PL<1），换方案收益有限、风险增加；维持 D1 + 持续监控最稳妥。")
    A("4. 改动量最小，避免引入未在实盘验证的新逻辑。")
    A("")
    A("**若用户想增强信号覆盖**：候选 B（加 BB_lower_revert 辅买点）性价比最高——")
    A("它达标数与 C1 并列，且互补 C1 在强势市的盲区（近1年 C1 失效时它仍 52.1%/1.23）。")
    A("候选 C（加 BB_upper_revert 辅卖点）次之——短周期止盈更灵敏，但会增加假信号。\n")

    # ---- 7. 落地建议 ----
    A("## 7. 落地建议（signals.py 改法）\n")
    A("### 7.1 候选 A（维持现状）——无需改代码\n")
    A("C1 买点 + D1 卖点已在 `app/compute/signals.py` 实施（2026-07-06 验收）。本回测在 244 资产上")
    A("再次验证其接近最优，**建议不动**。仅需持续监控 D1 实盘胜率（若连续 2 季度 10 日胜率<45%，")
    A("考虑启用候选 C 的 BB_upper_revert 互补）。\n")
    A("### 7.2 候选 B（加 BB_lower_revert 辅买点）\n")
    A("在 `app/compute/signals.py` `compute()` 内、现有 buy 判定后追加辅买点。")
    A("**主买点 C1 不动**，BB_lower_revert 作为低优先级辅买点单独标（避免喧宾夺主）。\n")
    A("BB_lower_revert 只用 close（布林带=MA20±2σ），无需改 `normalize.py`。\n")
    A("```python")
    A("# 在 buy = ... 之后追加（C1 主买点不变）")
    A("bu_, mid_, bl_ = bollinger(close, 20, 2.0)   # 复刻：mid=MA20, sd=std(ddof=0)")
    A("buy_aux = ((close.shift(1) < bl_.shift(1)) & (close > bl_)).fillna(False)")
    A("")
    A("# reason 格式（辅买点，标 aux 区分）")
    A("for date in buy_aux[buy_aux].index:")
    A("    c = close.get(date); b = bl_.get(date); r = rsi.get(date)")
    A('    reason = f"布林下轨回归(下轨{b:.0f},close{c:.0f})"')
    A("    if pd.notna(r): reason += f',RSI={r:.0f}'")
    A("    # cross 软标签同 C1")
    A('    signals.append((date, iid, "buy_aux", reason))   # signal 字段用 buy_aux 区分优先级')
    A("```\n")
    A("> 注：C1 与 BB_lower_revert 信号会部分重叠（同日触发），UI 可去重或并排展示。")
    A("> 建议主买点 C1 优先级高、辅买点 buy_aux 优先级低。\n")
    A("### 7.3 候选 C（加 BB_upper_revert 辅卖点）\n")
    A("在 D1 主卖点基础上追加辅卖点（短周期止盈）。**主卖点 D1 不动**。同样只用 close，无需改 normalize。\n")
    A("```python")
    A("# 在 sell = ...（D1）之后追加")
    A("bu_, mid_, bl_ = bollinger(close, 20, 2.0)")
    A("sell_aux = ((close.shift(1) > bu_.shift(1)) & (close < bu_)).fillna(False)")
    A("")
    A("for date in sell_aux[sell_aux].index:")
    A("    c = close.get(date); b = bu_.get(date); r = rsi.get(date)")
    A('    reason = f"布林上轨回归(上轨{b:.0f},close{c:.0f})"')
    A("    if pd.notna(r): reason += f',RSI={r:.0f}'")
    A('    signals.append((date, iid, "sell_aux", reason))')
    A("```\n")
    A("> D1 与 BB_upper_revert 时间维度互补（D1 强在 20d，BB_upper_revert 强在 5d/10d），")
    A("> 同日触发可视为高置信减仓信号。\n")
    A("### 7.4 reason 字段建议\n")
    A("无论哪个候选，reason 末尾保留 cross 软分级标签（`_cross_tag`），与现状一致。")
    A("辅买/辅卖点用 `buy_aux` / `sell_aux` 区分优先级，UI 可折叠展示。\n")

    # ---- 8. 诚实声明 ----
    A("## 8. 诚实声明与局限\n")
    A("- 信号独立统计：买/卖 forward return 各自评估，未模拟「买入→持有→卖出」真实配对收益；"
      "实际持仓收益还取决于信号匹配、滑点、手续费。")
    A("- 卖点本质难预测：A 股长期向上漂移，任何卖点都难长期高胜率；本回测在更大样本上再次印证此结构性问题。")
    A("- 个股 vs 指数：个股波动大、信号更频繁、胜率结构可能与指数不同；抽样 200 只已尽量覆盖，但仍非全市场。")
    A("- 缠论未纳入：定义主观、实现差异大，独立脚本难以可靠复刻。")
    A("- WebSearch 工具本次返回空结果，策略清单基于公认定义 + 权威 URL；如需最新研报/社区变体需后续补充检索。\n")

    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write("\n".join(L))

    # ---- 控制台汇总 ----
    print("\n" + "=" * 70)
    print("买点 10日 全史/近3年：")
    for sname in BUY_ORDER:
        na, ma_, _, wa, pa = stats_block(qual.get(('buy', sname, 10, '全史'), []), False)
        n3, m3, _, w3, p3 = stats_block(qual.get(('buy', sname, 10, '近3年'), []), False)
        print(f"  {sname:22s} 全史 n={na:6d} 胜={fmt_pct(wa*100)} PL={fmt(pa,2)} 均={fmt_pct(ma_)} | 近3年 n={n3:5d} 胜={fmt_pct(w3*100)} PL={fmt(p3,2)} 均={fmt_pct(m3)}")
    print("\n卖点 10日 全史/近3年：")
    for sname in SELL_ORDER:
        na, ma_, _, wa, pa = stats_block(qual.get(('sell', sname, 10, '全史'), []), True)
        n3, m3, _, w3, p3 = stats_block(qual.get(('sell', sname, 10, '近3年'), []), True)
        print(f"  {sname:22s} 全史 n={na:6d} 胜={fmt_pct(wa*100)} PL={fmt(pa,2)} 均={fmt_pct(ma_)} | 近3年 n={n3:5d} 胜={fmt_pct(w3*100)} PL={fmt(p3,2)} 均={fmt_pct(m3)}")
    print(f"\n报告已写入: {REPORT}")
    print(f"总耗时: {time.time()-t0:.1f}s")

    # ===================== JSON 输出（策略实验室） =====================
    # 全量 22策略 × 5窗口 × 4horizon = 440 数据点，供前端「策略实验室」多周期对比。
    # mean 存为小数（% ÷ 100，如 0.1% -> 0.001）；win 存为 0-1 小数。
    import json
    JSON_PATH = '/Users/linhuichen/code/trade/a-stock-data/lab_backtest.json'
    PERIOD_ORDER = [p[0] for p in PERIODS_JSON]
    all_strats = [('buy', s) for s in BUY_ORDER] + [('sell', s) for s in SELL_ORDER]
    lab = {
        "generated_at": str(max_date.date()),
        "data_cutoff": str(max_date.date()),
        "periods": PERIOD_ORDER,
        "horizons": [f"{h}d" for h in HORIZONS],
        "strategies": {}
    }
    nan_cells = 0
    total_cells = 0
    for side, sname in all_strats:
        is_sell = (side == 'sell')
        strat_obj = {
            "side": side,
            "desc": STRATEGY_DESC.get(sname, sname),
            "periods": {}
        }
        for pname in PERIOD_ORDER:
            strat_obj["periods"][pname] = {}
            for h in HORIZONS:
                n, m, _med, wr, pl = stats_block(
                    qual.get((side, sname, h, pname), []), is_sell)
                total_cells += 1
                cell = {
                    "win": round(float(wr), 4) if not np.isnan(wr) else None,
                    "pl": round(float(pl), 3) if not np.isnan(pl) else None,
                    "n": int(n),
                    "mean": round(float(m) / 100.0, 5) if not np.isnan(m) else None,
                }
                if cell["win"] is None or cell["pl"] is None or cell["mean"] is None:
                    nan_cells += 1
                strat_obj["periods"][pname][f"{h}d"] = cell
        lab["strategies"][sname] = strat_obj

    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(lab, f, ensure_ascii=False, indent=2)
    print(f"\n策略实验室 JSON 已写入: {JSON_PATH}")
    print(f"  策略={len(all_strats)} 窗口={len(PERIOD_ORDER)} horizon={len(HORIZONS)}"
          f" 数据点={total_cells}(空值={nan_cells})")


if __name__ == '__main__':
    main()
