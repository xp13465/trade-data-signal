"""Portable, offline tests for actual NAV control flow and temporary SQLite state.

Only source AST functions are executed. No collector import, credentials, production
DB, source HTTP, notifications, or business CLI is used.
"""
import ast
import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import pathlib
import sqlite3
import tempfile
import textwrap
import types
import pytest
ROOT = Path(__file__).resolve().parents[2]
BASE = (ROOT / 'app/collector/base.py').read_text()

class Clock:

    def __init__(self):
        self.now = 1804540800.0
        self.sleeps = []

    def time(self):
        return self.now

    def monotonic(self):
        return self.now

    def sleep(self, n):
        self.sleeps.append(n)

class Frame:

    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def iterrows(self):
        return enumerate(self.rows)

def extracted(src, names):
    t = ast.parse(src)
    return ast.Module(body=[n for n in t.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])

class Env:

    def __init__(self):
        self.t = tempfile.TemporaryDirectory(prefix='nav-candidate-')
        self.root = pathlib.Path(self.t.name)
        self.db = self.root / 'public_fund.db'
        self.path = self.root / 'progress.json'
        self.clock = Clock()
        self.calls = []
        self.responses = {}
        self.trace = []
        self.source = (ROOT / 'app/collector/public_fund.py').read_text()
        con = sqlite3.connect(self.db)
        con.executescript('CREATE TABLE fund_basic(fund_code TEXT PRIMARY KEY,fund_name TEXT,fund_type TEXT); CREATE TABLE fund_daily_nav(date TEXT,fund_code TEXT,fund_name TEXT,unit_nav REAL,acc_nav REAL,prev_unit_nav REAL,nav_change_pct REAL,PRIMARY KEY(date,fund_code));CREATE INDEX idx_daily_nav_code ON fund_daily_nav(fund_code);')
        con.close()

        def get_conn():
            c = sqlite3.connect(self.db)
            c.set_trace_callback(lambda x: self.trace.append(x))
            return c

        def upstream(symbol, indicator):
            self.calls.append(symbol)
            value = self.responses.get(symbol, 'value')
            if value == 'error':
                raise TimeoutError('fixture transport timeout')
            if value == 'none':
                return None
            if value == 'empty':
                return Frame([])
            if value == 'filtered':
                return Frame([{'净值日期': '19900101', '单位净值': 1.0}])
            return Frame([{'净值日期': '20261105', '单位净值': 1.1234, '日增长率': 0.0}])
        ns = {'get_conn': get_conn, 'PF_STAGE0_PROGRESS_PATH': self.path, 'json': json, 'time': self.clock, 'dt': dt, 'sys': types.SimpleNamespace(argv=['fixture', 'stage0-nav']), 'ak': types.SimpleNamespace(fund_open_fund_info_em=upstream), 'throttle': lambda: None, '_safe_float': lambda x: float(x) if x is not None else None, '_to_yyyymmdd': lambda x: str(x).replace('-', ''), '_STAGE0_DB_VALIDITY': {'nav': 'SELECT DISTINCT fund_code FROM fund_daily_nav', 'fund_manager': 'SELECT DISTINCT fund_code FROM fund_manager'}, '_STAGE0_NAV_RUN_ID': 'run-A', '_STAGE0_NAV_RETRY_SECONDS': 86400, '_STAGE0_NAV_RETRY_CAP': 100}
        ns.update({'os': __import__('os'), '_random': __import__('random')})
        atomic = (ROOT / 'scripts/util_atomic.py').read_text()
        exec(compile(extracted(atomic, {'atomic_write_json', '_tmp_path'}), '<real-atomic-write>', 'exec'), ns)
        exec(compile(extracted(BASE, {'safe_call'}), '<real-safe-call>', 'exec'), ns)
        names = {'fetch_nav_history', '_load_stage0_progress', '_save_stage0_progress', '_prune_stage0_done_vs_db', '_stage0_attempt_strong', '_stage0_nav_valid_codes', '_stage0_nav_validate', '_run_stage0_nav', '_save_stage0_nav_progress'}
        sql_constant = next((n for n in ast.parse(self.source).body if isinstance(n, ast.Assign) and any((isinstance(t, ast.Name) and t.id == '_STAGE0_NAV_VALIDITY_SQL' for t in n.targets))))
        ns['_STAGE0_NAV_VALIDITY_SQL'] = ast.literal_eval(sql_constant.value)
        exec(compile(extracted(self.source, names), 'NAV source functions', 'exec'), ns)
        self.ns = ns
        branch = self.source.split('    elif cmd == "stage0-nav":\n', 1)[1].split('    elif cmd == "stage0-sample":', 1)[0]
        self.branch = compile(textwrap.dedent(branch), 'stage0 branch body', 'exec')

    def pool(self, codes, valid=(), nulls=()):
        c = sqlite3.connect(self.db)
        c.executemany('INSERT INTO fund_basic VALUES (?,?,?)', [(x, 'fixture', '指数型-股票') for x in codes])
        c.executemany('INSERT INTO fund_daily_nav VALUES (?,?,?,?,?,?,?)', [('20261104', x, None, 1.0, None, None, None) for x in valid] + [('20261104', x, None, None, None, None, None) for x in nulls])
        c.commit()
        c.close()

    def progress(self, d):
        self.path.write_text(json.dumps({'nav': d, 'fund_manager': {'done': ['manager-control'], 'attempt': {'manager-control': 'empty0'}, 'total': 1}}))

    def state(self):
        return json.loads(self.path.read_text())

    def run(self):
        before = len(self.calls)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            exec(self.branch, self.ns)
        return {'calls': self.calls[before:], 'log': output.getvalue()[-700:]}

    def count(self, code):
        c = sqlite3.connect(self.db)
        n = c.execute('SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code=? AND unit_nav IS NOT NULL', (code,)).fetchone()[0]
        c.close()
        return n

    def close(self):
        self.t.cleanup()

