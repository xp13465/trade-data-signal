#!/usr/bin/env python3
"""Offline reconciliation of repository-declared schedules against explicit slots.

No systemctl, collectors, network, weekday calendar fallback or timeout-derived SLA.
Inputs are pinned claims, not authentication of deployment or business completion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import gen_schedule_stats as registry
import gen_systemd_units as units_parser

ROOT = Path(__file__).resolve().parent.parent
SOURCE = Path(units_parser.MD_REL_PATH)
REGISTRY = Path("scripts/gen_schedule_stats.py")
LIMIT = 32 * 1024 * 1024
MAX_SLOTS = 250000
MAX_DEADLINE_SECONDS = 366 * 86400
TZ = timezone(timedelta(hours=8))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("input_too_large")
    return raw


# Tie imported registry values to the code bytes loaded in this process. The
# entries hash additionally pins its generated rows (not a duplicate registry).
REGISTRY_LOADED_SHA256 = sha(read(Path(registry.__file__)))


def stamp(value):
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.utcoffset() != timedelta(hours=8):
        raise ValueError("Asia/Shanghai_offset_required")
    return at


def day(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("canonical_date_required")
    return parsed


def window(plan):
    start, end = stamp(plan["window_start"]), stamp(plan["window_end"])
    if not 1 <= (end - start).days <= 366 or start.time() != datetime.min.time() or end.time() != datetime.min.time():
        raise ValueError("bounded_whole_day_window_required")
    return start, end


def pinned(ref, root, hashes):
    path = Path(root) / ref["path"]
    raw = read(path)
    if sha(raw) != ref["sha256"]:
        raise ValueError("hash_mismatch:" + str(path))
    hashes[str(path)] = sha(raw)
    return raw


def fields(lines):
    """Retain repeated directives and systemd's empty-assignment list reset."""
    result, section = {}, None
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if not section or "=" not in line or line.endswith("\\"):
            raise ValueError("unsupported_unit_syntax")
        key, value = line.split("=", 1)
        entry = result.setdefault((section, key.strip()), [])
        if value.strip():
            entry.append(value.strip())
        else:
            entry.clear()
    return result


def numbers(expr, low, high):
    values = set()
    for part in expr.split(","):
        match = re.fullmatch(r"(\*|\d+)(?:\.\.(\d+))?(?:/(\d+))?", part)
        if not match:
            raise ValueError("unsupported_calendar_field:" + expr)
        first, last, step = match.groups()
        step = int(step or 1)
        begin = low if first == "*" else int(first)
        finish = int(last) if last else high if first == "*" or match[3] else begin
        if not low <= begin <= finish <= high or step < 1 or (first == "*" and last):
            raise ValueError("invalid_calendar_field:" + expr)
        values.update(range(begin, finish + 1, step))
    return sorted(values)


def expand(expression, start, end):
    """Bounded OnCalendar subset used by the repository; unsupported => unknown.

    Fixed +08:00 nominal triggers only, not systemd activation/catch-up semantics.
    """
    parts = expression.split()
    weekdays = set(range(7))
    if parts and re.match(r"[A-Za-z]", parts[0]):
        weekdays = set()
        for part in parts.pop(0).split(","):
            ends = part.split("..")
            if len(ends) > 2 or any(v not in WEEKDAYS for v in ends):
                raise ValueError("unsupported_weekday")
            first, last = WEEKDAYS.index(ends[0]), WEEKDAYS.index(ends[-1])
            if first > last:
                raise ValueError("unsupported_weekday_range")
            weekdays.update(range(first, last + 1))
    if len(parts) == 1:
        parts.insert(0, "*-*-*")
    if len(parts) != 2:
        raise ValueError("unsupported_OnCalendar:" + expression)
    date_fields, time_fields = parts[0].split("-"), parts[1].split(":")
    if len(date_fields) != 3 or len(time_fields) != 3:
        raise ValueError("unsupported_OnCalendar:" + expression)
    year, month, monthday = date_fields
    if year != "*" and not re.fullmatch(r"[0-9]{4}", year):
        raise ValueError("unsupported_year")
    months, days = numbers(month, 1, 12), numbers(monthday, 1, 31)
    hours, minutes, seconds = (numbers(s, 0, hi) for s, hi in zip(time_fields, (23, 59, 59)))
    result = set()
    current = start
    while current < end:
        if current.weekday() in weekdays and (year == "*" or int(year) == current.year) and current.month in months and current.day in days:
            for h in hours:
                for m in minutes:
                    for s in seconds:
                        result.add(current.replace(hour=h, minute=m, second=s).isoformat())
                        if len(result) > MAX_SLOTS:
                            raise ValueError("slot_limit_exceeded")
        current += timedelta(days=1)
    return result


