#!/usr/bin/env python3
"""Signal-triggered launcher for Claude/Codex handoffs.

The watcher performs no model work while idle. A small JSON metadata signal
causes one fixed CLI invocation or deterministic schema check; signal names are
strictly validated so a file name cannot become shell input.

信号状态机(2026-08-26 加自动重试):
    .ready --取货--> .processing --成功--> .done
                        |
                        +--失败--> retry_count<3: 原子写回 .ready
                        |          (retry_count+1 + last_failed_at +
                        |           next_retry_after = now+RETRY_DELAY_SECONDS,
                        |           到期前主循环跳过不消费)
                        |
                        +--失败--> retry_count>=3: .failed 终态 + 飞书放弃告警
    .ready/.processing --信号名或 id 不合法--> .invalid(终态,不重试)
崩溃恢复: 启动时 recover_processing 把遗留 .processing 还原成 .ready 重跑。
心跳: main 循环每轮 touch HEARTBEAT_PATH(mtime 超 10 分钟 ≈ 僵死,供人工排查;
schedule_monitor 接入待办)。

异步化(2026-08-26, codex 审计刺): 子命令改 subprocess.Popen 后台执行——codex exec
可能跑几十分钟, 原同步 subprocess.run 期间心跳停跳 + claude-inbox 积压(实测误报
僵死一次)。现每 inbox 一个作业槽(codex/claude 各同时最多一个子进程), 主循环每轮
poll 已结束子进程按退出码走 done/failed(重试语义不变), 心跳与另一 inbox 消费不
再被阻塞。

报告有效性机检(2026-08-31, codex ref 断点修复): claude 回传信号消费前校验报告
mtime 是否 >= 信号创建时刻(signaled_at, 容差 60s)。8-26 演进版(仅存于当日起跑
进程内存, 从未提交)比较报告 mtime vs job_started(作业启动时刻), 但报告必然写于
作业消费前 → 比较恒假 → 100% 误拦真实回传(agent-inbox.log :2155 实录 3 次重试
全拦后 gave_up)。8-28 磁盘重写时机检与进程未重启并存, 线上持续误拦 5 天。现版
语义: 报告明显早于信号创建 = 信号重发而报告未重写的旧残留, 该拦(.invalid 终态);
正常回传由 codex_review_complete.py 在写完信号后 touch 报告保证时序成立。
"""

import json
import os
import tomllib
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
LOG_PATH = Path("/tmp/codex-reports/agent-inbox.log")
CODEX_INBOX = Path("/tmp/codex-reports/signals/codex-inbox")
CLAUDE_INBOX = Path("/tmp/codex-reports/signals/claude-inbox")
LOCK_PATH = Path("/tmp/codex-reports/agent-inbox.lock")
HEARTBEAT_PATH = Path(
    "/Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher.heartbeat"
)
SESSIONS_DIR = Path.home() / ".codex" / "sessions"
MAIN_SESSION_LOOKBACK_DAYS = 7
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
POLL_SECONDS = 2
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 300
RETRY_KEY = "retry_count"
NEXT_RETRY_KEY = "next_retry_after"
LAST_FAIL_KEY = "last_failed_at"
# 报告 mtime vs signaled_at 的容差: 吸收文件系统 mtime 粒度与 touch/写信号的
# 毫秒级竞态, 只拦"明显早于信号创建"(分钟级以上)的真旧残留
FRESHNESS_TOLERANCE_SECONDS = 60


def notify_claude(request_id: str) -> None:
    try:
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from notify import send_feishu

        timestamp = time.strftime("%H:%M")
        send_feishu(
            "[codex] 外部 review 回传",
            f"{timestamp} request={request_id} 报告已通过 schema 校验。\n"
            f"Claude 下次开工请消费 /tmp/codex-reports/signals/claude-inbox/{request_id}.ready",
            chat_key="agent_done",
        )
    except Exception as error:  # noqa: BLE001 - notification must not break state
        log(f"notify_error={error}")


