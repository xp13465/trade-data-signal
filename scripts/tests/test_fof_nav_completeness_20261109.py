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
    def first(code, *a, **kw):
        called.append(code)
        if int(code) > 250:
            raise TimeoutError("隔离异常")
        return []
    monkeypatch.setattr(mod, "fetch_lsjz", first)
    assert mod.collect() == 0
    # 2026-11-13 方案 C 两遍: pass A 增量扫 500 只(1..250 空成功, 251..500 异常);
    # pass B 回补只跑未失败的 1..250(251..500 在 failed_funds 跳过)。
    assert called == [f"{i:06d}" for i in range(1, 501)] + [f"{i:06d}" for i in range(1, 251)]
    assert mod.LAST_BATCH_FAILED is True  # F01混合空/异常零成功契约不变。
    # 新Python进程，不依赖父进程内变量，读取同一临时DB旁的持久进度。
    program = """
import json, sqlite3, sys, socket
from pathlib import Path
def denied(*a, **kw): raise AssertionError('禁止真实网络')
socket.socket.connect = denied
# 裸子进程不加载父conftest；先复用CI唯一导入垫片，不加供应商依赖。
socket.getaddrinfo = lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
from scripts.tests._ci_stubs import install_missing_third_party_stubs
install_missing_third_party_stubs()
from scripts import collect_fof_nav as m
m.DB_PATH = Path(sys.argv[1])
m.get_conn = lambda: sqlite3.connect(sys.argv[1])
m.init_db = lambda: None
m._acquire_lock = lambda **kw: True
m.RATE_LIMIT = 0
called = []
m.fetch_lsjz = lambda code, *a, **kw: called.append(code) or []
m.collect()
print(json.dumps(called))
"""
    result = subprocess.run([sys.executable, "-c", program, str(sandbox)],
                            cwd=Path(__file__).absolute().parents[2],
                            env={"PATH": os.environ.get("PATH", ""),
                                 "REPO": str(sandbox.parent), "PYTHONNOUSERSITE": "1"},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    tail = json.loads(result.stdout.splitlines()[-1])
    # 方案 C 两遍: pass A 501..1000 增量扫 + pass B 同 500 只回补(全部成功, 无 failed 跳过)。
    assert tail == [f"{i:06d}" for i in range(501, 1001)] + [f"{i:06d}" for i in range(501, 1001)]
    called.clear()
    mod.collect()
    assert called[0] == "001001"
    assert len(dict.fromkeys(called)) == 500  # 绕回开头，但先触达最后一只。


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
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a, **kw: called.append(code) or [])
    mod.collect()
    # 方案 C 两遍: 进度损坏从头复查, pass A 增量扫 + pass B 回补各调一次(幂等, 无状态)。
    assert called == ["016989", "016989"]
    assert "进度损坏" in capsys.readouterr().out


def test_atomic_progress_failure_preserves_old_position_and_replay(sandbox, monkeypatch):
    from scripts import util_atomic
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    cursor = sandbox.with_suffix(".fof-nav-progress.json")
    cursor.write_text('{"version":1,"last_code":"000001"}')
    before = cursor.read_bytes()
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    with monkeypatch.context() as patch:
        def failed(*a, **kw):
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
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a, **kw: called.append(code) or [])
    mod.collect(**kwargs)
    # 方案 C: batch 轮转模式两遍(pass A 增量扫 500 + pass B 回补 500);
    # limit 显式窗口模式仍单遍(不读写轮转进度), 500 不变。
    assert len(called) == 1000 if "batch" in kwargs else 500
    if "limit" in kwargs:
        assert not sandbox.with_suffix(".fof-nav-progress.json").exists()


@pytest.mark.parametrize("kwargs", [{"batch": 0}, {"batch": -1}, {"limit": 0}, {"limit": -1}, {"days": -1}])
def test_invalid_limits_are_rejected_before_io(sandbox, kwargs):
    with pytest.raises(ValueError):
        mod.collect(**kwargs)


def test_unpublished_api_rows_are_legal_empty(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    payload = {"ErrCode": 0, "Data": {"LSJZList": [{"FSRQ": "2026-11-06", "DWJZ": "--"}]}, "TotalCount": 1, "PageIndex": 1, "PageSize": 20}
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
        def failed(*a, **kw):
            raise TimeoutError("隔离网络异常")
        monkeypatch.setattr(mod, "fetch_lsjz", failed)
    elif response == "empty":
        monkeypatch.setattr(mod, "fetch_lsjz", lambda *a, **kw: [])
    else:
        monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    assert mod.main() == expected


def test_window_moves_and_removed_cursor_code_do_not_restart_head(sandbox, monkeypatch):
    _seed_basic(sandbox, [(f"{i:06d}", "FOF", "FOF-均衡型") for i in range(1, 5)])
    called = []
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a, **kw: called.append(code) or [])
    mod.collect(batch=2)
    c = _conn(sandbox)
    c.execute("DELETE FROM fund_basic WHERE fund_code='000002'")
    c.commit()
    c.close()
    monkeypatch.setattr(mod, "date", type("Clock", (), {"today": staticmethod(lambda: date(2026, 11, 10))}))
    called.clear()
    mod.collect(batch=2)
    # 方案 C 两遍: pass A 增量扫 + pass B 回补, 本轮 2 只各调一次。
    assert called == ["000003", "000004", "000003", "000004"]



