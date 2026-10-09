# -*- coding: utf-8 -*-
"""#241 同族 B 波补漏: `scripts/retry_failed_metrics.py`(2026-10-09)。

背景(续跑补漏)
  B 波首轮穷举口径不成立 —— 漏了本文件这个同族「先落签、后 fire-and-forget」站点:
    · 病灶 A: main() 达标分支旧序 = `counts.pop(mid, None)`(**先清零/落签**) **后**
      `_notify_repeat_failure(...)`(fire-and-forget, check 未判), 且 `_notify_repeat_failure`
      里 `subprocess.run(...)` 结果不判送达。通道全挂时: 计数已被清零暂歇 + 通知没发出
      ⇒ 达标告警丢失(下轮从 0 重新累计, 相当于「已发过一次」的状态已落签) = 永久失报同族。
    · 病灶 B(pre-existing bug, 非本波引入): `_notify_repeat_failure` 组 cmd 时用未定义名
      `subj`(变量实为 `subject`)⇒ 阈值告警路径必 NameError 并冒泡终止本轮。

修法(与 B 波 5 站点同统一判据)
  `_notify_repeat_failure` 返回 bool = `scripts/notify_sent.py:notify_sent` 判据(rc 不可信:
  notify.py main() 全出口恒 return 0); main() **送达才清零**, 未送达保留计数下轮重试。
  同时修 `subj` → `subject`。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub): 本文件全部用例
  **本次自测未产生任何真实外发** —— `subprocess.run` 被 rfm 局部替身接管(根本不 spawn
  notify.py)+ `ZeroOutboundTrap` 包裹; `test_00` 先证 trap 武装生效。

red-before-green(判别力): test_06 连跑两轮, 断言「通道全挂时每轮都重试通知」(旧代码
  第一轮即清零, 第二轮不再通知 ⇒ calls==1 ⇒ FAIL)。

跑法: python3 -m pytest -q scripts/tests/test_241_family_b_retry_metrics_20261009.py
"""
from __future__ import annotations

import subprocess
import sys
import types
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))          # scripts/tests (for _zero_outbound)
sys.path.insert(0, str(Path(__file__).absolute().parent.parent))   # scripts (for retry_failed_metrics / notify_sent)
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

import retry_failed_metrics as rfm  # noqa: E402
from notify_sent import notify_sent  # noqa: E402

# notify.py 通用路径真实输出形态(逐字照 notify.py 打点行)
SUCCESS_GENERAL = "[notify] 汇总：已发出 email/feishu\n"
FAIL_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49)
_MIN_ASSERTIONS = 22
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


def _shim_run(output, rc=0, calls=None):
    """rfm.subprocess 替身(模块属性级, 不污染全局 subprocess): 绝不 spawn 真进程。"""
    def _run(cmd, *a, **k):
        if calls is not None:
            calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=output)
    return types.SimpleNamespace(run=_run)


