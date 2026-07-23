"""TASK-D3: BaoStock 全 A 股日线（1990-2026 全段，D1 封锁期替代主力源）。

设计要点
========
- **背景**：D1 用 akshare `stock_zh_a_hist`（东财 push2his）采 2016-2026 全 A 股日线，因
  东财 IP 临时封锁（F2 触发）尚未采全量。BaoStock 走自己服务（baostock.com，非东财 HTTP），
  不受东财封锁影响。本任务用 BaoStock 采**全段（1990-2026）全 A 股日线**作封锁期间替代
  主力数据源，采数顺序优先近 10 年 2016-2026（D2 急需），再补 1990-2015 老段。D1 akshare
  解封后采 2016-2026 作交叉校验源（阶段2，待 D1 数据采全后做）。

- **存储**：独立表 `baostock_daily_raw`，与 D1 的 `stock_daily_raw` 同库不同表
  （`data/stock_daily.db`），校验时 JOIN 对比。理由：清晰隔离，不污染 D1；同库便于跨表
  SQL。schema 与 D1 对齐（code/date/open/high/low/close/volume/amount/turnover/pct_change/
  preclose），PK(code,date) + 双索引。BaoStock 不返振幅/涨跌额，故缺 amplitude/pct_amt
  （校验时只比对共有字段；D2 算涨停价用 pct_change 已够）。

- **code 转换**：D1 缓存的 5527 只 6 位代码 → BaoStock 格式 sh.600000/sz.000001。
  - 6xxxxx（含 688 科创板）→ sh.6xxxxx
  - 0xxxxx / 2xxxxx / 3xxxxx（创业板）→ sz.xxxxxx
  - 920xxx / 8xxxxx / 4xxxxx（北交所）→ BaoStock 不支持，跳过 + 记 `data/baostock_skipped_bj.txt`
  - 9xxxxx（沪 B 股，非北交所）→ sh.9xxxxx（BaoStock 支持，但 D1 stock_info_a_code_name
    不含 B 股，故实际不出现；保险起见归 sh）

- **进度持久化**：`data/baostock_progress.json` = {code: {"r": yyyymmdd, "o": yyyymmdd}}。
  r=recent 段（2016-2026）已采到的最后日期；o=old 段（1990-2015）已采到的最后日期。
  断点续传：跑前读它，跳过已采段；每 N 只落盘一次。

- **限速**：BaoStock 单连接串行（login 后用同一连接），实测无显著限速（5 只<2s），
  仍加 0.3s 节流 + 0.1s jitter 防服务端风控。遇错误保存进度 + 记 fail 不中断（BaoStock
  无 IP 封锁概念，错误多为单 code 数据问题）。

- **CLI**：`python -m app.collector.baostock_daily <command>`
    recent [--limit N]           近 10 年段（2016-2026）全 A，D2 急需
    old [--limit N]              老段（1990-2015）补采
    full [--limit N]             全段（先 recent 后 old）
    update [--limit N]           增量所有 code（只拉 r 段 progress 之后到今天）
    one CODE [--start DATE]      单只全量（默认 19900101 到今天）
    upone CODE                   单只增量（r 段增量）
    stats                        库统计
    codes                        重建 code 列表缓存（复用 D1 的）

阶段2（BaoStock vs akshare 重叠段交叉校验）待 D1 akshare 数据采全后做，写 NOTES.md。
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

# 必须先 import base，应用 trust_env=False 全局补丁（BaoStock 走自己服务，也防 Clash 代理）
from . import base  # noqa: F401
import baostock as bs

# ── 路径 ──────────────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).absolute().parent.parent.parent / "data"
STOCK_DB_PATH = _DATA_DIR / "stock_daily.db"          # 与 D1 同库不同表
PROGRESS_PATH = _DATA_DIR / "baostock_progress.json"
CODES_CACHE_PATH = _DATA_DIR / "stock_codes.json"     # 复用 D1 的 code 列表缓存
SKIPPED_BJ_LOG = _DATA_DIR / "baostock_skipped_bj.txt"

# 段定义
RECENT_START = "2016-01-01"     # 近 10 年段起点（D1 同口径）
OLD_START = "1990-01-01"        # 老段起点（BaoStock 沪市从 1990-12-19 起）
OLD_END = "2015-12-31"          # 老段终点
TODAY = lambda: dt.date.today().strftime("%Y-%m-%d")  # noqa: E731

# 限速：BaoStock 走自己服务（非东财 HTTP），无 IP 封锁风险，0.1s 节流防服务端风控即可。
# 实测单只 10 年日线 ~6.5s（BaoStock 服务端 2.2ms/row），节流非瓶颈。
BS_MIN_INTERVAL = 0.1
_last_call = [0.0]
_logged_in = [False]

# 网络类错误码（baostock/common/contants.py L147-154）——出现即视为连接断开，需重连。
# 实证：baostock/util/socketutil.py 的 send_msg 断线时 try/except 抓异常后隐式 return None，
# query_history_k_data_plus 收到 None 返 BSERR_RECVSOCK_FAIL("10002007")。socket 不会自动重建，
# 后续 query 全 fail（2026-07-23 全量补采断链根因）。
_NETWORK_ERROR_CODES = frozenset({
    "10002001",  # SOCKET_ERR
    "10002002",  # CONNECT_FAIL
    "10002003",  # CONNECT_TIMEOUT
    "10002004",  # RECVCONNECTION_CLOSED（断线典型）
    "10002005",  # SENDSOCK_FAIL
    "10002006",  # SENDSOCK_TIMEOUT
    "10002007",  # RECVSOCK_FAIL（断线典型）
    "10002008",  # RECVSOCK_TIMEOUT
})
# 重连参数：3 次重试，每次间隔 2 秒（避免死循环 + 给服务端恢复时间）。
_RECONNECT_MAX_RETRIES = 3
_RECONNECT_INTERVAL = 2.0  # 秒


def _throttle():
    wait = BS_MIN_INTERVAL - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.02, 0.08))
    _last_call[0] = time.time()


def _ensure_login(*, force_reconnect: bool = False) -> None:
    """BaoStock 全局 login。

    - 默认幂等（_logged_in[0]=True 时不重复 login），保持原行为
    - force_reconnect=True：强制 _logout 清旧 socket 再 login，
      用于断线后重建连接（实证 bs.login 每次都重建新 socket，id 不同）
    """
    if force_reconnect:
        _logout()
    if not _logged_in[0]:
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login failed: {lg.error_code} {lg.error_msg}")
        _logged_in[0] = True


def _reconnect_with_retry(max_retries: int = _RECONNECT_MAX_RETRIES,
                          interval: float = _RECONNECT_INTERVAL) -> None:
    """断线重连：max_retries 次 logout+login，每次间隔 interval 秒。

    bs.login 会重建 socket（实证：每次调用都 setattr 新 socket 到 context），
    故先 _logout 标 _logged_in[0]=False，再 _ensure_login 触发 login。
    全失败才 raise RuntimeError，调用方决定是否记 fail。
    """
    last_err = ""
    for attempt in range(1, max_retries + 1):
        try:
            _logout()  # 清旧 socket（_logged_in=False）
            _ensure_login()  # 触发新 login 重建 socket
            return  # 成功立即返回
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
            print(f"  [baostock reconnect] attempt {attempt}/{max_retries} "
                  f"failed: {last_err}", flush=True)
            if attempt < max_retries:
                time.sleep(interval)
    raise RuntimeError(
        f"baostock reconnect failed after {max_retries} retries: {last_err}")


def _logout():
    if _logged_in[0]:
        try:
            bs.logout()
        except Exception:  # noqa: BLE001
            pass
        _logged_in[0] = False


# ── DB ────────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS baostock_daily_raw (
  code TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL,
  turnover REAL,       -- 换手率 %（BaoStock turn）
  pct_change REAL,     -- 涨跌幅 %（BaoStock pctChg）
  preclose REAL,       -- 昨收（BaoStock preclose，用于涨停价判定）
  PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_baostock_date ON baostock_daily_raw(date);
CREATE INDEX IF NOT EXISTS idx_baostock_code ON baostock_daily_raw(code);
"""


