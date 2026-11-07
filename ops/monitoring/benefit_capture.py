#!/usr/bin/env python3
"""Opt-in, local DB + sidecar capture. No network, credentials or notifications.

The policy is an explicit required inventory, not discovery of whatever happens
to exist. Its pins/as-of are supplied by the existing producer/archive context.
Missing pins remain unknown; bytes copied successfully do not prove delivery.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import fcntl
import math
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid

SCHEMA = "trade-benefit-capture-v1"
CHAIN = "backup_isolated_restore"
OBJECT = "backup_db_freeze_map_restore"
SIGNALS = {"buy_backup": 0, "buy": 1, "buy_aux": 2, "buy_special": 3}


class CaptureError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    max_bytes: int
    max_sets: int
    file_bytes: int = 256 * 1024 * 1024
    json_bytes: int = 8 * 1024 * 1024
    min_free_bytes: int = 128 * 1024 * 1024
    seconds: float = 30

    def validate(self):
        for value in (self.max_bytes, self.max_sets, self.file_bytes, self.json_bytes, self.min_free_bytes):
            if type(value) is not int or value < 1:
                raise CaptureError("positive_explicit_resource_budgets_required")
        if not math.isfinite(self.seconds) or not 0 < self.seconds <= 300:
            raise CaptureError("timeout_must_be_positive_at_most_300_seconds")
        return self


_BUDGET = ContextVar("benefit_resource_budget", default=None)


class Budget:
    def __init__(self, limits):
        if limits is None:
            raise CaptureError("explicit_resource_budgets_required")
        self.limits = limits.validate()
        self.deadline = time.monotonic() + limits.seconds
        self.existing_bytes, self.pending = 0, None

    def tick(self):
        if time.monotonic() >= self.deadline:
            raise CaptureError("operation_deadline_exceeded")

    def size(self, path, *, json_file=False):
        self.tick()
        st = Path(path).stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > (self.limits.json_bytes if json_file else self.limits.file_bytes):
            raise CaptureError("file_size_or_type_budget_exceeded")
        return st.st_size

    def space(self, directory, needed=0):
        self.tick()
        if shutil.disk_usage(directory).free < self.limits.min_free_bytes + needed:
            raise CaptureError("free_space_reserve_exceeded")

    def usage(self):
        self.tick()
        if self.pending is not None:
            total = sum(self.size(p) for p in self.pending.iterdir())
            if self.existing_bytes + total > self.limits.max_bytes:
                raise CaptureError("capture_bytes_budget_exceeded")
            self.space(self.pending)


@contextmanager
def budget_scope(limits):
    budget = Budget(limits)
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def tick():
    if _BUDGET.get() is not None:
        _BUDGET.get().tick()


def sql_budget(con):
    last_space_check = [time.monotonic()]
    def progress():
        try:
            tick()
            budget = _BUDGET.get()
            if budget and time.monotonic() - last_space_check[0] >= 0.25:
                budget.space(Path(tempfile.gettempdir()))
                budget.usage()
                last_space_check[0] = time.monotonic()
            return 0
        except CaptureError:
            return 1
    con.set_progress_handler(progress, 10000)


def resource_arguments(ap, stage):
    prefix = "OPS_BENEFIT_CAPTURE" if stage == "backup" else "OPS_BENEFIT_RESTORE"
    ap.add_argument("--max-bytes", default=os.environ.get(prefix + "_MAX_BYTES"))
    ap.add_argument("--max-sets", default=os.environ.get("OPS_BENEFIT_CAPTURE_MAX_SETS"))
    ap.add_argument("--max-file-bytes", default=os.environ.get("OPS_BENEFIT_MAX_FILE_BYTES", str(256 * 1024 * 1024)))
    ap.add_argument("--max-json-bytes", default=os.environ.get("OPS_BENEFIT_MAX_JSON_BYTES", str(8 * 1024 * 1024)))
    ap.add_argument("--min-free-bytes", default=os.environ.get("OPS_BENEFIT_MIN_FREE_BYTES", str(128 * 1024 * 1024)))
    ap.add_argument("--timeout-seconds", default=os.environ.get("OPS_BENEFIT_TIMEOUT_SECONDS", "30"))
    ap.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)


def limits_from_args(args, stage):
    try:
        return Limits(int(args.max_bytes), int(args.max_sets) if stage == "backup" else 1,
                      int(args.max_file_bytes), int(args.max_json_bytes), int(args.min_free_bytes),
                      float(args.timeout_seconds)).validate()
    except (ValueError, TypeError):
        raise CaptureError("explicit_valid_resource_budgets_required") from None


def bounded_cli(command, seconds, data_root, stage):
    """Parent watchdog surrounds ALL worker IO/SQL/hash/copy/receipt work.
    The worker spawns no children. A killed partial is never treated as complete;
    capture admission refuses unknown/pending entries instead of growing them.
    """
    try:
        seconds = float(seconds)
        if not math.isfinite(seconds) or not 0 < seconds <= 300:
            raise ValueError()
        run = subprocess.run(command, capture_output=True, text=True, timeout=seconds)
        sys.stdout.write(run.stdout)
        sys.stderr.write(run.stderr)
        if run.returncode >= 0:
            return run.returncode
        reason = "optional_worker_interrupted"
    except subprocess.TimeoutExpired:
        reason = "optional_worker_total_timeout"
    except (ValueError, OSError):
        reason = "optional_worker_invalid_limit_or_start_failure"
    result = {"status": "unknown", "reason": reason, "restore_status": "not_verified", "remote_coverage": "unknown",
              "attempt_id": str(uuid.uuid4()), "evaluated_at": now()}
    result["receipt"] = emit(data_root, stage, result)
    print(json.dumps(result, sort_keys=True))
    return 1


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha_file(path):
    h = hashlib.sha256()
    budget = _BUDGET.get()
    if budget:
        budget.size(path)
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            tick()
            h.update(part)
    return h.hexdigest()


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise CaptureError("duplicate_json_key")
            out[key] = value
        return out
    def invalid(_):
        raise CaptureError("non_finite_json")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    canonical(value)  # Also reject overflow such as 1e999.
    return value


def atomic_json(path, value):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        payload = canonical(value) + b"\n"
        budget = _BUDGET.get()
        if budget:
            if len(payload) > budget.limits.json_bytes:
                raise CaptureError("json_size_budget_exceeded")
            budget.space(path.parent, len(payload))
        with os.fdopen(fd, "wb") as f:
            fd = None
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fsync_dir(path.parent)
    finally:
        if fd is not None:
            os.close(fd)
        if os.path.exists(tmp):
            os.unlink(tmp)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stamp(path):
    s = Path(path).stat()
    if not stat.S_ISREG(s.st_mode):
        raise CaptureError("not_regular_file")
    return {"device": s.st_dev, "inode": s.st_ino, "size": s.st_size,
            "mtime_ns": s.st_mtime_ns, "ctime_ns": s.st_ctime_ns}


def stable_bytes(path):
    before = stamp(path)
    budget = _BUDGET.get()
    maximum = budget.limits.json_bytes if budget else 8 * 1024 * 1024
    if before["size"] > maximum:
        raise CaptureError("json_size_budget_exceeded")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise CaptureError("not_regular_file")
        parts, total = [], 0
        while True:
            tick()
            part = f.read(min(1024 * 1024, maximum + 1 - total))
            if not part:
                break
            parts.append(part)
            total += len(part)
            if total > maximum:
                raise CaptureError("json_size_budget_exceeded")
        raw = b"".join(parts)
    after = stamp(path)
    if before != after or len(raw) != before["size"]:
        raise CaptureError("source_changed_during_read")
    return raw, before


def owned_set_bytes(directory):
    """Inspect flat owned sets for accounting only. Never delete any entry."""
    if directory.is_symlink() or not directory.is_dir():
        raise CaptureError("unaccounted_capture_entry")
    try:
        if str(uuid.UUID(directory.name)) != directory.name:
            raise ValueError()
        mp = directory / "manifest.json"
        raw, _ = stable_bytes(mp)
        manifest = strict_json(raw)
        if manifest["schema"] != SCHEMA or manifest["capture_set_id"] != directory.name:
            raise ValueError()
        validate_policy(manifest["policy"])
        specs = manifest["policy"]["artifacts"]
        expected = {"manifest.json"} | {filename(a) for a in specs}
        if set(manifest["artifacts"]) != {a["id"] for a in specs}:
            raise ValueError()
        for a in specs:
            record = manifest["artifacts"][a["id"]]
            if record["capture_set_id"] != directory.name or record["file"] != filename(a):
                raise ValueError()
        paths = list(directory.iterdir())
        if {p.name for p in paths} != expected:
            raise ValueError()
        total = 0
        for p in paths:
            tick()
            s = p.lstat()
            if not stat.S_ISREG(s.st_mode):
                raise ValueError()
            total += s.st_size
        return total
    except (OSError, ValueError, KeyError, TypeError):
        raise CaptureError("unaccounted_capture_entry") from None


@contextmanager
def capture_admission(export_root, sources, policy_raw):
    budget = _BUDGET.get()
    if budget is None:
        raise CaptureError("explicit_resource_budgets_required")
    fd = os.open(export_root / ".capture.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        lock_stat = os.fstat(fd)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_size != 0 or lock_stat.st_nlink != 1:
            raise CaptureError("invalid_capture_lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CaptureError("capture_already_running") from None
        used, count = 0, 0
        for entry in export_root.iterdir():
            if entry.name == ".capture.lock":
                continue
            count += 1
            if count > budget.limits.max_sets:
                raise CaptureError("capture_set_count_exceeded")
            used += owned_set_bytes(entry)
        if count >= budget.limits.max_sets:
            raise CaptureError("capture_set_count_exceeded")
        # Conservative WAL reservation before any new DB copy. Snapshot page
        # count and progress checks below also enforce limits if WAL grows.
        reserve = len(policy_raw) + 65536
        for source in sources.values():
            reserve += budget.size(source)
            wal = source.with_name(source.name + "-wal")
            if source.suffix == ".db" and wal.exists():
                reserve += budget.size(wal)
        if used + reserve > budget.limits.max_bytes:
            raise CaptureError("capture_bytes_budget_exceeded")
        budget.space(export_root, reserve)
        budget.existing_bytes = used
        yield {"existing_sets": count, "existing_bytes": used, "reserved_bytes": reserve,
               "max_sets": budget.limits.max_sets, "max_bytes": budget.limits.max_bytes}
    finally:
        os.close(fd)  # Keep stable lock inode; no history/unknown/active GC.


def copy_bounded(src, dst):
    budget = _BUDGET.get()
    expected = budget.size(src)
    budget.space(Path(dst).parent, expected)
    with open(src, "rb") as reader, open(dst, "xb") as writer:
        copied = 0
        while True:
            tick()
            part = reader.read(1024 * 1024)
            if not part:
                break
            copied += len(part)
            if copied > budget.limits.file_bytes:
                raise CaptureError("copy_file_budget_exceeded")
            writer.write(part)
            budget.usage()
        writer.flush()
        os.fsync(writer.fileno())
    budget.usage()


def source_path(value):
    p = Path(value)
    if not p.is_absolute():
        raise CaptureError("source_path_must_be_absolute")
    p = p.resolve(strict=True)
    if any(x.startswith(".env") or x in {".ssh", ".aws", "credentials", "id_rsa", "id_ed25519"}
           for x in p.parts) or p.suffix.lower() in {".pem", ".key", ".p12"}:
        raise CaptureError("credential_path_forbidden")
    stamp(p)
    return p


def date8(value):
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except (ValueError, TypeError):
        raise CaptureError("invalid_session_date") from None


def instant(value):
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.utcoffset() is None:
            raise ValueError()
        return d
    except (ValueError, TypeError, AttributeError):
        raise CaptureError("as_of_requires_timezone") from None


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", value):
        raise CaptureError("invalid_identifier")
    return '"' + value + '"'


def validate_policy(policy):
    if not isinstance(policy, dict) or policy.get("schema") != SCHEMA:
        raise CaptureError("policy_schema")
    if not isinstance(policy.get("session_date"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", policy["session_date"]):
        raise CaptureError("session_date_requires_iso_date")
    date8(policy["session_date"].replace("-", ""))
    if not isinstance(policy.get("generation_id"), str) or not policy["generation_id"]:
        raise CaptureError("generation_id_required")
    artifacts = policy["artifacts"]
    if not isinstance(artifacts, list) or not all(isinstance(a, dict) for a in artifacts):
        raise CaptureError("artifact_inventory_type")
    ids = [a["id"] for a in artifacts]
    if len(ids) != len(set(ids)) or not all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", i) for i in ids):
        raise CaptureError("artifact_ids")
    kinds = [a["kind"] for a in artifacts]
    if not {"db", "freeze", "map", "config"}.issubset(kinds) or any(k not in {"db", "freeze", "map", "config"} for k in kinds):
        raise CaptureError("required_db_freeze_map_config")
    if kinds.count("freeze") != 1 or kinds.count("map") != 1:
        raise CaptureError("single_freeze_map_required")
    if any(filename(a) == "manifest.json" for a in artifacts):
        raise CaptureError("reserved_capture_filename")
    for a in artifacts:
        if a["generation_id"] != policy["generation_id"]:
            raise CaptureError("generation_mismatch")
        instant(a["as_of"])
        if "sha256" in a and (not isinstance(a["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", a["sha256"])):
            raise CaptureError("invalid_expected_sha256")
        if a["kind"] == "db":
            if not isinstance(a.get("tables"), dict) or not a["tables"]:
                raise CaptureError("required_tables_missing")
            for table, spec in a["tables"].items():
                ident(table)
                if not isinstance(spec, dict) or type(spec.get("min_rows")) is not int or spec["min_rows"] < 1:
                    raise CaptureError("positive_table_min_rows_required")
    b = policy["business"]
    if not isinstance(b, dict):
        raise CaptureError("business_policy_type")
    dbs = {a["id"] for a in artifacts if a["kind"] == "db"}
    if b["db_id"] not in dbs or not b.get("indexes") or not b.get("signals"):
        raise CaptureError("business_inventory_missing")
    if any(s not in SIGNALS for s in b["signals"]):
        raise CaptureError("unsupported_signal")
    ident(b["table"])
    if b["table"] not in next(a for a in artifacts if a["id"] == b["db_id"])["tables"]:
        raise CaptureError("business_table_not_in_required_tables")
    date8(b["start_date"])
    date8(b["cutoff_date"])
    if b["start_date"] > b["cutoff_date"] or b["cutoff_date"] != policy["session_date"].replace("-", ""):
        raise CaptureError("business_date_range")


def filename(artifact):
    return artifact["id"] + (".db" if artifact["kind"] == "db" else ".json" if artifact["kind"] in {"freeze", "map"} else ".config")


def connect_ro(path, *, immutable=False):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else ""), uri=True)


def snapshot_db(src, dst, timeout=60):
    deadline = time.monotonic() + timeout
    def progress(*_):
        tick()
        if _BUDGET.get():
            _BUDGET.get().usage()
        if time.monotonic() > deadline:
            raise CaptureError("snapshot_timeout")
    with closing(connect_ro(src)) as reader, closing(sqlite3.connect(dst)) as writer:
        reader.execute("PRAGMA query_only=ON")
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM sqlite_schema").fetchone()  # Pin read transaction, includes committed WAL.
        budget = _BUDGET.get()
        if budget:
            size = reader.execute("PRAGMA page_count").fetchone()[0] * reader.execute("PRAGMA page_size").fetchone()[0]
            if size > budget.limits.file_bytes:
                raise CaptureError("snapshot_file_budget_exceeded")
            budget.space(Path(dst).parent, size)
        reader.backup(writer, pages=256, progress=progress, sleep=0.01)
        writer.execute("PRAGMA journal_mode=DELETE").fetchone()
        reader.rollback()
    os.chmod(dst, 0o600)
    with open(dst, "rb") as f:
        os.fsync(f.fileno())


def db_summary(path, tables):
    out = {}
    with closing(connect_ro(path, immutable=True)) as con:
        sql_budget(con)
        con.execute("PRAGMA cache_size=-4096")
        con.execute("PRAGMA temp_store=FILE")
        budget = _BUDGET.get()
        if budget:
            budget.space(Path(tempfile.gettempdir()), 2 * budget.size(path))
        if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise CaptureError("sqlite_integrity")
        for table, spec in tables.items():
            columns = con.execute(f"PRAGMA table_info({ident(table)})").fetchall()
            if not columns:
                raise CaptureError("required_table_missing")
            names = [c[1] for c in columns]
            # Hash actual transaction rows, never the live .db file without WAL.
            h, count = hashlib.sha256(), 0
            for row in con.execute(f"SELECT * FROM {ident(table)} ORDER BY " + ",".join(ident(n) for n in names)):
                tick()
                if budget and sum(len(v) * (2 if isinstance(v, bytes) else 4) if isinstance(v, (bytes, str)) else 32 for v in row) > budget.limits.json_bytes:
                    raise CaptureError("db_row_size_budget_exceeded")
                values = [{"sqlite_blob_hex": v.hex()} if isinstance(v, bytes) else v for v in row]
                h.update(canonical(values) + b"\n")
                count += 1
            summary = {"rows": count, "rows_sha256": h.hexdigest(), "schema_sha256": digest(columns)}
            if spec.get("date_column"):
                summary["max_date"] = con.execute(f"SELECT MAX({ident(spec['date_column'])}) FROM {ident(table)}").fetchone()[0]
            out[table] = summary
    return out


def check_business(root, policy):
    """Independent read-only consumer of captured native signal/freeze/map shapes.

    Historical selections come only from freeze; today's highest score is never
    used to refreeze. Explicit expected_selections may pin audit-approved keys.
    """
    by_kind = {a["kind"]: a for a in policy["artifacts"] if a["kind"] != "db"}
    freeze = strict_json(stable_bytes(root / filename(by_kind["freeze"]))[0])
    mapping = strict_json(stable_bytes(root / filename(by_kind["map"]))[0])
    if not isinstance(freeze, dict) or not isinstance(mapping, dict):
        raise CaptureError("sidecar_shape")
    b = policy["business"]
    db = next(a for a in policy["artifacts"] if a["id"] == b["db_id"])
    with closing(connect_ro(root / filename(db), immutable=True)) as con:
        sql_budget(con)
        eligible = []
        for r in con.execute(f"SELECT date,index_id,signal FROM {ident(b['table'])} WHERE date BETWEEN ? AND ? ORDER BY date,index_id,signal",
                             (b["start_date"], b["cutoff_date"])):
            tick()
            if r[1] in b["indexes"] and r[2] in b["signals"]:
                eligible.append(r)
                if _BUDGET.get() and len(eligible) * 128 > _BUDGET.get().limits.json_bytes:
                    raise CaptureError("business_selection_budget_exceeded")
    if not eligible or max(r[0] for r in eligible) != b["cutoff_date"]:
        raise CaptureError("required_business_rows_or_cutoff_missing")
    selected = {}
    for date, iid, signal in eligible:
        key = f"{date}|{iid}|{signal}"
        entry = freeze.get(key)
        source_key = key
        if entry is None:  # Match the existing typed fallback, never current map.
            candidates = [(SIGNALS.get(k.split("|")[-1], 9), k, v) for k, v in freeze.items()
                          if k.startswith(f"{date}|{iid}|") and len(k.split("|")) == 3]
            if candidates:
                _, source_key, entry = min(candidates, key=lambda v: (v[0], v[1]))
        if not isinstance(entry, dict) or not isinstance(entry.get("code"), str) or not entry["code"]:
            raise CaptureError("required_freeze_key_or_code_missing")
        if not isinstance(entry.get("frozen_at"), str) or not entry["frozen_at"]:
            raise CaptureError("frozen_at_missing")
        if not isinstance(mapping.get(iid), list) or not mapping[iid] or not any(isinstance(c, dict) and c.get("track_score") is not None and c.get("code") for c in mapping[iid]):
            raise CaptureError("required_map_index_missing")
        expected = b.get("expected_selections", {}).get(key)
        if expected is not None and expected != entry["code"]:
            raise CaptureError("frozen_selection_mismatch")
        selected[key] = {"source_key": source_key, "code": entry["code"]}
    for key, code in b.get("expected_selections", {}).items():
        if key not in selected or selected[key]["code"] != code:
            raise CaptureError("expected_business_key_missing")
    return {"required_keys": len(selected), "selection_sha256": digest(selected),
            "db_cutoff_date": b["cutoff_date"], "reader": "capture_native_validator_v1"}


def assess(root, policy, artifacts, captured_at):
    unknown = []
    for spec in policy["artifacts"]:
        record = artifacts[spec["id"]]
        if record["generation_id"] != policy["generation_id"] or record["as_of"] != spec["as_of"]:
            raise CaptureError("artifact_generation_or_as_of_mismatch")
        if instant(spec["as_of"]) > instant(captured_at):
            raise CaptureError("as_of_after_capture")
        path = root / filename(spec)
        if spec["kind"] == "db":
            actual = db_summary(path, spec["tables"])
            if record.get("tables") != actual:
                raise CaptureError("db_summary_mismatch")
            for table, req in spec["tables"].items():
                got = actual[table]
                if got["rows"] < req["min_rows"]:
                    raise CaptureError("required_table_rows_missing")
                for field in ("rows_sha256", "schema_sha256", "max_date"):
                    expected = req.get(field)
                    if expected is not None and got.get(field) != expected:
                        raise CaptureError("db_expected_" + field + "_mismatch")
                if not req.get("rows_sha256"):
                    unknown.append(spec["id"] + ":table_identity_unpinned:" + table)
        else:
            if spec.get("sha256") and record["sha256"] != spec["sha256"]:
                raise CaptureError("sidecar_expected_hash_mismatch")
            if not spec.get("sha256"):
                unknown.append(spec["id"] + ":identity_unpinned")
    business = check_business(root, policy)
    return {"status": "unknown" if unknown else "validated", "limitations": unknown,
            "business": business}


def _capture(policy_path, export_root, *, policy_bytes=None):
    started = now()
    raw = policy_bytes if policy_bytes is not None else stable_bytes(source_path(policy_path))[0]
    policy = strict_json(raw)
    validate_policy(policy)
    sources = {a["id"]: source_path(a["path"]) for a in policy["artifacts"]}
    export_root = Path(export_root).resolve()
    if any(export_root == p or p.is_relative_to(export_root) for p in sources.values()):
        raise CaptureError("capture_root_overlaps_sources")
    export_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with capture_admission(export_root, sources, raw) as admission:
        return _capture_locked(policy, sources, export_root, started, raw, admission)


def _capture_locked(policy, sources, export_root, started, raw, admission):
    capture_id = str(uuid.uuid4())
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=export_root))
    budget = _BUDGET.get()
    budget.pending = pending
    try:
        artifacts, checks = {}, {}
        # Read all sidecars before DB snapshots; verify them again after all
        # snapshots. A changing JSON/config cannot silently straddle DB capture.
        for a in policy["artifacts"]:
            if a["kind"] == "db":
                continue
            payload, before = stable_bytes(sources[a["id"]])
            if a["kind"] in {"freeze", "map"}:
                strict_json(payload)
            target = pending / filename(a)
            budget.space(pending, len(payload))
            target.write_bytes(payload)
            os.chmod(target, 0o600)
            budget.usage()
            checks[a["id"]] = (before, hashlib.sha256(payload).hexdigest())
        summaries = {}
        for a in policy["artifacts"]:
            if a["kind"] == "db":
                target = pending / filename(a)
                snapshot_db(sources[a["id"]], target)
                summaries[a["id"]] = db_summary(target, a["tables"])
        for a in policy["artifacts"]:
            target = pending / filename(a)
            source = sources[a["id"]]
            source_identity = {"path": str(source)}
            if a["kind"] == "db":
                source_identity["method"] = "sqlite_read_transaction_backup_api_including_committed_wal"
            else:
                payload, after = stable_bytes(source)
                before, expected = checks[a["id"]]
                if before != after or hashlib.sha256(payload).hexdigest() != expected:
                    raise CaptureError("source_changed_across_capture")
                source_identity.update({"before": before, "after": after, "method": "stable_bytes_before_and_after_db_snapshots"})
            artifacts[a["id"]] = {"capture_set_id": capture_id, "file": filename(a), "kind": a["kind"],
                                  "sha256": sha_file(target), "size": target.stat().st_size,
                                  "observed_at": now(),
                                  "generation_id": a["generation_id"], "as_of": a["as_of"],
                                  "source": source_identity}
            if a["kind"] == "db":
                artifacts[a["id"]]["tables"] = summaries[a["id"]]
        assessment = assess(pending, policy, artifacts, started)
        manifest = {"schema": SCHEMA, "capture_set_id": capture_id, "session_date": policy["session_date"],
                    "started_at": started, "completed_at": now(), "policy": policy, "policy_sha256": hashlib.sha256(raw).hexdigest(),
                    "artifacts": artifacts, "assessment": assessment,
                    "resource_admission": admission,
                    "remote_coverage": {"status": "unknown", "reason": "matched_set_archive_evidence_not_connected"},
                    "restore_status": "not_verified"}
        for p in pending.iterdir():
            with p.open("rb") as f:
                os.fsync(f.fileno())
        atomic_json(pending / "manifest.json", manifest)
        budget.usage()
        final = export_root / capture_id
        os.rename(pending, final)
        fsync_dir(export_root)
        return final / "manifest.json", manifest
    finally:
        if pending.exists():
            shutil.rmtree(pending)


def capture(policy_path, export_root, *, policy_bytes=None, limits=None):
    with budget_scope(limits):
        return _capture(policy_path, export_root, policy_bytes=policy_bytes)


def emit(data_root, stage, result, manifest=None, manifest_sha=None):
    """Receipt errors are metadata failures and never change original backup RC."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from delivery_evidence import emit_receipt
        identities = []
        if manifest:
            identities = [{"object_id": key, "sha256": a["sha256"], "identity_kind": "bytes",
                           "quality": "strong", "observed_at": result["evaluated_at"] if stage == "restore" else a["observed_at"],
                           "source_at": result["evaluated_at"] if stage == "restore" else a["observed_at"],
                           "as_of": a["as_of"],
                           "session_date": manifest["session_date"], "capture_set_id": manifest["capture_set_id"]}
                          for key, a in manifest["artifacts"].items()]
        if manifest_sha:
            identities.append({"object_id": "capture_manifest", "sha256": manifest_sha, "identity_kind": "bytes",
                               "quality": "strong", "observed_at": result["evaluated_at"],
                               "source_at": result["evaluated_at"], "session_date": manifest["session_date"],
                               "capture_set_id": manifest["capture_set_id"]})
        code_files = {name: sha_file(Path(__file__).with_name(name))
                      for name in ("benefit_capture.py", "benefit_restore.py")}
        session = result.get("session_date", "unknown")
        return emit_receipt(data_root=data_root, stage=stage, chain_id=CHAIN, object_id=OBJECT,
                            session_date=result.get("session_date", "unknown"), attempt_id=result["attempt_id"],
                            batch_id=CHAIN + ":" + session if session != "unknown" else "unknown",
                            stage_status="failure" if result["status"] == "failure" else "unknown",
                            reason=result["reason"], inputs=identities if stage == "restore" else (),
                            outputs=identities if stage == "backup" else result.get("outputs", []),
                            config_identity={"sha256": manifest["policy_sha256"]} if manifest else None,
                            code_identity={"sha256": digest(code_files), "files": code_files},
                            counts={"capture_files": len(identities)},
                            consumer_witness=result.get("consumer_witness"),
                            evaluated_at=result["evaluated_at"],
                            producer_time={"started_at": result.get("started_at", "unknown"), "completed_at": result["evaluated_at"]},
                            events=[{"kind": "capture_set_validation", "capture_set_id": result.get("capture_set_id", "unknown"),
                                     "manifest_sha256": manifest_sha or "unknown",
                                     "local_capture_status": manifest["assessment"]["status"] if manifest else "unknown",
                                     "isolated_restore_status": result.get("restore_status", "not_verified"),
                                     "offsite_status": "unknown", "production_consumer_status": "unknown"}],
                            evidence_quality="strong" if manifest else "unknown")
    except Exception as e:
        print("benefit receipt metadata_failure: " + type(e).__name__, file=sys.stderr)
        return {"status": "metadata_failure", "reason": type(e).__name__}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy", type=Path, default=os.environ.get("OPS_BENEFIT_CAPTURE_POLICY"))
    ap.add_argument("--export-root", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    resource_arguments(ap, "backup")
    args = ap.parse_args(argv)
    if os.environ.get("OPS_DELIVERY_EVIDENCE_ENABLED") != "1":
        print('{"status":"disabled"}')
        return 0
    if not args._worker:
        return bounded_cli([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv), "--_worker"],
                           args.timeout_seconds, args.data_root, "backup")
    result = {"status": "unknown", "reason": "capture_policy_unconfigured", "restore_status": "not_verified",
              "remote_coverage": "unknown", "attempt_id": str(uuid.uuid4()), "evaluated_at": now()}
    manifest, msha = None, None
    if args.policy:
        try:
            limits = limits_from_args(args, "backup")
            with budget_scope(limits):
                raw, _ = stable_bytes(source_path(args.policy))
            policy = strict_json(raw)
            session = policy.get("session_date", "unknown") if isinstance(policy, dict) else "unknown"
            if isinstance(session, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", session):
                date8(session.replace("-", ""))
                result["session_date"] = session
            path, manifest = capture(args.policy, args.export_root, policy_bytes=raw, limits=limits)
            msha = sha_file(path)
            result.update({"session_date": manifest["session_date"], "capture_set_id": manifest["capture_set_id"],
                           "local_status": manifest["assessment"]["status"], "manifest_sha256": msha,
                           "started_at": manifest["started_at"],
                           "reason": "local_capture_only_remote_coverage_unknown"})
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
            result.update(status="failure", reason="capture_rejected:" + type(e).__name__)
            print("benefit capture rejected: " + str(e), file=sys.stderr)
    result["evaluated_at"] = now()
    result["receipt"] = emit(args.data_root, "backup", result, manifest, msha)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "failure" or result["receipt"]["status"] == "metadata_failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
