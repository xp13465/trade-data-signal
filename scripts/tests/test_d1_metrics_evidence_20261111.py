"""HC09: fake-only calls; isolated REPO, no credentials or real network."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts/lib/d1_execute.sh"
HELPER = ROOT / "scripts/d1_metrics_evidence.py"


def fake_env(tmp_path, body):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "npx"
    fake.write_text("#!/bin/bash\nprintf x >> \"$CALL_LOG\"\n" + body)
    fake.chmod(0o755)
    env = {"PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "REPO": str(tmp_path), "GIT_REPO": str(tmp_path), "PY": sys.executable,
           "D1_METRICS_DIR": str(tmp_path / "evidence"), "D1_METRICS_RUN_ID": "a" * 32,
           "D1_METRICS_CODE_REF": "b" * 40, "D1_METRICS_TABLES": "fund_score,sync_meta",
           "D1_RETRY_DELAYS": "0 0", "CALL_LOG": str(tmp_path / "calls")}
    return env


def run_shell(tmp_path, env, code):
    return subprocess.run(["bash", "-c", "source " + shlex.quote(str(LIB)) + "\n" + code],
                          cwd=tmp_path, env=env, text=True, capture_output=True, timeout=20)


def calls(tmp_path):
    files = list((tmp_path / "evidence").glob("*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text())["calls"]


def test_meta_survives_import_output_overwrite(tmp_path):
    env = fake_env(tmp_path, """n=$(wc -c < "$CALL_LOG")
if [ "$n" -eq 1 ]; then
  echo '[{"success":false,"meta":{"rows_read":9,"rows_written":2,"duration":1.5}}]'
  echo 'fetch failed' >&2
  exit 7
fi
echo '[{"success":true,"meta":{"rows_read":12,"rows_written":3,"duration":2.5}}]'
""")
    r = run_shell(tmp_path, env, 'd1_execute_sql_file testdb unused.sql "$REPO/out"')
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "calls").read_text() == "xx"
    history = calls(tmp_path)
    assert [c["attempt"] for c in history] == [1, 2]
    assert [c["exit_code"] for c in history] == [7, 0]
    assert [c["results"][0]["rows_written"] for c in history] == [2, 3]


@pytest.fixture
def m(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("d1_evidence_under_test", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result(read=4, written=0, success=True):
    # Official D1Result shape: https://developers.cloudflare.com/d1/worker-api/return-object/
    return {"success": success, "meta": {"rows_read": read, "rows_written": written,
            "duration": 0.2552, "total_attempts": 2}, "results": [{"secret": "DO_NOT_STORE"}]}


@pytest.mark.parametrize("shape", ["array", "object", "envelope", "logs", "stderr"])
def test_documented_result_shapes(m, shape):
    obj = result()
    raw = json.dumps([obj] if shape in {"array", "logs", "stderr"} else
                     {"success": True, "result": [obj]} if shape == "envelope" else obj)
    if shape == "logs":
        raw = "wrangler v4\n[WARNING] before\n" + raw + "\nlog suffix"
    rows = m.parse_results("" if shape == "stderr" else raw, raw if shape == "stderr" else "", "statement")
    assert len(rows) == 1
    assert rows[0]["rows_read"] == 4
    assert rows[0]["rows_written"] == 0
    assert rows[0]["total_attempts"] == 2
    assert "DO_NOT_STORE" not in json.dumps(rows)
    assert rows[0]["query_id"] is None


def test_wrangler_import_bundle_not_display_row_or_table_totals(m):
    # workers-sdk execute.ts blob 371376c74158813d9e53335bea81a65a5f85980b
    obj = result(60310, 36152)
    obj.update(finalBookmark="DO_NOT_STORE", results=[{"Total queries executed": 73,
               "Rows read": 60310, "Rows written": 36152, "Database size (MB)": "1.23"}])
    rows = m.parse_results(json.dumps([obj]), "", "bundle")
    assert len(rows) == 1 and rows[0]["scope"] == "bundle"
    assert (rows[0]["query_count"], rows[0]["rows_read"], rows[0]["rows_written"]) == (73, 60310, 36152)
    assert "DO_NOT_STORE" not in json.dumps(rows)


def test_multi_statement_partial_failure_and_identical_statements(m):
    obj = [result(), result(), {"success": False, "error": "SQL_AND_CREDENTIAL_DO_NOT_STORE"}]
    rows = m.parse_results(json.dumps(obj), "", "statement")
    assert len(rows) == 3
    assert [r["result_index"] for r in rows] == [0, 1, 2]
    assert [r["status"] for r in rows] == ["success", "success", "failed"]
    assert rows[2]["rows_written"] is None
    assert "SQL_AND_CREDENTIAL_DO_NOT_STORE" not in json.dumps(rows)


@pytest.mark.parametrize("raw", ["fetch failed", "", '[{"results":[]}]',
                                    '[{"meta":{"rows_read":100},"results":['])
def test_missing_and_truncated_meta_never_zero(m, raw):
    rows = m.parse_results(raw, "", "statement")
    assert rows[0]["rows_read"] is None
    assert rows[0]["rows_written"] is None
    assert rows[0]["missing_reasons"]["rows_read"]


@pytest.mark.parametrize("bad", [True, -1, "123", float("nan"), float("inf"), 1.5])
def test_invalid_counts(m, bad):
    row = m.parse_results(json.dumps([result(bad)]), "", "statement")[0]
    assert row["rows_read"] is None
    assert row["missing_reasons"]["rows_read"] == "invalid_number"


def test_snapshots_no_double_sum_and_mirrors_dedup(m):
    a, b = json.dumps(result(3)), json.dumps(result(6))
    rows = m.parse_results(a + "\n" + b, b, "bundle")
    assert len(rows) == 2
    assert [r["rows_read"] for r in rows] == [3, 6]
    assert {r["aggregation"] for r in rows} == {"ambiguous_snapshots_do_not_sum"}
    rows = m.parse_results(a + '\n{"success":false}', "", "statement")
    assert len(rows) == 2 and rows[0]["rows_read"] == 3 and rows[1]["status"] == "failed"


def test_query_id_returned_only(m):
    obj = result()
    obj["meta"]["query_id"] = "d961ec66-4648-4ba3-b7dd-455127812d75"
    assert m.parse_results(json.dumps(obj), "", "statement")[0]["query_id"] == obj["meta"]["query_id"]
    obj["meta"]["query_id"] = "Bearer DO_NOT_STORE"
    assert "DO_NOT_STORE" not in json.dumps(m.parse_results(json.dumps(obj), "", "statement"))


def test_hash_migration_count_routes_and_output(tmp_path):
    raw = json.dumps([{**result(), "results": [{"fund_code": "F1", "row_hash": "h1", "n": 1}]}])
    env = fake_env(tmp_path, "printf '%s\\n' " + shlex.quote(raw) + "\nprintf 'stderr-original\\n' >&2\n")
    code = 'source ' + shlex.quote(str(ROOT / "scripts/lib/d1_hash_read.sh")) + """
