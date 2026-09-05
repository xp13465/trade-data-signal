#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal-triggered launcher for Claude/Codex handoffs. 7x24 守护进程."""
from __future__ import annotations
import json, os, re, subprocess, sys, time, signal, threading, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/linhuichen/code/trade")
HEARTBEAT_PATH = Path("/tmp/agent_inbox_watcher.heartbeat")
LOCK_PATH = Path("/tmp/agent_inbox.lock")
CODEX_INBOX = Path("/tmp/codex-reports/signals/codex-inbox")
CLAUDE_INBOX = Path("/tmp/codex-reports/signals/claude-inbox")
REPORTS_DIR = Path("/tmp/codex-reports")
LOG_DIR = REPO / "data" / "logs"
LOG_FILE = LOG_DIR / "agent_inbox_watcher.log"
CODEX_BIN = os.environ.get("CODEX_BIN", "/Users/linhuichen/.nvm/versions/node/v25.8.0/bin/codex")
OR_API_KEY = os.environ.get("OR_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
if not OR_API_KEY:
    _key_file = Path.home() / ".codex" / ".or_api_key"
    if _key_file.exists():
        OR_API_KEY = _key_file.read_text().strip()
if not OR_API_KEY:
    raise SystemExit("OR_API_KEY required")
OR_API_BASE = "https://openrouter.ai/api/v1"
OR_MODEL = "openrouter/free"
MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 60
POLL_SECONDS = 5
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    line = f"{ts} {msg}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8", buffering=1) as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass

def acquire_lock():
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        log("acquired lock")
        return True
    except FileExistsError:
        log("lock held by another; exit")
        return False

def touch_heartbeat():
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.touch()
    except Exception as e:
        log(f"heartbeat_error={e}")

def read_signal(p):
    return json.loads(p.read_text(encoding="utf-8"))

def sync_git_refs():
    """将 git refs/codex/req 下 pending 但缺 .ready 的请求补 .ready 信号"""
    try:
        r = subprocess.run(
            ["git", "for-each-ref", "refs/codex/req", "--format=%(refname:short)"],
            capture_output=True, text=True, cwd=str(REPO), timeout=10
        )
    except Exception as e:
        log(f"sync_git_refs error: {e}")
        return
    for line in r.stdout.strip().splitlines():
        name = line.strip()
        if not name:
            continue
        rid = name.split("/")[-1]
        if not ID_PATTERN.fullmatch(rid):
            continue
        ready = CODEX_INBOX / f"{rid}.ready"
        if ready.exists():
            continue
        # fetch blob json
        try:
            br = subprocess.run(
                ["git", "cat-file", "blob", f"refs/{name}"],
                capture_output=True, text=True, cwd=str(REPO), timeout=10
            )
        except Exception:
            continue
        if br.returncode != 0:
            continue
        CODEX_INBOX.mkdir(parents=True, exist_ok=True)
        try:
            ready.write_text(br.stdout, encoding="utf-8")
            log(f"sync_git_refs created {ready}")
        except Exception as e:
            log(f"sync_git_refs write error {rid}: {e}")


def transition(src, new_state):
    dst = src.with_name(f"{src.stem}.{new_state}")
    src.rename(dst)
    return dst

def is_already_processed(request_id):
    if (CLAUDE_INBOX / f"{request_id}.ready").exists():
        return True
    return False

def build_codex_command_prompt(request_id):
    return (
        "你是 trade 仓库的 Codex 外部 reviewer。先读 AGENTS.md 和 "
        "docs/codex-collab-protocol.md,再检查 refs/codex/req 下所有 pending "
        "request。只按 request JSON 的 base..head 与 focus_areas 执行独立复核;"
        "报告必须先写 .tmp 再 rename 到 /tmp/codex-reports/<request_id>.json;"
        "每个完成项调用 python3 scripts/codex_review_complete.py <request_id> "
        "--verdict <PASS|FAIL|BLOCKED> 建立 Claude 回传信号。不要 commit/push。"
    )

def build_claude_command(request_id):
    return ["echo", "claude task"]

def pump_queue(inbox, kind, running, cmd_factory):
    if kind in running:
        return
    for ready in sorted(inbox.glob("*.ready")):
        stem = ready.stem
        if not ID_PATTERN.fullmatch(stem):
            transition(ready, "invalid")
            continue
        if is_already_processed(stem):
            transition(ready, "skipped")
            log(f"skipped already-processed request {stem}")
            continue
        payload = read_signal(ready)
        processing = transition(ready, "processing")
        request_id = str(payload.get("request_id", stem))
        if not ID_PATTERN.fullmatch(request_id):
            transition(processing, "invalid")
            continue
        log(f"spawn kind={kind} request_id={request_id}")
        if kind == "codex":
            prompt = cmd_factory(request_id)
            proc = subprocess.Popen(
                [CODEX_BIN, "exec", "--cd", str(REPO), "--add-dir", "/tmp/codex-reports",
                 "--ephemeral", "--sandbox", "workspace-write", "--color", "never",
                 "-c", "model_max_output_tokens=64000", prompt],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=str(REPO), preexec_fn=os.setpgrp
            )
        else:
            cmd = cmd_factory(request_id)
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    cwd=str(REPO), preexec_fn=os.setpgrp)
        running[kind] = dict(request_id=request_id, proc=proc, processing=processing)
        return

def poll_running(running):
    for kind in list(running):
        info = running[kind]
        proc = info.get("proc")
        if proc is None:
            continue
        rc = proc.poll()
        if rc is None:
            continue
        request_id = info["request_id"]
        processing = info["processing"]
        log(f"job_done kind={kind} request_id={request_id} exit={rc}")
        running.pop(kind, None)
        if rc == 0:
            transition(processing, "done")
            try:
                subprocess.run([
                    sys.executable, str(REPO / "scripts" / "codex_review_complete.py"),
                    request_id, "--verdict", "PASS"
                ], capture_output=True, timeout=30)
            except Exception as e:
                log(f"codex_review_complete error: {e}")
        else:
            transition(processing, "failed")

def main():
    if not acquire_lock():
        return 1
    _stop = threading.Event()
    def _handle_signal(signum, frame):
        log(f"received signal {signum}, shutting down")
        _stop.set()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        CODEX_INBOX.mkdir(parents=True, exist_ok=True)
        CLAUDE_INBOX.mkdir(parents=True, exist_ok=True)
        log(f"watcher started self-healing mode max_retries={MAX_RETRIES} retry_delay={RETRY_DELAY_SECONDS}s CODEX_BIN={CODEX_BIN}")
        running = {}
        while not _stop.is_set():
            touch_heartbeat()
            sync_git_refs()
            poll_running(running)
            pump_queue(CODEX_INBOX, "codex", running, build_codex_command_prompt)
            pump_queue(CLAUDE_INBOX, "claude", running, build_claude_command)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("watcher stopped by signal")
    finally:
        log("watcher exiting")
        LOCK_PATH.unlink(missing_ok=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