def test_dry_run_all_errors_does_not_set_f01_or_create_progress(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    def failed(*a, **kw):
        raise TimeoutError("隔离探测异常")
    monkeypatch.setattr(mod, "fetch_lsjz", failed)
    mod.LAST_BATCH_FAILED = True
    assert mod.collect(dry_run=True) == 0
    assert mod.LAST_BATCH_FAILED is False
    assert not sandbox.with_suffix(".fof-nav-progress.json").exists()



def test_targeted_cli_14_days_repairs_real_016989_without_global_progress(sandbox, monkeypatch):
    import sys
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型"), ("000001", "其他FOF", "FOF-稳健型")])
    c = _conn(sandbox)
    c.execute("INSERT INTO fund_daily_nav(date,fund_code,unit_nav) VALUES('20261102','016989',1.1404)")
    c.execute("INSERT INTO fund_daily_nav(date,fund_code) VALUES('20261103','016989')")
    c.commit()
    c.close()
    cursor = sandbox.with_suffix(".fof-nav-progress.json")
    cursor.write_text('{"version":1,"last_code":"000001"}')
    before = cursor.read_bytes()
    requests = []
    def reply(req, **kw):
        requests.append(req.full_url)
        return _FakeResp(json.dumps(REAL_016989).encode())
    monkeypatch.setattr(mod.urllib.request, "urlopen", reply)
    monkeypatch.setattr(sys, "argv", ["collect_fof_nav", "--fund-code", "016989", "--days", "14"])
    assert mod.main() == 0
    assert len(requests) == 1
    assert "fundCode=016989" in requests[0]
    assert "startDate=2026-10-26&endDate=2026-11-09" in requests[0]
    assert cursor.read_bytes() == before
    c = _conn(sandbox)
    assert [tuple(r) for r in c.execute("SELECT date,unit_nav FROM fund_daily_nav WHERE fund_code='016989' ORDER BY date")] == [
        ("20261102", 1.1404), ("20261103", 1.1298), ("20261104", 1.1631), ("20261105", 1.1713), ("20261106", 1.154)]
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav WHERE fund_code='000001'").fetchone()[0] == 0
    c.close()
    # 入口重放仍只补空，绝不把单次成功说成全窗完整。
    assert mod.main() == 0
    assert cursor.read_bytes() == before


@pytest.mark.parametrize("code", ["000001", "999999"])
def test_target_outside_fof_qdii_never_opens_writer(sandbox, monkeypatch, code):
    _seed_basic(sandbox, [("000001", "股票型", "股票型")])
    c = _conn(sandbox)
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    before = sandbox.read_bytes()
    def denied(*a, **kw):
        raise AssertionError("非目标不得写库或请求API")
    monkeypatch.setattr(mod, "get_conn", denied)
    monkeypatch.setattr(mod, "init_db", denied)
    monkeypatch.setattr(mod, "fetch_lsjz", denied)
    assert mod.collect(fund_code=code) == 0
    assert sandbox.read_bytes() == before
    assert not sandbox.with_suffix(".fof-nav-progress.json").exists()


@pytest.mark.parametrize("code", ["", "16989", "016989x", "０１６９８９", "' OR 1", "../db1"])
def test_invalid_target_rejected_before_any_io(sandbox, monkeypatch, code):
    def denied(*a, **kw):
        raise AssertionError("非法输入不得取锁/读写库/请求API")
    monkeypatch.setattr(mod, "_acquire_lock", denied)
    monkeypatch.setattr(mod, "get_conn", denied)
    monkeypatch.setattr(mod, "init_db", denied)
    monkeypatch.setattr(mod, "fetch_lsjz", denied)
    with pytest.raises(ValueError):
        mod.collect(fund_code=code)


def test_targeted_dry_run_stays_readonly_without_global_progress(sandbox, monkeypatch):
    _seed_basic(sandbox, [("016989", "FOF", "FOF-均衡型")])
    def denied(*a, **kw):
        raise AssertionError("dry_run不能写库或读写全局进度")
    monkeypatch.setattr(mod, "get_conn", denied)
    monkeypatch.setattr(mod, "init_db", denied)
    monkeypatch.setattr(mod, "atomic_write_json", denied)
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **kw: _FakeResp(json.dumps(REAL_016989).encode()))
    assert mod.collect(fund_code="016989", days=14, dry_run=True) == 5
    c = _conn(sandbox)
    assert c.execute("SELECT COUNT(*) FROM fund_daily_nav").fetchone()[0] == 0
    c.close()
    assert not sandbox.with_suffix(".fof-nav-progress.json").exists()


def test_targeted_qdii_uses_same_existing_universe(sandbox, monkeypatch):
    _seed_basic(sandbox, [("160125", "QDII", "QDII-普通股票")])
    called = []
    monkeypatch.setattr(mod, "fetch_lsjz", lambda code, *a, **kw: called.append(code) or [])
    assert mod.collect(fund_code="160125") == 0
    assert called == ["160125"]
    assert not sandbox.with_suffix(".fof-nav-progress.json").exists()



def test_invalid_target_cli_exits2_before_io(sandbox, monkeypatch):
    import sys
    def denied(*a, **kw):
        raise AssertionError("非法CLI不得触达锁/库/网络")
    monkeypatch.setattr(mod, "_acquire_lock", denied)
    monkeypatch.setattr(sys, "argv", ["collect_fof_nav", "--fund-code", "../bad"])
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 2
