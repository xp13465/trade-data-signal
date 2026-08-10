#!/usr/bin/env python3
"""给 index.html 的 CSS/JS 引用注入 ?v=<content hash> 版本号，破浏览器/CDN 缓存。

每次改动 static-site/style.css 或 static-site/app.js（源码）后：
  1. python scripts/build_min.py        # 重新生成 app.min.js / lab.min.js + source map
  2. python scripts/bump_asset_version.py  # 刷新 ?v= 版本号
  3. commit + push

- static-site/index.html: ./<asset>       -> ./<asset>?v=<ver>          (ver = static-site/<asset> 的 md5 前 8 位)
- 幂等：已有 ?v= 会被替换为最新内容哈希。

注意：app.js/lab.js 是开发源码（保留供开发），index.html 上线引用 app.min.js/lab.min.js。
版本号基于 .min.js 的内容哈希，build_min.py 重新生成后内容变化 -> bump 自动刷新版本。

动态站 (FastAPI / 路由) 会动态注入版本号（防忘跑脚本）；
静态站 (Cloudflare Pages) 依赖本脚本 + static-site/_headers 的 no-cache 策略。
"""
import glob
import hashlib
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = os.path.dirname(os.path.dirname(__file__))
ASSETS = ["style.min.css", "common.min.js", "purpose-notes.min.js", "kelly-review-notes.min.js", "app.min.js", "lab.min.css", "lab.min.js", "qr.js", "vendor/echarts.min.js"]

# 显式 Asia/Shanghai 时区，根治日期逻辑隐患：
# datetime.now() 不带 tz 时取系统本地时区，若系统 TZ 配错或脚本在 UTC 环境(如某些 CI/Launchd
# 缺 TZ 继承)下跑，UTC 16:00-24:00 会落到"昨天"（UTC 16:00 = 北京次日 00:00）。
# 2026-07-29 事故：sw.js CACHE_VERSION 曾被手工误写为 v2-20260720-a54（应为 20260729），
# 根因是无脚本约束、纯手工编辑易错。bump_sw_version() 用本时区自动生成日期根治此隐患。
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 匹配 sw.js: const CACHE_VERSION = 'v2-20260729-a58';
# 分三组：前缀 'v2-' / 日期 '20260729' / 后缀 '-a58'，只替换日期组。
SW_CACHE_VER_RE = re.compile(r"(CACHE_VERSION\s*=\s*'v\d+-)(\d{8})(-a\d+')")


def _ver(path):
    """返回文件内容 md5 前 8 位（16 进制），内容相同则版本号相同。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def today_version():
    """返回 Asia/Shanghai 当天日期 YYYYMMDD（8 位字符串）。

    显式指定时区根治两类隐患：
      1. UTC 边界：UTC 16:00 = 北京次日 00:00，用 datetime.now()/date.today()
         不带 tz 在 UTC 16:00-24:00 会取到"昨天"（launchd/CI 环境易缺 TZ 继承）。
      2. 手工写错：sw.js CACHE_VERSION 曾手工误写 20260720（应为 20260729），
         脚本化生成消除人为出错。
    """
    return datetime.now(TZ_SHANGHAI).strftime("%Y%m%d")


def bump_sw_version(sw_path):
    """同步 sw.js 的 CACHE_VERSION 日期部分为 Asia/Shanghai 当天。

    CACHE_VERSION 格式: 'v<N>-<YYYYMMDD>-a<M>'
      - v<N>:     大版本（手工管理，不动）
      - YYYYMMDD: 日期（自动同步为当天，根治手工误写）
      - a<M>:     小版本（改 sw 内容时手工 +1，不动）

    幂等：日期已是今天则不改文件（避免无意义写入触发缓存失效）。
    返回 True 表示有改写，False 表示跳过（未匹配/已是今天/文件不存在）。
    """
    if not os.path.exists(sw_path):
        print(f"  · {os.path.relpath(sw_path, BASE)}（sw.js 不存在，跳过）")
        return False
    with open(sw_path, encoding="utf-8") as f:
        content = f.read()
    m = SW_CACHE_VER_RE.search(content)
    if not m:
        print(f"  · {os.path.relpath(sw_path, BASE)}（未匹配 CACHE_VERSION 'vN-YYYYMMDD-aM'，跳过）")
        return False
    current_date = m.group(2)
    today = today_version()
    if current_date == today:
        print(f"  · {os.path.relpath(sw_path, BASE)}（CACHE_VERSION 日期已是今天 {today}，跳过）")
        return False
    new_content = content[:m.start(2)] + today + content[m.end(2):]
    with open(sw_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"  ✓ {os.path.relpath(sw_path, BASE)} 日期 {current_date} -> {today}")
    return True


def bump(html_path, prefix, asset_dir):
    """prefix='/static' (web) 或 '' (static-site 用 './')；asset_dir 为资源所在目录。"""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    changed = False
    for a in ASSETS:
        ver = _ver(os.path.join(asset_dir, a))
        ref = f"{prefix}/{a}" if prefix else f"./{a}"
        pattern = re.compile(re.escape(ref) + r"(\?v=[a-f0-9]+)?")
        html, n = pattern.subn(f"{ref}?v={ver}", html)
        if n:
            changed = True
    if changed:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  ✓ {os.path.relpath(html_path, BASE)}")
    else:
        print(f"  · {os.path.relpath(html_path, BASE)}（未找到资源引用，跳过）")
    return changed


def main():
    print("注入 CSS/JS 版本号：")
    ss_dir = os.path.join(BASE, "static-site")
    # 扫描 static-site/ 下所有引用 ./<asset> 的 HTML 页面（index/privacy/about 等）
    for html_path in sorted(glob.glob(os.path.join(ss_dir, "*.html"))):
        bump(html_path, "", ss_dir)
    # 同步 sw.js CACHE_VERSION 日期为 Asia/Shanghai 当天（根治手工误写，如 20260720 应为 20260729）
    bump_sw_version(os.path.join(ss_dir, "sw.js"))
    print("完成。记得 commit + push。")


if __name__ == "__main__":
    main()
