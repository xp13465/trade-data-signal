#!/usr/bin/env bash
# turnover_backfill_skip_notify.sh - turnover 独立任务锁被占时的跳过通知(#82 C6)。
# 由 with_lock.py --on-skip 调用。参数 $1 = 锁路径。
# 复用 on_skip_notify.sh 模式, 文案专指 turnover(否则发"update_all 锁跳过"误导)。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
PY="$REPO/.venv/bin/python"
LOCKPATH="${1:-/tmp/trade_turnover.lock}"
DRY_FLAG=""
[ "${ON_SKIP_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
# 与主脚本同日志(固定 append), 写标准开始/结束行: 防 schedule_monitor 漏跑检查把"锁跳过"
# 误报为"turnover_backfill 未跑"(parse_last_run 看 start 行; 结束行配 退出码=0 让
# gen_schedule_stats standard 模式解析为一次正常结束, 不误报 exit 失败/进行中卡死)
LOG="$REPO/data/logs/turnover_backfill_launchd.log"

NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
echo "=== turnover_backfill.sh 开始 $NOW_STR (锁跳过, 另一实例在运行) ===" >> "$LOG"
BODY="turnover 独立任务锁跳过：检测到另一实例正在运行（锁 $LOCKPATH 被占），本次跳过未执行采集，当日 a_turnover_* 可能缺。<br>时间：$NOW_STR<br>如非预期（无其他实例在跑），检查 $LOCKPATH 是否残留或进程是否卡死。"

"$PY" "$REPO/scripts/notify.py" "[告警] turnover 独立任务锁跳过 $(date '+%m-%d %H:%M')" "$BODY" --severe \
  --from-prefix "[告警]" \
  --alert-issue "turnover 独立任务锁跳过：另一实例在运行或锁残留($LOCKPATH)" \
  $DRY_FLAG || true
echo "=== turnover_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 (锁跳过) ===" >> "$LOG"