@pytest.fixture
def env_factory():
    environments = []

    def make(codes, *, done=None, responses=None, valid=(), nulls=(), attempts=None):
        env = Env()
        environments.append(env)
        env.pool(codes, valid=valid, nulls=nulls)
        selected_done = list(codes) if done is None else list(done)
        env.progress({'done': selected_done, 'total': len(codes), 'fail': [], 'attempt': attempts if attempts is not None else {c: 'empty0' for c in selected_done}})
        env.responses.update(responses or {})
        return env
    yield make
    for env in environments:
        env.close()
TARGETS = ['158076', '581070', '158901']

def test_zero_row_legacy_and_placeholder_reenter_once(env_factory):
    env = env_factory(TARGETS, attempts={'158076': 'empty0', '581070': 'empty0'})
    assert set(env.run()['calls']) == set(TARGETS)
    fixture_NAV_rows = {code: env.count(code) for code in TARGETS}
    assert fixture_NAV_rows == {code: 1 for code in TARGETS}
    assert not env.run()['calls']
    assert not env.state()['nav']['retry']

def test_original_any_row_contract_keeps_NULL_unit_done(env_factory):
    env = env_factory(['000001', '000002'], valid=['000001'], nulls=['000002'])
    assert not env.run()['calls']
    assert env.state()['nav']['done'] == ['000001', '000002']
    assert not env.state()['nav']['retry']

@pytest.mark.parametrize('response,expected_calls', [('value', 3), ('empty', 3), ('error', 6)])
def test_NAV_01_fresh_post_save_failure_is_reserved_without_retry_charge(env_factory, response, expected_calls):
    env = env_factory(TARGETS, done=[], responses={c: response for c in TARGETS})
    real_save = env.ns['atomic_write_json']
    writes = []

    def fail_result_save(*args, **kwargs):
        writes.append(1)
        if len(writes) == 2:
            raise OSError('fixture state disk full after fetch')
        return real_save(*args, **kwargs)
    env.ns['atomic_write_json'] = fail_result_save
    with pytest.raises(OSError):
        env.run()
    assert len(env.calls) == expected_calls
    reserved = env.state()['nav']
    assert reserved['retry_run']['count'] == 0
    assert set(reserved['fresh_reserved']) == set(TARGETS)
    assert all(('attempted_at' not in x for x in reserved['retry'].values()))
    env.ns['atomic_write_json'] = real_save
    assert not env.run()['calls']
    env.ns['_STAGE0_NAV_RUN_ID'] = 'run-B'
    assert len(env.run()['calls']) == expected_calls