exec 9>&2
export D1_METRICS_WARN_FD=9
 d1_migrate_row_hash testdb fund_score
 d1_read_hashes testdb fund_score "$REPO/hashes.json"
 d1_observed_command count_verify SELECT fund_score _d1_run_with_timeout 3 npx wrangler
"""
    r = run_shell(tmp_path, env, code)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "hashes.json").read_text()) == {"F1": "h1"}
    assert r.stdout == raw + "\n"
    history = calls(tmp_path)
    assert [c["stage"] for c in history] == ["migration", "hash_prefetch", "count_verify"]
    assert all(c["table_labels"] == ["fund_score"] for c in history)
    assert len({c["call_id"] for c in history}) == 3
    assert (tmp_path / "calls").read_text() == "xxx"


@pytest.mark.parametrize("rc", [0, 7])
def test_persistence_failure_preserves_rc_and_no_extra_retry(tmp_path, rc):
    env = fake_env(tmp_path, "echo 'syntax error' >&2\nprintf 'original-output\\n'\nexit " + str(rc))
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("unchanged")
    env["D1_METRICS_DIR"] = str(blocked)
    r = run_shell(tmp_path, env, 'exec 9>&2; export D1_METRICS_WARN_FD=9\nd1_execute_sql_file db unused "$REPO/out"')
    assert r.returncode == rc
    assert (tmp_path / "calls").read_text() == "x"
    assert "evidence incomplete" in r.stderr
    assert "original-output" in (tmp_path / "out").read_text()
    assert blocked.read_text() == "unchanged"


def test_stderr_only_and_timeout(tmp_path):
    raw = json.dumps([result(7)])
    env = fake_env(tmp_path, "printf '%s' " + shlex.quote(raw) + " >&2\nsleep 4\n")
    r = run_shell(tmp_path, env, 'd1_observed_command count_verify SELECT fund_score _d1_run_with_timeout 2 npx')
    assert r.returncode == 124
    assert r.stdout == "" and r.stderr == raw
    assert calls(tmp_path)[0]["results"][0]["rows_read"] == 7
    assert calls(tmp_path)[0]["exit_code"] == 124


def event(run="a" * 32, call="c" * 32):
    return {"run_id": run, "call_id": call, "attempt": 1, "results": []}


def test_atomic_private_dedup_retention_and_limits(m, tmp_path, monkeypatch):
    root = tmp_path / "evidence"
    e = event()
    m.persist(root, e); m.persist(root, e)
    path = root / (e["run_id"] + ".json")
    assert len(json.loads(path.read_text())["calls"]) == 1
    assert root.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setattr(m, "MAX_CALLS", 1)
    with pytest.raises(ValueError):
        m.persist(root, event(call="d" * 32))
    monkeypatch.setattr(m, "MAX_CALLS", 4096)
    monkeypatch.setattr(m, "MAX_RUNS", 2)
    m.persist(root, event(run="b" * 32)); m.persist(root, event(run="c" * 32))
    assert len(list(root.glob("*.json"))) == 2
    old = root / ("b" * 32 + ".json")
    os.utime(old, (0, 0))
    m.persist(root, event(run="d" * 32))
    assert not old.exists()


def test_enospc_leaves_previous_complete_file_and_cleans_tmp(m, tmp_path, monkeypatch):
    import errno
    import util_atomic
    m.persist(tmp_path, event())
    path = tmp_path / ("a" * 32 + ".json")
    before = path.read_bytes()
    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "DO_NOT_PRINT_SQL")
    monkeypatch.setattr(util_atomic.os, "fsync", full)
    with pytest.raises(OSError):
        m.persist(tmp_path, event(call="d" * 32))
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_symlink_rejected(m, tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        m.persist(link, event())
    target = real / ("a" * 32 + ".json")
    secret = tmp_path / "secret"; secret.write_text("not overwritten")
    target.symlink_to(secret)
    with pytest.raises(ValueError):
        m.persist(real, event())
    assert secret.read_text() == "not overwritten"


def test_concurrent_calls_no_lost_updates(tmp_path):
    import concurrent.futures
    env = fake_env(tmp_path, "echo '[{\"success\":true,\"meta\":{\"rows_read\":1}}]'\n")
    def work(_):
        return run_shell(tmp_path, env, 'd1_observed_command hash_prefetch SELECT fund_score _d1_run_with_timeout 3 npx')
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(work, range(12)))
    assert all(r.returncode == 0 and "incomplete" not in r.stderr for r in results)
    history = calls(tmp_path)
    assert len(history) == len({c["call_id"] for c in history}) == 12


def test_lock_contention_bounded(m, tmp_path):
    import fcntl
    m.private_directory(tmp_path)
    with (tmp_path / ".lock").open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        with pytest.raises(TimeoutError):
            m.persist(tmp_path, event())


@pytest.mark.parametrize("table", ["fund_score", "fund_screener"])
@pytest.mark.parametrize("bad_count", [False, True])
def test_complete_sync_fake_only(tmp_path, monkeypatch, table, bad_count):
    import shutil
    monkeypatch.syspath_prepend(str(ROOT / "scripts/tests"))
    import test_pfscore_d1_single_import_20261026 as fixtures
    repo = fixtures._make_repo(tmp_path, fixtures.SCREENER_DDL,
                              lambda con: (fixtures._build_screener_rows(con),
                                           con.execute("ALTER TABLE fund_score ADD COLUMN benchmark REAL")))
    scripts = repo / "scripts"
    (scripts / "lib").mkdir(parents=True)
    for name in ["d1_execute.sh", "d1_hash_read.sh", "d1_sql_bundle.py", "d1_incremental_sync.py", "repo_paths.sh"]:
        shutil.copy(ROOT / "scripts/lib" / name, scripts / "lib" / name)
    for name in ["d1_metrics_evidence.py", "util_atomic.py", "sync_" + table + "_to_d1.sh"]:
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    # Explicit stub for whoami/state recording: no credential reads or notification imports.
    (scripts / "d1_sync_state.py").write_text("import os,sys\nfrom pathlib import Path\np=Path(os.environ['REPO'])/'state-calls'\nwith p.open('a') as f:f.write(sys.argv[1]+'\\n')\n")
    env = fake_env(tmp_path, """case "$*" in
 *--file=*) echo '[{"success":true,"results":[{"Total queries executed":8,"Rows read":8,"Rows written":8}],"meta":{"rows_read":8,"rows_written":8,"duration":0.4}}]' ;;
 *'ALTER TABLE'*) echo 'duplicate column name' >&2; exit 1 ;;
 *'COUNT('* ) printf '[{"success":true,"results":[{"n":%s}],"meta":{"rows_read":3,"rows_written":0,"duration":0.1}}]\\n' "$FAKE_COUNT" ;;
 *'SELECT fund_code'*) echo '[{"success":true,"results":[],"meta":{"rows_read":0,"rows_written":0,"duration":0.1}}]' ;;
 *) echo 'unexpected fake call' >&2; exit 90 ;;
