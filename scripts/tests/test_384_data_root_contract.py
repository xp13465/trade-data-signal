#!/usr/bin/env python3
"""#384 批1 数据根契约 — code_root()/data_root()/_derive_data_root() 单元测试(2026-11-27)。

设计权威: /tmp/repo-unify-design-20261127.md §1.3(派生算法)/§1.4(读侧守卫)/§2.1(证据用例)。

覆盖:
  1. 派生三形态: 候选 A(经 <数据根>/scripts symlink 调用)/ 候选 B(兄弟 trade-data)/ 单仓;
  2. env REPO 指向数据树 → 采用; 指向代码仓 + 独立部署树存在 → SystemExit(响亮失败);
  3. 真单仓 REPO==代码根 → 允许;
  4. sentiment_db() 默认根 = data_root();
  5. 模块默认 MAIN_REPO 不再是写死 mac 字面量(起源于 #383 遗留 B)。

零网络、全 tmp_path。**任何触发读侧守卫的用例先打桩 `_alert_guard_blocked`(L48:
2026-11-27 14:05 设计阶段曾因直接调守卫真发过一次 critical 告警)。**
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import pick_repo  # noqa: E402


def _mk_dual_tree(tmp_path: Path) -> tuple[Path, Path]:
    """造双树布局: C(代码根) + D(数据根), 且 D/scripts -> C/scripts(symlink)。"""
    code = tmp_path / "code" / "trade-data-signal"
    data = tmp_path / "code" / "trade-data"
    (code / "scripts").mkdir(parents=True)
    (code / "scripts" / "pick_repo.py").write_text("", encoding="utf-8")
    data.mkdir(parents=True)
    (data / "scripts").symlink_to(code / "scripts")
    return code, data


def _stub_alert(monkeypatch) -> list[str]:
    """打桩守卫告警(L48 零外发), 返回记录列表 —— 只记录不发送。"""
    fired: list[str] = []
    monkeypatch.setattr(pick_repo, "_alert_guard_blocked", lambda m: fired.append(m))
    return fired


# ── 派生三形态(§1.3) ────────────────────────────────────────────────────────────

def test_derive_candidate_a_symlink(tmp_path):
    """候选 A: 经 <D>/scripts symlink 调用 → 推导出 D。"""
    code, data = _mk_dual_tree(tmp_path)
    assert pick_repo._derive_data_root(code, data) == data


def test_derive_candidate_b_sibling(tmp_path):
    """候选 B: 代码根的兄弟目录 trade-data 存在 → 推导出该兄弟目录。"""
    code = tmp_path / "trade"
    (code / "scripts").mkdir(parents=True)
    sibling = tmp_path / "trade-data"
    sibling.mkdir()
    assert pick_repo._derive_data_root(code, code) == sibling


def test_derive_single_repo(tmp_path):
    """真单仓(无 symlink、无兄弟 trade-data)→ 回退代码根本身。"""
    code = tmp_path / "solo"
    (code / "scripts").mkdir(parents=True)
    assert pick_repo._derive_data_root(code, code) == code


def test_derive_symlinked_ancestor_not_candidate_a(tmp_path):
    """#208 修正回归: 祖先目录是 symlink 但 scripts 本身是实体目录 → 不得误判为候选 A。"""
    real = tmp_path / "real"
    code = real / "trade"
    (code / "scripts").mkdir(parents=True)
    sibling = real / "trade-data"
    sibling.mkdir()
    link_parent = tmp_path / "link"
    link_parent.symlink_to(real)
    invoked = link_parent / "trade"  # 经祖先 symlink 的路径, scripts 本身不是 symlink
    assert pick_repo._derive_data_root(code, invoked) == sibling


# ── 读侧守卫(§1.4) ────────────────────────────────────────────────────────────

def test_env_repo_data_tree_wins(tmp_path, monkeypatch):
    """env REPO 指向数据树 → 直接采用, 且不触发告警。"""
    code, data = _mk_dual_tree(tmp_path)
    fired = _stub_alert(monkeypatch)
    monkeypatch.setenv("REPO", str(data))
    monkeypatch.setenv("GIT_REPO", str(code))
    assert pick_repo.data_root() == data.resolve()
    assert fired == [], f"数据树场景不应触发守卫告警, 实际 {fired}"


