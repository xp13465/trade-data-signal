"""worker-cleanup: D3 阶段2 校验（BaoStock vs mootdx）+ 补 D2 换手率分布。

任务（详见 TASKS.md 交接状态节）：
1. JOIN baostock_daily_raw vs mootdx_daily_raw on (code,date)，对比共有字段
   open/high/low/close/volume/amount/pct_change 的差异率（剔除除权日）。
2. 用 baostock_daily_raw 的 turnover 算全市场换手率分布（按日聚合），
   回填 daily_metric 2016-2026（source='baostock'）。

约束：
- 不 cd（用绝对路径）；不 commit/push。
- 手动值保护：upsert WHERE source != 'manual'。
- NaN 过滤：if v != v: continue。
- 写 data/sentiment.db (daily_metric)，读 data/stock_daily.db（两 raw 表）。

CLI:
  python -m app.collector.cleanup_d3d2 validate        # 仅阶段2 校验
  python -m app.collector.cleanup_d3d2 turnover        # 仅换手率分布回填
  python -m app.collector.cleanup_d3d2 all             # 两步串行
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

from app.db import get_conn

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"
SENTIMENT_DB_PATH = _DATA_DIR / "sentiment.db"
REPORT_PATH = _DATA_DIR / "cleanup_d3d2_report.json"

START_DATE = "20160101"  # 校验和回填起点（与 D2 一致）
END_DATE = "20260706"

# 除权日检测阈值：两源 pct_change 差异 > 0.5%（绝对值）视为除权日/源差异，
# 剔除后再算 pct_change 差异率（其他字段除权日通常仍一致，因为是同一日的真实价格）。
PCT_EXDIV_THRESHOLD = 0.5  # %

# 换手率分布指标（自定 metric_id，参考 D2 width_history 命名风格）
TURNOVER_METRICS = [
    "a_turnover_mean",      # 全市场换手率均值（%）
    "a_turnover_median",    # 中位数
    "a_turnover_p90",       # 90 分位（活跃度头部）
    "a_turnover_p10",       # 10 分位（活跃度底部）
    "a_turnover_gt5_pct",   # 换手率>5% 家数占比（0-1 小数）
]


# ═════════════════════════════════════════════════════════════════════════════
# 阶段2: BaoStock vs mootdx 交叉校验
# ═════════════════════════════════════════════════════════════════════════════
def validate_cross_source() -> dict:
    """JOIN baostock vs mootdx，算各字段差异率。

    策略：
    - 用 SQL 聚合（避免 16M 行全载入内存），分两步：
      (1) 算重叠行数 + 各字段 ABS diff 累加（含除权日）；
      (2) 用 pct_change 差异 > 0.5% 标除权日，重算各字段差异（剔除除权日）。
    - volume 已知单位差 100x（mootdx=手, baostock=股），单独处理：归一化到股。
    - amount/open/high/low/close 应高度一致（同源不复权原始价）。
    """
    print(f"[validate] JOIN baostock vs mootdx, {START_DATE}..{END_DATE} ...", flush=True)
    t0 = time.time()
    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=60.0)
    try:
        # 步骤 1：重叠行数 + 各字段差异聚合（全量，含除权日）
        # volume 归一化：mootdx × 100 → 股，与 baostock 对齐
        sql_full = f"""
        SELECT
          COUNT(*) AS n_overlap,
          SUM(CASE WHEN m.open>0 AND b.open IS NOT NULL
                   THEN ABS(b.open - m.open) / m.open ELSE 0 END) AS sum_open_diff,
          SUM(CASE WHEN m.high>0 AND b.high IS NOT NULL
                   THEN ABS(b.high - m.high) / m.high ELSE 0 END) AS sum_high_diff,
          SUM(CASE WHEN m.low>0 AND b.low IS NOT NULL
                   THEN ABS(b.low - m.low) / m.low ELSE 0 END) AS sum_low_diff,
          SUM(CASE WHEN m.close>0 AND b.close IS NOT NULL
                   THEN ABS(b.close - m.close) / m.close ELSE 0 END) AS sum_close_diff,
          SUM(CASE WHEN m.volume>0 AND b.volume IS NOT NULL
                   THEN ABS(b.volume - m.volume*100.0) / (m.volume*100.0) ELSE 0 END) AS sum_vol_diff,
          SUM(CASE WHEN m.amount>0 AND b.amount IS NOT NULL
                   THEN ABS(b.amount - m.amount) / m.amount ELSE 0 END) AS sum_amt_diff,
          SUM(CASE WHEN m.pct_change IS NOT NULL AND b.pct_change IS NOT NULL
                   THEN ABS(b.pct_change - m.pct_change) ELSE 0 END) AS sum_pct_diff_abs,
          SUM(CASE WHEN m.pct_change IS NOT NULL AND b.pct_change IS NOT NULL
                   THEN 1 ELSE 0 END) AS n_pct_both
        FROM baostock_daily_raw b
        INNER JOIN mootdx_daily_raw m ON b.code=m.code AND b.date=m.date
        WHERE b.date >= '{START_DATE}' AND b.date <= '{END_DATE}'
        """
        row = conn.execute(sql_full).fetchone()
        n_overlap = row[0]
        sum_open_diff = row[1] or 0.0
        sum_high_diff = row[2] or 0.0
        sum_low_diff = row[3] or 0.0
        sum_close_diff = row[4] or 0.0
        sum_vol_diff = row[5] or 0.0
        sum_amt_diff = row[6] or 0.0
        sum_pct_diff_abs = row[7] or 0.0
        n_pct_both = row[8] or 0
        print(f"[validate] overlap rows={n_overlap:,}, took {time.time()-t0:.1f}s", flush=True)

        # 步骤 2：剔除除权日后重算（pct_change 差异 > 阈值视为除权日/源差异）
        sql_excl = f"""
        SELECT
          COUNT(*) AS n_overlap,
          SUM(CASE WHEN m.open>0 AND b.open IS NOT NULL
                   THEN ABS(b.open - m.open) / m.open ELSE 0 END) AS sum_open_diff,
          SUM(CASE WHEN m.high>0 AND b.high IS NOT NULL
                   THEN ABS(b.high - m.high) / m.high ELSE 0 END) AS sum_high_diff,
          SUM(CASE WHEN m.low>0 AND b.low IS NOT NULL
                   THEN ABS(b.low - m.low) / m.low ELSE 0 END) AS sum_low_diff,
          SUM(CASE WHEN m.close>0 AND b.close IS NOT NULL
                   THEN ABS(b.close - m.close) / m.close ELSE 0 END) AS sum_close_diff,
          SUM(CASE WHEN m.volume>0 AND b.volume IS NOT NULL
                   THEN ABS(b.volume - m.volume*100.0) / (m.volume*100.0) ELSE 0 END) AS sum_vol_diff,
          SUM(CASE WHEN m.amount>0 AND b.amount IS NOT NULL
                   THEN ABS(b.amount - m.amount) / m.amount ELSE 0 END) AS sum_amt_diff,
          SUM(CASE WHEN m.pct_change IS NOT NULL AND b.pct_change IS NOT NULL
                   THEN ABS(b.pct_change - m.pct_change) ELSE 0 END) AS sum_pct_diff_abs,
          SUM(CASE WHEN m.pct_change IS NOT NULL AND b.pct_change IS NOT NULL
                   THEN 1 ELSE 0 END) AS n_pct_both
        FROM baostock_daily_raw b
        INNER JOIN mootdx_daily_raw m ON b.code=m.code AND b.date=m.date
        WHERE b.date >= '{START_DATE}' AND b.date <= '{END_DATE}'
          AND (m.pct_change IS NULL OR b.pct_change IS NULL
               OR ABS(b.pct_change - m.pct_change) <= {PCT_EXDIV_THRESHOLD})
        """
        row2 = conn.execute(sql_excl).fetchone()
        n_overlap_excl = row2[0]
        sum_open_diff_excl = row2[1] or 0.0
        sum_high_diff_excl = row2[2] or 0.0
        sum_low_diff_excl = row2[3] or 0.0
        sum_close_diff_excl = row2[4] or 0.0
        sum_vol_diff_excl = row2[5] or 0.0
        sum_amt_diff_excl = row2[6] or 0.0
        sum_pct_diff_abs_excl = row2[7] or 0.0
        n_pct_both_excl = row2[8] or 0
        n_exdiv = n_overlap - n_overlap_excl
        print(f"[validate] after excl ex-div: {n_overlap_excl:,} rows, ex-div={n_exdiv:,} "
              f"({n_exdiv/max(n_overlap,1)*100:.2f}%), took {time.time()-t0:.1f}s", flush=True)

        # 步骤 3：抽样统计中位 / 90 分位（抽 200 只 × 全段，避免 16M 行载入）
        # 取重叠的 code 中均匀抽 200 只
        codes_row = conn.execute(
            f"SELECT b.code FROM baostock_daily_raw b "
            f"WHERE b.date>='{START_DATE}' AND b.date<='{END_DATE}' "
            f"GROUP BY b.code HAVING COUNT(*) > 100 ORDER BY b.code "
            f"LIMIT 1 OFFSET 0"
        ).fetchall()
        # 用 SQLite 的 row_number() 均匀采样
        sample_codes = [r[0] for r in conn.execute(
            f"SELECT code FROM ("
            f"  SELECT code, ROW_NUMBER() OVER (ORDER BY code) AS rn FROM ("
            f"    SELECT DISTINCT code FROM baostock_daily_raw "
            f"    WHERE date>='{START_DATE}' AND date<='{END_DATE}'"
            f"  )"
            f") WHERE rn % (SELECT COUNT(DISTINCT code) FROM baostock_daily_raw "
            f"              WHERE date>='{START_DATE}' AND date<='{END_DATE}') / 200 = 0 "
            f"LIMIT 200"
        ).fetchall()]
        if not sample_codes:
            # 老版 SQLite 无 ROW_NUMBER，退化为前 200 只
            sample_codes = [r[0] for r in conn.execute(
                f"SELECT DISTINCT code FROM baostock_daily_raw "
                f"WHERE date>='{START_DATE}' AND date<='{END_DATE}' LIMIT 200"
            ).fetchall()]
        codes_in = ",".join(f"'{c}'" for c in sample_codes)
        sample_df = pd.read_sql_query(
            f"SELECT b.open AS b_open, m.open AS m_open, "
            f"       b.high AS b_high, m.high AS m_high, "
            f"       b.low AS b_low, m.low AS m_low, "
            f"       b.close AS b_close, m.close AS m_close, "
            f"       b.volume AS b_vol, m.volume AS m_vol, "
            f"       b.amount AS b_amt, m.amount AS m_amt, "
            f"       b.pct_change AS b_pct, m.pct_change AS m_pct "
            f"FROM baostock_daily_raw b "
            f"INNER JOIN mootdx_daily_raw m ON b.code=m.code AND b.date=m.date "
            f"WHERE b.date>='{START_DATE}' AND b.date<='{END_DATE}' "
            f"  AND b.code IN ({codes_in})", conn
        )
        print(f"[validate] sample loaded {len(sample_df):,} rows from {len(sample_codes)} codes", flush=True)

        def _stats(b, m, normalize_m=None):
            """返回 (mean, median, p90, max) of |b-m|/m."""
            if normalize_m:
                m = m * normalize_m
            mask = (m.notna()) & (b.notna()) & (m > 0)
            if mask.sum() == 0:
                return {"mean": None, "median": None, "p90": None, "max": None, "n": 0}
            diff = (b[mask] - m[mask]).abs() / m[mask]
            return {
                "mean": round(float(diff.mean()), 6),
                "median": round(float(diff.median()), 6),
                "p90": round(float(diff.quantile(0.9)), 6),
                "max": round(float(diff.max()), 6),
                "n": int(mask.sum()),
            }

        # 全量（含除权日）样本统计
        samp_full = {
            "open": _stats(sample_df["b_open"], sample_df["m_open"]),
            "high": _stats(sample_df["b_high"], sample_df["m_high"]),
            "low": _stats(sample_df["b_low"], sample_df["m_low"]),
            "close": _stats(sample_df["b_close"], sample_df["m_close"]),
            "volume": _stats(sample_df["b_vol"], sample_df["m_vol"], normalize_m=100.0),
            "amount": _stats(sample_df["b_amt"], sample_df["m_amt"]),
            "pct_change_abs": _stats(sample_df["b_pct"], sample_df["m_pct"].abs().replace(0, 1.0)
                                     ) if False else None,  # 占位
        }
        # pct_change 用绝对差（百分点），不是相对差
        mask = (sample_df["b_pct"].notna()) & (sample_df["m_pct"].notna())
        pct_diff_abs = (sample_df["b_pct"][mask] - sample_df["m_pct"][mask]).abs()
        samp_full["pct_change_abs"] = {
            "mean_pp": round(float(pct_diff_abs.mean()), 4),
            "median_pp": round(float(pct_diff_abs.median()), 4),
            "p90_pp": round(float(pct_diff_abs.quantile(0.9)), 4),
            "max_pp": round(float(pct_diff_abs.max()), 4),
            "n": int(mask.sum()),
        }

        # 剔除除权日后样本统计
        exdiv_mask = (sample_df["b_pct"].notna()) & (sample_df["m_pct"].notna()) & \
                     ((sample_df["b_pct"] - sample_df["m_pct"]).abs() > PCT_EXDIV_THRESHOLD)
        samp_excl_df = sample_df[~exdiv_mask].copy()
        samp_excl = {
            "open": _stats(samp_excl_df["b_open"], samp_excl_df["m_open"]),
            "high": _stats(samp_excl_df["b_high"], samp_excl_df["m_high"]),
            "low": _stats(samp_excl_df["b_low"], samp_excl_df["m_low"]),
            "close": _stats(samp_excl_df["b_close"], samp_excl_df["m_close"]),
            "volume": _stats(samp_excl_df["b_vol"], samp_excl_df["m_vol"], normalize_m=100.0),
            "amount": _stats(samp_excl_df["b_amt"], samp_excl_df["m_amt"]),
        }
        mask2 = (samp_excl_df["b_pct"].notna()) & (samp_excl_df["m_pct"].notna())
        pct_diff_abs2 = (samp_excl_df["b_pct"][mask2] - samp_excl_df["m_pct"][mask2]).abs()
        samp_excl["pct_change_abs"] = {
            "mean_pp": round(float(pct_diff_abs2.mean()), 4),
            "median_pp": round(float(pct_diff_abs2.median()), 4),
            "p90_pp": round(float(pct_diff_abs2.quantile(0.9)), 4),
            "max_pp": round(float(pct_diff_abs2.max()), 4),
            "n": int(mask2.sum()),
        }

        # 全量均值差异（含除权日，用累计 SUM/COUNT）
        full_mean = {
            "n_overlap": n_overlap,
            "open_mean_diff": round(sum_open_diff / max(n_overlap, 1), 6),
            "high_mean_diff": round(sum_high_diff / max(n_overlap, 1), 6),
            "low_mean_diff": round(sum_low_diff / max(n_overlap, 1), 6),
            "close_mean_diff": round(sum_close_diff / max(n_overlap, 1), 6),
            "volume_mean_diff": round(sum_vol_diff / max(n_overlap, 1), 6),
            "amount_mean_diff": round(sum_amt_diff / max(n_overlap, 1), 6),
            "pct_change_mean_diff_pp": round(sum_pct_diff_abs / max(n_pct_both, 1), 4),
            "n_pct_both": n_pct_both,
        }
        excl_mean = {
            "n_overlap": n_overlap_excl,
            "n_exdiv": n_exdiv,
            "pct_exdiv_of_overlap": round(n_exdiv / max(n_overlap, 1) * 100, 2),
            "open_mean_diff": round(sum_open_diff_excl / max(n_overlap_excl, 1), 6),
            "high_mean_diff": round(sum_high_diff_excl / max(n_overlap_excl, 1), 6),
            "low_mean_diff": round(sum_low_diff_excl / max(n_overlap_excl, 1), 6),
            "close_mean_diff": round(sum_close_diff_excl / max(n_overlap_excl, 1), 6),
            "volume_mean_diff": round(sum_vol_diff_excl / max(n_overlap_excl, 1), 6),
            "amount_mean_diff": round(sum_amt_diff_excl / max(n_overlap_excl, 1), 6),
            "pct_change_mean_diff_pp": round(sum_pct_diff_abs_excl / max(n_pct_both_excl, 1), 4),
            "n_pct_both": n_pct_both_excl,
        }
    finally:
        conn.close()

    # 单源独有行数（不在另一源出现）
    print("[validate] counting source-only rows ...", flush=True)
    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=60.0)
    try:
        bao_only = conn.execute(
            f"SELECT COUNT(*) FROM baostock_daily_raw b "
            f"WHERE b.date>='{START_DATE}' AND b.date<='{END_DATE}' "
            f"  AND NOT EXISTS (SELECT 1 FROM mootdx_daily_raw m "
            f"                  WHERE m.code=b.code AND m.date=b.date)"
        ).fetchone()[0]
        moo_only = conn.execute(
            f"SELECT COUNT(*) FROM mootdx_daily_raw m "
            f"WHERE m.date>='{START_DATE}' AND m.date<='{END_DATE}' "
            f"  AND NOT EXISTS (SELECT 1 FROM baostock_daily_raw b "
            f"                  WHERE b.code=m.code AND b.date=m.date)"
        ).fetchone()[0]
        bao_total = conn.execute(
            f"SELECT COUNT(*) FROM baostock_daily_raw "
            f"WHERE date>='{START_DATE}' AND date<='{END_DATE}'"
        ).fetchone()[0]
        moo_total = conn.execute(
            f"SELECT COUNT(*) FROM mootdx_daily_raw "
            f"WHERE date>='{START_DATE}' AND date<='{END_DATE}'"
        ).fetchone()[0]
    finally:
        conn.close()
    print(f"[validate] bao_only={bao_only:,}, moo_only={moo_only:,}, "
          f"bao_total={bao_total:,}, moo_total={moo_total:,}", flush=True)

    result = {
        "range": f"{START_DATE}..{END_DATE}",
        "overlap_rows": n_overlap,
        "bao_only_rows": bao_only,
        "moo_only_rows": moo_only,
        "bao_total_rows": bao_total,
        "moo_total_rows": moo_total,
        "exdiv_threshold_pct": PCT_EXDIV_THRESHOLD,
        "full_mean_diff": full_mean,
        "excl_exdiv_mean_diff": excl_mean,
        "sample_stats_full": samp_full,
        "sample_stats_excl_exdiv": samp_excl,
        "sample_codes_n": len(sample_codes),
        "elapsed_sec": round(time.time() - t0, 1),
    }
    return result


# ═════════════════════════════════════════════════════════════════════════════
# 补 D2 换手率分布（用 BaoStock turnover）
# ═════════════════════════════════════════════════════════════════════════════
def _now():
    return dt.datetime.now().isoformat()


def compute_turnover_dist() -> pd.DataFrame:
    """从 baostock_daily_raw 算每日换手率分布。

    返回 DataFrame: date/mean/median/p90/p10/gt5_pct。
    每日所有股票 turnover 的分布统计（剔除 NULL/NaN）。
    """
    print(f"[turnover] loading baostock turnover {START_DATE}..{END_DATE} ...", flush=True)
    t0 = time.time()
    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=60.0)
    try:
        df = pd.read_sql_query(
            f"SELECT date, turnover FROM baostock_daily_raw "
            f"WHERE date >= '{START_DATE}' AND date <= '{END_DATE}' "
            f"  AND turnover IS NOT NULL AND turnover != ''",
            conn,
        )
    finally:
        conn.close()
    if len(df) == 0:
        return df
    df["turnover"] = pd.to_numeric(df["turnover"], errors="coerce")
    df = df[df["turnover"].notna() & (df["turnover"] >= 0)]
    print(f"[turnover] loaded {len(df):,} rows, {df['date'].nunique()} dates, "
          f"took {time.time()-t0:.1f}s", flush=True)

    print("[turnover] grouping by date ...", flush=True)
    # 按日聚合：mean/median/p90/p10/gt5占比
    g = df.groupby("date", as_index=False)["turnover"].agg(
        ["mean", "median", "count",
         lambda x: x.quantile(0.90),
         lambda x: x.quantile(0.10),
         lambda x: (x > 5).sum() / len(x) if len(x) > 0 else float("nan")]
    )
    g.columns = ["date", "mean", "median", "count", "p90", "p10", "gt5_pct"]
    g = g.sort_values("date").reset_index(drop=True)
    print(f"[turnover] computed {len(g)} trading days, "
          f"mean range: {g['mean'].min():.3f}-{g['mean'].max():.3f}%, "
          f"median range: {g['median'].min():.3f}-{g['median'].max():.3f}%, "
          f"gt5_pct range: {g['gt5_pct'].min():.3f}-{g['gt5_pct'].max():.3f}", flush=True)
    return g


def upsert_turnover(g: pd.DataFrame) -> dict:
    """回填 daily_metric 5 个换手率分布指标（source='baostock'）。

    upsert ON CONFLICT DO UPDATE ... WHERE source != 'manual'（防覆盖手动补录）。
    NaN 过滤：if v != v: continue。
    """
    if g is None or len(g) == 0:
        return {"written": 0, "error": "no data"}
    conn = get_conn()
    now = _now()
    written = 0

    metric_cols = {
        "a_turnover_mean": g["mean"],
        "a_turnover_median": g["median"],
        "a_turnover_p90": g["p90"],
        "a_turnover_p10": g["p10"],
        "a_turnover_gt5_pct": g["gt5_pct"],
    }

    for mid, series in metric_cols.items():
        rows = []
        for d, v in zip(g["date"].tolist(), series.tolist()):
            if v != v:  # NaN 跳过
                continue
            rows.append((d, mid, float(v), "baostock", now))
        if not rows:
            continue
        cur = conn.executemany(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            rows,
        )
        written += cur.rowcount if cur.rowcount > 0 else len(rows)
        print(f"[turnover] {mid}: {len(rows)} rows upserted", flush=True)

    conn.commit()
    # 统计被 manual 保护未覆盖的行数
    skipped_manual = conn.execute(
        "SELECT COUNT(*) FROM daily_metric WHERE source='manual' "
        f"AND metric_id IN ({','.join('?' for _ in TURNOVER_METRICS)})",
        TURNOVER_METRICS,
    ).fetchone()[0]
    conn.close()
    return {"written": written, "skipped_manual": skipped_manual, "days": len(g)}


# ═════════════════════════════════════════════════════════════════════════════
# 主流程
# ═════════════════════════════════════════════════════════════════════════════
def run_validate() -> dict:
    res = validate_cross_source()
    REPORT_PATH.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== validate done: report → {REPORT_PATH} ===", flush=True)
    print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)
    return res


def run_turnover() -> dict:
    g = compute_turnover_dist()
    if len(g) == 0:
        print("[turnover] no data, abort", flush=True)
        return {"error": "no turnover data"}
    res = upsert_turnover(g)
    print(f"\n=== turnover done: {res} ===", flush=True)
    return res


def _cli(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "all"
    if cmd == "validate":
        run_validate()
    elif cmd == "turnover":
        run_turnover()
    elif cmd == "all":
        run_validate()
        run_turnover()
    else:
        print(f"unknown command: {cmd}")
        print("usage: python -m app.collector.cleanup_d3d2 <validate|turnover|all>")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
