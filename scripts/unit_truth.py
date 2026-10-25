#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#309 W1: systemd unit 真值读取(监控层的单一事实源)。

背景(docs/ops/monitor-fake-ok-fix-plan-20261025.md §1/§2):
  旧监控只解析任务日志文本, 结束行没写 `退出码=` 就当 0(已产出结束行 33.6% 缺该字段),
  systemd 明明记着 failed 也不读 ⇒ 「无关卡失败」的假 OK。本模块把 systemd 的权威终态
  (`Result` / `ExecMainCode` / `ExecMainStatus` / 起止时间 / InvocationID)读成纯数据结构,
  供 gen_schedule_stats(生成 40 行)与 schedule_monitor(结论行)共用, 避免两处各写一份
  (memory `repro-script-second-implementation-drift` 的同精神: 判定逻辑只留一份)。

本模块只做「读 + 纯函数映射」, 不写任何生产数据:
  - 读: `read_unit_states()` 一次 systemctl show 批量读 service + 同名 timer 的属性
    (43 service + 43 timer 共 86 个 unit 实测 0.093s, 2026-10-25 云上实测)。
  - 映射: `derive_exit_code()` / `derive_unit_state()` / `timer_health()` 全纯函数。
  - 持久化: `data/unit_exit_ledger.json` 的读写工具(单写者=schedule_monitor.sh, W5)。

⚠️ timer 属性的唯一来源(2026-10-25 独立审查 P1-1 修正):
  `NextElapseUSecRealtime` / `LastTriggerUSec` **只存在于同名 `.timer` 上**, `.service`
  没有这两个属性。因此读取层必须按 `.service` → **同名 `.timer`** 去取; 反过来,
  timer 上的 `Result` / `ExecMainStatus` **绝不**能当任务退出码(timer 的 Result 恒为
  success, 混进来会把失败的 service 洗成成功 —— 实测 `systemctl show a.service a.timer`
  的 timer 块确实带 `Result=success`)。本模块用 `SERVICE_PROPS` / `TIMER_PROPS`
  两张白名单分别合并, 物理上杜绝串味。

关键陷阱(方案 §2.1 S1 + §6.1 B14, 均有云上实测):
  1. `systemctl show <不存在的 unit>` 返回 **rc=0** 且 `LoadState=not-found` /
     `Result=success` / `ExecMainStatus=0` —— 绝不能被当成「成功 0」。
  2. 重启后 `ExecMain*` 会被清空(Result 可能仍留默认 success, start/invocation 为空),
     必须靠 ledger 补位, 不能当成功。
  3. 从未跑过的 unit(never-ran)与重启后清空(no-record)在 systemd 属性上很像:
     本模块按 `LoadState` / `Result` / `ExecMainStartTimestamp` / `InvocationID` 给出
     区分性诊断标签, 但两者都返回 `code=None`(未知), 绝不返回 0。

属性清单见 `UNIT_PROPS`;映射规则见 `derive_exit_code()` docstring。
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

# systemd 属性白名单: 一次 show 全读(--value 会有顺序/空值歧义, 用 key=value 前缀式)。
# SERVICE_PROPS 只能从 `.service` 读; TIMER_PROPS 只能从同名 `.timer` 读(见模块头 ⚠️)。
SERVICE_PROPS = (
    "LoadState",
    "Result",
    "ExecMainCode",
    "ExecMainStatus",
    "ExecMainStartTimestamp",
    "ExecMainExitTimestamp",
    "InvocationID",
    "ActiveState",
)
TIMER_PROPS = (
    "NextElapseUSecRealtime",
    "LastTriggerUSec",
)
# 请求给 systemctl 的并集(+ Id 用于按 unit 切分多 unit 输出), 顺序稳定便于调试。
UNIT_PROPS = SERVICE_PROPS + TIMER_PROPS

