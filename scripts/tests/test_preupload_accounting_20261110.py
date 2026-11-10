"""真实日志格式的日期/轮次与异常计数回归；所有输入、输出均为 tmp，禁止外发。"""
import gzip
import os
import sys
import types

import pytest

import check_preupload_backup as cpb

DAY = "20261110"
START = "=== turnover_backfill.sh 开始 2026-11-10 21:10:00 ==="
OLD_START = "=== turnover_backfill.sh 开始 2026-11-03 21:10:00 ==="
DONE = "[data-large] 备份完成 copied=7 skipped=0 failed=0"
FAIL = "[data-large] 备份完成 copied=2 skipped=0 failed=1"
EXCEPTION = "[data-large] 备份完成 copied=0 skipped=0 failed=-1"


@pytest.fixture
def run_check(tmp_path, monkeypatch, capsys):
    logs = tmp_path / "data" / "logs"
    logs.mkdir(parents=True)
    calls = []
    # 在加载上传模块之前替换整模块；绝不读取真实凭据或访问 R2。
    monkeypatch.setitem(sys.modules, "upload_r2", types.SimpleNamespace(BACKUP_BUCKET="tmp-test"))
    monkeypatch.setattr(cpb, "count_landed", lambda *a: 7)
    monkeypatch.setattr(cpb, "do_notify", lambda *a: calls.append(a) or True)
    monkeypatch.setattr(sys, "argv", ["check_preupload_backup.py", "--repo", str(tmp_path), "--day", DAY])

    def run(files, day=DAY):
        for name, text in files.items():
            path = logs / name
            if name.endswith(".gz"):
                with gzip.open(path, "wt") as f:
                    f.write(text)
            else:
                path.write_text(text)
            # 固定成查询日 mtime，证明日期归属不能由 mtime 提供。
            os.utime(path, (1794301200, 1794301200))
        monkeypatch.setattr(sys, "argv", ["check_preupload_backup.py", "--repo", str(tmp_path), "--day", day])
        rc = cpb.main()
        output = capsys.readouterr().out
        assert calls == []
        return rc, output
    return run


@pytest.mark.parametrize("rows", [[FAIL, EXCEPTION], [EXCEPTION, FAIL], [FAIL, EXCEPTION, EXCEPTION]])
def test_sentinel_never_cancels_positive_failures(rows):
    stat = cpb.parse_log_lines(rows)
    assert cpb.judge(7, stat)[:2] == (1, "FAIL")
    assert stat["failed"] == 1
    assert stat["exceptions"] == len(rows) - 1


def test_old_failure_is_history_not_today(run_check):
    rc, out = run_check({"turnover_launchd.log": "\n".join([OLD_START, FAIL, START, DONE])})
    assert rc == 1
    assert "failed=0" in out
    assert "历史未解决" in out and "20261103" in out


def test_old_exception_survives_current_success(run_check):
    rc, out = run_check({"turnover_launchd.log": "\n".join([OLD_START, EXCEPTION, START, DONE])})
    assert rc == 1
    assert "exceptions=0" in out
    assert "历史未解决" in out and '"exceptions": 1' in out


def test_mtime_cannot_hide_current_event(run_check, tmp_path):
    # fixture 写入后另改为旧日期；main 读取时必须仍认当日实际轮次。
    path = tmp_path / "data/logs/current.log"
    path.write_text(START + "\n" + FAIL)
    os.utime(path, (1, 1))
    rc, out = run_check({})
    assert rc == 1 and "failed=1" in out


@pytest.mark.parametrize("rows", [DONE, "2026-11-10 12:00:00 [INFO] 普通消息\n" + DONE,
                                  "=== turnover_backfill.sh 结束 2026-11-10 22:00:00 ===\n" + DONE])
def test_undated_completion_never_ok(run_check, rows):
    rc, out = run_check({"unknown.log": rows})
    assert rc == 2 and "PREUPLOAD_UNKNOWN" in out


def test_undated_failure_remains_visible(run_check):
    rc, out = run_check({"unknown.log": FAIL + "\n" + EXCEPTION})
    assert rc == 1 and "日期未知" in out


def test_empty_logs_are_no_run(run_check):
    rc, out = run_check({"empty.log": "", "blank.log": "\n\n"})
    assert rc == 0 and "PREUPLOAD_NO_RUN" in out


