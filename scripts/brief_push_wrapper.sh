#!/bin/bash
# brief_push_wrapper.sh —— AI 每日速递订阅推送服务定时调度入口。
# 在 daily_brief 生成（20:40 run_daily_brief.sh -> gen_daily_brief.py）之后，20:45 由 launchd
# com.trade.brief-push 触发，跑 brief_push.py 推送给订阅者 + 飞书报告群。
#
# 设计（§23.7 只增不改 + memory daily-brief-range-degrade-contract）：
#   - 独立 wrapper + 独立 launchd，不碰现有 run_daily_brief.sh / com.trade.daily-brief plist。
#   - 非交易日判断在 brief_push.py 内做（复用 trade/app/calendar.py is_trading_day），不在此重复。
#   - 失败不阻塞主流程，退出码恒 0（与 run_daily_brief.sh 同模式）。
#   - daily_brief 未生成（文件缺失）时 brief_push.py 自行报错退出，wrapper 记日志。
#
# 用法: bash scripts/brief_push_wrapper.sh [--dry-run]

set -u
REPO="${REPO:-/Users/linhuichen/code/trade-data}"
PY="$REPO/.venv/bin/python"

LOG="${LOG:-$REPO/data/logs/brief_push.log}"
mkdir -p "$(dirname "$LOG")"

echo "[brief_push_wrapper] start $(date '+%Y-%m-%d %H:%M:%S') args: $*" | tee -a "$LOG"
# 注意：wrapper 里 REPO=trade-data，但 brief_push.py 内部用 __file__ resolve 到 trade/scripts，
# daily_brief.json 读 trade/static-site/data/（与 gen_daily_brief.py 双写位置一致）。
if "$PY" "$REPO/scripts/brief_push.py" "$@" >> "$LOG" 2>&1; then
  echo "[brief_push_wrapper] ✓ 完成" | tee -a "$LOG"
else
  rc=$?
  echo "[brief_push_wrapper] ✗ 失败 rc=$rc" | tee -a "$LOG"
fi
exit 0
