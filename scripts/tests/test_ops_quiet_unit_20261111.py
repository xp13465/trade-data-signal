"""Real CFU CLI -> real notify CLI; external transports only are simulated.

Optional OPS_QUIET_NOTIFY_SOURCE / OPS_QUIET_SCHEDULE_SOURCE point to frozen
integration snapshots until their independent branches are merged. No business
shell body, systemctl, production credentials or real network is executed.
"""
import ast
import builtins
from collections import Counter
from datetime import datetime
import fcntl
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import smtplib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
CHANNELS = ("email", "telegram", "feishu")
CASES = [("public_fund_daily", "trade-public-fund-daily.service", 124, "a" * 32),
         ("overfit_monitor", "trade-overfit-monitor.service", 75, "b" * 32)]

# Installed before importing production modules, in every child including CFU.
GUARD = r'''
import builtins, http.client, io, os, pathlib, smtplib, socket, subprocess, urllib.request
root = pathlib.Path(os.environ['REPO']).resolve()
def deny(*a, **kw):
    with (root/'traps.jsonl').open('a') as out: out.write('external\n')
    raise AssertionError('external effect forbidden')
for obj, key in [(socket,'create_connection'),(socket,'getaddrinfo'),(socket.socket,'connect'),
                 (socket.socket,'connect_ex'),(urllib.request,'urlopen'),(smtplib,'SMTP'),
                 (smtplib,'SMTP_SSL'),(http.client.HTTPConnection,'connect'),
                 (http.client.HTTPSConnection,'connect'),(os,'system')]:
    setattr(obj, key, deny)
def guarded(real):
    def call(file, *a, **kw):
        if isinstance(file,(str,bytes,os.PathLike)):
            p=pathlib.Path(os.fsdecode(file)).absolute()
            if p.name=='.env' or (p.name in ('email.json','telegram.json','feishu.json') and not p.is_relative_to(root)):
                return deny()
        return real(file,*a,**kw)
    return call
builtins.open=guarded(builtins.open); io.open=guarded(io.open)
real_popen=subprocess.Popen
def popen(cmd,*a,**kw):
    if not (isinstance(cmd,list) and len(cmd)>1 and pathlib.Path(cmd[1])==root/'scripts/notify.py'):
        return deny()
    return real_popen(cmd,*a,**kw)
subprocess.Popen=popen
'''


def _offline_notify(source):
    """Only this child replaces actual wire calls; all gates/receipts stay real."""
    from email import message_from_string
    root = Path(os.environ["REPO"])
    spec = importlib.util.spec_from_file_location("offline_actual_notify", source)
    n = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(n)
    mode = json.loads((root / "mode.json").read_text())
    statefile = root / "data/alert_state.json"
    if mode.get("before") == "missing":
        statefile.unlink()
    elif mode.get("before") in ("superseded", "recovered"):
        state = json.loads(statefile.read_text())
        for st in state.values():
            if mode["before"] == "superseded":
                st["event_id"] = "new-event"
            else:
                st.update(status="recovered", requires_action=False)
        statefile.write_text(json.dumps(state))
    n.load_email_config = lambda: {"smtp": "offline", "user": "offline@example.test",
                                   "password": "offline", "to": "offline@example.test"}
    n.load_telegram_config = lambda: {"bot_token": "offline", "chat_id": "offline"}
    n.telegram_configured = lambda: True
    n.load_feishu_config = lambda: {"enabled": True, "mode": "app",
                                    "chat_ids": {"alert": "offline-alert", "report": "offline-report"}}
    n._load_feishu_credentials = lambda: ("", "")
    n._get_tenant_access_token = lambda: "offline-token"

    def wire(channel, body):
        ok = mode.get(channel, True)
        rec = {"channel": channel, "body": body, "accepted": ok, "pid": os.getpid()}
        with (root / "wire.jsonl").open("a") as out:
            fcntl.flock(out, fcntl.LOCK_EX)
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if mode.get("hold"):
            (root / "transport-entered").touch()
            deadline = time.monotonic() + 10
            while not (root / "transport-release").exists():
                if time.monotonic() > deadline:
                    raise AssertionError("bounded transport barrier timed out")
                time.sleep(.01)
        if mode.get("receipt_corrupt"):
            statefile.write_text("broken")
        return ok

    class SMTP:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def login(self, *a): pass
        def sendmail(self, sender, recipients, message):
            body = message_from_string(message).get_payload(decode=True).decode()
            if not wire("email", body):
                raise OSError("offline rejection")
            return {}

    def telegram(req, **kw):
        assert req.full_url.startswith("https://api.telegram.org/botoffline/")
        return io.BytesIO(json.dumps({"ok": wire("telegram", json.loads(req.data)["text"])}).encode())

    def feishu(url, payload, headers):
        assert "open.feishu.cn/" in url
        return {"code": 0 if wire("feishu", json.loads(payload)) else 99901}

    smtplib.SMTP_SSL = SMTP
    urllib.request.urlopen = telegram
    n._feishu_http_post_json = feishu
    return n.main(sys.argv[1:])


