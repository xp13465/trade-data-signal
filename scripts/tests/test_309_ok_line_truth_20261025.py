# -*- coding: utf-8 -*-
"""#309 W3 回归测试: 结论行的真假判定(E3, 2026-10-25)。

铁律(方案 §7.2 / 任务书 W3): 「OK 所有任务按计划执行」**只在** `alerts + CFU failed +
未知退出码 + 漏跑 + 退出失败` 全空时出现; 任一非空必须显式写明, 覆盖数每次标明。

取用方式: 从 `scripts/schedule_monitor.sh` 的 python heredoc 里 **ast 提取**结论函数与
辅助函数/常量后 exec(不复制逻辑), 沿用 test_monitor_resource_inprogress_20261005.py
的做法 —— 防测试与生产两份实现静默漂移(memory repro-script-second-implementation-drift)。

反向对照(判别力自证):
  - 有 CFU failed 时断言「不得含 OK 所有任务」; 去掉 CFU 失败 → OK 必须回来(防恒红空转)
  - 有任意 alert 时同样不得 OK(防「告警照发、结论仍 OK」的假绿)
"""
import datetime

import pytest

from _monitor_conclusion_309 import conclusion as _conclusion
from _monitor_conclusion_309 import namespace as _namespace


@pytest.fixture(scope="module")
def concl():
    return _conclusion()


NOW = datetime.datetime(2026, 10, 24, 21, 0)


def _row(task, unit=None, **kw):
    r = {
        "task": task,
        "unit": unit or f"trade-{task.replace('_', '-')}.service",
        "unit_exit": 0,
        "unit_result": "success",
        "unit_start": "2026-10-24 20:00:00",
        "unit_exit_ts": "2026-10-24 20:10:00",
        "next_elapse": "2026-10-25 20:00:00",
        "unit_missed": False,
        "last_exit": 0,
        "exit_source": "systemd",
        "exit_conflict": False,
        "last_exit_tier": None,
    }
    r.update(kw)
    return r


def _green_stats(n=40):
    return [_row(f"task_{i}") for i in range(n)]


OK_ALL = "OK 所有任务按计划执行，无漏跑，无退出失败"


# ---------------------------------------------------------------- 全绿

def test_all_green_exact_ok_with_coverage(concl):
    text = concl(_green_stats(), NOW, cfu_failed=0, alerts=0)
    assert text == f"{OK_ALL}; 覆盖 43/43(40 业务+基础, 3 自监控)"


# ---------------------------------------------------------------- CFU failed

def test_cfu_failed_blocks_ok_all(concl):
    """P2-5: 巡检输出的 N=问题类别数, 结论行必须展示真实 unit 名 + 真实个数。"""
    text = concl(_green_stats(), NOW, cfu_failed=1, alerts=0,
                 cfu_units=["pf-score-daily", "s06-snapshot"])
    assert "OK 所有任务" not in text
    assert "2 个云上 unit 处于 failed 状态: pf-score-daily、s06-snapshot" in text
    assert "1 个云上 unit failed" not in text  # 旧误导文案不得再出现
    assert "覆盖 43/43" in text


def test_cfu_failed_without_names_says_problem_categories(concl):
    """名字解析不到(输出格式变了)→ 只报「N 类巡检问题」, 不许把类别数说成 unit 数。"""
    text = concl(_green_stats(), NOW, cfu_failed=2, alerts=0)
    assert "2 类云上 unit 巡检问题" in text
    assert "2 个云上 unit 处于 failed" not in text


def test_cfu_failed_units_parses_real_output(concl):
    """真实形状(scripts/check_failed_units.py:759): 1 类问题含 2 个 unit 名。"""
    fn = _namespace()["_cfu_failed_units"]
    out = ("CHECK_FAILED_UNITS_FAIL(1 项): 云上 failed unit: "
           "trade-pf-score-daily.service, trade-s06-snapshot.service | "
           "存活异常: monitor 心跳过期")
    assert fn(out) == ["pf-score-daily", "s06-snapshot"]
    assert fn("CHECK_FAILED_UNITS_OK: 云上 43 unit 全部正常") == []
    assert fn("") == []


