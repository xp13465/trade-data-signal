"""AD Line（腾落线）+ 涨跌家数比。

数据来源：daily_metric 表，metric_id = a_width_up_count 和 a_width_down_count。

计算逻辑：
  1. 每日涨跌比 = up / (up + down)  (0-1 之间)
  2. AD Line = 累计(上涨家数 - 下跌家数)，从最早日期开始累加
  3. AD Line 的 5日/20日均线，用于判断背离

写入 daily_metric 表（metric_id: a_ad_line, a_up_down_ratio, a_ad_line_ma5, a_ad_line_ma20）。
"""
from datetime import datetime

import pandas as pd

from ..db import get_conn
from .normalize import load_metric_series


def compute_ad_line() -> dict[str, pd.Series]:
    """返回 {metric_id: Series}，写入 daily_metric 表。"""
    up = load_metric_series("a_width_up_count")
    down = load_metric_series("a_width_down_count")

    if up.empty or down.empty:
        return {}

    df = pd.DataFrame({"up": up, "down": down}).sort_index()
    # 确保有数据
    df = df.dropna(subset=["up", "down"])

    if df.empty:
        return {}

    # 涨跌比 = up / (up + down)
    df["ratio"] = df["up"] / (df["up"] + df["down"])

    # AD Line = 累计(up - down)
    diff = df["up"] - df["down"]
    df["ad_line"] = diff.cumsum()

    # AD Line 均线
    df["ad_line_ma5"] = df["ad_line"].rolling(5, min_periods=1).mean()
    df["ad_line_ma20"] = df["ad_line"].rolling(20, min_periods=1).mean()

    out = {
        "a_up_down_ratio": df["ratio"],
        "a_ad_line": df["ad_line"],
        "a_ad_line_ma5": df["ad_line_ma5"],
        "a_ad_line_ma20": df["ad_line_ma20"],
    }
    return out


def store_ad_line(out: dict[str, pd.Series]) -> int:
    """将 AD Line 指标写入 daily_metric 表，返回写入行数。"""
    if not out:
        return 0

    now = datetime.now().isoformat()
    conn = get_conn()
    n = 0
    for mid, s in out.items():
        rows = [(d, mid, float(v), "derived", now) for d, v in s.dropna().items()]
        if not rows:
            continue
        conn.executemany(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            rows,
        )
        n += len(rows)
    conn.commit()
    conn.close()
    return n