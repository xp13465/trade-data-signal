#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""staticdata_write_guard.py - staticdata git 写权限守卫单一源(2026-09-26, feat/staticdata-write-guard)

背景: 本机(mac)的 staticdata commit/push 路径是"mac 还是生产机"时代遗留:
  - 全仓穷举确认只有 2 个 git 写入路径(staticdata_backup_async.sh + staticdata_sync.sh), 无第三个;
  - mac 数据默认旧(9-13 迁云后 mac 无自动任务, 7/7 抽查全 mac 旧云新);
  - 9-26 14:52 那笔 commit(1963 文件)未被推上去, 是因为恰好被 non-fast-forward 偶然拒绝
    ——"失败是偶然不是保护", 下次远端落后时再跑就能用 13 天旧数据全量覆盖共享生产 DR 仓库
    (trade-data-signal-staticdata)。
  详见 docs/ops/staticdata-mac-write-path-research-20260926.md。

本脚本 = staticdata git 写权限判定单一源(守卫唯一源), 与 large_json_excludes.py --check-staged
下沉风格一致: 两个 commit 入口共用, 不复制逻辑。

两模式(rc 契约与 --check-staged 同风格: 0=放行, 1=拒绝, 2=内部错误):
- --check-write-auth: 判定本机是否生产机(纯函数: 仓库路径前缀 /home/ubuntu/ = 生产机)。
  生产机 rc=0 → 调用方原样走原 commit/push 逻辑(云上行为零变化);
  非生产机 rc=1 → 调用方跳过 git commit/push 段(仅保留 rsync 磁盘 + R2 + 降级通知)。
  显式放行 = 环境变量 STATICDATA_ALLOW_PUSH=1(调用方据此改走 --check-fresh 数据闸门)。
  判定是纯函数(输入路径字符串 → 结果), 可用假路径直接单测"云上放行"分支, 无需真建 /home/ubuntu。
- --check-fresh: 数据闸门(非生产机 + 显式 STATICDATA_ALLOW_PUSH=1 时调用)。
  ① 先 git fetch origin, 失败即拒(远端不可达 / 网络失败 → 不能判断远端现状 → 拒);
  ② 只允许「远端不存在的新路径(A)」+ 「M 中本地不旧于远端者」
     (M 陈旧判定 = 本地文件 mtime < 远端该路径最后一次 commit 时间 → 本地旧 → 排除);
  ③ 排除 D(本地删除: 不允许非生产机删远端路径, 防误删共享仓库);
  ④ stdout 输出被允许的 add 清单(每行一个相对仓库根路径), 调用方 git add 只用这份清单,
     不许再 git add -A(这是"只增不覆盖"的实现点); 摘要/排除原因走 stderr。
  rc: 0=放行(清单非空) 1=拒绝(fetch 失败 / 无允许项) 2=内部错误(git 命令异常)。

失败显性(§23.11): 拒绝 = rc 1 + 明确日志(写清"为什么拒/怎么显式放行"),
调用方对拒绝必须告警(降级 notify), 绝不许静默 exit 0。

用法:
  python staticdata_write_guard.py --check-write-auth --repo <staticdata仓库>
  python staticdata_write_guard.py --check-fresh --repo <staticdata仓库> [--remote main]
  # --repo 缺省用 env STATICDATA_REPO, 再缺省用默认本机路径(同 large_json_excludes.py)。

