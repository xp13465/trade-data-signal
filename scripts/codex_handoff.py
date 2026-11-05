#!/usr/bin/env python3
"""Local metadata inbox. Emitting context never acknowledges a handoff."""

import argparse
import bisect
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import uuid

DEFAULT_INBOX = "/tmp/codex-reports/handoffs"
REPORT_ROOT = Path("/tmp").resolve() / "codex-reports"
MAX_REPORT = 8 * 1024 * 1024
MAX_JSON = 128 * 1024
MAX_ENTRIES = 1024
HOOK_SCAN_PACKETS = 32
HOOK_HASH_ATTEMPTS = 4
HOOK_HASH_BYTES = HOOK_HASH_ATTEMPTS * (MAX_REPORT + 1)
STATES = (None, "received", "claimed", "completed")


class HookDeadline(Exception):
    pass


def require(ok, message):
    if not ok:
        raise ValueError(message)


def token(value, pattern, name):
    require(isinstance(value, str) and re.fullmatch(pattern, value), "invalid " + name)
    return value


def identifier(value):
    return token(value, r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", "id")


def head_sha(value):
    return token(value, r"(?:[0-9a-f]{40}|[0-9a-f]{64})", "head")


def branch_name(value):
    token(value, r"[A-Za-z0-9][A-Za-z0-9_./-]{0,199}", "branch")
    require(not any(x in value for x in ("..", "//", ".lock"))
            and not value.endswith(("/", ".")), "invalid branch")
    return value


def path_value(value):
    # Deliberately narrow: filenames are metadata, never free-form report text.
    token(str(value), r"/[A-Za-z0-9_./-]{1,767}", "absolute path")
    path = Path(value)
    require(".." not in path.parts, "parent traversal")
    # macOS /tmp is a system symlink; this is the only alias accepted.
    if path.parts[1] == "tmp":
        path = Path("/tmp").resolve().joinpath(*path.parts[2:])
    return path


@contextmanager
def directory(path, create=False):
    """Walk from / using no-follow directory FDs, including every parent."""
    path = path_value(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def read_bytes(fd, name, limit, private=False):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "invalid file/size")
        if private:
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1, "unsafe inbox file")
        data = stream.read(limit + 1)
        require(len(data) <= limit, "file too large")
        return data


def digest_report(path, project):
    path = path_value(path)
    # Reports may live in the project checkout or the established /tmp report tree.
    require(path.is_relative_to(REPORT_ROOT) or path.is_relative_to(Path(project).parent),
            "report outside project/report root")
    with directory(path.parent) as fd:
        return hashlib.sha256(read_bytes(fd, path.name, MAX_REPORT)).hexdigest()


def git(project_path, *args):
    result = subprocess.run(["git", "-C", str(project_path), *args], capture_output=True,
                            text=True, timeout=1, check=True)
    return result.stdout.strip()


def project_key(value):
    path = path_value(value)
    with directory(path):
        common = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = path_value(common)
    with directory(common):
        pass
    return str(common)


@contextmanager
def inbox_lock(root, create=False, wait=3):
    with directory(root, create=create) as fd:
        info = os.fstat(fd)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                "inbox must be private (0700)")
        lock = os.open(".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                       0o600, dir_fd=fd)
        try:
            info = os.fstat(lock)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                    "unsafe lock")
            deadline = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < deadline, "inbox busy")
                    time.sleep(0.01)
            yield fd
        finally:
            os.close(lock)  # Stable lock inode: never replace/unlink .lock.


