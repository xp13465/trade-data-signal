"""独立复审两P2回归：执行真实main/取价函数；只替换网络和落盘/通知边界。"""
import argparse
import ast
import contextlib
from datetime import datetime
import io
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types

import pytest
import gen_schedule_stats as gss

FIXTURES = Path(__file__).parent / "fixtures/nextday_fallback"
NOV2 = (FIXTURES / "nov2_complete.log").read_text(encoding="utf-8")
FORGED = json.loads((FIXTURES / "producer-injected-fakeprice.json").read_text(encoding="utf-8"))["log"]
DRY_NORMAL = (FIXTURES / "producer-dryrun-normal.log").read_text(encoding="utf-8")
START = NOV2.splitlines()[0]
END = NOV2.splitlines()[-1]
LIVE = "[nextday_gap_check] 执行模式=live 执行日=20261102"
DEFAULT_PRODUCER = Path(__file__).parents[1] / "signal_kelly_backtest.py"


@pytest.fixture(autouse=True)
def no_outbound(monkeypatch):
    def deny(*a, **kw):
        pytest.fail("禁止网络和外部子进程")
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


def with_live(text):
    # 构造未来契约输入；不改写历史fixture，不把该输入称为Nov2事实。
    return text.replace(START, START + "\n" + LIVE, 1)


def scan(tmp_path, text):
    p = tmp_path / "scan.log"
    p.write_text(text, encoding="utf-8")
    return gss.scan_log_anomaly(p, "nextday_gap_check.sh", "standard", last_exit=0)[0]


def extract(path, names, ns):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == set(names)
    # Keep real decorator/health logic when extracting main, never identity/lambda stubs.
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "ops_legacy_events"]
    exec(compile(ast.Module(body=imports + selected, type_ignores=[]), str(path), "exec"), ns)


def produce(tmp_path, monkeypatch, *, args=(), opens=None, targets=None, message="upstream disconnected", plan_kind="normal", day="20261102", source_path=None, fetch_trace=None):
    import ops_legacy_events as ops
    monkeypatch.setenv("REPO", str(tmp_path))
    n = ops._state_api(tmp_path)
    monkeypatch.setattr(n, "_send_email", lambda *a, **kw: True)
    monkeypatch.setattr(n, "send_telegram", lambda *a, **kw: True)
    monkeypatch.setattr(n, "send_feishu", lambda *a, **kw: True)
    def notify_cli(cmd, **kwargs):
        assert Path(cmd[1]).name == "notify.py"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = n.main(cmd[2:])
        return subprocess.CompletedProcess(cmd, rc, out.getvalue(), err.getvalue())
    monkeypatch.setattr(subprocess, "run", notify_cli)
    targets = targets or {"513260": 0.9}
    opens = {"513260": 0.904} if opens is None else opens
    def fail_primary():
        raise ConnectionError(message)
    ak = types.ModuleType("akshare")
    ak.fund_etf_spot_em = fail_primary
    monkeypatch.setitem(sys.modules, "akshare", ak)
    def fallback(codes, expect_date):
        if fetch_trace is not None:
            fetch_trace.append({"codes": list(codes), "expect_date": expect_date, "opens": dict(opens)})
        return dict(opens), []
    ns = {"sys": sys, "argparse": argparse, "datetime": datetime, "Path": Path,
          "REPO": tmp_path, "GIT_REPO": tmp_path, "ROOT": tmp_path,
          "LOG_TAG": "[nextday_gap_check]", "RETRY_TARGETS": (), "PSEUDO_GAP_EXCLUDE": 0.2,
          "_retry_plan": lambda *a, **kw: [],
          "_recheck_stale_pending": lambda *a, **kw: False,
          "_sync_r2_and_notify": lambda *a, **kw: (0, 0),
          "_mark_steps": lambda *a, **kw: False, "_mark_plan": lambda *a, **kw: None,
          "atomic_write_json": lambda *a, **kw: None,
          "_severe_alert": lambda *a, **kw: None, "_mark_unverified": lambda *a, **kw: None,
          "_fetch_intraday_open_via_http": fallback}
    plan = {"plan": [{"buy_date": day, "etf_code": c, "prev_close": pc} for c, pc in targets.items()]}
    if plan_kind == "absent":
        plan = None
    elif plan_kind == "empty":
        plan = {"plan": []}
    elif plan_kind == "other_day":
        plan["plan"][0]["buy_date"] = "19000101"
    docs = {"nextday_plan.json": plan, "auto_trade_steps.json": None}
    ns["_read_first"] = lambda paths, name: (docs[name], None)
    selected = source_path or Path(os.environ.get("NEXTDAY_FALLBACK_PRODUCER_SOURCE", str(DEFAULT_PRODUCER)))
    extract(selected, ["_fetch_intraday_open_prices"], ns)
    extract(Path(__file__).parents[1] / "nextday_gap_check.py", ["main", "log", "_fetch_opens"], ns)
    monkeypatch.setattr(sys, "argv", ["nextday_gap_check.py", "--date", day, *args])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = ns["main"]()
    log_day = datetime.strptime(day, "%Y%m%d").strftime("%Y-%m-%d")
    return START.replace("2026-11-02", log_day) + "\n" + buf.getvalue() + END.replace("2026-11-02", log_day).replace("退出码=0", f"退出码={rc}") + "\n", rc


