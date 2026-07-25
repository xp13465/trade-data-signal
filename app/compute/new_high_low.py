"""新高新低家数（P3-14）：统计 8 个主要指数创 N 日新高/新低的数量。

计算逻辑：
- 对 8 个主要指数，检查当日收盘价是否创 250 日（年度）/ 20 日（月度）新高/新低
- NH-NL = 新高数量 - 新低数量（IBD 经典指标）
- 写入 daily_metric 表
"""
import json
from datetime import datetime

import numpy as np
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
    # reindex 到 INDICES 顺序(保持 details 顺序一致;缺失指数列全 NaN,close NaN 跳过等效原 get 返回 NaN)
    pivoted = pivoted.reindex(columns=INDICES)

    # 计算滚动 N 日最高/最低
    rolling_high_52w = pivoted.rolling(WINDOW_52W, min_periods=20).max().shift(1)
    rolling_low_52w = pivoted.rolling(WINDOW_52W, min_periods=20).min().shift(1)
    rolling_high_20d = pivoted.rolling(WINDOW_20D, min_periods=5).max().shift(1)
    rolling_low_20d = pivoted.rolling(WINDOW_20D, min_periods=5).min().shift(1)

    # 向量化比较(替代逐日逐指数 .loc 循环,P1-1 AZ29)
    # close NaN->False, rolling NaN->False,等价原 pd.isna 检查 + 跳过
    nh_52w_bool = (pivoted > rolling_high_52w)
    nl_52w_bool = (pivoted < rolling_low_52w)
    nh_20d_bool = (pivoted > rolling_high_20d)
    nl_20d_bool = (pivoted < rolling_low_20d)

    # count: sum(axis=1) 向量化(等价原逐指数累加)
    nh_52w_count = nh_52w_bool.sum(axis=1).values
    nl_52w_count = nl_52w_bool.sum(axis=1).values
    nh_20d_count = nh_20d_bool.sum(axis=1).values
    nl_20d_count = nl_20d_bool.sum(axis=1).values

    # details:values.tolist() + list comp(替代逐日逐指数 append)
    close_arr = pivoted.values
    nh_52w_arr = nh_52w_bool.values
    nl_52w_arr = nl_52w_bool.values
    nh_20d_arr = nh_20d_bool.values
    nl_20d_arr = nl_20d_bool.values

    dates = pivoted.index
    names = [INDEX_NAMES.get(iid, iid) for iid in INDICES]
    n_indices = len(INDICES)

    results = []
    for i in range(len(dates)):
        d = dates[i]
        close_row = close_arr[i]
        nh_52w_row = nh_52w_arr[i]
        nl_52w_row = nl_52w_arr[i]
        nh_20d_row = nh_20d_arr[i]
        nl_20d_row = nl_20d_arr[i]
        # list comp 构造 details(close NaN 跳过,等价原 continue)
        details = [
            {
                "index_id": INDICES[j],
                "name": names[j],
                "close": round(float(close_row[j]), 2),  # Python round 保证与原一致
                "nh_52w": bool(nh_52w_row[j]),
                "nl_52w": bool(nl_52w_row[j]),
                "nh_20d": bool(nh_20d_row[j]),
                "nl_20d": bool(nl_20d_row[j]),
            }
            for j in range(n_indices)
            if not np.isnan(close_row[j])
        ]
        results.append({
            "date": d,
            "nh_52w": int(nh_52w_count[i]),
            "nl_52w": int(nl_52w_count[i]),
            "nhnl_52w": int(nh_52w_count[i] - nl_52w_count[i]),
            "nh_20d": int(nh_20d_count[i]),
            "nl_20d": int(nl_20d_count[i]),
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