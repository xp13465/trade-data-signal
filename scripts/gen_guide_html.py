#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
目的:将 docs/理财专员使用指南.md 渲染为 static-site/guide.html 静态页。
方法口径:markdown(python) 3.10.3,扩展 tables/fenced_code/toc/sane_lists;toc 生成目录(过滤 H1 主标题,只留 H2-H4);正文用页面 H1 标题替代 md 主 H1。
输入依赖:docs/理财专员使用指南.md(613 行,46 标题 + 102 表格行)
输出:static-site/guide.html(纯静态 HTML,复用 about.html 的 head 模板 + inline style + CSS 变量主题 + baidu 统计)
复现命令:python3 scripts/gen_guide_html.py
关键说明:纯静态页,不 bump 版本串/不 build_min/不动数据产物;baidu 统计脚本串与 about.html 原样一致。
"""
import markdown
import re
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_PATH = os.path.join(ROOT, "docs", "理财专员使用指南.md")
OUT_PATH = os.path.join(ROOT, "static-site", "guide.html")

HEAD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>理财专员使用指南 · 信号实验室(tdsignal)</title>
  <meta name="description" content="信号实验室(tdsignal)理财专员使用指南:站点定位、适合人群、6大核心板块、每日操作流程、基于真实回测的预期收益、风险提示、进阶用法。本站为个人学习与研究工具,非持牌证券投资咨询机构,不荐股,不构成投资建议。">
  <meta name="keywords" content="信号实验室,tdsignal,理财专员,使用指南,A股情绪看板,盘后复盘,恐贪指数,市场宽度,技术分析参考点,风险提示">
  <meta name="robots" content="index,follow">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <link rel="canonical" href="https://ss.fx8.store/guide.html">
  <link rel="icon" href="data:,">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="信号实验室">
  <meta property="og:title" content="理财专员使用指南 | 信号实验室(tdsignal)">
  <meta property="og:description" content="站点定位、适合人群、6大核心板块、每日操作流程、基于真实回测的预期收益、风险提示、进阶用法。非持牌证券投资咨询机构,不构成投资建议。">
  <meta property="og:url" content="https://ss.fx8.store/guide.html">
  <meta property="og:image" content="https://ss.fx8.store/og.png">
  <meta property="og:locale" content="zh_CN">
  <link rel="stylesheet" href="./style.min.css?v=20260818-a351">
  <link rel="stylesheet" href="./lab.min.css?v=20260818-a351">
  <!-- 防闪烁:CSS 加载后、body 渲染前读 localStorage 提前设 data-theme -->
  <script>
  (function(){
    try {
      var t = localStorage.getItem('trade-theme');
      if (t === null) t = 'redgold';
      if (t) document.documentElement.setAttribute('data-theme', t);
    } catch(e){
      document.documentElement.setAttribute('data-theme', 'redgold');
    }
  })();
  </script>
</head>
<body>
  <main class="about-wrap">
    <header class="about-header">
      <h1>📖 理财专员使用指南</h1>
      <p class="about-sub">信号实验室 · tdsignal · 面向理财专员讲解如何使用本网站</p>
      <p class="about-sites">主站 <a href="https://ss.fx8.store/">ss.fx8.store</a>(Cloudflare Workers)/ 备站 <a href="https://sss.sugas.site/">sss.sugas.site</a>(GitHub Pages)/ <a href="https://s.sugas.site/">s.sugas.site</a>(MaoziYun)</p>
      <p><a href="/about.html" class="about-back">← 返回关于页</a> · <a href="/" class="about-back">返回看板</a></p>
    </header>

    <section class="about-toc">
      <h2>📋 目录</h2>
      {{TOC}}
    </section>

    <article class="about-guide">
{{BODY}}
    </article>

  </main>

  <style>
  .about-wrap { max-width: 860px; margin: 0 auto; padding: 24px 20px 64px; font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; color: var(--text-1); line-height: 1.75; }
  .about-header h1 { font-size: 24px; margin: 0 0 4px; color: var(--text-1); }
  .about-sub { color: var(--text-3); font-size: 13px; margin: 0 0 6px; }
  .about-sites { color: var(--text-3); font-size: 12px; margin: 0 0 12px; }
  .about-sites a { color: var(--primary, #3370ff); }
  .about-back { color: var(--primary, #3370ff); text-decoration: none; font-size: 14px; }
  .about-back:hover { text-decoration: underline; }
  .about-updated { color: var(--text-3); font-size: 13px; margin: 0 0 8px; }
  .about-intro { color: var(--text-2); font-size: 14px; }
  .about-guide section { margin: 18px 0; padding: 18px 20px; background: var(--bg-card, var(--bg-hover)); border-radius: 8px; border-left: 3px solid var(--primary, #3370ff); }
  .about-guide section h2 { font-size: 18px; margin: 0 0 12px; color: var(--text-1); padding-bottom: 6px; border-bottom: 1px solid var(--border, #e5e6eb); }
  .about-guide section h3 { font-size: 15px; margin: 16px 0 8px; color: var(--text-1); }
  .about-guide section h4 { font-size: 14px; margin: 14px 0 6px; color: var(--text-1); }
  .about-guide section p { margin: 8px 0; font-size: 14px; color: var(--text-2); }
  .about-guide section ul, .about-guide section ol { margin: 8px 0 8px 22px; padding: 0; }
  .about-guide section li { font-size: 14px; color: var(--text-2); margin: 4px 0; }
  .about-guide section a { color: var(--primary, #3370ff); }
  .about-guide section strong { color: var(--text-1); font-weight: 600; }
  .about-guide section code { background: var(--bg-hover, rgba(0,0,0,0.05)); color: var(--text-1); padding: 1px 5px; border-radius: 3px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 13px; }
  /* table */
  .about-guide table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; display: block; overflow-x: auto; }
  .about-guide th, .about-guide td { border: 1px solid var(--border, #e5e6eb); padding: 6px 8px; text-align: left; vertical-align: top; }
  .about-guide th { background: var(--bg-hover, rgba(0,0,0,0.04)); color: var(--text-1); font-weight: 600; white-space: nowrap; }
  .about-guide td { color: var(--text-2); }
  .about-guide td.num { text-align: right; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; white-space: nowrap; }
  /* warn blockquote */
  .about-guide blockquote { margin: 12px 0; padding: 10px 14px; background: var(--bg-hover, rgba(255,180,0,0.06)); border-left: 3px solid #f5a623; border-radius: 4px; color: var(--text-2); font-size: 14px; }
  .about-guide blockquote ul { margin: 6px 0 6px 20px; }
  .about-guide blockquote strong { color: var(--text-1); }
  /* toc */
  .about-toc ol { margin: 8px 0 8px 24px; }
  .about-toc li { margin: 4px 0; }
  .about-toc ul { margin-left: 18px; }
  .about-toc a { color: var(--primary, #3370ff); text-decoration: none; }
  .about-toc a:hover { text-decoration: underline; }
  /* dark/redgold theme adjustments for warn/table */
  [data-theme="dark"] .about-guide blockquote { background: rgba(245,166,35,0.12); }
  [data-theme="dark"] .about-guide th { background: rgba(255,255,255,0.06); }
  [data-theme="redgold"] .about-guide blockquote { background: rgba(245,166,35,0.14); }
  [data-theme="redgold"] .about-guide th { background: rgba(255,255,255,0.08); }
  @media (max-width: 768px) {
    .about-wrap { padding: 16px 12px 64px; }
    .about-guide section { padding: 14px 14px; }
    .about-guide section h2 { font-size: 16px; }
    .about-guide section h3 { font-size: 14px; }
    .about-guide table { font-size: 12px; }
    .about-guide th, .about-guide td { padding: 5px 6px; }
  }
  </style>

  <script>
  var _hmt = _hmt || [];
  (function() {
    var hm = document.createElement("script");
    hm.src = "https://hm.baidu.com/hm.js?e1d50bf3c782798dd0c0515a14b1a48c";
    var s = document.getElementsByTagName("script")[0];
    s.parentNode.insertBefore(hm, s);
  })();
  </script>
</body>
</html>
"""

