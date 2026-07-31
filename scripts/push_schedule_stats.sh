#!/bin/bash
# push_schedule_stats.sh - 独立推送 schedule_stats.json 到 main（绕过 deploy.sh 时序矛盾）
#
# 根因（2026-07-30 方案C+R2 根治）：
#   deploy.sh L216 for 循环 git add schedule_stats.json 时，gen_schedule_stats.py
#   尚未运行（7 任务脚本在 gen_stats 之前 push / intraday_snapshot push 块在 gen_stats
#   之前），致 push 的 schedule_stats.json 是上一轮旧版 -> 前端"执行统计"滞后一轮。
#   原"方案A 移到结尾调 gen_stats"只解决了 gen_stats 时序，但 push 仍依赖 deploy.sh
#   下一轮才带最新版 -> 滞后 1 轮（intraday 10min / backfill 次日）。
#
# 方案C+R2：gen_stats 后立即独立 push schedule_stats.json，绕过 deploy.sh 时序。
#   - 7 任务脚本（us_stock/rzhb/futures/lhb/etf/update_all/update_lab）结尾 gen_stats 后调本脚本
#   - intraday_snapshot.sh 选项2：gen_stats 后调本脚本（实时性最佳，当轮 schedule_stats 当轮上线）
#   - deploy.sh L216 移除 schedule_stats（不再由 deploy.sh push，避免和本脚本双写撞 git lock）
#
# 机制（复用 intraday_snapshot.sh L132-298 worktree + deploy.lock + rebase 兜底）：
#   - 持 deploy.lock 串行化 git（阻塞，等 intraday/deploy 释放；避免 index.lock 冲突）
#   - 独立 worktree（detached HEAD @ origin/main，不影响当前 feat 开发分支）
#   - rsync schedule_stats.json + gzip -> git add + commit + push origin HEAD:main
#   - non-ff fetch + rebase 兜底（严禁 force push，§8 铁律；rebase 失败 abort 退出待人工）
#   - push 失败 notify.py --severe 告警（让 schedule_monitor 48h 监控发现）
#
# 用法：bash scripts/push_schedule_stats.sh
# 日志：data/logs/push_schedule_stats_YYYYMMDD_HHMM.log
# 退出码：0 = push 成功 / 无变更跳过；非 0 = push 失败（gen_stats 失败不在此脚本职责，
#         源文件缺失直接 exit 1 不 push 旧版）
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/push_schedule_stats_${STAMP}.log"
export LOG   # 让子 bash -c (commit+push 段) 继承 LOG，tee -a 可用

mkdir -p "$LOGDIR"
cd "$REPO"

echo "=== push_schedule_stats.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
echo "REPO=$REPO GIT_REPO=$GIT_REPO" | tee -a "$LOG"

# 源文件校验：gen_schedule_stats.py 未运行或失败致 schedule_stats.json 缺失 -> 不 push 旧版
SRC="$REPO/static-site/data/schedule_stats.json"
if [ ! -f "$SRC" ]; then
  echo "✗ 源文件不存在：$SRC（gen_schedule_stats.py 未运行？），跳过 push" | tee -a "$LOG" >&2
  exit 1
fi
echo "源文件：$SRC ($(stat -f '%z' "$SRC") bytes, mtime $(stat -f '%Sm' "$SRC"))" | tee -a "$LOG"

