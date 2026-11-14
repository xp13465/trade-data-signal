"""test_fof_prev_misalign_20261114.py - FOF/QDII T+2 窗口 prev_unit_nav 错位根治单测。

依据 /tmp/fof-conflict-audit-20261114.md + /tmp/task-fof-prev-rootfix-20261114.md:
  旧 fetch_lsjz 把 lsjz 降序相邻行无条件当 prev; QDII/FOF T+2 披露窗口内目标行的
  前一交易日净值未发布时相邻行是更早交易日(20261019 单日 553 只 prev=10-15 错位值),
  待真值(10-16)发布后重拉必冲突 ⇒ 整只拒绝停旧。修法 A: 仅当相邻行日期 == 期望前一
  交易日(fund_pct.is_prev_trading_day 唯一判据)才采信; 否则写 NULL, 待发布后 gap
  复查自愈。冲突检测不动(真实不一致仍整只拒绝)。

日历: 用仓库入库的 data/trade_dates.txt 真实日历(1990-2026), 不自造日历。
  2026-10-14(三)/15(四)/16(五)/19(一)/20(二) 均交易日, 10-17/18 周末;
  09-30 → 10-08 跨国庆长假相邻(见 test_prev_holiday_adjacent)。
日期全部写死历史日期, 无 today() 依赖(时敏冻结, L51)。
"""
import json
import sqlite3

import pytest

from scripts import collect_fof_nav as mod


def _resp(rows):
    return json.dumps(
        {"ErrCode": 0, "ErrMsg": None, "Data": {"LSJZList": rows},
         "TotalCount": len(rows), "PageIndex": 1, "PageSize": 20}
    ).encode("utf-8")


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def _stub_lsjz(monkeypatch, rows):
    """打桩 lsjz 单页响应(网络零依赖)。"""
    monkeypatch.setattr(
        mod.urllib.request, "urlopen",
        lambda req, timeout=None, context=None: _FakeResp(_resp(rows))
    )


# ── 证据 1: T+2 未发布场景, 不再写错位 prev ────────────────────────────
def test_prev_t2_window_writes_null(monkeypatch):
    """目标日 10-19(一), 前一交易日 10-16(五) 净值未发布(lsjz 只有 10-15 及更早):
    10-19 行 prev 必须 NULL(旧逻辑会把 10-15 值 2.1921 错位写入库);
    10-15 行 prev 正常取相邻 10-14 值(相邻即期望前一交易日)。"""
    rows = [
        {"FSRQ": "2026-10-19", "DWJZ": "2.2346", "LJJZ": "1.1", "JZZZL": "0.18"},
        {"FSRQ": "2026-10-15", "DWJZ": "2.1921", "LJJZ": "1.0", "JZZZL": "1.75"},
        {"FSRQ": "2026-10-14", "DWJZ": "2.1800", "LJJZ": "0.9", "JZZZL": "0.56"},
    ]
    _stub_lsjz(monkeypatch, rows)
    out = mod.fetch_lsjz("007280", "2026-10-09", "2026-10-20")
    by_date = {r["date"]: r for r in out}
    # 修复点: 10-19 的 prev 不再等于 10-15 的错位值(2.1921), 而是 NULL
    assert by_date["20261019"]["prev_unit_nav"] is None
    # 相邻即期望前一交易日的行不受影响(10-15 的 prev = 10-14 值)
    assert by_date["20261015"]["prev_unit_nav"] == pytest.approx(2.18)


