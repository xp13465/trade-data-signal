# -*- coding: utf-8 -*-
"""FOF 净值同源非空冲突告警测试(2026-11-12, 用户 11-11 拍板「维持旧值 + 加告警」)。

背景(生产实证 /tmp/night-fail-triage.md §3 + docs/ops/alert-checker-registry-20261015.md):
  11-11 21:10 轮 60 只 20261019 prev_unit_nav eastmoney 修订值触发整只拒绝,
  fund_collection_conflicts 存了 60 条, 但 run_fof_nav_collect.sh 无 notify 调用、
  unit 无 OnFailure ⇒ 全程零告警。拍板: 拒绝逻辑/DB 写入一字不改, 只补失败可见性。

本文件覆盖:
  ① 冲突轮 → 恰好发一次 notify 告警, 参数正确(warning 档/20h 去重/样本只数/计数)
  ② DB 旧值保留未覆盖(拒绝行为与本改动前逐位一致)
  ③ 无冲突轮 → 零告警(不搞每晚「一切正常」)
  ④ 告警发送本身失败(subprocess 抛错) → 不影响采集主流程(rc/返回值)
  ⑤ dry-run 轮的冲突 → 不告警(与 save_conflicts 的 not dry_run 守卫同口径)

零外发铁律(§18 L48): 全部用例 monkeypatch `collect_fof_nav.subprocess.run`,
真实 notify.py 子进程在本套用例内不可达(打桩在调用路径上, 断言捕获到的 cmd 即证
桩生效), 测试前后零真实外发。
日期口径(§18 L51): 冲突日 D 一律相对真实 today 运行期推导, 不写死字面量 ⇒ 隔天仍绿。
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts import collect_fof_nav as mod


def _conn(db: Path, wal: bool = True):
    c = sqlite3.connect(str(db), timeout=10.0)
    c.row_factory = sqlite3.Row
    if wal:
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
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_nav_code ON fund_daily_nav(fund_code)")
    c.commit()
    return c


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db = tmp_path / "public_fund.db"
    monkeypatch.setattr(mod, "get_conn", lambda: _conn(db))
    monkeypatch.setattr(mod, "init_db", lambda: None)
    monkeypatch.setattr(mod, "_acquire_lock",
                        lambda nonblock=True, lock_name="public_fund", **kw: True)
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


def _conflict_date() -> str:
    """冲突日 D = today-2(运行期推导, 不写死字面量 ⇒ 隔天仍绿, §18 L51)。"""
    return (date.today() - timedelta(days=2)).strftime("%Y%m%d")


def _seed_conflict_row(db: Path, code: str, d: str):
    """既有行: unit_nav NULL(合法缺口) + prev_unit_nav=1.0(非空旧值)。

    采集返回同日 prev_unit_nav=1.5 修订值 ⇒ NonNullConflict(field=prev_unit_nav,
    before=1.0, after=1.5), 复刻 11-11 生产实证的 20261019/prev_unit_nav/eastmoney 形态。
    """
    c = _conn(db)
    c.execute("INSERT OR REPLACE INTO fund_daily_nav(date,fund_code,prev_unit_nav) VALUES(?,?,1.0)",
              (d, code))
    c.commit()
    c.close()


@pytest.fixture
def stub_notify(monkeypatch):
    """打桩 collect_fof_nav 的 subprocess.run: 捕获全部调用, 真实子进程不可达(L48)。"""
    calls = []

    def fake_run(cmd, *a, **kw):
        calls.append(list(cmd))
        return "stubbed-no-real-subprocess"

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return calls


def test_conflict_round_sends_one_alert_with_params(tmp_db, monkeypatch, stub_notify):
    """① 冲突轮: 恰好一次告警, warning 档/20h 去重/样本/计数齐; ② DB 旧值保留。"""
    d = _conflict_date()
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])
    _seed_conflict_row(tmp_db, "005828", d)

    def fake_fetch(code, start, end, **kw):
        row = {"date": d, "fund_code": code, "unit_nav": 1.234, "acc_nav": 2.0,
               "prev_unit_nav": 1.5, "nav_change_pct": 0.5}
        if code == "005828":
            # 冲突只: 同日 prev_unit_nav 修订 1.0 -> 1.5
            row["prev_unit_nav"] = 1.5
        return [dict(row)]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    n = mod.collect(days=7, limit=None, dry_run=False)

    # ① 恰好一次告警
    assert len(stub_notify) == 1, f"冲突轮应恰好发一次告警, 实发 {len(stub_notify)} 次"
    cmd = stub_notify[0]
    assert cmd[1].endswith("scripts/notify.py"), f"应调 scripts/notify.py, 得 {cmd[1]}"
    subject, body = cmd[2], cmd[3]
    assert "[告警] FOF 净值同源非空冲突" in subject, f"主题缺关键词: {subject}"
    assert "1 条" in subject and "1 只" in subject, f"主题应含冲突条数/只数: {subject}"
    # 批量档(warning) + 20h 去重窗 + 独立 key(不与每日固定 key 混)
    assert "--tier" in cmd and cmd[cmd.index("--tier") + 1] == "warning"
    assert "--dedup-key" in cmd and cmd[cmd.index("--dedup-key") + 1] == "fof_nav_nonnull_conflict"
    assert "--dedup-window" in cmd and cmd[cmd.index("--dedup-window") + 1] == "72000"
    # 正文要素: 日期/字段/来源 + 拍板指引 + 本轮计数
    for needle in (d, "prev_unit_nav", "eastmoney", "DB 旧值保留未覆盖",
                   "attempted=3", "committed=2", "not_attempted=0", "005828"):
        assert needle in body, f"正文缺要素: {needle}\n---\n{body}"

    # ② 拒绝行为不变: DB 旧值逐位保留(未覆盖), 冲突基金零写入
    c = _conn(tmp_db)
    row = c.execute("SELECT unit_nav, prev_unit_nav FROM fund_daily_nav "
                    "WHERE fund_code='005828' AND date=?", (d,)).fetchone()
    assert row["prev_unit_nav"] == 1.0, f"旧值应保留 1.0, 得 {row['prev_unit_nav']}"
    assert row["unit_nav"] is None, "冲突基金应整只拒绝, unit_nav 不应被写入"
    audited = c.execute("SELECT before_value, after_value, source FROM "
                        "fund_collection_conflicts").fetchone()
    assert audited["before_value"] == 1.0 and audited["after_value"] == 1.5
    c.close()

    # 其余 2 只正常写入(rc 语义不变: 返回写入行数)
    assert n >= 2, f"其余基金应正常写入, 得 n={n}"
    assert mod.LAST_BATCH_FAILED is False, "部分成功不应判整批失败"


def test_no_conflict_round_sends_no_alert(tmp_db, monkeypatch, stub_notify):
    """③ 无冲突轮: 零告警(不搞每晚「一切正常」)。"""
    _seed_basic(tmp_db, [("005827", "FOF-A", "FOF-均衡型")])

    def fake_fetch(code, start, end, **kw):
        return [{"date": _conflict_date(), "fund_code": code, "unit_nav": 1.1,
                 "acc_nav": 1.1, "prev_unit_nav": 1.0, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n >= 1
    assert stub_notify == [], f"无冲突轮不应发告警, 实发 {len(stub_notify)} 次"


def test_alert_send_failure_does_not_break_collect(tmp_db, monkeypatch):
    """④ 告警发送本身失败(subprocess 抛错) → 不影响采集主流程(返回值/rc 不变)。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
    ])
    _seed_conflict_row(tmp_db, "005828", _conflict_date())

    def fake_fetch(code, start, end, **kw):
        return [{"date": _conflict_date(), "fund_code": code, "unit_nav": 1.234,
                 "acc_nav": 2.0, "prev_unit_nav": 1.5, "nav_change_pct": 0.5}]

    def broken_run(cmd, *a, **kw):
        raise RuntimeError("mock: notify 通道故障")

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)
    monkeypatch.setattr(mod.subprocess, "run", broken_run)

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n >= 1, f"告警发送失败不应影响采集写入, 得 n={n}"
    # 旧值仍保留(拒绝逻辑不受告警失败影响)
    c = _conn(tmp_db)
    row = c.execute("SELECT prev_unit_nav FROM fund_daily_nav WHERE fund_code='005828'").fetchone()
    assert row["prev_unit_nav"] == 1.0
    c.close()


