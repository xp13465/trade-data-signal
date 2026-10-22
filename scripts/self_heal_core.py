#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_heal_core.py - self_heal.sh 的决策核心(每任务配额 + heal 结果校验 + 连续失败升级)。

背景(只读评估报告 `/tmp/research-stability-eval.md` §4,数据截点 2026-10-22):
  - 旧版每日 3 次配额是**全局共享**(self_heal.sh 里同一个 state["count"]):某个任务
    反复失败就把全站当天的自愈额度吃光,别的任务当天再坏也没有自愈机会。
  - heal 只是「按一下重跑」,不校验是否治好;30 天可核对 19 次里只有 6 次成功
    (31.6%),audit 只记「触发了」不记「结果」。
  - 连续失败后无人知道(达上限只记 info,不发外发告警)。

本模块做三件事(**纯逻辑**:文件/命令/通知全部由调用方注入,便于打桩自测):
  1. 配额:每任务每日 3 次(独立计数)+ 全局宽松总上限 12 次/日(防总爆炸)。
     state 文件向后兼容旧格式(旧格式只有全局 count,缺 per_task/pending 不崩)。
  2. 结果校验:heal 触发时记 pending;后续轮次按「该任务日志里 heal 之后的新一次
     运行记录(退出码)+ 目标产物新鲜度」判 PASS/FAIL,结果写 audit:
     `[时间] VERIFY task=<任务> action=heal result=PASS|FAIL basis=<校验依据>`。
  3. 连续失败 ≥2 次 → 产出升级告警事件(真正调用 notify.py 的是 self_heal.sh 适配层)。

