# -*- coding: utf-8 -*-
"""告警降噪批次3-C(2026-10-28)用例: verify_r2 类别映射 + 「跨日同签名并入摘要」判据。

规格: docs/ops/alert-denoise-spec-20261027.md(批次3-C 落地段)
根因: /tmp/gate-gap-report.md(调研结论)
  病根 A  upload_r2.py 的 `verify_r2_standalone_stale` / `verify_r2_mass_mismatch` 不以 r2_
          开头 ⇒ category_of=None ⇒ severe/notice/域三门**整门跳过**(7 天 17 条绕过)。
  病根 B  调用方自带 6h/24h 前置 dedup ⇒ 同一自然日不可能有第 2 条到达 notify ⇒ 旧判据
          「当日已直发≥额度 且 当日同签名」恒判首条 ⇒ 每天各发一封, 永不收敛。

本文件逐条守任务书的 7 条硬约束 + 跨日边界 + fail-open 三态 + 摘要逐条可见:
  1 tier=="critical" 永不吸收(首报必达; 升级通道不动)
  2 新签名(近 N 天无直发记录)⇒ 直发
  3 停摆级在 gate 之前短路 ⇒ 独立直发
  4 ALERT_DIGEST_DISABLE=1 / ALERT_BUDGET_DISABLE=1 / 吸收失败 ⇒ fail-open 直发
  5 吸收的条目在摘要里逐条可见(subject + 次数 xN)
  6 同一签名当日首条/首现不得被吞(第一天首报直发)
  7 窗口 N 可配(ALERT_REPEAT_ABSORB_DAYS, 默认 7; 非法 → 7 + WARN)

零真实外发: 三个底层渠道(_send_email/send_telegram/send_feishu)全部替身 + ZeroOutboundTrap 兜底。
时间: 所有用例冻结运行日(L51: 被测代码内部取 datetime.now() ⇒ 用例必须注入/冻结, 禁写死"今天")。
"""
from __future__ import annotations

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
import alert_denoise_rules as adr  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

FROZEN_NOW = "2026-10-28 04:00:00"


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
    monkeypatch.setattr(notify, "ALERT_DIGEST_HM", "00:00")
    monkeypatch.setenv("REPO", str(tmp_path))
    for k in ("ALERT_DIGEST_DISABLE", "ALERT_BUDGET_DISABLE", "ALERT_NOTICE_BUDGET_DISABLE",
              "ALERT_DOMAIN_DISABLE", "ALERT_LEDGER_DISABLE", "EMAIL_GROUP_GATE_DISABLE",
              "ALERT_REPEAT_ABSORB_DAYS"):
        monkeypatch.delenv(k, raising=False)
    rec = _Recorder()
    monkeypatch.setattr(notify, "_send_email", rec.email)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: True)
    monkeypatch.setattr(notify, "send_feishu", lambda *a, **k: True)
    return {"tmp": tmp_path, "alerts": alerts, "rec": rec,
            "digest": alerts / "alert_digest.jsonl",
            "ledger": alerts / "alert_ledger.jsonl"}


def _freeze(monkeypatch, at: str = FROZEN_NOW) -> datetime:
    """冻结 notify 与 alert_denoise_rules 的 `datetime.now()`(L51: 禁依赖真实运行日)。"""
    fixed = datetime.strptime(at, "%Y-%m-%d %H:%M:%S")

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(notify, "datetime", _Frozen)
    monkeypatch.setattr(adr, "datetime", _Frozen)
    return fixed


def _seed_ledger(env, rows: list[dict]) -> None:
    """往隔离台账写历史行(默认 = group=alert / tier=notice / 已实际外发)。"""
    env["ledger"].parent.mkdir(parents=True, exist_ok=True)
    with open(env["ledger"], "a", encoding="utf-8") as f:
        for r in rows:
            rec = {"ts": FROZEN_NOW, "tree": "/tmp/test-tree", "tier": "notice",
                   "key": "k-default", "subject": "[告警] 占位",
                   "channels": {"email": True, "feishu": True},
                   "source": "test", "group": "alert"}
            rec.update(r)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _digest_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _ledger_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


SUBJ_STALE = "[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)"
KEY_STALE = "verify_r2_standalone_stale"
SUBJ_MASS = "[告警] R2 可能被异源覆盖(verify-r2 大量不一致)"
KEY_MASS = "verify_r2_mass_mismatch"


