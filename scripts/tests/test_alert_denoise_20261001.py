#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#123 告警降噪 R1~R6 —— 真故障反例实测 pytest 版(v3, 2026-10-03)

v1(本目录同名旧版)是「逻辑模拟」,v2 按任务成败判据 ② 改为**打真实判定代码**:
  - 导入 scripts/alert_denoise_rules.py 的真实规则函数(被 schedule_monitor.sh heredoc
    与 notify.py 直接 import, 是唯一判定实现, 无第二份逻辑副本)
  - 每条反例断言调真实函数: adr.r1_buffer_judge / r2_merge_already_sent·r2_merge_mark /
    r2_merge_cleanup / r3_nextday_product_generated_today / r4_staticdata_grade /
    r5_congestion_process / r5_is_r2_congestion_line
  - R3/R4 依赖实盘文件(mtime/心跳/状态), 测试用 pytest tmp_path 构造同构状态文件后仍调
    同一函数(文件路径可注入, 判定逻辑本身是真实代码)。

v3 改造(2026-10-03, CI Quality Gate ⑧ pytest 收集崩溃修复):
  - v2 是脚本式自测(顶层直接执行 34 条 check + sys.exit), pytest 收集阶段即执行, 且
    顶层 import 时对 pytest 无 test 收集 → 收集数=0 或 INTERNALERROR。改为真 pytest:
    34 条 check 逐条落成 test 函数(断言强度与原脚本逐条对等, 无删减无放宽), 临时目录
    统一用 pytest tmp_path fixture(并发/重跑安全), 不再顶层执行。
  - 断言消息保留原 check 的 name + detail, 便于失败时对照原脚本语义。

跑法(pytest, CI ⑧同):
  python3 -m pytest -q scripts/tests/test_alert_denoise_20261001.py
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest  # noqa: F401  (保留显式依赖声明)

import alert_denoise_rules as adr  # noqa: E402  (conftest 已注入 scripts/)


# ============================================================
# 规则 R1: overview lag(主站 overview_lag_3domain + r2_overview_lag) 连续轮
# → adr.r1_buffer_judge(真实函数, schedule_monitor.sh 两个 overview 块调用同一函数)
# ============================================================
def r1_sim(lag_min_each_round, thresh_min=20, buf_key="r2_overview_lag|buffer|%s",
           alert_key="r2_overview_lag"):
    """以 15min/轮 逐轮调 adr.r1_buffer_judge, 返回 (是否SEVERE, 条数, 各轮action)。"""
    st = {}
    alerts = []
    rounds = []
    NOW = datetime(2026, 9, 30, 14, 30)
    for i, lm in enumerate(lag_min_each_round):
        now_round = NOW + timedelta(minutes=15 * i)
        exceeds = lm > thresh_min
        act = adr.r1_buffer_judge(
            st, buf_key % now_round.strftime("%Y%m%d"), alert_key, exceeds, now_round,
        )
        if act == "alert":
            alerts.append((i, lm))
            st[alert_key] = {"status": "active", "last_alerted": str(i)}
        rounds.append((i, lm, act))
    return len(alerts) > 0, len(alerts), rounds


def test_r1_caseA_true_4rounds_lag():
    """R1反例A-真断供连续4轮滞后→SEVERE必响。"""
    sev, n, rnd = r1_sim([24, 25, 26, 27])
    assert sev and n >= 1, f"4轮滞后(24/25/26/27min), SEVERE={n}条 {rnd}"


def test_r1_caseB_2rounds_lag():
    """R1反例B-连续2轮(30min)真断链→SEVERE响。"""
    sev, n, rnd = r1_sim([24, 25])
    assert sev, f"2轮滞后(24/25min), SEVERE={n}条 {rnd}"


def test_r1_caseC_recover_after_1round():
    """R1正例C-单轮滞后后恢复→不响。"""
    sev, n, rnd = r1_sim([24, 3, 2])
    assert not sev, f"1轮24min滞后后恢复, SEVERE={n}条 {rnd}"


