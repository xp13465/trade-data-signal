#!/usr/bin/env python3
"""#195 批1 — 把 bash 单测 test_resolve_repo.sh 并入 pytest 全量(方案 §7.2 待拍板#4 已定:加 wrapper)。

不改既有测试;bash 侧 rc!=0(或输出 FAIL>0)即 pytest FAIL,并回显逐项 PASS/FAIL 便于定位。
零外发/零网络(全部在 mktemp 沙箱)。
"""
import shutil
import subprocess
from pathlib import Path

import pytest

SH = Path(__file__).absolute().parent / "test_resolve_repo.sh"


def test_resolve_repo_bash_suite():
    if shutil.which("bash") is None:
        pytest.skip("本机无 bash, 跳过")
    r = subprocess.run(["bash", str(SH)], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, f"test_resolve_repo.sh rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "FAIL=0" in r.stdout, f"bash 侧有 FAIL:\n{r.stdout}"