# ── 证据 2: 正常场景(前一交易日已发布), 写库结果与旧行为逐位一致 ─────────
def test_prev_normal_same_as_old(monkeypatch):
    """前一交易日已发布时, prev = 相邻行 DWJZ(旧行为 `_safe_float(rows[i+1]['DWJZ'])`
    逐位一致); 单行列表(无相邻行)prev=None(旧行为不变)。"""
    rows = [
        {"FSRQ": "2026-10-19", "DWJZ": "2.2346", "LJJZ": "1.1", "JZZZL": "0.18"},
        {"FSRQ": "2026-10-16", "DWJZ": "2.2305", "LJJZ": "1.0", "JZZZL": "1.75"},
        {"FSRQ": "2026-10-15", "DWJZ": "2.1921", "LJJZ": "0.9", "JZZZL": "0.56"},
    ]
    _stub_lsjz(monkeypatch, rows)
    out = mod.fetch_lsjz("007280", "2026-10-09", "2026-10-20")
    by_date = {r["date"]: r for r in out}
    # 10-19 的 prev = 10-16 真值(相邻行 = 期望前一交易日, 与旧行为逐位一致)
    assert by_date["20261019"]["prev_unit_nav"] == pytest.approx(2.2305)
    assert by_date["20261016"]["prev_unit_nav"] == pytest.approx(2.1921)
    # 最后一条无相邻行 → None(旧行为)
    assert by_date["20261015"]["prev_unit_nav"] is None


# ── 证据 3: 跨周末/节假日, 期望前一交易日取日历正确 ─────────────────────
def test_prev_weekend_adjacent(monkeypatch):
    """跨周末: 10-20(二) 的相邻行是 10-19(一), 周六日不在日历 ⇒ prev 正常写
    (与旧行为一致, 不因周末误杀)。"""
    rows = [
        {"FSRQ": "2026-10-20", "DWJZ": "1.0", "LJJZ": "1.0", "JZZZL": "0.1"},
        {"FSRQ": "2026-10-19", "DWJZ": "0.99", "LJJZ": "0.9", "JZZZL": "0.2"},
    ]
    _stub_lsjz(monkeypatch, rows)
    out = mod.fetch_lsjz("000041", "2026-10-14", "2026-10-21")
    assert out[0]["prev_unit_nav"] == pytest.approx(0.99)


def test_prev_holiday_adjacent(monkeypatch):
    """跨国庆长假: 10-08 的相邻行是 09-30(10-01~10-07 非交易日), 日历判
    09-30 == 期望前一交易日 ⇒ prev 正常写(旧行为一致)。"""
    assert "20261008" in open("data/trade_dates.txt", encoding="utf-8").read().split()
    rows = [
        {"FSRQ": "2026-10-08", "DWJZ": "1.5", "LJJZ": "1.5", "JZZZL": "0.5"},
        {"FSRQ": "2026-09-30", "DWJZ": "1.49", "LJJZ": "1.4", "JZZZL": "0.4"},
    ]
    _stub_lsjz(monkeypatch, rows)
    out = mod.fetch_lsjz("000043", "2026-09-25", "2026-10-09")
    assert out[0]["prev_unit_nav"] == pytest.approx(1.49)


def test_prev_calendar_unavailable_null(monkeypatch):
    """日历不可用(空集)⇒ 判据 None ⇒ prev 一律 NULL(宁缺勿错, fund_pct 既有
    降级口径); 不退化成周末启发式把错位值写库。"""
    import app.calendar as cal
    import app.collector.fund_pct as fund_pct
    fund_pct.prev_trading_date.cache_clear()  # 清真实日历缓存, 防跨用例污染
    monkeypatch.setattr(cal, "_load_trade_dates", lambda: set())
    try:
        rows = [
            {"FSRQ": "2026-10-20", "DWJZ": "1.0", "LJJZ": "1.0", "JZZZL": "0.1"},
            {"FSRQ": "2026-10-19", "DWJZ": "0.99", "LJJZ": "0.9", "JZZZL": "0.2"},
        ]
        _stub_lsjz(monkeypatch, rows)
        out = mod.fetch_lsjz("000041", "2026-10-14", "2026-10-21")
        assert out[0]["prev_unit_nav"] is None
    finally:
        fund_pct.prev_trading_date.cache_clear()  # 还原, 不污染后续用例


