# -*- coding: utf-8 -*-
"""notify.py P2-A 同类(2026-11-05): tmp+replace 写路径保留原文件权限。

5 条写路径(_atomic_write_digest 已修除外)替换前未对 tmp 做 fchmod/chmod 对齐
目标权限: os.replace 用 tmp 的 inode/权限替换原文件, 普通 open/write_text 默认
0644(umask 022)、mkstemp 默认 0600, 会把原文件显式设的 0600/0640 等权限换掉
(mkstemp 0600 路径反向收紧, 其余放宽)。

修复: 抽共用 helper _chmod_like_target(tmp_path, target_path), target 存在则取
st_mode & 0o7777 对 tmp os.chmod, 不存在则不动(新文件走各路径默认权限); 5 条
路径 replace 前调用。不改各路径业务语义/默认新建权限。

5 条路径(逐条覆盖):
  ① _write_result_file(--result-file)
  ② _replace_latest(latest.md)
  ③ _write_state_obj(域状态 JSON)
  ④ _save_warning_dedup_state(mkstemp 0600 反向收紧)
  ⑤ _flush_digest_locked 末尾 ALERT_DIGEST_STATE_FILE 写(经 send 路径, 全程打桩)

零外发铁律(§18 L48): 全程 ZeroOutboundTrap + monkeypatch 渠道函数, 收尾断言零外发。
时敏铁律(L51): 不写死「今天」, day 从 datetime.now() 派生(与被测代码同源)。
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
from _zero_outbound import ZeroOutboundTrap  # noqa: E402


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.fixture
def stub_channels(monkeypatch):
    """打桩所有发送渠道(先打桩, 先证沙箱生效), 零真实外发。"""
    calls: list[str] = []

    def _fake(kind):
        def _f(*_a, **_k):
            calls.append(kind)
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))
    return calls


# ── ① _write_result_file ─────────────────────────────────────────────────────
def test_path1_write_result_file_preserves_mode(tmp_path, stub_channels):
    target = tmp_path / "result.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o600)
    assert _mode(target) == 0o600

    notify._reset_outcome()
    notify._mark_outcome("ok", "test")
    notify._write_result_file(str(target))

    assert target.read_text(encoding="utf-8") != "{}"  # 真写了新内容
    assert _mode(target) == 0o600, f"result.json 权限应保持 0600, 得 {oct(_mode(target))}"


# ── ② _replace_latest ────────────────────────────────────────────────────────
def test_path2_replace_latest_preserves_mode(tmp_path, monkeypatch, stub_channels):
    alerts = tmp_path / "alerts"
    alerts.mkdir()
    latest = alerts / "latest.md"
    latest.write_text("old", encoding="utf-8")
    os.chmod(latest, 0o640)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERTS_FILE", latest)

    notify._replace_latest("new content")

    assert latest.read_text(encoding="utf-8") == "new content"
    assert _mode(latest) == 0o640, f"latest.md 权限应保持 0640, 得 {oct(_mode(latest))}"


# ── ③ _write_state_obj ───────────────────────────────────────────────────────
def test_path3_write_state_obj_preserves_mode(tmp_path, stub_channels):
    target = tmp_path / "state.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o600)

    ok = notify._write_state_obj(target, {"k": "v"})

    assert ok is True
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": "v"}
    assert _mode(target) == 0o600, f"state 权限应保持 0600, 得 {oct(_mode(target))}"


def test_path3_write_state_obj_new_file_default_mode(tmp_path, stub_channels):
    """新建文件(目标不存在)→ 保持默认权限 0644, 不擅自改 0600。"""
    target = tmp_path / "fresh_state.json"
    assert not target.exists()

    notify._write_state_obj(target, {"k": "v"})

    assert _mode(target) == 0o644, f"新建应默认 0644, 得 {oct(_mode(target))}"


# ── ④ _save_warning_dedup_state (mkstemp 0600 反向收紧) ──────────────────────
def test_path4_warning_dedup_preserves_mode(tmp_path, monkeypatch, stub_channels):
    target = tmp_path / "warning_dedup.json"
    target.write_text("{}", encoding="utf-8")
    os.chmod(target, 0o644)  # 原 0644, mkstemp 默认 0600 会反向收紧
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", target)

    ok = notify._save_warning_dedup_state({"a": 1})

    assert ok is True
    assert json.loads(target.read_text(encoding="utf-8"))["a"] == 1
    assert _mode(target) == 0o644, f"dedup 权限应保持 0644(防 mkstemp 0600 反向收紧), 得 {oct(_mode(target))}"


def test_path4_warning_dedup_new_file_default_mode(tmp_path, monkeypatch, stub_channels):
    """新建(mkstemp 默认 0600)→ 目标不存在时保持新文件默认(mkstemp 0600), 不擅自放宽。"""
    target = tmp_path / "fresh_dedup.json"
    assert not target.exists()
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", target)

    notify._save_warning_dedup_state({"a": 1})

    # mkstemp 默认 0600; 目标不存在 → helper 不动 → 保持 0600(与改前一致, 不放宽)
    assert _mode(target) == 0o600, f"新建 mkstemp 应保持 0600, 得 {oct(_mode(target))}"


# ── ⑤ _flush_digest_locked 末尾 ALERT_DIGEST_STATE_FILE 写 ───────────────────
def test_path5_flush_digest_state_preserves_mode(tmp_path, monkeypatch, stub_channels):
    """经 send 路径触发的 ALERT_DIGEST_STATE_FILE 写: 原权限 0600 → 发送后写 state 保持 0600。

    全程 ZeroOutboundTrap + 渠道打桩; ALERT_DIGEST_HM 改 "00:00" 使时控门控常通
    (不写死「今天」, day 从 datetime.now() 派生, 与被测代码同源, 避 L51 时敏漂移)。
    """
    alerts = tmp_path / "alerts"
    alerts.mkdir()
    digest = alerts / "alert_digest.jsonl"
    lock = alerts / "alert_digest.flushlock"
    state = alerts / "alert_digest_state.json"
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", digest)
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", lock)
    monkeypatch.setattr(notify, "ALERT_DIGEST_STATE_FILE", state)
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")  # 时控门控常通, 不写死时间字面量

    # 预置 state 文件 0600
    state.write_text(json.dumps({"last_sent_day": "1990-01-01"}), encoding="utf-8")
    os.chmod(state, 0o600)
    assert _mode(state) == 0o600

    # 预置一条「今日」due 条目
    _today = datetime.now().strftime("%Y-%m-%d")
    entry = {"day": _today, "category": "test", "reason": "defer",
             "subject": "s", "body": "b", "source": "t", "dedup_key": "dk1"}
    digest.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")

    # send 桩: 返回 email 成功 → sent=True → 走到 state 写
    monkeypatch.setattr(notify, "send", lambda *a, **k: {"email": True, "telegram": False, "feishu": False})

    with ZeroOutboundTrap() as trap:
        # 持锁主体直接调(跳过 flush_digest 的锁获取, 锁本身不影响 state 写权限)
        notify._flush_digest_locked(dry_run=False)
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"

    st = json.loads(state.read_text(encoding="utf-8"))
    assert "last_sent_day" in st
    assert _mode(state) == 0o600, f"digest state 权限应保持 0600, 得 {oct(_mode(state))}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
