# -*- coding: utf-8 -*-
"""#235 F1: 数据新鲜度校验「自然日 → 交易日」口径 —— pytest 自验(2026-10-09)。

对象: scripts/check_data_integrity.py 新增 helper `_lag_trading_days` + 8 处替换。
依据: docs/ops/235-f1-tradingday-caliber-design-20261009.md(已定稿)。

覆盖(对稿逐条):
  ① helper 数值表(稿 §4.3, 15 组 → 新 lag 逐个比对设计表 + 旧自然日对照)
  ② 护栏①: 日历未覆盖 today → 回退自然日(真实日历 2030 远期案例 + 打桩强制两法)
  ③ 护栏②: 任何异常 → 回退自然日 fail-safe
  ④ 契约: 解析失败 → None(与原 _days_ago 一致)
  ⑤ 判定矩阵(稿 §8.2): alert/notifications/ad_line/a_stock/accum_nav/trade_sim/s06(R2)
     的 OK/WARN/FAIL 档 —— 判据 A(长假后首日不误报) + 判据 B(真过期仍报)
  ⑥ s06 档间翻转(稿 §2.2): 自然日 7↔8 致 allow/deny 翻转, 改后稳定
  ⑦ §15 回归: 未改的 overview/fund_score 仍自然日口径; #188 ①b(s06 本地新鲜)兼容
  ⑧ 静态锁: 恰好 8 处 _lag_trading_days(落在 7 个函数, s06 占 2) + 2 处保留 _days_ago
     (落在 check_overview / check_fund_score)

零外发(§18 L48): 全程 monkeypatch `_fetch_r2_json`; R2 路径不触真实 urlopen(ZeroOutboundTrap 兜底)。
跑法: python3 -m pytest -q scripts/tests/test_235_f1_tradingday_caliber_20261009.py
"""
from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime as _real_dt
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_data_integrity as cdi  # noqa: E402

SCRIPTS = Path(__file__).absolute().parent.parent

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240/#241)
_MIN_ASSERTIONS = 60
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── 冻结 cdi.datetime.now() 到指定 today(YYYYMMDD), 其余行为透传真 datetime ──
def _freeze(monkeypatch, ymd: str):
    y, m, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:])

    class _FrozenDT:
        _now = _real_dt(y, m, d, 12, 0, 0)

        @staticmethod
        def strptime(s, fmt):
            return _real_dt.strptime(s, fmt)

        @staticmethod
        def fromtimestamp(ts):
            return _real_dt.fromtimestamp(ts)

        @classmethod
        def now(cls, tz=None):
            return cls._now

    monkeypatch.setattr(cdi, "datetime", _FrozenDT)


def _patch_r2(monkeypatch, payload):
    monkeypatch.setattr(cdi, "_fetch_r2_json", lambda rel, timeout=20: (payload, None))


# ══════════════════════ ① helper 数值表(稿 §4.3) ══════════════════════
# (date, today, 新 lag 期望, 旧自然日期望) —— 逐位照设计表, 含 15 组长假/边界/未来/周末
_TABLE = [
    ("20260930", "20261008", 1, 8),    # 长假后首日(6 项误报场景) → 改后 OK
    ("20260930", "20260930", 0, 0),    # 数据=今日
    ("20261008", "20261008", 0, 0),    # 稳态盘后
    ("20261008", "20261009", 1, 1),    # 盘前查昨日盘后数据
    ("20260930", "20261009", 2, 9),    # 首日后仍未更新
    ("20260930", "20261012", 3, 12),   # 周一
    ("20260930", "20261013", 4, 13),   # WARN 首现档(>3)
    ("20261009", "20261013", 2, 4),    # 相对滞后
    ("20260930", "20261014", 5, 14),   # alert/s06 WARN 首现档(>4)
    ("20260930", "20261016", 7, 16),   # 边界: 7 仍 WARN
    ("20260930", "20261019", 8, 19),   # FAIL 首现档(>7)
    ("20261019", "20261008", 0, -11),  # 未来日期 clamp 0
    ("20261007", "20261008", 1, 1),    # 假期日期按其后交易日计
    ("20261005", "20261008", 1, 3),    # 假期(旧口径 3 已近 WARN)
    ("20260930", "20261010", 2, 10),   # 周末 today 不误报
]