# ─────────────────────────── A. 类别映射补齐 ───────────────────────────
def test_a1_category_of_verify_r2_keys():
    """A: verify-r2 两类必须映射到既有 r2 类别(否则三门整门跳过 = 病根)。"""
    assert adr.category_of(KEY_STALE, SUBJ_STALE) == "r2"
    assert adr.category_of(KEY_MASS, SUBJ_MASS) == "r2"
    # 第三个同族点(对账台账缺失)也归 r2(同一前缀族, 举一反三)
    assert adr.category_of("verify_r2_standalone_ledger_gap", "[告警] 台账缺失") == "r2"


def test_a2_category_of_other_values_unchanged():
    """A 反例: 补前缀不得改动其他类别的映射(既有规则一字不变)。"""
    assert adr.category_of("unit_patrol_x", "") == "unit"
    assert adr.category_of("r2_upload_async_skip:/tmp/x", "") == "r2"
    assert adr.category_of("deploy_consecutive_fail", "") == "deploy"
    assert adr.category_of("fund_nav_stale", "") == "fund_nav"
    assert adr.category_of("kelly_freeze_orphan_buy", "") == "kelly"
    assert adr.category_of("data_gap_x", "") == "data_gap"
    assert adr.category_of("完全未映射的键", "普通业务播报") is None


# ─────────────────────────── B. 判据本体(纯函数) ───────────────────────────
def test_b1_critical_never_absorbed_unit():
    """硬约束1(纯函数级): tier==critical ⇒ 即使近 N 天同签名在集合内也**永不吸收**。"""
    assert adr.repeat_recent_absorb_judge("critical", "sig-x", {"sig-x"}) is False
    assert adr.repeat_recent_absorb_judge("notice", "sig-x", {"sig-x"}) is True


def test_b1b_critical_tier_message_not_absorbed_end_to_end(env, monkeypatch):
    """硬约束1(行为级): 显式 ledger_tier="critical" 的消息, 即使近 N 天有同签名直发行,
    也必须走直发(本门不吸收 critical 行 —— 首报必达; 升级通道不动)。"""
    fixed = _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r = notify.send(SUBJ_STALE, "R2 副本与本地不一致", severe=False,
                    ledger_tier="critical", ledger_key=KEY_STALE)
    assert not r.get("digested"), f"critical 行绝不能被新判据吸收: {r}"
    assert len(env["rec"].mails) == 1, r
    assert _digest_entries(env["digest"]) == []
    row = _ledger_rows(env["ledger"])[-1]
    assert row["tier"] == "critical" and row["key"] == KEY_STALE, row


def test_b1c_critical_ledger_rows_do_not_feed_notice_window(env, monkeypatch):
    """硬约束1(数据侧): 台账里 **critical 行不进** notice 门的近 N 天集合 ⇒ critical 行
    既不会吞噬后续 notice, 也不与 notice 额度互相挤占(B1 口径不破); report 群行同样不算。

    带正控(防「集合恒空」的假绿): 同一条读取函数必须能收录 alert 群的 notice 行。
    """
    fixed = _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "critical", "key": KEY_STALE, "subject": SUBJ_STALE},
                       {"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_MASS, "subject": SUBJ_MASS,
                        "group": "report"},
                       {"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": "kelly_freeze_orphan_buy",
                        "subject": "[kelly] 孤儿买事件 21 条"}])
    keys = adr.ledger_recent_direct_keys(env["tmp"], days=7, tiers={"notice", "warning"})
    assert KEY_STALE not in keys, "critical 行不得进 notice 门的近 N 天集合"
    assert KEY_MASS not in keys, "report 群的行不得进告警门的近 N 天集合"
    assert "kelly_freeze_orphan_buy" in keys, "正控: alert 群 notice 行必须被收录"
    r = notify.send(SUBJ_STALE, "R2 副本与本地不一致", severe=False, ledger_key=KEY_STALE)
    assert not r.get("digested"), f"critical 行不得让同签名 notice 被吸收: {r}"


def test_b2_new_signature_always_direct(env, monkeypatch):
    """硬约束2: 新签名(近 N 天台账无同签名直发记录)⇒ 永远直发。"""
    _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": "2026-10-27 04:00:00", "tier": "notice",
                        "key": "另一个完全不同的签名", "subject": "[告警] 别的故障"}])
    r = notify.send(SUBJ_STALE, "第一次出现", severe=False, ledger_key=KEY_STALE)
    assert not r.get("digested"), r
    assert len(env["rec"].mails) == 1, r


