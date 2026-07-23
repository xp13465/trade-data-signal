"""综合 AI 风险预警算法 (8+8 维度加权 0-100)。

设计依据: docs/alert-design.md 第二章(高位预警 8 维)+第三章(低位预警 8 维)
        + 第九章(交互式自定义分析,单标的版)。
- HIGH_ALERT: 顶部风险信号组合, 越高越危险 (0-100)
- LOW_ALERT : 底部机会信号组合, 越高越接近底 (0-100)
- 各维度强度均用 120 日滚动百分位归一化(自适应不同市场环境, 防过拟合)
- 缺项按可用维度重归一化权重, 至少 5 维度出分才给结论(单标的版放宽到 4, 见 §9.3)

数据源:
- sentiment.db: score_daily(情绪分) / daily_metric(宽度量能均线新高新低波指股息率)
                signal_daily(买卖点) / index_daily(指数收盘价算 position)
- etf_national_team.db: etf_signal(汪汪队 share_surge/share_outflow)
                        etf_daily(ETF close/amount 行情)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

_REPO = Path(__file__).absolute().parent.parent
_SENT_DB = _REPO / "data" / "sentiment.db"
_NT_DB = _REPO / "data" / "etf_national_team.db"

_WINDOW = 120          # 滚动百分位窗口(与 normalize._WINDOW 一致)
_MIN_PERIODS = 30      # 回测需足够样本; 上线近端可放宽
_POS_WINDOW = 252      # position 用 1 年(约 252 交易日)滚动分位
_POS_MIN = 120

# 8 宽基指数(算 position 均值); kc50 2020 起、csi1000 2014-10 起, 早期 NaN 自动跳过
_BROAD_INDICES = ["sh", "sz", "sz50", "hs300", "csi500", "csi1000", "cyb", "kc50"]

# 高位 8 维权重 (和=1.0)。依据回测诊断调整: 升 H1情绪/H4位置(顶部最同步信号,
# 2021核心资产顶 H1=93/H4=88, 2024-10-08 H1=97/H4=100), 降 H2量价背离/H5动量/H6均线
# (确认型滞后维度, 顶部刚形成时为低分, 全样本均值 H2=21.4 严重拉低总分)。
HIGH_WEIGHTS = {"H1": 0.26, "H2": 0.08, "H3": 0.13, "H4": 0.20,
                "H5": 0.08, "H6": 0.08, "H7": 0.10, "H8": 0.07}
# 低位 8 维权重 (和=1.0), 来自 docs/alert-design.md §3.2
LOW_WEIGHTS = {"L1": 0.20, "L2": 0.18, "L3": 0.15, "L4": 0.15,
               "L5": 0.10, "L6": 0.08, "L7": 0.07, "L8": 0.07}

MIN_DIMS = 5  # 至少 5 维度出分(全市场版)
MIN_DIMS_TARGET = 4  # 单标的版放宽到 4(§9.3,适配后缺项多)

# 宽基中已有 sentiment_xxx 序列的指数(6 个);sh/sz/bj50 等无 sentiment 退化为 RSI
_BROAD_WITH_SENTIMENT = {"sz50", "hs300", "csi500", "csi1000", "cyb", "kc50"}

# ── 阶段2: ETF 专属调权(待回测验证,默认 off)─────────────────────────────────
# 背景: ETF 有汪汪队 share_surge/share_outflow 专属信号(H7/L4,来自 etf_signal 表,
#   份额 z-score+放量双重确认,质量高);而 H3/L2 买卖点是对 ETF close/OHLC 现算的
#   (RSI 上穿30/BB 下轨回归/20日高回落,复用 signals.py _rsi/_bollinger),
#   无 signal_daily 表的指数级确认,质量低于指数版 H3/L2。
# 调权方向(相对 HIGH_WEIGHTS/LOW_WEIGHTS):
#   H7↑ 0.10->0.15  汪汪队离场是 ETF 强信号(份额 z<-2 + 放量,双重确认)
#   L4↑ 0.15->0.22  汪汪队入场是 ETF 强信号(份额 z>2 + 放量,双重确认)
#   H3↓ 0.13->0.08  ETF sell 现算(20日高回落5%)质量低于指数 signal_daily 表
#   L2↓ 0.18->0.12  ETF buy 现算(RSI 上穿30/BB 下轨)同上
# 调权后重归一化(和=1.0,浮点容差 1e-9 assert 校验)。
# ⚠️ 开关 ETF_ADJUST_ENABLED 默认 False:未回测验证前不启用,避免误杀。
#   回测验证通过后改 True 启用(预计 B4/B5 阶段做回测)。
ETF_ADJUST_ENABLED = False  # 待回测验证,默认 off
ETF_HIGH_WEIGHTS = {"H1": 0.26, "H2": 0.08, "H3": 0.08, "H4": 0.20,
                    "H5": 0.08, "H6": 0.08, "H7": 0.15, "H8": 0.07}
ETF_LOW_WEIGHTS = {"L1": 0.20, "L2": 0.12, "L3": 0.15, "L4": 0.22,
                   "L5": 0.10, "L6": 0.08, "L7": 0.07, "L8": 0.06}
# 校验调权后和=1.0(防手抖)
assert abs(sum(ETF_HIGH_WEIGHTS.values()) - 1.0) < 1e-9, "ETF_HIGH_WEIGHTS 和必须=1.0"
assert abs(sum(ETF_LOW_WEIGHTS.values()) - 1.0) < 1e-9, "ETF_LOW_WEIGHTS 和必须=1.0"


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _conn_sent() -> sqlite3.Connection:
    return sqlite3.connect(_SENT_DB)


def _conn_nt() -> sqlite3.Connection:
    # 阶段2: 与 etf_national_team.get_conn() 一致设 WAL + busy_timeout,
    # 避免并发连接 journal_mode 不一致致 WAL 损坏回滚(open/high/low 列丢失事故)
    c = sqlite3.connect(_NT_DB, timeout=10.0)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA busy_timeout=30000;")
    return c


def _series(conn, sql, params=()):
    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r[0]: r[1] for r in rows}).sort_index().astype(float)


def load_score(score_id: str) -> pd.Series:
    """score_daily.value 序列 (date->value, 过滤 NULL)。"""
    with _conn_sent() as c:
        return _series(c, "SELECT date,value FROM score_daily WHERE score_id=? AND value IS NOT NULL ORDER BY date", (score_id,))


def load_metric(metric_id: str) -> pd.Series:
    with _conn_sent() as c:
        return _series(c, "SELECT date,value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date", (metric_id,))


def load_index_close(index_id: str) -> pd.Series:
    with _conn_sent() as c:
        return _series(c, "SELECT date,close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date", (index_id,))


def _rolling_pct(s: pd.Series, window: int = _WINDOW, min_periods: int = _MIN_PERIODS) -> pd.Series:
    """0-100 滚动百分位 (复用 normalize.rolling_percentile 逻辑: rolling.rank(pct=True)*100)。

    入口 pd.to_numeric 兜底: 防御 object/字符串列(如 _compute_rsi 若上游 replace
    误用 pd.NA 会导致 object dtype), 转 NaN 后 rolling 自动跳过, 避免抛
    DataError: No numeric types to aggregate。
    """
    if s.empty:
        return s
    if s.dtype != float and s.dtype != int:
        s = pd.to_numeric(s, errors="coerce")
    return s.rolling(window, min_periods=min_periods).rank(pct=True) * 100


def _signal_count_daily(sig_types: list[str], table: str = "signal_daily", nt: bool = False) -> pd.Series:
    """按日统计指定信号类型的数量 (signal_daily 用 index_id 维度全市场聚合; etf_signal 用 etf_code 维度聚合)。
    返回 date->当日信号条数(去重到日级别计数: signal_daily 一个 index 一个 signal 算 1 条, 汇总全品种)。
    """
    if nt:
        with _conn_nt() as c:
            ph = ",".join("?" * len(sig_types))
            rows = c.execute(
                f"SELECT date, COUNT(*) AS n FROM etf_signal WHERE signal_type IN ({ph}) GROUP BY date ORDER BY date",
                sig_types,
            ).fetchall()
    else:
        with _conn_sent() as c:
            ph = ",".join("?" * len(sig_types))
            rows = c.execute(
                f"SELECT date, COUNT(*) AS n FROM signal_daily WHERE signal IN ({ph}) GROUP BY date ORDER BY date",
                sig_types,
            ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r[0]: r[1] for r in rows}).sort_index().astype(float)


def _rolling_sum_pct(s: pd.Series, sum_window: int, pct_window: int = _WINDOW) -> pd.Series:
    """近 sum_window 日求和 -> 再做 pct_window 日滚动百分位。用于买卖点/汪汪队密集度。

    入口 pd.to_numeric 兜底: 防御 object/字符串列(同 _rolling_pct)。
    """
    if s.empty:
        return s
    if s.dtype != float and s.dtype != int:
        s = pd.to_numeric(s, errors="coerce")
    cum = s.rolling(sum_window, min_periods=1).sum()
    return _rolling_pct(cum, pct_window)


# ---------------------------------------------------------------------------
# position 现算 (daily_metric 仅 8 天近端, 回测用 index_daily close 全历史现算)
# ---------------------------------------------------------------------------
def compute_position_mean() -> pd.Series:
    """8 宽基 1 年滚动分位(0-100)的均值。>80 高位 / <20 低位。"""
    parts = []
    for iid in _BROAD_INDICES:
        close = load_index_close(iid)
        if close.empty:
            continue
        pct = close.rolling(_POS_WINDOW, min_periods=_POS_MIN).rank(pct=True) * 100
        parts.append(pct.rename(iid))
    if not parts:
        return pd.Series(dtype=float)
    df = pd.concat(parts, axis=1)
    return df.mean(axis=1, skipna=True)  # 8 指数均值, 缺指数自动跳过


# ---------------------------------------------------------------------------
# 各维度强度计算 (0-100)
# ---------------------------------------------------------------------------
def _trade_days() -> pd.Index:
    """完整交易日历 (以上证 close 序列日期为准, YYYYMMDD 升序)。"""
    return load_index_close("sh").index


def compute_high_dims() -> pd.DataFrame:
    """高位 8 维度强度, 返回 DataFrame[date, H1..H8] (0-100, 越高越危险, NaN=缺)。"""
    fg = load_score("fear_greed")
    a_s = load_score("a_sentiment")
    cm = load_score("cross_market")
    pos = compute_position_mean()

    # H1 情绪过热 (0.26): max(fear_greed, a_sentiment, cross_market) — 任一过热
    h1 = pd.concat([fg, a_s, cm], axis=1).max(axis=1, skipna=True)

    # H2 量价背离 (0.08): 0.6*缩量上涨强度 + 0.4*position均值
    vr = load_metric("a_volume_ratio")
    vs = load_metric("a_volume_signal")
    sh = load_index_close("sh")
    sh_ret = (sh.pct_change() * 100) if not sh.empty else pd.Series(dtype=float)
    # 缩量上涨强度: 上涨且量比低 -> 量比越低分越高; volume_signal==3(缩量上涨) 直接 100
    shrink = _rolling_pct(-vr)  # -vr 升序百分位 => vr 越低分越高
    shrink_up = shrink.where((sh_ret > 0) & (vr < 0.8), 0)
    shrink_up = shrink_up.where(~(vs == 3), 100)  # 显式缩量上涨信号置满
    h2 = 0.6 * shrink_up + 0.4 * pos

    # H3 卖点密集 (0.13): 近10日 sell 信号总数滚动百分位
    sell_cnt = _signal_count_daily(["sell"]).reindex(_trade_days(), fill_value=0)
    h3 = _rolling_sum_pct(sell_cnt, 10)

    # H4 位置偏高 (0.20): 8 指数 position_1y 均值 (已是 0-100)
    h4 = pos

    # H5 动量衰退 (0.08): 100 - nhnl_52w 滚动百分位 (新高新低差从峰值回落=衰退)
    nhnl = load_metric("a_nhnl_52w")
    h5 = 100 - _rolling_pct(nhnl)

    # H6 均线转弱 (0.08): 0.5*(100-ma_bullish百分位) + 0.5*ma_bearish百分位
    mab = load_metric("a_ma_bullish")
    mae = load_metric("a_ma_bearish")
    h6 = 0.5 * (100 - _rolling_pct(mab)) + 0.5 * _rolling_pct(mae)

    # H7 汪汪队离场 (0.10): 近30日 share_outflow 次数滚动百分位
    outflow = _signal_count_daily(["share_outflow"], nt=True).reindex(_trade_days(), fill_value=0)
    h7 = _rolling_sum_pct(outflow, 30)

    # H8 全球走弱 (0.07): 0.6*(100-us_spx 20日涨跌百分位) + 0.4*(100-cn_us_spread百分位)
    spx = load_index_close("us_spx")
    spx20 = (spx.pct_change(20) * 100) if not spx.empty else pd.Series(dtype=float)
    cus = load_metric("cn_us_spread")
    h8 = 0.6 * (100 - _rolling_pct(spx20)) + 0.4 * (100 - _rolling_pct(cus))

    return pd.DataFrame({"H1": h1, "H2": h2, "H3": h3, "H4": h4,
                         "H5": h5, "H6": h6, "H7": h7, "H8": h8}).sort_index()


def compute_low_dims() -> pd.DataFrame:
    """低位 8 维度强度, 返回 DataFrame[date, L1..L8] (0-100, 越高越接近底, NaN=缺)。"""
    fg = load_score("fear_greed")
    a_s = load_score("a_sentiment")
    cm = load_score("cross_market")
    pos = compute_position_mean()

    # L1 情绪冰点 (0.20): 100 - min(fear_greed, a_sentiment, cross_market) — 任一冰点
    l1 = 100 - pd.concat([fg, a_s, cm], axis=1).min(axis=1, skipna=True)

    # L2 买点密集 (0.18): 近10日 (buy+buy_aux) 信号总数滚动百分位
    buy_cnt = _signal_count_daily(["buy", "buy_aux"]).reindex(_trade_days(), fill_value=0)
    l2 = _rolling_sum_pct(buy_cnt, 10)

    # L3 位置偏低 (0.15): 100 - 8 指数 position 均值
    l3 = 100 - pos

    # L4 汪汪队入场 (0.15): 近30日 share_surge 次数滚动百分位
    surge = _signal_count_daily(["share_surge"], nt=True).reindex(_trade_days(), fill_value=0)
    l4 = _rolling_sum_pct(surge, 30)

    # L5 量能异动 (0.10): max(放量下跌 signal=2 强度, 地量 amount 强度)
    vs = load_metric("a_volume_signal")
    amt = load_metric("a_amount")
    vol_down = (vs == 2).astype(float) * 100           # 放量下跌 -> 100
    low_amt = 100 - _rolling_pct(amt)                  # 地量分高
    l5 = pd.concat([vol_down, low_amt], axis=1).max(axis=1, skipna=True)

    # L6 新低极端 (0.08): nl_52w 滚动百分位
    nl = load_metric("a_nl_52w")
    l6 = _rolling_pct(nl)

    # L7 波指飙升 (0.07): a_qvix_300 滚动百分位 (2019-12 起, 早期缺)
    qv = load_metric("a_qvix_300")
    l7 = _rolling_pct(qv)

    # L8 价值显现 (0.07): a_div_yield 滚动百分位
    dy = load_metric("a_div_yield")
    l8 = _rolling_pct(dy)

    return pd.DataFrame({"L1": l1, "L2": l2, "L3": l3, "L4": l4,
                         "L5": l5, "L6": l6, "L7": l7, "L8": l8}).sort_index()


# ---------------------------------------------------------------------------
# 加权合成 + 缺项重归一化
# ---------------------------------------------------------------------------
def _weighted_score(dims: pd.DataFrame, weights: dict, min_dims: int = MIN_DIMS) -> pd.Series:
    """各维度加权求和, NaN 维度按可用维度重归一化权重; <min_dims 维度出分则置 NaN。"""
    cols = list(weights.keys())
    w = pd.Series(weights)
    d = dims[cols]
    valid = d.notna()
    # 每行有效维度的权重, NaN 维度权重置 0
    w_row = valid.mul(w, axis=1)
    w_sum = w_row.sum(axis=1)
    score = d.fillna(0).mul(w, axis=1).sum(axis=1) / w_sum.replace(0, pd.NA)
    score[valid.sum(axis=1) < min_dims] = pd.NA
    return score.clip(0, 100)


def compute_alert_scores(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """批量计算区间内每日 HIGH_ALERT / LOW_ALERT 及各维度强度。

    Args:
        start: 起始日 'YYYYMMDD' (含), None 不限
        end:   结束日 'YYYYMMDD' (含), None 不限
    Returns:
        DataFrame[date, high_alert, low_alert, H1..H8, L1..L8], date 升序, 缺分 NaN。
    """
    hd = compute_high_dims()
    ld = compute_low_dims()
    df = hd.join(ld, how="outer").sort_index()
    df["high_alert"] = _weighted_score(hd, HIGH_WEIGHTS)
    df["low_alert"] = _weighted_score(ld, LOW_WEIGHTS)
    if start:
        df = df[df.index >= start]
    if end:
        df = df[df.index <= end]
    return df


def compute_alert_for_date(date: str) -> dict:
    """单日预警 (上线每日调用)。返回总分 + 各维度分值 + 贡献 + 等级。"""
    df = compute_alert_scores(end=date)
    if df.empty:
        return {"date": date, "high_alert": None, "low_alert": None, "dims": {}}
    row = df.iloc[-1]
    ha, la = row["high_alert"], row["low_alert"]
    out = {
        "date": date,
        "high_alert": None if pd.isna(ha) else round(float(ha), 2),
        "low_alert": None if pd.isna(la) else round(float(la), 2),
        "high_level": _high_level(ha),
        "low_level": _low_level(la),
        "dims": {},
    }
    for k in list(HIGH_WEIGHTS) + list(LOW_WEIGHTS):
        v = row.get(k)
        out["dims"][k] = None if pd.isna(v) else round(float(v), 2)
    return out


def _high_level(score) -> str:
    if pd.isna(score):
        return "数据不足"
    if score > 88:
        return "高危"
    if score > 75:
        return "警示"
    if score > 60:
        return "关注"
    return "中性"


def _low_level(score) -> str:
    if pd.isna(score):
        return "数据不足"
    if score > 88:
        return "机遇"
    if score > 75:
        return "机会"
    if score > 60:
        return "关注"
    return "中性"


# ---------------------------------------------------------------------------
# 单标的交互式分析 (§9.3 适配表)
# ---------------------------------------------------------------------------
def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI(14) 经典算法 (Wilder 平滑)。

    注意: avg_loss 中的 0 必须用 np.nan 替换(而非 pd.NA), 否则 float64 会被
    强转为 object dtype (pd.NA 非 float), 导致下游 rolling.rank 报
    DataError: No numeric types to aggregate (sh 上证指数 8685 天数据曾触发)。
    """
    if close.empty or len(close) < period + 1:
        return pd.Series(dtype=float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)  # 保持 float64, rolling 自动跳过 NaN
    return (100 - (100 / (1 + rs)))


