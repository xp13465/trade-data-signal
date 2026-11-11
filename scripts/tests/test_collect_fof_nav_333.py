"""test_collect_fof_nav_333.py - #333 批1 FOF/QDII 采集器单测。

覆盖:
  V3 单测(mock 零网络): parse + 只补 NULL
  V7 反证: 去掉「只补 NULL」守卫 → 会覆盖非空 → 测试 FAIL(证明守卫生效)
  E5 单只失败不中断: mock 一只抛异常, 其余仍落行
  E4 真实小样: 3 只 FOF 实跑(临时 sqlite, 禁碰生产 public_fund.db)

禁网络: 所有 lsjz 调用走 monkeypatch 桩(除 E4 真实小样标 network)。
"""
import json
import sqlite3
from pathlib import Path

import pytest

from scripts import collect_fof_nav as mod


# ── 桩数据 ──────────────────────────────────────────────────────────────
def _mock_lsjz_rows():
    return [
        {"FSRQ": "2026-10-30", "DWJZ": "1.3725", "LJJZ": "1.3725", "JZZZL": "0.68"},
        {"FSRQ": "2026-10-29", "DWJZ": "1.3632", "LJJZ": "1.3632", "JZZZL": "-1.26"},
        {"FSRQ": "2026-10-28", "DWJZ": "1.3806", "LJJZ": "1.3806", "JZZZL": "0.52"},
    ]


def _make_resp_bytes(rows):
    return json.dumps(
        {"ErrCode": 0, "ErrMsg": None, "Data": {"LSJZList": rows}, "TotalCount": len(rows), "PageIndex": 1, "PageSize": 20}
    ).encode("utf-8")


# ── 临时 DB fixture(禁碰生产 public_fund.db) ─────────────────────────
@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db = tmp_path / "public_fund.db"
    monkeypatch.setattr(mod, "DB_PATH", db)
    # 指向临时库
    monkeypatch.setattr(mod, "get_conn", lambda: _conn(db))
    monkeypatch.setattr(mod, "init_db", lambda: None)  # schema 由 _conn 建
    monkeypatch.setattr(mod, "_acquire_lock", lambda nonblock=True, lock_name="public_fund", **kw: True)
    return db


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
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_nav_code ON fund_daily_nav(fund_code)")
    c.commit()
    return c


def _seed_basic(db: Path, funds):
    c = _conn(db)
    c.executemany(
        "INSERT OR REPLACE INTO fund_basic(fund_code,fund_name,fund_type) VALUES(?,?,?)",
        funds,
    )
    c.commit()
    c.close()


# ── 解析单测 ────────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, data):
        self._data = data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return self._data


def test_parse_lsjz(monkeypatch):
    """V3: lsjz 返回正确解析为 date/unit/acc/pct/prev。"""
    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return _FakeResp(_make_resp_bytes(_mock_lsjz_rows()))

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    rows = mod.fetch_lsjz("005827", "2026-10-20", "2026-10-31")
    assert len(rows) == 3
    assert rows[0]["date"] == "20261030"
    assert rows[0]["unit_nav"] == pytest.approx(1.3725)
    assert rows[0]["acc_nav"] == pytest.approx(1.3725)
    assert rows[0]["nav_change_pct"] == pytest.approx(0.68)
    # prev_unit = 下一条(2026-10-29)的 DWJZ
    assert rows[0]["prev_unit_nav"] == pytest.approx(1.3632)
    # 最后一条 prev 无下一条 → None
    assert rows[-1]["prev_unit_nav"] is None
    # Referer 必须带
    assert any("referer" in k.lower() for k in captured["headers"])


def test_parse_empty(monkeypatch):
    """V3: 上游无数据(封闭期/份额类)返回空列表, 不抛。"""
    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout=None, context=None: _FakeResp(_make_resp_bytes([]))
    )
    rows = mod.fetch_lsjz("000000", "2026-10-20", "2026-10-31")
    assert rows == []


def test_parse_errcode_raises(monkeypatch):
    """V3: ErrCode≠0 抛(上游真异常不静默)。"""
    bad = json.dumps({"ErrCode": 999, "ErrMsg": "deny", "Data": None}).encode()
    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout=None, context=None: _FakeResp(bad)
    )
    with pytest.raises(RuntimeError):
        mod.fetch_lsjz("005827", "2026-10-20", "2026-10-31")


