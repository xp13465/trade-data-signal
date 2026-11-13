"""test_fof_nav_budget_fix_20261113.py - FOF 采集预算根治三方案单测(2026-11-13)。

任务书 /tmp/task-fof-budget-fix-20261113.md 证据用例 1-4 + 方案 A(onetime 入口):
  1. nav_change_pct 长浮点 vs 两位小数(生产实证 -0.9095554420030627 vs -0.91) ⇒ 判定
     「舍入差已对齐」不拒绝; 真实差异(-0.91 vs 0.50) ⇒ 仍拒绝。
  2. unit_nav 1e-10 级差异 ⇒ 仍拒绝(严格口径不动)。
  3. 相位顺序: 3 只 recent 未跑 + 3 只 history 待跑 + 预算只够一半 ⇒ recent 三只全部
     先被处理, TimeoutError, cursor 未丢(未跑到的目标保留原尝试游标/存储相位)。
  4. 预算耗尽仍 raise TimeoutError(不吞异常/不做优雅收尾 rc=0)。
  A. --onetime-backfill 只跑无 state 基金, 不读写轮转进度; 独立预算默认/上限 1800s;
     预算耗尽同样 raise TimeoutError; 与 dry_run/fund_code/limit 互斥。

纪律: 零网络(fetch 全打桩) / 零外发(notify 的 subprocess.run 全打桩, §18 L48) /
日期全部运行时派生(禁写死"今天", §18 L51) / 禁碰生产 public_fund.db。
"""
import json
import sqlite3
import time as _time_mod
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import collect_fof_nav as mod
from app.collector import public_fund_gap as gap
from scripts.tests.test_collect_fof_nav_333 import _conn, _seed_basic


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """零网络 + 零外发: fetch 必须被各用例打桩; notify 的 subprocess.run 统一打桩(L48)。"""
    monkeypatch.setattr(mod, "RATE_LIMIT", 0)
    monkeypatch.setattr(mod, "_acquire_lock", lambda nonblock=True, lock_name="public_fund", **kw: True)
    monkeypatch.setattr(mod, "init_db", lambda: None)  # schema 由 _conn 建
    sent = []
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: sent.append(cmd))
    return sent


@pytest.fixture
def db(monkeypatch, tmp_path):
    path = tmp_path / "public_fund.db"
    monkeypatch.setattr(mod, "DB_PATH", path)
    monkeypatch.setattr(mod, "get_conn", lambda: _conn(path))
    return path


def _progress_path(db: Path) -> Path:
    return db.with_suffix(".fof-nav-progress.json")


def _today_minus(n: int) -> str:
    return (date.today() - timedelta(days=n)).strftime("%Y%m%d")


def _fetch_row(code, d, **over):
    row = dict(date=d, fund_code=code, unit_nav=1.234, acc_nav=2.0,
               prev_unit_nav=1.0, nav_change_pct=-0.91)
    row.update(over)
    return row


# ── 用例 1: nav_change_pct 两位小数对齐(方案 B) ─────────────────────────
def test_case1_rounding_aligned_long_float_not_rejected(db, monkeypatch):
    """长浮点(-0.9095554420030627) vs 两位小数(-0.91): 判定「已对齐」, 不整只拒绝。

    生产实证形态: 库内旧值来自 akshare 长浮点, lsjz 返回两位小数 ⇒ 每晚结构性必拒。
    """
    d = _today_minus(2)
    _seed_basic(db, [("000001", "FOF-测试", "FOF")])
    c = _conn(db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,"
              "prev_unit_nav,nav_change_pct) VALUES(?, '000001', 'FOF-测试', 1.234, 2.0,"
              " 1.0, -0.9095554420030627)", (d,))
    c.commit()
    c.close()
    monkeypatch.setattr(mod, "fetch_lsjz",
                        lambda code, *a, **kw: [_fetch_row(code, d)])
    n = mod.collect()
    assert n >= 1  # 不再整只拒绝, 行正常提交(对齐放行)
    c = _conn(db)
    # COALESCE 方向不动: 库值非空保留库值(长浮点原值不被 -0.91 覆盖; SQLite REAL 往返±1ulp)
    got = c.execute("SELECT nav_change_pct FROM fund_daily_nav WHERE date=?", (d,)).fetchone()[0]
    assert got != -0.91 and round(got, 2) == -0.91 and abs(got - (-0.9095554420030627)) < 1e-12
    # 无真实冲突 ⇒ 不入审计表
    assert c.execute("SELECT COUNT(*) FROM fund_collection_conflicts").fetchone()[0] == 0
    c.close()


