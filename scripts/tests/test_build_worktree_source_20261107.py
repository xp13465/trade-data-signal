"""Real temporary Git worktrees/refs, injected compiler only; no network/min output in repo."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

import build_min
import check_version_consistency as cvc


def _git(repo, *args):
    # No inherited Git routing, credentials, hooks, signing or personal config.
    result = subprocess.run(
        ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@invalid.example",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
         "-C", str(repo), *args],
        env={"PATH": os.defpath, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        check=True, capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip()


def _sources(root, label):
    contents = {}
    for source, target in build_min.PAIRS:
        raw = (f"/* {label}:{Path(source).name} */\n.a {{ color: red; }}\n" if source.endswith(".css") else
               f"/* {label}:{Path(source).name} */\nconst fixture = '{label}';\n").encode()
        (root / source).parent.mkdir(parents=True, exist_ok=True)
        (root / source).write_bytes(raw)
        (root / target).write_bytes(b"MIN:" + raw)
        contents[target] = b"MIN:" + raw
    return contents


@pytest.fixture
def linked(tmp_path, monkeypatch):
    for name in ("GIT_REPO", "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(name, raising=False)
    primary = tmp_path / "primary-fixture"
    primary.mkdir()
    _git(primary, "init", "-q")
    _sources(primary, "primary-HEAD")
    _git(primary, "add", "-A")
    _git(primary, "commit", "-qm", "fixture primary")
    primary_head = _git(primary, "rev-parse", "HEAD")
    worktree = tmp_path / "linked-fixture"
    _git(primary, "worktree", "add", "-q", "-b", "fixture-linked", str(worktree))
    expected = _sources(worktree, "linked-HEAD")
    site = worktree / "static-site"
    (site / "index.html").write_text('<script src="./app.min.js?v=20261107-a658"></script>')
    (site / "sw.js").write_text("const CACHE_VERSION = 'v6-20261107-a658';\n")
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-qm", "fixture linked")
    head = _git(worktree, "rev-parse", "HEAD")
    assert head != primary_head and (worktree / ".git").is_file()
    # Both trees are deliberately dirty and different from the linked HEAD.
    for src, _ in build_min.PAIRS:
        (worktree / src).write_bytes(b"DIRTY-LINKED-SOURCE")
        (primary / src).write_bytes(b"DO-NOT-USE-PRIMARY-SOURCE")
    monkeypatch.setattr(build_min, "BASE", str(worktree))
    monkeypatch.setattr(build_min, "_minify_js_content", lambda content, name: (b"MIN:" + content, None))
    monkeypatch.setattr(build_min, "_minify_css_content", lambda content: b"MIN:" + content)
    # Only real Git may use a subprocess; compiler/network calls are prohibited.
    original_run = subprocess.run
    def git_only(command, *args, **kwargs):
        assert command[0] == "git", "unexpected non-Git subprocess"
        return original_run(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", git_only)
    return worktree, site, head, expected


@pytest.mark.parametrize("via_env", [False, True])
def test_resolvers_validate_linked_git_file(linked, monkeypatch, tmp_path, via_env):
    worktree, site, head, _ = linked
    if via_env:
        monkeypatch.setenv("GIT_REPO", str(worktree))
        monkeypatch.setattr(build_min, "BASE", str(tmp_path / "no-repo"))
    assert Path(build_min._resolve_git_repo()).resolve() == worktree.resolve()
    assert Path(cvc._git_repo_of(site)).resolve() == worktree.resolve()
    assert cvc._git_head_sha(cvc._git_repo_of(site)) == head


def test_fake_git_file_is_not_accepted_without_rev_parse(linked, monkeypatch, tmp_path):
    worktree, site, _, _ = linked
    fake = tmp_path / "fake-repo"
    fake.mkdir()
    (fake / ".git").write_text("gitdir: /does-not-exist\n")
    monkeypatch.setenv("GIT_REPO", str(fake))
    assert Path(build_min._resolve_git_repo()).resolve() == worktree.resolve()
    assert Path(cvc._git_repo_of(site)).resolve() == worktree.resolve()


def test_dirty_source_builds_all_eight_from_real_pinned_head(linked, monkeypatch):
    worktree, _, head, expected = linked
    seen = []
    original = build_min._read_source
    def observe(src_rel, base=build_min.BASE, repo=None, head=None):
        seen.append(head)
        content, source = original(src_rel, base=base, repo=repo, head=head)
        assert source.startswith("git HEAD")
        assert b"DIRTY" not in content and b"PRIMARY" not in content
        return content, source
    monkeypatch.setattr(build_min, "_read_source", observe)
    actual = build_min.build_pairs_in_memory(base=worktree, repo=build_min._resolve_git_repo(), head=head)
    assert actual == expected and len(actual) == 8
    assert seen == [head] * 8


def test_checker_cli_checks_eight_and_dirty_min_really_fails(linked, monkeypatch, capsys):
    _, site, head, _ = linked
    monkeypatch.setattr(sys, "argv", ["checker", "--site-dir", str(site), "--checks", "3"])
    assert cvc.main() == 0
    output = capsys.readouterr().out
    assert "映射 8 对" in output and "0 对源缺失/重建跳过" in output and head[:12] in output
    (site / "app.min.js").write_bytes(b"MIN:DIRTY-LINKED-SOURCE")
    assert cvc.main() == 1
    output = capsys.readouterr().out
    assert "共 8 对映射" in output and "app.min.js" in output and "[FAIL]" in output


def test_missing_min_is_a_real_failure_in_linked_worktree(linked):
    _, site, _, _ = linked
    (site / "lab.min.css").unlink()
    passed, detail = cvc.check3(site)
    assert not passed and "缺 min 版" in detail and "lab.min.css" in detail


def test_pinned_build_does_not_switch_sources_after_real_ref_moves(linked, monkeypatch):
    worktree, _, head, expected = linked
    moved = []
    original = build_min._minify_js_content
    def advance(content, name):
        if not moved:
            _sources(worktree, "next-linked-HEAD")
            _git(worktree, "add", "-A")
            _git(worktree, "commit", "-qm", "advance actual fixture ref")
            moved.append(_git(worktree, "rev-parse", "HEAD"))
        return original(content, name)
    monkeypatch.setattr(build_min, "_minify_js_content", advance)
    actual = build_min.build_pairs_in_memory(base=worktree, repo=str(worktree), head=head)
    assert moved and moved[0] != head
    assert len(actual) == 8 and actual == expected


def test_non_git_data_root_keeps_legal_missing_source_skip(tmp_path, monkeypatch):
    site = tmp_path / "data-fixture/static-site"
    site.mkdir(parents=True)
    monkeypatch.delenv("GIT_REPO", raising=False)
    monkeypatch.setattr(build_min, "BASE", str(site.parent))
    assert build_min._resolve_git_repo() is None and cvc._git_repo_of(site) is None
    assert build_min.build_pairs_in_memory(base=site.parent) == {}
    passed, detail = cvc.check3(site)
    assert passed and "8 对源缺失/重建跳过" in detail


def test_non_git_existing_source_uses_correct_fallback_base(tmp_path, monkeypatch):
    root = tmp_path / "non-git-fixture"
    expected = _sources(root, "non-git-source")
    site = root / "static-site"
    monkeypatch.delenv("GIT_REPO", raising=False)
    monkeypatch.setattr(build_min, "BASE", str(root))
    monkeypatch.setattr(build_min, "_minify_js_content", lambda content, name: (b"MIN:" + content, None))
    monkeypatch.setattr(build_min, "_minify_css_content", lambda content: b"MIN:" + content)
    passed, detail = cvc.check3(site)
    assert len(expected) == 8 and passed and "映射 8 对" in detail
    (site / "common.min.js").write_bytes(b"STALE")
    passed, detail = cvc.check3(site)
    assert not passed and "common.min.js" in detail
