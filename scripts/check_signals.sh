#!/usr/bin/env bash
# check_signals.sh — 检测当天买卖点信号 + 发邮件
#
# 调 scripts/check_signals.py：查 signal_daily 当日信号，有则发邮件（SMTP 163）。
# 无信号不发邮件。邮件发送失败不阻塞（log 错误，退出码非 0 但脚本不崩）。
#
# 用法：
#   bash scripts/check_signals.sh              # 今天
#   bash scripts/check_signals.sh 20260706     # 指定日期（透传给 check_signals.py）
#
# 日志：tee 到 data/logs/check_signals_YYYYMMDD_HHMM.log
# 退出码：check_signals.py 退出码（0=成功/无信号/占位密码跳过；2=邮件发送失败；非 0 不崩）。
set -u
# 不 set -e：邮件发送失败应记日志继续，不中断 update_all.sh。

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/check_signals_${STAMP}.log"

mkdir -p "$LOGDIR"

echo "=== check_signals.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ==="
echo "查询日期参数：${1:-（今天）}"
echo "日志：$LOG"
echo

# 透传可选日期参数
if [ $# -ge 1 ]; then
  "$PY" "$REPO/scripts/check_signals.py" --date "$1" 2>&1 | tee "$LOG"
else
  "$PY" "$REPO/scripts/check_signals.py" 2>&1 | tee "$LOG"
fi
RC=${PIPESTATUS[0]}

echo
echo "=== check_signals.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ==="
exit $RC
