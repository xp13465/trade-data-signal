"""Real temporary SQLite + filesystem S3 substitute; no production IO/notifications."""
import datetime
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import backup_source_proof as proof
import upload_r2 as ur


# This same transport runs in-process for the actual uploader and in fresh CLI
# processes for verify_backup.sh. Only temporary local objects are accessible.
TRANSPORT = '''import os, json, hashlib
from pathlib import Path
BACKUP_BUCKET = "test-private-backups"
def s3_request(method, key, payload=b"", bucket=None, with_headers=False, extra_headers=None, **kw):
    assert bucket == BACKUP_BUCKET
    if os.environ.get("FIXTURE_READ_ONLY") == "1":
        assert method in ("GET", "HEAD"), "verifier must never upload/mutate backups"
    root = Path(os.environ["FIXTURE_S3"])
    obj = root / key
    meta = Path(str(obj) + ".headers.json")
    if method == "PUT":
        obj.parent.mkdir(parents=True, exist_ok=True)
        obj.write_bytes(payload)
        headers = dict(extra_headers or {})
        headers.update({"Content-Length": str(len(payload)), "ETag": hashlib.sha256(payload).hexdigest()})
        meta.write_text(json.dumps(headers))
        result = 200, b"", headers
    elif not obj.exists():
        result = 404, b"", {}
    elif method == "HEAD":
        result = 200, b"", json.loads(meta.read_text())
    elif method == "GET":
        data = obj.read_bytes()
        if extra_headers and "range" in extra_headers:
            start, end = map(int, extra_headers["range"].split("=")[1].split("-"))
            result = 206, data[start:end+1], {}
        else:
            result = 200, data, {}
    else:
        raise AssertionError("unexpected local S3 operation " + method)
    return result if with_headers else result[:2]
'''


def mkdb(path, name, signal_rows=150):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as c:
        for table in proof.TABLES[name]:
            c.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, value TEXT)')
            c.executemany(f'INSERT INTO "{table}" VALUES (?, ?)',
                          ((i, "before") for i in range(signal_rows if table == "signal_daily" else 3)))


