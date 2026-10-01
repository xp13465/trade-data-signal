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

原则(§23.2 修 bug 三铁律 + §18 降噪翻车教训): 每条规则必须保留「真故障判别维度」
(连续轮、跨天追平、产物未生成、首条仍即时), 绝不因降噪静默真故障。
"""
import json
from datetime import datetime, timedelta

# ---- 常量(单一事实源, schedule_monitor.sh 引用本模块而非各自定义) ----
OVERVIEW_LAG_CONTINUOUS_THRESHOLD = 2   # R1: overview lag 连续 >=2 轮(15min/轮=30min)仍滞后才 SEVERE
MERGE_PREFIX = "merge|"                  # R2: 超时/耗时双通道同 (task,last_run) 共享去重 key 前缀
R2_CONGESTION_SUMMARY_KEY_PREFIX = "r2_pipeline_congestion|"  # R5: 日级汇总 key 前缀
R4_OK_RESULTS = ("ok", "skip_oversize")  # R4: 备份心跳里视为「备份完成/追平」的 result
R4_HEARTBEAT_OK_SPAN = timedelta(hours=36)  # R4: 兜底——心跳 ok 距今超 36h 视为已过旧(不误判追平)


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
        if _bf and _bf.get("status") in ("pending", "alerted"):
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
    except Exception:
        pass

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