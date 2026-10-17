# -*- coding: utf-8 -*-
"""#205-R1 —— `restore-large-json.sh` 恢复默认路径改「随 REPO 推导」自验(2026-10-17)。

依据(用户 2026-10-17 拍板,选项②;推翻 2026-09-25 mac 常量默认):
  · 病灶:恢复目标默认 = mac 常量 `/Users/linhuichen/code/trade-data` ⇒ **云上裸调用**时该路径
    在云上不存在,恢复到错位/失败(与 lib/repo_paths.sh 立 lib 的 #205 动机同源)。
  · 改法:三级回退 `① STATICDATA_REPO > ② 随 REPO/GIT_REPO 推导 > ③ mac 常量末位兜底`
    (照 scripts/upload_r2.py:3009 `_large_json_staticdata_repo` 模式)。

探针纪律(§18 L50 / memory probe-harness-must-not-exec-prod-scripts):本文件**static-only**
  —— 从 `.sh` 内嵌 python heredoc **AST 提取** `_default_data_repo` 与 `DEFAULT_PRODUCTION_REPO`
  **单个符号**后 exec(只 exec 那两个片段, 绝 source/exec 脚本主体、绝不调 R2/恢复主体)。
  零网络、零 R2、零落盘。

跑法: python3 -m pytest -q scripts/tests/test_205_r1_restore_default_path_20261017.py
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
SH = ROOT / "scripts" / "restore-large-json.sh"

_N = [0]


def _chk(cond, msg=""):
    _N[0] += 1
    assert cond, msg


def _heredoc_py() -> str:
    text = SH.read_text(encoding="utf-8")
    m = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF\n", text, re.S)
    assert m, "未找到 restore-large-json.sh 的 python heredoc"
    return m.group(1)


def _load_helper():
    """AST 提取 DEFAULT_PRODUCTION_REPO 赋值 + _default_data_repo 函数, 仅 exec 这两段。"""
    src = _heredoc_py()
    tree = ast.parse(src)
    name, fn = None, None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "DEFAULT_PRODUCTION_REPO" for t in node.targets):
            name = ast.get_source_segment(src, node)
        if isinstance(node, ast.FunctionDef) and node.name == "_default_data_repo":
            fn = ast.get_source_segment(src, node)
    assert name and fn, "未提取到 DEFAULT_PRODUCTION_REPO / _default_data_repo(源码结构变更?)"
    ns: dict = {}
    exec("import os\n" + name + "\n" + fn + "\n", ns)  # noqa: S102 —— 只 exec 提取出的纯函数+常量
    return ns["DEFAULT_PRODUCTION_REPO"], ns["_default_data_repo"]


MAC_CONST, _default_data_repo = _load_helper()


def _clear(monkeypatch, *keys):
    for k in keys:
        monkeypatch.delenv(k, raising=False)


# ══════════ ① STATICDATA_REPO 优先(显式覆盖/测试用) ══════════
def test_01_staticdata_repo_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("STATICDATA_REPO", "/x/staticdata-override")
    monkeypatch.setenv("REPO", "/y/prod-data")
    _chk(_default_data_repo() == "/x/staticdata-override",
         "STATICDATA_REPO 应最高优先")


# ══════════ ② GIT_REPO 兄弟 trade-data 优先于 REPO ══════════
def test_02_derive_from_git_repo_sibling(monkeypatch, tmp_path):
    _clear(monkeypatch, "STATICDATA_REPO")
    code = tmp_path / "code"
    prod = code / "trade-data"
    (prod / "data").mkdir(parents=True)
    monkeypatch.setenv("GIT_REPO", str(code / "trade-data-signal"))
    monkeypatch.setenv("REPO", "/nonexistent/repo")
    _chk(_default_data_repo() == str(prod),
         f"应推 GIT_REPO 兄弟 trade-data, 得 {_default_data_repo()}")


# ══════════ ③ 兄弟缺 → 回退 REPO 本身(含 data/ 判据) ══════════
def test_03_fallback_to_repo(monkeypatch, tmp_path):
    _clear(monkeypatch, "STATICDATA_REPO")
    prod = tmp_path / "prod-trade-data"
    (prod / "data").mkdir(parents=True)
    monkeypatch.setenv("GIT_REPO", str(tmp_path / "no-sibling-here" / "trade-data-signal"))
    monkeypatch.setenv("REPO", str(prod))
    _chk(_default_data_repo() == str(prod),
         f"兄弟缺时应回退 REPO, 得 {_default_data_repo()}")


# ══════════ ④ 推导全不成立 → mac 常量末位兜底(不误指 dev/worktree) ══════════
def test_04_mac_const_last_resort(monkeypatch, tmp_path):
    _clear(monkeypatch, "STATICDATA_REPO")
    # worktree-like: REPO=某个没有 data/ 的目录; GIT_REPO 兄弟也不存在
    dev = tmp_path / "worktree"
    dev.mkdir()
    monkeypatch.setenv("REPO", str(dev))
    monkeypatch.setenv("GIT_REPO", str(tmp_path / "wt" / "trade-data-signal"))
    _chk(_default_data_repo() == MAC_CONST,
         f"推导都不成立应落 mac 常量, 得 {_default_data_repo()}")


def test_05_mac_const_when_both_unset(monkeypatch):
    _clear(monkeypatch, "STATICDATA_REPO", "REPO", "GIT_REPO")
    _chk(_default_data_repo() == MAC_CONST, f"env 全空应落 mac 常量, 得 {_default_data_repo()}")


def test_06_mac_const_value_unchanged():
    _chk(MAC_CONST == "/Users/linhuichen/code/trade-data",
         f"末位兜底常量应保持 mac 生产路径, 得 {MAC_CONST}")


# ══════════ ⑦ 两处使用点都走 helper(单一实现, 防第二份漂移) ══════════
def test_07_both_use_sites_call_helper():
    text = SH.read_text(encoding="utf-8")
    _chk(text.count("_default_data_repo()") == 3,
         f"_default_data_repo() 应出现 3 次(定义内 1 次调用点? 实为 2 个使用点), 实得 {text.count('_default_data_repo()')}")
    _chk('os.environ.get("STATICDATA_REPO", DEFAULT_PRODUCTION_REPO)' not in text,
         "旧的单级回退表达式应已消除")


# ══════════ ⑧ 断言下限 ══════════
def test_08z_assertion_floor():
    _chk(_N[0] >= 8, f"断言数应 >=8, 实得 {_N[0]}")