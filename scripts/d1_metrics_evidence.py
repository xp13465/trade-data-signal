#!/usr/bin/env python3
"""Private metadata from existing D1 calls only; never execute SQL or retain results.

One atomic file/run, serialized by a bounded flock. No totals: a failed attempt may
have committed work, and import meta is cumulative for a bundle, not per table.
See docs/codex-reviews/ops-backlog-20261111/d1.md for the evidence contract.
"""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import time

from util_atomic import atomic_write_json

MAX_RUNS = 128
MAX_CALLS = 4096
MAX_BYTES = 16 * 1024 * 1024
SAMPLE_BYTES = 1024 * 1024
MAX_AGE = 30 * 86400
TABLES = {"fund_score", "fund_screener", "sync_meta", "screener_meta"}
IDENTITY_FILES = ("sync_fund_score_to_d1.sh", "sync_fund_screener_to_d1.sh",
                  "lib/d1_execute.sh", "lib/d1_hash_read.sh", "d1_metrics_evidence.py",
                  "util_atomic.py", "delivery_evidence.py")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def startup_identity(script_dir):
    """Disk observation before sourcing D1 libs; explicitly not loaded shell proof."""
    def git(*args):
        try:
            result = subprocess.run(["git", "-C", str(script_dir.parent), *args],
                                    capture_output=True, timeout=2)
            return result.stdout.decode().strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            return None
    before = git("rev-parse", "HEAD")
    files = {}
    for name in IDENTITY_FILES:
        try:
            with (script_dir / name).open("rb") as f:
                raw = f.read(1024 * 1024 + 1)
            files[name] = hashlib.sha256(raw).hexdigest() if len(raw) <= 1024 * 1024 else None
        except OSError:
            files[name] = None
    dirty = git("status", "--porcelain", "--untracked-files=no", "--",
                *("scripts/" + name for name in IDENTITY_FILES))
    return {"schema": 1, "captured_utc": utc_now(), "head_before": before,
            "head_after": git("rev-parse", "HEAD"),
            "dirty_tracked": bool(dirty) if dirty is not None else None, "files_sha256": files}


def code_identity():
    # Reuse loaded bytecode identity. A reviewed manifest can bind THIS Python
    # executor to a commit; it cannot attest the already running shell pipeline.
    try:
        from delivery_evidence import loaded_code_identity
        executor = loaded_code_identity(main, Path(os.environ["REPO"]))
    except Exception:
        executor = {"sha": "unknown", "kind": "unavailable"}
    startup = None
    try:
        raw = os.environ.get("D1_METRICS_STARTUP_IDENTITY", "")
        if len(raw) <= 8192:
            obj = json.loads(raw)
            stamp = obj["captured_utc"]
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            digest = lambda v, n: v if isinstance(v, str) and re.fullmatch("[0-9a-f]{%d}" % n, v) else None
            startup = {"captured_utc": stamp, "head_before": digest(obj.get("head_before"), 40),
                       "head_after": digest(obj.get("head_after"), 40),
                       "dirty_tracked": obj.get("dirty_tracked") if type(obj.get("dirty_tracked")) is bool else None,
                       "files_sha256": {n: digest(obj["files_sha256"].get(n), 64) for n in IDENTITY_FILES}}
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return {"executor": executor, "startup_disk_snapshot": startup,
            "runtime_limits": {"sample_bytes_per_stream": SAMPLE_BYTES, "max_receipt_bytes": MAX_BYTES},
            "coverage": "loaded_python_executor_plus_pre_d1_source_disk_snapshot",
            "limitations": "shell_entry_already_started;disk_hash_not_loaded_shell_bytes;concurrent_replace_possible;git_heads_are_observations_not_code_attestation"}


def documents(text):
    """Decode whole JSON values surrounded by Wrangler banners, never recurse rows."""
    decoder = json.JSONDecoder()
    i = 0
    while i < len(text):
        if text[i] not in "[{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            # Do not salvage nested row objects from a truncated JSON response.
            # Text banners such as [WARNING] can still precede valid JSON.
            rest = text[i + 1:].lstrip()
            if rest.startswith(('"', '{', '[', ']', '}')):
                return
            i += 1
            continue
        yield obj
        i = end


def result_items(obj):
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict) and
                any(k in x for k in ("meta", "success", "error", "results"))]
    if not isinstance(obj, dict):
        return []
    # REST envelope; its success/errors apply to the call, not to each child.
    if isinstance(obj.get("result"), (list, dict)):
        return result_items(obj["result"])
    if any(k in obj for k in ("meta", "success", "error", "results")):
        return [obj]
    return []


