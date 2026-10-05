# -*- coding: utf-8 -*-
"""#164 资源维度 + #162 进行中判定 回归测试(2026-10-05)。

覆盖范围(取用 schedule_monitor.sh 里**同一份实现**, 不另写副本):
  - 常量策略值: RESOURCE_WARN_PCT=85.0 / RESOURCE_SEVERE_PCT=90.0 / IN_PROGRESS_MAX_AGE=6h
    (漂移守卫: 改阈值必须同步改本测试, 防"报告写 85/90 而代码悄悄变")
  - _df_pct_ceil / _df_used_pct / _inode_used_pct: df 口径 + 向上取整(与 GNU df 显示一致)
  - _mem_used_pct / _swap_used_pct: Linux /proc/meminfo 分支(本机 mac 测不到, 用假
    /proc/meminfo 注入跑真实函数; 云上另有真数据实测佐证)
  - _in_progress_state: #162 核心判定 —— 新鲜=在跑 / 陈旧=不判在跑(修残留 hold)
  - _check_resource: >=severe 进 alerts+state / >=warn 走 notify warning 聚合 / 否则静默
    / 持续中 suppress 不重发 / 恢复后 <6h 复现抑制

取用方式: 从 scripts/schedule_monitor.sh 的 python heredoc 里 **ast 提取**目标
FunctionDef / 顶层 Assign 源码后 exec(不是把逻辑抄一份到测试里), 否则测试与生产两份
实现会静默漂移(memory repro-script-second-implementation-drift)。
⚠️ 反面确认: #162 的 inline 调用点(把 "running" 收进 in_progress_tasks 的那个 for 体内,
与 A1/耗时检查混写、无法单独抽出)不在本测试范围, 由 2026-10-05 云上真数据 before/after
回放覆盖(旧版 [hold] s06 / 新版 [in-progress-stale]+[recovery] s06, 全程仅该条 key 状态
变化)—— 此缺口是有意登记, 非静默漏测。
"""
import ast
import datetime
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from datetime import datetime as _DATETIME
from datetime import timedelta as _TIMEDELTA

def _resolve_root():
    """定位含 scripts/schedule_monitor.sh 的仓根。

    正常在 scripts/tests/ 下跑 -> 上溯三级即仓根; 若本文件被拷到别处跑(如云上验证),
    再用 MONITOR_TEST_ROOT / REPO 环境变量兜(找不到就返回上溯值, 让报错指向真实路径)。
    """
    here = Path(__file__).absolute().parent.parent.parent
    if (here / "scripts" / "schedule_monitor.sh").exists():
        return here
    for key in ("MONITOR_TEST_ROOT", "REPO"):
        val = os.environ.get(key)
        if val and (Path(val) / "scripts" / "schedule_monitor.sh").exists():
            return Path(val)
    return here


ROOT = _resolve_root()
MONITOR = ROOT / "scripts" / "schedule_monitor.sh"

_WANT_ASSIGN = {"RESOURCE_WARN_PCT", "RESOURCE_SEVERE_PCT", "IN_PROGRESS_MAX_AGE", "DUR_THRESHOLDS"}
_WANT_FUNC = {
    "_df_pct_ceil", "_df_used_pct", "_inode_used_pct", "_mem_used_pct",
    "_swap_used_pct", "_in_progress_state", "_check_resource",
}

# macOS APFS: df 走"容器级"容量(含同容器其他卷空闲), 与 statvfs 的"卷级"口径不同
# (实测 df -P / 14% vs statvfs 82%); Linux(生产)两者一致(云上实测 df 85% == 实现 85.0%)。
# 故"与 df 逐位一致"只在 Linux 断言, mac 跳过并给出原因(不静默放过)。
_ON_LINUX = sys.platform.startswith("linux")


def _heredoc_source():
    """取 schedule_monitor.sh 里 python heredoc(<<'PYEOF' ... PYEOF)的正文。"""
    lines = MONITOR.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    end = next(i for i, l in enumerate(lines) if i > start and l.strip() == "PYEOF")
    return "".join(lines[start + 1:end])


@pytest.fixture(scope="module")
def extracted_src():
    """从生产脚本提取目标常量 + 函数的源码(真实源码, 非副本); 缺失则响亮失败。"""
    src = _heredoc_source()
    tree = ast.parse(src)
    picked, found = [], set()
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef) and node.name in _WANT_FUNC:
            name = node.name
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in _WANT_ASSIGN:
                    name = tgt.id
        if name:
            picked.append(ast.get_source_segment(src, node) + "\n")
            found.add(name)
    missing = (_WANT_ASSIGN | _WANT_FUNC) - found
    assert not missing, (
        f"schedule_monitor.sh 里未找到 {sorted(missing)}: 被重命名/删除了? 本测试锚点需同步"
    )
    return "\n".join(picked)


