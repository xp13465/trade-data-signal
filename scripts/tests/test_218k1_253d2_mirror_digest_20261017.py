# -*- coding: utf-8 -*-
"""#218-⑥-K1 非 severe 镜像 latest.md + #253-d2 digest 幂等计数留痕 —— 自验(2026-10-17)。

被测面(scripts/notify.py, 均为「不动发送行为/不动 dedup 语义的留痕增强」):
  · 改1 #218-⑥-K1:send() 告警群消息镜像面由「仅 severe」扩到「severe + 非 severe
    (notice/warning/digest/recovery)」;两级**各自独立容量**(severe 50 / 非 severe 30),
    非 severe 再多也不挤掉 severe 流水;条目级别标记走闭合集。
    → `_mirror_latest_entry` / `_latest_entry_level` / `_parse_latest` / `_compose_latest`
      / `_latest_severe_ref` / write_alert 覆盖保留。
  · 改2 #253-d2:`_absorb_to_digest` 幂等命中时 `_bump_digest_hits` 给旧行 hits+1 并记
    hits_ts(最近时刻);flush 渲染成 `xN(最近 HH:MM)`;旧行无 hits 字段按 1 计;
    L2 超预算路径 / CLI defer_digest 也已传 bump_hits=True(原仅件E 路径传 ⇒ #253 无痕)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):本文件全部用例
  **本次自测未产生任何真实外发** —— 渠道函数(send_feishu / _send_email / send_telegram)
  在 fixture 内整体打桩为「只记录、返回 True」的假函数, 外层再套 ZeroOutboundTrap 包裹
  最底层 urllib/smtplib 出口;收尾断言 `trap.hits == []` 即「全程零真实外发」。
  所有落盘面(台账/buffer/state/latest)全指向 tmp_path, 绝不碰生产 data/alerts/。

时敏(§18 L51):涉「当日/今日」的用例一律用**运行时 now() 动态推导**(不写死日期
  字面量);「前日 stale」用例用 now()-1day 动态构造 ⇒ 隔天仍绿。

跑法: python3 -m pytest -q scripts/tests/test_218k1_253d2_mirror_digest_20261017.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#240/#245)
_MIN_ASSERTIONS = 45
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
               "ALERT_BUDGET_TASK_FAMILY", "ALERT_DOMAIN_DISABLE",
               "ALERT_NOTICE_BUDGET_DISABLE"):
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
    # 2026-10-17 补齐既存隔离缝(对齐 a182abf73 先例): 上列 10 个常量漏了 2 个锁常量, 它们
    # 同为 **import 期**由 ALERTS_DIR 派生(notify.py:319)⇒ `_dedup_state_lock()` /
    # buffer flush 的 `open(...,"a+")` 会 build 到**真实工作树** data/alerts/(用例全绿=假绿)。
    monkeypatch.setattr(notify, "WARNING_DEDUP_LOCK_FILE", alerts / "warning_dedup.lock")
    monkeypatch.setattr(notify, "WARNING_FLUSH_LOCK_FILE", alerts / "warning_buffer.flushlock")
    _leak = [n for n in ("ALERTS_FILE", "WARNING_BUFFER_FILE", "INFO_LOG_FILE",
                         "WARNING_FLUSH_LOCK_FILE", "WARNING_DEDUP_STATE_FILE",
                         "WARNING_DEDUP_LOCK_FILE", "DEDUP_FILE", "ALERT_DIGEST_FILE",
                         "ALERT_DIGEST_LOCK_FILE", "ALERT_DIGEST_STATE_FILE")
             if tmp_path not in Path(getattr(notify, n)).parents]
    assert not _leak, f"隔离缝破损: notify 落盘面泄漏到真实树 {_leak} ⇒ 会污染生产 data/alerts/"

    sent: list[dict] = []   # 记录每次「渠道」调用(证明零外发 + 便于取摘要正文)

    def _fake(kind):
        def _f(*_a, **_k):
            sent.append({"channel": kind, "args": _a, "kwargs": _k})
            return True
        return _f

    monkeypatch.setattr(notify, "_send_email", _fake("email"))
    monkeypatch.setattr(notify, "send_telegram", _fake("telegram"))
    monkeypatch.setattr(notify, "send_feishu", _fake("feishu"))

    with ZeroOutboundTrap() as trap:
        yield {"tmp": tmp_path, "alerts": alerts, "sent": sent, "trap": trap}
    # 收尾:零真实外发(§18 L48)
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


def _digest_recs(alerts_dir: Path) -> list[dict]:
    return [json.loads(l) for l in _digest_lines(alerts_dir)]


def _seed_digest(alerts_dir: Path, recs: list[dict]) -> None:
    p = alerts_dir / "alert_digest.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _latest_entries() -> list[str]:
    if not notify.ALERTS_FILE.exists():
        return []
    content = notify.ALERTS_FILE.read_text(encoding="utf-8")
    _head, entries = notify._parse_latest(content)
    return entries


# ══════════════════════════════ 改1:非 severe 也进 latest.md ══════════════════════════════
def test_k1_nonsevere_alert_group_mirrored(_iso):
    """非 severe 告警群消息 ⇒ latest.md 出现 `## [notice]` 条目(旁路不再沉默)。"""
    notify.send("standalone_stale 巡检异常", "详情 A", severe=False,
                feishu_group="alert", ledger_tier="notice", source="watchdog.sh")
    entries = _latest_entries()
    _chk(any(e.strip().startswith("## [notice]") for e in entries),
         "非 severe 告警群消息未镜像到 latest.md(#218-⑥-K1 未生效)")
    e = [x for x in entries if x.strip().startswith("## [notice]")][0]
    _chk("- **级别**: notice" in e, "条目缺级别标注")
    _chk("standalone_stale 巡检异常" in e, "条目缺主题")
    _chk("- **摘要**: 详情 A" in e, "条目缺摘要")
    _chk("- **来源**: watchdog.sh" in e, "条目来源应为显式 source")
    _chk("已镜像登记" not in e, "镜像 stderr 串不应进条目正文")


def test_k1_severe_format_unchanged_and_region_intact(_iso):
    """severe 条目格式逐字同构(供现有消费方);非 severe 加入后 severe 区仍保留。"""
    notify.send("严重告警 X", "body X", severe=True, feishu_group="alert",
                ledger_tier="critical", source="pipe.sh")
    notify.send("普通告警 Y", "body Y", severe=False, feishu_group="alert",
                ledger_tier="notice", source="pipe.sh")
    entries = _latest_entries()
    sev = [e.strip() for e in entries if e.strip().startswith("## [severe]")]
    _chk(len(sev) == 1, f"severe 条目数应仍为 1, 实 {len(sev)}")
    _chk(re.match(r"## \[severe\] \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} · 严重告警 X", sev[0]),
         f"severe 条目格式漂移(旧消费方依赖): {sev[0][:60]!r}")
    _chk("- **级别**: severe" in sev[0], "severe 条目级别行缺失")
    # 顺序:severe 段在前, 非 severe 段在后(独立区段)
    _chk(notify._latest_entry_level(entries[0]) == "severe",
         "severe 应在流水区最前(独立段)")
    _chk(sum(1 for e in entries if notify._latest_entry_level(e) == "notice") == 1,
         "非 severe 段应含 1 条 notice")
    # _latest_severe_ref 仍取到 severe(非 severe 不干扰)
    _chk("严重告警 X" in notify._latest_severe_ref(entries),
         "_latest_severe_ref 应仍命中 severe 条目")


def test_k1_bracket_alert_prefix_autoresolve_mirrored(_iso):
    """无显式 feishu_group 时, `[告警]` 前缀自动路由 alert ⇒ 也镜像。"""
    notify.send("[告警] 管道告警 Z", "body Z")  # 无 feishu_group, 靠前缀解析
    entries = _latest_entries()
    _chk(len(entries) == 1, f"应恰好 1 条镜像, 实 {len(entries)}")
    _chk(entries[0].strip().startswith("## [notice]"),
         "ledger_tier 缺省时应回落 notice 标记")


def test_k1_report_group_and_agent_done_not_mirrored(_iso):
    """业务报告群(report)/完成通知(agent_done)非告警 ⇒ 不镜像(旧行为不变)。"""
    notify.send("买卖点信号", "body", severe=False, feishu_group="report")
    notify.send("[完成] 备份完成", "body", severe=False, feishu_group="agent_done")
    _chk(_latest_entries() == [], "report/agent_done 群消息不应进 latest.md 告警流水")


def test_k1_dry_run_writes_nothing(_iso):
    """dry_run 冒烟只读不落盘(与 write_alert / 旧 _mirror_severe 同口径)。"""
    notify.send("告警 dry", "body", severe=False, dry_run=True, feishu_group="alert")
    notify.send("告警 dry sev", "body", severe=True, dry_run=True, feishu_group="alert")
    _chk(not notify.ALERTS_FILE.exists(), "dry_run 不应创建/写入 latest.md")


def test_k1_per_level_cap_isolation(_iso):
    """1 条 severe + 40 条非 severe ⇒ severe 保留、非 severe 截到 30(互不挤占)。"""
    notify._mirror_latest_entry("severe", "SEV-ONLY", "b")
    for i in range(40):
        notify._mirror_latest_entry("notice", f"N-{i}", "b")
    entries = _latest_entries()
    _chk(notify._LATEST_MAX_NONSEVERE == 30, "非 severe 容量常量应为 30")
    _chk(notify._LATEST_MAX_ENTRIES == 50, "severe 容量常量应保持 50")
    sev = [e for e in entries if notify._latest_entry_level(e) == "severe"]
    oth = [e for e in entries if notify._latest_entry_level(e) == "notice"]
    _chk(len(sev) == 1, f"severe 应保留 1 条(不被非 severe 挤掉), 实 {len(sev)}")
    _chk(len(oth) == 30, f"非 severe 应截到 30, 实 {len(oth)}")
    _chk(any("SEV-ONLY" in e for e in sev), "severe 应仍是 SEV-ONLY")
    _chk(any("N-39" in e for e in oth), "非 severe 应保留最新 N-39")
    _chk(not any("N-0" in e for e in oth), "非 severe 应丢最旧 N-0")


def test_k1_zero_capacity_drops_level_not_keeps_all(_iso, monkeypatch):
    """S1(复查建议):容量 0 必须=该级**不保留**,而非 `x[-0:]` 的"不截断"陷阱。

    旧写法 `sev[-_LATEST_MAX_ENTRIES:]` 在常量=0 时等价 `sev[0:]` ⇒ 留全量,
    与"容量 0"直觉相反(复查 §6 S1 变异测 cap=0 实测不红即此因)。本用例=判别力门。
    """
    head = "# head\n"
    entries3 = [f"## [severe] 2026-01-0{i} 00:00:00 · S{i}\n- **摘要**: s"
                for i in range(1, 4)]
    monkeypatch.setattr(notify, "_LATEST_MAX_ENTRIES", 0)
    _h, kept = notify._parse_latest(notify._compose_latest(head, entries3))
    _chk(len(kept) == 0, f"severe 容量 0 应丢全部(非留全量), 实 {len(kept)}")

    entries3n = [f"## [notice] 2026-01-0{i} 00:00:00 · N{i}\n- **摘要**: s"
                 for i in range(1, 4)]
    monkeypatch.setattr(notify, "_LATEST_MAX_NONSEVERE", 0)
    _h2, kept2 = notify._parse_latest(notify._compose_latest(head, entries3n))
    _chk(len(kept2) == 0, f"非 severe 容量 0 应丢全部(非留全量), 实 {len(kept2)}")


def test_k1_write_alert_preserves_both_levels(_iso):
    """--alert-issue 覆盖头部区时, severe + 非 severe 流水条目都原样保留。"""
    notify._mirror_latest_entry("severe", "S1", "b")
    notify._mirror_latest_entry("notice", "N1", "b")
    notify.write_alert("测试问题", "测试详情")
    content = notify.ALERTS_FILE.read_text(encoding="utf-8")
    _head, entries = notify._parse_latest(content)
    _chk("测试问题" in _head, "头部区应含新问题")
    _chk("- **最近一次 SEVERE**：" in _head, "头部应保留最近 SEVERE 引用")
    levels = [notify._latest_entry_level(e) for e in entries]
    _chk("severe" in levels and "notice" in levels,
         f"覆盖后两级流水都应保留, 实 {levels}")


def test_k1_parse_compose_roundtrip_idempotent(_iso):
    """_compose_latest 与 _parse_latest 互逆(两次 compose 结果一致)。"""
    body = ("# head\n\n> note\n\n"
            "---\n## [severe] 2026-01-02 03:04:05 · S\n- **摘要**: s\n\n"
            "---\n## [notice] 2026-01-02 03:05:05 · N\n- **摘要**: n\n")
    head1, entries1 = notify._parse_latest(body)
    out1 = notify._compose_latest(head1, entries1)
    head2, entries2 = notify._parse_latest(out1)
    out2 = notify._compose_latest(head2, entries2)
    _chk(out1 == out2, "compose→parse→compose 应幂等")
    _chk(len(entries2) == 2, f"应识别 2 条条目, 实 {len(entries2)}")


def test_k1_level_splitter_only_matches_closed_set(_iso):
    """正文里偶然出现的 `---\\n## [x]`(x∉闭合集)不被当条目(防正文吞条目)。"""
    body = ("# head\n\n---\n## [severe] 2026-01-02 03:04:05 · S\n- **摘要**: s\n\n"
            "---\n## [任意标题] 正文里的伪条目\n随便\n")
    head, entries = notify._parse_latest(body)
    _chk(len(entries) == 1, f"非闭合集级别不应被当条目, 实 {len(entries)}")
    _chk(notify._latest_entry_level(entries[0]) == "severe",
         "唯一被识别的条目应是 severe")
    _chk("任意标题" in (entries[0] + head), "伪条目文本应作为正文保留(未被切走)")


def test_k1_latest_severe_ref_ignores_nonsevere(_iso):
    """只有非 severe 条目时 _latest_severe_ref 返回空(不误当 severe)。"""
    entries = ["## [notice] 2026-01-01 00:00:00 · N\n- **摘要**: n"]
    _chk(notify._latest_severe_ref(entries) == "", "非 severe 不应被当 severe 引用")
    entries2 = ["## [notice] 2026-01-01 00:00:00 · N\n- **摘要**: n",
                "## [severe] 2026-01-01 01:00:00 · S\n- **摘要**: s"]
    _chk("S" in notify._latest_severe_ref(entries2), "有 severe 时应取 severe")


def test_k1_invalid_level_falls_back_to_notice(_iso):
    """越界级别退回落 notice(防条目标记不被识别致条目被吞)。"""
    notify._mirror_latest_entry("bogus", "B", "b")
    entries = _latest_entries()
    _chk(len(entries) == 1 and notify._latest_entry_level(entries[0]) == "notice",
         "越界级别应回落 notice")


# ══════════════════════════════ 改2:digest 幂等计数留痕 ══════════════════════════════
def test_d2_same_day_same_key_second_absorb_counts(_iso):
    """同日同 key 二次 absorb ⇒ 仍 1 行, hits=2, hits_ts 已更新(不新增行)。"""
    a = _iso["alerts"]
    ok1 = notify._absorb_to_digest("r2 不可达", "b", key="r2_unreachable",
                                   category="r2", source="s", bump_hits=True)
    ok2 = notify._absorb_to_digest("r2 不可达", "b", key="r2_unreachable",
                                   category="r2", source="s", bump_hits=True)
    _chk(ok1 and ok2, "两次 absorb 都应返回 True")
    recs = _digest_recs(a)
    _chk(len(recs) == 1, f"同日同 key 应仍 1 行, 实 {len(recs)}")
    _chk(int(recs[0].get("hits")) == 2, f"hits 应为 2, 实 {recs[0].get('hits')}")
    _chk(str(recs[0].get("hits_ts", "")).startswith(_today()),
         f"hits_ts 应为当日时刻, 实 {recs[0].get('hits_ts')!r}")
    _chk(str(recs[0].get("hits_ts", "")).count(":") == 2, "hits_ts 应为 HH:MM:SS 格式")


def test_d2_bump_hits_false_keeps_silent_noop(_iso):
    """bump_hits=False(默认)时幂等命中不计数(参数语义保持, 未破坏)。"""
    a = _iso["alerts"]
    notify._absorb_to_digest("k", "b", key="dup_key", category="r2")
    notify._absorb_to_digest("k", "b", key="dup_key", category="r2")  # 默认 False
    recs = _digest_recs(a)
    _chk(len(recs) == 1, "应仍 1 行")
    _chk(int(recs[0].get("hits") or 1) == 1, "bump_hits=False 时不应累加计数")


def test_d2_old_row_without_hits_field_counts_as_one(_iso):
    """旧行无 hits/hits_ts 字段 ⇒ 按 1 计, 命中后变 2(向后兼容)。"""
    a = _iso["alerts"]
    _seed_digest(a, [{"ts": f"{_today()} 08:00:00", "rid": "dold", "day": _today(),
                      "key": "legacy_key", "category": "r2", "subject": "旧行",
                      "body": "b", "from_prefix": None, "source": "s",
                      "reason": "over_budget"}])  # 注意:无 hits / hits_ts 字段
    notify._absorb_to_digest("旧行", "b", key="legacy_key", category="r2", bump_hits=True)
    recs = _digest_recs(a)
    _chk(len(recs) == 1, "旧行应被复用(不新增)")
    _chk(int(recs[0].get("hits")) == 2, f"旧行无 hits 应按 1+1=2, 实 {recs[0].get('hits')}")
    _chk(recs[0].get("hits_ts"), "旧行被命中后应补 hits_ts")


def test_d2_l2_over_budget_path_bumps_hits(_iso):
    """#253 场景:L2 超预算并入路径(经 send)第二次命中 ⇒ 计数留痕(原缺 bump_hits)。"""
    a = _iso["alerts"]
    _seed_ledger(a, [_ledger_row("r2_unreachable", "r2 不可达")])  # 当日已直发 1 条 ⇒ 额度满
    r1 = notify.send("r2 不可达", "b1", severe=True, ledger_key="r2_unreachable",
                     source="pipe.sh")
    r2 = notify.send("r2 不可达", "b2", severe=True, ledger_key="r2_unreachable",
                     source="pipe.sh")
    _chk(r1.get("digested") is True and r2.get("digested") is True,
         f"两次都应并入摘要(额度满+同签名), 实 {r1} / {r2}")
    recs = _digest_recs(a)
    _chk(len(recs) == 1, f"应仍 1 行, 实 {len(recs)}")
    _chk(int(recs[0].get("hits")) == 2,
         f"L2 超预算路径也应累加 hits(=2), 实 {recs[0].get('hits')}")
    _chk(recs[0].get("hits_ts"), "L2 路径命中后应有 hits_ts")


