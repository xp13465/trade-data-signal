# -*- coding: utf-8 -*-
"""schedule_monitor.sh 漏跑检查(pending→SEVERE)回归测试(2026-10-26, P1 事故补测)。

## 为什么补这条测试

2026-09-29 引入「单轮漏跑先 pending、连续 2 轮才 SEVERE」降噪后, 漏跑分支在真实监控里
**一次都没跑通过**: 阈值常量 MISSED_CONTINUOUS_THRESHOLD 定义在模块尾部, 模块级
`for t in TASKS:` 循环先使用 ⇒ 任何任务首次漏跑必 NameError, 整轮监控中止; 脚本末尾
exit 0 让 systemd 恒 success ⇒ 崩溃 26 天完全静默(13 次真漏跑被吞)。

旧测试为什么没发现: 它们都是「ast 抽片段 + 手工把常量注入命名空间」, 常量缺失被测试自己
补上了。本文件改掉这个做法 ——

## 命名空间构建方式(本测试的重点)

1. 从 scripts/schedule_monitor.sh 的真实 heredoc 里取内嵌 Python 源码;
2. **按源码顺序 exec「漏跑循环之前的全部模块级语句」** —— 阈值常量、TASKS、解析函数
   全部来自 exec, 测试里一个常量值都不写;
3. 再把**真实循环体**(那个含 `missed|` key 的 `for t in TASKS:`)单独 exec 一次 = 一轮监控。
   `test_namespace_built_from_real_source_order` 用「把常量搬回尾部必须变红」把这条
   钉死: 顺序一错, 测试就报 NameError(与生产同形)。

## 覆盖

① 首轮漏跑: 打印 `[missed-buffer] ... 连续1/2 轮`, state=pending, 不抛异常;
② 连续第 2 轮: `SEVERE: <task> 漏跑`, state=active;
③ 已 active 的 key: 不重复 SEVERE(走 suppress 分支)。

## 安全

全静态 + 沙箱: REPO 指向 tmp_path; `subprocess` 被换成「一用就炸」的哨兵,
`notify_sent` 恒 False ⇒ 本测试**不可能真发邮件/飞书**(§18 L48)。
时间冻结在 FIXED_NOW(不读真实今天, 防跨天红 —— L51)。
"""

import ast
import os
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# 默认读仓内真源码; MONITOR_TEST_MONITOR 仅用于判别力验证(改坏的副本必须让本文件变红),
# 生产/CI 不设该变量。
MONITOR = Path(os.environ.get("MONITOR_TEST_MONITOR") or ROOT / "scripts" / "schedule_monitor.sh")
TAG = "PYEOF"

FIXED_NOW = datetime(2026, 10, 20, 14, 30, 0)  # 周二, 冻结运行时刻(L51)
SCH = "14:25"                                   # 计划时点:NOW 落在 [sch+60s, sch+30min] 窗口内


