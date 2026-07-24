#!/bin/bash
# etf_national_team_backfill.sh - ETF国家队当日单采+推送（launchd 20:07 定时）
#
# 问题：etf_national_team.py daily 只调 export_json_files() 写本地 static-site/data/*.json，
#   不 git push -> 最坏 ETF 数据等次日 17:50 update_all 才上线（和 cross_market 数据没上线同类隐患）。
#   本脚本补 deploy.sh 推送，当日采集当日上线。
#
# 只做：python -m app.collector.etf_national_team daily（mootdx OHLC + SSE/SZSE 份额 + 重算信号
#   + 导出 JSON）-> 持 deploy 锁推送（deploy.sh 重新 export 全量 JSON + git push）。
#   等价于 etf_national_team.py daily + deploy.sh，加自身互斥 + 交易日闸门 + caffeinate。
#
# 进程互斥：
#   - etf 锁 /tmp/trade_etf_nt.lock（--nb 非阻塞）：防自身重复并发（python 内 data/etf_national_team.lock
#     也持锁，双层保护：shell 直接调用 / python 直接调用都防并发）。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git，与 20:00 backfill / intraday_snapshot /
#     update_all pipeline 共享，避免撞 .git/index.lock。
#
# 非交易日：默认跳过。force 模式可绕过（手动补测）。
#
# 用法：bash scripts/etf_national_team_backfill.sh [force]
# 日志：data/logs/etf_national_team_backfill_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/etf_national_team_backfill_${STAMP}.log"
LOCK="/tmp/trade_etf_nt.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持 etf 锁重跑自己，ETF_NT_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过。
if [ -z "${ETF_NT_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env ETF_NT_LOCKED=1 bash "$0" "$@"
fi

echo "=== etf_national_team_backfill.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh / intraday_snapshot.sh / 其他 backfill 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过ETF国家队采集（force 可绕过）" | tee -a "$LOG"
  echo "=== etf_national_team_backfill.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 采集 ETF 国家队当日（mootdx OHLC + SSE/SZSE 份额 + 重算信号）+ 导出 JSON
#    python 内置 data/etf_national_team.lock 防并发；采集器写 DB + dump static-site/data/*.json。
echo "-> 采集 ETF 国家队当日 + 导出 JSON ..." | tee -a "$LOG"
"$PY" -m app.collector.etf_national_team daily 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "ETF国家队采集退出码=$COLLECT_RC" | tee -a "$LOG"

# 1.5) 采集完第一时间发汪汪队信号通知（20:07采集通常到T-1，check_nt_signals 标题注明数据日期）
#      放 deploy 前：deploy 持锁 git push 较慢，通知不依赖上线数据、只读 DB，先发最快。
#      失败不阻塞（脚本内 try/except，exit 非 0 但不崩）。
if [ "$COLLECT_RC" -eq 0 ]; then
  echo "-> 检测汪汪队信号 + 发邮件通知 ..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/check_nt_signals.py" 2>&1 | tee -a "$LOG"
  NT_NOTIFY_RC=${PIPESTATUS[0]}
  echo "汪汪队通知退出码=$NT_NOTIFY_RC" | tee -a "$LOG"
fi

# 2) 持 deploy 锁推送（串行化 git，阻塞排队；deploy.sh 重新 export 全量 JSON + git push）
#    deploy.sh 幂等：export 生成相同 JSON -> git add 无新变更 -> 跳过 commit -> push up-to-date。
#    无新数据时也安全（仅多跑一次 export.py）。
echo "-> 持 deploy 锁推送（串行化 git，可能排队等 backfill/intraday）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" etf-national-team 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

echo "=== etf_national_team_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json（2026-07-24 方案A根治：从 deploy.sh:72 移到此处，在"结束"行后调用，
# gen_stats 能读到完整"开始+结束"对，正确配对当前任务 exit/dur，不再 pending null）
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"

exit "$DEPLOY_RC"
