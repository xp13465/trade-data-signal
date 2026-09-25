#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_large_json_excluded.py - 大 JSON 移出 staticdata git 机检(2026-09-25, feat/large-json-r2-core)

调 large_json_excludes.py --check: staticdata 备份 git 仓库里仍存在 >20MB 的 tracked 大文件
→ 非零退出(FAIL), 打印漏网清单。挂 deploy 链常驻拦截(同 check_task_state/check_fade_keys 待遇:
FAIL 阻断上线), 防 .git 继续膨胀/积压超阈值跳过 commit 事故复发。

背景(9-25 首跑 skip_oversize): 7 个大 JSON(~320MB)天天进 delta, 撞 >300MB 积压阈值跳过 commit。
迁移 = scripts/migrate_large_json_out_of_git.sh(硬顺序先 R2 后 rm --cached, 留给人 commit+push)。
本机检 = 迁移是否完成 + 有无新漏网。⚠ merge 后须先人工跑迁移脚本再下一次 deploy, 否则被本闸门拦
(这正是闸门的目的)。

用法: python check_large_json_excluded.py --repo <GIT_REPO trade 仓库路径> [--deploy-mode]
"""
import os
import sys
import subprocess
import argparse


def main():
    ap = argparse.ArgumentParser(description="大 JSON 移出 staticdata git 机检")
    ap.add_argument("--repo", help="trade 仓库路径(用于派生 staticdata 路径, 云上单仓回退)")
    ap.add_argument("--staticdata-repo", dest="srepo", help="staticdata 仓库路径(缺省 env STATICDATA_REPO 或 --repo 派生)")
    ap.add_argument("--deploy-mode", action="store_true", help="兼容 deploy.sh 其它 check 传参")
    args = ap.parse_args()

    git_repo = args.repo or os.environ.get("GIT_REPO", "")
    srepo = args.srepo or os.environ.get("STATICDATA_REPO", "")
    if not srepo:
        # 与 staticdata_backup_async.sh 同款: 默认本机路径 + 云上单仓回退
        default_local = "/Users/linhuichen/code/trade-data-signal-staticdata"
        if os.path.isdir(os.path.join(default_local, ".git")):
            srepo = default_local
        elif git_repo and os.path.isdir(f"{git_repo}-staticdata/.git"):
            srepo = f"{git_repo}-staticdata"
    if not os.path.isdir(os.path.join(srepo, ".git")):
        print(f"✗ staticdata 仓库不存在(.git 缺失): {srepo}(机检无法执行)", file=sys.stderr)
        sys.exit(1)

    here = os.path.dirname(os.path.abspath(__file__))
    rc = subprocess.run(
        [sys.executable, os.path.join(here, "large_json_excludes.py"), "--check", "--repo", srepo],
    )
    sys.exit(rc.returncode)


if __name__ == "__main__":
    main()