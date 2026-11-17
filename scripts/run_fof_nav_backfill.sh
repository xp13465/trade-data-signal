#!/bin/bash
# FOF/QDII 净值回补 — backfill 相位(21:22 单元, 21:35 墙钟前必须收尾)
#
# 2026-11-17 相位拆分(依据 /tmp/fof-budget-rca-20261117.md):
#   仅跑 pass B「回补」(history/gap 相位 + backfill_pending 优先队列), 代码内预算 600s;
#   到 --deadline-at 21:35 软停 → rc=0 + backfill_not_attempted(软完成, 由覆盖率/滞后
#   看门狗兜底); 锁被占 ⇒ exit 3(真故障可见, 不静默 return 0)。
#   超时梯度: 内层 run_to 720 > 代码内预算 600; 外层 systemd TimeoutStartSec=900 > 720,
#   且 21:35 墙钟软截止远早于 900s 硬杀 ⇒ 22:00 起持锁的 public-fund-full 不被撞。
#   ⚠️ 本脚本只允许一个 run_to 字面量(审计脚本会把全部 run_to 串行相加)。
set -uo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh"
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"; mkdir -p "$LOGDIR"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/fof_nav_backfill_${STAMP}.log"
echo "=== fof_nav_backfill 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
# 交易日闸门: 回补只补交易日的净值缺口; 非交易日没有新数据, 跑也是全空, 跳过省源站请求。
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
if [ "$IS_TRADING" != "1" ]; then
  echo "非交易日，跳过 FOF/QDII 净值回补" | tee -a "$LOG"; exit 0
fi
run_to() {
  local t="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$t" "$@"
  else perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"; fi
}
run_to 720 "$PY" -m scripts.collect_fof_nav --phase backfill --deadline-at 21:35 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "=== fof_nav_backfill 结束 rc=$RC $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
exit "$RC"