def test_case1_real_difference_still_rejected(db, monkeypatch, offline):
    """两位小数仍不等(-0.91 vs 0.50): 真实差异 ⇒ 仍 NonNullConflict 整只拒绝。"""
    d = _today_minus(2)
    _seed_basic(db, [("000001", "FOF-测试", "FOF")])
    c = _conn(db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,"
              "prev_unit_nav,nav_change_pct) VALUES(?, '000001', 'FOF-测试', 1.234, 2.0,"
              " 1.0, -0.91)", (d,))
    c.commit()
    c.close()
    monkeypatch.setattr(mod, "fetch_lsjz",
                        lambda code, *a, **kw: [_fetch_row(code, d, nav_change_pct=0.50)])
    assert mod.collect() == 0
    c = _conn(db)
    assert c.execute("SELECT nav_change_pct FROM fund_daily_nav WHERE date=?", (d,)).fetchone()[0] == -0.91
    ev = c.execute("SELECT field,before_value,after_value FROM fund_collection_conflicts").fetchall()
    assert [(e[0], round(e[1], 2), round(e[2], 2)) for e in ev] == [("nav_change_pct", -0.91, 0.5)]
    c.close()
    assert len(offline) == 1 and "同源非空冲突" in offline[0][2]  # cmd=[python, notify.py, 主题, ...]


def test_case2_unit_nav_tiny_diff_still_rejected(db, monkeypatch):
    """unit_nav 1e-10 级差异: 严格口径不动, 仍拒绝(对齐只限 nav_change_pct)。"""
    d = _today_minus(2)
    _seed_basic(db, [("000001", "FOF-测试", "FOF")])
    c = _conn(db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,"
              "prev_unit_nav,nav_change_pct) VALUES(?, '000001', 'FOF-测试', 1.234, 2.0,"
              " 1.0, -0.91)", (d,))
    c.commit()
    c.close()
    monkeypatch.setattr(mod, "fetch_lsjz",
                        lambda code, *a, **kw: [_fetch_row(code, d, unit_nav=1.234000001)])
    assert mod.collect() == 0
    c = _conn(db)
    assert c.execute("SELECT unit_nav FROM fund_daily_nav WHERE date=?", (d,)).fetchone()[0] == 1.234
    assert c.execute("SELECT field FROM fund_collection_conflicts").fetchone()[0] == "unit_nav"
    c.close()


def test_check_conflicts_rounding_counter_distinguishes(db):
    """计数可分辨「舍入差已对齐」与「真实冲突」: 对齐≠冲突, 混合时真实冲突不吞。"""
    d = _today_minus(2)
    c = _conn(db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,"
              "prev_unit_nav,nav_change_pct) VALUES(?, '000001', 'FOF-测试', 1.0, 2.0,"
              " 0.9, 0.50555)", (d,))
    c.commit()
    # 纯舍入对齐: 不抛, 返回对齐条数 1
    assert gap.check_conflicts(c, "nav", "000001", [_fetch_row("000001", d, unit_nav=1.0,
                                                               acc_nav=2.0, prev_unit_nav=0.9,
                                                               nav_change_pct=0.51)], "src") == 1
    # 混合: pct 对齐 + unit_nav 真实差异 ⇒ 仍拒绝, 且 rounding_aligned==1 不算已解决
    with pytest.raises(gap.NonNullConflict) as exc:
        gap.check_conflicts(c, "nav", "000001", [_fetch_row("000001", d, unit_nav=1.1,
                                                            acc_nav=2.0, prev_unit_nav=0.9,
                                                            nav_change_pct=0.51)], "src")
    assert exc.value.rounding_aligned == 1
    assert [e["field"] for e in exc.value.evidence] == ["unit_nav"]
    # pct 真实差异: 仍拒绝, 对齐计数 0
    with pytest.raises(gap.NonNullConflict) as exc2:
        gap.check_conflicts(c, "nav", "000001", [_fetch_row("000001", d, unit_nav=1.0,
                                                            acc_nav=2.0, prev_unit_nav=0.9,
                                                            nav_change_pct=0.9)], "src")
    assert exc2.value.rounding_aligned == 0
    assert [e["field"] for e in exc2.value.evidence] == ["nav_change_pct"]
    c.close()


