#!/bin/bash
# rzhb_backfill.sh - 两融余额当日单采（launchd 22:10 定时，根治 a_fund_margin 滞后）
#
# 问题：两融余额（a_fund_margin，沪市融资余额）源 stock_margin_sse 盘后 ~18:00-19:00
#   才发布当日数据，17:50 update_all 采不到（源未出 -> 停在 T-1）。20:00 backfill
#   虽会重跑 SERIES_FUNCS 兜底，但为关键资金面指标设独立 22:10 单采，确保当日值
#   落库（22:10 远晚于发布时点，无论同日 18:00-19:00 发布或 T+1 均已可得）。
#
# 只做：单采两融指标（func=stock_margin_sse/szse 的 SERIES_FUNCS，collect_series
#   拉全量后 upsert，幂等）-> 采到 last_trading_day 当日新数据则重算情绪分 + 持
#   deploy 锁推送。轻量（几秒采集 + compute + export）。
#
# 注：两融属 SERIES_FUNCS（非 DATE_RANGE_FUNCS），不能用 collect_snapshot（会对
#   series func 全表求 sum 得错误值），必须用 collect_series 逐日入库后取当日行。
#
# 进程互斥：
#   - rzhb 锁 /tmp/trade_rzhb.lock（--nb 非阻塞）：防自身重复并发。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git add/commit/push，与
#     update_all pipeline / intraday_snapshot / backfill / lhb 共享，避免撞 .git/index.lock。
#
# 非交易日：默认跳过。force 模式可绕过（手动补测）。
#
# 用法：bash scripts/rzhb_backfill.sh [force]
# 日志：data/logs/rzhb_backfill_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/rzhb_backfill_${STAMP}.log"
LOCK="/tmp/trade_rzhb.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持 rzhb 锁重跑自己，RZHB_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过。
if [ -z "${RZHB_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env RZHB_LOCKED=1 bash "$0" "$@"
fi

echo "=== rzhb_backfill.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh / intraday_snapshot.sh / lhb_backfill.sh 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过两融采集（force 可绕过）" | tee -a "$LOG"
  echo "=== rzhb_backfill.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 单采两融当日（func=stock_margin_sse/szse 的 SERIES_FUNCS）
#    collect_series 拉全量历史逐日入库（幂等 upsert），再判断是否含 last_trading_day
#    当日行。22:10 远晚于源发布时点，避开 17:50 的未发布问题。
echo "-> 单采两融当日 (func=stock_margin_sse/szse) ..." | tee -a "$LOG"
"$PY" -c "
from app.collector import fetchers, runner
from app.collector.base import log_collect
from app.calendar import last_trading_day
import sys
date = last_trading_day()
if hasattr(date, 'strftime'):
    date = date.strftime('%Y%m%d')
cfg = fetchers.load_config()
MARGIN_FUNCS = {'stock_margin_sse', 'stock_margin_szse'}
ok = 0
has_today = False
for m in cfg.get('metrics', []):
    if not m.get('enabled') or m.get('type') == 'derived':
        continue
    if m.get('func') not in MARGIN_FUNCS:
        continue
    mid = m['id']
    try:
        rows, msg = fetchers.collect_series(m)
        if rows:
            runner.upsert_metrics_many(mid, rows)
            ok += 1
            if any(d == date for d, _ in rows):
                has_today = True
                log_collect(date, mid, 'ok', f'rzhb单采 {len(rows)} rows has {date}')
                print(f'[rzhb] {mid} ok ({len(rows)} rows, has {date})')
            else:
                log_collect(date, mid, 'ok', f'rzhb单采 {len(rows)} rows latest={rows[0][0]} (无{date})')
                print(f'[rzhb] {mid} ok ({len(rows)} rows, latest={rows[0][0]}, 暂无 {date})')
        else:
            log_collect(date, mid, 'error', msg)
            print(f'[rzhb] {mid} skip ({msg})')
    except Exception as e:
        log_collect(date, mid, 'error', str(e)[:150])
        print(f'[rzhb] {mid} exc: {e}')
print(f'[rzhb] date={date} ok={ok} has_today={has_today}')
sys.exit(0 if has_today else 1)
" 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]:-1}
echo "两融采集退出码=${COLLECT_RC}(0=采到当日新数据,非0=源未发布/为空)" | tee -a "$LOG"

if [ "$COLLECT_RC" -ne 0 ]; then
  echo "两融无当日新数据（源未发布或为空），跳过重算+推送" | tee -a "$LOG"
  echo "=== rzhb_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
  exit 0
fi

# 2) 有新数据 -> 重算情绪分 + 持 deploy 锁推送（串行化 git，阻塞排队）
echo "-> 重算情绪分 ..." | tee -a "$LOG"
"$PY" -c "from app.compute import runner; runner.run()" 2>&1 | tee -a "$LOG"

echo "-> 持 deploy 锁推送（串行化 git）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" rzhb 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

echo "=== rzhb_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"
exit "$DEPLOY_RC"
