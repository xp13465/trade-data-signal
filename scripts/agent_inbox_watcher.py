#!/usr/bin/env python3
"""Signal-triggered launcher for Claude/Codex handoffs.

The watcher performs no model work while idle. A small JSON metadata signal
causes one fixed CLI invocation or deterministic schema check; signal names are
strictly validated so a file name cannot become shell input.
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
LOG_PATH = Path("/tmp/codex-reports/agent-inbox.log")
CODEX_INBOX = Path("/tmp/codex-reports/signals/codex-inbox")
CLAUDE_INBOX = Path("/tmp/codex-reports/signals/claude-inbox")
LOCK_PATH = Path("/tmp/codex-reports/agent-inbox.lock")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
POLL_SECONDS = 2


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


def run_cli(command: list[str], cwd: Path) -> bool:
    log(f"exec {' '.join(command)}")
    try:
        result = subprocess.run(command, cwd=cwd, check=False)
        ok = result.returncode == 0
        log(f"exit={result.returncode}")
        return ok
    except OSError as error:
        log(f"spawn_error={error}")
        return False


def dispatch_codex(request_id: str) -> bool:
    prompt = (
        "你是 trade 仓库的 Codex 外部 reviewer。先读 AGENTS.md 和 "
        "docs/codex-collab-protocol.md，再检查 refs/codex/req 下所有 pending "
        "request。只按 request JSON 的 base..head 与 focus_areas 执行独立复核；"
        "报告必须先写 .tmp 再 rename 到 /tmp/codex-reports/<request_id>.json；"
        "每个完成项调用 python3 scripts/codex_review_complete.py <request_id> "
        "--verdict <PASS|FAIL|BLOCKED> 建立 Claude 回传信号。不要 commit/push。"
    )
    command = [
        os.environ.get("CODEX_BIN", "codex"),
        "exec",
        "--cd",
        str(REPO),
        "--add-dir",
        "/tmp/codex-reports",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--color",
        "never",
        prompt,
    ]
    return run_cli(command, REPO)


def validate_claude_report(request_id: str) -> bool:
    return run_cli(
        ["bash", str(REPO / "scripts" / "codex-review-report.sh"), request_id], REPO
    )


def process_queue(inbox: Path, kind: str) -> None:
    for ready in sorted(inbox.glob("*.ready")):
        stem = ready.stem
        if not ID_PATTERN.fullmatch(stem):
            transition(ready, "invalid")
            log(f"invalid_signal={ready.name}")
            continue

        processing = transition(ready, "processing")
        payload = read_signal(processing)
        request_id = str(payload.get("request_id") or stem)
        if not ID_PATTERN.fullmatch(request_id):
            transition(processing, "invalid")
            log(f"invalid_request_id={request_id}")
            continue

        if kind == "codex":
            ok = dispatch_codex(request_id)
        else:
            ok = validate_claude_report(request_id)

        if ok:
            transition(processing, "done")
            log(f"{kind}_completed request_id={request_id}")
            if kind == "claude":
                notify_claude(request_id)
        else:
            transition(processing, "failed")
            log(f"{kind}_failed request_id={request_id}")


def main() -> int:
    if acquire_lock():
        log("another watcher owns the lock; exiting")
        return 1
    try:
        CODEX_INBOX.mkdir(parents=True, exist_ok=True)
        CLAUDE_INBOX.mkdir(parents=True, exist_ok=True)
        recover_processing(CODEX_INBOX)
        recover_processing(CLAUDE_INBOX)
        log("watcher started")
        while True:
            process_queue(CODEX_INBOX, "codex")
            process_queue(CLAUDE_INBOX, "claude")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("watcher stopped")
        return 0
    finally:
        LOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
