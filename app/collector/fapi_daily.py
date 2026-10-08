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
  - 重建:  库内最新日期落后面临"缺口超出 10d 窗口能力"时才切 daily-k(10 年全量);
            判据为**交易日**口径(缺口 > STALE_TRADING_DAYS 个交易日,默认 10),
            长假后首跑不会因自然日跨度大而误切全量;加 `full` 参数强制全量。
  增量与本地重叠按主键 (thscode,date_ms) UPSERT 去重,幂等可重复。

#238 治本:full 路径改**流式分块**(ParquetFile.iter_batches → 逐列转 numpy → 逐组映射
→ 分批 upsert),峰值内存 ~290MB(本机 181MB / 1032 万行实测;旧全量路径 2786MB,
约 9.6x 降幅),不再全程物化(read_table → to_pandas → sort → 1032 万 tuple list
→ 一次性 executemany),消除 3.6GB 小机「单次全量 OOM 拖垮整机」。
峰值地板 = pyarrow 解码的最大 row group(rg0 = 765 万行 / 8 列未压缩 183MB,
加 pyarrow 工作集 ≈ 285MB 地板),与全量行数无关。
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

依赖:requests, pyarrow, numpy(.venv 已装)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import requests

BASE = "https://fuyao.aicubes.cn"
DUMP_10D = "daily-k-10d"
DUMP_FULL = "daily-k"
# #238 ⑤ 缺口判据 = **交易日**(非自然日)。daily-k-10d dump 覆盖最近 10 个交易日,
# 故只有当缺口 > 10 交易日(超出 10d 窗口能力)时才必须走全量;旧口径 STALE_DAYS=8
# (自然日)被国庆 8 天休市精确击穿 → 节后首跑误切全量 → 3.6GB 小机 OOM。
# 环境变量 FAPI_STALE_TRADING_DAYS 可覆盖(默认 10)。见 _stale / _stale_trading_days。
STALE_TRADING_DAYS = 10
STALE_TRADING_DAYS_ENV = "FAPI_STALE_TRADING_DAYS"
# #238 ④ 流式分块批大小(行/批)。峰值内存主要**由 pyarrow 解码的 row group 决定**
# (与本参数弱相关),故取小批以压 overhead。本机在 181MB / 1032 万行真实 dump
# (row group 0 = 765 万行 / 8 列未压缩 183MB)实测:bs=1万 峰值 RSS ~290MB
# (bs=5千 ~284MB 地板 = pyarrow 解码缓冲,bs=5万 ~329MB);旧全量路径实测 2786MB。
# 全量映射耗时与批大小无关(实测 ~29s / 1032 万行)。
BATCH_SIZE = 10_000
# 映射实际用到的列(其余 currency/interval/adjusted 全程未用,列裁剪省内存 —— 实测有效)
_COLS = ["thscode", "date_ms", "open_price", "high_price", "low_price",
         "close_price", "volume", "turnover"]
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
    # 优先 __file__ 派生的仓根 .env(云上单仓 /home/ubuntu/code/trade-data-signal/.env),
    # 再回退 macOS 本机 trade-data/trade 硬编码(向后兼容)。云上仅 mac 硬编码会读不到
    # key → SystemExit(2026-09-13 迁移残留修)。
    for cand in (_DATA_DIR.parent / ".env",
                 Path("/Users/linhuichen/code/trade-data/.env"),
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


_UPSERT_SQL = (
    "INSERT INTO fapi_daily_raw "
    "(thscode, date_ms, code, date, open, high, low, close, "
    " volume, amount, pct_change, turnover) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(thscode, date_ms) DO UPDATE SET "
    "code=excluded.code, date=excluded.date, open=excluded.open, "
    "high=excluded.high, low=excluded.low, close=excluded.close, "
    "volume=excluded.volume, amount=excluded.amount, "
    "pct_change=excluded.pct_change, turnover=excluded.turnover"
)


def _map_group(ts: str, cols: dict) -> list[tuple]:
    """单个 thscode 组(列名→numpy 数组)→ 入库行列表(#238 ④ 组处理原子)。

    pct_change 只依赖**同组内前一行**(组内时序前收,首日 None),不跨组依赖 ⇒
    天然可流式;组内排序由本函数保证(异常乱序时按 date_ms 稳定排序)。
    入参用 numpy 列数组(而非 DataFrame),省去 `to_pandas()` 的整批物化开销(实测 ~54MB)。
    """
    dm = cols["date_ms"]
    if len(dm) > 1 and not bool(np.all(dm[1:] >= dm[:-1])):
        order = np.argsort(dm, kind="stable")
        cols = {k: v[order] for k, v in cols.items()}
        dm = cols["date_ms"]
    close = cols["close_price"]
    opens = cols["open_price"]
    highs = cols["high_price"]
    lows = cols["low_price"]
    vols = cols["volume"]
    tos = cols["turnover"]
    code = _code_from(str(ts))
    rows = []
    prev = None
    for i in range(len(dm)):
        cur = _f(close[i])
        pct = None
        if prev and cur and prev != 0:
            pct = round((cur / prev - 1) * 100, 4)
        dms_i = int(dm[i])
        rows.append((
            str(ts),
            dms_i,
            code,
            _ms_to_date(dms_i),
            _f(opens[i]),
            _f(highs[i]),
            _f(lows[i]),
            cur,
            _f(vols[i]),
            _f(tos[i]),  # 命名交换:成交额 → amount
            pct,
            None,        # 换手率恒 NULL
        ))
        prev = cur
    return rows


def map_frame(df) -> list[tuple]:
    """[参照实现 / reference oracle]dump DataFrame → 入库行列表。

    ⚠️ 生产路径已改**流式**(`process_parquet`);本函数保留为语义参照,供测试做
    差分对账(§5.4⑦:复用单一语义源,防第二份实现静默漂移),也可人工核查。
    与流式路径共享同一 `_map_group`(单一语义源),避免第二份实现静默漂移。
    行格式:(thscode, date_ms, code, date, open, high, low, close,
             volume, amount, pct_change, turnover)
    """
    df = df.sort_values(["thscode", "date_ms"]).reset_index(drop=True)
    rows: list[tuple] = []
    for ts, g in df.groupby("thscode", sort=False):
        cols = {name: g[name].to_numpy() for name in _COLS}
        rows.extend(_map_group(str(ts), cols))
    return rows


def _iter_groups(path, batch_size: int = BATCH_SIZE):
    """流式产出 (thscode, {列名→numpy 数组}) **完整组**(#238 ④核心)。

    前提:dump 按 thscode **连续分组**(定因报告已证 dump 按 thscode 排序)。批尾未闭合
    的组缓冲至下一批,各批只放行已闭合的组(组=处理原子单位)。
    守卫:某 thscode 被放行后再次出现 ⇒ dump 分组前提被破坏,抛错中止(防把
    pct_change 静默算错),不静默吞掉。
    只读映射所需列(`_COLS`);`use_threads=False` 省 pyarrow 线程缓冲;逐列转 numpy
    (不经 `to_pandas()`),实测峰值更低。
    """
    pf = pq.ParquetFile(path)
    pend = None                    # 尾部未闭合组:列名 → numpy 数组(已 copy,脱离 batch)
    pend_ts = None
    finalized: set[str] = set()

    def _emit(ts, cols):
        ts = str(ts)
        if ts in finalized:
            raise RuntimeError(
                f"[fapi_daily] dump 未按 thscode 连续分组(thscode {ts} 重复出现),"
                f"流式分组前提被破坏,中止(防 pct_change 静默算错)")
        finalized.add(ts)
        return ts, cols

    for batch in pf.iter_batches(batch_size=batch_size, columns=_COLS,
                                 use_threads=False):
        arr = {name: batch.column(i).to_numpy(zero_copy_only=False)
               for i, name in enumerate(_COLS)}
        codes = arr["thscode"]
        n = len(codes)
        if n == 0:
            continue
        # 连续段边界:starts[j]..ends[j] 为同 thscode 的连续行段
        if n > 1:
            starts = np.concatenate(([0], np.nonzero(codes[1:] != codes[:-1])[0] + 1))
        else:
            starts = np.array([0])
        ends = np.concatenate((starts[1:], [n]))
        j0 = 0
        if pend is not None:
            if str(codes[0]) == pend_ts:
                if len(starts) == 1:  # 整批同码(单组 ≥ 批大小,罕见):仍未闭合,继续缓冲
                    pend = {k: np.concatenate([pend[k], arr[k]]) for k in _COLS}
                    continue
                merged = {k: np.concatenate([pend[k], arr[k][:ends[0]]]) for k in _COLS}
                yield _emit(pend_ts, merged)
                j0 = 1
            else:
                yield _emit(pend_ts, pend)
            pend = None
            pend_ts = None
        for j in range(j0, len(starts)):
            s, e = int(starts[j]), int(ends[j])
            # copy 脱离 batch 缓冲(尾部组要跨批存活,不 pin 整批内存)
            sub = {k: arr[k][s:e].copy() for k in _COLS}
            if j == len(starts) - 1:
                pend, pend_ts = sub, str(codes[s])  # 尾部未闭合组(≥1 行)
            else:
                yield _emit(str(codes[s]), sub)
    if pend is not None:
        yield _emit(pend_ts, pend)


def process_parquet(path, *, batch_size: int = BATCH_SIZE, on_rows=None) -> dict:
    """流式处理 dump parquet:逐组映射 → 分批回调 `on_rows(rows)`(#238 ④)。

    峰值内存与 `batch_size` 同阶(非全量)。防御断言(与旧全量口径等价):
      · 主键 (thscode,date_ms) 零重复:重复项必共享 thscode ⇒ 必落在同一组内,
        故「组内 date_ms 去重判」== 「全量 (thscode,date_ms) 去重判」;
      · turnover 语义机检:全量累计 |turnover|>|volume| 占比 ≥0.9(命名坑守卫)。
    """
    total = 0
    dup = 0
    amt_ok = 0
    for ts, cols in _iter_groups(path, batch_size):
        dm = cols["date_ms"]
        dup += int(len(dm) - len(np.unique(dm)))
        amt_ok += int(np.sum(np.abs(cols["turnover"]) > np.abs(cols["volume"])))
        rows = _map_group(ts, cols)
        total += len(rows)
        if on_rows is not None:
            on_rows(rows)
    if dup:
        raise RuntimeError(f"[fapi_daily] dump 主键重复 {dup} 行,中止(数据异常)")
    if total and amt_ok / total < 0.9:
        raise RuntimeError(
            f"[fapi_daily] turnover 语义疑似非成交额(与 volume 比 {amt_ok / total:.0%} "
            f">volume),拒绝映射,防止换手率/成交额错位")
    return {"rows": total, "dup": dup, "amt_ok": amt_ok}


def upsert_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    try:
        conn.executemany(_UPSERT_SQL, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def db_latest_date() -> str | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT MAX(date) FROM fapi_daily_raw").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _stale_trading_days() -> int:
    """当前全量阈值(交易日)。环境变量 `FAPI_STALE_TRADING_DAYS` 覆盖,非法值回退默认。"""
    try:
        return int(os.environ.get(STALE_TRADING_DAYS_ENV, STALE_TRADING_DAYS))
    except (TypeError, ValueError):
        return STALE_TRADING_DAYS


def _stale(latest: str | None, *, today: dt.date | None = None,
           trading_days_fn=None) -> bool:
    """库内最新日期缺口 > 阈值**交易日** → 全量重建(#238 ⑤:交易日口径)。

    daily-k-10d dump 覆盖最近 10 个交易日,故缺口 ≤10 交易日时 10d 增量即可补齐,
    无需全量;仅当缺口 > 阈值(default 10 交易日)才必须走全量。

    防前视(§5.1⑥):只统计 (latest, today] 区间内的交易日,**显式排除任何 > today 的
    日期**——即便调用方传入含未来日期的完整交易日历,也不会用到 t 之后的数据;判定在
    运行当次(t = today)生效,不使用任何未来日历。复用项目既有交易历机制
    `app.calendar.trading_days_between`(固化口径,不另造)。

    `today` / `trading_days_fn` 可注入以便确定性测试(默认取真实今天 + 真实交易日历)。
    """
    if latest is None:
        return False  # 首次无数据:10d 增量起步
    today = today or dt.date.today()
    today_s = today.strftime("%Y%m%d")
    try:
        dt.datetime.strptime(latest, "%Y%m%d")
    except (TypeError, ValueError):
        return True  # 库内日期不可解析 = 数据异常,保守走全量自愈
    if trading_days_fn is None:
        from app.calendar import trading_days_between
        td = trading_days_between(latest, today)
    else:
        td = trading_days_fn(latest, today)
    # 只数 (latest, today] 内交易日;`d <= today_s` 是防前视的显式闸门
    gap_td = sum(1 for d in td if latest < d <= today_s)
    return gap_td > _stale_trading_days()


def run(full: bool = False, dry_run: bool = False) -> dict:
    init_db()
    key = load_key()
    dump = DUMP_FULL if (full or _stale(db_latest_date())) else DUMP_10D
    print(f"[fapi_daily] dump={dump} dry_run={dry_run}", flush=True)

    dest = _DATA_DIR / f"{dump}.parquet"
    url = get_download_url(key, dump)
    download_parquet(url, dest)

    # #238 ④:只读 parquet 元数据(不物化),再流式分块处理
    pf = pq.ParquetFile(dest)
    print(f"[fapi_daily] parquet rows={pf.metadata.num_rows} "
          f"schema={[(f.name, str(f.type)) for f in pf.schema_arrow]}", flush=True)

    if dry_run:
        stats = process_parquet(dest)
        print(f"[fapi_daily] DRY-RUN: 映射 {stats['rows']} 行,不写库", flush=True)
        return {"dump": dump, "rows": stats["rows"], "dry_run": True}

    # 流式:逐组映射 → 分批 upsert(每批 commit,限 WAL 增长),防御断言在内部累计
    conn = get_conn()
    written = 0

    def _flush(rows: list[tuple]) -> None:
        nonlocal written
        conn.executemany(_UPSERT_SQL, rows)
        conn.commit()
        written += len(rows)

    try:
        process_parquet(dest, on_rows=_flush)
    finally:
        conn.close()

    n = written
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