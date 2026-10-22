# -*- coding: utf-8 -*-
"""#280 failed-unit 白名单回归测试(2026-10-22)。

背景: 云上 `systemctl --failed` 里的 `fwupd-refresh.service`(OS 侧 LVFS 固件刷新)
与本项目无关, 却让 failed-unit 巡检长期误报(docs/ops/failed-units-rca-20261022.md)。
#280 给 scripts/check_failed_units.py 加**可配置白名单**(默认 docs/deploy/failed-unit-allowlist.txt),
目标: 系统层噪音不告警但**可追溯**; 本项目 unit(trade-*)绝不允许进白名单。

证据用例(任务书口径, 每条都是真实子进程跑本脚本 + dry 模式零外发):
  ① fwupd-refresh.service failed ⇒ 不告警(rc=0) + 打印 `[INFO] 白名单忽略: fwupd-refresh.service`
  ② trade-xxx.service failed(同一白名单下)⇒ 照常告警(rc=1, CHECK_FAILED_UNITS_FAIL)
  ③ 白名单里出现 trade-xxx ⇒ 启动机检拒绝运行(rc=2, 报错写明禁止)
  ④ 白名单文件缺失 ⇒ 安全降级(按空白名单 + INFO, 不崩; 此时 fwupd 照常告警)
  ⑤ 通配模式(fwupd*)可用(与文件头声明一致)
  ⑥ 随仓默认白名单只含 fwupd、且不含任何 trade-*
  ⑦ 通配绕过(2026-10-22 审查 P1): 白名单写 `*` / `trade*` / `*.service` /
     `*.timer` / `trade*.timer` / `*.socket` ⇒ 同样 rc=2(探测样例覆盖
     service / timer / socket 三种后缀);对照组 `fwupd*` 仍 rc=0 + INFO(禁令不外溢)

⚠️ 零外发自证(§18 L48): 全部子进程用例**不传 --notify**(dry 模式); 另有一条进程内用例
   在 `--notify --dry-run` 下把 `_send_notify` 换成「调用即报错」, 证明 dry 时绝不触达通知链。

跑法: python3 -m pytest -q scripts/tests/test_280_failed_unit_allowlist_20261022.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_denoise_rules as adr  # noqa: E402
import check_failed_units as cfu  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
CFU = ROOT / "scripts" / "check_failed_units.py"

# 全部巡检 timer 健康样本(只喂三态; 不喂 ExecStart ⇒ 脚本存在性层不会误判, 见 test_196 注释)
HEALTHY_SHOW = {u: {"ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled"}
                for u, _ in adr.WATCHMAN_UNITS}

FWUPD_LINE = "fwupd-refresh.service loaded failed failed Refresh fwupd metadata\n"
TRADE_LINE = "trade-xxx.service loaded failed failed Some project unit\n"


def _run(tmp_path, failed_text="", allowlist=None, extra=None):
    """子进程跑 check_failed_units.py(注入样本; 默认 dry, 绝不真发通知)。"""
    f = tmp_path / "failed.txt"
    f.write_text(failed_text, encoding="utf-8")
    s = tmp_path / "show.json"
    s.write_text(json.dumps(HEALTHY_SHOW), encoding="utf-8")
    cmd = [sys.executable, str(CFU), "--repo", str(tmp_path),
           "--failed-units-file", str(f), "--unit-show-json", str(s)]
    if allowlist is not None:
        cmd += ["--allowlist-file", str(allowlist)]
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)


def _allowlist(tmp_path, *lines):
    p = tmp_path / "allow.txt"
    p.write_text("# test allowlist\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════
# ① fwupd failed ⇒ 不告警 + INFO 可追溯
# ══════════════════════════════════════════════════════════════════
def test_case1_fwupd_failed_allowlisted_no_alert_with_info(tmp_path):
    allow = _allowlist(tmp_path, "fwupd-refresh.service")
    r = _run(tmp_path, FWUPD_LINE, allowlist=allow)
    assert r.returncode == 0, f"白名单命中应健康返回(rc=0): rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[INFO] 白名单忽略: fwupd-refresh.service" in r.stdout, \
        f"白名单忽略必须留可追溯 INFO 行: {r.stdout}"
    assert "CHECK_FAILED_UNITS_FAIL" not in r.stdout, "白名单命中不得进入告警分支"


# ══════════════════════════════════════════════════════════════════
# ② trade-* failed ⇒ 照常告警(白名单不得影响本项目 unit)
# ══════════════════════════════════════════════════════════════════
def test_case2_trade_unit_failed_still_alerted(tmp_path):
    allow = _allowlist(tmp_path, "fwupd-refresh.service")
    r = _run(tmp_path, TRADE_LINE, allowlist=allow)
    assert r.returncode == 1, f"本项目 unit 失败必须照常告警(rc=1): rc={r.returncode}\n{r.stderr}"
    assert "CHECK_FAILED_UNITS_FAIL" in r.stdout, r.stdout
    assert "trade-xxx.service" in r.stdout
    assert "白名单忽略" not in r.stdout, "trade unit 不应被白名单命中"


# ══════════════════════════════════════════════════════════════════
# ③ 白名单含 trade-* ⇒ 启动机检拒绝运行
# ══════════════════════════════════════════════════════════════════
def test_case3_trade_unit_in_allowlist_rejected_exit2(tmp_path):
    allow = _allowlist(tmp_path, "fwupd-refresh.service", "trade-xxx.service")
    r = _run(tmp_path, TRADE_LINE, allowlist=allow)
    assert r.returncode == 2, f"白名单含 trade-* 必须拒绝运行(rc=2): rc={r.returncode}\n{r.stderr}"
    assert "禁止包含本项目 unit" in r.stderr, r.stderr
    assert "trade-xxx.service" in r.stderr


def test_case3b_trade_glob_also_rejected(tmp_path):
    """通配形态同样不能绕过禁令(trade-* 作为模式也不行)。"""
    allow = _allowlist(tmp_path, "trade-*")
    r = _run(tmp_path, "", allowlist=allow)
    assert r.returncode == 2, r.stderr
    assert "禁止包含本项目 unit" in r.stderr


@pytest.mark.parametrize("pattern", ["*", "trade*", "*.service",
                                     "*.timer", "trade*.timer", "*.socket"])
def test_case3c_wildcard_pattern_matching_trade_rejected(tmp_path, pattern):
    """效果判据(2026-10-22 审查 P1): 任何能命中 trade-* unit 的模式都必须 exit 2。

    旧实现只判字面前缀 `startswith("trade-")`, 上述写法都能让 fnmatch 命中本项目
    unit 从而把真故障静音(审查实测 `*` ⇒ trade-foo failed 被静音 rc=0)。
    探测样例覆盖 service / timer / socket 三种后缀: 本项目活跃巡检多为 `.timer`
    (如 trade-cloud-unit-patrol.timer), 只探 `.service` 时 `*.timer` 仍可绕过。
    """
    allow = _allowlist(tmp_path, pattern)
    r = _run(tmp_path, TRADE_LINE, allowlist=allow)
    assert r.returncode == 2, f"白名单 {pattern!r} 可静音本项目 unit, 必须拒绝运行: {r.stdout}\n{r.stderr}"
    assert "禁止包含" in r.stderr, r.stderr
    assert pattern in r.stderr, f"报错须写明违规 pattern: {r.stderr}"
    assert "白名单忽略" not in r.stdout, "拒绝启动时不得先静音任何 unit"


def test_case3d_generic_service_glob_not_silently_allowed(tmp_path):
    """对照组: 不会命中 trade-*.service 的系统噪音模式仍可用(禁令不外溢成「一律拒绝」)。"""
    allow = _allowlist(tmp_path, "fwupd*")
    r = _run(tmp_path, FWUPD_LINE, allowlist=allow)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[INFO] 白名单忽略: fwupd-refresh.service" in r.stdout


# ══════════════════════════════════════════════════════════════════
# ④ 白名单文件缺失 ⇒ 安全降级(不崩; 该报的照报)
# ══════════════════════════════════════════════════════════════════
def test_case4_allowlist_file_missing_safe(tmp_path):
    missing = tmp_path / "nope" / "allow.txt"
    r = _run(tmp_path, FWUPD_LINE, allowlist=missing)
    # 不崩: 按空白名单处理; fwupd 因此照常进入告警(rc=1), 并明确打印文件缺失 INFO
    assert r.returncode == 1, f"文件缺失应降级为空白名单(不崩): rc={r.returncode}\n{r.stderr}"
    assert "白名单文件缺失, 按空白名单处理" in r.stdout, r.stdout
    assert "Traceback" not in r.stderr
    assert "CHECK_FAILED_UNITS_FAIL" in r.stdout


# ══════════════════════════════════════════════════════════════════
# ⑤ 通配模式
# ══════════════════════════════════════════════════════════════════
def test_glob_pattern_fwupd_star(tmp_path):
    allow = _allowlist(tmp_path, "fwupd*")
    r = _run(tmp_path, FWUPD_LINE, allowlist=allow)
    assert r.returncode == 0, r.stdout
    assert "[INFO] 白名单忽略: fwupd-refresh.service" in r.stdout


# ══════════════════════════════════════════════════════════════════
# ⑥ 随仓默认白名单: 只收系统噪音, 不收 trade-*
# ══════════════════════════════════════════════════════════════════
def test_shipped_default_allowlist_only_system_noise():
    pats, errs = cfu.load_allowlist(cfu.ALLOWLIST_DEFAULT_PATH)
    assert errs == [], errs
    assert "fwupd-refresh.service" in pats, f"默认白名单缺 fwupd: {pats}"
    assert not [p for p in pats if p.startswith("trade-")], f"默认白名单混入 trade-*: {pats}"


# ══════════════════════════════════════════════════════════════════
# 零外发自证: --notify + --dry-run 时 _send_notify 绝不被调用
# ══════════════════════════════════════════════════════════════════
def test_dry_run_never_calls_notify(tmp_path, monkeypatch):
    allow = _allowlist(tmp_path, "fwupd-refresh.service")
    f = tmp_path / "failed.txt"
    f.write_text(TRADE_LINE, encoding="utf-8")
    s = tmp_path / "show.json"
    s.write_text(json.dumps(HEALTHY_SHOW), encoding="utf-8")

    def _boom(*a, **kw):  # pragma: no cover - 被调用即失败
        raise AssertionError("dry-run 不得触达通知链(L48 零外发)")

    monkeypatch.setattr(cfu, "_send_notify", _boom)
    monkeypatch.setattr(sys, "argv", [
        "check_failed_units.py", "--repo", str(tmp_path),
        "--failed-units-file", str(f), "--unit-show-json", str(s),
        "--allowlist-file", str(allow), "--notify", "--dry-run",
    ])
    rc = cfu.main()
    assert rc == 1, "dry 模式发现问题应 rc=1(打印将发送内容), 实际 rc=%s" % rc