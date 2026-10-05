#!/usr/bin/env python3
"""#163 断档回填：从 `fapi_daily_raw` 库内搬移补齐 `mootdx_daily_raw` 的缺失交易日。

背景（docs/pending-features-index.md #163）
==========================================
2026-09-29 / 09-30 mootdx 主源空 + baostock fallback 登录失败（10002007）双腿同死
→ `mootdx_daily_raw` 缺该两日（MAX 停在 09-28）→ 下游 `industry_width_daily`
（行业宽度卡）断档 2 天。FAPI（同花顺）T+0 全市场 dump 已在库（09-29=5559 / 09-30=5560），
columns 与 mootdx 同构，**库内搬移**分钟级、零网络依赖，优于重跑 baostock fallback
（mootdx `_TDX_SERVERS` 十台至今全空，baostock 串行 17 只 >5min、全量估 10h+ 且可能再断）。

口径（§23.13 三源核对，勿踩）
============================
主宽度宇宙**不含北交所**，三源一致：
  1. UI 文案 `static-site/app.js:_WIDTH_CALIBER_TIP`：涨跌家数口径 = mootdx 收盘全 A 快照
     （沪深主板/创业板/科创板，约 5200 只），**不包含北交所**（北交所宽度见独立 a_bj_* 指标）。
  2. 代码现状：`mootdx_daily_raw` 历史 **0 只 920 代码**（全表 `COUNT(DISTINCT code) WHERE code LIKE '920%'` = 0）；
     `bj_width.py` 头注 #101 拍板「主宽度 mootdx 全 A 宇宙不含北交所」；
     `width_history.py` #102 FAPI 兜底显式 `code NOT LIKE '920%'`（"补缺不改变宇宙定义"）。
  3. FAPI 源表 09-29=5559 / 09-30=5560 为**源表可用量**，其中 920 北交所各 348 只。

⇒ 搬移**必须排除 920**，否则 2 日凭空多出 348 只北交所 code，与全表其余日不一致、
且违反 #101 拍板并污染主宽度涨跌家数。搬移后应有 09-29=5211 / 09-30=5212 行。

幂等
====
`INSERT ... ON CONFLICT(code, date) DO UPDATE`（纯 upsert），可重复跑；当日休市无交易日影响。
不触碰 progress 文件（该文件只用于采集切任务清单，不影响库事实）。

用法
====
python scripts/backfill_mootdx_from_fapi.py --db /path/to/stock_daily.db \
    --dates 20260929,20260930 [--dry-run]

默认 --db 取仓根 data/stock_daily.db（云上跑时 cwd=/home/ubuntu/code/trade-data 即主库）。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_DEFAULT_DB = Path(__file__).absolute().parent.parent / "data" / "stock_daily.db"

# fapi_daily_raw 与 mootdx_daily_raw 同名列（可直接 INSERT ... SELECT）
_COLS = ("code", "date", "open", "high", "low", "close", "volume", "amount",
         "pct_change", "turnover")


def backfill(db: str, dates: list[str], *, dry_run: bool = False,
             verbose: bool = True) -> dict:
    conn = sqlite3.connect(db, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000;")
    out = {}
    try:
        for d in dates:
            src_n = conn.execute(
                "SELECT COUNT(*) FROM fapi_daily_raw WHERE date=?", (d,)).fetchone()[0]
            src_bj = conn.execute(
                "SELECT COUNT(*) FROM fapi_daily_raw WHERE date=? AND code LIKE '920%'",
                (d,)).fetchone()[0]
            dst_before = conn.execute(
                "SELECT COUNT(*) FROM mootdx_daily_raw WHERE date=?", (d,)).fetchone()[0]
            expect = src_n - src_bj
            if verbose:
                print(f"[{d}] fapi={src_n} (含 920 北交所 {src_bj},口径外) "
                      f"→ 应搬移 {expect}；搬移前 mootdx 当日 {dst_before} 行", flush=True)
            if dry_run:
                out[d] = {"fapi": src_n, "bj920": src_bj, "expected": expect,
                          "before": dst_before, "written": 0, "dry_run": True}
                continue
            cur = conn.execute(
                "INSERT INTO mootdx_daily_raw "
                "(code, date, open, high, low, close, volume, amount, pct_change, turnover) "
                "SELECT code, date, open, high, low, close, volume, amount, pct_change, turnover "
                "FROM fapi_daily_raw WHERE date=? AND code NOT LIKE '920%' "
                "ON CONFLICT(code, date) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                "volume=excluded.volume, amount=excluded.amount, "
                "pct_change=excluded.pct_change, turnover=excluded.turnover",
                (d,),
            )
            conn.commit()
            dst_after = conn.execute(
                "SELECT COUNT(*) FROM mootdx_daily_raw WHERE date=?", (d,)).fetchone()[0]
            out[d] = {"fapi": src_n, "bj920": src_bj, "expected": expect,
                      "before": dst_before, "written": cur.rowcount if cur.rowcount >= 0 else expect,
                      "after": dst_after, "dry_run": False}
            if verbose:
                print(f"[{d}] upsert 完成: 当日 mootdx 行数 {dst_before} → {dst_after} "
                      f"(应={expect})", flush=True)
    finally:
        conn.close()
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="从 fapi_daily_raw 回填 mootdx_daily_raw（#163）")
    ap.add_argument("--db", default=str(_DEFAULT_DB),
                    help=f"stock_daily.db 路径（默认 {_DEFAULT_DB}）")
    ap.add_argument("--dates", default="20260929,20260930",
                    help="逗号分隔的交易日期（YYYYMMDD）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args(argv[1:])
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    print(f"#163 回填: db={args.db} dates={dates} dry_run={args.dry_run}", flush=True)
    res = backfill(args.db, dates, dry_run=args.dry_run)
    ok = True
    for d, r in res.items():
        if r["dry_run"]:
            continue
        if r["after"] != r["expected"]:
            ok = False
            print(f"✗ [{d}] 校验失败: 搬移后 {r['after']} != 期望 {r['expected']}", flush=True)
        else:
            print(f"✓ [{d}] 校验通过: {r['after']} 行 == 期望 {r['expected']}", flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))