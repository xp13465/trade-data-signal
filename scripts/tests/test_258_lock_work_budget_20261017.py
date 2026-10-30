# -*- coding: utf-8 -*-
"""#258 拍板包二·P3(脚本侧)—— 「等锁不计入工作预算」机制 + 静态接线 + s06 耗时判据 自验
(2026-10-17)。

权威依据 = /tmp/258-e1-report.md §5(A1/A2/A3/C2/C3)+ 派单 /tmp/dispatch-pack2-p3.md。

本文件验证三件事:

  ① **机制层**(`scripts/with_lock.py` 新增 `--exec-timeout`):持锁**执行段**(工作段)预算,
     计时起点 = 真正拿到锁之后 ⇒ 排队等锁时长不计入工作预算(#258 核心口径, 与 #258 E1 在
     `upload_r2.py` 的 `R2_UPLOAD_LOCK_TIMEOUT` / `R2_UPLOAD_WORK_TIMEOUT` 同款)。
     用例:等锁不计预算 / 工作段超预算 rc=124 / 子进程组整组回收 / 未设=旧行为逐字不变 /
     参数校验退 2。
  ② **静态接线**:A1(`turnover_backfill.sh` 两个 R2 步)/ A2(`fund_nav_selfheal.sh` 重出步)
     是否真把两段预算接上、外层兜底是否严格大于「等锁 + 工作」(梯度不倒挂)。
  ③ **C2 不变量**:`schedule_monitor.sh` 的 `DUR_THRESHOLDS["s06_snapshot"]` 必须 > s06 合法
     最坏耗时(墙钟口径; #258 E1 后 = 两 R2 步各自「等锁 + shell 兜底」全量相加), 且不回落
     到把「合法长等锁」当异常的 900s —— 防 #258 误报复发。

零外发(§18 L48 / memory `notify-script-selftest-must-stub`):本文件**本次自测未产生任何真实
  外发**。子进程一律带 `WITH_LOCK_NOTIFY_DRY_RUN=1`(with_lock.py 的排队超时告警走 --dry-run,
  且本文件刻意不构造「排队超时」路径 ⇒ 连 dry-run 也不触发); 本进程内再套 `ZeroOutboundTrap`
  兜底真实网络/邮件出口。

跑法: python3 -m pytest -q scripts/tests/test_258_lock_work_budget_20261017.py
"""
from __future__ import annotations

import fcntl
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
WITH_LOCK = SCRIPTS / "with_lock.py"


def _chk(cond: bool, msg: str) -> None:
    assert cond, msg


def _env() -> dict:
    e = dict(os.environ)
    e["WITH_LOCK_NOTIFY_DRY_RUN"] = "1"   # with_lock 排队超时告警永不真发(双保险)
    return e


def _run_with_lock(args, timeout=60):
    """跑 with_lock.py, 返回 (rc, stdout, stderr, elapsed)。"""
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, str(WITH_LOCK), *args],
        capture_output=True, text=True, env=_env(), timeout=timeout,
    )
    return p.returncode, p.stdout, p.stderr, time.time() - t0


def _hold_lock_then_release(lockpath: str, seconds: float) -> threading.Timer:
    """在本进程持独占锁 seconds 秒(独立 open ⇒ 独立文件描述, flock 与子进程真冲突)。"""
    f = open(lockpath, "w")
    fcntl.flock(f, fcntl.LOCK_EX)

    def _release():
        try:
            fcntl.flock(f, fcntl.LOCK_UN)
        finally:
            f.close()

    t = threading.Timer(seconds, _release)
    t.start()
    return t


# ───────────────────────── ① 机制层: with_lock.py --exec-timeout ─────────────────────────

def test_wait_not_counted_into_work_budget():
    """等锁 3s(阻塞模式 --block-timeout 30) + 工作 1s(--exec-timeout 2) ⇒ rc=0。

    判别力: 总墙钟 ≈ 等锁(≥4s, 2s 粒度轮询)+ 工作 1s > 工作预算 2s —— 若旧口径(整段墙钟
    计进工作预算)会在此被杀 rc=124; 新口径必须 rc=0 且总耗时 ≥ 3s。
    """
    with tempfile.TemporaryDirectory() as d:
        lockpath = os.path.join(d, "l.lock")
        t = _hold_lock_then_release(lockpath, 3.0)
        try:
            rc, out, err, elapsed = _run_with_lock(
                ["--block-timeout", "30", "--exec-timeout", "2", lockpath, "/bin/sh", "-c", "sleep 1"])
        finally:
            t.cancel()
        _chk(rc == 0, f"等锁不应计入工作预算 ⇒ 应 rc=0, 实得 rc={rc} stderr={err}")
        _chk(elapsed >= 3.0, f"应真等过锁(≥3s), 实得 {elapsed:.1f}s(等锁没发生? 用例失效)")
        _chk("持锁执行段超" not in err, f"不应触发工作段预算, stderr={err}")


