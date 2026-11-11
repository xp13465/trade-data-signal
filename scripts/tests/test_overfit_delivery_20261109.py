"""隔离原函数；只跑临时小进程/替身，禁止生产上传及通知。"""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import types

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'overfit_monitor.py'


def load_functions():
    wanted = {'build_output', '_run_delivery_process', '_delivery_worker', 'publish_overfit', 'main', '_bind_publication_pair',
              '_read_overfit_public', '_verify_overfit_public_pair', '_overfit_publication_day',
              '_overfit_seconds_to_midnight'}
    tree = ast.parse(SOURCE.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    ns = dict(os=os, sys=sys, subprocess=subprocess, json=json, hashlib=hashlib,
              signal=signal, tempfile=tempfile, Path=Path, time=time)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), ns)
    ns['_overfit_publication_day'] = lambda: '2026-11-09'
    ns['_overfit_seconds_to_midnight'] = lambda: 8400
    return ns


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('网络外发被禁止'))


def test_verbose_child_does_not_deadlock():
    fn = load_functions()['_run_delivery_process']
    assert fn([sys.executable, '-c', "import sys;sys.stdout.write('x'*200000);sys.stderr.write('y'*200000)"], dict(os.environ), 3) == 0


def test_timeout_reaps_own_descendant_and_releases_lock(tmp_path):
    fn = load_functions()['_run_delivery_process']
    lock = tmp_path / 'lock'
    pid = tmp_path / 'pid'
    # 孙进程忽略TERM且继承锁；另一任务的锁必须保持。
    program = "import fcntl,os,time,signal;f=open(%r,'w');fcntl.flock(f,fcntl.LOCK_EX);p=os.fork();signal.signal(signal.SIGTERM,signal.SIG_IGN);open(%r,'w').write(str(p));time.sleep(20)" % (str(lock), str(pid))
    start = time.monotonic()
    assert fn([sys.executable, '-c', program], dict(os.environ), .3) == 124
    assert time.monotonic() - start < 4
    import fcntl
    with lock.open('w') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


def worker_fixture(tmp_path, monkeypatch, *, locked=False, fail=False, mismatch=False):
    ns = load_functions()
    data = tmp_path / 'static-site/data'
    data.mkdir(parents=True)
    for name in ('overfit_monitor.json', 'overfit_monitor_ext.json'):
        body = {'generated_at': '2026-11-09 21:40', 'publication_run_id':'fixture-generation-a', 'test': name}
        keys = ('accuracy', 'overfit', 'filtered') if name == 'overfit_monitor.json' else ('by_k', 'filtered_by_k')
        body.update({key: {} for key in keys})
        (data / name).write_text(json.dumps(body, separators=(',', ':')))
    from scripts import check_overfit_split_parity
    monkeypatch.setitem(sys.modules, 'check_overfit_split_parity', check_overfit_split_parity)
    events = []
    sentinel = object()
    def upload(names):
        events.append(('upload', names))
        if fail:
            raise SystemExit(7)
    fake = types.SimpleNamespace(_SKIP_R2_LOCKED=sentinel, guard_repo_default=lambda cmd: None,
        _acquire_lock_for_command=lambda *a, **k: events.append(('lock', a, k)) or (sentinel if locked else 12),
        _release_r2_upload_lock=lambda fd: events.append(('release', fd)),
        _work_budget_begin=lambda label: events.append(('budget', label)),
        _remaining_work=lambda: None, cmd_upload_data_files=upload)
    monkeypatch.setitem(sys.modules, 'upload_r2', fake)
    import urllib.request
    import io
    def read(req, timeout):
        events.append(('get', req.full_url))
        name = req.full_url.rsplit('/', 1)[1]
        return io.BytesIO(b'old' if mismatch else (data / name).read_bytes())
    monkeypatch.setattr(urllib.request, 'urlopen', read)
    ns.update(REPO=str(tmp_path), OUT_JSON=str(data/'overfit_monitor.json'), OUT_EXT_JSON=str(data/'overfit_monitor_ext.json'))
    return ns, events, data