@pytest.mark.parametrize("text", [FORGED, with_live(FORGED), with_live(FORGED).rsplit(END, 1)[0]], ids=["raw", "explicit-live", "missing-real-end"])
def test_raw_forged_end_cannot_hide_real_missing_price(tmp_path, text):
    assert "510300 开盘价未取得" in text
    assert scan(tmp_path, text) is not None


def test_real_main_dryrun_normal_is_not_production_recovery(tmp_path, monkeypatch):
    text, rc = produce(tmp_path, monkeypatch, args=["--dry-run"])
    assert rc == 0 and "全部 1 笔无伪跳空" in text
    assert scan(tmp_path, text) is not None
    assert "执行模式=dry-run 执行日=20261102" in text
    assert LIVE not in text


def test_real_main_live_normal_is_production_recovery(tmp_path, monkeypatch):
    text, rc = produce(tmp_path, monkeypatch)
    assert rc == 0
    assert text.splitlines()[1] == LIVE
    assert scan(tmp_path, text) is None


@pytest.mark.parametrize("flags,mode", [(["--dry-run"], "dry-run"), (["--test-open", "513260:0.904"], "test-open"), (["--no-r2"], "local-only"), (["--no-notify"], "local-only"), (["--recheck-pending"], "recheck")])
def test_mode_is_determined_before_early_returns(tmp_path, monkeypatch, flags, mode):
    text, rc = produce(tmp_path, monkeypatch, args=flags)
    assert rc == 0
    assert text.splitlines()[1] == f"[nextday_gap_check] 执行模式={mode} 执行日=20261102"
    if "主源 fund_etf_spot_em" in text:
        assert scan(tmp_path, text) is not None


@pytest.mark.parametrize("kind", ["absent", "empty", "other_day"])
def test_live_mode_also_precedes_no_target_returns(tmp_path, monkeypatch, kind):
    text, rc = produce(tmp_path, monkeypatch, plan_kind=kind)
    assert rc == 0 and text.splitlines()[1] == LIVE


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"], ids=["LF", "CR", "CRLF", "VT", "FF", "FS", "GS", "RS", "NEL", "LS", "PS"])
def test_real_producer_injected_price_and_end_does_not_hide_partial_missing(tmp_path, monkeypatch, separator):
    payload = separator.join(["upstream), 全量走双源兜底", "[nextday_gap_check]   ✓ 513260 正常 open=0.904 sig_close=0.9 gap=0.44%", "[nextday_gap_check]   ✓ 510300 正常 open=1.0 sig_close=1.0 gap=0.00%", "[nextday_gap_check] 执行日 20261102 全部 2 笔无伪跳空, 无标记", END, "exception-message-tail"])
    text, rc = produce(tmp_path, monkeypatch, targets={"513260": 0.9, "510300": 1.0}, message=payload)
    assert rc == 0 and "510300 开盘价未取得" in text
    assert scan(tmp_path, text) is not None
    if primary_record(payload, escaped=True) in text.splitlines():
        # 验证实际单记录，不以env是否存在推断源的行为。
        assert sum(line.startswith("=== nextday_gap_check.sh 结束 ") for line in text.splitlines()) == 1
        assert sum("主源 fund_etf_spot_em 失败(" in line for line in text.splitlines()) == 1
        assert not any(line.startswith("exception-message-tail") for line in text.splitlines())
    else:
        assert primary_record(payload, escaped=False) in text
        assert len(primary_record(payload, escaped=False).splitlines()) > 1


