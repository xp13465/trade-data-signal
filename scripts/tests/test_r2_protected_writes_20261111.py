"""真实 uploader + HTTPS transport fake。禁真实网络、凭据、通知，临时 REPO。"""
import ast
import hashlib
import io
import json
import sys
import types
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'upload_r2.py'
KEY = 'data/nextday_plan.json'


class Transport:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.uploads = {}
        self.fail_backup = False
        self.corrupt_backup = False
        self.lose_response = False
        self.never_commit = False
        self.race = False

    def put(self, bucket, key, body, headers=None):
        self.objects[bucket, key] = (body, {'ETag': '"' + hashlib.md5(body).hexdigest() + '"',
            'Content-Length': str(len(body)), **{k: v for k, v in (headers or {}).items() if k.startswith('x-amz-meta-')}})

    def request(self, method, uri, body, headers):
        parsed = urlsplit(uri)
        bucket, _, key = unquote(parsed.path).lstrip('/').partition('/')
        q = parse_qs(parsed.query, keep_blank_values=True)
        headers = {k.lower(): v for k, v in headers.items()}
        if hasattr(body, 'read'):
            body = body.read()
        self.calls.append((method, bucket, key, q, dict(headers)))
        old = self.objects.get((bucket, key))
        if method in ('GET', 'HEAD'):
            if old:
                return 200, old[0] if method == 'GET' else b'', old[1]
            return 404, b'<Error><Code>NoSuchKey</Code></Error>', {}
        if method == 'DELETE':
            return 204, b'', {}
        if bucket == 'backup' and self.fail_backup:
            return 403, b'denied', {}
        if method == 'POST' and 'uploads' in q:
            uid = str(len(self.uploads) + 1)
            self.uploads[uid] = [headers, {}]
            return 200, f'<Result><UploadId>{uid}</UploadId></Result>'.encode(), {}
        if 'partNumber' in q:
            self.uploads[q['uploadId'][0]][1][int(q['partNumber'][0])] = body
            return 200, b'', {'ETag': '"part"'}
        if self.race and bucket == 'public':
            self.put(bucket, key, b'concurrent')
            old = self.objects[bucket, key]
        if ('if-none-match' in headers and old) or ('if-match' in headers and (not old or old[1]['ETag'] != headers['if-match'])):
            return 412, b'precondition', {}
        if 'uploadId' in q:
            meta, parts = self.uploads[q['uploadId'][0]]
            body = b''.join(parts[n] for n in sorted(parts))
            headers.update(meta)
        if self.never_commit and bucket == 'public':
            raise OSError('response lost before known commit')
        if self.corrupt_backup and bucket == 'backup':
            body = b'x' * len(body)
        self.put(bucket, key, body, headers)
        if self.lose_response and bucket == 'public':
            self.lose_response = False
            raise OSError('response lost after commit')
        return 200, b'<CompleteMultipartUploadResult/>', {}


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ('R2_BUCKET', 'R2_S3_ENDPOINT', 'R2_S3_ACCESS_KEY_ID', 'R2_S3_SECRET_ACCESS_KEY'):
        monkeypatch.setenv(name, 'https://fake.invalid' if name.endswith('ENDPOINT') else 'fake')
    monkeypatch.setenv('REPO', str(tmp_path))
    monkeypatch.setenv('GIT_REPO', str(tmp_path))
    monkeypatch.setenv('ALLOW_FULL_UPLOAD', '1')
    monkeypatch.setenv('R2_UPLOAD_LOCK', str(tmp_path / 'upload.lock'))
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    monkeypatch.setitem(sys.modules, 'notify', types.SimpleNamespace(
        send=lambda *a, **k: None, check_dedup=lambda *a: True, update_dedup=lambda *a: None))
    # 只消除模块初始化读真实 .env/stdout reconfigure；生产函数原样执行。
    tree = ast.parse(SOURCE.read_text())
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and (getattr(n.value.func, 'id', '') == 'load_env' or getattr(n.value.func, 'attr', '') == 'reconfigure'))]
    m = types.ModuleType('isolated_r2'); m.__file__ = str(SOURCE)
    exec(compile(tree, str(SOURCE), 'exec'), m.__dict__)
    fake = Transport()
    class Connection:
        sock = None
        def __init__(self, *a, **k): pass
        def request(self, method, uri, body=None, headers=None):
            self.result = fake.request(method, uri, body, headers or {})
        def getresponse(self):
            st, body, headers = self.result
            return types.SimpleNamespace(status=st, read=io.BytesIO(body).read,
                                         getheaders=lambda: list(headers.items()),
                                         getheader=lambda k, default=None: headers.get(k, default))
        def close(self): pass
    monkeypatch.setattr(m.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(m, '_route_bucket', lambda b: ('fake.invalid', 'fake', 'fake'))
    monkeypatch.setattr(m, 'BUCKET', 'public'); monkeypatch.setattr(m, 'BACKUP_BUCKET', 'backup')
    monkeypatch.setattr(m, '_work_sleep', lambda *a: None)
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: True)
    monkeypatch.setattr(m, '_prune_pre_upload', lambda *a: None)
    monkeypatch.setattr(m, '_notify_channel_upload_fail', lambda *a, **k: None)
    m.STATIC_DIR.mkdir(parents=True)
    yield m, fake


def upload(m, body=b'new', key=KEY):
    p = m.STATIC_DIR / key
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(body)
    return m._upload_glob(p.parent, [p.name], key.rpartition('/')[0])


