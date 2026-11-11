"""Real producer -> real notify CLI -> real queues/receipts, transport-only fakes.

Run isolated: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest --noconftest ...
The imported fixture positively checks network/process/credential traps.
"""
import importlib.util
import io
import json
import os
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

import pytest
from test_notify_ops_quiet_20261111 import box, SCRIPTS


@pytest.fixture
def producers(box, monkeypatch):
    n, clock, cfg, wire, accepted, seed, state, update, cli, root = box
    modules = []
    for name in ('check_s06_freshness', 'check_monitor_heartbeat'):
        spec = importlib.util.spec_from_file_location('lifecycle_' + name, SCRIPTS / (name + '.py'))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        modules.append(m)
    s06, hb = modules
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0].replace(tzinfo=timezone.utc) if tz else clock[0]
    monkeypatch.setattr(hb, 'datetime', Clock)
    def adapter(cmd, **kw):
        assert Path(cmd[1]).name == 'notify.py'
        assert kw.get('env', {}).get('REPO', str(root)) == str(root)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = n.main(cmd[2:])
        return subprocess.CompletedProcess(cmd, rc, out.getvalue(), err.getvalue())
    monkeypatch.setattr(subprocess, 'run', adapter)
    snap, idx = root / 'snap.json', root / 'idx.json'
    dates = ['20261106', '20261109', '20261110', '20261111']
    idx.write_text(json.dumps({'ohlc': [{'date': d} for d in dates]}))
    def snapshot(healthy):
        snap.write_text(json.dumps({'daily': [{'date': d} for d in (dates if healthy else dates[:1])]}))
    def s06run(notify=True):
        monkeypatch.setattr(sys, 'argv', ['check_s06_freshness.py', '--repo', str(root), '--snap', str(snap), '--index', str(idx)] + (['--notify'] if notify else []))
        return s06.main()
    heartbeat = root / 'heartbeat'
    def hbrun(dry=False):
        return hb.main(['--repo', str(root), '--heartbeat-path', str(heartbeat)] + (['--dry-run'] if dry else []))
    def healthy_hb():
        heartbeat.write_text('complete')
        stamp = clock[0].replace(tzinfo=timezone.utc).timestamp()
        os.utime(heartbeat, (stamp, stamp))
    return box, snapshot, s06run, hbrun, healthy_hb, heartbeat


def flush(box):
    n, clock, *_ = box
    if clock[0].hour >= 23:
        clock[0] += timedelta(days=1)
    clock[0] = clock[0].replace(hour=23, minute=30)
    n.flush_warning_batch()
    n.flush_digest()


def test_s06_recovers_before_flush(producers):
    b, snap, run, *_ = producers
    snap(False)
    assert run() == 1
    assert not b[3]
    snap(True)
    assert run() == 0
    flush(b)
    assert b[3] == []


def test_heartbeat_same_incident_three_hours_later(producers):
    b, _, _, run, *_ = producers
    assert run() == 0
    assert len(b[3]) == 3
    b[1][0] += timedelta(hours=3)
    assert run() == 0
    assert len(b[3]) == 3


def own_entry(box, prefix):
    return next((k, v) for k, v in box[6]().items() if k.startswith(prefix))


def test_heartbeat_partial_retries_only_missing_channels_and_keeps_ack(producers):
    b, _, _, run, *_ = producers
    b[4].update(email=True, telegram=False, feishu=False)
    assert run() == 2
    key, old = own_entry(b, 'producer_heartbeat|')
    ref = [{'key': key, 'event_id': old['event_id'], 'phase': 'active', 'source_run': None}]
    b[7](ref, acknowledged='2026-11-11 10:00:00', ack_event_id=old['event_id'], ack_owner='offline')
    b[4].update(telegram=True, feishu=True)
    assert run() == 0
    assert [r['channel'] for r in b[3][3:]] == ['telegram', 'feishu']
    assert own_entry(b, 'producer_heartbeat|')[1]['ack_event_id'] == old['event_id']
    assert run() == 0
    assert len(b[3]) == 5


