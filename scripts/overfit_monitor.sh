#!/usr/bin/env bash
# overfit_monitor.sh - 过拟合监控每日打点(交易日 21:40 定时, B 档 2026-08-15)
#
# 交易日 21:40 跑: 重算准确率双口径(回测+实盘)每日打点 + 4 维过拟合指标 + 综合风险分,
# 命中预警(风险分>=60/连续5日攀升/象限退化/样本外衰减/参数尖峰)则 notify.py 发邮件+Telegram+飞书(24h去重)。
#
# 非交易日: 跳过打点(指数/信号数据不更新), 不产生新预警。传 force 绕过闸门强制跑(周末补数据)。
#
# 时点选择(§14): 21:40 避开盘后定时任务(17:50 update_all / 20:05 futures / 20:07 etf /
#   20:30 daily-summary / 20:40 daily-brief / 21:00 backfill-evening / 21:30 etf-national-team / 22:00)。
# 依赖: signal_kelly_trades.json(回测) + signal_daily/index_daily(实盘) + indicators.yaml(指数大类)。
#
# 用法: bash scripts/overfit_monitor.sh [force]
# 日志: data/logs/overfit_monitor_YYYYMMDD_HHMM.log
set -u

PY=/Users/linhuichen/code/trade-data/.venv/bin/python
REPO=/Users/linhuichen/code/trade-data
LOGDIR=$REPO/data/logs
mkdir -p "$LOGDIR"
cd "$REPO"

# 交易日闸门(非交易日跳过打点; 传 force 强制跑供周末补数据)
if [ "${1:-}" != "force" ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 非交易日, 跳过过拟合监控打点" >> "$LOGDIR/overfit_monitor_$(date +%Y%m%d).log"
    exit 0
  fi
fi

STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/overfit_monitor_${STAMP}.log"
echo "==== overfit_monitor 打点开始 $(date '+%F %T') ====" > "$LOG"
# 打点(不打 --dry-run: 正常发送时若触发预警会真发, 但有 dedup 防轰炸)
"$PY" scripts/overfit_monitor.py >> "$LOG" 2>&1
RC=$?
echo "==== overfit_monitor 结束 rc=$RC $(date '+%F %T') ====" >> "$LOG"
exit $RC
