#!/usr/bin/env bash
# us_stock_morning.sh - 美股早采任务（05:00 launchd 触发，美股 04:00 收盘后 1 小时）
#
# 根因：新浪 index_us_stock_sina 历史源对美股指数发布不同步（.DJI/.IXIC/.NDX 停 7-27
# 只有 .INX 有 7-28），backfill_evening 02:00 跑早于美股收盘 + require_today=False
# 距今≤3天不补 = 不触发美股补采，致 overview us_dji_date 滞后 2 天。
#
# 方案A：独立早采任务 05:00，换源新浪实时 gb_$（4 只全有完整 OHLC+prev_close+EDT 日期），
# 新浪历史 index_us_stock_sina 兜底。采集成功后跑 deploy.sh 全量 export+push。
#
# 用法：bash scripts/us_stock_morning.sh
# 日志：data/logs/us_stock_morning_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade-data}"   # §9 cwd=trade-data 让 db.py 读主库
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
# 脚本在 trade/scripts/（trade-data/scripts 是 symlink 指向 trade/scripts）
SCRIPT="$GIT_REPO/scripts/us_stock_morning.py"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/us_stock_morning_${STAMP}.log"

mkdir -p "$LOGDIR"

echo "=== us_stock_morning.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO" | tee -a "$LOG"

# 刷新 schedule_stats.json：脚本退出时(trap EXIT)调用 gen_schedule_stats.py，
# 确保 us_stock 的 last_run/last_exit 及时更新。2026-07-30 修复：us_stock_morning.sh
# 新增时漏调 gen_stats，致 schedule_stats.json us_stock 字段 exit=null/dur=null。
# 与 rzhb_backfill.sh L56-60 / futures_backfill.sh / lhb_backfill.sh 一致。
refresh_stats() {
  "$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" | tail -1 \
    || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"
}
trap refresh_stats EXIT

# 1) 采集美股 4 指数（新浪实时 gb_$ 主 + 新浪历史兜底），upsert 到 index_daily
echo "-> 采集美股指数 ..." | tee -a "$LOG"
"$PY" "$SCRIPT" 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "采集退出码=$COLLECT_RC" | tee -a "$LOG"

if [ "$COLLECT_RC" != "0" ]; then
  echo "✗ 采集失败（退出码 $COLLECT_RC），跳过 deploy" | tee -a "$LOG"
  echo "=== us_stock_morning.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$COLLECT_RC ===" | tee -a "$LOG"
  exit "$COLLECT_RC"
fi

# 2) deploy.sh 全量 export+push（幂等，只 global-all.json/overview.json 变化进 commit）
#    时段闸门：deploy.sh 内置 09:30-15:30 盘中拒跑（05:00 不触发）
echo "-> 跑 deploy.sh 全量 export+push ..." | tee -a "$LOG"
bash "$GIT_REPO/scripts/deploy.sh" 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
echo "deploy 退出码=$DEPLOY_RC" | tee -a "$LOG"

echo "=== us_stock_morning.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 采集=$COLLECT_RC deploy=$DEPLOY_RC ===" | tee -a "$LOG"
# deploy 失败不阻塞（采集已成功，下次 deploy 会带上）
exit 0
