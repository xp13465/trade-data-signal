"""Real freeze functions/processes and compute->CLI writes, only private /tmp files."""
import argparse
import ast
import contextlib
from datetime import datetime
import errno
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/signal_kelly_backtest.py"
OLD = "20261106|existing|buy"
A = "20261109|csi_000102|buy"
B = "20261109|csi_000330|buy_aux"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def namespace(root):
    names = {"_etf_freeze_path", "_load_etf_freeze", "_save_etf_freeze", "_signal_key",
             "_build_freeze_di_idx", "_freeze_fallback", "_resolve_etf", "compute", "main",
             "_frozen_input_identity", "_frozen_missing_context", "_classify_buy_rows"}
    evidence = module("isolated_persist_evidence", ROOT / "scripts/delivery_evidence.py")
    atomic = module("isolated_persist_atomic", ROOT / "scripts/util_atomic.py")
    ns = dict(__file__=str(SOURCE), ROOT=str(root), os=os, json=json, sys=sys,
              datetime=datetime, argparse=argparse, atomic_write_json=atomic.atomic_write_json,
              atomic_write_text=atomic.atomic_write_text,
              _iid_in_excluded_category=lambda iid: False)
    for name in ("capture_loaded", "capture_write", "capture_event", "capture_sql_rows", "evidence_stage"):
        ns[name] = getattr(evidence, name)
    nodes = []
    for node in ast.parse(SOURCE.read_text()).body:
        if isinstance(node, ast.Assign):
            try: value = ast.literal_eval(node.value)
            except (ValueError, TypeError): continue
            for target in node.targets:
                if isinstance(target, ast.Name): ns[target.id] = value
        elif isinstance(node, ast.ClassDef) and node.name == "_FreezePersistenceError":
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            if node.name != "_save_etf_freeze": node.decorator_list = []
            nodes.append(node)
    ns["ROOT"] = str(root)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns, atomic


@pytest.fixture
def sandbox(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="freeze-persist-", dir="/tmp") as td:
        root = Path(td).resolve()
        (root / "data").mkdir()
        monkeypatch.delenv("SIGNAL_KELLY_ETF_FREEZE_PATH", raising=False)
        monkeypatch.setenv("OPS_DELIVERY_EVIDENCE_ENABLED", "0")
        yield root


def entry(code="510300", **kw):
    return dict(code=code, name="fixture", track_tier="strong", track_score=80,
                frozen_at="2026-11-09 16:00", **kw)


def freeze_file(root):
    return root / "data/signal_kelly_etf_freeze.json"


def write(root, data):
    freeze_file(root).write_text(json.dumps(data))


def wait_file(path, proc=None):
    until = time.monotonic() + 8
    while not path.exists():
        if proc is not None and proc.poll() is not None:
            raise AssertionError(proc.communicate())
        if time.monotonic() >= until: raise TimeoutError(str(path))
        time.sleep(.01)


def publish_fixture_state(path, state):
    # Existence is the ready signal consumed by the parent. Do not expose an
    # empty/truncated JSON file between open() and write() under CPU contention.
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(sorted(state)))
    tmp.replace(path)


def worker(root, actor, mode="distinct"):
    assert str(root).startswith(("/tmp/", "/private/tmp/"))
    signal.alarm(12)
    def forbidden(*a, **kw): raise AssertionError("worker egress/process forbidden")
    socket.socket.connect = socket.getaddrinfo = forbidden
    subprocess.run = subprocess.Popen = forbidden
    ns, _ = namespace(root)
    state = ns["_load_etf_freeze"]()
    publish_fixture_state(root / (actor + '.loaded'), state)
    key = A if actor == "A" or mode != "distinct" else B
    date, iid, sig = key.split("|")
    choice = entry("same" if mode == "same" else actor)
    choice["name"] = actor
    ns["_resolve_etf"](date, iid, sig, {iid: choice}, state, "20261109")
    wait_file(root / (actor + ".go"))
    ns["_save_etf_freeze"](state)
    publish_fixture_state(root / (actor + '.saved'), state)


