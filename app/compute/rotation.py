"""板块轮动速度：计算领涨板块变化频率，量化轮动快慢。

对 SW 行业（sw_%）和同花顺概念（thsc_%）分别计算：
  - 每个交易日找出涨幅最高的板块（领涨板块）
  - 过去 N 日内领涨板块变化的次数
  - 轮动速度 = 变化次数 / (N-1) * 100，归一化到 0-100

写入 daily_metric 表（metric_id: a_rotation_5d, a_rotation_10d, a_rotation_20d,
a_rotation_concept_5d, a_rotation_concept_10d, a_rotation_concept_20d）。
"""
from datetime import datetime

import pandas as pd

from ..db import get_conn

WINDOWS = [5, 10, 20]


def _compute_rotation_for_boards(prefix: str) -> pd.DataFrame:
    """计算某个板块前缀（如 sw_ 或 thsc_）的每日领涨板块及轮动速度。

    返回 DataFrame，列: date, leader, rotation_5d, rotation_10d, rotation_20d
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, index_id, pct_change FROM index_daily "
        "WHERE index_id LIKE ? AND pct_change IS NOT NULL "
        "ORDER BY date, pct_change DESC",
        (f"{prefix}%",),
    ).fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame(columns=["date", "leader"])

    df = pd.DataFrame(rows, columns=["date", "index_id", "pct_change"])
    # 每个日期取涨幅最高的板块
    leaders = df.loc[df.groupby("date")["pct_change"].idxmax()][["date", "index_id"]].copy()
    leaders = leaders.sort_values("date").reset_index(drop=True)
    leaders.rename(columns={"index_id": "leader"}, inplace=True)

    # 计算各窗口的轮动速度（手动滑窗，避免 pandas rolling().apply() 不支持字符串列）
    for w in WINDOWS:
        col = f"rotation_{w}d"
        changes = []
        leaders_list = leaders["leader"].tolist()
        for i in range(len(leaders_list)):
            start = max(0, i - w + 1)
            window = leaders_list[start:i + 1]
            changes.append(_count_changes(window))
        leaders[col] = changes

    # 归一化：变化次数 / (N-1) * 100
    for w in WINDOWS:
        col = f"rotation_{w}d"
        if w > 1:
            leaders[col] = leaders[col] / (w - 1) * 100
        leaders[col] = leaders[col].round(1)

    return leaders


def _count_changes(leaders: list) -> int:
    """计算领涨板块变化的次数。

    例如：['A', 'A', 'B', 'C', 'B'] → 变化 3 次（A→B, B→C, C→B）
    """
    if len(leaders) < 2:
        return 0
    changes = 0
    for i in range(1, len(leaders)):
        if leaders[i] != leaders[i - 1]:
            changes += 1
    return changes


def compute_rotation(date: str | None = None) -> dict:
    """计算当日板块轮动速度。

    返回 dict，包含:
        {date, sw_rotation_5d, sw_rotation_10d, sw_rotation_20d,
         concept_rotation_5d, concept_rotation_10d, concept_rotation_20d,
         sw_leader, concept_leader, sw_top3, concept_top3}
    """
    sw_df = _compute_rotation_for_boards("sw_")
    concept_df = _compute_rotation_for_boards("thsc_")

    if date is None:
        # 取最新日期
        if not sw_df.empty:
            date = sw_df["date"].iloc[-1]
        elif not concept_df.empty:
            date = concept_df["date"].iloc[-1]
        else:
            date = datetime.now().strftime("%Y%m%d")

    result: dict = {"date": date}

    # SW 行业轮动
    if not sw_df.empty:
        sw_row = sw_df[sw_df["date"] == date]
        if not sw_row.empty:
            sw_row = sw_row.iloc[0]
            result["sw_rotation_5d"] = sw_row.get("rotation_5d")
            result["sw_rotation_10d"] = sw_row.get("rotation_10d")
            result["sw_rotation_20d"] = sw_row.get("rotation_20d")
            result["sw_leader"] = sw_row.get("leader")
            # 当日领涨前3
            result["sw_top3"] = _get_top_n("sw_", date, n=3)
        else:
            for w in WINDOWS:
                result[f"sw_rotation_{w}d"] = None
            result["sw_leader"] = None
            result["sw_top3"] = []
    else:
        for w in WINDOWS:
            result[f"sw_rotation_{w}d"] = None
        result["sw_leader"] = None
        result["sw_top3"] = []

    # 概念板块轮动
    if not concept_df.empty:
        concept_row = concept_df[concept_df["date"] == date]
        if not concept_row.empty:
            concept_row = concept_row.iloc[0]
            result["concept_rotation_5d"] = concept_row.get("rotation_5d")
            result["concept_rotation_10d"] = concept_row.get("rotation_10d")
            result["concept_rotation_20d"] = concept_row.get("rotation_20d")
            result["concept_leader"] = concept_row.get("leader")
            result["concept_top3"] = _get_top_n("thsc_", date, n=3)
        else:
            for w in WINDOWS:
                result[f"concept_rotation_{w}d"] = None
            result["concept_leader"] = None
            result["concept_top3"] = []
    else:
        for w in WINDOWS:
            result[f"concept_rotation_{w}d"] = None
        result["concept_leader"] = None
        result["concept_top3"] = []

    return result


def _get_top_n(prefix: str, date: str, n: int = 3) -> list[dict]:
    """获取某日涨幅前 N 的板块。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT index_id, pct_change FROM index_daily "
        "WHERE index_id LIKE ? AND date=? AND pct_change IS NOT NULL "
        "ORDER BY pct_change DESC LIMIT ?",
        (f"{prefix}%", date, n),
    ).fetchall()
    conn.close()
    return [{"index_id": r["index_id"], "pct_change": r["pct_change"]} for r in rows]


