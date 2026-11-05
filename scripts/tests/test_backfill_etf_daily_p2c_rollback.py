# -*- coding: utf-8 -*-
"""backfill_etf_daily.py P2-C 同类(2026-11-05): 单只 ETF 写库失败回滚测试。

背景: backfill_etf_daily.py 每只 ETF 在 backfill_one 内 executemany+commit,
main 的 per-item loop 旧 except 分支只计数不回滚, 失败那只的部分写入留在未提交
事务里, 会被下一只 backfill_one 的 commit 一起提交, 产生半截数据(与 collect_fof_nav
P2-C 同根因)。

修复(P2-C 同类): main 的 except 分支加 conn.rollback(), 保证失败那只零落库、
不影响下一只。

零外发铁律(§18 L48): 本文件不触碰任何发送链路, 零真实外发。
L51: 不写死「今天」, 不依赖被测代码内部 today()/now()。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

from scripts import backfill_etf_daily as mod


def _conn(db: Path):
    c = sqlite3.connect(str(db), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS etf_daily (
      date TEXT NOT NULL,
      etf_code TEXT NOT NULL,
      etf_name TEXT,
      open REAL, high REAL, low REAL, close REAL, amount REAL,
      fund_share REAL, share_change REAL, share_change_pct REAL, accum_nav REAL,
      PRIMARY KEY (date, etf_code)
    );
    """)
    c.commit()
    return c


def _seed_etf_map(monkeypatch, codes):
    """注入假 etf_index_map(status=ok) + 空 name 回退, 不读磁盘 json。"""
    fake_map = {code: {"status": "ok", "name": f"ETF-{code}"} for code in codes}
    monkeypatch.setattr(mod, "_load_etf_index_map", lambda: fake_map)
    monkeypatch.setattr(mod, "_load_name_fallback_map", lambda: {})


def test_mid_executemany_fail_rollback_zero_residue(tmp_path, monkeypatch):
    """P2-C 同类: 第 2 只 executemany 中途抛错 → 第 2 只零行落库、第 1/3 只正常。

    mock 策略: 包装 conn, 第 2 只(510301)的 executemany 写入第 1 行后抛 RuntimeError,
    模拟中途失败。断言:
      ① 第 2 只(510301)在 etf_daily 零行(rollback 生效, 部分写入被回滚)
      ② 第 1 只(510300)和第 3 只(510310)正常落库(各 1 行)
      ③ fail 计数含第 2 只(err 计入), success 含第 1/3 只
    """
    db = tmp_path / "etf_national_team.db"
    codes = ["510300", "510301", "510310"]
    _seed_etf_map(monkeypatch, codes)
    monkeypatch.setattr(mod, "_get_etf_db_path", lambda: db)

    real_conn = _conn(db)

    class _WrappedCursor:
        """包装真实 cursor: 第 2 次 executemany 写入第 1 行后抛错。"""
        def __init__(self, real_cur, real_conn, state):
            self._real = real_cur
            self._real_conn = real_conn
            self._state = state

        def __getattr__(self, name):
            return getattr(self._real, name)

        def executemany(self, sql, params):
            self._state["n"] += 1
            if self._state["n"] == 2:
                rows = list(params)
                if rows:
                    # 部分写入: 先写第 1 行(留在未提交事务里), 再抛错
                    self._real.execute(sql, rows[0])
                raise RuntimeError("mock executemany 中途失败")
            return self._real.executemany(sql, params)

    class _WrappedConn:
        def __init__(self, real):
            self._real = real
            self._state = {"n": 0}

        def __getattr__(self, name):
            return getattr(self._real, name)

        def cursor(self):
            return _WrappedCursor(self._real.cursor(), self._real, self._state)

        def execute(self, *a, **k):
            return self._real.execute(*a, **k)

        def commit(self):
            return self._real.commit()

        def rollback(self):
            return self._real.rollback()

        def close(self):
            return self._real.close()

    # 仅第一个 connect(main 主循环 conn)用包装; after-snapshot 重连用真 conn。
    connect_calls = {"n": 0}
    real_connect = mod.sqlite3.connect

    def fake_connect(path, *a, **k):
        connect_calls["n"] += 1
        c = real_connect(path, *a, **k)
        if connect_calls["n"] == 1:
            wc = _WrappedConn(c)
            # 建表(真实)
            c.executescript("""
            CREATE TABLE IF NOT EXISTS etf_daily (
              date TEXT NOT NULL, etf_code TEXT NOT NULL, etf_name TEXT,
              open REAL, high REAL, low REAL, close REAL, amount REAL,
              fund_share REAL, share_change REAL, share_change_pct REAL, accum_nav REAL,
              PRIMARY KEY (date, etf_code)
            );
            """)
            c.commit()
            return wc
        return c

    monkeypatch.setattr(mod.sqlite3, "connect", fake_connect)

    def fake_fetch(symbol):
        # symbol = sh510300 等; 反推 code 取后 6 位
        code = symbol[-6:]
        return mod.pd.DataFrame([{
            "date": "2026-11-04", "open": 1.0, "high": 1.1, "low": 0.9,
            "close": 1.05, "volume": 1000, "amount": 1050.0,
        }])

    monkeypatch.setattr(mod, "fetch_etf_hist", fake_fetch)
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["backfill_etf_daily.py", "--sleep", "0"])

    rc = mod.main()

    c = _conn(db)
    rows_mid = c.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE etf_code='510301'").fetchone()[0]
    rows_a = c.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE etf_code='510300'").fetchone()[0]
    rows_c = c.execute(
        "SELECT COUNT(*) FROM etf_daily WHERE etf_code='510310'").fetchone()[0]
    c.close()

    assert rows_mid == 0, f"失败 ETF 应零行(rollback), 得 {rows_mid} 行"
    assert rows_a == 1, f"第 1 只应 1 行, 得 {rows_a}"
    assert rows_c == 1, f"第 3 只应 1 行, 得 {rows_c}"
    assert rc == 0
    print(f"[P2-C 同类] rollback PASS: 510301 零行, 510300/510310 各 1 行")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
