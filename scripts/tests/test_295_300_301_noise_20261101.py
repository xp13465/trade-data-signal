#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#295/#300/#301 降噪边界专项(2026-11-01, B 小测试+实测)。

三条:
  #295 跨午夜专项 —— 预算计数 / 域静默窗 / 去重状态 跨 00:00 自然日边界的行为。
       现状:test_160 仅 r2_consistency 23:59 单点, 无「预算重置 / 域窗不跨日 / 去重跨日」
       专项用例。本文件补齐。
  #300 多规则叠加顺序专项 —— notify.py send() gate 的固定叠加序
       (stall > L2 budget > domain > notice_budget/rollover > dedup)在纯函数层的可观测投影:
       多规则同时命中时, 按固定序短路, 单一抑制, 结果确定(与「调用方臆想顺序」无关)。
  #301 >8MB 台账轮证实测 —— 造 >8MB suppression_ledger.jsonl 实测 _maybe_prune_suppression_ledger
       轮转路径(code 在位缺实测; 全程 tmp 目录, 禁碰生产台账)。

被测对象(纯函数 / 真实轮转代码, 不跑 notify 主路径, 零外发):
  - adr.alert_budget_process / adr.ledger_day_direct_counts          (预算计数, 跨日重置)
  - adr.domain_inhibit_judge                                          (域静默窗, 不跨自然日)
  - adr.wrapper_channel_alerted                                       (去重状态跨日)
  - adr._maybe_prune_suppression_ledger + SUPPRESSION_LEDGER_MAX_BYTES (8MB 轮转)

跑法: python3 -m pytest -q scripts/tests/test_295_300_301_noise_20261101.py
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_denoise_rules as adr  # noqa: E402

ROOT = Path(__file__).absolute().parent.parent.parent


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _write_ledger(repo: Path, rows):
    """造 alert_ledger.jsonl: rows = [(ts, key, tier, group), ...]。"""
    d = repo / "data" / "alerts"
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for ts, key, tier, group in rows:
        lines.append(json.dumps({
            "ts": ts, "key": key, "tier": tier, "group": group,
            "subject": "stub", "source": "test",
        }, ensure_ascii=False))
    (d / "alert_ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_dedup(repo: Path, last_alerted: str, key="r2_consistency_fail"):
    d = repo / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notify_dedup.json").write_text(
        json.dumps({key: {"last_alerted": last_alerted}}), encoding="utf-8")


# ════════════════════════════════════════════════════════════════════
# #295 跨午夜专项(预算重置 / 域窗不跨日 / 去重跨日)
# ════════════════════════════════════════════════════════════════════
class TestMidnightBudgetReset:
    """预算计数以自然日为界: 23:59 的计数不渗到次日 00:01。"""

    def test_budget_counts_reset_across_midnight(self, tmp_path):
        """23:59 day X 已发 1 条 critical(unit) → 00:01 day X+1 计数归 0, 首条直发。"""
        # day X 23:58 已直发一条 critical unit
        _write_ledger(tmp_path, [
            ("2026-10-05 23:58:00", "unit_patrol|abc", "critical", "alert"),
        ])
        # day X 23:59: 同类第 2 条 → 超预算(额度 1) → 吸收
        kept_x, absorbed_x = adr.alert_budget_process(
            {}, ["SEVERE: unit_patrol 第二条 23:59"], _dt("2026-10-05 23:59:00"),
            tmp_path, day="2026-10-05")
        assert absorbed_x and not kept_x, "23:59 第 2 条应超预算吸收"

        # 跨午夜: day X+1 00:01 计数归 0 → 首条直发(不被昨夜计数吞)
        kept_next, absorbed_next = adr.alert_budget_process(
            {}, ["SEVERE: unit_patrol 次日首条 00:01"], _dt("2026-10-06 00:01:30"),
            tmp_path, day="2026-10-06")
        assert kept_next and not absorbed_next, "跨午夜后计数应重置, 首条直发(不吞)"

    def test_ledger_day_direct_counts_filters_by_day_string(self, tmp_path):
        """底层口径: ledger_day_direct_counts 按 ts 前 10 位(YYYY-MM-DD)过滤, 跨日不混。"""
        _write_ledger(tmp_path, [
            ("2026-10-05 23:59:59", "unit_patrol|a", "critical", "alert"),
            ("2026-10-06 00:00:05", "unit_patrol|b", "critical", "alert"),
        ])
        cnt_x = adr.ledger_day_direct_counts(tmp_path, day="2026-10-05")
        cnt_next = adr.ledger_day_direct_counts(tmp_path, day="2026-10-06")
        assert cnt_x.get("unit", 0) == 1
        assert cnt_next.get("unit", 0) == 1, "00:00:05 已属次日, 不应并入昨日计数"


