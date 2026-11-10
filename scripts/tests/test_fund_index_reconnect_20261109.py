"""同源重连回归：固定实测数据、真实恢复助手、隔离假SDK；不导入采集器主体/联网/写库。"""
import ast
import datetime as dt
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = {
    'hs300': [
        ['2026-11-02', '4016.9179', '0.788280'], ['2026-11-03', '4008.8748', '-0.200231'],
        ['2026-11-04', '4101.3350', '2.306388'], ['2026-11-05', '4113.4112', '0.294446'],
        ['2026-11-06', '4054.2769', '-1.437598'], ['2026-11-09', '4056.1081', '0.045167']],
    'csi500': [
        ['2026-11-02', '6420.2268', '2.458270'], ['2026-11-03', '6327.0499', '-1.451302'],
        ['2026-11-04', '6622.0295', '4.662198'], ['2026-11-05', '6740.9272', '1.795487'],
        ['2026-11-06', '6597.3508', '-2.129921'], ['2026-11-09', '6586.1764', '-0.169377']],
    'gem': [
        ['2026-11-02', '2458.6984', '1.867284'], ['2026-11-03', '2391.6518', '-2.726914'],
        ['2026-11-04', '2544.7300', '6.400522'], ['2026-11-05', '2566.8030', '0.867400'],
        ['2026-11-06', '2465.2320', '-3.957101'], ['2026-11-09', '2458.5623', '-0.270551']],
}

