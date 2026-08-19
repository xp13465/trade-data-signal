#!/usr/bin/env python3
"""tasks_archive.py - TASKS.md 定期归档压缩脚本（2026-08-11 建立，机制见 docs/tasks-archive-maintain.md）

目标：TASKS.md 因历史已完成小节 + 会话状态超长行堆积而膨胀（曾 429KB），本脚本：
  ① 剪切归档：✅/已完成/已上线/全闭环 标题的已完成历史小节（level 2/3/4，2026-08-19 扩 level3）
     + `### 会话状态(日期)`/`### 每日总结(日期)`
     历史块 + 待办小节内旧会话状态块 + `#### ... 已完成` 锚点 -> append 到 docs/archive/TASKS-done.md
  ② 压缩超长行：`## 📍 当前会话状态` 小节的 `**最后更新**`/`**进行中**`/`**前·最后更新**` 超长行
     （>400ch）压缩为摘要（保留最新状态关键信息+日期+指向 git history 说明）
  ③ 待办保护：`#### 待办` 锚点 + 其下活跃待办必须保留（scripts/feishu_ws_listener.py 会在锚点后
     插入 `- [ ] (飞书 ...)` 待办行，本脚本不破坏该兼容）；归档小节中的 `- [ ]` 行 + `### 保留*（不动）`
     子节的待办 bullet 自动并入待办小节，不丢任何活跃待办（2026-08-08 教训：量子科技第4层曾丢）
  ④ 幂等：归档即从 TASKS.md 移除，重跑不重复；append 前按 内容hash+规范化标题 双重去重
  ⑤ 原子写：临时文件 + os.replace；单块处理异常不中断整体

用法：python3 scripts/tasks_archive.py [--dry-run]
  --dry-run：只打印将归档/压缩的块与预期大小，不写文件
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TASKS = REPO / "TASKS.md"
ARCHIVE = REPO / "docs" / "archive" / "TASKS-done.md"

MAX_LINE = 400          # 超长行阈值（压缩对象 = >MAX_LINE 的 最后更新/进行中/前·最后更新 行）
KEEP_CHARS = 500        # 压缩摘要保留前缀字符数
TODO_ANCHOR = "#### 待办"
DONE_MARKERS = ("已完成", "已上线", "全闭环", "已归档")
DONE_EMOJI = "✅"
SESSION_STATUS_RE = re.compile(r"^\*\*(最后更新|前·最后更新|进行中)")
DATE_HEAD_RE = re.compile(r"^(\*\*)?\d{4}-\d{2}-\d{2}")
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)")
SESSION_BLOCK_RE = re.compile(r"^(会话状态|每日总结)\(20\d\d-")
KEEP_SECTION_RE = re.compile(r"^###\s*保留(真待办|远期/搁置|当前在跑/待实施)")
TODO_ITEM_RE = re.compile(r"^\-\s*\[ \]")
STALE_REF_RE = re.compile(r"（L\d+(-\d+)?）")
TRAIL_PAREN_RE = re.compile(r"[（(].*?[)）]\s*$")
LEAD_EMOJI_RE = re.compile(r"^[✅📋🆕⏸🟢🔄🔴🔵🟡]+")
LEAD_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s*")


def log(msg: str) -> None:
    print(msg, flush=True)


def norm_text(s: str) -> str:
    """规范化文本（去空白）用于内容 hash 去重。"""
    return re.sub(r"\s+", "", s)


def content_hash(text: str) -> str:
    return hashlib.sha1(norm_text(text).encode("utf-8")).hexdigest()


def norm_title(t: str) -> str:
    """规范化小节标题用于去重：去 emoji 前缀/日期前缀/尾部括号说明。"""
    t = LEAD_EMOJI_RE.sub("", t)
    t = LEAD_DATE_RE.sub("", t)
    t = TRAIL_PAREN_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def is_done_title(title: str) -> bool:
    """标题含 ✅ 或 已完成/已上线/全闭环/已归档 任一 -> 判定为已完成小节。"""
    return DONE_EMOJI in title or any(m in title for m in DONE_MARKERS)


def is_session_block(title: str) -> bool:
    return bool(SESSION_BLOCK_RE.match(title))


def heading_info(line: str):
    m = HEADING_RE.match(line)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def block_extent(lines: list[str], start: int, level: int, cap: int | None = None) -> int:
    """返回从 start（heading 行）开始、到下一个 level<=level 的 heading 前的结束下标（不含）。"""
    j = start + 1
    while j < len(lines):
        h = heading_info(lines[j])
        if h and h[0] <= level:
            break
        j += 1
    if cap is not None:
        j = min(j, cap)
    return j


def compress_status_line(line: str) -> str:
    """压缩 最后更新/进行中/前·最后更新 超长行为摘要（单行）。"""
    m = SESSION_STATUS_RE.match(line)
    if not m or len(line) <= KEEP_CHARS + 60:
        return line
    # 幂等：行内已含压缩标记「本行原」= 已被本脚本/人工压缩过，不再重复压缩，
    # 保留标记后可能追加的最新状态（如主控在压缩摘要后补写的 AI 预测缺口核实），避免二次压缩丢尾部
    if "本行原" in line:
        return line
    head = line[:KEEP_CHARS]
    # 在自然断点（句号/括号/分号）处截断，避免句子被腰斩
    cut = max(head.rfind("。"), head.rfind("）"), head.rfind("；"), head.rfind(";"))
    if cut > 100:
        head = head[: cut + 1]
    marker = (
        f"……【本行原 {len(line)} 字符超长，已压缩为摘要（保留最新状态）；"
        f"完整历史见 git log -- TASKS.md 或 NOTES §48】"
    )
    # ⚠️ 必须补尾换行，否则压缩行输出后缺 \n，会把「下一行」熔成同一物理行(#77 L32 熔行根因)
    return head + marker + "\n"


def extract_live_todos(block: list[str]) -> list[str]:
    """从待归档块提取活跃待办：`- [ ]` 复选框行 + `### 保留*（不动）` 子节下的 bullet 行。"""
    out: list[str] = []
    in_keep_sub = False
    for ln in block:
        h = heading_info(ln)
        if h:
            in_keep_sub = bool(KEEP_SECTION_RE.match(h[1]))
            continue
        if in_keep_sub:
            s = ln.strip()
            if s.startswith("-") or s.startswith("*"):
                cleaned = STALE_REF_RE.sub("", ln.rstrip("\n"))
                cleaned = re.sub(r"[（(]不动[)）]\s*$", "", cleaned).rstrip()
                if cleaned.strip() and cleaned.strip() != "-":
                    out.append(cleaned.rstrip() + "\n")
        elif TODO_ITEM_RE.match(ln):
            out.append(ln.rstrip("\n") + "\n")
    return out


def archive_append(blocks: list[str], dry: bool) -> None:
    """把归档块 append 到 docs/archive/TASKS-done.md（内容hash + 规范化标题双重去重）。"""
    if not blocks:
        return
    if not ARCHIVE.exists():
        if dry:
            log(f"[dry] 将创建 {ARCHIVE}")
            return
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE.write_text("# TASKS 已完成项归档\n\n", encoding="utf-8")
    existing = ARCHIVE.read_text(encoding="utf-8")
    existing_hashes: set[str] = set()
    existing_titles: set[str] = set()
    lines = existing.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        h = heading_info(lines[i])
        if h:
            if h[0] in (1, 2):
                existing_titles.add(norm_title(h[1]))
            if h[0] == 2:
                j = block_extent(lines, i, 2)
                existing_hashes.add(content_hash("".join(lines[i:j])))
                i = j
                continue
        i += 1

    today = os.getenv("TASKS_ARCHIVE_DATE", "2026-08-11")
    batch_head = f"## 归档批次 {today}（tasks_archive.py 自动归档，机制见 docs/tasks-archive-maintain.md）\n"
    parts: list[str] = []
    if batch_head not in existing:
        parts.append(batch_head + "\n")
    appended = 0
    skipped = 0
    for b in blocks:
        h = heading_info(b[0])
        title = h[1] if h else ""
        ch = content_hash("".join(b))
        if ch in existing_hashes or norm_title(title) in existing_titles:
            skipped += 1
            continue
        parts.append("".join(b).rstrip("\n") + "\n\n")
        existing_hashes.add(ch)
        existing_titles.add(norm_title(title))
        appended += 1
    if not parts:
        log(f"[archive] 全部 {len(blocks)} 块已存在于 TASKS-done.md（去重跳过），无新增 append")
        return
    if dry:
        log(f"[dry] 将 append {appended} 块 / 跳过 {skipped} 块 到 {ARCHIVE}")
        return
    new_content = existing + ("\n" if not existing.endswith("\n") else "") + "".join(parts)
    tmp = ARCHIVE.with_name(ARCHIVE.name + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    os.replace(tmp, ARCHIVE)
    log(f"[archive] 已 append {appended} 块（跳过 {skipped}）到 {ARCHIVE}")


class Renderer:
    """递归渲染 TASKS.md：按标题层级决定 保留/归档/压缩，归档块收集到 self.archive_blocks。"""

    def __init__(self, lines: list[str]):
        self.lines = lines
        self.out: list[str] = []
        self.archive_blocks: list[list[str]] = []
        self.live_todos: list[str] = []
        self.compressed: list[tuple[int, str]] = []

    def render(self, start: int = 0, cap: int | None = None) -> None:
        i = start
        end = cap if cap is not None else len(self.lines)
        while i < end:
            h = heading_info(self.lines[i])
            if not h:
                self.out.append(self.lines[i])
                i += 1
                continue
            level, title = h
            j = block_extent(self.lines, i, level, cap=end)
            block = self.lines[i:j]

            if level == 4 and title == TODO_ANCHOR:
                # #### 待办：保留锚点 + 活跃项，归档其后旧会话状态块
                self.out.append(self.lines[i])
                k = i + 1
                while k < j:
                    if DATE_HEAD_RE.match(self.lines[k].lstrip("- ").lstrip()):
                        self._archive(block[k:j])
                        break
                    self.out.append(self.lines[k])
                    k += 1
                i = j
                continue

            if level == 2 and title.startswith("📍"):
                # ## 📍 当前会话状态：保留本块，压缩块内 最后更新/进行中/前·最后更新 超长行
                self.out.append(self.lines[i])
                k = i + 1
                while k < j:
                    hk = heading_info(self.lines[k])
                    if hk:
                        # 块内嵌套 #### 已完成锚点 / #### 待办：递归渲染处理
                        self.render(k, cap=j)
                        k = j
                        break
                    if SESSION_STATUS_RE.match(self.lines[k]) and len(self.lines[k]) > KEEP_CHARS + 60:
                        newline = compress_status_line(self.lines[k])
                        if newline != self.lines[k]:
                            self.compressed.append((k + 1, newline.rstrip("\n")))
                        self.out.append(newline)
                    else:
                        self.out.append(self.lines[k])
                    k += 1
                i = j
                continue

            # 归档判定：level 2/3/4 已完成标题 或 任意层会话状态历史块
            #   (2026-08-19 扩 level3：`### P2-新-X ✅` 等老已完成小块也归档，仅归 is_done_title 明确
            #    标注 已完成/已上线/全闭环/已归档/✅ 的；`### 保留*`/进行中/近期/下轮起点 非已完成不归)
            if (level in (2, 3, 4) and is_done_title(title)) or (level in (2, 3, 4) and is_session_block(title)):
                self._archive(block)
                i = j
                continue

            # 保留：heading + 递归渲染内部
            self.out.append(self.lines[i])
            self.render(i + 1, cap=j)
            i = j

    def _archive(self, block: list[str]) -> None:
        self.archive_blocks.append(block)
        for lt in extract_live_todos(block):
            if lt.strip() not in [x.strip() for x in self.live_todos]:
                self.live_todos.append(lt)

    def merge_live_todos(self) -> None:
        """把提取的活跃待办并入 #### 待办 小节（锚点后活跃项之后、小节末尾之前；去重）。"""
        if not self.live_todos:
            return
        anchor_idx = None
        for idx, ln in enumerate(self.out):
            if ln.strip() == TODO_ANCHOR:
                anchor_idx = idx
                break
        if anchor_idx is None:
            self.out += ["\n### 保留待办（tasks_archive.py 自动并入）\n"] + self.live_todos
            return
        # 待办小节末尾 = 锚点后第一个 ## 级 heading（或文件末尾）
        insert_idx = len(self.out)
        for idx in range(anchor_idx + 1, len(self.out)):
            h = heading_info(self.out[idx])
            if h and h[0] == 2:
                insert_idx = idx
                break
        existing_texts = {norm_text(ln) for ln in self.out[anchor_idx + 1 : insert_idx]}
        new_items = [lt for lt in self.live_todos if norm_text(lt) not in existing_texts]
        if not new_items:
            return
        merged = self.out[:insert_idx]
        if insert_idx < len(self.out) and not merged[-1].endswith("\n\n"):
            merged.append("\n")
        merged.append("### 保留待办（tasks_archive.py 自动并入，防归档丢待办）\n")
        merged.extend(new_items)
        merged.append("\n")
        merged.extend(self.out[insert_idx:])
        self.out = merged


