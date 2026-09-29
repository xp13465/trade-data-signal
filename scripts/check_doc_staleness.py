#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_doc_staleness.py — 文档「时点/调度口径」一致性机检(2026-09-29 建,B 线 launchd 扫除第 5 轮根治)

背景: 全仓 launchd → 云上 systemd timer 迁移后, 文档口径曾 4 轮 FAIL(改了邻行漏紧邻行)。
执行方(含 AI)用眼睛扫全仓文档必然会漏, 只有机器不会漏。本脚本把「过时口径」做成 merge 前
硬闸门, 根治「改邻行漏紧邻行」老毛病。

触发词: 发版/merge main/任何文档含 launchd·launchctl·LaunchAgents·15:33·废弃 unit 名的改动。

过时口径 = 现行规范类文档里出现以下任一断言, 且不在豁免上下文:
  - `launchd` / `launchctl` / `~/Library/LaunchAgents`(生产定时任务已迁云上 systemd timer)
  - `15:33`(全量采集 15:33 已实测否决, 后移 17:50, 权威见 scripts/README.md 定时任务配置)
  - 已废弃 unit 名(如 com.trade.update-all 作为现行时点, 现行 unit=trade-update-all)

豁免(避免误伤大量历史陈述):
  - 路径豁免: docs/archive/**, docs/deploy/migration-*, NOTES.md
  - 行内上下文豁免(历史陈述/迁移注/否定声明):
      「已废弃」「已否决」「历史存档」「历史安装存档」「已迁移」「迁云」「迁移」「历史」
      「存档」「已迁」「迁移注」「原 launchd」(对照)/「launchd 已废弃」「查 launchctl 是错的」
      「代理进程」(命中率统计注释)/「本机用」(agent-inbox-watcher 例外)
  - 显式豁免标记: 行内含 `<!-- staleness-ok: ... -->` 视为该行通过(可在豁免规则误判时手动标注)
  - 机器自动生成块豁免: `<!-- token-cache-*-begin -->` … `<!-- token-cache-*-end -->` 界定块内的行整块跳过。
    块内是逐字引用的 commit 标题/机器采集值(token-cache-stats 每日 23:30 自动追加), 非文档口径陈述, 不按口径判过时。

⚠️ 行级豁免 vs 词级豁免(2026-09-29 评审建议 3 评估, 有意保留行级):
  行级豁免 = 一行含任一豁免词即整行跳过。词级豁免(只抠掉豁免词覆盖片段, 剩余文本仍跑 stale 检测)
  实测当前树会引入 ~80 处误报——典型是「launchd 已废弃」「已切 update_all」这类否定/历史对照的正确
  现行表述: 词级抠掉「已废弃」后, 行内 launchd/launchctl/15:33 字面仍残留被误抓。故保留行级豁免,
  这是有意权衡: 同一行内「豁免词 + 真过时断言」并存未见实际受害行(reviewer 复核确认), 若未来出现
  可在该行补 `<!-- staleness-ok: ... -->` 精确定位放行, 而非全局改词级放大误报面。

用法:
  python3 scripts/check_doc_staleness.py [--root <repo>] [--list-files]
    --root      仓库根(默认脚本所在目录的上级)
    --list-files 只列出将被扫描的文件, 不检查(调试豁免范围用)
  退出码: 0=通过(无非豁免命中), 1=FAIL(有过时口径命中, 阻断 merge)

挂链: scripts/main-merge.sh merge 后/bump 后/push 前, 与 §7.5 critical-css 双源机检同处。
"""
import argparse
import os
import re
import sys

# --- 权威时点锚点(与 docs/deploy/systemd-units-20260912.md + scripts/README.md 一致) ---
# 过时字面量 → 现行口径说明(FAIL 时报给用户看)
STALE_PATTERNS = [
    # (正则, 现行口径说明)
    (r"\b15:33\b", "全量采集 15:33 已实测否决后移 17:50(baostock 主源 ~17:45 才发布当日数据, 见 scripts/README.md 定时任务配置)"),
    (r"launchctl", "生产定时任务已迁云上 systemd timer(ssh 云上 `systemctl list-timers`), 本机 mac 纯开发不跑生产定时任务, 查 launchctl 是错的"),
    (r"LaunchAgents", "生产定时任务已迁云上 systemd timer, 本机不配置 ~/Library/LaunchAgents(仅 agent-inbox-watcher 等本机开发工具例外)"),
    (r"\bcom\.trade\.[a-z0-9-]+\.plist\b", "历史 launchd plist 已迁云上 systemd timer(unit=trade-<name>), 现行清单见 docs/deploy/systemd-units-20260912.md"),
]
# launchd 单独处理(它出现在「launchd 已废弃」等否定声明中, 需上下文豁免后才是 stale)
LAUNCHD_RE = re.compile(r"launchd")

# 行内上下文豁免词(命中即认为该行是历史陈述/迁移注/否定声明/本机工具例外, 不算过时口径)
CONTEXT_EXEMPT_WORDS = [
    # 原词
    "已废弃", "已否决", "历史存档", "历史安装存档", "已迁移", "迁云", "迁移",
    "历史", "存档", "已迁", "迁移注", "原 launchd", "launchd 已废弃", "查 launchctl 是错的",
    "本机用", "本机开发", "历史 plist", "agent-inbox-watcher", "Agent Inbox", "代理进程",
    "launchd label", "历史 label", "启动/清理", "KeepAlive", "bootout", "已用 launchd",
    # 迁移对照 / 15:33 否定声明(首跑 2026-09-29 实命中新增)
    "已切", "已切换", "后移", "故后移", "实测否决", "已实测否决", "采不到当日", "太早",
    "映射", "数据来源", "StartCalendarInterval", "launchd 键", "→ 阿里云", "→ systemd",
    "_launchd.log", "_launchd.err",
    # 本机开发工具例外(自备份 / 代理 / 信号桥 / agent-inbox / 飞书监听等, 生产定时任务才迁云)
    "self-backup", "自备份", "Claude 自备份", "thinking-proxy", "守护", "8899",
    "sensenova-rotate", "sensenova-healthcheck", "SENSENOVA", "agent-inbox", "信号桥",
    "signal-bridge", "feishu_ws_listener", "lark-oapi", "长连接", "watcher", "本机模板",
    # token-cache-stats = 本机 Claude 开发环境专属「不迁」任务(权威: docs/deploy/systemd-units-20260912.md
    # L14/L1509), 用 launchd 是现行正确口径(claude-work-mode/README.md 命中), 非过时。
    # com.trade.token-cache-stats 同上(launchd 任务全名)。
    "token-cache-stats", "com.trade.token-cache-stats",
    # 历史 commit 记录行: claude-work-mode/README.md 版本/改动日志表引用历史 commit
    # 「根治环境幻觉-定时任务清单改云上systemd timer(本机纯开发不跑launchd)」——该行是 commit 存档标题,
    # 描述的是「launchd 已废弃」的迁移事实本身, 不是断言现行用 launchd, 非过时。
    "本机纯开发不跑launchd",
    # 任务索引历史状态(已完成/已关闭/待派/待实施 = 描述历史任务, 非现行调度口径)
    "已完成", "已关闭", "待派", "待实施",
    # systemd-units 权威锚点迁移对照词(对照/残留/阶段4 说明)
    "本机各", "本机无", "阶段4", "残留", "原本", "非本文件范围", "Linux 适配",
    # 教训条目引用归档(原文全量在 docs/archive, 行内仅为索引指针)
    "archive:",
]

# 路径豁免(整文件跳过; 前缀匹配)
PATH_EXEMPT_PREFIXES = [
    "docs/archive/",
    "docs/deploy/migration-",
    "docs/deploy/migration-inventory-",
    "docs/deploy/migration-operation-log-",
    "docs/deploy/migration-data-bootstrap-plan-",
    # uumit-knowledge = 知识商品生成目录(43 个文件已 tracked, .gitignore L281 在其后追加)。
    #   reviewer 复核(2026-09-29): 旧注释称「不在版本控制」与实测不符(实际 43 tracked);
    #   实测纳入扫描当前 0 命中(内容已被 B 线本轮修复)。保留豁免理由变为:
    #   ①知识正文是「对外知识商品」, 含大量外部产品/历史性引用, 非本仓「调度口径」受控文档,
    #      机检语义=拦「本仓定时任务口径」过时, 对知识正文是错位;
    #   ②其口径一致性由知识商品生成流程单独管理(生成时即按当前口径产出)。
    #   若未来知识商品内出现 launchd/15:33 字面, 属内容范畴, 由生成流程负责, 不由本闸门拦。
    "docs/uumit-knowledge/",
]
PATH_EXEMPT_FILES = [
    "NOTES.md",
]

# 权威锚点文件: 即使文件名带日期后缀(命中历史快照豁免), 也强制扫描。
# systemd-units-20260912.md = 现行 systemd 单元权威清单, 其 launchd 命中均为迁移对照/日志文件名,
# 靠行内豁免词放行, 不能被整文件豁免(否则权威锚点自身过时口径将无人拦截)。
FORCE_SCAN_FILES = [
    "docs/deploy/systemd-units-20260912.md",
]

# 文件名带日期后缀 = 历史快照文档(落档/审计/调研/实施方案/修复记录), 整文件豁免。
# 支持两种格式: -20260912(紧凑6位) 与 -2026-09-25(横线分隔)
DATE_SUFFIX_RE = re.compile(r"-(?:20\d{6}|20\d{2}-\d{2}-\d{2})\.md$")

# 无日期后缀但内容为「历史方案/调研/审计/实施快照」的文档(整文件豁免)。
# 这类文档是「当时的真实记录」(当时确实是 launchd/15:33), 读文件名即知非现行口径, 机检不该拦。
HISTORICAL_FILES = [
    "docs/72h-monitor-plan.md",
    "docs/architecture/safe-implementation-plan.md",
    "docs/bak-data-audit.md",
    "docs/chart-p2p3-data-source-research.md",
    "docs/chart-refactor-config-plan.md",
    "docs/feishu-bot-integration-plan.md",
    "docs/kelly/analysis/kelly-overfit-monitor-design.md",
    "docs/kelly/toggle/kelly-loss-reduction-toggle-v2-plan.md",
    "docs/ops/alert-system-evaluation.md",
    "docs/optimization-closeout-list.md",
    "docs/optimization-followup-inspection.md",
    "docs/r2-migration-implementation-report.md",
    "docs/tasks-done-list.md",
    "docs/ai-predict/ai-predict-self-growth.md",
    "docs/ai-predict/ai-predict-tts-plan.md",
    "docs/ai-predict/daily-brief-research.md",
    "docs/codex-signal-bridge.md",
    "docs/sensenova/sensenova-cooling-recovery-distribution.md",
    "docs/sensenova/sensenova-proxy-healthcheck.md",
]

# 显式豁免标记: 行内含该标记即豁免
EXEMPT_MARKER = "<!-- staleness-ok"

# 机器自动生成块(2026-09-30 自锁闸门根治): begin/end 标记界定, 块内整块豁免。
# 生成器 scripts/token_cache_stats.py --append-daily 每日 23:30 整块重写 claude-work-mode/README.md 的
# 4 个标记区块(命中率走势 trend / ASCII 柱状图 ascii / 版本改动日志 changelog / 配置快照日志 cfglog),
# 块内是逐字引用的 commit 标题(可能含 launchd/15:33 等字面)与机器采集值 = 「引用记录」而非「口径陈述」,
# 不按文档口径判过时(曾自锁: 2026-09-29 行的 commit 标题含 launchd → 之后每次 main-merge 都被本闸门拦死)。
# 标记行本身也跳过。若未来他处出现同类「机器生成引用块」(带 begin/end 标记), 追加到此表全仓生效。
MACHINE_BLOCK_MARKERS = [
    ("token-cache-trend-begin", "token-cache-trend-end"),
    ("token-cache-ascii-begin", "token-cache-ascii-end"),
    ("token-cache-changelog-begin", "token-cache-changelog-end"),
    ("token-cache-cfglog-begin", "token-cache-cfglog-end"),
]


def _is_path_exempt(relpath: str) -> bool:
    if relpath in FORCE_SCAN_FILES:
        return False
    for p in PATH_EXEMPT_PREFIXES:
        if relpath.startswith(p):
            return True
    for f in PATH_EXEMPT_FILES:
        if relpath == f:
            return True
    for f in HISTORICAL_FILES:
        if relpath == f:
            return True
    if DATE_SUFFIX_RE.search(relpath):
        return True
    return False


def _is_line_exempt(line: str) -> bool:
    """行级豁免: 显式标记 或 行内含历史/迁移/否定上下文词。"""
    if EXEMPT_MARKER in line:
        return True
    for w in CONTEXT_EXEMPT_WORDS:
        if w in line:
            return True
    # 日志文件名沿用(历史命名 *_launchd.log/.err/.out 或 *.log 通配, 是文件名不是 launchd 任务本体)
    if re.search(r"launchd\.(?:log|err|out|\*)", line):
        return True
    return False


def _machine_block_ranges(lines: list) -> list:
    """返回机器自动生成块的 (start, end) 0-based 行区间(含 begin/end 标记行)。

    只豁免「begin 标记与 end 标记都出现且 begin 在 end 之前」的配对块;
    begin 无配对 end(生成器中断/文件损坏)→ 该块不豁免, 防「未闭合 begin 把文件其余部分整体静默漏扫」。
    """
    begins = {b: [] for b, _ in MACHINE_BLOCK_MARKERS}
    ends = {e: [] for _, e in MACHINE_BLOCK_MARKERS}
    for idx, line in enumerate(lines):
        for b, e in MACHINE_BLOCK_MARKERS:
            if b in line:
                begins[b].append(idx)
            if e in line:
                ends[e].append(idx)
    ranges = []
    for b, e in MACHINE_BLOCK_MARKERS:
        k = 0
        eq = ends[e]
        for bi in begins[b]:
            while k < len(eq) and eq[k] <= bi:
                k += 1
            if k < len(eq):
                ranges.append((bi, eq[k]))
                k += 1
    return ranges


# 扫描范围白名单(相对仓库根的顶层前缀)。
# 根 CLAUDE.md 是全仓口径总源头, claude-work-mode/ 是 21 文件 tracked 活模板(2026-09-29 评审建议 1 纳入)。
SCOPE_BASES = ("docs", ".claude", "claude-work-mode")
SCOPE_ROOT_FILES = ("README.md", "CLAUDE.md")

# git ls-files 失败(非 git 树, 如 --root /tmp/xxx 基线验证)时 os.walk 降级的排除目录段。
# 关键: .claude/worktrees/ 下是其他 worktree 的完整仓库副本(历史/中间态快照, 非本仓受控文档),
#   os.walk 不排除会把它们全部扫进来 → 巨量假阳性(2026-09-29 P0: 主仓 1663 假命中阻断 merge)。
# 按「目录名段」匹配(rel_dir split 后任一段命中即跳过): .claude/worktrees/* 的任一路径 split 后
# 都含 worktrees 段; .git/node_modules/__pycache__/.venv 同理。曾把段写成 ".claude/worktrees"
# (含斜杠), split 后是单层段列表, "in list" 永 False → 排除失效(实测假命中扫进)。
WALK_EXCLUDE_DIR_SEGMENTS = (
    "worktrees", ".git", "node_modules", "__pycache__", ".venv",
)


def _git_ls_files_md(root: str):
    """用 git ls-files 取 tracked 清单(语义正确: 闸门只管进版本控制的文档)。
    天然排除 .claude/worktrees/(worktree 副本不 tracked)。非 git 树返回 None(调用方降级 os.walk)。

    2026-09-29 F2 修复: 裸 `git ls-files` 默认 core.quotepath=true, 中文文件名(md)输出为
    C 风格转义("docs/\\347\\220\\206..." 带引号) → l.endswith(".md") 永 False → 中文 md
    被静默漏扫(实测: 主仓扫 214 vs 干净树 215, 差 docs/理财专员使用指南.md)。先版加
    `-c core.quotepath=false` 只关非 ASCII 八进制转义, 但双引号/反斜杠/换行文件名仍走
    C-quoting → 同样静默漏扫。根治: `git ls-files -z`(NUL 分隔、不做任何转义)+
    split(b"\\x00"), 免疫全部形态; 每段 decode 用 errors="replace" 兜底非法 UTF-8。"""
    import subprocess
    try:
        out = subprocess.check_output(
            ["git", "-C", root, "ls-files", "-z"],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    names = []
    for seg in out.split(b"\x00"):
        if not seg:
            continue
        name = seg.decode("utf-8", errors="replace")
        if name.endswith(".md"):
            names.append(name)
    return names


def _collect_md_files(root: str) -> list:
    """收集受控文档 md(docs/** + .claude/** + claude-work-mode/** + 根 README.md/CLAUDE.md)。

    优先 git ls-files(tracked 清单, 不含 .claude/worktrees/ 副本);非 git 树降级 os.walk + 排除表。
    2026-09-29 P0: 原 os.walk 遍历 docs/.claude 会把 .claude/worktrees/ 下其他 worktree 的完整仓库
    副本(.claude/worktrees/**/*.md 共 3085 个)扫进来, 主仓实跑 1663 假命中 FAIL, 阻断所有 merge。
    """
    files = []

    def _in_scope(rel: str) -> bool:
        if rel in SCOPE_ROOT_FILES:
            return True
        return any(rel.startswith(base + "/") for base in SCOPE_BASES)

    tracked = _git_ls_files_md(root)
    if tracked is not None:
        for rel in sorted(tracked):
            if not _in_scope(rel):
                continue
            if not _is_path_exempt(rel):
                files.append(rel)
    else:
        for base in SCOPE_BASES:
            full = os.path.join(root, base)
            if not os.path.isdir(full):
                continue
            for dirpath, _dirnames, filenames in os.walk(full):
                rel_dir = os.path.relpath(dirpath, root)
                if any(seg in rel_dir.split(os.sep) for seg in WALK_EXCLUDE_DIR_SEGMENTS):
                    continue
                for fn in filenames:
                    if fn.endswith(".md"):
                        rel = os.path.relpath(os.path.join(dirpath, fn), root)
                        if not _is_path_exempt(rel):
                            files.append(rel)
        for rf in SCOPE_ROOT_FILES:
            if os.path.isfile(os.path.join(root, rf)) and not _is_path_exempt(rf):
                files.append(rf)
    return sorted(set(files))


def _check_file(root: str, relpath: str) -> list:
    """返回 [(行号, 原文, 现行口径说明)]。"""
    hits = []
    full = os.path.join(root, relpath)
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"  [warn] 读 {relpath} 失败: {e}", file=sys.stderr)
        return hits
    # 机器自动生成块(commit 标题引用/机器采集值)整块豁免, 非文档口径陈述
    skip = set()
    for s, e in _machine_block_ranges(lines):
        skip.update(range(s, e + 1))
    for i, line in enumerate(lines, 1):
        if (i - 1) in skip:
            continue
        if _is_line_exempt(line):
            continue
        # launchd 命中(独立判定: 上下文豁免已过滤掉历史/否定声明)
        if LAUNCHD_RE.search(line):
            hits.append((i, line.rstrip("\n"),
                         "生产定时任务已迁云上 systemd timer(37 个 trade- 前缀 .timer), launchd 已废弃"))
            continue
        for pat, desc in STALE_PATTERNS:
            if re.search(pat, line):
                hits.append((i, line.rstrip("\n"), desc))
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="文档时点/调度口径一致性机检")
    ap.add_argument("--root", default=None, help="仓库根(默认脚本所在目录的上级)")
    ap.add_argument("--list-files", action="store_true", help="只列待扫描文件, 不检查")
    args = ap.parse_args()

    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = _collect_md_files(root)

    if args.list_files:
        for f in files:
            print(f)
        return 0

    total_hits = 0
    for rel in files:
        hits = _check_file(root, rel)
        if hits:
            print(f"\n✗ {rel}")
            for lineno, text, desc in hits:
                print(f"  L{lineno}: {text}")
                print(f"     → {desc}")
                total_hits += 1

    print(f"\n扫描文件 {len(files)} 个")
    if total_hits:
        print(f"✗ 文档过时口径命中 {total_hits} 处, FAIL(§22 一致性铁律 + B 线 launchd 扫除)")
        print("  修复指引: 对照权威锚点 docs/deploy/systemd-units-20260912.md + scripts/README.md 定时任务配置")
        print("  若为历史陈述/迁移注: 行内补豁免上下文词(如「历史存档」「已迁云」)或显式标记 <!-- staleness-ok: 历史陈述 -->")
        return 1
    print("✓ 文档时点/调度口径一致性机检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