@pytest.mark.parametrize("date,today,exp_new,exp_old", _TABLE)
def test_01_helper_numeric_table(monkeypatch, date, today, exp_new, exp_old):
    """稿 §4.3: helper 新 lag 逐位等于设计表; 旧自然日对照同表(判别力=两口径确有差异)。"""
    _freeze(monkeypatch, today)
    _chk(cdi._lag_trading_days(date) == exp_new,
         f"lag({date}@{today}) 期望 {exp_new}, 实得 {cdi._lag_trading_days(date)}")
    _chk(cdi._days_ago(date) == exp_old,
         f"旧自然日({date}@{today}) 期望 {exp_old}, 实得 {cdi._days_ago(date)}")


# ══════════════════════ ④ 契约: 解析失败 → None ══════════════════════
@pytest.mark.parametrize("bad", ["", "  ", "2026-10-08", "abcdefgh", "2026/10/08", None, "2026100"])
def test_02_parse_failure_returns_none(monkeypatch, bad):
    """与原 _days_ago 契约一致: 非法/缺字段 → None(调用方按 None 分支处理, 不抛)。"""
    _freeze(monkeypatch, "20261009")
    _chk(cdi._lag_trading_days(bad) is None, f"非法输入 {bad!r} 应返回 None")


# ══════════════════════ ② 护栏①: 日历未覆盖 today → 回退自然日 ══════════════════════
def test_03_guard_calendar_not_covering_today_realistic(monkeypatch):
    """稿 §9.1 护栏①(真实日历): today 远在日历尾部之后 → 回退自然日, 防跨年静默放松。

    真实 trade_dates.txt 尾部约 20261231; today=20300615 远其后 → last_trading_day
    前找 15 天全非交易日 → 返回 today 自身 → is_trading_day=False → 回退。
    """
    _freeze(monkeypatch, "20300615")
    got = cdi._lag_trading_days("20300601")
    _chk(got == 14, f"未覆盖 today 应回退自然日 14, 实得 {got}")
    # 若不加护栏, 交易日口径会把 2027+ 日期恒判 False → 静默算成 0 —— 这里证明未被放松
    _chk(got != 0, "护栏必须挡住「未覆盖 → lag 恒 0」的静默放松")


def test_03b_guard_calendar_not_covering_today_forced(monkeypatch):
    """稿 §9.1 护栏①(打桩强制): 日历无法定位交易日(前找全非交易日)→ 回退自然日。"""
    import app.calendar as cal
    _freeze(monkeypatch, "20261019")
    monkeypatch.setattr(cal, "is_trading_day", lambda d=None: False)
    got = cdi._lag_trading_days("20260930")
    _chk(got == 19, f"日历不可定位 → 回退自然日 19, 实得 {got}")


# ══════════════════════ ③ 护栏②: 异常 → fail-safe 回退自然日 ══════════════════════
def test_04_guard_exception_falls_back_to_natural(monkeypatch):
    """稿 §4.2 护栏②: 日历计算抛异常 → 回退自然日(旧行为, 保守, 不崩)。"""
    import app.calendar as cal
    _freeze(monkeypatch, "20261019")

    def _boom(a, b):
        raise RuntimeError("simulated calendar failure")

    monkeypatch.setattr(cal, "trading_days_between", _boom)
    _chk(cdi._lag_trading_days("20260930") == 19, "异常应 fail-safe 回退自然日 19")


