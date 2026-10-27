#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""check_ledger.py — 错误台账对账机检(CLAUDE.md §18 防重犯索引表 ↔ 归档锚点索引块)。

背景(第三方评鉴 P1,2026-10-18;报告全文 `docs/ops/sugas-eval-20261018.md` §4-W1 + §5-P1):
  体系要求「同一事实多处副本必须机检」(§22),却对**自己的账本**(错误台账)零机检 ⇒ 账已实际漂移:
  归档索引块实际 **50** 条过错锚点,而 CLAUDE.md §18 与本文件表头都声称 **49**;且声称索引块
  「按归属 5 类分节」,归档实测无此结构。同类坑在 memory 索引上已炸过一次(2026-09-27 瘦身掉
  42 行含 17 条活条目、5 周无人发现)。本脚本补上这道机检(挂 CI Job1 `quality-gate-static`)。

对账维度(全 PASS 才 exit 0):
  A. L 计数三方一致:归档 `^L\d+` 实际条数 == 归档表头声称 == CLAUDE.md §18 声称。
     五项声称数**全部动态解析**(不写死数字)⇒ 日后加锚点只要同步改声称即可,不会又漂。
  B. E 计数三方一致:同上(`^E\d+`)。
  C. 锚点集完整(无遗漏):L id 必须是 01..N 连续无缺号;E 同理(防「少一条 → 静默过」)。
  D. 无悬空:归档「活索引面」(文件表头 + 防重犯锚点索引块)内**引用**到的每个 L/E 锚点 id
     必须真的在该面里被声明(防引用指向不存在锚点)。
     注:归档「正文」(索引块之前的原文快照)是**历史文本**,其内悬空引用只报 INFO 不清算
     (守 §6④ 历史不追改)。
     ⚠️ E31 有**三个编号空间**,引用时必须写清来源(2026-10-27 补第三处):
       ①归档**正文** 08-13/14 那条「派单前先核真值」经验(08-12 归档提炼时未进 E01-E30 索引);
       ②`docs/main-governance.md` §18.1 的 E31 = **2026-08-24 另行补录**的 codex 跨 agent 消息通道条;
       ③归档**锚点块**的 E31 = **2026-10-27 新加**的「生效判定」条(它在本维声明集内,不参与正文悬空判定)。
     三处编号空间**互不相干**(各自编号,只是撞了同一个号)。
     ⚠️ 勿再写成「E31 指 gov §18.1 主控专属账本」(P1 版此处归因不准,2026-10-18 批2 订正,= F1)。
  E. 根表窗口已归档(无遗漏,跨文档):CLAUDE.md §18 滚动窗每个锚点必须在归档索引块内,
     除非该行自述「未单独归档」(显式豁免,不靠人记)。
  F. 「机检=」字段在场 + 值域合法(2026-10-18 批2 加,评鉴 P9⑥):索引块**每条**锚点行尾必须带
     `机检=是(闸门:<名>)` 或 `机检=否`(缺字段/写成裸「机检=是」(无闸门名)/其它值 = FAIL)。
     本维只机检「字段在场 + 值域合法」;**闸门名指的东西是否真存在、是否真覆盖该条**,留给
     reviewer 抽样核对 —— 不在此假装机检(诚实边界)。
  G. 归属清单自洽(2026-10-18 批2 加,= P1 审查 F2):解析四份「零丢失校验」声明
     (governance §18.1 + 三个 role skill),校验①声称总条数 == 实列 id 数 == 分项括号和 + 「非归档」条数
     ②每个列出的 id 必须在归档索引块内存在(「非归档」除外)③(**C1,批3 加**)清单**标题**里的计数
     == 零丢失等式声称(标题是同一事实的**第三登记点**,批3 前漂了没人管:实测把 gov 标题 28→29
     而等式不动,--check 仍 PASS)。
     ⚠️ 只做**正向**(声明自身自洽 + 指向存在);**反向「归档全量 ⊆ 四清单并集」不成立**(实测差集
     20+ 条存量条目根本没挂归属清单),该项**只报 INFO 不设门** —— 不凭空造一个过不了的检查项(见下)。
     INFO 行含「(含 N 个非归档:id)」动态计数(C3,批3),不再让人拿「并集数 − 归档数」自己手算(E31 型)。

