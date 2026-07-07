"""归一化与数据加载。"""
import pandas as pd

from ..db import get_conn
from ..collector.fetchers import load_config

_WINDOW = 120
_MIN_PERIODS = 10  # 涨停板池等快照指标历史仅近 2 周，放宽 min_periods 让 §4 近期可算，随每日积累稳定


def load_metric_series(metric_id: str) -> pd.Series:
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id=? ORDER BY date", (metric_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["value"] for r in rows}).sort_index().astype(float)


def load_metric_value(metric_id: str) -> pd.Series:
    """从 daily_metric 取 value 序列（按 date 升序，过滤 NULL），供 signals 算指标买卖点用。

    与 load_metric_series 区别：过滤 value IS NULL（signals 需严格数值序列，避免 NaN 污染 RSI）。
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id=? AND value IS NOT NULL ORDER BY date",
        (metric_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["value"] for r in rows}).sort_index().astype(float)


def load_score_value(score_id: str) -> pd.Series:
    """从 score_daily 取 value 序列（按 date 升序，过滤 NULL），供 signals 算情绪分买卖点用。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, value FROM score_daily WHERE score_id=? AND value IS NOT NULL ORDER BY date",
        (score_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["value"] for r in rows}).sort_index().astype(float)


def load_index_high(index_id: str) -> pd.Series:
    """近 N 日最高价序列（D1 卖点用 high-based，必须用 high 不用 close 以捕捉盘中真实波峰）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, high FROM index_daily WHERE index_id=? AND high IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["high"] for r in rows}).sort_index().astype(float)


def load_index_close(index_id: str) -> pd.Series:
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["close"] for r in rows}).sort_index().astype(float)


def load_index_amount(index_id: str) -> pd.Series:
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, amount FROM index_daily WHERE index_id=? AND amount IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["amount"] for r in rows}).sort_index().astype(float)


def directions() -> dict:
    cfg = load_config()
    return {m["id"]: m.get("direction", "neutral") for m in cfg.get("metrics", [])}


def rolling_percentile(s: pd.Series, window: int = _WINDOW, min_periods: int = _MIN_PERIODS) -> pd.Series:
    """0–100 滚动百分位；不足 min_periods 返回 NaN。"""
    if s.empty:
        return s
    return s.rolling(window, min_periods=min_periods).rank(pct=True) * 100


def normalized(metric_id: str, window: int = _WINDOW) -> pd.Series:
    """加载指标 → 滚动百分位 0–100 → 方向调整（negative 取反）。"""
    s = load_metric_series(metric_id)
    if s.empty:
        return s
    p = rolling_percentile(s, window)
    if directions().get(metric_id, "neutral") == "negative":
        p = 100 - p
    return p
