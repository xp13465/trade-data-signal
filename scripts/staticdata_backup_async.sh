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
#     触发失败且 systemd 在跑(/run/systemd/system 存在) → alert-only(改1 C-1: KillMode=
#     control-group 下 nohup 子进程随 deploy 被连带杀, 不加 nohup); 本地无 systemd(mac) → nohup fallback。
#   - 持 /tmp/trade_deploy.lock(阻塞 + 排队超时护栏): 防与并发 deploy/staticdata_sync.sh
#     并发写同一 staticdata git 仓库(git index.lock 冲突 + add 半截 JSON)。deploy 触发本
#     脚本时锁仍被 deploy 持有 → with_lock 阻塞等到 deploy 退出(秒级)再开跑, 零并发写;
#     多次触发(如 17:50 async 还在跑时 20:07 etf deploy 又触发)→ with_lock 排队, 不并发。
#   - 积压兜底: 待提交变更 >5000 文件 或 总字节 >500MB → 仅 rsync 磁盘留档 + 告警,
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
# pipefail(2026-09-25 审查整改补): 管道退出码取首命令而非 `| tee` 的 tee(恒 0),
# 防 `cmd | tee` 首命令失败(rsync DB/JSON、git commit)被静默吞掉 → 心跳照写 ok,
# 新加的 C-3「36h 无 ok 告警」永不触发。审计全部 | tee 管道: notify 三处带 `|| true`
# (notify 失败不置位是良性, 语义不变); 其余非 echo 管道共 4 处: rsync DB(L118)/rsync JSON(L136)/
# git add(L151, PIPESTATUS[0] 判定)/git commit(L191)——均已在各步显式判定退出码; echo 纯日志管道无误伤。
set -o pipefail
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

# ── 改4 C-3 心跳状态文件(2026-09-25 审查整改): 供 schedule_monitor 检查异步备份新鲜度 ──
# 开始写 {ts,result:"running"}, 结束写 {ts,result:ok|fail|skip_oversize,files,bytes,duration_s}。
# 必须原子写(tmp+mv): 被 systemd 超时强杀会留半截(2026-09-21 signal_kelly_trades 半截先例)。
# 路径=$REPO/data/(与 schedule_monitor.sh LOG_DIR 同约定), 不进 git(deploy 只 add static-site/data/
# + min, 根 data/ 是 gitignore/未跟踪区); schedule_monitor.sh 用同路径常量读。
HB_FILE="$REPO/data/staticdata_backup_heartbeat.json"
_HB_START=$(date +%s)
_hb_write() {
  # 原子写: 写 $TMP 再 mv(禁直接重定向到目标, 防半截)。
  _hb_result="$1"; _hb_files="${2:-0}"; _hb_bytes="${3:-0}"
  _hb_ts=$(date '+%Y-%m-%d %H:%M:%S')
  _hb_dur=$(( $(date +%s) - _HB_START ))
  _hb_tmp="$REPO/data/.staticdata_backup_heartbeat.tmp.$$"
  if printf '{"ts":"%s","result":"%s","files":%s,"bytes":%s,"duration_s":%s}\n' \
      "$_hb_ts" "$_hb_result" "$_hb_files" "$_hb_bytes" "$_hb_dur" > "$_hb_tmp" 2>/dev/null && \
      mv "$_hb_tmp" "$HB_FILE" 2>/dev/null; then
    :
  else
    rm -f "$_hb_tmp" 2>/dev/null || true
    echo "⚠ 心跳状态写入失败($HB_FILE)" | tee -a "$LOG"
  fi
}

# notify 测试钩子: STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 → notify 走 --dry-run(自验用, 不真发)。
# 定义须在仓库存在性检查之前(改3 C-5 降级 notify 也要走测试钩子)。
_NOTIFY_DRY=()
if [ "${STATICDATA_BACKUP_NOTIFY_DRY_RUN:-}" = "1" ]; then
  _NOTIFY_DRY=(--dry-run)
fi