def _fresh_ns(extracted_src):
    """把提取源码 exec 成新命名空间。

    ⚠️ exec 出来的函数的 __globals__ 就是这个 dict, 所以想替换 sys/open 等注入依赖,
    必须换新 dict 重新 exec —— 对旧 dict 做 dict(...) 浅拷贝无效(实测踩过)。
    注入的 datetime 必须是 **类**(生产里 `from datetime import datetime`), 不是模块。
    """
    ns = {
        "os": os, "sys": sys, "subprocess": None, "datetime": _DATETIME,
        "timedelta": _TIMEDELTA, "Path": Path,
    }
    exec(compile(extracted_src, "<monitor-extract>", "exec"), ns)  # noqa: S102
    return ns


@pytest.fixture(scope="module")
def monitor_ns(extracted_src):
    """只读用例共用一份(不改注入依赖)。"""
    return _fresh_ns(extracted_src)


@pytest.fixture()
def fresh_ns(extracted_src):
    """需要替换 sys/open/subprocess 等注入依赖的用例: 每次新建命名空间。"""
    return _fresh_ns(extracted_src)


class _FakeSys:
    """替身 sys: 只改 platform, 其余透传(供 Linux 分支在 mac/CI 上跑到)。"""

    def __init__(self, platform):
        self.platform = platform
        self.executable = sys.executable
        self.stderr = sys.stderr


MEMINFO = (
    "MemTotal:        3808588 kB\n"
    "MemFree:          155760 kB\n"
    "MemAvailable:    1904294 kB\n"
    "SwapTotal:       1048572 kB\n"
    "SwapFree:         524286 kB\n"
)


def _fake_open(*_a, **_k):
    return io.StringIO(MEMINFO)


# ---------------------------------------------------------------- 常量策略值

def test_threshold_constants(monitor_ns):
    assert monitor_ns["RESOURCE_WARN_PCT"] == 85.0
    assert monitor_ns["RESOURCE_SEVERE_PCT"] == 90.0
    assert monitor_ns["IN_PROGRESS_MAX_AGE"] == datetime.timedelta(hours=6), (
        "#162 上限改动必须同步本测试 + 代码注释里的取值依据"
    )


# ---------------------------------------------------------------- df 取整 / 磁盘

def test_df_pct_ceil_matches_gnu_df(monitor_ns):
    f = monitor_ns["_df_pct_ceil"]
    # GNU df 向上取整: 84.01 -> 85(云上 2026-10-05 实测边界), 85.0 -> 85, 90.01 -> 91
    assert f(84.01) == 85.0
    assert f(85.0) == 85.0
    assert f(90.01) == 91.0
    assert f(0.0) == 0.0
    assert f(99.99) == 100.0
    assert f(None) is None


def test_disk_and_inode_pct_use_statvfs(monitor_ns, tmp_path):
    st = os.statvfs(str(tmp_path))
    used = st.f_blocks - st.f_bfree
    exp_disk = monitor_ns["_df_pct_ceil"](100.0 * used / (used + st.f_bavail))
    assert monitor_ns["_df_used_pct"](str(tmp_path)) == exp_disk
    if st.f_files > 0:  # 部分 fs 不报 inode
        exp_inode = monitor_ns["_df_pct_ceil"](100.0 * (st.f_files - st.f_ffree) / st.f_files)
        assert monitor_ns["_inode_used_pct"](str(tmp_path)) == exp_inode
    # 失败路径不抛、返回 None(静默不告警)
    assert monitor_ns["_df_used_pct"]("/no/such/path/xyz") is None
    assert monitor_ns["_inode_used_pct"]("/no/such/path/xyz") is None


@pytest.mark.skipif(not _ON_LINUX, reason="macOS APFS 的 df 为容器级口径, 与 statvfs 卷级不同")
def test_disk_pct_matches_df_p_output(monitor_ns, tmp_path):
    """df -P 的百分比 == 本实现(ceil 后), 保证操作者 df 复核数字对得上。"""
    out = subprocess.run(["df", "-P", str(tmp_path)], capture_output=True, text=True).stdout
    df_pct = float(out.splitlines()[1].split()[4].rstrip("%"))
    assert monitor_ns["_df_used_pct"](str(tmp_path)) == df_pct


# ---------------------------------------------------------------- 内存 / swap(Linux 分支)

def test_mem_used_pct_linux_branch(fresh_ns):
    fresh_ns["sys"] = _FakeSys("linux")
    fresh_ns["open"] = _fake_open
    mem_total, mem_avail = 3808588.0, 1904294.0
    assert fresh_ns["_mem_used_pct"]() == 100.0 * (1.0 - mem_avail / mem_total)


def test_swap_used_pct_linux_branch(fresh_ns):
    fresh_ns["sys"] = _FakeSys("linux")
    fresh_ns["open"] = _fake_open
    assert fresh_ns["_swap_used_pct"]() == 50.0  # (1048572-524286)/1048572


