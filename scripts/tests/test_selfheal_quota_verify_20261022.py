#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_heal 每任务配额 + heal 结果校验 + 连续失败升级(2026-10-22 P0)。

背景(只读评估报告 /tmp/research-stability-eval.md §4):
  - 旧版每日 3 次配额是**全站共享**,一个任务反复失败吃光额度,别的任务当天无法自愈;
  - heal 只"按一下重跑",不校验结果,30 天可核对 19 次里 6 次成功(31.6%);
  - audit 只记"触发了",连续失败无人知道。

本用例覆盖(对应派单五条证据用例):
  ① 三个任务各失败 3 次 → 计数互相独立,第 4 次被 per_task_limit 拒绝
  ② heal 后目标产物缺失 → 校验记 FAIL(依据含产物)
  ③ 同一任务连续 FAIL 2 次 → 升级告警恰发一次(第 3 次不重复发)
  ④ 旧格式 state 兼容(只有全局 count + healed 列表)不崩、按 healed 折算每任务计数
  ⑤ 全程零真实外发:先证零外发陷阱生效,再断言本套用例零触达;
     并静态核 self_heal.sh 的 notify 适配层带 --dry-run 开关与告警四元组参数

补充:超时无新记录判 FAIL / PASS 清零连败 / pending 去重 / 盘中 update_all 跳过 /
总上限 12 次 / 旧筛选口径(SKIP_STALE)。

纪律(L51):不依赖真实 "今天",所有时点由 datetime 显式注入。
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).absolute().parent))

import self_heal_core as core  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

NOW = datetime(2026, 10, 22, 18, 0, 0)  # 周四盘后,固定时点(L51:禁真实 today)


# ── 测试脚手架 ────────────────────────────────────────────────────────────────
def _stats(*tasks, last_run="2026-10-22 17:50", exit_code=1, anomaly=False):
    return [{"task": t, "last_exit": exit_code, "last_run": last_run,
             "log_anomaly": anomaly} for t in tasks]


def _cycle(tmp_path, stats, now, *, lookup_run=None, artifact_probe=None,
           trigger=None, escalate=None, info=None, launch_state=None,
           intraday_skip=None, state_name="state.json", total_limit=12,
           per_task_limit=3, heal_actions=None, labels=None):
    """跑一轮 run_cycle,返回 (summary, audit 文本)。"""
    calls = {"trigger": [], "escalate": [], "info": []}

    def _trigger(task, cmd):
        calls["trigger"].append((task, tuple(cmd)))
        return True, ""

    def _escalate(task, streak, basis):
        calls["escalate"].append((task, streak, basis))
        return True

    def _info(subject, body):
        calls["info"].append((subject, body))
        return True

    summary = core.run_cycle(
        repo=tmp_path, stats=stats, state_path=tmp_path / state_name,
        audit_path=tmp_path / "audit.log", now=now,
        heal_actions=heal_actions or {t: ["bash", f"scripts/{t}.sh"] for t in
                                      {s["task"] for s in stats}},
        labels=labels or {}, launch_state=launch_state or (lambda label: None),
        trigger=trigger or _trigger, notify_info=info or _info,
        notify_escalate=escalate or _escalate,
        lookup_run=lookup_run, artifact_probe=artifact_probe,
        per_task_limit=per_task_limit, total_limit=total_limit,
        intraday_skip=intraday_skip,
    )
    audit_path = tmp_path / "audit.log"
    audit = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
    return summary, audit, calls


def _run_after(heal_at, exit_code=0):
    """构造"heal 之后跑完的一次运行记录"(lookup_run 返回值)。"""
    return {"end": (heal_at + timedelta(minutes=5)).isoformat(timespec="seconds"),
            "exit": exit_code}


def _mutable_lookup(exit_code):
    """lookup_run:读 state 里该任务最近一次 heal_at,返回其后的运行记录。

    模拟「下次轮次校验时,任务日志里出现了 heal 之后的新运行」。
    """
    def _lookup(task):
        state = json.loads((Path(exit_code["dir"]) / "state.json").read_text(encoding="utf-8"))
        for p in state.get("pending", []):
            if p.get("task") == task:
                return _run_after(datetime.fromisoformat(p["heal_at"]),
                                  exit_code["code"])
        return None
    return _lookup


