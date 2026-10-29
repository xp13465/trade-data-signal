# -*- coding: utf-8 -*-
"""test_pf_budget_20261029.py — #352 公募日更「内外层成对预算」止血的判据。

被测:
  · scripts/deploy.sh —— EXPORT_TIMEOUT(调用方可控预算, 默认 0 = 不限时 = 改动前行为逐位不变)
  · scripts/public_fund_daily.sh —— 调用侧接线: 采集 run_to 300 / deploy 侧 EXPORT_TIMEOUT=600 + GIT_LOCK_TIMEOUT=420

为什么这么测(§18 L50 static-only):
  deploy.sh 是生产脚本本体(禁跑、禁 source 主体)。本文件只做两类事:
    (a) 静态文本断言(默认无预算 / 全局默认 3600 不动 / 接线值在位);
    (b) 按锚点行把 deploy.sh 里的 `run_with_budget` helper 与 export 预算片段**提取**到 tmp 沙箱,
        用桩 export(记录 argv / sleep)执行 —— 只执行被提取的这段逻辑, 绝不 source/exec deploy.sh 主体。

覆盖(对应任务书 E2/E3/E4):
  [E2] 默认(不设 EXPORT_TIMEOUT): 桩 export 收到的 argv 逐字 == ["--incremental"], 日志无「预算」行
       (证明默认路径未加任何包裹); 默认分支源码行与改动前字面量逐字一致。
  [E3] EXPORT_TIMEOUT=2 + 假慢 export(sleep 30): rc=124(明确区别于 0/143)、日志出现「超预算」、
       按失败 exit 124, 且耗时 2s 级(不是 30s)。
  [E4] 接线: 采集 = run_to 300(run_to 在 Linux 上即 coreutils `timeout N`)、deploy 调用 =
       EXPORT_TIMEOUT=600 + GIT_LOCK_TIMEOUT=420; deploy.sh 全局默认仍是 GIT_LOCK_TIMEOUT:-3600。

判别力(变异自证, 手工一条命令即可复跑):
  把 deploy.sh 里 `if [ "$EXPORT_TIMEOUT" -gt 0 ] ... else ... fi` 的预算分支整段删掉(只留裸命令)后,
  [E2] 的「预算分支在位」断言与 [E3] 必红。复跑方法:
    cp scripts/deploy.sh /tmp/mut-deploy.sh
    python - <<'EOF'
    import re,sys
    p='/tmp/mut-deploy.sh'; s=open(p,encoding='utf-8').read()
    s=s.replace('if [ "$EXPORT_TIMEOUT" -gt 0 ]; then\n  echo "→ export 预算 ${EXPORT_TIMEOUT}s（超时即杀，按失败处理）" | tee -a "$LOG"\n  run_with_budget "$EXPORT_TIMEOUT" "$PY" "$EXPORT" --incremental 2>&1 | tee -a "$LOG"\nelse\n','')
    s=s.replace('fi\nEXPORT_RC=${PIPESTATUS[0]}','EXPORT_RC=${PIPESTATUS[0]}',1)
    open(p,'w',encoding='utf-8').write(s)
    EOF
    PF_BUDGET_DEPLOY_SH=/tmp/mut-deploy.sh .venv/bin/python -m pytest -q scripts/tests/test_pf_budget_20261029.py
  (PF_BUDGET_DEPLOY_SH 只用于变异自证; 不设时读仓库真实 scripts/deploy.sh)

跑法:
  .venv/bin/python -m pytest -q scripts/tests/test_pf_budget_20261029.py
"""
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent.parent
DEPLOY = Path(os.environ.get("PF_BUDGET_DEPLOY_SH") or (ROOT / "scripts" / "deploy.sh"))
DAILY = ROOT / "scripts" / "public_fund_daily.sh"

