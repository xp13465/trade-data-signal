# -*- coding: utf-8 -*-
"""P2-01 回归(2026-11-05): _chmod_like_target 改 strict 后, latest.md 写失败
不阻塞通知发送主链路。

背景: _chmod_like_target 旧版 stat/chmod 双双 `except OSError: pass/return` 吞错,
随后调用方仍执行 tmp.replace → 原文件 mode 静默漂移(0600→0644)。P2-01 修复把
非 FileNotFoundError 的 OSError 改为上抛, 由调用方现有 best-effort except 接管
→ 跳过 replace → 旧 bytes+mode 保持 + 发送主链路不阻塞。

本文件验证「发送主链路不被 latest 写失败阻塞」这条期望 X→Y:
  X(修复前/吞错) = 无论 chmod 是否失败, send 都照发(latest mode 可能漂移)
  Y(修复后/strict) = _chmod_like_target 抛 OSError 时, _mirror_latest_entry 的
    best-effort except 接管 → 不抛、不 replace、旧 bytes+mode 保持; send() 仍把
    通知发到各渠道(渠道桩被调用、返回体含成功通道)。

零外发铁律(§18 L48): 全程 ZeroOutboundTrap + monkeypatch 渠道函数, 收尾断言零外发。
时敏铁律(L51): 不写死「今天」, day 从 datetime.now() 派生(与被测代码同源)。
不改 DRAFT 断言(test_codex_notify_closeout_regressions.py 原样保留)。
"""
import json
import os
import stat
import sys
import errno
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
def isolated(monkeypatch, tmp_path):
    """REPO 隔离 + 渠道打桩(先打桩先证沙箱生效), 零真实外发。"""
    for key in tuple(os.environ):
        if key.startswith(("ALERT_", "NOTIFY_", "FEISHU_", "EMAIL_", "TELEGRAM_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setenv("GIT_REPO", str(tmp_path))
    # 关闭预算/摘要 gate, 让 severe 直发(不被 L2 budget / digest 吞), 简化 send 路径
    monkeypatch.setenv("ALERT_BUDGET_DISABLE", "1")
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")

    alerts = tmp_path / "alerts"
    alerts.mkdir()
    latest = alerts / "latest.md"
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERTS_FILE", latest)

    sent: dict[str, bool] = {}

    def _fake_email(subject, body, *_a, **_k):
        sent["email"] = True
        return True

    def _fake_telegram(*_a, **_k):
        sent["telegram"] = True
        return True

    def _fake_feishu(*_a, **_k):
        sent["feishu"] = True
        return True

    monkeypatch.setattr(notify, "_send_email", _fake_email)
    monkeypatch.setattr(notify, "send_telegram", _fake_telegram)
    monkeypatch.setattr(notify, "send_feishu", _fake_feishu)
    return sent, latest, tmp_path


def test_mirror_latest_entry_not_blocked_by_chmod_fault(isolated, monkeypatch):
    """_chmod_like_target 抛 OSError → _mirror_latest_entry best-effort 接管:
    不抛异常 + 旧 latest.md bytes+mode 原样保持(replace 被跳过)。"""
    _sent, latest, _ = isolated
    old_bytes = b"## old latest content\n"
    latest.write_bytes(old_bytes)
    os.chmod(latest, 0o600)
    old_mode = _mode(latest)
    assert old_mode == 0o600

    def raising(_tmp, _target):
        raise OSError(errno.EPERM, "closeout chmod fault injected")

    monkeypatch.setattr(notify, "_chmod_like_target", raising)

    with ZeroOutboundTrap() as trap:
        # send() severe=True 的真实 latest 写路径 = _mirror_severe → _mirror_latest_entry
        # → _update_latest → _replace_latest → _chmod_like_target(抛) → 被
        # _mirror_latest_entry 的 try/except Exception 接管
        notify._mirror_latest_entry("severe", "[告警] P2-01 注入测试", "body-token",
                                    results={"email": True, "telegram": False,
                                             "feishu": True}, source="p2-01-test")
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"

    # 旧 bytes + 旧 mode 原样保持(replace 被跳过, 未漂移)
    assert latest.read_bytes() == old_bytes, "latest.md bytes 应保持旧内容(replace 被跳过)"
    assert _mode(latest) == old_mode, f"latest.md mode 应保持 {oct(old_mode)}, 得 {oct(_mode(latest))}"


def test_send_still_delivers_when_latest_write_fails(isolated, monkeypatch):
    """send(severe=True) 在 _chmod_like_target 抛 OSError 时仍把通知发到各渠道:
    渠道桩被调用 + 返回体含成功通道 + latest.md 旧 bytes/mode 保持。"""
    sent, latest, _ = isolated
    old_bytes = b"## pre-existing latest\n"
    latest.write_bytes(old_bytes)
    os.chmod(latest, 0o600)
    old_mode = _mode(latest)

    def raising(_tmp, _target):
        raise OSError(errno.EACCES, "closeout stat fault injected")

    monkeypatch.setattr(notify, "_chmod_like_target", raising)

    with ZeroOutboundTrap() as trap:
        result = notify.send("[告警] P2-01 send 路径测试", "notify-body-token",
                             severe=True, source="p2-01-send-test")
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"

    # 发送主链路未被 latest 写失败阻塞: 渠道桩被调用
    assert sent.get("email") is True, "email 渠道应仍发出(latest 写失败不阻塞发送)"
    # 返回体含至少一个成功通道
    assert any(result.get(ch) for ch in ("email", "telegram", "feishu")), \
        f"send 应返回至少一个成功通道, 得 {result}"
    # latest.md 旧 bytes + 旧 mode 保持(replace 被跳过, 未漂移)
    assert latest.read_bytes() == old_bytes, "latest.md bytes 应保持旧内容(replace 被跳过)"
    assert _mode(latest) == old_mode, f"latest.md mode 应保持 {oct(old_mode)}, 得 {oct(_mode(latest))}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