def _schedule_namespace(source, root):
    text = Path(source).read_text().split("<<'PYEOF' 2>&1\n", 1)[1].split("\nPYEOF", 1)[0]
    tree = ast.parse(text)
    names = {"_quiet_event", "_quiet_source_run", "save_alert_state", "_quiet_notified",
             "_quiet_send", "_quiet_core_unit_refs", "_quiet_route_alerts", "_format_alert_item",
             "_unit_short_name", "_unit_alert_events", "_sm_alert_subject", "_task_name_of", "_task_names_of"}
    constants = {"STATE_ACK_FIELDS", "STATE_NOTIFY_FIELDS", "STATE_SHARED_FIELDS"}
    nodes = [x for x in tree.body if (isinstance(x, ast.FunctionDef) and x.name in names)
             or (isinstance(x, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in x.targets))]
    ns = {"Path": Path, "REPO": root, "ALERT_STATE_FILE": root / "data/alert_state.json",
          "MONITOR_LOG": root / "monitor.log", "_STATE_PRE": {}, "_ALERT_MAIL_COUNTER": {"sent": 0},
          "_IMPACT_MAP": {}, "_SUGGEST_MAP": {}, "_LOG_MAP": {}, "ut": None,
          **{k: globals()[k] for k in ("json", "os", "sys", "subprocess", "tempfile", "hashlib", "re", "time", "fcntl")}}
    exec(compile(ast.Module(nodes, type_ignores=[]), str(source), "exec"), ns)
    return ns


def _schedule_child(source):
    root = Path(os.environ["REPO"])
    ns = _schedule_namespace(source, root)
    ns["alert_state"] = json.loads(ns["ALERT_STATE_FILE"].read_text())
    messages = [e["message"] for e in ns["alert_state"].values()]
    assert ns["_quiet_route_alerts"](messages) == []
    return 0