def test_backup_failure_blocks_actual_incremental_put(client):
    m, f = client
    f.put('public', KEY, b'old'); f.fail_backup = True
    p = m.STATIC_DIR / KEY; p.parent.mkdir(); p.write_bytes(b'new')
    with pytest.raises(SystemExit):
        m._incremental_upload(p.parent, ['*.json'], 'data', '.r2_test_state.json')
    assert f.objects['public', KEY][0] == b'old'


def test_multipart_complete_carries_condition(client):
    m, f = client
    m._multipart_upload('probe', 3, lambda off, n: b'new'[off:off+n], 'application/json',
                         extra_headers={'if-none-match': '*'})
    complete = [x for x in f.calls if x[0] == 'POST' and 'uploadId' in x[3]]
    assert complete[0][4]['if-none-match'] == '*'


def public_writes(fake):
    return [c for c in fake.calls if c[0] in ('PUT', 'POST') and c[1] == 'public' and not c[3]]


@pytest.mark.parametrize('old', [None, b'old'])
def test_create_and_overwrite_are_conditional(client, old):
    m, f = client
    if old is not None: f.put('public', KEY, old)
    assert upload(m)[0] == 1
    assert f.objects['public', KEY][0] == b'new'
    h = public_writes(f)[0][4]
    assert ('if-none-match' if old is None else 'if-match') in h
    assert 'x-amz-meta-write-id' in h
    row = m.SafeWriter(m.__dict__).load(KEY)
    assert row['confirmed'] and not row['pending_purge']
    if old: assert f.objects['backup', row['backup_key']][0] == old


def test_same_length_corrupt_backup_rejected(client):
    m, f = client
    f.put('public', KEY, b'old'); f.corrupt_backup = True
    assert upload(m)[0] == 0
    assert not public_writes(f)


def test_two_writers_cas_refuses_loser(client):
    m, f = client
    f.put('public', KEY, b'old'); f.race = True
    assert upload(m)[0] == 0
    assert f.objects['public', KEY][0] == b'concurrent'
    row = m.SafeWriter(m.__dict__).load(KEY)
    assert row['state'] == 'failed' and row['status'] == 412 and not row['confirmed']
    assert len(public_writes(f)) == 1


@pytest.mark.parametrize('multipart', [False, True])
def test_lost_response_after_commit_confirmed_by_write_id(client, multipart):
    m, f = client
    if multipart: m._MULTIPART_THRESHOLD = 2
    f.put('public', KEY, b'old'); f.lose_response = True
    assert upload(m)[0] == 1
    assert m.SafeWriter(m.__dict__).load(KEY)['confirmed']
    if multipart:
        c = [c for c in f.calls if c[0] == 'POST' and 'uploadId' in c[3] and c[1] == 'public']
        assert c[0][4]['if-match'] == '"' + hashlib.md5(b'old').hexdigest() + '"'


def test_negative_read_after_lost_response_blocks_reentry(client):
    m, f = client
    f.never_commit = True
    assert upload(m)[0] == 0
    count = len(public_writes(f))
    f.never_commit = False
    assert upload(m)[0] == 0
    assert len(public_writes(f)) == count
    assert m.SafeWriter(m.__dict__).load(KEY)['state'] == 'unknown'


def test_same_bytes_from_other_write_id_not_confirmation(client):
    m, f = client
    safe = m.SafeWriter(m.__dict__); row = safe.prepare(KEY, b'new')
    row['state'] = 'unknown'; safe.save(row)
    f.put('public', KEY, b'new', {'x-amz-meta-write-id': 'someone-else'})
    assert upload(m)[0] == 0


def test_purge_failure_reentry_without_rewrite(client, monkeypatch):
    m, f = client
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: False)
    assert upload(m)[0] == 0
    row = m.SafeWriter(m.__dict__).load(KEY)
    assert row['confirmed'] and row['pending_purge']
    count = len(public_writes(f))
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: True)
    assert upload(m)[0] == 1
    assert len(public_writes(f)) == count
    assert not m.SafeWriter(m.__dict__).load(KEY)['pending_purge']


def test_enospc_before_send_keeps_old_bytes(client, monkeypatch):
    import r2_safe_write
    m, f = client
    f.put('public', KEY, b'old')
    def full(*args): raise OSError(28, 'No space left on device')
    monkeypatch.setattr(r2_safe_write, 'durable', full)
    assert upload(m)[0] == 0
    assert not public_writes(f)
    assert f.objects['public', KEY][0] == b'old'


def test_crash_after_remote_commit_recovers_without_rewrite(client, monkeypatch):
    m, f = client
    original = m.SafeWriter.save
    def crash(self, row):
        if row['confirmed']: raise SystemExit(124)
        return original(self, row)
    monkeypatch.setattr(m.SafeWriter, 'save', crash)
    with pytest.raises(SystemExit): upload(m)
    assert m.SafeWriter(m.__dict__).load(KEY)['state'] == 'unknown'
    count = len(public_writes(f))
    monkeypatch.setattr(m.SafeWriter, 'save', original)
    assert upload(m)[0] == 1
    assert len(public_writes(f)) == count


def test_noncritical_independent_object_not_blocked(client):
    m, f = client
    p = m.STATIC_DIR / KEY; p.parent.mkdir(); p.write_bytes(b'new')
    (p.parent / 'independent.json').write_bytes(b'ok')
    f.put('public', KEY, b'old'); f.fail_backup = True
    result = m._upload_glob(p.parent, ['*.json'], 'data')
    assert result[:3] == (1, 2, ['nextday_plan.json'])
    assert f.objects['public', 'data/independent.json'][0] == b'ok'