def _load_target_close_amount(target_id: str, target_type: str):
    """单标的 close/amount 序列 (ETF 用 etf_daily, 指数用 index_daily)。
    阶段2: ETF 加读 open/high/low 字段(供 H3/L2 信号 RSI/BB/Donchian 计算)。
    返回 (close, amount, ohlc_df) - ohlc_df 含 date/open/high/low/close/amount(ETF 专属,
    指数为 None,因指数走 signal_daily 表查买卖点不需要 OHLC 重算)。
    """
    if target_type == "etf":
        # ETF 显式指定列名,fetchall 返 sqlite3.Row 列表退出 with 后变 tuple,
        # 用 columns 参数让 DataFrame 按 2D 数组解析(与指数版同风格)
        cols = ["date", "open", "high", "low", "close", "amount"]
        with _conn_nt() as c:
            rows = c.execute(
                "SELECT date, open, high, low, close, amount FROM etf_daily WHERE etf_code=? "
                "AND close IS NOT NULL ORDER BY date",
                (target_id,),
            ).fetchall()
        if not rows:
            return pd.Series(dtype=float), pd.Series(dtype=float), None
        df = pd.DataFrame(rows, columns=cols).set_index("date")
    else:
        cols = ["date", "close", "amount"]
        with _conn_sent() as c:
            rows = c.execute(
                "SELECT date, close, amount FROM index_daily WHERE index_id=? "
                "AND close IS NOT NULL ORDER BY date",
                (target_id,),
            ).fetchall()
        if not rows:
            return pd.Series(dtype=float), pd.Series(dtype=float), None
        df = pd.DataFrame(rows, columns=cols).set_index("date")
    close = df["close"].astype(float)
    amount = pd.to_numeric(df["amount"], errors="coerce")
    amount = amount.where(amount > 0, pd.NA)  # 0 视为缺省
    ohlc_df = df if target_type == "etf" else None
    return close, amount, ohlc_df


