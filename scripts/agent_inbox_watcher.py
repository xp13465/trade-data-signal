#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal-triggered launcher for Claude/Codex handoffs.

2026-09-01 codex-reviewer hardening:
- HEARTBEAT_PATH = /tmp/agent_inbox_watcher.heartbeat (避开 trade-data SIP)
- CLAUDE_BIN 环境变量替换 "claude"
- codex 分支 exec 命令固定 10 次重试 / 60s 间隔(应对 free 每日重置)
- claude 分支沿用 codex-review-report.sh(已在主控已合,无需 spawn claude)
"""

from __future__ import annotations

import json, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/linhuichen/code/trade")
HEARTBEAT_PATH = Path("/tmp/agent_inbox_watcher.heartbeat")
LOCK_PATH = Path("/tmp/agent_inbox.lock")
SESSIONS_DIR = Path.home() / ".codex" / "sessions"
CODEX_INBOX = Path("/tmp/codex-reports/signals/codex-inbox")
CLAUDE_INBOX = Path("/tmp/codex-reports/signals/claude-inbox")
MAIN_SESSION_LOOKBACK_DAYS = 7
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
POLL_SECONDS = 2
MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 60
RETRY_KEY = "retry_count"
NEXT_RETRY_KEY = "next_retry_after"
LAST_FAIL_KEY = "last_failed_at"
FRESHNESS_TOLERANCE_SECONDS = 60
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    print(f"{ts} {msg}", flush=True)


def acquire_lock():
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCK_PATH.touch()
        return False
    except FileExistsError:
        return True


def read_signal(p):
    return json.loads(p.read_text(encoding="utf-8"))


def atomic_write_signal(p, payload):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def transition(src, new_state):
    dst = src.with_suffix(f".{new_state}")
    src.rename(dst)
    return dst


def build_command(kind, request_id):
    if kind == "codex":
        prompt = (
            "你是 trade 仓库的 Codex 外部 reviewer。先读 AGENTS.md 和 "
            "docs/codex-collab-protocol.md,再检查 refs/codex/req 下所有 pending "
            "request。只按 request JSON 的 base..head 与 focus_areas 执行独立复核;"
            "报告必须先写 .tmp 再 rename 到 /tmp/codex-reports/<request_id>.json;"
            "每个完成项调用 python3 scripts/codex_review_complete.py <request_id> "
            "--verdict <PASS|FAIL|BLOCKED> 建立 Claude 回传信号。不要 commit/push。"
        )
        return [
            CODEX_BIN, "exec",
            "--cd", str(REPO),
            "--add-dir", "/tmp/codex-reports",
            "--ephemeral",
            "--sandbox", "workspace-write",
            "--color", "never",
            "-c", "model_max_output_tokens=64000",
            prompt,
        ]
    return ["bash", str(REPO / "scripts" / "codex-review-report.sh"), request_id]


def finish_job(running, kind, exit_code):
    job = running.pop(kind, None)
    if not job:
        return
    processing = job["processing"]
    payload = job["payload"]
    request_id = job["request_id"]
    log(f"job_done kind={kind} request_id={request_id} exit={exit_code}")
    if exit_code == 0:
        transition(processing, "done")
        return
    retries = int(payload.get(RETRY_KEY, 0)) + 1
    if retries < MAX_RETRIES:
        payload[RETRY_KEY] = retries
        payload[LAST_FAIL_KEY] = datetime.now().isoformat()
        payload[NEXT_RETRY_KEY] = time.time() + RETRY_DELAY_SECONDS
        atomic_write_signal(processing.with_suffix(".ready"), payload)
        log(f"{kind}_retry request_id={request_id} retry={retries}/{MAX_RETRIES} after={RETRY_DELAY_SECONDS}s")
    else:
        transition(processing, "failed")
        log(f"{kind}_gave_up request_id={request_id} after {MAX_RETRIES} retries")


def spawn_job(kind, request_id, processing, payload, command, running):
    log(f"spawn cmd: {' '.join(command)}")
    try:
        proc = subprocess.Popen(command, cwd=REPO)
    except OSError as e:
        log(f"spawn_error={e}")
        finish_job({kind: {"kind": kind, "request_id": request_id,
                            "processing": processing, "payload": payload}}, kind, -1)
        return
    running[kind] = {"kind": kind, "request_id": request_id,
                     "processing": processing, "payload": payload, "proc": proc}


def poll_running(running):
    for kind in list(running):
        proc = running[kind].get("proc")
        if proc is None:
            finish_job(running, kind, -1)
            continue
        rc = proc.poll()
        if rc is not None:
            finish_job(running, kind, rc)


def recover_processing(inbox):
    for f in inbox.glob("*.processing"):
        log(f"recover_processing {f.name}")
        atomic_write_signal(f.with_suffix(".ready"), read_signal(f))
        f.unlink()


def parse_signaled_epoch(payload, signal_path):
    raw = payload.get("signaled_at")
    if isinstance(raw, (int, float)):
        return raw
    return signal_path.stat().st_mtime


def report_is_fresh(payload, signal_path):
    request_id = payload.get("request_id", signal_path.stem)
    report = Path(f"/tmp/codex-reports/{request_id}.json")
    if not report.exists():
        return True, "report not yet written (normal during execution)"
    baseline = parse_signaled_epoch(payload, signal_path)
    if report.stat().st_mtime < baseline - FRESHNESS_TOLERANCE_SECONDS:
        return False, f"report mtime={report.stat().st_mtime} < signaled_at={baseline}"
    return True, "ok"


def pump_queue(inbox, kind, running):
    if kind in running:
        return
    now = time.time()
    for ready in sorted(inbox.glob("*.ready")):
        stem = ready.stem
        if not ID_PATTERN.fullmatch(stem):
            transition(ready, "invalid")
            continue
        payload = read_signal(ready)
        next_retry = payload.get(NEXT_RETRY_KEY)
        if isinstance(next_retry, (int, float)) and now < next_retry:
            continue
        processing = transition(ready, "processing")
        payload = read_signal(processing)
        request_id = str(payload.get("request_id", stem))
        if not ID_PATTERN.fullmatch(request_id):
            transition(processing, "invalid")
            continue
        valid, err = report_is_fresh(payload, processing)
        if not valid:
            transition(processing, "invalid")
            log(f"{kind}_rejected request_id={request_id} reason={err}")
            continue
        spawn_job(kind, request_id, processing, payload,
                  build_command(kind, request_id), running)
        return


def touch_heartbeat():
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.touch()
    except OSError as e:
        log(f"heartbeat_error={e}")


def main():
    if acquire_lock():
        log("another watcher owns the lock; exiting")
        return 1
    try:
        CODEX_INBOX.mkdir(parents=True, exist_ok=True)
        CLAUDE_INBOX.mkdir(parents=True, exist_ok=True)
        recover_processing(CODEX_INBOX)
        recover_processing(CLAUDE_INBOX)
        log(f"watcher started max_retries={MAX_RETRIES} retry_delay={RETRY_DELAY_SECONDS}s (codex uses config.toml default model)")
        running = {}
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
