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

2026-10-22 审查 M1~M6 批补(M1/M5 用 `fixtures/selfheal_logs/` 里**真实生产日志**原文,
禁编造样本,§18 L49):
  - M1 双源校验:heal 重跑只写 `<task>_heal.log` ⇒ 旧实现查定时日志必假 FAIL
    (update_all/backfill_evening/rzhb_backfill/lab_auto 四任务各验一次);真实失败仍判 FAIL;
    重跑进行中保持 pending,超 6h 才判卡死。
  - M2 连败计数:任务自恢复归零(否则一辈子只告警一次)+ 发送失败下轮补发(≥阈值持续尝试)。
  - M4 触发前查任务进程,在跑不重复触发;pgrep 出错按未运行处理。
  - M5 按运行**开始**时间归因:heal 前开始的旧运行不许顶包成假 PASS。

纪律(L51):不依赖真实 "今天",所有时点由 datetime 显式注入。
"""
import json
import shutil
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
def _stats(*tasks, last_run=None, exit_code=1, anomaly=False):
    """构造 schedule_stats;last_run 默认相对 NOW(不写死日期,冻结日平移一天仍绿)。

    last_run 允许传 datetime(自动按生产格式 "%Y-%m-%d %H:%M" 落地,少写格式化样板)。
    """
    if last_run is None:
        last_run = NOW - timedelta(minutes=10)
    if isinstance(last_run, datetime):
        last_run = last_run.strftime("%Y-%m-%d %H:%M")
    return [{"task": t, "last_exit": exit_code, "last_run": last_run,
             "log_anomaly": anomaly} for t in tasks]


def _cycle(tmp_path, stats, now, *, lookup_run=None, artifact_probe=None,
           trigger=None, escalate=None, info=None, launch_state=None,
           intraday_skip=None, state_name="state.json", total_limit=None,
           per_task_limit=None, heal_actions=None, labels=None,
           task_running=None):
    """跑一轮 run_cycle,返回 (summary, audit 文本)。

    配额默认值取模块常量(调用时读取),不许在这里再写死 3/12——
    否则常量改坏了用例照样绿,判别力关(§5.3.1 硬约束③)会失效。
    """
    calls = {"trigger": [], "escalate": [], "info": []}
    if per_task_limit is None:
        per_task_limit = core.PER_TASK_DAILY_LIMIT
    if total_limit is None:
        total_limit = core.TOTAL_DAILY_LIMIT

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
        heal_actions=heal_actions or {
            t: ["bash", f"scripts/{t}.sh"]
            for t in {s.get("task") for s in stats
                      if isinstance(s, dict) and s.get("task")}},
        labels=labels or {}, launch_state=launch_state or (lambda label: None),
        trigger=trigger or _trigger, notify_info=info or _info,
        notify_escalate=escalate or _escalate,
        lookup_run=lookup_run, artifact_probe=artifact_probe,
        per_task_limit=per_task_limit, total_limit=total_limit,
        intraday_skip=intraday_skip, task_running=task_running,
    )
    audit_path = tmp_path / "audit.log"
    audit = audit_path.read_text(encoding="utf-8") if audit_path.exists() else ""
    return summary, audit, calls


def _run_after(heal_at, exit_code=0):
    """构造"heal 之后跑完的一次运行记录"(lookup_run 返回值,形状与真实 lookup 一致)。"""
    rec = {"start": (heal_at + timedelta(seconds=10)).isoformat(timespec="seconds"),
           "end": (heal_at + timedelta(minutes=5)).isoformat(timespec="seconds"),
           "exit": exit_code, "source": "test_heal.log"}
    return {"start": rec["start"], "end": rec["end"], "exit": exit_code,
            "source": rec["source"], "pending_start": None, "runs": [rec]}


def _seed_pending(tmp_path, task, heal_at, streak=1, day=None):
    """预置「上一轮 heal 过、本轮待校验」的 state(不依赖真实今天,L51)。"""
    state = core.empty_state(day or heal_at.strftime("%Y-%m-%d"))
    iso = heal_at.isoformat(timespec="seconds")
    state["pending"] = [{"task": task, "heal_at": iso, "reason": "exit=1",
                         "last_exit": 1,
                         "last_run": (heal_at - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")}]
    state["per_task"][task] = {"count": 1, "fail_streak": streak, "last_heal_at": iso}
    state["count"] = 1
    core.save_state(tmp_path / "state.json", state)


# ── M1 真实日志样本(取自云上生产日志,原文照录,未编造)─────────────────────
FIXTURES = Path(__file__).absolute().parent / "fixtures" / "selfheal_logs"


def _real_lookup(log_dir):
    """用真实生产的 gen_schedule_stats 解析器去查夹具日志(=生产同一份实现)。"""
    import gen_schedule_stats as g

    def _lookup(task):
        spec = next(t for t in g.TASKS if t["task"] == task)
        return core.lookup_run_from_logs(task, spec, log_dir, g)
    return _lookup


def _fresh_artifact(repo, rel_path, heal_at):
    """造一个 mtime 晚于 heal 起点的产物(真实文件,不 mock 探针)。"""
    import os
    p = repo / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    ts = heal_at.timestamp() + 120
    os.utime(p, (ts, ts))
    return p


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
    limit = core.PER_TASK_DAILY_LIMIT
    total_triggers = 0
    for i in range(limit + 1):
        now = NOW + timedelta(minutes=15 * i)
        summary, audit, calls = _cycle(tmp_path, stats, now, lookup_run=lookup,
                                       artifact_probe=probe)
        total_triggers += len(calls["trigger"])

    # 前 limit 轮每轮 3 个任务各触发一次;第 limit+1 轮三任务各自达上限被拒
    assert total_triggers == len(tasks) * limit, \
        f"触发了 {total_triggers} 次(期望 {len(tasks) * limit}=3 任务×{limit} 次)"
    assert len(calls["trigger"]) == 0, "达上限后不应再触发"
    assert sorted(s["task"] for s in summary["skipped"]) == sorted(tasks)
    for t in tasks:
        assert f"SKIP_QUOTA {t} reason=per_task_limit" in audit, f"{t} 缺 per_task_limit 审计"
        assert f"task_count={limit}/{limit}" in audit
    state = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    for t in tasks:
        assert state["per_task"][t]["count"] == limit, f"{t} 每任务计数={state['per_task'][t]['count']}"
    assert state["count"] == len(tasks) * limit, f"全站计数={state['count']}"


def test_total_limit_loose_cap(tmp_path):
    """全站总上限 12 次(防总爆炸):达上限后不再触发,info 只发一次。"""
    stats = _stats("a_task", "b_task")
    state = core.empty_state(NOW.strftime("%Y-%m-%d"))
    state["count"] = core.TOTAL_DAILY_LIMIT
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


# ── 证据用例 ③ 连续失败达阈值 → 升级告警(≥阈值持续尝试,靠 6h 去重压噪)──────
def test_escalate_from_threshold_and_keep_trying(tmp_path):
    """M2:`>= 阈值` 而不是 `== 阈值`。

    根因:M2 审查指出「发送失败那轮恰好 == 阈值,之后 streak 继续增长条件永不成立
    ⇒ 一次丢=永久静默」。改成 ≥ 后每轮 FAIL(streak≥2)都尝试,重复发送由 notify.py 的
    6h 去重窗(发送成功才占窗)压住,不会轰炸。
    """
    lookup = _mutable_lookup({"dir": str(tmp_path), "code": 1})
    probe = lambda task, heal_at: (True, "无产物规格(按运行记录判定)")  # noqa: E731
    escalate_calls = []

    def _esc(task, streak, basis):
        escalate_calls.append((task, streak, basis))
        return True

    # heal + 其后校验 FAIL:streak 递增到阈值时发一次,再往后不再发
    need = core.ESCALATE_AFTER_FAILS
    for i in range(need + 3):
        _cycle(tmp_path, _stats("intraday_snapshot"), NOW + timedelta(minutes=15 * i),
               lookup_run=lookup, artifact_probe=probe, escalate=_esc)

    assert escalate_calls, "达到阈值必须尝试发送"
    assert escalate_calls[0][1] == need, f"首次尝试应在 streak=={need},实得 {escalate_calls[0][1]}"
    assert all(c[1] >= need for c in escalate_calls), "不得在阈值前提前告警"
    assert [c[1] for c in escalate_calls] == sorted({c[1] for c in escalate_calls}), \
        "同一 streak 不应重复尝试(每轮最多一条)"
    assert all(c[0] == "intraday_snapshot" and c[2] for c in escalate_calls)
    n = len(escalate_calls)
    audit = (tmp_path / "audit.log").read_text(encoding="utf-8")
    assert f"ESCALATE intraday_snapshot action=notify result=SENT streak={need}" in audit
    assert audit.count("ESCALATE intraday_snapshot action=notify") == n, \
        "每条升级尝试都要落 audit(含被去重压掉前的尝试)"


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
    assert f"task_count={core.PER_TASK_DAILY_LIMIT}/{core.PER_TASK_DAILY_LIMIT}" in audit


def test_corrupt_and_missing_state_no_crash(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{坏 json", encoding="utf-8")
    state = core.load_state(p, NOW.strftime("%Y-%m-%d"))
    assert state["count"] == 0 and state["per_task"] == {}
    state2 = core.load_state(tmp_path / "nope.json", NOW.strftime("%Y-%m-%d"))
    assert state2["count"] == 0
    # 跨天:计数清零,pending / fail_streak 保留
    p.write_text(json.dumps({
        "date": (NOW - timedelta(days=1)).strftime("%Y-%m-%d"), "count": 5,
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
    stats = [{"task": "update_all", "last_exit": 1,
              "last_run": (NOW - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")},
             {"task": "lhb_backfill", "last_exit": 1,
              "last_run": (NOW - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")}]
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
        tmp_path, _stats("update_all",
                         last_run=(now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M")), now,
        intraday_skip=lambda task, n: task == "update_all" and n.isoweekday() <= 5
        and 930 <= int(n.strftime("%H%M")) <= 1530)
    assert calls["trigger"] == []
    assert "SKIP_INTRADAY update_all" in audit


# ── 输入域/回退路径/上下游依赖补测 ──────────────────────────────────────────
def test_malformed_stats_entries_ignored(tmp_path):
    """stats 里非 dict / 缺 last_run / 日期非法 / exit=None 无 anomaly 都不崩、不误触发。"""
    recent = (NOW - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
    stats = [
        "坏条目",
        {"task": "a_task"},                                   # 缺 last_run
        {"task": "b_task", "last_exit": 1, "last_run": "昨天"},
        {"task": "c_task", "last_exit": None,
         "last_run": recent},
        {"task": "d_task", "last_exit": 0, "last_run": recent,
         "log_anomaly": True},                                # 异常标记=要 heal
    ]
    summary, audit, calls = _cycle(tmp_path, stats, NOW,
                                   lookup_run=lambda t: None)
    assert [c[0] for c in calls["trigger"]] == ["d_task"], "只应触发 log_anomaly 任务"
    assert "HEAL d_task" in audit


def test_trigger_failure_not_counted_and_audited(tmp_path):
    """触发失败:记 FAIL、不占配额、不写 pending(下一轮还能再试)。"""
    def _bad_trigger(task, cmd):
        return False, "nohup 失败"
    summary, audit, _ = _cycle(tmp_path, _stats("lhb_backfill"), NOW, trigger=_bad_trigger)
    assert summary["healed"] == []
    assert "FAIL lhb_backfill 触发失败: nohup 失败" in audit
    st = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    assert st["count"] == 0 and st["pending"] == []


def test_lookup_run_exception_keeps_pending(tmp_path):
    """查日志抛异常:本轮不判死,保留 pending 等下一轮(自愈脚本不能因查日志崩)。"""
    def _boom(task):
        raise RuntimeError("日志读不了")
    _cycle(tmp_path, _stats("lab_auto"), NOW, lookup_run=lambda t: None)  # 先触发
    summary, audit, _ = _cycle(tmp_path, _stats("lab_auto"), NOW + timedelta(minutes=15),
                               lookup_run=_boom)
    assert summary["verified"] == []
    st = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    assert len(st["pending"]) == 1, "证据不足应保留 pending"
    assert "lookup_error" in st["pending"][0]


def test_escalate_notify_failure_does_not_block(tmp_path):
    """升级告警发送失败:记 FAILED,但本轮其余 heal 照常进行(自愈不能因通知挂掉)。"""
    lookup = _mutable_lookup({"dir": str(tmp_path), "code": 1})
    state = core.empty_state(NOW.strftime("%Y-%m-%d"))
    state["pending"] = [{"task": "lhb_backfill",
                         "heal_at": (NOW - timedelta(minutes=15)).isoformat(timespec="seconds"),
                         "reason": "exit=1", "last_exit": 1, "last_run": "2026-10-22 17:50"}]
    state["per_task"]["lhb_backfill"] = {"count": 1, "fail_streak": 1, "last_heal_at": None}
    core.save_state(tmp_path / "state.json", state)

    def _boom(task, streak, basis):
        raise RuntimeError("notify 挂了")
    summary, audit, calls = _cycle(tmp_path, _stats("lhb_backfill"), NOW,
                                   lookup_run=lookup, escalate=_boom)
    assert summary["verified"][0]["result"] == "FAIL"
    assert summary["escalated"][0]["sent"] is False
    assert "ESCALATE lhb_backfill action=notify result=FAILED" in audit
    assert len(calls["trigger"]) == 1, "通知失败不应阻塞本轮自愈触发"


def test_probe_artifact_dir_glob(tmp_path):
    """目录型产物:目录不存在/无匹配 → FAIL;有匹配且新鲜 → PASS。"""
    ok, basis = core.probe_artifact(tmp_path, "etf_national_team", NOW)
    assert not ok and "产物目录缺失" in basis
    d = tmp_path / "static-site" / "data" / "etf"
    d.mkdir(parents=True)
    ok, basis = core.probe_artifact(tmp_path, "etf_national_team", NOW)
    assert not ok and "无匹配" in basis
    f = d / "20261022.json"
    f.write_text("{}", encoding="utf-8")
    import os
    ts = NOW.timestamp() + 60
    os.utime(f, (ts, ts))
    ok, basis = core.probe_artifact(tmp_path, "etf_national_team", NOW)
    assert ok and "20261022.json" in basis


def test_negative_and_bad_counts_clamped(tmp_path):
    """旧 state 里的负数/非数字计数一律夹到 0(坏数据不能把配额算成负数白送额度)。"""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "date": NOW.strftime("%Y-%m-%d"), "count": -5,
        "per_task": {"update_all": {"count": -3, "fail_streak": "x"}},
    }), encoding="utf-8")
    st = core.load_state(p, NOW.strftime("%Y-%m-%d"))
    assert st["count"] == 0 and st["per_task"]["update_all"]["count"] == 0
    assert st["per_task"]["update_all"]["fail_streak"] == 0
    # 空 stats 不崩、不触发
    summary, _a, calls = _cycle(tmp_path, [], NOW)
    assert calls["trigger"] == [] and summary["healed"] == []


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


def test_shell_notify_gate_and_param_quadruple():
    """静态核适配层:测试开关追加 --dry-run;升级告警四元组参数与实际实现一致。

    M6:`--alert-issue` 是**死参数**(notify.py:3167 只在 tier=critical 时写
    data/alerts/latest.md,warning 级带它不产生任何效果,还会误导值班以为 latest.md
    有记录)⇒ 已删除,这里反过来断言它**不在**,防有人再"补回去"。
    """
    sh = (SCRIPTS / "self_heal.sh").read_text(encoding="utf-8")
    # 测试期零外发开关:环境变量为 1 时所有 notify 调用追加 --dry-run
    assert 'SELF_HEAL_NOTIFY_DRYRUN") == "1"' in sh
    assert 'cmd.append("--dry-run")' in sh
    # 升级告警四元组:tier/dedup-key/dedup-window/from-prefix
    for frag in ('"--tier", "warning"', '"--dedup-key", f"self_heal_repeat_fail_{task}"',
                 '"--dedup-window", str(core.NOTIFY_DEDUP_WINDOW_SEC)',
                 '"--from-prefix", "[告警]"'):
        assert frag in sh, f"自愈升级告警缺参数: {frag}"
    assert '"--alert-issue"' not in sh, "warning 级 --alert-issue 是死参数,不许再带"
    # M3:lab_auto 必须带 force,否则非交易日重跑直接跳过 = 白烧配额 + 假 FAIL
    assert '"scripts/update_lab.sh", "force"' in sh
    # 决策走 core(不把逻辑留两处),白名单仍在 shell(供 #196 形状守卫 grep)
    assert "import self_heal_core as core" in sh
    assert "core.run_cycle(" in sh
    assert "core.lookup_run_from_logs(" in sh, "校验必须走 core 的双源解析(不许退回单源)"
    assert "task_running=task_process_running" in sh, "M4 进程检查未接入 run_cycle"
    assert "PGREP_PATTERNS" in sh and '"pgrep", "-f", pat' in sh
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


# ── M1 双源校验:用**真实生产日志样本**(夹具原文照录,未编造;§18 L49)──────────
def test_m1_update_all_heal_log_success_is_pass(tmp_path):
    """heal 重跑只写 update_all_heal.log(定时日志里根本没这次)。

    旧实现只读 launchd 日志 ⇒ 「heal 后无新运行记录」⇒ 每次 heal 都假 FAIL。
    真实样本:2026-09-15 00:07:01→00:44:56(生产 heal.log 原文)。
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    shutil.copy(FIXTURES / "update_all_heal.log", log_dir / "update_all_heal.log")
    heal_at = datetime(2026, 9, 15, 0, 7, 0)
    now = heal_at + timedelta(hours=1)
    _seed_pending(tmp_path, "update_all", heal_at)
    _fresh_artifact(tmp_path, "static-site/data/overview.json", heal_at)
    summary, audit, _ = _cycle(
        tmp_path, _stats("update_all", last_run=now - timedelta(minutes=10)), now,
        lookup_run=_real_lookup(log_dir),
        artifact_probe=lambda task, ha: core.probe_artifact(tmp_path, task, ha))
    ev = summary["verified"][0]
    assert ev["result"] == "PASS", f"heal 成功却判 {ev['result']}: {ev['basis']}"
    assert "update_all_heal.log" in ev["basis"], "证据来源必须是 heal.log"
    assert "2026-09-15 00:44:56" in ev["basis"]
    assert "VERIFY update_all action=heal result=PASS" in audit


