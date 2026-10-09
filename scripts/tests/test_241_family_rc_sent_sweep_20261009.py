# -*- coding: utf-8 -*-
"""#241 同族: 「用 rc 判 notify 是否真发出」的**全部**站点统一到 `notify_sent()`(2026-10-09)。

病灶(#240 F1 / #241 同根, 判据失真面穷举后)
  `scripts/notify.py` 的 `main()` **所有出口恒 return 0** —— 含通用路径「全部渠道未发出」
  (notify.py:2371)与 tier 分支 `defer_status='append_failed'`(notify.py:2190)。⇒ 子进程
  `returncode == 0` **完全不含送达告知力**: 渠道全挂也 rc=0。
  因此任何「按 rc 判 notify 是否真发出」的判据都是错的。本批统一的三处:
    ① `check_data_gap_alerts._notify`  → `run_alerts` 据其落 `state[key].last_fired=today`
       ⇒ 通知全失败当日被抑制 = **当天失报**;
    ② `sensenova-proxy-healthcheck._notify` → `main` 据其落 `fired=True` ⇒ 后续轮次抑制
       ⇒ **告警永不送达、永不重试**;
    ③ `overfit_monitor.send_notify` → 覆盖 `alerts[].sent` 观测标志(不丢告警, 误标误导排障)。
  修 = 三处全部改判 `scripts/notify_sent.py:notify_sent`(唯一实现, rc 不参与, fail-safe
  「判不出 ⇒ False ⇒ 下轮重试」), 与 `check_failed_units`(#240 F1)/`check_s06_freshness`
  (#241)共用同一判据。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub): 本文件全部用例
  **本次自测未产生任何真实外发** —— notify 子进程整体打桩(`subprocess.run` 替身, 根本不
  spawn)+ `ZeroOutboundTrap` 包裹; `test_00` 先证 trap 武装生效。

red-before-green(判别力证明): `test_05` 用**旧 rc 语义**(notify 恒 return 0 ⇒ 判 True,
等价 `lambda out: True`)跑同一负控场景, 复现「通知全失败却落签」的 bug。旧代码跑负控必 FAIL。

跑法: python3 -m pytest -q scripts/tests/test_241_family_rc_sent_sweep_20261009.py
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys
import types
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_data_gap_alerts as cdg  # noqa: E402
from notify_sent import notify_sent  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240)
_MIN_ASSERTIONS = 34
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


def _load_svh():
    """以独立模块名导入连字符脚本 `sensenova-proxy-healthcheck.py`(importlib, 无副作用:
    顶层仅常量 + 函数定义, 不 spawn/不 import notify 主体)。"""
    spec = importlib.util.spec_from_file_location(
        "svh_mod_241fam", SCRIPTS / "sensenova-proxy-healthcheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


svh = _load_svh()


# ── notify.py 通用路径(--severe 同)真实输出形态(逐字照 notify.py 打点行) ──
SUCCESS_GENERAL = "[notify] 汇总：已发出 email/feishu\n"
FAIL_GENERAL = "[notify] 汇总：全部渠道未发出（email/feishu）\n"


def _fake_run(output, rc=0, calls=None):
    """subprocess.run 替身: 返回给定输出, 绝不 spawn 真进程。calls 收集命令行。"""
    def _run(cmd, *a, **k):
        if calls is not None:
            calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr=output)
    return _run


def _load_overfit_send_notify(stub_run):
    """AST 抽取 `overfit_monitor.send_notify`(§18 L50 static-only: 不 import 业务模块,
    只把该函数体 exec 进隔离命名空间, 注入 subprocess 替身/notify_sent)。"""
    src = (SCRIPTS / "overfit_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "send_notify")
    code = compile(ast.Module(body=[fn], type_ignores=[]), "<overfit.send_notify>", "exec")
    ns = {"os": os, "sys": sys, "SCRIPT_DIR": str(SCRIPTS),
          "subprocess": types.SimpleNamespace(run=stub_run), "notify_sent": notify_sent}
    exec(code, ns)
    return ns["send_notify"]


# ══════════════════════ ⓪ 打桩生效自证(§18 L48) ══════════════════════
def test_00_zero_outbound_trap_armed():
    """先证 ZeroOutboundTrap 确已武装: 真触达出口即 raise + 计数(hits==1)。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("http://example.invalid/")  # noqa: S310 (打桩验证, 必抛)
    _chk(trap.hits == ["urllib.request.urlopen"], f"trap 应计数 1, 实得 {trap.hits}")


