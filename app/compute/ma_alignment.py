"""均线排列状态（P3-15）：统计 8 个主要指数处于多头/空头/震荡排列的数量。

计算逻辑：
- 对 8 个主要指数，计算 MA5, MA10, MA20, MA60
- 多头排列：MA5 > MA10 > MA20 > MA60
- 空头排列：MA5 < MA10 < MA20 < MA60
- 交叉/震荡：其他情况
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

MA_PERIODS = [5, 10, 20, 60]


def compute_ma_alignment(date: str | None = None) -> dict:
    """计算全量历史均线排列，返回 dict 包含 data 和 latest。"""
    conn = get_conn()

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

    results = []

    for iid in INDICES:
        if iid not in pivoted.columns:
            continue
        series = pivoted[iid].dropna()
        if len(series) < max(MA_PERIODS):
            continue

        # 向量化 MA 计算(替代逐日 .get 循环,P1-1 AZ29)
        # rolling.mean() 已向量化,取 .values 后用 numpy 索引替代 pandas .get
        ma5 = series.rolling(5, min_periods=5).mean().values
        ma10 = series.rolling(10, min_periods=10).mean().values
        ma20 = series.rolling(20, min_periods=20).mean().values
        ma60 = series.rolling(60, min_periods=60).mean().values

        # 有效 mask(4 个 MA 都非 NaN,等价原 any(None) continue)
        valid = ~(np.isnan(ma5) | np.isnan(ma10) | np.isnan(ma20) | np.isnan(ma60))
        valid_idx = np.where(valid)[0]

        # 逐元素 Python round + 排列判断
        # 必须用 Python round:np.round 在边界值(如 118.175)与 Python round 有差异
        # (118.175 浮点存为 118.1749999...,Python round->118.17,np.round->118.18)
        dates_arr = series.index
        name = INDEX_NAMES.get(iid, iid)
        for i in valid_idx:
            m5 = round(float(ma5[i]), 2)
            m10 = round(float(ma10[i]), 2)
            m20 = round(float(ma20[i]), 2)
            m60 = round(float(ma60[i]), 2)
            if m5 > m10 > m20 > m60:
                align = "bullish"
            elif m5 < m10 < m20 < m60:
                align = "bearish"
            else:
                align = "cross"
            results.append({
                "date": dates_arr[i],
                "index_id": iid,
                "name": name,
                "alignment": align,
                "ma5": m5,
                "ma10": m10,
                "ma20": m20,
                "ma60": m60,
            })

    conn.close()

    if not results:
        return {"data": [], "latest": {}}

    # 按日期汇总:sort + numpy 分组 + 一次 values.tolist
    # (替代 groupby 逐组 values.tolist 8630 次,原 to_dict 4.7s 瓶颈,values.tolist 1.2s 仍慢)
    df_results = pd.DataFrame(results)
    # 加 order 列保持 INDICES 顺序(groupby 保持 results 顺序=INDICES 顺序,sort 后需 order 列)
    index_order = {iid: i for i, iid in enumerate(INDICES)}
    df_results["order"] = df_results["index_id"].map(index_order)
    df_sorted = df_results.sort_values(["date", "order"])

    dates_arr = df_sorted["date"].values
    cols = ["index_id", "name", "alignment", "ma5", "ma10", "ma20", "ma60"]
    all_rows = df_sorted[cols].values.tolist()

    # numpy 找分组边界(连续相同 date;sort 后同 date 连续)
    date_change = np.concatenate(([True], dates_arr[1:] != dates_arr[:-1]))
    group_starts = np.where(date_change)[0]
    group_ends = np.append(group_starts[1:], len(dates_arr))

    data = []
    for s, e in zip(group_starts, group_ends):
        d = dates_arr[s]
        rows = all_rows[s:e]
        details = [dict(zip(cols, r)) for r in rows]
        # count 用 list comp(避免 pandas bool 比较 + sum 开销)
        aligns = [r[2] for r in rows]  # alignment 是 cols[2]
        bullish = sum(1 for a in aligns if a == "bullish")
        bearish = sum(1 for a in aligns if a == "bearish")
        cross = sum(1 for a in aligns if a == "cross")
        data.append({
            "date": d,
            "bullish": int(bullish),
            "bearish": int(bearish),
            "cross": int(cross),
            "details": details,
        })

    data.sort(key=lambda x: x["date"])
    latest = data[-1] if data else {}
    return {"data": data, "latest": latest}


def store_ma_alignment(results: dict) -> int:
    """将均线排列数据写入 daily_metric 表，返回写入行数。"""
    data = results.get("data", [])
    if not data:
        return 0

    now = datetime.now().isoformat()
    conn = get_conn()
    n = 0

    metric_ids = [
        ("a_ma_bullish", "bullish"),
        ("a_ma_bearish", "bearish"),
        ("a_ma_cross", "cross"),
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

    conn.commit()
    conn.close()
    return n


if __name__ == "__main__":
    result = compute_ma_alignment()
    print(f"Computed {len(result['data'])} days")
    if result["latest"]:
        print(json.dumps(result["latest"], ensure_ascii=False, indent=2))