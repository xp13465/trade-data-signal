"""DRAFT tests-first closeout; pair with Claude's business fix before merging.

At base 6c1493aea the 20 metadata-error cases must fail, without xfail/skip.
Each test loads a fresh real notify module after installing temporary isolation.
Importing this test module does not change env, sys.path, or notify globals.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import errno
import fcntl
import html
import http.client
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import re
import smtplib
import socket
import stat
import subprocess
import urllib.request

import pytest


# digest_state 已移除:main 已把 digest 写路径(path 5)从 `_chmod_like_target`
# 重构到独立函数 `_write_digest_delivery_state`(硬编码 0600、不走 _chmod_like_target),
# 故该组对 P2-01 的 _chmod_like_target strict fix 已 N/A;新函数的 0600/strict 语义
# 由 main 自有测试覆盖,不再纳入本 closeout 回归参数化。
WRITERS = ("result", "latest", "state", "warning_dedup")
OLD_BYTES = b'{"last_sent_day":"","marker":"old-bytes"}\n'
OLD = {"key": "closeout_old_key", "subject": "OLD_SUBJECT_TOKEN",
       "body": "OLD_BODY_TOKEN", "hits": 2}
NEW = {"key": "closeout_new_key", "subject": "NEW_SUBJECT_TOKEN",
       "body": "NEW_BODY_TOKEN", "hits": 3}


@contextmanager
def _umask(mask):
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


@contextmanager
def _locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@pytest.fixture
def isolated_notify(tmp_path, monkeypatch):
    """No credentials/config outside tmp_path; channel stubs also survive fork."""
    for key in tuple(os.environ):
        if key.startswith(("ALERT_", "NOTIFY_", "FEISHU_", "EMAIL_", "TELEGRAM_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setenv("GIT_REPO", str(tmp_path))
    guard_log = tmp_path / "unexpected-outbound.jsonl"

    def forbidden(*_args, **_kwargs):
        with guard_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "blocked": True}) + "\n")
        raise AssertionError("closeout: unexpected outbound/process execution")

    for owner, name in (
        (urllib.request, "urlopen"), (smtplib, "SMTP"), (smtplib, "SMTP_SSL"),
        (http.client.HTTPConnection, "connect"),
        (http.client.HTTPSConnection, "connect"),
        (socket, "getaddrinfo"), (socket, "gethostbyname"),
        (socket.socket, "connect"), (socket.socket, "connect_ex"),
        (socket.socket, "sendto"), (subprocess, "Popen"), (os, "system"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    # Positive control before any business call; later hits are never erased.
    with pytest.raises(AssertionError, match="unexpected outbound"):
        urllib.request.urlopen("https://invalid.example/closeout-control")
    assert guard_log.exists()
    guard_log.unlink()

    scripts = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("_closeout_notify", scripts / "notify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Every module-level runtime Path is derived from fixture REPO, including
    # configs, buffers, dedup, state, locks and ledgers; fail if that changes.
    for name, value in vars(mod).items():
        if isinstance(value, Path):
            assert value.is_relative_to(tmp_path), (name, value)

    class FixtureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2035, 1, 2, 23, 30, tzinfo=tz)

    monkeypatch.setattr(mod, "datetime", FixtureClock)
    monkeypatch.setattr(mod, "ALERT_DIGEST_HM", "00:00")
    mod.ALERTS_DIR.mkdir(parents=True)
    payload_file = tmp_path / "channel-payloads.jsonl"

    def channel(kind):
        def record(subject, body, *_args, **_kwargs):
            with payload_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"channel": kind, "subject": subject,
                                         "body": body, "pid": os.getpid()}) + "\n")
            return True
        return record

    for attr, kind in (("_send_email", "email"), ("send_telegram", "telegram"),
                       ("send_feishu", "feishu")):
        monkeypatch.setattr(mod, attr, channel(kind))
    try:
        yield mod, tmp_path, payload_file
    finally:
        assert not guard_log.exists(), "outbound trap fired (including a forked child)"


def _seed(mod, records):
    entries = [dict(record, ts=mod.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    day=mod.datetime.now().strftime("%Y-%m-%d"),
                    rid="seed-" + record["key"], category="r2", source="closeout",
                    reason=mod.DIGEST_WARNING_BATCH_REASON) for record in records]
    mod.ALERT_DIGEST_FILE.write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")


def _writer(mod, root, name):
    """Real writer plus its temporary target and expected successful content."""
    obj = {"closeout": "new-value"}
    if name == "result":
        target = root / "result.json"
        mod._mark_outcome("sent", "closeout", channels={"email": True})
        return target, lambda: mod._write_result_file(str(target)), mod._OUTCOME
    if name == "latest":
        def write_latest():
            with _locked(mod.ALERTS_DIR / ".latest.lock"):
                return mod._replace_latest("NEW_LATEST_TOKEN")
        return mod.ALERTS_FILE, write_latest, "NEW_LATEST_TOKEN"
    if name == "state":
        target = root / "state.json"
        return target, lambda: mod._write_state_obj(target, obj), obj
    if name == "warning_dedup":
        def write_warning():
            with mod._dedup_state_lock():
                return mod._save_warning_dedup_state(obj)
        return mod.WARNING_DEDUP_STATE_FILE, write_warning, obj
    assert name == "digest_state"
    _seed(mod, [OLD])
    return (mod.ALERT_DIGEST_STATE_FILE, mod.flush_digest,
            {"last_sent_day": mod.datetime.now().strftime("%Y-%m-%d")})


def _assert_content(target, expected):
    text = target.read_text(encoding="utf-8")
    assert (text if isinstance(expected, str) else json.loads(text)) == expected


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("mode", [0o600, 0o640], ids=["0600", "0640"])
@pytest.mark.parametrize("fault", ["stat", "chmod"])
def test_metadata_error_keeps_existing_bytes_and_mode(
        isolated_notify, monkeypatch, writer, mode, fault):
    """Desired contract: metadata-copy failure must prevent publication."""
    mod, root, _ = isolated_notify
    target, write, _ = _writer(mod, root, writer)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(OLD_BYTES)
    target.chmod(mode)
    original_copy = mod._chmod_like_target
    original_syscall = getattr(os, fault)
    injected = []

    def copy_with_fault(tmp, destination):
        if Path(destination) != target:
            return original_copy(tmp, destination)

        def fail_selected_path(path, *args, **kwargs):
            selected = target if fault == "stat" else Path(tmp)
            if Path(path) == selected:
                injected.append(fault)
                raise OSError(errno.EACCES if fault == "stat" else errno.EPERM,
                              "closeout metadata fault")
            return original_syscall(path, *args, **kwargs)

        # Limit injection to the real metadata helper, not Path.exists(),
        # file reading, pytest internals, or another writer's state operation.
        with monkeypatch.context() as local:
            local.setattr(os, fault, fail_selected_path)
            return original_copy(tmp, destination)

    monkeypatch.setattr(mod, "_chmod_like_target", copy_with_fault)
    with _umask(0o022):
        try:
            write()
        except OSError as exc:
            # _replace_latest has no outer error handler; abort is allowed.
            assert exc.errno in (errno.EACCES, errno.EPERM)
    assert injected, "negative control must reach the real metadata-copy syscall"
    observed = (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))
    assert observed == (OLD_BYTES, mode), (
        f"{writer}/{fault}: failed metadata copy published bytes/mode: {observed!r}")


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("mode", [0o600, 0o640], ids=["0600", "0640"])
def test_successful_writer_preserves_existing_mode(isolated_notify, writer, mode):
    mod, root, _ = isolated_notify
    target, write, expected = _writer(mod, root, writer)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(OLD_BYTES)
    target.chmod(mode)
    with _umask(0o022):
        write()
    _assert_content(target, expected)
    assert stat.S_IMODE(target.stat().st_mode) == mode


@pytest.mark.parametrize("writer", WRITERS)
@pytest.mark.parametrize("mask", [0o022, 0o027], ids=["umask022", "umask027"])
def test_missing_target_keeps_original_creation_default(isolated_notify, writer, mask):
    """Real stat FileNotFoundError is a valid creation case, not an error."""
    mod, root, _ = isolated_notify
    target, write, expected = _writer(mod, root, writer)
    assert not target.exists()
    with _umask(mask):
        write()
    _assert_content(target, expected)
    default = 0o600 if writer == "warning_dedup" else 0o666 & ~mask
    assert stat.S_IMODE(target.stat().st_mode) == default


@pytest.mark.parametrize("mode", [0o600, 0o640], ids=["0600", "0640"])
def test_atomic_digest_real_fchmod_control(isolated_notify, monkeypatch, mode):
    mod, _, _ = isolated_notify
    _seed(mod, [OLD])
    mod.ALERT_DIGEST_FILE.chmod(mode)
    original = os.fchmod
    applied = []

    def spy(fd, copied_mode):
        applied.append(copied_mode)
        return original(fd, copied_mode)

    monkeypatch.setattr(os, "fchmod", spy)
    assert mod._absorb_to_digest(NEW["subject"], NEW["body"], key=NEW["key"],
                                 category="r2", bump_hits=True)
    assert applied == [mode]
    assert stat.S_IMODE(mod.ALERT_DIGEST_FILE.stat().st_mode) == mode
    assert {e["key"] for e in _buffer(mod)} == {OLD["key"], NEW["key"]}


@pytest.mark.parametrize("mode", [0o600, 0o640], ids=["0600", "0640"])
def test_atomic_digest_fchmod_failure_is_strict(isolated_notify, monkeypatch, mode):
    mod, _, _ = isolated_notify
    _seed(mod, [OLD])
    mod.ALERT_DIGEST_FILE.chmod(mode)
    before = mod.ALERT_DIGEST_FILE.read_bytes()
    invoked = []

    def fail(_fd, _mode):
        invoked.append(True)
        raise OSError(errno.EPERM, "closeout fchmod fault")

    monkeypatch.setattr(os, "fchmod", fail)
    assert not mod._absorb_to_digest(NEW["subject"], NEW["body"], key=NEW["key"],
                                     category="r2", bump_hits=True)
    assert invoked
    assert mod.ALERT_DIGEST_FILE.read_bytes() == before
    assert stat.S_IMODE(mod.ALERT_DIGEST_FILE.stat().st_mode) == mode
    assert not list(mod.ALERTS_DIR.glob("*.tmp.*"))


@pytest.mark.parametrize("mask", [0o022, 0o027], ids=["umask022", "umask027"])
def test_atomic_digest_new_file_default(isolated_notify, mask):
    mod, _, _ = isolated_notify
    assert not mod.ALERT_DIGEST_FILE.exists()
    with _umask(mask):
        assert mod._absorb_to_digest(NEW["subject"], NEW["body"], key=NEW["key"],
                                     category="r2", bump_hits=True)
    assert stat.S_IMODE(mod.ALERT_DIGEST_FILE.stat().st_mode) == 0o666 & ~mask


def _buffer(mod):
    return [json.loads(line) for line in mod.ALERT_DIGEST_FILE.read_text().splitlines()
            if line.strip()]


def _assert_conservation(payloads, buffered, order, worker_pid):
    """Expected totals come from our inputs, independently of buffer cleanup."""
    expected = {entry["key"]: entry for entry in (OLD, NEW)}
    retained = Counter()
    for entry in buffered:
        assert entry["key"] in expected
        fixture = expected[entry["key"]]
        assert (entry["subject"], entry["body"]) == (fixture["subject"], fixture["body"])
        retained[entry["key"]] += entry["hits"]
    assert Counter(p["channel"] for p in payloads) == {
        "email": 1, "telegram": 1, "feishu": 1}
    for payload in payloads:
        assert payload["pid"] == worker_pid, "payload must come from the sending process"
        text = html.unescape(payload["body"])
        delivered = Counter()
        for key, fixture in expected.items():
            marker = ":" + key
            if marker in text:
                assert text.count(marker) == 1, "duplicate payload row"
                match = re.search(re.escape(marker) + r"(?: x(\d+))?", text)
                delivered[key] = int(match.group(1) or 1)
                assert fixture["subject"] in text and fixture["body"] in text
        assert delivered + retained == Counter({k: v["hits"] for k, v in expected.items()}), (
            f"payload/buffer conservation failed: delivered={delivered}, retained={retained}")
        assert delivered == ({OLD["key"]: 2, NEW["key"]: 3}
                             if order == "absorb-first" else {OLD["key"]: 2})
    assert retained == ({} if order == "absorb-first" else {NEW["key"]: 3})


def _ordered_processes(mod, root, payload_file, order, drop_new=False):
    """Hold the first worker's real critical section until the contender starts."""
    ctx = multiprocessing.get_context("fork")  # repository runtime: macOS/Linux
    entered, release, started = ctx.Event(), ctx.Event(), ctx.Event()
    absorb_done, flush_done = ctx.Event(), ctx.Event()
    _seed(mod, [OLD])
    mod.ALERT_DIGEST_FILE.chmod(0o640)

    def absorb():
        original = mod._atomic_write_digest
        calls = 0

        def hold_last_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == NEW["hits"]:
                entered.set()  # _absorb_to_digest already owns the sidecar lock
                assert release.wait(10), "absorb release timed out"
            return original(*args, **kwargs)

        if order == "absorb-first":
            mod._atomic_write_digest = hold_last_write  # child-local only
        else:
            started.set()
        for _ in range(NEW["hits"]):
            assert mod._absorb_to_digest(
                NEW["subject"], NEW["body"], key=NEW["key"], category="r2",
                source="closeout", reason=mod.DIGEST_WARNING_BATCH_REASON, bump_hits=True)
        absorb_done.set()

    def flush():
        original = mod._flush_digest_locked

        def hold_flush(*args, **kwargs):
            entered.set()  # flush_digest already owns the same sidecar lock
            assert release.wait(10), "flush release timed out"
            return original(*args, **kwargs)

        if order == "flush-first":
            mod._flush_digest_locked = hold_flush  # child-local only
        else:
            started.set()
        if drop_new:
            # Runtime negative control: remove the new row/body at channel boundary,
            # while the real flusher still clears both entries after success.
            for attr in ("_send_email", "send_telegram", "send_feishu"):
                record = getattr(mod, attr)

                def omit(subject, body, *args, _record=record, **kwargs):
                    body = "<br>".join(part for part in body.split("<br>")
                                       if NEW["key"] not in part and NEW["body"] not in part)
                    return _record(subject, body, *args, **kwargs)

                setattr(mod, attr, omit)
        result = mod.flush_digest()
        assert result["sent"] is True
        assert result["n"] == (2 if order == "absorb-first" else 1)
        flush_done.set()

    absorber, flusher = ctx.Process(target=absorb), ctx.Process(target=flush)
    first, second = (absorber, flusher) if order == "absorb-first" else (flusher, absorber)
    contender_done = flush_done if order == "absorb-first" else absorb_done
    processes = [first, second]
    sending_pid = None
    try:
        first.start()
        assert entered.wait(10), "first worker never reached its locked section"
        second.start()
        assert started.wait(10), "contender did not start"
        assert not contender_done.wait(0.15), "contender escaped the held sidecar lock"
        release.set()
        for process in processes:
            process.join(12)
            assert process.exitcode == 0, f"child exit={process.exitcode}"
        assert absorb_done.is_set() and flush_done.is_set()
        sending_pid = flusher.pid
    finally:
        release.set()
        for process in processes:
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                process.join(3)
                if process.is_alive():
                    process.kill()
                    process.join(3)
                assert not process.is_alive(), "child leaked after test"
            process.close()
    assert stat.S_IMODE(mod.ALERT_DIGEST_FILE.stat().st_mode) == 0o640
    payloads = [json.loads(line) for line in payload_file.read_text().splitlines()]
    return payloads, _buffer(mod), sending_pid


@pytest.mark.parametrize("order", ["absorb-first", "flush-first"])
def test_fixed_order_payload_and_buffer_conservation(isolated_notify, order):
    mod, root, payload_file = isolated_notify
    payloads, buffered, pid = _ordered_processes(mod, root, payload_file, order)
    _assert_conservation(payloads, buffered, order, pid)


def test_lost_new_payload_is_rejected_by_conservation(isolated_notify):
    mod, root, payload_file = isolated_notify
    payloads, buffered, pid = _ordered_processes(
        mod, root, payload_file, "absorb-first", drop_new=True)
    assert buffered == [], "negative control must reproduce empty-buffer false green"
    with pytest.raises(AssertionError, match="conservation failed"):
        _assert_conservation(payloads, buffered, "absorb-first", pid)
