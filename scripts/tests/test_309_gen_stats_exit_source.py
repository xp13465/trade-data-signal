# -*- coding: utf-8 -*-
"""#309 W2 回归测试: gen_schedule_stats 退出码口径(E2, 2026-10-25)。

核心(方案 §2 机制 A/B + 拍板点 1 = A):
  - 结束行只有 `deploy=1`、没有 `退出码=` ⇒ 不许再默认 0, 要报 last_exit=1 /
    exit_source=log-deploy / exit_conflict=true / tier=warning(聚合告警, 非 SEVERE)
  - `采集!=0` ⇒ exit_source=log-collect / tier=severe
  - systemd 真值非 0 为权威(systemd 失败优先于日志成功)
  - 全绿 ⇒ last_exit=0 / exit_source=systemd / 无冲突
  - **一行回滚**: MONITOR_EXIT_SOURCE=log 时, 同样的 deploy=1 日志返回旧口径 0(证明
    开关真起作用, 且只输出旧 19 行)

全部 static-only: 假日志写 tmp 沙箱, 假 systemd 用 `unit_reader` 注入 dict,
不启真 `systemctl`, 不跑业务脚本, 不触达 notify。

反向对照(判别力自证): 删掉日志里的 `deploy=1` → 期望变为 exit_source=systemd 且
last_exit=0(本文件对应用例必红)。
"""
import datetime
import json
from pathlib import Path

import pytest

import gen_schedule_stats as gss


NOW = datetime.datetime(2026, 10, 20, 18, 45)


def _props(result="success", status=0, start="2026-10-20 18:30:02",
           exit_ts="2026-10-20 18:31:02", load="loaded"):
    return {
        "LoadState": load, "Result": result, "ExecMainCode": "1",
        "ExecMainStatus": str(status), "InvocationID": "inv-" + str(start),
        "ExecMainStartTimestamp": start, "ExecMainExitTimestamp": exit_ts,
        "ActiveState": "inactive",
        "NextElapseUSecRealtime": "2026-10-21 18:00:00",
        "LastTriggerUSec": start,
    }


class _Runner:
    """假 systemctl: 默认全绿; 可按 unit 覆盖 props。"""

    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def __call__(self, unit):
        self.calls.append(unit)
        return self.overrides.get(unit) or _props()


