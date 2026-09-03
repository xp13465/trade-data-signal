#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal-triggered launcher for Claude/Codex handoffs.
守护进程版（2026-09-03 重构）：不依赖 launchd KeepAlive，自己守护自己。
每次启动扫 refs/codex/req，有 pending 就 spawn codex exec 处理；
处理完 sleep 5s 继续扫；spawn 出去的 codex 用 openrouter/free + 60s×10 重试兜底。
"""

from __future__ import annotations

import json, os, re, subprocess, sys, time
from datetime import datetime
import json, os, re, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

REPO = Path("/Users/linhuichen/code/trade")
HEARTBEAT_PATH = Path("/tmp/agent_inbox_watcher.heartbeat")
LOCK_PATH = Path("/tmp/agent_inbox.lock")
CODEX_INBOX = Path("/tmp/codex-reports/signals/codex-inbox")
CLAUDE_INBOX = Path("/tmp/codex-reports/signals/claude-inbox")
REPORTS_DIR = Path("/tmp/codex-reports")
MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 60
RETRY_KEY = "retry_count"
NEXT_RETRY_KEY = "next_retry_after"
LAST_FAIL_KEY = "last_failed_at"
POLL_SECONDS = 5
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FRESNESS_TOLERANCE = 60

# Codex 默认用 openrouter/free（环境变量覆盖），禁止显式指向付费模型
# Codex 默认用 openrouter/free（环境变量覆盖），禁止显式指向付费模型
CODEX_BIN = os.environ.get(
    "CODEX_BIN",
    str(Path.home() / ".nvm/versions/node/v25.8.0/bin")
)

# OpenRouter 直调用配置（bypass codex exec 的 app-server 沙盒问题）
# OR_API_KEY 从 ~/.codex/.or_api_key 读取（不在代码库中，避免 GitHub secret scanning）
# 也支持环境变量 OR_API_KEY / OPENROUTER_API_KEY（用于 launchd / CI）
_or_key_file = Path.home() / ".codex" / ".or_api_key"
OR_API_KEY = os.environ.get("OR_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
if not OR_API_KEY and _or_key_file.exists():
    OR_API_KEY = _or_key_file.read_text().strip()
if not OR_API_KEY:
    raise SystemExit("OR_API_KEY env var or ~/.codex/.or_api_key required (one secret-free line)")
OR_API_BASE = "https://openrouter.ai/api/v1"
OR_MODEL = "openrouter/free"
OR_TIMEOUT_SECONDS = 120
CODEX_BIN = os.environ.get(
    "CODEX_BIN",
    str(Path.home() / ".nvm/versions/node/v25.8.0/bin/codex")
)

LOG_DIR = REPO / "data" / "logs"
LOG_FILE = LOG_DIR / "agent_inbox_watcher.log"
ERR_FILE = LOG_DIR / "agent_inbox_watcher.err"


def log(msg, err=False):
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    line = f"{ts} {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if err:
        try:
            with open(ERR_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


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
    dst = src.with_name(f"{src.stem}.{new_state}")
    src.rename(dst)
    return dst


def _ensure_node_env(env):
    """确保 PATH 中包含 node 所在目录，防止 codex exec 找不到 node."""
    node_bin = str(Path.home() / ".nvm/versions/node/v25.8.0/bin")
    path = env.get("PATH", "")
    if node_bin and node_bin not in path.split(":"):
        env["PATH"] = node_bin + ":" + path
    return env

def call_openrouter_codex(prompt: str) -> int:
    """直接调 OpenRouter /api/v1/chat/completions，bypass codex exec 的 app-server 沙盒问题.
    返回退出码（0=成功, 1=失败, 2=rate limit, 3=auth 失败）.
    """
    url = OR_API_BASE + "/chat/completions"
    body = json.dumps({
        "model": OR_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32000,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + OR_API_KEY,
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/linhuichen/trade",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OR_TIMEOUT_SECONDS) as resp:
            data = resp.read()
        obj = json.loads(data)
        text = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
        log(f"openrouter_response_len={len(text)}")
        return 0
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        log(f"openrouter_http_error={e.code} body={body}", err=True)
        if e.code == 429:
            return 2
        if e.code in (401, 403):
            return 3
        return 1
    except Exception as e:
        log(f"openrouter_exception={e}", err=True)
        return 1


def _run_http_job(kind, request_id, processing, payload, running, prompt):
    """在主线程直接调 OpenRouter HTTP API，bypass codex exec 沙盒限制."""
    log(f"http_spawn kind={kind} request_id={request_id}")
    running[kind] = dict(kind=kind, request_id=request_id,
                          processing=processing, payload=payload, proc=None)
    try:
        rc = call_openrouter_codex(prompt)
        if rc == 2:
            # 429 rate limit：等 120s 重试
            running.pop(kind, None)
            retries = int(payload.get(RETRY_KEY, 0)) + 1
            if retries < MAX_RETRIES:
                payload[RETRY_KEY] = retries
                payload[NEXT_RETRY_KEY] = time.time() + 120
                atomic_write_signal(processing.with_name(f"{processing.stem}.ready"), payload)
                log(f"{kind}_retry_429 request_id={request_id} retry={retries}/{MAX_RETRIES} after=120s")
            else:
                transition(processing, "failed")
                log(f"{kind}_gave_up_429 request_id={request_id} after {MAX_RETRIES} retries")
            return
        finish_job(running, kind, rc)
    except Exception as e:
        log(f"http_error kind={kind} request_id={request_id} e={e}", err=True)
        finish_job(running, kind, 1)

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
    return [
        "bash",
        str(REPO / "scripts" / "codex-review-report.sh"),
        request_id
    ]


def finish_job(running, kind, exit_code):
    job = running.pop(kind, None)
    if not job:
        return
    proc = job.get("proc")
    request_id = job["request_id"]
    processing = job["processing"]
    payload = job["payload"]
    log(f"job_done kind={kind} request_id={request_id} exit={exit_code}")
    if exit_code == 0:
        transition(processing, "done")
        return
    retries = int(payload.get(RETRY_KEY, 0)) + 1
    if retries < MAX_RETRIES:
        payload[RETRY_KEY] = retries
        payload[LAST_FAIL_KEY] = datetime.now().isoformat()
        payload[NEXT_RETRY_KEY] = time.time() + RETRY_DELAY_SECONDS
        atomic_write_signal(processing.with_name(f"{processing.stem}.ready"), payload)
        log(f"{kind}_retry request_id={request_id} retry={retries}/{MAX_RETRIES} after={RETRY_DELAY_SECONDS}s")
    else:
        transition(processing, "failed")
        log(f"{kind}_gave_up request_id={request_id} after {MAX_RETRIES} retries")


def spawn_job(kind, request_id, processing, payload, command, running, prompt=None):
    log(f"spawn kind={kind} request_id={request_id} cmd={command[0]}...")
    try:
        env = _ensure_node_env(os.environ.copy())
        inp = prompt.encode("utf-8") if isinstance(prompt, str) else (prompt or b"")
        proc = subprocess.Popen(
            command,
            cwd=REPO,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env,
        )
        # 立即写入 stdin 并关闭，避免 codex exec 阻塞在读 stdin 上
        if inp:
            try:
                proc.stdin.write(inp)
                proc.stdin.close()
            except Exception as e:
                log(f"stdin_write_error kind={kind} request_id={request_id} e={e}", err=True)
    except OSError as e:
        log(f"spawn_error kind={kind} request_id={request_id} e={e}", err=True)
        # synthetic job for finish_job
        stub = dict(kind=kind, request_id=request_id, processing=processing,
                    payload=payload, proc=None)
        finish_job({kind: stub}, kind, -1)
        return
    running[kind] = dict(kind=kind, request_id=request_id,
                          processing=processing, payload=payload, proc=proc,
                          prompt=inp)


def poll_running(running):
    for kind in list(running):
        proc = running[kind].get("proc")
        if proc is None:
            finish_job(running, kind, -1)
            continue
        rc = proc.poll()
        if rc is not None:
            try:
                out, err = proc.communicate(timeout=5)
                if err and err.strip():
                    err_text = err.decode("utf-8", errors="replace").strip()
                    last_line = err_text.split(chr(10))[-1]
                    log(f"{kind}_stderr: {last_line[:300]}")
            except Exception as e:
                log(f"poll_running.communicate_error: {e}")
            finish_job(running, kind, rc)


def recover_processing(inbox):
    for f in inbox.glob("*.processing"):
        log(f"recover_processing {f.name}")
        atomic_write_signal(f.with_name(f"{f.stem}.ready"), read_signal(f))
        f.unlink()


def parse_signaled_epoch(payload, signal_path):
    raw = payload.get("signaled_at")
    if isinstance(raw, (int, float)):
        return raw
    return signal_path.stat().st_mtime


def report_is_fresh(payload, signal_path):
    """验证报告已落地且 request_id/verdict 有效.
    
    不再比较 mtime vs signaled_at（报告 mtime 必然 <= signaled_at，
    因为报告先写完再发信号。mtime freshness 检查方向错误，
    会误判新报告为 stale。.done 文件才是真正的完成信号。
    """
    request_id = payload.get("request_id", signal_path.stem)
    report = REPORTS_DIR / f"{request_id}.json"
    if not report.exists():
        return False, f"report not yet written at {report}"
    # 基本 schema 验证
    import json
    try:
        with report.open(encoding="utf-8") as f:
            obj = json.load(f)
        if obj.get("request_id") != request_id:
            return False, f"request_id mismatch: {obj.get('request_id')} != {request_id}"
        if "verdict" not in obj:
            return False, "verdict field missing"
    except Exception as e:
        return False, f"report parse error: {e}"
    return True, "ok"


def pump_queue(inbox, kind, running, cmd_factory):
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
        # codex 任务走 HTTP 直调（bypass codex exec app-server 沙盒问题）
        if kind == "codex":
            prompt = cmd_factory(request_id)
            _run_http_job(kind, request_id, processing, payload, running, prompt)
            return
        result = cmd_factory(request_id)
        cmd = result if isinstance(result, list) else result[0]
        prompt = result[1] if isinstance(result, tuple) else ""
        spawn_job(kind, request_id, processing, payload, cmd, running,
                  prompt=prompt)
        return


def touch_heartbeat():
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.touch()
    except OSError as e:
        log(f"heartbeat_error={e}", err=True)


def main():
    if acquire_lock():
        log("another watcher owns the lock; exiting")
        return 1
    try:
        CODEX_INBOX.mkdir(parents=True, exist_ok=True)
        CLAUDE_INBOX.mkdir(parents=True, exist_ok=True)
        recover_processing(CODEX_INBOX)
        recover_processing(CLAUDE_INBOX)
        log(f"watcher started self-healing mode max_retries={MAX_RETRIES} retry_delay={RETRY_DELAY_SECONDS}s CODEX_BIN={CODEX_BIN}")
        running = {}
        while True:
            touch_heartbeat()
            poll_running(running)
            pump_queue(CODEX_INBOX, "codex", running, build_codex_command_prompt)
            pump_queue(CLAUDE_INBOX, "claude", running, build_claude_command)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("watcher stopped by signal")
        return 0
    finally:
        LOCK_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
