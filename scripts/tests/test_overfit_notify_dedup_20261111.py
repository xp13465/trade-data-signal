# -*- coding: utf-8 -*-
"""过拟合预警「去重抑制被误判成发送失败 + 隔天一发」修复回归(2026-11-11)。

根因(逐条依据见 /tmp/notify-rca-20261111.md, 主控已验证):
  ① `overfit_monitor.send_notify` 用二值 `notify_sent(out)` 判结果, 而 notify.py 的 dedup
     抑制行(`[notify][dedup] suppress key=...`)既不含「已发出」也不含「全部渠道未发出」⇒
     notify_sent 返回 False ⇒ 调用方打成「发送失败」并把 suppress 原文写进
     `alerts[].notify_error`(线上数据产物可见);
  ② dedup 窗口写死 86400s(24h), 而本任务每日 21:40 启动、通知环节晚 55-75s 才到
     check_dedup ⇒ 每轮 age≈86388s(差 12s 不满 24h)⇒ 抑制; 抑制不落窗(update_dedup 仅
     发送成功后写)⇒ 下一轮 age≈48h 才发 = 隔天一发。

修复: send_notify 改三态(`notify_state`: sent/suppressed/failed), suppressed 不写
notify_error、不打印「发送失败」; 窗口常量 `NOTIFY_DEDUP_WINDOW_SECS = 82800`(23h)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):
  本文件所有用例的 notify 子进程一律**替身**(不 spawn), 且 autouse fixture 先把
  `subprocess.run` 换成「一调即 AssertionError」的陷阱、把 socket.connect 也设陷阱,
  收尾断言零命中; `test_stub_trap_is_armed` 先证明陷阱真的生效(判别力)。

时间口径: 被测 send_notify/deliver_alerts 内部**不取当前日期/时间**(无 today()/now()
  逻辑; 唯一时间量是 dedup 窗口常量), 故无「写死今天」风险; 窗口值用 82800 字面量断言。

跑法: python -m pytest -q scripts/tests/test_overfit_notify_dedup_20261111.py
"""
from __future__ import annotations

import ast
import os
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest

from notify_sent import notify_state

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts" / "overfit_monitor.py"
_REAL_RUN = subprocess.run

# 11-10 云上 overfit_monitor.json alerts[].notify_error 原文(RCA §二.2, 逐字)
REAL_20261110_SUPPRESS = (
    "[notify][dedup] suppress key=overfit_overfit_high last_alerted=2026-11-09 21:41:04 "
    "age=86388s < window=86400s, 不重发"
)
REAL_20261110_SUPPRESS_2 = (
    "[notify][dedup] suppress key=overfit_param_spike last_alerted=2026-11-09 21:41:10 "
    "age=86382s < window=86400s, 不重发"
)
SENT_OUTPUT = "[notify] 汇总: 已发出 email=true feishu=true"
FAILED_OUTPUT = "[notify] 汇总: 全部渠道未发出 email=false feishu=false"