def _target_signal_count(target_id: str, sig_types: list[str]) -> pd.Series:
    """该标的在 signal_daily 中的按日信号计数(指数版,按 index_id 过滤)。"""
    if not sig_types:
        return pd.Series(dtype=float)
    with _conn_sent() as c:
        ph = ",".join("?" * len(sig_types))
        rows = c.execute(
            f"SELECT date, COUNT(*) AS n FROM signal_daily WHERE index_id=? "
            f"AND signal IN ({ph}) GROUP BY date ORDER BY date",
            [target_id] + list(sig_types),
        ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r[0]: r[1] for r in rows}).sort_index().astype(float)


def _target_etf_signal_count(etf_code: str, sig_types: list[str]) -> pd.Series:
    """ETF 在 etf_signal 中的按日信号计数(按 etf_code 过滤)。"""
    if not sig_types:
        return pd.Series(dtype=float)
    with _conn_nt() as c:
        ph = ",".join("?" * len(sig_types))
        rows = c.execute(
            f"SELECT date, COUNT(*) AS n FROM etf_signal WHERE etf_code=? "
            f"AND signal_type IN ({ph}) GROUP BY date ORDER BY date",
            [etf_code] + list(sig_types),
        ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r[0]: r[1] for r in rows}).sort_index().astype(float)


