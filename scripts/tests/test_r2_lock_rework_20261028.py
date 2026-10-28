#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 分域锁「返工三项」单测(2026-10-28,R1 探针补域锁 / R2 文档口径 / R3 白名单+审计补盲)。

背景: 任务书 `/tmp/task-r2lock-rework-20261028.md`(审查结论「有条件 PASS, 无 FAIL」三项找平)。
本文件只测**返工新增行为**, 原分域行为由 `test_r2_lock_domains_20261028.py` 与
`test_r2_lock_a_small_lane_20261023.py` 覆盖。

覆盖(证据用例):
  R1-① 探针默认仍只给全局+小锁(既有调用方行为不变, 原断言不放宽)
  R1-② include_domains=True ⇒ 全局 + 小锁 + 20 把域锁, 且每条路径与 upload_r2 派生**逐位相同**
        (同一实现来源, 不是手抄的第二份列表)
  R1-③ 域锁被占 ⇒ 诊断指向**正确那把域锁文件**, 无占用的域锁折叠成一行
  R3-① 白名单内域名 ⇒ 正常分域(建域锁 + 持全局 SH 屏障)
  R3-② 形状合法但未登记的域名(typo) ⇒ 回落全局锁 + WARN, **不会自建新锁**
  R3-③ 审计能抓「新增一个没登记的 Python 调用方」
  R3-④ 审计能抓「脚本内字面量域没有对应登记行」(同一脚本多域只登记一行的老盲区)
  R3-⑤ 审计对变量形式给明确处置: 已登记 = 放行 + 列入人工确认清单; 未登记 = FAIL
  R3-⑥ 区块/白名单双向一致: 登记表少一个白名单域 ⇒ FAIL
  R3-⑦ 探针契约: 审计能抓「诊断没带 include_domains=True」与「探针丢了 r2_lock_paths 复用」

