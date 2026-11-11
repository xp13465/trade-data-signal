"""HC21: 只抽取白名单块；真实 Git/远端均在 tmp_path，云同步/CI 一律打桩。"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "scripts/main-merge.sh"
GIT = shutil.which("git")


def block(start, end=None):
    text = SOURCE.read_text()
    assert text.count(start) == 1
    part = text.split(start, 1)[1]
    if end:
        assert part.count(end) == 1
        part = part.split(end, 1)[0]
    return start + part


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # 三检查实际读取的文档、登记挂点与守卫目录；不复制生产 data/ 或凭据。
    paths = {"CLAUDE.md", "TASKS.md", "NOTES.md", "docs/pending-features-index.md",
             "docs/tasks-done-list.md", "docs/archive/TASKS-done.md", "docs/main-governance.md",
             "docs/archive/CLAUDE-errors-2026-08.md", "docs/ops/machine-check-registry.md",
             ".github/workflows/ci.yml", "scripts/main-merge.sh"}
    for role in ("implementer", "researcher", "tester"):
        paths.add(f".claude/skills/role-{role}/SKILL.md")
    registry = (ROOT / "docs/ops/machine-check-registry.md").read_text()
    paths.update(re.findall(r"(?:scripts|docs|\.github)/[A-Za-z0-9_./-]+\.(?:py|sh|yml|md|txt)", registry))
    paths.update(str(p.relative_to(ROOT)) for p in (ROOT / "scripts").rglob("check_*.py")
                 if "/tests/" not in p.as_posix())
    for rel in paths:
        src = ROOT / rel
        if src.is_file():
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    home = tmp_path / "home"
    home.mkdir()
    (home / "tdsignal.pem").touch()  # 仅供 ssh 桩通过在位检查，内容为空
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "MAIN_MERGE_"))}
    env.update(REPO=str(repo), GIT_REPO=str(repo), HOME=str(home), PY=sys.executable,
               REAL_GIT=GIT, TRACE=str(tmp_path / "trace"), DRY_RUN="0",
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="file")
    return repo, env


def run(sandbox, *args):
    repo, env = sandbox
    return subprocess.run(args, cwd=repo, env=env, text=True, capture_output=True, timeout=25)


def git(sandbox, *args):
    r = run(sandbox, GIT, "-c", "core.hooksPath=/dev/null", *args)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout.strip()


def shell(sandbox, script):
    return run(sandbox, "/bin/bash", "-c", "set -euo pipefail\n" + script)


def fastcheck(sandbox):
    return shell(sandbox, block("# 7.10 快检闸门(任何", "# 7.7 console 洁净度哨兵"))


def row(repo, top=False):
    p = repo / "docs/pending-features-index.md"
    text = p.read_text()
    assert not re.search(r"^\| 499 \|", text, re.M)
    addition = "| 499 | **(中) HC21 隔离反例** | test | test | test | 待办 |\n"
    p.write_text(addition + "\n" + text if top else text + "\n" + addition)


# 该函数只允许本地 origin + 四种 Git 操作；网络协议已由 GIT_ALLOW_PROTOCOL=file 禁止。
# ssh/CI 只记调用，不执行真实外发。源码尾段原样执行(含成功后的 10/11 步)。
TAIL_STUBS = r'''
GIT=guard_git
FEAT=hc21-fixture
guard_git() {
  echo "git $*" >> "$TRACE"
  case "$1" in
    push) [[ "$*" == "push origin main" ]] || return 99
          if [[ "${PUSH_RC:-0}" != "0" ]]; then return "$PUSH_RC"; fi;;
    fetch) [[ "$*" == "fetch origin" ]] || return 99;;
    rebase) [[ "$*" == "rebase origin/main" || "$*" == "rebase --abort" ]] || return 99;;
    rev-parse) [[ "$*" == "rev-parse HEAD" ]] || return 99;;
    *) return 99;;
  esac
  "$REAL_GIT" -c core.hooksPath=/dev/null -C "$REPO" "$@"
}
ssh() {
  echo "ssh $*" >> "$TRACE"
  echo LOCAL_SSH_STUB
  return "${SSH_RC:-0}"
}
ci_selfcheck() {
  echo "ci $*" >> "$TRACE"
  return "${TEST_CI_RC:-0}"
}
'''


def prepare_git(sandbox, diverge=False):
    repo, env = sandbox
    git(sandbox, "init", "-b", "main")
    git(sandbox, "config", "user.name", "HC21 test")
    git(sandbox, "config", "user.email", "hc21@example.invalid")
    git(sandbox, "add", ".")
    git(sandbox, "commit", "-m", "actual merged docs")
    base = git(sandbox, "rev-parse", "HEAD")
    remote = repo.parent / "remote.git"
    git(sandbox, "init", "--bare", str(remote))
    git(sandbox, "remote", "add", "origin", str(remote))
    git(sandbox, "push", "origin", "main")
    row(repo)
    git(sandbox, "add", ".")
    git(sandbox, "commit", "-m", "local row 499 at end")
    if diverge:
        local = git(sandbox, "rev-parse", "HEAD")
        git(sandbox, "checkout", "-b", "upstream", base)
        row(repo, top=True)
        git(sandbox, "add", ".")
        git(sandbox, "commit", "-m", "upstream row 499 at top")
        assert fastcheck(sandbox).returncode == 0
        git(sandbox, "push", "origin", "upstream:main")
        git(sandbox, "checkout", "main")
        assert git(sandbox, "rev-parse", "HEAD") == local
    return remote


def test_rejected_push_stops_without_changing_checked_tree(sandbox):
    repo, env = sandbox
    remote = prepare_git(sandbox, diverge=True)
    local = git(sandbox, "rev-parse", "HEAD")
    upstream = git(sandbox, "--git-dir", str(remote), "rev-parse", "main")
    assert fastcheck(sandbox).returncode == 0
    r = shell(sandbox, TAIL_STUBS + block("# push main\n"))
    trace = Path(env["TRACE"]).read_text().splitlines()
    assert r.returncode == 5, r.stdout + r.stderr
    assert trace == ["git push origin main"]
    assert "重走完整入口" in r.stderr
    assert git(sandbox, "rev-parse", "HEAD") == local
    assert git(sandbox, "--git-dir", str(remote), "rev-parse", "main") == upstream
    assert fastcheck(sandbox).returncode == 0
    # 负控证明夹具可触发原缺陷：仅在临时仓手动 rebase 后重复编号必须被检查发现。
    git(sandbox, "rebase", "origin/main")
    check = fastcheck(sandbox)
    assert check.returncode == 11
    assert "check_task_state.py(exit 1)" in check.stderr


@pytest.mark.parametrize("push_rc", [1, 128])
def test_other_push_failure_also_stops(sandbox, push_rc):
    repo, env = sandbox
    prepare_git(sandbox)
    env["PUSH_RC"] = str(push_rc)
    r = shell(sandbox, TAIL_STUBS + block("# push main\n"))
    assert r.returncode == 5
    assert Path(env["TRACE"]).read_text().splitlines() == ["git push origin main"]


@pytest.mark.parametrize("ssh_rc,ci_rc,expected", [(0, 0, 0), (1, 0, 6), (0, 1, 9), (0, 2, 0)])
def test_success_preserves_cloud_then_ci_semantics(sandbox, ssh_rc, ci_rc, expected):
    repo, env = sandbox
    remote = prepare_git(sandbox)
    env.update(SSH_RC=str(ssh_rc), TEST_CI_RC=str(ci_rc))
    r = shell(sandbox, TAIL_STUBS + block("# push main\n"))
    assert r.returncode == expected, r.stdout + r.stderr
    trace = Path(env["TRACE"]).read_text().splitlines()
    assert trace[0] == "git push origin main"
    assert trace[1].startswith("ssh ")
    assert sum(x.startswith("git push") for x in trace) == 1
    assert not any(x.startswith(("git fetch", "git rebase")) for x in trace)
    assert any(x.startswith("ci ") for x in trace) == (ssh_rc == 0)
    if ssh_rc == 0:
        assert trace[-1] == "ci " + git(sandbox, "rev-parse", "HEAD")
    assert git(sandbox, "--git-dir", str(remote), "rev-parse", "main") == git(sandbox, "rev-parse", "HEAD")


@pytest.mark.parametrize("dry,skip,expected", [("0", "0", 11), ("1", "0", 0),
                                             ("0", "1", 0), ("0", "true", 11)])
def test_three_real_failures_continue_under_errexit(sandbox, dry, skip, expected):
    repo, env = sandbox
    p = repo / "CLAUDE.md"
    text = p.read_text()
    assert "全量 58L+31E" in text
    p.write_text(text.replace("全量 58L+31E", "全量 999L+31E", 1))
    p = repo / "docs/ops/machine-check-registry.md"
    lines = p.read_text().splitlines(True)
    victims = [line for line in lines if line.startswith("|") and "scripts/main-merge.sh 3.5 四态对账" in line]
    assert len(victims) == 1
    p.write_text("".join(line for line in lines if line not in victims))
    p = repo / "docs/pending-features-index.md"
    line = next(line for line in p.read_text().splitlines() if line.startswith("| 376 |"))
    p.write_text(p.read_text() + "\n" + line + "\n")
    env.update(DRY_RUN=dry, MAIN_MERGE_SKIP_FASTCHECK=skip, MAIN_MERGE_SKIP_PYTEST="1")
    r = fastcheck(sandbox)
    assert r.returncode == expected, r.stdout + r.stderr
    if skip == "1":
        assert "MAIN_MERGE_SKIP_FASTCHECK=1" in r.stdout
        assert "快检通过" not in r.stdout and "快检 FAIL:" not in r.stderr
    else:
        for name in ("check_ledger.py", "check_gate_registry.py", "check_task_state.py"):
            assert name + "(exit 1)" in r.stderr
        assert ("[dry-run] 快检 FAIL 不阻断" in r.stderr) == (dry == "1")


def test_final_merged_documents_pass_all_three(sandbox):
    r = fastcheck(sandbox)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("快检通过") == 3


def test_document_only_change_still_checked(sandbox):
    repo, env = sandbox
    p = repo / "docs/pending-features-index.md"
    line = next(line for line in p.read_text().splitlines() if line.startswith("| 376 |"))
    p.write_text(p.read_text() + "\n" + line + "\n")
    prefix = 'GIT=docs_git\nMERGE_REF=docs\ndocs_git() { [[ "$1" == "diff" ]]; }\n'
    r = shell(sandbox, prefix + block("# 7.9 L52 pre-merge 全量 pytest(scripts/", "# 7.7 console 洁净度哨兵"))
    assert r.returncode == 11
    assert "scripts/ 无变更 → 跳过全量 pytest" in r.stdout
    assert "check_task_state.py(exit 1)" in r.stderr


def test_dry_run_exit_prevents_commit_push_and_followup(sandbox):
    repo, env = sandbox
    env["DRY_RUN"] = "1"
    # 仅执行 9 步开头的 dry-run 退出块，不执行完整入口(前段 fetch/rebase 有副作用)。
    r = shell(sandbox, block("# 9. commit(自动追加 Co-Authored-By)", 'echo "--- commit + push main ---"') +
              '\necho UNREACHABLE_AFTER_DRYRUN\n')
    assert r.returncode == 0
    assert "跳过 commit + push main" in r.stdout
    assert "UNREACHABLE" not in r.stdout
    assert not Path(env["TRACE"]).exists()
