#!/usr/bin/env python3
"""用 terser minify app.js / lab.js，生成 .min.js（不生成 source map，防线上泄露源码）。

对 static-site/ 生成 app.min.js / lab.min.js。
保留原文件供开发，min 版上线引用（index.html 引用 .min.js）。
可重复运行覆盖。幂等。

用法：
  python scripts/build_min.py

依赖：npx terser（首次运行 npx --yes terser 自动下载缓存，无需项目内 npm install）。
失败处理：任一文件 minify 失败则退出码 1，已成功的文件仍保留。

deploy.sh 会在 export.py 后调用本脚本，确保上线前 min 文件总是新鲜。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (源相对路径, 目标相对路径) -- 顺序：web 先于 static-site，app 先于 lab
PAIRS = [
    ("static-site/app.js", "static-site/app.min.js"),
    ("static-site/lab.js", "static-site/lab.min.js"),
]


def _check_terser():
    """确认 npx terser 可用，返回版本字符串或 None。"""
    r = subprocess.run(
        ["npx", "--yes", "terser", "--version"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def minify(src_rel, dst_rel):
    """对单个文件跑 terser minify（不生成 source map，防线上泄露源码）。"""
    src = os.path.join(BASE, src_rel)
    dst = os.path.join(BASE, dst_rel)
    if not os.path.exists(src):
        # 源缺失视为跳过（非失败）：trade-data 架构下 static-site/app.js 等源不在采集仓库，
        # build_min 作为 deploy 的安全网，缺源不应致退出码 1（deploy.sh 已视 build_min 失败为非阻断，
        # 但跳过可消除噪音 + 退出码 0 便于脚本判断）。返回 None 区别于 terser 真失败（False）。
        print(f"  · 跳过（源不存在）：{src_rel}")
        return None
    src_dir = os.path.dirname(src)          # /abs/static-site
    src_name = os.path.basename(src)        # app.js / lab.js
    dst_name = os.path.basename(dst)        # app.min.js / lab.min.js

    # terser 在 src_dir 内运行：输入 app.js -> 输出 app.min.js（无 sourceMappingURL 注释、无 .map）
    cmd = [
        "npx", "--yes", "terser", src_name,
        "--compress", "--mangle",
        "-o", dst_name,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=src_dir, timeout=300)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[:400]
        print(f"  ✗ terser 失败 [{src_rel}]: {err}")
        return False

    src_sz = os.path.getsize(src)
    dst_sz = os.path.getsize(dst)
    pct = (1 - dst_sz / src_sz) * 100 if src_sz else 0
    print(f"  ✓ {src_rel} ({src_sz:,}B) -> {dst_rel} ({dst_sz:,}B, -{pct:.1f}%)")
    return True


def main():
    print("=== terser minify 构建 ===")
    ver = _check_terser()
    if not ver:
        print("✗ terser 不可用（npx --yes terser --version 失败）")
        print("  排查：npx 是否在 PATH、是否联网首次下载 terser")
        return 1
    print(f"  terser {ver} 可用")

    ok = True
    built = 0
    skipped = 0
    for src_rel, dst_rel in PAIRS:
        res = minify(src_rel, dst_rel)
        if res is None:        # 缺源跳过（非失败）
            skipped += 1
        elif res:              # 成功
            built += 1
        else:                  # terser 真失败
            ok = False

    if not ok:
        print("✗ 部分 minify 失败，请检查上方错误")
        return 1

    print(f"完成（built={built} skipped={skipped}）。记得跑 bump_asset_version.py 刷新 ?v= 版本号。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
