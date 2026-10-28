#!/usr/bin/env python3
"""按产物域分锁 + 锁等待梯度(2026-10-28)单测 —— 全部打桩, 零网络/零真实上传。

覆盖(§5.8 证据用例):
  ① env 解析: 合法域; 非法域回落全局 + WARN; 空=未声明
  ② 域锁路径派生(/tmp/trade_r2_upload_<domain>.lock)
  ③ 同域互斥 / 跨域并行(真实 flock, 锁文件全在 tmp_path)
  ④ 全局 SH 屏障: 未声明写者(全局 EX)挡住域写者; 域写者挡住未声明写者
  ⑤ skip-if-locked 在域锁被占时返回哨兵并释放自己拿到的锁(不泄漏屏障 fd)
  ⑥ data-files 小载荷通道(2026-10-23 A 方案)不被域改变
  ⑦ 源形状契约: 域 env 常量 / 未声明回落全局 EX / SH 屏障
  ⑧ 审计脚本正例 PASS + 反例(标记缺失)FAIL
  ⑨ s06 显式梯度: run_to 900 内 + 锁等待 600 < 900(源码字面量)
  ⑩ 异步包装层解析 --lock-domain/--lock-wait 并只注入子进程 env

零外发证明: 本文件不调用 cmd_* / subprocess 上传 / 不 import requests; 只用 os.open+flock 与源码断言。
"""
from __future__ import annotations

import fcntl
import importlib.util
import os
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
UR_PY = REPO / "scripts" / "upload_r2.py"
R2SH = REPO / "scripts" / "r2_upload_async.sh"
S06 = REPO / "scripts" / "s06_snapshot.sh"


def _load_ur():
    spec = importlib.util.spec_from_file_location("upload_r2_under_test", UR_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["upload_r2_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ur(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK", str(tmp_path / "trade_r2_upload.lock"))
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", str(tmp_path / "trade_r2_upload_small.lock"))
    monkeypatch.delenv("R2_UPLOAD_LOCK_DOMAIN", raising=False)
    mod = _load_ur()
    mod._BARRIER_FDS.clear()
    yield mod
    for fd in list(mod._BARRIER_FDS):
        mod._release_r2_upload_lock(fd)


# ① env 解析
def test_domain_env_valid(ur, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    assert ur._lock_domain() == "data"


def test_domain_env_invalid_falls_back_global_with_warn(ur, monkeypatch, capsys):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "Bad Domain/../x")
    assert ur._lock_domain() is None
    assert "回落全局锁" in capsys.readouterr().err


def test_domain_env_empty_means_undeclared(ur, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "  ")
    assert ur._lock_domain() is None


# ② 域锁路径派生
def test_domain_lock_path_derived(ur):
    base = ur._global_upload_lock_path()
    assert ur._domain_upload_lock_path("data") == base.with_name(f"{base.stem}_data{base.suffix}")
    assert str(ur._domain_upload_lock_path("data")).endswith("/trade_r2_upload_data.lock")


# ③ 同域互斥 + 跨域并行
def test_same_domain_serialized(ur, monkeypatch, capsys):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    fd = ur._acquire_r2_upload_lock(timeout=0)
    assert isinstance(fd, int)
    try:
        with pytest.raises(SystemExit) as ei:
            ur._acquire_r2_upload_lock(timeout=0)
        assert ei.value.code == 1
    finally:
        ur._release_r2_upload_lock(fd)
    assert "排队等待超" in capsys.readouterr().err


def test_cross_domain_parallel(ur, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "lab")
    fd1 = ur._acquire_r2_upload_lock(timeout=0)
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "index")
    fd2 = ur._acquire_r2_upload_lock(timeout=0)
    assert isinstance(fd1, int) and isinstance(fd2, int) and fd1 != fd2
    ur._release_r2_upload_lock(fd1)
    ur._release_r2_upload_lock(fd2)


# ④ 全局 SH 屏障双向
def test_domain_writer_blocks_undeclared_global_ex(ur, monkeypatch, capsys):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    fd = ur._acquire_r2_upload_lock(timeout=0)
    try:
        monkeypatch.delenv("R2_UPLOAD_LOCK_DOMAIN")
        with pytest.raises(SystemExit) as ei:
            ur._acquire_r2_upload_lock(timeout=0)
        assert ei.value.code == 1
    finally:
        ur._release_r2_upload_lock(fd)
    err = capsys.readouterr().err
    assert f"R2 上传锁 {ur._global_upload_lock_path()}" in err


def test_undeclared_global_ex_blocks_domain_writer(ur, monkeypatch, capsys):
    holder = open(ur._global_upload_lock_path(), "w")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
    try:
        monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
        with pytest.raises(SystemExit) as ei:
            ur._acquire_r2_upload_lock(timeout=0)
        assert ei.value.code == 1
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    assert "排队等待超" in capsys.readouterr().err
    assert not ur._BARRIER_FDS, "超时退出前必须释放残留 fd(不许泄漏屏障)"


