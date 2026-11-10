"""Current execution reconciliation; all I/O sandboxed, no credentials or outbound."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from datetime import datetime, timezone

import pytest

SPEC = importlib.util.spec_from_file_location('ops_recovery_test_module', Path(__file__).resolve().parents[1] / 'ops_monitor.py')
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
UNIT = 'trade-ops-monitor.service'
ROW = {'unit': UNIT, 'task': 'ops_monitor', 'include': True}
# Projected from runtime-cloud.raw.json 2026-11-10T22:52:36+08:00.
DERIVED = {'task': 'ops_monitor', 'unit': UNIT, 'last_exit': 2,
           'unit_exit_source': 'systemd', 'unit_start': '2026-11-10 22:30:00',
           'unit_exit_ts': '2026-11-10 22:30:09', 'unit_result': 'exit-code',
           'unit_missed': False, 'log_anomaly': False, 'exit_conflict': False}
LIVE = {'Id': UNIT, 'LoadState': 'loaded', 'Type': 'oneshot', 'ActiveState': 'inactive',
        'SubState': 'dead', 'Result': 'success', 'ExecMainCode': '1', 'ExecMainStatus': '0',
        'ExecMainStartTimestamp': 'Tue 2026-11-10 22:45:03 CST',
        'ExecMainExitTimestamp': 'Tue 2026-11-10 22:45:09 CST'}
NOW = datetime(2026, 11, 10, 14, 52, 36, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    def deny(*a, **kw):
        raise AssertionError('production/network/process access prohibited')
    for obj, attr in ((socket.socket, 'connect'), (socket, 'create_connection'),
                      (socket, 'getaddrinfo'), (subprocess, 'Popen')):
        monkeypatch.setattr(obj, attr, deny)


def collect(tmp_path, fields=None, item=None, age=60, journal='', now=NOW):
    data = tmp_path / 'static-site/data'
    data.mkdir(parents=True, exist_ok=True)
    path = data / 'schedule_stats.json'
    original = [DERIVED | (item or {})]
    path.write_text(json.dumps(original))
    os.utime(path, (now.timestamp() - age,) * 2)
    class Runner:
        calls = []
        def run(self, args):
            self.calls.append(args)
            if isinstance(journal, Exception):
                raise journal
            return journal
    runner = Runner()
    cfg = m.Settings(data_root=str(tmp_path), code_root=str(tmp_path), output_dir=str(tmp_path / 'out'))
    c = m.Collector(cfg, runner=runner, now=now)
    c.unit_observations[UNIT] = {k: [v] for k, v in (LIVE | (fields or {})).items()}
    c.schedule([ROW])
    result = next(x for x in c.checks if x['id'] == 'schedule:ops_monitor')
    assert json.loads(path.read_text()) == original, 'historical producer must not be rewritten'
    return result, runner


def test_observed_completed_recovery(tmp_path):
    c, r = collect(tmp_path)
    assert c['status'] == 'ok'
    assert c['evidence']['derived_exit_code'] == 2
    assert c['evidence']['derived_exit_utc'] == '2026-11-10T14:30:09Z'
    assert c['evidence']['completed_at_utc'] == '2026-11-10T14:45:09Z'
    assert c['evidence']['recovery_verified'] is True
    assert r.calls == []


@pytest.mark.parametrize('fields', [
    {'ActiveState': 'activating', 'SubState': 'start', 'ExecMainExitTimestamp': ''},
    {'ExecMainStartTimestamp': ''}, {'ExecMainExitTimestamp': ''},
    {'ExecMainExitTimestamp': 'Tue 2026-11-10 22:44:00 CST'},
    {'ExecMainExitTimestamp': 'Tue 2026-11-10 23:00:00 CST'},
    {'ExecMainStartTimestamp': 'Tue 2026-11-10 22:00:00 CST', 'ExecMainExitTimestamp': 'Tue 2026-11-10 22:15:15 CST'},
    {'ExecMainCode': '2'}, {'Type': 'simple'}, {'LoadState': 'not-found'},
])
def test_no_unproved_success(tmp_path, fields):
    c, _ = collect(tmp_path, fields=fields)
    assert c['status'] == 'warning'
    assert not c['evidence'].get('recovery_verified')


@pytest.mark.parametrize('item', [{'unit_start': None}, {'unit_exit_ts': None},
    {'unit_start': '2026-11-10 22:40:00'}, {'unit': 'trade-other.service'},
    {'unit_exit_source': 'ledger-stale'}, {'exit_conflict': True},
    {'log_anomaly': True}, {'unit_missed': True}])
def test_missing_or_conflicting_derived_identity_not_cleared(tmp_path, item):
    c, _ = collect(tmp_path, item=item)
    assert c['status'] != 'ok'
    assert not c['evidence'].get('recovery_verified')


def test_stale_input_remains_unknown(tmp_path):
    c, _ = collect(tmp_path, age=1801)
    assert c['status'] == 'unknown'
    assert not c['evidence'].get('recovery_verified')


def test_new_failure_overrides_previous_success(tmp_path):
    c, _ = collect(tmp_path, item={'last_exit': 0, 'unit_result': 'success'},
                   fields={'ActiveState': 'failed', 'SubState': 'failed', 'Result': 'exit-code', 'ExecMainStatus': '2'})
    assert c['status'] == 'warning'
    assert c['evidence']['exit_code'] == 2
    assert c['evidence']['derived_exit_code'] == 0


def test_utc_local_midnight_and_same_time_not_newer(tmp_path):
    now = datetime(2026, 11, 10, 16, 10, tzinfo=timezone.utc)
    item = {'unit_start': '2026-11-10 23:59:00', 'unit_exit_ts': '2026-11-10 23:59:09'}
    fields = {'ExecMainStartTimestamp': '2026-11-10T16:00:03Z', 'ExecMainExitTimestamp': 'Wed 2026-11-11 00:00:09 CST'}
    c, _ = collect(tmp_path, fields=fields, item=item, now=now)
    assert c['status'] == 'ok'
    assert c['evidence']['completed_at_utc'] == '2026-11-10T16:00:09Z'
    c, _ = collect(tmp_path, fields={'ExecMainStartTimestamp': '2026-11-10T14:30:00Z',
                                   'ExecMainExitTimestamp': '2026-11-10T14:30:09Z'})
    assert c['status'] == 'warning'


def journal_pair(at='2026-11-10T14:45:09+00:00', successful=True, invocation='a' * 32):
    micros = str(int(datetime.fromisoformat(at).timestamp() * 1000000))
    # Schema from systemd job.c + collector main stdout. Live fixture checked separately.
    app = {'__REALTIME_TIMESTAMP': micros, '_BOOT_ID': 'b' * 32, '_PID': '1234',
           '_SYSTEMD_UNIT': UNIT, 'SYSLOG_IDENTIFIER': 'trade-ops-monitor',
           '_SYSTEMD_INVOCATION_ID': invocation,
           'MESSAGE': json.dumps({'snapshot_id': 'fd5cca3f-bc3c-4f7a-a523-8b64614f1d1a',
                                 'checks': 177, 'delivery_ok': successful, 'collect_only': False,
                                 'delivery': {'http_status': 200} if successful else {'error_kind': 'NetworkDeadline'}})}
    done = {'__REALTIME_TIMESTAMP': str(int(micros) + 100), '_BOOT_ID': 'b' * 32,
            '_PID': '1', 'UNIT': UNIT, 'INVOCATION_ID': invocation, 'JOB_TYPE': 'start',
            'JOB_RESULT': 'done' if successful else 'failed',
            'MESSAGE_ID': '39f53479d3a045ac8e11786248231fbf' if successful else 'be02cf6855d2428ba40df7e9d022f03d'}
    return [app, done]


def running():
    return {'ActiveState': 'activating', 'SubState': 'start',
            'ExecMainStartTimestamp': 'Tue 2026-11-10 22:50:00 CST', 'ExecMainExitTimestamp': ''}


def test_running_self_uses_proved_previous_completion(tmp_path):
    records = journal_pair()
    records.append({'_PID': '1', 'UNIT': UNIT, 'JOB_TYPE': 'start',
                    'MESSAGE_ID': '7d4958e842da4a758f6c1cdc7b36dcc5'})  # current Starting, not terminal
    raw = '\n'.join(map(json.dumps, records))
    c, r = collect(tmp_path, fields=running(), journal=raw)
    assert c['status'] == 'ok'
    assert c['evidence']['completion_source'] == 'systemd_journal'
    assert c['evidence']['execution_state'] == 'running'
    assert c['evidence']['recovery_verified']
    assert c['evidence']['derived_exit_code'] == 2
    assert len(r.calls) == 1
    assert r.calls[0][0] == '/usr/bin/journalctl'
    assert '--lines=64' in r.calls[0]


@pytest.mark.parametrize('case', ['denied', 'empty', 'truncated', 'badjson', 'no_app', 'no_done',
    'bad_invocation', 'wrong_boot', 'wrong_unit', 'forged_manager', 'no_time', 'future',
    'old', 'current_round', 'collect_only', 'delivery_failed', 'no_200', 'newer_failure', 'wrong_job'])
def test_journal_never_borrows_unproved_or_superseded_success(tmp_path, case):
    records = journal_pair()
    if case == 'no_app': records = records[1:]
    elif case == 'no_done': records = records[:1]
    elif case == 'bad_invocation': records[1]['INVOCATION_ID'] = 'c' * 32
    elif case == 'wrong_boot': records[1]['_BOOT_ID'] = 'c' * 32
    elif case == 'wrong_unit': records[1]['UNIT'] = 'trade-other.service'
    elif case == 'forged_manager': records[1]['_PID'] = '1234'
    elif case == 'no_time': records[1].pop('__REALTIME_TIMESTAMP')
    elif case == 'future': records = journal_pair('2026-11-11T14:45:09+00:00')
    elif case == 'old': records = journal_pair('2026-11-10T13:45:09+00:00')
    elif case == 'current_round': records = journal_pair('2026-11-10T14:50:01+00:00')
    elif case == 'collect_only':
        msg = json.loads(records[0]['MESSAGE']); msg['collect_only'] = True; records[0]['MESSAGE'] = json.dumps(msg)
    elif case == 'delivery_failed':
        msg = json.loads(records[0]['MESSAGE']); msg['delivery_ok'] = False; records[0]['MESSAGE'] = json.dumps(msg)
    elif case == 'no_200':
        msg = json.loads(records[0]['MESSAGE']); msg['delivery'] = {}; records[0]['MESSAGE'] = json.dumps(msg)
    elif case == 'newer_failure': records += journal_pair('2026-11-10T14:49:09+00:00', False, 'd' * 32)
    elif case == 'wrong_job': records[1]['JOB_TYPE'] = 'stop'
    raw = '\n'.join(map(json.dumps, records))
    if case == 'denied': raw = PermissionError('private forbidden details')
    elif case == 'empty': raw = ''
    elif case == 'badjson': raw = '{'
    elif case == 'truncated': raw = raw[:-12]
    c, _ = collect(tmp_path, fields=running(), journal=raw)
    assert c['status'] == 'warning'
    assert not c['evidence'].get('recovery_verified')
    assert 'private forbidden' not in json.dumps(c)


def test_journal_later_failed_completion_replaces_old_ok(tmp_path):
    records = journal_pair(successful=False)
    c, _ = collect(tmp_path, fields=running(), item={'last_exit': 0}, journal='\n'.join(map(json.dumps, records)))
    assert c['status'] == 'warning'
    assert c['evidence']['latest_completed_success'] is False


def test_journal_missing_does_not_call_running_success(tmp_path):
    c, _ = collect(tmp_path, fields=running(), item={'last_exit': 0})
    assert c['status'] == 'unknown'
    assert c['evidence']['execution_state'] == 'running'


@pytest.mark.parametrize('raw', ['x' * (m.MAX_COMMAND + 1), '{}\n' * 65])
def test_oversized_journal_preserves_failure(tmp_path, raw):
    c, _ = collect(tmp_path, fields=running(), journal=raw)
    assert c['status'] == 'warning'
    assert c['evidence']['completion_error_kind'] == 'LimitError'


def test_journal_command_is_fixed_and_capabilities_cannot_expand():
    runner = m.CommandRunner(m.Budget(1))
    for args in ([*m.SELF_JOURNAL, '--since=@-1'], [*m.SELF_JOURNAL, '--since=@123', '--all'],
                 ['/usr/bin/journalctl', '--unit=trade-other.service'], ['/bin/sh', '-c', 'true']):
        with pytest.raises(m.ContractError): runner.run(args)
    # The fixed allowed command reaches the already-patched process boundary.
    with pytest.raises(AssertionError, match='production/network/process'):
        runner.run([*m.SELF_JOURNAL, '--since=@1794319200'])


def test_ambiguous_terminal_order_does_not_clear_failure(tmp_path):
    records = journal_pair()
    records.append(records[-1] | {'JOB_RESULT': 'failed', 'MESSAGE_ID': 'be02cf6855d2428ba40df7e9d022f03d'})
    c, _ = collect(tmp_path, fields=running(), journal='\n'.join(map(json.dumps, records)))
    assert c['status'] == 'warning'


def test_reconciled_evidence_passes_actual_ingest_safety_contract(tmp_path):
    c, _ = collect(tmp_path, fields=running(), journal='\n'.join(map(json.dumps, journal_pair())))
    snapshot = {'schema_version': 1, 'snapshot_id': 'fd5cca3f-bc3c-4f7a-a523-8b64614f1d1a',
                'collector_id': 'offline-fixture', 'collected_at': NOW.isoformat(), 'code_ref': 'unknown',
                'duration_ms': 1, 'checks': [c], 'coverage': {'counts': {'checks': 1}, 'limitations': []}}
    m.validate_snapshot(snapshot)


@pytest.mark.parametrize('current_start,now,old_start,old_end,expected', [
    ('2026-11-10T14:30:00Z', '2026-11-10T14:30:01Z', '2026-11-10 22:00:14', '2026-11-10 22:00:22', 'ok'),
    ('2026-11-10T14:45:03Z', '2026-11-10T14:45:04Z', '2026-11-10 22:30:00', '2026-11-10 22:30:09', 'warning'),
    ('2026-11-10T15:00:07Z', '2026-11-10T15:00:08Z', '2026-11-10 22:30:00', '2026-11-10 22:30:09', 'ok'),
])
def test_real_cloud_journal_success_failure_success_sequence(tmp_path, current_start, now, old_start, old_end, expected):
    fixture = json.loads((Path(__file__).parent / 'fixtures/ops_monitor_recovery_20261110.json').read_text())
    frozen = datetime.fromisoformat(now.replace('Z', '+00:00'))
    # Replay only events already visible at that snapshot; no future success borrowed.
    rows = [r for r in fixture['records'] if int(r['__REALTIME_TIMESTAMP']) / 1e6 <= frozen.timestamp()]
    c, _ = collect(tmp_path, fields=running() | {'ExecMainStartTimestamp': current_start},
                   item={'unit_start': old_start, 'unit_exit_ts': old_end},
                   journal='\n'.join(map(json.dumps, rows)), now=frozen)
    assert c['status'] == expected
    assert c['evidence']['derived_exit_code'] == 2
    assert c['evidence']['recovery_verified'] is (expected == 'ok')
    assert c['evidence']['completion_source'] == 'systemd_journal'