# SDK形态依据：login失败10002007；ResultData.next/get_row_data及分页状态取已装SDK。
FAKE_SDK = '''
import json, os
from types import SimpleNamespace
scenario = os.environ['INDEX_TEST_SCENARIO']
sample = json.loads(os.environ['INDEX_TEST_SAMPLE'])
logins = queries = 0
if scenario == 'blocked_import':
    import time
    from pathlib import Path
    Path(os.environ['INDEX_TEST_CHILD_PID']).write_text(str(os.getpid()))
    time.sleep(30)  # 假SDK的长阻塞，不是新增生产超时。

def login():
    global logins
    logins += 1
    print('AUDIT login', logins, flush=True)
    print('AUDIT pid', os.getpid(), flush=True)
    if scenario == 'login_exception' and logins == 1:
        raise ConnectionResetError('connection reset')
    if scenario == 'slow_login' or (scenario in ('slow_login_once', 'slow_then_error') and logins == 1):
        import time
        try: time.sleep(10)
        except Exception: pass  # 模拟SDK吞Exception；预算守卫必须仍能打断。
    code = '10002007' if scenario in ('login_always', 'slow_then_error') or (scenario == 'login_once' and logins == 1) else '0'
    return SimpleNamespace(error_code=code, error_msg='网络接收错误。' if code != '0' else 'success')

def logout():
    if scenario == 'slow_logout':
        import time
        time.sleep(10)
    print('AUDIT logout', flush=True)
    if scenario == 'logout_exception':
        raise OSError('closed')

class Result:
    def __init__(self, first):
        self.first = first
        self.error_code = '10001011' if scenario == 'blacklist' else ('10002007' if first and scenario in ('query_code', 'query_always') else '0')
        if scenario == 'query_always':
            self.error_code = '10002007'
        self.error_msg = '网络接收错误。' if self.error_code != '0' else 'success'
        self.data = [] if scenario == 'empty' else sample
        self.cur_row_num = 0
        self.per_page_count = 10000
        if first and scenario == 'silent_page':
            self.per_page_count = len(sample)
    def next(self):
        if scenario in ('slow_next', 'trickle'):
            import time
            time.sleep(10 if scenario == 'slow_next' else 0.035)
        if (self.first or scenario == 'next_always') and self.cur_row_num == 1:
            if scenario in ('next_code', 'next_always'):
                self.error_code = '10002007'
                self.error_msg = '网络接收错误。'
                return False
            if scenario == 'next_exception':
                raise ConnectionResetError('connection reset')
            if scenario == 'silent_short':
                return False
        return self.cur_row_num < len(self.data)
    def get_row_data(self):
        if self.first and self.cur_row_num == 1 and scenario == 'row_exception':
            raise OSError('broken pipe')
        if self.first and self.cur_row_num == 1 and scenario == 'row_code':
            self.error_code = '10002007'
            return []
        row = self.data[self.cur_row_num]
        self.cur_row_num += 1
        return row

def query_history_k_data_plus(code, fields, **kwargs):
    global queries
    queries += 1
    print('AUDIT query', queries, code, fields, json.dumps(kwargs, sort_keys=True), flush=True)
    if queries == 1 and scenario == 'query_exception':
        raise OSError('broken pipe')
    if scenario == 'slow_query':
        import time
        time.sleep(10)
    return Result(queries == 1)
'''


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """子进程只看到临时假SDK；恢复函数从现有源码AST原样载入，零真实出口。"""
    sdk_file = tmp_path / 'baostock.py'
    sdk_file.write_text(FAKE_SDK)
    pkg = tmp_path / 'app' / 'collector'
    pkg.mkdir(parents=True)
    (pkg.parent / '__init__.py').write_text('')
    (pkg / '__init__.py').write_text('')
    tree = ast.parse((ROOT / 'app/collector/baostock_daily.py').read_text())
    wanted = {'_NETWORK_ERROR_CODES', '_RECONNECT_MAX_RETRIES', '_RECONNECT_INTERVAL'}
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name in ('_ensure_login', '_reconnect_with_retry', '_logout')) or
             (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in wanted for t in n.targets))]
    (pkg / 'baostock_daily.py').write_text(
        'import baostock as bs\nfrom types import SimpleNamespace\n'
        'time = SimpleNamespace(sleep=lambda _: None)\n_logged_in = [False]\n' +
        ast.unparse(ast.Module(body=nodes, type_ignores=[])))
    spec = importlib.util.spec_from_file_location('baostock', sdk_file)
    sdk = importlib.util.module_from_spec(spec)
    monkeypatch.setenv('INDEX_TEST_SCENARIO', 'ok')
    monkeypatch.setenv('INDEX_TEST_SAMPLE', json.dumps(SAMPLES['hs300']))
    spec.loader.exec_module(sdk)
    monkeypatch.setitem(sys.modules, 'baostock', sdk)
    source = (ROOT / 'app/collector/public_fund.py').read_text()
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'fetch_index_daily')
    batches = []
    conn = SimpleNamespace(executemany=lambda sql, rows: batches.append((sql, rows)),
                           execute=lambda *a: None, set_progress_handler=lambda *a: None,
                           commit=lambda: None, close=lambda: None)
    ns = {'dt': dt, 'time': time, 'json': json, 'sys': sys, '_ROOT': tmp_path,
          '_safe_float': lambda x: float(x) if x not in ('', None) else None,
          'get_conn': lambda **kw: conn}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT / 'app/collector/public_fund.py'), 'exec'), ns)
    # 外层只容许启动python -c只读子查询，子进程40秒硬停仅属测试看门狗。
    real_run = subprocess.run
    calls = []
    def run(args, **kwargs):
        assert args[:2] == [sys.executable, '-c']
        assert Path(kwargs['cwd']) == tmp_path
        calls.append(args)
        kwargs['timeout'] = min(kwargs.get('timeout', 40), 40)
        kwargs['env'] = {k: v for k, v in os.environ.items() if k.startswith('INDEX_TEST_')}
        kwargs['env'].update(PATH=os.defpath, HOME=str(tmp_path), PYTHONNOUSERSITE='1')
        return real_run(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', run)
    return SimpleNamespace(fetch=ns['fetch_index_daily'], sdk=sdk, batches=batches,
                           calls=calls, real_run=real_run)


def invoke(env, capsys, monkeypatch, scenario, iid='hs300'):
    monkeypatch.setenv('INDEX_TEST_SCENARIO', scenario)
    monkeypatch.setenv('INDEX_TEST_SAMPLE', json.dumps(SAMPLES[iid]))
    # 基线直接用假SDK，修后子进程用同一固定脚本；两边输入相同。
    env.sdk.scenario = scenario
    env.sdk.sample = SAMPLES[iid]
    try:
        result = env.fetch('20261102', '20261109', iid)
    except RuntimeError as exc:
        result = exc
    return result, capsys.readouterr().out


@pytest.mark.parametrize('scenario', ['login_once', 'login_exception', 'query_code',
                                      'query_exception', 'next_code', 'next_exception',
                                      'row_exception', 'row_code', 'silent_page', 'silent_short'])
def test_replays_whole_query_after_transient_failure(isolated, capsys, monkeypatch, scenario):
    result, output = invoke(isolated, capsys, monkeypatch, scenario)
    assert result == 6
    assert len(isolated.batches) == 1
    assert isolated.batches[0][1] == [(d.replace('-', ''), 'hs300', float(c), float(p))
                                    for d, c, p in SAMPLES['hs300']]
    assert '[baostock reconnect]' in output or '重连' in output
    assert output.count('AUDIT query') == (1 if scenario.startswith('login_') else 2)


@pytest.mark.parametrize('scenario', ['login_always', 'query_always', 'next_always', 'blacklist', 'empty'])
def test_failure_or_legal_empty_never_reaches_writer(isolated, capsys, monkeypatch, scenario):
    result, output = invoke(isolated, capsys, monkeypatch, scenario)
    assert result == 0 if scenario == 'empty' else isinstance(result, RuntimeError)
    assert isolated.batches == []
    assert output.count('AUDIT login') <= 4
    assert output.count('AUDIT query') <= 2
    if scenario == 'blacklist':
        assert output.count('AUDIT login') == 1
        assert '10001011' in str(result)
    if scenario != 'empty':
        assert 'fail' in str(result) or '失败' in str(result)


@pytest.mark.parametrize('iid,code', [('hs300', 'sh.000300'), ('csi500', 'sh.000905'), ('gem', 'sz.399006')])
def test_identity_prices_pct_and_parent_session_are_preserved(isolated, capsys, monkeypatch, iid, code):
    result, output = invoke(isolated, capsys, monkeypatch, 'ok', iid)
    assert result == 6
    assert isolated.batches[0][1] == [(d.replace('-', ''), iid, float(c), float(p)) for d, c, p in SAMPLES[iid]]
    assert f'{code} date,close,pctChg' in output
    assert '"frequency": "d"' in output
    assert '"start_date": "2026-11-02"' in output
    assert '"end_date": "2026-11-09"' in output
    assert isolated.sdk.logins == isolated.sdk.queries == 0  # 父进程任何已有SDK会话均不被触碰。
    assert len(isolated.calls) == 1
    assert output.count('AUDIT logout') == 1


def test_logout_exception_does_not_discard_complete_response(isolated, capsys, monkeypatch):
    result, output = invoke(isolated, capsys, monkeypatch, 'logout_exception')
    assert result == 6
    assert output.count('AUDIT logout') == 1


def test_concurrent_calls_have_distinct_sdk_processes(isolated, capsys):
    from concurrent.futures import ThreadPoolExecutor
    # 父进程已存在SDK会话；并发查询必须独立，不能login/logout/重连这个会话。
    isolated.sdk.logins, isolated.sdk.queries = 7, 13
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: isolated.fetch('20261102', '20261109'), range(2)))
    output = capsys.readouterr().out
    pids = {line for line in output.splitlines() if line.startswith('AUDIT pid')}
    assert results == [6, 6]
    assert len(pids) == 2
    assert (isolated.sdk.logins, isolated.sdk.queries) == (7, 13)
    assert len(isolated.batches) == 2


