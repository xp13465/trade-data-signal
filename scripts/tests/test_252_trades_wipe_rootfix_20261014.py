# -*- coding: utf-8 -*-
"""#252 trades 历史行被「重算抹除」根治 A 包 自测(T1/T3/T5 + T2 止血脚本)。

覆盖
  T1  app/history_audit.audit_signal_daily_store  —— signal_daily 重算前后历史行 diff 落表+告警
  T3  app/history_audit.audit_index_rows_upsert   —— index_daily 整段重写历史行实质改写审计
  T2b scripts/trades_orphan_backfill             —— 冻结表孤儿买事件 → 次日 open 候选清单(只读)
  §18 L48 零外发: 审计告警必须先打桩; 本文件用 ZeroOutboundTrap 包裹并**先证打桩生效**
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _zero_outbound import ZeroOutboundTrap  # noqa: E402
from app import history_audit  # noqa: E402
from app.db import SCHEMA  # noqa: E402
import trades_orphan_backfill as tob  # noqa: E402

RUN_DATE = "20261014"


def _mem_conn():
    """内存库 + 生产同一份 SCHEMA(零漂移;不碰 data/ 下任何真实 DB)。"""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _audit_rows(conn, src_table=None):
    q = "SELECT src_table, kind, date, index_id, signal, before_val, after_val FROM history_overwrite_audit"
    args = ()
    if src_table:
        q += " WHERE src_table=?"
        args = (src_table,)
    return conn.execute(q + " ORDER BY date, index_id, kind", args).fetchall()


@pytest.fixture
def recorder(monkeypatch):
    """把审计的告警出口换成记录器(§18 L48: 绝不真发)。"""
    calls = []

    def _fake(subject, body, **kw):
        calls.append({"subject": subject, "body": body, **kw})
        return 0

    monkeypatch.setattr(history_audit, "send_alert", _fake)
    return calls


# ────────────────────────── T1: signal_daily 重算审计 ──────────────────────────

def test_signal_audit_flags_disappear_and_appear(recorder):
    """buy→buy_aux 类型漂移: 消失 + 出现两条都记, 且告警一次。"""
    conn = _mem_conn()
    before = {("20261012", "csi_000673", "buy_aux"), ("20261012", "sz_div", "buy")}
    after = {("20261012", "csi_000673", "buy_aux"), ("20261012", "sz_div", "buy_aux")}

    changes = history_audit.audit_signal_daily_store(conn, before, after, run_date=RUN_DATE)

    assert [c["kind"] for c in changes] == ["disappeared", "appeared"]
    assert {c["signal"] for c in changes} == {"buy", "buy_aux"}
    rows = _audit_rows(conn, "signal_daily")
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"disappeared", "appeared"}
    assert len(recorder) == 1
    assert "历史行被重写 2 条" in recorder[0]["subject"]
    assert recorder[0]["dedup_key"] == f"history_overwrite:signal_daily:{RUN_DATE}"


def test_signal_audit_silent_when_no_change(recorder):
    conn = _mem_conn()
    same = {("20261012", "csi_000673", "buy_aux")}
    assert history_audit.audit_signal_daily_store(conn, same, set(same), run_date=RUN_DATE) == []
    assert _audit_rows(conn, "signal_daily") == []
    assert recorder == []


def test_signal_audit_ignores_pure_backfill(recorder):
    """纯历史回填(只有出现,无消失): 合法补账 → 不落表不告警(防告警风暴)。"""
    conn = _mem_conn()
    after = {("20261012", "csi_000673", "buy_aux"), ("20261013", "sz_div", "buy")}
    changes = history_audit.audit_signal_daily_store(conn, set(), after, run_date=RUN_DATE)
    assert [c["kind"] for c in changes] == ["appeared", "appeared"]  # diff 全貌仍返回
    assert _audit_rows(conn, "signal_daily") == []   # 但不落表
    assert recorder == []                            # 也不告警


def test_signal_snapshot_only_history(monkeypatch):
    """snapshot 只取 date < run_date 的历史行(当日行不在审计范围)。"""
    conn = _mem_conn()
    conn.executemany("INSERT INTO signal_daily (date, index_id, signal) VALUES (?,?,?)",
                     [("20261013", "a", "buy"), ("20261014", "b", "buy")])
    snap = history_audit.snapshot_signal_daily_history(conn, RUN_DATE)
    assert snap == {("20261013", "a", "buy")}


# ────────────────────────── T3: index_daily 整段重写审计 ──────────────────────────

def _seed_index(conn, date, iid, vals):
    conn.execute(
        "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
        "VALUES (?,?,?,?,?,?,?,?)", (date, iid, *vals))


def test_index_audit_flags_material_change(recorder):
    conn = _mem_conn()
    _seed_index(conn, "20261013", "csi_000673", (3125.973, 3126.0, 3057.216, 3057.907, -2.87, 1e9))
    # 采集整段重写: close 由盘中占位 3126 被真实值 3057.907 覆盖 + 历史行整段替换
    rows = [("20261013", "csi_000673", 3125.973, 3126.0, 3057.216, 3057.907, -2.87, 1e9),
            ("20261013", "csi_000673", 3125.973, 3126.0, 3057.216, 2987.8, -4.55, 1e9)]
    changes = history_audit.audit_index_rows_upsert(rows[1:], conn=conn, run_date=RUN_DATE)
    assert len(changes) == 1
    assert changes[0]["kind"] == "changed"
    assert changes[0]["index_id"] == "csi_000673"
    assert "3126" in changes[0]["before_val"] and "2987.8" in changes[0]["after_val"]
    assert len(_audit_rows(conn, "index_daily")) == 1
    assert len(recorder) == 1
    assert "值改写1" in recorder[0]["subject"]


def test_index_audit_ignores_rounding_noise(recorder):
    """源端舍入抖动(1e-9 级)不算改写,不制造噪声告警。"""
    conn = _mem_conn()
    _seed_index(conn, "20261013", "sw_801230", (4012.0, 4013.0, 4000.0, 4001.234, 0.1, 2e9))
    rows = [("20261013", "sw_801230", 4012.000000001, 4013.0, 4000.0, 4001.234000001, 0.1, 2e9)]
    assert history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE) == []
    assert recorder == []


def test_index_audit_ignores_new_rows(recorder):
    """库中原本没有的历史行(首次回填)不算改写。"""
    conn = _mem_conn()
    rows = [("20250801", "csi_000673", 1.0, 2.0, 0.5, 1.5, 1.0, 3e8)]
    assert history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE) == []
    assert recorder == []


def test_index_audit_row_partial_only_compares_given_cols(recorder):
    """单行局部审计(计算法 UPDATE 只改 close): 不因未动列(amount/open)误报。"""
    conn = _mem_conn()
    _seed_index(conn, "20261013", "sw_801230", (4012.0, 4013.0, 4000.0, 4001.234, 0.1, 2e9))
    # 只改 close 且值变化 → 记 1 条
    assert len(history_audit.audit_index_row_partial(
        conn, RUN_DATE, "20261013", "sw_801230", {"close": 3500.0})) == 1
    # 只改 close 但值在同一容差内 → 不记
    assert history_audit.audit_index_row_partial(
        conn, RUN_DATE, "20261013", "sw_801230", {"close": 4001.2340001}) == []
    # 不存在的行(新增) → 不记
    assert history_audit.audit_index_row_partial(
        conn, RUN_DATE, "20261013", "nope", {"close": 1.0}) == []
    # 白名单外列名 → 直接忽略(不拼进 SQL)
    assert history_audit.audit_index_row_partial(
        conn, RUN_DATE, "20261013", "sw_801230", {"evil; DROP TABLE": 1}) == []
    assert len(_audit_rows(conn, "index_daily")) == 1


def test_index_backfill_fallback_row_routes_through_audit(tmp_prod_db, monkeypatch):
    """index_backfill 3 处单行兜底写历史行 → 也过审计入口(§23.2③ 同类写入面统一)。"""
    from app.collector import index_backfill
    from app.db import get_conn
    c = get_conn()
    _seed_index(c, "20261013", "hkHSI", (25000.0, 25100.0, 24900.0, 25050.0, 0.2, None))
    c.commit()
    c.close()
    calls = []
    monkeypatch.setattr(history_audit, "send_alert", lambda s, b, **kw: calls.append(s) or 0)
    c = get_conn()
    index_backfill._audit_hist_row(
        c, "20261013", "hkHSI", (25000.0, 25100.0, 24900.0, 24000.0, -2.1, None))
    c.close()
    chk = sqlite3.connect(str(tmp_prod_db))
    rows = chk.execute("SELECT kind, date, index_id FROM history_overwrite_audit").fetchall()
    chk.close()
    assert rows == [("changed", "20261013", "hkHSI")]
    assert len(calls) == 1


def test_index_audit_skips_current_day(recorder):
    """当日行(date == run_date)不在审计范围(盘中正常抖动)。"""
    conn = _mem_conn()
    _seed_index(conn, RUN_DATE, "csi_000673", (1.0, 1.0, 1.0, 1.0, 0.0, 1e8))
    rows = [(RUN_DATE, "csi_000673", 9.0, 9.0, 9.0, 9.0, 9.0, 9e8)]
    assert history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE) == []
    assert recorder == []


# ────────────────────────── T1/T3/T5 接线(端到端: store / upsert_index_rows) ──────────────────────────

@pytest.fixture
def tmp_prod_db(tmp_path, monkeypatch):
    """把 app.db.DB_PATH 指向 tmp 库(不碰任何真实 DB),并强制首跑建表。"""
    from app import db as appdb
    p = tmp_path / "sentiment.db"
    monkeypatch.setattr(appdb, "DB_PATH", p)
    monkeypatch.setattr(appdb, "_schema_ensured", True)  # 禁止跑 SCHEMA(下面手动建最小表)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row      # _migrate 用 row["name"] 取值(与 get_conn 同设置)
    conn.executescript(SCHEMA)
    appdb._migrate(conn)          # 补 index_daily.source 等增量列(与生产 get_conn 同链)
    conn.commit()
    conn.close()
    return p


def test_signals_store_wires_t1_audit(tmp_prod_db, monkeypatch):
    """signals.store() 真的接线了 T1: 历史行在重算后消失 → 落审计表 + 告警。"""
    from app.compute import signals as sigmod
    from app.db import get_conn
    c = get_conn()
    c.execute("INSERT INTO signal_daily (date, index_id, signal, reason) VALUES (?,?,?,?)",
              ("20261013", "csi_000673", "buy_aux", "布林下轨回归"))
    c.commit()
    c.close()
    calls = []
    monkeypatch.setattr(history_audit, "send_alert",
                        lambda s, b, **kw: calls.append(s) or 0)
    # 钉死运行日:store() 内部用真实今天(history_audit.today_ymd)判定历史行,
    # 若不钉则测试出生当天(新行==运行日,只落 disappeared)绿、隔天再跑变历史行多落
    # appeared 而炸(时敏用例)。打桩模块属性即可命中(store 函数体内 from ..history_audit import)。
    monkeypatch.setattr(history_audit, "today_ymd", lambda: RUN_DATE)
    n = sigmod.store([("20261014", "sz_div", "buy", "x")])
    assert n == 1
    c = sqlite3.connect(str(tmp_prod_db))
    rows = c.execute("SELECT kind, date, index_id, signal FROM history_overwrite_audit").fetchall()
    c.close()
    assert rows == [("disappeared", "20261013", "csi_000673", "buy_aux")]
    assert len(calls) == 1


def test_upsert_index_rows_wires_t3_audit_and_source(tmp_prod_db, monkeypatch):
    """runner.upsert_index_rows(): ①写 source 列(T5) ②历史行实质改写落审计(T3)。"""
    from app.collector import runner
    from app.db import get_conn
    c = get_conn()
    c.execute("INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount, source) "
              "VALUES (?,?,?,?,?,?,?,?,?)",
              ("20261013", "csi_000673", 3125.973, 3126.0, 3057.216, 3126.0, -0.7, 1e9, "intraday_snapshot"))
    c.commit()
    c.close()
    calls = []
    monkeypatch.setattr(history_audit, "send_alert", lambda s, b, **kw: calls.append(s) or 0)

    # 行情源全历史重采: 历史行 close 由占位 3126 被真实 3057.907 覆盖
    runner.upsert_index_rows(
        [("20261013", "csi_000673", 3125.973, 3126.0, 3057.216, 3057.907, -2.87, 1e9)], source="collect")

    c = sqlite3.connect(str(tmp_prod_db))
    src = c.execute("SELECT source FROM index_daily WHERE date='20261013' AND index_id='csi_000673'").fetchone()[0]
    aud = c.execute("SELECT kind, before_val, after_val FROM history_overwrite_audit").fetchall()
    c.close()
    assert src == "collect"                     # T5: source 随整段 UPSERT 一起刷新
    assert len(aud) == 1 and aud[0][0] == "changed"  # T3: 历史行值改写被审计
    assert len(calls) == 1


# ────────────────────────── §18 L48 零外发 ──────────────────────────

def test_zero_outbound_stub_effective_and_no_real_send(recorder):
    """两条: ① 陷阱本身有效(正控: 触真实出口必炸) ② 本审计自测全程零真实外发。"""
    with ZeroOutboundTrap() as trap:
        import urllib.request
        # 正控 —— 先证打桩/陷阱真的在工作(否则「零外发」是假绿)
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://127.0.0.1:1/never")
        assert trap.hits == ["urllib.request.urlopen"]
        trap.hits.clear()

        conn = _mem_conn()
        before = {("20261012", "x", "buy"), ("20261012", "y", "buy_aux")}
        history_audit.audit_signal_daily_store(conn, before, set(), run_date=RUN_DATE)
        _seed_index(conn, "20261013", "z", (1.0, 1.0, 1.0, 1.0, 0.0, 1e8))  # 已存在 → 值改写
        history_audit.audit_index_rows_upsert(
            [("20261013", "z", 1.0, 1.0, 1.0, 9.0, 0.0, 1e8)], conn=conn, run_date=RUN_DATE)
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"

    assert len(recorder) == 2  # 告警走了打桩出口, 没走真实 notify


# ────────────────────────── T2b: 止血候选清单(只读) ──────────────────────────

def _make_etf_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE etf_daily (etf_code TEXT, date TEXT, open REAL, close REAL)")
    conn.executemany("INSERT INTO etf_daily VALUES (?,?,?,?)", [
        ("562810", "20261012", 1.10, 1.12),
        ("562810", "20261013", 1.15, 1.18),   # 10-12 信号的次日 open
        ("562810", "20261014", 1.20, 1.19),
        ("159999", "20261014", 2.00, 2.01),
    ])
    conn.commit()
    conn.close()


def _make_main_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO signal_daily (date, index_id, signal) VALUES (?,?,?)", [
        ("20261012", "csi_000330", "buy_aux"),   # 仍在
    ])
    conn.commit()
    conn.close()


def test_next_open_after_strictly_later():
    opens = [("20261012", 1.10), ("20261013", 1.15), ("20261014", 1.20)]
    assert tob.next_open_after(opens, "20261012") == ("20261013", 1.15)
    assert tob.next_open_after(opens, "20261014") == (None, None)
    assert tob.next_open_after([], "20261012") == (None, None)


def test_build_candidates_readonly_and_correct():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main_db = os.path.join(td, "main.db")
        etf_db = os.path.join(td, "etf.db")
        _make_main_db(main_db)
        _make_etf_db(etf_db)
        md5_before = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in (main_db, etf_db)}

        freeze = {
            "20261012|csi_000330|buy_aux": {"code": "562810", "name": "A", "frozen_at": "2026-10-12 16:38"},
            "20261012|csi_000673|buy_aux": {"code": "562810", "name": "A", "frozen_at": "2026-10-12 16:38"},
            "20261012|sz_div|buy": {"code": "159999", "name": "B", "frozen_at": "2026-10-12 16:38"},
            "20261012|us_ixic|buy_special": {"code": "159999", "name": "B", "frozen_at": "2026-10-13 05:03"},
        }
        present_di = tob.load_present_di(main_db)
        assert present_di == {("20261012", "csi_000330")}

        res = tob.build_candidates(freeze, present_di, etf_db)

        # csi_000330 仍在现值表 → 非孤儿; 其余 3 条 = 孤儿(buy 类,含 buy_special)
        got = {(c["date"], c["index_id"], c["signal"]) for c in res["candidates"]}
        assert got == {("20261012", "csi_000673", "buy_aux"),
                       ("20261012", "sz_div", "buy"),
                       ("20261012", "us_ixic", "buy_special")}
        # 防前视: 买价取「信号日之后第一个有行情日」的 open
        for c in res["candidates"]:
            if c["etf_code"] == "562810":
                assert (c["buy_date"], c["buy_price"]) == ("20261013", 1.15)
            else:  # 159999 只有 20261014
                assert (c["buy_date"], c["buy_price"]) == ("20261014", 2.00)
            assert c["source"] == "freeze_table_orphan"
        assert res["skipped_no_price"] == []
        assert res["stats"]["orphan_events"] == 3
        assert "readonly" not in res["stats"]  # readonly 标记在 main 的 meta 里

        # 只读铁证: 两库文件 md5 逐位不变(绝不写 signal_daily / 任何表)
        md5_after = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in (main_db, etf_db)}
        assert md5_after == md5_before


def test_build_candidates_reports_missing_price():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        main_db = os.path.join(td, "main.db")
        etf_db = os.path.join(td, "etf.db")
        _make_main_db(main_db)
        _make_etf_db(etf_db)
        freeze = {"20261012|zz|buy": {"code": "000000", "name": "X", "frozen_at": "x"}}
        res = tob.build_candidates(freeze, tob.load_present_di(main_db), etf_db)
        assert res["candidates"] == []
        assert len(res["skipped_no_price"]) == 1
        assert res["skipped_no_price"][0]["reason"].startswith("次日无行情")
        assert res["stats"]["candidates"] == 0


def test_ro_connect_rejects_missing_file():
    with pytest.raises(FileNotFoundError):
        tob._ro_connect("/nonexistent/definitely/missing.db")


def test_main_writes_only_out_file(tmp_path):
    """main --out 只写输出文件; 两个只读 DB md5 不变。"""
    main_db = str(tmp_path / "main.db")
    etf_db = str(tmp_path / "etf.db")
    freeze_path = str(tmp_path / "freeze.json")
    _make_main_db(main_db)
    _make_etf_db(etf_db)
    import json
    with open(freeze_path, "w", encoding="utf-8") as f:
        json.dump({"20261012|sz_div|buy": {"code": "159999", "name": "B", "frozen_at": "x"}}, f)
    md5_before = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in (main_db, etf_db)}

    out = str(tmp_path / "cands.json")
    rc = tob.main(["--freeze", freeze_path, "--db", main_db, "--etf-db", etf_db, "--out", out])
    assert rc == 0
    data = json.load(open(out, encoding="utf-8"))
    assert data["stats"]["candidates"] == 1
    assert data["meta"]["readonly"] is True
    md5_after = {p: hashlib.md5(open(p, "rb").read()).hexdigest() for p in (main_db, etf_db)}
    assert md5_after == md5_before