def inventory(contract, hashes):
    """Use the same parser and live registry as the existing unit drift gate."""
    for name, relative in (("source", SOURCE), ("registry", REGISTRY)):
        if contract[name]["path"] != relative.as_posix():
            raise ValueError("canonical_" + name + "_path_required")
        raw = pinned(contract[name], ROOT, hashes)
        if name == "registry" and sha(raw) != REGISTRY_LOADED_SHA256:
            raise ValueError("registry_code_changed_since_import")
    rows = registry.UNIT_REGISTRY
    if contract["registry"].get("entries_sha256") != sha(canonical(rows)):
        raise ValueError("registry_entries_hash_mismatch")
    raw = read(ROOT / SOURCE)
    if sha(raw) != contract["source"]["sha256"]:
        raise ValueError("schedule_source_changed_during_read")
    order, units = units_parser.parse_units(str(ROOT / SOURCE))
    titles = [m[1] for line in raw.decode().splitlines() if (m := units_parser.TITLE_RE.match(line.strip()))]
    if not order or len(titles) != len(set(titles)) or titles != order:
        raise ValueError("duplicate_or_unparsed_unit_title")
    if len(rows) != len({r["unit"] for r in rows}) or len(rows) != len({r["task"] for r in rows}):
        raise ValueError("duplicate_registry_identity")
    services = {name for name in units if name.endswith(".service")}
    if services != {r["unit"] for r in rows}:
        raise ValueError("registry_service_set_mismatch")
    if {name for name in units if name.endswith(".timer")} != {name.removesuffix(".service") + ".timer" for name in services}:
        raise ValueError("timer_service_set_mismatch")
    return rows, units


def calendar(contract, root, hashes, start, end):
    value = json.loads(pinned(contract["calendar"], root, hashes))
    if (value["schema"] != "ops-trading-calendar-v1" or value["timezone"] != "Asia/Shanghai"
            or not isinstance(value["source"], str) or not value["source"].strip()):
        raise ValueError("explicit_calendar_source_required")
    first, last = day(value["coverage_start"]), day(value["coverage_end"])
    if not first <= start.date() < end.date() <= last:
        raise ValueError("calendar_coverage_missing")
    dates = value["trading_dates"]
    if not isinstance(dates, list) or len(dates) != len(set(dates)):
        raise ValueError("invalid_calendar_dates")
    if any(not first <= day(d) < last for d in dates):
        raise ValueError("calendar_date_outside_coverage")
    return sorted(dates)


def deadlines(contract, root, hashes, start):
    value = json.loads(pinned(contract["deadlines"], root, hashes))
    if (value["schema"] != "ops-business-deadlines-v1" or value["kind"] != "business_contract"
            or not isinstance(value["source"], str) or not value["source"].strip() or stamp(value["approved_at"]) > start):
        raise ValueError("explicit_approved_business_contract_required")
    rules = value["after_seconds_by_task"]
    if not isinstance(rules, dict) or any(type(v) is not int or not 0 < v <= MAX_DEADLINE_SECONDS for v in rules.values()):
        raise ValueError("invalid_deadline_rules")
    return rules


