#!/usr/bin/env python3
"""Convert pinned immutable producer receipts to a C4 required-set policy.

No source DB/JSON/config is opened. A static profile declares required paths,
columns and business scope; it cannot supply observed pins, generation or as-of.
The context index names exact receipt hashes and exact input/output identities.
Existing loaded_object/ordered query digests cannot become source byte pins.

Usage (canonical local paths, new output filename):
  OPS_DELIVERY_EVIDENCE_ENABLED=1 python3 benefit_policy.py --data-root ROOT \
    --profile required-profile.json --context input-context.json --output new-policy.json
Exit: 0=ready/disabled, 3=unknown (no policy written), 2=CLI usage error.
Only ready writes a new exclusive 0600 policy. Output paths are never overwritten.

Profile schema trade-benefit-required-profile-v1:
 {profile_id, artifacts:[{id,kind,path,tables?:{table:{min_rows,columns,
 date_column?,require_session_max?}}}], business:{db_id,table,indexes,signals,
 start_date,expected_selections?}}. kind is db/freeze/map/config; paths absolute.
Context schema trade-benefit-input-context-v1:
 {session_date, generation_id, receipts:[{receipt_id,chain_id,sha256}],
 bindings:[{artifact_id,table?,receipt_id,collection:'inputs'|'outputs',object_id}]}.

Every selected identity needs strong quality, session_date, resolved_path,
generation_id, as_of and observed_at from the producer, not from this index.
Sidecars require identity_kind=bytes and SHA-256 of actual read/written bytes.
DB table rows require identity_kind=bytes, digest_domain=sqlite_table_rows,
digest_algorithm=trade-c4-table-rows-v1, and source_context:
 {method:'sqlite_read_transaction',scope:'full_table',transaction_id,table,
 columns,order_by:columns,row_count,includes_committed_wal:true,
 date_column?,max_date?,schema_sha256?}.
The bytes hashed are the actual C4 canonical full-table row stream (JSON array
per row + LF, ORDER BY every column), NEVER the live SQLite main file.

Hooke confirmed current production receipts DO NOT provide these full-table
digests or common generation/as-of. That input yields unknown. The typed DB
extension is a supported compatibility contract exercised with real temporary
WAL source reads in tests; it is not a claim that production emits it today.
Digests/metadata are a local producer trust boundary, not signed historical truth.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

from benefit_capture import SCHEMA, canonical, ident, instant, strict_json, validate_policy

PROFILE_SCHEMA = "trade-benefit-required-profile-v1"
CONTEXT_SCHEMA = "trade-benefit-input-context-v1"
ROWS_ALGORITHM = "trade-c4-table-rows-v1"
CHAINS = {"market_signal_freeze_plan", "backtest_publish_consume", "backup_isolated_restore"}
MAX_FILE = 64 * 1024
MAX_RECEIPTS = 16
MAX_BINDINGS = 64


class PolicyUnknown(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise PolicyUnknown(reason)


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def safe_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is not None


def source_name(value):
    """Compare producer paths as strings; never stat/resolve/open source files."""
    need(isinstance(value, str) and value.startswith("/"), "absolute_source_path_required")
    path = Path(value)
    need(".." not in path.parts, "source_path_traversal")
    need(not any(p in {"capture-sets", "capture-set"} or p.startswith(".pending-") for p in path.parts),
         "capture_copy_cannot_supply_source_pins")
    need(not any(p.startswith(".env") or p in {".ssh", ".aws", "credentials", "id_rsa", "id_ed25519"}
                 for p in path.parts) and path.suffix.lower() not in {".pem", ".key", ".p12"},
         "credential_path_forbidden")
    return str(path)


def checked_fields(obj, allowed, reason):
    need(isinstance(obj, dict) and not set(obj) - set(allowed), reason)


def validate_profile(profile):
    checked_fields(profile, {"schema", "profile_id", "artifacts", "business"}, "profile_fields")
    need(profile.get("schema") == PROFILE_SCHEMA and safe_id(profile.get("profile_id")), "profile_schema")
    artifacts = profile["artifacts"]
    need(isinstance(artifacts, list) and 4 <= len(artifacts) <= 16, "profile_inventory")
    for a in artifacts:
        checked_fields(a, {"id", "kind", "path", "tables"}, "profile_artifact_fields")
        source_name(a["path"])
        if a["kind"] == "db":
            need(isinstance(a.get("tables"), dict) and 0 < len(a["tables"]) <= 16, "profile_tables")
            for table, spec in a["tables"].items():
                ident(table)
                checked_fields(spec, {"min_rows", "columns", "date_column", "require_session_max"}, "profile_table_fields")
                columns = spec["columns"]
                need(isinstance(columns, list) and 0 < len(columns) <= 128 and len(set(columns)) == len(columns), "profile_columns")
                for column in columns:
                    ident(column)
                need(type(spec["min_rows"]) is int and spec["min_rows"] >= 1, "profile_min_rows")
                if "date_column" in spec:
                    need(spec["date_column"] in columns, "profile_date_column")
                if "require_session_max" in spec:
                    need(type(spec["require_session_max"]) is bool and "date_column" in spec, "profile_max_date")
        else:
            need("tables" not in a, "sidecar_profile_tables")
    checked_fields(profile["business"], {"db_id", "table", "indexes", "signals", "start_date", "expected_selections"}, "profile_business_fields")
    # Use the frozen C4 validator to enforce its inventory/business syntax, with
    # disposable markers solely for syntax validation, never for observed pins.
    draft = {"schema": SCHEMA, "session_date": "2000-01-01", "generation_id": "syntax-only",
             "artifacts": [dict(a, generation_id="syntax-only", as_of="2000-01-01T00:00:00Z") for a in artifacts],
             "business": dict(profile["business"], cutoff_date="20000101", start_date="20000101")}
    validate_policy(draft)


def validate_receipt(body, ref, session):
    need(isinstance(body, dict) and body.get("schema") == "trade-delivery-receipt-v1", "receipt_schema")
    need(body.get("receipt_id") == ref["receipt_id"] and body.get("chain_id") == ref["chain_id"], "receipt_identity_mismatch")
    need(body.get("session_date") == session, "receipt_session_mismatch")
    need(body.get("batch_id") == ref["chain_id"] + ":" + session, "receipt_batch_unknown")
    need(safe_id(body.get("attempt_id")) and body["attempt_id"] != "unknown", "receipt_attempt_unknown")
    need(body.get("stage") not in {"backup", "restore"} and body.get("stage") in {"signal", "freeze", "plan", "backtest", "publish", "consumer"},
         "capture_or_restore_cannot_supply_source_pins")
    need(body.get("stage_status") in {"success", "unknown"}, "source_stage_failed")
    started = instant(body["producer_time"]["started_at"])
    completed = instant(body["producer_time"]["completed_at"])
    evaluated = instant(body["evaluated_at"])
    need(started <= completed <= evaluated <= datetime.now(timezone.utc), "receipt_time_order")
    for side in ("inputs", "outputs"):
        need(isinstance(body.get(side), list) and len(body[side]) <= 64 and all(isinstance(i, dict) for i in body[side]), "receipt_identities")
    return started, completed


def convert(profile, context, receipt_loader):
    """Pure conversion except explicit pinned receipt_loader(ref) calls.

    No source files are read, and no partial candidate policy is returned.
    """
    result = {"status": "unknown", "policy_written": False, "reasons": [],
              "source_context_complete": False, "offsite_status": "unknown", "consumer_status": "unknown"}
    try:
        validate_profile(profile)
        checked_fields(context, {"schema", "session_date", "generation_id", "receipts", "bindings"}, "context_fields")
        need(context.get("schema") == CONTEXT_SCHEMA, "context_schema")
        session = context["session_date"]
        need(date.fromisoformat(session).isoformat() == session, "context_session")
        generation = context["generation_id"]
        need(safe_id(generation) and generation != "unknown", "context_generation_unknown")
        refs, bindings = context["receipts"], context["bindings"]
        need(isinstance(refs, list) and 0 < len(refs) <= MAX_RECEIPTS, "receipt_budget")
        need(isinstance(bindings, list) and 0 < len(bindings) <= MAX_BINDINGS, "binding_budget")
        known_refs, loaded = {}, {}
        for ref in refs:
            checked_fields(ref, {"receipt_id", "chain_id", "sha256"}, "receipt_ref_fields")
            need(safe_id(ref["receipt_id"]) and ref["chain_id"] in CHAINS and sha(ref["sha256"]), "receipt_ref_identity")
            need(ref["receipt_id"] not in known_refs, "duplicate_receipt_ref")
            known_refs[ref["receipt_id"]] = ref
        selected = {}
        for b in bindings:
            checked_fields(b, {"artifact_id", "table", "receipt_id", "collection", "object_id"}, "binding_fields")
            key = (b["artifact_id"], b.get("table"))
            need(key not in selected and b["receipt_id"] in known_refs, "ambiguous_binding")
            need(b["collection"] in {"inputs", "outputs"} and safe_id(b["object_id"]), "binding_identity")
            selected[key] = b
        required = {(a["id"], table) for a in profile["artifacts"] for table in (a["tables"] if a["kind"] == "db" else [None])}
        need(set(selected) == required, "required_binding_inventory_mismatch")
        artifacts, proofs = [], []
        for spec in profile["artifacts"]:
            artifact = {k: spec[k] for k in ("id", "kind", "path")}
            tables, transaction = {}, None
            for table in (spec["tables"] if spec["kind"] == "db" else [None]):
                binding = selected[(spec["id"], table)]
                ref = known_refs[binding["receipt_id"]]
                if ref["receipt_id"] not in loaded:
                    body = receipt_loader(ref)
                    times = validate_receipt(body, ref, session)
                    loaded[ref["receipt_id"]] = (body, times)
                body, (started, completed) = loaded[ref["receipt_id"]]
                matches = [i for i in body[binding["collection"]] if i.get("object_id") == binding["object_id"]]
                need(len(matches) == 1, "source_identity_missing_or_ambiguous")
                fact = matches[0]
                label = spec["id"] + (":" + table if table else "")
                try:
                    need(fact.get("quality") == "strong", "source_identity_not_strong")
                    need(fact.get("identity_kind") == "bytes", "logical_digest_is_not_compatible_bytes")
                    need(sha(fact.get("sha256")) and type(fact.get("size")) is int and fact["size"] >= 0, "source_byte_identity_missing")
                    need(fact.get("session_date") == session, "source_session_mismatch")
                    need(source_name(fact.get("resolved_path")) == source_name(spec["path"]), "source_path_mismatch")
                    need(fact.get("generation_id") == generation, "source_generation_missing_or_mismatch")
                    need("observed_at" in fact, "source_observation_time_missing")
                    need("as_of" in fact, "source_asof_missing")
                    observed = instant(fact["observed_at"])
                    as_of = instant(fact["as_of"])
                    need(started <= observed <= completed and as_of <= observed, "source_time_order_or_asof_unknown")
                    if table is None:
                        need(fact.get("digest_domain", "source_bytes") == "source_bytes" and fact.get("digest_algorithm", "sha256") == "sha256", "sidecar_digest_domain")
                        artifact.update(sha256=fact["sha256"])
                    else:
                        need(fact.get("digest_domain") == "sqlite_table_rows" and fact.get("digest_algorithm") == ROWS_ALGORITHM,
                             "db_rows_algorithm_not_compatible")
                        source = fact.get("source_context")
                        need(isinstance(source, dict) and source.get("method") == "sqlite_read_transaction" and source.get("scope") == "full_table"
                             and source.get("includes_committed_wal") is True, "db_transaction_scope_unknown")
                        need(safe_id(source.get("transaction_id")) and source["transaction_id"] != "unknown", "db_transaction_identity_unknown")
                        tx = (source["transaction_id"], fact["as_of"], ref["receipt_id"])
                        need(transaction is None or transaction == tx, "db_tables_not_same_transaction")
                        transaction = tx
                        req = spec["tables"][table]
                        need(source.get("table") == table and source.get("columns") == req["columns"] and source.get("order_by") == req["columns"],
                             "db_full_columns_or_order_mismatch")
                        need(type(source.get("row_count")) is int and source["row_count"] >= req["min_rows"], "db_required_rows_missing")
                        target = {"min_rows": req["min_rows"], "rows_sha256": fact["sha256"]}
                        if "date_column" in req:
                            need(source.get("date_column") == req["date_column"] and isinstance(source.get("max_date"), str), "db_date_metadata_missing")
                            max_date = source["max_date"]
                            need(datetime.strptime(max_date, "%Y%m%d").strftime("%Y%m%d") == max_date, "db_max_date_invalid")
                            need(not req.get("require_session_max") or max_date == session.replace("-", ""), "db_cutoff_stale")
                            target.update(date_column=req["date_column"], max_date=max_date)
                        if "schema_sha256" in source:
                            need(sha(source["schema_sha256"]), "db_schema_digest_invalid")
                            target["schema_sha256"] = source["schema_sha256"]
                        tables[table] = target
                    artifact.update(generation_id=generation, as_of=fact["as_of"])
                    proofs.append({"artifact_id": spec["id"], "table": table, "receipt_id": ref["receipt_id"],
                                   "receipt_sha256": ref["sha256"], "collection": binding["collection"],
                                   "object_id": fact["object_id"], "identity_sha256": fact["sha256"],
                                   "digest_domain": fact.get("digest_domain", "source_bytes"), "observed_at": fact["observed_at"]})
                except (KeyError, TypeError, ValueError) as e:
                    reason = str(e) if isinstance(e, PolicyUnknown) else "source_metadata_missing_or_invalid"
                    result["reasons"].append({"artifact_id": label, "reason": reason})
            if spec["kind"] == "db":
                artifact["tables"] = tables
            artifacts.append(artifact)
        if result["reasons"]:
            return result
        policy = {"schema": SCHEMA, "session_date": session, "generation_id": generation,
                  "artifacts": artifacts, "business": dict(profile["business"], cutoff_date=session.replace("-", "")),
                  "policy_source": {"profile_id": profile["profile_id"], "profile_logical_sha256": hashlib.sha256(canonical(profile)).hexdigest(),
                                    "context_logical_sha256": hashlib.sha256(canonical(context)).hexdigest(), "proofs": proofs}}
        validate_policy(policy)
        result.update(status="ready", policy=policy, source_context_complete=True)
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as e:
        result["reasons"].append({"reason": str(e) if isinstance(e, PolicyUnknown) else "profile_context_or_receipt_invalid"})
    return result


class Reader:
    """Only control/receipt files; openat pins directories, FIFO/links rejected."""
    def __init__(self):
        self.deadline, self.bytes = time.monotonic() + 2.0, 0

    def read(self, path, *, receipt=False):
        need(time.monotonic() < self.deadline, "reader_deadline")
        path = Path(path).absolute()
        need(".." not in path.parts and not path.name.startswith(".env"), "control_path_forbidden")
        # /tmp is the OS alias on macOS; normalize this trusted prefix only.
        if path.is_relative_to("/tmp"):
            path = Path("/tmp").resolve() / path.relative_to("/tmp")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            child = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(child, "rb") as f:
                before = os.fstat(f.fileno())
                need(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE, "control_not_regular_or_oversized")
                if receipt:
                    need(stat.S_IMODE(before.st_mode) == 0o600, "receipt_permissions")
                raw = f.read(MAX_FILE + 1)
                after = os.fstat(f.fileno())
                named = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            need(signature(before) == signature(after) == signature(named), "control_changed_during_read")
            self.bytes += len(raw)
            need(len(raw) <= MAX_FILE and self.bytes <= (MAX_RECEIPTS + 2) * MAX_FILE and time.monotonic() < self.deadline, "reader_budget")
            return raw
        finally:
            os.close(fd)

    def load_receipt(self, root, session, ref):
        path = Path(root) / "data/ops_delivery/receipts" / session / ref["chain_id"] / (ref["receipt_id"] + ".json")
        raw = self.read(path, receipt=True)
        need(hashlib.sha256(raw).hexdigest() == ref["sha256"], "receipt_hash_mismatch")
        return strict_json(raw)


def publish(path, policy):
    path = Path(path)
    payload = canonical(policy) + b"\n"
    fd, name = tempfile.mkstemp(prefix=".policy-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.link(name, path)  # Exclusive immutable output; never replace old policy.
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        os.unlink(name)
    return hashlib.sha256(payload).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ("data-root", "profile", "context", "output"):
        ap.add_argument("--" + name, required=True, type=Path)
    args = ap.parse_args(argv)
    if os.environ.get("OPS_DELIVERY_EVIDENCE_ENABLED") != "1":
        print('{"status":"disabled","policy_written":false}')
        return 0
    result = {"status": "unknown", "policy_written": False, "reasons": []}
    try:
        need(not os.path.lexists(args.output), "output_already_exists")
        reader = Reader()
        profile_raw, context_raw = reader.read(args.profile), reader.read(args.context)
        profile, context = strict_json(profile_raw), strict_json(context_raw)
        result = convert(profile, context, lambda ref: reader.load_receipt(args.data_root, context["session_date"], ref))
        if result["status"] == "ready":
            policy = result.pop("policy")
            policy["policy_source"].update(profile_file_sha256=hashlib.sha256(profile_raw).hexdigest(),
                                           context_file_sha256=hashlib.sha256(context_raw).hexdigest())
            result.update(policy_sha256=publish(args.output, policy), policy_written=True)
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as e:
        result = {"status": "unknown", "policy_written": False, "reasons": [
            {"reason": str(e) if isinstance(e, PolicyUnknown) else "control_read_or_publication_failed", "error_type": type(e).__name__}]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