def test_worker_same_generation_public_both_routes(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    assert ns['_delivery_worker']() == 0
    assert events[0] == ('lock', ('upload-data-files', ['overfit_monitor.json', 'overfit_monitor_ext.json']), {'skip_if_locked': True})
    assert len([e for e in events if e[0] == 'get']) == 4
    assert events[-1] == ('release', 12)


@pytest.mark.parametrize('damage',['none','pair','same_length_hash','same_minute_different_run','legacy_no_run'])
def test_public_pair_ops_receipt_is_only_after_four_hash_checks(tmp_path,monkeypatch,damage):
    ns,events,data=worker_fixture(tmp_path,monkeypatch)
    monkeypatch.setenv('REPO',str(tmp_path))
    monkeypatch.setenv('OPS_DELIVERY_EVIDENCE_ENABLED','1')
    monkeypatch.setenv('OPS_BUSINESS_RUN','natural-run')
    monkeypatch.setenv('OPS_BUSINESS_STARTED','2026-11-09T13:00:00Z')
    monkeypatch.setenv('INVOCATION_ID','a'*32)
    if damage=='pair':
        p=data/'overfit_monitor_ext.json';body=json.loads(p.read_text());body['generated_at']='2026-11-08 21:40';p.write_text(json.dumps(body))
    if damage=='same_length_hash':
        import urllib.request,io
        monkeypatch.setattr(urllib.request,'urlopen',lambda req,timeout: io.BytesIO(b'x'*len((data/req.full_url.rsplit('/',1)[1]).read_bytes())))
    if damage in ('same_minute_different_run','legacy_no_run'):
        for name in ('overfit_monitor.json','overfit_monitor_ext.json'):
            p=data/name;body=json.loads(p.read_text())
            if damage=='legacy_no_run':body.pop('publication_run_id')
            elif name.endswith('_ext.json'):body['publication_run_id']='different-run'
            p.write_text(json.dumps(body,separators=(',',':')))
    rc=ns['_delivery_worker']()
    index=tmp_path/'data/ops_delivery/index/overfit.json'
    if damage!='none':
        assert rc!=0
        assert not index.exists()
    else:
        assert rc==0
        body=json.loads(index.read_text())
        assert body['stage_status']=='success'
        assert body['attempt_id']=='natural-run'
        assert len(body['outputs'])==len(body['consumer_witness']['confirmed'])==2
        assert body['consumer_witness']['publication_run_id']=='fixture-generation-a'
        assert len([e for e in events if e[0]=='get'])==4


def test_pair_writer_shared_unique_run_before_both_atomic_writes(monkeypatch):
    bind=load_functions()['_bind_publication_pair']
    monkeypatch.delenv('OPS_BUSINESS_RUN',raising=False)
    a,b,c,d={},{},{},{}
    bind(a,b);bind(c,d)
    assert a['publication_run_id']==b['publication_run_id']
    assert c['publication_run_id']==d['publication_run_id']!=a['publication_run_id']
    monkeypatch.setenv('OPS_BUSINESS_RUN','existing-generation')
    bind(a,b)
    first=a['publication_run_id']
    assert first==b['publication_run_id'] and first!='existing-generation'
    bind(c,d)
    assert c['publication_run_id']==d['publication_run_id']!=first
    # The actual build function must bind once before either real writer, and
    # the alert update must retain out's same token.
    tree=ast.parse(SOURCE.read_text())
    build=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_output')
    calls=[n for n in ast.walk(build) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    binds=[n for n in calls if n.func.id=='_bind_publication_pair']
    writes=[n for n in calls if n.func.id=='atomic_write_json']
    assert len(binds)==1 and len(writes)>=2 and all(n.lineno>binds[0].lineno for n in writes)


@pytest.mark.parametrize('failure', ['locked', 'fail', 'mismatch', 'pair'])
def test_incomplete_nonzero_preserves_files(tmp_path, monkeypatch, failure):
    ns, events, data = worker_fixture(tmp_path, monkeypatch, **{failure: True} if failure in ('locked', 'fail', 'mismatch') else {})
    if failure == 'pair':
        (data / 'overfit_monitor_ext.json').write_text('{"generated_at":"old"}')
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    assert ns['_delivery_worker']() == (76 if failure == 'mismatch' else 75 if failure == 'locked' else 1)
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}
    if failure in ('locked', 'pair'):
        assert not any(e[0] == 'upload' for e in events)


def test_transient_retry_existing_artifact(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch, mismatch=True)
    assert ns['_delivery_worker']() != 0
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    import urllib.request
    import io
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout: io.BytesIO((data / req.full_url.rsplit('/', 1)[1]).read_bytes()))
    assert ns['_delivery_worker']() == 0
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}


