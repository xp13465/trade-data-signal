#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_ledger.py — 错误台账对账机检(CLAUDE.md §18 防重犯索引表 ↔ 归档锚点索引块)。

背景(第三方评鉴 P1,2026-10-18;报告全文 `docs/ops/sugas-eval-20261018.md` §4-W1 + §5-P1):
  体系要求「同一事实多处副本必须机检」(§22),却对**自己的账本**(错误台账)零机检 ⇒ 账已实际漂移:
  归档索引块实际 **50** 条过错锚点,而 CLAUDE.md §18 与本文件表头都声称 **49**;且声称索引块
  「按归属 5 类分节」,归档实测无此结构。同类坑在 memory 索引上已炸过一次(2026-09-27 瘦身掉
  42 行含 17 条活条目、5 周无人发现)。本脚本补上这道机检(挂 CI Job1 `quality-gate-static`)。

对账维度(全 PASS 才 exit 0):
  A. L 计数三方一致:归档 `^L\\d+` 实际条数 == 归档表头声称 == CLAUDE.md §18 声称。
     五项声称数**全部动态解析**(不写死数字)⇒ 日后加锚点只要同步改声称即可,不会又漂。
  B. E 计数三方一致:同上(`^E\\d+`)。
  C. 锚点集完整(无遗漏):L id 必须是 01..N 连续无缺号;E 同理(防「少一条 → 静默过」)。
  D. 无悬空:归档「活索引面」(文件表头 + 防重犯锚点索引块)内**引用**到的每个 L/E 锚点 id
     必须真的在该面里被声明(防引用指向不存在锚点)。
     注:归档「正文」(索引块之前的原文快照)是**历史文本**,其内悬空引用只报 INFO 不清算
     (守 §6④ 历史不追改;实测现存 1 处:E31 指 docs/main-governance.md §18.1 主控专属账本,
      属另一编号空间,非本文件锚点)。
  E. 根表窗口已归档(无遗漏,跨文档):CLAUDE.md §18 滚动窗每个锚点必须在归档索引块内,
     除非该行自述「未单独归档」(显式豁免,不靠人记)。

防空转(§18 L49/L52「假绿/空转」根治):
  · **恒在自检** —— 声称数解析不到 / 索引块锚点集为空 / 根表窗口解析为空 / 结构标题缺失,
    一律直接 FAIL,**不允许静默 PASS**;
  · **变异自测 `--selftest`** —— 临时树三向:①负对照(未变异)必须 PASS;②删掉归档最后一条 L
    锚点行 → 必须 FAIL(计数 + 连续性);③把 CLAUDE.md 声称数 50L 篡改成 52L → 必须 FAIL(三方不一致)。
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
        infos.append("正文(原文快照)悬空引用(历史文本,不清算): "
                     + ", ".join([f"L%02d" % x for x in sorted(b_l)] + [f"E%02d" % x for x in sorted(b_e)]))

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

        # ① 负对照(未变异)→ 必须 PASS(否则自测装置本身恒 FAIL,证据无效)
        rc0, out0 = _run(t)
        if rc0 == 0 and "RESULT=PASS" in out0:
            print("  PASS: 负对照(未变异样本)→ RESULT=PASS(装置本身非恒 FAIL)")
        else:
            ok = False
            print(f"  FAIL: 负对照(未变异)竟 rc={rc0}, tail={out0.strip().splitlines()[-3:]}")

        # ② 变异:删掉归档索引块最后一条 L 锚点行 → 必须 FAIL(计数 49≠50 + 缺号 50)
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
                print("  PASS: 变异样本(CLAUDE.md 声称 50L→52L)→ RESULT=FAIL(A 三方一致闸门真响)")
            else:
                ok = False
                print(f"  FAIL: 篡改声称数后竟 rc={rc2}(应 FAIL)⇒ A 闸门空转, "
                      f"tail={out2.strip().splitlines()[-4:]}")

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