零外发: 全打桩(临时目录 flock / fake probe / monkeypatch), 不跑上传、不联网、不发通知(§18 L48)。
"""
from __future__ import annotations

import fcntl
import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO / "scripts"
UR_PY = SCRIPTS / "upload_r2.py"
PROBE_PY = SCRIPTS / "r2_lock_probe.py"
PATHS_PY = SCRIPTS / "r2_lock_paths.py"
AUDIT_PY = SCRIPTS / "r2_lock_gradient_audit.py"


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ur(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK", str(tmp_path / "trade_r2_upload.lock"))
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", str(tmp_path / "trade_r2_upload_small.lock"))
    monkeypatch.delenv("R2_UPLOAD_LOCK_DOMAIN", raising=False)
    mod = _load(UR_PY, "upload_r2_rework_under_test")
    mod._BARRIER_FDS.clear()
    yield mod
    for fd in list(mod._BARRIER_FDS):
        mod._release_r2_upload_lock(fd)


@pytest.fixture()
def probe(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK", str(tmp_path / "trade_r2_upload.lock"))
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", str(tmp_path / "trade_r2_upload_small.lock"))
    return _load(PROBE_PY, "r2_lock_probe_rework_under_test")


# ══════════════════════ R1: 探针补域锁 ══════════════════════
def test_probe_default_still_two_locks(probe):
    """R1-① 默认(不传参)仍只给全局+小锁 —— 既有调用方/用例行为不变。"""
    got = probe.lock_paths_from_env()
    assert [label for label, _ in got] == ["全局锁", "小锁"]


def test_probe_with_domains_matches_upload_r2_paths(probe, ur):
    """R1-② 域锁路径与 upload_r2 派生逐位相同(同一实现来源, 防手抄第二份漂移)。"""
    got = dict(probe.lock_paths_from_env(include_domains=True))
    assert len(got) == 2 + 20, f"应为全局+小锁+20 把域锁, 实得 {len(got)}"
    for domain in ur._rlp.LOCK_DOMAINS:
        label = f"域锁:{domain}"
        assert label in got, f"探针缺域锁 {domain}"
        assert got[label] == str(ur._domain_upload_lock_path(domain)), \
            f"探针路径与 upload_r2 派生不一致: {label}"


def test_probe_points_at_held_domain_lock(probe, ur):
    """R1-③ 域锁被占 ⇒ 诊断指向正确那把域锁文件; 无占用的域锁折叠, 不冲垮日志。"""
    held = ur._domain_upload_lock_path("data")
    seen = []

    def fake_probe(path):
        seen.append(path)
        # 只有 data 域锁「有持锁者」, 其余(含全局锁)都探测不到 —— 模拟真实场景
        return "pid=4242(已运行 00:12) upload-intraday" if path == str(held) else ""

    exc = subprocess.TimeoutExpired(
        cmd="upload_r2.py", timeout=600,
        output=b"", stderr="⏳ 等待 R2 上传锁 137s(上限 600s)\n".encode())
    log, subject, body = probe.build_lock_timeout_diag(
        exc, lock_path=str(ur._global_upload_lock_path()), log_path="/tmp/x.log",
        date_tag="2026-10-28", lock_paths=probe.lock_paths_from_env(include_domains=True),
        probe=fake_probe)

    assert str(held) in seen, "诊断必须真的探测到域锁文件"
    assert f"域锁:data({held})=pid=4242" in log, f"诊断未指向被占的域锁: {log}"
    assert f"全局锁({ur._global_upload_lock_path()})=无占用/探测不到" in log
    assert "域锁(其余 19 把)=无占用/探测不到" in log, "无占用的域锁应折叠成一行"
    assert "137" in subject + body, "等锁秒数应取心跳里的真实值"
    for name in ("域锁:lab", "域锁:index"):
        assert f"{name}(" not in log, "无占用的域锁不该逐条展开"


def test_probe_layout_is_single_source():
    """R1 契约: 探针不得再持有自己的 env/缺省表(手抄第二份)。"""
    src = PROBE_PY.read_text(encoding="utf-8")
    assert "import r2_lock_paths as _rlp" in src
    assert "_rlp.lock_endpoints(include_domains=include_domains)" in src
    assert "_LOCK_PATH_ENVS" not in src, "探针不应再自持锁路径表(单一事实源在 r2_lock_paths.py)"
    assert "trade_r2_upload.lock" not in src, "探针不应硬编码锁路径(会被分域新增漏掉)"


# ══════════════════════ R3: 白名单 + 审计补盲 ══════════════════════
def test_whitelisted_domain_takes_domain_lock(ur, monkeypatch):
    """R3-① 白名单内域名 ⇒ 域锁 EX + 全局 SH 屏障(正常分域)。"""
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    assert ur._lock_domain() == "data"
    fd = ur._acquire_r2_upload_lock(timeout=0)
    try:
        assert ur._domain_upload_lock_path("data").exists(), "应建出 data 域锁文件"
        assert ur._BARRIER_FDS.get(fd), "域写者必须同时持全局 SH 屏障"
    finally:
        ur._release_r2_upload_lock(fd)


def test_unregistered_domain_falls_back_global_with_warn(ur, monkeypatch, capsys, tmp_path):
    """R3-② typo(形状合法但未登记) ⇒ 回落全局锁 + WARN, 且**不自建新锁**。

    这是本次返工要堵的洞: 原先只校验形状, `dataa` 会自建 `/tmp/trade_r2_upload_dataa.lock`,
    与真正的 data 域写者静默失去同 key 互斥。
    """
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "dataa")
    assert ur._lock_domain() is None
    err = capsys.readouterr().err
    assert "未登记" in err and "回落全局锁" in err
    fd = ur._acquire_r2_upload_lock(timeout=0)
    try:
        assert not ur._domain_upload_lock_path("dataa").exists(), "不许为未登记域名自建新锁"
        assert ur._global_upload_lock_path().exists(), "必须回落到全局锁文件"
        assert not ur._BARRIER_FDS, "回落全局锁时不应产生域屏障"
    finally:
        ur._release_r2_upload_lock(fd)
    assert tmp_path  # 锁文件都在临时目录(零生产影响)


def test_audit_catches_unregistered_python_caller(monkeypatch):
    """R3-③ 新增一个没登记的 Python 调用方 ⇒ 审计 FAIL(原审计只扫 shell 字面量)。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test")
    monkeypatch.setattr(mod, "_python_caller_domains",
                        lambda: {"scripts/brand_new_uploader.py": {"data"}})
    _rows, errs = mod.audit()
    assert any("brand_new_uploader.py" in e and "未在 SITES 登记" in e for e in errs), errs


