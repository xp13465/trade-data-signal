"""TASK-D1 (mootdx 分支): 全 A 股日线本地拉取（替代 akshare，TCP 7709 不封 IP）。

用 mootdx `bars(frequency=9)` 分页拉全 A 股日线，存 `data/stock_daily.db`
的独立表 `mootdx_daily_raw`（与 D1 akshare 的 `stock_daily_raw` 表隔离，
schema/PK 不同避免冲突）。

设计要点
========
- **数据源**：mootdx 走通达信 TCP 7709，不走 HTTP，不被东财 IP 封锁。
  实测 0.03s/页，单只 4 页 ~0.12s，5200 只串行 ~10min。
- **分页**：mootdx `bars` 单次硬上限 800 行（`offset=800`），`start` 是从
  最新往历史的偏移。循环 start=0→800→1600→...，返回 <800 行止，拼 10 年+
  （~4 页 = 3200 行）。安全上限 12 页（9600 行 ≈ 38 年）。
- **字段映射**：datetime→date(YYYYMMDD)，open/close/high/low→同，
  vol→volume（mootdx 同时给 vol 和 volume，值相同，取 volume），
  amount→amount。**无换手率/涨跌幅**：pct_change 自算
  `(close/prev_close-1)*100`（跨除权日失真，不复权原始价，记录不修）；
  turnover 留 NULL（由 BaoStock D3 补）。
- **存储**：`data/stock_daily.db` 表 `mootdx_daily_raw`，schema =
  code/date/open/high/low/close/volume/amount/pct_change/turnover，
  PK(code,date) + 索引(date) + 索引(code)。WAL 模式 + busy_timeout=5s
  与 worker-D3 (baostock_daily_raw) 并发写安全（写锁 DB 级串行，mootdx
  速度快偶发锁等待自动重试）。
- **进度持久化**：`data/mootdx_progress.json` = {code: last_date_yyyymmdd}。
  断点续传：跑前读它，跳过已采 code；增量：每 code 只拉 progress[code]
  之后到今天。
- **不复权**：mootdx 默认（与 D1 akshare `adjust=""` 一致）。
- **baostock fallback**：mootdx 通达信行情接口全 empty 停服时（2026-07-17+
  回归，80 节点 0 可用），run_batch 连续 `consecutive_fail_limit`（默认 50）
  只失败后自动切 baostock 采剩余 code，字段映射后写 **同一张 mootdx_daily_raw**
  表（下游 run_recent 无感）。baostock 含 turn 换手率 -> 填补 mootdx 原本恒
  NULL 的 turnover；pctChg(服务端算) -> 替代 mootdx 自算(不跨除权失真)；
  preclose 丢弃(表无此字段)。进度写 mootdx_progress.json，mootdx 恢复后
  这些 code 不重复采、自动回归 mootdx 主力。
- **CLI**：`python -m app.collector.mootdx_daily <command>`
    full [--limit N] [--fail-limit N]   全量（断点续传，跳过已采）
    update [--limit N] [--fail-limit N] 增量所有 code（只拉最新 1-2 页 + 过滤）
        --fail-limit: 连续N只失败切baostock(默认50，验证可设小值如3)
    one CODE                        单只全量回填
    upone CODE                      单只增量
    stats                           库统计
"""
from __future__ import annotations

import datetime as dt
import json
import socket
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd
from mootdx.quotes import Quotes

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"
PROGRESS_PATH = _DATA_DIR / "mootdx_progress.json"
CODES_CACHE_PATH = _DATA_DIR / "stock_codes.json"

PAGE_SIZE = 800          # mootdx bars 单次硬上限
MAX_PAGES_FULL = 12      # 全量安全上限（9600 行 ≈ 38 年）
MAX_PAGES_INC = 2        # 增量上限（1600 行 ≈ 6 年，覆盖任何合理 gap）

# ── mootdx 客户端（规避 0.11.x BESTIP 空串 bug） ──────────────────────────────
# 实测可用的备选服务器（按延迟排序，2026-06 验证）
_TDX_SERVERS = [
    ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
    ('123.60.73.44', 7709),  ('116.205.163.254', 7709), ('121.36.225.169', 7709),
    ('123.60.70.228', 7709), ('124.71.9.153', 7709),    ('110.41.147.114', 7709),
    ('124.71.187.122', 7709),
]


