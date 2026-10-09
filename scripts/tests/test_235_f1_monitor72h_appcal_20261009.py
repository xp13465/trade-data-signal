# -*- coding: utf-8 -*-
"""#235 F1 续: 交易日口径「单一事实源」+ monitor_72h.sh 同病根 4 处补齐(2026-10-09 复审返工)。

本次(复审后)覆盖 monitor_72h.sh 的 4 处「自然日/周几算术」时效点:
  ① stale_alert_date  —— 纯自然日 >3  → 共用 _trading_age(交易日口径)
  ② S5 alert 白名单    —— 依赖 ALERT_EXPECTED_DATE(周几算术) → 改走 app.calendar.last_trading_day
  ③ S8 notifications  白名单 —— 依赖 LAST_TRADING_DAY(周几算术)   → 同上
  ④ S2 intraday 白名单 —— 依赖 LAST_TRADING_DAY(周几算术)         → 同上
  (②③④ 同病根为 LAST_TRADING_DAY/ALERT_EXPECTED_DATE 的「周几算术」, 根因修复=改其计算,
   单点根治而非逐文件打补丁; 该变量另有 S1/S6/overview 消费者, 一并受益。)

覆盖:
  A) app.calendar.lag_trading_days 数值表(与设计表 §4.3 逐位一致) + 解析失败 None + 两道护栏
  B) 静态锁: heredoc 合法; _trading_age/ad_line 仍用 lag_trading_days + >3 + 文案「交易日」
  B3) 行为实测(替换旧的「子串假绿」): 提取 LAST_TRADING_DAY/ALERT_EXPECTED_DATE 计算片断 exec,
      对 长假工作日/周末/交易日盘后/交易日盘前/长假后首个交易日盘前 逐案核对; 并证明
      S2/S5/S8 白名单所用变量确由 app.calendar 计算(长假工作日不再误判「今日=交易日」)
  C) 行为: 提取纯函数 _trading_age 受控命名空间实测 —— 长假后首日 lag≤3 不误报 / 真过期 lag>3 仍报
  D) 降级不静默: app.calendar 口径不可用 → _trading_age / _last_trading_day_safe 回退自然日·周几算术

零外发(§18 L48): 仅 exec 两个纯函数 + 一段纯计算片断(不跑业务脚本主体, 不触 curl/notify),
ZeroOutboundTrap 兜底证明无外发。§18 L50: 不 source/exec 业务脚本, 只提取纯函数/纯计算源码。
跑法: python3 -m pytest -q scripts/tests/test_235_f1_monitor72h_appcal_20261009.py
"""
from __future__ import annotations

import ast
import re
import sys
from datetime import date, datetime, timedelta
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
    """sanity: app.calendar.lag_trading_days 与设计表逐位一致(各调用方共享的唯一实现)。"""
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


def test_B2_shared_trading_age_helper_and_adline():
    body = _heredoc_body()
    _chk("def _trading_age" in body, "应有共用 _trading_age 辅助函数")
    _chk("from app.calendar import lag_trading_days" in body, "应复用 app.calendar 单一事实源")
    _chk("_ad_age = _trading_age(_ad_last_date)" in body, "ad_line 块应改用共用交易日口径")
    _chk("_al_age = _trading_age(_al_date_str)" in body, "stale_alert_date 块应改用共用交易日口径")
    _chk("_ad_line_trading_age" not in body, "旧 ad_line 专用函数应已合并入 _trading_age")
    _chk(body.count("_trading_age(") >= 3, "_trading_age 应有 1 定义 + 2 调用点")
    _chk("> 3" in body and "_al_age > 3" in body, "阈值 >3 应保留(只换口径, 不动阈值)")
    _chk("_ad_age > 3" in body, "ad_line 判据阈值 >3 应保留")
    _chk("滞后{_al_age}交易日(>3交易日)" in body, "alert 文案应为「交易日」")
    _chk("滞后{_ad_age}交易日(>3交易日)" in body, "ad_line 文案应为「交易日」")
    _chk("_ad_dt" not in body, "旧 _ad_dt 变量应清除")
    _chk("_al_dt" not in body, "旧 _al_dt 自然日变量应清除")