# ─────────────────────────────────────────────────────────────────────────────
def test_00_trap_armed():
    """先证 ZeroOutboundTrap 武装生效(§18 L48: 打桩必须先证有效)。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.com/should-not-send")
    _chk(len(trap.hits) == 1, f"trap 未武装: hits={trap.hits}")


def test_01_notify_repeat_failure_returns_true_on_success(monkeypatch):
    """送达 ⇒ 返回 True(同时证 B 已修: 旧代码组 cmd 用未定义 subj 必 NameError)。"""
    calls = []
    monkeypatch.setattr(rfm, "subprocess", _shim_run(SUCCESS_GENERAL, calls=calls))
    with ZeroOutboundTrap() as trap:
        sent = rfm._notify_repeat_failure("a_fund_main", 3, "20261009", "boom")
    _chk(sent is True, f"送达应返回 True, got {sent!r}")
    _chk(len(calls) == 1, f"应调用 notify.py 一次, got {len(calls)}")
    cmd = calls[0]
    _chk(any("notify.py" in str(x) for x in cmd), "cmd 未含 notify.py")
    _chk(any("连续 3 轮重采失败" in str(x) for x in cmd), "subject 未含正确文案(B 修复佐证)")
    _chk("a_fund_main" in " ".join(str(x) for x in cmd), "subject 未含 mid")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_02_notify_repeat_failure_returns_false_on_all_channels_down(monkeypatch):
    """全渠道未发出 ⇒ 返回 False(notify_sent 判据)。"""
    monkeypatch.setattr(rfm, "subprocess", _shim_run(FAIL_GENERAL))
    with ZeroOutboundTrap() as trap:
        sent = rfm._notify_repeat_failure("m1", 3, "20261009", "boom")
    _chk(sent is False, f"全渠道失败应返回 False, got {sent!r}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_03_notify_repeat_failure_returns_false_on_exception():
    """send 异常 ⇒ 返回 False(fail-safe: 判不出 ⇒ 不落签)。"""
    def _boom(*a, **k):
        raise RuntimeError("spawn failed")

    orig = rfm.subprocess
    rfm.subprocess = types.SimpleNamespace(run=_boom)
    try:
        with ZeroOutboundTrap() as trap:
            sent = rfm._notify_repeat_failure("m1", 3, "20261009", "boom")
    finally:
        rfm.subprocess = orig
    _chk(sent is False, f"异常应返回 False, got {sent!r}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_04_rc_nonzero_is_not_sent(monkeypatch):
    """rc!=0 但输出含已发出? notify_sent 以输出为准仍 True —— 这里验 rc!=0 且输出为失败 ⇒ False。"""
    monkeypatch.setattr(rfm, "subprocess", _shim_run(FAIL_GENERAL, rc=1))
    sent = rfm._notify_repeat_failure("m1", 3, "20261009", "boom")
    _chk(sent is False, f"rc=1+全失败输出应 False, got {sent!r}")


# ── main() 行为:送达门控(核心 A 修复的行为证据) ──────────────────────────────
def _patch_main(monkeypatch, notify_output, seed_counts):
    """打桩 main() 的全部外部依赖, 返回 (state, notify_calls)。

    state 跨轮持久: _save_counts 写回 state, 供第二轮 _load_counts 读到。
    """
    state = dict(seed_counts)
    notify_calls = []

    monkeypatch.setattr(rfm, "is_trading_day", lambda d: True)
    monkeypatch.setattr(rfm, "load_config", lambda: {"metrics": []})
    monkeypatch.setattr(rfm, "get_failed_metrics",
                        lambda date: [{"metric_id": "a_fund_main", "message": "boom"}])
    monkeypatch.setattr(rfm, "retry_metric", lambda mid, date, cfg: (False, "boom"))
    monkeypatch.setattr(rfm, "_load_counts", lambda: dict(state))

    def _save(c):
        state.clear()
        state.update(c)

    monkeypatch.setattr(rfm, "_save_counts", _save)
    monkeypatch.setattr(rfm, "subprocess", _shim_run(notify_output, calls=notify_calls))
    return state, notify_calls


def test_05_main_not_confirmed_sent_keeps_count_negative(monkeypatch):
    """通道全挂 ⇒ **不清零**(保留计数 >= 阈值), 负控:旧代码必 pop 到此 FAIL。"""
    state, notify_calls = _patch_main(monkeypatch, FAIL_GENERAL, {"a_fund_main": 2})
    with ZeroOutboundTrap() as trap:
        rc = rfm.main()
    _chk(rc == 0, f"main 应返回 0, got {rc}")
    _chk(state.get("a_fund_main") == 3,
         f"未送达必须保留计数(=3), got {state.get('a_fund_main')!r}(旧代码会 pop 掉)")
    _chk(len(notify_calls) == 1, f"应尝试通知一次, got {len(notify_calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_06_main_retries_every_round_while_down_red_before_green(monkeypatch):
    """通道全挂连跑两轮: 每轮都重试通知(旧代码第一轮清零 ⇒ 第二轮不再通知 ⇒ calls==1 FAIL)。"""
    state, notify_calls = _patch_main(monkeypatch, FAIL_GENERAL, {"a_fund_main": 2})
    rfm.main()   # 第 1 轮: n=3 达标, 未送达 ⇒ 保留
    rfm.main()   # 第 2 轮: _load_counts 读到 3 ⇒ n=4 达标, 再试
    _chk(len(notify_calls) == 2,
         f"通道全挂应每轮重试(=2 次), got {len(notify_calls)}(旧代码清零后只 1 次)")
    _chk(state.get("a_fund_main") >= 3, f"计数应保留, got {state.get('a_fund_main')!r}")


def test_07_main_confirmed_sent_resets_count_positive(monkeypatch):
    """送达 ⇒ 清零(暂歇, 防每轮轰炸)。"""
    state, notify_calls = _patch_main(monkeypatch, SUCCESS_GENERAL, {"a_fund_main": 2})
    with ZeroOutboundTrap() as trap:
        rfm.main()
    _chk("a_fund_main" not in state, f"送达后应清零, got {state!r}")
    _chk(len(notify_calls) == 1, f"应通知一次, got {len(notify_calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_08_main_below_threshold_no_notify(monkeypatch):
    """未达阈值(计数 1 → n=2 <3)不通知、累加。"""
    state, notify_calls = _patch_main(monkeypatch, SUCCESS_GENERAL, {"a_fund_main": 1})
    rfm.main()
    _chk(len(notify_calls) == 0, f"未达阈值不应通知, got {len(notify_calls)}")
    _chk(state.get("a_fund_main") == 2, f"应累加到 2, got {state.get('a_fund_main')!r}")


def test_09_static_lock_source_shape():
    """静态锁: 送达门控在源码中到位, 旧的无条件 pop / `subj` 已消失(§18 L49 防假绿)。"""
    src = Path(rfm.__file__).read_text(encoding="utf-8")
    _chk("if _notify_repeat_failure(mid, n, today, msg):" in src, "缺送达门控 if")
    _chk("counts.pop(mid, None)  # 送达后清零暂歇" in src, "缺送达后清零分支")
    _chk("counts[mid] = n  # 未送达: 保留计数, 下轮重试(不静默丢告警)" in src, "缺未送达保留分支")
    _chk("counts.pop(mid, None)  # 达标发一次后清零暂歇" not in src, "旧无条件 pop 仍在")
    _chk("notify_sent(out)" in src, "缺 notify_sent 判据")
    _chk("\n           subj, body," not in src, "旧 subj 未定义名仍在(片段)")
    _chk("subject, body," in src, "subject 未到位")


def test_99_min_assertions():
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}")