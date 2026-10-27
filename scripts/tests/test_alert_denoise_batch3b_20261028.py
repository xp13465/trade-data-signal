# -*- coding: utf-8 -*-
"""告警降噪批次3-B(2026-10-28)用例: warning 聚合批/恢复留痕并入摘要 + noise_class 打标 + C2 尺子兜底。

规格: docs/ops/alert-denoise-spec-20261027.md(★6 + 批次3-B 落地段)
设计要点(验收口径见任务书 A/B/C/C2):
  A  warning 聚合批 → 先并入当日摘要; 摘要链路不可用(ALERT_DIGEST_DISABLE / ALERT_BUDGET_DISABLE /
     append 失败) ⇒ fail-open 直发(宁多发不吞)。
  B  恢复类 → 在 send() 内**清零去重状态之后**并入摘要(category=recovery); 停摆/普通 critical 不受影响。
  C  发送侧 noise_class 打标: digest / warning_batch / recovery / escalation, 其余 None。
  C2 尺子读侧兜底: critical 行除 escalation 外, 任何显式 noise_class 都不得降级成噪音。

零真实外发: 三个底层渠道(_send_email/send_telegram/send_feishu)全部替身 + ZeroOutboundTrap 兜底。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import notify  # noqa: E402
import alert_noise_count as anc  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

SRC_NOTIFY = SCRIPTS / "notify.py"


# ─────────────────────────── 夹具: 全路径隔离 + 渠道替身 ───────────────────────────
class _Recorder:
    def __init__(self):
        self.mails = []

    def email(self, subject, body, **kw):
        self.mails.append((str(subject), str(body)))
        return True


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """把 notify 的全部状态文件指到 tmp; 渠道打桩; 清掉相关开关环境变量。"""
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
    # 摘要窗口改成 00:00 ⇒ 任何时刻 flush_digest 都可发(不冻墙钟)
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")
    monkeypatch.setenv("REPO", str(tmp_path))
    for k in ("ALERT_DIGEST_DISABLE", "ALERT_BUDGET_DISABLE", "ALERT_NOTICE_BUDGET_DISABLE",
              "ALERT_DOMAIN_DISABLE", "ALERT_LEDGER_DISABLE", "EMAIL_GROUP_GATE_DISABLE"):
        monkeypatch.delenv(k, raising=False)
    rec = _Recorder()
    monkeypatch.setattr(notify, "_send_email", rec.email)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(notify, "send_feishu", lambda *a, **k: True)
    return {"tmp": tmp_path, "alerts": alerts, "rec": rec,
            "digest": alerts / "alert_digest.jsonl",
            "buffer": alerts / "warning_buffer.jsonl",
            "dedup": alerts / "warning_dedup_state.json"}


def _old_ts(minutes: int = 60) -> str:
    return (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _seed_warning_buffer(path: Path, items: list[tuple[str, str]]) -> None:
    """写满窗(已到期)的 warning 条目; subject/body 用互不同源的文本绕开指纹合并。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for i, (subject, body) in enumerate(items):
            f.write(json.dumps({
                "ts": _old_ts(),
                "rid": f"rid-b3b-{i}",
                "subject": subject,
                "body": body,
                "from_prefix": "[告警·聚合]",
            }, ensure_ascii=False) + "\n")


def _digest_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _flush_and_capture(env) -> str:
    """flush_digest 并返回真正发出去的邮件正文(替身捕获)。"""
    env["rec"].mails.clear()
    r = notify.flush_digest(dry_run=False)
    assert r.get("sent") is True, f"摘要应发出: {r}"
    assert env["rec"].mails, "摘要必须走邮件通道(替身捕获)"
    return env["rec"].mails[-1][1]