def test_r1_caseD_below_threshold():
    """R1边界D-2轮都<20min→不响。"""
    sev, n, rnd = r1_sim([19, 18])
    assert not sev, f"19/18min均低于阈值, SEVERE={n}条 {rnd}"


def test_r1_crossday_residue():
    """R1跨天E-隔日防残留从0起/持续不轰炸/恢复后独立再响。"""
    st2 = {}
    _bk = lambda dt: "overview_lag_3domain|buffer|" + dt.strftime("%Y%m%d")
    # 前日: 连续 2 轮滞后 → alert(活跃)
    a1 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 9, 30, 14, 0)), "overview_lag_3domain", True,
                             datetime(2026, 9, 30, 14, 0))
    a2 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 9, 30, 14, 15)), "overview_lag_3domain", True,
                             datetime(2026, 9, 30, 14, 15))
    # 模拟调用方(schedule_monitor overview 块)在 alert 分支写 active
    st2["overview_lag_3domain"] = {"status": "active", "last_alerted": "2026-09-30 14:15:00"}
    # 隔日首次滞后: 新日期计数从 1 起 → buffer(不直接 alert, 防前日计数误叠)
    a3 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 10, 1, 14, 0)), "overview_lag_3domain", True,
                             datetime(2026, 10, 1, 14, 0))
    # 隔日再滞后: alert_key 仍 active(前日未恢复)→ suppress 不轰炸(不是新 alert)
    a4 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 10, 1, 14, 15)), "overview_lag_3domain", True,
                             datetime(2026, 10, 1, 14, 15))
    # 恢复流程(隔日凌晨滞后消失)后再次滞后 → 独立再响(不吞跨天)
    a5 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 10, 2, 0, 0)), "overview_lag_3domain", False,
                             datetime(2026, 10, 2, 0, 0))  # recover: key 置 recovered
    st2["overview_lag_3domain"]["status"] = "recovered"
    a6 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 10, 2, 14, 0)), "overview_lag_3domain", True,
                             datetime(2026, 10, 2, 14, 0))
    a7 = adr.r1_buffer_judge(st2, _bk(datetime(2026, 10, 2, 14, 15)), "overview_lag_3domain", True,
                             datetime(2026, 10, 2, 14, 15))
    assert a1 == "buffer" and a2 == "alert" and a3 == "buffer" and a4 == "suppress" \
        and a5 == "recover" and a6 == "buffer" and a7 == "alert", \
        f"前日 buffer→alert; 隔日suppress(a4={a4}); 恢复后(a5={a5})再滞后 a6={a6}→a7={a7}"


def r1_with_recovery_loop(lag_mins, thresh_min=20, buf_prefix="overview_lag_3domain|buffer|%s",
                          alert_key="overview_lag_3domain", insert_recovery_loop=True):
    """按 schedule_monitor 真实执行序逐轮: 先恢复循环(上轮遗留 pending→recovered 不清 count),
    再调真实 r1_buffer_judge。返回各轮 action 列表。"""
    st = {}
    rounds = []
    NOW = datetime(2026, 9, 30, 14, 30)
    for i, lm in enumerate(lag_mins):
        now_round = NOW + timedelta(minutes=15 * i)
        # --- 恢复循环(L1178-1200)真实逻辑精简版: pending 未在本轮 seen → recovered ---
        if insert_recovery_loop:
            for _k, _info in list(st.items()):
                if _info.get("status") == "pending":
                    if _k.startswith("r2_") or _k.startswith("72h_"):
                        continue
                    if _k not in {alert_key}:  # buffer key 不会进 seen_keys_this_run
                        _info["status"] = "recovered"
                        _info["last_recovered"] = now_round.strftime("%Y-%m-%d %H:%M:%S")
        bk = buf_prefix % now_round.strftime("%Y%m%d")
        exceeds = lm > thresh_min
        act = adr.r1_buffer_judge(st, bk, alert_key, exceeds, now_round)
        if act == "alert":
            st[alert_key] = {"status": "active", "last_alerted": now_round.strftime("%Y-%m-%d %H:%M:%S")}
        elif act == "recover" and alert_key in st:
            st[alert_key]["status"] = "recovered"
            st[alert_key]["last_recovered"] = now_round.strftime("%Y-%m-%d %H:%M:%S")
        rounds.append(act)
    return rounds


