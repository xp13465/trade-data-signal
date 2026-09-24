#!/usr/bin/env python3
"""持锁执行命令（跨平台 fcntl.flock，macOS/Linux 通用）。

用法: python with_lock.py [--nb [--on-skip <cmd>]] [--block-timeout <秒>] <lockfile> <cmd> [args...]
持独占锁(LOCK_EX)执行 cmd；进程退出（含崩溃/被杀）锁自动释放。

  --nb            非阻塞：锁已被占则不等待，直接 exit 0 跳过（用于"重复跑跳过"场景）。
                  默认阻塞等待（用于 deploy 串行化排队场景）。
  --on-skip <cmd> 仅与 --nb 配合：锁被占跳过时先执行 cmd（把锁路径作为参数传给
                  cmd：`cmd <lockpath>`），再 exit 0。用于"锁跳过触发通知"。
                  不影响原有 --nb 无 --on-skip 的行为（仍 stderr 输出 + exit 0）。
                  不影响阻塞模式（无 --nb 时本参数无效）。
  --block-timeout <秒>  仅阻塞模式（无 --nb）生效：排队等锁超时护栏。默认 0=无限阻塞
                  （完全向后兼容）。设为 N>0 时改用「非阻塞轮询 + 累计超时」等锁
                  （fcntl LOCK_NB 循环 + sleep 小间隔），累计等待超过 N 秒仍未拿到锁
                  → notify 告警 + 优雅跳过（exit 0，不当作崩溃、不触发 systemd failed，
                  但必须通知：数据可能缺失需补跑，防静默丢）。

用途：
  - 多 pipeline 并发时串行化 git commit+push（阻塞），避免 .git/index.lock
    冲突 + git add 把别 pipeline 正在写的半截 JSON stage 进来。
  - update_all.sh 进程互斥（--nb）：防止多个 update_all 并发跑撞 mootdx/
    stock_daily progress 原子写 + 通达信/东财并发限流全 empty 空转。
  - update_all.sh 进程互斥 + --on-skip：锁跳过时触发 notify.py 通知用户。
  - deploy 串行锁 + --block-timeout：防单点慢 deploy 拖垮整条盘后链
    （2026-09-18 事故：R2 慢 deploy 85min 占锁，下游 futures/etf/lhb/lab
    排队到各自 systemd TimeoutStartSec 90min 被硬杀 exit143 连环告警）。

为何不用 flock(1)：macOS 默认无 flock 命令（util-linux 工具），
fcntl.flock 是 POSIX 标准，Python 自带，无外部依赖。
"""
import fcntl
import os
import subprocess
import sys
import time

args = sys.argv[1:]
nonblock = False
on_skip = None
block_timeout = 0

# 解析 --nb（无值开关）、--on-skip <cmd>（有值，取一个 token 作为命令名）、
# --block-timeout <秒>（有值，排队等锁超时护栏）
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
            print("usage: with_lock.py [--nb [--on-skip <cmd>]] [--block-timeout <秒>] <lockfile> <cmd> [args...]", file=sys.stderr)
            sys.exit(2)
        on_skip = args[i + 1]
        i += 2
    elif a == "--block-timeout":
        if i + 1 >= len(args):
            print("usage: with_lock.py [--nb [--on-skip <cmd>]] [--block-timeout <秒>] <lockfile> <cmd> [args...]", file=sys.stderr)
            sys.exit(2)
        try:
            block_timeout = int(args[i + 1])
        except ValueError:
            print(f"with_lock.py: --block-timeout 需为整数秒，收到 '{args[i + 1]}'", file=sys.stderr)
            sys.exit(2)
        i += 2
    else:
        rest.append(a)
        i += 1
args = rest

if len(args) < 2:
    print("usage: with_lock.py [--nb [--on-skip <cmd>]] [--block-timeout <秒>] <lockfile> <cmd> [args...]", file=sys.stderr)
    sys.exit(2)