def get_conn() -> sqlite3.Connection:
    STOCK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STOCK_DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    # 与 mootdx/stock_daily 并发写同库不同表时写锁串行化自动重试。
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# ── 进度持久化 ────────────────────────────────────────────────────────────────
def load_progress() -> dict:
    """{code: {"r": yyyymmdd, "o": yyyymmdd}}。"""
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_progress(progress: dict) -> None:
    """原子写：先写临时文件再 rename。"""
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=None, sort_keys=True),
                   encoding="utf-8")
    tmp.replace(PROGRESS_PATH)


# ── code 列表 + 转换 ──────────────────────────────────────────────────────────
def fetch_stock_codes(force_refresh: bool = False) -> list[str]:
    """复用 D1 的 code 列表（5527 只 6 位代码）。D1 用 stock_info_a_code_name（东财
    dataapi，非 push2his，未被反爬封）。无缓存时调 D1 的 fetch_stock_codes 重建。"""
    if not force_refresh and CODES_CACHE_PATH.exists():
        try:
            data = json.loads(CODES_CACHE_PATH.read_text(encoding="utf-8"))
            codes = data.get("codes") if isinstance(data, dict) else data
            if codes:
                return codes
        except (json.JSONDecodeError, OSError):
            pass
    # 委托 D1 重建缓存
    from . import stock_daily as d1
    return d1.fetch_stock_codes(force_refresh=True)