# commit + push schedule_stats.json 到 main 分支（独立 worktree，持 deploy 锁串行）
# 用环境变量传 commit message，避免 bash -c 引号转义问题（参考 intraday_snapshot.sh L127-128）
COMMIT_MSG="data update [schedule_stats] $(date +%Y-%m-%d_%H:%M)"
export SCHEDULE_COMMIT_MSG="$COMMIT_MSG"
echo "-> commit + push schedule_stats.json 到 main（独立 worktree，持 deploy 锁串行）msg=\"${COMMIT_MSG}\" ..." | tee -a "$LOG"
# 预初始化 PUSH_RC=0（防 set -u 下 bash -c 异常退出后外层引用未赋值 PUSH_RC 致 unbound 噪声）
PUSH_RC=0
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash -c '
  set -euo pipefail
  # 预初始化 PUSH_RC=0（防 set -u 下兜底分支引用未赋值 PUSH_RC 致 unbound 噪声）
  PUSH_RC=0
  REPO="${REPO:-/Users/linhuichen/code/trade}"
  GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
  # 主脚本 PY 未 export，子 bash -c 不继承非导出变量；此处必须重新定义
  # （参考 intraday_snapshot.sh L140-141，set -u 下 "$PY" 触发 unbound 致整个 commit+push 失败）
  PY="$REPO/.venv/bin/python"

  # 拉取最新 origin/main（worktree 基于此创建，确保 push 是 fast-forward）
  git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG"

  # 清理上次崩溃残留的 stale worktree 元数据
  git -C "$GIT_REPO" worktree prune

  # 创建独立 worktree（detached HEAD @ origin/main，即使 main 已被 trade checkout 也不冲突）
  WORKTREE=$(mktemp -d /tmp/trade_schedule_wt.XXXXXX)
  cleanup() {
    git -C "$GIT_REPO" worktree remove "$WORKTREE" --force 2>/dev/null || rm -rf "$WORKTREE"
  }
  trap cleanup EXIT

  if ! git -C "$GIT_REPO" worktree add --detach "$WORKTREE" origin/main 2>&1 | tee -a "$LOG"; then
    echo "✗ 创建 worktree 失败" >&2
    exit 1
  fi

  cd "$WORKTREE"

  # rsync schedule_stats.json（--checksum 强制 MD5 比对，size 不变+mtime同秒也覆盖；
  # 参考 intraday_snapshot.sh L173-174，schedule_stats last_run "11:30"->"13:05" size 不变
  # quick check 跳过致线上停滞，--checksum 根治）
  rsync -a --checksum "$REPO/static-site/data/schedule_stats.json" static-site/data/schedule_stats.json 2>&1 | tee -a "$LOG"

  # 生成 .gz（前端 fetchJSON 优先读 .gz，Decompression Stream 解压；
  # 不生成则线上 .gz 滞后 .json，前端读旧 .gz = 读旧数据根因）
  gzip -kf static-site/data/schedule_stats.json

  # 只 add schedule_stats（不碰其他文件，参考 intraday_snapshot.sh L191-211 精确文件列表）
  git add static-site/data/schedule_stats.json static-site/data/schedule_stats.json.gz 2>&1 | tee -a "$LOG" || true

  # 清掉非 add 列表的 unstaged 残留（rsync 可能带入其他 tracked 修改，影响 rebase；
  # 参考 intraday_snapshot.sh L213-220，git add 已暂存新数据，checkout -- . 还原工作区非 add 列表）
  git checkout -- .

  if git diff --cached --quiet; then
    echo "✓ schedule_stats.json 无变更，跳过 commit" | tee -a "$LOG"
  else
    git commit -m "$SCHEDULE_COMMIT_MSG" 2>&1 | tee -a "$LOG"
    echo "✓ git commit 完成（worktree @ main）" | tee -a "$LOG"
  fi

  # push + rebase 兜底（参考 intraday_snapshot.sh L250-297 / deploy.sh L141-160）
  #   worktree(detached HEAD @ 旧 origin/main + 1 本地 commit)，期间并发 agent 可能已推新
  #   commit 到 origin/main 致本地基址落后 = non-fast-forward。
  #   fetch 后判 HEAD 是否已在 origin/main（并发已推同内容=幂等成功）；
  #   本地落后则 rebase origin/main 后重试 push 一次。
  #   严禁 force-with-lease / force push（§8 铁律）；rebase 失败 abort 退出待人工。
  set +e  # push/rebase 失败不立即退出 bash -c，走兜底判断
  git push origin HEAD:main 2>&1 | tee -a "$LOG"
  PUSH_RC=$?
  if [ "$PUSH_RC" -ne 0 ]; then
    git fetch origin main 2>&1 | tee -a "$LOG" || true
    if git merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
      echo "⚠ push 返回 $PUSH_RC 但 HEAD 已在 origin/main（并发已推送），视为幂等成功"
      PUSH_RC=0
    else
      echo "-> push non-fast-forward，本地落后 origin/main，rebase 后重试一次 ..." | tee -a "$LOG"
      git rebase origin/main 2>&1 | tee -a "$LOG"
      REBASE_RC=$?
      if [ "$REBASE_RC" -eq 0 ]; then
        git push origin HEAD:main 2>&1 | tee -a "$LOG"
        PUSH_RC=$?
        if [ "$PUSH_RC" -ne 0 ]; then
          echo "✗ rebase 后重试 push 仍失败(退出码 $PUSH_RC)" | tee -a "$LOG"
        fi
      else
        git rebase --abort 2>/dev/null || true
        echo "✗ rebase origin/main 失败（数据 JSON 可能冲突），已 abort 保持工作区干净" | tee -a "$LOG"
        PUSH_RC=1
      fi
    fi
  fi
  set -e

  # push 最终失败 -> 告警（让 schedule_monitor 48h 监控发现）+ 退出非 0
  if [ "$PUSH_RC" -ne 0 ]; then
    echo "✗ git push origin HEAD:main 失败（rebase 重试后仍失败），发告警邮件 + 写 alerts/latest.md" | tee -a "$LOG"
    "$PY" "$REPO/scripts/notify.py" \
      "[告警] schedule_stats push失败(非ff) $(date '+%m-%d %H:%M')" \
      "push_schedule_stats 推 main 失败，rebase 重试后仍失败。线上 schedule_stats.json 滞后上一轮时点，需手动修复。<br>排查：cd $GIT_REPO && git fetch origin && git log --oneline -5 origin/main 看并发推的 commit；本地 worktree commit 已随 worktree 清理丢失，重跑 bash scripts/push_schedule_stats.sh 即可。<br>日志：$LOG" \
      --severe \
      --from-prefix "[告警]" \
      --alert-issue "push_schedule_stats git push 失败(非 fast-forward, rebase 重试后仍失败)" \
      --alert-log "$LOG" 2>&1 | tail -3 | tee -a "$LOG" || true
    exit "$PUSH_RC"
  fi
  echo "✓ git push origin HEAD:main 完成" | tee -a "$LOG"
' 2>&1
PUSH_RC=$?
if [ "$PUSH_RC" -ne 0 ]; then
  echo "✗ commit/push 失败（退出码 ${PUSH_RC}），写 stderr 告警" | tee -a "$LOG" >&2
  exit "$PUSH_RC"
fi

echo "=== push_schedule_stats.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
