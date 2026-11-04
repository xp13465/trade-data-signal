#!/usr/bin/env python3
"""F04(2026-11-04): 全局屏障锁 open 失败 → IndexError + fd 泄漏 根因修复单测。

全部打桩, 零网络/零真实上传/零真实 R2 对象。

覆盖(§5.8 证据用例):
  ① 第二把锁(全局屏障)open 抛 PermissionError → 无 IndexError、无 fd 泄漏、零上传调用,
    抛出原始 OSError(语义明确, fail-closed)
  ② 第一把锁(域锁)open 失败 → 保留既有 fail-open 行为(return None), 无 fd 泄漏
  ③ 正常双锁路径 → 域锁 + 屏障 + 心跳位 + 释放, 行为与改动前一致
  ④ fd 泄漏断言: 用 os.listdir('/proc/self/fd') 前后数量比对(不可用时回退 mock 层 opened/closed 计数)

零外发证明: 本文件不调用 cmd_* / subprocess 上传 / 不 import requests; 只 mock os.open 触发分支。
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
UR_PY = REPO / "scripts" / "upload_r2.py"


def _load_ur():
    spec = importlib.util.spec_from_file_location("upload_r2_under_test_f04", UR_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["upload_r2_under_test_f04"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fd_count() -> int | None:
    """返回当前进程 fd 数量; 非 Linux(/proc 不可用)返回 None。"""
    try:
        return len(os.listdir("/proc/self/fd"))
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None


@pytest.fixture()
def ur(tmp_path, monkeypatch):
    monkeypatch.setenv("R2_UPLOAD_LOCK", str(tmp_path / "trade_r2_upload.lock"))
    monkeypatch.setenv("R2_UPLOAD_SMALL_LOCK", str(tmp_path / "trade_r2_upload_small.lock"))
    monkeypatch.setenv("R2_UPLOAD_LOCK_DOMAIN", "data")
    mod = _load_ur()
    mod._BARRIER_FDS.clear()
    yield mod
    # 兜底清理: 残留 barrier fd 释放(防用例间串味)
    for fd in list(mod._BARRIER_FDS):
        try:
            mod._release_r2_upload_lock(fd)
        except Exception:
            pass


# ① 第二把锁(屏障)open 抛 PermissionError → 无 IndexError / 无 fd 泄漏 / 零上传 / 抛原始 OSError
def test_barrier_open_permission_error_no_index_error_no_leak(ur, monkeypatch):
    real_open = os.open
    barrier_path = str(ur._global_upload_lock_path())
    call_log = {"opens": []}

    def _fake_open(path, flags, mode=0o777):
        call_log["opens"].append(str(path))
        if str(path) == barrier_path:
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, "open", _fake_open)
    before = _fd_count()
    with pytest.raises(OSError) as ei:
        ur._acquire_r2_upload_lock(timeout=0)
    # 保留原始异常类型(PermissionError 是 OSError 子类), 不被吞成别的
    assert isinstance(ei.value, PermissionError)
    # 域锁 open 过、屏障 open 过(证明走到第二把)
    assert any(ur._domain_upload_lock_path("data").name in p for p in call_log["opens"])
    assert barrier_path in call_log["opens"]
    # 无 fd 泄漏: 进程 fd 数回落(若 /proc 可用)
    after = _fd_count()
    if before is not None and after is not None:
        assert after <= before, f"fd 泄漏: before={before} after={after}"
    # 屏障 fd 未登记(没建立屏障映射)
    assert not ur._BARRIER_FDS


# ② 第一把锁(域锁)open 失败 → 既有 fail-open(return None), 无 fd 泄漏
def test_first_lock_open_fail_returns_none_no_leak(ur, monkeypatch):
    domain_path = str(ur._domain_upload_lock_path("data"))

    def _fake_open(path, flags, mode=0o777):
        if str(path) == domain_path:
            raise PermissionError(13, "Permission denied", str(path))
        return os.open(path, flags, mode)  # 真实 open(不应被走到, 但留兜底)

    monkeypatch.setattr(os, "open", _fake_open)
    before = _fd_count()
    got = ur._acquire_r2_upload_lock(timeout=0)
    assert got is None, "第一把锁失败应 return None(fail-open 既有行为)"
    after = _fd_count()
    if before is not None and after is not None:
        assert after <= before, f"fd 泄漏: before={before} after={after}"
    assert not ur._BARRIER_FDS


# ③ 正常双锁路径 → 域锁 + 屏障 + 释放, 行为不变
def test_normal_dual_lock_path_unchanged(ur, monkeypatch):
    fd = ur._acquire_r2_upload_lock(timeout=0)
    try:
        assert isinstance(fd, int)
        # 域锁模式下建立了屏障映射
        assert fd in ur._BARRIER_FDS
        assert isinstance(ur._BARRIER_FDS[fd], int)
    finally:
        ur._release_r2_upload_lock(fd)
    # 释放后屏障映射清空
    assert not ur._BARRIER_FDS
    # 释放后可再拿(证明无残留锁)
    fd2 = ur._acquire_r2_upload_lock(timeout=0)
    assert isinstance(fd2, int)
    ur._release_r2_upload_lock(fd2)


# ④ 红先验锚点: 源码必须含 fail-closed raise(退回旧实现时本文件用例 ① 必红)
def test_source_contract_barrier_fail_closed_raise():
    s = UR_PY.read_text(encoding="utf-8")
    assert "raise" in s, "屏障锁 open 失败必须 raise(fail-closed), 不再 continue 退化"
    # fds 与 lock_plan 一一对应的等长保证(open 循环成功后 len 相等)
    assert "# fds 与 lock_plan 一一对应" in s, "锁计划与 fd 一一对应注释丢失"


# ⑤ mock 层 opened/closed 计数兜底(非 Linux 环境也跑得通的 fd 泄漏断言)
def test_barrier_open_fail_fd_balance_via_wrap(ur, monkeypatch):
    real_open = os.open
    real_close = os.close
    barrier_path = str(ur._global_upload_lock_path())
    opened = []
    closed = []

    def _fake_open(path, flags, mode=0o777):
        fd = real_open(path, flags, mode)
        opened.append(fd)
        return fd

    def _fake_close(fd):
        closed.append(fd)
        return real_close(fd)

    def _fake_open_fail_barrier(path, flags, mode=0o777):
        if str(path) == barrier_path:
            raise PermissionError(13, "Permission denied", str(path))
        fd = real_open(path, flags, mode)
        opened.append(fd)
        return fd

    # 先用 fail 版本触发屏障失败
    monkeypatch.setattr(os, "open", _fake_open_fail_barrier)
    monkeypatch.setattr(os, "close", _fake_close)
    with pytest.raises(OSError):
        ur._acquire_r2_upload_lock(timeout=0)
    # 域锁 fd 被打开过 → 必须全部被 close(失败路径释放, 无泄漏)
    assert set(opened).issubset(set(closed)), \
        f"fd 泄漏: opened={opened} closed={closed} 未配对关闭"
