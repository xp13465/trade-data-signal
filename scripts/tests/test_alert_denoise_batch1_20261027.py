# -*- coding: utf-8 -*-
"""告警降噪批次1（2026-10-27）用例：★1 邮件分流 + ★3 verify-r2 域映射。

依据（逐条对应实施规格 `docs/ops/alert-denoise-spec-20261027.md`）：
  ★1 用户 2026-10-27 拍板：**邮件只发告警和真故障**；业务报告（报告群/跟单群/完成通知）
     只走飞书对应群。唯一白名单 = `[状态说明]`（#309 F2 防假绿兜底，路由在 report 群
     但属真故障通道，必须保留邮件）。
     E1-1：alert 群发邮件；report 群不发；follow/agent_done 不发；`[状态说明]` 即使
          不在 alert 群仍发。
  ★3 verify-r2 两个 subject 哈希 key 补域映射到 r2_deploy（2h 静默窗聚合，首报仍直发）。
     E3-1：两个真实 subject 命中 r2_deploy。
     E3-2：反例不被抢（历史行改写返回 None；`[数据缺口]` 走显式类别 data_gap）。

全程打桩（§18 L48 铁律）：notify 的 `_send_email` / `send_telegram` / `send_feishu`
全部替换成计数替身，且 `send(dry_run=True)` 本身不写台账/latest.md/去重状态
⇒ 零真实外发、零落盘。断言只数「有没有调」，绝不碰网络。
"""
import inspect

import pytest

import alert_denoise_rules as adr
import daily_summary_email as dse
import notify


# ── 打桩工具 ────────────────────────────────────────────────────────────────
class _Chan:
    """渠道替身：记录每次调用，返回固定成功标志（不碰网络/配置）。"""

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
    """三渠道全部打桩（顺序：email / telegram / feishu）。"""
    email, tg, fs = _Chan(), _Chan(), _Chan()
    monkeypatch.setattr(notify, "_send_email", email)
    monkeypatch.setattr(notify, "send_telegram", tg)
    monkeypatch.setattr(notify, "send_feishu", fs)
    return {"email": email, "telegram": tg, "feishu": fs}


def _send(subject, **kwargs):
    """跑生产 `send()` 真实判定路径（dry_run=True ⇒ 不落盘不真发）。"""
    return notify.send(subject, "正文", dry_run=True, **kwargs)


# ── ★1 E1-1：四个群的邮件收发 ───────────────────────────────────────────────
def test_star1_alert_group_sends_email(chans):
    """告警群（severe）⇒ 发邮件，也发飞书（不得只发一路）。"""
    res = _send("[告警] 云上 unit 巡检发现异常(1 项)", severe=True, from_prefix="[告警]")
    assert chans["email"].n == 1, "告警群必须发邮件"
    assert chans["feishu"].n == 1, "告警群飞书通道不得丢"
    assert res["email"] is True and res["feishu"] is True


def test_star1_alert_group_by_subject_tag(chans):
    """非 severe 但主题含 [监控] ⇒ 路由 alert 群 ⇒ 发邮件（词根匹配，不只 [告警]）。"""
    _send("[监控] 三站一致性检查通过", from_prefix=None)
    assert chans["email"].n == 1


def test_star1_recovery_still_sends_email(chans):
    """[恢复] 与 [告警] 成对，同走 alert 群 ⇒ 邮件保留（闭环可见性）。"""
    _send("[恢复] baostock 封禁已解除", from_prefix="[恢复]")
    assert chans["email"].n == 1


def test_star1_report_group_no_email(chans):
    """report 群（业务播报）⇒ 不发邮件，但飞书报告群照发（可见性不丢）。"""
    res = _send("[盘中异动] 1项异动", from_prefix=None)
    assert chans["email"].n == 0, "业务播报不得再进管理员邮箱"
    assert chans["feishu"].n == 1, "业务播报必须仍进飞书报告群"
    assert res["email"] is False and res["feishu"] is True


def test_star1_follow_group_no_email(chans):
    """follow 群（跟单）⇒ 不发邮件。"""
    _send("明日买入计划", feishu_group="follow")
    assert chans["email"].n == 0
    assert chans["feishu"].n == 1


def test_star1_agent_done_no_email(chans):
    """agent_done 群（[完成]）⇒ 不发邮件。"""
    _send("[完成] update_all 12min", from_prefix="[完成]")
    assert chans["email"].n == 0
    assert chans["feishu"].n == 1


def test_star1_status_note_whitelisted(chans):
    """白名单：`[状态说明]` 路由在 report 群，但属真故障通道 ⇒ 必须发邮件。"""
    res = _send("[状态说明] 监控结论异常(本轮无告警邮件)", from_prefix="[状态说明]")
    assert chans["email"].n == 1, "[状态说明] 是防假绿兜底，邮件不得被降噪吞掉"
    assert chans["feishu"].n == 1
    assert res["email"] is True