def _compute_etf_buy_sell_signals(close: pd.Series, ohlc_df, idx) -> tuple:
    """阶段2: ETF 专属 H3/L2 信号计算。
    对 ETF close/open/high/low 现算买卖点事件,滚动10日计数百分位填 H3(sell 密集)/L2(buy 密集)。
    复用 app.compute.signals 的 _rsi/_bollinger 函数(模块私有函数,显式 import)。

    信号定义(与 signals.py compute() 同口径,§7 买卖点):
    - C1 主买 buy: RSI(14) 上穿30(前一日<=30 且当日>30)
    - B1 辅买 buy_aux: BB 下轨回归(前一日 close<下轨 且当日 close>下轨)
    - D1 卖点 sell: close 从近20日最高价(high-based)回落5%,且 close>MA60(多头趋势过滤)
    - Donchian20_up 特买(暂不计入 L2,与 signals.py 一致:独立信号不影响 buy/buy_aux/sell)

    返回 (h3, l2) pd.Series,对齐 idx。无 OHLC(ohlc_df 为 None 或 high/low 全空)时
    用 close 近似 high/low(close.rolling().max()/min(),与指数版一致)。
    """
    # 复用 signals.py 的 RSI/BB 函数(模块私有,显式 import)
    from .compute.signals import _rsi, _bollinger

    if close.empty or len(close) < 60:  # MA60 需 60 日
        return pd.Series(pd.NA, index=idx), pd.Series(pd.NA, index=idx)

    # high/low: 优先用 OHLC 真实值,缺失用 close 近似(与指数版一致)
    if ohlc_df is not None and "high" in ohlc_df.columns and "low" in ohlc_df.columns:
        high = pd.to_numeric(ohlc_df["high"], errors="coerce").reindex(idx)
        low = pd.to_numeric(ohlc_df["low"], errors="coerce").reindex(idx)
        # high/low 全空 -> close 近似
        if high.dropna().empty:
            high = close.copy()
        if low.dropna().empty:
            low = close.copy()
    else:
        high = close.copy()
        low = close.copy()

    rsi = _rsi(close, 14)
    rsi_prev = rsi.shift(1)
    # C1 主买: RSI 上穿30
    buy = ((rsi_prev <= 30) & (rsi > 30)).fillna(False).astype(int)
    # B1 辅买: BB 下轨回归
    _, _, bl_ = _bollinger(close, 20, 2.0)
    buy_aux = ((close.shift(1) < bl_.shift(1)) & (close > bl_)).fillna(False).astype(int)
    # C1 与 BB 同日触发去重(保留 C1,不重复发 buy_aux)
    buy_aux = buy_aux.where(buy == 0, 0)
    # D1 卖点: close 从20日高回落5%(high-based),且 close>MA60(多头过滤)
    hh20 = high.rolling(20).max()
    thresh = hh20 * 0.95
    sell = ((close.shift(1) >= thresh.shift(1)) & (close < thresh)).fillna(False)
    ma60 = close.rolling(60, min_periods=60).mean()
    sell = (sell & (close > ma60).fillna(False)).astype(int)

    buy_cnt = (buy + buy_aux).clip(upper=1)  # 当日任一买点触发算1条
    sell_cnt = sell

    h3 = _rolling_sum_pct(sell_cnt, 10) if sell_cnt.sum() > 0 else pd.Series(pd.NA, index=idx)
    l2 = _rolling_sum_pct(buy_cnt, 10) if buy_cnt.sum() > 0 else pd.Series(pd.NA, index=idx)
    return h3, l2


