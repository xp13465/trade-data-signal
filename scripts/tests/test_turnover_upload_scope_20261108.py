"""turnover 发布闭集回归：临时树、内存传输、禁网络、通知打桩。"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest
import upload_r2 as ur

ROOT = Path(__file__).resolve().parents[2]
# 独立需求锚点，不能拿被测常量当唯一预期。
SMALL = {'overview.json', 'boot.json', 'signals_today.json',
         'a-stock-3m.json', 'a-stock-6m.json', 'a-stock-1y.json'}
LARGE = {'a-stock-3y.json', 'a-stock-5y.json', 'a-stock-all.json'}

@pytest.fixture(autouse=True)
def isolation(monkeypatch, tmp_path):
    def forbidden(*a, **kw):
        raise AssertionError('测试禁止外发/通知')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(ur, 's3_request', forbidden)
    monkeypatch.setattr(ur, 's3_head', forbidden)
    monkeypatch.setattr(ur, '_guard_upload_intraday', lambda: None)
    monkeypatch.setenv('R2_NOW_OVERRIDE', '2026-11-06T21:10:00')
    monkeypatch.setenv('ALLOW_FULL_UPLOAD', '1')
    monkeypatch.setattr(ur, '_WORK_DEADLINE', None)
    monkeypatch.setattr(ur, '_WORK_EXPIRED', False)
    monkeypatch.setattr(ur, '_DRY_RUN', False)
    local = tmp_path / 'static-site' / 'data'
    local.mkdir(parents=True)
    for name in SMALL | LARGE:
        (local / name).write_text(json.dumps({'name': name}))
    # 模拟事故中两个无关超大文件；稀疏文件避免实际占用内存。
    for name in ('signal_kelly_trades.json', 'kelly_loss_features.json'):
        with (local / name).open('wb') as f:
            f.truncate(88 * 1024 * 1024)
    monkeypatch.setattr(ur, 'STATIC_DIR', local.parent)
    return local


@pytest.fixture
def transport(monkeypatch):
    calls = {'sent': [], 'backup': [], 'purge': [], 'ledger': [], 'fail': set(), 'interrupt': False}
    def backup(keys, label):
        calls['backup'].extend(keys)
        return 0, len(keys), 0, []
    def upload(local, patterns, prefix, *, only_files, on_success, verify_etag):
        assert verify_etag is True
        failed, keys = [], []
        for p in only_files:
            if p.name in calls['fail']:
                failed.append(p.name)
                continue
            keys.append(f'{prefix}/{p.name}')
            calls['sent'].append(p.name)
            on_success(p, p.name)
            if calls['interrupt']:
                # 使用真实预算到期门，已有单件 checkpoint 必须留存。
                monkeypatch.setattr(ur, '_WORK_DEADLINE', 0)
                ur._work_budget_check('test-turnover')
        return len(keys), len(only_files), failed, keys
    monkeypatch.setattr(ur, '_backup_overwritten_keys', backup)
    monkeypatch.setattr(ur, '_upload_glob', upload)
    monkeypatch.setattr(ur, 'purge_cache', lambda keys, cache_prefix='/': calls['purge'].append((set(keys), cache_prefix)))
    monkeypatch.setattr(ur, '_record_standalone_keys', lambda keys: calls['ledger'].extend(keys))
    return calls


def paths(local, scope):
    base = local.parents[1] / 'data'
    return [base / f'.r2_turnover_{scope}_{s}' for s in ('state.json', 'uploading.marker', 'ckpt.json')]


def test_exact_keys_and_global_state_isolation(isolation, transport):
    local = isolation
    d = local.parents[1] / 'data'
    d.mkdir()
    foreign = [d / f'.r2_{channel}_{suffix}' for channel in ('data_large', 'all_data', 'turnover_other')
               for suffix in ('state.json', 'uploading.marker', 'ckpt.json')]
    for p in foreign:
        p.write_text('foreign sentinel')
    for scope in ('small', 'large'):
        ur.cmd_upload_turnover(scope)
    assert set(transport['sent']) == SMALL | LARGE
    assert set(transport['backup']) == {f'data/{n}' for n in SMALL | LARGE}
    assert set(transport['ledger']) == set(transport['backup'])
    for names in (SMALL, LARGE):
        assert ({f'data/{n}' for n in names}, '/') in transport['purge']
        assert ({f'data/{n}' for n in names}, '/r2/') in transport['purge']
    for scope, names in (('small', SMALL), ('large', LARGE)):
        state, marker, ckpt = paths(local, scope)
        assert set(json.loads(state.read_text())['files']) == names
        assert not marker.exists() and not ckpt.exists()
    assert all(p.read_text() == 'foreign sentinel' for p in foreign)


@pytest.mark.parametrize('missing', ['overview.json', 'a-stock-all.json', 'boot.json', 'signals_today.json', 'ALL'])
def test_missing_or_empty_fails_before_upload(isolation, transport, missing):
    for name in (SMALL | LARGE if missing == 'ALL' else [missing]):
        (isolation / name).unlink()
    with pytest.raises(SystemExit, match='缺少必要产物'):
        ur.cmd_upload_turnover('small')
    assert not transport['sent'] and not transport['backup']
    assert not transport['purge'] and not transport['ledger']


def test_unchanged_no_put_but_repair_purge(isolation, transport):
    ur.cmd_upload_turnover('small')
    transport['sent'].clear()
    transport['backup'].clear()
    transport['purge'].clear()
    ur.cmd_upload_turnover('small')
    assert not transport['sent'] and not transport['backup']
    assert len(transport['purge']) == 2


@pytest.mark.parametrize('kind', ['partial', 'budget'])
def test_failure_and_checkpoint_reentry(isolation, transport, monkeypatch, kind):
    state, marker, ckpt = paths(isolation, 'large')
    if kind == 'partial':
        transport['fail'] = {'a-stock-all.json'}
    else:
        transport['interrupt'] = True
    with pytest.raises(SystemExit) as exc:
        ur.cmd_upload_turnover('large')
    assert exc.value.code == (1 if kind == 'partial' else 124)
    assert marker.exists() and ckpt.exists() and not state.exists()
    done = set(json.loads(ckpt.read_text())['files'])
    assert done
    assert not transport['purge'] and not transport['ledger']
    transport['fail'].clear()
    transport['interrupt'] = False
    transport['sent'].clear()
    monkeypatch.setattr(ur, '_WORK_DEADLINE', None)
    ur.cmd_upload_turnover('large')
    assert set(transport['sent']) == LARGE - done
    assert state.exists() and not marker.exists() and not ckpt.exists()


def test_checkpoint_fingerprint_change_and_foreign_entries(isolation, transport):
    _, marker, ckpt = paths(isolation, 'large')
    marker.parent.mkdir(parents=True)
    marker.write_text('interrupted')
    ckpt.write_text(json.dumps({'files': {'a-stock-all.json': 'old',
                                       'signal_kelly_trades.json': 'foreign'}}))
    ur.cmd_upload_turnover('large')
    assert set(transport['sent']) == LARGE


def test_dry_run_no_side_effects(isolation, transport, monkeypatch):
    monkeypatch.setattr(ur, '_DRY_RUN', True)
    ur.cmd_upload_turnover('small')
    assert 'upload-turnover' in ur._DRY_RUN_CONSUMERS
    assert all(not transport[k] for k in ('sent', 'backup', 'purge', 'ledger'))
    assert not any(p.exists() for p in paths(isolation, 'small'))


def test_full_data_large_keeps_global_selection(isolation, transport, monkeypatch):
    # 真实全站命令仍传大 range、两个凯利大件及额外其他类别。
    (isolation / 'hk-all.json').write_text('{}')
    # 避免哈希稀疏大文件开销，不改变取件判据。
    monkeypatch.setattr(ur, '_file_md5', lambda p: hashlib.md5(p.name.encode()).hexdigest())
    ur.cmd_upload_data_large()
    assert LARGE | {'hk-all.json', 'signal_kelly_trades.json', 'kelly_loss_features.json'} <= set(transport['sent'])
    assert not (SMALL & set(transport['sent']))


def test_turnover_uses_domain_lock_and_work_budget(monkeypatch, tmp_path):
    monkeypatch.setenv('R2_UPLOAD_LOCK', str(tmp_path / 'upload.lock'))
    monkeypatch.setenv('R2_UPLOAD_LOCK_DOMAIN', 'data')
    fd = ur._acquire_lock_for_command('upload-turnover', ['large'])
    try:
        assert fd in ur._BARRIER_FDS
        monkeypatch.setenv('R2_UPLOAD_WORK_TIMEOUT', '3120')
        ur._work_budget_begin('upload-turnover')
        assert 3119 < ur._remaining_work() <= 3120
    finally:
        ur._release_r2_upload_lock(fd)

@pytest.mark.parametrize('pipe,export,small,large,expected', [
    (7, 0, 0, 0, 7), (0, 8, 0, 0, 8), (0, 0, 1, 0, 1),
    (0, 0, 0, 124, 124), (0, 0, 0, 0, 0),
])
def test_shell_failure_semantics(tmp_path, pipe, export, small, large, expected):
    """运行临时副本；pipeline/PY/timeout/pgrep/uname 全打桩，不可能触达业务脚本。"""
    scripts = tmp_path / 'scripts'
    (scripts / 'lib').mkdir(parents=True)
    source = (ROOT / 'scripts/turnover_backfill.sh').read_text()
    shell = scripts / 'turnover_backfill.sh'
    shell.write_text(source)
    (scripts / 'lib/repo_paths.sh').write_text(
        'resolve_repo() { REPO="$TEST_REPO"; GIT_REPO="$TEST_REPO"; }\n')
    (scripts / 'pipeline.sh').write_text('echo pipeline >> "$TEST_CALLS"; exit "$TEST_PIPE"\n')
    (scripts / 'upload_r2.py').write_text('# fixture only\n')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    stubs = {
        'uname': 'echo Linux', 'pgrep': 'exit 1',
        'timeout': 'shift; exec "$@"',
        'fake-python': '''echo "PY $*" >> "$TEST_CALLS"
case "$1" in
  -) cat >/dev/null; exit "$TEST_EXPORT" ;;
  scripts/upload_r2.py)
    case "$3" in small) exit "$TEST_SMALL" ;; large) exit "$TEST_LARGE" ;; *) exit 99 ;; esac ;;
  scripts/notify.py) exit 0 ;;
  *) exit 98 ;;
esac''',
    }
    for name, body in stubs.items():
        p = bindir / name
        p.write_text('#!/bin/bash\n' + body + '\n')
        p.chmod(0o755)
    calls = tmp_path / 'calls'
    env = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
           'PY': str(bindir / 'fake-python'), 'TEST_REPO': str(tmp_path),
           'TEST_CALLS': str(calls), 'TEST_PIPE': str(pipe), 'TEST_EXPORT': str(export),
           'TEST_SMALL': str(small), 'TEST_LARGE': str(large), 'TURNOVER_BACKFILL_LOCKED': '1'}
    r = subprocess.run(['bash', str(shell), 'force'], env=env, capture_output=True, text=True, timeout=10)
    assert r.returncode == expected, r.stderr
    log = (tmp_path / 'data/logs/turnover_backfill_launchd.log').read_text()
    assert f'退出码={expected}' in log
    trace = calls.read_text()
    if pipe:
        assert 'PY -' not in trace
    if pipe or export:
        assert 'scripts/upload_r2.py' not in trace
    else:
        assert 'upload-turnover small' in trace and 'upload-turnover large' in trace
        assert 'upload-intraday' not in trace and 'upload-data-large' not in trace
    assert ('scripts/notify.py' in trace) == bool(expected)


@pytest.mark.parametrize('bad_split', [False, True])
def test_actual_embedded_export_and_one_hop_validation(tmp_path, bad_split):
    """真实 heredoc + 假 exporter/DB；不导入实际采集器，不读主库。"""
    tmp_path = tmp_path / "export-run"
    tmp_path.mkdir()
    shell = (ROOT / 'scripts/turnover_backfill.sh').read_text()
    code = shell.split("<<'PYEOF' >> \"$LOG\" 2>&1\n", 1)[1].split('\nPYEOF', 1)[0]
    (tmp_path / 'static-site').mkdir(exist_ok=True)
    (tmp_path / 'app/collector').mkdir(parents=True)
    (tmp_path / 'app/__init__.py').write_text('')
    (tmp_path / 'app/collector/__init__.py').write_text('')
    (tmp_path / 'app/collector/fetchers.py').write_text('def load_config(): return {}\n')
    (tmp_path / 'app/db.py').write_text('class Conn:\n def close(self): pass\ndef get_conn(): return Conn()\n')
    (tmp_path / 'static-site/export.py').write_text('''import json, os
from pathlib import Path
DATA_DIR = Path(os.environ['REPO']) / 'static-site/data'
EXPORT_RANGES = ('3m','6m','1y','3y','5y','all')
def write_json(p, obj):
 p.parent.mkdir(exist_ok=True, parents=True)
 p.write_text(json.dumps(obj))
def export_overview(conn, cfg):
 return {'date':'20261106','signals_today':[], 'signals_meta':{}, 'today':{'turnover':6}}
def export_a_stock(conn, cfg, rng): return {'metrics':{'turnover':6}, 'range':rng}
def export_boot():
 ov = json.loads((DATA_DIR / 'overview.json').read_text())
 st = {k:ov.get(k) for k in ('date','signals_today','signals_meta')}
 if os.environ['BAD_SPLIT'] == '1': st['date'] = 'old'
 write_json(DATA_DIR / 'signals_today.json', st)
 ov.pop('signals_today')
 write_json(DATA_DIR / 'boot.json', {'overview':ov})
''')
    r = subprocess.run(['python3', '-c', 'import socket\nsocket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError("network forbidden"))\n' + code],
                       env={**os.environ, 'REPO': str(tmp_path), 'BAD_SPLIT': str(int(bad_split)),
                            'PYTHONPATH': str(tmp_path)}, cwd=tmp_path,
                       capture_output=True, text=True, timeout=10)
    assert (r.returncode != 0) == bad_split, r.stderr
    assert {p.name for p in (tmp_path / 'static-site/data').iterdir()} == SMALL | LARGE
    if bad_split:
        assert '首屏依赖重导不一致' in r.stderr


def test_fully_checkpointed_and_corrupt_checkpoint(isolation, transport):
    _, marker, ckpt = paths(isolation, 'large')
    marker.parent.mkdir(parents=True)
    marker.write_text('interrupted after PUT')
    ckpt.write_text(json.dumps({'files': {n: hashlib.md5((isolation / n).read_bytes()).hexdigest() for n in LARGE}}))
    ur.cmd_upload_turnover('large')
    assert not transport['sent']
    assert transport['purge']  # 已传完但未 purge 的断点恢复不漏缓存清理
    marker.write_text('interrupted')
    ckpt.write_text('{broken')
    ur.cmd_upload_turnover('large')
    assert set(transport['sent']) == LARGE


def test_failure_preserves_previous_state(isolation, transport):
    ur.cmd_upload_turnover('large')
    state, marker, ckpt = paths(isolation, 'large')
    previous = state.read_bytes()
    (isolation / 'a-stock-all.json').write_text('{"updated":true}')
    transport['fail'] = {'a-stock-all.json'}
    with pytest.raises(SystemExit) as exc:
        ur.cmd_upload_turnover('large')
    assert exc.value.code == 1
    assert state.read_bytes() == previous
    assert marker.exists() and ckpt.exists()


def test_first_run_guard_not_bypassed(isolation, transport, monkeypatch):
    import sys
    import types
    monkeypatch.delenv('ALLOW_FULL_UPLOAD')
    # 仅模拟已去重，不导入或调用真实通知模块。
    monkeypatch.setitem(sys.modules, 'notify', types.SimpleNamespace(check_dedup=lambda *a: True))
    with pytest.raises(SystemExit) as exc:
        ur.cmd_upload_turnover('small')
    assert exc.value.code == 1
    assert not transport['sent'] and not transport['backup']
    assert not transport['purge'] and not transport['ledger']


def test_sunday_full_still_scoped(isolation, transport, monkeypatch):
    ur.cmd_upload_turnover('large')
    transport['sent'].clear()
    monkeypatch.setenv('R2_NOW_OVERRIDE', '2026-11-08T21:10:00')
    ur.cmd_upload_turnover('large')
    assert set(transport['sent']) == LARGE
