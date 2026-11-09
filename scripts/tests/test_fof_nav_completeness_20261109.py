"""NAV 完整性回归：真实016989响应重放、批次公平性，所有写入仅临时SQLite。"""
import json
import socket
from datetime import date
from pathlib import Path

import pytest

from scripts import collect_fof_nav as mod
from scripts.tests.test_collect_fof_nav_333 import _conn, _seed_basic, _FakeResp

# 2026-11-09只读获取的016989真实lsjz响应；不访问网络，不以生成数字替代真值。
REAL_016989 = {'Data': {'LSJZList': [{'FSRQ': '2026-11-06', 'DWJZ': '1.1540', 'LJJZ': '1.1540', 'SDATE': None, 'ACTUALSYI': '', 'NAVTYPE': '1', 'JZZZL': '-1.48', 'SGZT': '开放申购', 'SHZT': '开放赎回', 'FHFCZ': '', 'FHFCZ10': '', 'FHFCBZ': '', 'DTYPE': None, 'FHSP': ''}, {'FSRQ': '2026-11-05', 'DWJZ': '1.1713', 'LJJZ': '1.1713', 'SDATE': None, 'ACTUALSYI': '', 'NAVTYPE': '1', 'JZZZL': '0.71', 'SGZT': '开放申购', 'SHZT': '开放赎回', 'FHFCZ': '', 'FHFCZ10': '', 'FHFCBZ': '', 'DTYPE': None, 'FHSP': ''}, {'FSRQ': '2026-11-04', 'DWJZ': '1.1631', 'LJJZ': '1.1631', 'SDATE': None, 'ACTUALSYI': '', 'NAVTYPE': '1', 'JZZZL': '2.95', 'SGZT': '开放申购', 'SHZT': '开放赎回', 'FHFCZ': '', 'FHFCZ10': '', 'FHFCBZ': '', 'DTYPE': None, 'FHSP': ''}, {'FSRQ': '2026-11-03', 'DWJZ': '1.1298', 'LJJZ': '1.1298', 'SDATE': None, 'ACTUALSYI': '', 'NAVTYPE': '1', 'JZZZL': '-0.93', 'SGZT': '开放申购', 'SHZT': '开放赎回', 'FHFCZ': '', 'FHFCZ10': '', 'FHFCBZ': '', 'DTYPE': None, 'FHSP': ''}, {'FSRQ': '2026-11-02', 'DWJZ': '1.1404', 'LJJZ': '1.1404', 'SDATE': None, 'ACTUALSYI': '', 'NAVTYPE': '1', 'JZZZL': '0.80', 'SGZT': '开放申购', 'SHZT': '开放赎回', 'FHFCZ': '', 'FHFCZ10': '', 'FHFCBZ': '', 'DTYPE': None, 'FHSP': ''}], 'FundType': '002', 'SYType': None, 'isNewType': False, 'Feature': '030,073,211,701'}, 'ErrCode': 0, 'ErrMsg': None, 'TotalCount': 5, 'Expansion': None, 'PageSize': 20, 'PageIndex': 1}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    db = tmp_path / "public_fund.db"
    monkeypatch.setattr(mod, "DB_PATH", db)
    c = _conn(db)
    c.close()
    monkeypatch.setattr(mod, "get_conn", lambda: _conn(db))
    monkeypatch.setattr(mod, "init_db", lambda: None)
    monkeypatch.setattr(mod, "_acquire_lock", lambda **kw: True)
    monkeypatch.setattr(mod, "RATE_LIMIT", 0)
    monkeypatch.setattr(mod, "date", type("Clock", (), {"today": staticmethod(lambda: date(2026, 11, 9))}))
    def denied(*a, **kw):
        raise AssertionError("测试禁止真实网络/通知")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(mod.urllib.request, "urlopen", denied)
    return db


def test_real_016989_null_and_missing_rows_are_repaired(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "广发富信优选六个月持有混合(FOF)A", "FOF-均衡型")])
    c = _conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,acc_nav) VALUES('20261102','016989',1.1404,1.1404)")
    # Nov3/4/5为NULL，Nov6完全缺行，二者都必须能补。
    c.executemany("INSERT INTO fund_daily_nav(date,fund_code) VALUES(?,'016989')", [("20261103",), ("20261104",), ("20261105",)])
    c.commit()
    c.close()
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    mod.collect()
    c = _conn(sandbox)
    actual = [tuple(r) for r in c.execute("SELECT date,unit_nav FROM fund_daily_nav WHERE fund_code='016989' ORDER BY date")]
    c.close()
    assert actual == [("20261102", 1.1404), ("20261103", 1.1298), ("20261104", 1.1631), ("20261105", 1.1713), ("20261106", 1.154)]