def test_legacy_cross_midnight_uses_backup_prefix(run_check):
    rc, out = run_check({"cross.log": "\n".join([
        "=== r2_upload_async 开始 2026-11-09 23:50:00 ===",
        "[data-large] R2_BYTES_TOTAL=123",
        "[data-large] ✓ 备份 7 个将被覆盖 key -> signal-backup2/pre-upload/20261110/ (export-guard L5)",
        DONE,
        "=== r2_upload_async 结束 2026-11-10 00:15:00 退出码=0 ===",
    ])})
    assert rc == 0 and "PREUPLOAD_OK" in out and "runs=1" in out


def test_precise_stage_day_overrides_outer_day(run_check):
    rc, out = run_check({"cross.log": "\n".join([
        "=== r2_upload_async 开始 2026-11-09 23:50:00 ===",
        "[data-large] 备份开始 day=20261110 run_id=123-456",
        DONE,
        "=== r2_upload_async 结束 2026-11-10 00:15:00 退出码=0 ===",
    ])})
    assert rc == 0 and "PREUPLOAD_OK" in out and "copied=7" in out


def test_precise_prior_day_not_reassigned_by_end_or_later_logger(run_check):
    rc, out = run_check({"cross.log": "\n".join([
        "[data-large] 备份开始 day=20261109 run_id=123-789",
        "2026-11-10 00:01:00 [INFO] 无关消息",
        FAIL,
        "=== r2_upload_async 结束 2026-11-10 00:15:00 退出码=0 ===",
    ])})
    assert rc == 1 and "failed=0" in out and "历史未解决" in out and "20261109" in out


@pytest.mark.parametrize("suffix", [".1", ".2.gz"])
def test_rotation_carries_run_boundary_without_mtime(run_check, suffix):
    rc, out = run_check({"turnover.log" + suffix: START + "\n", "turnover.log": FAIL + "\n"})
    assert rc == 1 and "failed=1" in out and "日期未知" not in out


def test_precise_mirrors_are_not_counted_twice(run_check):
    content = "[data-large] 备份开始 day=20261110 run_id=123-456\n" + DONE + "\n"
    rc, out = run_check({"job.log": content, "job_launchd.log": content})
    assert rc == 0 and "runs=1" in out and "copied=7" in out


def test_nested_pipeline_end_restores_outer_scope(run_check):
    rc, out = run_check({"nested.log": "\n".join([
        START,
        "=== pipeline[turnover] 开始 2026-11-10 21:10:01 steps=turnover ===",
        "=== pipeline[turnover] 结束 2026-11-10 21:10:02 ===",
        DONE,
        "=== turnover_backfill.sh 结束 2026-11-10 22:00:00 退出码=0 ===",
        DONE,
    ])})
    assert rc == 2 and "PREUPLOAD_UNKNOWN" in out


def test_old_failure_beyond_former_tail_window_is_retained(run_check):
    rc, out = run_check({"large.log": OLD_START + "\n" + FAIL + "\n" + "x" * (2 * 1024 * 1024 + 10) + "\n" + START + "\n" + DONE})
    assert rc == 1 and "历史未解决" in out and "failed=0" in out


def test_next_day_query_does_not_recount_previous_success(run_check):
    rc, out = run_check({"previous.log": START + "\n" + DONE}, day="20261111")
    assert rc == 0 and "PREUPLOAD_NO_RUN" in out


def test_legacy_unlabelled_rows_keep_banner_scope(run_check):
    rc, out = run_check({"legacy.log": OLD_START + "\n备份完成 copied=0 skipped=0 failed=1\n" + START + "\n备份完成 copied=7 skipped=0 failed=0"})
    assert rc == 1 and "failed=0" in out and "历史未解决" in out


def test_unknown_state_does_not_leak_between_files(run_check):
    rc, out = run_check({"a.log": START + "\n" + DONE, "b.log": DONE})
    assert rc == 2 and "undated_runs=1" in out


def test_legacy_prefix_is_not_reused_for_next_call(run_check):
    rc, out = run_check({"legacy.log": "\n".join([
        "[data-large] ✓ 备份 7 个将被覆盖 key -> signal-backup2/pre-upload/20261110/ (export-guard L5)",
        DONE, DONE,
    ])})
    assert rc == 2 and "runs=1" in out and "undated_runs=1" in out


def test_bad_precise_day_is_unknown_not_outer_fallback(run_check):
    rc, out = run_check({"bad.log": START + "\n[data-large] 备份开始 day=20261399 run_id=1-2\n" + DONE})
    assert rc == 2 and "PREUPLOAD_UNKNOWN" in out


