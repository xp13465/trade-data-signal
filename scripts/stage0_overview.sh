#!/bin/bash
# stage0_overview.sh - 公募基金筛选器阶段0 overview 周频采集(launchd 周日 02:17)
#
# 调 python -m app.collector.public_fund stage0-overview
#   补 fund_overview_em 全量(补 fund_basic 15 新列) ~6.2h, 周频足够
#
# 进程互斥:
#   - shell 层 fcntl 互斥锁 /tmp/stage0-overview.lock(重复跑自动跳过)
#   - python 内 public_fund.lock(_acquire_lock, 与 quarterly/full/daily 共用, 撞锁跳过)
#
# 时点: 周日凌晨 02:17(避开 update_all 17:50 / 盘中 / intraday-snapshot 每10min 推 main)
# 日志: data/logs/stage0-overview.log(append)
set -uo pipefail
# 防脚本运行期间 mac 休眠(6.2h 长任务必须防休眠)
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade-data"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/stage0-overview.log"
LOCK="/tmp/stage0-overview.lock"

mkdir -p "$(dirname "$LOG")"
cd "$REPO"

# fcntl 互斥锁(非阻塞, 持不到=已有在跑=跳过)
"$PY" -c "import fcntl,sys; f=open('$LOCK','w'); sys.exit(0 if fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)==0 else 1)" \
  || { echo "=== $(date '+%F %T') stage0-overview lock busy, skip ===" >>"$LOG"; exit 0; }

{
echo "=== $(date '+%F %T') stage0-overview start ==="
"$PY" -m app.collector.public_fund stage0-overview
RC=$?
echo "=== $(date '+%F %T') stage0-overview end rc=$RC ==="
exit $RC
} >>"$LOG" 2>&1