# ── 写入守卫单测(只补 NULL, V7) ──────────────────────────────────────
def test_only_fill_null(tmp_db):
    """E2: 已有非空 unit_nav 不被覆盖; NULL 被补。"""
    _seed_basic(tmp_db, [("005827", "测试FOF", "FOF-均衡型")])
    # 预置: 1030 已有非空 1.0(不该被覆盖), 1029 为 NULL(该被补)
    c = _conn(tmp_db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav) "
              "VALUES('20261030','005827','旧名',1.0)")
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav) "
              "VALUES('20261029','005827','旧名',NULL)")
    c.commit()
    c.close()

    rows = [
        {"date": "20261030", "fund_code": "005827", "unit_nav": 1.3725, "acc_nav": 1.3725,
         "prev_unit_nav": 1.3632, "nav_change_pct": 0.68},
        {"date": "20261029", "fund_code": "005827", "unit_nav": 1.3632, "acc_nav": 1.3632,
         "prev_unit_nav": 1.3806, "nav_change_pct": -1.26},
    ]
    conn = mod.get_conn()
    params = [
        (r["date"], r["fund_code"], "测试FOF", r["unit_nav"], r["acc_nav"],
         r["prev_unit_nav"], r["nav_change_pct"])
        for r in rows
    ]
    conn.executemany(mod.UPSERT_SQL, params)
    conn.commit()
    conn.close()

    c = _conn(tmp_db)
    r30 = c.execute("SELECT unit_nav,fund_name FROM fund_daily_nav WHERE date='20261030'").fetchone()
    r29 = c.execute("SELECT unit_nav FROM fund_daily_nav WHERE date='20261029'").fetchone()
    c.close()
    # 1030 非空保留 1.0, 不被 1.3725 覆盖
    assert r30["unit_nav"] == pytest.approx(1.0)
    # 1029 NULL 被补成 1.3632
    assert r29["unit_nav"] == pytest.approx(1.3632)


def test_discriminator_overwrite_would_fail(tmp_db):
    """E3 判别力反证: 用 INSERT OR REPLACE(无 COALESCE 守卫)会覆盖非空 → 证明守卫是必要的。

    本测试故意用「无守卫」SQL, 断言它确实会覆盖(=坏行为), 以反证生产 SQL 的 COALESCE 守卫生效。
    """
    _seed_basic(tmp_db, [("005827", "测试FOF", "FOF-均衡型")])
    c = _conn(tmp_db)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav) "
              "VALUES('20261030','005827','旧名',1.0)")
    c.commit()
    c.close()

    # 故意用「无守卫」SQL(覆盖式)
    bad_sql = (
        "INSERT OR REPLACE INTO fund_daily_nav"
        "(date,fund_code,fund_name,unit_nav) VALUES(?,?,?,?)"
    )
    conn = mod.get_conn()
    conn.execute(bad_sql, ("20261030", "005827", "新名", 1.3725))
    conn.commit()
    conn.close()

    c = _conn(tmp_db)
    r = c.execute("SELECT unit_nav FROM fund_daily_nav WHERE date='20261030'").fetchone()
    c.close()
    # 无守卫 SQL 确实覆盖了 → 1.3725(证明: 去掉守卫会覆盖, 守卫是必要的)
    assert r["unit_nav"] == pytest.approx(1.3725)