DEFAULT_EXPORT_LINE = '"$PY" "$EXPORT" --incremental 2>&1 | tee -a "$LOG"'
BUDGET_EXPORT_LINE = 'run_with_budget "$EXPORT_TIMEOUT" "$PY" "$EXPORT" --incremental 2>&1 | tee -a "$LOG"'


# ── 片段提取(只取被设计的那两段, 不碰 deploy.sh 其它逻辑) ──────────────────────

def _deploy_lines():
    return DEPLOY.read_text(encoding="utf-8").splitlines()


def _extract_func(lines, name):
    """按 `name() {` 到匹配的 `}` 提取 shell 函数体(大括号计数, ${x} 成对不影响)。"""
    start = next((i for i, ln in enumerate(lines) if ln.startswith(name + "() {")), None)
    assert start is not None, f"deploy.sh 里找不到函数 {name}()"
    depth = 0
    out = []
    for ln in lines[start:]:
        out.append(ln)
        depth += ln.count("{") - ln.count("}")
        if depth == 0:
            break
    assert depth == 0, f"{name}() 大括号不平衡"
    return "\n".join(out)


def _extract_export_block(lines):
    """从 `EXPORT_TIMEOUT=...` 起, 到 `echo \"✓ export.py 完成\"` 止(含失败分支的 exit)。"""
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip() == 'EXPORT_TIMEOUT="${EXPORT_TIMEOUT:-0}"'), None)
    assert start is not None, "deploy.sh 里找不到 export 预算片段起点(EXPORT_TIMEOUT=...)"
    end = next((i for i in range(start, len(lines)) if 'echo "✓ export.py 完成"' in lines[i]), None)
    assert end is not None, "deploy.sh 里找不到 export 预算片段终点"
    return "\n".join(lines[start:end + 1])


def _write_stubs(tmp_path):
    rec = tmp_path / "argv.txt"
    fast = tmp_path / "fake_export_fast.sh"
    fast.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" >> "{rec}"\nexit 0\n', encoding="utf-8")
    fast.chmod(0o755)
    slow = tmp_path / "fake_export_slow.sh"
    slow.write_text("#!/bin/bash\nsleep 30\nexit 0\n", encoding="utf-8")
    slow.chmod(0o755)
    return fast, slow, rec


