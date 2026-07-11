#!/usr/bin/env python3
"""持锁执行命令（跨平台 fcntl.flock，macOS/Linux 通用）。

用法: python with_lock.py [--nb [--on-skip <cmd>]] <lockfile> <cmd> [args...]
持独占锁(LOCK_EX)执行 cmd；进程退出（含崩溃/被杀）锁自动释放。

  --nb            非阻塞：锁已被占则不等待，直接 exit 0 跳过（用于"重复跑跳过"场景）。
                  默认阻塞等待（用于 deploy 串行化排队场景）。
  --on-skip <cmd> 仅与 --nb 配合：锁被占跳过时先执行 cmd（把锁路径作为参数传给
                  cmd：`cmd <lockpath>`），再 exit 0。用于"锁跳过触发通知"。
                  不影响原有 --nb 无 --on-skip 的行为（仍 stderr 输出 + exit 0）。
                  不影响阻塞模式（无 --nb 时本参数无效）。

用途：
  - 多 pipeline 并发时串行化 git commit+push（阻塞），避免 .git/index.lock
    冲突 + git add 把别 pipeline 正在写的半截 JSON stage 进来。
  - update_all.sh 进程互斥（--nb）：防止多个 update_all 并发跑撞 mootdx/
    stock_daily progress 原子写 + 通达信/东财并发限流全 empty 空转。
  - update_all.sh 进程互斥 + --on-skip：锁跳过时触发 notify.py 通知用户。

为何不用 flock(1)：macOS 默认无 flock 命令（util-linux 工具），
fcntl.flock 是 POSIX 标准，Python 自带，无外部依赖。
"""
import fcntl
import subprocess
import sys

args = sys.argv[1:]
nonblock = False
on_skip = None

# 解析 --nb（无值开关）和 --on-skip <cmd>（有值，取一个 token 作为命令名）
# --on-skip 后紧跟的 token 是要执行的命令（如 scripts/on_skip_notify.sh），
# 该命令自己解析后续参数。这里只取命令名，不吞其参数。
rest = []
i = 0
while i < len(args):
    a = args[i]
    if a == "--nb":
        nonblock = True
        i += 1
    elif a == "--on-skip":
        if i + 1 >= len(args):
            print("usage: with_lock.py [--nb [--on-skip <cmd>]] <lockfile> <cmd> [args...]", file=sys.stderr)
            sys.exit(2)
        on_skip = args[i + 1]
        i += 2
    else:
        rest.append(a)
        i += 1
args = rest

if len(args) < 2:
    print("usage: with_lock.py [--nb [--on-skip <cmd>]] <lockfile> <cmd> [args...]", file=sys.stderr)
    sys.exit(2)

lockpath = args[0]
cmd = args[1:]
f = open(lockpath, "w")
try:
    fcntl.flock(f, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblock else 0))
except BlockingIOError:
    print(f"[with_lock] {lockpath} 已被占用，跳过", file=sys.stderr)
    if on_skip:
        try:
            subprocess.run([on_skip, lockpath])
        except Exception as e:  # noqa: BLE001
            print(f"[with_lock] --on-skip 执行失败（不阻塞跳过）：{e}", file=sys.stderr)
    sys.exit(0)
r = subprocess.run(cmd)
sys.exit(r.returncode)