@pytest.mark.parametrize('key', ['data/auto_trade_steps.json', 'data/signal_kelly_day_snapshot.json', 'nav_bucket/00.json'])
def test_critical_key_inventory(client, key):
    m, f = client
    f.put('public', key, b'old'); f.fail_backup = True
    assert upload(m, key=key)[0] == 0
    assert f.objects['public', key][0] == b'old'


@pytest.mark.parametrize('entry', ['raw', 'data-files'])
def test_direct_entries_cannot_bypass_backup(client, entry):
    m, f = client
    p = m.STATIC_DIR / KEY; p.parent.mkdir(); p.write_bytes(b'new')
    f.put('public', KEY, b'old'); f.fail_backup = True
    with pytest.raises(SystemExit):
        m.cmd_upload(str(p), KEY) if entry == 'raw' else m.cmd_upload_data_files([p.name])
    assert f.objects['public', KEY][0] == b'old'


def test_pair_backs_up_both_before_first_commit(client):
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    for key in m._OVERFIT_PAIR:
        (m.STATIC_DIR / key).write_bytes(b'{"generated_at":"new","publication_run_id":"new-run"}')
        f.put('public', key, b'{"generated_at":"old"}')
    assert m._upload_glob(d, ['overfit_monitor.json'], 'data')[:2] == (2, 2)
    first = next(i for i, c in enumerate(f.calls) if c in public_writes(f))
    backups = [c for c in f.calls[:first] if c[1] == 'backup' and c[0] == 'GET']
    assert len(backups) == 3  # 两个旧对象及恢复配对清单均已回读。
    rows = [m.SafeWriter(m.__dict__).load(k) for k in m._OVERFIT_PAIR]
    assert rows[0]['pair_id'] == rows[1]['pair_id']


def test_pair_generation_mismatch_blocks_both(client):
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    for i, key in enumerate(m._OVERFIT_PAIR):
        (m.STATIC_DIR / key).write_text(json.dumps({'generated_at': str(i)}))
    assert m._upload_glob(d, ['overfit*.json'], 'data')[0] == 0
    assert not public_writes(f)


@pytest.mark.parametrize('tokens', [('run-a', 'run-b'), ('', ''), ('_bad', '_bad'),
                                   ('a' * 129, 'a' * 129)])
def test_same_minute_pair_requires_valid_equal_unique_token(client, tokens):
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    for key, token in zip(m._OVERFIT_PAIR, tokens):
        (m.STATIC_DIR / key).write_text(json.dumps({
            'generated_at': '2026-11-11 08:05', 'publication_run_id': token}))
    assert m._upload_glob(d, ['overfit*.json'], 'data')[0] == 0
    assert not public_writes(f)


@pytest.mark.parametrize('olds', [(b'{"generated_at":"old"}', b'{"generated_at":"old"}'),
                                 (b'{"generated_at":"a"}', b'{"generated_at":"b"}'),
                                 (b'legacy raw bytes', None)])
def test_legacy_pair_upgrade_preserves_bytes_without_generation_claim(client, olds):
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    for key, old in zip(m._OVERFIT_PAIR, olds):
        (m.STATIC_DIR / key).write_bytes(b'{"generated_at":"new","publication_run_id":"new-run"}')
        if old is not None:
            f.put('public', key, old)
    assert m._upload_glob(d, ['overfit*.json'], 'data')[0] == 2
    safe = m.SafeWriter(m.__dict__)
    for key, old in zip(m._OVERFIT_PAIR, olds):
        row = safe.load(key)
        assert row['old_generation_verified'] is False
        if old is not None:
            assert f.objects['backup', row['backup_key']][0] == old
    manifest = json.loads((safe.root / 'pairs' / (row['pair_id'] + '.json')).read_text())
    assert manifest['generation_verified'] is True
    assert manifest['old_generation_verified'] is False


def test_token_contract_boundary(client):
    m, _ = client
    token = 'A' + '_.:-09' * 21 + 'z'
    assert len(token) == 128
    assert m.SafeWriter.publication_token(json.dumps({'publication_run_id': token}).encode()) == token


def test_reference_gc_bounds_completed_history(client):
    m, _ = client
    for i in range(9):
        assert upload(m, ('payload-%02d' % i).encode())[0] == 1
    safe = m.SafeWriter(m.__dict__)
    with safe.storage_lock(): safe.gc()
    assert len(list((safe.root / 'history').glob('*.json'))) == 1
    assert len(list((safe.root / 'payloads').iterdir())) == 2  # 当前及其旧版本。
    manifest = json.loads((safe.root / 'gc-manifest.json').read_text())
    assert all((safe.root / p).exists() for p in manifest['keep'])


def test_disk_space_preflight_blocks_without_remote_write(client, monkeypatch):
    import r2_safe_write
    m, f = client
    monkeypatch.setattr(r2_safe_write.shutil, 'disk_usage', lambda _: types.SimpleNamespace(free=128))
    assert upload(m)[0] == 0
    assert not public_writes(f)
    assert not [c for c in f.calls if c[0] == 'PUT']


