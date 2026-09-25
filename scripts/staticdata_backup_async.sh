#!/usr/bin/env bash
# staticdata_backup_async.sh - staticdata 灾备第2层备份异步任务(2026-09-25 pending #110)
#
# 背景: staticdata 备份段(原 deploy.sh L946-1005)是 update_all 主链最大耗时单点:
#   9-24 占主链 ~44-50%(31-35min/71min); 9-25 05:00 只变 58 文件仍 ~22min(固定开销
#   rsync 全量比对 2.7G/32125 文件 + git add 3.2G 仓库)。P1 方案 = 从 deploy 主链拆出
#   异步执行, 主链不等(触发即返回), 备份本体在后台独立跑。
#
# 本脚本即异步备份本体:
#   - 由 deploy.sh 内部在 push main 成功后触发(覆盖全部 deploy 调用方, 零改动):
#     update_all / etf_national_team_backfill / futures_backfill / public_fund_daily /
#     lhb_backfill / rzhb_backfill / public_fund_full / public_fund_quarterly 等。
#     云上走 systemd transient service(独立 cgroup, deploy 退出不清理);
#     无 systemd 环境(本地开发)fallback nohup。
#   - 持 /tmp/trade_deploy.lock(阻塞 + 排队超时护栏): 防与并发 deploy/staticdata_sync.sh
#     并发写同一 staticdata git 仓库(git index.lock 冲突 + add 半截 JSON)。deploy 触发本
#     脚本时锁仍被 deploy 持有 → with_lock 阻塞等到 deploy 退出(秒级)再开跑, 零并发写;
#     多次触发(如 17:50 async 还在跑时 20:07 etf deploy 又触发)→ with_lock 排队, 不并发。
#   - 积压兜底: 待提交变更 >5000 文件 或 总字节 >300MB → 仅 rsync 磁盘留档 + 告警,
#     跳过 git commit/push(次日 deploy 的 rsync 全量自然追平, 数据不丢; 防大 push 拖死
#     async 自身 + git gc 膨胀)。
#   - 失败必须告警(不静默): notify.py --severe + --alert-issue(写 data/alerts/latest.md),
#     沿用现有告警链(update_all/deploy 同款), 让 schedule_monitor 发现。
#   - 幂等: rsync + git add -A, 无变更跳过 commit; 重复跑安全(重复触发由 with_lock 排队)。
#   - step 打点(date +%s)落日志, 供复盘 rsync vs git add 谁是大头。
#
# 日志: $REPO/data/logs/staticdata_backup_async_YYYYMMDD_HHMMSS.log
# 用法: 由 deploy.sh 自动触发; 也可手动: bash scripts/staticdata_backup_async.sh <trigger>
#   测试(严禁写生产 staticdata 仓库): STATICDATA_REPO 指向 /tmp 临时 git 仓库,
#   STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 让 notify 走 --dry-run(不真发邮件/飞书)。
set -u
# 不 set -e: 每步显式判退出码(best-effort, 失败不中断后续步骤)。

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
STATICDATA_REPO="${STATICDATA_REPO:-/Users/linhuichen/code/trade-data-signal-staticdata}"
PY="${PY:-$REPO/.venv/bin/python}"
TRIGGER="${1:-all}"
LOCK="/tmp/trade_deploy.lock"

# 云上单仓: 本机硬编码 staticdata 路径不存在时, 回退 GIT_REPO 派生的 sibling 路径
# (云上 GIT_REPO=/home/ubuntu/code/trade-data-signal -> ...-staticdata), 防云上静默跳过备份
# (2026-09-13 迁移残留修; 同 deploy.sh/staticdata_sync.sh 同款回退)。
if [ ! -d "$STATICDATA_REPO/.git" ] && [ -n "${GIT_REPO:-}" ] && [ -d "${GIT_REPO}-staticdata/.git" ]; then
  STATICDATA_REPO="${GIT_REPO}-staticdata"
fi

# ── 持锁重入 ──
# 整个备份在 /tmp/trade_deploy.lock 内执行, 避免并发写同一 staticdata git 仓库。
# 阻塞 + 排队超时护栏: deploy 触发本脚本时锁仍被 deploy 持有 → 阻塞等到 deploy 退出再跑;
# 若排在前面的 async/consumer 拖太久(>3600s)则告警 + 优雅跳过(exit 0), 防本脚本傻等。
if [ "${STATICDATA_BACKUP_LOCKED:-}" != "1" ]; then
  export STATICDATA_BACKUP_LOCKED=1
  exec "$PY" "$GIT_REPO/scripts/with_lock.py" --block-timeout 3600 "$LOCK" bash "$0" "$@"
fi

