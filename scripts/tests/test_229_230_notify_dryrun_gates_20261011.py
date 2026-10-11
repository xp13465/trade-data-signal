#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#229 / #230 notify.py `--dry-run` 补门控自验（2026-10-11, B2 低危欠账清理批）。

背景（与 #184 同族, #184 只收了 write_alert 一个写入点）：
  - #229：CLI `--tier info --dry-run` 仍写 `data/alerts/info_log.jsonl` —— `send_tiered`
    的 info 分支**未透传 dry_run**，`log_info` 无条件 `_append_jsonl`。
  - #230：CLI `--flush-warnings --dry-run` 仍 `mkdir data/alerts` + 建 **0 字节**
    `warning_buffer.flushlock`（`flush_warning_batch` 在 dry-run 下也 `open(...,"a+")`）。
    **同模式面（§23.3 举一反三）**：`flush_digest` 与 `flush_warning_batch` 逐字同型 ⇒
    CLI `--flush-digest --dry-run` 同样建 0 字节 `alert_digest.lock`（一并修 + 同型回归机检）。

修法（「唯一写入函数内单点守卫」#6.5 口径, 与 #184 write_alert 同法）：
  - #229：`log_info(..., dry_run=False)` 最前短路；`send_tiered` info 分支透传
    `dry_run=dry_run`（返回 `info_logged` 如实反映）。
  - #230：`flush_warning_batch` 在 `dry_run` 时跳过 `mkdir+open`，直接进锁内主体
    （dry-run 全路径只读 ⇒ 无需互斥锁）；`flush_digest` 同法同型补齐。

本文件遵守 §18 L48（通知类脚本自测必须打桩）：
  - 所有落盘目标（INFO_LOG_FILE / WARNING_BUFFER_FILE / WARNING_FLUSH_LOCK_FILE /
    ALERTS_DIR / DEDUP_FILE）一律 monkeypatch 到 `tmp_path`，绝不碰生产 `data/alerts/`；
  - **零外发哨兵** `_boom`：patch 掉 `smtplib.SMTP_SSL` / `urllib.request.urlopen`；
  - **先证哨兵生效**（`test_zero_outbound_sentinel_is_effective`）——若哨兵不生效，
    其余「零外发」断言即为假绿（§18 L48: 先证打桩判定生效再跑）。

跑法：python3 -m pytest -q scripts/tests/test_229_230_notify_dryrun_gates_20261011.py
"""
import re
from pathlib import Path

import pytest

import notify

SCRIPTS = Path(__file__).absolute().parent.parent
NOTIFY_SRC = SCRIPTS / "notify.py"


def _boom(*a, **k):  # 零外发哨兵
    raise RuntimeError("OUTBOUND BLOCKED: 自测产生真实外发（邮件/飞书/TG）")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """全部落 tmp + 零外发哨兵（autouse）。"""
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_FILE", tmp_path / "latest.md")
    monkeypatch.setattr(notify, "INFO_LOG_FILE", tmp_path / "info_log.jsonl")
    monkeypatch.setattr(notify, "WARNING_BUFFER_FILE", tmp_path / "warning_buffer.jsonl")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", tmp_path / "warning_buffer.flushlock")
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", tmp_path / "warning_dedup_state.json")
    monkeypatch.setattr(notify, "DEDUP_FILE", tmp_path / "notify_dedup.json")
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _boom)
    monkeypatch.setattr(notify.urllib.request, "urlopen", _boom)
    yield


# ───────────────── 0. 先证零外发哨兵生效（§18 L48） ─────────────────
def test_zero_outbound_sentinel_is_effective():
    """打桩判定生效自证：哨兵确实会在真实外发被调用时抛错（否则后面断言皆假绿）。"""
    with pytest.raises(RuntimeError, match="OUTBOUND BLOCKED"):
        notify.urllib.request.urlopen("https://example.invalid")
    with pytest.raises(RuntimeError, match="OUTBOUND BLOCKED"):
        notify.smtplib.SMTP_SSL("smtp.example.invalid", 465)


# ───────────────── #229 log_info 单元门控 ─────────────────
def test_229_log_info_dry_run_does_not_write(tmp_path):
    """#229 核心：log_info(dry_run=True) 绝不创建 info_log.jsonl，且返回 False。"""
    info = tmp_path / "info_log.jsonl"
    ok = notify.log_info("测试 info", "detail", dry_run=True)
    assert ok is False, "dry_run=True 应返回 False（未落盘）"
    assert not info.exists(), "dry_run=True 不得创建 info_log.jsonl（#229 核心断言）"