def test_damaged_rotation_cannot_report_ok(run_check, tmp_path):
    path = tmp_path / "data/logs/broken.log.1.gz"
    path.write_bytes(b"not gzip")
    rc, out = run_check({"current.log": START + "\n" + DONE})
    assert rc == 2 and "log_errors=" in out


def test_helper_entry_marker_uses_selected_backup_day(monkeypatch, capsys):
    import ast
    import datetime
    import time
    from pathlib import Path

    tree = ast.parse((Path(cpb.__file__).parent / "upload_r2.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_backup_overwritten_keys")
    selected = datetime.date(2026, 11, 10)
    clock = types.SimpleNamespace(date=types.SimpleNamespace(today=lambda: selected))
    ns = {"datetime": clock, "time": time, "os": os, "_prune_pre_upload": lambda *a: None}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<real-helper>", "exec"), ns)
    assert ns["_backup_overwritten_keys"]({}, "data-large") == (0, 0, 0, [])
    first = capsys.readouterr().out
    assert "备份开始 day=20261110 run_id=" in first
    ns["_backup_overwritten_keys"]({}, "data-large")
    second = capsys.readouterr().out
    assert first != second  # 同进程同一天的两次调用也有不同轮次标识。


@pytest.mark.parametrize("completion", [DONE, FAIL, EXCEPTION])
def test_legacy_cross_midnight_without_stage_date_is_unknown(run_check, completion):
    rc, out = run_check({"cross.log": "\n".join([
        "=== r2_upload_async 开始 2026-11-09 23:50:00 ===", completion,
        "=== r2_upload_async 结束 2026-11-10 00:15:00 退出码=0 ===",
    ])})
    if completion == DONE:
        assert rc == 2 and "PREUPLOAD_UNKNOWN" in out
    else:
        assert rc == 1 and "日期未知" in out
    assert "runs=0" in out  # 不冒充查询日发生的一次新失败。


def test_current_failure_preserves_key_run_and_date(run_check):
    rc, out = run_check({"sample.log": "\n".join([
        "[etf-hist] 备份开始 day=20261110 run_id=123-456",
        "[etf-hist] ⚠ 备份失败样本 etf/512200-all.json [GET] status=503",
        "[etf-hist] 备份完成 copied=318 skipped=0 failed=1",
    ])})
    assert rc == 1 and "etf/512200-all.json" in out and "123-456" in out and DAY in out


@pytest.mark.parametrize("rotation", [None, ".1", ".2.gz"])
def test_prior_undated_success_is_audited_after_reliable_current_boundary(run_check, tmp_path, rotation):
    current = "[data-large] 备份开始 day=20261110 run_id=123-999\n" + DONE
    files = {"scope.log": DONE + "\n" + current} if rotation is None else {
        "scope.log" + rotation: DONE + "\n", "scope.log": current,
    }
    rc, out = run_check(files)
    stat = cpb.scan_today_logs(tmp_path / "data/logs", DAY)
    assert (rc, "PREUPLOAD_OK" in out) == (0, True)
    assert stat["runs"] == 1 and stat["copied"] == 7 and stat["undated_runs"] == 0
    assert len(stat["prior_undated_successes"]) == 1
    prior = stat["prior_undated_successes"][0]
    assert prior["day"] is None and prior["stat"]["failed"] == prior["stat"]["exceptions"] == 0
    assert "prior_undated_successes=" in out


@pytest.mark.parametrize("error", [FAIL, EXCEPTION])
def test_prior_undated_error_is_not_cleared_by_reliable_current_boundary(run_check, tmp_path, error):
    rc, out = run_check({"scope.log.1": error + "\n", "scope.log":
        "[data-large] 备份开始 day=20261110 run_id=123-999\n" + DONE})
    stat = cpb.scan_today_logs(tmp_path / "data/logs", DAY)
    assert rc == 1 and "日期未知" in out
    assert stat["failed"] == stat["exceptions"] == 0  # 不伪装为今天的新错误。
    assert len(stat["undated_failures"]) == 1 and not stat.get("prior_undated_successes", [])


def test_prior_unknown_success_only_cleared_in_same_log_family(run_check):
    rc, out = run_check({"a.log": DONE, "b.log":
        "[data-large] 备份开始 day=20261110 run_id=123-999\n" + DONE})
    assert rc == 2 and "undated_runs=1" in out
