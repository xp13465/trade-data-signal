"""B批 monitor-obs 回归(2026-11-14):attempts_detail 投影 + late_ack 迟到对账 + 外部告警配置模板。

真实 loopback HTTP 打真实 Worker handler + 真实 SQLite 触发器;journal 喂的是合成行。
不连生产、不读生产凭据、不发任何真实通知(L48)。"""
import contextlib
import io
import json
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))  # spawn 子进程按模块名反解 ops_monitor
import ops_monitor as m  # 同 test_ops_monitor_delivery: 绝不覆盖 sys.modules['ops_monitor'], 否则并行加载的两份模块实例会让 ForkingPickler 反解到不同函数对象而 PicklingError


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
            yield json.loads(line)['port']
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=2)
        proc.stdout.close()


def journal_lines(*entries):
    """Synthetic own-journal stdout lines: (wall_seconds_ago, snapshot_id, delivery_ok, collect_only)."""
    lines = []
    for age, sid, ok, collect_only in entries:
        record = {'__REALTIME_TIMESTAMP': str(int((time.time() - age) * 1000000)),
                  '_SYSTEMD_UNIT': m.SELF_UNIT, 'SYSLOG_IDENTIFIER': 'trade-ops-monitor',
                  'MESSAGE': json.dumps({'snapshot_id': sid, 'delivery_ok': ok, 'collect_only': collect_only,
                                         'delivery': {'error_kind': 'TimeoutError' if not ok else None,
                                                      'attempts': 3, 'elapsed_ms': 15547,
                                                      'attempt_deadline_exceeded': True}})}
        lines.append(json.dumps(record))
    return '\n'.join(lines)


class FakeJournalRunner:
    def __init__(self, raw):
        self.raw = raw

    def run(self, args):
        return self.raw


class FailingRunner:
    def run(self, args):
        raise RuntimeError('journal unavailable fixture')


def closed_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class AttemptsDetailTests(unittest.TestCase):
    def test_three_attempt_projection_stage_fields(self):
        # 证据用例1: 三条 attempt 齐全, 阶段字段有值或显式 unknown, 不可观测阶段显式标记。
        base = time.time()
        history = []
        for i, (status, kind) in enumerate([(None, 'TimeoutError'), (502, None), (None, 'TimeoutError')], start=1):
            started = base - 20 + i * 5
            history.append({'snapshot_id': str(uuid.uuid4()), 'attempt': i,
                            'started_at': m.utc_now(), 'finished_at': m.utc_now(),
                            'http_status': status, 'error_kind': kind, 'quota_kind': None,
                            'ack_state': 'unknown' if status is None else 'rejected',
                            'received_at': None, 'delivered_at': None})
        detail = m.attempts_detail({'attempt_history': history})
        self.assertEqual([d['attempt'] for d in detail], [1, 2, 3])
        for entry in detail:
            self.assertIn('duration_ms', entry)
            self.assertEqual(entry['in_flight_stages'], 'unobserved')
            self.assertIn('started_at', entry)
            self.assertIn('finished_at', entry)
            self.assertIn('ack_state', entry)
        self.assertEqual([d['http_status'] for d in detail], [None, 502, None])
        self.assertEqual([d['error_kind'] for d in detail], ['TimeoutError', None, 'TimeoutError'])
        # 无回包的三次 TimeoutError 可与「某次收到 4xx/5xx」区分(第2条 http_status=502)。

    def test_real_socket_timeout_attempt_detail(self):
        # 真实 socket 超时路径的 attempt 明细: 无回包 attempt 的 http_status 为 None。
        with server('hang') as port:
            secret = Path(tempfile.mkdtemp(prefix='ops-late-ack-')) / 'token'
            secret.write_text('fixture-token-0123456789')
            secret.chmod(0o600)
            snapshot = {'schema_version': 1, 'snapshot_id': str(uuid.uuid4()), 'collector_id': 'late-ack-fixture',
                        'collected_at': m.utc_now(), 'code_ref': 'unknown', 'duration_ms': 1,
                        'coverage': {'counts': {'checks': 1}, 'limitations': []},
                        'checks': [{'id': 'service:test', 'name': 'Fixture', 'category': 'service',
                                    'status': 'ok', 'observed_at': m.utc_now(), 'summary': 'Fixture', 'evidence': {}}]}
            result = m.network_bounded(m.Budget(8), f'http://127.0.0.1:{port}/api/ops/ingest',
                                       m.validate_snapshot(snapshot), str(secret), test_local=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['attempt_history'])
        detail = m.attempts_detail(result)
        for entry in detail:
            self.assertIsNone(entry['http_status'])
            self.assertEqual(entry['error_kind'], 'TimeoutError')
            self.assertGreaterEqual(entry['duration_ms'], 2000)
            self.assertEqual(entry['in_flight_stages'], 'unobserved')


class ReconcileLateAckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ops-late-ack-')
        self.addCleanup(self.temp.cleanup)
        self.secret = Path(self.temp.name) / 'token'
        self.secret.write_text('fixture-token-0123456789')
        self.secret.chmod(0o600)

    def cfg(self, ingest_url):
        return m.Settings(output_dir=str(Path(self.temp.name) / 'out'), secret_file=str(self.secret),
                          ingest_url=ingest_url)

    def test_previous_failed_delivery_filters(self):
        old, recent = str(uuid.uuid4()), str(uuid.uuid4())
        raw = '\n'.join([
            json.dumps({'__REALTIME_TIMESTAMP': str(int((time.time() - 2400) * 1e6)),  # 超龄, 排除
                        '_SYSTEMD_UNIT': m.SELF_UNIT, 'SYSLOG_IDENTIFIER': 'trade-ops-monitor',
                        'MESSAGE': json.dumps({'snapshot_id': old, 'delivery_ok': False,
                                               'collect_only': False, 'delivery': {}})}),
            json.dumps({'__REALTIME_TIMESTAMP': str(int((time.time() - 300) * 1e6)),  # 成功轮, 排除
                        '_SYSTEMD_UNIT': m.SELF_UNIT, 'SYSLOG_IDENTIFIER': 'trade-ops-monitor',
                        'MESSAGE': json.dumps({'snapshot_id': str(uuid.uuid4()), 'delivery_ok': True,
                                               'collect_only': False, 'delivery': {'http_status': 200}})}),
            json.dumps({'__REALTIME_TIMESTAMP': str(int((time.time() - 200) * 1e6)),  # collect-only, 排除
                        '_SYSTEMD_UNIT': m.SELF_UNIT, 'SYSLOG_IDENTIFIER': 'trade-ops-monitor',
                        'MESSAGE': json.dumps({'snapshot_id': str(uuid.uuid4()), 'delivery_ok': False,
                                               'collect_only': True, 'delivery': {}})}),
            json.dumps({'UNIT': m.SELF_UNIT, 'JOB_TYPE': 'start', 'JOB_RESULT': 'failed'}),  # manager 行, 排除
            journal_lines((900, recent, False, False)),
        ])
        picked = m.previous_failed_delivery(raw, time.time(), 1800)
        self.assertEqual(picked[1], recent)

    def test_late_ok_lost_unknown(self):
        # 证据用例2: 已入库→late_ok; 未入库→lost; 查询失败→unknown(不误判)。
        with server('503first') as port:
            snapshot = {'schema_version': 1, 'snapshot_id': str(uuid.uuid4()), 'collector_id': 'late-ack-fixture',
                        'collected_at': m.utc_now(), 'code_ref': 'unknown', 'duration_ms': 1,
                        'coverage': {'counts': {'checks': 1}, 'limitations': []},
                        'checks': [{'id': 'service:test', 'name': 'Fixture', 'category': 'service',
                                    'status': 'ok', 'observed_at': m.utc_now(), 'summary': 'Fixture', 'evidence': {}}]}
            delivered = m.network_bounded(m.Budget(8), f'http://127.0.0.1:{port}/api/ops/ingest',
                                          m.validate_snapshot(snapshot), str(self.secret), test_local=True)
            self.assertTrue(delivered['ok'])
            # late_ok: 上轮失败 snapshot 实际已入库(本轮成功投递同一 id 模拟「迟到已确认」)。
            late = m.reconcile_late_ack(self.cfg(f'http://127.0.0.1:{port}/api/ops/ingest'), time.time(),
                                        test_local=True, runner=FakeJournalRunner(journal_lines((300, snapshot['snapshot_id'], False, False))))
            self.assertEqual(late['state'], 'late_ok')
            self.assertEqual(late['snapshot_id'], snapshot['snapshot_id'])
            self.assertIn('received_at', late)
            # lost: journal 里的失败 snapshot 从未投递、库里没有。
            missing = str(uuid.uuid4())
            lost = m.reconcile_late_ack(self.cfg(f'http://127.0.0.1:{port}/api/ops/ingest'), time.time(),
                                        test_local=True, runner=FakeJournalRunner(journal_lines((300, missing, False, False))))
            self.assertEqual(lost, {'state': 'lost', 'snapshot_id': missing})
            # unknown: 服务端不可达(ConnectionError), 不误判 lost。
            dead = closed_port()
            unknown = m.reconcile_late_ack(self.cfg(f'http://127.0.0.1:{dead}/api/ops/ingest'), time.time(),
                                            test_local=True, runner=FakeJournalRunner(journal_lines((300, missing, False, False))))
            self.assertEqual(unknown['state'], 'unknown')
            self.assertEqual(unknown['snapshot_id'], missing)
            self.assertEqual(unknown['error_kind'], 'ConnectionError')
        # journal 读不到 → honest unknown, 不猜 lost。
        unreadable = m.reconcile_late_ack(self.cfg('https://ss.fx8.store/api/ops/ingest'), time.time(),
                                           runner=FailingRunner())
        self.assertEqual(unreadable, {'state': 'unknown', 'reason': 'journal_unavailable'})
        # 无失败前轮 → 不产出 late_ack(正常轮无对账需求)。
        none = m.reconcile_late_ack(self.cfg('https://ss.fx8.store/api/ops/ingest'), time.time(),
                                    runner=FakeJournalRunner(journal_lines((300, str(uuid.uuid4()), True, False))))
        self.assertIsNone(none)

    def test_run_once_stdout_projection_matches_previous_shape(self):
        # 证据用例3: 正常成功轮 journal 既有字段与旧行为一致; attempts_detail 为新增; late_ack 仅在有失败前轮时出现。
        for mode, journal_raw, expect_late in (
                ('503first', '', False),
                ('503first', journal_lines((300, str(uuid.uuid4()), False, False)), True)):
            with self.subTest(expect_late=expect_late), server(mode) as port:
                cfg = m.Settings(output_dir=str(Path(self.temp.name) / f'out-{expect_late}'),
                                secret_file=str(self.secret),
                                ingest_url=f'http://127.0.0.1:{port}/api/ops/ingest')
                config = Path(self.temp.name) / f'config-{expect_late}.json'
                config.write_text(json.dumps(cfg.__dict__))
                now = m.utc_now()
                snapshot = {'schema_version': 1, 'snapshot_id': str(uuid.uuid4()), 'collector_id': 'late-ack-fixture',
                           'collected_at': now, 'code_ref': 'unknown', 'duration_ms': 1,
                           'coverage': {'counts': {'checks': 1}, 'limitations': []},
                           'checks': [{'id': 'service:test', 'name': 'Fixture', 'category': 'service',
                                       'status': 'ok', 'observed_at': now, 'summary': 'Fixture', 'evidence': {}}]}
                out = io.StringIO()
                with patch.object(m.Collector, 'collect', return_value=snapshot) as collect, \
                        patch.object(m, 'CommandRunner', lambda budget, timeout: FakeJournalRunner(journal_raw)), \
                        contextlib.redirect_stdout(out):
                    rc = m.main(['--config', str(config), '--once', '--test-local-http'])
                collect.assert_called_once()
                self.assertEqual(rc, 0)
                projection = json.loads(out.getvalue())
                # 既有字段语义不变。
                self.assertTrue(projection['delivery_ok'])
                self.assertFalse(projection['collect_only'])
                self.assertEqual(projection['delivery']['http_status'], 200)
                self.assertEqual(projection['delivery']['attempts'], 2)
                self.assertIsInstance(projection['delivery']['elapsed_ms'], int)
                self.assertNotIn('error_kind', projection['delivery'])
                # 新增: attempts_detail 与轮内 attempt 数一致。
                self.assertEqual(len(projection['delivery']['attempts_detail']), 2)
                self.assertTrue(all(d['in_flight_stages'] == 'unobserved' for d in projection['delivery']['attempts_detail']))
                # late_ack: 有失败前轮才出现(未入库 → lost)。
                self.assertEqual('late_ack' in projection, expect_late)
                if expect_late:
                    self.assertEqual(projection['late_ack']['state'], 'lost')
                report = json.loads((Path(cfg.output_dir) / 'report.json').read_text())
                self.assertTrue(report['delivery']['ok'])
                self.assertEqual('late_ack' in report, expect_late)