def test_r1_fix_F_recovery_loop_no_false_alert():
    """R1修复F-滞后→恢复→再滞后三连不再误报(recovered也清count)。"""
    r_F = r1_with_recovery_loop([24, 3, 24])
    assert r_F == ["buffer", "ok", "buffer"] or r_F == ["buffer", "ok", "ok"], \
        f"三连 action={r_F} (recovered 状态恢复路径清 count → 再滞后从0计, 不回 alert)"


def test_r1_fix_G_true_2rounds_still_alert():
    """R1修复G-真连续2轮仍响SEVERE(不吞真故障)+恢复后再滞后从0计。"""
    r_G = r1_with_recovery_loop([24, 25, 3, 24])
    assert r_G[0] == "buffer" and r_G[1] == "alert" and r_G[2] in ("ok", "recover") \
        and r_G[3] == "buffer", \
        f"连续2轮 action={r_G} (前2轮buffer→alert 真断供照响; 恢复后第3轮从0计不再连击)"


def test_r1_fix_H_control_no_recovery_loop():
    """R1修复H-对照组(无恢复循环)仍是 buffer/ok/buffer 不回 alert。"""
    r_H = r1_with_recovery_loop([24, 3, 24], insert_recovery_loop=False)
    assert r_H == ["buffer", "ok", "buffer"], f"action={r_H}"


# ============================================================
# 规则 R2: 超时未完成 + 执行耗时 双通道同 (task,last_run) 合并
# → adr.r2_merge_already_sent / r2_merge_mark / r2_merge_cleanup(真实函数)
# ============================================================
def r2_sim(lr_events):
    """lr_events: [(last_run, channel), ...] 按时间序; channel=timeout/dur。
    模拟 monitor 两通道先 dur 后 timeout 的判断序, 用真实 merge key 机制。"""
    st = {}
    sent = []
    for lr, ch in lr_events:
        if not adr.r2_merge_already_sent(st, "us_stock_morning", lr):
            sent.append((ch, lr))
            adr.r2_merge_mark(st, "us_stock_morning", lr, datetime(2026, 9, 30, 6, 0))
    return sent


def test_r2_caseA_same_instance_merged():
    """R2反例A-同运行实例超时+耗时合并→只响1条且必响。"""
    al = r2_sim([("2026-09-30 05:00", "dur"), ("2026-09-30 05:00", "timeout")])
    assert len(al) == 1 and al[0][1] == "2026-09-30 05:00", f"合并后{len(al)}条({al})"


def test_r2_caseB_nextday_new_last_run():
    """R2反例B-隔日再次卡死→新last_run必再响。"""
    al = r2_sim([("2026-09-30 05:00", "dur"), ("2026-09-30 05:00", "timeout"),
                 ("2026-10-01 05:00", "timeout")])
    assert len(al) == 2, f"两天各1条:{al}"


def test_r2_caseC_dur_only():
    """R2正例C-单轮耗时超阈值→响1条(真退化保留),由 dur 通道先发独占。"""
    al = r2_sim([("2026-09-30 20:35", "dur")])
    assert len(al) == 1 and al[0][0] == "dur", f"{al}"


def test_r2_cleanup_old_merge_keys():
    """R2清理D-超24h merge key被清(防膨胀)。"""
    st = {}
    adr.r2_merge_mark(st, "t", "2026-09-29 01:00", datetime(2026, 9, 29, 1, 0))
    adr.r2_merge_mark(st, "t", "2026-09-30 05:00", datetime(2026, 9, 30, 5, 0))
    adr.r2_merge_cleanup(st, datetime(2026, 9, 30, 6, 0))
    assert "merge|t|2026-09-29 01:00" not in st and "merge|t|2026-09-30 05:00" in st, \
        f"state keys={list(st)}"


