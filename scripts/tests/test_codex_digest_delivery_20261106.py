"""FIX5 offline integration tests. Import only after positively proving traps."""
import builtins
import http.client
import importlib.util
import json
import os
import smtplib
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from alert_digest_delivery import MAX_REQUEST_BYTES, request_sizes, split_posts  # noqa: E402


def text_of(parts):
    return "".join(node["text"] for p in parts for row in p["zh_cn"]["content"] for node in row)


def entry(index=0, **changes):
    result = {"rid": str(index), "day": "2026-11-06", "ts": "2026-11-06 10:00:00",
              "key": f"k{index}", "category": "test", "subject": f"主题{index}",
              "source": "offline.sh", "reason": "over_budget", "hits": 1}
    result.update(changes)
    return result


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    hits = []

    def blocked(*args, **kwargs):
        hits.append("outbound")
        raise AssertionError("offline boundary trap")

    real_open = builtins.open
    real_io_open = __import__('io').open

    def safe_open(real):
        def guarded(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)) and Path(os.fsdecode(file)).name == '.env':
                hits.append("env")
                raise AssertionError(".env access forbidden")
            return real(file, *args, **kwargs)
        return guarded

    for obj, name in [(urllib.request, 'urlopen'), (smtplib, 'SMTP'), (smtplib, 'SMTP_SSL'),
                      (socket, 'create_connection'), (socket.socket, 'connect'),
                      (socket.socket, 'connect_ex'), (http.client.HTTPConnection, 'connect'),
                      (http.client.HTTPSConnection, 'connect'), (subprocess, 'Popen')]:
        monkeypatch.setattr(obj, name, blocked)
    monkeypatch.setattr(builtins, 'open', safe_open(real_open))
    monkeypatch.setattr(__import__('io'), 'open', safe_open(real_io_open))
    # Positive controls run BEFORE importing notify; no process/network is opened.
    for action in [lambda: urllib.request.urlopen('https://invalid.example'),
                   lambda: smtplib.SMTP_SSL('invalid.example'),
                   lambda: socket.create_connection(('invalid.example', 443)),
                   lambda: subprocess.Popen(['false']),
                   lambda: Path('/forbidden/.env').read_text()]:
        with pytest.raises(AssertionError):
            action()
    assert len(hits) == 5
    hits.clear()
    monkeypatch.setenv('REPO', str(tmp_path))
    for flag in ['ALERT_DIGEST_DISABLE', 'ALERT_BUDGET_DISABLE', 'NOTIFY_SOURCE']:
        monkeypatch.delenv(flag, raising=False)
    spec = importlib.util.spec_from_file_location('digest_notify_offline', SCRIPTS / 'notify.py')
    notify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notify)
    notify.ALERTS_DIR.mkdir(parents=True)
    config = {'enabled': True, 'mode': 'app', 'chat_ids': {'report': 'oc_offline'}}
    monkeypatch.setattr(notify, 'load_feishu_config', lambda: config)
    monkeypatch.setattr(notify, '_load_feishu_credentials', lambda: ('', ''))
    clock = [datetime(2026, 11, 6, 23, 30)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]
    monkeypatch.setattr(notify, 'datetime', Clock)
    calls = {'email': [], 'telegram': [], 'feishu': []}
    outcomes = {'email': True, 'telegram': False, 'feishu': True}

    def external(channel):
        def send(*args, **kwargs):
            calls[channel].append((args, kwargs))
            out = outcomes[channel]
            return out(*args, **kwargs) if callable(out) else out
        return send
    for name, channel in [('_send_email', 'email'), ('send_telegram', 'telegram'),
                          ('_send_feishu_api', 'feishu'), ('_send_feishu_webhook', 'feishu')]:
        stub = external(channel)
        stub.real = getattr(notify, name)
        monkeypatch.setattr(notify, name, stub)

    def seed(entries, bad=''):
        notify.ALERT_DIGEST_FILE.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n'
                                                   for e in entries) + bad)

    def rows():
        return notify._parse_buffer_lines(notify.ALERT_DIGEST_FILE.read_bytes())[0]

    def state():
        return json.loads(notify.ALERT_DIGEST_STATE_FILE.read_text())

    yield notify, config, clock, calls, outcomes, seed, rows, state
    assert hits == []