@pytest.mark.parametrize('which', ['s06', 'heartbeat'])
def test_recovery_then_new_fault_does_not_inherit_ack(producers, which):
    b, snap, srun, hrun, heal, heartbeat = producers
    if which == 's06':
        snap(False); assert srun() == 1; flush(b)
    else:
        assert hrun() == 0
    key, first = own_entry(b, 'producer_' + which + '|')
    ref = [{'key': key, 'event_id': first['event_id'], 'phase': 'active', 'source_run': None}]
    b[7](ref, acknowledged='2026-11-11 10:00:00', ack_event_id=first['event_id'])
    before = len(b[3])
    if which == 's06':
        snap(True); assert srun() == 0
        snap(False); assert srun() == 1; flush(b)
    else:
        heal(); assert hrun() == 0
        heartbeat.unlink(); assert hrun() == 0
    current = b[6]()[key]
    assert current['event_id'] != first['event_id']
    assert 'ack_event_id' not in current
    assert current['previous_events'][-1]['ack_event_id'] == first['event_id']
    assert len(b[3]) == before + 3


def test_s06_recovers_after_move_to_digest(producers):
    b, snap, run, *_ = producers
    snap(False); assert run() == 1
    b[1][0] += timedelta(hours=1)
    assert b[0].flush_warning_batch()['digested']
    snap(True); assert run() == 0
    flush(b)
    assert not b[3]


def test_s06_queue_loss_requeues_not_muted_by_local_signature(producers):
    b, snap, run, *_ = producers
    snap(False)
    legacy = b[-1] / 'data/s06_fresh_alert_state.json'
    legacy.write_text(json.dumps({'coverage_end': '20261106', 'n': 3}))
    before = legacy.read_bytes()
    assert run() == 1
    key, entry = own_entry(b, 'producer_s06|')
    b[0].WARNING_BUFFER_FILE.unlink()
    assert run() == 1
    assert b[0].WARNING_BUFFER_FILE.exists()
    assert own_entry(b, 'producer_s06|')[1]['event_id'] == entry['event_id']
    assert legacy.read_bytes() == before
    flush(b)
    assert len(b[3]) == 3


def test_s06_partial_digest_receipt_retry(producers):
    b, snap, run, *_ = producers
    snap(False); assert run() == 1
    b[4].update(email=True, telegram=False, feishu=False)
    flush(b)
    assert len(b[3]) == 3
    b[4].update(telegram=True, feishu=True)
    assert run() == 1
    flush(b)
    assert [r['channel'] for r in b[3][3:]] == ['telegram', 'feishu']
    assert run() == 1
    flush(b)
    assert len(b[3]) == 5


@pytest.mark.parametrize('which', ['s06', 'heartbeat'])
@pytest.mark.parametrize('raw', ['{BROKEN', '[]', '{"other": {"untouched": 1}}'])
def test_bad_or_unrelated_old_state_cannot_swallow_fault(producers, which, raw):
    b, snap, srun, hrun, *_ = producers
    path = b[-1] / 'data/alert_state.json'
    path.write_text(raw)
    if which == 's06':
        snap(False); rc = srun()
        if raw.startswith('{"other"'):
            assert rc == 1; flush(b)
        else:
            assert rc == 2
    else:
        assert hrun() == (0 if raw.startswith('{"other"') else 2)
    assert len(b[3]) == 3
    if raw.startswith('{"other"'):
        assert json.loads(path.read_text())['other'] == {'untouched': 1}
    else:
        assert path.read_text() == raw


def test_dry_runs_never_update_health_or_notify(producers):
    b, snap, srun, hrun, *_ = producers
    snap(False); assert srun(False) == 1; assert hrun(True) == 0
    snap(True); assert srun(False) == 0
    assert not (b[-1] / 'data/alert_state.json').exists()
    assert not b[3]


