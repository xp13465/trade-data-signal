#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
systemd unit 生成器:从落档文档 docs/deploy/systemd-units-20260912.md 解析出全部
trade-*.timer / trade-*.service unit 文件,输出到指定目录。

用途(阶段4 macOS→阿里云迁移落地):可复现生成,不手写 72 个文件。

用法:
  python3 scripts/gen_systemd_units.py <输出目录>            # 生成(目录不存在则创建)
  python3 scripts/gen_systemd_units.py --check [输出目录]     # 只校验不写,打印「N 个 unit 待生成」

解析规则(与文档结构对应):
  - 只认标题行 `` `trade-<name>.timer` `` / `` `trade-<name>.service` ``(反引号包裹 + 尾部冒号)
  - 标题行到下一个标题行之间找第一个 ```ini 代码块,块内容 = 该 unit 文件内容
  - 标题与 ini 块之间的说明文字(如 `- 源:` / `- 参数:` / `- 时点:`)跳过,不写入文件
  - §3 飞书(不迁)/ §5 不迁 / §6 未加载 / §7 落地注意事项,非 unit 标题,自然跳过

安全约束:
  - 只读文档、只写指定输出目录,不碰线上产物、不跑部署、不 enable/start 任何服务
  - 生成文件若含 `EnvironmentFile=/opt/trade/.env` 属文档已去明文的正常内容,保持原样,
    不往里塞任何真实 secret
"""

import argparse
import os
import re
import sys

# 文档文件名与相对路径(相对仓库根)
MD_REL_PATH = os.path.join("docs", "deploy", "systemd-units-20260912.md")

# 标题行:`trade-xxx.timer`:(反引号 + trade- 前缀 + 文件名 + 反引号 + 冒号)
TITLE_RE = re.compile(r"^`(trade-[A-Za-z0-9-]+\.(?:timer|service))`:$")


def repo_root():
    """脚本所在 scripts/ 的上一级 = 仓库根。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_md_path():
    return os.path.join(repo_root(), MD_REL_PATH)


def parse_units(md_path):
    """解析 markdown,返回 (unit_names 有序列表, name -> 内容行列表 字典)。

    只认 TITLE_RE 匹配的标题行;标题到下一个标题之间取第一个 ```ini 块;
    标题与 ini 块之间的说明文字自然跳过。
    """
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    order = []          # 保持文档出现顺序
    units = {}          # name -> [内容行, ...]

    i = 0
    n = len(lines)
    while i < n:
        m = TITLE_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue

        name = m.group(1)
        content_lines = None
        # 从标题下一行起,到下一个标题(或 EOF)之间,找第一个 ```ini 块
        j = i + 1
        while j < n:
            if TITLE_RE.match(lines[j].strip()):
                break
            if lines[j].strip() == "```ini":
                k = j + 1
                buf = []
                while k < n and lines[k].strip() != "```":
                    buf.append(lines[k])
                    k += 1
                content_lines = buf
                break
            j += 1

        if content_lines is None:
            print(f"WARN: 标题 {name} 后未找到 ```ini 代码块,已跳过", file=sys.stderr)
        elif name in units:
            print(f"WARN: unit 名 {name} 重复出现,保留首次", file=sys.stderr)
        else:
            units[name] = content_lines
            order.append(name)
        i += 1

    return order, units


def render_unit(content_lines):
    """把内容行列表渲染成文件文本:逐行换行 + 末尾补一个换行。"""
    return "\n".join(content_lines) + "\n"


def write_units(outdir, order, units):
    os.makedirs(outdir, exist_ok=True)
    written = 0
    for name in order:
        path = os.path.join(outdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_unit(units[name]))
        written += 1
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="从落档文档解析生成 systemd unit 文件(阶段4 迁移落地用)"
    )
    parser.add_argument(
        "outdir",
        nargs="?",
        default=None,
        help="输出目录(不存在则创建);--check 模式下可省略",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验解析、打印待生成 unit 数,不写任何文件",
    )
    args = parser.parse_args(argv)

    md_path = default_md_path()
    if not os.path.isfile(md_path):
        print(f"FATAL: 文档不存在: {md_path}", file=sys.stderr)
        return 2

    order, units = parse_units(md_path)
    n = len(order)

    if args.check:
        print(f"{n} 个 unit 待生成")
        return 0

    if not args.outdir:
        print("FATAL: 缺少输出目录(用法: gen_systemd_units.py <输出目录>)", file=sys.stderr)
        return 2

    written = write_units(args.outdir, order, units)
    print(f"已生成 {written} 个 unit 文件到 {args.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
