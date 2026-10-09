# -*- coding: utf-8 -*-
"""#235 F1 续: 交易日口径「单一事实源」+ monitor_72h.sh ad_line 同病根第三处(2026-10-09)。

本次两件事:
  ① 口径权威实现上移到 app/calendar.lag_trading_days(单一事实源),
     check_data_integrity._lag_trading_days 与 monitor_72h.sh 均调用它(防两份实现漂移)。
  ② monitor_72h.sh L772 ad_line「最后日期滞后」由纯自然日 >3 改交易日口径(同病根第三处):
     长假后首个交易日不再假 SEVERE; 真过期仍报。

覆盖:
  A) app.calendar.lag_trading_days 数值表(与设计表 §4.3 逐位一致) + 解析失败 None + 两道护栏
  B) 静态锁: monitor_72h.sh 的 python heredoc 合法 + ad_line 块改用 lag_trading_days
     + 判据 >3 保留 + 文案「交易日」+ 已无纯自然日判据
  C) 行为: 从 heredoc 提取纯函数 _ad_line_trading_age 在受控命名空间实测
     —— 长假后首日 lag≤3 不误报 / 真过期 lag>3 仍报 / 边界

零外发(§18 L48): 全程仅 exec 一个纯函数(不跑业务脚本主体, 不触 curl/notify),
ZeroOutboundTrap 兜底证明无外发。§18 L50: 不 source/exec 业务脚本, 只提取纯函数源码。
跑法: python3 -m pytest -q scripts/tests/test_235_f1_monitor72h_appcal_20261009.py
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

REPO = Path(__file__).absolute().parent.parent.parent
sys.path.insert(0, str(REPO))
import app.calendar as cal  # noqa: E402

_MONITOR = REPO / "scripts" / "monitor_72h.sh"

_MIN_ASSERTIONS = 30
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── 设计表 §4.3(与 check_data_integrity 测试同一张表, 保证两处口径逐位一致) ──
_TABLE = [
    ("20260930", "20261008", 1), ("20260930", "20260930", 0), ("20261008", "20261008", 0),
    ("20261008", "20261009", 1), ("20260930", "20261009", 2), ("20260930", "20261012", 3),
    ("20260930", "20261013", 4), ("20261009", "20261013", 2), ("20260930", "20261014", 5),
    ("20260930", "20261016", 7), ("20260930", "20261019", 8), ("20261019", "20261008", 0),
    ("20261007", "20261008", 1), ("20261005", "20261008", 1), ("20260930", "20261010", 2),
]


def _d(ymd: str) -> date:
    return date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))


@pytest.mark.parametrize("date_s,today_s,exp", _TABLE)
def test_A1_appcal_lag_numeric_table(date_s, today_s, exp):
    """sanity: app.calendar.lag_trading_days 与设计表逐位一致(两调用方共享的唯一实现)。"""
    _chk(cal.lag_trading_days(date_s, today=_d(today_s)) == exp,
         f"cal.lag({date_s}@{today_s}) 期望 {exp}, 实得 {cal.lag_trading_days(date_s, today=_d(today_s))}")


@pytest.mark.parametrize("bad", ["", "  ", "2026-10-08", "abcdefgh", None, "2026100"])
def test_A2_appcal_parse_failure_none(bad):
    _chk(cal.lag_trading_days(bad, today=_d("20261009")) is None, f"非法 {bad!r} 应 None")


def test_A3_appcal_guard_calendar_not_covering_today():
    """护栏①: today 远在真实日历尾部之后 → 回退自然日(20260930→20300615 = 自然 14)。"""
    got = cal.lag_trading_days("20260930", today=_d("20300615"))
    _chk(got == (date(2030, 6, 15) - date(2026, 9, 30)).days, f"护栏①应回退自然日, 实得 {got}")
    _chk(got != 0, "护栏①必须挡住「未覆盖 → lag 恒 0」静默放松")


def test_A4_appcal_guard_exception_fallback():
    """护栏②: 日历计算抛异常 → 回退自然日 fail-safe。"""
    orig = cal.trading_days_between

    def _boom(a, b):
        raise RuntimeError("simulated")

    cal.trading_days_between = _boom
    try:
        got = cal.lag_trading_days("20260930", today=_d("20261019"))
    finally:
        cal.trading_days_between = orig
    _chk(got == (date(2026, 10, 19) - date(2026, 9, 30)).days, f"护栏②应 fail-safe 回退, 实得 {got}")


# ══════════════════════ B) monitor_72h.sh 静态锁 ══════════════════════
def _heredoc_body() -> str:
    src = _MONITOR.read_text(encoding="utf-8")
    m = re.search(r"<<'PYEOF'[^\n]*\n(.*?)\nPYEOF", src, re.S)
    assert m, "monitor_72h.sh 的 PYEOF heredoc 未找到"
    return m.group(1)


def test_B1_heredoc_is_valid_python():
    ast.parse(_heredoc_body())  # 不抛即合法


def test_B2_adline_block_uses_trading_day_caliber():
    body = _heredoc_body()
    _chk("def _ad_line_trading_age" in body, "应有 _ad_line_trading_age 辅助函数")
    _chk("from app.calendar import lag_trading_days" in body, "应复用 app.calendar 单一事实源")
    _chk("_ad_age = _ad_line_trading_age(_ad_last_date)" in body, "ad_line 块应改用交易日口径")
    _chk("_ad_age > 3" in body, "判据阈值 >3 应保留(只换口径, 不动阈值)")
    _chk("滞后{_ad_age}交易日(>3交易日)" in body, "文案应为「交易日」")
    _chk("(NOW.date() - _ad_dt.date()).days" not in body, "已无纯自然日判据(旧代码应清除)")
    _chk("_ad_dt" not in body, "旧 _ad_dt 变量应清除")


def test_B3_no_other_natural_day_freshness_left():
    """§23.3: monitor_72h 内 ad_line 是唯一纯自然日时效点(alert/overview 已交易日感知)。"""
    body = _heredoc_body()
    # alert.json 时效检查用 LAST_TRADING_DAY/ALERT_EXPECTED_DATE 白名单(交易日感知, 无「天」阈值判据)
    _chk("_al_date_str in (LAST_TRADING_DAY, ALERT_EXPECTED_DATE)" in body, "alert 走交易日白名单")
    _chk("_ov_date not in (TODAY, LAST_TRADING_DAY)" in body, "overview 走交易日白名单")


# ══════════════════════ C) 提取纯函数行为实测 ══════════════════════
def _load_ad_line_age():
    body = _heredoc_body()
    tree = ast.parse(body)
    seg = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_ad_line_trading_age":
            seg = ast.get_source_segment(body, n)
    assert seg, "未提取到 _ad_line_trading_age"
    return seg


def _make_fn(today_ymd: str):
    seg = _load_ad_line_age()
    ns = {"datetime": datetime, "sys": sys, "NOW": datetime(int(today_ymd[:4]), int(today_ymd[4:6]), int(today_ymd[6:]), 12, 0, 0)}
    exec(seg, ns)  # 只 exec 一个纯函数(无 curl/notify/落库), ZeroOutboundTrap 兜底
    return ns["_ad_line_trading_age"]


@pytest.mark.parametrize("today_s,date_s,exp_lag,exp_alert", [
    ("20261008", "20260930", 1, False),   # 长假后首个交易日 → lag1 ≤3 → 不误报(判据 A)
    ("20261008", "20261008", 0, False),   # 当日
    ("20261009", "20260930", 2, False),   # 首日后次日
    ("20261010", "20260930", 2, False),   # 周末 today
    ("20261013", "20260930", 4, True),    # lag4 >3 → 报(WARN 首现档)
    ("20261019", "20260930", 8, True),    # 真过期 → lag8 >3 → 仍报(判据 B)
])
def test_C1_adline_behavior(today_s, date_s, exp_lag, exp_alert):
    """行为实测: 长假后首日不误报 + 真过期仍报 + 边界(阈值判定 =原 >3)。"""
    with ZeroOutboundTrap() as trap:
        fn = _make_fn(today_s)
        lag = fn(date_s)
        alerted = bool(lag is not None and lag > 3)  # 与 .sh 内 elif 判据同构
    _chk(lag == exp_lag, f"今日{today_s} 数据日{date_s}: lag 期望 {exp_lag}, 实得 {lag}")
    _chk(alerted is exp_alert, f"今日{today_s} 数据日{date_s}: 告警判定期望 {exp_alert}, 实得 {alerted}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_C2_fallback_on_bad_date():
    """非法日期 → None(不告警, 与原 ValueError 分支同效果)。"""
    fn = _make_fn("20261009")
    _chk(fn("not-a-date") is None, "非法日期应返回 None")
    _chk(fn("") is None, "空串应返回 None")


def test_C3_appcal_unavailable_falls_back_natural(monkeypatch):
    """app.calendar 口径不可用(调用抛)→ 回退自然日, 不静默跳过(旧口径 fail-safe)。"""
    seg = _load_ad_line_age()
    ns = {"datetime": datetime, "sys": sys, "NOW": datetime(2026, 10, 19, 12, 0, 0)}
    exec(seg, ns)

    def _boom(*a, **k):
        raise RuntimeError("simulated calendar down")

    monkeypatch.setattr(cal, "lag_trading_days", _boom)
    got = ns["_ad_line_trading_age"]("20260930")
    _chk(got == (date(2026, 10, 19) - date(2026, 9, 30)).days, f"口径不可用应回退自然日 19, 实得 {got}")


def test_99_min_assertions():
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")