def load_ns():
    """AST 只提取 send_notify / deliver_alerts + 窗口常量(不 import 主体, 防副作用)。"""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    wanted = {"send_notify", "deliver_alerts"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    const = [n for n in tree.body
             if isinstance(n, ast.Assign)
             and any(getattr(t, "id", "") == "NOTIFY_DEDUP_WINDOW_SECS" for t in n.targets)]
    assert len(nodes) == 2, f"send_notify/deliver_alerts 缺失: {[n.name for n in nodes]}"
    assert len(const) == 1, "NOTIFY_DEDUP_WINDOW_SECS 常量缺失"
    ns = {
        "os": os,
        "sys": sys,
        "subprocess": subprocess,
        "SCRIPT_DIR": str(ROOT / "scripts"),
        "notify_state": notify_state,
    }
    exec(compile(ast.Module(body=const + nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    """武装零外发陷阱; 用例可再用 monkeypatch 换成「返回替身输出」的假 run。"""
    hits = []

    def trap(*args, **kwargs):
        hits.append(("subprocess.run", args, kwargs))
        raise AssertionError("禁止真实外发: subprocess.run 被调用")

    def trap_connect(*args, **kwargs):
        hits.append(("socket.connect", args, kwargs))
        raise AssertionError("禁止真实外发: socket.connect 被调用")

    monkeypatch.setattr(subprocess, "run", trap)
    monkeypatch.setattr(socket.socket, "connect", trap_connect)
    yield hits
    assert hits == [], f"检测到真实外发尝试: {hits}"


def fake_run(record=None, stdout="", stderr="", raises=None):
    def _run(cmd, **kwargs):
        if record is not None:
            record.append((list(cmd), dict(kwargs)))
        if raises is not None:
            raise raises
        return types.SimpleNamespace(stdout=stdout, stderr=stderr, returncode=0)
    return _run


def alert(typ="overfit_high", level="SEVERE"):
    return {"type": typ, "level": level, "subject": "s", "body": "b"}


# ── 0. 打桩生效证明(判别力) ──────────────────────────────────────────────────
def test_stub_trap_is_armed(no_outbound):
    assert subprocess.run is not _REAL_RUN, "subprocess.run 未被替身替换"
    with pytest.raises(AssertionError, match="禁止真实外发"):
        subprocess.run(["true"])
    # 本用例是故意触陷阱证明其生效(判别力), 不算真实外发 ⇒ 清掉命中记录
    no_outbound.clear()


# ── 1. 真实 11-10 suppress 原文 → suppressed ─────────────────────────────────
@pytest.mark.parametrize("line", [REAL_20261110_SUPPRESS, REAL_20261110_SUPPRESS_2])
def test_real_20261110_suppress_output_is_suppressed(line):
    assert notify_state(line) == "suppressed"
    # 反向约束: 纯 suppress 行不得被当成 sent(否则抑制被当成功, 又会掩盖真问题)
    assert notify_state(line + "\n" + "[notify][dedup] 不重发") == "suppressed"


# ── 2. send_notify 三态映射 + 窗口参数 ───────────────────────────────────────
@pytest.mark.parametrize("stdout, expected", [
    (SENT_OUTPUT, "sent"),
    (REAL_20261110_SUPPRESS, "suppressed"),
    (FAILED_OUTPUT, "failed"),
    ("", "failed"),                      # 未知/空输出 ⇒ fail-safe failed
    ("随便一段无法判定的话", "failed"),
])
def test_send_notify_three_states(monkeypatch, stdout, expected):
    ns = load_ns()
    record = []
    monkeypatch.setattr(subprocess, "run", fake_run(record, stdout=stdout))
    state, err = ns["send_notify"]("s", "b", dedup_key="overfit_overfit_high")
    assert state == expected
    assert len(record) == 1, "必须走替身 subprocess, 不得 spawn 真进程"
    # 传给 notify.py 的窗口必须是 82800(23h), 不是 86400(24h)
    cmd = record[0][0]
    i = cmd.index("--dedup-window")
    assert cmd[i + 1] == "82800"
    assert "--dedup-key" in cmd and cmd[cmd.index("--dedup-key") + 1] == "overfit_overfit_high"


def test_dedup_window_constant_is_23h():
    ns = load_ns()
    assert ns["NOTIFY_DEDUP_WINDOW_SECS"] == 82800
    assert ns["NOTIFY_DEDUP_WINDOW_SECS"] < 86400
    # 关键余量: 实测 age≈86388s 必须 > 23h 窗口(否则仍被抑制), 同时低于 24h(说明取的是留余量值)
    assert 86388 > ns["NOTIFY_DEDUP_WINDOW_SECS"]


# ── 3. deliver_alerts 字段写回: 三态 + dry-run ───────────────────────────────
def test_real_11_10_suppress_through_deliver_alerts_sets_no_error(monkeypatch, capsys):
    ns = load_ns()
    monkeypatch.setattr(subprocess, "run", fake_run(stdout="", stderr=REAL_20261110_SUPPRESS))
    alerts = [alert()]
    ns["deliver_alerts"](alerts)
    a = alerts[0]
    assert a["notify_state"] == "suppressed"
    assert a["sent"] is False, "sent 只表示真实发出, 抑制不是 sent"
    assert a["notify_error"] is None, "抑制是成功且已知, 不得写 notify_error"
    out = capsys.readouterr().out
    assert "窗口内抑制(成功且已知" in out
    assert "发送失败" not in out


def test_failed_output_marks_notify_error(monkeypatch, capsys):
    ns = load_ns()
    monkeypatch.setattr(subprocess, "run", fake_run(stdout="", stderr=FAILED_OUTPUT))
    alerts = [alert("param_spike", "WARN")]
    ns["deliver_alerts"](alerts)
    a = alerts[0]
    assert a["notify_state"] == "failed"
    assert a["sent"] is False
    assert a["notify_error"] == FAILED_OUTPUT
    assert "发送失败" in capsys.readouterr().out


def test_sent_output_marks_sent_and_no_error(monkeypatch):
    ns = load_ns()
    monkeypatch.setattr(subprocess, "run", fake_run(stdout=SENT_OUTPUT))
    alerts = [alert()]
    ns["deliver_alerts"](alerts)
    a = alerts[0]
    assert a["sent"] is True
    assert a["notify_state"] == "sent"
    assert a["notify_error"] is None


def test_dry_run_never_calls_notify_and_marks_dry_run():
    ns = load_ns()
    calls = []
    ns["send_notify"] = lambda *a, **k: calls.append((a, k)) or ("sent", "")
    alerts = [alert()]
    ns["deliver_alerts"](alerts, dry_run=True)
    assert calls == [], "dry-run 不得调用 send_notify(更不得 spawn notify.py)"
    a = alerts[0]
    assert a["sent"] is False
    assert a["notify_state"] == "dry_run"
    assert a["notify_error"] == "dry_run"
    assert subprocess.run is not _REAL_RUN  # 陷阱仍在位(未被本用例触碰)


def test_subprocess_exception_maps_to_failed_and_writes_error(monkeypatch):
    ns = load_ns()
    monkeypatch.setattr(subprocess, "run",
                        fake_run(raises=subprocess.TimeoutExpired(cmd="notify.py", timeout=60)))
    alerts = [alert()]
    ns["deliver_alerts"](alerts)
    a = alerts[0]
    assert a["notify_state"] == "failed"
    assert a["sent"] is False
    assert "timed out" in (a["notify_error"] or "")


def test_source_no_longer_labels_suppress_as_failed():
    """源码形状守卫: send_notify 不得再退回二值 notify_sent, 失败标签只在 failed 分支。"""
    src = SOURCE.read_text(encoding="utf-8")
    assert "return notify_sent(out)" not in src
    assert "notify_state(out)" in src
    assert "NOTIFY_DEDUP_WINDOW_SECS = 82800" in src
