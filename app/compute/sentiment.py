"""§4 A股综合情绪分：6 分项加权（缺项按可用重归一化权重）。"""
import json
from datetime import datetime

import pandas as pd

from .normalize import load_metric_series, rolling_percentile, normalized
from ..db import get_conn

# (key, weight, direction)
COMPONENTS = [
    ("ratio", 0.25),    # 涨跌家数比 = up/(up+down)
    ("zt", 0.20),       # a_width_zt_count
    ("zhaban", 0.15),   # a_width_zhaban_rate（反向）
    ("lianban", 0.15),  # a_width_max_lianban
    ("amount", 0.10),   # a_amount
    ("north", 0.15),    # a_fund_north
]


def _up_ratio() -> pd.Series:
    up = load_metric_series("a_width_up_count")
    down = load_metric_series("a_width_down_count")
    if up.empty or down.empty:
        return pd.Series(dtype=float)
    df = pd.concat([up.rename("up"), down.rename("down")], axis=1)
    return df["up"] / (df["up"] + df["down"])


def compute():
    """返回 (score_series, components_df)。"""
    norm = {
        "ratio": rolling_percentile(_up_ratio()),
        "zt": normalized("a_width_zt_count"),
        "zhaban": normalized("a_width_zhaban_rate"),
        "lianban": normalized("a_width_max_lianban"),
        "amount": normalized("a_amount"),
        "north": normalized("a_fund_north"),
    }
    df = pd.DataFrame(norm)
    w = pd.Series({k: wt for k, wt in COMPONENTS})
    weighted = df.mul(w, axis=1)
    avail_w = df.notna().mul(w, axis=1).sum(axis=1).replace(0, pd.NA)
    avail_count = df.notna().sum(axis=1)
    score = weighted.sum(axis=1, skipna=True) / avail_w
    score = score.where(avail_count >= 3)  # 至少 3 个分项才出分，避免单分项误导
    return score, df


def store(score: pd.Series, components_df: pd.DataFrame) -> int:
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = []
    for date, val in score.dropna().items():
        if pd.isna(val):
            continue
        comps = {}
        for c in components_df.columns:
            v = components_df.at[date, c]
            if pd.notna(v):
                comps[c] = round(float(v), 2)
        rows.append((date, "a_sentiment", round(float(val), 2),
                     int(val < 20), int(val > 80), json.dumps(comps, ensure_ascii=False), now))
    conn.executemany(
        "INSERT INTO score_daily (date, score_id, value, is_freeze, is_overheat, components, updated_at) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(date, score_id) DO UPDATE SET value=excluded.value, "
        "is_freeze=excluded.is_freeze, is_overheat=excluded.is_overheat, "
        "components=excluded.components, updated_at=excluded.updated_at",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)
