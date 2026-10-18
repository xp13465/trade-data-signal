#!/usr/bin/env python3
"""P5 — 把「机检闸门保险登记表」对账并入 pytest 全量(主检 + 变异自测)。

背景:`docs/ops/machine-check-registry.md` 是闸门生命周期的单一事实源,`scripts/check_gate_registry.py`
是它的机检(四查:① schema ② 挂点存在性 ③ 与教训台账双向覆盖 ④ 新增守卫必登记)。
本文件让「登记表与实物脱节」在全量 pytest 里立刻被发现(§18 L49:机制空转 / 假样本养绿 = 违规)。

- 主检:正常跑必须 RESULT=PASS(四条 OK 齐)。
- 判别力(red-first):registry 某行单元格数≠表头时,主检必须 FAIL 并报出行号/列数 ——
  防「该行被静默丢弃、整体仍 PASS」(2026-10-18 审查差集 A;回退此修法则本用例转红)。
- 变异自测:`--selftest` rc=0(内部删掉「CI 全量 pytest」闸门行 → 断言必须 FAIL;
  删掉一条存量豁免行 → 断言必须 FAIL;未变异负对照必须 PASS,证装置本身非恒 FAIL)。

零外发/零网络(变异自测全在 tempfile 临时目录里改副本,不动仓库里的真表)。
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).absolute().parent.parent.parent
SCRIPT = ROOT / "scripts" / "check_gate_registry.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
        timeout=180, cwd=str(ROOT),
    )


def _skip_if_absent():
    if not SCRIPT.exists():
        pytest.skip("check_gate_registry.py 不存在, 跳过")


def test_gate_registry_main_pass():
    _skip_if_absent()
    r = _run()
    assert r.returncode == 0, f"gate-registry rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "RESULT=PASS" in r.stdout, r.stdout
    assert "RESULT=FAIL" not in r.stdout, r.stdout
    # 四查必须都真跑过(防某一查被改成空转)
    for mark in ("① schema", "② 挂点存在性", "③ 台账闸门", "④ 覆盖"):
        assert mark in r.stdout, f"四查未见「{mark}」行(空转风险):\n{r.stdout}"


def test_gate_registry_mutation_selftest():
    _skip_if_absent()
    r = _run("--selftest")
    assert r.returncode == 0, f"gate-registry --selftest rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "[gate-registry-selftest] PASS" in r.stdout, r.stdout
    # 两条变异必须真响(删闸门行 / 删存量豁免行各一条)
    assert "RESULT=FAIL" in r.stdout, r.stdout


def test_gate_registry_malformed_row_fails(tmp_path):
    """判别力:某闸门行单元格数≠表头 → 必须 FAIL 报行号/列数(不得静默丢行后仍 PASS)。"""
    _skip_if_absent()
    reg = ROOT / "docs" / "ops" / "machine-check-registry.md"
    lines = reg.read_text(encoding="utf-8").splitlines(keepends=True)

    # 取一条「无台账『机检=是』挂接」的闸门数据行(main-merge.sh 7.9):丢它原先四查全不响。
    victim = next((j for j, ln in enumerate(lines)
                   if ln.startswith("|") and "main-merge.sh 7.9 步" in ln), None)
    assert victim is not None, "变异注入失败:registry 里找不到 7.9 闸门行(改测试或改表须同步)"
    cells = [c.strip() for c in lines[victim].strip().strip("|").split("|")]
    assert len(cells) == 7, f"7.9 行原应 7 栏, 实为 {len(cells)} 栏(表结构变须同步本用例)"
    lines[victim] = "|" + "|".join(cells[:-1]) + "|\n"   # 7 栏 → 6 栏

    bad = tmp_path / "registry-malformed.md"
    bad.write_text("".join(lines), encoding="utf-8")
    r = _run("--registry", str(bad))
    assert r.returncode != 0, f"畸形行竟被放过 rc={r.returncode}\n{r.stdout}"
    assert "RESULT=FAIL" in r.stdout, r.stdout
    assert "单元格数" in r.stdout and str(victim + 1) in r.stdout, \
        f"FAIL 必须报出畸形行行号({victim + 1}):\n{r.stdout}"