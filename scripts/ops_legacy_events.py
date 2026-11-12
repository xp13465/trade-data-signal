"""Legacy producers adapted to the existing notify event/receipt contract.

No second queue, receipt store or dispatcher. Only the producer owns health;
notify owns channel receipts/claims and alert_ack owns ACK fields. The schedule
writer must preserve these entries (see owns_event_key) rather than recover them
from its own absence-of-observation. Corrupt shared state is never overwritten.
"""
from __future__ import annotations

import contextvars
from functools import wraps
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime
import uuid

PREFIXES = ("producer_s06|", "producer_heartbeat|", "producer_nextday_plan|",
            "producer_nextday_gap|", "producer_update_all|", "producer_daily_summary|")
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


def observe(repo, key, probe, *, run_id=None):
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
        if run_id is not None:
            current_run = state.get(key, {}).get("producer_run")
            if not current_run:
                raise ValueError("run fence missing; outcome unknown")
            if current_run != run_id:
                return {"action": None, "message": "superseded run"}, None
        facts = probe(state) if run_id is not None else probe()
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
        if facts["action"] and (not current or old["status"] == "recovered" or facts.get("new_cause")):
            entry = {"event_id": "producer:" + uuid.uuid4().hex, "source_run": None,
                     "first_seen": now}
            if old:
                entry["previous_events"] = (list(old.get("previous_events") or [])[-15:] +
                    [{k: old[k] for k in ("event_id", "source_run", "status", "first_seen", "last_recovered")
                      + ACK_FIELDS + api.OPS_RECEIPT_FIELDS if k in old}])
        else:
            entry = dict(old)  # preserves concurrent ACK/channel receipts/claim
        # Keep only the run fence on a new event, never its old ACK/receipt.
        for field in ("producer_run", "run_result", "run_detail", "run_failure_kind", "fault_kinds"):
            if field in old:
                entry[field] = old[field]
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


# Operation producers share the SAME state store. These are execution fences,
# not a second notification queue/receipt engine. Poll observers above remain
# independent of operation completion semantics.
TASKS = {"nextday_plan", "nextday_gap", "update_all", "daily_summary"}
# Reserved stdout token: diagnostics are distinct from a failed/empty begin.
DISABLED_RUN = "disabled:diagnostic"


def operation_key(task):
    if task not in TASKS:
        raise ValueError("unsupported operation")
    return "producer_" + task + "|operation"


def begin_operation(repo, task):
    api = _state_api(repo)
    with api._ops_state_lock():
        try:
            state = api._ops_read_state()
        except FileNotFoundError:
            state = {}
        key = operation_key(task)
        entry = state.setdefault(key, {})
        if not isinstance(entry, dict):
            raise ValueError("corrupt operation entry")
        token = uuid.uuid4().hex
        entry.update(producer_run=token, run_result="running", run_detail="", run_failure_kind="")
        api._ops_write_state(state)
        return token


