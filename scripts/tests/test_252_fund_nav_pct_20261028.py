# -*- coding: utf-8 -*-
"""#252 fund_daily_nav 涨跌幅/前值空值根治 自测(2026-10-28;2026-10-28 审查返工增补)。

背景(根因报告 `docs/ops/fund-nav-pct-rootfix-20261028.md`)
  · 采集器「当日未发布 → 回退写前一交易日」路径按设计不写 prev/pct,源端没给「日增长率」时
    也直接落 NULL,两条路径都没有「用库内前一交易日那条 unit_nav 派生 pct」的兜底
    ⇒ 2026-10 攒下 49,295 行 nav_change_pct IS NULL(10-16 单日 24,103)。
  · 修法 A(计算层·单一实现):`app/collector/fund_pct.py` 的
    `prev_trading_date / is_prev_trading_day / prev_nav_from_db / PrevNavCache /
    calc_pct / fill_row_prev_pct / fill_row_pct`,接进 `public_fund.fetch_daily_nav()`。
  · 修法 B(数据层):`scripts/backfill_fund_nav_pct_252.py` 默认 dry-run(只读连接),
    只补 NULL、绝不覆盖、分批 + 回滚清单(先落盘再 commit)+ `--apply` 备份硬门。

口径(2026-10-28 审查裁定):**基准行必须是前一交易日**(`app/calendar.py` 交易日历),
禁用自然日差 1 —— 否则会把 11.1% 跨多日累计涨幅写进「日增长率」。

覆盖
  A. 计算层
    A1 gap=1 ⇒ 派生成功                        A2 列值优先(列日期==前一交易日)
    A3 prev=0 ⇒ None                          A4 无基准行(真首条)⇒ NULL
    A5 pct 已有 ⇒ 不动                         A6 unit 空 ⇒ 不补
    A7 基准行 unit 为空 ⇒ 不派生                A8 calc_pct 边界
    A9 fill_row_pct 包装                       A10 跨周末但交易日相邻 ⇒ 仍派生(守「禁用自然日」)
    A11 gap=2 ⇒ NULL                          A12 跨长假(09-30→10-09)⇒ NULL
    A13 列 prev 日期是 gap2 ⇒ 不采信,改用基准行 A14 日历不可用 ⇒ 保守不派生
    A15 预取路径 vs 逐行路径逐位一致
  B. 端到端(经真实 fetch_daily_nav)
    B1 正常路径源端缺日增长率 ⇒ 派生           B2 回退路径次新列缺失 ⇒ 用基准行
    B3 回退路径列值优先                        B4 真首条仍 NULL
    B5 已有值不被覆盖                          B6 采集端列值 gap2 ⇒ 按限制处理(用基准行)
    B7 采集端列值 gap2 且库内无基准行 ⇒ NULL
  C. 回填脚本
    C1 范围判据                                C2 dry-run 零写入(md5 前后一致)
    C3 apply 只补 NULL + 回滚清单 + 精确还原    C4 apply 幂等
    C5 rollback 只还原仍等于写入值的行          C6 分批全填
    C7 源码形状守卫(无第二份公式)              C8 --apply 备份硬门
    C9 日期格式校验(建议 7)                    C10 回滚清单先落盘:commit 失败 ⇒ 库不变 + 日志回退

§18 L48 零外发:本文件不 import/调用任何通知脚本,全部用内存库或 tmp 库。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.collector import fund_pct  # noqa: E402
from app.collector import public_fund as pf  # noqa: E402
import backfill_fund_nav_pct_252 as bf  # noqa: E402

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fund_daily_nav (
    date TEXT NOT NULL, fund_code TEXT NOT NULL,
    fund_name TEXT, unit_nav REAL, acc_nav REAL,
    prev_unit_nav REAL, nav_change_pct REAL,
    PRIMARY KEY (date, fund_code)
);
"""


def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _ins(conn, date, code, unit, prev=None, pct=None):
    conn.execute(
        "INSERT INTO fund_daily_nav (date, fund_code, unit_nav, prev_unit_nav, nav_change_pct) "
        "VALUES (?,?,?,?,?)", (date, code, unit, prev, pct))
    conn.commit()


