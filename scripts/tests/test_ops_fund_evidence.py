"""Current NAV facts on temporary SQLite only; no production collector/network."""
import hashlib
import json
import socket
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from scripts import ops_fund_evidence as ev
from scripts import ops_business_evidence as business
from scripts import collect_fof_nav as fof
from app.collector import public_fund as pf
from scripts.tests.test_collect_fof_nav_333 import _conn, _seed_basic


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED', '1')
    monkeypatch.setenv('INVOCATION_ID', 'test-invocation')
    monkeypatch.delenv('OPS_FUND_RUN', raising=False)
    monkeypatch.delenv('OPS_FUND_STARTED', raising=False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('network forbidden'))
    monkeypatch.setattr(pf.ak, 'fund_open_fund_daily_em', lambda: None, raising=False)
    monkeypatch.setattr(fof, 'RATE_LIMIT', 0)
    monkeypatch.setattr(fof, '_acquire_lock', lambda **k: True)
    monkeypatch.setattr(fof, 'init_db', lambda: None)
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: pytest.fail('API not mocked'))


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / 'data/public_fund.db'
    path.parent.mkdir()
    _conn(path).close()
    for mod in (pf, fof):
        monkeypatch.setattr(mod, 'DB_PATH', path)
        monkeypatch.setattr(mod, 'get_conn', lambda: _conn(path))
    return path


def read(root, obj='fof-nav'):
    r = business.bounded_json(root / ('data/ops_delivery/index/' + obj + '.json'))
    return r, r['consumer_witness'].get('fund_evidence', {})


def seed(db, n=1):
    _seed_basic(db, [(f'{i:06d}', 'FOF', 'FOF-均衡型') for i in range(1, n + 1)])


def row(code='000001'):
    return dict(date='20261106', fund_code=code, unit_nav=1.154, acc_nav=1.154,
                prev_unit_nav=1.1713, nav_change_pct=-1.48)


def snapshot(new='1.20'):
    return pd.DataFrame([{'基金代码': '000001', '基金简称': 'A',
                         '2026-11-11-单位净值': new, '2026-11-11-累计净值': new,
                         '2026-11-10-单位净值': '1.10', '2026-11-10-累计净值': '1.10'},
                        {'基金代码': '000002', '基金简称': 'B',
                         '2026-11-11-单位净值': '', '2026-11-10-单位净值': ''}])


