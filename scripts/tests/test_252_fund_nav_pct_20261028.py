# -*- coding: utf-8 -*-
"""#252 fund_daily_nav 涨跌幅/前值空值根治 自测(2026-10-28)。

背景(根因报告 /tmp/navnull-rootcause-report.md)
  · 采集器「当日未发布 → 回退写前一交易日」路径按设计不写 prev/pct,源端没给「日增长率」时
    也直接落 NULL,两条路径都没有「用库内更早一条 unit_nav 派生 pct」的兜底
    ⇒ 2026-10 攒下 49,295 行 nav_change_pct IS NULL(10-16 单日 24,103)。
  · 修法 A(计算层·单一实现):`app/collector/fund_pct.py` 的
    `prev_nav_from_db / calc_pct / fill_row_prev_pct / fill_row_pct`,
    接进 `public_fund.fetch_daily_nav()` 的两条路径(正常路径 + 回退路径)。
  · 修法 B(数据层):`scripts/backfill_fund_nav_pct_252.py` 默认 dry-run(只读连接),
    只补 NULL、绝不覆盖、分批 + 回滚清单。

覆盖
  A1 有更早净值 ⇒ 派生对        A2 列值优先于库值(优先级断言,变异②的靶)
  A3 prev=0 ⇒ None              A4 无更早净值(真首条)⇒ 保持 NULL,不编数
  A5 pct 已有 ⇒ 不动            A6 unit 空 ⇒ 不补
  A7 prev 跳过 unit 为空的更早行 A8 calc_pct 边界
  B1 正常路径:源端没给日增长率 ⇒ 库/列派生   B2 回退路径·列缺失 ⇒ 用库值补 prev+pct
  B3 回退路径·列存在 ⇒ 列值优先(变异②)      B4 真首条经真实写入函数仍 NULL
  C1 回填脚本范围判据(5 类行)   C2 dry-run 零写入(文件 md5 前后一致)
  C3 apply 只补 NULL + 回滚清单 + rollback 精确还原   C4 apply 幂等(重跑 0 行)
  C5 rollback 只还原「当前值仍等于我们写入值」的行     C6 分批(每批 2 行)全填
  C7 源码形状守卫:回填脚本不含第二份公式(只调 fund_pct)

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


# ────────────────────────── A. 计算层(单一实现) ──────────────────────────

def test_a1_derive_with_db_prev():
    """A1:本行 prev 空、库里更早一条 unit=1.0 ⇒ prev=1.0,pct=10%。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000001", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "000001", 1.1, None, None, conn)
    assert prev == pytest.approx(1.0)
    assert pct == pytest.approx(10.0)


def test_a2_column_prev_wins_over_db():
    """A2(变异②靶):列 prev=1.5、库里更早=1.0 ⇒ 必须用列值 1.5(同源更可信)。"""
    conn = _mem_conn()
    _ins(conn, "20261018", "000002", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "000002", 1.65, 1.5, None, conn)
    assert prev == pytest.approx(1.5)
    assert pct == pytest.approx(10.0)


def test_a3_prev_zero_returns_none():
    """A3:prev=0 不可算 ⇒ pct None(不编数),prev 原样保留。"""
    conn = _mem_conn()
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "000003", 1.1, 0.0, None, conn)
    assert prev == pytest.approx(0.0)
    assert pct is None


def test_a4_no_earlier_row_keeps_null():
    """A4:该基金库里首条(无更早非空 unit)⇒ prev/pct 都 None,不编数。"""
    conn = _mem_conn()
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "brand_new", 1.0, None, None, conn)
    assert prev is None and pct is None


def test_a5_existing_pct_untouched():
    """A5:pct 已有值 ⇒ 两列原样返回(只补空,不重算、不覆盖源端口径)。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000004", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "000004", 1.1, None, 7.7, conn)
    assert prev is None and pct == 7.7


def test_a6_unit_null_not_filled():
    """A6:unit 空 ⇒ 不补(当日没有净值,算不出涨跌幅,也不编 prev)。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000005", 1.0, pct=0.0)
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "000005", None, None, None, conn)
    assert prev is None and pct is None


def test_a7_prev_skips_null_unit_rows():
    """A7:库里最近一条 unit 为 NULL ⇒ 必须继续往前取到更早的非空值(丢了 IS NOT NULL 就红)。"""
    conn = _mem_conn()
    _ins(conn, "20261016", "000006", 1.0, pct=0.0)
    _ins(conn, "20261019", "000006", None)  # 中间一条缺净值,不能当 prev
    prev, pct = fund_pct.fill_row_prev_pct("20261020", "000006", 1.1, None, None, conn)
    assert prev == pytest.approx(1.0)
    assert pct == pytest.approx(10.0)


def test_a8_calc_pct_edges():
    """A8:calc_pct 三条边界(正常/None/prev=0)。"""
    assert fund_pct.calc_pct(1.1, 1.0) == pytest.approx(10.0)
    assert fund_pct.calc_pct(None, 1.0) is None
    assert fund_pct.calc_pct(1.1, 0) is None


def test_a9_fill_row_pct_wrapper_returns_pct_only():
    """A9:fill_row_pct 只返 pct(供只补 pct 的调用点用),内部走同一实现。"""
    conn = _mem_conn()
    _ins(conn, "20261019", "000007", 2.0, pct=0.0)
    assert fund_pct.fill_row_pct("20261020", "000007", 2.2, None, conn) == pytest.approx(10.0)
    assert fund_pct.fill_row_pct("20261020", "000007", 2.2, 3.3, conn) == 3.3


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
    """B1:正常路径(当日已发布),源端「日增长率」缺失 ⇒ 用列 prev 派生 pct。"""
    db = _tmp_db(tmp_path, [("20261018", "A", 0.9, None, 0.0)])
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


