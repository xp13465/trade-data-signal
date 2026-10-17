# -*- coding: utf-8 -*-
"""#264 件D(业务订阅流独立渠道)—— 路由显式声明 + 台账 group 口径 自验(2026-10-17)。

权威依据:
  · /tmp/264d-plan-report.md(264D 细化方案)§一 A/B(出口链逐点实文)/§二 F2(双向误路由
    实测:故障落业务群 12 行/6 天)/§三 形态1(业务出口显式传渠道 + 路由守卫测试)/§四(实现
    预期「故障落业务群 12 行/6 天 -> 0」+ 证据用例 E2/E5)。
  · 用户 2026-10-17「按推荐全做」= 264D ①选(a alert 群口径)/②业务群沿用 report/③邮件维持/
    ④加前端分类开关/⑤台账 group 空值随 D 修/⑥登记。

被测面(本文件只读代码文本 + 打桩后直调,不跑任何业务脚本):
  · scripts/notify.py: send_to() 台账 group 记实际落群(原记 feishu_group 原值 => None);
    send() 台账 group 优先级 = ledger_group > feishu_group > 主题文本推断。
  · 业务出口显式渠道(=report): check_signals.py(买卖点全局/订阅) / check_nt_signals.py(汪汪队)
    / detect_intraday_anomaly.py(盘中异动) / gen_daily_brief.py / brief_push.py;
    跟单渠道(=follow): nextday_plan_generator.py / nextday_gap_check.py。
  · 故障出口显式渠道(=alert): r2_upload_skip_notify.sh / signal_kelly_backtest.py
    (冻结表缺失历史信号事件 + 冻结表新增孤儿买事件)。

证据用例:
  E2 误路由回归 —— 未显式声明的无括号主题(如「R2上传异步锁跳过」)兜底落 report(说明修法在
     出口显式声明, 不是改路由函数); 显式声明 alert 后落 alert。
  E5 守卫判别力 —— 故意抹掉任一出口的显式声明 => 静态登记守卫必红。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):
  渠道函数(_send_email/send_telegram/send_feishu)与台账(_record_ledger)全部打桩为只记录
  不真发; 外层再套 ZeroOutboundTrap 包裹最底层 urllib/smtplib 出口, 收尾断言 hits == []。
  打桩生效正控: 每个动态用例断言桩调用计数 > 0; test_00 是陷阱本身的正控(§18 L49)。

跑法: python3 -m pytest -q scripts/tests/test_business_channel_declaration_20261017.py
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
# ── 显式渠道声明登记表(§23.3 举一反三: 全部业务出口 + 全部已知「无故障标记」故障出口) ──
# 每项 = (站点说明, 相对路径, 必须命中的正则);  正则里必须含**显式渠道 token**,
# 命中即「该出口已显式声明渠道」, 未命中即「缺声明」=> 本守卫红。
EGRESS_REGISTRY = [
    ("买卖点信号·全局推送", "scripts/check_signals.py",
     r'notify\.send\(subject, body, from_prefix="\[买卖点信号\]",\s*'
     r'feishu_group="report"'),
    ("买卖点信号·订阅推送", "scripts/check_signals.py",
     r'notify\.send_to\(subject, body, email=email, chat_id=chat_id, dry_run=dry_run,\s*'
     r'from_prefix="\[买卖点信号\]", feishu_group="report"'),
    ("汪汪队信号", "scripts/check_nt_signals.py",
     r'notify\.send\(subject, body, feishu_group="report"'),
    ("盘中异动", "scripts/detect_intraday_anomaly.py",
     r'"--from-prefix", "\[盘中异动\]", "--feishu-group", "report"'),
    ("每日速递·邮件+飞书", "scripts/gen_daily_brief.py",
     r'from_prefix="\[每日速递\]", feishu_group="report"'),
    ("每日速递·飞书直发", "scripts/brief_push.py",
     r'send_feishu\(subject, body, chat_key="report"'),
    ("次日买入计划·跟单渠道", "scripts/nextday_plan_generator.py",
     r'"--dedup-window", "86400",\s*"--feishu-group", "follow"'),
    ("次日伪跳空剔除·跟单渠道", "scripts/nextday_gap_check.py",
     r'"--dedup-window", "86400",\s*"--feishu-group", "follow"'),
    ("R2上传异步锁跳过·故障", "scripts/r2_upload_skip_notify.sh",
     r'--from-prefix "\[提示\]" \\\s*--feishu-group alert'),
    ("冻结表缺失历史信号事件·故障", "scripts/signal_kelly_backtest.py",
     r'"--from-prefix", "\[kelly\]", "--feishu-group", "alert"'),
    ("冻结表新增孤儿买事件·故障", "scripts/signal_kelly_backtest.py",
     r'"--from-prefix", "\[kelly\]", "--feishu-group", "alert",\s*'
     r'"--dedup-key", "kelly_freeze_orphan_buy"'),
    ("订阅台账 group 记实际落群", "scripts/notify.py",
     r'group=feishu_group or _resolve_feishu_chat_key\(subject, from_prefix, False\)'),
    ("send 台账 group 优先级含显式渠道", "scripts/notify.py",
     r'ledger_group or feishu_group'),
]


@pytest.fixture(autouse=True)
def _no_real_outbound():
    """零外发铁律: 全程包裹底层出口, 收尾断言零触达(§18 L48)。"""
    with ZeroOutboundTrap() as trap:
        yield trap
    assert trap.hits == [], "零外发被破坏(§18 L48): %s" % (trap.hits,)


@pytest.fixture
def stub_channels(monkeypatch):
    """渠道 + 台账全打桩为「只记录、返回 True」, 并断言 dry_run=True(防真发)。"""
    hits = {"email": 0, "telegram": 0, "feishu": 0, "ledger": []}

    def fake_email(*_a, **k):
        assert k.get("dry_run") is True, "自测必须 dry_run=True"
        hits["email"] += 1
        return True

    def fake_tg(*_a, **k):
        assert k.get("dry_run") is True, "自测必须 dry_run=True"
        hits["telegram"] += 1
        return True

    def fake_feishu(*_a, **k):
        assert k.get("dry_run") is True, "自测必须 dry_run=True"
        hits["feishu"] += 1
        return True

    def fake_ledger(subject, _channels, **k):
        hits["ledger"].append({"subject": subject, "group": k.get("group"),
                               "tier": k.get("tier")})

    monkeypatch.setattr(notify, "_send_email", fake_email)
    monkeypatch.setattr(notify, "send_telegram", fake_tg)
    monkeypatch.setattr(notify, "send_feishu", fake_feishu)
    monkeypatch.setattr(notify, "_record_ledger", fake_ledger)
    return hits


# ── 0. 沙箱/陷阱正控(§18 L49: 防「因为没跑才没外发」的假绿) ────────────────
def test_00_zero_outbound_trap_is_effective():
    """陷阱必须真能抓住未打桩出口(否则本文件全绿也是假绿)。"""
    with ZeroOutboundTrap() as trap:
        with pytest.raises(AssertionError):
            urllib.request.urlopen("https://example.invalid/")  # noqa: S310
        assert trap.hits, "陷阱未生效(触达未计数)"


# ── 1. 台账 group 口径(⑤ 台账盲点: 原 5 行 group=None) ────────────────────
def test_send_to_ledger_group_resolves_to_report(stub_channels):
    """订阅推送未显式传渠道 => 台账记**实际落群** report(原记 None)。"""
    notify.send_to("[订阅:adam] [买卖点信号] 2026-10-17", "b",
                   email="a@b.c", chat_id="123", dry_run=True,
                   from_prefix="[买卖点信号]")
    assert stub_channels["email"] == 1 and stub_channels["telegram"] == 1
    assert stub_channels["feishu"] == 1, "打桩未生效(渠道函数未被调用)"
    assert stub_channels["ledger"], "台账桩未被调用(打桩未生效)"
    assert stub_channels["ledger"][-1]["group"] == "report"
    assert stub_channels["ledger"][-1]["tier"] == "subscribe"


def test_send_to_ledger_group_explicit_report(stub_channels):
    notify.send_to("[订阅:adam] [买卖点信号] 2026-10-17", "b",
                   email="a@b.c", dry_run=True,
                   from_prefix="[买卖点信号]", feishu_group="report")
    assert stub_channels["ledger"][-1]["group"] == "report"


def test_send_ledger_group_follows_explicit_channel(stub_channels):
    """直调 send() + 显式 feishu_group=alert => 台账记 alert(原被主题文本推断成 report)。"""
    notify.send("R2上传异步锁跳过 10-17 17:25", "b", dry_run=True, feishu_group="alert",
                ledger_key="r2_upload_async_skip")
    assert stub_channels["ledger"], "台账桩未被调用"
    assert stub_channels["ledger"][-1]["group"] == "alert"


def test_send_unmarked_subject_still_falls_back_to_report(stub_channels):
    """E2 对照: 未显式声明时路由兜底行为**不变**(证明修法在出口显式声明, 不靠改路由)。"""
    notify.send("R2上传异步锁跳过 10-17 17:25", "b", dry_run=True)
    assert stub_channels["ledger"][-1]["group"] == "report"


# ── 2. 静态登记守卫(§23.3 举一反三 + E5 判别力) ───────────────────────────
def _missing_declarations(texts):
    miss = []
    for label, rel, pat in EGRESS_REGISTRY:
        if not re.search(pat, texts.get(rel, "")):
            miss.append("%s (%s)" % (label, rel))
    return miss


def _load_texts():
    return {rel: (ROOT / rel).read_text(encoding="utf-8")
            for _, rel, _ in EGRESS_REGISTRY}


def test_all_egress_sites_declare_channel_explicitly():
    miss = _missing_declarations(_load_texts())
    assert not miss, "以下出口缺显式渠道声明(#264D 形态1 守卫):\n  " + "\n  ".join(miss)


def test_guard_has_discriminating_power():
    """E5: 把任一出口的显式声明抹掉 => 守卫必须报红(不是恒绿的空壳)。"""
    texts = _load_texts()
    assert not _missing_declarations(texts), "基线应为全声明"

    label, rel, _pat = EGRESS_REGISTRY[8]  # R2上传异步锁跳过·故障
    mutated = dict(texts)
    mutated[rel] = mutated[rel].replace("--feishu-group alert", "")
    miss = _missing_declarations(mutated)
    assert any(label in m for m in miss), "判据未检出缺声明(假绿): %s" % (miss,)

    label2, rel2, _p2 = EGRESS_REGISTRY[9]  # 冻结表缺失·故障
    mutated2 = dict(texts)
    mutated2[rel2] = mutated2[rel2].replace('"--feishu-group", "alert"', "")
    miss2 = _missing_declarations(mutated2)
    assert any(label2 in m for m in miss2), "判据未检出缺声明(假绿): %s" % (miss2,)


def test_no_business_egress_lands_in_alert_group():
    """反向断言: 业务出口不得显式落 alert 群(故障/业务分渠道的方向性检查)。"""
    texts = _load_texts()
    for rel in ("scripts/check_signals.py", "scripts/check_nt_signals.py",
                "scripts/detect_intraday_anomaly.py", "scripts/gen_daily_brief.py",
                "scripts/brief_push.py"):
        assert 'feishu_group="alert"' not in texts[rel], "%s 业务出口误落 alert 群" % rel