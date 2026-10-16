# -*- coding: utf-8 -*-
"""#257 D1: fund_index_daily 新鲜度 checker —— pytest 自验(2026-10-17)。

对象: scripts/check_data_integrity.py 新增 `check_fund_index_daily` + run_all_checks 编排
      + scripts/tests/test_235_f1_tradingday_caliber_20261009.py 静态锁同步(8→9 处)。
依据: 拍板包 /tmp/decide-pack-report.md 第 4 节 #257(现状: 最新 20260929, 参照交易日 20261013,
      停更 ~10 交易日 + 零告警覆盖)。

覆盖(对任务书验收逐条):
  ① 正例: 以当前真实停更态触发告警 —— 20260929@20261013(lag 5, WARN) / 20260929@20261017(lag 8, FAIL)
  ② 反例: 最新=参照交易日当日/T-1 → OK(不触发)
  ③ 阈值边界(刚好卡线): lag 3 OK / 4 WARN / 7 WARN / 8 FAIL
  ④ 环境缺库/空表/坏格式 三分支
  ⑤ 判别力: 改坏阈值 / 换回自然日口径 → 判定翻转(证明测试非空转)

零外发(§18 L48): 本 checker 只读本地 sqlite, 全程 monkeypatch `_find_public_fund_db` 指向临时库,
  真出口 urlopen 从未被触达(ZeroOutboundTrap 兜底); 不触真实 public_fund.db。
跑法: python3 -m pytest -q scripts/tests/test_257_fund_index_daily_checker_20261017.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime as _real_dt
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_data_integrity as cdi  # noqa: E402

SCRIPTS = Path(__file__).absolute().parent.parent

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240/#241/#235)
_MIN_ASSERTIONS = 30
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── 冻结 cdi.datetime.now() 到指定 today(其余行为透传真 datetime) ──
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


def _make_db(tmp_path: Path, latest: str, index_ids=("hs300", "csi500", "gem")) -> Path:
    """构造临时 public_fund.db(只含 fund_index_daily 表 + 三指数各 1 行 latest)。"""
    db = tmp_path / "public_fund.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE fund_index_daily (date TEXT NOT NULL, index_id TEXT NOT NULL, "
        "close REAL, pct_change REAL, PRIMARY KEY (date, index_id))"
    )
    for idx in index_ids:
        conn.execute(
            "INSERT INTO fund_index_daily(date, index_id, close, pct_change) VALUES (?,?,?,?)",
            (latest, idx, 3500.0, 0.5),
        )
    conn.commit()
    conn.close()
    return db


def _patch_db(monkeypatch, db: Path | None):
    monkeypatch.setattr(cdi, "_find_public_fund_db", lambda: db)


# ══════════════════════ ① 正例 + ② 反例 + ③ 阈值边界 ══════════════════════
# (today, latest, 期望 lag, 期望 status) —— lag 值经 cdi._lag_trading_days 自校验(下方 assert)
# 日期对取自 test_235 已核过的交易日历数值表(长假/边界同源), 避免脆弱的日期算术。
_CASES = [
    # ② 反例: 当日 / T-1 → OK
    ("20261008", "20261008", 0, "ok"),    # 当日盘后
    ("20261009", "20261008", 1, "ok"),    # 盘前查昨日盘后值
    ("20261008", "20260930", 1, "ok"),    # 长假后首个交易日(判据 A: 自然日 8 会误报, 交易日口径 OK)
    # ③ 阈值边界: 3 不触发 / 4 触发 WARN / 7 仍 WARN / 8 触发 FAIL
    ("20261012", "20260930", 3, "ok"),    # 刚好卡 WARN 线(不 > 3)
    ("20261013", "20260930", 4, "warn"),  # 越过 WARN(> 3)
    ("20261016", "20260930", 7, "warn"),  # 刚好卡 FAIL 线(不 > 7, 仍 WARN)
    ("20261019", "20260930", 8, "fail"),  # 越过 FAIL(> 7)
    # ① 正例: 当前真实停更态(20260929)
    ("20261013", "20260929", 5, "warn"),  # 拍板包参照交易日 20261013 → lag 5 → 告警
    ("20261017", "20260929", 8, "fail"),  # 今日(2026-10-17) → lag 8 → 停更故障
]


@pytest.mark.parametrize("today,latest,exp_lag,exp_status", _CASES)
def test_01_verdict_matrix(monkeypatch, tmp_path, today, latest, exp_lag, exp_status):
    _freeze(monkeypatch, today)
    _patch_db(monkeypatch, _make_db(tmp_path, latest))
    # 自校验 fixture: 该 latest@today 的交易日滞后 = 期望(防 fixture 悄悄漂移)
    got_lag = cdi._lag_trading_days(latest)
    _chk(got_lag == exp_lag, f"fixture lag({latest}@{today}) 期望 {exp_lag}, 实得 {got_lag}")
    r = cdi.check_fund_index_daily()
    _chk(r.status == exp_status, f"fund_index_daily {latest}@{today} 期望 {exp_status}, 实得 {r.status}: {r.msg}")


# ══════════════════════ ④ 环境缺库 / 空表 / 坏格式 ══════════════════════
def test_02_db_not_found_is_warn(monkeypatch):
    """库找不到 = WARN(与 a_fund_north_quarterly/fapi_mutex 同款: 环境缺库不误判数据故障)。"""
    _freeze(monkeypatch, "20261017")
    _patch_db(monkeypatch, None)
    r = cdi.check_fund_index_daily()
    _chk(r.status == "warn", f"缺库应 WARN, 实得 {r.status}: {r.msg}")


def test_03_empty_table_is_fail(monkeypatch, tmp_path):
    """表存在但无行 = FAIL(反推算法基准缺失)。"""
    _freeze(monkeypatch, "20261017")
    db = tmp_path / "public_fund.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE fund_index_daily (date TEXT, index_id TEXT, close REAL, pct_change REAL)")
    conn.commit()
    conn.close()
    _patch_db(monkeypatch, db)
    r = cdi.check_fund_index_daily()
    _chk(r.status == "fail", f"空表应 FAIL, 实得 {r.status}: {r.msg}")


def test_04_bad_date_format_is_fail(monkeypatch, tmp_path):
    """最新日期格式异常 = FAIL。"""
    _freeze(monkeypatch, "20261017")
    _patch_db(monkeypatch, _make_db(tmp_path, "abcdefgh"))
    r = cdi.check_fund_index_daily()
    _chk(r.status == "fail", f"坏格式应 FAIL, 实得 {r.status}: {r.msg}")


# ══════════════════════ ⑤ 判别力(改坏 → 判定必然翻转) ══════════════════════
def test_05_discriminating_power_thresholds(monkeypatch, tmp_path):
    """改坏阈值 → 判定翻转, 证明 ③ 的 FAIL/WARN 断言真被阈值驱动(非空转)。

    fixture: 20260930@20261019 → lag 8。
      原阈值(3/7): FAIL;
      改坏 FAIL 阈值到 100: 退为 WARN(证明 FAIL 断言敏感);
      再改坏 WARN 阈值到 100: 退为 OK(证明 WARN 断言敏感)。
    """
    _freeze(monkeypatch, "20261019")
    _patch_db(monkeypatch, _make_db(tmp_path, "20260930"))
    _chk(cdi.check_fund_index_daily().status == "fail", "原阈值应 FAIL")
    monkeypatch.setattr(cdi, "STALE_DAYS_FAIL", 100)
    _chk(cdi.check_fund_index_daily().status == "warn", "FAIL 阈值放宽后应退为 WARN")
    monkeypatch.setattr(cdi, "STALE_DAYS_WARN", 100)
    _chk(cdi.check_fund_index_daily().status == "ok", "WARN 阈值放宽后应退为 OK")


def test_06_discriminating_power_tradingday_caliber(monkeypatch, tmp_path):
    """换回自然日口径(旧/改坏实现) → 长假后首日误报, 证明交易日口径是判定承重件。

    fixture: 20260930@20261008 —— 交易日 lag 1(OK), 自然日 8(> 7 → 会 FAIL)。
    """
    _freeze(monkeypatch, "20261008")
    _patch_db(monkeypatch, _make_db(tmp_path, "20260930"))
    _chk(cdi._lag_trading_days("20260930") == 1, "交易日口径应 lag 1")
    _chk(cdi._days_ago("20260930") == 8, "自然日口径应 8(= 会误报)")
    _chk(cdi.check_fund_index_daily().status == "ok", "交易日口径: 长假后首日 OK 不误报")
    # 改坏 = 退回自然日口径
    monkeypatch.setattr(cdi, "_lag_trading_days", lambda d: cdi._days_ago(d))
    _chk(cdi.check_fund_index_daily().status == "fail", "自然日口径会误报 FAIL(判别力成立)")


# ══════════════════════ 静态锁: 阈值常量 + 编排登记点 ══════════════════════
def test_07_static_lock_thresholds_and_registration():
    src = (SCRIPTS / "check_data_integrity.py").read_text(encoding="utf-8")
    _chk("STALE_DAYS_WARN = 3" in src and "STALE_DAYS_FAIL = 7" in src, "复用既有阈值常量未变")
    _chk("def check_fund_index_daily(" in src, "新 check 函数已定义")
    _chk("results.append(check_fund_index_daily())" in src, "新 check 已登记进 run_all_checks")
    _chk("_lag_trading_days(latest)" in src, "用交易日口径(非自然日)")


# ══════════════════════ ⓪ 零外发自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_proves_db_patch(monkeypatch, tmp_path):
    """打桩生效自证: 库路径被 monkeypatch ⇒ 真出口 urlopen 从未被触达(hits==[])。"""
    _freeze(monkeypatch, "20261017")
    _patch_db(monkeypatch, _make_db(tmp_path, "20260929"))
    with ZeroOutboundTrap() as trap:
        cdi.check_fund_index_daily()
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_99_min_assertions():
    """§18 L49: 断言计数下限, 防收集/执行异常致假绿。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")