def store_rotation(rotation_data: dict) -> int:
    """将轮动速度写入 daily_metric 表，返回写入行数。"""
    now = datetime.now().isoformat()
    conn = get_conn()
    date = rotation_data["date"]
    n = 0

    metrics = [
        ("sw_rotation_5d", "a_rotation_5d"),
        ("sw_rotation_10d", "a_rotation_10d"),
        ("sw_rotation_20d", "a_rotation_20d"),
        ("concept_rotation_5d", "a_rotation_concept_5d"),
        ("concept_rotation_10d", "a_rotation_concept_10d"),
        ("concept_rotation_20d", "a_rotation_concept_20d"),
    ]

    for key, metric_id in metrics:
        val = rotation_data.get(key)
        if val is None:
            continue
        conn.execute(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            (date, metric_id, float(val), "derived", now),
        )
        n += 1

    conn.commit()
    conn.close()
    return n


def backfill_all() -> int:
    """回填所有历史日期的板块轮动速度数据。"""
    sw_df = _compute_rotation_for_boards("sw_")
    concept_df = _compute_rotation_for_boards("thsc_")

    now = datetime.now().isoformat()
    conn = get_conn()
    n = 0

    metric_pairs = [
        ("rotation_5d", "a_rotation_5d"),
        ("rotation_10d", "a_rotation_10d"),
        ("rotation_20d", "a_rotation_20d"),
    ]
    concept_metric_pairs = [
        ("rotation_5d", "a_rotation_concept_5d"),
        ("rotation_10d", "a_rotation_concept_10d"),
        ("rotation_20d", "a_rotation_concept_20d"),
    ]

    # SW 行业轮动
    if not sw_df.empty:
        for _, row in sw_df.iterrows():
            date = row["date"]
            for col, mid in metric_pairs:
                val = row.get(col)
                if val is None or pd.isna(val):
                    continue
                conn.execute(
                    "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
                    "source=excluded.source, updated_at=excluded.updated_at "
                    "WHERE daily_metric.source != 'manual'",
                    (date, mid, float(val), "derived", now),
                )
                n += 1

    # 概念板块轮动
    if not concept_df.empty:
        for _, row in concept_df.iterrows():
            date = row["date"]
            for col, mid in concept_metric_pairs:
                val = row.get(col)
                if val is None or pd.isna(val):
                    continue
                conn.execute(
                    "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT(date, metric_id) DO UPDATE SET value=excluded.value, "
                    "source=excluded.source, updated_at=excluded.updated_at "
                    "WHERE daily_metric.source != 'manual'",
                    (date, mid, float(val), "derived", now),
                )
                n += 1

    conn.commit()
    conn.close()
    return n


if __name__ == "__main__":
    result = compute_rotation()
    for k, v in result.items():
        print(f"  {k}: {v}")
    n = store_rotation(result)
    print(f"  写入 {n} 行")