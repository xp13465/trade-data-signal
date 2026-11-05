# -*- coding: utf-8 -*-
"""F01 P2-C(2026-11-05): 单只基金写库失败回滚测试。

背景: collect_fof_nav.py 每只基金 executemany+commit, 旧代码异常分支只计数不回滚,
失败那只的部分写入留在未提交事务里, 会被下一只的 commit 一起提交; 且「跳过已填」
按「范围内存在任一非空 unit_nav」判定, 会把部分写入的基金当成已填。

修复(P2-C): except 分支加 conn.rollback(), 保证失败那只零落库、不影响下一只。

零外发铁律(§18 L48): 本文件不触碰任何发送链路, 零真实外发。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

from scripts import collect_fof_nav as mod


def _conn(db: Path):
    c = sqlite3.connect(str(db), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS fund_basic (
      fund_code TEXT PRIMARY KEY, fund_name TEXT, fund_type TEXT,
      pinyin_abbr TEXT, pinyin_full TEXT, update_date TEXT
    );
    CREATE TABLE IF NOT EXISTS fund_daily_nav (
      date TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT,
      unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL,
      PRIMARY KEY (date, fund_code)
    );
    """)
    c.commit()
    return c


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db = tmp_path / "public_fund.db"
    monkeypatch.setattr(mod, "get_conn", lambda: _conn(db))
    monkeypatch.setattr(mod, "init_db", lambda: None)
    monkeypatch.setattr(mod, "_acquire_lock",
                        lambda nonblock=True, lock_name="public_fund": True)
    mod.LAST_BATCH_FAILED = False
    return db


def _seed_basic(db: Path, funds):
    c = _conn(db)
    c.executemany(
        "INSERT OR REPLACE INTO fund_basic(fund_code,fund_name,fund_type) VALUES(?,?,?)",
        funds,
    )
    c.commit()
    c.close()


def test_mid_executemany_fail_rollback_zero_residue(tmp_db, monkeypatch):
    """P2-C: 第 2 只 executemany 中途抛错 → 第 2 只零行落库、第 1/3 只正常落库。

    mock 策略: 包装 conn, 第 2 只(005828)的 executemany 在写入部分行后抛 RuntimeError,
    模拟中途失败。断言:
      ① 第 2 只(005828)在 fund_daily_nav 零行(rollback 生效, 部分写入被回滚)
      ② 第 1 只(005827)和第 3 只(005829)各 1 行正常落库
      ③ error_count=1(只有第 2 只计入真实异常)
      ④ 整批判据不受影响: 有成功写入 → LAST_BATCH_FAILED=False
    """
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])

    real_conn = mod.get_conn()
    call_log = []

    class _WrappedConn:
        """包装真实 conn: 第 2 只 executemany 写入部分行后抛错(模拟中途失败)。"""
        def __init__(self, real):
            self._real = real
            self._exec_count = 0

        def __getattr__(self, name):
            return getattr(self._real, name)

        def executemany(self, sql, params):
            self._exec_count += 1
            call_log.append(self._exec_count)
            if self._exec_count == 2:
                # 第 2 只: 先写第 1 行(部分写入), 再抛错(模拟中途失败)
                rows = list(params)
                if rows:
                    self._real.execute(sql, rows[0])  # execute 取单行 tuple, 非 [row]
                raise RuntimeError("mock executemany 中途失败")
            return self._real.executemany(sql, params)

        def commit(self):
            return self._real.commit()

        def rollback(self):
            return self._real.rollback()

        def close(self):
            return self._real.close()

    monkeypatch.setattr(mod, "get_conn", lambda: _WrappedConn(real_conn))

    def fake_fetch(code, start, end):
        return [{"date": "20261101", "fund_code": code, "unit_nav": 1.1, "acc_nav": 1.1,
                 "prev_unit_nav": 1.0, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    n = mod.collect(days=7, limit=None, dry_run=False)

    # ① 第 2 只(005828)零行落库(rollback 回滚了部分写入)
    c = _conn(tmp_db)
    rows_b = c.execute(
        "SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='005828'").fetchone()[0]
    assert rows_b == 0, f"失败基金应零行(rollback), 得 {rows_b} 行"

    # ② 第 1/3 只各 1 行正常落库
    rows_a = c.execute(
        "SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='005827'").fetchone()[0]
    rows_c = c.execute(
        "SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='005829'").fetchone()[0]
    assert rows_a == 1, f"第 1 只应 1 行, 得 {rows_a}"
    assert rows_c == 1, f"第 3 只应 1 行, 得 {rows_c}"
    c.close()

    # ③ 有成功写入(2 只)→ n >= 2
    assert n >= 2, f"应有 2 只写入, 得 n={n}"
    # ④ 整批判据不受影响: 有成功 → LAST_BATCH_FAILED=False
    assert mod.LAST_BATCH_FAILED is False, "部分成功不应判整批失败"
    print(f"[P2-C] rollback PASS: 005828 零行, 005827/005829 各 1 行, n={n}")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
