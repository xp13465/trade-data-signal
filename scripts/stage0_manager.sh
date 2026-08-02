#!/bin/bash
# stage0_manager.sh - 公募基金筛选器阶段0 manager 月频采集(launchd 每月1日 02:47)
#
# 调 python -m app.collector.public_fund stage0-manager
#   自爬 fundf10 补任职历史 ~3h(appoint_date + managed_history)
#
# 进程互斥:
#   - shell 层 fcntl 互斥锁 /tmp/stage0-manager.lock(重复跑自动跳过)
#   - python 内 public_fund.lock(_acquire_lock, 与 quarterly/full/daily 共用, 撞锁跳过)
#
# 时点: 每月1日 02:47(月频足够, 避开 update_all 17:50 / 盘中 / intraday-snapshot)
# 日志: data/logs/stage0-manager.log(append)
set -uo pipefail
# 防脚本运行期间 mac 休眠(3h 长任务必须防休眠)
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade-data"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/stage0-manager.log"
LOCK="/tmp/stage0-manager.lock"

mkdir -p "$(dirname "$LOG")"
cd "$REPO"

# fcntl 互斥锁(非阻塞, 持不到=已有在跑=跳过)
# 注意: fcntl.flock 成功返回 None(非 0), 用 try/except BlockingIOError 判断
"$PY" -c "import fcntl,sys
f=open('$LOCK','w')
try:
    fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.exit(0)
except BlockingIOError:
    sys.exit(1)" \
  || { echo "=== $(date '+%F %T') stage0-manager lock busy, skip ===" >>"$LOG"; exit 0; }

{
echo "=== $(date '+%F %T') stage0-manager start ==="
"$PY" -m app.collector.public_fund stage0-manager
RC=$?
echo "=== $(date '+%F %T') stage0-manager end rc=$RC ==="
exit $RC
} >>"$LOG" 2>&1