def test_work_over_budget_killed_124():
    """锁空闲, 工作 20s 但 --exec-timeout 2 ⇒ rc=124 + 明确文案(与 run_to/timeout 同码)。"""
    with tempfile.TemporaryDirectory() as d:
        lockpath = os.path.join(d, "l.lock")
        rc, out, err, elapsed = _run_with_lock(
            ["--exec-timeout", "2", lockpath, "/bin/sh", "-c", "sleep 20"])
        _chk(rc == 124, f"工作段超预算应 rc=124(同 shell timeout 码), 实得 rc={rc}")
        _chk("持锁执行段超" in err, f"应打印工作段超预算文案, stderr={err}")
        _chk(elapsed < 12, f"应在预算附近就返回(不等满 20s), 实得 {elapsed:.1f}s")


def test_child_process_group_reclaimed():
    """超时应**整组**回收(孙进程不死 = 残留后台进程, 会一直吃锁/吃 IO)。

    造真孙进程: 外层 sh → 内层 sh 循环写心跳文件。超时后心跳必须停(不涨)。
    """
    with tempfile.TemporaryDirectory() as d:
        lockpath = os.path.join(d, "l.lock")
        hb = os.path.join(d, "hb.txt")
        loop = os.path.join(d, "loop.sh")
        with open(loop, "w") as fh:
            fh.write(f'while :; do date +%s > "{hb}"; sleep 0.3; done\n')
        rc, out, err, elapsed = _run_with_lock(
            ["--exec-timeout", "2", lockpath, "/bin/sh", "-c", f"/bin/sh {loop} & wait"])
        _chk(rc == 124, f"应 rc=124, 实得 rc={rc}")
        _chk(os.path.exists(hb), "孙进程应已跑起来(用例前置不成立就没判别力)")
        m1 = os.path.getmtime(hb)
        time.sleep(2.5)
        m2 = os.path.getmtime(hb)
        _chk(m1 == m2, f"孙进程组应被整组回收, 但心跳仍在推进({m1} -> {m2}) = 残留进程")


def test_default_off_is_old_behavior():
    """未设 --exec-timeout ⇒ 旧行为逐字不变: rc 原样透传, 不新建会话/不加超时。"""
    with tempfile.TemporaryDirectory() as d:
        lockpath = os.path.join(d, "l.lock")
        rc0, _, _, _ = _run_with_lock([lockpath, "/bin/sh", "-c", "exit 0"])
        _chk(rc0 == 0, f"旧行为 rc 应透传 0, 实得 {rc0}")
        rc7, _, err7, _ = _run_with_lock([lockpath, "/bin/sh", "-c", "exit 7"])
        _chk(rc7 == 7, f"旧行为 rc 应透传 7(rc 判据口径不变), 实得 {rc7}")
        _chk("持锁执行段超" not in err7, "未设预算时不应有任何超时介入")


def test_exec_timeout_arg_validation():
    """参数校验: 非整数 / 负数 / 缺值 ⇒ exit 2(不静默降级成「没设预算」)。"""
    with tempfile.TemporaryDirectory() as d:
        lockpath = os.path.join(d, "l.lock")
        rc_bad, _, err_bad, _ = _run_with_lock(
            ["--exec-timeout", "abc", lockpath, "/bin/sh", "-c", "true"])
        _chk(rc_bad == 2 and "整数" in err_bad, f"非整数应 exit 2, 实得 rc={rc_bad} {err_bad}")
        rc_neg, _, err_neg, _ = _run_with_lock(
            ["--exec-timeout", "-1", lockpath, "/bin/sh", "-c", "true"])
        _chk(rc_neg == 2 and ">= 0" in err_neg, f"负数应 exit 2, 实得 rc={rc_neg} {err_neg}")
        rc_miss, _, _, _ = _run_with_lock(["--exec-timeout"])
        _chk(rc_miss == 2, f"缺值应 exit 2, 实得 {rc_miss}")


# ───────────────────────── ② 静态接线: A1 / A2 梯度不倒挂 ─────────────────────────