if [ ! -d "$STATICDATA_REPO/.git" ]; then
  # 改3 C-5(2026-09-25 审查整改): 两个候选仓库($STATICDATA_REPO 与 ${GIT_REPO}-staticdata)
  # 都不存在 → 原实现静默 exit 0(备份缺口无人知)。改为降级 notify(不必 --severe) + 日志
  # 写清两个候选路径都查过(路径打出来)。dedup 6h 防每次 deploy 重复轰炸。
  echo "⚠ staticdata 仓库不存在(已查候选1: ${STATICDATA_REPO:-无}, 候选2: ${GIT_REPO:-无}-staticdata), 跳过备份" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[通知] staticdata 仓库不存在, 跳过备份" \
    "staticdata 备份仓库不存在, 本次跳过备份(降级, 非 severe, 不影响 deploy 主链)。<br>已查两个候选路径: 候选1 ${STATICDATA_REPO:-无} / 候选2 ${GIT_REPO:-无}-staticdata<br>生产云上至少应存在 ${GIT_REPO:-无}-staticdata 灾备第2层仓库, 若缺失需人工核查 staticdata git 仓库初始化/迁移。<br>日志: $LOG" \
    --from-prefix "[通知]" --alert-issue "staticdata备份仓库缺失" --alert-log "$LOG" \
    --dedup-key staticdata_backup_repo_missing --dedup-window 21600 "${_NOTIFY_DRY[@]}" 2>&1 | tee -a "$LOG" || true
  exit 0
fi

echo "-> staticdata 备份（best-effort, 异步）..." | tee -a "$LOG"
STATICDATA_FAIL=0
_OVERSIZE=0
_hb_write "running"   # 改4 C-3: 开始心跳(备份启动前; 仓库缺失早退不写, 留上次 ok 心跳自然变旧触发 C3 停摆告警)

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

# 3.5 大 JSON 移出 staticdata git + R2 私有桶备份(2026-09-25, feat/large-json-r2-core)
# 背景: 7 个大 JSON(>20MB, ~320MB)天天变天天进 delta, .git 膨胀 3.3G, 9-25 撞 >300MB 积压阈值跳过 commit。
# 本步 = 排除规则单一源 large_json_excludes.py 维护 .gitignore 受管区块(幂等, 精确路径 /data/...),
# 再 upload_r2.py upload-large-json 按 large-json/<YYYY-MM-DD>/<相对data路径>.gz gzip 上传私有桶
# signal-backup(幂等: 内容没变跳过 PUT)+ 日14天/周8周/月12月滚动保留 + 自动重写 docs/large-json-backup-manifest.md。
# 失败不阻塞后续 git 步骤(大文件仍在 git 由原链路兜底), 置 STATICDATA_FAIL=1 进心跳与严重告警。
# 注意: git rm --cached(真正移出 git)由一次性迁移脚本 migrate_large_json_out_of_git.sh 完成,
# 本步只保证 .gitignore 区块最新(防已排除文件被 git add -A 重新纳入) + R2 备份持续。
_STEP_START=$(date +%s)
if "$PY" "$GIT_REPO/scripts/large_json_excludes.py" --repo "$STATICDATA_REPO" 2>&1 | tee -a "$LOG"; then
  echo "  [step3.5a large-json .gitignore 区块] ✓" | tee -a "$LOG"
else
  echo "⚠ large_json_excludes.py 维护 .gitignore 受管区块失败, 不阻塞" | tee -a "$LOG"
  STATICDATA_FAIL=1
fi
if STATICDATA_REPO="$STATICDATA_REPO" GIT_REPO="$GIT_REPO" "$PY" "$GIT_REPO/scripts/upload_r2.py" upload-large-json 2>&1 | tee -a "$LOG"; then
  echo "  [step3.5b large-json R2 上传] ✓" | tee -a "$LOG"
else
  echo "⚠ upload_r2.py upload-large-json 失败, 不阻塞" | tee -a "$LOG"
  STATICDATA_FAIL=1
fi
echo "  [step3.5 large-json 排除+R2] $(( $(date +%s) - _STEP_START ))s" | tee -a "$LOG"

