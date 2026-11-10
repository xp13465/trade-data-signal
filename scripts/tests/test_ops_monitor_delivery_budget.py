"""Real loopback stalled-read reproduction, no production credentials or services."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
from pathlib import Path
import threading
import time
import uuid

import ops_monitor as m


@contextlib.contextmanager
def slow_server(mode):
    attempts = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            attempts.append(body)
            ack = json.dumps({'accepted': True, 'snapshot_id': json.loads(body)['snapshot_id']}).encode()
            try:
                if mode == 'slow_both':
                    time.sleep(5.3 if len(attempts) == 1 else 3.3)
                self.send_response(200); self.send_header('Content-Length', str(len(ack))); self.end_headers()
                if mode == 'trickle_first' and len(attempts) == 1:
                    for byte in ack:
                        self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(.3)
                elif mode == 'always_hang':
                    time.sleep(10)
                else:
                    self.wfile.write(ack)
            except (BrokenPipeError, ConnectionResetError): pass
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, kwargs={'poll_interval': .05}, daemon=True); t.start()
    try: yield httpd.server_port, attempts
    finally: httpd.shutdown(); httpd.server_close(); t.join(1)


def test_trickle_read_cannot_consume_all_retries(tmp_path):
    secret = tmp_path / 'fixture.token'; secret.write_text('offline-fixture-token-12345'); secret.chmod(0o600)
    payload = json.dumps({'snapshot_id': str(uuid.uuid4())}).encode()
    with slow_server('trickle_first') as (port, attempts):
        started = time.monotonic()
        result = m.network_bounded(m.Budget(8), f'http://127.0.0.1:{port}/api/ops/ingest', payload,
                                   str(secret), test_local=True)
        elapsed = time.monotonic() - started
        assert result['ok'], result
        assert len(attempts) == 2
        assert attempts == [payload, payload]
        assert elapsed < 8.3
    assert not multiprocessing.active_children()


def test_reuses_available_total_budget_not_fixed_eight_seconds(tmp_path):
    secret = tmp_path / 'fixture.token'; secret.write_text('offline-fixture-token-12345'); secret.chmod(0o600)
    payload = json.dumps({'snapshot_id': str(uuid.uuid4())}).encode()
    with slow_server('slow_both') as (port, attempts):
        started = time.monotonic()
        result = m.network_bounded(m.Budget(15), f'http://127.0.0.1:{port}/api/ops/ingest', payload,
                                   str(secret), test_local=True)
        assert result['ok'], result
        assert 8 < time.monotonic() - started < 15.3
        assert attempts == [payload, payload]
    assert not multiprocessing.active_children()
