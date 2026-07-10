"""TASK-D1: 全 A 股日线本地拉取（回溯基础设施）。

用 akshare `stock_zh_a_hist`（东财 push2his kline 端点）拉全 A 股（~5500 只）日线，
10 年历史（start_date=20160101），存本地 raw store。

设计要点
========
- **存储**：独立 SQLite 库 `data/stock_daily.db`，表 `stock_daily_raw`。
  理由：(1) 与 `data/sentiment.db`（看板生产库）隔离，避免 ~13M 行原始日线撑大生产库
  影响看板查询；(2) 仍是 SQLite，D2 可直接 SQL 跨表算宽度，好查询；(3) WAL 模式
  读写并发安全；(4) 13M 行量级 SQLite 可承（~1-2GB），后续若需可平滑迁 parquet。
- **schema**：code/date/open/high/low/close/volume/amount/amplitude/pct_change/pct_amt/
  turnover。pct_change/pct_amt 留作 D2 涨停价/跌停价判定（主板 10% / 创业板科创板 20% / ST 5%）。
- **进度持久化**：`data/stock_daily_progress.json` = {code: last_date_yyyymmdd}。
  断点续传：跑前读它，跳过已采 code；增量更新：每个 code 只拉 progress[code] 之后到今天。
- **防封**：1s 串行节流 + 0.1-0.5s jitter（与 base.em_get 同档），遇
  RemoteDisconnected/ConnectionError/429 → 抛 CooldownError，停止批次、保存进度、汇报
  剩余待采（不硬刷，冷却 30min 再手动重跑）。复用 base 的 trust_env=False 全局补丁
  （绕 Clash 代理直连东财）。
- **CLI**：`python -m app.collector.stock_daily <command>`
    full [--start 20160101] [--limit N]   全量（断点续传，跑 N 只后停）
    update [--limit N]                    增量所有 code（只拉最新日）
    one CODE                              单只全量回填
    upone CODE                            单只增量
    codes                                 重建 code 列表缓存
    stats                                 库统计
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

# 必须先 import base，应用 trust_env=False 全局补丁（绕 Clash 代理）
from . import base  # noqa: F401
import akshare as ak

from .base import safe_call

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"
PROGRESS_PATH = _DATA_DIR / "stock_daily_progress.json"
CODES_CACHE_PATH = _DATA_DIR / "stock_codes.json"
COOLDOWN_LOG_PATH = _DATA_DIR / "stock_daily_cooldown.txt"

DEFAULT_START = "20160101"  # 10 年回溯

# ── 防封参数 ──────────────────────────────────────────────────────────────────
EM_MIN_INTERVAL = 1.0          # 东财 1s 串行（与 base.em_get 同档）
_last_call = [0.0]


def _throttle():
    """1s 串行 + 0.1-0.5s jitter，防东财速率风控。"""
    wait = EM_MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    _last_call[0] = time.time()


class CooldownError(Exception):
    """东财封 IP 信号（RemoteDisconnected/ConnectionError/429）。

    携带 remaining_codes（未采 code 列表）与 last_code（最后尝试的 code），
    CLI 捕获后保存进度、汇报剩余、退出（不硬刷）。
    """

    def __init__(self, message, remaining_codes=None, last_code=None):
        super().__init__(message)
        self.remaining_codes = remaining_codes or []
        self.last_code = last_code


# ── DB ────────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_daily_raw (
  code TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL,
  amplitude REAL,      -- 振幅 %
  pct_change REAL,     -- 涨跌幅 %
  pct_amt REAL,        -- 涨跌额（元，close - prev_close）
  turnover REAL,       -- 换手率 %
  PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_daily_raw(date);
CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily_raw(code);
"""