def main() -> int:
    ap = argparse.ArgumentParser(description="TASKS.md 归档压缩")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写文件")
    args = ap.parse_args()
    dry = args.dry_run

    if not TASKS.exists():
        log(f"ERROR: {TASKS} 不存在")
        return 1

    lines = TASKS.read_text(encoding="utf-8").splitlines(keepends=True)
    orig_size = os.path.getsize(TASKS)

    r = Renderer(lines)
    r.render()
    r.merge_live_todos()

    new_size = sum(len(l.encode("utf-8")) for l in r.out)
    log(f"[info] 原大小 {orig_size} B；归档块 {len(r.archive_blocks)} 个；"
        f"压缩超长行 {len(r.compressed)} 条；提取活跃待办 {len(r.live_todos)} 条")
    for ln_no, newtxt in r.compressed:
        log(f"  压缩 L{ln_no}: 摘要 = {newtxt[:90]!r}")
    for b in r.archive_blocks:
        h = heading_info(b[0])
        log(f"  归档: [{h[0]}#] {h[1][:70]}")
    log(f"[info] 压缩后预计大小 {new_size} B（{(new_size / orig_size * 100):.1f}%）")

    if dry:
        log("[dry] 不写文件")
        return 0

    # 原子写 TASKS.md
    tmp = TASKS.with_name(TASKS.name + ".tmp")
    tmp.write_text("".join(r.out), encoding="utf-8")
    os.replace(tmp, TASKS)

    # append 归档（须在 TASKS.md 写完后调用，避免中途失败留半成品）
    if r.archive_blocks:
        archive_append(r.archive_blocks, dry=False)

    after = os.path.getsize(TASKS)
    log(f"[done] TASKS.md {orig_size} -> {after} B（{(after / orig_size * 100):.1f}%）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
