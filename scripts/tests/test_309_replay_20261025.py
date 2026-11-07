# -*- coding: utf-8 -*-
"""#309 重放测试: X1/X2/X3 三套 fixture 走生产 build + 结论函数(E4, 2026-10-25)。

fixture = `scripts/tests/fixtures/309/`:
  - `x{1,2,3}_units.json`: 原 44 对 service/timer 快照,不回写历史样本
  - `x{1,2,3}/logs/`: 当天日志片段
  - `x2_backfill/logs/`: X2 同轮 backfill_evening 日志(单独放, 避免污染 X2 主断言;
    方案 X2 的「+ backfill_evening(exit=1)」由独立行级用例覆盖)

执行链: 原快照 + 单独标记的 ops-monitor 模拟扩展 → build() 生成当前 42 行 →
schedule_monitor.sh 的结论函数(AST 提取)合成结论行。全程 static-only:
不启真 systemctl、不跑业务脚本、不调用 notify。

三套各自独立 tmp 目录 + 独立 ledger, 断言互不串扰。
反向对照(判别力自证): 把 X1 里 pf-score 的 Result 改成 success → 结论不再含
pf-score-daily; 再把 s06 改成 success → 结论变回 OK(证明结论真依赖 unit 字段)。
"""
import datetime
import json
import shutil
from pathlib import Path

import pytest

import gen_schedule_stats as gss
from _monitor_conclusion_309 import conclusion

FIX = Path(__file__).parent / "fixtures" / "309"

X1_NOW = datetime.datetime(2026, 10, 25, 16, 15)
X2_NOW = datetime.datetime(2026, 10, 20, 18, 45)
X3_NOW = datetime.datetime(2026, 10, 24, 21, 0)

X1_EXPECT = (
    "2 个任务退出失败: "
    "pf-score-daily(Result=timeout, exit=124, 16:00:01→16:10:01); "
    "s06-snapshot(Result=exit-code, exit=124, 10-23 20:35:01→20:58:01); "
    "漏跑 0; 覆盖 45/45(42 业务+基础, 3 自监控)"
)
X2_EXPECT = (
    "1 个任务退出失败: lhb-backfill(exit=1, 源=systemd; "
    "日志 deploy=1 且无 退出码=, exit_conflict=true); "
    "漏跑 0; 覆盖 45/45(42 业务+基础, 3 自监控)"
)
X3_EXPECT = "OK 所有任务按计划执行，无漏跑，无退出失败; 覆盖 45/45(42 业务+基础, 3 自监控)"


