"""TASK-F3: 行业内宽度（每个申万一级 31 行业内部涨跌/涨停/炸板/封板率）。

用 D1 mootdx_daily_raw 全 A 股日线 + 申万一级成分股映射，按 industry_code 分组
算每日行业内宽度，回填 `data/sentiment.db` 的 `industry_width_daily` 表
（2016-2026，~31 行业 × 2550 日 ≈ 79000 行）。

口径复用 D2 width_history.py §8.5（前缀涨跌幅规则 / close-beyond-limit 除权日检测 /
容差 0.999/1.001 / 前收由 pct_change 反推）。

成分股映射源
============
申万一级指数代码（801010~801980）的成分股。akshare `index_component_sw` 仅返
"releasedetail" 指数（如申万50 801001）成分，不含 31 个一级行业指数。改用
legulegu `stockdata/index-composition?industryCode=801xxx.SI`（走 HTTPS，trust_env=False
全局已由 base.py patch），返当前成分股列表（含 .SZ/.SH 后缀，strip 取 6 位）。

⚠ 已知限制：legulegu 返**当前**成分股，非历史。申万 2021 修订为最近一次大改，
2016-2021 段用当前成分算宽度存在偏差（已退市股不在当前列表 → 漏算；行业变更股
按当前行业归属）。整体趋势仍可用，单日绝对值有 ~5-10% 偏差。详细见 NOTES.md。

指标（7 个，与 D2 §8.5 同口径）
================================
- up_count    上涨家数（pct_change > 0）
- down_count  下跌家数（pct_change < 0）
- zt_count    涨停数（close >= 涨停价 × 0.999）
- dt_count    跌停数（close <= 跌停价 × 1.001）
- zb_count    炸板数（high >= 涨停价 且 close < 涨停价）
- seal_rate   封板率 = zt / (zt + zb)
- amount      成交额（sum(amount) / 1e8，亿元）

CLI
====
python -m app.collector.industry_width                # 全量回填 2016-2026
python -m app.collector.industry_width --fetch-only   # 仅拉成分股映射
python -m app.collector.industry_width --dry-run      # 只算不写
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"
# sentiment.db 连接统一走 app.db.get_conn()（含 _migrate 补 net_inflow 列），勿直连
COMPONENTS_PATH = _DATA_DIR / "sw_components.json"

START_DATE = "20160101"
END_DATE = "20260706"

# 容差（与 D2 width_history.py 一致）
ZT_TOL = 0.999   # close >= 涨停价 × 0.999
DT_TOL = 1.001   # close <= 跌停价 × 1.001
EX_DIV_MULT = 1.5  # |pct_change| > 规则% × 1.5 → 除权日（辅助）

# 申万一级 31 行业指数代码（与 config/indicators.yaml market=industry 同步）
SW_FIRST_LEVEL_CODES = [
    "801010", "801030", "801040", "801050", "801080", "801880",
    "801110", "801120", "801130", "801140", "801150", "801160",
    "801170", "801180", "801200", "801210", "801780", "801790",
    "801230", "801710", "801720", "801730", "801890", "801740",
    "801750", "801760", "801770", "801950", "801960", "801970",
    "801980",
]


# ── 涨跌幅规则（与 D2 width_history.py 一致）─────────────────────────────────
def limit_rule(code: str) -> float:
    """按代码前缀返回涨跌幅规则（小数）。mootdx 仅 SH/SZ，无北交所/B股。

    300/301(创业板) 688/689(科创板) → 0.20；其余（主板）→ 0.10。
    ST 5% 无法判定（mootdx 无 ST 标记），不单独处理。
    """
    if code[:3] in ("300", "301", "688", "689"):
        return 0.20
    return 0.10


# ── 成分股映射 ────────────────────────────────────────────────────────────────
def fetch_components(force: bool = False) -> dict[str, list[str]]:
    """拉 31 个申万一级行业的成分股列表，存 data/sw_components.json。

    返回 {industry_code: [code, ...]}（code 为 6 位纯数字）。
    已有缓存且 force=False → 直接读缓存，缺的行业增量补拉。
    legulegu 限流（429/504）：2.5s 节流 + 指数退避重试 3 次 + 断点续传。
    """
    # 先读已有缓存（断点续传：缺的才拉）
    cached: dict[str, list[str]] = {}
    if COMPONENTS_PATH.exists():
        try:
            cached = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
            if not isinstance(cached, dict):
                cached = {}
        except (json.JSONDecodeError, OSError):
            cached = {}

    if force:
        cached = {}

    # 触发 base.py 的 DNS monkey-patch（swsresearch.com）+ trust_env=False
    from .base import throttle  # noqa
    import requests
    import re
    from io import StringIO
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    headers = {
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    }

    mapping: dict[str, list[str]] = dict(cached)  # 复制缓存，增量补
    total_new = 0
    for ic in SW_FIRST_LEVEL_CODES:
        if ic in mapping and len(mapping[ic]) > 0:
            continue  # 已有，跳过
        url = f"https://legulegu.com/stockdata/index-composition?industryCode={ic}.SI"
        codes: list[str] = []
        # 重试 4 次，指数退避（429/504 常见）
        for attempt in range(4):
            try:
                throttle()
                r = requests.get(url, headers=headers, timeout=30, verify=False)
                if r.status_code == 200:
                    dfs = pd.read_html(StringIO(r.text))
                    if dfs:
                        df = dfs[0]
                        code_col = None
                        for c in df.columns:
                            if "股票代码" in str(c):
                                code_col = c
                                break
                        if code_col is not None:
                            raw = df[code_col].astype(str).tolist()
                            for s in raw:
                                m = re.match(r"^(\d{6})", s.strip())
                                if m:
                                    codes.append(m.group(1))
                    break  # 成功，退出重试
                elif r.status_code in (429, 502, 503, 504):
                    wait = 5.0 * (attempt + 1)  # 5s, 10s, 15s, 20s
                    print(f"[F3] {ic}: HTTP {r.status_code}, retry in {wait}s "
                          f"(attempt {attempt+1}/4)", flush=True)
                    time.sleep(wait)
                else:
                    print(f"[F3] {ic}: HTTP {r.status_code}", flush=True)
                    break
            except Exception as e:  # noqa: BLE001
                wait = 5.0 * (attempt + 1)
                print(f"[F3] {ic}: ERR {type(e).__name__}: {str(e)[:60]}, "
                      f"retry in {wait}s", flush=True)
                time.sleep(wait)

        if codes:
            mapping[ic] = codes
            total_new += len(codes)
            print(f"[F3] {ic}: {len(codes)} components", flush=True)
        else:
            print(f"[F3] {ic}: FAILED (no codes)", flush=True)
        # 节流：legulegu 限流严格，每次请求后多等
        time.sleep(2.0)

    # 存缓存
    COMPONENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = COMPONENTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mapping, ensure_ascii=False, indent=None), encoding="utf-8")
    tmp.replace(COMPONENTS_PATH)
    n_ind = len(mapping)
    n_stk = sum(len(v) for v in mapping.values())
    print(f"[F3] components saved: {n_ind} industries, {n_stk} stocks total "
          f"(+{total_new} new)", flush=True)
    return mapping


def load_components() -> dict[str, list[str]]:
    """读 data/sw_components.json。若无则拉取。"""
    if COMPONENTS_PATH.exists():
        try:
            return json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return fetch_components()


# ── DB ────────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS industry_width_daily (
  industry_code TEXT NOT NULL,
  date TEXT NOT NULL,
  up_count INTEGER,
  down_count INTEGER,
  zt_count INTEGER,
  dt_count INTEGER,
  zb_count INTEGER,
  seal_rate REAL,
  amount REAL,
  updated_at TEXT,
  PRIMARY KEY (industry_code, date)
);
CREATE INDEX IF NOT EXISTS idx_industry_width_date ON industry_width_daily(date);
CREATE INDEX IF NOT EXISTS idx_industry_width_ind ON industry_width_daily(industry_code);
"""


