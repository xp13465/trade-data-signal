"""ETF 权重龙头个股历史日线补采脚本(Step2, 独立数据文件防污染)。

目的: 为 ETF 权重 TOP1-3 个股去重集合补采 2019 至今历史日线(前复权),
     落独立库 data/stock_top_weights.db(stock_top_daily 表),
     不覆盖/不混入生产 stock_daily.db(raw 表), 不动生产数据。

依赖:
  - docs/kelly/backtest-ai/etf-weight-leader/data/etf_hold_verify_result.json
    (Step1 产物, 含 a_stock_codes 去重集合)
  - baostock 前复权日线(adjustflag="2"), 复用 baostock_daily 只读工具函数

输出:
  - data/stock_top_weights.db 独立库 stock_top_daily 表
  - docs/kelly/backtest-ai/etf-weight-leader/data/stock_backfill_progress.json(断点续采)

复现命令:
  .venv/bin/python docs/kelly/backtest-ai/etf-weight-leader/scripts/stock_daily_backfill.py
"""
import os
os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")
import sys
import json
import time
import random
from pathlib import Path

PROJ_ROOT = Path(__file__).absolute().parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(PROJ_ROOT))

import sqlite3
import baostock as bs

# 复用生产只读工具函数(import 无副作用; fetch/upsert 独立实现不碰 baostock_daily_raw)
from app.collector.baostock_daily import (
    _ensure_login, _throttle, _reconnect_with_retry,
    to_baostock_code, _to_ymd, _norm_date,
)

SCRIPT_DIR = Path(__file__).absolute().parent
RESULT_PATH = SCRIPT_DIR.parent / "data" / "etf_hold_verify_result.json"
PROGRESS_PATH = SCRIPT_DIR.parent / "data" / "stock_backfill_progress.json"
DB_PATH = PROJ_ROOT / "data" / "stock_top_weights.db"

START = "2019-01-01"   # 个股法回测起点(与方案文档一致, 2019Q1持仓快照后)
FIELDS = "date,code,open,high,low,close,volume,amount,turn,pctChg,preclose"

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_top_daily (
  code TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL,
  volume REAL, amount REAL,
  turnover REAL,
  pct_change REAL,
  preclose REAL,
  PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_stock_top_code ON stock_top_daily(code);
CREATE INDEX IF NOT EXISTS idx_stock_top_date ON stock_top_daily(date);
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def fetch_adjusted(code: str, start: str, end: str) -> list[tuple]:
    """拉单只股票前复权日线(adjustflag="2"), 返回 (code,date,open,high,low,close,
    volume,amount,turn,pctChg,preclose) 元组列表。不复权用 adjustflag="3" 可切。"""
    bs_code = to_baostock_code(code)
    if bs_code is None:
        return []
    sd, ed = _to_ymd(start), _to_ymd(end)
    _ensure_login()
    last_err = ""
    for attempt in range(2):
        _throttle()
        try:
            rs = bs.query_history_k_data_plus(bs_code, FIELDS, start_date=sd,
                                              end_date=ed, frequency="d", adjustflag="2")
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            if attempt == 0:
                try:
                    _reconnect_with_retry()
                except Exception as re:
                    return []
                continue
            return []
        if rs.error_code != "0":
            last_err = f"bs {rs.error_code}"
            if attempt == 0:
                try:
                    _reconnect_with_retry()
                except Exception:
                    return []
                continue
            return []
        rows = []
        while rs.error_code == "0" and rs.next():
            d = rs.get_row_data()
            if not d[0]:
                continue
            rows.append((code, _norm_date(d[0]),
                         _f(d[2]), _f(d[3]), _f(d[4]), _f(d[5]),
                         _f(d[6]), _f(d[7]), _f(d[8]), _f(d[9]), _f(d[10])))
        return rows
    return []


def upsert_rows(rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn = get_conn()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO stock_top_daily "
            "(code,date,open,high,low,close,volume,amount,turnover,pct_change,preclose) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def _f(s):
    try:
        return float(s) if s not in (None, "") else None
    except (ValueError, TypeError):
        return None


def main():
    if not RESULT_PATH.exists():
        print(f"[E] 缺 Step1 结果: {RESULT_PATH}", flush=True)
        return
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    codes = result["top_stock_universe"]["a_stock_codes"]
    print(f"[I] TOP1-3 A股去重集合 {len(codes)} 只", flush=True)

    init_db()
    progress = {}
    if PROGRESS_PATH.exists():
        progress = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))

    today = time.strftime("%Y-%m-%d")
    ok = fail = 0
    for i, code in enumerate(codes):
        if code in progress:
            ok += 1
            continue
        rows = fetch_adjusted(code, START, today)
        if rows:
            n = upsert_rows(rows)
            progress[code] = {"rows": n, "last_date": rows[-1][1]}
            ok += 1
            print(f"[I] {i+1}/{len(codes)} {code}: {n} 行 {rows[0][1]}~{rows[-1][1]}", flush=True)
        else:
            progress[code] = {"rows": 0, "note": "fetch fail/empty"}
            fail += 1
            print(f"[W] {i+1}/{len(codes)} {code}: 拉取失败/空", flush=True)
        if (i + 1) % 10 == 0:
            PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False))
        time.sleep(0.3 + random.uniform(0, 0.2))

    PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False))
    print(f"\n[I] 完成: ok={ok} fail={fail} 总数={len(codes)}", flush=True)
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM stock_top_daily").fetchone()[0]
    print(f"[I] stock_top_daily 总行数: {n}, db: {DB_PATH}", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