@pytest.mark.parametrize('response', ['empty', 'filtered', 'error'])
def test_normal_outcomes_cooldown_same_process_and_next_process(env_factory, response):
    env = env_factory(TARGETS, responses={c: response for c in TARGETS})
    env.run()
    state = env.state()['nav']
    assert not state['done']
    assert set(state['fail']) == (set(TARGETS) if response == 'error' else set())
    assert all((x['attempted_at'] == env.clock.now for x in state['retry'].values()))
    assert all((x['next_retry_at'] == env.clock.now + 86400 for x in state['retry'].values()))
    assert not env.run()['calls']
    env.ns['_STAGE0_NAV_RUN_ID'] = 'run-B'
    assert not env.run()['calls']
    env.clock.now += 86401
    env.ns['_STAGE0_NAV_RUN_ID'] = 'run-A'
    assert not env.run()['calls']
    env.ns['_STAGE0_NAV_RUN_ID'] = 'run-C'
    env.responses.update({c: 'value' for c in TARGETS})
    assert set(env.run()['calls']) == set(TARGETS)
    assert not env.state()['nav']['retry']
    assert not env.state()['nav']['fail']

def test_migration_cap_is_per_process_and_deferred_queue_advances(env_factory):
    codes = [f'{i:06d}' for i in range(205)]
    env = env_factory(codes, responses={c: 'empty' for c in codes})
    first = env.run()['calls']
    assert len(first) == 100
    assert not env.run()['calls']
    env.clock.now += 90000
    assert not env.run()['calls']
    env.ns['_STAGE0_NAV_RUN_ID'] = 'run-B'
    second = env.run()['calls']
    assert len(second) == 100 and (not set(first) & set(second))
    assert env.state()['nav']['retry_run']['count'] == 100

def test_first_time_initialization_is_exempt_from_100_retry_budget(env_factory):
    codes = [f'{i:06d}' for i in range(105)]
    env = env_factory(codes, done=[], responses={c: 'empty' for c in codes})
    assert len(env.run()['calls']) == 105
    assert env.state()['nav']['retry_run']['count'] == 0
    assert not env.run()['calls']

def test_failed_pre_GET_reservation_preserves_original_state(env_factory):
    env = env_factory(TARGETS, done=[])
    before = env.path.read_bytes()

    def fail_save(*args, **kwargs):
        raise OSError('fixture readonly state')
    env.ns['atomic_write_json'] = fail_save
    with pytest.raises(OSError):
        env.run()
    assert not env.calls
    assert env.path.read_bytes() == before

def test_invalid_progress_JSON_stops_before_GET(env_factory):
    env = env_factory(TARGETS)
    env.path.write_text('{invalid JSON')
    with pytest.raises(json.JSONDecodeError):
        env.run()
    assert not env.calls
    assert env.path.read_text() == '{invalid JSON'

def test_failed_or_expired_validity_query_does_not_invent_invalid_done(env_factory):
    env = env_factory([f'{i:06d}' for i in range(1001)])
    before = env.path.read_bytes()
    sequence = []

    def advance_during_SQL():
        sequence.append(1)
        return float(len(sequence))
    env.clock.monotonic = advance_during_SQL
    with pytest.raises((sqlite3.OperationalError, TimeoutError)):
        env.run()
    assert not env.calls and env.path.read_bytes() == before

def test_missing_NAV_index_stops_before_progress_or_GET(env_factory):
    env = env_factory(TARGETS)
    before = env.path.read_bytes()
    conn = sqlite3.connect(env.db)
    conn.execute('DROP INDEX idx_daily_nav_code')
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match='missing'):
        env.run()
    assert not env.calls and env.path.read_bytes() == before

def test_manager_legal_empty_and_other_progress_partition_are_unchanged(env_factory):
    env = env_factory(TARGETS)
    before = copy.deepcopy(env.state()['fund_manager'])
    assert env.ns['_load_stage0_progress']('fund_manager') == before
    env.run()
    assert env.state()['fund_manager'] == before

def test_validity_reuses_original_covering_index_contract():
    tree = ast.parse((ROOT / 'app/collector/public_fund.py').read_text())
    validity = next((n for n in tree.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and (n.target.id == '_STAGE0_DB_VALIDITY')))
    assert ast.literal_eval(validity.value)['nav'] == 'SELECT DISTINCT fund_code FROM fund_daily_nav'