F2 处置留痕(2026-10-18):P1 审查提的「归属清单并集」原本是「每一条归档锚点都该被某个角色清单认领」,
  实测该等式**不成立**(并集 60 余条 < 归档 80 余条),且三份 role skill 清单不在本批可改面内 ⇒
  如实降级为:**正向自洽设门(G)+ 反向差距报 INFO**,不假装成 PASS/FAIL 门。

防空转(§18 L49/L52「假绿/空转」根治):
  · **恒在自检** —— 声称数解析不到 / 索引块锚点集为空 / 根表窗口解析为空 / 结构标题缺失 /
    四份归属清单一个都读不到,一律直接 FAIL,**不允许静默 PASS**;
  · **变异自测 `--selftest`** —— 临时树六向:①负对照(未变异)必须 PASS;②删掉归档最后一条 L
    锚点行 → 必须 FAIL(计数 + 连续性);③把 CLAUDE.md 声称数 nL 篡改成 (n+2)L → 必须 FAIL(三方不一致);
    ④删掉某锚点行的「机检=」字段 → 必须 FAIL(F 维真响);⑤把某份归属清单的「= n 条」改大 → 必须 FAIL(G 维真响);
    ⑥(**C1,批3 加**)把 gov 清单**标题**的 `(28 条` 改成 `(29 条` → 必须 FAIL(第三登记点真响)。
    rc=0 = 自测通过 = 闸门真能响(非空转)。

用法:
  python3 scripts/check_ledger.py              # 仓根默认 = 脚本所在仓根
  python3 scripts/check_ledger.py --repo DIR   # 指定仓根(自测/沙箱用)
  python3 scripts/check_ledger.py --selftest   # 变异自测(一条命令验闸门真能响)
退出码:0 = PASS(含 INFO),1 = FAIL(挂 CI 阻断)。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ARCHIVE_REL = "docs/archive/CLAUDE-errors-2026-08.md"
CLAUDE_REL = "CLAUDE.md"
INDEX_HEADING = "## 防重犯锚点索引"
MD18_HEADING = "## 18. 防重犯索引表"

# 四份「归属清单」声明(每条带「零丢失校验」等式)—— G 维解析对象
OWNERSHIP_DECLS = (
    ("主控归属(governance §18.1)", "docs/main-governance.md"),
    ("实施归属(implementer skill §7)", ".claude/skills/role-implementer/SKILL.md"),
    ("调研归属(researcher skill §5)", ".claude/skills/role-researcher/SKILL.md"),
    ("测试归属(tester skill §6)", ".claude/skills/role-tester/SKILL.md"),
)

_RE_ANCHOR_LINE = re.compile(r"^([LE])(\d+)\b")
_RE_ARCH_HEAD_RANGE_L = re.compile(r"L01-L(\d+) 过错锚点")
_RE_ARCH_HEAD_RANGE_E = re.compile(r"E01-E(\d+) 经验锚点")
_RE_ARCH_ZLOSS = re.compile(r"grep -c '\^L\[0-9\]'` == (\d+)")
_RE_ARCH_SEC_L = re.compile(r"^### 过错锚点\((\d+) 条", re.M)
_RE_ARCH_SEC_E = re.compile(r"^### 经验锚点\((\d+) 条", re.M)
_RE_MD_CLAIM = re.compile(r"\((\d+) 过错\+(\d+) 经验")
_RE_MD_CLAIM_SLIM = re.compile(r"全量 (\d+)L\+(\d+)E")
_RE_MD_ROW = re.compile(r"^\|\s*([LE])(\d+)\s*\|")
_RE_REF_L = re.compile(r"(?<![A-Za-z0-9])L(\d{2})(?![0-9])")
_RE_REF_E = re.compile(r"(?<![A-Za-z0-9])E(\d{2})(?![0-9])")

