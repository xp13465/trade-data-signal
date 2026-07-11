#!/usr/bin/env python3
"""持锁执行命令（跨平台 fcntl.flock，macOS/Linux 通用）。

用法: python with_lock.py [--nb] <lockfile> <cmd> [args...]
持独占锁(LOCK_EX)执行 cmd；进程退出（含崩溃/被杀）锁自动释放。

  --nb  非阻塞：锁已被占则不等待，直接 exit 0 跳过（用于"重复跑跳过"场景）。
        默认阻塞等待（用于 deploy 串行化排队场景）。

用途：
  - 多 pipeline 并发时串行化 git commit+push（阻塞），避免 .git/index.lock
    冲突 + git add 把别 pipeline 正在写的半截 JSON stage 进来。
  - update_all.sh 进程互斥（--nb）：防止多个 update_all 并发跑撞 mootdx/
    stock_daily progress 原子写 + 通达信/东财并发限流全 empty 空转。

为何不用 flock(1)：macOS 默认无 flock 命令（util-linux 工具），
fcntl.flock 是 POSIX 标准，Python 自带，无外部依赖。
"""
import fcntl
import subprocess
import sys

args = sys.argv[1:]
nonblock = False
if args and args[0] == "--nb":
    nonblock = True
    args = args[1:]

if len(args) < 2:
    print("usage: with_lock.py [--nb] <lockfile> <cmd> [args...]", file=sys.stderr)
    sys.exit(2)

lockpath = args[0]
cmd = args[1:]
f = open(lockpath, "w")
try:
    fcntl.flock(f, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblock else 0))
except BlockingIOError:
    print(f"[with_lock] {lockpath} 已被占用，跳过", file=sys.stderr)
    sys.exit(0)
r = subprocess.run(cmd)
sys.exit(r.returncode)
