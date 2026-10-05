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
        return parse_dump(args.dump)
    units = {}
    for path in sorted(glob.glob(os.path.join(args.units_dir, "trade-*.service"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            units[os.path.basename(path)] = f.read()
    return units


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
    args = ap.parse_args(argv)

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