def _tmp_db(tmp_path, rows=()) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "public_fund.db"
    conn = sqlite3.connect(p)
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO fund_daily_nav (date, fund_code, unit_nav, prev_unit_nav, nav_change_pct) "
        "VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return p


def _q(db, sql, args=()):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


# 2026-10 真实交易日历(见 data/trade_dates.txt):
#   09-29 09-30 [10-01..10-07 国庆休市] 10-08 10-09 10-12 10-13 10-14 10-15 10-16
#   10-19 10-20 10-21 ...(10-17/18 周末)

# ────────────────────────── A. 计算层(单一实现) ──────────────────────────

def test_a1_gap1_derive():
    """A1:本行 prev 空、前一交易日(10-19)unit=1.0 ⇒ prev=1.0,pct=10%。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000001", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000001", 1.1, None, None, fund_pct.PrevNavCache(conn))
    assert prev == pytest.approx(1.0)
    assert pct == pytest.approx(10.0)


def test_a2_column_prev_wins_when_date_is_prev_trading_day():
    """A2:列 prev=1.5 且列日期==前一交易日(10-19)⇒ 必须用列值(同源更可信)。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000002", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000002", 1.65, 1.5, None, fund_pct.PrevNavCache(conn),
        prev_unit_date="20261019")
    assert prev == pytest.approx(1.5)
    assert pct == pytest.approx(10.0)


def test_a3_base_zero_returns_none():
    """A3:基准为 0 不可算 ⇒ pct None(不编数)。"""
    conn = _mem_conn()
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000003", 1.1, 0.0, None, fund_pct.PrevNavCache(conn),
        prev_unit_date="20261019")
    assert prev == pytest.approx(0.0)
    assert pct is None


def test_a4_no_base_row_keeps_null():
    """A4:该基金库里首条(前一交易日无行)⇒ prev/pct 都 None,不编数。"""
    conn = _mem_conn()
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "brand_new", 1.0, None, None, fund_pct.PrevNavCache(conn))
    assert prev is None and pct is None


def test_a5_existing_pct_untouched():
    """A5:pct 已有值 ⇒ 两列原样返回(只补空,不重算、不覆盖源端口径)。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000004", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000004", 1.1, None, 7.7, fund_pct.PrevNavCache(conn))
    assert prev is None and pct == 7.7


def test_a6_unit_null_not_filled():
    """A6:unit 空 ⇒ 不补(当日没有净值,算不出涨跌幅,也不编 prev)。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000005", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000005", None, None, None, fund_pct.PrevNavCache(conn))
    assert prev is None and pct is None


def test_a7_base_row_null_unit_not_used():
    """A7:基准行 unit_nav 为空 ⇒ 不可算(不许继续往前拿更早的,那会变跨多日)。"""
    conn = _mem_conn()
    _ins(conn, "20261016", "000006", 1.0, pct=0.0)
    _ins(conn, "20261019", "000006", None)  # 前一交易日缺净值
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000006", 1.1, None, None, fund_pct.PrevNavCache(conn))
    assert prev is None and pct is None


def test_a8_calc_pct_edges():
    """A8:calc_pct 三条边界(正常/None/prev=0)。"""
    assert fund_pct.calc_pct(1.1, 1.0) == pytest.approx(10.0)
    assert fund_pct.calc_pct(None, 1.0) is None
    assert fund_pct.calc_pct(1.1, 0) is None


