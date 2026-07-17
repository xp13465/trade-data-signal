#!/bin/bash
# futures_backfill.sh - 期货机构持仓当日单采（launchd 20:05 定时，根治期货 46h 滞后）
#
# 问题：CFFEX 股指期货（IF/IC/IH/IM）前20名会员持仓次日约 20:00 后才发布当日数据，
#   17:50 update_all 采不到 -> 第三日才采到，滞后最久 46h。20:05 单采当日 -> 滞后 0.05h。
#
# 只做：期货 collect_daily(当日) + compute_accuracy -> (有新数据则) 持 deploy 锁推送。
#   等价于 pipeline.sh futures，但加自身互斥 + 交易日闸门 + 20:05 定时。
#   不跑 compute_runner（期货 accuracy 已在本步算，export 直接读 DB，与 pipeline futures DO_COMPUTE=0 一致）。
#
# 进程互斥：
#   - futures 锁 /tmp/trade_futures.lock（--nb 非阻塞）：防自身重复并发。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git，与 20:00 backfill / 20:07 etf /
#     update_all pipeline 共享，避免撞 .git/index.lock。20:00-20:07 密集时段 deploy.lock
#     排队，各自 ExitTimeOut 给足（plist 设 3600s）。
#
# 非交易日：默认跳过。force 模式可绕过（手动补测）。
#
# 用法：bash scripts/futures_backfill.sh [force]
# 日志：data/logs/futures_backfill_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/futures_backfill_${STAMP}.log"
LOCK="/tmp/trade_futures.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持 futures 锁重跑自己，FUTURES_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过。
if [ -z "${FUTURES_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env FUTURES_LOCKED=1 bash "$0" "$@"
fi

echo "=== futures_backfill.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh / intraday_snapshot.sh 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过期货采集（force 可绕过）" | tee -a "$LOG"
  echo "=== futures_backfill.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 期货 collect_daily(当日) + compute_accuracy（镜像 runner.py futures step）
#    collect_daily 返回空 = 源未发布/非交易日 -> 跳过 deploy。
echo "-> 采集期货机构持仓当日 + compute_accuracy ..." | tee -a "$LOG"
"$PY" -c "
from app.calendar import last_trading_day
from app.collector import futures_position as fp
from app.compute.futures_position import compute_accuracy
import sys
date = last_trading_day()
if hasattr(date, 'strftime'):
    date = date.strftime('%Y%m%d')
try:
    res = fp.collect_daily(date)
except Exception as e:
    print(f'[futures] {date} collect_daily exc: {e}')
    sys.exit(1)
if not res:
    print(f'[futures] {date}: no data (源未发布/非交易日)')
    sys.exit(1)
combos = sum(len(v) for v in res.values())
vlist = ', '.join(sorted(res.keys()))
print(f'[futures] {date}: collected {combos} variety-role combos ({vlist})')
try:
    n = compute_accuracy(date=date)
    print(f'[futures] accuracy: {n} rows')
except Exception as e:
    print(f'[futures] accuracy fail: {e}')
sys.exit(0)
" 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]:-1}
echo "期货采集退出码=${COLLECT_RC}(0=有新数据,非0=源未发布/为空)" | tee -a "$LOG"

if [ "$COLLECT_RC" -ne 0 ]; then
  echo "期货无新数据（源未发布或为空），跳过推送" | tee -a "$LOG"
  echo "=== futures_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
  exit 0
fi

# 2) 有新数据 -> 持 deploy 锁推送（串行化 git，阻塞排队；20:00-20:07 密集时段等 backfill 释放）
echo "-> 持 deploy 锁推送（串行化 git，可能排队等 backfill/etf）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" futures 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

echo "=== futures_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"
exit "$DEPLOY_RC"
