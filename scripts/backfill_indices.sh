#!/bin/bash
# backfill_indices.sh - 凌晨+晚间轻量补采兜底（launchd 02:00+20:00 定时）
# 只做：校验补采缺失指数 + (有补则)重算情绪分 + 推送。不全量采集（几十秒）。
# 兜底场景：15:33 早跑时三源都没今日数据 -> 20:00 三源已更新，补上；02:00 凌晨再兜一次确保次日清晨数据齐全。
# 详见 app/collector/index_backfill.py 的 main()。
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &
REPO="${REPO:-/Users/linhuichen/code/trade}"
cd "$REPO"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$REPO/data/logs/backfill_${STAMP}.log"
mkdir -p "$REPO/data/logs"

echo "=== backfill_indices.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
"$REPO/.venv/bin/python" -c "from app.collector.index_backfill import main; main()" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "=== backfill_indices.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"
exit $RC
