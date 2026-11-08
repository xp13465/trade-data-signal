"""nextday 主源降级必须由同轮全部计划目标真实价和收尾证明恢复。纯日志输入，零外发。"""
import ast
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import sys
import types
import socket
import subprocess

import pytest
import gen_schedule_stats as gss

FIXTURE = Path(__file__).parent / "fixtures/nextday_fallback/nov2_complete.log"
NOV2 = FIXTURE.read_text(encoding="utf-8")
PRIMARY = NOV2.splitlines()[3]
READY = NOV2.splitlines()[4]
PLAN = NOV2.splitlines()[2]
SUMMARY = NOV2.splitlines()[5]
END = NOV2.splitlines()[6]
# 构造新契约边界样本，不是历史Nov2已具备模式证明。
LIVE_WINDOW = NOV2.replace(PLAN, "[nextday_gap_check] 执行模式=live 执行日=20261102\n" + PLAN)


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("日志测试不允许网络或子进程外发")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)


def scan(tmp_path, text=LIVE_WINDOW, exit_code=0, script="nextday_gap_check.sh", mode="standard"):
    p = tmp_path / "nextday.log"
    p.write_text(text, encoding="utf-8")
    result, skip = gss.scan_log_anomaly(p, script, mode, last_exit=exit_code)
    assert skip == text.count("SKIPPED_LOCKED")
    assert p.read_text(encoding="utf-8") == text  # 原始降级原因保留可见
    return result


def test_explicit_live_contract_fallback_is_recovered(tmp_path, capsys):
    assert scan(tmp_path) is None
    assert "[nextday-fallback-self-heal]" in capsys.readouterr().out


def test_all_targets_must_be_priced(tmp_path):
    text = LIVE_WINDOW.replace("ETF=1: ['513260']", "ETF=2: ['510300', '513260']")
    text = text.replace(SUMMARY, "[nextday_gap_check] 执行日 20261102 全部 2 笔无伪跳空, 无标记")
    text = text.replace(READY, READY + "\n" + READY.replace("513260", "510300"))
    assert scan(tmp_path, text) is None


def test_real_priced_exclusion_with_persistence_completed(tmp_path):
    excluded = READY.replace("✓ 513260 正常", "✗ 513260 伪跳空剔除").replace("open=0.904", "open=1.2").replace("gap=0.44%", "gap=33.33%")
    text = LIVE_WINDOW.replace(READY, excluded).replace(SUMMARY, "[nextday_gap_check] 落盘完成: /tmp/auto_trade_steps.json, /tmp/nextday_plan.json")
    assert scan(tmp_path, text) is None


@pytest.mark.parametrize("old,new", [
    (PLAN, ""),
    ("ETF=1:", "ETF=2:"),
    ("['513260']", "['513260', '513260']"),
    ("['513260']", "[513260]"),
    ("['513260']", "['513260', bad]"),
    ("['513260']", "[]"),
    (READY, ""),
    (READY, "[nextday_gap_check] ✓ 重试成功(第1次失败后重试)"),
    (READY, "[1/1] ✓ unrelated.json"),
    (READY, READY.replace("513260", "510300")),
    ("open=0.904", "open=0"),
    ("open=0.904", "open=-1"),
    ("open=0.904", "open=nan"),
    ("open=0.904", "open=inf"),
    ("open=0.904", "open=1e999"),
    ("sig_close=0.9", "sig_close=0"),
    (SUMMARY, ""),
    (SUMMARY, SUMMARY.replace("20261102", "20261103")),
    (SUMMARY, SUMMARY.replace("全部 1", "全部 2")),
    (END, ""),
    ("退出码=0", "退出码=2"),
    ("退出码=0", ""),
])
def test_incomplete_or_malformed_evidence_still_alerts(tmp_path, old, new):
    got = scan(tmp_path, LIVE_WINDOW.replace(old, new))
    assert got and got["keyword"] == "ConnectionError:"


@pytest.mark.parametrize("exit_code", [None, 1, 2, 124, 143])
def test_nonzero_or_unknown_exit_does_not_heal(tmp_path, exit_code):
    assert scan(tmp_path, exit_code=exit_code) is not None


@pytest.mark.parametrize("extra", [
    "[nextday_gap_check] --test-open 注入开盘价: {'513260': 0.904}",
    "[nextday_gap_check] DRY-RUN: 不落盘不 R2 不通知",
    "[nextday_gap_check]   ~ 513260 开盘价未取得(op=None), 标记未完成(待人工)",
    "[nextday_gap_check] ✗ 开盘价就绪闸 FAIL(重试后仍失败): missing; 标记未完成(待人工)",
    PLAN,
    READY,
    PRIMARY,
])
def test_ambiguous_or_failed_tail_cannot_heal(tmp_path, extra):
    assert scan(tmp_path, LIVE_WINDOW.replace(END, extra + "\n" + END)) is not None