# ─────────────────────────── A. warning 聚合批并入摘要 ───────────────────────────
def test_a1_warning_batch_absorbed_not_sent(env):
    """摘要链路可用 ⇒ 聚合批并入摘要, 不直发(取代 3.4 封/天)。"""
    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha"),
                                         ("B-due-bravo", "body-bravo")])
    r = notify.flush_warning_batch(dry_run=False)
    assert r["sent_batch"] is True and r["digested"] is True, r
    assert r["n_due"] == 2 and r["n_remaining"] == 0, r
    assert env["rec"].mails == [], "并入摘要后不得再直发一封聚合邮件"
    cats = [e["category"] for e in _digest_entries(env["digest"])]
    assert cats == ["warning_batch", "warning_batch"], cats


def test_a2_warning_batch_clears_buffer_after_absorb(env):
    """吸收成功 = 已处置 ⇒ buffer 清空(与真发出同语义)。"""
    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
    notify.flush_warning_batch(dry_run=False)
    left = [ln for ln in env["buffer"].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert left == [], f"buffer 未清空: {left}"


def test_a3_warning_batch_failopen_when_digest_disabled(env, monkeypatch):
    """黑洞反例①: ALERT_DIGEST_DISABLE=1 ⇒ 必须走直发(一条路, 不重复)。"""
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")
    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
    r = notify.flush_warning_batch(dry_run=False)
    assert r["digested"] is False and r["sent_batch"] is True, r
    assert len(env["rec"].mails) == 1, f"应恰好直发一封: {env['rec'].mails}"
    assert _digest_entries(env["digest"]) == [], "禁用摘要时不得再写摘要 buffer"


def test_a4_warning_batch_failopen_when_budget_disabled(env, monkeypatch):
    """黑洞反例②: ALERT_BUDGET_DISABLE=1 ⇒ 摘要链路不可用 ⇒ 直发。"""
    monkeypatch.setenv("ALERT_BUDGET_DISABLE", "1")
    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
    r = notify.flush_warning_batch(dry_run=False)
    assert r["digested"] is False and r["sent_batch"] is True, r
    assert len(env["rec"].mails) == 1, f"应恰好直发一封: {env['rec'].mails}"
    assert _digest_entries(env["digest"]) == []


def test_a5_warning_batch_failopen_when_absorb_fails(env, monkeypatch):
    """黑洞反例③: 吸收函数失败 ⇒ 直发(至少一条路发出, 不重复两条)。"""
    monkeypatch.setattr(notify, "_absorb_split_to_digest", lambda *a, **k: False)
    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
    r = notify.flush_warning_batch(dry_run=False)
    assert r["digested"] is False and r["sent_batch"] is True, r
    assert len(env["rec"].mails) == 1, f"应恰好直发一封: {env['rec'].mails}"
    assert _digest_entries(env["digest"]) == []


def test_a6_warning_batch_keeps_buffer_when_send_fails(env, monkeypatch):
    """直发失败 ⇒ buffer 保留待下轮(不丢不重)。"""
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")
    monkeypatch.setattr(notify, "_send_email", lambda *a, **k: False)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    monkeypatch.setattr(notify, "send_feishu", lambda *a, **k: False)
    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
    r = notify.flush_warning_batch(dry_run=False)
    assert r["sent_batch"] is False and r["digested"] is False, r
    assert r["n_remaining"] == 1, f"失败必须保留条目: {r}"


# ─────────────────────────── B. 恢复留痕并入摘要 ───────────────────────────
def test_b1_recovery_absorbed_and_dedup_cleared(env):
    """恢复被吸收进摘要, 且 dedup state 对应 warning 指纹确被清零(清零在吸收之前)。"""
    fp = "fp-alpha"
    env["dedup"].write_text(json.dumps({
        fp: {"norm_subject": "A-due-alpha", "repeat_count": 3,
             "last_enqueued": _old_ts(10)},
    }), encoding="utf-8")
    subject = "[恢复] A-due-alpha 已恢复 10-28 03:00"
    r = notify.send(subject, "A-due-alpha 异常关键词<kw> 已消失", severe=False)
    assert r.get("digested") is True, f"恢复应并入摘要: {r}"
    assert env["rec"].mails == [], "恢复不得再单独外发"
    state = json.loads(env["dedup"].read_text(encoding="utf-8"))
    assert fp not in state, f"恢复必须照旧清零 warning 指纹状态: {state}"
    entries = _digest_entries(env["digest"])
    assert len(entries) == 1 and entries[0]["category"] == "recovery", entries
    assert entries[0]["reason"] == notify.DIGEST_RECOVERY_ABSORB_REASON


def test_b2_recovery_failopen_when_digest_disabled(env, monkeypatch):
    """摘要链路禁用 ⇒ 恢复 fail-open 直发(不丢闭环信号)。"""
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")
    r = notify.send("[恢复] A-due-alpha 已恢复 10-28 03:00", "已消失", severe=False)
    assert not r.get("digested")
    assert r.get("email") is True and len(env["rec"].mails) == 1, r


def test_b3_recovery_failopen_when_absorb_fails(env, monkeypatch):
    """吸收失败 ⇒ 恢复 fail-open 直发(恰好一条)。"""
    monkeypatch.setattr(notify, "_absorb_split_to_digest", lambda *a, **k: False)
    r = notify.send("[恢复] A-due-alpha 已恢复 10-28 03:00", "已消失", severe=False)
    assert not r.get("digested")
    assert len(env["rec"].mails) == 1, r


def test_b4_stall_critical_not_absorbed(env):
    """停摆级(必须在摘要 gate 之前短路) ⇒ 仍即时直发, 没进摘要。"""
    r = notify.send("[告警] deploy 连续失败", "deploy 连续 3 轮失败",
                    severe=True, ledger_key="deploy_consecutive_fail")
    assert not r.get("digested"), r
    assert r.get("email") is True, r
    assert _digest_entries(env["digest"]) == [], "停摆级不得进摘要"


def test_b5_plain_critical_not_absorbed(env):
    """普通 critical 首报 ⇒ 仍即时直发, 没进摘要。"""
    r = notify.send("[告警] 某采集失败", "采集失败详情", severe=True)
    assert not r.get("digested"), r
    assert len(env["rec"].mails) == 1, r


# ─────────────────────────── 内容保真(§23.10) ───────────────────────────
def test_c1_content_fidelity_warning_20_items(env):
    """warning 批量 20 条 ⇒ 摘要正文逐条都在, 不截断/省略号/「等 N 条」。"""
    items = [(f"W-due-{chr(ord('a') + i)}", f"warning-body-{chr(ord('a') + i)}")
             for i in range(20)]
    _seed_warning_buffer(env["buffer"], items)
    r = notify.flush_warning_batch(dry_run=False)
    assert r["digested"] is True, r
    body = _flush_and_capture(env)
    for subject, detail in items:
        assert subject in body, f"摘要丢了条目: {subject}"
        assert detail in body, f"摘要丢了明细: {detail}"
    assert "..." not in body and "等 " not in body and "…" not in body


def test_c2_content_fidelity_recovery_20_lines(env):
    """恢复明细 20 条且正文超单条上限 ⇒ 拆段入摘要, 20 条明细逐条可见。"""
    lines = [
        f"[恢复] task{i:02d} 异常关键词<kw{i:02d}> 已消失 (首次发现: 2026-10-27 10:00, "
        f"恢复时间: 2026-10-28 03:00) 备注{'x' * 120}"
        for i in range(20)
    ]
    body = "<br>".join(lines)
    assert len(body) > notify.DIGEST_ENTRY_BODY_LIMIT, "构造用例必须真的超单条上限"
    r = notify.send("[恢复] 20项异常恢复 10-28 03:00", body, severe=False)
    assert r.get("digested") is True, r
    entries = _digest_entries(env["digest"])
    assert len(entries) >= 2, f"超长正文必须拆成多段(拆条), 实际 {len(entries)} 段"
    for e in entries:
        assert len(e["body"]) <= notify.DIGEST_ENTRY_BODY_LIMIT
    out = _flush_and_capture(env)
    for i in range(20):
        assert f"kw{i:02d}" in out, f"摘要丢了第 {i} 条恢复明细"
    assert "…" not in out and "等 20 条" not in out


# ─────────────────────────── C. 发送侧打标 ───────────────────────────
def test_d1_noise_class_four_types_and_none(env, monkeypatch):
    """四类消息各一条 ⇒ 台账 noise_class 分别为 digest/warning_batch/recovery/escalation; 普通=None。"""
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")  # 全部走直发, 才有台账行
    cases = [
        ("[告警·摘要] 当日合并 3 条 10-28 23:25", "digest"),
        ("[告警·聚合] 3条 warning 汇总 10-28 03:00", "warning_batch"),
        ("[恢复] task 异常关键词<kw> 已消失 10-28 03:00", "recovery"),
        ("[告警] 【持续故障升级】某任务已连续 3 天", "escalation"),
        ("[告警] 普通采集失败", None),
    ]
    for subject, _ in cases:
        notify.send(subject, "body", severe=False)
    ledger = Path(os.environ["REPO"]) / "data" / "alerts" / "alert_ledger.jsonl"
    rows = [json.loads(ln) for ln in ledger.read_text(encoding="utf-8").splitlines() if ln.strip()]
    got = [r.get("noise_class") for r in rows]
    assert got == [c[1] for c in cases], f"打标不符: {got}"


def test_d2_noise_class_docstring_single_source():
    """值域单一事实源: notify 的 docstring 与 alert_noise_count docstring 逐字一致。"""
    n_src = SRC_NOTIFY.read_text(encoding="utf-8")
    a_src = (SCRIPTS / "alert_noise_count.py").read_text(encoding="utf-8")
    line = "digest / warning_batch / recovery / escalation"
    assert line in n_src, "notify 侧缺值域声明"
    assert line in a_src, "尺子侧缺值域声明(两处必须逐字一致)"
    assert "routine_notice" in n_src and "routine_notice" in a_src


def test_d3_record_ledger_omits_field_by_default():
    """旧行形态兼容: noise_class=None 时**不写字段**(读侧 .get() 兼容), 不制造空串。"""
    import inspect
    sig = inspect.signature(notify._record_ledger)
    assert sig.parameters["noise_class"].default is None


# ─────────────────────────── C2. 尺子读侧兜底 ───────────────────────────
def _ledger_row(tier: str, subject: str, noise_class: str | None = None,
                ts: str | None = None) -> dict:
    row = {"ts": ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "tier": tier, "subject": subject, "group": "alert"}
    if noise_class is not None:
        row["noise_class"] = noise_class
    return row


def _classify_one(rec: dict) -> dict:
    day = rec["ts"][:10]
    return anc.classify_rows([rec], [day])


def test_e1_critical_with_repeat_tag_counts_as_real(env):
    """C2: critical + noise_class=repeat ⇒ 计真故障(不得被显式标签降级成噪音)。"""
    res = _classify_one(_ledger_row("critical", "[告警] 真故障", "repeat"))
    assert res["totals"]["noise"] == 0, res["totals"]
    assert res["totals"]["real"] == 1, res["totals"]


def test_e2_critical_with_escalation_tag_counted_separately(env):
    """C2: critical + noise_class=escalation ⇒ 升级单列(口径待拍板)。"""
    res = _classify_one(_ledger_row("critical", "[告警] 持续故障升级", "escalation"))
    assert res["totals"]["escalation"] == 1, res["totals"]
    assert res["totals"]["breakdown"].get("escalation") == 1, res["totals"]


def test_e3_notice_with_repeat_tag_still_repeat(env):
    """C2 对照组: notice + noise_class=repeat ⇒ 照旧算 repeat。"""
    res = _classify_one(_ledger_row("notice", "[告警] 重复播报", "repeat"))
    assert res["totals"]["breakdown"].get("repeat") == 1, res["totals"]


# ─────────────────────────── 零外发 / 运维口径 ───────────────────────────
def test_f1_zero_outbound(env):
    """整条链路跑一遍(吸收 + 摘要出线)全程零真实外发。"""
    with ZeroOutboundTrap() as trap:
        _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
        notify.flush_warning_batch(dry_run=False)
        notify.send("[恢复] A-due-alpha 已恢复 10-28 03:00", "已消失", severe=False)
        notify.flush_digest(dry_run=False)
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"


def test_f2_schedule_monitor_treats_digested_as_handled():
    """schedule_monitor 必须把 status=digested 当作已处置(否则入 pending ⇒ 摘要重复一条)。"""
    src = (SCRIPTS / "schedule_monitor.sh").read_text(encoding="utf-8")
    assert 'globals().get("_read_notify_result_status")' in src
    assert '_st_reader(_rf) == "digested"' in src
    assert '_s in ("sent", "digested")' in src
    assert 'return "digested"' in src


def test_f3_recovery_block_digested_not_pending():
    """行为级: 真跑 schedule_monitor 的恢复发送块, status=digested ⇒ 不入 pending 桶。"""
    import ast
    import textwrap
    import types

    from notify_sent import notify_state

    slines = (SCRIPTS / "schedule_monitor.sh").read_text(encoding="utf-8").splitlines(
        keepends=True)
    h0 = next(i for i, ln in enumerate(slines) if "<<'PYEOF'" in ln)
    h1 = next(i for i, ln in enumerate(slines) if i > h0 and ln.strip() == "PYEOF")
    tree = ast.parse("".join(slines[h0 + 1:h1]))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                and isinstance(n.test, ast.Name) and n.test.id == "_combined")
    block = compile(textwrap.dedent(
        "".join(slines[h0 + node.lineno:h0 + node.end_lineno + 1])),
        "<recovery-block>", "exec")

    class _Sub:
        def __init__(self):
            self.calls = []

        def run(self, argv, **kw):
            self.calls.append(list(argv))
            if "--result-file" in argv:
                Path(argv[argv.index("--result-file") + 1]).write_text(
                    json.dumps({"status": "digested"}), encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    rec = {"task": "taskA", "keyword": "exit", "first_seen": "?", "tier": "severe"}
    ns = {
        "sys": sys, "REPO": ROOT, "MONITOR_LOG": Path("/tmp/monitor-b3b.log"),
        "NOW": datetime(2026, 10, 28, 4, 0, 0), "now_str": "2026-10-28 04:00:00",
        "print": (lambda *a, **k: None), "notify_state": notify_state,
        "_PEND_KEY": "monitor_recovery|pending", "alert_state": {},
        "save_alert_state": (lambda st: None), "subprocess": _Sub(),
        "_combined": [rec], "recoveries": [rec], "_pend_items": [], "_pend_tks": set(),
        "_pend_n": 0, "_read_notify_result_status": lambda p: "digested",
    }
    exec(block, ns)  # noqa: S102
    assert ns["alert_state"].get("monitor_recovery|pending") is None, \
        f"digested 不应入 pending: {ns['alert_state']}"


# ────────── G. 审查返工1：拆段吸收必须传 bump_hits(#253-d2 不变式) ──────────
def _freeze_datetime(monkeypatch, at: str) -> None:
    """冻结 `notify.datetime.now()`（L51：用例不得依赖真实运行日/墙钟）。

    只替换 notify 模块里那个名字（`from datetime import datetime`），不动标准库类。
    """
    fixed = datetime.strptime(at, "%Y-%m-%d %H:%M:%S")

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(notify, "datetime", _Frozen)


def _wbatch_key(fp: str, body: str) -> str:
    """与生产 flush_warning_batch 同式（内容哈希入键）：不同正文落不同摘要条目。"""
    return "wbatch|" + hashlib.sha1((fp + "|" + body).encode("utf-8")).hexdigest()[:16]


def test_g1_split_absorb_same_group_twice_bumps_hits(env, monkeypatch):
    """同 group 同正文吸收两次 ⇒ 仍是 1 条摘要, 但 hits=2 且最近时刻被更新。

    漏传 `bump_hits=True` 时第二次被幂等静默吞掉（hits 停在 1、无 hits_ts）——
    这正是审查实测到的缺陷，也是 `_absorb_to_digest` docstring「全部调用点均传 True」的
    不变式被破坏点。
    """
    body = "same-body-alpha"
    key = _wbatch_key("fp-alpha", body)
    subj = "[告警·聚合] 1条 warning 汇总 10-28 03:00"
    _freeze_datetime(monkeypatch, "2026-10-28 03:00:00")
    assert notify._absorb_split_to_digest(subj, body, key=key,
                                          category="warning_batch",
                                          reason="review_rework") is True
    _freeze_datetime(monkeypatch, "2026-10-28 03:25:00")
    assert notify._absorb_split_to_digest(subj, body, key=key,
                                          category="warning_batch",
                                          reason="review_rework") is True
    entries = _digest_entries(env["digest"])
    assert len(entries) == 1, f"同 group 同正文只该 1 条(幂等不重复写): {entries}"
    assert entries[0]["hits"] == 2, f"第二次吸收必须 hits+1: {entries[0]}"
    assert entries[0]["hits_ts"] == "2026-10-28 03:25:00", \
        f"最近时刻必须被更新: {entries[0]}"


def test_g2_split_absorb_different_body_not_merged(env, monkeypatch):
    """对照组: 同指纹不同正文 ⇒ 两条并列、各自 hits=1（不得串成一条）。"""
    _freeze_datetime(monkeypatch, "2026-10-28 03:00:00")
    subj = "[告警·聚合] 1条 warning 汇总 10-28 03:00"
    for body in ("body-A", "body-B"):
        assert notify._absorb_split_to_digest(subj, body,
                                              key=_wbatch_key("fp-alpha", body),
                                              category="warning_batch",
                                              reason="review_rework") is True
    entries = _digest_entries(env["digest"])
    assert len(entries) == 2, f"不同正文必须各留一条: {entries}"
    assert [e["hits"] for e in entries] == [1, 1], entries
    assert {e["body"] for e in entries} == {"body-A", "body-B"}, entries


# ────── H. 审查返工2：两条新并入成功行必须判「已处置」而非 failed ──────
# 样本一律由**被测代码自己打印**(真跑吸收路径 + capsys 捕获), 不手写"看起来合理"的假样本(L49)。
def test_h1_notify_state_recovery_digest_line(env, capsys):
    """恢复留痕并入成功行 ⇒ notify_state == suppressed（判 failed 会让监控重列 ⇒ 摘要重复）。"""
    from notify_sent import notify_state

    r = notify.send("[恢复] schedule_monitor taskA 异常关键词<exit> 已消失 10-28 03:25",
                    "taskA 异常关键词<exit> 已消失<br>— 无需操作, 异常已自动恢复 —",
                    severe=False)
    assert r.get("digested") is True, f"恢复应并入摘要: {r}"
    out, err = capsys.readouterr()
    got = notify_state(out + err)
    assert got == "suppressed", f"恢复并入行应判 suppressed, 实际 {got}: {(out + err)[:300]}"


def test_h2_notify_state_warning_batch_digest_line(env, capsys):
    """warning 聚合批并入成功行 ⇒ notify_state == suppressed。"""
    from notify_sent import notify_state

    _seed_warning_buffer(env["buffer"], [("A-due-alpha", "body-alpha")])
    r = notify.flush_warning_batch(dry_run=False)
    assert r.get("digested") is True, r
    out, err = capsys.readouterr()
    got = notify_state(out + err)
    assert got == "suppressed", f"聚合批并入行应判 suppressed, 实际 {got}: {(out + err)[:300]}"


def test_h3_notify_state_real_failure_still_failed(env):
    """对照组: 真失败/真「并入失败」文本仍判 failed（防「一律放过」的假修）。"""
    from notify_sent import notify_state

    assert notify_state("[notify] 汇总：全部渠道未发出（email/feishu 均失败）") == "failed"
    assert notify_state(
        "[notify][digest] warning 聚合批并入失败(buffer append) → fail-open 直发: n=1"
    ) == "failed"
    assert notify_state(
        "[notify][digest] 恢复留痕并入失败(buffer append) → fail-open 直发: [恢复] x"
    ) == "failed"