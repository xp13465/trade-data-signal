#!/usr/bin/env python3
"""pick_repo.py - 部署源树(写/上传)与 git 仓统一 helper(防再犯机制 E, 2026-08-18)

背景(2026-08-18 冲突覆盖根因报告 docs/conflict-overwrite-rootcause-2026-08-18.md #3/#4):
  项6/fetch_news 两次「写部署源树路径错」——upload 子进程用 env.setdefault("REPO",...) 不覆盖
  已有值, 导致按 env.REPO=trade-data 拼错源目录(旧实体目录), deploy rsync 反覆盖线上。
  根因: 各脚本各自实现 REPO 解析(重复 pick_repo), 且子进程 env 用 setdefault 不强制覆盖,
  部署链读到与写入位置不一致的目录 → rsync clobber。

本模块统一「部署源树/上传源树」repo 解析, 所有写部署源树 + R2 上传 + staticdata 同步入口统一走它:
  - pick_repo():  部署源树(trade-data, launchd 主数据/上传源树), 写 static-site/data 的目标
  - pick_git_repo(): trade git 仓库(deploy.sh commit/push 目标)
  - force_env():  env 强制覆盖 REPO/GIT_REPO(不用 setdefault), 确保子进程解析到同一 repo
  - guard_deploy_source_tree(): 写源树守卫——目标必须 = trade-data(上传源树), 误写 trade(git 仓)
    即报错(§23.11 发现问题绝不静默, 立即阻断, 不静默继续)。

目录语义:
  - trade-data(/Users/linhuichen/code/trade-data) = 部署源树/上传源树(launchd 主数据, 非 git 仓)
  - trade(/Users/linhuichen/code/trade) = git 仓库(deploy.rsync trade-data -> trade, commit+push)
"""
from __future__ import annotations

import os
from pathlib import Path

# 部署源树(上传源树, 非 git 仓): launchd/update_all 写主数据的位置
MAIN_REPO = Path("/Users/linhuichen/code/trade-data")
# git 仓库: deploy.sh commit/push 目标
GIT_REPO_DEFAULT = Path(__file__).resolve().parent.parent  # trade/scripts/pick_repo.py -> trade


def candidate_repos() -> list[Path]:
    """候选 repo 列表(去重, 保序): trade-data 优先, 再 git 仓, 再 env 注入。"""
    out: list[Path] = []
    for c in ([str(MAIN_REPO), str(GIT_REPO_DEFAULT),
               os.environ.get("GIT_REPO", ""), os.environ.get("REPO", "")]):
        if not c:
            continue
        p = Path(c).resolve()
        if p not in out:
            out.append(p)
    return out


def pick_git_repo() -> Path:
    """返回 trade git 仓库(env GIT_REPO 优先, 否则脚本所在仓库)。"""
    env_g = os.environ.get("GIT_REPO", "").strip()
    if env_g:
        p = Path(env_g).resolve()
        if p.is_dir():
            return p
    return GIT_REPO_DEFAULT.resolve()


def pick_repo() -> Path:
    """部署源树(写/上传)repo: 挑 static-site/data/overview.json.date 最新者, 同日期优先 trade-data。

    launchd/update_all 从 trade-data(部署源树)跑, 手动从 trade 跑。写 + R2 上传 + staticdata
    同步统一落到本函数选中的同一树, 保证部署链读到新版不 clobber(2026-08-18 断点根因)。
    仅当 trade-data 不存在/不可用时才回退其他候选(dev 环境无 trade-data)。"""
    best, best_date = None, ""
    for r in candidate_repos():
        ov = r / "static-site" / "data" / "overview.json"
        if not ov.exists():
            continue
        d = _read_overview_date(ov)
        if d > best_date:  # 严格大于: 同日期保留先出现者(trade-data 在前)
            best_date, best = d, r
    if best is None:
        best = candidate_repos()[0]
    return best


def _read_overview_date(ov: Path) -> str:
    import json
    try:
        return str(json.loads(ov.read_text(encoding="utf-8")).get("date", ""))
    except Exception:
        return ""


def guard_deploy_source_tree(repo: Path | str) -> Path:
    """写源树守卫(§23.11): 写部署源树的目标必须 = trade-data(上传源树)。

    若解析出的 repo == trade(git 仓) 而 trade-data 存在 → 误写 git 仓(会把 trade-data 新版
    clobber 回旧版的老 bug), 立即报错阻断, 绝不静默继续。返回规范化 repo(合法时)。
    """
    repo = Path(repo).resolve()
    git = pick_git_repo().resolve()
    # 只有「解析到 git 仓」才需要守卫检查; 若本来就是 trade-data 或非 git 仓目录, 直接放行
    if repo != git:
        return repo
    # repo == git 仓(trade): 若 trade-data(部署源树)存在, 则本次写目标是 git 仓 = 误写
    trade_data = MAIN_REPO.resolve()
    if trade_data.exists() and trade_data.is_dir():
        raise SystemExit(
            f"✗ 写部署源树目标错误: pick_repo() 解析到 git 仓 {git}(/trade), 而非部署源树 "
            f"{trade_data}(/trade-data)。误写 git 仓会导致 deploy rsync 把 trade-data 新版 "
            f"clobber 回旧版(2026-08-18 断点根因, §23.11 发现问题绝不静默)。"
            f"请检查 REPO/GIT_REPO 环境变量与数据写入逻辑。"
        )
    # trade-data 不存在(dev 环境) → 回退 git 仓合法
    return repo


def force_env(env: dict, repo: Path | str, git_repo: Path | str | None = None) -> dict:
    """env 强制覆盖 REPO/GIT_REPO(不用 setdefault, 同 fetch_news 818 根修)。

    子进程(upload_r2/staticdata_sync)常因 env 已有值而 setdefault 不覆盖 → 解析到与写入位置
    不一致的目录(读旧版/读空目录)。这里强制覆盖, 确保上传/staticdata 源目录 = 写部署源树。
    """
    repo = guard_deploy_source_tree(repo)
    env = dict(env)
    env["REPO"] = str(repo)
    env["GIT_REPO"] = str(git_repo if git_repo is not None else pick_git_repo())
    return env


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="打印部署源树/git 仓 repo(防再犯机制 E 统一 helper)")
    ap.add_argument("--mode", choices=["deploy", "git"], default="deploy",
                    help="deploy=部署源树(写/上传, 默认); git=git 仓库")
    args = ap.parse_args()
    if args.mode == "git":
        print(pick_git_repo())
        return 0
    try:
        r = guard_deploy_source_tree(pick_repo())
    except SystemExit as e:
        print(str(e), file=os.sys.stderr)
        return 1
    print(r)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
