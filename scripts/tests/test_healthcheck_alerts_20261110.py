"""HC01/02: AST-only behavior tests; never import detector/notify or open a DB."""
import ast
import html
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/detect_intraday_anomaly.py"
INVALID = [None, False, True, 0, -1, float("nan"), float("inf"), -float("inf"), "123"]


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    # Positive whitelist: no module imports, initialization, main or DB helpers.
    assert all(not isinstance(n, (ast.Import, ast.ImportFrom))
               for node in nodes for n in ast.walk(node))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class Ledger:
    def __init__(self):
        self.data = None

    def exists(self):
        return self.data is not None

    def read_text(self, **kwargs):
        return json.dumps(self.data)


class Rows:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchall(self):
        return self.rows


def history(n=10):
    return [{"high": 4000.0, "low": 3500.0} for _ in range(n)]


def snapshot(high=3900, low=3600):
    return {"indices": [{"code": "sh000001", "name": "上证", "high": high, "low": low}]}


@pytest.fixture
def ns():
    constants = {n.targets[0].id: ast.literal_eval(n.value)
                 for n in ast.parse(SOURCE.read_text()).body
                 if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id in {"BREAKOUT_LOOKBACK", "BREAKOUT_MIN_HISTORY", "SNAPSHOT_TO_INDEX_ID"}}
    def blocked(*args, **kwargs):
        raise AssertionError("BLOCKED outbound")
    space = dict(constants, datetime=datetime, math=math, html=html, json=json,
                 sys=SimpleNamespace(executable="test-python", stderr=sys.stderr),
                 subprocess=SimpleNamespace(run=blocked), NOTIFY_PY="never-execute-notify.py",
                 DEDUP_FILE=Ledger(), notify_sent=lambda out: out == "TEST_SENT")
    load_functions(SOURCE, {"_is_valid_breakout_price", "detect_breakout", "_alert_key",
                            "filter_and_record", "send_alert", "send_or_stage",
                            "retry_pending_emails"}, space)
    with pytest.raises(AssertionError, match="BLOCKED outbound"):
        space["subprocess"].run([])
    return space


@pytest.mark.parametrize("bad", INVALID)
@pytest.mark.parametrize("field", ["high", "low"])
def test_current_invalid_cannot_alert(ns, bad, field):
    args = {"high": 3900, "low": 3600, field: bad}
    assert ns["detect_breakout"](snapshot(**args), Rows(history())) == []


@pytest.mark.parametrize("bad", INVALID)
@pytest.mark.parametrize("field,high,low,kind", [
    ("low", 4100, 3600, "breakout_up"), ("high", 3900, 3400, "breakout_down")])
def test_valid_direction_survives_invalid_other_side(ns, bad, field, high, low, kind):
    args = {"high": high, "low": low, field: bad}
    assert ns["detect_breakout"](snapshot(**args), Rows(history()))[0]["type"] == kind


@pytest.mark.parametrize("bad", INVALID)
@pytest.mark.parametrize("field,high,low", [("high", 4100, 3600), ("low", 3900, 3400)])
@pytest.mark.parametrize("valid_count", [0, 9, 10])
def test_history_filters_before_sample_gate(ns, bad, field, high, low, valid_count):
    rows = history(valid_count) + [dict(history(1)[0], **{field: bad}) for _ in range(10)]
    # A fake query result deliberately admits malformed types/None to test the boundary.
    result = ns["detect_breakout"](snapshot(high, low), Rows(rows))
    assert bool(result) == (valid_count >= 10)
    if result:
        assert result[0]["hh20" if field == "high" else "ll20"] == (4000 if field == "high" else 3500)


@pytest.mark.parametrize("bad", INVALID)
@pytest.mark.parametrize("field,high,low,kind", [
    ("low", 4100, 3600, "breakout_up"), ("high", 3900, 3400, "breakout_down")])
def test_history_other_side_does_not_block(ns, bad, field, high, low, kind):
    rows = [dict(row, **{field: bad}) for row in history()]
    assert ns["detect_breakout"](snapshot(high, low), Rows(rows))[0]["type"] == kind


@pytest.mark.parametrize("high,low,expected", [
    (4100, None, [{"type": "breakout_up", "tier": "normal", "kind": "指数", "name": "上证",
                   "high": 4100, "hh20": 4000.0,
                   "desc": "突破20日高 指数上证 当日高4100.00 > 20日高4000.00"}]),
    (3900, 3400, [{"type": "breakout_down", "tier": "normal", "kind": "指数", "name": "上证",
                   "low": 3400, "ll20": 3500.0,
                   "desc": "跌破20日低 指数上证 当日低3400.00 < 20日低3500.00"}]),
    (4000, 3500, []), (3900, 3600, []),
])
def test_normal_complete_payload_and_strict_boundaries(ns, high, low, expected):
    conn = Rows(history())
    assert ns["detect_breakout"](snapshot(high, low), conn) == expected
    query, params = conn.calls[0]
    assert "date < ?" in query and "ORDER BY date DESC LIMIT ?" in query
    assert "high IS NOT NULL AND low IS NOT NULL" in query
    assert params == ("sh", datetime.now().strftime("%Y%m%d"), 20)


