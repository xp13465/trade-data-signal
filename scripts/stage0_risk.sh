#!/bin/bash
# stage0_risk.sh - 公募基金筛选器阶段0 risk 季报后采集(launchd 每月15日 02:33)
#
# 调 python -m app.collector.public_fund stage0-risk
#   季报后 risk_indicator + fee_detail ~4.5h(逐只 xq + 费率)
#
# 月份闸门: launchd 每月15日触发, 脚本内判断只有 1/4/7/10 月(季报披露完成月)才真跑,
#   其他月份 exit 0 跳过(避免非季报月空跑)
#
# 进程互斥:
#   - shell 层 fcntl 互斥锁 /tmp/stage0-risk.lock(重复跑自动跳过)
#   - python 内 public_fund.lock(_acquire_lock, 与 quarterly/full/daily 共用, 撞锁跳过)
#
# 时点: 每月15日 02:33(季报披露完成后, 避开 update_all 17:50 / 盘中 / intraday-snapshot)
# 日志: data/logs/stage0-risk.log(append)
set -uo pipefail
# 防脚本运行期间 mac 休眠(4.5h 长任务必须防休眠)
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade-data"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/stage0-risk.log"
LOCK="/tmp/stage0-risk.lock"

mkdir -p "$(dirname "$LOG")"
cd "$REPO"

# 季度月闸门: 只有 1/4/7/10 月(季报披露完成月)才真跑, 其他月份跳过
MONTH=$(date +%m)
case "$MONTH" in
  01|04|07|10) ;;
  *) echo "=== $(date '+%F %T') stage0-risk skip (month=$MONTH, not quarter month) ===" >>"$LOG"; exit 0 ;;
esac

# fcntl 互斥锁(非阻塞, 持不到=已有在跑=跳过)
"$PY" -c "import fcntl,sys; f=open('$LOCK','w'); sys.exit(0 if fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)==0 else 1)" \
  || { echo "=== $(date '+%F %T') stage0-risk lock busy, skip ===" >>"$LOG"; exit 0; }

{
echo "=== $(date '+%F %T') stage0-risk start (month=$MONTH) ==="
"$PY" -m app.collector.public_fund stage0-risk
RC=$?
echo "=== $(date '+%F %T') stage0-risk end rc=$RC ==="
exit $RC
} >>"$LOG" 2>&1
