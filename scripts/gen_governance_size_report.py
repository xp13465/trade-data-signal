#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""gen_governance_size_report.py — 治理体量月报(P3,2026-10-18 评鉴;治 W2「只加不减」棘轮)。

背景与依据(设计报告 `docs/ops/sugas-eval-20261018.md` §P3 + 批3 设计报告 /tmp/eval-p3-design-report.md §A):
  体系对自己的**体量**零测点 —— 根规范 CLAUDE.md 11 天 3,267B→61,533B(+18.4%),批2 单批 +4.7KB,
  却没有任何"长胖了没"的记录。本脚本把体量做成**每月一行数字**(单一事实源 = 快照 JSON
  `docs/ops/governance-budget-history.json`),并由 CI 对账(rev 逐位复核),防"账已漂移无人知"。

计量对象(设计报告 §A1 全集):
  · repo 内文件:CLAUDE.md / docs/main-governance.md / 台账归档 / **全部 role skill**
    (当前 5 份:implementer/reviewer/tester/researcher/mech-runner;新增 role skill 时须同步本清单);
  · repo 外 1 个:memory 索引 MEMORY.md(每日备份 tarball 内 `memory/MEMORY.md`;只承诺近 30 天,
    更早月份记 null,**不造假**);
  · 条款净增:台账锚点(`^L\d+`/`^E\d+`)季内增量(**教训级口径**,条款级增补不进计数 —— 诚实标注)。

三子命令:
  `--backfill [--since 2026-07]`  逐月末 rev 算 repo 对象字节 + 查 30 天 MEMORY 备份 → 写 JSON。
                                  **只补缺行,不覆盖已钉行**(已钉行=历史快照,重算会让审计留痕漂移)。
                                  例外:`--force` 显式重钉(用于口径修正,改前先在报告里说明)。
  `--report --month 2026-10`      从 JSON 生成 NOTES.md 月段文本(stdout;主控 §19 周 review 月度档粘)。
  `--check`                       ①schema ②每行 rev 对账(`git show <rev>:<path>` 字节逐位相等)
                                  ③缺月/陈旧检测(INFO)④字节环比 +10% / 季净增 >3(**WARN**,不 FAIL)
                                  ⑤季度退役清单「候选」字段格式(§5.3.1 ③,缺候选 = WARN)。
  `--selftest`                    变异自测:负对照必须 PASS;改坏一行 rev / 字节数 → 必须 FAIL;
                                  删一行 → 必须被"缺月"检出(INFO,按设计 A-3 不设 FAIL);
                                  清单候选留空 → 必须出 WARN(不 FAIL)。

**FAIL 边界(设计 §A4① 写死,防误伤)**:只有「schema 错 / rev 逐位对不上」才 FAIL(账不平=真错);
字节超阈值、季净增超 3 = **WARN + 触发动作**(「超预算即触发瘦身」出口见 §5.3.1 第 5 条),不阻断 merge ——
否则任何一次正常写文档都会随机卡全仓,拦的不是错误而是项目日常形态(gate-position-blast-radius)。

零外发、零网络:只读本地 git 对象 + 本地备份 tarball + 写本地 JSON。
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_DEFAULT = Path(__file__).absolute().parent.parent
JSON_REL = "docs/ops/governance-budget-history.json"
CHECKLIST_REL = "docs/ops/clause-retirement-checklist.md"

# 计量对象 → repo 内相对路径(repo 对象);键名 = JSON 字段名
REPO_PATHS = {
    "claude_md": "CLAUDE.md",
    "governance": "docs/main-governance.md",
    "archive": "docs/archive/CLAUDE-errors-2026-08.md",
}
# 全部 role skill(当前 5 份;新增 role skill 时在此登记 + JSON 各行补该键)。
# ⚠️ skills_sum 语义 = **该行当时存在的 skill 件数之和**(非固定口径):历史行在新增 skill 前
#    只含当时件数(旧行其新键补 null,值不追改,不额外加权外推)⇒ 与最新行口径不同,
#    跨行环比(预算 WARN)会**低估**增量(例:2026-10 记 4 件之和 113,869B,5 件真实口径 +28.4%)。
SKILL_PATHS = {
    "implementer": ".claude/skills/role-implementer/SKILL.md",
    "reviewer": ".claude/skills/role-reviewer/SKILL.md",
    "tester": ".claude/skills/role-tester/SKILL.md",
    "researcher": ".claude/skills/role-researcher/SKILL.md",
    "mech-runner": ".claude/skills/role-mech-runner/SKILL.md",
}
ARCHIVE_REL = REPO_PATHS["archive"]
INDEX_HEADING = "## 防重犯锚点索引"

