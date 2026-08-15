#!/usr/bin/env python3
"""check_version_consistency.py - 部署版本一致性校验(§24⑤, #48, 适配 #46 日期+批次版本串机制)

背景(孤儿快照全站白屏事故, 2026-08-14): 版本串机制原为「内容md5哈希」(bump_asset_version.py 内容相同则
版本号相同), A+B 实施期集中改前端+备站数据不同步+中间"改源码漏bump"断链点 → CDN/浏览器缓存滞留
「孤儿旧快照」(引不存在对应内容产物的版本串) → SW 更新清缓存重建时裸崩全白。根因=「版本串机制 +
SW更新接管 + 数据同步」三处设计未闭环。

#46(2026-08-15)已把版本串机制从「内容md5」改为「日期+批次」:  `?v=<YYYYMMDD>-a<N>`(如
`?v=20260815-a238`), 与 sw.js CACHE_VERSION(`'v6-20260815-a238'`)同源。新机制下内容md5≠版本串
(版本串是批次号, 每次部署强制换新串, 内容相同也换), 故校验语义适配如下:

校验目标(防孤儿快照/版本串断链):
  校验1 - index 引用版本串格式正确 + 与 sw.js 批次一致:
          index 里所有 `?v=`(排除 favicon.ico / apple-touch-icon.png 两个遗留旧 md5
          `?v=1dbb579c` / `?v=9d27c273`)必须是 `<YYYYMMDD>-a<N>` 格式, 且所有 `a<N>` 数字一致;
          再读 sw.js `CACHE_VERSION = 'v<N>-<YYYYMMDD>-a<M>'` 的 M, 与 index 批次数字比对, 不等 → FAIL。
  校验2 - index 引用的所有资源文件存在:
          每个 `./<asset>?v=...` 引用, 确认 --site-dir/<asset> 文件实际存在(防版本串指向不存在的产物)。
  校验3 - min 版比源版新:
          每个 build_min 映射 .min.js 对应 .js 源 / .min.css 对应 .css 源, mtime 上 min ≥ 源
          (防 build 漏跑导致 min 过期上线)。源缺失视为跳过(与 build_min.py 缺源跳过语义一致, 不 FAIL)。

用法:
  python3 scripts/check_version_consistency.py --site-dir /path/to/static-site [--deploy-mode]
  python3 scripts/check_version_consistency.py --site-dir /path/to/static-site   # 普通跑(FYI 模式)
  --deploy-mode   deploy 接入(任一 FAIL 以非0退出阻断上线, 同 §24⑤ FAIL 阻断语义)

退出码:
  0 = 全部 PASS
  1 = 有 FAIL(任一校验 FAIL → 阻断上线)

deploy.sh 接入(step 1.2 宇宙校验之后, 见部署 §24⑤):
  "$PY" "$REPO/scripts/check_version_consistency.py" --site-dir "$GIT_REPO/static-site" --deploy-mode
  rc=$?; [ $rc -ne 0 ] && exit $rc
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

# 遗留旧 md5 版本串的文件(不做日期+批次格式校验, 直接跳过)
# 背景: 这俩是 favicon/apple-touch-icon 的静态图片指纹, 不在 bump_asset_version.py 批次机制内,
#       沿用内容md5 `?v=1dbb579c` / `?v=9d27c273`, 属设计遗留非断链, 故跳过格式/批次校验。
LEGACY_FILES = {"favicon.ico", "apple-touch-icon.png"}

# 与 scripts/build_min.py PAIRS 完全一致的映射(相对 --site-dir):  (源, min)
# 顺序: common 先于 app/lab(依赖), CSS 独立。source 缺失视为跳过(与 build_min 缺源跳过一致)。
MIN_PAIRS = [
    ("common.js", "common.min.js"),
    ("purpose-notes.js", "purpose-notes.min.js"),
    ("kelly-review-notes.js", "kelly-review-notes.min.js"),
    ("kelly-reports-content.js", "kelly-reports-content.min.js"),
    ("app.js", "app.min.js"),
    ("lab.js", "lab.min.js"),
    ("style.css", "style.min.css"),
    ("lab.css", "lab.min.css"),
]

# index.html 里带 ?v= 的引用: 捕获相对路径 ./<asset> 与版本串 <v>
VERSION_REF_RE = re.compile(r"(\./[^\s\"'<>]+?)\?v=\s*([A-Za-z0-9-]+)")
# 新版本串格式: <YYYYMMDD>-a<N>
VERSION_PATTERN = re.compile(r"^(\d{8})-a(\d+)$")
# sw.js CACHE_VERSION 声明: 'v<N>-<YYYYMMDD>-a<M>'
SW_CACHE_VERSION_RE = re.compile(r"CACHE_VERSION\s*=\s*'v\d+-(?P<date>\d{8})-a(?P<batch>\d+)'")


def load_index_meta(site_dir: Path):
    """读 index.html, 返回 [(asset, version)] 列表(全部 ?v= 引用)。"""
    index = site_dir / "index.html"
    if not index.exists():
        print(f"✗ 缺少 index.html: {index}", file=sys.stderr)
        return None
    text = index.read_text(encoding="utf-8")
    refs = []
    for m in VERSION_REF_RE.finditer(text):
        refs.append((m.group(1), m.group(2)))
    return refs


def check1(index_refs, site_dir: Path) -> tuple[bool, str]:
    """校验1: 非遗留引用版本串格式 + 批次一致 + 与 sw.js CACHE_VERSION 一致。"""
    problems = []
    batches = set()
    n_nonlegacy = 0
    seen = set()
    for asset, ver in index_refs:
        # 遗留 md5 文件跳过
        base = os.path.basename(asset)
        if base in LEGACY_FILES:
            continue
        n_nonlegacy += 1
        key = (asset, ver)
        if key in seen:          # 同文件多次引用(link+noscript)去重
            continue
        seen.add(key)
        m = VERSION_PATTERN.match(ver)
        if not m:
            problems.append(f"{asset} 版本串格式错误(期望 <YYYYMMDD>-a<N>): ?v={ver}")
            continue
        batches.add(int(m.group(2)))

    if not seen:
        problems.append("index.html 未引用任何非遗留 ?v= 资源(版本串断链?)")

    # 所有非遗留引用的批次数字必须一致
    if len(batches) > 1:
        problems.append(f"index 内存在多个不一致批次号 a{'-a'.join(str(b) for b in sorted(batches))}(应统一)")
    # 与 sw.js CACHE_VERSION 批次对比
    else:
        sw = site_dir / "sw.js"
        if not sw.exists():
            problems.append(f"缺少 sw.js: {sw}")
        else:
            sm = SW_CACHE_VERSION_RE.search(sw.read_text(encoding="utf-8"))
            if not sm:
                problems.append("sw.js 中未找到 CACHE_VERSION = 'v<N>-<YYYYMMDD>-a<M>'(版本串机制未落地?)")
            else:
                sw_batch = int(sm.group("batch"))
                index_batch = next(iter(batches), None)
                if index_batch is not None and sw_batch != index_batch:
                    problems.append(f"index 批次 a{index_batch} ≠ sw.js CACHE_VERSION 批次 a{sw_batch}(不同批→孤儿快照)")
                elif index_batch is None:
                    problems.append("index 无非遗留版本引用, 无法与 sw.js 批次比对")

    if problems:
        det = ";\n    ".join(problems)
        det = f"共 {n_nonlegacy} 个非遗留引用, 问题 {len(problems)} 处:\n    " + det
    else:
        det = (f"index 全部 {n_nonlegacy} 个非遗留引用均为 <YYYYMMDD>-a<batch> 统一格式, "
               f"批次 a{next(iter(batches), '?')} 与 sw.js CACHE_VERSION 批次一致")
    return (not problems, det)


def check2(index_refs, site_dir: Path) -> tuple[bool, str]:
    """校验2: index 引用的每个 ./<asset> 文件实际存在。"""
    missing = []
    checked = set()
    for asset, _ in index_refs:
        base = os.path.basename(asset)
        if base in LEGACY_FILES:
            continue
        if asset in checked:
            continue
        checked.add(asset)
        if not (site_dir / asset).exists():
            missing.append(asset)
    if missing:
        det = f"共 {len(checked)} 个引用, {len(missing)} 个资源文件缺失:\n    " + "\n    ".join(missing)
    else:
        det = f"index 引用的 {len(checked)} 个资源文件全部存在"
    return (not missing, det)


def check3(site_dir: Path) -> tuple[bool, str]:
    """校验3: 每个 build_min 映射的 min 版 mtime ≥ 源(防 build 漏跑 min 过期上线)。"""
    problems = []
    n_checked = 0
    n_skipped = 0
    for src, dst in MIN_PAIRS:
        sp = site_dir / src
        dp = site_dir / dst
        if not sp.exists():
            n_skipped += 1            # 源缺失: 与 build_min.py 缺源跳过语义一致, 不 FAIL
            continue
        if not dp.exists():
            problems.append(f"缺 min 版(源在 min 无): {dst}  <-  {src}")
            continue
        n_checked += 1
        src_mt = sp.stat().st_mtime
        dst_mt = dp.stat().st_mtime
        if dst_mt < src_mt:
            problems.append(
                f"min 版比源旧: {dst}({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(dst_mt))}) "
                f"< {src}({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(src_mt))})"
            )
    if problems:
        det = f"共 {n_checked} 对映射, {len(problems)} 处 min 过期:\n    " + "\n    ".join(problems)
    else:
        det = f"build_min 映射 {n_checked} 对全部 min≥源({n_skipped} 对源缺失跳过)"
    return (not problems, det)


def main() -> int:
    ap = argparse.ArgumentParser(description="部署版本一致性校验(§24⑤, #48, 适配 #46 日期+批次版本串)")
    ap.add_argument("--site-dir", required=True, help="static-site 目录路径(如 /Users/linhuichen/code/trade/static-site)")
    ap.add_argument("--deploy-mode", action="store_true", help="deploy 接入模式(任一 FAIL 以非0退出阻断上线)")
    args = ap.parse_args()

    site_dir = Path(args.site_dir).resolve()
    if not site_dir.exists() or not site_dir.is_dir():
        print(f"✗ --site-dir 不存在或非目录: {site_dir}", file=sys.stderr)
        return 1

    print(f"=== check_version_consistency.py(§24⑤ 部署版本一致性校验, 适配 #46 日期+批次版本串) ===")
    print(f"  site-dir : {site_dir}")

    index_refs = load_index_meta(site_dir)
    if index_refs is None:
        return 1

    nonlegacy = [r for r in index_refs if os.path.basename(r[0]) not in LEGACY_FILES]
    sw_batch = ""
    sw_file = site_dir / "sw.js"
    if sw_file.exists():
        sm = SW_CACHE_VERSION_RE.search(sw_file.read_text(encoding="utf-8"))
        sw_batch = f"a{sm.group('batch')}" if sm else "?"
    print(f"  index 引用 : {len(index_refs)} 处(非遗留 {len(nonlegacy)} 处), 遗留 {len(index_refs) - len(nonlegacy)} 处(favicon/apple-touch-icon)")
    print(f"  sw.js     : CACHE_VERSION 批次 {sw_batch}")
    print()

    ok = True
    results = []
    checks = [
        ("校验1:index版本串格式/批次与sw一致", check1, (index_refs, site_dir)),
        ("校验2:index引用资源文件存在", check2, (index_refs, site_dir)),
        ("校验3:min版比源版新(build_min映射)", check3, (site_dir,)),
    ]

    for title, fn, tup in checks:
        passed, detail = fn(*tup)
        status = "PASS" if passed else "FAIL"
        results.append((title, passed))
        print(f"[{status}] {title}")
        print(f"    {detail}")
        print()
        ok = ok and passed

    if not ok:
        print("✗ 版本一致性校验未通过(任一 FAIL 阻断上线, 防孤儿快照再产生, 2026-08-14 全站白屏事故根因⑤)")
        return 1
    print("✓ 版本一致性全部校验通过(§24⑤ PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