@pytest.fixture
def case(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    for name in proof.TABLES:
        mkdb(repo / "data" / (name + ".db"), name)
    (repo / "scripts/lib").mkdir(parents=True)
    (repo / "docs/scripts").mkdir(parents=True)
    (repo / ".venv/bin").mkdir(parents=True)
    (repo / ".venv/bin/python").symlink_to(sys.executable)
    for file in ["backup_source_proof.py", "verify_backup.sh", "lib/repo_paths.sh"]:
        shutil.copyfile(ROOT / "scripts" / file, repo / "scripts" / file)
    shutil.copyfile(ROOT / "docs/scripts/restore_r2_db_backup.py", repo / "docs/scripts/restore_r2_db_backup.py")
    (repo / "scripts/upload_r2.py").write_text(TRANSPORT)
    (repo / "scripts/notify.py").write_text('import os,sys\nfrom pathlib import Path\nPath(os.environ["FIXTURE_NOTIFY"]).write_text("\\n".join(sys.argv))\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "sleep": "#!/bin/sh\nexit 0\n",
        "date": '#!/bin/sh\nif [ "$1" = "+%u" ]; then echo "${FIXTURE_DOW:-1}"; else /bin/date "$@"; fi\n',
        "df": '#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted"\necho "/fixture 99999999 0 99999999 0% /"\n',
    }.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    env = {"REPO": str(repo), "GIT_REPO": str(repo), "FIXTURE_S3": str(tmp_path / "s3"),
           "FIXTURE_NOTIFY": str(tmp_path / "notify"), "VERIFY_NOTIFY_DRY_RUN": "1",
           "R2_DB_BACKUP_PROOF": str(repo / "data/logs/run-source.json"),
           "R2_DB_BACKUP_RUN_ID": "fixture-run-a", "VERIFY_PUBLIC_FUND": "1",
           "R2_DB_BACKUP_REQUIRE_PUBLIC_FUND": "1",
           "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
    env.update(VERIFY_BACKUP_SOURCE_PROOF=env["R2_DB_BACKUP_PROOF"], VERIFY_BACKUP_RUN_ID=env["R2_DB_BACKUP_RUN_ID"])
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    module = type(sys)("fixture_transport")
    exec(TRANSPORT, module.__dict__)
    monkeypatch.setattr(ur, "BACKUP_BUCKET", module.BACKUP_BUCKET)
    monkeypatch.setattr(ur, "s3_request", module.s3_request)
    monkeypatch.setattr(ur, "s3_head", lambda key, **kw: (200, "fixture", str((tmp_path / "s3" / key).stat().st_size)))
    for method in ["_maybe_upload_weekly", "_maybe_upload_monthly", "_maybe_upload_weekly_file",
                   "_maybe_upload_monthly_file", "_prune_r2_backup"]:
        monkeypatch.setattr(ur, method, lambda *a, **kw: None)
    return repo, tmp_path


def upload(case):
    ur.cmd_upload_db()
    return json.loads(Path(os.environ["R2_DB_BACKUP_PROOF"]).read_text())


def verify(case, **env):
    repo, _ = case
    return subprocess.run(["bash", str(repo / "scripts/verify_backup.sh")],
                          env={**os.environ, "FIXTURE_READ_ONLY": "1", **env}, text=True, capture_output=True, timeout=25)


def test_real_upload_restore_and_live_minus_116(case):
    receipt = upload(case)
    assert receipt["complete"] and set(receipt["objects"]) == set(proof.TABLES)
    receipt_path = Path(os.environ["R2_DB_BACKUP_PROOF"])
    assert receipt_path.stat().st_size < 16 << 10
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(case[0] / "data/sentiment.db") as c:
        c.execute("DELETE FROM signal_daily WHERE id < 116")
    r = verify(case)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '"delta": -116' in r.stdout and 'live_drift=-116' in r.stdout
    assert not (case[1] / "notify").exists()


@pytest.mark.parametrize("attack", ["truncate", "wrong-object", "same-length", "covered-run", "receipt-tamper", "wrong-run", "no-proof"])
def test_object_and_proof_attacks_fail(case, attack):
    receipt = upload(case)
    entry = receipt["objects"]["sentiment"]
    obj = case[1] / "s3" / entry["key"]
    overrides = {}
    if attack == "truncate":
        obj.write_bytes(obj.read_bytes()[:-10])
    elif attack == "wrong-object":
        obj.write_bytes((case[1] / "s3" / receipt["objects"]["stock_daily"]["key"]).read_bytes())
    elif attack == "same-length":
        data = bytearray(obj.read_bytes()); data[len(data)//2] ^= 1; obj.write_bytes(data)
    elif attack == "covered-run":
        headers = Path(str(obj) + ".headers.json")
        h = json.loads(headers.read_text()); h["x-amz-meta-backup-run-id"] = "fixture-run-b"
        headers.write_text(json.dumps(h))  # even identical bytes/length cannot impersonate this run
    elif attack == "receipt-tamper":
        entry["tables"]["signal_daily"] += 1
        proof.atomic_json(os.environ["R2_DB_BACKUP_PROOF"], receipt)
    elif attack == "wrong-run":
        overrides["VERIFY_BACKUP_RUN_ID"] = "wrong-run"
    else:
        Path(os.environ["R2_DB_BACKUP_PROOF"]).unlink()
    r = verify(case, **overrides)
    assert r.returncode == 1, r.stdout + r.stderr
    assert (case[1] / "notify").exists()


@pytest.mark.parametrize("damage", ["empty", "missing", "corrupt"])
def test_matching_source_cannot_hide_bad_backup(case, damage):
    src = case[0] / "data/sentiment.db"
    if damage == "corrupt":
        src.write_bytes(b"not SQLite")
        with pytest.raises(sqlite3.DatabaseError):
            upload(case)
        assert not json.loads(Path(os.environ["R2_DB_BACKUP_PROOF"]).read_text())["complete"]
        return
    with sqlite3.connect(src) as c:
        c.execute("DELETE FROM signal_daily" if damage == "empty" else "DROP TABLE signal_daily")
    upload(case)
    assert verify(case).returncode == 1


@pytest.mark.parametrize("damage", ["empty-live", "missing-live", "other-table-drop"])
def test_real_live_failures_still_alert(case, damage):
    upload(case)
    with sqlite3.connect(case[0] / "data/sentiment.db") as c:
        c.execute({"empty-live": "DELETE FROM signal_daily", "missing-live": "DROP TABLE signal_daily",
                   "other-table-drop": "DELETE FROM daily_metric WHERE id=0"}[damage])
    r = verify(case)
    assert r.returncode == 1 and (case[1] / "notify").exists()


def test_non_sunday_skip_healthy(case):
    upload(case)
    r = verify(case, VERIFY_PUBLIC_FUND="auto", FIXTURE_DOW="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP(周频未到:非周日)" in r.stdout


def test_wal_commits_and_live_writes_during_upload(case, monkeypatch):
    src = sqlite3.connect(case[0] / "data/sentiment.db")
    src.execute("PRAGMA journal_mode=WAL")
    src.execute("PRAGMA wal_autocheckpoint=0")
    src.execute("INSERT INTO signal_daily VALUES (9999, 'in WAL')")
    src.commit()
    real_put = ur.s3_request
    def write_after_capture(method, key, *a, **kw):
        if method == "PUT" and "sentiment_" in key:
            src.execute("DELETE FROM signal_daily WHERE id < 116"); src.commit()
        return real_put(method, key, *a, **kw)
    monkeypatch.setattr(ur, "s3_request", write_after_capture)
    try:
        rec = upload(case)
        assert rec["objects"]["sentiment"]["tables"]["signal_daily"] == 151
        r = verify(case)
        assert r.returncode == 0 and '"delta": -116' in r.stdout, r.stdout + r.stderr
    finally:
        src.close()


@pytest.mark.parametrize("rows,live", [(72108,71992), (72139,72032), (72171,72058)])
def test_unbound_historical_counts_never_turn_green(case, rows, live):
    # Execute the actual checker against physical DB files without a source marker.
    repo, tmp = case
    bdb = tmp / ("sentiment_" + datetime.date.today().strftime("%Y%m%d") + ".db")
    mkdb(bdb, "sentiment", rows)
    with sqlite3.connect(repo / "data/sentiment.db") as c:
        c.execute("DELETE FROM signal_daily")
        c.executemany("INSERT INTO signal_daily VALUES (?, 'live')", ((i,) for i in range(live)))
    script = (ROOT / "scripts/verify_backup.sh").read_text()
    block = script.split("VERIFY_REPORT=$(", 1)[1].split("<<'PYEOF'\n", 1)[1].split("\nPYEOF", 1)[0]
    r = subprocess.run([sys.executable, "-", str(bdb), "", "", "", str(repo / "data"), "public_fund=SKIP(周频未到:非周日)"],
                       input=block, text=True, capture_output=True, timeout=15)
    assert "VERIFY_OK=0" in r.stdout and "unknown/not_verified" in r.stdout


def test_public_fund_bound_drill_does_not_trust_skip_ledger(case):
    upload(case)
    # Source stat is unchanged and HEAD length matches, but the new drill still
    # uploads a new owned snapshot so an old ledger cannot fabricate this run.
    os.environ["R2_DB_BACKUP_RUN_ID"] = "fixture-run-b"
    os.environ["VERIFY_BACKUP_RUN_ID"] = "fixture-run-b"
    rec = upload(case)
    assert rec["objects"]["public_fund"]["run_id"] == "fixture-run-b"
    assert verify(case).returncode == 0


def test_file_multipart_metadata_reaches_initiate(case, monkeypatch):
    calls = []
    parts = {}
    def transport(method, key, payload=b"", query="", with_headers=False, **kw):
        calls.append((method, query, kw.get("extra_headers")))
        if query == "uploads=":
            return 200, b"<UploadId>fixture</UploadId>"
        if method == "PUT":
            parts[query] = payload
            return 200, b"", {"ETag": "part"}
        return 200, b"<CompleteMultipartUploadResult/>"
    monkeypatch.setattr(ur, "s3_request", transport)
    monkeypatch.setattr(ur, "_MULTIPART_THRESHOLD", 1)
    f = case[1] / "parts"; f.write_bytes(b"source-bytes")
    meta = {"x-amz-meta-backup-run-id": "test"}
    assert ur._upload_file_to_key("backup/test", f, "application/gzip", bucket=ur.BACKUP_BUCKET, extra_headers=meta)[0] == 200
    assert calls[0] == ("POST", "uploads=", meta)
    assert b"".join(parts.values()) == f.read_bytes()


def test_same_key_uploaded_by_another_run_cannot_revalidate_old_receipt(case, monkeypatch):
    old = upload(case)
    old_path = case[1] / "old-source.json"
    proof.atomic_json(old_path, old)
    monkeypatch.setenv("R2_DB_BACKUP_RUN_ID", "fixture-run-b")
    upload(case)  # a real successful overwrite through the actual uploader
    r = verify(case, VERIFY_BACKUP_SOURCE_PROOF=str(old_path), VERIFY_BACKUP_RUN_ID="fixture-run-a")
    assert r.returncode == 1 and (case[1] / "notify").exists()


def test_incomplete_upload_receipt_cannot_reuse_old_success(case, monkeypatch):
    upload(case)
    real = ur.s3_request
    def fail_stock(method, key, *a, **kw):
        if method == "PUT" and "stock_daily_" in key:
            return 500, b"fixture failure"
        return real(method, key, *a, **kw)
    monkeypatch.setattr(ur, "s3_request", fail_stock)
    with pytest.raises(SystemExit):
        upload(case)
    receipt = json.loads(Path(os.environ["R2_DB_BACKUP_PROOF"]).read_text())
    assert receipt["complete"] is False and "stock_daily" not in receipt["objects"]
    assert verify(case).returncode == 1


@pytest.mark.parametrize("local_bad,upload_rc,verify_rc", [(False,0,1), (False,1,0), (True,0,0)])
def test_parent_local_rc_stays_separate(case, monkeypatch, local_bad, upload_rc, verify_rc):
    repo, _ = case
    shutil.copyfile(ROOT / "scripts/backup_db.sh", repo / "scripts/backup_db.sh")
    if local_bad:
        (repo / "data/sentiment.db").write_bytes(b"corrupt fixture")
    (repo / "scripts/upload_r2.py").write_text(
        "import os,sys\nassert os.environ['R2_DB_BACKUP_RUN_ID']\n"
        "assert os.environ['R2_DB_BACKUP_PROOF']\nsys.exit(" + str(upload_rc) + ")\n")
    (repo / "scripts/verify_backup.sh").write_text(
        '#!/bin/sh\ntest -n "$VERIFY_BACKUP_RUN_ID" || exit 90\n'
        'test -n "$VERIFY_BACKUP_SOURCE_PROOF" || exit 91\nexit ' + str(verify_rc) + '\n')
    r = subprocess.run(["bash", str(repo / "scripts/backup_db.sh")],
                       text=True, capture_output=True, timeout=20)
    assert r.returncode == int(local_bad), r.stdout + r.stderr
    assert f"local_rc={int(local_bad)} upload_rc={upload_rc} verify_rc={verify_rc}" in r.stdout


def test_same_size_valid_sqlite_content_change_is_detected(case):
    src = case[0] / "data/sentiment.db"
    entry = {"name": "sentiment"}
    gz = case[1] / "capture.gz"
    ur._sqlite_snapshot_to_gz(src, gz, source=entry)
    import gzip
    restored = case[1] / "restored.db"
    restored.write_bytes(gzip.decompress(gz.read_bytes()))
    before = restored.stat().st_size
    with sqlite3.connect(restored) as c:
        c.execute("UPDATE signal_daily SET value='after!' WHERE id=0")
    assert restored.stat().st_size == before
    assert proof.snapshot_counts(restored, "sentiment") == entry["tables"]
    with pytest.raises(ValueError, match="fingerprint"):
        proof.check_restored(restored, entry)


def test_object_changes_during_range_download_fails_without_success_marker(case):
    rec = upload(case)
    entry = rec["objects"]["sentiment"]
    def downloaded_then_overwritten(key, gz, total, **kw):
        obj = case[1] / "s3" / key
        gz.write_bytes(obj.read_bytes())
        header_path = Path(str(obj) + ".headers.json")
        headers = json.loads(header_path.read_text())
        headers["x-amz-meta-backup-run-id"] = "another-run"
        header_path.write_text(json.dumps(headers))
    out = case[1] / "range-race"
    with pytest.raises(ValueError, match="metadata mismatch"):
        proof.restore_bound(ur, os.environ["R2_DB_BACKUP_PROOF"], rec["run_id"], "sentiment", out, downloaded_then_overwritten)
    assert not list(out.glob("*.source-verified.json"))


def test_real_small_sample_stream_and_disk_peak(case, monkeypatch):
    import tempfile
    src = case[0] / "data/sentiment.db"
    with sqlite3.connect(src) as c:
        c.executemany("UPDATE signal_daily SET value=? WHERE id=?", ((os.urandom(65536), i) for i in range(80)))
    monkeypatch.setattr(tempfile, "tempdir", str(case[1]))
    gz = case[1] / "sample.db.gz"
    peaks = []
    real_fingerprint = proof.fingerprint
    def observe(path):
        if Path(path) == gz:
            raw = next(case[1].glob("r2-db-snapshot-*/snapshot.db"))
            peaks.append({"raw": raw.stat().st_size, "gzip": gz.stat().st_size,
                          "peak_raw_plus_gzip": raw.stat().st_size + gz.stat().st_size})
        return real_fingerprint(path)
    monkeypatch.setattr(proof, "fingerprint", observe)
    real_copy = shutil.copyfileobj
    chunks = []
    def observe_copy(fin, fout, length):
        chunks.append(length)
        return real_copy(fin, fout, length)
    monkeypatch.setattr(shutil, "copyfileobj", observe_copy)
    # The capture path must not materialize the raw database with read_bytes().
    monkeypatch.setattr(Path, "read_bytes", lambda self: (_ for _ in ()).throw(AssertionError("whole file read")))
    entry = {"name": "sentiment"}
    ur._sqlite_snapshot_to_gz(src, gz, source=entry)
    assert chunks == [4 << 20] and peaks[0]["raw"] > 4 << 20
    assert peaks[0]["peak_raw_plus_gzip"] < entry["raw"]["size"] * 2.01
    assert not list(case[1].glob("r2-db-snapshot-*"))
    # This is a reproducible small-sample observation, not production capacity.
    print("RESOURCE_SAMPLE=" + json.dumps(peaks[0], sort_keys=True))


def test_small_snapshot_space_gate_includes_wal_and_prevents_upload(case, monkeypatch):
    original = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: original(p)._replace(free=1))
    calls = []
    monkeypatch.setattr(ur, "s3_request", lambda *a, **kw: calls.append(a))
    with pytest.raises(OSError, match="insufficient temporary space"):
        upload(case)
    assert calls == []
    assert not json.loads(Path(os.environ["R2_DB_BACKUP_PROOF"]).read_text())["complete"]


def test_restore_space_gate_prevents_range_allocation_and_preserves_history(case, monkeypatch):
    rec = upload(case)
    old_file = case[1] / "old-history.db"
    old_file.write_bytes(b"history must not be cleaned")
    original = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: original(p)._replace(free=1))
    def forbidden(*a, **kw):
        raise AssertionError("download must not start with insufficient space")
    out = case[1] / "no-space"
    with pytest.raises(OSError, match="insufficient temporary space"):
        proof.restore_bound(ur, os.environ["R2_DB_BACKUP_PROOF"], rec["run_id"], "sentiment", out, forbidden)
    assert old_file.read_bytes() == b"history must not be cleaned"
    assert not list(out.iterdir())


@pytest.mark.parametrize("dow,mode,skip,expected", [(1,"auto","0","0"), (7,"auto","0","1"), (1,"1","0","1"), (7,"0","0","0"), (7,"auto","1","0")])
def test_only_existing_parent_schedule_requests_fresh_pf(case, monkeypatch, dow, mode, skip, expected):
    repo, _ = case
    shutil.copyfile(ROOT / "scripts/backup_db.sh", repo / "scripts/backup_db.sh")
    (repo / "scripts/upload_r2.py").write_text("import os\nassert os.environ['R2_DB_BACKUP_REQUIRE_PUBLIC_FUND'] == " + repr(expected) + "\n")
    (repo / "scripts/verify_backup.sh").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("FIXTURE_DOW", str(dow))
    monkeypatch.setenv("VERIFY_PUBLIC_FUND", mode)
    monkeypatch.setenv("VERIFY_BACKUP_SKIP", skip)
    r = subprocess.run(["bash", str(repo / "scripts/backup_db.sh")], text=True, capture_output=True, timeout=20)
    assert r.returncode == 0 and "R2 上传失败" not in r.stdout, r.stdout + r.stderr