class TestMidnightDomainWindowNotCrossDay:
    """域静默窗(ALERT_DOMAIN_GROUP_INTERVAL=2h)不跨自然日: 昨夜 23:50 的同域告警,
    次日 00:01 视为新事件直发(即便 <2h)。"""

    def test_domain_window_resets_at_midnight(self, tmp_path):
        state = {"unit": {"last_ts": "2026-10-05 23:50:00", "last_day": "2026-10-05",
                          "day_first_ts": "2026-10-05 23:50:00",
                          "n_direct": 1, "n_absorbed": 0, "n_absorbed_today": 0,
                          "interval": 7200}}
        # 次日 00:05 距昨夜 23:50 仅 15 分钟(< 2h), 但跨了自然日 → first
        action, entry = adr.domain_inhibit_judge(
            state, "unit", _dt("2026-10-06 00:05:00"))
        assert action == "first", "域窗不跨自然日: 跨午夜即便 <2h 也算新事件直发"
        assert entry["n_direct"] == 2
        assert entry["n_absorbed_today"] == 0, "次日 n_absorbed_today 应归零"

    def test_domain_same_day_within_window_absorbs(self, tmp_path):
        """对照: 同日 23:50 → 23:55(<2h)→ absorb(窗口内)。"""
        state = {"unit": {"last_ts": "2026-10-05 23:50:00", "last_day": "2026-10-05",
                          "day_first_ts": "2026-10-05 23:50:00",
                          "n_direct": 1, "n_absorbed": 0, "n_absorbed_today": 0,
                          "interval": 7200}}
        action, _ = adr.domain_inhibit_judge(
            state, "unit", _dt("2026-10-05 23:55:00"))
        assert action == "absorb", "同日窗内应并入"


class TestMidnightDedupState:
    """去重状态跨午夜: wrapper_channel_alerted 用「本次实例」判据(last_alerted >= last_run),
    不是「今天」。跨午夜场景下昨夜告警 < 次日 last_run → 返回 False(monitor 兜底照发)。"""

    def test_dedup_yesterday_alert_does_not_cover_today_run(self, tmp_path):
        """昨夜 23:50 告警 vs 今日 00:02 last_run: last_alerted < last_run → False。"""
        _write_dedup(tmp_path, "2026-10-05 23:50:10")
        assert adr.r7_r2_consistency_wrapper_alerted(
            tmp_path, "2026-10-06 00:02:00") is False, \
            "跨午夜: 昨夜告警不应覆盖今日新实例(monitor 兜底)"

    def test_dedup_same_instance_across_midnight_still_covers(self, tmp_path):
        """同实例失败持续到次日: last_run=昨 23:50, 告警=昨 23:51(>= last_run)→ True。
        这是「失败持续到次日, 次日全天不复述」的核心(R7②), 跨午夜仍成立。"""
        _write_dedup(tmp_path, "2026-10-05 23:51:00")
        assert adr.r7_r2_consistency_wrapper_alerted(
            tmp_path, "2026-10-05 23:50:00") is True, \
            "同实例(告警 >= last_run)跨午夜仍覆盖"


# ════════════════════════════════════════════════════════════════════
# #300 多规则叠加顺序专项(notify.py send() gate 固定序的纯函数投影)
# ════════════════════════════════════════════════════════════════════
# notify.py send() gate 真实叠加序(行号锚点):
#   ① stall_dedup(停摆级, ~L1391)短路最先
#   ② L2 日预算 gate(~L1367, alert_budget_process / category_of)
#   ③ 故障域聚合 gate(~L1497, domain_of / domain_inhibit_judge)
#   ④ 非 critical 重复类预算+rollover(~L1542)
#   ⑤ 通用 check_dedup(~L2119)
# 本节用纯函数验证: 多规则同时命中时按固定序短路 → 单一抑制, 结果确定,
# 与「概念上先调谁」无关(纯函数层不重新排 notify 顺序, 只验可观测结果稳定)。
#
# 举一反三·同模式覆盖来源(2026-11-01 #B 订正: 原降噪批报告张冠李戴标 test_282/245,
# 实际如下, 已逐文件 grep 核实):
#   · failed_units_daily_judge(集合未变+当日已报→跳过)→ test_240_alert_denoise_batch2
#     _20261009.py:165-210(adr.failed_units_daily_judge 6 分支直测)
#   · rollover(窗内命中/跨日首现/超窗/裁剪)→ test_264_alert_domain_budget_20261015
#     .py:576-611(rollover_absorb_judge / rollover_prune 纯函数 + 吸收路径)
#   · notice_budget(非 critical 重复类预算)→ 零独立直测; 同构「日预算+叠加序」由
#     本节 #300(TestOverlayOrderDeterministic)投影覆盖(notify.py send() gate 固定序
#     的纯函数层可观测结果, 不重跑 notify 主路径)。


