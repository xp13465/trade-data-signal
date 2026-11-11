"""Committed inputs -> real SQLite exporter -> bounded public-byte witness, offline."""
import hashlib
import json
import socket
import sqlite3
import time
from datetime import timedelta

import pytest

from scripts import export_fund_nav as exporter
from scripts import ops_business_evidence as business
from scripts import ops_fund_evidence as fund
from scripts import ops_nav_publication as nav

CODE = 'a' * 40


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED', '1')
    monkeypatch.setenv('INVOCATION_ID', 'nav-test')
    monkeypatch.delenv('OPS_FUND_RUN', raising=False)
    monkeypatch.delenv('OPS_FUND_STARTED', raising=False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr(nav, 'code_identity', lambda *a: {'sha': CODE})
    monkeypatch.setattr(nav, '_CACHE', None)
    monkeypatch.setattr(exporter, 'ROOT', tmp_path)
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE fund_daily_nav(date TEXT, fund_code TEXT, fund_name TEXT, unit_nav REAL, acc_nav REAL, prev_unit_nav REAL, nav_change_pct REAL)')
    rows = [('20261111', '000001', 'A', 1.25, 2.5, None, None),
            ('20261111', '000002', 'B', 2.25, None, None, None),
            ('20261111', '000003', 'C', None, None, None, None)]
    conn.executemany('INSERT INTO fund_daily_nav VALUES(?,?,?,?,?,?,?)', rows)
    conn.commit()
    out = tmp_path / 'static-site/data/nav_bucket'
    out.mkdir(parents=True)
    def collect():
        current = fund.Round(tmp_path, 'public-fund', {'sha': CODE})
        current.observation_deadline = time.monotonic() + 10
        current.apply('daily', rows=rows, selected_date='20261111')
        current.apply('daily_commit', rows=rows)
        current.record()
        return business.bounded_json(tmp_path / 'data/ops_delivery/index/public-fund.json')
    def export():
        nav.export_begin(tmp_path, exporter._build_payload)
        buckets = {}
        for code in ('000001', '000002', '000003'):
            buckets.setdefault(exporter._fund_bucket(code), {})[code] = exporter._build_payload(conn, code)
        for bucket, payload in buckets.items():
            exporter._atomic_write_json(out / (bucket+'.json'), payload)
        return buckets
    calls = []
    def fetch(bucket, size, deadline):
        calls.append(bucket)
        return (out / (bucket+'.json')).read_bytes()
    yield tmp_path, conn, collect, export, fetch, calls
    conn.close()


def test_selected_publication_does_not_make_whole_pool_healthy(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect()
    assert receipt['consumer_witness']['fund_evidence']['publication_input']['rows'] == 2
    export()
    assert nav.inspect_scope(root, receipt)['exported_buckets'] == 2
    assert nav.verify(root, fetch=fetch)['confirmed'] == 2
    stage = nav.inspect_scope(root, receipt)
    assert stage['state'] == 'scoped_confirmed' and not stage['whole_pool_verified']
    live = {k: [v] for k,v in dict(InvocationID='nav-test', ActiveState='inactive', SubState='dead', Result='success', ExecMainStatus='0').items()}
    state, evidence = business.assess(root, 'public-fund', business.now(), CODE, live)
    assert state == 'unknown' and evidence['publication_state'] == 'scoped_confirmed'
    assert len(evidence) <= 20


def test_partial_budget_resumes_without_refetching_confirmed_bucket(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export()
    bucket = sorted(nav._scope(root, receipt, nav.fund_bucket)['buckets'])[0]
    size = nav._bucket_path(root, bucket).stat().st_size
    first = nav.verify(root, max_bytes=size+1, fetch=fetch)
    assert first['confirmed'] == 1 and first['budget_exhausted']
    assert nav.inspect_scope(root, receipt)['state'] == 'partial'
    assert nav.verify(root, fetch=fetch)['confirmed'] == 1
    assert len(calls) == len(set(calls)) == 2
    assert nav.inspect_scope(root, receipt)['state'] == 'scoped_confirmed'


def test_identical_export_preserves_confirmed_generation(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export(); nav.verify(root, fetch=fetch)
    for path in (root/'static-site/data/nav_bucket').glob('*.json'):
        with path.open('rb') as f:
            token = nav.file_identity(f.fileno()); raw = f.read()
        nav.export_bucket(root, path, json.loads(raw), raw, producer=exporter._build_payload, file_token=token)
    assert nav.inspect_scope(root, receipt)['state'] == 'scoped_confirmed'
    assert nav.verify(root, fetch=fetch)['attempted'] == 0


@pytest.mark.parametrize('change', ['value', 'date', 'missing'])
def test_conflicting_export_invalidates_old_good_witness(pipeline, change):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export(); nav.verify(root, fetch=fetch)
    sql = {'value': "UPDATE fund_daily_nav SET unit_nav=9 WHERE fund_code='000001'",
           'date': "UPDATE fund_daily_nav SET date='20261110' WHERE fund_code='000001'",
           'missing': "DELETE FROM fund_daily_nav WHERE fund_code='000001'"}[change]
    conn.execute(sql); conn.commit(); export()
    stage = nav.inspect_scope(root, receipt)
    assert stage['state'] == 'unknown' and stage['exported_buckets'] == 1
    result = nav.verify(root, fetch=fetch)
    assert result['unverified'] == 1 and result['confirmed'] == 1
    assert nav.inspect_scope(root, receipt)['state'] == 'partial'


def test_wrong_public_bytes_remain_unknown(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export()
    report = nav.verify(root, fetch=lambda *a: b'{}')
    assert report['confirmed'] == 0 and report['unverified'] == 2
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_new_collection_cannot_inherit_old_publication(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    first = collect(); export(); nav.verify(root, fetch=fetch)
    second = collect()
    assert first['attempt_id'] != second['attempt_id']
    assert nav.inspect_scope(root, second)['state'] == 'unknown'
    assert nav.verify(root, fetch=fetch)['attempted'] == 0


def test_tampered_scope_or_fake_success_cannot_confirm(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export(); nav.verify(root, fetch=fetch)
    path = nav._input_path(root, receipt['object_id'], receipt['attempt_id'])
    path.write_bytes(b'{}')
    receipt['stage_status'] = 'success'
    receipt['consumer_witness']['fund_evidence']['publication_status'] = 'success'
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_unreviewed_export_code_cannot_confirm(pipeline, monkeypatch):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect()
    monkeypatch.setattr(nav, 'code_identity', lambda *a: {'sha': 'unknown'})
    export()
    assert nav.verify(root, fetch=fetch)['attempted'] == 0
    assert nav.inspect_scope(root, receipt)['exported_buckets'] == 0


def test_expired_scope_and_exhausted_inspection_are_unknown(pipeline, monkeypatch):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export(); nav.verify(root, fetch=fetch)
    assert nav.inspect_scope(root, receipt, seconds=0)['state'] == 'unknown'
    later = business.now() + timedelta(hours=27)
    monkeypatch.setattr(business, 'now', lambda: later)
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_missing_scope_inspection_creates_nothing(tmp_path):
    assert nav.inspect_scope(tmp_path, {})['state'] == 'unknown'
    assert list(tmp_path.iterdir()) == []


def test_disabled_observation_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED', '0')
    assert nav.save_inputs(tmp_path, 'public-fund', 'r', 'x', {}) is None
    nav.export_begin(tmp_path)
    nav.export_bucket(tmp_path, tmp_path/'00.json', {}, b'{}')
    assert nav.verify(tmp_path, fetch=lambda *a: pytest.fail('GET forbidden'))['status'] == 'disabled'
    assert list(tmp_path.iterdir()) == []


def test_loaded_identity_changes_with_helper(tmp_path, monkeypatch):
    before = nav.code_identity(exporter._build_payload, tmp_path)
    monkeypatch.setattr(nav, 'fund_bucket', lambda x: '00')
    after = nav.code_identity(exporter._build_payload, tmp_path)
    assert before['module_sha256'] != after['module_sha256']


def test_symlink_input_is_refused(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect()
    path = nav._input_path(root, receipt['object_id'], receipt['attempt_id'])
    backup = path.with_suffix('.backup')
    path.rename(backup); path.symlink_to(backup)
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_metadata_initialization_failure_does_not_break_export(pipeline, monkeypatch):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect()
    monkeypatch.setattr(nav, 'code_identity', lambda *a: (_ for _ in ()).throw(OSError('metadata disk')))
    export()
    assert len(list((root/'static-site/data/nav_bucket').glob('*.json'))) == 3
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_cli_process_deadline_covers_blocking_lookup(tmp_path, monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, 'argv', ['nav', 'verify', '--root', str(tmp_path), '--seconds', '.02'])
    monkeypatch.setattr(nav, 'verify', lambda *a, **k: time.sleep(5))
    started = time.monotonic()
    nav.main()
    assert time.monotonic()-started < 1
    assert json.loads(capsys.readouterr().out) == {'status':'unknown', 'budget_exhausted':True}


def test_public_transport_uses_fixed_identity_url_and_bounded_read1(monkeypatch):
    import urllib.request
    calls = []
    class Response:
        status = 200
        headers = {'Content-Encoding': 'identity'}
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, *a): pytest.fail('unbounded read cannot be used')
        def read1(self, n):
            calls.append(n)
            return b'x' * n
    class Opener:
        def open(self, req, timeout):
            assert req.full_url == nav.PUBLIC_BASE+'00.json'
            assert req.get_header('Accept-encoding') == 'identity'
            assert 0 < timeout <= 5
            return Response()
    def build(*handlers):
        redirect = next(h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
        assert redirect.redirect_request(None, None, None, None, None, None) is None
        return Opener()
    monkeypatch.setattr(urllib.request, 'build_opener', build)
    assert nav._fetch_public('00', 2, time.monotonic()+1) == b'xxx'
    assert calls == [3]  # exactly size+1, enough to reject an oversized object


def test_rewrite_without_metadata_invalidates_old_success(pipeline, monkeypatch):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export(); nav.verify(root, fetch=fetch)
    conn.execute('UPDATE fund_daily_nav SET unit_nav=9'); conn.commit()
    monkeypatch.setattr(nav, 'emit_receipt', lambda **k: {'status':'metadata_failure'})
    export()
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'
    assert nav.verify(root, fetch=fetch)['attempted'] == 0


def test_late_callback_cannot_overwrite_current_export(pipeline, monkeypatch):
    import threading
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export()
    bucket = nav.fund_bucket('000001'); path = nav._bucket_path(root, bucket)
    old = json.loads(path.read_bytes()); new = json.loads(path.read_bytes())
    new['000001']['nav'][0][1] = 9
    entered, release = threading.Event(), threading.Event()
    callback = exporter._nav_bucket
    errors = []
    def delayed(*args, **kwargs):
        if threading.current_thread().name == 'old-exporter':
            entered.set(); assert release.wait(5)
        return callback(*args, **kwargs)
    monkeypatch.setattr(exporter, '_nav_bucket', delayed)
    def old_writer():
        try: exporter._atomic_write_json(path, old)
        except BaseException as exc: errors.append(exc)
    thread = threading.Thread(target=old_writer, name='old-exporter')
    thread.start()
    try:
        assert entered.wait(5)
        exporter._atomic_write_json(path, new)
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors
    assert nav.inspect_scope(root, receipt)['exported_buckets'] == 1  # only other bucket
    nav.verify(root, fetch=fetch)
    assert nav.inspect_scope(root, receipt)['state'] == 'partial'


def test_public_get_cannot_confirm_export_replaced_during_request(pipeline):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export()
    def replaced(bucket, size, deadline):
        raw = fetch(bucket, size, deadline)
        path = nav._bucket_path(root, bucket)
        exporter._atomic_write_json(path, json.loads(raw))
        return raw
    report = nav.verify(root, fetch=replaced)
    assert report['confirmed'] == 0 and report['unverified'] == 2
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_late_response_and_failed_publication_are_unverified(pipeline, monkeypatch):
    root, conn, collect, export, fetch, calls = pipeline
    receipt = collect(); export()
    def slow(*args):
        time.sleep(.03)
        return fetch(*args)
    report = nav.verify(root, seconds=.02, fetch=slow)
    assert report['confirmed'] == 0 and report['unverified'] == 1
    monkeypatch.setattr(nav, 'emit_receipt', lambda **k: {'status':'metadata_failure'})
    report = nav.verify(root, fetch=fetch)
    assert report['confirmed'] == 0 and report['unverified'] == 2
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'


def test_slow_sidecar_preserves_commit_fact_but_not_publication_proof(pipeline, monkeypatch):
    root, conn, collect, export, fetch, calls = pipeline
    original = nav.save_inputs
    def slow(*args):
        time.sleep(.03)
        return original(*args)
    monkeypatch.setattr(nav, 'save_inputs', slow)
    monkeypatch.setattr(fund, 'MAX_WORK_SECONDS', .02)
    receipt = collect()
    facts = receipt['consumer_witness']['fund_evidence']
    assert facts['collection_status'] == 'scoped_committed'
    assert facts['publication_finalize_seconds'] >= .03
    assert facts['publication_input'] is None
    assert nav.inspect_scope(root, receipt)['state'] == 'unknown'
