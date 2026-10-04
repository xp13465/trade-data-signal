#!/usr/bin/env bash
# r2_upload_skip_notify.sh - r2_upload_async 锁跳过时留痕(由 with_lock.py --on-skip 调用)。
# 参数 $1 = 锁路径(with_lock.py 传入, 本脚本只用于标记/文案, 不操作锁)。
#
# 跳过=正常降级(同内容已有实例在跑负责完成+告警; 上传幂等+增量指纹+verify-r2 对账,
# 下一趟 deploy 的 R2 增量兜底, 不丢数据)→ 留痕即可, 不发 --severe 不轰炸(2026-10-04
# P1 修 review F1: 此前跳过只 stderr 进 journal + deploy 只见 systemd-run rc=0, 零痕迹)。
#
# 留痕三处:
#   1. deploy 日志显式一行(经 DEPLOY_LOG env, deploy.sh 触发 async 时传入)→ 不再只在 journal。
#   2. data/logs/r2_upload_async_skip.log 追加式流水(无 deploy 上下文手动跑也留痕)。
#   3. data/alerts/latest.md + 普通级 notify(非 --severe, 带 --dedup-key 防重复触发轰炸)。
# 环境变量 R2_SKIP_NOTIFY_DRY_RUN=1 时 notify.py 走 --dry-run(验证用, 不真发邮件/不写 latest.md)。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
PY="$REPO/.venv/bin/python"
LOCKPATH="${1:-/tmp/trade_r2_upload_async.lock}"
DEPLOY_LOG="${DEPLOY_LOG:-}"
DRY_FLAG=""
[ "${R2_SKIP_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"

NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')

# 1+2. deploy 日志显式一行 + skip 留痕流水(每次跳过都记, 不走去重)
SKIP_TRACE="$REPO/data/logs/r2_upload_async_skip.log"
mkdir -p "$(dirname "$SKIP_TRACE")"
if [ -n "$DEPLOY_LOG" ]; then
  echo "⚠ r2_upload_async 锁跳过(锁 $LOCKPATH 被占, 已有实例在跑负责完成, 本次不执行上传, 不丢数据)。$NOW_STR" >> "$DEPLOY_LOG"
fi
echo "⚠ r2_upload_async 锁跳过(锁 $LOCKPATH 被占, 已有实例在跑负责完成)。$NOW_STR" >> "$SKIP_TRACE"

# 3. latest.md + 普通级 notify(--alert-issue 写 data/alerts/latest.md; 非 --severe;
#    dedup 21600=6h 防并发重复触发时轰炸; on_skip_notify.sh 同款骨架, 去 severe)。
"$PY" "$REPO/scripts/notify.py" "R2上传异步锁跳过 $(date '+%m-%d %H:%M')" \
  "R2 上传异步任务(r2_upload_async.sh)锁跳过: 检测到另一实例正在运行(锁 $LOCKPATH 被占), 本次跳过未执行上传。<br>时间: $NOW_STR<br>跳过=正常降级: 已在跑那趟负责完成+告警, 上传幂等+增量指纹+verify-r2 对账, 下一趟 deploy 的 R2 增量兜底, 不丢数据。如非预期(无其他实例在跑), 检查 $LOCKPATH 是否残留或进程是否卡死。" \
  --from-prefix "[提示]" \
  --alert-issue "r2_upload_async 锁跳过: 已有实例在运行或锁残留($LOCKPATH)" \
  --dedup-key "r2_upload_async_skip:$LOCKPATH" --dedup-window 21600 \
  $DRY_FLAG || true
