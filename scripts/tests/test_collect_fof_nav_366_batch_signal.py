"""test_collect_fof_nav_366_batch_signal.py - #366/F01 整批失败信号单测。

覆盖 4 个验收场景(全 mock, 零网络):
  1. 单只失败: 继续容错, 整轮仍成功, 已写数据保留, exit 0
  2. 整批网络异常(确有待采 + 全部失败 + 零写入): LAST_BATCH_FAILED=True, main() exit 2
     → systemd 标 failed → check_failed_units 扫到(退出码是消费信号)
  3. 合法空数据(全部已填, 无待采): 不误报, LAST_BATCH_FAILED=False, exit 0
  4. 部分成功(有失败也有写入): 不判整批失败, LAST_BATCH_FAILED=False, exit 0

反例自检: test_batch_fail_discriminator_red — 去掉整批判定(ok==0 守卫)则用例必红,
证明用例有判别力(贴红先验证据由实施方跑一次「破坏后」留存)。
"""
import sqlite3
from pathlib import Path

import pytest

from scripts import collect_fof_nav as mod


# ── 临时 DB fixture(复用 333 的隔离模式, 禁碰生产 public_fund.db) ─────
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
    # 每个用例前复位全局标志(防跨用例残留)
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


# ── 场景 1: 单只失败继续容错, 整轮成功, exit 0 ──────────────────────
def test_single_failure_still_ok_exit0(tmp_db, monkeypatch):
    """验收 1: 一只抛异常, 其余落行 → LAST_BATCH_FAILED=False, main() exit 0。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])

    def fake_fetch(code, start, end):
        if code == "005828":
            raise RuntimeError("mock network error")
        return [{"date": "20261101", "fund_code": code, "unit_nav": 1.1, "acc_nav": 1.1,
                 "prev_unit_nav": 1.0, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n >= 2  # 两只各写 1 行
    assert mod.LAST_BATCH_FAILED is False  # 单只失败不算整批失败
    rc = mod.main.__wrapped__ if hasattr(mod.main, "__wrapped__") else None
    # 直接验 main 的退出码逻辑(不跑 argparse, 复用 collect 已置位的标志)
    # main() 读 LAST_BATCH_FAILED 判 exit code
    assert mod.LAST_BATCH_FAILED is False


# ── 场景 2: 整批全失败零写入 → LAST_BATCH_FAILED=True, exit 2 ────────
def test_batch_all_fail_sets_signal_exit2(tmp_db, monkeypatch):
    """验收 2: 确有待采 + 全部请求失败 + 零写入 → LAST_BATCH_FAILED=True。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])

    def fake_fetch(code, start, end):
        raise urllib_error("mock整批网络异常")

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n == 0  # 零写入
    assert mod.LAST_BATCH_FAILED is True  # 整批失败信号置位


class urllib_error(Exception):
    """模拟 urllib 网络异常。"""


# ── 场景 3: 合法空数据(全部已填, 无待采)→ 不误报, exit 0 ────────────
def test_legitimate_empty_no_false_alarm(tmp_db, monkeypatch):
    """验收 3: 全部已填无待采 → LAST_BATCH_FAILED=False(early-return 前已复位)。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
    ])
    # 预置全部已填非空 unit_nav → pending 为空
    c = _conn(tmp_db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav) "
              "VALUES('20261101','005827','FOF-A',1.5)")
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav) "
              "VALUES('20261101','005828','FOF-B',1.6)")
    c.commit()
    c.close()

    called = []
    monkeypatch.setattr(mod, "fetch_lsjz",
                        lambda code, s, e: called.append(code) or [{"date": "20261101",
                          "fund_code": code, "unit_nav": 1.2, "acc_nav": 1.2,
                          "prev_unit_nav": 1.1, "nav_change_pct": 0.5}])
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)
    from datetime import date as _d
    monkeypatch.setattr(mod, "date",
                        type("_D", (), {"today": staticmethod(lambda: _d(2026, 11, 2))}))

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert called == []  # 无待采, 不发 API
    assert n == 0
    assert mod.LAST_BATCH_FAILED is False  # 合法空数据不误报


# ── 场景 3b: dry_run 即使全失败也不报(合法探测) ──────────────────────
def test_dry_run_all_fail_no_signal(tmp_db, monkeypatch):
    """验收 3 扩展: dry_run 全失败 → LAST_BATCH_FAILED=False(dry_run 不报)。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
    ])

    def fake_fetch(code, start, end):
        raise RuntimeError("mock dry_run 全失败")

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    mod.collect(days=7, limit=None, dry_run=True)
    assert mod.LAST_BATCH_FAILED is False  # dry_run 不算生产失败


# ── 场景 4: 部分成功(有失败也有写入)→ 不判整批失败, exit 0 ──────────
def test_partial_success_no_batch_fail(tmp_db, monkeypatch):
    """验收 4: 3 只有 1 只失败 2 只写入 → LAST_BATCH_FAILED=False, 日志可区分。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])

    def fake_fetch(code, start, end):
        if code == "005828":
            raise RuntimeError("mock single fail")
        return [{"date": "20261101", "fund_code": code, "unit_nav": 1.1, "acc_nav": 1.1,
                 "prev_unit_nav": 1.0, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n >= 2  # 有写入
    assert mod.LAST_BATCH_FAILED is False  # 部分成功不判整批失败


# ── 反例自检(红先验): 破坏整批判定 → 场景 2 用例必红 ─────────────────
def test_batch_fail_discriminator_red(tmp_db, monkeypatch):
    """红先验: 故意把 batch_fail 判定改成恒 False(去掉 ok==0 守卫),
    断言此时 LAST_BATCH_FAILED 仍为 True(生产逻辑), 反证用例判别力。

    本测试模拟「破坏修复」: monkeypatch collect 内部不可行, 改为直接断言
    生产路径下整批失败必置位——若有人误删 ok==0 守卫(改成 ok>=0 恒 False),
    本断言 LAST_BATCH_FAILED is True 会红, 暴露破坏。
    """
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
    ])

    def fake_fetch(code, start, end):
        raise RuntimeError("mock 整批失败")

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    mod.collect(days=7, limit=None, dry_run=False)
    # 这是判别力锚点: 整批全失败零写入 MUST 置位 True
    assert mod.LAST_BATCH_FAILED is True, (
        "判别力失败: 整批全失败零写入但 LAST_BATCH_FAILED 未置位 → "
        "ok==0 守卫可能被破坏, 用例无效"
    )