# ── 用例 3: 相位顺序——预算只够一半, recent 三只全部先被处理, cursor 未丢 ──
def test_case3_recent_first_on_half_budget(db, monkeypatch):
    """3 只 stateless(recent 未跑) + 3 只 history 待跑, 预算够 3 只:
    pass A recent 增量扫先处理 3 只 stateless; 第 4 只预算耗尽 raise TimeoutError;
    游标停在已尝试的最后一只; 3 只回补基金存储相位原样保留(不丢/不跳)。"""
    d = _today_minus(2)
    funds = [(f"00000{i}", "FOF-测试", "FOF") for i in range(1, 7)]
    _seed_basic(db, funds)
    c = _conn(db)
    gap.migrate(c)
    # 3 只回补基金已有存储相位 history
    for code in ("000004", "000005", "000006"):
        c.execute("INSERT INTO fund_collection_state VALUES('nav', ?, '20260101', '')", (code,))
    c.commit()
    c.close()
    _progress_path(db).write_text(json.dumps({
        "version": 1, "last_code": "000006",
        "work_limits": {code: {"history_days": 366, "gap_fields": 64, "phase": "history"}
                        for code in ("000004", "000005", "000006")}}))
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a, **kw: [_fetch_row(code, d)])
    # 预算控制: 第 3 次进度写入后令 monotonic 爆表 ⇒ 第 4 只 fund 顶检查触发预算耗尽
    state = {"expired": False}
    real_time = mod.time
    monkeypatch.setattr(mod, "time", SimpleNamespace(
        monotonic=lambda: 1e18 if state["expired"] else real_time.monotonic(),
        time=real_time.time))
    real_awj = mod.atomic_write_json
    writes = []

    def flip_awj(path, value):
        real_awj(path, value)
        writes.append(value["last_code"])
        if len(writes) >= 3:
            state["expired"] = True

    monkeypatch.setattr(mod, "atomic_write_json", flip_awj)
    with pytest.raises(TimeoutError, match="预算耗尽"):
        mod.collect(batch=6)
    c = _conn(db)
    # recent 三只全部先被处理(各提交 1 行)
    for code in ("000001", "000002", "000003"):
        assert c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code=?", (code,)).fetchone()[0] == 1
    # 回补三只零落库
    for code in ("000004", "000005", "000006"):
        assert c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code=?", (code,)).fetchone()[0] == 0
    c.close()
    # cursor 未丢: 停在第 3 只(尝试制), 未跑到的目标保留原尝试游标
    saved = json.loads(_progress_path(db).read_text())
    assert saved["last_code"] == "000003"
    # 3 只回补基金的存储相位原样保留(不被增量扫消耗/轮转)
    for code in ("000004", "000005", "000006"):
        assert saved["work_limits"][code] == {"history_days": 366, "gap_fields": 64, "phase": "history"}


# ── 用例 4: 预算耗尽仍 raise TimeoutError(exit 码语义不变) ──────────────
def test_case4_budget_exhaustion_still_raises_timeout(db, monkeypatch):
    """预算耗尽 raise TimeoutError 透传(不吞/不转 rc=0 语义), 整批失败信号不误置。"""
    _seed_basic(db, [("000001", "FOF-测试", "FOF")])

    def slow(code, *a, **kw):
        _time_mod.sleep(0.05)
        return [_fetch_row(code, _today_minus(2))]

    monkeypatch.setattr(mod, "fetch_lsjz", slow)
    with pytest.raises(TimeoutError, match="预算耗尽"):
        mod.collect(budget_seconds=0.01)
    assert mod.LAST_BATCH_FAILED is False  # 预算中断走 rc=1 路径, 非整批失败 exit 2


# ── 方案 A: --onetime-backfill 一次性清欠入口 ────────────────────────────
def test_onetime_backfill_targets_stateless_only(db, monkeypatch):
    """只跑无 fund_collection_state 基金; 全相位首查后写 state; 不读写轮转进度。"""
    d = _today_minus(2)
    _seed_basic(db, [("000001", "FOF-测试", "FOF"), ("000002", "FOF-测试", "FOF")])
    c = _conn(db)
    gap.migrate(c)
    c.execute("INSERT INTO fund_collection_state VALUES('nav', '000002', '20260101', '')")
    c.commit()
    c.close()
    called = []
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a, **kw: called.append(code) or [_fetch_row(code, d)])
    n = mod.collect(onetime=True)
    assert called == ["000001"]  # 只跑无 state 基金(000002 有 state 跳过)
    assert n >= 1
    assert not _progress_path(db).exists()  # 不读写轮转进度
    c = _conn(db)
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='000001'").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM fund_collection_state WHERE code='000001'").fetchone()[0] == 1
    c.close()


def test_onetime_budget_cap_and_mode_conflicts(db):
    """独立预算默认/上限 1800s; 与 dry_run/fund_code/limit 互斥。"""
    with pytest.raises(ValueError):
        mod.collect(onetime=True, onetime_budget=1801)
    with pytest.raises(ValueError):
        mod.collect(onetime=True, onetime_budget=0)
    with pytest.raises(ValueError):
        mod.collect(onetime=True, dry_run=True)
    with pytest.raises(ValueError):
        mod.collect(onetime=True, fund_code="000001")
    with pytest.raises(ValueError):
        mod.collect(onetime=True, limit=1)


def test_onetime_budget_exhaustion_raises_timeout(db, monkeypatch):
    """onetime 预算耗尽同样 raise TimeoutError(不吞), 已提交基金保留。"""
    _seed_basic(db, [("000001", "FOF-测试", "FOF"), ("000002", "FOF-测试", "FOF")])

    def slow(code, *a, **kw):
        if code == "000002":
            _time_mod.sleep(0.05)
        return [_fetch_row(code, _today_minus(2))]

    monkeypatch.setattr(mod, "fetch_lsjz", slow)
    with pytest.raises(TimeoutError, match="预算耗尽"):
        mod.collect(onetime=True, onetime_budget=0.02)
    c = _conn(db)
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='000001'").fetchone()[0] >= 1
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='000002'").fetchone()[0] == 0
    c.close()
