#!/usr/bin/env bash
# check_data_gap_alerts.sh - 采集数据缺口/停更告警检测(交易日 22:35 定时, 2026-08-27)
#
# 背景(告警兜底批 #103 方案A + S2 用户拍板): 上游源停发超窗口后留下的数据洞
# 「不自愈」目前监控零捕获。本脚本=launchd com.trade.check-data-gap 的包装, 调
# check_data_gap_alerts.py 四检查器(north_hole/north_stale/etf_accum_nav_gap/
# width_freshness), 命中即走 notify.py 既有通道发邮件(SEVERE 另写 alerts/latest.md)。
# 检测器细节/阈值来源/two-way 自测见 scripts/check_data_gap_alerts.py 头注释与
# docs/ops/data-gap-alert-batch-20260827.md。
#
# 时点选择依据(§14): 22:35 ——
#   当日晚链全部完成(backfill_evening 21:00 / etf_national_team 21:30 / overfit 21:40
#   / 信号邮件 22:00)后检测, 数据为收盘定型终态; 与相邻槽位错峰 ≥35min;
#   位于 23:00 安全窗前且秒级完成不抢资源; 不推 main 不写业务 DB。
#   pmset 无需新增唤醒: 既有 wakepoweron 工作日 17:48, 机器持续活跃至 21:40 之后
#   (overfit-monitor 同款依赖), 22:35 落在活跃区间内(实测主机该时段未入睡)。
# 非交易日: 跳过(序列静止无新缺口; 长假期间历史洞不会突变); 传 force 绕过闸门补跑。
#
# 用法: bash scripts/check_data_gap_alerts.sh [force]
# 日志: data/logs/check_data_gap_launchd.log(固定名 append, 标准开始/结束行供
#   gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读, 同 overfit_monitor 先例)
set -u

export REPO="${REPO:-/Users/linhuichen/code/trade-data}"
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
mkdir -p "$LOGDIR"
cd "$REPO"
LOG="$LOGDIR/check_data_gap_launchd.log"

run_to() {
  local t="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$t" "$@"
  else
    perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"
  fi
}

# 交易日闸门(fail-open 默认跑, 防日历源异常静默停更)
if [ "${1:-}" != "force" ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "$(date '+%F %T') 非交易日, 跳过数据缺口检测" >> "$LOG"
    exit 0
  fi
fi

echo "=== check_data_gap_alerts.sh 开始 $(date '+%F %T') ===" >> "$LOG"

RC=0
# 相对路径走 trade-data/scripts symlink(merge 即生效, 与全站任务同哲学)
run_to 300 "$PY" scripts/check_data_gap_alerts.py --repo "$REPO" >> "$LOG" 2>&1
RC=$?
[ "$RC" -ne 0 ] && echo "✗ 数据缺口检测器异常退出 rc=${RC}(自身故障也是告警)" >> "$LOG"

echo "=== check_data_gap_alerts.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"
