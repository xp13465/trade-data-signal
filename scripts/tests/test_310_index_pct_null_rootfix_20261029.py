# -*- coding: utf-8 -*-
"""#310 index_daily.pct_change 被清空根治 自测(2026-10-29)。

背景(根因报告 /tmp/pctchange-rootcause-report.md)
  · pct_change 全部自算(fetchers 两个分支都用「本次 df 上一行 close」),df **首行没有
    上一行** ⇒ pct=None;upsert 全字段覆盖 ⇒ 把库里正确的好值抹成 NULL;两个源的窗口
    首行每天前移(thsc 起拉日=date-400 天 / 新浪全球指数服务端只给 1000 行)⇒ 每天抹掉
    一个新日期。
  · 修法 A(计算层):`app.collector.index_pct.fill_first_pct` 用库里更早的最近一条 close
    补 prev,并接进 `runner.upsert_index_rows`(所有经它的写入路径)。
  · 修法 B(写入层):`index_pct.PCT_CHANGE_PRESERVE_SQL` —— close 完全相同且新 pct 为 NULL
    ⇒ 保留旧值;close 真变 ⇒ 照常覆盖(不挡真修正)。

覆盖
  A1 首行有前收 ⇒ 算出的 pct 与被抹掉的原值一致(-1.484729,真实样本 thsc_300816)
  A2 prev 不存在(序列真正第一行)⇒ 保持 NULL
  A3 close 为 NULL ⇒ 不填(真缺行不许编数)
  A4 pct 已有值 ⇒ 不动
  A5 端到端:经 `runner.upsert_index_rows` 写库,首行 pct 自动补上
  B1-B4 写入层四种组合(经真实 upsert 生产 SQL,不复制第二份 SQL)
  §18 L48 零外发:本文件所有用例 monkeypatch 审计入口与 send_alert,不触真实通知链。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.db as app_db  # noqa: E402
from app.collector import index_pct  # noqa: E402
from app.collector import runner  # noqa: E402
from app.db import SCHEMA  # noqa: E402

# 真实样本(根因报告 §4.2):thsc_300816 20250909 被抹掉的原值
PREV_CLOSE = 3928.327
FIRST_CLOSE = 3870.002
EXPECTED_PCT = -1.4847287407591114


def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _insert_row(conn, date, index_id, close, pct=None):
    conn.execute(
        "INSERT INTO index_daily (date, index_id, close, pct_change) VALUES (?,?,?,?)",
        (date, index_id, close, pct),
    )
    conn.commit()


@pytest.fixture(autouse=True)
def _no_alert(monkeypatch):
    """§18 L48:审计/告警一律打桩,自测绝不产生真实外发。"""
    import app.history_audit as ha
    monkeypatch.setattr(ha, "audit_index_rows_upsert", lambda *a, **k: [])
    monkeypatch.setattr(ha, "send_alert", lambda *a, **k: None)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """把 app.db.DB_PATH 指向临时库(带 source/net_inflow 迁移列),供 runner 端到端用。"""
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(app_db, "DB_PATH", db_path)
    monkeypatch.setattr(app_db, "_schema_ensured", False)
    conn = app_db.get_conn()
    app_db._migrate(conn)
    conn.commit()
    conn.close()
    return db_path


def _read(db_path, sql, args=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


# ────────────────────────── A. 计算层 ──────────────────────────

def test_a1_first_row_uses_prev_close_from_db():
    """A1:首行缺 prev ⇒ 用库里更早的最近一条 close,算出被抹掉的原值。"""
    conn = _mem_conn()
    _insert_row(conn, "20250908", "thsc_300816", PREV_CLOSE, pct=0.0)
    rows = [("20250909", "thsc_300816", None, None, None, FIRST_CLOSE, None, None)]
    out = index_pct.fill_first_pct(rows, conn, "thsc_300816")
    assert out[0][6] == pytest.approx(EXPECTED_PCT, abs=1e-6)


def test_a2_no_prev_keeps_null():
    """A2:该序列真正的第一行(库里没有更早 close)⇒ 保持 NULL,不编数。"""
    conn = _mem_conn()
    rows = [("20200102", "brand_new", None, None, None, 100.0, None, None)]
    out = index_pct.fill_first_pct(rows, conn, "brand_new")
    assert out[0][6] is None


def test_a3_close_null_not_filled():
    """A3:close 为 NULL 的行是真缺行,即使有 prev 也不许填 pct。"""
    conn = _mem_conn()
    _insert_row(conn, "20250908", "thsc_300816", PREV_CLOSE, pct=0.0)
    rows = [("20250909", "thsc_300816", None, None, None, None, None, None)]
    out = index_pct.fill_first_pct(rows, conn, "thsc_300816")
    assert out[0][6] is None


def test_a4_existing_pct_untouched():
    """A4:已有 pct 的行一律不动(只补空,不重算)。"""
    conn = _mem_conn()
    _insert_row(conn, "20250908", "thsc_300816", PREV_CLOSE, pct=0.0)
    rows = [("20250909", "thsc_300816", None, None, None, FIRST_CLOSE, 7.7, None)]
    out = index_pct.fill_first_pct(rows, conn, "thsc_300816")
    assert out[0][6] == 7.7


def test_a5_upsert_end_to_end_fills_first_pct(tmp_db):
    """A5:经真实 upsert 写入(全仓唯一主写入入口)首行 pct 自动补上。"""
    conn = app_db.get_conn()
    conn.execute(
        "INSERT INTO index_daily (date, index_id, close, pct_change) VALUES (?,?,?,?)",
        ("20250908", "thsc_300816", PREV_CLOSE, 0.0),
    )
    conn.commit()
    conn.close()

    runner.upsert_index_rows(
        [("20250909", "thsc_300816", 3900.0, 3910.0, 3860.0, FIRST_CLOSE, None, None)],
        caller="runner",
    )
    got = _read(tmp_db, "SELECT pct_change FROM index_daily WHERE date=? AND index_id=?",
                ("20250909", "thsc_300816"))
    assert got[0] == pytest.approx(EXPECTED_PCT, abs=1e-6)


# ────────────────────────── B. 写入层(四种组合) ──────────────────────────

def _seed_and_upsert(tmp_db, old_close, old_pct, new_close, new_pct):
    conn = app_db.get_conn()
    conn.execute(
        "INSERT INTO index_daily (date, index_id, close, pct_change) VALUES (?,?,?,?)",
        ("20260101", "b_case", old_close, old_pct),
    )
    conn.commit()
    conn.close()
    runner.upsert_index_rows(
        [("20260101", "b_case", None, None, None, new_close, new_pct, None)], caller="runner")
    return _read(tmp_db, "SELECT pct_change FROM index_daily WHERE date=? AND index_id=?",
                 ("20260101", "b_case"))[0]


def test_b1_close_same_pct_none_keeps_old(tmp_db):
    """B1:价没变、pct 变空 ⇒ 保留旧值(原行为会抹成 NULL)。"""
    assert _seed_and_upsert(tmp_db, 100.0, 1.5, 100.0, None) == 1.5


def test_b2_close_changed_pct_none_becomes_null(tmp_db):
    """B2:close 真变 + pct 空 ⇒ 照常写 NULL(不挡真缺行/真修正)。"""
    assert _seed_and_upsert(tmp_db, 100.0, 1.5, 101.0, None) is None


def test_b3_close_same_pct_value_overwrites(tmp_db):
    """B3:价没变、pct 有新值(如舍入修正)⇒ 覆盖新值。"""
    assert _seed_and_upsert(tmp_db, 100.0, 1.5, 100.0, 2.0) == 2.0


def test_b4_close_changed_pct_value_overwrites(tmp_db):
    """B4:价变 + pct 有新值 ⇒ 覆盖新值。"""
    assert _seed_and_upsert(tmp_db, 100.0, 1.5, 101.0, 2.0) == 2.0


# ────────────────────────── C. 端到端(两种采集器的构造样本) ──────────────────────────

def _df_thsc():
    """thsc 构造样本:首行 2025-09-09(无 prev),次行 2025-09-10。"""
    import pandas as pd
    return pd.DataFrame([
        {"日期": "2025-09-09", "开盘价": 3900.0, "最高价": 3910.0, "最低价": 3865.0,
         "收盘价": FIRST_CLOSE, "成交额": 1.0e9},
        {"日期": "2025-09-10", "开盘价": 3870.0, "最高价": 3890.0, "最低价": 3860.0,
         "收盘价": 3880.0, "成交额": 1.1e9},
    ])


def _df_global():
    """海外指数构造样本(新浪全局接口无涨跌幅列):首行 2022-11-11。"""
    import pandas as pd
    return pd.DataFrame([
        {"date": "2022-11-11", "open": 7400.0, "high": 7450.0, "low": 7350.0,
         "close": 7425.5, "volume": 1.0e6},
        {"date": "2022-11-14", "open": 7425.0, "high": 7470.0, "low": 7400.0,
         "close": 7440.0, "volume": 1.1e6},
    ])


def test_e2e_thsc_first_row_pct_filled(tmp_db, monkeypatch):
    """E2E-1:thsc 采集器返回的首行(pct=None)经 upsert 后库里 pct 有值。"""
    from app.collector import fetchers
    df = _df_thsc()
    monkeypatch.setattr(fetchers, "_safe_call_guarded", lambda fn, **kw: df)
    idx = {"id": "thsc_300816", "func": "index_hist_ths_concept", "symbol": "第三代半导体"}
    rows, status = fetchers.collect_index(idx, "20250908", "20250910")
    assert status == "ok"
    assert rows[0][6] is None, "前置:采集器首行确实没有 prev(修法的目标场景)"

    conn = app_db.get_conn()
    conn.execute("INSERT INTO index_daily (date, index_id, close, pct_change) VALUES (?,?,?,?)",
                 ("20250908", "thsc_300816", PREV_CLOSE, 0.0))
    conn.commit()
    conn.close()
    runner.upsert_index_rows(rows, caller="runner")
    got = _read(tmp_db, "SELECT pct_change FROM index_daily WHERE date=? AND index_id=?",
                ("20250909", "thsc_300816"))
    assert got[0] == pytest.approx(EXPECTED_PCT, abs=1e-6)


def test_e2e_global_first_row_pct_filled(tmp_db, monkeypatch):
    """E2E-2:海外指数(新浪全局,无涨跌幅列)首行同样补上。"""
    from app.collector import fetchers
    df = _df_global()
    monkeypatch.setattr(fetchers, "_safe_call_guarded", lambda fn, **kw: df)
    monkeypatch.setattr(fetchers.ak, "index_global_hist_sina", lambda **kw: df, raising=False)
    idx = {"id": "ftse100", "func": "index_global_hist_sina", "symbol": "英国富时100指数"}
    rows, status = fetchers.collect_index(idx, "20221101", "20221114")
    assert status == "ok"
    assert rows[0][6] is None

    conn = app_db.get_conn()
    conn.execute("INSERT INTO index_daily (date, index_id, close, pct_change) VALUES (?,?,?,?)",
                 ("20221110", "ftse100", 7400.0, 0.0))
    conn.commit()
    conn.close()
    runner.upsert_index_rows(rows, caller="runner")
    got = _read(tmp_db, "SELECT pct_change FROM index_daily WHERE date=? AND index_id=?",
                ("20221111", "ftse100"))
    assert got[0] == pytest.approx((7425.5 / 7400.0 - 1.0) * 100.0, abs=1e-9)


def test_e2e_thsc_year_gap_warns(monkeypatch, capsys):
    """E2E-3:thsc 首行比请求起拉日晚 >5 天(分年 chunk 被静默跳过)⇒ 打 warn 日志。"""
    from app.collector import fetchers
    import pandas as pd
    df = pd.DataFrame([{"日期": "2026-01-05", "开盘价": 1.0, "最高价": 1.0, "最低价": 1.0,
                        "收盘价": 1.0, "成交额": 1.0}])
    monkeypatch.setattr(fetchers, "_safe_call_guarded", lambda fn, **kw: df)
    idx = {"id": "thsc_300816", "func": "index_hist_ths_concept", "symbol": "x"}
    fetchers.collect_index(idx, "20250101", "20260105")
    out = capsys.readouterr().out
    assert "[warn] thsc 分年 chunk 缺失" in out