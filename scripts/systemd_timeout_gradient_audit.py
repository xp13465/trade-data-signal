#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""systemd 超时梯度审计:外层 service TimeoutStartSec vs 内层脚本 run_to 串行合计。

背景(2026-10-05,task feat/s06-timeout-grad-20261005):
  systemd `TimeoutStartSec` 计量**整个服务(整条脚本)的墙钟**,而脚本内部常有多段
  `run_to <N>`(纯 shell)包装;若外层值 < 内层各段**串行合计**,systemd 会先于内层
  看门狗把脚本杀掉 -> 「结束」行/告警发不出(病灶实例 s06-snapshot 外层 600 < 内层 3000)。
  梯度原则 = 外层 > 内层留梯度(memory `watchdog-inner-timeout-no-gradient`)。
  对多段串行的脚本,「内层」= 各段 run_to 值之和(走最长路径的上界;循环体内的 run_to
  按循环项数倍增,如 `for _D in A B; do run_to 300 ...; done` 计 600)。

用法:
  # 云上直接跑(读 /etc/systemd/system/trade-*.service)
  python3 scripts/systemd_timeout_gradient_audit.py
  # 或读一份 `@@@FILE:<name>` 分隔的 unit dump(本地核对云上快照)
  python3 scripts/systemd_timeout_gradient_audit.py --dump /tmp/cloudunits/units/dump.txt

  # 生成源防漂移(#189,2026-10-05):比对 doc §2 生成源(gen_systemd_units 解析结果)
  # vs 权威 unit 源(云上实值 --units-dir,或仓库内固化快照 --dump),逐字段全量比对,
  # 任一不一致 exit 1。挂 main-merge.sh 7.8,防「doc 旧值被重跑生成器装回云上 = 静默回退」。
  python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --check-doc
  # 对齐模式:把 doc §2 ini 块字段值就地改写为权威源值(改文档;仅覆盖两侧同名且各出现一次的 key)。
  python3 scripts/systemd_timeout_gradient_audit.py --dump docs/deploy/systemd-units-cloud-snapshot.txt --align-doc

局限(须知):
  * 只识别 shell 层 `run_to N` / `perl -e 'alarm ...' N`;Python 侧 subprocess timeout
    (如 nextday_gap_check.py 的 60/300/120)不计入——这类 service 无 shell 内层看门狗,
    外层 systemd 即唯一看门狗,不存在「内层 > 外层」倒挂。
  * 值是**上界**(假定所有 if 分支都走最耗时的路);用于暴露倒挂足够。

只读:不写任何文件、不碰线上服务。
"""

import argparse
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RUN_TO_RE = re.compile(r"\brun_to\s+(\d+)\b")
PERL_ALARM_RE = re.compile(r"alarm[^']*'\s+(\d+)\b")
# for _D in "$REPO/a" "$GIT_REPO/b"; do   /  for x in a b c; do
FOR_RE = re.compile(r"^\s*for\s+\w+\s+in\s+(.+?);?\s*do\s*$")


def parse_dump(dump_path):
    """把 `@@@FILE:<name>` 分隔的 dump 解析为 {name: text}。"""
    units = {}
    cur = None
    for line in open(dump_path, encoding="utf-8", errors="replace"):
        if line.startswith("@@@FILE:"):
            cur = line.split(":", 1)[1].strip()
            units[cur] = ""
        elif cur is not None:
            units[cur] += line
    return units


def read_units(args):
    if args.dump:
        # gradient 审计只针对 service(dump 可能含 timer,如生成源快照;timer 无 TimeoutStartSec 语义)
        return {n: t for n, t in parse_dump(args.dump).items() if n.endswith(".service")}
    units = {}
    for path in sorted(glob.glob(os.path.join(args.units_dir, "trade-*.service"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            units[os.path.basename(path)] = f.read()
    return units


def read_all_units(args):
    """读 service + timer 两类(生成源比对用;gradient 审计只读 service)。"""
    if args.dump:
        return parse_dump(args.dump)
    units = {}
    for pat in ("trade-*.service", "trade-*.timer"):
        for path in sorted(glob.glob(os.path.join(args.units_dir, pat))):
            with open(path, encoding="utf-8", errors="replace") as f:
                units[os.path.basename(path)] = f.read()
    return units


def unit_field_map(text):
    """把 unit 文本(str)或行列表(list)解析为 {key: [value, ...]}(保序)。"""
    d = {}
    it = text.splitlines() if isinstance(text, str) else text
    for raw in it:
        line = raw.rstrip("\n")
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)=(.*)$", line)
        if m:
            d.setdefault(m.group(1), []).append(m.group(2))
    return d


def _doc_block_ranges(lines):
    """解析 doc 的 (unit 名 -> ini 内容行区间 [start, end))。复用 gen_systemd_units 的 TITLE_RE。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gen_systemd_units as G
    blocks = {}
    i, n = 0, len(lines)
    while i < n:
        m = G.TITLE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        name = m.group(1)
        j = i + 1
        while j < n:
            if G.TITLE_RE.match(lines[j].strip()):
                break
            if lines[j].strip() == "```ini":
                k = j + 1
                while k < n and lines[k].strip() != "```":
                    k += 1
                blocks[name] = (j + 1, k)
                break
            j += 1
        i += 1
    return blocks