def _probe(ip, port, timeout=2.0):
    """TCP 握手探测，判断服务器是否可达。

    注意：仅测 TCP 握手可达，不验证能否返回行情数据。部分服务器 TCP 可达
    但 bars() 返回空（协议升级/停服）。故 tdx_client 优先用 bestip=True。
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def _bars_ok(client, code='000001'):
    """发一个真实 bars 请求验证服务器能返回行情数据（非仅 TCP 握手）。"""
    try:
        df = client.bars(symbol=code, frequency=9, offset=10, start=0)
        return df is not None and len(df) > 0
    except Exception:
        return False


def tdx_client(market='std'):
    """创建 mootdx 客户端，规避 0.11.x BESTIP.HQ 空串 bug。

    顺序兜底：
      1) mootdx bestip=True 测速选优（自动选能返回行情的服务器，最可靠）；
      2) bestip 失败 -> 顺序探测 _TDX_SERVERS，用第一个 TCP 可达且 bars 实测通过的；
      3) 再不行 -> 回退裸 factory（老用户 config 已有可用 BESTIP）；
      4) 仍失败 -> 抛 RuntimeError。

    2026-07-12 回归：_TDX_SERVERS 全部 TCP 握手可达但 bars() 返回空（协议升级），
    只有 bestip=True 选出的服务器能正常返回行情，故改为优先 bestip。
    """
    # 1. 优先 bestip=True（mootdx 自动测速选服务器，验证行情可达）
    try:
        client = Quotes.factory(market=market, bestip=True)
        if _bars_ok(client):
            return client
    except Exception:
        pass
    # 2. _TDX_SERVERS 逐个验证（TCP 握手 + bars 实测）
    for ip, port in _TDX_SERVERS:
        if not _probe(ip, port):
            continue
        try:
            client = Quotes.factory(market=market, server=(ip, port))
            if _bars_ok(client):
                return client
        except Exception:
            continue
    # 3. 回退裸 factory
    try:
        return Quotes.factory(market=market)
    except Exception as e:
        raise RuntimeError(
            "所有 mootdx 服务器均不可达或 bars 返回空。海外网络通常全部超时（TCP 7709），"
            "请走国内代理或更新 _TDX_SERVERS 列表。原始错误：%s" % e
        )


# ── DB ────────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS mootdx_daily_raw (
  code TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL,
  pct_change REAL,     -- 涨跌幅 %（自算 close/prev_close-1，跨除权日失真）
  turnover REAL,       -- 换手率 %（mootdx 无此字段，留 NULL，BaoStock D3 补）
  PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_mootdx_daily_date ON mootdx_daily_raw(date);
CREATE INDEX IF NOT EXISTS idx_mootdx_daily_code ON mootdx_daily_raw(code);
"""


def get_conn() -> sqlite3.Connection:
    STOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STOCK_DB_PATH, timeout=10.0)  # busy_timeout 10s，与 worker-D3 并发写
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ── 进度持久化 ────────────────────────────────────────────────────────────────
def load_progress() -> dict[str, str]:
    """{code: last_date_yyyymmdd}。"""
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_progress(progress: dict[str, str]) -> None:
    """原子写：先写临时文件再 rename。"""
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=None, sort_keys=True),
                   encoding="utf-8")
    tmp.replace(PROGRESS_PATH)


# ── code 列表 ─────────────────────────────────────────────────────────────────
def load_codes() -> list[str]:
    """读 data/stock_codes.json（D1 缓存的 5527 只）。"""
    data = json.loads(CODES_CACHE_PATH.read_text(encoding="utf-8"))
    codes = data.get("codes") if isinstance(data, dict) else data
    return sorted(str(c) for c in codes if str(c).strip())


# ── 单只拉取 ──────────────────────────────────────────────────────────────────
def _norm_date(s) -> str:
    """'2026-06-23 15:00' / '2026-06-23' / datetime → '20260623'。"""
    if hasattr(s, "strftime"):
        try:
            return s.strftime("%Y%m%d")
        except (ValueError, AttributeError):
            pass
    return str(s)[:10].replace("-", "").replace("/", "")


