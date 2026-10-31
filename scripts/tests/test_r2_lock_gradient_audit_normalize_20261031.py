"""r2_lock_gradient_audit.py 常态化(2026-10-31)三态测试。

背景: 该审计 2026-10-28 建成后无自动闸门, overfit_monitor「内层 960 ≥ 外层 360」倒置
漏网多天(L55)。本次挂 main-merge 7.8b(--check-doc)+ 云上 patrol 第二段(--check-snapshot)。
本测试钉住: ①仓库侧默认 PASS; ②云上侧用真值重算能抓倒置; ③云上缺引用 unit 必须 FAIL
(不许当"无界"静默放过)。全部只读静态, 不跑上传/不发通知。
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
AUDIT_PY = REPO / "scripts" / "r2_lock_gradient_audit.py"
SNAPSHOT = REPO / "docs" / "deploy" / "systemd-units-cloud-snapshot.txt"


def _load():
    spec = importlib.util.spec_from_file_location(
        "r2_lock_audit_normalize_under_test", AUDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repo_side_audit_passes():
    """① 仓库侧(= --check-doc): 当前树应 PASS。"""
    mod = _load()
    _rows, errs = mod.audit()
    assert errs == [], f"当前树仓库侧审计应 PASS, 实得 {errs[:3]}"


def test_check_doc_cli_exit_zero():
    """①' 闸门真跑的命令: --check-doc --quiet exit 0。"""
    r = subprocess.run([sys.executable, str(AUDIT_PY), "--check-doc", "--quiet"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"rc={r.returncode} out={r.stdout[-500:]} err={r.stderr[-500:]}"


def test_live_units_inversion_detected():
    """② 云上侧: 用真值把 overfit 外层调到 360 ⇒ 必须报梯度倒置(闸门/告警不能空转)。"""
    mod = _load()
    units = mod._parse_units_file(SNAPSHOT)
    name = "trade-overfit-monitor.service"
    assert name in units, "快照缺 overfit unit, 测试前提不成立"
    units[name] = units[name].replace("TimeoutStartSec=1920", "TimeoutStartSec=360")
    assert "TimeoutStartSec=360" in units[name]
    _rows, errs = mod.audit(outer_units=units)
    assert any("梯度倒置" in e and "overfit_monitor" in e for e in errs), \
        f"注入倒置必须 FAIL, 实得 {errs[:3]}"


def test_live_units_missing_unit_fails_in_strict_mode():
    """③ 云上(严格)模式: 引用的 unit 不在权威源 ⇒ FAIL, 不许 WAIVED 成"无界"。"""
    mod = _load()
    units = mod._parse_units_file(SNAPSHOT)
    name = "trade-s06-snapshot.service"
    assert name in units, "快照缺 s06 unit, 测试前提不成立"
    del units[name]
    _rows, errs = mod.audit(outer_units=units, strict_missing=True)
    assert any("找不到 trade-s06-snapshot.service" in e for e in errs), \
        f"云上缺 unit 必须 FAIL, 实得 {errs[:3]}"


def test_repo_side_missing_unit_keeps_waived_behavior():
    """③' 仓库侧保持旧行为(缺 unit = WAIVED 无界), 防本次改动误伤既有口径。"""
    mod = _load()
    units = mod._parse_units_file(SNAPSHOT)
    del units["trade-s06-snapshot.service"]
    rows, errs = mod.audit(outer_units=units)
    assert errs == [], f"仓库侧缺 unit 不应 FAIL(旧行为), 实得 {errs[:3]}"
    assert any(r["status"] == "WAIVED" for r in rows), "应保留 WAIVED 语义"