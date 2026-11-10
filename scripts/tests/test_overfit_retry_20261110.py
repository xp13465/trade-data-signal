"""发布恢复的隔离回归：只提取函数，假时钟/上传器，禁止外发。"""
import json
import socket
import sys
import types

import pytest

from scripts.tests.test_overfit_delivery_20261109 import load_functions, worker_fixture


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('禁止外发'))
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('禁止外发'))
    monkeypatch.delenv('R2_UPLOAD_SKIP_RETRY_SECS', raising=False)
    monkeypatch.delenv('OVERFIT_PUBLISH_DATE', raising=False)


def publisher(codes, elapsed=60):
    ns = load_functions()
    calls, sleeps, clock = [], [], [0.0]
    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds
    def child(cmd, env, timeout):
        calls.append((cmd, dict(env), timeout))
        clock[0] += elapsed
        return codes[min(len(calls) - 1, len(codes) - 1)]
    ns.update(REPO='/isolated', SCRIPT_DIR='/isolated/scripts',
              force_env=lambda env, repo: dict(env, REPO=repo), _r2_upload_timeout=lambda: 900,
              _run_delivery_process=child, _overfit_publication_day=lambda: '2026-11-10',
              time=types.SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep))
    return ns, calls, sleeps, clock


def test_lock_released_after_first_window_recovers_without_recompute():
    ns, calls, sleeps, clock = publisher([75, 0])
    assert ns['publish_overfit']() == 0
    assert len(calls) == 2
    assert all(cmd[-1] == '--delivery-worker' for cmd, _, _ in calls)
    assert sleeps == [30]
    assert calls[1][2] == 870
    assert calls[1][1]['R2_UPLOAD_WORK_TIMEOUT'] == '690'


def test_yesterday_pair_is_rejected_before_upload(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    ns['_overfit_publication_day'] = lambda: '2026-11-10'
    assert ns['_delivery_worker']() != 0
    assert not any(e[0] == 'upload' for e in events)


def test_continuous_contention_is_bounded_and_not_success():
    ns, calls, sleeps, clock = publisher([75])
    assert ns['publish_overfit']() == 75
    assert len(calls) == 8
    assert len(sleeps) == 7
    assert clock[0] == 690 < 960
    assert [c[2] for c in calls] == [960 - i * 90 for i in range(8)]


def test_never_resets_wallclock_when_worker_is_slow():
    ns, calls, sleeps, clock = publisher([75], elapsed=800)
    assert ns['publish_overfit']() == 75
    assert len(calls) == 1
    assert not sleeps


@pytest.mark.parametrize('failure', [1, 7, 76, 124, -15])
def test_other_failures_do_not_restart_upload_or_hide_identity(failure):
    ns, calls, sleeps, clock = publisher([failure, 0])
    assert ns['publish_overfit']() == failure
    assert len(calls) == 1
    assert not sleeps


def test_cross_midnight_during_backoff_stops_old_day():
    ns, calls, sleeps, clock = publisher([75, 0])
    ns['_overfit_publication_day'] = lambda: '2026-11-10' if clock[0] < 70 else '2026-11-11'
    assert ns['publish_overfit']() != 0
    assert len(calls) == 1


def test_inflight_budget_ends_before_midnight():
    ns, calls, sleeps, clock = publisher([0])
    ns['_overfit_seconds_to_midnight'] = lambda: 600
    assert ns['publish_overfit']() == 0
    assert calls[0][2] == 595


def test_too_close_to_midnight_does_not_start_child():
    ns, calls, sleeps, clock = publisher([0])
    ns['_overfit_seconds_to_midnight'] = lambda: 100
    assert ns['publish_overfit']() == 1
    assert not calls


@pytest.mark.parametrize('today', ['2026-11-09', '2026-11-10'])
def test_current_day_pair_passes_on_consecutive_days(tmp_path, monkeypatch, today):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    ns['_overfit_publication_day'] = lambda: today
    for p in data.iterdir():
        body = json.loads(p.read_bytes())
        body['generated_at'] = today + ' 21:40'
        p.write_text(json.dumps(body, separators=(',', ':')))
    assert ns['_delivery_worker']() == 0


@pytest.mark.parametrize('generation', ['2026-11-08 21:40', '2026-11-10 21:40',
                                      '2026-11-09-invalid', '2026-02-30 21:40', 123])
def test_invalid_or_stale_pair_never_uploads(tmp_path, monkeypatch, generation):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    for p in data.iterdir():
        body = json.loads(p.read_bytes())
        body['generated_at'] = generation
        p.write_text(json.dumps(body, separators=(',', ':')))
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    assert ns['_delivery_worker']() == 1
    assert not any(e[0] == 'upload' for e in events)
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}


