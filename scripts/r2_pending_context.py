"""Bounded per-run proof handoff beside the existing async pending flag.

No worker/queue daemon: normal async passes snapshot once, then acknowledge exact id+hash.
Proof copies belong to this record set, independent of a waiting caller's temp directory.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
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


# Inspect deliberately does not call _locked: diagnostics must never mkdir/touch/write.
INSPECT_MAX_RECORDS = 128
INSPECT_MAX_ENTRIES = 1024
INSPECT_RECORD_BYTES = 64 * 1024
INSPECT_PROOF_BYTES = 1024 * 1024
INSPECT_SECONDS = 5


def _inspect_require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _inspect_path(value):
    path = Path(value)
    _inspect_require(path.is_absolute() and '..' not in path.parts
                     and len(str(path)) <= 4096, 'unsafe_path')
    # The OS-owned /tmp alias is needed by the existing default on macOS.
    # No other caller-controlled symlink is resolved.
    if path.parts[1:2] == ('tmp',):
        path = Path('/tmp').resolve().joinpath(*path.parts[2:])
    return path


@contextlib.contextmanager
def _inspect_directory(path):
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=fd)
            os.close(fd)
            fd = new
        info = os.fstat(fd)
        _inspect_require(info.st_uid == os.geteuid() and not info.st_mode & 0o022,
                         'unsafe_directory')
        yield fd
    finally:
        os.close(fd)


def _inspect_stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink, info.st_uid)


def _inspect_regular(info, private=True):
    _inspect_require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and info.st_uid == os.geteuid()
                     and not info.st_mode & (0o077 if private else 0o022),
                     'unsafe_file')


def _inspect_read(fd, name, limit, observed):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _inspect_regular(before)
        _inspect_require(before.st_size <= limit, 'file_too_large')
        raw = stream.read(limit + 1)
        _inspect_require(len(raw) <= limit, 'file_too_large')
        stamp = _inspect_stamp(before)
        _inspect_require(stamp == _inspect_stamp(os.fstat(stream.fileno()))
                         == _inspect_stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)),
                         'changed_during_read')
        observed[name] = stamp
        return raw


def _inspect_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _inspect_require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    body = json.loads(raw, object_pairs_hook=pairs)
    _inspect_require(isinstance(body, dict), 'invalid_json_object')
    return body


def _inspect_time(value):
    return (type(value) in (int, float) and value >= 0
            and (type(value) is int or math.isfinite(value)))


def _inspect_row(fd, directory, name, root, now, observed):
    answer = {'record_file': name, 'id': None, 'run_id': None,
              'state': 'unknown', 'consumption_status': 'unknown',
              'proof_integrity': 'unknown', 'wait_seconds': None,
              'since_last_offer_seconds': None, 'deadline_status': 'unknown',
              'deadline_reason': 'no_explicit_request_contract',
              'public_bytes_status': 'unknown', 'issues': []}
    try:
        row = _inspect_json(_inspect_read(fd, name, INSPECT_RECORD_BYTES, observed))
        identity, run_id, static_dir = row.get('id'), row.get('run_id'), row.get('static_dir')
        _inspect_require(type(row.get('version')) is int and row['version'] == 1
                         and isinstance(run_id, str) and 0 < len(run_id) <= 4096
                         and isinstance(static_dir, str) and Path(static_dir).is_absolute()
                         and '..' not in Path(static_dir).parts
                         and str(Path(static_dir)) == static_dir
                         and identity == _identity(run_id, static_dir)
                         and name == identity + '.json', 'invalid_request_identity')
        answer.update(id=identity, run_id=run_id,
                      scope='requested_root' if static_dir == str(root) else 'other_root')
        state = row.get('state')
        _inspect_require(state in ('pending', 'missing', 'done', 'superseded'), 'invalid_state')
        terminal = state in ('done', 'superseded')
        answer.update(state=state, **{field: row.get(field) if _inspect_time(row.get(field))
                      else None for field in ('created_at', 'offered_at', 'completed_at')})
        created, offered = row.get('created_at'), row.get('offered_at')
        completed = row.get('completed_at')
        end = completed if terminal else now
        if (not all(_inspect_time(t) for t in (created, offered, end))
                or not 0 < created <= end <= now
                or (offered != 0 and not created <= offered <= end)
                or (terminal and offered == 0)
                or (not terminal and completed is not None)):
            answer['issues'].append('invalid_or_future_timestamp')
        else:
            answer['wait_seconds'] = end - created
            answer['since_last_offer_seconds'] = end - offered if offered else None
            answer['consumption_status'] = (state if terminal else
                                            'offered' if offered else 'not_offered')
        digest = row.get('proof_sha256')
        answer['proof_sha256'] = (digest if isinstance(digest, str)
            and re.fullmatch('[0-9a-f]{64}', digest) else None)
        if state == 'missing':
            answer['proof_integrity'] = 'missing'
            answer['issues'].append('proof_unavailable')
            return answer
        _inspect_require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest),
                         'invalid_proof_digest')
        proof_name = identity + '.' + digest + '.proof'
        _inspect_require(row.get('proof_path') == str(directory / proof_name),
                         'unsafe_proof_path')
        try:
            raw = _inspect_read(fd, proof_name, INSPECT_PROOF_BYTES, observed)
        except FileNotFoundError:
            observed[proof_name] = None
            answer['proof_integrity'] = 'retired' if terminal else 'missing'
            if not terminal:
                answer['issues'].append('proof_unavailable')
            return answer
        _inspect_require(hashlib.sha256(raw).hexdigest() == digest, 'proof_hash_mismatch')
        proof = _inspect_json(raw)
        _inspect_require(type(proof.get('version')) is int and proof['version'] == 1
                         and proof.get('run_id') == run_id
                         and proof.get('static_dir') == static_dir, 'proof_identity_mismatch')
        outputs = proof.get('outputs')
        _inspect_require(isinstance(outputs, dict) and bool(outputs), 'invalid_proof_outputs')
        for key, value in outputs.items():
            _inspect_require(isinstance(key, str) and bool(key)
                             and not Path(key).is_absolute() and '..' not in Path(key).parts
                             and str(Path(key)) == key and '\\' not in key
                             and isinstance(value, dict) and type(value.get('size')) is int
                             and value['size'] >= 0 and isinstance(value.get('sha256'), str)
                             and re.fullmatch('[0-9a-f]{64}', value['sha256']),
                             'invalid_proof_output')
        answer.update(proof_integrity='verified_owned_copy', output_count=len(outputs))
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        answer['issues'].append(_inspect_error(exc))
        answer['proof_integrity'] = 'unknown' if answer['id'] is None else 'invalid'
    return answer


def _inspect_error(exc):
    # Do not echo attacker-controlled JSON, paths, or exception text into diagnostics.
    if isinstance(exc, OSError):
        return 'filesystem_error_' + str(exc.errno)
    if type(exc) is ValueError and re.fullmatch('[a-z_]+', str(exc)):
        return str(exc)
    return 'invalid_metadata_' + type(exc).__name__


def inspect_contexts(flag, root, *, limit=LIMIT, now=None, budget_seconds=INSPECT_SECONDS):
    """Bounded, local, read-only evidence; never a public-byte health/SLA assertion.

    Only the requested root is returned; all scanned records count against limits.
    Observed counts in a partial view are not queue totals. No deadline contract
    exists in this schema. budget_seconds is a cooperative local I/O budget only.
    """
    _inspect_require(type(limit) is int and 1 <= limit <= INSPECT_MAX_RECORDS, 'invalid_limit')
    _inspect_require(type(budget_seconds) in (int, float)
                     and 0 <= budget_seconds <= INSPECT_SECONDS, 'invalid_budget')
    now = time.time() if now is None else now
    _inspect_require(_inspect_time(now), 'invalid_now')
    result = {'version': 1, 'observed_at': now, 'inspection_status': 'unavailable',
              'health': 'unknown', 'public_bytes_status': 'unknown',
              'records': [], 'issues': [], 'truncated': False, 'entries_scanned': 0,
              'records_scanned': 0, 'other_root_records': 0,
              'limits': {'records': limit, 'entries': INSPECT_MAX_ENTRIES,
                         'record_bytes': INSPECT_RECORD_BYTES,
                         'proof_bytes': INSPECT_PROOF_BYTES, 'seconds': budget_seconds}}
    started = time.monotonic()
    try:
        _inspect_require(budget_seconds > 0, 'inspection_budget_exhausted')
        directory = _inspect_path(str(flag) + '.contexts')
        root = Path(root).resolve()
        with _inspect_directory(directory) as fd:
            before = _inspect_stamp(os.fstat(fd))
            lock = os.open('.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                lock_info = os.fstat(lock)
                _inspect_regular(lock_info, private=False)
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                observed = {'.lock': _inspect_stamp(lock_info)}
                with os.scandir(fd) as entries:
                    for entry in entries:
                        if (result['entries_scanned'] >= INSPECT_MAX_ENTRIES
                                or time.monotonic() - started >= budget_seconds):
                            result['truncated'] = True
                            break
                        result['entries_scanned'] += 1
                        if not entry.name.endswith('.json'):
                            continue
                        if result['records_scanned'] >= limit:
                            result['truncated'] = True
                            break
                        result['records_scanned'] += 1
                        row = _inspect_row(fd, directory, entry.name, root, now, observed)
                        if row.pop('scope', None) == 'other_root':
                            result['other_root_records'] += 1
                            if row['issues']:
                                result['issues'].append('invalid_other_root_record')
                        else:
                            result['records'].append(row)
                for name, stamp in observed.items():
                    try:
                        current = _inspect_stamp(os.stat(name, dir_fd=fd, follow_symlinks=False))
                    except FileNotFoundError:
                        current = None
                    _inspect_require(current == stamp, 'changed_during_inspection')
                _inspect_require(before == _inspect_stamp(os.fstat(fd)), 'directory_changed')
                with _inspect_directory(directory) as reopened:
                    _inspect_require(before == _inspect_stamp(os.fstat(reopened)), 'directory_changed')
                if time.monotonic() - started >= budget_seconds:
                    result['truncated'] = True
                if result['truncated']:
                    result['issues'].append('scan_truncated')
                result['inspection_status'] = ('incomplete' if result['issues']
                    or any(r['issues'] for r in result['records']) else 'complete')
            finally:
                os.close(lock)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        result['issues'].append(_inspect_error(exc))
        # Any rows already read are evidence only, not a coherent scan.
        result['inspection_status'] = 'incomplete' if result['records'] else 'unavailable'
    result['records'].sort(key=lambda row: row['record_file'])
    result['counts'] = {state: sum(r['state'] == state for r in result['records'])
                                 for state in ('pending', 'missing', 'done', 'superseded', 'unknown')}
    read_uncertain = any(
        issue.startswith('filesystem_error_') or issue == 'changed_during_read'
        for row in result['records'] for issue in row['issues'])
    if result['issues'] or result['inspection_status'] == 'unavailable' or read_uncertain:
        result.update(status='unknown', reason='inspection_incomplete')
    elif any(r['issues'] for r in result['records']):
        result.update(status='warning', reason='invalid_request_evidence')
    elif result['counts']['pending'] or result['counts']['missing']:
        result.update(status='unknown', reason='pending_without_deadline_contract')
    else:
        result.update(status='empty', reason='no_pending_requests_observed')
    result['summary'] = project_observation(result)
    return result


def project_observation(report):
    """Pure <=20-scalar projection for ops evidence; no paths or free-form text."""
    rows = report['records']
    active = [r for r in rows if r['state'] in ('pending', 'missing')]
    waits = [r['wait_seconds'] for r in active if r['wait_seconds'] is not None]
    return {
        'status': report['status'], 'reason': report['reason'],
        'inspection_status': report['inspection_status'],
        **{state + '_count': count for state, count in report['counts'].items()},
        'proof_invalid_count': sum(r['proof_integrity'] in ('invalid', 'missing') for r in rows),
        'invalid_record_count': sum(bool(r['issues']) for r in rows),
        'oldest_wait_seconds': max(waits, default=None),
        'unoffered_count': sum(r['consumption_status'] == 'not_offered' for r in active),
        'records_scanned': report['records_scanned'],
        'entries_scanned': report['entries_scanned'],
        'other_root_records': report['other_root_records'],
        'truncated': report['truncated'],
        'deadline_status': 'unknown', 'public_bytes_status': 'unknown',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("enqueue", "snapshot", "finish", "retire-source", "inspect"))
    parser.add_argument("--batch")
    parser.add_argument("--result")
    parser.add_argument("--phase-ok", action="store_true")
    parser.add_argument("--limit", type=int, default=LIMIT, help="inspect record limit (1..128)")
    args = parser.parse_args()
    if args.action == "inspect" and not 1 <= args.limit <= INSPECT_MAX_RECORDS:
        parser.error("--limit must be between 1 and 128")
    flag = os.environ.get("R2_UPLOAD_ASYNC_PENDING", "/tmp/trade_r2_upload_async.pending")
    root = (Path(os.environ["REPO"]) / "static-site").resolve()
    if args.action == "inspect":
        answer = inspect_contexts(flag, root, limit=args.limit)
    elif args.action == "enqueue":
        answer = enqueue(flag, root, os.environ.get("R2_EXPORT_PROOF_PATH"), os.environ.get("R2_EXPORT_RUN_ID"))
    elif args.action == "retire-source":
        answer = retire_source(flag, root, os.environ.get("R2_EXPORT_PROOF_PATH"), os.environ.get("R2_EXPORT_RUN_ID"))
    elif args.action == "snapshot":
        answer = snapshot(flag, root, args.batch)
    else:
        answer = finish(flag, root, args.batch, args.result, args.phase_ok)
    print(json.dumps(answer, ensure_ascii=False))
    if args.action == "inspect" and answer["inspection_status"] != "complete":
        raise SystemExit(2)

if __name__ == "__main__":
    main()