@pytest.mark.parametrize('kind', ['crash', 'missing_result', 'bad_json'])
def test_child_failure_cannot_commit_partial_output(isolated, monkeypatch, capsys, kind):
    def fail(*args, **kwargs):
        if kind == 'crash':
            raise subprocess.CalledProcessError(1, args[0], stderr='受控子查询中断')
        return SimpleNamespace(stdout='AUDIT partial\n' if kind == 'missing_result'
                               else 'FUND_INDEX_RESULT={bad json}\n')
    monkeypatch.setattr(subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='隔离查询失败'):
        isolated.fetch('20261102', '20261109')
    assert isolated.batches == []


def test_real_module_import_uses_same_isolated_route(isolated, monkeypatch, capsys):
    import app.collector as collector
    from types import ModuleType
    # 模块实际导入也不触发base的DNS/SDK补丁；纯查询子进程仍只看到临时假SDK包。
    base = ModuleType('app.collector.base')
    base.safe_call = lambda fn, **kw: fn(**kw)
    base.throttle = lambda: None
    monkeypatch.setitem(sys.modules, 'app.collector.base', base)
    monkeypatch.setattr(collector, 'base', base, raising=False)
    monkeypatch.setitem(sys.modules, 'akshare', ModuleType('akshare'))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    spec = importlib.util.spec_from_file_location('app.collector._fund_index_test',
                                                ROOT / 'app/collector/public_fund.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 复用本fixture写入捕获器，只断言写入参数，不创建任何sqlite库。
    module._ROOT = isolated.fetch.__globals__['_ROOT']
    module.get_conn = isolated.fetch.__globals__['get_conn']
    assert module.fetch_index_daily('20261102', '20261109', 'hs300') == 6
    assert len(isolated.batches) == 1
    assert isolated.sdk.logins == 0
    assert 'AUDIT query 1 sh.000300' in capsys.readouterr().out


def _process_state(pid):
    result = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                            capture_output=True, text=True, timeout=2)
    state = result.stdout.strip()
    return state, bool(state and not state.startswith('Z'))


