# -*- coding: utf-8 -*-
"""#245 批2 L2 预算+摘要层 —— 正/负控自验(2026-10-10)。

权威规格 = docs/ops/245-batch2-impl-spec-20261010.md §1(1.1~1.9)。被测面:
  · `scripts/alert_denoise_rules.py`: category_of / category_of_line / ALERT_BUDGET /
    ledger_day_direct_counts / alert_budget_process(§1.2/§1.3/§1.6)。
  · `scripts/notify.py`: send() 单点 gate(§1.4)+ digest buffer/flush_digest(§1.5)+
    --flush-digest / --defer-digest CLI + digested 早退。
  · `scripts/notify_sent.py`: W2 契约登记(§1.8)。
  · `scripts/schedule_monitor.sh`: 批次行级吸收/恢复闭环 D5/摘要 flush 接线(§1.6/§1.7)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):本文件全部用例
  **本次自测未产生任何真实外发** —— 渠道函数(send_feishu / _send_email / send_telegram)
  在 fixture 内整体打桩为「只记录、返回 True」的假函数, 外层再套 `ZeroOutboundTrap`
  包裹最底层 urllib/smtplib 出口; 收尾断言 `trap.hits == []` 即「全程零真实外发」。
  所有落盘面(台账/buffer/state/dedup)全指向 tmp_path, 绝不碰生产 data/alerts/。

第三实现漂移防护(memory repro-script-second-implementation-drift):§1.6/§1.7 的
  monitor 侧判定不重写副本, 而是从 `schedule_monitor.sh` 内嵌 python heredoc **ast 提取
  真源码块**后 exec(与 test_240/test_232 同法); `SCHEDULE_MONITOR_SH` 环境变量可覆盖。

跑法: python3 -m pytest -q scripts/tests/test_245_l2_budget_digest_20261010.py
"""
from __future__ import annotations

import ast
import json
import os
import sys
import textwrap
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402
from notify_sent import notify_state, notify_sent  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
MONITOR = Path(os.environ.get("SCHEDULE_MONITOR_SH", str(SCRIPTS / "schedule_monitor.sh")))

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#193/#240)
_MIN_ASSERTIONS = 60
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
    for _v in ("NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE", "ALERT_DIGEST_DISABLE",
               "ALERT_BUDGET_TASK_FAMILY"):
        monkeypatch.delenv(_v, raising=False)
    monkeypatch.setattr(notify, "REPO", tmp_path)
    monkeypatch.setattr(notify, "ALERTS_DIR", alerts)
    monkeypatch.setattr(notify, "ALERTS_FILE", alerts / "latest.md")
    monkeypatch.setattr(notify, "WARNING_BUFFER_FILE", alerts / "warning_buffer.jsonl")
    monkeypatch.setattr(notify, "INFO_LOG_FILE", alerts / "info_log.jsonl")
    monkeypatch.setattr(notify, "WARNING_DEDUP_STATE_FILE", alerts / "warning_dedup_state.json")
    monkeypatch.setattr(notify, "DEDUP_FILE", alerts / "notify_dedup.json")
    monkeypatch.setattr(notify, "ALERT_DIGEST_FILE", alerts / "alert_digest.jsonl")
    monkeypatch.setattr(notify, "ALERT_DIGEST_LOCK_FILE", alerts / "alert_digest.flushlock")
    monkeypatch.setattr(notify, "ALERT_DIGEST_STATE_FILE", alerts / "alert_digest_state.json")

    calls: list[str] = []

    def _fake(kind):
        def _f(*_a, **_k):
            calls.append(kind)
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "calls": calls, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ledger_row(key: str, subject: str = "", *, day=None, group="alert",
                tier="critical") -> dict:
    return {"ts": f"{day or _today()} 09:00:00", "group": group, "tier": tier,
            "key": key, "subject": subject or key}


def _seed_ledger(alerts_dir: Path, rows: list[dict]) -> None:
    p = alerts_dir / "alert_ledger.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _digest_lines(alerts_dir: Path) -> list[str]:
    p = alerts_dir / "alert_digest.jsonl"
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _patch_now(monkeypatch, dtv: datetime) -> None:
    """把 notify.datetime 换成固定 now() 的替身(flush 门控用)。"""
    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return dtv
    monkeypatch.setattr(notify, "datetime", _DT)


