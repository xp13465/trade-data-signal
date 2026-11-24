"""MA3连3日(post)凯利区开关: 前端 node 单测的 pytest 包装(CI 收集入口)。

行为+形状守卫全在 .cjs 内(抽取生产函数执行, 不复制逻辑), 本包装只负责在 CI 的
既有 Node 运行时里跑一遍。复现: node --test scripts/tests/test_ma3_lab_post_20261124.cjs
"""
import subprocess
from pathlib import Path


def test_ma3_lab_post_20261124():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "--test", str(root / "scripts/tests/test_ma3_lab_post_20261124.cjs")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
