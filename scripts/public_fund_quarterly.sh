#!/bin/bash
# public_fund_quarterly.sh - 公募基金季度主链路（launchd 03:00 定时）
#
# 调 python -m app.collector.public_fund quarterly（5汇总+top1000×2子页+8指标, ~35min）
# + export JSON + 持 deploy 锁推送 static-site/data/public_fund_*.json
#
# 时点: 每日 03:00（主槽）+ 04:00（兜槽1）+ 08:00（兜槽2）。
# 季报披露（1/22, 4/22, 7/22, 10/22）次日才真有新数据，但 collector 无季报期判断，
# 每天都跑（幂等，无新数据 fetch 返回 0 行）。03:00/04:00 撞 full 02:00 跑 5.25h 锁会跳过
# （public_fund.py 内部 public_fund.lock nonblock），08:00 兜槽在 full 07:15 跑完后真跑。
#
# 进程互斥:
#   - quarterly 锁 /tmp/trade_public_fund_quarterly.lock（--nb 非阻塞）: 防自身重复并发
#   - python 内 public_fund.lock: 防 quarterly/full/daily 互相并发（共用，撞锁跳过）
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）: 串行化 git，与 update_all/backfill 共享
#
# 非交易日: 默认跳过。force 可绕过（手动补测）。
#
# 用法: bash scripts/public_fund_quarterly.sh [force]
# 日志: data/logs/public_fund_quarterly_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/public_fund_quarterly_${STAMP}.log"
LOCK="/tmp/trade_public_fund_quarterly.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装: 首次调用经 with_lock.py --nb 持 quarterly 锁重跑自己，PF_QUARTERLY_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过。
if [ -z "${PF_QUARTERLY_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env PF_QUARTERLY_LOCKED=1 bash "$0" "$@"
fi

echo "=== public_fund_quarterly.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh / intraday_snapshot.sh / etf_nt backfill 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过公募基金季度采集（force 可绕过）" | tee -a "$LOG"
  echo "=== public_fund_quarterly.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 季度全量采集（5汇总+top1000×2子页+8指标, ~35min）+ 导出 JSON
#    python 内 public_fund.lock 防并发；采集器写 DB + dump static-site/data/public_fund_*.json。
echo "-> 采集公募基金季度（5汇总+top1000+8指标, ~35min）+ 导出 JSON ..." | tee -a "$LOG"
"$PY" -m app.collector.public_fund quarterly 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "公募基金季度采集退出码=$COLLECT_RC" | tee -a "$LOG"
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_quarterly] quarterly 失败 exit=$COLLECT_RC" | tee -a "$LOG"
fi

# 2) 持 deploy 锁推送（串行化 git，阻塞排队；deploy.sh public-fund 重新 export 全量 JSON + git push）
#    deploy.sh 幂等: export 生成相同 JSON -> git add 无新变更 -> 跳过 commit -> push up-to-date。
echo "-> 持 deploy 锁推送（串行化 git，可能排队等 full/other backfill）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" public-fund 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

# 综合退出码（collector 或 deploy 任一失败即非0）
FINAL_RC=0
[ "$COLLECT_RC" -ne 0 ] && FINAL_RC=$COLLECT_RC
[ "$DEPLOY_RC" -ne 0 ] && FINAL_RC=$DEPLOY_RC

echo "=== public_fund_quarterly.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json（仿 etf_nt/lhb backfill，gen_stats 读完整"开始+结束"对）
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"

# 独立 push schedule_stats.json 到 main（gen_stats 后立即 push 绕过 deploy.sh 时序）
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit "$FINAL_RC"
