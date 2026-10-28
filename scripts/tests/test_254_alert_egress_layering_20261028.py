# -*- coding: utf-8 -*-
"""#321 告警出口分层(2026-10-28)自验: 尺子三态退出码 / 摘要与恢复移 report 群 / 升级并入摘要 /
例行提示吸收 / repeat 去重窗 24h。

依据: docs/ops/alert-egress-layering-20261028.md(证据报告 /tmp/alert-egress-plan-20261028.md)
验收口径(任务书 STEP C/D/E):
  C  尺子 alert_noise_count.py 三态退出码(0 PASS / 1 FAIL / 2 测不了)、ROOT 不穿透 symlink、
     diverted(report 群 digest/recovery/escalation)只展示不参与 PASS。
  A  摘要 flush 落 report 群 + 邮件保留([告警·摘要] 白名单); 台账 group == 实际飞书 chat_key。
  A2 恢复类摘要链路不可用 fail-open 落 report 群且邮件保留(原推断落 alert 群)。
  B  持续故障升级 digest_only 并入摘要(category=escalation, 同日 bump_hits); critical 物理不可达。
  D  例行提示(kelly 孤儿买)吸收为 category=routine; R2 锁跳过改 report 群; 两处 repeat 去重窗 86400。

零真实外发(§18 L48): 三渠道替身 + ZeroOutboundTrap 兜底, 收尾断言 trap.hits == []。
时间敏感(L51): 显式固定 `--date`, 不依赖真实今天; 摘要窗口改 00:00 免冻墙钟。
跑法: python -m pytest -q scripts/tests/test_254_alert_egress_layering_20261028.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(Path(__file__).absolute().parent))
sys.path.insert(0, str(SCRIPTS))

import notify  # noqa: E402
import alert_noise_count as anc  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402


# ─────────────────────────── 夹具: 全路径隔离 + 渠道替身 ───────────────────────────
class _Recorder:
    def __init__(self):
        self.mails: list[tuple[str, str]] = []
        self.feishu_calls: list[dict] = []

    def email(self, subject, body, **kw):
        self.mails.append((str(subject), str(body)))
        return True

    def feishu(self, subject, body, **kw):
        self.feishu_calls.append({"subject": str(subject), "body": str(body), **kw})
        return True


@pytest.fixture()
def env(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    for name, path in {
        "ALERTS_DIR": alerts,
        "ALERTS_FILE": alerts / "latest.md",
        "WARNING_BUFFER_FILE": alerts / "warning_buffer.jsonl",
        "WARNING_FLUSH_LOCK_FILE": alerts / "warning_buffer.flushlock",
        "WARNING_DEDUP_STATE_FILE": alerts / "warning_dedup_state.json",
        "WARNING_DEDUP_LOCK_FILE": alerts / "warning_dedup.lock",
        "ALERT_DIGEST_FILE": alerts / "alert_digest.jsonl",
        "ALERT_DIGEST_LOCK_FILE": alerts / "alert_digest.flushlock",
        "ALERT_DIGEST_STATE_FILE": alerts / "alert_digest_state.json",
        "DEDUP_FILE": alerts / "notify_dedup.json",
    }.items():
        monkeypatch.setattr(notify, name, path)
    # 摘要窗口 00:00 ⇒ 任何时刻都能 flush, 不冻墙钟(3-B 用例同款)
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")
    monkeypatch.setenv("REPO", str(tmp_path))
    for k in ("ALERT_DIGEST_DISABLE", "ALERT_BUDGET_DISABLE", "ALERT_NOTICE_BUDGET_DISABLE",
              "ALERT_DOMAIN_DISABLE", "ALERT_LEDGER_DISABLE", "EMAIL_GROUP_GATE_DISABLE",
              "ALERT_REPEAT_ABSORB_DAYS", "NOTIFY_SOURCE"):
        monkeypatch.delenv(k, raising=False)
    rec = _Recorder()
    monkeypatch.setattr(notify, "_send_email", rec.email)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(notify, "send_feishu", rec.feishu)
    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "rec": rec, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


def _rec(ts: str, subject: str, *, group: str = "alert", tier: str = "notice",
         noise_class: str | None = None) -> dict:
    r = {"ts": ts, "group": group, "subject": subject, "tier": tier}
    if noise_class:
        r["noise_class"] = noise_class
    return r


def _write_ledger(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def _digest_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ═════════════════════ C. 尺子三态退出码 / ROOT / diverted ═════════════════════
def test_c1_rc_pass_is_0(tmp_path, capsys):
    p = _write_ledger(tmp_path / "l.jsonl", [
        _rec("2026-10-27 01:00:00", "[告警] 真故障 A", tier="critical"),
        _rec("2026-10-27 00:00:30", "[告警·摘要] 当日合并 1 条", tier="digest"),
    ])
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["rc"] == 0, payload
    assert payload["totals"]["pass"] is True


def test_c2_rc_fail_is_1(tmp_path, capsys):
    rows = [_rec(f"2026-10-27 0{i}:00:00", f"[告警·聚合] warning 批 {i}") for i in range(4)]
    p = _write_ledger(tmp_path / "l.jsonl", rows)
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1 and payload["rc"] == 1, payload
    assert payload["totals"]["noise"] == 4 and payload["totals"]["pass"] is False


def test_c3_rc_no_data_is_2(tmp_path, capsys):
    """台账存在但窗口内无 alert 行 ⇒ pass=null ⇒ 测不了(2), 不许冒充 PASS。"""
    p = _write_ledger(tmp_path / "l.jsonl", [
        _rec("2026-10-20 01:00:00", "[告警] 窗口外的行", tier="critical"),
    ])
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2 and payload["rc"] == 2, payload
    assert payload["totals"]["pass"] is None and payload["no_data"] is True


def test_c4_root_does_not_resolve_symlink(tmp_path, monkeypatch):
    """ROOT 用 absolute() 保留调用侧路径形状; 穿透 symlink 会去另一棵树找台账(pass=null 病灶)。"""
    real = tmp_path / "realrepo"
    (real / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPTS / "alert_noise_count.py", real / "scripts" / "alert_noise_count.py")
    link = tmp_path / "linkrepo"
    link.mkdir()
    (link / "scripts").symlink_to(real / "scripts")
    mod_path = link / "scripts" / "alert_noise_count.py"
    assert mod_path.absolute() != mod_path.resolve()  # 前置: 确有 symlink 可穿透

    spec = importlib.util.spec_from_file_location("anc_symlink_probe", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.ROOT == link, f"ROOT 穿透了 symlink: {mod.ROOT}"
    assert mod.ROOT != real
    monkeypatch.delenv("REPO", raising=False)  # 默认台账路径必须跟随 ROOT(不看外部 REPO)
    assert str(mod.default_ledger_path()).startswith(str(link))


def test_c5_diverted_printed_but_not_judged(tmp_path, capsys):
    rows = [_rec(f"2026-10-27 0{i}:00:00", f"[告警·摘要] 改道 {i}",
                 group="report", noise_class="digest") for i in range(6)]
    rows.append(_rec("2026-10-27 10:00:00", "[恢复] foo 正常", group="report",
                     noise_class="recovery"))
    rows.append(_rec("2026-10-27 11:00:00", "[告警] 【持续故障升级】bar",
                     group="report", noise_class="escalation"))
    rows.append(_rec("2026-10-27 12:00:00", "[告警] 真故障 Z", tier="critical"))
    p = _write_ledger(tmp_path / "l.jsonl", rows)

    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    payload = json.loads(capsys.readouterr().out)
    # report 群 8 条不参与判定: 告警群只有 1 条真故障 ⇒ PASS
    assert rc == 0 and payload["totals"]["alert"] == 1, payload
    assert payload["diverted"] == {"digest": 6, "recovery": 1, "escalation": 1, "total": 8}

    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p)])
    text = capsys.readouterr().out
    assert rc == 0
    assert "改道 report 群" in text and "摘要 6 条" in text and "共 8 条" in text


def test_c6_alert_group_escalation_still_counted_as_noise(tmp_path, capsys):
    """仍留在 alert 群的升级提醒(摘要链路 fail-open)照旧计入噪音 ⇒ 不许被 diverted 洗掉。"""
    rows = [_rec(f"2026-10-27 0{i}:00:00", f"[告警] 【持续故障升级】任务{i}",
                 noise_class="escalation") for i in range(4)]
    p = _write_ledger(tmp_path / "l.jsonl", rows)
    rc = anc.main(["--date", "2026-10-27", "--ledger", str(p), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["diverted"]["total"] == 0
    assert payload["totals"]["breakdown"]["escalation"] == 4
    assert rc == 1


# ═════════════════════ A. 摘要 → report 群 + 邮件保留 ═════════════════════
def test_a1_digest_flush_is_report_group_with_email(env):
    p = env["alerts"] / "alert_digest.jsonl"
    day = datetime.now().strftime("%Y-%m-%d")
    p.write_text(json.dumps({
        "ts": f"{day} 10:00:00", "rid": "d1", "day": day, "key": "k1",
        "category": "warning_batch", "subject": "[告警·聚合] x", "body": "b",
        "from_prefix": "[告警·聚合]", "source": "probe", "reason": "warning_batch_digest_only",
        "hits": 1,
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    r = notify.flush_digest(dry_run=False)
    assert r["sent"] is True, r
    assert env["rec"].feishu_calls and env["rec"].feishu_calls[-1]["chat_key"] == "report"
    assert env["rec"].mails, "摘要移 report 群后邮件必须保留([告警·摘要] 白名单)"
    assert env["rec"].mails[-1][0].startswith("[告警·摘要]")

    row = _ledger(env["alerts"] / "alert_ledger.jsonl")[-1]
    # §22 一致性机检: 台账 group 必须 == 实际发送的 chat_key
    assert row["group"] == env["rec"].feishu_calls[-1]["chat_key"] == "report"
    assert row["noise_class"] == "digest" and row["tier"] == "digest"


# ═════════════════════ A2. 恢复类 fail-open → report + 邮件 ═════════════════════
def test_a2_recovery_fail_open_lands_report_with_email(env, monkeypatch):
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")
    r = notify.send("[恢复] 某任务恢复正常", "body-recovery", source="probe")
    assert not r.get("digested"), r
    assert env["rec"].feishu_calls and env["rec"].feishu_calls[-1]["chat_key"] == "report"
    assert env["rec"].mails, "恢复 fail-open 落 report 群时邮件必须保留"
    assert _digest_entries(env["alerts"] / "alert_digest.jsonl") == []


def test_a3_recovery_absorbed_when_chain_available(env):
    r = notify.send("[恢复] 另一任务恢复正常", "body-recovery-2", source="probe")
    assert r.get("digested") is True and not any(
        (r.get("email"), r.get("telegram"), r.get("feishu"))), r
    entries = _digest_entries(env["alerts"] / "alert_digest.jsonl")
    assert len(entries) == 1
    assert entries[0]["category"] == "recovery"
    assert entries[0]["reason"] == notify.DIGEST_RECOVERY_ABSORB_REASON
    assert not env["rec"].feishu_calls and not env["rec"].mails


# ═════════════════════ B. 持续故障升级并入摘要 ═════════════════════
def test_b1_escalation_absorbed_with_hits(env):
    args = dict(from_prefix="[告警]", feishu_group="alert", digest_only=True,
                ledger_key="active_escalate|probe")
    subj = "[告警] 【持续故障升级】计划任务持续异常升级 probe"
    r1 = notify.send(subj, "持续 24h 未处置", source="probe", **args)
    r2 = notify.send(subj, "持续 24h 未处置", source="probe", **args)
    assert r1.get("digested") is True and r2.get("digested") is True
    assert not env["rec"].feishu_calls and not env["rec"].mails
    entries = _digest_entries(env["alerts"] / "alert_digest.jsonl")
    assert len(entries) == 1, "同键同日只 1 行(幂等)"
    e = entries[0]
    assert e["category"] == "escalation"
    assert e["reason"] == notify.DIGEST_ESCALATION_REASON
    assert e["hits"] == 2, "第二次并入必须 bump_hits, 不丢「同日升级几次」"


def test_b2_critical_never_absorbed(env):
    """check_failed_units 的『升级 critical』走 --severe ⇒ 吸收块(not severe)物理不可达。"""
    r = notify.send("[告警] 【持续故障升级】critical probe", "body", severe=True,
                    from_prefix="[告警]", feishu_group="alert", digest_only=True,
                    ledger_key="active_escalate|critical", source="probe")
    assert not r.get("digested"), r
    assert env["rec"].feishu_calls and env["rec"].feishu_calls[-1]["chat_key"] == "alert"
    assert _digest_entries(env["alerts"] / "alert_digest.jsonl") == []


# ═════════════════════ D. 例行提示 / 改群 / 去重窗 ═════════════════════
def test_d1_routine_orphan_buy_absorbed_as_routine(env):
    r = notify.send("[kelly] 冻结表新增孤儿买事件 3 条(累计 9 条)", "样例: x",
                    from_prefix="[kelly]", feishu_group="alert", digest_only=True,
                    ledger_key="kelly_freeze_orphan_buy", source="probe")
    assert r.get("digested") is True
    entries = _digest_entries(env["alerts"] / "alert_digest.jsonl")
    assert entries and entries[0]["category"] == "routine"
    assert entries[0]["reason"] == notify.DIGEST_ROUTINE_REASON
    assert not env["rec"].feishu_calls


def test_d2_repeat_window_24h_boundaries(env, monkeypatch):
    """6h05m 前发过: 旧 6h 窗会放行(噪声来源), 新 24h 窗抑制; 24h01m 前: 新窗也放行(必达)。"""
    def _seed(age_seconds: int):
        ts = (datetime.now() - timedelta(seconds=age_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        (env["alerts"] / "notify_dedup.json").write_text(json.dumps(
            {"verify_r2_mass_mismatch": {"last_alerted": ts}}), encoding="utf-8")

    _seed(6 * 3600 + 5 * 60)  # 6h05m
    assert notify.check_dedup("verify_r2_mass_mismatch", 21600) is False  # 旧口径会重发
    assert notify.check_dedup("verify_r2_mass_mismatch", 86400) is True   # 新口径抑制

    _seed(24 * 3600 + 60)     # 24h01m
    assert notify.check_dedup("verify_r2_mass_mismatch", 86400) is False


def test_d3_upload_r2_dedup_windows_source_shape():
    src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    assert src.count("check_dedup(_dedup_key, 86400)") == 2, "两处 repeat 源都要改 24h"
    assert "check_dedup(_dedup_key, 21600)" not in src


def test_d4_skip_notify_routes_report_and_docstring_updated():
    src = (SCRIPTS / "r2_upload_skip_notify.sh").read_text(encoding="utf-8")
    assert "--feishu-group report" in src
    assert "--feishu-group alert" not in src
    assert "#321" in src, "口径变更理由必须与行为同批写进 docstring(§23.8)"


def test_d5_orphan_buy_caller_passes_digest_only():
    src = (SCRIPTS / "signal_kelly_backtest.py").read_text(encoding="utf-8")
    block = src[src.index("kelly_freeze_orphan_buy") - 900:
                src.index("kelly_freeze_orphan_buy") + 200]
    assert '"--digest-only"' in block
    # fail-open 落点仍是 alert 群 + 邮件(吸收块前置条件), 不许顺手改成 report
    assert '"--feishu-group", "alert"' in block