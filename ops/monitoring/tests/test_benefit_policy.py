"""Actual temporary source/WAL read facts -> real immutable receipts -> policy.

No pins come from a capture-set copy, current files after conversion, live user
data or network. The typed DB stream is a compatibility fixture; today's native
producer emits scoped logical query hashes instead, tested as unknown below.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import types

import pytest

MONITORING = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MONITORING))
sys.path.insert(0, str(MONITORING.parents[1] / "scripts"))
import benefit_policy as tool
import benefit_capture as cap
import benefit_restore as restore
import delivery_evidence as producer


@pytest.fixture
def facts():
    with tempfile.TemporaryDirectory(prefix="c4-policy-source-", dir=Path("/tmp").resolve()) as tmp:
        root = Path(tmp)
        source = root / "source"
        source.mkdir()
        con = sqlite3.connect(source / "sentiment.db")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE signal_daily(date TEXT,index_id TEXT,signal TEXT)")
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("INSERT INTO signal_daily VALUES('20261106','test_index','buy')")
        con.commit()  # Real committed data remains in WAL, writer held open.
        (source / "freeze.json").write_text(json.dumps({"20261106|test_index|buy": {"code": "OLD_ETF", "frozen_at": "2026-11-06 16:00"}}))
        (source / "map.json").write_text(json.dumps({"test_index": [{"code": "NEW_ETF", "track_score": 100}]}))
        (source / "universe.yaml").write_text("indexes: [test_index]\n")
        profile = {"schema": tool.PROFILE_SCHEMA, "profile_id": "synthetic-source-profile-v1", "artifacts": [
            {"id": "sentiment", "kind": "db", "path": str(source / "sentiment.db"), "tables": {
                "signal_daily": {"min_rows": 1, "columns": ["date", "index_id", "signal"], "date_column": "date", "require_session_max": True}}},
            {"id": "freeze", "kind": "freeze", "path": str(source / "freeze.json")},
            {"id": "mapping", "kind": "map", "path": str(source / "map.json")},
            {"id": "universe", "kind": "config", "path": str(source / "universe.yaml")},
        ], "business": {"db_id": "sentiment", "table": "signal_daily", "indexes": ["test_index"],
                        "signals": ["buy", "buy_aux"], "start_date": "20261101",
                        "expected_selections": {"20261106|test_index|buy": "OLD_ETF"}}}
        session, generation = "2026-11-06", "actual-fixture-read-generation-1"
        started = cap.now()
        observed = []
        # This is the source transaction, not a capture copy or a raw main-db hash.
        with closing(sqlite3.connect((source / "sentiment.db").as_uri() + "?mode=ro", uri=True)) as reader:
            reader.execute("BEGIN")
            columns = reader.execute('PRAGMA table_info("signal_daily")').fetchall()
            rows = reader.execute('SELECT * FROM "signal_daily" ORDER BY "date","index_id","signal"').fetchall()
            raw_rows = b"".join(json.dumps(list(r), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n" for r in rows)
            as_of = cap.now()
            db_identity = producer.identity_for_bytes("sentiment_signal_table", raw_rows,
                session_date=session, resolved_path=str(source / "sentiment.db"), generation_id=generation, as_of=as_of,
                digest_domain="sqlite_table_rows", digest_algorithm=tool.ROWS_ALGORITHM,
                source_context={"method": "sqlite_read_transaction", "scope": "full_table", "transaction_id": "fixture-txn-1",
                                "table": "signal_daily", "columns": [c[1] for c in columns], "order_by": [c[1] for c in columns],
                                "row_count": len(rows), "includes_committed_wal": True, "date_column": "date",
                                "max_date": max(r[0] for r in rows), "schema_sha256": cap.digest(columns)})
            reader.rollback()
        observed.append(db_identity)
        bindings = [{"artifact_id": "sentiment", "table": "signal_daily", "receipt_id": "fixture-source-reads",
                     "collection": "inputs", "object_id": "sentiment_signal_table"}]
        for a in profile["artifacts"][1:]:
            # Read true source bytes now. Converter will never open these paths.
            payload = Path(a["path"]).read_bytes()
            fact = producer.identity_for_bytes(a["id"], payload, session_date=session,
                resolved_path=a["path"], generation_id=generation, as_of=cap.now())
            observed.append(fact)
            bindings.append({"artifact_id": a["id"], "receipt_id": "fixture-source-reads", "collection": "inputs", "object_id": a["id"]})
        completed = cap.now()
        metadata = producer.emit_receipt(data_root=root, receipt_id="fixture-source-reads", stage="backtest",
            chain_id="backtest_publish_consume", object_id="fixture-source-context", session_date=session,
            batch_id="backtest_publish_consume:" + session, attempt_id="actual-source-fixture-attempt", inputs=observed,
            producer_time={"started_at": started, "completed_at": completed}, evidence_quality="stage_only", enabled=True)
        assert metadata["status"] == "written"
        context = {"schema": tool.CONTEXT_SCHEMA, "session_date": session, "generation_id": generation,
                   "receipts": [{"receipt_id": metadata["receipt_id"], "chain_id": "backtest_publish_consume", "sha256": metadata["receipt_sha256"]}],
                   "bindings": bindings}
        receipt_path = root / "data/ops_delivery/receipts" / session / "backtest_publish_consume/fixture-source-reads.json"
        body = producer.read_receipt(receipt_path)
        profile_path, context_path = root / "profile.json", root / "context.json"
        profile_path.write_text(json.dumps(profile))
        context_path.write_text(json.dumps(context))
        yield types.SimpleNamespace(root=root, source=source, con=con, profile=profile, context=context,
                                    body=body, raw_rows=raw_rows, receipt_path=receipt_path,
                                    profile_path=profile_path, context_path=context_path)
        con.close()


def convert(facts):
    reader = tool.Reader()
    return tool.convert(facts.profile, facts.context,
                        lambda ref: reader.load_receipt(facts.root, facts.context["session_date"], ref))


def rewrite_receipt(facts):
    # Fault injection rewrites local fixture and deliberately refreshes the ref;
    # semantic checks still must reject it even with a matching file digest.
    facts.receipt_path.write_bytes(cap.canonical(facts.body))
    facts.context["receipts"][0]["sha256"] = cap.sha_file(facts.receipt_path)


def run_cli(facts, output=None, enabled="1"):
    facts.profile_path.write_text(json.dumps(facts.profile))
    facts.context_path.write_text(json.dumps(facts.context))
    return subprocess.run([sys.executable, str(MONITORING / "benefit_policy.py"), "--data-root", str(facts.root),
                           "--profile", str(facts.profile_path), "--context", str(facts.context_path),
                           "--output", str(output or facts.root / "policy.json")],
                          env={"PATH": os.defpath, "OPS_DELIVERY_EVIDENCE_ENABLED": enabled}, capture_output=True, text=True, timeout=5)


def test_actual_source_wal_receipts_produce_compatible_policy_and_isolated_restore(facts):
    result = convert(facts)
    assert result["status"] == "ready"
    policy = result["policy"]
    table = policy["artifacts"][0]["tables"]["signal_daily"]
    assert table["rows_sha256"] == hashlib.sha256(facts.raw_rows).hexdigest()
    assert "columns" not in table  # Source metadata isn't confused with expected C4 schema.
    assert result["offsite_status"] == "unknown" and result["consumer_status"] == "unknown"
    # Confirm it is WAL source evidence rather than main-file data/hash.
    raw_db = facts.root / "raw-main.db"
    shutil.copyfile(facts.source / "sentiment.db", raw_db)
    with closing(sqlite3.connect(raw_db)) as con:
        assert con.execute("SELECT count(*) FROM signal_daily").fetchone()[0] == 0
    policy_path = facts.root / "policy.json"
    tool.publish(policy_path, policy)
    manifest_path, manifest = cap.capture(policy_path, facts.root / "exports", limits=cap.Limits(32*1024*1024, 8, min_free_bytes=1))
    assert manifest["assessment"]["status"] == "validated"
    restored, _ = restore.isolated_restore(manifest_path, facts.root / "restored", manifest_sha256=cap.sha_file(manifest_path), limits=cap.Limits(32*1024*1024, 1, min_free_bytes=1))
    assert restored["restore_status"] == "validated" and restored["status"] == "unknown"


def test_cli_writes_private_immutable_policy_with_actual_control_hashes(facts):
    run = run_cli(facts)
    assert run.returncode == 0 and not run.stderr
    out = json.loads(run.stdout)
    assert out["status"] == "ready" and out["policy_written"] is True
    path = facts.root / "policy.json"
    assert path.stat().st_mode & 0o777 == 0o600
    body = json.loads(path.read_text())
    assert body["policy_source"]["profile_file_sha256"] == cap.sha_file(facts.profile_path)
    assert out["policy_sha256"] == cap.sha_file(path)
    old = path.read_bytes()
    retry = run_cli(facts)
    assert retry.returncode == 3 and json.loads(retry.stdout)["policy_written"] is False
    assert path.read_bytes() == old


def test_converter_does_not_read_current_artifacts_or_retrofit_source_pins(facts, monkeypatch):
    before = [i["sha256"] for i in facts.body["inputs"]]
    original = tool.Reader.read
    allowed = {str(facts.receipt_path)}
    def receipt_only(self, path, **kwargs):
        assert str(path) in allowed, "conversion attempted to open a current source"
        return original(self, path, **kwargs)
    monkeypatch.setattr(tool.Reader, "read", receipt_only)
    (facts.source / "freeze.json").write_text('{"changed":"after real source read"}')
    result = convert(facts)
    assert result["status"] == "ready"
    assert result["policy"]["artifacts"][1]["sha256"] == before[1]
    assert result["policy"]["artifacts"][1]["sha256"] != cap.sha_file(facts.source / "freeze.json")


@pytest.mark.parametrize("kind", ["loaded_object", "scoped_loaded_object", "ordered_loaded_observations"])
@pytest.mark.parametrize("idx", [0, 1])
def test_logical_or_ordered_digests_never_become_bytes_or_table_pins(facts, kind, idx):
    facts.body["inputs"][idx]["identity_kind"] = kind
    rewrite_receipt(facts)
    out = convert(facts)
    assert out["status"] == "unknown" and "policy" not in out
    assert "logical_digest_is_not_compatible_bytes" in str(out["reasons"])


@pytest.mark.parametrize("field", ["generation_id", "as_of", "resolved_path", "observed_at", "session_date"])
def test_missing_observed_identity_cannot_be_filled_from_static_profile_or_index(facts, field):
    facts.body["inputs"][1].pop(field)
    rewrite_receipt(facts)
    out = convert(facts)
    assert out["status"] == "unknown" and "policy" not in out


@pytest.mark.parametrize("mutation", ["wrong_generation", "asof_future", "weak", "wrong_algorithm", "live_db_bytes",
                                       "not_transaction", "partial_columns", "wrong_order", "wal_unknown", "zero_rows", "stale", "wrong_table"])
def test_db_algorithm_transaction_scope_and_generation_are_not_guessed(facts, mutation):
    fact = facts.body["inputs"][0]
    scope = fact["source_context"]
    if mutation == "wrong_generation": fact["generation_id"] = "wrong"
    elif mutation == "asof_future": fact["as_of"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    elif mutation == "weak": fact["quality"] = "weak"
    elif mutation == "wrong_algorithm": fact["digest_algorithm"] = "producer-logical-v1"
    elif mutation == "live_db_bytes": fact["digest_domain"] = "source_bytes"
    elif mutation == "not_transaction": scope["method"] = "autocommit_observation"
    elif mutation == "partial_columns": scope["columns"] = ["date"]
    elif mutation == "wrong_order": scope["order_by"] = list(reversed(scope["columns"]))
    elif mutation == "wal_unknown": scope["includes_committed_wal"] = "unknown"
    elif mutation == "zero_rows": scope["row_count"] = 0
    elif mutation == "stale": scope["max_date"] = "20261105"
    elif mutation == "wrong_table": scope["table"] = "wrong_table"
    rewrite_receipt(facts)
    out = convert(facts)
    assert out["status"] == "unknown" and "policy" not in out


def test_current_native_context_is_unknown_not_fake_policy(facts):
    for item in facts.body["inputs"]:
        item["identity_kind"] = "scoped_loaded_object"
        item.pop("generation_id")
        item.pop("as_of")
        item["snapshot_scope"] = "single_query_rows"
        item.pop("source_context", None)
    rewrite_receipt(facts)
    run = run_cli(facts)
    assert run.returncode == 3
    out = json.loads(run.stdout)
    assert out["status"] == "unknown" and not out["policy_written"] and "policy" not in out
    assert not (facts.root / "policy.json").exists()


@pytest.mark.parametrize("idx", [0, 1])
def test_actual_producer_logical_hash_does_not_equal_c4_row_or_file_bytes(facts, idx):
    original = facts.body["inputs"][idx]
    if idx == 0:
        # Existing query producer hashes named-row logical objects, not the
        # C4 canonical positional rows with LF ordering contract.
        value = [{"date": "20261106", "index_id": "test_index", "signal": "buy"}]
    else:
        value = json.loads((facts.source / "freeze.json").read_text())
    metadata = {k: original[k] for k in ("session_date", "resolved_path", "generation_id", "as_of", "observed_at")}
    logical = producer.identity_for_loaded(original["object_id"], value, **metadata)
    assert logical["sha256"] != original["sha256"]
    facts.body["inputs"][idx] = logical
    rewrite_receipt(facts)
    result = convert(facts)
    assert result["status"] == "unknown" and "policy" not in result


@pytest.mark.parametrize("folder", ["capture-sets", "capture-set", ".pending-example"])
def test_known_capture_copy_paths_cannot_supply_pins(facts, folder):
    fake_copy = str(facts.root / folder / "freeze.json")
    facts.profile["artifacts"][1]["path"] = fake_copy
    facts.body["inputs"][1]["resolved_path"] = fake_copy
    rewrite_receipt(facts)
    result = convert(facts)
    assert result["status"] == "unknown" and "policy" not in result


def test_receipt_parent_symlink_and_reference_budget_are_rejected(facts):
    directory = facts.receipt_path.parent
    moved = directory.with_name("moved-receipts")
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    assert convert(facts)["status"] == "unknown"
    facts.context["receipts"] *= tool.MAX_RECEIPTS + 1
    def no_reads(_):
        raise AssertionError("oversized index was not rejected before IO")
    result = tool.convert(facts.profile, facts.context, no_reads)
    assert result["status"] == "unknown" and "policy" not in result


def test_changed_receipt_hash_duplicate_bindings_and_missing_required_set(facts):
    original = facts.receipt_path.read_bytes()
    facts.receipt_path.write_bytes(original + b" ")
    assert convert(facts)["status"] == "unknown"
    facts.receipt_path.write_bytes(original)
    facts.context["bindings"].append(dict(facts.context["bindings"][0]))
    assert convert(facts)["status"] == "unknown"
    facts.context["bindings"] = facts.context["bindings"][:-2]
    assert convert(facts)["status"] == "unknown"


@pytest.mark.parametrize("stage", ["backup", "restore"])
def test_cannot_use_capture_or_restore_receipt_to_backfill_its_own_pins(facts, stage):
    facts.body["stage"] = stage
    rewrite_receipt(facts)
    assert convert(facts)["status"] == "unknown"


@pytest.mark.parametrize("fact_field", ["generation_id", "as_of", "sha256"])
def test_static_profile_cannot_supply_source_evidence(facts, fact_field):
    facts.profile["artifacts"][1][fact_field] = facts.body["inputs"][1].get(fact_field, "invented")
    assert convert(facts)["status"] == "unknown"


def test_insecure_symlink_fifo_and_oversized_receipt_do_not_block_or_create_policy(facts):
    original = facts.receipt_path.read_bytes()
    facts.receipt_path.unlink()
    os.mkfifo(facts.receipt_path, 0o600)
    run = run_cli(facts)
    assert run.returncode == 3 and not (facts.root / "policy.json").exists()
    facts.receipt_path.unlink()
    alternate = facts.root / "alternate.json"
    alternate.write_bytes(original)
    facts.receipt_path.symlink_to(alternate)
    assert run_cli(facts).returncode == 3
    facts.receipt_path.unlink()
    facts.receipt_path.write_bytes(b"x" * (tool.MAX_FILE + 1))
    facts.receipt_path.chmod(0o600)
    assert run_cli(facts).returncode == 3
    facts.receipt_path.write_bytes(original)
    facts.receipt_path.chmod(0o644)
    assert run_cli(facts).returncode == 3


def test_default_disabled_cli_does_not_open_configuration_or_write_output(facts):
    facts.profile_path.unlink()
    facts.context_path.unlink()
    run = subprocess.run([sys.executable, str(MONITORING / "benefit_policy.py"), "--data-root", "/forbidden/no-read",
                          "--profile", "/forbidden/profile", "--context", "/forbidden/context", "--output", str(facts.root / "disabled")],
                         env={"PATH": os.defpath}, capture_output=True, text=True, timeout=5)
    assert run.returncode == 0 and json.loads(run.stdout)["status"] == "disabled"
    assert not (facts.root / "disabled").exists()