class ExternalAlertTemplateTests(unittest.TestCase):
    def test_config_template_and_gap_registration(self):
        # 证据用例4: 断主机/断库场景的 stale 判定与配置模板; 不实配、不外发(L48)。
        template = json.loads((ROOT / 'ops/monitoring/alert-webhook.example.json').read_text())
        self.assertEqual(template['vars']['OPS_ALERT_ENABLED'], 'true')
        self.assertEqual(template['vars']['OPS_ALERT_SCOPE'], 'watchdog')
        self.assertIn('<REPLACE-WITH-PRIVATE-BOT-TOKEN>', template['secrets']['OPS_ALERT_WEBHOOK'])
        # 生产缺口如实登记: 根配置仍关闭, 本批不擅自打开。
        root = (ROOT / 'wrangler.jsonc').read_text()
        self.assertIn('"OPS_ALERT_ENABLED": "false"', root)
        # 断主机(无采样到达)时 watchdog stale/恢复判定已有本地单测, 不发真实通知。
        d1test = (ROOT / 'ops/monitoring/tests/worker-d1.test.mjs').read_text()
        self.assertIn("watchdog.status, 'stale'", d1test)
        self.assertIn("watchdog.status, 'fresh'", d1test)
        # 告警关闭时 outbox 不外发(worker/ops.js outboxConfiguration)。
        worker = (ROOT / 'worker/ops.js').read_text()
        self.assertIn("env.OPS_ALERT_ENABLED !== 'true'", worker)


if __name__ == '__main__':
    unittest.main()