# ── F/G 维(2026-10-18 批2)──
_RE_JIAN = re.compile(r"机检=(是\(闸门:[^)]+\)|否)")
_RE_OWN_LINE = re.compile(r"零丢失校验[:：]")
# C1(批3):四份归属清单**标题**里的计数(第三登记点)。键 = OWNERSHIP_DECLS 标签去掉括号后的短名。
# 实测四文件全命(gov=28 / impl=22(12+10) / res=9(5+4) / tester=3(1+2),@fabe7c38a)。
_RE_OWN_HEAD = {
    "主控归属": re.compile(r"^## 18\.1 主控专属教训\((\d+) 条", re.M),
    "实施归属": re.compile(r"^## 7\.[^\n]*?(\d+) 条 = 过错 (\d+) \+ 经验 (\d+)\)", re.M),
    "调研归属": re.compile(r"^## 5\.[^\n]*?(\d+) 条 = 过错 (\d+) \+ 经验 (\d+)\)", re.M),
    "测试归属": re.compile(r"^## 6\.[^\n]*?(\d+) 条 = 过错 (\d+) \+ 经验 (\d+)\)", re.M),
}
_RE_OWN_TOTAL = re.compile(r"=\s*(\d+)\s*条")
_RE_OWN_PART = re.compile(r"\((\d+)[^)]*\)")
_RE_OWN_EXEMPT = re.compile(r"([LE]\d{2})\(非归档\)")


# ── 解析 ─────────────────────────────────────────────────────────────────────
def _regions(text: str):
    """归档切三段:(表头, 正文原文快照, 锚点索引块)。结构标题缺失返回 None。"""
    lines = text.splitlines()
    h = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
    idx = next((i for i, ln in enumerate(lines) if ln.startswith(INDEX_HEADING)), None)
    if h is None or idx is None or idx <= h:
        return None
    return lines[:h], lines[h:idx], lines[idx:]


def _anchors(lines):
    """索引块内声明的锚点 id 集(行首 `L\\d+` / `E\\d+`)。"""
    l_ids, e_ids = set(), set()
    for ln in lines:
        m = _RE_ANCHOR_LINE.match(ln)
        if m:
            (l_ids if m.group(1) == "L" else e_ids).add(int(m.group(2)))
    return l_ids, e_ids


def _refs(text: str):
    """文本内引用的锚点 id(剔除 `archive:LNN` 指针与锚点行首 id 本身)。"""
    t = re.sub(r"archive:[LE]\d+", "", text)
    t = re.sub(r"(?m)^[LE]\d+", "", t)
    return (set(int(x) for x in _RE_REF_L.findall(t)),
            set(int(x) for x in _RE_REF_E.findall(t)))


def _gaps(ids) -> list:
    """01..max 之间缺掉的 id(缺号 = 少一条锚点被静默吞掉)。"""
    if not ids:
        return []
    return sorted(set(range(1, max(ids) + 1)) - ids)


def _md18_rows(md: str):
    """CLAUDE.md §18 滚动窗表格行 [(kind, num, 整行文本), ...]。"""
    lines = md.splitlines()
    s = next((i for i, ln in enumerate(lines) if ln.startswith(MD18_HEADING)), None)
    if s is None:
        return None
    e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rows = []
    for i in range(s, e):
        m = _RE_MD_ROW.match(lines[i])
        if m:
            rows.append((m.group(1), int(m.group(2)), lines[i]))
    return rows


