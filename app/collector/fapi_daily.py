#!/usr/bin/env python3
"""FAPI(P0) 日线 T+0 采集:同花顺金融开放平台全市场日线 dump 增量写入。

试点背景(docs/fapi/fapi-integration-plan-20260901.md §2):mootdx 主链存在
断片(000001 曾停 08-24)+ 北交所缺口 + BaoStock T+1 痛点,本脚本从 FAPI
全市场 dump(daily-k-10d)获得 T+0 当日全部 A 股日线,作为「官换届兜底」,
与 mootdx_daily_raw 双源互证(§15.1 异源互备),观察 ≥1 周后评估转主。

流程(3 步):
  ① GET /api/dump/market-dumps/daily-k-10d/download-url(X-api-key 头)
     → data.presigned_url(预签名 ≤5 分钟过期,须立即用)
  ② GET presigned_url 下载 Parquet(dump 实测 ~1.1MB / 55448 行 / 10 交易日)
  ③ pyarrow 读 → 字段映射 → UPSERT 到 fapi_daily_raw,主键 (thscode, date_ms)

字段映射(FAPI dump → fapi_daily_raw):
  thscode "600519.SH" → code=600519(去 .SH/.SZ/.BJ 后缀)+ thscode 原样保留
  date_ms(int64 毫秒 Asia/Shanghai 零点) → date=YYYYMMDD
  open/high/low/close_price → open/high/low/close(直接)
  volume → volume(股)
  turnover → amount  ⚠️ 命名坑:FAPI turnover=成交额(元)非换手率,必须映射到
                      amount,不能同名直拷(机检断言 turnover > volume 才通过)
  (无) → pct_change 自算 close/prev_close-1(与 mootdx 同口径,首日 None)
  (无) → turnover=换手率:缺失,NULL(由现有腾讯/快照链补)

增量策略:
  - 常规:  daily-k-10d(每交易日 1 次,10 交易日窗口,默认)
  - 重建:  库内最新日期落后 ≥8 自然日 → 自动切 daily-k(10 年全量)一次跑完,
            防缺口;加 `full` 参数强制全量。
  增量与本地重叠按主键 (thscode,date_ms) UPSERT 去重,幂等可重复。

幂等/重试:UPSERT 天然幂等;下载 5 分钟过期前立即用,session 重试 ≤3 次指数
退避;换手率列始终 NULL(FAPI dump 不含),不覆盖其他源写入。

安全:API key 只从 .env 读(HITHINK_FINANCE_API_KEY),绝不打印/入日志/入 git;
    presigned_url 只打 host 不打 querystring(防泄露签名参数)。

CLI:
  python -m app.collector.fapi_daily [--full] [--dry-run] [--workdir PATH]
  --full      强制全量 daily-k 重建(默认自动判断)
  --dry-run   下载+映射验证,不写库
  --workdir   显式指定仓库根(默认根据 __file__ 自动定位)

依赖:requests, pyarrow(.venv 已装)
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq
import requests

BASE = "https://fuyao.aicubes.cn"
DUMP_10D = "daily-k-10d"
DUMP_FULL = "daily-k"
STALE_DAYS = 8  # 库内最新日落后 ≥8 自然日 → 全量重建(含周末/节假日缓冲)
RETRY = 3
BACKOFF = [5, 15, 30]  # 秒

_DB_TZ = dt.timezone(dt.timedelta(hours=8))
_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
DB_PATH = _DATA_DIR / "stock_daily.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fapi_daily_raw (
  thscode TEXT NOT NULL,        -- 600519.SH 原始 thscode
  date_ms INTEGER NOT NULL,     -- int64 毫秒,Asia/Shanghai 零点
  code TEXT NOT NULL,           -- 600519(去后缀整理)
  date TEXT NOT NULL,           -- 20260901
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL,     -- amount = FAPI turnover(成交额元),命名交换
  pct_change REAL,              -- 自算 close/prev_close-1,与 mootdx 同口径
  turnover REAL,                -- 换手率:不存在,恒 NULL(由现有链补)
  PRIMARY KEY (thscode, date_ms)
);
CREATE INDEX IF NOT EXISTS idx_fapi_daily_code ON fapi_daily_raw(code);
CREATE INDEX IF NOT EXISTS idx_fapi_daily_date ON fapi_daily_raw(date);
"""