def test_a9_fill_row_pct_wrapper_returns_pct_only():
    """A9:fill_row_pct 只返 pct(供只补 pct 的调用点用),内部走同一实现。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000007", 2.0, pct=0.0)
    cache = fund_pct.PrevNavCache(conn)
    assert fund_pct.fill_row_pct("20261020", "000007", 2.2, None, cache) == pytest.approx(10.0)
    assert fund_pct.fill_row_pct("20261020", "000007", 2.2, 3.3, cache) == 3.3


def test_a10_cross_weekend_but_adjacent_trading_days_still_derive():
    """A10(守「禁用自然日」):10-16(周五)→10-19(周一)自然日差 3,但交易日相邻 ⇒ 必须派生。

    变异靶②:把判据换成「自然日差 1」⇒ 本条必红。
    """
    assert fund_pct.prev_trading_date("20261019") == "20261016"
    conn = _mem_conn()
    _ins(conn, "20261016", "000010", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261019", "000010", 1.1, None, None, fund_pct.PrevNavCache(conn))
    assert prev == pytest.approx(1.0)
    assert pct == pytest.approx(10.0)


def test_a11_gap2_keeps_null():
    """A11(变异靶①):只有 10-16 的行,目标 10-20(前一交易日=10-19)⇒ 不得跨 2 个交易日派生。"""
    assert fund_pct.prev_trading_date("20261020") == "20261019"
    conn = _mem_conn()
    _ins(conn, "20261016", "000011", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000011", 1.1, None, None, fund_pct.PrevNavCache(conn))
    assert prev is None and pct is None


def test_a12_long_holiday_gap_keeps_null():
    """A12:09-30 → 10-09(前一交易日=10-08,国庆休市 10-01..07)⇒ NULL,不许当一日涨幅。"""
    assert fund_pct.prev_trading_date("20261009") == "20261008"
    conn = _mem_conn()
    _ins(conn, "20260930", "000012", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261009", "000012", 1.1, None, None, fund_pct.PrevNavCache(conn))
    assert prev is None and pct is None


def test_a13_column_prev_from_gap2_not_trusted():
    """A13:源端 prev 列值来自 10-16(跨 2 个交易日),目标 10-20 ⇒ 不采信,改用基准行(10-19)。

    prev 与 pct 必须同一口径(§22 一致性):都取基准行 1.0 ⇒ pct=10%。
    """
    conn = _mem_conn()
    _ins(conn, "20261019", "000013", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct(
        "20261020", "000013", 1.1, 1.05, None, fund_pct.PrevNavCache(conn),
        prev_unit_date="20261016")
    assert prev == pytest.approx(1.0)
    assert pct == pytest.approx(10.0)


def test_a14_calendar_unavailable_fails_closed(monkeypatch):
    """A14:交易日历不可用 ⇒ 保守不派生(绝不退化成自然日口径)。"""
    monkeypatch.setattr(fund_pct, "calendar_available", lambda: False)
    fund_pct.prev_trading_date.cache_clear()
    try:
        assert fund_pct.prev_trading_date("20261020") is None
        conn = _mem_conn()
        _ins(conn, "20261019", "000014", 1.0, pct=0.0)
        prev, pct = fund_pct.fill_row_prev_pct(
            "20261020", "000014", 1.1, None, None, fund_pct.PrevNavCache(conn))
        assert prev is None and pct is None
    finally:
        fund_pct.prev_trading_date.cache_clear()


def test_a15_prefetch_equals_per_row_lookup():
    """A15:预取路径(PrevNavCache)与逐行点查(prev_nav_from_db)结果逐位一致。"""
    conn = _mem_conn()
    rows = [("20261015", "X", 1.00), ("20261016", "X", 1.05), ("20261019", "X", 1.10),
            ("20261016", "Y", 2.00), ("20261019", "Y", 2.10),
            ("20261019", "Z", None), ("20261012", "W", 0.5)]
    for d, code, unit in rows:
        _ins(conn, d, code, unit, pct=0.0)
    cache = fund_pct.PrevNavCache(conn)
    checked = 0
    for date in ("20261016", "20261019", "20261020"):
        for code in ("X", "Y", "Z", "W", "NOPE"):
            a = cache.prev_nav(code, date)
            b = fund_pct.prev_nav_from_db(conn, code, date)
            assert a == b or (a is None and b is None), (date, code, a, b)
            checked += 1
    assert checked == 15


# ────────────────────── B. 端到端(经真实 fetch_daily_nav) ──────────────────────

def _df(cols, rows):
    return pd.DataFrame(rows, columns=cols)


def _run_fetch(df: pd.DataFrame, db_path: Path) -> int:
    """把模块 DB_PATH / ak 源函数换成测试替身,调用**真实** fetch_daily_nav(不复制第二份 SQL)。

    CI 上 akshare 是空 ModuleType(conftest stub)⇒ 不得在替换前读属性;恢复时按
    「原本有则 setattr、原本无则 delattr」。
    """
    orig_db = pf.DB_PATH
    had_attr = hasattr(pf.ak, "fund_open_fund_daily_em")
    orig_ak = getattr(pf.ak, "fund_open_fund_daily_em", None)
    pf.DB_PATH = db_path
    pf.ak.fund_open_fund_daily_em = lambda *a, **k: df
    try:
        return pf.fetch_daily_nav()
    finally:
        pf.DB_PATH = orig_db
        if had_attr:
            pf.ak.fund_open_fund_daily_em = orig_ak
        else:
            del pf.ak.fund_open_fund_daily_em


def test_b1_normal_path_missing_source_pct_derived(tmp_path):
    """B1:正常路径(当日已发布),源端「日增长率」缺失 ⇒ 用前一交易日(列/库)派生 pct。"""
    db = _tmp_db(tmp_path, [("20261016", "A", 0.9, None, 0.0)])
    df = _df(
        ["基金代码", "基金简称", "2026-10-20-单位净值", "2026-10-20-累计净值",
         "2026-10-19-单位净值", "2026-10-19-累计净值", "日增长率"],
        [{"基金代码": "A", "基金简称": "甲", "2026-10-20-单位净值": "1.10",
          "2026-10-20-累计净值": "1.10", "2026-10-19-单位净值": "1.00",
          "2026-10-19-累计净值": "1.00", "日增长率": ""},
         {"基金代码": "B", "基金简称": "乙", "2026-10-20-单位净值": "1.05",
          "2026-10-20-累计净值": "1.05", "2026-10-19-单位净值": "1.00",
          "2026-10-19-累计净值": "1.00", "日增长率": "5.00"}],
    )
    assert _run_fetch(df, db) == 2
    got = {r["fund_code"]: r for r in _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020'")}
    assert got["A"]["prev_unit_nav"] == pytest.approx(1.0)
    assert got["A"]["nav_change_pct"] == pytest.approx(10.0)  # 用列值(1.0),不是库里的 0.9
    assert got["B"]["nav_change_pct"] == pytest.approx(5.0)   # 源端有值 ⇒ 原样


def test_b2_fallback_path_prev_from_base_row(tmp_path):
    """B2:回退路径(当日列未发布)且次新列缺失 ⇒ prev 用前一交易日那一行,pct 一并派生。"""
    db = _tmp_db(tmp_path, [("20261019", "C", 1.0, None, 0.0)])
    df = _df(
        ["基金代码", "基金简称", "2026-10-20-单位净值", "2026-10-20-累计净值", "日增长率"],
        [{"基金代码": "C", "基金简称": "丙",
          "2026-10-20-单位净值": "1.10", "2026-10-20-累计净值": "1.10", "日增长率": ""}],
    )
    assert _run_fetch(df, db) == 1
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='C'")[0]
    assert row["prev_unit_nav"] == pytest.approx(1.0)
    assert row["nav_change_pct"] == pytest.approx(10.0)
    assert _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261021'") == []


def test_b3_fallback_path_column_prev_wins(tmp_path):
    """B3:回退路径次新列 prev=1.5(列日期=前一交易日)⇒ 必须用列值 1.5。"""
    db = _tmp_db(tmp_path, [("20261019", "D", 1.0, None, 0.0)])
    df = _df(
        ["基金代码", "基金简称", "2026-10-21-单位净值", "2026-10-21-累计净值",
         "2026-10-20-单位净值", "2026-10-20-累计净值",
         "2026-10-19-单位净值", "2026-10-19-累计净值", "日增长率"],
        [{"基金代码": "D", "基金简称": "丁", "2026-10-21-单位净值": "",
          "2026-10-21-累计净值": "", "2026-10-20-单位净值": "1.65",
          "2026-10-20-累计净值": "1.65", "2026-10-19-单位净值": "1.50",
          "2026-10-19-累计净值": "1.50", "日增长率": "0.00"}],
    )
    assert _run_fetch(df, db) == 1
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='D'")[0]
    assert row["prev_unit_nav"] == pytest.approx(1.5)
    assert row["nav_change_pct"] == pytest.approx(10.0)


def test_b4_true_first_row_stays_null(tmp_path):
    """B4:该基金库里首条(无前一交易日净值)⇒ 经真实写入后 pct 仍 NULL(不编数)。"""
    db = _tmp_db(tmp_path)
    df = _df(
        ["基金代码", "基金简称", "2026-10-20-单位净值", "2026-10-20-累计净值",
         "2026-10-19-单位净值", "2026-10-19-累计净值", "日增长率"],
        [{"基金代码": "NEW", "基金简称": "新基", "2026-10-20-单位净值": "1.00",
          "2026-10-20-累计净值": "1.00", "2026-10-19-单位净值": "",
          "2026-10-19-累计净值": "", "日增长率": ""}],
    )
    assert _run_fetch(df, db) == 1
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='NEW'")[0]
    assert row["unit_nav"] == pytest.approx(1.0)
    assert row["prev_unit_nav"] is None
    assert row["nav_change_pct"] is None


def test_b5_existing_row_values_not_overwritten(tmp_path):
    """B5(回归锁):回退重写已有行时,COALESCE 不许把已有 prev/pct 抹掉。"""
    db = _tmp_db(tmp_path, [("20261020", "E", 1.0, 0.98, 2.04)])
    df = _df(
        ["基金代码", "基金简称", "2026-10-21-单位净值", "2026-10-21-累计净值",
         "2026-10-20-单位净值", "2026-10-20-累计净值", "日增长率"],
        [{"基金代码": "E", "基金简称": "戊", "2026-10-21-单位净值": "",
          "2026-10-21-累计净值": "", "2026-10-20-单位净值": "1.00",
          "2026-10-20-累计净值": "1.00", "日增长率": "0.00"}],
    )
    _run_fetch(df, db)
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='E'")[0]
    assert row["prev_unit_nav"] == pytest.approx(0.98)   # 原值保留
    assert row["nav_change_pct"] == pytest.approx(2.04)


def test_b6_collector_column_prev_gap2_uses_base_row(tmp_path):
    """B6(变异靶①):采集端源端 prev 列来自 10-16(gap2),库里有 10-19 基准行 ⇒ 用基准行。

    期望:prev=1.0(基准行)、pct=10%(而不是拿 1.05 算出的 4.76% 跨两日累计)。
    """
    db = _tmp_db(tmp_path, [("20261019", "F", 1.0, None, 0.0)])
    df = _df(
        ["基金代码", "基金简称", "2026-10-20-单位净值", "2026-10-20-累计净值",
         "2026-10-16-单位净值", "2026-10-16-累计净值", "日增长率"],
        [{"基金代码": "F", "基金简称": "己", "2026-10-20-单位净值": "1.10",
          "2026-10-20-累计净值": "1.10", "2026-10-16-单位净值": "1.05",
          "2026-10-16-累计净值": "1.05", "日增长率": ""}],
    )
    assert _run_fetch(df, db) == 1
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='F'")[0]
    assert row["prev_unit_nav"] == pytest.approx(1.0)
    assert row["nav_change_pct"] == pytest.approx(10.0)


def test_b7_collector_column_prev_gap2_no_base_keeps_null(tmp_path):
    """B7:同上但库里没有前一交易日基准行(10-16 事件)⇒ pct 必须 NULL(不许跨日编数)。"""
    db = _tmp_db(tmp_path)
    df = _df(
        ["基金代码", "基金简称", "2026-10-20-单位净值", "2026-10-20-累计净值",
         "2026-10-16-单位净值", "2026-10-16-累计净值", "日增长率"],
        [{"基金代码": "G", "基金简称": "庚", "2026-10-20-单位净值": "1.10",
          "2026-10-20-累计净值": "1.10", "2026-10-16-单位净值": "1.05",
          "2026-10-16-累计净值": "1.05", "日增长率": ""}],
    )
    assert _run_fetch(df, db) == 1
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='G'")[0]
    assert row["nav_change_pct"] is None
    assert row["prev_unit_nav"] == pytest.approx(1.05)  # 源值保留,不抹数据


# ────────────────────────── C. 回填脚本 ──────────────────────────

def _bf_fixture(tmp_path) -> Path:
    """覆盖全部桶:
    A_UNITNULL  unit 空 / D_FIRST 真首条 / E_OK pct 已有 /
    B_BUCKET    prev 空有基准行(补 prev+pct) / C_BUCKET 有 prev 且一致(只补 pct) /
    H_GAP       只有 10-16 行(跨 2 个交易日 ⇒ 正确留 NULL) /
    M_MISMATCH  prev 与基准行不一致(历史 gap2 列值 ⇒ 不派生)。
    """
    return _tmp_db(tmp_path, [
        ("20261001", "A_UNITNULL", None, None, None),
        ("20261019", "A_UNITNULL", 1.0, None, 0.0),
        ("20261019", "B_BUCKET", 1.0, None, 0.0),
        ("20261020", "B_BUCKET", 1.1, None, None),
        ("20261019", "C_BUCKET", 1.1, None, 0.0),
        ("20261020", "C_BUCKET", 1.21, 1.1, None),
        ("20261020", "D_FIRST", 1.0, None, None),
        ("20261019", "E_OK", 1.0, None, 0.0),
        ("20261020", "E_OK", 1.1, 1.0, 9.99),
        ("20261016", "H_GAP", 1.0, None, 0.0),
        ("20261020", "H_GAP", 1.1, None, None),
        ("20261019", "M_MISMATCH", 1.0, None, 0.0),
        ("20261020", "M_MISMATCH", 1.1, 1.05, None),
    ])


def test_c1_plan_scope(tmp_path):
    """C1:范围判据——unit 空/真首条/跨多日/prev 不一致/pct 已有 都不进计划。"""
    db = _bf_fixture(tmp_path)
    conn = bf._open_ro(db)
    try:
        rows, stats = [], {}
        for kind, payload in bf.iter_plan(conn, "20261001", "20261031"):
            if kind == "stats":
                stats = payload
            else:
                rows.append(payload)
    finally:
        conn.close()
    plan = {(r["date"], r["fund_code"]): r for r in rows}
    assert set(plan) == {("20261020", "B_BUCKET"), ("20261020", "C_BUCKET")}
    assert plan[("20261020", "B_BUCKET")]["fill_prev"] is True
    assert plan[("20261020", "B_BUCKET")]["new_prev"] == pytest.approx(1.0)
    assert plan[("20261020", "B_BUCKET")]["new_pct"] == pytest.approx(10.0)
    assert plan[("20261020", "C_BUCKET")]["fill_prev"] is False
    assert plan[("20261020", "C_BUCKET")]["new_pct"] == pytest.approx(10.0)
    assert stats["unit_null"] == 1          # A_UNITNULL
    assert stats["underivable"] == 2         # D_FIRST + H_GAP(跨多日)
    assert stats["prev_mismatch"] == 1       # M_MISMATCH
    assert stats["plan"] == 2


def test_c2_dry_run_zero_write(tmp_path, capsys):
    """C2:dry-run 前后库文件 md5 完全一致(只读连接 + query_only,物理零写入)。"""
    db = _bf_fixture(tmp_path)
    before = _md5(db)
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031"]) == 0
    assert _md5(db) == before, "dry-run 改动了库文件(违规)"
    out = capsys.readouterr().out
    assert "本次将补 pct: 2 行" in out
    assert "[dry-run] 未写库" in out


def _copy_db(db: Path, tmp_path) -> Path:
    """造一份「一致副本」备份(用 sqlite backup API,等价 sqlite3 .backup)。"""
    dst = tmp_path / "backup.db"
    src = sqlite3.connect(db)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def test_c3_apply_fills_only_null_and_rollback(tmp_path):
    """C3:apply 只补 NULL + 回滚清单可精确还原;备份硬门必须过。"""
    db = _bf_fixture(tmp_path)
    log = tmp_path / "rollback.jsonl"
    bak = _copy_db(db, tmp_path)
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log, backup_path=bak) == 0
    got = {(r["date"], r["fund_code"]): r for r in
           _q(db, "SELECT * FROM fund_daily_nav")}
    assert got[("20261020", "B_BUCKET")]["nav_change_pct"] == pytest.approx(10.0)
    assert got[("20261020", "B_BUCKET")]["prev_unit_nav"] == pytest.approx(1.0)
    assert got[("20261020", "C_BUCKET")]["nav_change_pct"] == pytest.approx(10.0)
    assert got[("20261020", "C_BUCKET")]["prev_unit_nav"] == pytest.approx(1.1)  # 原值不改
    assert got[("20261020", "E_OK")]["nav_change_pct"] == pytest.approx(9.99)    # 绝不覆盖
    assert got[("20261001", "A_UNITNULL")]["nav_change_pct"] is None              # 不可派生
    assert got[("20261020", "D_FIRST")]["nav_change_pct"] is None                 # 真首条
    assert got[("20261020", "H_GAP")]["nav_change_pct"] is None                   # 跨多日
    assert got[("20261020", "M_MISMATCH")]["nav_change_pct"] is None              # prev 不一致
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2                 # 逐行回滚清单

    assert bf.do_rollback(db, log, 5000) == 0
    back = {(r["date"], r["fund_code"]): r for r in
            _q(db, "SELECT * FROM fund_daily_nav")}
    assert back[("20261020", "B_BUCKET")]["nav_change_pct"] is None
    assert back[("20261020", "B_BUCKET")]["prev_unit_nav"] is None
    assert back[("20261020", "C_BUCKET")]["nav_change_pct"] is None
    assert back[("20261020", "C_BUCKET")]["prev_unit_nav"] == pytest.approx(1.1)


def test_c4_apply_idempotent(tmp_path):
    """C4:apply 可中断可续跑——重跑一次写入 0 行(只补 NULL ⇒ 天然幂等)。"""
    db = _bf_fixture(tmp_path)
    bak = _copy_db(db, tmp_path)
    log1 = tmp_path / "r1.jsonl"
    log2 = tmp_path / "r2.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log1, backup_path=bak) == 0
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log2, backup_path=bak) == 0
    assert log2.read_text(encoding="utf-8") == ""


def test_c5_rollback_skips_rows_changed_by_others(tmp_path):
    """C5:回滚只还原「当前值仍等于我们写入值」的行;被别人改过的跳过并报告。"""
    db = _bf_fixture(tmp_path)
    bak = _copy_db(db, tmp_path)
    log = tmp_path / "r.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log, backup_path=bak) == 0
    conn = sqlite3.connect(db)
    conn.execute("UPDATE fund_daily_nav SET nav_change_pct=99.9 "
                 "WHERE date='20261020' AND fund_code='B_BUCKET'")
    conn.commit()
    conn.close()
    assert bf.do_rollback(db, log, 5000) == 4   # 有跳过的行 ⇒ 非 0(如实报告)
    got = {(r["date"], r["fund_code"]): r for r in
           _q(db, "SELECT * FROM fund_daily_nav")}
    assert got[("20261020", "B_BUCKET")]["nav_change_pct"] == pytest.approx(99.9)  # 不碰
    assert got[("20261020", "C_BUCKET")]["nav_change_pct"] is None                 # 已还原


def test_c6_apply_multi_batch(tmp_path):
    """C6:分批写(每批 2 行)覆盖多批,全部填对;回滚清单行数=计划行数。"""
    rows = []
    for i in range(5):
        code = f"F{i}"
        rows.append(("20261019", code, 1.0, None, 0.0))
        rows.append(("20261020", code, 1.1, None, None))
    db = _tmp_db(tmp_path, rows)
    bak = _copy_db(db, tmp_path)
    log = tmp_path / "r.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 2, log_path=log, backup_path=bak) == 0
    assert len(log.read_text(encoding="utf-8").splitlines()) == 5
    got = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020'")
    assert len(got) == 5
    assert all(r["nav_change_pct"] == pytest.approx(10.0) for r in got)


def test_c7_no_second_formula_in_backfill_script():
    """C7(源码形状守卫):回填脚本不得复制第二份公式——只 import fund_pct 的实现。"""
    src = (ROOT / "scripts" / "backfill_fund_nav_pct_252.py").read_text(encoding="utf-8")
    assert "from app.collector.fund_pct import PrevNavCache, calc_pct" in src
    assert "* 100" not in src and "*100" not in src, "回填脚本里出现了第二份 pct 公式"
    assert "- 1.0" not in src and "-1.0" not in src, "回填脚本里出现了第二份 pct 公式"


def test_c8_apply_backup_hard_gate(tmp_path):
    """C8:--apply 备份硬门——不给/不存在/指向库本身/非 SQLite/行数不符 都必须拒绝且零写入。"""
    db = _bf_fixture(tmp_path)
    before = _md5(db)
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031",
                    "--apply"]) == 2
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031",
                    "--apply", "--backup-confirm", str(tmp_path / "nope.db")]) == 2
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031",
                    "--apply", "--backup-confirm", str(db)]) == 2
    fake = tmp_path / "fake.db"
    fake.write_text("not a sqlite file")
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031",
                    "--apply", "--backup-confirm", str(fake)]) == 2
    # 行数不符的备份(空库)
    short = _tmp_db(tmp_path / "short", [])
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031",
                    "--apply", "--backup-confirm", str(short)]) == 2
    assert _md5(db) == before, "备份门拒绝时不得写库"
    ok, msg = bf._verify_backup(db, _copy_db(db, tmp_path))
    assert ok and "PASS" in msg


def test_c9_date_format_validation(tmp_path, capsys):
    """C9(建议 7):--from/--to 必须是 8 位 YYYYMMDD;传 2026-10-01 必须报错而不是静默 0 行。"""
    db = _bf_fixture(tmp_path)
    before = _md5(db)
    assert bf.main(["--db", str(db), "--from", "2026-10-01", "--to", "20261031"]) == 2
    assert "8 位" in capsys.readouterr().out
    assert bf.main(["--db", str(db), "--from", "20261001", "--to", "20261031--"]) == 2
    assert bf.main(["--db", str(db), "--from", "20260231"]) == 2  # 不存在的日期
    assert _md5(db) == before


def test_c10_rollback_log_written_before_commit(tmp_path, monkeypatch):
    """C10(必修 4):commit 失败 ⇒ 库不变 + 该批回滚日志回退(不留「以为写了」的记录)。"""
    db = _bf_fixture(tmp_path)
    bak = _copy_db(db, tmp_path)
    log = tmp_path / "boom.jsonl"

    class _CommitBoom:
        def __init__(self, conn):
            self._c = conn

        def __getattr__(self, name):
            return getattr(self._c, name)

        def commit(self):
            raise sqlite3.OperationalError("simulated commit failure")

    real_open_rw = bf._open_rw
    monkeypatch.setattr(bf, "_open_rw",
                        lambda p: _CommitBoom(real_open_rw(p)))
    with pytest.raises(sqlite3.OperationalError):
        bf.do_apply(db, "20261001", "20261031", 5000, log_path=log, backup_path=bak)
    got = {(r["date"], r["fund_code"]): r for r in
           _q(db, "SELECT * FROM fund_daily_nav")}
    assert got[("20261020", "B_BUCKET")]["nav_change_pct"] is None  # 未写库
    assert log.read_bytes() == b"", "commit 失败后回滚日志必须回退到本批起点"