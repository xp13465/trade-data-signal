# Offline regression for 0007_ops_content_change_write.sql (A2 write amplification).
# Replays the same 186-check snapshot stream against two chains:
#   OLD = 0001..0006 (prod before this change; every round rewrites every check)
#   NEW = 0001..0007 (content-change-only writes; volatility = evidence only)
# Rows written are measured with SQLite's total_changes() (the local analogue of D1's
# query-level rowsWritten: every INSERT/UPDATE/DELETE, including trigger actions).
# Unknown semantics are asserted by observable transitions/events, never by rewording.
import json
import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / 'migrations'
OLD_CHAIN = ['0001_ops.sql', '0002_watchdog_bootstrap.sql', '0003_check_observation.sql',
             '0004_benefits.sql', '0005_ops_recovery_invocation.sql',
             '0006_ops_observation_inline.sql']
NEW_CHAIN = OLD_CHAIN + ['0007_ops_content_change_write.sql']
BUSINESS = 'business:turnover'


def _build(chain):
    db = sqlite3.connect(':memory:')
    for name in chain:
        db.executescript((MIGRATIONS / name).read_text())
    return db


def _check(i, status='ok', valid_until='2026-11-20T00:00:00Z'):
    cid = BUSINESS if i == 0 else f'data:series-{i:03d}'
    evidence = {'valid_until': valid_until} if i == 0 else {'stable': i}
    if i in (1, 2, 3):  # resource-like checks whose numeric evidence changes every round
        evidence = {'free_bytes': 1000 + i}
    return {'id': cid, 'name': f'check {i}', 'category': 'monitor', 'status': status,
            'observed_at': '2026-11-16T00:00:00.000Z', 'summary': f'check {i} {status}',
            'evidence': evidence, 'reported_status': status, 'observation_status': 'observed',
            '_observed_ms': 0}


def _checks(round_no, statuses=None, drop=None):
    out = []
    for i in range(186):
        if drop is not None and i == drop:
            continue
        status = 'ok'
        if statuses and i in statuses:
            status = statuses[i]
        check = _check(i, status)
        check['observed_at'] = f'2026-11-16T00:{round_no * 15 // 60:02d}:{round_no * 15 % 60:02d}.000Z'
        check['_observed_ms'] = 1000 + round_no * 900000  # every round carries a fresh observation
        if i in (1, 2, 3):
            check['evidence'] = {'free_bytes': 1000 + i + round_no}
        out.append(check)
    return out


def _run(db, snapshot_id, collected_ms, received_ms, checks, collector='cloud-main'):
    snapshot = {'collector_id': collector, 'collected_at': '2026-11-16T00:00:00.000Z',
                'snapshot_id': snapshot_id, 'checks': checks}
    # The worker validates and inserts the envelope's own counts (compact JSON); the
    # 0007 counts guard then only rewrites when the atomically elected counts differ.
    counts = {'ok': 0, 'warning': 0, 'critical': 0, 'unknown': 0}
    for check in checks:
        counts[check['status']] += 1
    before = db.execute('SELECT total_changes()').fetchone()[0]
    db.execute('INSERT INTO ops_runs VALUES(?,?,?,?,?,?,?,?)'
               ' ON CONFLICT(snapshot_id) DO UPDATE SET content_hash=CASE'
               ' WHEN ops_runs.content_hash=excluded.content_hash THEN ops_runs.content_hash ELSE NULL END',
               (snapshot_id, 'hash-' + snapshot_id, collector, collected_ms, received_ms, 120,
                json.dumps(counts, separators=(',', ':')), json.dumps(snapshot)))
    after = db.execute('SELECT total_changes()').fetchone()[0]
    return after - before


def _state(db):
    return {r[0]: r[1:] for r in db.execute(
        'SELECT check_id,status,summary,observed_ms,updated_ms,problem_open,observation_json'
        ' FROM ops_check_state ORDER BY check_id').fetchall()}


def _events(db, kind):
    return db.execute('SELECT check_id,previous_status,status FROM ops_events WHERE kind=? ORDER BY created_ms', (kind,)).fetchall()


def _warm(db):
    """Round 1: initial insert of all 186 checks."""
    return _run(db, 'snap01', 1000, 1100, _checks(1))


