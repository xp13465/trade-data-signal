#!/usr/bin/env python3
"""check_task_state.py - 任务状态一致性机检脚本(2026-09-06 用户拍板根治)

目的: 根治「同一任务事实多处各写各的」导致的状态漂移。2026-09-06 三事故复盘:
  #36 北交所宽度宇宙拍板结果没落档 + 僵尸巡检 cron 挂着, 造成「待拍板」误判;
  #81 已关闭但 TASKS 顶部曾残留远期指针;
  FAPI 评估 09-04 产出 09-06 才 commit(落档不及时)。
数据一致性有 check_data_integrity 挂 deploy 机检, 任务状态零机检 -> 本脚本补位。

对账维度:
  A. pending-index 编号完整性: docs/pending-features-index.md 表格行编号
     唯一/无重复/乱序(跳号异常可容忍, 只告警)/状态列非空。
  B. TASKS 交接日志编号对账: 扫 TASKS.md「📍 当前会话状态」+「📋 待办」两段提取 #N:
     ① 幽灵编号 = TASKS 里提到的 #N 不在 pending-index / done-list / archive
        (docs/tasks-done-list.md / docs/archive/TASKS-done.md) 任一存在 -> FAIL
     ② 残留关闭指针 = 编号已关闭/已完成(pending 状态列 ∈ CLOSED_STATUSES, 或在
        done-list/archive 完成)但 TASKS 仍作远期/待办指针提及 -> FAIL
        (例外: done-list 引用编号 + 已关闭上下文标注(如「勿再列为/已完成 done-list」
        视为正常, 不告警)。
  C. 僵尸巡检 cron 检测: .claude/scheduled_tasks.json 里 prompt 含「巡检兜底」
     /「agent-progress」的巡检 cron, 查其进度文件 /tmp/agent-progress-*.md:
     不存在 或 mtime > 7 天 = 疑似僵尸(任务早结束 cron 未删), 建议 CronDelete。
     不自动删, 只报告。

输入依赖:
  - docs/pending-features-index.md   (编号+状态列=任务状态唯一权威, §23.12 单一事实源)
  - TASKS.md                          (顶部交接日志 + 待办/远期段)
  - docs/tasks-done-list.md           (完成文件)
  - docs/archive/TASKS-done.md        (归档/关闭记录)
  - .claude/scheduled_tasks.json      (cron 清单)

输出: 人类可读报告(每项 ok/warn/fail + 汇总), 漂移含定位行号/编号/建议动作。
退出码: 0=全过(含 warn), 1=有 fail(漂移, 挂 deploy 阻断), 2=有 warn 且 --strict。

重跑命令:
  python scripts/check_task_state.py                 # 全量对账(只读, 不改任何文件)
  python scripts/check_task_state.py --strict        # warn 当 fail
  python scripts/check_task_state.py --deploy-mode   # deploy 接入(非0退出阻断)
  python scripts/check_task_state.py --repo DIR      # 指定仓库根(自测/沙箱用)

日常挂载: 每日 cron + deploy 前 check(与 check_data_integrity 同链), FAIL 阻断上线。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ── 阈值常量 ──────────────────────────────────────────────────────────────────
ZOMBIE_CRON_STALE_DAYS = 7          # 巡检进度文件 mtime 超过 7 天 = 疑似僵尸 cron
ZOMBIE_CRON_STALE_SECS = ZOMBIE_CRON_STALE_DAYS * 86400

# pending-index 中视为「已关闭/已完成」的状态关键词(命中即不得再作远期/待办指针)
CLOSED_STATUSES = [
    "已完成", "已关闭", "已合 main", "已合main", "已上线", "已归档", "已拍板关闭",
]

# TASKS 行内出现这些词 = 该行是对已完成/关闭的上下文标注(正常, 不告警残留指针)
CLOSED_CONTEXT_MARKERS = [
    "已完成", "已关闭", "已合 main", "已合main", "已上线", "done-list", "TASKS-done.md",
    "勿再", "已销号", "已实施", "拍板关闭", "已归档", "✅", "完成", "关闭记录", "已实施上线",
]

# TASKS 行内出现这些词 = 该行是把编号当「远期/待办/待跟进」指针(触发残留指针检查)
FORWARD_POINTER_MARKERS = [
    "待跟进", "待办", "远期", "待用户拍板", "等用户拍板", "待派", "待实施",
    "待排期", "待观察", "pending #", "在跑", "进行中", "拍板材料", "待安排",
]

# 巡检 cron prompt 识别: 巡检兜底(XXX) 或 显式 /tmp/agent-progress-*.md 路径
PROGRESS_PATH_RE = re.compile(r"/tmp/agent-progress-([A-Za-z0-9._-]+)\.md")
PATROL_NAME_RE = re.compile(r"巡检兜底\(([A-Za-z0-9._-]+)\)")

# TASKS 扫描的段标题关键字
SECTION_STATUS_TITLE = "📍 当前会话状态"
SECTION_TODO_TITLE = "📋 待办"


# ── 校验结果 ──────────────────────────────────────────────────────────────────
class CheckResult:
    """单个校验函数的返回结果。"""
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"

    def __init__(self, name: str, status: str, msg: str = "", detail: list[str] | None = None):
        self.name = name
        self.status = status
        self.msg = msg
        self.detail = detail or []

    def __repr__(self):
        return f"CheckResult({self.name!r}, {self.status!r}, {self.msg!r})"


def _ok(name: str, msg: str = "", detail: list[str] | None = None) -> CheckResult:
    return CheckResult(name, CheckResult.OK, msg, detail)


def _warn(name: str, msg: str, detail: list[str] | None = None) -> CheckResult:
    return CheckResult(name, CheckResult.WARN, msg, detail)


def _fail(name: str, msg: str, detail: list[str] | None = None) -> CheckResult:
    return CheckResult(name, CheckResult.FAIL, msg, detail)


# ── 读取工具 ──────────────────────────────────────────────────────────────────
def _read_text(path: Path) -> str | None:
    """安全整读文本文件, 失败返回 None。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _load_json(path: Path):
    """安全加载 JSON, 返回 (data, error_msg)。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"文件不存在: {path}"
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {path}: {e}"
    except Exception as e:  # noqa: BLE001
        return None, f"读取失败: {path}: {type(e).__name__}: {e}"


def _table_rows(text: str) -> list[tuple[int, int, str]]:
    """从 pending-index 表格文本提取编号行。

    返回 [(行号, 编号, 状态列)], 只认 `| N |` 开头的表格数据行(忽略表头/分隔行)。
    状态列 = 最后一个非空单元格(鲁棒处理行尾多 `|` / 行内嵌套 `|` 的脏行)。
    """
    rows: list[tuple[int, int, str]] = []
    for ln, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\|\s*(\d+)\s*\|", line)
        if not m:
            continue
        num = int(m.group(1))
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 2:
            status = ""
        else:
            # parts[0]='' parts[-1]=''(或尾空格), 状态列=第一个/最后一个非空单元格
            status = next((c for c in reversed(cells) if c), "")
        rows.append((ln, num, status))
    return rows


def _collect_hashes(path: Path) -> set[int]:
    """提取文本中所有 #N 编号(用于 done-list/archive 的合法编号集)。"""
    text = _read_text(path)
    if text is None:
        return set()
    return {int(x) for x in re.findall(r"#(\d{1,3})\b", text)}