# ══════════════════════ ⑤ 判定矩阵(稿 §8.2) ══════════════════════
def _mkdir(tmp_path: Path) -> Path:
    dd = tmp_path / "static-site" / "data"
    dd.mkdir(parents=True, exist_ok=True)
    return dd


# today 20261008 是交易日, 20260930 为其前一交易日(长假首日场景)
@pytest.mark.parametrize("date,exp", [
    ("20261008", "ok"),    # lag 0
    ("20260930", "ok"),    # lag 1 —— 判据 A: 长假后首日不误报
])
def test_05a_alert_judgment(monkeypatch, date, exp):
    _freeze(monkeypatch, "20261008")
    _patch_r2(monkeypatch, {"date": date})
    _chk(cdi.check_alert(Path("/nonexistent")).status == exp, f"alert date={date} 期望 {exp}")


@pytest.mark.parametrize("today,date,exp", [
    ("20261014", "20260930", "warn"),  # lag 5 > 4 → WARN
    ("20261019", "20260930", "fail"),  # lag 8 > 7 → FAIL(判据 B)
])
def test_05b_alert_warn_fail(monkeypatch, today, date, exp):
    _freeze(monkeypatch, today)
    _patch_r2(monkeypatch, {"date": date})
    _chk(cdi.check_alert(Path("/nonexistent")).status == exp, f"alert {date}@{today} 期望 {exp}")


def test_05c_notifications_judgment(monkeypatch):
    _freeze(monkeypatch, "20261008")
    _patch_r2(monkeypatch, {"date": "20261008"})
    _chk(cdi.check_notifications(Path("/nonexistent")).status == "ok", "notifications 当日 OK")
    _freeze(monkeypatch, "20261009")
    _patch_r2(monkeypatch, {"date": "20260930"})  # lag 2 > 1 → WARN
    _chk(cdi.check_notifications(Path("/nonexistent")).status == "warn", "notifications lag2 WARN")
    _freeze(monkeypatch, "20261019")
    _patch_r2(monkeypatch, {"date": "20260930"})  # lag 8 > 7 → FAIL
    _chk(cdi.check_notifications(Path("/nonexistent")).status == "fail", "notifications lag8 FAIL")


def _write_ad_line(dd: Path, date: str):
    (dd / "ad_line.json").write_text(
        json.dumps({"data": [{"date": date, "v": 1}]}), encoding="utf-8")


@pytest.mark.parametrize("today,date,exp", [
    ("20261008", "20261008", "ok"),     # lag 0
    ("20261008", "20260930", "ok"),     # lag 1 —— 判据 A
    ("20261013", "20260930", "warn"),   # lag 4 > 3 → WARN
    ("20261019", "20260930", "fail"),   # lag 8 > 7 → FAIL —— 判据 B
])
def test_05d_ad_line_judgment(monkeypatch, tmp_path, today, date, exp):
    _freeze(monkeypatch, today)
    dd = _mkdir(tmp_path)
    _write_ad_line(dd, date)
    _chk(cdi.check_ad_line(dd).status == exp, f"ad_line {date}@{today} 期望 {exp}")


def _write_a_stock(dd: Path, date: str):
    (dd / "a-stock-1y.json").write_text(json.dumps({
        "metrics": {"a_amount": {"data": [{"date": date, "v": 1}]}},
        "indices": {},
    }), encoding="utf-8")


@pytest.mark.parametrize("today,date,exp", [
    ("20261008", "20260930", "ok"),     # lag 1 —— 判据 A
    ("20261013", "20260930", "warn"),   # lag 4 → WARN
    ("20261019", "20260930", "fail"),   # lag 8 → FAIL
])
def test_05e_a_stock_judgment(monkeypatch, tmp_path, today, date, exp):
    _freeze(monkeypatch, today)
    dd = _mkdir(tmp_path)
    _write_a_stock(dd, date)
    _chk(cdi.check_a_stock(dd).status == exp, f"a_stock {date}@{today} 期望 {exp}")