def _ownership(root: Path, l_ids, e_ids):
    """G 维:四份归属清单「零丢失校验」等式自洽 + 列出的 id 必须存在于归档索引块。

    只做**正向**(声明自身自洽 + 指向存在);**反向「归档全量 ⊆ 四清单并集」不成立**
    (实测差集 20+ 条存量条目未挂归属清单)⇒ 只报 INFO,不设门(见文件头 F2 处置留痕)。
    """
    fails, passes, infos = [], [], []
    files_found, declared_sum, seen = 0, 0, set()
    for label, rel in OWNERSHIP_DECLS:
        p = root / rel
        if not p.is_file():
            infos.append(f"G. {label}: 声明文件不在({rel})⇒ 该份跳过")
            continue
        files_found += 1
        text = p.read_text(encoding="utf-8")
        hits = [ln for ln in text.splitlines() if _RE_OWN_LINE.search(ln)]
        if not hits:
            fails.append(f"G. {label}: {rel} 内找不到「零丢失校验」声明行 ⇒ 声明消失/漂移,拒绝静默通过")
            continue
        # C1(批3):标题计数 = 同一事实的第三登记点,必须在场且与零丢失等式一致
        head_rx = _RE_OWN_HEAD.get(label.split("(")[0])
        hm = head_rx.search(text) if head_rx else None
        if hm is None:
            fails.append(f"G. {label}: {rel} 标题计数解析不到(标题消失/格式漂移)⇒ "
                         f"第三登记点失守,拒绝静默通过")
        for ln in hits:
            rl, reids = _refs(ln)
            ids = {("L", x) for x in rl} | {("E", x) for x in reids}
            exempt = {(s[0], int(s[1:])) for s in _RE_OWN_EXEMPT.findall(ln)}
            totals = _RE_OWN_TOTAL.findall(ln)
            parts = [int(x) for x in _RE_OWN_PART.findall(ln)]
            if not totals or not ids or not parts:
                fails.append(f"G. {label}: 零丢失等式解析不全(总条数/清单/分项括号缺)⇒ 拒绝静默通过")
                continue
            declared, calc = int(totals[-1]), sum(parts) + len(exempt)
            if declared != len(ids) or declared != calc:
                fails.append(f"G. {label}: 零丢失等式不自洽 → 声称 {declared} 条;实列 {len(ids)} 个 id;"
                             f"分项和 {sum(parts)} + 「非归档」{len(exempt)} = {calc}")
            else:
                passes.append(f"G. {label}: 等式自洽 {declared} 条(= 实列 {len(ids)} 个 id = "
                              f"分项和 {sum(parts)} + 「非归档」{len(exempt)})")
                if hm is not None:
                    if int(hm.group(1)) != declared:
                        fails.append(f"G. {label}: 标题计数({hm.group(1)})与零丢失等式({declared})不一致")
                    elif hm.lastindex and hm.lastindex >= 3:
                        head_parts = [int(hm.group(x)) for x in range(2, hm.lastindex + 1)]
                        if head_parts != parts:
                            fails.append(f"G. {label}: 标题分项({'/'.join(str(x) for x in head_parts)})"
                                         f"与零丢失等式分项({'/'.join(str(x) for x in parts)})不一致")
                        else:
                            passes.append(f"G. {label}: 标题计数 {declared} 条(分项 "
                                          f"{'+'.join(str(x) for x in head_parts)})与等式一致")
                    else:
                        passes.append(f"G. {label}: 标题计数 {declared} 条与等式一致")
            for kind, num in sorted(ids):
                if (kind, num) in exempt:
                    continue
                pool = l_ids if kind == "L" else e_ids
                if num not in pool:
                    fails.append(f"G. {label}: 列出的 {kind}{num:02d} 在归档索引块内不存在")
            declared_sum += declared
            seen |= ids
    if files_found == 0:
        fails.append("G. 四份归属清单声明文件一个都没读到 ⇒ 本维空转,拒绝 PASS")
    else:
        pool_all = {("L", x) for x in l_ids} | {("E", x) for x in e_ids}
        gap = sorted(pool_all - seen)
        unarch = sorted(seen - pool_all)   # C3(批3):动态计,不让人拿「并集数 − 归档数」自己手算
        head = ", ".join(f"{k}{n:02d}" for k, n in gap[:10]) + (" …" if len(gap) > 10 else "")
        unarch_s = ",".join(f"{k}{n:02d}" for k, n in unarch) or "无"
        infos.append(f"G. 归属清单**并集(反向)**未覆盖归档 {len(gap)} 条 / 归档共 {len(pool_all)} 条"
                     f"(四份声明合计 {declared_sum} 条,并集 {len(seen)} 个 id(含 {len(unarch)} 个非归档:"
                     f"{unarch_s}))——存量未认领条目,不设门。差集: {head}")
    return fails, passes, infos


def _one(rx, text, label, group=1):
    m = rx.search(text)
    if not m:
        return None, f"解析不到声称数: {label}"
    return int(m.group(group)), None


