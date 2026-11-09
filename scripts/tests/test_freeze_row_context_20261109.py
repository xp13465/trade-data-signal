"""FREEZE-P2-01: real get_conn Row -> compute -> save/alert/archive, isolated to /tmp."""
import ast
import contextlib
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import types

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/signal_kelly_backtest.py"
ROWS = [("20261103", "old", "buy"), ("20261104", "new", "buy")]
HASH_FIELDS = ("freeze_input_sha256", "map_input_sha256", "signal_input_sha256", "rating_input_sha256")


def module_from_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def producer_namespace():
    names = {"compute", "_signal_key", "_build_freeze_di_idx", "_freeze_fallback", "_resolve_etf",
             "_freeze_buy_keys", "_freeze_key_of", "_union_freeze_backfill_rows", "_load_etf_freeze",
             "_etf_freeze_path", "_save_etf_freeze", "_frozen_input_identity", "_frozen_missing_context",
             "_load_frozen_missing_accepted", "_archive_frozen_missing_diagnostics", "_alert_frozen_missing",
             "_classify_buy_rows"}
    ns = dict(__file__=str(SOURCE), datetime=datetime, json=json, os=os, sys=sys)
    nodes = []
    for n in ast.parse(SOURCE.read_text()).body:
        if isinstance(n, ast.Assign):
            try: value = ast.literal_eval(n.value)
            except (ValueError, TypeError): continue
            for target in n.targets:
                if isinstance(target, ast.Name): ns[target.id] = value
        elif isinstance(n, ast.ClassDef) and n.name == "_FreezePersistenceError":
            nodes.append(n)
        elif isinstance(n, ast.FunctionDef) and n.name in names:
            n.decorator_list = []  # remove instrumentation only; execute complete business bodies
            nodes.append(n)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


