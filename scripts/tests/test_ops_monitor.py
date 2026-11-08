"""Offline collector regression tests; no business modules or real network."""
import contextlib
import builtins
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ops_monitor', ROOT / 'scripts/ops_monitor.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class FakeRunner:
    def __init__(self, rows, fail=False):
        self.names = [r['unit'] for r in rows]
        self.fail = fail
        self.calls = []

    def run(self, args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError('Bearer fake-private-value /home/private')
        names = self.names + [n.replace('.service', '.timer') for n in self.names]
        if args[1] == 'list-unit-files':
            return '\n'.join(n + ' enabled enabled' for n in names)
        blocks = []
        for name in names:
            if name.endswith('.timer'):
                blocks.append('\n'.join(['Id=' + name, 'LoadState=loaded', 'ActiveState=active',
                                         'SubState=waiting',
                                         'TimersCalendar={ OnCalendar=*-*-* 16:35:00 ; next_elapse=Sat 2026-11-07 16:35:00 CST }',
                                         'TimersCalendar={ OnCalendar=*-*-* 21:00:00 ; next_elapse=Sat 2026-11-07 21:00:00 CST }',
                                         'NextElapseUSecRealtime=Sat 2026-11-07 16:35:00 CST',
                                         'LastTriggerUSec=Fri 2026-11-06 21:00:00 CST']))
            else:
                blocks.append('\n'.join(['Id=' + name, 'LoadState=loaded', 'ActiveState=inactive',
                                         'SubState=dead', 'Type=oneshot', 'Result=success', 'ExecMainCode=1', 'ExecMainStatus=0',
                                         'ExecMainStartTimestamp=Fri 2026-11-06 21:00:00 CST',
                                         'ExecMainExitTimestamp=Fri 2026-11-06 21:02:00 CST']))
        return '\n\n'.join(blocks)


class ServiceStateRunner(FakeRunner):
    def __init__(self, rows, fields):
        super().__init__(rows)
        self.fields = fields

    def run(self, args):
        raw = super().run(args)
        if args[1] != 'show':
            return raw
        blocks = raw.split('\n\n')
        for i, block in enumerate(blocks):
            if block.startswith('Id=' + self.names[0] + '\n'):
                props = dict(line.split('=', 1) for line in block.splitlines())
                props.update(self.fields)
                blocks[i] = '\n'.join(key + '=' + str(value) for key, value in props.items())
        return '\n\n'.join(blocks)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.hits = []
        def deny(*a, **k):
            self.hits.append('network')
            raise AssertionError('network blocked')
        for obj, attr in ((socket.socket, 'connect'), (socket, 'create_connection'),
                          (socket, 'getaddrinfo')):
            self.stack.enter_context(patch.object(obj, attr, deny))
        with socket.socket() as sock, self.assertRaises(AssertionError):
            sock.connect(('127.0.0.1', 9))
        self.hits.clear()
        self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ops-collector-')))
        self.code, self.data = self.temp / 'code', self.temp / 'data'
        (self.code / 'scripts').mkdir(parents=True)
        (self.data / 'static-site/data').mkdir(parents=True)
        (self.data / 'data/backups').mkdir(parents=True)
        self.source = (ROOT / 'scripts/gen_schedule_stats.py').read_text()
        (self.code / 'scripts/gen_schedule_stats.py').write_text(self.source)
        inv = self.code / 'docs/ops/architecture/inventory'
        inv.mkdir(parents=True)
        (inv / 'data_assets.json').write_text((ROOT / 'docs/ops/architecture/inventory/data_assets.json').read_text())
        self.rows = m.load_registry(self.code)
        self.runner = FakeRunner(self.rows)
        self.cfg = m.Settings(code_root=str(self.code), data_root=str(self.data), output_dir=str(self.temp / 'out'))
        schedule = [{'task': r['task'], 'last_exit': 0, 'unit_exit_source': 'systemd',
                     'log_anomaly': False, 'unit_missed': False} for r in self.rows if r['include']]
        (self.data / 'static-site/data/schedule_stats.json').write_text(json.dumps(schedule))
        (self.data / 'data/.r2_db_backup_state.json').write_text('{}')
        for family in ('sentiment', 'etf_national_team', 'stock_daily'):
            (self.data / f'data/backups/{family}_20261106_2100.db').write_bytes(b'fixture-not-a-real-backup')
        self.secret = self.temp / 'ingest.token'
        self.secret.write_text('fixture-token-0123456789012345')
        self.secret.chmod(0o600)

    def tearDown(self):
        self.assertEqual(self.hits, [])

    def collect(self, runner=None):
        return m.Collector(self.cfg, runner=runner or self.runner).collect()

    def test_real_collect_to_validate_full_registry_assets_and_resources(self):
        imported = []
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.split('.')[0] in ('gen_schedule_stats', 'unit_truth', 'app'):
                imported.append(name)
                raise AssertionError('business import forbidden during collection')
            return original_import(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=guarded_import):
            with self.assertRaisesRegex(AssertionError, 'business import forbidden'):
                builtins.__import__('gen_schedule_stats')
            imported.clear()
            snapshot = self.collect()
            body = m.validate_snapshot(snapshot)
        self.assertEqual(imported, [])
        expected = {r['unit'] for r in self.rows}
        got = {c['id'].removeprefix('cloud-service:') for c in snapshot['checks'] if c['category'] == 'service'}
        self.assertEqual(got, expected)
        self.assertEqual(sum(c['category'] == 'timer' for c in snapshot['checks']), len(expected))
        assets = {c['id'] for c in snapshot['checks'] if c['category'] == 'data'}
        self.assertEqual(assets, set(m.ASSETS))
        self.assertEqual(len(assets), 34)
        self.assertTrue(all(c['status'] == 'unknown' for c in snapshot['checks'] if c['category'] == 'data'))
        self.assertIn('resource:load', {c['id'] for c in snapshot['checks']})
        load = next(c for c in snapshot['checks'] if c['id'] == 'resource:load')
        self.assertIn('cpu_count', load['evidence'])
        self.assertNotIn('logical_cpus', load['evidence'])
        self.assertLessEqual(len(body), m.MAX_SNAPSHOT)
        self.assertNotIn(b'/home/', body)

    def test_dynamic_45th_registry_and_builder_changes_fail_closed(self):
        target = self.code / 'scripts/gen_schedule_stats.py'
        # Current repository may already have45; add one more literal entry to prove no fixed count.
        text = self.source.replace('UNIT_ONLY = [', 'UNIT_ONLY = [\n {"unit":"trade-test-added.service","task":"test_added","name":"added"},', 1)
        target.write_text(text)
        self.assertEqual(len(m.load_registry(self.code)), len(self.rows) + 1)
        target.write_text(text.replace('rows = []', 'rows = []; open("SHOULD_NOT_EXIST", "w")', 1))
        with self.assertRaises(m.ContractError):
            m.load_registry(self.code)
        self.assertFalse((self.code / 'SHOULD_NOT_EXIST').exists())

    def test_repeated_timer_properties_fingerprint_and_utc_fields(self):
        text = self.runner.run(['/usr/bin/systemctl', 'show'])
        expected = set(self.runner.names + [n.replace('.service', '.timer') for n in self.runner.names])
        props = m.parse_properties(text, expected)
        name = self.runner.names[0].replace('.service', '.timer')
        self.assertEqual(len(props[name]['TimersCalendar']), 2)
        c = m.unit_check(name, props[name])
        self.assertEqual(c['evidence']['expression_count'], 2)
        self.assertEqual(c['evidence']['next_elapse_utc'], '2026-11-07T08:35:00Z')
        self.assertEqual(c['evidence']['last_trigger_utc'], '2026-11-06T13:00:00Z')
        original = c['evidence']['calendar_sha256']
        props[name]['TimersCalendar'].reverse()
        self.assertEqual(m.calendar_fingerprint(props[name]), original)
        props[name]['TimersCalendar'][0] = props[name]['TimersCalendar'][0].replace('21:00:00', '22:00:00')
        self.assertNotEqual(m.calendar_fingerprint(props[name]), original)
        self.assertIsNone(m.systemd_time_utc('/tmp/not-a-date'))
        self.assertIsNone(m.systemd_time_utc('Sat 2026-11-07 16:35:00 XYZ'))

    def test_no_record_is_not_green_and_failed_service_is_not_timer_success(self):
        def props(**fields):return {k: [str(v)] for k, v in fields.items()}
        base = props(LoadState='loaded', ActiveState='inactive', Type='oneshot', Result='success', ExecMainStatus=0)
        self.assertEqual(m.unit_check('trade-test.service', base)['status'], 'unknown')
        base['ExecMainStartTimestamp'] = ['Fri 2026-11-06 21:00:00 CST']
        self.assertEqual(m.unit_check('trade-test.service', base)['status'], 'ok')
        base['ActiveState'] = ['failed'];base['Result'] = ['timeout'];base['ExecMainStatus'] = ['124']
        failed = m.unit_check('trade-test.service', base)
        self.assertEqual(failed['status'], 'critical')
        self.assertEqual(failed['evidence']['last_start_utc'], '2026-11-06T13:00:00Z')
        self.assertIsNone(failed['evidence']['last_exit_utc'])
        base['LoadState'] = ['not-found']
        self.assertEqual(m.unit_check('trade-test.service', base)['status'], 'unknown')

    def test_independent_command_failure_preserves_full_unknown_unit_coverage(self):
        obj = self.collect(FakeRunner(self.rows, fail=True))
        m.validate_snapshot(obj)
        units = [c for c in obj['checks'] if c['category'] in ('service', 'timer')]
        self.assertEqual(len(units), len(self.rows) * 2)
        self.assertTrue(all(c['status'] == 'unknown' for c in units))
        self.assertGreater(obj['coverage']['counts']['source_errors'], 0)
        self.assertNotIn('fake-private-value', json.dumps(obj))

    def test_weekend_mtime_and_large_asset_never_business_green_or_parsed(self):
        artifact = self.data / 'static-site/data/signal_kelly_trades.json'
        with artifact.open('wb') as f:f.truncate(91 * 1024 * 1024)
        os.utime(artifact, (1, 1))
        original = m.read_bytes
        def limited(path, cap):
            self.assertNotEqual(Path(path), artifact)
            return original(path, cap)
        with patch.object(m, 'read_bytes', side_effect=limited):
            obj = self.collect()
        c = next(c for c in obj['checks'] if c['id'] == 'data:kelly-trades')
        self.assertEqual(c['status'], 'unknown')
        self.assertEqual(c['evidence']['bytes'], 91 * 1024 * 1024)

    def test_schedule_reuses_existing_verdict_without_leaking_body(self):
        source = self.data / 'static-site/data/schedule_stats.json'
        rows = json.loads(source.read_text())
        rows[0].update(log_anomaly=True, log_anomaly_line='Bearer fake-secret /home/private', last_exit=0)
        source.write_text(json.dumps(rows))
        obj = self.collect()
        c = next(c for c in obj['checks'] if c['id'] == 'schedule:' + self.rows[0]['task'])
        self.assertEqual(c['status'], 'warning')
        self.assertNotIn('fake-secret', json.dumps(obj))
        os.utime(source, (1, 1))
        obj = self.collect()
        self.assertTrue(all(c['status'] == 'unknown' for c in obj['checks'] if c['id'].startswith('schedule:')))

    def unfinished_check(self, fields=None, **item_fields):
        path = self.data / 'static-site/data/schedule_stats.json'
        rows = json.loads(path.read_text())
        rows[0].update(round_state='started_unfinished', round_start_ts='2026-11-06 21:00:00')
        rows[0].update(item_fields)
        path.write_text(json.dumps(rows))
        snapshot = self.collect(ServiceStateRunner(self.rows, fields or {}))
        m.validate_snapshot(snapshot)
        return next(c for c in snapshot['checks'] if c['id'] == 'schedule:' + self.rows[0]['task'])

    def test_running_round_waits_for_completion_without_failure_or_success(self):
        for active in ('active', 'activating', 'reloading'):
            with self.subTest(active=active):
                c = self.unfinished_check({'ActiveState': active, 'SubState': 'start',
                                           'Result': 'exit-code', 'ExecMainStatus': '124'}, last_exit=124)
                self.assertEqual(c['status'], 'unknown')
                self.assertEqual(c['evidence']['execution_state'], 'running')
                self.assertNotIn('exit_code', c['evidence'])
                self.assertIn('completion not yet observed', c['summary'])

    def test_reset_failed_manager_success_does_not_rewrite_process_exit(self):
        props = {key: [str(value)] for key, value in {
            'LoadState': 'loaded', 'ActiveState': 'inactive', 'SubState': 'dead',
            'Type': 'oneshot', 'Result': 'success', 'ExecMainStatus': 124,
            'ExecMainStartTimestamp': 'Fri 2026-11-06 21:10:00 CST',
            'ExecMainExitTimestamp': 'Fri 2026-11-06 22:59:36 CST',
        }.items()}
        c = m.unit_check('trade-turnover-backfill.service', props)
        self.assertEqual(c['status'], 'warning')
        self.assertEqual(c['evidence']['unit_result'], 'success')
        self.assertEqual(c['evidence']['exit_code'], 124)
        self.assertEqual(c['evidence']['last_exit_utc'], '2026-11-06T14:59:36Z')

    def test_service_exit_success_policy_preserves_raw_code_and_uses_same_show(self):
        for status, policy, expected in ((0, '', 'ok'), (5, '5', 'ok'),
                                         (5, '', 'warning'), (124, '', 'warning'),
                                         (124, '5', 'warning'), (124, '124', 'ok'),
                                         (5, '15 50', 'warning'), (5, ' 3  5 7 ', 'ok')):
            with self.subTest(status=status, policy=policy):
                runner = ServiceStateRunner(self.rows, {
                    'ExecMainCode': '1', 'ExecMainStatus': str(status), 'SuccessExitStatus': policy,
                })
                snapshot = self.collect(runner)
                m.validate_snapshot(snapshot)
                c = next(c for c in snapshot['checks']
                         if c['id'] == 'cloud-service:' + self.rows[0]['unit'])
                self.assertEqual(c['status'], expected)
                self.assertEqual(c['evidence']['exit_code'], status)
                self.assertEqual(c['evidence']['unit_result'], 'success')
                self.assertEqual(c['evidence'].get('accepted_success_exit', False),
                                 status != 0 and expected == 'ok')
                shows = [args for args in runner.calls if args[1] == 'show']
                self.assertEqual(len(shows), 1)
                props = next(a.removeprefix('--property=') for a in shows[0]
                             if a.startswith('--property=')).split(',')
                self.assertEqual(props.count('SuccessExitStatus'), 1)

    def test_same_round_accepted_exit_retains_policy_evidence_without_washing_124(self):
        for status, policy, expected in ((5, '5', 'ok'), (5, '', 'warning'),
                                         (124, '', 'warning'), (124, '5', 'warning'),
                                         (124, '124', 'ok')):
            with self.subTest(status=status, policy=policy):
                c = self.unfinished_check({'ExecMainCode': '1', 'ExecMainStatus': str(status),
                                           'SuccessExitStatus': policy})
                self.assertEqual(c['status'], expected)
                self.assertTrue(c['evidence']['same_round'])
                self.assertEqual(c['evidence']['exit_code'], status)
                self.assertEqual(c['evidence']['execution_state'],
                                 'completed' if expected == 'ok' else 'failed')
                self.assertEqual(c['evidence'].get('accepted_success_exit', False), expected == 'ok')
                if expected == 'ok':
                    self.assertEqual(c['evidence']['completion_source'], 'systemd_live')
                    self.assertTrue(c['evidence']['trusted_exit_origin'])

    def test_signal_status_five_is_not_an_accepted_exit_five(self):
        for exec_code in ('2', '3'):
            with self.subTest(exec_code=exec_code):
                fields = {'ExecMainCode': exec_code, 'ExecMainStatus': '5',
                          'SuccessExitStatus': '5', 'Result': 'success'}
                snapshot = self.collect(ServiceStateRunner(self.rows, fields))
                m.validate_snapshot(snapshot)
                service = next(c for c in snapshot['checks']
                               if c['id'] == 'cloud-service:' + self.rows[0]['unit'])
                self.assertEqual(service['status'], 'warning')
                self.assertEqual(service['evidence']['exit_code'], 5)
                self.assertNotIn('accepted_success_exit', service['evidence'])
                scheduled = self.unfinished_check(fields)
                self.assertEqual(scheduled['status'], 'warning')
                self.assertTrue(scheduled['evidence']['same_round'])
                self.assertEqual(scheduled['evidence']['exit_code'], 5)
                self.assertEqual(scheduled['evidence']['execution_state'], 'failed')
                self.assertNotEqual(scheduled['evidence']['execution_state'], 'completed')
                self.assertNotIn('accepted_success_exit', scheduled['evidence'])

    def test_live_success_reconciles_only_the_same_round_after_schedule_snapshot(self):
        c = self.unfinished_check(last_exit=124)
        self.assertEqual(c['status'], 'ok')
        self.assertTrue(c['evidence']['same_round'])
        self.assertEqual(c['evidence']['execution_state'], 'completed')
        self.assertEqual(c['evidence']['exit_code'], 0)
        self.assertEqual(c['evidence']['completion_source'], 'systemd_live')

    def test_unfinished_round_cannot_borrow_other_or_unproved_unit_success(self):
        cases = [
            ({'ExecMainStartTimestamp': 'Fri 2026-11-06 20:00:00 CST'}, 'unknown'),
            ({'ExecMainStartTimestamp': 'n/a'}, 'unknown'), ({'ExecMainExitTimestamp': 'n/a'}, 'unknown'),
            ({'ExecMainExitTimestamp': 'Fri 2026-11-06 20:59:59 CST'}, 'unknown'),
            ({'ExecMainExitTimestamp': 'Thu 2099-01-01 21:02:00 UTC'}, 'unknown'),
            ({'ExecMainStatus': '124'}, 'warning'), ({'Result': 'exit-code'}, 'warning'),
            ({'ActiveState': 'failed'}, 'warning'), ({'LoadState': 'not-found'}, 'unknown'),
            ({'Type': 'simple'}, 'unknown'),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                c = self.unfinished_check(fields)
                self.assertEqual(c['status'], expected)
                if 'exit_code' in c['evidence']:
                    self.assertEqual(c['status'], 'warning')

    def test_real_schedule_fault_flags_take_priority_over_running(self):
        for flag in ('exit_conflict', 'unit_missed', 'log_anomaly'):
            with self.subTest(flag=flag):
                # Remove flags from the previous subcase to test each independently.
                path = self.data / 'static-site/data/schedule_stats.json'
                rows = json.loads(path.read_text())
                rows[0].update(exit_conflict=False, unit_missed=False, log_anomaly=False)
                path.write_text(json.dumps(rows))
                c = self.unfinished_check({'ActiveState': 'activating'}, **{flag: True})
                self.assertEqual(c['status'], 'warning')
                self.assertNotIn('execution_state', c['evidence'])

    def test_same_round_future_end_never_claims_completion(self):
        collector = m.Collector(self.cfg, runner=self.runner,
                                now=datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc))
        props = {
            'LoadState': 'loaded', 'ActiveState': 'inactive', 'Type': 'oneshot',
            'Result': 'success', 'ExecMainStatus': '0',
            'ExecMainStartTimestamp': 'Fri 2026-11-06 21:00:00 CST',
        }
        for end in ('14:00:01', '14:02:00', '14:02:01'):
            with self.subTest(end=end):
                props['ExecMainExitTimestamp'] = f'Fri 2026-11-06 {end} UTC'
                collector.unit_observations[self.rows[0]['unit']] = {
                    key: [value] for key, value in props.items()}
                evidence = {}
                status, _ = collector.unfinished_schedule(
                    self.rows[0], {'round_start_ts': '2026-11-06 21:00:00'}, evidence)
                self.assertEqual(status, 'unknown')
                self.assertEqual(evidence['execution_state'], 'pending')
                self.assertNotIn('exit_code', evidence)

    def test_unfinished_round_without_live_unit_proof_is_not_a_failure_or_recovery(self):
        c = self.unfinished_check({'ExecMainStartTimestamp': '', 'ExecMainExitTimestamp': ''})
        self.assertEqual(c['status'], 'unknown')
        self.assertEqual(c['evidence']['execution_state'], 'pending')
        path = self.data / 'static-site/data/schedule_stats.json'
        os.utime(path, (1, 1))
        snapshot = self.collect(ServiceStateRunner(self.rows, {'ActiveState': 'activating'}))
        c = next(c for c in snapshot['checks'] if c['id'] == 'schedule:' + self.rows[0]['task'])
        self.assertEqual(c['status'], 'unknown')
        self.assertNotIn('execution_state', c['evidence'])

    def test_read_limits_symlinks_duplicate_and_nonfinite_json(self):
        p = self.temp / 'input.json'
        for text in ('{"a":1,"a":2}', '{"a":NaN}'):
            p.write_text(text)
            with self.assertRaises(m.ContractError):m.read_json(p)
        p.write_text('x' * 50)
        with self.assertRaises(m.LimitError):m.read_bytes(p, 20)
        link = self.temp / 'link';link.symlink_to(p)
        with self.assertRaises(OSError):m.read_bytes(link, 100)
        fifo = self.temp / 'fifo';os.mkfifo(fifo)
        with self.assertRaises(m.LimitError):m.read_bytes(fifo, 100)

    def test_secret_owner_modes_no_symlink_and_no_echo(self):
        for mode in (0o400, 0o600):
            self.secret.chmod(mode)
            self.assertTrue(m.read_secret(self.secret).startswith('fixture-'))
        self.secret.chmod(0o640)
        with self.assertRaises(m.ContractError):m.read_secret(self.secret)
        link = self.temp / 'credential-link';link.symlink_to(self.secret)
        with self.assertRaises(OSError):m.read_secret(link)

    def test_endpoint_https_allowlist_and_explicit_loopback(self):
        for bad in ('https://evil.invalid/api/ops/ingest', 'http://ss.fx8.store/api/ops/ingest',
                    'https://ss.fx8.store:444/api/ops/ingest', 'https://user:ss@ss.fx8.store/api/ops/ingest',
                    'https://ss.fx8.store/api/ops/ingest?token=private', 'http://127.0.0.1:8787/api/ops/ingest'):
            with self.subTest(bad=bad), self.assertRaises(m.ContractError):m.endpoint(bad)
        self.assertEqual(m.endpoint('http://127.0.0.1:8787/api/ops/ingest', test_local=True).port, 8787)
        with self.assertRaises(m.ContractError):m.endpoint('http://localhost:8787/api/ops/ingest', test_local=True)

    def test_fake_http_ack_redirect_and_no_body_export(self):
        snapshot = self.collect();payload = m.validate_snapshot(snapshot)
        conn = MagicMock();response = conn.getresponse.return_value
        response.status = 200;response.read.return_value = json.dumps({'accepted': True, 'snapshot_id': snapshot['snapshot_id']}).encode()
        with patch.object(m.http.client, 'HTTPSConnection', return_value=conn):
            result = m.request_http(self.cfg.ingest_url, payload, str(self.secret))
        self.assertTrue(result['ok'])
        self.assertIn('Bearer fixture-', conn.request.call_args.kwargs['headers']['Authorization'])
        self.assertNotIn('fixture-', json.dumps(result))
        response.status = 302;response.read.return_value = b'private response body'
        with patch.object(m.http.client, 'HTTPSConnection', return_value=conn):
            self.assertFalse(m.request_http(self.cfg.ingest_url, payload, str(self.secret))['ok'])
        self.assertEqual(conn.request.call_count, 2)  # no redirect followup

    def test_collect_only_real_pipeline_private_files_and_no_network(self):
        cfgfile = self.temp / 'collector.json';cfgfile.write_text(json.dumps(self.cfg.__dict__))
        with patch.object(m.CommandRunner, 'run', side_effect=self.runner.run), patch.object(m, 'network_bounded', side_effect=AssertionError('outbound')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):rc = m.main(['--config', str(cfgfile), '--collect-only', '--token-file', str(self.secret)])
        self.assertEqual(rc, 0)
        for name in ('snapshot.json', 'report.json'):
            self.assertEqual((Path(self.cfg.output_dir) / name).stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(Path(self.cfg.output_dir).glob('.*-*.tmp')))
        obj = json.loads((Path(self.cfg.output_dir) / 'snapshot.json').read_text());m.validate_snapshot(obj)
        self.assertNotIn(str(self.secret), out.getvalue())
        self.assertNotIn('fixture-token', (Path(self.cfg.output_dir) / 'report.json').read_text())

    def test_main_stdout_projects_only_safe_delivery_metadata(self):
        cfgfile = self.temp / 'stdout-collector.json'
        cfgfile.write_text(json.dumps(self.cfg.__dict__))
        sensitive = 'Bearer fixture-private-token https://private.invalid/body /home/private'
        cases = [
            ({'ok': False, 'http_status': 503, 'error_kind': 'HTTPError'},
             {'http_status': 503, 'error_kind': 'HTTPError'}, '--once', 2),
            ({'ok': False, 'error_kind': 'TimeoutError'},
             {'error_kind': 'TimeoutError'}, '--once', 2),
            ({'ok': True, 'http_status': 200}, {'http_status': 200}, '--once', 0),
            ({'ok': False, 'state': 'collect_only'}, {}, '--collect-only', 0),
        ]
        for delivery, expected, mode, expected_rc in cases:
            with self.subTest(delivery=expected, mode=mode):
                private_delivery = {**delivery, 'body': sensitive, 'url': sensitive,
                                    'secret': sensitive, 'headers': {'Authorization': sensitive}}
                original = json.dumps(private_delivery, sort_keys=True)
                report = {'snapshot_id': 'synthetic-safe-projection',
                          'coverage': {'counts': {'checks': 7}}, 'delivery': private_delivery}
                out = io.StringIO()
                with patch.object(m, 'run_once', return_value=(report, expected_rc)) as run_once:
                    with contextlib.redirect_stdout(out):
                        rc = m.main(['--config', str(cfgfile), mode])
                self.assertEqual(rc, expected_rc)
                self.assertEqual(json.loads(out.getvalue()), {
                    'snapshot_id': 'synthetic-safe-projection', 'checks': 7,
                    'delivery_ok': delivery['ok'], 'collect_only': mode == '--collect-only',
                    'delivery': expected,
                })
                self.assertNotIn(sensitive, out.getvalue())
                self.assertEqual(json.dumps(private_delivery, sort_keys=True), original)
                run_once.assert_called_once()
                self.assertEqual(run_once.call_args.kwargs['collect_only'], mode == '--collect-only')

    def test_upload_reserve_survives_collection_deadline_and_skips_head(self):
        now = [100.0]
        real_budget = m.Budget
        def budgets(seconds=20):return real_budget(seconds, clock=lambda: now[0])
        original_collect = m.Collector.collect
        def slow(collector):
            now[0] = collector.budget.deadline
            return original_collect(collector)
        calls = []
        def network(budget, url, *a, **k):
            calls.append((url, budget.remaining()))
            self.assertFalse(k.get('head', False))
            self.assertGreaterEqual(budget.remaining(), 8)
            return {'ok': True, 'http_status': 200}
        self.cfg.publication_head_url = 'https://ss.fx8.store/__build'
        with patch.object(m, 'Budget', side_effect=budgets), patch.object(m.Collector, 'collect', slow), patch.object(m, 'network_bounded', side_effect=network):
            report, rc = m.run_once(self.cfg)
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertGreater(report['coverage']['counts']['unknown'], 0)
        self.assertEqual(report['duration_ms'], 12000)

    def test_real_command_pipe_output_cap_and_deadline(self):
        original = subprocess.Popen
        def spawn_text(*a, **kw):
            self.assertEqual(kw['env']['TZ'], 'UTC')
            return original([sys.executable, '-c', "import sys;sys.stdout.write('x'*200000)"], **kw)
        with patch.object(m.subprocess, 'Popen', side_effect=spawn_text):
            with self.assertRaises(m.LimitError):m.CommandRunner(m.Budget(2)).run(['/usr/bin/systemctl', 'show'])
        def spawn_sleep(*a, **kw):return original([sys.executable, '-c', 'import time;time.sleep(5)'], **kw)
        start = time.monotonic()
        with patch.object(m.subprocess, 'Popen', side_effect=spawn_sleep):
            with self.assertRaises(m.LimitError):m.CommandRunner(m.Budget(.05)).run(['/usr/bin/systemctl', 'show'])
        self.assertLess(time.monotonic() - start, 1.5)
        with self.assertRaises(m.ContractError):m.CommandRunner(m.Budget(1)).run(['/bin/sh', '-c', 'echo unsafe'])

    def test_wire_rejects_sensitive_key_and_partial_atomic_write(self):
        obj = self.collect();obj['checks'][0]['evidence'] = {'logical_cpus': 4}
        with self.assertRaises(m.ContractError):m.validate_snapshot(obj)
        out = self.temp / 'private';m.atomic_private_json(out, 'snapshot.json', {'old': True})
        before = (out / 'snapshot.json').read_bytes()
        with patch.object(m.os, 'replace', side_effect=OSError('atomic fail')):
            with self.assertRaises(OSError):m.atomic_private_json(out, 'snapshot.json', {'new': True})
        self.assertEqual((out / 'snapshot.json').read_bytes(), before)
        self.assertEqual(list(out.iterdir()), [out / 'snapshot.json'])


if __name__ == '__main__':
    unittest.main()