def _write_accum_nav_map(dd: Path, date: str):
    (dd / "accum_nav_map.json").write_text(
        json.dumps({"513400": {date: 1.23}}), encoding="utf-8")


@pytest.mark.parametrize("today,date,exp", [
    ("20261008", "20260930", "ok"),     # lag 1 —— 判据 A
    ("20261013", "20260930", "warn"),   # lag 4 → WARN
    ("20261019", "20260930", "fail"),   # lag 8 → FAIL
])
def test_05f_accum_nav_map_judgment(monkeypatch, tmp_path, today, date, exp):
    _freeze(monkeypatch, today)
    dd = _mkdir(tmp_path)
    _write_accum_nav_map(dd, date)
    _chk(cdi.check_accum_nav_map_fresh(dd).status == exp, f"accum_nav {date}@{today} 期望 {exp}")


def _write_trade_sim(dd: Path, mtime_ymd: str):
    p = dd / "trade_sim_indices.json"
    p.write_text(json.dumps(["sh", "hs300"]), encoding="utf-8")
    y, m, d = int(mtime_ymd[:4]), int(mtime_ymd[4:6]), int(mtime_ymd[6:])
    ts = _real_dt(y, m, d, 12, 0, 0).timestamp()
    os.utime(p, (ts, ts))
    return p


@pytest.mark.parametrize("today,mdate,exp", [
    ("20261008", "20260930", "ok"),     # mtime 交易日口径 lag 1 —— 判据 A(旧自然日 8 会 FAIL)
    ("20261013", "20260930", "warn"),   # lag 4 → WARN
    ("20261019", "20260930", "fail"),   # lag 8 → FAIL
])
def test_05g_trade_sim_mtime_judgment(monkeypatch, tmp_path, today, mdate, exp):
    _freeze(monkeypatch, today)
    dd = _mkdir(tmp_path)
    _write_trade_sim(dd, mdate)
    _chk(cdi.check_trade_sim_indices(dd).status == exp, f"trade_sim {mdate}@{today} 期望 {exp}")


def _r2_s06(cov_end: str):
    return {
        "daily": [{"date": cov_end}], "threshold": 1, "confirm_days": 1, "min_hold_days": 1,
        "on_base": 1, "off_base": 2, "coverage_start": "20250101", "coverage_end": cov_end,
    }


# s06 本地无快照 → 走 R2 路径(② 降级)
@pytest.mark.parametrize("today,date,exp", [
    ("20261008", "20260930", "ok"),     # R2 coverage_end lag 1 —— 判据 A
    ("20261014", "20260930", "warn"),   # lag 5 > 4 → WARN
    ("20261019", "20260930", "fail"),   # lag 8 > 7 → FAIL —— 判据 B
])
def test_05h_s06_r2_judgment(monkeypatch, tmp_path, today, date, exp):
    _freeze(monkeypatch, today)
    dd = _mkdir(tmp_path)  # 无 kelly_mode_s06_state.json → local_fresh=False → ② R2
    _patch_r2(monkeypatch, _r2_s06(date))
    _chk(cdi.check_s06_state_snapshot(dd).status == exp, f"s06 R2 {date}@{today} 期望 {exp}")