def test_purge_drip_response_keeps_absolute_deadline(client, monkeypatch):
    m, _ = client
    tree = ast.parse(SOURCE.read_text())
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'purge_cache')
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(SOURCE), 'exec'), m.__dict__)
    monkeypatch.setenv('PURGE_SECRET', 'fake-only')
    reads, closed = [], []
    now = [100.0]
    monkeypatch.setattr(m.time, 'monotonic', lambda: now[0])
    m._WORK_DEADLINE = 100.1
    class Connection:
        sock = None
        def __init__(self, *a, **kw): pass
        def request(self, *a, **kw): pass
        def close(self): closed.append(True)
        def getresponse(self):
            def drip(n):
                reads.append(n); now[0] += .11
                return b'x'
            return types.SimpleNamespace(status=200, read=drip, read1=drip,
                                         getheader=lambda _: '100')
    monkeypatch.setattr(m.http.client, 'HTTPSConnection', Connection)
    with pytest.raises(m.WorkBudgetExceeded): m.purge_cache([KEY])
    assert len(reads) == 1 and closed == [True]


def test_default_capacity_fits_observed_working_set(client, monkeypatch):
    import r2_safe_write
    m, _ = client
    monkeypatch.delenv('R2_PROTECTED_MAX_BYTES', raising=False)
    safe = m.SafeWriter(m.__dict__); safe.root.mkdir(parents=True)
    monkeypatch.setattr(r2_safe_write.shutil, 'disk_usage', lambda _: types.SimpleNamespace(free=4 * 1024**3))
    # 父任务实测输入；仅元数据模型检验容量，不分配1GB临时测试数据。
    measured = 2 * (574207502 + 4007963 + 10606607)
    existing = types.SimpleNamespace(stat=lambda: types.SimpleNamespace(st_size=measured))
    safe.check_capacity([existing], {safe.root / 'sample': b'x' * 4096})


def test_capacity_refuses_before_write_preserving_pending(client, monkeypatch):
    m, f = client
    f.never_commit = True
    assert upload(m)[0] == 0
    safe = m.SafeWriter(m.__dict__); row = safe.load(KEY)
    anchor = (safe.root / 'payloads' / row['sha256']).read_bytes()
    f.never_commit = False
    monkeypatch.setenv('R2_PROTECTED_MAX_BYTES', '1')
    before = len(public_writes(f))
    assert upload(m, b'other', 'data/auto_trade_steps.json')[0] == 0
    assert len(public_writes(f)) == before
    assert (safe.root / 'payloads' / row['sha256']).read_bytes() == anchor
    assert safe.load(KEY)['state'] == 'unknown'
    # 非关键独立对象不需要关键存储容量。
    assert upload(m, b'independent', 'data/ordinary.json')[0] == 1


def test_gc_unknown_and_partial_pair_anchors_survive_other_updates(client, monkeypatch):
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    for key in m._OVERFIT_PAIR:
        (m.STATIC_DIR / key).write_bytes(b'{"generated_at":"new","publication_run_id":"new-run"}')
    original = f.request
    def reject_ext(method, uri, body, headers):
        if method == 'PUT' and uri == '/public/' + m._OVERFIT_PAIR[1]:
            return 409, b'locked', {}
        return original(method, uri, body, headers)
    monkeypatch.setattr(f, 'request', reject_ext)
    assert m._upload_glob(d, ['overfit*.json'], 'data')[0] == 1
    f.never_commit = True
    assert upload(m)[0] == 0
    safe = m.SafeWriter(m.__dict__)
    rows = [safe.load(k) for k in (*m._OVERFIT_PAIR, KEY)]
    f.never_commit = False
    monkeypatch.setenv('R2_PROTECTED_HISTORY_KEEP', '0')
    for i in range(4):
        assert upload(m, str(i).encode(), 'data/auto_trade_steps.json')[0] == 1
    for row in rows:
        assert (safe.root / 'payloads' / row['sha256']).exists()
        assert (safe.root / 'history' / (row['write_id'] + '.json')).exists()
    assert (safe.root / 'pairs' / (rows[0]['pair_id'] + '.json')).exists()


@pytest.mark.parametrize('failure', ['manifest', 'unlink', 'corrupt'])
def test_gc_faults_never_delete_referenced_payload(client, monkeypatch, failure):
    import r2_safe_write
    m, _ = client
    assert upload(m)[0] == 1
    safe = m.SafeWriter(m.__dict__); row = safe.load(KEY)
    anchor = safe.root / 'payloads' / row['sha256']
    orphan = safe.root / 'payloads' / ('a' * 64); orphan.write_bytes(b'orphan')
    original = r2_safe_write.durable
    if failure == 'manifest':
        def full(path, body):
            if path.name == 'gc-manifest.json': raise OSError(28, 'ENOSPC')
            original(path, body)
        monkeypatch.setattr(r2_safe_write, 'durable', full)
    elif failure == 'unlink':
        original_unlink = Path.unlink
        def crashed(path, *a, **kw):
            if path == orphan: raise SystemExit('crash during GC')
            return original_unlink(path, *a, **kw)
        monkeypatch.setattr(Path, 'unlink', crashed)
    else:
        safe.path(KEY).write_text('{bad json')
    with pytest.raises((OSError, SystemExit, ValueError)):
        with safe.storage_lock(): safe.gc()
    assert anchor.read_bytes() == b'new'
    assert orphan.exists()  # 拒绝删除或可重入，未抢先删锚点。


def test_absolute_deadline_blocks_before_new_io(client):
    m, f = client
    m._WORK_DEADLINE = 1
    with pytest.raises(m.WorkBudgetExceeded): upload(m)
    assert not f.calls


def test_verify_repair_uses_same_protected_write(client, monkeypatch):
    m, f = client
    p = m.STATIC_DIR / KEY; p.parent.mkdir(); p.write_bytes(b'new')
    f.put('public', KEY, b'old'); f.fail_backup = True
    monkeypatch.setattr(m, '_R2_CHANNELS', [{'label': 'fixture', 'local_dir': lambda: p.parent,
        'patterns': ['*.json'], 'r2_prefix': 'data', 'state_name': None}])
    monkeypatch.setattr(m, '_load_standalone_keys', lambda **kw: ({KEY}, 'ok'))
    with pytest.raises(SystemExit): m.cmd_verify_r2()
    assert f.objects['public', KEY][0] == b'old'