def _section_lines(text: str, heading_substr: str) -> list[tuple[int, str]] | None:
    """提取从指定一级段标题(含 heading_substr)到下一个一级段(## )的行。

    返回 [(行号, 行内容)]; 段标题未找到返回 None(容错: 格式变化不崩溃)。
    """
    lines = text.splitlines()
    start = None
    for i, l in enumerate(lines):
        if l.startswith("## ") and heading_substr in l:
            start = i
            break
    if start is None:
        return None
    out: list[tuple[int, str]] = []
    for i in range(start, len(lines)):
        if i > start and lines[i].startswith("## "):
            break
        out.append((i + 1, lines[i]))
    return out


# ── A. pending-index 编号完整性 ───────────────────────────────────────────────
def check_pending_index(repo: Path) -> CheckResult:
    """A 维度: 编号唯一/无重复/乱序告警/状态列非空。"""
    name = "pending_index"
    p = repo / "docs" / "pending-features-index.md"
    text = _read_text(p)
    if text is None:
        return _fail(name, f"pending-index 不可读(单一事实源缺失): {p}")

    rows = _table_rows(text)
    if not rows:
        return _fail(name, f"pending-index 无表格行 `| N |`: {p}")

    detail_fail: list[str] = []
    detail_warn: list[str] = []

    # ① 编号重复
    seen: dict[int, list[int]] = {}
    for ln, num, _st in rows:
        seen.setdefault(num, []).append(ln)
    dups = {n: ls for n, ls in seen.items() if len(ls) > 1}
    if dups:
        for n, ls in dups.items():
            detail_fail.append(f"编号 #{n} 重复出现 {len(ls)} 次: 行 {ls}")

    # ② 跳号异常(可容忍, 只告警): 编号超出合理区间 = 疑似抄错/格式破坏。
    # 注: 不做全局升序检查——pending-index 按「模块」组织, 模块内编号不保证全局递增
    # (如 #96/#97 在模块十六前部的行, #56/#62/#65-72/#79-91 等模块十六行在其后),
    # 且完成项会被移除产生大量正常空号; 全局乱序在该结构下无意义, 只会误报。
    for ln, num, _st in rows:
        if num > 500 or num < 1:
            detail_warn.append(f"行 L{ln} 编号 #{num} 超出合理区间(1-500, 疑似抄错)")

    # ③ 状态列非空
    empty_status = [(ln, num) for ln, num, st in rows if not st]
    if empty_status:
        for ln, num in empty_status[:8]:
            detail_fail.append(f"行 L{ln} 编号 #{num} 状态列为空")
        if len(empty_status) > 8:
            detail_fail.append(f"... 共 {len(empty_status)} 行状态列为空")

    max_num = max((num for _ln, num, _st in rows), default=0)
    if detail_fail:
        return _fail(name, f"pending-index 编号完整性 FAIL({len(detail_fail)} 处): "
                           f"{len(rows)} 行编号 至 #{max_num}", detail_fail)
    if detail_warn:
        return _warn(name, f"pending-index 编号完整性 OK, 但有 {len(detail_warn)} 处告警"
                           f"(共 {len(rows)} 行, 编号至 #{max_num})", detail_warn)
    return _ok(name, f"pending-index 编号完整性 OK({len(rows)} 行, 编号唯一, 状态列全非空, 至 #{max_num})")


