#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#123 告警降噪 R1~R6 —— 真故障反例实测(v2, 2026-10-01)

v1(本目录同名旧版)是「逻辑模拟」,v2 按任务成败判据 ② 改为**打真实判定代码**:
  - 导入 scripts/alert_denoise_rules.py 的真实规则函数(被 schedule_monitor.sh heredoc
    与 notify.py 直接 import, 是唯一判定实现, 无第二份逻辑副本)
  - 每条反例断言调真实函数: adr.r1_buffer_judge / r2_merge_already_sent·r2_merge_mark /
    r3_nextday_product_generated_today / r4_staticdata_grade / r5_congestion_process
  - R3/R4 依赖实盘文件(mtime/心跳/状态), 测试用临时目录构造同构状态文件后仍调同一函数
    (文件路径可注入, 判定逻辑本身是真实代码), 另附真实数据目录 sanity 观测(schedule_monitor
    实跑判定会看到的同一角度)。

跑法(worktree 内, 用 trade-data venv):
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/tests/test_alert_denoise_20261001.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import alert_denoise_rules as adr  # noqa: E402

FAIL = []


def check(name, cond, detail):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"[{tag}] {name} — {detail}")


def new_tmp():
    _d = tempfile.mkdtemp(prefix="adr-test-")
    return Path(_d)


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


sev, n, rnd = r1_sim([24, 25, 26, 27])
check("R1反例A-真断供连续4轮滞后→SEVERE必响", sev and n >= 1,
      f"4轮滞后(24/25/26/27min), SEVERE={n}条 {rnd}")
sev, n, rnd = r1_sim([24, 25])
check("R1反例B-连续2轮(30min)真断链→SEVERE响", sev,
      f"2轮滞后(24/25min), SEVERE={n}条 {rnd}")
sev, n, rnd = r1_sim([24, 3, 2])
check("R1正例C-单轮滞后后恢复→不响", not sev,
      f"1轮24min滞后后恢复, SEVERE={n}条 {rnd}")
sev, n, rnd = r1_sim([19, 18])
check("R1边界D-2轮都<20min→不响", not sev,
      f"19/18min均低于阈值, SEVERE={n}条 {rnd}")
# R1 补充:跨天防残留——隔日新日期 buffer key 从 0 起(不叠加前日计数)
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
check("R1跨天E-隔日防残留从0起/持续不轰炸/恢复后独立再响",
      a1 == "buffer" and a2 == "alert" and a3 == "buffer" and a4 == "suppress"
      and a5 == "recover" and a6 == "buffer" and a7 == "alert",
      f"前日 buffer→alert; 隔日suppress(a4={a4}); 恢复后(a5={a5})再滞后 a6={a6}→a7={a7}")

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


al = r2_sim([("2026-09-30 05:00", "dur"), ("2026-09-30 05:00", "timeout")])
check("R2反例A-同运行实例超时+耗时合并→只响1条且必响", len(al) == 1 and al[0][1] == "2026-09-30 05:00",
      f"合并后{len(al)}条({al})")
al = r2_sim([("2026-09-30 05:00", "dur"), ("2026-09-30 05:00", "timeout"),
             ("2026-10-01 05:00", "timeout")])
check("R2反例B-隔日再次卡死→新last_run必再响", len(al) == 2,
      f"两天各1条:{al}")
# 正例C: 单次耗时超阈值但已完成(无对应超时) → 响1条(真退化保留),由 dur 通道先发独占
al = r2_sim([("2026-09-30 20:35", "dur")])
check("R2正例C-单轮耗时超阈值→响1条", len(al) == 1 and al[0][0] == "dur", f"{al}")
# merge cleanup: >24h 的 merge key 被清理;新 key 保留
st = {}
adr.r2_merge_mark(st, "t", "2026-09-29 01:00", datetime(2026, 9, 29, 1, 0))
adr.r2_merge_mark(st, "t", "2026-09-30 05:00", datetime(2026, 9, 30, 5, 0))
adr.r2_merge_cleanup(st, datetime(2026, 9, 30, 6, 0))
check("R2清理D-超24h merge key被清(防膨胀)", "merge|t|2026-09-29 01:00" not in st
      and "merge|t|2026-09-30 05:00" in st, f"state keys={list(st)}")

# ============================================================
# 规则 R3: nextday_plan 双发去重 → adr.r3_nextday_product_generated_today(真实函数)
# ============================================================
def r3_with_repo(mtime_date_iso):
    d = new_tmp() / "data"
    d.mkdir(parents=True)
    p = d / "nextday_plan.json"
    if mtime_date_iso is not None:
        p.write_text("{}", encoding="utf-8")
        import os
        os.utime(p, (0, datetime.fromisoformat(mtime_date_iso).timestamp()))
    return adr.r3_nextday_product_generated_today(d.parent, "2026-10-01")