@pytest.mark.parametrize('new,target,fallback', [('1.20', '20261111', False), ('', '20261110', True)])
def test_daily_source_date_and_commit_not_global_max(db, tmp_path, monkeypatch, new, target, fallback):
    monkeypatch.setenv('OPS_FUND_STARTED', '2026-11-11T08:20:00Z')
    monkeypatch.setattr(pf, 'safe_call', lambda *a, **k: snapshot(new))
    monkeypatch.setattr(pf, 'fill_row_prev_pct', lambda d, c, u, prev, pct, cache, **k: (2.0, 3.0))
    assert pf.fetch_daily_nav() == 2
    r, facts = read(tmp_path, 'public-fund')
    assert r['stage_status'] == 'unknown'
    assert r['session_date'] == '2026-11-11'  # invocation date, not source NAV date
    assert facts['scope']['selected_date'] == target
    assert facts['scope']['latest_column_unpublished'] is fallback
    assert facts['counts']['published_rows'] == facts['counts']['committed_rows'] == 1
    assert facts['counts']['unpublished_rows'] == 1
    assert facts['counts']['committed_statements'] == 2
    assert facts['publication_status'] == 'unknown'
    # Actual DB state is independently compared; no global latest-row inference.
    con = _conn(db)
    rows = con.execute('SELECT date,fund_code,unit_nav FROM fund_daily_nav ORDER BY fund_code').fetchall()
    assert [tuple(x) for x in rows] == [(target, '000001', float(new or '1.10')), (target, '000002', None)]
    con.close()
    assert r['inputs'][0]['sha256'] != r['outputs'][0]['sha256']  # derived prev/pct bound after commit
    from scripts import ops_nav_publication as nav
    raw = nav._input_path(tmp_path, 'public-fund', r['attempt_id']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == facts['publication_input']['sha256']
    assert json.loads(raw)['rows'] == [['000001', target, float(new or '1.10'), float(new or '1.10')]]


@pytest.mark.parametrize('kind,status,reason', [('exception', 'failure', 'source_error'),
    ('none', 'unknown', 'source_empty_unclassified'), ('bad_columns', 'failure', 'source_date_columns_missing'),
    ('unpublished', 'unknown', 'source_observed')])
def test_daily_empty_error_and_unpublished_differ(db, tmp_path, monkeypatch, kind, status, reason):
    value = {'exception': RuntimeError('no source'), 'none': None,
             'bad_columns': pd.DataFrame([{'基金代码': '000001'}]),
             'unpublished': pd.DataFrame([{'基金代码': '000001', '2026-11-11-单位净值': ''}])}[kind]
    monkeypatch.setattr(pf, 'safe_call', lambda *a, **k: value)
    assert pf.fetch_daily_nav() == 0
    r, f = read(tmp_path, 'public-fund')
    assert r['stage_status'] == status
    assert f['reason'] == reason
    assert f['publication_status'] == 'unknown'
    assert not r['outputs']


def test_daily_failed_commit_has_source_but_no_persistence(db, tmp_path, monkeypatch):
    monkeypatch.setattr(pf, 'safe_call', lambda *a, **k: snapshot())
    monkeypatch.setattr(pf, 'fill_row_prev_pct', lambda *a, **k: (None, None))
    class Failed(sqlite3.Connection):
        def commit(self):
            self.rollback()
            raise sqlite3.OperationalError('commit failed')
    monkeypatch.setattr(pf, 'get_conn', lambda: sqlite3.connect(db, factory=Failed))
    with pytest.raises(sqlite3.OperationalError):
        pf.fetch_daily_nav()
    r, f = read(tmp_path, 'public-fund')
    assert r['stage_status'] == 'failure' and not r['outputs']
    assert f['counts']['published_rows'] == 1 and f['counts']['committed_rows'] == 0


def test_fof_mixed_commits_empty_errors_and_outside_batch(db, tmp_path, monkeypatch):
    seed(db, 4)
    def fetch(code, *a, **k):
        if code == '000002': return []
        if code == '000003': raise TimeoutError('source')
        return [row(code)]
    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    assert fof.collect(limit=3) == 1
    assert not fof.LAST_BATCH_FAILED  # existing partial rc0 preserved; evidence exposes failure
    r, f = read(tmp_path)
    assert r['stage_status'] == 'failure'
    assert f['scope']['selected_codes'] == ['000001', '000002', '000003']
    assert f['counts'] == dict(selected=3, attempted=3, committed_targets=2, published_rows=1,
        committed_rows=1, legal_empty=1, errors=1, selected_not_attempted=0, pool_not_attempted=1,
        query_ranges_attempted=3, query_ranges_returned=2)
    assert f['publication_status'] == 'unknown'
    con = _conn(db)
    assert con.execute('SELECT count(*) FROM fund_daily_nav WHERE unit_nav IS NOT NULL').fetchone()[0] == 1
    con.close()

    # Real collector's committed prefix, not a source-response-only witness.
    from scripts import ops_nav_publication as nav
    raw = nav._input_path(tmp_path, 'fof-nav', r['attempt_id']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == f['publication_input']['sha256']
    assert json.loads(raw)['rows'] == [['000001', '20261106', 1.154, 1.154]]


def test_fof_500_batch_is_never_full_pool(db, tmp_path, monkeypatch):
    seed(db, 501)
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: [])
    assert fof.collect() == 0
    r, f = read(tmp_path)
    assert r['stage_status'] == 'unknown' and not fof.LAST_BATCH_FAILED
    assert f['counts']['pool_not_attempted'] == 1 and f['counts']['legal_empty'] == 500
    assert f['counts']['committed_rows'] == 0
    assert f['historical_completeness'] == 'unknown'
    assert len(f['samples']) == 8
    assert len(json.dumps(r).encode()) < 65536


def test_fof_timeout_retains_committed_prefix_and_unattempted_tail(db, tmp_path, monkeypatch):
    seed(db, 3)
    from app.collector import public_fund_gap as gap
    clock = [0.0]
    # clock only the collector/gap modules via replacement, not evidence timing.
    from types import SimpleNamespace
    monkeypatch.setattr(fof, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 0))
    monkeypatch.setattr(gap, 'remaining', lambda deadline: 1)
    def fetch(code, *a, **k):
        clock[0] = 291
        return [row(code)]
    monkeypatch.setattr(fof, 'fetch_lsjz', fetch)
    with pytest.raises(TimeoutError): fof.collect(limit=3)
    r, f = read(tmp_path)
    assert r['stage_status'] == 'failure'
    assert f['counts']['committed_rows'] == 1
    assert f['counts']['attempted'] == 1 and f['counts']['selected_not_attempted'] == 2