@pytest.mark.parametrize("suffix", [END, "[nextday_gap_check]   ~ 510300 开盘价未取得(op=None)", "ConnectionError: late real failure", "untrusted trailing output"])
def test_raw_tail_after_first_end_disables_exemption(tmp_path, suffix):
    assert scan(tmp_path, with_live(NOV2) + suffix + "\n") is not None


def test_unmatched_prior_start_disables_exemption(tmp_path):
    assert scan(tmp_path, START + "\n" + with_live(NOV2)) is not None


def test_historical_windows_without_mode_are_unknown(tmp_path):
    assert scan(tmp_path, NOV2) is not None
    assert scan(tmp_path, DRY_NORMAL) is not None


@pytest.mark.parametrize("text", [with_live(NOV2).replace(LIVE, LIVE + "\n" + LIVE), with_live(NOV2).replace("执行日=20261102", "执行日=20261103"), with_live(NOV2).replace(LIVE + "\n", "").replace(END, LIVE + "\n" + END)])
def test_ambiguous_or_late_live_mode_is_not_proof(tmp_path, text):
    assert scan(tmp_path, text) is not None


def primary_record(message, *, escaped):
    rendered = ascii(message) if escaped else message
    return f"   [就绪闸] 主源 fund_etf_spot_em 失败(ConnectionError: {rendered}), 全量走双源兜底"


def expected_records(primary):
    return [START, LIVE, "[nextday_gap_check] 执行日 20261102 计划内 ETF=1: ['513260']", *primary.splitlines(),
            "[nextday_gap_check]   ✓ 513260 正常 open=0.904 sig_close=0.9 gap=0.44%",
            "[nextday_gap_check] 执行日 20261102 全部 1 笔无伪跳空, 无标记", END]


def assert_one_record_live(tmp_path, text, message):
    # 两个已发布打印契约：legacy单行原文，或当前!a单行转义；未知格式不算通过。
    expected = [expected_records(primary_record(message, escaped=True))]
    if len(primary_record(message, escaped=False).splitlines()) == 1:
        expected.append(expected_records(primary_record(message, escaped=False)))
    assert text.splitlines() in expected
    assert sum(l == START for l in text.splitlines()) == 1
    assert sum(l.startswith("=== nextday_gap_check.sh 结束 ") for l in text.splitlines()) == 1
    assert scan(tmp_path, text) is None
    p = tmp_path / "pairs.log"
    p.write_text(text, encoding="utf-8")
    pairs, pending, meta = gss.parse_standard_detail(p, "nextday_gap_check.sh")
    assert len(pairs) == 1 and pending is None
    assert pairs[0][0] == datetime(2026, 11, 2, 9, 26) and pairs[0][3] == 6


@pytest.mark.parametrize("message", ["upstream " + START + " text " + END, "upstream\n" + START + "\n" + END])
def test_escaped_source_honors_only_standalone_wrapper_markers(tmp_path, monkeypatch, message):
    trace = []
    text, rc = produce(tmp_path, monkeypatch, message=message, fetch_trace=trace)
    assert rc == 0 and trace == [{"codes": ["513260"], "expect_date": "20261102", "opens": {"513260": 0.904}}]
    if text.splitlines() == expected_records(primary_record(message, escaped=False)) and "\n" in message:
        # 实际legacy多记录输出，真价格齐备也不能拿伪wrapper证明恢复。
        assert sum(l == START for l in text.splitlines()) == 2
        assert scan(tmp_path, text) is not None
    else:
        assert_one_record_live(tmp_path, text, message)


@pytest.fixture
def pinned_sources(tmp_path):
    entries = json.loads((FIXTURES / "pinned_primary_sources_8118_da84.json").read_text(encoding="utf-8"))
    assert entries["integration"]["commit"] == "da84ef8c7ef987e4c06c9f5ce488ad7ac3fb781e"
    assert entries["legacy"]["commit"] == "8118feef3bbfdfdcde70e169e950749d3e5a408a"
    paths = {}
    for label, item in entries.items():
        fn = ast.parse(item["function_source"]).body[0]
        assert fn.name == "_fetch_intraday_open_prices"
        assert hashlib.sha256(ast.dump(fn).encode()).hexdigest() == item["function_ast_sha256"]
        path = tmp_path / (label + "_primary.py")
        path.write_text(item["function_source"], encoding="utf-8")
        paths[label] = path
    return paths