def test_backup_versions_do_not_replace_prior_same_day(client):
    m, f = client
    f.put('public', KEY, b'old')
    assert upload(m, b'new')[0] == 1
    assert upload(m, b'newer')[0] == 1
    versions = [body for (bucket, key), (body, _) in f.objects.items() if bucket == 'backup']
    assert sorted(versions) == [b'new', b'old']


def test_get_forbidden_is_not_true_absence(client, monkeypatch):
    m, f = client
    original = f.request
    def forbidden(method, *args):
        if method == 'GET': return 403, b'forbidden', {}
        return original(method, *args)
    monkeypatch.setattr(f, 'request', forbidden)
    assert upload(m)[0] == 0
    assert not public_writes(f)


def test_fixed_payload_despite_local_change_during_backup(client, monkeypatch):
    m, f = client
    f.put('public', KEY, b'old')
    original = f.request
    def mutate(method, uri, body, headers):
        if method == 'GET' and uri.startswith('/backup/'):
            (m.STATIC_DIR / KEY).write_bytes(b'changed after prepare')
        return original(method, uri, body, headers)
    monkeypatch.setattr(f, 'request', mutate)
    assert upload(m)[0] == 1
    assert f.objects['public', KEY][0] == b'new'


def test_enospc_after_remote_success_preserves_unknown_journal(client, monkeypatch):
    m, f = client
    original = m.SafeWriter.save
    def disk_full(self, row):
        if row['confirmed']: raise OSError(28, 'full')
        return original(self, row)
    monkeypatch.setattr(m.SafeWriter, 'save', disk_full)
    assert upload(m)[0] == 0
    assert m.SafeWriter(m.__dict__).load(KEY)['state'] == 'unknown'
    monkeypatch.setattr(m.SafeWriter, 'save', original)
    count = len(public_writes(f))
    assert upload(m)[0] == 1
    assert len(public_writes(f)) == count


def test_incremental_purge_failure_reentry_keeps_state_honest(client, monkeypatch):
    m, f = client
    p = m.STATIC_DIR / KEY; p.parent.mkdir(); p.write_bytes(b'new')
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: False)
    with pytest.raises(SystemExit):
        m._incremental_upload(p.parent, ['*.json'], 'data', '.r2_test_state.json', checkpoint_every=1)
    assert not (m.STATIC_DIR.parent / 'data/.r2_test_state.json').exists()
    count = len(public_writes(f))
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: True)
    assert m._incremental_upload(p.parent, ['*.json'], 'data', '.r2_test_state.json', checkpoint_every=1)[0] == 1
    assert len(public_writes(f)) == count
    assert (m.STATIC_DIR.parent / 'data/.r2_test_state.json').exists()


def test_pair_partial_failure_and_recovery_retains_original_pair(client, monkeypatch):
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    for key in m._OVERFIT_PAIR:
        (m.STATIC_DIR / key).write_bytes(b'{"generated_at":"new","publication_run_id":"new-run"}')
        f.put('public', key, b'{"generated_at":"old"}')
    original = f.request
    def reject_ext(method, uri, body, headers):
        if method == 'PUT' and uri == '/public/' + m._OVERFIT_PAIR[1]:
            return 409, b'locked', {}
        return original(method, uri, body, headers)
    monkeypatch.setattr(f, 'request', reject_ext)
    assert m._upload_glob(d, ['overfit*.json'], 'data')[0] == 1
    rows = [m.SafeWriter(m.__dict__).load(k) for k in m._OVERFIT_PAIR]
    pair_id = rows[0]['pair_id']
    assert rows[0]['confirmed'] and rows[1]['state'] == 'failed'
    monkeypatch.setattr(f, 'request', original)
    assert m._upload_glob(d, ['overfit*.json'], 'data')[0] == 2
    assert {m.SafeWriter(m.__dict__).load(k)['pair_id'] for k in m._OVERFIT_PAIR} == {pair_id}