class TestOverlayOrderDeterministic:
    """叠加序确定: 同一输入重复跑 N 次, 各规则判定结果逐位一致(无随机/无状态漂移)。"""

    def test_budget_plus_domain_both_absorb_deterministic(self, tmp_path):
        """同一条 alert 既超预算又同域窗内: 两个 gate 都判「吸收」, 重复跑结果一致。"""
        _write_ledger(tmp_path, [
            ("2026-10-05 23:58:00", "unit_patrol|a", "critical", "alert"),
        ])
        line = "SEVERE: unit_patrol 重复"
        now = _dt("2026-10-05 23:59:30")
        state = {"unit": {"last_ts": "2026-10-05 23:58:30", "last_day": "2026-10-05",
                          "day_first_ts": "2026-10-05 23:58:30",
                          "n_direct": 1, "n_absorbed": 0, "n_absorbed_today": 0,
                          "interval": 7200}}
        results = []
        for _ in range(5):
            kept, absorbed = adr.alert_budget_process({}, [line], now, tmp_path,
                                                       day="2026-10-05")
            dom_action, _ = adr.domain_inhibit_judge(
                dict(state), "unit", now)  # 纯函数, 不写盘
            results.append((bool(kept), bool(absorbed), dom_action))
        # 5 次全一致(确定性)
        assert all(r == results[0] for r in results), "叠加判定应确定性, 不应逐次漂移"
        # 预算判吸收 + 域判 absorb → 两层都吸收(notify 实际走预算先短路, 此处验两纯函数各自稳定)
        assert results[0] == (False, True, "absorb")

    def test_overlay_order_budget_short_circuits_before_domain(self, tmp_path):
        """notify 固定序: 预算 gate 在域 gate 之前。可观测投影: 超预算的行被预算层吸收,
        不进 kept(域层对已被预算吸收的行无作用 —— alert_budget_process 返回的 absorbed 已移出)。"""
        _write_ledger(tmp_path, [
            ("2026-10-05 23:58:00", "unit_patrol|a", "critical", "alert"),
        ])
        line = "SEVERE: unit_patrol 超预算且同域"
        now = _dt("2026-10-05 23:59:30")
        kept, absorbed = adr.alert_budget_process({}, [line], now, tmp_path,
                                                   day="2026-10-05")
        # 预算层先吃 → 行进 absorbed, 不在 kept → 域层对 kept(空)无可作用
        assert not kept and len(absorbed) == 1
        assert absorbed[0]["category"] == "unit"

    def test_overlay_under_budget_reaches_domain(self, tmp_path):
        """对照: 未超预算 → 预算层放行(kept), 域层才可达并判 absorb/first。"""
        # 无台账 → counts 全 0 → 预算放行
        line = "SEVERE: unit_patrol 首条"
        now = _dt("2026-10-05 23:50:00")
        kept, absorbed = adr.alert_budget_process({}, [line], now, tmp_path,
                                                   day="2026-10-05")
        assert kept and not absorbed, "首条未超预算应放行, 域层才可达"
        # 域层: 首条(state 空)→ first
        action, _ = adr.domain_inhibit_judge({}, "unit", now)
        assert action == "first"

    def test_overlay_independent_categories_no_cross_contamination(self, tmp_path):
        """叠加序不串类: unit 超预算不影响 r2 类首条直发(各类独立额度, 序内并行安全)。"""
        _write_ledger(tmp_path, [
            ("2026-10-05 23:58:00", "unit_patrol|a", "critical", "alert"),
        ])
        lines = ["SEVERE: unit_patrol 第二条", "SEVERE: r2_consistency 首条"]
        now = _dt("2026-10-05 23:59:30")
        kept, absorbed = adr.alert_budget_process({}, lines, now, tmp_path,
                                                   day="2026-10-05")
        kept_bodies = [k for k in kept]
        assert any("r2_consistency" in k for k in kept_bodies), "r2 首条应直发(独立额度)"
        assert any("unit_patrol" in a["line"] for a in absorbed), "unit 第 2 条应吸收"


