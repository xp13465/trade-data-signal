# -*- coding: utf-8 -*-
"""#282 告警降噪三件(A 停摆直发 / B active 升级阶梯 / C 抑制审计台账)自验。

依据(只读评估报告 /tmp/research-alert-denoise-eval.md §4.1/§4.3/§5/§7.3):
  A: scripts/alert_denoise_rules.py 旧 DOMAIN_AGGREGATE_EXEMPT_KEYS 只豁免
     deploy_consecutive_fail; domain_of 把「计划任务异常/锁跳过/deploy/R2/双站一致性」
     都并成 r2_deploy ⇒ 10-20 deploy 连续失败 39 次、15 条 R2/deploy 失败被并进 23:30
     摘要; staticdata 备份停摆 36h 只报一条泛化异常; D1 同步连续失败 39 次零告警。
  B: scripts/schedule_monitor.sh 旧实现无条件静默 status=active, 与 :371 注释
     「真卡死(持续 active >6h)仍响」矛盾; nextday_gap_check|ConnectionError 自
     10-13 active 9 天、1,125 条 suppress 零再提醒。
  C: 旧台账只记「已外发」, 答不了「这条故障为什么没通知我」; alert_domains.json
     的 n_absorbed 是累计值, 日志却写「本日该域已并入 N 条」。

零外发铁律(§18 L48): 渠道函数整体打桩 + 外层 ZeroOutboundTrap 包住
  urllib/smtplib; 收尾断言 trap.hits == []。所有落盘面全指向 tmp_path。
  另有 test_zero_outbound_trap_sandbox_works 先证明「陷阱确实会响」, 防打桩假绿。

跑法: python3 -m pytest -q scripts/tests/test_282_alert_denoise3_20261022.py
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
MONITOR = SCRIPTS / "schedule_monitor.sh"
SUPP_LEDGER = "suppression_ledger.jsonl"

_MIN_ASSERTIONS = 80
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


@pytest.fixture(scope="module", autouse=True)
def _count_guard():
    yield
    assert _N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < {_MIN_ASSERTIONS}(防假绿)"


# ══════════════════════════ 隔离 fixture(零外发 + 全 tmp) ══════════════════════════
@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPO", str(tmp_path))
    for _v in ("NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE", "ALERT_DOMAIN_DISABLE",
               "ALERT_DIGEST_DISABLE", "ALERT_NOTICE_BUDGET_DISABLE",
               "ALERT_LEDGER_DISABLE", "NOTIFY_RESULT_FILE"):
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
    monkeypatch.setattr(notify, "WARNING_DEDUP_LOCK_FILE", alerts / "warning_dedup.lock")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", alerts / "warning_buffer.flushlock")
    _leak = [n for n in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                         "WARNING_FLUSH_LOCK_FILE", "WARNING_DEDUP_STATE_FILE",
                         "WARNING_DEDUP_LOCK_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                         "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE")
             if tmp_path not in Path(getattr(notify, n)).parents]
    assert not _leak, f"隔离缝破损: {_leak}"

    calls: list[dict] = []

    def _fake(kind):
        def _f(subject, body, *_a, **_k):
            calls.append({"kind": kind, "subject": subject, "body": body,
                          "args": _a, "kwargs": _k})
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "calls": calls, "trap": trap}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


def _now_s(dt=None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _seed_ledger(alerts: Path, rows: list[dict]) -> None:
    p = alerts / "alert_ledger.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _seed_domain(alerts: Path, now=None) -> None:
    _write_json(alerts / adr.ALERT_DOMAIN_STATE_FILENAME,
                {"r2_deploy": {"last_ts": _now_s(now), "last_day": _now_s(now)[:10]}})


def _seed_dedup(alerts: Path, key: str, now=None) -> None:
    _write_json(alerts / "notify_dedup.json", {key: {"last_alerted": _now_s(now)}})


def _supp_records(repo: Path) -> list[dict]:
    p = repo / "data" / "alerts" / SUPP_LEDGER
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ══════════════════════════ 0. 先证明沙箱判定生效 ══════════════════════════
def test_zero_outbound_trap_sandbox_works():
    import urllib.request
    with ZeroOutboundTrap() as t:
        try:
            urllib.request.urlopen("https://example.invalid/")
            _chk(False, "陷阱未拦截真实外发")
        except AssertionError as e:
            _chk("零外发被破坏" in str(e))
        except Exception as e:  # noqa: BLE001
            _chk(False, f"陷阱行为异常: {type(e).__name__}: {e}")
    _chk(len(t.hits) == 1, f"陷阱命中数应为 1, 实际 {t.hits}")


# ══════════════════════════ A. 停摆级独立通道 ══════════════════════════
def test_a_registry_covers_five_classes_and_is_disjoint():
    five = {
        "deploy 连续失败": {"deploy_consecutive_fail", "deploy_r2_upload_fail",
                            "deploy_purge_low_freq_fail"},
        "staticdata 备份失败/停摆": {"staticdata_backup_fail",
                                    "staticdata_backup_trigger_fail",
                                    "staticdata_backup_stale"},
        "R2 上传失败/超时": {"r2_upload_trigger_fail"},
        "D1 同步连续失败": {"d1_sync_fail"},
        "unit 连续失败": {"failed_units_patrol", "cloud_unit_patrol_drift"},
    }
    for label, keys in five.items():
        _chk(keys & adr.STALL_KEYS == keys, f"{label} 未在 STALL_KEYS 登记: {keys - adr.STALL_KEYS}")
    _chk(not (adr.STALL_KEYS & adr.NON_STALL_KEYS), "两张登记表不得重叠")
    _chk(adr.is_stall_key("deploy_consecutive_fail"), "deploy 连续失败必须仍为停摆级(不回退)")
    _chk(adr.is_stall_key("stall|consecutive_fail"), "monitor 合成键应识别为停摆")
    _chk(not adr.is_stall_key("r2_consistency_fail"), "三站一致性语义未收口, 不得误升停摆")
    _chk(not adr.is_stall_key("deploy_check_version_fail"), "单次闸门失败不得误升停摆")


def test_a_stall_line_markers():
    cases = {
        "SEVERE: staticdata 备份停摆 36h 未完成": "staticdata_backup_stale",
        "SEVERE: D1 同步连续失败 39 次": "d1_sync_fail",
        "SEVERE: cloud_unit_patrol_drift 缺 2 个 unit": "cloud_unit_patrol_drift",
        "SEVERE: failed_units_patrol 3 个 unit failed": "failed_units_patrol",
    }
    for line, canon in cases.items():
        _chk(adr.stall_line_key(line) == canon, f"{line} → {adr.stall_line_key(line)}, 期望 {canon}")
        _chk(adr.is_stall_line(line), f"{line} 应判停摆级")
    _chk(adr.stall_line_key("SEVERE: deploy 连续失败 39 次").startswith("stall|"),
         "泛化连续失败应合成 stall| 键")
    _chk(adr.stall_line_key("SEVERE: 某脚本单次失败 rc=1") is None, "普通单次失败不得判停摆")


def test_a_omission_guard_all_producer_keys_classified():
    """防遗漏: 扫 scripts/ 全部生产方 --dedup-key 字面量, 必须落在两张表其一。

    动态键(f-string/变量)无法静态取值, 用显式前缀白名单 + 理由登记(见 DYNAMIC_PREFIXES);
    新增键若既不登记也不是已知动态前缀 ⇒ 本用例红, 逼人做「是否停摆级」判定。
    """
    dynamic_prefixes = {
        "nextday_plan_": "按交易日每日一个键, 生成计划失败单轮自愈(非停摆)",
        "nextday_gap_excluded_": "按日排除清单键, 非故障链",
        "with_lock_block_timeout:": "锁等待超时键, 按锁路径动态",
        "agent_done_": "agent 完成通知按键名动态, 非告警",
        "r2_upload_async_skip:": "按锁路径动态跳过键, 非停摆",
        "p0_smoke_": "测试用键",
    }
    pats = [
        r'--dedup-key"?\s*,\s*"([A-Za-z0-9_|.:-]+)"',
        r'--dedup-key[ =]+"([A-Za-z0-9_|.:-]+)"',
        r"--dedup-key[ =]+'([A-Za-z0-9_|.:-]+)'",
        r"--dedup-key[ =]+([A-Za-z0-9_|.-]+)",
    ]
    found, dynamic = set(), set()
    fpat = re.compile(r'--dedup-key"?\s*,\s*f"([A-Za-z0-9_|.:-]+)\{')
    for p in sorted(SCRIPTS.glob("*")):
        if p.suffix not in (".py", ".sh") or not p.is_file():
            continue
        if p.name.startswith("test_") or p.name == "alert_weekly_review.py":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for m in fpat.finditer(text):
            dynamic.add(m.group(1))
            dynamic.add("r2_upload_async_skip:")
        for pat in pats:
            for m in re.finditer(pat, text):
                k = m.group(1).rstrip(":")
                if "_" in k:
                    found.add(k)
    unclassified = {k for k in found
                    if k not in adr.STALL_KEYS and k not in adr.NON_STALL_KEYS}
    _chk(not unclassified, f"未登记的新 dedup key(必须判停摆/非停摆): {sorted(unclassified)}")
    for pre in dynamic:
        _chk(any(pre.startswith(x) for x in dynamic_prefixes),
             f"动态键前缀 {pre!r} 未在防遗漏白名单登记")
    _chk(len(found) >= 40, f"扫描到的生产键过少({len(found)}), 防遗漏网可能失效")


def test_a_stall_bypasses_budget_and_domain_and_2h_dedup(iso):
    """构造 10-20 场景同款: 预算已满 + 同域 2h 窗内, 停摆级仍首报直发; 2h 内同键只发一次。"""
    alerts, calls = iso["alerts"], iso["calls"]
    keys = ["deploy_consecutive_fail", "staticdata_backup_stale",
            "r2_upload_trigger_fail", "d1_sync_fail",
            "failed_units_patrol", "cloud_unit_patrol_drift"]
    _write_json(iso["tmp"] / "data" / "alert_state.json", {
        "deploy_consecutive_fail": {"first_seen": "2026-10-20 12:00:00",
                                    "consecutive_count": 39},
        "staticdata_backup_stale": {"first_seen": "2026-10-20 09:00:00"},
    })
    _write_json(iso["tmp"] / "data" / "deploy_fail_state.json",
                {"consecutive_fail": 39, "last_fail_at": _now_s()})
    _write_json(iso["tmp"] / "data" / "staticdata_backup_fail_state.json",
                {"first_fail_date": "2026-10-20", "consecutive_days": 3})
    (iso["tmp"] / "data" / "d1_sync_state").mkdir(parents=True, exist_ok=True)
    _write_json(iso["tmp"] / "data" / "d1_sync_state" / "sync_a.json",
                {"script": "sync_a", "first_failure_at": "2026-10-20 10:00:00",
                 "consecutive_failures": 39})
    _write_json(iso["tmp"] / "data" / "failed_units_patrol_state.json",
                {"first_fail_date": "2026-10-20", "consecutive_days": 3})

    for key in keys:
        _seed_ledger(alerts, [{"ts": _now_s(), "group": "alert", "tier": "critical",
                               "key": key, "subject": key}])
        _seed_domain(alerts)
        _seed_dedup(alerts, "other_key")
        before = len(calls)
        res = notify.send(f"[告警] 计划任务异常: {key}", "原始正文",
                          severe=True, from_prefix="[告警]", ledger_key=key)
        _chk(res.get("email") and res.get("telegram") and res.get("feishu"),
             f"{key} 应三渠道直发(停摆绕过预算/域聚合), 实际 {res}")
        _chk(len(calls) == before + 3, f"{key} 应发出 3 次渠道调用")
        subj = calls[before]["subject"]
        body = calls[before]["body"]
        _chk(subj.startswith(adr.STALL_PREFIX), f"{key} 标题缺停摆前缀: {subj}")
        _chk("首次发生" in body and "连续失败" in body and "影响产物" in body,
             f"{key} 正文缺三字段: {body[:200]}")
        # 第二次(2h 内同键)只 suppress, 不再外发
        before2 = len(calls)
        res2 = notify.send(f"[告警] 计划任务异常: {key}", "原始正文",
                           severe=True, from_prefix="[告警]", ledger_key=key)
        _chk(res2.get("suppressed") is True, f"{key} 2h 内应 suppress, 实际 {res2}")
        _chk(len(calls) == before2, f"{key} 2h 内不得再次外发")
    recs = _supp_records(iso["tmp"])
    _chk(sum(1 for r in recs if r["mechanism"] == "stall_dedup") == len(keys),
         f"stall_dedup 审计记录应 {len(keys)} 条, 实际 {len(recs)}")


def test_a_context_three_fields_real_state(iso):
    _write_json(iso["tmp"] / "data" / "alert_state.json", {
        "deploy_consecutive_fail": {"first_seen": "2026-10-20 12:00:00"},
    })
    _write_json(iso["tmp"] / "data" / "deploy_fail_state.json",
                {"consecutive_fail": 39, "last_fail_at": "2026-10-22 11:00:00"})
    ctx = adr.stall_context("deploy_consecutive_fail", iso["tmp"])
    _chk(ctx["first_seen"] == "2026-10-20 12:00:00", f"首次发生应取 alert_state: {ctx}")
    _chk(ctx["consecutive"] == 39, f"连续失败应取真实状态 39: {ctx}")
    _chk("线上静态站" in ctx["impact"] or "发布链" in ctx["impact"], f"影响产物: {ctx}")
    ctx2 = adr.stall_context("r2_upload_trigger_fail", iso["tmp"])
    _chk(ctx2["first_seen"] == "未知" and ctx2["consecutive"] == "未知",
         f"无状态文件必须显式写未知: {ctx2}")


def test_a_stall_window_policy():
    """停摆通道窗径: 非零窗 2h 地板; 显式 0(脚本自管闸门)原样保留, 不吞新增立即报。"""
    _chk(adr.stall_dedup_window(None) == adr.STALL_DEDUP_WINDOW)
    _chk(adr.stall_dedup_window(0) == 0, "显式 0 必须保留(check_failed_units/d1_sync 自管闸门)")
    _chk(adr.stall_dedup_window(-1) == 0)
    _chk(adr.stall_dedup_window(3600) == adr.STALL_DEDUP_WINDOW, "1h 调用窗应抬到 2h 地板")
    _chk(adr.stall_dedup_window(21600) == 21600, "deploy 现网 6h 窗不得被缩短成 2h")


def test_a_cli_staticdata_path_not_swallowed_by_r4(iso):
    """R4 staticdata 分段路径(连续>=2天)也必须走停摆直发, 不能被 6h 窗/无 key 转发吞掉。"""
    alerts, calls = iso["alerts"], iso["calls"]
    _write_json(iso["tmp"] / "data" / "staticdata_backup_fail_state.json",
                {"last_fail_date": "2026-10-20", "consecutive_days": 2})
    # 现网调用窗 = staticdata_backup_async.sh:521 的 3600(1h) ⇒ 停摆通道抬到 2h 地板。
    rc = notify.main(["[告警] staticdata 备份失败(连续 3 天)", "备份正文", "--severe",
                      "--from-prefix", "[告警]", "--dedup-key", "staticdata_backup_fail",
                      "--dedup-window", "3600"])
    _chk(rc == 0)
    _chk(len(calls) == 3, f"R4 停摆应直发三渠道, 实际 {calls}")
    _chk(calls[0]["subject"].startswith(adr.STALL_PREFIX), calls[0]["subject"])
    _chk("首次发生" in calls[0]["body"] and "影响产物" in calls[0]["body"])
    before = len(calls)
    rc2 = notify.main(["[告警] staticdata 备份失败(连续 3 天)", "备份正文", "--severe",
                       "--from-prefix", "[告警]", "--dedup-key", "staticdata_backup_fail",
                       "--dedup-window", "3600"])
    _chk(rc2 == 0)
    _chk(len(calls) == before, "2h 内同键不得再发")
    _chk(any(r["mechanism"] == "stall_dedup" for r in _supp_records(iso["tmp"])))


def test_a_ordinary_event_still_aggregated(iso):
    """普通事件行为不回退: 日预算满或同域 2h 窗内仍并入摘要, 不外发。"""
    alerts, calls = iso["alerts"], iso["calls"]
    key = "r2_consistency_fail"  # 非停摆级(语义待 #279 收口), 预算类别 r2
    _chk(not adr.is_stall_key(key))
    _chk(adr.category_of(key, "") == "r2" and adr.domain_of(key, "") == "r2_deploy")
    _seed_ledger(alerts, [{"ts": _now_s(), "group": "alert", "tier": "critical",
                           "key": key, "subject": key}])
    _seed_domain(alerts)
    res = notify.send(f"[告警] {key} R2 上传失败", "正文", severe=True,
                      from_prefix="[告警]", ledger_key=key)
    _chk(res.get("digested") is True, f"普通键预算满应并入摘要, 实际 {res}")
    _chk(calls == [], f"普通键被聚合时不得外发, 实际 {calls}")
    _chk(any(r["mechanism"] == "budget" for r in _supp_records(iso["tmp"])),
         "预算吸收必须写审计台账")


def test_a_domain_aggregation_record_and_n_absorbed_today(iso):
    alerts, calls = iso["alerts"], iso["calls"]
    key = "intraday_upload_index_r2_fail"
    _seed_domain(alerts)
    res = notify.send(f"[告警] {key} R2 上传失败", "正文", severe=True,
                      from_prefix="[告警]", ledger_key=key)
    _chk(res.get("digested") is True, f"同域 2h 窗内应并入摘要, 实际 {res}")
    _chk(calls == [])
    recs = [r for r in _supp_records(iso["tmp"]) if r["mechanism"] == "domain_aggregate"]
    _chk(len(recs) == 1, f"应写 1 条 domain_aggregate, 实际 {recs}")
    _chk(recs[0]["domain"] == "r2_deploy" and recs[0]["key"] == key)
    # 口径: n_absorbed(累计) vs n_absorbed_today(本日)
    st = json.loads((alerts / adr.ALERT_DOMAIN_STATE_FILENAME).read_text(encoding="utf-8"))
    entry = st["r2_deploy"]
    _chk(entry["n_absorbed_today"] == 1 and entry["n_absorbed"] >= 1,
         f"域状态口径字段缺失: {entry}")


# ══════════════════════════ B. active 升级阶梯 ══════════════════════════
def test_b_active_judge_three_states_and_old_state():
    now = datetime(2026, 10, 22, 12, 0, 0)
    fresh = {"first_alerted": _now_s(now - timedelta(hours=1)), "last_alerted": _now_s(now)}
    ok, info = adr.active_escalation_judge(fresh, now)
    _chk(ok is False and info["elapsed_hours"] == 1.0, f"1h 不应升级: {ok} {info}")

    old = {"first_alerted": _now_s(now - timedelta(hours=25)), "suppress_count": 7}
    ok, info = adr.active_escalation_judge(old, now)
    _chk(ok is True and info["elapsed_hours"] == 25.0 and info["suppress_count"] == 7,
         f"25h 应升级: {ok} {info}")

    just = dict(old, last_escalated=_now_s(now))
    ok, info = adr.active_escalation_judge(just, now)
    _chk(ok is False and "距上次升级" in info["reason"], f"刚升级不应重复: {ok} {info}")

    later = dict(old, last_escalated=_now_s(now - timedelta(hours=25)))
    ok, _ = adr.active_escalation_judge(later, now)
    _chk(ok is True, "距上次升级满 24h 应再提醒")

    # 老状态向后兼容: 没有 first_alerted
    ok, info = adr.active_escalation_judge(
        {"first_seen": _now_s(now - timedelta(hours=30))}, now)
    _chk(ok is True and info["first_alerted"].startswith("2026-10-21"), f"{info}")
    ok, info = adr.active_escalation_judge(
        {"last_alerted": _now_s(now - timedelta(hours=1))}, now)
    _chk(ok is False, f"老状态回填 last_alerted 后不应立刻升级: {info}")
    ok, info = adr.active_escalation_judge({}, now)
    _chk(ok is False and info["reason"].startswith("无首次时间"), f"空状态不得崩: {info}")


def _load_active_escalate(tmp_path: Path):
    """从 schedule_monitor.sh 内嵌 python heredoc ast 提取 _active_escalate 真源码执行。

    不重写副本(防第三实现漂移): 测的就是线上那个函数体。
    """
    text = MONITOR.read_text(encoding="utf-8")
    _mark = text.index("<<'PYEOF'")
    start = text.index("\n", _mark) + 1
    end = text.index("\nPYEOF", start)
    py_src = text[start:end]
    tree = ast.parse(py_src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_active_escalate")
    code = ast.get_source_segment(py_src, node)
    events = []

    def _run(cmd, **kw):
        events.append({"cmd": cmd, "kw": kw})
        return types.SimpleNamespace(returncode=0, stdout="[notify] sent", stderr="")

    ns = {
        "adr": adr, "NOW": datetime.now(), "sys": sys, "hashlib": __import__("hashlib"),
        "REPO": tmp_path, "MONITOR_LOG": tmp_path / "monitor.log",
        "subprocess": types.SimpleNamespace(run=_run),
        "notify_sent": lambda out: "sent" in out,
    }
    exec(compile(code, "<monitor:_active_escalate>", "exec"), ns)
    return ns["_active_escalate"], events


def test_b_active_escalate_helper_outbound_counts(iso):
    fn, events = _load_active_escalate(iso["tmp"])
    now = datetime.now()
    fresh = {"first_alerted": _now_s(now - timedelta(hours=1))}
    _chk(fn(fresh, "key|ConnectionError", "nextday_gap_check") is False)
    _chk(len(events) == 0, "1h 持续只抑制不外发")
    _chk(fresh["suppress_count"] == 1, "抑制轮次必须累计")

    old = {"first_alerted": _now_s(now - timedelta(hours=25))}
    _chk(fn(old, "key|ConnectionError", "nextday_gap_check") is True)
    _chk(len(events) == 1, "满 24h 必须发一次升级")
    body = events[0]["kw"].get("capture_output") is not None  # subprocess 调用形态
    _chk(body, "升级提醒必须走 notify 子进程")
    _chk("last_escalated" in old and old["n_escalated"] == 1, f"状态未记升级: {old}")
    _chk(fn(old, "key|ConnectionError", "nextday_gap_check") is False)
    _chk(len(events) == 1, "刚升级 24h 内不得重复")

    legacy = {"last_alerted": _now_s(now - timedelta(hours=1))}
    _chk(fn(legacy, "k2", "legacy") is False, "老状态不得崩")
    _chk(len(events) == 1)
    legacy2 = {"first_seen": _now_s(now - timedelta(hours=26))}
    _chk(fn(legacy2, "k3", "legacy2") is True, "老状态 first_seen 满 24h 应升级")
    _chk(len(events) == 2 and legacy2["first_alerted"] == legacy2["first_seen"],
         "first_alerted 应回填")

    recs = [r for r in _supp_records(iso["tmp"]) if r["mechanism"] == "active"]
    _chk(len(recs) == 5, f"每次 active 抑制都要留审计(5 次), 实际 {len(recs)}")
    _chk(all(r["source"] == "schedule_monitor" for r in recs))
    _chk(all(r["first_seen"] for r in recs))


def test_b_monitor_wiring_and_comment_consistency():
    src = MONITOR.read_text(encoding="utf-8")
    _chk("def _active_escalate(" in src)
    _chk(src.count("_active_escalate(") >= 21,
         f"active 抑制点应全部收敛到 _active_escalate, 实际 {src.count('_active_escalate(')}")
    _chk(src.count("[suppress]") == 1, "只允许升级函数内部打印一次抑制日志")
    _chk("原注释声称「真卡死仍响」但实现无条件静默" in src, "注释须如实说明旧口径矛盾")
    _chk("首次告警满 24h 且距上次升级满 24h" in src, "新口径须写清")
    # A 的 monitor 接线: 停摆行必须在批次预算之前被拆出
    _chk("_stall_batch = []" in src and "adr.stall_line_key" in src)
    _chk(src.index("_stall_batch = []")
         < src.index("alerts, _absorbed = adr.alert_budget_process("),
         "停摆行拆分必须早于批次预算(否则仍会被预算吸收)")
    _chk('"--dedup-window", str(adr.STALL_DEDUP_WINDOW)' in src, "停摆直发必须带 2h 窗")


# ══════════════════════════ C. 抑制/合并审计台账 ══════════════════════════
def test_c_records_have_complete_fields(iso):
    now = datetime(2026, 10, 22, 12, 0, 0)
    ok = adr.record_suppression(mechanism="budget", key="k_demo", reason="演示",
                                source="test_282", repo=iso["tmp"], now=now,
                                first_seen="2026-10-20 09:00:00", event_id="evt1")
    _chk(ok is True)
    rec = _supp_records(iso["tmp"])[-1]
    for f in ("ts", "day", "mechanism", "key", "fingerprint", "domain", "reason",
              "source", "first_seen", "event_id"):
        _chk(f in rec, f"审计字段缺失: {f} ({rec})")
    _chk(rec["day"] == "2026-10-22" and len(rec["fingerprint"]) == 12)
    _chk(adr.SUPPRESSION_LEDGER_RETAIN_DAYS == 30)
    for m in ("budget", "domain_aggregate", "dedup", "active", "recurrence",
              "stall_dedup", "escalation_window", "monitor_budget"):
        _chk(m in adr.SUPPRESS_MECHANISMS, f"机制枚举缺 {m}")


def test_c_unwritable_ledger_does_not_break_main_path(iso, monkeypatch):
    alerts, calls = iso["alerts"], iso["calls"]
    blocker = iso["tmp"] / "blocked"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setattr(adr, "suppression_ledger_path",
                        lambda repo=None: blocker / "x" / SUPP_LEDGER)
    _chk(adr.record_suppression(mechanism="budget", key="k", repo=iso["tmp"]) is False,
         "不可写时应安静返回 False")
    _seed_domain(alerts)
    res = notify.send("[告警] intraday_upload_index_r2_fail R2 上传失败", "正文",
                      severe=True, from_prefix="[告警]",
                      ledger_key="intraday_upload_index_r2_fail")
    _chk(res.get("digested") is True, f"台账写失败不得改变聚合行为: {res}")
    _chk(calls == [], "台账写失败不得触发外发")


def test_c_ledger_30day_rotation(iso):
    p = iso["tmp"] / "data" / "alerts" / SUPP_LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    old_ts = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    keep_ts = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": old_ts, "mechanism": "budget"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"ts": keep_ts, "mechanism": "budget"}, ensure_ascii=False) + "\n")
    _chk(adr.record_suppression(mechanism="dedup", key="fresh", repo=iso["tmp"]) is True)
    recs = _supp_records(iso["tmp"])
    _chk(all(r.get("ts") != old_ts for r in recs), "40 天前记录应被轮转清理")
    _chk(any(r.get("ts") == keep_ts for r in recs), "3 天前记录必须保留")
    _chk(any(r.get("key") == "fresh" for r in recs))
    _chk((p.parent / adr.SUPPRESSION_LEDGER_PRUNE_MARKER).exists(), "轮转须留当日标记防重复重写")