def test_future_heartbeat_is_fault_not_recovery(producers):
    b, _, _, run, heal, hb = producers
    assert run() == 0
    key, entry = own_entry(b, 'producer_heartbeat|')
    heal()
    stamp = (b[1][0] + timedelta(hours=1)).replace(tzinfo=timezone.utc).timestamp()
    os.utime(hb, (stamp, stamp))
    assert run() == 0
    assert b[6]()[key]['status'] == 'active'
    assert b[6]()[key]['event_id'] == entry['event_id']


def test_opaque_legacy_warning_not_deleted_by_title(producers):
    b, snap, run, *_ = producers
    n = b[0]
    assert n.defer_warning('S06 快照过期 3 日', 'unverifiable legacy payload') == 'enqueued'
    original = n.WARNING_BUFFER_FILE.read_bytes()
    snap(True); assert run() == 0
    assert n.WARNING_BUFFER_FILE.read_bytes() == original
    flush(b)
    # Honest migration boundary: existing opaque entry still follows legacy route.
    assert len(b[3]) == 3


def test_failed_transport_never_consumes_incident(producers):
    b, _, _, run, *_ = producers
    b[4].update(dict.fromkeys(b[4], False))
    assert run() == 2
    _, entry = own_entry(b, 'producer_heartbeat|')
    assert not entry.get('notified_event_id')
    b[4].update(dict.fromkeys(b[4], True))
    assert run() == 0
    assert len(b[3]) == 6


def test_ack_without_receipt_cannot_hide_first_report(producers):
    b, _, _, run, *_ = producers
    b[4].update(dict.fromkeys(b[4], False)); assert run() == 2
    key, entry = own_entry(b, 'producer_heartbeat|')
    b[7]([{'key': key}], acknowledged='2026-11-11 10:00:00', ack_event_id=entry['event_id'])
    b[4].update(dict.fromkeys(b[4], True)); assert run() == 0
    assert len(b[3]) == 6


def test_recovery_between_transports_cancels_remaining_channels(producers):
    b, _, _, run, heal, _ = producers
    def recover(body):
        heal(); assert run() == 0
        return True
    b[4]['email'] = recover
    assert run() == 2  # lost claim mid-send is unknown, never fabricated success
    assert [r['channel'] for r in b[3]] == ['email']
    assert own_entry(b, 'producer_heartbeat|')[1]['status'] == 'recovered'


def test_concurrent_producers_share_one_incident_and_preserve_other_keys(box):
    from concurrent.futures import ThreadPoolExecutor
    from ops_legacy_events import observe
    n, _, _, wire, _, seed, state, *_ = box
    seed(key='unrelated', marker='preserve')
    root = box[-1]
    def work(_):
        return observe(root, 'producer_s06|concurrent', lambda: {'action': True, 'message': 'fault'})[1][0]['event_id']
    with ThreadPoolExecutor(max_workers=6) as pool:
        ids = list(pool.map(work, range(12)))
    assert len(set(ids)) == 1
    assert state()['unrelated']['marker'] == 'preserve'
    assert not wire


def test_s06_unknown_input_does_not_recover_existing_event(producers):
    b, snap, run, *_ = producers
    snap(False); assert run() == 1
    key, old = own_entry(b, 'producer_s06|')
    (b[-1] / 'snap.json').write_text('{broken')
    assert run() == 2
    current = b[6]()[key]
    assert current['status'] == 'active' and current['event_id'] == old['event_id']
    assert len(b[3]) == 3  # fail-visible unknown, no invented healthy baseline


def test_legacy_heartbeat_window_cannot_mute_new_first_report(producers):
    b, _, _, run, *_ = producers
    b[0].DEDUP_FILE.write_text(json.dumps({'schedule_monitor_heartbeat': {'last_alerted': b[1][0].strftime('%Y-%m-%d %H:%M:%S')}}))
    assert run() == 0
    assert len(b[3]) == 3


def test_no_result_file_never_means_delivery(producers, monkeypatch):
    b, _, _, run, *_ = producers
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, 'success', ''))
    assert run() == 2
    assert not own_entry(b, 'producer_heartbeat|')[1].get('notified_event_id')
    assert not b[3]


