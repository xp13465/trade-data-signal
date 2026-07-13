#!/usr/bin/env python3
"""给 index.html 的 CSS/JS 引用注入 ?v=<mtime hex> 版本号，破浏览器/CDN 缓存。

每次改动 web/style.css 或 web/app.js（源码）后：
  1. python scripts/build_min.py        # 重新生成 app.min.js / lab.min.js + source map
  2. python scripts/bump_asset_version.py  # 刷新 ?v= 版本号
  3. commit + push

- web/index.html:        /static/<asset>  -> /static/<asset>?v=<ver>   (ver = web/<asset> 的 mtime)
- static-site/index.html: ./<asset>       -> ./<asset>?v=<ver>          (ver = static-site/<asset> 的 mtime)
- 幂等：已有 ?v= 会被替换为最新 mtime。

注意：app.js/lab.js 是开发源码（保留供开发），index.html 上线引用 app.min.js/lab.min.js。
版本号基于 .min.js 的 mtime，build_min.py 重新生成后 mtime 更新 -> bump 自动刷新版本。

动态站 (FastAPI / 路由) 会动态注入版本号（防忘跑脚本）；
静态站 (Cloudflare Pages) 依赖本脚本 + static-site/_headers 的 no-cache 策略。
"""
import os
import re

BASE = os.path.dirname(os.path.dirname(__file__))
ASSETS = ["style.css", "app.min.js", "lab.css", "lab.min.js", "qr.js", "vendor/echarts.min.js"]


def _ver(path):
    return format(int(os.path.getmtime(path)), "x")


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
    web_dir = os.path.join(BASE, "web")
    ss_dir = os.path.join(BASE, "static-site")
    bump(os.path.join(web_dir, "index.html"), "/static", web_dir)
    bump(os.path.join(ss_dir, "index.html"), "", ss_dir)
    print("完成。记得 commit + push。")


if __name__ == "__main__":
    main()