def _load_units(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _run(tmp_path: Path, units: dict, now, log_case: str, *, with_ops=True):
    """历史故障不变;只在内存追加新增控制面的健康模拟,不是历史运行证明。"""
    units = dict(units)
    if with_ops:
        for suffix in ("service", "timer"):
            name = f"trade-ops-monitor.{suffix}"
            assert name not in units  # 原始历史快照必须仍未包含新增 unit
            units[name] = dict(units[f"trade-ab-direction-anchor.{suffix}"],
                               InvocationID=f"synthetic-ops-monitor-{suffix}")
    log_dir = tmp_path / "logs"
    shutil.copytree(FIX / log_case / "logs", log_dir)
    out = tmp_path / "schedule_stats.json"

    def runner(unit):
        return units.get(unit) or {}

    rows = gss.build(log_dir=log_dir, out=out, now=now, unit_reader=runner,
                     ledger_path=tmp_path / "ledger.json")
    text = conclusion()(rows, now, cfu_failed=0, alerts=0)
    return rows, text


def _row(rows, task):
    return next(r for r in rows if r["task"] == task)


@pytest.fixture(autouse=True)
def _systemd_mode(monkeypatch):
    monkeypatch.setenv("MONITOR_EXIT_SOURCE", "systemd")


# ---------------------------------------------------------------- X1

def test_x1_replay_exact(tmp_path):
    rows, text = _run(tmp_path, _load_units("x1_units.json"), X1_NOW, "x1")
    assert text == X1_EXPECT
    assert "OK 所有任务" not in text
    pf = _row(rows, "pf_score_daily")
    assert (pf["last_exit"], pf["unit_exit"], pf["unit_result"], pf["exit_source"]) == (
        124, 124, "timeout", "systemd")
    s06 = _row(rows, "s06_snapshot")
    assert (s06["last_exit"], s06["unit_result"]) == (124, "exit-code")


def test_x1_mutation_pf_score_success_removes_only_pf(tmp_path):
    """反向对照 1: pf-score 改 success → 只剩 s06 一条失败(证明 X1 真依赖该字段)。"""
    units = _load_units("x1_units.json")
    units["trade-pf-score-daily.service"].update(
        {"Result": "success", "ExecMainStatus": "0", "ExecMainCode": "1"})
    rows, text = _run(tmp_path, units, X1_NOW, "x1")
    assert "pf-score-daily" not in text
    assert "s06-snapshot" in text
    assert "1 个任务退出失败" in text and "漏跑 0" in text


def test_x1_mutation_both_success_returns_ok(tmp_path):
    """反向对照 2: 两条失败都改 success → 结论必须回到 OK(防恒红空转)。"""
    units = _load_units("x1_units.json")
    for unit in ("trade-pf-score-daily.service", "trade-s06-snapshot.service"):
        units[unit].update({"Result": "success", "ExecMainStatus": "0", "ExecMainCode": "1"})
    _rows, text = _run(tmp_path, units, X1_NOW, "x1")
    assert text == X3_EXPECT


# ---------------------------------------------------------------- X2

def test_x2_replay_exact(tmp_path):
    rows, text = _run(tmp_path, _load_units("x2_units.json"), X2_NOW, "x2")
    assert text == X2_EXPECT
    assert "OK 所有任务" not in text
    lhb = _row(rows, "lhb_backfill")
    assert (lhb["last_exit"], lhb["exit_source"], lhb["exit_conflict"],
            lhb["log_deploy"], lhb["log_exit_field"]) == (1, "systemd", True, 1, None)


def test_x2_backfill_evening_row_level(tmp_path):
    """X2 同轮 backfill_evening 日志 exit=1 → 行级 last_exit=1(独立于 lhb)。"""
    rows, _text = _run(tmp_path, _load_units("x2_units.json"), X2_NOW, "x2_backfill")
    be = _row(rows, "backfill_evening")
    assert be["last_exit"] == 1 and be["exit_source"] == "log"
    assert be["exit_conflict"] is True


# ---------------------------------------------------------------- X3 / 互不串扰

def test_x3_all_green_still_ok(tmp_path):
    rows, text = _run(tmp_path, _load_units("x3_units.json"), X3_NOW, "x3")
    assert text == X3_EXPECT
    assert all(r["last_exit"] == 0 for r in rows)
    assert all(r["unit_missed"] is False for r in rows)


def test_three_cases_do_not_cross_contaminate(tmp_path):
    """三套依次跑, 各自结论/行数独立(独立 tmp + ledger)。"""
    x1_rows, x1_text = _run(tmp_path / "x1", _load_units("x1_units.json"), X1_NOW, "x1")
    x2_rows, x2_text = _run(tmp_path / "x2", _load_units("x2_units.json"), X2_NOW, "x2")
    x3_rows, x3_text = _run(tmp_path / "x3", _load_units("x3_units.json"), X3_NOW, "x3")
    assert (len(x1_rows), len(x2_rows), len(x3_rows)) == (42, 42, 42)
    assert x1_text == X1_EXPECT and x2_text == X2_EXPECT and x3_text == X3_EXPECT
    assert x1_text != x2_text != x3_text
    # X1 的失败不得漏进 X3 / X2 的行里
    assert _row(x3_rows, "pf_score_daily")["last_exit"] == 0
    assert _row(x2_rows, "s06_snapshot")["last_exit"] == 0


def test_unextended_historical_snapshot_cannot_confirm_new_unit(tmp_path):
    """缺少新 unit 的真实旧快照不得因适配而被假装成当前全绿。"""
    rows, text = _run(tmp_path, _load_units("x3_units.json"), X3_NOW, "x3",
                      with_ops=False)
    ops = _row(rows, "ops_monitor")
    assert ops["last_exit"] is None
    assert ops["exit_source"] == "missing"
    assert "OK 所有任务" not in text
    assert "退出码未知 1 个" in text
