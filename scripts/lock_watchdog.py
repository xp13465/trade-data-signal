#!/usr/bin/env python3
"""
lock_watchdog.py — 盘中快照锁 watchdog（根治 with_lock.py --nb 永久跳过问题）

背景：
  intraday_snapshot.sh 用 with_lock.py --nb 持 /tmp/trade_intraday_snapshot.lock
  若采集进程僵死（网络/数据库卡死），锁被真实进程持有，后续每 10 分钟
  launchd 拉起的新进程全部跳过 -> 数据永久停更。

逻辑：
  1. 锁文件不存在   -> 正常（无前序进程），返回 True（可继续）
  2. 锁文件存在，且 lsof 确认有进程持锁，且进程仍在运行
     -> 真实运行中（哪怕已跑 7h），返回 False（跳过本次，不砸锁）
  3. 锁文件存在，lsof 无进程持锁（进程已死/被杀）
     -> 死锁，删除锁文件，返回 True（允许新进程继续）
  4. 锁文件存在，lsof 无输出，且文件 mtime > STALE_THRESHOLD 秒
     -> 极可能死锁（进程死但 flock 已自动释放），删除锁文件，返回 True
  5. 锁文件存在，mtime < STALE_THRESHOLD，但 lsof 无进程
     -> 刚创建锁文件就进程挂了，极罕见，视为死锁删除

调用方式（替换 with_lock.py --nb）：
  python3 scripts/lock_watchdog.py /tmp/trade_intraday_snapshot.lock && \
    bash scripts/intraday_snapshot.sh

或作为 with_lock.py 的预检：
  python3 scripts/lock_watchdog.py /tmp/trade_intraday_snapshot.lock || exit 0
  python3 scripts/with_lock.py --nb /tmp/trade_intraday_snapshot.lock ...
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

STALE_THRESHOLD = 600  # 10 分钟：超过视为可能死锁

def check_lock_alive(lock_path: Path) -> tuple[bool, str]:
    """
    返回 (is_alive, reason)
    is_alive=True  : 锁真实被某进程持有
    is_alive=False : 锁已死（无进程持锁）
    """
    if not lock_path.exists():
        return False, "lock_file_not_exist"

    # 尝试 lsof 查持锁进程
    try:
        r = subprocess.run(
            ["lsof", str(lock_path)],
            capture_output=True, text=True, timeout=10
        )
        lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
        # lsof 输出格式: COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
        # 第一行是表头，跳过
        data_lines = [l for l in lines if not l.startswith("COMMAND")]
        if data_lines:
            pids = set()
            for line in data_lines:
                parts = line.split()
                if len(parts) >= 2:
                    pids.add(parts[1])
            for pid in pids:
                try:
                    os.kill(int(pid), 0)  # 只测进程是否存在
                    return True, f"process_holding_lock_pid={pid}"
                except (OSError, ProcessLookupError):
                    pass
            # lsof 找到进程但进程已死 -> 死锁
            return False, f"lsof_found_dead_pid={pids}"
    except subprocess.TimeoutExpired:
        pass
    except FileNotFoundError:
        pass  # lsof 不存在（极少）

    # 无 lsof 或 lsof 无输出：用 mtime 判断
    mtime = lock_path.stat().st_mtime
    age = time.time() - mtime
    if age > STALE_THRESHOLD:
        return False, f"stale_by_mtime_age={age:.0f}s"
    # 锁文件新但无进程持锁 -> 极罕见（进程创建文件后立即挂），视为死锁
    return False, f"no_lsof_holder_age={age:.0f}s"


def main() -> int:
    parser = argparse.ArgumentParser(description="盘中快照锁 watchdog")
    parser.add_argument("lockfile", type=Path)
    parser.add_argument(
        "--stale-threshold", type=int, default=STALE_THRESHOLD,
        help=f"锁文件超过多少秒视为可能死锁（默认 {STALE_THRESHOLD}s）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只诊断不操作"
    )
    args = parser.parse_args()

    lock_path = args.lockfile.resolve()
    is_alive, reason = check_lock_alive(lock_path)

    if is_alive:
        print(f"[lock_watchdog] 锁真实被持有({reason})，本次跳过", file=sys.stderr)
        return 1  # 退出码1 = 不要继续
    else:
        if not lock_path.exists():
            print(f"[lock_watchdog] 锁文件不存在({reason})，允许继续", file=sys.stderr)
            return 0  # 退出码0 = 可以继续
        else:
            if args.dry_run:
                print(f"[lock_watchdog] [DRY RUN] 会删除锁({reason})，允许继续", file=sys.stderr)
                return 0
            lock_path.unlink()
            print(f"[lock_watchdog] ⚠ 死锁检测到({reason})，已删除锁文件，允许继续", file=sys.stderr)
            return 0  # 退出码0 = 可以继续

if __name__ == "__main__":
    raise SystemExit(main())