告警四元组声明(#264 件F):
  - 默认 tier:    warning
  - dedup window: 21600s(6h)
  - 聚合域:       collect(子域 self_heal_repeat_fail_<task>,按任务独立)
  - 首报策略:     该任务连续失败计数**首次达到 2** 时发一次;计数归零后再次达到 2 才再发
                 (实现:本模块只在 fail_streak == ESCALATE_AFTER_FAILS 时产出事件)。
  适配层实际参数:`--tier warning --dedup-key self_heal_repeat_fail_<task>
  --dedup-window 21600 --alert-issue 自愈连续失败:<task>`。

只读边界:本模块不直接跑任务、不直接发通知;命令内嵌非法字符/异常一律降级为 FAIL/SKIP,
不向调用方抛异常(自愈脚本本身挂掉 = 没人自愈)。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

# ── 配额/阈值(集中在此,便于机检与调参)──────────────────────────────────────
PER_TASK_DAILY_LIMIT = 3      # 每任务每日自愈次数上限(独立计数)
TOTAL_DAILY_LIMIT = 12        # 全站每日总上限(宽松值,防单日总爆炸)
ESCALATE_AFTER_FAILS = 2      # 同一任务连续 heal 校验失败达到该值 → 升级告警
VERIFY_DEADLINE_SEC = 3 * 3600  # heal 后超过该时长仍无新运行记录 → 判 FAIL(超时)
ARTIFACT_SLACK_SEC = 120      # 产物 mtime 允许比 heal 起点早 2min(文件系统秒级误差)
RUN_END_SLACK_SEC = 60        # 运行结束时间允许比 heal 起点早 1min(时点取整误差)
NOTIFY_DEDUP_WINDOW_SEC = 21600  # 告警去重窗 6h(四元组声明见模块 docstring)

# 任务 → 目标产物(存在且新鲜 = heal 生效的**第二路证据**,与运行记录退出码互证)。
# 只登记产出路径明确的 4 个任务;其余任务无稳定单产物,按「运行记录退出码」判定
# (basis 会显式写「无产物规格」,不假装校验过产物)。
ARTIFACT_SPECS = {
    "update_all": {"kind": "file", "path": "static-site/data/overview.json"},
    "intraday_snapshot": {"kind": "file", "path": "static-site/data/intraday_snapshot.json"},
    "etf_national_team": {"kind": "dir_glob", "path": "static-site/data/etf", "glob": "*.json"},
    "lab_auto": {"kind": "file", "path": "static-site/data/lab/lab_backtest.json"},
}


# ── state 读写(向后兼容旧格式)────────────────────────────────────────────────
def empty_state(today: str) -> dict:
    return {
        "date": today,
        "count": 0,
        "per_task": {},
        "pending": [],
        "healed": [],
        "skipped": [],
        "limit_notified": False,
    }


def _task_entry(raw) -> dict:
    """归一化单任务计数条目;坏字段一律按 0 处理(不许崩)。"""
    raw = raw if isinstance(raw, dict) else {}
    try:
        count = int(raw.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    try:
        streak = int(raw.get("fail_streak") or 0)
    except (TypeError, ValueError):
        streak = 0
    last_heal = raw.get("last_heal_at")
    entry = {"count": max(0, count), "fail_streak": max(0, streak),
             "last_heal_at": last_heal if isinstance(last_heal, str) else None}
    if isinstance(raw.get("last_verify"), dict):
        entry["last_verify"] = raw["last_verify"]
    return entry


def load_state(path, today: str) -> dict:
    """读 state;缺文件/坏 JSON/旧格式一律兜底,不抛异常。

    旧格式(2026-10-22 之前)只有 {"date","count","healed",...},没有 per_task/pending:
      - per_task 按 healed 列表里每任务出现次数折算(不额外赠额度);
      - pending 视为空(旧版没有待校验记录)。
    跨天:计数清零,但 pending(跨天没校验完的 heal)与 fail_streak 保留。
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}
    same_day = raw.get("date") == today
    per_task: dict[str, dict] = {}
    raw_per = raw.get("per_task")
    if isinstance(raw_per, dict):
        for task, entry in raw_per.items():
            if isinstance(task, str) and task:
                per_task[task] = _task_entry(entry)
    if not per_task:
        # 旧格式迁移:按 healed 里每个任务出现次数重建每任务计数
        healed_old = raw.get("healed")
        if isinstance(healed_old, list):
            for h in healed_old:
                if isinstance(h, dict) and isinstance(h.get("task"), str) and h["task"]:
                    per_task.setdefault(h["task"], _task_entry(None))["count"] += 1
    if not same_day:
        for entry in per_task.values():
            entry["count"] = 0
    try:
        global_count = int(raw.get("count") or 0) if same_day else 0
    except (TypeError, ValueError):
        global_count = 0
    state = empty_state(today)
    state["count"] = max(0, global_count)
    state["per_task"] = per_task
    pending = raw.get("pending")
    state["pending"] = [p for p in pending if isinstance(p, dict) and isinstance(p.get("task"), str)] \
        if isinstance(pending, list) else []
    if same_day:
        for key in ("healed", "skipped"):
            val = raw.get(key)
            state[key] = val if isinstance(val, list) else []
        state["limit_notified"] = bool(raw.get("limit_notified"))
    return state


def save_state(path, state: dict) -> None:
    """原子写(临时文件 + os.replace),坏文件不会留下半截 JSON。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_audit(path, msg: str, now: datetime) -> None:
    """append 写 audit 日志(与旧格式同:每行 `[YYYY-MM-DD HH:MM:SS] msg`)。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


# ── 配额判定 ───────────────────────────────────────────────────────────────────
def quota_decision(state: dict, task: str,
                   per_task_limit: int = PER_TASK_DAILY_LIMIT,
                   total_limit: int = TOTAL_DAILY_LIMIT) -> tuple[bool, str, dict]:
    """返回 (allowed, reason, 计数快照)。reason ∈ ok/pending_verify/per_task_limit/total_limit。"""
    snapshot = {
        "task_count": int((state.get("per_task", {}).get(task) or {}).get("count") or 0),
        "task_limit": per_task_limit,
        "total_count": int(state.get("count") or 0),
        "total_limit": total_limit,
    }
    # 同一任务已有待校验的 heal → 先不重复触发(否则 15min 一轮把配额空烧在同一个故障上)
    for p in state.get("pending") or []:
        if isinstance(p, dict) and p.get("task") == task:
            return False, "pending_verify", snapshot
    if snapshot["task_count"] >= per_task_limit:
        return False, "per_task_limit", snapshot
    if snapshot["total_count"] >= total_limit:
        return False, "total_limit", snapshot
    return True, "ok", snapshot


# ── heal 结果校验 ─────────────────────────────────────────────────────────────
def _parse_dt(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _fmt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt, datetime) else "?"


def probe_artifact(repo, task: str, heal_at: datetime,
                   slack_sec: int = ARTIFACT_SLACK_SEC) -> tuple[bool, str]:
    """检查任务目标产物是否存在且新鲜(mtime ≥ heal 起点 - slack)。

    返回 (ok, 依据文本)。无产物规格的任务返回 (True, "无产物规格(按运行记录判定)")。
    """
    spec = ARTIFACT_SPECS.get(task)
    if not spec:
        return True, "无产物规格(按运行记录判定)"
    root = Path(repo)
    path = root / spec["path"]
    try:
        if spec["kind"] == "dir_glob":
            if not path.is_dir():
                return False, f"产物目录缺失 {spec['path']}"
            files = [f for f in path.glob(spec.get("glob", "*")) if f.is_file()]
            if not files:
                return False, f"产物目录无匹配 {spec['path']}/{spec.get('glob', '*')}"
            newest = max(files, key=lambda f: f.stat().st_mtime)
            mtime = newest.stat().st_mtime
            label = str(newest.relative_to(root))
        else:
            if not path.is_file():
                return False, f"产物缺失 {spec['path']}"
            mtime = path.stat().st_mtime
            label = spec["path"]
    except OSError as e:
        return False, f"产物不可读 {spec['path']}: {e}"
    mtime_dt = datetime.fromtimestamp(mtime)
    if mtime >= heal_at.timestamp() - slack_sec:
        return True, f"产物 {label} mtime={_fmt(mtime_dt)}(新鲜)"
    return False, f"产物陈旧 {label} mtime={_fmt(mtime_dt)} < heal 起点 {_fmt(heal_at)}"


def verify_pending(state: dict, lookup_run, artifact_probe, now: datetime,
                   deadline_sec: int = VERIFY_DEADLINE_SEC) -> list[dict]:
    """校验 state["pending"] 里的 heal 结果,返回事件列表(除 state 外不产生副作用)。

    PASS: heal 之后该任务有新运行记录且退出码 0,并且(有产物规格时)产物新鲜。
    FAIL: 新运行记录退出码 != 0 / 产物缺失或陈旧 / 超过 deadline 仍无新运行记录。
    证据不足(还没跑完)的 pending 原样留到下一轮。
    """
    events: list[dict] = []
    keep: list[dict] = []
    for p in state.get("pending") or []:
        task = p.get("task")
        heal_at = _parse_dt(p.get("heal_at"))
        if not task or not heal_at:
            continue  # 坏记录直接丢弃,不阻塞后续
        try:
            run = lookup_run(task) or {}
        except Exception as e:  # 查日志失败按「暂无可判证据」处理,不崩
            run = {}
            p.setdefault("lookup_error", str(e))
        end = _parse_dt(run.get("end"))
        result = None
        basis = ""
        if end and end >= heal_at - timedelta(seconds=RUN_END_SLACK_SEC):
            try:
                exit_code = int(run.get("exit") or 0)
            except (TypeError, ValueError):
                exit_code = 1
            if exit_code != 0:
                result = "FAIL"
                basis = f"重跑结束 {_fmt(end)} 退出码={exit_code}"
            else:
                ok, art_basis = artifact_probe(task, heal_at)
                if ok:
                    result = "PASS"
                    basis = f"重跑结束 {_fmt(end)} 退出码=0; {art_basis}"
                else:
                    result = "FAIL"
                    basis = f"重跑结束 {_fmt(end)} 退出码=0 但产物校验未过: {art_basis}"
        elif (now - heal_at).total_seconds() > deadline_sec:
            result = "FAIL"
            age_h = (now - heal_at).total_seconds() / 3600
            basis = (f"heal 后 {age_h:.1f}h 无新运行记录"
                     f"(超过判定时限 {deadline_sec // 3600}h)")
        else:
            keep.append(p)
            continue
        entry = state.setdefault("per_task", {}).setdefault(task, _task_entry(None))
        if result == "PASS":
            entry["fail_streak"] = 0
        else:
            entry["fail_streak"] = int(entry.get("fail_streak") or 0) + 1
        entry["last_verify"] = {
            "at": now.isoformat(timespec="seconds"),
            "result": result,
            "basis": basis,
        }
        events.append({
            "task": task,
            "result": result,
            "basis": basis,
            "heal_at": p.get("heal_at"),
            "fail_streak": entry["fail_streak"],
        })
    state["pending"] = keep
    return events


# ── 任务筛选(保持旧版口径,只把 IO 回调化)──────────────────────────────────
def select_candidates(stats, labels, launch_state, now: datetime,
                      stale_threshold_sec: int = 24 * 3600):
    """返回 (候选列表, 审计行列表)。

    候选 = last_exit 非 0(或 log_anomaly=true)且 last_run 在 stale 阈值内且任务不在跑。
    与旧版 self_heal.sh 的筛选口径逐条一致(SKIP_STALE / SKIP_RUNNING 的 audit 文本保留)。
    """
    candidates: list[dict] = []
    audit_lines: list[str] = []
    for s in stats or []:
        if not isinstance(s, dict):
            continue
        task = s.get("task")
        exit_code = s.get("last_exit")
        last_run_str = s.get("last_run")
        log_anomaly = bool(s.get("log_anomaly", False))
        if (exit_code is None or exit_code == 0) and not log_anomaly:
            continue
        if not last_run_str:
            continue
        try:
            last_run_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        age_sec = (now - last_run_dt).total_seconds()
        if age_sec > stale_threshold_sec:
            audit_lines.append(
                f"SKIP_STALE {task} last_run={last_run_str} "
                f"age={int(age_sec // 3600)}h last_exit={exit_code}")
            continue
        label = (labels or {}).get(task)
        try:
            st = launch_state(label)
        except Exception:
            st = None
        if st and "running" in st:
            audit_lines.append(f"SKIP_RUNNING {task} state={st} last_exit={exit_code}")
            continue
        candidates.append({
            "task": task, "exit": exit_code, "last_run": last_run_str,
            "state": st, "log_anomaly": log_anomaly,
        })
    return candidates, audit_lines


# ── 一轮完整决策 ─────────────────────────────────────────────────────────────
def run_cycle(*, repo, stats, state_path, audit_path, now: datetime,
              heal_actions: dict, labels: dict, launch_state, trigger,
              notify_info, notify_escalate,
              lookup_run=None, artifact_probe=None,
              per_task_limit: int = PER_TASK_DAILY_LIMIT,
              total_limit: int = TOTAL_DAILY_LIMIT,
              verify_deadline_sec: int = VERIFY_DEADLINE_SEC,
              stale_threshold_sec: int = 24 * 3600,
              intraday_skip=None) -> dict:
    """跑一轮:校验上一轮 heal → 升级连续失败 → 按每任务配额触发新 heal。

    注入回调:
      trigger(task, cmd) -> (ok: bool, err: str)     后台触发重跑
      notify_info(subject, body) -> bool              达总上限的 info(只落盘,不邮件)
      notify_escalate(task, streak, basis) -> bool    连续失败升级告警
      lookup_run(task) -> {"end": iso, "exit": int}|None
      artifact_probe(task, heal_at) -> (ok, basis)
      intraday_skip(task, now) -> bool                update_all 盘中保护(旧版 §8 口径)
    """
    lookup_run = lookup_run or (lambda task: None)
    artifact_probe = artifact_probe or (lambda task, heal_at: (True, "无产物规格(按运行记录判定)"))
    intraday_skip = intraday_skip or (lambda task, now: False)
    today = now.strftime("%Y-%m-%d")
    state = load_state(state_path, today)
    summary = {"verified": [], "escalated": [], "healed": [], "skipped": [], "limit": None}

    # 1) 先校验上一轮 heal(先判定再触发,避免同一任务连烧额度)
    events = verify_pending(state, lookup_run, artifact_probe, now,
                            deadline_sec=verify_deadline_sec)
    for ev in events:
        append_audit(audit_path,
                     f"VERIFY {ev['task']} action=heal result={ev['result']} "
                     f"basis={ev['basis']}", now)
        summary["verified"].append(ev)

    # 2) 同一任务连续 heal 失败达到阈值 → 升级告警(只在计数恰为阈值时发一次)
    for ev in events:
        if ev["result"] != "FAIL" or ev["fail_streak"] != ESCALATE_AFTER_FAILS:
            continue
        try:
            sent = bool(notify_escalate(ev["task"], ev["fail_streak"], ev["basis"]))
        except Exception:
            sent = False
        append_audit(audit_path,
                     f"ESCALATE {ev['task']} action=notify result="
                     f"{'SENT' if sent else 'FAILED'} streak={ev['fail_streak']} "
                     f"basis={ev['basis']}", now)
        summary["escalated"].append({"task": ev["task"], "streak": ev["fail_streak"],
                                     "sent": sent, "basis": ev["basis"]})

    # 3) 全局总上限:达上限就不再触发新 heal(旧版「达上限只记 info 一次」保留)
    if int(state.get("count") or 0) >= total_limit:
        msg = (f"已达全站每日总上限 {total_limit} 次停止自愈。今日 healed: "
               f"{json.dumps(state.get('healed', []), ensure_ascii=False)}")
        append_audit(audit_path, f"LIMIT 达总上限 count={state['count']}: {msg}", now)
        if not state.get("limit_notified"):
            try:
                notify_info("自愈脚本达到每日上限停止", msg)
            except Exception:
                pass
            state["limit_notified"] = True
        summary["limit"] = "total_limit"
        save_state(state_path, state)
        return summary

    # 4) 选失败任务(旧口径)
    candidates, skip_lines = select_candidates(
        stats, labels, launch_state, now, stale_threshold_sec=stale_threshold_sec)
    for line in skip_lines:
        append_audit(audit_path, line, now)
    if not candidates:
        save_state(state_path, state)
        return summary

    # 5) 逐个按配额触发
    for cand in candidates:
        task = cand["task"]
        allowed, reason, snap = quota_decision(
            state, task, per_task_limit=per_task_limit, total_limit=total_limit)
        if not allowed:
            append_audit(
                audit_path,
                f"SKIP_QUOTA {task} reason={reason} "
                f"task_count={snap['task_count']}/{snap['task_limit']} "
                f"total_count={snap['total_count']}/{snap['total_limit']} "
                f"last_exit={cand['exit']} last_run={cand['last_run']}", now)
            summary["skipped"].append({"task": task, "reason": reason})
            if reason == "total_limit" and not state.get("limit_notified"):
                # 只有总上限触发 info;每任务上限是正常保护(每 15min 会重复出现),不打扰
                msg = (f"全站每日总上限 {total_limit} 次已用尽,剩余任务本轮跳过。"
                       f"已 heal: {json.dumps(state.get('healed', []), ensure_ascii=False)}")
                try:
                    notify_info("自愈脚本达到每日上限停止", msg)
                except Exception:
                    pass
                state["limit_notified"] = True
                summary["limit"] = "total_limit"
            continue
        cmd = (heal_actions or {}).get(task)
        if not cmd:
            continue
        if intraday_skip(task, now):
            append_audit(audit_path,
                         f"SKIP_INTRADAY {task} reason=intraday_skip "
                         f"now={now.strftime('%H:%M')} §8 盘中不跑全量,收盘后自愈 "
                         f"last_exit={cand['exit']} last_run={cand['last_run']} "
                         f"log_anomaly={cand['log_anomaly']}", now)
            state.setdefault("skipped", []).append({
                "task": task, "time": now.strftime("%H:%M:%S"),
                "reason": "intraday_skip",
                "last_exit": cand["exit"], "last_run": cand["last_run"],
                "log_anomaly": cand["log_anomaly"],
            })
            summary["skipped"].append({"task": task, "reason": "intraday_skip"})
            continue
        try:
            ok, err = trigger(task, list(cmd))
        except Exception as e:
            ok, err = False, str(e)
        if not ok:
            append_audit(audit_path, f"FAIL {task} 触发失败: {err}", now)
            summary["skipped"].append({"task": task, "reason": "trigger_failed"})
            continue
        state["count"] = int(state.get("count") or 0) + 1
        entry = state.setdefault("per_task", {}).setdefault(task, _task_entry(None))
        entry["count"] = int(entry.get("count") or 0) + 1
        entry["last_heal_at"] = now.isoformat(timespec="seconds")
        state.setdefault("pending", []).append({
            "task": task,
            "heal_at": now.isoformat(timespec="seconds"),
            "reason": "log_anomaly" if (cand["log_anomaly"] and
                                        (cand["exit"] is None or cand["exit"] == 0))
                      else f"exit={cand['exit']}",
            "last_exit": cand["exit"],
            "last_run": cand["last_run"],
        })
        state.setdefault("healed", []).append({
            "task": task, "time": now.strftime("%H:%M:%S"),
            "exit": cand["exit"], "last_run": cand["last_run"],
            "log_anomaly": cand["log_anomaly"], "result": "PENDING",
        })
        reason_txt = ("log_anomaly" if (cand["log_anomaly"] and
                                        (cand["exit"] is None or cand["exit"] == 0))
                      else f"exit={cand['exit']}")
        append_audit(
            audit_path,
            f"HEAL {task} action=rerun result=PENDING reason={reason_txt} "
            f"last_exit={cand['exit']} last_run={cand['last_run']} "
            f"log_anomaly={cand['log_anomaly']} state={cand['state']} "
            f"-> 触发 {' '.join(cmd)} (log={task}_heal.log) "
            f"task_count={entry['count']}/{per_task_limit}", now)
        summary["healed"].append(task)

    save_state(state_path, state)
    return summary