def test_partial_missing_exit_zero_even_with_successful_other_target(tmp_path):
    text = LIVE_WINDOW.replace("ETF=1: ['513260']", "ETF=2: ['510300', '513260']")
    text = text.replace(SUMMARY, "[nextday_gap_check]   ~ 510300 开盘价未取得(op=None), 标记未完成(待人工)\n[nextday_gap_check] 落盘完成: /tmp/auto_trade_steps.json")
    assert scan(tmp_path, text) is not None


def test_all_sources_fail_real_producer_shape(tmp_path):
    failure = "[nextday_gap_check] ⚠ 第 1 次拉开盘价失败: 就绪闸: 未取得任何目标真实开盘价(fail-closed)\n[nextday_gap_check] ✗ 开盘价就绪闸 FAIL(重试后仍失败): 就绪闸: 未取得任何目标真实开盘价(fail-closed); 标记未完成(待人工)"
    text = LIVE_WINDOW.replace(READY, failure).replace(SUMMARY, "").replace("退出码=0", "退出码=2")
    assert scan(tmp_path, text, exit_code=2) is not None


def test_price_before_last_degradation_is_not_recovery(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace(PRIMARY + "\n" + READY, READY + "\n" + PRIMARY)) is not None


def test_plan_after_degradation_is_not_same_attempt(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace(PLAN + "\n" + PRIMARY, PRIMARY + "\n" + PLAN)) is not None


def test_success_from_previous_round_cannot_heal_latest_failure(tmp_path):
    failed = LIVE_WINDOW.replace(READY, "").replace(SUMMARY, "").replace("2026-11-02", "2026-11-03")
    assert scan(tmp_path, LIVE_WINDOW + failed) is not None


def test_success_before_next_wrapper_is_not_imported(tmp_path):
    failed = LIVE_WINDOW.replace(READY, "").replace(SUMMARY, "")
    assert scan(tmp_path, failed + READY + "\n" + SUMMARY + "\n") is not None


def test_old_failed_round_does_not_poison_latest_recovered_round(tmp_path):
    failed = LIVE_WINDOW.replace(READY, "").replace(SUMMARY, "").replace("2026-11-02", "2026-11-01")
    assert scan(tmp_path, failed + LIVE_WINDOW) is None


def test_repeated_primary_failure_can_heal_only_after_final_attempt(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace(PRIMARY, PRIMARY + "\n" + PRIMARY)) is None


@pytest.mark.parametrize("tail,keyword", [
    ("ConnectionError: other operation failed", "ConnectionError:"),
    ("Traceback (most recent call last):", "Traceback (most recent call last)"),
    ("FATAL persistence failed", "FATAL"),
    ("✗ R2 上传失败", "✗ R2 上传失败"),
])
def test_unrelated_real_errors_remain_visible(tmp_path, tail, keyword):
    got = scan(tmp_path, LIVE_WINDOW.replace(END, tail + "\n" + END))
    assert got and got["keyword"] == keyword


def test_same_producer_message_under_other_task_is_not_suppressed(tmp_path):
    text = LIVE_WINDOW.replace("nextday_gap_check.sh", "intraday_snapshot.sh")
    assert scan(tmp_path, text, script="intraday_snapshot.sh") is not None


def test_unrelated_primary_message_not_suppressed(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace("fund_etf_spot_em", "other_source")) is not None


@pytest.mark.parametrize("body,exit_code,expected", [
    ("⚠ PUT data/boot.json attempt 1 失败(TimeoutError: timed out), 1s 后重试\n[1/1] ✓ boot.json", 0, None),
    ("⚠ PUT data/boot.json attempt 1 失败(TimeoutError: timed out), 1s 后重试\n[1/1] ✓ boot.json", None, None),
    ("⚠ PUT data/B.json attempt 1 失败(ConnectionError: disconnected), 1s 后重试\n[1/1] ✓ A.json", 1, "critical"),
    ("⚠ PUT data/B.json attempt 1 失败(ConnectionError: disconnected), 1s 后重试", None, "degrade"),
    ("⚠ PUT data/B.json attempt 1 失败(ConnectionError: disconnected), 1s 后重试", 0, None),
])
def test_existing_upload_self_heal_contract(tmp_path, body, exit_code, expected):
    text = "=== upload.sh 开始 2026-11-02 09:26:00 ===\n" + body
    if exit_code is not None:
        text += f"\n=== upload.sh 结束 2026-11-02 09:26:06 退出码={exit_code} ===\n"
    got = scan(tmp_path, text, exit_code=exit_code, script="upload.sh")
    assert (got["severity"] if got else None) == expected


