# -*- coding: utf-8 -*-
"""#264 包2 件C(故障域聚合层)+ 件E(预算+摘要层扩容)—— 正/负控自验(2026-10-15)。

权威依据:
  · docs/ops/alert-noise-rca-20261015.md §1.4(10-15 单日解剖)/§4.0(业界对照)/
    §4.1 C + E(三件套: 依据 / 预期 / 证据用例)/§4.2。
  · docs/ops/alert-convergence-plan-20261010.md L10 降噪铁律 + §5 不变式。

被测面:
  · `scripts/alert_denoise_rules.py`: domain_of / domain_inhibit_judge /
    domain_aggregate_summary / ledger_day_notice_index / rollover_absorb_judge / rollover_prune。
  · `scripts/notify.py`: send() 域 gate(C)+ 非 critical 重复类 gate(E)+ 恢复留痕;
    _absorb_to_digest(reason/domain/mark_seen/bump_hits); _flush_digest_locked 渲染。
  · `scripts/notify_sent.py`: 新并入行登记(三态判别不许把「已并入」判成 failed)。

零外发铁律(§18 L48 / memory notify-script-selftest-must-stub):
  本文件全部用例**本次自测零真实外发** —— 渠道函数(_send_email/send_telegram/send_feishu)
  在 fixture 内整体打桩为「只记录、返回 True」的假函数, 外层套 ZeroOutboundTrap 包裹最底层
  urllib/smtplib 出口; 收尾断言 trap.hits == []。另有**沙箱生效正控**(test_00)证明本陷阱
  真能抓住未打桩的出口(不是「因为没跑才没外发」的假绿, §18 L49)。
  所有落盘面(台账/buffer/state/dedup/域名状态/rollover 记忆)全指向 tmp_path, 绝不碰生产
  data/alerts/。

时敏铁律(§18 L51 / memory tests-freeze-today-must-inject):
  被测代码内部取 `datetime.now()`(域静默窗判定/台账按日过滤/buffer 按日归档), 故本文件
  **一律用虚拟时钟注入**(`_patch_clock`: 同时替换 notify.datetime 与 adr.datetime 的 now()),
  不写死「今天」; 重放用例固定跑 2026-10-15 虚拟日 ⇒ 明天/后天跑结果**一致**(CI 不跨天红)。

跑法: python3 -m pytest -q scripts/tests/test_264_alert_domain_budget_20261015.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent))
from _zero_outbound import ZeroOutboundTrap  # noqa: E402

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import notify  # noqa: E402
import alert_denoise_rules as adr  # noqa: E402
from notify_sent import notify_state  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPTS = ROOT / "scripts"
FIXTURE = Path(__file__).absolute().parent / "fixtures" / "alert_264_ledger_20261015.jsonl"

# 断言计数下限(防收集/执行异常致「0 断言假绿」, §18 L49 / 仿 #201/#193/#240/#245)
_MIN_ASSERTIONS = 70
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ══════════════════════════ 虚拟时钟 + 隔离 fixture ══════════════════════════
class _Clock:
    """可推进的虚拟时钟(重放用: 每行告警把时钟推到该行的 ts)。"""

    def __init__(self, dtv: datetime):
        self.dtv = dtv

    def set(self, dtv: datetime) -> None:
        self.dtv = dtv


def _patch_clock(monkeypatch, clock: _Clock) -> None:
    """替换 notify.datetime / adr.datetime 的 now() 为虚拟时钟(其余语义保持 datetime)。"""
    for _m in (notify, adr):
        class _DT(datetime):  # noqa: N801
            @classmethod
            def now(cls, tz=None):
                return clock.dtv
        monkeypatch.setattr(_m, "datetime", _DT)


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("REPO", str(tmp_path))
    for _v in ("NOTIFY_SOURCE", "ALERT_BUDGET_DISABLE", "ALERT_DIGEST_DISABLE",
               "ALERT_DOMAIN_DISABLE", "ALERT_NOTICE_BUDGET_DISABLE",
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
        yield {"tmp": tmp_path, "alerts": alerts, "calls": calls, "trap": trap,
               "sends": calls}
    assert trap.hits == [], f"零外发被破坏(§18 L48): {trap.hits}"


def _domain_state(alerts_dir: Path) -> dict:
    p = alerts_dir / "alert_domains.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _digest_rows(alerts_dir: Path) -> list[dict]:
    p = alerts_dir / "alert_digest.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _seed_ledger(alerts_dir: Path, rows: list[dict]) -> None:
    p = alerts_dir / "alert_ledger.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _ledger_row(key, subject, *, ts="2026-10-15 09:00:00", group="alert", tier="critical"):
    return {"ts": ts, "group": group, "tier": tier, "key": key, "subject": subject}


def _load_fixture() -> list[dict]:
    return [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines() if l.strip()]


# ══════════════════════ ⓪ 沙箱生效正控(§18 L48 前置) ══════════════════════
def test_00_zero_outbound_trap_really_works():
    """正控: 未打桩时出口真会被抓 ⇒ trap 判定有效(防「没跑=零外发」假绿)。"""
    hit = False
    with ZeroOutboundTrap() as trap:
        try:
            urllib.request.urlopen("http://127.0.0.1:1/never")  # 打桩后不会真联
        except AssertionError:
            hit = True
    _chk(hit, "陷阱未抓到未打桩的 urlopen ⇒ 本文件零外发断言无判别力")
    _chk(len(trap.hits) == 1, f"陷阱应记 1 次命中, 得 {trap.hits}")


# ══════════════════════ ① 件C 域表(真实 10-15 样本表驱动) ══════════════════════
# (key, subject, 期望域) —— 全部取自 10-15 台账真实行(§1.4 事件域表)
DOMAIN_CASES = [
    ("deploy_check_data_integrity_fail", "[告警] deploy 数据产物校验失败", "r2_deploy"),
    (None, "[告警] R2 上传失败: data-files 通道(0/71)", "r2_deploy"),
    (None, "[告警] R2 上传失败: kelly-snapshots 通道(0/3)", "r2_deploy"),
    ("schedule_stats_r2_fail", "[告警] schedule_stats R2上传失败 10-15 18:32", "r2_deploy"),
    ("update_lab_r2_upload_fail", "[告警] update_lab R2上传失败 10-15 19:16", "r2_deploy"),
    ("update_lab_tradesim_r2_fail", "[告警] update_lab trade_sim R2上传失败", "r2_deploy"),
    ("update_all_severe:update_all", "[告警] update_all 严重告警：统一deploy失败(1)", "r2_deploy"),
    ("turnover_backfill_fail", "[告警] turnover 独立任务链路异常 pipe=0 export=0 r2=1 r2large=124", "r2_deploy"),
    ("nextday_plan_fail", "[告警] 次日买入计划 R2 上传失败 rc=1 20261015", "r2_deploy"),
    (None, "[告警] update_all 锁跳过 10-15 20:07", "r2_deploy"),
    (None, "[告警] 1项计划任务异常 10-15 18:45", "r2_deploy"),
    (None, "[告警] §22 三站一致性校验失败(连续 2 天, 升级 critical)", "r2_deploy"),
    ("s06_snapshot_fail", "[S06] 快照重生链路异常 EXIT rc=124 gen=0 check=0 r2=124 pr=0 pr_r2=1", "r2_deploy"),
    (None, "[S06] 快照重生链路异常 EXIT rc=1 gen=1 check=1", "snapshot"),
    (None, "[告警][数据缺口] 交易记录缺 7 条冻结/评级缺失 10-15 22:35", "data_gap"),
    (None, "[告警][数据缺口] 最近 deploy(deploy_20261015_2152.log)无成功标记, kelly 产物可能未刷新", "data_gap"),
    ("4cdbff00234e", "[告警] 信号凯利回测指标突变(C/D/K)", "kelly"),
    ("73ad3acf51d2", "[告警] 云上 failed unit 持续未清(连续 8 天, 升级 critical)", "unit"),
    # 不聚合族(宁漏不误并 / 机制自身绝不入聚合)
    ("history_overwrite:index_daily:20261015", "[历史行改写] index_daily 历史行被重写 1 条(值改写1)", None),
    ("history_overwrite:signal_daily:20261015", "[历史行改写] signal_daily 历史行被重写 997 条", None),
    (None, "[告警·聚合] 1条 warning 汇总 10-15 21:45", None),
    (None, "[恢复] fetch_news ⚠ [fetch_news] R2 上传 rc 10-15 20:15", "r2_deploy"),
    (None, "普通通知: 站点已更新", None),
]


@pytest.mark.parametrize("key,subject,expect", DOMAIN_CASES)
def test_01a_domain_of_table(key, subject, expect):
    """域表对真实 10-15 样本逐条命中(表驱动; 与 category 预算类别正交)。"""
    _chk(adr.domain_of(key, subject) == expect,
         f"domain_of({key!r},{subject[:30]!r}) 期望 {expect} 得 {adr.domain_of(key, subject)}")


def test_01b_domain_labels_cover_all_rules():
    """每个可能的域都有中文标签(摘要正文用; 防域出现却显示英文标识)。"""
    for _d in ("r2_deploy", "snapshot", "unit", "data_gap", "gap_check", "kelly",
               "fund_nav", "collect"):
        _chk(_d in adr.DOMAIN_LABELS, f"域 {_d} 缺中文标签")


def test_01c_domain_inhibit_judge_semantics():
    """域静默窗判定: 无历史/跨日/窗外 ⇒ first; 窗内 ⇒ absorb; 状态条目计数累加。"""
    t0 = datetime(2026, 10, 15, 18, 25, 19)
    a, e = adr.domain_inhibit_judge({}, "r2_deploy", t0)
    _chk(a == "first" and e["n_direct"] == 1 and e["n_absorbed"] == 0,
         f"无历史应 first, 得 {a}/{e}")
    _chk(e["last_ts"] == "2026-10-15 18:25:19" and e["last_day"] == "2026-10-15",
         f"状态条目时间字段不对: {e}")
    _chk(e["interval"] == adr.ALERT_DOMAIN_GROUP_INTERVAL, f"窗口应记录, 得 {e}")
    st = {"r2_deploy": e}
    a2, e2 = adr.domain_inhibit_judge(st, "r2_deploy", t0 + timedelta(minutes=5))
    _chk(a2 == "absorb" and e2["n_absorbed"] == 1 and e2["n_direct"] == 1,
         f"窗内应 absorb 且计数累加, 得 {a2}/{e2}")
    # 恰好 2h 边界 ⇒ 视为新事件(>= 窗口)
    a3, _ = adr.domain_inhibit_judge({"r2_deploy": e}, "r2_deploy", t0 + timedelta(hours=2))
    _chk(a3 == "first", f"=2h 边界应 first, 得 {a3}")
    # 窗内但跨自然日 ⇒ 次日首条必直发
    a4, e4 = adr.domain_inhibit_judge({"r2_deploy": e}, "r2_deploy",
                                      datetime(2026, 10, 16, 0, 5, 0))
    _chk(a4 == "first" and e4["last_day"] == "2026-10-16", f"跨日首条应 first, 得 {a4}/{e4}")
    # 坏时间戳 → 当无历史(fail-open 直发)
    a5, _ = adr.domain_inhibit_judge({"r2_deploy": {"last_ts": "garbage"}}, "r2_deploy", t0)
    _chk(a5 == "first", f"坏状态应 first(fail-open), 得 {a5}")
    # 域开关值可配
    a6, e6 = adr.domain_inhibit_judge({}, "unit", t0, interval_seconds=60)
    _chk(a6 == "first" and e6["interval"] == 60, f"窗口可配, 得 {e6}")


def test_01e_domain_window_is_two_hours(_iso):
    """域静默窗口径钉死 = 2h(RCA 建议 group_interval): 119min 内并 / 121min 外直发。

    判别力: 窗口被改成任何 <119min 的值(如 1h) ⇒ 119min 那条变 first ⇒ 本用例变红。"""
    _chk(adr.ALERT_DOMAIN_GROUP_INTERVAL == 7200, "默认窗口必须是 7200s(2h)")
    t0 = datetime(2026, 10, 15, 18, 25, 19)
    _, e = adr.domain_inhibit_judge({}, "r2_deploy", t0)
    a_in, _ = adr.domain_inhibit_judge({"r2_deploy": e}, "r2_deploy", t0 + timedelta(minutes=119))
    a_out, _ = adr.domain_inhibit_judge({"r2_deploy": e}, "r2_deploy", t0 + timedelta(minutes=121))
    _chk(a_in == "absorb", f"119min(<2h)应并, 得 {a_in}")
    _chk(a_out == "first", f"121min(>2h)应直发, 得 {a_out}")


def test_01d_domain_aggregate_summary():
    """摘要域汇总: 条数 + 来源脚本去重清单 + 首条时刻(C-③ 判别维度保留)。"""
    g = adr.domain_aggregate_summary([
        {"domain": "r2_deploy", "source": "update_lab", "ts": "2026-10-15 18:28:03", "key": "k1"},
        {"domain": "r2_deploy", "source": "update_lab", "ts": "2026-10-15 19:16:13", "key": "k2"},
        {"domain": "r2_deploy", "source": "schedule_stats", "ts": "2026-10-15 19:43:39", "key": "k3"},
        {"domain": "", "source": "x", "ts": "2026-10-15 20:00:00", "key": "k4"},
    ])
    _chk(g["r2_deploy"]["n"] == 3, f"域内应 3 条, 得 {g}")
    _chk(g["r2_deploy"]["sources"] == ["update_lab", "schedule_stats"],
         f"来源脚本应去重, 得 {g['r2_deploy']['sources']}")
    _chk(g["r2_deploy"]["first_hm"] == "18:28" and g["r2_deploy"]["first_key"] == "k1",
         f"首条信息不对, 得 {g['r2_deploy']}")
    _chk(len(g) == 1, f"无域条目不应进汇总, 得 {list(g)}")


# ══════════════════════ ② 件C 域 gate(send 真实路径) ══════════════════════
def test_02a_first_of_domain_goes_direct_and_marks_window(_iso, monkeypatch):
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    r = notify.send("[告警] deploy 数据产物校验失败", "正文",
                    severe=True, ledger_key="deploy_check_data_integrity_fail")
    _chk(r.get("email") is True and not r.get("digested"), f"域首条应直发, 得 {r}")
    st = _domain_state(_iso["alerts"])
    _chk(st.get("r2_deploy", {}).get("n_direct") == 1, f"域首条应占窗, 得 {st}")
    _chk(_digest_rows(_iso["alerts"]) == [], "首条不得进摘要")


def test_02b_same_domain_within_window_absorbed(_iso, monkeypatch):
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] deploy 数据产物校验失败", "b1", severe=True,
                ledger_key="deploy_check_data_integrity_fail")
    n_calls = len(_iso["calls"])
    clk.set(datetime(2026, 10, 15, 18, 28, 3))
    r = notify.send("[告警] R2 上传失败: data-files 通道(0/71)", "b2", severe=True,
                    ledger_key="e516c06e9ff7", source="schedule_stats")
    _chk(r.get("digested") is True, f"同域窗内应并入摘要, 得 {r}")
    _chk(len(_iso["calls"]) == n_calls, "并入不得产生任何渠道外发")
    rows = _digest_rows(_iso["alerts"])
    _chk(len(rows) == 1, f"应写 1 行摘要条目, 得 {rows}")
    _chk(rows[0]["domain"] == "r2_deploy"
         and rows[0]["reason"] == adr.DOMAIN_ABSORB_REASON
         and rows[0]["source"] == "schedule_stats", f"条目字段应齐, 得 {rows[0]}")
    st = _domain_state(_iso["alerts"])
    _chk(st["r2_deploy"]["n_absorbed"] == 1 and st["r2_deploy"]["n_direct"] == 1,
         f"域状态计数应累加, 得 {st}")


def test_02c_outside_window_direct(_iso, monkeypatch):
    """静默窗外(距上一条同域 >= 2h) ⇒ 视为事件复发, 直发。"""
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    clk.set(datetime(2026, 10, 15, 20, 30, 0))
    r = notify.send("[告警] R2 上传失败: b", "b", severe=True, ledger_key="r2_b")
    _chk(r.get("email") is True and not r.get("digested"), f"窗外应直发, 得 {r}")
    _chk(_domain_state(_iso["alerts"])["r2_deploy"]["n_direct"] == 2,
         f"应记 2 次直发, 得 {_domain_state(_iso['alerts'])}")


def test_02d_cross_day_first_direct(_iso, monkeypatch):
    """跨自然日首条必直发(给「持续未清」留每日一次分页通道)。"""
    clk = _Clock(datetime(2026, 10, 15, 23, 30, 0))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    clk.set(datetime(2026, 10, 16, 0, 5, 0))
    r = notify.send("[告警] R2 上传失败: a2", "b", severe=True, ledger_key="r2_a2")
    _chk(r.get("email") is True and not r.get("digested"),
         f"跨日首条应直发(距上条仅 35min), 得 {r}")


def test_02e_real_fault_counterexample_other_domain_direct(_iso, monkeypatch):
    """**真故障反例(C-②)**: 同时段第二个「不同域」故障仍独立首报(不同根因不并)。"""
    clk = _Clock(datetime(2026, 10, 15, 21, 0, 24))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] R2 上传失败: kelly-snapshots 通道(0/3)", "b", severe=True,
                ledger_key="r2_x")
    clk.set(datetime(2026, 10, 15, 21, 0, 27))
    r = notify.send("[告警] 云上 failed unit 持续未清(连续 8 天, 升级 critical)", "b",
                    severe=True, ledger_key="73ad3acf51d2")
    _chk(r.get("email") is True and not r.get("digested"),
         f"不同域真故障必须独立直发, 得 {r}")
    st = _domain_state(_iso["alerts"])
    _chk(st.get("unit", {}).get("n_direct") == 1, f"unit 域应独立首报, 得 {st}")
    # 同一时刻同域再来一条 ⇒ 被并(证明是「按域」而非「一刀切全直发」)
    clk.set(datetime(2026, 10, 15, 21, 0, 30))
    r2 = notify.send("[告警] R2 上传失败: etf-hist 通道(0/112)", "b", severe=True,
                     ledger_key="r2_y")
    _chk(r2.get("digested") is True, f"同域派生应被并, 得 {r2}")


def test_02f_report_group_business_signals_untouched(_iso, monkeypatch):
    """业务订阅流(report 群)不在本包作用面: 域映射命中也不聚合(不进告警群就不该并)。

    判别力: 若去掉域 gate 的 `_grp == "alert"`, 第 2/3 条会被第 1 条占的窗吸走 ⇒ 本用例变红。"""
    clk = _Clock(datetime(2026, 10, 15, 17, 21, 21))
    _patch_clock(monkeypatch, clk)
    for _i in range(3):
        r = notify.send("R2上传异步锁跳过 10-15 17:2%d" % _i, "b", severe=False,
                        ledger_key="r2_upload_async_skip:/tmp/x.lock")
        _chk(r.get("email") is True and not r.get("digested"),
             f"report 群消息应照发, 得 {r}")
    _chk(_domain_state(_iso["alerts"]) == {}, "report 群消息不得写域状态")
    _chk(_digest_rows(_iso["alerts"]) == [], "report 群消息不得进告警摘要")


def test_02g_recovery_exempt_but_trace_kept(_iso, monkeypatch):
    """恢复类照发(闭环信号必须即时) + 摘要里留痕(件E「恢复类入摘要且可见」)。"""
    clk = _Clock(datetime(2026, 10, 15, 20, 15, 10))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    clk.set(datetime(2026, 10, 15, 20, 15, 11))
    r = notify.send("[恢复] fetch_news ⚠ 已消失", "恢复正文", severe=False)
    _chk(r.get("email") is True and not r.get("digested"), f"恢复应直发, 得 {r}")
    rows = _digest_rows(_iso["alerts"])
    _chk(len(rows) == 1 and rows[0]["reason"] == notify.DIGEST_RECOVERY_TRACE_REASON,
         f"恢复应留痕 1 行, 得 {rows}")
    _chk(str(rows[0]["key"]).startswith("recovery-trace|"), f"留痕键应独立命名空间, 得 {rows[0]}")
    _chk(rows[0]["category"] == "recovery", f"留痕类别应 recovery, 得 {rows[0]}")


def test_02n_recovery_trace_only_after_real_send(_iso, monkeypatch):
    """R2 修(2026-10-16, 审查 R2): 恢复留痕**只在真发出之后**才写(设计口径「照发后留存」)。

    旧实现发送前预写 ⇒ 全渠道失败时摘要【闭环信号(恢复)】段仍自称「已即时直发」= 不实。
    判别力: 把行为改回「发送前无条件写」, 本用例第 ① 组必红(失败场景留痕行出现)。
    """
    clk = _Clock(datetime(2026, 10, 15, 20, 15, 10))
    _patch_clock(monkeypatch, clk)

    # ① 全渠道失败 ⇒ 不写留痕(摘要才不会自称「已直发」)
    monkeypatch.setattr(notify, "_send_email", lambda *a, **k: False)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    monkeypatch.setattr(notify, "send_feishu", lambda *a, **k: False)
    r = notify.send("[恢复] fetch_news ⚠ 已消失", "恢复正文", severe=False)
    _chk(not any((r.get("email"), r.get("telegram"), r.get("feishu"))),
         f"应全渠道失败, 得 {r}")
    _chk(_digest_rows(_iso["alerts"]) == [],
         f"全渠道失败不得写恢复留痕(否则摘要自称已直发=不实), 得 {_digest_rows(_iso['alerts'])}")

    # ② 任一渠道成功 ⇒ 照写留痕(正控: 行为未被过度收紧; 与 test_02g 同源, 单测自含)
    monkeypatch.setattr(notify, "send_feishu", lambda *a, **k: True)
    r2 = notify.send("[恢复] other_task ⚠ 已消失", "恢复正文", severe=False)
    _chk(r2.get("feishu") is True, f"飞书成功, 得 {r2}")
    rows = _digest_rows(_iso["alerts"])
    _chk(len(rows) == 1 and rows[0]["reason"] == notify.DIGEST_RECOVERY_TRACE_REASON
         and str(rows[0]["key"]).startswith("recovery-trace|"),
         f"真发出后应留痕 1 行, 得 {rows}")


def test_02h_dry_run_writes_nothing(_iso, monkeypatch):
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    for _i in range(3):
        r = notify.send("[告警] R2 上传失败: %d" % _i, "b", severe=True, dry_run=True)
        _chk(not r.get("digested"), f"dry-run 不得并入, 得 {r}")
    _chk(_domain_state(_iso["alerts"]) == {}, "dry-run 不得写域状态")
    _chk(_digest_rows(_iso["alerts"]) == [], "dry-run 不得写 buffer")


def test_02i_budget_exempt_critical_escalation_direct(_iso, monkeypatch):
    """critical 升级档(#196 send_tiered(critical) ⇒ budget_exempt)永不入域摘要。"""
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    clk.set(datetime(2026, 10, 15, 18, 30, 0))
    r = notify.send("[告警] 云上 failed unit 持续未清(连续 8 天, 升级 critical)", "b",
                    severe=True, ledger_key="73ad3acf51d2", budget_exempt=True)
    _chk(r.get("email") is True and not r.get("digested"),
         f"升级档必须直发(豁免), 得 {r}")


def test_02j_disable_switches_full_rollback(_iso, monkeypatch):
    """各层独立开关 + 总开关: 置 1 ⇒ 逐字节回现状(全直发、不写状态、不写 buffer)。"""
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    monkeypatch.setenv("ALERT_DOMAIN_DISABLE", "1")
    notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    clk.set(datetime(2026, 10, 15, 18, 28, 0))
    r = notify.send("[告警] R2 上传失败: b", "b", severe=True, ledger_key="r2_b")
    _chk(r.get("email") is True and not r.get("digested"), f"域开关应全停, 得 {r}")
    _chk(_domain_state(_iso["alerts"]) == {}, "关域开关不得写域状态")
    monkeypatch.delenv("ALERT_DOMAIN_DISABLE")
    monkeypatch.setenv("ALERT_BUDGET_DISABLE", "1")
    notify.send("[告警] R2 上传失败: c", "b", severe=True, ledger_key="r2_c")
    r2 = notify.send("[告警] R2 上传失败: d", "b", severe=True, ledger_key="r2_d")
    _chk(r2.get("email") is True and not r2.get("digested"), f"总开关应全停, 得 {r2}")
    _chk(not (_iso["alerts"] / "alert_domains.json").exists()
         and _digest_rows(_iso["alerts"]) == [],
         "总开关 ⇒ 域状态/buffer 逐字节回现状(全无)")


def test_02k_send_failure_does_not_claim_window(_iso, monkeypatch):
    """发送失败不占窗(P1-1 同款): 下一条同域告警仍直发重试, 绝不静默 2h。"""
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    monkeypatch.setattr(notify, "_send_email", lambda *a, **k: False)
    monkeypatch.setattr(notify, "send_telegram", lambda *a, **k: False)
    monkeypatch.setattr(notify, "send_feishu", lambda *a, **k: False)
    r = notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    _chk(not any((r.get("email"), r.get("telegram"), r.get("feishu"))), f"应全渠道失败, 得 {r}")
    _chk(_domain_state(_iso["alerts"]) == {}, f"失败不得占窗, 得 {_domain_state(_iso['alerts'])}")
    clk.set(datetime(2026, 10, 15, 18, 27, 0))
    monkeypatch.setattr(notify, "_send_email", lambda *a, **k: True)
    r2 = notify.send("[告警] R2 上传失败: b", "b", severe=True, ledger_key="r2_b")
    _chk(r2.get("email") is True and not r2.get("digested"),
         f"失败后同域下一条应重试直发, 得 {r2}")


def test_02l_absorb_append_failure_fail_open(_iso, monkeypatch):
    """buffer 写失败 ⇒ fail-open 直发(宁多发不吞, 绝不因降噪机制故障吞告警)。"""
    clk = _Clock(datetime(2026, 10, 15, 18, 25, 19))
    _patch_clock(monkeypatch, clk)
    notify.send("[告警] R2 上传失败: a", "b", severe=True, ledger_key="r2_a")
    monkeypatch.setattr(notify, "_append_jsonl", lambda *a, **k: False)
    clk.set(datetime(2026, 10, 15, 18, 28, 0))
    r = notify.send("[告警] R2 上传失败: b", "b", severe=True, ledger_key="r2_b")
    _chk(r.get("email") is True and not r.get("digested"),
         f"append 失败应落直发, 得 {r}")


def test_02m_unmapped_domain_never_absorbed(_iso, monkeypatch):
    """未映射/故意不映射(历史行改写)的告警永远直发 —— 宁漏不误并。"""
    clk = _Clock(datetime(2026, 10, 15, 16, 37, 45))
    _patch_clock(monkeypatch, clk)
    for _k, _s in (("history_overwrite:index_daily:20261015",
                    "[历史行改写] index_daily 历史行被重写 1 条(值改写1)"),
                   ("history_overwrite:signal_daily:20261015",
                    "[历史行改写] signal_daily 历史行被重写 997 条")):
        r = notify.send(_s, "b", severe=True, ledger_key=_k)
        _chk(r.get("email") is True and not r.get("digested"), f"应直发, 得 {r}")
    _chk(_domain_state(_iso["alerts"]) == {}, "未映射不得写域状态")


# ══════════════════════ ③ 件E 非 critical 重复类预算 + rollover ══════════════════════
def test_03a_notice_budget_pure_functions(_iso):
    """非 critical 台账口径(与 critical 口径**并行隔离** ⇒ B1 不破)。"""
    _seed_ledger(_iso["alerts"], [
        _ledger_row("r2_x", "[告警] R2上传失败", tier="notice"),
        _ledger_row("r2_x", "[告警] R2上传失败", tier="warning", ts="2026-10-15 10:00:00"),
        _ledger_row("r2_y", "[告警] R2上传失败", tier="critical"),
        _ledger_row("dep_1", "[告警] deploy x", tier="notice", group="report"),
    ])
    idx = adr.ledger_day_notice_index(_iso["tmp"], "2026-10-15")
    _chk(idx.get("r2") == ["r2_x", "r2_x"], f"只数 notice/warning 且 group=alert, 得 {idx}")
    _chk("deploy" not in idx, f"report 群不计入, 得 {idx}")
    _chk(adr.ledger_day_direct_counts(_iso["tmp"], "2026-10-15").get("r2") == 1,
         "critical 口径不受影响")
    _chk(adr.ALERT_NOTICE_BUDGET.keys() == adr.ALERT_BUDGET.keys(),
         "两套额度键集应一致(独立可调但同形)")


def test_03b_notice_first_direct_then_absorb(_iso, monkeypatch):
    """件E: notice 首现必直发; 同签名当日第二次(额度已用尽)⇒ 并入摘要。

    归因隔离: 本用例关域层(ALERT_DOMAIN_DISABLE=1), 让「并入」只能出自 E 层
    (两层是独立可回滚开关; 域层行为已由 ② 组用例各自覆盖)。"""
    monkeypatch.setenv("ALERT_DOMAIN_DISABLE", "1")
    clk = _Clock(datetime(2026, 10, 15, 22, 35, 22))
    _patch_clock(monkeypatch, clk)
    r = notify.send("[告警][数据缺口] 交易记录缺 7 条 10-15 22:35", "b", severe=False,
                    ledger_key="data_gap_x")
    _chk(r.get("email") is True and not r.get("digested"), f"首现必直发, 得 {r}")
    clk.set(datetime(2026, 10, 15, 23, 10, 0))
    r2 = notify.send("[告警][数据缺口] 交易记录缺 7 条 10-15 23:10", "b", severe=False,
                     ledger_key="data_gap_x")
    _chk(r2.get("digested") is True, f"同签名重复应并入, 得 {r2}")
    rows = _digest_rows(_iso["alerts"])
    _chk(len(rows) == 1 and rows[0]["reason"] == adr.NOTICE_OVER_BUDGET_REASON,
         f"应并入且带 notice reason, 得 {rows}")
    seen = json.loads((_iso["alerts"] / notify.ALERT_DIGEST_SEEN_FILE_NAME)
                      .read_text(encoding="utf-8"))
    _chk(seen.get("data_gap_x") == "2026-10-15", f"应登记 rollover 记忆, 得 {seen}")


def test_03c_notice_new_signature_direct(_iso, monkeypatch):
    """新签名(台账无、记忆无)永远直发 —— 首报必达对新事件成立。"""
    clk = _Clock(datetime(2026, 10, 15, 22, 35, 22))
    _patch_clock(monkeypatch, clk)
    _seed_ledger(_iso["alerts"], [_ledger_row("data_gap_a", "x", tier="notice")])
    r = notify.send("[告警][数据缺口] 另一条不同缺口", "b", severe=False,
                    ledger_key="data_gap_b")
    _chk(r.get("email") is True and not r.get("digested"), f"新签名应直发, 得 {r}")


def test_03d_critical_not_touched_by_notice_layer(_iso, monkeypatch):
    """critical 结构性豁免: 同签名 notice 用过额度也不影响 critical 的直发。"""
    clk = _Clock(datetime(2026, 10, 15, 22, 35, 22))
    _patch_clock(monkeypatch, clk)
    _seed_ledger(_iso["alerts"], [
        _ledger_row("r2_x", "[告警] R2上传失败", tier="notice"),
        _ledger_row("r2_x", "[告警] R2上传失败", tier="notice", ts="2026-10-15 10:00:00"),
    ])
    r = notify.send("[告警] R2 上传失败: 通道(0/1)", "b", severe=True, ledger_key="r2_x")
    _chk(r.get("email") is True and not r.get("digested"),
         f"critical 不得被 notice 层吞(也不得被 critical 层吞: 台账无 critical 行), 得 {r}")
    _chk(all(row["reason"] != adr.NOTICE_OVER_BUDGET_REASON for row in _digest_rows(_iso["alerts"])),
         "不得有 notice 层并入记录")


def test_03e_rollover_memory_and_prune(_iso):
    """rollover 纯函数: 窗内命中 / 跨日首现(今天)不命中 / 超窗不命中 / 裁剪。"""
    now = datetime(2026, 10, 16, 9, 0, 0)
    hit, _ = adr.rollover_absorb_judge({"sig1": "2026-10-15"}, "sig1", now)
    _chk(hit is True, "前日已并入 ⇒ 命中(不再当新事件重发)")
    hit2, _ = adr.rollover_absorb_judge({"sig1": "2026-10-16"}, "sig1", now)
    _chk(hit2 is False, "今天已并入过 ⇒ 由当日幂等处理, 不算 rollover")
    hit3, _ = adr.rollover_absorb_judge({"sig1": "2026-10-01"}, "sig1", now)
    _chk(hit3 is False, "超窗不命中(现为直发 = 现行为)")
    hit4, _ = adr.rollover_absorb_judge({}, "sig1", now)
    _chk(hit4 is False, "无记忆不命中")
    hit5, _ = adr.rollover_absorb_judge({"sig1": "garbage"}, "sig1", now)
    _chk(hit5 is False, "坏日期不命中(fail-open)")
    pruned = adr.rollover_prune({"a": "2026-10-16", "b": "2026-10-15", "c": "2026-01-01"}, now)
    _chk(pruned == {"a": "2026-10-16", "b": "2026-10-15"}, f"裁剪应只留窗内, 得 {pruned}")
    _chk(adr.rollover_prune({"x": "bad"}, now) == {}, "坏日期应被裁掉")


def test_03f_rollover_absorb_path(_iso, monkeypatch):
    """被吸收事件次日重现 ⇒ 仍并入摘要(修 RCA §2.2④b 跨日 rollover 重复播报)。

    归因隔离: 关域层(域层对跨自然日首条=直发), 单测 E 层的 rollover 记忆。
    构造: 当日类别额度已被**另一条**同类别通知用掉(count>=1) + 本签名昨日已并入过
    ⇒ _dup_today=False 而 _roll=True ⇒ reason 必须是 rollover_digested(而非常见超预算)。"""
    monkeypatch.setenv("ALERT_DOMAIN_DISABLE", "1")
    _seed_ledger(_iso["alerts"], [_ledger_row("r2_other", "[告警] R2上传失败", tier="notice",
                                              ts="2026-10-16 09:00:00")])
    (Path(_iso["alerts"]) / notify.ALERT_DIGEST_SEEN_FILE_NAME).write_text(
        json.dumps({"r2_x": "2026-10-15"}), encoding="utf-8")
    clk = _Clock(datetime(2026, 10, 16, 9, 5, 0))
    _patch_clock(monkeypatch, clk)
    r = notify.send("[告警] R2上传失败 10-16 09:05", "b", severe=False, ledger_key="r2_x")
    _chk(r.get("digested") is True, f"前日已并入 ⇒ 仍并入, 得 {r}")
    rows = _digest_rows(_iso["alerts"])
    _chk(rows and rows[0]["reason"] == adr.ROLLOVER_ABSORB_REASON,
         f"reason 应标 rollover, 得 {rows}")


def test_03h_notice_gate_skips_report_group(_iso, monkeypatch):
    """E 层限群判别力: **非 severe** 消息没有「severe⇒alert 群」的结构保证, 故必须显式
    限 alert 群 —— 否则 report 群业务流(买卖点/异动)同签名重复会被并进「告警摘要」而
    从报告群消失 = 丢业务信号。

    判别力: 去掉 notice gate 的 `_grp == "alert"` ⇒ 本条被并入 ⇒ 本用例变红。"""
    _seed_ledger(_iso["alerts"], [
        _ledger_row("r2_upload_async_skip:/tmp/x.lock", "[告警] R2上传异步锁跳过",
                    tier="notice", ts="2026-10-15 17:21:21")])
    clk = _Clock(datetime(2026, 10, 15, 17, 25, 0))
    _patch_clock(monkeypatch, clk)
    # 无方括号告警标记 ⇒ _resolve_feishu_chat_key 判为 report 群(业务订阅流)
    r = notify.send("R2上传异步锁跳过 10-15 17:25", "b", severe=False,
                    ledger_key="r2_upload_async_skip:/tmp/x.lock")
    _chk(r.get("email") is True and not r.get("digested"), f"report 群必须照发, 得 {r}")
    _chk(_digest_rows(_iso["alerts"]) == [], "report 群消息不得进告警摘要")


def test_03g_notice_switch_off(_iso, monkeypatch):
    """ALERT_NOTICE_BUDGET_DISABLE=1 ⇒ E 层单停(该重复照发/零并入)。

    归因隔离: 同关域层, 否则本条会由域层并入而掩盖 E 层开关是否真生效。"""
    monkeypatch.setenv("ALERT_DOMAIN_DISABLE", "1")
    monkeypatch.setenv("ALERT_NOTICE_BUDGET_DISABLE", "1")
    clk = _Clock(datetime(2026, 10, 15, 22, 35, 22))
    _patch_clock(monkeypatch, clk)
    # 构造: 台账当日已有同签名直发记录(= 无开关时必被并入的形态)
    _seed_ledger(_iso["alerts"], [_ledger_row("data_gap_x", "[告警][数据缺口] 缺 7 条",
                                              tier="notice")])
    r = notify.send("[告警][数据缺口] 缺 7 条", "b", severe=False, ledger_key="data_gap_x")
    _chk(r.get("email") is True and not r.get("digested"), f"关层应直发, 得 {r}")
    _chk(_digest_rows(_iso["alerts"]) == [], "关层不得写 buffer")


# ══════════════════════ ④ 件E 摘要渲染(flush_digest) ══════════════════════
def _run_flush(_iso, monkeypatch, clk, entries):
    (Path(_iso["alerts"]) / "alert_digest.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    captured = {}

    def _rec(subj, body, **k):
        captured["subj"] = subj
        captured["body"] = body
        captured["kw"] = k
        return {"email": True, "telegram": False, "feishu": True}

    monkeypatch.setattr(notify, "send", _rec)
    return notify.flush_digest(), captured


def _dentry(day, key, *, cat="r2", reason="over_budget", dom=None, src="t.sh",
            subject="主题", hits=1, hm="18:28:03"):
    e = {"ts": f"{day} {hm}", "rid": f"d-{day}-{key}", "day": day, "key": key,
         "category": cat, "subject": subject, "body": "正文", "from_prefix": "[告警]",
         "source": src, "reason": reason, "hits": hits}
    if dom:
        e["domain"] = dom
    return e


def test_04a_digest_mentions_merged_count_and_all_rows_searchable(_iso, monkeypatch):
    """E-①/E-③: 摘要注明「被合并 N 条」+ 全部被合并条目逐条可检索(含来源脚本/去重键)。

    buffer 形态对齐生产: 同签名重复并入只留 1 行 + hits 累加(不写两行), 摘要渲染成 `xN`。"""
    clk = _Clock(datetime(2026, 10, 15, 23, 30, 0))
    _patch_clock(monkeypatch, clk)
    entries = [
        _dentry("2026-10-15", "e516c06e9ff7", reason="domain_inhibited", dom="r2_deploy",
                src="schedule_stats", subject="[告警] R2 上传失败: data-files 通道(0/71)"),
        _dentry("2026-10-15", "r2_lab", cat="r2", reason="domain_inhibited", dom="r2_deploy",
                src="update_lab", subject="[告警] R2 上传失败: lab 通道(0/65)",
                hm="19:16:13", hits=2),
    ]
    r, cap = _run_flush(_iso, monkeypatch, clk, entries)
    _chk(r["sent"] is True and r["n"] == 2, f"被合并数 = 条目数(2), 得 {r}")
    _chk(cap["subj"].startswith("[告警·摘要] 当日合并 2 条"), f"subject 模板不对: {cap['subj']}")
    _chk("被合并 2 条" in cap["body"], f"正文须含「被合并 N 条」: {cap['body'][:120]}")
    _chk("同一故障域静默窗内派生" in cap["body"], "原因应用人读中文标签")
    _chk("e516c06e9ff7" in cap["body"] and "r2_lab" in cap["body"],
         "每条去重键须出现在正文(可检索)")
    _chk("schedule_stats" in cap["body"] and "update_lab" in cap["body"],
         "来源脚本须逐条列出(受影响通道判别维度)")
    _chk("x2" in cap["body"], f"同签名重复并入应显示次数, 得 {cap['body']}")
    _chk(cap["kw"].get("merged_count") == 2, f"merged_count 应为被合并数, 得 {cap['kw']}")
    _chk(_digest_rows(_iso["alerts"]) == [], "发出后应精确清理")


def test_04b_digest_domain_header_keeps_blast_radius(_iso, monkeypatch):
    """C-③: 合并消息保留「多少脚本/通道受影响」判别维度(域汇总段)。"""
    clk = _Clock(datetime(2026, 10, 15, 23, 30, 0))
    _patch_clock(monkeypatch, clk)
    entries = [
        _dentry("2026-10-15", "k1", reason="domain_inhibited", dom="r2_deploy", src="update_lab"),
        _dentry("2026-10-15", "k2", reason="domain_inhibited", dom="r2_deploy",
                src="schedule_stats", hm="19:00:00"),
        _dentry("2026-10-15", "k3", reason="domain_inhibited", dom="unit", src="cloud_unit_patrol",
                hm="20:00:00"),
        _dentry("2026-10-15", "k4", cat="data_gap", reason="notice_over_budget", src="check_data_gap",
                hm="22:35:00"),
    ]
    r, cap = _run_flush(_iso, monkeypatch, clk, entries)
    _chk(r["n"] == 4, f"4 条全并, 得 {r}")
    _chk("【故障域 R2/双树/部署链路】共 2 条" in cap["body"], f"域段不对: {cap['body'][:200]}")
    _chk("涉及 2 个来源脚本" in cap["body"], "应报受影响脚本数")
    _chk("【故障域 云上 systemd 单元】共 1 条" in cap["body"], "第二个域应独立成段")
    _chk("非 critical 重复类超预算" in cap["body"], "notice 层原因标签应出现")


def test_04c_digest_recovery_section_and_trace_not_counted(_iso, monkeypatch):
    """E-②: 恢复类出现在摘要; 留痕条**不计入**「被合并 N 条」(它不是被合并, 是已直发留痕)。"""
    clk = _Clock(datetime(2026, 10, 15, 23, 30, 0))
    _patch_clock(monkeypatch, clk)
    entries = [
        _dentry("2026-10-15", "r2_a", reason="domain_inhibited", dom="r2_deploy"),
        _dentry("2026-10-15", "task_x", cat="recovery", reason="over_budget",
                subject="[恢复] task_x kw_x", hm="20:15:10"),
        _dentry("2026-10-15", "recovery-trace|sig1", cat="recovery",
                reason=notify.DIGEST_RECOVERY_TRACE_REASON,
                subject="[恢复] fetch_news ⚠ 已消失", hm="20:15:12"),
    ]
    r, cap = _run_flush(_iso, monkeypatch, clk, entries)
    _chk(r["n"] == 2, f"被合并数应排除留痕条(3 条目 - 1 留痕), 得 {r}")
    _chk("被合并 2 条" in cap["body"], f"被合并数不对: {cap['body'][:120]}")
    _chk("【闭环信号(恢复)】" in cap["body"], "应单列闭环信号段")
    _chk("[恢复留痕·已直发]" in cap["body"], "留痕条应标注已直发")
    _chk("[恢复补列]" in cap["body"], "被合并的恢复条应沿用 [恢复补列] 标注")
    _chk("恢复留痕 1 条" in cap["subj"], f"subject 应标注留痕数: {cap['subj']}")


def test_04d_digest_trace_only_day_subject(_iso, monkeypatch):
    """只有留痕、无被合并条时 subject 措辞不撒谎(不写「当日合并 0 条」)。"""
    clk = _Clock(datetime(2026, 10, 15, 23, 30, 0))
    _patch_clock(monkeypatch, clk)
    r, cap = _run_flush(_iso, monkeypatch, clk,
                        [_dentry("2026-10-15", "recovery-trace|s", cat="recovery",
                                 reason=notify.DIGEST_RECOVERY_TRACE_REASON)])
    _chk(r["sent"] is True and r["n"] == 0, f"留痕日仍出摘要(闭环可见), 得 {r}")
    _chk("当日无合并告警" in cap["subj"] and "恢复留痕 1 条" in cap["subj"],
         f"subject 措辞不对: {cap['subj']}")


# ══════════════════════ ⑤ 机检(结构不变式 + 三态判别) ══════════════════════
def test_05a_source_invariants_machine_checked():
    """机检: 结构性不变式(防未来重构悄悄破坏红线)。"""
    src = (SCRIPTS / "notify.py").read_text(encoding="utf-8")
    _chk("not severe and not dry_run and not budget_exempt" in src,
         "件E gate 必须前置 `not severe`(critical 结构性豁免)")
    _chk("ALERT_NOTICE_BUDGET_DISABLE" in src and "ALERT_DOMAIN_DISABLE" in src,
         "各层独立回滚开关必须在代码里")
    i_gate = src.find("adr.DOMAIN_ABSORB_REASON")
    i_sub = src.find("if severe:\n        subject = SEVERE_PREFIX + subject")
    _chk(i_gate > 0 and i_sub > i_gate, "域 gate 必须在 subject 前缀改写之前(与 L2 gate 同层)")
    i_dig = src.find('if results.get("digested"):')
    i_ok = src.find("ok = [ch for ch, v in results.items() if v]", i_dig)
    _chk(i_dig >= 0 and i_ok > i_dig, "digested 早退仍必须在 ok 判定之前(消费点不被吞)")
    _chk("_commit_domain_state(_dom, _dom_entry)" in src, "域状态提交点必须在(发送成功才占窗)")
    sent = (SCRIPTS / "notify_sent.py").read_text(encoding="utf-8")
    _chk("[notify][domain] 并入当日域摘要" in sent and "[notify][notice-budget] 并入当日摘要" in sent,
         "新并入行必须登记进 notify_sent 抑制签名表(否则被判 failed 触发重试)")
    adr_src = (SCRIPTS / "alert_denoise_rules.py").read_text(encoding="utf-8")
    _chk("def domain_of(" in adr_src and "def domain_inhibit_judge(" in adr_src,
         "域判定纯函数应在共享模块(单一实现, 无第二副本)")
    _chk("DOMAIN_LABELS" in adr_src, "域中文标签应在")


def test_05b_notify_state_three_way_for_new_signatures():
    """三态判别: 新并入行 ⇒ suppressed; 反向用例(路由完成含 suppressed)仍 ⇒ sent。"""
    _chk(notify_state("[notify][domain] 并入当日域摘要 domain=r2_deploy key=k "
                      "(同域 2h 静默窗内派生)") == "suppressed", "域并入行应判 suppressed")
    _chk(notify_state("[notify][notice-budget] 并入当日摘要 key=k sig=s category=r2 "
                      "reason=notice_over_budget") == "suppressed", "非 critical 并入行应判 suppressed")
    _chk(notify_state("[notify][budget] 并入当日摘要 key=k sig=s category=r2") == "suppressed",
         "既有 L2 并入行仍 suppressed")
    rev = ("[notify][tier=warning] 路由完成：{'email': False, 'telegram': False, "
           "'feishu': False, 'tier': 'warning', 'deferred': True, "
           "'defer_status': 'suppressed'}")
    _chk(notify_state(rev) == "sent", "反向用例: 路由完成行含 suppressed 子串必须判 sent")
    _chk(notify_state("[notify] 汇总：已发出 email") == "sent", "常规发送行应判 sent")


def test_05c_min_assertions_counter():
    """断言计数下限守卫(防收集/执行异常致「0 断言假绿」)。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数 {_N[0]} < 下限 {_MIN_ASSERTIONS}")


# ══════════════════════ ⑥ 10-15 全天重放(真实台账样本) ══════════════════════
def test_06_replay_1015_real_day(_iso, monkeypatch):
    """重放 10-15 真实告警流(真实台账样本逐条) —— C-①/C-③ + E-①/E-③ 的机检证据。

    频道口径: 只重放 group=="alert" 的行(告警群 = 本包作用面); report/subscribe/follow
    群行不在作用面(fixture 里保留并计为「照发」以便对照总数), 台账自身 digest 行跳过。
    """
    rows = [r for r in _load_fixture() if r["ts"][:10] == "2026-10-15"]
    _chk(len(rows) > 40, f"fixture 应含 10-15 全天真实行, 得 {len(rows)}")
    clk = _Clock(datetime(2026, 10, 15, 0, 0, 0))
    _patch_clock(monkeypatch, clk)
    direct, absorbed, sent_other, digest_rows = [], [], [], 0
    for r in rows:
        _ts = datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S")
        clk.set(_ts)
        if r.get("tier") == "digest":
            digest_rows += 1
            continue
        if r.get("group") != "alert":
            sent_other.append(r)
            continue
        res = notify.send(r["subject"], r["subject"], severe=(r.get("tier") == "critical"),
                          ledger_key=r.get("key"), ledger_group="alert")
        (absorbed if res.get("digested") else direct).append(r)
    # ── R2 故障域(18:00 起)域级外发条数 = C-① 的核心数字
    _r2_direct = [r for r in direct if adr.domain_of(r.get("key"), r["subject"]) == "r2_deploy"
                  and r["ts"] >= "2026-10-15 18:00"]
    _r2_all = [r for r in rows if r.get("group") == "alert" and r.get("tier") != "digest"
               and adr.domain_of(r.get("key"), r["subject"]) == "r2_deploy"
               and r["ts"] >= "2026-10-15 18:00"]
    _chk(len(_r2_all) >= 20, f"10-15 R2 故障域应 >=20 条(现 28 量级), 得 {len(_r2_all)}")
    _chk(1 <= len(_r2_direct) <= 2,
         f"C-① 域级外发应 1~2 条, 得 {len(_r2_direct)}: {[r['ts'] for r in _r2_direct]}")
    # ── 台账被并条目: 逐条可检索 + 域段保留通道清单
    clk.set(datetime(2026, 10, 15, 23, 30, 0))
    tr, cap = _run_flush(_iso, monkeypatch, clk, _digest_rows(_iso["alerts"]))
    _chk(tr["sent"] is True and tr["n"] >= 10, f"当日摘要应含被合并条目, 得 {tr}")
    _chk(f"被合并 {tr['n']} 条" in cap["body"], f"E-① 应含「被合并 N 条」: {cap['body'][:100]}")
    _missing = [r["key"] for r in absorbed if str(r.get("key") or "") and
                str(r["key"]) not in cap["body"] and r["subject"][:20] not in cap["body"]]
    _chk(_missing == [], f"E-③ 被合并条目必须全部可检索, 缺: {_missing[:5]}")
    _chk("【故障域 R2/双树/部署链路】" in cap["body"], "C-③ 域段必须出现")
    _chk("个来源脚本" in cap["body"], "C-③ 受影响脚本数必须保留")
    print(f"[replay-1015] 告警群直发={len(direct)} 被并={len(absorbed)} "
          f"非告警群照发={len(sent_other)} 域外发={len(_r2_direct)} 摘要={tr['n']}",
          file=sys.stderr)


# ══════════════════════ ⑦ 时钟无关性(§18 L51 隔天仍绿 机检) ══════════════════════
def test_07_verdicts_independent_of_real_run_day(_iso, monkeypatch):
    """同一告警序列在**两个不同的虚拟运行日**下判定必须逐位一致。

    被测代码内部取 now()(域静默窗/台账按日/摘要按日), 本文件全部经虚拟时钟注入 ⇒
    结果只随「数据时点」变, 不随「真实运行日」变 ⇒ 今天跑/明天跑/明年跑同一结论
    (§18 L51 教训: 写死运行日 ⇒ 出生当天绿、次日红)。"""
    seq = [("[告警] deploy 数据产物校验失败", True, "deploy_check_data_integrity_fail"),
           ("[告警] R2 上传失败: data-files 通道(0/71)", True, "e516c06e9ff7"),
           ("[告警] R2 上传失败: lab 通道(0/65)", True, "update_lab_r2_fail"),
           ("[告警] 云上 failed unit 持续未清(连续 8 天, 升级 critical)", True, "73ad3acf51d2"),
           ("[告警][数据缺口] 交易记录缺 7 条", False, "data_gap_x"),
           ("[历史行改写] index_daily 历史行被重写 1 条(值改写1)", True,
            "history_overwrite:index_daily:20261015")]

    def _run(base: datetime) -> list:
        # 清空上一轮的落盘面(两次运行必须是同一初始态)
        for _n in ("alert_domains.json", "alert_digest_seen.json", "alert_ledger.jsonl",
                   "alert_digest.jsonl", "latest.md"):
            _p = _iso["alerts"] / _n
            if _p.exists():
                _p.unlink()
        clk = _Clock(base)
        _patch_clock(monkeypatch, clk)
        _v = []
        for _i, (subj, sev, key) in enumerate(seq):
            clk.set(base + timedelta(minutes=10 * _i))
            r = notify.send(subj, subj, severe=sev, ledger_key=key)
            _v.append("absorb" if r.get("digested") else "direct")
        return _v

    v1 = _run(datetime(2026, 10, 15, 18, 0, 0))     # 数据当日
    v2 = _run(datetime(2027, 3, 8, 18, 0, 0))       # 完全不同的「真实运行日」
    _chk(v1 == v2, f"判定随真实运行日漂移(§18 L51): {v1} vs {v2}")
    _chk(v1 == ["direct", "absorb", "absorb", "direct", "direct", "direct"],
         f"设计与实测不一致: {v1}")