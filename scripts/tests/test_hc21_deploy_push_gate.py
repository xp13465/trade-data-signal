"""HC21 deploy 闭环：只跑指定块，Git 全在临时根，通知为只记录参数的桩。"""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_hc21_main_merge_push_gate import ROOT, fastcheck, git, prepare_git, sandbox  # noqa: F401

DEPLOY = ROOT / "scripts/deploy.sh"


def extract(start, end):
    text = DEPLOY.read_text()
    assert text.count(start) == 1 and text.count(end) == 1
    return start + text.split(start, 1)[1].split(end, 1)[0]


STUBS = r'''
# 原样使用 deploy 的 set -u / 无 set -e 语义。
set -u
DEPLOY_STAGE=git_commit_push
DEPLOY_RECORD_OFF=0
_deploy_integrity_summary_cleanup() { :; }
git() {
  [[ "$1" == "-C" && "$2" == "$GIT_REPO" ]] || return 99
  case "$3" in
    rev-parse|merge-base|stash|rebase|diff|checkout|add) ;;
    *) return 99;;
  esac
  echo "git ${*:3}" >> "$TRACE"
  "$REAL_GIT" -c core.hooksPath=/dev/null "$@"
}
git_push_timeout() {
  echo "push budget=$1" >> "$TRACE"
  case "${PUSH_MODE:-real}" in
    forced) return "$FORCED_RC";;
    accepted_unknown)
      "$REAL_GIT" -c core.hooksPath=/dev/null -C "$GIT_REPO" push origin main:main || return 99
      return 124;;
    real) "$REAL_GIT" -c core.hooksPath=/dev/null -C "$GIT_REPO" push origin main:main;;
    *) return 99;;
  esac
}
git_fetch_timeout() {
  echo "fetch budget=$1" >> "$TRACE"
  if [[ "${FETCH_RC:-0}" != "0" ]]; then return "$FETCH_RC"; fi
  "$REAL_GIT" -c core.hooksPath=/dev/null -C "$GIT_REPO" fetch origin main
}
'''


def setup_runtime(sandbox):
    repo, env = sandbox
    env.update(LOG=str(repo.parent / "deploy.log"), DEPLOY_FAIL_ALERT_THRESHOLD="2",
               GIT_PUSH_TIMEOUT="19", GIT_FETCH_TIMEOUT="17")
    shutil.copyfile(ROOT / "scripts/deploy_fail_tracker.py", repo / "scripts/deploy_fail_tracker.py")
    (repo / "scripts/notify.py").write_text(
        'import json, os, sys\nfrom pathlib import Path\n'
        'with Path(os.environ["TRACE"]).open("a") as f: print("notify " + json.dumps(sys.argv[1:]), file=f)\n'
        'sys.exit(int(os.environ.get("NOTIFY_RC", "0")))\n')


def script():
    return (STUBS + extract("_deploy_record_result() {", "# 加载 .env") +
            extract("# 5. 总是 git push", "# === staticdata 备份") +
            '\necho AFTER_PUSH >> "$TRACE"\nexit 0\n')


def execute(sandbox, locked=False):
    repo, env = sandbox
    setup_runtime(sandbox)
    args = ["/bin/bash", "-c", script()]
    if locked:
        args = [sys.executable, str(ROOT / "scripts/with_lock.py"),
                "--block-timeout", "2", str(repo.parent / "deploy.lock"), *args]
    return subprocess.run(args, cwd=repo, env=env, text=True, capture_output=True, timeout=25)


def traces(sandbox):
    return Path(sandbox[1]["TRACE"]).read_text().splitlines()


def state(sandbox):
    return json.loads((sandbox[0] / "data/deploy_fail_state.json").read_text())


