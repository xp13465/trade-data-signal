# -*- coding: utf-8 -*-
"""#264b 摘要时序缺陷修复(选项②) —— last_sent_day 水位线语义自验(2026-10-17)。

权威依据 = /tmp/anchor-264b-report.md §一/§四/§五.2:
  · 病灶:`_flush_digest_locked` 把 `last_sent_day` 写成「发送时刻的日期」⇒ 次日 00:00 的
    stale 兜底 flush 抢先把**新一日**标记为已发 ⇒ 当日 23:25 flush 被 `!= today` 永久挡住
    (10-13~10-16 摘要连续滑到次日 00:00)。
  · 修法(选项②):`last_sent_day` 改记「**已发条目所属最大 day**」(水位线),门控比较改 `<`
    (已发水位未达今日才发)。
  · ★5a(2026-10-28 批次2)口径变更:00:00 **不再补发** stale,前日遗留并入当晚 23:25 后的
    摘要(subject 自带「含前日遗留 N 条」)⇒ 本文件用例统一按新口径断言(00:00 no-op、
    当晚 23:30 发)。

被测面:`scripts/notify.py:flush_digest` / `_flush_digest_locked`(门控 + state 写入)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):本文件全部用例
  **本次自测未产生任何真实外发** —— 渠道函数在 fixture 内整体打桩为「只记录、返回 True」,
  外层再套 `ZeroOutboundTrap`;收尾断言 `trap.hits == []`。所有落盘面全指向 tmp_path。
  本文件**不执行恢复主体/flush 之外的生产动作**,只调 `notify.flush_digest`(沙箱内)。

已知残余(报告 §残,本次有意不修,属选项②范围外):
  若 00:00 的 stale flush 里的 buffer **同时**含"前日遗留 + 当日(新一日)早期条目",则水位
  会被推到当日至当天 ⇒ 当日 23:25 被挡。此形态仅在"前日真有未发遗留"时出现(修好后正常路径
  不再产生 stale);且条目零丢失(会在次日以 stale 补发)。见 /tmp/pack2-p1-report.md。
  ★5a(2026-10-28) 起:00:00 根本不 flush(门控要求 HM 到点)⇒ 上述残余形态结构性消失。

跑法: python3 -m pytest -q scripts/tests/test_264b_digest_watermark_20261017.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402

# 断言计数下限(防收集/执行异常致「0 断言假绿」,§18 L49)
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════════ 隔离 fixture(零外发 + 全 tmp) ══════════════════════════
@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPO", str(tmp_path))
    for _v in ("NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE", "ALERT_DIGEST_DISABLE"):
        monkeypatch.delenv(_v, raising=False)
    monkeypatch.setattr(notify, "REPO", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERTS_FILE", alerts / "latest.md")
    monkeypatch.setattr(notify, "WARNING_BUFFER_FILE", alerts / "warning_buffer.jsonl")
    monkeypatch.setattr(notify, "INFO_LOG_FILE", alerts / "info_log.jsonl")
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", alerts / "warning_dedup_state.json")
    monkeypatch.setattr(notify, "WARNING_DEDUP_LOCK_FILE", alerts / "warning_dedup.lock")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", alerts / "warning_buffer.flushlock")
    monkeypatch.setattr(notify, "DEDUP_FILE", alerts / "notify_dedup.json")
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", alerts / "alert_digest.jsonl")
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", alerts / "alert_digest.flushlock")
    monkeypatch.setattr(notify, "ALERT_DIGEST_STATE_FILE", alerts / "alert_digest_state.json")
    _leak = [n for n in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                         "WARNING_FLUSH_LOCK_FILE", "WARNING_DEDUP_STATE_FILE",
                         "WARNING_DEDUP_LOCK_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                         "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE")
             if tmp_path not in Path(getattr(notify, n)).parents]
    assert not _leak, f"隔离缝破损: 落盘面泄漏到真实树 {_leak}"

    calls: list = []

    def _fake(kind):
        def _f(*a, **k):
            calls.append((kind, a, k))
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "calls": calls, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


# ══════════════════════════════ helpers ══════════════════════════════
def _entry(day: str, key="r2_x", cat="r2") -> dict:
    return {"ts": f"{day} 10:00:00", "rid": f"d-{day}-{key}", "day": day, "key": key,
            "category": cat, "subject": "主题", "body": "正文",
            "from_prefix": "[告警]", "source": "t.sh", "reason": "over_budget"}


def _seed(alerts_dir: Path, entries: list[dict]) -> None:
    with open(alerts_dir / "alert_digest.jsonl", "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _digest_lines(alerts_dir: Path) -> list[str]:
    p = alerts_dir / "alert_digest.jsonl"
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _state(alerts_dir: Path) -> dict:
    return json.loads((alerts_dir / "alert_digest_state.json").read_text(encoding="utf-8"))


def _patch_now(monkeypatch, dtv: datetime) -> None:
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return dtv
    monkeypatch.setattr(notify, "datetime", _DT)


def _stub_send(monkeypatch):
    """把 notify.send 打桩为「记录 + 报成功」, 不进真渠道。"""
    calls: list = []

    def _f(*a, **k):
        calls.append((a, k))
        return {"email": True, "telegram": False, "feishu": True}
    monkeypatch.setattr(notify, "send", _f)
    return calls


# 固定的跨零点场景(日期无关性: 全部由常量日期派生, 不取真实 now)
D0 = datetime(2026, 10, 13, 23, 30, 0)   # 第 1 天 23:30
DAY0 = D0.strftime("%Y-%m-%d")
DAY1 = (D0 + timedelta(days=1)).strftime("%Y-%m-%d")
DAY2 = (D0 + timedelta(days=2)).strftime("%Y-%m-%d")


# ══════════ ① 核心回归: 00:00 stale 兜底 flush 不再"抢记新一日" ══════════
def test_01_stale_flush_midnight_does_not_block_next_day_2325(_iso, monkeypatch):
    """★5a(2026-10-28)口径: 次日 00:00 **不再补发** stale(前日遗留并入当晚 23:30)。

    原 #264b 病灶(00:00 stale flush 抢占「新一日」水位 ⇒ 当晚 23:25 被永久挡住)在新口径下
    结构性消失。本用例继续守两件事:
      ① 00:00 不发、不写 state、不清 buffer(不抢水位);
      ② 当晚 23:25 前日遗留 + 新条目一起发, 水位 = 已发条目最大 day。"""
    alerts = _iso["alerts"]
    # 第1天 23:30 条目(未发, 留 buffer)
    _seed(alerts, [_entry(DAY0, "r2_d1")])
    # 次日 00:00 → 新口径: 不补发(旧口径此处补发并抢写水位)
    _patch_now(monkeypatch, datetime.strptime(DAY1 + " 00:00:30", "%Y-%m-%d %H:%M:%S"))
    calls = _stub_send(monkeypatch)
    r1 = notify.flush_digest()
    _chk(r1["sent"] is False and r1["n"] == 0, f"次日 00:00 应不补发, 得 {r1}")
    _chk(calls == [], "00:00 不得发送")
    _chk(len(_digest_lines(alerts)) == 1, "00:00 不得清 buffer")
    _chk(not (alerts / "alert_digest_state.json").exists(),
         "00:00 不得写 state(否则可能挡住当晚)")
    # 次日晚 23:25: 前日遗留 + 新一日条目 → 一起发
    _seed(alerts, [_entry(DAY0, "r2_d1"), _entry(DAY1, "r2_d2")])
    _patch_now(monkeypatch, datetime.strptime(DAY1 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    r2 = notify.flush_digest()
    _chk(r2["sent"] is True and r2["n"] == 2,
         f"次日晚 23:25 应发前日遗留+新条目, 得 {r2}")
    _chk("含前日遗留" in calls[0][0][0], f"subject 应标前日遗留: {calls[0][0][0]}")
    _chk(_digest_lines(alerts) == [], "已发条目应清空")
    _chk(len(calls) == 1, f"应恰 1 次 send, 得 {len(calls)}")
    _chk(_state(alerts).get("last_sent_day") == DAY1, "水位线应推进到次日")


def test_01b_old_semantics_would_have_blocked(_iso, monkeypatch):
    """负控: 直接构造「旧语义写出的 state(次日)」, 断言新门控会放行 —— 证判别力。"""
    alerts = _iso["alerts"]
    # 旧语义残留 state: 次日已标已发, 但当日条目还在
    (alerts / "alert_digest_state.json").write_text(
        json.dumps({"last_sent_day": DAY1}), encoding="utf-8")
    _seed(alerts, [_entry(DAY1, "r2_x")])
    _patch_now(monkeypatch, datetime.strptime(DAY1 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    calls = _stub_send(monkeypatch)
    r = notify.flush_digest()
    # 新语义 state(DAY1) 不 < DAY1 ⇒ 仍挡(这是同日幂等, 正确); 换 DAY2 场景才放行
    _chk(r["sent"] is False, f"水位=今日(同日)应幂等挡住, 得 {r}")
    # 真正判别: 水位 < 今日 ⇒ 放行
    (alerts / "alert_digest_state.json").write_text(
        json.dumps({"last_sent_day": DAY0}), encoding="utf-8")
    _seed(alerts, [_entry(DAY1, "r2_x")])
    r2 = notify.flush_digest()
    _chk(r2["sent"] is True, f"水位(第1天)< 今日 ⇒ 应发, 得 {r2}")
    _chk(len(calls) == 1, "只应第 2 次发")


# ══════════ ② 当日幂等: 23:25 发出后当日不重发 ══════════
def test_02_same_day_single_send(_iso, monkeypatch):
    alerts = _iso["alerts"]
    _patch_now(monkeypatch, datetime.strptime(DAY0 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    _seed(alerts, [_entry(DAY0, "r2_a"), _entry(DAY0, "deploy_b", "deploy")])
    calls = _stub_send(monkeypatch)
    r = notify.flush_digest()
    _chk(r["sent"] is True and r["n"] == 2, f"23:25 后应发, 得 {r}")
    _chk(_state(alerts).get("last_sent_day") == DAY0, "水位应=当日")
    # 同日再入条目 → 不重发
    _seed(alerts, [_entry(DAY0, "r2_c")])
    r2 = notify.flush_digest()
    _chk(r2["sent"] is False, f"同日二次不应重发, 得 {r2}")
    _chk(len(calls) == 1, "不应再 send")
    _chk(len(_digest_lines(alerts)) == 1, "未发条目应原样保留")


# ══════════ ③ 23:25 前 no-op(回归保护) ══════════
def test_03_before_2325_noop(_iso, monkeypatch):
    alerts = _iso["alerts"]
    _patch_now(monkeypatch, datetime.strptime(DAY0 + " 12:00:00", "%Y-%m-%d %H:%M:%S"))
    _seed(alerts, [_entry(DAY0, "r2_x")])
    calls = _stub_send(monkeypatch)
    r = notify.flush_digest()
    _chk(r["sent"] is False and r["n"] == 0, f"23:25 前应 no-op, 得 {r}")
    _chk(calls == [], "不应发送")
    _chk(len(_digest_lines(alerts)) == 1, "条目应保留")


# ══════════ ④ 纯 stale 发送 → 水位 = 最大 stale day ══════════
def test_04_pure_stale_watermark(_iso, monkeypatch):
    """纯 stale(无当日条目)在水位门控下仍会发 —— ★5a 后只在**当晚 23:25 后**发。"""
    alerts = _iso["alerts"]
    d_prev2 = (D0 - timedelta(days=2)).strftime("%Y-%m-%d")
    _seed(alerts, [_entry(d_prev2, "a"), _entry(DAY0, "b")])
    _patch_now(monkeypatch, datetime.strptime(DAY1 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    calls = _stub_send(monkeypatch)
    r = notify.flush_digest()
    _chk(r["sent"] is True, f"隔日 stale 应在当晚 23:25 后发, 得 {r}")
    _chk("含前日遗留" in calls[0][0][0], f"subject 应标前日遗留: {calls[0][0][0]}")
    _chk(_state(alerts).get("last_sent_day") == DAY0,
         f"水位=最大已发条目 day(第1天), 得 {_state(alerts)}")


# ══════════ ⑤ 当日窗口内含 stale → 水位 = 当日 ══════════
def test_05_window_flush_with_stale_watermark_is_today(_iso, monkeypatch):
    alerts = _iso["alerts"]
    _seed(alerts, [_entry(DAY0, "old"), _entry(DAY1, "new")])
    _patch_now(monkeypatch, datetime.strptime(DAY1 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    calls = _stub_send(monkeypatch)
    r = notify.flush_digest()
    _chk(r["sent"] is True and r["n"] == 2, f"当日窗口应发全部, 得 {r}")
    _chk(_state(alerts).get("last_sent_day") == DAY1, "水位应=当日")


# ══════════ ⑥ 多日连续: 水位单调推进, 每天各发一次 ══════════
def test_06_multi_day_progression(_iso, monkeypatch):
    alerts = _iso["alerts"]
    days = [DAY0, DAY1, DAY2]
    sent_days = []
    calls = _stub_send(monkeypatch)
    for i, d in enumerate(days):
        _seed(alerts, [_entry(d, f"r2_{i}")])
        _patch_now(monkeypatch, datetime.strptime(d + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
        r = notify.flush_digest()
        _chk(r["sent"] is True, f"{d} 23:25 应发, 得 {r}")
        sent_days.append(_state(alerts).get("last_sent_day"))
    _chk(sent_days == days, f"水位应逐日推进 {days}, 得 {sent_days}")
    _chk(len(calls) == 3, f"应 3 次 send, 得 {len(calls)}")


# ══════════ ⑦ 空 buffer → no-op(含 state 不写) ══════════
def test_07_empty_buffer_noop(_iso, monkeypatch):
    alerts = _iso["alerts"]
    _patch_now(monkeypatch, datetime.strptime(DAY0 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    calls = _stub_send(monkeypatch)
    r = notify.flush_digest()
    _chk(r["sent"] is False, f"空 buffer 应 no-op, 得 {r}")
    _chk(not (alerts / "alert_digest_state.json").exists(), "不应写 state")
    _chk(calls == [], "不应 send")


# ══════════ ⑧ send 失败 → 不写 state(回归) ══════════
def test_08_send_fail_keeps_no_state(_iso, monkeypatch):
    alerts = _iso["alerts"]
    _patch_now(monkeypatch, datetime.strptime(DAY0 + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    _seed(alerts, [_entry(DAY0, "r2_x")])
    monkeypatch.setattr(notify, "send",
                        lambda *a, **k: {"email": False, "telegram": False, "feishu": False})
    r = notify.flush_digest()
    _chk(r["sent"] is False and r["n_remaining"] == 1, f"发送失败条目应保留, 得 {r}")
    _chk(len(_digest_lines(alerts)) == 1, "失败后条目不得清理")
    _chk(not (alerts / "alert_digest_state.json").exists(),
         "失败后不得写 state(否则当日永不重试)")


# ══════════ ⑨ 断言下限(防 0 断言假绿) ══════════
def test_09z_assertion_floor():
    _chk(_N[0] >= 25, f"断言数应 >=25, 实得 {_N[0]}")