#!/usr/bin/env python3
"""Ownership leases for Codex external-review requests."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
CLAIMS_DIR = Path("/tmp/codex-reports/claims")
DEFAULT_LEASE_SECONDS = int(os.environ.get("CODEX_REVIEW_LEASE_SECONDS", "1800"))


def _validate_request_id(request_id: str) -> None:
    import re

    if not re.fullmatch(ID_PATTERN, request_id):
        raise ValueError(f"invalid request_id: {request_id!r}")


def claim_path(request_id: str) -> Path:
    _validate_request_id(request_id)
    return CLAIMS_DIR / f"{request_id}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _process_alive(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _is_active(payload: dict[str, Any] | None, now: float) -> bool:
    if not payload:
        return False
    expires_at = payload.get("expires_at")
    owner_pid = payload.get("owner_pid")
    worker_pid = payload.get("worker_pid", owner_pid)
    fresh = isinstance(expires_at, (int, float)) and now < float(expires_at)
    owner_or_worker_alive = _process_alive(owner_pid) or _process_alive(worker_pid)
    return (fresh and owner_or_worker_alive) or _process_alive(worker_pid)


def acquire(
    request_id: str,
    owner: str = "manual",
    owner_pid: int | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any] | None:
    """Atomically create a request lease, stealing only a dead/expired one."""

    _validate_request_id(request_id)
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    path = claim_path(request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        now = time.time()
        token = uuid.uuid4().hex
        payload = {
            "request_id": request_id,
            "token": token,
            "owner": owner,
            "owner_pid": owner_pid if owner_pid is not None else os.getpid(),
            "worker_pid": None,
            "acquired_at": now,
            "expires_at": now + lease_seconds,
        }
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            existing = _read_json(path)
            if _is_active(existing, now):
                return None
            stolen = path.with_name(f".{path.name}.stolen.{uuid.uuid4().hex}")
            try:
                path.replace(stolen)
                stolen.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            continue

        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        return payload
    raise RuntimeError(f"could not acquire lease after retries: {request_id}")


def renew(
    request_id: str,
    token: str,
    worker_pid: int | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any]:
    _validate_request_id(request_id)
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")

    path = claim_path(request_id)
    payload = _read_json(path)
    if not payload or payload.get("token") != token:
        raise RuntimeError(f"lease is not owned by this token: {request_id}")

    now = time.time()
    payload["expires_at"] = now + lease_seconds
    if worker_pid is not None:
        payload["worker_pid"] = worker_pid
    _atomic_write_json(path, payload)
    return payload


def release(request_id: str, token: str) -> bool:
    _validate_request_id(request_id)
    path = claim_path(request_id)
    payload = _read_json(path)
    if not payload or payload.get("token") != token:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


def status(request_id: str) -> dict[str, Any]:
    path = claim_path(request_id)
    payload = _read_json(path)
    active = _is_active(payload, time.time())
    result: dict[str, Any] = {
        "request_id": request_id,
        "state": "claimed" if active else "free",
        "claim_path": str(path),
    }
    if active and payload:
        result.update(
            {
                "owner": payload.get("owner"),
                "owner_pid": payload.get("owner_pid"),
                "worker_pid": payload.get("worker_pid"),
                "expires_at": payload.get("expires_at"),
            }
        )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire_parser = subparsers.add_parser("acquire")
    acquire_parser.add_argument("request_id")
    acquire_parser.add_argument("--owner", default="manual")
    acquire_parser.add_argument("--pid", type=int, default=None)
    acquire_parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)

    renew_parser = subparsers.add_parser("renew")
    renew_parser.add_argument("request_id")
    renew_parser.add_argument("--token", required=True)
    renew_parser.add_argument("--worker-pid", type=int, default=None)
    renew_parser.add_argument("--lease-seconds", type=int, default=DEFAULT_LEASE_SECONDS)

    release_parser = subparsers.add_parser("release")
    release_parser.add_argument("request_id")
    release_parser.add_argument("--token", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("request_id")
    status_parser.add_argument("--quiet", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "acquire":
            payload = acquire(args.request_id, args.owner, args.pid, args.lease_seconds)
            if payload is None:
                print(json.dumps({"state": "claimed"}), flush=True)
                return 10
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if args.command == "renew":
            payload = renew(
                args.request_id,
                args.token,
                args.worker_pid,
                args.lease_seconds,
            )
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if args.command == "release":
            released = release(args.request_id, args.token)
            print(json.dumps({"released": released}), flush=True)
            return 0 if released else 1

        payload = status(args.request_id)
        if not args.quiet:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
        return 10 if payload["state"] == "claimed" else 0
    except (OSError, RuntimeError, ValueError) as error:
        print(str(error), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
