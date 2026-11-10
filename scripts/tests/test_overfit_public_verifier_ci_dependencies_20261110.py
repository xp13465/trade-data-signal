"""#382: full script regression jobs must install the verifier's real CA dependency."""
from pathlib import Path
import re
import shlex

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("workflow", ["ops-monitoring-checks.yml", "ci.yml"])
def test_full_script_regression_jobs_install_certifi(workflow):
    config = yaml.load((ROOT / ".github/workflows" / workflow).read_text(), Loader=yaml.BaseLoader)
    jobs = []
    for name, job in config["jobs"].items():
        runs = [step["run"] for step in job.get("steps", []) if "run" in step]
        if any(re.search(r"pytest\b[^\n]*scripts/tests/(?:\s|$)", run) for run in runs):
            jobs.append(name)
            installed = set()
            for run in runs[:next(i for i, text in enumerate(runs) if re.search(r"pytest\b[^\n]*scripts/tests/(?:\s|$)", text)) + 1]:
                for line in run.splitlines():
                    if re.search(r"pytest\b[^\n]*scripts/tests/(?:\s|$)", line):
                        break
                    parts = shlex.split(line)
                    if "pip" in parts and "install" in parts:
                        installed.update(part.split("==", 1)[0].lower() for part in parts[parts.index("install") + 1:])
            assert "certifi" in installed, f"{workflow}:{name}: _read_overfit_public requires certifi before curl"
    assert jobs, f"{workflow}: expected full scripts/tests regression job not found"