def test_m1_backfill_evening_heal_log_not_false_fail(tmp_path):
    """backfill_evening:定时日志最后一条是 10-20 21:36 退出码=1(heal 之前),
    heal.log 里 10-21 00:22:03→00:23:19 退出码=0 才是本次重跑 → 旧实现必假 FAIL。"""
    heal_at = datetime(2026, 10, 21, 0, 20, 0)
    now = heal_at + timedelta(hours=3, minutes=40)   # 已超 3h 判定时限
    _seed_pending(tmp_path, "backfill_evening", heal_at)
    summary, audit, _ = _cycle(
        tmp_path, _stats("backfill_evening", last_run=now - timedelta(minutes=10)), now,
        lookup_run=_real_lookup(FIXTURES))
    ev = summary["verified"][0]
    assert ev["result"] == "PASS", f"假 FAIL 未修掉: {ev['basis']}"
    assert "backfill_evening_heal.log" in ev["basis"] and "00:23:19" in ev["basis"]


def test_m1_lab_auto_force_rerun_is_pass(tmp_path):
    """lab_auto:定时那轮 09-22 19:00→20:30 超时放弃退出码=1(heal 之前);
    heal.log 里 09-23 00:07:02→00:45:14 成功(生产原文,正是 M3 加 force 后跑出来的)。"""
    heal_at = datetime(2026, 9, 23, 0, 7, 0)
    now = heal_at + timedelta(hours=1)
    _seed_pending(tmp_path, "lab_auto", heal_at)
    _fresh_artifact(tmp_path, "static-site/data/lab/lab_backtest.json", heal_at)
    summary, _audit, _ = _cycle(
        tmp_path, _stats("lab_auto", last_run=now - timedelta(minutes=10)), now,
        lookup_run=_real_lookup(FIXTURES),
        artifact_probe=lambda task, ha: core.probe_artifact(tmp_path, task, ha))
    ev = summary["verified"][0]
    assert ev["result"] == "PASS", f"非交易日/超时后 heal 仍假 FAIL: {ev['basis']}"
    assert "lab_auto_heal.log" in ev["basis"]