# ── 主检查 ───────────────────────────────────────────────────────────────────
def check(root: Path):
    """返回 (fail_lines, pass_lines, info_lines)。"""
    fails: list = []
    passes: list = []
    infos: list = []

    arch_p, md_p = root / ARCHIVE_REL, root / CLAUDE_REL
    if not arch_p.is_file() or not md_p.is_file():
        return [f"缺文件: {ARCHIVE_REL} 或 {CLAUDE_REL} (root={root})"], [], []
    arch = arch_p.read_text(encoding="utf-8")
    md = md_p.read_text(encoding="utf-8")

    reg = _regions(arch)
    if reg is None:
        return [f"归档结构漂移:缺「{INDEX_HEADING}」标题或段序异常 ⇒ 机检挂点失效"], [], []
    header_lines, body_lines, index_lines = reg

    l_ids, e_ids = _anchors(index_lines)
    if not l_ids or not e_ids:
        return [f"索引块解析到锚点为空(L={len(l_ids)} E={len(e_ids)})= 解析器空转,拒绝 PASS"], [], []

    live = "\n".join(header_lines + index_lines)          # 活索引面(表头 + 索引块)
    claims: list = []
    parse_errs: list = []

    def add_claim(label, rx, text, group=1):
        v, err = _one(rx, text, label, group)
        if err:
            parse_errs.append(err)
        else:
            claims.append((label, v))
        return v

    arch_head_l = add_claim("归档表头「L01-L{n} 过错锚点」", _RE_ARCH_HEAD_RANGE_L, live)
    arch_head_e = add_claim("归档表头「E01-E{n} 经验锚点」", _RE_ARCH_HEAD_RANGE_E, live)
    arch_zloss = add_claim("归档零丢失校验锚「`grep -c '^L[0-9]'` == n」", _RE_ARCH_ZLOSS, live)
    arch_sec_l = add_claim("归档「### 过错锚点(n 条」", _RE_ARCH_SEC_L, live)
    arch_sec_e = add_claim("归档「### 经验锚点(n 条」", _RE_ARCH_SEC_E, live)
    md_l = add_claim("CLAUDE.md §18「(n 过错+m 经验)」", _RE_MD_CLAIM, md, 1)
    md_e = add_claim("CLAUDE.md §18「(n 过错+m 经验)」", _RE_MD_CLAIM, md, 2)
    md_l2 = add_claim("CLAUDE.md §18「全量 nL+mE」", _RE_MD_CLAIM_SLIM, md, 1)
    md_e2 = add_claim("CLAUDE.md §18「全量 nL+mE」", _RE_MD_CLAIM_SLIM, md, 2)

    if parse_errs:
        return parse_errs + ["⇒ 声称数解析失败(结构漂移),拒绝 PASS"], [], []

    # ── A / B:计数三方一致 ──
    l_claims = [("归档实际锚点行数", len(l_ids)), ("归档表头 L 范围", arch_head_l),
                ("归档零丢失校验锚", arch_zloss), ("归档章节标题", arch_sec_l),
                ("CLAUDE.md §18 (n 过错)", md_l), ("CLAUDE.md §18 全量 nL", md_l2)]
    e_claims = [("归档实际锚点行数", len(e_ids)), ("归档表头 E 范围", arch_head_e),
                ("归档章节标题", arch_sec_e),
                ("CLAUDE.md §18 (m 经验)", md_e), ("CLAUDE.md §18 全量 mE", md_e2)]
    for tag, claims_ in (("A. L 计数三方一致", l_claims), ("B. E 计数三方一致", e_claims)):
        vals = {v for _, v in claims_}
        if len(vals) == 1:
            n = next(iter(vals))
            passes.append(f"{tag}: {n}  [" + " / ".join(f"{k}={v}" for k, v in claims_) + "]")
        else:
            fails.append(f"{tag}: 声称数与实际不一致 → " + " / ".join(f"{k}={v}" for k, v in claims_))

    # ── C:锚点集连续无缺号(无遗漏)──
    for tag, ids, claimed in (("C. L 锚点集连续", l_ids, l_claims[0][1]),
                              ("C. E 锚点集连续", e_ids, e_claims[0][1])):
        gp = _gaps(ids)
        if gp:
            fails.append(f"{tag}: 01..{max(ids)} 缺号 {gp}(共 {len(gp)} 条锚点缺失)")
        else:
            passes.append(f"{tag}: 01..{max(ids)} 无缺号({len(ids)} 条)")

    # ── D:索引面内引用无悬空 ──
    ref_l, ref_e = _refs(live)
    d_l = sorted(ref_l - l_ids)
    d_e = sorted(ref_e - e_ids)
    if d_l or d_e:
        parts = []
        if d_l:
            parts.append(f"L 悬空 {['L%02d' % x for x in d_l]}")
        if d_e:
            parts.append(f"E 悬空 {['E%02d' % x for x in d_e]}")
        fails.append("D. 索引面引用无悬空: " + "; ".join(parts) + "(引用了未声明的锚点)")
    else:
        passes.append(f"D. 索引面引用无悬空: {len(ref_l)} 个 L 引用 / {len(ref_e)} 个 E 引用全部落点")

    # 正文(历史文本)悬空只报 INFO,不清算(§6④ 历史不追改)
    b_l, b_e = _refs("\n".join(body_lines))
    b_l -= l_ids
    b_e -= e_ids
    if b_l or b_e:
        # E31 专项说明**只在正文确实悬空引用 E31 时**才附(2026-10-27 修:原版把它硬编码在任意
        # 悬空引用上,正文悬空一个 L99 也会被告知「E31 同号不同所指」⇒ 误导;判据见文件头 D 维注)
        e31_note = ""
        if 31 in b_e:
            e31_note = (" —— 其中 E31 指正文历史文本里那条「派单前先核真值」经验(未入 E01-E30 索引);"
                        "须与 gov §18.1 的 E31(codex 通道条)和归档锚点块的 E31(生效判定条)区分,"
                        "三处编号空间互不相干(详见文件头 D 维注)")
        infos.append("正文(原文快照)悬空引用(历史文本,不清算): "
                     + ", ".join([f"L%02d" % x for x in sorted(b_l)] + [f"E%02d" % x for x in sorted(b_e)])
                     + e31_note)

    # ── E:根表窗口锚点已归档(未单独归档显式豁免)──
    rows = _md18_rows(md)
    if not rows:
        return ["E. 根表窗口解析为空 ⇒ 机检空转,拒绝 PASS(CLAUDE.md §18 表格结构漂移?)"], [], infos
    missing, exempt = [], 0
    for kind, num, line in rows:
        pool = l_ids if kind == "L" else e_ids
        if num in pool:
            continue
        if "未单独归档" in line:
            exempt += 1
            continue
        missing.append(f"{kind}{num:02d}")
    if missing:
        fails.append(f"E. 根表窗口锚点已归档: CLAUDE.md §18 滚动窗有但归档缺 {missing}"
                     f"(既未归档、也未自述「未单独归档」)")
    else:
        passes.append(f"E. 根表窗口锚点已归档: {len(rows)} 行中 {len(rows) - exempt} 条在归档内"
                      f" + {exempt} 条自述「未单独归档」豁免,缺档 0")

    # ── F:「机检=」字段在场 + 值域合法 ──
    miss_j, n_yes = [], 0
    for ln in index_lines:
        m = _RE_ANCHOR_LINE.match(ln)
        if not m:
            continue
        aid = f"{m.group(1)}{int(m.group(2)):02d}"
        if "机检=" not in ln:
            miss_j.append(aid)
        elif not _RE_JIAN.search(ln):
            miss_j.append(f"{aid}(值域非法:须是「机检=是(闸门:<名>)」或「机检=否」)")
        elif "机检=是" in ln:
            n_yes += 1
    if miss_j:
        fails.append(f"F. 「机检=」字段: {len(miss_j)} 行缺字段或值域非法 → {miss_j[:12]}"
                     f"{' …' if len(miss_j) > 12 else ''}")
    else:
        passes.append(f"F. 「机检=」字段: {len(l_ids) + len(e_ids)} 条锚点行全部在场且值域合法"
                      f"(其中 是(带闸门名) {n_yes} 条 / 否 {len(l_ids) + len(e_ids) - n_yes} 条)。"
                      f"注:闸门名指的东西是否真存在、是否真覆盖该条,由 reviewer 抽样核对")

    # ── G:四份归属清单「零丢失校验」自洽(正向)+ 并集缺口 INFO(反向)──
    g_f, g_p, g_i = _ownership(root, l_ids, e_ids)
    fails += g_f
    passes += g_p
    infos += g_i

    return fails, passes, infos


