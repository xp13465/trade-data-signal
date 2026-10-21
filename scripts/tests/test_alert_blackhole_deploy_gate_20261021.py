# -*- coding: utf-8 -*-
"""告警黑洞 + 部署闸门分级 + history_overwrite 误报 自测(2026-10-21, P0)。

覆盖任务书三件(A/B/C):
  A 告警黑洞根因修:
    A1 notify.py `--result-file` 结构化发送结果(status=sent/suppressed/failed/noop/dry_run)。
    A2 **72h 升级抽屉内新增对象仍首报**(病灶: 升级档 suppress 直接 return 0, 位于普通首报路径之前)。
    A3 check_failed_units 判「真发出」改用结果文件; 旧版 notify 无结果文件时回退字符串判据(兼容)。
    A4 check_failed_units 未送达出口码 = 4(不再误报 rc=1「巡检已处理」); schedule_monitor rc=4 独立复核。
  B 部署闸门分级:
    B1 校验项定级: 阻断级 fail → rc=1; 仅告警级 fail + --deploy-mode → rc=3(不阻断)。
    B2 summary JSON 分级明细(供 deploy 告警正文)。
    B3 nextday_plan / day_snapshot 读「本地待上传副本优先, 缺失回退 R2」, 本地损坏仍 FAIL(不放松)。
    B4 deploy_fail_tracker: 连续失败计数/阈值(默认 2, 可配)/成功清零/原子写。
    B5 deploy.sh 接线静态守卫(trap / rc=3 分支 / 盘中拒跑不计数)。
  C history_overwrite 误报口径:
    C1 消失行能在同 (date,index_id) 找到「出现」行 = 型别变更(每日全量重算设计行为)→ notice。
    C2 无配对 = 纯丢失 → 仍 critical(判别力不降); 混合场景写明纯丢失条数。

零外发铁律(§18 L48): 全部用例打桩通知出口 + ZeroOutboundTrap 包裹; 不跑任何生产业务脚本
(deploy.sh / schedule_monitor.sh 只做 `bash -n` 语法校验与源码形状断言, 绝不执行主流程)。
运行日: 所有日期均按测试运行时动态推导, 无写死「今天」字面量(教训 L51)。
"""
from __future__ import annotations

import datetime
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _zero_outbound import ZeroOutboundTrap  # noqa: E402
from app import history_audit  # noqa: E402
from app.db import SCHEMA  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402
import check_data_integrity as cdi  # noqa: E402
import check_failed_units as cfu  # noqa: E402
import deploy_fail_tracker as dft  # noqa: E402
import notify  # noqa: E402

SCRIPTS = ROOT / "scripts"
DEPLOY_SH = SCRIPTS / "deploy.sh"
MONITOR_SH = SCRIPTS / "schedule_monitor.sh"


# ══════════════════════ A1/A2/A3: notify 结构化结果 + 72h 窗首报 ══════════════════════

@pytest.fixture
def notify_env(tmp_path, monkeypatch):
    """隔离 notify 的全部落盘出口: dedup 文件 / REPO 状态 / 发送函数(零外发)。"""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    dedup = data / "notify_dedup.json"
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setattr(notify, "DEDUP_FILE", dedup)
    calls = {"send": [], "tier": []}

    def _send(subject, body, **kw):
        calls["send"].append({"subject": subject, "body": body, **kw})
        return {"email": True}

    def _tier(subject, body, **kw):
        calls["tier"].append({"subject": subject, "body": body, **kw})
        return {"email": True}

    monkeypatch.setattr(notify, "send", _send)
    monkeypatch.setattr(notify, "send_tiered", _tier)
    return {"tmp": tmp_path, "data": data, "dedup": dedup, "calls": calls}


def _seed_escalation_state(repo: Path, days: int = 3) -> Path:
    """写 failed_units_patrol 状态: 最近 N 天(含今天)都异常 ⇒ 升级档 critical。"""
    today = datetime.date.today()
    seen = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days - 1, -1, -1)]
    p = repo / "data" / "failed_units_patrol_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"seen_dates": seen, "last_fail_date": seen[-1],
                             "consecutive_days": days, "first_fail_date": seen[0]}),
                 encoding="utf-8")
    return p


