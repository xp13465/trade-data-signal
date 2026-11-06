"""OHLC空窗口诊断：完整模块、真实fetch/worker/store；不访问网络或生产库。"""
import builtins
import importlib.util
import io
import os
from pathlib import Path
import shutil
import smtplib
import socket
import sqlite3
import subprocess
import sys
import types

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
CODES = "581030 581000 581070 581050 581090 158076 158900 158902 158906 158901 158907".split()
START = "20261022"
DATE = "20261104"
FIELDS = ["etf_name", "open", "high", "low", "close", "amount"]


class Blocked(AssertionError):
    pass


@pytest.fixture
def case(tmp_path, monkeypatch):
    connect, original_open, original_io_open = sqlite3.connect, builtins.open, io.open

    def deny(*args, **kwargs):
        raise Blocked("业务出口已拦截")

    def local_connect(path, *args, **kwargs):
        if str(path) != ":memory:" and not Path(path).resolve().is_relative_to(tmp_path):
            return deny()
        return connect(path, *args, **kwargs)

    def local_open(original):
        def checked(file, mode="r", *args, **kwargs):
            if any(c in mode for c in "wax+") and not isinstance(file, int):
                if not Path(file).resolve().is_relative_to(tmp_path):
                    return deny()
            return original(file, mode, *args, **kwargs)
        return checked

    monkeypatch.setattr(socket, "socket", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(smtplib, "SMTP", deny)
    monkeypatch.setattr(smtplib, "SMTP_SSL", deny)
    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(os, "system", deny)
    monkeypatch.setattr(sqlite3, "connect", local_connect)
    monkeypatch.setattr(builtins, "open", local_open(original_open))
    monkeypatch.setattr(io, "open", local_open(original_io_open))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setenv("REPO", str(tmp_path))
    monkeypatch.setenv("GIT_REPO", str(tmp_path))
    # 先正控出口，再导入业务模块；没有不可撤回的全局audit hook。
    for attempt in (socket.socket, smtplib.SMTP, smtplib.SMTP_SSL,
                    lambda: socket.create_connection(("invalid.example", 443)),
                    lambda: socket.getaddrinfo("invalid.example", 443),
                    lambda: subprocess.run(["forbidden"]), lambda: os.system("forbidden"),
                    lambda: sqlite3.connect(ROOT / "data/forbidden-test.db"),
                    lambda: (ROOT / ".forbidden-ohlc-test").write_text("never")):
        with pytest.raises(Blocked):
            attempt()

    path = tmp_path / "app/collector/etf_national_team.py"
    path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "app/collector/etf_national_team.py", path)
    namespace = "_codex_ohlc_warning_test"

    def module(name, **attrs):
        result = types.ModuleType(name)
        result.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    module(namespace, __path__=[])
    module(namespace + ".collector", __path__=[])
    module(namespace + ".collector.base",
           safe_call=lambda fn, *a, **kw: fn(*a, **{k: v for k, v in kw.items() if k != "skip_throttle"}),
           em_get=deny, throttle=lambda *a: None)
    module(namespace + ".collector.nav_placeholder_defense",
           is_placeholder_row=lambda *a: False, trading_gap_between=lambda *a: 0)
    module("util_atomic", atomic_write_json=deny)
    module("requests", get=deny, post=deny)
    ak = module("akshare")
    state = types.SimpleNamespace(primary=None, fallback=None, calls=[])

    def sina(*args, **kwargs):
        state.calls.append(("sina", kwargs))
        return state.primary

    ak.fund_etf_hist_sina = sina

    class Client:
        def bars(self, **kwargs):
            state.calls.append(("mootdx", kwargs))
            return state.fallback

    client = Client()
    spec = importlib.util.spec_from_file_location(namespace + ".collector.etf_national_team", path)
    m = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, m)
    spec.loader.exec_module(m)
    monkeypatch.setattr(m, "_get_worker_tdx", lambda: client)
    conn = sqlite3.connect(":memory:")
    conn.executescript(m.SCHEMA)

    def seed(code):
        m._upsert_daily(conn, [dict(date=DATE, etf_code=code, etf_name="既有名称",
                                   open=9, high=10, low=8, close=9.5, amount=99)], FIELDS)

    def snapshot():
        return conn.execute("SELECT * FROM etf_daily ORDER BY date,etf_code").fetchall()

    def fetch(code, entry="daily"):
        if entry == "fetch":
            return m.fetch_etf_ohlc(code, START, client)
        worker = m._fetch_one_ohlc_worker if entry == "daily" else m._fetch_one_backfill_worker
        got_code, _, rows = worker((code, "测试ETF", m._etf_market(code), START))
        assert got_code == code
        return rows

    yield types.SimpleNamespace(m=m, state=state, conn=conn, client=client,
                                seed=seed, snapshot=snapshot, fetch=fetch)
    conn.close()