def test_high_priority_and_independent_history_gate(ns):
    assert ns["detect_breakout"](snapshot(4100, 3400), Rows(history()))[0]["type"] == "breakout_up"
    rows = history(9) + [{"high": 0, "low": 3500}]
    assert ns["detect_breakout"](snapshot(4100, 3400), Rows(rows))[0]["type"] == "breakout_down"
    assert ns["detect_breakout"](snapshot(4100, 3400), Rows(history(9))) == []
    assert ns["detect_breakout"]({"indices": [{"code": "unknown", "high": 4100}]}, Rows(history())) == []


def test_invalid_then_valid_dedup_sequence(ns):
    detect, dedup = ns["detect_breakout"], ns["filter_and_record"]
    new, pending = dedup(detect(snapshot(low=0), Rows(history())))
    assert new == [] and not any(pending.values())
    assert not ns["DEDUP_FILE"].exists()  # compute never writes
    new, pending = dedup(detect(snapshot(low=3400), Rows(history())))
    assert len(new) == 1
    ns["DEDUP_FILE"].data = pending  # simulate already-produced signature
    assert dedup(detect(snapshot(low=3400), Rows(history())))[0] == []
    assert all(isinstance(v, str) for day in pending.values() for v in day.values())


def capture_render(ns, alerts, success=True):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(stdout="TEST_SENT" if success else "", stderr="", returncode=0)
    ns["subprocess"] = SimpleNamespace(run=fake_run)
    assert ns["send_alert"](alerts) is success
    assert len(calls) == 1 and calls[0][0][1] == "never-execute-notify.py"
    assert calls[0][1]["timeout"] == 60
    converter = load_functions(ROOT / "scripts/notify.py", {"_html_to_text"}, {"re": re})["_html_to_text"]
    return calls[0][0][3], converter(calls[0][0][3])


def test_nine_descriptions_and_markup_survive(ns):
    alerts = [{"desc": f"跌破20日低 指数{i} 当日低0.00 < 20日低3500.00", "tier": "normal"}
              for i in range(9)]
    body, text = capture_render(ns, alerts)
    assert body.count("<li>") == body.count("</li>") == 9
    assert "<h3>" in body and "<ul>" in body and "</ul>" in body
    assert "<h3>" not in text and "<li>" not in text
    assert all(a["desc"] in text for a in alerts)
    assert text.count("跌破20日低") == 9


@pytest.mark.parametrize("desc", ["A < B > C & D '单' \"双\"", "<script>alert('x')</script>",
                                 "急涨≥3% 指数上证 +3.25%", "急跌≥3% 指数上证 -3.25%",
                                 "突破20日高 指数上证 当日高4100.00 > 20日高4000.00"])
def test_dynamic_desc_is_text_and_quotes_unchanged(ns, desc):
    body, text = capture_render(ns, [{"desc": desc, "tier": "normal"}])
    assert f"<li>[普通] {html.escape(desc, quote=False)}</li>" in body
    assert desc in text
    assert "&quot;" not in body and "&#x27;" not in body


def test_delivery_failure_and_retry_keep_payload_and_signature(ns):
    alert = {"type": "breakout_down", "kind": "指数", "name": "上证", "desc": "低 < 3500", "tier": "normal"}
    _, signature = ns["filter_and_record"]([alert])
    ns["DEDUP_FILE"].data = signature
    pending = []
    ns["stage_email_pending"] = lambda alerts: pending.extend(alerts)
    capture_render(ns, [alert], success=False)
    assert ns["send_or_stage"]([alert]) is False and pending == [alert]
    ns["_load_email_pending"] = lambda: {"key": alert} if pending else {}
    ns["_write_email_pending"] = lambda value: pending.clear()
    ns["retry_pending_emails"]()
    assert pending == [alert] and ns["DEDUP_FILE"].data == signature
    capture_render(ns, [alert])
    ns["retry_pending_emails"]()
    assert pending == [] and ns["DEDUP_FILE"].data == signature


def test_empty_alert_does_not_send(ns):
    assert ns["send_alert"]([]) is False


def test_recorded_nine_descriptions(ns):
    # Saved 2026-11-10 09:31 incident descriptions; no private runtime file dependency.
    descriptions = ['跌破20日低 指数上证指数 当日低0.00 < 20日低3574.27', '跌破20日低 指数深证成指 当日低0.00 < 20日低10810.42', '跌破20日低 指数沪深300 当日低0.00 < 20日低3958.14', '跌破20日低 指数上证50 当日低0.00 < 20日低2676.64', '跌破20日低 指数中证500 当日低0.00 < 20日低6253.79', '跌破20日低 指数中证1000 当日低0.00 < 20日低6136.52', '跌破20日低 指数创业板指 当日低0.00 < 20日低2376.28', '跌破20日低 指数科创50 当日低0.00 < 20日低1132.33', '跌破20日低 指数北证50 当日低0.00 < 20日低847.36']
    _, text = capture_render(ns, [{"desc": d, "tier": "normal"} for d in descriptions])
    assert all(d in text for d in descriptions)
    assert text.count("跌破20日低") == 9