@pytest.mark.parametrize('mode', ['perl_alarm', 'early_sigalrm', 'normal_exit'])
def test_parent_death_reclaims_only_own_query(isolated, monkeypatch, tmp_path, mode):
    """真父进程+真查询子进程；perl alarm保留mac行为，不模拟Linux群杀。"""
    import shutil
    if mode == 'perl_alarm' and not shutil.which('perl'):
        pytest.skip('此环境无perl；另两例仍验证等价SIGALRM/正常退出')
    monkeypatch.setenv('INDEX_TEST_SCENARIO', 'blocked_import')
    sdk_pid = tmp_path / 'sdk-pid'
    started_pid = tmp_path / 'child-started-pid'
    writer = tmp_path / 'unexpected-writer'
    monkeypatch.setenv('INDEX_TEST_CHILD_PID', str(sdk_pid))
    # 包一层极短启动桩，early模式在真正守卫代码开始之前杀父。
    bootstrap = (
        'import os,sys,time\nfrom pathlib import Path\n'
        f'Path({str(started_pid)!r}).write_text(str(os.getpid()))\n'
        + ('time.sleep(0.4)\n' if mode == 'early_sigalrm' else '')
        + 'code=sys.argv.pop(1)\nexec(compile(code,"<query-under-test>","exec"))\n')
    runner = f'''
import ast,datetime as dt,json,os,signal,subprocess,sys,threading,time
from pathlib import Path
from types import SimpleNamespace
source=Path({str(ROOT / 'app/collector/public_fund.py')!r}).read_text()
fn=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='fetch_index_daily')
ns={{'dt':dt,'time':time,'json':json,'sys':sys,'_ROOT':Path({str(tmp_path)!r}),
    '_safe_float':float,'get_conn':lambda **kw:SimpleNamespace(
        executemany=lambda *a:Path({str(writer)!r}).write_text('writer reached'),commit=lambda:None,close=lambda:None)}}
exec(compile(ast.Module(body=[fn],type_ignores=[]),'<fetch-under-test>','exec'),ns)
real_run=subprocess.run
def launch(args,**kwargs):
    args=[args[0],'-c',{bootstrap!r},args[2],*args[3:]]
    return real_run(args,**kwargs)
subprocess.run=launch
threading.Thread(target=lambda:ns['fetch_index_daily']('20261102','20261109'),daemon=True).start()
ready=Path({str(started_pid if mode == 'early_sigalrm' else sdk_pid)!r})
deadline=time.monotonic()+5
while not ready.exists():
    if time.monotonic()>deadline:raise RuntimeError('child not ready')
    time.sleep(0.01)
if {mode!r}=='early_sigalrm':os.kill(os.getpid(),signal.SIGALRM)
if {mode!r}=='perl_alarm':time.sleep(30)
'''
    # 只取消本fixture的run包装，保留真子进程，不触达生产模块/SDK。
    monkeypatch.setattr(subprocess, 'run', isolated.real_run)
    env = dict(os.environ, INDEX_TEST_SCENARIO='blocked_import',
               INDEX_TEST_SAMPLE=json.dumps(SAMPLES['hs300']), INDEX_TEST_CHILD_PID=str(sdk_pid))
    command = [sys.executable, '-c', runner]
    if mode == 'perl_alarm':
        command = ['perl', '-e', 'alarm shift; exec @ARGV or exit 127', '2', *command]
    log_path = tmp_path / 'lifecycle-parent.log'
    child_pid = None
    observer = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    with log_path.open('w') as output:
        parent = subprocess.Popen(command, cwd=tmp_path, env=env, stdout=output, stderr=output)
        try:
            rc = parent.wait(timeout=7)
            assert rc == (0 if mode == 'normal_exit' else -signal.SIGALRM), log_path.read_text()
            assert started_pid.exists(), log_path.read_text()
            child_pid = int(started_pid.read_text())
            exited_at = time.monotonic()
            deadline = exited_at + 3
            state, alive = _process_state(child_pid)
            while alive and time.monotonic() < deadline:
                time.sleep(0.02)
                state, alive = _process_state(child_pid)
            print(f'LIFECYCLE mode={mode} parent={rc} child_alive={alive} state={state!r} '
                  f'observer_alive={observer.poll() is None} '
                  f'reclaim_seconds={time.monotonic() - exited_at:.3f}', flush=True)
            assert observer.poll() is None
            assert not writer.exists()
            assert not alive, f'{mode}: parent={rc}, child={child_pid} remains {state}'
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.wait(timeout=2)
            if child_pid is None and started_pid.exists():
                child_pid = int(started_pid.read_text())
            if child_pid and _process_state(child_pid)[1]:
                # 修前反例清理：仅清理命令含本tmp路径启动桩的已知测试子进程。
                cmd = subprocess.run(['ps', '-o', 'command=', '-p', str(child_pid)],
                                     capture_output=True, text=True, timeout=2).stdout
                assert str(tmp_path) in cmd
                os.kill(child_pid, signal.SIGKILL)
            observer.kill()
            observer.wait(timeout=2)


