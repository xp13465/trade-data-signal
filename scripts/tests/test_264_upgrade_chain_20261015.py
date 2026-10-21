#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#264 包1「升级链」—— pytest 自验(件 A 升级档独立抑制窗 + 件 B 判据事件化, 2026-10-15)。

依据: docs/ops/alert-noise-rca-20261015.md §1.3/§1.4/§2.2④/§4.1(A+B)/§4.2。

覆盖(全程零真实外发, §18 L48 / memory notify-script-selftest-must-stub):
  件 A(升级档独立抑制窗)
    A-① 升级档窗口内已发 → 抑制(不再因调用方 --dedup-window 0 而恒放行)
    A-② 真故障反例: 窗口外/首报 仍必发 critical(降噪不吞真故障判别维度)
    A-③ 首报通道不受牵连: 首日仍走普通 severe 路径、首报窗仍=0(「集合有变立即报」不变)
    A-④ 直接取证: 升级档 check_dedup 收到的是**该通道自己的**窗口值, 不是调用方的 0/首报窗
         (failed-unit=72h 独立窗; patrol_drift=原 6h, 收口 2026-10-16 边界差集①)
  件 B(判据事件化: 「连续天数」→ 有界滚动窗「近 N 天出现天数」)
    B-① 计数有界(≤ 窗口天数), 不再单调无界(实测原 consecutive_days=8 仍在涨)
    B-② 稀疏出现(间隔断链)不误升, 但真持续仍升 critical
    B-③ 迁移: 旧状态(只存 consecutive_days)不丢历史连续性, 升级档不误降级
    B-④ R7 回归: rolling_window_days=None → 旧语义逐位不变(R7 链路零影响)
    B-⑤ R7 通道经 notify 真跑: 仍用调用方窗口(21600), 未被件 A 的独立升级窗波及
  件 C(收口 2026-10-16 防御性输入校验)
    C-① consecutive_days 非数值 → 容错按缺省, 不抛 ValueError(含 r4 同类面)
    C-② seen_dates 非列表/垃圾内容 → 形状过滤, 不虚增计数误判 critical
  零外发: ZeroOutboundTrap 包裹全链真跑, 断言零真实出口触达

跑法: /tmp/ci-venv/bin/python -m pytest -q scripts/tests/test_264_upgrade_chain_20261015.py
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest  # noqa: F401  (显式依赖声明)

import alert_denoise_rules as adr  # noqa: E402
import notify  # noqa: E402
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

# 冻结运行日(§18 L51): 被测代码内部取 now()/today(), 用例必须**注入冻结运行日**, 不写死
# 「今天」再让代码取真实 now —— 否则引入当天绿、次日红。冻结 20:00 避开自然日边界。
FROZEN_NOW = datetime(2026, 10, 15, 20, 0, 0)
TODAY = FROZEN_NOW.strftime("%Y-%m-%d")
YESTERDAY = (FROZEN_NOW - timedelta(days=1)).strftime("%Y-%m-%d")
DAY2 = (FROZEN_NOW - timedelta(days=2)).strftime("%Y-%m-%d")


class _FrozenDatetime(datetime):
    """冻结 notify 模块内的 datetime.now()(只 monkeypatch notify 属性, 不动标准库全局)。"""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003
        return FROZEN_NOW


class _DedupSpy:
    """check_dedup 打桩: 记录 (key, window) 调用 + 复刻真实现语义(窗口 <=0 恒放行)。

    这个语义复刻是**判别力关键**(§18 L49): 若实现退回「升级档复用调用方的 0 窗」,
    spy 会返回 False → 用例真红, 而不是被假样本养绿。
    """

    def __init__(self, alerted=()):
        self.alerted = set(alerted)
        self.calls = []

    def __call__(self, key, window):
        self.calls.append((key, window))
        return bool(window and window > 0 and key in self.alerted)

    def windows_for(self, key):
        return [w for k, w in self.calls if k == key]


