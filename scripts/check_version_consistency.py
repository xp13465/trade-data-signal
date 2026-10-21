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
  校验3 - min 内容 == git HEAD 源重建内容 (B2, 2026-08-18 升级, 防"工作区源脏+min旧版"内容覆盖):
          每个 build_min 映射, 从 git HEAD 源重新生成 min(build_min.build_pairs_in_memory 复用 B1 同一套
          生成逻辑), 与当前 min 文件内容 md5 比对, 不一致即 FAIL。
          根治 16:30 事故: 原校验3只比 mtime(min ≥ 源), 拦不住「工作区源被 reset --soft 停旧版、min 是旧版」
          的内容覆盖(mtime 上 min 仍 ≥ 工作区旧源)。升级后 min 必须 == git HEAD 源重建结果, 脏工作区
          旧源生成的旧 min 过不了。源缺失/生成失败视为跳过(与 build_min.py 缺源跳过语义一致, 不 FAIL)。
          **2026-10-22 TOCTOU 加固(B1)**: 校验窗口自洽 —— 开头只取一次 `git rev-parse HEAD` 并固定该 sha,
          重建读源全部用 `git show <sha>:<path>`; 重建**前**快照 8 个 min 文件 md5(重建后不再读磁盘);
          重建+比对后再取一次 HEAD: 变了(典型 = main-merge 第 10 步 ssh 云上 `git pull` 落在窗口内)
          就重新固定 sha **只重试一次**, 再变才 FAIL 且消息写明「校验期间 HEAD 变化」,不再输出误导性的
          「min 过期/工作区源脏」。正常路径(同一 HEAD、干净工作区、min 正确)判定语义不变。