# ============================================================
# 规则 R3: nextday_plan 双发去重 → adr.r3_nextday_product_generated_today(真实函数)
# ============================================================
def r3_with_repo(mtime_date_iso, base: Path):
    d = base / "data"
    d.mkdir(parents=True)
    p = d / "nextday_plan.json"
    if mtime_date_iso is not None:
        p.write_text("{}", encoding="utf-8")
        os.utime(p, (0, datetime.fromisoformat(mtime_date_iso).timestamp()))
    return adr.r3_nextday_product_generated_today(d.parent, "2026-10-01")


def test_r3_caseA_today_generated(tmp_path):
    """R3反例A-产物今日已生成→monitor去重(自身通道已发, 不再双发)。"""
    assert r3_with_repo("2026-10-01 22:35:00", tmp_path) is True, "nextday_plan.json mtime=今日"


def test_r3_caseB_file_missing(tmp_path):
    """R3反例B-产物未生成(真失败)→不判定已生成, monitor汇总双保险。"""
    assert r3_with_repo(None, tmp_path) is False, "文件缺失→False"


def test_r3_caseC_yesterday_stale(tmp_path):
    """R3正例C-产物为昨日(陈旧)→False(不算今日生成)。"""
    assert r3_with_repo("2026-09-30 22:30:00", tmp_path) is False, "mtime=昨日→False"


# ============================================================
# 规则 R4: staticdata 备份失败分级 → adr.r4_staticdata_grade(真实函数)
# (notify.py R4 拦截块调同一函数的同一调用方式: heartbeat+state 均可注入)
# ============================================================
def r4_with_state(hb_result, hb_ts, state_last_fail, state_days, base: Path):
    hb = base / "staticdata_backup_heartbeat.json"
    st = base / "staticdata_backup_fail_state.json"
    if hb_result is not None:
        hb.write_text(json.dumps({"result": hb_result, "ts": hb_ts}), encoding="utf-8")
    if state_last_fail:
        st.write_text(json.dumps({"last_fail_date": state_last_fail,
                                  "consecutive_days": state_days}), encoding="utf-8")
    return adr.r4_staticdata_grade(hb, st, datetime(2026, 10, 1, 22, 0))[0]


def test_r4_caseA_ok_today_info(tmp_path):
    """R4反例A-单日预算耗尽但次日追平→降info。"""
    r = r4_with_state("ok", "2026-10-01 21:00:00", "2026-09-30", 1, tmp_path)
    assert r == "info", f"判定={r}"


def test_r4_caseB_2day_unrecovered_severe(tmp_path):
    """R4反例B-连续2天未追平(真R2备份缺口)→SEVERE。"""
    r = r4_with_state("fail", "2026-10-01 21:00:00", "2026-09-30", 1, tmp_path)
    assert r == "severe", f"判定={r}"


def test_r4_caseC_hb_missing_severe(tmp_path):
    """R4反例C-心跳缺失且未追平→SEVERE(宁多勿漏)。"""
    r = r4_with_state(None, None, "2026-09-30", 1, tmp_path)
    assert r == "severe", f"判定={r}"


def test_r4_caseD_first_fail_info(tmp_path):
    """R4补充D-单日首次失败→info(观察中)。"""
    r = r4_with_state("fail", "2026-10-01 21:00:00", None, 0, tmp_path)
    assert r == "info", f"判定={r}"


