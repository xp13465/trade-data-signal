"""Bind a DB restore to the private SQLite snapshot actually uploaded in one run.

The local receipt is a selector, not authority: its digest must match signed S3
object metadata, and downloaded gzip/raw bytes must match its SHA-256 hashes.
No credentials, SQL values, or new R2 objects are recorded here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

TABLES = {
    "sentiment": ["score_daily", "daily_metric", "signal_daily", "index_daily",
                  "industry_width_daily", "futures_position", "futures_accuracy", "collect_log"],
    "etf_national_team": ["etf_daily", "etf_signal", "etf_holder_quarterly", "national_team_holders"],
    "stock_daily": ["baostock_daily_raw", "fapi_daily_raw", "mootdx_daily_raw"],
    "public_fund": ["fund_daily_nav", "fund_purchase_status", "fund_performance", "fund_rating", "fund_basic"],
}


def fingerprint(path):
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    return {"sha256": h.hexdigest(), "size": size}


def digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, sort_keys=True, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def snapshot_counts(path, name):
    con = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError(f"{name}: snapshot integrity failed")
        existing = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] if t in existing else None
                for t in TABLES[name]}
    finally:
        con.close()


def metadata(entry):
    return {"x-amz-meta-backup-run-id": entry["run_id"],
            "x-amz-meta-backup-source-sha256": digest(entry)}


def select_entry(path, run_id, name, bucket):
    if not run_id or not path:
        raise ValueError("unknown/not_verified: missing explicit run/source proof")
    receipt = json.loads(Path(path).read_text())
    # Run completion is an aggregate result, not this object's provenance.
    # Only successful uploads get entries; each still needs remote/byte checks.
    if receipt.get("schema") != 1 or receipt.get("run_id") != run_id or type(receipt.get("complete")) is not bool:
        raise ValueError("unknown/not_verified: wrong run or malformed upload receipt")
    entry = receipt["objects"][name]
    if entry["run_id"] != run_id or entry["bucket"] != bucket or entry["name"] != name:
        raise ValueError("unknown/not_verified: source identity mismatch")
    if not re.fullmatch(r"backup/" + re.escape(name) + r"_\d{8}\.db\.gz", entry["key"]):
        raise ValueError("unknown/not_verified: unexpected source key")
    if set(entry["tables"]) != set(TABLES[name]):
        raise ValueError("unknown/not_verified: incomplete source table proof")
    return entry


def check_restored(path, entry):
    if fingerprint(path) != entry["raw"]:
        raise ValueError("restored SQLite fingerprint differs from uploaded snapshot")
    counts = snapshot_counts(path, entry["name"])
    if counts != entry["tables"]:
        raise ValueError("restored table counts differ from uploaded snapshot")
    for table, count in counts.items():
        if count is None or count <= 0:
            raise ValueError(f"{entry['name']}: {table} missing/empty")


def restore_bound(ur, receipt, run_id, name, out_dir, downloader):
    """Reuse the existing bounded-memory Range downloader; never select latest."""
    entry = select_entry(receipt, run_id, name, ur.BACKUP_BUCKET)

    def head():
        status, _body, headers = ur.s3_request("HEAD", entry["key"], bucket=entry["bucket"], with_headers=True)
        headers = {k.lower(): str(v) for k, v in headers.items()}
        if status != 200 or any(headers.get(k) != v for k, v in metadata(entry).items()):
            raise ValueError("unknown/not_verified: R2 object run/source metadata mismatch")
        if int(headers.get("content-length", -1)) != entry["gzip"]["size"]:
            raise ValueError("R2 object length mismatch")
        return headers.get("etag")

    before = head()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    gz = out_dir / Path(entry["key"]).name
    db = gz.with_suffix("")
    marker = Path(str(db) + ".source-verified.json")
    marker.unlink(missing_ok=True)
    import shutil
    if shutil.disk_usage(out_dir).free < entry["raw"]["size"] + entry["gzip"]["size"] + (64 << 20):
        raise OSError("source-bound restore: insufficient temporary space for raw+gzip+reserve")
    downloader(entry["key"], gz, entry["gzip"]["size"], threads=6)
    if fingerprint(gz) != entry["gzip"]:
        raise ValueError("downloaded gzip fingerprint mismatch")
    # Bound decompression to the expected raw length (also catches a forged gzip bomb).
    import gzip
    with gzip.open(gz, "rb") as src, db.open("wb") as dst:
        size = 0
        for chunk in iter(lambda: src.read(4 << 20), b""):
            size += len(chunk)
            if size > entry["raw"]["size"]:
                raise ValueError("decompressed SQLite exceeds source size")
            dst.write(chunk)
    check_restored(db, entry)
    if head() != before:
        raise ValueError("unknown/not_verified: R2 object changed during restore")
    atomic_json(marker, entry)
    gz.unlink()  # only this invocation's temporary download; never touch history
    return str(db)


def verified_entry(path, receipt, run_id, name, bucket):
    """Checker consumes only this invocation's successfully downloaded proof."""
    entry = select_entry(receipt, run_id, name, bucket)
    if json.loads(Path(str(path) + ".source-verified.json").read_text()) != entry:
        raise ValueError("unknown/not_verified: no matching restore identity proof")
    check_restored(path, entry)
    return entry


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True, choices=TABLES)
    p.add_argument("--out-dir", required=True)
    a = p.parse_args()
    import upload_r2 as ur
    spec = importlib.util.spec_from_file_location("bound_range_restore", Path(__file__).resolve().parents[1] / "docs/scripts/restore_r2_db_backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ur = ur
    try:
        result = restore_bound(ur, os.environ.get("VERIFY_BACKUP_SOURCE_PROOF"),
                               os.environ.get("VERIFY_BACKUP_RUN_ID"), a.name, a.out_dir, module.download)
    except Exception as exc:
        print(f"{a.name}: source-bound restore FAIL: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