def test_B3a_root_last_trading_day_via_appcal_static():
    """静态锁: LAST_TRADING_DAY/ALERT_EXPECTED_DATE 由 _last_trading_day_safe(app.calendar) 计算。"""
    body = _heredoc_body()
    _chk("def _last_trading_day_safe" in body, "应有 _last_trading_day_safe 包装")
    _chk("from app.calendar import last_trading_day" in body, "应走 app.calendar 交易日历(非自造假日表)")
    _chk("LAST_TRADING_DAY = _last_trading_day_safe(_td)" in body, "非交易日分支应走日历")
    _chk("LAST_TRADING_DAY = _last_trading_day_safe(_td - timedelta(days=1))" in body, "盘前分支应走上交易日")
    _chk("ALERT_EXPECTED_DATE = _last_trading_day_safe(_td - timedelta(days=1))" in body, "预期上一交易日应走日历")
    # S2/S5/S8 白名单仍引用这两个变量(行为由下面 B3b 实测其取值正确性)
    _chk("if TODAY not in _ca_compact and LAST_TRADING_DAY not in _ca_compact:" in body, "S2 白名单引用 LAST_TRADING_DAY")
    _chk("_al_date not in (TODAY, LAST_TRADING_DAY, _yesterday, ALERT_EXPECTED_DATE)" in body, "S5 白名单引用两变量")
    _chk("_ntf_online.get(\"date\") not in (TODAY, LAST_TRADING_DAY)" in body, "S8 白名单引用 LAST_TRADING_DAY")
    # 旧的周几算术硬编码应已从 LAST_TRADING_DAY 主体移除(仅保留在 _last_trading_day_safe 的降级分支里)
    _chk("_offset = 3 if _td.weekday() == 0 else 1" not in body, "旧周几算术(盘前 offset)应已换成日历")
    _chk("_prev_offset = 3 if _td.weekday() == 0 else 1" not in body, "旧周几算术(预期上一交易日)应已换成日历")


# ══════════════════════ B3b) 行为实测: 提取计算片断 exec ══════════════════════
_LAE_START = "_td = NOW.date()"
_LAE_END = "ALERT_EXPECTED_DATE = LAST_TRADING_DAY"


def _load_lae_slice() -> str:
    body = _heredoc_body()
    i = body.index(_LAE_START)
    j = body.index(_LAE_END) + len(_LAE_END)
    return body[i:j]


def _eval_lae(today_ymd: str, hm: str):
    """在受控命名空间 exec「最近交易日/预期上一交易日」纯计算片断, 返回 (LAST_TRADING_DAY, ALERT_EXPECTED_DATE)。

    片断用真实 app.calendar 计算; _is_today_trading 按真实日历注入(与 .sh L106 同源)。
    """
    seg = _load_lae_slice()
    y, mo, d = int(today_ymd[:4]), int(today_ymd[4:6]), int(today_ymd[6:])
    ns = {
        "NOW": datetime(y, mo, d, int(hm[:2]), int(hm[2:]), 0),
        "timedelta": timedelta,
        "sys": sys,
        "TODAY": today_ymd,
        "_is_today_trading": cal.is_trading_day(date(y, mo, d)),
    }
    exec(seg, ns)  # 纯计算(无 curl/notify/落库), ZeroOutboundTrap 兜底
    return ns["LAST_TRADING_DAY"], ns["ALERT_EXPECTED_DATE"]