def test_229_log_info_real_writes(tmp_path):
    """写路径仍工作（向后兼容/负控）：dry_run=False 缺省正常落盘且返回 True。"""
    info = tmp_path / "info_log.jsonl"
    assert notify.log_info("实写 info", "d") is True
    assert info.exists() and "实写 info" in info.read_text(encoding="utf-8")
    info.unlink()
    assert notify.log_info("显式 False", "d", dry_run=False) is True
    assert info.exists()


def test_229_send_tiered_info_dry_run_info_logged_false(tmp_path):
    """send_tiered(info, dry_run=True) 透传：info_logged=False（dry-run 不落 dashboard）。"""
    res = notify.send_tiered("t info", "body", tier=notify.TIER_INFO, dry_run=True)
    assert res["info_logged"] is False
    assert not (tmp_path / "info_log.jsonl").exists()
    # 三级路由判据：info 档按 info_logged 判「已成功路由」
    assert notify._tier_send_ok(res, notify.TIER_INFO) is False


def test_229_send_tiered_info_real_logged_true(tmp_path):
    """send_tiered(info, dry_run=False) → info_logged=True（写路径未被误伤）。"""
    res = notify.send_tiered("t info real", "body", tier=notify.TIER_INFO)
    assert res["info_logged"] is True
    assert (tmp_path / "info_log.jsonl").exists()


# ───────────────── #229 CLI 路径 ─────────────────
def test_229_cli_tier_info_dry_run_no_info_log(tmp_path):
    """CLI `--tier info --dry-run`：不写 info_log.jsonl（零落盘）+ 哨兵证明零外发。"""
    rc = notify.main(["subject", "body", "--tier", "info", "--dry-run"])
    assert rc == 0
    assert not (tmp_path / "info_log.jsonl").exists(), \
        "--tier info --dry-run 不得写 info_log.jsonl（#229）"


# ───────────────── #230 flush_warning_batch 门控 ─────────────────
def test_230_flush_dry_run_no_flushlock_no_alertsdir(tmp_path, monkeypatch):
    """#230 核心：--flush-warnings --dry-run 既不建 flushlock，也不建 ALERTS_DIR。"""
    alerts_dir = tmp_path / "aler_absent_dir"          # 独立 ALERTS_DIR 断言未被 mkdir
    lock = tmp_path / "warning_buffer.flushlock"
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", lock)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts_dir)
    r = notify.flush_warning_batch(dry_run=True)
    assert isinstance(r, dict)
    assert not lock.exists(), "dry-run 不得留 0 字节 warning_buffer.flushlock（#230）"
    assert not alerts_dir.exists(), "dry-run 不得 mkdir ALERTS_DIR（#230）"


def test_230_flush_real_creates_lock(tmp_path, monkeypatch):
    """写路径仍工作（负控）：dry_run=False 正常走 mkdir+open 建 lock（渠道打桩零外发）。"""
    lock = tmp_path / "warning_buffer.flushlock"
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", lock)
    # buffer 不存在 → 主体读不到 → 返回 empty（仍须已建 lock，证明非 dry-run 走原路径）
    import unittest.mock as mock
    with mock.patch.object(notify, "send", lambda *a, **k: {}):
        r = notify.flush_warning_batch(dry_run=False)
    assert isinstance(r, dict)
    assert lock.exists(), "非 dry-run 必须走原 mkdir+open 建 lock 路径"