# ══════════════════════ ⑥ s06 档间翻转(稿 §2.2) ══════════════════════
def test_06_s06_local_fresh_flip_fixed(monkeypatch, tmp_path):
    """稿 §2.2: 旧口径自然日 7↔8 使 s06 本地门槛 allow/deny 翻转; 改交易日口径后稳定。

    today=20261008, 本地快照 coverage_end=20260930:
      旧自然日=8 > STALE_DAYS_FAIL(7) → local_fresh=False → 降级 R2 路径(易 FAIL);
      新交易日=1 ≤ 7 → local_fresh=True → 走 ① 本地互证(正确: 验「将上传的快照」)。
    """
    _freeze(monkeypatch, "20261008")
    _chk(cdi._days_ago("20260930") == 8 and cdi._days_ago("20260930") > cdi.STALE_DAYS_FAIL,
         "旧口径应 8 > 7(=翻转诱因)")
    _chk(cdi._lag_trading_days("20260930") == 1 and cdi._lag_trading_days("20260930") <= cdi.STALE_DAYS_FAIL,
         "新口径应 1 ≤ 7(local_fresh 稳定为真)")

    dd = _mkdir(tmp_path)
    (dd / "kelly_mode_s06_state.json").write_text(json.dumps({
        "coverage_start": "20250101", "coverage_end": "20260930", "daily": [1],
        "on_base": 1, "off_base": 2,
    }), encoding="utf-8")

    class _P:
        returncode, stdout, stderr = 0, "✓ A1-A6 全部通过\n", ""

    monkeypatch.setattr(cdi.subprocess, "run", lambda *a, **k: _P())
    _patch_r2(monkeypatch, _r2_s06("20260930"))  # R2 副本一致 → ①b 不 WARN
    r = cdi.check_s06_state_snapshot(dd)
    _chk(r.status == "ok", f"改后应走 ① 本地互证 OK, 实得 {r.status}: {r.msg}")


# ══════════════════════ ⑦ §15 回归 ══════════════════════
def test_07a_overview_still_natural_day(monkeypatch, tmp_path):
    """§15: 未改的 check_overview 仍自然日口径(稿 §6: 每日驱动含假期, 不该改)。"""
    _freeze(monkeypatch, "20261015")
    dd = _mkdir(tmp_path)
    (dd / "overview.json").write_text(json.dumps({"date": "20261013"}), encoding="utf-8")
    _chk(cdi.check_overview(dd).status == "ok", "overview 自然日 2 天 → OK")
    (dd / "overview.json").write_text(json.dumps({"date": "20261007"}), encoding="utf-8")
    _chk(cdi.check_overview(dd).status == "fail", "overview 自然日 8 天 → FAIL(口径未变)")


def test_07b_fund_score_still_natural_day(monkeypatch, tmp_path):
    """§15: 未改的 check_fund_score 仍自然日口径(稿 §6)。"""
    _freeze(monkeypatch, "20261015")
    dd = _mkdir(tmp_path)
    (dd / "fund_score.json").write_text(
        json.dumps({"date": "20261013", "count": 2000}), encoding="utf-8")
    _chk(cdi.check_fund_score(dd).status == "ok", "fund_score 自然日 2 天 → OK")
    (dd / "fund_score.json").write_text(
        json.dumps({"date": "20261007", "count": 2000}), encoding="utf-8")
    _chk(cdi.check_fund_score(dd).status == "fail", "fund_score 自然日 8 天 → FAIL(口径未变)")


def test_07c_188_local_fresh_still_ok(monkeypatch, tmp_path):
    """§15 / 稿 §7.4: #188 ①b 兼容 —— coverage_end=today 时 lag=0 → 走 ① 本地互证 → OK。"""
    _freeze(monkeypatch, "20261008")
    dd = _mkdir(tmp_path)
    (dd / "kelly_mode_s06_state.json").write_text(json.dumps({
        "coverage_start": "20250101", "coverage_end": "20261008", "daily": [1],
        "on_base": 1, "off_base": 2,
    }), encoding="utf-8")

    class _P:
        returncode, stdout, stderr = 0, "✓ A1-A6 全部通过\n", ""

    monkeypatch.setattr(cdi.subprocess, "run", lambda *a, **k: _P())
    _patch_r2(monkeypatch, _r2_s06("20261008"))
    _chk(cdi.check_s06_state_snapshot(dd).status == "ok", "coverage_end=today → OK(#188 兼容)")

    # R2 落后 → 只 WARN(不 FAIL, 防 deploy 死锁, 稿 §7.4)
    _patch_r2(monkeypatch, _r2_s06("20260101"))
    _chk(cdi.check_s06_state_snapshot(dd).status == "warn", "R2 落后 → WARN(#188 原语义)")