TAIL_TEMPLATE = """"""


def main():
    with open(MD_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": _slugify}},
    )
    body = md.convert(text)
    toc = md.toc if hasattr(md, "toc") else ""

    # 过滤 toc 中的 H1 主标题(只保留 h2-h4)
    toc = _strip_h1_from_toc(toc)

    # 从正文移除 md 主 H1 标题(用页面 header 的 h1 替代)
    body = _remove_first_h1(body)

    # 把 toc 的 <div class="toc"> 包装替换为 <ol>
    toc = _wrap_toc(toc)

    html = HEAD_TEMPLATE.replace("{{TOC}}", toc).replace("{{BODY}}", body)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print("OK wrote %s (%d bytes)" % (OUT_PATH, len(html.encode("utf-8"))))


def _slugify(value, separator="-"):
    """toc slug 用中文原标题(带 # 前缀)作为锚点,保证锚点可读。"""
    return re.sub(r"[^\w一-鿿]+", separator, value.strip().lower()).strip(separator)


def _strip_h1_from_toc(toc_html):
    """把 toc 里 H1 主标题的外层 <li> 剥掉,保留其内部所有 h2-h4 子项。
    结构:md 只有一个 H1 且是整篇根节点,toc 为 <ul><li>主标题<ul>…全部h2…</ul></li></ul>。
    做法:去掉外层 li 开/闭标签,只留内部 ul(即 h2 起全部子项)。"""
    # 去掉开头的 <li>主标题链接</a> 前缀(主标题链接本身也丢弃)
    toc_html = re.sub(
        r"<li><a href=\"#[^\"]*\">信号实验室\(tdsignal\)理财专员使用指南</a>",
        "<li>",  # 保留 <li> 使内部 ul 合法(下面再统一处理)
        toc_html,
        count=1,
    )
    # 内部 <ul> 紧跟在 <li> 后,把它提到外层:<li><ul> -> <ul>
    toc_html = re.sub(r"<li>\s*<ul>", "<ul>", toc_html, count=1)
    # 去掉末尾外层 li 的收尾 </ul></li>(倒数第二层),使 <ul>...</ul> 直接闭合
    # toc 结尾形如 ...</ul>\n</li>\n</ul>\n</div>
    toc_html = re.sub(r"</ul>\s*</li>\s*</ul>\s*</div>", "</ul>\n</div>", toc_html, count=1)
    return toc_html


def _remove_first_h1(body):
    """移除正文开头的 <h1 ...>...</h1> 主标题块。"""
    pattern = re.compile(r"<h1[^>]*>.*?</h1>", re.S)
    return pattern.sub("", body, count=1)


def _wrap_toc(toc_html):
    """把 markdown toc 的 <div class="toc"><ul>…</ul></div> 转成可直接嵌入的 <ol>。</div>"""
    toc_html = toc_html.strip()
    # 取 <ul>...</ul> 主体
    m = re.search(r"<ul>(.*)</ul>", toc_html, re.S)
    if m:
        return "<ol>\n%s\n</ol>" % m.group(1)
    return toc_html


if __name__ == "__main__":
    main()
