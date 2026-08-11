#!/usr/bin/env python3
"""tasks_verify.py - TASKS.md 完成度校验脚本（2026-08-11 建立，机制见 docs/tasks-archive-maintain.md）

校验 TASKS.md 里任务完成状态与代码/线上实际是否同步，输出 3 类不同步清单：
  ① 悬空 hash 但功能在 main：小节标已上线，但引用的 commit hash 不在 origin/main，
     且小节标题的关键功能词在 main 代码/产物中 grep 得到（说明功能实际已上线，只是 hash 不同/过期）
  ② 漏标：小节标题标 📋/待办（未标完成），但内容/引用 hash 显示功能已在 main（应改标 ✅ 待归档）
  ③ 状态超前：小节标题写「已完成归档/已归档」，但 docs/archive/TASKS-done.md 中查不到对应内容
     （标题写归档实际未归档）

报告写 docs/archive/tasks-verify-report-<YYYYMMDD>.md。

用法：python3 scripts/tasks_verify.py [--report-dir docs/archive] [--no-grep]
  --no-grep：跳过功能词 git grep（更快，只做 hash 与归档存在性校验）
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "TASKS.md"
ARCHIVE = REPO / "docs" / "archive" / "TASKS-done.md"

HASH_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{8,12})(?![0-9a-fA-F])")
# 8-12 位纯数字 = 日期/代码（如 20260805 / 20070930），非 git hash；日期+字母（20260805b）同样排除
DATE_LIKE_RE = re.compile(r"^\d{8,12}$|^20\d{6}[a-z]$")


def is_likely_hash(h: str) -> bool:
    return not DATE_LIKE_RE.match(h)
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)")
DONE_MARKERS = ("已完成", "已上线", "全闭环", "已归档")
DONE_EMOJI = "✅"
TODO_TITLE_RE = re.compile(r"^(📋|🆕|⏸|待办|待实施|待排期)")
# ③ 归档声明匹配：标题明确声明"已归档/已完成归档/归档到 TASKS-done.md"（"批量归档汇总"这类描述性标题不算）
ARCHIVE_CLAIM_RE = re.compile(r"已完成归档|已归档|归档\s*(到\s*)?TASKS-done")
LEAD_EMOJI_RE = re.compile(r"^[✅📋🆕⏸🟢🔄🔴🔵🟡]+")
LEAD_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s*")
TRAIL_PAREN_RE = re.compile(r"[（(].*?[)）]\s*$")


def log(msg: str) -> None:
    print(msg, flush=True)


def git(*args: str, timeout: int = 60) -> str:
    r = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {r.stderr[:200]}")
    return r.stdout


def git_ok(*args: str, timeout: int = 60) -> bool:
    r = subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode == 0


def norm_title(t: str) -> str:
    t = LEAD_EMOJI_RE.sub("", t)
    t = LEAD_DATE_RE.sub("", t)
    t = TRAIL_PAREN_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def is_done_title(title: str) -> bool:
    return DONE_EMOJI in title or any(m in title for m in DONE_MARKERS)


def block_extent(lines: list[str], start: int, level: int) -> int:
    j = start + 1
    while j < len(lines):
        m = HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= level:
            break
        j += 1
    return j


def collect_main_full_hashes() -> set[str]:
    """origin/main 可达的全量 40 位 hash 集合。"""
    try:
        out = git("log", "origin/main", "--format=%H")
    except RuntimeError:
        try:
            git("fetch", "origin", timeout=180)
            out = git("log", "origin/main", "--format=%H")
        except RuntimeError as e:
            log(f"[warn] 无法获取 origin/main 历史: {e}")
            return set()
    return {h.strip().lower() for h in out.splitlines() if h.strip()}


def collect_all_branch_hashes() -> set[str]:
    try:
        out = git("log", "--all", "--format=%H")
    except RuntimeError:
        return set()
    return {h.strip().lower() for h in out.splitlines() if h.strip()}


def hash_in_set(short: str, full_set: set[str]) -> bool:
    s = short.lower()
    return any(h.startswith(s) for h in full_set)


def keyword_from_title(title: str) -> str | None:
    """从标题提取功能关键词（去 emoji/日期/括号，取核心片段），用于 git grep 反查功能是否在 main。"""
    t = LEAD_EMOJI_RE.sub("", title)
    t = LEAD_DATE_RE.sub("", t)
    t = TRAIL_PAREN_RE.sub("", t)
    t = re.sub(r"\s+", "", t)
    # 取最长的一段中文连续串（≥3 字），否则整个
    m = re.search(r"[一-鿿]{3,}", t)
    if m:
        return m.group(0)
    return t[:8] if t else None


def grep_main(kw: str) -> bool:
    """在 origin/main 代码/产物中 grep 关键词，判断功能是否在 main。"""
    if not kw:
        return False
    r = subprocess.run(
        ["git", "-C", str(REPO), "grep", "-l", "-F", kw, "origin/main",
         "--", "*.py", "*.js", "*.sh", "*.md", "*.json"],
        capture_output=True, text=True, timeout=60,
    )
    return r.returncode == 0 and bool(r.stdout.strip())


def scan_sections(lines: list[str]):
    """解析 TASKS.md 的 ## 小节（含标题行号/标题/内容/哈希）。"""
    sections = []
    i = 0
    while i < len(lines):
        m = HEADING_RE.match(lines[i])
        if not m:
            i += 1
            continue
        lvl = len(m.group(1)); title = m.group(2)
        if lvl == 2:
            j = block_extent(lines, i, 2)
            content = "".join(lines[i:j])
            hashes = sorted({h.lower() for h in HASH_RE.findall(content) if is_likely_hash(h)})
            sections.append({"line": i + 1, "title": title, "content": content, "hashes": hashes})
            i = j
        else:
            i += 1
    return sections


