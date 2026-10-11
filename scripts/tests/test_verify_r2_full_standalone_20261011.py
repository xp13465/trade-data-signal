# -*- coding: utf-8 -*-
"""B6(2026-10-11)P0 热修回归测试: verify-r2 周日 full 模式 UnboundLocalError 根治。

背景(事故)
  `upload_r2.py::cmd_verify_r2` 的 `standalone_files` 只在**平日增量(else)分支**赋值, 而
  「独立链产物脱节」告警记名在 `if mismatches:` 内**无条件引用**它 ⇒ 周日(=full 全量对账)
  只要任一通道有不一致就 `UnboundLocalError: cannot access local variable 'standalone_files'`,
  全量对账中断、自动补传不执行(10-11 生产 02:16 / 05:11 两打; 引入 commit 09338aa0f #188)。

本测试
  · 全部在 tempdir 上跑, 依赖(s3_head / _upload_glob / _uniform_sample / notify / datetime /
    _R2_CHANNELS)逐个打桩, 属纯纯函数级调用 —— 零真实 R2 接触、零真实外发(ZeroOutboundTrap
    + notify 假模块双层, §18 L48)。
  · 跨环境敏感处显式传参/显式打桩, 不依赖任何「本机有 X」假设(#223④ 教训)。
  · 正向断言(修后语义)+ 反向断言(修前必崩的形态)都覆盖, 防「断言被删静默假绿」。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent))   # scripts/tests, 供 _zero_outbound
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

import upload_r2 as u  # noqa: E402  (conftest 已铺 .env 垫片, 收集期可 import)

_SUNDAY = (2026, 10, 11)      # 2026-10-11 = 周日 → weekday()==6 → full 模式
_MONDAY = (2026, 10, 5)       # 非周日 → 平日增量模式


class _FakeDate(_dt.date):
    _FORCE = _SUNDAY

    @classmethod
    def today(cls):
        return cls(*cls._FORCE)


class _FakeDT:
    """替换 upload_r2.datetime, 只固定 date.today() 的口径(其余委托真 datetime)。"""
    date = _FakeDate
    datetime = _dt.datetime
    timedelta = _dt.timedelta
    timezone = _dt.timezone


class _FakeNotify:
    """假 notify: check_dedup 恒 False(告警必发声), send 收 subject, update_dedup no-op。"""

    def __init__(self):
        self.sent: list[str] = []

    def check_dedup(self, key, window):
        return False

    def send(self, subject, body, **kw):
        self.sent.append(subject)

    def update_dedup(self, key):
        return None


def _build_env(tmp_path, monkeypatch, force_day, files, rows_in_r2=None):
    """铺一个单通道最小环境。

    files: {文件名: 内容} 写入 static-site/data/。
    rows_in_r2: {文件名: 是否与 R2 一致}(缺省一致); 不一致者 fake_head 返回异 ETag。
    返回 (dd, seen_keys, notify_fake)。
    """
    dd = tmp_path / "static-site" / "data"
    dd.mkdir(parents=True)
    for name, content in files.items():
        (dd / name).write_text(content, encoding="utf-8")

    _FakeDate._FORCE = force_day
    monkeypatch.setattr(u, "datetime", _FakeDT)
    monkeypatch.setattr(u, "STATIC_DIR", tmp_path / "static-site")

    nf = _FakeNotify()
    monkeypatch.setitem(sys.modules, "notify", nf)

    seen: list[str] = []
    inconsistent = set(rows_in_r2 or {})

    def fake_head(key, **kw):
        seen.append(key)
        name = key.rsplit("/", 1)[-1]
        fp = dd / name
        if not fp.exists():
            return (404, None)
        if name in inconsistent:
            return (200, '"ffffffffffffffffffffffffffffffff"')   # 故意与本地 md5 不同
        return (200, f'"{hashlib.md5(fp.read_bytes()).hexdigest()}"')

    monkeypatch.setattr(u, "s3_head", fake_head)
    monkeypatch.setattr(u, "_upload_glob", lambda *a, **k: (0, 0, [], []))
    monkeypatch.setattr(u, "_uniform_sample", lambda files, n: [])
    monkeypatch.setattr(u, "_assert_no_double_upload", lambda *a, **k: True)
    monkeypatch.setattr(u, "_R2_CHANNELS", [{
        "label": "synth", "local_dir": lambda: dd, "patterns": ["*.json"],
        "r2_prefix": "data", "state_name": None,
    }])
    return dd, seen, nf


def test_full_mode_mismatch_no_unboundlocalerror(monkeypatch, tmp_path):
    """P0 核心: 周日 full + 通道不一致 → 修前 UnboundLocalError, 修后正常收尾且发脱节告警。

    2026-10-11 降噪②: 单文件小规模脱节已降为仅日志 ⇒ 以「规模超常(3 文件 ≥ 阈值)」驱动,
    保持本用例原意(不崩 + 有等效告警输入)。
    """
    dd, seen, nf = _build_env(
        tmp_path, monkeypatch, _SUNDAY,
        files={"kelly_mode_s06_state.json": '{"coverage_end":"2026-10-10"}', "overview.json": '{"a":1}',
               "extra_a.json": '{"x":1}', "extra_b.json": '{"x":2}'},
        rows_in_r2={"kelly_mode_s06_state.json", "extra_a.json", "extra_b.json"},
    )
    u._record_standalone_keys(["data/kelly_mode_s06_state.json",
                               "data/extra_a.json", "data/extra_b.json"])

    with ZeroOutboundTrap() as trap:
        u.cmd_verify_r2()          # 修前此处抛 UnboundLocalError(L3730)

    assert trap.hits == [], f"零外发被破坏: {trap.hits}"
    # full 模式: 全池都在被查对象里(4 个文件逐个 HEAD)
    assert sorted(k.rsplit("/", 1)[-1] for k in seen) == [
        "extra_a.json", "extra_b.json", "kelly_mode_s06_state.json", "overview.json"]
    # 语义正确: 独立链产物脱节(规模超常) → 层4 外围告警照发(full 模式同样要有等效输入, 非仅消崩)
    assert any("独立上传链产物与 R2 脱节" in s for s in nf.sent), f"full 模式缺脱节告警: {nf.sent}"


def test_full_mode_all_consistent_no_alert(monkeypatch, tmp_path):
    """反向: 周日 full + 全一致 → 不崩、无任何告警。"""
    _dd, seen, nf = _build_env(
        tmp_path, monkeypatch, _SUNDAY,
        files={"kelly_mode_s06_state.json": '{"coverage_end":"2026-10-10"}'},
        rows_in_r2=set(),
    )
    u._record_standalone_keys(["data/kelly_mode_s06_state.json"])
    with ZeroOutboundTrap() as trap:
        u.cmd_verify_r2()
    assert trap.hits == []
    assert seen, "full 模式应逐个 HEAD 本地文件"
    assert nf.sent == [], f"全一致不应有告警: {nf.sent}"


def test_weekday_standalone_still_selected_and_alert(monkeypatch, tmp_path):
    """回归: 平日(changed 空 + 抽样空)独立链产物仍被选中对账 → 超常脱节 → 告警。

    2026-10-11 降噪②: 单文件小规模脱节降为「仅日志」⇒「仍被选中对账」不变(该断言保留),
    告警断言改为「规模超常(3 文件)」触发的形态。
    """
    _dd, seen, nf = _build_env(
        tmp_path, monkeypatch, _MONDAY,
        files={"kelly_mode_s06_state.json": '{"coverage_end":"2026-10-10"}', "overview.json": '{"a":1}',
               "extra_a.json": '{"x":1}', "extra_b.json": '{"x":2}'},
        rows_in_r2={"kelly_mode_s06_state.json", "extra_a.json", "extra_b.json"},
    )
    u._record_standalone_keys(["data/kelly_mode_s06_state.json",
                               "data/extra_a.json", "data/extra_b.json"])
    with ZeroOutboundTrap() as trap:
        u.cmd_verify_r2()
    assert trap.hits == []
    assert "data/kelly_mode_s06_state.json" in seen, "平日: 台账内独立链产物必须被对账(不受抽样/上限截断)"
    assert any("独立上传链产物与 R2 脱节" in s for s in nf.sent), f"平日超常脱节应告警: {nf.sent}"


def test_weekday_small_stale_only_logs_no_alert(monkeypatch, tmp_path, capsys):
    """2026-10-11 降噪②验收①: 平日单文件小规模脱节 ⇒ 仅日志(不发通知)。"""
    _dd, seen, nf = _build_env(
        tmp_path, monkeypatch, _MONDAY,
        files={"kelly_mode_s06_state.json": '{"coverage_end":"2026-10-10"}'},
        rows_in_r2={"kelly_mode_s06_state.json"},
    )
    u._record_standalone_keys(["data/kelly_mode_s06_state.json"])
    with ZeroOutboundTrap() as trap:
        u.cmd_verify_r2()
    assert trap.hits == []
    assert "data/kelly_mode_s06_state.json" in seen, "平日仍须对账该产物(不因降噪漏检)"
    assert nf.sent == [], f"小规模脱节不应外发通知: {nf.sent}"
    assert "仅日志" in capsys.readouterr().out, "应打印「仅日志」说明(留痕不静默)"


def test_ledger_missing_full_mode_no_weekday_alert(monkeypatch, tmp_path):
    """周日 full + 台账缺失: 不发「平日对账退化」告警(full 全池覆盖不受台账影响, 防周日误报)。"""
    _dd, _seen, nf = _build_env(
        tmp_path, monkeypatch, _SUNDAY,
        files={"overview.json": '{"a":1}'}, rows_in_r2=set(),
    )
    assert not u._standalone_keys_path().exists(), "本用例前提: 台账不存在"
    with ZeroOutboundTrap() as trap:
        u.cmd_verify_r2()
    assert trap.hits == []
    assert not any("台账缺失" in s for s in nf.sent), f"full 模式不应发平日台账告警: {nf.sent}"


def test_ledger_missing_weekday_alert_unchanged(monkeypatch, tmp_path):
    """回归: 平日 + 台账缺失 → 仍发「台账缺失」告警(既有行为不能被本次热修改掉)。"""
    _dd, _seen, nf = _build_env(
        tmp_path, monkeypatch, _MONDAY,
        files={"overview.json": '{"a":1}'}, rows_in_r2={"overview.json"},
    )
    assert not u._standalone_keys_path().exists()
    with ZeroOutboundTrap() as trap:
        u.cmd_verify_r2()
    assert trap.hits == []
    assert any("台账缺失" in s for s in nf.sent), f"平日台账缺失必须仍告警: {nf.sent}"


def test_load_standalone_keys_warn_flag(capsys, monkeypatch, tmp_path):
    """_load_standalone_keys(warn=False) 不打 stderr 文案; 缺省(True)仍打(#188 不静默语义保留)。"""
    monkeypatch.setattr(u, "STATIC_DIR", tmp_path / "static-site")   # 台账路径指向空 tempdir, 隔离本机
    assert u._load_standalone_keys(warn=False)[1] == u._LEDGER_MISSING
    assert capsys.readouterr().err == "", "warn=False 不应有 stderr 输出"
    u._load_standalone_keys()
    assert "台账不存在" in capsys.readouterr().err, "缺省 warn=True 仍须显式告警"