def test_inconsistent_old_entry_does_not_hide_current_fault(producers):
    b, _, _, run, *_ = producers
    assert run() == 0
    key, old = own_entry(b, 'producer_heartbeat|')
    b[7]([{'key': key}], requires_action=False)  # contradictory active + no action
    assert run() == 0
    assert own_entry(b, 'producer_heartbeat|')[1]['event_id'] != old['event_id']
    assert len(b[3]) == 6


def schedule_ns(box):
    from test_notify_ops_schedule_integration_20261111 import monitor_namespace
    ns, tree = monitor_namespace(box[-1])
    ns['alert_state'] = box[6]()
    ns['_STATE_PRE'] = json.loads(json.dumps(ns['alert_state']))
    ns['CONCLUSION_STATUS_KEY_PREFIX'] = 'conclusion_status|'
    return ns, tree


@pytest.mark.parametrize('which', ['s06', 'heartbeat'])
def test_schedule_cannot_recover_or_route_owned_incident(producers, which):
    import ast
    b, snap, srun, hrun, *_ = producers
    if which == 's06':
        snap(False); assert srun() == 1
    else:
        assert hrun() == 0
    key, old = own_entry(b, 'producer_' + which + '|')
    ns, tree = schedule_ns(b)
    loop = next(n for n in tree.body if isinstance(n, ast.For) and ast.unparse(n.target) == '(_key, _info)')
    exec(compile(ast.Module(body=[loop], type_ignores=[]), 'actual-schedule-recovery', 'exec'), ns)
    assert ns['alert_state'][key] == old
    before = len(b[3])
    assert ns['_quiet_route_alerts']([old['message']]) == []
    assert ns['_active_escalate'](ns['alert_state'][key], key, 'independent') is False
    assert ns['_quiet_send'](key, ns['alert_state'][key], 'recovery', 'fake', 'fake') is False
    assert len(b[3]) == before
    assert b[6]()[key] == old


@pytest.mark.parametrize('which', ['s06', 'heartbeat'])
def test_schedule_stale_snapshot_preserves_new_incident_receipts_and_ack(producers, which):
    b, snap, srun, hrun, heal, hb = producers
    if which == 's06':
        snap(False); assert srun() == 1
    else:
        assert hrun() == 0
    ns, _ = schedule_ns(b)
    key, old = own_entry(b, 'producer_' + which + '|')
    if which == 's06':
        snap(True); assert srun() == 0
        snap(False); assert srun() == 1; flush(b)
    else:
        heal(); assert hrun() == 0
        hb.unlink(); assert hrun() == 0
    fresh = b[6]()[key]
    b[7]([{'key':key}], ack_event_id=fresh['event_id'], acknowledged='now', ack_owner='oncall')
    expected = b[6]()[key]
    assert expected['event_id'] != old['event_id']
    assert ns['save_alert_state'](ns['alert_state'])
    assert b[6]()[key] == expected == ns['alert_state'][key]


def test_schedule_missing_disk_entry_never_revived_and_concurrent_new_key_kept(producers):
    b, _, _, run, *_ = producers
    assert run() == 0
    ns, _ = schedule_ns(b)
    key, _ = own_entry(b, 'producer_heartbeat|')
    path = b[-1] / 'data/alert_state.json'
    path.write_text('{}')
    assert ns['save_alert_state'](ns['alert_state'])
    assert key not in b[6]() and key not in ns['alert_state']
    assert run() == 0
    latest = b[6]()[key]
    ns['alert_state'].pop(key, None)
    assert ns['save_alert_state'](ns['alert_state'])
    assert b[6]()[key] == latest


def test_schedule_never_emits_owned_recovery(producers):
    b, _, _, run, heal, _ = producers
    assert run() == 0
    heal(); assert run() == 0
    ns, _ = schedule_ns(b)
    key, old = own_entry(b, 'producer_heartbeat|')
    rec = {'task':key.split('|')[0], 'keyword':old.get('keyword'), 'first_seen':old['first_seen']}
    assert ns['_quiet_route_recoveries']([rec]) == []
    assert len(b[3]) == 3
    assert b[6]()[key]['status'] == 'recovered'