测试(严禁写生产 staticdata 仓库): STATICDATA_REPO=/tmp/xxx 克隆或 --repo 指向克隆;
写权限判定用假路径(如 --repo /home/ubuntu/code/xxx / --repo /tmp/xxx)。
"""
import argparse
import os
import subprocess
import sys

PRODUCTION_PATH_PREFIX = "/home/ubuntu/"  # 生产机(云上)路径特征
DEFAULT_STATIC_REPO = "/Users/linhuichen/code/trade-data-signal-staticdata"
REMOTE_NAME = "origin"
BRANCH_NAME = "main"


# ── 纯函数: 生产机判定(可假路径单测云上放行分支) ──
def is_production_path(repo_path):
    """输入路径字符串 → 是否生产机路径(前缀 /home/ubuntu/)。"""
    return str(repo_path).startswith(PRODUCTION_PATH_PREFIX)


# ── 模式一: --check-write-auth ──
def check_write_auth(repo_path):
    """rc: 0=生产机(允许 git 写) 1=非生产机(默认拒绝, 仅 rsync+R2+降级通知)。"""
    if is_production_path(repo_path):
        print(f"✓ 生产机({repo_path}): 允许 staticdata git 写(commit/push)", file=sys.stderr)
        return 0
    print(f"✗ 非生产机({repo_path}): 默认禁止 staticdata git 写(commit/push)。", file=sys.stderr)
    print("  → 调用方应跳过 git 段仅留存 rsync 磁盘 + R2 + 降级通知。", file=sys.stderr)
    print("  → 显式放行(走只增不覆盖数据闸门): 设 STATICDATA_ALLOW_PUSH=1 并调 --check-fresh。",
          file=sys.stderr)
    return 1


# ── 模式二: --check-fresh 数据闸门 ──
def _git(repo, args, description):
    """跑 git 命令, 失败 → (None, err)。description 仅用于报错文案。"""
    out = subprocess.run(["git", "-C", repo] + args, capture_output=True, text=True)
    if out.returncode != 0:
        return None, out.stderr.strip()[:500]
    return out, None


def _remote_last_commit_ts(repo, path):
    """远端 main 上该路径最后一次 commit 的 unix 时间戳(没有 → None)。"""
    out = subprocess.run(
        ["git", "-C", repo, "log", "-1", "--format=%ct", f"{REMOTE_NAME}/{BRANCH_NAME}", "--", path],
        capture_output=True, text=True)
    if out.returncode != 0:
        return None
    ts = out.stdout.strip()
    try:
        return int(ts) if ts else None
    except ValueError:
        return None


def check_fresh(repo, remote=REMOTE_NAME, branch=BRANCH_NAME):
    """数据闸门: 只增不覆盖。rc 0=放行(清单 stdout) 1=拒绝 2=内部错误。"""
    # ① 先 fetch origin, 失败即拒(判断远端现状的前提)。
    out, err = _git(repo, ["fetch", remote], "git fetch origin")
    if out is None:
        print(f"✗ 数据闸门拒绝: git fetch {remote} 失败 -> {err}\n"
              f"  无法确认远端现状, 拒绝从非生产机推 staticdata git(只增不覆盖前提不成立), "
              f"跳过 commit/push 仅磁盘留档。", file=sys.stderr)
        return 1
    # ② 候选变更集(工作树 vs 远端 main): M/D(已跟踪) + A(未跟踪)。
    out, err = _git(repo, ["diff", "--name-status", f"{remote}/{branch}"],
                    "git diff --name-status origin/main")
    if out is None:
        print(f"✗ 数据闸门内部错误: git diff --name-status 失败 -> {err}", file=sys.stderr)
        return 2
    status_lines = out.stdout.splitlines()
    out2, err2 = _git(repo, ["ls-files", "--others", "--exclude-standard"],
                      "git ls-files --others")
    if out2 is None:
        print(f"✗ 数据闸门内部错误: git ls-files --others 失败 -> {err2}", file=sys.stderr)
        return 2
    allow = []    # 允许加入 add 清单的路径
    denied = []   # 被排除路径及原因(日志)
    candidates = []
    for line in status_lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        st, path = parts[0], parts[1].strip()
        candidates.append((st, path))
    for u in out2.stdout.splitlines():
        u = u.strip()
        if u:
            candidates.append(("A", u))
    for st, path in candidates:
        if st == "D":
            denied.append((path, "D:不允许非生产机删除远端路径"))
            continue
        # 该路径在远端分支树上是否存在?
        exists_on_remote = _remote_last_commit_ts(repo, path) is not None
        if not exists_on_remote:
            allow.append(path)  # A: 远端不存在的新路径, 只增, 不覆盖任何东西
            continue
        # M: 本地旧于远端 → 排除(防旧数据覆盖新数据)。
        full = os.path.join(repo, path)
        try:
            local_mtime = int(os.path.getmtime(full))
        except OSError:
            denied.append((path, "M:本地文件缺失/不可读, 排除"))
            continue
        remote_ts = _remote_last_commit_ts(repo, path)
        if remote_ts is not None and local_mtime < remote_ts:
            denied.append((path, f"M:本地旧(本地mtime={local_mtime} < 远端commit={remote_ts}), 排除"))
            continue
        allow.append(path)  # M 本地不旧于远端(或读不到远端时间)——允许
    # ③ 输出结果
    for path in allow:
        print(path)
    if denied:
        print(f"✗ 数据闸门排除 {len(denied)} 项(只增不覆盖):", file=sys.stderr)
        for path, why in denied:
            print(f"  {why}  {path}", file=sys.stderr)
    if not allow:
        print("✗ 数据闸门拒绝(0 项允许): 无远端不存在的新路径, 且无本地不旧于远端的修改。"
              "跳过 commit/push 仅磁盘留档。", file=sys.stderr)
        return 1
    print(f"✓ 数据闸门放行 {len(allow)} 项(仅新增/不旧覆盖, 见 stdout 清单)", file=sys.stderr)
    return 0


def resolve_repo(repo_arg):
    """--repo > env STATICDATA_REPO > 默认本机路径(同 large_json_excludes.staticdata_repo 风格,
    但不强求 .git 存在——写权限判定是纯路径字符串判定, 云上/假路径单测都不依赖真仓库)。"""
    return repo_arg or os.environ.get("STATICDATA_REPO", DEFAULT_STATIC_REPO)


def main():
    ap = argparse.ArgumentParser(
        description="staticdata git 写权限守卫单一源(供 staticdata_backup_async.sh / staticdata_sync.sh 共用)")
    ap.add_argument("--repo", help="staticdata 仓库路径(缺省 env STATICDATA_REPO 或默认本机路径)")
    ap.add_argument("--check-write-auth", action="store_true",
                    help="判定本机是否生产机(rc: 0=允许 1=非生产机默认拒绝 2=内部错误)")
    ap.add_argument("--check-fresh", action="store_true",
                    help="数据闸门(显式 STATICDATA_ALLOW_PUSH=1 时): fetch+只增不覆盖, stdout 输出允许 add 清单")
    ap.add_argument("--remote", default=REMOTE_NAME, help="远端名(默认 origin)")
    args = ap.parse_args()
    repo = resolve_repo(args.repo)
    if args.check_write_auth:
        sys.exit(check_write_auth(repo))
    elif args.check_fresh:
        sys.exit(check_fresh(repo, remote=args.remote))
    else:
        ap.error("必须指定 --check-write-auth 或 --check-fresh")


if __name__ == "__main__":
    main()