#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""check_gate_registry.py — 机检「保险登记表」对账(P5,2026-10-18 评鉴;设计报告 §B4)。

背景:体系里越来越多的「自动拦闸门」(CI step / merge 前置步 / hook / 检查脚本),却**没有一处**
  写得清「这个闸门防什么、什么时候不再保护、误伤什么、坏了谁接手」。教训台账的「机检=是(闸门:X)」
  只表达**某条教训**的现状(83 行,历史冻结不许追改),不是闸门的生命周期档案 ⇒ 需要第二份表:
  `docs/ops/machine-check-registry.md`(闸门→生命周期,单一事实源),两者**只靠一个键连接:闸门名**。
  本脚本 = 那份表的机检(挂 CI pytest,见 `scripts/tests/test_gate_registry_pytest.py`)。

四查(全 PASS 才 exit 0):
  ① schema:每行 7 字段齐且非空(闸门名 / 挂点 / 防什么 / 失效条件 / 误伤条件 / 失效时谁接手 + 动作 /
     自检方式);闸门名唯一;单元格数与表头不符的行 ⇒ 直接 FAIL(报行号/列数,**不静默丢弃**——
     静默丢行会让「整体仍 PASS」,正是本脚本「拒绝静默通过」承诺的反面)。
  ② 挂点存在性:挂点里出现的每个 repo 路径必须真存在;若该行提到 `ci.yml`,则行内至少一个反引号
     `` `...` `` 记号必须能在 `.github/workflows/ci.yml` 里逐字找到(防"指到不存在的挂点";
     `gate-verify-in-prod-tree` 精神:在**生产目录**里验,不在干净副本里验)。
  ③ 双向覆盖:台账锚点块里每条 `机检=是(闸门:X)` 的 X,必须在 registry 有对应行(闸门名 = X 或
     X 的子串,匹配模式打印出来);反向,registry 每行「防什么」里点到的锚点 id 必须真存在
     (不点锚点的行必须显式写「无锚点」理由,不许留空)。
  ④ 恒在自检 + 新增守卫必登记:registry 行数 > 0(空表 = 空转);repo 内**每个** `scripts/**/check_*.py`
     (tests/ 除外)必须出现在闸门表或存量豁免表里 —— 防「新写个守卫没人登记 = 保护面静默扩不动」。
     `--selftest`:删一行闸门 → 必须 FAIL;删一行存量豁免 → 必须 FAIL;负对照必须 PASS。

⚠️ 诚实边界(不假装机检):
  · 「失效条件/误伤条件/谁接手」三栏**内容对不对**是判断,不是格式 —— 本脚本只保证栏位在场非空;
    内容由 reviewer 抽样核对(与 check_ledger F 维同一取舍)。
  · 「每个闸门都真在跑」不在本脚本能力内(需生产实跑);registry 只保证「登记与覆盖无遗漏」。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_DEFAULT = Path(__file__).absolute().parent.parent
REGISTRY_REL = "docs/ops/machine-check-registry.md"
CI_REL = ".github/workflows/ci.yml"
ARCHIVE_REL = "docs/archive/CLAUDE-errors-2026-08.md"
INDEX_HEADING = "## 防重犯锚点索引"

COLS = ("闸门名", "挂点", "防什么", "失效条件", "误伤条件", "失效时谁接手 + 动作", "自检方式")

_RE_JIAN = re.compile(r"机检=是\(闸门:([^)]+)\)")
_RE_ANCHOR = re.compile(r"(?m)^([LE])(\d+)\b")
_RE_ANCHOR_REF = re.compile(r"(?<![A-Za-z0-9])([LE])(\d{2})(?![0-9])")
_RE_PATH = re.compile(r"(?:^|[\s`(])((?:scripts|docs|\.github)/[A-Za-z0-9_./-]+\.(?:py|sh|yml|md|txt))")
_RE_BACKTICK = re.compile(r"`([^`]+)`")
_RE_CHECKFILE = re.compile(r"check_[a-z0-9_]+\.py")
_RE_NONANCHOR = re.compile(r"无锚点|无对应锚点")