def _run_export_block(tmp_path, export_script, export_timeout):
    """在 tmp 沙箱执行「helper + export 预算片段」, 返回 (rc, log_text, elapsed, argv_file)。"""
    lines = _deploy_lines()
    helper = _extract_func(lines, "run_with_budget")
    block = _extract_export_block(lines)
    log = tmp_path / "run.log"
    harness = tmp_path / "harness.sh"
    harness.write_text(
        "set -u\n"
        f'LOG="{log}"\n'
        f'PY="{export_script}"\n'
        'EXPORT="ignored_path"\n'
        f"{helper}\n"
        f"{block}\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.pop("EXPORT_TIMEOUT", None)
    if export_timeout is not None:
        env["EXPORT_TIMEOUT"] = str(export_timeout)
    t0 = time.monotonic()
    # 被杀进程的 stdout 可能截断在多字节字符中间(tee/kill 并发), 用 errors="replace" 解码
    r = subprocess.run(["bash", str(harness)], capture_output=True, timeout=90, env=env)
    elapsed = time.monotonic() - t0
    r.stdout = r.stdout.decode("utf-8", "replace")
    r.stderr = r.stderr.decode("utf-8", "replace")
    return r.returncode, log.read_text(encoding="utf-8") if log.exists() else "", elapsed, tmp_path / "argv.txt"


# ── [E2] 默认路径: 逐字不变, 无包裹 ─────────────────────────────────────────────

def test_E2_default_export_argv_unchanged(tmp_path):
    fast, _slow, rec = _write_stubs(tmp_path)
    rc, log_text, _elapsed, argv = _run_export_block(tmp_path, fast, export_timeout=None)
    assert rc == 0, f"默认路径应成功:\n{log_text}"
    # argv = [$EXPORT, --incremental](沙箱里 EXPORT=ignored_path); 重点是「无任何前缀/包裹」且顺序逐字不变
    assert argv.read_text(encoding="utf-8").split() == ["ignored_path", "--incremental"], \
        "默认路径 export 的 argv 必须逐字等于改动前的 [$EXPORT, --incremental]"
    assert "预算" not in log_text, f"默认路径不得出现预算日志:\n{log_text}"


def test_E2b_default_branch_source_byte_identical():
    """默认分支的源码行与改动前逐字一致 = 不加前缀、不加包裹。"""
    lines = [ln.strip() for ln in _deploy_lines()]
    assert DEFAULT_EXPORT_LINE in lines, "默认分支丢失(改动前那行 `$PY $EXPORT --incremental` 不在)"
    # 预算分支必须在 if EXPORT_TIMEOUT>0 之下, else 里才是默认分支
    i_if = next((i for i, ln in enumerate(lines) if ln == 'if [ "$EXPORT_TIMEOUT" -gt 0 ]; then'), None)
    assert i_if is not None, "deploy.sh 缺少 `if [ \"$EXPORT_TIMEOUT\" -gt 0 ]` 预算分支"
    i_default = lines.index(DEFAULT_EXPORT_LINE)
    i_budget = lines.index(BUDGET_EXPORT_LINE)
    assert i_if < i_budget < i_default, "预算/默认分支顺序不对(预算分支应在 else 前)"
    assert lines[i_default - 1] == "else", "默认分支必须落在 else 分支里"


# ── [E3] 预算生效: 2s 被杀, rc=124, 日志有标记, 且不当成功 ──────────────────────

def test_E3_budget_kills_slow_export_with_124(tmp_path):
    _fast, slow, _rec = _write_stubs(tmp_path)
    rc, log_text, elapsed, _argv = _run_export_block(tmp_path, slow, export_timeout=2)
    assert rc == 124, f"超预算必须返回 124(区别于命令自身失败): rc={rc}\n{log_text}"
    assert "超预算" in log_text, f"日志必须留超预算标记:\n{log_text}"
    assert "EXPORT_TIMEOUT" in log_text and "终止部署" in log_text, \
        f"必须按失败终止(不当成功):\n{log_text}"
    assert elapsed < 15, f"2s 预算应在秒级被杀, 实测 {elapsed:.1f}s(贴到上限=预算没生效)"


# ── [E4] 调用侧接线 + 全局默认不动 ──────────────────────────────────────────────

def test_E4_call_side_budgets_wired():
    daily = DAILY.read_text(encoding="utf-8")
    # 采集 pipeline: run_to 300(Linux 上即 coreutils `timeout 300`)
    assert 'run_to 300 "$PY" -m app.collector.public_fund daily' in daily, \
        "采集 pipeline 未包 300s 预算"
    assert 'timeout "$t" "$@"' in daily, "run_to 必须优先用 coreutils timeout(云上 Linux 生效)"
    # deploy 调用: 只对这一条链给预算
    assert 'EXPORT_TIMEOUT=600 GIT_LOCK_TIMEOUT=420 bash "$REPO/scripts/deploy.sh" public-fund' in daily, \
        "deploy 调用处必须设 EXPORT_TIMEOUT=600 + GIT_LOCK_TIMEOUT=420"


def test_E4b_global_defaults_untouched():
    deploy = DEPLOY.read_text(encoding="utf-8")
    assert 'EXPORT_TIMEOUT="${EXPORT_TIMEOUT:-0}"' in deploy, "EXPORT_TIMEOUT 默认必须为 0(不限时)"
    assert 'GIT_LOCK_TIMEOUT:-3600' in deploy, "deploy.sh 全局等锁默认 3600 必须保持原样(共享 17:50 全量链)"
    assert "GIT_LOCK_TIMEOUT=420" not in deploy, "GIT_LOCK_TIMEOUT=420 只许在调用侧, 不得写进 deploy.sh"