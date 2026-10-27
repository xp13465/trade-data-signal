# -*- coding: utf-8 -*-
"""#288 历史改写审计「NULL↔NaN 假改写」根治 + csi_000102 盘中映射纠错 自测(2026-10-28)。

背景(诊断报告 docs/ops/index-daily-rewrite-diagnosis-20261028.md)
  ① `history_overwrite_audit` 491,532 行里 490,384 行(99.77%)是「库里 NULL、采集回 NaN」的
     纯表示差异被比较器判成改写;真实变化只有 80–128 行/天。
  ② `_SIGNAL_UNIVERSE_TENCENT_MAP["csi_000102"]` 被机械规则套成 sh000102(沪投资品),
     而配置里 csi_000102 = 创业板综 sz399102 ⇒ 每交易日盘中当日点位错成另一个标的。

覆盖
  A. `_values_changed` 判据逐条(缺失等价/值↔缺失仍算变/字段级容差/纠错红线)
  B. 端到端:`audit_index_rows_upsert` NULL↔NaN 不落表不告警;真纠错仍落表
  C. 端到端:`audit_index_row_partial` 只改 pct 的精度抖动不误报(局部列顺序对齐)
  D. `_SIGNAL_UNIVERSE_TENCENT_MAP` 48 条 vs `config/indicators.yaml` **配置驱动**全量一致
  §18 L48 零外发:所有审计用例 monkeypatch `history_audit.send_alert`,不触真实通知链。
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).absolute().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import history_audit  # noqa: E402
from app.collector.intraday_snapshot import _SIGNAL_UNIVERSE_TENCENT_MAP  # noqa: E402
from app.db import SCHEMA  # noqa: E402

RUN_DATE = "20261028"
NAN = float("nan")


def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _row(open=None, high=None, low=None, close=None, pct_change=None, amount=None):
    """按 _IDX_VALUE_COLS 顺序(open, high, low, close, pct_change, amount)组一行。"""
    return (open, high, low, close, pct_change, amount)


def _insert_index_row(conn, date, index_id, open_, high, low, close, pct, amount):
    """只写 app/db.py SCHEMA 里的列(生产库的 source 列是 ALTER 加的, 内存库无)。"""
    conn.execute(
        "INSERT INTO index_daily (date, index_id, open, high, low, close, pct_change, amount) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (date, index_id, open_, high, low, close, pct, amount),
    )
    conn.commit()


@pytest.fixture
def no_alert(monkeypatch):
    """兜底零外发:审计告警必须被打桩(§18 L48)。返回被调用记录供断言。"""
    calls = []

    def _fake(*a, **kw):
        calls.append((a, kw))
        return 0

    monkeypatch.setattr(history_audit, "send_alert", _fake)
    return calls


# ────────────────────────── A. 比较器判据 ──────────────────────────

@pytest.mark.parametrize("before,after,expected,why", [
    # 缺失 ↔ 缺失(任意组合)= 不变化
    (_row(), _row(NAN, NAN, NAN, NAN, NAN, NAN), False, "None↔NaN 都是缺失"),
    (_row(NAN, NAN, NAN, NAN, NAN, NAN), _row(), False, "NaN↔None 都是缺失"),
    (_row(100.0, NAN, None, 105.0, NAN, 1e9), _row(100.0, None, NAN, 105.0, None, 1e9),
     False, "缺失混排(None/NaN 互换) + 有值字段相同"),
    # 值 ↔ 缺失 = 仍算变化(真丢行不许吞)
    (_row(100.0), _row(NAN), True, "值↔NaN 必须判变化"),
    (_row(NAN), _row(100.0), True, "NaN↔值 必须判变化"),
    (_row(None, None, None, None, 1.0, None), _row(), True, "值→缺失(None)也要判变化"),
    # 数值纠错红线
    (_row(close=6562.71), _row(close=3367.89), True, "csi_000102 张冠李戴纠错必须可见"),
    # pct 发布精度抖动(实测最大 0.00501)在字段级绝对容差 0.006 内 = 不变化
    (_row(pct_change=-0.88), _row(pct_change=-0.884983), False, "pct 2 位小数舍入抖动"),
    (_row(pct_change=-2.96), _row(pct_change=-2.96501), False, "实测最大抖动 0.00501"),
    (_row(pct_change=0.1), _row(pct_change=0.095385), False, "0.1→0.095385"),
    # 超出 pct 容差 = 变化
    (_row(pct_change=-0.88), _row(pct_change=-0.90), True, "pct 差 0.02 超容差"),
    # amount:不加绝对容差, 真实成交额修正必须可见
    (_row(amount=6.03992e10), _row(amount=5.64961e10), True, "成交额真实修正"),
    (_row(amount=1.0e10), _row(amount=1.0000001e10), False, "amount 纯浮点舍入(rel 1e-7)"),
    # 混排:pct 抖动可忽略, 但 close 真变化 ⇒ 整体仍算变化
    (_row(close=3367.89, pct_change=-0.88), _row(close=3354.83, pct_change=-0.884983), True,
     "pct 抖动不许掩盖 close 变化"),
    # 非数值
    (_row(), _row(), False, "全 None"),
])
def test_values_changed_judgement(before, after, expected, why):
    assert history_audit._values_changed(before, after) is expected, why


def test_values_changed_nan_equivalent_is_symmetric():
    """同一行 NULL↔NaN 在任意字段位置都不算变化(旧逻辑 6 个字段任一处命中即返回 True)。"""
    base = _row(100.0, 110.0, 90.0, 105.0, 5.0, 1e9)
    nan_row = _row(100.0, NAN, 90.0, NAN, NAN, 1e9)
    none_row = _row(100.0, None, 90.0, None, None, 1e9)
    assert history_audit._values_changed(none_row, nan_row) is False
    assert history_audit._values_changed(base, nan_row) is True


def test_is_missing_covers_none_and_nan_and_rejects_str():
    assert history_audit._is_missing(None) is True
    assert history_audit._is_missing(NAN) is True
    assert history_audit._is_missing(0.0) is False
    assert history_audit._is_missing("abc") is False


# ────────────────────────── B. 整段 UPSERT 审计端到端 ──────────────────────────

def test_upsert_audit_ignores_null_nan_representation(no_alert):
    """核心根因:库里 NULL、采集回 NaN ⇒ 不落表、不告警(旧逻辑落 1 行 + 告警)。"""
    conn = _mem_conn()
    _insert_index_row(conn, "20200102", "csi_932365", None, None, None, 2354.37, 1.4, 251.25)
    rows = [("20200102", "csi_932365", NAN, NAN, NAN, 2354.37, 1.4, 251.25)]

    changes = history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE)

    assert changes == []
    assert conn.execute("SELECT COUNT(*) FROM history_overwrite_audit").fetchone()[0] == 0
    assert no_alert == []


def test_upsert_audit_still_records_real_correction(no_alert):
    """csi_000102 张冠李戴(6562.71→3367.89)必须仍被判改写并落表 + 告警。"""
    conn = _mem_conn()
    _insert_index_row(conn, "20261026", "csi_000102", 6562.71, 6562.71, 6562.71, 6562.71, -0.88, None)
    rows = [("20261026", "csi_000102", 3367.89, 3396.24, 3319.9, 3354.83, -1.57514, None)]

    changes = history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE)

    assert len(changes) == 1
    assert changes[0]["index_id"] == "csi_000102"
    assert conn.execute("SELECT COUNT(*) FROM history_overwrite_audit").fetchone()[0] == 1
    assert len(no_alert) == 1


def test_upsert_audit_value_to_missing_is_not_swallowed(no_alert):
    """真丢值(库里 100.0 → 采集回 NaN)必须仍记改写(反例保护缺一不可)。"""
    conn = _mem_conn()
    _insert_index_row(conn, "20261026", "csi_000330", 100.0, 110.0, 90.0, 105.0, 1.0, 1e9)
    rows = [("20261026", "csi_000330", NAN, 110.0, 90.0, 105.0, 1.0, 1e9)]

    changes = history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE)

    assert len(changes) == 1


def test_upsert_audit_ignores_pct_precision_jitter(no_alert):
    """四价全同、只有 pct 由 2 位小数变全精度 ⇒ 不落表(实测 450 行/14 天的噪声类)。"""
    conn = _mem_conn()
    _insert_index_row(conn, "20261013", "sh", 3760.8, 3822.11, 3741.53, 3800.86, 0.1, None)
    rows = [("20261013", "sh", 3760.8, 3822.11, 3741.53, 3800.86, 0.095385, None)]

    assert history_audit.audit_index_rows_upsert(rows, conn=conn, run_date=RUN_DATE) == []
    assert no_alert == []


# ────────────────────────── C. 局部字段审计(列顺序对齐) ──────────────────────────

def test_partial_audit_pct_only_aligned_with_column_order(no_alert):
    """updates 只含 pct_change 时 cols=['pct_change'], 字段级容差必须仍命中(靠 fields=cols)。"""
    conn = _mem_conn()
    _insert_index_row(conn, "20261013", "sh", 3760.8, 3822.11, 3741.53, 3800.86, 0.1, None)

    changes = history_audit.audit_index_row_partial(
        conn, RUN_DATE, "20261013", "sh", {"pct_change": 0.095385})

    assert changes == []
    assert no_alert == []


def test_partial_audit_value_to_missing_recorded(no_alert):
    """局部字段 close 由值变 None(值→缺失)仍算改写。"""
    conn = _mem_conn()
    _insert_index_row(conn, "20261013", "sh", 3760.8, 3822.11, 3741.53, 3800.86, 0.1, None)

    changes = history_audit.audit_index_row_partial(conn, RUN_DATE, "20261013", "sh", {"close": None})

    assert len(changes) == 1


# ────────────────────────── D. 48 条腾讯映射 vs 配置(配置驱动) ──────────────────────────

def _indicator_symbols():
    """config/indicators.yaml 的 id → (name, symbol)(递归收集所有含 id+symbol 的条目)。"""
    cfg = yaml.safe_load((ROOT / "config" / "indicators.yaml").read_text())
    out = {}

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "symbol" in o:
                out[o["id"]] = (o.get("name"), o["symbol"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(cfg)
    return out


def _bare(code):
    """去掉腾讯/新浪市场前缀(sh/sz/r_hk), 只比代码本体。"""
    c = str(code)
    for p in ("r_hk", "sh", "sz"):
        if c.startswith(p):
            return c[len(p):]
    return c


def test_csi_000102_maps_to_chuangye_zong():
    """修二点名断言: 创业板综, 不是沪投资品 sh000102。"""
    assert _SIGNAL_UNIVERSE_TENCENT_MAP["csi_000102"] == "sz399102"


def test_tencent_map_matches_indicators_config_all_entries():
    """48 条逐条与 indicators.yaml 的 symbol 对齐(配置驱动, 新增条目自动纳入, 不写死)。"""
    cfg = _indicator_symbols()
    assert len(_SIGNAL_UNIVERSE_TENCENT_MAP) == 48, "映射表条数变化请同步复核并更新本断言"

    not_in_cfg = sorted(set(_SIGNAL_UNIVERSE_TENCENT_MAP) - set(cfg))
    assert not not_in_cfg, f"映射表出现配置里没有的 id(需人工确认): {not_in_cfg}"

    mismatches = {
        iid: (mv, cfg[iid][1], cfg[iid][0])
        for iid, mv in _SIGNAL_UNIVERSE_TENCENT_MAP.items()
        if _bare(mv) != _bare(cfg[iid][1])
    }
    assert not mismatches, f"映射值 vs 配置 symbol 不一致(不许自行取舍, 报主控): {mismatches}"


def test_tencent_map_csi_000xxx_rule_exceptions_documented():
    """csi_000xxx 机械规则→sh 的两条历史例外 + 本次新增例外必须都在映射表里。"""
    assert _SIGNAL_UNIVERSE_TENCENT_MAP["csi_000330"] == "sz399330"   # 深证100
    assert _SIGNAL_UNIVERSE_TENCENT_MAP["csi_000673"] == "sz399673"   # 创业板50
    assert _SIGNAL_UNIVERSE_TENCENT_MAP["csi_000102"] == "sz399102"   # 创业板综(2026-10-28)