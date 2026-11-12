"""Run real shell notification branches through the real notify CLI, offline.

Bounded, verbatim shell sections and complete isolated staticdata scripts run:
no real collectors, git, R2, deployment or global locks. Guard results and the business-summary process are
fixtures; notify routing/dedup/info persistence are real, with all three channel
transports stubbed before main(). All roots/config/state are temporary. The child
blocks networking, further processes and writes outside its temporary root before
importing notify. This tests producer classification, not backup end-to-end.
"""
import ast
import json
from pathlib import Path
import os
import signal
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
ASYNC = "staticdata_backup_async.sh"
SYNC = "staticdata_sync.sh"

# The shell's $PY is an executable fixture dispatcher, not a production interpreter.
DRIVER = r'''
import datetime
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
root = Path(os.environ["REPO"]).resolve()
allowed_exec = None
def record(kind, **fields):
    with (root / "calls.jsonl").open("a") as f:
        f.write(json.dumps(dict(kind=kind, **fields)) + "\n")

def audit(event, args):
    if event == "os.exec" and allowed_exec and args[0] == allowed_exec[0] and args[1] == allowed_exec[1]:
        return
    if event.startswith("socket.") or event in (
        "subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.fork"
    ):
        raise AssertionError("forbidden external action: " + event)
    if event == "open" and isinstance(args[0], (str, bytes)):
        path, mode, flags = args
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
        )
        if writing and not Path(os.fsdecode(path)).resolve().is_relative_to(root):
            raise AssertionError("write outside isolated root")
sys.addaudithook(audit)

target = Path(sys.argv[1])
if str(target) != "-c":
    target = target.absolute()
assert target.parent == root / "scripts" or (str(target) == "-c")
if str(target) == "-c":
    print(os.environ.get("TEST_TRADING", "1"))
    sys.exit(0)
args = sys.argv[2:]
record("cli", target=target.name, args=args)
if target.name == "with_lock.py":
    cmd = args[args.index("bash"):]
    if cmd[1] == "-c":
        assert args[:2] == ["--nb", "/tmp/trade_backup_r2.lock"]
        assert cmd[-1] == str(root / "scripts/upload_r2.py")
        record("upload_stub", args=["upload-large-json"])
        sys.exit(int(os.environ.get("TEST_UPLOAD_RC", "0")))
    assert Path(cmd[1]).parent == root / "scripts"
    assert Path(cmd[1]).name in ("staticdata_backup_async.sh", "staticdata_sync.sh")
    allowed_exec = (os.environ["TEST_BASH"], [os.environ["TEST_BASH"], *cmd[1:]])
    os.execve(*allowed_exec, dict(os.environ))
if target.name == "large_json_excludes.py":
    sys.exit(0)
if target.name == "staticdata_write_guard.py":
    if "--check-fresh" in args:
        print("data/new.json")
        sys.exit(int(os.environ["TEST_FRESH_RC"]))
    sys.exit(int(os.environ["TEST_AUTH_RC"]))
if target.name == "daily_summary_email.py":
    sys.exit(int(os.environ["TEST_SUMMARY_RC"]))
assert target.name in ("notify.py", "ops_legacy_events.py"), "unexpected production entry point"
sys.path.insert(0, os.environ["TEST_SCRIPTS"])
spec = importlib.util.spec_from_file_location("quiet_notify_under_test", Path(os.environ["TEST_SCRIPTS"]) / "notify.py")
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)
class FrozenDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 11, 12, 0, tzinfo=tz)
notify.datetime = FrozenDatetime
def channel(name):
    def send(*args, **kwargs):
        record("transport", channel=name, subject=args[0])
        return True
    return send
notify._send_email = channel("email")
notify.send_telegram = channel("telegram")
notify.send_feishu = channel("feishu")
if target.name == "ops_legacy_events.py":
    import ops_legacy_events as ops
    import contextlib, io, subprocess
    def transport_cli(cmd, **kwargs):
        assert Path(cmd[1]).name == "notify.py"
        record("cli", target="notify.py", args=cmd[2:])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = notify.main(cmd[2:])
        return subprocess.CompletedProcess(cmd, rc, out.getvalue(), err.getvalue())
    ops.subprocess.run = transport_cli
    sys.exit(ops.main(args))
sys.exit(notify.main(args))
'''