# ───────────────── #230 同模式面（§23.3）：flush_digest 逐字同型（--flush-digest --dry-run） ─────────────────
def test_230_digest_flush_dry_run_no_lock_no_alertsdir(tmp_path, monkeypatch):
    """#230 举一反三：`--flush-digest --dry-run` 同型病灶（digest lock 亦无条件 mkdir+open）。"""
    alerts_dir = tmp_path / "dg_absent_dir"
    lock = tmp_path / "alert_digest.lock"
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", lock)
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", tmp_path / "alert_digest.jsonl")
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts_dir)
    r = notify.flush_digest(dry_run=True)
    assert isinstance(r, dict)
    assert not lock.exists(), "dry-run 不得留 0 字节 alert_digest.lock（#230 同型）"
    assert not alerts_dir.exists(), "dry-run 不得 mkdir ALERTS_DIR（#230 同型）"


def test_230_digest_flush_real_creates_lock(tmp_path, monkeypatch):
    """写路径仍工作（负控）：flush_digest(dry_run=False) 正常建 digest lock。"""
    lock = tmp_path / "alert_digest.lock"
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", lock)
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", tmp_path / "alert_digest.jsonl")
    r = notify.flush_digest(dry_run=False)
    assert isinstance(r, dict)
    assert lock.exists(), "非 dry-run 必须走原 mkdir+open 建 digest lock"


def test_230_digest_cli_dry_run_no_lock(tmp_path, monkeypatch):
    """CLI `--flush-digest --dry-run`：零落盘（哨兵证明零外发）。"""
    lock = tmp_path / "alert_digest.lock"
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", lock)
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", tmp_path / "alert_digest.jsonl")
    rc = notify.main(["--flush-digest", "--dry-run"])
    assert rc == 0
    assert not lock.exists(), "--flush-digest --dry-run 不得留 alert_digest.lock"


# ───────────────── 静态机检（§23.2 修完整：单点守卫不靠人肉记得） ─────────────────
def test_static_log_info_has_dry_run_and_send_tiered_passes_it():
    """机检：log_info 签名含 dry_run；send_tiered info 分支透传 dry_run=dry_run。"""
    src = NOTIFY_SRC.read_text(encoding="utf-8")
    m = re.search(r"def log_info\(([^)]*)\)", src)
    assert m, "未找到 log_info 定义"
    assert "dry_run" in m.group(1), f"log_info 签名缺 dry_run 参数：{m.group(1)}"
    # info 分支透传
    assert re.search(r"log_info\(\s*subject,\s*body,\s*dry_run=dry_run\)", src), \
        "send_tiered info 分支未透传 dry_run=dry_run（#229 病灶复发）"


def test_static_flush_dry_run_short_circuits_before_lock():
    """机检：flush_warning_batch 在 dry_run 时于 mkdir/open 之前短路（#230 病灶复发防护）。"""
    src = NOTIFY_SRC.read_text(encoding="utf-8")
    seg = src[src.index("def flush_warning_batch("):src.index("def _flush_warning_batch_locked(")]
    dry_idx = seg.index("if dry_run:")
    mkdir_idx = seg.index("WARNING_FLUSH_LOCK_FILE.parent.mkdir(")
    assert dry_idx < mkdir_idx, \
        "flush_warning_batch 的 dry_run 短路必须在 mkdir 之前（否则 dry-run 仍建 lock）"


def test_static_digest_flush_dry_run_short_circuits_before_lock():
    """机检：flush_digest 在 dry_run 时于 mkdir/open 之前短路（#230 同型病灶复发防护）。"""
    src = NOTIFY_SRC.read_text(encoding="utf-8")
    seg = src[src.index("def flush_digest("):src.index("def _flush_digest_locked(")]
    dry_idx = seg.index("if dry_run:")
    mkdir_idx = seg.index("ALERT_DIGEST_LOCK_FILE.parent.mkdir(")
    assert dry_idx < mkdir_idx, \
        "flush_digest 的 dry_run 短路必须在 mkdir 之前（否则 --flush-digest --dry-run 仍建 lock）"