# -*- coding: utf-8 -*-
"""a_fund_north CCASS 采集器「翻档日查询日期 clamp」自验(2026-10-20)。

背景(根因,不改): app/collector/hkex_ccass_quarterly.py 主路径与回填 CLI 原写
  query_date = q + timedelta(days=20)。
翻档日(= 季度末 + 20 天当天)时 q+20 恰=当天, CCASS mutualmarket.aspx 拒收
「不早于当天」的日期(alert 原文 "Please enter a date earlier than current date."),
→ 空持股 → warn「多源皆败无数据」→ cdi FAIL → deploy 阻断。每季度必复发。

修复(2 处, 同口径): query_date = min(q + 20d, today - 1d)
  · 主路径 fetch_north_fund_ccass_quarterly 循环内;
  · 回填 CLI backfill_quarterly_close_prices 循环内。

用例(对任务书验收逐条):
  a 翻档日钳制: 冻结 today=2026-10-20 时, 2026-09-30 这一档请求日 = 2026/10/19(today-1),
    而 2026-06-30 档仍 = 2026/07/20(q+20 未被误钳);
  b 常规日回归: 冻结 today=2026-10-25 时, 2026-09-30 档请求日逐位不变 = 2026/10/20;
  c 回填 CLI 同款 clamp: backfill_quarterly_close_prices(['20260930']) 在翻档日 = 2026/10/19、
    常规日 = 2026/10/20(参数化, 防两路径口径分叉)。

冻结手法(§18 L51 冻结运行日铁律): monkeypatch 模块级 `_dt` 命名空间, 只冻结
  `date.today()`(其余 date 构造 / timedelta / datetime 全部透传真标准库), **不替换
  标准库 date/datetime 类本体**(否则其它代码假失败)。

零外发(§18 L48): `_fetch_ccass_holdings` / `_latest_quarter_value` / 收盘价取数全打桩;
  另把模块内 `requests` 换成任何 .get/.post 即炸的替身 —— 全程零网络。

判别力(§18 L49 变异看门): 把源码改回 `q + timedelta(days=20)`, 用例 a 必须真红。

复现命令: python -m pytest -q scripts/tests/test_afn_ccass_query_date_clamp_20261020.py
"""
from __future__ import annotations

from datetime import date as _real_date
from datetime import datetime as _real_datetime
from datetime import timedelta as _real_timedelta
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import app.collector.hkex_ccass_quarterly as hkq  # noqa: E402

# 断言计数下限(防收集/执行异常致「0 断言假绿」, 仿 #201/#240/#257)
_MIN_ASSERTIONS = 17
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


def _freeze_today(monkeypatch, ymd: str):
    """把 hkq._dt 换成「date.today() 冻结到 ymd, 其余透传真标准库」的命名空间替身。"""
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:])
    frozen = _real_date(y, m, d)

    class _FrozenDate(_real_date):
        @classmethod
        def today(cls):
            return frozen

    class _Shim:
        date = _FrozenDate
        timedelta = _real_timedelta
        datetime = _real_datetime

    monkeypatch.setattr(hkq, "_dt", _Shim)
    return frozen


class _NoNetRequests:
    """模块内 requests 替身: 任何 Session().get/.post 触达即炸(证明零外发)。"""

    class Session:  # noqa: D401
        def get(self, *a, **k):
            raise AssertionError("零外发被破坏: requests.get 被触达")

        def post(self, *a, **k):
            raise AssertionError("零外发被破坏: requests.post 被触达")


def _stub_module(monkeypatch):
    """通用打桩: 抓 query 日期 + 关闸门 + 关取价 + 关限速 + 断网。"""
    calls = []

    def _fake_fetch(session, url, query_date_str):
        calls.append((url, query_date_str))
        return {}  # 空持股 → 后续取价/算差短路, 零副作用

    monkeypatch.setattr(hkq, "_fetch_ccass_holdings", _fake_fetch)
    monkeypatch.setattr(hkq, "_latest_quarter_value", lambda *a, **k: None)
    monkeypatch.setattr(hkq, "_fetch_close_prices_db", lambda *a, **k: ({}, []))
    monkeypatch.setattr(hkq, "_fetch_close_prices_baostock", lambda *a, **k: {})
    monkeypatch.setattr(hkq, "_count_db_rows", lambda *a, **k: 0)
    monkeypatch.setattr(hkq, "_time", type("_T", (), {"sleep": staticmethod(lambda *a, **k: None)}))
    monkeypatch.setattr(hkq, "requests", _NoNetRequests)
    return calls