# ── 证据用例 ① 每任务配额独立 + 第 4 次拒绝 ──────────────────────────────────
def test_per_task_quota_independent(tmp_path):
    tasks = ["update_all", "lhb_backfill", "rzhb_backfill"]
    stats = _stats(*tasks)
    lookup = _mutable_lookup({"dir": str(tmp_path), "code": 1})
    probe = lambda task, heal_at: (True, "无产物规格(按运行记录判定)")  # noqa: E731
    total_triggers = 0
    for i in range(4):
        now = NOW + timedelta(minutes=15 * i)
        summary, audit, calls = _cycle(tmp_path, stats, now, lookup_run=lookup,
                                       artifact_probe=probe)
        total_triggers += len(calls["trigger"])

    # 前 3 轮每轮 3 个任务各触发一次 = 9 次;第 4 轮三任务各自达 3 次上限被拒
    assert total_triggers == 9, f"触发了 {total_triggers} 次(期望 9=3 任务×3 次)"
    assert len(calls["trigger"]) == 0, "第 4 轮不应再触发"
    assert sorted(s["task"] for s in summary["skipped"]) == sorted(tasks)
    for t in tasks:
        assert f"SKIP_QUOTA {t} reason=per_task_limit" in audit, f"{t} 缺 per_task_limit 审计"
        assert f"task_count=3/3" in audit
    state = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    for t in tasks:
        assert state["per_task"][t]["count"] == 3, f"{t} 每任务计数={state['per_task'][t]['count']}"
    assert state["count"] == 9, f"全站计数={state['count']}(期望 9)"


def test_total_limit_loose_cap(tmp_path):
    """全站总上限 12 次(防总爆炸):达上限后不再触发,info 只发一次。"""
    stats = _stats("a_task", "b_task")
    state = core.empty_state(NOW.strftime("%Y-%m-%d"))
    state["count"] = 12
    core.save_state(tmp_path / "state.json", state)
    summary, audit, calls = _cycle(tmp_path, stats, NOW)
    assert calls["trigger"] == []
    assert summary["limit"] == "total_limit"
    assert len(calls["info"]) == 1
    assert "LIMIT" in audit
    # 第二轮不再重复 info
    summary2, _audit2, calls2 = _cycle(tmp_path, stats, NOW + timedelta(minutes=15))
    assert calls2["info"] == [], "limit_notified 后不应重复发 info"


# ── 证据用例 ② heal 后产物缺失 → FAIL ────────────────────────────────────────
def test_verify_artifact_missing_fails(tmp_path):
    lookup = _mutable_lookup({"dir": str(tmp_path), "code": 0})
    # 第 1 轮触发 heal
    _cycle(tmp_path, _stats("update_all"), NOW, lookup_run=lookup,
           artifact_probe=lambda task, heal_at: (False, "产物缺失 static-site/data/overview.json"))
    # 第 2 轮:运行记录 exit=0 但产物缺失 → FAIL
    summary, audit, _ = _cycle(
        tmp_path, _stats("update_all"), NOW + timedelta(minutes=15), lookup_run=lookup,
        artifact_probe=lambda task, heal_at: (False, "产物缺失 static-site/data/overview.json"))
    assert len(summary["verified"]) == 1
    ev = summary["verified"][0]
    assert ev["result"] == "FAIL"
    assert "产物" in ev["basis"]
    assert "VERIFY update_all action=heal result=FAIL" in audit
    assert "产物缺失" in audit


def test_verify_pass_requires_fresh_artifact(tmp_path):
    """产物新鲜 + 退出码 0 → PASS;PASS 清零连续失败计数。"""
    repo = tmp_path / "repo"
    (repo / "static-site" / "data").mkdir(parents=True)
    lookup = _mutable_lookup({"dir": str(repo), "code": 0})
    probe = lambda task, heal_at: core.probe_artifact(repo, task, heal_at)  # noqa: E731
    _cycle(repo, _stats("update_all"), NOW, lookup_run=lookup, artifact_probe=probe)  # heal
    # 让产物 mtime 晚于 heal 起点(真实文件,不 mock 探针)
    art = repo / "static-site" / "data" / "overview.json"
    art.write_text("{}", encoding="utf-8")
    state = core.load_state(repo / "state.json", NOW.strftime("%Y-%m-%d"))
    heal_at = datetime.fromisoformat(state["pending"][0]["heal_at"])
    import os
    ts = heal_at.timestamp() + 120
    os.utime(art, (ts, ts))
    state["per_task"]["update_all"] = {"count": 1, "fail_streak": 1, "last_heal_at": None}
    core.save_state(repo / "state.json", state)
    summary, audit, _ = _cycle(repo, _stats("update_all"), NOW + timedelta(minutes=15),
                               lookup_run=lookup, artifact_probe=probe)
    assert summary["verified"][0]["result"] == "PASS"
    assert "result=PASS" in audit and "mtime" in audit
    state = core.load_state(repo / "state.json", NOW.strftime("%Y-%m-%d"))
    assert state["per_task"]["update_all"]["fail_streak"] == 0


