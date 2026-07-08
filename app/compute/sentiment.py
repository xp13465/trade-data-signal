"""§4 A股综合情绪分：6 分项加权（缺项按可用重归一化权重）。"""
import json
from datetime import datetime

import pandas as pd

from .normalize import load_metric_series, rolling_percentile, normalized, load_index_close, load_index_amount
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

# 指数 → QVIX 指标映射（仅沪深300和中证1000有对应QVIX）
INDEX_QVIX_MAP = {
    "hs300": "a_qvix_300",
    "csi1000": "a_qvix_1000",
}


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI(N) — 已经是 0–100 量纲，无需再归一化。"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


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


def compute_index_sentiment(index_id: str):
    """计算单个指数的 0–100 情绪分。

    分项：
      - RSI(14)：基于收盘价，已是 0–100
      - 量偏离：(成交额/20日均量 - 1) → 滚动百分位
      - 涨跌幅：pct_change → 滚动百分位
      - QVIX（如有）：高波=恐慌 → 取反，滚动百分位

    等权平均，至少 2 个分项才出分。
    返回 (score_series, components_df)。
    """
    close = load_index_close(index_id)
    amount = load_index_amount(index_id)

    if close.empty:
        return pd.Series(dtype=float), pd.DataFrame()

    # RSI(14) — 已是 0–100
    rsi = _rsi(close)

    # 量偏离：(amount / amount_ma20 - 1) → 滚动百分位
    amount_ma20 = amount.rolling(20, min_periods=5).mean()
    vol_dev = (amount / amount_ma20 - 1)
    vol_dev_norm = rolling_percentile(vol_dev)

    # 涨跌幅 → 滚动百分位
    pct = close.pct_change()
    pct_norm = rolling_percentile(pct)

    components = {
        "rsi": rsi,
        "volume": vol_dev_norm,
        "pct_change": pct_norm,
    }

    # QVIX（如有）：高波动 = 恐慌 = 低情绪分，取反
    qvix_metric = INDEX_QVIX_MAP.get(index_id)
    if qvix_metric:
        qvix = load_metric_series(qvix_metric)
        if not qvix.empty:
            qvix_norm = 100 - rolling_percentile(qvix)
            components["qvix"] = qvix_norm

    df = pd.DataFrame(components)

    # 等权平均，至少 2 个分项
    avail_count = df.notna().sum(axis=1)
    score = df.mean(axis=1, skipna=True)
    score = score.where(avail_count >= 2)

    return score, df


def store(score: pd.Series, components_df: pd.DataFrame, score_id: str = "a_sentiment") -> int:
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
        rows.append((date, score_id, round(float(val), 2),
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
