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

        ma = {}
        for p in MA_PERIODS:
            ma[p] = series.rolling(p, min_periods=p).mean()

        for date_idx in series.index:
            vals = {}
            for p in MA_PERIODS:
                v = ma[p].get(date_idx)
                if pd.isna(v):
                    vals[p] = None
                else:
                    vals[p] = round(float(v), 2)

            if any(v is None for v in vals.values()):
                continue

            # 判断排列
            if vals[5] > vals[10] > vals[20] > vals[60]:
                alignment = "bullish"
            elif vals[5] < vals[10] < vals[20] < vals[60]:
                alignment = "bearish"
            else:
                alignment = "cross"

            results.append({
                "date": date_idx,
                "index_id": iid,
                "name": INDEX_NAMES.get(iid, iid),
                "alignment": alignment,
                "ma5": vals[5],
                "ma10": vals[10],
                "ma20": vals[20],
                "ma60": vals[60],
            })

    conn.close()

    if not results:
        return {"data": [], "latest": {}}

    # 按日期汇总
    df_results = pd.DataFrame(results)
    grouped = df_results.groupby("date")

    data = []
    for d, grp in grouped:
        bullish = (grp["alignment"] == "bullish").sum()
        bearish = (grp["alignment"] == "bearish").sum()
        cross = (grp["alignment"] == "cross").sum()
        details = grp[["index_id", "name", "alignment", "ma5", "ma10", "ma20", "ma60"]].to_dict("records")
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