def test_more_than_500_empty_and_errors_reach_tail_after_process_restart(sandbox, monkeypatch):
    import os
    import subprocess
    import sys
    _seed_basic(sandbox, [(f"{i:06d}", "FOF", "FOF-均衡型") for i in range(1, 1002)])
    called = []
    def first(code, *a):
        called.append(code)
        if int(code) > 250:
            raise TimeoutError("隔离异常")
        return []
    monkeypatch.setattr(mod, "fetch_lsjz", first)
    assert mod.collect() == 0
    assert called == [f"{i:06d}" for i in range(1, 501)]
    assert mod.LAST_BATCH_FAILED is True  # F01混合空/异常零成功契约不变。
    # 新Python进程，不依赖父进程内变量，读取同一临时DB旁的持久进度。
    program = """
import json, sqlite3, sys, socket
from pathlib import Path
from scripts import collect_fof_nav as m
def denied(*a, **kw): raise AssertionError('禁止真实网络')
socket.socket.connect = denied
m.DB_PATH = Path(sys.argv[1])
m.get_conn = lambda: sqlite3.connect(sys.argv[1])
m.init_db = lambda: None
m._acquire_lock = lambda **kw: True
m.RATE_LIMIT = 0
called = []
m.fetch_lsjz = lambda code, *a: called.append(code) or []
m.collect()
print(json.dumps(called))
"""
    result = subprocess.run([sys.executable, "-c", program, str(sandbox)],
                            cwd=Path(__file__).absolute().parents[2],
                            env={**os.environ, "REPO": str(sandbox.parent)},
                            capture_output=True, text=True, timeout=15, check=True)
    tail = json.loads(result.stdout.splitlines()[-1])
    assert tail == [f"{i:06d}" for i in range(501, 1001)]
    called.clear()
    mod.collect()
    assert called[0] == "001001"
    assert len(called) == 500  # 绕回开头，但先触达最后一只。


def test_real_response_replay_is_idempotent_and_nonnull_is_never_overwritten(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "原名", "FOF-均衡型")])
    c = _conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav,acc_nav) VALUES('20261102','016989',9.9,8.8)")
    c.commit()
    c.close()
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    mod.collect()
    c = _conn(sandbox)
    before = [tuple(r) for r in c.execute("SELECT * FROM fund_daily_nav ORDER BY date")]
    c.close()
    mod.collect()
    c = _conn(sandbox)
    after = [tuple(r) for r in c.execute("SELECT * FROM fund_daily_nav ORDER BY date")]
    c.close()
    assert before == after
    assert after[0][3:5] == (9.9, 8.8)


def test_dry_run_no_database_or_progress_changes(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    cursor = sandbox.with_suffix(".fof-nav-progress.json")
    cursor.write_text('{"version":1,"last_code":"016989"}')
    cursor_before = cursor.read_bytes()
    c = _conn(sandbox)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    db_before = sandbox.read_bytes()
    def forbidden():
        raise AssertionError("dry_run不能用写连接/初始化")
    monkeypatch.setattr(mod, "get_conn", forbidden)
    monkeypatch.setattr(mod, "init_db", forbidden)
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    mod.collect(dry_run=True)
    assert sandbox.read_bytes() == db_before
    assert cursor.read_bytes() == cursor_before
    assert mod.LAST_BATCH_FAILED is False


@pytest.mark.parametrize("broken", ['{', '[]', '{"version":2,"last_code":"016989"}', '{"version":1,"last_code":null}'])
def test_corrupt_progress_recovers_by_rechecking(sandbox, monkeypatch, broken, capsys):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    sandbox.with_suffix(".fof-nav-progress.json").write_text(broken)
    called = []
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a: called.append(code) or [])
    mod.collect()
    assert called == ["016989"]
    assert "进度损坏" in capsys.readouterr().out


