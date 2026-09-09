#!/usr/bin/env bash
# turnover_backfill.sh - 换手率分布独立延后任务(#82 C6, 2026-09-09, 用户已拍板)
#
# 背景: turnover pipeline(a_turnover_mean/median/p90/p10/gt5_pct 写 daily_metric, baostock
#   增量 + cleanup_d3d2 计算)是 update_all 主链最大单块(90.8min)。用户拍板摘出主链,
#   改独立 launchd 延后 1-2h 跑(21:10), update_all 主链 175→~85min(实测 112-121min)。
#   副作用自动治好: update_lab 饿死(19:00 等 update_all 5400s 放弃) + C2 告警(阈值失真)。
# 本脚本 = launchd com.trade.turnover-backfill 的包装(参照 s06_snapshot.sh 模板):
#   ①caffeinate 防睡眠 ②交易日闸门(fail-open, force 绕过) ③进程互斥(独立锁 + 锁跳过通知)
#   ④等 update_all 主链结束(最多 1800s, 防并发 baostock/DB 锁)
#   ⑤pipeline.sh turnover(RUN_BAOSTOCK=1 由 pipeline.sh 内部设, 90.8min, 超时 7200s)
#   ⑥增量重导 overview.json + a-stock-{3m,6m,1y,3y,5y,all}.json(只重写换手率相关展示文件,
#     消费链 overview() 读 daily_metric 最新非空值, 缺当日=显示 T-1 不报错)
#   ⑦upload-intraday(overview/a-stock-3m/6m/1y)+ upload-data-large(3y/5y/all)上传 R2 + purge CF
#   ⑧失败 notify --severe(--dedup-key 1h 防轰炸); 成功静默(git 渠道随次日 17:50 deploy 追上)
# 日志: data/logs/turnover_backfill_launchd.log(固定名 append, 标准开始/结束行供
#   gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读, 同 s06_snapshot 先例)
# 用法: bash scripts/turnover_backfill.sh [force]
set -uo pipefail

# 防脚本运行期间 mac 休眠(caffeinate 跟随脚本 PID, 退出自动结束)
caffeinate -i -w $$ >/dev/null 2>&1 &

# ⚠️ 必须 export(2026-08-26 手动裸跑事故根因): upload_r2.py 从 os.environ 读 REPO 派生
# STATIC_DIR, 只设 shell 变量不 export 时子进程读不到 → 回退 ROOT=trade 触发盘中守卫 abort。
export REPO="${REPO:-/Users/linhuichen/code/trade-data}"
export GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
mkdir -p "$LOGDIR"
cd "$REPO"
LOG="$LOGDIR/turnover_backfill_launchd.log"
LOCK="/tmp/trade_turnover.lock"

# codex008 F5(P3②): 三段命令统一超时包装防挂死(macOS 无 coreutils timeout,
# fallback 链: timeout → gtimeout → perl alarm-exec)。超时按非零处理走既有 FAIL 告警链。
run_to() {
  local t="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$t" "$@"
  else
    perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"
  fi
}

