#!/usr/bin/env python3
"""SYNTHETIC end-to-end benefits smoke, no browser or production resources.

Run after npm ci:
    python3 ops/monitoring/tests/smoke_benefits_pipeline.py
Optional --report writes a private JSON result. All fixtures live below /tmp.
Actual backtest main/_build_outputs AST -> atomic writers -> run proof -> isolated
reader -> normalizer -> actual collector CLI -> full bundled Worker/Miniflare D1
-> private APIs. Synthetic evidence MUST NOT enter real benefit studies. The
local reader is not a CDN user. Today's date (possibly weekend) is explicitly a
synthetic calendar, not a claimed exchange session. No realized ROI is measured.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ops.monitoring import benefits
from scripts import delivery_evidence as producer
from scripts.tests.test_delivery_evidence_20261107 import build_hook_fixture, function_ast, receipt_pairs

NATIVE = 'backtest_publish_consume'
MARKET = 'market_signal_freeze_plan'
BACKUP = 'backup_isolated_restore'
INGEST = 'synthetic-ingest-benefits-pipeline'
ADMIN = 'synthetic-admin-benefits-pipeline'


def require(value, name):
    if not value:
        raise AssertionError(name)


def clean_env():
    # Do not inherit cloud tokens, proxy configuration or producer overrides.
    return {'PATH': os.defpath, 'TZ': 'UTC', 'LC_ALL': 'C', 'WRANGLER_SEND_METRICS': 'false',
            'CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV': 'false', 'CLOUDFLARE_INCLUDE_PROCESS_ENV': 'false'}


def run(command, *, env=None, timeout=25):
    result = subprocess.run(command, cwd=ROOT, env=env or clean_env(), capture_output=True, text=True, timeout=timeout)
    require(result.returncode == 0, 'local command failed: ' + Path(command[0]).name)
    return result.stdout


def private_json(path, obj):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, allow_nan=False) + '\n')
    path.chmod(0o600)


def wait_json(stream, process, timeout=40):
    stop = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(stream, selectors.EVENT_READ)
        while time.monotonic() < stop:
            if selector.select(min(0.2, stop - time.monotonic())):
                line = stream.readline()
                if not line:
                    raise RuntimeError('local runtime ended before response')
                try:
                    return json.loads(line)
                except ValueError:
                    continue
            if process.poll() is not None:
                raise RuntimeError('local runtime failed')
    raise TimeoutError('local runtime deadline')


@contextmanager
def runtime(base):
    node = shutil.which('node')
    require(node is not None and (ROOT / 'node_modules/miniflare').is_dir(), 'npm ci and Node required')
    with (base / 'runtime.stderr').open('w') as errors:
        process = subprocess.Popen([node, str(Path(__file__).with_name('benefits_pipeline_runtime.mjs')), str(base / 'runtime')],
                                   cwd=ROOT, env=clean_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=errors, text=True, bufsize=1, start_new_session=True)
        try:
            ready = wait_json(process.stdout, process)
            require(ready.get('ready') and ready.get('remote') is False, 'local runtime readiness')
            target = urlsplit(ready['origin'])
            require(target.scheme == 'http' and target.hostname == '127.0.0.1' and target.port >= 1024, 'loopback runtime required')
            yield ready['origin'], process
        finally:
            if process.poll() is None:
                try:
                    process.stdin.write('{"op":"stop"}\n'); process.stdin.flush()
                    process.wait(timeout=8)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=3)
            for stream in (process.stdin, process.stdout):
                stream.close()


def call(origin, path, *, method='GET', value=None, role='admin', extra_headers=None):
    target = urlsplit(origin)
    require(target.hostname == '127.0.0.1' and target.scheme == 'http' and path.startswith('/api/ops/'), 'loopback ops only')
    headers = {'Content-Type': 'application/json'}
    if role == 'admin':
        headers['X-Ops-Admin-Token'] = ADMIN
    elif role == 'ingest':
        headers['Authorization'] = 'Bearer ' + INGEST
    elif role == 'wrong':
        headers['X-Ops-Admin-Token'] = 'synthetic-wrong-admin'
    headers.update(extra_headers or {})
    raw = json.dumps(value).encode() if value is not None else None
    con = http.client.HTTPConnection(target.hostname, target.port, timeout=8)
    try:
        con.request(method, path, raw, headers)
        response = con.getresponse()
        body = response.read(2 * 1024 * 1024 + 1)
        require(len(body) <= 2 * 1024 * 1024, 'bounded API response')
        return response.status, dict(response.headers), json.loads(body)
    finally:
        con.close()


def market_hook(root, session):
    """Execute the original signal.store AST on a temporary SQLite DB.

    Existing history audit/notification collaborator is replaced by a synthetic
    no-op, so this deliberately remains weak/stage_only; no fabricated chain.
    """
    path = root / 'data/synthetic-signal.db'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE signal_daily(date,index_id,signal,reason,PRIMARY KEY(date,index_id,signal))')
    con.commit(); con.close()
    audit = types.ModuleType('app.history_audit')
    audit.today_ymd = lambda: session.replace('-', '')
    audit.snapshot_signal_daily_history = lambda *_: set()
    audit.audit_signal_daily_store = lambda *_: None
    ns = dict(__name__='synthetic_market', __package__='app.compute',
              __file__=str(root / 'app/compute/signals.py'), Path=Path,
              evidence_stage=producer.evidence_stage, capture_loaded=producer.capture_loaded,
              capture_event=producer.capture_event, capture_signal_visibility=producer.capture_signal_visibility,
              capture_connection=producer.capture_connection, get_conn=lambda: sqlite3.connect(path))
    function_ast('app/compute/signals.py', {'store'}, ns)
    with patch.dict(sys.modules, {'app.history_audit': audit}), patch.dict(os.environ, {'OPS_DELIVERY_EVIDENCE_ENABLED': '1'}), \
         patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), \
         patch.object(subprocess, 'run', side_effect=AssertionError('business command forbidden')):
        require(ns['store']([(session.replace('-', ''), 'synthetic_index', 'buy', 'synthetic input')]) == 1, 'actual market store')
    with sqlite3.connect(path) as con:
        require(con.execute('SELECT count(*) FROM signal_daily').fetchone()[0] == 1, 'market committed row')
    require(any(r['chain_id'] == MARKET for _, r in receipt_pairs(root)), 'market actual hook receipt')


def backup_hooks(base, root, session):
    """Actual capture/restore CLIs on synthetic DB/sidecars; offsite stays unknown."""
    source = base / 'backup-source'; source.mkdir()
    db = source / 'synthetic.db'
    with sqlite3.connect(db) as con:
        con.execute('CREATE TABLE signal_daily(date,index_id,signal,PRIMARY KEY(date,index_id,signal))')
        con.execute('INSERT INTO signal_daily VALUES(?,?,?)', (session.replace('-', ''), 'synthetic_index', 'buy'))
    key = session.replace('-', '') + '|synthetic_index|buy'
    freeze = source / 'freeze.json'
    freeze.write_text(json.dumps({key: {'code': 'SYNTHETIC_OLD', 'frozen_at': session + ' 12:00'}}))
    mapping = source / 'mapping.json'
    mapping.write_text(json.dumps({'synthetic_index': [{'code': 'SYNTHETIC_NEW', 'track_score': 99}]}))
    config = source / 'universe.yaml'; config.write_text('synthetic_universe: [synthetic_index]\n')
    rowsha = hashlib.sha256((json.dumps([session.replace('-', ''), 'synthetic_index', 'buy'], separators=(',', ':')) + '\n').encode()).hexdigest()
    policy = {'schema': 'trade-benefit-capture-v1', 'session_date': session, 'generation_id': 'synthetic-generation',
              'artifacts': [{'id': 'sentiment', 'kind': 'db', 'path': str(db),
                             'tables': {'signal_daily': {'min_rows': 1, 'date_column': 'date', 'max_date': session.replace('-', ''), 'rows_sha256': rowsha}}},
                            {'id': 'freeze', 'kind': 'freeze', 'path': str(freeze)},
                            {'id': 'mapping', 'kind': 'map', 'path': str(mapping)},
                            {'id': 'universe', 'kind': 'config', 'path': str(config)}],
              'business': {'db_id': 'sentiment', 'table': 'signal_daily', 'indexes': ['synthetic_index'],
                           'signals': ['buy', 'buy_aux'], 'start_date': session.replace('-', ''), 'cutoff_date': session.replace('-', ''),
                           'expected_selections': {key: 'SYNTHETIC_OLD'}}}
    for a in policy['artifacts']:
        a.update(generation_id=policy['generation_id'], as_of=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        if a['kind'] != 'db':
            a['sha256'] = hashlib.sha256(Path(a['path']).read_bytes()).hexdigest()
    policy_file = base / 'capture-policy.json'; private_json(policy_file, policy)
    env = dict(clean_env(), OPS_DELIVERY_EVIDENCE_ENABLED='1')
    limits = ['--max-bytes', '1048576', '--max-sets', '2', '--max-file-bytes', '524288',
              '--max-json-bytes', '65536', '--min-free-bytes', '1', '--timeout-seconds', '5']
    result = json.loads(run([sys.executable, str(ROOT / 'ops/monitoring/benefit_capture.py'), '--policy', str(policy_file),
                             '--export-root', str(base / 'exports'), '--data-root', str(root)] + limits, env=env))
    require(result['status'] == 'unknown' and result['receipt']['status'] == 'written', 'capture unknown remote boundary')
    manifests = list((base / 'exports').glob('*/manifest.json'))
    require(len(manifests) == 1, 'actual capture manifest')
    manifest = manifests[0]
    restored = json.loads(run([sys.executable, str(ROOT / 'ops/monitoring/benefit_restore.py'), '--manifest', str(manifest),
                               '--manifest-sha256', hashlib.sha256(manifest.read_bytes()).hexdigest(),
                               '--target', str(base / 'isolated-restore'), '--data-root', str(root)] + limits, env=env))
    require(restored['restore_status'] == 'validated' and restored['status'] == 'unknown', 'isolated restore not production success')
    require(restored['consumer_witness']['status'] == 'unknown', 'offsite/production consumer not invented')
    return {'capture_status': result['status'], 'local_restore_status': restored['restore_status'],
            'chain_status': restored['status'], 'offsite': 'unknown', 'production_consumer': 'unknown'}


def fixture(base):
    root = base / 'project'; root.mkdir()
    # No network or subprocess/notification can escape the native in-process hook.
    with patch.object(socket, 'create_connection', side_effect=AssertionError('network forbidden')), \
         patch.object(subprocess, 'run', side_effect=AssertionError('business command forbidden')):
        control, _, session, native_policy = build_hook_fixture(root)
    market_hook(root, session)
    backup = backup_hooks(base, root, session)
    # Reuse a structural required-set template, never manually emit strong facts.
    from ops.monitoring.tests.test_benefits import fixture as synthetic_control
    template, _ = synthetic_control()
    market = copy.deepcopy(template['sessions'][0]['chains'][MARKET])
    market.update(deadline_at=producer.utc_now(), batches=[MARKET + ':' + session])
    market['required'][0].update(object_id='signal_daily', inputs=['signal_daily'], outputs=['signal_daily_write_payload'])
    market['edges'][0]['from'] = ['signal', 'signal_daily']
    backup_policy = {'inventory_complete': True, 'inventory_id': 'synthetic-capture-inventory', 'code_sha': 'a'*40,
                     'config_sha': 'b'*64, 'deadline_at': producer.utc_now(), 'batches': [BACKUP + ':' + session],
                     'required': [{'stage': 'backup', 'object_id': 'backup_db_freeze_map_restore', 'inputs': ['synthetic_source'], 'outputs': ['capture_manifest']},
                                  {'stage': 'restore', 'object_id': 'backup_db_freeze_map_restore', 'inputs': ['capture_manifest'], 'outputs': ['isolated_selection'],
                                   'consumer_scope': 'production_offsite_reader'}],
                     'edges': [{'from': ['backup', 'backup_db_freeze_map_restore'], 'to': ['restore', 'backup_db_freeze_map_restore'], 'object_id': 'capture_manifest'}]}
    control['calendar']['source_ref'] = 'synthetic-calendar-including-possible-weekend-not-exchange'
    control['sessions'] = [{'date': session, 'chains': {NATIVE: native_policy, MARKET: market, BACKUP: backup_policy}}]
    benefits.validate_control(control)
    private_json(root / benefits.CONTROL, control)
    # Explicit operational fixture sources. These numbers never become outcomes.
    ledger = root / 'data/alerts/alert_ledger.jsonl'; ledger.parent.mkdir()
    ledger.write_text('{"synthetic":true,"status":"not_a_delivery"}\n')
    private_json(root / 'static-site/data/schedule_stats.json', [])
    (root / 'empty-code').mkdir()
    return root, control, session, backup


def collector(base, root, origin, label):
    out = base / ('collector-' + label)
    token = base / 'fake-ingest-token'
    token.write_text(INGEST); token.chmod(0o600)
    config = {'collector_id': 'synthetic-pipeline', 'code_root': str(root / 'empty-code'), 'data_root': str(root),
              'output_dir': str(out), 'ingest_url': origin + '/api/ops/ingest', 'secret_file': str(token),
              'benefits_enabled': True, 'total_timeout_seconds': 20}
    path = base / ('collector-' + label + '.json'); private_json(path, config)
    stdout = run([sys.executable, str(ROOT / 'scripts/ops_monitor.py'), '--config', str(path), '--once', '--test-local-http'])
    require(json.loads(stdout)['delivery_ok'] is True, 'actual collector CLI accepted by actual local Worker')
    snapshot = json.loads((out / 'snapshot.json').read_text())
    local = sqlite3.connect(out / 'benefits.sqlite3')
    try:
        records = [json.loads(row[0]) for row in local.execute('SELECT payload FROM observations')]
    finally:
        local.close()
    return snapshot, {r['evidence']['chain_id']: r for r in records}


def assert_no_leaks(payload, base):
    raw = json.dumps(payload, sort_keys=True)
    for forbidden in (str(base), INGEST, ADMIN, 'resolved_path', 'consumer_witness', 'source_receipts', 'receipt_proofs'):
        require(forbidden not in raw, 'private path or detail leaked through wire/API')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    checks = []
    def check(name, truth):
        require(truth, name); checks.append(name)
    report = {'measurement_kind': 'synthetic', 'real_benefit_claim': False, 'realized_roi': None,
              'consumer_scope': 'isolated_local_reader', 'cdn_user_consumption': 'not_proven',
              'calendar': 'synthetic_declared_date_may_be_weekend_not_actual_exchange_session',
              'checks': checks, 'production_actions': 0}
    try:
        with tempfile.TemporaryDirectory(prefix='synthetic-benefits-pipeline-', dir=Path('/tmp').resolve()) as temp:
            base = Path(temp).resolve()
            root, control, session, backup = fixture(base)
            report['backup'] = backup
            native_receipts = [(h, r) for h, r in receipt_pairs(root) if r['chain_id'] == NATIVE]
            now = datetime.now(timezone.utc)
            local = benefits.normalize(control, native_receipts, NATIVE, session, now)
            check('actual_native_hook_normalizer_positive', local['evidence']['success'] == 1)
            missing = [(h, r) for h, r in native_receipts if r['stage'] != 'consumer']
            check('actual_native_missing_consumer_negative', benefits.normalize(control, missing, NATIVE, session, now)['evidence']['unknown'] == 1)
            with runtime(base) as (origin, process):
                for role in (None, 'wrong', 'ingest'):
                    check('private_benefits_denies_' + str(role), call(origin, '/api/ops/benefits', role=role)[0] in (401, 403))
                snapshot, normalized = collector(base, root, origin, 'complete')
                check('three_chains_normalized', set(normalized) == set(benefits.CHAINS))
                check('native_positive_survives_actual_collector', normalized[NATIVE]['evidence']['success'] == 1)
                check('market_hook_missing_chain_remains_unknown', normalized[MARKET]['evidence']['unknown'] == 1)
                check('backup_actual_capture_restore_remains_unknown', normalized[BACKUP]['evidence']['unknown'] == 1)
                transported = [c for c in snapshot['checks'] if c['id'].startswith('benefit:')]
                check('three_chains_transported_as_synthetic', len(transported) == 3 and all(c['evidence']['record_kind'] == 'delivery_v1' and c['evidence']['measurement_kind'] == 'synthetic' and 'attempt_id' not in c['evidence'] and len(c['evidence']) == 20 and c['status'] == 'unknown' for c in transported))
                assert_no_leaks(snapshot, base)
                status, headers, view = call(origin, '/api/ops/benefits')
                check('private_benefits_configured_not_ready', status == 200 and view['configured'] and view['status'] == 'not_ready' and view['real_benefit_claim'] is False)
                check('all_API_records_explicitly_synthetic', len(view['records']) == 3 and all(r.get('measurement_kind') == 'synthetic' for r in view['records']) and view['studies'] == [])
                check('private_api_no_store', 'no-store' in headers.get('Cache-Control', ''))
                assert_no_leaks(view, base)
                status, _, state = call(origin, '/api/ops/state')
                diagnostic = [c for c in state['latest']['checks'] if c['id'].startswith('benefit:')]
                check('actual_D1_ops_diagnostics_visible_three_chains', status == 200 and len(diagnostic) == 3 and all(c['status'] == 'unknown' for c in diagnostic))
                assert_no_leaks(state, base)
                # Repeat immutable snapshot, then a genuinely later resample of the
                # same receipts. Neither can manufacture real benefit audit rows.
                before = call(origin, '/api/ops/events')[2]['events']
                check('same_snapshot_replay_accepted', call(origin, '/api/ops/ingest', method='POST', value=snapshot, role='ingest')[0] == 200)
                again, _ = collector(base, root, origin, 'repeat')
                repeated = [c for c in again['checks'] if c['id'].startswith('benefit:')]
                check('same_receipt_proof_stable_across_resampling', {c['id']: c['evidence']['proof_sha'] for c in transported} == {c['id']: c['evidence']['proof_sha'] for c in repeated})
                # Remove only temporary test consumer receipt; no historical success
                # is fabricated or revoked. The new local evaluation must be unknown.
                consumer = next(p for p in (root / benefits.RECEIPTS / session / NATIVE).glob('*.json') if producer.read_receipt(p)['stage'] == 'consumer')
                consumer.unlink()
                negative, missing_records = collector(base, root, origin, 'missing-consumer')
                check('missing_consumer_actual_CLI_unknown', missing_records[NATIVE]['evidence']['unknown'] == 1)
                check('old_snapshot_replay_accepted', call(origin, '/api/ops/ingest', method='POST', value=snapshot, role='ingest')[0] == 200)
                state = call(origin, '/api/ops/state')[2]
                check('old_snapshot_cannot_replace_new_head', state['latest']['snapshot_id'] == negative['snapshot_id'])
                later = call(origin, '/api/ops/events')[2]['events']
                check('replays_do_not_create_business_recovery', not any(e.get('check_id', '').startswith('benefit:') and e.get('kind') == 'recovery' for e in later))
                status, _, audit = call(origin, '/api/ops/benefits/audit')
                check('benefit_audit_kind_preserved', status == 200 and len(audit['records']) >= 3 and all(r['record'].get('measurement_kind') == 'synthetic' for r in audit['records']))
                for payload in (state, audit, later):
                    assert_no_leaks(payload, base)
                # An adversarial attested declaration intentionally labels a
                # study real while reusing this synthetic sample's IDs. Its day
                # must remain empty; never relabel the actual collector sample.
                rollout = {'effective_at': (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                           'evidence_ref': 'synthetic-adversarial-declaration-not-production',
                           'before_code_sha': 'a'*40, 'after_code_sha': 'a'*40,
                           'before_config_sha256': 'b'*64, 'after_config_sha256': 'b'*64}
                period = {k: control[k] for k in ('contract_id', 'caliber_id', 'population_id', 'schedule_id', 'exclusion_policy_id', 'normalizer_sha', 'calendar')}
                period.update(schema_version='delivery-benefits-v1', measurement_kind='real', metric_id='chain_delivery_success',
                              code_sha='a'*40, config_sha256='b'*64, rollout=rollout,
                              as_of=producer.utc_now(), confounders=[], days=[])
                proof = next(c['evidence']['proof_sha'] for c in transported if c['evidence']['chain_id'] == NATIVE)
                study = {'expected_revision': 0, 'study_id': 'synthetic-adversarial-real-study', 'chain_id': NATIVE,
                         'first_sample_proof_sha': proof, 'before': period, 'after': copy.deepcopy(period)}
                status, _, registration = call(origin, '/api/ops/benefits/studies', method='POST', value=study,
                                                extra_headers={'Origin': origin, 'X-Ops-Intent': 'update'})
                check('adversarial_real_study_registered_as_attestation', status == 200)
                view = call(origin, '/api/ops/benefits')[2]
                real_study = next(s for s in view['studies'] if s['study_id'] == study['study_id'])
                check('synthetic_not_a_real_study_natural_sample', real_study['comparison']['status'] == 'not_ready'
                      and real_study['after']['days'][0]['inventory_complete'] is False
                      and real_study['after']['days'][0]['success'] is None
                      and real_study['evidence_strength'] == 'attested')
                # Replay an old/omitted-kind protocol envelope as hostile input.
                # This is a transport negative, not a manually emitted hook proof.
                legacy = copy.deepcopy(snapshot)
                legacy.update(snapshot_id=str(uuid.uuid4()), collected_at=producer.utc_now().replace('+00:00', 'Z'))
                for c in legacy['checks']:
                    if c['id'].startswith('benefit:'):
                        c['evidence'].pop('measurement_kind')
                        c['observed_at'] = producer.utc_now().replace('+00:00', 'Z')
                        c['evidence']['evaluated_at'] = c['observed_at']
                        c['status'] = 'ok'
                legacy_status, _, legacy_ack = call(origin, '/api/ops/ingest', method='POST', value=legacy, role='ingest')
                check('missing_kind_input_accepted_only_as_unknown_' + str(legacy_status) + '_' + str(legacy_ack.get('error', '')), legacy_status == 200)
                view = call(origin, '/api/ops/benefits')[2]
                check('missing_kind_never_real', all(r.get('measurement_kind') in ('synthetic', 'unknown') for r in view['records']))
                latest = call(origin, '/api/ops/state')[2]
                check('missing_kind_cannot_go_green', all(c['status'] == 'unknown' for c in latest['latest']['checks'] if c['id'].startswith('benefit:')))
                real_study = next(s for s in view['studies'] if s['study_id'] == study['study_id'])
                check('legacy_missing_kind_cannot_fill_real_study', real_study['after']['days'][0]['inventory_complete'] is False
                      and real_study['after']['days'][0]['success'] is None)
                for payload in (view, latest, registration):
                    assert_no_leaks(payload, base)
                process.stdin.write('{"op":"stats"}\n'); process.stdin.flush()
                stats = wait_json(process.stdout, process, timeout=5)
                check('native_D1_contains_original_ops_runs', stats['counts']['ops_runs'] >= 3)
                check('native_D1_kind_isolation', all(r['kind'] in ('synthetic', 'unknown') for r in stats['kinds']) and not any(r['kind'] == 'real' for r in stats['kinds']))
                check('zero_external_requests', stats['external_requests'] == 0 and stats['remote'] is False)
                report['d1_counts'] = stats['counts']
        report['status'] = 'PASS'
    except Exception as error:
        # Test failures must not leak raw paths/token payloads through CLI logs.
        report.update(status='FAIL', error_kind=type(error).__name__, failed_check=str(error) if isinstance(error, AssertionError) else 'local_fixture_failed')
    report['checks_passed'] = len(checks)
    report['source_hashes'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in
                               ('ops/monitoring/tests/smoke_benefits_pipeline.py', 'ops/monitoring/tests/benefits_pipeline_runtime.mjs',
                                'scripts/ops_monitor.py', 'ops/monitoring/benefits.py', 'scripts/delivery_evidence.py', 'worker/ops_benefits.js')}
    if args.report:
        tmp = args.report.with_suffix(args.report.suffix + '.tmp')
        private_json(tmp, report); tmp.replace(args.report)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