def test_worker_checks_fixed_publish_day_after_waiting_lock(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv('OVERFIT_PUBLISH_DATE', '2026-11-08')
    assert ns['_delivery_worker']() == 1
    assert not any(e[0] == 'upload' for e in events)


def test_midnight_during_structure_validation_blocks_put(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    days = iter(['2026-11-09', '2026-11-09', '2026-11-10'])
    ns['_overfit_publication_day'] = lambda: next(days)
    assert ns['_delivery_worker']() == 1
    assert not any(e[0] == 'upload' for e in events)


def test_midnight_during_upload_cannot_report_today_success(tmp_path, monkeypatch):
    ns, events, data = worker_fixture(tmp_path, monkeypatch)
    days = iter(['2026-11-09'] * 3 + ['2026-11-10'])
    ns['_overfit_publication_day'] = lambda: next(days)
    assert ns['_delivery_worker']() == 76


def test_actual_data_lock_release_recovers_in_same_cli_without_recompute(tmp_path, monkeypatch):
    import argparse
    from scripts.tests.test_r2_lock_domains_20261028 import _load_ur
    ur = _load_ur()
    worker, events, data = worker_fixture(tmp_path, monkeypatch)
    fake = sys.modules['upload_r2']
    monkeypatch.setattr(ur, 'STATIC_DIR', data.parent)
    monkeypatch.setenv('R2_UPLOAD_LOCK', str(tmp_path / 'global.lock'))
    monkeypatch.setenv('R2_UPLOAD_SMALL_LOCK', str(tmp_path / 'small.lock'))
    monkeypatch.setenv('R2_UPLOAD_LOCK_DOMAIN', 'data')
    monkeypatch.setenv('R2_UPLOAD_SKIP_RETRY_SECS', '0')
    monkeypatch.delenv('OVERFIT_SKIP_R2', raising=False)
    fake._acquire_lock_for_command = ur._acquire_lock_for_command
    fake._release_r2_upload_lock = ur._release_r2_upload_lock
    fake._SKIP_R2_LOCKED = ur._SKIP_R2_LOCKED
    held = ur._acquire_r2_upload_lock(timeout=0)
    ns, calls, sleeps, clock = publisher([75, 0], elapsed=0)
    ns['_overfit_publication_day'] = worker['_overfit_publication_day']
    computes, workers = [], []
    def run(cmd, env, timeout):
        workers.append(cmd)
        with monkeypatch.context() as m:
            for key in ('OVERFIT_PUBLISH_DATE', 'R2_UPLOAD_SKIP_RETRY_SECS', 'R2_UPLOAD_LOCK_DOMAIN'):
                m.setenv(key, env[key])
            return worker['_delivery_worker']()
    def unlock(seconds):
        nonlocal held
        clock[0] += seconds
        ur._release_r2_upload_lock(held)
        held = None
    ns.update(_run_delivery_process=run, argparse=argparse,
              guard_deploy_source_tree=lambda repo: None,
              build_output=lambda **kwargs: computes.append(kwargs))
    ns['time'].sleep = unlock
    monkeypatch.setattr(sys, 'argv', ['overfit_monitor.py'])
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    try:
        assert ns['main']() == 0
    finally:
        if held is not None:
            ur._release_r2_upload_lock(held)
    assert len(computes) == 1
    assert len(workers) == 2
    assert len([e for e in events if e[0] == 'upload']) == 1
    assert len([e for e in events if e[0] == 'get']) == 4
    assert before == {p.name: p.read_bytes() for p in data.iterdir()}
