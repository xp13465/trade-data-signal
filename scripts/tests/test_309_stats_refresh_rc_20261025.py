# -*- coding: utf-8 -*-
"""#309 F1 回归测试: stats 刷新必须看返回码, 不许「进程崩了还打 OK」(2026-10-25)。

病灶: `scripts/schedule_monitor.sh` 里刷新 `gen_schedule_stats.py` 的 `subprocess.run(...)`
返回值被丢弃, 只在抛异常时置 `STATS_REFRESH_OK = False`。而 gen 脚本顶层没有 try/except,
任何未捕获异常 → 进程退出码 1 → `subprocess.run` **不 raise** → 旧代码仍判刷新成功 →
结论行照打「OK 所有任务按计划执行」(残余假 OK), 且 gen 持续崩溃没有任何告警。

取用方式: 从 `schedule_monitor.sh` 的 python heredoc **ast 提取**「STATS_REFRESH_OK 赋值 +
紧随其后的 try 刷新块」后 exec(不复制实现, 防两份实现静默漂移), 并用 stub 的
`subprocess.run` / `sys` 注入返回值 —— 全程 static-only: 不跑业务脚本, 不发任何通知。

反向对照(判别力自证): 把生产代码里的 `if _stats_refresh.returncode != 0:` 判断注释掉 →
`test_nonzero_rc_marks_refresh_failed` 与 `test_nonzero_rc_conclusion_never_says_ok` 必红;
还原 → 绿。
"""
import ast
import io
import sys
import types
from pathlib import Path

import pytest

from _monitor_conclusion_309 import conclusion as _conclusion
from _monitor_conclusion_309 import heredoc_source

REPO = Path(__file__).absolute().parent.parent.parent


def _refresh_nodes():
    """定位「STATS_REFRESH_OK = True + 紧随其后的 try 刷新块」两个顶层语句。"""
    src = heredoc_source()
    tree = ast.parse(src)
    for i, node in enumerate(tree.body):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "STATS_REFRESH_OK" not in targets:
            continue
        nxt = tree.body[i + 1] if i + 1 < len(tree.body) else None
        assert isinstance(nxt, ast.Try), (
            "STATS_REFRESH_OK 赋值后面不是 try 刷新块 —— 生产代码被改了? 本测试锚点需同步"
        )
        try_src = ast.get_source_segment(src, nxt)
        assert "gen_schedule_stats" in try_src, (
            "STATS_REFRESH_OK 后面的 try 块没刷新 gen_schedule_stats —— 锚点错位"
        )
        return ast.get_source_segment(src, node), try_src
    raise AssertionError("schedule_monitor.sh heredoc 里找不到 STATS_REFRESH_OK 赋值")


class _SysShim:
    """略替 `sys`: 只提供生产块用到的 executable / stderr(后者收集告警文本)。"""

    executable = sys.executable

    def __init__(self):
        self.stderr = io.StringIO()


def _run_refresh(run_impl):
    """在 stub 环境里执行生产刷新块, 返回 (STATS_REFRESH_OK, stderr 文本, 调用参数)。"""
    assign_src, try_src = _refresh_nodes()
    shim = _SysShim()
    calls = []

    def _run(cmd, **kw):
        calls.append((cmd, kw))
        return run_impl(cmd, **kw)

    ns = {
        "sys": shim,
        "subprocess": types.SimpleNamespace(run=_run),
        "REPO": REPO,
    }
    exec(compile(assign_src + "\n" + try_src, "<stats-refresh-block>", "exec"), ns)  # noqa: S102
    return ns["STATS_REFRESH_OK"], shim.stderr.getvalue(), calls


# ---------------------------------------------------------------- 刷新块本身

def test_nonzero_rc_marks_refresh_failed():
    """F1 核心: 退出码 1(gen 顶层异常的真实表现)必须判刷新失败。"""
    ok, err, calls = _run_refresh(
        lambda cmd, **kw: types.SimpleNamespace(
            returncode=1, stdout="", stderr="Traceback (most recent call last):\n"
                                           "RuntimeError: boom\n"))
    assert ok is False, "gen 退出码非 0 却仍判刷新成功 = 残余假 OK"
    assert len(calls) == 1 and calls[0][0][-1].endswith("gen_schedule_stats.py")
    # 排查线索进日志: 退出码 + stderr 尾部
    assert "退出码 1" in err
    assert "RuntimeError: boom" in err


def test_nonzero_rc_with_empty_stderr_still_flags():
    """rc 非 0 但不输出 stderr: 仍必须判失败(日志尾部为空只是少一条线索)。"""
    ok, err, _ = _run_refresh(
        lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr=""))
    assert ok is False
    assert "退出码 1" in err


def test_zero_rc_keeps_refresh_ok():
    """反向对照(防恒红): 退出码 0 必须仍是刷新成功。"""
    ok, err, _ = _run_refresh(
        lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert ok is True
    assert err == ""


def test_stderr_tail_is_truncated():
    """stderr 只记尾部一行且截断: 防整段 traceback 刷屏/带出无关内容。"""
    long_line = "E" * 500
    ok, err, _ = _run_refresh(
        lambda cmd, **kw: types.SimpleNamespace(
            returncode=2, stdout="", stderr=f"first line\n{long_line}\n"))
    assert ok is False
    assert "first line" not in err
    assert long_line not in err
    assert "E" * 200 in err and "E" * 201 not in err


def test_exception_still_marks_refresh_failed():
    """原有 P1b 行为不许退化: 抛异常(timeout 等)照样判失败。"""
    def _raise(cmd, **kw):
        raise TimeoutExpiredStub("timeout after 60s")

    ok, err, _ = _run_refresh(_raise)
    assert ok is False
    assert "刷新失败" in err


class TimeoutExpiredStub(Exception):
    pass


# ---------------------------------------------------------------- 端到端: 结论行

def _green_stats(n=40):
    return [{
        "task": f"task_{i}",
        "unit": f"trade-task-{i}.service",
        "unit_exit": 0,
        "unit_result": "success",
        "unit_start": "2026-10-24 20:00:00",
        "unit_exit_ts": "2026-10-24 20:10:00",
        "next_elapse": "2026-10-25 20:00:00",
        "unit_missed": False,
        "last_exit": 0,
        "exit_source": "systemd",
        "exit_conflict": False,
        "last_exit_tier": None,
    } for i in range(n)]


OK_ALL = "OK 所有任务按计划执行"


def test_nonzero_rc_conclusion_never_says_ok():
    """F1 证据用例: rc=1 的真实刷新结果喂给结论层 → 结论行不含「OK 所有任务」。"""
    import datetime

    ok, _, _ = _run_refresh(
        lambda cmd, **kw: types.SimpleNamespace(
            returncode=1, stdout="", stderr="ValueError: xxx\n"))
    text = _conclusion()(_green_stats(), datetime.datetime(2026, 10, 25, 16, 15),
                         cfu_failed=0, alerts=0, stats_refresh_ok=ok)
    assert OK_ALL not in text
    assert "stats 刷新失败" in text


def test_zero_rc_all_green_still_says_ok():
    """反向对照: 同一批全绿数据 + rc=0 → OK 必须回来(防本次修复把结论打成恒不 OK)。"""
    import datetime

    ok, _, _ = _run_refresh(
        lambda cmd, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    text = _conclusion()(_green_stats(), datetime.datetime(2026, 10, 25, 16, 15),
                         cfu_failed=0, alerts=0, stats_refresh_ok=ok)
    assert OK_ALL in text