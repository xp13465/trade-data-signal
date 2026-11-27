#!/usr/bin/env python3
"""#383 pick_db 家族收敛到部署数据树单源 — 单元测试(2026-11-27)。

背景: pick_db 家族(gen_daily_brief / brief_ledger / aggregate_shadow / ab_direction_anchor /
replay_direction_anchor)原先遍历 candidate_repos() 逐个打开 data/sentiment.db 读
MAX(date) 挑最新, 把 git 仓侧陈旧镜像(云上 C 10-28 起冻结)也当数据源, 每日被只读打开。
现收敛为 pick_repo.sentiment_db() 单源 = (repo or data_root()) / "data" / "sentiment.db"
(#384 批1 起默认根由 pick_repo() 改为 data_root())。

本文件固化两条证据用例(调研 /tmp/repo-paths-research-20261127.md §3):
  1. 排除代码仓: env 的代码仓侧库 MAX(date) 更新也不得被选中;
  2. 无 env 回退: 跟随 data_root() 的数据根。

零网络、零生产 DB 写(全部落在 pytest tmp_path)。
"""
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import pick_repo  # noqa: E402


def _make_db(root: Path, max_date: str) -> Path:
    """在 <root>/data/sentiment.db 造一个只含 daily_metric(date) 的最小库。"""
    db = root / "data" / "sentiment.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE daily_metric (date TEXT, metric_id TEXT, value REAL)")
        conn.execute("INSERT INTO daily_metric VALUES (?, 'a_turnover_mean', 1.0)", (max_date,))
        conn.commit()
    finally:
        conn.close()
    return db


def test_excludes_git_repo_even_if_newer(tmp_path, monkeypatch):
    """用例 1: 代码仓侧库更新(MAX 更大)也不得被选中 —— 只认部署数据树 REPO。"""
    data_repo = tmp_path / "trade-data"
    git_repo = tmp_path / "trade"
    data_db = _make_db(data_repo, "20260101")
    git_db = _make_db(git_repo, "20261231")  # 代码仓侧"更新", 旧逻辑会选它

    monkeypatch.setenv("REPO", str(data_repo))
    monkeypatch.setenv("GIT_REPO", str(git_repo))
    monkeypatch.setenv("MAIN_REPO", str(data_repo))

    got = pick_repo.sentiment_db()
    assert got == data_db, f"应只认部署数据树 {data_db}, 实际 {got}"
    assert got != git_db


def test_no_env_falls_back_to_data_root(tmp_path, monkeypatch):
    """用例 2: 无显式 repo 时跟随数据根(默认入口 = data_root(), #384 批1 起)。"""
    chosen = tmp_path / "c"
    chosen.mkdir()

    monkeypatch.delenv("REPO", raising=False)
    monkeypatch.delenv("GIT_REPO", raising=False)
    monkeypatch.delenv("MAIN_REPO", raising=False)
    monkeypatch.setattr(pick_repo, "data_root", lambda: chosen)

    assert pick_repo.sentiment_db() == chosen / "data" / "sentiment.db"


def test_explicit_repo_param_wins(tmp_path):
    """显式传入 repo 时直接拼该树的 data/sentiment.db(gen_daily_brief.pick_db(repo) 依赖此路径)。"""
    repo = tmp_path / "explicit"
    assert pick_repo.sentiment_db(repo) == repo / "data" / "sentiment.db"


def test_pick_db_delegates_to_single_root(tmp_path, monkeypatch):
    """gen_daily_brief.pick_db(repo) 保留签名但委托单源(3 个生产调用点兼容)。"""
    gen = pytest.importorskip("gen_daily_brief")
    repo = tmp_path / "tradedata"
    got = gen.pick_db(repo)
    assert got == repo / "data" / "sentiment.db"
