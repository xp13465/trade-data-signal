#!/usr/bin/env bash
# update_lab.sh - 策略实验室自动回测 + 上线（每天 update_all 完成后跑）
#
# 依赖 update_all（17:50）写入当天 index_daily 日线后，lab 才能回测当天。
# update_all 实测约 49 分钟（17:50→18:39），故 launchd 定 19:00，并在脚本内
# 等待 update_all 完成（防撞车 + 防读旧数据缺当天）。
#
# 步骤：lab_simulate（单信号 128 组 × 9 指数）→ lab_simulate --fusion（91 × 9）
#       → lab_retest（二次测试切片）→ git add lab 产物 → commit → push 上线
#
# 失败不阻塞：每步 || 记错误继续（单步失败不影响后续步骤 + 上线已成功的部分）。
# 非交易日跳过（无新日线，跑了也是旧数据，省时间）。
#
# 用法：bash scripts/update_lab.sh
# 日志：data/logs/update_lab_YYYYMMDD_HHMM.log
set -u
# 不 set -e：每步显式判退出码，单步失败不阻断后续 + 上线。

# 防止脚本运行期间 mac 休眠（launchd 19:00 触发时若 mac 在睡眠边缘，跑期间不再睡；
# caffeinate -i 防系统空闲睡眠，-w $$ 跟随本脚本 PID，脚本退出 caffeinate 自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/update_lab_${STAMP}.log"

mkdir -p "$LOGDIR"
cd "$REPO"

# 进程互斥：防止手动跑 + launchd 并发撞（lab_simulate 写 lab/*.json 原子覆盖 +
# git index.lock 冲突）。fcntl.flock 非阻塞独占锁，持不到 = 已有在跑 = 跳过。
if [ -z "${UPDATE_LAB_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb --on-skip "$REPO/scripts/on_skip_notify.sh" /tmp/trade_lab.lock \
    env UPDATE_LAB_LOCKED=1 bash "$0" "$@"
fi

START_TS=$(date +%s)
echo "=== update_lab.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（非交易日无新日线，跳过省时间；与 update_all.sh 一致）
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown}" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ]; then
  echo "非交易日，跳过 lab 回测（无新日线）" | tee -a "$LOG"
  echo "=== update_lab.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 等待 update_all 完成（防撞车 + 防读旧数据缺当天）
# update_all 持 /tmp/trade_update_all.lock 并跑 update_all.sh 进程；最多等 90 分钟防异常久。
WAIT_MAX=5400  # 90 min
WAITED=0
while pgrep -f 'update_all\.sh' >/dev/null 2>&1; do
  if [ "$WAITED" -ge "$WAIT_MAX" ]; then
    echo "⚠ update_all 仍运行中（已等 ${WAITED}s），超时放弃本次 lab（避免读旧数据）" | tee -a "$LOG"
    exit 1
  fi
  echo "update_all 仍在运行，等待...（${WAITED}s）" | tee -a "$LOG"
  sleep 60
  WAITED=$((WAITED + 60))
done
echo "✓ update_all 已完成（或未运行），开始 lab 回测" | tee -a "$LOG"

# [1/3] lab_simulate 单信号
echo "-> [1/3] lab_simulate 单信号（128 组 × 9 指数）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_simulate.py" 2>&1 | tee -a "$LOG"
RC1=${PIPESTATUS[0]}
if [ "$RC1" -ne 0 ]; then
  echo "⚠ lab_simulate 单信号失败（退出码 $RC1），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 单信号完成" | tee -a "$LOG"
fi

# [2/3] lab_simulate 融合
echo "-> [2/3] lab_simulate 融合（91 候选 × 9 指数）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_simulate.py" --fusion 2>&1 | tee -a "$LOG"
RC2=${PIPESTATUS[0]}
if [ "$RC2" -ne 0 ]; then
  echo "⚠ lab_simulate 融合失败（退出码 $RC2），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 融合完成" | tee -a "$LOG"
fi

# [3/3] lab_retest 二次测试
echo "-> [3/3] lab_retest 二次测试（切片）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_retest.py" 2>&1 | tee -a "$LOG"
RC3=${PIPESTATUS[0]}
if [ "$RC3" -ne 0 ]; then
  echo "⚠ lab_retest 失败（退出码 $RC3），继续上线已生成产物" | tee -a "$LOG"
else
  echo "✓ retest 完成" | tee -a "$LOG"
fi

# 上线：git add lab 产物（只 lab 目录，§8 不碰根 data/）
echo "-> git add static-site/data/lab/ + web/data/lab/ ..." | tee -a "$LOG"
git -C "$REPO" add static-site/data/lab/ web/data/lab/ 2>&1 | tee -a "$LOG"

# 检查有无变更（cached diff 非空才 commit；无变更跳过 commit 但仍 push）
if git -C "$REPO" diff --cached --quiet; then
  echo "✓ lab 无新变更，跳过 commit（仍 push 推未 push commit）" | tee -a "$LOG"
else
  COMMIT_MSG="data update [lab] $(date +%Y-%m-%d_%H:%M)"
  echo "-> git commit: $COMMIT_MSG" | tee -a "$LOG"
  git -C "$REPO" commit -m "$COMMIT_MSG" -m "Co-Authored-By: Claude <noreply@anthropic.com>" 2>&1 | tee -a "$LOG"
  COMMIT_RC=${PIPESTATUS[0]}
  if [ "$COMMIT_RC" -ne 0 ]; then
    echo "⚠ git commit 失败（退出码 $COMMIT_RC），仍尝试 push" | tee -a "$LOG"
  fi
fi

# push（§10 不 checkout，直接当前分支 HEAD 推到 main；与 deploy.sh 一致）
echo "-> git push origin HEAD:main ..." | tee -a "$LOG"
git -C "$REPO" push origin HEAD:main 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]:-1}
if [ "$PUSH_RC" -ne 0 ]; then
  echo "⚠ git push 失败（退出码 $PUSH_RC）" | tee -a "$LOG"
else
  echo "✓ push 完成" | tee -a "$LOG"
fi

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
ELAPSED_MIN=$((ELAPSED / 60))
echo "=== update_lab.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 耗时 ${ELAPSED}s（${ELAPSED_MIN}min）===" | tee -a "$LOG"
echo "退出码汇总: sim=$RC1 fusion=$RC2 retest=$RC3 push=$PUSH_RC" | tee -a "$LOG"
