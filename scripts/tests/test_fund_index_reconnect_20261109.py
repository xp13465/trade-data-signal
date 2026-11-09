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
    code = '10002007' if scenario == 'login_always' or (scenario == 'login_once' and logins == 1) else '0'
    return SimpleNamespace(error_code=code, error_msg='网络接收错误。' if code != '0' else 'success')

def logout():
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
                           commit=lambda: None, close=lambda: None)
    ns = {'dt': dt, 'time': time, 'json': json, 'sys': sys, '_ROOT': tmp_path,
          '_safe_float': lambda x: float(x) if x not in ('', None) else None,
          'get_conn': lambda: conn}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT / 'app/collector/public_fund.py'), 'exec'), ns)
    # 外层只容许启动python -c只读子查询，子进程40秒硬停仅属测试看门狗。
    real_run = subprocess.run
    calls = []
    def run(args, **kwargs):
        assert args[:2] == [sys.executable, '-c']
        assert Path(kwargs['cwd']) == tmp_path
        calls.append(args)
        return real_run(args, **kwargs, timeout=40)
    monkeypatch.setattr(subprocess, 'run', run)
    return SimpleNamespace(fetch=ns['fetch_index_daily'], sdk=sdk, batches=batches,
                           calls=calls, real_run=real_run)


def invoke(env, capsys, monkeypatch, scenario, iid='hs300'):
    monkeypatch.setenv('INDEX_TEST_SCENARIO', scenario)
    monkeypatch.setenv('INDEX_TEST_SAMPLE', json.dumps(SAMPLES[iid]))
    # 基线直接用假SDK，修后子进程用同一固定脚本；两边输入相同。
    env.sdk.scenario = scenario
    env.sdk.sample = SAMPLES[iid]
    result = env.fetch('20261102', '20261109', iid)
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
    assert result == 0
    assert isolated.batches == []
    assert output.count('AUDIT login') <= 4
    assert output.count('AUDIT query') <= 2
    if scenario == 'blacklist':
        assert output.count('AUDIT login') == 1
        assert '10001011' in output
    if scenario != 'empty':
        assert 'fail' in output or '失败' in output


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
    assert isolated.fetch('20261102', '20261109') == 0
    assert isolated.batches == []
    assert '隔离查询失败' in capsys.readouterr().out


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
    '_safe_float':float,'get_conn':lambda:SimpleNamespace(
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
    assert isolated.fetch('20261102', '20261109') == (0 if fail else 6)
    assert owned
    # 第一个pipe由fetch创建；subprocess另建stdout/stderr管道不计入本函数资源。
    for fd in owned[0]:
        with pytest.raises(OSError):
            os.fstat(fd)