def complete_operation(repo, task, token, *, failed=False, detail="", kind="execution", health=None):
    """Fenced result and health update. Unknown/skips leave old health untouched.

    Wrapper failures reuse a child's exact failure payload and identity; complete
    child success is NOT inferred from a wrapper exit status. First failure still
    alerts if the state cannot be read/persisted (unknown, no invented receipt).
    """
    api = _state_api(repo)
    key = operation_key(task)
    try:
        if not token:
            raise ValueError("run fence unavailable")
        def probe(state):
            # Called within observe's original state lock and fresh state mapping.
            entry = state[key]
            prior_failed = entry.get("run_result") == "failed"
            actual_detail = entry.get("run_detail") if prior_failed else detail
            actual_kind = entry.get("run_failure_kind") if prior_failed else kind
            if failed or prior_failed:
                entry.update(run_result="failed", run_detail=actual_detail,
                             run_failure_kind=actual_kind)
                # A run may accumulate different failure kinds, never erase one
                # merely because the later failure has better recovery evidence.
                kinds = set(entry.get("fault_kinds") or []) if entry.get("status") == "active" else set()
                new_kinds = set(actual_kind.split(","))
                new_cause = bool(kinds and not new_kinds <= kinds)
                kinds.update(new_kinds)
                entry["fault_kinds"] = sorted(kinds)
                return {"action": True, "message": actual_detail, "kind": actual_kind, "new_cause": new_cause}
            # Current prices do not bind the original failed execution date or
            # asset set. Keep gap/plan/update outcomes unknown until that proof
            # exists; never let today's healthy target close yesterday's gap.
            verified = task == "daily_summary" and health == "report_accepted"
            entry.update(run_result="verified" if verified else "unknown", run_detail=detail)
            api._ops_write_state(state)
            if not verified:
                raise _UnverifiedCompletion("no complete recovery witness")
            return {"action": False, "message": detail, "health_witness": health}
        facts, refs = observe(repo, key, probe, run_id=token)
        if facts["action"] is None:
            return "superseded"
        if not facts["action"]:
            return "verified"
        return dispatch(repo, Path(__file__).with_name("notify.py"),
                        "[告警] " + task + " 操作失败", facts["message"], refs,
                        source=task)
    except _UnverifiedCompletion:
        return "unknown"
    except Exception as exc:
        print(f"[ops-operation] unknown {task}: {type(exc).__name__}: {exc}", file=sys.stderr)
        if failed:
            # Cannot trust broken state/old ACK. Keep critical visible; may repeat.
            try:
                dispatch(repo, Path(__file__).with_name("notify.py"), "[告警] " + task + " 操作失败",
                         detail + "；事件状态未知", None, source=task)
            except Exception as send_exc:
                print(f"[ops-operation] notification unknown: {send_exc}", file=sys.stderr)
        return "unknown"


class _UnverifiedCompletion(Exception):
    pass


_CONTEXT = contextvars.ContextVar("ops_operation", default=None)


def operation_failure(subject, body, kind="execution"):
    ctx = _CONTEXT.get()
    if ctx is None:
        return False  # compatibility for helper-only callers, no fabricated run
    if ctx["failed"] and ctx["kind"] != kind:
        kind = ",".join(sorted(set(ctx["kind"].split(",")) | set(kind.split(","))))
    detail = subject + "\n" + body
    if ctx["failed"] and detail != ctx["detail"]:
        detail = ctx["detail"] + "\n" + detail
    ctx.update(failed=True, detail=detail, kind=kind)
    return True


def operation_health(witness):
    ctx = _CONTEXT.get()
    if ctx is not None:
        ctx["health"] = witness


def operation_mode(task, argv, *, unknown_is_live=False):
    """Alert and recovery are different permissions; real backfills still fail loud.

    Recognize the producer's argparse flags, including --option=value. Unknown
    argv (e.g. importing from pytest) is not an operational entrypoint. A real
    shell begin opts into fail-visible unknown argv, never a diagnostic marker.
    """
    flags = ({"--dry-run"} if task == "daily_summary" else
             {"--dry-run", "--no-r2", "--no-notify", "--no-backfill", "--repair-backfill"}
             if task == "nextday_plan" else
             {"--dry-run", "--no-r2", "--no-notify", "--no-retry", "--recheck-pending"})
    flags |= {"--help", "-h"}  # argparse built-ins, including unique long abbreviations
    valued = {"--mode"} if task == "daily_summary" else ({"--date"} if task == "nextday_plan" else {"--date", "--test-open", "--retry-targets"})
    seen, positional = set(), False
    items = iter(argv)
    for item in items:
        key, equal, value = item.partition("=")
        if key.startswith("--") and key not in flags | valued:
            matches = [option for option in flags | valued if option.startswith(key)]
            if len(matches) == 1:
                key = matches[0]
        if key in valued:
            value = value if equal else next(items, "")
            if not value:
                return unknown_is_live, False
            if task == "daily_summary" and value != "main":
                return (False if value == "supplement" else unknown_is_live), False
        elif key in flags and not equal:
            if key in {"--help", "-h"}:
                # Help exits without executing: do not replace an in-flight token.
                # An attached value does not reach here; it remains fail-visible.
                return False, False
            pass
        elif task == "daily_summary" and not positional and len(item) == 8 and item.isdigit():
            positional = True
            key = "--date"
        else:
            return unknown_is_live, False
        seen.add(key)
    live = not bool(seen & {"--dry-run", "--test-open", "--no-r2", "--no-notify"})
    recover = live and not bool(seen & {"--date", "--no-backfill", "--repair-backfill", "--recheck-pending", "--no-retry"})
    return live, recover