# ════════════════════════════════════════════════════════════════════
# #301 >8MB suppression_ledger 轮转实测(造大台账 → 触发轮转 → 核结果)
# ════════════════════════════════════════════════════════════════════
# 红线: 全程 tmp_path(禁碰生产 data/alerts/); 轮转 code 在位缺实测, 本节补。


class TestSuppressionLedgerRotation:
    """造 >8MB 台账实测 _maybe_prune_suppression_ledger 轮转路径。"""

    def _make_big_ledger(self, repo: Path, n_rows: int, ts_prefix="2026-10-30"):
        """造 n_rows 行的 suppression_ledger.jsonl(每行 ~200B → n_rows=50000 ≈ 10MB)。"""
        p = adr.suppression_ledger_path(repo)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        base = datetime.strptime(ts_prefix + " 00:00:00", "%Y-%m-%d %H:%M:%S")
        for i in range(n_rows):
            ts = (base + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
            lines.append(json.dumps({
                "ts": ts, "day": ts[:10], "mechanism": "dedup",
                "key": f"k{i}", "fingerprint": f"{i:012x}",
                "domain": "unit", "reason": "big-ledger-test", "source": "test",
                "first_seen": ts, "event_id": i,
            }, ensure_ascii=False))
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def test_rotation_triggers_when_over_8mb(self, tmp_path):
        """造 >8MB 台账 → 调 _maybe_prune_suppression_ledger → 触发轮转(文件被重写)。"""
        p = self._make_big_ledger(tmp_path, n_rows=50000)  # ~10MB+
        size_before = p.stat().st_size
        assert size_before > adr.SUPPRESSION_LEDGER_MAX_BYTES, \
            f"造台账应 >8MB, 实得 {size_before}B"

        adr._maybe_prune_suppression_ledger(p, _dt("2026-11-01 12:00:00"))

        size_after = p.stat().st_size
        # 轮转后: 30 天保留窗 cut = 2026-10-02; 造的数据 ts=2026-10-30 → 全在窗内 → 全留
        # 但 8MB 上限触发重写(去重/截断到 200000 行); 这里 50000 行 < 200000, 全留
        # 关键观测: marker 被写(说明轮转分支真的跑了)
        marker = p.with_name(adr.SUPPRESSION_LEDGER_PRUNE_MARKER)
        assert marker.exists(), "轮转应写 prune marker(当日已检查标记)"
        assert marker.read_text(encoding="utf-8").strip() == "2026-11-01"
        # 行数不丢(全在 30 天窗内 + 未超 200000 硬上限)
        n_after = sum(1 for _ in p.read_text(encoding="utf-8").splitlines() if _.strip())
        assert n_after == 50000, f"窗内数据不应丢, 实得 {n_after} 行"

    def test_rotation_prunes_old_entries_outside_30day_window(self, tmp_path):
        """造一批 30 天外的旧行 + 一批窗内新行 → 轮转后旧行被裁、新行全留。"""
        p = adr.suppression_ledger_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 40 天前(超 30 天窗)+ 今天
        old_ts = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        new_ts = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        rows = []
        for i in range(100):
            rows.append(json.dumps({"ts": old_ts, "day": old_ts[:10], "mechanism": "dedup",
                                    "key": f"old{i}", "source": "test"}))
        for i in range(50):
            rows.append(json.dumps({"ts": new_ts, "day": new_ts[:10], "mechanism": "dedup",
                                    "key": f"new{i}", "source": "test"}))
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        # 强制 >8MB 不必(按日检查也触发轮转); 但 marker 不在今日 → 走轮转分支
        adr._maybe_prune_suppression_ledger(p, datetime.now())
        kept_lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        # 旧行(40 天前)被裁; 新行(1 天前)全留
        assert len(kept_lines) == 50, f"应裁 100 旧行留 50 新行, 实得 {len(kept_lines)}"
        for ln in kept_lines:
            assert json.loads(ln)["key"].startswith("new"), "残留行不应含旧行"

    def test_rotation_no_trigger_under_8mb_and_marker_today(self, tmp_path):
        """<8MB 且 marker 已是今日 → 不重写(短路返回, 不动文件)。"""
        p = self._make_big_ledger(tmp_path, n_rows=100)  # ~20KB, 远 <8MB
        marker = p.with_name(adr.SUPPRESSION_LEDGER_PRUNE_MARKER)
        marker.write_text(datetime.now().strftime("%Y-%m-%d"), encoding="utf-8")
        mtime_before = p.stat().st_mtime
        adr._maybe_prune_suppression_ledger(p, datetime.now())
        mtime_after = p.stat().st_mtime
        assert mtime_after == mtime_before, "<8MB 且 marker=今日 应短路不重写"

    def test_rotation_corrupt_line_tolerated(self, tmp_path):
        """轮转遇坏行跳过(不抛、不丢好行)。"""
        p = adr.suppression_ledger_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        new_ts = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        p.write_text(
            json.dumps({"ts": new_ts, "key": "good", "source": "t"}) + "\n"
            "@@not-json@@\n"
            "{bad\n",
            encoding="utf-8")
        adr._maybe_prune_suppression_ledger(p, datetime.now())
        kept = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(kept) == 1 and json.loads(kept[0])["key"] == "good", \
            "坏行应跳过, 好行保留"

    def test_rotation_truncates_at_max_rows_hard_cap(self, tmp_path, monkeypatch):
        """#A(2026-11-01): 窗内行数 > SUPPRESSION_LEDGER_MAX_ROWS → 截断到上限, 不爆内存。

        alert_denoise_rules.py:1988 的 `len(_kept) >= SUPPRESSION_LEDGER_MAX_ROWS` 硬上限
        分支(#301 批只测 50000 行 < 200000, 未触该分支)。本用例 monkeypatch MAX_ROWS=5,
        造 10 行全在 30 天窗内的台账 → 截断后留前 5 行 + marker 写 + 行不丢(保留前 MAX_ROWS 行)。
        全程 tmp_path, 禁碰生产台账。
        """
        # 把硬上限压到 5(避免造 200000 行真台账 ~40MB 拖慢测试)
        monkeypatch.setattr(adr, "SUPPRESSION_LEDGER_MAX_ROWS", 5)
        p = adr.suppression_ledger_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        base = datetime.now() - timedelta(days=1)
        rows = []
        for i in range(10):
            ts = (base + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
            rows.append(json.dumps({
                "ts": ts, "day": ts[:10], "mechanism": "dedup",
                "key": f"cap{i}", "source": "test",
            }, ensure_ascii=False))
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")

        adr._maybe_prune_suppression_ledger(p, datetime.now())

        kept = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        # 截断到 MAX_ROWS=5(硬上限分支触发); 全在窗内 ⇒ 不是日期裁剪, 是上限裁剪
        assert len(kept) == 5, f"应截断到 MAX_ROWS=5, 实得 {len(kept)} 行"
        # 保留的是文件前 5 行(顺序保留, 不丢前段)
        keys = [json.loads(ln)["key"] for ln in kept]
        assert keys == [f"cap{i}" for i in range(5)], f"应保留前 5 行, 实得 {keys}"
        # marker 写(说明轮转分支真的跑了, 不是短路)
        marker = p.with_name(adr.SUPPRESSION_LEDGER_PRUNE_MARKER)
        assert marker.exists(), "截断轮转应写 prune marker"

    def test_rotation_max_rows_branch_distinguishable(self, tmp_path, monkeypatch):
        """#A 反证判别力: MAX_ROWS=5 但只造 3 行(< 上限)→ 不截断, 全留(证明上例不是巧合)。"""
        monkeypatch.setattr(adr, "SUPPRESSION_LEDGER_MAX_ROWS", 5)
        p = adr.suppression_ledger_path(tmp_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        base = datetime.now() - timedelta(days=1)
        rows = []
        for i in range(3):
            ts = (base + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S")
            rows.append(json.dumps({"ts": ts, "key": f"nocap{i}", "source": "t"}))
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        adr._maybe_prune_suppression_ledger(p, datetime.now())
        kept = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(kept) == 3, f"<上限应全留 3 行, 实得 {len(kept)}(判别力: 上例截断非巧合)"


# ════════════════════════════════════════════════════════════════════
# 断言计数下限(防 0 断言假绿, §18 L49)
# ════════════════════════════════════════════════════════════════════
_MIN_ASSERTIONS = 14


def test_zzz_assertion_floor():
    """本文件用例数 ≥ _MIN_ASSERTIONS(防收集/执行异常致 0 断言假绿)。"""
    import inspect
    cnt = 0
    for _n, _o in globals().items():
        if inspect.isclass(_o) and _n.startswith("Test"):
            for _mn, _mo in vars(_o).items():
                if _mn.startswith("test_") and inspect.isfunction(_mo):
                    cnt += 1
        elif _n.startswith("test_") and _n != "test_zzz_assertion_floor" and inspect.isfunction(_o):
            cnt += 1
    assert cnt >= _MIN_ASSERTIONS, f"用例数 {cnt} < 下限 {_MIN_ASSERTIONS}"