@pytest.mark.parametrize('fail', [False, True])
def test_liveness_pipe_descriptors_close_on_success_or_launch_failure(isolated, monkeypatch, fail):
    real_pipe = os.pipe
    owned = []
    def pipe():
        pair = real_pipe()
        owned.append(pair)
        return pair
    monkeypatch.setattr(os, 'pipe', pipe)
    if fail:
        def cannot_start(*a, **kw):
            raise OSError('受控启动失败')
        monkeypatch.setattr(subprocess, 'run', cannot_start)
    if fail:
        with pytest.raises(RuntimeError, match='隔离查询失败'):
            isolated.fetch('20261102', '20261109')
    else:
        assert isolated.fetch('20261102', '20261109') == 6
    assert owned
    # 第一个pipe由fetch创建；subprocess另建stdout/stderr管道不计入本函数资源。
    for fd in owned[0]:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize('scenario', ['slow_login', 'slow_query', 'slow_next', 'trickle'])
def test_deadline_bounds_sdk_and_discards_partial_rows(isolated, monkeypatch, scenario):
    monkeypatch.setenv('INDEX_TEST_SCENARIO', scenario)
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        isolated.fetch('20261102', '20261109', deadline=start + 0.20, io_timeout=0.06)
    assert time.monotonic() - start < 1.0
    assert isolated.batches == []


def test_logout_is_bounded_but_keeps_complete_response(isolated, monkeypatch):
    monkeypatch.setenv('INDEX_TEST_SCENARIO', 'slow_logout')
    start = time.monotonic()
    assert isolated.fetch('20261102', '20261109', deadline=start + 1, io_timeout=0.06) == 6
    assert time.monotonic() - start < 0.8
    assert len(isolated.batches) == 1


def test_parent_timeout_kills_and_reaps_blocked_sdk_import(isolated, monkeypatch, tmp_path):
    monkeypatch.setenv('INDEX_TEST_SCENARIO', 'blocked_import')
    pidfile = tmp_path / 'query-pid'
    monkeypatch.setenv('INDEX_TEST_CHILD_PID', str(pidfile))
    with pytest.raises(TimeoutError):
        isolated.fetch('20261102', '20261109', deadline=time.monotonic() + 0.3)
    assert pidfile.exists()
    monkeypatch.setattr(subprocess, 'run', isolated.real_run)
    state, alive = _process_state(int(pidfile.read_text()))
    assert not alive and not state  # wait已回收，连僵尸也没有。
    assert isolated.batches == []


def test_expired_deadline_never_launches_or_writes(isolated):
    with pytest.raises(TimeoutError):
        isolated.fetch('20261102', '20261109', deadline=time.monotonic() - 1)
    assert isolated.calls == []
    assert isolated.batches == []


