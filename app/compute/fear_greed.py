"""§12 恐贪指数（Fear & Greed Index）：等权平均 8 个情绪分，合成 0-100 综合情绪指标。"""
import json
from datetime import datetime

import pandas as pd

from ..db import get_conn

# 8 个输入情绪分
INPUT_SCORES = [
    "a_sentiment",
    "cross_market",
    "sentiment_sz50",
    "sentiment_hs300",
    "sentiment_csi500",
    "sentiment_csi1000",
    "sentiment_cyb",
    "sentiment_kc50",
]

OUTPUT_SCORE_ID = "fear_greed"


def get_label(value: float) -> str:
    """恐贪标签：0-25 极度恐惧，25-40 恐惧，40-60 中性，60-75 贪婪，75-100 极度贪婪。"""
    if value <= 25:
        return "极度恐惧"
    elif value <= 40:
        return "恐惧"
    elif value <= 60:
        return "中性"
    elif value <= 75:
        return "贪婪"
    else:
        return "极度贪婪"


def compute_fear_greed() -> int:
    """计算全量历史恐贪指数，写入 score_daily 表。返回写入天数。"""
    conn = get_conn()

    # 读入 8 个情绪分数据
    placeholders = ",".join(["?"] * len(INPUT_SCORES))
    rows = conn.execute(
        f"SELECT date, score_id, value FROM score_daily WHERE score_id IN ({placeholders}) ORDER BY date",
        INPUT_SCORES,
    ).fetchall()

    # pivot 为 DataFrame：行=date，列=score_id
    df = pd.DataFrame(rows, columns=["date", "score_id", "value"])
    if df.empty:
        return 0

    pivoted = df.pivot(index="date", columns="score_id", values="value")

    # 等权平均，至少 4 个分项才出分（避免单分项误导）
    avail_count = pivoted.notna().sum(axis=1)
    score = pivoted.mean(axis=1, skipna=True)
    score = score.where(avail_count >= 4)

    # 写入 score_daily
    now = datetime.now().isoformat()
    write_rows = []
    for date, val in score.dropna().items():
        if pd.isna(val):
            continue
        label = get_label(val)
        meta = json.dumps({"label": label, "available_scores": int(avail_count.get(date, 0))}, ensure_ascii=False)
        write_rows.append((date, OUTPUT_SCORE_ID, round(float(val), 2), 0, 0, meta, now))

    conn.executemany(
        "INSERT INTO score_daily (date, score_id, value, is_freeze, is_overheat, components, updated_at) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(date, score_id) DO UPDATE SET value=excluded.value, "
        "is_freeze=excluded.is_freeze, is_overheat=excluded.is_overheat, "
        "components=excluded.components, updated_at=excluded.updated_at",
        write_rows,
    )
    conn.commit()
    conn.close()
    return len(write_rows)