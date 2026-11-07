"""etf_name 写入契约测试(2026-11-07, task #Codex-name-contract).

直接调用被测函数 ``scripts.signal_kelly_backtest._batch_load_etf_prices``,
验证 etf_name 契约修复后真实名称行进入价格映射、占位/NULL 行仍被排除。

不复制 SQL, 不写生产库: 用临时 SQLite + monkeypatch ``_get_etf_db_path``。

用例:
  A. 163109 / 20261104-06 有 OHLC+NAV, etf_name=申万深成LOF(真实名) → 进 open/close/nav 映射 + sorted dates
  B. 同结构但 etf_name=etf_code(163109) 占位假数据 → 仍被排除(etf_name<>etf_code 过滤)
  C. etf_name=NULL 的行 → 仍被排除(防占位保护没被放宽, NULL 不满足 <> 条件)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest


def _make_db(tmp_path: Path) -> Path:
    """建临时 etf_national_team.db(只含 etf_daily 表, 满足 _batch_load_etf_prices 查询字段)。"""
    db = tmp_path / "etf_national_team.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE etf_daily (
          date TEXT NOT NULL,
          etf_code TEXT NOT NULL,
          etf_name TEXT,
          open REAL,
          high REAL,
          low REAL,
          close REAL,
          amount REAL,
          fund_share REAL,
          share_change REAL,
          share_change_pct REAL,
          accum_nav REAL,
          PRIMARY KEY (date, etf_code)
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def _insert(conn: sqlite3.Connection, code: str, date: str, etf_name, op, close, nav):
    conn.execute(
        "INSERT OR REPLACE INTO etf_daily (date, etf_code, etf_name, open, close, accum_nav) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (date, code, etf_name, op, close, nav),
    )
    conn.commit()


def _load(monkeypatch, db: Path, codes: list[str]):
    """直接调用被测函数 _batch_load_etf_prices(注入临时 DB 路径, 不碰生产库)。"""
    from scripts import signal_kelly_backtest as skb
    monkeypatch.setattr(skb, "_get_etf_db_path", lambda: str(db))
    return skb._batch_load_etf_prices(codes)


CODE = "163109"
NAME = "申万深成LOF"


def test_A_real_name_enters_price_mapping(monkeypatch, tmp_path):
    """用例 A: etf_name=真实名(申万深成LOF)+OHLC+NAV → 进映射 + sorted dates。"""
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    # 20261104/05/06 三天真实名 + OHLC + NAV
    for d, op, cl, nav in [("20261104", 1.10, 1.12, 1.20),
                           ("20261105", 1.12, 1.15, 1.22),
                           ("20261106", 1.15, 1.18, 1.25)]:
        _insert(conn, CODE, d, NAME, op, cl, nav)
    conn.close()

    nav_map, open_map, close_map, sorted_dates = _load(monkeypatch, db, [CODE])
    assert set(nav_map[CODE].keys()) == {"20261104", "20261105", "20261106"}, \
        f"真实名行应全部进入 nav 映射, 实际={sorted(nav_map[CODE])}"
    assert set(open_map[CODE].keys()) == {"20261104", "20261105", "20261106"}
    assert set(close_map[CODE].keys()) == {"20261104", "20261105", "20261106"}
    assert sorted_dates[CODE] == ["20261104", "20261105", "20261106"], \
        f"sorted_dates 应含三真实名日, 实际={sorted_dates[CODE]}"
    # 值正确性
    assert close_map[CODE]["20261106"] == 1.18
    assert nav_map[CODE]["20261106"] == 1.25


def test_B_placeholder_code_name_excluded(monkeypatch, tmp_path):
    """用例 B: etf_name=etf_code(163109) 占位假数据 → 仍被排除(不进映射)。"""
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    for d, op, cl, nav in [("20261104", 1.10, 1.12, 1.20),
                           ("20261105", 1.12, 1.15, 1.22)]:
        _insert(conn, CODE, d, CODE, op, cl, nav)  # etf_name = code 占位
    conn.close()

    nav_map, open_map, close_map, sorted_dates = _load(monkeypatch, db, [CODE])
    assert nav_map[CODE] == {}, f"占位行(etf_name=etf_code)应被排除, 实际 nav={nav_map[CODE]}"
    assert open_map[CODE] == {}
    assert close_map[CODE] == {}
    assert sorted_dates[CODE] == [], f"占位行不应进 sorted_dates, 实际={sorted_dates[CODE]}"


def test_C_null_name_excluded(monkeypatch, tmp_path):
    """用例 C: etf_name=NULL 的行 → 仍被排除(NULL 不满足 <> 条件, 防占位保护未放宽)。"""
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    for d, op, cl, nav in [("20261104", 1.10, 1.12, 1.20),
                           ("20261105", 1.12, 1.15, 1.22)]:
        _insert(conn, CODE, d, None, op, cl, nav)  # etf_name = NULL
    conn.close()

    nav_map, open_map, close_map, sorted_dates = _load(monkeypatch, db, [CODE])
    assert nav_map[CODE] == {}, f"NULL etf_name 行应被排除, 实际 nav={nav_map[CODE]}"
    assert open_map[CODE] == {}
    assert close_map[CODE] == {}
    assert sorted_dates[CODE] == [], f"NULL etf_name 行不应进 sorted_dates, 实际={sorted_dates[CODE]}"


def test_D_mixed_real_and_placeholder(monkeypatch, tmp_path):
    """用例 D(边界): 同一 code 混合真实名 + NULL 行 → 只真实名进映射, NULL 被排除。

    模拟生产事故场景: 163109 部分日期 NULL(临时脚本写入) + 部分日期真实名(契约修复后写入)。
    """
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    _insert(conn, CODE, "20261104", NAME, 1.10, 1.12, 1.20)   # 真实名
    _insert(conn, CODE, "20261105", None, 1.12, 1.15, 1.22)   # NULL(事故残留)
    _insert(conn, CODE, "20261106", NAME, 1.15, 1.18, 1.25)   # 真实名
    conn.close()

    nav_map, open_map, close_map, sorted_dates = _load(monkeypatch, db, [CODE])
    # 只有真实名的 04/06 进映射, NULL 的 05 被排除
    assert set(nav_map[CODE].keys()) == {"20261104", "20261106"}, \
        f"混合场景只真实名进映射, 实际 nav={sorted(nav_map[CODE])}"
    assert sorted_dates[CODE] == ["20261104", "20261106"]


# ── _upsert_daily 写入契约直接测试(证明 ON CONFLICT 保护) ──────────────────────


def _make_db_with_schema(tmp_path: Path) -> Path:
    db = _make_db(tmp_path)
    return db


class TestUpsertDailyNameContract:
    """直接调用 _upsert_daily, 验证 etf_name ON CONFLICT 保护规则。"""

    def _conn(self, tmp_path: Path):
        from app.collector.etf_national_team import _upsert_daily
        db = _make_db_with_schema(tmp_path)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn, _upsert_daily

    def test_null_does_not_overwrite_real_name(self, tmp_path):
        """已有真实名行, 再 upsert etf_name=None → 真实名保留(不被 NULL 覆盖)。"""
        conn, upsert = self._conn(tmp_path)
        # 先写真实名行
        upsert(conn, [{"date": "20261104", "etf_code": CODE, "etf_name": NAME,
                        "open": 1.1, "close": 1.12}],
               ["etf_name", "open", "close"])
        # 再用 NULL etf_name upsert 同一行(fetch_etf_ohlc 不返 name 的场景)
        upsert(conn, [{"date": "20261104", "etf_code": CODE, "etf_name": None,
                        "open": 1.1, "close": 1.13}],
               ["etf_name", "open", "close"])
        row = conn.execute("SELECT etf_name, close FROM etf_daily WHERE date='20261104' AND etf_code=?",
                           (CODE,)).fetchone()
        assert row["etf_name"] == NAME, \
            f"NULL 不得覆盖已有真实名, 实际 etf_name={row['etf_name']!r}"
        assert row["close"] == 1.13  # 非 etf_name 字段仍正常更新
        conn.close()

    def test_empty_string_does_not_overwrite_real_name(self, tmp_path):
        """已有真实名, upsert etf_name='' → 真实名保留。"""
        conn, upsert = self._conn(tmp_path)
        upsert(conn, [{"date": "20261105", "etf_code": CODE, "etf_name": NAME, "close": 1.1}],
               ["etf_name", "close"])
        upsert(conn, [{"date": "20261105", "etf_code": CODE, "etf_name": "", "close": 1.2}],
               ["etf_name", "close"])
        row = conn.execute("SELECT etf_name FROM etf_daily WHERE date='20261105' AND etf_code=?",
                           (CODE,)).fetchone()
        assert row["etf_name"] == NAME, f"空串不得覆盖真实名, 实际={row['etf_name']!r}"
        conn.close()

    def test_code_placeholder_does_not_overwrite_real_name(self, tmp_path):
        """已有真实名, upsert etf_name=code 占位 → 真实名保留(占位不写库)。"""
        conn, upsert = self._conn(tmp_path)
        upsert(conn, [{"date": "20261106", "etf_code": CODE, "etf_name": NAME, "close": 1.1}],
               ["etf_name", "close"])
        upsert(conn, [{"date": "20261106", "etf_code": CODE, "etf_name": CODE, "close": 1.2}],
               ["etf_name", "close"])
        row = conn.execute("SELECT etf_name FROM etf_daily WHERE date='20261106' AND etf_code=?",
                           (CODE,)).fetchone()
        assert row["etf_name"] == NAME, f"code 占位不得覆盖真实名, 实际={row['etf_name']!r}"
        conn.close()

    def test_real_name_overwrites_placeholder(self, tmp_path):
        """已有 code 占位名, upsert 真实名 → 占位被真实名覆盖(调用方真实名优先)。"""
        conn, upsert = self._conn(tmp_path)
        upsert(conn, [{"date": "20261107", "etf_code": CODE, "etf_name": CODE, "close": 1.1}],
               ["etf_name", "close"])
        upsert(conn, [{"date": "20261107", "etf_code": CODE, "etf_name": NAME, "close": 1.2}],
               ["etf_name", "close"])
        row = conn.execute("SELECT etf_name FROM etf_daily WHERE date='20261107' AND etf_code=?",
                           (CODE,)).fetchone()
        assert row["etf_name"] == NAME, f"真实名应覆盖占位, 实际={row['etf_name']!r}"
        conn.close()

