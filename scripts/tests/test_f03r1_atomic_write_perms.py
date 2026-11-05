# -*- coding: utf-8 -*-
"""F03-R1 P2-A(2026-11-05): 原子替换丢显式文件权限回归测试。

背景: _atomic_write_digest 用 tmp + os.replace 原子替换原文件。os.replace 换的是
inode, tmp 文件在 umask 022 下建出 0644, 会把原文件显式设的 0600/0640 等权限换掉。
修复(P2-A): 替换前若目标已存在, os.stat 取原 mode, 对已打开 tmp fd 做 fchmod,
replace 后权限逐位保持; 目标不存在时保持新文件默认(0644, 与改前一致)。

零外发铁律(§18 L48): 本文件不触碰任何发送链路, 全程只测文件权限, 零真实外发。
时敏铁律(L51): 不写死日期字面量。
"""
import json
import os
import stat
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    digest = alerts / "alert_digest.jsonl"
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", digest)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "REPO", tmp_path)
    monkeypatch.setenv("REPO", str(tmp_path))
    return digest


def _entry(key="p_k"):
    return {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rid": f"d{os.getpid()}", "day": datetime.now().strftime("%Y-%m-%d"),
            "key": key, "category": "r2", "subject": "权限", "body": "",
            "from_prefix": None, "source": "test", "reason": "over_budget", "hits": 1}


# ── ① 0600 保持 0600 ──────────────────────────────────────────────
def test_mode_0600_preserved(sandbox, monkeypatch):
    """目标已存在且显式 0600 → replace 后仍 0600(不被 tmp 0644 覆盖)。"""
    sandbox.write_text("seed\n", encoding="utf-8")
    os.chmod(sandbox, 0o600)
    assert _mode(sandbox) == 0o600
    notify._atomic_write_digest([_entry()], [])
    assert _mode(sandbox) == 0o600, f"0600 应保持, 得 {oct(_mode(sandbox))}"


# ── ② 默认新文件(目标不存在)在 umask 022 下仍 0644 ────────────────
def test_mode_new_file_default_0644(sandbox, monkeypatch):
    """目标不存在 → 新文件走默认 umask(022 ⇒ 0644), 不擅自改 0600。"""
    old = os.umask(0o022)
    try:
        assert not sandbox.exists()
        notify._atomic_write_digest([_entry()], [])
        assert sandbox.exists()
        assert _mode(sandbox) == 0o644, f"新文件应 0644(umask 022), 得 {oct(_mode(sandbox))}"
    finally:
        os.umask(old)


# ── ③ 其他模式(0640)保持 ──────────────────────────────────────────
def test_mode_0640_preserved(sandbox, monkeypatch):
    """目标显式 0640 → replace 后仍 0640。"""
    sandbox.write_text("seed\n", encoding="utf-8")
    os.chmod(sandbox, 0o640)
    assert _mode(sandbox) == 0o640
    notify._atomic_write_digest([_entry()], [])
    assert _mode(sandbox) == 0o640, f"0640 应保持, 得 {oct(_mode(sandbox))}"


# ── ④ umask 设置与恢复不污染其它用例 ──────────────────────────────
def test_umask_isolation(sandbox, monkeypatch):
    """显式设 umask 007 → 新文件 0660; 恢复 umask 022 → 新文件 0644, 互不污染。"""
    old = os.umask(0o007)
    try:
        sandbox.write_text("seed\n", encoding="utf-8")
        os.chmod(sandbox, 0o660)
        notify._atomic_write_digest([_entry()], [])
        assert _mode(sandbox) == 0o660, f"umask 007 + 0660 应保持, 得 {oct(_mode(sandbox))}"
    finally:
        os.umask(old)
    # 恢复后新文件应回 0644
    other = sandbox.parent / "other.jsonl"
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", other)
    notify._atomic_write_digest([_entry()], [])
    assert _mode(other) == 0o644, f"恢复 umask 后新文件应 0644, 得 {oct(_mode(other))}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