def row(date=DATE, amount=100.):
    return dict(date=date, open=2., high=3., low=1., close=2.5, amount=amount)


def assert_warning(output, code, count=1):
    assert output.count("WARNING") == count
    assert output.count(f"[ohlc] WARNING {code}") == count
    assert f"start={START}" in output
    assert "未取得OHLC" in output
    assert "本轮不写OHLC" in output and "已有行情保留" in output
    assert "新份额行可能缺行情" in output
    assert "均返空" not in output and "将为 NULL" not in output
    assert "未上市" not in output


@pytest.mark.parametrize("code", CODES)
@pytest.mark.parametrize("existing", (False, True))
@pytest.mark.parametrize("empty_mode", ("no_rows", "history_before_start"))
def test_empty_window_real_worker_preserves_history(case, capsys, code, existing, empty_mode):
    if existing:
        case.seed(code)
    before = case.snapshot()
    if empty_mode == "history_before_start":
        # 原始主源有数据，只因日期筛选变空，不能宣称两端点原响应都空。
        case.state.primary = pd.DataFrame([row("2026-10-01")])
    rows = case.fetch(code)
    assert rows == []
    assert case.m._upsert_daily(case.conn, rows, FIELDS) == 0
    assert case.snapshot() == before
    assert_warning(capsys.readouterr().out, code)
    assert [name for name, _ in case.state.calls] == ["sina", "mootdx"]
    assert case.state.calls[0][1]["symbol"] == ("sh" if code.startswith("58") else "sz") + code
    assert case.state.calls[1][1] == dict(symbol=code, frequency=9, offset=800, start=0)
    # 实际份额writer仅更新fund_share；新份额日可能有份额而无OHLC。
    case.m._upsert_daily(case.conn, [dict(date="20261105", etf_code=code, fund_share=1)], ["fund_share"])
    assert case.conn.execute("SELECT open,high,low,close,amount,fund_share FROM etf_daily "
                             "WHERE date='20261105' AND etf_code=?", (code,)).fetchone() == (
                                 None, None, None, None, None, 1.)
    if existing:
        # 同日份额更新也不清行情。
        case.m._upsert_daily(case.conn, [dict(date=DATE, etf_code=code, fund_share=2)], ["fund_share"])
        assert case.conn.execute("SELECT close,amount,fund_share FROM etf_daily WHERE date=? AND etf_code=?",
                                 (DATE, code)).fetchone() == (9.5, 99., 2.)


@pytest.mark.parametrize("code", ("581030", "158076"))
@pytest.mark.parametrize("existing", (False, True))
def test_full_history_worker_empty_uses_same_warning_and_no_write(case, capsys, code, existing):
    if existing:
        case.seed(code)
    before = case.snapshot()
    rows = case.fetch(code, "backfill")
    assert case.m._upsert_daily(case.conn, rows, FIELDS) == 0
    assert case.snapshot() == before
    assert_warning(capsys.readouterr().out, code)


@pytest.mark.parametrize("code", ("581030", "158076"))
@pytest.mark.parametrize("source", ("primary", "fallback"))
@pytest.mark.parametrize("amount", (0., 100.))
def test_normal_sources_same_data_units_and_legitimate_update(case, capsys, code, source, amount):
    case.seed(code)
    raw = row("2026-11-04", amount)
    if source == "primary":
        case.state.primary = pd.DataFrame([raw])
    else:
        case.state.fallback = pd.DataFrame([{k: v for k, v in raw.items() if k != "date"}],
                                           index=[pd.Timestamp("2026-11-04")])
    # 直接真实fetch入口：主/备同口径fixture原数值返回，不复权、不换单位。
    rows = case.fetch(code, "fetch")
    assert rows == [dict(date=DATE, etf_code=code, open=2., close=2.5, high=3., low=1., amount=amount)]
    assert "WARNING" not in capsys.readouterr().out
    for item in rows:
        item["etf_name"] = "正常修订"
    assert case.m._upsert_daily(case.conn, rows, FIELDS) == 1
    assert case.conn.execute("SELECT etf_name,open,high,low,close,amount FROM etf_daily "
                             "WHERE date=? AND etf_code=?", (DATE, code)).fetchone() == (
                                 "正常修订", 2., 3., 1., 2.5, amount)
    assert [name for name, _ in case.state.calls] == (["sina"] if source == "primary" else ["sina", "mootdx"])


def test_repeated_empty_requests_are_not_silenced(case, capsys):
    for _ in range(2):
        assert case.fetch("581030", "fetch") == []
    assert_warning(capsys.readouterr().out, "581030", count=2)