def _get_sentiment_conn() -> sqlite3.Connection:
    """统一走 app.db.get_conn()：确保建表+迁移（net_inflow 等）在首次连接时执行，
    避免 clone 仓库后直接跑采集器缺列报错。"""
    from app.db import get_conn
    return get_conn()


def init_db() -> None:
    conn = _get_sentiment_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ── 读数据 + 算宽度 ───────────────────────────────────────────────────────────
def load_daily_with_industry(components: dict[str, list[str]],
                             start: str = START_DATE, end: str = END_DATE
                             ) -> pd.DataFrame:
    """从 mootdx_daily_raw 读 2016+ 日线，关联成分股映射加 industry_code 列。

    返回 DataFrame: code/date/high/close/amount/pct_change/rule/industry_code。
    仅保留在成分股映射中的 code（每只 A 股属于一个申万一级）。
    """
    # 反向映射 code → industry_code
    code2ind: dict[str, str] = {}
    for ind, codes in components.items():
        for c in codes:
            code2ind[c] = ind  # 一只股只属于一个一级（若重复取最后一个，正常不重复）

    load_start = "20151201"  # 多读一个月确保首日 prev_close
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

    # 关联 industry_code（仅保留映射中的 code）
    df["industry_code"] = df["code"].map(code2ind)
    df = df[df["industry_code"].notna()].copy()
    # 涨跌幅规则
    df["rule"] = df["code"].map(limit_rule)
    # 只保留 >= start
    df = df[df["date"] >= start].copy()
    return df.reset_index(drop=True)


