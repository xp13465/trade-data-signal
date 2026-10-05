#!/usr/bin/env python3
"""#195 批1 返修 — 把 ratchet 机检并入 pytest 全量(主检 + 变异自测)。

背景:批1 独立审判 `check_repo_paths_ratchet.py` 的 R3 空转(正则 `:/Users/linhuichen` 匹配不到
全仓主流形态 `:-/Users/linhuichen` ⇒ 代码行命中恒 0 ⇒ 闸门永不响)。本文件让「改正则改坏了」
在全量 pytest 里立刻被发现(§18 L49:假样本养绿 = 违规)。

- 主检:正常跑必须 RESULT=PASS,且打印「R3 正则健康自检 ... OK」(恒在防空转自检)。
- 变异自测:`--selftest` rc=0(内部构造「已迁移文件 env 默认值改回写死 mac 路径」样本 →
  断言 ratchet 必须 FAIL;负对照必须 PASS,证装置本身非恒 FAIL)。

零外发/零网络(变异自测全在 tempfile 临时树;不跑任何 notify / R2 写)。
"""
import subprocess
import sys
from pathlib import Path

import pytest

RATCHET = Path(__file__).absolute().parent.parent / "check_repo_paths_ratchet.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(RATCHET), *args], capture_output=True, text=True, timeout=180
    )


def test_ratchet_main_pass():
    if not RATCHET.exists():
        pytest.skip("ratchet 脚本不存在, 跳过")
    r = _run()
    assert r.returncode == 0, f"ratchet rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "RESULT=PASS" in r.stdout, r.stdout
    assert "RESULT=FAIL" not in r.stdout, r.stdout
    assert "命中标准样本 OK" in r.stdout, f"R3 正则健康自检未 OK(空转风险):\n{r.stdout}"


def test_ratchet_mutation_selftest():
    if not RATCHET.exists():
        pytest.skip("ratchet 脚本不存在, 跳过")
    r = _run("--selftest")
    assert r.returncode == 0, f"ratchet --selftest rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[ratchet-selftest] PASS" in r.stdout, r.stdout
    assert "变异样本" in r.stdout and "RESULT=FAIL" in r.stdout, r.stdout