def test_fof_conflict_rolls_back_observed_source(db, tmp_path, monkeypatch):
    seed(db)
    con = _conn(db)
    con.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES('20261106','000001',9)")
    con.commit(); con.close()
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: [row()])
    assert fof.collect(limit=1) == 0
    r, f = read(tmp_path)
    assert f['counts']['published_rows'] == 1 and f['counts']['committed_rows'] == 0
    assert r['stage_status'] == 'failure' and not r['outputs']


def test_fof_lock_and_new_round_do_not_reuse_old_success(db, tmp_path, monkeypatch):
    seed(db)
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: [row()])
    fof.collect(limit=1)
    first, _ = read(tmp_path)
    monkeypatch.setattr(fof, '_acquire_lock', lambda **k: False)
    assert fof.collect() == 0
    r, f = read(tmp_path)
    assert r['attempt_id'] != first['attempt_id'] and not r['outputs']
    assert f['reason'] == 'lock_not_attempted' and r['stage_status'] == 'unknown'


@pytest.mark.parametrize('disabled', [False, True])
def test_dry_run_or_disabled_makes_no_receipts(db, tmp_path, monkeypatch, disabled):
    seed(db)
    if disabled: monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED', '0')
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: [])
    fof.collect(dry_run=not disabled)
    assert not (tmp_path / 'data/ops_delivery').exists()


def test_metadata_budget_or_writer_failure_never_changes_business(db, tmp_path, monkeypatch):
    seed(db)
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: [row()])
    monkeypatch.setattr(ev, 'MAX_WORK_SECONDS', 0)
    assert fof.collect(limit=1) == 1
    r, f = read(tmp_path)
    assert f['metadata_failed'] and r['stage_status'] == 'unknown'
    monkeypatch.setattr(business, 'record_result', lambda *a, **k: (_ for _ in ()).throw(OSError('disk')))
    assert fof.collect(limit=1) == 1


def test_shell_rc0_keeps_source_failure_and_does_not_reuse_other_round(db, tmp_path, monkeypatch):
    monkeypatch.setattr(pf, 'safe_call', lambda *a, **k: RuntimeError('source'))
    pf.fetch_daily_nav()
    r, _ = read(tmp_path, 'public-fund')
    ev.shell_result(tmp_path, r['attempt_id'], r['producer_time']['started_at'], 0, 'shell_completed')
    r2, _ = read(tmp_path, 'public-fund')
    assert r2['stage_status'] == 'failure'
    later = business.stamp(business.now() + timedelta(seconds=1))
    ev.shell_result(tmp_path, 'new-shell', later, 0, 'calendar_not_attempted')
    r3, f = read(tmp_path, 'public-fund')
    assert r3['stage_status'] == 'unknown' and not r3['outputs'] and not f


