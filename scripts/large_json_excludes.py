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
  防 git rm --cached 后 R2 备份断链——备份对象清单以区块为权威, 不是动态 tracked)
  ∪ 磁盘 data/ 下未跟踪且未被 ignore 的 >THRESHOLD 新文件(2026-09-26, feat/large-json-guard-sync:
  缺口 B 修复——新 >20MB 文件在 `git add -A` 前先被 ignore, 防被暂存后 .gitignore 移除不掉)。
  排除行用精确路径写法(/data/signal_kelly_trades.json 前导斜杠锚定仓库根), 不用宽通配防误伤。
- --print: 输出待上传清单(相对 data/ 的路径 + 完整字节数, tab 分隔), 供 upload_r2.py upload-large-json 消费。
- --check: 若 staticdata 里仍存在 >THRESHOLD 的 tracked 文件 → 非零退出 + 打印清单(机检用,
  由 scripts/check_large_json_excluded.py 包装挂 deploy 链)。
- --check-staged: 判定 staticdata 仓库「待提交变更」是否超阈值(单文件大 JSON 未迁移 / 积压),
  与 staticdata_backup_async.sh 原内联守卫逐项一致(消除双实现, 守卫唯一源下沉到本脚本)。
  rc: 0=干净, 1=超阈值, 2=内部错误(git 失败等); 只读不写任何文件, 可重复跑。
  供两个提交入口调用: staticdata_backup_async.sh(deploy 后) + staticdata_sync.sh(intraday 等)。

幂等性: 重复跑结果稳定; 区块外内容原样保留, 只重写区块内。

用法:
  python large_json_excludes.py --repo <staticdata仓库>            # 默认模式: 维护 .gitignore 区块
  python large_json_excludes.py --print --repo <staticdata仓库>    # 输出待上传清单
  python large_json_excludes.py --check --repo <staticdata仓库>    # 机检 tracked 大文件(非零=FAIL)
  python large_json_excludes.py --check-staged --repo <仓库>       # 判定待提交变更是否超阈值(rc 0/1/2)
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
# 积压(backlog)阈值单一源(2026-09-26, feat/large-json-guard-sync):
# 来源 = 原 scripts/staticdata_backup_async.sh 写死的积压阈值, 下沉到本脚本做唯一权威,
# staticdata_backup_async.sh / staticdata_sync.sh 的 --check-staged 判定共用, 不许再在 sh 里写死数字。
# 语义: 待提交变更 文件数 > BACKLOG_FILE_COUNT 或 变更总字节 > BACKLOG_BYTES_THRESHOLD
#       → 跳过 git commit/push 仅磁盘留档(防大 push 拖死备份自身 + git gc 膨胀)。
BACKLOG_FILE_COUNT = 5000
BACKLOG_BYTES_THRESHOLD = 500_000_000  # 变更文件当前 wc -c 总和(保守估计, 宁高勿低触发跳过)
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


def untracked_large_in_data(repo):
    """磁盘 data/ 下未跟踪且未被 ignore 的 >THRESHOLD 文件(相对仓库根)。

    用 `git ls-files --others --exclude-standard -- data/`: 未跟踪且未被 .gitignore 排除的候选。
    已被受管区块 ignore 的文件不会出现在这里(ignore 后 --exclude-standard 滤掉)——那一类
    靠 block_entries_exist(existing: 区块已有且磁盘仍在)保留; 两路合起来才覆盖全:
    - 本函数兜住「新出现的大文件」(迁移后新增 / 首跑时尚未进区块)
    - existing 兜住「已进区块、已 rm --cached 不在 tracked」的迁移文件
    """
    out = subprocess.run(
        ["git", "-C", repo, "ls-files", "--others", "--exclude-standard", "--", "data/"],
        capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"✗ git ls-files --others 失败: {out.stderr[:500]}")
    result = []
    for f in out.stdout.splitlines():
        f = f.strip()
        if not f or not f.startswith(DATA_PREFIX):
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
    untracked = untracked_large_in_data(repo)
    # 合并: tracked 大文件(新出现即纳入) ∪ 区块已有且磁盘仍在(迁移后 rm --cached 了它们不再
    # tracked, 但备份必须持续, 区块不缩水直到文件从磁盘消失) ∪ 磁盘未跟踪的新大文件
    # (缺口 B: 新 >20MB 文件未进区块时 `git add -A` 会暂存它, 而 .gitignore 移除不掉已暂存项;
    # 在 git add 前刷新区块让它先被 ignore, 防被提交)。
    desired = set(tracked) | set(existing) | set(untracked)
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


