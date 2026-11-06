"""Bounded per-run proof handoff beside the existing async pending flag.

No worker/queue daemon: normal async passes snapshot once, then acknowledge exact id+hash.
Proof copies belong to this record set, independent of a waiting caller's temp directory.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from util_atomic import atomic_write_json, atomic_write_text

LIMIT = 32

def _identity(run_id, root):
    return hashlib.sha256((str(root) + "\0" + run_id).encode()).hexdigest()

@contextlib.contextmanager
def _locked(flag):
    directory = Path(str(flag) + ".contexts").resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / ".lock").open("a+") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield directory

def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _proof(path, run_id, root):
    path = Path(path)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("proof too large")
    raw = path.read_bytes()
    body = json.loads(raw)
    if (body.get("version") != 1 or body.get("run_id") != run_id
            or body.get("static_dir") != str(root) or not isinstance(body.get("outputs"), dict)):
        raise ValueError("proof identity/root mismatch")
    return raw, hashlib.sha256(raw).hexdigest()

def enqueue(flag, root, path, run_id):
    root = Path(root).resolve()
    if not path or not run_id:
        # Legacy callers keep the existing wakeup; no invented proof authorization.
        with _locked(flag):
            Path(flag).touch()
        return {"status": "legacy", "registered": False}
    identity = _identity(run_id, root)
    with _locked(flag) as directory:
        record_path = directory / (identity + ".json")
        prior = _read(record_path) if record_path.exists() else None
        if prior and prior.get("state") in ("done", "superseded") and not Path(path).exists():
            return prior  # completed exact run retry needs no resurrected producer temp file
        try:
            raw, digest = _proof(path, run_id, root)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            if prior is None:
                prior = {"version": 1, "id": identity, "run_id": run_id,
                         "static_dir": str(root), "original_path": str(path),
                         "state": "missing", "proof_sha256": None,
                         "created_at": time.time(), "offered_at": 0,
                         "reason": type(exc).__name__}
                atomic_write_json(record_path, prior, mode=0o600)
            Path(flag).touch()
            raise ValueError("pending request proof unavailable; record retained") from exc
        if prior and prior.get("proof_sha256") not in (None, digest):
            raise ValueError("same run-id attempted to replace immutable proof")
        if prior and prior.get("state") in ("done", "superseded"):
            return prior  # exact retries never resurrect a consumed request
        proof_path = directory / (identity + "." + digest + ".proof")
        if not proof_path.exists():
            atomic_write_text(proof_path, raw.decode("utf-8"), mode=0o600)
        elif hashlib.sha256(proof_path.read_bytes()).hexdigest() != digest:
            raise ValueError("queue-owned proof changed")
        record = {"version": 1, "id": identity, "run_id": run_id,
                  "static_dir": str(root), "proof_path": str(proof_path),
                  "proof_sha256": digest, "state": "pending",
                  "created_at": (prior or {}).get("created_at", time.time()),
                  "offered_at": (prior or {}).get("offered_at", 0)}
        atomic_write_json(record_path, record, mode=0o600)
        Path(flag).touch()
        return record

def snapshot(flag, root, output):
    root = Path(root).resolve()
    with _locked(flag) as directory:
        candidates = []
        for p in directory.glob("*.json"):
            try:
                row = _read(p)
                if row.get("static_dir") == str(root) and row.get("state") in ("pending", "missing"):
                    candidates.append((row.get("offered_at", 0), row.get("created_at", 0), p, row))
            except (OSError, ValueError, TypeError):
                continue
        candidates.sort(key=lambda row: (row[0], row[1], row[2].name))
        selected = []
        for _, _, p, row in candidates[:LIMIT]:
            row["offered_at"] = time.time()
            atomic_write_json(p, row, mode=0o600)
            selected.append(row)
        # Rename claims only this legacy wakeup instance. A later touch creates a new flag.
        claim = None
        if Path(flag).exists():
            claim = directory / (".legacy-" + uuid.uuid4().hex)
            try:
                os.replace(flag, claim)
            except FileNotFoundError:
                claim = None
        body = {"version": 1, "static_dir": str(root), "batch_id": uuid.uuid4().hex,
                "records": selected, "legacy_claim": str(claim) if claim else None}
        atomic_write_json(output, body, mode=0o600)
        return body

def finish(flag, root, batch_path, result_path, phase_ok):
    root = Path(root).resolve()
    batch = _read(batch_path)
    if batch.get("static_dir") != str(root):
        raise ValueError("snapshot root mismatch")
    try:
        result = _read(result_path) if phase_ok and Path(result_path).exists() else {}
    except (OSError, ValueError, TypeError):
        result = {}
    outcomes = result.get("outcomes", []) if result.get("batch_id") == batch.get("batch_id") else []
    offered = {(r.get("id"), r.get("proof_sha256")): r for r in batch.get("records", [])}
    consumed = []
    with _locked(flag) as directory:
        for outcome in outcomes:
            key = outcome.get("id"), outcome.get("proof_sha256")
            if key not in offered or not key[1] or outcome.get("state") not in ("done", "superseded"):
                continue
            p = directory / (key[0] + ".json")
            if not p.exists():
                continue
            row = _read(p)
            if (row.get("state") != "pending" or row.get("proof_sha256") != key[1]
                    or row.get("static_dir") != str(root)):
                continue
            proof_path = directory / (key[0] + "." + key[1] + ".proof")
            if (row.get("proof_path") != str(proof_path) or not proof_path.exists()
                    or hashlib.sha256(proof_path.read_bytes()).hexdigest() != key[1]):
                continue
            row["state"] = outcome["state"]
            row["completed_at"] = time.time()
            atomic_write_json(p, row, mode=0o600)  # durable tombstone before retiring owned proof
            proof_path.unlink(missing_ok=True)
            consumed.append(key[0])
        remaining = 0
        for p in directory.glob("*.json"):
            try:
                row = _read(p)
                if row.get("static_dir") == str(root) and row.get("state") in ("pending", "missing"):
                    remaining += 1
            except (OSError, ValueError, TypeError):
                continue
        if remaining or (batch.get("legacy_claim") and not phase_ok):
            Path(flag).touch()  # next normal worker; never remove a newer registration's flag
        claim = batch.get("legacy_claim")
        if claim and Path(claim).parent == directory and Path(claim).name.startswith(".legacy-"):
            Path(claim).unlink(missing_ok=True)
    return {"consumed": consumed, "remaining": remaining}

def retire_source(flag, root, path, run_id):
    if not path or not run_id:
        return {"retired_source": False}
    root = Path(root).resolve()
    with _locked(flag) as directory:
        record = directory / (_identity(run_id, root) + ".json")
        if not record.exists() or not Path(path).exists():
            return {"retired_source": False}
        row = _read(record)
        _, digest = _proof(path, run_id, root)
        if digest != row.get("proof_sha256"):
            return {"retired_source": False}
        owned = Path(row["proof_path"])
        if Path(path).resolve() == owned.resolve():
            return {"retired_source": False}
        if row.get("state") not in ("done", "superseded"):
            if not owned.exists() or hashlib.sha256(owned.read_bytes()).hexdigest() != digest:
                return {"retired_source": False}
        Path(path).unlink()
        try:
            Path(path).parent.rmdir()
        except OSError:
            pass
        return {"retired_source": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("enqueue", "snapshot", "finish", "retire-source"))
    parser.add_argument("--batch")
    parser.add_argument("--result")
    parser.add_argument("--phase-ok", action="store_true")
    args = parser.parse_args()
    flag = os.environ.get("R2_UPLOAD_ASYNC_PENDING", "/tmp/trade_r2_upload_async.pending")
    root = (Path(os.environ["REPO"]) / "static-site").resolve()
    if args.action == "enqueue":
        answer = enqueue(flag, root, os.environ.get("R2_EXPORT_PROOF_PATH"), os.environ.get("R2_EXPORT_RUN_ID"))
    elif args.action == "retire-source":
        answer = retire_source(flag, root, os.environ.get("R2_EXPORT_PROOF_PATH"), os.environ.get("R2_EXPORT_RUN_ID"))
    elif args.action == "snapshot":
        answer = snapshot(flag, root, args.batch)
    else:
        answer = finish(flag, root, args.batch, args.result, args.phase_ok)
    print(json.dumps(answer, ensure_ascii=False))

if __name__ == "__main__":
    main()