def test_audit_catches_shell_literal_without_site(monkeypatch):
    """R3-④ 同一脚本里另写了一个域、SITES 却没对应行 ⇒ FAIL(update_all 老盲区族)。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test2")
    monkeypatch.setattr(mod, "_shell_domain_literals",
                        lambda: [("scripts/s06_snapshot.sh", "etf")])
    _rows, errs = mod.audit()
    assert any("s06_snapshot.sh" in e and "'etf'" in e for e in errs), errs


def test_audit_variable_form_known_vs_unknown(monkeypatch, capsys):
    """R3-⑤ 变量形式: 已登记 = 放行且进「人工确认清单」; 未登记 = FAIL(不许静默放过)。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test3")
    unknown = ("scripts/foo.sh", 'env R2_UPLOAD_LOCK_DOMAIN="$D" upload-index')
    monkeypatch.setattr(mod, "_shell_variable_forms", lambda: [unknown])
    _rows, errs = mod.audit()
    assert any("人工确认清单" in e and "foo.sh" in e for e in errs), errs
    assert mod.main([]) == 1
    out = capsys.readouterr().out
    assert "待确认 scripts/foo.sh" in out

    known = ("scripts/r2_upload_async.sh",
             'env ${_lock_domain:+R2_UPLOAD_LOCK_DOMAIN="$_lock_domain"} \\')
    monkeypatch.setattr(mod, "_shell_variable_forms", lambda: [known])
    _rows, errs = mod.audit()
    assert not [e for e in errs if "人工确认清单" in e], "已登记的 pass-through 行不该 FAIL"


def test_audit_domain_registry_must_match_whitelist(monkeypatch):
    """R3-⑥ 计登记表与白名单双向一致(单源漂移即 FAIL)。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test4")
    shrunk = {k: v for k, v in mod.DOMAINS.items() if k != "decommissioned"}
    monkeypatch.setattr(mod, "DOMAINS", shrunk)
    _rows, errs = mod.audit()
    assert any("decommissioned" in e for e in errs), errs


def test_audit_catches_probe_call_without_domains(monkeypatch, tmp_path):
    """R3-⑦ 诊断调用点缺 include_domains=True ⇒ FAIL(防返工被后续改回去)。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test5")
    fake_scripts = tmp_path / "scripts"
    fake_scripts.mkdir()
    (fake_scripts / "fake_caller.py").write_text(
        "def f(p):\n    return p\n\nlock_paths = lock_paths_from_env()\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO", tmp_path)
    monkeypatch.setattr(mod, "SITES", [])
    _rows, errs = mod.audit()
    assert any("fake_caller.py" in e and "include_domains=True" in e for e in errs), errs


def test_audit_catches_probe_contract_loss(monkeypatch, tmp_path):
    """R3-⑦ 探针丢了单一事实源复用 ⇒ FAIL(变异: 删掉 _rlp.lock_endpoints 调用)。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test6")
    fake = tmp_path / "probe.py"
    fake.write_text("# 变异版: 探针不再复用共享实现\n", encoding="utf-8")
    monkeypatch.setattr(mod, "PROBE_PY", fake)
    _rows, errs = mod.audit()
    assert any("r2_lock_probe.py 契约缺失" in e for e in errs), errs


def test_shared_module_is_single_truth_for_domains(ur):
    """R3 单源: 白名单 20 个域 = 审计登记表 = 探针探测集, 三处一处不落。"""
    mod = _load(AUDIT_PY, "r2_lock_audit_rework_under_test7")
    assert set(mod.DOMAINS) == set(ur._rlp.LOCK_DOMAINS)
    assert "LOCK_DOMAINS" in PATHS_PY.read_text(encoding="utf-8")
    assert len(ur._rlp.LOCK_DOMAINS) == 20