@pytest.mark.parametrize("today_s,hm,exp_ltd,exp_aed,note", [
    ("20261006", "1810", "20260930", "20260930", "长假工作日(周二): 旧代码误判今日=交易日 → 现取最近交易日"),
    ("20261010", "1200", "20261009", "20261009", "周六: 最近交易日=周五 10-09"),
    ("20261009", "1200", "20261009", "20261008", "交易日盘后: LTD=今日; 19:00前 AED=上一交易日"),
    ("20261009", "0800", "20261008", "20261008", "交易日盘前: 上一交易日 10-08"),
    ("20261008", "0800", "20260930", "20260930", "长假后首个交易日盘前: 上一交易日应为 09-30(旧=10-07 假日)"),
    ("20261012", "0800", "20261009", "20261009", "周一盘前(跨周末): 上一交易日 10-09(旧=10-11 周日)"),
])
def test_B3b_last_trading_day_behavior(today_s, hm, exp_ltd, exp_aed, note):
    with ZeroOutboundTrap() as trap:
        ltd, aed = _eval_lae(today_s, hm)
    _chk(ltd == exp_ltd, f"{note}: LAST_TRADING_DAY 期望 {exp_ltd}, 实得 {ltd}")
    _chk(aed == exp_aed, f"{note}: ALERT_EXPECTED_DATE 期望 {exp_aed}, 实得 {aed}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_B3c_whitelist_behavior_on_long_holiday_workday():
    """生产实证复现(alert_state.json 2026-10-06 假 SEVERE): 长假工作日白名单应放行最近交易日数据。"""
    today_s, hm = "20261006", "1810"
    ltd, aed = _eval_lae(today_s, hm)
    data_date = "20260930"  # 长假前最后交易日数据(节假日无新数据)
    # S2/S8 白名单成员集合: {TODAY, LAST_TRADING_DAY}
    s2_s8_member = data_date in (today_s, ltd)
    # S5 白名单: {TODAY, LAST_TRADING_DAY, _yesterday, ALERT_EXPECTED_DATE}
    yesterday = (datetime(2026, 10, 6) - timedelta(days=1)).strftime("%Y%m%d")
    s5_member = data_date in (today_s, ltd, yesterday, aed)
    _chk(s2_s8_member, f"S2/S8 白名单应放行 {data_date}(TODAY={today_s}/LTD={ltd})")
    _chk(s5_member, f"S5 白名单应放行 {data_date}(AED={aed})")
    _chk(ltd != today_s, "长假工作日 LAST_TRADING_DAY 不得等于今日(旧周几算术误判的病灶)")


# ══════════════════════ C) 提取纯函数 _trading_age 行为实测 ══════════════════════
def _load_trading_age():
    body = _heredoc_body()
    tree = ast.parse(body)
    seg = None
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_trading_age":
            seg = ast.get_source_segment(body, n)
    assert seg, "未提取到 _trading_age"
    return seg


def _make_fn(today_ymd: str):
    seg = _load_trading_age()
    ns = {"datetime": datetime, "sys": sys,
          "NOW": datetime(int(today_ymd[:4]), int(today_ymd[4:6]), int(today_ymd[6:]), 12, 0, 0)}
    exec(seg, ns)  # 只 exec 一个纯函数(无 curl/notify/落库), ZeroOutboundTrap 兜底
    return ns["_trading_age"]


@pytest.mark.parametrize("today_s,date_s,exp_lag,exp_alert", [
    ("20261008", "20260930", 1, False),   # 长假后首个交易日 → lag1 ≤3 → 不误报(判据 A)
    ("20261008", "20261008", 0, False),   # 当日
    ("20261009", "20260930", 2, False),   # 首日后次日
    ("20261010", "20260930", 2, False),   # 周末 today
    ("20261013", "20260930", 4, True),    # lag4 >3 → 报(WARN 首现档)
    ("20261019", "20260930", 8, True),    # 真过期 → lag8 >3 → 仍报(判据 B)
])
def test_C1_trading_age_behavior(today_s, date_s, exp_lag, exp_alert):
    """行为实测: 长假后首日不误报 + 真过期仍报 + 边界(阈值判定 =原 >3)。_trading_age 供 stale_alert/ad_line 共用。"""
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
    """降级不静默: app.calendar 口径不可用(调用抛)→ _trading_age 回退自然日。"""
    seg = _load_trading_age()
    ns = {"datetime": datetime, "sys": sys, "NOW": datetime(2026, 10, 19, 12, 0, 0)}
    exec(seg, ns)

    def _boom(*a, **k):
        raise RuntimeError("simulated calendar down")

    monkeypatch.setattr(cal, "lag_trading_days", _boom)
    got = ns["_trading_age"]("20260930")
    _chk(got == (date(2026, 10, 19) - date(2026, 9, 30)).days, f"口径不可用应回退自然日 19, 实得 {got}")


# ══════════════════════ D) 降级不静默: _last_trading_day_safe fallback ══════════════════════
def _load_ltd_safe():
    body = _heredoc_body()
    tree = ast.parse(body)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "_last_trading_day_safe":
            return ast.get_source_segment(body, n)
    raise AssertionError("未提取到 _last_trading_day_safe")


def test_D1_last_trading_day_safe_fallback(monkeypatch):
    """app.calendar 不可用 → 回退周几算术(不静默), 工作日降级为「今日」(保守=更严, 不放松)。"""
    ns = {"timedelta": timedelta, "sys": sys}
    exec(_load_ltd_safe(), ns)

    def _boom(*a, **k):
        raise RuntimeError("simulated calendar down")

    monkeypatch.setattr(cal, "last_trading_day", _boom)
    fn = ns["_last_trading_day_safe"]
    _chk(fn(date(2026, 10, 10)) == "20261009", "周六降级应取周五")
    _chk(fn(date(2026, 10, 11)) == "20261009", "周日降级应取周五")
    _chk(fn(date(2026, 10, 6)) == "20261006", "工作日降级取今日(保守更严, 非静默跳过)")
    monkeypatch.undo()
    _chk(fn(date(2026, 10, 6)) == "20260930", "日历可用时长假工作日应取最近交易日 09-30")


def test_99_min_assertions():
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")