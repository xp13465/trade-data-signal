#!/usr/bin/env bash
# r2_upload_skip_notify.sh - r2_upload_async 锁超时跳过时留痕(由 with_lock.py --on-timeout 调用)。
# 参数 $1 = 锁路径(with_lock.py 传入, 本脚本只用于标记/文案, 不操作锁)。
#
# 跳过=正常降级但有真缺口风险(2026-10-04 ③ 已根治同日内): 本脚本写并发跳过标记
# /tmp/trade_r2_upload_async.pending(R2_UPLOAD_ASYNC_PENDING env 可覆盖), 在跑 async 实例
# 收尾检测到标记 → 增量补跑数据通道一次(读当前本地文件含被跳过那趟的新 export)。
# 上传幂等+增量指纹+verify-r2 对账, 被跳过那趟不丢数据、不拖到下一趟 deploy。
#
# 留痕三处+标记一处:
#   1. deploy 日志显式一行(经 DEPLOY_LOG env, deploy.sh 触发 async 时传入)→ 不再只在 journal。
#   2. data/logs/r2_upload_async_skip.log 追加式流水(无 deploy 上下文手动跑也留痕)。
#   3. data/alerts/latest.md + 普通级 notify(非 --severe, 带 --dedup-key 防重复触发轰炸)。
#   4. 并发跳过标记 PENDING_FILE(在跑 async 收尾补跑触发源)。
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

# 0. 并发跳过标记(2026-10-04 ③): 在跑 async 实例收尾检测到 → 增量补跑数据通道一次,
#    读当前本地文件(含本趟被跳过时点之后落地的新 export), 保证同日内数据上 R2,
#    不拖到下一趟 deploy。单文件语义: 任意次跳过 = 补跑一次读最新本地态, 幂等安全。
PENDING_FILE="${R2_UPLOAD_ASYNC_PENDING:-/tmp/trade_r2_upload_async.pending}"
touch "$PENDING_FILE"

# 1+2. deploy 日志显式一行 + skip 留痕流水(每次跳过都记, 不走去重)
SKIP_TRACE="$REPO/data/logs/r2_upload_async_skip.log"
mkdir -p "$(dirname "$SKIP_TRACE")"
if [ -n "$DEPLOY_LOG" ]; then
  echo "⚠ r2_upload_async 锁跳过(锁 $LOCKPATH 被占, 已有实例在跑负责完成, 本次不执行上传; 已写并发跳过标记 $PENDING_FILE, 在跑实例收尾会增量补跑, 同日内数据上 R2)。$NOW_STR" >> "$DEPLOY_LOG"
fi
echo "⚠ r2_upload_async 锁跳过(锁 $LOCKPATH 被占, 已有实例在跑负责完成; 并发跳过标记已写 $PENDING_FILE, 在跑实例收尾增量补跑)。$NOW_STR" >> "$SKIP_TRACE"

# 3. latest.md + 普通级 notify(--alert-issue 写 data/alerts/latest.md; 非 --severe;
#    dedup 21600=6h 防并发重复触发时轰炸; on_skip_notify.sh 同款骨架, 去 severe)。
"$PY" "$REPO/scripts/notify.py" "R2上传异步锁跳过 $(date '+%m-%d %H:%M')" \
  "R2 上传异步任务(r2_upload_async.sh)锁跳过: 检测到另一实例正在运行(锁 $LOCKPATH 被占), 本次跳过未执行上传。<br>时间: $NOW_STR<br>跳过=正常降级+同日内补跑: 已在跑那趟收尾检测到并发跳过标记, 会增量补跑数据通道一次(读当前本地文件, 覆盖本趟新 export), 上传幂等+增量指纹+verify-r2 对账, 不拖到下一趟 deploy。如非预期(无其他实例在跑), 检查 $LOCKPATH 是否残留或进程是否卡死。" \
  --from-prefix "[提示]" \
  --alert-issue "r2_upload_async 锁跳过: 已有实例在运行或锁残留($LOCKPATH)" \
  --dedup-key "r2_upload_async_skip:$LOCKPATH" --dedup-window 21600 \
  $DRY_FLAG || true
