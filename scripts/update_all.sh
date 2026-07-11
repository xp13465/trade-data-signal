#!/usr/bin/env bash
# update_all.sh - 一键更新（并发流水线版）
#
# 把原串行 collect->deploy->check 拆成 4 条并行 pipeline，各自独立
# 采集->计算->导出->commit+push，慢任务（mootdx 5072 只）不阻塞快核心上线：
#   core        快核心（指数/指标/情绪分），分钟级先上线
#   width       慢宽度（mootdx/行业宽度/全市场宽度），完成后覆盖上线
#   futures     独立（期货机构持仓），独立上线
#   stock_daily 后台死端（全 A 股日线备用源），不 export 不 push，不阻塞
# 各 pipeline 的 commit+push 经 flock /tmp/trade_deploy.lock 串行，避免 git index.lock 冲突。
#
# 非交易日：默认跳过采集仅 deploy+check_signals；传 force 绕闸门强制采集（周末补数据/校准）。
# 旧串行版备份：scripts/update_all_serial.sh。
#
# 用法：bash scripts/update_all.sh [force]
#   force: 绕过交易日闸门，非交易日也跑全量 pipeline（补漏跑数据/校准；当日快照采最近交易日值）
# 日志：data/logs/update_all_YYYYMMDD_HHMM.log（汇总，含各 pipeline 交错输出）
#       data/logs/pipeline_<name>_<STAMP>.log（各流水线独立日志）
# 退出码：core pipeline 退出码（核心看板公网状态）。
set -u

REPO=/Users/linhuichen/code/trade
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/update_all_${STAMP}.log"

mkdir -p "$LOGDIR"
cd "$REPO"

# 进程互斥：防止多个 update_all 并发跑（撞 mootdx/stock_daily progress 原子写 +
# 通达信/东财并发限流全 empty 空转）。fcntl.flock 非阻塞独占锁，持不到=已有在跑=跳过。
# 自包装：首次调用经 with_lock.py --nb 持锁重跑自己，UPDATE_ALL_LOCKED=1 防递归。
if [ -z "${UPDATE_ALL_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_update_all.lock \
    env UPDATE_ALL_LOCKED=1 bash "$0" "$@"
fi

echo "=== update_all.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# force 模式：绕过交易日闸门（周末补数据/校准；当日快照采最近交易日值，幂等不误盖）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1

# 交易日闸门（统一判断一次，避免各 pipeline 重复判断；闸门内部已 refresh_trade_dates）
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"

if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过采集，仅 deploy 补推 + check_signals（force 可绕过）" | tee -a "$LOG"
  bash "$REPO/scripts/deploy.sh" 2>&1 | tee -a "$LOG"
  bash "$REPO/scripts/check_signals.sh" 2>&1 | tee -a "$LOG"
  echo "=== update_all.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

[ "$FORCE" = "1" ] && [ "$IS_TRADING" != "1" ] && echo "⚠ force 模式：非交易日强制采集（补数据/校准）" | tee -a "$LOG"

# 交易日：并发启动 pipeline
# core/width/futures 前台并发（wait 等）；stock_daily 后台（死端不 wait，不阻塞）
echo "-> 并发启动 pipeline: core / width / futures / stock_daily(后台)" | tee -a "$LOG"
bash "$REPO/scripts/pipeline.sh" core        >> "$LOG" 2>&1 &
PID_CORE=$!
bash "$REPO/scripts/pipeline.sh" width       >> "$LOG" 2>&1 &
PID_WIDTH=$!
bash "$REPO/scripts/pipeline.sh" futures     >> "$LOG" 2>&1 &
PID_FUTURES=$!
bash "$REPO/scripts/pipeline.sh" stock_daily >> "$LOG" 2>&1 &
PID_STOCK=$!
echo "  PID: core=$PID_CORE width=$PID_WIDTH futures=$PID_FUTURES stock_daily=$PID_STOCK(后台不等)" | tee -a "$LOG"

# 等核心三线（stock_daily 后台不等）
wait "$PID_CORE";    RC_CORE=$?
wait "$PID_WIDTH";   RC_WIDTH=$?
wait "$PID_FUTURES"; RC_FUTURES=$?
echo "pipeline 退出码: core=$RC_CORE width=$RC_WIDTH futures=$RC_FUTURES (stock_daily PID=$PID_STOCK 仍在后台)" | tee -a "$LOG"

# 信号检测 + 邮件（失败不阻塞，保持原逻辑）
echo "-> check_signals.sh ..." | tee -a "$LOG"
bash "$REPO/scripts/check_signals.sh" 2>&1 | tee -a "$LOG"
SIGNAL_RC=${PIPESTATUS[0]}
[ "$SIGNAL_RC" -ne 0 ] && echo "⚠ check_signals 退出码 $SIGNAL_RC（邮件失败或配置缺失，不影响公网部署）" | tee -a "$LOG"

echo "=== update_all.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
echo "core=$RC_CORE width=$RC_WIDTH futures=$RC_FUTURES check_signals=$SIGNAL_RC" | tee -a "$LOG"

# 退出码以 core 为准（核心看板公网状态）
exit "$RC_CORE"
