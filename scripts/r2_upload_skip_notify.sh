#!/usr/bin/env bash
# r2_upload_skip_notify.sh - r2_upload_async 锁超时跳过时留痕(由 with_lock.py --on-timeout 调用)。
# 参数 $1 = 锁路径(with_lock.py 传入, 本脚本只用于标记/文案, 不操作锁)。
#
# 本钩子只报告本地交接事实：入队保全不等于已接手/已上传，锁路径不证明合法持锁者。
# pending 队列与正常 worker 的有界补跑逻辑不变，不保证同日交付。
#
# 留痕三处+标记一处:
#   1. deploy 日志显式一行(经 DEPLOY_LOG env, deploy.sh 触发 async 时传入)→ 不再只在 journal。
#   2. data/logs/r2_upload_async_skip.log 追加式流水(无 deploy 上下文手动跑也留痕)。
#   3. data/alerts/latest.md + notify：正常交接保留普通 report；入队/结果校验/清理失败
#      走 --severe + alert。失败种类与锁路径构成稳定 key，6h 去重，不被普通 skip 占窗。
#   4. 并发跳过标记 PENDING_FILE：仅 helper 成功返回的结果可用于说明本地保全状态。
# 环境变量 R2_SKIP_NOTIFY_DRY_RUN=1 时 notify.py 走 --dry-run(验证用, 不真发邮件/不写 latest.md)。
set -u

# ── REPO/GIT_REPO 单点解析(#195 批2):共享 lib(env 优先零改写 > $0 双布局推导 > fail-loud)──
# 去掉写死的 mac 默认值(原靠 unit 的 Environment= 兜住,env 一丢即静默坏);原 export
# 语义逐字节保留(python 子进程可见性与迁移前一致)。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
LOCKPATH="${1:-/tmp/trade_r2_upload_async.lock}"
DEPLOY_LOG="${DEPLOY_LOG:-}"
DRY_FLAG=""
[ "${R2_SKIP_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"

NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')

# 0. 只在已确认逐请求登记时请求 retire-source；删除权限仍由 helper 原校验决定。
# enqueue rc=0 也可能只是 legacy 唤醒，或已有 done/superseded 记录，不能一概称已保全待接手。
PENDING_FILE="${R2_UPLOAD_ASYNC_PENDING:-/tmp/trade_r2_upload_async.pending}"
_HANDOFF_STATE=enqueue_failed
if _ENQUEUE_RESULT=$("$PY" "$REPO/scripts/r2_pending_context.py" enqueue); then
  _HANDOFF_STATE=$("$PY" -c '
import json, os, re, sys
from pathlib import Path
state = "invalid_result"
try:
    row = json.load(sys.stdin)
    if isinstance(row, dict):
        if row.get("status") == "legacy" and row.get("registered") is False:
            state = "legacy"
        elif (row.get("state") in ("pending", "done", "superseded")
              and row.get("run_id") == os.environ.get("R2_EXPORT_RUN_ID")
              and row.get("static_dir") == str((Path(os.environ["REPO"]) / "static-site").resolve())
              and re.fullmatch(r"[0-9a-f]{64}", str(row.get("proof_sha256", "")))):
            state = "queued" if row["state"] == "pending" else "recorded_terminal"
except (ValueError, TypeError, KeyError, OSError):
    pass
print(state)
' <<< "$_ENQUEUE_RESULT")
fi

# #321 的普通 report 路由保留给非失败交接；失败分支在下方明确切换 alert。
_NOTIFY_FLAGS=(--from-prefix "[提示]" --feishu-group report)
_SUBJECT="R2上传异步锁跳过"
_DEDUP_KEY="r2_upload_async_skip:$LOCKPATH"
case "$_HANDOFF_STATE" in
  queued)
    _DETAIL="本请求 proof 已保全待接手；是否接手、消费及远端确认以逐请求记录为准。"
    ;;
  recorded_terminal)
    _DETAIL="同 run 已有 done/superseded 逐请求终态记录，本次未重新登记待接手任务；该本地结果不单独证明远端交付。"
    ;;
  legacy)
    _DETAIL="仅保留 legacy 唤醒标记，未登记逐请求 proof；未调用 retire-source，不宣称本请求已保全。"
    ;;
  *)
    [ "$_HANDOFF_STATE" = "enqueue_failed" ] || _HANDOFF_STATE=invalid_result
    _DETAIL="入队失败或返回结果无法校验，无法确认 proof 已保全；未调用 retire-source，未清理源 metadata。请保留原 run/root/proof 元数据，检查源内容与队列写入错误后显式 retry 入队。"
    ;;
esac
if [ "$_HANDOFF_STATE" = "queued" ] || [ "$_HANDOFF_STATE" = "recorded_terminal" ]; then
  if ! "$PY" "$REPO/scripts/r2_pending_context.py" retire-source >/dev/null 2>&1; then
    _HANDOFF_STATE=retire_failed
    _DETAIL="${_DETAIL} 源 metadata 清理未确认；本钩子不追加删除。请保留现有队列记录及可用副本，检查实际源状态并按需显式 retry retire-source。"
  fi
fi
case "$_HANDOFF_STATE" in
  enqueue_failed|invalid_result|retire_failed)
    _NOTIFY_FLAGS=(--severe --from-prefix "[告警]" --feishu-group alert)
    _SUBJECT="[告警] R2锁跳过交接异常 ($_HANDOFF_STATE)"
    _DEDUP_KEY="r2_upload_async_skip:${_HANDOFF_STATE}:$LOCKPATH"
    ;;
esac
_LOCK_DETAIL="锁等待超时($LOCKPATH)，本次未执行上传；仅凭锁路径不能确认合法持锁者、接手状态或交付时间。"

# 1+2. deploy 日志显式一行 + skip 留痕流水(每次跳过都记, 不走去重)
SKIP_TRACE="$REPO/data/logs/r2_upload_async_skip.log"
mkdir -p "$(dirname "$SKIP_TRACE")"
if [ -n "$DEPLOY_LOG" ]; then
  echo "⚠ r2_upload_async 锁跳过 [handoff=$_HANDOFF_STATE] $_LOCK_DETAIL $_DETAIL 队列标记路径=$PENDING_FILE 时间=$NOW_STR" >> "$DEPLOY_LOG"
fi
echo "⚠ r2_upload_async 锁跳过 [handoff=$_HANDOFF_STATE] $_LOCK_DETAIL $_DETAIL 队列标记路径=$PENDING_FILE 时间=$NOW_STR" >> "$SKIP_TRACE"

# 3. 不改 callback/with_lock 的 best-effort 返回契约，不将任何 skip 统一静音。
"$PY" "$REPO/scripts/notify.py" "$_SUBJECT $(date '+%m-%d %H:%M')" \
  "R2 上传异步任务(r2_upload_async.sh)锁跳过。<br>$_LOCK_DETAIL<br>交接状态: $_HANDOFF_STATE<br>$_DETAIL<br>队列标记路径: $PENDING_FILE<br>时间: $NOW_STR" \
  "${_NOTIFY_FLAGS[@]}" \
  --alert-issue "r2_upload_async 锁跳过交接状态: $_HANDOFF_STATE ($LOCKPATH)" \
  --dedup-key "$_DEDUP_KEY" --dedup-window 21600 \
  $DRY_FLAG || true
