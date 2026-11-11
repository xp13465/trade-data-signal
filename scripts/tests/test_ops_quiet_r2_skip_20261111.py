"""Complete skip shell + real local queue/notify, with transport/failure stubs.

No real lock, upload, credentials or network. Reuse the preceding producer
fixture's pre-import network/process/write guard and bounded process-group runner.
Only queue disk errors and the three notification transports are injected; queue
copy/readback/source retirement and notify dedup are the actual implementations.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

from test_ops_quiet_producers_20261111 import DRIVER, bounded_shell, notifications, transports

SCRIPTS = Path(__file__).resolve().parents[1]
SCRIPT = "r2_upload_skip_notify.sh"
INLINE_PYTHON = '''
if sys.argv[1] == "-c":
    code = sys.argv[2]
    sys.argv = ["-c", *sys.argv[3:]]
    exec(compile(code, "<shell-state-parser>", "exec"), {"__name__": "__main__"})
    sys.exit(0)
'''
PENDING = '''
if target.name == "r2_pending_context.py":
    sys.path.insert(0, os.environ["TEST_SCRIPTS"])
    spec = importlib.util.spec_from_file_location("pending_under_test", Path(os.environ["TEST_SCRIPTS"]) / target.name)
    pending = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pending)
    mode = os.environ.get("TEST_PENDING_MODE", "normal")
    def fail(*args, **kwargs):
        raise OSError("injected disk failure")
    if mode == "enqueue_failure":
        pending.atomic_write_text = fail
    elif mode == "retire_failure":
        pending.retire_source = fail
    elif mode == "retire_noop":
        pending.retire_source = lambda *args: {"retired_source": False}
    elif mode == "malformed" and args == ["enqueue"]:
        print("not-json")
        sys.exit(0)
    elif mode in ("wrong_run", "wrong_root"):
        original = pending.enqueue
        def wrong_identity(*args):
            row = original(*args)
            row["run_id" if mode == "wrong_run" else "static_dir"] = "other-request"
            return row
        pending.enqueue = wrong_identity
    sys.argv = [str(target), *args]
    try:
        pending.main()
    except OSError:
        print("injected disk failure", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
'''


@pytest.fixture
def skip_runner(tmp_path):
    root = tmp_path / "runtime"
    for name in ("scripts/lib", ".venv/bin", "data/logs", "config", "bin", "static-site/data", "source"):
        (root / name).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCRIPTS / SCRIPT, root / "scripts" / SCRIPT)
    shutil.copyfile(SCRIPTS / "lib/repo_paths.sh", root / "scripts/lib/repo_paths.sh")
    text = DRIVER.replace('target = Path(sys.argv[1])', INLINE_PYTHON + '\ntarget = Path(sys.argv[1])')
    text = text.replace('assert target.name == "notify.py", "unexpected production entry point"',
                        PENDING + '\nassert target.name == "notify.py", "unexpected production entry point"')
    assert text != DRIVER and text.count("pending_under_test") == 1
    driver = root / ".venv/bin/python"
    driver.write_text(f"#!{sys.executable}\n" + text)
    driver.chmod(0o700)
    for name in ("date", "dirname", "basename", "mkdir"):
        executable = shutil.which(name)
        assert executable
        (root / "bin" / name).symlink_to(executable)
    bash = shutil.which("bash")
    assert bash
    proof = root / "source/export-proof.json"
    proof.write_text(json.dumps({"version": 1, "run_id": "skip-test-run",
                                "static_dir": str((root / "static-site").resolve()),
                                "outputs": {"probe.json": {"size": 2, "sha256": hashlib.sha256(b"{}").hexdigest()}}}))
    raw = proof.read_bytes()
    env = {"PATH": str(root / "bin"), "REPO": str(root), "GIT_REPO": str(root),
           "MAIN_REPO": str(root), "TEST_SCRIPTS": str(SCRIPTS), "PYTHONDONTWRITEBYTECODE": "1",
           "DEPLOY_LOG": str(root / "data/logs/deploy.log"),
           "R2_UPLOAD_ASYNC_PENDING": str(root / "pending"),
           "R2_EXPORT_PROOF_PATH": str(proof), "R2_EXPORT_RUN_ID": "skip-test-run"}

    def run(mode="normal", legacy=False, **overrides):
        current = {**env, "TEST_PENDING_MODE": mode, **overrides}
        if legacy:
            current.pop("R2_EXPORT_PROOF_PATH")
            current.pop("R2_EXPORT_RUN_ID")
        proc = bounded_shell([bash, str(root / "scripts" / SCRIPT), str(root / "async.lock")], current, root)
        records = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
        log = (root / "data/logs/r2_upload_async_skip.log").read_text()
        deploy = (root / "data/logs/deploy.log").read_text()
        assert proc.returncode == 0, proc  # Existing best-effort callback contract.
        assert "Traceback" not in proc.stderr and "command not found" not in proc.stderr, proc
        return records, log + deploy

    return root, proof, raw, run


def pending_calls(records):
    return [r["args"] for r in records if r.get("target") == "r2_pending_context.py"]


def assert_actionable_failure(records, text, state):
    call = notifications(records)[-1]
    assert "--severe" in call and "--tier" not in call
    assert call[call.index("--feishu-group") + 1] == "alert"
    assert state in text and state in call[call.index("--dedup-key") + 1]
    assert "显式 retry" in call[1]
    assert transports(records)
    assert "已有实例在跑负责完成" not in text + call[1]


def test_enqueue_disk_failure_preserves_source_and_alerts(skip_runner):
    root, proof, raw, run = skip_runner
    records, text = run("enqueue_failure")
    assert pending_calls(records) == [["enqueue"]]
    assert proof.read_bytes() == raw
    assert not list((root / "pending.contexts").glob("*.proof"))
    assert_actionable_failure(records, text, "enqueue_failed")
    assert "无法确认 proof 已保全" in text
    assert "已保全待接手" not in text


def test_retire_failure_keeps_queue_and_source_but_never_normal_report(skip_runner):
    root, proof, raw, run = skip_runner
    records, text = run("retire_failure")
    assert pending_calls(records) == [["enqueue"], ["retire-source"]]
    assert proof.read_bytes() == raw
    assert [p.read_bytes() for p in (root / "pending.contexts").glob("*.proof")] == [raw]
    assert_actionable_failure(records, text, "retire_failed")
    assert "已保全待接手" in text and "清理未确认" in text


@pytest.mark.parametrize("mode,source_exists", [("normal", False), ("retire_noop", True)])
def test_success_only_claims_preserved_pending_not_holder_or_delivery(skip_runner, mode, source_exists):
    root, proof, raw, run = skip_runner
    records, text = run(mode)
    assert proof.exists() is source_exists
    assert [p.read_bytes() for p in (root / "pending.contexts").glob("*.proof")] == [raw]
    assert pending_calls(records) == [["enqueue"], ["retire-source"]]
    call, = notifications(records)
    assert "--severe" not in call and "--tier" not in call
    assert call[call.index("--feishu-group") + 1] == "report"
    assert "已保全待接手" in text and "handoff=queued" in text
    assert "合法持锁者" in call[1] and "交付时间" in call[1]
    for false_claim in ("已有实例在跑负责完成", "检测到另一实例正在运行", "保证同日", "源已删除"):
        assert false_claim not in call[1] + text


def test_legacy_wakeup_does_not_claim_proof_or_retire_source(skip_runner):
    root, proof, raw, run = skip_runner
    records, text = run(legacy=True)
    assert (root / "pending").exists() and proof.read_bytes() == raw
    assert pending_calls(records) == [["enqueue"]]
    assert "handoff=legacy" in text and "未登记逐请求 proof" in text
    assert "已保全待接手" not in text


def test_zero_exit_with_malformed_enqueue_result_is_unknown_not_success(skip_runner):
    _, proof, raw, run = skip_runner
    records, text = run("malformed")
    assert pending_calls(records) == [["enqueue"]]
    assert proof.read_bytes() == raw
    assert_actionable_failure(records, text, "invalid_result")
    assert "已保全待接手" not in text


@pytest.mark.parametrize("mode", ["enqueue_failure", "retire_failure"])
def test_repeated_failure_keeps_stable_key_and_real_dedup(skip_runner, mode):
    _, _, _, run = skip_runner
    first, _ = run(mode)
    second, _ = run(mode)
    a, b = notifications(second)
    assert a[a.index("--dedup-key") + 1] == b[b.index("--dedup-key") + 1]
    assert len(transports(first)) > 0
    assert len(transports(second)) == len(transports(first))  # Actual notify dedup, not a transport model.


@pytest.mark.parametrize("mode", ["wrong_run", "wrong_root"])
def test_success_result_for_wrong_identity_cannot_authorize_source_retirement(skip_runner, mode):
    _, proof, raw, run = skip_runner
    records, text = run(mode)
    assert pending_calls(records) == [["enqueue"]]
    assert proof.read_bytes() == raw
    assert_actionable_failure(records, text, "invalid_result")


@pytest.mark.parametrize("state", ["done", "superseded"])
def test_existing_terminal_record_is_not_reported_as_new_pending(skip_runner, state):
    root, _, _, run = skip_runner
    run()
    row_path, = (root / "pending.contexts").glob("*.json")
    row = json.loads(row_path.read_text())
    row["state"] = state
    row_path.write_text(json.dumps(row))
    Path(row["proof_path"]).unlink()  # Simulate the queue's existing completed/superseded tombstone.
    _, text = run()
    last_line = text.splitlines()[-1]
    assert "handoff=recorded_terminal" in last_line
    assert "已保全待接手" not in last_line


def test_prior_normal_report_dedup_cannot_hide_new_cleanup_failure(skip_runner):
    _, _, _, run = skip_runner
    normal, _ = run("retire_noop")
    fault, text = run("retire_failure")
    before, after = notifications(fault)
    assert before[before.index("--dedup-key") + 1] != after[after.index("--dedup-key") + 1]
    assert len(transports(fault)) > len(transports(normal))
    assert_actionable_failure(fault, text, "retire_failed")