# ── B. TASKS 交接日志编号对账 ─────────────────────────────────────────────────
def check_tasks_references(repo: Path) -> CheckResult:
    """B 维度: 幽灵编号 + 残留关闭指针。"""
    name = "tasks_refs"
    tasks_p = repo / "TASKS.md"
    tasks_text = _read_text(tasks_p)
    if tasks_text is None:
        return _fail(name, f"TASKS.md 不可读: {tasks_p}")

    done_p = repo / "docs" / "tasks-done-list.md"
    arch_p = repo / "docs" / "archive" / "TASKS-done.md"
    done_nums = _collect_hashes(done_p)
    arch_nums = _collect_hashes(arch_p)
    if not done_p.exists():
        return _fail(name, f"完成文件缺失(done-list 是合法编号集之一): {done_p}")
    if not arch_p.exists():
        return _fail(name, f"归档文件缺失(docs/archive/TASKS-done.md 是合法编号集之一): {arch_p}")

    # pending-index 表格行 -> {编号: 状态列}
    pend_rows = _table_rows(_read_text(repo / "docs" / "pending-features-index.md") or "")
    pend_status: dict[int, str] = {num: st for _ln, num, st in pend_rows}
    pend_nums = set(pend_status)

    def is_closed(n: int) -> bool:
        """编号是否"已关闭/已完成": pending 状态列命中 CLOSED, 或在完成/归档文件里。"""
        st = pend_status.get(n, "")
        if any(k in st for k in CLOSED_STATUSES):
            return True
        if n not in pend_nums and (n in done_nums or n in arch_nums):
            return True
        return False

    detail_fail: list[str] = []

    for title, section_key in ((SECTION_STATUS_TITLE, "当前会话状态"), (SECTION_TODO_TITLE, "待办/远期")):
        lines = _section_lines(tasks_text, title)
        if lines is None:
            detail_fail.append(f"TASKS 未找到「{title}」段(格式变化?), 跳过该段对账")
            continue
        for ln, line in lines:
            for m in re.finditer(r"#(\d{1,3})\b", line):
                n = int(m.group(1))
                # ① 幽灵编号
                if n not in pend_nums and n not in done_nums and n not in arch_nums:
                    detail_fail.append(
                        f"L{ln} {section_key}段 幽灵编号 #{n}: 不存在于 pending-index/done-list/archive"
                        f"(行原文: {line.strip()[:80]})")
                    continue
                # ② 残留关闭指针
                if is_closed(n) and not any(k in line for k in CLOSED_CONTEXT_MARKERS):
                    if any(k in line for k in FORWARD_POINTER_MARKERS):
                        st = pend_status.get(n, "")
                        loc = f"pending 状态列=「{st}」" if st else f"位于 {('done-list' if n in done_nums else 'archive')}"
                        detail_fail.append(
                            f"L{ln} {section_key}段 残留关闭指针 #{n}: {loc}, 但 TASKS 仍作远期/待办指针"
                            f"(行原文: {line.strip()[:80]})")

    if detail_fail:
        return _fail(name, f"TASKS 编号对账 FAIL({len(detail_fail)} 处): 幽灵编号/残留关闭指针", detail_fail)
    return _ok(name, f"TASKS 编号对账 OK({SECTION_STATUS_TITLE}/{SECTION_TODO_TITLE} 段提及编号均可在"
                     f"pending-index/done-list/archive 中找到且无残留关闭指针)")


