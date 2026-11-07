"""Deployment policy and GET-only verifier tests: no real HTTP or notifications."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('ops_deployment_verify', ROOT / 'ops/monitoring/verify_deployment.py')
v = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v)
NOW = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
HEADERS = {'cache-control': 'no-store, max-age=0', 'content-type': 'application/json'}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('REAL_NETWORK_FORBIDDEN')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    # Positive control before every production verifier call.
    with pytest.raises(AssertionError, match='REAL_NETWORK_FORBIDDEN'):
        socket.create_connection(('invalid.example', 443))


def state(status='ok', age=0, observed_age=0):
    stamp = lambda age: (NOW - timedelta(seconds=age)).isoformat()
    return {'schema_version': 1, 'server_time': stamp(0), 'collector_status': 'fresh',
            'latest': {'collected_at': stamp(age), 'checks': [{'id': 'fixture', 'status': status, 'observed_at': stamp(observed_age)}]},
            'counts': {s: int(s == status) for s in v.VALID_STATUSES}}


def package(tmp_path):
    install = tmp_path / 'ops/monitoring/install'
    canonical = tmp_path / 'docs/deploy/systemd-units-20260912.md'
    install.mkdir(parents=True)
    canonical.parent.mkdir(parents=True)
    text = ''
    for name in ('trade-ops-monitor.service', 'trade-ops-monitor.timer'):
        content = (ROOT / 'ops/monitoring/install' / name).read_text()
        (install / name).write_text(content)
        text += f'`{name}`:\n\n```ini\n{content}```\n\n'
    canonical.write_text(text)
    return tmp_path


def test_default_is_read_only_unknown_and_does_not_read_tokens(tmp_path, monkeypatch, capsys):
    root = package(tmp_path)
    monkeypatch.setattr(v, 'get_json', lambda *a, **k: pytest.fail('default network probe'))
    monkeypatch.setattr(v, 'read_private_token', lambda *a: pytest.fail('implicit credential read'))
    assert v.main(['--root', str(root)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'unknown' and report['verification_mode'] == 'local-static-only'
    assert all(c['status'] == 'unknown' for c in report['checks'] if c['id'].startswith('runtime.'))


@pytest.mark.parametrize('value', ['http://remote.example', 'https://x.example/path', 'https://u:secret@x.example',
                                    'https://x.example?token=x', 'https://x.example#token', 'https://x.example\n',
                                    'https://x.example:bad', 'https://x.example%2fother'])
def test_unsafe_origin_rejected(value):
    with pytest.raises(ValueError):
        v.origin_url(value)


def test_loopback_explicit_only():
    assert v.origin_url('http://127.0.0.1:8787', True) == 'http://127.0.0.1:8787'
    with pytest.raises(ValueError):
        v.origin_url('http://127.0.0.1:8787')
    with pytest.raises(ValueError):
        v.origin_url('http://remote.example', True)


def test_private_token_mode_owner_symlink_and_limit(tmp_path):
    token = tmp_path / 'bootstrap.token'
    token.write_text('fixture-only-secret\n')
    token.chmod(0o600)
    assert v.read_private_token(token) == 'fixture-only-secret'
    token.chmod(0o644)
    with pytest.raises(ValueError):
        v.read_private_token(token)
    token.chmod(0o600)
    link = tmp_path / 'link'
    link.symlink_to(token)
    with pytest.raises(OSError):
        v.read_private_token(link)
    token.write_text('x' * 4097)
    with pytest.raises(ValueError):
        v.read_private_token(token)


@pytest.mark.parametrize('status', ['ok', 'warning', 'critical', 'unknown'])
def test_snapshot_preserves_business_findings_and_unknown(status):
    assert v.snapshot_checks(state(status), NOW)[0]['status'] == status


@pytest.mark.parametrize('body', [None, {}, {'schema_version': 1, 'latest': None},
                                 {'schema_version': 1, 'latest': {}},
                                 {**state(), 'latest': {'collected_at': NOW.isoformat(), 'checks': []}}])
def test_no_evidence_never_green(body):
    assert v.snapshot_checks(body, NOW)[0]['status'] != 'ok'


def test_fresh_envelope_cannot_hide_stale_check_or_server_clock():
    assert v.snapshot_checks(state(observed_age=901), NOW)[0]['status'] == 'unknown'
    assert v.snapshot_checks(state(), NOW + timedelta(minutes=3))[0]['status'] == 'unknown'
    assert v.snapshot_checks(state(age=-121), NOW)[0]['status'] == 'critical'
    assert v.snapshot_checks(state(age=901), NOW)[0]['status'] == 'critical'
    body = state(age=901)
    body['collector_status'] = 'stale'
    assert v.snapshot_checks(body, NOW)[0]['status'] == 'warning'


def test_counts_mismatch_and_missing_observation_not_green():
    body = state()
    body['counts']['ok'] = 5
    assert v.snapshot_checks(body, NOW)[0]['status'] == 'critical'
    body = state()
    del body['latest']['checks'][0]['observed_at']
    assert v.snapshot_checks(body, NOW)[0]['status'] == 'unknown'


@pytest.mark.parametrize('code,status', [(200, 'critical'), (401, 'ok'), (403, 'ok'), (503, 'unknown'), (404, 'critical')])
def test_unauthenticated_gate(code, status):
    assert v.response_checks('state', (code, HEADERS, {}))[0]['status'] == status


def test_headers_errors_also_no_store_and_no_cors():
    assert v.response_checks('state', (403, {}, {}))[1]['status'] == 'critical'
    headers = dict(HEADERS, **{'access-control-allow-origin': '*'})
    assert v.response_checks('state', (403, headers, {}))[1]['status'] == 'critical'


def test_full_verifier_calls_only_fixed_reads_and_never_reports_secrets(tmp_path):
    calls = []
    def request(origin, endpoint, token):
        calls.append((endpoint, bool(token)))
        if not token:
            return 403, HEADERS, {}
        body = {'state': state(), 'history?limit=1': {'runs': []}, 'events?limit=1': {'events': []},
                'knowledge': {'schema_version': 1, 'baseline_code_ref': 'a' * 40, 'records': []},
                'incidents': {'incidents': []}}[endpoint]
        return 200, HEADERS, body
    report = v.verify(package(tmp_path), 'https://fixture.invalid', 'private-fixture-token', requester=request, now=NOW)
    assert calls == [('state', False)] + [(e, True) for e in v.ENDPOINTS]
    assert report['status'] == 'unknown'  # GETs cannot prove independent cron.
    assert 'private-fixture-token' not in json.dumps(report)
    assert 'fixture.invalid' not in json.dumps(report)


def test_transport_get_serialization_redirect_policy_and_bounded_body(monkeypatch):
    seen = []
    class Response:
        code = 200
        headers = HEADERS
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, maximum):
            assert maximum == v.MAX_RESPONSE_BYTES + 1
            return b'{"schema_version":1}'
    class Opener:
        def open(self, req, timeout):
            seen.append(req)
            assert timeout == 5
            return Response()
    def build(*handlers):
        assert any(isinstance(h, v.NoRedirect) for h in handlers)
        assert any(isinstance(h, v.urllib.request.ProxyHandler) and h.proxies == {} for h in handlers)
        return Opener()
    monkeypatch.setattr(v.urllib.request, 'build_opener', build)
    assert v.get_json('https://fixture.invalid', 'state', 'fixture-secret')[0] == 200
    assert seen[0].get_method() == 'GET' and seen[0].data is None
    assert seen[0].get_header('X-ops-admin-token') == 'fixture-secret'
    assert seen[0].get_header('Authorization') is None
    assert v.NoRedirect().redirect_request(None, None, 302, None, {}, 'https://elsewhere.invalid') is None
    with pytest.raises(ValueError):
        v.get_json('https://fixture.invalid', 'ingest', 'fixture-secret')


def test_network_failure_does_not_echo_sensitive_exception(tmp_path):
    def failure(*args):
        raise OSError('https://private.example?token=DO_NOT_PRINT')
    report = v.verify(package(tmp_path), 'https://fixture.invalid', 'DO_NOT_PRINT', requester=failure)
    assert report['status'] == 'unknown'
    assert 'DO_NOT_PRINT' not in json.dumps(report) and 'private.example' not in json.dumps(report)


def test_canonical_drift_is_critical(tmp_path):
    root = package(tmp_path)
    target = root / 'ops/monitoring/install/trade-ops-monitor.service'
    target.write_text(target.read_text().replace('MemoryMax=256M', 'MemoryMax=2G'))
    rows = v.package_checks(root)
    assert next(c for c in rows if c['id'] == 'canonical.trade-ops-monitor.service')['status'] == 'critical'


def test_actual_install_units_match_canonical_bytes():
    document = (ROOT / 'docs/deploy/systemd-units-20260912.md').read_text()
    for name in ('trade-ops-monitor.service', 'trade-ops-monitor.timer'):
        assert v.canonical_unit(document, name) == (ROOT / 'ops/monitoring/install' / name).read_text(), f'C canonical integration required: {name}'


def test_unit_constraints_separate_code_data_and_credentials():
    content = (ROOT / 'ops/monitoring/install/trade-ops-monitor.service').read_text()
    assert 'OPS_CODE_ROOT=/home/ubuntu/code/trade-data-signal' in content
    assert '/scripts/ops_monitor.py' in content and '--once' in content
    assert 'LoadCredential=ops_ingest_token:' in content and '--token-file %d/ops_ingest_token' in content
    assert 'EnvironmentFile=-' not in content and 'Restart=no' in content
    assert 'ReadWritePaths=/run/trade-ops-monitor' in content
    assert 'ProtectSystem=strict' in content and 'ProtectHome=read-only' in content
    assert 'PrivateNetwork=yes' not in content and 'ListenStream' not in content
    assert 'MemoryMax=256M' in content and 'CPUQuota=25%' in content


CHILD_GUARD = r'''
import builtins, http.client, io, multiprocessing, os, runpy, selectors, socket, ssl, subprocess, sys
from pathlib import Path
class Blocked(BaseException): pass
def deny(*a, **k): raise Blocked('SIDE_EFFECT_BLOCKED')
for obj, name in [(socket,'socket'),(socket,'create_connection'),(subprocess,'Popen'),(os,'system')]: setattr(obj,name,deny)
real_open, real_io = builtins.open, io.open
def guard(original):
    def opened(file, mode='r', *a, **k):
        if isinstance(file,(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(file))
            if p.name.startswith('.env') or any(c in mode for c in 'wax+') or p.suffix in ('.db','.sqlite'):
                raise Blocked('SIDE_EFFECT_BLOCKED')
        return original(file,mode,*a,**k)
    return opened
builtins.open,io.open=guard(real_open),guard(real_io)
for probe in (lambda: socket.socket(), lambda: subprocess.Popen(['false']), lambda: Path('/forbidden/.env').read_text(), lambda: Path('/forbidden/no-write').write_text('x')):
    try: probe()
    except Blocked: pass
    else: raise AssertionError('CHILD_POSITIVE_CONTROL_FAILED')
sys.path.insert(0,str(Path(sys.argv[1]).parent))
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
'''


def test_real_collector_help_and_missing_configuration_fail_closed(tmp_path):
    script = ROOT / 'scripts/ops_monitor.py'
    assert script.is_file(), 'B collector integration required'
    env = {'PATH': '/usr/bin:/bin', 'REPO': str(tmp_path), 'HOME': str(tmp_path),
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}
    base = [sys.executable, '-B', '-c', CHILD_GUARD, str(script)]
    help_run = subprocess.run(base + ['--help'], env=env, capture_output=True, text=True, timeout=10)
    assert help_run.returncode == 0, help_run.stderr
    for flag in ('--config', '--once', '--collect-only', '--token-file'):
        assert flag in help_run.stdout, flag
    missing = subprocess.run(base + ['--config', str(tmp_path / 'missing.json'), '--collect-only'],
                             env=env, capture_output=True, text=True, timeout=10)
    assert missing.returncode != 0
    assert 'SIDE_EFFECT_BLOCKED' not in missing.stderr and 'SIDE_EFFECT_BLOCKED' not in missing.stdout
    assert not list(tmp_path.rglob('*.json'))


def test_real_local_config_simulates_all_storage():
    config = v.parse_jsonc((ROOT / 'ops/monitoring/wrangler.local.jsonc').read_text())
    assert all(c['status'] == 'ok' for c in v.worker_config_checks(config, local=True))


def test_config_detects_database_aliasing_missing_cron_and_inline_secret():
    config = {'d1_databases': [
        {'binding': 'OPS_DB', 'database_id': '00000000-0000-0000-0000-000000000001', 'database_name': 'shared', 'migrations_dir': 'migrations'},
        {'binding': 'FUND_SCORE_DB', 'database_id': '00000000-0000-0000-0000-000000000001', 'database_name': 'shared'}],
        'triggers': {'crons': []}, 'vars': {'OPS_INGEST_TOKEN': 'never-print-fixture'}}
    rows = v.worker_config_checks(config)
    assert len([c for c in rows if c['status'] == 'critical']) == 3
    assert 'never-print-fixture' not in json.dumps(rows)


def test_jsonc_preserves_strings_and_trailing_commas():
    config = v.parse_jsonc('{ // ignore\n "url":"https://example.invalid/a//b", "text":",}", /* ok */ "list":[1,],}')
    assert config == {'url': 'https://example.invalid/a//b', 'text': ',}', 'list': [1]}


def test_missing_canonical_block_does_not_borrow_next_unit():
    text = '`trade-one.service`:\nmissing\n`trade-two.service`:\n```ini\n[Unit]\nDescription=two\n```\n'
    assert v.canonical_unit(text, 'trade-one.service') is None


def test_missing_historical_checks_are_unknown_not_count_mismatch():
    body = state()
    body['missing_checks'] = [{'id': 'previous', 'status': 'unknown'}]
    body['counts']['unknown'] = 1
    rows = v.snapshot_checks(body, NOW)
    assert v.overall(rows) == 'unknown'
    assert all(row['status'] != 'critical' for row in rows)


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"v":NaN}', '{"v":Infinity}'])
def test_verifier_jsonc_rejects_ambiguous_values(text):
    with pytest.raises(ValueError):
        v.parse_jsonc(text)


def test_relocated_candidate_paths_must_still_reference_real_sources(tmp_path):
    root = tmp_path / 'source'
    (root / 'worker').mkdir(parents=True)
    (root / 'worker/headers.js').write_text('// fixture')
    (root / 'static-site').mkdir()
    (root / 'ops/monitoring/migrations').mkdir(parents=True)
    candidate = tmp_path / 'private/wrangler.jsonc'
    candidate.parent.mkdir()
    config = {'main': 'worker/headers.js', 'assets': {'directory': 'static-site'},
              'd1_databases': [{'binding': 'OPS_DB', 'database_id': '00000000-0000-0000-0000-000000000001',
                               'database_name': 'dedicated', 'migrations_dir': str(root / 'ops/monitoring/migrations')}],
              'triggers': {'crons': ['*/5 * * * *']}}
    rows = v.worker_config_checks(config, config_path=candidate, source_root=root)
    assert next(c for c in rows if c['id'] == 'config.paths')['status'] == 'critical'
    config['main'] = str(root / 'worker/headers.js')
    config['assets']['directory'] = str(root / 'static-site')
    rows = v.worker_config_checks(config, config_path=candidate, source_root=root)
    assert all(c['status'] == 'ok' for c in rows)


def test_unreadable_local_units_are_unknown_not_false_green(tmp_path, monkeypatch):
    root = package(tmp_path)
    original = Path.read_text
    def unreadable(path, *args, **kwargs):
        if path.name == 'trade-ops-monitor.service':
            raise PermissionError('sensitive details not to display')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', unreadable)
    rows = v.package_checks(root)
    assert next(c for c in rows if c['id'] == 'package.trade-ops-monitor.service')['status'] == 'unknown'
    assert 'sensitive details' not in json.dumps(rows)


@pytest.mark.parametrize('scope,status', [('watchdog', 'ok'), ('all', 'warning'), ('invalid', 'critical')])
def test_notification_scope_defaults_to_watchdog_and_requires_explicit_review(scope, status):
    config = {'vars': {'OPS_ALERT_ENABLED': 'false', 'OPS_ALERT_SCOPE': scope}}
    rows = v.worker_config_checks(config)
    row = next(c for c in rows if c['id'] == 'config.alert-scope')
    assert row['status'] == status
    if scope == 'watchdog':
        assert 'existing chain' in row['summary']
    default = next(c for c in v.worker_config_checks({}) if c['id'] == 'config.alert-scope')
    assert default['status'] == 'ok'


def test_real_notification_opt_in_is_visible_and_local_mode_rejects_it():
    config = v.parse_jsonc((ROOT / 'ops/monitoring/wrangler.local.jsonc').read_text())
    config['vars']['OPS_ALERT_ENABLED'] = 'true'
    rows = v.worker_config_checks(config, local=True)
    assert next(c for c in rows if c['id'] == 'config.alert-enabled')['status'] == 'warning'
    assert next(c for c in rows if c['id'] == 'config.local')['status'] == 'critical'