def test_d2_flush_renders_recent_hm(_iso):
    """flush 摘要把 hits>1 的行渲染成 `xN(最近 HH:MM)`(仍 1 行)。"""
    a = _iso["alerts"]
    yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _seed_digest(a, [{"ts": f"{yday} 18:24:00", "rid": "d1", "day": yday,
                      "key": "r2_unreachable", "category": "r2", "subject": "r2 不可达",
                      "body": "b", "from_prefix": None, "source": "pipe.sh",
                      "reason": "over_budget", "hits": 2, "hits_ts": f"{yday} 21:16:00"}])
    res = notify.flush_digest(dry_run=False)  # stale(前日) ⇒ 必触发
    _chk(res.get("sent") is True, f"stale 条目应触发 flush, 实 {res}")
    bodies = [s["args"][1] for s in _iso["sent"] if len(s["args"]) >= 2]
    _chk(any("x2(最近 21:16)" in b for b in bodies),
         f"摘要正文应含 `x2(最近 21:16)`, 实 {bodies[:1]}")


def test_d2_old_row_flush_no_ts_renders_plain_x(_iso):
    """hits>1 但无 hits_ts(旧行) ⇒ 只渲染 `xN`, 不带时刻;不崩。"""
    a = _iso["alerts"]
    yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _seed_digest(a, [{"ts": f"{yday} 18:24:00", "rid": "d2", "day": yday,
                      "key": "k", "category": "r2", "subject": "旧重复",
                      "body": "b", "from_prefix": None, "source": "pipe.sh",
                      "reason": "over_budget", "hits": 3}])  # 无 hits_ts
    res = notify.flush_digest(dry_run=False)
    _chk(res.get("sent") is True, f"应触发 flush, 实 {res}")
    bodies = [s["args"][1] for s in _iso["sent"] if len(s["args"]) >= 2]
    _chk(any("x3" in b for b in bodies) and not any("x3(最近" in b for b in bodies),
         "旧行(无 hits_ts) 应渲染 x3 但不带时刻")
    # 顺带:digest 消息自身(alert 群)也应在 latest.md 留痕(改1 覆盖)
    _chk(any(e.strip().startswith("## [digest]") for e in _latest_entries()),
         "摘要消息自身应镜像为 `## [digest]`")


# ══════════════════════════ 断言总数下限(防假绿) ══════════════════════════
def test_zz_min_assertions(_iso):
    _chk(_N[0] >= _MIN_ASSERTIONS,
         f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}(疑收集/执行异常)")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))