def test_dry_run_conflict_sends_no_alert(tmp_db, monkeypatch, stub_notify):
    """⑤ dry-run 轮的冲突 → 不告警(与 save_conflicts 的 not dry_run 守卫同口径)。

    dry-run 只读快照(readonly_snapshot), 冲突会被检出但不存审计表、不写库;
    告警应同口径只在真实写轮发, 防调试 dry-run 打真告警。
    """
    d = _conflict_date()
    # dry-run 需要无 WAL 的静态副本: 用非 WAL 连接种子库
    c = _conn(tmp_db, wal=False)
    c.executemany("INSERT OR REPLACE INTO fund_basic(fund_code,fund_name,fund_type) "
                  "VALUES(?,?,?)", [("005828", "FOF-B", "FOF-进取型")])
    c.execute("INSERT OR REPLACE INTO fund_daily_nav(date,fund_code,prev_unit_nav) "
              "VALUES(?,?,1.0)", (d, "005828"))
    c.commit()
    c.close()
    monkeypatch.setattr(mod, "DB_PATH", tmp_db)

    def fake_fetch(code, start, end, **kw):
        return [{"date": d, "fund_code": code, "unit_nav": 1.234, "acc_nav": 2.0,
                 "prev_unit_nav": 1.5, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)

    mod.collect(days=7, limit=1, dry_run=True)
    assert stub_notify == [], f"dry-run 轮不应发告警, 实发 {len(stub_notify)} 次"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