def _entrypoints(isolated):
    tree = ast.parse((ROOT / 'app/collector/public_fund.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in ('pipeline_daily', 'main')]
    ns = dict(isolated.fetch.__globals__)
    ns.update(init_db=lambda: None, _acquire_lock=lambda **kw: True,
              fetch_daily_nav=lambda: 0, fetch_estimation=lambda: 0)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<entrypoints>', 'exec'), ns)
    return ns


def test_pipeline_carries_one_deadline_after_prior_stages(isolated):
    ns = _entrypoints(isolated)
    now = [100.0]
    seen = []
    ns['time'] = SimpleNamespace(time=lambda: now[0], monotonic=lambda: now[0])
    def nav():
        now[0] += 200
        return 7
    def estimation():
        now[0] += 40
        return 0
    def index(**kwargs):
        seen.append((kwargs['index_id'], kwargs['deadline'], kwargs['deadline'] - now[0]))
        now[0] += 10
        return 6
    ns.update(fetch_daily_nav=nav, fetch_estimation=estimation, fetch_index_daily=index,
              get_conn=lambda: SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: []),
                                                close=lambda: None))
    stats = ns['pipeline_daily']()
    assert stats['fund_daily_nav'] == 7
    assert seen == [('hs300', 390, 50), ('csi500', 390, 40), ('gem', 390, 30)]


@pytest.mark.parametrize('scenario,exit_code', [('empty', None), ('query_always', 2), ('slow_login', 124)])
def test_daily_cli_distinguishes_empty_error_timeout(isolated, monkeypatch, scenario, exit_code):
    ns = _entrypoints(isolated)
    monkeypatch.setattr(sys, 'argv', ['public_fund', 'daily'])
    monkeypatch.setenv('INDEX_TEST_SCENARIO', scenario)
    real_fetch = isolated.fetch
    ns['fetch_index_daily'] = lambda **kw: real_fetch(
        '20261102', '20261109', kw['index_id'],
        deadline=min(kw['deadline'], time.monotonic() + 0.2), io_timeout=0.06)
    ns['get_conn'] = lambda: SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: []),
                                           close=lambda: None)
    if exit_code is None:
        assert ns['main']() is None
    else:
        with pytest.raises(SystemExit) as exc:
            ns['main']()
        assert exc.value.code == exit_code
    assert isolated.batches == []


def test_later_index_failure_keeps_prior_complete_commit_but_fails_batch(isolated, monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / 'indices.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE fund_index_daily(date TEXT, index_id TEXT, close REAL, pct_change REAL, '
                     'PRIMARY KEY(date,index_id))')
    monkeypatch.setitem(isolated.fetch.__globals__, 'get_conn', lambda **kw: sqlite3.connect(db))
    ns = _entrypoints(isolated)
    def fetch(**kw):
        monkeypatch.setenv('INDEX_TEST_SCENARIO', 'ok' if kw['index_id'] == 'hs300' else 'query_always')
        return isolated.fetch('20261102', '20261109', **kw)
    ns['fetch_index_daily'] = fetch
    with pytest.raises(RuntimeError, match='查询失败'):
        ns['pipeline_daily']()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT DISTINCT index_id FROM fund_index_daily').fetchall() == [('hs300',)]
        assert conn.execute('SELECT COUNT(*) FROM fund_index_daily').fetchone()[0] == 6


@pytest.mark.parametrize('failure', ['sql', 'deadline'])
def test_write_failure_rolls_back_batch_preserves_previous_commit(isolated, monkeypatch, tmp_path, failure):
    import sqlite3
    db = tmp_path / 'indices.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE fund_index_daily(date TEXT, index_id TEXT, close REAL, pct_change REAL, '
                     'PRIMARY KEY(date,index_id))')
        conn.execute("INSERT INTO fund_index_daily VALUES ('20261102','hs300',123,1)")
        if failure == 'sql':
            conn.execute("CREATE TRIGGER stop_second BEFORE INSERT ON fund_index_daily "
                         "WHEN NEW.date='20261103' BEGIN SELECT RAISE(ABORT,'injected'); END")
    clock = [0]
    class Connection:
        def __init__(self, **kwargs):
            self.conn = sqlite3.connect(db)
        def __getattr__(self, name):
            return getattr(self.conn, name)
        def executemany(self, sql, rows):
            result = self.conn.executemany(sql, rows)
            if failure == 'deadline':
                clock[0] = 1
            return result
    monkeypatch.setitem(isolated.fetch.__globals__, 'get_conn', Connection)
    # 使用真实monotonic绝对截止，写完时单独让父时钟越界，不污染全局time。
    deadline = time.monotonic() + 5
    monkeypatch.setitem(isolated.fetch.__globals__, 'time', SimpleNamespace(
        time=time.time, monotonic=lambda: deadline + 1 if clock[0] else time.monotonic()))
    with pytest.raises(sqlite3.IntegrityError if failure == 'sql' else TimeoutError):
        isolated.fetch('20261102', '20261109', deadline=deadline)
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT * FROM fund_index_daily').fetchall() == [('20261102', 'hs300', 123, 1)]


