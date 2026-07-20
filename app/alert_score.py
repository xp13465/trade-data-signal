"""综合 AI 风险预警算法 (8+8 维度加权 0-100)。

设计依据: docs/alert-design.md 第二章(高位预警 8 维)+第三章(低位预警 8 维)。
- HIGH_ALERT: 顶部风险信号组合, 越高越危险 (0-100)
- LOW_ALERT : 底部机会信号组合, 越高越接近底 (0-100)
- 各维度强度均用 120 日滚动百分位归一化(自适应不同市场环境, 防过拟合)
- 缺项按可用维度重归一化权重, 至少 5 维度出分才给结论

数据源:
- sentiment.db: score_daily(情绪分) / daily_metric(宽度量能均线新高新低波指股息率)
                signal_daily(买卖点) / index_daily(指数收盘价算 position)
- etf_national_team.db: etf_signal(汪汪队 share_surge/share_outflow)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parent.parent
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

MIN_DIMS = 5  # 至少 5 维度出分


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _conn_sent() -> sqlite3.Connection:
    return sqlite3.connect(_SENT_DB)


def _conn_nt() -> sqlite3.Connection:
    return sqlite3.connect(_NT_DB)


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
    """0-100 滚动百分位 (复用 normalize.rolling_percentile 逻辑: rolling.rank(pct=True)*100)。"""
    if s.empty:
        return s
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
    """近 sum_window 日求和 -> 再做 pct_window 日滚动百分位。用于买卖点/汪汪队密集度。"""
    if s.empty:
        return s
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

    # H1 情绪过热 (0.20): max(fear_greed, a_sentiment, cross_market) — 任一过热
    h1 = pd.concat([fg, a_s, cm], axis=1).max(axis=1, skipna=True)

    # H2 量价背离 (0.18): 0.6*缩量上涨强度 + 0.4*position均值
    vr = load_metric("a_volume_ratio")
    vs = load_metric("a_volume_signal")
    sh = load_index_close("sh")
    sh_ret = (sh.pct_change() * 100) if not sh.empty else pd.Series(dtype=float)
    # 缩量上涨强度: 上涨且量比低 -> 量比越低分越高; volume_signal==3(缩量上涨) 直接 100
    shrink = _rolling_pct(-vr)  # -vr 升序百分位 => vr 越低分越高
    shrink_up = shrink.where((sh_ret > 0) & (vr < 0.8), 0)
    shrink_up = shrink_up.where(~(vs == 3), 100)  # 显式缩量上涨信号置满
    h2 = 0.6 * shrink_up + 0.4 * pos

    # H3 卖点密集 (0.15): 近10日 sell 信号总数滚动百分位
    sell_cnt = _signal_count_daily(["sell"]).reindex(_trade_days(), fill_value=0)
    h3 = _rolling_sum_pct(sell_cnt, 10)

    # H4 位置偏高 (0.15): 8 指数 position_1y 均值 (已是 0-100)
    h4 = pos

    # H5 动量衰退 (0.10): 100 - nhnl_52w 滚动百分位 (新高新低差从峰值回落=衰退)
    nhnl = load_metric("a_nhnl_52w")
    h5 = 100 - _rolling_pct(nhnl)

    # H6 均线转弱 (0.10): 0.5*(100-ma_bullish百分位) + 0.5*ma_bearish百分位
    mab = load_metric("a_ma_bullish")
    mae = load_metric("a_ma_bearish")
    h6 = 0.5 * (100 - _rolling_pct(mab)) + 0.5 * _rolling_pct(mae)

    # H7 汪汪队离场 (0.07): 近30日 share_outflow 次数滚动百分位
    outflow = _signal_count_daily(["share_outflow"], nt=True).reindex(_trade_days(), fill_value=0)
    h7 = _rolling_sum_pct(outflow, 30)

    # H8 全球走弱 (0.05): 0.6*(100-us_spx 20日涨跌百分位) + 0.4*(100-cn_us_spread百分位)
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
def _weighted_score(dims: pd.DataFrame, weights: dict) -> pd.Series:
    """各维度加权求和, NaN 维度按可用维度重归一化权重; <MIN_DIMS 维度出分则置 NaN。"""
    cols = list(weights.keys())
    w = pd.Series(weights)
    d = dims[cols]
    valid = d.notna()
    # 每行有效维度的权重, NaN 维度权重置 0
    w_row = valid.mul(w, axis=1)
    w_sum = w_row.sum(axis=1)
    score = d.fillna(0).mul(w, axis=1).sum(axis=1) / w_sum.replace(0, pd.NA)
    score[valid.sum(axis=1) < MIN_DIMS] = pd.NA
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


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    r = compute_alert_for_date(d) if d else compute_alert_for_date(
        load_index_close("sh").index[-1])
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2))
