"""北交所宽度独立指标组计算（#101 方案C，2026-09-06）。

背景（docs/analysis/beijiao-exchange-width-universe-20260902.md）:
主宽度 mootdx 全 A 宇宙不含北交所（mootdx 仅 SH/SZ），北交所 920xxx 段长期缺失。
#101 拍板方案C：从 FAPI（同花顺）日线 dump 单独算北交所宽度独立指标组 a_bj_width_*，
**不动现有主宽度**（AD线/恐贪/涨停判定全冻结，§23.7 只增不改）。

指标（6 个，metric_id，前缀 a_bj_）
======================================
- a_bj_width_zt_count    涨停数（北交所 30% 档判定）
- a_bj_width_dt_count    跌停数（30% 档）
- a_bj_width_up_count    上涨家数（pct_change > 0）
- a_bj_width_down_count  下跌家数（pct_change < 0）
- a_bj_width_amount      成交额（sum(amount) / 1e8，亿元）
- a_bj_width_ad_line     AD线（cumsum(up-down)）

口径
====
- 宇宙：fapi_daily_raw 表 code LIKE '920%'（北交所，FAPI 341 只）。
- 涨停档：北交所 30%，禁套主板 10% 档（主板档会漏判 30% 涨停，误判 2-14 只）。
  zt: close >= prev_close × (1+0.30) × 0.999
  dt: close <= prev_close × (1-0.30) × 1.001
- prev_close 由 pct_change 反推（pct_change = (close/prev-1)*100）
  prev_close = close / (1 + pct_change/100)，与 width_history 同模式。
- 除权日检测 + 容差同 width_history（beyond_limit → ex_div 跳过 zt/dt）：
  close > zt_price×1.001 或 close < dt_price×0.999 → 除权日/数据异常，跳过 zt/dt 判定。
- 首行无 pct_change（NULL）→ 跳过该行所有判定。
- 每日最少 code 数阈值：北交所 ~341 只，MIN_BJ_CODES_PER_DAY = 250（区分采集不全）。

数据源
======
- 读表 fapi_daily_raw（data/stock_daily.db，FAPI 来源），source 标记 'fapi'。
- 写入 daily_metric（sentiment.db，走 app.db.get_conn()）。
- FAPI dump 仅近 10 交易日（daily-k-10d），故本模块只支持 run_recent 模式
  （近 N 天然日窗口重算），不支持 2016 全量回填（FAPI 无历史）。

CLI
====
python -m app.collector.bj_width          # run_recent(days=35) 默认
python -m app.collector.bj_width --days=60
python -m app.collector.bj_width --dry-run  # 只算不写
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from app.db import get_conn

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"

# ── 北交所 30% 涨跌停档 ──────────────────────────────────────────────────────
# 北交所 30% 规则（禁套主板 10% 档会误判 2-14 只；实证 920075@20260904 pct_change=30.0）。
BJ_LIMIT = 0.30
ZT_TOL = 0.999   # close >= 涨停价 × 0.999
DT_TOL = 1.001   # close <= 跌停价 × 1.001
EX_DIV_MULT = 1.5  # |pct_change| > 规则% × 1.5 → 除权日（北交所 30%→45%）

# 北交所宇宙 ~341 只（FAPI 920 段实测 341），低于 250 视为采集不全，跳过该日
MIN_BJ_CODES_PER_DAY = 250


# ── 读数据 ────────────────────────────────────────────────────────────────────
def load_bj_daily(start: str, end: str) -> pd.DataFrame:
    """从 fapi_daily_raw 读北交所（920xxx）日线窗口。

    返回 DataFrame: code/date/high/low/close/amount/pct_change。
    仅 920 前缀（北交所），band 段丢弃。
    """
    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=30.0)
    try:
        df = pd.read_sql_query(
            "SELECT code, date, high, low, close, amount, pct_change "
            "FROM fapi_daily_raw "
            "WHERE date >= ? AND date <= ? AND code LIKE '920%' "
            "ORDER BY code, date",
            conn,
            params=(start, end),
        )
    finally:
        conn.close()
    return df.reset_index(drop=True)


# ── 算宽度 ────────────────────────────────────────────────────────────────────
def compute_bj_width(df: pd.DataFrame) -> pd.DataFrame:
    """算每日北交所宽度指标。返回按 date 聚合的 DataFrame。

    输入 df 需含: code/date/high/low/close/amount/pct_change。
    输出列: date/zt/dt/up/down/amount_sum/seal_rate。
    涨停档固定 30%（北交所规则，不套 limit_rule）。
    """
    p = df["pct_change"]
    # prev_close 由 pct_change 反推（与 width_history 同模式）
    # prev_close = close / (1 + pct_change/100)
    prev_close = df["close"] / (1.0 + p / 100.0)
    zt_price = prev_close * (1.0 + BJ_LIMIT)
    dt_price = prev_close * (1.0 - BJ_LIMIT)

    has_pct = p.notna()  # 首行无 pct_change → 跳过
    # 除权日/数据异常检测（close 超出 0.1% 限价外→必为除权日，正常交易不可能破板）
    beyond_limit = (df["close"] > zt_price * 1.001) | (df["close"] < dt_price * 0.999)
    ex_div = (beyond_limit | (p.abs() > BJ_LIMIT * 100.0 * EX_DIV_MULT)) & has_pct

    # 涨停/跌停（30% 档，除权日跳过）
    zt = (df["close"] >= zt_price * ZT_TOL) & has_pct & ~ex_div
    dt = (df["close"] <= dt_price * DT_TOL) & has_pct & ~ex_div
    # 上涨/下跌（含除权日，按 pct_change 符号）
    up = (p > 0) & has_pct
    down = (p < 0) & has_pct

    tmp = df[["date", "amount"]].copy()
    tmp["has_pct"] = has_pct.astype("int32")
    tmp["zt"] = zt.astype("int32")
    tmp["dt"] = dt.astype("int32")
    tmp["up"] = up.astype("int32")
    tmp["down"] = down.astype("int32")

    g = tmp.groupby("date", as_index=False).agg(
        zt=("zt", "sum"),
        dt=("dt", "sum"),
        up=("up", "sum"),
        down=("down", "sum"),
        amount_sum=("amount", "sum"),
        n_codes=("date", "count"),
        n_has_pct=("has_pct", "sum"),  # 该日有 pct_change 的行数
    )
    # pct_change 数据不足的日期（如 FAPI 10d 窗口外首日无 prev_close）：
    # up/down/zt/dt 判定无意义 → 置 NaN 只写 amount，不写误导性 0
    # （2026-09-06 实测 20260819-24 行全 pct=NULL 被算成 0 的问题发现）。
    g.loc[g["n_has_pct"] < MIN_BJ_CODES_PER_DAY, ["zt", "dt", "up", "down"]] = float("nan")

    # 过滤采集不全的日期（code 数 < MIN_BJ_CODES_PER_DAY）
    low_data_dates = g[g["n_codes"] < MIN_BJ_CODES_PER_DAY]["date"].tolist()
    if low_data_dates:
        print(f"[BJ-width] WARN: 跳过 {len(low_data_dates)} 个采集不全日期 "
              f"(北交所code数<{MIN_BJ_CODES_PER_DAY}): {low_data_dates[:5]}...", flush=True)
    g = g[g["n_codes"] >= MIN_BJ_CODES_PER_DAY].copy()
    if len(g) == 0:
        return g
    return g.sort_values("date").reset_index(drop=True)


# ── 写库 ──────────────────────────────────────────────────────────────────────
def _now():
    return dt.datetime.now().isoformat()


def upsert_bj_width(g: pd.DataFrame, *, dry_run: bool = False) -> dict:
    """把算好的北交所宽度写回 sentiment.db daily_metric（source='fapi'）。

    - zt/dt/up/down/amount 写近窗口。
    - AD 线单独由 store_bj_ad_line 算（cumsum 需全序列）。
    - ON CONFLICT DO UPDATE ... WHERE source != 'manual'（防覆盖手动补录）。
    """
    if dry_run:
        return {"written": 0, "skipped_manual": 0, "dry_run": True}

    conn = get_conn()
    now = _now()
    written = 0

    metrics = [
        ("a_bj_width_zt_count", g["zt"]),
        ("a_bj_width_dt_count", g["dt"]),
        ("a_bj_width_up_count", g["up"]),
        ("a_bj_width_down_count", g["down"]),
        ("a_bj_width_amount", g["amount_sum"] / 1.0e8),  # 元 → 亿元
    ]

    def _upsert(metric_id, dates, values):
        nonlocal written
        rows = []
        for d, v in zip(dates, values):
            if v != v:  # NaN 跳过
                continue
            rows.append((d, metric_id, float(v), "fapi", now))
        if not rows:
            return
        cur = conn.executemany(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            rows,
        )
        written += cur.rowcount if cur.rowcount > 0 else len(rows)

    for mid, series in metrics:
        _upsert(mid, g["date"].tolist(), series.tolist())

    conn.commit()
    conn.close()
    return {"written": written, "dry_run": False}


def store_bj_ad_line(*, dry_run: bool = False) -> int:
    """重算北交所 AD 线（cumsum up-down）写 daily_metric。返回写入行数。

    AD 线是累计序列，需从 daily_metric 现有 a_bj_width_up_count/down_count
    全序列 cumsum（不能只算近窗口，否则 AD 线基准漂移）。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT date, metric_id, value FROM daily_metric "
            "WHERE metric_id IN ('a_bj_width_up_count','a_bj_width_down_count') "
            "ORDER BY date"
        ).fetchall()
    except Exception:
        conn.close()
        return 0
    conn.close()
    if not rows:
        return 0
    # pandas 3.0: sqlite3.Row 列表直接 pd.DataFrame(rows) 列名变整数索引(0/1/2), 必然 KeyError;
    # dict(r) 显式转普通 dict 保留列名(上游 fapi_fallback 用 dict 列表不受影响, 此为唯一同类点)。
    df = pd.DataFrame([dict(r) for r in rows])
    up = df[df["metric_id"] == "a_bj_width_up_count"].set_index("date")["value"].astype(float)
    down = df[df["metric_id"] == "a_bj_width_down_count"].set_index("date")["value"].astype(float)
    s = pd.concat([up, down], axis=1).dropna()
    if s.empty:
        return 0
    ad_line = (s.iloc[:, 0] - s.iloc[:, 1]).cumsum()

    if dry_run:
        return len(ad_line)
    now = _now()
    conn = get_conn()
    rows = [(d, "a_bj_width_ad_line", float(v), "fapi", now)
            for d, v in ad_line.items() if v == v]
    n = len(rows)
    if rows:
        conn.executemany(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            rows,
        )
        conn.commit()
    conn.close()
    return n


