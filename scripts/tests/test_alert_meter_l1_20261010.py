#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W1 L1 度量层自验（2026-10-10）：台账打点 + 日计数幂等 + 跨树查询面。

覆盖（对应派单验收口径）：
  A. §18 L48 零外发哨兵生效性正控（先证沙箱能拦住真实链路，再跑其余用例）。
  B. notify.py 台账打点：
     B1 消息级 send() 一条（邮件+飞书双通道只记 1 条，不双记）；
     B2 底层直调 send_feishu / _send_email / send_telegram → 单渠道各记 1 条（旁路出口覆盖）；
     B3 send() 分发内部底层不重复记账（重入守卫）；
     B4 --dry-run 不写台账；
     B5 key 口径（dedup_key 优先 / subject 哈希回退）+ tier/group 落字段。
  C. 今日真实 20 条样本重放（§18 L49 真样本；来自审计 §4 表 + §2/§3 逐条定性）
     → 台账重算 total/severe/alert 口径 == 人工重建，并打印逐条对照表。
  D. alert_daily.json 幂等：同台账重算两次逐位一致；schema 合法。
  E. 跨两树聚合（运行树 + 信号树各含部分样本 → 聚合为同一数字）。

零外发：所有用例只在 tmp 目录构造，绝不碰生产 data/；真实邮件/飞书/TG 链路被
    smtplib.SMTP_SSL / urllib.request.urlopen 哨兵拦截（A 先证生效）。