def compute_industry_width(df: pd.DataFrame) -> pd.DataFrame:
    """算每行业每日宽度。返回按 (industry_code, date) 聚合的 DataFrame。

    输入 df 需含: code/date/high/low/close/amount/pct_change/rule/industry_code。
    输出列: industry_code/date/zt/dt/zb/up/down/amount_sum/seal_rate。
    口径与 D2 width_history.py §8.5 完全一致。
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
    zb = (df["high"] >= zt_price * ZT_TOL) & (df["close"] < zt_price * ZT_TOL) & has_pct & ~ex_div
    up = (p > 0) & has_pct
    down = (p < 0) & has_pct

    tmp = df[["industry_code", "date", "amount"]].copy()
    tmp["zt"] = zt.astype("int32")
    tmp["dt"] = dt.astype("int32")
    tmp["zb"] = zb.astype("int32")
    tmp["up"] = up.astype("int32")
    tmp["down"] = down.astype("int32")

    g = tmp.groupby(["industry_code", "date"], as_index=False).agg(
        zt=("zt", "sum"),
        dt=("dt", "sum"),
        zb=("zb", "sum"),
        up=("up", "sum"),
        down=("down", "sum"),
        amount_sum=("amount", "sum"),
    )
    denom = g["zt"] + g["zb"]
    g["seal_rate"] = g["zt"].where(denom > 0, 0) / denom.where(denom > 0, 1)
    g.loc[denom == 0, "seal_rate"] = float("nan")
    return g.sort_values(["industry_code", "date"]).reset_index(drop=True)


# ── 写库 ──────────────────────────────────────────────────────────────────────
def _now():
    return dt.datetime.now().isoformat()


def upsert_industry_width(g: pd.DataFrame, *, dry_run: bool = False) -> dict:
    """写 industry_width_daily。PK(industry_code, date) 幂等 upsert。

    无 manual 概念（新表），直接覆盖。
    """
    if dry_run:
        return {"written": 0, "dry_run": True}

    conn = _get_sentiment_conn()
    conn.execute("PRAGMA busy_timeout=10000;")
    now = _now()
    rows = []
    for _, r in g.iterrows():
        sr = r["seal_rate"]
        if sr != sr:  # NaN → None
            sr = None
        rows.append((
            r["industry_code"], r["date"],
            int(r["up"]), int(r["down"]), int(r["zt"]), int(r["dt"]), int(r["zb"]),
            sr, r["amount_sum"] / 1.0e8,  # 元 → 亿元
            now,
        ))
    cur = conn.executemany(
        "INSERT INTO industry_width_daily "
        "(industry_code, date, up_count, down_count, zt_count, dt_count, zb_count, seal_rate, amount, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(industry_code, date) DO UPDATE SET "
        "up_count=excluded.up_count, down_count=excluded.down_count, "
        "zt_count=excluded.zt_count, dt_count=excluded.dt_count, zb_count=excluded.zb_count, "
        "seal_rate=excluded.seal_rate, amount=excluded.amount, updated_at=excluded.updated_at",
        rows,
    )
    conn.commit()
    conn.close()
    return {"written": cur.rowcount if cur.rowcount > 0 else len(rows), "dry_run": False}


# ── 主流程 ────────────────────────────────────────────────────────────────────
def run(*, dry_run: bool = False, fetch_only: bool = False, refetch: bool = False) -> dict:
    print("[F3] fetching/loading sw first-level components ...", flush=True)
    components = fetch_components(force=refetch)
    n_ind = len(components)
    n_stk = sum(len(v) for v in components.values())
    print(f"[F3] components: {n_ind} industries, {n_stk} stocks", flush=True)
    if fetch_only:
        return {"industries": n_ind, "stocks": n_stk, "fetch_only": True}

    init_db()
    print(f"[F3] loading mootdx_daily_raw {START_DATE}..{END_DATE} ...", flush=True)
    df = load_daily_with_industry(components)
    print(f"[F3] loaded {len(df):,} rows, {df['code'].nunique()} codes, "
          f"{df['industry_code'].nunique()} industries, {df['date'].nunique()} dates", flush=True)
    if len(df) == 0:
        return {"error": "no data"}

    print("[F3] computing industry width ...", flush=True)
    g = compute_industry_width(df)
    print(f"[F3] computed {len(g)} rows ({g['industry_code'].nunique()} industries × "
          f"{g['date'].nunique()} dates)", flush=True)
    print(f"[F3] zt total={g['zt'].sum()}, dt total={g['dt'].sum()}, zb total={g['zb'].sum()}", flush=True)

    # 写库
    print(f"[F3] writing to industry_width_daily (dry_run={dry_run}) ...", flush=True)
    res = upsert_industry_width(g, dry_run=dry_run)
    print(f"[F3] wrote: {res}", flush=True)
    return {"computed_rows": len(g), "industries": g["industry_code"].nunique(),
            "dates": g["date"].nunique(), "write": res}


def run_recent(days: int = 15, *, dry_run: bool = False) -> dict:
    """增量更新最近 N 天（scheduler 每日跑，mootdx 增量后调）。

    只加载近 days+10 天的 mootdx 数据（多 10 天确保 prev_close），算宽度后 upsert。
    比 run() 全量快（~2s vs ~90s）。
    """
    components = load_components()
    if not components:
        return {"error": "no components, run full first"}
    init_db()
    # 算起始日：今天往前 days+15 自然日（覆盖 days 个交易日 + prev_close buffer）
    today = dt.date.today()
    load_start = (today - dt.timedelta(days=days + 20)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    code2ind: dict[str, str] = {}
    for ind, codes in components.items():
        for c in codes:
            code2ind[c] = ind

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
    df["industry_code"] = df["code"].map(code2ind)
    df = df[df["industry_code"].notna()].copy()
    df["rule"] = df["code"].map(limit_rule)
    # 只写 >= load_start + buffer 之后的日子（保留 buffer 用于 prev_close）
    write_start = (today - dt.timedelta(days=days + 5)).strftime("%Y%m%d")
    df_all = df[df["date"] >= write_start].copy()
    if len(df_all) == 0:
        return {"error": "no data in write window"}
    # compute 需要前后 context（pct_change 已含 prev_close 信息），用全 df 算后过滤写
    g = compute_industry_width(df)
    g = g[g["date"] >= write_start]
    print(f"[F3-recent] {len(g)} rows ({g['industry_code'].nunique()} ind × "
          f"{g['date'].nunique()} dates, since {write_start})", flush=True)
    res = upsert_industry_width(g, dry_run=dry_run)
    return {"computed_rows": len(g), "write": res}


def _cli(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    fonly = "--fetch-only" in argv
    refetch = "--refetch" in argv
    recent = "--recent" in argv
    if recent:
        days = 15
        for a in argv:
            if a.startswith("--days="):
                days = int(a.split("=", 1)[1])
        res = run_recent(days=days, dry_run=dry)
        print(f"\n=== F3 recent done: {res} ===")
        return 0
    res = run(dry_run=dry, fetch_only=fonly, refetch=refetch)
    print(f"\n=== F3 done: {res} ===")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