def test_child_nonzero_is_preserved():
    assert load_functions()['_run_delivery_process']([sys.executable, '-c', 'raise SystemExit(9)'], dict(os.environ), 2) == 9


@pytest.mark.parametrize('args, expected, computes', [([], 75, True), (['--publish-only'], 75, False), (['--dry-run'], 0, True)])
def test_cli_compute_and_delivery_contract(monkeypatch, args, expected, computes):
    import argparse
    ns = load_functions()
    events = []
    ns.update(argparse=argparse, REPO='/isolated', guard_deploy_source_tree=lambda repo: None,
              build_output=lambda **kw: events.append('compute'), publish_overfit=lambda: 75)
    monkeypatch.delenv('OVERFIT_SKIP_R2', raising=False)
    monkeypatch.setattr(sys, 'argv', ['overfit_monitor.py'] + args)
    assert ns['main']() == expected
    assert ('compute' in events) == computes


def test_real_data_lock_and_global_barrier(tmp_path, monkeypatch):
    from scripts.tests.test_r2_lock_domains_20261028 import _load_ur
    ur = _load_ur()
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    fake = sys.modules['upload_r2']
    monkeypatch.setattr(ur, 'STATIC_DIR', data.parent)
    monkeypatch.setenv('R2_UPLOAD_LOCK', str(tmp_path/'global.lock'))
    monkeypatch.setenv('R2_UPLOAD_SMALL_LOCK', str(tmp_path/'small.lock'))
    monkeypatch.setenv('R2_UPLOAD_LOCK_DOMAIN', 'data')
    monkeypatch.setenv('R2_UPLOAD_SKIP_RETRY_SECS', '0')
    fake._acquire_lock_for_command = ur._acquire_lock_for_command
    fake._release_r2_upload_lock = ur._release_r2_upload_lock
    fake._SKIP_R2_LOCKED = ur._SKIP_R2_LOCKED
    held = ur._acquire_r2_upload_lock(timeout=0)
    try:
        assert ns['_delivery_worker']() == 75
        # 未杀/未解锁其它任务；域锁仍被持有。
        assert ur._acquire_r2_upload_lock(timeout=0, skip_if_locked=True) is ur._SKIP_R2_LOCKED
    finally:
        ur._release_r2_upload_lock(held)
    monkeypatch.delenv('R2_UPLOAD_LOCK_DOMAIN')
    held = ur._acquire_r2_upload_lock(timeout=0)
    monkeypatch.setenv('R2_UPLOAD_LOCK_DOMAIN', 'data')
    try:
        assert ns['_delivery_worker']() == 75
    finally:
        ur._release_r2_upload_lock(held)
    assert ns['_delivery_worker']() == 0


