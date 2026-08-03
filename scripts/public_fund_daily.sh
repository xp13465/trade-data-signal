#!/bin/bash
# public_fund_daily.sh - 公募基金日更（launchd 16:30 定时）
#
# 调 python -m app.collector.public_fund daily（日更净值+盘中估算+三指数刷新+估算仓位变化, ~15s）
# + 持 deploy 锁推送 static-site/data/public_fund_*.json
#
# 时点: 每交易日 16:30（主槽，收盘后 1h）+ 17:00（兜槽）。
# akshare fund_open_fund_daily_em 约 16:00-17:00 发布当日净值，16:30 采可能部分，
# 17:00 兜槽补完整。轻量 15s，幂等覆盖重采。
# pipeline_daily 含 fetch_index_daily(三指数baostock ~5s), 确保 fund_index_daily 每日更新,
# _compute_position_estimate 有最新指数算当日预估仓位(2026-08-02 根治: 原不调致算法缺当日r_hs300跳过)。
#
# 进程互斥:
#   - daily 锁 /tmp/trade_public_fund_daily.lock（--nb 非阻塞）: 防自身重复并发
#   - python 内 public_fund.lock: 防 quarterly/full/daily 互相并发（共用，撞锁跳过）
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）: 串行化 git
#
# 非交易日: 默认跳过。force 可绕过。
#
# 用法: bash scripts/public_fund_daily.sh [force]
# 日志: data/logs/public_fund_daily_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/public_fund_daily_${STAMP}.log"
LOCK="/tmp/trade_public_fund_daily.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装: 首次调用经 with_lock.py --nb 持 daily 锁重跑自己，PF_DAILY_LOCKED=1 防递归。
if [ -z "${PF_DAILY_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env PF_DAILY_LOCKED=1 bash "$0" "$@"
fi

echo "=== public_fund_daily.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过公募基金日更（force 可绕过）" | tee -a "$LOG"
  echo "=== public_fund_daily.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 日更采集（fund_open_fund_daily_em ~23738 行 + 估算仓位变化, ~8s）
#    pipeline_daily 不调 export_json_files（只更新 fund_daily_nav 表），需手动 export 推 JSON。
echo "-> 采集公募基金日更净值（~8s）..." | tee -a "$LOG"
"$PY" -m app.collector.public_fund daily 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "公募基金日更采集退出码=$COLLECT_RC" | tee -a "$LOG"
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_daily] daily 失败 exit=$COLLECT_RC" | tee -a "$LOG"
fi

# 2) 导出 5 类 JSON + 3) deploy 推送
# 修复a(2026-08-03): daily 撞锁(python sys.exit(2))或其他失败时, 不 export+deploy,
# 避免推旧数据上线(原 bug: 撞锁 exit0 当成功, 继续 export+deploy 旧 position_estimate.json)
EXPORT_RC=0
DEPLOY_RC=0
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_daily] daily 失败/撞锁跳过 exit=$COLLECT_RC, 跳过 export+deploy 避免推旧数据上线" | tee -a "$LOG"
else
  echo "-> 导出 5 类 JSON ..." | tee -a "$LOG"
  "$PY" -m app.collector.public_fund export 2>&1 | tee -a "$LOG"
  EXPORT_RC=${PIPESTATUS[0]}
  echo "导出退出码=$EXPORT_RC" | tee -a "$LOG"
  if [ "$EXPORT_RC" -eq 0 ]; then
    # 持 deploy 锁推送（deploy.sh public-fund 重新 export + git push + R2 上传）
    echo "-> 持 deploy 锁推送（串行化 git）..." | tee -a "$LOG"
    "$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" public-fund 2>&1 | tee -a "$LOG"
    DEPLOY_RC=${PIPESTATUS[0]}
    [ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"
  else
    echo "[public_fund_daily] export 失败 exit=$EXPORT_RC, 跳过 deploy" | tee -a "$LOG"
  fi
fi

# 综合退出码
FINAL_RC=0
[ "$COLLECT_RC" -ne 0 ] && FINAL_RC=$COLLECT_RC
[ "$EXPORT_RC" -ne 0 ] && FINAL_RC=$EXPORT_RC
[ "$DEPLOY_RC" -ne 0 ] && FINAL_RC=$DEPLOY_RC

echo "=== public_fund_daily.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json + 独立 push
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit "$FINAL_RC"