@pytest.fixture
def box(tmp_path):
    """Copy the actual CFU file, NOT a fake CFU function. CLI inputs supply systemd."""
    root = tmp_path / "isolated"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / "data").mkdir()
    shutil.copy2(SCRIPTS / "check_failed_units.py", scripts / "check_failed_units.py")
    (scripts / "sitecustomize.py").write_text(GUARD)
    (scripts / "exists.sh").write_text("# no business execution\n")
    (root / "mode.json").write_text("{}")
    notify = Path(os.environ.get("OPS_QUIET_NOTIFY_SOURCE", SCRIPTS / "notify.py"))
    schedule = Path(os.environ.get("OPS_QUIET_SCHEDULE_SOURCE", SCRIPTS / "schedule_monitor.sh"))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("FEISHU_", "SMTP_", "TELEGRAM_", "ALERT_", "NOTIFY_"))}
    env.update(REPO=str(root), MAIN_REPO=str(root), GIT_REPO=str(root), HOME=str(root),
               PATH="/nonexistent", PYTHONPATH=os.pathsep.join((str(scripts), str(SCRIPTS))),
               PYTHONDONTWRITEBYTECODE="1")
    runner = ("import runpy,sys\nns=runpy.run_path(" + repr(str(Path(__file__).resolve())) + ")\n"
              "sys.exit(ns['_offline_notify'](" + repr(str(notify)) + "))\n")
    (scripts / "notify.py").write_text(runner)
    (scripts / "schedule_driver.py").write_text(
        "import runpy,sys\nns=runpy.run_path(" + repr(str(Path(__file__).resolve())) + ")\n"
        "sys.exit(ns['_schedule_child'](" + repr(str(schedule)) + "))\n")
    sys.path.insert(0, str(SCRIPTS))
    import alert_denoise_rules as adr
    show = {}
    for unit, kind in adr.WATCHMAN_UNITS:
        service = unit.replace(".timer", ".service")
        show[unit] = dict(ActiveState="active", LoadState="loaded", UnitFileState="enabled", Triggers=service)
        show[service] = dict(ActiveState="inactive", LoadState="loaded", ExecStart=f"/bin/sh {scripts / 'exists.sh'}")
    (root / "show.json").write_text(json.dumps(show))
    (root / "failed.txt").write_text("")
    processes = []
    logs = []

    def command(refs=None, dry=False):
        args = [sys.executable, str(scripts / "check_failed_units.py"), "--repo", str(root), "--notify",
                "--failed-units-file", str(root / "failed.txt"), "--unit-show-json", str(root / "show.json"),
                "--allowlist-file", str(root / "absent-allowlist")]
        if refs is not None:
            args += ["--ops-unit-event-refs", refs if isinstance(refs, str) else json.dumps(refs)]
        if dry:
            args.append("--dry-run")
        return args

    def run(args=None, **kw):
        r = subprocess.run(args or command(**kw), cwd=root, env=env, capture_output=True, text=True, timeout=35)
        logs.append({"args": args, "rc": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
        (root / "cli-results.json").write_text(json.dumps(logs, ensure_ascii=False, indent=2))
        return r

    def spawn(args):
        p = subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(p)
        return p

    def seed(case=CASES[0], extra=()):
        task, unit, code, invocation = case
        key = f"{task}|unit_exit!=0|{code}"
        state = json.loads((root / "data/alert_state.json").read_text()) if (root / "data/alert_state.json").exists() else {}
        state[key] = dict(status="active", requires_action=True, source_run=invocation, event_id="event-" + task,
                          first_seen="2026-11-11 10:00:00", keyword="unit_exit!=0",
                          message=f"SEVERE: {task} unit_exit!=0 {code}")
        (root / "data/alert_state.json").write_text(json.dumps(state))
        props = json.loads((root / "show.json").read_text())
        props[unit] = dict(LoadState="loaded", ActiveState="failed", InvocationID=invocation,
                           Result="timeout" if code == 124 else "exit-code", ExecMainCode="1",
                           ExecMainStatus="15" if code == 124 else str(code))
        (root / "show.json").write_text(json.dumps(props))
        units = [unit, *extra]
        (root / "failed.txt").write_text("\n".join(u + " loaded failed failed fixture" for u in units))
        return {unit: dict(key=key, event_id=state[key]["event_id"], phase="active", source_run=invocation, exit_code=code)}

    def wire():
        p = root / "wire.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def counts():
        return dict(Counter(r["channel"] for r in wire() if r["accepted"]))

    def mode(**kw):
        (root / "mode.json").write_text(json.dumps(kw))

    def require_integration():
        if "--ops-event-refs" not in notify.read_text() or "def _quiet_core_unit_refs" not in schedule.read_text():
            pytest.skip("requires notify + schedule ops contract; set frozen OPS_QUIET_*_SOURCE")

    yield dict(root=root, scripts=scripts, env=env, run=run, spawn=spawn, command=command,
               seed=seed, wire=wire, counts=counts, mode=mode, notify=notify, schedule=schedule,
               require=require_integration, schedule_cmd=[sys.executable, str(scripts / "schedule_driver.py")])
    for p in processes:
        if p.poll() is None:
            p.kill()
        p.communicate(timeout=5)
    traps = root / "traps.jsonl"
    assert not traps.exists() or not traps.read_text(), traps.read_text()
    sys.path.remove(str(SCRIPTS))


def _state(box):
    return json.loads((box["root"] / "data/alert_state.json").read_text())


def _result(box, r, code=1, sent=None):
    assert r.returncode == code, r.stdout + r.stderr
    if sent is not None:
        assert f"NOTIFY_SENT={sent}\n" in r.stdout, r.stdout + r.stderr
    assert "CHECK_FAILED_UNITS_FAIL" in r.stdout
    assert "CHECK_FAILED_UNITS_OK" not in r.stdout


@pytest.mark.parametrize("case", CASES)
def test_real_schedule_mapping_cfu_cli_and_schedule_send_once(box, case):
    box["require"]()
    refs = box["seed"](case)
    ns = _schedule_namespace(box["schedule"], box["root"])
    ns["alert_state"] = _state(box)
    task, unit, code, invocation = case
    ns["UNIT_STATES"] = {unit: dict(code=code, source="systemd", invocation_id=invocation)}
    produced = ns["_quiet_core_unit_refs"]()
    assert produced == refs  # actual producer, not independently invented mapping
    _result(box, box["run"](refs=produced), sent=1)
    r = box["run"](box["schedule_cmd"])
    assert r.returncode == 0, r.stdout + r.stderr
    _result(box, box["run"](refs=produced), sent=0)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)
    st = _state(box)[refs[unit]["key"]]
    assert st["status"] == "active" and st["requires_action"] is True
    assert st["notified_event_id"] == refs[unit]["event_id"]
    assert not (box["root"] / "data/failed_units_patrol_sig.json").exists()


@pytest.mark.parametrize("case", CASES)
def test_no_handoff_baseline_real_cfu_cli_plus_schedule_is_two(box, case):
    box["require"]()
    box["seed"](case)
    _result(box, box["run"](), sent=1)  # actual full legacy CFU entry
    r = box["run"](box["schedule_cmd"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert box["counts"]() == dict.fromkeys(CHANNELS, 2)


def test_mixed_payload_keeps_other_unit_and_watchman_outside_core_body(box):
    box["require"]()
    refs = box["seed"](extra=["trade-other.service"])
    root = box["root"]
    props = json.loads((root / "show.json").read_text())
    props["trade-cloud-unit-patrol.timer"]["ActiveState"] = "inactive"
    (root / "show.json").write_text(json.dumps(props))
    _result(box, box["run"](refs=refs), sent=2)
    emails = [x["body"] for x in box["wire"]() if x["channel"] == "email"]
    assert len(emails) == 2
    core = next(x for x in emails if "InvocationID" in x)
    legacy = next(x for x in emails if "trade-other.service" in x)
    assert "trade-other.service" not in core and "trade-cloud-unit-patrol.timer" not in core
    assert CASES[0][1] not in legacy and "trade-cloud-unit-patrol.timer" in legacy
    sig = json.loads((root / "data/failed_units_patrol_sig.json").read_text())
    assert CASES[0][1] not in json.dumps(sig) and "trade-other.service" in json.dumps(sig)


@pytest.mark.parametrize("bad", ["missing", "timestamp", "different_run", "different_exit", "bool_exit",
                                   "wrong_key", "wrong_phase", "extra", "bad_state", "unconfirmed_state",
                                   "ledger_shape", "not_failed", "malformed", "not_object"])
def test_invalid_identity_stays_visible_legacy_fallback(box, bad):
    refs = box["seed"]()
    unit = CASES[0][1]
    ref = refs[unit]
    root = box["root"]
    if bad == "missing": ref["source_run"] = None
    elif bad == "timestamp": ref["source_run"] = "2026-11-11 10:00:00"
    elif bad == "different_run": ref["source_run"] = "c" * 32
    elif bad == "different_exit": ref["exit_code"] = 75
    elif bad == "bool_exit": ref["exit_code"] = True
    elif bad == "wrong_key": ref["key"] = "other|unit_exit!=0|124"
    elif bad == "wrong_phase": ref["phase"] = "recovery"
    elif bad == "extra": ref["last_run"] = "2026-11-11 10:00:00"
    elif bad == "bad_state": (root / "data/alert_state.json").write_text("broken")
    elif bad == "unconfirmed_state": (root / "data/alert_state.json").write_text("{}")
    elif bad in ("ledger_shape", "not_failed"):
        props = json.loads((root / "show.json").read_text())
        if bad == "ledger_shape": props[unit] = dict(invocation_id=ref["source_run"], code=124, source="ledger")
        else: props[unit]["ActiveState"] = "activating"
        (root / "show.json").write_text(json.dumps(props))
    elif bad == "malformed": refs = "{broken"
    elif bad == "not_object": refs = "[]"
    r = box["run"](refs=refs)
    _result(box, r, sent=1)
    assert "legacy fallback" in r.stderr
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)


def test_standalone_daily_signature_and_dryrun_stay_compatible(box):
    box["seed"]()
    _result(box, box["run"](), sent=1)
    _result(box, box["run"](), sent=0)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)


def test_valid_refs_dryrun_zero_writes_and_zero_transport(box):
    refs = box["seed"]()
    state = (box["root"] / "data/alert_state.json").read_bytes()
    r = box["run"](refs=refs, dry=True)
    _result(box, r, sent=0)
    assert box["wire"]() == []
    assert (box["root"] / "data/alert_state.json").read_bytes() == state
    assert list((box["root"] / "data").iterdir()) == [box["root"] / "data/alert_state.json"]


@pytest.mark.parametrize("before", ["missing", "superseded", "recovered"])
def test_state_changes_after_validation_not_fake_success(box, before):
    box["require"]()
    refs = box["seed"]()
    box["mode"](before=before)
    _result(box, box["run"](refs=refs), code=4, sent=0)
    assert box["wire"]() == []
    assert not (box["root"] / "data/failed_units_patrol_sig.json").exists()


def test_all_channels_fail_then_retry_same_event(box):
    box["require"]()
    refs = box["seed"]()
    box["mode"](**dict.fromkeys(CHANNELS, False))
    _result(box, box["run"](refs=refs), code=4, sent=0)
    st = next(iter(_state(box).values()))
    assert "notified_event_id" not in st and st["last_notification_attempt"]["status"] == "failed"
    box["mode"]()
    _result(box, box["run"](refs=refs), sent=1)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)


