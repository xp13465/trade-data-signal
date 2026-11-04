"""用已有 Node 运行时执行真实前端辅助加载器定向回归。"""
import subprocess
from pathlib import Path


def test_frontend_aux_body_timeouts():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "--test", str(root / "scripts/tests/test_frontend_aux_body_timeouts.cjs")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