def _f(v):
    """转 float；NaN/None/非法 → None（不入库）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def fetch_one(code: str, client=None, max_pages: int | None = None
              ) -> tuple[list[tuple], str, object]:
    """拉单只股票日线，分页拼全历史。返回 (rows, msg, client)。

    rows = [(code, date, open, high, low, close, volume, amount, pct_change, turnover), ...]
    turnover 恒 None（mootdx 无换手率）。pct_change 自算（首行 None）。
    NaN 行过滤；日期归一 YYYYMMDD；按 date 升序。

    max_pages: None=全量（到 <800 行止，安全上限 12 页）；N=限 N 页（增量用）。
    client: 复用外部 client；若 None 则新建。返回的 client 供外部复用（可能被重建）。
    """
    if client is None:
        client = tdx_client()
    cap = MAX_PAGES_FULL if max_pages is None else max_pages

    all_dfs = []
    start = 0
    pages = 0
    while True:
        try:
            df = client.bars(symbol=code, frequency=9, offset=PAGE_SIZE, start=start)
        except Exception as e:
            # 连接可能掉线：重建 client 重试一次
            try:
                client = tdx_client()
                df = client.bars(symbol=code, frequency=9, offset=PAGE_SIZE, start=start)
            except Exception as e2:
                return [], f"fetch err: {type(e2).__name__}: {str(e2)[:150]}", client
        pages += 1
        if df is None or len(df) == 0:
            break
        all_dfs.append(df)
        rows_this = len(df)
        if rows_this < PAGE_SIZE:
            break  # 不足一页 = 已到最早数据
        start += rows_this
        if pages >= cap:
            break

    if not all_dfs:
        return [], "empty", client

    merged = pd.concat(all_dfs, ignore_index=True)
    merged = merged.drop_duplicates(subset='datetime', keep='first')
    merged = merged.sort_values('datetime').reset_index(drop=True)

    # 字段映射 + pct_change 自算
    dates = merged['datetime'].map(_norm_date).tolist()
    opens = merged['open'].map(_f).tolist()
    closes = merged['close'].map(_f).tolist()
    highs = merged['high'].map(_f).tolist()
    lows = merged['low'].map(_f).tolist()
    # mootdx 同时有 vol 和 volume 列（值相同），优先 volume，回退 vol
    if 'volume' in merged.columns:
        vols = merged['volume'].map(_f).tolist()
    else:
        vols = merged['vol'].map(_f).tolist()
    amounts = merged['amount'].map(_f).tolist()

    # pct_change = (close/prev_close - 1) * 100，首行 None
    pct = [None]
    for i in range(1, len(closes)):
        prev, cur = closes[i - 1], closes[i]
        if prev and cur and prev != 0:
            pct.append(round((cur / prev - 1) * 100, 4))
        else:
            pct.append(None)

    rows = []
    for i in range(len(dates)):
        if not dates[i]:
            continue
        rows.append((code, dates[i], opens[i], highs[i], lows[i], closes[i],
                     vols[i], amounts[i], pct[i], None))  # turnover 恒 None
    return rows, f"ok {len(rows)} rows ({pages}p)", client


def upsert_rows(rows: list[tuple]) -> int:
    """批量 upsert 到 mootdx_daily_raw。rows 格式同 fetch_one 返回。"""
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT INTO mootdx_daily_raw "
        "(code, date, open, high, low, close, volume, amount, pct_change, turnover) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(code, date) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
        "volume=excluded.volume, amount=excluded.amount, pct_change=excluded.pct_change, "
        "turnover=excluded.turnover",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


# ── baostock fallback（mootdx 全停服兜底） ─────────────────────────────────────
# 字段映射 baostock row -> mootdx_daily_raw row:
#   baostock = (code, date, open, high, low, close, volume, amount,
#               turnover, pct_change, preclose)
#   mootdx   = (code, date, open, high, low, close, volume, amount,
#               pct_change, turnover)
# 即交换 turnover/pct_change 位置、丢弃 preclose。
# baostock 含 turn(换手率) -> 填补 mootdx 原本恒 NULL 的 turnover；
# baostock pctChg(服务端算) -> 比 mootdx 自算 close/prev_close-1 更准(不跨除权失真)。
def _baostock_to_mootdx_rows(bs_rows: list[tuple]) -> list[tuple]:
    """baostock fetch_one 返回的 rows -> mootdx_daily_raw 入库格式。"""
    # baostock row: (code[0], date[1], open[2], high[3], low[4], close[5],
    #                volume[6], amount[7], turnover[8], pct_change[9], preclose[10])
    # mootdx row:   (code, date, open, high, low, close, volume, amount,
    #                pct_change, turnover)
    return [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[9], r[8])
            for r in bs_rows]


def _run_baostock_fallback(codes: list[str], *, progress: dict[str, str],
                           incremental: bool, today: str,
                           verbose: bool = True) -> tuple[int, int, int]:
    """mootdx 连续失败(疑似全停服)时用 baostock 兜底采剩余 codes，写
    mootdx_daily_raw 表（下游 run_recent 读该表无感）。

    增量模式: 从 progress[code]+1 到 today（无 progress 则从 2016-01-01）。
    全量模式: 从 2016-01-01 到 today（覆盖下游近 10 年需求；1990-2015 老段
              由 baostock old 命令单独补，fallback 不采老段避免耗时）。
    今天已采(progress[code]>=today)的跳过。北交所 code 由 baostock 内部跳过。

    进度写 mootdx_progress.json（非 baostock_progress.json），保证 mootdx
    恢复后这些 code 不重复采、自动回归 mootdx 主力。

    返回 (total_rows, ok_codes, skip_bj_codes)。
    """
    from . import baostock_daily  # 延迟 import，避免启动开销/循环依赖
    baostock_daily._ensure_login()
    recent_start = baostock_daily.RECENT_START.replace("-", "")  # '20160101'
    total_rows = 0
    ok = 0
    skip_bj = 0
    save_every = 5

    for j, code in enumerate(codes):
        last = progress.get(code)
        # 今天已采跳过（full/incremental 通用）
        if last and last >= today:
            continue
        # 起始日期
        if incremental and last:
            d = dt.datetime.strptime(last, "%Y%m%d").date() + dt.timedelta(days=1)
            start = d.strftime("%Y%m%d")
        else:
            start = recent_start  # full 或无 progress -> 从 2016 起
        end = today
        if start.replace("-", "") > end.replace("-", ""):
            continue

        try:
            bs_rows, msg = baostock_daily.fetch_one(code, start, end)
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"    [fallback {j+1}/{len(codes)}] {code}: ERR "
                      f"{type(e).__name__}: {str(e)[:100]}", flush=True)
            continue
        if not bs_rows:
            if "skip bj" in msg:
                skip_bj += 1
            elif verbose and (j + 1) % 100 == 0:
                print(f"    [fallback {j+1}/{len(codes)}] {code}: {msg}", flush=True)
            continue

        mootdx_rows = _baostock_to_mootdx_rows(bs_rows)
        n = upsert_rows(mootdx_rows)
        total_rows += n
        ok += 1
        progress[code] = max(r[1] for r in mootdx_rows)
        if verbose and (j + 1) % 50 == 0:
            print(f"    [fallback {j+1}/{len(codes)}] {code}: +{n} rows "
                  f"(baostock)", flush=True)
        if (j + 1) % save_every == 0:
            save_progress(progress)

    # 不主动 logout：baostock login 进程级幂等，退出自然释放；避免影响可能
    # 并行的 baostock pipeline 的全局 login 状态。
    return total_rows, ok, skip_bj


# ── 增量更新（单只） ──────────────────────────────────────────────────────────
def update_one(code: str, progress: dict[str, str] | None = None,
               client=None, today: str | None = None
               ) -> tuple[int, str, object]:
    """增量拉单只：拉最近 2 页（~6 年），过滤 date > progress[code]。

    mootdx bars 始终从最新往历史拉，无法指定 start_date。增量策略：
    拉 2 页（1600 行 ≈ 6 年）覆盖任何合理 gap，过滤 > progress[code] 的行。
    返回 (新增/更新行数, msg, client)。
    """
    if progress is None:
        progress = load_progress()
    if today is None:
        today = dt.date.today().strftime("%Y%m%d")
    last = progress.get(code)

    # 增量跳过：今天已采（last>=today）直接返回，不发 TCP 请求。
    # mootdx 是 5203 codes 串行主力，update_all 当日重复跑或多数 code 当日已采，
    # 跳过省 ~10-25min。日 K 未收盘本就无新数据，last>=today 跳过安全。
    if last and last >= today:
        return 0, f"up-to-date (last={last})", client

    rows, msg, client = fetch_one(code, client=client, max_pages=MAX_PAGES_INC)
    if not rows:
        return 0, msg, client
    if last:
        rows = [r for r in rows if r[1] > last]
    if not rows:
        return 0, f"up-to-date (last={last})", client
    n = upsert_rows(rows)
    new_last = max(r[1] for r in rows)
    progress[code] = new_last
    return n, f"ok +{n} (last={new_last})", client


# ── 批量 ──────────────────────────────────────────────────────────────────────
def run_batch(codes: list[str], *, incremental: bool = False,
              save_every: int = 5, verbose: bool = True,
              consecutive_fail_limit: int = 50) -> dict:
    """批量拉取。incremental=True 走 update_one（拉 2 页+过滤），否则全量回填。

    串行（mootdx TCP 连接数安全；0.12s/只，5200 只 ~10min）。
    client 复用，遇错重建重试。进度每 save_every 只落盘。

    consecutive_fail_limit: 连续 N 只失败(无 rows)提前终止，避免数据源异常
        (服务端限流/封 IP/返回全 empty)时 5200 只空转数小时触发耗时告警。
        正常时偶发 empty 不会连续达阈值；50 只连续失败 ≈ 数据源已坏。
    """
    init_db()
    progress = load_progress()
    today = dt.date.today().strftime("%Y%m%d")
    ok = fail = total_rows = 0
    consecutive_fails = 0
    aborted = False
    fallback_used = False
    fallback_rows = 0
    fallback_ok = 0
    details: list[tuple] = []
    client = None
    t_start = time.time()

    try:
        client = tdx_client()
    except Exception as e:
        if verbose:
            print(f"!! tdx_client init failed: {e}", flush=True)
        return {"ok": 0, "fail": len(codes), "total_rows": 0,
                "processed": 0, "details": [], "error": str(e)[:150]}

    for i, code in enumerate(codes):
        try:
            if incremental:
                n, msg, client = update_one(code, progress=progress, client=client, today=today)
            else:
                # 全量回填：跳过已采到今天的
                last = progress.get(code)
                if last and last >= today:
                    ok += 1
                    consecutive_fails = 0
                    if verbose and (i + 1) % 500 == 0:
                        print(f"  [{i+1}/{len(codes)}] {code}: skip (last={last})", flush=True)
                    continue
                rows, msg, client = fetch_one(code, client=client)
                if rows:
                    n = upsert_rows(rows)
                    progress[code] = max(r[1] for r in rows)
                else:
                    n = 0
            if n > 0 or "ok" in msg or "up-to-date" in msg:
                ok += 1
                consecutive_fails = 0
                total_rows += n
                details.append((code, "ok", msg))
            else:
                fail += 1
                consecutive_fails += 1
                details.append((code, "fail", msg))
            if verbose and (i + 1) % 100 == 0:
                elapsed = time.time() - t_start
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(codes) - i - 1) / rate if rate > 0 else 0
                print(f"  [{i+1}/{len(codes)}] {code}: {msg} | "
                      f"elapsed {elapsed:.0f}s, {rate:.1f}/s, ETA {eta:.0f}s", flush=True)
        except Exception as e:  # noqa: BLE001  其它错误记 fail 不中断
            fail += 1
            consecutive_fails += 1
            details.append((code, "fail", f"{type(e).__name__}: {str(e)[:150]}"))
            if verbose:
                print(f"  [{i+1}/{len(codes)}] {code}: ERR {type(e).__name__}: "
                      f"{str(e)[:150]}", flush=True)
            # 重建 client 防连接坏掉
            try:
                client = tdx_client()
            except Exception:
                pass
        if (i + 1) % save_every == 0:
            save_progress(progress)
        # 连续失败提前终止：mootdx 全 empty/封 IP/停服时，切 baostock fallback
        # 采剩余 code，写 mootdx_daily_raw（下游无感），避免 5200 只空转数小时。
        if (consecutive_fail_limit > 0
                and consecutive_fails >= consecutive_fail_limit
                and not aborted):
            aborted = True
            remaining_codes = codes[i + 1:]
            if verbose:
                print(f"  ⚠ 连续{consecutive_fails}只失败(阈值{consecutive_fail_limit})，"
                      f"mootdx 疑似全停服，剩余{len(remaining_codes)}只改用 baostock fallback",
                      flush=True)
            if remaining_codes:
                fallback_used = True
                fb_rows, fb_ok, _fb_skip = _run_baostock_fallback(
                    remaining_codes, progress=progress, incremental=incremental,
                    today=today, verbose=verbose)
                fallback_rows = fb_rows
                fallback_ok = fb_ok
                total_rows += fb_rows
                ok += fb_ok
            break

    save_progress(progress)
    elapsed = time.time() - t_start
    if verbose:
        abort_tag = ""
        if aborted:
            abort_tag = " ABORTED(mootdx停服" + (
                f"+baostock fallback: +{fallback_rows}rows/{fallback_ok}codes)" if fallback_used
                else ")")
        print(f"=== batch done: ok={ok} fail={fail} rows={total_rows} "
              f"processed={ok + fail}/{len(codes)} elapsed={elapsed:.0f}s{abort_tag} ===",
              flush=True)
    return {"ok": ok, "fail": fail, "total_rows": total_rows,
            "processed": ok + fail, "details": details, "elapsed": elapsed,
            "aborted": aborted, "fallback_used": fallback_used,
            "fallback_rows": fallback_rows, "fallback_ok": fallback_ok}


# ── CLI ───────────────────────────────────────────────────────────────────────
def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    init_db()

    if cmd == "stats":
        conn = get_conn()
        n_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM mootdx_daily_raw").fetchone()[0]
        n_rows = conn.execute("SELECT COUNT(*) FROM mootdx_daily_raw").fetchone()[0]
        dmin = conn.execute("SELECT MIN(date) FROM mootdx_daily_raw").fetchone()[0]
        dmax = conn.execute("SELECT MAX(date) FROM mootdx_daily_raw").fetchone()[0]
        conn.close()
        prog = load_progress()
        print(f"mootdx_daily_raw: {n_codes} codes, {n_rows} rows, "
              f"date range {dmin}..{dmax}")
        print(f"mootdx_progress.json: {len(prog)} codes tracked")
        return 0

    if cmd == "one":
        if len(argv) < 3:
            print("usage: one CODE"); return 1
        code = argv[2]
        client = tdx_client()
        rows, msg, client = fetch_one(code, client=client)
        print(f"{code}: {msg}")
        if rows:
            n = upsert_rows(rows)
            prog = load_progress()
            prog[code] = max(r[1] for r in rows)
            save_progress(prog)
            print(f"  upserted {n} rows, last={prog[code]}")
            print(f"  sample first: {rows[0]}")
            print(f"  sample last:  {rows[-1]}")
        return 0

    if cmd == "upone":
        if len(argv) < 3:
            print("usage: upone CODE"); return 1
        code = argv[2]
        client = tdx_client()
        n, msg, client = update_one(code, client=client)
        prog = load_progress()
        save_progress(prog)
        print(f"{code}: {msg}")
        return 0

    if cmd == "full":
        limit = None
        fail_limit = 50  # 默认50只连续失败才切baostock，避免偶发抖动误触发
        for a in argv[2:]:
            if a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
            elif a.startswith("--fail-limit="):
                fail_limit = int(a.split("=", 1)[1])
        codes = load_codes()
        prog = load_progress()
        today = dt.date.today().strftime("%Y%m%d")
        todo = [c for c in codes if prog.get(c, "") < today]
        if limit:
            todo = todo[:limit]
        print(f"full: {len(todo)}/{len(codes)} to fetch, "
              f"{len(codes)-len(todo)} already up-to-date "
              f"(fail_limit={fail_limit})", flush=True)
        res = run_batch(todo, incremental=False, verbose=True,
                        consecutive_fail_limit=fail_limit)
        fb = f" fallback=+{res.get('fallback_rows',0)}rows/{res.get('fallback_ok',0)}codes" if res.get('fallback_used') else ""
        print(f"\n=== full done: ok={res['ok']} fail={res['fail']} "
              f"rows={res['total_rows']} elapsed={res.get('elapsed',0):.0f}s{fb} ===")
        return 0

    if cmd == "update":
        limit = None
        fail_limit = 50
        for a in argv[2:]:
            if a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
            elif a.startswith("--fail-limit="):
                fail_limit = int(a.split("=", 1)[1])
        codes = load_codes()
        if limit:
            codes = codes[:limit]
        print(f"update: {len(codes)} codes incremental "
              f"(fail_limit={fail_limit})", flush=True)
        res = run_batch(codes, incremental=True, verbose=True,
                        consecutive_fail_limit=fail_limit)
        fb = f" fallback=+{res.get('fallback_rows',0)}rows/{res.get('fallback_ok',0)}codes" if res.get('fallback_used') else ""
        print(f"\n=== update done: ok={res['ok']} fail={res['fail']} "
              f"rows={res['total_rows']} elapsed={res.get('elapsed',0):.0f}s{fb} ===")
        return 0

    print(f"unknown command: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
