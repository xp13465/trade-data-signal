"""大盘位置感：计算各指数当前收盘价在历史中的分位（1年/3年/5年）。

对 8 个 A 股指数（sh/sz/hs300/sz50/csi500/csi1000/cyb/kc50）计算：
  - 1年/3年/5年滚动分位（percentile rank）
  - 标签：低位(≤20%) / 偏低(20-40%) / 合理(40-60%) / 偏贵(60-80%) / 高位(>80%)

写入 daily_metric 表（metric_id 如 sh_position_1y, sh_position_3y, sh_position_5y）。
标签为衍生计算，不写入 daily_metric（value 列为 REAL 类型）。
"""
from datetime import datetime

import pandas as pd

from ..db import get_conn
from .normalize import load_index_close

POSITION_INDICES = ["sh", "sz", "hs300", "sz50", "csi500", "csi1000", "cyb", "kc50"]

INDEX_NAMES = {
    "sh": "上证指数", "sz": "深成指", "hs300": "沪深300",
    "sz50": "上证50", "csi500": "中证500", "csi1000": "中证1000",
    "cyb": "创业板指", "kc50": "科创50",
}

WINDOW_DAYS = {"1y": 250, "3y": 750, "5y": 1250}


def _percentile_rank(series: pd.Series, current_val: float, window_days: int) -> float | None:
    """计算 current_val 在近 window_days 个交易日中的分位（0-100）。"""
    if series.empty:
        return None
    recent = series.iloc[-window_days:]
    if len(recent) < 20:
        recent = series
    if len(recent) < 2:
        return None
    rank = (recent < current_val).sum()
    pct = (rank / len(recent)) * 100
    return round(pct, 1)


def _label_from_percentile(pct: float) -> str:
    if pct <= 20:
        return "低位"
    elif pct <= 40:
        return "偏低"
    elif pct <= 60:
        return "合理"
    elif pct <= 80:
        return "偏贵"
    else:
        return "高位"


def _level_from_percentile(pct: float) -> str:
    if pct <= 40:
        return "low"
    elif pct <= 60:
        return "mid"
    elif pct <= 80:
        return "high"
    else:
        return "top"


def compute_position() -> list[dict]:
    """计算所有指数的位置感，返回今日的 position 列表。"""
    results = []
    for iid in POSITION_INDICES:
        close_series = load_index_close(iid)
        if close_series.empty:
            continue

        current_val = close_series.iloc[-1]
        current_date = close_series.index[-1]

        pct_1y = _percentile_rank(close_series, current_val, WINDOW_DAYS["1y"])
        pct_3y = _percentile_rank(close_series, current_val, WINDOW_DAYS["3y"])
        pct_5y = _percentile_rank(close_series, current_val, WINDOW_DAYS["5y"])

        label = _label_from_percentile(pct_1y) if pct_1y is not None else "未知"
        level = _level_from_percentile(pct_1y) if pct_1y is not None else "mid"

        results.append({
            "index_id": iid,
            "name": INDEX_NAMES.get(iid, iid),
            "current": round(float(current_val), 2),
            "current_date": current_date,
            "percentile_1y": pct_1y,
            "percentile_3y": pct_3y,
            "percentile_5y": pct_5y,
            "label": label,
            "level": level,
        })

    return results


def store_position(positions: list[dict]) -> int:
    """将位置感分位数值写入 daily_metric 表，返回写入行数。"""
    if not positions:
        return 0

    now = datetime.now().isoformat()
    conn = get_conn()
    n = 0

    for p in positions:
        iid = p["index_id"]
        date = p["current_date"]
        for window_key in ["1y", "3y", "5y"]:
            pct_val = p.get(f"percentile_{window_key}")
            if pct_val is None:
                continue
            mid = f"{iid}_position_{window_key}"
            conn.execute(
                "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, updated_at=excluded.updated_at "
                "WHERE daily_metric.source != 'manual'",
                (date, mid, float(pct_val), "derived", now),
            )
            n += 1

    conn.commit()
    conn.close()
    return n