def test_b2_fallback_path_prev_from_db(tmp_path):
    """B2:回退路径(当日列未发布)且次新列缺失 ⇒ prev 用库值,pct 一并派生(不再一律 NULL)。"""
    db = _tmp_db(tmp_path, [("20261018", "C", 1.0, None, 0.0)])
    df = _df(
        ["基金代码", "基金简称", "2026-10-21-单位净值", "2026-10-21-累计净值",
         "2026-10-20-单位净值", "2026-10-20-累计净值", "日增长率"],
        [{"基金代码": "C", "基金简称": "丙", "2026-10-21-单位净值": "",
          "2026-10-21-累计净值": "", "2026-10-20-单位净值": "1.10",
          "2026-10-20-累计净值": "1.10", "日增长率": "0.00"}],
    )
    assert _run_fetch(df, db) == 1
    row = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020' AND fund_code='C'")[0]
    assert row["prev_unit_nav"] == pytest.approx(1.0)
    assert row["nav_change_pct"] == pytest.approx(10.0)
    # 未发布的 10-21 不应落行
    assert _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261021'") == []


def test_b3_fallback_path_column_prev_wins(tmp_path):
    """B3(变异②靶):回退路径有次新列 prev=1.5、库里更早=1.0 ⇒ 必须用列值 1.5。"""
    db = _tmp_db(tmp_path, [("20261018", "D", 1.0, None, 0.0)])
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
    """B4:该基金库里首条(无更早净值)⇒ 经真实写入后 pct 仍 NULL(不编数)。"""
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


# ────────────────────────── C. 回填脚本 ──────────────────────────

def _bf_fixture(tmp_path) -> Path:
    """5 类行:unit 空 / B 桶(prev 空可派生) / C 桶(有 prev 只缺 pct) /
    真首条(无更早) / pct 已有。"""
    return _tmp_db(tmp_path, [
        ("20261001", "A_UNITNULL", None, None, None),
        ("20261019", "A_UNITNULL", 1.0, None, 0.0),
        ("20261019", "B_BUCKET", 1.0, None, 0.0),
        ("20261020", "B_BUCKET", 1.1, None, None),
        ("20261019", "C_BUCKET", 1.0, None, 0.0),
        ("20261020", "C_BUCKET", 1.21, 1.1, None),
        ("20261020", "D_FIRST", 1.0, None, None),
        ("20261019", "E_OK", 1.0, None, 0.0),
        ("20261020", "E_OK", 1.1, 1.0, 9.99),
    ])


def test_c1_plan_scope(tmp_path):
    """C1:范围判据——unit 空/真首条/pct 已有 都不进计划;B 桶补 prev+pct;C 桶只补 pct。"""
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
    assert stats["underivable"] == 1        # D_FIRST
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


def test_c3_apply_fills_only_null_and_rollback(tmp_path):
    """C3:apply 只补 NULL(pct 已有 9.99 不动)+ 回滚清单可精确还原。"""
    db = _bf_fixture(tmp_path)
    log = tmp_path / "rollback.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log) == 0
    got = {(r["date"], r["fund_code"]): r for r in
           _q(db, "SELECT * FROM fund_daily_nav")}
    assert got[("20261020", "B_BUCKET")]["nav_change_pct"] == pytest.approx(10.0)
    assert got[("20261020", "B_BUCKET")]["prev_unit_nav"] == pytest.approx(1.0)
    assert got[("20261020", "C_BUCKET")]["nav_change_pct"] == pytest.approx(10.0)
    assert got[("20261020", "C_BUCKET")]["prev_unit_nav"] == pytest.approx(1.1)  # 原值不改
    assert got[("20261020", "E_OK")]["nav_change_pct"] == pytest.approx(9.99)    # 绝不覆盖
    assert got[("20261001", "A_UNITNULL")]["nav_change_pct"] is None              # 不可派生
    assert got[("20261020", "D_FIRST")]["nav_change_pct"] is None                 # 真首条
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
    log1 = tmp_path / "r1.jsonl"
    log2 = tmp_path / "r2.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log1) == 0
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log2) == 0
    assert log2.read_text(encoding="utf-8") == ""


def test_c5_rollback_skips_rows_changed_by_others(tmp_path):
    """C5:回滚只还原「当前值仍等于我们写入值」的行;被别人改过的跳过并报告。"""
    db = _bf_fixture(tmp_path)
    log = tmp_path / "r.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 5000, log_path=log) == 0
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
    log = tmp_path / "r.jsonl"
    assert bf.do_apply(db, "20261001", "20261031", 2, log_path=log) == 0
    assert len(log.read_text(encoding="utf-8").splitlines()) == 5
    got = _q(db, "SELECT * FROM fund_daily_nav WHERE date='20261020'")
    assert len(got) == 5
    assert all(r["nav_change_pct"] == pytest.approx(10.0) for r in got)


def test_c7_no_second_formula_in_backfill_script():
    """C7(源码形状守卫):回填脚本不得复制第二份公式——只 import fund_pct 的 calc_pct。"""
    src = (ROOT / "scripts" / "backfill_fund_nav_pct_252.py").read_text(encoding="utf-8")
    assert "from app.collector.fund_pct import calc_pct, prev_nav_from_db" in src
    assert "* 100" not in src and "*100" not in src, "回填脚本里出现了第二份 pct 公式"
    assert "- 1.0" not in src and "-1.0" not in src, "回填脚本里出现了第二份 pct 公式"