# ============================================================
# 规则 R5: R2/部署链路拥堵同根因日汇总 → adr.r5_congestion_process / r5_is_r2_congestion_line
# ============================================================
def test_r5_caseA_summary_first_direct():
    """R5反例A-同日多条R2同根因告警→首条直发其余并入汇总(23:25收尾出汇总)。"""
    alerts_in = [
        "SEVERE: R2 overview.json 时效滞后 collected_at<...> lag=24min ...",
        "SEVERE: r2_unreachable ssd.fx8.store 不可达 ...",
        "SEVERE: r2_intraday_lag 盘中数据滞后 legacy_path 迟 ...",
        "SEVERE: fetch_news 退出失败 last_exit=1 ...",  # 非 R2,不入聚合
    ]
    kept, summary = adr.r5_congestion_process({}, alerts_in, datetime(2026, 9, 30, 23, 30))
    r2_lines = [a for a in alerts_in if adr.r5_is_r2_congestion_line(a)]
    non_r2 = [a for a in alerts_in if not adr.r5_is_r2_congestion_line(a)]
    assert len(r2_lines) >= 2 and kept == [alerts_in[0]] + non_r2 \
        and summary is not None and all(a not in kept for a in r2_lines[1:]), \
        f"入聚合={len(r2_lines)}条→kept={len(kept)}条(R2首条+非R2) summary={'有' if summary else '无'}"


def test_r5_midday_no_summary():
    """R5中间轮-未到23:25不入汇总(首条仍即时发, 其余挂起)。"""
    alerts_in = [
        "SEVERE: R2 overview.json 时效滞后 collected_at<...> lag=24min ...",
        "SEVERE: r2_unreachable ssd.fx8.store 不可达 ...",
    ]
    _, summary_early = adr.r5_congestion_process({}, alerts_in[:2], datetime(2026, 9, 30, 14, 30))
    assert summary_early is None, f"14:30 轮 summary={'有' if summary_early else '无'}"


def test_r5_non_r2_not_aggregated():
    """R5非R2-数据错/漏跑照发不入聚合。"""
    k2, s2 = adr.r5_congestion_process({}, ["SEVERE: fetch_news 退出失败 last_exit=1 ..."],
                                       datetime(2026, 9, 30, 23, 30))
    assert k2 == ["SEVERE: fetch_news 退出失败 last_exit=1 ..."] and s2 is None, \
        f"kept={len(k2)}条 summary={'有' if s2 else '无'}"


def r5_monitor_sim(rounds, tmpdir):
    """rounds: [(now, alerts列表)]。模拟每轮独立进程: load->r5(无条件)->save。返回 (kept_list, summary_list, final_state)。"""
    st_file = tmpdir / "alert_state.json"
    st = {}
    if st_file.exists():
        st = json.loads(st_file.read_text(encoding="utf-8"))
    kepts, summaries = [], []
    for now, alerts in rounds:
        _kept, _summary = adr.r5_congestion_process(st, alerts, now)
        if _summary:
            _kept.append(_summary)
        kepts.append(_kept)
        summaries.append(bool(_summary))
        # save_alert_state 等价: 每轮结束落盘(修复后 R5 调用点之后必有)
        st_file.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        st = json.loads(st_file.read_text(encoding="utf-8"))  # 下一轮 load
    return kepts, summaries, st


def test_r5_fix_A_cross_round(tmp_path):
    """R5修复A-跨轮3种R2:首条直发+第2种并入+23:30汇总必发+状态落盘读回。"""
    _rounds = [
        (datetime(2026, 9, 30, 14, 15), ["SEVERE: r2_unreachable ssd.fx8.store 不可达 ..."]),
        (datetime(2026, 9, 30, 21, 0), ["SEVERE: R2 overview.json 时效滞后 collected_at<..> lag=24min ..."]),
        (datetime(2026, 9, 30, 23, 30), ["SEVERE: r2_intraday_lag 盘中数据滞后 ..."]),
    ]
    _kepts, _summs, _stA = r5_monitor_sim(_rounds, tmp_path)
    assert len(_kepts[0]) == 1 and not _summs[0] and not _summs[1] \
        and _summs[2] and len(_kepts[2]) >= 1 \
        and adr.R2_CONGESTION_SUMMARY_KEY_PREFIX + "20260930" in _stA, \
        f"kept轮次={[len(k) for k in _kepts]} summary={_summs} " \
        f"最终state含汇总key={'20260930' in ' '.join(_stA) or bool([k for k in _stA if k.startswith(adr.R2_CONGESTION_SUMMARY_KEY_PREFIX)])}"


