# -*- coding: utf-8 -*-
"""告警黑洞 + 部署闸门分级 + history_overwrite 误报 自测(2026-10-21, P0)。

覆盖任务书三件(A/B/C) + 2026-10-22 审查 BLOCK 返修:
  A 告警黑洞根因修:
    A1 notify.py `--result-file` 结构化发送结果
       (status=sent/suppressed/failed/digested/noop/dry_run)。
    A2 **72h 升级抽屉内新增对象仍首报**(病灶: 升级档 suppress 直接 return 0, 位于普通首报路径之前)。
    A3 check_failed_units 判「真发出」改用结果文件 status ∈ {sent, digested};
       结果文件缺失 = 未送达(旧版字符串回退已删, 审查差集 D7)。
    A4 check_failed_units 未送达出口码 = 4(不再误报 rc=1「巡检已处理」); schedule_monitor rc=4 独立复核。
    A5 **BLOCK-2**: 域聚合 digested ≠ 未送达 —— 不 rc=4 / 不产生假 SEVERE / 落签名防重复;
       真发送失败仍 rc=4(不吞真故障)。
  B 部署闸门分级:
    B1 校验项定级: 阻断级 fail → rc=1; 仅告警级 fail + --deploy-mode → rc=3(不阻断)。
    B2 summary JSON 分级明细(供 deploy 告警正文)。
    B3 nextday_plan / day_snapshot 读「本地待上传副本优先, 缺失回退 R2」, 本地损坏仍 FAIL(不放松)。
    B4 deploy_fail_tracker: 连续失败计数/阈值(默认 2, 可配)/成功清零/原子写。
    B5 deploy.sh 接线静态守卫(trap / rc=3 分支 / 盘中拒跑不计数)。
    B6 **BLOCK-1**: fund_nav / changelog_current_version 回阻断级; fund_nav 唯一失败 ⇒ rc=1,
       deploy.sh 自愈门(rc≠0)被进入; D3 deploy_consecutive_fail 免域聚合(停摆告警直发)。
  C history_overwrite 误报口径:
    C1 消失行能在同 (date,index_id) 找到「出现」行 = 型别变更(每日全量重算设计行为)→ notice。
    C2 无配对 = 纯丢失 → 仍 critical(判别力不降); 混合场景写明纯丢失条数。
    C4 **D6**: 配对必须一对一多重集(Counter), 同键多行少补回时仍计入纯丢失。

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

def _isolate_notify_paths(tmp_path, monkeypatch):
    """隔离 notify 的全部落盘出口: dedup/域状态/摘要 buffer / REPO 状态(防污染真实 data/alerts/)。"""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    alerts = data / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    dedup = data / "notify_dedup.json"
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setattr(notify, "DEDUP_FILE", dedup)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERTS_FILE", alerts / "latest.md")
    monkeypatch.setattr(notify, "WARNING_BUFFER_FILE", alerts / "warning_buffer.jsonl")
    monkeypatch.setattr(notify, "INFO_LOG_FILE", alerts / "info_log.jsonl")
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", alerts / "warning_dedup_state.json")
    monkeypatch.setattr(notify, "WARNING_DEDUP_LOCK_FILE", alerts / "warning_dedup.lock")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", alerts / "warning_buffer.flushlock")
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", alerts / "alert_digest.jsonl")
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", alerts / "alert_digest.flushlock")
    monkeypatch.setattr(notify, "ALERT_DIGEST_STATE_FILE", alerts / "alert_digest_state.json")
    return {"tmp": tmp_path, "data": data, "alerts": alerts, "dedup": dedup}


@pytest.fixture
def notify_env(tmp_path, monkeypatch):
    """隔离落盘出口 + 打桩 send/send_tiered(测 main 路由, 不跑 send 内部 gate)。"""
    env = _isolate_notify_paths(tmp_path, monkeypatch)
    calls = {"send": [], "tier": []}

    def _send(subject, body, **kw):
        calls["send"].append({"subject": subject, "body": body, **kw})
        return {"email": True}

    def _tier(subject, body, **kw):
        calls["tier"].append({"subject": subject, "body": body, **kw})
        return {"email": True}

    monkeypatch.setattr(notify, "send", _send)
    monkeypatch.setattr(notify, "send_tiered", _tier)
    return {**env, "calls": calls}


@pytest.fixture
def notify_real_send_env(tmp_path, monkeypatch):
    """保留 send() 本体(域聚合 gate 在 send 内部), 只打桩**出口渠道**(零外发)。"""
    env = _isolate_notify_paths(tmp_path, monkeypatch)
    calls = {"email": [], "telegram": [], "feishu": []}

    def _email(subject, body, **kw):
        calls["email"].append({"subject": subject, "body": body})
        return True

    def _telegram(subject, body, **kw):
        calls["telegram"].append({"subject": subject, "body": body})
        return True

    def _feishu(subject, body, **kw):
        calls["feishu"].append({"subject": subject, "body": body})
        return True

    monkeypatch.setattr(notify, "_send_email", _email)
    monkeypatch.setattr(notify, "send_telegram", _telegram)
    monkeypatch.setattr(notify, "send_feishu", _feishu)
    return {**env, "calls": calls}


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


@pytest.mark.parametrize("status,expect", [("sent", True), ("digested", True),
                                           ("suppressed", False), ("failed", False),
                                           ("noop", False)])
def test_a3_send_notify_uses_structured_status(monkeypatch, tmp_path, status, expect):
    """A3: 「真发出/已处置」只看结果文件 status; suppressed/failed/noop 不算已发(不落状态)。

    BLOCK-2: digested = 已并入当日摘要(23:25 统一交付) ⇒ 已处置, 必须与「未送达」区分。
    """
    monkeypatch.setattr(cfu.subprocess, "run", _fake_run_writing_result(status))
    with ZeroOutboundTrap() as trap:
        sent, detail = cfu._send_notify(tmp_path, "s", "b")
    assert sent is expect, detail
    assert f"status={status}" in detail
    assert trap.hits == []


def test_a3b_missing_result_file_is_not_delivered(monkeypatch, tmp_path):
    """A3/D7: 结果文件缺失(旧版 notify / 写失败) ⇒ 按未送达处理, **不再**回退字符串判据。

    旧字符串回退不可达: 旧版 notify argparse 不认 --result-file 会直接报错, 不会产出
    「汇总：已发出」。留它 = 死代码(审查差集 D7)。保守方向 = 不落签、下轮重试。
    """
    monkeypatch.setattr(cfu.subprocess, "run",
                        _fake_run_writing_result(None, out="[notify] 汇总：已发出 email",
                                                 write_file=False))
    sent, detail = cfu._send_notify(tmp_path, "s", "b")
    assert sent is False and "status=missing" in detail
    # 也不得再调用已删除的字符串判据符号(防死代码回潮)
    assert not hasattr(cfu, "_notify_sent")


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
    # BLOCK-1: fund_nav / changelog_current_version 必须阻断级(用户 2026-10-13 拍板 + 原 docstring)
    assert "fund_nav" not in cdi.ALERT_ONLY_CHECKS
    assert cdi.grade_of("fund_nav") == cdi.BLOCKING_GRADE
    assert "changelog_current_version" not in cdi.ALERT_ONLY_CHECKS
    assert cdi.grade_of("changelog_current_version") == cdi.BLOCKING_GRADE

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


def test_b6_block1_fund_nav_blocking_and_selfheal_gate(tmp_path):
    """BLOCK-1: fund_nav 回阻断级 + 自愈门 rc≠0 ⇒ fund_nav 唯一失败时自愈分支真被进入。

    证据用例:
      ① fund_nav 唯一失败 ⇒ rc=1(阻断, 不是 3);
      ② fund_nav + 其他告警级失败 ⇒ 仍有阻断级 ⇒ rc=1;
      ③ deploy.sh 自愈门条件 = `-ne 0`(上一批写成 `-eq 1` ⇒ fund_nav 唯一失败时 rc=1
         **碰巧**能进、但 fund_nav 曾被降级成 rc=3 时永不进入 = 10-13 自愈机制在自己的
         设计场景失效); 且该门位于 rc=3 分支之前;
      ④ 门条件在 bash 里实测: CHECK_RC=1 / 3 进入, 0 不进入(只取条件式执行, 不跑生产脚本)。
    """
    fund_nav_only = [_res("fund_nav", cdi.CheckResult.FAIL)]
    assert cdi.determine_exit_code(fund_nav_only, False, deploy_mode=True) == 1
    mixed = fund_nav_only + [_res("nextday_plan", cdi.CheckResult.FAIL)]
    assert cdi.determine_exit_code(mixed, False, deploy_mode=True) == 1

    src = DEPLOY_SH.read_text(encoding="utf-8")
    gate = 'if [ "$CHECK_RC" -ne 0 ]; then'
    assert gate in src, "自愈门缺失或条件被改(应为 rc≠0)"
    assert 'if [ "$CHECK_RC" -eq 1 ]; then' not in src, \
        "自愈门又写回 ==1 ⇒ fund_nav 降级为 rc=3 的回归场景会再次自愈失效"
    assert src.index(gate) < src.index('if [ "$CHECK_RC" -eq 3 ]; then'), \
        "自愈门必须在 rc=3(告警级继续)分支之前: 先尝试自愈, 再决定是否降级继续"
    assert src.index(gate) < src.index('"$CHECK_RC" -ne 0 ] && [ "$CHECK_RC" -ne 3'), \
        "阻断退出必须在自愈之后(重跑仍 FAIL 才终止)"

    bash = shutil.which("bash")
    if bash:
        def _gate_entered(rc: str) -> bool:
            script = "CHECK_RC=" + rc + "\n" + gate + "\n  echo entered\nfi\n"
            r = subprocess.run([bash, "-c", script], capture_output=True, text=True,
                               timeout=30, check=False)
            assert r.returncode == 0, r.stderr
            return r.stdout.strip() == "entered"

        assert _gate_entered("1") is True     # fund_nav 唯一失败(阻断)
        assert _gate_entered("3") is True     # 其余告警级失败也过探针(非 DB 领先方向即快速返回)
        assert _gate_entered("0") is False    # 全绿不自愈


# ══════════════════════ BLOCK-2: 域聚合 digested = 已处置(≠ 未送达) ══════════════════════

def _seed_domain_state(alerts_dir: Path, domain: str, seconds_ago: int = 3600) -> Path:
    """写域状态: 同域上一条告警 N 秒前(默认 1h, 落在 2h 静默窗内)。

    窗口**不跨自然日**(设计口径): 跨零点时 1h 前会落到昨天 ⇒ 必须夹到今日 00:00:01,
    否则用例会在凌晨 00:00~01:00 随机失败(时敏测试教训 L51 同族)。
    """
    now = datetime.datetime.now()
    last = now - datetime.timedelta(seconds=seconds_ago)
    if last.strftime("%Y-%m-%d") != now.strftime("%Y-%m-%d"):
        last = now.replace(hour=0, minute=0, second=1, microsecond=0)
    ts = last.strftime("%Y-%m-%d %H:%M:%S")
    p = alerts_dir / adr.ALERT_DOMAIN_STATE_FILENAME
    p.write_text(json.dumps({domain: {"last_ts": ts, "last_day": now.strftime("%Y-%m-%d"),
                                      "day_first_ts": ts, "n_direct": 1, "n_absorbed": 0}}),
                 encoding="utf-8")
    return p


_FAILED_LINE = "trade-foo.service loaded failed failed synthetic unit(false sample)"


def _seed_patrol_inputs(tmp_path: Path):
    """注入 failed-unit 样本 + 全部巡检 timer 健康(避免 watchman 噪声混入)."""
    failed = tmp_path / "failed.txt"
    failed.write_text(_FAILED_LINE + "\n", encoding="utf-8")
    show = {u: {"ActiveState": "active", "LoadState": "loaded", "UnitFileState": "enabled"}
            for u, _k in adr.WATCHMAN_UNITS}
    show_path = tmp_path / "show.json"
    show_path.write_text(json.dumps(show), encoding="utf-8")
    return failed, show_path


def _run_patrol(tmp_path: Path, monkeypatch, notify_ret):
    """跑 check_failed_units 主流程(--notify), 发送函数打桩(零外发)。"""
    failed, show = _seed_patrol_inputs(tmp_path)
    calls = []

    def _stub(repo, subject, body):
        calls.append({"subject": subject, "body": body})
        return notify_ret

    monkeypatch.setattr(cfu, "_send_notify", _stub)
    monkeypatch.setattr(sys, "argv", ["check_failed_units.py", "--repo", str(tmp_path), "--notify",
                                      "--failed-units-file", str(failed),
                                      "--unit-show-json", str(show)])
    with ZeroOutboundTrap() as trap:
        rc = cfu.main()
    assert trap.hits == [], f"零外发被破坏: {trap.hits}"
    return rc, calls


def test_d1_domain_absorbed_notify_reports_digested(notify_real_send_env, tmp_path):
    """BLOCK-2 证据①前半: 同域 2h 内第二条巡检告警 ⇒ notify 结果文件 status=digested。"""
    env = notify_real_send_env
    _seed_domain_state(env["alerts"], "unit", seconds_ago=3600)
    rf = tmp_path / "r.json"
    with ZeroOutboundTrap() as trap:
        rc = notify.main(["[告警] 云上 unit 巡检发现异常(1 项) 10:00", "trade-foo.service failed",
                          "--severe", "--from-prefix", "[告警]",
                          "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                          "--dedup-window", "0", "--result-file", str(rf)])
    assert rc == 0
    payload = json.loads(rf.read_text(encoding="utf-8"))
    assert payload["status"] == "digested", payload
    assert env["calls"]["email"] == [], "域聚合并入 = 走摘要, 不得再直发(否则重复)"
    digest = env["alerts"] / "alert_digest.jsonl"
    assert digest.exists() and "trade-foo.service failed" in digest.read_text(encoding="utf-8")
    st = json.loads((env["alerts"] / adr.ALERT_DOMAIN_STATE_FILENAME).read_text(encoding="utf-8"))
    assert st["unit"]["n_absorbed"] == 1
    assert trap.hits == []


def test_d2_digested_writes_signature_no_false_severe(tmp_path, monkeypatch):
    """BLOCK-2 证据①②: digested ⇒ 落签名(不再每 15min 重试) + 连续 3 轮零 rc=4(无假 SEVERE)。

    病灶: digested 曾被当「未送达」⇒ rc=4 ⇒ schedule_monitor 打
    `SEVERE: 云上 failed-unit 巡检发现异常但告警未送达`; 且不落签名 ⇒ 每轮都重试 ⇒
    同域状态被不断刷新 ⇒ 2h 窗永不过期(假 SEVERE 持续一整天)。
    """
    sig_path = tmp_path / "data" / adr.FAILED_UNITS_SIG_STATE_FILENAME
    rcs = []
    for _round in range(3):
        rc, calls = _run_patrol(tmp_path, monkeypatch, (True, "status=digested"))
        rcs.append(rc)
    assert rcs == [1, 1, 1], f"digested 不得 rc=4(假 SEVERE); 实际 {rcs}"
    # 首轮已落签名(不再每 15min 重试); 后两轮同集合当日 ⇒ 降噪静默(也不重试)
    st = json.loads(sig_path.read_text(encoding="utf-8"))
    assert st["signature"], "digested 未落签名 ⇒ 下轮仍会重试, 域滑窗永不过期"
    assert st["last_alert_date"] == datetime.date.today().strftime("%Y-%m-%d")
    # 末轮 = 同集合当日重复 ⇒ 降噪静默, 不得再调发送(真故障判别维度: 新集合才立即报)
    assert len(calls) == 0, "同集合当日重复轮不得再调发送(降噪维度保留)"


def test_d3_true_delivery_failure_still_rc4(tmp_path, monkeypatch):
    """BLOCK-2 证据③: 真发送失败 ⇒ 仍 rc=4 + 不落签名(不吞真故障, 下轮重试)。"""
    sig_path = tmp_path / "data" / adr.FAILED_UNITS_SIG_STATE_FILENAME
    rc, calls = _run_patrol(tmp_path, monkeypatch, (False, "status=failed"))
    assert rc == 4, "真未送达必须 rc=4(schedule_monitor 才会打真 SEVERE 复核)"
    assert len(calls) == 1
    assert not sig_path.exists(), "发送失败不得落签名(否则当天失报)"


def test_d4_deploy_consecutive_fail_exempt_from_domain(notify_real_send_env, tmp_path):
    """D3: deploy 连续失败(停摆级)即使落 r2_deploy 域、2h 窗内也直发, 不得推迟到 23:25。"""
    env = notify_real_send_env
    _seed_domain_state(env["alerts"], "r2_deploy", seconds_ago=600)
    rf = tmp_path / "r.json"
    with ZeroOutboundTrap() as trap:
        rc = notify.main(["[告警] deploy 连续失败 2 次", "rc=1 stage=export",
                          "--severe", "--from-prefix", "[告警]",
                          "--dedup-key", "deploy_consecutive_fail",
                          "--dedup-window", "0", "--result-file", str(rf)])
    assert rc == 0
    payload = json.loads(rf.read_text(encoding="utf-8"))
    assert payload["status"] == "sent", payload
    assert len(env["calls"]["email"]) == 1
    # 正控: 同域普通告警仍被聚合(豁免只给点名键, 不是整域放开)
    with ZeroOutboundTrap():
        notify.main(["[告警] R2 上传失败", "r2=1",
                     "--severe", "--from-prefix", "[告警]",
                     "--dedup-key", "r2_upload_fail",
                     "--dedup-window", "0", "--result-file", str(rf)])
    assert json.loads(rf.read_text(encoding="utf-8"))["status"] == "digested"
    assert trap.hits == []


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


def test_c4_multiset_pairing_pure_loss_not_masked(audit_calls):
    """D6: 同 (date,index_id) 多行时配对必须一对一 —— 2 消失只补回 1 行 ⇒ 仍有 1 条纯丢失。

    实测依据: 本地库 3155 个键同 (date,index_id) 有多行(如 cgb_10y_etf 同日
    band_hold + buy_special)。用集合判「同键出现过」会把被掩盖的那一行也算成配对,
    纯丢失漏报 ⇒ critical 漏发(真故障判别力下降)。
    """
    conn = _mem_conn()
    before = {("20261012", "idx_multi", "buy"), ("20261012", "idx_multi", "buy_special")}
    after = {("20261012", "idx_multi", "band_hold")}
    changes = history_audit.audit_signal_daily_store(conn, before, after, run_date="20261014")
    assert sum(1 for c in changes if c["kind"] == "disappeared") == 2
    assert sum(1 for c in changes if c["kind"] == "appeared") == 1
    assert len(audit_calls) == 1
    c = audit_calls[0]
    assert c["severe"] is True, "有未配对消失行 ⇒ 必须 critical(不得被同键配对掩盖)"
    assert "纯丢失 1 条" in c["body"] and "型别变更 1 条" in c["body"]