def bounded_shell(command, env, root):
    proc = subprocess.Popen(command, env=env, cwd=root, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(command, proc.returncode, out, err)


def section(name, start, end=None):
    text = (SCRIPTS / name).read_text()
    assert text.count(start) == 1, (name, start)
    text = text[text.index(start):]
    if end:
        assert text.count(end) == 1, (name, end)
        text = text[:text.index(end)]
    return text


SECTIONS = {
    "update": ("update_all.sh", 'NOTIFY_BODY="update_all 完成', "# daily_brief 每日AI预测"),
    "r2": (ASYNC, '  _R2_GA_MSG=$(', '  if [ "$_R2_SKIP" = "0" ]; then'),
    "async_git": (ASYNC, '_GA_NEW_ADD=""', 'if [ "$_GA_GIT_SKIP" = "0" ]; then'),
    "sync_git": (SYNC, '_GA_NEW_ADD=""', 'if [ "$_GAUTH_RC" -ne 1 ] || [ "$_GA_OK" = "1" ]; then'),
    "backup_fail": (ASYNC, 'if [ "$STATICDATA_FAIL" = "1" ]; then\n  "$PY"', None),
    "backup_missing": (ASYNC, '  if [ ! -d "$STATICDATA_REPO/.git" ]; then', '  echo "-> staticdata 备份'),
}


@pytest.fixture
def runner(tmp_path):
    root = tmp_path / "runtime"
    for name in ("scripts", "config", "data", "static-site/data", "bin", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    driver = root / "driver"
    driver.write_text(f"#!{sys.executable}\n" + DRIVER)
    driver.chmod(0o700)
    # Only the non-mutating shell utilities used by these sections are available.
    for command in ("tee", "grep", "date"):
        executable = shutil.which(command)
        assert executable, command
        (root / "bin" / command).symlink_to(executable)
    bash = shutil.which("bash")
    assert bash
    # Do not inherit secrets, ambient opt-ins, notification switches or production roots.
    env = {
        "PATH": str(root / "bin"), "PY": str(driver), "REPO": str(root),
        "GIT_REPO": str(root), "MAIN_REPO": str(root), "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": str(root / "tmp"), "TEST_SCRIPTS": str(SCRIPTS), "STATICDATA_REPO": str(root / "staticdata"),
        "LOG": str(root / "shell.log"), "TRIGGER": "offline-producer-test",
        "TEST_AUTH_RC": "1", "TEST_FRESH_RC": "0", "TEST_SUMMARY_RC": "0",
        "STATICDATA_FAIL": "0", "SYNC_FAIL": "0", "_SKIP_NONPROD": "0",
        "ELAPSED": "120", "ELAPSED_MIN": "2", "RC_CORE": "0", "RC_WIDTH": "0",
        "RC_FUTURES": "0", "SIGNAL_RC": "0", "FAILED_DETAILS": "",
        "FRESH_MSG": "fresh", "FRESH_OK": "1", "NOW_STR": "2026-11-11 12:00:00",
        "MM_DD_HM": "11-11 12:00", "SEVERE": "0",
    }

    def run(kind, **overrides):
        script = root / "branch.sh"
        prelude = ('_UA_OP_RUN=$("$PY" "$REPO/scripts/ops_legacy_events.py" begin --repo "$REPO" --task update_all)\n' if kind == "update" else "")
        script.write_text("set -u\nset -o pipefail\n_NOTIFY_DRY=()\n" + prelude + section(*SECTIONS[kind]) +
                          '\nprintf "STATE %s %s %s %s %s\\n" "${_R2_SKIP:-unset}" '
                          '"${_GA_GIT_SKIP:-unset}" "${_GA_OK:-unset}" "$STATICDATA_FAIL" "$SYNC_FAIL"\n')
        proc = bounded_shell([bash, str(script)], {**env, **overrides}, root)
        records = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
        assert not any("Traceback" in x for x in (proc.stdout, proc.stderr, (root / "shell.log").read_text()
                                                  if (root / "shell.log").exists() else "")), proc
        return proc, records

    run.env = env
    run.bash = bash
    return root, run


def notifications(records):
    return [r["args"] for r in records if r["kind"] == "cli" and r["target"] == "notify.py"]


def transports(records):
    return [r for r in records if r["kind"] == "transport"]


@pytest.mark.parametrize("kind", ["r2", "async_git", "sync_git"])
def test_expected_success_and_protection_are_local_info(runner, kind):
    root, run = runner
    proc, records = run(kind)
    assert proc.returncode == 0, proc
    assert not transports(records), records  # Fails on all unpatched producers.
    calls = notifications(records)
    assert len(calls) == 1
    assert calls[0][calls[0].index("--tier") + 1] == "info"
    logged = [json.loads(line) for line in (root / "data/alerts/info_log.jsonl").read_text().splitlines()]
    assert [r["subject"] for r in logged] == [calls[0][0]]
    assert not (root / "data/alerts/latest.md").exists()
    expected = {"r2": "STATE 1 unset unset 0 0", "async_git": "STATE unset 1 unset 0 0",
                "sync_git": "STATE unset unset 0 0 1"}
    assert expected[kind] in proc.stdout  # No changes to the actual guard decision/exit state.


def test_update_completion_mail_restored_baseline_delivery(runner):
    # 2026-11-12 合并：同时保留完成邮件外发 + 运行证据/unknown 语义。
    # 完成邮件按 main 的 F3 回退版本外发（无 --tier info，info=noop 会被静默）；
    # Codex 侧的 ops_legacy_events 运行证据（unknown）必须同在，旧故障不自动关闭。
    root, run = runner
    proc, records = run("update")
    assert proc.returncode == 0, proc
    calls = notifications(records)
    assert len(calls) == 1
    assert calls[0][0].startswith("[完成] update_all")
    assert "--tier" not in calls[0]
    assert [r["subject"] for r in transports(records)] == [calls[0][0]] * len(transports(records))
    assert transports(records), records  # 完成邮件真的外发。
    assert any(r.get("target") == "daily_summary_email.py" and r["args"] == ["--mode", "main"] for r in records)
    unknown = [r for r in records if r.get("target") == "ops_legacy_events.py"
               and "unknown" in r["args"]]
    assert unknown, records  # 证据不足保留 unknown，不自动关闭旧故障。


@pytest.mark.parametrize("kind,key", [
    ("r2", "staticdata_backup_r2_guard_error"),
    ("async_git", "staticdata_backup_guard_error"),
    ("sync_git", "staticdata_sync_guard_error"),
])
def test_guard_internal_errors_remain_reachable(runner, kind, key):
    _, run = runner
    proc, records = run(kind, TEST_AUTH_RC="2")
    assert proc.returncode == 0, proc
    assert key in notifications(records)[0]
    assert "--tier" not in notifications(records)[0]
    assert transports(records), records
    if kind == "r2":
        assert "STATE 1 unset unset 1 0" in proc.stdout  # R2 remains fail-closed.


@pytest.mark.parametrize("kind", ["async_git", "sync_git"])
@pytest.mark.parametrize("fresh_rc,suffix", [("1", "gate_reject"), ("2", "gate_error")])
def test_explicit_fresh_gate_rejection_and_internal_error_are_not_silenced(runner, kind, fresh_rc, suffix):
    _, run = runner
    proc, records = run(kind, STATICDATA_ALLOW_PUSH="1", TEST_FRESH_RC=fresh_rc)
    assert proc.returncode == 0, proc
    call, = notifications(records)
    assert any(arg.endswith(suffix) for arg in call)
    assert "--tier" not in call
    assert transports(records), records  # rc=1 also includes real fetch failure.


@pytest.mark.parametrize("kind", ["r2", "async_git", "sync_git"])
@pytest.mark.parametrize("auth_rc", ["0", "1"])
def test_production_or_explicit_allow_keeps_existing_guard_decision(runner, kind, auth_rc):
    _, run = runner
    proc, records = run(kind, TEST_AUTH_RC=auth_rc, STATICDATA_ALLOW_PUSH="1", STATICDATA_ALLOW_R2_UPLOAD="1")
    assert proc.returncode == 0, proc
    assert notifications(records) == []
    assert transports(records) == []
    expected = {"r2": "STATE 0 unset unset 0 0", "async_git": "STATE unset 0 unset 0 0",
                "sync_git": f"STATE unset unset {auth_rc} 0 0"}
    assert expected[kind] in proc.stdout


def test_update_failure_preserves_alert_and_business_summary(runner):
    _, run = runner
    proc, records = run("update", SEVERE="1", RC_CORE="1")
    assert proc.returncode == 0, proc
    call, = notifications(records)
    assert call[call.index("--tier") + 1] == "critical" and "--ops-event-refs" in call
    assert transports(records)
    assert any(r.get("target") == "daily_summary_email.py" for r in records)


def test_business_summary_failure_still_alerts_after_baseline_success(runner):
    # 2026-11-12 合并：同时保留完成邮件外发 + 运行证据/unknown 语义。
    # 成功分支：完成通知无 --tier（照旧外发，进入 transports）；
    # 失败分支：改由 ops_legacy_events 产生 daily_summary 操作失败（带 --ops-event-refs），照旧外发。
    _, run = runner
    proc, records = run("update", TEST_SUMMARY_RC="3")
    assert proc.returncode == 0, proc
    success, failure = notifications(records)
    assert "--tier" not in success
    assert "daily_summary 操作失败" in failure[0] and "--ops-event-refs" in failure
    subjects = {r["subject"] for r in transports(records)}
    assert transports(records) and subjects == {success[0], failure[0]}


def test_missing_backup_repository_still_alerts(runner):
    _, run = runner
    proc, records = run("backup_missing")
    assert proc.returncode == 0, proc
    call, = notifications(records)
    assert "staticdata_backup_repo_missing" in call and "--tier" not in call
    assert transports(records)


def test_persistent_backup_failure_keeps_real_escalation(runner):
    root, run = runner
    (root / "data/staticdata_backup_fail_state.json").write_text(json.dumps({
        "last_fail_date": "2026-11-10", "consecutive_days": 1,
    }))
    proc, records = run("backup_fail", STATICDATA_FAIL="1")
    assert proc.returncode == 1, proc
    call, = notifications(records)
    assert "staticdata_backup_fail" in call and "--severe" in call and "--tier" not in call
    assert transports(records), records  # Real existing R4 rule, not a mocked grade.


@pytest.fixture
def full_runner(runner):
    root, branch_run = runner
    for name in (ASYNC, SYNC):
        shutil.copyfile(SCRIPTS / name, root / "scripts" / name)
    (root / "scripts/lib").mkdir()
    shutil.copyfile(SCRIPTS / "lib/repo_paths.sh", root / "scripts/lib/repo_paths.sh")
    for name in (".venv/bin", "staticdata/.git", "staticdata/data", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / ".venv/bin/python").symlink_to(root / "driver")
    (root / "static-site/data/probe.json").write_text('{"test":true}')
    for command in ("dirname", "basename", "mkdir", "cp", "mv", "rm", "mktemp", "tail"):
        executable = shutil.which(command)
        assert executable, command
        (root / "bin" / command).symlink_to(executable)
    # No real git/rsync/sed executable is available. In particular the legacy
    # launch-agent sed call never reads the host's plist contents (HOME unchanged).
    helper = root / "safe-tools"
    helper.write_text(f"#!{sys.executable}\n" + r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ["REPO"]).resolve()
name = Path(sys.argv[0]).name
args = sys.argv[1:]
def local(path):
    p = Path(path).resolve()
    assert p.is_relative_to(root), "tool escaped temporary root"
    return p
with (root / "calls.jsonl").open("a") as f:
    f.write(json.dumps({"kind": "tool", "name": name}) + "\n")
if name == "sed":
    sys.exit(0)
if name == "rsync":
    source, dest = map(local, args[-2:])
    if os.environ.get("TEST_RSYNC_RC", "0") != "0":
        sys.exit(int(os.environ["TEST_RSYNC_RC"]))
    dest.mkdir(parents=True, exist_ok=True)
    for p in source.glob("*.json"):
        (dest / p.name).write_bytes(p.read_bytes())
    sys.exit(0)
assert name == "git" and args[0] == "-C"
local(args[1])
assert args[2] in ("add", "reset", "diff"), "unexpected git operation"
sys.exit(0)  # diff --quiet: isolated repository has no staged changes.
''')
    helper.chmod(0o700)
    for command in ("git", "rsync", "sed"):
        (root / "bin" / command).symlink_to(helper)
    env = {**branch_run.env, "TEST_BASH": branch_run.bash, "TMPDIR": str(root / "tmp")}

    def run(name, **overrides):
        # Full unmodified shell, including lock reentry and heartbeat/exit tail.
        proc = bounded_shell([branch_run.bash, str(root / "scripts" / name), "offline"],
                             {**env, **overrides}, root)
        records = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
        all_output = proc.stdout + proc.stderr + "".join(p.read_text() for p in (root / "data/logs").glob("*.log"))
        assert "Traceback" not in all_output and "command not found" not in all_output, all_output
        return proc, records

    return root, run


@pytest.mark.parametrize("name,count", [(ASYNC, 2), (SYNC, 1)])
def test_complete_default_nonprod_flow_has_no_late_notification(full_runner, name, count):
    root, run = full_runner
    proc, records = run(name)
    assert proc.returncode == 0, proc
    assert len(notifications(records)) == count
    assert not transports(records), records
    assert not any(r["kind"] == "upload_stub" or r.get("name") == "git" for r in records)
    assert any(r.get("target") == "with_lock.py" for r in records)  # Reentry was exercised.
    assert (root / "staticdata/data/probe.json").read_bytes() == (root / "static-site/data/probe.json").read_bytes()
    if name == ASYNC:
        assert json.loads((root / "data/staticdata_backup_heartbeat.json").read_text())["result"] == "skip_nonprod"
        assert "staticdata_backup_fail" not in str(notifications(records))
    else:
        assert "同步部分失败(best-effort,不阻塞调用方)" in proc.stdout  # Existing SYNC_FAIL/exit-0 contract unchanged.


@pytest.mark.parametrize("name", [ASYNC, SYNC])
def test_complete_guard_internal_failure_still_reaches_transport(full_runner, name):
    _, run = full_runner
    proc, records = run(name, TEST_AUTH_RC="2")
    assert proc.returncode == (1 if name == ASYNC else 0), proc
    assert transports(records)
    assert not any(r["kind"] == "upload_stub" for r in records)
    assert any("guard_error" in " ".join(args) for args in notifications(records))


@pytest.mark.parametrize("failure", ["rsync", "upload"])
def test_complete_backup_failure_is_not_hidden_by_nonprod_guard(full_runner, failure):
    root, run = full_runner
    (root / "data/staticdata_backup_fail_state.json").write_text(json.dumps({
        "last_fail_date": "2026-11-10", "consecutive_days": 1,
    }))
    overrides = {"TEST_RSYNC_RC": "1"} if failure == "rsync" else {
        "STATICDATA_ALLOW_R2_UPLOAD": "1", "TEST_UPLOAD_RC": "1",
    }
    proc, records = run(ASYNC, **overrides)
    assert proc.returncode == 1, proc
    calls = notifications(records)
    assert any("staticdata_backup_fail" in args and "--severe" in args for args in calls)
    assert transports(records)
    assert all("staticdata备份失败" in r["subject"] for r in transports(records))


@pytest.mark.parametrize("name", [ASYNC, SYNC])
def test_complete_old_default_guard_reproduces_outbound_calls(full_runner, name):
    root, run = full_runner
    path = root / "scripts" / name
    before = path.read_text()
    after = before
    for key in ("staticdata_backup_r2_nonprod_skip", "staticdata_backup_nonprod_skip", "staticdata_sync_nonprod_skip"):
        after = after.replace(f"--tier info --dedup-key {key}", f"--dedup-key {key}")
    assert after != before
    path.write_text(after)  # Mutation is confined to the disposable script copy.
    proc, records = run(name)
    assert proc.returncode == 0, proc
    assert transports(records)  # Old routine flow really would call a channel.


def source_symbols(name, names, namespace):
    """Execute only named pure definitions; never import a producer's main body."""
    tree = ast.parse((SCRIPTS / name).read_text())
    selected = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name in names
    ) or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in node.targets))]
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SCRIPTS / name), "exec"), namespace)


def test_complete_sync_output_through_real_parent_summary_and_monitor_patterns(full_runner, capsys):
    root, run = full_runner
    proc, records = run(SYNC)
    calls = []

    def parent_subprocess(command, **kwargs):
        calls.append(command)
        assert command == ["bash", str(root / "scripts" / SYNC), "daily-brief", "probe.json"]
        return subprocess.CompletedProcess(command, proc.returncode, proc.stdout.encode(), proc.stderr.encode())

    # Real wrapper definitions consume the complete script's actual output/rc.
    namespace = {"Path": Path, "os": SimpleNamespace(environ={}),
                 "subprocess": SimpleNamespace(run=parent_subprocess),
                 "force_env": lambda env, repo: {"REPO": str(repo), "GIT_REPO": str(repo)}}
    source_symbols("gen_daily_brief.py", {"_sync_warn_extra", "staticdata_sync"}, namespace)
    namespace["staticdata_sync"](root, no_upload=False, files=["probe.json"])
    summary = capsys.readouterr().out
    assert calls and "[staticdata]" in summary and "同步部分失败" in summary
    assert not transports(records)
    patterns = {"re": re}
    source_symbols("gen_schedule_stats.py", {"ANOMALY_RE", "MARKER_ANOMALY_RE"}, patterns)
    for key in ("ANOMALY_RE", "MARKER_ANOMALY_RE"):
        assert patterns[key].search(proc.stdout + proc.stderr + summary) is None
    # Negative controls: the real monitoring predicates still catch real faults.
    assert patterns["ANOMALY_RE"].search("FATAL storage unavailable")
    assert patterns["MARKER_ANOMALY_RE"].search("⚠ [fetch_news] staticdata 同步 rc=1")
