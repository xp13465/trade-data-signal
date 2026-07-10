#!/usr/bin/env python3
"""持锁执行命令（跨平台 fcntl.flock，macOS/Linux 通用）。

用法: python with_lock.py <lockfile> <cmd> [args...]
持独占锁(LOCK_EX)执行 cmd；进程退出（含崩溃/被杀）锁自动释放。

用途：多 pipeline 并发时串行化 git commit+push，避免
  ① .git/index.lock 冲突；② 一个 pipeline 的 git add 把另一 pipeline
  正在写的半截 JSON stage 进来。

为何不用 flock(1)：macOS 默认无 flock 命令（util-linux 工具），
fcntl.flock 是 POSIX 标准，Python 自带，无外部依赖。
"""
import fcntl
import subprocess
import sys

if len(sys.argv) < 3:
    print("usage: with_lock.py <lockfile> <cmd> [args...]", file=sys.stderr)
    sys.exit(2)

lockpath = sys.argv[1]
cmd = sys.argv[2:]
with open(lockpath, "w") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    r = subprocess.run(cmd)
    sys.exit(r.returncode)
