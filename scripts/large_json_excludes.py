#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""large_json_excludes.py - large-json 排除规则单一源(2026-09-25, feat/large-json-r2-core)

背景: staticdata 备份 git 仓库(trade-data-signal-staticdata)里 7 个大 JSON(>20MB, 共~320MB)
天天变、天天进 delta, .git 膨胀到 3.3G, 9-25 18:13 异步备份首跑撞「变更总字节 >300MB」积压
阈值跳过 commit。本脚本 = 排除规则唯一权威: 决定「哪些大 JSON 移出 staticdata git、走 R2 私有桶
signal-backup large-json/ 每日备份」。

本脚本三模式(冻结接口, 主控定):
- 默认模式(带 --repo 直接跑): 在 staticdata 仓库 .gitignore 里维护受管区块
  (# >>> large-json auto-generated >>> / # <<< large-json auto-generated <<<), 幂等。
  区块 = 当前 tracked 且 >THRESHOLD 的文件 ∪ 区块已有且磁盘仍存在的文件(迁移后仍保留,
  防 git rm --cached 后 R2 备份断链——备份对象清单以区块为权威, 不是动态 tracked)。
  排除行用精确路径写法(/data/signal_kelly_trades.json 前导斜杠锚定仓库根), 不用宽通配防误伤。
- --print: 输出待上传清单(相对 data/ 的路径 + 完整字节数, tab 分隔), 供 upload_r2.py upload-large-json 消费。
- --check: 若 staticdata 里仍存在 >THRESHOLD 的 tracked 文件 → 非零退出 + 打印清单(机检用,
  由 scripts/check_large_json_excluded.py 包装挂 deploy 链)。

幂等性: 重复跑结果稳定; 区块外内容原样保留, 只重写区块内。

用法:
  python large_json_excludes.py --repo <staticdata仓库>            # 默认模式: 维护 .gitignore 区块
  python large_json_excludes.py --print --repo <staticdata仓库>    # 输出待上传清单
  python large_json_excludes.py --check --repo <staticdata仓库>    # 机检 tracked 大文件(非零=FAIL)
  # --repo 缺省用 env STATICDATA_REPO, 再缺省用 /Users/linhuichen/code/trade-data-signal-staticdata,
  # 末尾带云上单仓回退(与 staticdata_backup_async.sh L50-52 同款)。

测试(严禁写生产 staticdata 仓库): STATICDATA_REPO=/tmp/xxx(git clone 克隆)或 --repo 指向克隆。
"""
import os
import sys
import tempfile
import argparse
import subprocess

THRESHOLD = 20_000_000  # 冻结接口: 20MB(完整文件大小, 非 diff 大小)
DATA_PREFIX = "data/"  # 排除对象限定 data/ 下(冻结接口)

BLOCK_BEGIN = "# >>> large-json auto-generated >>>"
BLOCK_END = "# <<< large-json auto-generated <<<"

_DEFAULT_STATICDATA = "/Users/linhuichen/code/trade-data-signal-staticdata"


def staticdata_repo(repo_arg):
    """解析 staticdata 仓库路径: --repo > env STATICDATA_REPO > 默认; 缺失时云上单仓回退。"""
    repo = repo_arg or os.environ.get("STATICDATA_REPO", _DEFAULT_STATICDATA)
    if not os.path.isdir(os.path.join(repo, ".git")):
        # 云上单仓: 本机硬编码路径不存在时回退 GIT_REPO 派生的 sibling 路径(同 staticdata_backup_async.sh)
        git_repo = os.environ.get("GIT_REPO", "")
        if git_repo and os.path.isdir(f"{git_repo}-staticdata/.git"):
            repo = f"{git_repo}-staticdata"
    if not os.path.isdir(os.path.join(repo, ".git")):
        sys.exit(f"✗ staticdata 仓库不存在(.git 缺失): {repo}(已尝试 env 回退)")
    return repo


def git_ls_files(repo):
    """staticdata 仓库 git ls-files(只读, 不改 index/不写 .git)。"""
    out = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"✗ git ls-files 失败: {out.stderr[:500]}")
    return [l for l in out.stdout.splitlines() if l.strip()]


def large_tracked(repo, files=None):
    """git ls-files 中 >THRESHOLD 且落在 data/ 下的文件(相对仓库根)。"""
    files = files if files is not None else git_ls_files(repo)
    result = []
    for f in files:
        if not f.startswith(DATA_PREFIX):
            continue
        p = os.path.join(repo, f)
        try:
            if os.path.isfile(p) and os.path.getsize(p) > THRESHOLD:
                result.append(f)
        except OSError:
            continue
    return result


def _parse_gitignore(text):
    """把 .gitignore 文本切成 (before, after, block_entries); 无区块时 before=全文 after="", entries=[]。"""
    lines = text.splitlines(keepends=True)
    begin = end = None
    for i, l in enumerate(lines):
        r = l.rstrip("\n")
        if r == BLOCK_BEGIN:
            begin = i
        if r == BLOCK_END:
            end = i
    if begin is not None and end is not None and end > begin:
        before = "".join(lines[:begin])
        after = "".join(lines[end + 1:])
        inner = "".join(lines[begin + 1:end])
        entries = [l.strip() for l in inner.splitlines() if l.strip()]
        return before, after, entries
    return "".join(lines), "", []


def block_entries_exist(repo):
    """区块内现有排除行(/data/... 形式)里, 磁盘仍存在的文件(相对仓库根)。"""
    gitignore_path = os.path.join(repo, ".gitignore")
    if not os.path.isfile(gitignore_path):
        return []
    with open(gitignore_path, encoding="utf-8") as fh:
        _, _, entries = _parse_gitignore(fh.read())
    existing = []
    for line in entries:
        line = line.strip()
        if line.startswith("#") or not line.startswith("/data/"):
            continue
        rel = line.lstrip("/")
        if os.path.isfile(os.path.join(repo, rel)):
            existing.append(rel)
    return existing


def _render_block(rel_paths):
    """生成受管区块文本(精确路径 /data/... , 前导斜杠锚定仓库根)。"""
    lines = [
        BLOCK_BEGIN,
        "# 由 scripts/large_json_excludes.py 自动维护(2026-09-25), 勿手改。",
        "# 排除 staticdata 备份 git 仓库 data/ 下 >20MB 的 JSON: 移出 git, 改走 R2 私有桶",
        "# signal-backup large-json/<YYYY-MM-DD>/<相对data路径>.gz 每日备份(日14天+周8周+月12月)。",
    ]
    for rel in sorted(rel_paths):
        lines.append("/" + rel)
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


def default_mode(repo):
    """维护 .gitignore 受管区块(幂等)。返回当前区块管理的排除路径(相对仓库根)清单。"""
    tracked = large_tracked(repo)
    existing = block_entries_exist(repo)
    # 合并: tracked 大文件(新出现即纳入) ∪ 区块已有且磁盘仍在(迁移后 rm --cached 了它们不再
    # tracked, 但备份必须持续, 区块不缩水直到文件从磁盘消失)。
    desired = set(tracked) | set(existing)
    gitignore_path = os.path.join(repo, ".gitignore")
    text = ""
    if os.path.isfile(gitignore_path):
        with open(gitignore_path, encoding="utf-8") as fh:
            text = fh.read()
    before, after, _ = _parse_gitignore(text)
    new_text = before.rstrip("\n") + "\n\n" + _render_block(desired) + "\n" + after.lstrip("\n")
    if new_text == text:
        print(f"✓ .gitignore 受管区块已最新({len(desired)} 个排除项, 无变化)", file=sys.stderr)
    else:
        # 原子写(tmp + os.replace, 防 systemd 超时强杀留半截, 2026-09-21 signal_kelly_trades 半截先例)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(gitignore_path) or ".",
                                   prefix=".gitignore.largejson.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            os.replace(tmp, gitignore_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        print(f"✓ 已更新 staticdata .gitignore 受管区块({len(desired)} 个排除项)", file=sys.stderr)
    return sorted(desired)


def print_mode(repo):
    """--print: 输出待上传清单(相对 data/ 的路径 + 完整字节数, tab 分隔), 供上传脚本消费。

    先跑 default_mode 确保区块最新(幂等), 再按区块输出——备份对象权威 = 区块(迁移后持续)。
    """
    rel_paths = default_mode(repo)
    for rel in rel_paths:
        relpath = rel
        if relpath.startswith(DATA_PREFIX):
            relpath = relpath[len(DATA_PREFIX):]
        p = os.path.join(repo, rel)
        try:
            print(f"{relpath}\t{os.path.getsize(p)}")
        except OSError as e:
            print(f"⚠ 读大小失败 {rel}: {e}", file=sys.stderr)


def check_mode(repo):
    """--check: 仍存在 >THRESHOLD 的 tracked 大文件 → 非零退出 + 打印清单(机检)。"""
    tracked = large_tracked(repo)
    if tracked:
        print(f"✗ 仍存在 {len(tracked)} 个 >{THRESHOLD / 1_000_000:.0f}MB 的 tracked 大文件"
              f"(需人工跑 scripts/migrate_large_json_out_of_git.sh):", file=sys.stderr)
        for f in sorted(tracked):
            print(f"  {os.path.getsize(os.path.join(repo, f))}  {f}", file=sys.stderr)
        sys.exit(1)
    print("✓ 无 >20MB tracked 大文件(staticdata git 干净)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="large-json 排除规则单一源(staticdata 大 JSON 移出 git + R2 私有桶备份)")
    ap.add_argument("--repo", help="staticdata 仓库路径(缺省 env STATICDATA_REPO 或默认路径, 含云上回退)")
    ap.add_argument("--print", action="store_true", help="输出待上传清单(相对 data/ 路径 + 字节数)")
    ap.add_argument("--check", action="store_true", help="机检 tracked 大文件(有则 exit 1)")
    args = ap.parse_args()
    repo = staticdata_repo(args.repo)
    if args.print:
        print_mode(repo)
    elif args.check:
        check_mode(repo)
    else:
        default_mode(repo)


if __name__ == "__main__":
    main()