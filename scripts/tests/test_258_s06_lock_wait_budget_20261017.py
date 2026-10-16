# -*- coding: utf-8 -*-
"""#258 E1 自测: S06 快照 R2 步骤「等锁段 / 工作段」两预算各自独立计时(2026-10-17)。

背景(拍板包 #258;现场 = s06 退出码 124, 10-13 / 10-15 两天复发):
  旧写法 `run_to 900` 量的是「进程启动→结束」整段墙钟(**含排队等锁**)⇒ 撞上长持锁者时
  「等锁 870s + 工作 30s」即判 900s 超时: **等锁吃掉了工作预算**。
  E1 = 计时起点后移到「真正拿到锁之后」(工作预算只量工作耗时), 等锁段另有自己的预算。

本文件四条(全部零网络/零 R2 写):
  ① 核心不变量: 等锁时长 > 工作预算时, 工作预算的**计时起点仍在拿锁之后**(=预算完整可用)。
     尺度说明: 现场量级「等锁 870s > 工作预算 900s」在 CI 不可复现 ⇒ 按比例缩放到
     「等锁 3s > 工作预算 2s」, 要验的不变量同一条(旧实现会把 3s 算进 2s 预算 → 拿锁即超时)。
  ② 计时器到点真的杀: 子进程 arm 1s 预算后 sleep ⇒ rc=124(与 shell `timeout` 同码)+ 明确文案。
  ③ opt-in 默认关: 未设 env 时读数为 0 且不 arm(= 其余直调 upload_r2.py 的调用方零行为变化)。
  ④ 接线守护(静态读脚本文本): 两个 R2 步骤必须带两个预算 env; 旧病形态 `run_to 900 upload_r2`
     必须消失; shell 兜底字面量(梯度审计只认字面量)必须严格大于「等锁 + 工作」。

零外发自证(§18 L48/L50 精神): ①③ 只碰本地 flock 临时锁文件(不跑任何命令);
② 只 arm 计时器后 sleep(不跑命令, 不 import 采集链); ④ 只读文本。
"""
import fcntl
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO))

# upload_r2 顶层 load_env() 在无 .env(CI)时会 sys.exit(收集期崩); 临时 .env 垫片由
# conftest.py §④ 统一铺好, 本文件无需自建(同 test_239 先例)。
import upload_r2 as ur  # noqa: E402


def _hold_lock(path: Path):
    """同进程内以 LOCK_EX 持锁(flock 对同一文件的**不同 fd** 互相排斥, 可同进程模拟占用)。"""
    f = open(path, "w")
    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    return f


def test_work_budget_clock_starts_after_lock(tmp_path):
    """① 等锁 3s > 工作预算 2s ⇒ 工作预算计时起点仍落在拿锁之后(预算完整可用, 未被等锁吃掉)。

    拿锁过程放**子进程**(旧病复发时它会按设计被 2s 预算杀掉 rc=124) ⇒ 本用例得到的是
    干净断言失败而不是「pytest 被 os._exit 带走」, 便于定位。
    """
    import json

    lock = tmp_path / "held258.lock"
    holder = _hold_lock(lock)
    code = (
        f"import sys, time, json; sys.path.insert(0, {str(SCRIPTS)!r}); "
        "import upload_r2 as ur; t0 = time.time(); "
        "fd = ur.acquire_r2_upload_lock_with_budgets(); "
        "print(json.dumps({'armed': ur._WORK_BUDGET_ARMED_AT, 't0': t0, "
        "'interval': (ur._WORK_BUDGET_TIMER.interval if ur._WORK_BUDGET_TIMER else 0), "
        "'locked': fd is not None and fd is not ur._SKIP_R2_LOCKED}), flush=True); "
        "(ur._WORK_BUDGET_TIMER.cancel() if ur._WORK_BUDGET_TIMER else None)"
    )
    env = dict(os.environ)
    env["R2_UPLOAD_LOCK"] = str(lock)
    env["R2_UPLOAD_LOCK_TIMEOUT"] = "30"    # 等锁段预算(宽松, 只做护栏)
    env["R2_UPLOAD_WORK_TIMEOUT"] = "2"     # 工作段预算(严格, 比等锁窗口 3s 短)
    try:
        proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(3)                        # 等锁窗口: 已超过工作预算 2s, 但锁仍被占
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)   # 放锁 → 子进程应拿到锁并能跑工作阶段
        out, err = proc.communicate(timeout=60)
    finally:
        fcntl.flock(holder.fileno(), fcntl.LOCK_UN)
        holder.close()
    assert proc.returncode == 0, (
        f"子进程 rc={proc.returncode} —— 等锁 3s 期间就被判超时(工作预算把等锁算进去了 = #258 复发)\n"
        f"{err[-800:]}")
    info = json.loads(out.strip().splitlines()[-1])
    assert info["locked"] is True, f"拿锁失败, 用例未覆盖目标场景(out={out!r})"
    # 核心断言: 工作预算起算时刻在等锁之后(旧实现起算于进程启动 ⇒ delta≈0, 且已在 2s 被杀)
    armed_delta = info["armed"] - info["t0"]
    assert armed_delta >= 3.0, (
        f"工作段预算起算于拿锁之前(armed_delta={armed_delta:.2f}s < 等锁 3.0s) —— "
        f"等锁仍被计入工作预算 = #258 未修")
    assert info["interval"] == 2, "工作段预算数值未按 env 如实消费(计时口径接错)"