def test_publication_requires_same_run_proof_and_remote_hash(client, monkeypatch):
    import delivery_evidence
    m, f = client
    key = 'data/overview.json'; payload = b'{"v":1}'
    proof = m.STATIC_DIR.parent / 'proof.json'
    proof.write_text(json.dumps({'version': 1, 'run_id': 'fixture-run', 'static_dir': str(m.STATIC_DIR.resolve()),
        'outputs': {'overview.json': {'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}}}))
    proof.chmod(0o600)
    monkeypatch.setenv('R2_EXPORT_PROOF_PATH', str(proof)); monkeypatch.setenv('R2_EXPORT_RUN_ID', 'fixture-run')
    calls = []
    monkeypatch.setattr(delivery_evidence, 'record_publication', lambda **kw: calls.append(kw), raising=False)
    assert upload(m, payload, key)[0] == 1
    assert [c['confirmed'] for c in calls] == [False, True]
    assert calls[1:] == [{'data_root': m.STATIC_DIR.parent, 'run_id': 'fixture-run', 'object_name': 'overview.json',
        'sha256': hashlib.sha256(payload).hexdigest(), 'size': len(payload), 'confirmed': True}]
    calls.clear(); monkeypatch.setenv('R2_EXPORT_RUN_ID', 'wrong-run')
    assert upload(m, payload, key)[0] == 1
    assert not calls


def test_two_prepared_clients_one_cas_wins(client):
    m, f = client
    f.put('public', KEY, b'old')
    a = m.SafeWriter(m.__dict__)
    b = m.SafeWriter(m.__dict__); b.root = a.root.parent / 'second-client'
    first = a.prepare(KEY, b'first'); second = b.prepare(KEY, b'second')
    a.commit(first, b'first')
    with pytest.raises(m.UnsafeWrite, match='412'): b.commit(second, b'second')
    assert f.objects['public', KEY][0] == b'first'


def test_multipart_competing_write_before_complete_is_not_overwritten(client):
    m, f = client
    m._MULTIPART_THRESHOLD = 2; f.race = True
    assert upload(m)[0] == 0
    assert f.objects['public', KEY][0] == b'concurrent'
    complete = [c for c in f.calls if c[0] == 'POST' and c[1] == 'public' and 'uploadId' in c[3]]
    assert len(complete) == 1 and complete[0][4]['if-none-match'] == '*'
    assert not m.SafeWriter(m.__dict__).load(KEY)['confirmed']


def test_recovery_command_replays_only_original_conditional_bytes(client):
    m, f = client
    f.never_commit = True
    assert upload(m)[0] == 0
    first = public_writes(f)[0]
    f.never_commit = False
    m.cmd_recover_protected()
    assert public_writes(f)[1][4]['x-amz-meta-write-id'] == first[4]['x-amz-meta-write-id']
    assert public_writes(f)[1][4]['if-none-match'] == '*'
    assert m.SafeWriter(m.__dict__).load(KEY)['confirmed']


def _seed_recovery_journals(m, fake, pair, pending_purge=False):
    keys = m._OVERFIT_PAIR if pair else (KEY,)
    directory = m.STATIC_DIR / 'data'
    directory.mkdir(exist_ok=True)
    for key in keys:
        (m.STATIC_DIR / key).write_bytes(
            b'{"generated_at":"same-minute","publication_run_id":"recovery-test"}')
    fake.never_commit = not pending_purge
    assert m._upload_glob(directory, [Path(k).name for k in keys], 'data')[0] == 0
    safe = m.SafeWriter(m.__dict__)
    rows = {key: safe.load(key) for key in keys}
    assert all(row['state'] == ('confirmed' if pending_purge else 'unknown')
               for row in rows.values())
    fake.never_commit = False
    fake.calls.clear()
    return safe, rows


@pytest.mark.parametrize('pair', [False, True], ids=['key', 'pair'])
@pytest.mark.parametrize('pending_purge', [False, True], ids=['unknown', 'pending-purge'])
def test_recovery_lock_open_failure_has_no_effects(client, monkeypatch, tmp_path, pair, pending_purge):
    m, fake = client
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: False)
    safe, rows = _seed_recovery_journals(m, fake, pair, pending_purge)
    before = {p.relative_to(safe.root): p.read_bytes() for p in safe.root.rglob('*') if p.is_file()}
    loads, purges, releases, lock_keys = [], [], [], []
    real_load, real_release = m.SafeWriter.load, m._release_r2_upload_lock
    def unavailable_path(bucket_key):
        lock_keys.append(bucket_key)
        return tmp_path / 'absent-parent' / 'key.lock'
    def load(self, key):
        loads.append(key)
        return real_load(self, key)
    def release(fd):
        releases.append(fd)
        return real_release(fd)
    monkeypatch.setattr(m._rlp, 'key_lock_path', unavailable_path)
    monkeypatch.setattr(m.SafeWriter, 'load', load)
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: purges.append(a) or True)
    monkeypatch.setattr(m, '_release_r2_upload_lock', release)
    # Real os.open fails; do not replace the acquisition helper with a fake None.
    with pytest.raises(SystemExit) as exc:
        m.cmd_recover_protected()
    assert exc.value.code == 1
    assert not loads and not fake.calls and not purges and not releases
    assert lock_keys == [f'public/{"overfit-pair" if pair else KEY}'] * len(rows)
    assert before == {p.relative_to(safe.root): p.read_bytes() for p in safe.root.rglob('*') if p.is_file()}


def test_recovery_failed_key_continues_other_key(client, monkeypatch, tmp_path):
    m, fake = client
    safe, _ = _seed_recovery_journals(m, fake, False)
    other = 'data/auto_trade_steps.json'
    fake.never_commit = True
    assert upload(m, b'other', other)[0] == 0
    fake.never_commit = False
    fake.calls.clear()
    # Ensure the failed key is first, so the successful key proves continuation.
    first = json.loads(sorted(p for p in safe.root.glob('*.json') if p.name != 'gc-manifest.json')[0].read_text())['key']
    second = other if first == KEY else KEY
    unchanged = safe.path(first).read_bytes()
    lock_path = m._rlp.key_lock_path
    monkeypatch.setattr(m._rlp, 'key_lock_path', lambda key:
        tmp_path / 'absent-parent' / 'key.lock' if key == f'public/{first}' else lock_path(key))
    purges = []
    monkeypatch.setattr(m, 'purge_cache', lambda keys, **kw: purges.append(keys) or True)
    with pytest.raises(SystemExit) as exc:
        m.cmd_recover_protected()
    assert exc.value.code == 1
    assert safe.path(first).read_bytes() == unchanged
    assert safe.load(first)['state'] == 'unknown'
    assert safe.load(second)['confirmed']
    assert {call[2] for call in fake.calls} == {second}
    assert len(public_writes(fake)) == 1 and purges
    assert all(first not in keys for keys in purges)


@pytest.mark.parametrize('pair', [False, True], ids=['key', 'pair'])
@pytest.mark.parametrize('commit', [False, True], ids=['still-unknown', 'confirmed'])
def test_recovery_obeys_real_flock_and_releases_valid_locks(client, monkeypatch, pair, commit):
    import fcntl
    m, fake = client
    safe, rows = _seed_recovery_journals(m, fake, pair)
    before = {p.relative_to(safe.root): p.read_bytes() for p in safe.root.rglob('*') if p.is_file()}
    lock_path = m._rlp.key_lock_path(f'public/{"overfit-pair" if pair else KEY}')
    holder = m._acquire_r2_upload_lock(timeout=0, lock_path_override=lock_path)
    assert holder is not None
    purges, loads = [], []
    real_load = m.SafeWriter.load
    def load(self, key):
        loads.append(key)
        return real_load(self, key)
    monkeypatch.setattr(m.SafeWriter, 'load', load)
    acquire = m._acquire_r2_upload_lock
    monkeypatch.setattr(m, '_acquire_r2_upload_lock', lambda **kw: acquire(**{**kw, 'timeout': 0}))
    monkeypatch.setattr(m, 'probe_lock_holder', lambda *a: '')
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: purges.append(a) or True)
    try:
        with pytest.raises(SystemExit) as exc:
            m.cmd_recover_protected()
        assert exc.value.code == 1
        assert not loads and not fake.calls and not purges
        assert before == {p.relative_to(safe.root): p.read_bytes() for p in safe.root.rglob('*') if p.is_file()}
    finally:
        m._release_r2_upload_lock(holder)
    # Once available, the lock must be released on both success and failed replay.
    fake.never_commit = not commit
    if commit:
        m.cmd_recover_protected()
    else:
        with pytest.raises(SystemExit) as exc:
            m.cmd_recover_protected()
        assert exc.value.code == 1
    for key, original in rows.items():
        current = safe.load(key)
        assert current['state'] == ('confirmed' if commit else 'unknown')
        assert current['confirmed'] == commit and current['write_id'] == original['write_id']
    assert len(public_writes(fake)) == len(rows) and bool(purges) == commit
    with lock_path.open('a+b') as contender:
        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(contender, fcntl.LOCK_UN)


def test_isolated_probe_real_client_fake_transport_end_to_end(client, tmp_path):
    import r2_isolated_probe as probe_module
    m, f = client
    plan = probe_module.make_plan('public')
    probe = probe_module.Probe(m, tmp_path / 'probe.json', plan)
    probe.save(); probe.run()
    assert plan['status'] == 'passed'
    assert plan['results']['same_condition_two_writers'] == [200, 412]
    assert plan['results']['multipart_final_complete'] == [412, 200]
    assert plan['results']['discarded_response_original_write_id'] is True
    assert [r['status'] for r in plan['complete_requests']] == [412, 200]
    assert all('if-match' in r['conditions'] for r in plan['complete_requests'])
    assert all(k.startswith(plan['prefix']) for _, _, k, _, _ in f.calls)
    assert all(not m._protected_key(k) for k in plan['objects'])
    # 清理不盲删已变化版本；所有对象都在逐对象归属清单中。
    foreign = plan['prefix'] + 'backup.bin'
    f.put('public', foreign, b'foreign', {'x-amz-meta-write-id': 'foreign'})
    cleanup = probe.cleanup()
    assert cleanup[foreign] == 'UNKNOWN-retained'
    assert plan['execution_limits'] == {'budget':180,'request_timeout':25}
    assert plan['cleanup_limits'] == {'budget':180,'request_timeout':25}
    deletes = [c for c in f.calls if c[0] == 'DELETE']
    assert deletes
    assert all({'key': c[2], 'upload_id': c[3]['uploadId'][0]} in plan['multipart_uploads'] for c in deletes)
    assert all('uploadId' in c[3] for c in deletes)  # Never DeleteObject.
    with pytest.raises(ValueError): probe.run()


@pytest.mark.parametrize('budget,request_timeout', [(0,25),(601,25),(180,121),(10,25)])
def test_probe_limits_are_bounded(client, tmp_path, budget, request_timeout):
    import r2_isolated_probe as probe_module
    m, _ = client
    with pytest.raises(ValueError):
        probe_module.Probe(m, tmp_path/'probe.json', probe_module.make_plan('public'),
                           budget=budget, request_timeout=request_timeout)


def test_probe_rejects_outside_prefix_and_unknown_deletes(client, tmp_path):
    import r2_isolated_probe as probe_module
    m, f = client
    plan = probe_module.make_plan('public')
    probe = probe_module.Probe(m, tmp_path / 'probe.json', plan)
    with pytest.raises(ValueError): probe.request('PUT', KEY, payload=b'bad')
    with pytest.raises(ValueError): probe.request('DELETE', plan['prefix'] + 'cas.bin')
    with pytest.raises(ValueError): probe.request('GET', plan['prefix'] + 'cas.bin', bucket='other')
    with pytest.raises(ValueError): probe.request('DELETE', plan['prefix'] + 'cas.bin', query='uploadId=unknown')
    assert not f.calls


def test_probe_dry_plan_unique_and_has_no_client_import(client, tmp_path, monkeypatch):
    import r2_isolated_probe as probe_module
    m, f = client
    first = probe_module.make_plan('public'); second = probe_module.make_plan('public')
    assert first['prefix'] != second['prefix']
    assert len(first['objects']) == 4
    assert max(e['max_bytes'] for e in first['objects'].values()) == 5 * 1024**2 + 31
    monkeypatch.setattr(probe_module.importlib, 'import_module', lambda *a: pytest.fail('dry plan imported client'))
    # CLI path检查要求/tmp；这里只调用纯计划函数，不操作用户运行树。
    probe_module.validate(first)
    first['objects'][KEY] = {}
    with pytest.raises(ValueError): probe_module.validate(first)
    assert not f.calls


def test_purge_checks_shared_absolute_budget(client, monkeypatch):
    m, f = client
    # 执行真实 purge 函数而不是成功桩；过期时不发请求、不发通知。
    node = next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == 'purge_cache')
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), m.__dict__)
    monkeypatch.setenv('PURGE_SECRET', 'fake')
    m._WORK_DEADLINE = 1
    with pytest.raises(m.WorkBudgetExceeded): m.purge_cache([KEY])
    assert not f.calls


