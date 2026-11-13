# Offline equivalence regression for 0006_ops_observation_inline.sql.
# The same snapshot sequence is replayed against two chains:
#   OLD = 0001..0005 (current production), NEW = 0001..0006 (with 0006).
# Every user-visible column must match bit for bit; the only permitted difference
# is rows_read/work, never content. See /tmp/monitor-quota-20261113.md for the
# D1 read-amplification root cause this migration fixes.
import json
import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'
OLD_CHAIN = ['0001_ops.sql', '0002_watchdog_bootstrap.sql', '0003_check_observation.sql',
             '0004_benefits.sql', '0005_ops_recovery_invocation.sql']
NEW_CHAIN = OLD_CHAIN + ['0006_ops_observation_inline.sql']
SEVERE = 'cloud-service:trade-public-fund-daily.service'
SEVERE2 = 'cloud-service:trade-overfit-monitor.service'


def _build(chain):
    db = sqlite3.connect(':memory:')
    for name in chain:
        db.executescript((MIGRATIONS / name).read_text())
    return db


def _severe(status, invocation, observed_ms, start_ms=None, exit_ms=None):
    start = f'2026-11-13T00:0{10 if start_ms is None else start_ms // 10000}:00.000Z'
    exit_ = f'2026-11-13T00:0{11 if exit_ms is None else exit_ms // 10000}:00.000Z'
    return {'id': SEVERE, 'name': 'severe service', 'status': status, 'summary': f'severe {status}',
            '_observed_ms': observed_ms,
            'evidence': {'execution_state': 'completed', 'exit_code': 0, 'unit_result': 'success',
                         'invocation_id': invocation, 'last_start_utc': start, 'last_exit_utc': exit_}}


def _check(cid, status, observed_ms, name='normal check'):
    return {'id': cid, 'name': name, 'status': status, 'summary': f'{cid} {status}',
            '_observed_ms': observed_ms, 'evidence': {}}


def _run(db, snapshot_id, collected_ms, received_ms, checks):
    snapshot = {'collector_id': 'cloud-main', 'collected_at': '2026-11-13T00:00:00.000Z',
                'snapshot_id': snapshot_id, 'checks': checks}
    # Same idempotent upsert the worker's ingest path uses (content-hash guarded).
    db.execute('INSERT INTO ops_runs VALUES(?,?,?,?,?,?,?,?)'
               ' ON CONFLICT(snapshot_id) DO UPDATE SET content_hash=CASE'
               ' WHEN ops_runs.content_hash=excluded.content_hash THEN ops_runs.content_hash ELSE NULL END',
               (snapshot_id, 'hash-' + snapshot_id, 'cloud-main', collected_ms, received_ms, 120,
                json.dumps({'ok': 0, 'warning': 0, 'critical': 0, 'unknown': 0}), json.dumps(snapshot)))


def _dump(db):
    return {
        'check_state': db.execute(
            'SELECT collector_id,check_id,name,status,observed_ms,collected_ms,snapshot_id,updated_ms,'
            'problem_open,summary,observation_json,recovery_failure_invocation,recovery_failure_ms'
            ' FROM ops_check_state ORDER BY collector_id,check_id').fetchall(),
        'head': db.execute('SELECT * FROM ops_head').fetchall(),
        'watchdog': db.execute('SELECT * FROM ops_watchdog').fetchall(),
        'runs': db.execute(
            'SELECT snapshot_id,collector_id,collected_ms,received_ms,counts_json FROM ops_runs'
            ' ORDER BY snapshot_id').fetchall(),
        # event_id is randomblob(16): compare everything except it.
        'events': db.execute(
            'SELECT source,check_id,previous_status,status,kind,summary,created_ms FROM ops_events'
            ' ORDER BY created_ms,source,check_id,kind').fetchall(),
    }


def _replay(chain):
    db = _build(chain)
    # 1. Initial severe failure anchor + a normal warning + an ok check.
    _run(db, 'snap1', 1000, 1100, [_severe('critical', 'a' * 32, 900),
                                   _check('data:series', 'warning', 950),
                                   _check('timer:cleanup', 'ok', 980)])
    # 2. Valid severe recovery (different invocation, later start) + dropped check.
    _run(db, 'snap2', 61000, 61100, [_severe('ok', 'b' * 32, 60900, start_ms=55000, exit_ms=60000),
                                     _check('timer:cleanup', 'ok', 60950)])
    # 3. Same failed invocation replayed as ok: must NOT be accepted as recovery.
    _run(db, 'snap3', 121000, 121100, [_severe('ok', 'a' * 32, 120900, start_ms=115000, exit_ms=120000),
                                       _check('timer:cleanup', 'ok', 120950)])
    # 4. Older collected envelope with fresher per-check clock: nothing regresses.
    _run(db, 'snap4', 500, 181000, [_severe('ok', 'c' * 32, 200000, start_ms=190000, exit_ms=195000),
                                    _check('timer:cleanup', 'ok', 200050)])
    # 5. Duplicate same snapshot id/content: idempotent, no trigger work.
    _run(db, 'snap1', 1000, 1100, [_severe('critical', 'a' * 32, 900),
                                   _check('data:series', 'warning', 950),
                                   _check('timer:cleanup', 'ok', 980)])
    # 6. Second severe service first-seen critical with non-verified ok observation.
    _run(db, 'snap6', 241000, 241100, [
        {**_severe('ok', 'd' * 32, 240900, start_ms=235000, exit_ms=240000), 'id': SEVERE2},
        _check('timer:cleanup', 'warning', 240950)])
    return db


def test_0006_equivalence_old_vs_new_chain():
    old, new = _dump(_replay(OLD_CHAIN)), _dump(_replay(NEW_CHAIN))
    assert old == new


def test_observation_json_matches_own_check_value():
    db = _replay(NEW_CHAIN)
    rows = db.execute('SELECT check_id,observation_json FROM ops_check_state WHERE snapshot_id=\'snap3\'').fetchall()
    assert rows
    for check_id, observation_json in rows:
        value = json.loads(observation_json)
        assert value['id'] == check_id  # observation is the check's own value from the same snapshot


def test_0003_observation_triggers_are_gone_after_0006():
    db = _build(NEW_CHAIN)
    names = {r[0] for r in db.execute(
        'SELECT name FROM sqlite_master WHERE type=\'trigger\'').fetchall()}
    assert 'ops_check_observation_insert' not in names
    assert 'ops_check_observation_update' not in names
    # 0005 triggers are all retained verbatim.
    for kept in ('ops_run_insert', 'ops_severe_anchor_insert', 'ops_severe_anchor_update',
                 'ops_check_initial', 'ops_check_transition', 'ops_watchdog_initial',
                 'ops_watchdog_transition', 'ops_override_insert', 'ops_override_update',
                 'ops_event_outbox'):
        assert kept in names, kept


def test_policy_version_stays_two():
    db = _build(NEW_CHAIN)
    assert db.execute('SELECT version FROM ops_recovery_policy WHERE id=1').fetchone()[0] == 2