def to_baostock_code(code: str) -> str | None:
    """6 位代码 → BaoStock 格式（sh.600000 / sz.000001）。北交所返 None（不支持）。"""
    if not code or len(code) != 6 or not code.isdigit():
        return None
    # 北交所：920xxx / 8xxxxx / 4xxxxx
    if code.startswith("920") or code.startswith("8") or code.startswith("4"):
        return None
    # 沪市：6xxxxx（主板 + 688 科创板） + 9xxxxx（B 股，D1 列表不含但保险归 sh）
    if code.startswith("6") or code.startswith("9"):
        return f"sh.{code}"
    # 深市：0xxxxx（主板） / 2xxxxx（B 股） / 3xxxxx（创业板）
    if code.startswith("0") or code.startswith("2") or code.startswith("3"):
        return f"sz.{code}"
    return None


# ── 单只拉取 ──────────────────────────────────────────────────────────────────
def _norm_date(s) -> str:
    """'2016-01-04' → '20160104'。"""
    if hasattr(s, "strftime"):
        try:
            return s.strftime("%Y%m%d")
        except (ValueError, AttributeError):
            pass
    return str(s).replace("-", "").replace("/", "")


def _f(v):
    """转 float；NaN/None/'' → None（不入库）。BaoStock 返字符串。"""
    if v is None or v == "" or v == "None":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg,preclose"