def test_verify_timeout_without_new_run_fails(tmp_path):
    """heal 后超过判定时限仍无新运行记录 → FAIL(依据=超时)。"""
    state = core.empty_state(NOW.strftime("%Y-%m-%d"))
    heal_at = NOW - timedelta(hours=4)
    state["pending"] = [{"task": "lhb_backfill",
                         "heal_at": heal_at.isoformat(timespec="seconds"),
                         "reason": "exit=1", "last_exit": 1, "last_run": "2026-10-22 14:00"}]
    core.save_state(tmp_path / "state.json", state)
    summary, audit, _ = _cycle(tmp_path, _stats("lhb_backfill"), NOW,
                               lookup_run=lambda task: None)
    assert summary["verified"][0]["result"] == "FAIL"
    assert "无新运行记录" in audit


# ── 证据用例 ③ 连续失败 2 次 → 升级告警恰一次 ────────────────────────────────
def test_escalate_once_after_two_consecutive_failures(tmp_path):
    lookup = _mutable_lookup({"dir": str(tmp_path), "code": 1})
    probe = lambda task, heal_at: (True, "无产物规格(按运行记录判定)")  # noqa: E731
    escalate_calls = []

    def _esc(task, streak, basis):
        escalate_calls.append((task, streak, basis))
        return True

    # 3 轮 heal + 其后校验 FAIL:streak 1 → 2(发) → 3(不发)
    for i in range(4):
        _cycle(tmp_path, _stats("intraday_snapshot"), NOW + timedelta(minutes=15 * i),
               lookup_run=lookup, artifact_probe=probe, escalate=_esc)

    assert len(escalate_calls) == 1, f"升级告警发了 {len(escalate_calls)} 次(期望恰 1)"
    task, streak, basis = escalate_calls[0]
    assert task == "intraday_snapshot" and streak == 2
    assert basis, "升级告警必须带校验依据"
    audit = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert "ESCALATE intraday_snapshot action=notify result=SENT streak=2" in audit


def test_pass_resets_streak_no_escalate(tmp_path):
    """FAIL 一次后转 PASS:streak 归零,后续不再因旧失败升级。"""
    lookup = _mutable_lookup({"dir": str(tmp_path), "code": 1})
    probe = lambda task, heal_at: (True, "无产物规格(按运行记录判定)")  # noqa: E731
    esc = []
    _cycle(tmp_path, _stats("lab_auto"), NOW, lookup_run=lookup, artifact_probe=probe,
           escalate=lambda *a: esc.append(a) or True)          # heal #1
    _cycle(tmp_path, _stats("lab_auto"), NOW + timedelta(minutes=15),
           lookup_run=lookup, artifact_probe=probe, escalate=lambda *a: esc.append(a) or True)  # FAIL streak1
    assert esc == []
    # 改成记录 exit=0 + 产物新鲜 → PASS
    state = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    state["pending"][0]["heal_at"] = (NOW + timedelta(minutes=20)).isoformat(timespec="seconds")
    core.save_state(tmp_path / "state.json", state)
    summary, _a, _c = _cycle(tmp_path, _stats("lab_auto"), NOW + timedelta(minutes=30),
                             lookup_run=lambda task: _run_after(NOW + timedelta(minutes=25)),
                             artifact_probe=lambda task, heal_at: (True, "无产物规格(按运行记录判定)"))
    assert summary["verified"][0]["result"] == "PASS"
    assert summary["verified"][0]["fail_streak"] == 0