跑法：python3 -m pytest -q scripts/tests/test_alert_meter_l1_20261010.py -s
"""
import json
import os
from pathlib import Path

import pytest

import notify
import alert_meter

# ── §18 L48 零外发哨兵（记录命中 + 抛错；正控证明其能拦住真实链路） ──
_OUTBOUND_HITS: list[str] = []


def _boom(*a, **k):
    _OUTBOUND_HITS.append("hit")
    raise RuntimeError("OUTBOUND BLOCKED: 自测产生真实外发（邮件/飞书/TG）")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch, request):
    """全部落 tmp + 零外发哨兵；env REPO=tmp 令 notify 台账写 tmp/data/alerts。

    哨兵收尾断言对「正控用例」豁免——正控的**目的**就是撞哨兵以证明沙箱有效
    （phishing 陷阱必须先自证能拦到鱼）；其余用例哨兵一旦命中即失败。
    """
    _OUTBOUND_HITS.clear()
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setattr(notify, "ALERTS_DIR", tmp_path / "data" / "alerts")
    monkeypatch.setattr(notify, "ALERTS_FILE", tmp_path / "data" / "alerts" / "latest.md")
    monkeypatch.setattr(notify, "DEDUP_FILE", tmp_path / "data" / "notify_dedup.json")
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", _boom)
    monkeypatch.setattr(notify.urllib.request, "urlopen", _boom)
    # TG 配置存在与否决定台账 channels 是否含 telegram 键 → 固定为「未配置」，
    # 消除本机 config/telegram.json 有无带来的环境依赖（B2 用例内单独覆盖为 True）。
    monkeypatch.setattr(notify, "telegram_configured", lambda: False)
    _OUTBOUND_HITS.clear()
    yield
    if request.node.name != "test_A_sandbox_sentinel_effective":
        assert not _OUTBOUND_HITS, "本次用例产生真实外发（哨兵命中），违反零外发铁律"


def _ledger_lines(tmp_path: Path) -> list[dict]:
    p = tmp_path / "data" / "alerts" / "alert_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ───────────────── A. 零外发哨兵正控（§18 L48「先证沙箱判定生效」） ─────────────────
def test_A_sandbox_sentinel_effective(monkeypatch):
    """正控：真实 _send_email_core（配齐 config）必然触发 SMTP_SSL 哨兵 = 沙箱生效。"""
    monkeypatch.setattr(notify, "load_email_config", lambda: {
        "smtp": "smtp.invalid", "port": 465, "user": "u@x", "password": "realpw",
        "to": "t@x"})
    _OUTBOUND_HITS.clear()
    ok = notify._send_email_core("sandbox-probe", "body")
    assert _OUTBOUND_HITS, "哨兵未生效：真实发送链路未被拦截（沙箱无效）"
    assert ok is False, "真实链路被哨兵拦下后应返回 False"


# ───────────────── B. notify 台账打点 ─────────────────
def test_B1_message_level_single_line(tmp_path, monkeypatch):
    """send() 消息级只记 1 条（邮件+飞书都成功也不双记），字段完整。"""
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    notify.send("[告警] 测试消息", "body", severe=True, ledger_key="k1")
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 1, f"消息级应恰好 1 条台账，实得 {len(lines)}"
    rec = lines[0]
    assert rec["key"] == "k1"
    assert rec["tier"] == "critical"
    assert rec["channels"] == {"email": True, "feishu": True}
    assert rec["group"] == "alert"
    assert rec["tree"] == str(tmp_path)


def test_B2_lowlevel_direct_single_channel(tmp_path, monkeypatch):
    """底层直调（旁路出口）：send_feishu / _send_email / send_telegram 各记单渠道 1 条。"""
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_telegram_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "telegram_configured", lambda: True)  # 使 telegram 键入台账
    notify.send_feishu("速递标题", "x", chat_key="report")
    notify._send_email("邮件直调标题", "x")
    notify.send_telegram("TG 直调标题", "x")
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 3, f"三次直调应各记 1 条，实得 {len(lines)}"
    fs = [r for r in lines if r["channels"].get("feishu")]
    em = [r for r in lines if r["channels"].get("email")]
    tg = [r for r in lines if r["channels"].get("telegram")]
    assert len(fs) == 1 and fs[0]["group"] == "report"
    assert len(em) == 1 and em[0]["channels"] == {"email": True, "feishu": False,
                                                  "telegram": False}
    assert len(tg) == 1 and tg[0]["channels"] == {"email": False, "feishu": False,
                                                  "telegram": True}


def test_B3_no_double_count_inside_dispatch(tmp_path, monkeypatch):
    """send() 分发内部底层包装不记账（重入守卫）→ 仍只 1 条消息级。"""
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    notify.send_to("订阅推送", "x", email="a@b.c", chat_id=None)
    notify.send("经 send 分发", "x", severe=False)
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 2, f"send_to + send 各 1 条，不得因底层重复记账，实得 {len(lines)}"


def test_B4_dry_run_no_ledger(tmp_path, monkeypatch):
    """--dry-run 不写台账（同 latest.md 契约）：消息级 + 三个渠道级逐一验证。"""
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_telegram_core", lambda s, b, **k: True)
    notify.send("[告警] dry", "x", severe=True, dry_run=True)
    notify.send_feishu("dry feishu", "x", dry_run=True)
    notify._send_email("dry email", "x", dry_run=True)
    notify.send_telegram("dry tg", "x", dry_run=True)
    assert _ledger_lines(tmp_path) == [], "dry-run 不得写台账（任一入口）"


def test_B5_key_hash_fallback_and_all_failed_not_recorded(tmp_path, monkeypatch):
    """key 无 dedup_key 时回退 subject 哈希；全渠道失败（未实际外发）不记账。"""
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    notify.send("[告警] 无 key 消息", "x", severe=True)
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 1
    assert lines[0]["key"] == notify._ledger_key_of("[告警] 无 key 消息", None)
    # 全渠道失败 → 不记
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: False)
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: False)
    notify.send("[告警] 全失败", "x", severe=True)
    assert len(_ledger_lines(tmp_path)) == 1, "全渠道未发出=未实际外发，不得记账"


# ───────────────── C. 今日真实 20 条样本重放（§18 L49） ─────────────────
# 来源：docs/ops/alert-system-fullchain-audit-20261009.md §4 逐条定性表 + §2/§3 键/源证据。
# 字段=(时间, tier, dedup_key, subject, source, tree)：tree=run(运行树)/signal(信号树)。
REAL_20 = [
    ("2026-10-09 00:22:11", "critical", "r2_upload_trigger_fail",
     "[告警] R2上传异步触发失败(同名 unit 已在跑)", "upload_r2.py", "run"),
    ("2026-10-09 01:12:30", "critical", "deploy_r2_upload_fail",
     "[告警] R2上传失败(etf-hist 停滞被杀)", "deploy.sh", "run"),
    ("2026-10-09 01:45:00", "critical", "schedule_monitor_alert",
     "[告警] 1项计划任务异常", "schedule_monitor.sh", "run"),
    ("2026-10-09 04:30:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 3 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 08:27:00", "critical", "cloud_unit_patrol_drift",
     "[告警] 云上 unit 快照漂移: 3 字段配置差异", "check_failed_units.py", "run"),
    ("2026-10-09 09:31:43", "critical", "nextday_gap_check_fail",
     "[告警] 伪跳空校验失败(东财接口被拒)", "nextday_gap_check.sh", "run"),
    ("2026-10-09 09:31:37", "critical", "nextday_gap_check_gen_fail",
     "[告警] 伪跳空校验未完成", "nextday_gap_check.py", "signal"),
    ("2026-10-09 09:45:00", "critical", "schedule_monitor_alert",
     "[告警] 2项计划任务异常", "schedule_monitor.sh", "run"),
    ("2026-10-09 10:45:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 3 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 10:45:00", "critical", "schedule_monitor_alert",
     "[告警] 1项计划任务异常", "schedule_monitor.sh", "run"),
    ("2026-10-09 13:00:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 3 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 16:30:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 7 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 16:42:00", "critical", "deploy_check_data_integrity_fail",
     "[告警] deploy 数据产物校验失败(fund_nav 领先产物 9 天)", "deploy.sh", "run"),
    ("2026-10-09 16:45:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 7 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 17:00:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 6 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 17:35:00", "critical", "intraday_upload_index_r2_fail",
     "[告警] R2上传失败(upload-index 停滞被杀)", "intraday_snapshot.sh", "run"),
    ("2026-10-09 18:15:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 5 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 18:30:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 4 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 20:15:00", "critical", "failed_units_patrol",
     "[告警] 云上 failed unit 巡检: 2 个未清", "check_failed_units.py", "run"),
    ("2026-10-09 22:00:00", "critical", "schedule_monitor_alert",
     "[告警] 1项计划任务异常", "schedule_monitor.sh", "run"),
]
DAY = "2026-10-09"


def _write_replay(tmp_path: Path) -> tuple[Path, Path]:
    """把 20 条真样本写入两棵树的台账（运行树 19 + 信号树 1），返回两树根。"""
    run = tmp_path / "trade-data"
    sig = tmp_path / "trade-data-signal"
    for t in (run, sig):
        (t / "data" / "alerts").mkdir(parents=True, exist_ok=True)
    run_lines, sig_lines = [], []
    for i, (ts, tier, key, subj, src, tree) in enumerate(REAL_20, 1):
        rec = {"ts": ts, "tree": str(run if tree == "run" else sig), "tier": tier,
               "key": key, "subject": subj, "channels": {"email": True, "feishu": True},
               "source": src, "group": "alert"}
        (run_lines if tree == "run" else sig_lines).append(json.dumps(rec, ensure_ascii=False))
    (run / "data" / "alerts" / "alert_ledger.jsonl").write_text(
        "\n".join(run_lines) + "\n", encoding="utf-8")
    (sig / "data" / "alerts" / "alert_ledger.jsonl").write_text(
        "\n".join(sig_lines) + "\n", encoding="utf-8")
    return run, sig


def test_C_replay_20_real_samples(tmp_path):
    """20 条真样本重放：台账重算 == 人工重建（20 / severe 20 / alert 20）；打印对照表。"""
    run, sig = _write_replay(tmp_path)
    trees = alert_meter.resolve_trees([str(run), str(sig)])
    agg = alert_meter.aggregate(alert_meter.load_day(trees, DAY))

    manual_total = len(REAL_20)
    print(f"\n[对照表] 人工重建 {manual_total} 条 / 台账重算 {agg['total']} 条")
    print(f"  severe(直发) = {alert_meter.severe_count(agg)}   alert 群 = {alert_meter.alert_count(agg)}")
    print(f"  by_source = {agg['by_source']}")
    print(f"  by_key top = {sorted(agg['by_key'].items(), key=lambda x: -x[1])[:5]}")
    for i, (ts, tier, key, subj, src, tree) in enumerate(REAL_20, 1):
        print(f"  #{i:>2} {ts} [{key}] {subj[:34]}  <= {src}({tree})")

    assert agg["total"] == manual_total == 20, "台账重算条数应==人工重建 20 条"
    assert alert_meter.severe_count(agg) == 20, "20 条均为 severe(critical)"
    assert alert_meter.alert_count(agg) == 20, "20 条均落 alert 群"
    # 逐键核对：unit 巡检族 9 条（审计 §2-D3）
    assert agg["by_key"]["failed_units_patrol"] == 9
    assert agg["by_key"]["schedule_monitor_alert"] == 4
    # 双树各含部分样本（运行树 19 + 信号树 1）→ 跨树聚合后是**一个**数字
    assert len(trees) == 2


# ───────────────── D. 日计数幂等 + schema ─────────────────
def test_D_daily_idempotent_and_schema(tmp_path):
    """alert_daily.json 由台账幂等重算：两次逐位一致；schema 合法（含 total/by_*/merged）。"""
    run, sig = _write_replay(tmp_path)
    trees = alert_meter.resolve_trees([str(run), str(sig)])
    d1 = alert_meter.build_daily(trees, DAY)
    d2 = alert_meter.build_daily(trees, DAY)
    assert d1 == d2, "同台账重算两次必须逐位一致（幂等）"
    for k in ("date", "total", "by_tier", "by_source", "by_key", "by_group",
              "merged_in_digest", "trees"):
        assert k in d1, f"daily schema 缺字段 {k}"
    assert d1["date"] == DAY and d1["total"] == 20 and d1["merged_in_digest"] == 0

    # recount 落盘 → 每棵树内容一致（§22），且再次 recount 结果不变
    r1 = alert_meter.recount(trees, DAY)
    body1 = (run / "data" / "alerts" / "alert_daily.json").read_text(encoding="utf-8")
    body_sig = (sig / "data" / "alerts" / "alert_daily.json").read_text(encoding="utf-8")
    assert body1 == body_sig, "两棵树的 alert_daily.json 必须一致（§22）"
    alert_meter.recount(trees, DAY)
    body2 = (run / "data" / "alerts" / "alert_daily.json").read_text(encoding="utf-8")
    assert body1 == body2, "recount 两次输出必须逐位一致（幂等）"
    assert json.loads(body1)["total"] == 20


def test_E_cross_tree_single_number(tmp_path):
    """跨树聚合：样本分落两树，查询面输出单一数字（非「两个数字」）。"""
    run, sig = _write_replay(tmp_path)
    only_run = alert_meter.aggregate(alert_meter.load_day([run], DAY))
    both = alert_meter.aggregate(alert_meter.load_day([run, sig], DAY))
    assert only_run["total"] == 19, "运行树单独 19 条"
    assert both["total"] == 20, "跨两树聚合 = 20（含信号树 1 条）"
    # 信号树独有的 key 只在跨树聚合里出现
    assert "nextday_gap_check_gen_fail" not in only_run["by_key"]
    assert both["by_key"]["nextday_gap_check_gen_fail"] == 1


# ───────────────── F. CLI --trees（os.pathsep 多树）─────────────────
def test_F_cli_trees_pathsep(tmp_path):
    """CLI `--trees a:b` 按 os.pathsep 拆多树（复现脚本踩出的真 bug：整串当单路径）。"""
    run, sig = _write_replay(tmp_path)
    spec = f"{run}{os.pathsep}{sig}"
    rc = alert_meter.main(["--recount", "--date", DAY, "--trees", spec])
    assert rc == 0
    for t in (run, sig):
        f = t / "data" / "alerts" / "alert_daily.json"
        assert f.exists(), f"--trees 多树未生效：{f} 未写"
        assert json.loads(f.read_text(encoding="utf-8"))["total"] == 20
    rc = alert_meter.main(["--today", "--date", DAY, "--trees", spec, "--json"])
    assert rc == 0


# ───────────────── H. 内部旁路 `_alert_feishu_config_missing` ─────────────────
def _stub_feishu_missing(monkeypatch):
    """把「飞书配置缺失但 .env 有凭证」态装齐（触发内部基建告警邮件路径）。"""
    monkeypatch.setattr(notify, "load_feishu_config", lambda: None)
    monkeypatch.setattr(notify, "_load_feishu_credentials", lambda: ("cli_x", "sec"))
    monkeypatch.setattr(notify, "check_dedup", lambda *a, **k: False)
    monkeypatch.setattr(notify, "update_dedup", lambda *a, **k: None)
    monkeypatch.delenv("TRADE_HOST_TAG", raising=False)  # 免 subject 来源标签扰动 key 哈希


def test_H1_config_missing_direct_records_one(tmp_path, monkeypatch):
    """depth==0 直调 `_alert_feishu_config_missing`：走 _send_email 渠道包装 ⇒ 恰好 1 条。"""
    _stub_feishu_missing(monkeypatch)
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    notify._alert_feishu_config_missing()
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 1, f"应恰好 1 条（渠道包装记），实得 {len(lines)}"
    # depth==0 走渠道包装 ⇒ 拿不到 dedup_key，key = subject 哈希（预期口径）
    assert lines[0]["key"] == notify._ledger_key_of(
        "[告警] 飞书配置缺失 feishu.json 已丢失", None)
    assert lines[0]["channels"] == {"email": True, "feishu": False}


def test_H2_config_missing_nested_no_miss_no_double(tmp_path, monkeypatch):
    """嵌套（send 内 feishu cfg 缺失）：外层消息 1 条 + 基建告警补记 1 条 = 2 条，无漏无误。"""
    _stub_feishu_missing(monkeypatch)
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    # 不桩 _send_feishu_core：走真实 core → cfg None → 触发内部基建告警邮件
    notify.send("[告警] 外层主题", "x", severe=True, ledger_key="outer")
    lines = _ledger_lines(tmp_path)
    assert len(lines) == 2, f"应为 2 条（外层 1 + 补记 1），实得 {len(lines)}: {lines}"
    keys = sorted(r["key"] for r in lines)
    assert keys == ["feishu_config_missing", "outer"], f"键不符：{keys}"
    inner = [r for r in lines if r["key"] == "feishu_config_missing"][0]
    outer = [r for r in lines if r["key"] == "outer"][0]
    assert inner["tier"] == "critical" and inner["group"] == "alert"
    assert outer["channels"] == {"email": True, "feishu": False}, "外层只邮件发出"


# ───────────────── G. 回滚开关 ─────────────────
def test_G_kill_switch_no_write(tmp_path, monkeypatch):
    """ALERT_LEDGER_DISABLE=1 = 一键回滚开关：台账零写入（发送行为不变）。"""
    monkeypatch.setattr(notify, "_send_email_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "_send_feishu_core", lambda s, b, **k: True)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    monkeypatch.setenv("ALERT_LEDGER_DISABLE", "1")
    notify.send("[告警] 开关测试", "x", severe=True, ledger_key="ks")
    assert _ledger_lines(tmp_path) == [], "ALERT_LEDGER_DISABLE=1 时不得写台账"