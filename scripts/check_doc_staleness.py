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
    # uumit-knowledge = gitignore 知识商品生成目录(.gitignore L280-282), 不在版本控制,
    # 机检扫它会拦「文件系统有但 git 无」的旧内容 → merge 必误拦, 豁免(其内容由生成流程单独管理)
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


def _collect_md_files(root: str) -> list:
    """收集 docs/**/*.md + .claude/**/*.md + README.md(排除豁免路径)。"""
    files = []
    for base in ("docs", ".claude"):
        full = os.path.join(root, base)
        if not os.path.isdir(full):
            continue
        for dirpath, _dirnames, filenames in os.walk(full):
            # 跳过 .git 等隐藏目录
            if "/.git" in dirpath or dirpath.startswith(".git"):
                continue
            for fn in filenames:
                if fn.endswith(".md"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), root)
                    if not _is_path_exempt(rel):
                        files.append(rel)
    readme = os.path.join(root, "README.md")
    if os.path.isfile(readme):
        files.append("README.md")
    return sorted(files)


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
    for i, line in enumerate(lines, 1):
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
