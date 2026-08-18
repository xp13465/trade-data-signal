#!/usr/bin/env python3
"""check_version_progress.py - 版本串倒退哨兵 + merge 净回退校验(防再犯机制 A/B)

事故背景(2026-08-18 冲突覆盖根因报告 docs/conflict-overwrite-rootcause-2026-08-18.md):
  bf8841966(四档收窄, 版本串 a350)被 e3fa985c3(首页要闻, 基于旧 base, 版本串回退 a349)静默覆盖:
  merge 无冲突静默吃掉 bf 的 app.js 改动, 线上色带 1/2→1/4 消失, 直到用户发现显性 bug 才暴露。
  **最早可见信号 = 版本串 a350→a349 倒退**, 但此前没有任何环节校验版本串单调前进。

本脚本做两层校验(防再犯机制 A/B, 2026-08-18 实施):
  A. 版本串倒退哨兵(最重要, 成本最低):
     解析当前 static-site/index.html 的 ?v=<YYYYMMDD>-a<N>(app.min.js/lab.min.js/common.js
     等), 与「first-parent 链上的最近版本串天花板」比较(按 (date, batch) 元组):
       - 取 first-parent + 沿 first-parent 链回看最近 N 个 commit 的最大版本串 = 天花板
       - 当前 < 天花板 = 倒退 → FAIL(阻断上线, 直接抓本次事故类型)
         ※ 不只比 immediate 父: 本次事故 a350→a349 在 merge 提交 efa92ffd8 处
           immediate 父 a084cd74a 已是 a348(倒退), 直接比父(a349>a348)抓不到,
           须比"最近祖先天花板"(含 bf 的 a350)才能抓到 a349<a350。
       - 关键源文件(app.js/lab.js/common.js/style.css)相对 first-parent 有 diff
         但版本串未前进(同值) → 告警(提示"改源码未 bump")
     → 逻辑: "版本串必须 ≥ 最近祖先天花板; 且当源码文件有 diff 时版本串必须 > 父"
     版本串可能因文件本身没变而合法不变(如纯数据改动), 不误报。

  B. merge 净回退校验(与 A 同一脚本加强):
     检测"当前内容相对 first-parent 是否删回了最近新增的关键内容"(抓 e3fa985c3 这类
     把最近改动删回去的静默回退)。
     实现(方案1): 对关键文件(app.js/lab.js/common.js), 若版本串 ≤ 父 且文件内容 ≠ 父内容,
     把当前内容 md5 与父之前的历史 commit(回看窗口)逐一比对, 若与某个更旧 commit 的内容
     相同 = 净回退(回到旧状态) → FAIL。

用法:
  python3 scripts/check_version_progress.py --site-dir /path/to/static-site --repo /path/to/trade [--deploy-mode]
  --deploy-mode  FAIL 以非0退出阻断上线; 告警仍 exit 0(仅提示, 同 check_data_integrity warn 语义)

退出码:
  0 = PASS(或仅告警)
  1 = FAIL(版本倒退 / 净回退 → 阻断上线)

deploy.sh 接入(push main 之前的 安全网 阶段):
  "$PY" "$REPO/scripts/check_version_progress.py" --site-dir "$GIT_REPO/static-site" --repo "$GIT_REPO" --deploy-mode
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

# index.html 里带 ?v= 的引用: 捕获相对路径 ./<asset> 与版本串 <v>
VERSION_REF_RE = re.compile(r"(\./[^\s\"'<>]+?)\?v=\s*([A-Za-z0-9-]+)")
# 新版本串格式: <YYYYMMDD>-a<N>
VERSION_PATTERN = re.compile(r"^(\d{8})-a(\d+)$")

# 关键源文件(相对 --site-dir): 版本串必须随这些文件的 diff 前进
KEY_SOURCES = ["app.js", "lab.js", "common.js", "style.css"]
# B 净回退校验覆盖的关键文件(相对 --site-dir), 取源文件(内容可读、在历史里可比对)
B_FILES = ["app.js", "lab.js", "common.js", "style.css"]
# B 回看历史 commit 窗口大小(遍历父之前最多 N 个 commit 比对内容)
B_HISTORY_WINDOW = 40
# A 天花板回看: 沿 first-parent 链回看最近 N 个 commit 取最大版本串为天花板
# (抓"merge 提交 immediate 父已倒退、但更早祖先有更高版本"的延迟回归场景)
CEILING_WINDOW = 40


def _run_git(repo: str, *args: str) -> str | None:
    """跑 git 命令, 失败返回 None(不抛异常)。"""
    try:
        r = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def _git_file_at(repo: str, commit: str, path: str) -> bytes | None:
    """取某 commit 的文件内容(bytes); 文件不存在/出错返回 None。"""
    try:
        r = subprocess.run(
            ["git", "-C", repo, "show", f"{commit}:{path}"],
            capture_output=True, timeout=60,
        )
        if r.returncode != 0:
            return None
        return r.stdout
    except Exception:
        return None


def _md5hex(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def load_versions(site_dir: Path) -> dict[str, str]:
    """从 index.html 解析 {asset: version}, 仅返回匹配 <YYYYMMDD>-a<N> 的引用。"""
    index = site_dir / "index.html"
    if not index.exists():
        print(f"✗ 缺少 index.html: {index}", file=sys.stderr)
        return {}
    text = index.read_text(encoding="utf-8")
    out = {}
    for m in VERSION_REF_RE.finditer(text):
        asset, ver = m.group(1), m.group(2)
        if VERSION_PATTERN.match(ver):
            out[asset] = ver
    return out


def parse_version(ver: str) -> tuple[int, int] | None:
    """把 <YYYYMMDD>-a<N> 解析为 (date_int, batch_int) 用于比较; 格式不符返回 None。"""
    m = VERSION_PATTERN.match(ver)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def version_key(repo: str, site_rel: str, commit: str) -> tuple[int, int] | None:
    """取某 commit 的 index.html 里指定 asset(相对路径如 ./app.min.js) 的版本串 key。"""
    idx = _git_file_at(repo, commit, "static-site/index.html")
    if idx is None:
        return None
    text = idx.decode("utf-8", errors="replace")
    for m in VERSION_REF_RE.finditer(text):
        asset, ver = m.group(1), m.group(2)
        if asset == site_rel:
            return parse_version(ver)
    return None


def _changed_sources(site_dir: Path, repo: str, parent: str) -> list[str]:
    """返回相对 first-parent 有 diff 的关键源文件列表(相对 --site-dir 路径)。"""
    changed = []
    for src in KEY_SOURCES:
        cur = site_dir / src
        if not cur.exists():
            continue
        cur_md5 = _md5hex(cur.read_bytes())
        parent_blob = _git_file_at(repo, parent, f"static-site/{src}")
        if parent_blob is None or _md5hex(parent_blob) != cur_md5:
            changed.append(src)
    return changed


def _first_parent_chain(repo: str, parent: str, window: int) -> list[str]:
    """返回 first-parent 链上最近 window 个 commit(含 parent, 按时间从近到远)。"""
    out = _run_git(repo, "rev-list", "--first-parent", "-n", str(window), parent)
    if not out:
        return []
    return [c.strip() for c in out.split() if c.strip()]


def check_a(
    repo: str, site_dir: Path, parent: str, versions: dict[str, str]
) -> tuple[bool, list[str], list[str]]:
    """任务 A: 版本串倒退哨兵。

    返回 (fail, problems, warnings):
      - fail: 版本串倒退(当前 < 最近祖先天花板) → 阻断
      - problems: FAIL 明细
      - warnings: 告警(源码有 diff 但版本串未前进), 不阻断

    天花板 = max(first-parent 链最近 window 个 commit 的版本串)。
    用天花板而非仅 immediate 父: 抓"immediate 父已倒退、更早祖先有更高版本"的延迟回归
    (本次事故 a084cd74a/efa92ffd8 即此类: 直接比父抓不到, 比含 bf 的天花板 a350 才抓到)。
    """
    problems, warnings = [], []

    chain = _first_parent_chain(repo, parent, CEILING_WINDOW)
    if not chain:
        # first-parent 链历史不可得(rev-list 失败)→ 天花板无法计算, 宁拦不放(§23.11)
        problems.append(
            f"无法获取 first-parent 链历史(rev-list 失败)。版本串倒退哨兵无法计算天花板,"
            f"阻断上线而非静默放行(§23.11)"
        )

    for src in KEY_SOURCES:
        min_asset = f"./{os.path.splitext(src)[0]}.min.js"
        if src == "style.css":
            min_asset = "./style.min.css"
        cur_ver = versions.get(min_asset)
        if cur_ver is None:
            continue
        cur_key = parse_version(cur_ver)
        if cur_key is None:
            continue

        # 计算最近祖先版本串天花板
        ceiling_key = None
        ceiling_commit = None
        for c in chain:
            k = version_key(repo, min_asset, c)
            if k is None:
                continue
            if ceiling_key is None or k > ceiling_key:
                ceiling_key, ceiling_commit = k, c
        if ceiling_key is None:
            # 最近祖先无对应版本串(旧 commit 无 min 引用?) → 无法比较, 跳过
            continue

        if cur_key < ceiling_key:
            problems.append(
                f"{min_asset} 版本串倒退: 当前 {cur_ver} < 最近祖先天花板 "
                f"{ceiling_key[0]:08d}-a{ceiling_key[1]}(@ {ceiling_commit[:8]})"
                f"(倒退 = 大概率基于旧 base 提交, 可能静默覆盖最近改动)"
            )

    # 源码有 diff 但版本串未前进(相对 immediate 父) → 告警
    changed = _changed_sources(site_dir, repo, parent)
    if changed:
        cur_batches = {parse_version(v)[1] for v in versions.values() if parse_version(v)}
        parent_batches = set()
        for asset, _v in versions.items():
            pk = version_key(repo, asset, parent)
            if pk:
                parent_batches.add(pk[1])
        if cur_batches and cur_batches <= parent_batches:
            warnings.append(
                f"关键源文件 {changed} 相对父有 diff, 但版本串未前进(改源码未 bump 版本串?)"
                f"当前批次 {sorted(cur_batches)} vs 父 {sorted(parent_batches)}"
            )

    return (bool(problems), problems, warnings)


def check_b(
    repo: str, site_dir: Path, parent: str, versions: dict[str, str]
) -> tuple[bool, list[str]]:
    """任务 B: merge 净回退校验。

    对关键文件(app.js/lab.js/common.js/style.css):
      若版本串 ≤ 父 且 当前内容 ≠ 父内容, 把当前内容 md5 与父之前的历史 commit 逐一比对,
      若与某个更旧 commit 内容相同 = 净回退(把最近改动删回去了) → FAIL。
    """
    problems = []

    # 当前 index 相对父版本串是否未前进(≤ 父)
    cur_advance = True
    for src in KEY_SOURCES:
        min_asset = f"./{os.path.splitext(src)[0]}.min.js"
        if src == "style.css":
            min_asset = "./style.min.css"
        cur_ver = versions.get(min_asset)
        if cur_ver is None:
            continue
        cur_key = parse_version(cur_ver)
        parent_key = version_key(repo, min_asset, parent)
        if cur_key is None or parent_key is None:
            continue
        if cur_key <= parent_key:
            cur_advance = False
            break

    # 若版本串已前进(> 父), 说明是向前推进, 净回退可能性低 → 跳过 B
    # (B 主要抓"版本串未前进 + 内容被改回旧态"的组合)
    if cur_advance:
        return (False, [])

    for src in B_FILES:
        cur_file = site_dir / src
        if not cur_file.exists():
            continue
        cur_md5 = _md5hex(cur_file.read_bytes())
        parent_blob = _git_file_at(repo, parent, f"static-site/{src}")
        if parent_blob is None:
            continue
        if _md5hex(parent_blob) == cur_md5:
            continue  # 内容与父一致, 无回退
        # 版本串未前进且内容 ≠ 父: 回看历史, 找当前内容是否匹配某个更旧 commit(净回退)
        hist = _run_git(
            repo,
            "rev-list",
            f"{parent}~1",
            "-n", str(B_HISTORY_WINDOW),
            "--",
            f"static-site/{src}",
        )
        if not hist:
            # 版本串未前进且内容 ≠ 父, 但历史不可得(rev-list 失败)→ 净回退无法判定,
            # 宁拦不放(§23.11 绝不静默), 不静默跳过
            problems.append(
                f"{src} 净回退无法判定: 版本串未前进(≤ 父)且内容 ≠ 父, 但 rev-list 历史不可得,"
                f"阻断上线而非静默放行(§23.11)"
            )
            break
        for c in hist.split():
            c = c.strip()
            if not c:
                continue
            blob = _git_file_at(repo, c, f"static-site/{src}")
            if blob is not None and _md5hex(blob) == cur_md5:
                problems.append(
                    f"{src} 净回退: 版本串未前进(≤ 父)且当前内容与历史旧 commit {c[:8]} 相同"
                    f"(把最近改动删回旧状态, 可能静默覆盖最近功能)"
                )
                break

    return (bool(problems), problems)


def main() -> int:
    ap = argparse.ArgumentParser(description="版本串倒退哨兵 + merge 净回退校验(防再犯机制 A/B)")
    ap.add_argument("--site-dir", required=True, help="static-site 目录路径")
    ap.add_argument("--repo", required=True, help="trade git 仓库根路径(用于取 first-parent 历史)")
    ap.add_argument("--deploy-mode", action="store_true", help="deploy 接入模式(FAIL 以非0退出阻断)")
    args = ap.parse_args()

    site_dir = Path(args.site_dir).resolve()
    repo = args.repo
    if not site_dir.exists() or not site_dir.is_dir():
        print(f"✗ --site-dir 不存在或非目录: {site_dir}", file=sys.stderr)
        return 1

    print(f"=== check_version_progress.py(防再犯机制 A/B: 版本串倒退哨兵 + merge 净回退校验) ===")
    print(f"  site-dir : {site_dir}")
    print(f"  repo     : {repo}")

    # 当前 HEAD 与 first-parent
    head = _run_git(repo, "rev-parse", "HEAD")
    parent = _run_git(repo, "rev-parse", "HEAD^")
    if not head:
        # 非 git 仓库 / 无任何提交 → 校验不可执行, 宁拦不放(§23.11 发现问题绝不静默)
        print("✗ 无法解析 HEAD(非 git 仓库或无任何提交)。校验不可执行, 阻断上线而非静默放行(§23.11)", file=sys.stderr)
        return 1
    head = head.strip()
    if not parent:
        # 仅「首提交」(HEAD 存在、无父) 才合法 PASS(无历史可比对, 天然无倒退)
        print("✓ 首提交(HEAD^ 无父), 版本串倒退/净回退校验 PASS", file=sys.stderr)
        return 0
    parent = parent.strip()
    print(f"  HEAD     : {head[:10]}")
    print(f"  first-parent: {parent[:10]}")
    print()

    versions = load_versions(site_dir)
    if not versions:
        print("✗ index.html 未解析到任何 <YYYYMMDD>-a<N> 版本串引用", file=sys.stderr)
        return 1

    ok = True
    results = []

    # 任务 A
    a_fail, a_problems, a_warns = check_a(repo, site_dir, parent, versions)
    for w in a_warns:
        print(f"[告警] {w}")
    if a_fail:
        print("[FAIL] 任务 A: 版本串倒退哨兵")
        for p in a_problems:
            print(f"    {p}")
        ok = False
    else:
        print("[PASS] 任务 A: 版本串倒退哨兵(版本串 ≥ 父, 无倒退)" +
              (f"; {len(a_warns)} 条告警(源码 diff 未 bump)" if a_warns else ""))
    results.append(("A-版本串倒退哨兵", not a_fail))
    print()

    # 任务 B
    b_fail, b_problems = check_b(repo, site_dir, parent, versions)
    if b_fail:
        print("[FAIL] 任务 B: merge 净回退校验")
        for p in b_problems:
            print(f"    {p}")
        ok = False
    else:
        print("[PASS] 任务 B: merge 净回退校验(版本串前进或内容未回退到旧状态)")
    results.append(("B-merge净回退校验", not b_fail))
    print()

    if not ok:
        print("✗ 版本串倒退/净回退校验未通过(任一 FAIL 阻断上线, 防静默覆盖事故再犯, 2026-08-18 §23.11)")
        return 1
    print("✓ 版本串倒退/净回退校验通过(防再犯机制 A/B PASS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
