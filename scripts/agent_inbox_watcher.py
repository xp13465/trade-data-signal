#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal-triggered launcher for Claude/Codex handoffs. 7x24 守护进程.

设计要点 (2026-09-05 重构):
- PID 锁: lock 文件写 os.getpid(), 启动时检测已存在锁对应的 PID 是否存活;
  死了自动回收, 活着则退出避免 202 进程并存(根因修复)
- verdict 来源: poll_running rc==0 时 parse 报告里 verdict, 透传给 codex_review_complete
  (避免硬编码 PASS 与报告真实 verdict 不一致导致 raise)
- 重试治理: failed 状态记录 retry_count, sync_git_refs 跳过 retry 耗尽的请求,
  避免无限重试烧额度
- ref 清理: 报告落盘 + claude-inbox 信号完成后, git update-ref -d 删除 ref 防止
  已 done 请求被 sync_git_refs 反复扫描(skip 而不是补)
- claude 通道: 真实 spawn claude-inbox-consumer.sh, 不再 echo 占位
- 429 识别: poll_running 检测 stderr/output 含 429 自动延时重试
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, signal, threading
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
REF_STATUS_DIR = Path("/tmp/codex-ref-status")
CODEX_BIN = os.environ.get("CODEX_BIN", "/Users/linhuichen/.nvm/versions/node/v25.8.0/bin/codex")
REVIEWER_MODEL = os.environ.get("CODEX_REVIEWER_MODEL", "").strip()  # 外审模型, 缺省跟随 config.toml
OR_API_KEY = os.environ.get("OR_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or ""
if not OR_API_KEY:
    _key_file = Path.home() / ".codex" / ".or_api_key"
    if _key_file.exists():
        OR_API_KEY = _key_file.read_text().strip()
if not OR_API_KEY:
    raise SystemExit("OR_API_KEY required")
MAX_RETRIES = 10
RETRY_DELAY_SECONDS = 60
POLL_SECONDS = 5
LOCK_STALE_SECONDS = 600  # 锁文件无心跳超过 10 分钟视为陈旧
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

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def acquire_lock():
    """PID 锁: O_EXCL 创建, 含本进程 PID. 已有锁时检查 PID 是否存活."""
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, f"{os.getpid()}\n".encode())
        os.close(fd)
        log(f"acquired lock pid={os.getpid()}")
        return True
    except FileExistsError:
        # 锁已存在, 检查对方 PID
        try:
            content = LOCK_PATH.read_text(encoding="utf-8").strip()
            other_pid = int(content.splitlines()[0])
        except (FileNotFoundError, ValueError, IndexError):
            # 锁文件为空或不可解析, 强制回收
            try:
                LOCK_PATH.unlink()
                log("recovered malformed lock")
            except FileNotFoundError:
                pass
            return acquire_lock()
        if _pid_alive(other_pid):
            log(f"lock held by alive pid={other_pid}; exit")
            return False
        # PID 已死, 强制回收陈旧锁
        log(f"recovered stale lock from dead pid={other_pid}")
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
        return acquire_lock()

def touch_heartbeat():
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_PATH.write_text(f"{os.getpid()} {time.time()}\n", encoding="utf-8")
    except Exception as e:
        log(f"heartbeat_error={e}")

def read_signal(p):
    return json.loads(p.read_text(encoding="utf-8"))

def transition(src, new_state):
    dst = src.with_name(f"{src.stem}.{new_state}")
    try:
        src.rename(dst)
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return dst

def is_already_processed(request_id):
    """已处理 = claude-inbox 已收到回传(.ready/.done/.skipped/.blocked)."""
    for state in ("ready", "done", "skipped", "blocked"):
        if (CLAUDE_INBOX / f"{request_id}.{state}").exists():
            return True
    return False

