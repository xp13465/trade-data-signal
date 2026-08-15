#!/usr/bin/env python3
"""把 docs/kelly/ 的 10 份凯利回测报告 md 转 HTML，输出 static-site/kelly-reports-content.js。

目的: 为「凯利回测报告查看弹窗」提供完整正文(非仅目录)。前端 lab.js _kellyReportModalHTML()
从全局 KELLY_REPORTS_CONTENT[id] 读取该报告完整 HTML 正文展示, 保留 h1-h4 结构与表格/代码块。

复用 scripts/md_to_html.py 模式: 纯配置对象, 无 IIFE 副作用, 无 DOM 依赖。
加载顺序: index.html 中 <script defer> 在 purpose-notes.min.js 之后、app.min.js 之前加载(terser
mangle keep_fnames 保留全局变量名 KELLY_REPORTS_CONTENT, 前端 window.KELLY_REPORTS_CONTENT 读取)。

方法口径: GFM markdown 转 HTML, 使用 markdown 库 extensions=['tables','fenced_code'](与 md_to_html.py 同款)。
前端弹窗将正文容器 class=.lab-kelly-repo-body 设 white-space:normal(表格/代码块用独立样式), 目录(TOC)折叠。

用法(复现):
  python scripts/kelly_reports_html.py

依赖:
  pip install markdown   (需 extensions=['tables','fenced_code'] 支持 GFM 表格+代码块)

输入: 10 份报告 md 路径(下方 DOCS 声明, 与 static-site/lab.js _KELLY_REPORTS 的 id/path 一一对应, §23.5 数据来源一致)
输出: static-site/kelly-reports-content.js(定义 var KELLY_REPORTS_CONTENT = {id: html})

幂等: 可重复运行覆盖。改 docs/kelly/*.md 后需重跑本脚本 + build_min.py + bump_asset_version.py(§24 前端铁律)。
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

# (报告 md 相对路径, JS 对象 key), 与 static-site/lab.js _KELLY_REPORTS 的 id/path 对齐(§23.5)
DOCS = [
    ("docs/kelly/position/kelly-position-filter-backtest.md", "kelly-position-filter-backtest"),
    ("docs/kelly/position/kelly-position-cap-k-sensitivity.md", "kelly-position-cap-k-sensitivity"),
    ("docs/kelly/position/kelly-dailypool-exhaustive-rerun.md", "kelly-dailypool-exhaustive-rerun"),
    ("docs/kelly/position/kelly-g-mode-recheck.md", "kelly-g-mode-recheck"),
    ("docs/kelly/position/kelly-ghi-continuous-cap-sweep.md", "kelly-ghi-continuous-cap-sweep"),
    ("docs/kelly/position/kelly-nextday-batch-limit-sop.md", "kelly-nextday-batch-limit-sop"),
    ("docs/kelly/combo/kelly-combo-usage-advice.md", "kelly-combo-usage-advice"),
    ("docs/kelly/combo/kelly-jan-adjust-combo-verify.md", "kelly-jan-adjust-combo-verify"),
    ("docs/kelly/analysis/kelly-fee-adjust.md", "kelly-fee-adjust"),
    ("docs/kelly/analysis/kelly-fee-presets.md", "kelly-fee-presets"),
]

OUTPUT = os.path.join(BASE, "static-site", "kelly-reports-content.js")


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
    print("=== kelly_reports_html: docs/kelly/ 10 份报告 md -> kelly-reports-content.js ===")
    obj = {}
    for md_rel, key in DOCS:
        html = md_to_html(md_rel)
        obj[key] = html
        sz = len(html.encode("utf-8"))
        print(f"  ✓ {md_rel} -> {key} ({sz:,}B)")

    # JSON 序列化为 JS 对象（json.dumps 处理所有转义, 与 md_to_html.py 同款, html 内 </script> 由 markdown 无语义保留,
    # 但 docs 报告无 <script> 标签(GFM 无 script 语法), 且文档标题/正文均为文本, 无 HTML 注入风险）
    js_obj = json.dumps(obj, ensure_ascii=False)
    output = f"// === 凯利回测报告文档(10 份, md->html 预处理生成, 供 lab.js 报告弹窗完整正文展示) ===\n"
    output += f"// 由 scripts/kelly_reports_html.py 从 docs/kelly/**/*.md 生成, 勿手动编辑\n"
    output += f"// 加载顺序: index.html 中 kelly-reports-content.min.js 用 <script defer> 在 purpose-notes.min.js 之后\n"
    output += f"// 目录(key)与 lab.js _KELLY_REPORTS 的 id/path 一一对应(§23.5 数据来源一致)\n"
    output += f"var KELLY_REPORTS_CONTENT = {js_obj};\n"

    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(output)
    out_sz = os.path.getsize(OUTPUT)
    print(f"\n完成: {OUTPUT} ({out_sz:,}B)")
    print("记得跑 build_min.py 生成 .min.js + bump_asset_version.py 刷新 ?v= + 同步 sw.js CACHE_VERSION(§24)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
