"""Opt-in local delivery facts. No business engines, credentials or network.

Stage completion never certifies chain completion. In particular loaded objects
prove what this caller saw, not source arrival, calendar completeness or a
consumer's use. Readers must apply the independently approved delivery contract.
"""
from __future__ import annotations

import contextvars
from datetime import datetime, timezone
import functools
import hashlib
import inspect
import itertools
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import uuid
import types
from zoneinfo import ZoneInfo

SCHEMA = "trade-delivery-receipt-v1"
STAGES = {"signal", "freeze", "plan", "backtest", "publish", "backup", "restore", "consumer"}
REQUIRED = ("receipt_id", "chain_id", "object_id", "session_date", "attempt_id",
            "batch_id", "evaluated_at", "stage_status", "reason", "code_identity",
            "config_identity", "inputs", "outputs", "counts", "consumer_witness")
MAX_BYTES = 64 * 1024
MAX_IDENTITIES = 64
MAX_EVENTS = 32
MAX_HASH_BYTES = 32 * 1024 * 1024
MAX_HASH_NODES = 200000
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_PROCESS_ATTEMPT = f"{os.getpid()}-{uuid.uuid4().hex}"
_ACTIVE = contextvars.ContextVar("delivery_capture", default=None)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def evidence_enabled():
    return os.environ.get("OPS_DELIVERY_EVIDENCE_ENABLED", "0") == "1"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _logical(value, budget=None):
    """Canonicalize already loaded values, including SQLite rows and series.

    This is a logical-data digest; it is explicitly not an exact source-byte hash.
    No fallback repr(): unsupported objects must surface a metadata failure.
    """
    if budget is None:
        budget = [MAX_HASH_NODES, MAX_HASH_BYTES]
    budget[0] -= 1
    budget[1] -= len(value) * 4 if isinstance(value, str) else 16
    if budget[0] < 0 or budget[1] < 0:
        raise ValueError("loaded identity work budget exceeded")
    convert = lambda v: _logical(v, budget)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"nonfinite": str(value)}
    if isinstance(value, dict):
        # JSON object keys would lose tuple/type identity; use sorted pairs.
        pairs = [(convert(k), convert(v)) for k, v in value.items()]
        return {"pairs": sorted(pairs, key=lambda p: _canonical(p[0]))}
    if isinstance(value, (list, tuple)):
        return [convert(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {"set": sorted((convert(v) for v in value), key=_canonical)}
    if hasattr(value, "keys"):  # sqlite3.Row
        return convert({k: value[k] for k in value.keys()})
    if hasattr(value, "items"):  # pandas Series, without importing pandas
        # Consume lazily up to the node budget, before making a full copy.
        pairs = []
        for k, v in value.items():
            pairs.append((convert(k), convert(v)))
        return {"pairs": sorted(pairs, key=lambda p: _canonical(p[0]))}
    if hasattr(value, "item"):  # numpy scalar
        return convert(value.item())
    raise TypeError("unsupported loaded value type")


def identity_for_bytes(object_id, payload, **metadata):
    if not isinstance(payload, bytes):
        raise TypeError("payload must be actual bytes")
    if len(payload) > MAX_HASH_BYTES:
        raise ValueError("byte identity work budget exceeded")
    return dict(metadata, object_id=object_id, sha256=hashlib.sha256(payload).hexdigest(),
                size=len(payload), identity_kind="bytes",
                observed_at=metadata.get("observed_at", utc_now()),
                quality=metadata.get("quality", "strong"))


def identity_for_loaded(object_id, value, **metadata):
    result = identity_for_bytes(object_id, _canonical(_logical(value)), **metadata)
    result["identity_kind"] = "loaded_object"
    return result


def _private_dir(path):
    path.mkdir(mode=0o700, exist_ok=True)
    mode = path.lstat().st_mode
    if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) != 0o700:
        raise ValueError("receipt directory must be a real private 0700 directory")


def receipt_root(data_root):
    return Path(data_root) / "data" / "ops_delivery"


def _validate(body):
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        raise ValueError("unsupported receipt schema")
    if any(k not in body for k in REQUIRED):
        raise ValueError("missing receipt field")
    for k in ("receipt_id", "chain_id", "object_id", "attempt_id", "batch_id"):
        if not isinstance(body[k], str) or not _ID.fullmatch(body[k]):
            raise ValueError("invalid receipt identity")
    if body.get("stage") not in STAGES or body["stage_status"] not in {"success", "failure", "unknown"}:
        raise ValueError("invalid receipt stage/status")
    if body.get("evidence_quality") not in {"strong", "weak", "unknown", "stage_only"}:
        raise ValueError("invalid evidence quality")
    if body["session_date"] != "unknown":
        datetime.strptime(body["session_date"], "%Y-%m-%d")
    for k in ("evaluated_at",):
        if datetime.fromisoformat(body[k].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("timestamp requires timezone")
    if not isinstance(body["reason"], str):
        raise ValueError("invalid reason")
    for k in ("inputs", "outputs"):
        if not isinstance(body[k], list) or len(body[k]) > MAX_IDENTITIES or any(not isinstance(v, dict) for v in body[k]):
            raise ValueError("invalid identities")
    for k in ("counts", "consumer_witness", "code_identity", "config_identity"):
        if not isinstance(body[k], dict):
            raise ValueError("invalid receipt object")
    if any(type(v) is not int or v < 0 for v in body["counts"].values()):
        raise ValueError("counts must be nonnegative integers")
    if len(body.get("events", [])) > MAX_EVENTS:
        raise ValueError("too many receipt events")
    return body


def read_receipt(path):
    """Strict schema reader, NOT a validator of delivery business predicates."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("receipt must be a regular 0600 file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("receipt too large")
    body = _validate(json.loads(raw))
    if Path(path).name != body["receipt_id"] + ".json":
        raise ValueError("receipt filename does not match identity")
    return body


def iter_receipts(data_root, session_dates=None, chain_ids=None):
    """Yield validated receipts; invalid files raise instead of disappearing."""
    directory = receipt_root(data_root) / "receipts"
    if not directory.exists():
        return
    sessions = [directory / d for d in session_dates] if session_dates is not None else sorted(directory.iterdir())
    for session in sessions:
        if not session.is_dir() or session.is_symlink():
            continue
        chains = [session / c for c in chain_ids] if chain_ids is not None else sorted(session.iterdir())
        for chain in chains:
            if chain.is_dir() and not chain.is_symlink():
                for path in sorted(chain.glob("*.json")):
                    body = read_receipt(path)
                    if body["session_date"] != session.name or body["chain_id"] != chain.name:
                        raise ValueError("receipt partition mismatch")
                    yield body


def _metadata_failure(exc):
    # Exception text may include paths/content; expose only bounded type.
    try:
        print(f"[delivery-evidence] metadata_failure: {type(exc).__name__}", file=sys.stderr)
    except Exception:
        pass  # A closed stderr cannot replace a business result/exception.
    return {"status": "metadata_failure", "reason": type(exc).__name__}


def emit_receipt(*, data_root, stage, chain_id, object_id, session_date="unknown",
                 attempt_id="unknown", batch_id="unknown", stage_status="unknown",
                 reason="unknown", inputs=(), outputs=(), counts=None,
                 consumer_witness=None, code_identity=None, config_identity=None,
                 producer_time=None, receipt_id=None, evaluated_at=None,
                 evidence_quality="unknown", enabled=None, events=()):
    """Best-effort immutable publication, never changes business return/exception.

    enabled is a trusted local configuration/test override, never remote input.
    A caller-supplied ID retry must supply identical evaluated_at and body.
    """
    if not (evidence_enabled() if enabled is None else enabled is True):
        return {"status": "disabled"}
    temp = None
    try:
        if session_date != "unknown":
            session_date = datetime.strptime(str(session_date).replace("-", ""), "%Y%m%d").strftime("%Y-%m-%d")
        if batch_id == "unknown" and session_date != "unknown":
            batch_id = f"{chain_id}:{session_date}"
        if len(reason) > 2048:
            raise ValueError("reason too large")
        body = dict(schema=SCHEMA, receipt_id=receipt_id or uuid.uuid4().hex,
                    stage=stage, chain_id=chain_id, object_id=object_id,
                    session_date=session_date, attempt_id=attempt_id if attempt_id != "unknown" else _PROCESS_ATTEMPT,
                    batch_id=batch_id, evaluated_at=evaluated_at or utc_now(),
                    stage_status=stage_status, reason=reason, inputs=list(itertools.islice(inputs, MAX_IDENTITIES + 1)),
                    outputs=list(itertools.islice(outputs, MAX_IDENTITIES + 1)), counts=counts or {},
                    code_identity=code_identity or {"sha": "unknown"},
                    config_identity=config_identity or {"sha256": "unknown"},
                    consumer_witness=consumer_witness or {"status": "unknown", "reason": "not_observed"},
                    evidence_quality=evidence_quality, producer_time=producer_time or {},
                    events=list(itertools.islice(events, MAX_EVENTS + 1)))
        _validate(body)
        payload = _canonical(body)
        if len(payload) > MAX_BYTES:
            raise ValueError("receipt too large")
        root = receipt_root(data_root)
        root.parent.mkdir(parents=True, exist_ok=True)
        _private_dir(root)
        directory = root
        for part in ("receipts", session_date, chain_id):
            directory = directory / part
            _private_dir(directory)
        target = directory / (body["receipt_id"] + ".json")
        fd, name = tempfile.mkstemp(prefix=".receipt-", dir=directory)
        temp = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp, target)  # atomic O_EXCL publication; never replace
            status = "written"
        except FileExistsError:
            read_receipt(target)  # rejects symlink/insecure existing file
            if target.read_bytes() != payload:
                raise ValueError("immutable receipt conflict")
            status = "idempotent"
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {"status": status, "receipt_id": body["receipt_id"],
                "receipt_sha256": hashlib.sha256(payload).hexdigest()}
    except Exception as exc:
        return _metadata_failure(exc)
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError as exc:
                _metadata_failure(exc)


class _Capture:
    def __init__(self, data_root, stage, chain_id, object_id, fn):
        self.fn = fn
        self.data_root, self.stage, self.chain_id, self.object_id = data_root, stage, chain_id, object_id
        self.inputs, self.outputs, self.events, self.errors = [], [], [], []
        self.started = utc_now()
        self.work_seconds = 0.0
        self.hash_bytes = 0
        self.operations = 0
        self.validation = None
        self.session_date = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        self.attempt_id = _PROCESS_ATTEMPT
        self.config = {"sha256": "unknown"}
        self.code = loaded_code_identity(fn, data_root)

    def record(self, object_id, value, *, output=False, raw=False, config=False, **metadata):
        if self.errors:
            return value
        began = time.monotonic()
        try:
            self.operations += 1
            target = self.outputs if output else self.inputs
            if self.operations > 256 or len(target) >= MAX_IDENTITIES or self.work_seconds >= 0.75:
                raise ValueError("stage capture work budget exceeded")
            identity = (identity_for_bytes if raw else identity_for_loaded)(object_id, value, **metadata)
            if "query_scope" in metadata:
                identity["content_sha256"] = identity["sha256"]
                identity["sha256"] = hashlib.sha256(_canonical([metadata["query_scope"], identity["sha256"]])).hexdigest()
                identity["identity_kind"] = "scoped_loaded_object"
            self.hash_bytes += identity["size"]
            if self.hash_bytes > MAX_HASH_BYTES:
                raise ValueError("stage hashing budget exceeded")
            identity.setdefault("session_date", self.session_date)
            previous = next((v for v in target if v['object_id'] == object_id), None)
            if previous is None:
                target.append(identity)
            elif previous["sha256"] != identity["sha256"]:
                # Bind the actual ordered read observations, not a fictional DB snapshot.
                previous["sha256"] = hashlib.sha256(_canonical([previous["sha256"], identity["sha256"]])).hexdigest()
                previous["identity_kind"] = "ordered_loaded_observations"
                previous["snapshot_scope"] = "multiple_queries_not_single_transaction"
                previous["quality"] = "weak"
                previous["observed_at"] = identity["observed_at"]
            if config:
                self.config = {"sha256": identity["sha256"], "kind": "loaded_object"}
            return value
        except Exception as exc:
            if not self.errors:
                _metadata_failure(exc)
            self.errors[:] = [type(exc).__name__]
            return value
        finally:
            self.work_seconds += time.monotonic() - began

    def finish(self, status, reason):
        validated = (self.validation is not None and not self.errors
                     and re.fullmatch(r"[0-9a-f]{40}", self.code.get("sha", ""))
                     and re.fullmatch(r"[0-9a-f]{64}", self.config.get("sha256", "")))
        counts = self.validation if validated else {"metadata_failures": len(self.errors)}
        if validated:
            status = "failure" if counts["failed"] else "unknown" if counts["unknown"] else status
        return emit_receipt(data_root=self.data_root, stage=self.stage, chain_id=self.chain_id,
                            object_id=self.object_id, session_date=self.session_date,
                            attempt_id=self.attempt_id, stage_status="unknown" if self.errors else status,
                            reason="metadata_failure" if self.errors else reason,
                            inputs=self.inputs, outputs=self.outputs,
                            counts=counts,
                            code_identity=self.code, config_identity=self.config,
                            producer_time={"started_at": self.started, "completed_at": utc_now(),
                                           "arrival_at": "unknown"},
                            evidence_quality="unknown" if self.errors else "strong" if validated else "stage_only", events=self.events)


def _code_digest(code):
    # marshal's reference/interning flags can change on the first execution.
    # Hash stable loaded semantics, independent of runtime quickening and paths.
    def constant(value):
        if isinstance(value, types.CodeType):
            return {"code": _code_digest(value)}
        if isinstance(value, bytes):
            return {"bytes": value.hex()}
        if isinstance(value, (tuple, frozenset)):
            values = [constant(v) for v in value]
            return {type(value).__name__: sorted(values, key=_canonical) if isinstance(value, frozenset) else values}
        return {type(value).__name__: repr(value)}
    stable = {k: getattr(code, k) for k in ("co_names", "co_varnames", "co_freevars", "co_cellvars",
                                           "co_flags", "co_argcount", "co_kwonlyargcount", "co_posonlyargcount")}
    stable.update(bytecode=code.co_code.hex(), constants=[constant(v) for v in code.co_consts],
                  exceptions=getattr(code, "co_exceptiontable", b"").hex())
    return hashlib.sha256(_canonical(stable)).hexdigest()


def loaded_code_identity(fn, data_root):
    """Loaded Python module identity plus optional reviewed local commit binding.

    Never infer loaded code from HEAD or a disk file read after execution. Claude
    provisions the private manifest AFTER review/commit on the actual runtime.
    {schema:'trade-producer-identity-v1', reviewed:true, code_sha:40hex,
     loaded_module_sha256:[...actual loaded digests reviewed for that version...]}
    Missing/mismatched binding remains unknown; module digest is still available.
    """
    pieces = []
    for name, value in sorted(fn.__globals__.items()):
        if inspect.isfunction(value):
            pieces.append((name, value.__module__, _code_digest(inspect.unwrap(value).__code__)))
    # Include instrumentation implementation, including class methods. A helper
    # update must invalidate an approved binding even if its imported decorator
    # function's own bytecode happens to be unchanged.
    for name, value in sorted(globals().items()):
        if inspect.isfunction(value) and value.__module__ == __name__:
            pieces.append(("evidence." + name, __name__, _code_digest(value.__code__)))
        elif inspect.isclass(value) and value.__module__ == __name__:
            for method, implementation in sorted(vars(value).items()):
                if inspect.isfunction(implementation):
                    pieces.append(("evidence." + name + "." + method, __name__,
                                   _code_digest(implementation.__code__)))
    module_sha = hashlib.sha256(_canonical(pieces)).hexdigest()
    result = {"sha": "unknown", "kind": "loaded_python_module", "module_sha256": module_sha,
              "coverage": "module_and_direct_imported_function_code_plus_evidence_helper;runtime_constants_in_config;transitive_dependencies_unattested"}
    path = receipt_root(data_root) / "producer-identity.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return result
            raw = stream.read(MAX_BYTES + 1)
        if stat.S_IMODE(info.st_mode) != 0o600 or len(raw) > MAX_BYTES:
            return result
        binding = json.loads(raw)
        if (binding.get("schema") == "trade-producer-identity-v1" and binding.get("reviewed") is True
                and re.fullmatch(r"[0-9a-f]{40}", binding.get("code_sha", ""))
                and isinstance(binding.get("loaded_module_sha256"), list)
                and len(binding["loaded_module_sha256"]) <= 128
                and module_sha in binding["loaded_module_sha256"]):
            result["sha"] = binding["code_sha"]
            result["binding_sha256"] = hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return result


def _validation(predicates):
    current = _ACTIVE.get()
    if current:
        values = list(predicates)
        current.validation = {"inventory_complete": 1, "expected": len(values),
                              "validated": sum(v is True for v in values),
                              "failed": sum(v is False for v in values),
                              "unknown": sum(v is not True and v is not False for v in values)}


def validate_backtest_outputs(stats, trades, quadrants):
    """Validate the existing engine's loaded -> columnar projection and counts.

    Local generation contract only; no source freshness/strategy-profit claim.
    A production contract must additionally require its declared raw inputs and
    selected-basis artifacts. No consumer is manufactured here.
    """
    current = _ACTIVE.get()
    if not current:
        return
    try:
        current.record("backtest_input", quadrants)
        current.record("backtest_config", stats["config"], config=True)
        if current.errors:
            return
        fields = trades["fields"]
        checks = [isinstance(fields, list), len(fields) == len(set(fields)),
                  "signal_date" in fields, "index_id" in fields,
                  stats["config"].get("buy_price_basis") in {"next_day_open", "signal_day_close"},
                  set(trades["quadrants"]) == set(quadrants) == set(stats["quadrants"])]
        for q, modes in quadrants.items():
            checks.append(set(trades["quadrants"][q]) == set(modes))
            for mode, rows in modes.items():
                checks.append(trades["quadrants"][q][mode] == [[r.get(f, "") for f in fields] for r in rows])
                all_stats = stats["quadrants"][q]["periods"].get("all", {}).get(mode)
                checks.append(all_stats is not None and type(all_stats.get("n")) is int and all_stats["n"] == len(rows))
        _validation(checks)
    except Exception as exc:
        current.errors[:] = [type(exc).__name__]
        _metadata_failure(exc)


def validate_run_proof(body):
    """Witness local current-run proof publication, not remote publication."""
    current = _ACTIVE.get()
    if current:
        try:
            current.record("export_config", {"manifest_version": body["version"]}, config=True)
            checks = [body["version"] == 1, bool(body["run_id"]), bool(body["outputs"])]
            for name, identity in body["outputs"].items():
                valid = (isinstance(identity, dict) and type(identity.get("size")) is int
                         and identity["size"] >= 0 and bool(re.fullmatch(r"[0-9a-f]{64}", identity.get("sha256", ""))))
                checks.append(valid)
                if valid:
                    fact = dict(identity, object_id=name, quality="strong", identity_kind="current_run_byte_proof",
                                observed_at=utc_now(), session_date=current.session_date)
                    current.inputs.append(dict(fact))
                    current.outputs.append(dict(fact))
            _validation(checks)
        except Exception as exc:
            current.errors[:] = [type(exc).__name__]
            _metadata_failure(exc)


def verify_local_backtest_consumer(*, data_root, producer_receipt, publication_receipt,
                                   artifact_paths, session_date):
    """Explicit isolated reader witness. NEVER a browser/R2 delivery witness.

    Reads exact named files, requires matching producer and local proof digests,
    validates selected basis and per-mode columnar row counts. The approved
    collector policy must explicitly select consumer_scope=isolated_local_reader.
    No remote operations, main entrypoints, database or notifications.
    """
    if not evidence_enabled():
        return {"status": "disabled"}
    current = None
    try:
        current = _Capture(data_root, "consumer", "backtest_publish_consume",
                           "backtest_parts_and_consumer", verify_local_backtest_consumer)
        current.session_date = session_date
        producer = read_receipt(producer_receipt)
        publication = read_receipt(publication_receipt)
        checks = [producer["stage"] == "backtest", publication["stage"] == "publish"]
        batch = f"backtest_publish_consume:{session_date}"
        for source in (producer, publication):
            source_known = source["evidence_quality"] == "strong"
            checks.extend([source["stage_status"] == "success" if source_known else None, True if source_known else None,
                           source["session_date"] == session_date, source["batch_id"] == batch])
        expected_names = {"signal_kelly_backtest.json", "signal_kelly_trades.json"}
        checks.append(set(artifact_paths) == expected_names)
        decoded = {}
        for name in sorted(expected_names):
            fd = os.open(artifact_paths[name], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("consumer input must be regular file")
                payload = stream.read(MAX_HASH_BYTES + 1)
            identity = identity_for_bytes(name, payload, session_date=session_date)
            current.inputs.append(dict(identity))
            current.outputs.append(dict(identity))
            for source in (producer, publication):
                matching = [v for v in source["outputs"] if v.get("object_id") == name]
                checks.append(len(matching) == 1 and matching[0].get("sha256") == identity["sha256"])
            decoded[name] = json.loads(payload)
        stats, trades = decoded["signal_kelly_backtest.json"], decoded["signal_kelly_trades.json"]
        current.record("consumer_config", stats["config"], config=True)
        fields = trades["fields"]
        checks.extend([stats["config"].get("buy_price_basis") == "next_day_open",
                       isinstance(fields, list), "signal_date" in fields, "index_id" in fields,
                       set(stats["quadrants"]) == set(trades["quadrants"])])
        for q, modes in trades["quadrants"].items():
            for mode, rows in modes.items():
                checks.append(all(isinstance(r, list) and len(r) == len(fields) for r in rows))
                checks.append(stats["quadrants"][q]["periods"]["all"][mode]["n"] == len(rows))
        completed = utc_now()
        counts = {"inventory_complete": 1, "expected": len(checks), "validated": sum(v is True for v in checks),
                  "failed": sum(v is False for v in checks), "unknown": sum(v is None for v in checks)}
        code_known = bool(re.fullmatch(r"[0-9a-f]{40}", current.code["sha"]))
        status = "unknown" if counts["unknown"] else "success" if all(checks) else "failure"
        witness = {"status": status,
                   "output_sha256": current.outputs[0]["sha256"], "session_date": session_date,
                   "batch_id": batch, "consumer_scope": "isolated_local_reader",
                   "producer_receipt_id": producer["receipt_id"],
                   "publication_receipt_id": publication["receipt_id"]}
        return emit_receipt(data_root=data_root, stage="consumer", chain_id=current.chain_id,
                            object_id=current.object_id, session_date=session_date,
                            stage_status=status if code_known else "unknown",
                            reason="isolated_local_reader_validated" if all(checks) else "consumer_validation_failed",
                            inputs=current.inputs, outputs=current.outputs, counts=counts,
                            code_identity=current.code, config_identity=current.config,
                            consumer_witness=witness if code_known else {"status": "unknown", "reason": "code_unbound"},
                            producer_time={"started_at": current.started, "completed_at": completed},
                            evidence_quality="strong" if code_known else "unknown")
    except Exception as exc:
        _metadata_failure(exc)
        if current:
            current.errors[:] = [type(exc).__name__]
            return _finish_safely(current, "unknown", "consumer_unverified")
        return {"status": "metadata_failure", "reason": type(exc).__name__}


def _finish_safely(current, status, reason):
    try:
        return current.finish(status, reason)
    except Exception as exc:
        return _metadata_failure(exc)


def capture_loaded(object_id, value, **metadata):
    """Return the identical value; disabled path never examines it."""
    current = _ACTIVE.get()
    return current.record(object_id, value, **metadata) if current else value


def capture_sql_rows(conn, object_id, rows, *, query_scope):
    """Capture rows the business caller already fetched; no second data query."""
    current = _ACTIVE.get()
    if current and not current.errors:
        try:
            main = capture_connection(conn)
            current.record(object_id, rows, query_scope=query_scope, resolved_path=main,
                           snapshot_scope="single_query_rows")
        except Exception as exc:
            current.errors[:] = [type(exc).__name__]
            _metadata_failure(exc)
    return rows


def capture_connection(conn):
    """Resolve the already-open connection; never query business rows again."""
    current = _ACTIVE.get()
    if current and not current.errors:
        try:
            dbs = conn.execute("PRAGMA database_list").fetchall()
            main = next((r[2] for r in dbs if r[1] == "main"), "unknown")
            if main != "unknown" and Path(main).parent.name == "data":
                root = Path(main).parent.parent
                if Path(current.data_root) != root:
                    current.data_root = root
                    current.code = loaded_code_identity(current.fn, root)
            return main
        except Exception as exc:
            current.errors[:] = [type(exc).__name__]
            _metadata_failure(exc)
    return "unknown"


def capture_event(kind, **metadata):
    current = _ACTIVE.get()
    if current and not current.errors:
        try:
            if len(current.events) >= MAX_EVENTS:
                raise ValueError("event capture limit")
            current.events.append(dict(metadata, kind=kind, observed_at=utc_now()))
        except Exception as exc:
            if not current.errors:
                _metadata_failure(exc)
            current.errors[:] = [type(exc).__name__]


def capture_signal_visibility(signals, before, audit_available):
    """Observe current/changed signal keys now; never backdate first arrival.

    before is the existing business audit snapshot, not a newly read DB file.
    Absent audit cannot prove historical first visibility.
    """
    current = _ACTIVE.get()
    if current:
        try:
            session = current.session_date.replace("-", "")
            for row in signals:
                if current.errors:
                    break
                key = tuple(row[:3])
                if key[0] == session or (audit_available and key not in before):
                    capture_event("signal_visible", key="|".join(key),
                                  first_visible_at="unknown", arrival_at="unknown",
                                  historical_audit_available=audit_available,
                                  reason_sha256=hashlib.sha256(str(row[3]).encode()).hexdigest())
        except Exception as exc:
            current.errors[:] = [type(exc).__name__]
            _metadata_failure(exc)


def capture_identity(*, session_date=None, attempt_id=None, data_root=None):
    current = _ACTIVE.get()
    if current:
        try:
            if session_date is not None:
                current.session_date = datetime.strptime(str(session_date).replace("-", ""), "%Y%m%d").strftime("%Y-%m-%d")
            if attempt_id:
                current.attempt_id = attempt_id
            if data_root is not None:
                current.data_root = data_root
        except Exception as exc:
            current.errors[:] = [type(exc).__name__]
            _metadata_failure(exc)


def capture_write(writer, path, value, *args, **kwargs):
    """Call the existing writer unchanged; capture its actual serialized value.

    No read-after-write race, no writer replacement or permission changes.
    Serialization mirror failures affect metadata only, never business behavior.
    """
    result = writer(path, value, *args, **kwargs)
    if _ACTIVE.get():
        try:
            if isinstance(value, str):
                payload = value.encode("utf-8")
            else:
                payload = json.dumps(value, **{k: v for k, v in kwargs.items() if k != "mode"},
                                     **({} if "ensure_ascii" in kwargs else {"ensure_ascii": False})).encode("utf-8")
            capture_loaded(Path(path).name, payload, output=True, raw=True, resolved_path=str(Path(path).absolute()))
        except Exception as exc:
            _ACTIVE.get().errors[:] = [type(exc).__name__]
            _metadata_failure(exc)
    return result


def evidence_stage(*, data_root, stage, chain_id, object_id, return_output=False, exit_status=False):
    """Optional instrumentation boundary; business result and exceptions pass through."""
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if not evidence_enabled():
                return fn(*args, **kwargs)
            try:
                current = _Capture(data_root(), stage, chain_id, object_id, fn)
                previous = _ACTIVE.get()
                if previous:
                    current.session_date = previous.session_date
                    current.attempt_id = previous.attempt_id
                    current.config = previous.config
                    current.inputs.extend(previous.inputs)
            except Exception as exc:
                _metadata_failure(exc)
                return fn(*args, **kwargs)
            token = _ACTIVE.set(current)
            parent = token.old_value
            try:
                result = fn(*args, **kwargs)
                if return_output:
                    current.record(object_id, result, output=True)
                status = "failure" if exit_status and result not in (None, 0) else "success"
                _finish_safely(current, status, "stage_completed_consumer_unverified")
                return result
            except BaseException as exc:
                # SystemExit(0), interrupts and guard skips cannot certify success.
                _finish_safely(current, "unknown" if isinstance(exc, (SystemExit, KeyboardInterrupt)) else "failure",
                               type(exc).__name__)
                raise
            finally:
                _ACTIVE.reset(token)
                if isinstance(parent, _Capture):
                    for identity in current.inputs + current.outputs:
                        if len(parent.inputs) < MAX_IDENTITIES and not any(v["object_id"] == identity["object_id"] for v in parent.inputs):
                            parent.inputs.append(identity)
                    parent.errors.extend(current.errors)
                    if current.validation:
                        parent.validation = current.validation
                        parent.config = current.config
        return wrapped
    return decorate


def _cli_receipt(data_root, path, expected_sha256):
    """Explicit private partition + caller's out-of-band content pin, no glob."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("invalid receipt SHA256")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("receipt must be a regular 0600 file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("receipt content pin mismatch")
    body = _validate(json.loads(raw))
    directory = receipt_root(data_root)
    for part in (None, "receipts", body["session_date"], body["chain_id"]):
        if part is not None:
            directory = directory / part
        mode = directory.lstat().st_mode
        if not stat.S_ISDIR(mode) or stat.S_IMODE(mode) != 0o700:
            raise ValueError("receipt partition must be a real 0700 directory")
    if path != directory / (body["receipt_id"] + ".json"):
        raise ValueError("receipt must be the exact named private partition fact")
    return body


def cli(argv=None):
    """Explicit local reader and read-only binding draft; never a business entrypoint."""
    import argparse

    def absolute(value):
        path = Path(value)
        if not path.is_absolute():
            raise argparse.ArgumentTypeError("an explicit absolute path is required")
        return Path(os.path.abspath(path))

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify-local-backtest", help="Witness exactly two named NDO artifacts locally")
    verify.add_argument("--data-root", type=absolute, required=True)
    verify.add_argument("--session-date", required=True, help="ISO date YYYY-MM-DD; no inference from latest/mtime")
    verify.add_argument("--producer-receipt", type=absolute, required=True)
    verify.add_argument("--producer-sha256", required=True)
    verify.add_argument("--publication-receipt", type=absolute, required=True)
    verify.add_argument("--publication-sha256", required=True)
    verify.add_argument("--stats", type=absolute, required=True, help="Exact signal_kelly_backtest.json")
    verify.add_argument("--trades", type=absolute, required=True, help="Exact signal_kelly_trades.json")
    candidate = commands.add_parser("binding-candidate", help="Read pinned receipt module digests; never approve/install a binding")
    candidate.add_argument("--data-root", type=absolute, required=True)
    candidate.add_argument("--code-sha", required=True, help="Externally reviewed commit; not inferred or authenticated here")
    candidate.add_argument("--receipt", nargs=2, action="append", required=True, metavar=("ABSOLUTE_PATH", "SHA256"))
    args = parser.parse_args(argv)
    if not evidence_enabled():
        print(json.dumps({"status": "disabled"}, separators=(",", ":")))
        return 0
    try:
        if args.command == "binding-candidate":
            if not re.fullmatch(r"[0-9a-f]{40}", args.code_sha) or len(args.receipt) > 128:
                raise ValueError("invalid binding candidate")
            sources, digests = [], set()
            for name, sha256 in args.receipt:
                body = _cli_receipt(args.data_root, absolute(name), sha256)
                code = body["code_identity"]
                module = code.get("module_sha256", "")
                if code.get("kind") != "loaded_python_module" or not re.fullmatch(r"[0-9a-f]{64}", module):
                    raise ValueError("receipt has no actual loaded module digest")
                digests.add(module)
                sources.append({"receipt_id": body["receipt_id"], "receipt_sha256": sha256,
                                "stage": body["stage"], "object_id": body["object_id"],
                                "module_sha256": module, "coverage": code.get("coverage", "unknown")})
            print(json.dumps({"schema": "trade-producer-identity-v1", "reviewed": False,
                              "code_sha": args.code_sha, "loaded_module_sha256": sorted(digests),
                              "source_receipts": sources}, ensure_ascii=False, sort_keys=True))
            return 0
        datetime.strptime(args.session_date, "%Y-%m-%d")
        if args.stats.name != "signal_kelly_backtest.json" or args.trades.name != "signal_kelly_trades.json":
            raise ValueError("only the two explicitly named NDO artifacts are supported")
        for path, pin, stage in ((args.producer_receipt, args.producer_sha256, "backtest"),
                                 (args.publication_receipt, args.publication_sha256, "publish")):
            source = _cli_receipt(args.data_root, path, pin)
            if (source["stage"] != stage or source["chain_id"] != "backtest_publish_consume"
                    or source["session_date"] != args.session_date
                    or source["batch_id"] != "backtest_publish_consume:" + args.session_date):
                raise ValueError("explicit receipt stage/session/batch mismatch")
        result = verify_local_backtest_consumer(data_root=args.data_root,
                     producer_receipt=args.producer_receipt, publication_receipt=args.publication_receipt,
                     artifact_paths={"signal_kelly_backtest.json": args.stats, "signal_kelly_trades.json": args.trades},
                     session_date=args.session_date)
        if result.get("status") not in {"written", "idempotent"}:
            print(json.dumps(result, sort_keys=True))
            return 2
        path = (receipt_root(args.data_root) / "receipts" / args.session_date /
                "backtest_publish_consume" / (result["receipt_id"] + ".json"))
        receipt = _cli_receipt(args.data_root, path, result["receipt_sha256"])
        result.update(stage_status=receipt["stage_status"], evidence_quality=receipt["evidence_quality"],
                      consumer_scope=receipt["consumer_witness"].get("consumer_scope", "unknown"))
        print(json.dumps(result, sort_keys=True))
        if receipt["stage_status"] == "success" and receipt["evidence_quality"] == "strong":
            return 0
        return 1 if receipt["stage_status"] == "failure" else 2
    except Exception as exc:
        _metadata_failure(exc)
        print(json.dumps({"status": "unknown", "reason": type(exc).__name__}, sort_keys=True))
        return 2


if __name__ == "__main__":
    # A script and a -m invocation use the same canonical helper namespace as
    # source imports. Do not change module identity merely by choosing the CLI.
    sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
    from scripts.delivery_evidence import cli as _canonical_cli
    raise SystemExit(_canonical_cli())
