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
# 巡检者自身存活检查的 unit 清单(只告警不改生产; 状态判定一律 systemctl show -p ActiveState, 禁 is-active)
# 收录边界(§23.3 穷举后定的原则, 非随手清单): **只收「无数据产物可反证其存活」的守护/巡检/监控类
# 调度器** —— 采集/生成/回填类 timer 停跑的后果会体现在数据上(数据陈旧 → check_data_integrity/
# check_data_gap 数据级告警兜底), 且多数已登记进 schedule_monitor 漏跑表; 而监控器/巡检器**不产出
# 数据**, 它死了没有任何数据会变旧 ⇒ 必须靠本清单直接看 timer 活性。同理不收「有自身 loud 失败通道」
# 的推送器(如 trade-brief-push, 失败时 wrapper 自己 notify --severe)。
# 清单与云上实测(2026-10-05 只读 `systemctl show`): 41 个 trade-*.timer 全为 active+enabled。
WATCHMAN_UNITS = (
    ("trade-cloud-unit-patrol.timer", "timer"),        # #191 云上 unit 漂移巡检调度器
    ("trade-check-monitor-heartbeat.timer", "timer"),  # schedule-monitor 心跳消费者(元监控)
    ("trade-schedule-monitor.timer", "timer"),         # 主监控调度器
    ("trade-self-heal.timer", "timer"),                # 自愈调度器
    ("trade-r2-consistency.timer", "timer"),           # §22 三站一致性巡检调度器
    ("trade-check-data-gap.timer", "timer"),           # 数据缺口/停更告警检测器(巡检类, 不产出数据)
    ("trade-overfit-monitor.timer", "timer"),          # 过拟合监控器(监控类, 不产出数据)
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


def consecutive_days_escalate(state_path, now, escalate_days, log_prefix=""):
    """通用「连续 N 自然日异常 → 升 critical」判定(单一事实源; R7 与 #196 共用)。

    「连续 N 天」定义: 相邻自然日各发生一次异常。中间夹一个正常日/未跑日(间隔 >1 自然日)
    即视为连续链中断, 从 1 重新计; 同日重复调用(手动重跑/重试)不重复计数。

    返回 (tier, consecutive_days, first_fail_date), tier in ("severe", "critical"):
      - 连续 < escalate_days 天 → "severe"(与历史行为一致, 单次异常照发不降噪)
      - 连续 >= escalate_days 天 → "critical"(调用侧换独立 dedup key → 不被首日 6h 窗吞 → 必达)

    状态原子落盘 state_path(原子写): {last_fail_date, consecutive_days, first_fail_date,
    last_grade_time}。故意**不**依赖外部「成功心跳」文件: 正常日在链路上根本不会调用本函数,
    间隔 >1 天即自然中断(省一个跨脚本耦合点)。

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
    _days = int(_state.get("consecutive_days") or 0)
    _first = str(_state.get("first_fail_date") or "")

    if _last == _today:
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

    实测云上 systemd 249 格式(7 个守护 unit 全部同形):
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
    _days = int(_state.get("consecutive_days") or 0)
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


def ledger_day_direct_counts(repo, day=None):
    """台账当日各类别「已直发」条数(单一事实源; 读不到=全 0=全直发 fail-open)。

    只数: ts 前缀==day 且 group=="alert" 且 tier!="digest" 的行, 按 category_of(key,subject)
    归类。坏行跳过 / 文件缺失 → 空 dict(绝不因台账问题吞告警)。
    """
    _day = day or datetime.now().strftime("%Y-%m-%d")
    counts = {}
    if repo is None:
        return counts
    try:
        _p = Path(repo) / "data" / "alerts" / "alert_ledger.jsonl"
        if not _p.exists():
            return counts
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
            if _r.get("tier") == "digest":
                continue
            _c = category_of(_r.get("key"), _r.get("subject"))
            if _c:
                counts[_c] = counts.get(_c, 0) + 1
    except Exception:  # noqa: BLE001  台账问题绝不吞告警
        return counts
    return counts


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
    加强档 task_family 第二层(默认 OFF, env ALERT_BUDGET_TASK_FAMILY=1 开启, 拍板项见 spec
    §0.3/§1.3): 同类判完后对 kept 行再按 task 分组, 超 task 预算(1/日)的行转入 absorbed。
    """
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