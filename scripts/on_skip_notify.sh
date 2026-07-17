#!/usr/bin/env bash
# on_skip_notify.sh - update_all 锁跳过时触发通知（由 with_lock.py --on-skip 调用）。
# 参数 $1 = 锁路径（with_lock.py 传入）。
# 调 notify.py 发"锁跳过"严重通知 + 写 data/alerts/latest.md。
# 环境变量 ON_SKIP_DRY_RUN=1 时 notify.py 用 --dry-run（验证用，不真发邮件）。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOCKPATH="${1:-/tmp/trade_update_all.lock}"
DRY_FLAG=""
[ "${ON_SKIP_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"

NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
BODY="update_all 锁跳过：检测到另一实例正在运行（锁 $LOCKPATH 被占），本次跳过未执行采集。<br>时间：$NOW_STR<br>如非预期（无其他实例在跑），检查 $LOCKPATH 是否残留或进程是否卡死。"

"$PY" "$REPO/scripts/notify.py" "[锁跳过]update_all被锁跳过" "$BODY" --severe \
  --alert-issue "update_all 锁跳过：另一实例在运行或锁残留($LOCKPATH)" \
  $DRY_FLAG || true