def log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    line = f"{timestamp} {message}\n"
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line)


def acquire_lock() -> int:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(lock_fd, str(os.getpid()).encode())
        os.close(lock_fd)
        return 0
    except FileExistsError:
        try:
            pid = int(LOCK_PATH.read_text(encoding="ascii").strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError):
            LOCK_PATH.unlink(missing_ok=True)
            return acquire_lock()
        except OSError:
            return 1
        return 1


def recover_processing(inbox: Path) -> None:
    for path in inbox.glob("*.processing"):
        target = path.with_suffix("").with_suffix(".ready")
        path.replace(target)
        log(f"recovered {path.name} -> {target.name}")


def read_signal(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def transition(path: Path, state: str) -> Path:
    suffix = f".{state}"
    target = path.with_suffix(suffix)
    counter = 1
    while target.exists():
        target = path.with_suffix(f"{suffix}.{counter}")
        counter += 1
    path.replace(target)
    return target


def atomic_write_signal(path: Path, payload: dict) -> None:
    """原子写回信号文件(tmp -> rename),供失败重试场景重建 .ready。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def parse_config_model(config_path: Path | None = None) -> str | None:
    try:
        path = config_path or Path.home() / ".codex" / "config.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    model = data.get("model")
    return model if isinstance(model, str) else None


def _recent_session_files() -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []

    year_dirs = sorted(
        (path for path in SESSIONS_DIR.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    files: list[Path] = []
    for year_dir in reversed(year_dirs[:2]):
        try:
            int(year_dir.name)
        except ValueError:
            continue
        month_dirs = sorted(
            (path for path in year_dir.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )
        for month_dir in reversed(month_dirs[:2]):
            day_dirs = sorted(
                (path for path in month_dir.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
            for day_dir in reversed(day_dirs[:MAIN_SESSION_LOOKBACK_DAYS]):
                files.extend(day_dir.glob("*.jsonl"))

    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def _session_model(session_file: Path) -> tuple[str, float] | None:
    try:
        with session_file.open(encoding="utf-8") as stream:
            meta_line = next(
                line for line in stream
                if '"type":"session_meta"' in line
            )
        event = json.loads(meta_line)
    except (OSError, StopIteration, json.JSONDecodeError):
        return None

    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("cwd") != str(REPO):
        return None
    if payload.get("thread_source") != "user":
        return None

    model = payload.get("provenance", {}).get("model")
    if not isinstance(model, str) or not model:
        model = None

    return (model, session_file.stat().st_mtime) if model else None


def current_main_session_model() -> str:
    override = os.environ.get("CODEX_REVIEWER_MODEL")
    if override:
        return override

    for session_file in _recent_session_files()[:64]:
        result = _session_model(session_file)
        if result:
            return result[0]

    return parse_config_model() or "z-ai/glm-5.3-flash"


def build_command(kind: str, request_id: str) -> list[str]:
    """按通道构造子命令(纯构造不执行; codex exec 可能跑几十分钟)。"""
    if kind == "codex":
        prompt = (
            "你是 trade 仓库的 Codex 外部 reviewer。先读 AGENTS.md 和 "
            "docs/codex-collab-protocol.md，再检查 refs/codex/req 下所有 pending "
            "request。只按 request JSON 的 base..head 与 focus_areas 执行独立复核；"
            "报告必须先写 .tmp 再 rename 到 /tmp/codex-reports/<request_id>.json；"
            "每个完成项调用 python3 scripts/codex_review_complete.py <request_id> "
            "--verdict <PASS|FAIL|BLOCKED> 建立 Claude 回传信号。不要 commit/push。"
        )
        return [
            os.environ.get("CODEX_BIN", "codex"),
            "exec",
            "--cd",
            str(REPO),
            "-m",
            current_main_session_model(),
            "--add-dir",
            "/tmp/codex-reports",
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "--color",
            "never",
            prompt,
        ]
    return ["bash", str(REPO / "scripts" / "codex-review-report.sh"), request_id]


def spawn_job(kind: str, request_id: str, processing: Path, payload: dict,
              command: list[str], running: dict) -> None:
    """Popen 后台起子进程占本通道槽位; spawn 失败(OSError)立即按失败处置。"""
    log(f"exec {' '.join(command)}")
    job = {"kind": kind, "request_id": request_id, "processing": processing,
           "payload": payload, "proc": None}
    try:
        job["proc"] = subprocess.Popen(command, cwd=REPO)
    except OSError as error:
        log(f"spawn_error={error}")
        running[kind] = job
        finish_job(running, kind, -1)
        return
    running[kind] = job


def finish_job(running: dict, kind: str, exit_code: int) -> None:
    """子进程结束后按退出码处置(与原同步版语义一致): 0=.done(claude 附飞书通知);
    非 0 且未耗尽重试=原子写回 .ready 带退避元数据; 重试耗尽=.failed 终态+放弃告警。"""
    job = running.pop(kind)
    log(f"exit={exit_code}")
    processing = job["processing"]
    payload = job["payload"]
    request_id = job["request_id"]
    if exit_code == 0:
        transition(processing, "done")
        log(f"{kind}_completed request_id={request_id}")
        if kind == "claude":
            notify_claude(request_id)
        return

    retries = int(payload.get(RETRY_KEY) or 0) + 1
    log(f"{kind}_failed request_id={request_id} retry_count={retries}")
    if retries < MAX_RETRIES:
        # 原子写回 .ready 带重试元数据(retry_count+1/last_failed_at/next_retry_after)
        payload[RETRY_KEY] = retries
        payload[LAST_FAIL_KEY] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        payload[NEXT_RETRY_KEY] = time.time() + RETRY_DELAY_SECONDS
        atomic_write_signal(processing.with_suffix(".ready"), payload)
        processing.unlink(missing_ok=True)
    else:
        transition(processing, "failed")
        log(f"{kind}_gave_up request_id={request_id} after {retries} attempts")
        notify_gave_up(kind, request_id, retries)


def poll_running(running: dict) -> None:
    """非阻塞回收已结束子进程(poll() 立即返回), 按退出码处置; 未结束的跳过。"""
    for kind in list(running):
        exit_code = running[kind]["proc"].poll()
        if exit_code is not None:
            finish_job(running, kind, exit_code)


def notify_gave_up(kind: str, request_id: str, retries: int) -> None:
    """重试耗尽放弃告警:飞书 agent_done 群(失败绝不反噬主循环)。"""
    try:
        import sys

        sys.path.insert(0, str(REPO / "scripts"))
        from notify import send_feishu

        timestamp = time.strftime("%H:%M")
        send_feishu(
            "[codex] 信号处理放弃",
            f"{timestamp} request={request_id} {kind} 通道连续失败 "
            f"{retries} 次,已落 .failed 终态不再自动重试。\n"
            f"排查: /tmp/codex-reports/agent-inbox.log;人工处理后换新 id 重发。",
            chat_key="agent_done",
        )
    except Exception as error:  # noqa: BLE001 - notification must not break state
        log(f"notify_error={error}")


def parse_signaled_epoch(payload: dict, signal_path: Path) -> float:
    """报告时序基准: 优先信号 payload 的 signaled_at(codex_review_complete.py
    写入的 ISO8601 时刻); 缺失或不可解析时回退信号文件自身 mtime 作基准
    (重试写回会刷新 mtime, 故 signaled_at 必在时仅作手造信号的兜底)。"""
    raw = payload.get("signaled_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            pass
    try:
        return signal_path.stat().st_mtime
    except OSError:
        return 0.0


def report_is_fresh(payload: dict, signal_path: Path) -> tuple[bool, str]:
    """claude 回传报告有效性检查(2026-08-31 修复 codex ref 断点)。
    8-26 演进版比较报告 mtime vs job_started(作业启动时刻), 但报告必然写于
    作业消费前 → 比较恒假 → 100% 误拦真实回传。正确基准=信号创建时刻:
    codex_review_complete.py 写完信号后 touch 报告, 正常回传满足
    report.mtime >= signaled_at - 容差; 报告明显早于信号创建 = 信号重发而
    报告未重写的旧残留, 该拦(文案区分 stale report 真实语义)。
    无 report_path 的信号(codex 通道, 报告由作业期间自写)不适用, 直接放行。"""
    report_path = payload.get("report_path")
    if not isinstance(report_path, str) or not report_path:
        return True, ""
    report = Path(report_path)
    try:
        report_mtime = report.stat().st_mtime
    except OSError:
        return False, f"report missing: {report_path}"
    baseline = parse_signaled_epoch(payload, signal_path)
    if report_mtime < baseline - FRESHNESS_TOLERANCE_SECONDS:
        return False, (
            f"stale report: report mtime={report_mtime:.3f} 早于信号创建基准 "
            f"{baseline:.3f}(超容差 {FRESHNESS_TOLERANCE_SECONDS}s)"
            "= 疑似旧残留(信号重发但报告未重写), 该拦"
        )
    return True, ""


def pump_queue(inbox: Path, kind: str, running: dict) -> None:
    """扫描 inbox 取第一个可消费信号后台起子进程(每通道单槽: 本通道已有作业在跑
    则整轮跳过, 防并发多 codex exec; invalid 立即转态、重试未到期跳过)。"""
    if kind in running:
        return
    now = time.time()
    for ready in sorted(inbox.glob("*.ready")):
        stem = ready.stem
        if not ID_PATTERN.fullmatch(stem):
            transition(ready, "invalid")
            log(f"invalid_signal={ready.name}")
            continue

        payload = read_signal(ready)
        # 失败重试间隔:未到期(.ready 带 next_retry_after)本次跳过,防疯转
        next_retry = payload.get(NEXT_RETRY_KEY)
        if isinstance(next_retry, (int, float)) and now < next_retry:
            continue

        processing = transition(ready, "processing")
        payload = read_signal(processing)
        request_id = str(payload.get("request_id") or stem)
        if not ID_PATTERN.fullmatch(request_id):
            transition(processing, "invalid")
            log(f"invalid_request_id={request_id}")
            continue

        # 报告有效性机检: 不过 = 旧残留/缺失, .invalid 终态(重试无意义, 报告
        # 不会自己变新), 人工排查后换新 id 重发(同 gave_up 排查指引)
        valid, error = report_is_fresh(payload, processing)
        if not valid:
            transition(processing, "invalid")
            log(f"{kind}_rejected request_id={request_id} reason=report_invalid: {error}")
            continue

        spawn_job(kind, request_id, processing, payload,
                  build_command(kind, request_id), running)
        return  # 本轮至多占一个槽, 其余信号下轮槽空再取


def touch_heartbeat() -> None:
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.touch()
    except OSError as error:
        log(f"heartbeat_error={error}")


def main() -> int:
    if acquire_lock():
        log("another watcher owns the lock; exiting")
        return 1
    try:
        CODEX_INBOX.mkdir(parents=True, exist_ok=True)
        CLAUDE_INBOX.mkdir(parents=True, exist_ok=True)
        recover_processing(CODEX_INBOX)
        recover_processing(CLAUDE_INBOX)
        log("watcher started (async)")
        running: dict[str, dict] = {}  # kind -> 作业槽(codex/claude 各最多一个子进程)
        while True:
            touch_heartbeat()
            poll_running(running)
            pump_queue(CODEX_INBOX, "codex", running)
            pump_queue(CLAUDE_INBOX, "claude", running)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("watcher stopped")
        return 0
    finally:
        LOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