@pytest.fixture
def stubbed_notify(tmp_path, monkeypatch):
    """打桩 notify 全部发送/落盘出口 + 冻结运行日; 返回 (sent[], spy, tmp_path)。"""
    sent = []
    spy = _DedupSpy()
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setattr(notify, "datetime", _FrozenDatetime)
    monkeypatch.setattr(notify, "send_tiered",
                        lambda subject, body, **kw: (sent.append(("tiered", subject)),
                                                     {"email": True, "feishu": True,
                                                      "telegram": False})[1])
    monkeypatch.setattr(notify, "send",
                        lambda subject, body, **kw: (sent.append(("send", subject)),
                                                     {"email": True, "feishu": True,
                                                      "telegram": False})[1])
    monkeypatch.setattr(notify, "check_dedup", spy)
    monkeypatch.setattr(notify, "update_dedup", lambda *a, **k: None)
    monkeypatch.setattr(notify, "write_alert", lambda *a, **k: None)
    return sent, spy, tmp_path


def _seed_state(tmp_path, name, obj):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / name).write_text(json.dumps(obj), encoding="utf-8")


def _escalate_state(last, days, first=None):
    return {"last_fail_date": last, "consecutive_days": days,
            "first_fail_date": first or last, "last_grade_time": ""}


# ══════════════════════════════════════════════════════════════════
# 件 A: 升级档独立抑制窗(病灶 = 复用调用方首报窗 0 ⇒ 恒放行 ⇒ 永不抑制)
# ══════════════════════════════════════════════════════════════════
def test_a1_escalated_window_suppresses_when_already_sent(stubbed_notify):
    """A-① 升级档独立窗内已发 → 不重复升级; 落回普通路径按调用方窗判重(2026-10-21 修)。

    旧实现: 此处直接 return 0(位于普通首报路径之前) ⇒ 72h 内新增 failed unit 的首报被吞
    (云上 10-19 11:00 后 7 天零告警)。新语义: 升级窗只抑制「同一对象的重复升级」;
    调用方 window=0(集合有变立即报)⇒ 普通首报必须照发, 只是不再发第二次升级 critical。
    """
    sent, spy, tmp_path = stubbed_notify
    assert adr.ESCALATED_DEDUP_WINDOW_SECONDS == 259200, \
        "failed-unit 升级档窗 = 72h(件A 实测锚定值, 独立锚点)"
    spy.alerted.add(adr.FAILED_UNITS_ESCALATED_DEDUP_KEY)  # 模拟独立窗内已发过升级档
    _seed_state(tmp_path, "failed_units_patrol_state.json",
                _escalate_state(YESTERDAY, 2))
    rc = notify.main(["failed 主题", "failed 正文", "--severe",
                      "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                      "--dedup-window", "0"])   # ← 调用方真实形态: 首报窗=0(集合有变立即报)
    assert rc == 0
    assert not [s for k, s in sent if k == "tiered"], f"升级档窗口内不得重复升级, 实际={sent}"
    assert [s for k, s in sent if k == "send"], "首报被升级窗吞 = 黑洞回退(2026-10-21 回归)"
    assert spy.windows_for(adr.FAILED_UNITS_ESCALATED_DEDUP_KEY) == [
        adr.ESCALATED_DEDUP_WINDOW_SECONDS], "升级档必须用独立窗常量, 不得复用调用方窗口"


def test_a2_escalated_window_expired_still_sends(stubbed_notify, capsys):
    """A-② 真故障反例: 窗口外(或首报)升级档仍必发 critical —— 降噪不吞真故障。"""
    sent, _spy, tmp_path = stubbed_notify
    _seed_state(tmp_path, "failed_units_patrol_state.json", _escalate_state(YESTERDAY, 2))
    rc = notify.main(["failed 主题", "failed 正文", "--severe",
                      "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY, "--dedup-window", "0"])
    assert rc == 0
    tiered = [s for k, s in sent if k == "tiered"]
    assert tiered, "升级档窗口外必须真发(不吞真故障)"
    assert "升级 critical" in tiered[0] and "近 7 天出现 3 天" in tiered[0]
    assert "升级档路由完成" in capsys.readouterr().err


def test_a3_first_report_channel_not_affected(stubbed_notify):
    """A-③ 首报通道零影响: 首日仍走普通 severe 路径, 首报窗仍=0(「集合有变立即报」不变)。"""
    sent, spy, tmp_path = stubbed_notify
    _seed_state(tmp_path, "failed_units_patrol_state.json", _escalate_state(TODAY, 1))
    rc = notify.main(["首报主题", "首报正文", "--severe",
                      "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY, "--dedup-window", "0"])
    assert rc == 0
    assert [s for k, s in sent if k == "send"], "首报必须走普通 severe 路径(不被升级窗牵连)"
    assert not [s for k, s in sent if k == "tiered"]
    assert spy.windows_for(adr.FAILED_UNITS_DEDUP_KEY) == [0], "首报窗必须仍为调用方传入的 0"


def test_a4_patrol_drift_channel_keeps_own_window(stubbed_notify):
    """A-④ 收口(2026-10-16): patrol_drift 升级档用**自己的窗** —— 原 6h(21600), 不并入 72h。

    该通道不在 RCA 病灶范围且现网零升级流量(审查边界差集①)。
    判别力: 断言钉**字面量 21600**(独立锚点 = cloud_unit_patrol.sh:153 的 --dedup-window),
    不用常量比常量 —— 否则「把常量的值改回 72h」这种改坏不会红(自证式断言)。
    """
    sent, spy, tmp_path = stubbed_notify
    assert adr.PATROL_DRIFT_ESCALATED_DEDUP_WINDOW_SECONDS == 21600, \
        "patrol_drift 升级档窗常量必须仍是 6h(独立锚点: cloud_unit_patrol.sh:153)"
    spy.alerted.add(adr.PATROL_DRIFT_ESCALATED_DEDUP_KEY)
    # 升级档发出时会同步占首报 key(notify 原逻辑), 故普通通道也在 6h 窗内 ⇒ 本次零外发。
    spy.alerted.add(adr.PATROL_DRIFT_DEDUP_KEY)
    _seed_state(tmp_path, "cloud_unit_patrol_drift_state.json", _escalate_state(YESTERDAY, 2))
    rc = notify.main(["漂移主题", "漂移正文", "--severe",
                      "--dedup-key", adr.PATROL_DRIFT_DEDUP_KEY, "--dedup-window", "21600"])
    assert rc == 0
    assert not sent, "patrol 漂移升级档窗口内已发 → 必须抑制(两条通道都应在窗内)"
    assert spy.windows_for(adr.PATROL_DRIFT_ESCALATED_DEDUP_KEY) == [21600], \
        "patrol_drift 升级档必须真收到 6h(21600), 不得被 72h 统一档吞并"


# ══════════════════════════════════════════════════════════════════
# 件 B: 判据事件化(有界滚动窗)
# ══════════════════════════════════════════════════════════════════
def test_b1_rolling_count_is_bounded(tmp_path):
    """B-① 计数有界: 旧状态 20 天历史 → 计数 = 窗口天数(7), 不再单调无界。"""
    p = tmp_path / "data" / "failed_units_patrol_state.json"
    seen = [(FROZEN_NOW - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(20)]
    _seed_state(tmp_path, "failed_units_patrol_state.json",
                {"last_fail_date": TODAY, "consecutive_days": 20,
                 "first_fail_date": seen[-1], "seen_dates": seen})
    tier, days, first = adr.consecutive_days_escalate(
        p, FROZEN_NOW, adr.FAILED_UNITS_ESCALATE_DAYS,
        rolling_window_days=adr.ESCALATE_ROLLING_WINDOW_DAYS)
    assert (tier, days) == ("critical", adr.ESCALATE_ROLLING_WINDOW_DAYS)
    assert first == (FROZEN_NOW - timedelta(days=adr.ESCALATE_ROLLING_WINDOW_DAYS - 1)
                     ).strftime("%Y-%m-%d"), "first 应取窗口内最早一天"
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert on_disk["consecutive_days"] == adr.ESCALATE_ROLLING_WINDOW_DAYS  # 落盘同样有界
    assert len(on_disk["seen_dates"]) == adr.ESCALATE_ROLLING_WINDOW_DAYS  # 窗口外旧日滑出


def test_b2_rolling_sparse_keeps_severe(tmp_path):
    """B-② 稀疏出现(窗口内仅 2 天, 含断链) → 不误升 critical(真持续才升)。"""
    p = tmp_path / "data" / "failed_units_patrol_state.json"
    _seed_state(tmp_path, "failed_units_patrol_state.json",
                {"last_fail_date": TODAY, "consecutive_days": 9,
                 "first_fail_date": DAY2,
                 "seen_dates": [TODAY, DAY2, (FROZEN_NOW - timedelta(days=20)).strftime("%Y-%m-%d")]})
    tier, days, _first = adr.consecutive_days_escalate(
        p, FROZEN_NOW, adr.FAILED_UNITS_ESCALATE_DAYS,
        rolling_window_days=adr.ESCALATE_ROLLING_WINDOW_DAYS)
    assert (tier, days) == ("severe", 2), "窗口外旧日不计入; 计数从旧「连续 9 天」降为窗口真实 2 天"


def test_b3_migration_from_legacy_state(tmp_path):
    """B-③ 迁移: 旧状态无 seen_dates → 用 consecutive_days 反推补齐, 升级档不误降级。"""
    p = tmp_path / "data" / "failed_units_patrol_state.json"
    _seed_state(tmp_path, "failed_units_patrol_state.json", _escalate_state(YESTERDAY, 2, DAY2))
    tier, days, first = adr.consecutive_days_escalate(
        p, FROZEN_NOW, adr.FAILED_UNITS_ESCALATE_DAYS,
        rolling_window_days=adr.ESCALATE_ROLLING_WINDOW_DAYS)
    assert (tier, days, first) == ("critical", 3, DAY2), "迁移必须保住历史连续性(否则误降级)"
    assert len(json.loads(p.read_text(encoding="utf-8"))["seen_dates"]) == 3


def test_b4_legacy_semantics_unchanged_when_rolling_none(tmp_path):
    """B-④ R7 回归: rolling_window_days=None → 旧「连续天数」语义逐位不变, 状态无新字段。"""
    p = tmp_path / "data" / "r2_consistency_fail_state.json"
    _seed_state(tmp_path, "r2_consistency_fail_state.json", _escalate_state(YESTERDAY, 1))
    tier, days, _first = adr.consecutive_days_escalate(p, FROZEN_NOW, 2)
    assert (tier, days) == ("critical", 2), "旧语义: 昨日 1 天 + 今日 = 连续 2 天"
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert "seen_dates" not in on_disk, "未启用 rolling 时不得新增字段(旧状态格式逐位不变)"


def test_b5_r7_notify_channel_keeps_caller_window(stubbed_notify):
    """B-⑤ R7 经 notify 真跑: 仍走调用方窗口 21600(未被件 A 的独立升级窗波及), 语义不漂移。"""
    sent, spy, tmp_path = stubbed_notify
    _seed_state(tmp_path, "r2_consistency_fail_state.json", _escalate_state(YESTERDAY, 1))
    rc = notify.main(["§22 主题", "§22 正文", "--severe",
                      "--dedup-key", adr.R2_CONSISTENCY_DEDUP_KEY, "--dedup-window", "21600"])
    assert rc == 0
    tiered = [s for k, s in sent if k == "tiered"]
    assert tiered and "连续 2 天" in tiered[0], "R7 措辞/阈值不变(件 B 只作用 #196 通道)"
    assert spy.windows_for(adr.R2_CONSISTENCY_ESCALATED_DEDUP_KEY) == [21600], \
        "R7 升级档仍用调用方窗口(件 A 不改 R7)"


# ══════════════════════════════════════════════════════════════════
# 件 C(收口 2026-10-16): 防御性输入校验(损坏状态文件不崩 / 不误判)
# ══════════════════════════════════════════════════════════════════
def test_c1_non_numeric_consecutive_days_does_not_crash(tmp_path):
    """C-① consecutive_days 非数值(损坏状态) → 容错按缺省, 不抛 ValueError。

    判别力: 旧实现 `int(_state.get("consecutive_days") or 0)` 对 'abc' 抛 ValueError →
    整个分级链崩(该通道当次零告警)。同类面: r4_staticdata_grade 同款崩点, 一并断言。
    """
    _seed_state(tmp_path, "failed_units_patrol_state.json",
                {"last_fail_date": YESTERDAY, "consecutive_days": "abc"})
    tier, days, first = adr.consecutive_days_escalate(
        tmp_path / "data" / "failed_units_patrol_state.json", FROZEN_NOW,
        adr.FAILED_UNITS_ESCALATE_DAYS,
        rolling_window_days=adr.ESCALATE_ROLLING_WINDOW_DAYS)
    assert (tier, days, first) == ("severe", 2, YESTERDAY), \
        "非数值应容错退化(缺省 1 天 + 迁移补齐昨日) → severe, 不崩不误升"

    # 同类面: r4_staticdata_grade 的同款 `int(_state.get("consecutive_days"))` 崩点
    _seed_state(tmp_path, "r4_grade_state.json",
                {"last_fail_date": YESTERDAY, "consecutive_days": "oops"})
    tier4, reason4 = adr.r4_staticdata_grade(
        None, tmp_path / "data" / "r4_grade_state.json", FROZEN_NOW)
    assert tier4 == "info", f"同类面(r4 分级)非数值同样不得崩: {reason4}"


@pytest.mark.parametrize("garbage", [
    ["abc", "xyz", "foo", "bar", "baz"],   # 垃圾串 list
    "abcdefghij",                          # 非 list(字符串 → 会被逐字符迭代)
    12345,                                 # 非 list(数字 → 迭代会 TypeError)
])
def test_c2_garbage_seen_dates_not_falsely_critical(tmp_path, garbage):
    """C-② seen_dates 非列表/垃圾内容 → 形状过滤, 不虚增窗口计数误判 critical。

    判别力: 旧实现下垃圾串字符序 > '2026-…' ⇒ 全被保留 ⇒ 计数 6 ≥ 3 ⇒ **误判 critical**;
    非 list 情形还会 TypeError 崩。过滤后回落 severe。
    """
    _seed_state(tmp_path, "failed_units_patrol_state.json",
                {"last_fail_date": TODAY, "consecutive_days": 1, "seen_dates": garbage})
    tier, days, _first = adr.consecutive_days_escalate(
        tmp_path / "data" / "failed_units_patrol_state.json", FROZEN_NOW,
        adr.FAILED_UNITS_ESCALATE_DAYS,
        rolling_window_days=adr.ESCALATE_ROLLING_WINDOW_DAYS)
    assert (tier, days) == ("severe", 1), \
        f"垃圾 seen_dates({garbage!r}) 必须被形状过滤 → severe, 不得误判 critical"


# ══════════════════════════════════════════════════════════════════
# 零真实外发声明(§18 L48)
# ══════════════════════════════════════════════════════════════════
def test_zero_real_outbound_full_chain(stubbed_notify):
    """零外发: 打桩 + 真实出口陷阱双保险, 升级链全跑后真实出口触达数 == 0。"""
    sent, _spy, tmp_path = stubbed_notify
    _seed_state(tmp_path, "failed_units_patrol_state.json", _escalate_state(YESTERDAY, 2))
    with ZeroOutboundTrap() as trap:
        notify.main(["x", "y", "--severe", "--dedup-key", adr.FAILED_UNITS_DEDUP_KEY,
                     "--dedup-window", "0"])
    assert trap.hits == [], f"零外发被破坏: {trap.hits}"
    assert sent, "打桩生效(发送被拦截到内存, 未触真实出口)"