def tracked_operation(task, repo):
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            root = Path(repo())
            argv = sys.argv[1:]
            live, recover = operation_mode(task, argv)
            # _run_main(date, dry_run) must never certify dry runs even if called
            # directly by Python with an empty argv.
            if task == "daily_summary" and (kwargs.get("dry_run") or len(args) > 1 and args[1]):
                live = False
            inherited = os.environ.get("OPS_LEGACY_TASK") == task
            token = os.environ.get("OPS_LEGACY_RUN", "") if inherited else ""
            ctx = {"failed": False, "detail": "", "kind": "execution", "health": None}
            marker = _CONTEXT.set(ctx)
            try:
                if live and not inherited:
                    try:
                        token = begin_operation(root, task)
                    except Exception as exc:
                        print(f"[ops-operation] begin unknown: {exc}", file=sys.stderr)
                try:
                    rc = fn(*args, **kwargs)
                except Exception as exc:
                    if live:
                        logfile = os.environ.get("OPS_LEGACY_LOG") or str(root / "data/logs" /
                            {"nextday_plan": "nextday_plan_launchd.log", "nextday_gap": "nextday_gap_check_launchd.log",
                             "daily_summary": "update_all_*.log"}[task])
                        detail = f"{task}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-2000:]}\n日志: {logfile}"
                        complete_operation(root, task, token, failed=True, detail=detail)
                    raise
                if live:
                    complete_operation(root, task, token, failed=ctx["failed"] or rc not in (0, None),
                        detail=ctx["detail"] or f"{task} completed rc={rc}; business health not inferred",
                        kind=ctx["kind"], health=ctx["health"] if recover else None)
                return rc
            finally:
                _CONTEXT.reset(marker)
        return run
    return decorate


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("begin", "fail", "unknown"))
    ap.add_argument("--repo", required=True)
    ap.add_argument("--task", choices=sorted(TASKS), required=True)
    ap.add_argument("--run", default="")
    ap.add_argument("--detail", default="")
    ap.add_argument("--disabled", action="store_true")
    ap.add_argument("--kind", default="execution")
    ap.add_argument("--producer-args", nargs=argparse.REMAINDER, default=None,
                    help="begin only: unmodified producer argv, parsed by operation_mode")
    args = ap.parse_args(argv)
    if args.disabled or args.run == DISABLED_RUN or (args.action == "begin"
            and args.producer_args is not None and not operation_mode(args.task, args.producer_args, unknown_is_live=True)[0]):
        print(DISABLED_RUN if args.action == "begin" else "disabled")
        return 0
    if args.action == "begin":
        try:
            print(begin_operation(args.repo, args.task))
        except Exception as exc:
            # No stdout token: wrapper still reports a real child failure with
            # unknown metadata, never mistakes a broken state file for dry-run.
            print(f"[ops-operation] begin unknown: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
    else:
        status = complete_operation(args.repo, args.task, args.run,
                                    failed=args.action == "fail", detail=args.detail, kind=args.kind)
        print(status)
        return 0 if status in ("sent", "suppressed", "superseded", "verified") else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
