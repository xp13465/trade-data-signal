#!/bin/bash
# daily_brief 每日AI预测 —— 定时调度入口(挂在 update_all.sh 17:50 盘后管线)。
# 读 config/daily_brief.yaml 的 schedule_enabled 开关:
#   false = 拦截不跑(默认),主控/用户手动 `python3 scripts/gen_daily_brief.py` 始终可跑
#   true  = 每天自动跑
# 失败不阻塞主流程(与 daily_summary_email 同模式),退出码恒 0。
# 用法: bash scripts/run_daily_brief.sh [--extra-args...]  透传给 gen_daily_brief.py

set -u
REPO="${REPO:-/Users/linhuichen/code/trade-data}"
CFG="$REPO/config/daily_brief.yaml"
PY="$REPO/.venv/bin/python"

LOG="${LOG:-$REPO/data/logs/daily_brief.log}"
mkdir -p "$(dirname "$LOG")"

if [ ! -f "$CFG" ]; then
  echo "[run_daily_brief] 配置缺失 $CFG,跳过" | tee -a "$LOG"
  exit 0
fi

# 读 schedule_enabled(yaml 简单 grep,值在行首;去行尾注释/空格加固,防 `true #注释` 误判)
SCHED=$(grep -E '^schedule_enabled:' "$CFG" | head -1 \
  | sed -E 's/^schedule_enabled:[[:space:]]*//' | sed -E 's/[[:space:]]*#.*$//' | tr -d ' ')
if [ "$SCHED" != "true" ]; then
  echo "[run_daily_brief] schedule_enabled=$SCHED(非 true),定时调度拦截,跳过(手动 CLI 仍可跑)" | tee -a "$LOG"
  exit 0
fi

# 非交易日跳过(复用 trade/app/calendar.py 节假日历;非交易日不生成不覆盖不通知)
# PY=trade-data/.venv/bin/python,import trade/app/calendar.py(scripts/config 是 symlink 指向 trade,venv 可访问)
if ! "$PY" -c "import sys; sys.path.insert(0,'/Users/linhuichen/code/trade'); from app.calendar import is_trading_day; import datetime as _dt; sys.exit(0 if is_trading_day(_dt.date.today()) else 1)"; then
  echo "[run_daily_brief] 非交易日,跳过(不生成不覆盖不通知) $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
  exit 0
fi

echo "[run_daily_brief] schedule_enabled=true,开始生成 $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
if "$PY" "$REPO/scripts/gen_daily_brief.py" "$@" >> "$LOG" 2>&1; then
  echo "[run_daily_brief] ✓ 完成" | tee -a "$LOG"
else
  rc=$?
  echo "[run_daily_brief] ✗ 失败 rc=$rc(不阻塞主流程)" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] daily_brief 生成失败 rc=$rc" \
    "run_daily_brief 退出码 $rc<br>日志: $LOG" --from-prefix "[告警]" --dedup-key daily_brief_fail --dedup-window 1800 >> "$LOG" 2>&1 || true
fi

# ── 影子模式对账聚算(2026-08-24 四项改进R1 挂载)────────────────────────────
# 背景:aggregate_shadow.py 此前无任何调度挂载(run_daily_brief.sh 全文不调、无独立 launchd 槽位),
# 影子记录 actual 自 0819 起断档全 null(审计 docs/ai-predict/ai-predict-shadow-vs-default-hitrate-audit-20260824.md §一)。
# 挂载口径:20:40 预测生成完顺带对账「截至昨日」的全部未对账影子记录——T 日预测需 T+1 收盘才可判,
# 本时点(20:40)T-1 及更早的收盘数据已由 17:50 update_all 采入 sentiment.db(index_daily),输入就绪;
# 每日滚动清账不留断档。失败不阻塞主流程(与生成同模式)。不改 launchd StartCalendarInterval,不动 plist。
echo "[run_daily_brief] 开始影子对账 aggregate_shadow $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
if REPO="$REPO" "$PY" "$REPO/scripts/aggregate_shadow.py" >> "$LOG" 2>&1; then
  echo "[run_daily_brief] ✓ 影子对账完成" | tee -a "$LOG"
else
  echo "[run_daily_brief] ✗ 影子对账失败(不阻塞主流程)" | tee -a "$LOG"
fi
exit 0