def test_atomic_progress_failure_preserves_old_position_and_replay(sandbox, monkeypatch):
    from scripts import util_atomic
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    cursor = sandbox.with_suffix(".fof-nav-progress.json")
    cursor.write_text('{"version":1,"last_code":"000001"}')
    before = cursor.read_bytes()
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    with monkeypatch.context() as patch:
        def failed(*a):
            raise OSError("模拟replace失败")
        patch.setattr(util_atomic.os, "replace", failed)
        with pytest.raises(OSError):
            mod.collect()
    assert cursor.read_bytes() == before
    assert not list(cursor.parent.glob("*.tmp"))
    # NAV已单只提交，进度未提交；重放只补空，不产生重复行。
    mod.collect()
    c = _conn(sandbox)
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav").fetchone()[0] == 5
    c.close()


def test_no_targets_and_lock_busy_reset_f01_without_progress(sandbox, monkeypatch):
    mod.LAST_BATCH_FAILED = True
    assert mod.collect() == 0
    assert mod.LAST_BATCH_FAILED is False
    assert not sandbox.with_suffix(".fof-nav-progress.json").exists()
    monkeypatch.setattr(mod, "_acquire_lock", lambda **kw: False)
    mod.LAST_BATCH_FAILED = True
    assert mod.collect() == 0
    assert mod.LAST_BATCH_FAILED is False


@pytest.mark.parametrize("kwargs", [{"batch": 999}, {"limit": 999}])
def test_500_hard_cap_including_debug_limit(sandbox, monkeypatch, kwargs):
    _seed_basic(sandbox, [(f"{i:06d}", "FOF", "FOF-均衡型") for i in range(1, 502)])
    called = []
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a: called.append(code) or [])
    mod.collect(**kwargs)
    assert len(called) == 500
    if "limit" in kwargs:
        assert not sandbox.with_suffix(".fof-nav-progress.json").exists()


@pytest.mark.parametrize("kwargs", [{"batch": 0}, {"batch": -1}, {"limit": 0}, {"limit": -1}, {"days": -1}])
def test_invalid_limits_are_rejected_before_io(sandbox, kwargs):
    with pytest.raises(ValueError):
        mod.collect(**kwargs)


def test_unpublished_api_rows_are_legal_empty(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    payload = {"ErrCode": 0, "Data": {"LSJZList": [{"FSRQ": "2026-11-06", "DWJZ": "--"}]}}
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(payload).encode()))
    assert mod.collect() == 0
    assert mod.LAST_BATCH_FAILED is False
    c = _conn(sandbox)
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav").fetchone()[0] == 0
    c.close()


@pytest.mark.parametrize("response,expected", [("empty", 0), ("error", 2), ("success", 0)])
def test_original_f01_main_exit_contract(sandbox, monkeypatch, response, expected):
    import sys
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    monkeypatch.setattr(sys, "argv", ["collect_fof_nav"])
    if response == "error":
        def failed(*a):
            raise TimeoutError("隔离网络异常")
        monkeypatch.setattr(mod, "fetch_lsjz", failed)
    elif response == "empty":
        monkeypatch.setattr(mod, "fetch_lsjz", lambda *a: [])
    else:
        monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    assert mod.main() == expected


def test_window_moves_and_removed_cursor_code_do_not_restart_head(sandbox, monkeypatch):
    _seed_basic(sandbox, [(f"{i:06d}", "FOF", "FOF-均衡型") for i in range(1, 5)])
    called = []
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a: called.append(code) or [])
    mod.collect(batch=2)
    c = _conn(sandbox)
    c.execute("DELETE FROM fund_basic WHERE fund_code='000002'")
    c.commit()
    c.close()
    monkeypatch.setattr(mod, "date", type("Clock", (), {"today": staticmethod(lambda: date(2026, 11, 10))}))
    called.clear()
    mod.collect(batch=2)
    assert called == ["000003", "000004"]



def test_dry_run_all_errors_does_not_set_f01_or_create_progress(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    def failed(*a):
        raise TimeoutError("隔离探测异常")
    monkeypatch.setattr(mod, "fetch_lsjz", failed)
    mod.LAST_BATCH_FAILED = True
    assert mod.collect(dry_run=True) == 0
    assert mod.LAST_BATCH_FAILED is False
    assert not sandbox.with_suffix(".fof-nav-progress.json").exists()