def test_b3_stall_shortcircuits_before_gate(env, monkeypatch):
    """硬约束3: 停摆级在 gate 之前短路 ⇒ 独立直发, 不进摘要、不占额度。"""
    _freeze(monkeypatch)
    r = notify.send("[告警] deploy 连续失败", "deploy 连续 3 轮失败",
                    severe=True, ledger_key="deploy_consecutive_fail")
    assert not r.get("digested"), r
    assert r.get("email") is True, r
    assert _digest_entries(env["digest"]) == []


def test_b4_failopen_when_digest_disabled(env, monkeypatch):
    """硬约束4①: ALERT_DIGEST_DISABLE=1 ⇒ 摘要链路不可用 ⇒ 直发(不写进永不 flush 的 buffer)。"""
    fixed = _freeze(monkeypatch)
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r = notify.send(SUBJ_STALE, "重复", severe=False, ledger_key=KEY_STALE)
    assert not r.get("digested") and r.get("email") is True, r
    assert _digest_entries(env["digest"]) == []


def test_b4b_failopen_when_budget_disabled(env, monkeypatch):
    """硬约束4②: ALERT_BUDGET_DISABLE=1(总开关)⇒ 直发。"""
    fixed = _freeze(monkeypatch)
    monkeypatch.setenv("ALERT_BUDGET_DISABLE", "1")
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r = notify.send(SUBJ_STALE, "重复", severe=False, ledger_key=KEY_STALE)
    assert not r.get("digested") and r.get("email") is True, r
    assert _digest_entries(env["digest"]) == []


def test_b4c_failopen_when_absorb_fails(env, monkeypatch):
    """硬约束4③: 吸收函数失败(append 失败)⇒ fail-open 直发(恰好一条, 不重复)。"""
    fixed = _freeze(monkeypatch)
    monkeypatch.setattr(notify, "_absorb_to_digest", lambda *a, **k: False)
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r = notify.send(SUBJ_STALE, "重复", severe=False, ledger_key=KEY_STALE)
    assert not r.get("digested") and len(env["rec"].mails) == 1, r


def test_b5_absorbed_entry_visible_in_digest_with_hits(env, monkeypatch):
    """硬约束5: 吸收的条目在摘要里**逐条可见**(subject + x2 次数 + 人读原因), 不许只写「已吸收 N 条」。"""
    fixed = _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r1 = notify.send(SUBJ_STALE, "第 1 次重复", severe=False, ledger_key=KEY_STALE)
    assert r1.get("digested") is True, r1
    _freeze(monkeypatch, "2026-10-28 04:25:00")
    r2 = notify.send(SUBJ_STALE, "第 2 次重复", severe=False, ledger_key=KEY_STALE)
    assert r2.get("digested") is True, r2
    entries = _digest_entries(env["digest"])
    assert len(entries) == 1 and entries[0]["hits"] == 2, entries
    assert entries[0]["reason"] == adr.REPEAT_RECENT_ABSORB_REASON, entries[0]
    env["rec"].mails.clear()
    res = notify.flush_digest(dry_run=False)
    assert res.get("sent") is True, res
    body = env["rec"].mails[-1][1]
    assert SUBJ_STALE in body, f"摘要丢了条目主题: {body[:400]}"
    assert " x2" in body and "(最近 04:25)" in body, f"摘要缺次数/最近时刻: {body[:600]}"
    assert "近 N 天同签名已直发过(跨日重复)" in body, f"摘要缺人读原因: {body[:600]}"


def test_b6_first_occurrence_direct_then_next_day_absorbed(env, monkeypatch):
    """硬约束6: 同一签名的**首现**(第一天首报)必直发; 次日同签名才并入。"""
    _freeze(monkeypatch)
    r1 = notify.send(SUBJ_STALE, "第一次(首报)", severe=False, ledger_key=KEY_STALE)
    assert not r1.get("digested") and len(env["rec"].mails) == 1, r1
    assert _ledger_rows(env["ledger"])[-1]["tier"] == "notice"
    _freeze(monkeypatch, "2026-10-29 04:00:00")
    r2 = notify.send(SUBJ_STALE, "第二天同签名", severe=False, ledger_key=KEY_STALE)
    assert r2.get("digested") is True, f"次日同签名应并入摘要: {r2}"
    assert len(env["rec"].mails) == 1, "并入后不得再单独外发一封"


