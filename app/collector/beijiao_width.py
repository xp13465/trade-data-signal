"""北交所宽度指标计算（方案C：独立指标组 a_bj_*，零改动现有宽度）。

从 `data/stock_daily.db` 的 `fapi_daily_raw` 表（920xxx.BJ，FAPI 源）算北交所
自己的宽度指标，写 `data/sentiment.db` 的 `daily_metric` 表（独立 metric_id，
与现有 a_width_* 平行新增，不动任何现有指标/恐贪/AD线）。

指标（5 个，metric_id）
========================
- a_bj_up_count    北交所上涨家数（pct_change > 0）
- a_bj_down_count  北交所下跌家数（pct_change < 0）
- a_bj_zt_count    北交所涨停数（30% 档，close >= 涨停价 × 0.999）
- a_bj_dt_count    北交所跌停数（30% 档，close <= 跌停价 × 1.001）
- a_bj_amount      北交所成交额（sum(amount) / 1e8，亿元）

口径（与 width_history.py 对齐，仅涨跌幅档位不同）
==================================================
- 北交所涨跌幅规则 = 30%（920xxx，复用 width_history.limit_rule() 单一事实源）
- 涨停价 = prev_close × (1+规则)；跌停价 = prev_close × (1-规则)
- 浮点容差：涨停 close >= 涨停价 × 0.999；跌停 close <= 跌停价 × 1.001
- 除权日处理：close 超出限价 1.001 或 pct_change 超规则 1.5 倍 → 跳过涨停/跌停判定
- 上涨/下跌家数仍按 pct_change 符号（pct_change>0 上涨）
- 首行无 pct_change（NULL）→ 跳过该行所有判定
- 最小 code 数阈值：MIN_BJ_CODES=300（北交所约 339 只，低于此值视为采集不全跳过）

数据源与历史
============
- fapi_daily_raw 为 FAPI 源全市场日线（含北交所 339 只），数据起点 20260819。
- 北交所历史从 FAPI 已有数据起画（10 日实测+后续累积），不假装完整历史（诚实标注）。
- FAPI 采集由 com.trade.fapi-daily launchd 18:10 每日执行（2026-09-02 已核实挂载）。
- 北交所宽度计算由 com.trade.beijiao-width launchd 18:15 每日执行（FAPI 之后）。

CLI
====
python -m app.collector.beijiao_width --recent            # 增量重算近 30 天（scheduler 每日调）
python -m app.collector.beijiao_width --recent --days=60  # 自定义天数
python -m app.collector.beijiao_width --dry-run           # 只算不写
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from app.db import get_conn
from .width_history import limit_rule, ZT_TOL, DT_TOL, EX_DIV_MULT

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"
# sentiment.db 连接统一走 app.db.get_conn()

# 北交所最小 code 数阈值：正常约 339 只；低于 300 视为采集不全（FAPI 停服/半拉）跳过
MIN_BJ_CODES = 300

# 指标（5 个，metric_id）
BJ_METRIC_IDS = [
    "a_bj_up_count",
    "a_bj_down_count",
    "a_bj_zt_count",
    "a_bj_dt_count",
    "a_bj_amount",
]


def load_bj_daily(start: str, end: str) -> pd.DataFrame:
    """从 fapi_daily_raw 读北交所（920 前缀）日线。

    返回 DataFrame: code/date/high/low/close/amount/pct_change/rule。
    pct_change 为 FAPI 入库时自算（与 mootdx 同口径），跨除权日失真（与主宽度一致）。
    """
    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=30.0)
    try:
        df = pd.read_sql_query(
            "SELECT code, date, high, low, close, amount, pct_change "
            "FROM fapi_daily_raw "
            "WHERE code LIKE '920%' AND date >= ? AND date <= ? "
            "ORDER BY code, date",
            conn,
            params=(start, end),
        )
    finally:
        conn.close()
    if len(df) == 0:
        return df
    # 涨跌幅规则（920 → 0.30，复用 width_history.limit_rule 单一事实源）
    df["rule"] = df["code"].map(limit_rule)
    return df.reset_index(drop=True)


def compute_bj_width(df: pd.DataFrame) -> pd.DataFrame:
    """算北交所每日宽度。输入需含 code/date/high/low/close/amount/pct_change/rule。

    逻辑与 width_history.compute_width 同构（prev_close 反推 / 除权日 / 浮点容差），
    仅最小 code 数阈值不同（北交所 339 vs 全 A 5000+）。输出列：
    date/zt/dt/up/down/amount_sum/n_codes。
    """
    p = df["pct_change"]
    prev_close = df["close"] / (1.0 + p / 100.0)
    rule = df["rule"]
    zt_price = prev_close * (1.0 + rule)
    dt_price = prev_close * (1.0 - rule)

    has_pct = p.notna()
    beyond_limit = (df["close"] > zt_price * 1.001) | (df["close"] < dt_price * 0.999)
    ex_div = (beyond_limit | (p.abs() > rule * 100.0 * EX_DIV_MULT)) & has_pct

    zt = (df["close"] >= zt_price * ZT_TOL) & has_pct & ~ex_div
    dt = (df["close"] <= dt_price * DT_TOL) & has_pct & ~ex_div
    up = (p > 0) & has_pct
    down = (p < 0) & has_pct

    tmp = df[["date", "amount"]].copy()
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
    )
    # 过滤采集不全的日期（北交所 code 数 < 300，如 FAPI 停服只采到几十只）
    low_data_dates = g[g["n_codes"] < MIN_BJ_CODES]["date"].tolist()
    if low_data_dates:
        print(f"[bj-width] WARN: 跳过 {len(low_data_dates)} 个采集不全日期 "
              f"(code数<{MIN_BJ_CODES}): {low_data_dates[:5]}...", flush=True)
    g = g[g["n_codes"] >= MIN_BJ_CODES].copy()
    if len(g) == 0:
        return g
    return g.sort_values("date").reset_index(drop=True)


def _now():
    return dt.datetime.now().isoformat()


def upsert_bj_width(g: pd.DataFrame, *, dry_run: bool = False) -> dict:
    """把北交所宽度写回 daily_metric（source='fapi'，防手动补录覆盖）。"""
    if dry_run:
        return {"written": 0, "dry_run": True}

    conn = get_conn()
    now = _now()
    written = 0
    metric_rows = [
        ("a_bj_up_count", g["up"]),
        ("a_bj_down_count", g["down"]),
        ("a_bj_zt_count", g["zt"]),
        ("a_bj_dt_count", g["dt"]),
        ("a_bj_amount", g["amount_sum"] / 1.0e8),  # 元 → 亿元（与 a_amount 同口径）
    ]

    rows = []
    for mid, series in metric_rows:
        for d, v in zip(g["date"].tolist(), series.tolist()):
            if v != v:  # NaN 跳过
                continue
            rows.append((d, mid, float(v), "fapi", now))
    if rows:
        cur = conn.executemany(
            "INSERT INTO daily_metric (date, metric_id, value, source, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(date, metric_id) DO UPDATE SET "
            "value=excluded.value, source=excluded.source, updated_at=excluded.updated_at "
            "WHERE daily_metric.source != 'manual'",
            rows,
        )
        written += cur.rowcount if cur.rowcount > 0 else len(rows)
    conn.commit()
    conn.close()
    return {"written": written, "dry_run": False}


def run_recent(days: int = 30, *, dry_run: bool = False) -> dict:
    """增量重算最近 N 天北交所宽度（scheduler/launchd 每日调）。

    FAPI 每日 18:10 采集当天北交所日线，本函数 18:15 重算近 N 天覆盖漏跑日。
    写窗口 = 近 days 天；load 多 50 天确保首日 prev_close。
    """
    today = dt.date.today()
    load_start = (today - dt.timedelta(days=days + 50)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    write_start = (today - dt.timedelta(days=days)).strftime("%Y%m%d")

    df = load_bj_daily(load_start, end)
    if len(df) == 0:
        return {"error": "no recent bj data"}
    g = compute_bj_width(df)
    g = g[g["date"] >= write_start].copy()
    if len(g) == 0:
        return {"error": "no bj data in write window"}
    print(f"[bj-width-recent] {len(g)} trading days ({g['date'].min()}~{g['date'].max()}), "
          f"zt={g['zt'].sum()}, dt={g['dt'].sum()}, up={g['up'].sum()}, "
          f"down={g['down'].sum()}, amount_yi={(g['amount_sum']/1e8).max():.1f}", flush=True)

    res = upsert_bj_width(g, dry_run=dry_run)
    print(f"[bj-width-recent] wrote: {res}", flush=True)
    return {"computed_days": len(g), "date_range": (g["date"].min(), g["date"].max()),
            "write": res}


def run(*, dry_run: bool = False) -> dict:
    """全量回填北交所宽度（FAPI 数据起点起）。"""
    end = dt.date.today().strftime("%Y%m%d")
    df = load_bj_daily("20260819", end)  # FAPI 北交所数据起点（10 日实测）
    if len(df) == 0:
        return {"error": "no bj data"}
    print(f"[bj-width] loaded {len(df):,} rows, {df['code'].nunique()} codes, "
          f"{df['date'].nunique()} dates", flush=True)
    g = compute_bj_width(df)
    print(f"[bj-width] computed {len(g)} trading days", flush=True)
    res = upsert_bj_width(g, dry_run=dry_run)
    print(f"[bj-width] wrote: {res}", flush=True)
    return {"computed_days": len(g), "write": res}


def _cli(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    recent = "--recent" in argv
    if recent:
        days = 30
        for a in argv:
            if a.startswith("--days="):
                days = int(a.split("=", 1)[1])
        res = run_recent(days=days, dry_run=dry)
        print(f"\n=== bj-width recent done: {res} ===")
        return 0
    res = run(dry_run=dry)
    print(f"\n=== bj-width done: {res} ===")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
