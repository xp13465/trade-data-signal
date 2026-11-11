#!/usr/bin/env python3
"""Private metadata from existing D1 calls only; never execute SQL or retain results.

One atomic file/run, serialized by a bounded flock. No totals: a failed attempt may
have committed work, and import meta is cumulative for a bundle, not per table.
See docs/codex-reviews/ops-backlog-20261111/d1.md for the evidence contract.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

from util_atomic import atomic_write_json

MAX_RUNS = 128
MAX_CALLS = 4096
MAX_BYTES = 16 * 1024 * 1024
MAX_AGE = 30 * 86400
TABLES = {"fund_score", "fund_screener", "sync_meta", "screener_meta"}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
    code = os.environ.get("D1_METRICS_CODE_REF", "")
    code = code if re.fullmatch(r"[0-9a-f]{40,64}", code) else None
    script = os.environ.get("SCRIPT_NAME")
    script = script if script in {"sync_fund_score_to_d1", "sync_fund_screener_to_d1"} else None
    if any(len(raw) > MAX_BYTES for raw in streams):
        raise ValueError("response_size_limit")
    event = {"run_id": run_id, "call_id": args.call_id, "code_ref": code,
             "code_ref_reason": None if code else "unavailable", "script": script,
             "table_labels": tables, "stage": args.stage, "operation": args.operation,
             "start_utc": args.start, "end_utc": args.end, "attempt": args.attempt,
             "exit_code": args.exit_code, "status": "success" if args.exit_code == 0 else "failed",
             "results": parse_results(*(s.decode("utf-8", errors="replace") for s in streams), args.scope)}
    known = [r["rows_read"] is not None and r["rows_written"] is not None for r in event["results"]]
    event["metrics_status"] = "complete" if all(known) else "partial" if any(known) else "unavailable"
    persist(Path(os.environ["D1_METRICS_DIR"]), event)


def warn():
    message = b"[d1-evidence] WARN: evidence incomplete; original command rc retained; no evidence-triggered SQL retry\n"
    try:
        os.write(int(os.environ.get("D1_METRICS_WARN_FD", "2")), message)
    except OSError:
        pass


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout")
    parser.add_argument("--stderr")
    parser.add_argument("--run", action="store_true")
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
    if not args.run:
        with open(args.stdout, "rb") as out, open(args.stderr, "rb") as err:
            streams = out.read(MAX_BYTES + 1), err.read(MAX_BYTES + 1)
        return 0 if save_safely(args, streams) else 1
    args.start = utc_now()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except OSError:
        streams = b"", b"[d1] executor unavailable\n"
        args.exit_code = 127
    else:
        def terminate(signum, _frame):
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGINT, terminate)
        try:
            streams = proc.communicate(timeout=args.timeout if args.timeout > 0 else None)
            args.exit_code = proc.returncode if proc.returncode >= 0 else 128 - proc.returncode
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            streams = proc.communicate()
            args.exit_code = 124
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
    args.end = utc_now()
    save_safely(args, streams)
    # Binary replay preserves stdout/stderr bytes, even invalid UTF-8. Persistence
    # failure does not change business rc or feed the network retry classifier.
    for target, raw in zip((sys.stdout.buffer, sys.stderr.buffer), streams):
        try:
            target.write(raw)
            target.flush()
        except OSError:
            warn()
    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())