def _write_log(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _build(tmp_path, runner):
    out = tmp_path / "stats.json"
    rows = gss.build(log_dir=tmp_path, out=out, now=NOW, unit_reader=runner,
                     ledger_path=tmp_path / "ledger.json")
    return rows, json.loads(out.read_text(encoding="utf-8"))


def _row(rows, task):
    return next(r for r in rows if r["task"] == task)


# ---------------------------------------------------------------- B 类补充

def test_deploy_failure_without_exit_code_is_not_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 deploy=1 ===\n")
    rows, _ = _build(tmp_path, _Runner())
    r = _row(rows, "lhb_backfill")
    assert r["last_exit"] == 1
    assert r["exit_source"] == "log-deploy"
    assert r["exit_conflict"] is True
    assert r["last_exit_tier"] == "warning"
    assert r["log_deploy"] == 1 and r["log_exit_field"] is None


def test_deploy_removed_reverts_to_systemd_success(tmp_path, monkeypatch):
    """反向对照: 同一日志删掉 deploy=1 → 判据消失, 回到 systemd 0。"""
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 ===\n")
    rows, _ = _build(tmp_path, _Runner())
    r = _row(rows, "lhb_backfill")
    assert r["last_exit"] == 0
    assert r["exit_source"] == "systemd"
    assert r["exit_conflict"] is False
    assert r["last_exit_tier"] is None


def test_collect_failure_is_severe_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 采集=2 ===\n")
    rows, _ = _build(tmp_path, _Runner())
    r = _row(rows, "lhb_backfill")
    assert r["last_exit"] == 2
    assert r["exit_source"] == "log-collect"
    assert r["last_exit_tier"] == "severe"
    assert r["exit_conflict"] is True


def test_systemd_nonzero_wins_over_log_success(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 退出码=0 ===\n")
    runner = _Runner({"trade-lhb-backfill.service":
                      _props(result="exit-code", status=1,
                             start="2026-10-20 18:30:02", exit_ts="2026-10-20 18:31:02")})
    rows, _ = _build(tmp_path, runner)
    r = _row(rows, "lhb_backfill")
    assert r["last_exit"] == 1 and r["unit_exit"] == 1
    assert r["exit_source"] == "systemd"
    assert r["exit_conflict"] is True


def test_primary_exit_code_uses_log_value(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 退出码=3 ===\n")
    rows, _ = _build(tmp_path, _Runner())
    r = _row(rows, "lhb_backfill")
    assert r["last_exit"] == 3 and r["exit_source"] == "log"
    # 日志 3 vs systemd 0 也是口径冲突(两套来源不一致, 显式标记)
    assert r["exit_conflict"] is True


# ---------------------------------------------------------------- 真值采信窗口

@pytest.mark.parametrize("unit_start,trusted", [
    ("2026-10-20 18:30:00", True),   # 与日志 start 同秒 → 采信
    ("2026-10-20 18:28:00", True),   # 早 120s(边界, 不 >120) → 采信
    ("2026-10-20 18:27:59", False),  # 早 121s → 判上一轮残留, 不采信
])
def test_unit_truth_trust_window_is_120s(tmp_path, monkeypatch, unit_start, trusted):
    """脚本「开始」行天然晚于 unit 启动几秒; 超过 120s 视为残留真值, 回退日志口径。"""
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 退出码=0 ===\n")
    runner = _Runner({"trade-lhb-backfill.service":
                      _props(result="exit-code", status=1, start=unit_start,
                             exit_ts="2026-10-20 18:31:02")})
    rows, _ = _build(tmp_path, runner)
    r = _row(rows, "lhb_backfill")
    if trusted:
        assert r["last_exit"] == 1 and r["exit_source"] == "systemd"
        assert r["unit_exit"] == 1
    else:
        assert r["last_exit"] == 0 and r["exit_source"] == "log"
        assert r["unit_exit"] is None and r["unit_timer_health"] == "unknown"


# ---------------------------------------------------------------- 覆盖与全绿

def test_systemd_mode_emits_40_rows_and_43_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    rows, _ = _build(tmp_path, _Runner())
    assert len(rows) == 40
    assert len(gss.UNIT_REGISTRY) == 43
    # 3 个自监控 unit 不进统计表(拍板点 2 = A)
    tasks = {r["task"] for r in rows}
    assert not ({"schedule_monitor", "self_heal", "check_monitor_heartbeat"} & tasks)


def test_all_green_has_no_failures_and_full_coverage_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    rows, _ = _build(tmp_path, _Runner())
    assert all(r["last_exit"] == 0 for r in rows)
    assert all(r["exit_source"] == "systemd" for r in rows)
    assert all(r["exit_conflict"] is False for r in rows)
    assert all(r["unit_missed"] is False for r in rows)
    # 新增字段每行都在(前端/结论行消费)
    assert all({"exit_source", "exit_conflict", "unit_result", "unit_exit",
                "unit_missed", "next_elapse"} <= set(r) for r in rows)


def test_not_found_unit_is_unknown_not_success(tmp_path, monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")
    runner = _Runner({"trade-fapi-daily.service": {"LoadState": "not-found",
                                                   "Result": "success",
                                                   "ExecMainStatus": "0"}})
    rows, _ = _build(tmp_path, runner)
    r = _row(rows, "fapi_daily")
    assert r["unit_exit"] is None
    assert r["last_exit"] is None
    assert r["exit_source"] == "unknown"


# ---------------------------------------------------------------- 一行回滚

def test_rollback_log_mode_restores_old_caliber(tmp_path, monkeypatch):
    """MONITOR_EXIT_SOURCE=log ⇒ 旧口径: deploy=1 无退出码仍当 0, 只输出旧 19 行。"""
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "log")
    _write_log(tmp_path, "lhb_backfill_launchd.log",
               "=== lhb_backfill.sh 开始 2026-10-20 18:30:00 ===\n"
               "=== lhb_backfill.sh 结束 2026-10-20 18:31:00 deploy=1 ===\n")
    rows, _ = _build(tmp_path, _Runner())
    assert len(rows) == len(gss.LOG_TASKS) == 19
    r = _row(rows, "lhb_backfill")
    assert r["last_exit"] == 0 and r["exit_source"] == "log"
    assert r["exit_conflict"] is False and r["unit_exit"] is None
    # 日志口径下不读 systemd: 假 runner 一次都不该被调用
    runner = _Runner()
    _build(tmp_path, runner)
    assert runner.calls == []


def test_rollback_log_mode_missing_log_is_none(tmp_path, monkeypatch):
    """回滚口径逐位对齐旧实现: 无日志/无配对时 last_exit=None(不是 0)。"""
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "log")
    rows, _ = _build(tmp_path, _Runner())
    assert len(rows) == 19
    assert all(r["last_exit"] is None for r in rows)
    assert all(r["exit_source"] == "log" for r in rows)