def test_swap_used_pct_no_swap_is_none(fresh_ns):
    fresh_ns["sys"] = _FakeSys("linux")
    fresh_ns["open"] = lambda *a, **k: io.StringIO(
        "MemTotal: 100 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    assert fresh_ns["_swap_used_pct"]() is None  # 无 swap -> 不判


def test_mem_and_swap_none_on_non_procfs_platform(fresh_ns):
    fresh_ns["sys"] = _FakeSys("win32")
    assert fresh_ns["_mem_used_pct"]() is None
    assert fresh_ns["_swap_used_pct"]() is None


# ---------------------------------------------------------------- #162 进行中判定

def _row(task="update_all", last_run="2026-10-05 14:00", last_exit=0, dur=None):
    return {"task": task, "last_run": last_run, "last_exit": last_exit, "last_duration_sec": dur}


@pytest.mark.parametrize(
    "row,expect",
    [
        (_row(last_run="2026-10-05 13:50"), "running"),      # 真在跑(10 分钟)
        (_row(last_run="2026-10-05 08:01"), "running"),      # 上限内(5h59m), 不得误伤
        (_row(last_run="2026-10-05 08:00"), "running"),      # 恰好上限(6h, 含等号)
        (_row(last_run="2026-10-05 07:59"), "stale"),        # 刚过上限
        (_row(task="s06_snapshot", last_run="2026-09-30 20:35"), "stale"),  # s06 实况(5 天)
        (_row(last_exit=1), "no"),                           # 失败: 由退出检查告警, 不并入
        (_row(last_exit=143), "no"),
        (_row(dur=318), "no"),                               # 已完成
        (_row(task="fetch_news"), "no"),                     # 非 DUR_THRESHOLDS 任务
        (_row(last_run=""), "no"),                           # 不可判新鲜 -> 不 hold
        (_row(last_run="不是日期"), "no"),
    ],
)
def test_in_progress_state(monitor_ns, row, expect):
    now = datetime.datetime(2026, 10, 5, 14, 0)
    assert monitor_ns["_in_progress_state"](row, now) == expect


# ---------------------------------------------------------------- _check_resource 分级

class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, *a, **k):
        self.calls.append(list(cmd))

        class _R:
            returncode = 0

        return _R()


@pytest.fixture()
def res_env(fresh_ns):
    rec = _Recorder()
    fresh_ns["subprocess"] = type("S", (), {"run": staticmethod(rec)})()
    fresh_ns["alerts"] = []
    fresh_ns["alert_state"] = {}
    fresh_ns["seen_keys_this_run"] = set()
    fresh_ns["NOW"] = datetime.datetime(2026, 10, 5, 14, 0)
    fresh_ns["REPO"] = ROOT
    fresh_ns["_recurrence_suppressed"] = lambda _ex: False
    fresh_ns["_rec"] = rec
    return fresh_ns


def _warn_calls(rec):
    return [c for c in rec.calls if "--tier" in c and c[c.index("--tier") + 1] == "warning"]


def test_check_resource_severe(res_env):
    res_env["_check_resource"]("主机磁盘", "/", 92.3)
    assert len(res_env["alerts"]) == 1
    assert res_env["alerts"][0].startswith("SEVERE: 主机磁盘 使用率 92.3%")
    assert res_env["seen_keys_this_run"] == {"host_resource|主机磁盘|/"}
    st = res_env["alert_state"]["host_resource|主机磁盘|/"]
    assert st["status"] == "active" and st["keyword"] == "主机磁盘_high"
    assert _warn_calls(res_env["_rec"]) == []  # severe 不走 warning 缓冲


def test_check_resource_warn_tier(res_env):
    res_env["_check_resource"]("主机内存", "host", 86.4)
    assert res_env["alerts"] == []          # 不即时 SEVERE
    assert res_env["alert_state"] == {}     # warning 不写 alert_state
    assert res_env["seen_keys_this_run"] == set()
    wc = _warn_calls(res_env["_rec"])
    assert len(wc) == 1
    assert wc[0][wc[0].index("--dedup-key") + 1] == "host_resource_warn_主机内存_host"
    assert wc[0][wc[0].index("--dedup-window") + 1] == "21600"


def test_check_resource_below_warn_and_measure_failure(res_env):
    res_env["_check_resource"]("主机内存", "host", 84.9)   # 未达预警线 -> 静默
    res_env["_check_resource"]("主机磁盘", "/", None)      # 测量失败 -> 静默
    assert res_env["alerts"] == [] and res_env["alert_state"] == {}
    assert res_env["_rec"].calls == []


def test_check_resource_severe_suppressed_when_active(res_env):
    res_env["_check_resource"]("主机磁盘", "/", 91.0)
    res_env["alerts"].clear()
    res_env["_check_resource"]("主机磁盘", "/", 95.0)      # 持续中 -> 不重发
    assert res_env["alerts"] == []
    assert res_env["alert_state"]["host_resource|主机磁盘|/"]["last_alerted"] == "2026-10-05 14:00:00"


def test_check_resource_recurrence_suppressed(res_env):
    res_env["alert_state"]["host_resource|主机内存|host"] = {
        "status": "recovered", "first_seen": "2026-10-05 10:00", "last_alerted": "2026-10-05 10:00",
    }
    res_env["_recurrence_suppressed"] = lambda _ex: True
    res_env["_check_resource"]("主机内存", "host", 93.0)
    assert res_env["alerts"] == []  # 恢复后 <6h 复现 -> 抑制
    assert res_env["alert_state"]["host_resource|主机内存|host"]["status"] == "active"