def test_turnover_small_large_share_ops_run_and_existing_proof(client, monkeypatch):
    import delivery_evidence
    m, f = client
    d = m.STATIC_DIR / 'data'; d.mkdir()
    names = sum(m._TURNOVER_UPLOAD_FILES.values(), ())
    outputs = {}
    for name in names:
        body = json.dumps({'name': name}).encode(); (d / name).write_bytes(body)
        outputs[name] = {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    proof = m.STATIC_DIR.parent / 'turnover-proof.json'
    proof.write_text(json.dumps({'version': 1, 'run_id': 'same-turnover',
                                'static_dir': str(m.STATIC_DIR.resolve()), 'outputs': outputs}))
    proof.chmod(0o600)
    monkeypatch.setenv('OPS_BUSINESS_RUN', 'same-turnover')
    monkeypatch.setenv('OPS_TURNOVER_PROOF', str(proof))
    monkeypatch.delenv('R2_EXPORT_RUN_ID', raising=False)
    calls = []
    monkeypatch.setattr(delivery_evidence, 'record_publication', lambda **kw: calls.append(kw), raising=False)
    monkeypatch.setattr(m, '_guard_upload_intraday', lambda: None)
    monkeypatch.setattr(m, '_backup_overwritten_keys', lambda *a, **k: (0, 0, 0, []))
    m.cmd_upload_turnover('small'); m.cmd_upload_turnover('large')
    done = [x for x in calls if x['confirmed']]
    assert {x['object_name'] for x in done} == set(names)
    assert {x['run_id'] for x in done} == {'same-turnover'}
    assert all(x['data_root'] == m.STATIC_DIR.parent for x in done)
    # 同run重入必须重新验证，即使增量state全命中，也不能仅借用旧确认。
    calls.clear(); m.cmd_upload_turnover('small')
    assert len([x for x in calls if x['confirmed']]) == len(m._TURNOVER_UPLOAD_FILES['small'])
    assert 'R2_EXPORT_RUN_ID' not in m.os.environ


def test_failed_publication_invalidates_same_run_success(client, monkeypatch):
    import delivery_evidence
    m, f = client
    key = 'data/overview.json'; payload = b'new'
    proof = m.STATIC_DIR.parent / 'proof.json'
    proof.write_text(json.dumps({'version': 1, 'run_id': 'same-run', 'static_dir': str(m.STATIC_DIR.resolve()),
        'outputs': {'overview.json': {'size': 3, 'sha256': hashlib.sha256(payload).hexdigest()}}}))
    proof.chmod(0o600)
    monkeypatch.setenv('R2_EXPORT_PROOF_PATH', str(proof)); monkeypatch.setenv('R2_EXPORT_RUN_ID', 'same-run')
    calls = []
    monkeypatch.setattr(delivery_evidence, 'record_publication', lambda **kw: calls.append(kw), raising=False)
    assert upload(m, payload, key)[0] == 1
    assert calls[-1]['confirmed']
    f.never_commit = True
    assert upload(m, payload, key)[0] == 0
    assert calls[-1]['confirmed'] is False


def test_streaming_get_rechecks_deadline_between_receives(client):
    m, f = client
    class Trickle:
        count = 0
        def getheader(self, name): return '3'
        def read(self, n=-1): raise AssertionError('must use bounded read1')
        def read1(self, n):
            self.count += 1
            m._WORK_DEADLINE = 1
            return b'n'
    m._WORK_DEADLINE = m.time.monotonic() + 5
    stream = Trickle()
    with pytest.raises(m.WorkBudgetExceeded): m._read_with_progress(stream, 'fixture')
    assert stream.count == 1


def test_streaming_put_rechecks_deadline_before_more_bytes(client):
    m, f = client
    stream = m._ProgressBody(b'new', 'fixture')
    assert stream.read(1) == b'n'
    m._WORK_DEADLINE = 1
    with pytest.raises(m.WorkBudgetExceeded): stream.read(1)


def test_nav_purge_proxy_failure_retained_until_both_routes_confirm(client, monkeypatch):
    m, f = client
    calls = []
    def purge(keys, cache_prefix='/'):
        calls.append(cache_prefix)
        return cache_prefix == '/'
    monkeypatch.setattr(m, 'purge_cache', purge)
    assert upload(m, key='nav_bucket/00.json')[0] == 0
    assert calls == ['/', '/r2/']
    assert m.SafeWriter(m.__dict__).load('nav_bucket/00.json')['pending_purge']
    count = len(public_writes(f))
    monkeypatch.setattr(m, 'purge_cache', lambda *a, **k: True)
    assert upload(m, key='nav_bucket/00.json')[0] == 1
    assert len(public_writes(f)) == count
