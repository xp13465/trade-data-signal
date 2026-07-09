"""成交量对比（放量/缩量标注）

从 a_amount（全市场成交额，亿元）计算 MA5/MA20、量比、量价信号。
结果写入 daily_metric 表（新增 metric_id: a_volume_ratio, a_amount_ma5, a_amount_ma20, a_volume_signal）。
"""

import pandas as pd

from ..db import get_conn

# 量比阈值
RATIO_HIGH = 1.2   # 放量
RATIO_LOW = 0.8    # 缩量


def compute_volume_ratio(verbose: bool = True) -> int:
    """计算全量历史成交量对比指标，写入 daily_metric。

    返回写入的日期数（日均写入 4 条 metric）。
    """
    conn = get_conn()

    # 读取成交额序列
    amount_rows = conn.execute(
        "SELECT date, value FROM daily_metric WHERE metric_id='a_amount' ORDER BY date"
    ).fetchall()
    if not amount_rows:
        if verbose:
            print("[volume_ratio] 无 a_amount 数据，跳过")
        return 0

    df = pd.DataFrame(amount_rows, columns=["date", "amount"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["amount"])
    df = df.set_index("date")
    df.index = pd.to_datetime(df.index, format="%Y%m%d")

    # 读取上证指数涨跌幅（用于判断涨跌方向）
    idx_rows = conn.execute(
        "SELECT date, pct_change FROM index_daily WHERE index_id='sh' ORDER BY date"
    ).fetchall()
    idx_df = pd.DataFrame(idx_rows, columns=["date", "pct_change"])
    idx_df["pct_change"] = pd.to_numeric(idx_df["pct_change"], errors="coerce")
    idx_df = idx_df.set_index("date")
    idx_df.index = pd.to_datetime(idx_df.index, format="%Y%m%d")

    # 对齐到成交额日期
    df = df.join(idx_df[["pct_change"]], how="left")

    # 计算 MA5 / MA20
    df["ma5"] = df["amount"].rolling(5, min_periods=3).mean()
    df["ma20"] = df["amount"].rolling(20, min_periods=10).mean()

    # 量比 = 当日成交额 / MA5
    df["ratio"] = df["amount"] / df["ma5"]

    # 量价信号
    def _signal(row):
        ratio = row["ratio"]
        pct = row["pct_change"]
        if pd.isna(ratio) or pd.isna(pct):
            return "正常"
        if ratio > RATIO_HIGH:
            return "放量上涨" if pct > 0 else "放量下跌"
        if ratio < RATIO_LOW:
            return "缩量上涨" if pct > 0 else "缩量下跌"
        return "正常"

    df["signal"] = df.apply(_signal, axis=1)

    # 写入 daily_metric（4 个新 metric_id）
    written = 0
    now = pd.Timestamp.now().isoformat()
    for date_idx, row in df.iterrows():
        d = date_idx.strftime("%Y%m%d")
        for mid, val in [
            ("a_volume_ratio", row["ratio"]),
            ("a_amount_ma5", row["ma5"]),
            ("a_amount_ma20", row["ma20"]),
            ("a_volume_signal", None),  # 文本信号，单独写入
        ]:
            if mid == "a_volume_signal":
                continue
            if pd.isna(val):
                continue
            conn.execute(
                "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(date, metric_id) DO UPDATE SET "
                "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
                "WHERE daily_metric.source != 'manual'",
                (d, mid, float(val), "computed", now),
            )
            written += 1

        # a_volume_signal 是文本值，存为 value_text（用 value=0 存，signal 文本存备注）
        # 实际：用 value=NULL 插入，signal 字段无法存文本，改存到单独的 value 字段为 0，
        # 前端通过 ratio + pct_change 判断即可，不依赖 a_volume_signal 文本。
        # 但为了数据完整性，我们把 signal 编码为数值：
        # 放量上涨=1, 放量下跌=2, 缩量上涨=3, 缩量下跌=4, 正常=0
        signal_map = {"放量上涨": 1, "放量下跌": 2, "缩量上涨": 3, "缩量下跌": 4, "正常": 0}
        sig_val = signal_map.get(row["signal"], 0)
        conn.execute(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            (d, "a_volume_signal", float(sig_val), "computed", now),
        )
        written += 1

    conn.commit()
    conn.close()

    n_days = len(df)
    if verbose:
        print(f"[volume_ratio] 计算完成: {n_days} 天, 写入 {written} 条 metric")
    return n_days


if __name__ == "__main__":
    compute_volume_ratio()