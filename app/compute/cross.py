"""§6 跨市场综合评分：全指标归一化后去最高/最低，其余均值。"""
from datetime import datetime

import pandas as pd

from .normalize import normalized
from ..collector.fetchers import load_config
from ..db import get_conn


def compute() -> pd.Series:
    cfg = load_config()
    series = {}
    for m in cfg.get("metrics", []):
        if m.get("type") != "simple" or not m.get("enabled"):
            continue
        s = normalized(m["id"])
        if not s.empty:
            series[m["id"]] = s
    if not series:
        return pd.Series(dtype=float)
    df = pd.DataFrame(series)

    def trim_mean(row):
        vals = row.dropna()
        if len(vals) < 3:
            return pd.NA
        return vals.sort_values().iloc[1:-1].mean()

    return df.apply(trim_mean, axis=1)


def store(score: pd.Series) -> int:
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = [
        (date, "cross_market", round(float(v), 2), int(v < 20), int(v > 80), None, now)
        for date, v in score.dropna().items()
    ]
    conn.executemany(
        "INSERT INTO score_daily (date, score_id, value, is_freeze, is_overheat, components, updated_at) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(date, score_id) DO UPDATE SET value=excluded.value, "
        "is_freeze=excluded.is_freeze, is_overheat=excluded.is_overheat, updated_at=excluded.updated_at",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)