# ══════════════════════════════ ① 类别映射表驱动 ══════════════════════════════
CAT_CASES = [
    # (key, subject, 期望类别)  —— 10-08 直发样本族 + 豁免族
    ("cloud_unit_patrol_drift", None, "unit"),
    ("failed_units_patrol", None, "unit"),
    ("r2_unreachable", None, "r2"),
    ("r2_overview_lag", None, "r2"),
    ("r2_intraday_lag", None, "r2"),
    ("deploy_fail", None, "deploy"),
    ("deploy_verify_fail", None, "deploy"),
    ("fund_nav_stale", None, "fund_nav"),
    ("kelly_snapshot_fail", None, "kelly"),
    ("kelly_intraday_rerun", None, "kelly"),
    ("nextday_gap_check_fail", None, "gap_check"),
    (None, "[数据缺口] 公募全 NULL", "data_gap"),
    (None, "次日买入计划伪跳空校验失败", "gap_check"),
    # 豁免(未映射 → None, 永远直发)
    ("staticdata_backup_fail", None, None),
    ("board_etf_map_stale", None, None),
    ("s06_snapshot_fail", None, None),
    ("gold_night_fail", None, None),
]

LINE_CASES = [
    ("SEVERE: r2_unreachable R2 不可达", "r2"),
    ("SEVERE: [数据缺口] 公募全 NULL", "data_gap"),
    ("SEVERE: nextday_gap_check 伪跳空校验失败", "gap_check"),
    ("SEVERE: cloud_unit_patrol_drift 云上 unit 漂移", "unit"),
    ("SEVERE: failed_units_patrol failed unit 合集", "unit"),
    ("SEVERE: deploy_verify_fail 部署校验失败", "deploy"),
    ("SEVERE: unrelated_task 内存超限告急", None),
]


def test_01_category_of_table():
    for k, s, exp in CAT_CASES:
        got = adr.category_of(k, s)
        _chk(got == exp, f"category_of({k!r},{s!r}) 应={exp}, 得 {got}")
    _chk(adr.ALERT_BUDGET == {"unit": 1, "r2": 1, "data_gap": 1, "gap_check": 1,
                              "deploy": 1, "fund_nav": 1, "kelly": 1},
         f"ALERT_BUDGET 初值应为 7 类各 1, 得 {adr.ALERT_BUDGET}")


def test_01b_category_of_line_table():
    for line, exp in LINE_CASES:
        got = adr.category_of_line(line)
        _chk(got == exp, f"category_of_line({line!r}) 应={exp}, 得 {got}")


# ══════════════════════════════ ② send() 单点 gate ══════════════════════════════
def test_02_gate_second_over_budget_is_digested(_iso):
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "R2 不可达")])
    res = notify.send("[告警] R2 又一次不可达", "body", severe=True,
                      ledger_key="r2_overbudget", feishu_group="alert")
    _chk(res.get("digested") is True, f"超预算第 2 条应 digested, 得 {res}")
    _chk(_iso["calls"] == [], f"digested 不得触达任何渠道, 得 {_iso['calls']}")
    _chk(len(_digest_lines(_iso["alerts"])) == 1,
         f"buffer 应恰 1 行, 得 {len(_digest_lines(_iso['alerts']))}")


