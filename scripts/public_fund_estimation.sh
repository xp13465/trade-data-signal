#!/bin/bash
# public_fund_estimation.sh - 公募基金盘中实时估算采集（launchd 10:00/11:00/13:30/14:30 定时）
#
# 调 python -m app.collector.public_fund fetch-estimation（fund_value_estimation_em 盘中实时估算, ~5s）
# 只采 fund_estimation_nav 表, 不跑 export/deploy（盘中避免撞 intraday-snapshot 定时任务推 main）
#
# 时点: 盘中 10:00/11:00/13:30/14:30 四档（fetch_estimation docstring 设计）。
# fund_value_estimation_em 盘中(09:30-15:00)返回全市场基金当日实时估算净值/涨跌,
# 盘后/非交易日返回 None（正常, 不阻塞）。避开 09:30 开盘波动 + 15:00 收盘（估算可能已无）。
#
# 进程互斥:
#   - estimation 锁 /tmp/trade_public_fund_estimation.lock（--nb 非阻塞）: 防自身重复并发
#   - 不持 python 内 public_fund.lock（fetch-estimation 命令不持锁, 轻量~5s, 不和 daily/quarterly/full 撞）
#
# 非交易日: 默认跳过。force 可绕过。
#
# 用法: bash scripts/public_fund_estimation.sh [force]
# 日志: data/logs/public_fund_estimation_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/public_fund_estimation_${STAMP}.log"
LOCK="/tmp/trade_public_fund_estimation.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装: 首次调用经 with_lock.py --nb 持 estimation 锁重跑自己，PF_EST_LOCKED=1 防递归。
if [ -z "${PF_EST_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env PF_EST_LOCKED=1 bash "$0" "$@"
fi

echo "=== public_fund_estimation.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过盘中实时估算采集（force 可绕过）" | tee -a "$LOG"
  echo "=== public_fund_estimation.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 盘中实时估算采集（fund_value_estimation_em ~5s, 盘后/非交易日返回0正常）
echo "-> 采集盘中实时估算（~5s）..." | tee -a "$LOG"
"$PY" -m app.collector.public_fund fetch-estimation 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "盘中实时估算采集退出码=$COLLECT_RC" | tee -a "$LOG"
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_estimation] fetch-estimation 失败 exit=$COLLECT_RC" | tee -a "$LOG"
fi

echo "=== public_fund_estimation.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"

# 综合退出码
exit "$COLLECT_RC"