def test_partial_receipt_not_full_delivery_or_second_legacy_copy(box):
    box["require"]()
    refs = box["seed"]()
    box["mode"](telegram=False, feishu=False)
    _result(box, box["run"](refs=refs), sent=1)
    st = next(iter(_state(box).values()))
    assert st["notified_channels"] == dict(email=True, telegram=False, feishu=False)
    assert st["last_notification_attempt"]["status"] == "partial"
    _result(box, box["run"](refs=refs), sent=0)
    assert box["counts"]() == {"email": 1}


def test_accepted_but_receipt_persistence_unknown_is_rc4(box):
    box["require"]()
    refs = box["seed"]()
    box["mode"](receipt_corrupt=True)
    _result(box, box["run"](refs=refs), code=4, sent=1)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)
    assert (box["root"] / "data/alert_state.json").read_text() == "broken"


def test_concurrent_actual_cfu_and_schedule_share_claim(box):
    box["require"]()
    refs = box["seed"]()
    box["mode"](hold=True)
    first = box["spawn"](box["command"](refs=refs))
    deadline = time.monotonic() + 10
    while not (box["root"] / "transport-entered").exists():
        assert first.poll() is None
        assert time.monotonic() < deadline
        time.sleep(.01)
    # Real independent CLI contender observes claim, not a forged successful receipt.
    _result(box, box["run"](refs=refs), sent=0)
    assert "notified_event_id" not in next(iter(_state(box).values()))
    r = box["run"](box["schedule_cmd"])
    assert r.returncode == 0, r.stdout + r.stderr
    (box["root"] / "transport-release").touch()
    out, err = first.communicate(timeout=15)
    assert first.returncode == 1, out + err
    assert "NOTIFY_SENT=1" in out
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)
    assert "notification_claim" not in next(iter(_state(box).values()))


