#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#184 `--dry-run` 真正零落盘自验 pytest（2026-10-07）。

病灶：`notify.write_alert()` 不收 `dry_run` 参数——CLI `--alert-issue` 配 `--dry-run`
仍会写真实 `data/alerts/latest.md`，与 `--dry-run` 自带契约「不真发」(notify.py L35)
及 `send(severe=True)` 的 `_mirror_severe`（`if severe and not dry_run`）相悖。
修复=把门控收在**唯一写入函数** `write_alert` 内（根因单点守卫，§6.5），5 个 CLI
调用点全部透传 `dry_run=args.dry_run`，未来新增调用点亦自动覆盖。

本文件（§18 L48 通知类脚本自测必须打桩）：
  - 所有用例在 tmp 目录内构造，绝不碰生产 `data/alerts/`；
  - **零外发哨兵**：patch 掉 `smtplib.SMTP_SSL` / `urllib.request.urlopen`，任何真实
    邮件/飞书/TG 尝试即 `RuntimeError` 响亮失败（非假绿）；
  - 实跑（非 dry-run）写盘路径用 `notify.send` 桩覆盖，验证写路径仍工作且零外发。

覆盖：
  1. write_alert(dry_run=True)           → 不写 latest.md（负控：改前会写）
  2. write_alert(dry_run=False / 缺省)   → 写 latest.md（写路径仍工作 / 向后兼容）
  3. CLI --alert-issue --dry-run         → 不写 latest.md + 零外发
  4. CLI --alert-issue（实跑，send 打桩）→ 写 latest.md + 零外发
  5. CLI --tier critical --alert-issue --dry-run → 不写 latest.md（覆盖 2180 调用点）
  6. 静态机检：源码内每个 write_alert( 调用点都透传 dry_run=（防未来调用点漏挂）

跑法：python3 -m pytest -q scripts/tests/test_184_notify_dryrun_gate_20261007.py
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
    """全部落 tmp + 零外发哨兵（autouse，任何用例都不许真外发/碰生产）。"""
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_FILE", tmp_path / "latest.md")
    monkeypatch.setattr(notify, "WARNING_BUFFER_FILE", tmp_path / "warning_buffer.jsonl")
    monkeypatch.setattr(notify, "INFO_LOG_FILE", tmp_path / "info_log.jsonl")
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", tmp_path / "warning_dedup_state.json")
    monkeypatch.setattr(notify, "DEDUP_FILE", tmp_path / "notify_dedup.json")
    # 零外发哨兵：真实发送链路任一处被触达即失败
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _boom)
    monkeypatch.setattr(notify.urllib.request, "urlopen", _boom)
    yield


# ───────────────── 1~2. write_alert 单元门控 ─────────────────
def test_write_alert_dry_run_does_not_write(tmp_path):
    """#184 核心：dry_run=True 绝不触碰 latest.md（负控：改前此处会创建文件）。"""
    latest = tmp_path / "latest.md"
    notify.write_alert("测试告警", "详情正文", log_path="/tmp/x.log", dry_run=True)
    assert not latest.exists(), "dry_run=True 不得创建 latest.md（#184 核心断言）"


def test_write_alert_default_and_false_write(tmp_path):
    """写路径仍工作：缺省 / dry_run=False 均正常落盘（向后兼容，5 调用点靠此）。"""
    latest = tmp_path / "latest.md"
    notify.write_alert("缺省写入", "body-默认")
    assert latest.exists() and "缺省写入" in latest.read_text(encoding="utf-8")
    latest.unlink()
    notify.write_alert("显式 False", "body-false", dry_run=False)
    assert latest.exists() and "显式 False" in latest.read_text(encoding="utf-8")


# ───────────────── 3. CLI dry-run 路径 ─────────────────
def test_cli_dry_run_alert_issue_no_latest_no_outbound(tmp_path):
    """CLI `--alert-issue X --dry-run`：不写 latest.md（零落盘），且轴心哨兵证明零外发。"""
    rc = notify.main(["subject", "body", "--alert-issue", "issue X", "--dry-run"])
    assert rc == 0
    assert not (tmp_path / "latest.md").exists(), \
        "--dry-run + --alert-issue 不得写 latest.md（#184）"


# ───────────────── 4. CLI 实跑写路径（send 打桩，零外发） ─────────────────
def test_cli_real_alert_issue_writes_latest_send_stubbed(tmp_path, monkeypatch):
    """实跑（无 --dry-run）：write_alert 正常写 latest.md；send 打桩保证零外发。"""
    monkeypatch.setattr(notify, "send",
                        lambda *a, **k: {"email": True, "telegram": False, "feishu": True})
    rc = notify.main(["subject", "body", "--alert-issue", "real issue"])
    assert rc == 0
    latest = tmp_path / "latest.md"
    assert latest.exists(), "实跑必须写 latest.md（写路径未被误伤）"
    assert "real issue" in latest.read_text(encoding="utf-8")


# ───────────────── 5. tier=critical 调用点 ─────────────────
def test_cli_tier_critical_dry_run_no_latest(tmp_path):
    """tier=critical + --alert-issue + --dry-run：仍不写 latest.md（覆盖 tier 分支调用点）。"""
    rc = notify.main(["subject", "body", "--tier", "critical",
                      "--alert-issue", "tier issue", "--dry-run"])
    assert rc == 0
    assert not (tmp_path / "latest.md").exists(), \
        "tier=critical 的 dry-run 亦不得写 latest.md"


# ───────────────── 6. 静态机检：全部调用点透传 dry_run ─────────────────
def test_all_write_alert_callers_pass_dry_run():
    """§23.2 修完整：机检源码内每个 write_alert(...) 调用点都带 dry_run=（防漏/防未来新增漏挂）。"""
    src = NOTIFY_SRC.read_text(encoding="utf-8")
    calls = []
    for m in re.finditer(r"write_alert\(", src):
        # 取调用括号内文本（贪婪到第一个 ')'，调用均为单层）
        seg = src[m.end():src.index(")", m.end())]
        calls.append(seg)
    # 排除函数定义自身（def write_alert(issue ...）——定义体不含 " args." 形式
    call_sites = [s for s in calls if "args.alert_issue" in s]
    assert len(call_sites) >= 5, f"应有 5 个 CLI 调用点，实得 {len(call_sites)}"
    missing = [s for s in call_sites if "dry_run=args.dry_run" not in s]
    assert not missing, f"以下 write_alert 调用点未透传 dry_run=args.dry_run：{missing}"