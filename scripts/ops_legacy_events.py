"""Two legacy producers adapted to the existing notify event/receipt contract.

No second queue, receipt store or dispatcher. Only the producer owns health;
notify owns channel receipts/claims and alert_ack owns ACK fields. The schedule
writer must preserve these entries (see owns_event_key) rather than recover them
from its own absence-of-observation. Corrupt shared state is never overwritten.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime
import uuid

PREFIXES = ("producer_s06|", "producer_heartbeat|")
ACK_FIELDS = ("acknowledged", "ack_owner", "ack_event_id", "ack_note", "last_ack_log")


def owns_event_key(key):
    return isinstance(key, str) and key.startswith(PREFIXES)


def _state_api(repo):
    # Private module instance: do not change another caller's notify.REPO or
    # environment. Reuse the existing stable lock, atomic write and state reader.
    spec = importlib.util.spec_from_file_location("_legacy_notify_state", Path(__file__).with_name("notify.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.REPO = Path(repo)
    return module


def observe(repo, key, probe):
    """Probe under the SAME state lock, update health, preserve current ACK/receipts.

    probe returns {action: bool, message: str, ...facts}. Errors never recover an
    old fault. Returning no ref means healthy without any prior identified event.
    New incidents get new IDs; legacy ACK without an ID is not reused.
    """
    if not owns_event_key(key):
        raise ValueError("producer key outside owned scope")
    api = _state_api(repo)
    with api._ops_state_lock():
        try:
            state = api._ops_read_state()
        except FileNotFoundError:
            state = {}
        facts = probe()
        if type(facts.get("action")) is not bool:
            raise ValueError("unknown observation cannot prove recovery")
        old = state.get(key)
        if old is not None and not isinstance(old, dict):
            raise ValueError("corrupt producer entry")
        old = old or {}
        current = (isinstance(old.get("event_id"), str) and bool(old["event_id"])
                   and old.get("status") in ("active", "recovered")
                   and type(old.get("requires_action")) is bool
                   and old["requires_action"] == (old["status"] == "active")
                   and old.get("producer") == key.split("|", 1)[0]
                   and old.get("source_run") is None)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not facts["action"] and not current:
            return facts, None
        if facts["action"] and (not current or old["status"] == "recovered"):
            entry = {"event_id": "producer:" + uuid.uuid4().hex, "source_run": None,
                     "first_seen": now}
            if old:
                entry["previous_events"] = (list(old.get("previous_events") or [])[-15:] +
                    [{k: old[k] for k in ("event_id", "source_run", "status", "first_seen", "last_recovered")
                      + ACK_FIELDS + api.OPS_RECEIPT_FIELDS if k in old}])
        else:
            entry = dict(old)  # preserves concurrent ACK/channel receipts/claim
        entry.update(status="active" if facts["action"] else "recovered",
                     requires_action=facts["action"], message=facts["message"],
                     producer=key.split("|", 1)[0], observation=facts, observed_at=now)
        if not facts["action"] and old.get("status") != "recovered":
            entry["last_recovered"] = now
        state[key] = entry
        api._ops_write_state(state)
        return facts, [{"key": key, "event_id": entry["event_id"], "phase": "active", "source_run": None}]


def dispatch(repo, notify_py, subject, body, refs, *, warning=False, source):
    """Real notify CLI, structured outcome; rc=0 is never proof of delivery.

    State failure: caller explicitly uses refs=None, immediate fail-visible send
    without legacy dedup (unknown state cannot suppress a real fault). No queued
    no-ref warning is created. The caller retains a nonzero unknown result.
    """
    with tempfile.TemporaryDirectory(prefix="ops-producer-result-") as temp:
        result = Path(temp) / "result.json"
        cmd = [sys.executable, str(notify_py), subject, body,
               "--tier", "warning" if warning and refs else "critical",
               "--from-prefix", "[告警]", "--result-file", str(result)]
        if refs:
            cmd += ["--ops-event-refs", json.dumps(refs)]
        else:
            cmd += ["--dedup-window", "0"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False,
                              env={**os.environ, "REPO": str(Path(repo).absolute()), "NOTIFY_SOURCE": source})
        try:
            payload = json.loads(result.read_text())
            status = payload.get("status", "unknown")
        except (OSError, ValueError, AttributeError):
            status = "unknown"
        print(f"[{source}] notify status={status} rc={proc.returncode}", file=sys.stderr)
        return status
