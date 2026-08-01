#!/bin/bash
# public_fund_full.sh - 公募基金凌晨补充链路（launchd 02:00 定时）
#
# 调 python -m app.collector.public_fund full（全量9000只×2子页, ~5.25h）
# + export JSON + 持 deploy 锁推送 static-site/data/public_fund_*.json
#
# 时点: 每日 02:00（凌晨补充链路，在 quarterly 03:00 前启动）。
# 5.25h 跑到约 07:15，期间 quarterly 03:00/04:00 撞 python 内 public_fund.lock 跳过，
# quarterly 08:00 兜槽在 full 跑完后真跑。
#
# 进程互斥:
#   - full 锁 /tmp/trade_public_fund_full.lock（--nb 非阻塞）: 防自身重复并发
#   - python 内 public_fund.lock: 防 quarterly/full/daily 互相并发（共用，撞锁跳过）
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）: 串行化 git
#
# 非交易日: 默认跳过（季报披露日是工作日，凌晨跑前一日数据）。force 可绕过。
#
# 用法: bash scripts/public_fund_full.sh [force]
# 日志: data/logs/public_fund_full_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，5.25h 长任务必须防休眠）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/public_fund_full_${STAMP}.log"
LOCK="/tmp/trade_public_fund_full.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装: 首次调用经 with_lock.py --nb 持 full 锁重跑自己，PF_FULL_LOCKED=1 防递归。
if [ -z "${PF_FULL_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env PF_FULL_LOCKED=1 bash "$0" "$@"
fi

echo "=== public_fund_full.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过公募基金全量补充（force 可绕过）" | tee -a "$LOG"
  echo "=== public_fund_full.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 全量补充采集（9000只×2子页, ~5.25h）+ 导出 JSON
echo "-> 采集公募基金全量（9000只×2子页, ~5.25h）+ 导出 JSON ..." | tee -a "$LOG"
"$PY" -m app.collector.public_fund full 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "公募基金全量采集退出码=$COLLECT_RC" | tee -a "$LOG"
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_full] full 失败 exit=$COLLECT_RC" | tee -a "$LOG"
fi

# 2) 持 deploy 锁推送（deploy.sh public-fund 重新 export + git push + R2 上传）
echo "-> 持 deploy 锁推送（串行化 git）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" public-fund 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

# 综合退出码
FINAL_RC=0
[ "$COLLECT_RC" -ne 0 ] && FINAL_RC=$COLLECT_RC
[ "$DEPLOY_RC" -ne 0 ] && FINAL_RC=$DEPLOY_RC

echo "=== public_fund_full.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json + 独立 push
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit "$FINAL_RC"