def test_assess_and_acceptance_never_accept_even_a_forged_full_success(tmp_path, monkeypatch):
    from scripts import ops_stability_acceptance as acceptance
    start = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
    finish = start + timedelta(minutes=1)
    monkeypatch.setattr(business, 'now', lambda: finish)
    ident = dict(object_id='nav.json', sha256='a'*64, size=1)
    business.record_result(tmp_path, 'fof-nav', run_id='run', started_at=business.stamp(start),
        finished_at=business.stamp(finish), status='success', expected=1, observed=1,
        code='b'*40, invocation_id='test-invocation', inputs=[ident], outputs=[ident], confirmed=[ident],
        fund_evidence={'version': ev.VERSION, 'collection_status': 'scoped_committed', 'publication_status': 'success'})
    journal = dict(InvocationID='test-invocation', ActiveState='inactive', SubState='dead', Result='success', ExecMainStatus='0')
    status, evidence = business.assess(tmp_path, 'fof-nav', finish, 'b'*40, {k: [v] for k,v in journal.items()})
    assert status == 'unknown' and evidence['source_reason'] == 'fund_publication_unverified'
    (tmp_path / 'journal').write_text('\n'.join(f'{k}={v}' for k,v in journal.items()))
    run = dict(receipt='data/ops_delivery/index/fof-nav.json', journal='journal', journal_complete=True,
               manual_intervention=False, origin='timer', upstream_failure=False)
    slot = dict(object_id='fof-nav', business_date='2026-11-11', scheduled_at=business.stamp(start))
    plan = dict(deployment=dict(code_ref='b'*40, config_sha256=hashlib.sha256(business.RULE.encode()).hexdigest()),
                window_start=business.stamp(start))
    result = acceptance.inspect_run(run, slot, plan, tmp_path, finish, {})
    assert result['status'] == 'unknown' and result['reasons'] == ['fund_publication_unverified']