def _seed_dedup(dedup_path: Path, key: str, seconds_ago: int = 60) -> None:
    ts = (datetime.datetime.now() - datetime.timedelta(seconds=seconds_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")
    dedup_path.write_text(json.dumps({key: {"last_alerted": ts}}), encoding="utf-8")


def test_a1_result_file_statuses(notify_env, tmp_path, monkeypatch):
    """A1: 结果文件按真实路由写 status(dry_run / suppressed / sent / failed)。"""
    rf = tmp_path / "r.json"
    with ZeroOutboundTrap() as trap:
        # dry-run
        rc = notify.main(["s", "b", "--dry-run", "--result-file", str(rf)])
        assert rc == 0
        payload = json.loads(rf.read_text(encoding="utf-8"))
        assert payload["status"] == "dry_run", payload

        # 去重窗内 suppress(不是故障, 必须与 failed 区分开)
        _seed_dedup(notify_env["dedup"], "test_blackhole_suppress", seconds_ago=60)
        rc = notify.main(["s", "b", "--dedup-key", "test_blackhole_suppress",
                          "--dedup-window", "3600", "--result-file", str(rf)])
        assert rc == 0
        payload = json.loads(rf.read_text(encoding="utf-8"))
        assert payload["status"] == "suppressed", payload

        # 真发送(stub 返回 email=True)
        rc = notify.main(["s", "b", "--result-file", str(rf)])
        assert rc == 0
        payload = json.loads(rf.read_text(encoding="utf-8"))
        assert payload["status"] == "sent", payload
        assert payload["channels"] == {"email": True}

        # 全渠道失败
        monkeypatch.setattr(notify, "send", lambda *a, **kw: {"email": False, "feishu": False})
        rc = notify.main(["s", "b", "--result-file", str(rf)])
        assert rc == 0
        payload = json.loads(rf.read_text(encoding="utf-8"))
        assert payload["status"] == "failed", payload
    assert trap.hits == [], f"零外发被破坏: {trap.hits}"


def test_a2_upgrade_window_does_not_swallow_new_object_first_report(notify_env, tmp_path):
    """A2 回归: 72h 升级档已发过 + 本轮出现**新对象**(集合有变) ⇒ 仍必须首报。

    病灶复现: 旧代码在升级档 check_dedup 命中时直接 `return 0`, 位于普通首报路径之前,
    72h 内所有新 failed unit 的首报被吞(云上 10-19 11:00 后彻底黑洞)。
    """
    _seed_escalation_state(notify_env["tmp"])
    _seed_dedup(notify_env["dedup"], adr.FAILED_UNITS_ESCALATED_DEDUP_KEY, seconds_ago=3600)
    rf = tmp_path / "r.json"

    with ZeroOutboundTrap() as trap:
        rc = notify.main(["[告警] 云上 failed unit 新增", "trade-new.service failed",
                          "--severe", "--from-prefix", "[告警]",
                          "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                          "--dedup-window", "0", "--result-file", str(rf)])
    assert rc == 0
    payload = json.loads(rf.read_text(encoding="utf-8"))
    # 关键断言: 升级档被抑制, 但普通首报通道**照发**(不是 suppressed)。
    assert payload["status"] == "sent", payload
    assert len(notify_env["calls"]["tier"]) == 0, "同对象升级重复发 ⇒ 72h 窗失效"
    assert len(notify_env["calls"]["send"]) == 1, notify_env["calls"]
    assert trap.hits == [], f"零外发被破坏: {trap.hits}"


def test_a2b_upgrade_still_sends_when_window_empty(notify_env, tmp_path):
    """A2 正控: 72h 窗空时升级档照发 critical(不因修黑洞把升级维度修没)。"""
    _seed_escalation_state(notify_env["tmp"])
    rf = tmp_path / "r.json"
    with ZeroOutboundTrap() as trap:
        notify.main(["s", "b", "--severe", "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                     "--dedup-window", "0", "--result-file", str(rf)])
    assert len(notify_env["calls"]["tier"]) == 1
    assert "升级 critical" in notify_env["calls"]["tier"][0]["subject"]
    assert trap.hits == []


# ══════════════════════ A3/A4: check_failed_units 发送判据 + rc ══════════════════════

class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", rc: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, rc


def _fake_run_writing_result(status, out="", write_file=True):
    def _run(cmd, **kw):
        if write_file:
            rf = cmd[cmd.index("--result-file") + 1]
            Path(rf).write_text(json.dumps({"status": status, "channels": {"email": True}}),
                                encoding="utf-8")
        return _FakeProc(stdout=out)
    return _run


@pytest.mark.parametrize("status,expect", [("sent", True), ("suppressed", False),
                                           ("failed", False), ("noop", False)])
def test_a3_send_notify_uses_structured_status(monkeypatch, tmp_path, status, expect):
    """A3: 「真发出」只看结果文件 status; suppressed/failed/noop 一律不算已发(不落状态)。"""
    monkeypatch.setattr(cfu.subprocess, "run", _fake_run_writing_result(status))
    with ZeroOutboundTrap() as trap:
        sent, detail = cfu._send_notify(tmp_path, "s", "b")
    assert sent is expect, detail
    assert f"status={status}" in detail
    assert trap.hits == []


def test_a3b_old_notify_fallback_string_judge(monkeypatch, tmp_path):
    """A3 兼容: 旧版 notify 不写结果文件 → 回退字符串判据(不因升级判失败)。"""
    monkeypatch.setattr(cfu.subprocess, "run",
                        _fake_run_writing_result(None, out="[notify] 汇总：已发出 email",
                                                 write_file=False))
    sent, detail = cfu._send_notify(tmp_path, "s", "b")
    assert sent is True and "回退字符串判据" in detail

    monkeypatch.setattr(cfu.subprocess, "run",
                        _fake_run_writing_result(None, out="[notify] 汇总：全部渠道未发出（email）",
                                                 write_file=False))
    sent, detail = cfu._send_notify(tmp_path, "s", "b")
    assert sent is False


def test_a4_undelivered_exit_code_and_monitor_branch():
    """A4: 未送达出口码=4 + schedule_monitor 有 rc=4 独立复核分支、rc=1 不再自证已发。"""
    src = (SCRIPTS / "check_failed_units.py").read_text(encoding="utf-8")
    assert "return 4" in src and "告警未发出(不落抑制, 下轮重试)" in src

    mon = MONITOR_SH.read_text(encoding="utf-8")
    assert "elif _r_cfu.returncode == 4:" in mon
    assert "check_failed_units|delivery|down" in mon
    # 只查**实际打印文案**(注释里引用旧文案做说明不算), rc=1 不得再自证「已发告警」。
    prints = [ln for ln in mon.splitlines() if 'print(f"[196]' in ln]
    assert prints, "未找到 [196] 打印行(源码形状变了, 守卫需同步)"
    assert not any("已发告警" in ln for ln in prints), \
        "rc=1 仍在自证「已发」⇒ 黑洞另一半未修"


# ══════════════════════ B1/B2/B3: 校验项分级 + 本地优先 ══════════════════════

def _res(name, status):
    return cdi.CheckResult(name, status, "msg")


def test_b1_grading_exit_codes():
    """B1: 阻断级 fail 阻断; 告警级 fail 仅 deploy 模式降为 rc=3(不阻断)。"""
    assert cdi.grade_of("nextday_plan") == cdi.ALERT_ONLY_GRADE
    assert cdi.grade_of("overview") == cdi.BLOCKING_GRADE       # 未登记项默认阻断(fail-safe)

    blocking = [_res("overview", cdi.CheckResult.FAIL)]
    alert_only = [_res("nextday_plan", cdi.CheckResult.FAIL)]
    both = blocking + alert_only

    assert cdi.determine_exit_code(blocking, False, deploy_mode=True) == 1
    assert cdi.determine_exit_code(alert_only, False, deploy_mode=True) == 3
    assert cdi.determine_exit_code(alert_only, False, deploy_mode=False) == 1  # 手动排查不降级
    assert cdi.determine_exit_code(both, False, deploy_mode=True) == 1        # 有阻断级 ⇒ 仍阻断
    assert cdi.determine_exit_code([_res("overview", cdi.CheckResult.WARN)], True) == 2
    assert cdi.determine_exit_code([_res("overview", cdi.CheckResult.OK)], False) == 0


def test_b2_summary_written_with_grade_split(tmp_path):
    """B2: summary JSON 分级明细(deploy 告警正文数据源)。"""
    out = tmp_path / "summary.json"
    results = [_res("overview", cdi.CheckResult.OK),
               _res("nextday_plan", cdi.CheckResult.FAIL),
               _res("alert", cdi.CheckResult.FAIL),
               _res("fund_nav", cdi.CheckResult.WARN)]
    cdi._write_summary(str(out), results, 3, deploy_mode=True)
    p = json.loads(out.read_text(encoding="utf-8"))
    assert p["rc"] == 3 and p["deploy_mode"] is True
    assert p["ok"] == 1 and p["warn"] == 1 and p["fail_total"] == 2
    assert [x["name"] for x in p["alert_only_fails"]] == ["nextday_plan", "alert"]
    assert p["blocking_fails"] == []
    assert not (tmp_path / "summary.json.tmp").exists()


def test_b3_local_first_prefers_local_then_r2(tmp_path, monkeypatch):
    """B3: 本地待上传副本优先; 缺失才回退 R2; 本地损坏仍 FAIL(不降级)。"""
    local = tmp_path / "nextday_plan.json"
    local.write_text(json.dumps({"date": "20261021"}), encoding="utf-8")
    called = []

    def _fetch(rel):
        called.append(rel)
        return {"date": "20261019"}, None

    monkeypatch.setattr(cdi, "_fetch_r2_json", _fetch)
    data, err, src = cdi._load_local_first(tmp_path, "nextday_plan.json")
    assert (data, err, src) == ({"date": "20261021"}, None, "local")
    assert called == [], "本地副本在位时不得读 R2(自锁根因)"

    local.unlink()
    data, err, src = cdi._load_local_first(tmp_path, "nextday_plan.json")
    assert data == {"date": "20261019"} and err is None and src == "r2"
    assert called == ["nextday_plan.json"]

    local.write_text("{broken", encoding="utf-8")
    called.clear()
    data, err, src = cdi._load_local_first(tmp_path, "nextday_plan.json")
    assert data is None and src == "local" and "本地副本损坏" in err
    assert called == [], "本地坏副本必须直接 FAIL, 不得悄悄用 R2 旧版放行"


# ══════════════════════ B4: deploy 连续失败 tracker ══════════════════════

def _tr(tmp, *args):
    return dft.main(list(args) + ["--repo", str(tmp)])


def test_b4_consecutive_fail_threshold_and_reset(tmp_path):
    """B4: 连续失败达阈值只报一次; 成功清零后新一段再报; 状态字段完整/原子写。"""
    base = ["--now", "2026-10-21 10:00:00", "--rc", "1", "--stage", "export",
            "--log", "/tmp/deploy.log"]
    assert _tr(tmp_path, "failure", *base) == 0
    assert _tr(tmp_path, "failure", *base) == 10          # 默认阈值 2 ⇒ 第二次命中
    assert _tr(tmp_path, "failure", *base) == 0           # 同一段不重复告警

    st = json.loads((tmp_path / "data" / "deploy_fail_state.json").read_text(encoding="utf-8"))
    assert st["consecutive_fail"] == 3
    assert st["last_rc"] == 1 and st["last_stage"] == "export"
    assert st["alerted_for_count"] == 2 and st["last_fail_at"] == "2026-10-21 10:00:00"
    assert not (tmp_path / "data" / "deploy_fail_state.json.tmp").exists()

    assert _tr(tmp_path, "success", "--now", "2026-10-21 11:00:00") == 0
    st = json.loads((tmp_path / "data" / "deploy_fail_state.json").read_text(encoding="utf-8"))
    assert st["consecutive_fail"] == 0 and st["last_success_at"] == "2026-10-21 11:00:00"
    assert "alerted_for_count" not in st

    assert _tr(tmp_path, "failure", *base) == 0
    assert _tr(tmp_path, "failure", *base) == 10          # 新一段重新计数并再报


def test_b4b_threshold_configurable(tmp_path, monkeypatch):
    """B4: 阈值可配(--threshold / env), N=3 时第三次才报。"""
    assert _tr(tmp_path, "failure", "--threshold", "3") == 0
    assert _tr(tmp_path, "failure", "--threshold", "3") == 0
    assert _tr(tmp_path, "failure", "--threshold", "3") == 10

    monkeypatch.setenv("DEPLOY_FAIL_ALERT_THRESHOLD", "1")
    tmp2 = tmp_path / "second"
    tmp2.mkdir()
    assert _tr(tmp2, "failure") == 10


def test_b5_deploy_wiring_static_guard():
    """B5: deploy.sh 接线静态守卫 + bash 语法(不执行主流程)。"""
    src = DEPLOY_SH.read_text(encoding="utf-8")
    assert "trap _deploy_record_result EXIT" in src
    assert "deploy_fail_tracker.py\" success --repo" in src
    assert "deploy_fail_tracker.py\" failure --repo" in src
    assert "--dedup-key deploy_consecutive_fail" in src
    # 盘中有意拒跑不计数(否则每天手动跑一次就误报)
    assert "DEPLOY_RECORD_OFF=1" in src
    # 告警级 fail 不退出: rc=3 分支存在且阻断条件排除 3
    assert '"$CHECK_RC" -eq 3' in src
    assert '"$CHECK_RC" -ne 0 ] && [ "$CHECK_RC" -ne 3' in src
    assert "deploy_check_data_integrity_alertonly" in src

    bash = shutil.which("bash")
    if bash:  # CI/本机都有 bash; 无 bash 环境跳过语法校验(不写死「本机有」判断)
        r = subprocess.run([bash, "-n", str(DEPLOY_SH)], capture_output=True, text=True,
                           timeout=60, check=False)
        assert r.returncode == 0, r.stderr


# ══════════════════════ C: history_overwrite 误报口径 ══════════════════════

def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


@pytest.fixture
def audit_calls(monkeypatch):
    calls = []

    def _fake(subject, body, **kw):
        calls.append({"subject": subject, "body": body, **kw})
        return 0

    monkeypatch.setattr(history_audit, "send_alert", _fake)
    return calls


def test_c1_paired_type_change_is_notice(audit_calls):
    """C1: 消失行有同 (date,index_id) 的「出现」配对 = 每日全量重算设计行为 ⇒ notice。"""
    conn = _mem_conn()
    before = {("20261012", "idx_a", "buy"), ("20261012", "idx_b", "buy")}
    after = {("20261012", "idx_a", "buy_aux"), ("20261012", "idx_b", "buy_aux")}
    history_audit.audit_signal_daily_store(conn, before, after, run_date="20261014")
    assert len(audit_calls) == 1
    c = audit_calls[0]
    assert c["severe"] is False
    assert c["subject"].startswith("[历史行改写-提示]")
    assert "设计行为" in c["body"] and "判据局限" in c["body"]
    assert c["dedup_key"].endswith(":notice") and c["dedup_window"] == 86400


def test_c2_pure_loss_still_critical(audit_calls):
    """C2: 无配对的消失 = 纯丢失 ⇒ 仍 critical(真故障判别力不降)。"""
    conn = _mem_conn()
    before = {("20261012", "idx_a", "buy")}
    history_audit.audit_signal_daily_store(conn, before, set(), run_date="20261014")
    assert len(audit_calls) == 1
    c = audit_calls[0]
    assert c["severe"] is True
    assert c["subject"].startswith("[历史行改写]")
    assert "纯丢失 1 条" in c["body"]
    assert c["dedup_key"].endswith(":critical")


def test_c2b_mixed_paired_plus_loss_is_critical(audit_calls):
    """C2 混合: 有配对型别变更 + 有纯丢失 ⇒ critical, 正文分别标注两类条数。"""
    conn = _mem_conn()
    before = {("20261012", "idx_a", "buy"), ("20261012", "idx_lost", "buy")}
    after = {("20261012", "idx_a", "buy_aux")}
    history_audit.audit_signal_daily_store(conn, before, after, run_date="20261014")
    c = audit_calls[0]
    assert c["severe"] is True
    assert "型别变更 1 条" in c["body"] and "纯丢失 1 条" in c["body"]


def test_c3_index_daily_keeps_critical(audit_calls):
    """举一反三: index_daily 值改写(源值修正)未改动口径 ⇒ 仍 critical(不借机降噪)。"""
    conn = _mem_conn()
    conn.execute("INSERT INTO index_daily (date, index_id, close) VALUES (?,?,?)",
                 ("20261012", "idx_a", 100.0))
    conn.commit()
    history_audit.audit_index_rows_upsert(
        [("20261012", "idx_a", 1.0, 1.0, 1.0, 90.0, 0.0, 1e8)],
        conn=conn, run_date="20261014")
    assert len(audit_calls) == 1
    assert audit_calls[0]["severe"] is True