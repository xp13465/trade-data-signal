#!/bin/bash
# backfill_indices.sh - 晚间轻量补采兜底（launchd 18:00 定时）
# 只做：校验补采缺失指数 + (有补则)重算情绪分 + 推送。不全量采集（几十秒）。
# 兜底场景：15:33 早跑时三源都没今日数据 -> 18:00 三源已更新，补上。
# 详见 app/collector/index_backfill.py 的 main()。
set -uo pipefail
REPO="/Users/linhuichen/code/trade"
cd "$REPO"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$REPO/data/logs/backfill_${STAMP}.log"
mkdir -p "$REPO/data/logs"

echo "=== backfill_indices.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
"$REPO/.venv/bin/python" -c "from app.collector.index_backfill import main; main()" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "=== backfill_indices.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"
exit $RC