# 退出码合成口径(方案 §7.2 W1):
#   Result=success → 0
#   Result=exit-code → ExecMainStatus
#   Result=timeout → 124(与 coreutils timeout 同码, 便于人和脚本识别)
#   Result=signal/core-dump → 128 + ExecMainStatus(对齐 launchd 143=SIGTERM15)
SYNTH_TIMEOUT = 124
SIGNAL_BASE = 128

# 漏跑宽限: `now > NextElapseUSecRealtime + 10min` 判 missed(方案 §7.2 W1)。
MISSED_GRACE = timedelta(minutes=10)

# 运行态集合(oneshot 运行中 ActiveState=activating, 见 schedule_monitor.sh launchctl_loaded
# 的同款陷阱注释): 这些状态下 timer 的 next elapse 不能当「漏跑」。
RUNNING_STATES = ("active", "activating", "reloading")

_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_USEC_RE = re.compile(r"^\d{10,}$")

LEDGER_REL_PATH = Path("data") / "unit_exit_ledger.json"
LEDGER_VERSION = 1


# ────────────────────────────────────────────────────────────────
# 开关 / 可用性
# ────────────────────────────────────────────────────────────────
def exit_source_mode() -> str:
    """退出码口径开关: `MONITOR_EXIT_SOURCE=systemd|log`, 默认 systemd。

    log = 一键退回旧口径(只读日志, 缺退出码当 0, 不读 systemd), 用于线上发现问题时
    单行回滚(方案 §7.2 回滚第①层)。非法值按默认 systemd 处理(不静默变 log)。
    """
    raw = (os.environ.get("MONITOR_EXIT_SOURCE") or "systemd").strip().lower()
    return "log" if raw == "log" else "systemd"


def systemd_available() -> bool:
    """当前环境是否有可用的 systemd(平台 + 二进制双判, 不真跑)。"""
    if not sys.platform.startswith("linux"):
        return False
    return shutil.which("systemctl") is not None


# ────────────────────────────────────────────────────────────────
# 读取
# ────────────────────────────────────────────────────────────────
def _parse_props(stdout: str) -> dict:
    """把 `systemctl show` 的 key=value 输出解析成 dict(同 key 后者覆盖前者)。"""
    props = {}
    for line in (stdout or "").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props


def _show_cmd(unit_names) -> list:
    """构造 `systemctl show <unit...> -p a -p b ...`(多 unit 一次调用, 低耗时)。"""
    cmd = ["systemctl", "show", *unit_names]
    for p in ("Id",) + UNIT_PROPS:
        cmd.extend(["-p", p])
    return cmd


def _read_one(unit: str, timeout: float = 10) -> dict:
    """调一次 `systemctl show <unit>` 读 UNIT_PROPS; 失败返回 {} (未知, 不猜)。"""
    try:
        r = subprocess.run(_show_cmd([unit]), capture_output=True, text=True,
                           timeout=timeout)
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    return _parse_props(r.stdout)


def _parse_multi(stdout: str) -> dict:
    """解析多 unit 的 `systemctl show` 输出 → `{unit: props}`。

    实测形状(2026-10-25 云上): 每个 unit 一块, **块间空行分隔**, 块内某处必有一行
    `Id=<unit>`(位置不固定, 可能排在中部), 因此不能靠「Id 开头」切块, 只能空行切块 +
    块内取 Id。没有 Id 的残块直接丢弃(未知, 不猜)。
    """
    out, block = {}, {}

    def _flush():
        if not block:
            return
        name = block.get("Id")
        if name:
            out[name] = {k: v for k, v in block.items() if k != "Id"}
        block.clear()

    for line in (stdout or "").splitlines():
        if not line.strip():
            _flush()
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            block[k.strip()] = v.strip()
    _flush()
    return out


def _read_many(unit_names, timeout: float = 10) -> dict:
    """一次 `systemctl show` 批量读多个 unit; 失败返回 {}(调用方回退逐个读)。"""
    if not unit_names:
        return {}
    try:
        r = subprocess.run(_show_cmd(unit_names), capture_output=True, text=True,
                           timeout=timeout)
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    return _parse_multi(r.stdout)