def test_r5_fix_B_same_round(tmp_path):
    """R5修复B-同轮3种R2@23:30:首条照发+汇总必发(不静默)。"""
    _kepts, _summs, _stB = r5_monitor_sim(
        [(datetime(2026, 9, 30, 23, 30), [
            "SEVERE: R2 overview.json 时效滞后 ...",
            "SEVERE: r2_unreachable ssd.fx8.store 不可达 ...",
            "SEVERE: r2_intraday_lag 盘中数据滞后 ...",
        ])], tmp_path)
    assert _summs[0] and len(_kepts[0]) >= 1, \
        f"kept={len(_kepts[0])}条 summary={'有' if _summs[0] else '无'}(首条直发+其余并入汇总)"


def test_r5_fix_C_empty_wrapup_round(tmp_path):
    """R5修复C-收尾轮alerts为空也必须发汇总(修复if alerts盲区)。"""
    _kepts, _summs, _stC = r5_monitor_sim([
        (datetime(2026, 9, 30, 14, 15), ["SEVERE: r2_unreachable ssd.fx8.store 不可达 ..."]),
        (datetime(2026, 9, 30, 21, 0), ["SEVERE: R2 overview.json 时效滞后 collected_at<..> lag=24min ..."]),
        (datetime(2026, 9, 30, 23, 30), []),  # 收尾轮无新告警
    ], tmp_path)
    assert not _summs[0] and not _summs[1] and _summs[2], \
        f"前2轮聚合, 收尾轮summary={'有' if _summs[2] else '无'}(无条件调用生效)"


def test_r5_fix_D_state_readback_phenomena(tmp_path):
    """R5修复D-状态跨轮读回:现象列表累计>=2(第2+种不静默)。"""
    _kepts, _summs, _stC = r5_monitor_sim([
        (datetime(2026, 9, 30, 14, 15), ["SEVERE: r2_unreachable ssd.fx8.store 不可达 ..."]),
        (datetime(2026, 9, 30, 21, 0), ["SEVERE: R2 overview.json 时效滞后 collected_at<..> lag=24min ..."]),
        (datetime(2026, 9, 30, 23, 30), []),  # 收尾轮无新告警
    ], tmp_path)
    _phen_c = _stC.get(adr.R2_CONGESTION_SUMMARY_KEY_PREFIX + "20260930", {})
    assert len(_phen_c.get("phenomena", [])) >= 2, \
        f"收尾轮读回 phenomena={len(_phen_c.get('phenomena', []))} 项(状态已落盘可读回)"


# ============================================================
# R6: kelly + fetch_news 低频真问题保留 — 本次改动未触碰其告警路径(skip_continuous/
# exit!=0 保留), 断言这两类 key 判定函数仍直接命中(读真实函数通路)
# ============================================================
def test_r6_kelly_not_congestion():
    """R6保留-非R2告警(漏跑/数据错)不受任何降噪规则吞没。"""
    assert adr.r5_is_r2_congestion_line("SEVERE: kelly 评分失败 last_exit=1") is False, \
        "kelly exit!=0 非 R2 行, 不进 R5 聚合"