# ── a: 翻档日钳制(主路径)───────────────────────────────────────────────
def test_a_rollover_day_clamps_query_to_yesterday(monkeypatch):
    """today=2026-10-20(= 2026-09-30 季度末 + 20 天当天):
    2026-09-30 档请求日必须 = 2026/10/19(today-1), 2026-06-30 档仍 = 2026/07/20。"""
    _freeze_today(monkeypatch, "20261020")
    calls = _stub_module(monkeypatch)

    rows = hkq.fetch_north_fund_ccass_quarterly(n_quarters=2)

    qs = [c[1] for c in calls]
    _chk(len(calls) == 4, f"两档 × 沪深应 4 次抓取: {calls}")
    _chk(calls[0][0] == hkq.CCASS_URL_SH and calls[1][0] == hkq.CCASS_URL_SZ,
         f"沪深取数顺序/URL 异常: {[c[0] for c in calls]}")
    _chk(qs == ["2026/10/19", "2026/10/19", "2026/07/20", "2026/07/20"],
         f"翻档日查询日期钳制错: {qs}")
    _chk(all("2026/10/20" not in s for s in qs),
         f"翻档日仍发出「不早于当天」的日期(today 本身): {qs}")
    _chk(rows == [], f"空持股应无结果: {rows}")


# ── b: 常规日回归(不被误钳)─────────────────────────────────────────────
def test_b_normal_day_query_date_unchanged(monkeypatch):
    """today=2026-10-25(> q+20): 2026-09-30 档请求日逐位不变 = 2026/10/20(q+20)。"""
    _freeze_today(monkeypatch, "20261025")
    calls = _stub_module(monkeypatch)

    hkq.fetch_north_fund_ccass_quarterly(n_quarters=2)

    qs = [c[1] for c in calls]
    _chk(len(qs) == 4, f"两档 × 沪深应 4 次抓取: {qs}")
    _chk(qs == ["2026/10/20", "2026/10/20", "2026/07/20", "2026/07/20"],
         f"常规日查询日期被误钳: {qs}")


# ── c: 回填 CLI 同款 clamp(参数化, 防两路径口径分叉)────────────────────
@pytest.mark.parametrize("today,expect_first", [
    ("20261020", "2026/10/19"),  # 翻档日 → today-1
    ("20261025", "2026/10/20"),  # 常规日 → q+20
])
def test_c_backfill_cli_same_clamp(monkeypatch, today, expect_first):
    _freeze_today(monkeypatch, today)
    calls = _stub_module(monkeypatch)

    res = hkq.backfill_quarterly_close_prices(["20260930"])

    qs = [c[1] for c in calls]
    _chk(len(calls) == 2, f"回填单档 × 沪深应 2 次抓取: {qs}")
    _chk(qs == [expect_first, expect_first], f"回填 CLI 查询日期错: {qs}")
    _chk(len(res) == 1 and res[0]["date"] == "20260930", f"回填结果结构异常: {res}")


# ── d: 翻档日 ±1 天 邻域(隔天绿关: 冻结日平移不侧漏)────────────────────
@pytest.mark.parametrize("today,expect", [
    ("20261019", ["2026/07/20", "2026/07/20", "2026/04/20", "2026/04/20"]),  # 09-30 档尚未发布
    ("20261021", ["2026/10/20", "2026/10/20", "2026/07/20", "2026/07/20"]),  # today-1 == q+20
])
def test_d_rollover_neighbour_days(monkeypatch, today, expect):
    _freeze_today(monkeypatch, today)
    calls = _stub_module(monkeypatch)

    hkq.fetch_north_fund_ccass_quarterly(n_quarters=2)

    qs = [c[1] for c in calls]
    _chk(qs == expect, f"翻档日邻域({today})查询日期错: {qs}")
    _chk(all(s <= today[:4] + "/" + today[4:6] + "/" + str(int(today[6:]) - 1) for s in qs),
         f"邻域日仍发出 today 或更晚的日期: {qs}")


def test_zzz_assertion_floor():
    """收尾断言计数下限守卫(防 0 断言假绿, §18 L49)。"""
    assert _N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}"