def numeric(meta, name, integer=False):
    value = meta.get(name)
    if value is None:
        return None, "meta_missing" if not meta else "field_missing"
    if (type(value) not in (int, float) or not math.isfinite(value) or value < 0
            or (integer and not float(value).is_integer())):
        return None, "invalid_number"
    return value, None


def parse_results(stdout, stderr, scope):
    # Multiple emissions may be cumulative snapshots OR partial results. Retain
    # distinct emissions without adding them; deduplicate mirrored documents.
    snapshots = []
    for stream in (stdout, stderr):
        found = [x for x in documents(stream) if result_items(x)]
        snapshots.extend(found)
    unique = []
    for obj in snapshots:
        if obj not in unique:
            unique.append(obj)
    # Differing snapshots across streams have no reliable chronology. Preserve
    # them but mark non-additive, rather than guessing which counter is final.
    ambiguous = len(unique) > 1
    records = []
    for snap_index, obj in enumerate(unique):
        for index, item in enumerate(result_items(obj)):
            meta = item.get("meta")
            meta = meta if isinstance(meta, dict) else {}
            row = {"scope": scope, "result_index": index, "snapshot_index": snap_index,
                   "aggregation": "ambiguous_snapshots_do_not_sum" if ambiguous else "one_snapshot",
                   "status": ("success" if item.get("success") is True else
                              "failed" if item.get("success") is False or item.get("error") else "unknown"),
                   "missing_reasons": {}}
            for key in ("rows_read", "rows_written", "duration", "total_attempts"):
                value, reason = numeric(meta, key, integer=key != "duration")
                row[key] = value
                if reason:
                    row["missing_reasons"][key] = reason
            row["duration_unit"] = "ms"
            # Query IDs are not guaranteed by D1Result. Never substitute bookmark,
            # account/database IDs, SQL, or a guessed identifier.
            query_id = item.get("query_id", meta.get("query_id"))
            row["query_id"] = query_id if (isinstance(query_id, str) and
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", query_id)) else None
            if row["query_id"] is None:
                row["missing_reasons"]["query_id"] = "not_returned" if query_id is None else "unrecognized_id"
            # Wrangler import renders num_queries twice (display row + meta).
            # The display row is ONLY used for this query count, never row costs.
            count = item.get("num_queries")
            if scope == "bundle" and count is None:
                display = item.get("results")
                if isinstance(display, list) and len(display) == 1 and isinstance(display[0], dict):
                    count = display[0].get("Total queries executed")
            row["query_count"], reason = numeric({"query_count": count}, "query_count", integer=True)
            if reason:
                row["missing_reasons"]["query_count"] = "not_returned"
            records.append(row)
    if not records:
        # A textual error, killed process, or missing meta is not zero usage.
        records = parse_results('{"success":null}', "", scope)
        records[0]["missing_reasons"] = {k: "no_structured_response" for k in records[0]["missing_reasons"]}
    return records


def private_directory(root):
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    st = root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise ValueError("unsafe_directory")
    root.chmod(0o700)


def persist(root, event):
    """Dedup by call_id+attempt; retain latest bounded run files under one lock."""
    private_directory(root)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root / ".lock", flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("evidence_lock")
                time.sleep(0.02)
        path = root / (event["run_id"] + ".json")
        if path.is_symlink():
            raise ValueError("unsafe_file")
        if path.exists() and path.stat().st_size > MAX_BYTES:
            raise ValueError("run_size_limit")
        data = json.loads(path.read_text()) if path.exists() else {"schema_version": 1, "calls": []}
        key = event["call_id"], event["attempt"]
        if any((x["call_id"], x["attempt"]) == key for x in data["calls"]):
            return
        if len(data["calls"]) >= MAX_CALLS:
            raise ValueError("run_call_limit")
        data["calls"].append(event)
        if len(json.dumps(data).encode()) > MAX_BYTES:
            raise ValueError("run_size_limit")
        # Serialize retention with writes. Only our UUID-named JSON files qualify.
        # Admission fails if eviction fails: repeated failures cannot grow the
        # directory without bound. The current run's prior receipt stays intact.
        old = sorted((p for p in root.glob("*.json") if re.fullmatch(r"[0-9a-f]{32}\.json", p.name)
                      and p != path and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
        now = time.time()
        for i, p in enumerate(old):
            if i >= MAX_RUNS - 1 or now - p.stat().st_mtime > MAX_AGE:
                p.unlink()
        atomic_write_json(path, data, mode=0o600)
    finally:
        os.close(fd)


def record(args, streams):
    run_id = os.environ["D1_METRICS_RUN_ID"]
    if not re.fullmatch(r"[0-9a-f]{32}", run_id) or not re.fullmatch(r"[0-9a-f]{32}", args.call_id):
        raise ValueError("invalid_identity")
    tables = args.tables.split(",") if args.tables else []
    if set(tables) - TABLES or args.attempt < 1:
        raise ValueError("invalid_labels")
    for stamp in (args.start, args.end):
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    script = os.environ.get("SCRIPT_NAME")
    script = script if script in {"sync_fund_score_to_d1", "sync_fund_screener_to_d1"} else None
    observation = getattr(args, "response_observation", {})
    overflow = observation.get("sample_overflow", False) or any(len(raw) > SAMPLE_BYTES for raw in streams)
    rows = parse_results("", "", args.scope) if overflow else parse_results(
        *(s.decode("utf-8", errors="replace") for s in streams), args.scope)
    if overflow:
        rows[0]["missing_reasons"] = {k: "response_sample_limit" for k in rows[0]["missing_reasons"]}
    event = {"run_id": run_id, "call_id": args.call_id, "code_ref": None,
             "code_ref_reason": "shell_chain_unattested", "script": script,
             "code_identity": getattr(args, "code_identity", None) or code_identity(),
             "response_observation": observation,
             "table_labels": tables, "stage": args.stage, "operation": args.operation,
             "start_utc": args.start, "end_utc": args.end, "attempt": args.attempt,
             "exit_code": args.exit_code, "status": "success" if args.exit_code == 0 else "failed",
             "results": rows}
    known = [r["rows_read"] is not None and r["rows_written"] is not None for r in event["results"]]
    event["metrics_status"] = "complete" if all(known) else "partial" if any(known) else "unavailable"
    persist(Path(os.environ["D1_METRICS_DIR"]), event)


@contextmanager
def nonblocking(fd):
    """Temporarily make inherited sinks nonblocking, restoring status flags."""
    # O_NONBLOCK cannot bound regular-file I/O; leave their status flags alone.
    if stat.S_ISREG(os.fstat(fd).st_mode):
        yield
        return
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    changed = not flags & os.O_NONBLOCK
    if changed:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    try:
        yield
    finally:
        if changed:
            fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def merge_sink(targets, declared=False):
    """Pipe aliases share capacity. Regular-file aliases need caller attestation.

    Same inode alone does not prove the same open file description: two opens
    may have independent offsets. The shell declares its explicit >out 2>&1.
    """
    if targets[0] == targets[1]:
        return True
    try:
        a, b = (os.fstat(fd) for fd in targets)
        same = (a.st_dev, a.st_ino, a.st_mode) == (b.st_dev, b.st_ino, b.st_mode)
        return same and (declared or stat.S_ISFIFO(a.st_mode) or stat.S_ISSOCK(a.st_mode))
    except OSError:
        return False


def warn():
    message = b"[d1-evidence] WARN: evidence incomplete; original command rc retained; no evidence-triggered SQL retry\n"
    try:
        fd = int(os.environ.get("D1_METRICS_WARN_FD", "2"))
        with nonblocking(fd):
            os.write(fd, message)
    except (OSError, ValueError):
        pass  # A full/closed warning sink must not defeat cleanup or change rc.


def save_safely(args, streams):
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError()))
    signal.alarm(8)
    try:
        record(args, streams)
        return True
    except Exception:
        warn()  # no exception text, paths, SQL or response fragments
        return False
    finally:
        signal.alarm(0)


def run_streamed(command, timeout, targets=(1, 2), merge_output=False):
    """Continuously forward/drain two pipes with <=64 KiB pending per stream.

    Only a bounded prefix is sampled; discard it after overflow. Never spool raw
    responses to disk, and never close a child pipe because metrics are too large.
    Shared sinks get one OS-merged child pipe, preserving atomic error messages.
    Readiness is only a hint: nonblocking writes handle races and backpressure.
    """
    samples = [bytearray(), bytearray()]
    counts = [0, 0]
    overflow = [False, False]
    failed = [False, False]
    pending = [b"", b""]
    merged = merge_sink(targets, merge_output)
    if merged:
        targets = targets[:1]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT if merged else subprocess.PIPE,
                            start_new_session=True, bufsize=0)
    pipes = (proc.stdout,) if merged else (proc.stdout, proc.stderr)
    readers = {pipe.fileno(): i for i, pipe in enumerate(pipes)}
    deadline = time.monotonic() + timeout if timeout > 0 else float("inf")
    stopped = None
    cleanup_deadline = float("inf")
    requested = [None]
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    for s in previous:
        signal.signal(s, lambda sig, _frame: requested.__setitem__(0, sig))
    # Atomic-sized writes plus O_NONBLOCK; select alone cannot reserve capacity.
    write_sizes = []
    for fd in targets:
        try:
            write_sizes.append(min(4096, os.fpathconf(fd, "PC_PIPE_BUF")))
        except OSError:
            write_sizes.append(512)

    def kill_group():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    modes = ExitStack()
    try:
        for i, fd in enumerate(targets):
            try:
                modes.enter_context(nonblocking(fd))
            except OSError:
                failed[i] = True  # still drain child and preserve its return code
        while readers or any(pending) or proc.poll() is None:
            now = time.monotonic()
            if stopped is None and (requested[0] or now >= deadline):
                stopped = 128 + requested[0] if requested[0] else 124
                kill_group()
                cleanup_deadline = now + 2
            if now >= cleanup_deadline:
                # A detached descendant/blocked consumer must not retain us.
                failed = [failed[i] or bool(pending[i]) or i in readers.values() for i in range(2)]
                break
            readable = [fd for fd, i in readers.items() if not pending[i]]
            writable = [fd for i, fd in enumerate(targets) if pending[i] and not failed[i]]
            wait = min(0.05, max(0, (deadline if stopped is None else cleanup_deadline) - now))
            ready_r, ready_w, _ = select.select(readable, writable, [], wait)
            for fd in ready_r:
                i = readers[fd]
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    del readers[fd]
                    pipes[i].close()
                    continue
                counts[i] += len(chunk)
                if not overflow[i]:
                    if counts[i] > SAMPLE_BYTES:
                        overflow[i] = True
                        samples[i].clear()
                    else:
                        samples[i].extend(chunk)
                if not failed[i]:
                    pending[i] = chunk
            for i in range(len(targets)):
                if pending[i] and targets[i] in ready_w:
                    try:
                        written = os.write(targets[i], pending[i][:write_sizes[i]])
                        pending[i] = pending[i][written:]
                    except BlockingIOError:
                        continue  # shared/racing writers consumed the ready space
                    except OSError:
                        failed[i] = True
                        pending[i] = b""  # continue draining; do not change child rc
        proc.wait(timeout=2)
    finally:
        if proc.poll() is None:
            kill_group()
            proc.wait(timeout=2)
        for pipe in pipes:
            pipe.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        modes.close()
    if any(failed):
        warn()
    observation = {"sample_limit_per_stream": SAMPLE_BYTES, "sample_overflow": any(overflow),
                   "stdout_bytes": counts[0], "stderr_bytes": counts[1],
                   "stdout_sample_bytes": len(samples[0]), "stderr_sample_bytes": len(samples[1]),
                   "stdout_overflow": overflow[0], "stderr_overflow": overflow[1],
                   "forwarding_failed": any(failed)}
    observation["stream_mode"] = "merged" if merged else "separate"
    if merged:
        observation.update(merged_bytes=counts[0], merged_sample_bytes=len(samples[0]),
                           merged_overflow=overflow[0], stdout_bytes=None, stderr_bytes=None,
                           stdout_sample_bytes=None, stderr_sample_bytes=None,
                           stdout_overflow=None, stderr_overflow=None)
    rc = stopped if stopped is not None else proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
    return tuple(bytes(s) for s in samples), observation, rc


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--capture-identity":
        signal.alarm(8)
        try:
            print(json.dumps(startup_identity(Path(sys.argv[2]))))
            return 0
        finally:
            signal.alarm(0)
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout")
    parser.add_argument("--stderr")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output-mode", choices=("separate", "merged"), default="separate")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--call-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--stage", choices=["migration", "hash_prefetch", "import", "count_verify"], required=True)
    parser.add_argument("--operation", choices=["ALTER", "SELECT", "IMPORT"], required=True)
    parser.add_argument("--scope", choices=["statement", "bundle"], required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    args.code_identity = code_identity()  # actual loaded functions, before child execution
    if not args.run:
        with open(args.stdout, "rb") as out, open(args.stderr, "rb") as err:
            streams = out.read(SAMPLE_BYTES + 1), err.read(SAMPLE_BYTES + 1)
        return 0 if save_safely(args, streams) else 1
    args.start = utc_now()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        streams, args.response_observation, args.exit_code = run_streamed(command, args.timeout,
                                                                       merge_output=args.output_mode == "merged")
    except OSError:
        streams = b"", b"[d1] executor unavailable\n"
        args.exit_code = 127
        os.write(2, streams[1])
    args.end = utc_now()
    save_safely(args, streams)
    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())