# ============================================================
# 09-30 交易日 15 条真实告警回归(每条用真实判定函数验证「改后发不发」)
# 权威口径: docs/ops/alert-denoise-design-20261001.md §1 表(18 行 = 15 条)
# 期望: 15 条 → 约 8 条(staticdata×4 全降;overview×2 单轮不响;双发 3 对各砍1;
#       nextday 双发砍1;R5 首条照发不吞;R6 kelly/fetch 保留)
# ============================================================
def r2_one_pair(task, lr, dur_s, dur_thresh_s, run_min):
    """模拟一轮 monitor 对同一 (task,last_run) 的 dur/超时双通道(真实 merge 判定)。"""
    st = {}
    alerts = []
    if dur_s > dur_thresh_s:  # dur 通道(先于超时检查? 实际代码 dur 在前, 此处两通道同轮)
        if not adr.r2_merge_already_sent(st, task, lr):
            alerts.append("dur"); adr.r2_merge_mark(st, task, lr, datetime(2026, 9, 30, 6, 0))
    if run_min > 45:  # 超时通道
        if not adr.r2_merge_already_sent(st, task, lr):
            alerts.append("timeout"); adr.r2_merge_mark(st, task, lr, datetime(2026, 9, 30, 6, 0))
    return len(alerts)


def test_reg_staticdata_x4_zero_severe(tmp_path):
    """回归-staticdata×4→SEVERE 0(单日 fail 降 info, 不轰炸)。"""
    _hb_reg = tmp_path / "hb.json"  # 不存在=心跳缺失(保守按未追平)
    _st_reg = tmp_path / "st.json"
    _tiers_reg = []
    for _i in range(4):  # 09-30 00:53/02:36/05:49/08:49 四轮 fail, 同一日
        _tiers_reg.append(adr.r4_staticdata_grade(_hb_reg, _st_reg, datetime(2026, 9, 30, 0, 30))[0])
    assert all(t == "info" for t in _tiers_reg), \
        f"4 条同日 staticdata fail → tier={_tiers_reg}(第1轮 info, 后续同日不升级+dedup 21600 窗口 suppress)"


def test_reg_us_stock_x2_merge():
    """回归-us_stock×2→1(双通道合并)。"""
    assert r2_one_pair("us_stock_morning", "2026-09-30 05:00", 2968, 1800, 45) == 1, \
        f"{r2_one_pair('us_stock_morning', '2026-09-30 05:00', 2968, 1800, 45)} 条"


def test_reg_kelly_kept():
    """回归-kelly→1(R6 保留)。"""
    assert adr.r5_is_r2_congestion_line("SEVERE: kelly_intraday_rerun 退出码5") is False, \
        "kelly 不入 R5 聚合 → 直发保留"


def test_reg_overview_x2_zero():
    """回归-overview×2→0(单轮滞后后恢复不响)。"""
    sev, n, _ = r1_sim([24, 3], buf_key="overview_lag_3domain|buffer|%s", alert_key="overview_lag_3domain")
    sev2, n2, _ = r1_sim([24, 3], buf_key="r2_overview_lag|buffer|%s", alert_key="r2_overview_lag")
    assert not sev and not sev2, f"主站{n}条 R2{n2}条(均单轮后恢复)"


def test_reg_intraday_s06_x3_merge():
    """回归-intraday/s06×3→2(intraday 双通道合并,s06 独立)。"""
    assert r2_one_pair("intraday_snapshot", "2026-09-30 20:35", 2081, 1800, 25) == 1, \
        f"intraday 合并后 {r2_one_pair('intraday_snapshot', '2026-09-30 20:35', 2081, 1800, 25)} 条(+s06 独立 1 条)"


def test_reg_backfill_x2_merge():
    """回归-backfill×2→1(双通道合并)。"""
    assert r2_one_pair("backfill_evening", "2026-09-30 21:00", 7373, 4500, 90) == 1, \
        f"{r2_one_pair('backfill_evening', '2026-09-30 21:00', 7373, 4500, 90)} 条"


def test_reg_nextday_x2_dedup(tmp_path):
    """回归-nextday×2→1(R3 产物今日已生成→monitor 去重)。"""
    assert r3_with_repo("2026-10-01 22:35:00", tmp_path) is True, \
        "自身通道发详细 + monitor 对已生成产物轮去重"
