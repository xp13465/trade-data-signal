#!/usr/bin/env python3
"""Validate a capture set; restore only into a new directory below /tmp.

No target means not_verified. A local isolated validation never proves remote
archive availability or execution of the production backtest consumer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid

from benefit_capture import (SCHEMA, CaptureError, assess, date8, emit,
                             filename, fsync_dir, now, sha_file, stable_bytes,
                             strict_json, validate_policy, budget_scope, _BUDGET,
                             copy_bounded, resource_arguments, limits_from_args, bounded_cli)


def validate_set(root, manifest, *, trusted_manifest_sha=None, actual_manifest_sha=None):
    if manifest["schema"] != SCHEMA:
        raise CaptureError("manifest_schema")
    policy = manifest["policy"]
    validate_policy(policy)
    if manifest["session_date"] != policy["session_date"]:
        raise CaptureError("manifest_session_mismatch")
    if trusted_manifest_sha and trusted_manifest_sha != actual_manifest_sha:
        raise CaptureError("manifest_hash_mismatch")
    expected_ids = {a["id"] for a in policy["artifacts"]}
    if set(manifest["artifacts"]) != expected_ids:
        raise CaptureError("partial_or_extra_artifact_inventory")
    expected_files = {"manifest.json"} | {filename(a) for a in policy["artifacts"]}
    if {p.name for p in root.iterdir()} != expected_files:
        raise CaptureError("partial_or_extra_files_including_wal")
    budget = _BUDGET.get()
    if budget and sum(budget.size(root / name) for name in expected_files) > budget.limits.max_bytes:
        raise CaptureError("restore_bytes_budget_exceeded")
    for a in policy["artifacts"]:
        record = manifest["artifacts"][a["id"]]
        if record["capture_set_id"] != manifest["capture_set_id"] or record["file"] != filename(a) or record["kind"] != a["kind"]:
            raise CaptureError("capture_file_identity_mismatch")
        p = root / filename(a)
        if p.is_symlink() or not p.is_file() or p.stat().st_size != record["size"] or sha_file(p) != record["sha256"]:
            raise CaptureError("capture_file_hash_size_or_type_mismatch")
    assessment = assess(root, policy, manifest["artifacts"], manifest["started_at"])
    if not trusted_manifest_sha:
        assessment["status"] = "unknown"
        assessment["limitations"].append("manifest_identity_not_pinned_out_of_band")
    return assessment


def _isolated_restore(manifest_path, target=None, *, manifest_sha256=None, context=None):
    started, timer = now(), time.monotonic()
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink() or manifest_path.name != "manifest.json":
        raise CaptureError("manifest_must_be_regular_manifest_json")
    raw, _ = stable_bytes(manifest_path)
    msha = hashlib.sha256(raw).hexdigest()
    manifest = strict_json(raw)
    if not isinstance(manifest, dict):
        raise CaptureError("manifest_type")
    if context is not None:
        # Preserve an observed logical slot on a rejected attempt, without
        # emitting unvalidated artifact identities as actual restored outputs.
        session = manifest.get("session_date", "unknown")
        if isinstance(session, str) and len(session) == 10:
            date8(session.replace("-", ""))
            context["session_date"] = session
    root = manifest_path.resolve().parent
    before = validate_set(root, manifest, trusted_manifest_sha=manifest_sha256, actual_manifest_sha=msha)
    result = {"status": "unknown", "reason": "restore_not_run", "restore_status": "not_verified",
              "remote_coverage": "unknown", "attempt_id": str(uuid.uuid4()),
              "session_date": manifest["session_date"], "capture_set_id": manifest["capture_set_id"],
              "started_at": started,
              "manifest_sha256": msha, "evaluated_at": now(), "local_assessment": before,
              "consumer_witness": {"status": "unknown", "reason": "production_consumer_not_run"}}
    if target is None:
        return result, manifest
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise CaptureError("target_must_not_exist")
    target = target.resolve()
    tmp_root = Path("/tmp").resolve()
    if target == tmp_root or not target.is_relative_to(tmp_root) or not target.parent.is_dir():
        raise CaptureError("target_must_be_new_directory_below_tmp_with_existing_parent")
    sources = [Path(a["source"]["path"]).resolve() for a in manifest["artifacts"].values()]
    if target == root or target.is_relative_to(root) or root.is_relative_to(target) or any(p == target or p.is_relative_to(target) or target.is_relative_to(p.parent) for p in sources):
        raise CaptureError("target_overlaps_capture_or_sources")
    # Reserve the destination exclusively; an existing or concurrently created
    # target is never replaced, even if empty. No files are written to sources.
    budget = _BUDGET.get()
    needed = sum(budget.size(p) for p in root.iterdir())
    budget.space(target.parent, needed)
    target.mkdir(mode=0o700)
    pending = Path(tempfile.mkdtemp(prefix=".restore-", dir=target))
    budget.pending = pending
    try:
        for a in manifest["policy"]["artifacts"]:
            copy_bounded(root / filename(a), pending / filename(a))
            os.chmod(pending / filename(a), 0o600)
        copy_bounded(manifest_path, pending / "manifest.json")
        os.chmod(pending / "manifest.json", 0o600)
        copied_sha = sha_file(pending / "manifest.json")
        if copied_sha != msha:
            raise CaptureError("manifest_changed_during_copy")
        assessment = validate_set(pending, manifest, trusted_manifest_sha=manifest_sha256, actual_manifest_sha=copied_sha)
        # Re-read source manifest/files to reject concurrent replacements during
        # restore. No receipt is emitted before this and destination validation.
        if sha_file(manifest_path) != msha:
            raise CaptureError("manifest_changed_during_restore")
        validate_set(root, manifest, trusted_manifest_sha=manifest_sha256, actual_manifest_sha=msha)
        final = target / "capture-set"
        os.rename(pending, final)
        fsync_dir(target)
        result.update({"reason": "isolated_validator_only_remote_and_production_consumer_unknown",
                       "restore_status": "validated" if assessment["status"] == "validated" else "unknown",
                       "local_assessment": assessment, "duration_ms": round((time.monotonic() - timer) * 1000),
                       "started_at": started, "evaluated_at": now(),
                       "outputs": [{"object_id": "isolated_selection", "sha256": assessment["business"]["selection_sha256"],
                                    "identity_kind": "loaded_object", "quality": "strong", "observed_at": now(),
                                    "session_date": manifest["session_date"], "capture_set_id": manifest["capture_set_id"]}]})
        result["evaluated_at"] = now()
        return result, manifest
    except BaseException:
        shutil.rmtree(target)
        raise


def isolated_restore(manifest_path, target=None, *, manifest_sha256=None, context=None, limits=None):
    with budget_scope(limits):
        return _isolated_restore(manifest_path, target, manifest_sha256=manifest_sha256, context=context)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=os.environ.get("OPS_BENEFIT_RESTORE_MANIFEST"))
    ap.add_argument("--manifest-sha256", default=os.environ.get("OPS_BENEFIT_RESTORE_MANIFEST_SHA256"))
    ap.add_argument("--target", type=Path)
    ap.add_argument("--data-root", type=Path, required=True)
    resource_arguments(ap, "restore")
    args = ap.parse_args(argv)
    if os.environ.get("OPS_DELIVERY_EVIDENCE_ENABLED") != "1":
        print('{"status":"disabled"}')
        return 0
    if not args._worker:
        return bounded_cli([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv), "--_worker"],
                           args.timeout_seconds, args.data_root, "restore")
    result = {"status": "unknown", "reason": "capture_manifest_unconfigured", "restore_status": "not_verified",
              "remote_coverage": "unknown", "attempt_id": str(uuid.uuid4()), "evaluated_at": now()}
    manifest = None
    if args.manifest:
        try:
            result, manifest = isolated_restore(args.manifest, args.target, manifest_sha256=args.manifest_sha256,
                                                context=result, limits=limits_from_args(args, "restore"))
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
            result.update(status="failure", reason="restore_rejected:" + type(e).__name__)
            print("benefit restore rejected: " + str(e), file=sys.stderr)
    result["receipt"] = emit(args.data_root, "restore", result, manifest, result.get("manifest_sha256"))
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "failure" or result["receipt"]["status"] == "metadata_failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