def test_star1_status_note_whitelist_ignores_leading_space(chans):
    """白名单用 lstrip 比对（subject 前置空格不破坏白名单）。"""
    _send("  [状态说明] 监控结论异常", from_prefix="[状态说明]")
    assert chans["email"].n == 1


def test_star1_feishu_only_still_skips_email(chans):
    """feishu_only=True 旧语义不变（调试开关，跳过邮件/Telegram）。"""
    _send("[告警] X", severe=True, feishu_only=True)
    assert chans["email"].n == 0
    assert chans["telegram"].n == 0
    assert chans["feishu"].n == 1


def test_star1_report_group_email_false_other_channels_unchanged(chans):
    """report 群 ⇒ 只有 email 被收敛为 False；Telegram/飞书通道本次不动（行为保持）。

    这也是 check_failed_units 判 `status=sent` 的输入语义：送达 = **任一真实渠道发出**，
    不是「email 发出」，故只剩飞书也不影响 sent 判定（E1-2 回归见
    test_280/test_196 既有用例）。
    """
    res = _send("[买卖点信号] 主买卖", from_prefix=None)
    assert res["email"] is False
    assert res["feishu"] is True
    assert res["telegram"] is True, "Telegram 不在本次范围内，行为不得改变"


# ── ★1 每日速递改走飞书报告群 ───────────────────────────────────────────────
def test_star1_daily_summary_helper_routes_to_report_chat(monkeypatch):
    """情绪速递/补充速递 ⇒ notify.send_feishu(chat_key="report")，不碰 SMTP。"""
    calls = []

    def _fake_send_feishu(subject, body, chat_key=None, **kwargs):
        calls.append({"subject": subject, "body": body, "chat_key": chat_key})
        return True

    monkeypatch.setattr(notify, "send_feishu", _fake_send_feishu)

    def _boom(*_a, **_k):  # pragma: no cover - 被调用即失败
        raise AssertionError("每日速递不得再走 smtplib 直发邮件")

    monkeypatch.setattr(dse, "send_email", _boom)

    ok = dse.send_report_to_feishu("[情绪速递] 2026-10-27", "正文")
    assert ok is True
    assert len(calls) == 1
    assert calls[0]["chat_key"] == "report"
    assert calls[0]["subject"] == "[情绪速递] 2026-10-27"


def test_star1_daily_summary_helper_swallows_failure(monkeypatch):
    """飞书发送抛异常 ⇒ 返回 False 不抛（不阻塞 update_all 主流程）。"""
    def _boom(*_a, **_k):
        raise RuntimeError("feishu down")

    monkeypatch.setattr(notify, "send_feishu", _boom)
    assert dse.send_report_to_feishu("[情绪速递] x", "正文") is False


@pytest.mark.parametrize("fn_name", ["_run_main", "_run_supplement"])
def test_star1_daily_summary_runners_do_not_call_send_email(fn_name):
    """源码形状守卫：两个入口都不再直发邮件（防后人回退）。"""
    src = inspect.getsource(getattr(dse, fn_name))
    assert "send_email(" not in src, f"{fn_name} 不应再调用 send_email（邮件只发告警）"
    assert "send_report_to_feishu(" in src


# ── ★3 E3-1：两个真实 subject 命中 r2_deploy ────────────────────────────────
R2_SPLIT_SUBJECT = "[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)"
R2_COVER_SUBJECT = "[告警] R2 可能被异源覆盖(verify-r2 大量不一致)"


@pytest.mark.parametrize("key,subject", [
    ("499ec8489d1f", R2_SPLIT_SUBJECT),
    ("621d8489dea6", R2_COVER_SUBJECT),
])
def test_star3_verify_r2_subjects_map_to_r2_deploy(key, subject):
    assert adr.domain_of(key, subject) == "r2_deploy"


def test_star3_bare_r2_space_not_pulled_in():
    """反例：不得用裸 `"R2 "` 关键词（会把无关主题一起吸进 r2_deploy）。"""
    assert adr.domain_of("x", "[告警] R2 容量水位偏高(非上传链路)") is None


# ── ★3 E3-2：反例不被抢 ────────────────────────────────────────────────────
def test_star3_history_overwrite_not_pulled_in():
    """历史行改写（index_daily）不属于 R2 域 ⇒ None（不被新关键词误吸）。"""
    assert adr.domain_of("x", "[告警] 历史行改写 index_daily 历史行被重写 1 条") is None


def test_star3_data_gap_explicit_category_wins():
    """显式类别优先：[数据缺口] 仍归 data_gap，不被 r2 关键词抢。"""
    assert adr.domain_of("x", "[数据缺口] index_daily 缺失") == "data_gap"


def test_star3_existing_r2_keywords_unchanged():
    """既有 R2/部署链路关键词行为不变（回归）。"""
    assert adr.domain_of("x", "[告警] R2 上传失败") == "r2_deploy"
    assert adr.domain_of("x", "[告警] 双树一致性校验失败") == "r2_deploy"