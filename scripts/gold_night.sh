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

# 2) commit + push global-3m/6m/1y.json 到 main (独立 worktree, 持 deploy.lock 串行)
#    global-3y/5y/all/extras-all 已 .gitignore 移出(R2 托管), 不进 git, 走 upload_r2.
#    参考 intraday_snapshot.sh 部署模式: worktree detached @ origin/main + cp + git add + rebase 兜底.
COMMIT_MSG="data update [gold_night] $(date +%Y-%m-%d_%H:%M)"
export GOLD_NIGHT_COMMIT_MSG="$COMMIT_MSG"
ALERT_TIME=$(date '+%m-%d %H:%M')
export ALERT_TIME
echo "-> commit + push global JSON 到 main (worktree, 持 deploy 锁) msg=\"${COMMIT_MSG}\" ..." | tee -a "$LOG"
PUSH_RC=0
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash -c '
  set -euo pipefail
  PUSH_RC=0
  REPO="${REPO:-/Users/linhuichen/code/trade-data}"
  GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
  PY="$REPO/.venv/bin/python"

  git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG"
  git -C "$GIT_REPO" worktree prune

  WORKTREE=$(mktemp -d /tmp/trade_gold_night_wt.XXXXXX)
  cleanup() {
    git -C "$GIT_REPO" worktree remove "$WORKTREE" --force 2>/dev/null || rm -rf "$WORKTREE"
  }
  trap cleanup EXIT

  if ! git -C "$GIT_REPO" worktree add --detach "$WORKTREE" origin/main 2>&1 | tee -a "$LOG"; then
    echo "✗ 创建 work tree 失败" >&2
    exit 1
  fi

  cd "$WORKTREE"

  # 从 REPO 拷贝采集器刚写的 global-*.json + .gz 到 worktree
  # (trade-data 架构: 采集器写 trade-data/static-site/data/, git 操作在 trade 仓库 worktree)
  cp -p "$REPO/static-site/data/"global-*.json static-site/data/ 2>/dev/null || true
  cp -p "$REPO/static-site/data/"global-*.json.gz static-site/data/ 2>/dev/null || true

  # 只 add global-3m/6m/1y (3y/5y/all/extras-all 被 .gitignore 移出 R2 托管, git add 会跳过 ignored)
  git add static-site/data/global-3m.json static-site/data/global-3m.json.gz \
          static-site/data/global-6m.json static-site/data/global-6m.json.gz \
          static-site/data/global-1y.json static-site/data/global-1y.json.gz 2>&1 | tee -a "$LOG" || true

  # 清掉非 add 列表的 unstaged 残留(防 rebase 阻塞, 参考 intraday_snapshot.sh L225)
  git checkout -- . 2>/dev/null || true

  if git diff --cached --quiet; then
    echo "✓ global JSON 无变更, 跳过 commit" | tee -a "$LOG"
  else
    git commit -m "$GOLD_NIGHT_COMMIT_MSG" 2>&1 | tee -a "$LOG"
    echo "✓ git commit 完成(worktree @ main)" | tee -a "$LOG"
  fi

  # R2 上传 global-3y/5y/all/extras-all (>=1MB, .gitignore 移出, 前端 dataUrl 走 R2 直链 ssd.fx8.store)
  # upload-data-large 遍历 data/ 顶层上传 >=1MB 或大 range 文件(幂等, 含其他大文件无妨)
  echo "-> upload_r2 upload-data-large (global 大 range 走 R2)..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/upload_r2.py" upload-data-large 2>&1 | tee -a "$LOG" || \
    echo "⚠ upload-data-large 失败/无大文件, 不阻塞 git push" | tee -a "$LOG"

  # push 含 rebase 兜底(参考 intraday_snapshot.sh L267-307 / deploy.sh L155-186)
  # 严禁 force-with-lease / force push(CLAUDE.md §8 铁律); rebase 失败 abort 退出待人工.
  set +e
  git push origin HEAD:main 2>&1 | tee -a "$LOG"
  PUSH_RC=$?
  if [ "$PUSH_RC" -ne 0 ]; then
    git fetch origin main 2>&1 | tee -a "$LOG" || true
    if git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
      echo "⚠ push 返回 $PUSH_RC 但 HEAD 已在 origin/main(并发已推), 视为幂等成功" | tee -a "$LOG"
      PUSH_RC=0
    else
      echo "-> push non-fast-forward, rebase 后重试一次..." | tee -a "$LOG"
      git rebase origin/main 2>&1 | tee -a "$LOG"
      REBASE_RC=$?
      if [ "$REBASE_RC" -eq 0 ]; then
        git push origin HEAD:main 2>&1 | tee -a "$LOG"
        PUSH_RC=$?
      else
        git rebase --abort 2>/dev/null || true
        echo "✗ rebase origin/main 失败(数据 JSON 可能冲突), 已 abort" | tee -a "$LOG"
        PUSH_RC=1
      fi
    fi
  fi
  set -e

  if [ "$PUSH_RC" -ne 0 ]; then
    echo "✗ git push 失败(rebase 后仍失败), 发告警 + 写 alerts/latest.md" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" \
      "[告警] gold_night push失败(非ff) ${ALERT_TIME}" \
      "gold_night 推 main 失败, rebase 重试后仍失败. 线上 global JSON 滞后, 需手动重跑 bash scripts/gold_night.sh.<br>日志: $LOG" \
      --severe --from-prefix "[告警]" \
      --alert-issue "gold_night git push 失败(非 fast-forward, rebase 重试后仍失败)" \
      --alert-log "$LOG" 2>&1 | tail -3 | tee -a "$LOG" || true
    exit "$PUSH_RC"
  fi
  echo "✓ git push origin HEAD:main 完成" | tee -a "$LOG"
' 2>&1
PUSH_RC=$?
if [ "$PUSH_RC" -ne 0 ]; then
  echo "✗ commit/push 失败(退出码 ${PUSH_RC})" | tee -a "$LOG" >&2
  exit "$PUSH_RC"
fi

echo "=== gold_night.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"

# 3) 刷新 schedule_stats.json(gold_night 运行统计, 失败不阻塞)
#    gen_schedule_stats 扫 launchd plist 识别任务; push_schedule_stats 独立 push 绕过 deploy 时序.
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" | tail -1 || \
  echo "⚠ gen_schedule_stats 失败, 不阻塞" | tee -a "$LOG"
bash "$REPO/scripts/push_schedule_stats.sh" 2>&1 | tee -a "$LOG" || \
  echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit 0
