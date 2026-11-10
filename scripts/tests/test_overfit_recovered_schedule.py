"""A recovered publication must not become a repeated missing-upload alert."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('overfit_schedule_test', Path(__file__).parents[1] / 'gen_schedule_stats.py')
schedule = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schedule)

VERIFIED = 'overfit 发布已核验: 主/ext 2026-11-10 21:40，两站逐字节一致'
SKIPPED = 'SKIPPED_LOCKED: R2 上传锁被占用, 跳过本轮上传'


@pytest.mark.parametrize('exit_code,lines,expected', [
    (0, [SKIPPED, VERIFIED], True),
    (0, [SKIPPED, SKIPPED, VERIFIED], True),
    (75, [SKIPPED], False),
    (76, [SKIPPED, VERIFIED], False),
    (None, [SKIPPED, VERIFIED], False),
    (0, [SKIPPED], False),
    (0, [VERIFIED, SKIPPED], False),
    (0, [SKIPPED, 'quoted: ' + VERIFIED], False),
])
def test_verified_recovery_preserves_raw_skips_and_adds_evidence(tmp_path, exit_code, lines, expected):
    path = tmp_path / 'overfit.log'
    text = '\n'.join(['=== overfit_monitor.sh 开始 2026-11-10 21:40:00 ===', *lines,
                      '=== overfit_monitor.sh 结束 2026-11-10 21:42:30 退出码=0 ==='])
    path.write_text(text)
    evidence = {}
    _, skips = schedule.scan_log_anomaly(path, 'overfit_monitor.sh', 'standard', last_exit=exit_code, execution_evidence=evidence)
    assert skips == sum(SKIPPED in line for line in lines)
    assert evidence['r2_skip_recovered'] is expected
    assert path.read_text() == text


def test_other_task_or_previous_round_cannot_borrow_recovery(tmp_path):
    path = tmp_path / 'run.log'
    path.write_text('\n'.join([
        '=== overfit_monitor.sh 开始 2026-11-09 21:40:00 ===', VERIFIED,
        '=== overfit_monitor.sh 结束 2026-11-09 21:42:30 退出码=0 ===',
        '=== overfit_monitor.sh 开始 2026-11-10 21:40:00 ===', SKIPPED,
        '=== overfit_monitor.sh 结束 2026-11-10 21:42:30 退出码=0 ===']))
    evidence = {}
    assert schedule.scan_log_anomaly(path, 'overfit_monitor.sh', 'standard', last_exit=0, execution_evidence=evidence)[1] == 1
    assert evidence['r2_skip_recovered'] is False
    path.write_text('\n'.join(['=== different.sh 开始 2026-11-10 21:40:00 ===', SKIPPED, VERIFIED,
                              '=== different.sh 结束 2026-11-10 21:42:30 退出码=0 ===']))
    assert schedule.scan_log_anomaly(path, 'different.sh', 'standard', last_exit=0, execution_evidence=evidence)[1] == 1
    assert evidence['r2_skip_recovered'] is False


@pytest.mark.parametrize('task,exit_code,recovered,expected_rounds', [
    ('overfit_monitor', 0, True, 0),
    ('overfit_monitor', 75, True, 3),
    ('overfit_monitor', None, True, 3),
    ('overfit_monitor', 0, False, 3),
    ('overfit_monitor', 0, 'true', 3),
    ('other_daily', 0, True, 3),
])
def test_real_consumer_only_clears_verified_completed_overfit(task, exit_code, recovered, expected_rounds):
    # Execute the production consumer with in-memory state: no notification or subprocess.
    import textwrap
    from datetime import datetime, timedelta
    source = (Path(__file__).parents[1] / 'schedule_monitor.sh').read_text()
    start = source.index('            _r2_skip_cnt = s.get("r2_skip_count")')
    end = source.index('        # P2(2026-09-24 r2 终审)', start)
    key = f'{task}|r2_skip_rounds'
    state = {key: {'skip_rounds': 2, 'last_round': '2026-11-10 20:40'}}
    env = dict(datetime=datetime, timedelta=timedelta, NOW=datetime(2026, 11, 10, 21, 45),
               R2_SKIP_CONTINUOUS_THRESHOLD=3, R2_SKIP_OBS_WINDOW=timedelta(minutes=30),
               R2_SKIP_TRANSIENT_TASKS=('gen_daily_brief', 'fetch_news'), R2_SKIP_ESCALATE_ROUNDS=6,
               alert_state=state, alerts=[], seen_keys_this_run=set(), _active_escalate=lambda *a: None,
               s=dict(task=task, last_exit=exit_code, unit_exit=exit_code,
                      last_run='2026-11-10 21:40', r2_round_id='2026-11-10 21:40',
                      r2_skip_count=1, r2_skip_recovered=recovered))
    exec(compile(textwrap.dedent(source[start:end]), 'real-r2-skip-consumer', 'exec'), env)
    assert state[key]['skip_rounds'] == expected_rounds
    assert env['s']['r2_skip_count'] == 1
    if expected_rounds == 0:
        assert not env['alerts']