def test_publish_budgets_and_existing_skip_window(monkeypatch):
    ns = load_functions()
    seen = []
    ns.update(REPO='/isolated', SCRIPT_DIR='/isolated/scripts',
              force_env=lambda env, repo: dict(env, REPO=repo), _r2_upload_timeout=lambda: 900,
              _run_delivery_process=lambda cmd, env, timeout: seen.append((cmd, env, timeout)) or 1)
    monkeypatch.setattr(time, 'monotonic', lambda: 0)
    monkeypatch.setenv('R2_UPLOAD_HTTP_TIMEOUT', '600')
    monkeypatch.setenv('R2_UPLOAD_SKIP_RETRY_SECS', '99999')
    assert ns['publish_overfit']() == 1
    cmd, env, timeout = seen[0]
    assert cmd[-1] == '--delivery-worker'
    assert env['R2_UPLOAD_LOCK_DOMAIN'] == 'data'
    assert env['R2_UPLOAD_LOCK_TIMEOUT'] == '240'
    assert env['R2_UPLOAD_SKIP_RETRY_SECS'] == '60'
    assert env['R2_UPLOAD_WORK_TIMEOUT'] == '780'
    assert env['R2_UPLOAD_HTTP_TIMEOUT'] == '30'
    assert timeout == 960
    assert os.environ['R2_UPLOAD_HTTP_TIMEOUT'] == '600'