# ⑤ skip-if-locked + 不泄漏
def test_skip_if_locked_domain_returns_sentinel_and_releases(ur, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    fd = ur._acquire_r2_upload_lock(timeout=0)
    try:
        monkeypatch.setenv("R2_UPLOAD_SKIP_RETRY_SECS", "0")
        got = ur._acquire_r2_upload_lock(timeout=0, skip_if_locked=True)
        assert got is ur._SKIP_R2_LOCKED
    finally:
        ur._release_r2_upload_lock(fd)
    # 释放后同域可再拿(证明 skip 分支没把域锁/屏障泄漏在本进程)
    fd2 = ur._acquire_r2_upload_lock(timeout=0)
    assert isinstance(fd2, int)
    ur._release_r2_upload_lock(fd2)


# ⑥ 小载荷通道不受域影响
def test_small_lane_ignores_domain(ur, monkeypatch, tmp_path):
    # static-site/data 在 worktree 里可能不存在(产物 gitignore) ⇒ 指到 tmp 目录, 不碰真数据。
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(ur, "STATIC_DIR", tmp_path)
    p = data_dir / "__lock_domain_probe__.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    target = ur._route_upload_lock("upload-data-files", [p])
    assert target == ur._small_upload_lock_path()
    fd = ur._acquire_lock_for_command("upload-data-files", ["__lock_domain_probe__.json"])
    assert isinstance(fd, int)
    os.close(fd)
    assert not ur._BARRIER_FDS, "小载荷通道不应建立域屏障"


# ⑦ 源形状契约
def test_source_contract_domain_shapes():
    s = UR_PY.read_text(encoding="utf-8")
    assert '_LOCK_DOMAIN_ENV = "R2_UPLOAD_LOCK_DOMAIN"' in s
    assert "_domain_upload_lock_path" in s
    assert "fcntl.LOCK_SH" in s, "全局 SH 屏障丢失(未声明写者挡不住域写者)"
    assert "lock_plan = [(lock_path, fcntl.LOCK_EX)]" in s, "未声明域回落全局 EX 丢失"
    assert '"R2_UPLOAD_LOCK_TIMEOUT", "7300"' in s, "默认锁等待语义被改(应保持 7300)"


# ⑧ 审计脚本正反例
def _load_audit():
    spec = importlib.util.spec_from_file_location(
        "r2_lock_audit_under_test", REPO / "scripts" / "r2_lock_gradient_audit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_current_tree_passes():
    mod = _load_audit()
    _rows, errs = mod.audit()
    assert errs == [], f"当前树审计应 PASS, 实得 {errs[:3]}"


def test_audit_detects_missing_declaration(monkeypatch):
    mod = _load_audit()
    monkeypatch.setattr(mod, "SITES", mod.SITES + [
        ("scripts/s06_snapshot.sh", "构造反例", "data", 600, 900,
         "trade-s06-snapshot.service", "绝不存在的标记字符串")])
    _rows, errs = mod.audit()
    assert any("构造反例" in e for e in errs), "标记缺失必须 FAIL(审计不能空转)"


def test_audit_detects_gradient_inversion(monkeypatch):
    mod = _load_audit()
    band = mod.SITES[0]
    bad = (band[0], "构造倒置", band[2], 99999, 100, band[5], band[6])
    monkeypatch.setattr(mod, "SITES", [bad])
    _rows, errs = mod.audit()
    assert any("梯度倒置" in e for e in errs), "锁等待 ≥ 内层必须 FAIL"


# ⑨ s06 梯度字面量
def test_s06_lock_wait_600_under_run_to_900():
    s = S06.read_text(encoding="utf-8")
    m = re.search(r"run_to 900 env R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=(\d+)", s)
    assert m, "s06 state 上传应显式声明域 + 锁等待"
    assert int(m.group(1)) == 600, "s06 锁等待须为 600(内层 900 的 2/3)"
    assert 600 < 900


# ⑩ 异步包装层: 参数剥离 + 只注入子进程
def test_async_wrapper_parses_lock_flags():
    s = R2SH.read_text(encoding="utf-8")
    assert 'if [ "${1:-}" = "--lock-domain" ]' in s
    assert 'if [ "${1:-}" = "--lock-wait" ]' in s
    assert '${_lock_domain:+R2_UPLOAD_LOCK_DOMAIN="$_lock_domain"}' in s
    assert '${_lock_wait:+R2_UPLOAD_LOCK_TIMEOUT="$_lock_wait"}' in s
    # 参数不能漏传给 upload_r2.py 当子命令(剥离在 launch 之前)
    assert s.index('"--lock-wait"') < s.index('"$REPO/scripts/upload_r2.py" "$@"')