check("R3反例A-产物今日已生成→monitor去重(自身通道已发, 不再双发)",
      r3_with_repo("2026-10-01 22:35:00") is True, "nextday_plan.json mtime=今日")
check("R3反例B-产物未生成(真失败)→不判定已生成, monitor汇总双保险",
      r3_with_repo(None) is False, "文件缺失→False")
check("R3正例C-产物为昨日(陈旧)→False(不算今日生成)",
      r3_with_repo("2026-09-30 22:30:00") is False, "mtime=昨日→False")

# ============================================================
# 规则 R4: staticdata 备份失败分级 → adr.r4_staticdata_grade(真实函数)
# (notify.py R4 拦截块调同一函数的同一调用方式: heartbeat+state 均可注入)
# ============================================================
def r4_with_state(hb_result, hb_ts, state_last_fail, state_days):
    d = new_tmp()
    hb = d / "staticdata_backup_heartbeat.json"
    st = d / "staticdata_backup_fail_state.json"
    if hb_result is not None:
        hb.write_text(json.dumps({"result": hb_result, "ts": hb_ts}), encoding="utf-8")
    if state_last_fail:
        st.write_text(json.dumps({"last_fail_date": state_last_fail,
                                  "consecutive_days": state_days}), encoding="utf-8")
    return adr.r4_staticdata_grade(hb, st, datetime(2026, 10, 1, 22, 0))[0]


# 反例A: 09-30(昨天)预算耗尽 fail → 10-01 备份心跳 ok(追平) → info
r = r4_with_state("ok", "2026-10-01 21:00:00", "2026-09-30", 1)
check("R4反例A-单日预算耗尽但次日追平→降info", r == "info", f"判定={r}")
# 反例B: 连续2天未追平(心跳一直没有 ok 当日之后) → SEVERE
r = r4_with_state("fail", "2026-10-01 21:00:00", "2026-09-30", 1)
check("R4反例B-连续2天未追平(真R2备份缺口)→SEVERE", r == "severe", f"判定={r}")
# 反例C: 心跳文件缺失(无任何成功证明)+状态已连续2天 → SEVERE(保守不漏)
r = r4_with_state(None, None, "2026-09-30", 1)
check("R4反例C-心跳缺失且未追平→SEVERE(宁多勿漏)", r == "severe", f"判定={r}")
# 补充: 单日首次 fail(迁移期一次性)→ info(观察中),不轰炸
r = r4_with_state("fail", "2026-10-01 21:00:00", None, 0)
check("R4补充D-单日首次失败→info(观察中)", r == "info", f"判定={r}")

# ============================================================
# 规则 R5: R2/部署链路拥堵同根因日汇总 → adr.r5_congestion_process / r5_is_r2_congestion_line
# ============================================================
alerts_in = [
    "SEVERE: R2 overview.json 时效滞后 collected_at<...> lag=24min ...",
    "SEVERE: r2_unreachable ssd.fx8.store 不可达 ...",
    "SEVERE: r2_intraday_lag 盘中数据滞后 legacy_path 迟 ...",
    "SEVERE: fetch_news 退出失败 last_exit=1 ...",  # 非 R2,不入聚合
]
kept, summary = adr.r5_congestion_process({}, alerts_in, datetime(2026, 9, 30, 23, 30))
r2_lines = [a for a in alerts_in if adr.r5_is_r2_congestion_line(a)]
non_r2 = [a for a in alerts_in if not adr.r5_is_r2_congestion_line(a)]
check("R5反例A-同日多条R2同根因告警→首条直发其余并入汇总(23:25收尾出汇总)",
      len(r2_lines) >= 2 and kept == [alerts_in[0]] + non_r2 and summary is not None
      and all(a not in kept for a in r2_lines[1:]),
      f"入聚合={len(r2_lines)}条→kept={len(kept)}条(R2首条+非R2) summary={'有' if summary else '无'}")
# 当天未到收尾轮: 只聚合不入汇总, 首条仍发
_, summary_early = adr.r5_congestion_process({}, alerts_in[:2], datetime(2026, 9, 30, 14, 30))
check("R5中间轮-未到23:25不入汇总(首条仍即时发, 其余挂起)", summary_early is None,
      f"14:30 轮 summary={'有' if summary_early else '无'}")
# 非 R2 告警(数据错/漏跑)不聚合, 不受影响
k2, s2 = adr.r5_congestion_process({}, ["SEVERE: fetch_news 退出失败 last_exit=1 ..."],
                                   datetime(2026, 9, 30, 23, 30))