def _sh(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """去掉整行注释后的代码文本 —— 防把注释里「旧写法…」的历史引述误当现行接线。"""
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


def test_a1_turnover_two_budget_wiring():
    """A1: turnover_backfill.sh 两个 R2 步 = 两段预算 + 各自外层兜底(#364)。

    #364 起 intraday / data-large 各自独立工作预算 + 独立外层 run_to, 两步不再共用一个字面量。
    **数值不写死**(#364 二版 S1/S4 会调值): 从源码抽真实 `run_to <N>` 字面量与三个常量,
    按算式「外层 = 等锁 + 工作 + 60」核对 —— 改任一边漏另一边必红。
    """
    src = _sh("turnover_backfill.sh")
    code = _code_only(src)
    n_lock = code.count('R2_UPLOAD_LOCK_TIMEOUT="$R2_LOCK_WAIT_BUDGET"')
    n_work_large = code.count('R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET" ')
    n_work_intraday = code.count('R2_UPLOAD_WORK_TIMEOUT="$R2_WORK_BUDGET_INTRADAY" ')
    _chk(n_lock == 2, f"两个 R2 步都应传等锁预算(实得 {n_lock} 处)")
    _chk(n_work_large == 1, f"data-large 步应传工作预算 $R2_WORK_BUDGET(实得 {n_work_large} 处)")
    _chk(n_work_intraday == 1,
         f"intraday 步应传独立工作预算 $R2_WORK_BUDGET_INTRADAY(实得 {n_work_intraday} 处)")
    _chk('run_to 900 "$PY" scripts/upload_r2.py' not in code,
         "旧 900 整段口径应已从代码消失(否则等锁吃预算的病灶还在)")
    lock_wait = int(re.search(r'^R2_LOCK_WAIT_BUDGET=(\d+)', src, re.M).group(1))
    work = int(re.search(r'^R2_WORK_BUDGET=(\d+)', src, re.M).group(1))
    work_intraday = int(re.search(r'^R2_WORK_BUDGET_INTRADAY=(\d+)', src, re.M).group(1))
    for name, work_var, work_val in (("intraday", "R2_WORK_BUDGET_INTRADAY", work_intraday),
                                     ("data-large", "R2_WORK_BUDGET", work)):
        pat = (r'^\s*run_to (\d+) env R2_UPLOAD_LOCK_TIMEOUT="\$R2_LOCK_WAIT_BUDGET" '
               rf'R2_UPLOAD_WORK_TIMEOUT="\${work_var}"')
        lits = re.findall(pat, code, re.M)
        _chk(len(lits) == 1, f"{name} 应为恰好 1 处 run_to 兜底(实得 {len(lits)} 处)")
        lit = int(lits[0])
        _chk(lit > lock_wait + work_val,
             f"梯度倒挂: {name} 外层 {lit} 应严格 > 等锁 {lock_wait} + 工作 {work_val}")
        _chk(lit == lock_wait + work_val + 60,
             f"{name} 外层 {lit} != 等锁 {lock_wait} + 工作 {work_val} + 60(改一边漏另一边)")


def test_a2_selfheal_two_budget_wiring():
    """A2: fund_nav_selfheal.sh 重出步 = with_lock 两段预算 + 外层兜底 strict > 两者之和。"""
    src = _sh("fund_nav_selfheal.sh")
    code = _code_only(src)
    _chk('--exec-timeout "$TIMEOUT"' in code,
         "重出步应把工作段预算交给 with_lock(--exec-timeout)")
    _chk('regen_with_timeout "$TIMEOUT"' not in code,
         "旧写法(整段墙钟=TIMEOUT, 等锁计进预算)应已从代码消失")
    _chk('regen_with_timeout "$SHELL_LIMIT"' in code,
         "外层兜底应为 SHELL_LIMIT(= 等锁 + 工作 + 余量)")
    _chk('--block-timeout "$LOCK_WAIT_BUDGET"' in code,
         "等锁预算应改用常量(LOCK_WAIT_BUDGET, 不再是硬编码 300)")
    lock_wait = int(re.search(r'LOCK_WAIT_BUDGET="\$\{FUNDNAV_SELFHEAL_LOCK_WAIT:-(\d+)\}"', src).group(1))
    work = int(re.search(r'TIMEOUT="\$\{FUNDNAV_SELFHEAL_TIMEOUT:-(\d+)\}"', src).group(1))
    expr = re.search(r"^SHELL_LIMIT=\$\(\((.+)\)\)", src, re.M).group(1)
    _chk(re.fullmatch(r"[0-9A-Za-z_ +*()-]+", expr) is not None,
         f"SHELL_LIMIT 表达式含未知符号, 不敢求值: {expr}")
    val = eval(expr, {"__builtins__": {}}, {"LOCK_WAIT_BUDGET": lock_wait, "TIMEOUT": work})  # noqa: S307
    _chk(val > lock_wait + work,
         f"梯度倒挂: 外层兜底 {val} 应严格 > 等锁 {lock_wait} + 工作 {work}")
    _chk("notify" not in src,
         "本脚本刻意零 notify 依赖(test_fundnav_selfheal_dbday 同断言), 勿引入")


def test_c3_comment_rebased():
    """C3: r2_upload_async.sh 的停滞阈值依据不再绑 s06 的 run_to 字面量(注释口径订正)。

    判据 = 陈旧说法只许作为**历史引述**留在注释里(且同处留 #258 C3 订正痕迹), 代码/现行
    依据必须只谈「停滞阈值 > 内层 HTTP 超时 + 裕量」这条真不变量。
    """
    src = _sh("r2_upload_async.sh")
    for ln in src.splitlines():
        if "s06_snapshot.sh run_to 900" in ln:
            _chk(ln.lstrip().startswith("#"),
                 f"陈旧依据只应作为历史引述留在注释里, 实见非注释行: {ln}")
    _chk("#258 C3" in src, "应留 #258 C3 订正留痕(便于反查本口径)")
    _chk("R2_UPLOAD_HTTP_TIMEOUT" in src and "_http_to + 300" in src,
         "真正的判据(停滞阈值 > 内层 HTTP 超时 + 裕量)与自动抬升保护都应在位")


# ───────────────────────── ③ C2: s06 耗时判据不变量 ─────────────────────────

def _dur_thresholds() -> dict:
    """从 schedule_monitor.sh 真源码提取 DUR_THRESHOLDS(不抄副本 = 防第二实现漂移)。"""
    src = _sh("schedule_monitor.sh")
    block = re.search(r"^DUR_THRESHOLDS = \{(.*?)^\}", src, re.S | re.M).group(1)
    out = {}
    for k, v in re.findall(r'"([a-z_0-9]+)":\s*(\d+)', block):
        out[k] = int(v)
    _chk("s06_snapshot" in out, "DUR_THRESHOLDS 应含 s06_snapshot(改名/删除须同步本测试锚点)")
    return out


def _s06_inner_worst_secs() -> int:
    """s06_snapshot.sh 合法最坏(墙钟口径) = 各 run_to 字面量之和。

    #258 E1 后两个 R2 步的 shell 兜底字面量变 2760(内含等锁段 1800 + 工作段 900),
    故本和会自动跟到 6720; 若 E1 未合入则为旧的 3000 —— 两者都必须 < 判据阈值。
    """
    src = _sh("s06_snapshot.sh")
    parts = [int(x) for x in re.findall(r"^\s*run_to (\d+) ", src, re.M)]
    _chk(len(parts) >= 5, f"s06_snapshot.sh 的 run_to 步数异常({len(parts)}), 本测试锚点需同步")
    return sum(parts)


def test_c2_s06_threshold_not_wallclock_regression():
    """C2: 判据阈值必须 > 合法最坏耗时, 且不得回落到 900(合法长等锁 ⇒ 结构性误报)。"""
    th = _dur_thresholds()["s06_snapshot"]
    inner = _s06_inner_worst_secs()
    _chk(th > inner,
         f"s06_snapshot 阈值 {th}s 应 > 合法最坏(各 run_to 之和 {inner}s), 否则合法慢跑被误报")
    _chk(th >= 6720,
         f"s06_snapshot 阈值 {th}s < #258 E1 后合法最坏 6720s(两 R2 步: 各 1800 等锁 + 2760 兜底, "
         "加 gen/check/posrating 600) —— 回落即 #258 误报复发")
    # 口径留痕: 是否明显早于云上硬墙(< 7020)由注释交代, 墙是云上元数据(http 不在仓库可验),
    # 故此处只断言「留有与硬墙对比的口径说明」, 不比对具体墙值(墙抬升属 C1, 需用户授权)。
    src = _sh("schedule_monitor.sh")
    _chk("7020" in src, "应在注释里留与云上硬墙(7020)的对比依据(C1 配套, 便于复核)")


def test_no_outbound_guard_effective():
    """零外发双保险(§18 L48):
    ① 本进程: autouse 夹具把真实网络/邮件出口挂在陷阱上(hits 非空即炸)。
    ② 子进程: 本文件给所有子进程注入 `WITH_LOCK_NOTIFY_DRY_RUN=1` —— 此处静态证明该开关
       **真被 with_lock.py 读取**(不是设了个没人认的变量), 且本文件刻意不构造「排队超时」路径。
    """
    src = _sh("with_lock.py")
    _chk("WITH_LOCK_NOTIFY_DRY_RUN" in src and '"--dry-run"' in src,
         "with_lock.py 应真读 WITH_LOCK_NOTIFY_DRY_RUN 并把告警降级为 --dry-run(否则本文件的零外发声明不成立)")
    _chk(_env()["WITH_LOCK_NOTIFY_DRY_RUN"] == "1", "子进程环境应带 dry-run 开关")


@pytest.fixture(autouse=True)
def _no_outbound():
    """本进程内真实外发出口的陷阱(子进程另由 WITH_LOCK_NOTIFY_DRY_RUN 兜)。"""
    with ZeroOutboundTrap() as trap:
        yield trap
    assert trap.hits == [], f"零外发被破坏: {trap.hits}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))