LOGDIR="$REPO/data/logs"
LOG="$LOGDIR/staticdata_backup_async_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$LOGDIR"
echo "=== staticdata_backup_async 开始 $(date '+%Y-%m-%d %H:%M:%S') (trigger=$TRIGGER) ===" | tee -a "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO STATICDATA_REPO=$STATICDATA_REPO" | tee -a "$LOG"

if [ ! -d "$STATICDATA_REPO/.git" ]; then
  echo "⚠ staticdata 仓库不存在($STATICDATA_REPO),跳过备份" | tee -a "$LOG"
  exit 0
fi

# notify 测试钩子: STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 → notify 走 --dry-run(自验用, 不真发)。
_NOTIFY_DRY=()
if [ "${STATICDATA_BACKUP_NOTIFY_DRY_RUN:-}" = "1" ]; then
  _NOTIFY_DRY=(--dry-run)
fi

echo "-> staticdata 备份（best-effort, 异步）..." | tee -a "$LOG"
STATICDATA_FAIL=0

# 1. rsync DB原件到 staticdata/db/（本地备份，不进 git，.gitignore 排除 db/*.db）
_STEP_START=$(date +%s)
rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/" 2>&1 | tee -a "$LOG" || {
  echo "⚠ staticdata DB rsync 失败,不阻塞" | tee -a "$LOG"
  STATICDATA_FAIL=1
}
echo "  [step1 DB rsync] $(( $(date +%s) - _STEP_START ))s" | tee -a "$LOG"

# 2. rsync 配置（wrangler.jsonc + launchd plist 模板脱敏）
# mkdir -p config/launchd 补原 deploy.sh 缺失(原代码假设目录已存在, 新仓库首跑会 sed 重定向失败)。
_STEP_START=$(date +%s)
cp "$GIT_REPO/wrangler.jsonc" "$STATICDATA_REPO/config/wrangler.jsonc" 2>/dev/null || true
mkdir -p "$STATICDATA_REPO/config/launchd"
for _plist in ~/Library/LaunchAgents/com.trade.*.plist; do
  [ -f "$_plist" ] && sed 's|/Users/linhuichen|/Users/USER|g' "$_plist" > "$STATICDATA_REPO/config/launchd/$(basename "$_plist")" 2>/dev/null || true
done
echo "  [step2 config] $(( $(date +%s) - _STEP_START ))s" | tee -a "$LOG"

# 3. rsync 全量 JSON 到 staticdata（全量备份，DB 不在此目录）
_STEP_START=$(date +%s)
rsync -a \
  "$REPO/static-site/data/" "$STATICDATA_REPO/data/" 2>&1 | tee -a "$LOG" || {
  echo "⚠ staticdata JSON rsync 失败,不阻塞" | tee -a "$LOG"
  STATICDATA_FAIL=1
}
echo "  [step3 JSON rsync] $(( $(date +%s) - _STEP_START ))s" | tee -a "$LOG"

# 4. git commit + push（差异化日志，best-effort）——积压超阈值跳过 commit 仅磁盘留档
# 阈值依据(researcher 报告 update-all-staticdata-backup-eval-20260925.md): 正常日 58~487 文件
# ≈22min 固定开销; 9-22 积压 25789 文件 ≈70-75min(rsync 拉长 + push 7min + GitHub 大文件警告)。
# >5000 文件 或 变更文件当前总字节 >300MB → 跳过 commit/push, 仅 rsync 磁盘留档 + 告警;
# 次日 deploy 的 rsync 全量自然追平 git, 数据不丢, 只 git 历史缺一档(防大 push 拖死 async 自身)。
# 字节口径 = 变更文件当前 wc -c 总和(保守估计: 大 JSON 即使只改 100B 也按全文件计, 与 GitHub
# 仓库膨胀口径一致, 宁高勿低触发跳过)。
_STEP_START=$(date +%s)
git -C "$STATICDATA_REPO" add -A 2>&1 | tee -a "$LOG" || true
if git -C "$STATICDATA_REPO" diff --cached --quiet 2>/dev/null; then
  echo "✓ staticdata 无新变更,跳过 commit" | tee -a "$LOG"
