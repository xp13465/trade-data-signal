#!/usr/bin/env bash
# fund_nav_upload_async.sh - fund-nav R2 上传异步任务(2026-09-23 P1 主链有界化)
#
# 背景: fund-nav 上传(桶化前 fund_nav/{code}.json, 26458 只 ~578MB)是 update_all 主链最大耗时单点:
#   9-22 一次传 21957 只耗时 6225.8s(1h43m), 占 deploy 段 56%; 9-18 超 7200s 被 kill 后
#   checkpoint 断点续传。2026-09-23 桶化(§9B): 产物 nav_bucket/{xx}.json 256 桶(~2MB/桶),
#   PUT 次数固定 256 上传耗时有界。P1 方案 = 产物生成仍主链(export_fund_nav 照跑), 上传拆出主链异步,
#   主链等待区间不再计入 fund-nav 上传时长(否则 update_lab 19:00 等不到)。
#
# 本脚本即异步上传本体:
#   - 由 update_all.sh 在 export_fund_nav 成功后触发。云上走 systemd transient service
#     (独立 cgroup, update_all 退出不清理); 无 systemd 环境 fallback setsid+nohup。
#   - 失败必须告警(不静默): notify.py --severe + --alert-issue(写 data/alerts/latest.md),
#     沿用现有告警链(update_all/deploy 同款), 让 schedule_monitor 发现。
#   - 幂等: upload_r2.py upload-fund-nav 增量指纹(整文件 md5)+ checkpoint 断点续传,
#     重复跑安全(重复触发由 with_lock.py 进程互斥跳过)。
#
# 日志: $REPO/data/logs/fund_nav_upload_async_YYYYMMDD_HHMMSS.log
# 用法: 由 update_all.sh 自动触发; 也可手动: bash scripts/fund_nav_upload_async.sh
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"

# 进程互斥: 同日内重复触发(force 重跑/手动补跑)不并发上传。锁跳过=已有在跑, 那趟会负责
# 完成+告警; 上传幂等+checkpoint, 本次跳过不丢数据。用 with_lock.py(fcntl, mac/linux 通用)。
if [ -z "${FUND_NAV_UPLOAD_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_fund_nav_upload.lock \
    env FUND_NAV_UPLOAD_LOCKED=1 bash "$0" "$@"
fi

LOG="$REPO/data/logs/fund_nav_upload_async_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
echo "=== fund_nav_upload_async 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO" | tee -a "$LOG"

"$PY" "$REPO/scripts/upload_r2.py" upload-fund-nav >> "$LOG" 2>&1
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "✗ upload-fund-nav 异步上传失败 rc=$rc (不静默, 走 notify 告警)" | tee -a "$LOG"
  MM_DD_HM=$(date '+%m-%d %H:%M')
  "$PY" "$REPO/scripts/notify.py" "[告警] fund-nav R2 异步上传失败 ${MM_DD_HM}" \
    "fund_nav 异步上传失败(退出码 $rc)。R2 nav_bucket/ 前缀可能停留旧版, 前端「净值走势」懒加载读 R2 会拿到过期数据。<br>建议手动重试: cd $REPO && python scripts/upload_r2.py upload-fund-nav<br>日志: $LOG" \
    --severe --from-prefix "[告警]" --alert-issue "fund-nav异步上传失败" --alert-log "$LOG" \
    --dedup-key "fund_nav_async_upload_fail" --dedup-window 3600 2>&1 | tee -a "$LOG" || true
  exit "$rc"
fi
echo "✓ upload-fund-nav 异步上传完成 $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
