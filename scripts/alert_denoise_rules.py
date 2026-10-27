#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
#123 告警降噪 R1~R5 判定规则纯函数(2026-10-01)

schedule_monitor.sh(Python heredoc) / notify.py 共用本模块的判定逻辑(消除双实现),
测试脚本 scripts/tests/test_alert_denoise_20261001.py import 本模块打「真实判定函数」
反例断言(任务要求: 规则必须落进真实代码, 断言不许只跑逻辑模拟)。

各函数对应 schedule_monitor.sh / notify.py 的代码锚点(行号见函数 docstring,
实际调用点行号在 schedule_monitor.sh / notify.py 中 grep 本函数名可查)。

规则目录:
  R1 overview_lag_3domain / r2_overview_lag 单次直发 → 连续 ≥2 轮(30min)仍滞后才 SEVERE
     (复用 r2_intraday_lag 已有 buffer 计数模式; 调用点 schedule_monitor.sh L1402 / L1578 / L1611)
  R2 「超时未完成」与「执行耗时」双通道同 (task,last_run) 合并去重
     (调用点 schedule_monitor.sh 耗时通道 L723/L738、超时通道 L926/L942、cleanup L1171)
  R3 nextday_plan 自身通道(内容详细)已发时, schedule_monitor exit!=0 汇总通道对已落盘产物轮去重
     (调用点 schedule_monitor.sh L495)
  R4 staticdata_backup_fail 分级: 连续 >=2 天未追平才 SEVERE, 单日追平/未追平降 info
     (因 staticdata_backup_async.sh 被并发改动占用, 分级落在 notify.py 调用侧 L2110)
  R5 R2/部署链路拥堵同根因日汇总: 当日 >=2 种 R2 相关告警 → 首条直发, 第 2 条起聚合,
     23:25 收尾轮发 1 条汇总(现象清单 + #149 根因指针; 调用点 schedule_monitor.sh L2151)
  R7 r2_consistency(§22 三站一致性巡检)两件事(2026-10-05 #160 收口):
     ①连续失败天数分级: 首日 severe(= 现状不变), 连续第 2 日及以后升 critical(独立 dedup
       key 不占首日 6h 窗, 确保必达; 邮件 + 飞书 alert 群)。判定 r7_r2_consistency_escalate
       (调用点 notify.py dedup_key=r2_consistency_fail 拦截, 同 R4 落调用侧先例)
     ②同实例去重: 包装器自身通道(notify --dedup-key r2_consistency_fail)已为本次运行实例
       发过告警时, schedule_monitor exit!=0 汇总通道不复述(判定 r7_r2_consistency_wrapper_alerted,
       调用点 schedule_monitor.sh exit!=0 分支; 同 R3 nextday_plan 先例)

原则(§23.2 修 bug 三铁律 + §18 降噪翻车教训): 每条规则必须保留「真故障判别维度」
(连续轮、跨天追平、产物未生成、首条仍即时), 绝不因降噪静默真故障。
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---- 常量(单一事实源, schedule_monitor.sh 引用本模块而非各自定义) ----
OVERVIEW_LAG_CONTINUOUS_THRESHOLD = 2   # R1: overview lag 连续 >=2 轮(15min/轮=30min)仍滞后才 SEVERE
MERGE_PREFIX = "merge|"                  # R2: 超时/耗时双通道同 (task,last_run) 共享去重 key 前缀
R2_CONGESTION_SUMMARY_KEY_PREFIX = "r2_pipeline_congestion|"  # R5: 日级汇总 key 前缀
R4_OK_RESULTS = ("ok", "skip_oversize")  # R4: 备份心跳里视为「备份完成/追平」的 result
R4_HEARTBEAT_OK_SPAN = timedelta(hours=36)  # R4: 兜底——心跳 ok 距今超 36h 视为已过旧(不误判追平)
R2_CONSISTENCY_DEDUP_KEY = "r2_consistency_fail"           # R7: 包装器自身告警通道去重 key(check_r2_consistency.sh)
R2_CONSISTENCY_ESCALATED_DEDUP_KEY = "r2_consistency_fail_escalated"  # R7: 连续失败升级档独立 key(不复用首日 6h 窗)
R2_CONSISTENCY_ESCALATE_DAYS = 2                            # R7: 连续失败天数达此值 → severe 升 critical

# #196(F1 族「巡检/链路自身死亡」可见性统一, 2026-10-05): failed-unit 巡检 + 巡检者自身存活 +
# 「连续 N 天仍异常 → 升 critical」档。与 R7 同口径(首日 severe 不降噪 / 连续第 N 日起 critical
# 换独立 dedup key 必达 / 连续天数持久化), 共用下面的 consecutive_days_escalate 单一实现。
# ⚠️ memory alert-denoise-keep-fault-discriminator: 升级的必须是**真故障判别维度**
# (「有 unit 处于 failed」「巡检 timer 不在跑」= 真故障), 不是把噪音一起升。
FAILED_UNITS_DEDUP_KEY = "failed_units_patrol"                        # #196① 云上 failed-unit 巡检首报通道
FAILED_UNITS_ESCALATED_DEDUP_KEY = "failed_units_patrol_escalated"   # 连续 N 天异常升级档独立 key(不占首日窗)
FAILED_UNITS_ESCALATE_DAYS = 3                                       # #196③ 用户拍板: 连续 3 天仍异常 → critical
PATROL_DRIFT_DEDUP_KEY = "cloud_unit_patrol_drift"                   # #191 cloud_unit_patrol.sh 漂移首报 key(与脚本字面量一致)
PATROL_DRIFT_ESCALATED_DEDUP_KEY = "cloud_unit_patrol_drift_escalated"  # 连续 N 天漂移升级档独立 key
PATROL_DRIFT_ESCALATE_DAYS = 3                                       # #196③: patrol 连续 3 天仍漂移 → critical

# ── #264 件A(2026-10-15 用户拍板降噪包1): 升级档独立抑制窗 ─────────────────────
# 病灶(实测): 升级档原先复用调用方的**首报窗** args.dedup_window。failed_units 链路为「集合有变
# 立即报」把首报窗设成 0, 而 notify.py 的 check_dedup(key, 0) 恒放行 ⇒ **升级 critical 永不被抑制**,
# 同一「持续未清」主题集合每变化一次/每天零点就真发一封(实测 10-11~10-15 共 19 封, 10-15 单日 6 封)。
# 修复: 升级档改判自己的独立窗(本常量), 与首报窗彻底解耦 —— 首报「新增立即报」不受影响(仍 window=0)。
# 口径: 同档 ≤1 封 / ESCALATED_DEDUP_WINDOW_SECONDS。可配置, 改此常量即可(单位秒)。
# 取值依据(RCA §4.1.A 建议 24h, 本处据实测重放上调, 2026-10-16 实测):
#   用 10-11~10-16 云上 alert_ledger.jsonl 的 20 封升级行重放(逐条按窗口判定):
#     窗 24h → 10-12~10-15 发 4 封(> 验收口径 ≤2; 因「每天零点巡检」恒跨过 24h 边界 ⇒ 日课不灭)
#     窗 48h → 该段 2 封 ✓, 但 6 天段 3 封(> RCA 预期 ≤2)
#     窗 72h → 该段 2 封 ✓, 6 天段 2 封 ✓, 10-15 单日 0 封(≤ RCA「同档 ≤1 封」) —— 三项量化预期全达
#   ⇒ 取 72h(259200):满足 RCA 全部量化预期的最小窗口, 且消灭「凌晨零点日课」。
#   ⚠️ 残余(见实施报告 §残余): 纯窗口制下, 已处 critical 的链路若「当日新增失败单元」,
#      该首报仍受本窗约束(最长延后一个窗); 首报通道(未升 critical 时, window=0)与
#      「升 critical 首报」(窗空必发)不受影响。
ESCALATED_DEDUP_WINDOW_SECONDS = 259200

# ── #264 收口(2026-10-16, 审查边界差集①): patrol_drift 升级档窗归位 ──────────────
# 件A 把**两个** #196 通道的升级档窗统一成 ESCALATED_DEDUP_WINDOW_SECONDS(72h), 顺带把
# patrol_drift 从原 6h(21600)放大到 72h。但 patrol_drift **不在 RCA 病灶范围**(噪声清单只有
# failed unit), 且现网零升级流量 ⇒ 属「同病一并修」之外的范围外行为变更。收口: patrol_drift
# 升级档保持其原 6h 窗(与 scripts/cloud_unit_patrol.sh:153 `--dedup-window 21600` 同源, 该值
# 即 #264 前该通道升级档的实际生效窗), 不受 72h 逻辑影响; failed-unit 升级链仍 72h(不变)。
# 选「独立常量」而非「该通道保留 args.dedup_window」: 与件A「升级档窗 = 该通道自己的窗, 不依赖
# 调用方参数」口径一致(件A 正是为消除这种隐式耦合), 且常量名显式可 grep, 避免行为藏在分支里。
PATROL_DRIFT_ESCALATED_DEDUP_WINDOW_SECONDS = 21600

# ── #264 件B(2026-10-15): 「连续天数」→「近 N 天出现天数」(判据事件化, 有界不单调) ──────
# 病灶: 判据原先挂在 systemd 的**持久 failed 状态**上(只有人工 reset-failed/重跑成功才消),
# 条件挂着不消时「连续天数」单调递增无上界(实测 consecutive_days=8 仍在涨), 既不真实也无收益。
# 修复: #196 两个通道改用**有界滚动窗口**——状态记 seen_dates(窗口内观测到的自然日),
# 计数 = 窗口内出现天数(≤ 本值), 语义从「连续了几天」变为「近 N 天里出现了几天」;
# R7 不传本参数(rolling_window_days=None) → 保持旧「连续天数」语义逐位不变。
ESCALATE_ROLLING_WINDOW_DAYS = 7

# 巡检者自身存活检查的 unit 清单(只告警不改生产; 状态判定一律 systemctl show -p ActiveState, 禁 is-active)
# 收录边界(§23.3 穷举后定的原则, 非随手清单): **只收「无数据产物可反证其存活」的守护/巡检/监控类
# 调度器** —— 采集/生成/回填类 timer 停跑的后果会体现在数据上(数据陈旧 → check_data_integrity/
# check_data_gap 数据级告警兜底), 且多数已登记进 schedule_monitor 漏跑表; 而监控器/巡检器**不产出
# 数据**, 它死了没有任何数据会变旧 ⇒ 必须靠本清单直接看 timer 活性。同理不收「有自身 loud 失败通道」
# 的推送器(如 trade-brief-push, 失败时 wrapper 自己 notify --severe)。
# 清单与云上实测(2026-10-16 只读 `systemctl show`): 42 个 trade-*.timer 全为 active+enabled。
WATCHMAN_UNITS = (
    ("trade-cloud-unit-patrol.timer", "timer"),        # #191 云上 unit 漂移巡检调度器
    ("trade-check-monitor-heartbeat.timer", "timer"),  # schedule-monitor 心跳消费者(元监控)
    ("trade-schedule-monitor.timer", "timer"),         # 主监控调度器
    ("trade-self-heal.timer", "timer"),                # 自愈调度器
    ("trade-r2-consistency.timer", "timer"),           # §22 三站一致性巡检调度器
    ("trade-check-data-gap.timer", "timer"),           # 数据缺口/停更告警检测器(巡检类, 不产出数据)
    ("trade-overfit-monitor.timer", "timer"),          # 过拟合监控器(监控类, 不产出数据)
    # #264 包3 件F(2026-10-16): 告警周度 review 调度器(巡检类, 不产出数据; 停了没有任何
    # 数据会变旧 ⇒ 纳入本清单直接看 timer 活性 = L45 第 4 件「过期告警」落点)。
    ("trade-alert-weekly-review.timer", "timer"),
    # #258 云上批(2026-10-22): 孤儿冻结清理调度器(每日 21:50, dry-run)。同属巡检/清理类,
    # 不产出数据 —— 停跑后孤儿只在冻结表缓慢累积, 没有任何数据会变旧 ⇒ 纳入本清单看 timer 活性。
    ("trade-freeze-orphan-cleanup.timer", "timer"),
)


# ---- #240 ②(2026-10-09) failed-unit 巡检「同一集合每天只报 1 次 / 集合有变立即报」----
# 病灶(见 docs/ops/alert-triage-1008-20261008.md R3): 同一批 failed unit 在 09:45 / 16:00 /
# 22:15 被**逐轮(6h 窗)重报同一内容**; 而 notify 的 dedup 窗仅 6h → 一天 3 封同文邮件。
# 降噪口径(保留真故障判别维度, memory alert-denoise-keep-fault-discriminator):
#   - 集合**未变**且当日已报 → 只报 1 次(本函数判 "same-set-same-day" → 调用方跳过发送)
#   - 集合**有变**(新增 failed unit / 消失) → **立即报**(reason="changed")
#   - 次日首报(集合同但跨自然日) → 照报(reason="daily-first")
#   ⇒ 静默的只有「同一事实的当日重复」, 真故障(新 unit 挂 / 持续未清)一封不少
#     (持续未清另有 #196③ 连续 3 天升 critical 兜底)。
#
# ---- #240 ② 精修(2026-10-09, 方向感知; 见 docs/ops/alert-system-fullchain-audit-20261009.md §6-L3a)----
# 病灶2(审计 §2-D3 / §3-F3): 原判定**对称**, 不区分方向 —— 集合**新增** failed unit(真信号)
#   与集合**缩小**(unit 被清零/恢复)一视同仁「立即报」⇒ 12:52 部署后 7 连发中 4 条
#   (17:00/18:15/18:30/20:15)是纯「恢复进展」方向的假信号(今日 unit 巡检 9/20 条, 占 45%)。
# 精修口径(把 changed 拆方向; 判别维度一条不少):
#   - added         : 新集合 − 旧集合 非空(新增 failed unit / 新存活异常) → **立即报**
#   - added-jitter  : 新增, 但「结果集合」24h 内已 added 过 → 静默(防 unit 反复 fail→clear→fail 抖动)
#   - shrunk        : 只有移除(集合缩小 = 恢复进展) → 静默(并入观测, 不单独发)
#   - daily-first   : 集合与上次观测一致且跨自然日 → 照报(每日一次提醒)
#   - same-set-same-day: 集合与上次观测一致且当日已报 → 跳过
#   - changed       : 旧状态无成员快照(迁移期, 方向不可判) → 保守照报(fail-open)
#   ⇒ **真故障判别维度保留**: ①新增立即报 ②持续未清由 #196③ 连续 3 天升 critical 兜底
#     ③跨日首报照旧 ④集合清空后 unit 重现 = added(会报, 不因「曾缩到空」漏掉重现的真故障)
FAILED_UNITS_SIG_STATE_FILENAME = "failed_units_patrol_sig.json"  # 签名+最近一次已报日期状态
FAILED_UNITS_SIG_LEN = 12                                          # 签名取 md5 前 N 位(可读+足够区分)
FAILED_UNITS_ADDED_JITTER_WINDOW = timedelta(hours=24)            # #240②精修: 同集合二次 added 抖动抑制窗

# ---- #240 ③ 复审 F2(2026-10-09) dur 计数桶键标记(单一事实源) ----
# 桶键 = f"{task}|dur_buffer|{阈值}"; schedule_monitor.sh 用本常量**构造**桶键 + 在恢复循环里
# **豁免**同前缀键(桶复位只由 dur 块内联负责)。两处共用同一常量, 防字面量漂移导致豁免失配。
DUR_BUFFER_KEY_MARK = "|dur_buffer|"

# ---- #245 批2 B4-3 收口(2026-10-10) nextday_gap_check 三层统一 dedup key ----
# py(notify --dedup-key)/sh(notify --dedup-key)/monitor(wrapper_channel_alerted 读 notify_dedup.json)
# 三层共用同一键: py 已发 → sh 同键窗内 suppress + monitor 汇总去重(0 重复);py 崩/未发 → sh/monitor
# 照发(兜底不断层)。此常量本模块暴露, 供 monitor 引用; py/sh 的 CLI 字面量须与之一致(机检断言)。
NEXTDAY_GAP_DEDUP_KEY = "nextday_gap_check_fail"


def _safe_int(value, default=0):
    """容错取整(#264 收口 2026-10-16): 状态文件字段被写坏(非数值, 如人工编辑/异常写)时返回
    default, **不抛 ValueError** —— 分级判定退化为「从零重算」, 而不是让调用方整体崩掉
    (崩 = 该通道当次零告警, 比降级更糟)。缺省行为与旧「字段缺失」一致。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _looks_like_iso_date(value) -> bool:
    """形状判定: 是否形如 YYYY-MM-DD(只做形状 ASCII 检查, 不验证日历有效性)。

    用于 seen_dates 状态字段过滤(#264 收口 2026-10-16): 防损坏内容被当日期参与 `>=` 字符串
    比较 —— 垃圾串(如 'a')字符序大于 '2026-…' 会被保留 ⇒ 虚增窗口计数 ⇒ 误判 critical。
    """
    if not isinstance(value, str) or len(value) != 10 or not value.isascii():
        return False
    return (value[4] == "-" and value[7] == "-"
            and value[:4].isdigit() and value[5:7].isdigit() and value[8:].isdigit())


def failed_units_signature(problems) -> str:
    """告警项列表 → 稳定集合签名(排序后 md5 前 FAILED_UNITS_SIG_LEN 位)。

    与顺序无关(排序): 同一批 failed unit 无论 systemctl 输出顺序如何, 签名一致。
    空列表 → ""(调用方据此短路, 不判「集合变化」)。
    """
    items = [str(p) for p in (problems or []) if str(p)]
    if not items:
        return ""
    return hashlib.md5("|".join(sorted(items)).encode("utf-8")).hexdigest()[:FAILED_UNITS_SIG_LEN]


def failed_units_identity(failed_units, watchman_problems=None) -> list:
    """方向判定用的**细粒度成员集**(去重保序): failed unit 名逐个 + 巡检者存活异常描述逐条。

    ⚠️ 方向判定必须用细粒度成员, **不能**用汇总后的整串("云上 failed unit: a, b")——
       否则集合缩小(a,b → a)会表现为「整串换新」= 旧串消失 + 新串出现, 被误判为
       added(实为 shrunk)⇒ 方向判定失效、恢复进展照旧被当故障报。
    """
    out = []
    for x in list(failed_units or []) + list(watchman_problems or []):
        s = str(x)
        if s and s not in out:
            out.append(s)
    return out


def failed_units_daily_judge(state: dict, signature: str, items, today_str: str, now=None) -> tuple:
    """#240 ② 方向感知每日判定(纯函数, 不碰 I/O)。返回 (send: bool, reason: str)。

    state = 上次落盘状态:
      {"signature"/"prev_signature": 上次观测集合签名, "items": 上次观测成员列表(方向判定),
       "last_alert_date": 最近一次真发出日期, "last_added_signature"/"last_added_at": 抖动抑制}。
    signature = 本轮集合签名(变更检测键, 与调用方 failed_units_signature(problems) 同源)。
    items     = 本轮**细粒度成员**(方向判定; 见 failed_units_identity)。
    now       = 当前时间(抖动抑制窗口用; 缺省 None → 不做抖动抑制, fail-open 照报)。

    reason ∈ {"empty"(无异常, 调用方本不该调) / "added"(有新增→立即报) /
              "added-jitter"(同集合二次新增→静默) / "shrunk"(只有移除→静默) /
              "changed"(迁移期无成员快照→保守照报) /
              "daily-first"(今日首报) / "same-set-same-day"(当日同集合重复→跳过)}。
    """
    if not signature:
        return False, "empty"
    prev_sig = str(state.get("prev_signature") or state.get("signature") or "")
    last_alert_date = str(state.get("last_alert_date") or "")
    prev_items_raw = state.get("items")

    if isinstance(prev_items_raw, list):
        _items = sorted(str(p) for p in (items or []) if str(p))
        _prev = set(str(x) for x in prev_items_raw if str(x))
        _cur = set(_items)
        _added = _cur - _prev
        if _added:
            # 抖动抑制: 结果集合与 24h 内上一次 added 相同 → 静默(unit 反复 fail→clear→fail)
            _la_sig = str(state.get("last_added_signature") or "")
            _la_at = str(state.get("last_added_at") or "")
            if now is not None and _la_at and signature == _la_sig:
                try:
                    _at = datetime.strptime(_la_at, "%Y-%m-%d %H:%M:%S")
                    if timedelta(0) <= (now - _at) < FAILED_UNITS_ADDED_JITTER_WINDOW:
                        return False, "added-jitter"
                except (ValueError, TypeError):
                    pass
            return True, "added"
        if _prev - _cur:
            return False, "shrunk"
        # 无增无减(含聚合串顺序变化): 落到按日判定(下方统一)
    else:
        # 迁移期(旧状态无成员快照): 方向不可判 → 按签名判「变没变」, 变了保守照报(fail-open)
        if signature != prev_sig:
            return True, "changed"
    if last_alert_date != today_str:
        return True, "daily-first"
    return False, "same-set-same-day"


def consecutive_days_escalate(state_path, now, escalate_days, log_prefix="",
                              rolling_window_days=None):
    """通用「连续 N 自然日异常 → 升 critical」判定(单一事实源; R7 与 #196 共用)。

    「连续 N 天」定义: 相邻自然日各发生一次异常。中间夹一个正常日/未跑日(间隔 >1 自然日)
    即视为连续链中断, 从 1 重新计; 同日重复调用(手动重跑/重试)不重复计数。

    rolling_window_days(#264 件B, 2026-10-15, 默认 None=旧语义逐位不变):
      非 None 时启用**有界滚动窗口**语义 —— 「连续 N 天」改判「近 N 天出现天数」:
        * 状态记 seen_dates(窗口内观测到的自然日, 升序, 只保留窗口内);
        * 计数 = 窗口内出现过的天数(≤ rolling_window_days), 不再无界单调递增;
        * 链中断(间隔>1 天)不再"清零", 而是随窗口滑动自然衰减(旧日滑出窗口)。
      为什么改: 判据原先挂在 systemd 的**持久 failed 状态**(只有人工 reset-failed 才消),
      条件挂着不消时连续天数单调递增无上界 ⇒ 既不真实也没收益(#259 病灶)。
      迁移: 旧状态无 seen_dates 时用 last_fail_date 播种, 不丢历史连续性观察。

    返回 (tier, consecutive_days, first_fail_date), tier in ("severe", "critical"):
      - 连续/窗口出现 < escalate_days 天 → "severe"(与历史行为一致, 单次异常照发不降噪)
      - 连续/窗口出现 >= escalate_days 天 → "critical"(调用侧换独立 dedup key → 不被首日窗吞 → 必达)

    状态原子落盘 state_path(原子写): {last_fail_date, consecutive_days, first_fail_date,
    last_grade_time} (+ rolling 时的 seen_dates)。故意**不**依赖外部「成功心跳」文件: 正常日在链路
    上根本不会调用本函数, 间隔 >1 天即自然中断(省一个跨脚本耦合点)。

    残余(如实登记): 状态无法落盘时(权限/磁盘)连续天数恒为 1 → 升级档静默失效; 此时首日
    severe 通道仍照发(不吞真故障), 且 stderr 打印可查 —— 只丢「升级」不丢「告警本身」。
    """
    _today = now.strftime("%Y-%m-%d")
    _state = {}
    try:
        if state_path is not None and state_path.exists():
            _loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(_loaded, dict):
                _state = _loaded
    except Exception:
        _state = {}
    _last = str(_state.get("last_fail_date") or "")
    _days = _safe_int(_state.get("consecutive_days"))   # #264 收口: 容错, 非数值不崩
    _first = str(_state.get("first_fail_date") or "")

    if rolling_window_days is not None:
        # ── #264 件B: 有界滚动窗口「近 N 天出现天数」(判据事件化) ──
        # #264 收口(2026-10-16, 审查边界差集③): seen_dates **形状过滤** —— 非 list(字符串/数字
        # 等)一律视为缺失; list 内逐项只留 ISO 日期串。防损坏文件把垃圾当日期: 字符串比较
        # 'a' >= '2026-10-09' 成立 ⇒ 逐字符/垃圾项全被保留 ⇒ 窗口"满" ⇒ **误判 critical**。
        # 方向: 过滤后不足 escalate_days 至多退回 severe(少升一次级), 绝不虚增计数误升级。
        _raw_seen = _state.get("seen_dates")
        _seen = ([str(d) for d in _raw_seen if _looks_like_iso_date(str(d))]
                 if isinstance(_raw_seen, list) else [])
        if not _seen and _last:
            # 迁移: 旧状态无 seen_dates(只存 consecutive_days) → 用「连续天数」+ last_fail_date
            # **反推补齐**窗口内日期, 不丢历史连续性(否则迁移当天会把已升 critical 的链路误降级)。
            try:
                _n = max(1, _safe_int(_state.get("consecutive_days"), 1))
                _last_dt = datetime.strptime(_last, "%Y-%m-%d")
                _seen = [(_last_dt - timedelta(days=i)).strftime("%Y-%m-%d")
                         for i in range(_n - 1, -1, -1)]
            except (ValueError, TypeError):
                _seen = [_last]
        if _today not in _seen:
            _seen.append(_today)
        _seen = sorted(set(_seen))
        try:
            _floor = (now - timedelta(days=int(rolling_window_days) - 1)).strftime("%Y-%m-%d")
            _seen = [d for d in _seen if d >= _floor]
        except (ValueError, TypeError):
            _seen = [d for d in _seen if d == _today] or [_today]
        _days = len(_seen)                   # 有界: ≤ rolling_window_days, 不再单调无界
        _first = _seen[0] if _seen else _today
    elif _last == _today:
        # 同日重复(手动重跑/重试): 不重复计数
        _days = max(_days, 1)
        _first = _first or _today
    elif _last:
        try:
            _gap = (datetime.strptime(_today, "%Y-%m-%d")
                    - datetime.strptime(_last, "%Y-%m-%d")).days
        except (ValueError, TypeError):
            _gap = 0
        if _gap == 1:
            _days += 1
        else:
            # 间隔 >1 自然日(中间有正常日 / 该日未跑) = 连续链中断, 从 1 重新计
            _days = 1
            _first = _today
    else:
        _days = 1
        _first = _today

    _new_state = {
        "last_fail_date": _today,
        "consecutive_days": _days,
        "first_fail_date": _first or _today,
        "last_grade_time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if rolling_window_days is not None:
        _new_state["seen_dates"] = _seen
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        _tmp = state_path.with_name(state_path.name + ".tmp")
        _tmp.write_text(json.dumps(_new_state, ensure_ascii=False, indent=2), encoding="utf-8")
        _tmp.replace(state_path)
    except Exception as _e:  # noqa: BLE001
        print(f"{log_prefix} 状态落盘失败(连续天数计数可能丢失, 升级档或失效): {_e}",
              file=sys.stderr)

    _tier = "critical" if _days >= escalate_days else "severe"
    return _tier, _days, (_first or _today)


def parse_failed_units(out_text):
    """解析 `systemctl --failed --no-legend --plain` 输出 → 失败 unit 名列表(去重保序)。

    行形如: `trade-xxx.service loaded failed failed Trade xxx`(--no-legend 无表头/无图例)。
    只取每行首个 token(unit 名), 且必须是 .service/.timer/.socket 结尾(过滤描述列/杂行)。
    空输出/None → [](= 无失败 unit, 健康)。
    """
    names = []
    for line in (out_text or "").splitlines():
        tok = line.strip().lstrip("● ").strip().split(" ")[0] if line.strip() else ""
        if tok.endswith((".service", ".timer", ".socket")) and tok not in names:
            names.append(tok)
    return names


def judge_watchman_units(rows):
    """巡检者自身存活判定(纯函数; 供 check_failed_units.py 调用, 单测可注入构造行)。

    rows: 每项 dict —— {"unit": str, "kind": "timer"|"service",
                        "active_state": str|None, "load_state": str|None,
                        "unit_file_state": str|None}
      任一字段 None = systemctl show 读不到 → 视为异常(fail-loud, 不静默)。
    返回 [异常描述, ...](空 = 全健康)。

    判据(requirement: 状态判定用 ActiveState, 禁 is-active):
      - load_state == "not-found" → unit 文件已从盘上消失(巡检被删, 永久静默的根形态)
      - unit_file_state != "enabled" → 巡检 unit 被停用/禁用/掩蔽(不再随开机调度)
      - kind == "timer" 且 active_state != "active" → 巡检 timer 不再在跑(停摆)
    (oneshot service 的 ActiveState 在 inactive/activating 间跳, 故只对 timer 判 active。)
    ⚠️ 「被执行的脚本文件已从盘上消失」是**文件系统 I/O**, 不在本纯函数内: 由调用方
    (check_failed_units.py) 用 extract_script_paths() 取路径 + Path.exists() 判, 再并入告警。
    """
    problems = []
    for r in rows:
        u = str(r.get("unit") or "?")
        kind = r.get("kind") or "service"
        load = r.get("load_state")
        ufs = r.get("unit_file_state")
        active = r.get("active_state")
        if load == "not-found":
            problems.append(f"{u}: unit 文件不在盘(LoadState=not-found) —— 巡检/守护 unit 可能被删")
            continue
        if ufs != "enabled":
            problems.append(f"{u}: UnitFileState={ufs!r}(非 enabled) —— 巡检 unit 被停用/禁用")
        if kind == "timer" and active != "active":
            problems.append(f"{u}: timer ActiveState={active!r}(非 active) —— 巡检不再被调度(停摆)")
    return problems


def extract_script_paths(exec_start_entries):
    """从 `systemctl show -p ExecStart` 行提取「脚本文件绝对路径」(纯解析, 无 I/O)。

    实测云上 systemd 249 格式(9 个守护 unit 全部同形):
      `ExecStart={ path=/bin/bash ; argv[]=/bin/bash /home/ubuntu/.../x.sh ; ... }`
      `ExecStart={ path=/home/.../python ; argv[]=/home/.../python /home/.../x.py ; ... }`
    ⇒ 取 argv[] 里「以 / 开头且以 .sh/.py 结尾」的 token = 被执行的脚本本体。
    **为什么只认 .sh/.py**: 保守 + 零误报 —— 解释器/子命令/flag 一律不认, 认不出返回 []
    (fail-open: 解析不到就不检查, 绝不把「解析失败」报成「脚本被删」)。
    entries 可为 str / list[str] / None(调用方直接喂 systemctl show 的原始行)。

    ⚠️ 调用方须喂「真正持 ExecStart 的 unit」的原始行: `.timer` 自身**无 ExecStart 属性**,
    须先经 check_failed_units._resolve_exec_entries 解析到它触发的 `.service` 再取 ExecStart
    (2026-10-06 #203 根因: 直读 timer 的 ExecStart 恒空 → 本层生产空转/假绿)。
    """
    if isinstance(exec_start_entries, str):
        exec_start_entries = [exec_start_entries]
    out = []
    for e in (exec_start_entries or []):
        m = re.search(r"argv\[\]=([^;]*)", str(e))
        if not m:
            continue
        for tok in m.group(1).split():
            if tok.startswith("/") and tok.endswith((".sh", ".py")) and tok not in out:
                out.append(tok)
    return out


def r1_buffer_judge(alert_state, buf_key, alert_key, exceeds_threshold, now,
                    threshold_rounds=OVERVIEW_LAG_CONTINUOUS_THRESHOLD):
    """R1: overview lag 连续轮 buffer 判定(复用 r2_intraday_lag 模式同构; R1 应用点 =
    schedule_monitor.sh ①overview_lag_3domain 块 L1402 ②r2_overview_lag 块 L1578/L1611)。

    直接读改写 alert_state(dict 引用)。返回 action 字符串:
      "alert"    -> 已达连续轮阈值且 alert_key 首次 active → 调用方应发 SEVERE
      "buffer"   -> 未达阈值, 只记 buffer(不通知; 单次滞后=上传间隙瞬时)
      "suppress" -> 已达阈值但 alert_key 持续 active → 不重发
      "recover"  -> alert_key 曾 active 本轮恢复 → 调用方按 _recovery_cooldown_ok 发/静默恢复邮件
      "ok"       -> 无异常(本轮未滞后且无 active 告警)
    防跨天残留: buf_key 由调用方带 YYYYMMDD 日期维度(隔日自动从 0 起)。
    """
    _ex_alert = alert_state.get(alert_key)
    if not exceeds_threshold:
        # 恢复路径: 清 buffer(防恢复前累计计数在下次单次滞后时 +1 误升级)
        _bf = alert_state.get(buf_key)
        # 2026-10-01 复审修复(R1 恢复循环交互误报): status 含 "recovered" 也清 count——
        # schedule_monitor 恢复循环(L1178-1200)会把上一轮 pending buffer 置 recovered
        # 但不清 consecutive_count(且 r2_ 前缀 buffer 由各块 inline 恢复处理)。若不支持
        # recovered, 「滞后→恢复→再滞后」跨 3 轮时轮2 恢复路径看到 status=recovered
        # 不清 count, 轮3 再滞后 count 残留 +1 直接触顶发假 SEVERE。此处一并清=重置
        # 连续计数基准, 使「恢复后再滞后」从 0 重新计数; 真连续 2 轮滞后(轮2 仍滞后)
        # 不受影响(轮2 走滞后分支, count 照常 +1 → 2 触发, 不吞真故障)。
        if _bf and _bf.get("status") in ("pending", "alerted", "recovered"):
            _bf["status"] = "recovered"
            _bf["consecutive_count"] = 0
            _bf["recovered_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        if _ex_alert is not None and _ex_alert.get("status") == "active":
            return "recover"
        return "ok"
    # 本轮滞后: 连续轮计数
    _bf = alert_state.get(buf_key) or {}
    if _bf.get("status") == "alerted":
        _c = threshold_rounds
    else:
        _c = (_bf.get("consecutive_count") or 0) + 1
    alert_state[buf_key] = {
        "status": "alerted" if _c >= threshold_rounds else "pending",
        "first_seen": _bf.get("first_seen") or now.strftime("%Y-%m-%d %H:%M:%S"),
        "consecutive_count": _c,
        "keyword": alert_key,
    }
    if _c < threshold_rounds:
        return "buffer"
    if _ex_alert is None or _ex_alert.get("status") != "active":
        return "alert"
    return "suppress"


def r2_merge_key(task, last_run):
    """R2: 超时/耗时双通道共享去重 key = merge|{task}|{last_run}"""
    return f"{MERGE_PREFIX}{task}|{last_run}"


def r2_merge_already_sent(alert_state, task, last_run):
    """R2: 同 (task, last_run) 已由另一通道发过告警 → 本通道应 suppress(合并只发 1 条)。

    反例保证(R2-A/B): 同实例超时+耗时合并后仍必响(首条由先发通道发出);
    隔日再次卡死 = 新 last_run → 新 merge key → 独立再响, 不吞跨天。
    """
    if not last_run:
        return False
    _ex = alert_state.get(r2_merge_key(task, last_run))
    return bool(_ex) and _ex.get("status") == "active"


def r2_merge_mark(alert_state, task, last_run, now):
    """R2: 标记同 (task, last_run) 已发告警(先发通道独占, 后发通道查 r2_merge_already_sent)。"""
    if not last_run:
        return
    alert_state[r2_merge_key(task, last_run)] = {
        "status": "active",
        "last_alerted": now.strftime("%Y-%m-%d %H:%M:%S"),
        "keyword": "merged_timeout_dur",
    }


def r2_merge_cleanup(alert_state, now):
    """R2: 清理超 24h 的 merge key(防 alert_state 无界膨胀; merge key 不被恢复循环处理)。"""
    for _k in [k for k in alert_state if k.startswith(MERGE_PREFIX)]:
        _info = alert_state[_k]
        _last = _info.get("last_alerted") or _info.get("first_seen") or ""
        if _last:
            try:
                if now - datetime.strptime(_last[:16], "%Y-%m-%d %H:%M") > timedelta(hours=24):
                    del alert_state[_k]
                    continue
            except (ValueError, TypeError):
                pass


def r3_nextday_product_generated_today(repo, today):
    """R3: nextday_plan 产物是否「今日生成」。

    nextday_plan 22:30 生成 data/nextday_plan.json → mtime 是当天日期代表产物已落盘
    (自身通道 nextday_plan.sh L68-76 已发详细通知) → schedule_monitor exit!=0 汇总通道
    不再对同一失败面双发(去重)。产物未生成(mtime 非今日/文件缺失) = 真失败 → 双保险双响。

    反例保证(R3-B): 产物未生成(真失败) → 返回 False → monitor 仍发汇总(双保险)。
    """
    if repo is None:
        return False
    _p = repo / "data" / "nextday_plan.json"
    if not _p.exists():
        return False
    try:
        _mt = datetime.fromtimestamp(_p.stat().st_mtime)
    except Exception:
        return False
    return _mt.strftime("%Y-%m-%d") == today


def _notify_r4_state_write_fail(state_path, e):
    """R4 分级状态写失败告警(#132, 2026-10-02): 独立 warning, dedup 24h。

    本模块是纯函数库(被 notify.py / schedule_monitor.sh heredoc 引用), 此处经子进程
    调 notify.py CLI 发通知 —— dedup-key 独立(r4_state_write_fail), 与触发自己的
    staticdata_backup_fail 链不冲突不递归; 发送失败仅打印不抛(R4 主流程不被吞,
    stderr 会随调用进程日志落盘可查)。
    """
    import os as _os
    import subprocess as _sp
    import sys as _sys

    _root = Path(__file__).resolve().parent.parent
    _subject = "[告警][staticdata分级] R4 分级状态写失败, 备份缺口分级可能失效"
    _body = (
        f"<b>alert_denoise_rules.r4_staticdata_grade 状态落盘失败</b>: "
        f"<code>{state_path}</code><br>异常: <code>{e}</code><br>"
        f"影响: R4 分级状态(last_fail_date/consecutive_days)无法持久化, "
        f"「连续 &gt;=2 天未追平」的 SEVERE 阈值可能因计数丢失而静默失效。<br>"
        f"建议: 检查 data/ 目录/磁盘权限或空间; 修复后下次 staticdata_backup_fail 自动恢复。"
    )
    _cmd = [_sys.executable, str(_root / "scripts" / "notify.py"),
            _subject, _body, "--tier", "warning", "--from-prefix", "[告警]",
            "--dedup-key", "r4_state_write_fail", "--dedup-window", "86400"]
    if _os.environ.get("R4_STATE_WRITE_DRY_RUN") == "1":
        _cmd.append("--dry-run")
    try:
        _sp.run(_cmd, capture_output=True, text=True, timeout=120)
    except Exception as _ne:  # noqa: BLE001
        print(f"[r4-staticdata-grade] 状态写失败告警发送异常(不阻塞): {_ne}", file=sys.stderr)


def r4_staticdata_grade(heartbeat_path, state_path, now):
    """R4: staticdata 备份部分失败分级(notify.py 对 dedup_key=staticdata_backup_fail 调用)。

    判定(反例 A/B/C 对账):
      - 心跳 result in R4_OK_RESULTS 且其 ts 日期 >= 上次 fail 日期 → 已追平 → info, 连续天数归 0
        (09-30 预算耗尽 fail 后 10-01 备份 ok = 设计允许的追平 → info)
      - 未追平: 新的一天(非同日重复) → 连续天数 +1
        - 连续 >=2 天未追平(真 R2 备份缺口持续) → SEVERE
        - 单日未追平(迁移期一次性) → info(只记 dashboard, 可追溯)
      - manifest 未重写也未追平 → 心跳非 ok → 走未追平路径, 连续 2 天即 SEVERE

    返回 (tier, reason)。
    状态落盘 state_path(原子写): {last_fail_date, consecutive_days, last_grade_time}
    心跳文件缺失/解析失败 → 保守按未追平处理(宁 SEVERE 不漏), continuous 计数看状态文件。
    """
    _state = {}
    try:
        if state_path.exists():
            _state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(_state, dict):
                _state = {}
    except Exception:
        _state = {}
    _last_fail = str(_state.get("last_fail_date") or "")
    _days = _safe_int(_state.get("consecutive_days"))   # #264 收口: 同类面(同款非数值崩点)
    _today = now.strftime("%Y-%m-%d")

    # 追平判定: 心跳最新 ok/skip_oversize 且其 ts 日期 >= 上次 fail 日期
    _caught_up = False
    try:
        if heartbeat_path is not None and heartbeat_path.exists():
            _hb = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            _hb_res = _hb.get("result")
            _hb_ts = str(_hb.get("ts") or "")
            if _hb_res in R4_OK_RESULTS and _hb_ts:
                if not _last_fail or _hb_ts[:10] >= _last_fail:
                    _caught_up = True
    except Exception:
        pass

    if _caught_up:
        _days = 0
    elif _today != _last_fail:
        _days += 1

    _new_state = {
        "last_fail_date": _today,
        "consecutive_days": _days,
        "last_grade_time": now.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        _tmp = state_path.with_name(state_path.name + ".tmp")
        _tmp.write_text(json.dumps(_new_state, ensure_ascii=False, indent=2), encoding="utf-8")
        _tmp.replace(state_path)
    except Exception as _e:
        # #132 fail-loud(2026-10-02): 状态写失败不再静默吞 —— R4 分级状态
        # (last_fail_date/consecutive_days)无法持久化 = 连续天数计数可能丢失 →
        # 真 R2 备份缺口持续却永远到不了 2 天 SEVERE 阈值(防静默机制本体静默)。
        # 走独立 warning(dedup 24h)而非升级 severe: 状态写失败是本地基础设施故障
        # (权限/磁盘), 备份数据级失败仍由心跳/追平判定走原 severe 通道, 不重复告警。
        print(f"[r4-staticdata-grade] 状态落盘失败(连续天数计数可能丢失): {_e}", file=sys.stderr)
        _notify_r4_state_write_fail(state_path, _e)

    if _days >= 2 and not _caught_up:
        return "severe", f"staticdata 备份连续{_days}天未追平(上次 fail {_last_fail or '无记录'} 之后无成功备份)"
    if _caught_up:
        return "info", "staticdata 备份单日预算耗尽但已追平(心跳 ok, 设计允许)"
    if _days < 2:
        return "info", f"staticdata 备份单日失败未追平(连续{_days}天, 观察中)"
    return "info", "staticdata 备份分级判定异常(按 info 兜底)"


def r5_is_r2_congestion_line(line):
    """R5: 判定告警行是否属 R2/部署链路拥堵同根因范畴。

    同根因 = 当天多条 R2 相关告警由同一个系统原因驱动(#149 trade_deploy.lock 队列拥堵 /
    R2 上传链路慢)。命中任一 R2 链路特征(大小写兼收, 覆盖 r2_unreachable 等小写任务名):
      - "R2" / "r2_" 前缀(直连不可达/overview 滞后/intraday 滞后/上传锁跳过/R2 上传超时)
      - "ssd.fx8.store"(R2 存储域名不可达)
      - "upload_r2" / "R2 上传"(上传锁/超时)
    非 R2 告警(漏跑/退出失败/数据错/kelly/fetch_news 低频真问题)不入聚合, 照发。
    """
    _t = line
    if "R2" in _t:
        return True
    if "r2_" in _t:
        return True
    if "ssd.fx8.store" in _t:
        return True
    if "upload_r2" in _t or "R2 上传" in _t:
        return True
    return False


def r5_congestion_process(alert_state, alerts, now, summary_hm="23:25"):
    """R5: R2/部署拥堵同根因日汇总(处理整轮 alerts 列表, 返回 (kept, summary_alert))。

    状态 key r2_pipeline_congestion|{YYYYMMDD} = {phenomena: [], summary_sent: bool}:
      - 当日首条 R2 相关告警 → 照发(保真故障即时性, 反例: 真 R2 全断供首条必响)
      - 第 2 条起 → 从 alerts 移除, 现象并入状态(不再逐条 SEVERE)
      - 当日收尾轮(NOW >= summary_hm, monitor 15min/轮 → 命中 23:30 轮)且现象 >=2 且
        未发汇总 → 返回 1 条汇总 SEVERE(现象清单 + #149 根因指针)
    keep/summary 由调用方替换原 alerts 并持久化状态。

    #245 批2(2026-10-10): monitor 侧起由 alert_budget_process(超集: 按类别日预算)取代;
    本函数**保留不删**(scripts/tests/test_alert_denoise_20261001.py 引用), 供历史测试。
    """
    _today = now.strftime("%Y%m%d")
    _sk = f"{R2_CONGESTION_SUMMARY_KEY_PREFIX}{_today}"
    _st = alert_state.get(_sk)
    if not isinstance(_st, dict):
        _st = {"phenomena": [], "summary_sent": False}
    # 现象列表只留最新 50 条防膨胀
    _st.setdefault("phenomena", [])
    _st.setdefault("summary_sent", False)
    _kept = []
    for _a in alerts:
        if not r5_is_r2_congestion_line(_a):
            _kept.append(_a)
            continue
        _phen = _a[8:] if _a.startswith("SEVERE: ") else _a
        _phen = _phen.split(" now<")[0][:120]
        if _phen not in _st["phenomena"]:
            _st["phenomena"].append(_phen)
        _st["phenomena"] = _st["phenomena"][-50:]
        if len(_st["phenomena"]) <= 1:
            # 当日首条 R2 告警: 照发
            _kept.append(_a)
        else:
            print(f"[r5-congest] 第{len(_st['phenomena'])}种 R2 现象并入当日汇总"
                  f"({_phen[:60]}...)")
    _summary = None
    _hm_now = now.strftime("%H:%M")
    _fma = now.strftime("%H:%M") >= summary_hm
    if len(_st["phenomena"]) >= 2 and not _st.get("summary_sent") and _fma:
        _summary = (
            f"SEVERE: R2/部署链路拥堵日汇总 {_today} "
            f"({len(_st['phenomena'])} 项同根因现象, 根因指针 #149 trade_deploy.lock 队列拥堵, "
            f"见 docs/pending-features-index.md, 处理见 docs/ops/149-deploy-lock-queue-rootcause-20261001.md):<br>"
            + "<br>· ".join("· " + p for p in _st["phenomena"])
        )
        _st["summary_sent"] = True
        print(f"[r5-congest] 生成当日拥堵汇总({_hm_now}, {len(_st['phenomena'])} 项现象)")
    alert_state[_sk] = _st
    return _kept, _summary


def r7_r2_consistency_escalate(state_path, now):
    """R7①: r2_consistency(§22 三站一致性巡检)连续失败天数分级(#160 收口, 2026-10-05 用户拍板)。

    「连续 N 天 FAIL」定义: 相邻自然日各发生一次失败(r2_consistency 每日 23:20 跑一轮)。
    中间夹一个成功日/未跑日(间隔 >1 自然日)即视为连续链中断, 从 1 重新计。

    档位(返回 (tier, consecutive_days, reason), tier in ("severe", "critical")):
      - 首日失败(连续 1 天) → "severe": 与历史行为一致(notify --severe 单封, 6h 去重
        由调用侧 R2_CONSISTENCY_DEDUP_KEY 承担)——单次失败仍是真故障即时告警, 不降噪。
      - 连续 >= R2_CONSISTENCY_ESCALATE_DAYS(2) 天失败 → "critical": 升级档
        (换 R2_CONSISTENCY_ESCALATED_DEDUP_KEY 独立窗口 → 不被首日的 6h 窗吞掉 → 必达;
        邮件 + 飞书 alert 群, 与 severe 同渠道但显式标注「连续 N 天」)。
    同日重复调用(手动重跑/重试) → 天数不变(不重复计数)。

    状态落盘 state_path(原子写): {last_fail_date, consecutive_days, first_fail_date,
    last_grade_time}。故意**不**依赖外部「成功心跳」文件: 成功日在通知链路上根本不会调用本函数,
    间隔 >1 天即自然中断(省一个跨脚本耦合点)。

    残余(如实登记): 状态无法落盘时(权限/磁盘)连续天数恒为 1 → 升级档静默失效; 此时首日
    severe 通道仍然照发(不吞真故障), 且 stderr 打印落进包装器日志可查 —— 只丢「升级」不丢
    「告警本身」。
    """
    # 计数/落盘逻辑收敛到 consecutive_days_escalate 单一实现(#196 起 R7 与 failed-unit/patrol
    # 两个新通道共用), 本函数只保留 R7 专属的档位措辞(reason 文案是 R7 语义, 不复用通用文案)。
    _tier, _days, _first = consecutive_days_escalate(
        state_path, now, R2_CONSISTENCY_ESCALATE_DAYS, log_prefix="[r7-r2-consistency]")
    _today = now.strftime("%Y-%m-%d")
    if _tier == "critical":
        return "critical", _days, (
            f"连续 {_days} 天一致性校验失败(自 {_first} 起, 末次 {_today})")
    return "severe", _days, f"首日失败({_today}, 当前连续 {_days} 天)"


def wrapper_channel_alerted(repo, last_run, dedup_key):
    """通用: 某「包装器自身通道」是否**已为本次运行实例**发过告警(dedup_key 由调用方指定)。

    单一实现(R7 是第一处应用, #196 的 patrol/_failed-unit 复用): 同一次 FAIL 常有两通道
    ——①包装器/巡检脚本自己 notify --severe(带问题明细) ②schedule_monitor exit!=0 汇总
    通道 / failed-unit 巡检 再发一封。②是①的复述 → 用本函数判定后抑制。

    判据: data/notify_dedup.json 的 <dedup_key>.last_alerted >= last_run
      (last_run = 本次运行开始时刻, 由 gen_schedule_stats 记录; 包装器在本次运行内发出告警
      时 last_alerted 必然 >= last_run)。用「本次实例」而非「今天」: 失败持续到次日时,
      昨日告警仍 >= 昨日 last_run → 次日全天不重复复述。

    反例保证(真故障不吞): 包装器告警**发送失败**(update_dedup 只在发送成功后写)或脚本在
    notify 前被杀 / notify_dedup.json 缺失 → 返回 False → 汇总通道照发(双保险)。
    解析失败一律 False(fail-open: 宁多告警不漏)。
    """
    if repo is None or not last_run:
        return False
    try:
        _lr_dt = datetime.strptime(str(last_run)[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return False
    try:
        _p = Path(repo) / "data" / "notify_dedup.json"
        if not _p.exists():
            return False
        _st = json.loads(_p.read_text(encoding="utf-8"))
        _entry = _st.get(dedup_key) if isinstance(_st, dict) else None
        _last = (_entry or {}).get("last_alerted")
        if not _last:
            return False
        _al_dt = datetime.strptime(str(_last)[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return False
    return _al_dt >= _lr_dt


def r7_r2_consistency_wrapper_alerted(repo, last_run, dedup_key=R2_CONSISTENCY_DEDUP_KEY):
    """R7②: r2_consistency 包装器自身通道是否已为本次运行实例发过告警。

    给 schedule_monitor 的 exit!=0 汇总通道去重用(同 R3 nextday_plan 先例): 同一次 FAIL
    会有两条通道 —— ①包装器 check_r2_consistency.sh 自己 notify --severe(去重 key
    r2_consistency_fail, 内容含问题明细)②gen_schedule_stats 记 last_exit!=0 →
    schedule_monitor exit!=0 通道再发一封(去重 key {task}|exit!=0|{code})。②是①的复述。

    实现已收敛到 wrapper_channel_alerted(单一实现), 本函数保留 R7 语义命名 + 默认 key。
    """
    return wrapper_channel_alerted(repo, last_run, dedup_key)


# ══ #245 批2 L2 预算+摘要层(2026-10-10) ═══════════════════════════════════════
# 类别维度 + 日预算 + 台账当日直发计数 + monitor 批次行级吸收。纯函数, 可单测。
# 计数单一事实源 = W1 台账(data/alerts/alert_ledger.jsonl)——跨通道统一数字(§22),
# 与 alert_meter 展示口径一致。诚实标注: 未映射类别一律 exempt(不限预算, 直发),
# 首版只咬「已识别的重复族」(宁多发不吞, 见 spec §1.2/§1.3)。
# ⚠️ 计数口径(2026-10-13 修 B1, 见 docs/ops/... 「降噪吞 severe」): 只数 tier=="critical"
# 的行(severe 直发登记口径); notice/warning 行不吃 severe 额度。
ALERT_BUDGET = {
    "unit": 1, "r2": 1, "data_gap": 1, "gap_check": 1,
    "deploy": 1, "fund_nav": 1, "kelly": 1,
}


def category_of(key, subject):
    """键/主题 → 告警类别(未映射返回 None=不限预算)。

    key 优先(前缀/子串), subject 兜底; 均 case-sensitive(沿用 dedup key 风格)。
    映射表见 docs/ops/245-batch2-impl-spec-20261010.md §1.2(基于 10-08 直发样本)。
    """
    _k = str(key or "")
    _s = str(subject or "")
    if "unit_patrol" in _k or "failed_units" in _k or "cloud_unit_patrol" in _k:
        return "unit"
    if _k.startswith("r2_") or "r2_pipeline_congestion" in _k:
        return "r2"
    if "data_gap" in _k or "[数据缺口]" in _s:
        return "data_gap"
    if _k in (NEXTDAY_GAP_DEDUP_KEY, "nextday_gap_check_gen_fail") or "伪跳空" in _s:
        return "gap_check"
    if _k.startswith("deploy_"):
        return "deploy"
    if _k.startswith("fund_nav"):
        return "fund_nav"
    if "kelly" in _k:
        return "kelly"
    return None


def category_of_line(line):
    """monitor 批次行文本 → 类别(未映射返回 None)。strip "SEVERE: " 前缀后判定。

    与 category_of 的分工: 行文本没有 dedup key, 只能靠 task 前缀/文本特征(§1.2)。
    """
    _t = str(line or "")
    if _t.startswith("SEVERE: "):
        _t = _t[len("SEVERE: "):]
    if r5_is_r2_congestion_line(_t):
        return "r2"
    if "[数据缺口]" in _t:
        return "data_gap"
    if "nextday_gap_check" in _t or "伪跳空" in _t:
        return "gap_check"
    _toks = _t.split()
    _first = _toks[0] if _toks else ""
    if "unit_patrol" in _first or "failed_units" in _first:
        return "unit"
    if "deploy" in _t:
        return "deploy"
    return None


def ledger_day_direct_index(repo, day=None):
    """台账当日各类别「已直发(severe)」行的签名索引(category -> [key...], 含重复)。

    单一事实源; **只数 tier=="critical" 的行**:
      B1(2026-10-13 修「降噪吞 severe」): severe 直发统一登记 tier=critical
      (notify.py L1210 `ledger_tier or ("critical" if severe else "notice")`), 而 notice
      (告警转发/买卖点/恢复)与 warning 行同样落台账、却不是 severe 直发 —— 旧口径
      `tier!="digest"` 把它们一并计入 ⇒ notice 行吃掉 severe 的当日类别额度(10-12 22:35
      「公募基金 20261009 采集全 NULL: 24224 行」severe 被同日 22:35:27 一条 notice 行
      挤掉额度, 并入摘要未直发)。改后 notice/warning 不再吃额度。
    只取: ts 前缀==day 且 group=="alert" 且 tier=="critical"。
    坏行跳过 / 文件缺失 → 空 dict(绝不因台账问题吞告警, fail-open)。
    """
    _day = day or datetime.now().strftime("%Y-%m-%d")
    index: dict[str, list[str]] = {}
    if repo is None:
        return index
    try:
        _p = Path(repo) / "data" / "alerts" / "alert_ledger.jsonl"
        if not _p.exists():
            return index
        for _ln in _p.read_text(encoding="utf-8").splitlines():
            _ln = _ln.strip()
            if not _ln:
                continue
            try:
                _r = json.loads(_ln)
            except json.JSONDecodeError:
                continue
            if not isinstance(_r, dict):
                continue
            if str(_r.get("ts", ""))[:10] != _day:
                continue
            if _r.get("group") != "alert":
                continue
            if _r.get("tier") != "critical":
                continue
            _c = category_of(_r.get("key"), _r.get("subject"))
            if _c:
                index.setdefault(_c, []).append(str(_r.get("key", "")))
    except Exception:  # noqa: BLE001  台账问题绝不吞告警
        return index
    return index


def ledger_day_direct_counts(repo, day=None):
    """台账当日各类别「已直发(severe)」条数 = 索引长度(兼容既有调用方)。

    口径同 ledger_day_direct_index(B1: 只数 tier=="critical")。
    """
    return {c: len(ks) for c, ks in ledger_day_direct_index(repo, day).items()}


def ledger_day_direct_keys(repo, day=None):
    """台账当日各类别「已直发(severe)」的**故障签名集合**(category -> set(key))。

    B2(2026-10-13)「新签名必达」判据用: gate 并入前比对本条签名是否已在本集合内 ——
    在=同签名重复(并入); 不在=新故障签名(直发, 复用 #240②「added→立即报」方法论)。
    """
    return {c: set(ks) for c, ks in ledger_day_direct_index(repo, day).items()}


def _budget_entry(line, category, now):
    """构造吸收条目(供 monitor 的 --defer-digest 循环; key 仅用于摘要展示/幂等)。"""
    _t = str(line)
    _body = _t[8:] if _t.startswith("SEVERE: ") else _t
    _toks = _body.split()
    _task = _toks[0] if _toks else "alert"
    _h = hashlib.md5(_t.encode("utf-8", errors="replace")).hexdigest()[:8]
    _ts = now.strftime("%Y-%m-%d %H:%M:%S") if hasattr(now, "strftime") else str(now)
    return {"line": _t, "category": category, "key": f"{_task}|{_h}", "ts": _ts}


def alert_budget_process(alert_state, alerts, now, repo, day=None):
    """monitor 批次行级预算: 逐行判类别预算, 超预算的行移出批次(交 --defer-digest 吸收)。

    返回 (kept, absorbed)。**不写 alert_state**(计数实时读台账, 无需状态键)。
    counts 从 ledger_day_direct_counts 起算(当日已直发数) + **同轮乐观增量**(同轮第 2 条
    同类行吸收, 镜像「首条直发」语义)。台账读不到 → 全 0 → 全部 kept(=现状 fail-open)。
    B1(2026-10-13): counts 只数 tier=="critical" 行(severe 直发口径), notice/warning 行不再
    吃额度 —— 与 notify.py gate 同一共享函数, 一刀两端。
    B2 边界(2026-10-13 诚实标注): 本层**不做**「新签名必达」(notify gate 侧做了)——
    monitor 批次行的故障签名(台账 key)是**每轮载荷哈希**(notify.py 批次 subject 含轮次时间,
    key=sha1(subject)), 无跨轮稳定签名可比; 且 monitor 上游 alert_state 已自带「同故障抑制
    重发」层(批次里的行本身绝大多数就是新故障), 实测近 14 天 severe 类零吸收(仅 recovery
    补列 1 条)。若将来要给本层加 B2, 需先给批次行引入稳定签名源(勿凭空哈希)。
    加强档 task_family 第二层(默认 OFF, env ALERT_BUDGET_TASK_FAMILY=1 开启, 拍板项见 spec
    §0.3/§1.3): 同类判完后对 kept 行再按 task 分组, 超 task 预算(1/日)的行转入 absorbed。

    回滚(#245 批2 F1 订正, 2026-10-10): `ALERT_BUDGET_DISABLE=1` 是 **L2 全链总开关** ——
    本层同样短路返回全部 kept(逐字节回现状: 批次行全直发, 无吸收), 与 notify.py send()
    gate / --defer-digest CLI 三处开关齐, 否则「置总开关=完整回滚」声明不成立(monitor 侧
    仍抽走批次行而 flush 被停 → 静默吞告警)。
    """
    if os.environ.get("ALERT_BUDGET_DISABLE") == "1":
        return list(alerts), []
    counts = ledger_day_direct_counts(repo, day)
    _fam_on = os.environ.get("ALERT_BUDGET_TASK_FAMILY") == "1"
    kept, absorbed = [], []
    for _a in alerts:
        _c = category_of_line(_a)
        if _c is None:
            kept.append(_a)
            continue
        _lim = ALERT_BUDGET.get(_c, 1)
        if counts.get(_c, 0) < _lim:
            counts[_c] = counts.get(_c, 0) + 1
            kept.append(_a)
        else:
            absorbed.append(_budget_entry(_a, _c, now))
    if _fam_on and kept:
        _tcnt = {}
        _kept2 = []
        for _a in kept:
            _body = _a[8:] if _a.startswith("SEVERE: ") else _a
            _toks = _body.split()
            _t = _toks[0] if _toks else "alert"
            if _tcnt.get(_t, 0) < 1:
                _tcnt[_t] = _tcnt.get(_t, 0) + 1
                _kept2.append(_a)
            else:
                absorbed.append(_budget_entry(_a, category_of_line(_a) or "task_family", now))
        kept = _kept2
    return kept, absorbed


# ══ #264 件C 故障域聚合层(域 inhibition, 2026-10-15) ════════════════════════════
# 依据(RCA docs/ops/alert-noise-rca-20261015.md §4.1 C): 10-15 一个真实 R2 故障被 7~8 个
# 脚本各自独立告警 = 同一故障域 28 条(现 83 条里最大的一坨); 全站此前无 domain 概念;
# 业界对照 = Alertmanager 的 group_by / inhibit_rules + group_interval(§4.0)。
#
# 口径(降噪铁律, 收敛计划 alert-convergence-plan-20261010.md L10):
#   ① 首报必达: 域首条 / 跨自然日首条 / 静默窗外复发 一律直发(即「本条 = 新事件」);
#   ② 不吞真故障判别维度: 被并入的条目 100% 进摘要正文逐条列出(key/来源脚本/正文全留,
#      可逐条检索), 且不占用/不改变 critical 的发送与额度;
#   ③ 不同根因不并: 不同域各自独立首报(真故障反例), 未映射域一律直发;
#   ④ 宁多勿吞(fail-open): 域未映射 / 状态写盘失败 / dry-run / 域开关关闭 ⇒ 直发。
#
# 语义 = Alertmanager 的「分组静默窗」: 距上一条**同域**告警 < 窗口 ⇒ 本条属同一事件派生,
#   并入当日摘要; 否则视为「上一事件已结束后的复发 / 新事件」⇒ 直发。
#   窗口**不跨自然日** ⇒ 「持续未清」每自然日仍有一次直发(留一条分页通道, 与 §4.0
#   SRE「分页 vs 工单/摘要」分级精神一致), 同时把「跨日 rollover 重复播报」压在 1 条/日。
ALERT_DOMAIN_STATE_FILENAME = "alert_domains.json"      # data/alerts/ 下: 各域 last_seen/计数
ALERT_DOMAIN_GROUP_INTERVAL = 7200                      # 域静默窗(秒; 默认 2h = RCA 建议 group_interval)
DOMAIN_ABSORB_REASON = "domain_inhibited"               # 域聚合并入摘要的 reason 标记
# 域聚合豁免键(2026-10-22 审查差集 D3): 以下通道是「全局停摆/已连续失败」级的关键告警,
# 被同域 2h 静默窗吸收会推迟到 23:25 摘要才交付 —— 停摆告警迟到等于没告警。必须直发。
# deploy_consecutive_fail = deploy 连续失败停摆告警(替代「39 次零成功两天无人知」的兜底通道;
#   其 dedup_key 以 deploy_ 前缀本会落 r2_deploy 域, 故显式豁免)。
DOMAIN_AGGREGATE_EXEMPT_KEYS = frozenset({"deploy_consecutive_fail"})
# 前缀豁免: monitor 的「持续故障升级提醒」(B,#282) 是人工处置超时的强制提醒, 不得被同域
# 2h 静默窗吸收(其主题可能带 R2/备份等字样 ⇒ 会误落 r2_deploy 域)。
DOMAIN_AGGREGATE_EXEMPT_PREFIXES = ("active_escalate|",)
DOMAIN_R2_RC_RE = re.compile(r"\br2(?:large)?=(\d+)")   # 主题内 R2 rc 值(≠0 ⇒ 该告警派生自 R2 链路失败)
DOMAIN_LABELS = {                                       # 域 → 人读标签(摘要正文用, 说人话)
    "data_gap": "数据缺口",
    "gap_check": "伪跳空/次日计划",
    "r2_deploy": "R2/双树/部署链路",
    "snapshot": "快照/S06",
    "unit": "云上 systemd 单元",
    "kelly": "信号凯利",
    "fund_nav": "公募基金净值",
    "collect": "采集/回补",
}


def domain_of(key, subject) -> str | None:
    """键/主题 → 故障域(未映射返回 None = 不聚合, 照发)。顺序敏感(首个命中胜出)。

    域表定稿依据 = 10-15 真实台账逐条归纳(RCA §1.4 的事件域表) + notify.py 既有
    event/类别归纳; 与 category_of(L2 预算类别)的分工: **域是更粗粒度的「同一故障域」**
    —— r2 与 deploy 合一(部署→上传→校验是同一条流水线, RCA §1.4 按一个域计 28 条),
    category 维持原样不动(预算额度不因本层改动)。
    优先序 = ①显式类别标记(数据缺口/伪跳空, 最强) > ②R2/双树/部署链路(最大域; 含主题里
    R2 rc≠0 的派生告警, 如 S06 rc=124 ⇒ 归根因域) > ③其余单脚本域。
    ⚠️ 不并入 history_overwrite(历史行改写): 每次出现的表/条数不同(index_daily 1 条 vs
    signal_daily 997/1000 条)= 无法判定「同一事实」⇒ 宁漏不误并, 保持直发(报告 §③ 定稿理由)。
    """
    _k = str(key or "")
    _kl = _k.lower()
    _s = str(subject or "")
    _sl = _s.lower()
    # ① 显式类别标记(方括号类别 = 人工定义的事件类, 优先于根因域)
    if "[数据缺口]" in _s or "数据缺口" in _s:
        return "data_gap"
    if "伪跳空" in _s or "nextday_gap_check" in _k:
        return "gap_check"
    # ② R2/双树/部署链路(最大故障域)
    if (_k.startswith("r2_") or "r2_fail" in _k or "r2_consistency" in _k
            or "r2_pipeline" in _k or _k.startswith("deploy_")
            or _k.startswith("update_all_severe")):
        return "r2_deploy"
    # 「R2 脱节 / 异源覆盖」= verify-r2 兜底的两个 key（subject 哈希，无显式 --dedup-key）:
    #   `[告警] 独立上传链产物与 R2 脱节(verify-r2 兜底补传)`
    #   `[告警] R2 可能被异源覆盖(verify-r2 大量不一致)`
    # 7 天台账 17 条同域重复直发（RCA2 §2），补域映射后按 2h 静默窗聚合（首报仍直发）。
    # ⚠️ 禁写裸 `"R2 "`：会把「R2 上传」以外的无关主题一起吸进本域。
    if ("R2 上传" in _s or "R2上传" in _s or "ssd.fx8.store" in _s or "双树" in _s
            or "三站一致性" in _s or "锁跳过" in _s or "计划任务异常" in _s
            or "统一deploy" in _s or "数据产物校验失败" in _s
            or "R2 脱节" in _s or "R2脱节" in _s or "异源覆盖" in _s):
        return "r2_deploy"
    if any(int(_m) != 0 for _m in DOMAIN_R2_RC_RE.findall(_sl)):
        return "r2_deploy"
    # ③ 其余单脚本域
    if "s06" in _kl or "snapshot" in _kl or "S06" in _s or "快照" in _s:
        return "snapshot"
    if ("unit_patrol" in _k or "failed_units" in _k or "cloud_unit_patrol" in _k
            or "failed unit" in _sl):
        return "unit"
    if "kelly" in _kl or "kelly" in _sl or "凯利" in _s:
        return "kelly"
    if _kl.startswith("fund_nav") or "公募基金" in _s:
        return "fund_nav"
    if "backfill" in _kl or "backfill" in _sl or "采集" in _s:
        return "collect"
    return None


def domain_inhibit_judge(state, domain, now, interval_seconds=None) -> tuple:
    """判定本条同域告警 = 「首报(直发)」还是「同事件派生(并入摘要)」。

    返回 (action, entry): action ∈ {"first", "absorb"}; entry = 更新后的域状态条目
    (调用方在**真发出/真并入之后**写回 state —— 对齐 P1-1「发送成功才占窗」,
    发送失败不占窗 ⇒ 下次同域告警仍是 first 重试, 绝不因一次发送失败静默 2h)。
    规则: 无历史 / 跨自然日 / 距上一条同域告警 >= 窗口 ⇒ "first"; 否则 "absorb"。
    纯函数(不读盘不写盘), 可单测。
    """
    _iv = ALERT_DOMAIN_GROUP_INTERVAL if interval_seconds is None else int(interval_seconds)
    _today = now.strftime("%Y-%m-%d") if hasattr(now, "strftime") else str(now)[:10]
    _now_ts = now.strftime("%Y-%m-%d %H:%M:%S") if hasattr(now, "strftime") else str(now)
    _cur = state.get(domain) if isinstance(state, dict) else None
    _cur = _cur if isinstance(_cur, dict) else {}
    _last = None
    _raw = str(_cur.get("last_ts") or "")
    if _raw:
        try:
            _last = datetime.strptime(_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            _last = None
    _in_window = False
    if _last is not None and _last.strftime("%Y-%m-%d") == _today:
        try:
            _in_window = (now - _last).total_seconds() < _iv
        except TypeError:  # tz-aware 混 naive → 不判窗, 当新事件直发(fail-open)
            _in_window = False
    action = "absorb" if _in_window else "first"
    _entry = {
        "last_ts": _now_ts,
        "last_day": _today,
        "day_first_ts": str(_cur.get("day_first_ts") or _now_ts) if _cur.get("last_day") == _today
                        else _now_ts,
        "n_direct": int(_cur.get("n_direct") or 0) + (1 if action == "first" else 0),
        "n_absorbed": int(_cur.get("n_absorbed") or 0) + (1 if action == "absorb" else 0),
        # #282(2026-10-22 报告盲区 10): n_absorbed 是**累计**值, 旧日志却写「本日该域已并入
        # N 条」= 口径误导。新增「本日」独立字段(跨日归零); 旧状态无此字段时从本日 0 起算,
        # 绝不把历史累计冒充本日。累计值 n_absorbed 保留供排查趋势。
        "n_absorbed_today": (
            (int(_cur.get("n_absorbed_today") or 0) if _cur.get("last_day") == _today else 0)
            + (1 if action == "absorb" else 0)),
        "interval": _iv,
    }
    return action, _entry


def domain_aggregate_summary(entries) -> dict:
    """按域汇总摘要条目(纯函数): domain -> {"n", "sources": [...], "first_hm", "first_key"}。

    供摘要正文「【故障域 X】共 N 条, 涉及 M 个来源脚本」段 —— C-③ 的「多少通道/脚本受影响」
    判别维度必须保留在合并消息里(不做逐域静默)。
    """
    _out: dict[str, dict] = {}
    for _e in entries or []:
        _d = str(_e.get("domain") or "")
        if not _d:
            continue
        _g = _out.setdefault(_d, {"n": 0, "sources": [], "first_hm": "--:--", "first_key": ""})
        _g["n"] += 1
        _src = str(_e.get("source") or "")
        if _src and _src not in _g["sources"]:
            _g["sources"].append(_src)
        _hm = str(_e.get("ts") or "")[11:16] or "--:--"
        if _g["first_hm"] == "--:--":
            _g["first_hm"] = _hm
            _g["first_key"] = str(_e.get("key") or "")
    return _out


# ══ #264 件E 非 critical 重复类预算 + 跨日 rollover(2026-10-15) ══════════════════
# 依据(RCA §4.1 E): merged_in_digest 仅 3 条/日(容量太小 ⇒ 几乎不挡); 跨日 rollover(被预算
# 吸收的事件次日重新计数再发); 恢复类消息(闭环信号)无痕迹。
# 口径: 「非 critical 重复类超预算 ⇒ 入摘要」; **critical 结构性豁免**(下挂 gate 只在
# not severe 时可达 ⇒ 物理上不可能吞 critical, 与 10-14 已修约束 440c9b8cd 正交);
# 计数走独立台账口径(tier ∈ {notice, warning}) ⇒ 绝不与 severe 额度互相挤占(B1 不破)。
ALERT_NOTICE_BUDGET = {                                 # 非 critical(notice/warning)各类别日额度
    "unit": 1, "r2": 1, "data_gap": 1, "gap_check": 1,  # 默认同 ALERT_BUDGET; 独立可调
    "deploy": 1, "fund_nav": 1, "kelly": 1,             # (改一处不动 critical 额度)
}
NOTICE_OVER_BUDGET_REASON = "notice_over_budget"
ROLLOVER_ABSORB_REASON = "rollover_digested"
ALERT_DIGEST_SEEN_FILENAME = "alert_digest_seen.json"   # 已被并入摘要的签名 → 最后并入日
ALERT_DIGEST_ROLLOVER_DAYS = 3                          # rollover 记忆窗(天): 窗内再次出现 ⇒ 仍并入


def ledger_day_notice_index(repo, day=None):
    """台账当日各类别「非 critical 直发(notice/warning)」行的签名索引(category -> [key])。

    与 ledger_day_direct_index(B1: tier=="critical")**并行的独立口径**: 只取
    group=="alert" 且 tier ∈ {"notice","warning"} 的行 —— 两套额度互不挤占(B1 不破)。
    坏行跳过 / 文件缺失 → 空 dict(绝不因台账问题吞告警, fail-open)。
    """
    _day = day or datetime.now().strftime("%Y-%m-%d")
    index: dict[str, list[str]] = {}
    if repo is None:
        return index
    try:
        _p = Path(repo) / "data" / "alerts" / "alert_ledger.jsonl"
        if not _p.exists():
            return index
        for _ln in _p.read_text(encoding="utf-8").splitlines():
            _ln = _ln.strip()
            if not _ln:
                continue
            try:
                _r = json.loads(_ln)
            except json.JSONDecodeError:
                continue
            if not isinstance(_r, dict):
                continue
            if str(_r.get("ts", ""))[:10] != _day:
                continue
            if _r.get("group") != "alert":
                continue
            if _r.get("tier") not in ("notice", "warning"):
                continue
            _c = category_of(_r.get("key"), _r.get("subject"))
            if _c:
                index.setdefault(_c, []).append(str(_r.get("key", "")))
    except Exception:  # noqa: BLE001  台账问题绝不吞告警
        return index
    return index


def rollover_absorb_judge(seen, sig, now, days=None) -> tuple:
    """跨日 rollover 判据: 该签名是否在记忆窗内已被并入过摘要(且不是今天)。

    返回 (should_absorb, seen): 命中 ⇒ 本条属「已并入过的事件次日重现」⇒ 仍并入摘要,
    不再当新事件直发(病灶见 RCA §2.2 ④b: 被吸收事件次日重新计数再发)。
    纯函数; seen 的裁剪由 rollover_prune 负责(调用方落盘前调)。
    """
    _days = ALERT_DIGEST_ROLLOVER_DAYS if days is None else int(days)
    _today = now.strftime("%Y-%m-%d") if hasattr(now, "strftime") else str(now)[:10]
    _d = str((seen or {}).get(str(sig)) or "")
    if not _d or _d == _today:
        return False, seen
    try:
        if (datetime.strptime(_today, "%Y-%m-%d")
                - datetime.strptime(_d, "%Y-%m-%d")).days <= _days:
            return True, seen
    except ValueError:
        return False, seen
    return False, seen


def rollover_prune(seen, now, days=None) -> dict:
    """裁剪记忆表: 只保留最近 days 天内的签名(防状态无限膨胀)。纯函数。"""
    _days = ALERT_DIGEST_ROLLOVER_DAYS if days is None else int(days)
    _today = now.strftime("%Y-%m-%d") if hasattr(now, "strftime") else str(now)[:10]
    _out = {}
    for _sig, _d in (seen or {}).items():
        try:
            if 0 <= (datetime.strptime(_today, "%Y-%m-%d")
                     - datetime.strptime(str(_d), "%Y-%m-%d")).days <= _days:
                _out[_sig] = _d
        except ValueError:
            continue
    return _out# ══ 停摆级告警独立通道(A, 2026-10-22) ════════════════════════════════════════════
# 依据(只读评估报告 /tmp/research-alert-denoise-eval.md §5 盲区 1/2/5/6/14):
#   · 10-20/21 deploy 连续失败 39 次零成功, 15 条 deploy/R2 失败被域聚合埋进 23:30 摘要;
#   · staticdata 备份停摆 36h 才出现一条泛化的「1项计划任务异常」;
#   · D1 同步连续失败 39 次零告警(修前); unit 异常同样会进 2h 域静默窗。
# 口径(§7.3 之 1): 停摆级 = 「整条链路/数据产物已停止产出」, 必须 2 小时内独立直发,
#   **永不进域摘要、不受日预算限制**; 但保留同键 2h 去重(防每轮重复轰炸)。
#   例外: 调用方显式传 --dedup-window 0(脚本自管闸门)时保留 0 —— 见 stall_dedup_window()。
# 与 D3(DOMAIN_AGGREGATE_EXEMPT_KEYS 只豁免 deploy_consecutive_fail)的关系: 本表是它的
#   超集 + 统一判据; notify.py 在预算/域 gate **之前**短路, D3 原豁免保留(向后兼容)。
STALL_DEDUP_WINDOW = 7200                    # 停摆级同键最短去重窗(2h, 报告 §7.3 时限)
STALL_PREFIX = "【停摆】"                     # 外发标题醒目前缀(邮件/飞书/telegram 同一 subject)
# active 升级提醒自己的标题标记(schedule_monitor.sh:_active_escalate 生成) ——
# 见到它就**禁止** subject 兜底判停摆(MF2: 升级提醒必须用自己的键与去重窗)。
STALL_ESCALATE_SUBJECT_MARK = "【持续故障升级】"

# 停摆级键登记表(按**生产真实键名**登记, 覆盖报告点名的 5 类; 新增键必须在此或 NON_STALL_KEYS)
STALL_KEYS = frozenset({
    # ① deploy 连续失败停摆
    "deploy_consecutive_fail",
    "deploy_r2_upload_fail",          # deploy 主链 R2 上传失败 ⇒ 整条发布链没产出
    "deploy_purge_low_freq_fail",     # deploy 收尾 purge 失败 ⇒ CDN 旧缓存长期不刷新
    # ② staticdata 备份失败/停摆
    "staticdata_backup_fail",         # 备份收口失败(连续 >=2 天仍 severe; 单日分级见 R4)
    "staticdata_backup_trigger_fail", # 异步备份触发失败 ⇒ 本轮备份根本没启动
    "staticdata_backup_stale",        # 心跳 >36h 无完成 = 备份停摆(monitor 兜底)
    # ③ R2 上传失败/超时(链路级, 非单数据集单轮上传)
    "r2_upload_trigger_fail",         # 统一上传触发器失败 ⇒ 全量上传停摆
    # ④ D1 同步连续失败
    "d1_sync_fail",
    # ⑤ unit 连续失败(同一 unit/集合 >=N 轮)
    "failed_units_patrol",
    "cloud_unit_patrol_drift",
})

# 非停摆级键登记表(防遗漏机制: 测试扫描 scripts/ 全部 --dedup-key 字面量, 必须二者其一)。
# 每条都写明「为什么不是停摆级」——新增/改名键未登记 ⇒ 防遗漏测试直接红, 逼人做判定。
NON_STALL_KEYS = frozenset({
    # 单轮/单次失败: 下一次调度会自愈, 且已有各自的去重/域窗; 不构成整条产物停摆
    "brief_push_fail", "daily_brief_fail", "nextday_plan_fail", "nextday_gap_check_fail",
    "board_etf_map_stale", "s06_snapshot_fail", "turnover_backfill_fail",
    "gold_night_collect_fail", "gold_night_r2_upload_fail",
    "intraday_upload_index_r2_fail", "intraday_upload_intraday_r2_fail",
    "intraday_schedule_stats_r2_fail", "intraday_sentiment_r2_upload_fail",
    "schedule_stats_r2_fail", "fund_nav_async_upload_fail",
    "kelly_intraday_upload_r2_fail", "kelly_intraday_rerun_fail",
    "kelly_intraday_verify_fail", "kelly_intraday_gate_decider_crash",
    "update_lab_r2_upload_fail", "update_lab_labjson_r2_fail", "update_lab_tradesim_r2_fail",
    "preupload_backup_fail", "r2_upload_async_skip", "update_all_severe",
    # deploy 单次闸门失败(非连续失败聚合通道; 连续停摆由 deploy_consecutive_fail 覆盖)
    "deploy_check_data_integrity_fail", "deploy_check_data_integrity_alertonly",
    "deploy_check_placeholder_residue_fail", "deploy_check_task_state_fail",
    "deploy_check_universe_fail", "deploy_check_version_fail",
    # staticdata 守卫/跳过类: 明确是「按设计跳过」或可自愈的单环节错误, 不是停摆
    "staticdata_backup_repo_missing", "staticdata_backup_oversize_skip",
    "staticdata_backup_nonprod_skip", "staticdata_backup_r2_nonprod_skip",
    "staticdata_backup_guard_error", "staticdata_backup_r2_guard_error",
    "staticdata_backup_gate_reject", "staticdata_backup_gate_error",
    "staticdata_sync_gate_error", "staticdata_sync_gate_reject",
    "staticdata_sync_guard_error", "staticdata_sync_nonprod_skip",
    "staticdata_sync_oversize_skip",
    # 巡检者自身存活心跳 + 三站一致性(语义待 #279 收口, 不是产出停摆)
    "schedule_monitor_heartbeat", "r2_consistency_fail",
    # 状态文件写失败(写不了状态 ≠ 数据产物停摆; 下一轮会重试, 属本次动作失败)
    "agent_inbox_state_write_fail", "anomaly_dedup_write_fail",
    "data_gap_state_write_fail", "feishu_cursor_write_fail",
    "healthcheck_state_write_fail", "r4_state_write_fail",
    "retry_fm_count_file_write_fail",
    # 冻结表/信号缺失: 是「缺输入数据」告警, 由回测链路自身重跑补齐, 非发布/备份停摆
    "kelly_freeze_orphan_buy", "signal_kelly_frozen_missing",
    "signal_kelly_frozen_missing_small",
    # 恢复通知(报「已恢复」, 不是故障本身)
    "schedule_monitor_recovery",
})

# 文本兜底: 没有 dedup key 的批次行(monitor 聚合通道)按行文特征识别停摆级
# ⚠️ #282 审查 MF1(2026-10-22): 原泛化 marker ("停摆", "staticdata_backup_stale") 会把
#   EXTRA 任务停摆行(`<task> 停摆(超 Nh 未运行)`, schedule_monitor.sh:1397)也判成
#   staticdata 心跳停摆 ⇒ 两者共用同一去重键互相 2h 抑制, 正文还张冠李戴成
#   「备份心跳超 36h」。现改为两条精确判据(见下方 _EXTRA_STALL_RE/_STATICDATA_STALL_RE),
#   本表不再收泛化「停摆」二字。
STALL_LINE_MARKERS = (
    # ⚠️ 顺序敏感: 具体特征必须排在泛化「连续失败」之前, 否则 D1 行会被抢判成合成键。
    ("D1 同步连续失败", "d1_sync_fail"),
    ("cloud_unit_patrol_drift", "cloud_unit_patrol_drift"),
    ("failed_units_patrol", "failed_units_patrol"),
    ("连续失败", "stall|consecutive_fail"),
)

# 停摆行文精确判据(#282 审查 MF1, 2026-10-22):
#   ① EXTRA 任务停摆: `<task> 停摆(超 Nh 未运行)`(schedule_monitor.sh:1397)
#      → 按行首任务名合成独立键族 `stall|extra_stale|<task>`(每个任务各发各的);
#   ② staticdata 心跳停摆: 行内**同时**有 staticdata 与「停摆」(schedule_monitor.sh:1743)
#      → 只认这份自身行文, 不再吃泛化「停摆」(否则 EXTRA 行会被抢判)。
# ⚠️ #282 审查 R2 建议(2026-10-22): 任务名由 `[A-Za-z0-9_.\-]+` 放宽为 `\S+`, 阈值放宽为
#   `\S+` —— 新 EXTRA 任务名(含中文/冒号/@ 等)或行文微调(超 4.5h / 多空格)不再静默降级
#   进普通批次。任务名仍原样取用 ⇒ 与 schedule_monitor 的 `{task}|extra_stale` 状态键一致。
_EXTRA_STALL_RE = re.compile(r"^(?P<task>\S+)\s+停摆\(\s*超\s*\S+\s+未运行\s*\)")
_STATICDATA_STALL_RE = re.compile(r"staticdata.*停摆")


def is_stall_key(key) -> bool:
    """dedup key 是否停摆级(精确登记表 + monitor 批次行合成键 `stall|...`)。

    不做前缀泛猜(防把普通 deploy_* 误升);唯一例外是 stall_line_key() 自己合成的
    `stall|...` 键 —— 它只可能由停摆行产生, 前缀即身份。
    """
    _k = str(key or "")
    return _k in STALL_KEYS or _k.startswith("stall|")


def stall_dedup_window(caller_window=None) -> int:
    """停摆通道的实际去重窗(秒)。

    - 调用方**显式传 0** = 「本通道由脚本自管闸门, 新集合/新连续段立即报」(现网
      `check_failed_units.py:51`、`d1_sync_state.py` 均如此, 注释写明留 6h 窗会吞掉新增立即报)
      ⇒ **原样保留 0**。降噪不得吞真故障判别维度(否则「新失败集合」会被 2h 窗静默)。
    - 非零窗取 max(调用方窗, STALL_DEDUP_WINDOW): 保住「同键 1 条/2h」下限, 但不缩短
      调用方更宽的窗(deploy_consecutive_fail 现网 6h 保持 6h, 不因本通道变密)。
    - 未传窗(None = 进程内直调)按停摆通道默认 2h。
    """
    if caller_window is None:
        return STALL_DEDUP_WINDOW
    try:
        _w = int(caller_window)
    except (TypeError, ValueError):
        return STALL_DEDUP_WINDOW
    if _w <= 0:
        return 0
    return max(_w, STALL_DEDUP_WINDOW)


def _strip_severe(line) -> str:
    _t = str(line or "")
    return _t[len("SEVERE: "):] if _t.startswith("SEVERE: ") else _t


def stall_line_key(line):
    """批次行 → 停摆级去重键; 非停摆级返回 None。

    批次行没有 dedup key, 只能按行文特征判定; 命中后给稳定键(sha1 前 12 位),
    **同一行文每轮得到同一键** ⇒ 2h 去重成立, 不会每轮重复外发。
    """
    _t = _strip_severe(line)
    # ① EXTRA 任务停摆(独立键族, 键内含任务名 ⇒ 去重逐任务独立 + 正文可回查任务状态)
    _m = _EXTRA_STALL_RE.match(_t)
    if _m:
        return f"stall|extra_stale|{_m.group('task')}"
    # ② staticdata 心跳停摆(只认自身行文)
    if _STATICDATA_STALL_RE.search(_t):
        return "staticdata_backup_stale"
    for _marker, _canon in STALL_LINE_MARKERS:
        if _marker in _t:
            if _canon in STALL_KEYS:
                return _canon
            _h = hashlib.sha1(re.sub(r"\d+", "#", _t).encode("utf-8")).hexdigest()[:12]
            return f"{_canon}|{_h}"
    return None


def is_stall_line(line) -> bool:
    return stall_line_key(line) is not None


def stall_state_key(line) -> str | None:
    """批次停摆行 → schedule_monitor 的 alert_state 键(仅用于「直发失败回滚本轮落签」)。

    EXTRA 任务停摆的 state 键是 `{task}|extra_stale`(schedule_monitor.sh:1404 写入),
    与去重合成键 `stall|extra_stale|{task}` 不同 —— 回滚必须落回前者, 否则回滚写不进去。
    其余键(schedule_monitor 只管 staticdata 状态)只认 staticdata_backup_stale。
    """
    _k = stall_line_key(line)
    if not _k:
        return None
    if _k.startswith("stall|extra_stale|"):
        return _k[len("stall|extra_stale|"):] + "|extra_stale"
    if _k == "staticdata_backup_stale":
        return "staticdata_backup_stale"
    return None


def stall_canonical_key(key, subject=None) -> str | None:
    """统一判定: dedup key 命中登记表, 或主题命中停摆族(无 key 的旧调用路径)。"""
    _k = str(key or "")
    if _k in STALL_KEYS or _k.startswith("stall|"):
        return _k
    # ⚠️ #282 审查 MF2(2026-10-22): 升级提醒(`active_escalate|...`)必须走自己的键族与去重窗,
    #   绝不能被下面的 subject 兜底改写成「被升级故障」的停摆键 —— 否则
    #   【持续故障升级】staticdata_backup 异步备份停摆 会被写成 staticdata_backup_fail,
    #   与真实 R4 告警共用 86400s 窗 ⇒ 满 24h 升级提醒永久发不出(= 本次改动要根治的病)。
    if _k.startswith("active_escalate|"):
        return None
    _s = str(subject or "")
    if STALL_ESCALATE_SUBJECT_MARK in _s:
        return None
    if "staticdata" in _s and ("备份失败" in _s or "备份停摆" in _s or "未追平" in _s):
        return "staticdata_backup_fail"
    if "deploy 连续失败" in _s or "deploy连续失败" in _s:
        return "deploy_consecutive_fail"
    if "D1 同步连续失败" in _s:
        return "d1_sync_fail"
    return None


STALL_IMPACT = {
    "deploy_consecutive_fail": "整条发布链停摆: R2 上传/static-site/数据备份全部未更新",
    "deploy_r2_upload_fail": "deploy 主链 R2 上传失败: 线上静态站仍读旧产物",
    "deploy_purge_low_freq_fail": "CDN 低频资源未 purge: 线上可能长期读旧缓存",
    "staticdata_backup_fail": "staticdata 灾备第 2 层仓库未追平",
    "staticdata_backup_trigger_fail": "staticdata 异步备份本轮未启动",
    "staticdata_backup_stale": "staticdata 备份心跳超 36h: 灾备副本已停止更新",
    "r2_upload_trigger_fail": "统一 R2 上传停摆: 新数据未进入线上存储",
    "d1_sync_fail": "Cloudflare D1 数据未更新: 对外查询读旧数据",
    "failed_units_patrol": "云上 systemd unit 持续 failed(服务/定时链可能已死)",
    "cloud_unit_patrol_drift": "云上 unit 清单漂移: 预期服务缺失/多出, 巡检基线失真",
}


def _read_json(path):
    try:
        _obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return _obj if isinstance(_obj, dict) else {}
    except Exception:  # noqa: BLE001 - 状态缺失/损坏都当「未知」, 绝不影响告警主路径
        return {}


def stall_context(key, repo=None, now=None) -> dict:
    """停摆告警正文三字段: 首次发生时间 / 连续失败次数 / 影响产物。

    取值优先级: 各生产方状态文件 > alert_state[key] > 「未知」。
    ⚠️ 「未知」是**显式诚实标注**(报告 §7.3 要求「拿不到就写未知」), 不是占位符:
       · deploy 连续失败状态文件(deploy_fail_tracker.py)只记 last_fail_at/consecutive_fail,
         没有 first_fail_at; 该文件不在本次改动允许范围 ⇒ 首次发生时间只能写「未知」
         (代码注释说明, 不臆造)。
       · R2 上传触发器无持久状态 ⇒ 连续次数写「未知」。
    """
    _now = now or datetime.now()
    _repo = Path(repo or os.environ.get("REPO") or Path(__file__).absolute().parent.parent)
    _canon = stall_canonical_key(key) or str(key or "")
    _ctx = {"key": _canon, "first_seen": "未知", "consecutive": "未知",
            "impact": STALL_IMPACT.get(_canon, "未知(该键无状态文件, 见告警正文)")}
    # EXTRA 任务停摆(合成键 `stall|extra_stale|<task>`): 正文必须按任务名说清受影响产物,
    # 状态回查 schedule_monitor 写的 `{task}|extra_stale` —— 修复前两者都不认, 正文会
    # 张冠李戴成「staticdata 备份心跳超 36h」(审查 MF1)。
    _state_key = _canon
    if _canon.startswith("stall|extra_stale|"):
        _task = _canon[len("stall|extra_stale|"):]
        _state_key = f"{_task}|extra_stale"
        _ctx["impact"] = f"{_task} 生成器停摆(定时器/脚本可能被删或崩溃): 该任务产物停止更新"
    # 通用兜底: monitor 自己维护的 alert_state(所有 active 告警都有 first_seen)
    _st = _read_json(_repo / "data" / "alert_state.json").get(_state_key)
    if isinstance(_st, dict):
        _ctx["first_seen"] = str(_st.get("first_seen") or "未知")
        if _st.get("consecutive_count") not in (None, ""):
            _ctx["consecutive"] = int(_st["consecutive_count"])
        _ctx["suppress_count"] = int(_st.get("suppress_count") or 0)
    # 各生产方状态文件补充
    if _canon.startswith("deploy_"):
        _d = _read_json(_repo / "data" / "deploy_fail_state.json")
        if _d.get("consecutive_fail") is not None:
            _ctx["consecutive"] = int(_d["consecutive_fail"])
        _ctx["last_fail_at"] = str(_d.get("last_fail_at") or "未知")
        _ctx["impact"] = STALL_IMPACT.get(_canon, _ctx["impact"])
    elif _canon.startswith("staticdata_"):
        _d = _read_json(_repo / "data" / "staticdata_backup_fail_state.json")
        if _d.get("first_fail_date"):
            _ctx["first_seen"] = str(_d["first_fail_date"])
        if _d.get("consecutive_days") is not None:
            _ctx["consecutive"] = f"{int(_d['consecutive_days'])} 天"
        _hb = _read_json(_repo / "data" / "staticdata_backup_heartbeat.json")
        if _hb.get("ts"):
            _ctx["last_backup_ok"] = str(_hb["ts"])
    elif _canon == "d1_sync_fail":
        _dir = _repo / "data" / "d1_sync_state"
        _firsts, _maxn, _scripts = [], 0, []
        try:
            for _p in sorted(_dir.glob("*.json")):
                _d = _read_json(_p)
                if not _d:
                    continue
                _scripts.append(str(_d.get("script") or _p.stem))
                if _d.get("first_failure_at"):
                    _firsts.append(str(_d["first_failure_at"]))
                _maxn = max(_maxn, int(_d.get("consecutive_failures") or 0))
        except Exception:  # noqa: BLE001
            pass
        if _firsts:
            _ctx["first_seen"] = min(_firsts)
        if _maxn:
            _ctx["consecutive"] = _maxn
        if _scripts:
            _ctx["impact"] = (STALL_IMPACT["d1_sync_fail"]
                              + "；受影响同步脚本: " + ", ".join(_scripts[:6]))
    elif _canon in ("failed_units_patrol", "cloud_unit_patrol_drift"):
        _name = ("failed_units_patrol_state.json" if _canon == "failed_units_patrol"
                 else "cloud_unit_patrol_drift_state.json")
        _d = _read_json(_repo / "data" / _name)
        if _d.get("first_fail_date"):
            _ctx["first_seen"] = str(_d["first_fail_date"])
        if _d.get("consecutive_days") is not None:
            _ctx["consecutive"] = f"{int(_d['consecutive_days'])} 天"
    return _ctx


def format_stall_body(body, ctx) -> str:
    """停摆告警正文头: 三字段 + 分隔线 + 原始正文(原正文一字不减)。"""
    _c = ctx or {}
    _head = (f"<b>【停摆级告警】</b><br>"
             f"· 首次发生: {_c.get('first_seen', '未知')}<br>"
             f"· 连续失败: {_c.get('consecutive', '未知')}<br>"
             f"· 影响产物: {_c.get('impact', '未知')}")
    if _c.get("suppress_count"):
        _head += f"<br>· 本轮已抑制轮次: {_c['suppress_count']}"
    return _head + "<br><br>" + str(body or "")


# ══ 持续 active 故障升级阶梯(B, 2026-10-22) ═════════════════════════════════════
# 依据(报告 §4.3 + §5 盲区 3): nextday_gap_check|ConnectionError 自 10-13 09:30 起 active
# 9 天, 1,125 条 suppress 零再提醒; schedule_monitor.sh:371 注释写「真卡死(持续 active >6h)
# 仍响」但实现无条件静默 —— 注释与代码不符。
# 口径: active 抑制 ≠ 永久静音。首次告警后满 24h、且距上次升级提醒满 24h ⇒ 强制发一次
# 升级提醒(正文带首次时间/已持续时长/累计抑制次数); 之后每 24h 一次, 直到恢复。
ACTIVE_ESCALATE_AFTER_HOURS = 24
ACTIVE_REMIND_INTERVAL_HOURS = 24


def _dt_of(value):
    _v = str(value or "")
    if not _v:
        return None
    for _fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(_v, _fmt)
        except ValueError:
            continue
    return None


def active_escalation_judge(entry, now=None, escalate_after_hours=None,
                            remind_interval_hours=None) -> tuple:
    """active 状态是否该发升级提醒。返回 (should_send, info)。

    · 老状态无 first_alerted → 退回 first_seen → last_alerted → 视为刚发生(不升级, 不崩);
    · 持续 <24h 或距上次升级 <24h ⇒ 不发;
    · 纯函数, 时间全部可注入, 可单测。
    """
    _now = now or datetime.now()
    _after = (ACTIVE_ESCALATE_AFTER_HOURS if escalate_after_hours is None
              else float(escalate_after_hours))
    _interval = (ACTIVE_REMIND_INTERVAL_HOURS if remind_interval_hours is None
                 else float(remind_interval_hours))
    _e = entry if isinstance(entry, dict) else {}
    _first = _dt_of(_e.get("first_alerted")) or _dt_of(_e.get("first_seen")) \
        or _dt_of(_e.get("last_alerted"))
    _info = {
        "first_alerted": (_first.strftime("%Y-%m-%d %H:%M:%S") if _first else "未知"),
        "elapsed_hours": None,
        "suppress_count": int(_e.get("suppress_count") or 0),
    }
    if _first is None:
        _info["reason"] = "无首次时间(老状态), 本轮不升级"
        return False, _info
    _elapsed = (_now - _first).total_seconds() / 3600.0
    _info["elapsed_hours"] = round(_elapsed, 1)
    if _elapsed < _after:
        _info["reason"] = f"持续 {_elapsed:.1f}h < {_after:g}h"
        return False, _info
    _last_esc = _dt_of(_e.get("last_escalated"))
    if _last_esc is not None:
        _gap = (_now - _last_esc).total_seconds() / 3600.0
        if _gap < _interval:
            _info["reason"] = f"距上次升级 {_gap:.1f}h < {_interval:g}h"
            return False, _info
    _info["reason"] = f"持续 {_elapsed:.1f}h, 满足升级条件"
    return True, _info


# ══ 抑制/合并审计台账(C, 2026-10-22) ════════════════════════════════════════════
# 依据(报告 §5 盲区 10/11): alert_ledger.jsonl 只记外发, 无法回答「这条故障为什么没通知我」;
# n_absorbed 是累计值但日志文案说「本日」。
# 口径: 每次 suppress/absorb/dedup 命中写一条结构化记录(**只落本地, 永不外发**);
# 写失败只 stderr, 绝不抛异常/绝不影响告警主路径; 保留 30 天, 按日/按大小轮转。
SUPPRESSION_LEDGER_FILENAME = "suppression_ledger.jsonl"
SUPPRESSION_LEDGER_RETAIN_DAYS = 30
SUPPRESSION_LEDGER_MAX_BYTES = 8 * 1024 * 1024
SUPPRESSION_LEDGER_PRUNE_MARKER = "suppression_ledger.prune"
SUPPRESS_MECHANISMS = (
    "budget",              # A: 日预算 gate 并入摘要
    "domain_aggregate",    # B: 2h 域静默窗并入摘要
    "notice_budget",       # C: 非 critical 重复类预算/rollover
    "dedup",               # D: 通用 dedup 窗口
    "stall_dedup",         # A: 停摆通道 2h 同键去重
    "active",              # B: monitor active 持续抑制
    "recurrence",          # D: 恢复后 6h 复现抑制
    "escalation_window",   # E: 升级档抑制窗(重复升级)
    "monitor_budget",      # A: monitor 批次行级预算并入
    "deploy_budget",       # A: deploy 独立告警预算
)


def suppression_ledger_path(repo=None) -> Path:
    _repo = Path(repo or os.environ.get("REPO") or Path(__file__).absolute().parent.parent)
    return _repo / "data" / "alerts" / SUPPRESSION_LEDGER_FILENAME


def record_suppression(*, mechanism, key=None, domain=None, reason="", source=None,
                       first_seen=None, event_id=None, repo=None, now=None,
                       extra=None) -> bool:
    """写一条「被抑制/被合并」审计记录。返回 True=已写。

    失败**绝不抛出**、绝不改变调用方行为(报告要求: 台账不能影响告警主路径)。
    并发: 与会写外发台账的进程共用 data/alerts/ 目录, 本函数用独立 lock 文件串行化
    append + 轮转, 防两条 append 交错/轮转时丢行。
    """
    try:
        _now = now or datetime.now()
        _p = suppression_ledger_path(repo)
        _p.parent.mkdir(parents=True, exist_ok=True)
        _day = _now.strftime("%Y-%m-%d")
        _src = source or os.environ.get("NOTIFY_SOURCE") or "unknown"
        _rec = {
            "ts": _now.strftime("%Y-%m-%d %H:%M:%S"),
            "day": _day,
            "mechanism": str(mechanism),
            "key": str(key) if key else None,
            "fingerprint": (hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]
                            if key else None),
            "domain": domain,
            "reason": str(reason or ""),
            "source": _src,
            "first_seen": first_seen,
            "event_id": event_id,
        }
        if extra and isinstance(extra, dict):
            for _k, _v in extra.items():
                if _k not in _rec and _k != "ts":
                    _rec[_k] = _v
        import fcntl
        _lock = _p.with_name(_p.name + ".lock")
        with open(_lock, "a+") as _lf:
            fcntl.flock(_lf, fcntl.LOCK_EX)
            try:
                _maybe_prune_suppression_ledger(_p, _now)
                with open(_p, "a", encoding="utf-8") as _f:
                    fcntl.flock(_f, fcntl.LOCK_EX)
                    _f.write(json.dumps(_rec, ensure_ascii=False) + "\n")
                    fcntl.flock(_f, fcntl.LOCK_UN)
            finally:
                fcntl.flock(_lf, fcntl.LOCK_UN)
        return True
    except Exception as e:  # noqa: BLE001 - 审计台账失败绝不影响告警主路径
        print(f"[adr][suppression-ledger] 写入失败(忽略, 不影响告警): "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return False


def _maybe_prune_suppression_ledger(path: Path, now: datetime) -> None:
    """30 天保留 + 8MB 上限轮转(按日检查标记, 每天最多重写一次; 大小超标随时触发)。"""
    try:
        if not path.exists():
            return
        _marker = path.with_name(SUPPRESSION_LEDGER_PRUNE_MARKER)
        _today = now.strftime("%Y-%m-%d")
        _last = ""
        try:
            _last = _marker.read_text(encoding="utf-8").strip()
        except Exception:  # noqa: BLE001
            pass
        _too_big = path.stat().st_size > SUPPRESSION_LEDGER_MAX_BYTES
        if _last == _today and not _too_big:
            return
        _cut = now - timedelta(days=SUPPRESSION_LEDGER_RETAIN_DAYS)
        _kept = []
        for _ln in path.read_text(encoding="utf-8").splitlines():
            _ln2 = _ln.strip()
            if not _ln2:
                continue
            try:
                _ts = json.loads(_ln2).get("ts", "")
            except Exception:  # noqa: BLE001
                continue
            _dt = _dt_of(_ts)
            if _dt is None or _dt >= _cut:
                _kept.append(_ln2)
            if len(_kept) >= 200000:  # 防极端体量把内存打爆(相当于硬上限 ~60MB)
                break
        _tmp = path.with_name(path.name + ".tmp")
        _tmp.write_text("\n".join(_kept) + ("\n" if _kept else ""), encoding="utf-8")
        os.replace(_tmp, path)
        _marker.write_text(_today, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[adr][suppression-ledger] 轮转失败(忽略): {type(e).__name__}: {e}",
              file=sys.stderr)