esac
""")
    env.update(REPO=str(repo), GIT_REPO=str(repo), FAKE_COUNT="999" if bad_count else "3")
    r = subprocess.run(["bash", str(scripts / ("sync_" + table + "_to_d1.sh"))],
                       cwd=repo, env=env, capture_output=True, text=True, timeout=25)
    assert r.returncode == (1 if bad_count else 0), r.stdout + r.stderr
    state_calls = (repo / "state-calls").read_text().splitlines()
    assert state_calls == ["whoami-check", "record-failure" if bad_count else "record-success"]
    history = calls(tmp_path)
    stages = [c["stage"] for c in history]
    assert stages == ["migration"] * (2 if table == "fund_score" else 1) + ["hash_prefetch", "import", "count_verify"]
    assert (tmp_path / "calls").read_text() == "x" * len(stages)
    assert len({c["run_id"] for c in history}) == 1
    bundle = next(c for c in history if c["stage"] == "import")
    assert bundle["table_labels"] == [table, "sync_meta" if table == "fund_score" else "screener_meta"]
    assert len(bundle["results"]) == 1 and bundle["results"][0]["scope"] == "bundle"
    for c in history:
        assert c["start_utc"] <= c["end_utc"]
        assert c["code_ref"] is None and c["code_ref_reason"] == "unavailable"
    serialized = json.dumps(history)
    assert "SELECT" not in serialized.replace('"SELECT"', '""')
    assert "基金" not in serialized and "duplicate column" not in serialized


@pytest.mark.parametrize("kind,expected", [("network", 3), ("sql", 1)])
def test_instrumented_retry_limits(tmp_path, kind, expected):
    env = fake_env(tmp_path, "echo '" + ("fetch failed" if kind == "network" else "syntax error") + "' >&2\nexit 6\n")
    r = run_shell(tmp_path, env, 'd1_execute_sql_file db unused "$REPO/out"')
    assert r.returncode == 6
    assert (tmp_path / "calls").read_text() == "x" * expected
    history = calls(tmp_path)
    assert [c["attempt"] for c in history] == list(range(1, expected + 1))
    assert len({c["call_id"] for c in history}) == 1
    assert all(c["metrics_status"] == "unavailable" for c in history)


def test_hash_pagination_records_every_page(tmp_path):
    env = fake_env(tmp_path, """n=$(wc -c < "$CALL_LOG")