def test_m1_rzhb_backfill_no_false_fail(tmp_path):
    """rzhb_backfill:heal.log 里 08:00:01→08:00:03 退出码=0(生产原文样本)。"""
    heal_at = datetime(2026, 10, 22, 8, 0, 0)
    now = heal_at + timedelta(minutes=10)
    _seed_pending(tmp_path, "rzhb_backfill", heal_at)
    summary, _audit, _ = _cycle(
        tmp_path, _stats("rzhb_backfill", last_run=now - timedelta(minutes=5)), now,
        lookup_run=_real_lookup(FIXTURES))
    ev = summary["verified"][0]
    assert ev["result"] == "PASS", f"rzhb 假 FAIL 未修掉: {ev['basis']}"


def test_m1_etf_heal_failure_is_fail(tmp_path):
    """ETF 汪汪队 heal 重跑真的失败(生产原文 exit=1)→ 必须判 FAIL,不能因为双源就一律放行。"""
    heal_at = datetime(2026, 10, 22, 0, 37, 0)
    now = heal_at + timedelta(minutes=30)
    _seed_pending(tmp_path, "etf_national_team", heal_at)
    _fresh_artifact(tmp_path, "static-site/data/etf/20261022.json", heal_at)
    summary, _audit, _ = _cycle(
        tmp_path, _stats("etf_national_team", last_run=now - timedelta(minutes=5)), now,
        lookup_run=_real_lookup(FIXTURES),
        artifact_probe=lambda task, ha: core.probe_artifact(tmp_path, task, ha))
    ev = summary["verified"][0]
    assert ev["result"] == "FAIL", f"heal 失败被误判 {ev['result']}: {ev['basis']}"
    assert "退出码=1" in ev["basis"]