def test_02b_gate_first_is_direct(_iso):
    res = notify.send("[告警] R2 不可达", "body", severe=True,
                      ledger_key="r2_first", feishu_group="alert")
    _chk(not res.get("digested"), f"首条应直发, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "首条应触达渠道")
    _chk(_digest_lines(_iso["alerts"]) == [], "首条不应入 buffer")


def test_02c_gate_unmapped_always_direct(_iso):
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    res = notify.send("[告警] staticdata 备份失败", "body", severe=True,
                      ledger_key="staticdata_backup_fail", feishu_group="alert")
    _chk(not res.get("digested"), f"未映射类别永远直发, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "未映射应触达渠道")
    _chk(_digest_lines(_iso["alerts"]) == [], "未映射不应入 buffer")


def test_02d_gate_non_severe_exempt(_iso):
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    res = notify.send("普通通知", "body", severe=False, ledger_key="r2_ns")
    _chk(not res.get("digested"), f"severe=False 不应进 gate, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "severe=False 应直发")


def test_02e_gate_dry_run_direct(_iso):
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    res = notify.send("[告警] R2 x", "body", severe=True, dry_run=True, ledger_key="r2_dry")
    _chk(not res.get("digested"), f"dry_run 不应进 gate(只读), 得 {res}")
    _chk(_digest_lines(_iso["alerts"]) == [], "dry_run 不应入 buffer")


def test_02f_gate_missing_ledger_failopen(_iso):
    # 无台账文件 → 计数 0 → 直发(fail-open, 绝不因台账问题吞告警)
    res = notify.send("[告警] R2 无台账也直发", "body", severe=True,
                      ledger_key="r2_noledger")
    _chk(not res.get("digested"), f"台账缺失应 fail-open 直发, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "台账缺失应触达渠道")


def test_02g_gate_disable_switch(_iso, monkeypatch):
    monkeypatch.setenv("ALERT_BUDGET_DISABLE", "1")
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    res = notify.send("[告警] R2 回滚开关", "body", severe=True, ledger_key="r2_dis")
    _chk(not res.get("digested"), f"ALERT_BUDGET_DISABLE=1 应全停 gate, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "回滚开关下应直发")


def test_02h_gate_critical_tier_exempt(_iso):
    """N3: send_tiered(critical) 走 budget_exempt=True ⇒ 超预算也直发, 绝不入摘要。"""
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    res = notify.send_tiered("[告警] R2 升级档", "body", tier=notify.TIER_CRITICAL,
                             ledger_key="r2_tier_crit", feishu_group="alert")
    _chk(not res.get("digested"), f"critical 升级档应直发, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "critical 升级档应触达渠道")
    _chk(_digest_lines(_iso["alerts"]) == [], "critical 升级档不得入 buffer")


def test_02i_gate_absorb_fail_failopen(_iso, monkeypatch):
    """N4: buffer 吸收失败(_absorb_to_digest 返回 False) ⇒ fail-open 落直发, 绝不吞告警。"""
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    monkeypatch.setattr(notify, "_absorb_to_digest", lambda *a, **k: False)
    res = notify.send("[告警] R2 吸收失败", "body", severe=True, ledger_key="r2_absfail",
                      feishu_group="alert")
    _chk(not res.get("digested"), f"吸收失败应 fail-open 直发, 得 {res}")
    _chk(len(_iso["calls"]) >= 1, "吸收失败应触达渠道")


def test_02j_gate_bad_ledger_line_tolerated(_iso):
    """N5: 台账含坏行(非法 JSON) ⇒ 计数跳过坏行不崩, 好行仍计入(此处 1 条 → 第 2 条 digested)。"""
    p = _iso["alerts"] / "alert_ledger.jsonl"
    p.write_text(
        '{"ts": "%s 09:00:00", "group": "alert", "tier": "critical", "key": "r2_unreachable"}\n'
        'NOT-JSON-GARBAGE{{{\n' % _today(), encoding="utf-8")
    res = notify.send("[告警] R2 坏行也不吞", "body", severe=True, ledger_key="r2_badline",
                      feishu_group="alert")
    _chk(res.get("digested") is True, f"好行计入 1 ⇒ 第 2 条应 digested, 得 {res}")


# ══════════════════════════════ ③ _absorb_to_digest 幂等 ══════════════════════════════
def test_03_absorb_idempotent_same_key(_iso):
    ok1 = notify._absorb_to_digest("主题", "正文", key="r2_x", category="r2")
    ok2 = notify._absorb_to_digest("主题", "正文", key="r2_x", category="r2")
    _chk(ok1 and ok2, "两次吸收都应返回 True(第二次幂等命中)")
    lines = _digest_lines(_iso["alerts"])
    _chk(len(lines) == 1, f"同日同 key 应只 1 行, 得 {len(lines)}")
    rec = json.loads(lines[0])
    _chk(rec["key"] == "r2_x" and rec["category"] == "r2" and rec["reason"] == "over_budget",
         f"条目字段应齐, 得 {rec}")


def test_03b_absorb_different_key_two_lines(_iso):
    notify._absorb_to_digest("a", "b", key="k1", category="r2")
    notify._absorb_to_digest("a", "b", key="k2", category="r2")
    _chk(len(_digest_lines(_iso["alerts"])) == 2, "不同 key 应各 1 行")


# ══════════════════════════════ ④ flush_digest 门控 ══════════════════════════════
def _seed_digest(alerts_dir: Path, entries: list[dict]) -> None:
    p = alerts_dir / "alert_digest.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _entry(day: str, key="r2_x", cat="r2") -> dict:
    return {"ts": f"{day} 10:00:00", "rid": f"d-{day}-{key}", "day": day, "key": key,
            "category": cat, "subject": "主题", "body": "正文",
            "from_prefix": "[告警]", "source": "t.sh", "reason": "over_budget"}


def test_04_flush_before_2325_noop(_iso, monkeypatch):
    _patch_now(monkeypatch, datetime(2026, 10, 10, 12, 0, 0))
    _seed_digest(_iso["alerts"], [_entry(_today())])
    calls = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: (calls.append((a, k)),
                                                         {"email": True, "telegram": False,
                                                          "feishu": True})[1])
    r = notify.flush_digest()
    _chk(r["sent"] is False and r["n"] == 0, f"23:25 前应 no-op, 得 {r}")
    _chk(calls == [], "23:25 前不应发送")
    _chk(len(_digest_lines(_iso["alerts"])) == 1, "条目应原样保留")


def test_04b_flush_after_2325_sends_once(_iso, monkeypatch):
    today = _today()
    _patch_now(monkeypatch, datetime.strptime(today + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    _seed_digest(_iso["alerts"], [_entry(today, "r2_a"), _entry(today, "deploy_b", "deploy")])
    calls = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: (calls.append((a, k)),
                                                         {"email": True, "telegram": False,
                                                          "feishu": True})[1])
    r = notify.flush_digest()
    _chk(r["sent"] is True and r["n"] == 2, f"23:25 后应发 1 条(n=2), 得 {r}")
    _chk(len(calls) == 1, "应恰 1 次 send")
    subj, body = calls[0][0][0], calls[0][0][1]
    kw = calls[0][1]
    _chk(subj.startswith("[告警·摘要] 当日合并 2 条"), f"subject 模板不对: {subj}")
    _chk(kw.get("severe") is False and kw.get("from_prefix") == "[告警·摘要]"
         and kw.get("feishu_group") == "alert" and kw.get("ledger_tier") == "digest"
         and kw.get("ledger_key") == "alert_digest" and kw.get("merged_count") == 2,
         f"send 参数字段应逐字对标 §1.5 模板, 得 {kw}")
    _chk(_digest_lines(_iso["alerts"]) == [], "成功后应精确清理已发条目")
    st = json.loads((_iso["alerts"] / "alert_digest_state.json").read_text(encoding="utf-8"))
    _chk(st.get("last_sent_day") == today, f"state 应写 last_sent_day=today, 得 {st}")
    # 同日二次 flush → 不重发
    r2 = notify.flush_digest()
    _chk(r2["sent"] is False, f"同日二次 flush 不应重发, 得 {r2}")
    _chk(len(calls) == 1, "同日二次 flush 不应再 send")


def test_04c_flush_send_fail_keeps_entries(_iso, monkeypatch):
    today = _today()
    _patch_now(monkeypatch, datetime.strptime(today + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    _seed_digest(_iso["alerts"], [_entry(today)])
    monkeypatch.setattr(notify, "send", lambda *a, **k: {"email": False, "telegram": False,
                                                         "feishu": False})
    r = notify.flush_digest()
    _chk(r["sent"] is False and r["n_remaining"] == 1, f"发送失败条目应保留, 得 {r}")
    _chk(len(_digest_lines(_iso["alerts"])) == 1, "失败后条目不得清理")
    _chk(not (_iso["alerts"] / "alert_digest_state.json").exists(),
         "失败后不得写 state(否则当日永不重试)")


def test_04d_flush_stale_next_day_sends(_iso, monkeypatch):
    yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _patch_now(monkeypatch, datetime(2026, 10, 10, 12, 0, 0))  # 非 23:25 也发(stale)
    _seed_digest(_iso["alerts"], [_entry(yday)])
    calls = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: (calls.append((a, k)),
                                                         {"email": True, "telegram": False,
                                                          "feishu": True})[1])
    r = notify.flush_digest()
    _chk(r["sent"] is True and r["n"] == 1, f"隔日 stale 必发, 得 {r}")
    _chk("含前日遗留" in calls[0][0][0], f"stale 摘要 subject 应标注前日遗留: {calls[0][0][0]}")


def test_04e_flush_digest_disable(_iso, monkeypatch):
    today = _today()
    _patch_now(monkeypatch, datetime.strptime(today + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    _seed_digest(_iso["alerts"], [_entry(today)])
    monkeypatch.setenv("ALERT_DIGEST_DISABLE", "1")
    calls = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: (calls.append(1), {"email": True})[1])
    r = notify.flush_digest()
    _chk(r["sent"] is False and calls == [], f"ALERT_DIGEST_DISABLE=1 应全停 flush, 得 {r}")


# ══════════════════════════════ ⑤ main() digested 早退 ══════════════════════════════
def test_05_main_digested_early_return(_iso, monkeypatch):
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    updated, written = [], []
    monkeypatch.setattr(notify, "update_dedup", lambda k: updated.append(k))
    monkeypatch.setattr(notify, "write_alert",
                        lambda *a, **k: written.append(a))
    rc = notify.main(["主题", "正文", "--severe", "--dedup-key", "r2_two",
                      "--alert-issue", "议题"])
    _chk(rc == 0, f"digested 恒 return 0, 得 {rc}")
    _chk(_iso["calls"] == [], "digested 不应外发")
    _chk(updated == [], f"digested 不得 update_dedup(未外发不该占窗), 得 {updated}")
    _chk(written == [], f"digested 不得 write_alert, 得 {written}")
    _chk(len(_digest_lines(_iso["alerts"])) == 1, "应入 buffer 1 行")


# ══════════════════════════════ ⑥ W2 契约登记 ══════════════════════════════
def test_06_w2_signature_registered():
    _chk(notify_state("[notify][budget] 并入当日摘要 key=r2_x category=r2\n") == "suppressed",
         "budget 吸收行应判 suppressed")
    _chk(notify_state("[notify][digest] 已并入摘要 buffer category=r2\n") == "suppressed",
         "defer-digest 成功行应判 suppressed")
    _chk(notify_sent("[notify][budget] 并入当日摘要\n") is False,
         "budget 行不算「已发出」(notify_sent 保持 False)")
    # 反向用例:tier=warning 的 suppressed 成功行仍判 sent(不得被 substring 误判)
    _chk(notify_state("[notify][tier=warning] 路由完成：{'deferred': True, "
                      "'defer_status': 'suppressed'}\n") == "sent",
         "tier 分支 suppressed 成功行必须判 sent(顺序硬约束)")


# ══════════════════════════════ ⑦ alert_budget_process ══════════════════════════════
def test_07_budget_process_mixed_round(_iso):
    kept, absorbed = adr.alert_budget_process({}, [
        "SEVERE: r2_a R2 不可达",
        "SEVERE: r2_b R2 又一次",
        "SEVERE: cloud_unit_patrol_drift unit 漂移",
        "SEVERE: unrelated_x 内存超限",
    ], datetime.now(), _iso["tmp"])
    _chk(kept == ["SEVERE: r2_a R2 不可达", "SEVERE: cloud_unit_patrol_drift unit 漂移",
                  "SEVERE: unrelated_x 内存超限"], f"kept 分布不对: {kept}")
    _chk(len(absorbed) == 1 and absorbed[0]["category"] == "r2",
         f"同轮第 2 条 r2 应被吸收, 得 {absorbed}")
    _chk(absorbed[0]["line"] == "SEVERE: r2_b R2 又一次", "吸收条目应带原始行")


def test_07b_budget_process_per_category(_iso):
    # 注: category_of_line 只覆盖 §1.2 定义的 5 类(r2/data_gap/gap_check/unit/deploy);
    # fund_nav/kelly 行文本无特征 ⇒ monitor 行级不可识别, 由 notify gate 的 key 维度覆盖。
    samples = {
        "unit": "SEVERE: failed_units_patrol failed unit 合集",
        "r2": "SEVERE: r2_overview_lag R2 overview 滞后",
        "data_gap": "SEVERE: [数据缺口] 公募全 NULL",
        "gap_check": "SEVERE: nextday_gap_check 伪跳空校验失败",
        "deploy": "SEVERE: deploy_verify_fail 部署校验失败",
    }
    for cat, line in samples.items():
        kept, absorbed = adr.alert_budget_process({}, [line, line], datetime.now(), _iso["tmp"])
        _chk(len(kept) == 1 and kept[0] == line, f"[{cat}] 首条应 kept, 得 {kept}")
        _chk(len(absorbed) == 1 and absorbed[0]["category"] == cat,
             f"[{cat}] 第 2 条应 absorbed, 得 {absorbed}")


def test_07c_budget_process_ledger_aware(_iso):
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_unreachable", "x")])
    kept, absorbed = adr.alert_budget_process({}, ["SEVERE: r2_a R2 不可达"], datetime.now(),
                                              _iso["tmp"])
    _chk(kept == [] and len(absorbed) == 1,
         f"台账已耗 r2 预算 → 首行即吸收, 得 kept={kept}")


def test_07d_budget_process_failopen_no_ledger(_iso):
    kept, absorbed = adr.alert_budget_process({}, ["SEVERE: r2_a R2 x", "SEVERE: r2_b R2 y"],
                                              datetime.now(), _iso["tmp"])
    _chk(len(kept) == 1 and len(absorbed) == 1, "空台账下同轮首行直发/次行吸收")


def test_07e_task_family_off_by_default(_iso, monkeypatch):
    # 不同 task 同类两条: task_family 默认关 → 只有类别预算生效(仍只首条直发)
    kept, absorbed = adr.alert_budget_process({}, [
        "SEVERE: task_a [数据缺口] x",
        "SEVERE: task_b [数据缺口] y",
    ], datetime.now(), _iso["tmp"])
    _chk(len(kept) == 1 and len(absorbed) == 1, f"默认档应只受类别预算, 得 {kept}/{absorbed}")


# ══════════════════════════════ ⑦b monitor 吸收循环 fail-open 回批 ══════════════════════════════
def _monitor_src() -> str:
    text = MONITOR.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    h0 = next(i for i, l in enumerate(lines) if "<<'PYEOF'" in l)
    h1 = next(i for i, l in enumerate(lines) if i > h0 and l.strip() == "PYEOF")
    return "".join(lines[h0 + 1:h1])


def _absorb_loop_code():
    """ast 提取真「defer-digest 吸收循环」块(`for _ent in _absorbed:`)。"""
    src = _monitor_src()
    tree = ast.parse(src)
    loop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.For) and getattr(n.target, "id", None) == "_ent"
                and isinstance(n.iter, ast.Name) and n.iter.id == "_absorbed")
    return compile(textwrap.dedent(ast.get_source_segment(src, loop)),
                   "<absorb-loop>", "exec")


def _run_absorb_loop(rc: int, absorbed: list[dict]) -> list[str]:
    alerts: list[str] = []

    def _run(cmd, *a, **k):
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

    g = {"subprocess": types.SimpleNamespace(run=_run), "sys": sys,
         "REPO": Path("/x"), "alerts": alerts, "_absorbed": absorbed,
         "print": lambda *a, **k: None}
    exec(_absorb_loop_code(), g)  # noqa: S102  (真源码块: 只 append alerts)
    return alerts


def test_07f_monitor_defer_fail_rebatch():
    ent = {"line": "SEVERE: r2_b R2 又一次", "category": "r2", "key": "r2_b|a1b2c3d4"}
    _chk(_run_absorb_loop(1, [ent]) == [ent["line"]], "defer rc!=0 应回批直发")
    _chk(_run_absorb_loop(0, [ent]) == [], "defer rc=0 不应回批(已吸收)")


def test_07g_monitor_wires_budget_process_and_branch():
    src = _monitor_src()
    _chk("adr.alert_budget_process(alert_state, alerts, NOW, REPO)" in src,
         "monitor 应调用 alert_budget_process(§1.6)")
    _chk("elif _orig_has_alerts or _absorbed:" in src,
         "批次全吸收分支应含 _absorbed(§1.6 日志分支)")
    _chk("adr.r5_congestion_process(" not in src,
         "monitor 不应再调用 r5(已被 alert_budget_process 取代)")


# ══════════════════════════════ ⑧ 恢复闭环 D5 ══════════════════════════════
def _recovery_loop_code():
    """ast 提取**真恢复检测环**(`for _key, _info in list(alert_state.items()):` 整块)。"""
    src = _monitor_src()
    tree = ast.parse(src)
    loop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.For) and isinstance(n.iter, ast.Call)
                and isinstance(n.target, ast.Tuple) and len(n.target.elts) == 2
                and getattr(n.target.elts[0], "id", None) == "_key"
                and getattr(n.target.elts[1], "id", None) == "_info")
    return compile(textwrap.dedent(ast.get_source_segment(src, loop)),
                   "<recovery-loop>", "exec")


def _run_recovery_loop(state, seen, now):
    g = {"adr": adr, "NOW": now, "alert_state": state, "seen_keys_this_run": seen,
         "recoveries": [], "in_progress_tasks": set(),
         "print": lambda *a, **k: None,
         "_recovery_cooldown_ok": lambda k, i: True,
         "RECOVERY_COOLDOWN": timedelta(hours=6)}
    exec(_recovery_loop_code(), g)  # noqa: S102
    return g["recoveries"], state


def test_08_pending_key_not_flipped_by_recovery_loop():
    now = datetime(2026, 10, 10, 12, 0, 0)
    state = {
        "monitor_recovery|pending": {"status": "pending_hold",
                                     "items": [{"task": "t", "keyword": "kw",
                                                "first_seen": "2026-10-10 10:00:00"}]},
        "real_task|x": {"status": "active", "keyword": "kw2",
                        "first_seen": "2026-10-10 09:00:00"},
    }
    recs, state2 = _run_recovery_loop(state, seen=set(), now=now)
    _chk(state2["monitor_recovery|pending"]["status"] == "pending_hold",
         "pending 桶不得被恢复环误判翻转")
    _chk(not any(r.get("task") == "monitor_recovery" for r in recs),
         f"pending 键不得产生恢复项, 得 {recs}")
    _chk(state2["real_task|x"]["status"] == "recovered", "真异常 key 应正常置 recovered")


def test_08b_recovery_loop_has_skip_anchor():
    src = _monitor_src()
    _chk('_key.startswith("monitor_recovery|")' in src, "恢复环应含 monitor_recovery| skip(§1.7)")
    _chk('_PEND_KEY = "monitor_recovery|pending"' in src, "应定义 pending 桶键(§1.7)")
    _chk("notify_state(_rec_out)" in src, "恢复发送块应用 notify_state 三态(§1.7)")
    _chk('"--digest-category", "recovery"' in src, "尾应含恢复摘要补列(§1.7④)")
    _chk("--flush-digest" in src, "尾应含摘要 flush 调用(§1.6④)")


def test_08c_recovery_digest_defer_via_cli(_iso):
    # monitor 尾恢复补列 = `notify.py <subj> <body> --defer-digest --digest-category recovery`
    rc = notify.main(["[恢复] task_x kw_x", "恢复补列正文", "--defer-digest",
                      "--digest-category", "recovery"])
    _chk(rc == 0, f"defer-digest recovery 应 rc=0, 得 {rc}")
    lines = _digest_lines(_iso["alerts"])
    _chk(len(lines) == 1, "应入 buffer 1 行")
    rec = json.loads(lines[0])
    _chk(rec["category"] == "recovery", f"类别应 recovery, 得 {rec['category']}")


def test_08d_flush_marks_recovery_row(_iso, monkeypatch):
    today = _today()
    _patch_now(monkeypatch, datetime.strptime(today + " 23:30:00", "%Y-%m-%d %H:%M:%S"))
    _seed_digest(_iso["alerts"], [_entry(today, "task_x", "recovery")])
    captured = {}

    def _rec(subj, body, **k):
        captured["subj"] = subj
        captured["body"] = body
        return {"email": True, "telegram": False, "feishu": True}

    monkeypatch.setattr(notify, "send", _rec)
    r = notify.flush_digest()
    _chk(r["sent"] is True, f"恢复条目应发, 得 {r}")
    _chk("[恢复补列]" in captured.get("body", ""),
         f"恢复条目应带 [恢复补列] 标注: {captured.get('body')}")


# ══════════════════════════════ ⑨ 机检:digested 消费点 ══════════════════════════════
def test_09_consumption_points_adapted():
    src = (SCRIPTS / "notify.py").read_text(encoding="utf-8")
    _chk("digested" in src, "notify.py 应含 digested")
    i_dig = src.find('if results.get("digested"):')
    i_ok = src.find("ok = [ch for ch, v in results.items() if v]", i_dig)
    _chk(i_dig >= 0 and i_ok > i_dig, "通用路径 digested 早退必须在 ok 判定之前")
    # 通用路径 ok 判定所在函数应紧邻 digested 早退(防未来新增消费点漏挂)
    _chk(src.count('results.get("digested")') >= 1, "至少一处 digested 早退")
    # 其它 results.items() ok 判定:仅在固定渠道键白名单上取,不被 digested 污染
    _chk('if v and ch in ("email", "telegram", "feishu")' in src,
         "r4 路径 ok 判定应白名单化渠道键(天然排除 digested)")


def test_zzz_assertion_floor():
    _chk(_N[0] >= _MIN_ASSERTIONS,
         f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(收集/执行被短路?)")