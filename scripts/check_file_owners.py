#!/usr/bin/env python3
"""check_file_owners.py - 同文件并发串行化工具(防再犯机制 C, 2026-08-19 实施)

背景: 冲突覆盖根因 docs/conflict-overwrite-rootcause-2026-08-18.md(§五.C) +
      诱因链 docs/conflict-overwrite-triggers-2026-08-18.md(缺口②「同文件串行」无工具支撑)。
      08-18 一天 app.js 被 10+ feature agent 各自 worktree 并发触碰, §23.4「同文件串行排队」
      靠主控记忆核对在跑 agent 文件范围, 08-18 明显没执行到位。

本脚本从 /tmp/agent-progress-*.md 扫描「在跑 agent 声明的改动文件」, 主控派单前核对大文件
(app.js/lab.js/common.js/style.css)是否已被其他在跑 agent 占用; 无占用才可派, 有则排队。
把 C 从「主控记忆」工具化为「扫进度文件」, 替代记忆(缺口②建议)。

声明格式(agent 进度文件里): 一行含 `文件: static-site/app.js` 或 `改动文件: .../app.js` 等,
本脚本按「在跑(未标 DONE/完成/结束)的进度文件里 grep 到目标文件路径」判定占用。

用法:
  python3 scripts/check_file_owners.py <目标文件相对路径> [--progress-dir /tmp] [--verbose]
  例: python3 scripts/check_file_owners.py static-site/app.js
      python3 scripts/check_file_owners.py static-site/app.js --verbose

返回(退出码):
  0 = 未被任何在跑 agent 占用(可派单)
  1 = 已被某在跑 agent 占用(需排队, 输出占用 agent 的进度文件)
  2 = 进度目录不存在/无进度文件(视为无占用, 放行)

容错(按任务要求):
  - 进度文件不存在/目录不存在 → 放行(exit 0 或 2)
  - 未声明文件(进度文件里没提到目标文件) → 不占用, 放行
  - 进度文件标了 DONE/完成/结束 的 agent → 视为已完成, 不占用
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# 进度文件里「已完成」标记: 出现任一即视为该 agent 已结束, 不占用
DONE_MARKERS = ["DONE", "完成", "结束", "已上线", "已推送", "已 merge", "已合并", "PASS"]

# mtime 新鲜度阈值: 进度文件修改时间距今超过该小时数, 一律视为历史文件放行
# (在跑 agent 的任务通常几小时内完成, 24h 足够新鲜; 防历史遗留文件误判为「在跑占用」)
MAX_AGE_HOURS = 24
MAX_AGE_SECONDS = MAX_AGE_HOURS * 3600

# 声明文件的行内关键词(行内同时出现「文件」和路径即视为声明)
DECLARE_KEYWORDS = ["文件", "改动", "修改", "touch", "写", "编辑"]

def _is_done(text: str) -> bool:
    """判断进度文件是否已完成。只在文件末尾 4 行检测 DONE 标记(约定 agent 收尾时
    末尾写 DONE 标记行), 防「STEP2: 完成 app.js 修改(继续改 lab.js)」这类中途"完成"
    字样误标 DONE 导致占用漏检(机制 C 同模块冲突预防)。"""
    tail_lines = text.strip().splitlines()[-4:]
    tail = "\n".join(tail_lines)
    for m in DONE_MARKERS:
        if m in tail:
            return True
    return False


def _declares_target(line: str, target_rel: str, verbose: bool) -> bool:
    """判断一行是否声明了对目标文件的操作。"""
    if target_rel not in line:
        return False
    # 必须带「文件/改动/修改/touch/写」类关键词, 防「提到但没改」
    for kw in DECLARE_KEYWORDS:
        if kw in line:
            return True
    return False


def scan(progress_dir: str, target_rel: str, verbose: bool) -> tuple[list[str], bool]:
    """扫描进度目录, 返回(占用者进度文件列表, 目录是否存在)。

    占用者 = 在跑(未 DONE)且声明了目标文件的进度文件。
    """
    d = Path(progress_dir)
    if not d.exists() or not d.is_dir():
        if verbose:
            print(f"[verbose] 进度目录不存在或非目录: {d}(视为无占用, 放行)")
        return [], False

    owners = []
    try:
        files = list(d.glob("agent-progress-*.md"))
    except Exception:
        if verbose:
            print(f"[verbose] 扫描进度目录失败: {d}")
        return [], True
    if verbose:
        print(f"[verbose] 进度目录 {d} 找到 {len(files)} 个进度文件")

    for fp in sorted(files):
        # mtime 新鲜度过滤: 超过 MAX_AGE_HOURS 未修改的历史进度文件, 一律放行不判占用
        # (在跑 agent 的任务通常几小时内完成; 防历史遗留文件被误判为「在跑占用」)
        try:
            mtime = os.path.getmtime(fp)
        except Exception:
            # 取不到 mtime(文件被删/权限) → 容错放行, 不判占用
            if verbose:
                print(f"[verbose] {fp.name}: 取 mtime 失败, 视为历史文件放行")
            continue
        age = time.time() - mtime
        if age > MAX_AGE_SECONDS:
            if verbose:
                print(f"[verbose] {fp.name}: mtime 距今 {age/3600:.1f}h > {MAX_AGE_HOURS}h, 视为历史文件放行")
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if _is_done(text):
            if verbose:
                print(f"[verbose] {fp.name}: 标记已完成(DONE), 不占用")
            continue
        declared = False
        for line in text.splitlines():
            if _declares_target(line, target_rel, verbose):
                declared = True
                break
        if declared:
            owners.append(str(fp))
            if verbose:
                print(f"[verbose] {fp.name}: 声明占用 {target_rel}")
        elif verbose:
            print(f"[verbose] {fp.name}: 未声明 {target_rel}, 不占用")

    return owners, True


def main() -> int:
    ap = argparse.ArgumentParser(description="同文件并发串行化工具(防再犯机制 C)")
    ap.add_argument("target", help="目标文件相对路径, 如 static-site/app.js")
    ap.add_argument("--progress-dir", default="/tmp",
                    help="进度文件目录(默认 /tmp)")
    ap.add_argument("--verbose", action="store_true", help="输出详细扫描过程")
    args = ap.parse_args()

    target_rel = args.target
    if verbose := args.verbose:
        print(f"=== check_file_owners.py(同文件并发串行化, 机制 C) ===")
        print(f"  目标: {target_rel}")
        print(f"  进度目录: {args.progress_dir}")

    owners, dir_ok = scan(args.progress_dir, target_rel, verbose)

    if not dir_ok:
        # 目录不存在 → 无在跑 agent, 放行(容错)
        print(f"✓ {target_rel} 未被占用(进度目录不可用, 视为无在跑 agent, 可派单)")
        return 2

    if owners:
        print(f"✗ {target_rel} 已被 {len(owners)} 个在跑 agent 占用, 需排队:")
        for o in owners:
            print(f"    - {o}")
        print("  请先等这些 agent 完成(进度文件标 DONE)或协调串行, 再派单(机制 C / §23.4 同模块冲突预防)")
        return 1

    print(f"✓ {target_rel} 未被任何在跑 agent 占用, 可派单(机制 C 放行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
