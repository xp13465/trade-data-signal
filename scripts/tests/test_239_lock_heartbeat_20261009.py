# -*- coding: utf-8 -*-
"""#239 止血自测: 排队等锁心跳可见性(2026-10-09)。

背景(定因报告 docs/ops/etf-hist-forcefull-stall-rootcause-20261009.md §3-4):
  etf-hist 通道不是「force_full 卡死」, 而是通道子进程在 `upload_r2._acquire_r2_upload_lock`
  入口撞上长持锁者(upload-large-json 实测持锁 1155s)后, 进入**设计即静默**的排队循环
  (L3925-3951 原实现在排队分支除 time.sleep(2) 外零输出)。外层看门狗 r2_upload_async.sh L139
  只认「tmp_log 900s 无输出」⇒ 把健康等锁进程 kill。止血 = 排队等锁期间周期性打一行到 stderr,
  刷新 tmp_log mtime, 让看门狗能区分「在等锁」与「真卡死」。

本测试只验**可见性止血**四条(严格不动锁/sleep/超时语义):
  ① 等锁分支: 排队期出现周期性心跳(含超时 fail-closed 文案仍在)。
  ② 反证-锁空闲: 立即拿锁、零心跳(业务路径不变)。
  ③ 反证-skip 分支: --skip-if-locked 的 SKIPPED_LOCKED 语义不变, 且不打心跳(未动 #217① 语义)。
  ④ 常量守护: _R2_LOCK_HEARTBEAT_SECS 默认 30(远小于看门狗停滞阈值 900)。

零网络/零 R2 写: 全程只 import 模块 + 调拿锁纯函数(flock 本地文件), 不触任何上传路径。
"""
import fcntl
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

# upload_r2 顶层 load_env() 在无 .env(CI)时会 sys.exit(收集期崩); 临时 .env 垫片由
# conftest.py §④ 统一铺好(GIT_REPO 指向垫片), 本文件无需自建。
import upload_r2 as ur  # noqa: E402


def _hold_lock(path: Path):
    """在同一进程内以 LOCK_EX 持有锁(flock 对同一文件的**不同 fd** 互相排斥, 可同进程模拟占用)。"""
    f = open(path, "w")
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


def test_heartbeat_prints_during_queue_wait(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "held.lock"
    holder = _hold_lock(lock)
    try:
        monkeypatch.setenv("R2_UPLOAD_LOCK", str(lock))
        monkeypatch.setenv("R2_UPLOAD_LOCK_TIMEOUT", "3")
        monkeypatch.setattr(ur, "_R2_LOCK_HEARTBEAT_SECS", 1)  # 加速: 1s 心跳
        with pytest.raises(SystemExit):
            ur._acquire_r2_upload_lock()
        err = capsys.readouterr().err
        # ① 排队期出现心跳(每 ≥1s 一行)
        assert "等待 R2 上传锁" in err
        # 超时 fail-closed 文案仍在(未改超时语义)
        assert "排队等待超" in err
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_no_heartbeat_when_lock_free(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "free.lock"
    monkeypatch.setenv("R2_UPLOAD_LOCK", str(lock))
    monkeypatch.setattr(ur, "_R2_LOCK_HEARTBEAT_SECS", 1)
    fd = ur._acquire_r2_upload_lock(timeout=2)
    try:
        # ② 锁空闲: 立即拿锁成功, 零心跳输出(业务路径不变)
        assert fd is not None
        assert fd is not ur._SKIP_R2_LOCKED
        assert "等待 R2 上传锁" not in capsys.readouterr().err
    finally:
        os.close(fd)


def test_skip_if_locked_branch_unchanged(tmp_path, monkeypatch, capsys):
    lock = tmp_path / "held2.lock"
    holder = _hold_lock(lock)
    try:
        monkeypatch.setenv("R2_UPLOAD_LOCK", str(lock))
        monkeypatch.setenv("R2_UPLOAD_SKIP_RETRY_SECS", "0")   # 立即跳过(无有界重试窗口)
        monkeypatch.setattr(ur, "_R2_LOCK_HEARTBEAT_SECS", 1)
        sentinel = ur._acquire_r2_upload_lock(skip_if_locked=True)
        # ③ skip 分支语义不变: 返回哨兵 + 打印 SKIPPED_LOCKED, 且不掺入心跳
        assert sentinel is ur._SKIP_R2_LOCKED
        err = capsys.readouterr().err
        assert "SKIPPED_LOCKED" in err
        assert "等待 R2 上传锁" not in err
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()


def test_heartbeat_constant_default():
    # ④ 常量守护: 心跳间隔 30s, 必须远小于看门狗停滞阈值(默认 900s), 防未来被调大致误杀复发
    assert ur._R2_LOCK_HEARTBEAT_SECS == 30
    assert ur._R2_LOCK_HEARTBEAT_SECS * 10 < 900