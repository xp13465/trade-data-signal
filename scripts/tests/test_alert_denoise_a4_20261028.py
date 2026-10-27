# -*- coding: utf-8 -*-
"""告警降噪 ★4(2026-10-28)——「降噪生效 + 判别保留」回归套。

三项(逐项双验收: 常态不再吵 / 异常照常响; 依据 docs/ops/alert-denoise-a4-research-20261028.md §6):
  ① index_daily 历史行改写分级(app/history_audit.plan_index_daily_alerts + _alert_index_daily):
     数量档 small<200 / mid 200–999 / large>=1000;只有 `caller=="runner"` 的 mid/large 才 critical,
     `index_backfill`(计划内回填)与 small(常态 T+1 修正)只进 23:25 摘要;
     「旧行真覆盖」独立成一条 critical(行龄 >=30 天 且 值→值),不被数量档稀释。
  ② signal_daily 无状态判据(app/history_audit.plan_signal_daily_alert):
     net<=-200 或 任一 date「消失>=20 且占原有>=30%」⇒ critical;否则 notice。
  ③ kelly 常态降级(scripts/signal_kelly_backtest):
     冻结表缺失 <10 ⇒ 只进摘要(--defer-digest, 不单发);>=10 仍 --severe;
     冻结孤儿买事件按「新增条数 >=5」门控(基线落原子写状态文件, 无基线 fail-open 照发)。

【零外发(§18 L48/L50)】全程 static-only: notify 出口一律替换为「记录参数」的假函数/假
  subprocess.run, 真子进程/真网络不起;收尾套 `_zero_outbound.ZeroOutboundTrap` 兜底。
【冻结运行日(§18 L51)】所有判定显式传 run_date, 并有一条用例把 `history_audit.today_ymd`
  替换成「一调用即炸」, 证明决策路径不读真实当天日期(隔天跑结论不变)。
【复现】/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \\
          scripts/tests/test_alert_denoise_a4_20261028.py
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import _zero_outbound  # noqa: E402  (conftest 已把 scripts/tests 与 scripts 入 sys.path)

ROOT = Path(__file__).absolute().parent.parent.parent

pytest.importorskip("yaml", reason="CI 需 pyyaml 才能 import signal_kelly_backtest")
sys.path.insert(0, str(ROOT / "scripts"))

from app import history_audit as ha  # noqa: E402

try:
    import signal_kelly_backtest as sk  # noqa: E402
except Exception as _e:  # pragma: no cover
    pytest.skip(f"kelly 依赖不可用: {_e}", allow_module_level=True)

RUN_DATE = "20261028"          # 冻结运行日: 判定只看它, 不看真实今天
_MIN_ASSERTIONS = 55
_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


# ════════════════════════════════════════════════════════════════════════════
# 公共假件
# ════════════════════════════════════════════════════════════════════════════
class _Recorder:
    """记录 send_alert 参数(不真发)。"""

    def __init__(self):
        self.calls = []

    def __call__(self, subject, body, **kw):
        self.calls.append({"subject": subject, "body": body, **kw})
        return 0


class _FakeRun:
    """记录 argv 的假 subprocess.run(不真起子进程 = 零真实外发)。"""

    def __init__(self, rc=0):
        self.calls = []
        self.rc = rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        return types.SimpleNamespace(returncode=self.rc, stdout="", stderr="")


def _chg(date, index_id, kind="changed", kinds=("correct",),
         before_val="open=1", after_val="open=2", signal=None):
    """造一条 index_daily 改写记录(字段形状与 _diff_index_history 一致)。"""
    return {"kind": kind, "date": date, "index_id": index_id, "signal": signal,
            "before_val": before_val, "after_val": after_val, "kinds": set(kinds)}


def _batch(n, date="20261027", kinds=("correct",), prefix="idx"):
    return [_chg(date, f"{prefix}{k:04d}", kinds=kinds) for k in range(n)]


def _sig_changes(n_dis, n_app, date="20261027"):
    ch = [{"kind": "disappeared", "date": date, "index_id": f"d{k:03d}", "signal": "buy",
           "before_val": "", "after_val": "", "kinds": set()} for k in range(n_dis)]
    ch += [{"kind": "appeared", "date": date, "index_id": f"a{k:03d}", "signal": "buy_aux",
            "before_val": "", "after_val": "", "kinds": set()} for k in range(n_app)]
    return ch


def _sig_set(n_by_date):
    out = set()
    for d, n in n_by_date.items():
        for k in range(n):
            out.add((d, f"i{k:03d}", "buy"))
    return out


# ════════════════════════════════════════════════════════════════════════════
# ① index_daily 分级(纯函数 = 决策本身)
# ════════════════════════════════════════════════════════════════════════════
def test_a1_positive_control_runner_mid_is_critical():
    """正控(判别保留): runner 中批(250 条)必须 critical。"""
    plan = ha.plan_index_daily_alerts(_batch(250), RUN_DATE, "runner")
    _chk(len(plan) == 1, f"无旧行覆盖时只 1 条计划, 得 {len(plan)}")
    _chk(plan[0]["critical"] is True, "runner mid 应 critical")
    _chk(plan[0]["dedup_suffix"] == "runner:mid", f"键尾={plan[0]['dedup_suffix']}")
    _chk("mid 档" in plan[0]["note"], f"说明应写档位: {plan[0]['note']}")


def test_a2_counter_example_runner_small_is_notice():
    """反例 1(降噪生效): runner 小批(50 条, 实测常态 ~85 行/天)不再是 critical。"""
    plan = ha.plan_index_daily_alerts(_batch(50), RUN_DATE, "runner")
    _chk(plan[0]["critical"] is False, "runner small 应 notice")
    _chk(plan[0]["dedup_suffix"] == "runner:small", "键尾=runner:small")


def test_a3_counter_example_index_backfill_large_is_notice():
    """反例 2: index_backfill 大批(2062 条, 回填真实形态)是计划内回填 ⇒ notice。"""
    plan = ha.plan_index_daily_alerts(_batch(2062, date="20261022"), RUN_DATE, "index_backfill")
    _chk(plan[0]["critical"] is False, "计划内回填即便 large 也不 critical")
    _chk(plan[0]["dedup_suffix"] == "index_backfill:large", "键尾=index_backfill:large")


def test_a4_bucket_boundaries():
    """档位边界: 199/200/999/1000 四个拐点逐位核对。"""
    cases = [(1, "small"), (199, "small"), (200, "mid"), (999, "mid"), (1000, "large")]
    for n, want in cases:
        got = ha._index_bucket(n)
        _chk(got == want, f"{n} 条应判 {want}, 得 {got}")
    _chk(ha._index_bucket(0) == "small", "0 条也 small(防御性)")


def test_a5_old_row_value_to_value_is_independent_critical():
    """旧行真覆盖: 1 行(行龄 400 天, 值→值)也必须 critical, 且与 small 提示各发一条。"""
    old = _chg("20250923", "csi_000300", kinds=("correct",),
               before_val="close=6562", after_val="close=3367")
    plan = ha.plan_index_daily_alerts([old], RUN_DATE, "runner")
    _chk(len(plan) == 2, f"small 提示 + 旧行 critical 应各自成计划, 得 {len(plan)}")
    _chk(plan[0]["critical"] is False and plan[0]["dedup_suffix"] == "runner:small",
         "数量档 small 仍是提示")
    _chk(plan[1]["critical"] is True, "旧行真覆盖必须 critical")
    _chk(plan[1]["dedup_suffix"] == "old_overwrite", "独立键尾 old_overwrite")
    _chk(len(plan[1]["changes"]) == 1, "旧行清单只含该行")


def test_a6_old_row_fill_or_wipe_is_not_old_overwrite():
    """判别保留的反面: 旧行只是补空(fill)/抹空(wipe) 不算「被改成别的值」。"""
    for kinds in (("fill",), ("wipe",), ("fill", "wipe")):
        plan = ha.plan_index_daily_alerts(
            [_chg("20250923", "csi_000300", kinds=kinds)], RUN_DATE, "runner")
        _chk(all(p["dedup_suffix"] != "old_overwrite" for p in plan),
             f"kinds={kinds} 不应触发 old_overwrite")
        _chk(len(plan) == 1, f"kinds={kinds} 只应 1 条数量档计划")


def test_a7_recent_row_value_change_not_old_overwrite():
    """行龄门槛: 值→值但行龄 2 天(<30) ⇒ 不算旧行真覆盖(常态 T+1 修正)。"""
    plan = ha.plan_index_daily_alerts(
        [_chg("20261026", "csi_000300", kinds=("correct",))], RUN_DATE, "runner")
    _chk(len(plan) == 1 and plan[0]["dedup_suffix"] == "runner:small", "2 天行龄不触发旧行判据")
    _chk(ha._row_age_days("20261026", RUN_DATE) == 2, "行龄计算应为 2 天")


def test_a8_partial_single_row_is_notice():
    """单行局部改写(caller=partial)恒 small ⇒ notice, 但旧行判据照常生效。"""
    plan = ha.plan_index_daily_alerts(_batch(1), RUN_DATE, "partial")
    _chk(plan[0]["critical"] is False and plan[0]["dedup_suffix"] == "partial:small", "partial 应提示")


def test_a9_empty_batch_no_plan():
    _chk(ha.plan_index_daily_alerts([], RUN_DATE, "runner") == [], "空批不发计划")


def test_a10_missing_or_malformed_inputs_tolerated():
    """输入域兜底: 旧 change 字典缺 "kinds" / 行龄日期非法 ⇒ 按「非值→值」处理, 不炸。"""
    legacy = {"kind": "changed", "date": "20261027", "index_id": "idx0", "signal": None,
              "before_val": "x", "after_val": "y"}          # 无 "kinds" 键(旧调用方形状)
    plan = ha.plan_index_daily_alerts([legacy], RUN_DATE, "runner")
    _chk(len(plan) == 1 and plan[0]["critical"] is False, "缺 kinds 视为无旧行覆盖")
    _chk(ha._row_age_days("not-a-date", RUN_DATE) == 0, "非法日期按 0 天(不当旧行)")
    plan2 = ha.plan_index_daily_alerts([_chg("baddate", "idx0", kinds=("correct",))],
                                       RUN_DATE, "runner")
    _chk(all(p["dedup_suffix"] != "old_overwrite" for p in plan2),
         "行龄解析失败不得触发旧行判据")


# ════════════════════════════════════════════════════════════════════════════
# ① 真实发送路径(_alert_index_daily → _alert → send_alert 打桩)
# ════════════════════════════════════════════════════════════════════════════
def _run_index_alert(monkeypatch, changes, caller="runner"):
    rec = _Recorder()
    monkeypatch.setattr(ha, "send_alert", rec)
    ha._alert_index_daily(changes, RUN_DATE, caller)
    return rec.calls


def test_b1_small_notice_defers_to_digest(monkeypatch):
    """降噪生效: 常态小批 ⇒ 不单发(severe=False, defer_digest=True), 键按 caller+bucket 分。"""
    with _zero_outbound.ZeroOutboundTrap() as trap:
        calls = _run_index_alert(monkeypatch, _batch(85))
    _chk(len(calls) == 1, f"应 1 条摘要调用, 得 {len(calls)}")
    c = calls[0]
    _chk(c["severe"] is False, "small 应非 severe")
    _chk(c["defer_digest"] is True, "small 应只进 23:25 摘要")
    _chk(c["digest_category"] == "history_overwrite", f"摘要分类={c['digest_category']}")
    _chk(c["dedup_key"] == f"history_overwrite:index_daily:{RUN_DATE}:runner:small",
         f"dedup key={c['dedup_key']}")
    _chk(c["from_prefix"] == "[提示]", f"前缀={c['from_prefix']}")
    _chk(c["dedup_window"] >= 86400, "提示级窗口至少 1 天")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_b2_missing_values_wipe_is_notice(monkeypatch):
    """实测形态(10-27 ftse100/cac40 value→缺失 等 5 个海外指数): 属于小批 ⇒ 提示。"""
    changes = [_chg("20261027", "ftse100", kinds=("wipe",), before_val="close=8321", after_val="close=None"),
               _chg("20261027", "cac40", kinds=("wipe",), before_val="close=7925", after_val="close=None")]
    calls = _run_index_alert(monkeypatch, changes)
    _chk(len(calls) == 1 and calls[0]["severe"] is False, "海外指数抹空是小批提示")


def test_b3_synthetic_2062_runner_batch_is_critical(monkeypatch):
    """判别保留: 合成 2062 条「值→值」runner 批 ⇒ 明确 critical(即时通道, 不进摘要)。"""
    with _zero_outbound.ZeroOutboundTrap() as trap:
        calls = _run_index_alert(monkeypatch, _batch(2062, date="20261022"), "runner")
    _chk(len(calls) == 1, f"应 1 条, 得 {len(calls)}")
    c = calls[0]
    _chk(c["severe"] is True, "large 应 severe")
    _chk(c["defer_digest"] is False, "critical 不得进摘要")
    _chk(c["dedup_key"].endswith(":runner:large"), f"key={c['dedup_key']}")
    _chk("critical" in c["body"] or "大批量" in c["body"], "正文应说明判 critical 的原因")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_b4_old_overwrite_two_alerts_both_emitted(monkeypatch):
    """一跑两见: 提示级 small 与旧行 critical 各一条, critical 不被小批吞掉。"""
    old = _chg("20250923", "csi_000300", kinds=("correct",),
               before_val="close=6562", after_val="close=3367")
    calls = _run_index_alert(monkeypatch, [old] + _batch(3, date="20261027"), "runner")
    _chk(len(calls) == 2, f"应 2 条(提示+旧行 critical), 得 {len(calls)}")
    by_key = {c["dedup_key"].rsplit(":", 1)[-1]: c for c in calls}
    _chk(set(by_key) == {"small", "old_overwrite"}, f"键尾集合={set(by_key)}")
    _chk(by_key["small"]["defer_digest"] is True and by_key["small"]["severe"] is False,
         "小批走摘要")
    _chk(by_key["old_overwrite"]["defer_digest"] is False, "旧行 critical 即时发")
    _chk(by_key["old_overwrite"]["severe"] is True, "旧行 critical 应 severe")
    _chk("6562" in by_key["old_overwrite"]["body"], "正文应带旧值样例")


def test_b5_index_backfill_mid_not_critical(monkeypatch):
    """同模式覆盖: 回填中等批量(400 条)也只提示(index_backfill 全部写入点口径一致)。"""
    calls = _run_index_alert(monkeypatch, _batch(400, date="20261027"), "index_backfill")
    _chk(len(calls) == 1 and calls[0]["severe"] is False, "index_backfill 400 条应提示")
    _chk(calls[0]["dedup_key"].endswith(":index_backfill:mid"), f"key={calls[0]['dedup_key']}")


# ════════════════════════════════════════════════════════════════════════════
# ② signal_daily 无状态判据
# ════════════════════════════════════════════════════════════════════════════
def test_c1_net_threshold_boundary():
    """net 边界: -200 判 critical, -199 不判(且无单日大消失)。"""
    before = _sig_set({"20261027": 500})
    ch200 = _sig_changes(200, 0)
    after200 = before - {(c["date"], c["index_id"], c["signal"]) for c in ch200}
    p = ha.plan_signal_daily_alert(ch200, before, after200)
    _chk(p["critical"] is True, f"净 -200 应 critical: {p['note']}")

    # -199 条: 分散在 11 天(每天 drop<=19, 占比 19%<30%)⇒ 两条判据都不达
    by_date = {f"202610{d:02d}": 19 for d in range(10, 20)}   # 10 天 × 19 = 190
    by_date["20261020"] = 9                                    # + 9 = 199
    before2 = _sig_set({d: 100 for d in by_date})
    ch199 = [{"kind": "disappeared", "date": d, "index_id": f"i{k:03d}", "signal": "buy",
              "before_val": "", "after_val": "", "kinds": set()}
             for d, n in by_date.items() for k in range(n)]
    _chk(len(ch199) == 199, f"前置: 构造 199 条消失, 得 {len(ch199)}")
    after199 = before2 - {(c["date"], c["index_id"], c["signal"]) for c in ch199}
    p2 = ha.plan_signal_daily_alert(ch199, before2, after199)
    _chk(p2["critical"] is False, f"净 -199 且无单日大消失应提示: {p2['note']}")


def test_c2_date_drop_thresholds():
    """单日判据: drop>=20 且占比>=30% 才 critical;19 条或占比 20% 都不算。"""
    # ③ 100 行 → 剩 75(drop 25, 25%<30%) ⇒ 不判
    before = _sig_set({"20261027": 100})
    ch = [{"kind": "disappeared", "date": "20261027", "index_id": f"i{k:03d}", "signal": "buy",
           "before_val": "", "after_val": "", "kinds": set()} for k in range(25)]
    after = before - {(c["date"], c["index_id"], c["signal"]) for c in ch}
    _chk(ha.plan_signal_daily_alert(ch, before, after)["critical"] is False, "占比 25% 不判")

    # ④ 60 行 → 剩 30(drop 30, 50%) ⇒ critical
    before2 = _sig_set({"20261027": 60})
    ch2 = [{"kind": "disappeared", "date": "20261027", "index_id": f"i{k:03d}", "signal": "buy",
            "before_val": "", "after_val": "", "kinds": set()} for k in range(30)]
    after2 = before2 - {(c["date"], c["index_id"], c["signal"]) for c in ch2}
    p = ha.plan_signal_daily_alert(ch2, before2, after2)
    _chk(p["critical"] is True, f"drop 30/60 应 critical: {p['note']}")
    _chk("20261027" in p["note"], "说明应带命中日期")

    # ⑤ 60 行 → 剩 41(drop 19 <20) ⇒ 不判
    before3 = _sig_set({"20261027": 60})
    ch3 = [{"kind": "disappeared", "date": "20261027", "index_id": f"i{k:03d}", "signal": "buy",
            "before_val": "", "after_val": "", "kinds": set()} for k in range(19)]
    after3 = before3 - {(c["date"], c["index_id"], c["signal"]) for c in ch3}
    _chk(ha.plan_signal_daily_alert(ch3, before3, after3)["critical"] is False, "drop 19 不判")


def test_c3_typical_type_drift_is_notice():
    """实测常态(型别漂移: 出现≈消失, 单日小批) ⇒ 提示, 不再 critical。"""
    before = _sig_set({"20261027": 300})
    ch = (_sig_changes(15, 14))
    after = (before - {(c["date"], c["index_id"], c["signal"]) for c in ch
                       if c["kind"] == "disappeared"}) | {
        (c["date"], c["index_id"], c["signal"]) for c in ch if c["kind"] == "appeared"}
    p = ha.plan_signal_daily_alert(ch, before, after)
    _chk(p["critical"] is False, f"常态型别漂移应提示: {p['note']}")
    _chk("净变化" in p["note"], "提示应带判据说明")


def test_c4_signal_daily_alert_path_defers_notice(monkeypatch):
    """真实发送路径: notice ⇒ defer_digest=True + 键尾 notice;critical ⇒ 即时。"""
    rec = _Recorder()
    monkeypatch.setattr(ha, "send_alert", rec)
    before = _sig_set({"20261027": 300})
    ch = _sig_changes(15, 14)
    after = before - {(c["date"], c["index_id"], c["signal"]) for c in ch
                      if c["kind"] == "disappeared"}
    ha._alert("signal_daily", ch, RUN_DATE, ha._SIGNAL_DEDUP_WINDOW,
              pure_lost=[], critical_override=False)
    _chk(len(rec.calls) == 1 and rec.calls[0]["defer_digest"] is True, "notice 应进摘要")
    _chk(rec.calls[0]["dedup_key"].endswith(":notice"), f"key={rec.calls[0]['dedup_key']}")


# ════════════════════════════════════════════════════════════════════════════
# ③ kelly 冻结表缺失: <10 只进摘要, >=10 仍 severe
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture()
def accepted_file(tmp_path):
    p = tmp_path / "accepted.json"
    p.write_text(json.dumps({"accepted": []}), encoding="utf-8")
    return p


def _run_frozen_missing(monkeypatch, n, accepted_path):
    fake = _FakeRun()
    monkeypatch.setattr(sk, "FROZEN_MISSING_ACCEPTED_PATH", str(accepted_path))
    monkeypatch.setattr(sk.subprocess, "run", fake)
    events = {("20261020", f"idx{k:03d}", "buy") for k in range(n)}
    sk._alert_frozen_missing(events)
    return fake.calls


def test_d1_frozen_missing_small_defers(monkeypatch, accepted_file):
    """降噪生效: <10 个 ⇒ 不单发, 只进摘要(--defer-digest), 且不再用 small dedup key。"""
    with _zero_outbound.ZeroOutboundTrap() as trap:
        calls = _run_frozen_missing(monkeypatch, 9, accepted_file)
    _chk(len(calls) == 1, f"应 1 条摘要调用, 得 {len(calls)}")
    _chk("--defer-digest" in calls[0], "9 个应 --defer-digest")
    _chk("kelly_frozen_missing" in calls[0], "应带 digest-category")
    _chk("--severe" not in calls[0], "9 个不应 severe")
    _chk("signal_kelly_frozen_missing_small" not in calls[0], "不得再用 small dedup key")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_d2_frozen_missing_severe_unchanged(monkeypatch, accepted_file):
    """判别保留: >=10 个(实测 11/12/14 真 P0 形态)仍 --severe 即时直发, 不进摘要。"""
    calls = _run_frozen_missing(monkeypatch, 11, accepted_file)
    _chk(len(calls) == 1, "应 1 条")
    _chk("--severe" in calls[0], "11 个应 severe")
    _chk("--defer-digest" not in calls[0], "severe 不得进摘要")
    _chk("signal_kelly_frozen_missing" in calls[0], "应带 severe dedup key")
    _chk("11 个" in calls[0][2], f"subject 应报 11 个: {calls[0][2]}")


def test_d3_frozen_missing_threshold_boundary(monkeypatch, accepted_file):
    """阈值边界: 10 个 = severe 档(阈值常量 FROZEN_MISSING_SEVERE_THRESHOLD 不动的证据)。"""
    _chk(sk.FROZEN_MISSING_SEVERE_THRESHOLD == 10, "阈值应保持 10")
    calls = _run_frozen_missing(monkeypatch, 10, accepted_file)
    _chk("--severe" in calls[0] and "--defer-digest" not in calls[0], "10 个应 severe")


# ════════════════════════════════════════════════════════════════════════════
# ④ kelly 冻结孤儿买事件: 按新增 >=5 门控
# ════════════════════════════════════════════════════════════════════════════
def _orphans(n):
    return [("20261020", f"idx{k:03d}", "buy") for k in range(n)]


@pytest.fixture()
def orphan_env(monkeypatch, tmp_path):
    """开启孤儿告警 + 状态文件指到临时目录(不碰仓库 data/)。"""
    state = tmp_path / "alerts" / "kelly_freeze_orphan_state.json"
    monkeypatch.setenv(sk.FREEZE_ORPHAN_ALERT_ENV, "1")
    monkeypatch.setenv(sk.FREEZE_ORPHAN_STATE_ENV, str(state))
    fake = _FakeRun()
    monkeypatch.setattr(sk.subprocess, "run", fake)
    return state, fake


def test_e1_delta_gate_three_sends_over_nine_days(orphan_env):
    """实测序列 2→11→16→21→21→21→24 ⇒ 只发 3 条(新增 11/5/5), 不是 7 条。"""
    state, fake = orphan_env
    with _zero_outbound.ZeroOutboundTrap() as trap:
        for n in (2, 11, 16, 21, 21, 21, 24):
            sk._alert_freeze_orphans(_orphans(n))
    _chk(len(fake.calls) == 3, f"9 天应只发 3 条, 实发 {len(fake.calls)}")
    subs = [c[2] for c in fake.calls]
    _chk("新增孤儿买事件 11 条(累计 11 条)" in subs[0], f"第 1 条 subject: {subs[0]}")
    _chk("新增孤儿买事件 5 条(累计 16 条)" in subs[1], f"第 2 条 subject: {subs[1]}")
    _chk("新增孤儿买事件 5 条(累计 21 条)" in subs[2], f"第 3 条 subject: {subs[2]}")
    _chk(json.loads(state.read_text(encoding="utf-8"))["reported_n"] == 21, "基线=21")
    _chk(trap.hits == [], f"零外发被破坏: {trap.hits}")


def test_e2_fail_open_without_state(orphan_env):
    """状态文件缺失 ⇒ fail-open 照发一次(绝不因丢状态而永久静默)。"""
    state, fake = orphan_env
    _chk(not state.exists(), "前置: 状态文件不存在")
    sk._alert_freeze_orphans(_orphans(50))
    _chk(len(fake.calls) == 1, "无基线应照发 1 条")
    _chk("首次告警" in fake.calls[0][3], "正文应标注 fail-open")
    _chk(json.loads(state.read_text(encoding="utf-8"))["reported_n"] == 50, "基线应写入 50")


def test_e3_corrupt_state_fails_open(orphan_env):
    """状态文件损坏 ⇒ 同样 fail-open(不静默)。"""
    state, fake = orphan_env
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("{not json", encoding="utf-8")
    _chk(sk._load_freeze_orphan_reported_n() is None, "损坏应读成 None")
    sk._alert_freeze_orphans(_orphans(5))
    _chk(len(fake.calls) == 1, "损坏视作无基线 ⇒ 照发")


def test_e4_reset_baseline_on_zero_and_regrow(orphan_env):
    """孤儿归零 ⇒ 基线归零;再长 5 条即报(不会被旧高基线长期压住)。"""
    state, fake = orphan_env
    sk._alert_freeze_orphans(_orphans(11))
    _chk(len(fake.calls) == 1 and json.loads(state.read_text())["reported_n"] == 11, "首报 11")
    sk._alert_freeze_orphans([])
    _chk(json.loads(state.read_text())["reported_n"] == 0, "归零后基线=0")
    sk._alert_freeze_orphans(_orphans(4))
    _chk(len(fake.calls) == 1, "4 <5 不发")
    sk._alert_freeze_orphans(_orphans(5))
    _chk(len(fake.calls) == 2, "5 >=5 应发")
    _chk("新增孤儿买事件 5 条(累计 5 条)" in fake.calls[-1][2], f"subject: {fake.calls[-1][2]}")


def test_e5_send_failure_keeps_baseline(orphan_env, monkeypatch, capsys):
    """发送失败不更新基线 ⇒ 下一轮还会重试(真故障不被静默丢掉)。"""
    state, _fake = orphan_env
    sk._alert_freeze_orphans(_orphans(6))          # 首报(无基线 fail-open) 6 条, 成功
    _chk(json.loads(state.read_text())["reported_n"] == 6, "基线=6")
    bad = _FakeRun(rc=1)
    monkeypatch.setattr(sk.subprocess, "run", bad)
    sk._alert_freeze_orphans(_orphans(12))         # delta 6, 发送失败
    _chk(json.loads(state.read_text())["reported_n"] == 6, "失败后基线不得抬到 12")
    _chk("发送失败" in capsys.readouterr().err, "应有失败留痕")


def test_e6_alert_disabled_writes_nothing(monkeypatch, tmp_path):
    """默认关闭(env 未设)⇒ 只打日志, 不起子进程、不落状态文件。"""
    state = tmp_path / "alerts" / "state.json"
    monkeypatch.delenv(sk.FREEZE_ORPHAN_ALERT_ENV, raising=False)
    monkeypatch.setenv(sk.FREEZE_ORPHAN_STATE_ENV, str(state))
    fake = _FakeRun()
    monkeypatch.setattr(sk.subprocess, "run", fake)
    sk._alert_freeze_orphans(_orphans(30))
    _chk(fake.calls == [], "关闭时不得调用 notify")
    _chk(not state.exists(), "关闭时不得写状态文件")


def test_e7_delta_helper_pure():
    """纯函数对账: None ⇒ 全量;有基线 ⇒ 差值(负数=下降, 由调用方下调基线)。"""
    _chk(sk._freeze_orphan_delta(7, None) == 7, "无基线=全量")
    _chk(sk._freeze_orphan_delta(21, 16) == 5, "21-16=5")
    _chk(sk._freeze_orphan_delta(3, 11) == -8, "下降为负")
    _chk(sk.FREEZE_ORPHAN_GROWTH_THRESHOLD == 5, "阈值=5(报告 §3.2 定)")


# ════════════════════════════════════════════════════════════════════════════
# 冻结运行日 + 断言下限(§18 L51 / 防「0 断言假绿」)
# ════════════════════════════════════════════════════════════════════════════
def test_f1_frozen_run_date_no_today(monkeypatch):
    """冻结运行日: 决策路径不得读真实「今天」(把 today_ymd 换成炸弹, 隔天跑结论不变)。"""
    def _boom(*_a, **_k):
        raise AssertionError("决策路径不应调用 today_ymd(必须显式传 run_date)")

    monkeypatch.setattr(ha, "today_ymd", _boom)
    plan = ha.plan_index_daily_alerts(_batch(3), RUN_DATE, "runner")
    _chk(plan[0]["dedup_suffix"] == "runner:small", "plan 不受 today 影响")
    rec = _Recorder()
    monkeypatch.setattr(ha, "send_alert", rec)
    ha._alert_index_daily(_batch(3), RUN_DATE, "runner")
    _chk(rec.calls[0]["dedup_key"] == f"history_overwrite:index_daily:{RUN_DATE}:runner:small",
         f"key 必须用显式 run_date: {rec.calls[0]['dedup_key']}")


def test_f2_assertion_floor():
    """断言下限: 防收集/执行异常致「0 断言假绿」。"""
    _chk(_N[0] >= _MIN_ASSERTIONS, f"断言数下限 {_MIN_ASSERTIONS}, 实得 {_N[0]}")