def test_legacy_notify_cannot_fake_accept_new_refs(box):
    # Fixed baseline (or any legacy-only notifier) rejects unknown CLI option.
    legacy = os.environ.get("OPS_QUIET_LEGACY_NOTIFY_SOURCE")
    if not legacy:
        if "--ops-event-refs" in (SCRIPTS / "notify.py").read_text():
            pytest.skip("supply fixed legacy notify snapshot for old-version control")
        legacy = str(SCRIPTS / "notify.py")
    refs = box["seed"]()
    wrapper = box["scripts"] / "notify.py"
    wrapper.write_text(wrapper.read_text().replace(repr(str(box["notify"])), repr(legacy)))
    _result(box, box["run"](refs=refs), code=4, sent=0)
    assert box["wire"]() == []


def test_sandbox_guards_are_effective(box):
    code = """import pathlib, socket, subprocess
for f in [lambda:socket.create_connection(('invalid.example',443)), lambda:subprocess.Popen(['false']), lambda:pathlib.Path('/forbidden/.env').read_text()]:
 try: f(); raise RuntimeError('guard missed effect')
 except AssertionError: pass
"""
    r = box["run"]([sys.executable, "-c", code])
    assert r.returncode == 0, r.stderr
    trap = box["root"] / "traps.jsonl"
    assert trap.read_text().splitlines() == ["external"] * 3
    trap.unlink()