@pytest.mark.parametrize('collect_rc,deploy_rc,nav_rc', [(0, 0, 0), (0, 0, 10), (0, 7, 0), (2, 0, 0)])
def test_shell_current_run_and_original_exit_codes(tmp_path, collect_rc, deploy_rc, nav_rc):
    import os
    import subprocess
    import sys
    import textwrap
    project = Path(__file__).resolve().parents[2]
    scripts = tmp_path / 'scripts'
    (scripts / 'lib').mkdir(parents=True)
    (tmp_path / '.venv/bin').mkdir(parents=True)
    (scripts / 'public_fund_daily.sh').write_bytes((project / 'scripts/public_fund_daily.sh').read_bytes())
    (scripts / 'lib/repo_paths.sh').write_text('resolve_repo() { REPO="$FIXTURE_ROOT"; }\n')
    (scripts / 'lib/nav_bucket_refresh.sh').write_text(
        'nav_bucket_refresh_run() { return "$FIXTURE_NAV_RC"; }\n'
        'nav_bucket_refresh_blocks_deploy() { [ "$1" != 0 ] && [ "$1" != 10 ]; }\n')
    (scripts / 'deploy.sh').write_text('exit "$FIXTURE_DEPLOY_RC"\n')
    (scripts / 'push_schedule_stats.sh').write_text('exit 0\n')
    # All business commands are inert. Only the real metadata CLI runs.
    py = tmp_path / '.venv/bin/python'
    py.write_text('#!' + sys.executable + '\n' + textwrap.dedent('''
        import os, sys
        if sys.argv[1:3] == ['-m', 'scripts.ops_fund_evidence']:
            from scripts.ops_fund_evidence import main
            sys.argv = ['ops_fund_evidence'] + sys.argv[3:]
            main()
        elif '-c' in sys.argv:
            print(1)
        elif sys.argv[-1] == 'daily':
            from scripts.ops_fund_evidence import Round
            r = Round(os.environ['FIXTURE_ROOT'], 'public-fund')
            r.record()
            sys.exit(int(os.environ['FIXTURE_COLLECT_RC']))
    '''))
    py.chmod(0o700)
    env = dict(os.environ, PYTHONPATH=str(project), PF_DAILY_LOCKED='1', FIXTURE_ROOT=str(tmp_path),
               FIXTURE_COLLECT_RC=str(collect_rc), FIXTURE_DEPLOY_RC=str(deploy_rc), FIXTURE_NAV_RC=str(nav_rc))
    p = subprocess.run(['bash', str(scripts / 'public_fund_daily.sh'), 'force'], env=env,
                       cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert p.returncode == (collect_rc or deploy_rc), p.stdout + p.stderr
    r, f = read(tmp_path, 'public-fund')
    assert r['attempt_id'].startswith('pf-') and f['shell_rc'] == p.returncode
    assert r['stage_status'] == ('failure' if p.returncode else 'unknown')
    assert f['publication_status'] == 'unknown' and not r['outputs']


def test_fund_monitor_projection_respects_scalar_ingest_contract(tmp_path, monkeypatch):
    import ops_monitor as monitor
    from types import SimpleNamespace
    at = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(business, 'now', lambda: at)
    business.record_result(tmp_path, 'public-fund', run_id='daily', started_at=business.stamp(at-timedelta(minutes=1)),
        finished_at=business.stamp(at), code='b'*40, invocation_id='test',
        fund_evidence={'version': ev.VERSION, 'collection_status': 'scoped_committed',
                       'counts': {'published_rows': 42, 'committed_rows': 42}, 'scope': {'private_codes': ['000001']}})
    c = monitor.Collector(SimpleNamespace(data_root=tmp_path, code_root=tmp_path, total_timeout_seconds=20,
                                         command_timeout_seconds=1, collector_id='offline'), now=at)
    monkeypatch.setattr(monitor, 'code_ref', lambda root: 'b'*40)
    c.unit_observations['trade-public-fund-daily.service'] = {
        k: [v] for k,v in dict(InvocationID='test', ActiveState='inactive', SubState='dead',
                               Result='success', ExecMainStatus='0').items()}
    c.business_evidence()
    snapshot = c.snapshot()
    monitor.validate_snapshot(snapshot)
    r = next(x for x in snapshot['checks'] if x['id'] == 'business:public-fund')
    assert len(r['evidence']) <= 20
    assert r['status'] == 'unknown'
    assert r['evidence']['committed_rows'] == 42
    assert r['evidence']['publication_state'] == 'unknown'
    assert 'private_codes' not in json.dumps(snapshot)


def test_current_run_code_and_private_permissions_are_preserved(db, tmp_path, monkeypatch):
    monkeypatch.setattr(pf, 'safe_call', lambda *a, **k: None)
    monkeypatch.setattr(ev, 'loaded_code_identity', lambda fn, root: {'sha': 'b'*40, 'module_sha256': 'c'*64})
    pf.fetch_daily_nav()
    r, _ = read(tmp_path, 'public-fund')
    ev.shell_result(tmp_path, r['attempt_id'], r['producer_time']['started_at'], 0, 'completed')
    new, _ = read(tmp_path, 'public-fund')
    assert new['code_identity'] == r['code_identity']
    import stat
    for path in (tmp_path / 'data/ops_delivery').rglob('*'):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_helper_only_change_invalidates_loaded_identity(tmp_path, monkeypatch):
    before = ev.producer_identity(pf.fetch_daily_nav.__wrapped__, tmp_path)
    monkeypatch.setattr(ev.Round, 'apply', lambda self, action, **data: None)
    after = ev.producer_identity(pf.fetch_daily_nav.__wrapped__, tmp_path)
    assert before['module_sha256'] != after['module_sha256']
    assert before['sha'] == after['sha'] == 'unknown'


def test_direct_script_import_without_repository_on_path(tmp_path):
    import os
    import subprocess
    import sys
    scripts = Path(__file__).resolve().parents[1]
    program = '''
import sys
sys.path.insert(0, sys.argv[1])
import ops_fund_evidence as e
import ops_business_evidence
import ops_stability_acceptance
assert e.assessment({'consumer_witness': {}})[0] == 'unknown'
print('direct script imports OK')
'''
    p = subprocess.run([sys.executable, '-I', '-c', program, str(scripts)], cwd=tmp_path,
                       env={'PATH': os.environ['PATH']}, capture_output=True, text=True, timeout=10)
    assert p.returncode == 0, p.stderr


def test_planned_ranges_are_not_all_claimed_attempted_on_first_error(db, tmp_path, monkeypatch):
    from app.collector import public_fund_gap as gap
    seed(db)
    monkeypatch.setattr(gap, 'plan', lambda *a, **k: {'ranges': [('20261101', '20261106'), ('20260101', '20260201')]})
    monkeypatch.setattr(fof, 'fetch_lsjz', lambda *a, **k: (_ for _ in ()).throw(TimeoutError('first range')))
    assert fof.collect(batch=1) == 0
    r, f = read(tmp_path)
    assert f['counts']['query_ranges_attempted'] == 1
    assert f['counts'].get('query_ranges_returned', 0) == 0
    assert len(f['samples'][0]['planned_ranges']) == 2
    assert f['outcomes'] == [['000001', 'error', 'failed', 0, 0]]