def reconcile(plan, root):
    """Return uncertainty as data, even for malformed/missing pinned inputs."""
    result = {"schema": "ops-schedule-reconciliation-v1", "scope": "repository-declared",
              "denominator_completeness": "unknown", "business_deadline_coverage": "unknown",
              "actual_systemd_deployment": "NOT_VERIFIED", "execution_coverage_satisfied": None,
              "expected_slots": [], "tasks": [], "missing_slots": [], "extra_slots": [],
              "duplicate_slots": [], "mismatched_slots": [], "issues": [], "input_hashes": {}}
    issues, hashes = result["issues"], result["input_hashes"]
    try:
        start, end = window(plan)
        contract = plan["schedule_contract"]
        result["contract_sha256"] = sha(canonical(contract))
        if contract["schema"] != "ops-schedule-contract-v1" or contract["scope"] != "repository-declared" or contract["timezone"] != "Asia/Shanghai":
            raise ValueError("explicit_repository_contract_required")
        if plan.get("status") != "frozen" or not stamp(plan["generated_at"]) <= stamp(plan["frozen_at"]) <= start:
            issues.append("schedule_contract_not_pre_frozen")
        rows, units = inventory(contract, hashes)
        result["registry_tasks"] = len(rows)
        result["timer_units"] = sum(name.endswith(".timer") for name in units)
        try:
            trading = calendar(contract, root, hashes, start, end)
            expected_dates = [d for d in trading if start.date() <= day(d) < end.date()]
            if sorted(plan["trading_dates"]) != expected_dates:
                issues.append("plan_trading_dates_mismatch")
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            trading = None
            issues.append("calendar_unknown:" + str(exc))
        try:
            budgets = deadlines(contract, root, hashes, start)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            budgets = {}
            result["deadline_issue"] = str(exc)
        policies = contract["tasks"]
        if not isinstance(policies, dict):
            raise ValueError("task_contract_mapping_required")
        task_names = {r["task"] for r in rows}
        if set(policies) != task_names:
            issues.append("task_contract_set_mismatch")
        if set(budgets) - task_names:
            issues.append("deadline_task_set_mismatch")
        for row in rows:
            task, service = row["task"], row["unit"]
            timer = service.removesuffix(".service") + ".timer"
            item = {"task_id": task, "service": service, "timer": timer, "status": "unknown", "reasons": []}
            result["tasks"].append(item)
            try:
                tf, sf = fields(units[timer]), fields(units[service])
                expressions = tf.get(("Timer", "OnCalendar"), [])
                item["on_calendar"] = expressions
                if tf.get(("Timer", "Unit"), [service]) != [service]:
                    raise ValueError("timer_target_mismatch")
                if not expressions or any(sec == "Timer" and key.startswith("On") and key != "OnCalendar" and values for (sec, key), values in tf.items()):
                    raise ValueError("unsupported_or_relative_timer")
                triggers = set()
                for expression in expressions:
                    triggers.update(expand(expression, start, end))
                    if len(triggers) > MAX_SLOTS:
                        raise ValueError("slot_limit_exceeded")
                item["nominal_trigger_count"] = len(triggers)
                if any(values and (key.startswith(("Condition", "Assert")) or key == "ExecCondition") for (_, key), values in list(tf.items()) + list(sf.items())):
                    raise ValueError("conditional_unit")
                policy = policies.get(task, {})
                if policy.get("eligibility") not in {"calendar", "trading"}:
                    raise ValueError("unknown_or_conditional_eligibility")
                if policy.get("business_date_rule") not in {"scheduled_date", "previous_trading_date"}:
                    raise ValueError("unknown_business_date_rule")
                if policy.get("eligibility") == "trading" and trading is None:
                    raise ValueError("trading_calendar_missing")
                expected = []
                for at in sorted(triggers):
                    local_day = at[:10]
                    if policy["eligibility"] == "trading" and local_day not in trading:
                        continue
                    business_day = local_day
                    if policy["business_date_rule"] == "previous_trading_date":
                        previous = [d for d in (trading or []) if d < local_day]
                        if not previous:
                            raise ValueError("previous_trading_date_unavailable")
                        business_day = previous[-1]
                    expected.append({"task_id": task, "scheduled_at": at, "business_date": business_day,
                                     "deadline": (stamp(at) + timedelta(seconds=budgets[task])).isoformat() if task in budgets else None})
                if len(result["expected_slots"]) + len(expected) > MAX_SLOTS:
                    raise ValueError("slot_limit_exceeded")
                result["expected_slots"].extend(expected)
                item.update(status="known", expected_slots=len(expected), deadline_status="explicit_contract" if task in budgets else "unknown")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                item["reasons"].append(str(exc))
        actual = plan["slots"]
        if not isinstance(actual, list) or len(actual) > MAX_SLOTS:
            raise ValueError("invalid_explicit_slots")
        by_key, ids = {}, Counter()
        for slot in actual:
            try:
                key = (slot["task_id"], stamp(slot["scheduled_at"]).isoformat())
                if not isinstance(key[0], str) or not isinstance(slot["slot_id"], str) or not slot["slot_id"]:
                    raise ValueError("slot_identity_required")
                ids[slot["slot_id"]] += 1
                if key in by_key:
                    result["duplicate_slots"].append(list(key))
                by_key[key] = slot
                day(slot["business_date"])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                issues.append("invalid_slot:" + str(exc))
        if any(count > 1 for count in ids.values()):
            issues.append("duplicate_slot_id")
        expected = {(s["task_id"], s["scheduled_at"]): s for s in result["expected_slots"]}
        result["missing_slots"] = [expected[k] for k in sorted(expected.keys() - by_key.keys())]
        result["extra_slots"] = [list(k) for k in sorted(by_key.keys() - expected.keys())]
        for key in sorted(expected.keys() & by_key.keys()):
            want, got = expected[key], by_key[key]
            mismatch = []
            if want["business_date"] != got["business_date"]:
                mismatch.append("business_date")
            if want["deadline"] is not None:
                try:
                    if stamp(got["deadline"]).isoformat() != want["deadline"]:
                        mismatch.append("deadline")
                except (ValueError, KeyError, TypeError, AttributeError):
                    mismatch.append("deadline")
            if mismatch:
                result["mismatched_slots"].append({"key": list(key), "fields": mismatch})
        for path, expected_hash in hashes.items():
            if sha(read(path)) != expected_hash:
                issues.append("input_changed_during_read:" + path)
        unknown = any(t["status"] == "unknown" for t in result["tasks"])
        mismatch = any(result[k] for k in ("missing_slots", "extra_slots", "duplicate_slots", "mismatched_slots"))
        result["denominator_completeness"] = "unknown" if issues or unknown else "incomplete" if mismatch else "complete"
        if not issues and not unknown and not mismatch and all(t["task_id"] in budgets for t in result["tasks"]):
            result["business_deadline_coverage"] = "complete"
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        issues.append(str(exc))
    result["expected_slot_count"] = len(result["expected_slots"])
    result["limitations"] = [
        "Nominal repository-declared triggers only; persistent catch-up, jitter, skips, runtime overrides and deployment are not verified.",
        "Calendar/eligibility/business-date/SLA inputs are pinned external claims, not independently authenticated business facts.",
        "Unknown/conditional tasks are retained; known expected slots are only a partial denominator while any task is unknown.",
        "TimeoutStartSec is never a business deadline; no publication receipts or execution success are proved here."]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--evidence-root", required=True, help="offline calendar/deadline reference directory")
    args = parser.parse_args(argv)
    try:
        raw = read(args.manifest)
        if sha(raw) != args.manifest_sha256:
            raise ValueError("manifest_hash_mismatch")
        result = reconcile(json.loads(raw), Path(args.evidence_root))
        result["manifest_sha256"] = sha(raw)
    except (OSError, ValueError, TypeError) as exc:
        result = {"scope": "repository-declared", "denominator_completeness": "unknown", "issues": [str(exc)],
                  "actual_systemd_deployment": "NOT_VERIFIED"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["denominator_completeness"] == "complete" else 2


if __name__ == "__main__":
    sys.exit(main())
