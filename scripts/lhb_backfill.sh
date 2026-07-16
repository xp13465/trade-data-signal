#!/bin/bash
# lhb_backfill.sh - 龙虎榜当日单采（launchd 18:30 定时，根治 lhb_count 46h 滞后）
#
# 问题：龙虎榜（lhb_count / lhb_inst_net）东财约 18:00 后才发布完整当日数据，
#   17:50 update_all 采不到（<18:00 或仅部分值，如 0710@16:45 得 62 而完整值 105）；
#   backfill 不补（stock_lhb_detail_em 不在 SERIES_FUNCS）-> 滞后最久 46h。
#   18:30 单采当日（数据已完整）-> 滞后 0.5h。
#
# 只做：单采 group=lhb 的指标（lhb_count / lhb_inst_net）当日值 -> (有新数据则)
#   重算情绪分 + 持 deploy 锁推送。轻量（几秒采集 + compute + export）。
#
# 进程互斥：
#   - lhb 锁 /tmp/trade_lhb.lock（--nb 非阻塞）：防自身重复并发。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git add/commit/push，与
#     update_all pipeline / intraday_snapshot / backfill 共享，避免撞 .git/index.lock。
#
# 非交易日：默认跳过。force 模式可绕过（手动补测）。
#
# 用法：bash scripts/lhb_backfill.sh [force]
# 日志：data/logs/lhb_backfill_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="/Users/linhuichen/code/trade"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/lhb_backfill_${STAMP}.log"
LOCK="/tmp/trade_lhb.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持 lhb 锁重跑自己，LHB_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过。
if [ -z "${LHB_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env LHB_LOCKED=1 bash "$0" "$@"
fi

echo "=== lhb_backfill.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh / intraday_snapshot.sh 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过龙虎榜采集（force 可绕过）" | tee -a "$LOG"
  echo "=== lhb_backfill.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 单采龙虎榜当日（group=lhb：lhb_count / lhb_inst_net）
#    collect_snapshot 对 DATE_RANGE_FUNCS 传 start_date=end_date=date 单日采；
#    18:30 数据已完整发布，避开 17:50 的部分值问题。
echo "-> 单采龙虎榜当日 (group=lhb) ..." | tee -a "$LOG"
"$PY" -c "
from app.collector import fetchers, runner
from app.collector.base import log_collect
from app.calendar import last_trading_day
import sys
date = last_trading_day()
if hasattr(date, 'strftime'):
    date = date.strftime('%Y%m%d')
cfg = fetchers.load_config()
ok = fail = 0
for m in cfg.get('metrics', []):
    if not m.get('enabled') or m.get('group') != 'lhb':
        continue
    mid = m['id']
    try:
        val, msg = fetchers.collect_snapshot(m, date)
        if val is not None:
            runner.upsert_metric(date, mid, val)
            ok += 1
            log_collect(date, mid, 'ok', f'lhb单采 {val:.4g}')
            print(f'[lhb] {mid} = {val:.4g}')
        else:
            fail += 1
            log_collect(date, mid, 'error', msg)
            print(f'[lhb] {mid} fail: {msg}')
    except Exception as e:
        fail += 1
        log_collect(date, mid, 'error', str(e)[:150])
        print(f'[lhb] {mid} exc: {e}')
print(f'[lhb] date={date} ok={ok} fail={fail}')
sys.exit(0 if ok > 0 else 1)
" 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "龙虎榜采集退出码=${COLLECT_RC:-?}(0=有新数据,非0=源未发布/为空)" | tee -a "$LOG"

if [ "$COLLECT_RC" -ne 0 ]; then
  echo "龙虎榜无新数据（源未发布或为空），跳过重算+推送" | tee -a "$LOG"
  echo "=== lhb_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
  exit 0
fi

# 2) 有新数据 -> 重算情绪分 + 持 deploy 锁推送（串行化 git，阻塞排队）
echo "-> 重算情绪分 ..." | tee -a "$LOG"
"$PY" -c "from app.compute import runner; runner.run()" 2>&1 | tee -a "$LOG"

echo "-> 持 deploy 锁推送（串行化 git）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" lhb 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

echo "=== lhb_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"
exit "$DEPLOY_RC"