# 4. git commit + push（差异化日志，best-effort）——积压超阈值跳过 commit 仅磁盘留档
# 阈值依据(researcher 报告 update-all-staticdata-backup-eval-20260925.md): 正常日 58~487 文件
# ≈22min 固定开销; 9-22 积压 25789 文件 ≈70-75min(rsync 拉长 + push 7min + GitHub 大文件警告)。
#   - 积压兜底阈值 500MB(2026-09-25 抬升, feat/large-json-r2-core): 7 个大 JSON(~320MB, 天天
#     变天天进 delta)已移出 staticdata git、改走 R2 私有桶 large-json/ 每日备份(见 step3.5),
#     正常日变更字节不再触 300MB; 抬到 500MB 给异常日留余量(如首跑大回填), 防误触跳过 commit。
#     >5000 文件 或 变更文件当前总字节 >500MB → 跳过 commit/push, 仅 rsync 磁盘留档 + 告警;
# 次日 deploy 的 rsync 全量自然追平 git, 数据不丢, 只 git 历史缺一档(防大 push 拖死 async 自身)。
# 字节口径 = 变更文件当前 wc -c 总和(保守估计: 大 JSON 即使只改 100B 也按全文件计, 与 GitHub
# 仓库膨胀口径一致, 宁高勿低触发跳过)。
_STEP_START=$(date +%s)
git -C "$STATICDATA_REPO" add -A 2>&1 | tee -a "$LOG"
# 改2 C-2(2026-09-25 审查整改): add 退出码必须判定(原 `|| true` 吞掉 add 失败 → diff --cached
# 为空 → 误打印"✓ staticdata 无新变更,跳过 commit", 看着正常实际 git 历史缺口)。
# 无 pipefail 下管道退出码=tee(恒 0), 必须取 PIPESTATUS[0]; add 失败 → STATICDATA_FAIL=1 +
# 日志明确 + 不得再进"无新变更"分支(直接跳收口段)。
if [ "${PIPESTATUS[0]:-0}" -ne 0 ]; then
  echo "⚠ git add 失败(staticdata 仓库 $STATICDATA_REPO), 置 STATICDATA_FAIL=1, 跳过 commit(git 历史缺口, 需人工排查)" | tee -a "$LOG"
  STATICDATA_FAIL=1
elif git -C "$STATICDATA_REPO" diff --cached --quiet 2>/dev/null; then
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
    [ "$_BYTES" -gt 500000000 ] && _OVERSIZE=1
  fi
  echo "  [变更量] 文件数=$_N 字节=$_BYTES 超阈值=$_OVERSIZE" | tee -a "$LOG"
  if [ "$_OVERSIZE" = "1" ]; then
    echo "⚠ 变更量超阈值(文件=$_N >5000 或 字节=$_BYTES >500MB), 跳过 commit/push 仅磁盘留档(积压兜底)" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" "[告警] staticdata 变更量超阈值跳过 commit" \
      "staticdata 备份变更量超阈值(文件 ${_N} >5000 或 字节 ${_BYTES} >500MB), 本次仅 rsync 磁盘留档未 commit/push。<br>数据已在 $STATICDATA_REPO/data/ 与 db/ 磁盘留档(灾备第1/2层安全), 次日 deploy 的 rsync 全量自然追平 git。<br>如连续多日触发, 需评估: 是否大 JSON 需入 .gitignore(>50MB 先例 signal_kelly_trades*.json)<br>日志: $LOG" \
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

# 改4 C-3: 收口前写最终心跳(ok/fail/skip_oversize + files/bytes/duration)。
# STATICDATA_FAIL=1 优先(fail 已由脚本内 --severe notify 覆盖, C3 检查不重复告警 fail);
# _OVERSIZE=1(积压超阈值跳过 commit) → skip_oversize(该分支已有超阈值跳过 --severe notify)。
if [ "$STATICDATA_FAIL" = "1" ]; then
  _hb_write "fail" "${_N:-0}" "${_BYTES:-0}"
elif [ "${_OVERSIZE:-0}" = "1" ]; then
  _hb_write "skip_oversize" "${_N:-0}" "${_BYTES:-0}"
else
  _hb_write "ok" "${_N:-0}" "${_BYTES:-0}"
fi

if [ "$STATICDATA_FAIL" = "1" ]; then
  "$PY" "$REPO/scripts/notify.py" "[告警] staticdata备份失败" \
    "staticdata_backup_async.sh staticdata备份部分失败(不阻塞主链)<br>日志: $LOG" \
    --severe --from-prefix "[告警]" --dedup-key staticdata_backup_fail --dedup-window 3600 \
    "${_NOTIFY_DRY[@]}" 2>&1 | tee -a "$LOG" || true
  echo "✗ staticdata 备份完成但部分失败(已告警)" | tee -a "$LOG"
  exit 1
fi
echo "✓ staticdata 备份完成 $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$LOG"
