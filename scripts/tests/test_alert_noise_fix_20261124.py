# -*- coding: utf-8 -*-
"""2026-11-24 告警噪音三修验收: 反例逐个断言(task book 要求)。

① FOF「无法判定」分支: 稳定事件 + 有界兜底, 保持 critical 立即首报 + 稳定去重
   (复审判定: 降 warning 属动已上线行为, 已还原)。
   反例: 同一旧格式进度文件连续 48 轮 / 重启后重读 / 并发重入 ⇒ 同 event 同 phase,
   通知队列只有 1 条; 文件恢复 ⇒ 恢复只发 1 次; 真实业务故障仍走原首报路径。
② 监控首报消费同 snapshot ACK 对账 + 30min 新鲜度合同(复审 P1-1: 数据源 = 持久
   journal 按 invocation 轮次对齐, 不读 /run 瞬态目录)。
   反例: 客户端超时但服务端已收且数据新鲜 ⇒ pending(不造故障/恢复对);
   真失联 / 401 / 503 / ACK 读不出 / 任务没启动 / 新鲜度超期 ⇒ 仍首报。
③ 「本轮无告警邮件」状态补位默认关。
   反例: 不设环境变量时正常轮零补位邮件且零状态落签; 显式 =1 可逆重开
   (重开路径的完整验收在 test_309_conclusion_email_20261026.py)。

自测零真实外发(§18 L48): 本文件 autouse 把 subprocess 起进程直接判违规; FOF 的
dispatch 被替换成本地记录器; notify 侧只直接调用纯路由函数并读临时 REPO 的 buffer,
email/telegram/feishu transport 根本不会被触达。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "tests"))

import _monitor_conclusion_309 as m309  # noqa: E402

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_process():
    """自测护栏: 本文件任何真实子进程启动 = 违规(证明零真实外发)。"""
    real_run, real_popen = subprocess.run, subprocess.Popen

    def denied(*a, **kw):
        raise AssertionError("测试不许启动真实子进程(零外发证据)")

    subprocess.run, subprocess.Popen = denied, denied
    try:
        yield
    finally:
        subprocess.run, subprocess.Popen = real_run, real_popen


# ─────────────────────────── ① FOF 无法判定 ───────────────────────────
def _load_fof():
    spec = importlib.util.spec_from_file_location("fof_under_test", SCRIPTS / "check_fof_backfill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _state(repo: Path) -> dict:
    path = repo / "data" / "alert_state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


OLD_FORMAT = {"version": 1, "last_run": "2026-11-23T21:00:00"}  # 缺 last_runs(L60 现场旧格式)
VALID = {
    "version": 1,
    "last_runs": {"recent": {"selected": 3, "attempted": 3, "stage_status": "complete"}},
    "backfill_pending": [], "backfill_pending_since": {}, "backfill_last_attempt": {},
}


@pytest.fixture
def fof(tmp_path, monkeypatch):
    mod = _load_fof()
    calls = []

    def fake_dispatch(repo, notify_py, subject, body, refs, **kw):
        calls.append({"subject": subject, "body": body,
                      "refs": [dict(r) for r in refs] if refs else None, "kw": dict(kw)})
        return "deferred"

    monkeypatch.setattr(mod, "dispatch", fake_dispatch)
    monkeypatch.setattr(mod, "_load_trading_dates", lambda: set())
    return mod, tmp_path, calls


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(mod, repo: Path, progress: Path) -> int:
    argv = ["--repo", str(repo), "--progress", str(progress), "--notify", "--today", "20261124"]
    old = sys.argv
    sys.argv = ["check_fof_backfill.py", *argv]
    try:
        return mod.main()
    finally:
        sys.argv = old


def test_fof_old_progress_48_polls_same_event_and_restart_reuses_it(fof):
    mod, repo, calls = fof
    progress = repo / "data" / "public_fund.fof-nav-progress.json"
    _write(progress, OLD_FORMAT)
    for _ in range(48):
        assert _run(mod, repo, progress) == 2

    assert len(calls) == 48
    assert all(c["refs"] and len(c["refs"]) == 1 for c in calls)
    assert {c["refs"][0]["event_id"] for c in calls} == {calls[0]["refs"][0]["event_id"]}
    assert {c["refs"][0]["phase"] for c in calls} == {"active"}

    state = _state(repo)
    assert len(state) == 1, state  # 同一持续事故=同一条事件
    (entry,) = state.values()
    obs = entry["observation"]
    assert obs["exception_type"] == "ValueError"
    assert "last_runs" in obs["exception_detail"]
    assert obs["progress_version"] == 1
    assert isinstance(obs["progress_sha256"], str) and len(obs["progress_sha256"]) == 64
    assert obs["first_expected_at"] and obs["progress_last_write"]
    body = calls[-1]["body"]
    assert "last_runs" in body and "版本=1" in body and "sha256=" in body

    # 「重启」= 新进程重新加载模块后读同一份磁盘状态 ⇒ 仍是同一事件。
    mod2 = _load_fof()
    mod2.dispatch = mod.dispatch
    mod2._load_trading_dates = mod._load_trading_dates
    assert _run(mod2, repo, progress) == 2
    assert calls[-1]["refs"][0]["event_id"] == calls[0]["refs"][0]["event_id"]
    assert len(_state(repo)) == 1


def test_fof_observable_queue_has_one_entry_per_event_and_phase(fof, tmp_path, monkeypatch):
    """同 event 同 phase 连续入队只留 1 条(真实 notify 去重代码, 不启动进程)。"""
    mod, repo, calls = fof
    progress = repo / "data" / "public_fund.fof-nav-progress.json"
    _write(progress, OLD_FORMAT)
    assert _run(mod, repo, progress) == 2
    refs = calls[-1]["refs"]

    for key in ("REPO", "GIT_REPO", "MAIN_REPO"):
        monkeypatch.setenv(key, str(tmp_path))
    spec = importlib.util.spec_from_file_location("notify_under_test", SCRIPTS / "notify.py")
    notify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notify)

    assert notify.defer_warning("[告警] FOF", "body", "[告警]", ops_event_refs=refs) == "enqueued"
    assert notify.defer_warning("[告警] FOF", "body", "[告警]", ops_event_refs=refs) == "enqueued"
    lines = (tmp_path / "data" / "alerts" / "warning_buffer.jsonl").read_text().splitlines()
    assert len(lines) == 1, lines


def test_fof_unobservable_concurrent_reentry_gets_same_event(tmp_path):
    import ops_legacy_events as ops

    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    key = "fof_backfill|" + "a" * 64
    found, barrier = [], threading.Barrier(2)

    def worker():
        barrier.wait()
        _facts, refs = ops.observe_failure(repo, key, "boom", {"exception_type": "ValueError"},
                                           cause_key="ValueError|1")
        found.append(refs[0]["event_id"])

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(found)) == 1, found  # 并发首见不许各造一个事件
    assert len(_state(repo)) == 1


def test_fof_recovery_sent_once_then_business_path_resumes(fof):
    mod, repo, calls = fof
    progress = repo / "data" / "public_fund.fof-nav-progress.json"
    _write(progress, OLD_FORMAT)
    assert _run(mod, repo, progress) == 2
    event_id = calls[-1]["refs"][0]["event_id"]

    _write(progress, VALID)
    assert _run(mod, repo, progress) == 0
    recoveries = [c for c in calls if c["refs"] and c["refs"][0]["phase"] == "recovery"]
    assert len(recoveries) == 1
    assert recoveries[0]["refs"][0]["event_id"] == event_id
    assert recoveries[0]["subject"].startswith("[恢复]")

    # 第二次健康轮: 不重复恢复、不重复首报
    assert _run(mod, repo, progress) == 0
    assert len([c for c in calls if c["refs"] and c["refs"][0]["phase"] == "recovery"]) == 1
    state_key = recoveries[0]["refs"][0]["key"]
    assert _state(repo)[state_key]["status"] == "recovered"

    # 幂等: 已恢复后再 close 一次拿不到 ref(并发/重复收口都不会二次 [恢复])。
    import ops_legacy_events as ops
    assert ops.close_observe_failure(repo, state_key, "again") is None


def test_fof_real_business_fault_still_first_reports_via_original_path(fof):
    mod, repo, calls = fof
    progress = repo / "data" / "public_fund.fof-nav-progress.json"
    bad = dict(VALID)
    bad["last_runs"] = {"recent": {"selected": 5, "attempted": 2, "stage_status": "stopped"}}
    _write(progress, bad)
    assert _run(mod, repo, progress) == 1
    call = calls[-1]
    assert "覆盖率" in call["subject"] or "回补" in call["subject"]
    assert call["refs"] and call["refs"][0]["phase"] == "active"
    assert call["kw"].get("warning") is True


def test_fof_broken_shared_state_fallback_is_stable_and_bounded(fof):
    mod, repo, calls = fof
    progress = repo / "data" / "public_fund.fof-nav-progress.json"
    _write(progress, OLD_FORMAT)
    (repo / "data" / "alert_state.json").write_text("{not-json", encoding="utf-8")
    for _ in range(3):
        assert _run(mod, repo, progress) == 2
    fallbacks = [c for c in calls if c["refs"] is None]
    assert len(fallbacks) == 3
    keys = {c["kw"].get("dedup_key") for c in fallbacks}
    assert len(keys) == 1 and next(iter(keys)).startswith("fof_backfill|")
    # 严重级不降级(复审 P1-2): 仍 critical, 但有稳定 key + 6h 窗口 ⇒ 不会每轮轰炸。
    assert {c["kw"].get("tier") for c in fallbacks} == {"critical"}
    assert all(c["kw"].get("dedup_key") for c in fallbacks)


def test_ops_dispatch_fallback_uses_stable_key_not_zero_window(monkeypatch, tmp_path):
    import ops_legacy_events as ops

    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        rf = Path(cmd[cmd.index("--result-file") + 1])
        rf.write_text(json.dumps({"status": "deferred"}))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(ops.subprocess, "run", fake_run)
    key = "fof_backfill|" + "b" * 64
    assert ops.dispatch(tmp_path, tmp_path / "notify.py", "s", "b", None,
                        warning=True, tier="warning", dedup_key=key,
                        source="test") == "deferred"
    cmd = seen[-1]
    assert cmd[cmd.index("--dedup-key") + 1] == key
    assert cmd[cmd.index("--dedup-window") + 1] == str(ops.UNOBSERVABLE_DEDUP_WINDOW) != "0"
    assert cmd[cmd.index("--tier") + 1] == "warning"
    assert "--ops-event-refs" not in cmd


# ───────────── ② monitor 首报消费 ACK 对账(复审 P1-1: 持久 journal, 无 runtime 目录) ─────────────
def _decision(evidence):
    return m309.namespace()["monitor_ack_decision"](evidence, NOW)


def _evidence(raw, invocation):
    return m309.namespace()["monitor_ack_evidence"](
        now=NOW, journal_loader=lambda now: raw, unit_state={"invocation_id": invocation})


def _t(minutes_ago):
    return NOW - timedelta(minutes=minutes_ago)


def _jline(at, invocation, snapshot, ok, late_ack=None):
    """journalctl -o json 一行: 字段/嵌套 MESSAGE 形状与 ops_monitor.py:1492-1497 一致。"""
    msg = {"snapshot_id": snapshot, "checks": 7, "delivery_ok": ok, "collect_only": False,
           "delivery": {"attempts": 3 if not ok else 1}}
    if late_ack is not None:
        msg["late_ack"] = late_ack
    row = {"__REALTIME_TIMESTAMP": str(int(at.timestamp() * 1000000)),
           "UNIT": "trade-ops-monitor.service",
           "_SYSTEMD_UNIT": "trade-ops-monitor.service",
           "_SYSTEMD_INVOCATION_ID": invocation,
           "SYSLOG_IDENTIFIER": "trade-ops-monitor",
           "MESSAGE": json.dumps(msg, ensure_ascii=False)}
    return json.dumps(row, ensure_ascii=False)


def _late_ok(snapshot, minutes_ago):
    return {"state": "late_ok", "snapshot_id": snapshot,
            "received_at": _t(minutes_ago).isoformat().replace("+00:00", "Z")}


# 云上真实四轮(2026-11-17 18:45/19:00/19:15/19:30 CST, 取自
# /tmp/codex-reports/alert-root-cause-20261123-code-evidence/monitor-sample.json 657 条真实 journal):
# A/B/C 三轮 delivery_ok=false, 每轮 late_ack 都指向上一轮并 late_ok —— 正是「13 首报 / 11 late_ok」
# 的现场形态; D 轮恢复成功。id/invocation 全为真实值, 不是自造样本(L49)。
INV_A = "21437e9888be45d0aa345693bba80e8c"
INV_B = "75db6afe7879400cbc6b08c9f14e505d"
INV_C = "a753db2357bf445480878aa682df0568"
INV_D = "6c77f760cc1648b5904cc759d61ab8b0"
SNAP_A = "8c1bb993-d38c-4ccb-a416-7858dfcc17a5"
SNAP_B = "21c8bae7-90bc-4557-a405-2000d2793b87"
SNAP_C = "ecbdbeab-7abc-4d43-9066-fd03627bfba3"
SNAP_D = "a2d0e9d5-9ee8-4dd4-a786-3adef187d28f"


def test_monitor_journal_fixture_matches_ops_monitor_parser():
    """尺子先验: 同一份 journal 行喂 ops_monitor 的真实解析函数, 必须解出同一 snapshot。

    证明测试样本字段/嵌套 MESSAGE 形状是真的(L49 假样本养绿教训), 不是自造字段。
    """
    import ops_monitor

    raw = "\n".join([_jline(_t(16), INV_A, SNAP_A, False),
                     _jline(_t(1), INV_B, SNAP_B, False, _late_ok(SNAP_A, 15.9))])
    got = ops_monitor.previous_failed_delivery(raw, _t(1).timestamp(), 1800)
    assert got is not None and got[1] == SNAP_A
    assert _evidence(raw, INV_A)["alarmed_snapshot_id"] == SNAP_A


def test_monitor_real_cloud_chain_aligns_alarmed_round_and_pending():
    """真实三轮生命周期: 被告警轮按 invocation 对齐, ACK 由下一轮携带; 新鲜 ⇒ pending。"""
    raw = "\n".join([
        _jline(_t(31), INV_A, SNAP_A, False),
        _jline(_t(16), INV_B, SNAP_B, False, _late_ok(SNAP_A, 31.1)),
        _jline(_t(1), INV_C, SNAP_C, False, _late_ok(SNAP_B, 16.1)),
    ])
    ev = _evidence(raw, INV_B)  # 被告警轮 = B(而不是最新的 C)
    assert ev["read_ok"] and ev["alarmed_snapshot_id"] == SNAP_B
    assert ev["verdict_kind"] == "fresh" and ev["chain_failed_rounds"] == 3
    dec = _decision(ev)
    assert dec["action"] == "pending" and dec["reason"] == "server_received_and_fresh"
    # 同一份 journal, 被告警轮换成 A: A 的回执已 31 分钟 ⇒ 新鲜度超期, 仍首报。
    ev_a = _evidence(raw, INV_A)
    assert ev_a["alarmed_snapshot_id"] == SNAP_A
    assert _decision(ev_a)["reason"] == "late_ok_but_freshness_expired"


def test_monitor_three_polls_same_snapshot_make_no_fault_or_recovery_pair():
    raw = "\n".join([_jline(_t(2), INV_A, SNAP_A, False),
                     _jline(_t(1), INV_B, SNAP_B, False, _late_ok(SNAP_A, 1.2))])
    decisions = [_decision(_evidence(raw, INV_A)) for _ in range(3)]
    assert [x["action"] for x in decisions] == ["pending"] * 3

    concl = m309.namespace()["_build_conclusion"](
        [], NOW, unit_pending=[{"task": "ops_monitor", "unit": "trade-ops-monitor.service",
                                "reason": decisions[0]["reason"]}])
    assert not concl.startswith("OK")
    assert "monitor ACK 对账暂未确认" in concl
    assert "ops-monitor" in concl  # _unit_short_name 去掉 .service 后缀


def test_monitor_late_ack_for_older_snapshot_is_not_borrowed():
    raw = "\n".join([_jline(_t(10), INV_A, SNAP_A, False),
                     _jline(_t(2), INV_B, SNAP_B, False, _late_ok(SNAP_A, 9.9))])
    ev = _evidence(raw, INV_B)
    assert ev["alarmed_snapshot_id"] == SNAP_B
    assert ev["verdict_kind"] == "absent"
    assert _decision(ev)["action"] == "pending"  # 下一轮还没对账, 链起点 10min 在预算内


def test_monitor_true_loss_first_reports():
    raw = "\n".join([_jline(_t(2), INV_A, SNAP_A, False),
                     _jline(_t(1), INV_B, SNAP_B, False,
                            {"state": "lost", "snapshot_id": SNAP_A})])
    assert _decision(_evidence(raw, INV_A))["reason"] == "server_confirmed_not_received"


def test_monitor_sustained_loss_in_chain_first_reports():
    """最新一轮回执未到, 但链上更早一轮已定论 lost ⇒ 真失联不许被继续 pending 掉。"""
    raw = "\n".join([_jline(_t(20), INV_A, SNAP_A, False),
                     _jline(_t(5), INV_B, SNAP_B, False,
                            {"state": "lost", "snapshot_id": SNAP_A})])
    ev = _evidence(raw, INV_B)
    assert ev["verdict_kind"] == "absent" and ev["bad_verdict"]["kind"] == "lost"
    assert _decision(ev)["reason"] == "server_confirmed_not_received"


@pytest.mark.parametrize("status", [401, 403, 503])
def test_monitor_ack_http_error_first_reports(status):
    raw = "\n".join([_jline(_t(2), INV_A, SNAP_A, False),
                     _jline(_t(1), INV_B, SNAP_B, False,
                            {"state": "unknown", "snapshot_id": SNAP_A, "http_status": status})])
    dec = _decision(_evidence(raw, INV_A))
    assert dec["action"] == "report" and dec["reason"] == "ack_http_error"


@pytest.mark.parametrize("case", ["missing", "unreadable", "corrupt", "no-failed-round",
                                  "wrong-unit", "round-missing"])
def test_monitor_unreadable_or_never_started_first_reports(case):
    ns = m309.namespace()

    def loader(now):
        if case == "unreadable":
            raise OSError("journalctl rc=1")
        if case == "missing":
            return ""
        if case == "corrupt":
            return "{oops\nnot-json"
        if case == "wrong-unit":
            row = json.loads(_jline(_t(1), INV_A, SNAP_A, False))
            row["_SYSTEMD_UNIT"] = "trade-other.service"
            return json.dumps(row)
        if case == "no-failed-round":
            return _jline(_t(1), INV_A, SNAP_A, True)
        return _jline(_t(1), INV_A, SNAP_A, False)  # round-missing: 被告警轮是 B
    ev = ns["monitor_ack_evidence"](now=NOW, journal_loader=loader,
                                    unit_state={"invocation_id": INV_B})
    dec = ns["monitor_ack_decision"](ev, NOW)
    assert dec["action"] == "report"
    assert dec["reason"].startswith(
        ("ack_unreadable", "no_failed_delivery_in_journal",
         "alarmed_round_has_no_delivery_record"))


def test_monitor_invocation_unknown_first_reports():
    raw = _jline(_t(1), INV_A, SNAP_A, False)
    ev = m309.namespace()["monitor_ack_evidence"](now=NOW, journal_loader=lambda now: raw,
                                                  unit_state={})
    assert ev["reason"] == "alarmed_invocation_unknown"
    assert _decision(ev)["action"] == "report"


def test_monitor_unknown_within_budget_pending_and_past_budget_reports():
    unk = {"state": "unknown", "snapshot_id": SNAP_B, "error_kind": "TimeoutError"}
    within = "\n".join([_jline(_t(10), INV_A, SNAP_A, False),
                        _jline(_t(2), INV_B, SNAP_B, False),
                        _jline(_t(1), INV_C, SNAP_C, False, unk)])
    assert _decision(_evidence(within, INV_B))["action"] == "pending"

    # 失败链起点 35min 前 ⇒ 超 30min 预算, 持续未知不许吞。
    past = "\n".join([_jline(_t(35), INV_A, SNAP_A, False),
                      _jline(_t(2), INV_B, SNAP_B, False),
                      _jline(_t(1), INV_C, SNAP_C, False, unk)])
    dec = _decision(_evidence(past, INV_B))
    assert dec["action"] == "report" and dec["reason"] == "unknown_sustained_past_budget"


def test_monitor_late_ok_but_freshness_expired_reports():
    raw = "\n".join([_jline(_t(45), INV_A, SNAP_A, False),
                     _jline(_t(30), INV_B, SNAP_B, False, _late_ok(SNAP_A, 40))])
    dec = _decision(_evidence(raw, INV_A))
    assert dec["action"] == "report" and dec["reason"] == "late_ok_but_freshness_expired"


def test_monitor_future_round_clock_is_invalid():
    raw = _jline(_t(-3), INV_A, SNAP_A, False)  # 完成时刻在未来 3 分钟 > 120s 容差
    dec = _decision(_evidence(raw, INV_A))
    assert dec["action"] == "report" and dec["reason"] == "failed_round_clock_invalid"


# ─────────────────────── ③ 状态补位默认关 ───────────────────────
def test_normal_round_has_zero_backfill_mail_and_zero_state_by_default(monkeypatch, capfd):
    monkeypatch.delenv("MONITOR_CONCLUSION_STATUS_EMAIL", raising=False)
    ns = m309.namespace()
    calls, saves = [], []

    def stub(cmd):
        calls.append(cmd)
        return "[notify] 汇总：已发出 email"

    result = ns["_maybe_send_conclusion_status_email"](
        "有 1 条告警(见上方), 不判 OK; 覆盖 43/43(40 业务+基础, 3 自监控)",
        0, {}, NOW, stub, lambda s: saves.append(s))
    assert result["reason"] == "disabled" and result["sent"] is False
    assert calls == [] and saves == []
    assert ns["_conclusion_email_enabled"]() is False