# 进程互斥: 自包装经 with_lock.py --nb 持独立锁重跑自己, TURNOVER_BACKFILL_LOCKED=1 防递归。
# 锁被占(上一轮还在跑/手动补跑在跑) = --on-skip 发通知 + 写标准开始/结束行(防 schedule_monitor
# 误报漏跑), 然后 exit 0 跳过本轮。手动补跑场景跳过无常(补跑数据已覆盖), 定时场景跳过=当日
# turnover 缺失, 通知让用户知道(§23.11 不静默同精神)。
if [ -z "${TURNOVER_BACKFILL_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb --on-skip "$REPO/scripts/turnover_backfill_skip_notify.sh" "$LOCK" \
    env TURNOVER_BACKFILL_LOCKED=1 bash "$0" "$@"
fi

echo "=== turnover_backfill.sh 开始 $(date '+%F %T') ===" >> "$LOG"

# 交易日闸门(同 overfit_monitor.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)
if [ "${1:-}" != "force" ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "=== turnover_backfill.sh 结束（非交易日）$(date '+%F %T') ===" >> "$LOG"
    exit 0
  fi
fi

RC_PIPE=0; RC_EXPORT=0; RC_R2=0; RC_R2L=0

# 1) 等 update_all 主链结束(摘出后主链 17:50+~115min≈19:45, 21:10 时通常已结束; 防御性等待
#    防并发 baostock 采集/DB 锁, 最多 1800s = 30min。等满仍在跑=update_all 卡死, 记录警告继续:
#    放弃本轮=当日 turnover 缺失更糟, 并发风险由 runner step try/except 兜底)
WAIT_ROUNDS=0
for _i in $(seq 1 180); do
  if ! pgrep -f "update_all\.sh" >/dev/null 2>&1; then
    break
  fi
  sleep 10
  WAIT_ROUNDS=$_i
done
echo "-> 等待 update_all 结束完成(rounds=${WAIT_ROUNDS}×10s)" >> "$LOG"

# 2) 跑 turnover pipeline(baostock 增量 + cleanup_d3d2 算 a_turnover 入 daily_metric;
#    RUN_BAOSTOCK=1 由 pipeline.sh 内部对 turnover 分支自动 export; 90.8min, 超时 7200s)
echo "-> 跑 pipeline.sh turnover(约 90min) ..." >> "$LOG"
run_to 7200 bash scripts/pipeline.sh turnover >> "$LOG" 2>&1
RC_PIPE=$?
if [ "$RC_PIPE" -ne 0 ]; then
  echo "✗ turnover pipeline 失败 rc=${RC_PIPE}" >> "$LOG"
else
  echo "✓ turnover pipeline 采集完成" >> "$LOG"
fi

# 3) 增量重导换手率相关展示文件(仅采集成功时; overview 必更白名单 + a-stock 6 range 全量重算,
#    同 export.py main 的 write_json 语义; 只写 REPO 主库树, git 渠道随次日 17:50 deploy 追上)
if [ "$RC_PIPE" -eq 0 ]; then
  echo "-> 增量重导 overview.json + a-stock-{3m,6m,1y,3y,5y,all}.json ..." >> "$LOG"
  run_to 600 "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import importlib.util
import os
from pathlib import Path

ROOT = Path(os.environ["REPO"])
spec = importlib.util.spec_from_file_location("export", ROOT / "static-site" / "export.py")
export_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_mod)
from app.collector.fetchers import load_config
from app.db import get_conn

cfg = load_config()
conn = get_conn()
DATA_DIR = export_mod.DATA_DIR

export_mod.write_json(DATA_DIR / "overview.json", export_mod.export_overview(conn, cfg))
print("  overview.json 重导完成")
for _rng in export_mod.EXPORT_RANGES:
    export_mod.write_json(
        DATA_DIR / f"a-stock-{_rng}.json",
        export_mod.export_a_stock(conn, cfg, _rng),
    )
    print(f"  a-stock-{_rng}.json 重导完成")
conn.close()
PYEOF
  RC_EXPORT=$?
  if [ "$RC_EXPORT" -ne 0 ]; then
    echo "✗ 增量重导失败 rc=${RC_EXPORT}" >> "$LOG"
  fi
fi

# 4) 上传 R2 + purge CF edge(§22 N 缓存同步; upload-intraday 覆盖 overview/a-stock-3m/6m/1y,
#    upload-data-large 兜底大 range 3y/5y/all; 失败仅告警不阻断——git 渠道随次日 deploy 追上)
if [ "$RC_EXPORT" -eq 0 ]; then
  echo "-> 上传 R2(upload-intraday + upload-data-large) ..." >> "$LOG"
  run_to 600 "$PY" scripts/upload_r2.py upload-intraday >> "$LOG" 2>&1
  RC_R2=$?
  [ "$RC_R2" -ne 0 ] && echo "⚠ upload-intraday R2 同步失败 rc=${RC_R2}(git 渠道随次日 deploy 追上)" >> "$LOG"
  run_to 600 "$PY" scripts/upload_r2.py upload-data-large >> "$LOG" 2>&1
  RC_R2L=$?
  [ "$RC_R2L" -ne 0 ] && echo "⚠ upload-data-large R2 同步失败 rc=${RC_R2L}(git 渠道随次日 deploy 追上)" >> "$LOG"
fi

FINAL_RC=$RC_PIPE
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_EXPORT
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_R2
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_R2L

if [ "$FINAL_RC" -ne 0 ]; then
  "$PY" scripts/notify.py \
    "[告警] turnover 独立任务链路异常 pipe=$RC_PIPE export=$RC_EXPORT r2=$RC_R2 r2large=$RC_R2L $(date '+%m-%d %H:%M')" \
    "turnover 独立延后任务(21:10)四段(pipeline 采集 / 增量重导 overview+a-stock / upload-intraday / upload-data-large)任一失败, 当日 a_turnover_* 数据可能缺失或未上线。<br>日志: $LOG (尾部 50 行)<br>影响: 首页折叠区/A股走势图换手率读 T-1(缺当日不报错, 前端 T1_COLLECT_DEADLINE 18:00 会标红色异常至数据上线)。" \
    --severe --from-prefix "[告警]" \
    --alert-issue "turnover 独立任务链路异常" --alert-log "$LOG" \
    --dedup-key turnover_backfill_fail --dedup-window 3600 >> "$LOG" 2>&1
fi

echo "=== turnover_backfill.sh 结束 $(date '+%F %T') 退出码=$FINAL_RC ===" >> "$LOG"
exit "$FINAL_RC"