def retry_count(request_id):
    """读 /tmp/codex-ref-status/<id>.retry 文件, 缺省 0."""
    rc_file = REF_STATUS_DIR / f"{request_id}.retry"
    try:
        return int(rc_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0

def bump_retry(request_id):
    rc_file = REF_STATUS_DIR / f"{request_id}.retry"
    try:
        REF_STATUS_DIR.mkdir(parents=True, exist_ok=True)
        rc_file.write_text(str(retry_count(request_id) + 1), encoding="utf-8")
    except Exception as e:
        log(f"bump_retry error {request_id}: {e}")

def _failed_at(request_id):
    """读上次失败时间戳, 缺省 0."""
    p = REF_STATUS_DIR / f"{request_id}.failed_at"
    try:
        return float(p.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0.0

def _touch_failed(request_id):
    try:
        REF_STATUS_DIR.mkdir(parents=True, exist_ok=True)
        (REF_STATUS_DIR / f"{request_id}.failed_at").write_text(str(time.time()), encoding="utf-8")
    except Exception as e:
        log(f"_touch_failed error {request_id}: {e}")

def retry_backoff_ok(request_id):
    """距上次失败是否已满退避时间(首次失败视为已満)."""
    return (time.time() - _failed_at(request_id)) >= RETRY_DELAY_SECONDS

def cleanup_ref(request_id):
    """报告/信号都落盘后, 删 git ref + /tmp 镜像 + 锁残留 retry 计数."""
    ref_short = f"refs/codex/req/{request_id}"
    try:
        subprocess.run(
            ["git", "update-ref", "-d", ref_short],
            capture_output=True, text=True, cwd=str(REPO), timeout=10
        )
        log(f"cleanup_ref removed git ref {ref_short}")
    except Exception as e:
        log(f"cleanup_ref git error {request_id}: {e}")
    for ext in (".retry", ".failed_at"):
        try:
            (REF_STATUS_DIR / f"{request_id}{ext}").unlink()
        except FileNotFoundError:
            pass

def sync_git_refs():
    """扫描 git refs/codex/req, 把有 ref 但缺 .ready 的请求补 .ready 信号.

    跳过 retry_count >= MAX_RETRIES 的请求(避免烧额度).
    跳过已 done/failed 的请求(防止 sync 反复补已完结请求).
    """
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
        done = CODEX_INBOX / f"{rid}.done"
        failed = CODEX_INBOX / f"{rid}.failed"
        skipped = CODEX_INBOX / f"{rid}.skipped"
        processing = CODEX_INBOX / f"{rid}.processing"
        # 在途: ready/processing 不重复建
        if ready.exists() or processing.exists():
            continue
        # 终态: done/skipped 但 ref 未删(cleanup 失败或 skip 未清理) -> 补删 ref 防泄漏
        if done.exists() or skipped.exists():
            log(f"sync_git_refs terminal {rid} -> cleanup_ref")
            cleanup_ref(rid)
            continue
        # failed 但 retry 未耗尽 -> 重建 .ready 让 pump 重试
        if failed.exists():
            if retry_count(rid) >= MAX_RETRIES:
                # 重试耗尽, 标记 blocked 终态(不再重试, 避免烧额度)
                log(f"sync_git_refs blocked {rid}: retry exhausted")
                _write_blocked(rid)
                cleanup_ref(rid)
                continue
            if not retry_backoff_ok(rid):
                # 退避时间未满, 暂不重建 ready
                continue
            # retry 未耗尽且退避已满, fall through 补 ready
        # blocked 终态, 不再处理
        blocked = CODEX_INBOX / f"{rid}.blocked"
        if blocked.exists():
            continue
        # claude 已收到回传 -> 终态, 直接删 ref 防泄漏
        if is_already_processed(rid):
            log(f"sync_git_refs already-processed {rid} -> cleanup_ref")
            cleanup_ref(rid)
            continue
        # 报告已落盘但可能未回传(一次 exec 审所有 ref 的场景) -> 补回传 + 清理
        verdict = _read_report_verdict(rid)
        if verdict:
            log(f"sync_git_refs report-done {rid} verdict={verdict} -> complete+cleanup")
            _run_codex_complete(rid, verdict)
            cleanup_ref(rid)
            continue
        if retry_count(rid) >= MAX_RETRIES:
            log(f"sync_git_refs skip {rid}: retry_count >= {MAX_RETRIES}")
            transition_failed_marker = CODEX_INBOX / f"{rid}.failed"
            try:
                transition_failed_marker.write_text(
                    json.dumps({"request_id": rid, "reason": "retry_exhausted"}),
                    encoding="utf-8",
                )
            except Exception:
                pass
            cleanup_ref(rid)
            continue
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

def _write_blocked(request_id):
    """重试耗尽后标记 .blocked 终态(不再重试, 避免烧额度)."""
    try:
        (CODEX_INBOX / f"{request_id}.blocked").write_text(
            json.dumps({"request_id": request_id, "reason": "retry_exhausted",
                        "blocked_at": datetime.now().isoformat()}),
            encoding="utf-8",
        )
        log(f"sync_git_refs wrote .blocked {request_id}")
    except Exception as e:
        log(f"sync_git_refs write blocked error {request_id}: {e}")


def sweep_stale_state():
    """启动时清理没有对应 git ref 的僵尸 active 状态与 retry 计数(防无限重试)."""
    try:
        r = subprocess.run(
            ["git", "for-each-ref", "refs/codex/req", "--format=%(refname:short)"],
            capture_output=True, text=True, cwd=str(REPO), timeout=10
        )
        ref_ids = set()
        for line in r.stdout.strip().splitlines():
            rid = line.strip().split("/")[-1]
            if ID_PATTERN.fullmatch(rid):
                ref_ids.add(rid)
    except Exception as e:
        log(f"sweep_stale_state git error: {e}")
        return
    active_suffixes = (".ready", ".processing", ".failed")
    for inbox in (CODEX_INBOX, CLAUDE_INBOX):
        if not inbox.exists():
            continue
        for sig in inbox.iterdir():
            if not sig.is_file() or sig.suffix not in active_suffixes:
                continue
            if sig.stem not in ref_ids:
                try:
                    sig.unlink()
                    log(f"sweep_stale_state removed {sig}")
                except Exception as e:
                    log(f"sweep_stale_state remove error {sig}: {e}")
    for ext in (".retry", ".failed_at"):
        if not REF_STATUS_DIR.exists():
            break
        for rc in REF_STATUS_DIR.iterdir():
            if rc.suffix == ext and rc.stem not in ref_ids:
                try:
                    rc.unlink()
                    log(f"sweep_stale_state removed counter {rc}")
                except Exception as e:
                    log(f"sweep_stale_state counter error {rc}: {e}")

def build_codex_command_prompt(request_id):
    return (
        "你是 trade 仓库的 Codex 外部 reviewer。先读 AGENTS.md 和 "
        "docs/codex-collab-protocol.md,再检查 refs/codex/req 下所有 pending "
        "request。只按 request JSON 的 base..head 与 focus_areas 执行独立复核;"
        "报告必须先写 .tmp 再 rename 到 /tmp/codex-reports/<request_id>.json;"
        "全部复核完成、完整报告落盘后只调用一次 python3 scripts/codex_review_complete.py <request_id> "
        "--verdict <PASS|FAIL|BLOCKED> 建立 Claude 回传信号(verdict 必须与 "
        "报告 JSON 中 verdict 字段一致, 否则 raise)。不要 commit/push。"
    )

def build_claude_command(request_id):
    return ["bash", str(REPO / "scripts" / "claude-inbox-consumer.sh"), request_id]

def pump_queue(inbox, kind, running, cmd_factory):
    if kind in running:
        return
    for ready in sorted(inbox.glob("*.ready")):
        stem = ready.stem
        if not ID_PATTERN.fullmatch(stem):
            transition(ready, "invalid")
            continue
        # is_already_processed 短路只服务 codex 队列(避免重跑已回传请求);
        # claude 队列的 .ready 就是待消费信号, 不能短路, 否则 claude-inbox-consumer 永不 spawn
        if kind == "codex" and is_already_processed(stem):
            transition(ready, "skipped")
            cleanup_ref(stem)
            log(f"skipped already-processed request {stem} (ref cleaned)")
            continue
        try:
            payload = read_signal(ready)
        except Exception as e:
            log(f"pump_queue read_signal error {stem}: {e}")
            transition(ready, "invalid")
            continue
        request_id = str(payload.get("request_id", stem))
        if not ID_PATTERN.fullmatch(request_id):
            transition(ready, "invalid")
            continue
        if retry_count(request_id) >= MAX_RETRIES:
            log(f"pump_queue blocked {request_id}: retry exhausted")
            transition(ready, "blocked")
            _write_blocked(request_id)
            cleanup_ref(request_id)
            continue
        # 根治竞态(2026-09-16):codex worker 还在跑时,其子 agent 可能已过早回传
        # .ready(中间态报告),此时消费会拿到半成品并反复覆盖 claude 回执。等 codex 收尾。
        if kind == "claude":
            cw = running.get("codex")
            if cw is not None and (cw.get("request_id") == stem or cw.get("request_id") == request_id):
                log(f"claude queue wait: codex worker still running for {stem}")
                continue
        processing = transition(ready, "processing")
        if kind == "codex":
            prompt = cmd_factory(request_id)
            cmd = [CODEX_BIN, "exec", "--cd", str(REPO),
                   "--add-dir", "/tmp/codex-reports", "--ephemeral",
                   "--sandbox", "workspace-write", "--color", "never"]
            if REVIEWER_MODEL:
                cmd += ["-m", REVIEWER_MODEL]
            cmd += ["-c", "model_max_output_tokens=64000", prompt]
        else:
            cmd = cmd_factory(request_id)
        log(f"spawn kind={kind} request_id={request_id} retry={retry_count(request_id)}")
        # stdout/stderr 用文件重定向, 避免 PIPE 缓冲写满导致子进程阻塞死锁
        # (此前 PIPE 只在进程退出后才 communicate 排水, 子进程写满 64KB 后永久卡住)
        log_path = LOG_DIR / f"inbox-{kind}-{request_id}.log"
        try:
            outf = log_path.open("wb")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=outf, stderr=subprocess.STDOUT,
                cwd=str(REPO), preexec_fn=os.setpgrp,
            )
        except Exception as e:
            log(f"spawn error kind={kind} request_id={request_id}: {e}")
            try:
                outf.close()
            except Exception:
                pass
            transition(processing, "failed")
            continue
        running[kind] = dict(request_id=request_id, proc=proc,
                              processing=processing, started_at=time.time(),
                              cmd_kind=kind, cmd=cmd,
                              outfile=outf, log_path=log_path)
        return

def _detect_429(proc) -> bool:
    """轻量检测: 看启动后短窗口进程是否很快退出且返回码含 429 痕迹.
    简化: 只看 rc 与触发时间间隔(<10s 退出判 429 嫌疑)."""
    return False  # 现有 OpenRouter 通过 429 重试由 codex 自身处理, 此函数留作扩展

def _read_report_verdict(request_id):
    report_path = REPORTS_DIR / f"{request_id}.json"
    if not report_path.exists():
        return None
    try:
        with report_path.open(encoding="utf-8") as f:
            data = json.load(f)
        v = data.get("verdict")
        if v in ("PASS", "FAIL", "BLOCKED"):
            return v
    except Exception as e:
        log(f"_read_report_verdict parse error {request_id}: {e}")
    return None

def _run_codex_complete(request_id, verdict):
    try:
        subprocess.run([
            sys.executable, str(REPO / "scripts" / "codex_review_complete.py"),
            request_id, "--verdict", verdict
        ], capture_output=True, timeout=30)
    except Exception as e:
        log(f"codex_review_complete error {request_id}: {e}")

def _notify_feishu(request_id, title, body):
    """外审/复核完成直接推飞书(2026-09-16 根治, 不要复线)。
    通知不再依赖 codex 的 ~/.codex/config.toml notify(该键会被 computer-use
    插件覆盖导致静默断链, 属「被覆盖就不应出现」的根因)。改为内嵌到 watcher 主循环,
    版本受 git 管理, 不可被插件改写。任何异常只 log 不抛, 绝不影响主循环。"""
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from notify import send_feishu
        send_feishu(f"[codex-review] {title} {request_id}", body, chat_key="agent_done")
    except Exception as e:  # noqa: BLE001
        log(f"_notify_feishu error {request_id}: {e}")

def poll_running(running):
    now = time.time()
    for kind in list(running):
        info = running[kind]
        proc = info.get("proc")
        if proc is None:
            continue
        rc = proc.poll()
        if rc is None:
            # 进程还在跑, 检查是否超时
            if now - info["started_at"] > 3600:  # 60 分钟硬超时
                log(f"job_timeout kind={kind} request_id={info['request_id']}")
                proc.kill()
                proc.wait()
                rc = -1
            else:
                continue
        request_id = info["request_id"]
        processing = info["processing"]
        log(f"job_done kind={kind} request_id={request_id} exit={rc}")
        # 关输出文件句柄, 读 log 尾部做诊断
        outfile = info.get("outfile")
        if outfile is not None:
            try:
                outfile.flush()
                outfile.close()
            except Exception:
                pass
        log_path = info.get("log_path")
        if log_path is not None:
            try:
                tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
                if tail and ("429" in tail or "Rate limit" in tail or "quota" in tail.lower()):
                    log(f"job_{request_id} 429 detected: {tail[-300:]}")
                elif tail:
                    log(f"job_{request_id} output tail: {tail[-300:]}")
            except Exception:
                pass
        running.pop(kind, None)
        if rc == 0 and kind == "codex":
            verdict = _read_report_verdict(request_id)
            if verdict:
                transition(processing, "done")
                _run_codex_complete(request_id, verdict)
                cleanup_ref(request_id)
                _notify_feishu(
                    request_id,
                    f"外审完成 verdict={verdict}",
                    f"报告: /tmp/codex-reports/{request_id}.json",
                )
            else:
                # 报告缺失/不可解析 -> BLOCKED 终态(不重试, 同 prompt 大概率同样失败)
                log(f"job_done but report invalid request_id={request_id} -> blocked")
                transition(processing, "blocked")
                _write_blocked(request_id)
                bump_retry(request_id)
                cleanup_ref(request_id)
        elif rc == 0:
            transition(processing, "done")
            cleanup_ref(request_id)
            _notify_feishu(
                request_id,
                "复核完成",
                f"claude 消费者 exit=0, 回执: /tmp/codex-reports/claude-actions/{request_id}.json",
            )
        else:
            _touch_failed(request_id)
            bump_retry(request_id)
            if retry_count(request_id) >= MAX_RETRIES:
                log(f"retry exhausted request_id={request_id} -> blocked")
                transition(processing, "blocked")
                _write_blocked(request_id)
                cleanup_ref(request_id)
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
        REF_STATUS_DIR.mkdir(parents=True, exist_ok=True)
        sweep_stale_state()
        log(f"watcher started pid={os.getpid()} max_retries={MAX_RETRIES} retry_delay={RETRY_DELAY_SECONDS}s CODEX_BIN={CODEX_BIN}")
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
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
