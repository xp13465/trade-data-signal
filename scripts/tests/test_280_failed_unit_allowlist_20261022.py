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
     `*.timer` / `trade*.timer` / `*.socket` ⇒ 同样 rc=2
  ⑧ 第三次同类绕过(2026-10-22 复审): `*schedule-monitor.timer` /
     `*schedule-monitor.service` / `*patrol*` ⇒ rc=2, 且报错**写明会静音哪个真实 unit**
     (探针 = 项目真实 unit 全集, 不是列举样例; 样例永远追不上组合)
  ⑨ 动态取数失败 ⇒ 回退静态集合(INFO)仍能拦 `*schedule-monitor.timer`, 不崩
  ⑩ `*.socket` 当前无真实 socket unit 也拒绝(命名空间结构判据, 防未来新增被静音)
  ⑪ 合法系统条目 `fwupd-refresh.service` / `fwupd*` / `systemd-tmpfiles-clean.timer`
     仍 rc=0 + `[INFO] 白名单忽略`(禁令不外溢)
  ⑫ 动态源并集(2026-10-22 复审 must-fix): `systemctl list-unit-files` 报的
     `trade-foo.service` **不在静态文档里**, 也必须进探针全集 ⇒ `*foo*` rc=2;
     同一动态源下合法 `fwupd*` 仍 rc=0 + INFO(并集不误伤)
  ⑬ 编码式后缀改写(2026-10-22 复审 must-fix): `*ocket` / `*.sock*` / `*[.]socke*`
     字面后缀都不是 `.socket`, 但 fnmatch 实测命中 `trade-zzz.socket` ⇒ 全部 rc=2

⚠️ 零外发自证(§18 L48): 全部子进程用例**不传 --notify**(dry 模式); 另有一条进程内用例
   在 `--notify --dry-run` 下把 `_send_notify` 换成「调用即报错」, 证明 dry 时绝不触达通知链。

