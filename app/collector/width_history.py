"""TASK-D2: 历史宽度指标计算与回填（10 年）。

从 `data/stock_daily.db` 的 `mootdx_daily_raw` 表算历史宽度，回填
`data/sentiment.db` 的 `daily_metric` 表（2016-2026，按日期聚合全市场）。

替代现有靠 `stock_zh_a_spot`（无历史）+ `stock_zt_pool_em`（仅近 2 周）的口径。

指标（7 个，metric_id）
========================
- a_width_zt_count    涨停数（close >= 涨停价 × 0.999）
- a_width_dt_count    跌停数（close <= 跌停价 × 1.001）
- a_width_zb_count    炸板数（high >= 涨停价 且 close < 涨停价）
- a_width_seal_rate   封板率 = zt / (zt + zb)
- a_width_up_count    上涨家数（pct_change > 0）
- a_width_down_count  下跌家数（pct_change < 0）
- a_amount            成交额（sum(amount) / 1e8，亿元）

口径（详见 REQUIREMENTS.md §宽度指标口径）
========================================
- 涨跌幅规则：主板(000/001/002/003/600/601/603/605) 10% /
  创业板(300/301) 科创板(688/689) 20%。mootdx 不覆盖北交所(430/830/920)，
  故无 30% 档；不含 B 股(200)。
- ST 5%：mootdx 无 ST 标记，不单独处理（误差说明写 REQUIREMENTS.md）。
- 前收：用 mootdx 预算的 pct_change 反推 prev_close = close / (1 + pct_change/100)。
  pct_change 为该 code 上一交易日 close 算得（D1 入库时自算，跨除权日失真）。
- 涨停价 = prev_close × (1+规则)；跌停价 = prev_close × (1-规则)。
- 浮点容差：涨停 close >= 涨停价 × 0.999；跌停 close <= 跌停价 × 1.001。
- 除权日处理：若 |pct_change| > 规则 × 100 × 1.5（主板 >15%、创业板 >30%），
  标记为除权日，**跳过该日该股涨停/炸板/跌停判定**（避免误判）；
  上涨/下跌家数仍按 pct_change 符号（pct_change>0 上涨，含除权日，已知偏差）。
- 首行无 pct_change（NULL）→ 跳过该行所有判定。

A1 近端值保护
=============
- a_width_up_count / a_width_down_count / a_amount 在 20260703/20260706 有
  A1 修复的近端值（source='akshare'，全市场含北交所，更准）。
- 本模块**只回填 20160101-20260702** 这三个指标，不动 20260703+（A1 保留）。
- a_width_zt_count / a_width_dt_count 在 20260612-20260706 有 stock_zt_pool_em
  近 2 周值；本模块回填 20160101-20260706 全段（含覆盖近 2 周，用 close 口径替代
  封板口径）。覆盖前先做交叉校验。
- upsert ON CONFLICT DO UPDATE ... WHERE source != 'manual'（防覆盖手动补录）。

换手率分布（a_turnover_*）跳过
================================
mootdx turnover 全 NULL，等 D3 BaoStock 补。本模块不写换手率。

CLI
====
python -m app.collector.width_history                # 全量回填 2016-2026
python -m app.collector.width_history --validate    # 仅校验（对比 stock_zt_pool_em）
python -m app.collector.width_history --dry-run     # 只算不写
python -m app.collector.width_history --recent      # 增量重算近 30 天（scheduler 每日调）
python -m app.collector.width_history --recent --days=60  # 自定义天数

漏跑工作日回填（run_recent）
============================
scheduler 每日跑 step 9 调 `run_recent(days=30)`：从 mootdx_daily_raw 重算近 30 天
全市场宽度（zt/dt/zb/seal_rate/up/down/amount），覆盖漏跑工作日。用户漏跑几天
（如周一忘周二跑），下次 scheduler 执行时本函数自动重算近 30 天补全。

- run_recent 从 mootdx_daily_raw 算（不依赖 collect_snapshot 当日快照）。
- zt/dt/zb/seal_rate：全段覆盖（mootdx 收盘封板口径替代 zt_pool 触板口径，与 run() 一致）。
- up/down/amount：动态 A1 保护——跳过已有 source='akshare' 的日期（A1 全市场口径含
  北交所更准），只写无 akshare 值的漏跑日。比 run() 的固定 A1_PROTECT_AFTER 掩码更灵活：
  能为漏跑的未来日期补 mootdx 值，又不覆盖已采的 akshare 近端值。
- 所有 upsert WHERE source != 'manual'（防覆盖手动补录）。
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from app.db import get_conn

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"
# sentiment.db 连接统一走 app.db.get_conn()（含 _migrate 补 net_inflow 列），勿直连

START_DATE = "20160101"
END_DATE = "20260706"
# up/down/amount 回填上限（不含 20260703+，A1 保留）
A1_PROTECT_AFTER = "20260702"

# 容差
ZT_TOL = 0.999   # close >= 涨停价 × 0.999
DT_TOL = 1.001   # close <= 跌停价 × 1.001
EX_DIV_MULT = 1.5  # |pct_change| > 规则% × 1.5 → 除权日


# ── 涨跌幅规则 ────────────────────────────────────────────────────────────────
def limit_rule(code: str) -> float:
    """按代码前缀返回涨跌幅规则（小数）。mootdx 仅 SH/SZ，无北交所/B股。

    300/301(创业板) 688/689(科创板) → 0.20；其余（主板）→ 0.10。
    ST 5% 无法判定（mootdx 无 ST 标记），不单独处理。
    """
    if code[:3] in ("300", "301", "688", "689"):
        return 0.20
    return 0.10


# ── 读数据 ────────────────────────────────────────────────────────────────────
def load_daily(start: str = START_DATE, end: str = END_DATE) -> pd.DataFrame:
    """从 mootdx_daily_raw 读 2016+ 日线（含 2015-12 一个月用于 prev_close 校验）。

    返回 DataFrame: code/date/open/high/low/close/amount/pct_change/rule。
    pct_change 为 D1 入库时自算（(close/prev_close-1)*100），跨除权日失真。
    """
    # 多读一个月，确保 2016-01-04 的 prev_close 来自 2015-12-31（虽然 pct_change
    # 已含，但多读无妨，过滤时丢弃 < START_DATE）。
    load_start = "20151201"
    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=30.0)
    try:
        df = pd.read_sql_query(
            "SELECT code, date, high, low, close, amount, pct_change "
            "FROM mootdx_daily_raw "
            f"WHERE date >= '{load_start}' AND date <= '{end}' "
            "ORDER BY code, date",
            conn,
        )
    finally:
        conn.close()
    if len(df) == 0:
        return df
    # 涨跌幅规则（按 code 前缀）
    df["rule"] = df["code"].map(limit_rule)
    # 只保留 >= START_DATE 用于聚合（2015-12 仅辅助，丢弃）
    df = df[df["date"] >= start].copy()
    return df.reset_index(drop=True)


# ── 算宽度 ────────────────────────────────────────────────────────────────────
def compute_width(df: pd.DataFrame) -> pd.DataFrame:
    """算每日宽度指标。返回按 date 聚合的 DataFrame。

    输入 df 需含: code/date/high/low/close/amount/pct_change/rule。
    输出列: date/zt/dt/zb/up/down/amount_sum/seal_rate。
    """
    p = df["pct_change"]
    # prev_close 由 pct_change 反推（pct_change = (close/prev-1)*100）
    # prev_close = close / (1 + pct_change/100)
    prev_close = df["close"] / (1.0 + p / 100.0)
    rule = df["rule"]
    zt_price = prev_close * (1.0 + rule)
    dt_price = prev_close * (1.0 - rule)

    has_pct = p.notna()  # 首行无 pct_change → 跳过
    # 除权日检测（close-beyond-limit，比 pct_change 1.5x 阈值更精确）：
    # 正常交易 close ∈ [dt_price, zt_price]；若 close 超出限价 0.1% 以外
    # （close > zt_price×1.001 或 close < dt_price×0.999），必为除权日/数据异常
    # （正常交易不可能突破涨跌停板）。跳过该日该股 zt/dt/zb 判定。
    # 同时保留 pct_change 1.5x 阈值作辅助（捕捉 close 恰好卡限价但 pct 异常大的情况）。
    beyond_limit = (df["close"] > zt_price * 1.001) | (df["close"] < dt_price * 0.999)
    ex_div = (beyond_limit | (p.abs() > rule * 100.0 * EX_DIV_MULT)) & has_pct

    # 涨停/跌停/炸板（除权日跳过）
    zt = (df["close"] >= zt_price * ZT_TOL) & has_pct & ~ex_div
    dt = (df["close"] <= dt_price * DT_TOL) & has_pct & ~ex_div
    zb = (df["high"] >= zt_price * ZT_TOL) & (df["close"] < zt_price * ZT_TOL) & has_pct & ~ex_div
    # 上涨/下跌（含除权日，按 pct_change 符号）
    up = (p > 0) & has_pct
    down = (p < 0) & has_pct

    tmp = df[["date", "amount"]].copy()
    tmp["zt"] = zt.astype("int32")
    tmp["dt"] = dt.astype("int32")
    tmp["zb"] = zb.astype("int32")
    tmp["up"] = up.astype("int32")
    tmp["down"] = down.astype("int32")

    g = tmp.groupby("date", as_index=False).agg(
        zt=("zt", "sum"),
        dt=("dt", "sum"),
        zb=("zb", "sum"),
        up=("up", "sum"),
        down=("down", "sum"),
        amount_sum=("amount", "sum"),
    )
    # 封板率 = zt / (zt + zb)
    denom = g["zt"] + g["zb"]
    g["seal_rate"] = g["zt"].where(denom > 0, 0) / denom.where(denom > 0, 1)
    g.loc[denom == 0, "seal_rate"] = float("nan")  # 无涨停无炸板 → NaN
    return g.sort_values("date").reset_index(drop=True)


# ── 写库 ──────────────────────────────────────────────────────────────────────
def _now():
    return dt.datetime.now().isoformat()


def upsert_width(g: pd.DataFrame, *, dry_run: bool = False) -> dict:
    """把算好的宽度写回 sentiment.db daily_metric。

    - zt/dt/zb/seal_rate: 写 20160101-20260706 全段（覆盖 stock_zt_pool_em 近 2 周）。
    - up/down/amount: 只写 <= 20260702（A1 保留 20260703+）。
    - ON CONFLICT DO UPDATE ... WHERE source != 'manual'（防覆盖手动补录）。
    """
    if dry_run:
        return {"written": 0, "skipped_manual": 0, "dry_run": True}

    conn = get_conn()
    now = _now()
    written = 0
    skipped_manual = 0

    # 全段指标：zt/dt/zb/seal_rate
    full_metrics = [
        ("a_width_zt_count", g["zt"]),
        ("a_width_dt_count", g["dt"]),
        ("a_width_zb_count", g["zb"]),
        ("a_width_seal_rate", g["seal_rate"]),
    ]
    # A1 保护指标：up/down/amount（只写 <= A1_PROTECT_AFTER）
    a1_mask = g["date"] <= A1_PROTECT_AFTER
    a1_metrics = [
        ("a_width_up_count", g.loc[a1_mask, "up"]),
        ("a_width_down_count", g.loc[a1_mask, "down"]),
        ("a_amount", g.loc[a1_mask, "amount_sum"] / 1.0e8),  # 元 → 亿元
    ]

    def _upsert(metric_id, dates, values):
        nonlocal written, skipped_manual
        rows = []
        for d, v in zip(dates, values):
            if v != v:  # NaN 跳过
                continue
            rows.append((d, metric_id, float(v), "mootdx", now))
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

    for mid, series in full_metrics:
        _upsert(mid, g["date"].tolist(), series.tolist())
    for mid, series in a1_metrics:
        _upsert(mid, g.loc[a1_mask, "date"].tolist(), series.tolist())

    conn.commit()
    # 统计被 manual 保护未覆盖的行数
    skipped_manual = conn.execute(
        "SELECT COUNT(*) FROM daily_metric WHERE source='manual' "
        "AND metric_id IN ('a_width_zt_count','a_width_dt_count','a_width_zb_count',"
        "'a_width_seal_rate','a_width_up_count','a_width_down_count','a_amount')"
    ).fetchone()[0]
    conn.close()
    return {"written": written, "skipped_manual": skipped_manual, "dry_run": False}


# ── 校验 ──────────────────────────────────────────────────────────────────────
def validate(g: pd.DataFrame) -> dict:
    """与 stock_zt_pool_em 近 2 周（daily_metric 现有值）交叉校验。

    daily_metric 现有 a_width_zt_count/dt_count 来自 stock_zt_pool_em（封板口径），
    本模块算的是 close 口径。对比重叠日期的误差。
    """
    conn = get_conn()
    try:
        existing = pd.read_sql_query(
            "SELECT date, metric_id, value FROM daily_metric "
            "WHERE metric_id IN ('a_width_zt_count','a_width_dt_count') "
            "AND source='akshare'",
            conn,
        )
    finally:
        conn.close()
    if len(existing) == 0:
        return {"compared": 0, "note": "no stock_zt_pool_em historical data"}

    zt_ref = existing[existing["metric_id"] == "a_width_zt_count"][["date", "value"]].rename(
        columns={"value": "zt_ref"})
    dt_ref = existing[existing["metric_id"] == "a_width_dt_count"][["date", "value"]].rename(
        columns={"value": "dt_ref"})
    merged = g[["date", "zt", "dt"]].merge(zt_ref, on="date", how="inner").merge(dt_ref, on="date", how="inner")
    if len(merged) == 0:
        return {"compared": 0, "note": "no overlapping dates"}

    merged["zt_err_pct"] = (merged["zt"] - merged["zt_ref"]).abs() / merged["zt_ref"].replace(0, 1) * 100
    merged["dt_err_pct"] = (merged["dt"] - merged["dt_ref"]).abs() / merged["dt_ref"].replace(0, 1) * 100
    return {
        "compared": len(merged),
        "zt_mean_err_pct": round(merged["zt_err_pct"].mean(), 2),
        "zt_max_err_pct": round(merged["zt_err_pct"].max(), 2),
        "dt_mean_err_pct": round(merged["dt_err_pct"].mean(), 2),
        "dt_max_err_pct": round(merged["dt_err_pct"].max(), 2),
        "details": merged[["date", "zt", "zt_ref", "zt_err_pct", "dt", "dt_ref", "dt_err_pct"]].to_dict("records"),
    }


def try_fetch_zt_pool_recent() -> dict:
    """尝试用 akshare stock_zt_pool_em 取近几日做额外校验（东财 push2ex 可能封锁）。

    trust_env=False 全局已由 base.py patch。封锁则记遗留。
    """
    try:
        from .base import safe_call  # noqa
        import akshare as ak
        results = {}
        # 试最近几个交易日
        for d in ("20260706", "20260703", "20260702"):
            try:
                df = ak.stock_zt_pool_em(date=d)
                if df is not None and len(df) >= 0:
                    results[d] = int(len(df))
            except Exception as e:
                results[d] = f"err: {type(e).__name__}: {str(e)[:80]}"
        return results
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


# ── 主流程 ────────────────────────────────────────────────────────────────────
def run(*, dry_run: bool = False, validate_only: bool = False) -> dict:
    print(f"[D2] loading mootdx_daily_raw {START_DATE}..{END_DATE} ...", flush=True)
    df = load_daily()
    print(f"[D2] loaded {len(df):,} rows, {df['code'].nunique()} codes, "
          f"{df['date'].nunique()} dates", flush=True)
    if len(df) == 0:
        return {"error": "no data"}

    print("[D2] computing width ...", flush=True)
    g = compute_width(df)
    print(f"[D2] computed {len(g)} trading days, "
          f"zt total={g['zt'].sum()}, dt total={g['dt'].sum()}, "
          f"zb total={g['zb'].sum()}", flush=True)
    print(f"[D2] up range: {g['up'].min()}-{g['up'].max()}, "
          f"down range: {g['down'].min()}-{g['down'].max()}, "
          f"amount_yi range: {(g['amount_sum']/1e8).min():.0f}-{(g['amount_sum']/1e8).max():.0f}", flush=True)

    # 校验（写库前，用现有 stock_zt_pool_em 值对比）
    print("[D2] validating vs stock_zt_pool_em (existing 16d) ...", flush=True)
    val = validate(g)
    print(f"[D2] validate: compared={val.get('compared',0)}, "
          f"zt mean err={val.get('zt_mean_err_pct','n/a')}%, "
          f"dt mean err={val.get('dt_mean_err_pct','n/a')}%", flush=True)

    # 试取近几日 stock_zt_pool_em 做额外校验
    print("[D2] trying akshare stock_zt_pool_em for recent days ...", flush=True)
    recent = try_fetch_zt_pool_recent()
    print(f"[D2] recent zt_pool: {recent}", flush=True)

    if validate_only:
        return {"computed_days": len(g), "validate": val, "recent_zt_pool": recent}

    # 写库
    print(f"[D2] writing to daily_metric (dry_run={dry_run}) ...", flush=True)
    res = upsert_width(g, dry_run=dry_run)
    print(f"[D2] wrote: {res}", flush=True)
    return {"computed_days": len(g), "validate": val, "recent_zt_pool": recent, "write": res}


def _upsert_width_recent(g: pd.DataFrame, *, dry_run: bool = False) -> dict:
    """run_recent 专用 upsert：动态 A1 保护（跳过已有 akshare 值的 up/down/amount 日期）。

    与 upsert_width 的区别：
    - upsert_width 用固定 A1_PROTECT_AFTER=20260702 掩码（一次性回填时的快照边界）。
    - 本函数动态查 DB 已有 source='akshare' 的日期，跳过它们——能为漏跑的未来日期
      补 mootdx 值，又不覆盖已采的 akshare 近端值。
    - zt/dt/zb/seal_rate 仍全段覆盖（mootdx 收盘封板替代 zt_pool 触板口径，与 run() 一致）。
    """
    if dry_run:
        return {"written": 0, "dry_run": True}

    conn = get_conn()
    now = _now()
    written = 0

    # 查已有 akshare 值的日期（up/down/amount 保护用）
    dates_in_window = g["date"].tolist()
    placeholders = ",".join("?" * len(dates_in_window))
    akshare_dates: set[str] = set()
    for mid in ("a_width_up_count", "a_width_down_count", "a_amount"):
        rows = conn.execute(
            f"SELECT DISTINCT date FROM daily_metric "
            f"WHERE metric_id=? AND source='akshare' AND date IN ({placeholders})",
            [mid] + dates_in_window,
        ).fetchall()
        akshare_dates.update(r[0] for r in rows)

    # 全段指标：zt/dt/zb/seal_rate（覆盖 akshare zt_pool，与 run() 一致）
    full_metrics = [
        ("a_width_zt_count", g["zt"]),
        ("a_width_dt_count", g["dt"]),
        ("a_width_zb_count", g["zb"]),
        ("a_width_seal_rate", g["seal_rate"]),
    ]
    # A1 保护指标：up/down/amount（跳过已有 akshare 值的日期）
    a1_mask = ~g["date"].isin(akshare_dates)
    a1_metrics = [
        ("a_width_up_count", g.loc[a1_mask, "up"]),
        ("a_width_down_count", g.loc[a1_mask, "down"]),
        ("a_amount", g.loc[a1_mask, "amount_sum"] / 1.0e8),  # 元 → 亿元
    ]

    def _upsert(metric_id, dates, values):
        nonlocal written
        rows = []
        for d, v in zip(dates, values):
            if v != v:  # NaN 跳过
                continue
            rows.append((d, metric_id, float(v), "mootdx", now))
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

    for mid, series in full_metrics:
        _upsert(mid, g["date"].tolist(), series.tolist())
    for mid, series in a1_metrics:
        _upsert(mid, g.loc[a1_mask, "date"].tolist(), series.tolist())

    conn.commit()
    conn.close()
    return {"written": written, "protected_akshare_dates": len(akshare_dates), "dry_run": False}


def run_recent(days: int = 30, *, dry_run: bool = False) -> dict:
    """增量重算最近 N 天全市场宽度（scheduler 每日跑，mootdx 增量后调）。

    只加载近 days+20 自然日的 mootdx 数据（多 20 天确保 prev_close），算宽度后 upsert。
    比 run() 全量快（~2s vs ~30s）。

    漏跑工作日回填：用户漏跑几天（如周一忘周二跑），下次 scheduler 执行时本函数
    重算近 days 天从 mootdx_daily_raw 算 zt/dt/zb/up/down/amount 覆盖漏跑日。
    """
    today = dt.date.today()
    # 加载窗口：多读 50 天确保首日 prev_close（pct_change 自算需前一日 close）
    load_start = (today - dt.timedelta(days=days + 50)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    # 写入窗口起始（buffer 段仅辅助 prev_close，不写）
    write_start = (today - dt.timedelta(days=days)).strftime("%Y%m%d")

    conn = sqlite3.connect(f"file:{STOCK_DB_PATH}?mode=ro", uri=True, timeout=30.0)
    try:
        df = pd.read_sql_query(
            "SELECT code, date, high, low, close, amount, pct_change "
            "FROM mootdx_daily_raw "
            f"WHERE date >= '{load_start}' AND date <= '{end}' "
            "ORDER BY code, date",
            conn,
        )
    finally:
        conn.close()
    if len(df) == 0:
        return {"error": "no recent data"}
    df["rule"] = df["code"].map(limit_rule)
    # 只保留 >= load_start 用于聚合（buffer 段丢弃）
    df = df[df["date"] >= load_start].copy()

    g = compute_width(df)
    g = g[g["date"] >= write_start].copy()
    if len(g) == 0:
        return {"error": "no data in write window"}
    print(f"[D2-recent] {len(g)} trading days ({g['date'].min()}~{g['date'].max()}), "
          f"zt total={g['zt'].sum()}, dt total={g['dt'].sum()}, "
          f"zb total={g['zb'].sum()}, up total={g['up'].sum()}", flush=True)

    res = _upsert_width_recent(g, dry_run=dry_run)
    print(f"[D2-recent] wrote: {res}", flush=True)
    return {"computed_days": len(g), "date_range": (g["date"].min(), g["date"].max()),
            "write": res}


def _cli(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    vonly = "--validate" in argv
    recent = "--recent" in argv
    if recent:
        days = 30
        for a in argv:
            if a.startswith("--days="):
                days = int(a.split("=", 1)[1])
        res = run_recent(days=days, dry_run=dry)
        print(f"\n=== D2 recent done: {res} ===")
        return 0
    res = run(dry_run=dry, validate_only=vonly)
    print(f"\n=== D2 done: {res} ===")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