# ══════════════════════ ① 判据判别力(单元, 三处 wrapper) ══════════════════════
def test_01_sensenova_notify_criterion(monkeypatch, tmp_path):
    """sensenova `_notify`: rc 不参与, 只认输出真实路由结果; 全失败 ⇒ False。"""
    for out, exp, why in [
        (SUCCESS_GENERAL, True, "真发出"),
        (FAIL_GENERAL, False, "全部渠道未发出 ⇒ 不算发出"),
        ("", False, "无输出 ⇒ fail-safe False"),
    ]:
        monkeypatch.setattr(svh.subprocess, "run", _fake_run(out, rc=0))
        got = svh._notify(tmp_path, "s", "b", severe=True, dry_run=False)
        _chk(got is exp, f"sensenova {why}: 期望 {exp} 实得 {got}")
    # rc 不是判据: rc=1(崩溃)但输出含真发出过 → 仍 True(与 s06/cfu 同款: 只认输出)
    monkeypatch.setattr(svh.subprocess, "run", _fake_run(SUCCESS_GENERAL, rc=1))
    _chk(svh._notify(tmp_path, "s", "b", severe=False, dry_run=False) is True,
         "rc 不参与: 输出有真发出即 True")
    # dry-run 通用路径 notify.py 仍打「已发出」(各渠道 dry_run 模拟成功) ⇒ True(自测 code path 不退化)
    monkeypatch.setattr(svh.subprocess, "run", _fake_run(SUCCESS_GENERAL, rc=0))
    _chk(svh._notify(tmp_path, "s", "b", severe=True, dry_run=True) is True,
         "dry-run 通用路径应打已发出 ⇒ True")