SCHEMA_VERSION = 1
DEFAULT_SINCE = "2026-07"
BACKUP_DIR_DEFAULT = Path.home() / ".claude" / "backups" / "daily"
LIVE_MEMORY_DEFAULT = (Path.home() / ".claude" / "projects"
                       / "-Users-linhuichen-code-trade" / "memory" / "MEMORY.md")

# 字节预算(设计 §A5 触发条件①:任一对象环比 +10%/月);季条款净增上限(触发条件②)
BYTE_MOM_PCT = 10.0
CLAUSE_QUARTER_MAX = 3

_RE_MONTH = re.compile(r"^\d{4}-\d{2}$")
_RE_ANCHOR_L = re.compile(r"(?m)^L\d+")
_RE_ANCHOR_E = re.compile(r"(?m)^E\d+")


# ── 小工具 ───────────────────────────────────────────────────────────────────
def _month_end(month: str) -> dt.date:
    y, m = (int(x) for x in month.split("-"))
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def _add_months(month: str, n: int) -> str:
    y, m = (int(x) for x in month.split("-"))
    t = (y * 12 + (m - 1)) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _quarter(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return f"{y}-Q{(m - 1) // 3 + 1}"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True)


def git_show_bytes(repo: Path, rev: str, rel: str):
    """`git show <rev>:<rel>` 的字节数;该 rev 不可达 → 抛 ValueError;该路径当时不存在 → None。"""
    if _git(repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode != 0:
        raise ValueError(f"rev 不可达: {rev}")
    r = _git(repo, "show", f"{rev}:{rel}")
    if r.returncode != 0:
        return None
    return len(r.stdout)


def resolve_month_end_rev(repo: Path, month: str) -> str:
    """月末 rev = 该月最后一秒之前的最后一个提交。

    注:`--before=<月末日>` 会把月末次日的合并提交也算进来(git approxidate 边界),
    故必须用 "月末日 23:59:59" 这个显式时刻(实测 2026-07 得 160f7ca4,与设计报告一致)。
    """
    stamp = f"{_month_end(month).isoformat()} 23:59:59"
    r = _git(repo, "rev-list", "-1", f"--before={stamp}", "HEAD")
    if r.returncode != 0 or not r.stdout.strip():
        raise ValueError(f"取不到 {month} 月末 rev(before={stamp})")
    return r.stdout.decode().strip()


def clause_counts(repo: Path, rev: str):
    """台账锚点块内 `^L\\d+` / `^E\\d+` 行数;该 rev 无归档文件 → None。"""
    if _git(repo, "cat-file", "-e", f"{rev}^{{commit}}").returncode != 0:
        raise ValueError(f"rev 不可达: {rev}")
    r = _git(repo, "show", f"{rev}:{ARCHIVE_REL}")
    if r.returncode != 0:
        return None
    text = r.stdout.decode("utf-8", errors="replace")
    i = text.find(INDEX_HEADING)
    if i < 0:
        return None
    blk = text[i:]
    return (len(_RE_ANCHOR_L.findall(blk)), len(_RE_ANCHOR_E.findall(blk)))


def memory_bytes_for_month(month: str, today: dt.date, backup_dir: Path, live_path: Path):
    """MEMORY.md 字节:已过月份取该月内**最晚一天**的每日备份;当月取现测文件;取不到 → None。

    诚实标注:每日备份只保留 30 天 ⇒ 更早月份必然 None(不造假,记 null)。
    """
    if month >= f"{today:%Y-%m}":
        try:
            return live_path.stat().st_size if live_path.is_file() else None
        except OSError:
            return None
    day = _month_end(month)
    for _ in range(day.day):          # 从月末往前找最近一天的备份
        tar = backup_dir / f"claude-self-{day:%Y%m%d}.tar.gz"
        if tar.is_file():
            try:
                with tarfile.open(tar, "r:gz") as tf:
                    for m in tf.getmembers():
                        if m.name.endswith("memory/MEMORY.md") and "/bak" not in m.name:
                            return m.size
            except (tarfile.TarError, OSError):
                return None
            return None
        day -= dt.timedelta(days=1)
    return None


def _atomic_write_text(path: Path, text: str) -> None:
    """原子写(临时文件 + os.replace)。§「数据产物必须原子写」:防半截 JSON 被读到。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".size-report-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ── 采集一行 ─────────────────────────────────────────────────────────────────
def collect_row(repo: Path, month: str, today: dt.date, backup_dir: Path, live_path: Path) -> dict:
    rev = resolve_month_end_rev(repo, month)
    row: dict = {"month": month, "rev": rev}
    for key, rel in REPO_PATHS.items():
        row[key] = git_show_bytes(repo, rev, rel)
    row["skills"] = {k: git_show_bytes(repo, rev, rel) for k, rel in SKILL_PATHS.items()}
    vals = [v for v in row["skills"].values() if v is not None]
    row["skills_sum"] = sum(vals) if len(vals) == len(SKILL_PATHS) else None
    row["mem_md"] = memory_bytes_for_month(month, today, backup_dir, live_path)
    cc = clause_counts(repo, rev)
    row["clauses"] = {"l": None, "e": None, "net": 0} if cc is None else {"l": cc[0], "e": cc[1], "net": 0}
    return row


def _fill_net(entries: list) -> None:
    """net = 本行 (l+e) − 上一行 (l+e);上一行缺(genesis/未回填)⇒ 记 0(初始化不计"净增")。"""
    prev = None
    for e in entries:
        c = e.get("clauses") or {}
        cur = None if (c.get("l") is None or c.get("e") is None) else c["l"] + c["e"]
        e["clauses"] = {"l": c.get("l"), "e": c.get("e"),
                        "net": (cur - prev) if (cur is not None and prev is not None) else 0}
        if cur is not None:
            prev = cur


def _quarter_net(entries: list, month: str) -> int:
    q = _quarter(month)
    return sum((e.get("clauses") or {}).get("net") or 0 for e in entries if _quarter(e["month"]) == q)


# ── schema ───────────────────────────────────────────────────────────────────
def schema_errors(doc) -> list:
    errs = []
    if not isinstance(doc, dict):
        return ["顶层不是对象"]
    if doc.get("schema") != SCHEMA_VERSION:
        errs.append(f"schema 字段应为 {SCHEMA_VERSION},实测 {doc.get('schema')!r}")
    try:
        dt.date.fromisoformat(str(doc.get("updated")))
    except ValueError:
        errs.append(f"updated 不是 ISO 日期: {doc.get('updated')!r}")
    entries = doc.get("entries")
    if not isinstance(entries, list) or not entries:
        return errs + ["entries 缺失/为空(空 JSON = 解析器空转,拒绝 PASS)"]
    for i, e in enumerate(entries):
        tag = f"entries[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{tag} 不是对象")
            continue
        m = e.get("month")
        if not isinstance(m, str) or not _RE_MONTH.match(m):
            errs.append(f"{tag}.month 格式应为 YYYY-MM: {m!r}")
        if not isinstance(e.get("rev"), str) or len(e["rev"]) < 7:
            errs.append(f"{tag}.rev 缺失/过短: {e.get('rev')!r}")
        for k in ("claude_md", "governance", "archive", "skills_sum", "mem_md"):
            if k not in e:
                errs.append(f"{tag}.{k} 字段缺失")
            elif e[k] is not None and not isinstance(e[k], int):
                errs.append(f"{tag}.{k} 应为 int 或 null: {e[k]!r}")
        sk = e.get("skills")
        if not isinstance(sk, dict) or set(sk) != set(SKILL_PATHS):
            errs.append(f"{tag}.skills 键集应 = {sorted(SKILL_PATHS)}: {sk!r}")
        else:
            for k, v in sk.items():
                if v is not None and not isinstance(v, int):
                    errs.append(f"{tag}.skills.{k} 应为 int 或 null: {v!r}")
        cl = e.get("clauses")
        if not isinstance(cl, dict) or set(cl) != {"l", "e", "net"}:
            errs.append(f"{tag}.clauses 应含 l/e/net: {cl!r}")
        elif not isinstance(cl["net"], int):
            errs.append(f"{tag}.clauses.net 应为 int: {cl['net']!r}")
    months = [e.get("month") for e in entries if isinstance(e, dict)]
    if months != sorted(months):
        errs.append(f"entries 未按月升序: {months}")
    return errs


# ── --backfill ───────────────────────────────────────────────────────────────
def cmd_backfill(args) -> int:
    repo, json_p = args.repo, args.json
    today = dt.date.today()
    doc = _load_json(json_p) if json_p.is_file() else {"schema": SCHEMA_VERSION,
                                                      "updated": today.isoformat(), "entries": []}
    have = {e["month"] for e in doc.get("entries", [])}
    months = []
    m = args.since
    cur = f"{today:%Y-%m}"
    while m <= cur:
        months.append(m)
        m = _add_months(m, 1)

    added = []
    for month in months:
        if month in have and not args.force:
            continue
        row = collect_row(repo, month, today, args.backup_dir, args.live_memory)
        doc["entries"] = [e for e in doc["entries"] if e["month"] != month]
        doc["entries"].append(row)
        doc["entries"].sort(key=lambda e: e["month"])
        added.append(month)
        print(f"[backfill] {month} rev={row['rev'][:8]} CLAUDE.md={row['claude_md']} "
              f"skills_sum={row['skills_sum']} mem_md={row['mem_md']} clauses={row['clauses']}")
    _fill_net(doc["entries"])
    doc["schema"] = SCHEMA_VERSION
    doc["updated"] = today.isoformat()
    _atomic_write_text(json_p, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print(f"[backfill] 已写 {json_p}(新增/重钉 {len(added)} 行:{', '.join(added) or '无'};"
          f"合计 {len(doc['entries'])} 行)")
    return 0


# ── --report ─────────────────────────────────────────────────────────────────
def cmd_report(args) -> int:
    doc = _load_json(args.json)
    row = next((e for e in doc["entries"] if e["month"] == args.month), None)
    if row is None:
        print(f"[report] FAIL: JSON 内无 {args.month} 行(先 --backfill)", file=sys.stderr)
        return 1
    end = _month_end(args.month)
    today = dt.date.today()
    asof = min(end, today) if args.month >= f"{today:%Y-%m}" else end
    qnet = _quarter_net(doc["entries"], args.month)
    over = " 超预算 ⇒ 触发动作见 docs/ops/clause-retirement-checklist.md" if qnet > CLAUSE_QUARTER_MAX else ""
    mem = f"{row['mem_md']:,}B" if row.get("mem_md") is not None else "null(30 天外,无备份)"
    arch = f"{row['archive']:,}B" if row.get("archive") is not None else "null"
    sk = f"{row['skills_sum']:,}B" if row.get("skills_sum") is not None else "null"
    print(f"## {args.month} 月报(体量 + 成本;数据源 {JSON_REL})")
    print(f"- 体量(截至 {asof:%m-%d},rev {row['rev'][:8]}):CLAUDE.md {row['claude_md']:,}B / "
          f"MEMORY.md {mem} / 台账归档 {arch} / skills 合计 {sk};"
          f"本季条款净增 {qnet:+d}(≤{CLAUSE_QUARTER_MAX}){over}。")
    print("- 花费:deepseek 官方 ¥__ / 火山方舟 ¥__ / 各代理 ¥__;规范维护时长 __h"
          "(§5.2④;待 §19 月度归并填写)。")
    return 0


# ── 季度清单格式机检(§5.3.1 ③;设计 A-6:格式=机检 / 候选质量=人工)──────────────
_RE_TABLE_DELIM = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _md_tables(text: str):
    """极简 markdown 表解析 → [(表头 cells, [数据行 cells, ...]), ...](跳过 |---| 行)。"""
    tables, lines = [], text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) \
                and _RE_TABLE_DELIM.match(lines[i + 1]):
            head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            tables.append((head, rows))
            i = j
        else:
            i += 1
    return tables


def checklist_format_warns(path: Path) -> list:
    """季度退役清单的「候选」字段格式(§5.3.1 ③)。

    只看「表头同时含 条款 与 候选」的表:每条条款行必须给 ≥1 个候选(非空)。
    只判**在场非空**,不判候选内容合不合理(那是内容判断,归人工 / reviewer —— 不假装机检)。
    """
    out = []
    if not path.is_file():
        return out
    for head, rows in _md_tables(path.read_text(encoding="utf-8")):
        joined = " ".join(head)
        if "条款" not in joined or "候选" not in joined:
            continue
        i_clause = next(i for i, h in enumerate(head) if "条款" in h)
        i_cand = next(i for i, h in enumerate(head) if "候选" in h)
        for cells in rows:
            if len(cells) <= max(i_clause, i_cand):
                continue
            clause, cand = cells[i_clause], cells[i_cand]
            if not clause or clause in ("-", "—"):
                continue
            if not cand or cand in ("-", "—"):
                out.append(f"清单格式:{path.name} 行「{clause}」缺「候选」字段"
                           f"(§5.3.1 ③:新增条款必须给 ≥1 个合并/删除候选)")
    return out


# ── --check ──────────────────────────────────────────────────────────────────
def cmd_check(args) -> int:
    repo, json_p = args.repo, args.json
    if not json_p.is_file():
        print(f"FAIL 体量月报 JSON 不在位: {json_p}(§23.5 新产物当场落档)")
        return 1
    doc = _load_json(json_p)
    fails, warns, infos = [], [], []

    errs = schema_errors(doc)
    fails += [f"schema: {e}" for e in errs]

    # ② rev 对账:记录的每个非 null repo 字节,必须与 `git show <rev>:<path>` 逐位相等
    if not errs:
        for e in doc["entries"]:
            rev = e["rev"]
            for key in ("claude_md", "governance", "archive"):
                rec = e.get(key)
                try:
                    actual = git_show_bytes(repo, rev, REPO_PATHS[key])
                except ValueError as ex:
                    fails.append(f"{e['month']} {key}: {ex}(rev 对账锚失效 = 账不平)")
                    break
                if rec is None:
                    continue
                if actual is None:
                    fails.append(f"{e['month']} {key}: 记录 {rec}B 但该 rev 下文件不存在")
                elif actual != rec:
                    fails.append(f"{e['month']} {key}: 记录 {rec}B ≠ git 实测 {actual}B(rev {rev[:8]})")
            for k, rel in SKILL_PATHS.items():
                rec = (e.get("skills") or {}).get(k)
                if rec is None:
                    continue
                try:
                    actual = git_show_bytes(repo, rev, rel)
                except ValueError:
                    continue          # rev 不可达已在上面报过
                if actual != rec:
                    fails.append(f"{e['month']} skills.{k}: 记录 {rec}B ≠ git 实测 {actual}B")
    # ③ 缺月 / 陈旧(INFO,不 FAIL —— 设计 A-3)
    months = [e["month"] for e in doc["entries"]]
    span = []
    m, last = months[0], months[-1]
    while m <= last:
        span.append(m)
        m = _add_months(m, 1)
    missing = [x for x in span if x not in months]
    if missing:
        infos.append(f"缺月(未回填): {', '.join(missing)}")
    now_m = f"{dt.date.today():%Y-%m}"
    if last < _add_months(now_m, -1):
        infos.append(f"月报陈旧:最新 {last},现 {now_m} —— 按 §5.3.1 每月一行,该补了")

    # ④ 预算信号(WARN,不 FAIL)
    for key, label in (("claude_md", "CLAUDE.md"), ("governance", "治理规范"),
                       ("archive", "台账归档"), ("skills_sum", "skills 合计")):
        if len(doc["entries"]) >= 2:
            a, b = doc["entries"][-2], doc["entries"][-1]
            if a.get(key) and b.get(key):
                pct = (b[key] - a[key]) / a[key] * 100
                if pct > BYTE_MOM_PCT:
                    warns.append(f"预算:{label} 环比 {pct:+.1f}% > {BYTE_MOM_PCT:.0f}%/月"
                                 f"({a[key]:,}B → {b[key]:,}B)→ 触发动作(§5.3.1 第 5 条④)")
    qnet = _quarter_net(doc["entries"], doc["entries"][-1]["month"])
    if qnet > CLAUSE_QUARTER_MAX:
        note = ""
        if args.checklist.is_file():
            text = args.checklist.read_text(encoding="utf-8")
            if "超预算触发" in text and _quarter(doc["entries"][-1]["month"]) in text:
                note = "(清单已记录超预算触发)"
        if not note:
            note = f"(清单 {CHECKLIST_REL} 未记录 {_quarter(doc['entries'][-1]['month'])} 超预算触发 ⇒ 请补录)"
        warns.append(f"预算:本季条款净增 {qnet:+d} > {CLAUSE_QUARTER_MAX} → 触发动作(§5.3.1 第 5 条④){note}")

    # ⑤ 季度清单「候选」字段格式(§5.3.1 ③;WARN 不 FAIL —— 文档格式问题不该卡 merge)
    warns += checklist_format_warns(args.checklist)

    print(f"[size-report] JSON={json_p} 共 {len(doc['entries'])} 行,最新 {months[-1]}")
    for i in infos:
        print(f"  INFO {i}")
    for w in warns:
        print(f"  WARN {w}")
    for f in fails:
        print(f"  FAIL {f}")
    if fails:
        print(f"[size-report] RESULT=FAIL({len(fails)})")
        return 1
    print(f"[size-report] RESULT=PASS(WARN {len(warns)} / INFO {len(infos)};字节与净增超限=WARN 不 FAIL)")
    return 0


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        print(f"[size-report] FAIL 读取 JSON 失败: {path} → {ex}", file=sys.stderr)
        raise SystemExit(1)


# ── --selftest(变异自测,防空转)───────────────────────────────────────────────
def selftest(repo: Path, json_p: Path, checklist: Path) -> int:
    ok = True
    base = _load_json(json_p)

    def _run(jp: Path, cl: Path = None):
        cmd = [sys.executable, str(Path(__file__).absolute()),
               "--check", "--repo", str(repo), "--json", str(jp)]
        if cl is not None:
            cmd += ["--checklist", str(cl)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        # ① 负对照(未变异)→ 必须 PASS(否则装置本身恒 FAIL,证据无效)
        rc0, out0 = _run(json_p)
        if rc0 == 0 and "RESULT=PASS" in out0:
            print("  PASS: 负对照(未变异)→ RESULT=PASS(装置本身非恒 FAIL)")
        else:
            ok = False
            print(f"  FAIL: 负对照竟 rc={rc0}, tail={out0.strip().splitlines()[-3:]}")

        # ② 变异:改坏一行 rev → 必须 FAIL(rev 对账锚真响)
        bad = json.loads(json.dumps(base))
        bad["entries"][-1]["rev"] = "0" * 40
        p = t / "bad-rev.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        rc1, out1 = _run(p)
        if rc1 != 0 and "RESULT=FAIL" in out1 and "rev" in out1:
            print("  PASS: 变异样本(rev 改成全 0)→ RESULT=FAIL(rev 对账真响)")
        else:
            ok = False
            print(f"  FAIL: 改坏 rev 竟 rc={rc1}(应 FAIL), tail={out1.strip().splitlines()[-3:]}")

        # ③ 变异:改坏一行字节数(+1)→ 必须 FAIL(逐位对账真响)
        bad2 = json.loads(json.dumps(base))
        bad2["entries"][-1]["claude_md"] = (bad2["entries"][-1]["claude_md"] or 0) + 1
        p2 = t / "bad-bytes.json"
        p2.write_text(json.dumps(bad2), encoding="utf-8")
        rc2, out2 = _run(p2)
        if rc2 != 0 and "RESULT=FAIL" in out2 and "≠ git 实测" in out2:
            print("  PASS: 变异样本(CLAUDE.md 字节 +1)→ RESULT=FAIL(逐位对账真响)")
        else:
            ok = False
            print(f"  FAIL: 改坏字节竟 rc={rc2}(应 FAIL), tail={out2.strip().splitlines()[-3:]}")

        # ④ 变异:删掉**中间**一行 → 必须被"缺月"检出(INFO 行在场;设计 A-3 = INFO 不 FAIL)
        #    注:删**最后**一行不设检出 —— 那是「本月月报还没出」,只有跨过整月才由「陈旧」提示;
        #    故意不把它做成 FAIL,否则每月月初都会红(同 §A4① 的误伤理由)。
        bad3 = json.loads(json.dumps(base))
        dropped = bad3["entries"].pop(-2)["month"]
        p3 = t / "dropped.json"
        p3.write_text(json.dumps(bad3), encoding="utf-8")
        rc3, out3 = _run(p3)
        if "缺月" in out3:
            print(f"  PASS: 变异样本(删掉中间行 {dropped})→ 被检出(缺月 INFO);rc={rc3}")
        else:
            ok = False
            print(f"  FAIL: 删行后未被检出 ⇒ 缺月检测空转, tail={out3.strip().splitlines()[-3:]}")

        # ⑤ 变异:季度清单里插一条「候选」留空的行 → 必须出 WARN(§5.3.1 ③ 格式机检真响)
        if not checklist.is_file():
            print("  INFO: 季度清单不存在,跳过格式机检向(不判 FAIL)")
        else:
            lines = checklist.read_text(encoding="utf-8").splitlines(keepends=True)
            hit = None
            for i, ln in enumerate(lines):
                if ln.lstrip().startswith("|") and "候选" in ln and i + 1 < len(lines) \
                        and _RE_TABLE_DELIM.match(lines[i + 1]):
                    hit = i
                    break
            if hit is None:
                ok = False
                print("  FAIL: 清单里找不到「候选」表头 ⇒ 格式机检没有可查对象(空转)")
            else:
                lines.insert(hit + 2, "| (自测注入行) | 保留 |  | 自测注入:候选留空必须被检出 |\n")
                p4 = t / "bad-checklist.md"
                p4.write_text("".join(lines), encoding="utf-8")
                rc4, out4 = _run(json_p, cl=p4)
                if "缺「候选」字段" in out4:
                    print(f"  PASS: 变异样本(清单行候选留空)→ 出 WARN 检出(rc={rc4},不 FAIL)")
                else:
                    ok = False
                    print(f"  FAIL: 清单候选留空未被检出 ⇒ 格式机检空转, tail={out4.strip().splitlines()[-3:]}")

    print(f"[size-report-selftest] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


# ── 入口 ─────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="治理体量月报(P3)")
    ap.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    ap.add_argument("--json", type=Path, default=None, help=f"默认 <repo>/{JSON_REL}")
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--force", action="store_true", help="重钉已有行(口径修正用,慎用)")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--month", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--backup-dir", type=Path, default=BACKUP_DIR_DEFAULT)
    ap.add_argument("--live-memory", type=Path, default=LIVE_MEMORY_DEFAULT)
    ap.add_argument("--checklist", type=Path, default=None, help=f"默认 <repo>/{CHECKLIST_REL}")
    args = ap.parse_args(argv)
    args.repo = args.repo.resolve()
    args.json = (args.json or (args.repo / JSON_REL)).resolve()
    args.checklist = (args.checklist or (args.repo / CHECKLIST_REL)).resolve()

    if args.selftest:
        return selftest(args.repo, args.json, args.checklist)
    if args.backfill:
        return cmd_backfill(args)
    if args.report:
        if not args.month:
            print("[report] 需要 --month YYYY-MM", file=sys.stderr)
            return 2
        return cmd_report(args)
    if args.check:
        return cmd_check(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())