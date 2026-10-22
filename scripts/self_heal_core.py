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
  2. 结果校验:heal 触发时记 pending;后续轮次按「heal 之后**开始**的那次运行记录
     (退出码,来自 <task>_heal.log 与 launchd 任务日志的合并视图)+ 目标产物新鲜度」
     判 PASS/FAIL,结果写 audit:
     `[时间] VERIFY task=<任务> action=heal result=PASS|FAIL basis=<校验依据>`。
     重跑仍在进行(有开始无结束)→ 保持 pending 不判 FAIL;长跑超过 6h 才判卡死。
  3. 连续失败 ≥2 次 → 产出升级告警事件(真正调用 notify.py 的是 self_heal.sh 适配层)。

告警四元组声明(#264 件F):
  - 默认 tier:    warning
  - dedup window: 21600s(6h)(由 notify.py 的 --dedup-window 执行,发送成功才占窗)
  - 聚合域:       collect(子域 self_heal_repeat_fail_<task>,按任务独立)
  - 首报策略:     该任务连续失败计数达到 ≥ ESCALATE_AFTER_FAILS 即尝试发送,靠 6h 去重窗
                 压成「每 6h 最多一条」;发送失败记 escalate_pending,下一轮补发(仍受 6h 窗约束)。
                 连败计数在「任务自身恢复」或「heal 校验 PASS」时归零,归零后新事故重新计数。
  适配层实际参数:`--tier warning --dedup-key self_heal_repeat_fail_<task>
  --dedup-window 21600 --from-prefix [告警]`(warning 级不写 data/alerts/latest.md,
  那是 critical 专属;值班入口以邮件/飞书为准)。

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
ARTIFACT_SLACK_SEC = 60       # 产物 mtime 允许比 heal 起点早 60s(文件系统时间戳精度)
RUN_START_SLACK_SEC = 5       # 只认「开始时间 ≥ heal 起点 - 5s」的运行(同机时钟,几乎零误差)
RUN_INFLIGHT_MAX_SEC = 6 * 3600  # 重跑进行中超过 6h 仍未结束 → 判 FAIL(疑似卡死)
_RECENT_RUNS = 20             # 日志证据里保留的最近运行条数(双源合并后,判据只需 heal 后第一条)
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
        "escalate_pending": {},
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
    跨天:计数清零,但 pending(跨天没校验完的 heal)/fail_streak/escalate_pending
    (上轮发送失败待补发的升级告警)保留 —— 告警丢失比多试一次更糟。
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
    esc = raw.get("escalate_pending")
    if isinstance(esc, dict):
        for task, rec in esc.items():
            if isinstance(task, str) and task and isinstance(rec, dict):
                state["escalate_pending"][task] = rec
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


def lookup_run_from_logs(task: str, spec: dict, log_dir, parser=None):
    """合并「heal 重跑日志」与「定时任务日志」,给出该任务最近一次运行的证据。

    为什么必须双源(M1,审查实测):heal 重跑是 `nohup ... >> data/logs/<task>_heal.log 2>&1`,
    只写 <task>_heal.log;**launchd/systemd 的任务日志只有定时运行**。只读后者 ⇒ heal 成功
    也判「heal 后无新运行记录」= 假 FAIL(update_all/backfill_evening/rzhb_backfill/lab_auto
    每次必假 FAIL;高频任务又会被下一次定时跑顶包成假 PASS)。
    任务脚本自身的 `tee` per-run 日志(<task>_YYYYMMDD_HHMM.log)不再单读:开始/结束行会同时
    进 stdout(→ heal.log)与 per-run 日志,heal.log 已覆盖,少读一份不丢证据。

    解析复用 gen_schedule_stats 的 parse_standard/parse_etf_nt(不另写第二份日志解析)。
    `parser`=gen_schedule_stats 模块(调用方注入,便于测试与避免循环导入);缺省按名字导入。

    返回 {"start","end","exit","source","pending_start","runs"} 或 None:
      - start/end/exit = end 最大的那次已结束运行(来自 heal.log 或定时任务日志);
      - pending_start  = 有开始无结束的最新一次(进行中),由 verify_pending 判「保持 pending」;
      - runs           = 最近 _RECENT_RUNS 条已结束运行(时间升序,带 source)。给 verify_pending
                         用「heal 之后**开始**的第一条运行」当判据 —— 只看 end 最大者会让
                         「下一次定时跑」顶包成本次 heal 的假 PASS(审查 §2 已点出)。
    """
    if parser is None:
        import gen_schedule_stats as parser  # noqa: F401  (调用方通常在 scripts/ 下)
    log_dir = Path(log_dir)
    best = None      # (end, start, exit, 日志名)
    pending = None   # (pending_start, 日志名)
    runs = []        # [(start, end, exit, 日志名)]
    seen = set()
    for log_path in (log_dir / f"{task}_heal.log", log_dir / spec["log"]):
        try:
            if spec.get("mode") == "etf_nt":
                pairs, pend = parser.parse_etf_nt(log_path)
            else:
                pairs, pend = parser.parse_standard(log_path, spec["script"])
        except Exception:
            continue
        for _start, _end, _code, _dur in pairs:
            key = (_start, _end, _code)
            if key not in seen:   # 同一运行可能两边都有(定时跑也会 tee 进 stdout 之外的日志)
                seen.add(key)
                runs.append((_start, _end, _code, log_path.name))
            if best is None or _end > best[0]:
                best = (_end, _start, _code, log_path.name)
        if pend is not None and (pending is None or pend > pending[0]):
            pending = (pend, log_path.name)
    if best is None and pending is None:
        return None
    out = {"source": best[3] if best else pending[1]}
    if best is not None:
        out["start"] = best[1].isoformat(timespec="seconds")
        out["end"] = best[0].isoformat(timespec="seconds")
        out["exit"] = best[2]
    if pending is not None:
        out["pending_start"] = pending[0].isoformat(timespec="seconds")
    runs.sort(key=lambda r: r[0])
    out["runs"] = [{"start": r[0].isoformat(timespec="seconds"),
                    "end": r[1].isoformat(timespec="seconds"),
                    "exit": r[2], "source": r[3]}
                   for r in runs[-_RECENT_RUNS:]]
    return out


def _run_fields(run) -> tuple:
    """从 lookup_run 返回值里取 (start, end, pending_start, exit)。

    兼容只给 {"end","exit"} 的注入型调用(老测试/其他调用方):缺 start/pending_start 时
    由 verify_pending 退回「按 end 判定」的宽松口径(见 _run_started_after_heal)。
    """
    run = run if isinstance(run, dict) else {}
    return (_parse_dt(run.get("start")), _parse_dt(run.get("end")),
            _parse_dt(run.get("pending_start")), run.get("exit"))


def _run_started_after_heal(start, end, pending_start, heal_at: datetime,
                            slack_sec: int = RUN_START_SLACK_SEC) -> bool:
    """这条运行是不是「本次 heal 触发的重跑」——判据=运行**开始时间** ≥ heal 起点。

    M5:旧口径只看 end(还带 60s 容差),heal 前 60s 内跑完的旧运行会被当成本次重跑,
    导致「旧运行失败 → 判新 heal FAIL」的错误归因。开始时间没有歧义:heal 触发时
    这次运行还没开始。只有调用方没给 start/pending_start(注入型)时,才退回 end 判据。
    """
    ref = start or pending_start or end
    if ref is None:
        return False
    return ref >= heal_at - timedelta(seconds=slack_sec)


def verify_pending(state: dict, lookup_run, artifact_probe, now: datetime,
                   deadline_sec: int = VERIFY_DEADLINE_SEC,
                   inflight_max_sec: int = RUN_INFLIGHT_MAX_SEC) -> list[dict]:
    """校验 state["pending"] 里的 heal 结果,返回事件列表(除 state 外不产生副作用)。

    PASS: heal 之后该任务有新运行记录(开始时间晚于 heal 起点)且退出码 0,
          并且(有产物规格时)产物新鲜。
    FAIL: 该次重跑退出码 != 0 / 产物缺失或陈旧 / 超过 deadline 仍无新运行记录 /
          重跑进行中超过 inflight_max_sec(疑似卡死)。
    重跑仍在进行(有 start 无 end,且 start 晚于 heal 起点)→ **不判 FAIL**,原样留到下一轮
    (M4:长跑任务 heal 后 3h 还在跑属于正常,判 FAIL 会白烧配额并重复触发)。
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
        start, end, pend, raw_exit = _run_fields(run)
        source = run.get("source") if isinstance(run, dict) else None
        src = f"[{source}]" if source else ""
        result = None
        basis = ""

        # ①-pre 判据选集:heal 之后**开始**的第一条已结束运行 = 本次 heal 触发的重跑本身。
        # 只看「end 最大者」会被之后的定时跑顶包成假 PASS(高频任务尤甚,审查 §2);
        # 本次重跑是 heal 一触发就跑的那条,所以取「开始时间最早且 ≥ heal 起点」。
        picked = None
        for r in (run.get("runs") or []) if isinstance(run, dict) else []:
            if not isinstance(r, dict):
                continue
            r_start = _parse_dt(r.get("start"))
            r_end = _parse_dt(r.get("end"))
            if r_start is None or r_end is None:
                continue
            if r_start < heal_at - timedelta(seconds=RUN_START_SLACK_SEC):
                continue
            if picked is None or r_start < picked[0]:
                picked = (r_start, r)
        if picked is not None:
            start, end = picked[0], _parse_dt(picked[1].get("end"))
            raw_exit = picked[1].get("exit")
            source = picked[1].get("source") or source
            src = f"[{source}]" if source else ""

        # ① 进行中:开始晚于最后一次结束 → 还在跑,不判死
        inflight = None
        if pend is not None and (end is None or pend > end):
            if pend >= heal_at - timedelta(seconds=RUN_START_SLACK_SEC):
                inflight = pend
        if inflight is not None:
            running_sec = (now - inflight).total_seconds()
            if running_sec > inflight_max_sec:
                result = "FAIL"
                basis = (f"重跑{src} {_fmt(inflight)} 开始后 {running_sec / 3600:.1f}h "
                         f"仍未结束(超过上限 {inflight_max_sec // 3600}h,疑似卡死)")
            else:
                keep.append(p)
                continue

        # ② 已有结束后运行记录:必须是「本次 heal 之后开始」的那一次
        if result is None and end is not None and _run_started_after_heal(
                start, end, pend, heal_at):
            try:
                exit_code = int(raw_exit or 0)
            except (TypeError, ValueError):
                exit_code = 1
            if exit_code != 0:
                result = "FAIL"
                basis = f"重跑{src} 结束 {_fmt(end)} 退出码={exit_code}"
            else:
                ok, art_basis = artifact_probe(task, heal_at)
                if ok:
                    result = "PASS"
                    basis = f"重跑{src} 结束 {_fmt(end)} 退出码=0; {art_basis}"
                else:
                    result = "FAIL"
                    basis = f"重跑{src} 结束 {_fmt(end)} 退出码=0 但产物校验未过: {art_basis}"
        elif result is None and (now - heal_at).total_seconds() > deadline_sec:
            result = "FAIL"
            age_h = (now - heal_at).total_seconds() / 3600
            stale_txt = ""
            if end is not None:
                stale_txt = (f";日志里最近一次运行 {_fmt(start or end)}→{_fmt(end)} "
                             f"开始于 heal 之前,不是本次重跑")
            basis = (f"heal 后 {age_h:.1f}h 无新运行记录"
                     f"(超过判定时限 {deadline_sec // 3600}h){stale_txt}")
        elif result is None:
            # 证据还没到(未超时限)→ 留到下轮。注意这里必须显式 `result is None`:
            # 进行中判卡死(① 分支)已经把 result 置成 FAIL,若写成裸 else 会把结论吞掉。
            keep.append(p)
            continue
        entry = state.setdefault("per_task", {}).setdefault(task, _task_entry(None))
        if result == "PASS":
            entry["fail_streak"] = 0
            (state.get("escalate_pending") or {}).pop(task, None)
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


def reset_healthy_streaks(state: dict, stats, now: datetime,
                          skip_tasks=None) -> list[str]:
    """任务自己恢复了(不是 heal 治好的)→ 连败计数清零 + 清掉待补发告警。

    M2 根因:fail_streak 只在 heal 校验 PASS 时归零。任务若靠下一次定时跑自愈(很常见),
    计数就永远停在 2/3/4 —— 该任务这辈子只会告警一次,之后任何事故都不再告警。
    判据:监控数据(gen_schedule_stats 读任务自身日志)显示该任务最近一次运行成功,
    且这次成功**晚于上次 heal**(否则只是 heal 之前那次旧成功,不能算恢复)。
    `skip_tasks`=本轮校验已有新鲜结论的任务(新鲜证据优先,不被监控数据的滞后覆盖)。
    """
    skip = set(skip_tasks or ())
    by_task = {}
    for s in stats or []:
        if isinstance(s, dict) and isinstance(s.get("task"), str):
            by_task[s["task"]] = s
    reset: list[str] = []
    for task, entry in (state.get("per_task") or {}).items():
        if task in skip or not isinstance(entry, dict):
            continue
        if int(entry.get("fail_streak") or 0) <= 0:
            continue
        s = by_task.get(task)
        if not s or bool(s.get("log_anomaly")):
            continue
        if s.get("last_exit") not in (0, "0"):
            continue
        try:
            last_run = datetime.strptime(str(s.get("last_run")), "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        heal_at = _parse_dt(entry.get("last_heal_at"))
        # stats 里的 last_run 只到分钟:同一分钟内无法区分「heal 前跑完」还是「heal 后跑完」,
        # 按保守方向处理(只有严格晚于 heal 所在分钟的成功才算恢复),不拿旧成功抹掉本次失败。
        if heal_at is not None and last_run <= heal_at.replace(second=0, microsecond=0):
            continue
        entry["fail_streak"] = 0
        (state.get("escalate_pending") or {}).pop(task, None)
        reset.append(task)
    return reset


def escalation_targets(state: dict, events, threshold: int = ESCALATE_AFTER_FAILS) -> list[dict]:
    """本轮要尝试发送的升级告警:新达阈值的 FAIL 事件 + 上轮发送失败待补发的。

    M2:`fail_streak >= threshold` 而不是 `== threshold` —— 发送失败那轮如果恰好 == 阈值,
    之后 streak 继续增长条件就再不成立,一次丢就永久静默。重复发送由 notify.py 的
    6h 去重窗(--dedup-window,发送成功才占窗)压住,不会轰炸。
    """
    targets: dict[str, dict] = {}
    for ev in events or []:
        if ev.get("result") != "FAIL":
            continue
        streak = int(ev.get("fail_streak") or 0)
        if streak < threshold:
            continue
        targets[ev["task"]] = {"task": ev["task"], "streak": streak,
                               "basis": ev.get("basis", ""), "retry": False}
    for task, rec in (state.get("escalate_pending") or {}).items():
        if not isinstance(rec, dict) or task in targets:
            continue
        streak = int((state.get("per_task", {}).get(task) or {}).get("fail_streak") or 0)
        if streak <= 0:
            continue  # 已恢复/已清偿,不再补发
        targets[task] = {"task": task, "streak": streak,
                         "basis": rec.get("basis") or "", "retry": True}
    return list(targets.values())


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
              intraday_skip=None, task_running=None) -> dict:
    """跑一轮:校验上一轮 heal → 升级连续失败 → 按每任务配额触发新 heal。

    注入回调:
      trigger(task, cmd) -> (ok: bool, err: str)     后台触发重跑
      notify_info(subject, body) -> bool              达总上限的 info(只落盘,不邮件)
      notify_escalate(task, streak, basis) -> bool    连续失败升级告警
      lookup_run(task) -> {"start","end","exit","source","pending_start","runs"}|None
      artifact_probe(task, heal_at) -> (ok, basis)
      intraday_skip(task, now) -> bool                update_all 盘中保护(旧版 §8 口径)
      task_running(task) -> bool                      任务脚本进程仍在跑(M4:不重复触发)
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

    # 1.5) 任务自己恢复了(下一次定时跑成功)→ 连败计数清零(M2:否则一辈子只告警一次)
    for task in reset_healthy_streaks(
            state, stats, now, skip_tasks={ev["task"] for ev in events}):
        append_audit(audit_path,
                     f"STREAK_RESET {task} reason=task_recovered "
                     f"last_exit=0(任务自身最近一次运行成功,晚于上次 heal)", now)

    # 2) 连败达到阈值 → 升级告警;发送失败记待补发,下一轮重试
    for tgt in escalation_targets(state, events):
        task = tgt["task"]
        try:
            sent = bool(notify_escalate(task, tgt["streak"], tgt["basis"]))
        except Exception:
            sent = False
        if sent:
            (state.get("escalate_pending") or {}).pop(task, None)
        else:
            prev = (state.get("escalate_pending") or {}).get(task) or {}
            state.setdefault("escalate_pending", {})[task] = {
                "streak": tgt["streak"], "basis": tgt["basis"],
                "since": prev.get("since") or now.isoformat(timespec="seconds"),
            }
        append_audit(audit_path,
                     f"ESCALATE {task} action=notify result="
                     f"{'SENT' if sent else 'FAILED'} streak={tgt['streak']} "
                     f"retry={int(tgt['retry'])} basis={tgt['basis']}", now)
        summary["escalated"].append({"task": task, "streak": tgt["streak"],
                                     "sent": sent, "retry": tgt["retry"],
                                     "basis": tgt["basis"]})

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
        # M4:任务脚本进程仍在跑(长跑那一轮/上一次 heal 的重跑还没结束)→ 不重复触发。
        # 重复触发的坏处不只是浪费:update_all 撞锁会经 on_skip_notify.sh 发 --severe 真告警,
        # 而被锁跳过的那次没有 per-run 日志,校验层又看不到证据 → 连环假 FAIL。
        if task_running is not None:
            try:
                busy = bool(task_running(task))
            except Exception as e:
                busy = False
                append_audit(audit_path,
                             f"WARN {task} 进程检查失败(按未运行处理): {e}", now)
            if busy:
                append_audit(audit_path,
                             f"SKIP_RUNNING_PROC {task} reason=process_running "
                             f"(任务脚本进程在跑,本轮不重复触发) "
                             f"last_exit={cand['exit']} last_run={cand['last_run']}", now)
                summary["skipped"].append({"task": task, "reason": "process_running"})
                continue
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