"""新高新低家数（P3-14）：统计 8 个主要指数创 N 日新高/新低的数量。

计算逻辑：
- 对 8 个主要指数，检查当日收盘价是否创 250 日（年度）/ 20 日（月度）新高/新低
- NH-NL = 新高数量 - 新低数量（IBD 经典指标）
- 写入 daily_metric 表
"""
import json
from datetime import datetime

import pandas as pd

from ..db import get_conn

INDICES = ["sh", "sz", "hs300", "sz50", "csi500", "csi1000", "cyb", "kc50"]

INDEX_NAMES = {
    "sh": "上证指数", "sz": "深成指", "hs300": "沪深300",
    "sz50": "上证50", "csi500": "中证500", "csi1000": "中证1000",
    "cyb": "创业板指", "kc50": "科创50",
}

WINDOW_52W = 250
WINDOW_20D = 20


def compute_new_highs_lows(date: str | None = None) -> dict:
    """计算全量历史新高新低，返回最新日期的结果。

    返回 dict 包含：
    - data: list[{date, nh_52w, nl_52w, nhnl_52w, nh_20d, nl_20d, details: [...]}]
    - latest: 最新日期摘要
    """
    conn = get_conn()

    # 读取所有 8 个指数的收盘价，pivot 为 DataFrame
    placeholders = ",".join(["?"] * len(INDICES))
    rows = conn.execute(
        f"SELECT date, index_id, close FROM index_daily "
        f"WHERE index_id IN ({placeholders}) AND close IS NOT NULL ORDER BY date",
        INDICES,
    ).fetchall()

    if not rows:
        conn.close()
        return {"data": [], "latest": {}}

    df = pd.DataFrame(rows, columns=["date", "index_id", "close"])
    pivoted = df.pivot(index="date", columns="index_id", values="close")

    # 计算滚动 N 日最高/最低
    rolling_high_52w = pivoted.rolling(WINDOW_52W, min_periods=20).max().shift(1)
    rolling_low_52w = pivoted.rolling(WINDOW_52W, min_periods=20).min().shift(1)
    rolling_high_20d = pivoted.rolling(WINDOW_20D, min_periods=5).max().shift(1)
    rolling_low_20d = pivoted.rolling(WINDOW_20D, min_periods=5).min().shift(1)

    results = []
    for date_idx in pivoted.index:
        d = date_idx
        close_row = pivoted.loc[d]
        nh_52w_count = 0
        nl_52w_count = 0
        nh_20d_count = 0
        nl_20d_count = 0
        details = []

        for iid in INDICES:
            close_val = close_row.get(iid)
            if pd.isna(close_val):
                continue

            is_nh_52w = False
            is_nl_52w = False
            is_nh_20d = False
            is_nl_20d = False

            if d in rolling_high_52w.index:
                prev_high_52w = rolling_high_52w.loc[d, iid]
                prev_low_52w = rolling_low_52w.loc[d, iid]
                if not pd.isna(prev_high_52w) and close_val > prev_high_52w:
                    is_nh_52w = True
                    nh_52w_count += 1
                if not pd.isna(prev_low_52w) and close_val < prev_low_52w:
                    is_nl_52w = True
                    nl_52w_count += 1

            if d in rolling_high_20d.index:
                prev_high_20d = rolling_high_20d.loc[d, iid]
                prev_low_20d = rolling_low_20d.loc[d, iid]
                if not pd.isna(prev_high_20d) and close_val > prev_high_20d:
                    is_nh_20d = True
                    nh_20d_count += 1
                if not pd.isna(prev_low_20d) and close_val < prev_low_20d:
                    is_nl_20d = True
                    nl_20d_count += 1

            details.append({
                "index_id": iid,
                "name": INDEX_NAMES.get(iid, iid),
                "close": round(float(close_val), 2),
                "nh_52w": is_nh_52w,
                "nl_52w": is_nl_52w,
                "nh_20d": is_nh_20d,
                "nl_20d": is_nl_20d,
            })

        results.append({
            "date": d,
            "nh_52w": nh_52w_count,
            "nl_52w": nl_52w_count,
            "nhnl_52w": nh_52w_count - nl_52w_count,
            "nh_20d": nh_20d_count,
            "nl_20d": nl_20d_count,
            "details": details,
        })

    conn.close()

    latest = results[-1] if results else {}
    return {"data": results, "latest": latest}


def store_new_highs_lows(results: dict) -> int:
    """将新高新低数据写入 daily_metric 表，返回写入行数。"""
    data = results.get("data", [])
    if not data:
        return 0

    now = datetime.now().isoformat()
    conn = get_conn()
    n = 0

    metric_ids = [
        ("a_nh_52w", "nh_52w"),
        ("a_nl_52w", "nl_52w"),
        ("a_nhnl_52w", "nhnl_52w"),
        ("a_nh_20d", "nh_20d"),
        ("a_nl_20d", "nl_20d"),
    ]

    for entry in data:
        d = entry["date"]
        for mid, key in metric_ids:
            val = entry.get(key)
            if val is None:
                continue
            conn.execute(
                "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, updated_at=excluded.updated_at "
                "WHERE daily_metric.source != 'manual'",
                (d, mid, float(val), "derived", now),
            )
            n += 1

        # 写入 details JSON 作为 a_nhnl_details 指标
        conn.execute(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            (d, "a_nhnl_details", 0, "derived", now),
        )

    conn.commit()
    conn.close()
    return n


if __name__ == "__main__":
    result = compute_new_highs_lows()
    print(f"Computed {len(result['data'])} days")
    if result["latest"]:
        print(json.dumps(result["latest"], ensure_ascii=False, indent=2))