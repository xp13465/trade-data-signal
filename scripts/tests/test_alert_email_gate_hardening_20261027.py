# -*- coding: utf-8 -*-
"""告警邮件门控加固（2026-10-27 批次1 审查加固 H1~H4）。

依据：批次1「邮件只发告警群」合入后审查挑出的 4 项加固（任务书
`/tmp/task-alert-hardening-20261027.md`，规格见
`docs/ops/alert-denoise-spec-20261027.md`）。

  H1 staticdata 备份仓库缺失是真故障，旧 subject `[通知]` 会被路由到 report 群
     ⇒ 批次1 之后不再发邮件。改为 `[告警]` 主题前缀（主题即路由单一事实源）。
  H2 门控 `or severe` 兜底：调用方显式 `feishu_group="report"` 但 `severe=True`
     ⇒ 仍发邮件（严重度压过显式群名，防显式指错群把真故障一起吞掉）。
  H3 逃生门 `EMAIL_GROUP_GATE_DISABLE=1/true` ⇒ 门控失效、恢复全群发邮件；
     `0`/未设置/其他值 ⇒ 门控照常。
  H4 情绪速递/补充速递发送失败 ⇒ `_run_main`/`_run_supplement` 返回非 0，
     让 update_all.sh 既有「情绪速递邮件失败」告警路径生效（不新增第二条通道）。

全程打桩（§18 L48 铁律）：notify 的三条真实渠道（`_send_email` / `send_telegram` /
`send_feishu`）全部替换成计数替身，且一律 `dry_run=True`（`send()` 内部 dry-run
不写台账/latest.md/去重态）⇒ 零真实外发、零落盘。断言只数「调没调」，绝不碰网络。

时敏防护（L51 铁律）：所有用例的日期都是显式传入的字面量或被 monkeypatch 的
桩返回值，被测路径不取 `date.today()` ⇒ 隔天跑仍绿。
"""
import inspect
import re
from pathlib import Path

import pytest

import daily_summary_email as dse
import notify

SCRIPTS = Path(__file__).resolve().parents[1]
DATE = "20261027"  # 固定字面量（不取 today，防跨天红）


# ── 打桩工具 ────────────────────────────────────────────────────────────────
class _Chan:
    """渠道替身：记录每次调用，返回固定成功标志（不碰网络/配置/落盘）。"""

    def __init__(self, ok: bool = True):
        self.calls = []
        self.ok = ok

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.ok

    @property
    def n(self) -> int:
        return len(self.calls)


