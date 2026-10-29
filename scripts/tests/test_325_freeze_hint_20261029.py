# -*- coding: utf-8 -*-
"""#325 首屏瘦身：overview.freeze_hint 单测 + 前后端常量源形状守卫。

约束（派单要求）：
- 只用临时 sqlite（禁打生产库/真镜像库，禁写根 data/）；
- 所有日期由用例参数注入，不写死真实 today（L51：被测代码取 today() 时必须注入/冻结运行日）；
- 覆盖：四档文案（近N月/近N年/近期持续冰点/数据期内首次）、今日不足 3 冰点 → None、
  共振阈值 2 vs 3 边界、20100101 历史下界、M2 上界（某宽基停更致 cur_date 回退）、
  M1 异常降级（返回 None + warning 日志，不抛给 overview/export）；
- S2 源形状守卫：前端 app.js `_BROAD_SENT_IDS` 与后端 BROAD_SENT_IDS 全等且同序；
  `_FREEZE_HISTORY_START` 必须等于 `range_for("all")[0]`。
"""
import logging
import re
import sqlite3
from pathlib import Path

from app import queries
from app.queries import BROAD_SENT_IDS, _FREEZE_HISTORY_START, _freeze_hint

IDS = list(BROAD_SENT_IDS)
REPO = Path(__file__).resolve().parents[2]
APP_JS = REPO / "static-site" / "app.js"


def _conn(rows):
    """临时内存 sqlite：表结构与生产 score_daily 的对账所需列一致（date/score_id/value/is_freeze）。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE score_daily ("
        "date TEXT NOT NULL, score_id TEXT NOT NULL, value REAL, is_freeze INTEGER)"
    )
    if rows:
        conn.executemany("INSERT INTO score_daily VALUES (?, ?, ?, ?)", rows)
    return conn


def _day(date, n_frozen):
    """某日 6 宽基行：前 n_frozen 个冰点（value=10 / is_freeze=1），其余正常（value=60）。"""
    rows = []
    for i, sid in enumerate(IDS):
        frozen = i < n_frozen
        rows.append((date, sid, 10.0 if frozen else 60.0, 1 if frozen else 0))
    return rows


def _scores(date, n_frozen):
    """今日卡片分数（overview 里 today.scores 的形态）。"""
    out = {}
    for i, sid in enumerate(IDS):
        frozen = i < n_frozen
        out[sid] = {"value": 10.0 if frozen else 60.0, "is_freeze": frozen, "date": date}
    return out


# ---------- 四档文案 ----------

def test_wording_months():
    rows = _day("20260115", 3) + _day("20260410", 3)
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "近3月首次"


def test_wording_years():
    rows = _day("20230105", 3) + _day("20260410", 3)
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "近3年首次"


def test_wording_recent_persistent():
    """同月内（月差 0）⇒ 近期持续冰点；跨月（即使只差 20 天）按“近1月首次”。"""
    rows = _day("20260401", 3) + _day("20260410", 3)
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "近期持续冰点"


def test_wording_first_in_period():
    """历史表里有数据（只是从没共振过）⇒ 数据期内首次。"""
    rows = _day("20260410", 3) + [("20260409", IDS[0], 60.0, 0)]
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "数据期内首次"


# ---------- 不足 3 / 阈值边界 ----------

def test_less_than_three_frozen_returns_none():
    rows = _day("20260115", 3) + _day("20260410", 2)
    assert _freeze_hint(_conn(rows), _scores("20260410", 2), "20260410") is None


def test_three_is_threshold_but_two_is_not():
    rows = _day("20260115", 3) + _day("20260410", 3)
    conn = _conn(rows)
    assert _freeze_hint(conn, _scores("20260410", 3), "20260410") == "近3月首次"
    assert _freeze_hint(conn, _scores("20260410", 2), "20260410") is None


def test_two_frozen_day_does_not_count_as_prev():
    """历史上某日只 2 个冰点不算共振日；prev 应取更早的真正共振日。"""
    rows = (
        _day("20260101", 3)
        + _day("20260301", 2)
        + _day("20260410", 3)
    )
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "近3月首次"


def test_history_only_today_still_first_in_period():
    """历史表里只有当前锚当天一行（数据首日）⇒ 数据期内首次（对齐旧前端口径，不返回 None）。"""
    rows = _day("20100101", 3)
    assert _freeze_hint(_conn(rows), _scores("20100101", 3), "20100101") == "数据期内首次"


def test_empty_history_returns_none():
    """历史表完全为空 ⇒ None（前端不显示这句；与旧前端“历史为空”降级一致）。"""
    assert _freeze_hint(_conn([]), _scores("20260410", 3), "20260410") is None


# ---------- 20100101 历史下界 ----------

def test_history_before_2010_ignored():
    """2009 年的共振日不在前端可见历史内，必须忽略 ⇒ 数据期内首次。"""
    rows = _day("20091201", 3) + [("20100105", IDS[0], 60.0, 0)] + _day("20260410", 3)
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "数据期内首次"


# ---------- M2 上界：某宽基停更，cur_date 回退 ----------

def test_upper_bound_prev_not_taken_from_after_cur_date():
    """当前锚 20260410，但库里还有 20260601 的共振日（如别的宽基数据更晚）。

    没有上界时 20260601 会被当成 prev → 月差为负 → 误报“近期持续冰点”；
    有上界（date < cur_date）⇒ prev 取 20260115 → 近3月首次。
    """
    rows = _day("20260115", 3) + _day("20260410", 3) + _day("20260601", 3)
    assert _freeze_hint(_conn(rows), _scores("20260410", 3), "20260410") == "近3月首次"


# ---------- M1 异常降级 ----------

def test_exception_degrades_to_none_and_logs(caplog):
    """真实异常（临时库缺 score_daily 表）⇒ 返回 None 且有 warning 日志，不向上抛。"""
    conn = sqlite3.connect(":memory:")  # 故意不建表
    with caplog.at_level(logging.WARNING, logger="app.queries"):
        got = _freeze_hint(conn, _scores("20260410", 3), "20260410")
    assert got is None
    assert any("freeze_hint 计算失败" in rec.message for rec in caplog.records)


# ---------- S2 源形状守卫（前后端同一常量登记点）----------

def test_frontend_broad_sent_ids_matches_backend_exactly_and_in_order():
    src = APP_JS.read_text(encoding="utf-8")
    m = re.search(r"_BROAD_SENT_IDS\s*=\s*\[([^\]]*)\]", src)
    assert m, "static-site/app.js 里找不到 _BROAD_SENT_IDS 数组字面量"
    front_ids = re.findall(r"""["']([^"']+)["']""", m.group(1))
    assert front_ids == IDS, (
        "前后端宽基冰点常量不一致（增删或换序）: app.js=%r, app.queries=%r"
        % (front_ids, IDS)
    )


def test_freeze_history_start_equals_range_for_all(monkeypatch):
    """历史下界必须取 range_for("all") 的起点；冻结到期日避免读日历/网络。"""
    monkeypatch.setattr(queries, "last_trading_day", lambda *a, **k: "20261029")
    assert _FREEZE_HISTORY_START == queries.range_for("all")[0]