def test_work_budget_fires_with_124(monkeypatch):
    """② 工作段预算到点 ⇒ rc=124(与 shell `timeout` 同码)+ 文案; 计时起点 = arm 时刻。"""
    code = (
        f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); import upload_r2 as ur; "
        "ur._arm_work_budget(1); print('ARMED', flush=True); "
        "import time; time.sleep(60)"
    )
    env = dict(os.environ)
    env.pop("R2_UPLOAD_WORK_TIMEOUT", None)   # 直接传值, 不经 env
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, "-c", code], env=env,
                       capture_output=True, text=True, timeout=60)
    elapsed = time.monotonic() - t0
    assert p.returncode == 124, f"应 rc=124(timeout 同码), 实得 {p.returncode}\n{p.stderr[-800:]}"
    assert "ARMED" in p.stdout, "子进程未成功 arm(计时器可能根本没启动)"
    assert "工作阶段超" in p.stderr, f"缺超时文案\n{p.stderr[-800:]}"
    assert elapsed < 30, f"应当在 ~1s 被杀, 实耗 {elapsed:.1f}s"


def test_work_budget_optin_default_off(monkeypatch):
    """③ opt-in 默认关: 未设/空/非法值 ⇒ 0(不 arm); 其余调用方行为零变化。"""
    monkeypatch.delenv("R2_UPLOAD_WORK_TIMEOUT", raising=False)
    assert ur._R2_WORK_TIMEOUT_ENV == "R2_UPLOAD_WORK_TIMEOUT"
    assert ur._work_budget_secs() == 0
    assert ur._arm_work_budget(0) is None
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "")
    assert ur._work_budget_secs() == 0
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "abc")
    assert ur._work_budget_secs() == 0
    monkeypatch.setenv("R2_UPLOAD_WORK_TIMEOUT", "-5")
    assert ur._arm_work_budget(ur._work_budget_secs()) is None


def test_s06_chain_wiring_and_gradient():
    """④ 接线守护: 两个 R2 步骤带两个预算 env; 旧病形态消失; shell 兜底 > 等锁 + 工作。"""
    src = (SCRIPTS / "s06_snapshot.sh").read_text(encoding="utf-8")
    assert src.count('R2_UPLOAD_LOCK_TIMEOUT="$R2_LOCK_WAIT_BUDGET"') == 2, \
        "两个 R2 步骤(③ 快照 / ④b 首页快照目录)都要带等锁段预算"
    assert src.count('R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET"') == 2, \
        "两个 R2 步骤都要带工作段预算"
    assert 'run_to 900 "$PY" scripts/upload_r2.py' not in src, \
        "旧病形态(整段墙钟含等锁的 run_to 900)必须消失, 否则 #258 复发"
    wait = int(re.search(r"^R2_LOCK_WAIT_BUDGET=(\d+)", src, re.M).group(1))
    work = int(re.search(r"^R2_WORK_BUDGET=(\d+)", src, re.M).group(1))
    assert work == 900, f"工作段预算必须保持旧值 900(本单不许改总预算数值), 实得 {work}"
    # 只取**代码**(去注释)+ 拼接续行, 再抓「run_to <字面量> ... upload_r2.py」的兜底字面量
    code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines()).replace("\\\n", " ")
    backstops = [int(m) for m in re.findall(r"run_to\s+(\d+)[^\n]*upload_r2\.py", code)]
    assert len(backstops) == 2, f"两个 R2 步骤各需一个 shell 层兜底字面量(梯度审计只认字面量), 实得 {backstops}"
    for b in backstops:
        assert b > wait + work, f"shell 兜底 {b} <= 等锁 {wait} + 工作 {work} ⇒ 合法等锁会被 shell 先杀"