# ── 证据 4: 冲突检测未放松(真实不一致仍整只拒绝) ────────────────────────
def test_conflict_detection_not_relaxed(tmp_path):
    """gap.check_conflicts 未动: 库内非空旧值与新值真差异(两位小数也对不齐)
    仍抛 NonNullConflict(整只拒绝)。"""
    from app.collector import public_fund_gap as gap
    db = tmp_path / "pf.db"
    c = sqlite3.connect(str(db))
    c.executescript("""
    CREATE TABLE fund_daily_nav (
      date TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT,
      unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL,
      PRIMARY KEY (date, fund_code));
    """)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,prev_unit_nav) "
              "VALUES('20261019','007280',2.2346,1.0)")
    c.commit()
    rows = [{"date": "20261019", "fund_code": "007280", "unit_nav": 2.2346,
             "acc_nav": None, "prev_unit_nav": 2.2305, "nav_change_pct": 0.18}]
    with pytest.raises(gap.NonNullConflict):
        gap.check_conflicts(c, "nav", "007280", rows, "test://lsjz")
    c.close()


# ── 证据 5(端到端): 同基金先 T+2 未发布、再发布, 两轮零 prev 冲突 ────────
def _nav_db(tmp_path):
    db = tmp_path / "pf.db"
    c = sqlite3.connect(str(db))
    c.executescript("""
    CREATE TABLE fund_daily_nav (
      date TEXT NOT NULL, fund_code TEXT NOT NULL, fund_name TEXT,
      unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL,
      PRIMARY KEY (date, fund_code));
    """)
    c.commit()
    return c


def test_two_run_no_prev_conflict(monkeypatch, tmp_path):
    """同一基金重复跑两轮(复刻 collect 的 拉取→check_conflicts→UPSERT 路径):
    第 1 轮 10-16 未发布(旧逻辑会写 10-15 错位值), 第 2 轮 10-16 已发布;
    两轮均不产生 prev_unit_nav 冲突, 且 10-19 行 prev 最终 == 10-16 真值。"""
    from app.collector import public_fund_gap as gap
    round1 = [
        {"FSRQ": "2026-10-19", "DWJZ": "2.2346", "LJJZ": "1.1", "JZZZL": "0.18"},
        {"FSRQ": "2026-10-15", "DWJZ": "2.1921", "LJJZ": "1.0", "JZZZL": "1.75"},
        {"FSRQ": "2026-10-14", "DWJZ": "2.1800", "LJJZ": "0.9", "JZZZL": "0.56"},
    ]
    round2 = [
        {"FSRQ": "2026-10-19", "DWJZ": "2.2346", "LJJZ": "1.1", "JZZZL": "0.18"},
        {"FSRQ": "2026-10-16", "DWJZ": "2.2305", "LJJZ": "1.0", "JZZZL": "1.75"},
        {"FSRQ": "2026-10-15", "DWJZ": "2.1921", "LJJZ": "1.0", "JZZZL": "1.75"},
        {"FSRQ": "2026-10-14", "DWJZ": "2.1800", "LJJZ": "0.9", "JZZZL": "0.56"},
    ]
    conn = _nav_db(tmp_path)
    for rnd, stub in ((1, round1), (2, round2)):
        _stub_lsjz(monkeypatch, stub)
        rows = mod.fetch_lsjz("007280", "2026-10-09", "2026-10-20")
        # 冲突检测照常先行: 真实不一致仍整只拒绝(此处无差异, 不抛)
        gap.check_conflicts(conn, "nav", "007280", rows, "test://lsjz")
        conn.executemany(mod.UPSERT_SQL, [
            (r["date"], r["fund_code"], "测试QDII", r["unit_nav"], r["acc_nav"],
             r["prev_unit_nav"], r["nav_change_pct"]) for r in rows])
        conn.commit()
        if rnd == 1:
            prev1 = conn.execute(
                "SELECT prev_unit_nav FROM fund_daily_nav WHERE date='20261019'").fetchone()[0]
            assert prev1 is None  # 未发布窗口不再写 10-15 错位值
    prev2 = conn.execute(
        "SELECT prev_unit_nav FROM fund_daily_nav WHERE date='20261019'").fetchone()[0]
    assert prev2 == pytest.approx(2.2305)  # 发布后 gap/UPSERT 只补空, 自然补齐真值
    conn.close()