def check_staged_mode(repo):
    """--check-staged: 判定「待提交变更」是否超阈值(守卫唯一源, 供 async/sync 两提交入口共用)。

    与 staticdata_backup_async.sh 原内联守卫逐项一致(2026-09-26 消除双实现):
    - 清单 = `git diff --cached --name-only --diff-filter=d`:
      ⚠ 必须带 --diff-filter=d(小写 d=排除已暂存删除 D)。2026-09-26 P1 自锁修复: 不加会把
      `rm --cached` 后「磁盘文件仍在」的 D 按全文件字节算 → 永久误触发 → 拦死唯一能解除它自己的
      那次提交(见 docs/ops/large-json-guard-fix-review-20260926.md)。别改回去。
    - 超阈值条件: 文件数 > BACKLOG_FILE_COUNT 或 任一文件字节 > THRESHOLD 或 变更总字节 > BACKLOG_BYTES_THRESHOLD
    - 原因口径(与 async 原 _OVERSIZE_REASON 同序): 文件数超 → backlog; 单个大 JSON → largejson;
      总字节超 → backlog(largejson 优先)。
    - stdout 一行人类可读: 文件数=N 字节=B 超阈值=0|1 原因=<空|backlog|largejson>
    - rc: 0=干净, 1=超阈值, 2=内部错误(git 失败等)。
    - 只读, 不写任何文件, 可重复跑。
    """
    out = subprocess.run(
        ["git", "-C", repo, "diff", "--cached", "--name-only", "--diff-filter=d"],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(f"✗ git diff --cached 失败: {out.stderr[:500]}", file=sys.stderr)
        return 2
    changed = [l for l in out.stdout.splitlines() if l.strip()]
    n = len(changed)
    total_bytes = 0
    over = 0
    reason = ""
    # 文件数阈值短路(与 async 一致: 积压场景 32k 文件逐个 wc 白耗 ~30s, 文件数已定不再需要字节数)。
    if n > BACKLOG_FILE_COUNT:
        over = 1
        reason = "backlog"
    else:
        for f in changed:
            p = os.path.join(repo, f)
            try:
                sz = os.path.getsize(p) if os.path.isfile(p) else 0
            except OSError:
                sz = 0
            total_bytes += sz
            if sz > THRESHOLD:
                over = 1
                reason = "largejson"
        if total_bytes > BACKLOG_BYTES_THRESHOLD:
            over = 1
            if not reason:
                reason = "backlog"
    print(f"文件数={n} 字节={total_bytes} 超阈值={over} 原因={reason}")
    return over


def main():
    ap = argparse.ArgumentParser(description="large-json 排除规则单一源(staticdata 大 JSON 移出 git + R2 私有桶备份)")
    ap.add_argument("--repo", help="staticdata 仓库路径(缺省 env STATICDATA_REPO 或默认路径, 含云上回退)")
    ap.add_argument("--print", action="store_true", help="输出待上传清单(相对 data/ 路径 + 字节数)")
    ap.add_argument("--check", action="store_true", help="机检 tracked 大文件(有则 exit 1)")
    ap.add_argument("--check-staged", action="store_true",
                    help="判定待提交变更是否超阈值(rc: 0=干净 1=超阈值 2=内部错误, 供 async/sync 提交入口共用)")
    args = ap.parse_args()
    repo = staticdata_repo(args.repo)
    if args.print:
        print_mode(repo)
    elif args.check:
        check_mode(repo)
    elif args.check_staged:
        sys.exit(check_staged_mode(repo))
    else:
        default_mode(repo)


if __name__ == "__main__":
    main()