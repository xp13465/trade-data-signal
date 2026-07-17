#!/usr/bin/env bash
# update_all.sh — 一键更新（采集 + 部署 + 信号检测）
#
# 顺序：collect.sh → deploy.sh → check_signals.sh。
# **无论采集成功失败都继续 deploy**：用现有（可能部分更新）数据导出推送，
# 公网保持最新可用状态，但记录 collect 退出码供排查。
# **check_signals 失败不阻塞**：邮件发送失败 / 配置缺失仅记日志，不影响公网部署。
#
# 用法：
#   bash scripts/update_all.sh
#
# 日志：tee 到 data/logs/update_all_YYYYMMDD_HHMM.log
# 退出码：deploy.sh 退出码（最终公网状态）；collect / check_signals 失败仅记日志不改变退出码。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade}"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/update_all_${STAMP}.log"

mkdir -p "$LOGDIR"

echo "=== update_all.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 1. 采集（不中断流程）
echo "→ [1/3] 运行 collect.sh ..." | tee -a "$LOG"
bash "$REPO/scripts/collect.sh" 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "⚠ collect.sh 退出码 ${COLLECT_RC:-?}(部分失败),仍继续 deploy 用现有数据推送" | tee -a "$LOG"
else
  echo "✓ collect.sh 完成" | tee -a "$LOG"
fi

echo | tee -a "$LOG"

# 2. 部署（无论采集成败都跑）
echo "→ [2/3] 运行 deploy.sh ..." | tee -a "$LOG"
bash "$REPO/scripts/deploy.sh" 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}

echo | tee -a "$LOG"

# 3. 信号检测 + 邮件（失败不阻塞）
echo "→ [3/3] 运行 check_signals.sh ..." | tee -a "$LOG"
bash "$REPO/scripts/check_signals.sh" 2>&1 | tee -a "$LOG"
SIGNAL_RC=${PIPESTATUS[0]}
if [ "$SIGNAL_RC" -ne 0 ]; then
  echo "⚠ check_signals.sh 退出码 ${SIGNAL_RC:-?}(邮件发送失败或配置缺失),不影响公网部署" | tee -a "$LOG"
else
  echo "✓ check_signals.sh 完成" | tee -a "$LOG"
fi

echo | tee -a "$LOG"
echo "=== update_all.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
echo "collect 退出码=$COLLECT_RC  deploy 退出码=$DEPLOY_RC  check_signals 退出码=$SIGNAL_RC" | tee -a "$LOG"

exit "$DEPLOY_RC"