# ── C. 僵尸巡检 cron 检测 ─────────────────────────────────────────────────────
def check_zombie_crons(repo: Path) -> CheckResult:
    """C 维度: 巡检 cron 的进度文件不存在 / 过期 = 疑似僵尸。"""
    name = "zombie_crons"
    cron_p = repo / ".claude" / "scheduled_tasks.json"
    if not cron_p.exists():
        return _warn(name, f"scheduled_tasks.json 不存在: {cron_p}(无 cron 可检, 跳过)")
    data, err = _load_json(cron_p)
    if err:
        return _warn(name, f"scheduled_tasks.json 读取失败: {err}(跳过僵尸 cron 检测)")
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        return _warn(name, f"scheduled_tasks.json 结构异常(预期 {{tasks: [...]}}), 跳过")

    now = time.time()
    detail_fail: list[str] = []
    detail_warn: list[str] = []
    patrol_count = 0
    for t in data["tasks"]:
        if not isinstance(t, dict):
            continue
        prompt = t.get("prompt") or ""
        cid = t.get("id") or "?"
        # 只检"巡检兜底"类 cron
        if "巡检兜底" not in prompt and "agent-progress" not in prompt:
            continue
        patrol_count += 1
        # 收集进度文件路径: 显式路径 / 巡检兜底(name) -> /tmp/agent-progress-<name>.md
        paths: list[Path] = []
        for m in PROGRESS_PATH_RE.finditer(prompt):
            paths.append(Path(f"/tmp/agent-progress-{m.group(1)}.md"))
        for m in PATROL_NAME_RE.finditer(prompt):
            paths.append(Path(f"/tmp/agent-progress-{m.group(1)}.md"))
        if not paths:
            detail_warn.append(f"cron {cid} 是巡检兜底但 prompt 未含可解析的 /tmp/agent-progress-*.md 路径(人工核对)")
            continue
        for pp in dict.fromkeys(paths):  # 去重保序
            if not pp.exists():
                detail_fail.append(f"cron {cid} 巡检进度文件不存在: {pp} -> 疑似僵尸(任务已结束 cron 未删), 建议 CronDelete")
                continue
            try:
                age = now - pp.stat().st_mtime
            except OSError:
                detail_warn.append(f"cron {cid} 读进度文件 mtime 失败: {pp}")
                continue
            if age > ZOMBIE_CRON_STALE_SECS:
                days = int(age // 86400)
                detail_fail.append(
                    f"cron {cid} 巡检进度文件 {pp.name} mtime 已 {days} 天未更新 > {ZOMBIE_CRON_STALE_DAYS} 天 -> "
                    f"疑似僵尸(任务早已结束 cron 未删), 建议 CronDelete; 若 agent 真卡死请主控核实")

    if detail_fail:
        return _fail(name, f"僵尸巡检 cron FAIL({len(detail_fail)} 处, 共 {patrol_count} 个巡检 cron)", detail_fail)
    msg = f"巡检 cron 检测 OK({patrol_count} 个巡检 cron 进度文件均存在且新鲜)"
    if detail_warn:
        return _warn(name, msg + f", 但有 {len(detail_warn)} 处告警", detail_warn)
    if patrol_count == 0:
        return _ok(name, "当前无巡检兜底 cron(无需检测)")
    return _ok(name, msg)


# ── 编排 ──────────────────────────────────────────────────────────────────────
def run_all_checks(repo: Path) -> list[CheckResult]:
    return [
        check_pending_index(repo),
        check_tasks_references(repo),
        check_zombie_crons(repo),
    ]


def print_result(r: CheckResult) -> None:
    if r.status == CheckResult.OK:
        print(f"  ✓ {r.name}: {r.msg}")
    elif r.status == CheckResult.WARN:
        print(f"  ⚠ {r.name}: {r.msg}")
    elif r.status == CheckResult.FAIL:
        print(f"  ✗ {r.name}: {r.msg}")
    for d in r.detail:
        print(f"      · {d}")


def determine_exit_code(results: list[CheckResult], strict: bool) -> int:
    fails = [r for r in results if r.status == CheckResult.FAIL]
    warns = [r for r in results if r.status == CheckResult.WARN]
    if fails:
        return 1
    if warns and strict:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="任务状态一致性机检脚本(2026-09-06 用户拍板根治, §23.12 单一事实源)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码: 0=全过(含 warn)  1=有 fail(漂移, deploy 阻断)  2=有 warn 且 --strict",
    )
    parser.add_argument("--strict", action="store_true", help="warn 当 fail(exit 2)")
    parser.add_argument("--deploy-mode", action="store_true", help="deploy 接入(非0退出阻断, 与 check_data_integrity 同链)")
    parser.add_argument("--repo", metavar="DIR", default=None, help="指定仓库根目录(默认=脚本所在仓根)")
    args = parser.parse_args()

    if args.repo:
        repo = Path(args.repo).absolute()
    else:
        repo = Path(__file__).resolve().parent.parent

    print("=== 任务状态一致性对账 ===")
    print(f"  repo:            {repo}")
    print()

    results = run_all_checks(repo)
    for r in results:
        print_result(r)

    fails = [r for r in results if r.status == CheckResult.FAIL]
    warns = [r for r in results if r.status == CheckResult.WARN]
    oks = [r for r in results if r.status == CheckResult.OK]
    print()
    print(f"=== 汇总: {len(oks)} ok / {len(warns)} warn / {len(fails)} fail ===")
    if fails:
        print("⚠ 存在任务状态漂移, FAIL 阻断上线(挂 deploy 链), 逐项修后重跑。")

    return determine_exit_code(results, args.strict)


if __name__ == "__main__":
    sys.exit(main())