else
  _CHANGED=$(git -C "$STATICDATA_REPO" diff --cached --name-only)
  _N=$(printf '%s\n' "$_CHANGED" | grep -c . || true)
  _BYTES=0
  _OVERSIZE=0
  # 文件数阈值短路: >5000 直接跳过(积压场景 32k 文件逐个 wc 白耗 ~30s, 阈值已定不再需要字节数)。
  if [ "$_N" -gt 5000 ]; then
    _OVERSIZE=1
  else
    # 字节口径 = 变更文件当前 wc -c 总和(保守估计: 大 JSON 即使只改 100B 也按全文件计, 与 GitHub
    # 仓库膨胀口径一致, 宁高勿低触发跳过)。
    while IFS= read -r _f; do
      [ -z "$_f" ] && continue
      if [ -f "$STATICDATA_REPO/$_f" ]; then
        _sz=$(wc -c < "$STATICDATA_REPO/$_f" 2>/dev/null || echo 0)
        _BYTES=$((_BYTES + _sz))
      fi
    done <<< "$_CHANGED"
    [ "$_BYTES" -gt 300000000 ] && _OVERSIZE=1
  fi
  echo "  [变更量] 文件数=$_N 字节=$_BYTES 超阈值=$_OVERSIZE" | tee -a "$LOG"
  if [ "$_OVERSIZE" = "1" ]; then
    echo "⚠ 变更量超阈值(文件=$_N >5000 或 字节=$_BYTES >300MB), 跳过 commit/push 仅磁盘留档(积压兜底)" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" "[告警] staticdata 变更量超阈值跳过 commit" \
      "staticdata 备份变更量超阈值(文件 ${_N} >5000 或 字节 ${_BYTES} >300MB), 本次仅 rsync 磁盘留档未 commit/push。<br>数据已在 $STATICDATA_REPO/data/ 与 db/ 磁盘留档(灾备第1/2层安全), 次日 deploy 的 rsync 全量自然追平 git。<br>如连续多日触发, 需评估: 是否大 JSON 需入 .gitignore(>50MB 先例 signal_kelly_trades*.json)<br>日志: $LOG" \
      --severe --from-prefix "[告警]" --alert-issue "staticdata备份变更量超阈值跳过commit" --alert-log "$LOG" \
      --dedup-key "staticdata_backup_oversize_skip" --dedup-window 21600 "${_NOTIFY_DRY[@]}" 2>&1 | tee -a "$LOG" || true
  else
    # commit message 详细化：标题含触发 pipeline 名($TRIGGER) + 变更文件数；body 按顶层目录分类计数 top5
    _BODY=$(printf '%s\n' "$_CHANGED" | sed 's|/.*||' | sort | uniq -c | sort -rn | head -5 | awk '{printf "%s %s\n", $2, $1}')
    if ! git -C "$STATICDATA_REPO" commit -m "data backup [$TRIGGER] $(date +%Y-%m-%d_%H:%M) - ${_N} files" -m "$_BODY" 2>&1 | tee -a "$LOG"; then
      echo "⚠ staticdata commit 失败(best-effort)" | tee -a "$LOG"
      STATICDATA_FAIL=1
    else
      # git push 超时保护(同 deploy.sh git_push_timeout 精神): 防 push 卡 GitHub 22 端口
      # 死拽 /tmp/trade_deploy.lock 连锁卡后续所有 deploy(2026-09-15 事故同根因)。
      # 正常 push 6-7min(大 commit), 超 900s 判死并 kill ssh 子进程释放锁。
      _PUSH_TMP=$(mktemp)
      git -C "$STATICDATA_REPO" push origin main >"$_PUSH_TMP" 2>&1 &
      _push_pid=$!
      _slept=0
      _push_rc=""
      while kill -0 "$_push_pid" 2>/dev/null; do
        sleep 5
        _slept=$((_slept + 5))
        if [ "$_slept" -ge 900 ]; then
          echo "⚠ staticdata push 超 900s 未退出, kill pid=$_push_pid 释放 deploy.lock" | tee -a "$LOG"
          pkill -TERM -P "$_push_pid" 2>/dev/null || true
          kill -TERM "$_push_pid" 2>/dev/null; sleep 2
          pkill -KILL -P "$_push_pid" 2>/dev/null || true
          kill -KILL "$_push_pid" 2>/dev/null || true
          wait "$_push_pid" 2>/dev/null || true
          _push_rc=124
          break
        fi
      done
      if [ -z "$_push_rc" ]; then
        wait "$_push_pid"; _push_rc=$?
      fi
      tail -n 30 "$_PUSH_TMP" >> "$LOG" 2>/dev/null || true
      rm -f "$_PUSH_TMP"
      if [ "$_push_rc" -ne 0 ]; then
        echo "⚠ staticdata push 失败(best-effort, rc=$_push_rc)" | tee -a "$LOG"
        STATICDATA_FAIL=1
      fi
    fi
  fi
fi
echo "  [step4 git add+commit+push] $(( $(date +%s) - _STEP_START ))s" | tee -a "$LOG"

if [ "$STATICDATA_FAIL" = "1" ]; then
  "$PY" "$REPO/scripts/notify.py" "[告警] staticdata备份失败" \
    "staticdata_backup_async.sh staticdata备份部分失败(不阻塞主链)<br>日志: $LOG" \
    --severe --from-prefix "[告警]" --dedup-key staticdata_backup_fail --dedup-window 3600 \
    "${_NOTIFY_DRY[@]}" 2>&1 | tee -a "$LOG" || true
  echo "✗ staticdata 备份完成但部分失败(已告警)" | tee -a "$LOG"
  exit 1
fi
echo "✓ staticdata 备份完成 $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
