#!/usr/bin/env python3
"""把 docs/kelly-backtest-*.md 转 HTML，输出 static-site/kelly-review-notes.js。

复用 purpose-notes.js 模式：纯配置对象，无 IIFE 副作用，无 DOM 依赖。
加载顺序：index.html 中 kelly-review-notes.min.js 用 <script defer> 在 purpose-notes.min.js 之后、app.min.js 之前加载。

用法：
  python scripts/md_to_html.py

依赖：
  pip install markdown   (需 extensions=['tables','fenced_code'] 支持 GFM 表格+代码块)

幂等：可重复运行覆盖。
"""
import json
import os
import sys

try:
    import markdown as md
except ImportError:
    print("✗ markdown 未安装，请运行: pip install markdown", file=sys.stderr)
    sys.exit(1)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (md 源文件相对路径, JS 对象 key)
DOCS = [
    ("docs/kelly-backtest-comparison.md", "comparison"),
    ("docs/kelly-backtest-comprehensive-review.md", "comprehensive"),
    ("docs/kelly-backtest-deepseek-review.md", "deepseek"),
]

OUTPUT = os.path.join(BASE, "static-site", "kelly-review-notes.js")


def md_to_html(md_path):
    """读 markdown 文件，转 HTML 字符串。"""
    full = os.path.join(BASE, md_path)
    if not os.path.exists(full):
        print(f"  ✗ 源不存在: {md_path}")
        return ""
    with open(full, encoding="utf-8") as f:
        text = f.read()
    html = md.markdown(text, extensions=["tables", "fenced_code"])
    return html


def main():
    print("=== md_to_html: kelly-backtest-*.md -> kelly-review-notes.js ===")
    obj = {}
    for md_rel, key in DOCS:
        html = md_to_html(md_rel)
        obj[key] = html
        sz = len(html.encode("utf-8"))
        print(f"  ✓ {md_rel} -> {key} ({sz:,}B)")

    # JSON 序列化为 JS 对象（双引号在 JS 中合法，json.dumps 处理所有转义）
    js_obj = json.dumps(obj, ensure_ascii=False)
    output = f"// === 凯利回测双AI对比文档(md->html 预处理生成) ===\n"
    output += f"// 由 scripts/md_to_html.py 从 docs/kelly-backtest-*.md 生成，勿手动编辑\n"
    output += f"// 加载顺序: index.html 中 kelly-review-notes.min.js 用 <script defer> 在 purpose-notes.min.js 之后\n"
    output += f"var KELLY_REVIEW_NOTES = {js_obj};\n"

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(output)
    out_sz = os.path.getsize(OUTPUT)
    print(f"\n完成: {OUTPUT} ({out_sz:,}B)")
    print("记得跑 build_min.py 生成 .min.js + bump_asset_version.py 刷新 ?v=")
    return 0


if __name__ == "__main__":
    sys.exit(main())