def test_two_core_services_and_same_key_new_incident(box):
    box["require"]()
    first = box["seed"](CASES[0])
    second = box["seed"](CASES[1], extra=[CASES[0][1]])
    refs = {**first, **second}
    _result(box, box["run"](refs=refs), sent=2)
    _result(box, box["run"](refs=refs), sent=0)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 2)
    # Same open incident, different real invocation: still one first notification.
    root = box["root"]
    unit = CASES[0][1]
    state = _state(box)
    key = refs[unit]["key"]
    state[key]["source_run"] = refs[unit]["source_run"] = "c" * 32
    props = json.loads((root / "show.json").read_text())
    props[unit]["InvocationID"] = "c" * 32
    (root / "show.json").write_text(json.dumps(props))
    (root / "data/alert_state.json").write_text(json.dumps(state))
    _result(box, box["run"](refs=refs), sent=0)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 2)
    # A genuinely new incident must not inherit old event receipt evidence.
    state[key]["event_id"] = refs[unit]["event_id"] = "new-public-fund-incident"
    (root / "data/alert_state.json").write_text(json.dumps(state))
    _result(box, box["run"](refs=refs), sent=1)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 3)


def test_missing_actual_exit_cannot_use_parser_default_one(box):
    refs = box["seed"](("overfit_monitor", CASES[1][1], 1, "b" * 32))
    root = box["root"]
    props = json.loads((root / "show.json").read_text())
    props[CASES[1][1]].pop("ExecMainStatus")
    (root / "show.json").write_text(json.dumps(props))
    r = box["run"](refs=refs)
    _result(box, r, sent=1)
    assert "live exit status unavailable" in r.stderr


