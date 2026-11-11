"""Real CLI -> warning/digest/outbox -> transport, with isolated state and no network.

Run with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest --noconftest. No production
conftest, credentials, collectors or notification endpoints are used.
"""
import builtins
import http.client
import importlib.util
import io
import json
import multiprocessing
import os
from pathlib import Path
import smtplib
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from email import message_from_string

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


@pytest.fixture
def box(tmp_path, monkeypatch):
    traps = []

    def deny(*args, **kwargs):
        traps.append("external")
        raise AssertionError("external network/process forbidden")

    def guarded(real):
        def call(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(file)).absolute()
                if path.name == ".env" or (path.name in ("email.json", "telegram.json", "feishu.json") and not path.is_relative_to(tmp_path)):
                    traps.append("credential")
                    raise AssertionError("production credentials forbidden")
            return real(file, *args, **kwargs)
        return call

    for obj, key in [(socket, "create_connection"), (socket, "getaddrinfo"),
                     (socket.socket, "connect"), (socket.socket, "connect_ex"),
                     (urllib.request, "urlopen"), (smtplib, "SMTP"), (smtplib, "SMTP_SSL"),
                     (http.client.HTTPConnection, "connect"), (http.client.HTTPSConnection, "connect"),
                     (subprocess, "Popen"), (os, "system")]:
        monkeypatch.setattr(obj, key, deny)
    monkeypatch.setattr(builtins, "open", guarded(builtins.open))
    monkeypatch.setattr(io, "open", guarded(io.open))
    for f in [lambda: socket.create_connection(("invalid.example", 443)),
              lambda: urllib.request.urlopen("https://invalid.example"),
              lambda: smtplib.SMTP_SSL("invalid.example"),
              lambda: subprocess.Popen(["false"]), lambda: Path("/forbidden/.env").read_text()]:
        with pytest.raises(AssertionError):
            f()
    assert len(traps) == 5
    traps.clear()
    for k in ("REPO", "GIT_REPO", "MAIN_REPO"):
        monkeypatch.setenv(k, str(tmp_path))
    for k in ("ALERT_LEDGER_DISABLE", "ALERT_BUDGET_DISABLE", "ALERT_DIGEST_DISABLE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("quiet_notify", SCRIPTS / "notify.py")
    n = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(n)
    clock = [datetime(2026, 11, 11, 10, 0)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    n.datetime = Clock
    cfg = {"enabled": True, "mode": "app", "chat_ids": {"report": "offline-report", "alert": "offline-alert"}}
    monkeypatch.setattr(n, "load_feishu_config", lambda: cfg)
    monkeypatch.setattr(n, "_load_feishu_credentials", lambda: ("", ""))
    monkeypatch.setattr(n, "_get_tenant_access_token", lambda: "offline-token")
    monkeypatch.setattr(n, "load_email_config", lambda: {"smtp": "offline", "user": "offline@example.test", "password": "offline-test", "to": "offline@example.test"})
    monkeypatch.setattr(n, "load_telegram_config", lambda: {"bot_token": "offline", "chat_id": "offline"})
    monkeypatch.setattr(n, "telegram_configured", lambda: True)
    wire, accepted = [], dict.fromkeys(n.OPS_CHANNELS, True)
    wire_path = tmp_path / "wire.jsonl"

    def transport(channel, body):
        value = accepted[channel]
        ok = value(body) if callable(value) else value
        rec = {"channel": channel, "body": body, "accepted": ok}
        wire.append(rec)
        with wire_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return ok

    class SMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def sendmail(self, sender, recipients, text):
            body = message_from_string(text).get_payload(decode=True).decode()
            if not transport("email", body):
                raise smtplib.SMTPRecipientsRefused({"offline@example.test": (550, "offline rejected")})
            return {}

    def urlopen(req, **kw):
        assert "api.telegram.org/botoffline/" in req.full_url
        return io.BytesIO(json.dumps({"ok": transport("telegram", json.loads(req.data)["text"])}).encode())

    def feishu(url, payload, headers):
        return {"code": 0 if transport("feishu", json.loads(payload)) else 99901}

    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(n, "_feishu_http_post_json", feishu)
    n.ALERTS_DIR.mkdir(parents=True)
    state_path = tmp_path / "data/alert_state.json"

    def seed(event="e1", key="task|condition", status="active", action=True, **extra):
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state[key] = {"event_id": event, "source_run": "run-A", "status": status,
                      "requires_action": action, **extra}
        state_path.write_text(json.dumps(state))
        return [{"key": key, "event_id": event, "phase": "active", "source_run": "run-A"}]

    def state():
        return json.loads(state_path.read_text())

    def update(ref, **kw):
        data = state()
        data[ref[0]["key"]].update(kw)
        state_path.write_text(json.dumps(data))

    def cli(refs=None, tier=None, **kw):
        args = [kw.pop("subject", "[告警] offline fixture"), kw.pop("body", "COMPLETE BODY")]
        if refs is not None:
            args += ["--ops-event-refs", json.dumps(refs)]
        if tier:
            args += ["--tier", tier]
        args += kw.pop("args", [])
        assert not kw
        result = tmp_path / "result.json"
        n.main(args + ["--result-file", str(result)])
        return json.loads(result.read_text())

    yield n, clock, cfg, wire, accepted, seed, state, update, cli, tmp_path
    assert not traps


def test_unnotified_warning_heals_before_flush(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    ref = seed()
    assert cli(ref, "warning")["status"] == "deferred"
    assert not wire
    update(ref, status="recovered", requires_action=False)
    clock[0] = datetime(2026, 11, 11, 23, 30)
    n.main(["--flush-warnings"])
    n.main(["--flush-digest"])
    assert not wire
    assert "notified_at" not in state()[ref[0]["key"]]
    assert "verified no action required" in n.INFO_LOG_FILE.read_text()


def test_all_failed_first_no_recovery_and_failure_ledger(box):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    accepted.update(dict.fromkeys(accepted, False))
    first = cli(ref, "critical")
    assert first["status"] == "failed"
    assert first["attempted_channels"] == list(n.OPS_CHANNELS)
    row = json.loads(n._ledger_path().read_text().splitlines()[-1])
    assert row["ops_event_refs"] == ref and not any(row["channels"].values())
    assert row["attempt_id"] == first["attempt_id"]
    accepted.update(dict.fromkeys(accepted, True))
    update(ref, status="recovered", requires_action=False)
    rec = [{**ref[0], "phase": "recovery"}]
    before = len(wire)
    assert cli(rec)["status"] == "suppressed"
    assert len(wire) == before and "notified_at" not in state()[ref[0]["key"]]


def test_pair_recovery_only_accepted_channels_and_once(box):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    accepted.update(telegram=False, feishu=False)
    assert cli(ref, "critical")["status"] == "partial"
    assert state()[ref[0]["key"]]["notified_channels"] == {"email": True, "telegram": False, "feishu": False}
    # Time window expiry never repeats the same event's first alert.
    clock[0] = datetime(2026, 12, 20, 10)
    before = len(wire)
    assert cli(ref, "critical", args=["--dedup-window", "0"])["status"] == "partial"
    assert [r["channel"] for r in wire[before:]] == ["telegram", "feishu"]
    before = len(wire)
    update(ref, status="recovered", requires_action=False)
    accepted.update(telegram=True, feishu=True)
    rec = [{**ref[0], "phase": "recovery"}]
    assert cli(rec)["status"] == "sent"
    assert [r["channel"] for r in wire[before:]] == ["email"]
    assert cli(rec)["status"] == "suppressed"
    assert len(wire) == before + 1


def test_new_event_supersedes_buffer_and_does_not_inherit_receipts(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    old = seed()
    cli(old, "warning", body="OLD_SECRET_BODY")
    new = seed(event="e2", ack_by="new-owner")
    clock[0] = datetime(2026, 11, 11, 23, 30)
    n.flush_warning_batch()
    n.flush_digest()
    assert not wire and "superseded" in n.INFO_LOG_FILE.read_text()
    assert cli(new, "critical")["status"] == "sent"
    assert state()[new[0]["key"]]["ack_by"] == "new-owner"
    assert all("OLD_SECRET_BODY" not in str(w) for w in wire)


def test_real_warning_digest_receipt_survives_another_sender_instance(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    ref = seed()
    ref[0]["source_run"] = None
    assert cli(ref, "warning")["status"] == "deferred"
    clock[0] = datetime(2026, 11, 11, 23, 30)
    assert n.flush_warning_batch()["digested"]
    assert not wire
    n._OUTCOME = {}  # no source process/result-file receipt is used
    assert n.flush_digest()["sent"]
    assert len(wire) == 3
    st = state()[ref[0]["key"]]
    assert st["notified_event_id"] == "e1" and all(st["notified_channels"].values())
    row = json.loads(n._ledger_path().read_text().splitlines()[-1])
    assert row["ops_event_refs"][0]["source_run"] is None
    assert set(row["attempted_channels"]) == set(n.OPS_CHANNELS)


def test_mixed_buffer_removes_entire_quiet_body_keeps_fault_and_legacy(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    healed = seed(key="heal")
    active = seed(key="fault")
    for ref, body in [(healed, "HEALED_BODY"), (active, "ACTION_BODY")]:
        cli(ref, "warning", body=body)
    update(healed, status="recovered", requires_action=False)
    n._absorb_to_digest("legacy business", "LEGACY_BODY", key="legacy", category="business")
    clock[0] = datetime(2026, 11, 11, 23, 30)
    n.flush_warning_batch()
    n.flush_digest()
    n.flush_digest()
    assert any("ACTION_BODY" in str(x) for x in wire)
    assert any("legacy business" in str(x) for x in wire)
    assert all("HEALED_BODY" not in str(x) for x in wire)


@pytest.mark.parametrize("change", ["heal", "supersede"])
def test_partial_pending_rechecked_before_retry(box, change):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    accepted.update(email=False, telegram=False)
    count = [0]
    def fs(body):
        count[0] += 1
        return count[0] == 1
    accepted["feishu"] = fs
    clock[0] = datetime(2026, 11, 11, 23, 30)
    cli(ref, args=["--defer-digest"], body="LARGE_BODY" * 7000)
    assert not n.flush_digest()["sent"]
    pending = json.loads(n.ALERT_DIGEST_STATE_FILE.read_text())["pending_delivery"]
    assert pending["confirmed_parts"] == [0] and not pending["complete"]
    assert "notified_event_id" not in state()[ref[0]["key"]]
    if change == "heal":
        update(ref, status="recovered", requires_action=False)
    else:
        seed(event="e2")
    before = len(wire)
    n.flush_digest()
    assert len(wire) == before
    assert "pending_delivery" not in json.loads(n.ALERT_DIGEST_STATE_FILE.read_text())


def test_pending_resume_full_content_no_duplicate_email(box):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    accepted["feishu"] = False
    clock[0] = datetime(2026, 11, 11, 23, 30)
    cli(ref, args=["--defer-digest"], body="FULL_TAIL_" * 4000)
    assert n.flush_digest()["status"] == "partial"
    assert state()[ref[0]["key"]]["notified_channels"]["feishu"] is False
    before = len(wire)
    accepted["feishu"] = True
    assert n.flush_digest()["sent"]
    assert all(x["channel"] == "feishu" for x in wire[before:])
    assert state()[ref[0]["key"]]["notified_channels"]["feishu"] is True


@pytest.mark.parametrize("mode", ["missing", "corrupt", "unknown_action"])
def test_unknown_is_visible_not_recovery_or_fake_health(box, mode):
    n, clock, _, wire, _, seed, state, update, cli, root = box
    ref = seed()
    if mode == "missing":
        (root / "data/alert_state.json").unlink()
    elif mode == "corrupt":
        (root / "data/alert_state.json").write_text("{bad")
    else:
        update(ref, requires_action=None)
    result = cli(ref, "critical")
    assert result["status"] == ("sent" if mode == "unknown_action" else "unknown")
    before = len(wire)
    rec = [{**ref[0], "phase": "recovery"}]
    assert cli(rec)["status"] == "unknown"
    assert len(wire) == before and "unknown" in n.INFO_LOG_FILE.read_text()


def test_business_legacy_status_compat_and_actual_delivery_field(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    info = cli(tier="info")
    warning = cli(tier="warning")
    assert info["status"] == warning["status"] == "sent"
    assert info["delivery_status"] == "noop" and warning["delivery_status"] == "deferred"
    assert not wire
    cli(subject="业务订阅日报", body="BUSINESS_BODY", args=["--feishu-group", "report"])
    assert any("BUSINESS_BODY" in str(x) for x in wire)


def test_missing_feishu_config_once_and_new_incident_after_repair(box, monkeypatch):
    n, clock, cfg, wire, accepted, seed, state, update, cli, _ = box
    monkeypatch.setattr(n, "load_feishu_config", lambda: None)
    monkeypatch.setattr(n, "_load_feishu_credentials", lambda: ("offline-id", "offline-secret"))
    n.send_feishu("business", "body")
    assert [x["channel"] for x in wire] == ["email"]
    incident = state()["feishu_config_missing"]["event_id"]
    clock[0] = datetime(2026, 12, 20, 10)
    n.send_feishu("business", "body")
    assert len(wire) == 1
    monkeypatch.setattr(n, "load_feishu_config", lambda: cfg)
    n.send_feishu("business", "body", chat_key="report")
    monkeypatch.setattr(n, "load_feishu_config", lambda: None)
    n.send_feishu("business", "body")
    assert state()["feishu_config_missing"]["event_id"] != incident
    assert sum(x["channel"] == "email" for x in wire) == 2


def test_concurrent_process_claim_only_one_first_send(box):
    n, clock, _, wire, accepted, seed, state, update, cli, root = box
    ref = seed()
    ctx = multiprocessing.get_context("fork")
    entered, release = ctx.Event(), ctx.Event()
    def slow(body):
        entered.set()
        assert release.wait(10)
        return True
    accepted["email"] = slow
    def worker(name):
        result = n.send_tiered("fault", "body", ops_event_refs=ref)
        (root / name).write_text(json.dumps(result))
    first = ctx.Process(target=worker, args=("first.json",))
    second = ctx.Process(target=worker, args=("second.json",))
    try:
        first.start()
        assert entered.wait(10)
        second.start()
        second.join(10)
        assert second.exitcode == 0
        assert json.loads((root / "second.json").read_text())["status"] == "deferred"
        # Simulate ACK writer while network is blocked: lock is available.
        with n._ops_state_lock():
            data = n._ops_read_state()
            data[ref[0]["key"]]["ack_by"] = "operator"
            n._ops_write_state(data)
        release.set()
        first.join(10)
        assert first.exitcode == 0
    finally:
        release.set()
        for p in (first, second):
            if p.pid and p.is_alive():
                p.kill()
            if p.pid:
                p.join(5)
    rows = [json.loads(l) for l in (root / "wire.jsonl").read_text().splitlines()]
    assert [r["channel"] for r in rows] == list(n.OPS_CHANNELS)
    assert state()[ref[0]["key"]]["ack_by"] == "operator"
    assert "notification_claim" not in state()[ref[0]["key"]]


def test_expired_claim_unknown_audit_retry_and_dry_run_zero_write(box):
    n, clock, _, wire, _, seed, state, update, cli, root = box
    ref = seed(notification_claim={"event_id": "e1", "phase": "active", "attempt_id": "lost", "expires_at": 1})
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert n.send_tiered("fault", "body", dry_run=True, ops_event_refs=ref)["status"] == "dry_run"
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before and not wire
    assert cli(ref, "critical")["status"] == "sent"
    assert "expired claim" in n.INFO_LOG_FILE.read_text()


def test_mixed_opaque_refs_fail_without_transport(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    refs = seed() + seed(event="e2", key="other")
    assert cli(refs, "critical")["status"] == "failed"
    assert not wire


def test_unknown_active_is_not_hidden_forever_in_broken_state(box):
    n, clock, _, wire, _, seed, state, update, cli, root = box
    ref = seed()
    (root / "data/alert_state.json").write_text("{broken")
    result = cli(ref, "critical")
    assert result["status"] == "unknown" and result["retained_in_outbox"]
    assert not wire
    clock[0] = datetime(2026, 11, 11, 23, 30)
    assert n.flush_digest()["sent"]
    assert len(wire) == 3
    assert (root / "data/alert_state.json").read_text() == "{broken"
    assert "outbox-serialized fault delivery" in n.INFO_LOG_FILE.read_text()


def test_receipt_write_failure_is_visible_no_claimed_state_success(box, monkeypatch):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    ref = seed()
    original = n._ops_write_state
    calls = [0]
    def fail_after_claim(data):
        calls[0] += 1
        if calls[0] > 1:
            raise OSError("offline disk full")
        original(data)
    monkeypatch.setattr(n, "_ops_write_state", fail_after_claim)
    result = cli(ref, "critical")
    assert result["status"] == "sent" and not result["receipt_persisted"]
    assert len(wire) == 3
    assert "notified_at" not in state()[ref[0]["key"]]
    assert state()[ref[0]["key"]]["notification_claim"]
    assert "receipt persistence failed" in n.INFO_LOG_FILE.read_text()


def test_async_actual_process_merges_receipt_not_source_result(box):
    n, clock, _, wire, _, seed, state, update, cli, root = box
    ref = seed()
    assert cli(ref, "warning")["status"] == "deferred"
    clock[0] = datetime(2026, 11, 11, 23, 30)
    ctx = multiprocessing.get_context("fork")
    def flush():
        n.main(["--flush-warnings"])
        n.main(["--flush-digest"])
    process = ctx.Process(target=flush)
    try:
        process.start()
        process.join(10)
        assert process.exitcode == 0
    finally:
        if process.pid and process.is_alive():
            process.kill()
        if process.pid:
            process.join(5)
    assert not wire  # parent transport memory didn't participate
    assert len((root / "wire.jsonl").read_text().splitlines()) == 3
    assert state()[ref[0]["key"]]["notified_event_id"] == "e1"


def test_legacy_unverified_pending_not_silenced(box):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    clock[0] = datetime(2026, 11, 11, 23, 30)
    accepted["feishu"] = False
    n._absorb_to_digest("legacy ops or business unknown", "PRESERVE_BODY", key="legacy", category="unmapped")
    n.flush_digest()
    assert json.loads(n.ALERT_DIGEST_STATE_FILE.read_text())["pending_delivery"]
    accepted["feishu"] = True
    before = len(wire)
    n.flush_digest()
    assert len(wire) > before


def test_config_missing_failed_email_retries_and_no_unconfigured_noise(box, monkeypatch):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    monkeypatch.setattr(n, "load_feishu_config", lambda: None)
    n.send_feishu("business", "body")
    assert not wire
    monkeypatch.setattr(n, "_load_feishu_credentials", lambda: ("offline-id", "offline-secret"))
    accepted["email"] = False
    n.send_feishu("business", "body")
    assert "notified_at" not in state()["feishu_config_missing"]
    accepted["email"] = True
    n.send_feishu("business", "body")
    assert state()["feishu_config_missing"]["notified_channels"]["email"]
    assert [r["channel"] for r in wire] == ["email", "email"]


def test_phase_receipts_once_and_late_old_receipt_cannot_touch_new_event(box):
    n, clock, _, wire, accepted, seed, state, update, cli, root = box
    ref = seed()
    cli(ref, "critical")
    esc = [{**ref[0], "phase": "escalation"}]
    assert cli(esc, "critical")["status"] == "sent"
    assert cli(esc, "critical")["status"] == "suppressed"
    assert len(wire) == 6
    new = seed(event="e2", ack_by="new-owner")
    assert not n._ops_receipt(ref, {"attempt_id": "late"}, {"email": True}, ["email"], "sent")
    assert state()[new[0]["key"]] == {"event_id": "e2", "source_run": "run-A", "status": "active", "requires_action": True, "ack_by": "new-owner"}


def test_notified_flag_without_actual_channel_cannot_silence_fault(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    ref = seed(notified_event_id="e1", notified_at="old", notified_channels={"email": False, "deferred": True})
    assert cli(ref, "critical")["status"] == "sent"
    assert len(wire) == 3


def test_recovery_only_feishu_and_partial_chunk_not_full_receipt(box):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    accepted.update(email=False, telegram=False)
    assert cli(ref, "critical")["status"] == "partial"
    update(ref, status="recovered", requires_action=False)
    rec = [{**ref[0], "phase": "recovery"}]
    before = len(wire)
    assert cli(rec)["status"] == "sent"
    assert [w["channel"] for w in wire[before:]] == ["feishu"]


def test_unknown_recovery_does_not_remove_other_active_buffer_item(box):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    first = seed(key="unknown")
    cli(first, "critical")
    update(first, status="recovered", requires_action=False)
    rec = [{**first[0], "phase": "recovery"}]
    cli(rec, args=["--defer-digest"], body="UNVERIFIED_RECOVERY")
    update(first, status="active", requires_action=True)
    active = seed(key="live")
    cli(active, args=["--defer-digest"], body="LIVE_FAULT")
    before = len(wire)
    clock[0] = datetime(2026, 11, 11, 23, 30)
    assert n.flush_digest()["sent"]
    assert any("LIVE_FAULT" in str(w) for w in wire[before:])
    assert all("UNVERIFIED_RECOVERY" not in str(w) for w in wire[before:])
    assert "UNVERIFIED_RECOVERY" in n.ALERT_DIGEST_FILE.read_text()


def test_config_compensation_shares_monitor_event_no_nested_duplicate(box, monkeypatch):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed(key="feishu_config_missing", event="monitor-event")
    monkeypatch.setattr(n, "load_feishu_config", lambda: None)
    monkeypatch.setattr(n, "_load_feishu_credentials", lambda: ("offline-id", "offline-secret"))
    assert cli(ref, "critical")["status"] == "partial"
    assert [r["channel"] for r in wire] == ["email", "telegram"]
    assert state()[ref[0]["key"]]["event_id"] == "monitor-event"
    assert len(n._ledger_path().read_text().splitlines()) == 1


def test_readable_but_disabled_config_is_not_proven_repair(box, monkeypatch):
    n, clock, cfg, wire, accepted, seed, state, update, cli, _ = box
    monkeypatch.setattr(n, "load_feishu_config", lambda: None)
    monkeypatch.setattr(n, "_load_feishu_credentials", lambda: ("offline-id", "offline-secret"))
    n.send_feishu("business", "body")
    cfg["enabled"] = False
    monkeypatch.setattr(n, "load_feishu_config", lambda: cfg)
    n.send_feishu("business", "body")
    assert state()["feishu_config_missing"]["status"] == "active"
    assert len(wire) == 1


@pytest.mark.parametrize("phase", ["active", "recovery", "escalation"])
def test_partial_phase_retries_only_unconfirmed_channels(box, phase):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    if phase != "active":
        assert cli(ref, "critical")["status"] == "sent"
    if phase == "recovery":
        update(ref, status="recovered", requires_action=False)
    ref = [{**ref[0], "phase": phase}]
    accepted.update(telegram=False, feishu=False)
    assert cli(ref)["status"] == "partial"
    before = len(wire)
    accepted.update(telegram=True, feishu=True)
    result = cli(ref)
    assert result["status"] == "sent"
    assert result["channels"]["email"] is False  # this attempt, not the old receipt
    assert all(result["cumulative_channels"].values())
    assert [r["channel"] for r in wire[before:]] == ["telegram", "feishu"]
    row = json.loads(n._ledger_path().read_text().splitlines()[-1])
    assert row["channels"] == {"email": False, "telegram": True, "feishu": True}
    assert row["attempted_channels"] == ["telegram", "feishu"]
    assert cli(ref)["status"] == "suppressed"
    assert len(wire) == before + 2


@pytest.mark.parametrize("channel", ["email", "telegram", "feishu"])
def test_response_lost_remains_unknown_in_result_state_and_ledger(box, monkeypatch, channel):
    n, clock, _, wire, accepted, seed, state, update, cli, _ = box
    ref = seed()
    accepted.update(dict.fromkeys(accepted, False))
    accepted[channel] = True
    if channel == "email":
        original = smtplib.SMTP_SSL.sendmail
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError("reply lost after server accepted")
        monkeypatch.setattr(smtplib.SMTP_SSL, "sendmail", lost)
    else:
        obj, attr = (urllib.request, "urlopen") if channel == "telegram" else (n, "_feishu_http_post_json")
        original = getattr(obj, attr)
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise TimeoutError("reply lost after server accepted")
        monkeypatch.setattr(obj, attr, lost)
    result = cli(ref, "critical")
    assert result["status"] == "unknown" and result["channels"][channel] is None
    assert sum(r["channel"] == channel and r["accepted"] for r in wire) == 1
    attempt = state()[ref[0]["key"]]["last_notification_attempt"]
    assert attempt["status"] == "unknown" and attempt["channels"][channel] is None
    row = json.loads(n._ledger_path().read_text().splitlines()[-1])
    assert row["channels"][channel] is None and channel in row["attempted_channels"]
    assert "notified_at" not in state()[ref[0]["key"]]


@pytest.mark.parametrize("old_shape", [False, True])
def test_async_html_preserves_original_payload_and_repairs_unattempted_0687(box, old_shape):
    n, clock, _, wire, _, seed, state, update, cli, _ = box
    from alert_digest_delivery import signature, split_posts
    ref = seed()
    body = "<b>ACTIVE_MARKER</b><br>需人工处理 &amp; 完整尾部"
    cli(ref, args=["--defer-digest"], body=body)
    if old_shape:
        entry = json.loads(n.ALERT_DIGEST_FILE.read_text().splitlines()[0])
        subject, lines = entry["subject"], [n._html_to_text(body)]
        required, route, chat = n._digest_delivery_route()
        pending = dict(version=1, entries=[entry], subject=subject, body=body, lines=lines, n=1,
                       signature=signature([[entry], subject, body, lines, 1]), parts=split_posts(subject, lines, chat),
                       route_hash=route, feishu_required=required, confirmed_parts=[], other_attempted=False,
                       other_success={"email": False, "telegram": False}, first_attempted=False, complete=False)
        pending["parts_signature"] = signature([pending["signature"], pending["parts"]])
        n._write_digest_delivery_state({"pending_delivery": pending})
    clock[0] = datetime(2026, 11, 11, 23, 30)
    assert n.flush_digest()["sent"]
    assert [r["body"] for r in wire if r["channel"] == "email"] == [body]
    assert all("ACTIVE_MARKER" in str(r["body"]) and "完整尾部" in str(r["body"]) for r in wire)
    assert all(state()[ref[0]["key"]]["notified_channels"].values())


def test_expired_live_owner_cannot_continue_or_overwrite_new_attempt(box, monkeypatch):
    import types
    n, clock, _, wire, accepted, seed, state, update, cli, root = box
    ref = seed()
    wall = root / "wall"
    wall.write_text("1000000")
    fake_time = types.SimpleNamespace(**{name: getattr(time, name) for name in dir(time)})
    fake_time.time = lambda: float(wall.read_text())
    monkeypatch.setattr(n, "time", fake_time)
    ctx = multiprocessing.get_context("fork")
    entered, release = ctx.Event(), ctx.Event()
    def slow(body):
        entered.set()
        assert release.wait(10)
        return True
    def worker(actor):
        accepted["email"] = slow if actor == "A" else True
        n.main(["fault", "body", "--ops-event-refs", json.dumps(ref), "--result-file", str(root / (actor + ".json"))])
    first = ctx.Process(target=worker, args=("A",))
    second = ctx.Process(target=worker, args=("B",))
    try:
        first.start()
        assert entered.wait(10)
        wall.write_text("1000181")
        second.start()
        second.join(10)
        assert second.exitcode == 0
        newest = state()[ref[0]["key"]]["last_notification_attempt"]
        release.set()
        first.join(10)
        assert first.exitcode == 0
        assert state()[ref[0]["key"]]["last_notification_attempt"] == newest
    finally:
        release.set()
        for process in (first, second):
            if process.pid and process.is_alive(): process.kill()
            if process.pid: process.join(5)
    rows = [json.loads(s) for s in (root / "wire.jsonl").read_text().splitlines()]
    assert {c: sum(r["channel"] == c for r in rows) for c in n.OPS_CHANNELS} == {"email": 2, "telegram": 1, "feishu": 1}
    old = json.loads((root / "A.json").read_text())
    assert old["claim_lost"] and old["status"] == "unknown"


@pytest.mark.parametrize("phase", ["recovery", "escalation"])
def test_0687_phase_receipts_not_resent_during_channel_contract_upgrade(box, phase):
    n, clock, _, wire, _, seed, state, update, cli, root = box
    ref = seed()
    cli(ref, "critical")
    if phase == "recovery": update(ref, status="recovered", requires_action=False)
    ref = [{**ref[0], "phase": phase}]
    cli(ref)
    data = state()
    data[ref[0]["key"]].pop("last_" + phase + "_notified_channels")
    (root / "data/alert_state.json").write_text(json.dumps(data))
    before = len(wire)
    assert cli(ref)["status"] == "suppressed"  # old last-attempt channels remain evidence
    assert len(wire) == before
    # Without any channel evidence the legacy phase flag is unknown, not a new send.
    data[ref[0]["key"]].pop("last_notification_attempt")
    (root / "data/alert_state.json").write_text(json.dumps(data))
    assert cli(ref)["status"] == "unknown"
    assert len(wire) == before

@pytest.mark.parametrize('body', ['<b>ACTION</b><br>需人工处理', 'A &amp; B<br>C'])
def test_html_digest_contract_delivers_complete_content(box, body):
    n, clock, _, wire, _, seed, state, update, cli, root = box
    refs = seed()
    cli(refs, 'warning', body=body)
    clock[0] = datetime(2026, 11, 11, 23, 30)
    n.flush_warning_batch()
    result = n.flush_digest()
    assert result['sent'] and len(wire) == 3
    assert all(state()[refs[0]['key']]['notified_channels'].values())


def test_partial_retry_records_only_new_channel_acceptances(box):
    n, _, _, wire, accepted, seed, state, update, cli, _ = box
    refs = seed()
    accepted.update(telegram=False, feishu=False)
    assert cli(refs, 'critical')['status'] == 'partial'
    accepted.update(telegram=True, feishu=True)
    before = len(wire)
    result = cli(refs, 'critical')
    assert result['status'] == 'sent'
    assert [r['channel'] for r in wire[before:]] == ['telegram', 'feishu']
    rows = [json.loads(line) for line in n._ledger_path().read_text().splitlines()]
    assert rows[-1]['channels'] == {'email': False, 'telegram': True, 'feishu': True}
    assert 'email' not in rows[-1]['attempted_channels']
    assert all(state()[refs[0]['key']]['notified_channels'].values())


def test_response_loss_is_unknown_in_receipt_and_ledger(box):
    n, _, _, wire, accepted, seed, state, update, cli, _ = box
    refs = seed()
    def lost(body):
        raise TimeoutError('remote acceptance possible; response lost')
    accepted['email'] = lost
    result = cli(refs, 'critical')
    assert result['status'] == 'unknown' and result['channels']['email'] is None
    assert state()[refs[0]['key']]['last_notification_attempt']['channels']['email'] is None
    assert json.loads(n._ledger_path().read_text().splitlines()[-1])['channels']['email'] is None
    accepted['email'] = True
    before = len(wire)
    assert cli(refs, 'critical')['status'] == 'sent'
    assert [r['channel'] for r in wire[before:]] == ['email']


def test_expired_live_owner_stops_remaining_channels_and_preserves_new_receipt(box):
    n, _, _, wire, accepted, seed, state, update, cli, root = box
    refs = seed()
    replacement = {'attempt_id': 'new-owner', 'status': 'sent', 'channels': dict.fromkeys(n.OPS_CHANNELS, True)}
    def takeover(body):
        with n._ops_state_lock():
            data = n._ops_read_state()
            current = data[refs[0]['key']]
            current.pop('notification_claim')
            current['last_notification_attempt'] = replacement
            current.update(notified_event_id='e1', notified_at='new', notified_channels=dict.fromkeys(n.OPS_CHANNELS, True))
            n._ops_write_state(data)
        return True
    accepted['email'] = takeover
    result = cli(refs, 'critical')
    assert result['claim_lost'] and result['status'] == 'unknown'
    assert [r['channel'] for r in wire] == ['email']
    assert state()[refs[0]['key']]['last_notification_attempt'] == replacement