@pytest.fixture()
def chans(monkeypatch):
    """三渠道全部打桩（email / telegram / feishu）。"""
    email, tg, fs = _Chan(), _Chan(), _Chan()
    monkeypatch.setattr(notify, "_send_email", email)
    monkeypatch.setattr(notify, "send_telegram", tg)
    monkeypatch.setattr(notify, "send_feishu", fs)
    return {"email": email, "telegram": tg, "feishu": fs}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个用例都从「逃生门未设置」起步，且 WARNING 只打一次的进程态归零。"""
    monkeypatch.delenv("EMAIL_GROUP_GATE_DISABLE", raising=False)
    monkeypatch.setattr(notify, "_EMAIL_GATE_DISABLE_WARNED", False)


def _send(subject, **kwargs):
    """跑生产 `send()` 真实判定路径（dry_run=True ⇒ 不落盘不真发）。"""
    return notify.send(subject, "正文", dry_run=True, **kwargs)


# ── H1：真故障补 alert 群 ───────────────────────────────────────────────────
H1_SUBJECT = "[告警] staticdata 仓库不存在, 跳过备份"


def test_h1_subject_resolves_to_alert_group():
    """该 subject 自己就 resolve 成 alert（主题=路由单一事实源，不靠隐形 flag）。"""
    assert notify._resolve_feishu_chat_key(H1_SUBJECT, "[告警]", False) == "alert"


def test_h1_real_fault_sends_email(chans):
    """真故障（非 severe，但主题 [告警]）⇒ 必须发邮件，且飞书进 alert 群。"""
    res = _send(H1_SUBJECT, from_prefix="[告警]",
                ledger_key="staticdata_backup_repo_missing", dedup_window=21600)
    assert chans["email"].n == 1, "备份缺口是真故障，批次1 后不得掉邮件"
    assert res["email"] is True
    assert chans["feishu"].n == 1
    assert chans["feishu"].calls[0][1].get("chat_key") is None, "走自动路由(主题推断)"
    # Telegram 通道本次不动（本来就每条都尝试；不是「因为改 [告警] 才升级」）
    assert res["telegram"] is True


def test_h1_old_notification_subject_would_drop_email(chans):
    """反例留证：旧 `[通知]` 主题在批次1 门控下不发邮件（这就是 H1 要修的病）。"""
    _send("[通知] staticdata 仓库不存在, 跳过备份", from_prefix="[通知]")
    assert chans["email"].n == 0


def test_h1_shell_call_site_guard():
    """源码形状守卫：脚本里那条 notify 调用已改成 [告警] 主题（防后人回退成 [通知]）。"""
    src = (SCRIPTS / "staticdata_backup_async.sh").read_text(encoding="utf-8")
    assert H1_SUBJECT in src
    assert "[通知] staticdata 仓库不存在, 跳过备份" not in src
    # 该调用的去重键仍在（不许顺手换键语义）
    assert "--dedup-key staticdata_backup_repo_missing --dedup-window 21600" in src


# ── H2：门控加 severe 兜底 ──────────────────────────────────────────────────
def test_h2_explicit_report_group_but_severe_still_emails(chans):
    """显式 feishu_group="report" + severe=True ⇒ 仍发邮件（H2 的核心）。"""
    res = _send("[盘中异动] 1项异动", feishu_group="report", severe=True)
    assert chans["email"].n == 1, "severe 是最高优先判据，显式群名压不过它"
    assert res["email"] is True
    # 落群仍是调用方显式指定的 report（只救邮件，不改路由）
    assert chans["feishu"].calls[0][1].get("chat_key") == "report"


def test_h2_non_severe_report_group_still_no_email(chans):
    """回归：非 severe 的 report 群仍不发邮件（兜底不得放宽成「全发」）。"""
    _send("[盘中异动] 1项异动", feishu_group="report")
    assert chans["email"].n == 0


def test_h2_severe_gate_does_not_override_feishu_only(chans):
    """feishu_only 是调试开关，优先级不变：severe 也不因 H2 而发邮件。"""
    _send("[告警] X", severe=True, feishu_only=True)
    assert chans["email"].n == 0
    assert chans["telegram"].n == 0


# ── H3：逃生门 EMAIL_GROUP_GATE_DISABLE ─────────────────────────────────────
@pytest.mark.parametrize("value", ["1", "true", "TRUE", " true "])
def test_h3_gate_disabled_restores_email_for_report_group(monkeypatch, chans, value):
    """`1`/`true`（含大小写/空白变体）⇒ 门控失效，report 群也发邮件。"""
    monkeypatch.setenv("EMAIL_GROUP_GATE_DISABLE", value)
    _send("[盘中异动] 1项异动", from_prefix=None)
    assert chans["email"].n == 1


@pytest.mark.parametrize("value", ["0", "", "false", "yes", "no"])
def test_h3_gate_keeps_working_for_other_values(monkeypatch, chans, value):
    """`0`/空/false/其他值 ⇒ 门控照常（report 群不发邮件）。"""
    monkeypatch.setenv("EMAIL_GROUP_GATE_DISABLE", value)
    _send("[盘中异动] 1项异动", from_prefix=None)
    assert chans["email"].n == 0


def test_h3_unset_keeps_gate(monkeypatch, chans):
    """未设置 ⇒ 门控照常。"""
    monkeypatch.delenv("EMAIL_GROUP_GATE_DISABLE", raising=False)
    _send("[盘中异动] 1项异动", from_prefix=None)
    assert chans["email"].n == 0


def test_h3_warns_once_per_process(monkeypatch, chans, capsys):
    """禁用时打一行 WARNING 说明已禁用，且只打一次（不随每条消息刷屏）。"""
    monkeypatch.setenv("EMAIL_GROUP_GATE_DISABLE", "1")
    for _ in range(3):
        _send("[盘中异动] 1项异动")
    err = capsys.readouterr().err
    assert "EMAIL_GROUP_GATE_DISABLE" in err
    assert err.count("[notify][WARNING]") == 1
    assert "门控已禁用" in err


def test_h3_warns_even_if_first_message_is_alert_group(monkeypatch, chans, capsys):
    """告警群消息也要触发那行 WARNING（逃生门先求值，不被 or 短路跳过）。"""
    monkeypatch.setenv("EMAIL_GROUP_GATE_DISABLE", "true")
    _send("[告警] X", severe=True)
    err = capsys.readouterr().err
    assert err.count("[notify][WARNING]") == 1


def test_h3_disabled_still_respects_feishu_only(monkeypatch, chans):
    """逃生门只关「按群分流」这一层，不动 feishu_only 调试语义。"""
    monkeypatch.setenv("EMAIL_GROUP_GATE_DISABLE", "1")
    _send("[盘中异动] 1项异动", feishu_only=True)
    assert chans["email"].n == 0
    assert chans["feishu"].n == 1


def test_h3_disabled_profile_alert_unchanged(monkeypatch, chans):
    """逃生门开启时告警群行为与平时一致（回归：逃生门不是「改语义」）。"""
    monkeypatch.setenv("EMAIL_GROUP_GATE_DISABLE", "1")
    res = _send("[告警] 云上 unit 巡检发现异常", severe=True, from_prefix="[告警]")
    assert res["email"] is True and res["feishu"] is True


# ── H4：速递发送失败要响 ────────────────────────────────────────────────────
@pytest.fixture()
def _stub_main_builders(monkeypatch):
    """把 main 模式的数据读取/正文构建全打桩（不读真实 summary_history.json）。"""
    monkeypatch.setattr(dse, "load_summary_item", lambda date: {"date": date})
    monkeypatch.setattr(dse, "build_subject", lambda it: f"[情绪速递] {it['date']}")
    monkeypatch.setattr(dse, "load_subscriptions", lambda: [])
    monkeypatch.setattr(dse, "build_text", lambda it, subs, extras: "纯文本")
    monkeypatch.setattr(dse, "build_html", lambda it, subs, extras: "<p>HTML</p>")


@pytest.fixture()
def _stub_supplement_builders(monkeypatch):
    """把 supplement 模式的交易日闸门/数据段/正文构建全打桩。"""
    monkeypatch.setattr(dse, "_is_trading_day", lambda: True)
    monkeypatch.setattr(dse, "load_futures_brief", lambda: {"k": "v"})
    monkeypatch.setattr(dse, "load_nt_brief", lambda: None)
    monkeypatch.setattr(dse, "load_public_fund_brief", lambda: None)
    monkeypatch.setattr(dse, "build_supplement_subject", lambda d: f"[补充速递] {d}")
    monkeypatch.setattr(dse, "build_supplement_text", lambda d, e: "纯文本")
    monkeypatch.setattr(dse, "build_supplement_html", lambda d, e: "<p>HTML</p>")


def test_h4_run_main_success_returns_zero(monkeypatch, _stub_main_builders):
    """发送成功 ⇒ 0（保持原契约，update_all 的 then 分支）。"""
    monkeypatch.setattr(dse, "send_report_to_feishu", lambda s, b: True)
    assert dse._run_main(DATE, dry_run=False) == 0


def test_h4_run_main_failure_returns_nonzero(monkeypatch, _stub_main_builders):
    """发送失败 ⇒ 非 0（交给 update_all 既有失败告警，不再恒 0 静默）。"""
    monkeypatch.setattr(dse, "send_report_to_feishu", lambda s, b: False)
    assert dse._run_main(DATE, dry_run=False) != 0


def test_h4_run_supplement_success_returns_zero(monkeypatch, _stub_supplement_builders):
    monkeypatch.setattr(dse, "send_report_to_feishu", lambda s, b: True)
    assert dse._run_supplement(DATE, dry_run=False) == 0


def test_h4_run_supplement_failure_returns_nonzero(monkeypatch, _stub_supplement_builders):
    monkeypatch.setattr(dse, "send_report_to_feishu", lambda s, b: False)
    assert dse._run_supplement(DATE, dry_run=False) != 0


def test_h4_dry_run_still_returns_zero(monkeypatch, _stub_main_builders):
    """dry-run 只打印不发送 ⇒ 仍 0（不得把自验/预览变成失败）。"""
    def _boom(*_a, **_k):  # pragma: no cover - 被调用即失败
        raise AssertionError("dry-run 不得真发")
    monkeypatch.setattr(dse, "send_report_to_feishu", _boom)
    assert dse._run_main(DATE, dry_run=True) == 0


def test_h4_main_propagates_exit_code(monkeypatch):
    """main() 原样透出 runner 的退出码（`sys.exit(main())` ⇒ 进程非 0）。"""
    monkeypatch.setattr(dse, "_run_main", lambda date, dry_run: 3)
    monkeypatch.setattr(dse, "_run_supplement", lambda date, dry_run: 4)
    assert dse.main([DATE, "--mode", "main"]) == 3
    assert dse.main([DATE, "--mode", "supplement"]) == 4


def test_h4_update_all_failure_branch_still_wired():
    """上层告警路径守卫：update_all.sh 的 main 调用仍是 if/else，失败分支发 [告警]。

    H4 复用这条既有通道（不新增第二条）：只有它还在，非 0 才真的有人喊。
    """
    src = (SCRIPTS / "update_all.sh").read_text(encoding="utf-8")
    m = re.search(
        r'if "\$PY" "\$REPO/scripts/daily_summary_email\.py" --mode main[^\n]*; then\n'
        r'(?P<ok>.*?)\nelse\n(?P<fail>.*?)\nfi',
        src, re.S)
    assert m, "update_all.sh 里 daily_summary_email --mode main 的 if/else 结构变了"
    assert "情绪速递邮件失败" in m.group("fail")
    assert "情绪速递邮件失败" not in m.group("ok")


def test_h4_runners_keep_single_channel_contract():
    """源码形状守卫：仍在调 send_report_to_feishu，且返回值参与退出码（防回退成恒 0）。"""
    for fn in (dse._run_main, dse._run_supplement):
        src = inspect.getsource(fn)
        assert "send_report_to_feishu(" in src
        assert "return 1" in src, f"{fn.__name__} 失败分支必须返回非 0"