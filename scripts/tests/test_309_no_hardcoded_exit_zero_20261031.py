# -*- coding: utf-8 -*-
r"""#309 收尾 C: 脚本结案行禁「写死退出码=0」源码形状守卫(2026-10-31)。

防 fake OK 再发: `gen_schedule_stats._EXIT_FIELD_RE` 只认 `退出码=(\d+)` 字面,
脚本若在结案行写死 `退出码=0` 而子步骤(deploy/采集)真失败, last_exit 仍 0 ⇒ 假成功
(#309 病灶)。本守卫扫 `scripts/*.sh` 结案行(`=== xxx.sh 结束 ... ===`),
命中最恶性模式即 FAIL:

  **结案行含字面 `退出码=0` 且同行还带 `$` 变量子步骤字段(deploy=$VAR / 采集=$VAR /
   collect=$VAR)** = 主码写死 0、子码却诚实暴露 ⇒ 自相矛盾, 必为「主码该写变量没写」。

  例外(放行):
  - `退出码=$VAR`(变量, 非字面 0) —— 已诚实;
  - `退出码=0` 单独出现(无子字段) —— 可能是合法的「无数据=成功」覆盖(lhb/futures/rzhb
    早期退出路径, collect 非 0 表示源未发布, 脚本主动当成功处理, exit 0 与 systemd 一致),
    不属「主码该写变量没写」的恶性模式, 放行;
  - `退出码=N`(非 0 字面) —— 真失败路径, 放行。

V5 判别力: 注入「退出码=0 deploy=$X」⇒ 红; 合规(退出码=$VAR 或 退出码=0 单独)⇒ 绿。
"""
import re
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).absolute().parent.parent.parent / "scripts"

# 结案行: === xxx.sh 结束 ... ===
_END_RE = re.compile(r"===\s+\S+\.sh\s+结束.*?===")
# 字面 退出码=0 (退出码=$VAR 不匹配, $ 非 0)
_LITERAL_ZERO_RE = re.compile(r"退出码=0")
# 同行子步骤变量字段
_SUBRC_VAR_RE = re.compile(r"(?:deploy|采集|collect)=\$\w")


def _scan():
    offenders = []
    for sh in sorted(SCRIPTS_DIR.glob("*.sh")):
        text = sh.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if not _END_RE.search(line):
                continue
            if _LITERAL_ZERO_RE.search(line) and _SUBRC_VAR_RE.search(line):
                offenders.append(f"{sh.name}:{i}: {line.strip()}")
    return offenders


def test_no_hardcoded_exit_zero_alongside_subrc_vars():
    """V5: 结案行禁「退出码=0 字面 + 子步骤 $ 变量」自相矛盾模式。"""
    offenders = _scan()
    assert not offenders, (
        "结案行写死 退出码=0 却同行带 $ 子步骤变量(主码该写变量没写, #309 假 OK 同类):\n  "
        + "\n  ".join(offenders)
    )


def test_lint_has_discriminative_power():
    """V5 判别力: 合规形态不误报、恶性形态必报。"""
    good_lines = [
        "echo \"=== x.sh 结束 $(date) 退出码=$COLLECT_RC 采集=$COLLECT_RC deploy=$DEPLOY_RC ===\"",
        "echo \"=== x.sh 结束 $(date) 退出码=0 ===\"",  # 单独, 合法无数据覆盖
        "echo \"=== x.sh 结束 $(date) 退出码=1 ===\"",  # 真失败
        "echo \"=== x.sh 结束 $(date) deploy=$DEPLOY_RC ===\"",  # 无主码字段
    ]
    for line in good_lines:
        if _END_RE.search(line):
            assert not (_LITERAL_ZERO_RE.search(line) and _SUBRC_VAR_RE.search(line)), \
                f"误报合规行: {line}"
    bad_line = "echo \"=== x.sh 结束 $(date) 退出码=0 采集=$COLLECT_RC deploy=$DEPLOY_RC ===\""
    assert _LITERAL_ZERO_RE.search(bad_line) and _SUBRC_VAR_RE.search(bad_line), \
        "未识别恶性模式(退出码=0 + 子步骤变量)"