def load_key() -> str:
    """从 .env 读 HITHINK_FINANCE_API_KEY,绝不打印明文。"""
    # key 实际放 trade/.env;launchd 从 trade-data 跑时 __file__ 定位到 trade-data 侧,
    # 故两处都查:先 trade-data(生产运行目录),再 trade(开发目录)。
    for cand in (Path("/Users/linhuichen/code/trade-data/.env"),
                 Path("/Users/linhuichen/code/trade/.env")):
        if cand.exists():
            for line in cand.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("HITHINK_FINANCE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("HITHINK_FINANCE_API_KEY not found in .env")


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_download_url(key: str, dump: str = DUMP_10D) -> str:
    """签名下载 URL。失败重试 ≤3 次(网络抖动)。"""
    h = {"X-api-key": key}
    last = None
    for i in range(RETRY):
        try:
            r = requests.get(f"{BASE}/api/dump/market-dumps/{dump}/download-url",
                             headers=h, timeout=60)
            r.raise_for_status()
            j = r.json()
            assert j.get("code") == 0, f"FAPI code={j.get('code')} msg={j.get('message', '')[:120]}"
            data = j["data"]
            url = (data.get("download_url") or data.get("presigned_url")
                   or data.get("url"))
            assert url, f"download-url 无 url: {list(data.keys())}"
            return url
        except Exception as e:  # noqa: BLE001
            last = e
            if i < RETRY - 1:
                time.sleep(BACKOFF[i])
    raise RuntimeError(f"[fapi_daily] 获取下载 URL 失败({RETRY} 次): {last}")


def download_parquet(url: str, dest: Path) -> Path:
    """立即下载 parquet(预签名短时效)。只打 host 不打 querystring。"""
    host = url.split("?", 1)[0]
    print(f"[fapi_daily] 下载 {host} …", flush=True)
    last = None
    for i in range(RETRY):
        try:
            with requests.get(url, timeout=600, stream=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
                return dest
        except Exception as e:  # noqa: BLE001
            last = e
            if i < RETRY - 1:
                time.sleep(BACKOFF[i])
    raise RuntimeError(f"[fapi_daily] 下载失败({RETRY} 次): host={host} err={last}")


def _ms_to_date(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=_DB_TZ).strftime("%Y%m%d")


def _code_from(thscode: str) -> str:
    return str(thscode).split(".")[0].strip()


def _f(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def map_frame(df) -> list[tuple]:
    """dump DataFrame → 入库行列表(含只增仅 dup 0 的防御断言)。

    行格式:(thscode, date_ms, code, date, open, high, low, close,
             volume, amount, pct_change, turnover)
    """
    rows = []
    # 按 code 分组,date 升序,算 pct_change(与 mootdx 同口径)
    df = df.sort_values(["thscode", "date_ms"]).reset_index(drop=True)
    groups = df.groupby("thscode", sort=False).indices

    for ts, idx in groups.items():
        g = df.loc[idx]
        closes = g["close_price"].map(_f).tolist()
        dates = [_ms_to_date(int(ms)) for ms in g["date_ms"].tolist()]
        for i in range(len(g)):
            prev = closes[i - 1] if i > 0 else None
            cur = closes[i]
            pct = None
            if prev and cur and prev != 0:
                pct = round((cur / prev - 1) * 100, 4)
            rows.append((
                str(ts),
                int(g.iloc[i]["date_ms"]),
                _code_from(str(ts)),
                dates[i],
                _f(g.iloc[i]["open_price"]),
                _f(g.iloc[i]["high_price"]),
                _f(g.iloc[i]["low_price"]),
                cur,
                _f(g.iloc[i]["volume"]),
                _f(g.iloc[i]["turnover"]),  # 命名交换:成交额 → amount
                pct,
                None,  # 换手率恒 NULL
            ))
    return rows


def upsert_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT INTO fapi_daily_raw "
        "(thscode, date_ms, code, date, open, high, low, close, "
        " volume, amount, pct_change, turnover) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(thscode, date_ms) DO UPDATE SET "
        "code=excluded.code, date=excluded.date, open=excluded.open, "
        "high=excluded.high, low=excluded.low, close=excluded.close, "
        "volume=excluded.volume, amount=excluded.amount, "
        "pct_change=excluded.pct_change, turnover=excluded.turnover",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def db_latest_date() -> str | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT MAX(date) FROM fapi_daily_raw").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _stale(latest: str | None) -> bool:
    """库内最新日落后 ≥STALE_DAYS 自然日 → 全量重建。"""
    if latest is None:
        return False  # 首次无数据:10d 增量起步
    try:
        gap = (dt.date.today() - dt.datetime.strptime(latest, "%Y%m%d").date()).days
    except ValueError:
        gap = 999
    return gap >= STALE_DAYS


def run(full: bool = False, dry_run: bool = False) -> dict:
    init_db()
    key = load_key()
    dump = DUMP_FULL if (full or _stale(db_latest_date())) else DUMP_10D
    print(f"[fapi_daily] dump={dump} dry_run={dry_run}", flush=True)

    dest = _DATA_DIR / f"{dump}.parquet"
    url = get_download_url(key, dump)
    download_parquet(url, dest)

    table = pq.read_table(dest)
    print(f"[fapi_daily] parquet rows={table.num_rows} "
          f"schema={[(f.name, str(f.type)) for f in table.schema]}", flush=True)
    df = table.to_pandas()

    # 防御断言:主键零重复 + 命名坑机检(turnover>volume 才符合成交额语义)
    dup = int(df.duplicated(subset=["thscode", "date_ms"]).sum())
    if dup:
        raise RuntimeError(f"[fapi_daily] dump 主键重复 {dup} 行,中止(数据异常)")
    amt_ok = (df["turnover"].abs() > df["volume"].abs()).mean()
    if amt_ok < 0.9:
        raise RuntimeError(
            f"[fapi_daily] turnover 语义疑似非成交额(与 volume 比 {amt_ok:.0%} "
            f">volume),拒绝映射,防止换手率/成交额错位")

    rows = map_frame(df)
    if dry_run:
        print(f"[fapi_daily] DRY-RUN: 映射 {len(rows)} 行,不写库", flush=True)
        return {"dump": dump, "rows": len(rows), "dry_run": True}

    n = upsert_rows(rows)
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM fapi_daily_raw").fetchone()[0]
    mdate = conn.execute("SELECT MAX(date) FROM fapi_daily_raw").fetchone()[0]
    ncode = conn.execute("SELECT COUNT(DISTINCT code) FROM fapi_daily_raw").fetchone()[0]
    conn.close()
    print(f"[fapi_daily] upserted {n} rows; 库 {cnt} rows / {ncode} codes, "
          f"latest={mdate}", flush=True)
    # 下载的临时 dump 已消费,清理防 accumulate(.part 由 tempfile 自动回收)
    try:
        dest.unlink(missing_ok=True)
    except OSError:
        pass  # 清理失败不阻断(残留 1MB 可接受)
    return {"dump": dump, "upserted": n, "db_rows": cnt, "db_codes": ncode,
            "db_latest": mdate}


def _cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="FAPI 日线 T+0 采集")
    ap.add_argument("--full", action="store_true", help="强制全量 daily-k 重建")
    ap.add_argument("--dry-run", action="store_true", help="只映射不下库")
    args = ap.parse_args(argv)
    run(full=args.full, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))