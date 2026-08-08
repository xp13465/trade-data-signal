#!/bin/bash
# gold_night.sh - 黄金/原油夜盘收盘价补采 (launchd 02:40, 02:30 夜盘收盘后 10min)
#
# 采 nf_AU0(沪金)->gold / nf_SC0(INE原油)->oil 夜盘收盘价写 daily_metric source=gold_night,
# 导出 global-*.json, commit+push global-3m/6m/1y 到 main + upload_r2 global-3y/5y/all(>=1MB).
#
# 闸门 is_trading_day(昨日): 昨晚有夜盘才跑(覆盖周五夜盘周六02:40跑; 周日/周一凌晨跳过无夜盘).
# 详见 app/collector/gold_night.py docstring.
#
# 进程互斥: deploy 锁 /tmp/trade_deploy.lock(阻塞) 串行化 git, 避免和 update_all/intraday 撞 index.lock.
# §14 安全: 02:40 在 backfill-evening(02:00-02:17) 后 / pf-score-weekly(周日03:17) 前 / us-stock-morning(05:00) 前.
#
# 用法: bash scripts/gold_night.sh
# 日志: data/logs/gold_night_YYYYMMDD_HHMM.log
# 退出码: 0=成功/闸门跳过, 1=采集失败/push失败.
set -uo pipefail
# 防脚本运行期间 mac 休眠(caffeinate 跟随脚本 PID, 退出自动结束)
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 始终在 trade 仓库(trade-data 不 git init)
export REPO GIT_REPO
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/gold_night_${STAMP}.log"
export LOG

mkdir -p "$LOGDIR"
cd "$REPO"

echo "=== gold_night.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 1) 采集 + 导出 (gold_night.py 内含 is_trading_day(昨日) 闸门 + 采集 nf_AU0/nf_SC0 + 导出 global)
#    cwd=$REPO(trade-data) 让 app.db 读主库 trade-data/data/sentiment.db (CLAUDE.md §9)
echo "-> 采集夜盘收盘价 + 导出 global JSON ..." | tee -a "$LOG"
"$PY" -m app.collector.gold_night 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
if [ "$COLLECT_RC" -ne 0 ]; then
  if [ "$COLLECT_RC" -eq 1 ]; then
    echo "✗ gold_night 采集失败(退出码 1), 跳过 push, 发告警" | tee -a "$LOG" >&2
    "$PY" "$REPO/scripts/notify.py" "[告警] gold_night 采集失败 $(date '+%m-%d %H:%M')" \
      "黄金夜盘补采失败(退出码 1, nf_AU0/nf_SC0 采集返回空或 price=None). 日志: $LOG" \
      --severe --from-prefix "[告警]" \
      --dedup-key gold_night_collect_fail --dedup-window 3600 2>&1 | tee -a "$LOG" || true
    exit "$COLLECT_RC"
  fi
  echo "gold_night.py 退出码 $COLLECT_RC(未知), 跳过 push" | tee -a "$LOG" >&2
  exit "$COLLECT_RC"
fi
# 退出码 0 = 闸门跳过(非交易日) 或 采集成功. 区分: 闸门跳过时 gold_night.py 输出"跳过"
if grep -q "非交易日.*跳过" "$LOG"; then
  echo "=== gold_night.sh 结束(闸门跳过, 非交易日) $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 2) 上传 global JSON 到 R2（阶段3：去 git push，前端走 R2）
#    global-3m/6m/1y.json + global-3y/5y/all/extras-all 全部走 R2（前端 dataUrl 走 R2 直链）。
#    采集器写 REPO/static-site/data/（trade-data），upload_r2.py 读 REPO（env）直接上传。
#    static-site/data/ 仍 tracked，R2 故障时可手动 git push 兜底。
ALERT_TIME=$(date '+%m-%d %H:%M')
echo "-> 上传 global 大 range JSON 到 R2（upload-data-large）..." | tee -a "$LOG"
if ! "$PY" "$REPO/scripts/upload_r2.py" upload-data-large 2>&1 | tee -a "$LOG"; then
  echo "⚠ upload-data-large 失败/无大文件，继续上传小 range" | tee -a "$LOG"
fi
echo "-> 上传 global-3m/6m/1y.json 到 R2（upload-data-files + purge）..." | tee -a "$LOG"
if ! "$PY" "$REPO/scripts/upload_r2.py" upload-data-files global-3m.json global-6m.json global-1y.json 2>&1 | tee -a "$LOG"; then
  echo "✗ global R2 上传失败，发告警邮件" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" \
    "[告警] gold_night R2上传失败 ${ALERT_TIME}" \
    "gold_night global JSON R2 上传失败，前端走势图将读旧数据，需手动补刷: bash scripts/upload_r2.py upload-data-files global-3m.json global-6m.json global-1y.json<br>日志: $LOG" \
    --severe --from-prefix "[告警]" \
    --alert-issue "gold_night R2 上传失败" \
    --alert-log "$LOG" \
    --dedup-key gold_night_r2_upload_fail --dedup-window 3600 2>&1 | tail -3 | tee -a "$LOG" || true
  exit 1
fi
echo "✓ global JSON R2 上传完成" | tee -a "$LOG"

echo "=== gold_night.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"

# 3) 刷新 schedule_stats.json(gold_night 运行统计, 失败不阻塞)
#    gen_schedule_stats 扫 launchd plist 识别任务; push_schedule_stats 独立 push 绕过 deploy 时序.
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" | tail -1 || \
  echo "⚠ gen_schedule_stats 失败, 不阻塞" | tee -a "$LOG"
bash "$REPO/scripts/push_schedule_stats.sh" 2>&1 | tee -a "$LOG" || \
  echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit 0