def compute_target_dims(target_id: str, target_type: str = "index") -> pd.DataFrame:
    """单标的 8+8 维度现算,套 §9.3 适配表。返回 DataFrame[date, H1..H8, L1..L8]。

    适配要点:
    - H1/L1: 宽基(6 个)用 sentiment_xxx,其他用 RSI(14) 120 日滚动百分位
    - H2: 0.6*缩量上涨 + 0.4*position_1y(无 amount 时退化为 position_1y)
    - H3/L2: 指数走 signal_daily 按 index_id 查 sell/buy+buy_aux;
      ETF 阶段2 新增:对 ETF close/open/high/low 现算 RSI 上穿30(C1 主买)+BB 下轨回归
      (B1 辅买)+20日高回落5%(D1 卖点)+Donchian20 突破(特买),事件化后滚动10日计数填
      H3(sell 信号密集)/L2(buy+buy_aux 信号密集)。复用 app.compute.signals 的 _rsi/
      _bollinger/_macd/_atr 函数,不依赖 signal_daily 表(ETF 不在 signals.compute() 流程)。
    - H4/L3: close 1 年滚动分位 / 100-分位
    - H5: 100 - 新高(close>=52w_high)120 日滚动百分位
    - H6: 0.5*(100-ma_bullish百分位) + 0.5*ma_bearish百分位
    - H7/L4: 仅 ETF 适用(share_outflow/share_surge 近 30 日计数滚动百分位)
    - H8/L7/L8: 单标的缺省(外部宏观/全市场指标,单标的不适用)
    - L5: 100 - amount 120 日滚动百分位(地量分高)
    - L6: 新低(close<=52w_low)120 日滚动百分位
    """
    close, amount, ohlc_df = _load_target_close_amount(target_id, target_type)
    if close.empty or len(close) < 30:
        return pd.DataFrame()
    idx = close.index

    # 1. 基础指标
    position_1y = close.rolling(_POS_WINDOW, min_periods=_POS_MIN).rank(pct=True) * 100
    rsi = _compute_rsi(close, 14)
    rsi_pct = _rolling_pct(rsi)

    ma5 = close.rolling(5, min_periods=5).mean()
    ma10 = close.rolling(10, min_periods=10).mean()
    ma20 = close.rolling(20, min_periods=20).mean()
    ma60 = close.rolling(60, min_periods=60).mean()
    ma_bullish = ((close > ma5) & (ma5 > ma10) & (ma10 > ma20) & (ma20 > ma60)).astype(float) * 100
    ma_bearish = ((close < ma5) & (ma5 < ma10) & (ma10 < ma20) & (ma20 < ma60)).astype(float) * 100

    high_52w = close.rolling(252, min_periods=120).max()
    low_52w = close.rolling(252, min_periods=120).min()
    nh = (close >= high_52w).astype(float) * 100
    nl = (close <= low_52w).astype(float) * 100
    close_ret = close.pct_change() * 100

    # 2. H1/L1 情绪: 宽基用 sentiment_xxx(查不到退化为 RSI 百分位)
    if target_type == "index" and target_id in _BROAD_WITH_SENTIMENT:
        sent = load_score(f"sentiment_{target_id}")
        if sent.empty:
            sent = rsi_pct
    else:
        sent = rsi_pct
    h1 = sent
    l1 = 100 - sent

    # 3. H2 量价背离 (0.6*缩量上涨 + 0.4*position)
    if amount.notna().sum() >= _MIN_PERIODS:
        amt_pct = _rolling_pct(amount)
        shrink = 100 - amt_pct  # 量越低分越高
        shrink_up = shrink.where(close_ret > 0, 0)
        h2 = 0.6 * shrink_up + 0.4 * position_1y
    else:
        h2 = position_1y  # 无 amount 退化

    # 4. H3/L2 买卖点密集
    # 指数: signal_daily 按 index_id 查 sell/buy+buy_aux
    # ETF 阶段2: 对 ETF close/open/high/low 现算 RSI 上穿30(C1 主买)+BB 下轨回归(B1 辅买)
    #   +20日高回落5%(D1 卖点)+Donchian20 突破(特买),事件化后滚动10日计数填 H3/L2
    if target_type == "index":
        sell_cnt = _target_signal_count(target_id, ["sell"]).reindex(idx, fill_value=0)
        buy_cnt = _target_signal_count(target_id, ["buy", "buy_aux"]).reindex(idx, fill_value=0)
        h3 = _rolling_sum_pct(sell_cnt, 10) if sell_cnt.sum() > 0 else pd.Series(pd.NA, index=idx)
        l2 = _rolling_sum_pct(buy_cnt, 10) if buy_cnt.sum() > 0 else pd.Series(pd.NA, index=idx)
    else:
        # ETF 阶段2: 现算买卖点事件计数(复用 signals.py _rsi/_bollinger)
        h3, l2 = _compute_etf_buy_sell_signals(close, ohlc_df, idx)

    # 5. H4/L3 位置
    h4 = position_1y
    l3 = 100 - position_1y

    # 6. H5 动量衰退 (100 - 新高百分位)
    h5 = 100 - _rolling_pct(nh)

    # 7. H6 均线转弱
    h6 = 0.5 * (100 - _rolling_pct(ma_bullish)) + 0.5 * _rolling_pct(ma_bearish)

    # 8. H7/L4 汪汪队 (仅 ETF)
    if target_type == "etf":
        outflow = _target_etf_signal_count(target_id, ["share_outflow"]).reindex(idx, fill_value=0)
        surge = _target_etf_signal_count(target_id, ["share_surge"]).reindex(idx, fill_value=0)
        h7 = _rolling_sum_pct(outflow, 30) if outflow.sum() > 0 else pd.Series(pd.NA, index=idx)
        l4 = _rolling_sum_pct(surge, 30) if surge.sum() > 0 else pd.Series(pd.NA, index=idx)
    else:
        h7 = pd.Series(pd.NA, index=idx)
        l4 = pd.Series(pd.NA, index=idx)

    # 9. H8/L7/L8 单标的缺省
    h8 = pd.Series(pd.NA, index=idx)
    l7 = pd.Series(pd.NA, index=idx)
    l8 = pd.Series(pd.NA, index=idx)

    # 10. L5 量能异动 (地量分高)
    if amount.notna().sum() >= _MIN_PERIODS:
        l5 = 100 - _rolling_pct(amount)
    else:
        l5 = pd.Series(pd.NA, index=idx)

    # 11. L6 新低极端
    l6 = _rolling_pct(nl)

    return pd.DataFrame({
        "H1": h1, "H2": h2, "H3": h3, "H4": h4,
        "H5": h5, "H6": h6, "H7": h7, "H8": h8,
        "L1": l1, "L2": l2, "L3": l3, "L4": l4,
        "L5": l5, "L6": l6, "L7": l7, "L8": l8,
    }).sort_index()


