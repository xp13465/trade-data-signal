# -*- coding: utf-8 -*-
"""#309/#310 收尾 A: UNIT_REGISTRY 漂移机检单测(2026-10-31)。

V1 现状: 43/43 无漂移。
V2 注入: 多/少一个 timer ⇒ FAIL 并明列差异。
V3 main-merge 闸门: 走 check_drift() 入口, 漂移非零退出, 正常零退出。

全程 static-only: 不跑 systemctl、不跑业务脚本; 只 monkeypatch
`check_unit_registry_drift._dynamic_real_units` / `_static_real_services`
返回注入集合。
"""
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).absolute().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def drift_mod(monkeypatch):
    import check_unit_registry_drift as mod
    importlib.reload(mod)
    # 默认禁用动态源, 用例自己注入静态集
    monkeypatch.setattr(mod, "_dynamic_real_units", lambda: set())
    return mod


def _real_set():
    """取当前 43 个 .service 作为「真实集」基线(与登记表一致)。"""
    import gen_schedule_stats as gss
    return {r["unit"] for r in gss.UNIT_REGISTRY if r["unit"].endswith(".service")}


def test_v1_no_drift_43(drift_mod, monkeypatch, capsys):
    """V1: 现状 43/43 → PASS (rc=0)。"""
    baseline = _real_set()
    monkeypatch.setattr(drift_mod, "_static_real_services", lambda: set(baseline))
    rc = drift_mod.check_drift(quiet=True)
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "无漂移" in out.out
    assert f"{len(baseline)}" in out.out


def test_v2_extra_in_real(drift_mod, monkeypatch, capsys):
    """V2: 真实侧多一个(新增 timer 漏进登记表, #310 同类)→ FAIL rc=2 明列。"""
    baseline = _real_set()
    extra = {"trade-NEW-fake-task.service"}
    monkeypatch.setattr(drift_mod, "_static_real_services", lambda: set(baseline) | extra)
    rc = drift_mod.check_drift(quiet=True)
    out = capsys.readouterr()
    assert rc == 2, out.err
    assert "真实侧多" in out.err
    assert "trade-NEW-fake-task.service" in out.err


def test_v2_missing_from_real(drift_mod, monkeypatch, capsys):
    """V2: 真实侧少一个(登记表有但 docs/systemd 没有, 改名/删除未销账)→ FAIL rc=2。"""
    baseline = _real_set()
    dropped = {sorted(baseline)[0]}
    monkeypatch.setattr(drift_mod, "_static_real_services", lambda: set(baseline) - dropped)
    rc = drift_mod.check_drift(quiet=True)
    out = capsys.readouterr()
    assert rc == 2, out.err
    assert "登记表多" in out.err


def test_v3_empty_real_blocks(drift_mod, monkeypatch):
    """V3: 真实集为空(docs 缺 + 无 systemd)→ 拒绝放行 rc=3, 不静默通过。"""
    monkeypatch.setattr(drift_mod, "_static_real_services", lambda: set())
    rc = drift_mod.check_drift(quiet=True)
    assert rc == 3