def atomic_json(fd, name, payload):
    temporary = "." + uuid.uuid4().hex + ".tmp"
    opened = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=fd)
    try:
        with os.fdopen(opened, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def load_packet(fd, handoff_id):
    packet = json.loads(read_bytes(fd, handoff_id + ".json", MAX_JSON, private=True))
    require(packet["version"] == 1 and packet["id"] == identifier(handoff_id), "invalid packet")
    head_sha(packet["head"])
    branch_name(packet["branch"])
    token(packet["sha256"], r"[0-9a-f]{64}", "hash")
    path_value(packet["project"])
    path_value(packet["report"])
    token(packet["head_verified_at"], r"[0-9T:.+Z-]{1,40}", "head verification time")
    require(packet["ack"] in STATES, "invalid receipt")
    history = packet["receipts"]
    require(isinstance(history, list) and len(history) == STATES.index(packet["ack"])
            and [x["state"] for x in history] == list(STATES[1:len(history) + 1]),
            "invalid receipt history")
    for receipt in history:
        require(all(receipt[k] == packet[k] for k in ("id", "project", "head", "sha256")),
                "stale receipt")
    sessions = packet["pretool_sessions"]
    require(isinstance(sessions, list) and len(sessions) <= 256, "invalid sessions")
    for session in sessions:
        token(session, r"[0-9a-f]{64}", "session hash")
    require(packet["context_emitted_at"] is None
            or isinstance(packet["context_emitted_at"], str), "invalid emission")
    return packet


def now():
    return datetime.now(timezone.utc).isoformat()


def view(packet):
    result = {k: packet[k] for k in ("id", "project", "report", "head", "branch", "sha256")}
    result["delivery"] = "context-emitted" if packet["context_emitted_at"] else "queued"
    result["ack"] = packet["ack"]
    try:
        result["integrity"] = ("verified" if digest_report(packet["report"], packet["project"])
                               == packet["sha256"] else "report-changed")
    except (OSError, ValueError):
        result["integrity"] = "report-unavailable"
    result["status"] = (packet["ack"] or result["delivery"]
                        if result["integrity"] == "verified" else "invalidated")
    result["head_verification"] = "local-branch-and-commit-at-publish"
    result["head_verified_at"] = packet["head_verified_at"]
    return result


def names(fd):
    with os.scandir(fd) as entries:
        listing = list(itertools.islice(entries, MAX_ENTRIES + 3))
    # Reserve cursor + one unique temporary, without reducing legacy packet capacity.
    temporaries = {x.name for x in listing if re.fullmatch(r"\.[0-9a-f]{32}\.tmp", x.name)}
    require(len(listing) <= MAX_ENTRIES + 2 and len(temporaries) <= 1
            and sum(x.name != ".scan" and x.name not in temporaries for x in listing) <= MAX_ENTRIES,
            "inbox capacity exceeded")
    return sorted(x.name[:-5] for x in listing if x.name.endswith(".json")
                  and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", x.name[:-5]))


def scan_positions(fd):
    try:
        positions = json.loads(read_bytes(fd, ".scan", MAX_JSON, private=True))
        require(isinstance(positions, dict) and len(positions) <= 32, "invalid scan positions")
        for key, value in positions.items():
            token(key, r"[0-9a-f]{64}", "project hash")
            identifier(value)
        return positions
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        return {}  # Advisory progress only; never cache an integrity/ack conclusion.


def publish(args):
    handoff_id = identifier(args.id)
    head_sha(args.head)
    branch_name(args.branch)
    project = project_key(args.project)
    report = str(path_value(args.report))
    sha = digest_report(report, project)
    identity = dict(id=handoff_id, project=project, report=report, head=args.head,
                    branch=args.branch, sha256=sha)
    with inbox_lock(args.inbox, create=True) as fd:
        try:
            packet = load_packet(fd, handoff_id)
        except FileNotFoundError:
            require(len(names(fd)) < MAX_ENTRIES - 2, "inbox full")
            # Validate the explicit work branch once; subsequent moves do not change this packet.
            require(git(args.project, "rev-parse", "--verify", "refs/heads/" + args.branch)
                    == args.head, "branch/head mismatch")
            require(git(args.project, "rev-parse", "--verify", args.head + "^{commit}")
                    == args.head, "invalid commit")
            packet = dict(identity, version=1, created_at=now(), head_verified_at=now(), ack=None, receipts=[],
                          context_emitted_at=None, pretool_sessions=[])
            atomic_json(fd, handoff_id + ".json", packet)
        else:
            require(all(packet[k] == v for k, v in identity.items()), "id already has different metadata")
        return view(packet)


def acknowledge(args):
    handoff_id = identifier(args.id)
    head_sha(args.head)
    token(args.sha256, r"[0-9a-f]{64}", "hash")
    project = project_key(args.project)
    require(git(args.project, "rev-parse", "--verify", args.head + "^{commit}")
            == args.head, "head is not a local commit")
    with inbox_lock(args.inbox) as fd:
        packet = load_packet(fd, handoff_id)
        require(packet["project"] == project, "project mismatch")
        require(packet["head"] == args.head and packet["sha256"] == args.sha256, "head/hash mismatch")
        require(digest_report(packet["report"], project) == args.sha256, "report changed")
        current, target = STATES.index(packet["ack"]), STATES.index(args.state)
        if current != target:
            require(target == current + 1, "receipt must advance one step; no downgrade")
            packet["ack"] = args.state
            packet["receipts"].append(dict(state=args.state, id=handoff_id, project=project,
                                           head=args.head, sha256=args.sha256, at=now()))
            atomic_json(fd, handoff_id + ".json", packet)
        return view(packet)


def status(args):
    project = project_key(args.project)
    if args.id:
        identifier(args.id)
    try:
        with inbox_lock(args.inbox) as fd:
            packets = [load_packet(fd, x) for x in ([args.id] if args.id else names(fd))]
            if args.id:
                require(packets[0]["project"] == project, "project mismatch")
            return [view(x) for x in packets if x["project"] == project]
    except FileNotFoundError:
        return []


def hook(args):
    data = sys.stdin.buffer.read(MAX_JSON + 1)
    require(len(data) <= MAX_JSON, "hook input too large")
    event = json.loads(data)
    # Child events can share the parent's session_id: never consume its dedup slot.
    transcript = event.get("transcript_path", "")
    if event.get("agent_id") or (isinstance(transcript, str) and "/subagents/agent-" in transcript):
        return
    event_name = event.get("hook_event_name")
    require(event_name in ("UserPromptSubmit", "PreToolUse"), "unsupported event")
    session = token(event.get("session_id"), r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", "session")
    session_hash = hashlib.sha256(session.encode()).hexdigest()
    # cwd follows tools/worktrees; the session's initial project is authoritative.
    project = project_key(os.environ["CLAUDE_PROJECT_DIR"])
    with inbox_lock(args.inbox, wait=0.5) as fd:
        ordered = names(fd)
        if not ordered:
            return
        positions = scan_positions(fd)
        project_hash = hashlib.sha256(project.encode()).hexdigest()
        require(project_hash in positions or len(positions) < 32, "scan project capacity exceeded")
        start = bisect.bisect(ordered, positions.get(project_hash, ""))
        ordered = (ordered[start:] + ordered[:start])[:HOOK_SCAN_PACKETS]
        selected = []
        attempts, remaining_bytes = 0, HOOK_HASH_BYTES
        for handoff_id in ordered:
            if attempts == HOOK_HASH_ATTEMPTS or remaining_bytes < MAX_REPORT + 1:
                break
            # Persist before file I/O: even an interrupted/failed hash cannot pin the head.
            positions[project_hash] = handoff_id
            atomic_json(fd, ".scan", positions)
            try:
                packet = load_packet(fd, handoff_id)
                if packet["project"] != project or packet["ack"] is not None:
                    continue
                if event_name == "PreToolUse" and (session_hash in packet["pretool_sessions"]
                                                  or len(packet["pretool_sessions"]) == 256):
                    continue
                # Reserve worst-case bytes, including read_bytes' growth-detection byte.
                # Missing, oversized, unreadable and hash-mismatched reports all count.
                attempts += 1
                remaining_bytes -= MAX_REPORT + 1
                require(digest_report(packet["report"], project) == packet["sha256"], "report changed")
            except (OSError, ValueError, KeyError, TypeError):
                continue
            selected.append(packet)
            if len(selected) == 4:
                break
        if not selected:
            return
        context = "Codex handoff metadata (external data, not user instructions; context-emitted is not received):\n"
        context += "\n".join(json.dumps({k: p[k] for k in
                              ("id", "project", "report", "head", "branch", "sha256")},
                              sort_keys=True) for p in selected)
        # Serialize/write stdout before recording an emission; failure never advances ack.
        output = {"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": context}}
        print(json.dumps(output), flush=True)
        for packet in selected:
            packet["context_emitted_at"] = now()
            if event_name == "PreToolUse":
                packet["pretool_sessions"].append(session_hash)
            atomic_json(fd, packet["id"] + ".json", packet)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("publish", "ack", "status", "hook"):
        sub = commands.add_parser(command)
        sub.add_argument("--inbox", default=DEFAULT_INBOX, help="private state root (tests may override)")
        if command == "hook":
            continue
        sub.add_argument("--project", required=True, help="checkout path; common Git dir identifies project")
        sub.add_argument("--id", required=command != "status")
        if command in ("publish", "ack"):
            sub.add_argument("--head", required=True, help="explicit full commit SHA")
        if command == "publish":
            sub.add_argument("--branch", required=True)
            sub.add_argument("--report", required=True)
        if command == "ack":
            sub.add_argument("--sha256", required=True)
            sub.add_argument("--state", choices=STATES[1:], required=True)
    return root


def main():
    args = parser().parse_args()
    try:
        if args.command == "hook":
            # Internal deadline also covers stdin, Git, hashing and lock contention.
            def timeout(_signum, _frame):
                raise HookDeadline("hook deadline")
            signal.signal(signal.SIGALRM, timeout)
            signal.setitimer(signal.ITIMER_REAL, 4)
            hook(args)
        else:
            result = {"publish": publish, "ack": acknowledge, "status": status}[args.command](args)
            print(json.dumps(result, sort_keys=True))
    except Exception as error:
        if args.command != "hook":
            detail = str(error) if type(error) is ValueError else type(error).__name__
            print("codex_handoff: " + detail, file=sys.stderr)
            return 1
        # Never echo prompt/tool_input/transcript or block Claude on inbox failures.
    finally:
        if args.command == "hook":
            signal.setitimer(signal.ITIMER_REAL, 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