@pytest.fixture
def run_case(monkeypatch):
    def forbidden(*a, **kw): raise AssertionError("real transport forbidden")
    for owner, attr in ((socket.socket, "connect"), (socket, "getaddrinfo"),
                        (subprocess, "run"), (subprocess, "Popen")):
        monkeypatch.setattr(owner, attr, forbidden)
    with pytest.raises(AssertionError, match="transport forbidden"):
        subprocess.run(["must-not-run"])
    temps = contextlib.ExitStack()
    def run(row_kind="row", fail_save=False, fail_hash=None):
        temp = Path(temps.enter_context(tempfile.TemporaryDirectory(prefix="freeze-p2-", dir="/tmp")))
        db = module_from_file("isolated_p2_real_db", ROOT / "app/db.py")
        db.DB_PATH = temp / "sentiment.db"
        conn = db.get_conn()
        try:
            assert conn.row_factory is sqlite3.Row
            conn.executemany("INSERT INTO signal_daily(date,index_id,signal) VALUES(?,?,?)", ROWS)
            conn.commit()
        finally: conn.close()
        ns = producer_namespace()
        atom = module_from_file("isolated_p2_atomic", ROOT / "scripts/util_atomic.py")
        freeze_path = temp / "freeze.json"
        freeze_path.write_text("{}")
        best = {iid: dict(code="510300", name="fixture ETF", track_tier="strong") for _,iid,_ in ROWS}
        seen = {}
        def connect():
            c = db.get_conn()  # real schema/path/migration and Row factory
            if row_kind == "tuple": c.row_factory = None
            return c
        def capture_rows(conn, name, rows, **kw):
            if name == "signal_daily": seen["sql_rows"] = rows
        real_union = ns["_union_freeze_backfill_rows"]
        def union(rows, freeze, keys, present):
            result = real_union(rows, freeze, keys, present)
            seen["unchanged_union_object"] = result is rows
            return result
        def capture_write(fn, path, *a, **kw):
            if fail_save and Path(path).resolve() == freeze_path.resolve(): raise PermissionError("injected save failure")
            return fn(path, *a, **kw)
        ns.update(ROOT=str(temp), get_conn=connect, atomic_write_json=atom.atomic_write_json,
            ETF_FREEZE_PATH_ENV="SIGNAL_KELLY_ETF_FREEZE_PATH",
            FROZEN_MISSING_ACCEPTED_PATH=str(temp / "accepted.json"),
            _load_signal_stats=lambda:{}, _load_board_etf_map=lambda:{}, _build_best_etf=lambda m:best,
            _load_market_map=lambda:{}, _load_market_state=lambda c:({},[]), _load_market_tiers=lambda c,**kw:{},
            _detect_freeze_orphan_buy_events=lambda *a:[], _load_freeze_backfill_registry=lambda:set(),
            _split_registered_orphans=lambda *a:([],0), _alert_freeze_orphans=lambda *a,**kw:None,
            _union_freeze_backfill_rows=union, _iid_in_excluded_category=lambda iid:False,
            _etf_daily_today_ready=lambda:(True,"20261104",1), _batch_load_etf_prices=lambda codes:({},{},{},{}),
            capture_loaded=lambda *a,**kw:None, capture_sql_rows=capture_rows,
            capture_event=lambda *a,**kw:None, capture_write=capture_write,
            _KELLY_FEE_CONFIG={}, KELLY_ASOF="", KELLY_BUY_NEXTDAY=1,
            _FROZEN_MISSING_EVENTS=set(), _PRUNED_UNIVERSE_N=0,
            _build_outputs=lambda q:({"fixture_aggregate":True},{}))
        original_hash = ns["_frozen_input_identity"]
        if fail_hash:
            def injected_hash(value):
                if fail_hash == "all" or value is best: raise TypeError("injected diagnostic hash failure")
                return original_hash(value)
            ns["_frozen_input_identity"] = injected_hash
        calls=[]
        fake = types.ModuleType("app.notify_hook")
        fake.send_alert=lambda *a,**kw:calls.append((a,kw)) or types.SimpleNamespace(rc=0,route="isolated")
        with monkeypatch.context() as m, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            m.setitem(sys.modules,"app.notify_hook",fake)
            m.setenv(ns["ETF_FREEZE_PATH_ENV"],str(freeze_path)); m.setenv(ns["FREEZE_UNION_ENV"],"0")
            returned=ns["compute"]()
        paths=list((temp/"data/audit/frozen_missing").glob("*.json"))
        assert len(paths)==1
        result=dict(payload=json.loads(paths[0].read_text()), saved=json.loads(freeze_path.read_text()),
                    stderr=err.getvalue(), calls=calls, returned=returned, seen=seen)
        assert seen["unchanged_union_object"]
        assert type(seen["sql_rows"][0]) is (sqlite3.Row if row_kind=="row" else tuple)
        assert [tuple(r) for r in seen["sql_rows"]] == ROWS
        assert result["payload"]["filtered_missing"] == ["20261103|old|buy"]
        assert len(calls)==1
        assert calls[0][1] == dict(dedup_key="signal_kelly_frozen_missing",dedup_window=3600,
            severe=False,from_prefix="[kelly]",feishu_group="alert",defer_digest=True,digest_category="kelly_frozen_missing")
        assert set(result["saved"]) == (set() if fail_save else {"20261104|new|buy"})
        assert result["returned"] == ({"fixture_aggregate":True},{})
        return result
    yield run
    temps.close()


def assert_context(result, fail_save=False, failed_hashes=()):
    p=result["payload"]
    assert p["latest_signal_date"] == "20261104"
    assert p["freeze_persistence"] == ({"status":"failed","error_type":"PermissionError"} if fail_save
                                         else {"status":"saved","count":1})
    assert p["input_counts"] == dict(freeze=0,map=2,signal=2,rating=0)
    for key in HASH_FIELDS:
        value=p["hashes"][key]
        assert value == "unknown" if key in failed_hashes else len(value)==64 and int(value,16)>=0
    if "signal_input_sha256" not in failed_hashes:
        expected=hashlib.sha256(json.dumps(ROWS,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        assert p["hashes"]["signal_input_sha256"] == expected


@pytest.mark.parametrize("fail_save",[False,True])
def test_real_row_compute_save_alert_archive_preserves_context(run_case,fail_save):
    result=run_case(fail_save=fail_save)
    assert_context(result,fail_save)
    assert "冻结输入取证失败" not in result["stderr"]


@pytest.mark.parametrize("fail_save",[False,True])
def test_tuple_control_has_same_canonical_values(run_case,fail_save):
    result=run_case(row_kind="tuple",fail_save=fail_save)
    assert_context(result,fail_save)


@pytest.mark.parametrize("fail_save",[False,True])
@pytest.mark.parametrize("failure",["map","all"])
def test_hash_failure_preserves_independent_latest_and_save_result(run_case,fail_save,failure):
    result=run_case(fail_save=fail_save,fail_hash=failure)
    assert_context(result,fail_save,HASH_FIELDS if failure=="all" else ("map_input_sha256",))
    assert "TypeError" in result["stderr"]