# ── 从真实源码取「模块级语句 + 漏跑循环」 ────────────────────────────────────
def _heredoc_src(path: Path) -> str:
    """取 .sh 里 <<'PYEOF' … PYEOF 之间的正文(真实源码, 不是副本)。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if "<<'PYEOF'" in ln)
    end = next(i for i, ln in enumerate(lines) if i > start and ln.strip() == TAG)
    return "\n".join(lines[start + 1:end]) + "\n"


def _split_module(path: Path):
    """→ (全部模块级语句, 漏跑循环节点)。循环按「含 missed| key」定位, 改名会响亮失败。"""
    tree = ast.parse(_heredoc_src(path))
    loop = next(
        (n for n in tree.body
         if isinstance(n, ast.For) and "missed|" in ast.unparse(n)),
        None,
    )
    assert loop is not None, "没找到含 `missed|` 的模块级 for 循环 —— 循环被重写/改名了?"
    prefix = [n for n in tree.body if n.end_lineno < loop.lineno]
    assert prefix, "漏跑循环之前没有模块级语句? 源码结构变了"
    return prefix, loop


def _compile(nodes, label: str):
    mod = ast.Module(body=list(nodes), type_ignores=[])
    return compile(ast.fix_missing_locations(mod), label, "exec")


def _forbidden(*_a, **_k):
    raise AssertionError("测试禁止起子进程/真发通知(静态 only, §18 L48)")


def _build_ns(path: Path, sandbox: Path, monkeypatch):
    """exec 真实源码的模块级前缀(按顺序) → 命名空间 + 漏跑循环节点。"""
    repo = sandbox / "repo"
    (repo / "data" / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPO", str(repo))
    prefix, loop = _split_module(path)

    ns = {"__name__": "__monitor_under_test__"}
    exec(_compile(prefix, "<monitor-prefix>"), ns)  # noqa: S102 - 真实源码

    # 哨兵: 任何路径走到真外发都当场失败(不是静默放过)
    ns["subprocess"] = types.SimpleNamespace(run=_forbidden)
    ns["notify_sent"] = lambda *_a, **_k: False
    return ns, loop


def _prime_scenario(ns, sandbox: Path) -> str:
    """一轮监控的初始条件: 一个只在 SCH 有计划的假任务 + 空日志目录 + 空 alert_state。"""
    logdir = sandbox / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    ns["NOW"] = FIXED_NOW
    ns["TASKS"] = [{
        "task": "faketask", "log": "faketask.log",
        "trading_day_only": False, "schedules": [SCH],
    }]
    ns["LOG_DIR"] = logdir
    ns["alerts"] = []
    ns["alert_state"] = {}
    ns["seen_keys_this_run"] = set()
    return f"missed|faketask|{SCH}|{FIXED_NOW.strftime('%Y-%m-%d')}"


def _run_round(ns, loop, capsys) -> str:
    """跑一轮真实漏跑循环(真实源码), 返回本轮 stdout。"""
    capsys.readouterr()
    exec(_compile([loop], "<monitor-missed-loop>"), ns)  # noqa: S102 - 真实源码
    return capsys.readouterr().out


# ── ① 首轮: pending 缓冲, 不通知, 不崩 ──────────────────────────────────────
def test_round1_pending_buffer(tmp_path, monkeypatch, capsys):
    ns, loop = _build_ns(MONITOR, tmp_path, monkeypatch)
    # 阈值常量必须是 exec 真实源码得到的(测试没有手工注入任何常量值)
    assert "MISSED_CONTINUOUS_THRESHOLD" in ns, "常量没从源码进命名空间 —— 本测试的前提破了"
    assert "TOLERANCE" in ns and "TASKS" in ns

    key = _prime_scenario(ns, tmp_path)
    out = _run_round(ns, loop, capsys)

    assert ns["alerts"] == [], f"首轮不该有 SEVERE, 实得 {ns['alerts']}"
    state = ns["alert_state"][key]
    assert state["status"] == "pending"
    assert state["consecutive_count"] == 1
    assert f"[missed-buffer] faketask 漏跑 计划<{SCH}> 连续1/2 轮" in out


# ── ② 连续第 2 轮: 升级 SEVERE + 落 active ──────────────────────────────────
def test_round2_escalates_severe(tmp_path, monkeypatch, capsys):
    ns, loop = _build_ns(MONITOR, tmp_path, monkeypatch)
    key = _prime_scenario(ns, tmp_path)
    _run_round(ns, loop, capsys)          # 第 1 轮: pending
    out2 = _run_round(ns, loop, capsys)   # 第 2 轮: 连续 2 轮

    assert len(ns["alerts"]) == 1, f"第 2 轮应恰好 1 条 SEVERE, 实得 {ns['alerts']}"
    assert ns["alerts"][0].startswith(f"SEVERE: faketask 漏跑 计划<{SCH}>")
    state = ns["alert_state"][key]
    assert state["status"] == "active"
    assert state["consecutive_count"] == 2
    assert "[missed-buffer]" not in out2, "第 2 轮不该再打缓冲行"


# ── ③ 已 active 的 key: 不重复 SEVERE ───────────────────────────────────────
def test_active_key_not_repeated(tmp_path, monkeypatch, capsys):
    ns, loop = _build_ns(MONITOR, tmp_path, monkeypatch)
    key = _prime_scenario(ns, tmp_path)
    _run_round(ns, loop, capsys)          # 第 1 轮: pending
    _run_round(ns, loop, capsys)          # 第 2 轮: active + 1 条 SEVERE
    assert len(ns["alerts"]) == 1

    out3 = _run_round(ns, loop, capsys)   # 第 3 轮: 已 active
    assert len(ns["alerts"]) == 1, f"已 active 不该重复 SEVERE, 实得 {ns['alerts']}"
    assert ns["alert_state"][key]["status"] == "active"
    assert "[suppress]" in out3, "已 active 应走抑制分支(打 [suppress])"


# ── 判别力: 常量搬回模块尾部(事故原形) ⇒ 本测试必须变红 ──────────────────────
def test_namespace_built_from_real_source_order(tmp_path, monkeypatch, capsys):
    """证明阈值不是测试手工注入的: 顺序一错, exec 真实循环就 NameError。

    构造方式与 2026-10-26 事故同形 —— 把 MISSED_CONTINUOUS_THRESHOLD 的定义从引用点之前
    挪到 heredoc 末尾, 其余不动。
    """
    lines = MONITOR.read_text(encoding="utf-8").splitlines()
    const = "MISSED_CONTINUOUS_THRESHOLD = 2"
    hits = [i for i, ln in enumerate(lines) if ln.strip() == const]
    assert len(hits) == 1, f"预期模块级定义恰好 1 处, 实得 {hits}"
    moved = lines.pop(hits[0])
    end = max(i for i, ln in enumerate(lines) if ln.strip() == TAG)
    lines.insert(end, moved)

    bad = tmp_path / "bad" / "scripts" / "schedule_monitor.sh"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ns, loop = _build_ns(bad, tmp_path / "bad", monkeypatch)
    assert "MISSED_CONTINUOUS_THRESHOLD" not in ns, "前缀 exec 不该拿到尾部的定义"
    _prime_scenario(ns, tmp_path / "bad")

    with pytest.raises(NameError, match="MISSED_CONTINUOUS_THRESHOLD"):
        _run_round(ns, loop, capsys)


# ── 顺带钉住窗口口径: 提前 60s 下界仍在(避免启动竞态误报) ───────────────────
def test_window_lower_bound_still_buffer(tmp_path, monkeypatch, capsys):
    """NOW 只比 sch 晚 30s(在 +60s 下界内) ⇒ 本轮不该判漏跑。"""
    ns, loop = _build_ns(MONITOR, tmp_path, monkeypatch)
    _prime_scenario(ns, tmp_path)
    ns["NOW"] = FIXED_NOW.replace(minute=25, second=30)  # sch=14:25:00, 只晚 30s
    out = _run_round(ns, loop, capsys)
    assert ns["alert_state"] == {}
    assert "[missed-buffer]" not in out
    assert ns["alerts"] == []
    # 窗口上界口径: 30min 容忍窗口(TOLERANCE)仍须是源码里的值
    assert ns["TOLERANCE"] == timedelta(minutes=30)