def fetch_one(code: str, start_date: str, end_date: str) -> tuple[list[tuple], str]:
    """拉单只股票日线。返回 (rows, msg)。

    code = 6 位代码（如 '600519'），内部转 BaoStock 格式。
    start_date / end_date = 'YYYY-MM-DD' 或 'YYYYMMDD'（统一转 YYYY-MM-DD 给 BaoStock）。
    rows = [(code_6digit, date_yyyymmdd, open, high, low, close, volume, amount,
             turnover, pct_change, preclose), ...]

    BaoStock adjustflag="3" 不复权（与 D1 一致，保证涨停价判定准确）。

    断线重连（2026-07-23 修复）：query 抛异常或返网络类错误码时，调
    _reconnect_with_retry 重建 socket 后重试一次。第二次仍失败才返回 fail。
    """
    bs_code = to_baostock_code(code)
    if bs_code is None:
        return [], "skip bj (BaoStock unsupported)"

    # BaoStock 要 'YYYY-MM-DD' 格式
    sd = _to_ymd(start_date)
    ed = _to_ymd(end_date)

    _ensure_login()

    # 2 次尝试：attempt 0=初次，attempt 1=重连后重试
    reconnect_err = ""
    for attempt in range(2):
        _throttle()
        try:
            rs = bs.query_history_k_data_plus(
                bs_code, FIELDS,
                start_date=sd, end_date=ed,
                frequency="d", adjustflag="3",
            )
        except Exception as e:  # noqa: BLE001  socket 异常（断线典型）
            reconnect_err = f"{type(e).__name__}: {str(e)[:150]}"
            if attempt == 0:
                try:
                    _reconnect_with_retry()
                except Exception as re:  # noqa: BLE001
                    return [], f"fetch err: {reconnect_err} (reconnect failed: {str(re)[:80]})"
                continue  # 重试
            return [], f"fetch err: {reconnect_err} (after reconnect)"

        if rs.error_code != "0":
            # 网络类错误码 -> 断线，重连后重试
            if rs.error_code in _NETWORK_ERROR_CODES and attempt == 0:
                reconnect_err = f"bs err {rs.error_code}: {rs.error_msg}"
                try:
                    _reconnect_with_retry()
                except Exception as re:  # noqa: BLE001
                    return [], f"{reconnect_err} (reconnect failed: {str(re)[:80]})"
                continue  # 重试
            return [], f"bs err {rs.error_code}: {rs.error_msg}"

        rows = []
        while (rs.error_code == "0") & rs.next():
            d = rs.get_row_data()
            # d = [date, code, open, high, low, close, volume, amount, turn, pctChg, preclose]
            date_str = _norm_date(d[0]) if d[0] else None
            if not date_str:
                continue
            row = (code, date_str,
                   _f(d[2]), _f(d[3]), _f(d[4]), _f(d[5]),
                   _f(d[6]), _f(d[7]),
                   _f(d[8]), _f(d[9]), _f(d[10]))
            rows.append(row)
        return rows, "ok" if rows else "empty"

    # 理论不可达（for 内 attempt 0/1 都会 return）
    return [], f"unexpected fetch_one exit (last reconnect err: {reconnect_err})"