# ══════════════════════ ⑧ 静态锁(8 处替换 / 2 处保留) ══════════════════════
def _calls_by_func(src: str) -> dict[str, dict[str, int]]:
    tree = ast.parse(src)
    out: dict[str, dict[str, int]] = {}

    def walk(node, func):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(ch, ch.name)
            else:
                if isinstance(ch, ast.Call) and isinstance(ch.func, ast.Name) \
                        and ch.func.id in ("_days_ago", "_lag_trading_days"):
                    out.setdefault(func, {}).setdefault(ch.func.id, 0)
                    out[func][ch.func.id] += 1
                walk(ch, func)

    walk(tree, "<module>")
    return out


def test_08a_exactly_eight_lag_calls_in_expected_funcs():
    src = (SCRIPTS / "check_data_integrity.py").read_text(encoding="utf-8")
    calls = _calls_by_func(src)
    lag_funcs = {f: c["_lag_trading_days"] for f, c in calls.items() if "_lag_trading_days" in c}
    _chk(lag_funcs == {
        "check_alert": 1, "check_notifications": 1, "check_ad_line": 1, "check_a_stock": 1,
        "check_trade_sim_indices": 1, "check_accum_nav_map_fresh": 1,
        "check_s06_state_snapshot": 2,
    }, f"8 处替换应落在 7 个预期函数, 实得 {lag_funcs}")
    _chk(sum(lag_funcs.values()) == 8, f"应恰好 8 处 _lag_trading_days, 实得 {sum(lag_funcs.values())}")


def test_08b_days_ago_kept_only_for_overview_and_fund_score():
    src = (SCRIPTS / "check_data_integrity.py").read_text(encoding="utf-8")
    calls = _calls_by_func(src)
    old_funcs = {f: c["_days_ago"] for f, c in calls.items() if "_days_ago" in c}
    _chk(old_funcs == {"check_overview": 1, "check_fund_score": 1},
         f"_days_ago 应仅余 check_overview/fund_score 各 1 处, 实得 {old_funcs}")


def test_08c_no_threshold_or_message_changed():
    """静态锁: 8 处替换只换口径来源, 阈值常量与 FAIL/WARN 判据未动。"""
    src = (SCRIPTS / "check_data_integrity.py").read_text(encoding="utf-8")
    _chk("STALE_DAYS_WARN = 3" in src and "STALE_DAYS_FAIL = 7" in src, "阈值常量未变")
    for fn in ("check_alert", "check_notifications", "check_ad_line", "check_a_stock",
               "check_trade_sim_indices", "check_accum_nav_map_fresh", "check_s06_state_snapshot"):
        body = _func_src(src, fn)
        _chk("_lag_trading_days(" in body, f"{fn} 应改用交易日口径")
    _chk("STALE_DAYS_WARN + 1" in _func_src(src, "check_alert"), "alert 跨日容差判据保留")
    _chk("days > 1" in _func_src(src, "check_notifications"), "notifications 阈值判据保留")


def _func_src(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


# ══════════════════════ ⓪ 零外发自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_proves_r2_patch(monkeypatch):
    """打桩生效自证: R2 拉取被 monkeypatch ⇒ 真出口 urlopen 从未被触达(hits==[])。"""
    _freeze(monkeypatch, "20261008")
    _patch_r2(monkeypatch, {"date": "20261008"})
    with ZeroOutboundTrap() as trap:
        _chk(cdi.check_alert(Path("/nonexistent")).status == "ok", "打桩下 alert OK")
        _chk(cdi.check_notifications(Path("/nonexistent")).status == "ok", "打桩下 notifications OK")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_99_min_assertions():
    """§18 L49: 断言计数下限, 防收集/执行异常致假绿。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")