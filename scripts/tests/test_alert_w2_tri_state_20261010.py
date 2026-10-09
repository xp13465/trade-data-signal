# -*- coding: utf-8 -*-
"""W2(#241 Pattern B): 三个巡检站点「notify 是否真发出」判据 → 三态(notify_state) 的正/负控自验。

病灶(#240 F1 / #241 同根)
  `scripts/notify.py` 的 `main()` **13 个 CLI 分支恒 return 0** ⇒ 子进程 `returncode` 对
  「告警是否真发出」零判别力;且抑制路径**有 stderr 输出**(7 处)但旧判据(rc)读不到。
  三站点(check_monitor_heartbeat / nextday_gap_check / nextday_plan_generator)此前按 rc
  判 ⇒ 无法区分「真发出」与「被 dedup 抑制」(且全渠道失败也 rc=0)。
修 = 三态判据 `scripts/notify_sent.py:notify_state`(既有 notify_sent 一字不改, 存量 12 调用方零回归):
    sent       → 成功(不重试不报错)
    suppressed → 成功且已知(被 dedup 窗口抑制, 不重试不报错)
    failed/未知 → 保守(回非 0, 交包装层告警/重试), 沿用 #241「不吞真故障」

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub): 本文件全部用例
  **本次自测未产生任何真实外发** —— notify 子进程整体打桩(绝不 spawn)+ `ZeroOutboundTrap`
  包裹, `test_00` 先证 trap 武装生效、各用例收尾断言 `trap.hits == []`。

red-before-green(判别力证明): `test_40` 用**旧 rc 语义**(notify 恒 return 0 ⇒ 判成功,
等价 `notify_state = lambda out: "sent"`)跑同一负控场景, 复现「全渠道失败却被当成功」的 bug。

跑法: /Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
        scripts/tests/test_alert_w2_tri_state_20261010.py
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
from notify_sent import notify_state, notify_sent  # noqa: E402
import check_monitor_heartbeat as cmh  # noqa: E402  (轻量脚本: 仅 stdlib + notify_sent)

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49)
_MIN_ASSERTIONS = 20
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ── notify.py 真实输出形态(逐字照 notify.py 打点行) ──────────────────────────────
SENT_GENERAL = "[notify] 汇总：已发出 email/feishu\n"                       # notify.py:2359
FAILED_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"           # notify.py:2362
SUPPRESS_CMH = ("[notify][dedup] suppress key=schedule_monitor_heartbeat "
                "last_alerted=2026-10-10 00:00:00 age=30s < window=3600s, 不重发\n")  # notify.py:1272-1273


def _fake_run(output, rc=0, calls=None):
    """subprocess.run 替身: 返回给定输出, 绝不 spawn 真进程。calls 收集命令行。"""
    def _run(cmd, *a, **k):
        if calls is not None:
            calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=output)
    return _run


# ══════════════════════ ⓪ 打桩生效自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_armed():
    """先证 ZeroOutboundTrap 确已武装: 真触达出口即 raise + 计数(hits==1)。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.invalid/")  # noqa: S310 (打桩验证, 必抛)
    _chk(trap.hits == ["urllib.request.urlopen"], f"trap 应计数 1, 实得 {trap.hits}")


# ══════════════════════ ① notify_state 分类单元(含反向用例) ══════════════════════
def test_01_notify_state_classification():
    """三态分类: sent/suppressed/failed; 反向用例 = tier warning 的 deferred/suppressed 行判 sent。"""
    for out, exp, why in [
        (SENT_GENERAL, "sent", "通用路径已发出"),
        (FAILED_GENERAL, "failed", "全部渠道未发出"),
        ("", "failed", "空输出 ⇒ 保守 failed"),
        (SUPPRESS_CMH, "suppressed", "通用 check_dedup 抑制行"),
        ("[notify][tier=warning] dedup 窗口内 suppress key=k\n", "suppressed", "tier 窗口抑制"),
        ("[notify][r4] staticdata_backup_fail 21600s 窗口内已发, suppress\n", "suppressed", "R4"),
        ("[notify][r7] 升级档窗口内已发, suppress\n", "suppressed", "R7"),
        ("[notify][196] 升级档窗口内已发, suppress\n", "suppressed", "#196"),
        ("[notify][agent-done] suppress foo 5min 内已发过\n", "suppressed", "agent-done"),
        ("[notify][dedup] 同源抑制(窗口内第 3 次，已通知 1 次，4h 窗)：subj\n", "suppressed", "指纹层"),
        # —— 反向用例(必测): tier warning res dict 含 defer_status='suppressed' + 路由完成 + True ⇒ sent
        ("[notify][tier=warning] 路由完成：{'tier': 'warning', 'deferred': True, "
         "'defer_status': 'suppressed'}\n", "sent", "res dict 里 suppressed 不得误判抑制"),
        # —— 非抑制的同前缀行不得误判
        ("[notify][r4] staticdata_backup_fail 分级=info: 已追平\n", "failed", "r4 非抑制行"),
        ("[notify][r7] r2_consistency 连续失败分级=warning(1天): x\n", "failed", "r7 非抑制行"),
        ("[notify][r7] 升级档路由完成：{'email': False, 'telegram': False, 'feishu': False}\n",
         "failed", "r7 全失败路由完成"),
    ]:
        got = notify_state(out)
        _chk(got == exp, f"notify_state {why}: 期望 {exp} 实得 {got} (out={out!r})")
    # 既有 notify_sent 语义零回归(与 notify_state 的 sent 判据同源): 只读不改
    _chk(notify_sent(SENT_GENERAL) is True and notify_sent(FAILED_GENERAL) is False,
         "既有 notify_sent 语义保持(零回归)")