@pytest.mark.parametrize("mutation", ["fake_sent", "fake_digest", "fake_receipt", "different_event", "expired", "unbounded", "no_claim"])
def test_result_controls_cannot_invent_receipt_or_claim(tmp_path, mutation, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    import check_failed_units as cfu
    ref = dict(key="public_fund_daily|unit_exit!=0|124", event_id="e", phase="active", source_run="a" * 32)
    st = dict(event_id="e", source_run=ref["source_run"], status="active", requires_action=True)
    payload = dict(status="deferred", channels={}, event_results=[{**ref, "status": "deferred"}])
    if mutation in ("fake_sent", "fake_digest", "fake_receipt", "different_event"):
        payload["status"] = "digested" if mutation == "fake_digest" else "sent"
        payload["event_results"][0]["status"] = payload["status"]
        payload["receipt_persisted"] = True
        payload["channels"] = {"email": True}
        if mutation == "fake_sent": payload["channels"] = {"deferred": True, "info_logged": True}
        if mutation == "fake_receipt":
            st.update(notified_event_id="e", notified_at="timestamp", notified_channels={"email": "true"})
        if mutation == "different_event": payload["event_results"][0]["event_id"] = "other"
    else:
        st["notification_claim"] = dict(event_id="e", phase="active", attempt_id="test",
                                        expires_at=time.time() + (999 if mutation == "unbounded" else -1))
        if mutation == "no_claim": st.pop("notification_claim")
    (tmp_path / "data").mkdir()
    (tmp_path / "data/alert_state.json").write_text(json.dumps({ref["key"]: st}))
    handled, _ = cfu._ops_notify_result(tmp_path, ref, payload)
    assert handled is False


def _baseline_schedule_child(source, case):
    root = Path(os.environ["REPO"])
    ns = _schedule_namespace(source, root)
    task, unit, code, invocation = case
    events = ns["_unit_alert_events"]([dict(unit=unit, task=task)],
        {unit: dict(code=code, source="systemd", result="exit-code", invocation_id=invocation)}, {}, datetime.now())
    assert len(events) == 1
    msg = events[0]["msg"]
    import alert_denoise_rules as adr
    kept, absorbed = adr.alert_budget_process({}, [msg], datetime.now(), root)
    assert kept == [msg] and not absorbed
    subject = ns["_sm_alert_subject"](kept, datetime.now().strftime("%m-%d %H:%M"))
    r = subprocess.run([sys.executable, str(root / "scripts/notify.py"), subject,
        ns["_format_alert_item"](msg), "--severe", "--from-prefix", "[告警]",
        "--alert-issue", "计划任务监控告警", "--alert-log", str(root / "monitor.log")],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    return 0


@pytest.mark.parametrize("case", CASES)
def test_fixed49_original_full_cfu_baseline_two_per_channel(box, case):
    baseline = os.environ.get("OPS_QUIET_BASELINE_ROOT")
    if not baseline:
        pytest.skip("optional fixed49 archive required to rerun historical baseline")
    baseline = Path(baseline) / "scripts"
    box["seed"](case)
    shutil.copy2(baseline / "check_failed_units.py", box["scripts"] / "check_failed_units.py")
    wrapper = box["scripts"] / "notify.py"
    wrapper.write_text(wrapper.read_text().replace(repr(str(box["notify"])), repr(str(baseline / "notify.py"))))
    driver = box["scripts"] / "baseline_schedule.py"
    driver.write_text("import runpy,sys\nns=runpy.run_path(" + repr(str(Path(__file__).resolve())) + ")\n"
                     "sys.exit(ns['_baseline_schedule_child'](" + repr(str(baseline / "schedule_monitor.sh"))
                     + "," + repr(case) + "))\n")
    _result(box, box["run"](), sent=1)
    r = box["run"]([sys.executable, str(driver)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert box["counts"]() == dict.fromkeys(CHANNELS, 2)


def test_real_systemctl_parser_then_actual_cli_notify(box):
    box["require"]()
    refs = box["seed"]()
    root = box["root"]
    bindir = root / "bin"
    bindir.mkdir()
    # Local executable emits Key=Value shape; no machine systemd access.
    stub = bindir / "systemctl"
    stub.write_text("#!" + sys.executable + "\nimport json,os,pathlib,sys\n"
        "r=pathlib.Path(os.environ['REPO'])\n"
        "if sys.argv[1]=='list-units': print((r/'failed.txt').read_text())\n"
        "elif sys.argv[1]=='show':\n"
        " for k,v in json.loads((r/'show.json').read_text()).get(sys.argv[-1],{}).items(): print(k+'='+str(v))\n")
    stub.chmod(0o700)
    guard = box["scripts"] / "sitecustomize.py"
    guard.write_text(guard.read_text().replace(
        "def popen(cmd,*a,**kw):\n",
        "def popen(cmd,*a,**kw):\n"
        "    if isinstance(cmd,list) and cmd[0]=='systemctl' and os.environ['PATH']==str(root/'bin'):\n"
        "        return real_popen(cmd,*a,**kw)\n"))
    box["env"]["PATH"] = str(bindir)
    cmd = box["command"](refs=refs)
    for flag in ("--failed-units-file", "--unit-show-json"):
        idx = cmd.index(flag)
        del cmd[idx:idx + 2]
    _result(box, box["run"](cmd), sent=1)
    assert box["counts"]() == dict.fromkeys(CHANNELS, 1)