@pytest.mark.parametrize("text,expected", [(LIVE_WINDOW, False), (LIVE_WINDOW.replace(READY, "").replace(SUMMARY, ""), True)], ids=["recovered", "unrecovered"])
def test_real_stats_fields_consumed_by_monitor(tmp_path, monkeypatch, text, expected):
    monkeypatch.setattr(gss.ut, "exit_source_mode", lambda: "log")
    monkeypatch.setattr(gss, "_systemd_last_exit", lambda label: None)
    monkeypatch.setattr(gss, "_unit_active_state", lambda label: None)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "nextday_gap_check_launchd.log").write_text(text, encoding="utf-8")
    out = tmp_path / "schedule_stats.json"
    rows = gss.build(log_dir=log_dir, out=out, now=datetime(2026, 11, 2, 9, 30))
    row = next(row for row in rows if row["task"] == "nextday_gap_check")
    assert row["last_exit"] == 0
    assert row["log_anomaly"] is expected
    assert row["log_anomaly_keyword"] == ("ConnectionError:" if expected else None)
    assert json.loads(out.read_text()) == rows


def test_real_fixture_gzip_has_same_recovery(tmp_path):
    p = tmp_path / "nextday.log"
    with gzip.open(str(p) + ".gz", "wt", encoding="utf-8") as f:
        f.write(LIVE_WINDOW)
    assert gss.scan_log_anomaly(p, "nextday_gap_check.sh", "standard", last_exit=0) == (None, 0)


def test_exact_primary_line_comes_from_real_producer(tmp_path, monkeypatch, capsys):
    producer = Path(os.environ.get("NEXTDAY_FALLBACK_PRODUCER_SOURCE", str(Path(__file__).parents[1] / "signal_kelly_backtest.py")))
    source = producer.read_text(encoding="utf-8")
    func = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)
                and node.name == "_fetch_intraday_open_prices")
    def fail_primary():
        raise ConnectionError("upstream disconnected")
    akshare = types.ModuleType("akshare")
    akshare.fund_etf_spot_em = fail_primary
    monkeypatch.setitem(sys.modules, "akshare", akshare)
    ns = {"sys": sys, "_fetch_intraday_open_via_http": lambda codes, expect_date: ({"513260": 0.904}, [])}
    exec(compile(ast.Module(body=[func], type_ignores=[]), "real-producer", "exec"), ns)
    got = ns["_fetch_intraday_open_prices"](["513260"], expect_date="20261102")
    assert got == ({"513260": 0.904}, [], {"main_source_ok": False, "fallback_used": True})
    emitted = capsys.readouterr().err.strip()
    # freeze owner转义前/后两个确切契约；组合测试直接读取owner真实源。
    assert emitted in (
        "[就绪闸] 主源 fund_etf_spot_em 失败(ConnectionError: upstream disconnected), 全量走双源兜底",
        "[就绪闸] 主源 fund_etf_spot_em 失败(ConnectionError: 'upstream disconnected'), 全量走双源兜底",
    )
    assert scan(tmp_path, LIVE_WINDOW.replace(PRIMARY, emitted)) is None


@pytest.mark.parametrize("replacement", [
    "[nextday_gap_check] 执行日 20261102 全部 2 笔无伪跳空, 无标记",
    "[nextday_gap_check] 落盘完成: /tmp/auto_trade_steps.json",
])
def test_partial_price_with_bogus_success_summary_cannot_heal(tmp_path, replacement):
    text = LIVE_WINDOW.replace("ETF=1: ['513260']", "ETF=2: ['510300', '513260']").replace(SUMMARY, replacement)
    assert scan(tmp_path, text) is not None


def test_real_exclusion_without_persistence_cannot_heal(tmp_path):
    excluded = READY.replace("✓ 513260 正常", "✗ 513260 伪跳空剔除")
    assert scan(tmp_path, LIVE_WINDOW.replace(READY, excluded).replace(SUMMARY, "")) is not None


def test_nested_wrapper_cannot_supply_recovery(tmp_path):
    nested = "=== other.sh 开始 2026-11-02 09:26:01 ===\n" + READY + "\n=== other.sh 结束 2026-11-02 09:26:02 退出码=0 ==="
    assert scan(tmp_path, LIVE_WINDOW.replace(READY, nested)) is not None


def test_other_task_success_cannot_supply_recovery(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace("[nextday_gap_check]   ✓", "[other_task]   ✓")) is not None


def test_price_rows_after_summary_do_not_heal(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace(READY + "\n" + SUMMARY, SUMMARY + "\n" + READY)) is not None


def test_skip_count_retained_with_recovered_fallback(tmp_path):
    assert scan(tmp_path, LIVE_WINDOW.replace(END, "SKIPPED_LOCKED\n" + END)) is None