用法:
  python3 scripts/check_version_consistency.py --site-dir /path/to/static-site [--deploy-mode]
  python3 scripts/check_version_consistency.py --site-dir /path/to/static-site   # 普通跑(FYI 模式)
  python3 scripts/check_version_consistency.py --site-dir /path/to/static-site --checks 1,2
  --deploy-mode   deploy 接入(任一 FAIL 以非0退出阻断上线, 同 §24⑤ FAIL 阻断语义)
  --checks        只跑指定校验(逗号分隔, 取值 1/2/3; 默认 1,2,3)。
                 用途(#261 选项①, CI 拆步): CI 把「校验1/2」(纯静态硬项, 真阻断)与
                 「校验3」(需 build_min 依赖 npx terser/rcssmin, 尽力而为)拆成两步分别传
                 `--checks 1,2` 与 `--checks 3`, 使注释自称「纯静态必跑」名副其实。
                 deploy.sh 不传本参数 ⇒ 默认全跑, 行为不变。

退出码:
  0 = 所选校验全部 PASS
  1 = 有 FAIL(所选任一校验 FAIL → 阻断上线); 或 --checks 取值非法

deploy.sh 接入(step 1.2 宇宙校验之后, 见部署 §24⑤):
  "$PY" "$REPO/scripts/check_version_consistency.py" --site-dir "$GIT_REPO/static-site" --deploy-mode
  rc=$?; [ $rc -ne 0 ] && exit $rc
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
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


def _git_repo_of(site_dir: Path):
    """解析 site_dir 所在 git 仓库根。优先环境变量 GIT_REPO，否则 git -C site_dir rev-parse。"""
    env = os.environ.get("GIT_REPO")
    if env and os.path.isdir(os.path.join(env, ".git")):
        return env
    try:
        r = subprocess.run(
            ["git", "-C", str(site_dir), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            top = r.stdout.strip()
            if top and os.path.isdir(os.path.join(top, ".git")):
                return top
    except Exception:
        pass
    return None


def _md5hex(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def _git_head_sha(repo) -> str | None:
    """读一次 git HEAD 的 sha(整个校验窗口的唯一基准;取不到返回 None)。

    2026-10-22 TOCTOU 加固: 原实现每次读源都 `git show HEAD:<path>`、最后才读磁盘 min, 重建那几十秒
    期间若 main-merge.sh 第 10 步 ssh 云上 `git pull`(Fast-forward)落地, 就会「源按旧 HEAD 读、min
    按新 HEAD 比」错位 ⇒ 误报 min 过期(deploy_20261022_0042.log:729-733)。
    """
    if not repo:
        return None
    try:
        r = subprocess.run(
            ["git", "-C", repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


def _snapshot_min_md5(site_dir: Path) -> dict:
    """重建**前**快照全部 min 文件的 md5(缺失记 None)。

    先快照再见比对 ⇒ 重建耗时窗口内磁盘 min 被并发 pull 改写, 也不会混进本次比对。
    """
    snap = {}
    for _src, dst in MIN_PAIRS:
        dp = site_dir / dst
        snap[dst] = _md5hex(dp.read_bytes()) if dp.exists() else None
    return snap


def _rebuild_from_head(site_dir: Path, repo, head):
    """按**固定 sha** 重建全部 min(生产恒走 build_min 同一套生成逻辑, 单独成函数便于单测注入)。"""
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import build_min
    return build_min.build_pairs_in_memory(base=site_dir, repo=repo, head=head)


def _check3_once(site_dir: Path, repo, head):
    """单次比对(窗口自洽): 快照 min → 按固定 head 重建 → 比快照。

    返回 (problems, n_checked, n_skipped, snap)。
    """
    snap = _snapshot_min_md5(site_dir)
    rebuilt = _rebuild_from_head(site_dir, repo, head)
    problems = []
    n_checked = 0
    n_skipped = 0
    for src, dst in MIN_PAIRS:
        sp = site_dir / src
        if not sp.exists():
            n_skipped += 1            # 源缺失: 与 build_min.py 缺源跳过语义一致, 不 FAIL
            continue
        cur_md5 = snap.get(dst)
        if cur_md5 is None:
            problems.append(f"缺 min 版(源在 min 无): {dst}  <-  {src}")
            continue
        rebuilt_key = "static-site/" + dst
        if rebuilt_key not in rebuilt:
            # git 该提交源重建失败/被 skip(如新源未 commit) → 保守不 FAIL(避免误伤首次未 commit)
            n_skipped += 1
            continue
        n_checked += 1
        head_md5 = _md5hex(rebuilt[rebuilt_key])
        if cur_md5 != head_md5:
            problems.append(
                f"min 内容与 git HEAD 源重建不一致(工作区源脏或 min 过期): {dst}"
                f"(当前 {cur_md5[:8]} ≠ HEAD重建 {head_md5[:8]})"
            )
    return problems, n_checked, n_skipped, snap


def check3(site_dir: Path) -> tuple[bool, str]:
    """校验3(B2+TOCTOU 加固): min 内容 == 从 git HEAD 源重建的 min 内容。

    复用 build_min.build_pairs_in_memory(同一套 terser keep_fnames / rcssmin 生成逻辑, 杜绝两处算法分叉)。
    校验窗口自洽(2026-10-22): 固定一次 HEAD sha + 重建前快照 min + 结束后复验 HEAD; HEAD 变了只重试
    一次, 仍变则 FAIL 并写明「校验期间 HEAD 变化」(不再报误导性的 min 过期)。
    """
    repo = _git_repo_of(site_dir)
    head0 = _git_head_sha(repo)
    problems, n_checked, n_skipped, snap = _check3_once(site_dir, repo, head0)
    head1 = _git_head_sha(repo)
    retried = False
    head = head0
    if head0 and head1 and head0 != head1:
        # 校验窗口内 HEAD 移动(典型: main-merge 第 10 步 ssh 云上 git pull 落在窗口内)⇒ 重新固定 sha 重试一次
        retried = True
        head = head1
        problems, n_checked, n_skipped, snap = _check3_once(site_dir, repo, head)
        head2 = _git_head_sha(repo)
        if head2 and head2 != head:
            det = (f"校验期间 HEAD 变化(疑似并发 git pull), 已重试 1 次仍不稳定: "
                   f"head {head0[:12]} → {head[:12]} → {(head2 or '?')[:12]};"
                   f"本次比对结果不可信, 故不做内容判定(避免误导);请等并发 git pull 结束后重跑")
            return (False, det)

    trace = (f"head={(head or 'n/a')[:12]} min_snapshot=["
             + " ".join(f"{dst}={(m or 'missing')[:8]}" for dst, m in snap.items()) + "]")
    if problems:
        det = f"共 {n_checked} 对映射, {len(problems)} 处 min 与 git HEAD 源不一致:\n    " + "\n    ".join(problems)
    else:
        det = (f"build_min 映射 {n_checked} 对 min 内容均 == git HEAD 源重建({n_skipped} 对源缺失/重建跳过)")
    if retried:
        det += f"\n    注: 校验期间 HEAD 变化, 已重新固定 sha 重试 1 次"
    det += f"\n    {trace}"
    return (not problems, det)


def main() -> int:
    ap = argparse.ArgumentParser(description="部署版本一致性校验(§24⑤, #48, 适配 #46 日期+批次版本串)")
    ap.add_argument("--site-dir", required=True, help="static-site 目录路径(如 /Users/linhuichen/code/trade/static-site)")
    ap.add_argument("--deploy-mode", action="store_true", help="deploy 接入模式(任一 FAIL 以非0退出阻断上线)")
    ap.add_argument("--checks", default="1,2,3",
                    help="只跑指定校验(逗号分隔, 取值 1/2/3; 默认 1,2,3)。CI 拆步用 1,2 / 3")
    args = ap.parse_args()

    sel = {c.strip() for c in args.checks.split(",") if c.strip()}
    if not sel or not sel <= {"1", "2", "3"}:
        print(f"✗ --checks 取值非法: {args.checks!r}(只允许 1/2/3 的逗号分隔子集)", file=sys.stderr)
        return 1

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
        ("1", "校验1:index版本串格式/批次与sw一致", check1, (index_refs, site_dir)),
        ("2", "校验2:index引用资源文件存在", check2, (index_refs, site_dir)),
        ("3", "校验3:min内容==git HEAD源重建(B2防脏工作区覆盖)", check3, (site_dir,)),
    ]
    checks = [c for c in checks if c[0] in sel]
    print(f"  本次校验子集 : --checks {args.checks}({'/'.join(c[0] for c in checks)})")
    print()

    for _n, title, fn, tup in checks:
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
    print(f"✓ 版本一致性校验通过(所选子集 {args.checks}, §24⑤ PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
