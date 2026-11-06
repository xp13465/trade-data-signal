"""Portable, offline tests of real uploader functions; no uploader top-level import.

Run this file with pytest --noconftest to avoid the repository's .env shim.
Transport is in memory; primary uploads in incremental tests are explicit stubs.
"""

import ast
import datetime
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.request

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "upload_r2.py"
SOURCE_BUCKET = "preupload-source-test"
BACKUP_BUCKET = "preupload-backup-test"
KEY = "data/example.json"
OLD = b'{"version":"old"}'
NEW = b'{"version":"new"}'
FUNCTIONS = {
    "_backup_overwritten_keys", "_incremental_upload", "_norm_state_val",
    "_file_md5", "_read_checkpoint", "_route_bucket", "_infer_content_type",
}


def blocked(*args, **kwargs):
    raise RuntimeError("preupload test blocked external effect")


def load_functions(source=SOURCE, *, disable_reuse=False, guard=blocked):
    """Compile named, real source functions; never execute module-level .env code.

    disable_reuse is a behavioral negative control, not a historical source copy.
    It disables only the new reuse branch, without embedding an old revision.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in nodes} == FUNCTIONS
    if disable_reuse:
        branches = [node for node in ast.walk(ast.Module(body=nodes, type_ignores=[]))
                    if isinstance(node, ast.If)
                    and {"source_md5", "backup_md5"}.issubset(
                        {item.id for item in ast.walk(node.test)
                         if isinstance(item, ast.Name)})]
        assert len(branches) == 1
        branches[0].test = ast.copy_location(ast.Constant(value=False), branches[0].test)
    module = types.ModuleType("upload_r2")
    module.__dict__.update(
        Path=Path, datetime=datetime, hashlib=hashlib, http=http, json=json,
        os=os, re=re, sys=sys, threading=threading, time=time,
        BUCKET=SOURCE_BUCKET, BACKUP_BUCKET=BACKUP_BUCKET,
        BACKUP2_BUCKET=BACKUP_BUCKET, BACKUP2_HOST="backup.invalid",
        BACKUP2_AK="test", BACKUP2_SK="test", HOST="source.invalid", AK="test", SK="test",
        _CONTENT_TYPE_MAP={".json": "application/json", ".gz": "application/gzip"},
        _MULTIPART_THRESHOLD=100 * 1024 * 1024, _DRY_RUN=False,
        _NIGHT_FULL_DEFER_CHANNELS=frozenset(),
        _NIGHT_FULL_DEFER_FROM_HOUR=8, _NIGHT_FULL_DEFER_HOUR=23,
        _now=lambda: datetime.datetime(2026, 11, 6, 15),
        _phase_timing=lambda *args, **kwargs: None,
        _work_budget_check=lambda *args, **kwargs: None,
        _prune_pre_upload=lambda *args, **kwargs: None,
        s3_head=guard, s3_request=guard, _upload_multipart=guard,
        _upload_glob=guard, purge_cache=guard,
        ROOT=SOURCE.parent.parent,
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"),
         module.__dict__)
    return module


@pytest.fixture(autouse=True)
def no_external_effects(monkeypatch):
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("blocked")
        return blocked()

    for owner, name in [
        (socket.socket, "connect"), (socket.socket, "connect_ex"),
        (socket, "create_connection"), (socket, "getaddrinfo"),
        (http.client.HTTPConnection, "request"),
        (http.client.HTTPSConnection, "request"),
        (urllib.request, "urlopen"), (subprocess, "Popen"), (os, "system"),
    ]:
        monkeypatch.setattr(owner, name, deny)
    notification = types.ModuleType("notify")
    notification.send = notification.check_dedup = notification.update_dedup = deny
    monkeypatch.setitem(sys.modules, "notify", notification)
    # Positive controls happen before any source function in each test.
    for call in [
        lambda: socket.create_connection(("invalid.example", 443)),
        lambda: socket.getaddrinfo("invalid.example", 443),
        lambda: http.client.HTTPSConnection("invalid.example").request("GET", "/"),
        lambda: urllib.request.urlopen("https://invalid.example"),
        lambda: subprocess.Popen(["ssh", "invalid.example"]),
        lambda: notification.send("positive control"),
    ]:
        with pytest.raises(RuntimeError, match="blocked external effect"):
            call()
    assert len(attempts) == 6
    attempts.clear()
    yield deny, attempts
    assert attempts == [], "unexpected attempted external effect"


@pytest.fixture
def uploader(no_external_effects):
    deny, attempts = no_external_effects
    module = load_functions(guard=deny)
    # Real backup entry must fail before transport is explicitly installed.
    result = module._backup_overwritten_keys({KEY: "new"}, "positive control")
    assert result[:3] == (0, 0, 1)
    assert result[3][0]["stage"] == "HEAD源"
    assert attempts == ["blocked"]
    attempts.clear()
    return module


def md5(body):
    return hashlib.md5(body).hexdigest()


def object_record(body, *, etag=None):
    return {"body": body, "etag": md5(body) if etag is None else etag,
            "size": len(body)}


def backup_key(key=KEY, day=None):
    return f"pre-upload/{day or datetime.date.today():%Y%m%d}/{key}"


class MemoryTransport:
    """Bucket/key-scoped raw bytes; failures model real function return contracts."""

    def __init__(self, *, source=OLD):
        self.objects = {}
        if source is not None:
            self.objects[SOURCE_BUCKET, KEY] = object_record(source)
        self.calls = []
        self.fault = None

    def seed_backup(self, body=OLD, *, bucket=BACKUP_BUCKET, key=None):
        self.objects[bucket, key or backup_key()] = object_record(body)
        return self.objects[bucket, key or backup_key()]

    def head(self, key, bucket=None, keep_alive=False, with_len=False):
        self.calls.append(("HEAD", bucket, key, 0))
        if ((self.fault == "source_head" and bucket == SOURCE_BUCKET)
                or (self.fault == "backup_head" and bucket == BACKUP_BUCKET)):
            raise OSError("memory HEAD failure")
        obj = self.objects.get((bucket, key))
        result = ((404, None, None) if obj is None else
                  (200, obj["etag"], obj["size"]))
        return result if with_len else result[:2]

    def request(self, method, key, payload=b"", bucket=None, **kwargs):
        assert bucket in {SOURCE_BUCKET, BACKUP_BUCKET}
        if method == "GET":
            assert bucket == SOURCE_BUCKET
            body = self.objects[bucket, key]["body"]
            if self.fault == "short_get":
                body = body[:-1]
            self.calls.append((method, bucket, key, len(body)))
            return (503 if self.fault == "get" else 200), body
        assert method == "PUT" and bucket == BACKUP_BUCKET
        assert key.startswith(f"pre-upload/{datetime.date.today():%Y%m%d}/")
        self.calls.append((method, bucket, key, len(payload)))
        if self.fault == "put":
            return 403, b"denied"
        if self.fault != "not_landed":
            body = b"x" * len(payload) if self.fault == "corrupt_target" else payload
            self.objects[bucket, key] = object_record(body)
        return 200, b""

    def multipart(self, key, payload, content_type, bucket=None):
        result = self.request("PUT", key, payload=payload, bucket=bucket)
        if (bucket, key) in self.objects:
            self.objects[bucket, key]["etag"] = "parts-not-full-md5-2"
        return result

    def install(self, module):
        module.s3_head = self.head
        module.s3_request = self.request
        module._upload_multipart = self.multipart

    def count(self, method):
        return sum(call[0] == method for call in self.calls)

    def backup(self, module, local_md5=None):
        self.install(module)
        return module._backup_overwritten_keys(
            {KEY: md5(NEW) if local_md5 is None else local_md5}, "offline")


def test_old_source_new_local_retry_restores_bytes(uploader):
    memory = MemoryTransport()
    assert memory.backup(uploader) == (1, 0, 0, [])
    assert memory.backup(uploader) == (0, 1, 0, [])
    assert memory.count("GET") == memory.count("PUT") == 1
    assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] == OLD


def test_reuse_disabled_current_withdrawal_control():
    results = []
    for disable in (True, False, True):
        module = load_functions(disable_reuse=disable)
        memory = MemoryTransport()
        memory.backup(module)
        memory.backup(module)
        results.append((memory.count("GET"), memory.count("PUT")))
        assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] == OLD
    assert results == [(2, 2), (1, 1), (2, 2)]


@pytest.mark.parametrize("wrong", ["hash", "size", "missing_size", "bucket", "date", "key"])
def test_backup_must_match_source_and_scope(uploader, wrong):
    memory = MemoryTransport()
    obj = memory.seed_backup(
        b"x" * len(OLD) if wrong == "hash" else OLD,
        bucket="another-bucket" if wrong == "bucket" else BACKUP_BUCKET,
        key=(backup_key(day=datetime.date.today() - datetime.timedelta(days=1))
             if wrong == "date" else backup_key("data/other.json") if wrong == "key" else None),
    )
    if wrong == "size":
        obj["size"] += 1
    if wrong == "missing_size":
        obj["size"] = None
    assert memory.backup(uploader) == (1, 0, 0, [])
    assert memory.count("GET") == memory.count("PUT") == 1
    assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] == OLD


@pytest.mark.parametrize("side", ["source", "backup"])
@pytest.mark.parametrize("length", [False, True, -1, None, 0.0, float("inf"),
                                    float("nan"), "+0", "0.0", " 0 ", "bad", "٠"])
def test_invalid_length_never_authorizes_reuse(uploader, side, length):
    memory = MemoryTransport(source=b"")
    obj = memory.seed_backup(b"")
    (memory.objects[SOURCE_BUCKET, KEY] if side == "source" else obj)["size"] = length
    try:
        result = memory.backup(uploader)
    except (TypeError, ValueError, OverflowError):
        # Existing relay int(source length) may reject malformed values after GET.
        assert side == "source"
    else:
        assert result[1] == 0
    assert memory.count("GET") == 1


@pytest.mark.parametrize("length", [0, "0", "00"])
def test_valid_zero_length_reuses_empty_object(uploader, length):
    memory = MemoryTransport(source=b"")
    memory.objects[SOURCE_BUCKET, KEY]["size"] = length
    memory.seed_backup(b"")["size"] = length
    assert memory.backup(uploader) == (0, 1, 0, [])
    assert memory.count("GET") == memory.count("PUT") == 0


@pytest.mark.parametrize("etag", ["multipart-2", "unknown", '"unbalanced',
                                  'W/"weak"', '""' + md5(OLD) + '""', md5(OLD).upper()])
def test_noncanonical_or_multipart_backup_falls_back(uploader, etag):
    memory = MemoryTransport()
    memory.seed_backup()["etag"] = etag
    assert memory.backup(uploader) == (1, 0, 0, [])
    assert memory.count("GET") == memory.count("PUT") == 1


@pytest.mark.parametrize("multipart_side", ["source", "both", "target_upload"])
def test_multipart_never_uses_full_md5_reuse(uploader, multipart_side):
    memory = MemoryTransport()
    backup = memory.seed_backup()
    if multipart_side != "target_upload":
        memory.objects[SOURCE_BUCKET, KEY]["etag"] = "multipart-2"
    if multipart_side == "both":
        backup["etag"] = "multipart-2"
    if multipart_side == "target_upload":
        memory.objects.pop((BACKUP_BUCKET, backup_key()))
        uploader._MULTIPART_THRESHOLD = 1
    assert memory.backup(uploader) == (1, 0, 0, [])
    assert memory.count("GET") == memory.count("PUT") == 1


def test_standard_quoted_etags_reuse(uploader):
    memory = MemoryTransport()
    memory.objects[SOURCE_BUCKET, KEY]["etag"] = '"' + md5(OLD) + '"'
    memory.seed_backup()["etag"] = '"' + md5(OLD) + '"'
    assert memory.backup(uploader) == (0, 1, 0, [])


@pytest.mark.parametrize("fault,stage", [
    ("source_head", "HEAD源"), ("backup_head", "HEAD备份桶"),
    ("get", "GET"), ("short_get", "GET"), ("put", "PUT"),
    ("not_landed", "回读"), ("corrupt_target", "回读"),
])
def test_failure_counts_and_samples(uploader, fault, stage):
    memory = MemoryTransport()
    memory.fault = fault
    copied, skipped, failed, samples = memory.backup(uploader)
    assert (copied, skipped, failed) == (0, 0, 1)
    assert samples[0]["key"] == KEY and samples[0]["stage"] == stage


def test_176_is_no_overwrite_loss_not_backup_content_proof(uploader):
    memory = MemoryTransport()
    memory.seed_backup(b"another older version")
    assert memory.backup(uploader, md5(OLD)) == (0, 1, 0, [])
    assert memory.count("GET") == memory.count("PUT") == 0
    assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] != OLD


def test_missing_today_backup_still_copies_when_local_equals_source(uploader):
    memory = MemoryTransport()
    assert memory.backup(uploader, md5(OLD)) == (1, 0, 0, [])
    assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] == OLD


def test_source_change_invalidates_same_day_backup(uploader):
    memory = MemoryTransport()
    memory.seed_backup()
    assert memory.backup(uploader) == (0, 1, 0, [])
    memory.objects[SOURCE_BUCKET, KEY] = object_record(NEW)
    assert memory.backup(uploader, "different local") == (1, 0, 0, [])
    assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] == NEW


def test_gzip_bytes_restore_without_transcoding(uploader):
    wire = gzip.compress(OLD, mtime=0)
    memory = MemoryTransport(source=wire)
    assert memory.backup(uploader) == (1, 0, 0, [])
    assert memory.backup(uploader) == (0, 1, 0, [])
    restored = memory.objects[BACKUP_BUCKET, backup_key()]["body"]
    assert restored == wire and gzip.decompress(restored) == OLD


def test_existing_multipart_length_only_is_not_content_proof(uploader):
    memory = MemoryTransport()
    memory.objects[SOURCE_BUCKET, KEY]["etag"] = "multipart-2"
    memory.fault = "corrupt_target"
    assert memory.backup(uploader) == (1, 0, 0, [])
    restored = memory.objects[BACKUP_BUCKET, backup_key()]["body"]
    assert len(restored) == len(OLD) and restored != OLD


def prepare_incremental(module, tmp_path):
    local = tmp_path / "static-site" / "data"
    local.mkdir(parents=True)
    (local / "example.json").write_bytes(NEW)
    state = tmp_path / "data" / ".r2_case_state.json"
    state.parent.mkdir()
    state.write_text(json.dumps({"files": {"example.json":
                     {"size": len(OLD), "md5": md5(OLD)}}}), encoding="utf-8")
    module.STATIC_DIR = local.parent
    return local, state, state.with_name(".r2_case_uploading.marker")


def incremental(module, local):
    return module._incremental_upload(
        local, ["*.json"], "data", ".r2_case_state.json", dry_run=False, label="offline")


def test_real_incremental_failure_keeps_state_then_reuses_backup(uploader, tmp_path, capsys):
    memory = MemoryTransport()
    memory.install(uploader)
    local, state, marker = prepare_incremental(uploader, tmp_path)
    old_state = state.read_bytes()
    uploader._upload_glob = lambda *args, **kwargs: (0, 1, ["example.json"], [])
    with pytest.raises(SystemExit) as failure:
        incremental(uploader, local)
    assert failure.value.code == 1
    assert state.read_bytes() == old_state and marker.exists()
    uploader._upload_glob = lambda *args, **kwargs: (1, 1, [], [KEY])
    assert incremental(uploader, local)[:2] == (1, 1)
    assert not marker.exists()
    assert json.loads(state.read_text())["files"]["example.json"]["md5"] == md5(NEW)
    assert memory.count("GET") == memory.count("PUT") == 1
    assert memory.objects[BACKUP_BUCKET, backup_key()]["body"] == OLD
    output = capsys.readouterr().out
    assert "备份完成 copied=1 skipped=0 failed=0" in output
    assert "备份完成 copied=0 skipped=1 failed=0" in output


def test_existing_backup_failure_does_not_block_primary_upload(uploader, tmp_path, capsys):
    memory = MemoryTransport()
    memory.fault = "source_head"
    memory.install(uploader)
    local, state, marker = prepare_incremental(uploader, tmp_path)
    primary_calls = []

    def primary(*args, **kwargs):
        primary_calls.append(True)
        return 1, 1, [], [KEY]

    uploader._upload_glob = primary
    assert incremental(uploader, local)[:2] == (1, 1)
    assert primary_calls == [True] and not marker.exists()
    assert "备份完成 copied=0 skipped=0 failed=1" in capsys.readouterr().out