def timer_unit_name(unit: str) -> str | None:
    """service 名 → 同名 timer 名; `.timer` 原样返回; 无后缀的按 `<unit>.timer`。"""
    if not unit:
        return None
    if unit.endswith(".timer"):
        return unit
    if unit.endswith(".service"):
        return unit[:-len(".service")] + ".timer"
    return unit + ".timer"


def _merge_unit_props(service_props: dict | None, timer_props: dict | None) -> dict:
    """按白名单合并: service 8 属性 + timer 2 属性, 绝不让 timer 的 Result 串味。"""
    out = {k: (service_props or {})[k] for k in SERVICE_PROPS
           if k in (service_props or {})}
    for k in TIMER_PROPS:
        if k in (timer_props or {}):
            out[k] = timer_props[k]
    return out


def _safe_runner(runner, unit) -> dict:
    try:
        return runner(unit) or {}
    except Exception:
        return {}


def read_unit_states(units, *, runner=None, timeout: float = 10) -> dict:
    """批量读 unit 终态 → `{unit: props}`(props 已按白名单合并 service + 同名 timer)。

    runner: 测试注入点 `runner(unit_name) -> props dict|None`(假 systemctl), 生产不传。
      注入时对每个 unit 各调两次(service 名 + 同名 timer 名), 测试用真实形状假数据。
    读失败/unit 不存在时对应值为 {}(调用方会得到 code=None/missing, 不会假成功)。
    """
    out = {}
    if runner is not None:
        for unit in units:
            svc = {} if unit.endswith(".timer") else _safe_runner(runner, unit)
            timer = _safe_runner(runner, timer_unit_name(unit))
            out[unit] = _merge_unit_props(svc, timer)
        return out

    # 生产: 86 个 unit(43 service + 43 timer)一次 show(云上实测 0.093s)。
    names = []
    for unit in units:
        for name in (unit, timer_unit_name(unit)):
            if name and name not in names:
                names.append(name)
    props = _read_many(names, timeout=timeout)
    if not props:
        # 批量失败 → 逐个读兜底(仍然只信白名单合并, 不猜成功)
        props = {n: _read_one(n, timeout=timeout) for n in names}
    for unit in units:
        svc_name = None if unit.endswith(".timer") else unit
        out[unit] = _merge_unit_props(props.get(svc_name or "", {}),
                                      props.get(timer_unit_name(unit) or "", {}))
    return out


# ────────────────────────────────────────────────────────────────
# 纯映射
# ────────────────────────────────────────────────────────────────
def parse_systemd_timestamp(value) -> datetime | None:
    """解析 systemd 墙钟属性 → naive 本地 datetime。

    兼容: "Sat 2026-10-25 16:00:01 CST" / "2026-10-25 16:00:01" / 微秒整数串。
    "n/a" / "" / None / 非法 → None(不猜时间)。
    """
    if value is None:
        return None
    v = str(value).strip()
    if not v or v in ("n/a", "N/A"):
        return None
    m = _TS_RE.search(v)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if _USEC_RE.match(v):
        try:
            return datetime.fromtimestamp(int(v) / 1_000_000)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _int_or_none(value) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def derive_exit_code(props: dict) -> tuple[int | None, str]:
    """systemd 属性 → `(退出码, 来源标签)`。**任何不确定都返回 None, 绝不返回 0**。

    来源标签:
      - "missing"        LoadState != loaded(unit 不存在/未注册; not-found 陷阱)
      - "never-ran"      unit 已加载但从未运行(属性为默认值, 无 start/invocation)
      - "no-record"      重启后 ExecMain* 被清空(Result 也为空), 需 ledger 补位
      - "systemd"        读到本次调用的权威终态
      - "unknown-result" Result 是未知非成功值且无法换算退出码(诚实标注未知)
    """
    if props.get("LoadState") != "loaded":
        return (None, "missing")

    result = (props.get("Result") or "").strip()
    start_raw = (props.get("ExecMainStartTimestamp") or "").strip()
    start = parse_systemd_timestamp(start_raw)
    invocation = (props.get("InvocationID") or "").strip()
    ec = _int_or_none(props.get("ExecMainCode"))
    es = _int_or_none(props.get("ExecMainStatus"))

    # 重启后属性清空: Result 也为空(部分 systemd 版本会把 Result 重置为空, 而非 success)
    if result == "":
        return (None, "no-record")
    # 已加载但从未运行: 默认 Result=success + 无 start + 无 invocation
    if result == "success" and start is None and not invocation:
        return (None, "never-ran")

    if result == "success":
        return (0, "systemd")
    if result == "exit-code":
        return (es if es is not None else 1, "systemd")
    if result == "timeout":
        return (SYNTH_TIMEOUT, "systemd")
    if result in ("signal", "core-dump"):
        return (SIGNAL_BASE + (es or 0), "systemd")
    # 其他非成功终态(resources / watchdog / start-limit-hit / oom-kill ...):
    # 能按 CLD_EXITED / CLD_KILLED 换算就换算, 否则明确未知。
    if ec == 1 and es is not None:
        return (es, "systemd")
    if ec in (2, 3) and es is not None:
        return (SIGNAL_BASE + es, "systemd")
    return (None, "unknown-result")