def get_conn() -> sqlite3.Connection:
    STOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STOCK_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    # 与 mootdx/baostock 并发写同库不同表时写锁串行化自动重试。
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ── 进度持久化 ────────────────────────────────────────────────────────────────
def load_progress() -> dict[str, str]:
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
def fetch_stock_codes(force_refresh: bool = False) -> list[str]:
    """全 A 股代码列表（~5500 只）。优先读缓存，否则走 akshare。

    用 `stock_info_a_code_name`（东财 dataapi 端点，非 push2his，未被反爬封）。
    返回 6 位代码字符串列表（如 '600519'），按代码升序。
    """
    if not force_refresh and CODES_CACHE_PATH.exists():
        try:
            data = json.loads(CODES_CACHE_PATH.read_text(encoding="utf-8"))
            codes = data.get("codes") if isinstance(data, dict) else data
            if codes:
                return codes
        except (json.JSONDecodeError, OSError):
            pass
    df = safe_call(ak.stock_info_a_code_name, retries=3)
    if isinstance(df, Exception) or df is None or len(df) == 0:
        raise RuntimeError(f"fetch_stock_codes failed: {df}")
    codes = sorted(str(c) for c in df["code"].tolist() if str(c).strip())
    CODES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODES_CACHE_PATH.write_text(
        json.dumps({"codes": codes, "count": len(codes),
                    "fetched_at": dt.datetime.now().isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )
    return codes


# ── 单只拉取 ──────────────────────────────────────────────────────────────────
def _norm_date(s) -> str:
    if hasattr(s, "strftime"):
        try:
            return s.strftime("%Y%m%d")
        except (ValueError, AttributeError):
            pass
    return str(s).replace("-", "").replace("/", "")


def _f(v):
    """转 float；NaN/None/非法 → None（不入库）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def fetch_one(code: str, start_date: str, end_date: str) -> tuple[list[tuple], str]:
    """拉单只股票日线。返回 (rows, msg)。

    rows = [(code, date, open, high, low, close, volume, amount,
             amplitude, pct_change, pct_amt, turnover), ...]
    NaN 行过滤；日期归一为 YYYYMMDD。

    防封：调用前 _throttle()；遇 RemoteDisconnected/ConnectionError → 抛 CooldownError。
    """
    _throttle()
    try:
        df = ak.stock_zh_a_hist(symbol=code, period="daily",
                                start_date=start_date, end_date=end_date, adjust="")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        ename = type(e).__name__
        # 东财封 IP 信号：RemoteDisconnected / ConnectionError / 429
        if ("RemoteDisconnected" in msg or "Remote end closed" in msg
                or ename in ("ConnectionError", "ProxyError")
                or "429" in msg):
            raise CooldownError(f"{ename}: {msg[:200]}", last_code=code)
        return [], f"fetch err: {ename}: {msg[:200]}"
    if df is None or len(df) == 0:
        return [], "empty"
    # akshare 1.18.64 stock_zh_a_hist 固定中文列名（已从源码确认）：
    # 日期/开盘/收盘/最高/最低/成交量/成交额/振幅/涨跌幅/涨跌额/换手率/股票代码
    rows = []
    for _, r in df.iterrows():
        d = _norm_date(r["日期"]) if "日期" in df.columns else None
        if not d:
            continue
        row = (code, d,
               _f(r.get("开盘")), _f(r.get("最高")), _f(r.get("最低")), _f(r.get("收盘")),
               _f(r.get("成交量")), _f(r.get("成交额")),
               _f(r.get("振幅")), _f(r.get("涨跌幅")), _f(r.get("涨跌额")),
               _f(r.get("换手率")))
        rows.append(row)
    return rows, "ok" if rows else "empty after norm"


def upsert_rows(rows: list[tuple]) -> int:
    """批量 upsert 到 stock_daily_raw。rows 格式同 fetch_one 返回。"""
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT INTO stock_daily_raw "
        "(code, date, open, high, low, close, volume, amount, amplitude, "
        "pct_change, pct_amt, turnover) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(code, date) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
        "volume=excluded.volume, amount=excluded.amount, amplitude=excluded.amplitude, "
        "pct_change=excluded.pct_change, pct_amt=excluded.pct_amt, turnover=excluded.turnover",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


# ── 增量更新（单只） ──────────────────────────────────────────────────────────
def update_one(code: str, progress: dict[str, str] | None = None,
               today: str | None = None) -> tuple[int, str]:
    """增量拉单只：从 progress[code] 之后到今天。

    progress[code] 是已采到的最后日期（YYYYMMDD）。start 取 progress[code]+1 天，
    end 取今天。无 progress 时回退到 DEFAULT_START 全量回填。
    返回 (新增行数, msg)。
    """
    if progress is None:
        progress = load_progress()
    if today is None:
        today = dt.date.today().strftime("%Y%m%d")
    last = progress.get(code)
    if last:
        # +1 天，避免重采 progress[code] 当天（PK 上 upsert 也幂等，但省一次请求）
        d = dt.datetime.strptime(last, "%Y%m%d").date() + dt.timedelta(days=1)
        start = d.strftime("%Y%m%d")
    else:
        start = DEFAULT_START
    if start > today:
        return 0, f"up-to-date (last={last})"
    rows, msg = fetch_one(code, start, today)
    if not rows:
        return 0, msg
    n = upsert_rows(rows)
    # 更新进度：取本次拉的最后一行日期
    new_last = max(r[1] for r in rows)
    progress[code] = new_last
    return n, f"ok +{n} (last={new_last})"


# ── 批量 ──────────────────────────────────────────────────────────────────────
def run_batch(codes: list[str], *, incremental: bool = False,
              start_date: str = DEFAULT_START, save_every: int = 5,
              verbose: bool = True) -> dict:
    """批量拉取。incremental=True 走 update_one（只拉最新日），否则全量回填。

    防封：每只前 _throttle()；遇 CooldownError → 保存进度 + 抛出（不硬刷）。
    进度每 save_every 只落盘一次（断电安全）。
    """
    init_db()
    progress = load_progress()
    today = dt.date.today().strftime("%Y%m%d")
    ok = fail = total_rows = empty_count = 0
    details: list[tuple] = []
    remaining = list(codes)
    i = 0
    while i < len(remaining):
        code = remaining[i]
        try:
            if incremental:
                n, msg = update_one(code, progress=progress, today=today)
            else:
                # 全量回填：若已有 progress 且 last==today-ish 则跳过
                last = progress.get(code)
                if last and last >= today:
                    i += 1
                    continue
                if last:
                    # 续传：从 last+1
                    d = dt.datetime.strptime(last, "%Y%m%d").date() + dt.timedelta(days=1)
                    start = d.strftime("%Y%m%d")
                else:
                    start = start_date
                rows, msg = fetch_one(code, start, today)
                if rows:
                    n = upsert_rows(rows)
                    progress[code] = max(r[1] for r in rows)
                else:
                    n = 0
            if n > 0 or "ok" in msg:
                ok += 1
                total_rows += n
                details.append((code, "ok", msg))
                if verbose and empty_count > 0:
                    print(f"  ... ({empty_count} 只无新数据)", flush=True)
                    empty_count = 0
                if verbose:
                    print(f"  [{i+1}/{len(remaining)}] {code}: {msg}", flush=True)
            else:
                fail += 1
                details.append((code, "fail", msg))
                empty_count += 1
                # 每100只 empty 汇总一次
                if verbose and empty_count > 0 and empty_count % 100 == 0:
                    print(f"  [{i+1}/{len(remaining)}] ... ({empty_count} 只无新数据，继续...)", flush=True)
        except CooldownError as e:
            # 封 IP：保存进度，汇报剩余，停
            save_progress(progress)
            remaining_after = remaining[i:]
            e.remaining_codes = remaining_after
            _write_cooldown_report(e, ok=ok, fail=fail, total_rows=total_rows,
                                   processed=i)
            if verbose:
                print(f"\n!! COOLDOWN: {e}. 已采 {i}/{len(remaining)}，"
                      f"剩余 {len(remaining_after)} 待采。进度已保存。", flush=True)
            raise
        except Exception as e:  # noqa: BLE001  其它错误记 fail 不中断
            fail += 1
            details.append((code, "fail", f"{type(e).__name__}: {str(e)[:150]}"))
            if verbose:
                print(f"  [{i+1}/{len(remaining)}] {code}: ERR {type(e).__name__}: "
                      f"{str(e)[:150]}", flush=True)
        i += 1
        if i % save_every == 0:
            save_progress(progress)
    save_progress(progress)
    if verbose and empty_count > 0:
        print(f"  === 股票日线采集完成: {ok} 只有新数据, {fail} 只无新数据（含 {empty_count} 只 empty）===", flush=True)
    return {"ok": ok, "fail": fail, "total_rows": total_rows,
            "processed": len(codes), "details": details}


def _write_cooldown_report(err: CooldownError, *, ok: int, fail: int,
                           total_rows: int, processed: int) -> None:
    """封 IP 后写剩余待采报告，便于恢复后续跑。"""
    lines = [
        f"# stock_daily cooldown report @ {dt.datetime.now().isoformat()}",
        f"# reason: {err}",
        f"# last_code: {err.last_code}",
        f"# processed: {processed}  ok: {ok}  fail: {fail}  rows: {total_rows}",
        f"# remaining ({len(err.remaining_codes)}):",
    ]
    lines.extend(err.remaining_codes)
    COOLDOWN_LOG_PATH.write_text("\n".join(lines), encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────────────────
def _cli(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[1]
    init_db()

    if cmd == "codes":
        codes = fetch_stock_codes(force_refresh=True)
        print(f"fetched {len(codes)} codes -> {CODES_CACHE_PATH}")
        print("sample:", codes[:3], "...", codes[-3:])
        return 0

    if cmd == "stats":
        conn = get_conn()
        n_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM stock_daily_raw").fetchone()[0]
        n_rows = conn.execute("SELECT COUNT(*) FROM stock_daily_raw").fetchone()[0]
        dmin = conn.execute("SELECT MIN(date) FROM stock_daily_raw").fetchone()[0]
        dmax = conn.execute("SELECT MAX(date) FROM stock_daily_raw").fetchone()[0]
        conn.close()
        prog = load_progress()
        print(f"stock_daily_raw: {n_codes} codes, {n_rows} rows, "
              f"date range {dmin}..{dmax}")
        print(f"progress.json: {len(prog)} codes tracked")
        return 0

    if cmd == "one":
        if len(argv) < 3:
            print("usage: one CODE [START]"); return 1
        code = argv[2]
        start = argv[3] if len(argv) > 3 else DEFAULT_START
        end = dt.date.today().strftime("%Y%m%d")
        try:
            rows, msg = fetch_one(code, start, end)
        except CooldownError as e:
            print(f"!! COOLDOWN: {e} (last_code={e.last_code}). 停 30min 再重跑。")
            return 2
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
        try:
            n, msg = update_one(code)
        except CooldownError as e:
            print(f"!! COOLDOWN: {e} (last_code={e.last_code}). 停 30min 再重跑。")
            return 2
        prog = load_progress()
        save_progress(prog)
        print(f"{code}: {msg}")
        return 0

    if cmd == "full":
        start = DEFAULT_START
        limit = None
        for a in argv[2:]:
            if a.startswith("--start="):
                start = a.split("=", 1)[1]
            elif a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
        codes = fetch_stock_codes()
        prog = load_progress()
        # 跳过已采到今天的（增量时仍跑 update_one 兜底）
        today = dt.date.today().strftime("%Y%m%d")
        todo = [c for c in codes if prog.get(c, "") < today]
        if limit:
            todo = todo[:limit]
        print(f"full: {len(todo)}/{len(codes)} to fetch (start={start}), "
              f"{len(codes)-len(todo)} already up-to-date")
        try:
            res = run_batch(todo, incremental=False, start_date=start, verbose=True)
            print(f"\n=== full done: ok={res['ok']} fail={res['fail']} "
                  f"rows={res['total_rows']} ===")
        except CooldownError as e:
            print(f"\n=== COOLDOWN: {e}. 剩余 {len(e.remaining_codes)} 待采 ===")
            return 2
        return 0

    if cmd == "update":
        limit = None
        for a in argv[2:]:
            if a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
        codes = fetch_stock_codes()
        if limit:
            codes = codes[:limit]
        print(f"update: {len(codes)} codes incremental")
        try:
            res = run_batch(codes, incremental=True, verbose=True)
            print(f"\n=== update done: ok={res['ok']} fail={res['fail']} "
                  f"rows={res['total_rows']} ===")
        except CooldownError as e:
            print(f"\n=== COOLDOWN: {e}. 剩余 {len(e.remaining_codes)} 待采 ===")
            return 2
        return 0

    print(f"unknown command: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
