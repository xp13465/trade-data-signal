"""Cross-owner interface test: actual monitor definitions -> real notify CLI.

On the isolated 49fe9 notify branch the monitor is intentionally unchanged.
Set NOTIFY_OPS_SCHEDULE_SOURCE to the coordinated monitor source; after integration
the default local path runs the same test without this override.
"""
import ast
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import types

import pytest
from test_notify_ops_quiet_20261111 import box  # noqa: F401


def monitor_namespace(root):
    path = Path(os.environ.get("NOTIFY_OPS_SCHEDULE_SOURCE", Path(__file__).resolve().parents[1] / "schedule_monitor.sh"))
    text = path.read_text().split("<<'PYEOF'", 1)[1].split("\n", 1)[1].split("\nPYEOF", 1)[0]
    tree = ast.parse(text)
    if not any(isinstance(n, ast.FunctionDef) and n.name == "_quiet_route_alerts" for n in tree.body):
        pytest.skip("coordinated monitor not integrated; set NOTIFY_OPS_SCHEDULE_SOURCE")
    import alert_denoise_rules as adr
    ns = dict(datetime=datetime, timedelta=timedelta, Path=Path, os=os, re=re, json=json,
              tempfile=tempfile, time=time, fcntl=fcntl, hashlib=hashlib, sys=sys, subprocess=subprocess,
              REPO=root, LOG_DIR=root / "logs", ALERT_STATE_FILE=root / "data/alert_state.json",
              NOW=datetime(2026, 11, 11, 15, 30), adr=adr, alerts=[], recoveries=[],
              alert_state={}, seen_keys_this_run=set(), in_progress_tasks=set(),
              STATS_FRESH_WINDOW=timedelta(hours=24), _STATE_PRE={},
              _ALERT_MAIL_COUNTER={"sent": 0}, MONITOR_LOG=root / "monitor.log", stats=[])
    constants = {"DUR_THRESHOLDS", "DUR_CONTINUOUS_THRESHOLD", "DUR_IMMEDIATE_MULTIPLE",
                 "DUR_BUFFER_MAX_AGE", "STALE_EXIT_THRESHOLD", "IN_PROGRESS_MAX_AGE", "RECOVERY_COOLDOWN",
                 "STATE_SHARED_FIELDS", "STATE_ACK_FIELDS", "STATE_NOTIFY_FIELDS",
                 "_IMPACT_MAP", "_SUGGEST_MAP", "_LOG_MAP", "TASKS"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) or (isinstance(node, ast.Assign) and any(getattr(t, "id", "") in constants for t in node.targets)):
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    return ns, tree


@pytest.mark.parametrize("first_accepts", [True, False])
@pytest.mark.parametrize("run_known", [True, False])
def test_real_detection_state_refs_send_receipt_recovery(box, monkeypatch, first_accepts, run_known):
    n, clock, _, wire, accepted, seed, state, update, cli, root = box
    ns, tree = monitor_namespace(root)
    assert set(n.OPS_RECEIPT_FIELDS) <= set(ns["STATE_NOTIFY_FIELDS"])
    accepted.update(dict.fromkeys(accepted, first_accepts))
    calls = []

    def run(cmd, **kwargs):
        assert Path(cmd[1]) == root / "scripts/notify.py"
        assert "--ops-event-refs" in cmd and kwargs["timeout"] == 30
        calls.append(cmd)
        rc = n.main(cmd[2:])  # Real CLI/parser/routing, only transport below is stubbed.
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    node = next(x for x in ast.walk(tree) if isinstance(x, ast.If) and ast.unparse(x.test).startswith("_dur is not None"))
    ns.update(_dur=1900, _dur_task="intraday_snapshot", s={"task": "intraday_snapshot",
              "last_duration_sec": 1900, "last_run": "2026-11-11 15:02", "last_exit": 0})
    # In the real monitor s comes from stats. Also test a genuinely absent run
    # evidence row: the reference must retain null rather than invent NOW.
    ns["stats"] = [ns["s"]] if run_known else []
    exec(compile(ast.Module(body=[node], type_ignores=[]), "monitor-duration", "exec"), ns)
    assert ns["alerts"]
    assert ns["_quiet_route_alerts"](ns["alerts"]) == []
    assert len(calls) == 1
    ref = json.loads(calls[0][calls[0].index("--ops-event-refs") + 1])[0]
    row = state()[ref["key"]]
    assert row["event_id"] == ref["event_id"]
    assert ref["source_run"] == ("2026-11-11 15:02" if run_known else None)
    assert bool(row.get("notified_at")) == first_accepts
    assert len(wire) == 3
    # Monitor retains fresh async receipts when saving its earlier state object.
    ns["save_alert_state"](ns["alert_state"])
    assert bool(state()[ref["key"]].get("notified_at")) == first_accepts
    ns["alert_state"][ref["key"]].update(status="recovered", last_recovered="2026-11-11 15:40:00")
    accepted.update(dict.fromkeys(accepted, True))
    ns["_quiet_route_recoveries"]([])
    assert len(calls) == (2 if first_accepts else 1)
    assert len(wire) == (6 if first_accepts else 3)
    ns["_quiet_route_recoveries"]([])
    assert len(wire) == (6 if first_accepts else 3)