def derive_unit_state(unit: str, props: dict) -> dict:
    """单 unit 的结构化终态(供 gen_schedule_stats 生成行 / monitor 判漏跑)。"""
    code, source = derive_exit_code(props or {})
    return {
        "unit": unit,
        "load_state": (props or {}).get("LoadState"),
        "result": ((props or {}).get("Result") or "").strip() or None,
        "code": code,
        "source": source,
        "exec_code": _int_or_none((props or {}).get("ExecMainCode")),
        "exec_status": _int_or_none((props or {}).get("ExecMainStatus")),
        "start": parse_systemd_timestamp((props or {}).get("ExecMainStartTimestamp")),
        "exit": parse_systemd_timestamp((props or {}).get("ExecMainExitTimestamp")),
        "invocation_id": ((props or {}).get("InvocationID") or "").strip() or None,
        "active_state": ((props or {}).get("ActiveState") or "").strip() or None,
        "next_elapse": parse_systemd_timestamp((props or {}).get("NextElapseUSecRealtime")),
        "last_trigger": parse_systemd_timestamp((props or {}).get("LastTriggerUSec")),
    }


def timer_health(state: dict, now: datetime, grace: timedelta = MISSED_GRACE) -> str:
    """timer 漏跑判定 → "ok" / "missed" / "running" / "unknown"。

    判据: `now > next_elapse + grace` = missed。运行中(RUNNING_STATES)不算漏跑;
    无 next_elapse(字段缺失/非 timer) = unknown(不猜)。
    """
    if not state or state.get("source") == "missing" or state.get("load_state") not in ("loaded", None):
        return "unknown"
    if state.get("active_state") in RUNNING_STATES:
        return "running"
    nxt = state.get("next_elapse")
    if nxt is None:
        return "unknown"
    return "missed" if now > nxt + grace else "ok"


# ────────────────────────────────────────────────────────────────
# 持久化账本(W5): 重启后 ExecMain* 清空 → ledger + LastTriggerUSec 补位
# ────────────────────────────────────────────────────────────────
def default_ledger_path(repo) -> Path:
    return Path(repo) / LEDGER_REL_PATH


def load_ledger(path) -> dict:
    """读账本 → `{unit: entry}`。文件缺失/损坏返回 {}(核验逻辑按未知处理)。"""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, dict) and isinstance(data.get("units"), dict):
        data = data["units"]
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


