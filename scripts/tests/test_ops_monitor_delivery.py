"""Real loopback HTTP + real Worker/SQLite; never contacts production."""
import contextlib
import http.client
import io
import json
import multiprocessing
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ops_monitor as m

ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def server(mode):
    proc = subprocess.Popen(['node', str(ROOT / 'ops/monitoring/tests/worker-delivery-server.mjs'), mode],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            if not selector.select(5):
                raise AssertionError('local fixture startup timeout')
        line = proc.stdout.readline()
        if not line:
            raise AssertionError('local fixture exited during startup')
        port = json.loads(line)['port']
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=2)
        proc.stdout.close()


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ops-delivery-')
        self.addCleanup(self.temp.cleanup)
        self.secret = Path(self.temp.name) / 'token'
        self.secret.write_text('fixture-token-0123456789')
        self.secret.chmod(0o600)
        now = m.utc_now()
        self.snapshot = dict(schema_version=1, snapshot_id=str(uuid.uuid4()), collector_id='delivery-fixture',
                             collected_at=now, code_ref='unknown', duration_ms=1,
                             coverage={'counts': {'checks': 1}, 'limitations': []}, checks=[{
                                 'id': 'service:test', 'name': 'Fixture', 'category': 'service',
                                 'status': 'critical', 'observed_at': now, 'summary': 'Fixture', 'evidence': {}}])
        self.payload = m.validate_snapshot(self.snapshot)

    def deliver(self, port, seconds=8):
        start = time.monotonic()
        result = m.network_bounded(m.Budget(seconds), f'http://127.0.0.1:{port}/api/ops/ingest',
                                   self.payload, str(self.secret), test_local=True)
        elapsed = time.monotonic() - start
        print(json.dumps({'upload_budget': seconds, 'elapsed_seconds': round(elapsed, 3), 'delivery': result}))
        return result, elapsed

    def state(self, port):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        try:
            conn.request('GET', '/test-state')
            return json.loads(conn.getresponse().read())
        finally:
            conn.close()

    def test_503_then_200_same_bytes_id_one_event(self):
        with server('503first') as port:
            result, elapsed = self.deliver(port)
            self.assertTrue(result['ok'], result)
            state = self.state(port)
        self.assertEqual(len(state['attempts']), 2)
        self.assertEqual(state['attempts'][0], state['attempts'][1])
        self.assertEqual((state['runs'], state['events'], state['outbox']), (1, 1, 1))
        self.assertLess(elapsed, 8.3)

    def test_real_five_second_socket_timeout_then_200(self):
        with server('timeoutfirst') as port:
            result, elapsed = self.deliver(port)
            self.assertTrue(result['ok'], result)
            state = self.state(port)
        self.assertGreaterEqual(elapsed, 5)
        self.assertLess(elapsed, 8.3)
        self.assertEqual(len(state['attempts']), 2)
        self.assertEqual(state['attempts'][0], state['attempts'][1])
        self.assertEqual((state['runs'], state['events'], state['outbox']), (1, 1, 1))

    def test_committed_but_response_lost_replay_is_safe(self):
        for mode in ('dropfirst', 'headfail', '502first', '504first'):
            with self.subTest(mode=mode), server(mode) as port:
                result, _ = self.deliver(port)
                self.assertTrue(result['ok'], result)
                state = self.state(port)
            self.assertEqual(len(state['attempts']), 2)
            self.assertEqual(state['attempts'][0], state['attempts'][1])
            self.assertEqual((state['runs'], state['events'], state['outbox']), (1, 1, 1))

    def test_permanent_failures_unknown_ack_and_safe_metadata(self):
        for mode in ('400', '401', '403', '409', '500', 'badack', 'invalidjson', 'duplicateack', 'hugeack', 'quota', 'config', 'constraint', 'overloaded', 'resource_limit', 'malicious'):
            with self.subTest(mode=mode), server(mode) as port:
                result, _ = self.deliver(port)
                self.assertFalse(result['ok'], result)
                state = self.state(port)
                self.assertEqual(len(state['attempts']), 3 if mode == 'malicious' else 1)
                self.assertNotIn('injected-private', json.dumps(result))
                self.assertNotIn('secret=unsafe', json.dumps(result))

    def test_once_single_collection_report_stdout_never_reflect_error_text(self):
        for mode in ('503first', 'malicious'):
            with self.subTest(mode=mode), server(mode) as port:
                cfg = m.Settings(output_dir=str(Path(self.temp.name) / 'out'), secret_file=str(self.secret),
                                 ingest_url=f'http://127.0.0.1:{port}/api/ops/ingest')
                config = Path(self.temp.name) / 'config.json'; config.write_text(json.dumps(cfg.__dict__))
                out = io.StringIO()
                with patch.object(m.Collector, 'collect', return_value=self.snapshot) as collect, contextlib.redirect_stdout(out):
                    rc = m.main(['--config', str(config), '--once', '--test-local-http'])
                collect.assert_called_once()
                self.assertEqual(rc, 0 if mode == '503first' else 2)
                report = json.loads((Path(cfg.output_dir) / 'report.json').read_text())
                self.assertEqual(report['delivery']['ok'], mode == '503first')
                stored = json.loads((Path(cfg.output_dir) / 'snapshot.json').read_text())
                self.assertEqual(stored['snapshot_id'], self.snapshot['snapshot_id'])
                self.assertNotIn('injected-private', out.getvalue() + json.dumps(report))
                self.assertNotIn('secret=unsafe', out.getvalue() + json.dumps(report))

    def test_always_503_and_timeout_obey_original_budget_and_reap(self):
        for mode, seconds in [('always503', 8), ('slow503', 8), ('hang', 8), ('hang', .5)]:
            with self.subTest(mode=mode, seconds=seconds), server(mode) as port:
                result, elapsed = self.deliver(port, seconds)
                self.assertFalse(result['ok'], result)
                self.assertLess(elapsed, seconds + .3)
                self.assertLessEqual(len(self.state(port)['attempts']), 3)
                self.assertFalse(multiprocessing.active_children())


if __name__ == '__main__':
    unittest.main()
