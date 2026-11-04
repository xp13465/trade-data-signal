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
    注: 方向与 fetch_daily_nav **相反**——fetch_daily_nav 用 COALESCE(新值, 库值)=新值非空优先
    用新值(可覆盖库值); 本采集器用 COALESCE(库值, 新值)=库值非空永不被覆盖(更保守, 止漏不踩踏)。
  - 跳过已填: 先查库中目标日期范围内已有非空 unit_nav 的 fund_code, 从待采列表排除,
    只对未填的发 API(解决"每轮重头跑→后段永不触达")。
  - 分批: 每轮最多采 BATCH_SIZE 只(默认 500, 可配), 剩余下轮续(配合跳过已填, 几轮覆盖 1796)。
  - 单只失败不中断; 限速 0.3s/只防 WAF(实测 50 只 0.3s 间隔零 429/零封, 见 docs/ops/333-fix-plan.md);
    幂等(重跑只补 NULL + 跳过已填, 天然断点续跑)。
  - 原子写: 每只一个 transaction。

入口: python -m scripts.collect_fof_nav [--days N] [--limit N] [--batch N] [--dry-run]
  --days   拉 lsjz 的近 N 自然日(默认 7, 覆盖 T-1/T-2 + 周末)
  --limit  只跑前 N 只(调试/小样, 优先于 --batch)
  --batch  每轮最多采 N 只(默认 500, 配合跳过已填分批续跑)
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
RATE_LIMIT = 0.3  # 每只间隔(秒, 防 WAF; 实测 50 只 0.3s 间隔零 429/零封, 见 docs/ops/333-fix-plan.md)
BATCH_SIZE = 500  # 每轮最多采 N 只(配合跳过已填分批续跑, 几轮覆盖 1796)

# 整批失败信号(#366/F01): collect() 每轮置位, main() 据此 exit 2。
# 判定 = 本轮确有待采(pending 非空) + 非空(dry_run 不报) + ok==0 且零写入
# ⇒ exit 2 让 systemd 把 trade-fof-nav-collect.service 标 failed,
#   现有消费者 scripts/check_failed_units.py(扫 systemctl --failed)即可发现。
# 单只 FAIL 是常态(封闭期/份额类上游空),不算整批失败,不触发本信号。
LAST_BATCH_FAILED = False
SELECT_SQL = (
    "SELECT fund_code, fund_name, fund_type FROM fund_basic "
    "WHERE fund_type LIKE 'FOF%' OR fund_type LIKE 'QDII%' "
    "ORDER BY fund_code"
)
# 只补 NULL/缺行: COALESCE(库值, 新值) = 库值非空保留库值, 新值只填空位。
# 方向与 fetch_daily_nav **相反**: fetch_daily_nav 用 COALESCE(新值, 库值)=新值非空优先用新值
# (可覆盖库值); 本采集器用 COALESCE(库值, 新值)=库值非空永不被覆盖(更保守, 止漏不踩踏)。
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


