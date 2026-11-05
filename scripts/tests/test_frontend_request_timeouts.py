"""Run real frontend loader regression cases in CI's existing Node runtime."""
import subprocess
from pathlib import Path


def test_frontend_request_timeouts():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["node", "--test", str(root / "scripts/tests/test_frontend_request_timeouts.cjs")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