def test_env_repo_code_repo_two_tree_raises(tmp_path, monkeypatch):
    """env REPO 指向代码仓 + 独立部署树存在 → SystemExit(响亮失败, 不再静默读陈旧库)。"""
    code, data = _mk_dual_tree(tmp_path)
    fired = _stub_alert(monkeypatch)
    monkeypatch.setenv("REPO", str(code))
    monkeypatch.setenv("GIT_REPO", str(code))
    # 模块常量 MAIN_REPO 在 import 时求值, 这里显式指向本用例的独立部署树(模拟生产布局)
    monkeypatch.setattr(pick_repo, "MAIN_REPO", data)
    with pytest.raises(SystemExit) as ei:
        pick_repo.data_root()
    msg = str(ei.value)
    assert "解析到 git 仓" in msg and "而非部署源树" in msg, msg
    assert fired, "守卫阻断必须走告警路径(此处打桩记录, 不发真实告警)"


def test_single_repo_repo_equals_code_root_ok(tmp_path, monkeypatch):
    """真单仓(无独立部署树)时 REPO == 代码根 合法, 不告警。"""
    solo = tmp_path / "solo"
    (solo / "scripts").mkdir(parents=True)
    fired = _stub_alert(monkeypatch)
    monkeypatch.setenv("REPO", str(solo))
    monkeypatch.setenv("GIT_REPO", str(solo))
    monkeypatch.setattr(pick_repo, "MAIN_REPO", solo)
    assert pick_repo.data_root() == solo.resolve()
    assert fired == []


# ── 代码根与 sentiment_db 默认根 ───────────────────────────────────────────────

def test_code_root_prefers_env_git_repo(tmp_path, monkeypatch):
    """code_root() 优先 env GIT_REPO; pick_git_repo() 兼容委托同一结果。"""
    code, _ = _mk_dual_tree(tmp_path)
    monkeypatch.setenv("GIT_REPO", str(code))
    assert pick_repo.code_root() == code.resolve()
    assert pick_repo.pick_git_repo() == code.resolve()


def test_sentiment_db_follows_data_root(tmp_path, monkeypatch):
    """sentiment_db() 无显式 repo 时根 = data_root(); 显式 repo 仍拼该树(#383 兼容)。"""
    chosen = tmp_path / "chosen"
    monkeypatch.setattr(pick_repo, "data_root", lambda: chosen)
    assert pick_repo.sentiment_db() == chosen / "data" / "sentiment.db"
    explicit = tmp_path / "explicit"
    assert pick_repo.sentiment_db(explicit) == explicit / "data" / "sentiment.db"


# ── #383 遗留 B: MAIN_REPO 默认不再是 mac 字面量 ───────────────────────────────

def test_main_repo_default_not_mac_literal():
    """源码不再写死 mac 默认值, 且模块默认 == 布局派生数据根(env 清空下)。"""
    src = Path(pick_repo.__file__).read_text(encoding="utf-8")
    assert 'os.environ.get("MAIN_REPO", "/Users' not in src, "MAIN_REPO 默认值仍是写死 mac 路径"
    assert "_DERIVED_DATA_ROOT" in src, "MAIN_REPO 默认应取布局派生值"

    env = {k: v for k, v in os.environ.items() if k not in ("REPO", "GIT_REPO", "MAIN_REPO")}
    env["PYTHONPATH"] = str(SCRIPTS) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [sys.executable, "-c", "import pick_repo; print(pick_repo.MAIN_REPO)"],
        cwd=str(SCRIPTS), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    got = Path(proc.stdout.strip())
    expected = pick_repo._derive_data_root(pick_repo.CODE_ROOT, pick_repo.INVOKED_ROOT)
    assert got == expected, f"无 env 时默认 MAIN_REPO 应=派生数据根 {expected}, 实际 {got}"
