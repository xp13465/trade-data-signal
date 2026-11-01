#!/bin/bash
set -uo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh"
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"; mkdir -p "$LOGDIR"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/fof_nav_collect_${STAMP}.log"
echo "=== fof_nav_collect 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
# 交易日闸门
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
if [ "$IS_TRADING" != "1" ]; then
  echo "非交易日，跳过 FOF/QDII 净值采集" | tee -a "$LOG"; exit 0
fi
run_to() {
  local t="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$t" "$@"
  else perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; fi
}
run_to 600 "$PY" -m scripts.collect_fof_nav 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "=== fof_nav_collect 结束 rc=$RC $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
exit "$RC"