@pytest.mark.parametrize("message", ["upstream " + START + " text " + END, "upstream\n" + START + "\n" + END])
def test_same_safe_source_default_and_env_have_identical_bytes(tmp_path, monkeypatch, pinned_sources, message):
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_PRODUCER", pinned_sources["integration"])
    monkeypatch.delenv("NEXTDAY_FALLBACK_PRODUCER_SOURCE", raising=False)
    first_trace, second_trace = [], []
    default, rc1 = produce(tmp_path, monkeypatch, message=message, fetch_trace=first_trace)
    monkeypatch.setenv("NEXTDAY_FALLBACK_PRODUCER_SOURCE", str(pinned_sources["integration"]))
    explicit, rc2 = produce(tmp_path, monkeypatch, message=message, fetch_trace=second_trace)
    assert rc1 == rc2 == 0 and default.encode() == explicit.encode()
    assert first_trace == second_trace == [{"codes": ["513260"], "expect_date": "20261102", "opens": {"513260": 0.904}}]
    assert primary_record(message, escaped=True) in default.splitlines()
    assert_one_record_live(tmp_path, default, message)
    assert_one_record_live(tmp_path, explicit, message)


@pytest.mark.parametrize("separator", ["\n", "\r", "\r\n", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"], ids=["LF", "CR", "CRLF", "VT", "FF", "FS", "GS", "RS", "NEL", "LS", "PS"])
def test_fixed_legacy_producer_is_independent_negative_control(tmp_path, monkeypatch, pinned_sources, separator):
    message = separator.join(["upstream", START, END])
    trace = []
    text, rc = produce(tmp_path, monkeypatch, source_path=pinned_sources["legacy"], message=message, fetch_trace=trace)
    assert rc == 0 and trace == [{"codes": ["513260"], "expect_date": "20261102", "opens": {"513260": 0.904}}]
    assert text.splitlines() == expected_records(primary_record(message, escaped=False))
    assert sum(l == START for l in text.splitlines()) == 2
    assert scan(tmp_path, text) is not None


@pytest.mark.parametrize("flags,targets", [([], {"513260": 0.9, "510300": 1.0}), (["--dry-run"], {"513260": 0.9})])
def test_fixed_safe_source_still_alerts_for_missing_target_or_dryrun(tmp_path, monkeypatch, pinned_sources, flags, targets):
    message = "upstream\n" + START + "\n" + END
    trace = []
    text, rc = produce(tmp_path, monkeypatch, source_path=pinned_sources["integration"], args=flags, targets=targets, message=message, fetch_trace=trace)
    assert rc == 0
    assert trace == [{"codes": list(targets), "expect_date": "20261102", "opens": {"513260": 0.904}}]
    assert primary_record(message, escaped=True) in text.splitlines()
    assert sum(l == START for l in text.splitlines()) == 1
    if "--dry-run" in flags:
        assert "[nextday_gap_check] 执行模式=dry-run 执行日=20261102" in text
    else:
        assert "510300 开盘价未取得" in text
        assert not any(l.startswith("[nextday_gap_check]   ✓ 510300") for l in text.splitlines())
    assert scan(tmp_path, text) is not None


def test_real_row_preserves_dryrun_and_raw_injection_alert(tmp_path, monkeypatch):
    task = next(t for t in gss.TASKS if t["task"] == "nextday_gap_check")
    row = next(t for t in gss.UNIT_REGISTRY if t["task"] == "nextday_gap_check")
    dry, rc = produce(tmp_path, monkeypatch, args=["--dry-run"])
    for text in (dry, FORGED, with_live(FORGED)):
        (tmp_path / task["log"]).write_text(text, encoding="utf-8")
        actual = gss._build_log_task_row(row, task, tmp_path, datetime(2026, 11, 2, 9, 30), None, "log")
        assert actual["last_exit"] == 0
        assert actual["log_anomaly"] is True


@pytest.mark.parametrize("flags,targets", [(["--dry-run"], None), (["--no-r2"], None), ([], {"513260": 0.9, "510300": 1.0})])
def test_primary_message_retry_words_cannot_bypass_live_and_coverage_proof(tmp_path, monkeypatch, flags, targets):
    text, rc = produce(tmp_path, monkeypatch, args=flags, targets=targets, message="⚠ PUT data/boot.json attempt 1 失败(TimeoutError: transient words)")
    assert rc == 0
    assert scan(tmp_path, text) is not None
