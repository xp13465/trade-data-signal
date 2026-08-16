#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻 digest HTML 存量重清洗(2026-08-16 修 bug:金十 title/summary 源码泄漏)。

目的:历史一次性清洗 data/news_digest.json + data/news_digest/**/*.json 里
      title/summary 含 HTML 标签的脏数据(2026-08-16 之前金十未清洗入库的), 保持 schema/字段不变。
      同步重清洗 static-site/data/ 上线目录(与 data/ 一致, §22 三步同步先清本地再部署)。

输入依赖:
  - data/news_digest.json + data/news_digest/<date>.json(年目录 + 扁平旧档)
  - static-site/data/news_digest.json + static-site/data/news_digest/**/*.json
输出:
  - 同路径覆写(仅清洗 title/summary 字符串值, 结构/字段数组顺序不变)
复现命令:
  /Users/linhuichen/code/trade-data/.venv/bin/python scripts/rewash_news_digest_html.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_news import _clean_html

REPO = Path(__file__).resolve().parent.parent


def _has_html(v):
    # 检测:完整标签(<...>) 或 未闭合标签残尾(内容[:120] 截断所致, 如 "…<span class=\"secti")
    return isinstance(v, str) and (re.search(r"<[^>]+>", v) or re.search(r"<\s*/?\s*[a-zA-Z][^>]*$", v))


def _rewash_one(path: Path, fixed: list) -> bool:
    """清洗单文件 title/summary;返回是否发生改动。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  ⚠ 读失败 {path}: {e}")
        return False
    try:
        d = json.loads(raw)
    except Exception as e:
        print(f"  ⚠ 解析失败(跳过) {path}: {e}")
        return False
    changed = False
    for n in (d.get("news") or []):
        for k in ("title", "summary"):
            cleaned = _clean_html(n.get(k) or "")
            if cleaned != n.get(k):
                n[k] = cleaned
                changed = True
                fixed.append((str(path), k))
    for n in (d.get("upcoming") or []):
        cleaned = _clean_html(n.get("title") or "")
        if cleaned != n.get("title"):
            n["title"] = cleaned
            changed = True
            fixed.append((str(path), "upcoming.title"))
    if changed:
        path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    return changed


def main():
    fixed = []
    targets = [REPO / "data" / "news_digest.json",
               REPO / "static-site" / "data" / "news_digest.json"]
    arch_dirs = [
        REPO / "data" / "news_digest",
        REPO / "static-site" / "data" / "news_digest",
    ]
    for arch in arch_dirs:
        if not arch.is_dir():
            continue
        for pf in sorted(arch.rglob("*.json")):
            if pf.name == "_index.json":
                continue
            targets.append(pf)
    n_cleaned_file = 0
    for t in targets:
        if t.exists():
            if _rewash_one(t, fixed):
                n_cleaned_file += 1
    print(f"[rewash] 清洗了 {n_cleaned_file} 个文件, 修正 {len(fixed)} 处字段:")
    for f, k in fixed:
        print(f"  {f} :: {k}")
    # 复扫确认无残留
    leftover = 0
    for t in targets:
        if not t.exists():
            continue
        try:
            d = json.loads(t.read_text(encoding="utf-8"))
        except Exception:
            continue
        for n in (d.get("news") or []):
            if _has_html(n.get("title")) or _has_html(n.get("summary")):
                leftover += 1
        for n in (d.get("upcoming") or []):
            if _has_html(n.get("title")):
                leftover += 1
    print(f"[rewash] 复扫残留 HTML 字段: {leftover}(应为 0)")


if __name__ == "__main__":
    main()