def _to_ymd(s: str) -> str:
    """'20160101' / '2016-01-01' → '2016-01-01'（BaoStock 要这格式）。"""
    s = str(s).replace("-", "").replace("/", "")
    if len(s) != 8:
        return s
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def upsert_rows(rows: list[tuple]) -> int:
    """批量 upsert 到 baostock_daily_raw。"""
    if not rows:
        return 0
    conn = get_conn()
    conn.executemany(
        "INSERT INTO baostock_daily_raw "
        "(code, date, open, high, low, close, volume, amount, "
        "turnover, pct_change, preclose) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(code, date) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
        "volume=excluded.volume, amount=excluded.amount, turnover=excluded.turnover, "
        "pct_change=excluded.pct_change, preclose=excluded.preclose",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


# ── 段拉取（recent / old） ────────────────────────────────────────────────────
def _fetch_segment(code: str, seg: str, today_ymd: str) -> tuple[int, str, str | None]:
    """拉单只的某段。seg='r' → recent(2016-2026)；seg='o' → old(1990-2015)。
    返回 (新增行数, msg, last_date_or_None)。"""
    if seg == "r":
        start, end = RECENT_START, today_ymd
    else:
        start, end = OLD_START, OLD_END
    rows, msg = fetch_one(code, start, end)
    if not rows:
        return 0, msg, None
    n = upsert_rows(rows)
    last = max(r[1] for r in rows)
    return n, "ok", last


def update_recent(code: str, progress: dict, today_ymd: str) -> tuple[int, str]:
    """recent 段增量：从 progress[code]['r'] 之后到今天。无 progress 则全量回填 recent 段。"""
    bs_code = to_baostock_code(code)
    if bs_code is None:
        return 0, "skip bj"
    entry = progress.get(code, {})
    last_r = entry.get("r")
    if last_r:
        # +1 天
        d = dt.datetime.strptime(last_r, "%Y%m%d").date() + dt.timedelta(days=1)
        start = d.strftime("%Y-%m-%d")
    else:
        start = RECENT_START
    end = today_ymd
    if start.replace("-", "") > end.replace("-", ""):
        return 0, f"up-to-date (r={last_r})"
    rows, msg = fetch_one(code, start, end)
    if not rows:
        return 0, msg
    n = upsert_rows(rows)
    new_last = max(r[1] for r in rows)
    entry["r"] = new_last
    progress[code] = entry
    return n, f"ok +{n} (r={new_last})"


# ── 批量 ──────────────────────────────────────────────────────────────────────
def run_segment(codes: list[str], seg: str, *, save_every: int = 10,
                verbose: bool = True) -> dict:
    """批量拉某段。seg='r' 或 'o'。

    跳过北交所 code（记 SKIPPED_BJ_LOG）；跳过 progress 已标该段 done 的 code。
    每 save_every 只落盘一次进度。
    """
    init_db()
    progress = load_progress()
    today_ymd = TODAY()
    ok = fail = skip_bj = skip_done = total_rows = 0
    details: list[tuple] = []
    bj_skipped: list[str] = []

    for i, code in enumerate(codes):
        bs_code = to_baostock_code(code)
        if bs_code is None:
            skip_bj += 1
            bj_skipped.append(code)
            details.append((code, "skip_bj", ""))
            if verbose:
                print(f"  [{i+1}/{len(codes)}] {code}: skip bj", flush=True)
            continue

        # 跳过该段已采的
        entry = progress.get(code, {})
        if seg == "r" and entry.get("r"):
            skip_done += 1
            continue
        if seg == "o" and entry.get("o"):
            skip_done += 1
            continue

        try:
            n, msg, last = _fetch_segment(code, seg, today_ymd)
            if n > 0 or "ok" in msg or "empty" in msg:
                ok += 1
                total_rows += n
                # 标 progress
                entry = progress.get(code, {})
                if last:
                    entry[seg] = last
                    progress[code] = entry
                details.append((code, "ok", msg))
                if verbose:
                    print(f"  [{i+1}/{len(codes)}] {code}: {msg} +{n} "
                          f"({seg}={last})", flush=True)
            else:
                fail += 1
                details.append((code, "fail", msg))
                if verbose:
                    print(f"  [{i+1}/{len(codes)}] {code}: FAIL {msg}", flush=True)
        except Exception as e:  # noqa: BLE001  单只错误不中断
            fail += 1
            details.append((code, "fail", f"{type(e).__name__}: {str(e)[:150]}"))
            if verbose:
                print(f"  [{i+1}/{len(codes)}] {code}: ERR {type(e).__name__}: "
                      f"{str(e)[:150]}", flush=True)

        if (i + 1) % save_every == 0:
            save_progress(progress)

    save_progress(progress)
    # 写北交所跳过列表
    if bj_skipped:
        SKIPPED_BJ_LOG.parent.mkdir(parents=True, exist_ok=True)
        existing = set()
        if SKIPPED_BJ_LOG.exists():
            existing = set(SKIPPED_BJ_LOG.read_text(encoding="utf-8").splitlines())
        all_bj = sorted(existing | set(bj_skipped))
        SKIPPED_BJ_LOG.write_text("\n".join(all_bj), encoding="utf-8")

    return {"ok": ok, "fail": fail, "skip_bj": skip_bj, "skip_done": skip_done,
            "total_rows": total_rows, "processed": len(codes),
            "details": details}


def run_update(codes: list[str], *, save_every: int = 10, verbose: bool = True) -> dict:
    """增量更新所有 code（recent 段增量）。"""
    init_db()
    progress = load_progress()
    today_ymd = TODAY()
    ok = fail = skip_bj = skip_done = total_rows = 0
    details: list[tuple] = []

    for i, code in enumerate(codes):
        bs_code = to_baostock_code(code)
        if bs_code is None:
            skip_bj += 1
            continue
        # 只对已 backfill recent 段的 code 增量（未 backfill 的由 recent 命令跑）
        entry = progress.get(code, {})
        if not entry.get("r"):
            skip_done += 1
            continue
        try:
            n, msg = update_recent(code, progress, today_ymd)
            if n > 0 or "ok" in msg:
                ok += 1
                total_rows += n
                details.append((code, "ok", msg))
                if verbose and n > 0:
                    print(f"  [{i+1}/{len(codes)}] {code}: {msg}", flush=True)
            else:
                # up-to-date 不算 fail
                if "up-to-date" in msg:
                    skip_done += 1
                else:
                    fail += 1
                    if verbose:
                        print(f"  [{i+1}/{len(codes)}] {code}: {msg}", flush=True)
        except Exception as e:  # noqa: BLE001
            fail += 1
            details.append((code, "fail", f"{type(e).__name__}: {str(e)[:150]}"))
            if verbose:
                print(f"  [{i+1}/{len(codes)}] {code}: ERR {type(e).__name__}: "
                      f"{str(e)[:150]}", flush=True)

        if (i + 1) % save_every == 0:
            save_progress(progress)

    save_progress(progress)
    return {"ok": ok, "fail": fail, "skip_bj": skip_bj, "skip_done": skip_done,
            "total_rows": total_rows, "processed": len(codes),
            "details": details}


def reconcile() -> int:
    """从 DB 实际数据重建 progress（修并行采数时 progress.json 可能的写覆盖）。

    也用于 turnover pipeline 跑前确保 progress 含全量 code：历史全量 backfill 若未
    跑完，progress 只含少数 code -> runner.run_update 的 todo 只含这些 code ->
    a_turnover_* 5项 缺 T 日数据角标滞后（2026-07-23 修复）。
    """
    conn = get_conn()
    # 每个 code 的 recent 段最大日期
    rows_r = conn.execute(
        "SELECT code, MAX(date) FROM baostock_daily_raw "
        "WHERE date >= '20160101' GROUP BY code").fetchall()
    # 每个 code 的 old 段最大日期
    rows_o = conn.execute(
        "SELECT code, MAX(date) FROM baostock_daily_raw "
        "WHERE date < '20160101' GROUP BY code").fetchall()
    conn.close()
    prog = load_progress()
    n_fix = 0
    for code, max_r in rows_r:
        entry = prog.get(code, {})
        if entry.get("r") != max_r:
            entry["r"] = max_r
            prog[code] = entry
            n_fix += 1
    for code, max_o in rows_o:
        entry = prog.get(code, {})
        if entry.get("o") != max_o:
            entry["o"] = max_o
            prog[code] = entry
            n_fix += 1
    save_progress(prog)
    print(f"reconcile: {n_fix} entries fixed, {len(prog)} codes total")
    return n_fix


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

    if cmd == "reconcile":
        reconcile()
        return 0

    if cmd == "stats":
        conn = get_conn()
        n_codes = conn.execute(
            "SELECT COUNT(DISTINCT code) FROM baostock_daily_raw").fetchone()[0]
        n_rows = conn.execute(
            "SELECT COUNT(*) FROM baostock_daily_raw").fetchone()[0]
        dmin = conn.execute(
            "SELECT MIN(date) FROM baostock_daily_raw").fetchone()[0]
        dmax = conn.execute(
            "SELECT MAX(date) FROM baostock_daily_raw").fetchone()[0]
        # 段分布
        n_recent = conn.execute(
            "SELECT COUNT(*) FROM baostock_daily_raw WHERE date >= '20160101'").fetchone()[0]
        n_old = conn.execute(
            "SELECT COUNT(*) FROM baostock_daily_raw WHERE date < '20160101'").fetchone()[0]
        conn.close()
        prog = load_progress()
        n_r_done = sum(1 for v in prog.values() if v.get("r"))
        n_o_done = sum(1 for v in prog.values() if v.get("o"))
        print(f"baostock_daily_raw: {n_codes} codes, {n_rows} rows, "
              f"date range {dmin}..{dmax}")
        print(f"  recent段(>=20160101): {n_recent} rows")
        print(f"  old段(<20160101): {n_old} rows")
        print(f"progress.json: {len(prog)} codes tracked "
              f"(r done={n_r_done}, o done={n_o_done})")
        if SKIPPED_BJ_LOG.exists():
            n_bj = len(SKIPPED_BJ_LOG.read_text(encoding="utf-8").splitlines())
            print(f"skipped bj: {n_bj} codes -> {SKIPPED_BJ_LOG.name}")
        return 0

    if cmd == "one":
        if len(argv) < 3:
            print("usage: one CODE [START]"); return 1
        code = argv[2]
        start = argv[3] if len(argv) > 3 else OLD_START
        end = TODAY()
        try:
            rows, msg = fetch_one(code, start, end)
        except Exception as e:  # noqa: BLE001
            print(f"!! ERR: {type(e).__name__}: {e}")
            return 2
        print(f"{code}: {msg}")
        if rows:
            n = upsert_rows(rows)
            prog = load_progress()
            entry = prog.get(code, {})
            new_last = max(r[1] for r in rows)
            if new_last >= "20160101":
                entry["r"] = new_last
            if new_last < "20160101" or len(rows) > 100:
                entry["o"] = new_last
            prog[code] = entry
            save_progress(prog)
            print(f"  upserted {n} rows, last={new_last}")
            print(f"  sample first: {rows[0]}")
            print(f"  sample last:  {rows[-1]}")
        return 0

    if cmd == "upone":
        if len(argv) < 3:
            print("usage: upone CODE"); return 1
        code = argv[2]
        prog = load_progress()
        n, msg = update_recent(code, prog, TODAY())
        save_progress(prog)
        print(f"{code}: {msg}")
        return 0

    # 批量命令：recent / old / full / update
    if cmd in ("recent", "old", "full", "update"):
        limit = None
        for a in argv[2:]:
            if a.startswith("--limit="):
                limit = int(a.split("=", 1)[1])
        codes = fetch_stock_codes()
        if limit:
            codes = codes[:limit]
        print(f"{cmd}: {len(codes)} codes" + (f" (limit={limit})" if limit else ""))

        try:
            if cmd == "recent":
                res = run_segment(codes, "r", verbose=True)
                print(f"\n=== recent done: ok={res['ok']} fail={res['fail']} "
                      f"skip_bj={res['skip_bj']} skip_done={res['skip_done']} "
                      f"rows={res['total_rows']} ===")
            elif cmd == "old":
                res = run_segment(codes, "o", verbose=True)
                print(f"\n=== old done: ok={res['ok']} fail={res['fail']} "
                      f"skip_bj={res['skip_bj']} skip_done={res['skip_done']} "
                      f"rows={res['total_rows']} ===")
            elif cmd == "full":
                print("--- phase 1: recent (2016-2026) ---")
                r1 = run_segment(codes, "r", verbose=True)
                print(f"\n=== recent done: ok={r1['ok']} fail={r1['fail']} "
                      f"rows={r1['total_rows']} ===")
                print("--- phase 2: old (1990-2015) ---")
                r2 = run_segment(codes, "o", verbose=True)
                print(f"\n=== old done: ok={r2['ok']} fail={r2['fail']} "
                      f"rows={r2['total_rows']} ===")
                print(f"\n=== full done: total rows={r1['total_rows']+r2['total_rows']} ===")
            elif cmd == "update":
                res = run_update(codes, verbose=True)
                print(f"\n=== update done: ok={res['ok']} fail={res['fail']} "
                      f"skip_bj={res['skip_bj']} skip_done={res['skip_done']} "
                      f"rows={res['total_rows']} ===")
        except KeyboardInterrupt:
            print("\n!! interrupted, progress saved")
            return 130
        finally:
            _logout()
        return 0

    print(f"unknown command: {cmd}\n{__doc__}")
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