跑法: python3 -m pytest -q scripts/tests/test_280_failed_unit_allowlist_20261022.py
"""
from __future__ import annotations

import json
import os
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
TMPFILES_LINE = "systemd-tmpfiles-clean.timer loaded failed failed Cleanup tmp\n"


def _run(tmp_path, failed_text="", allowlist=None, extra=None, env=None):
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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False,
                          env=env)


def _fake_systemctl(tmp_path, unit_files):
    """造一个假 systemctl(只答 list-unit-files), 模拟「运行时系统有静态文档之外的 unit」。

    返回带 PATH 前缀的 env: 让被测脚本 `shutil.which("systemctl")` 命中这个桩, 从而走
    **真实** `_dynamic_project_units` 解析路径(不是 monkeypatch 掉函数, 防测了个空壳)。
    """
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    listing = "".join(f"{u} enabled enabled\n" for u in unit_files)
    shim = bindir / "systemctl"
    shim.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "  list-unit-files)\n"
        f"    printf '%s' '{listing}'\n"
        "    exit 0\n"
        "    ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    return env


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
                                     "*.timer", "trade*.timer", "*.socket",
                                     "*schedule-monitor.timer",
                                     "*schedule-monitor.service",
                                     "*patrol*"])
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
# ③b 第三次同类绕过(2026-10-22 复审): 报错必须点名「会静音哪个真实 unit」
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("pattern,unit", [
    ("*schedule-monitor.timer", "trade-schedule-monitor.timer"),
    ("*schedule-monitor.service", "trade-schedule-monitor.service"),
])
def test_case3e_extended_wildcard_names_the_real_unit(tmp_path, pattern, unit):
    """列举式样例的洞: 补 `.timer`/`.socket` 样例后 `*schedule-monitor.timer` 仍绕过。
    根治后的判据是真实 unit 全集 ⇒ 报错必须写明会静音的真实 unit 名。"""
    allow = _allowlist(tmp_path, pattern)
    r = _run(tmp_path, "", allowlist=allow)
    assert r.returncode == 2, f"{pattern} 可静音真实 {unit}: {r.stdout}\n{r.stderr}"
    assert f"会静音真实 unit {unit}" in r.stderr, f"报错须点名真实 unit: {r.stderr}"


def test_case3f_patrol_glob_rejected_by_real_units(tmp_path):
    """`*patrol*` 只能靠真实 unit 全集拦住(无项目后缀, 命名空间判据不兜底)。"""
    allow = _allowlist(tmp_path, "*patrol*")
    r = _run(tmp_path, "", allowlist=allow)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "会静音真实 unit trade-cloud-unit-patrol." in r.stderr, r.stderr


def test_real_unit_universe_covers_all_watchman_and_repo_units():
    """静态全集必须同时覆盖 WATCHMAN_UNITS 与仓库 unit 文档(不只 9 个 timer)。"""
    units = cfu.collect_real_units()
    assert "trade-schedule-monitor.timer" in units, units
    assert "trade-schedule-monitor.service" in units, units
    assert "trade-cloud-unit-patrol.timer" in units, units
    assert all(u.startswith("trade-") for u in units), units


def test_dynamic_fetch_failure_falls_back_static_and_still_blocks(monkeypatch, capsys, tmp_path):
    """⑨ 动态取数失败(抛异常)⇒ 回退静态集合 + INFO, 仍能拦 `*schedule-monitor.timer`, 不崩。"""
    def _boom():
        raise RuntimeError("simulated systemctl failure")

    monkeypatch.setattr(cfu, "_dynamic_project_units", _boom)
    units = cfu.collect_real_units()          # 不得抛异常
    out = capsys.readouterr().out
    assert "回退静态 unit 集合" in out, out
    assert "trade-schedule-monitor.timer" in units

    allow = _allowlist(tmp_path, "*schedule-monitor.timer")
    patterns, errors = cfu.load_allowlist(allow, probe_units=units)
    assert patterns == [], patterns
    assert any("会静音真实 unit trade-schedule-monitor.timer" in e for e in errors), errors


def test_static_doc_parse_failure_falls_back_watchman(monkeypatch, capsys, tmp_path):
    """回退路径②: 仓库 unit 文档不可解析 ⇒ 仅用 WATCHMAN_UNITS, 不崩且仍能拦。"""
    import gen_systemd_units as gsu

    def _boom(*a, **kw):
        raise RuntimeError("simulated broken doc")

    monkeypatch.setattr(gsu, "parse_units", _boom)
    monkeypatch.setattr(cfu, "_dynamic_project_units", lambda: [])
    units = cfu.collect_real_units()
    out = capsys.readouterr().out
    assert "仅用 WATCHMAN_UNITS" in out, out
    assert {u for u, _ in adr.WATCHMAN_UNITS} <= set(units)

    allow = _allowlist(tmp_path, "*schedule-monitor.timer")
    patterns, errors = cfu.load_allowlist(allow, probe_units=units)
    assert patterns == [], patterns
    assert any("会静音真实 unit trade-schedule-monitor.timer" in e for e in errors), errors


def test_empty_universe_refuses_allowlist(monkeypatch, tmp_path):
    """全部取不到 ⇒ 拒绝加载白名单(exit 2), 绝不因判不了而放行。"""
    monkeypatch.setattr(cfu, "_static_project_units", lambda: set())
    monkeypatch.setattr(cfu, "_dynamic_project_units", lambda: [])
    allow = _allowlist(tmp_path, "fwupd-refresh.service")
    patterns, errors = cfu.load_allowlist(allow)
    assert patterns == [], patterns
    assert any("拒绝加载白名单" in e for e in errors), errors


def test_socket_namespace_guard_without_real_socket_unit(tmp_path):
    """⑩ 项目当前没有 trade-*.socket 真实 unit, `*.socket` 仍须拒绝(防未来新增被静音)。"""
    allow = _allowlist(tmp_path, "*.socket")
    r = _run(tmp_path, "", allowlist=allow)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "命名空间" in r.stderr, r.stderr


# ══════════════════════════════════════════════════════════════════
# ⑫ 动态源并集(2026-10-22 复审 must-fix ①): 静态文档之外的运行时 unit 也要进探针全集
# ══════════════════════════════════════════════════════════════════
def test_dynamic_union_unit_outside_static_docs_blocks_pattern(tmp_path):
    """`systemctl list-unit-files` 报的 trade-foo.service 不在静态文档里, 也必须被拦。

    走真实 `_dynamic_project_units` 解析路径(假 systemctl 桩 + 真子进程), 不是 monkeypatch
    掉函数 —— 变异检验: 把 collect_real_units 的 `static | set(dynamic)` 改回只 static 时,
    本用例必须真红(rc 从 2 掉成 0)。
    """
    assert "trade-foo.service" not in cfu._static_project_units(), \
        "前提: trade-foo.service 必须是静态文档之外的 unit(否则测不到动态并集)"
    env = _fake_systemctl(tmp_path, ["trade-foo.service", "fwupd-refresh.service"])
    allow = _allowlist(tmp_path, "*foo*")
    r = _run(tmp_path, "", allowlist=allow, env=env)
    assert r.returncode == 2, \
        f"动态源里的 trade-foo.service 必须使 *foo* 被拒(rc=2): rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "会静音真实 unit trade-foo.service" in r.stderr, r.stderr
    assert "系统现状" in r.stdout, f"INFO 须显示动态源已并入: {r.stdout}"


def test_dynamic_union_does_not_overblock_system_noise(tmp_path):
    """同一动态源下合法 `fwupd*` 仍 rc=0 + INFO(并集不误伤系统噪音)。"""
    env = _fake_systemctl(tmp_path, ["trade-foo.service", "fwupd-refresh.service"])
    allow = _allowlist(tmp_path, "fwupd*")
    r = _run(tmp_path, FWUPD_LINE, allowlist=allow, env=env)
    assert r.returncode == 0, f"合法系统噪音不应被并集误伤: rc={r.returncode}\n{r.stderr}"
    assert "[INFO] 白名单忽略: fwupd-refresh.service" in r.stdout, r.stdout


# ══════════════════════════════════════════════════════════════════
# ⑬ 编码式后缀改写(2026-10-22 复审 must-fix ②): 实测探针判据, 不看字面后缀
# ══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("pattern", ["*ocket", "*.sock*", "*[.]socke*"])
def test_encoded_socket_suffix_patterns_rejected(tmp_path, pattern):
    """字面后缀不是 `.socket`, 但 fnmatch 实测命中 trade-zzz.socket ⇒ 必须 rc=2。

    变异检验: 命名空间判据退回「字面前缀是否与 trade- 相容」时, 这些写法全部放行(rc=1)。
    """
    allow = _allowlist(tmp_path, pattern)
    r = _run(tmp_path, TRADE_LINE, allowlist=allow)
    assert r.returncode == 2, f"{pattern!r} 可静音 trade-*.socket, 必须拒绝: {r.stdout}\n{r.stderr}"
    assert "命名空间" in r.stderr, r.stderr
    assert "白名单忽略" not in r.stdout, "拒绝启动时不得先静音任何 unit"


@pytest.mark.parametrize("pattern,unit", [
    ("fwupd-refresh.service", "fwupd-refresh.service"),
    ("fwupd*", "fwupd-refresh.service"),
    ("systemd-tmpfiles-clean.timer", "systemd-tmpfiles-clean.timer"),
])
def test_legal_system_patterns_still_rc0_with_info(tmp_path, pattern, unit):
    """⑪ 合法系统条目在探针判据下仍 rc=0 + `[INFO] 白名单忽略`(真实子进程口径)。"""
    line = f"{unit} loaded failed failed OS noise\n"
    allow = _allowlist(tmp_path, pattern)
    r = _run(tmp_path, line, allowlist=allow)
    assert r.returncode == 0, f"{pattern!r} 属合法系统噪音, 不应被拦: {r.stdout}\n{r.stderr}"
    assert f"[INFO] 白名单忽略: {unit}" in r.stdout, r.stdout


def test_legal_system_entries_pass_with_real_unit_universe(tmp_path):
    """⑪ 合法系统条目不受影响(禁令不外溢)。"""
    for pat in ("fwupd-refresh.service", "fwupd*", "systemd-tmpfiles-clean.timer"):
        allow = _allowlist(tmp_path, pat)
        patterns, errors = cfu.load_allowlist(allow)
        assert errors == [], f"{pat}: {errors}"
        assert pat in patterns


def test_systemd_tmpfiles_allowlisted_rc0_with_info(tmp_path):
    """⑩ 合法 timer 噪音: rc=0 + `[INFO] 白名单忽略`。"""
    allow = _allowlist(tmp_path, "systemd-tmpfiles-clean.timer")
    r = _run(tmp_path, TMPFILES_LINE, allowlist=allow)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[INFO] 白名单忽略: systemd-tmpfiles-clean.timer" in r.stdout


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