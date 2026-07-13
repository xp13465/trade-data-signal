#!/bin/bash
# intraday_snapshot.sh - 盘中实时快照采集（launchd 定时，盘中每 30 分钟）
#
# 跑 .venv/bin/python -m app.collector.intraday_snapshot（秒级）：
#   采腾讯9指数实时 + 同花顺行业实时涨跌幅，存 DB + dump static-site/data/intraday_snapshot.json
# 然后 commit + push 该 JSON（推公网，供前端"盘中实时小结"展示）。
#
# 进程互斥：
#   - 快照锁 /tmp/trade_intraday_snapshot.lock（--nb 非阻塞）：防快照自身重复，秒级。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git add/commit/push，避免和
#     update_all pipeline 撞 .git/index.lock。阻塞等待 update_all 释放后执行。
#
# 非交易日：默认跳过（不浪费 git commit）。force 模式可绕过（手动补测）。
# 旧串行 update_all.sh 末尾也顺带跑快照但不 push；本脚本独立 push。
#
# 用法：bash scripts/intraday_snapshot.sh [force]
#   force: 绕过交易日闸门，非交易日也跑（补测/校准）
# 日志：data/logs/intraday_snapshot_YYYYMMDD_HHMM.log
# 退出码：快照采集退出码（git push 失败也计入）。
set -uo pipefail

REPO="/Users/linhuichen/code/trade"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/intraday_snapshot_${STAMP}.log"
SNAP_JSON="static-site/data/intraday_snapshot.json"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持快照锁重跑自己，INTRADAY_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过（秒级任务不该撞，撞了就跳过）。
if [ -z "${INTRADAY_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_intraday_snapshot.lock \
    env INTRADAY_LOCKED=1 bash "$0" "$@"
fi

echo "=== intraday_snapshot.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"

if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过快照采集（force 可绕过）" | tee -a "$LOG"
  echo "=== intraday_snapshot.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

[ "$FORCE" = "1" ] && [ "$IS_TRADING" != "1" ] && echo "⚠ force 模式：非交易日强制采集快照（补测）" | tee -a "$LOG"

# 1) 采集快照（存 DB + dump static-site/data/intraday_snapshot.json）
echo "-> 采集盘中快照 ..." | tee -a "$LOG"
"$PY" -m app.collector.intraday_snapshot 2>&1 | tee -a "$LOG"
SNAP_RC=${PIPESTATUS[0]}
if [ "$SNAP_RC" -ne 0 ]; then
  echo "✗ 快照采集失败（退出码 $SNAP_RC），写 stderr 告警" | tee -a "$LOG" >&2
  exit "$SNAP_RC"
fi

# 2) commit + push intraday_snapshot.json
#    持 deploy.lock 串行化 git（阻塞，等 update_all pipeline 释放；避免 index.lock 冲突）。
#    只 add intraday_snapshot.json，不碰其他文件（前端 agent 可能改了 app.js 等）。
#    用环境变量传 commit message，避免 bash -c 引号转义问题。
COMMIT_MSG="data update [intraday] $(date +%Y-%m-%d_%H:%M)"
export INTRADAY_COMMIT_MSG="$COMMIT_MSG"
echo "-> commit + push ${SNAP_JSON}（持 deploy 锁串行）msg=\"${COMMIT_MSG}\" ..." | tee -a "${LOG}"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash -c '
  cd /Users/linhuichen/code/trade
  git add static-site/data/intraday_snapshot.json
  if git diff --cached --quiet; then
    echo "✓ 快照 JSON 无变更，跳过 commit（仍 push 推未 push commit）"
  else
    git commit -m "$INTRADAY_COMMIT_MSG"
    echo "✓ git commit 完成"
  fi
  git push
' 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]}
if [ "$PUSH_RC" -ne 0 ]; then
  echo "✗ commit/push 失败（退出码 $PUSH_RC），写 stderr 告警" | tee -a "$LOG" >&2
  exit "$PUSH_RC"
fi

echo "=== intraday_snapshot.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
