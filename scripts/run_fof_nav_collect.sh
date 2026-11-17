#!/bin/bash
# FOF/QDII 净值采集 — recent 相位(21:10 单元,硬承诺 T-1 新鲜度)
#
# 2026-11-17 相位拆分(依据 /tmp/fof-budget-rca-20261117.md):
#   本脚本只跑 pass A「recent 增量扫」, 代码内预算 200s; 预算耗尽仍 rc=1(硬承诺,
#   新鲜度没扫完就是真失败)。回补(h history/gap)由 run_fof_nav_backfill.sh 21:22 单独跑。
#   超时梯度: 内层 run_to 480 > 代码内预算 200; 外层 systemd TimeoutStartSec=600 > 480。
#   ⚠️ 本脚本只允许一个 run_to 字面量: scripts/systemd_timeout_gradient_audit.py 会把
#      脚本内所有 run_to N 串行相加, 多相位分支写在同一脚本会得出 1200s 假内层值。
set -uo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh"
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"; mkdir -p "$LOGDIR"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/fof_nav_collect_${STAMP}.log"
echo "=== fof_nav_collect(recent) 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
# 交易日闸门(recent 只保交易日新鲜度; 非交易日跳过)
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
if [ "$IS_TRADING" != "1" ]; then
  echo "非交易日，跳过 FOF/QDII 净值采集(recent)" | tee -a "$LOG"; exit 0
fi
run_to() {
  local t="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$t" "$@"
  else perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; fi
}
run_to 480 "$PY" -m scripts.collect_fof_nav --phase recent 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "=== fof_nav_collect(recent) 结束 rc=$RC $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
exit "$RC"
