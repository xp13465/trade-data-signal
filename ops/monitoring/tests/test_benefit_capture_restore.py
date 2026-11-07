"""C4 synthetic only: temporary WAL/JSON, no business imports or external IO."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import select
import subprocess
import sys
import tempfile
import time
import types

import pytest

MONITORING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MONITORING))
import benefit_capture as cap
import benefit_restore as restore


TEST_LIMITS = cap.Limits(max_bytes=32*1024*1024, max_sets=8, file_bytes=8*1024*1024, json_bytes=1024*1024, min_free_bytes=1, seconds=10)


def restore_call(*args, **kwargs):
    return restore.isolated_restore(*args, limits=kwargs.pop("limits", TEST_LIMITS), **kwargs)


@pytest.fixture
def sample():
    with tempfile.TemporaryDirectory(prefix="c4-synthetic-", dir=Path("/tmp").resolve()) as tmp:
        root = Path(tmp)
        source = root / "source"
        source.mkdir()
        con = sqlite3.connect(source / "sentiment.db")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE signal_daily(date TEXT,index_id TEXT,signal TEXT, PRIMARY KEY(date,index_id,signal))")
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("INSERT INTO signal_daily VALUES('20261106','test_index','buy')")
        con.commit()  # Keep connection open: committed row is ONLY in WAL.
        freeze = {"20261106|test_index|buy": {"code": "OLD_ETF", "frozen_at": "2026-11-06 16:00"}}
        # Historic frozen code deliberately differs from today's best.
        mapping = {"test_index": [{"code": "NEW_ETF", "track_score": 99}]}
        (source / "freeze.json").write_text(json.dumps(freeze))
        (source / "map.json").write_text(json.dumps(mapping))
        (source / "universe.yaml").write_text("synthetic_universe: [test_index]\n")
        as_of = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        policy = {"schema": cap.SCHEMA, "session_date": "2026-11-06", "generation_id": "test-generation-1",
                  "artifacts": [
                      {"id": "sentiment", "kind": "db", "path": str(source / "sentiment.db"),
                       "tables": {"signal_daily": {"min_rows": 1, "date_column": "date", "max_date": "20261106",
                                                    "rows_sha256": hashlib.sha256(b'["20261106","test_index","buy"]\n').hexdigest()}}},
                      {"id": "freeze", "kind": "freeze", "path": str(source / "freeze.json")},
                      {"id": "mapping", "kind": "map", "path": str(source / "map.json")},
                      {"id": "universe", "kind": "config", "path": str(source / "universe.yaml")},
                  ],
                  "business": {"db_id": "sentiment", "table": "signal_daily", "indexes": ["test_index"],
                               "signals": ["buy", "buy_aux"], "start_date": "20261101", "cutoff_date": "20261106",
                               "expected_selections": {"20261106|test_index|buy": "OLD_ETF"}}}
        for a in policy["artifacts"]:
            a.update(generation_id=policy["generation_id"], as_of=as_of)
            if a["kind"] != "db":
                a["sha256"] = cap.sha_file(a["path"])
        path = root / "policy.json"
        path.write_text(json.dumps(policy))
        yield types.SimpleNamespace(root=root, source=source, con=con, policy=policy, policy_path=path,
                                    export=root / "exports", freeze=freeze, mapping=mapping)
        con.close()


def policy_save(sample):
    sample.policy_path.write_text(json.dumps(sample.policy))


def make_capture(sample):
    policy_save(sample)
    return cap.capture(sample.policy_path, sample.export, limits=TEST_LIMITS)


def test_wal_capture_and_isolated_native_consumer(sample):
    # Prove raw cp is an invalid baseline: committed signal isn't in main file.
    raw = sample.root / "raw.db"
    shutil.copyfile(sample.source / "sentiment.db", raw)
    with closing(sqlite3.connect(raw)) as con:
        assert con.execute("SELECT count(*) FROM signal_daily").fetchone()[0] == 0
    path, manifest = make_capture(sample)
    with closing(sqlite3.connect(path.parent / "sentiment.db")) as con:
        assert con.execute("SELECT * FROM signal_daily").fetchall() == [("20261106", "test_index", "buy")]
    assert manifest["assessment"]["status"] == "validated"
    assert manifest["remote_coverage"]["status"] == "unknown"
    assert manifest["restore_status"] == "not_verified"
    assert not any(p.name.startswith(".pending") for p in sample.export.iterdir())
    before = {p.name: cap.sha_file(p) for p in sample.source.iterdir()}
    result, _ = restore_call(path, sample.root / "isolated", manifest_sha256=cap.sha_file(path))
    assert result["restore_status"] == "validated"
    assert result["status"] == "unknown"  # Not chain success, no remote or production consumer proof.
    assert result["consumer_witness"]["status"] == "unknown"
    assert result["local_assessment"]["business"]["required_keys"] == 1
    assert (sample.root / "isolated/capture-set/sentiment.db").exists()
    assert {p.name: cap.sha_file(p) for p in sample.source.iterdir()} == before


def test_without_restore_target_never_claim_restored(sample):
    path, _ = make_capture(sample)
    result, _ = restore_call(path, manifest_sha256=cap.sha_file(path))
    assert result["restore_status"] == "not_verified"
    assert result["reason"] == "restore_not_run"


def test_unpinned_bytes_and_manifest_remain_unknown(sample):
    for a in sample.policy["artifacts"]:
        a.pop("sha256", None)
        for req in a.get("tables", {}).values():
            req.pop("rows_sha256", None)
    path, manifest = make_capture(sample)
    assert manifest["assessment"]["status"] == "unknown"
    result, _ = restore_call(path, sample.root / "unknown")
    assert result["restore_status"] == "unknown"
    assert "manifest_identity_not_pinned_out_of_band" in result["local_assessment"]["limitations"]


@pytest.mark.parametrize("name,change", [
    ("freeze.json", "missing"), ("mapping.json", "missing"), ("universe.config", "missing"),
    ("sentiment.db", "truncate"), ("freeze.json", "tamper"), ("mapping.json", "tamper"),
])
def test_partial_tampered_truncated_never_green(sample, name, change):
    path, _ = make_capture(sample)
    p = path.parent / name
    if change == "missing":
        p.unlink()
    elif change == "truncate":
        p.write_bytes(p.read_bytes()[:64])
    else:
        p.write_text('{"wrong":"generation"}')
    with pytest.raises(cap.CaptureError):
        restore_call(path, sample.root / "reject", manifest_sha256=cap.sha_file(path))
    assert not (sample.root / "reject").exists()


@pytest.mark.parametrize("mutation", ["generation", "missing_freeze_key", "wrong_selection", "wrong_map",
                                       "empty_db", "stale_db", "pin_mismatch", "future_asof", "missing_config"])
def test_business_capture_rejections_leave_no_partial_set(sample, mutation):
    if mutation == "generation":
        sample.policy["artifacts"][1]["generation_id"] = "another-generation"
    elif mutation in {"missing_freeze_key", "wrong_selection"}:
        value = {} if mutation == "missing_freeze_key" else {"20261106|test_index|buy": {"code": "BAD", "frozen_at": "2026-11-06 16:00"}}
        (sample.source / "freeze.json").write_text(json.dumps(value))
        sample.policy["artifacts"][1]["sha256"] = cap.sha_file(sample.source / "freeze.json")
    elif mutation == "wrong_map":
        (sample.source / "map.json").write_text('{"other_index":[]}')
        sample.policy["artifacts"][2]["sha256"] = cap.sha_file(sample.source / "map.json")
    elif mutation == "empty_db":
        sample.con.execute("DELETE FROM signal_daily")
        sample.con.commit()
    elif mutation == "stale_db":
        sample.con.execute("UPDATE signal_daily SET date='20261105'")
        sample.con.commit()
    elif mutation == "pin_mismatch":
        sample.policy["artifacts"][2]["sha256"] = "0" * 64
    elif mutation == "future_asof":
        sample.policy["artifacts"][1]["as_of"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif mutation == "missing_config":
        (sample.source / "universe.yaml").unlink()
    with pytest.raises((cap.CaptureError, FileNotFoundError)):
        make_capture(sample)
    assert not sample.export.exists() or list(sample.export.iterdir()) == [sample.export / ".capture.lock"]


def test_json_changes_during_db_snapshot_are_detected(sample, monkeypatch):
    original = cap.snapshot_db
    def changing(src, dst):
        original(src, dst)
        p = sample.source / "freeze.json"
        old = p.stat()
        p.write_text(json.dumps({}))
        os.utime(p, ns=(old.st_atime_ns, old.st_mtime_ns))  # Spoofed mtime doesn't hide bytes/ctime change.
    monkeypatch.setattr(cap, "snapshot_db", changing)
    with pytest.raises(cap.CaptureError, match="source_changed_across_capture"):
        make_capture(sample)
    assert list(sample.export.iterdir()) == [sample.export / ".capture.lock"]


def test_db_changes_after_snapshot_cannot_change_captured_transaction(sample, monkeypatch):
    original = cap.snapshot_db
    def changing(src, dst):
        original(src, dst)
        sample.con.execute("INSERT INTO signal_daily VALUES('20261106','another','buy')")
        sample.con.commit()
    monkeypatch.setattr(cap, "snapshot_db", changing)
    path, manifest = make_capture(sample)
    assert manifest["artifacts"]["sentiment"]["tables"]["signal_daily"]["rows"] == 1
    assert restore_call(path, sample.root / "after", manifest_sha256=cap.sha_file(path))[0]["restore_status"] == "validated"


def test_capture_set_identity_and_external_manifest_pin(sample):
    path, manifest = make_capture(sample)
    trusted = cap.sha_file(path)
    manifest["artifacts"]["freeze"]["capture_set_id"] = "different-set"
    cap.atomic_json(path, manifest)
    with pytest.raises(cap.CaptureError, match="manifest_hash_mismatch"):
        restore_call(path, manifest_sha256=trusted)
    with pytest.raises(cap.CaptureError, match="capture_file_identity_mismatch"):
        restore_call(path, manifest_sha256=cap.sha_file(path))


def test_no_overwrite_symlink_or_production_target(sample):
    path, _ = make_capture(sample)
    target = sample.root / "existing"
    target.mkdir()
    (target / "keep").write_text("never overwrite")
    for dest in (target, sample.source / "new", Path("/opt/forbidden-c4"), path.parent / "new"):
        with pytest.raises(cap.CaptureError):
            restore_call(path, dest, manifest_sha256=cap.sha_file(path))
    assert (target / "keep").read_text() == "never overwrite"
    linked = sample.root / "linked"
    linked.symlink_to(sample.source)
    with pytest.raises(cap.CaptureError):
        restore_call(path, linked, manifest_sha256=cap.sha_file(path))


def test_db_only_and_stray_wal_are_not_complete(sample):
    path, _ = make_capture(sample)
    (path.parent / "sentiment.db-wal").write_bytes(b"not part of snapshot")
    with pytest.raises(cap.CaptureError, match="partial_or_extra_files"):
        restore_call(path)
    (path.parent / "sentiment.db-wal").unlink()
    for p in path.parent.iterdir():
        if p.name not in {"manifest.json", "sentiment.db"}:
            p.unlink()
    with pytest.raises(cap.CaptureError):
        restore_call(path)


def test_restore_copy_interruption_cleans_only_own_target(sample, monkeypatch):
    path, _ = make_capture(sample)
    def fail(*args, **kwargs):
        raise OSError("synthetic disk error")
    monkeypatch.setattr(restore, "copy_bounded", fail)
    with pytest.raises(OSError):
        restore_call(path, sample.root / "partial", manifest_sha256=cap.sha_file(path))
    assert not (sample.root / "partial").exists()
    assert path.is_file() and (sample.source / "freeze.json").is_file()


def test_restore_keeps_exact_manifest_bytes(sample):
    path, manifest = make_capture(sample)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=4))
    trusted = cap.sha_file(path)
    result, _ = restore_call(path, sample.root / "pretty-manifest", manifest_sha256=trusted)
    assert result["restore_status"] == "validated"
    assert cap.sha_file(sample.root / "pretty-manifest/capture-set/manifest.json") == trusted


def test_real_producer_emit_reader_contract_with_temp_fixture(sample, monkeypatch):
    monkeypatch.syspath_prepend(str(MONITORING.parents[1] / "scripts"))
    import delivery_evidence as producer
    monkeypatch.setenv("OPS_DELIVERY_EVIDENCE_ENABLED", "1")
    path, manifest = make_capture(sample)
    result, _ = restore_call(path, sample.root / "real-receipt", manifest_sha256=cap.sha_file(path))
    metadata = cap.emit(sample.root, "restore", result, manifest, cap.sha_file(path))
    assert metadata["status"] == "written"
    receipts = list(producer.iter_receipts(sample.root))
    assert len(receipts) == 1
    assert receipts[0]["batch_id"] == cap.CHAIN + ":2026-11-06"
    assert receipts[0]["attempt_id"] == result["attempt_id"]
    assert receipts[0]["stage_status"] == "unknown"
    assert receipts[0]["inputs"][-1]["sha256"] == cap.sha_file(path)
    assert receipts[0]["events"][0]["isolated_restore_status"] == "validated"
    assert receipts[0]["events"][0]["offsite_status"] == "unknown"


def test_real_capture_restore_receipts_do_not_normalize_into_chain_success(sample, monkeypatch):
    monkeypatch.syspath_prepend(str(MONITORING.parents[1] / "scripts"))
    import delivery_evidence as producer
    import benefits
    monkeypatch.setenv("OPS_DELIVERY_EVIDENCE_ENABLED", "1")
    path, manifest = make_capture(sample)
    backup = {"status": "unknown", "reason": "local_capture_only_remote_coverage_unknown",
              "attempt_id": "synthetic-capture-attempt", "session_date": manifest["session_date"],
              "capture_set_id": manifest["capture_set_id"], "evaluated_at": cap.now(),
              "started_at": manifest["started_at"], "restore_status": "not_verified"}
    assert cap.emit(sample.root, "backup", backup, manifest, cap.sha_file(path))["status"] == "written"
    result, _ = restore_call(path, sample.root / "normalize", manifest_sha256=cap.sha_file(path))
    assert cap.emit(sample.root, "restore", result, manifest, cap.sha_file(path))["status"] == "written"
    receipts = list(producer.iter_receipts(sample.root))
    assert len(receipts) == 2
    batch = cap.CHAIN + ":2026-11-06"
    assert {r["batch_id"] for r in receipts} == {batch}
    assert len({r["attempt_id"] for r in receipts}) == 2
    assert all(r["stage_status"] == "unknown" for r in receipts)
    requirements = {"code_sha": "a" * 40, "config_sha": manifest["policy_sha256"], "edges": [],
                    "required": [{"stage": stage, "object_id": cap.OBJECT, "inputs": ["capture_manifest"],
                                  "outputs": ["capture_manifest"]} for stage in ("backup", "restore")]}
    outcome = benefits.batch_outcome([(str(i), r) for i, r in enumerate(receipts)], requirements,
                                     batch, cap.CHAIN, "2026-11-06", datetime.now(timezone.utc))
    assert outcome[:2] == ("unknown", "receipt_missing_or_ambiguous")


@pytest.mark.parametrize("script,extra", [
    ("benefit_capture.py", ["--policy", "policy.json", "--export-root", "exports"]),
    ("benefit_restore.py", ["--manifest", "manifest.json"]),
])
def test_invalid_config_cli_emits_rejection_without_crashing(sample, script, extra):
    (sample.root / extra[1]).write_text('[]')
    run = subprocess.run([sys.executable, str(MONITORING / script), "--data-root", str(sample.root), *extra],
                         cwd=sample.root, env={"PATH": os.defpath, "OPS_DELIVERY_EVIDENCE_ENABLED": "1"},
                         capture_output=True, text=True)
    assert run.returncode == 1
    result = json.loads(run.stdout)
    assert result["status"] == "failure" and result["restore_status"] == "not_verified"
    assert result["receipt"]["status"] == "written"


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}', b'{"x":'])
def test_invalid_json_rejected(raw):
    with pytest.raises(ValueError):
        cap.strict_json(raw)


def test_receipt_uses_stable_batch_actual_digests_and_unique_attempts(sample, monkeypatch):
    received = []
    def emit_receipt(**kw):
        received.append(kw)
        return {"status": "written"}
    monkeypatch.setitem(sys.modules, "delivery_evidence", types.SimpleNamespace(emit_receipt=emit_receipt))
    path, manifest = make_capture(sample)
    result, _ = restore_call(path, sample.root / "receipt", manifest_sha256=cap.sha_file(path))
    assert cap.emit(sample.root, "restore", result, manifest, cap.sha_file(path))["status"] == "written"
    kw = received[0]
    assert kw["batch_id"] == "backup_isolated_restore:2026-11-06"
    assert kw["stage_status"] == "unknown"
    assert kw["consumer_witness"]["status"] == "unknown"
    assert next(i for i in kw["inputs"] if i["object_id"] == "capture_manifest")["sha256"] == cap.sha_file(path)
    again, _ = restore_call(path)
    assert again["attempt_id"] != result["attempt_id"]


def test_disabled_cli_does_not_read_sources_or_create_directories(sample):
    for script, extra in (("benefit_capture.py", ["--policy", "/forbidden/no-read", "--export-root", str(sample.root / "no-export")]),
                          ("benefit_restore.py", ["--manifest", "/forbidden/no-read", "--target", str(sample.root / "no-restore")])):
        run = subprocess.run([sys.executable, str(MONITORING / script), "--data-root", str(sample.root / "no-data"), *extra],
                             env={"PATH": os.defpath, "OPS_DELIVERY_EVIDENCE_ENABLED": "0"}, capture_output=True, text=True)
        assert run.returncode == 0 and json.loads(run.stdout)["status"] == "disabled"
    assert not any((sample.root / x).exists() for x in ("no-export", "no-restore", "no-data"))


@pytest.mark.parametrize("script,extra,reason", [
    ("benefit_capture.py", ["--export-root", "no-export"], "capture_policy_unconfigured"),
    ("benefit_restore.py", ["--target", "no-restore"], "capture_manifest_unconfigured"),
])
def test_missing_configuration_is_visible_unknown_receipt(sample, script, extra, reason):
    run = subprocess.run([sys.executable, str(MONITORING / script), "--data-root", str(sample.root), *extra],
                         cwd=sample.root, env={"PATH": os.defpath, "OPS_DELIVERY_EVIDENCE_ENABLED": "1"},
                         capture_output=True, text=True)
    assert run.returncode == 0  # Existing hooks do not change established backup/verify RC.
    result = json.loads(run.stdout)
    assert result["status"] == "unknown" and result["reason"] == reason
    assert result["restore_status"] == "not_verified" and result["remote_coverage"] == "unknown"
    assert result["receipt"]["status"] == "written"
    assert not (sample.root / extra[-1]).exists()


@pytest.mark.parametrize("script", ["benefit_capture.py", "benefit_restore.py"])
def test_missing_required_cli_arguments_are_visible_error(script):
    run = subprocess.run([sys.executable, str(MONITORING / script)],
                         env={"PATH": os.defpath}, capture_output=True, text=True)
    assert run.returncode == 2 and "required" in run.stderr and "--data-root" in run.stderr


def test_existing_verify_hook_with_real_local_cli_and_its_actual_target(sample):
    path, _ = make_capture(sample)
    text = (MONITORING.parents[1] / "scripts/verify_backup.sh").read_text()
    start = text.index('if [ "${OPS_DELIVERY_EVIDENCE_ENABLED:-0}" = "1" ]; then')
    hook = text[start:text.index("\nfi", start) + 3]
    tmp = sample.root / "verify-backup-fixture"
    tmp.mkdir()
    log = sample.root / "real-hook.log"
    run = subprocess.run(["bash", "-c", 'RC=7\n' + hook + '\nexit "$RC"'], capture_output=True, text=True,
                         env={"PATH": os.defpath, "PY": sys.executable, "GIT_REPO": str(MONITORING.parents[1]),
                              "REPO": str(sample.root), "TMPDIR": str(tmp), "LOG": str(log),
                              "OPS_DELIVERY_EVIDENCE_ENABLED": "1", "OPS_BENEFIT_RESTORE_MANIFEST": str(path),
                              "OPS_BENEFIT_RESTORE_MANIFEST_SHA256": cap.sha_file(path), "OPS_BENEFIT_RESTORE_MAX_BYTES": str(TEST_LIMITS.max_bytes), "OPS_BENEFIT_MIN_FREE_BYTES": "1"})
    assert run.returncode == 7 and not run.stdout and not run.stderr
    result = json.loads(log.read_text())
    assert result["restore_status"] == "validated" and result["status"] == "unknown"
    assert result["remote_coverage"] == "unknown" and result["consumer_witness"]["status"] == "unknown"
    assert (tmp / "benefit-restore/capture-set/sentiment.db").exists()
    assert result["receipt"]["status"] == "written"


@pytest.mark.parametrize("script,entry", [("backup_db.sh", "benefit_capture.py"), ("verify_backup.sh", "benefit_restore.py")])
@pytest.mark.parametrize("enabled", ["0", "1"])
def test_only_safe_hook_snippet_preserves_original_exit_contract(sample, script, entry, enabled):
    # Execute just the hook, never a production backup/verify main entry point.
    text = (MONITORING.parents[1] / "scripts" / script).read_text()
    start = text.index('if [ "${OPS_DELIVERY_EVIDENCE_ENABLED:-0}" = "1" ]; then')
    hook = text[start:text.index("\nfi", start) + 3]
    stub = sample.root / "stub-python"
    marker = sample.root / "hook.calls"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$MARKER"\nexit 9\n')
    stub.chmod(0o700)
    run = subprocess.run(["bash", "-c", 'RC=7\n' + hook + '\nexit "$RC"'], capture_output=True, text=True,
                         env={"PATH": os.defpath, "PY": str(stub), "GIT_REPO": str(sample.root / "fake-code"),
                              "REPO": str(sample.root / "fake-data"), "BACKUP_DIR": str(sample.root / "fake-backups"),
                              "TMPDIR": str(sample.root), "LOG": str(sample.root / "hook.log"), "MARKER": str(marker),
                              "OPS_DELIVERY_EVIDENCE_ENABLED": enabled})
    assert run.returncode == 7
    assert marker.exists() == (enabled == "1")
    if marker.exists():
        assert entry in marker.read_text()
        assert "退出码不变" in run.stdout


def test_accumulated_expired_capture_sets_are_preserved_and_budget_refuses_before_copy(sample, monkeypatch):
    for _ in range(3):
        make_capture(sample)
    for p in sample.export.rglob("*"):
        os.utime(p, (1, 1), follow_symlinks=False)
    before = {str(p.relative_to(sample.export)): cap.sha_file(p) for p in sample.export.rglob("*") if p.is_file()}
    def no_snapshot(*_):
        raise AssertionError("budget must reject before copying DB")
    monkeypatch.setattr(cap, "snapshot_db", no_snapshot)
    with pytest.raises(cap.CaptureError, match="capture_set_count_exceeded"):
        cap.capture(sample.policy_path, sample.export, limits=replace(TEST_LIMITS, max_sets=3))
    used = sum(p.stat().st_size for p in sample.export.rglob("*") if p.is_file())
    with pytest.raises(cap.CaptureError, match="capture_bytes_budget_exceeded"):
        cap.capture(sample.policy_path, sample.export, limits=replace(TEST_LIMITS, max_bytes=used))
    assert before == {str(p.relative_to(sample.export)): cap.sha_file(p) for p in sample.export.rglob("*") if p.is_file()}
    assert not any(p.name.startswith(".pending-") for p in sample.export.iterdir())


@pytest.mark.parametrize("entry", ["foreign-file", ".pending-leftover", "bad-lock"])
def test_unknown_pending_and_nonempty_lock_refuse_without_modifying_any_bytes(sample, entry):
    sample.export.mkdir()
    target = sample.export / (".capture.lock" if entry == "bad-lock" else entry)
    target.write_text("preserve this unknown fact")
    before = target.read_bytes()
    with pytest.raises(cap.CaptureError, match="unaccounted_capture_entry|invalid_capture_lock"):
        make_capture(sample)
    assert target.read_bytes() == before
    assert not any(p.name.startswith(".pending-") for p in sample.export.iterdir() if p != target)


@pytest.mark.parametrize("limits", [None, replace(TEST_LIMITS, max_bytes=0), replace(TEST_LIMITS, max_sets=0)])
def test_missing_or_invalid_resource_budgets_refuse(sample, limits):
    with pytest.raises(cap.CaptureError):
        cap.capture(sample.policy_path, sample.export, limits=limits)
    assert not sample.export.exists()


@pytest.mark.parametrize("idx", [1, 2])
def test_manifest_control_filename_cannot_be_used_as_freeze_or_map(sample, monkeypatch, idx):
    sample.policy["artifacts"][idx]["id"] = "manifest"
    def no_snapshot(*_):
        raise AssertionError("reserved filename must reject before copy")
    monkeypatch.setattr(cap, "snapshot_db", no_snapshot)
    with pytest.raises(cap.CaptureError, match="reserved_capture_filename"):
        make_capture(sample)
    assert not sample.export.exists()


def test_manifest_prefix_is_allowed_for_nonconflicting_config_filename(sample):
    sample.policy["artifacts"][3]["id"] = "manifest"
    path, result = make_capture(sample)
    assert (path.parent / "manifest.config").is_file()
    assert result["assessment"]["status"] == "validated"


@pytest.mark.parametrize("limit", ["file", "json", "space"])
def test_size_and_free_space_limits_refuse_before_snapshot(sample, monkeypatch, limit):
    def no_snapshot(*_):
        raise AssertionError("preflight must reject before DB copy")
    monkeypatch.setattr(cap, "snapshot_db", no_snapshot)
    limits = TEST_LIMITS
    if limit == "file": limits = replace(limits, file_bytes=64)
    elif limit == "json": limits = replace(limits, json_bytes=64)
    else:
        monkeypatch.setattr(cap.shutil, "disk_usage", lambda _: types.SimpleNamespace(free=0))
    with pytest.raises(cap.CaptureError):
        cap.capture(sample.policy_path, sample.export, limits=limits)
    assert not sample.export.exists() or list(sample.export.iterdir()) == [sample.export / ".capture.lock"]


def test_restore_size_and_space_limits_refuse_without_partial_target(sample, monkeypatch):
    path, _ = make_capture(sample)
    for limits in (replace(TEST_LIMITS, max_bytes=1), replace(TEST_LIMITS, file_bytes=64)):
        with pytest.raises(cap.CaptureError):
            restore_call(path, sample.root / "refused", limits=limits)
        assert not (sample.root / "refused").exists()
    monkeypatch.setattr(cap.shutil, "disk_usage", lambda _: types.SimpleNamespace(free=0))
    with pytest.raises(cap.CaptureError):
        restore_call(path, sample.root / "refused")
    assert not (sample.root / "refused").exists()


def test_two_processes_cannot_consume_one_slot_twice(sample):
    script = '''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import benefit_capture as cap
original=cap.snapshot_db
def gated(src,dst):
 print("LOCK_HELD",flush=True)
 sys.stdin.readline()
 return original(src,dst)
cap.snapshot_db=gated
p,m=cap.capture(Path(sys.argv[2]),Path(sys.argv[3]),limits=cap.Limits(33554432,1,min_free_bytes=1))
print("CAPTURED",flush=True)
'''
    proc = subprocess.Popen([sys.executable, "-c", script, str(MONITORING), str(sample.policy_path), str(sample.export)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={"PATH": os.defpath})
    try:
        assert select.select([proc.stdout], [], [], 3)[0]
        assert proc.stdout.readline().strip() == "LOCK_HELD"
        run = subprocess.run([sys.executable, str(MONITORING / "benefit_capture.py"), "--data-root", str(sample.root),
                              "--policy", str(sample.policy_path), "--export-root", str(sample.export),
                              "--max-bytes", "33554432", "--max-sets", "1", "--min-free-bytes", "1"],
                             env={"PATH": os.defpath, "OPS_DELIVERY_EVIDENCE_ENABLED": "1"}, capture_output=True, text=True, timeout=5)
        assert run.returncode == 1 and "capture_already_running" in run.stderr
        output, error = proc.communicate("\n", timeout=5)
        assert proc.returncode == 0 and "CAPTURED" in output and not error
        assert len([p for p in sample.export.iterdir() if p.is_dir()]) == 1
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


@pytest.mark.parametrize("where", ["json", "summary", "copy"])
def test_outer_cli_watchdog_covers_json_sql_summary_and_restore_copy(sample, where):
    instrumented = sample.root / "instrumented/ops/monitoring"
    instrumented.mkdir(parents=True)
    for name in ("benefit_capture.py", "benefit_restore.py"):
        shutil.copyfile(MONITORING / name, instrumented / name)
    entry, fn = ("benefit_restore.py", "copy_bounded") if where == "copy" else ("benefit_capture.py", "stable_bytes" if where == "json" else "db_summary")
    script = instrumented / entry
    text = script.read_text()
    injection = f'\n_slow_original = {fn}\ndef {fn}(*a, **kw):\n    time.sleep(5)\n    return _slow_original(*a, **kw)\n\n'
    script.write_text(text.replace('if __name__ == "__main__":', injection + 'if __name__ == "__main__":'))
    path, _ = make_capture(sample)
    # SQLite's shared-memory lock/read-mark arena can change on a read-only
    # connection or forced process exit. DB/WAL and business sidecars are the
    # source data invariants; shm is not a durable backup artifact.
    source_before = {p.name: cap.sha_file(p) for p in sample.source.iterdir() if not p.name.endswith("-shm")}
    extra = ["--manifest", str(path), "--target", str(sample.root / "timed-target")] if where == "copy" else [
        "--policy", str(sample.policy_path), "--export-root", str(sample.root / "timeout-exports")]
    started = time.monotonic()
    run = subprocess.run([sys.executable, str(script), "--data-root", str(sample.root), *extra,
                          "--max-bytes", "33554432", "--max-sets", "8", "--min-free-bytes", "1", "--timeout-seconds", "0.4"],
                         env={"PATH": os.defpath, "OPS_DELIVERY_EVIDENCE_ENABLED": "1", "PYTHONPATH": str(MONITORING.parents[1] / "scripts")},
                         capture_output=True, text=True, timeout=3)
    assert run.returncode == 1 and time.monotonic() - started < 3
    result = json.loads(run.stdout)
    assert result["status"] == "unknown" and result["reason"] == "optional_worker_total_timeout"
    assert result["restore_status"] == "not_verified" and result["receipt"]["status"] == "written"
    assert source_before == {p.name: cap.sha_file(p) for p in sample.source.iterdir() if not p.name.endswith("-shm")}
    if where == "copy":
        assert not (sample.root / "timed-target/capture-set").exists()
    else:
        export = sample.root / "timeout-exports"
        if export.exists():
            assert not any(p.is_dir() and not p.name.startswith(".pending-") for p in export.iterdir())
