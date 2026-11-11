"""Kepler P2：真实共享flock不得截断已有协调文件；只使用临时库和本地子进程。"""
import select
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.collector import public_fund as shared
from scripts import collect_fof_nav as nav
from scripts.tests.test_collect_fof_nav_333 import _conn, _seed_basic


@pytest.fixture
def locked_sandbox(tmp_path, monkeypatch):
    db = tmp_path / "public_fund.db"
    _seed_basic(db, [("016989", "FOF", "FOF-均衡型")])
    c = _conn(db)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    cursor = db.with_suffix(".fof-nav-progress.json")
    cursor.write_text('{"version":1,"last_code":"016989"}')
    monkeypatch.setattr(shared, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(shared, "_LOCK_FILE", [None])
    monkeypatch.setattr(nav, "DB_PATH", db)
    monkeypatch.setattr(nav, "_acquire_lock", shared._acquire_lock)  # 必须用真实共享helper。
    monkeypatch.setattr(nav, "get_conn", lambda: sqlite3.connect(db))
    monkeypatch.setattr(nav, "init_db", lambda: None)
    monkeypatch.setattr(nav, "RATE_LIMIT", 0)
    def forbidden(*args, **kwargs):
        raise AssertionError("禁止真实网络/通知")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(nav.urllib.request, "urlopen", forbidden)
    yield db, tmp_path / "public_fund.lock", cursor
    if shared._LOCK_FILE[0] is not None:
        shared._LOCK_FILE[0].close()


def _peer_try(lock_path):
    # 独立进程使用原生产锁域和相同LOCK_EX|LOCK_NB竞争，绝不写入文件内容。
    program = """
import fcntl, sys
with open(sys.argv[1], 'a') as f:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(2)
"""
    return subprocess.run([sys.executable, "-c", program, str(lock_path)],
                          capture_output=True, text=True, timeout=5).returncode


def test_existing_lock_sentinel_preview_keeps_content_db_cursor_and_exclusion(locked_sandbox, monkeypatch):
    db, lock, cursor = locked_sandbox
    lock.write_bytes(b"existing-public-fund-lock-sentinel\n")
    before = (lock.read_bytes(), lock.stat().st_ino, db.read_bytes(), cursor.read_bytes())
    peers = []
    def preview(*a, **kw):
        peers.append(_peer_try(lock))
        return []
    monkeypatch.setattr(nav, "fetch_lsjz", preview)
    assert nav.collect(dry_run=True, fund_code="016989") == 0
    assert peers == [2]  # 预览期间同域正常写者被真实flock排斥。
    assert (lock.read_bytes(), lock.stat().st_ino, db.read_bytes(), cursor.read_bytes()) == before
    shared._LOCK_FILE[0].close()
    shared._LOCK_FILE[0] = None
    assert _peer_try(lock) == 0  # 预览释放后正常进程能取得同一文件锁。


@pytest.mark.parametrize("dry_run", [True, False])
def test_busy_real_lock_never_truncates_or_touches_db_cursor(locked_sandbox, monkeypatch, dry_run):
    db, lock, cursor = locked_sandbox
    lock.write_bytes(b"held-by-production-like-peer\n")
    before = (lock.read_bytes(), lock.stat().st_ino, db.read_bytes(), cursor.read_bytes())
    program = """
import fcntl, sys
with open(sys.argv[1], 'a') as f:
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print('locked', flush=True)
    sys.stdin.readline()
"""
    proc = subprocess.Popen([sys.executable, "-c", program, str(lock)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert select.select([proc.stdout], [], [], 5)[0], "子进程取锁未就绪"
        assert proc.stdout.readline().strip() == "locked"
        def forbidden(*a, **kw):
            raise AssertionError("锁忙不得初始化/取连接/请求API")
        monkeypatch.setattr(nav, "init_db", forbidden)
        monkeypatch.setattr(nav, "get_conn", forbidden)
        monkeypatch.setattr(nav, "fetch_lsjz", forbidden)
        nav.LAST_BATCH_FAILED = True
        assert nav.collect(dry_run=dry_run, fund_code="016989") == 0
        assert nav.LAST_BATCH_FAILED is False
        assert shared._LOCK_FILE[0] is None
        assert (lock.read_bytes(), lock.stat().st_ino, db.read_bytes(), cursor.read_bytes()) == before
    finally:
        try:
            proc.communicate(input="release\n", timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)
    assert proc.returncode == 0
    assert _peer_try(lock) == 0


def test_missing_lock_preview_does_not_create_coordination_metadata(locked_sandbox, monkeypatch):
    db, lock, cursor = locked_sandbox
    assert not lock.exists()
    before = (db.read_bytes(), cursor.read_bytes())
    monkeypatch.setattr(nav, "fetch_lsjz", lambda *a, **kw: [])
    assert nav.collect(dry_run=True, fund_code="016989") == 0
    assert not lock.exists()  # HC07本次授权要求：dry-run连协调文件也不创建。
    assert (db.read_bytes(), cursor.read_bytes()) == before
    assert shared._LOCK_FILE[0] is None


def test_other_existing_production_lock_domain_is_nontruncating(locked_sandbox):
    db, public_lock, cursor = locked_sandbox
    lock = public_lock.with_name("public_fund_stage0.lock")
    lock.write_bytes(b"stage0-sentinel\n")
    assert shared._acquire_lock(nonblock=True, lock_name="public_fund_stage0") is True
    assert lock.read_bytes() == b"stage0-sentinel\n"
    assert _peer_try(lock) == 2
    assert not public_lock.exists()  # 没有混入公募日更锁域。