lockpath = args[0]
cmd = args[1:]


def _notify_block_timeout(waited_sec: int) -> None:
    """排队超时跳过告警：调 notify.py，带 lockpath + 已等待时长 + 需补跑提示。
    失败不阻塞跳过（best-effort，同 --on-skip 语义），但通常能发出去。
    """
    try:
        # REPO 定位：优先环境变量（pipeline.sh/update_all.sh 等调用方已 export REPO），
        # fallback realpath（脚本在 scripts/，父父级即项目根）
        repo = os.environ.get("REPO")
        if not repo:
            repo = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        py = os.path.join(repo, ".venv", "bin", "python")
        notify_py = os.path.join(repo, "scripts", "notify.py")
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        subject = f"[告警] 排队超时跳过 {lockpath}"
        body = (
            f"with_lock 排队等锁超时：等待锁 {lockpath} 超过 {block_timeout}s "
            f"（实际等待 {waited_sec}s），本次任务已优雅跳过（exit 0），命令未执行：{' '.join(cmd)}。<br>"
            f"时间：{now}<br>"
            f"⚠ 数据可能缺失需补跑（如 deploy 链某下游产物未生成）。"
        )
        # WITH_LOCK_NOTIFY_DRY_RUN=1 时走 --dry-run（不真发邮件/飞书，本地模拟自测用，
        # 对齐 on_skip_notify.sh 的 ON_SKIP_DRY_RUN 惯例）。生产不设该变量 → 真发告警。
        dry_flag = ["--dry-run"] if os.environ.get("WITH_LOCK_NOTIFY_DRY_RUN") == "1" else []
        # 2026-09-24 告警降噪 P2: dedup 30min->6h(排队超时=锁竞争瞬时, 已自愈, 8 封/周噪音)。
        # 保持 --severe(任务被跳过需补跑提示), 首封立即发, 6h 内同 lockpath 不重复轰炸。
        # 真锁死(排队任务互相饿死)由 schedule_monitor exit/产物时效/进行中超时通道兜底不掩盖。
        subprocess.run(
            [py, notify_py, subject, body, "--severe", "--from-prefix", "[告警]",
             "--alert-issue", f"with_lock 排队超时跳过({lockpath})",
             "--dedup-key", f"with_lock_block_timeout:{lockpath}", "--dedup-window", "21600"] + dry_flag,
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[with_lock] 排队超时告警发送失败（不阻塞跳过）：{e}", file=sys.stderr)


f = open(lockpath, "w")
try:
    if nonblock:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"[with_lock] {lockpath} 已被占用，跳过", file=sys.stderr)
            if on_skip:
                try:
                    subprocess.run([on_skip, lockpath])
                except Exception as e:  # noqa: BLE001
                    print(f"[with_lock] --on-skip 执行失败（不阻塞跳过）：{e}", file=sys.stderr)
            sys.exit(0)
    elif block_timeout > 0:
        # 阻塞模式 + 排队超时护栏：非阻塞轮询 + 累计超时（fcntl LOCK_NB 循环 + sleep 小间隔）
        # 超时 → 告警 + 优雅跳过（exit 0，不当作崩溃；告警防数据缺失没人知道）
        poll_interval = 2  # 秒，小间隔轮询（锁一旦释放尽快拿到，又不空转打 CPU）
        waited = 0
        acquired = False
        while waited < block_timeout:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(poll_interval)
                waited += poll_interval
        if not acquired:
            print(f"[with_lock] {lockpath} 排队等锁超时（>{block_timeout}s），优雅跳过（exit 0）", file=sys.stderr)
            _notify_block_timeout(waited)
            sys.exit(0)
    else:
        fcntl.flock(f, fcntl.LOCK_EX)
except BlockingIOError:
    print(f"[with_lock] {lockpath} 已被占用，跳过", file=sys.stderr)
    sys.exit(0)
r = subprocess.run(cmd)
sys.exit(r.returncode)