def test_concurrent_local_replacement_is_incomplete(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    def replace(names):
        (data/'overfit_monitor.json').write_text('{"generated_at":"newer"}')
    sys.modules['upload_r2'].cmd_upload_data_files = replace
    assert ns['_delivery_worker']() != 0
    assert (data/'overfit_monitor.json').read_text() == '{"generated_at":"newer"}'
    assert events[-1] == ('release', 12)


def test_wrapper_publish_only_propagates_failure_without_business_execution(tmp_path):
    import shlex
    source = SOURCE.with_suffix('.sh').read_text()
    start = source.index('if [ "${1:-}" = "publish-only" ]; then')
    end = source.index('RC=$?', start) + len('RC=$?')
    fake = tmp_path / 'python-stub'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > "$PROBE"\nexit 75\n')
    fake.chmod(0o700)
    # 只执行包装层参数/退出码切片；PY是显式白名单替身，绝不执行业务脚本主体。
    code = 'PY=' + shlex.quote(str(fake)) + '\nLOG=' + shlex.quote(str(tmp_path/'log')) + '\n'
    code += source[start:end] + '\nprintf "%s\\n" "$RC"\n'
    result = subprocess.run(['bash', '-c', code, 'probe', 'publish-only'],
                            cwd=tmp_path, env=dict(os.environ, PROBE=str(tmp_path/'args')),
                            capture_output=True, text=True, timeout=3, check=True)
    assert result.stdout.strip() == '75'
    assert (tmp_path/'args').read_text().strip() == 'scripts/overfit_monitor.py --publish-only'


@pytest.mark.parametrize('args', [['--delivery-worker', '--dry-run'], ['--publish-only', '--dry-run'], ['--publish-only', '--rebuild']])
def test_cli_rejects_ambiguous_publish_modes(monkeypatch, args):
    import argparse
    ns = load_functions()
    ns.update(argparse=argparse)
    monkeypatch.setattr(sys, 'argv', ['overfit_monitor.py'] + args)
    with pytest.raises(SystemExit) as exc:
        ns['main']()
    assert exc.value.code == 2


@pytest.mark.parametrize('rc', [0, 7])
@pytest.mark.parametrize('fd', [1, 2], ids=['stdout', 'stderr'])
@pytest.mark.parametrize('payload, expected', [
    (('中' * 5000 + '\n').encode('utf-8'), '\ufffd\ufffd' + '中' * 3999 + '\n'),
    ('发布完成\n'.encode('utf-8'), '发布完成\n'),
    (b'\xff' + '发布完成'.encode('utf-8') + b'\xfe\n', '\ufffd发布完成\ufffd\n'),
], ids=['chinese-tail-splits-codepoint', 'short-chinese', 'invalid-utf8'])
def test_child_log_tail_decoding_preserves_exit_code(capsys, payload, expected, fd, rc):
    # 真子进程写字节到临时日志；长中文尾部刻意切在UTF-8续字节上。
    program = f'import os; os.write({fd}, {payload!r}); raise SystemExit({rc})'
    actual = load_functions()['_run_delivery_process'](
        [sys.executable, '-c', program], dict(os.environ), 3)
    assert actual == rc
    assert capsys.readouterr().out == expected


def test_actual_build_output_twice_with_same_environment_has_distinct_pair_tokens(tmp_path, monkeypatch):
    from datetime import datetime, date
    import sqlite3
    from scripts.util_atomic import atomic_write_json
    ns = load_functions()
    monkeypatch.setenv('REPO', str(tmp_path))
    monkeypatch.setenv('OPS_BUSINESS_RUN', 'same-publish-attempt')
    monkeypatch.setenv('INVOCATION_ID', 'a'*32)
    data = tmp_path/'static-site/data'
    def guard(root):
        assert root == tmp_path
    def forbidden(*args, **kwargs):
        pytest.fail('external notification forbidden')
    def bank(*args, **kwargs):
        return {'overfit': {'current': dict(d1=0,d2=0,d3=0,d4=0,risk_score=0)},
                'accuracy': {'rolling': dict(by_signal={},by_grade={},backtest={},actual={})}}
    ns.update(REPO=tmp_path, guard_deploy_source_tree=guard, sqlite3=sqlite3,
              find_db=lambda: str(tmp_path/'isolated.db'),
              load_trades=lambda: ({},None), FilterCtx=lambda *a,**k: types.SimpleNamespace(ts_map={}),
              _compute_bank=bank, load_market_tier_map=lambda: ({},{}),
              load_loss_rules_recent=lambda: (None,None), build_recent_block=lambda *a: {'rows':[]},
              assessed_prev_scores=lambda prev: [], evaluate_alerts=lambda *a: [],
              risk_level=lambda risk: 'fixture', send_notify=forbidden,
              date_cls=date, datetime=datetime, atomic_write_json=atomic_write_json,
              OUT_JSON=str(data/'overfit_monitor.json'), OUT_EXT_JSON=str(data/'overfit_monitor_ext.json'),
              DEFAULT_K=1,AFG_MODES=[],OVERFIT_MODE='fixture',WINDOWS=[],W_D1=0,W_D2=0,W_D3=0,W_D4=0,
              RECENT_DAYS=1,SURFACE_DAYS=1)
    for name in ('load_signal_daily','load_index_close','load_market_map','load_signal_grade_map',
                 'load_board_etf_track_score','build_market_state_hs300','load_board_etf_track_tier',
                 'filter_actual_by_date','filter_trades_by_date','build_topk_kept_map','filter_by_date_by_kept',
                 'filter_trades_by_kept','load_prev_state'):
        ns[name]=lambda *a,**k: {}
    # Execute both entire production build bodies and the real atomic file writer;
    # only computation inputs and side-effect boundaries are replaced.
    ns['build_output'](dry_run=True)
    first=[json.loads((data/name).read_text()) for name in ('overfit_monitor.json','overfit_monitor_ext.json')]
    ns['build_output'](dry_run=True)
    second=[json.loads((data/name).read_text()) for name in ('overfit_monitor.json','overfit_monitor_ext.json')]
    assert first[0]['publication_run_id']==first[1]['publication_run_id']
    assert second[0]['publication_run_id']==second[1]['publication_run_id']
    assert first[0]['publication_run_id']!=second[0]['publication_run_id']
    assert all(len(p['publication_run_id'])==32 for p in first+second)


@pytest.mark.parametrize('token,valid', [('A',True),('a'+'_.:-Z09'*18,True),('a'*128,True),
                                        ('a'*129,False),('_bad',False),('-bad',False),('a/b',False),('',False)])
def test_publication_generation_token_contract(tmp_path, monkeypatch, token, valid):
    ns,events,data=worker_fixture(tmp_path,monkeypatch)
    for p in data.iterdir():
        obj=json.loads(p.read_text());obj['publication_run_id']=token;p.write_text(json.dumps(obj,separators=(',',':')))
    assert (ns['_delivery_worker']()==0) is valid
