#!/bin/bash
# push_schedule_stats.sh - 独立推送 schedule_stats.json 到 main（绕过 deploy.sh 时序矛盾）
#
# 根因（2026-07-30 方案C+R2 根治）：
#   deploy.sh L216 for 循环 git add schedule_stats.json 时，gen_schedule_stats.py
#   尚未运行（7 任务脚本在 gen_stats 之前 push / intraday_snapshot push 块在 gen_stats
#   之前），致 push 的 schedule_stats.json 是上一轮旧版 -> 前端"执行统计"滞后一轮。
#   原"方案A 移到结尾调 gen_stats"只解决了 gen_stats 时序，但 push 仍依赖 deploy.sh
#   下一轮才带最新版 -> 滞后 1 轮（intraday 10min / backfill 次日）。
#
# 方案C+R2：gen_stats 后立即独立 push schedule_stats.json，绕过 deploy.sh 时序。
#   - 7 任务脚本（us_stock/rzhb/futures/lhb/etf/update_all/update_lab）结尾 gen_stats 后调本脚本
#   - intraday_snapshot.sh 选项2：gen_stats 后调本脚本（实时性最佳，当轮 schedule_stats 当轮上线）
#   - deploy.sh L216 移除 schedule_stats（不再由 deploy.sh push，避免和本脚本双写撞 git lock）
#
# 机制（阶段3：R2 上传，替代 git push worktree + deploy.lock + rebase 兜底）：
#   - gen_stats 刷新本地 schedule_stats.json，upload-data-files 上传到 R2 + purge_cache
#   - 无需 worktree/git push（前端走 R2，static-site/data/ 仍 tracked 作兜底）
#   - R2 上传失败 notify.py --severe 告警（让 schedule_monitor 48h 监控发现）
#
# 用法：bash scripts/push_schedule_stats.sh
# 日志：data/logs/push_schedule_stats_YYYYMMDD_HHMM.log
# 退出码：0 = push 成功 / 无变更跳过；非 0 = push 失败（gen_stats 失败不在此脚本职责，
#         源文件缺失直接 exit 1 不 push 旧版）
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/push_schedule_stats_${STAMP}.log"
export LOG   # 让子 bash -c (commit+push 段) 继承 LOG，tee -a 可用

mkdir -p "$LOGDIR"
cd "$REPO"

echo "=== push_schedule_stats.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO" | tee -a "$LOG"

# 源文件校验：gen_schedule_stats.py 未运行或失败致 schedule_stats.json 缺失 -> 不 push 旧版
SRC="$REPO/static-site/data/schedule_stats.json"
if [ ! -f "$SRC" ]; then
  echo "✗ 源文件不存在：$SRC（gen_schedule_stats.py 未运行？），跳过 push" | tee -a "$LOG" >&2
  exit 1
fi
echo "源文件：$SRC ($(stat -f '%z' "$SRC") bytes, mtime $(stat -f '%Sm' "$SRC"))" | tee -a "$LOG"

# 上传 schedule_stats.json 到 R2（阶段3：替代 git push，前端走 R2）
# gen_stats 已刷新本地 schedule_stats.json，upload-data-files 上传到 R2 + purge_cache。
# R2 上传失败发告警邮件（notify.py --severe），让 schedule_monitor 发现。
ALERT_TIME=$(date '+%m-%d %H:%M')
echo "-> 上传 schedule_stats.json 到 R2（upload-data-files + purge）..." | tee -a "$LOG"
if ! "$PY" "$REPO/scripts/upload_r2.py" upload-data-files schedule_stats.json 2>&1 | tee -a "$LOG"; then
  echo "✗ schedule_stats R2 上传失败，发告警邮件" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" \
    "[告警] schedule_stats R2上传失败 ${ALERT_TIME}" \
    "push_schedule_stats R2 上传失败，前端"执行统计"将读旧数据，需手动补刷: bash scripts/upload_r2.py upload-data-files schedule_stats.json<br>日志: $LOG" \
    --severe --from-prefix "[告警]" \
    --dedup-key schedule_stats_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  exit 1
fi
echo "✓ schedule_stats.json R2 上传完成" | tee -a "$LOG"

echo "=== push_schedule_stats.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