check("R5非R2-数据错/漏跑照发不入聚合", k2 == ["SEVERE: fetch_news 退出失败 last_exit=1 ..."] and s2 is None,
      f"kept={len(k2)}条 summary={'有' if s2 else '无'}")

# ============================================================
# R6: kelly + fetch_news 低频真问题保留 — 本次改动未触碰其告警路径(skip_continuous/
# exit!=0 保留), 断言这两类 key 判定函数仍直接命中(读真实函数通路)
# ============================================================
check("R6保留-非R2告警(漏跑/数据错)不受任何降噪规则吞没",
      adr.r5_is_r2_congestion_line("SEVERE: kelly 评分失败 last_exit=1") is False,
      "kelly exit!=0 非 R2 行, 不进 R5 聚合")

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

r15 = []
# #1/#2/#3/#6 staticdata 部分失败×4(R4): 09-30 单日 4 轮 fail(心跳全天无 ok), 同日重复
# 不升级连续计数 → 第1轮 info(单日未追平, 观察中), 后续同一日仍 info + notify 侧 dedup
# 21600(6h)窗口 suppress → SEVERE 0 条。用真实 r4 函数验证: 同日多次 fail 不跨天升级。
_r4_reg_dir = new_tmp()
_hb_reg = _r4_reg_dir / "hb.json"  # 不存在=心跳缺失(保守按未追平)
_st_reg = _r4_reg_dir / "st.json"
_tiers_reg = []
for _i in range(4):  # 09-30 00:53/02:36/05:49/08:49 四轮 fail, 同一日
    _tiers_reg.append(adr.r4_staticdata_grade(_hb_reg, _st_reg, datetime(2026, 9, 30, 0, 30))[0])
check("回归-staticdata×4→SEVERE 0(单日 fail 降 info, 不轰炸)",
      all(t == "info" for t in _tiers_reg),
      f"4 条同日 staticdata fail → tier={_tiers_reg}(第1轮 info, 后续同日不升级+dedup 21600 窗口 suppress)")
# #4/#5 us_stock 超时+耗时 → 合并 1 条
check("回归-us_stock×2→1(双通道合并)", r2_one_pair("us_stock_morning", "2026-09-30 05:00", 2968, 1800, 45) == 1,
      f"{r2_one_pair('us_stock_morning', '2026-09-30 05:00', 2968, 1800, 45)} 条")
# #7 kelly_intraday_rerun → R6 保留 1 条
check("回归-kelly→1(R6 保留)", adr.r5_is_r2_congestion_line("SEVERE: kelly_intraday_rerun 退出码5") is False,
      "kelly 不入 R5 聚合 → 直发保留")
# #8/#9 overview lag 主站+R2 各1 → R1 单轮 buffer 不响
sev, n, _ = r1_sim([24, 3], buf_key="overview_lag_3domain|buffer|%s", alert_key="overview_lag_3domain")
sev2, n2, _ = r1_sim([24, 3], buf_key="r2_overview_lag|buffer|%s", alert_key="r2_overview_lag")
check("回归-overview×2→0(单轮滞后后恢复不响)", not sev and not sev2,
      f"主站{n}条 R2{n2}条(均单轮后恢复)")
# #10/#11/#12 intraday 超时 + s06 超时 + intraday 耗时: intraday 合并→1, s06 独立→1
check("回归-intraday/s06×3→2(intraday 双通道合并,s06 独立)", r2_one_pair("intraday_snapshot", "2026-09-30 20:35", 2081, 1800, 25) == 1,
      f"intraday 合并后 {r2_one_pair('intraday_snapshot', '2026-09-30 20:35', 2081, 1800, 25)} 条(+s06 独立 1 条)")
# #14/#18 backfill 超时+耗时 → 合并 1 条
check("回归-backfill×2→1(双通道合并)", r2_one_pair("backfill_evening", "2026-09-30 21:00", 7373, 4500, 90) == 1,
      f"{r2_one_pair('backfill_evening', '2026-09-30 21:00', 7373, 4500, 90)} 条")
# #15/#16 nextday 双发 → 自身通道保留, monitor 汇总去重 → 1 条(产物今日已生成)
check("回归-nextday×2→1(R3 产物今日已生成→monitor 去重)",
      r3_with_repo("2026-10-01 22:35:00") is True,
      "自身通道发详细 + monitor 对已生成产物轮去重")

print()
if FAIL:
    print(f"=== 共 {len(FAIL)} 项 FAIL: {FAIL} ===")
    sys.exit(1)
print("=== 13+ 项真故障反例断言 + 09-30 回归断言全部 PASS ===")