def compute_alert_for_target(target_id: str, target_type: str = "index",
                             date: str | None = None) -> dict:
    """单标的预警分(§9.4)。返回 {date, high, low, high_level, low_level, dims, adapt}。

    Args:
        target_id: 指数 id (hs300/sw_801080/thsc_301085/...) 或 ETF 代码 (510300/...)
        target_type: 'index' 或 'etf'
        date: 指定日 'YYYYMMDD' (None=最近交易日)
    """
    dims = compute_target_dims(target_id, target_type)
    if dims.empty:
        return {
            "target_id": target_id, "target_type": target_type, "date": None,
            "high": None, "low": None, "high_level": "数据不足", "low_level": "数据不足",
            "dims": {}, "adapt": {"min_dims": MIN_DIMS_TARGET, "available_high": 0,
                                  "available_low": 0, "missing": list(HIGH_WEIGHTS) + list(LOW_WEIGHTS)},
        }
    if date:
        dims = dims[dims.index <= date]
    if dims.empty:
        return {
            "target_id": target_id, "target_type": target_type, "date": date,
            "high": None, "low": None, "high_level": "数据不足", "low_level": "数据不足",
            "dims": {}, "adapt": {"min_dims": MIN_DIMS_TARGET, "available_high": 0,
                                  "available_low": 0, "missing": list(HIGH_WEIGHTS) + list(LOW_WEIGHTS)},
        }
    row = dims.iloc[-1]
    actual_date = str(dims.index[-1])
    # 阶段2: ETF 专属调权(开关 ETF_ADJUST_ENABLED 默认 off,待回测验证)
    # 启用时对 ETF 用 ETF_HIGH_WEIGHTS/ETF_LOW_WEIGHTS(H7/L4↑ H3/L2↓),
    # 指数或开关 off 用原 HIGH_WEIGHTS/LOW_WEIGHTS。
    use_etf_adjust = (target_type == "etf" and ETF_ADJUST_ENABLED)
    high_w = ETF_HIGH_WEIGHTS if use_etf_adjust else HIGH_WEIGHTS
    low_w = ETF_LOW_WEIGHTS if use_etf_adjust else LOW_WEIGHTS
    hd = dims[list(high_w.keys())]
    ld = dims[list(low_w.keys())]
    ha = _weighted_score(hd, high_w, min_dims=MIN_DIMS_TARGET).iloc[-1]
    la = _weighted_score(ld, low_w, min_dims=MIN_DIMS_TARGET).iloc[-1]

    avail_h = int(sum(1 for k in high_w if not pd.isna(row[k])))
    avail_l = int(sum(1 for k in low_w if not pd.isna(row[k])))
    missing = [k for k in list(high_w) + list(low_w) if pd.isna(row[k])]
    adapt = {
        "target_id": target_id, "target_type": target_type,
        "min_dims": MIN_DIMS_TARGET,
        "available_high": avail_h, "available_low": avail_l,
        "missing": missing,
        "etf_adjust": use_etf_adjust,  # 阶段2: 是否启用 ETF 专属调权(默认 off)
    }
    return {
        "date": actual_date,
        "target_id": target_id, "target_type": target_type,
        "high": None if pd.isna(ha) else round(float(ha), 2),
        "low": None if pd.isna(la) else round(float(la), 2),
        "high_level": _high_level(ha),
        "low_level": _low_level(la),
        "dims": {k: (None if pd.isna(row[k]) else round(float(row[k]), 2))
                 for k in list(high_w) + list(low_w)},
        "adapt": adapt,
    }


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    r = compute_alert_for_date(d) if d else compute_alert_for_date(
        load_index_close("sh").index[-1])
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
