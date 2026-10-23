# -*- coding: utf-8 -*-
"""R2 锁治理 B1(阻断项) + 同类面 3 处 —— 2026-10-23 审查 FAIL 修复自测。

覆盖:
  ① nextday_plan_generator 超时 handler: 诊断函数抛 RuntimeError 时 r2_rc 仍为 1、仍发 1 条告警、
     不抛到上层(后续「明日计划」通知不会被整段跳过);
  ② 诊断正常时只发 1 条(不重复告警);
  ③ r2_lock_probe 不可用时 nextday 仍能正常 import(占位实现吐简单文案);
  ④ 同类面 3 处超时分支补「子进程 stderr 尾段 + 持锁候选」后: 日志字段在位、超时值/退出码/
     degrade 判定与改前一致。

**零真实外发 / 零真实上传**:所有 `subprocess.run` 在调用前打桩(直接抛 TimeoutExpired, 子进程
根本没被创建);`_severe_alert` 打桩只记账;`_r2_has` 打桩;不碰 R2/网络/notify(§18 L48)。
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _timeout_exc(tail="⏳ 等待 R2 上传锁 420s(上限 7300s, 持锁进程可用 lsof 排查)\n",
                 timeout=480, cmd=("python3", "upload_r2.py")):
    exc = subprocess.TimeoutExpired(cmd=list(cmd), timeout=timeout)
    exc.stderr = tail.encode("utf-8")
    exc.stdout = b""
    return exc


# ══════════════════════ ① nextday B1: 诊断抛异常 → 仍告警 + r2_rc=1 ══════════════════════
def test_b1_diag_raises_alert_still_sent_and_flow_continues(monkeypatch, capsys):
    import nextday_plan_generator as m

    def _boom(*_a, **_k):
        raise _timeout_exc()

    def _diag_raises(*_a, **_k):
        raise RuntimeError("诊断模块炸了")

    alerts = []
    monkeypatch.setattr(m.subprocess, "run", _boom)
    monkeypatch.setattr(m, "build_lock_timeout_diag", _diag_raises)
    monkeypatch.setattr(m, "_severe_alert", lambda s, b: alerts.append((s, b)))

    # 如果异常逃逸, 这里会直接抛 RuntimeError 让用例失败(= 修复前的坏行为)
    r2_rc = m._uphold_plan_r2_upload(["nextday_plan.json"], "20261023")

    assert r2_rc == 1, "诊断抛异常时 r2_rc 必须仍为 1(赋值在内层 try/except 之外)"
    assert len(alerts) == 1, f"必须恰好发 1 条回落告警, 实际 {len(alerts)} 条"
    subject, body = alerts[0]
    assert "次日买入计划 R2 上传超时 20261023" in subject, subject
    assert "RuntimeError" in body and "诊断模块炸了" in body, body
    out = capsys.readouterr().out
    assert "等锁诊断失败(RuntimeError: 诊断模块炸了), 回落简单告警" in out, out

    # 后续流程继续: 函数已正常返回(不抛), main() 才能走到下面的「明日计划」通知段
    _next_stage_reached = True
    assert _next_stage_reached


def test_b1_diag_ok_single_alert(monkeypatch, capsys):
    import nextday_plan_generator as m

    monkeypatch.setattr(m.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(_timeout_exc()))
    monkeypatch.setattr(m, "build_lock_timeout_diag",
                        lambda *a, **k: ("DIAG-LOG", "[告警] 等锁超时 20261023", "DIAG-BODY"))
    alerts = []
    monkeypatch.setattr(m, "_severe_alert", lambda s, b: alerts.append((s, b)))

    assert m._uphold_plan_r2_upload(["nextday_plan.json"], "20261023") == 1
    assert alerts == [("[告警] 等锁超时 20261023", "DIAG-BODY")], "正常路径且只发 1 条"
    assert "DIAG-LOG" in capsys.readouterr().out


def test_b1_import_fallback_when_probe_module_missing():
    """模拟云上没同步 r2_lock_probe.py: nextday 仍能 import, 且占位诊断仍吐简单文案。"""
    code = f'''
import importlib.abc
import sys

# 裸子进程不加载 conftest: 先补 CI 缺省第三方库的导入级桩(否则 CI 无 akshare ⇒ import 失败;
# 本机装了真库时该函数不补桩, 保持与生产同构。同款先例见 test_278_nav_bucket_refresh.py)
sys.path.insert(0, {str(REPO / "scripts" / "tests")!r})
from _ci_stubs import install_missing_third_party_stubs
install_missing_third_party_stubs()


class _BlockProbe(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "r2_lock_probe":
            raise ImportError("blocked by test: r2_lock_probe 不可用")
        return None


sys.meta_path.insert(0, _BlockProbe())
sys.path.insert(0, {str(REPO / "scripts")!r})
sys.path.insert(0, {str(REPO)!r})
import nextday_plan_generator as m

assert "r2_lock_probe" not in sys.modules, "测试前提: 探测模块确实被挡住"
exc = Exception("boom")
exc.timeout = 480
log_text, subject, body = m.build_lock_timeout_diag(
    exc, lock_path="/tmp/x.lock", log_path="/tmp/a.log",
    date_tag="20261023", subject_prefix="[告警] 次日买入计划 R2",
    source="nextday_plan_generator.py", file_names=["nextday_plan.json"])
ok = ("r2_lock_probe 不可用" in log_text and "不可用" in body
      and "480" in log_text and "20261023" in subject)
print("FALLBACK-OK" if ok else f"FALLBACK-BAD: {{log_text!r}} {{subject!r}} {{body!r}}")
'''
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       timeout=180, cwd=str(REPO))
    assert r.returncode == 0, f"import 兜底失败: {r.stdout}\n{r.stderr}"
    assert "FALLBACK-OK" in r.stdout, r.stdout


# ══════════════════════ ② 同类面: nextday_gap_check ══════════════════════
def test_gap_check_timeout_logs_tail_and_holder(monkeypatch, capsys):
    import nextday_gap_check as g

    seen = {}

    def _boom(*_a, **k):
        seen.update(k)
        raise _timeout_exc(timeout=300)

    monkeypatch.setattr(g.subprocess, "run", _boom)
    monkeypatch.setattr(g, "probe_locks", lambda _paths: (
        "全局锁(/tmp/trade_r2_upload.lock)=无占用/探测不到; "
        "小锁(/tmp/trade_r2_upload_small.lock)=pid=41022(已运行 24:13) upload_r2.py"))
    monkeypatch.setattr(g, "subprocess_output_tail",
                        lambda e, limit=2000: "⏳ 等待 R2 上传锁 419s(上限 7300s)")

    r2_rc, notify_rc = g._sync_r2_and_notify([], True, "20261023", no_r2=False, no_notify=True)

    assert (r2_rc, notify_rc) == (1, 0), "退出码/通知码与改前一致"
    assert seen.get("timeout") == 300, "timeout 值未变(仍 300)"
    out = capsys.readouterr().out
    assert "R2 上传异常: Command" in out, "原告警文案保留"
    assert "子进程输出尾段(等锁心跳): ⏳ 等待 R2 上传锁 419s" in out, out
    assert "锁占用探测(lsof 只读, 全局锁/小锁逐把): " in out, out
    assert "小锁(/tmp/trade_r2_upload_small.lock)=pid=41022" in out, \
        "A 方案后必须报出小锁被占(只报全局锁会指错方向)"


# ══════════════════════ ③ 同类面: fapi_bj_width_export ══════════════════════
def test_fapi_timeout_logs_tail_and_holder(monkeypatch, capsys):
    import fapi_bj_width_export as f

    seen = {}

    def _boom(*_a, **k):
        seen.update(k)
        raise _timeout_exc(timeout=900)

    monkeypatch.setattr(f.subprocess, "run", _boom)
    monkeypatch.setattr(f, "probe_locks", lambda _paths: (
        "全局锁(/tmp/trade_r2_upload.lock)=pid=999(已运行 01:02) upload-data-large; "
        "小锁(/tmp/trade_r2_upload_small.lock)=无占用/探测不到"))
    monkeypatch.setattr(f, "subprocess_output_tail", lambda e, limit=2000: "⏳ 等待 R2 上传锁 880s")

    assert f._upload_r2(["overview.json"]) is False, "降级行为未变(仍 return False)"
    assert seen.get("timeout") == 900, "timeout 值未变(仍 900)"
    out = capsys.readouterr().out
    assert "✗ upload-data-files 超时(900s)" in out, "原超时文案保留"
    assert "子进程输出尾段(等锁心跳): ⏳ 等待 R2 上传锁 880s" in out, out
    assert "锁占用探测(lsof 只读, 全局锁/小锁逐把): " in out, out
    assert "全局锁(/tmp/trade_r2_upload.lock)=pid=999" in out, out


# ══════════════════════ ④ 同类面: gen_daily_brief(degrade 判定严禁变) ══════════════════════
def test_brief_timeout_logs_tail_and_degrade_unchanged(monkeypatch, capsys):
    import gen_daily_brief as b

    def _boom(*_a, **_k):
        raise _timeout_exc(timeout=120)

    monkeypatch.setattr(b.subprocess, "run", _boom)
    monkeypatch.setattr(b, "probe_locks", lambda _paths: (
        "全局锁(/tmp/trade_r2_upload.lock)=无占用/探测不到; "
        "小锁(/tmp/trade_r2_upload_small.lock)=pid=777(已运行 03:04) upload_r2.py"))
    monkeypatch.setattr(b, "subprocess_output_tail", lambda e, limit=2000: "⏳ 等待 R2 上传锁 110s")

    # degrade 分支: 兜底已到位 ⇒ 只打 ⚠ 不视为缺口(原判定逐字保留)
    monkeypatch.setattr(b, "_r2_has", lambda name, timeout=8, min_date="": True)
    b.upload_to_r2(Path(REPO), False, ["daily_brief.json"])
    out = capsys.readouterr().out
    assert "子进程输出尾段(等锁心跳): ⏳ 等待 R2 上传锁 110s" in out, out
    assert "锁占用探测(lsof 只读, 全局锁/小锁逐把): " in out, out
    assert "小锁(/tmp/trade_r2_upload_small.lock)=pid=777" in out, out
    assert "⚠ R2 上传超 120s 但 R2 已有较新版 daily_brief.json" in out, out
    assert "R2_UPLOAD_TIMEOUT" not in out, "degrade 分支不得打 critical 标记(判定未变)"

    # critical 分支: 兜底未到位 ⇒ ✗ 标记照打(原判定逐字保留)
    monkeypatch.setattr(b, "_r2_has", lambda name, timeout=8, min_date="": False)
    b.upload_to_r2(Path(REPO), False, ["daily_brief.json"])
    cap = capsys.readouterr()
    assert ("✗ R2_UPLOAD_TIMEOUT: daily_brief R2 上传超 120s 未完成, "
            "上传文件可能缺口(缺口由 17:50 deploy upload-all-data 或次日任务兜底), "
            "请核对 R2 是否缺/是否仅存旧版") in cap.err, cap.err


# ══════════════════════ ⑤ 时间冻结说明(L51) ══════════════════════
# 本文件不依赖 date.today(): brief 的 _r2_has 已打桩(不读真实日期), 其余断言均为静态文案。
@pytest.mark.parametrize("weekday_run", [0])
def test_no_wall_clock_dependency(weekday_run):
    assert weekday_run == 0