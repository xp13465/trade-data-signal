#!/bin/bash
# restore-launchd.sh —— 恢复阶段4c 停用的本机业务 launchd 任务(云上 systemd 已接管的 35 个)
#
# 用途:2026-09-13 阶段4c 停用本机 35 个业务 launchd(云上 36 个 systemd timer 已接管采集/export/deploy/告警,
#       避免本机与云上双写 R2 打架)。本脚本用于应急把停掉的 35 个 launchd 一次性恢复(如云上故障回切本机)。
#
# 用法:bash scripts/restore-launchd.sh
#   - 逐个 label 检查:已 loaded 跳过;原 plist 缺失则从备份目录(~/.Library/LaunchAgents.backup-20260913)恢复;
#     然后 launchctl bootstrap 重新加载。
#   - 幂等:重复跑只会补加载仍未 loaded 的 label,不会重复加载已 loaded 的。
#
# 前置:备份目录 ~/Library/LaunchAgents.backup-20260913/ 含全部 35 个 plist(2026-09-13 备份)。
#
# 注意:本脚本只恢复「停用」的 35 个业务任务,不动本机专属的留用任务
#       (feishu-listener/thinking-proxy/sensenova-healthcheck/agent-inbox-watcher/token-cache-stats/env/self-backup)。

set -u

BACKUP_DIR="$HOME/Library/LaunchAgents.backup-20260913"
DEFAULT_DIR="$HOME/Library/LaunchAgents"
# check-data-gap 的 plist 在 code/trade/launchd/ 目录(其余 34 个在 ~/Library/LaunchAgents/)
SPECIAL_DIR="/Users/linhuichen/code/trade/launchd"

# 35 个停用 label 清单(与 run-task-manually.sh 同步)
LABELS=(
com.trade.etf-track-index
com.trade.pf-score-weekly
com.trade.gold-night
com.trade.pf-stage0-risk
com.trade.schedule-monitor
com.trade.lab-auto
com.trade.etf-national-team
com.trade.update-all
com.trade.nextday-plan
com.trade.public-fund-full
com.trade.pf-stage0-nav
com.trade.pf-score-daily
com.trade.intraday-snapshot
com.trade.kelly-intraday-rerun
com.trade.pf-stage0-overview
com.trade.overfit-monitor
com.trade.fetch-news
com.trade.brief-push
com.trade.daily-brief
com.trade.public-fund-daily
com.trade.futures-backfill
com.trade.pf-stage0-manager
com.trade.s06-snapshot
com.trade.public-fund-quarterly
com.trade.public-fund-estimation
com.trade.ab-direction-anchor
com.trade.backfill-evening
com.trade.fapi-daily
com.trade.us-stock-morning
com.trade.self-heal
com.trade.daily-summary-supplement
com.trade.rzhb-backfill
com.trade.lhb-backfill
com.trade.check-data-gap
com.trade.turnover-backfill
)

[ -d "$BACKUP_DIR" ] || { echo "[FAIL] 备份目录不存在: $BACKUP_DIR"; exit 1; }

ok=0; skip=0; fail=0
for label in "${LABELS[@]}"; do
  # 已 loaded 跳过(幂等)
  if launchctl list | grep -qE "^[^[:space:]]*[[:space:]]+[^[:space:]]*[[:space:]]+$label\$"; then
    echo "[skip] $label 已 loaded"
    skip=$((skip+1))
    continue
  fi

  # 确定 plist 原始路径
  if [ "$label" = "com.trade.check-data-gap" ]; then
    plist="$SPECIAL_DIR/$label.plist"
  else
    plist="$DEFAULT_DIR/$label.plist"
  fi

  # 原 plist 缺失 -> 从备份恢复
  if [ ! -f "$plist" ]; then
    bak="$BACKUP_DIR/$label.plist"
    if [ -f "$bak" ]; then
      cp "$bak" "$plist" && echo "[restore-plist] $label" || { echo "[FAIL] $label 恢复 plist 失败"; fail=$((fail+1)); continue; }
    else
      echo "[FAIL] $label: 原 plist 缺失且备份也无 ($bak)"
      fail=$((fail+1))
      continue
    fi
  fi

  # bootstrap 重新加载
  if launchctl bootstrap gui/$(id -u) "$plist" 2>/tmp/restore-err.txt; then
    echo "[OK] $label"
    ok=$((ok+1))
  else
    echo "[FAIL] $label bootstrap 失败: $(cat /tmp/restore-err.txt)"
    fail=$((fail+1))
  fi
done

echo ""
echo "恢复完成: 成功 $ok / 已跳过 $skip / 失败 $fail"
[ "$fail" -eq 0 ] || exit 1
