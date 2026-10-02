#!/usr/bin/env python3
"""futures_position 综合品种 REPLACE 整行覆盖隐患 自测(2026-10-03 修)。

背景: app/compute/futures_position.py compute_net_position 原用
  INSERT OR REPLACE INTO futures_position (date, variety, role, net_ratio, source)
只填 2 个业务列, REPLACE=删整行重插, 会把采集器(collector/futures_position.py _upsert)
写入综合品种行的 total_long/total_short/net_position/long_chg/short_chg/contract_count 清成 NULL。
本次改为 ON CONFLICT DO UPDATE, 只更新 net_ratio+source, 其余列保留。

Part A: 复现旧 REPLACE 行为(应证明会被清成 NULL —— 这就是病灶)
Part B: 用修复后的真实 compute_net_position() 跑, 证明其他列被保留
__file__ 断言: 目标模块必须解析在本 worktree 内(防 import 到主 checkout 老代码假通过)

用法: WT_PATH=<worktree根目录绝对路径> python3 docs/ops/test_futures_position_replace_selfcheck.py
"""
import os
import sys
import sqlite3
import tempfile
from pathlib import Path

WT = Path(os.environ["WT_PATH"]).resolve()
sys.path.insert(0, str(WT))

PASS = 0

def assert_ok(cond, msg):
    global PASS
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    PASS += 1
    print(f"  PASS[{PASS}] {msg}")


# ── 0. __file__ 断言: 目标模块必须在本 worktree 内 ──
import app.compute.futures_position as fp
import app.db as dbmod

fp_path = Path(fp.__file__).resolve()
assert_ok(str(fp_path).startswith(str(WT)),
          f"fp.__file__={fp_path} 落在 worktree {WT} 内(非主 checkout 老代码)")
db_path = Path(dbmod.__file__).resolve()
assert_ok(str(db_path).startswith(str(WT)),
          f"db.__file__={db_path} 落在 worktree {WT} 内")

FULL_ROW = ("20261003", "综合", "top20", 100.0, 90.0, 10.0, 0.0526, 5.0, -3.0, 200,
            "akshare", "2026-10-03T00:00:00")
TOTAL_COLS_SAVED = {"total_long": 100.0, "total_short": 90.0, "net_position": 10.0,
                    "long_chg": 5.0, "short_chg": -3.0, "contract_count": 200}


def _create_schema(conn: sqlite3.Connection):
    conn.executescript(dbmod.SCHEMA)
    conn.commit()


def _insert_full_row(conn: sqlite3.Connection):
    """复刻 collector/futures_position.py _upsert 的全列写入。"""
    conn.execute(
        "INSERT INTO futures_position "
        "(date, variety, role, total_long, total_short, net_position, net_ratio, "
        " long_chg, short_chg, contract_count, source, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(date, variety, role) DO UPDATE SET "
        "total_long=excluded.total_long, total_short=excluded.total_short, "
        "net_position=excluded.net_position, net_ratio=excluded.net_ratio, "
        "long_chg=excluded.long_chg, short_chg=excluded.short_chg, "
        "contract_count=excluded.contract_count, source=excluded.source, "
        "created_at=excluded.created_at",
        FULL_ROW,
    )
    conn.commit()


def _read_row(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute(
        "SELECT total_long, total_short, net_position, net_ratio, "
        "       long_chg, short_chg, contract_count, source "
        "FROM futures_position WHERE date='20261003' AND variety='综合' AND role='top20'"
    ).fetchone()


# ── Part A: 旧 REPLACE 行为复现(证明病灶真实存在) ──
print("\n=== Part A: 旧 INSERT OR REPLACE 行为(病灶复现) ===")
with tempfile.TemporaryDirectory() as td:
    dbmod.DB_PATH = Path(td) / "a.db"
    dbmod._schema_ensured = False
    conn = dbmod.get_conn()
    _create_schema(conn)
    _insert_full_row(conn)
    row = _read_row(conn)
    assert_ok(row is not None and row["total_long"] == 100.0,
              f"前置: 全列写入后 total_long={row['total_long']}")
    # 旧 SQL: REPLACE 只写 net_ratio+source
    conn.execute(
        "INSERT OR REPLACE INTO futures_position (date, variety, role, net_ratio, source) "
        "VALUES (?,?,?,?,?)",
        ("20261003", "综合", "top20", 0.1234, "computed"),
    )
    conn.commit()
    row = _read_row(conn)
    wiped = [c for c in TOTAL_COLS_SAVED if row[c] is not None]
    print(f"  REPLACE 后 total_long={row['total_long']} total_short={row['total_short']} "
          f"net_position={row['net_position']} long_chg={row['long_chg']} "
          f"short_chg={row['short_chg']} contract_count={row['contract_count']}")
    assert_ok(len(wiped) == 0,
              f"病灶复现: REPLACE 部分列后 {TOTAL_COLS_SAVED.keys()} 全部被清成 NULL(保留=0)")
    conn.close()

# ── Part B: 修复后真实 compute_net_position (UPSERT) 保留其他列 ──
print("\n=== Part B: 修复后 compute_net_position(UPSERT) 其他列保留 ===")
with tempfile.TemporaryDirectory() as td:
    dbmod.DB_PATH = Path(td) / "b.db"
    dbmod._schema_ensured = False
    conn = dbmod.get_conn()
    _create_schema(conn)
    # 采集器先写: 4 品种行 + 综合全列行
    for v, ntr in (("IF", 0.05), ("IC", 0.06), ("IH", 0.04), ("IM", 0.07)):
        conn.execute(
            "INSERT INTO futures_position (date, variety, role, net_ratio, source) "
            "VALUES (?,?,?,?,?)",
            ("20261003", v, "top20", ntr, "akshare"),
        )
    conn.commit()
    _insert_full_row(conn)  # 综合品种全列
    # 跑真正的 compute_net_position(当前模块 = worktree 内修复版)
    fp.ROLES = ["top20"]
    n = fp.compute_net_position()
    assert_ok(n > 0, f"compute_net_position 写回 {n} 行")
    row = _read_row(conn)
    assert_ok(abs(row["net_ratio"] - 0.055) < 1e-6,  # mean(0.05,0.06,0.04,0.07)=0.055
              f"net_ratio 被更新为综合值 {row['net_ratio']}(mean=0.055)")
    preserved = all(row[c] == v for c, v in TOTAL_COLS_SAVED.items())
    print(f"  UPSERT 后 total_long={row['total_long']} total_short={row['total_short']} "
          f"net_position={row['net_position']} long_chg={row['long_chg']} "
          f"short_chg={row['short_chg']} contract_count={row['contract_count']}")
    assert_ok(preserved,
              f"其他列(采集器写入)在 UPSERT 后逐列保留(六列全=写入值)")
    assert_ok(row["source"] == "computed",
              f"source 被更新为 'computed'(本次真正取到的列正常更新)")
    conn.close()

print(f"\n=== ALL {PASS} PASS === (sqlite {sqlite3.sqlite_version}, worktree={WT})")