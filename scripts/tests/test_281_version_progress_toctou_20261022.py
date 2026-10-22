# -*- coding: utf-8 -*-
"""#281 check_version_progress 同族竞态(固定 sha)回归测试(2026-10-22)。

背景: 原实现 `rev-parse HEAD` 与 `rev-parse HEAD^` 是两次独立调用(实测窗口 ~2.42s, 期间
约 320 次 git show)。并发 `git pull` 落地时 head/parent 可能来自两个不同提交, 判定输入
不自洽, **误判方向 = stale PASS**(该拦的版本倒退被放过, 比误报更危险)。
修法(复用 #277 check_version_consistency 思路): head 只取一次 → parent 由固定 sha 派生
→ 磁盘(版本串/源文件 md5)窗口开始一次性快照 → 校验后复验 HEAD; 变了只重试 1 次, 仍变
才 FAIL 并明说「校验期间 HEAD 变化」。A/B 判定语义不变。

证据用例:
  ① 正常干净仓库 ⇒ PASS(输出含 HEAD / 快照行)
  ② 窗口内 HEAD A→B ⇒ 重新固定 sha 重试 1 次后 PASS(rev-parse 恰好 3 次)
  ③ 窗口内 HEAD 持续变化(A→B→C)⇒ FAIL「校验期间 HEAD 变化」, 不给 stale PASS
  ④ 真版本倒退 ⇒ 仍 FAIL(原语义不变)
  ⑤ 真净回退(B 任务)⇒ 仍 FAIL(原语义不变)
  M1 复验钉住: 去掉"校验后复验 HEAD" ⇒ 用例②的红(变异证据)
  M2 固定 sha 钉住: parent 改用实时 HEAD 派生 ⇒ 首次窗口的 first-parent 变成新 HEAD 的父,
     用例 M2 断言旧 parent 曾出现 ⇒ 红(变异证据)

跑法: python3 -m pytest -q scripts/tests/test_281_version_progress_toctou_20261022.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).absolute().parent.parent))
import check_version_progress as cvp  # noqa: E402

_GIT_ID = ("-c", "user.email=t@example.com", "-c", "user.name=tester")


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       check=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def _commit(repo: Path, site: Path, version: str, app_text: str, msg: str) -> str:
    (site / "index.html").write_text(
        f'<script src="./app.min.js?v={version}"></script>\n', encoding="utf-8")
    (site / "app.js").write_text(app_text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, *_GIT_ID, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo_site(tmp_path):
    """3 个提交的小仓(C0 a0 → C1 a1 → C2 a2); 只有 app.js 一个源(其余源缺失 = skip, 语义同生产)。"""
    repo = tmp_path / "repo"
    site = repo / "static-site"
    site.mkdir(parents=True)
    _git(repo, "init", "-q")
    c0 = _commit(repo, site, "20261022-a0", "const v='v0';\n", "c0")
    c1 = _commit(repo, site, "20261022-a1", "const v='v1';\n", "c1")
    c2 = _commit(repo, site, "20261022-a2", "const v='v2';\n", "c2")
    return repo, site, {"c0": c0, "c1": c1, "c2": c2}


def _run(monkeypatch, repo: Path, site: Path):
    monkeypatch.setattr(sys, "argv", [
        "check_version_progress.py", "--site-dir", str(site),
        "--repo", str(repo), "--deploy-mode",
    ])
    return cvp.main()


def _fake_head(monkeypatch, seq):
    """按序返回 head sha(耗尽后重复最后一个), 记录调用次数。"""
    calls = []

    def fake(_repo):
        v = seq[min(len(calls), len(seq) - 1)]
        calls.append(v)
        return v

    monkeypatch.setattr(cvp, "_head_sha", fake)
    return calls


# ══════════════════════════════════════════════════════════════════
# ① 正常态 ⇒ PASS
# ══════════════════════════════════════════════════════════════════
def test_case1_normal_clean_head_pass(repo_site, monkeypatch, capsys):
    repo, site, shas = repo_site
    rc = _run(monkeypatch, repo, site)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[PASS] 任务 A" in out and "[PASS] 任务 B" in out
    assert f"HEAD     : {shas['c2'][:10]}" in out
    assert f"first-parent: {shas['c1'][:10]}" in out
    assert "快照" in out and "窗口内不再读磁盘" in out


# ══════════════════════════════════════════════════════════════════
# ② 窗口内 HEAD A→B ⇒ 重试 1 次后 PASS
# ══════════════════════════════════════════════════════════════════
def test_case2_head_moves_once_retry_pass(repo_site, monkeypatch, capsys):
    repo, site, shas = repo_site
    calls = _fake_head(monkeypatch, [shas["c1"], shas["c2"], shas["c2"]])
    rc = _run(monkeypatch, repo, site)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert len(calls) == 3, f"应只重试 1 次(rev-parse 3 次), 实际 {len(calls)}: {calls}"
    assert "已重新固定 sha 并重新快照, 重试 1 次" in out, out
    assert "已重新固定 sha 重试 1 次" in out, out
    # 第一轮用固定 C1 的父 C0; 重试用 C2 的父 C1
    assert f"first-parent: {shas['c0'][:10]}" in out
    assert f"first-parent: {shas['c1'][:10]}" in out


# ══════════════════════════════════════════════════════════════════
# ③ HEAD 持续变化 ⇒ FAIL, 不给 stale PASS
# ══════════════════════════════════════════════════════════════════
def test_case3_head_keeps_moving_no_stale_pass(repo_site, monkeypatch, capsys):
    repo, site, shas = repo_site
    calls = _fake_head(monkeypatch, [shas["c1"], shas["c2"], shas["c0"]])
    rc = _run(monkeypatch, repo, site)
    cap = capsys.readouterr()
    assert rc == 1, cap.out
    assert "校验期间 HEAD 变化" in cap.err, cap.err
    assert "已重试 1 次仍不稳定" in cap.err
    assert "✓ 版本串倒退/净回退校验通过" not in cap.out, "不得给出可能过期的 PASS"
    assert len(calls) == 3, calls


# ══════════════════════════════════════════════════════════════════
# ④ 真版本倒退 ⇒ 仍 FAIL(A 任务原语义)
# ══════════════════════════════════════════════════════════════════
def test_case4_real_version_regression_still_fail(repo_site, monkeypatch, capsys):
    repo, site, _shas = repo_site
    _commit(repo, site, "20261022-a1", "const v='regress';\n", "c3 regression")
    rc = _run(monkeypatch, repo, site)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "[FAIL] 任务 A: 版本串倒退哨兵" in out
    assert "当前 20261022-a1 < 最近祖先天花板 20261022-a2" in out


# ══════════════════════════════════════════════════════════════════
# ⑤ 真净回退 ⇒ 仍 FAIL(B 任务原语义)
# ══════════════════════════════════════════════════════════════════
def test_case5_real_net_rollback_still_fail(repo_site, monkeypatch, capsys):
    """版本串不前进(仍 a2) + 内容回到 C0 ⇒ B 任务净回退。"""
    repo, site, _shas = repo_site
    _commit(repo, site, "20261022-a2", "const v='v0';\n", "c3 rollback content")
    rc = _run(monkeypatch, repo, site)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "[FAIL] 任务 B: merge 净回退校验" in out
    assert "净回退" in out


# ══════════════════════════════════════════════════════════════════
# M1/M2 变异盲区钉住(去掉修复 ⇒ 本文件必红)
# ══════════════════════════════════════════════════════════════════
def test_m1_head_must_be_rechecked_after_checks(repo_site, monkeypatch, capsys):
    """M1: 校验后必须复验 HEAD —— 去掉复验则不会重试, 本用例断言的重试行消失 ⇒ 红。"""
    repo, site, shas = repo_site
    _fake_head(monkeypatch, [shas["c1"], shas["c2"], shas["c2"]])
    rc = _run(monkeypatch, repo, site)
    out = capsys.readouterr().out
    assert rc == 0
    assert "已重新固定 sha 并重新快照, 重试 1 次" in out


def test_m2_parent_must_derive_from_fixed_head(repo_site, monkeypatch, capsys):
    """M2: parent 必须由**固定 sha** 派生。

    固定 head = C1(第一轮) ⇒ 其父 = C0, 输出必须出现 first-parent C0。
    若实现改成 `_parent_of(repo, 实时 HEAD)`(HEAD=C2)⇒ 首轮父就是 C1, C0 永不会出现 ⇒ 红。
    """
    repo, site, shas = repo_site
    _fake_head(monkeypatch, [shas["c1"], shas["c2"], shas["c2"]])
    rc = _run(monkeypatch, repo, site)
    out = capsys.readouterr().out
    assert rc == 0
    assert f"first-parent: {shas['c0'][:10]}" in out, \
        "固定 sha 的首轮父提交未出现(parent 疑似取自实时 HEAD):\n" + out