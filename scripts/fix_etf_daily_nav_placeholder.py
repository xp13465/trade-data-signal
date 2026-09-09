#!/usr/bin/env python3
"""清除 etf_daily 20260908 accum_nav=1.5 占位污染(P0 数据止血, 2026-09-09)。

目的
----
线上 bug: signal_kelly_backtest 持仓 current_price 全取到 1.5 元, 收益率虚高 80%+。
根因: etf_daily 表 20260908 有 accum_nav=1.5 占位污染(盘中占位写入后, 盘后 backfill
只覆盖 OHLC/name 不覆盖 accum_nav, COALESCE 不覆盖已有值; accum-nav pipeline 只补
accum_nav IS NULL 的行 → 1.5 非 NULL 永不修复)。回测 current_price 取 max(date) 当日
accum_nav → 全持仓 current_price=1.5。

本脚本只处理「混合行」: date='20260908' AND accum_nav=1.5 AND etf_name<>etf_code
(1480 行, 真实名+真实 close+残留 accum_nav=1.5), 把 accum_nav 置 NULL, 便于后续
accum-nav pipeline 从真实源补回。

绝不处理「纯占位行」: close IS NULL(或 etf_name=etf_code, 60 行), 本来盘后就没真实价,
置 NULL 后 accum-nav 也拉不到(跳过列表), 保持原样。

口径
----
- 判定混合行:  date='20260908' AND accum_nav=1.5 AND etf_name<>etf_code
                 (close IS NOT NULL 已由历史查询确认 1480 行全满足, 不额外卡 close)
- 不动纯占位:  etf_name=etf_code 或 close IS NULL 的行一律不碰
- 置 None(空) 后由 app.collector.etf_national_team accum-nav --lookback 30 补齐真实累计净值

DB 路径
-------
- 主库: /Users/linhuichen/code/trade-data/data/etf_national_team.db(脚本优先)
- 备份: data/etf_national_team.db.bak-p0-20260909(实改前自动备份)

用法/复现
---------
    # 1. 预览(不改库)
    .venv/bin/python scripts/fix_etf_daily_nav_placeholder.py --dry-run
    # 2. 实改(自动备份 -> 置 NULL 1480 行)
    .venv/bin/python scripts/fix_etf_daily_nav_placeholder.py
    # 3. 补齐真实累计净值(在 trade-data 目录跑)
    .venv/bin/python -m app.collector.etf_national_team accum-nav --lookback 30
    # 4. 验证无残留
    .venv/bin/python scripts/fix_etf_daily_nav_placeholder.py --verify
"""
import argparse
import os
import shutil
import sqlite3
import sys

# 与 signal_kelly_backtest._get_etf_db_path 同源: 优先 trade-data 主库, 回退 trade/data
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # trade 仓库根
CANDIDATES = [
    os.path.join(os.path.dirname(ROOT), "trade-data", "data", "etf_national_team.db"),
    os.path.join(ROOT, "data", "etf_national_team.db"),
]
DB_PATH = next((p for p in CANDIDATES if os.path.exists(p)), None)
if DB_PATH is None:
    print("✗ 找不到 etf_national_team.db", file=sys.stderr)
    sys.exit(2)

BACKUP_PATH = os.path.join(os.path.dirname(DB_PATH), "etf_national_team.db.bak-p0-20260909")

TARGET_DATE = "20260908"
COND = "date=? AND accum_nav=1.5 AND etf_name<>etf_code"


def count(conn):
    return conn.execute(f"SELECT COUNT(*) FROM etf_daily WHERE {COND}", (TARGET_DATE,)).fetchone()[0]


# 已知真实累计净值恰好 =1.5 的 ETF(akshare fund_open_fund_info_em 实测确认, 非占位污染)
# 2026-09-09: 588930(科创人工智能ETF银) 20260908 真实累计净值 =1.5000(补数后残留 1 行是真实值)。
REAL_NAV_ONE_FIVE = {"588930"}


def verify(conn):
    """验证: 20260908 无混合污染残留(纯占位 1.5 允许存在, 数量应为 60)。

    混合行 accum_nav=1.5 且 etf_name<>etf_code 中, 剔除 REAL_NAV_ONE_FIVE 已知真实值后应为 0;
    剩余的逐行列出 etf_code 便于人工/机制复核是否也是真实值。
    """
    rows = conn.execute(
        "SELECT etf_code, etf_name, close, accum_nav FROM etf_daily "
        f"WHERE {COND}",
        (TARGET_DATE,),
    ).fetchall()
    non_real = [r for r in rows if r["etf_code"] not in REAL_NAV_ONE_FIVE]
    place = conn.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE date=? AND accum_nav=1.5 AND etf_name=etf_code",
        (TARGET_DATE,),
    ).fetchone()[0]
    place_close = conn.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE date=? AND accum_nav=1.5 AND close IS NULL",
        (TARGET_DATE,),
    ).fetchone()[0]
    print(f"  [verify] 20260908 混合 accum_nav=1.5: {len(rows)} 行(已知真实值豁免 {sorted(REAL_NAV_ONE_FIVE)})")
    for r in rows:
        mark = "真实值" if r["etf_code"] in REAL_NAV_ONE_FIVE else "⚠ 待复核"
        print(f"    {r['etf_code']} {r['etf_name']} close={r['close']} accum_nav={r['accum_nav']} [{mark}]")
    print(f"  [verify] 20260908 纯占位 etf_name=etf_code: {place} 行(应=60, 不动)")
    print(f"  [verify] 20260908 纯占位 close IS NULL: {place_close} 行(应=60, 不动)")
    return len(non_real) == 0 and place == 60 and place_close == 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印受影响行数与抽样, 不改库")
    ap.add_argument("--verify", action="store_true", help="只验证当前 DB 状态, 不改库")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        total = count(conn)
        if args.verify:
            ok = verify(conn)
            sys.exit(0 if ok else 1)
        # 抽样展示
        rows = conn.execute(
            f"SELECT etf_code, etf_name, open, high, low, close, accum_nav FROM etf_daily WHERE {COND} LIMIT 5",
            (TARGET_DATE,),
        ).fetchall()
        print(f"DB: {DB_PATH}")
        print(f"{TARGET_DATE} accum_nav=1.5 混合行(etf_name<>etf_code): {total} 行")
        print("抽样(确认是真实行+残留1.5):")
        for r in rows:
            print(f"  {dict(r)}")
        pure = conn.execute(
            "SELECT COUNT(*) FROM etf_daily WHERE date=? AND accum_nav=1.5 AND etf_name=etf_code",
            (TARGET_DATE,),
        ).fetchone()[0]
        print(f"纯占位行(etf_name=etf_code, 保护不处理): {pure} 行")
        if total == 0:
            print("无需处理")
            return
        if args.dry_run:
            print(f"[dry-run] 将置 NULL {total} 行(不执行)")
            return
        # 实改: 先备份
        if not os.path.exists(BACKUP_PATH):
            print(f"备份 DB -> {BACKUP_PATH}")
            shutil.copy2(DB_PATH, BACKUP_PATH)
        else:
            print(f"备份已存在, 跳过: {BACKUP_PATH}")
        cur = conn.execute(f"UPDATE etf_daily SET accum_nav=NULL WHERE {COND}", (TARGET_DATE,))
        conn.commit()
        print(f"✓ 已置 NULL {cur.rowcount} 行")
        ok = verify(conn)
        print(f"verify: {'PASS' if ok else 'FAIL'}")
        sys.exit(0 if ok else 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()