def test_b7_window_configurable_and_illegal_falls_back(env, monkeypatch, capsys):
    """硬约束7: 窗口 N 由 ALERT_REPEAT_ABSORB_DAYS 控制; 非法值 → 7 + WARN。"""
    assert adr.repeat_absorb_days() == 7
    monkeypatch.setenv("ALERT_REPEAT_ABSORB_DAYS", "3")
    assert adr.repeat_absorb_days() == 3
    monkeypatch.setenv("ALERT_REPEAT_ABSORB_DAYS", "0")
    assert adr.repeat_absorb_days() == 7
    monkeypatch.setenv("ALERT_REPEAT_ABSORB_DAYS", "abc")
    assert adr.repeat_absorb_days() == 7
    err = capsys.readouterr().err
    assert "ALERT_REPEAT_ABSORB_DAYS" in err and "非法" in err and "回退默认 7" in err


def test_b8_huge_env_clamped_and_never_crashes(env, monkeypatch, capsys):
    """审查返工项: env 超大 N(1000000) 必须夹紧到安全上限, 不许把 notify.send 打崩。

    病根: 窗口起点 = today-(N-1) 天, N 过大 ⇒ 早于公元 1 年 ⇒ `datetime.strptime - timedelta`
    抛 OverflowError(在 try 之外)⇒ 整条通知链崩(审查实测 `ALERT_REPEAT_ABSORB_DAYS=1000000`)。
    """
    monkeypatch.setenv("ALERT_REPEAT_ABSORB_DAYS", "1000000")
    assert adr.repeat_absorb_days() == adr.ALERT_REPEAT_ABSORB_DAYS_MAX
    err = capsys.readouterr().err
    assert "超出上限" in err and str(adr.ALERT_REPEAT_ABSORB_DAYS_MAX) in err, err

    fixed = _freeze(monkeypatch)
    # 实际窗口断言(夹紧到 3650 天的真实效果): 8 天前(=默认 7 天窗外)的行仍在窗内 ⇒ 并入
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    assert KEY_STALE in adr.ledger_recent_direct_keys(env["tmp"], tiers={"notice", "warning"})
    r = notify.send(SUBJ_STALE, "超大 N 样本", severe=False, ledger_key=KEY_STALE)
    assert r.get("digested") is True, f"超大 N 下 notify.send 不许崩且窗口按夹紧值生效: {r}"


@pytest.mark.parametrize("raw", ["abc", "", "   "])
def test_b9_blank_or_non_numeric_env_falls_back_with_warn(monkeypatch, capsys, raw):
    """审查返工项: 非整数 / 空串 / 纯空白 ⇒ 回退 7 且**必须 WARN**(此前空值静默回落)。"""
    monkeypatch.setenv("ALERT_REPEAT_ABSORB_DAYS", raw)
    assert adr.repeat_absorb_days() == adr.ALERT_REPEAT_ABSORB_DAYS_DEFAULT
    err = capsys.readouterr().err
    assert "ALERT_REPEAT_ABSORB_DAYS" in err and "回退默认 7" in err, err


def test_b10_user_ruling_72h_notice_repeat_absorbed_critical_still_direct(env, monkeypatch):
    """用户拍板(2026-10-28)钉死: **notice 级同签名隔 72 小时复发也要并入摘要**(不即时),
    critical 同场景仍直发(首报必达不变)。防以后有人按「尺子 24h 窗」改回 24h 口径。
    """
    fixed = _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": (fixed - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_MASS, "subject": SUBJ_MASS}])
    r = notify.send(SUBJ_MASS, "72 小时前的同签名", severe=False, ledger_key=KEY_MASS)
    assert r.get("digested") is True, f"用户拍板: notice 隔 72h 复发应并入摘要: {r}"
    assert env["rec"].mails == [], "并入后不得即时单独外发一封"

    # 对照组: critical 行同场景(台账里有 72h 前同签名 notice 行)仍必须直发
    env["rec"].mails.clear()
    r2 = notify.send(SUBJ_MASS, "critical 同场景", severe=False,
                     ledger_tier="critical", ledger_key=KEY_MASS)
    assert not r2.get("digested"), f"critical 永不吸收(用户拍板口径不变): {r2}"
    assert len(env["rec"].mails) == 1, r2


# ─────────────────────────── C. 跨日窗口边界(第 6/7/8 天) ───────────────────────────
@pytest.mark.parametrize("offset_days,expect_digested", [
    (5, True),   # 第 6 天: 窗内
    (6, True),   # 第 7 天: 窗内(窗口 = 今天 ~ 今天-(N-1), N=7)
    (7, False),  # 第 8 天: 窗外 ⇒ 视为新签名 ⇒ 直发
])
def test_c1_window_boundary(env, monkeypatch, offset_days, expect_digested):
    fixed = _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=offset_days)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    assert (KEY_STALE in adr.ledger_recent_direct_keys(
        env["tmp"], days=7, tiers={"notice", "warning"})) is expect_digested
    r = notify.send(SUBJ_STALE, "边界样本", severe=False, ledger_key=KEY_STALE)
    assert bool(r.get("digested")) is expect_digested, f"offset={offset_days}: {r}"


