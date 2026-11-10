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
    (0, [SKIPPED, VERIFIED], 0),
    (0, [SKIPPED, SKIPPED, VERIFIED], 0),
    (75, [SKIPPED], 1),
    (76, [SKIPPED, VERIFIED], 1),
    (None, [SKIPPED, VERIFIED], 1),
    (0, [SKIPPED], 1),
    (0, [VERIFIED, SKIPPED], 1),
    (0, [SKIPPED, 'quoted: ' + VERIFIED], 1),
])
def test_only_final_verified_overfit_recovery_clears_outstanding_skips(tmp_path, exit_code, lines, expected):
    path = tmp_path / 'overfit.log'
    text = '\n'.join(['=== overfit_monitor.sh 开始 2026-11-10 21:40:00 ===', *lines,
                      '=== overfit_monitor.sh 结束 2026-11-10 21:42:30 退出码=0 ==='])
    path.write_text(text)
    _, skips = schedule.scan_log_anomaly(path, 'overfit_monitor.sh', 'standard', last_exit=exit_code)
    assert skips == expected
    assert path.read_text() == text


def test_other_task_or_previous_round_cannot_borrow_recovery(tmp_path):
    path = tmp_path / 'run.log'
    path.write_text('\n'.join([
        '=== overfit_monitor.sh 开始 2026-11-09 21:40:00 ===', VERIFIED,
        '=== overfit_monitor.sh 结束 2026-11-09 21:42:30 退出码=0 ===',
        '=== overfit_monitor.sh 开始 2026-11-10 21:40:00 ===', SKIPPED,
        '=== overfit_monitor.sh 结束 2026-11-10 21:42:30 退出码=0 ===']))
    assert schedule.scan_log_anomaly(path, 'overfit_monitor.sh', 'standard', last_exit=0)[1] == 1
    path.write_text('\n'.join(['=== different.sh 开始 2026-11-10 21:40:00 ===', SKIPPED, VERIFIED,
                              '=== different.sh 结束 2026-11-10 21:42:30 退出码=0 ===']))
    assert schedule.scan_log_anomaly(path, 'different.sh', 'standard', last_exit=0)[1] == 1