def _doc_vs_units_diffs(order, doc_units, units):
    """返回逐字段差异列表 [(unit, key, doc_val_list, auth_val_list)] + 单边 unit 名单。"""
    diffs = []
    only_doc = [n for n in order if n not in units]
    only_auth = [n for n in units if n not in doc_units]
    for name in order:
        if name not in units:
            continue
        dk = unit_field_map(doc_units[name])
        ck = unit_field_map(units[name])
        for key in sorted(set(dk) | set(ck)):
            if sorted(dk.get(key, [])) != sorted(ck.get(key, [])):
                diffs.append((name, key, dk.get(key), ck.get(key)))
    return diffs, only_doc, only_auth


def _align_doc_inplace(md_path, units):
    """把 doc ini 块内「两侧同名且各出现一次」的 key 值就地改写为权威源值。返回改动处数。

    只在 ```ini 块内改值,不动标题/prose/结构;多值 key(如 Environment 多行)保守跳过,
    留给 --check-doc 报差异人工处理。
    """
    with open(md_path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    blocks = _doc_block_ranges(lines)
    changed = 0
    for name, (s, e) in blocks.items():
        if name not in units:
            continue
        ck = unit_field_map(units[name])
        doc_cnt = {}
        for idx in range(s, e):
            mm = re.match(r"^([A-Za-z][A-Za-z0-9_]*)=(.*)$", lines[idx])
            if mm:
                doc_cnt[mm.group(1)] = doc_cnt.get(mm.group(1), 0) + 1
        for idx in range(s, e):
            mm = re.match(r"^([A-Za-z][A-Za-z0-9_]*)=(.*)$", lines[idx])
            if not mm:
                continue
            key = mm.group(1)
            if len(ck.get(key, [])) == 1 and doc_cnt.get(key) == 1:
                want = ck[key][0]
                if mm.group(2) != want:
                    lines[idx] = f"{key}={want}"
                    changed += 1
    if changed:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return changed


def doc_sync(args, units):
    """比对(doc §2 生成源)vs(权威 unit 源);--align-doc 时先就地对齐再复检。返回退出码。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import gen_systemd_units as G

    md_path = args.md or G.default_md_path()

    if args.align_doc:
        changed = _align_doc_inplace(md_path, units)
        print(f"已对齐 {changed} 处字段值 → {md_path}")

    order, doc_units = G.parse_units(md_path)
    diffs, only_doc, only_auth = _doc_vs_units_diffs(order, doc_units, units)

    if diffs or only_doc or only_auth:
        print(f"✗ 生成源(doc §2)与权威 unit 源不一致:差异字段 {len(diffs)} 处"
              f",仅 doc {len(only_doc)} unit,仅权威源 {len(only_auth)} unit")
        hdr = f"{'unit':44} {'field':26} {'doc':>16} {'authoritative':>16}"
        print(hdr)
        print("-" * len(hdr))
        for name, key, dv, cv in diffs:
            print(f"{name:44} {key:26} {str(dv):>16} {str(cv):>16}")
        for n in only_doc:
            print(f"{n:44} {'<unit>':26} {'存在':>16} {'缺失':>16}")
        for n in only_auth:
            print(f"{n:44} {'<unit>':26} {'缺失':>16} {'存在':>16}")
        return 1
    print(f"✓ 生成源(doc §2)与权威 unit 源一致({len(order)} unit,逐字段全量比对通过)")
    return 0


def field(text, key):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return None


def exec_script(text):
    """ExecStart 最后一个参数若指向 *.sh,返回其 basename(否则 None)。"""
    ex = field(text, "ExecStart")
    if not ex:
        return None
    target = ex.split()[-1] if ex.split() else ""
    return os.path.basename(target) if target.endswith(".sh") else None


def inner_serial_sum(script_name):
    """脚本内层看门狗串行合计(上界):sum(run_to N × 所在 for 循环项数)。

    返回 (总秒, 命中的段数);无任何 run_to/alarm 时返回 (None, 0)。
    文本级近似:用 for/done 栈跟踪嵌套循环项数,循环体内 run_to 按栈内项数之积倍增;
    多行 `for x in a b` + 独立 `do` 行的手写风格未识别(本项目内层包装均为单行 for,足够)。
    """
    path = os.path.join(REPO, "scripts", script_name)
    if not os.path.isfile(path):
        return None, 0
    total, hits = 0, 0
    stack = []  # 嵌套 for 的项数栈;当前倍增 = 栈内所有项数之积
    for raw in open(path, encoding="utf-8", errors="replace"):
        line = raw.split("#", 1)[0]
        mult = 1
        for v in stack:
            mult *= v
        m = FOR_RE.match(line)
        if m:
            items = [t for t in m.group(1).split() if t]
            stack.append(max(len(items), 1))
        elif re.match(r"^\s*done\b", line) and stack:
            stack.pop()
        vals = [int(x) for x in RUN_TO_RE.findall(line)]
        vals += [int(x) for x in PERL_ALARM_RE.findall(line)]
        if vals:
            hits += len(vals)
            total += sum(vals) * mult
    return (total if hits else None), hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="systemd 超时梯度审计(外层 vs 内层 run_to 串行合计)")
    ap.add_argument("--dump", help="@@@FILE: 分隔的 unit dump 文件")
    ap.add_argument("--units-dir", default="/etc/systemd/system",
                    help="unit 目录(默认 /etc/systemd/system)")
    ap.add_argument("--check-doc", action="store_true",
                    help="比对 doc §2 生成源 vs 权威 unit 源(逐字段),不一致 exit 1(#189 生成源防漂移)")
    ap.add_argument("--align-doc", action="store_true",
                    help="把 doc §2 ini 块字段值就地对齐权威源值(改文档;配合 --dump/--units-dir)")
    ap.add_argument("--md", default=None,
                    help="doc 路径(默认 = gen_systemd_units 的 MD_REL_PATH)")
    args = ap.parse_args(argv)

    if args.check_doc or args.align_doc:
        units = read_all_units(args)
        if not units:
            print("未读到任何 trade-*.service / trade-*.timer", file=sys.stderr)
            return 2
        return doc_sync(args, units)

    units = read_units(args)
    if not units:
        print("未读到任何 trade-*.service", file=sys.stderr)
        return 2

    hdr = f"{'service':44} {'script':26} {'outer':>6} {'inner':>7}  status"
    print(hdr)
    print("-" * len(hdr))
    fails, fails_noinner, n = 0, 0, 0
    for name in sorted(units):
        text = units[name]
        outer = field(text, "TimeoutStartSec")
        outer_sec = 90 if outer is None else int(outer)  # 缺省 systemd 默认 90s
        script = exec_script(text)
        isum, _ = inner_serial_sum(script) if script else (None, 0)
        n += 1

        if script is None:
            status, sdisp = "—(非 .sh,无 shell 内层看门狗)", "-"
        elif isum is None:
            fails_noinner += 1
            status, sdisp = "—(.sh 但无 run_to,外层即唯一看门狗)", script
        elif outer_sec == 0:
            status, sdisp = "OK(外层=0 无限)", script
        elif outer_sec > isum:
            status, sdisp = f"OK(余量 {outer_sec - isum}s)", script
        else:
            fails += 1
            status, sdisp = f"FAIL(外层 {outer_sec} <= 内层 {isum})", script
        idep = "-" if isum is None else str(isum)
        print(f"{name:44} {sdisp:26} {outer_sec:>6} {idep:>7}  {status}")
    print("-" * len(hdr))
    print(f"共 {n} service;倒挂 FAIL {fails} 个;.sh 无内层看门狗 {fails_noinner} 个(外包 systemd 唯一看门狗)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())