def test_real_non_ff_keeps_checked_tree_dirty_files_and_remote(sandbox):
    repo, env = sandbox
    remote = prepare_git(sandbox, diverge=True)
    before = git(sandbox, "rev-parse", "HEAD")
    remote_before = git(sandbox, "--git-dir", str(remote), "rev-parse", "main")
    assert fastcheck(sandbox).returncode == 0
    # 旧逻辑为 rebase 自动 stash；新路径不得碰 staged/unstaged/untracked。
    (repo / "NOTES.md").write_text((repo / "NOTES.md").read_text() + "\nHC21 dirty\n")
    (repo / "untracked.txt").write_text("keep me")
    (repo / "stage.txt").write_text("keep staged")
    git(sandbox, "add", "stage.txt")
    dirty_before = git(sandbox, "status", "--porcelain", "--", "NOTES.md", "untracked.txt", "stage.txt")
    r = execute(sandbox, locked=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert git(sandbox, "rev-parse", "HEAD") == before
    assert git(sandbox, "--git-dir", str(remote), "rev-parse", "main") == remote_before
    assert git(sandbox, "status", "--porcelain", "--", "NOTES.md", "untracked.txt", "stage.txt") == dirty_before
    assert traces(sandbox) == ["git rev-parse --abbrev-ref HEAD", "push budget=19"]
    assert "重走完整入口" in Path(env["LOG"]).read_text()
    assert state(sandbox)["last_stage"] == "git_commit_push"
    with (repo.parent / "deploy.lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 拒推退出后锁可立即获取


@pytest.mark.parametrize("rc", [1, 124, 128])
def test_failed_fetch_cannot_use_stale_ref_as_success(sandbox, rc):
    repo, env = sandbox
    remote = prepare_git(sandbox)
    # 制造真实不一致：remote 仍旧 base，本地 tracking ref 却声称已接受 local。
    checked = git(sandbox, "rev-parse", "HEAD")
    git(sandbox, "update-ref", "refs/remotes/origin/main", checked)
    assert git(sandbox, "--git-dir", str(remote), "rev-parse", "main") != checked
    env.update(PUSH_MODE="forced", FORCED_RC=str(rc), FETCH_RC="128")
    r = execute(sandbox)
    assert r.returncode == rc, r.stdout + r.stderr
    assert traces(sandbox) == ["git rev-parse --abbrev-ref HEAD", "push budget=19"]
    assert state(sandbox)["last_rc"] == rc
    assert "push 成功" not in Path(env["LOG"]).read_text()


def test_unknown_after_remote_acceptance_is_not_declared_success(sandbox):
    repo, env = sandbox
    remote = prepare_git(sandbox)
    env["PUSH_MODE"] = "accepted_unknown"
    r = execute(sandbox)
    assert git(sandbox, "--git-dir", str(remote), "rev-parse", "main") == git(sandbox, "rev-parse", "HEAD")
    assert r.returncode == 124  # 没有可靠独立确认时保留失败，不猜成功
    assert state(sandbox)["last_rc"] == 124
    assert "AFTER_PUSH" not in traces(sandbox)


@pytest.mark.parametrize("notify_rc", [0, 9])
def test_failure_tracker_threshold_and_notification_contract(sandbox, notify_rc):
    repo, env = sandbox
    prepare_git(sandbox)
    env.update(PUSH_MODE="forced", FORCED_RC="128", FETCH_RC="128", NOTIFY_RC=str(notify_rc))
    # 过期 ref 会诱使旧逻辑报幂等成功，且错误地清空连续失败。
    git(sandbox, "update-ref", "refs/remotes/origin/main", "HEAD")
    for i in range(2):
        r = execute(sandbox)
        assert r.returncode == 128
        assert state(sandbox)["consecutive_fail"] == i + 1
    calls = [json.loads(x.removeprefix("notify ")) for x in traces(sandbox) if x.startswith("notify ")]
    assert len(calls) == 1
    assert calls[0][0] == "[告警] deploy 连续失败(停摆)"
    assert "--severe" in calls[0]
    assert calls[0][calls[0].index("--dedup-key") + 1] == "deploy_consecutive_fail"
    assert calls[0][calls[0].index("--dedup-window") + 1] == "21600"


def test_success_and_up_to_date_keep_followup_and_reset_failures(sandbox):
    repo, env = sandbox
    remote = prepare_git(sandbox)
    (repo / "data").mkdir()
    (repo / "data/deploy_fail_state.json").write_text('{"consecutive_fail": 2}')
    for _ in range(2):
        r = execute(sandbox)
        assert r.returncode == 0, r.stdout + r.stderr
        assert state(sandbox)["consecutive_fail"] == 0
    assert traces(sandbox).count("AFTER_PUSH") == 2
    assert git(sandbox, "--git-dir", str(remote), "rev-parse", "main") == git(sandbox, "rev-parse", "HEAD")
    assert "push 成功" in Path(env["LOG"]).read_text()
    assert not any(x.startswith(("fetch", "notify", "git stash", "git rebase")) for x in traces(sandbox))


def test_non_main_still_refused_before_push(sandbox):
    prepare_git(sandbox)
    git(sandbox, "checkout", "-b", "feat")
    r = execute(sandbox)
    assert r.returncode == 1
    assert traces(sandbox) == ["git rev-parse --abbrev-ref HEAD"]
    assert "deploy 必须在 main" in r.stdout


def test_real_push_timeout_kills_children_releases_lock_and_records_124(sandbox):
    repo, env = sandbox
    prepare_git(sandbox)
    setup_runtime(sandbox)
    bindir = repo.parent / "bin"
    bindir.mkdir()
    pidfile = repo.parent / "pids.json"
    lock = repo.parent / "deploy.lock"
    fake = bindir / "git"
    fake.write_text(f"#!{sys.executable}\n" + r'''
import fcntl, json, os, signal, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
if args == ["-C", os.environ["GIT_REPO"], "rev-parse", "--abbrev-ref", "HEAD"]:
    sys.exit(subprocess.run([os.environ["REAL_GIT"], *args], timeout=5).returncode)
assert args == ["-C", os.environ["GIT_REPO"], "push", "origin", "main:main"], args
with open(os.environ["TEST_LOCK"], "a") as f:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise AssertionError("push 没有持锁")
    except BlockingIOError:
        print("LOCK_HELD", flush=True)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
Path(os.environ["TEST_PIDS"]).write_text(json.dumps([os.getpid(), child.pid]))
def stop(*args):
    child.wait(timeout=3)
    sys.exit(143)
signal.signal(signal.SIGTERM, stop)
child.wait()
''')
    fake.chmod(0o755)
    env.update(PATH=str(bindir) + os.pathsep + env["PATH"], TEST_LOCK=str(lock),
               TEST_PIDS=str(pidfile), GIT_PUSH_TIMEOUT="1")
    # 只抽原 push timeout 函数 + EXIT trap + 第5步；其余生产主体不执行。
    body = ('set -u\nDEPLOY_STAGE=git_commit_push\nDEPLOY_RECORD_OFF=0\n'
            '_deploy_integrity_summary_cleanup() { :; }\n' +
            extract("_deploy_record_result() {", "# 加载 .env") +
            extract("git_push_timeout() {", "# 通用超时预算 helper") +
            extract("# 5. 总是 git push", "# === staticdata 备份"))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/with_lock.py"),
                        "--block-timeout", "2", str(lock), "/bin/bash", "-c", body],
                       env=env, cwd=repo, capture_output=True, text=True, timeout=20)
    assert r.returncode == 124, r.stdout + r.stderr
    assert state(sandbox)["last_rc"] == 124
    log = Path(env["LOG"]).read_text()
    assert "LOCK_HELD" in log and "超 1s 未退出" in log
    assert "push 成功" not in log
    for pid in json.loads(pidfile.read_text()):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    with lock.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