@pytest.mark.parametrize('cmd', ['estimate', 'backfill-nav'])
def test_other_index_batches_share_deadline_and_stop_followup(isolated, monkeypatch, cmd):
    ns = _entrypoints(isolated)
    monkeypatch.setattr(sys, 'argv', ['public_fund', cmd])
    calls = []
    def index(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise RuntimeError('index unavailable')
        return 6
    def forbidden(*args, **kwargs):
        pytest.fail('指数失败不得继续回填/导出')
    ns.update(fetch_index_daily=index, fetch_nav_history=forbidden, export_json_files=forbidden)
    with pytest.raises(RuntimeError):
        ns['main']()
    assert [c['index_id'] for c in calls] == ['hs300', 'csi500']
    assert len({c['deadline'] for c in calls}) == 1


def test_connection_setup_lock_obeys_remaining_budget_and_closes(tmp_path):
    import sqlite3
    db = tmp_path / 'locked.db'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE fixture(x)')
    holder = sqlite3.connect(db)
    holder.execute('BEGIN EXCLUSIVE')
    tree = ast.parse((ROOT / 'app/collector/public_fund.py').read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_conn')
    opened = []
    def connect(*args, **kwargs):
        conn = sqlite3.connect(*args, **kwargs)
        opened.append(conn)
        return conn
    ns = {'sqlite3': SimpleNamespace(connect=connect, Row=sqlite3.Row, Connection=sqlite3.Connection),
          'DB_PATH': db}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<get_conn>', 'exec'), ns)
    try:
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            ns['get_conn'](timeout=0.05)
        assert time.monotonic() - started < 0.5
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            opened[0].execute('SELECT 1')
    finally:
        holder.rollback()
        holder.close()


@pytest.mark.parametrize('scenario,expected_exit', [('slow_login', 124), ('login_always', 2)])
def test_reconnect_exhaustion_keeps_timeout_type_with_budget_left(
        isolated, monkeypatch, capsys, scenario, expected_exit):
    # 使用真实2秒退避；20秒总预算足够跑完初次登录+三次重连，
    # 必须由错误类型而非整轮deadline决定124/2。
    helper = isolated.fetch.__globals__['_ROOT'] / 'app/collector/baostock_daily.py'
    helper.write_text(helper.read_text().replace('time = SimpleNamespace(sleep=lambda _: None)', 'import time'))
    monkeypatch.setenv('INDEX_TEST_SCENARIO', scenario)
    monkeypatch.setattr(sys, 'argv', ['public_fund', 'daily'])
    ns = _entrypoints(isolated)
    started = time.monotonic()
    deadline = started + 20
    ns['fetch_index_daily'] = lambda **kw: isolated.fetch(
        '20261102', '20261109', kw['index_id'], deadline=deadline, io_timeout=2.05)
    with pytest.raises(SystemExit) as exc:
        ns['main']()
    elapsed = time.monotonic() - started
    output = capsys.readouterr()
    print(f'RECONNECT_CLASSIFICATION scenario={scenario} exit={exc.value.code} '
          f'elapsed={elapsed:.3f} remaining={deadline-time.monotonic():.3f}')
    assert elapsed < 18  # 总预算未耗尽，不能靠父run超时把错误凑成124。
    assert output.out.count('AUDIT login') == 4
    assert output.out.count('[baostock reconnect] attempt') == 3
    assert isolated.batches == []
    assert exc.value.code == expected_exit


@pytest.mark.parametrize('scenario', ['slow_login_once', 'slow_then_error'])
def test_recovered_or_replaced_login_timeout_is_not_sticky(isolated, monkeypatch, scenario):
    monkeypatch.setenv('INDEX_TEST_SCENARIO', scenario)
    if scenario == 'slow_login_once':
        assert isolated.fetch('20261102', '20261109', deadline=time.monotonic() + 5, io_timeout=.1) == 6
        assert len(isolated.batches) == 1
    else:
        with pytest.raises(RuntimeError, match='重连失败'):
            isolated.fetch('20261102', '20261109', deadline=time.monotonic() + 5, io_timeout=.1)
        assert isolated.batches == []
