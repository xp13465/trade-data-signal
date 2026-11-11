"""Real receipt/index functions; isolated roots, concurrent callbacks, no network."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import errno
import fcntl
import hashlib
import importlib
import os
from pathlib import Path
import socket
import threading
import time

import pytest


@pytest.fixture
def publication(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED','1')
    monkeypatch.setenv('REPO',str(tmp_path))
    def no_network(*a,**k):pytest.fail('external transport forbidden')
    monkeypatch.setattr(socket,'create_connection',no_network)
    monkeypatch.setattr(socket.socket,'connect',no_network)
    e=importlib.import_module('ops_business_evidence');d=importlib.import_module('delivery_evidence')
    run='publication-concurrent';started=e.stamp(e.now()-timedelta(minutes=1))
    def put(name,confirmed=True):
        return d.record_publication(data_root=tmp_path,run_id=run,object_name=name,
            sha256=hashlib.sha256(name.encode()).hexdigest(),size=len(name),confirmed=confirmed)
    directory=d.receipt_root(tmp_path)/'publication'/hashlib.sha256(run.encode()).hexdigest()
    return e,d,tmp_path,run,started,put,directory


def test_real_parallel_distinct_objects_all_keep_confirmations(publication,monkeypatch):
    e,d,root,run,started,put,directory=publication
    names=e.TURNOVER;barrier=threading.Barrier(len(names));original=e.tempfile.mkstemp
    def overlap(*a,**k):
        if k.get('prefix')=='.publication-':barrier.wait(timeout=2)
        return original(*a,**k)
    monkeypatch.setattr(e.tempfile,'mkstemp',overlap)
    with ThreadPoolExecutor(max_workers=len(names)) as pool:results=list(pool.map(put,names))
    assert all(r['status']=='written' for r in results),results
    expected={name:{'sha256':hashlib.sha256(name.encode()).hexdigest(),'size':len(name)} for name in names}
    assert e.publication_confirmations(root,run,expected,started)==expected
    assert all((directory/name).stat().st_mode&0o777==0o600 for name in names)


def test_same_object_waits_for_short_contention_then_unknown_supersedes(publication,monkeypatch):
    e,d,root,run,started,put,directory=publication
    entered=threading.Event();release=threading.Event();original=e.tempfile.mkstemp
    def hold(*a,**k):
        if k.get('prefix')=='.publication-' and threading.current_thread().name.startswith('older'):
            entered.set();assert release.wait(timeout=1)
        return original(*a,**k)
    monkeypatch.setattr(e.tempfile,'mkstemp',hold)
    with ThreadPoolExecutor(max_workers=1,thread_name_prefix='older') as old,ThreadPoolExecutor(max_workers=1) as new:
        first=old.submit(put,'overview.json');assert entered.wait(timeout=1)
        second=new.submit(put,'overview.json',False)
        time.sleep(.04);release.set()
        assert first.result(timeout=1)['status']=='written'
        assert second.result(timeout=1)['status']=='written'
    assert e.bounded_json(directory/'overview.json')['stage_status']=='unknown'


def test_lock_timeout_is_bounded_metadata_failure_and_other_object_proceeds(publication):
    e,d,root,run,started,put,directory=publication
    assert put('overview.json')['status']=='written'
    fd=os.open(e._index_lock_path(directory,'overview.json'),os.O_RDWR)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:
        began=time.monotonic();result=put('overview.json',False);elapsed=time.monotonic()-began
        assert result=={'status':'metadata_failure','reason':'TimeoutError'}
        assert e.INDEX_LOCK_TIMEOUT_SECONDS<=elapsed<1
        assert put('boot.json')['status']=='written'
    finally:os.close(fd)
    # The caller may retry after the bounded metadata failure; no business rc changes.
    assert put('overview.json',False)['status']=='written'
    assert e.bounded_json(directory/'overview.json')['stage_status']=='unknown'


def test_enospc_keeps_valid_old_index_cleans_temp_and_reports_failure(publication,monkeypatch):
    e,d,root,run,started,put,directory=publication
    assert put('overview.json')['status']=='written'
    before=(directory/'overview.json').read_bytes();original=e.os.replace
    def full(src,dst):
        if Path(dst).parent==directory:raise OSError(errno.ENOSPC,'synthetic disk full')
        return original(src,dst)
    monkeypatch.setattr(e.os,'replace',full)
    assert put('overview.json',False)=={'status':'metadata_failure','reason':'OSError'}
    assert (directory/'overview.json').read_bytes()==before
    assert not list(directory.glob('.publication-*'))


def test_older_success_cannot_replace_newer_unknown_after_wait(publication,monkeypatch):
    e,d,root,run,started,put,directory=publication
    assert put('overview.json',False)['status']=='written'
    newer=e.bounded_json(directory/'overview.json')
    older=dict(newer,stage_status='success',evaluated_at=e.stamp(e.parsed(newer['evaluated_at'])-timedelta(seconds=1)))
    e.write_publication_index(root,older)
    assert e.bounded_json(directory/'overview.json')==newer
