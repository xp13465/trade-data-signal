# -*- coding: utf-8 -*-
"""#327 P0 BUILD_ID 一致性·bump 4 处全覆盖回归测试（2026-10-31）。

背景: #327 首发提交手工把 build-id meta 写进 index.html, 漏了 databrief.html / trade_sim.html,
且 __build.json 写成陈旧值（a653 vs index a654）, 致 inline-init.js 比对不一致 → 循环 reload
白屏风险。bump_asset_version.py 已通过 glob 全量 *.html 覆盖（无 meta 自动插入）+ 写 __build.json,
本测试 LOCK 该行为: bump 后所有 HTML build-id meta == ver, __build.json == ver, 无遗漏。

覆盖（证据用例）:
  1 index/databrief/trade_sim 三页 bump 后 meta == ver（含 databrief/trade_sim 无 ASSETS 引用场景）
  2 无 meta 的 HTML bump 后自动插入 meta == ver
  3 陈旧 meta 的 HTML bump 后刷新为 ver
  4 write_build_json 写 __build.json == ver
  5 verify_build_id_coverage: 缺 meta / 陈旧 meta 均 FAIL 退出（防回归）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import bump_asset_version as bav

META_RE = bav.BUILD_ID_META_RE


def _meta_content(html: str) -> str:
    m = META_RE.search(html)
    if not m:
        return ""
    cm = re.search(r'content="([^"]*)"', m.group(0))
    return cm.group(1) if cm else ""


def _make_html(title: str, with_meta: bool = False, meta_val: str = "", with_asset: bool = False) -> str:
    meta_line = f'<meta name="build-id" content="{meta_val}">\n' if with_meta else ""
    asset_line = '<script src="./app.min.js"></script>\n' if with_asset else ""
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"{meta_line}{asset_line}"
        f"<title>{title}</title>\n</head>\n<body></body>\n</html>\n"
    )


@pytest.fixture()
def ss_dir(tmp_path: Path) -> Path:
    d = tmp_path / "static-site"
    d.mkdir()
    (d / "index.html").write_text(_make_html("index", with_meta=True, meta_val="20261029-a000", with_asset=True), encoding="utf-8")
    (d / "databrief.html").write_text(_make_html("databrief"), encoding="utf-8")  # 无 meta 无 asset
    (d / "trade_sim.html").write_text(_make_html("trade_sim", with_meta=True, meta_val="stale-old"), encoding="utf-8")
    (d / "sw.js").write_text("const CACHE_VERSION = 'v6-20261029-a000';\n", encoding="utf-8")
    return d


def test_bump_inserts_meta_into_all_html_and_syncs_build_json(ss_dir: Path):
    """用例 1-4: bump 后 4 处（index/databrief/trade_sim/__build.json）全部 == ver。"""
    ver = "20261031-a999"
    # 对每个 html 跑 bump（模拟 main() 的 glob 循环）
    for hp in sorted(ss_dir.glob("*.html")):
        bav.bump(str(hp), "", str(ss_dir), ver)
    bav.write_build_json(str(ss_dir), ver)

    for name in ("index.html", "databrief.html", "trade_sim.html"):
        content = (ss_dir / name).read_text(encoding="utf-8")
        assert _meta_content(content) == ver, f"{name} build-id != {ver}: {_meta_content(content)!r}"

    bj = json.loads((ss_dir / "__build.json").read_text(encoding="utf-8"))
    assert bj["build_id"] == ver


def test_verify_build_id_coverage_passes_when_all_match(ss_dir: Path):
    """用例 5-正面: 全部 == ver 时 verify PASS（不退出）。"""
    ver = "20261031-a999"
    for hp in sorted(ss_dir.glob("*.html")):
        bav.bump(str(hp), "", str(ss_dir), ver)
    bav.write_build_json(str(ss_dir), ver)
    bav.verify_build_id_coverage(str(ss_dir), ver)  # 不抛 = PASS


def test_verify_build_id_coverage_fails_when_meta_missing(ss_dir: Path):
    """用例 5-反面: 有 HTML 缺 meta 时 verify FAIL 退出。"""
    ver = "20261031-a999"
    # 只 bump index, databrief 无 meta 仍缺
    bav.bump(str(ss_dir / "index.html"), "", str(ss_dir), ver)
    bav.write_build_json(str(ss_dir), ver)
    with pytest.raises(SystemExit) as ei:
        bav.verify_build_id_coverage(str(ss_dir), ver)
    assert ei.value.code == 2


def test_verify_build_id_coverage_fails_when_meta_stale(ss_dir: Path):
    """用例 5-反面: 有 HTML meta 陈旧时 verify FAIL 退出。"""
    ver = "20261031-a999"
    # bump 全部后, 手动把 databrief meta 改回陈旧
    for hp in sorted(ss_dir.glob("*.html")):
        bav.bump(str(hp), "", str(ss_dir), ver)
    bav.write_build_json(str(ss_dir), ver)
    db = ss_dir / "databrief.html"
    txt = db.read_text(encoding="utf-8")
    txt = re.sub(r'content="[^"]*"(?=" name="build-id"| name="build-id")', 'content="stale"', txt, count=1)
    # 上面正则可能不匹配, 直接用 BUILD_ID_META_RE 替换
    txt = bav.BUILD_ID_META_RE.sub('<meta name="build-id" content="stale-old">', txt)
    db.write_text(txt, encoding="utf-8")
    with pytest.raises(SystemExit) as ei:
        bav.verify_build_id_coverage(str(ss_dir), ver)
    assert ei.value.code == 2
