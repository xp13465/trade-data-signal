#!/bin/bash
# intraday_snapshot.sh - 盘中实时快照采集（launchd 定时，盘中每 30 分钟）
#
# 跑 .venv/bin/python -m app.collector.intraday_snapshot（秒级）：
#   采腾讯9指数实时 + 同花顺行业实时涨跌幅，存 DB + dump static-site/data/intraday_snapshot.json
# 然后 commit + push 该 JSON 到 main 分支（部署分支），供前端"盘中实时小结"展示。
#   采集在主仓库跑（DB 持久化），commit+push 在独立 worktree 操作 main（不影响当前 feat 开发）。
#
# 进程互斥：
#   - 快照锁 /tmp/trade_intraday_snapshot.lock（--nb 非阻塞）：防快照自身重复，秒级。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git add/commit/push，避免和
#     update_all pipeline 撞 .git/index.lock。阻塞等待 update_all 释放后执行。
#
# 非交易日：默认跳过（不浪费 git commit）。force 模式可绕过（手动补测）。
# 旧串行 update_all.sh 末尾也顺带跑快照但不 push；本脚本独立 push。
#
# 用法：bash scripts/intraday_snapshot.sh [force]
#   force: 绕过交易日闸门，非交易日也跑（补测/校准）
# 日志：data/logs/intraday_snapshot_YYYYMMDD_HHMM.log
# 退出码：快照采集退出码（git push 失败也计入）。
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 始终在 trade 仓库(trade-data 不 git init)
export REPO   # 让子 bash -c (commit+push 段) 继承 REPO，trade-data 跑时采集路径用 trade-data
export GIT_REPO   # 让子 bash -c 继承 GIT_REPO，git worktree 操作在 trade 仓库
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/intraday_snapshot_${STAMP}.log"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持快照锁重跑自己，INTRADAY_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过（秒级任务不该撞，撞了就跳过）。
if [ -z "${INTRADAY_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_intraday_snapshot.lock \
    env INTRADAY_LOCKED=1 bash "$0" "$@"
fi

echo "=== intraday_snapshot.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"

if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过快照采集（force 可绕过）" | tee -a "$LOG"
  echo "=== intraday_snapshot.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

[ "$FORCE" = "1" ] && [ "$IS_TRADING" != "1" ] && echo "⚠ force 模式：非交易日强制采集快照（补测）" | tee -a "$LOG"

# 1) 采集快照（存 DB + dump static-site/data/intraday_snapshot.json）
echo "-> 采集盘中快照 ..." | tee -a "$LOG"
"$PY" -m app.collector.intraday_snapshot 2>&1 | tee -a "$LOG"
SNAP_RC=${PIPESTATUS[0]}
if [ "$SNAP_RC" -ne 0 ]; then
  echo "✗ 快照采集失败（退出码 $SNAP_RC），写 stderr 告警" | tee -a "$LOG" >&2
  exit "$SNAP_RC"
fi

# 2) commit + push 受影响的静态数据 JSON 到 main 分支（部署分支）
#    用独立 git worktree 操作 main，不影响当前 feat 开发分支：
#    - 采集在 REPO 跑（trade-data 架构：trade-data 采集，数据 JSON 写到 trade-data/static-site/data/）
#    - git 操作在 GIT_REPO=trade 仓库（trade-data 不 git init）：worktree at origin/main
#    - 采集器写的 JSON 从 REPO rsync 到 worktree，再 git add+commit+push origin HEAD:main
#    持 deploy.lock 串行化 git（阻塞，等 update_all pipeline 释放；避免 index.lock 冲突）。
#    只 add 数据文件，不碰 app.js/style.css 等（前端 agent 可能改了，-A 会把半成品提交）。
#    用环境变量传 commit message，避免 bash -c 引号转义问题。
COMMIT_MSG="data update [intraday] $(date +%Y-%m-%d_%H:%M)"
export INTRADAY_COMMIT_MSG="$COMMIT_MSG"
echo "-> commit + push 数据 JSON 到 main（独立 work tree，持 deploy 锁串行）msg=\"${COMMIT_MSG}\" ..." | tee -a "${LOG}"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash -c '
  set -euo pipefail
  REPO="${REPO:-/Users/linhuichen/code/trade}"
  GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
  # 主脚本 PY 未 export，子 bash -c 不继承非导出变量；此处必须重新定义，
  # 否则 set -u 下 "$PY" 触发 unbound variable 致整个 commit+push 失败（2026-07-17 15:35 事故根因）。
  PY="$REPO/.venv/bin/python"

  # 拉取最新 origin/main（work tree 基于此创建，确保 push 是 fast-forward）
  # git 操作在 GIT_REPO=trade 仓库（trade-data 不 git init）
  git -C "$GIT_REPO" fetch origin main

  # 清理上次崩溃残留的 stale worktree 元数据
  git -C "$GIT_REPO" worktree prune

  # 创建独立 work tree（detached HEAD @ origin/main，即使 main 已被 trade checkout 也不冲突）
  WORKTREE=$(mktemp -d /tmp/trade_intraday_wt.XXXXXX)
  cleanup() {
    git -C "$GIT_REPO" worktree remove "$WORKTREE" --force 2>/dev/null || rm -rf "$WORKTREE"
  }
  trap cleanup EXIT

  if ! git -C "$GIT_REPO" worktree add --detach "$WORKTREE" origin/main; then
    echo "✗ 创建 work tree 失败" >&2
    exit 1
  fi

  # 刷新 schedule_stats.json（在 REPO 跑，读 data/logs/；持 deploy.lock 安全，
  # 避免和 deploy.sh 的 gen_schedule_stats 并发）。写 REPO static-site/data/，
  # 随后 rsync 进 worktree 一起 push，修复"近期执行统计"intraday 行 last_run 滞后 bug。
  "$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tail -1 || echo "⚠ gen_schedule_stats.py 失败，继续 push"

  cd "$WORKTREE"

  # 从 REPO 拷贝采集器刚写的数据 JSON 到 worktree（trade-data 架构：rsync trade-data->worktree）
  rsync -a "$REPO/static-site/data/." static-site/data/

  # 生成 .gz（前端 fetchJSON 优先读 .gz，Decompression Stream 解压；
  # 不生成则线上 .gz 滞后 .json，前端读旧 .gz = 读旧数据根因）
  # intraday_snapshot + overview/summary/schedule_stats/hk-1y/sentiment-all 共 6 个
  gzip -kf static-site/data/intraday_snapshot.json
  gzip -kf static-site/data/overview.json
  gzip -kf static-site/data/summary.json
  gzip -kf static-site/data/schedule_stats.json
  gzip -kf static-site/data/hk-1y.json
  gzip -kf static-site/data/sentiment-all.json

  # 只 add 数据文件，不碰 app.js/style.css 等
  # period .gz 通配必加：write_json 生成 raw+.gz，rsync 进 worktree 后 .gz 也在，
  # 不 add 则 .gz 不进 commit 不 push，前端 fetchJSON 优先读 .gz = 读旧数据（停 7-21 根因）。
  # sentiment-*.json.gz / hk-*.json.gz 通配已含 all/1y，故不再单列 sentiment-all/hk-1y 显式行。
  # index/ 已 R2 托管（2026-07-20 R2 阶段3 瘦身），本地 untracked 不进 git，由 upload_r2.py upload-index 刷 R2。
  git add static-site/data/intraday_snapshot.json \
          static-site/data/intraday_snapshot.json.gz \
          static-site/data/schedule_stats.json \
          static-site/data/schedule_stats.json.gz \
          static-site/data/overview.json \
          static-site/data/overview.json.gz \
          static-site/data/sentiment-*.json \
          static-site/data/sentiment-*.json.gz \
          static-site/data/summary.json \
          static-site/data/summary.json.gz \
          static-site/data/summary_history.json \
          static-site/data/hk-*.json \
          static-site/data/hk-*.json.gz \
          static-site/data/a-stock-*.json \
          static-site/data/a-stock-*.json.gz \
          static-site/data/global-*.json \
          static-site/data/global-*.json.gz
  if git diff --cached --quiet; then
    echo "✓ 数据 JSON 无变更，跳过 commit"
  else
    git commit -m "$INTRADAY_COMMIT_MSG"
    echo "✓ git commit 完成（work tree @ main）"
  fi
  git push origin HEAD:main
  echo "✓ git push origin HEAD:main 完成"
' 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]}
if [ "$PUSH_RC" -ne 0 ]; then
  echo "✗ commit/push 失败（退出码 $PUSH_RC），写 stderr 告警" | tee -a "$LOG" >&2
  exit "$PUSH_RC"
fi

# 2.5) 同步 index/ + industry/ 到 R2（前端已全迁 R2 读，盘中需同步刷新 R2 保实时）
#      intraday collector 写 REPO/static-site/data/index/{iid}-all.json + industry-*-indices/，
#      git push 只推到 git（MaoziYun/CF 源），R2 是前端 index/industry 唯一来源，必须同步。
#      非阻塞：R2 失败不阻断 intraday（git 已推，下轮 deploy.sh 会补刷 R2）。
echo "-> 同步 index/industry 到 R2（前端 R2 源）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-index 2>&1 | tail -1 | tee -a "$LOG" || echo "⚠ upload-index R2 失败，不阻断 intraday" | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-industry 2>&1 | tail -1 | tee -a "$LOG" || echo "⚠ upload-industry R2 失败，不阻断 intraday" | tee -a "$LOG"

# 3) 盘中信号邮件通知（标注【盘中实时】，去重防重复发）
#    intraday_snapshot 已在 collect_and_save 中重算 signal_daily（_recompute_signals），
#    check_signals 查当日信号发邮件。复用 signal_notified.json 去重（同日同 index_id+signal
#    只发一次），盘中多次跑（9:35/10:05/...）只发新出现的信号。
#    邮件标题加【盘中实时】+ 正文风险横幅（盘中快照非最终，收盘 17:50 update_all 仍发最终版）。
#    失败不阻塞：快照数据已 push 上线，邮件失败仅 log 告警。
#    REPO=trade-data 时 check_signals.sh 用 trade-data/scripts/check_signals.py，
#    NOTIFIED_PATH=trade-data/data/signal_notified.json（与 update_all 同路径，去重一致）。
echo "-> check_signals.sh --intraday（盘中信号邮件）..." | tee -a "$LOG"
bash "$REPO/scripts/check_signals.sh" --intraday 2>&1 | tee -a "$LOG"
SIGNAL_RC=${PIPESTATUS[0]}
[ "$SIGNAL_RC" -ne 0 ] && echo "⚠ check_signals 退出码 ${SIGNAL_RC:-?}(邮件失败或配置缺失,不阻塞快照)" | tee -a "$LOG"

echo "=== intraday_snapshot.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0
