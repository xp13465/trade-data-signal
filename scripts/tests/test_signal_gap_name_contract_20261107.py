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


# ── _upsert_daily 写入契约直接测试(证明 ON CONFLICT 保护 + 前置规范化) ──────────


def _make_db_with_schema(tmp_path: Path) -> Path:
    db = _make_db(tmp_path)
    return db


def _clear_name_caches():
    """清模块级名称缓存(防测试间污染: 缓存按 code 跨 test 共享会串结果)。"""
    from app.collector import etf_national_team as ent
    ent._UPSERT_DB_NAME_CACHE.clear()
    ent._UPSERT_PLACEHOLDER_WARNED.clear()
    # 重置 board_map 懒加载索引, 强制下次重新解析(测试可能 monkeypatch 解析函数)
    ent._BOARD_MAP_NAME_INDEX = None


class TestUpsertDailyNameContract:
    """直接调用 _upsert_daily, 验证 etf_name 前置规范化 + ON CONFLICT 保护规则。"""

    def _conn(self, tmp_path: Path):
        from app.collector.etf_national_team import _upsert_daily
        _clear_name_caches()
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

    # ── F1 闭合: 新行 INSERT 不产生 NULL(前置规范化) ──────────────────────────

    def test_F1_new_row_none_with_authoritative_name_writes_real(
        self, monkeypatch, tmp_path
    ):
        """F1 用例1: 全新行 INSERT, etf_name=None, monkeypatch 权威名解析 → 写真实名(非 NULL), loader 能看到。"""
        conn, upsert = self._conn(tmp_path)
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "_resolve_etf_name_authoritative", lambda c: NAME)
        # 全新行(DB 无该 code 任何行), etf_name=None(fetch_etf_ohlc 不返 name 的场景)
        upsert(conn, [{"date": "20261104", "etf_code": CODE, "etf_name": None,
                        "open": 1.10, "close": 1.12, "accum_nav": 1.20}],
               ["etf_name", "open", "close", "accum_nav"])
        row = conn.execute("SELECT etf_name FROM etf_daily WHERE date='20261104' AND etf_code=?",
                           (CODE,)).fetchone()
        shown = row["etf_name"] if row is not None else "NO ROW"
        assert row is not None and row["etf_name"] is not None, \
            f"新行不得产生 NULL, 实际 etf_name={shown!r}"
        assert row["etf_name"] == NAME, f"应写权威真实名, 实际={row['etf_name']!r}"
        conn.close()
        # loader 能看到(真实名行不被 etf_name<>etf_code 过滤); 复用同一 tmp_path 的 DB 文件
        db_path = tmp_path / "etf_national_team.db"
        from scripts import signal_kelly_backtest as skb
        monkeypatch.setattr(skb, "_get_etf_db_path", lambda: str(db_path))
        nav_map, open_map, close_map, sorted_dates = skb._batch_load_etf_prices([CODE])
        assert "20261104" in nav_map[CODE], \
            f"真实名新行应进 loader 映射, 实际 nav={sorted(nav_map[CODE])}"
        assert sorted_dates[CODE] == ["20261104"]

    def test_F1_new_row_none_no_authoritative_writes_code_placeholder(
        self, monkeypatch, tmp_path
    ):
        """F1 用例2: 全新行 INSERT, etf_name=None, 无权威名 → 写 code 占位(非 NULL), loader 仍排除。"""
        conn, upsert = self._conn(tmp_path)
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "_resolve_etf_name_authoritative", lambda c: None)
        upsert(conn, [{"date": "20261105", "etf_code": CODE, "etf_name": None,
                        "open": 1.10, "close": 1.12, "accum_nav": 1.20}],
               ["etf_name", "open", "close", "accum_nav"])
        row = conn.execute("SELECT etf_name FROM etf_daily WHERE date='20261105' AND etf_code=?",
                           (CODE,)).fetchone()
        assert row is not None, "新行应存在"
        assert row["etf_name"] is not None, \
            f"无权威名也不得产生 NULL, 应写 code 占位哨兵, 实际={row['etf_name']!r}"
        assert row["etf_name"] == CODE, \
            f"无权威名应回退 code 占位哨兵(非 NULL), 实际={row['etf_name']!r}"
        conn.close()
        # loader 仍排除占位行(etf_name=etf_code)
        db_path = tmp_path / "etf_national_team.db"
        from scripts import signal_kelly_backtest as skb
        monkeypatch.setattr(skb, "_get_etf_db_path", lambda: str(db_path))
        nav_map, _, _, sorted_dates = skb._batch_load_etf_prices([CODE])
        assert nav_map[CODE] == {}, \
            f"code 占位行应被 loader 排除, 实际 nav={sorted(nav_map[CODE])}"
        assert sorted_dates[CODE] == []

    def test_F1_explicit_code_placeholder_not_replaced_by_real_name(
        self, monkeypatch, tmp_path
    ):
        """F1 用例3: 明确 etf_name=code 占位行 → 保持 code, 不被真实名替换, loader 仍排除。

        调用方主动写占位哨兵(盘中假数据)时, 即使权威名可得也保持占位(防假数据洗成真数据)。
        """
        conn, upsert = self._conn(tmp_path)
        from app.collector import etf_national_team as ent
        monkeypatch.setattr(ent, "_resolve_etf_name_authoritative", lambda c: NAME)
        upsert(conn, [{"date": "20261106", "etf_code": CODE, "etf_name": CODE,
                        "open": 1.10, "close": 1.12, "accum_nav": 1.20}],
               ["etf_name", "open", "close", "accum_nav"])
        row = conn.execute("SELECT etf_name FROM etf_daily WHERE date='20261106' AND etf_code=?",
                           (CODE,)).fetchone()
        assert row is not None, "占位行应存在"
        assert row["etf_name"] == CODE, \
            f"调用方主动占位应保持 code, 不被真实名替换, 实际={row['etf_name']!r}"
        conn.close()
        # loader 仍排除占位行
        db_path = tmp_path / "etf_national_team.db"
        from scripts import signal_kelly_backtest as skb
        monkeypatch.setattr(skb, "_get_etf_db_path", lambda: str(db_path))
        nav_map, _, _, sorted_dates = skb._batch_load_etf_prices([CODE])
        assert nav_map[CODE] == {}, \
            f"占位行应被 loader 排除, 实际 nav={sorted(nav_map[CODE])}"
        assert sorted_dates[CODE] == []