# ── 主流程 ────────────────────────────────────────────────────────────────────
def run_recent(days: int = 35, *, dry_run: bool = False) -> dict:
    """重算最近 N 天北交所宽度（scheduler 每日调，FAPI 采集后调）。

    窗口：FAPI dump 仅 10 交易日，days 取天然日 35（含 buffer 计算 pct_change。
    load 窗口取 days+10，写窗口取 days）。
    """
    today = dt.date.today()
    # 加载窗口：多读 10 天 buffer 确保首日 prev_close；FAPI 仅近 10 交易日故不超 35 天意义
    load_start = (today - dt.timedelta(days=days + 10)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    write_start = (today - dt.timedelta(days=days)).strftime("%Y%m%d")

    df = load_bj_daily(load_start, end)
    if len(df) == 0:
        return {"error": "no bj data (fapi_daily_raw 920 段为空, 检查 fapi_daily 采集)"}
    print(f"[BJ-width] loaded {len(df):,} rows, {df['code'].nunique()} bj codes, "
          f"{df['date'].nunique()} dates ({df['date'].min()}~{df['date'].max()})", flush=True)

    g = compute_bj_width(df)
    g = g[g["date"] >= write_start].copy()
    if len(g) == 0:
        return {"error": "no bj data in write window"}
    print(f"[BJ-width] {len(g)} trading days ({g['date'].min()}~{g['date'].max()}), "
          f"zt total={g['zt'].sum()}, dt total={g['dt'].sum()}, "
          f"up total={g['up'].sum()}, down total={g['down'].sum()}", flush=True)

    res = upsert_bj_width(g, dry_run=dry_run)
    n_ad = store_bj_ad_line(dry_run=dry_run)
    print(f"[BJ-width] wrote: {res}, ad_line rows={n_ad}", flush=True)
    return {"computed_days": len(g), "date_range": (g["date"].min(), g["date"].max()),
            "write": res, "ad_line_rows": n_ad}


def _cli(argv: list[str]) -> int:
    days = 35
    dry = "--dry-run" in argv
    for a in argv:
        if a.startswith("--days="):
            days = int(a.split("=", 1)[1])
    res = run_recent(days=days, dry_run=dry)
    print(f"\n=== BJ-width done: {res} ===")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))