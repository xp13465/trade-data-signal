#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体量月报(P3)机检接线:负对照 + 变异(改坏 rev / 字节数 → --check 必须 FAIL)+ 自测。

接线形态仿 test_repo_paths_ratchet_pytest.py:**跑真脚本、看 rc 与结果串**,不重复实现逻辑。
零外发/零网络:只读本地 git 对象 + 往 tempdir 写 JSON 变异副本。

⚠️ CI-sim(§5.8 上线关):只依赖 stdlib + git(CI checkout fetch-depth=0,历史 rev 可达),
不 import requests/akshare 等真实库;不断言"本机有没有某命令"以外的东西(此处只用 git)。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent          # scripts/tests -> 仓根
SCRIPT = ROOT / "scripts" / "gen_governance_size_report.py"
JSON_P = ROOT / "docs" / "ops" / "governance-budget-history.json"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=180, cwd=str(ROOT))


def _skip_if_absent():
    if not SCRIPT.exists():
        pytest.skip("体量月报脚本不存在, 跳过")
    if not JSON_P.is_file():
        pytest.skip("体量月报 JSON 不存在(未回填), 跳过")


def test_size_report_check_pass():
    """负对照:仓内真 JSON + 真 git 历史 → --check 必须 PASS(装置本身非恒 FAIL)。"""
    _skip_if_absent()
    r = _run("--check", "--repo", str(ROOT), "--json", str(JSON_P))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "RESULT=PASS" in r.stdout, r.stdout
    assert "RESULT=FAIL" not in r.stdout, r.stdout


def test_size_report_bad_rev_fails(tmp_path):
    """变异①:改坏一行 rev → 必须 FAIL(rev 对账锚真响,不是空转)。"""
    _skip_if_absent()
    doc = json.loads(JSON_P.read_text(encoding="utf-8"))
    doc["entries"][-1]["rev"] = "0" * 40
    p = tmp_path / "bad-rev.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    r = _run("--check", "--repo", str(ROOT), "--json", str(p))
    assert r.returncode == 1, f"rc={r.returncode}(应 FAIL)\n{r.stdout}"
    assert "RESULT=FAIL" in r.stdout, r.stdout


def test_size_report_bad_bytes_fails(tmp_path):
    """变异②:改坏一行字节数(+1)→ 必须 FAIL(逐位对账真响)。"""
    _skip_if_absent()
    doc = json.loads(JSON_P.read_text(encoding="utf-8"))
    if doc["entries"][-1]["claude_md"] is None:
        pytest.skip("该行无 CLAUDE.md 记录, 跳过")
    doc["entries"][-1]["claude_md"] += 1
    p = tmp_path / "bad-bytes.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    r = _run("--check", "--repo", str(ROOT), "--json", str(p))
    assert r.returncode == 1, f"rc={r.returncode}(应 FAIL)\n{r.stdout}"
    assert "RESULT=FAIL" in r.stdout, r.stdout
    assert "≠ git 实测" in r.stdout, r.stdout


def test_size_report_selftest():
    """防空转:银证 --selftest(负对照 + 三向变异)必须全过。"""
    _skip_if_absent()
    r = _run("--selftest", "--repo", str(ROOT), "--json", str(JSON_P))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[size-report-selftest] PASS" in r.stdout, r.stdout