def test_c2_window_env_3_days_shrinks_behaviorally(env, monkeypatch):
    """窗口 N=3 时: 4 天前的直发行落到窗外 ⇒ 直发; 2 天前仍窗内 ⇒ 并入。"""
    fixed = _freeze(monkeypatch)
    monkeypatch.setenv("ALERT_REPEAT_ABSORB_DAYS", "3")
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r = notify.send(SUBJ_STALE, "4 天前只发过一次", severe=False, ledger_key=KEY_STALE)
    assert not r.get("digested"), r
    env["ledger"].write_text("", encoding="utf-8")
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_MASS, "subject": SUBJ_MASS}])
    r2 = notify.send(SUBJ_MASS, "2 天前发过", severe=False, ledger_key=KEY_MASS)
    assert r2.get("digested") is True, r2


# ─────────────────────────── D. 与 3B 现成件的接口 ───────────────────────────
def test_d1_notify_state_suppressed_for_new_reason_line(env, monkeypatch, capsys):
    """硬约束8(3B 审查踩过的坑): 新判据的「并入摘要」成功行必须被判 suppressed,
    否则 schedule_monitor 兜底路径当「没发出去」⇒ 补列 ⇒ 摘要里同一条出现两次。"""
    from notify_sent import notify_state

    fixed = _freeze(monkeypatch)
    _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                        "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
    r = notify.send(SUBJ_STALE, "重复", severe=False, ledger_key=KEY_STALE)
    assert r.get("digested") is True, r
    out, err = capsys.readouterr()
    assert notify_state(out + err) == "suppressed", (out + err)[:400]


def test_d2_signature_formula_drift_guard():
    """台账签名公式单一事实源守卫: rules 的兜底式必须与 notify._ledger_key_of 逐位一致。"""
    rec = {"subject": "[告警] 某标题 10-28 04:00"}
    assert adr.ledger_row_signature(rec) == notify._ledger_key_of(rec["subject"], None)
    assert adr.ledger_row_signature({"key": "显式键", "subject": "x"}) == "显式键"


def test_d3_upload_r2_passes_ledger_key_at_verify_r2_points():
    """配套: verify-r2 三个告警点统一传 ledger_key(台账键=dedup key, 可读可反查)。"""
    src = (SCRIPTS / "upload_r2.py").read_text(encoding="utf-8")
    assert src.count("ledger_key=_dedup_key") == 2, "两个 verify-r2 主告警点必须传台账键"
    assert "ledger_key=_dk" in src, "对账台账缺失告警点同族同口径"


# ─────────────────────────── E. 冻结行为回归(未被本单改动) ───────────────────────────
def test_e1_severe_same_day_repeat_still_absorbed_frozen(env, monkeypatch):
    """回归: 既有「当日同签名 severe 第 2+ 条并入」(2026-10-10 上线, 用户已验收)保持不动。

    本单新增判据只管**非 critical** 门(test_b1); 本条证明改动没有顺手改坏冻结面(§23.7)。
    """
    _freeze(monkeypatch)
    r1 = notify.send("[告警] 某采集失败", "第一封", severe=True,
                     ledger_key="kelly_freeze_orphan_buy")
    assert not r1.get("digested"), r1
    _freeze(monkeypatch, "2026-10-28 04:20:00")
    r2 = notify.send("[告警] 某采集失败", "第二封", severe=True,
                     ledger_key="kelly_freeze_orphan_buy")
    assert r2.get("digested") is True, f"既有 severe 当日重复并入应保持: {r2}"


# ─────────────────────────── F. 零外发 ───────────────────────────
def test_f1_zero_outbound(env, monkeypatch):
    """整条链路跑一遍(吸收 + 摘要出线)全程零真实外发。"""
    fixed = _freeze(monkeypatch)
    with ZeroOutboundTrap() as trap:
        _seed_ledger(env, [{"ts": (fixed - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
                            "tier": "notice", "key": KEY_STALE, "subject": SUBJ_STALE}])
        notify.send(SUBJ_STALE, "重复", severe=False, ledger_key=KEY_STALE)
        notify.flush_digest(dry_run=False)
        assert trap.hits == [], f"零外发被破坏: {trap.hits}"