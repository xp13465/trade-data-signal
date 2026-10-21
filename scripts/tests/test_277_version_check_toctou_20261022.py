# -*- coding: utf-8 -*-
"""#277 §24⑤ 版本一致性校验 TOCTOU 竞态加固的回归测试(2026-10-22)。

背景(实测): `deploy_20261022_0042.log:729-733` 唯一一次 FAIL —— 校验3 先按 HEAD 读源重建(min 用旧源
`0f658507/e44dbcbe`), 之后才读磁盘 min(main-merge 第 10 步 ssh 云上 `git pull` 已换成新值
`22306377/87dbf668`)⇒ 误报「min 与 HEAD 源重建不一致」, 部署段1 终止。10-01~10-22 共 121 轮跑到该校验,
120 PASS / 1 FAIL(= 并发 pull 与校验窗口重叠)。

修法 B1(校验窗口自洽): 只取一次 `git rev-parse HEAD` 并把该 sha 固定用于全部读源; 重建**前**快照 8 个
min 文件 md5(重建后不再读磁盘); 重建+比对后复验 HEAD; HEAD 变了只重试一次(重新固定 sha、重新快照、
重新重建), 仍变才 FAIL 且消息写明「校验期间 HEAD 变化」, 不报误导性的「min 过期/工作区源脏」。

覆盖(证据用例 1-5, 任务书口径):
  1 正常态(真实 git 仓库、干净 HEAD) ⇒ PASS, 输出含 `head=` / `min_snapshot=`
  2 竞态模拟(桩: HEAD A→重建后 B→重试 B 稳定) ⇒ PASS 且**只重试 1 次**(rev-parse 恰好 3 次)
  3 持续变化(A→B→C) ⇒ FAIL, 消息含「校验期间 HEAD 变化」, **不含**「min 过期」
  4 真脏工作区(源脏 + min 由脏源生成) ⇒ 仍 FAIL(原语义), 消息含「工作区源脏」
  5 min 真过期(干净源 + 旧 min) ⇒ FAIL(防误判回归)
  + 真实并发 pull 模拟(重建过程中真提交新 HEAD 且 min 同步更新) ⇒ 重试后 PASS

边界声明(§10.8 七轴之「外部依赖/压缩器」): 本文件**不测**真实 terser/rcssmin 压缩路径——那属外部工具,
由 `test_261_build_min_deps.py`(CSS 真压缩 + 映射一致性)与 CI ③b 步覆盖; 这里把
`build_min._minify_css_content` 换成确定性桩 `b"MIN:" + 源字节`, 焦点收敛到「读源 sha 固定 + 快照时机 +
HEAD 复验/重试」这一本次改动面。选 CSS 配对是因为它不走 terser, 换桩后测试无需网络/无需 npx。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import build_min
import check_version_consistency as cvc

_GIT_ID = ("-c", "user.email=t@example.com", "-c", "user.name=tester")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, timeout=60)


def _fake_css_min(content: bytes) -> bytes:
    """确定性 CSS 压缩桩(替掉外部 rcssmin; 只要求「同源 ⇒ 同产物」)。"""
    return b"MIN:" + content


@pytest.fixture()
def repo_site(tmp_path, monkeypatch):
    """临时 git 仓库 + static-site/ 目录(只有 CSS 两条配对, 其余 6 对源缺失走 skip, 语义与生产一致)。

    同时清掉 GIT_REPO 环境变量(conftest 会 setdefault 成 .env 垫片目录), 否则 `_git_repo_of` 会解析到
    真实仓库而不是本测试的临时仓库。
    """
    monkeypatch.delenv("GIT_REPO", raising=False)
    monkeypatch.setattr(build_min, "_minify_css_content", _fake_css_min)
    repo = tmp_path / "repo"
    site = repo / "static-site"
    site.mkdir(parents=True)
    (site / "style.css").write_text(".a { color: red; }\n", encoding="utf-8")
    (site / "style.min.css").write_text("MIN:.a { color: red; }\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, *_GIT_ID, "commit", "-q", "-m", "base")
    return repo, site


def test_case1_normal_clean_head_pass(repo_site):
    """证据用例 1: 正常态(干净 HEAD、min 正确)⇒ PASS, 且输出带 head=/min_snapshot= 可追溯行。"""
    _repo, site = repo_site
    ok, det = cvc.check3(site)
    assert ok, f"干净仓库应 PASS: {det}"
    assert "head=" in det, f"缺可追溯 head= 行: {det}"
    assert "min_snapshot=" in det, f"缺可追溯 min_snapshot= 行: {det}"
    assert "校验期间 HEAD 变化" not in det


def test_case2_race_simulated_retry_once_pass(repo_site, monkeypatch):
    """证据用例 2: 桩级竞态 —— HEAD A→B, 重试稳定在 B ⇒ PASS, 且只重试 1 次(rev-parse 恰好 3 次)。

    A 的"重建"故意返回错误内容(模拟旧 HEAD 产物), B 的重建返回正确内容 ⇒ 断言最终采用的是重试结果,
    而不是"第一次碰巧也 PASS"。
    """
    _repo, site = repo_site
    sha_a, sha_b = "a" * 40, "b" * 40
    calls: list[str] = []

    def fake_head_sha(_repo):
        seq = [sha_a, sha_b, sha_b]          # 开头 / 复验 / 重试后复验
        val = seq[len(calls)] if len(calls) < len(seq) else sha_b
        calls.append(val)
        return val

    correct = (site / "style.min.css").read_bytes()

    def fake_rebuild(site_dir, _repo, head):
        if head == sha_a:
            return {"static-site/style.min.css": b"BUILT-FROM-OLD-HEAD"}
        return {"static-site/style.min.css": correct}

    monkeypatch.setattr(cvc, "_git_head_sha", fake_head_sha)
    monkeypatch.setattr(cvc, "_rebuild_from_head", fake_rebuild)

    ok, det = cvc.check3(site)
    assert ok, f"HEAD 变化后重试应 PASS: {det}"
    assert len(calls) == 3, f"应只重试 1 次(rev-parse 3 次), 实际 {len(calls)} 次: {calls}"
    assert "已重新固定 sha 重试 1 次" in det, f"缺重试提示: {det}"
    assert sha_b[:12] in det, f"追溯行未指向重试后的 sha: {det}"


def test_case5b_min_file_missing_still_fail(repo_site):
    """改动面边界: 「源在、min 文件缺失」分支仍 FAIL(该分支改从快照取 md5, 语义不得变松)。"""
    _repo, site = repo_site
    (site / "style.min.css").unlink()
    ok, det = cvc.check3(site)
    assert not ok, f"缺 min 版应 FAIL: {det}"
    assert "缺 min 版" in det, f"消息应指出缺 min 版: {det}"


def test_case3_head_keeps_moving_fail_with_head_change_message(repo_site, monkeypatch):
    """证据用例 3: 三次 HEAD 各不相同 ⇒ FAIL, 消息写明「校验期间 HEAD 变化」, 且不报「min 过期」。"""
    _repo, site = repo_site
    seq = ["a" * 40, "b" * 40, "c" * 40]
    calls: list[int] = []

    def fake_head_sha(_repo):
        val = seq[min(len(calls), len(seq) - 1)]
        calls.append(len(calls))
        return val

    monkeypatch.setattr(cvc, "_git_head_sha", fake_head_sha)

    ok, det = cvc.check3(site)
    assert not ok, f"HEAD 持续变化应 FAIL: {det}"
    assert "校验期间 HEAD 变化" in det, f"消息未写明 HEAD 变化: {det}"
    assert "疑似并发 git pull" in det, f"消息未给出并发 pull 线索: {det}"
    assert "min 过期" not in det, f"不许再输出误导性的 min 过期: {det}"
    assert "工作区源脏" not in det, f"不许输出误导性的工作区源脏: {det}"
    assert len(calls) == 3, f"只应重试 1 次(rev-parse 3 次), 实际 {len(calls)} 次"


def test_case4_dirty_worktree_still_fail(repo_site):
    """证据用例 4: 真脏工作区(源与 HEAD blob 不同, min 由脏源生成)⇒ 仍 FAIL(原语义不变)。"""
    _repo, site = repo_site
    (site / "style.css").write_text(".a { color: blue; }\n", encoding="utf-8")          # 脏源(未 commit)
    (site / "style.min.css").write_text("MIN:.a { color: blue; }\n", encoding="utf-8")  # min 由脏源生成
    ok, det = cvc.check3(site)
    assert not ok, f"脏工作区应 FAIL: {det}"
    assert "工作区源脏" in det, f"消息应指出工作区源脏: {det}"
    assert "style.min.css" in det


def test_case5_stale_min_still_fail(repo_site):
    """证据用例 5: 干净源 + 旧 min ⇒ FAIL(防「修 TOCTOU 把真检查改松」的回归)。"""
    _repo, site = repo_site
    (site / "style.min.css").write_text("MIN:stale\n", encoding="utf-8")
    ok, det = cvc.check3(site)
    assert not ok, f"min 过期应 FAIL: {det}"
    assert "min 内容与 git HEAD 源重建不一致" in det, f"消息应指出内容不一致: {det}"


def test_real_head_advance_during_rebuild_retries_and_passes(repo_site, monkeypatch):
    """真并发 pull 复刻: 重建过程中真提交新 HEAD(源+min 一起变)⇒ 重试一次后 PASS。

    与用例 2 的区别: 不打桩 rev-parse/重建,**真**在里程中途推进 git HEAD(等价 main-merge 第 10 步
    ssh 云上 `git pull` Fast-forward), 验证「重新固定 sha + 重新快照」真的消除了旧源/新 min 错位误报。
    """
    repo, site = repo_site
    real_rebuild = cvc._rebuild_from_head
    state = {"done": False}

    def racing_rebuild(site_dir, repo_arg, head):
        out = real_rebuild(site_dir, repo_arg, head)
        if not state["done"]:
            state["done"] = True
            # 并发 pull 落地: 新 commit 里源与 min 同步换新
            (site / "style.css").write_text(".a { color: green; }\n", encoding="utf-8")
            (site / "style.min.css").write_text("MIN:.a { color: green; }\n", encoding="utf-8")
            _git(repo, "add", "-A")
            _git(repo, *_GIT_ID, "commit", "-q", "-m", "pull: fast-forward")
        return out

    monkeypatch.setattr(cvc, "_rebuild_from_head", racing_rebuild)
    ok, det = cvc.check3(site)
    assert ok, f"并发 pull 落在窗口内应重试后 PASS(不得误报 min 过期): {det}"
    assert "已重新固定 sha 重试 1 次" in det, f"缺重试提示: {det}"