def main() -> int:
    ap = argparse.ArgumentParser(description="TASKS.md 完成度校验")
    ap.add_argument("--report-dir", default="docs/archive")
    ap.add_argument("--no-grep", action="store_true", help="跳过功能词 git grep")
    args = ap.parse_args()

    if not TASKS.exists():
        log(f"ERROR: {TASKS} 不存在")
        return 1

    lines = TASKS.read_text(encoding="utf-8").splitlines(keepends=True)
    sections = scan_sections(lines)
    log(f"[info] 解析到 {len(sections)} 个 ## 小节")

    main_full = collect_main_full_hashes()
    all_branch = collect_all_branch_hashes()
    log(f"[info] origin/main 可达 commit {len(main_full)} 个 / --all {len(all_branch)} 个")

    archive_titles: set[str] = set()
    if ARCHIVE.exists():
        for ln in ARCHIVE.read_text(encoding="utf-8").splitlines():
            m = HEADING_RE.match(ln)
            if m and len(m.group(1)) in (1, 2):
                archive_titles.add(norm_title(m.group(2)))

    dangling_but_live: list[str] = []   # ① 悬空 hash 但功能在 main
    missing_labels: list[str] = []      # ② 漏标（已上线仍标待办）
    ahead_status: list[str] = []        # ③ 状态超前（标题写已归档但实际不在归档）
    stats: dict[str, int] = {"total_hash_refs": 0, "not_in_main": 0, "no_such": 0}

    for sec in sections:
        title = sec["title"]
        content = sec["content"]
        hashes = sec["hashes"]
        done = is_done_title(title)
        todo_marked = bool(TODO_TITLE_RE.match(title))
        stats["total_hash_refs"] += len(hashes)

        not_main = [h for h in hashes if not hash_in_set(h, main_full)]
        stats["not_in_main"] += len(not_main)
        no_such = [h for h in not_main if not hash_in_set(h, all_branch) and not git_ok("cat-file", "-e", h + "^{commit}")]
        stats["no_such"] += len(no_such)

        kw = keyword_from_title(title)

        # ① 悬空 hash 但功能在 main
        if done and not_main:
            live = False
            if args.no_grep:
                live = False
            else:
                live = bool(kw and grep_main(kw))
            loc = f"L{sec['line']}"
            if live:
                dangling_but_live.append(
                    f"- **{loc}** `{title[:60]}`：引用 hash {','.join(not_main[:4])}{'...' if len(not_main)>4 else ''} 不在 main，"
                    f"但功能词「{kw}」在 main 代码/产物中命中 → 功能已在 main（hash 过期/不同，建议更新 hash 或归档）"
                )
            else:
                dangling_but_live.append(
                    f"- **{loc}** `{title[:60]}`：引用 hash {','.join(not_main[:4])} 不在 main，功能词「{kw}」未命中 → "
                    f"需人工确认（可能真未上线，或功能词命中失败）"
                )

        # ② 漏标：标题标待办但内容已上线/hash 全在 main
        if todo_marked and not done:
            content_done = ("已上线" in content or "已完成" in content or "已实施" in content)
            all_in_main = bool(hashes) and all(hash_in_set(h, main_full) for h in hashes)
            if all_in_main and content_done:
                missing_labels.append(
                    f"- **L{sec['line']}** `{title[:60]}`：标题标待办但内容含「已上线/已完成」且引用 hash 全在 main → 疑似已完成未改标（漏标）"
                )

        # ③ 状态超前：标题写已归档/已完成归档/归档到 TASKS-done.md 但 TASKS-done.md 查不到
        if ARCHIVE_CLAIM_RE.search(title):
            n = norm_title(title)
            if n not in archive_titles:
                ahead_status.append(
                    f"- **L{sec['line']}** `{title[:60]}`：标题含「归档」但 TASKS-done.md 无对应小节 → 状态超前/未落归档"
                )

    # 报告
    today = datetime.now().strftime("%Y%m%d")
    report_dir = REPO / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / f"tasks-verify-report-{today}.md"
    lines_out = [
        "# TASKS.md 完成度校验报告",
        "",
        f"> 生成：{datetime.now().strftime('%Y-%m-%d %H:%M')}（scripts/tasks_verify.py）",
        "",
        "## 统计",
        f"- TASKS.md 共 {len(sections)} 个 ## 小节 / hash 引用 {stats['total_hash_refs']} 个（去重后）",
        f"- 不在 origin/main 的 hash：{stats['not_in_main']} 个；其中查无此 commit（悬空）：{stats['no_such']} 个",
        "",
        "## ① 悬空 hash 但功能在 main / 需人工确认（建议更新 hash 或归档）",
        "",
    ]
    lines_out += dangling_but_live if dangling_but_live else ["（无）", ""]
    lines_out += ["", "## ② 漏标（已上线仍标待办，建议改标 ✅ + 归档）", ""]
    lines_out += missing_labels if missing_labels else ["（无）", ""]
    lines_out += ["", "## ③ 状态超前（标题写已归档但实际未在 TASKS-done.md）", ""]
    lines_out += ahead_status if ahead_status else ["（无）", ""]
    lines_out += [
        "",
        "> 说明：① 的「功能词命中」为启发式判断（git grep origin/main 标题关键词），可能漏判/误判，",
        "> 人工确认后：hash 确实过期 → 更新 TASKS 或跑 tasks_archive.py 归档；功能真未上线 → 改标待办。",
        "> ②/③ 由 tasks_archive.py 按标题 done 标记自动归档，漏标项需人工/后续轮次改标后归档。",
        "",
    ]
    report.write_text("\n".join(lines_out), encoding="utf-8")
    log(f"[done] 报告已写 {report}")
    log(f"  ① 悬空 hash 但功能在 main/需人工: {len(dangling_but_live)} 条")
    log(f"  ② 漏标: {len(missing_labels)} 条")
    log(f"  ③ 状态超前: {len(ahead_status)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
