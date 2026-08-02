#!/bin/bash
# stage0_nav.sh - 公募基金筛选器阶段0 nav 周频断点续采(launchd 周五 01:43)
#
# 调 python -m app.collector.public_fund stage0-nav --days 1825
#   补 5 年净值历史(27409 只, 分批断点续采, 可中断续跑累计完成)
#
# 进程互斥:
#   - shell 层 fcntl 互斥锁 /tmp/stage0-nav.lock(重复跑自动跳过)
#   - python 内 public_fund.lock(_acquire_lock, 与 quarterly/full/daily 共用, 撞锁跳过)
#
# 时点: 周五凌晨 01:43(周五凌晨市场关闭净值不变, 断点续采可多次跑累计完成;
#   避开 update_all 17:50 / 盘中 / intraday-snapshot 每10min 推 main)
# 日志: data/logs/stage0-nav.log(append)
set -uo pipefail
# 防脚本运行期间 mac 休眠(5 年净值大工程, 长任务必须防休眠)
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade-data"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/stage0-nav.log"
LOCK="/tmp/stage0-nav.lock"

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
  || { echo "=== $(date '+%F %T') stage0-nav lock busy, skip ===" >>"$LOG"; exit 0; }

{
echo "=== $(date '+%F %T') stage0-nav start (days=1825) ==="
"$PY" -m app.collector.public_fund stage0-nav --days 1825
RC=$?
echo "=== $(date '+%F %T') stage0-nav end rc=$RC ==="
exit $RC
} >>"$LOG" 2>&1