# ── 变异自测(防空转)────────────────────────────────────────────────────────
def selftest() -> int:
    import shutil
    import subprocess
    import tempfile

    me = str(Path(__file__).absolute())
    root = Path(__file__).absolute().parent.parent
    ok = True

    def _run(rp: Path):
        r = subprocess.run([sys.executable, me, "--repo", str(rp)],
                           capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr)

    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "docs/archive").mkdir(parents=True)
        shutil.copy2(root / ARCHIVE_REL, t / ARCHIVE_REL)
        shutil.copy2(root / CLAUDE_REL, t / CLAUDE_REL)
        # G 维要读的 4 份归属清单声明文件也拷进临时树(缺了负对照会因「读不到声明」而 FAIL)
        for _, rel in OWNERSHIP_DECLS:
            dst = t / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dst)

        # ① 负对照(未变异)→ 必须 PASS(否则自测装置本身恒 FAIL,证据无效)
        rc0, out0 = _run(t)
        if rc0 == 0 and "RESULT=PASS" in out0:
            print("  PASS: 负对照(未变异样本)→ RESULT=PASS(装置本身非恒 FAIL)")
        else:
            ok = False
            print(f"  FAIL: 负对照(未变异)竟 rc={rc0}, tail={out0.strip().splitlines()[-3:]}")

        # ② 变异:删掉归档索引块最后一条 L 锚点行 → 必须 FAIL(计数 (n-1)≠n)
        ap = t / ARCHIVE_REL
        orig = ap.read_text(encoding="utf-8")
        lines = orig.splitlines(keepends=True)
        hit_i = None
        for i in range(len(lines) - 1, -1, -1):
            if _RE_ANCHOR_LINE.match(lines[i]) and lines[i].startswith("L"):
                hit_i = i
                break
        if hit_i is None:
            ok = False
            print("  FAIL: 变异注入失败(归档里找不到 `^L\\d+` 锚点行)")
        else:
            dropped = lines[hit_i].split("|")[0].strip()
            ap.write_text("".join(lines[:hit_i] + lines[hit_i + 1:]), encoding="utf-8")
            rc1, out1 = _run(t)
            if rc1 != 0 and "RESULT=FAIL" in out1:
                detail = [ln for ln in out1.splitlines() if ln.startswith("  FAIL")]
                print(f"  PASS: 变异样本(删掉索引块最后一条锚点行 {dropped})→ RESULT=FAIL(闸门真响);"
                      f"{detail[0].strip() if detail else ''}")
            else:
                ok = False
                print(f"  FAIL: 删锚点后竟 rc={rc1}(应 FAIL)⇒ 计数/连续性闸门空转, "
                      f"tail={out1.strip().splitlines()[-4:]}")
            ap.write_text(orig, encoding="utf-8")   # 还原

        # ③ 变异:把 CLAUDE.md 声称数 50L 篡改成 52L → 必须 FAIL(三方不一致)
        mp = t / CLAUDE_REL
        mtext = mp.read_text(encoding="utf-8")
        m_new, n_sub = _RE_MD_CLAIM_SLIM.subn(lambda m: f"全量 {int(m.group(1)) + 2}L+{m.group(2)}E", mtext, count=1)
        if n_sub == 0:
            ok = False
            print("  FAIL: 变异注入失败(CLAUDE.md 里找不到「全量 nL+mE」声称)")
        else:
            mp.write_text(m_new, encoding="utf-8")
            rc2, out2 = _run(t)
            if rc2 != 0 and "RESULT=FAIL" in out2 and "A. L 计数三方一致" in out2:
                print("  PASS: 变异样本(CLAUDE.md 声称 nL→(n+2)L)→ RESULT=FAIL(A 三方一致闸门真响)")
            else:
                ok = False
                print(f"  FAIL: 篡改声称数后竟 rc={rc2}(应 FAIL)⇒ A 闸门空转, "
                      f"tail={out2.strip().splitlines()[-4:]}")

        # ④ 变异:删掉某锚点行的「机检=」字段 → 必须 FAIL(F 维真响)
        ap2 = t / ARCHIVE_REL
        orig2 = ap2.read_text(encoding="utf-8")
        lines2 = orig2.splitlines(keepends=True)
        hit2 = next((i for i in range(len(lines2) - 1, -1, -1)
                     if _RE_ANCHOR_LINE.match(lines2[i]) and "机检=" in lines2[i]), None)
        if hit2 is None:
            ok = False
            print("  FAIL: 变异注入失败(归档里找不到带「机检=」的锚点行)")
        else:
            dropped2 = lines2[hit2].split("|")[0].strip()
            lines2[hit2] = lines2[hit2].split(" | 机检=")[0].rstrip() + "\n"
            ap2.write_text("".join(lines2), encoding="utf-8")
            rc3, out3 = _run(t)
            if rc3 != 0 and "RESULT=FAIL" in out3 and "F. 「机检=」字段" in out3:
                print(f"  PASS: 变异样本(删掉 {dropped2} 的「机检=」字段)→ RESULT=FAIL(F 维真响)")
            else:
                ok = False
                print(f"  FAIL: 删「机检=」字段后竟 rc={rc3}(应 FAIL)⇒ F 维空转, "
                      f"tail={out3.strip().splitlines()[-4:]}")
            ap2.write_text(orig2, encoding="utf-8")   # 还原

        # ⑤ 变异:把某份归属清单的「= n 条」改大 → 必须 FAIL(G 维真响)
        gp = t / OWNERSHIP_DECLS[0][1]
        gtext = gp.read_text(encoding="utf-8")
        g_new, g_sub = re.subn(r"(零丢失校验[^\n]*?=\s*)(\d+)(\s*条)",
                               lambda m: f"{m.group(1)}{int(m.group(2)) + 1}{m.group(3)}", gtext, count=1)
        if g_sub == 0:
            ok = False
            print("  FAIL: 变异注入失败(归属清单里找不到「= n 条」声称)")
        else:
            gp.write_text(g_new, encoding="utf-8")
            rc4, out4 = _run(t)
            if rc4 != 0 and "RESULT=FAIL" in out4 and "G. " in out4 and "不自洽" in out4:
                print("  PASS: 变异样本(归属清单声称 n 条→n+1 条)→ RESULT=FAIL(G 维真响)")
            else:
                ok = False
                print(f"  FAIL: 篡改归属清单声称后竟 rc={rc4}(应 FAIL)⇒ G 维空转, "
                      f"tail={out4.strip().splitlines()[-4:]}")
            gp.write_text(gtext, encoding="utf-8")    # 还原

        # ⑥ 变异(C1,批3):把 gov 清单**标题**计数 28→29(等式不动)→ 必须 FAIL(第三登记点真响)
        #    批3 前此变异 rc=0 静默放过(标题漂了没人管);本向把它永久钉死。
        gp2 = t / OWNERSHIP_DECLS[0][1]
        g2text = gp2.read_text(encoding="utf-8")
        g2_new, g2_sub = _RE_OWN_HEAD["主控归属"].subn(
            lambda m: f"## 18.1 主控专属教训({int(m.group(1)) + 1} 条", g2text, count=1)
        if g2_sub == 0:
            ok = False
            print("  FAIL: 变异注入失败(找不到 `## 18.1 主控专属教训(n 条`)")
        else:
            gp2.write_text(g2_new, encoding="utf-8")
            rc5, out5 = _run(t)
            if rc5 != 0 and "RESULT=FAIL" in out5 and "标题计数" in out5:
                detail5 = [ln for ln in out5.splitlines()
                           if ln.startswith("  FAIL") and "标题计数" in ln]
                print(f"  PASS: 变异样本(标题计数 n→n+1)→ RESULT=FAIL(C1 第三登记点真响);"
                      f"{detail5[0].strip() if detail5 else ''}")
            else:
                ok = False
                print(f"  FAIL: 标题变异后竟 rc={rc5}(应 FAIL)⇒ C1 空转, "
                      f"tail={out5.strip().splitlines()[-4:]}")
            gp2.write_text(g2text, encoding="utf-8")  # 还原

    print(f"[ledger-selftest] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


# ── 入口 ─────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="错误台账对账机检(CLAUDE.md §18 防重犯索引表 ↔ 归档锚点索引块)")
    ap.add_argument("--repo", metavar="DIR", default=None,
                    help="仓库根目录(默认 = 脚本所在仓根)")
    ap.add_argument("--selftest", action="store_true",
                    help="变异自测:证明闸门非空转(rc=0 = 自测通过)")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    root = Path(args.repo).absolute() if args.repo else Path(__file__).absolute().parent.parent
    fails, passes, infos = check(root)

    print(f"[ledger] 仓根 {root}")
    for line in passes:
        print(f"  OK   {line}")
    for line in infos:
        print(f"  INFO {line}")
    for line in fails:
        print(f"  FAIL {line}")
    print(f"[ledger] RESULT={'FAIL' if fails else 'PASS'}"
          f"(通过 {len(passes)} 项,失败 {len(fails)} 项)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())