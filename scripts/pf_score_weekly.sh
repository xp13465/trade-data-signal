#!/bin/bash
# pf_score_weekly.sh - 公募基金评分引擎周频 (launchd 周日 03:17 全量27409只)
#
# 调 python -c compute_all_scores(top_n=None, resume=True) + export_fund_score.py + upload-fund-score
#   全量27409只~2.3h (实测头部2000只~2min, 全量含偏股基金完整评分较慢)
#
# 进程互斥:
#   - shell 层 fcntl 互斥锁 /tmp/pf-score-weekly.lock (重复跑自动跳过)
#   - python public_fund.lock 不持 (评分只读 DB, 不和 stage0-* 采集撞)
#
# 时点: 周日 03:17 (避开 update_all 17:50 / intraday-snapshot 每10min / stage0-* 凌晨任务)
# 日志: data/logs/pf-score-weekly.log (append)
set -uo pipefail
# 防脚本运行期间 mac 休眠 (2.3h 长任务必须防休眠)
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade-data"
PY="$REPO/.venv/bin/python"
LOG="$REPO/data/logs/pf-score-weekly.log"
LOCK="/tmp/pf-score-weekly.lock"

mkdir -p "$(dirname "$LOG")"
cd "$REPO"

# fcntl 互斥锁(非阻塞, 持不到=已有在跑=跳过)
"$PY" -c "import fcntl,sys
f=open('$LOCK','w')
try:
    fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.exit(0)
except BlockingIOError:
    sys.exit(1)" \
  || { echo "=== $(date '+%F %T') pf-score-weekly lock busy, skip ===" >>"$LOG"; exit 0; }

{
echo "=== $(date '+%F %T') pf-score-weekly start (全量27409只) ==="
"$PY" -c "from app.collector.public_fund import compute_all_scores; compute_all_scores(top_n=None, resume=True)"
RC1=$?
"$PY" "$REPO/scripts/export_fund_score.py" --top-n 2000
RC2=$?
rsync -a --checksum "$REPO/static-site/data/fund_score"* "/Users/linhuichen/code/trade/static-site/data/" 2>/dev/null || true
"$PY" "$REPO/scripts/upload_r2.py" upload-fund-score
RC3=$?
# D1 全量同步（#79 方案C step3: /api/fund_score 数据源; 失败告警不阻塞评分主流程）
bash /Users/linhuichen/code/trade/scripts/sync_fund_score_to_d1.sh || \
  echo "⚠ sync_fund_score_to_d1 失败（不阻塞主流程, D1 数据滞后一轮）"
echo "=== $(date '+%F %T') pf-score-weekly end compute=$RC1 export=$RC2 upload=$RC3 ==="
exit $RC1
} >>"$LOG" 2>&1
