"""期货机构净多空持仓：净持仓计算 + 准确率回测（滚动窗口）。

品种与对标指数映射：
  IF → hs300, IC → csi500, IH → sz50, IM → csi1000, 综合 → hs300

准确率逻辑：
  - 从 futures_position 读每日 net_ratio，方向 sign = +1（净多）或 -1（净空）
  - 从 index_daily 读对标指数的 close，算次日涨跌（1 日 forward）
  - 同向准确率 = (sign == sign(next_day_return)) 的占比
  - 逆向准确率 = (sign != sign(next_day_return)) 的占比
  - 使用滚动窗口（7/15/30/60/120 日）计算，写入 futures_accuracy

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

DEFAULT_WINDOWS = [7, 15, 30, 60, 120]


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
    min_window = min(windows)

    if target_date is not None:
        # 单日计算：取 target_date 及之前的数据
        if target_date not in pos.index:
            return []
        idx = dates.index(target_date)
        start_idx = max(0, idx - max_window + 1)
        window_check = dates[start_idx : idx + 1]
        if len(window_check) < max_window // 4:  # 窗口内至少要有 1/4 的数据
            return []
        # 输出 target_date 及之前 BACKFILL_DAYS 日的准确率行。
        # 关键：actual_return = 次日涨跌，target_date 当日因次日收盘未就绪必为 None；
        # 但前一日的 actual_return 此时已可算（target_date 收盘已就绪）。
        # 旧实现 work_dates=[target_date] 只算当日 -> actual_return 永远 None、latest_bet 滞后。
        # 回算最近 BACKFILL_DAYS 日：既补 actual_return 滞后，又自愈偶发漏跑（mac 休眠等）多日空缺。
        BACKFILL_DAYS = 10
        work_dates = dates[max(0, idx - BACKFILL_DAYS + 1) : idx + 1]
    else:
        # 全量计算：从第 min_window 个日期开始（各窗口从各自最早有效日起算，
        # 小窗口不被大窗口拖后；早期日期大窗口 follow_n 较小属正常，按实际 n 算）
        work_dates = dates[min_window - 1:]

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


def compute_role_ih_detail(role: str = "中信期货", n_days: int = 15, index_id: str = "sh",
                           as_of_date: str | None = None) -> dict:
    """指定角色4品种合计净加仓方向 vs 上证指数(sh)次日涨跌（最近 n_days + 当天）。

    算法：
      - 取 futures_position 指定 role 的 IH/IF/IC/IM 的 long_chg/short_chg
      - 每日每品种 net_chg = long_chg - short_chg，4品种合计 total_chg
      - citic_dir = sign(total_chg)：正=多，负=空
      - next_return = 上证指数(sh, 上证综指000001) close[t+1]/close[t]-1
        （4品种覆盖50/300/500/1000，对标大盘上证综指，非单品种指数）
      - 同向 count = (多&涨)|(空&跌)；逆向 count = (多&跌)|(空&涨)
      - 主导方向 = 同向 >= 逆向 ? "同向" : "逆向"
      - 每日对错按主导方向判定
      - details 含最近 n_days 个有 next_return 的交易日 + 当天（next_return=null）

    Args:
      as_of_date: 回溯快照日期(YYYYMMDD)。None=用最新数据(实时路径)；
        指定时只取 <= as_of_date 的数据计算15日窗口(backfill 路径，date=as_of_date)。

    Returns:
        {dominant_dir, total, same_count, contrarian_count, correct_count, wrong_count,
         accuracy, sample_start, sample_end,
         details:[{date, ih_chg, if_chg, ic_chg, im_chg, total_chg, citic_dir, next_return, correct}]}
        或 None（数据不足）
    """
    conn = get_conn()
    # 指定角色4品种 long_chg/short_chg
    rows = conn.execute(
        "SELECT date, variety, long_chg, short_chg FROM futures_position "
        "WHERE role=? AND variety IN ('IH','IF','IC','IM') "
        "AND long_chg IS NOT NULL AND short_chg IS NOT NULL "
        "ORDER BY date, variety",
        (role,),
    ).fetchall()
    # 上证指数(sh) close
    close_rows = conn.execute(
        "SELECT date, close FROM index_daily WHERE index_id=? "
        "AND close IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()

    if not rows or not close_rows:
        return None

    # 按日期聚合4品种 net_chg
    chg_by_date: dict[str, dict] = {}
    for r in rows:
        d = r["date"]
        v = r["variety"]
        nc = float(r["long_chg"]) - float(r["short_chg"])
        if d not in chg_by_date:
            chg_by_date[d] = {}
        chg_by_date[d][v] = nc

    close_map = {r["date"]: float(r["close"]) for r in close_rows}
    close_dates = sorted(close_map.keys())
    close_idx = {d: i for i, d in enumerate(close_dates)}

    # 每日计算
    all_daily = []
    for d in sorted(chg_by_date.keys()):
        chgs = chg_by_date[d]
        # 4品种齐全才算
        if not all(v in chgs for v in ("IH", "IF", "IC", "IM")):
            continue
        ih_chg = chgs["IH"]
        if_chg = chgs["IF"]
        ic_chg = chgs["IC"]
        im_chg = chgs["IM"]
        total_chg = ih_chg + if_chg + ic_chg + im_chg
        citic_dir = "多" if total_chg > 0 else ("空" if total_chg < 0 else None)

        # next_return from 上证指数(sh)
        next_return = None
        if d in close_idx:
            ci = close_idx[d]
            if ci + 1 < len(close_dates):
                c0 = close_map[d]
                c1 = close_map[close_dates[ci + 1]]
                if c0 != 0:
                    next_return = round((c1 / c0 - 1) * 100, 4)

        all_daily.append({
            "date": d,
            "ih_chg": round(ih_chg, 0),
            "if_chg": round(if_chg, 0),
            "ic_chg": round(ic_chg, 0),
            "im_chg": round(im_chg, 0),
            "total_chg": round(total_chg, 0),
            "citic_dir": citic_dir,
            "next_return": next_return,
        })

    if not all_daily:
        return None

    # as_of_date 回溯过滤：只取 <= as_of_date 的数据(backfill 路径)
    if as_of_date is not None:
        all_daily = [x for x in all_daily if x["date"] <= as_of_date]
        if not all_daily:
            return None

    # 当天 = 最新日期（next_return 通常为 null，次日未收盘）
    current_day = all_daily[-1]

    # judged = 有 next_return 且方向明确的
    judged = [
        x for x in all_daily
        if x["next_return"] is not None and x["next_return"] != 0 and x["citic_dir"] is not None
    ]
    last_judged = judged[-n_days:]
    if not last_judged:
        return None

    # 统计同向/逆向
    same_count = 0
    contrarian_count = 0
    for x in last_judged:
        is_up = x["next_return"] > 0
        is_long = x["citic_dir"] == "多"
        if (is_long and is_up) or (not is_long and not is_up):
            same_count += 1
        else:
            contrarian_count += 1

    dominant_dir = "同向" if same_count >= contrarian_count else "逆向"
    total = len(last_judged)

    # 每日对错（按主导方向）
    details = []
    correct_count = 0
    wrong_count = 0
    for x in last_judged:
        is_up = x["next_return"] > 0
        is_long = x["citic_dir"] == "多"
        is_same = (is_long and is_up) or (not is_long and not is_up)
        if dominant_dir == "同向":
            correct = is_same
        else:
            correct = not is_same
        if correct:
            correct_count += 1
        else:
            wrong_count += 1
        details.append({
            "date": x["date"],
            "ih_chg": x["ih_chg"],
            "if_chg": x["if_chg"],
            "ic_chg": x["ic_chg"],
            "im_chg": x["im_chg"],
            "total_chg": x["total_chg"],
            "citic_dir": x["citic_dir"],
            "next_return": x["next_return"],
            "correct": correct,
        })

    # 加当天行（当天 next_return=null 时，追加到明细末尾供用户对照）
    if current_day["next_return"] is None:
        details.append({
            "date": current_day["date"],
            "ih_chg": current_day["ih_chg"],
            "if_chg": current_day["if_chg"],
            "ic_chg": current_day["ic_chg"],
            "im_chg": current_day["im_chg"],
            "total_chg": current_day["total_chg"],
            "citic_dir": current_day["citic_dir"],
            "next_return": None,
            "correct": None,
        })

    accuracy = round(correct_count / total * 100, 1) if total > 0 else 0
    follow_ratio = round(same_count / total * 100, 1) if total > 0 else 0

    # 样本区间 = judged 明细的首末日（不含当天 next_return=null 行）
    sample_start = last_judged[0]["date"] if last_judged else None
    sample_end = last_judged[-1]["date"] if last_judged else None

    return {
        "dominant_dir": dominant_dir,
        "total": total,
        "same_count": same_count,
        "contrarian_count": contrarian_count,
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "accuracy": accuracy,
        "follow_ratio": follow_ratio,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "details": details,
    }


def record_ih_detail_acc(role: str, result: dict, conn=None) -> bool:
    """将 compute_role_ih_detail 结果写入 futures_ih_detail_acc 表（每日快照）。

    快照日期 = result["details"] 最后一行的 date（当天行，next_return=null）。
    若最后一行有 next_return（非当天，回溯边界），用其 date 作快照日期。
    INSERT OR REPLACE 按 (date, role) 去重，同日重算覆盖。

    Args:
      role: 角色名（中信期货/top20/国泰君安 等，与 compute_role_ih_detail 入参一致）
      result: compute_role_ih_detail 返回 dict
      conn: 可选连接（backfill 批量场景复用，None 时自建）
    Returns:
      True=写入成功，False=数据不足跳过
    """
    if not result or not result.get("total") or not result.get("details"):
        return False
    snapshot_date = result["details"][-1]["date"]
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO futures_ih_detail_acc "
            "(date, role, dominant_dir, total, same_count, contrarian_count, "
            "correct_count, wrong_count, accuracy, follow_ratio, sample_start, sample_end) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (snapshot_date, role, result["dominant_dir"], result["total"],
             result["same_count"], result["contrarian_count"],
             result["correct_count"], result["wrong_count"], result["accuracy"],
             result["follow_ratio"], result["sample_start"], result["sample_end"]),
        )
        if own_conn:
            conn.commit()
        return True
    finally:
        if own_conn:
            conn.close()


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

    p_compute = sub.add_parser("compute", help="计算截至指定日期的滚动窗口准确率（7/15/30/60/120 日）")
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