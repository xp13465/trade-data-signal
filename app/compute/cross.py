"""§6 跨市场综合评分：全指标归一化后去最高/最低，其余均值。"""
import json
from datetime import datetime

import pandas as pd

from .normalize import normalized
from ..collector.fetchers import load_config
from ..db import get_conn

# 指标分组 -> 中文标签（组成因子 chips 展示用）
GROUP_LABELS = {
    "a_width": "A股宽度",
    "a_fund": "资金面",
    "a_sentiment": "A股情绪",
    "hk": "港股",
    "global": "全球",
    "lhb": "龙虎榜",
    "unlock": "解禁",
    "ipo": "IPO",
    "cov": "可转债",
}


def compute():
    """返回 (score_series, components_df)。

    score_series：全指标归一化(滚动百分位)后去最高/最低取均值。
    components_df：各指标分组的归一化均值（0-100），供组成因子 chips 展示。
    """
    cfg = load_config()
    series = {}
    metric_groups = {}
    for m in cfg.get("metrics", []):
        if m.get("type") != "simple" or not m.get("enabled"):
            continue
        mid = m["id"]
        s = normalized(mid)
        if not s.empty:
            series[mid] = s
            metric_groups[mid] = m.get("group", "")
    if not series:
        return pd.Series(dtype=float), pd.DataFrame()
    df = pd.DataFrame(series)

    def trim_mean(row):
        vals = row.dropna()
        if len(vals) < 3:
            return pd.NA
        return vals.sort_values().iloc[1:-1].mean()

    score = df.apply(trim_mean, axis=1)

    # 按分组聚合归一化均值（组成因子：展示各市场维度冷热）
    group_cols = {}
    for grp in GROUP_LABELS:
        cols = [mid for mid, g in metric_groups.items() if g == grp]
        if cols:
            group_cols[grp] = df[cols].mean(axis=1, skipna=True)
    components_df = pd.DataFrame(group_cols) if group_cols else pd.DataFrame()

    return score, components_df


def store(score: pd.Series, components_df: pd.DataFrame = None) -> int:
    conn = get_conn()
    now = datetime.now().isoformat()
    rows = []
    for date, v in score.dropna().items():
        comps = {}
        if components_df is not None and date in components_df.index:
            for c in components_df.columns:
                cv = components_df.at[date, c]
                if pd.notna(cv):
                    comps[c] = round(float(cv), 2)
        comp_json = json.dumps(comps, ensure_ascii=False) if comps else None
        rows.append((date, "cross_market", round(float(v), 2),
                     int(v < 20), int(v > 80), comp_json, now))
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