def collect(days: int = 7, limit: int | None = None, dry_run: bool = False,
            batch: int = BATCH_SIZE) -> int:
    """主流程。返回写入行数。

    整批失败信号(#366/F01): 若本轮确有待采(pending 非空)、非 dry_run、且 ok==0 且零写入,
    置位 mod.LAST_BATCH_FAILED, main() 据此 exit 2 → systemd 标 failed →
    check_failed_units.py 扫到。单只失败是常态不算整批失败。

    跳过已填 + 分批:
      - 跳过已填: 查库中目标日期范围内已有非空 unit_nav 的 fund_code, 从待采列表排除,
        只对未填的发 API(解决"每轮重头跑→后段永不触达")。
      - 分批: 每轮最多采 batch 只(默认 BATCH_SIZE), 剩余下轮续(配合跳过已填, 几轮覆盖 1796)。
      - limit: 调试小样, 优先于 batch(只取前 N 只, 不分批续跑)。
    """
    global LAST_BATCH_FAILED
    LAST_BATCH_FAILED = False  # 每轮重置, 防同进程跨轮残留(合法空数据/锁占/无待采均保持 False)
    init_db()  # 幂等(确保表存在)
    if not _acquire_lock(nonblock=True, lock_name="public_fund"):
        print("[fof_nav] WARN public_fund.lock 被占, 跳过(防与 daily/quarterly 并发写同库)",
              flush=True)
        return 0
    conn = get_conn()
    end = date.today()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    start_yyyymmdd = start.strftime("%Y%m%d")
    end_yyyymmdd = end.strftime("%Y%m%d")

    all_funds = list(conn.execute(SELECT_SQL))
    total_pool = len(all_funds)

    # 跳过已填: 目标日期范围内已有非空 unit_nav 的 fund_code(只对未填的发 API)
    if not dry_run:
        filled = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT fund_code FROM fund_daily_nav "
                "WHERE date BETWEEN ? AND ? AND unit_nav IS NOT NULL",
                (start_yyyymmdd, end_yyyymmdd),
            )
        }
    else:
        filled = set()  # dry-run 不查库已填(只验 API)
    pending = [(c, n, t) for (c, n, t) in all_funds if c not in filled]
    skipped_filled = total_pool - len(pending)

    if limit:
        pending = pending[:limit]
        run_batch = len(pending)  # limit 模式不分批, 一次性跑完
    else:
        run_batch = min(batch, len(pending))
    pending = pending[:run_batch]

    print(f"[fof_nav] FOF/QDII 总数={total_pool} 已填跳过={skipped_filled} "
          f"待采={len(pending)}/{len(all_funds)-skipped_filled} 本轮跑 "
          f"(拉近{days}日 {start_str}~{end_str} batch={run_batch} dry_run={dry_run})",
          flush=True)
    if not pending:
        print("[fof_nav] 全部已填, 无待采, 跳过", flush=True)
        conn.close()
        return 0

    had_pending = True  # 走到此处 = pending 非空(上方 not pending 已 early-return)
    total_written = 0
    ok = 0
    fail = 0
    t0 = time.time()
    for idx, (fund_code, fund_name, fund_type) in enumerate(pending, 1):
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
            print(f"[fof_nav] 进度 {idx}/{len(pending)} ok={ok} fail={fail} "
                  f"written={total_written} {time.time()-t0:.0f}s", flush=True)
        time.sleep(RATE_LIMIT)
    conn.close()
    remaining = (total_pool - skipped_filled) - len(pending)
    print(f"[fof_nav] 完成 ok={ok} fail={fail} written={total_written} "
          f"{time.time()-t0:.0f}s 剩余待采={remaining}(下轮续)",
          flush=True)
    # 整批失败信号(#366/F01): 确有待采 + 非 dry_run + 全失败零写入 → 置位供 main() exit 2。
    # 单只失败是常态(封闭期/份额类),ok>0 或 written>0 即判部分成功,不触发。
    batch_fail = had_pending and (not dry_run) and ok == 0 and total_written == 0
    if batch_fail:
        print(f"[fof_nav] BATCH_FAIL 本轮待采={len(pending)} 全部失败零写入 "
              f"(疑似整批网络异常/WAF, 已写数据保留, 下轮自动续跑)",
              flush=True)
    LAST_BATCH_FAILED = batch_fail  # global 声明在函数头(配合顶部复位)
    return total_written


def main() -> int:
    ap = argparse.ArgumentParser(description="#333 批1 FOF/QDII 净值采集器")
    ap.add_argument("--days", type=int, default=7, help="拉近 N 自然日(默认 7)")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 只(调试, 优先于 --batch)")
    ap.add_argument("--batch", type=int, default=BATCH_SIZE,
                    help=f"每轮最多采 N 只(默认 {BATCH_SIZE}, 配合跳过已填分批续跑)")
    ap.add_argument("--dry-run", action="store_true", help="只拉不写")
    args = ap.parse_args()
    n = collect(days=args.days, limit=args.limit, dry_run=args.dry_run, batch=args.batch)
    print(f"[fof_nav] return written={n}", flush=True)
    # 整批失败(#366/F01): exit 2 → systemd 标 trade-fof-nav-collect.service failed
    # → check_failed_units.py 扫 systemctl --failed 即发现。合法空数据/单只失败/部分成功均 exit 0。
    if LAST_BATCH_FAILED:
        print("[fof_nav] exit 2: 整批失败信号已置位(供 check_failed_units 消费)", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