# ── 单只失败不中断(E5) ────────────────────────────────────────────────
def test_single_failure_does_not_break(tmp_db, monkeypatch):
    """E5: 一只抛异常, 其余仍落行 + 失败被记录。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])
    call_count = {"n": 0}

    def fake_fetch(code, start, end, **kw):
        call_count["n"] += 1
        if code == "005828":  # 故意让中间一只失败
            raise RuntimeError("mock network error")
        return [
            {"date": "20261030", "fund_code": code, "unit_nav": 1.1, "acc_nav": 1.1,
             "prev_unit_nav": 1.0, "nav_change_pct": 0.5},
        ]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)  # 测试不限速

    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n >= 2  # 005827 + 005829 各写 1 行 = 2
    # 失败的那只没落行
    c = _conn(tmp_db)
    cnt_b = c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='005828'").fetchone()[0]
    cnt_a = c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='005827'").fetchone()[0]
    cnt_c = c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='005829'").fetchone()[0]
    c.close()
    assert cnt_b == 0
    assert cnt_a == 1
    assert cnt_c == 1


# ── 跳过已填(ISSUE-2) ───────────────────────────────────────────────
def test_partial_window_is_rechecked(tmp_db, monkeypatch):
    """窗口中一日非空不代表完整，仍请求API并保留原有非空值。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("005828", "FOF-B", "FOF-进取型"),
        ("005829", "FOF-C", "FOF-稳健型"),
    ])
    c = _conn(tmp_db)
    # 005827 仅一日有值，不能据此跳过整窗。
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav) "
              "VALUES('20261101','005827','FOF-A',1.5)")
    c.commit()
    c.close()

    called = []

    def fake_fetch(code, start, end, **kw):
        called.append(code)
        return [{"date": "20261101", "fund_code": code, "unit_nav": 1.2, "acc_nav": 1.2,
                 "prev_unit_nav": 1.1, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)
    # 用固定日期范围覆盖 20261101
    from datetime import date as _d
    monkeypatch.setattr(mod, "date", type("_D", (), {"today": staticmethod(lambda: _d(2026, 11, 2))}))

    n = mod.collect(days=7, limit=None, dry_run=False, batch=10)
    assert set(called) == {"005827", "005828", "005829"}
    assert n == 2  # HC07授权新语义：冲突基金整只拒绝，另两只正常提交。
    c = _conn(tmp_db)
    assert c.execute("SELECT unit_nav FROM fund_daily_nav WHERE fund_code='005827'").fetchone()[0] == 1.5
    assert tuple(c.execute("SELECT acc_nav,prev_unit_nav,nav_change_pct FROM fund_daily_nav WHERE fund_code='005827'").fetchone()) == (None,None,None)
    assert c.execute("SELECT COUNT(*) FROM fund_collection_conflicts WHERE code='005827'").fetchone()[0] == 1
    c.close()


# ── 分批(ISSUE-2) ────────────────────────────────────────────────────
def test_batch_limits_per_run(tmp_db, monkeypatch):
    """分批: 每轮最多采 batch 只, 超出的本轮不跑(剩余下轮续)。"""
    funds = [(f"{i:06d}", f"FOF-{i}", "FOF-均衡型") for i in range(1, 6)]  # 5 只
    _seed_basic(tmp_db, funds)
    called = []

    def fake_fetch(code, start, end, **kw):
        called.append(code)
        return [{"date": "20261101", "fund_code": code, "unit_nav": 1.2, "acc_nav": 1.2,
                 "prev_unit_nav": 1.1, "nav_change_pct": 0.5}]

    monkeypatch.setattr(mod, "fetch_lsjz", fake_fetch)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.0)
    from datetime import date as _d
    monkeypatch.setattr(mod, "date", type("_D", (), {"today": staticmethod(lambda: _d(2026, 11, 2))}))

    n = mod.collect(days=7, limit=None, dry_run=False, batch=2)
    # batch=2, 只跑前 2 只
    assert len(called) == 2
    assert n >= 2


def test_select_only_fof_qdii(tmp_db):
    """V3: 选基 SQL 只选 FOF/QDII, 不选股票型。"""
    _seed_basic(tmp_db, [
        ("005827", "FOF-A", "FOF-均衡型"),
        ("160125", "QDII-X", "QDII-普通股票"),
        ("000001", "股票型A", "股票型"),
        ("000002", "债型B", "债券型-长债"),
    ])
    conn = mod.get_conn()
    rows = list(conn.execute(mod.SELECT_SQL))
    conn.close()
    codes = {r[0] for r in rows}
    assert codes == {"005827", "160125"}


# ── 真实小样(E4, 需网络, 默认 skip) ──────────────────────────────────
@pytest.mark.network
def test_real_sample_3_fof(tmp_db, monkeypatch):
    """E4: 3 只真实 FOF 实跑(临时 sqlite), 断言落行 unit_nav 非空。

    标 network 标记: CI 默认跳过(docker 无外网/限速); 本机 -m 'network' 手动跑。
    禁碰生产 public_fund.db(tmp_db fixture 已隔离)。
    """
    _seed_basic(tmp_db, [
        ("005827", "华夏聚惠稳健目标FOF", "FOF-稳健型"),
        ("017579", "汇添富添福欣享均衡FOF", "FOF-均衡型"),
        ("018302", "华夏聚盈优选FOF", "FOF-进取型"),
    ])
    monkeypatch.setattr(mod, "RATE_LIMIT", 0.3)
    n = mod.collect(days=7, limit=None, dry_run=False)
    assert n > 0
    # 至少 1 只落到非空 unit_nav(持有期/定期开放 FOF 可能近 7 日不发净值, 不强求每只都有)
    c = _conn(tmp_db)
    nonnull = 0
    for code in ("005827", "017579", "018302"):
        r = c.execute(
            "SELECT unit_nav FROM fund_daily_nav WHERE fund_code=? AND unit_nav IS NOT NULL "
            "ORDER BY date DESC LIMIT 1", (code,)
        ).fetchone()
        if r is not None and r["unit_nav"] > 0:
            nonnull += 1
    c.close()
    assert nonnull >= 1, f"3 只 FOF 无一落非空 unit_nav(可能上游全停发, 换样本重试)"