@contextmanager
def _ledger_lock(path: Path):
    """对账本加排他 flock(锁文件与账本同目录, 不锁账本本体以免 rename 换 inode 失效)。"""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def save_ledger_atomic(path, records: dict, now: datetime | None = None) -> None:
    """账本原子写(tmp + fsync + os.replace + flock)。单写者 = schedule_monitor.sh。"""
    from util_atomic import atomic_write_json  # 同目录模块(scripts/ 在 sys.path)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": LEDGER_VERSION,
        "updated_at": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "units": records,
    }
    with _ledger_lock(p):
        atomic_write_json(p, payload, ensure_ascii=False, indent=2)


def update_ledger_records(states: dict, prev: dict, now: datetime) -> dict:
    """用本轮 unit 终态更新账本记录(纯函数; 只增不删已被观测到的 unit)。

    consecutive / first_bad_at 口径:
      - code != 0 且上轮同 unit 也是失败(同 result 或同 code) → consecutive + 1, 保留 first_bad_at
      - code != 0 且上轮成功/无记录 → consecutive = 1, first_bad_at = now
      - code == 0 → consecutive = 0, first_bad_at = None
    只有 source ∈ {systemd, ledger} 且 code 非 None 的记录才落账(未知不覆盖已知)。
    """
    out = {k: dict(v) for k, v in (prev or {}).items() if isinstance(v, dict)}
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    for unit, st in (states or {}).items():
        if not isinstance(st, dict):
            continue
        code = st.get("code")
        if code is None:
            continue
        if st.get("source") not in ("systemd", "ledger"):
            continue
        old = out.get(unit) or {}
        old_code = old.get("code")
        if code != 0:
            same = (old_code not in (None, 0)
                    and (old.get("result") == st.get("result") or old_code == code))
            consecutive = int(old.get("consecutive") or 0) + 1 if same else 1
            first_bad = old.get("first_bad_at") if same and old.get("first_bad_at") else stamp
        else:
            consecutive, first_bad = 0, None
        start = st.get("start")
        exit_ts = st.get("exit")
        out[unit] = {
            "unit": unit,
            "invocation_id": st.get("invocation_id"),
            "result": st.get("result"),
            "code": code,
            "start": start.strftime("%Y-%m-%d %H:%M:%S") if start else None,
            "exit": exit_ts.strftime("%Y-%m-%d %H:%M:%S") if exit_ts else None,
            "consecutive": consecutive,
            "first_bad_at": first_bad,
            "source": st.get("source"),
            "updated_at": stamp,
        }
    return out


def merge_ledger_state(state: dict, entry: dict | None) -> dict:
    """重启/清空时用账本补位(纯函数, 返回新 dict)。

    - 只补「当前无记录」的情形(source ∈ {no-record, never-ran}); `missing`(unit 真不存在)
      不补, 否则拼错 unit 名会被历史账本永久掩盖成「上次成功」。
    - 若 systemd 报了 LastTriggerUSec 且晚于账本 exit, 说明 unit 在账本之后又跑过但记录
      已被清空(重启), 仍补账本数据但标 `source="ledger-stale"`(诊断用, code 照给)。
    - 当前已有 systemd 真值时原样返回(账本不覆盖实时真值)。
    """
    st = dict(state or {})
    if st.get("source") not in ("no-record", "never-ran"):
        return st
    if not entry or not isinstance(entry, dict):
        return st
    code = entry.get("code")
    if code is None:
        return st
    st["code"] = int(code)
    st["result"] = entry.get("result")
    st["invocation_id"] = entry.get("invocation_id")
    st["start"] = parse_systemd_timestamp(entry.get("start")) or st.get("start")
    st["exit"] = parse_systemd_timestamp(entry.get("exit")) or st.get("exit")
    last_trigger = st.get("last_trigger")
    exit_ts = st.get("exit")
    stale = bool(last_trigger and exit_ts and last_trigger > exit_ts)
    st["source"] = "ledger-stale" if stale else "ledger"
    st["ledger_consecutive"] = entry.get("consecutive")
    st["ledger_first_bad_at"] = entry.get("first_bad_at")
    return st