# ── 证据用例 ④ 旧格式 state 兼容 ─────────────────────────────────────────────
def test_legacy_state_compatible(tmp_path):
    legacy = {"date": NOW.strftime("%Y-%m-%d"), "count": 2,
              "healed": [{"task": "update_all", "time": "17:52:00"},
                         {"task": "update_all", "time": "18:07:00"},
                         {"task": "lhb_backfill", "time": "18:22:00"}],
              "skipped": [], "limit_notified": True}
    p = tmp_path / "state.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")
    state = core.load_state(p, NOW.strftime("%Y-%m-%d"))
    assert state["count"] == 2, "旧全局 count 保留"
    assert state["per_task"]["update_all"]["count"] == 2, "按 healed 折算每任务计数"
    assert state["per_task"]["lhb_backfill"]["count"] == 1
    assert state["pending"] == [] and state["limit_notified"] is True
    # 旧格式下继续跑一轮不崩(且 update_all 只剩 1 次额度)
    summary, audit, calls = _cycle(tmp_path, _stats("update_all"), NOW)
    assert len(calls["trigger"]) == 1, "update_all 旧计数 2 → 还可自愈 1 次"
    assert "task_count=3/3" in audit


def test_corrupt_and_missing_state_no_crash(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{坏 json", encoding="utf-8")
    state = core.load_state(p, NOW.strftime("%Y-%m-%d"))
    assert state["count"] == 0 and state["per_task"] == {}
    state2 = core.load_state(tmp_path / "nope.json", NOW.strftime("%Y-%m-%d"))
    assert state2["count"] == 0
    # 跨天:计数清零,pending / fail_streak 保留
    p.write_text(json.dumps({
        "date": "2026-10-21", "count": 5,
        "per_task": {"update_all": {"count": 3, "fail_streak": 2, "last_heal_at": None}},
        "pending": [{"task": "update_all", "heal_at": NOW.isoformat(timespec="seconds")}],
    }), encoding="utf-8")
    st = core.load_state(p, NOW.strftime("%Y-%m-%d"))
    assert st["count"] == 0 and st["per_task"]["update_all"]["count"] == 0
    assert st["per_task"]["update_all"]["fail_streak"] == 2
    assert len(st["pending"]) == 1


def test_pending_blocks_duplicate_trigger(tmp_path):
    """同一任务已有待校验 heal → 不再重复触发(避免 15min 一轮烧光配额)。"""
    _cycle(tmp_path, _stats("etf_national_team"), NOW, lookup_run=lambda t: None)
    summary, audit, calls = _cycle(tmp_path, _stats("etf_national_team"),
                                   NOW + timedelta(minutes=15), lookup_run=lambda t: None)
    assert calls["trigger"] == []
    assert "SKIP_QUOTA etf_national_team reason=pending_verify" in audit


# ── 旧筛选口径保留 + 盘中保护 ────────────────────────────────────────────────
def test_stale_and_running_skip_preserved(tmp_path):
    stats = [{"task": "update_all", "last_exit": 1, "last_run": "2026-10-20 17:50"},
             {"task": "lhb_backfill", "last_exit": 1, "last_run": "2026-10-22 17:50"}]
    summary, audit, calls = _cycle(
        tmp_path, stats, NOW,
        launch_state=lambda label: "running" if label == "com.trade.lhb-backfill" else None,
        labels={"update_all": "com.trade.update-all", "lhb_backfill": "com.trade.lhb-backfill"})
    assert calls["trigger"] == []
    assert "SKIP_STALE update_all" in audit
    assert "SKIP_RUNNING lhb_backfill state=running" in audit


def test_intraday_update_all_skipped(tmp_path):
    """§8 盘中(周四 10:00)不重跑 update_all 全量 export+deploy。"""
    now = datetime(2026, 10, 22, 10, 0, 0)
    summary, audit, calls = _cycle(
        tmp_path, _stats("update_all", last_run="2026-10-22 09:30"), now,
        intraday_skip=lambda task, n: task == "update_all" and n.isoweekday() <= 5
        and 930 <= int(n.strftime("%H%M")) <= 1530)
    assert calls["trigger"] == []
    assert "SKIP_INTRADAY update_all" in audit


# ── 证据用例 ⑤ 零真实外发(先证陷阱生效,再证全程零触达)─────────────────────
def test_zero_outbound_trap_effective():
    """先证沙箱生效:触达真实出口会被立刻拦下并计数(否则后面的"零外发"不算证据)。"""
    import urllib.request
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("https://example.com", timeout=1)
        assert trap.hits == ["urllib.request.urlopen"]


def test_core_and_suite_zero_outbound(tmp_path):
    """整套核心决策跑下来零网络/邮件依赖(纯逻辑 + 注入回调)。"""
    with ZeroOutboundTrap() as trap:
        lookup = _mutable_lookup({"dir": str(tmp_path), "code": 1})
        for i in range(2):
            _cycle(tmp_path, _stats("update_all", "lhb_backfill"),
                   NOW + timedelta(minutes=15 * i), lookup_run=lookup)
        core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"


def test_shell_notify_dryrun_gate_and_alert_quadruple():
    """静态核适配层:测试开关追加 --dry-run;升级告警带四元组参数;不改 notify.py。"""
    sh = (SCRIPTS / "self_heal.sh").read_text(encoding="utf-8")
    # 测试期零外发开关:环境变量为 1 时所有 notify 调用追加 --dry-run
    assert 'SELF_HEAL_NOTIFY_DRYRUN") == "1"' in sh
    assert 'cmd.append("--dry-run")' in sh
    # 升级告警四元组:tier/dedup-key/dedup-window/alert-issue/from-prefix
    for frag in ('"--tier", "warning"', '"--dedup-key", f"self_heal_repeat_fail_{task}"',
                 '"--dedup-window", str(core.NOTIFY_DEDUP_WINDOW_SEC)',
                 '"--alert-issue"', '"--from-prefix", "[告警]"'):
        assert frag in sh, f"自愈升级告警缺参数: {frag}"
    # 决策走 core(不把逻辑留两处),白名单仍在 shell(供 #196 形状守卫 grep)
    assert "import self_heal_core as core" in sh
    assert "core.run_cycle(" in sh
    assert 'HEAL_ACTIONS = {' in sh
    assert "PER_TASK_DAILY_LIMIT = 3" in (SCRIPTS / "self_heal_core.py").read_text(encoding="utf-8")
    # 核心模块不引网络/邮件库(纯逻辑)
    core_src = (SCRIPTS / "self_heal_core.py").read_text(encoding="utf-8")
    for banned in ("import urllib", "import smtplib", "import requests", "subprocess"):
        assert banned not in core_src, f"核心决策模块不应含 {banned}"


def test_shell_heredoc_compiles_and_all_notify_go_through_gate():
    """heredoc 里的适配层语法可编译(改 shell 忘测 python 段的高发坑);notify 无旁路。

    bash -n 只查 shell 语法,不查 heredoc 里的 python;这里把 python 段抽出来 compile,
    并断言所有 notify 调用都经 `_notify`(带 --dry-run 门),没有直接 subprocess 调 notify.py。
    """
    sh = (SCRIPTS / "self_heal.sh").read_text(encoding="utf-8")
    head = "<<'PYEOF'"
    start = sh.index("\n", sh.index(head)) + 1  # 跳过 heredoc 标记行剩余部分(如 ` 2>&1`)
    end = sh.index("\nPYEOF\n", start)
    body = sh[start:end]
    compile(body, "self_heal.sh:PYEOF", "exec")
    assert "core.run_cycle(" in body
    # 没有任何其它路径直接调 notify.py(否则 --dry-run 门可能被绕过):
    # 去掉注释后,唯一一处构造 notify 命令的代码行必须落在 `def _notify(args):` 函数体内
    code_lines = [(i, ln) for i, ln in enumerate(sh.splitlines())
                  if ln.strip() and not ln.lstrip().startswith("#") and "notify.py" in ln
                  and "sys.executable" in ln]
    assert len(code_lines) == 1, f"notify.py 出现 {len(code_lines)} 处(期望恰 1 处=_notify 内)"
    fn_start = next(i for i, ln in enumerate(sh.splitlines()) if ln.startswith("def _notify(args):"))
    fn_end = next((i for i, ln in enumerate(sh.splitlines())
                   if i > fn_start and ln.startswith("def ")), len(sh.splitlines()))
    assert fn_start <= code_lines[0][0] < fn_end, "notify 命令不在 _notify 函数体内(绕过 dry-run 门)"


def test_escalate_dedup_window_constant():
    assert core.PER_TASK_DAILY_LIMIT == 3
    assert core.TOTAL_DAILY_LIMIT == 12 >= core.PER_TASK_DAILY_LIMIT
    assert core.ESCALATE_AFTER_FAILS == 2
    assert core.NOTIFY_DEDUP_WINDOW_SEC == 21600