# ── 解析 ─────────────────────────────────────────────────────────────────────
def _split_row(line: str):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def parse_tables(text: str):
    """返回 [(表头 cells, [数据行 cells...], [数据行 1-based 行号...]), ...](跳过 `|---|` 分隔行)。"""
    tables, lines = [], text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) \
                and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = _split_row(lines[i])
            rows, lns, j = [], [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = _split_row(lines[j])
                if any(cells):
                    rows.append(cells)
                    lns.append(j + 1)
                j += 1
            tables.append((head, rows, lns))
            i = j
        else:
            i += 1
    return tables


def load_registry(path: Path):
    """→ (gates, legacy, text, malformed):gates=[dict(zip(COLS, cells))], legacy=[(脚本, 理由)],
    malformed=[(表名, 行号, 实际列数, 表头列数)] —— 单元格数与表头不符的行**收集上报**,不静默丢弃。"""
    text = path.read_text(encoding="utf-8")
    gates, legacy, malformed = [], [], []
    for head, rows, lns in parse_tables(text):
        if "闸门名" in head:
            label = "闸门表"
        elif any("豁免理由" in h for h in head):
            label = "存量豁免表"
        else:
            continue
        for r, ln in zip(rows, lns):
            if len(r) != len(head):
                malformed.append((label, ln, len(r), len(head)))
                continue
            if label == "闸门表":
                gates.append(dict(zip(head, r)))
            else:
                idx = next(i for i, h in enumerate(head) if "豁免理由" in h)
                legacy.append((r[0], r[idx]))
    return gates, legacy, text, malformed


# ── 四查 ─────────────────────────────────────────────────────────────────────
def check(repo: Path, registry: Path):
    fails, passes, infos = [], [], []
    if not registry.is_file():
        return [f"缺 registry 文件: {registry}"], [], []
    gates, legacy, _, malformed = load_registry(registry)

    # ④ 恒在自检(先查,防空转)
    if not gates:
        fails.append("registry 闸门表解析为空(0 行)= 空转,拒绝 PASS")
    if not legacy:
        fails.append("registry 存量豁免表解析为空(0 行)= 空转,拒绝 PASS")

    # ① schema(先报「单元格数与表头不符」的行 —— 这些行在解析时已被拒,不静默丢弃)
    for label, ln, got, want in malformed:
        fails.append(f"① {label} 第 {ln} 行单元格数 {got}≠表头 {want}(该行被拒收,拒绝静默丢弃)")
    seen = {}
    for g in gates:
        name = (g.get("闸门名") or "").strip()
        for c in COLS:
            v = (g.get(c) or "").strip()
            if not v:
                fails.append(f"① {name or '(无名行)'}: 栏「{c}」为空")
        if name in seen:
            fails.append(f"① 闸门名重复: {name}")
        seen[name] = g
    if gates and not malformed:
        passes.append(f"① schema: {len(gates)} 行 × {len(COLS)} 栏全部在场非空")

    # ② 挂点存在性
    ci = (repo / CI_REL).read_text(encoding="utf-8") if (repo / CI_REL).is_file() else ""
    for g in gates:
        name = (g.get("闸门名") or "").strip()
        spot = (g.get("挂点") or "")
        if not ci:
            fails.append(f"② 缺 {CI_REL}(无法核 CI 挂点)")
            break
        for rel in _RE_PATH.findall(spot):
            if not (repo / rel).exists():
                fails.append(f"② {name}: 挂点文件不存在 → {rel}")
        if "ci.yml" in spot:
            marks = [t for t in _RE_BACKTICK.findall(spot)
                     if not _RE_PATH.search(t) and t not in ("ci.yml",)]
            if not marks:
                fails.append(f"② {name}: 提到 ci.yml 但没给反引号 step 名(无法核对挂点)")
            elif not any(mk in ci for mk in marks):
                fails.append(f"② {name}: ci.yml 内找不到挂点 step 名 {marks}")
    if gates:
        passes.append("② 挂点存在性:挂点文件全在位 + ci.yml step 名全命中")

    # ③ 双向覆盖
    arch_p = repo / ARCHIVE_REL
    if not arch_p.is_file():
        fails.append(f"③ 缺 {ARCHIVE_REL}(无法对账台账侧)")
        arch_text, anchors = "", set()
    else:
        arch_text = arch_p.read_text(encoding="utf-8")
        i = arch_text.find(INDEX_HEADING)
        blk = arch_text[i:] if i >= 0 else arch_text
        anchors = {(m.group(1), int(m.group(2))) for m in _RE_ANCHOR.finditer(blk)}
        if not anchors:
            return fails + [f"③ {ARCHIVE_REL} 锚点块解析为空 = 空转,拒绝 PASS"], passes, infos
    # 只取**锚点行**(行首 L##/E##)上的闸门串 —— 归档块头有一条讲格式的散文行也写着
    # `机检=是(闸门:<脚本/闸门名>)`(占位符),按全文 grep 会把它当真实闸门误报。
    ledger_gates = []
    for ln in blk.splitlines():
        if _RE_ANCHOR.match(ln):
            ledger_gates += [m.group(1).strip() for m in _RE_JIAN.finditer(ln)]
    ledger_gates = [g for g in ledger_gates if g and "<" not in g and ">" not in g]
    if not ledger_gates:
        fails.append("③ 台账侧一条「机检=是(闸门:…)」都没解析到 = 空转,拒绝 PASS")
    for x in ledger_gates:
        if x in seen:
            passes.append(f"③ 台账闸门 → registry:「{x}」(精确匹配)")
            continue
        sub = [n for n in seen if n and n in x]
        if sub:
            passes.append(f"③ 台账闸门 → registry:「{sub[0]}」⊂「{x}」(子串匹配)")
        else:
            fails.append(f"③ 台账闸门「{x}」在 registry 无对应行(保护面漏登记)")
    for name, g in seen.items():
        why = g.get("防什么") or ""
        ids = {(m.group(1), int(m.group(2))) for m in _RE_ANCHOR_REF.finditer(why)}
        if not ids:
            if not _RE_NONANCHOR.search(why):
                fails.append(f"③ registry「{name}」的「防什么」既无锚点 id 也没写「无锚点」理由")
            continue
        for kind, num in sorted(ids):
            if (kind, num) not in anchors:
                fails.append(f"③ registry「{name}」指向不存在的锚点 {kind}{num:02d}")

    # ④ 新增守卫必登记:repo 内每个 check_*.py 必须出现在闸门表或存量豁免表
    gate_text = "\n".join(f"{g.get('闸门名','')} {g.get('挂点','')} {g.get('自检方式','')}"
                          for g in gates)
    legacy_text = "\n".join(f"{a} {b}" for a, b in legacy)
    tree = sorted({p.name for p in (repo / "scripts").rglob("check_*.py")
                   if "/tests/" not in p.as_posix()})
    if not tree:
        fails.append("④ scripts/ 下扫到 0 个 check_*.py = 扫描空转,拒绝 PASS")
    unregistered = [n for n in tree if n not in gate_text and n not in legacy_text]
    for n in unregistered:
        fails.append(f"④ 守卫未登记: scripts/**/{n} 既不在闸门表也不在存量豁免表(新增守卫必登记)")
    if tree:
        passes.append(f"④ 覆盖:{len(tree)} 个 check_*.py 全部已登记"
                      f"(闸门行 {sum(1 for n in tree if n in gate_text)} / 存量豁免 "
                      f"{sum(1 for n in tree if n not in gate_text and n in legacy_text)})")
    infos.append(f"registry 闸门 {len(gates)} 行 / 存量豁免 {len(legacy)} 行;"
                 f"台账「机检=是」{len(ledger_gates)} 条全部对账")
    return fails, passes, infos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="机检保险登记表对账(P5)")
    ap.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    ap.add_argument("--registry", type=Path, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    args.repo = args.repo.resolve()
    args.registry = (args.registry or (args.repo / REGISTRY_REL)).resolve()
    if args.selftest:
        return selftest(args.repo, args.registry)

    fails, passes, infos = check(args.repo, args.registry)
    print(f"[gate-registry] registry={args.registry}")
    for p in passes:
        print(f"  OK   {p}")
    for i in infos:
        print(f"  INFO {i}")
    for f in fails:
        print(f"  FAIL {f}")
    if fails:
        print(f"[gate-registry] RESULT=FAIL({len(fails)})")
        return 1
    print("[gate-registry] RESULT=PASS")
    return 0


def selftest(repo: Path, registry: Path) -> int:
    """变异自测(防空转):负对照必须 PASS;删闸门行 / 删存量豁免行 → 必须 FAIL。"""
    import tempfile

    ok = True

    def _run(reg: Path):
        r = subprocess.run(
            [sys.executable, str(Path(__file__).absolute()), "--repo", str(repo),
             "--registry", str(reg)], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    text = registry.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        # ① 负对照(未变异)→ 必须 PASS
        rc0, out0 = _run(registry)
        if rc0 == 0 and "RESULT=PASS" in out0:
            print("  PASS: 负对照(未变异)→ RESULT=PASS(装置本身非恒 FAIL)")
        else:
            ok = False
            print(f"  FAIL: 负对照竟 rc={rc0}, tail={out0.strip().splitlines()[-3:]}")

        # ② 变异:删掉「CI 全量 pytest …」闸门行 → 台账侧 ③ 必须 FAIL
        keep, dropped = [], None
        for ln in text.splitlines(keepends=True):
            if ln.startswith("|") and "CI 全量 pytest" in ln and not ln.startswith("|---"):
                dropped = ln.split("|")[1].strip()
                continue
            keep.append(ln)
        if dropped is None:
            ok = False
            print("  FAIL: 变异注入失败(registry 里找不到「CI 全量 pytest」闸门行)")
        else:
            p = t / "no-gate.md"
            p.write_text("".join(keep), encoding="utf-8")
            rc1, out1 = _run(p)
            if rc1 != 0 and "RESULT=FAIL" in out1 and "无对应行" in out1:
                print(f"  PASS: 变异样本(删闸门行「{dropped}」)→ RESULT=FAIL(③ 双向覆盖真响)")
            else:
                ok = False
                print(f"  FAIL: 删闸门行竟 rc={rc1}(应 FAIL), tail={out1.strip().splitlines()[-3:]}")

        # ③ 变异:删掉任一存量豁免行(仅当它确实是仓内 check 脚本)→ ④ 必须 FAIL
        victim = None
        tree_names = {p.name for p in (repo / "scripts").rglob("check_*.py")
                      if "/tests/" not in p.as_posix()}
        for a, _b in load_registry(registry)[1]:
            name = _RE_CHECKFILE.search(a)
            if name and name.group(0) in tree_names:
                victim = name.group(0)
                break
        if victim is None:
            infos_msg = "  INFO: 存量豁免表里没有可定位的 check_*.py 行,跳过该向(不判 FAIL)"
            print(infos_msg)
        else:
            keep2 = [ln for ln in text.splitlines(keepends=True) if victim not in ln]
            p2 = t / "no-legacy.md"
            p2.write_text("".join(keep2), encoding="utf-8")
            rc2, out2 = _run(p2)
            if rc2 != 0 and "守卫未登记" in out2:
                print(f"  PASS: 变异样本(删存量豁免行 {victim})→ RESULT=FAIL(④ 覆盖真响)")
            else:
                ok = False
                print(f"  FAIL: 删存量行竟 rc={rc2}(应 FAIL), tail={out2.strip().splitlines()[-3:]}")

    print(f"[gate-registry-selftest] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())