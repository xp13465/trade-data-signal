# -*- coding: utf-8 -*-
"""§0.2 派单机检 hook 第 ③ 项「命令超时约束」机检(2026-10-07)。

被测对象: scripts/agent_dispatch_cron_reminder.py 的 main() —— PostToolUse(Agent) hook。
本测试**static-only**(§18 L50):只 import 该 hook 模块 + 喂 stdin JSON 调 main(),
不 source/exec 任何业务脚本,不产生任何外发(邮件/飞书/告警/R2),只往 tmp_path 写日志
(monkeypatch DISPATCH_LOG_PATH)。

真实 hook JSON 形态(线上实测):tool_input 含 subagent_type/isolation/prompt,无
run_in_background。故本文件样本字段集按该形态构造。

覆盖:
  a) implementer + worktree + 有进度文件路径,但 prompt 无 timeout ⇒ exit 2 且 stderr 含「③」
  b) prompt 含 timeout ⇒ exit 0 静默(stderr 空)
  c) 非 Agent 工具 ⇒ exit 0
  d) 坏 JSON ⇒ exit 0
  e) ③ 对所有 subagent_type 生效:reviewer(只读角色)+ 无 timeout ⇒ exit 2 含「③」
  f) timeout 大小写不敏感(Timeout/TIMEOUT)⇒ exit 0
  g) ①③ 同时缺失 ⇒ stderr 同时含「①」与「③」(编号收集=①③)
"""
from __future__ import annotations

import io
import json

import pytest

import agent_dispatch_cron_reminder as m

PROG = "/tmp/agent-progress-x.md"


def _run(monkeypatch, capsys, tmp_path, payload):
    """喂 stdin JSON 调 main(),返回 (returncode, stderr)。日志落 tmp_path 不污染 /tmp。"""
    monkeypatch.setattr(m, "DISPATCH_LOG_PATH", str(tmp_path / "hook.log"))
    if isinstance(payload, str):
        raw = payload  # 原样字符串(坏 JSON 用例)
    else:
        raw = json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    code = m.main()
    err = capsys.readouterr().err
    return code, err


def _agent_input(prompt, subagent_type="implementer", isolation="worktree"):
    return {
        "tool_name": "Agent",
        "tool_input": {
            "subagent_type": subagent_type,
            "isolation": isolation,
            "prompt": prompt,
        },
    }


def test_a_timeout_missing_red(monkeypatch, capsys, tmp_path):
    """a) 无 timeout 但其余齐备 ⇒ exit 2 + stderr 含 ③(负向探针必须能红)。"""
    prompt = f"实施任务:进度文件 {PROG},每步 echo。所有命令按规范执行。"
    code, err = _run(monkeypatch, capsys, tmp_path, _agent_input(prompt))
    assert code == 2
    assert "③" in err
    assert "timeout" in err


def test_b_timeout_present_green(monkeypatch, capsys, tmp_path):
    """b) prompt 含 timeout ⇒ exit 0 静默(stderr 空)。"""
    prompt = f"实施任务:进度文件 {PROG};所有 Bash 调用显式传 timeout(默认 120s 内也写)。"
    code, err = _run(monkeypatch, capsys, tmp_path, _agent_input(prompt))
    assert code == 0
    assert err == ""


def test_c_non_agent_tool_silent(monkeypatch, capsys, tmp_path):
    """c) 非 Agent 工具 ⇒ exit 0(不机检)。"""
    code, err = _run(monkeypatch, capsys, tmp_path, {"tool_name": "Bash", "tool_input": {}})
    assert code == 0
    assert err == ""


def test_d_bad_json_silent(monkeypatch, capsys, tmp_path):
    """d) 坏 JSON ⇒ exit 0。"""
    code, err = _run(monkeypatch, capsys, tmp_path, "{not valid json")
    assert code == 0
    assert err == ""


def test_e_readonly_role_also_checked(monkeypatch, capsys, tmp_path):
    """e) ③ 对所有 subagent_type 生效:reviewer + 无 timeout ⇒ exit 2 含 ③。"""
    prompt = f"只读核对任务:进度文件 {PROG}。"
    code, err = _run(
        monkeypatch, capsys, tmp_path, _agent_input(prompt, subagent_type="reviewer", isolation=None)
    )
    assert code == 2
    assert "③" in err


def test_f_timeout_case_insensitive(monkeypatch, capsys, tmp_path):
    """f) timeout 大小写不敏感(Timeout / TIMEOUT)⇒ exit 0。"""
    prompt = f"任务:进度文件 {PROG};Bash 命令必带 Timeout。"
    code, err = _run(monkeypatch, capsys, tmp_path, _agent_input(prompt))
    assert code == 0
    assert err == ""

    prompt2 = f"任务:进度文件 {PROG};TIMEOUT 约束见下。"
    code2, err2 = _run(monkeypatch, capsys, tmp_path, _agent_input(prompt2))
    assert code2 == 0
    assert err2 == ""


def test_g_missing_1_and_3_together(monkeypatch, capsys, tmp_path):
    """g) ①③ 同时缺失 ⇒ stderr 同时含 ① 与 ③,编号收集为 ①③。"""
    code, err = _run(monkeypatch, capsys, tmp_path, _agent_input("随手派个活,没写进度文件也没写超时。"))
    assert code == 2
    assert "①" in err
    assert "③" in err