def test_full_large_digest_plain_post_exact_coverage(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    items = [entry(i, subject=('中文😀"\\\n<&>' * 900 if i == 0 else f'row{i}')) for i in range(190)]
    items[-1]['subject'] = 'TAIL_SENTINEL_末尾'
    seed(items)
    subject, body, lines, count = n._render_digest_delivery(items, [], clock[0])
    assert len(body) > 2000 and len(body.encode()) > 20 * 1024
    assert n.flush_digest() == {'sent': True, 'n': 190, 'n_remaining': 0}
    parts = [kwargs['content'] for args, kwargs in calls['feishu']]
    assert len(parts) > 3
    assert text_of(parts) == ''.join(lines)
    assert text_of(parts).endswith('TAIL_SENTINEL_末尾 (原因: 超当日类别预算)')
    assert text_of(parts) == unescape(body.replace('<br>', '\n'))
    assert len(calls['email']) == 1 and calls['email'][0][0][1] == body
    assert all(len(p['zh_cn']['content']) <= 80 and max(request_sizes(p, 'oc_offline')) <= MAX_REQUEST_BYTES for p in parts)
    assert all(node['tag'] == 'text' for p in parts for row in p['zh_cn']['content'] for node in row)
    ledger = [json.loads(line) for line in (n.ALERTS_DIR / 'alert_ledger.jsonl').read_text().splitlines()]
    assert sum(e.get('merged_count', 0) for e in ledger) == count
    assert all(e['group'] == 'report' for e in ledger)
    assert rows() == [] and state()['last_sent_day'] == '2026-11-06'


@pytest.mark.parametrize('line', ['中😀' * 14000, '\\"\n\t' * 10000])
def test_byte_cap_giant_line_and_title_overflow(line):
    title = '[告警·摘要]' + '长标题😀' * 100
    parts = split_posts(title, [line, 'TAIL'], 'oc_offline')
    prefix = parts[0]['zh_cn']['title'].rsplit(' ', 1)[0]
    assert text_of(parts) == title[len(prefix):] + '\n' + line + 'TAIL'
    assert all(max(request_sizes(p, 'oc_offline')) <= 16 * 1024 for p in parts)


def test_partial_restart_midnight_new_rows_and_changed_hits(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    items = [entry(i) for i in range(100)]
    seed(items, '{bad\n')
    outcomes['feishu'] = lambda *a, **k: len(calls['feishu']) != 2
    assert not n.flush_digest()['sent']
    frozen = state()['pending_delivery']
    assert frozen['confirmed_parts'] == [0] and frozen['other_success']['email']
    assert len(rows()) == 100 and 'last_sent_day' not in state()
    changed = dict(items[0], hits=3, hits_ts='2026-11-06 23:40:00')
    seed([changed] + items[1:] + [entry(200)], '{bad\n')
    clock[0] = datetime(2026, 11, 7, 0, 5)
    outcomes['feishu'] = True
    # Import a fresh notify module; recover only from the actual files on disk.
    spec = importlib.util.spec_from_file_location('digest_notify_restarted', SCRIPTS / 'notify.py')
    restarted = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(restarted)
    for name in ('datetime', 'load_feishu_config', '_load_feishu_credentials',
                 '_send_email', 'send_telegram', '_send_feishu_api', '_send_feishu_webhook'):
        setattr(restarted, name, getattr(n, name))
    assert restarted.flush_digest()['sent']
    assert len(calls['email']) == 1
    assert len(calls['feishu']) == 3
    assert calls['feishu'][1][1]['content'] == calls['feishu'][2][1]['content']
    assert rows() == [changed, entry(200)]
    assert '{bad' in n.ALERT_DIGEST_FILE.read_text()
    assert state()['last_sent_day'] == '2026-11-06'
    assert frozen['signature']


@pytest.mark.parametrize('config,credentials,complete', [
    ({'enabled': False}, ('', ''), True), (None, ('', ''), True),
    ({'enabled': True}, ('', ''), False), (None, ('intended', 'secret'), False)])
def test_required_vs_disabled_unconfigured(sandbox, monkeypatch, config, credentials, complete):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    monkeypatch.setattr(n, 'load_feishu_config', lambda: config)
    monkeypatch.setattr(n, '_load_feishu_credentials', lambda: credentials)
    # Missing-config warning is another external email path, stub that boundary.
    monkeypatch.setattr(n, '_alert_feishu_config_missing', lambda **k: None)
    seed([entry()])
    assert n.flush_digest()['sent'] == complete
    assert bool(rows()) != complete


def test_no_channel_success_retains(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    outcomes.update(email=False, telegram=False, feishu=False)
    seed([entry()])
    assert not n.flush_digest()['sent']
    assert rows() == [entry()] and 'last_sent_day' not in state()


@pytest.mark.parametrize('fail_at', [1, 2, 3, 4])
def test_state_failures_stop_before_cleanup(sandbox, monkeypatch, fail_at):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    original = n._write_digest_delivery_state
    count = [0]

    def fail(value):
        count[0] += 1
        if count[0] == fail_at:
            raise OSError('checkpoint injection')
        original(value)
    monkeypatch.setattr(n, '_write_digest_delivery_state', fail)
    assert not n.flush_digest()['sent']
    assert rows() == [entry()]
    if fail_at <= 2:
        assert not calls['email'] and not calls['feishu']
    if n.ALERT_DIGEST_STATE_FILE.exists():
        assert 'last_sent_day' not in state()
    monkeypatch.setattr(n, '_write_digest_delivery_state', original)
    assert n.flush_digest()['sent']
    # send -> receipt failure can replay; confirmed successful email never repeats.
    assert len(calls['email']) == (2 if fail_at == 3 else 1)


def test_cleanup_failure_only_retries_cleanup(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    original = n._atomic_write_digest
    monkeypatch.setattr(n, '_atomic_write_digest', lambda *a: (_ for _ in ()).throw(OSError('cleanup')))
    assert not n.flush_digest()['sent']
    assert rows() == [entry()] and state()['pending_delivery']['complete']
    assert 'last_sent_day' not in state()
    monkeypatch.setattr(n, '_atomic_write_digest', original)
    assert n.flush_digest()['sent']
    assert len(calls['email']) == len(calls['feishu']) == 1


def test_route_change_invalidates_parts_only(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry(i) for i in range(100)])
    outcomes['feishu'] = lambda *a, **k: len(calls['feishu']) != 2
    assert not n.flush_digest()['sent']
    cfg['chat_ids']['report'] = 'oc_changed'
    outcomes['feishu'] = True
    assert n.flush_digest()['sent']
    assert len(calls['feishu']) == 4 and len(calls['email']) == 1
    assert calls['feishu'][0][1]['content'] == calls['feishu'][2][1]['content']


def test_strict_checkpoint_chmod_failure_and_mode(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    n.ALERT_DIGEST_STATE_FILE.write_text('{}')
    n.ALERT_DIGEST_STATE_FILE.chmod(0o600)
    with patch.object(n.os, 'fchmod', side_effect=PermissionError('chmod')):
        assert not n.flush_digest()['sent']
    assert rows() == [entry()] and state() == {} and not calls['email']
    assert n.flush_digest()['sent']
    assert n.ALERT_DIGEST_STATE_FILE.stat().st_mode & 0o7777 == 0o600


def test_dry_run_and_disable_zero_writes(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    before = {p: p.read_bytes() for p in n.REPO.rglob('*') if p.is_file()}
    assert not n.flush_digest(dry_run=True)['sent']
    after = {p: p.read_bytes() for p in n.REPO.rglob('*') if p.is_file()}
    assert after == before and not calls['email'] and not calls['feishu']
    monkeypatch.setenv('ALERT_DIGEST_DISABLE', '1')
    assert not n.flush_digest()['sent']
    assert after == {p: p.read_bytes() for p in n.REPO.rglob('*') if p.is_file()}


def test_nondigest_uses_existing_text_path(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    result = n.send('普通业务报告', '中' * 5000, feishu_group='report')
    assert result['feishu'] and not calls['email']
    args, kwargs = calls['feishu'][0]
    assert kwargs['msg_type'] == 'text' and kwargs['content'] is None
    assert '已截断' in args[2]
    assert not n.ALERT_DIGEST_STATE_FILE.exists()


def test_all_false_then_email_recovers_legacy_and_count(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    cfg['enabled'] = False
    outcomes.update(email=False, telegram=False)
    seed([entry()])
    assert not n.flush_digest()['sent']
    assert not state()['pending_delivery']['first_attempted']
    outcomes['email'] = True
    assert n.flush_digest()['sent']
    assert len(calls['email']) == 2
    ledger = [json.loads(x) for x in (n.ALERTS_DIR / 'alert_ledger.jsonl').read_text().splitlines()]
    assert sum(x.get('merged_count', 0) for x in ledger) == 1


def test_crash_before_first_send_still_attempts_email(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    send = n.send
    monkeypatch.setattr(n, 'send', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('before send')))
    assert not n.flush_digest()['sent']
    assert state()['pending_delivery']['other_attempted'] is False
    monkeypatch.setattr(n, 'send', send)
    assert n.flush_digest()['sent'] and len(calls['email']) == 1


def test_route_change_after_complete_cleanup_failure(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    cleanup = n._atomic_write_digest
    monkeypatch.setattr(n, '_atomic_write_digest', lambda *a: (_ for _ in ()).throw(OSError('cleanup')))
    assert not n.flush_digest()['sent']
    cfg['chat_ids']['report'] = 'oc_new'
    outcomes['feishu'] = False
    monkeypatch.setattr(n, '_atomic_write_digest', cleanup)
    assert not n.flush_digest()['sent'] and rows() == [entry()]
    assert not state()['pending_delivery']['complete']
    assert state()['pending_delivery']['confirmed_parts'] == []
    outcomes['feishu'] = True
    assert n.flush_digest()['sent']
    assert len(calls['email']) == 1 and len(calls['feishu']) == 3


def test_retained_late_rows_wait_next_daily_window(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    def during_send(*a, **k):
        seed([entry(hits=2), entry(1)])
        return True
    outcomes['feishu'] = during_send
    assert n.flush_digest()['sent']
    assert rows() == [entry(hits=2), entry(1)]
    assert state()['last_sent_day'] == '2026-11-06'
    outcomes['feishu'] = True
    assert not n.flush_digest()['sent'] and len(calls['email']) == 1
    clock[0] = datetime(2026, 11, 7, 23, 30)
    assert n.flush_digest()['sent'] and rows() == []
    assert len(calls['email']) == 2


def test_new_state_private_default(sandbox):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    outcomes['feishu'] = False
    assert not n.flush_digest()['sent']
    assert n.ALERT_DIGEST_STATE_FILE.stat().st_mode & 0o7777 == 0o600


@pytest.mark.parametrize('field', ['chat_ids', 'webhook_urls'])
def test_malformed_mapping_retained_visible(sandbox, capsys, field):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    cfg[field] = ['malformed']
    seed([entry()])
    assert not n.flush_digest()['sent'] and rows() == [entry()]
    assert 'must be objects' in capsys.readouterr().err
    assert not calls['email'] and not calls['feishu']


def test_malformed_config_file_requires_feishu(sandbox, monkeypatch):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    n.FEISHU_CONFIG.parent.mkdir(parents=True)
    n.FEISHU_CONFIG.write_text('{broken')
    monkeypatch.setattr(n, 'load_feishu_config', lambda: None)
    monkeypatch.setattr(n, '_alert_feishu_config_missing', lambda **k: None)
    seed([entry()])
    assert not n.flush_digest()['sent'] and rows() == [entry()]
    assert state()['pending_delivery']['feishu_required']


def test_corrupt_state_diagnostic_retained(sandbox, capsys):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry()])
    n.ALERT_DIGEST_STATE_FILE.write_text('{broken')
    assert not n.flush_digest()['sent'] and rows() == [entry()]
    assert 'state 读取失败' in capsys.readouterr().err
    assert not calls['email'] and not calls['feishu']


@pytest.mark.parametrize('mutation', ['parts', 'part_hash', 'body', 'duplicate', 'range', 'index_bool', 'flag', 'complete', 'other'])
def test_malformed_pending_never_sends_or_cleans(sandbox, capsys, mutation):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    seed([entry(i) for i in range(100)])
    outcomes['feishu'] = lambda *a, **k: len(calls['feishu']) != 2
    assert not n.flush_digest()['sent']
    journal = state()
    pending = journal['pending_delivery']
    if mutation == 'parts':
        pending['parts'][1]['zh_cn']['content'][0][0]['text'] = 'LOST CONTENT'
    elif mutation == 'part_hash':
        pending['parts_signature'] = 'bad'
    elif mutation == 'body':
        pending['body'] = 'different frozen batch'
    elif mutation == 'duplicate':
        pending['confirmed_parts'] = [0, 0]
    elif mutation == 'range':
        pending['confirmed_parts'] = [len(pending['parts'])]
    elif mutation == 'index_bool':
        pending['confirmed_parts'] = [True]
    elif mutation == 'flag':
        pending['complete'] = 'true'
    elif mutation == 'complete':
        pending['complete'] = True
    else:
        pending['other_success'] = {'email': 'yes', 'telegram': False}
    n.ALERT_DIGEST_STATE_FILE.write_text(json.dumps(journal, ensure_ascii=False))
    calls_before = {k: len(v) for k, v in calls.items()}
    buffer_before = n.ALERT_DIGEST_FILE.read_bytes()
    capsys.readouterr()
    assert not n.flush_digest()['sent']
    assert 'invalid digest pending:' in capsys.readouterr().err
    assert n.ALERT_DIGEST_FILE.read_bytes() == buffer_before
    assert calls_before == {k: len(v) for k, v in calls.items()}


def test_genuine_shadow_with_all_runtime_dependencies(sandbox, monkeypatch, tmp_path):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    shadow = tmp_path / 'shadow'
    scripts = shadow / 'scripts'
    scripts.mkdir(parents=True)
    for name in ('notify.py', 'alert_denoise_rules.py', 'alert_digest_delivery.py'):
        (scripts / name).write_bytes((SCRIPTS / name).read_bytes())
    monkeypatch.setenv('REPO', str(shadow))
    # Remove source modules and source sys.path so missing copied deps cannot
    # accidentally resolve from the actual checkout or earlier test imports.
    path = [str(scripts)] + [p for p in sys.path if str(SCRIPTS.parent) not in p]
    with patch.dict(sys.modules), patch.object(sys, 'path', path):
        for name in ('alert_denoise_rules', 'alert_digest_delivery'):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location('shadow_notify', scripts / 'notify.py')
        shadow_n = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(shadow_n)
        for name in ('datetime', 'load_feishu_config', '_load_feishu_credentials',
                     '_send_email', 'send_telegram', '_send_feishu_api', '_send_feishu_webhook'):
            setattr(shadow_n, name, getattr(n, name))
        shadow_n.ALERTS_DIR.mkdir(parents=True)
        shadow_n.ALERT_DIGEST_FILE.write_text(json.dumps(entry()) + '\n')
        assert shadow_n.flush_digest()['sent']
        assert Path(sys.modules['alert_digest_delivery'].__file__).parent == scripts
        assert Path(sys.modules['alert_denoise_rules'].__file__).parent == scripts
        assert shadow_n.REPO == shadow
        assert json.loads(shadow_n.ALERT_DIGEST_STATE_FILE.read_text())['last_sent_day'] == '2026-11-06'


@pytest.mark.parametrize('mode', ['app', 'webhook'])
def test_real_feishu_serialized_requests_offline(sandbox, monkeypatch, mode):
    n, cfg, clock, calls, outcomes, seed, rows, state = sandbox
    cfg['mode'] = mode
    cfg['webhook_urls'] = {'report': 'https://example.invalid/offline-report'}
    monkeypatch.setattr(n, '_send_feishu_api', n._send_feishu_api.real)
    monkeypatch.setattr(n, '_send_feishu_webhook', n._send_feishu_webhook.real)
    monkeypatch.setattr(n, '_get_tenant_access_token', lambda: 'offline-token')
    wire = []

    def http_boundary(url, payload, headers):
        wire.append((url, payload, headers))
        return {'code': 0}

    monkeypatch.setattr(n, '_feishu_http_post_json', http_boundary)
    items = [entry(i, subject=('中文😀"\\\n<&>' * 1500 if i == 0 else f'row{i}')) for i in range(110)]
    items[-1]['subject'] = 'WIRE_TAIL_SENTINEL_末尾'
    seed(items)
    _, body, lines, _ = n._render_digest_delivery(items, [], clock[0])
    assert n.flush_digest()['sent']
    assert len(wire) >= 3
    posts = []
    for url, payload, headers in wire:
        assert len(payload) <= MAX_REQUEST_BYTES
        decoded = json.loads(payload.decode('utf-8'))
        assert decoded['msg_type'] == 'post'
        if mode == 'app':
            assert decoded['receive_id'] == 'oc_offline'
            assert url.endswith('/im/v1/messages?receive_id_type=chat_id')
            assert isinstance(decoded['content'], str)
            posts.append(json.loads(decoded['content']))
        else:
            assert url == cfg['webhook_urls']['report']
            assert isinstance(decoded['content'], dict)
            posts.append(decoded['content']['post'])
    assert text_of(posts) == ''.join(lines) == unescape(body.replace('<br>', '\n'))
    assert text_of(posts).endswith('WIRE_TAIL_SENTINEL_末尾 (原因: 超当日类别预算)')
    assert len(calls['email']) == 1 and calls['email'][0][0][1] == body
    ledger = [json.loads(line) for line in (n.ALERTS_DIR / 'alert_ledger.jsonl').read_text().splitlines()]
    assert len(ledger) == len(wire) and all(item['group'] == 'report' for item in ledger)