def test_unchanged_rounds_write_only_structure_not_186_checks():
    old, new = _build(OLD_CHAIN), _build(NEW_CHAIN)
    old_warm, new_warm = _warm(old), _warm(new)
    # Old predicate (timestamp only) rewrites every check every round.
    assert old_warm >= 186 and new_warm >= 186
    old_round = _run(old, 'snap02', 901000, 901100, _checks(2))
    new_round = _run(new, 'snap02', 901000, 901100, _checks(2))
    # Old baseline reproduces the production 194-row/round shape (186 checks + structure).
    assert old_round >= 186, old_round
    # New: only the 3 resource-like checks whose evidence changed + structure rows
    # (ops_runs insert + ops_head advance). Unchanged 183 checks are not written.
    assert new_round <= 20, new_round
    assert new_round <= 2 + 3, new_round
    # And the table is complete: all 186 checks are still there.
    assert len(_state(new)) == 186


def test_static_content_round_writes_at_most_structure_rows():
    new = _build(NEW_CHAIN)
    _warm(new)
    static = _checks(2)
    for i in (1, 2, 3):
        static[i]['evidence'] = {'free_bytes': 1000 + i + 1}  # same as round 1
    assert _run(new, 'snap02', 901000, 901100, static) <= 4


def test_transition_and_recovery_each_exactly_once():
    new = _build(NEW_CHAIN)
    _warm(new)
    _run(new, 'snap02', 901000, 901100, _checks(2, statuses={0: 'critical'}))
    assert _events(new, 'alert') == [(BUSINESS, 'ok', 'critical')]
    _run(new, 'snap03', 1801000, 1801100, _checks(3, statuses={0: 'critical'}))
    assert _events(new, 'alert') == [(BUSINESS, 'ok', 'critical')]  # continuing is not a new page
    _run(new, 'snap04', 2701000, 2701100, _checks(4))  # back to ok
    assert _events(new, 'recovery') == [(BUSINESS, 'critical', 'ok')]
    assert _events(new, 'transition') == []


def test_missing_check_marked_unknown_once_then_reappears():
    new = _build(NEW_CHAIN)
    _warm(new)
    _run(new, 'snap02', 901000, 901100, _checks(2, drop=0))
    state = _state(new)
    assert state[BUSINESS][0] == 'unknown'
    assert 'Missing from latest snapshot' in state[BUSINESS][1]
    written = state[BUSINESS][3]
    # A second snapshot without the check must NOT rewrite the already-unknown row.
    delta = _run(new, 'snap03', 1801000, 1801100, _checks(3, drop=0))
    assert _state(new)[BUSINESS][3] == written
    assert delta <= 2 + 3
    assert len(_events(new, 'transition')) == 1
    # Reappearing with content ok produces exactly one further transition and no recovery.
    _run(new, 'snap04', 2701000, 2701100, _checks(4))
    assert _state(new)[BUSINESS][0] == 'ok'
    assert len(_events(new, 'transition')) == 2
    assert _events(new, 'recovery') == []


def test_business_valid_until_change_is_persisted():
    new = _build(NEW_CHAIN)
    _warm(new)
    assert '2026-11-20' in json.loads(_state(new)[BUSINESS][5])['evidence']['valid_until']
    _run(new, 'snap02', 901000, 901100, _checks(2))
    # Same status/name/summary; only evidence (valid_until) changes -> must still be stored.
    changed = _checks(3)
    changed[0]['evidence'] = {'valid_until': '2026-11-21T00:00:00Z'}
    _run(new, 'snap03', 1801000, 1801100, changed)
    stored = json.loads(_state(new)[BUSINESS][5])
    assert stored['evidence']['valid_until'] == '2026-11-21T00:00:00Z'
    assert stored['_observed_ms'] == 1000 + 3 * 900000  # the write carries the round's clock


def test_older_observation_with_different_content_cannot_regress():
    new = _build(NEW_CHAIN)
    _warm(new)
    _run(new, 'snap02', 901000, 901100, _checks(2, statuses={0: 'critical'}))
    older = _checks(3)  # content ok, but observation clock is older than the elected critical
    older[0]['_observed_ms'] = 500
    older[0]['observed_at'] = '2026-11-15T23:00:00.000Z'
    _run(new, 'snap03', 1801000, 1801100, older)
    assert _state(new)[BUSINESS][0] == 'critical'


def test_missing_row_is_only_rewritten_when_it_disappears():
    new = _build(NEW_CHAIN)
    _warm(new)
    _run(new, 'snap02', 901000, 901100, _checks(2, drop=0))
    row = _state(new)[BUSINESS]
    assert row[0] == 'unknown'
    # Same missing round again: the unknown row keeps its write clock.
    _run(new, 'snap03', 1801000, 1801100, _checks(3, drop=0))
    assert _state(new)[BUSINESS] == row