if [ "$n" -eq 1 ]; then
 echo '[{"success":true,"results":[{"fund_code":"A","row_hash":"a"},{"fund_code":"B","row_hash":"b"}],"meta":{"rows_read":2,"rows_written":0}}]'
else
 echo '[{"success":true,"results":[{"fund_code":"C","row_hash":"c"}],"meta":{"rows_read":1,"rows_written":0}}]'
fi
""")
    r = run_shell(tmp_path, env, 'source ' + shlex.quote(str(ROOT / "scripts/lib/d1_hash_read.sh")) +
                  '\nd1_read_hashes db fund_score "$REPO/hashes" 2')
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "hashes").read_text()) == {"A": "a", "B": "b", "C": "c"}
    assert [c["results"][0]["rows_read"] for c in calls(tmp_path)] == [2, 1]
    assert (tmp_path / "calls").read_text() == "xx"


def test_save_safely_enospc_warns_no_sensitive_text(m, tmp_path, monkeypatch, capfd):
    import argparse
    import errno
    args = argparse.Namespace(call_id="a" * 32, attempt=1, tables="fund_score", start="2026-01-01T00:00:00Z",
                              end="2026-01-01T00:00:01Z", stage="import", operation="IMPORT", scope="bundle", exit_code=0)
    monkeypatch.setenv("D1_METRICS_RUN_ID", "b" * 32)
    monkeypatch.setenv("D1_METRICS_DIR", str(tmp_path))
    def full(*a, **k):
        raise OSError(errno.ENOSPC, "SECRET_SQL")
    monkeypatch.setattr(m, "atomic_write_json", full)
    assert not m.save_safely(args, (json.dumps([result()]).encode(), b""))
    out = capfd.readouterr()
    assert out.out == "" and "incomplete" in out.err and "SECRET_SQL" not in out.err
    assert args.exit_code == 0


def test_retention_failure_is_not_business_failure(m, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "MAX_RUNS", 1)
    m.persist(tmp_path, event())
    original = Path.unlink
    def denied(self, *a, **kw):
        if self.suffix == ".json":
            raise PermissionError("private")
        return original(self, *a, **kw)
    monkeypatch.setattr(Path, "unlink", denied)
    with pytest.raises(PermissionError):
        m.persist(tmp_path, event(run="b" * 32))
    # Refuse new receipt when eviction fails: bounded storage even under errors.
    assert not (tmp_path / ("b" * 32 + ".json")).exists()
    assert len(list(tmp_path.glob("*.json"))) == 1
