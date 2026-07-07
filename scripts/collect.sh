#!/usr/bin/env bash
# collect.sh — 采集数据（手动 / 定时）
#
# 调 app.scheduler.run()：refresh_trade_dates → is_trading_day 闸门 →
# 采集 → 计算 → 告警检查（step 1-8）。scheduler 内部各 step 已 try/except，
# 部分失败不阻塞整体。
#
# 用法：
#   bash scripts/collect.sh          # 今天
#   bash scripts/collect.sh 20260706 # 指定日期（透传给 scheduler）
#
# 日志：tee 到 data/logs/collect_YYYYMMDD_HHMM.log
# 退出码：scheduler 退出码（部分 step 失败仍返 0，scheduler 不抛）。
set -u  # 未定义变量报错
# 注意：故意不 set -e —— scheduler 内部 try/except 已兜底，部分失败应继续不中断脚本。

REPO=/Users/linhuichen/code/trade
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/collect_${STAMP}.log"

mkdir -p "$LOGDIR"
cd "$REPO"  # scheduler 用相对 import + WorkingDirectory

echo "=== collect.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "调度日期参数：${1:-（今天）}"
echo "日志：$LOG"
echo

# 透传可选日期参数
if [ $# -ge 1 ]; then
  "$PY" -m app.scheduler "$1" 2>&1 | tee "$LOG"
else
  "$PY" -m app.scheduler 2>&1 | tee "$LOG"
fi
RC=${PIPESTATUS[0]}

echo
echo "=== collect.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ==="
exit $RC