def test_m1_inflight_run_keeps_pending_then_stuck_fails(tmp_path):
    """重跑进行中(有开始无结束)不判 FAIL,留到下轮;超过 6h 才判「疑似卡死」。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    shutil.copy(FIXTURES / "etf_national_team_heal_inflight.log",
                log_dir / "etf_national_team_heal.log")
    heal_at = datetime(2026, 10, 22, 0, 37, 0)
    _seed_pending(tmp_path, "etf_national_team", heal_at)
    # ① 还在跑(3 分钟后):不判死,保留 pending
    summary, audit, _ = _cycle(
        tmp_path, _stats("etf_national_team", last_run=heal_at - timedelta(minutes=5)),
        heal_at + timedelta(minutes=3), lookup_run=_real_lookup(log_dir),
        artifact_probe=lambda task, ha: (True, "无产物规格(按运行记录判定)"))
    assert summary["verified"] == [], "进行中不应产出 PASS/FAIL"
    assert "VERIFY" not in audit
    st = core.load_state(tmp_path / "state.json", "2026-10-22")
    assert len(st["pending"]) == 1, "进行中必须保留 pending 等下轮"
    # ② 7 小时后仍未结束:判卡死 FAIL
    summary2, audit2, _ = _cycle(
        tmp_path, _stats("etf_national_team", last_run=heal_at - timedelta(minutes=5)),
        heal_at + timedelta(hours=7), lookup_run=_real_lookup(log_dir),
        artifact_probe=lambda task, ha: (True, "无产物规格(按运行记录判定)"))
    assert summary2["verified"][0]["result"] == "FAIL"
    assert "疑似卡死" in summary2["verified"][0]["basis"]


# ── M5 旧运行不许顶包成「本次重跑」(60s 容差误归因)─────────────────────────
def test_m5_stale_run_not_attributed_to_heal(tmp_path):
    """heal 起点 18:57:00,最近一次运行 17:50:01→18:56:16(heal 之前开始)。

    旧口径只看 end + 60s 容差 ⇒ 18:56:16 ≥ 18:56:00 ⇒ 被当成本次重跑(还退出码 0)= 假 PASS。
    新口径按**开始时间**判:17:50:01 < heal 起点 ⇒ 不是本次重跑 ⇒ 超时 FAIL 并写明原因。
    """
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    shutil.copy(FIXTURES / "update_all_launchd.log", log_dir / "update_all_launchd.log")
    heal_at = datetime(2026, 10, 21, 18, 57, 0)
    now = heal_at + timedelta(hours=3, minutes=5)
    _seed_pending(tmp_path, "update_all", heal_at)
    summary, audit, _ = _cycle(
        tmp_path, _stats("update_all", last_run=heal_at - timedelta(minutes=20)), now,
        lookup_run=_real_lookup(log_dir),
        artifact_probe=lambda task, ha: (True, "无产物规格(按运行记录判定)"))
    ev = summary["verified"][0]
    assert ev["result"] == "FAIL", f"旧运行被顶包成本次重跑(假 PASS): {ev['basis']}"
    assert "开始于 heal 之前" in ev["basis"], f"依据未说明旧运行: {ev['basis']}"
    assert "2026-10-21 17:50:01" in ev["basis"]


def test_m5_next_scheduled_run_does_not_mask_heal(tmp_path):
    """高频任务:heal 后先有本次重跑(失败),之后还有一次定时跑(成功)。

    只看 end 最大者会把定时跑当成本次 heal 的成果 = 假 PASS。必须认「heal 后**开始**的
    第一条」= 本次重跑,按其退出码判 FAIL。
    """
    heal_at = datetime(2026, 10, 22, 10, 0, 0)
    run_heal = {"start": (heal_at + timedelta(seconds=8)).isoformat(timespec="seconds"),
                "end": (heal_at + timedelta(minutes=2)).isoformat(timespec="seconds"),
                "exit": 1, "source": "intraday_snapshot_heal.log"}
    run_sched = {"start": (heal_at + timedelta(minutes=30)).isoformat(timespec="seconds"),
                 "end": (heal_at + timedelta(minutes=31)).isoformat(timespec="seconds"),
                 "exit": 0, "source": "intraday_snapshot_launchd.log"}
    lookup = lambda task: {**run_sched, "runs": [run_heal, run_sched]}  # noqa: E731
    _seed_pending(tmp_path, "intraday_snapshot", heal_at)
    summary, _audit, _ = _cycle(
        tmp_path, _stats("intraday_snapshot", last_run=heal_at - timedelta(minutes=5)),
        heal_at + timedelta(hours=1), lookup_run=lookup,
        artifact_probe=lambda task, ha: (True, "无产物规格(按运行记录判定)"))
    ev = summary["verified"][0]
    assert ev["result"] == "FAIL", f"定时跑顶包成假 PASS: {ev['basis']}"
    assert "intraday_snapshot_heal.log" in ev["basis"] and "退出码=1" in ev["basis"]


# ── M2 连败计数:任务自恢复归零 + 发送失败下轮补发 ───────────────────────────
def test_m2_streak_reset_when_task_self_recovers(tmp_path):
    """任务靠下一次定时跑自己好了 → 连败归零,下次事故还能重新告警(否则一辈子只响一次)。"""
    heal_at = NOW - timedelta(hours=2)
    _seed_pending(tmp_path, "update_all", heal_at, streak=2)
    state = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    state["pending"] = []                      # 已经校验完,没有新证据
    state["escalate_pending"]["update_all"] = {"streak": 2, "basis": "旧", "since": "x"}
    core.save_state(tmp_path / "state.json", state)
    stats = _stats("update_all", last_run=NOW - timedelta(minutes=30), exit_code=0)
    summary, audit, calls = _cycle(tmp_path, stats, NOW)
    assert calls["trigger"] == []
    assert "STREAK_RESET update_all reason=task_recovered" in audit
    st = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    assert st["per_task"]["update_all"]["fail_streak"] == 0
    assert st["escalate_pending"] == {}


def test_m2_streak_not_reset_by_success_not_strictly_after_heal(tmp_path):
    """「heal 之前那次旧成功」不算恢复(否则本次 heal 的失败会被旧成功抹掉)。

    边界:stats 的 last_run 只到分钟,heal 也在同一分钟时无法区分先后 ⇒ 保守不清零。
    """
    _seed_pending(tmp_path, "update_all", NOW - timedelta(minutes=10), streak=2)
    state = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    state["pending"] = []
    core.save_state(tmp_path / "state.json", state)
    stats = _stats("update_all", last_run=NOW - timedelta(minutes=10), exit_code=0)
    _summary, audit, _ = _cycle(tmp_path, stats, NOW)
    st = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    assert st["per_task"]["update_all"]["fail_streak"] == 2, "同一分钟/更早的成功不得清零连败"
    assert "STREAK_RESET" not in audit


def test_m2_escalate_send_failure_retried_next_round(tmp_path):
    """发送失败 → 记 escalate_pending,下一轮补发(一次丢不许变成永久静默)。"""
    heal_at = NOW - timedelta(minutes=15)
    _seed_pending(tmp_path, "lhb_backfill", heal_at, streak=1)
    lookup = lambda task: _run_after(heal_at, 1)          # noqa: E731
    probe = lambda task, ha: (True, "无产物规格(按运行记录判定)")  # noqa: E731

    def _fail_send(task, streak, basis):
        return False

    summary, audit, _ = _cycle(
        tmp_path, _stats("lhb_backfill", last_run=NOW - timedelta(minutes=5)), NOW,
        lookup_run=lookup, artifact_probe=probe, escalate=_fail_send)
    assert summary["verified"][0]["result"] == "FAIL"
    assert summary["escalated"][0]["sent"] is False
    assert "ESCALATE lhb_backfill action=notify result=FAILED" in audit
    st = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    assert "lhb_backfill" in st["escalate_pending"], "发送失败必须记待补发"

    sent = []
    summary2, audit2, _ = _cycle(
        tmp_path, _stats("lhb_backfill", last_run=NOW - timedelta(minutes=5)),
        NOW + timedelta(minutes=15), lookup_run=lookup, artifact_probe=probe,
        escalate=lambda task, streak, basis: sent.append((task, streak)) or True)
    assert sent == [("lhb_backfill", 2)], f"下轮未补发: {sent}"
    assert summary2["escalated"][0]["retry"] is True
    assert "retry=1" in audit2
    st2 = core.load_state(tmp_path / "state.json", NOW.strftime("%Y-%m-%d"))
    assert st2["escalate_pending"] == {}, "补发成功后必须清掉待补发标记"


# ── M4 任务进程在跑 → 不重复触发(防撞锁 + 连环假 FAIL)──────────────────────
def test_m4_process_running_skips_trigger(tmp_path):
    summary, audit, calls = _cycle(tmp_path, _stats("update_all"), NOW,
                                   task_running=lambda task: True)
    assert calls["trigger"] == [], "任务脚本还在跑时不许重复触发"
    assert "SKIP_RUNNING_PROC update_all reason=process_running" in audit
    assert summary["skipped"][0]["reason"] == "process_running"


def test_m4_process_check_error_does_not_block_heal(tmp_path):
    """pgrep 自己出错 → 按未运行处理(自愈不能因为查不到进程就停摆),但要留 WARN。"""
    def _boom(task):
        raise OSError("pgrep 不可用")
    _summary, audit, calls = _cycle(tmp_path, _stats("lhb_backfill"), NOW,
                                    task_running=_boom)
    assert [c[0] for c in calls["trigger"]] == ["lhb_backfill"]
    assert "WARN lhb_backfill 进程检查失败(按未运行处理)" in audit