def test_02_sensenova_main_negative_control_no_consign_and_retries(monkeypatch, tmp_path):
    """负控(必修): 告警全渠道失败 ⇒ **不得落 fired** ⇒ 下轮必须重试(解开抑制链)。"""
    calls: list = []
    monkeypatch.setattr(svh, "_one_round", lambda port: (False, ["[t] fail 1/3", "[t] fail 2/3", "[t] fail 3/3"]))
    monkeypatch.setattr(svh.subprocess, "run", _fake_run(FAIL_GENERAL, rc=0, calls=calls))
    monkeypatch.setattr(sys, "argv", ["sensenova-proxy-healthcheck.py", "--repo", str(tmp_path), "--port", "8899"])
    with ZeroOutboundTrap() as trap:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc1 = svh.main()
        _chk(rc1 == 0, f"main 应 rc 0(launchd 契约), 实得 {rc1}")
        _chk(len(calls) == 1, f"应尝试 notify 1 次, 实得 {len(calls)}")
        _chk(not (tmp_path / "data" / svh.STATE_PATH_NAME).exists(),
             "全渠道失败**不得**落 fired 状态")
        calls.clear()
        # 下轮同一异常: 因未落 fired ⇒ 必须**再次**尝试 notify(不吞真告警)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc2 = svh.main()
        _chk(rc2 == 0 and len(calls) == 1, f"未落 fired ⇒ 下轮必须重试, 实得 rc={rc2} n={len(calls)}")
        _chk(not (tmp_path / "data" / svh.STATE_PATH_NAME).exists(), "重试轮仍不得落 fired")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_03_sensenova_main_positive_control_consigns_and_suppresses(monkeypatch, tmp_path):
    """正控: 告警真发出 ⇒ 落 fired ⇒ 下轮同异常被抑制(不重发)。"""
    calls: list = []
    monkeypatch.setattr(svh, "_one_round", lambda port: (False, ["[t] fail"]))
    monkeypatch.setattr(svh.subprocess, "run", _fake_run(SUCCESS_GENERAL, rc=0, calls=calls))
    monkeypatch.setattr(sys, "argv", ["sensenova-proxy-healthcheck.py", "--repo", str(tmp_path), "--port", "8899"])
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    with ZeroOutboundTrap() as trap:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            svh.main()
        st = json.loads((tmp_path / "data" / svh.STATE_PATH_NAME).read_text(encoding="utf-8"))
        _chk(st.get("fired") is True and len(calls) == 1, f"真发出应落 fired, 实得 {st} n={len(calls)}")
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            svh.main()
        _chk(len(calls) == 0, f"已 fired ⇒ 抑制重发(0 次 notify), 实得 {len(calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_04_data_gap_run_alerts_negative_control_no_consign_and_retries(monkeypatch, tmp_path):
    """负控: check_data_gap_alerts.run_alerts notify 全失败 ⇒ 不落 state[key].last_fired
    ⇒ 次轮同 key 必须重发(不被当日 dedup 抑制)。"""
    calls: list = []
    monkeypatch.setattr(cdg.subprocess, "run", _fake_run(FAIL_GENERAL, rc=0, calls=calls))
    from datetime import datetime
    f = [cdg.Finding("data_gap:x", "warn", "X 标题", "X 明细")]
    with ZeroOutboundTrap() as trap:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cdg.run_alerts(tmp_path, f, dry_run=False, now=datetime(2026, 9, 1, 22, 35))
        st = cdg._load_json(tmp_path / "data" / "alerts" / "data_gap_alert_state.json", {})
        _chk(st.get("data_gap:x") is None, f"全失败不得落签, 实得 {st}")
        _chk(len(calls) == 1, f"应尝试 notify 1 次, 实得 {len(calls)}")
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cdg.run_alerts(tmp_path, f, dry_run=False, now=datetime(2026, 9, 1, 23, 0))
        _chk(len(calls) == 1, f"未落签 ⇒ 次轮必须重发, 实得 {len(calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_05_data_gap_run_alerts_positive_control_consigns_and_dedups(monkeypatch, tmp_path):
    """正控: notify 真发出 ⇒ 落 state[key].last_fired=today ⇒ 次轮同 key 被 dedup(不重发)。"""
    calls: list = []
    monkeypatch.setattr(cdg.subprocess, "run", _fake_run(SUCCESS_GENERAL, rc=0, calls=calls))
    from datetime import datetime
    f = [cdg.Finding("data_gap:y", "severe", "Y 标题", "Y 明细")]
    with ZeroOutboundTrap() as trap:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cdg.run_alerts(tmp_path, f, dry_run=False, now=datetime(2026, 9, 2, 22, 35))
        st = cdg._load_json(tmp_path / "data" / "alerts" / "data_gap_alert_state.json", {})
        _chk(st.get("data_gap:y", {}).get("last_fired") == "2026-09-02", f"真发出应落签, 实得 {st}")
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cdg.run_alerts(tmp_path, f, dry_run=False, now=datetime(2026, 9, 2, 23, 0))
        _chk(len(calls) == 0, f"同 key 当日已发 ⇒ dedup 抑制(0 次 notify), 实得 {len(calls)}")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_06_overfit_send_notify_criterion(monkeypatch):
    """overfit_monitor.send_notify 返回 (ok, err); ok 由 notify_sent 判, 不看 rc。"""
    for out, exp in [(SUCCESS_GENERAL, True), (FAIL_GENERAL, False), ("", False)]:
        fn = _load_overfit_send_notify(_fake_run(out, rc=0))
        ok, _err = fn("s", "b", "SEVERE", False, "overfit_x")
        _chk(ok is exp, f"overfit send_notify out={out!r}: 期望 {exp} 实得 {ok}")
    # rc 不参与
    fn = _load_overfit_send_notify(_fake_run(SUCCESS_GENERAL, rc=7))
    ok, _ = fn("s", "b", "WARN", False, None)
    _chk(ok is True, "rc 不参与: 输出含真发出即 True")


# ══════════════════════ ② 静态锁(判据落在 notify_sent, 不是 rc) ══════════════════════
def _assert_no_rc_criterion(fn_src, label):
    _chk("notify_sent(out)" in fn_src, f"{label} 判据应为 notify_sent(out)")
    _chk("returncode == 0" not in fn_src, f"{label} 不得用 returncode == 0 当 sent")
    _chk("if r.returncode != 0" not in fn_src, f"{label} 不得用 rc!=0 早退当 sent 判据")


def test_07_static_locks_all_three_sites():
    """三处源码: 判据 = notify_sent(唯一实现), 不再是 rc; 且都 from notify_sent import。"""
    _assert_no_rc_criterion(inspect.getsource(cdg._notify), "check_data_gap._notify")
    _assert_no_rc_criterion(inspect.getsource(svh._notify), "sensenova._notify")
    # overfit: AST 只取 send_notify 段(该脚本别处仍有 R2 上传的 returncode==0, 不算本判据)
    src = (SCRIPTS / "overfit_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "send_notify")
    _assert_no_rc_criterion(ast.get_source_segment(src, fn), "overfit.send_notify")
    for p, label in [(SCRIPTS / "check_data_gap_alerts.py", "cdg"),
                     (SCRIPTS / "sensenova-proxy-healthcheck.py", "svh"),
                     (SCRIPTS / "overfit_monitor.py", "overfit")]:
        _chk("from notify_sent import notify_sent" in p.read_text(encoding="utf-8"),
             f"{label} 应复用唯一实现 notify_sent")


# ══════════════════════ ③ red-before-green 判别力证据 ══════════════════════
def test_08_red_before_green_old_rc_semantics_would_consign(monkeypatch, tmp_path):
    """用**旧 rc 语义**(notify 恒 return 0 ⇒ 判 True, 等价 `lambda out: True`)跑 sensenova
    负控场景, 复现 bug: 全渠道失败却落 fired ⇒ 下轮被抑制 = 告警静默丢失。

    证明 test_02 有判别力: 判据从 rc 换成 notify_sent 才让 test_02 PASS。
    """
    monkeypatch.setattr(svh, "_one_round", lambda port: (False, ["[t] fail"]))
    monkeypatch.setattr(svh.subprocess, "run", _fake_run(FAIL_GENERAL, rc=0))
    monkeypatch.setattr(svh, "notify_sent", lambda out: True)  # 旧 rc 语义: rc 恒 0 ⇒ 恒 True
    monkeypatch.setattr(sys, "argv", ["sensenova-proxy-healthcheck.py", "--repo", str(tmp_path), "--port", "8899"])
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    with ZeroOutboundTrap() as trap:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            svh.main()
        st = json.loads((tmp_path / "data" / svh.STATE_PATH_NAME).read_text(encoding="utf-8"))
        _chk(st.get("fired") is True, "旧 rc 语义在全渠道失败时**会**落 fired —— 复现 #241 同族 bug")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_09_red_before_green_data_gap_old_rc_semantics_would_consign(monkeypatch, tmp_path):
    """同样以旧 rc 语义跑 check_data_gap run_alerts: 全失败却落 last_fired ⇒ 当日失报。"""
    monkeypatch.setattr(cdg.subprocess, "run", _fake_run(FAIL_GENERAL, rc=0))
    monkeypatch.setattr(cdg, "notify_sent", lambda out: True)  # 旧 rc 语义
    from datetime import datetime
    f = [cdg.Finding("data_gap:z", "warn", "Z 标题", "Z 明细")]
    with ZeroOutboundTrap() as trap:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            cdg.run_alerts(tmp_path, f, dry_run=False, now=datetime(2026, 9, 3, 22, 35))
        st = cdg._load_json(tmp_path / "data" / "alerts" / "data_gap_alert_state.json", {})
        _chk(st.get("data_gap:z", {}).get("last_fired") == "2026-09-03",
             "旧 rc 语义在全失败时**会**落签 —— 复现 #241 同族 bug(当日失报)")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_99_min_assertions():
    """§18 L49: 断言计数下限, 防收集/执行异常致假绿。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑似假绿)")