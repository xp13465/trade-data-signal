#!/usr/bin/env python3
"""collect_fof_nav.py - #333 批1: FOF/QDII 净值独立采集器(方案 A, 止漏核心)。

根因(详见 docs/ops/333-fix-plan.md):
  app/collector/public_fund.py:fetch_daily_nav 用东财每日快照表(只最新 2 日列)+ 只写
  target_date 单日 + 次新列只喂 prev_unit_nav;FOF/QDII T+1/T+2 跨日发布,采集时当日列空
  → 写 NULL,次日 target_date 滚到 T+1,FOF 的 T 日净值落进次新列只成 prev_unit_nav,
  永不作为 T 日 unit_nav 落行。无回填(COALESCE 只保留非空)。

本采集器(止漏, 不改 fetch_daily_nav):
  - 走天天基金 lsjz 历史 API(api.fund.eastmoney.com/f10/lsjz, 带 Referer)补近 7 自然日净值。
  - 只选 fund_basic.fund_type LIKE 'FOF%' OR 'QDII%'。
  - 只补「缺行 or NULL」, 不覆盖已有非空(COALESCE(库值, 新值) = 库值非空保留库值)。
  - 单只失败不中断; 限速 0.3s/只防 WAF; 幂等(重跑只补 NULL, 天然断点续跑)。
  - 原子写: 每只一个 transaction。

入口: python -m scripts.collect_fof_nav [--days N] [--limit N] [--dry-run]
  --days   拉 lsjz 的近 N 自然日(默认 7, 覆盖 T-1/T-2 + 周末)
  --limit  只跑前 N 只(调试/小样)
  --dry-run 只拉不写

时点(云上 timer): 21:10 交易日(21:00 backfill-evening 写 sentiment.db 不撞同库,
  21:20 futures 写期货不撞; public_fund.db 写入只 16:20/17:00 daily + 03:00 quarterly)。
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # cloud 无 certifi 时用系统 CA
    _SSL_CTX = ssl.create_default_context()

# 复用 public_fund 的 DB 连接/schema/锁(§6.5 第 2 层: 库里已有不重写)
from app.collector.public_fund import get_conn, init_db, _acquire_lock, _safe_float

LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"
REFERER = "https://fundf10.eastmoney.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
REQ_TIMEOUT = 15  # 单只请求上限(秒)
RATE_LIMIT = 0.3  # 每只间隔(秒, 防 WAF)
SELECT_SQL = (
    "SELECT fund_code, fund_name, fund_type FROM fund_basic "
    "WHERE fund_type LIKE 'FOF%' OR fund_type LIKE 'QDII%' "
    "ORDER BY fund_code"
)
# 只补 NULL/缺行: COALESCE(库值, 新值) = 库值非空保留库值, 新值只填空位。
# 与 fetch_daily_nav(public_fund.py:960-969) 同口径, 永不覆盖非空。
UPSERT_SQL = (
    "INSERT INTO fund_daily_nav"
    "(date, fund_code, fund_name, unit_nav, acc_nav, prev_unit_nav, nav_change_pct) "
    "VALUES (?,?,?,?,?,?,?) "
    "ON CONFLICT(date, fund_code) DO UPDATE SET "
    "fund_name      = COALESCE(fund_daily_nav.fund_name,      excluded.fund_name), "
    "unit_nav       = COALESCE(fund_daily_nav.unit_nav,       excluded.unit_nav), "
    "acc_nav        = COALESCE(fund_daily_nav.acc_nav,        excluded.acc_nav), "
    "prev_unit_nav  = COALESCE(fund_daily_nav.prev_unit_nav,  excluded.prev_unit_nav), "
    "nav_change_pct = COALESCE(fund_daily_nav.nav_change_pct, excluded.nav_change_pct)"
)


def fetch_lsjz(fund_code: str, start_date: str, end_date: str) -> list[dict]:
    """拉 lsjz 历史 API, 返回 [{'date','unit_nav','acc_nav','pct','prev_unit'}, ...]。

    start/end = YYYY-MM-DD。返回按日期降序(API 原序), prev_unit 取下一条(更早一日)的 DWJZ。
    """
    url = (
        f"{LSJZ_URL}?fundCode={fund_code}&pageIndex=1&pageSize=20"
        f"&startDate={start_date}&endDate={end_date}"
    )
    req = urllib.request.Request(
        url, headers={"Referer": REFERER, "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=REQ_TIMEOUT, context=_SSL_CTX) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not data or data.get("ErrCode") not in (0, None):
        raise RuntimeError(f"lsjz ErrCode={data.get('ErrCode')} Msg={data.get('ErrMsg')}")
    rows = (data.get("Data") or {}).get("LSJZList") or []
    out: list[dict] = []
    for i, r in enumerate(rows):
        fsrq = str(r.get("FSRQ", "")).strip()  # 2026-10-30
        if not fsrq:
            continue
        d = fsrq.replace("-", "")  # 20261030
        unit = _safe_float(r.get("DWJZ"))
        acc = _safe_float(r.get("LJJZ"))
        pct = _safe_float(r.get("JZZZL"))
        # prev_unit = 列表里下一条(更早一日)的单位净值(API 按日期降序)
        prev_unit = None
        if i + 1 < len(rows):
            prev_unit = _safe_float(rows[i + 1].get("DWJZ"))
        out.append(
            {
                "date": d,
                "fund_code": fund_code,
                "unit_nav": unit,
                "acc_nav": acc,
                "prev_unit_nav": prev_unit,
                "nav_change_pct": pct,
            }
        )
    return out


def collect(days: int = 7, limit: int | None = None, dry_run: bool = False) -> int:
    """主流程。返回写入行数。"""
    init_db()  # 幂等(确保表存在)
    if not _acquire_lock(nonblock=True, lock_name="public_fund"):
        print("[fof_nav] WARN public_fund.lock 被占, 跳过(防与 daily/quarterly 并发写同库)",
              flush=True)
        return 0
    conn = get_conn()
    funds = list(conn.execute(SELECT_SQL))
    if limit:
        funds = funds[:limit]
    end = date.today()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    print(f"[fof_nav] {len(funds)} 只 FOF/QDII, 拉近{days}日({start_str}~{end_str}) "
          f"dry_run={dry_run}", flush=True)
    total_written = 0
    ok = 0
    fail = 0
    t0 = time.time()
    for idx, (fund_code, fund_name, fund_type) in enumerate(funds, 1):
        try:
            rows = fetch_lsjz(fund_code, start_str, end_str)
            if not rows:
                fail += 1
                continue
            if not dry_run:
                params = [
                    (
                        r["date"], r["fund_code"], fund_name,
                        r["unit_nav"], r["acc_nav"], r["prev_unit_nav"],
                        r["nav_change_pct"],
                    )
                    for r in rows
                ]
                conn.executemany(UPSERT_SQL, params)
                conn.commit()  # 每只一个原子事务
            total_written += len(rows)
            ok += 1
        except Exception as e:
            fail += 1
            print(f"[fof_nav] FAIL {fund_code} {fund_type}: {e}", flush=True)
        if idx % 50 == 0:
            print(f"[fof_nav] 进度 {idx}/{len(funds)} ok={ok} fail={fail} "
                  f"written={total_written} {time.time()-t0:.0f}s", flush=True)
        time.sleep(RATE_LIMIT)
    conn.close()
    print(f"[fof_nav] 完成 ok={ok} fail={fail} written={total_written} "
          f"{time.time()-t0:.0f}s", flush=True)
    return total_written


def main() -> int:
    ap = argparse.ArgumentParser(description="#333 批1 FOF/QDII 净值采集器")
    ap.add_argument("--days", type=int, default=7, help="拉近 N 自然日(默认 7)")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 只(调试)")
    ap.add_argument("--dry-run", action="store_true", help="只拉不写")
    args = ap.parse_args()
    n = collect(days=args.days, limit=args.limit, dry_run=args.dry_run)
    print(f"[fof_nav] return written={n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