@pytest.mark.parametrize("order", [("A", "B"), ("B", "A")])
@pytest.mark.parametrize("evidence", ["0", "1"])
def test_real_process_stale_snapshots_keep_both_orders(sandbox, order, evidence):
    write(sandbox, {OLD: entry()})
    procs = {}
    try:
        for actor in order:
            env = dict(os.environ, OPS_DELIVERY_EVIDENCE_ENABLED=evidence,
                       PYTHONDONTWRITEBYTECODE="1")
            procs[actor] = subprocess.Popen([sys.executable, "-B", __file__, "worker", str(sandbox), actor],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            wait_file(sandbox / (actor + ".loaded"), procs[actor])
            assert json.loads((sandbox / (actor + ".loaded")).read_text()) == [OLD]
        for actor in order:
            (sandbox / (actor + ".go")).touch()
            stdout, stderr = procs[actor].communicate(timeout=10)
            assert procs[actor].returncode == 0, (stdout, stderr)
        assert set(json.loads(freeze_file(sandbox).read_text())) == {OLD, A, B}
        ns, _ = namespace(sandbox)
        assert ns["_resolve_etf"]("20261109", "csi_000102", "buy", {},
                                 ns["_load_etf_freeze"](), "20261110")[0]["code"] == "A"
    finally:
        for proc in procs.values():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate(timeout=3)


def test_stable_sidecar_inode_blocks_other_process_and_releases(sandbox):
    ns, _ = namespace(sandbox)
    ns["_save_etf_freeze"]({OLD: entry()})  # missing-file initialization
    lock = Path(str(freeze_file(sandbox)) + ".lock")
    assert lock.exists()
    inode = lock.stat().st_ino
    proc = None
    try:
        with lock.open("a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            proc = subprocess.Popen([sys.executable, "-B", __file__, "worker", str(sandbox), "A"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            wait_file(sandbox / "A.loaded", proc)
            (sandbox / "A.go").touch()
            # Wait for the worker to reach save, while holding the actual stable inode.
            time.sleep(.15)
            assert proc.poll() is None and not (sandbox / "A.saved").exists()
        stdout, stderr = proc.communicate(timeout=10)
        assert proc.returncode == 0, (stdout, stderr)
        for _ in range(3): ns["_save_etf_freeze"]({B: entry()})
        assert lock.stat().st_ino == inode
        assert set(json.loads(freeze_file(sandbox).read_text())) == {OLD, A, B}
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL); proc.communicate(timeout=3)


def test_same_code_prefers_complete_old_metadata_and_reentry(sandbox):
    old = entry(); old.update(track_tier="related", track_score=66, name="old", frozen_at="2026-11-06 16:00")
    write(sandbox, {A: old})
    ns, _ = namespace(sandbox)
    current = {A: entry()}
    for _ in range(2): ns["_save_etf_freeze"](current)
    assert current[A] == old == json.loads(freeze_file(sandbox).read_text())[A]


@pytest.mark.parametrize("mode", ["same", "conflict"])
def test_real_process_same_key_immutable_choice(sandbox, mode):
    write(sandbox, {})
    procs = []
    try:
        for actor in ("A", "B"):
            proc = subprocess.Popen([sys.executable, "-B", __file__, "worker", str(sandbox), actor, mode],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            procs.append(proc); wait_file(sandbox / (actor + ".loaded"), proc)
        (sandbox / "A.go").touch()
        stdout, stderr = procs[0].communicate(timeout=10)
        assert procs[0].returncode == 0, (stdout, stderr)
        first = freeze_file(sandbox).read_bytes()
        (sandbox / "B.go").touch()
        stdout, stderr = procs[1].communicate(timeout=10)
        assert (procs[1].returncode == 0) == (mode == "same"), (stdout, stderr)
        assert freeze_file(sandbox).read_bytes() == first
        if mode == "conflict": assert "冲突" in stderr.decode()
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL); proc.communicate(timeout=3)


def test_recursive_save_fails_without_deadlock_and_releases(sandbox):
    write(sandbox, {OLD: entry()}); original = freeze_file(sandbox).read_bytes()
    ns, _ = namespace(sandbox); capture = ns["capture_write"]
    ns["capture_write"] = lambda fn, path, obj, **kw: ns["_save_etf_freeze"](obj)
    with pytest.raises(RuntimeError, match="递归"): ns["_save_etf_freeze"]({A: entry()})
    assert freeze_file(sandbox).read_bytes() == original
    ns["capture_write"] = capture
    ns["_save_etf_freeze"]({A: entry()})
    assert set(json.loads(freeze_file(sandbox).read_text())) == {OLD, A}


def test_canonical_path_alias_uses_same_lock_and_file(sandbox, monkeypatch):
    write(sandbox, {OLD: entry()})
    alias = sandbox / "alias.json"; alias.symlink_to(freeze_file(sandbox))
    ns, _ = namespace(sandbox)
    monkeypatch.setenv("SIGNAL_KELLY_ETF_FREEZE_PATH", str(alias))
    ns["_save_etf_freeze"]({A: entry()})
    inode = Path(str(freeze_file(sandbox)) + ".lock").stat().st_ino
    monkeypatch.delenv("SIGNAL_KELLY_ETF_FREEZE_PATH")
    ns["_save_etf_freeze"]({B: entry()})
    assert alias.is_symlink()
    assert Path(str(freeze_file(sandbox)) + ".lock").stat().st_ino == inode
    assert set(json.loads(freeze_file(sandbox).read_text())) == {OLD, A, B}


def test_true_choice_conflict_never_overwrites(sandbox):
    write(sandbox, {A: entry("old")})
    before = freeze_file(sandbox).read_bytes()
    ns, _ = namespace(sandbox)
    with pytest.raises(RuntimeError, match="冲突"):
        ns["_save_etf_freeze"]({A: entry("new"), B: entry()})
    assert freeze_file(sandbox).read_bytes() == before


@pytest.mark.parametrize("bad", ["{broken", "[]", "null", '{"x":null}'])
def test_latest_bad_json_cannot_become_empty_overwrite(sandbox, bad):
    freeze_file(sandbox).write_text(bad)
    ns, _ = namespace(sandbox)
    with pytest.raises(RuntimeError): ns["_save_etf_freeze"]({A: entry()})
    assert freeze_file(sandbox).read_text() == bad


def test_latest_read_failure_keeps_original(sandbox, monkeypatch):
    import builtins
    write(sandbox, {OLD: entry()}); original = freeze_file(sandbox).read_bytes()
    ns, _ = namespace(sandbox)
    real_open = builtins.open
    def denied(path, *a, **kw):
        if str(path) == str(freeze_file(sandbox)):
            raise PermissionError("injected latest read denied")
        return real_open(path, *a, **kw)
    with monkeypatch.context() as m:
        m.setattr(builtins, "open", denied)
        with pytest.raises(RuntimeError, match="读取"): ns["_save_etf_freeze"]({A: entry()})
    assert freeze_file(sandbox).read_bytes() == original


def test_enospc_keeps_original_releases_lock_and_can_retry(sandbox, monkeypatch):
    write(sandbox, {OLD: entry()}); original = freeze_file(sandbox).read_bytes()
    ns, atomic = namespace(sandbox)
    real_replace = atomic.os.replace
    def full(src, dst):
        if str(dst) == str(freeze_file(sandbox)): raise OSError(errno.ENOSPC, "injected full")
        return real_replace(src, dst)
    with monkeypatch.context() as m:
        m.setattr(atomic.os, "replace", full)
        with pytest.raises(OSError) as exc: ns["_save_etf_freeze"]({A: entry()})
        assert exc.value.errno == errno.ENOSPC
    assert freeze_file(sandbox).read_bytes() == original
    assert not list((sandbox / "data").glob("*.tmp*"))
    ns["_save_etf_freeze"]({A: entry()})
    assert set(json.loads(freeze_file(sandbox).read_text())) == {OLD, A}


def test_historical_missing_still_rejected(sandbox):
    ns, _ = namespace(sandbox); state = {}
    assert ns["_resolve_etf"]("20261106", "idx", "buy", {"idx": entry()}, state,
                              "20261109") == (None, False)
    assert not state and ns["_FROZEN_MISSING_EVENTS"] == {("20261106", "idx", "buy")}


def cli_case(root, monkeypatch, canonical, fail_write=False):
    """Real get_conn/compute/classify/main/file writes; finite loader/backtest/aggregate seams."""
    ns, atomic = namespace(root)
    db = module("isolated_persist_db", ROOT / "app/db.py"); db.DB_PATH = root / "sentiment.db"
    conn = db.get_conn()
    conn.execute("INSERT INTO signal_daily(date,index_id,signal) VALUES('20261109','csi_000102','buy')")
    conn.commit(); conn.close()
    write(root, {})
    before = ns["_frozen_missing_context"]
    def concurrent(*a):
        result = before(*a)
        freeze_file(root).write_text(canonical if isinstance(canonical, str) else json.dumps({A: canonical}))
        return result
    seen = dict(price_calls=0)
    def prices(codes):
        seen["price_calls"] += 1; seen["price_codes"] = codes
        return ({c:{"20261109":1} for c in codes}, {}, {}, {c:["20261109"] for c in codes})
    def backtest(*a, **kw):
        return dict(etf_code=a[3], etf_name=a[4], track_tier=a[8], track_score=a[9])
    ns.update(get_conn=db.get_conn, _load_signal_stats=lambda:{"csi_000102":{"buy":{"10d":{"score":.4}}}},
        _load_board_etf_map=lambda:{}, _build_best_etf=lambda m:{"csi_000102":entry()},
        _load_market_map=lambda:{}, _load_market_state=lambda c:({},[]), _load_market_tiers=lambda *a,**k:{},
        _detect_freeze_orphan_buy_events=lambda *a:[], _load_freeze_backfill_registry=lambda:set(),
        _split_registered_orphans=lambda *a:([],0), _alert_freeze_orphans=lambda *a,**k:None,
        _union_freeze_backfill_rows=lambda rows,*a:rows,
        _etf_daily_today_ready=lambda:(True,"20261109",1), _batch_load_etf_prices=prices,
        _market_tier_at=lambda *a:"", _backtest_one=backtest,
        _frozen_missing_context=concurrent, _KELLY_FEE_CONFIG={}, KELLY_ASOF="", KELLY_UNIQUE_EXPORT=0,
        KELLY_BUY_NEXTDAY=1,
        _build_outputs=lambda q:({"quadrants":q},{"quadrants":q}))
    output, trades = root / "stats.json", root / "trades.json"
    output.write_text("existing stats"); trades.write_text("existing trades")
    err = io.StringIO()
    if fail_write:
        real_replace = atomic.os.replace
        def full(src, dst):
            if str(dst) == str(freeze_file(root)): raise OSError(errno.ENOSPC, "injected full")
            return real_replace(src, dst)
        monkeypatch.setattr(atomic.os, "replace", full)
    monkeypatch.setenv(ns["FREEZE_UNION_ENV"], "0")
    monkeypatch.setattr(sys, "argv", ["isolated", "--output", str(output), "--trades-output", str(trades), "--skip-parts"])
    def forbidden(*a, **kw): raise AssertionError("real transport forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    def run():
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err): ns["main"]()
    return run, ns, seen, err, output, trades


@pytest.mark.parametrize("canonical", [entry("other"), "{broken", "[]"])
def test_real_compute_cli_failure_preserves_outputs(sandbox, monkeypatch, canonical):
    run, ns, seen, err, output, trades = cli_case(sandbox, monkeypatch, canonical)
    with pytest.raises(SystemExit) as exc: run()
    assert exc.value.code != 0
    assert output.read_text() == "existing stats" and trades.read_text() == "existing trades"
    assert not output.with_suffix(".json.gz").exists()
    assert seen["price_calls"] == 0 and "FAIL" in err.getvalue()
    if isinstance(canonical, dict): assert json.loads(freeze_file(sandbox).read_text()) == {A: canonical}
    else: assert freeze_file(sandbox).read_text() == canonical


def test_cli_cannot_open_lock_never_outputs_unknown_choice(sandbox, monkeypatch):
    import builtins
    run, ns, seen, err, output, trades = cli_case(sandbox, monkeypatch, entry("other"))
    real_open = builtins.open
    def denied(path, *a, **kw):
        if str(path).endswith(".lock"): raise PermissionError("injected lock permission")
        return real_open(path, *a, **kw)
    monkeypatch.setattr(builtins, "open", denied)
    with pytest.raises(SystemExit) as exc: run()
    assert exc.value.code != 0 and "冻结锁" in err.getvalue()
    assert output.read_text() == "existing stats" and trades.read_text() == "existing trades"


@pytest.mark.parametrize("fail_write", [False, True])
@pytest.mark.parametrize("nextday", [0, 1])
def test_real_compute_cli_uses_old_canonical_metadata(sandbox, monkeypatch, fail_write, nextday):
    old = entry(); old.update(name="old frozen", track_tier="related", track_score=66)
    run, ns, seen, err, output, trades = cli_case(sandbox, monkeypatch, old, fail_write)
    ns["KELLY_BUY_NEXTDAY"] = nextday
    run()
    result = json.loads(trades.read_text())["quadrants"]
    assert result["etf_related"]["A"][0] == dict(etf_code="510300", etf_name="old frozen", track_tier="related", track_score=66)
    assert not result["etf_strong"]["A"]
    assert seen["price_codes"] == {"510300"}
    assert json.loads(freeze_file(sandbox).read_text())[A] == old
    assert ("写盘失败" in err.getvalue()) == fail_write
    assert output.exists() and trades.with_suffix(".json.gz").exists()


if __name__ == "__main__" and sys.argv[1] == "worker":
    worker(Path(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "distinct")