def test_removing_cfu_failure_restores_ok(concl):
    """反向对照: 去掉 CFU 失败输入 → OK 必须回来(防恒红空转)。"""
    assert "OK 所有任务" in concl(_green_stats(), NOW, cfu_failed=0, alerts=0)


# ---------------------------------------------------------------- 其它告警

@pytest.mark.parametrize("n", [1, 3])
def test_any_alert_blocks_ok_all(concl, n):
    text = concl(_green_stats(), NOW, cfu_failed=0, alerts=n)
    assert "OK 所有任务" not in text
    assert f"有 {n} 条告警" in text
    assert "覆盖 43/43" in text


# ---------------------------------------------------------------- 退出失败 / 漏跑 / 未知

def test_unit_failure_blocks_ok_and_names_unit(concl):
    stats = _green_stats()
    stats[0] = _row("pf_score_daily", unit="trade-pf-score-daily.service",
                    unit_exit=124, unit_result="timeout", last_exit=124)
    text = concl(stats, NOW)
    assert "OK 所有任务" not in text
    assert "pf-score-daily" in text and "exit=124" in text
    assert "1 个任务退出失败" in text and "漏跑 0" in text


def test_missed_blocks_ok(concl):
    stats = _green_stats()
    stats[1] = _row("gold_night", unit_missed=True, next_elapse="2026-10-20 09:25:00")
    text = concl(stats, NOW)
    assert "OK 所有任务" not in text
    assert "漏跑 1" in text


def test_unknown_exit_blocks_ok(concl):
    stats = _green_stats()
    stats[2] = _row("fapi_daily", unit_exit=None, last_exit=None, exit_source="unknown")
    text = concl(stats, NOW)
    assert "OK 所有任务" not in text
    assert "退出码未知 1 个(无法确认成功)" in text


@pytest.mark.parametrize("src", ["never-ran", "no-record", "missing", "unknown-result"])
def test_unconfirmed_sources_block_ok(concl, src):
    """P2-6: 没有可信终态的四种诊断标签都必须阻断 OK(危险的是「以为成功」)。"""
    stats = _green_stats()
    stats[3] = _row("gold_night", unit_exit=None, last_exit=None, exit_source=src)
    text = concl(stats, NOW)
    assert "OK 所有任务" not in text
    assert "退出码未知 1 个(无法确认成功)" in text


def test_running_source_does_not_block_ok(concl):
    """在跑(exit_source=running)不是失败/无记录, 保持旧行为(不阻断 OK)。"""
    stats = _green_stats()
    stats[4] = _row("update_all", unit_exit=None, last_exit=None,
                    exit_source="running", unit_start=None, unit_exit_ts=None)
    assert concl(stats, NOW).startswith("OK 所有任务")


# ---------------------------------------------------------------- 仅日志口径(回滚 / 本机 mac)

def test_log_mode_clean_is_x6_exact(concl):
    text = concl(_green_stats(19), NOW, mode="log", systemd_available=False)
    assert text == "OK(仅日志口径, 覆盖 17/40; 本机无 systemd)"
    assert "43/43" not in text


def test_log_mode_alerts_do_not_claim_ok(concl):
    text = concl(_green_stats(19), NOW, alerts=2, mode="log", systemd_available=False)
    assert not text.startswith("OK")
    assert "有 2 条告警" in text and "17/40" in text


def test_log_mode_failure_names_task(concl):
    stats = _green_stats(19)
    stats[0] = _row("backfill_evening", unit_exit=None, last_exit=1, exit_source="log")
    text = concl(stats, NOW, mode="log", systemd_available=False)
    assert text == "1 个任务退出失败: backfill_evening(exit=1); 覆盖 17/40(仅日志口径)"