# ══════════════════════ ② check_monitor_heartbeat 三态 ══════════════════════
def _run_cmh(monkeypatch, captured, output, heartbeat_path):
    monkeypatch.setattr(subprocess, "run", _fake_run(output, rc=0, calls=captured))
    return cmh.main(["--heartbeat-path", str(heartbeat_path), "--stale-seconds", "1800",
                     "--repo", str(ROOT)])


def test_10_cmh_sent_rc0(tmp_path, monkeypatch):
    """正控: notify 真发出 ⇒ rc 0(不重试不报错)。"""
    captured = []
    with ZeroOutboundTrap() as trap:
        rc = _run_cmh(monkeypatch, captured, SENT_GENERAL, tmp_path / "nope.txt")
    _chk(rc == 0, f"sent 应 rc 0, 实得 {rc}")
    _chk(len(captured) == 1, "缺失心跳必须调 notify 一次")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_11_cmh_suppressed_rc0(tmp_path, monkeypatch):
    """suppressed 分类: notify 被 dedup 窗口抑制 ⇒ 成功且已知, rc 0。"""
    captured = []
    with ZeroOutboundTrap() as trap:
        rc = _run_cmh(monkeypatch, captured, SUPPRESS_CMH, tmp_path / "nope.txt")
    _chk(rc == 0, f"suppressed 应 rc 0, 实得 {rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_12_cmh_failed_rc2(tmp_path, monkeypatch):
    """负控: notify 全渠道失败(旧 rc 也=0, 无判别力) ⇒ 三态判 failed ⇒ rc 2(保守告警)。"""
    captured = []
    with ZeroOutboundTrap() as trap:
        rc = _run_cmh(monkeypatch, captured, FAILED_GENERAL, tmp_path / "nope.txt")
    _chk(rc == 2, f"failed 应 rc 2, 实得 {rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ══════════════════════ ③ nextday_gap_check 三态(AST 提取静态安全) ══════════════════════
def _load_gap_sync_run(stub_run):
    """AST 抽取 `nextday_gap_check._sync_r2_and_notify`(§18 L50 static-only: 不 import 业务
    模块, 只把该函数体 exec 进隔离命名空间, 注入 subprocess 替身/notify_state)。"""
    src = (SCRIPTS / "nextday_gap_check.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_sync_r2_and_notify")
    code = compile(ast.Module(body=[fn], type_ignores=[]), "<gap._sync_r2_and_notify>", "exec")
    ns = {"os": os, "PY": sys.executable, "SCRIPT_DIR": SCRIPTS, "REPO": SCRIPTS.parent,
          "subprocess": types.SimpleNamespace(run=stub_run),
          "notify_state": notify_state, "log": lambda *_a: None}
    exec(code, ns)
    return ns["_sync_r2_and_notify"]


def test_20_gap_sent_notify_rc0():
    """正控: 真发出 ⇒ notify_rc 0。"""
    fn = _load_gap_sync_run(_fake_run(SENT_GENERAL, rc=0))
    with ZeroOutboundTrap() as trap:
        _r2, notify_rc = fn([("000001", 0.25)], False, "20261010", no_r2=True)
    _chk(notify_rc == 0, f"sent ⇒ notify_rc 0, 实得 {notify_rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_21_gap_suppressed_notify_rc0():
    """suppressed: 被 dedup 窗口抑制 ⇒ 成功且已知 ⇒ notify_rc 0。"""
    fn = _load_gap_sync_run(_fake_run(SUPPRESS_CMH, rc=0))
    with ZeroOutboundTrap() as trap:
        _r2, notify_rc = fn([("000001", 0.25)], False, "20261010", no_r2=True)
    _chk(notify_rc == 0, f"suppressed ⇒ notify_rc 0, 实得 {notify_rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_22_gap_failed_notify_rc1():
    """负控: 全渠道失败 ⇒ notify_rc 1(旧 rc 语义会误判 0)。"""
    fn = _load_gap_sync_run(_fake_run(FAILED_GENERAL, rc=0))
    with ZeroOutboundTrap() as trap:
        _r2, notify_rc = fn([("000001", 0.25)], False, "20261010", no_r2=True)
    _chk(notify_rc == 1, f"failed ⇒ notify_rc 1, 实得 {notify_rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ══════════════════════ ④ nextday_plan_generator 三态(AST 提取 notify try 块) ══════════════════════
def _load_plan_notify_block(stub_run):
    """AST 抽取 nextday_plan_generator.main() 内「notify 三态」try 块并 exec(static-only)。
    返回可调用对象: 传入 notify_state 替身, 跑块后读 notify_rc。"""
    src = (SCRIPTS / "nextday_plan_generator.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    target = None
    for n in ast.walk(tree):
        if isinstance(n, ast.Try):
            seg = ast.get_source_segment(src, n) or ""
            if "notify_state(out)" in seg and "notify_rc = 1" in seg:
                target = n
                break
    assert target is not None, "未在 nextday_plan_generator.py 找到 notify 三态 try 块"
    code = compile(ast.Module(body=[target], type_ignores=[]), "<plan.notify_try>", "exec")

    def _run(notify_state_fn):
        ns = {"subprocess": types.SimpleNamespace(run=stub_run),
              "notify_state": notify_state_fn, "log": lambda *_a: None,
              "cmd": ["notify.py"], "notify_rc": 0}
        exec(code, ns)
        return ns["notify_rc"]
    return _run


def test_30_plan_sent_rc0():
    """正控: 真发出 ⇒ notify_rc 0。"""
    run = _load_plan_notify_block(_fake_run(SENT_GENERAL, rc=0))
    with ZeroOutboundTrap() as trap:
        rc = run(notify_state)
    _chk(rc == 0, f"sent ⇒ notify_rc 0, 实得 {rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_31_plan_suppressed_rc0():
    """suppressed: 被 dedup 窗口抑制 ⇒ notify_rc 0。"""
    run = _load_plan_notify_block(_fake_run(SUPPRESS_CMH, rc=0))
    with ZeroOutboundTrap() as trap:
        rc = run(notify_state)
    _chk(rc == 0, f"suppressed ⇒ notify_rc 0, 实得 {rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_32_plan_failed_rc1():
    """负控: 全渠道失败 ⇒ notify_rc 1。"""
    run = _load_plan_notify_block(_fake_run(FAILED_GENERAL, rc=0))
    with ZeroOutboundTrap() as trap:
        rc = run(notify_state)
    _chk(rc == 1, f"failed ⇒ notify_rc 1, 实得 {rc}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


# ══════════════════════ ⑤ red-before-green 判别力证据 ══════════════════════
def test_40_red_before_green_old_rc_semantics_would_pass_failed():
    """用**旧 rc 语义**(notify 恒 return 0 ⇒ 判成功, 等价 `notify_state = lambda out: "sent"`)
    跑 gap_check 负控场景, 复现 bug: 全渠道失败却被当成功 ⇒ notify_rc 0 ⇒ 掩盖真故障。
    证明 test_22 有判别力: 判据从 rc 换成 notify_state 才让负控暴露。"""
    # 旧语义 = 只看 rc(=0)⇒ 判成功; 用「恒 sent」的替身复现
    src = (SCRIPTS / "nextday_gap_check.py").read_text(encoding="utf-8")
    fn_old_src = ast.parse(src)
    # 直接以 notify_state 替身(恒 sent)复跑同一真实函数体
    ns_fn = next(n for n in fn_old_src.body
                 if isinstance(n, ast.FunctionDef) and n.name == "_sync_r2_and_notify")
    code = compile(ast.Module(body=[ns_fn], type_ignores=[]), "<gap.old>", "exec")
    with ZeroOutboundTrap() as trap:
        ns = {"os": os, "PY": sys.executable, "SCRIPT_DIR": SCRIPTS, "REPO": SCRIPTS.parent,
              "subprocess": types.SimpleNamespace(run=_fake_run(FAILED_GENERAL, rc=0)),
              "notify_state": lambda out: "sent",  # 旧 rc 语义
              "log": lambda *_a: None}
        exec(code, ns)
        _r2, notify_rc_old = ns["_sync_r2_and_notify"]([("000001", 0.25)], False,
                                                       "20261010", no_r2=True)
    _chk(notify_rc_old == 0,
         "旧 rc 语义在全渠道失败时**会**当成功(notify_rc 0) —— 复现 #241 Pattern B bug")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_50_static_lock_three_sites_use_tri_state():
    """静态锁: 三站点源码均复用 notify_state 三态判据(不再是 rc), 且都 from notify_sent import。"""
    for script, markers in [
        ("check_monitor_heartbeat.py",
         ['notify_state(out)', 'state in ("sent", "suppressed")']),
        ("nextday_gap_check.py",
         ['notify_state(out)', 'state not in ("sent", "suppressed")']),
        ("nextday_plan_generator.py",
         ['notify_state(out)', 'state not in ("sent", "suppressed")']),
    ]:
        src = (SCRIPTS / script).read_text(encoding="utf-8")
        for m in markers:
            _chk(m in src, f"{script} 应含三态判据标记 {m!r}")
        _chk("from notify_sent import notify_state" in src,
             f"{script} 应 from notify_sent import notify_state")


def test_99_min_assertions():
    """§18 L49: 断言计数下限, 防收集/执行异常致假绿。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")