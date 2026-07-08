"""期货机构净多空持仓：净持仓计算 + 准确率回测（滚动窗口）。

品种与对标指数映射：
  IF → hs300, IC → csi500, IH → sz50, IM → csi1000, 综合 → hs300

准确率逻辑：
  - 从 futures_position 读每日 net_ratio，方向 sign = +1（净多）或 -1（净空）
  - 从 index_daily 读对标指数的 close，算次日涨跌（1 日 forward）
  - 同向准确率 = (sign == sign(next_day_return)) 的占比
  - 逆向准确率 = (sign != sign(next_day_return)) 的占比
  - 使用三个滚动窗口（30/60/120 日）计算，写入 futures_accuracy

独立跑：python -m app.compute.futures_position compute [--date YYYYMMDD]
        python -m app.compute.futures_position compute-all
"""
import argparse
import sys
from datetime import datetime, timedelta

import pandas as pd

from ..db import get_conn

# 品种 → 对标指数
VARIETY_INDEX_MAP = {
    "IF": "hs300",
    "IC": "csi500",
    "IH": "sz50",
    "IM": "csi1000",
    "综合": "hs300",
}

DEFAULT_WINDOWS = [30, 60, 120]


ROLES = ['top20', '中信期货', '国泰君安']


def _load_positions(role: str = None) -> pd.DataFrame:
    """从 futures_position 读所有 net_ratio 数据，返回 pivot DataFrame（date × variety）。

    Args:
        role: 角色过滤，None 则不过滤
    """
    conn = get_conn()
    if role:
        rows = conn.execute(
            "SELECT date, variety, net_ratio FROM futures_position "
            "WHERE role=? AND net_ratio IS NOT NULL ORDER BY date, variety",
            (role,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT date, variety, net_ratio FROM futures_position "
            "WHERE net_ratio IS NOT NULL ORDER BY date, variety"
        ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = df["date"].astype(str)
    df["net_ratio"] = df["net_ratio"].astype(float)
    pivot = df.pivot_table(index="date", columns="variety", values="net_ratio", aggfunc="first")
    return pivot.sort_index()


def _load_index_close(index_id: str) -> pd.Series:
    """从 index_daily 读指定指数的 close 序列（按 date 升序）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series({r["date"]: r["close"] for r in rows}).sort_index().astype(float)


def _compute_accuracy_for_variety(
    variety: str,
    index_id: str,
    pos_series: pd.Series,
    close_series: pd.Series,
    windows: list,
    target_date: str = None,
) -> list[dict]:
    """对单个品种计算滚动窗口准确率，返回 rows 列表用于写入 futures_accuracy。

    如果 target_date 非空，只计算截至该日的单日准确率；否则全量计算所有日期。
    windows: 滚动窗口大小列表，如 [30, 60, 120]
    """
    # 对齐日期
    common = pos_series.index.intersection(close_series.index)
    if len(common) < 2:
        return []

    pos = pos_series.loc[common].sort_index()
    close = close_series.loc[common].sort_index()

    # 方向：+1 净多，-1 净空，0 持平
    direction = pos.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))

    rows = []
    dates = list(pos.index)

    max_window = max(windows)

    if target_date is not None:
        # 单日计算：取 target_date 及之前的数据
        if target_date not in pos.index:
            return []
        idx = dates.index(target_date)
        start_idx = max(0, idx - max_window + 1)
        work_dates = dates[start_idx : idx + 1]
        if len(work_dates) < max_window // 4:  # 窗口内至少要有 1/4 的数据
            return []
        work_dates = [target_date]  # 只输出 target_date 的准确率行
    else:
        # 全量计算：从第 max_window 个日期开始
        work_dates = dates[max_window - 1:]

    for d in work_dates:
        idx = dates.index(d)

        for w in windows:
            start_idx = max(0, idx - w + 1)
            window_dates = dates[start_idx : idx + 1]

            follow_wins = 0
            follow_total = 0
            contrarian_wins = 0
            contrarian_total = 0

            for wd in window_dates:
                wd_pos = dates.index(wd)
                fwd_idx = wd_pos + 1  # 只看次日涨跌
                if fwd_idx >= len(dates):
                    continue

                cur_close = close.iloc[wd_pos]
                fwd_close = close.iloc[fwd_idx]
                if cur_close == 0:
                    continue
                next_day_return = (fwd_close / cur_close - 1) * 100
                fwd_sign = 1 if next_day_return > 0 else (-1 if next_day_return < 0 else 0)
                if fwd_sign == 0:
                    continue

                sig = direction.iloc[wd_pos]
                if sig == 0:
                    continue

                follow_total += 1
                contrarian_total += 1
                if sig == fwd_sign:
                    follow_wins += 1
                else:
                    contrarian_wins += 1

            # 当前日期的方向
            cur_dir = direction.loc[d] if d in direction.index else 0
            cur_return = None
            d_idx = dates.index(d)
            if d_idx + 1 < len(dates):
                c0 = close.iloc[d_idx]
                if c0 != 0:
                    cur_return = float((close.iloc[d_idx + 1] / c0 - 1) * 100)

            rows.append({
                "date": d,
                "variety": variety,
                "index_id": index_id,
                "window": w,  # 滚动窗口大小 30/60/120
                "follow_accuracy": round(follow_wins / follow_total, 6) if follow_total > 0 else None,
                "contrarian_accuracy": round(contrarian_wins / contrarian_total, 6) if contrarian_total > 0 else None,
                "follow_n": follow_total,
                "contrarian_n": contrarian_total,
                "net_direction": "long" if cur_dir > 0 else ("short" if cur_dir < 0 else "neutral"),
                "actual_return": round(cur_return, 6) if cur_return is not None else None,
            })

    return rows


def compute_accuracy(date: str = None, windows: list = None):
    """计算截至 date 的滚动窗口准确率，按角色分别计算，写入 futures_accuracy。

    Args:
        date: 目标日期（YYYYMMDD），None 则全量计算
        windows: 滚动窗口大小列表，默认 [30, 60, 120]
    """
    if windows is None:
        windows = DEFAULT_WINDOWS

    all_rows = []
    for role in ROLES:
        pos_df = _load_positions(role=role)
        if pos_df.empty:
            print(f"futures_position 表 {role} 无数据，跳过准确率计算")
            continue

        for variety, index_id in VARIETY_INDEX_MAP.items():
            if variety not in pos_df.columns:
                continue
            pos_series = pos_df[variety].dropna()
            close_series = _load_index_close(index_id)
            if close_series.empty:
                continue

            rows = _compute_accuracy_for_variety(
                variety, index_id, pos_series, close_series, windows, target_date=date
            )
            for r in rows:
                r["role"] = role
            all_rows.extend(rows)

    if not all_rows:
        print("无准确率数据可写入")
        return 0

    conn = get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO futures_accuracy "
        "(date, variety, role, index_id, window, follow_accuracy, contrarian_accuracy, "
        "follow_n, contrarian_n, net_direction, actual_return) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["date"], r["variety"], r["role"], r["index_id"], r["window"],
          r["follow_accuracy"], r["contrarian_accuracy"],
          r["follow_n"], r["contrarian_n"],
          r["net_direction"], r["actual_return"]) for r in all_rows],
    )
    conn.commit()
    conn.close()
    return len(all_rows)


def compute_all():
    """全量重算所有历史日期的准确率。"""
    return compute_accuracy(date=None)


def compute_net_position():
    """防御性每日汇总：从 futures_position 读取最新数据，计算综合净持仓（可选）。

    如果采集器已经直接写入 net_ratio，此函数作为防御性重算，确保综合品种的汇总值。
    综合品种 = IF + IC + IH + IM 的 net_ratio 平均。按角色分别计算。
    """
    varieties = ["IF", "IC", "IH", "IM"]
    n = 0
    conn = get_conn()
    try:
        for role in ROLES:
            pos_df = _load_positions(role=role)
            if pos_df.empty:
                continue

            available = [v for v in varieties if v in pos_df.columns]
            if len(available) < 2:
                continue

            composite = pos_df[available].mean(axis=1, skipna=True)
            for date_val, net_ratio in composite.dropna().items():
                conn.execute(
                    "INSERT OR REPLACE INTO futures_position (date, variety, role, net_ratio, source) "
                    "VALUES (?,?,?,?,?)",
                    (date_val, "综合", role, float(net_ratio), "computed"),
                )
                n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def main():
    parser = argparse.ArgumentParser(description="期货机构持仓准确率计算")
    sub = parser.add_subparsers(dest="cmd")

    p_compute = sub.add_parser("compute", help="计算截至指定日期的滚动窗口准确率（30/60/120 日）")
    p_compute.add_argument("--date", type=str, default=None, help="YYYYMMDD，默认最新交易日")

    p_all = sub.add_parser("compute-all", help="全量重算所有历史日期")

    p_net = sub.add_parser("net", help="防御性重算综合品种净持仓")

    args = parser.parse_args()

    if args.cmd == "compute":
        from ..calendar import last_trading_day
        d = args.date or last_trading_day()
        n = compute_accuracy(date=d)
        print(f"=== 期货准确率计算完成: date={d}, windows={DEFAULT_WINDOWS}, rows={n} ===")
    elif args.cmd == "compute-all":
        n = compute_all()
        print(f"=== 期货准确率全量重算完成: rows={n} ===")
    elif args.cmd == "net":
        n = compute_net_position()
        print(f"=== 综合净持仓重算完成: rows={n} ===")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()