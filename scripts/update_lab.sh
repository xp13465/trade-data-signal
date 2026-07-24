#!/usr/bin/env bash
# update_lab.sh - 策略实验室自动回测 + 上线（每天 update_all 完成后跑）
#
# 依赖 update_all（17:50）写入当天 index_daily 日线后，lab 才能回测当天。
# update_all 实测约 49 分钟（17:50->18:39），故 launchd 定 19:00，并在脚本内
# 等待 update_all 完成（防撞车 + 防读旧数据缺当天）。
#
# 步骤（11 步）：
#   [1/11]  lab_simulate 单信号（128 组 × 9 指数）
#   [2/11]  lab_simulate --fusion（91 × 9）
#   [3/11]  lab_matrix 单信号矩阵（lab_backtest_{idx}.json，前端策略矩阵视图）
#   [4/11]  lab_matrix --fusion（融合矩阵 lab_backtest_fusion_{idx}.json，前端融合矩阵）
#   [5/11]  lab_retest 二次测试切片（lab_retest_{idx}.json）
#   [6/11]  lab_retest_honors 荣誉表（lab_retest_honors.json，前端 retest 徽章）
#   [7/11]  backtest_strategies 全市场聚合（lab_backtest.json，前端策略详情默认视图）
#   [8/11]  lab_ablation 信号消融（static-site/data/lab_ablation.json，顶层）
#   [9/11]  lab_cost_compare 手续费对比（static-site/data/lab_cost_compare.json，顶层）
#   [10/11] lab_param_scan 参数敏感扫描（static-site/data/lab_param_scan.json，顶层）
#   [11/11] lab_short_symmetry 多空对称（static-site/data/lab_short_symmetry.json，顶层）
#   -> upload_r2.py upload-lab 刷 R2 上线（lab/ 子目录 65 文件）
#   -> git push 顶层 lab_*.json（static-site/data/ 4 顶层文件走 deploy）
#
# P1-7 修复（2026-07-21）：原脚本只跑 lab_simulate + lab_retest，漏跑 lab_matrix 和
# backtest_strategies，致 lab_backtest*.json 系列停滞（lab_backtest.json 停 7/10 滞后 11 天，
# lab_backtest_{idx}.json 停 7/16，lab_backtest_fusion_{idx}.json 停 7/17），但前端 lab.js
# 仍引用这些文件做策略矩阵视图 -> 功能审计报 lab 滞后 11 天。补 3 步后全量每日刷新。
#
# P1-7b 修复（2026-07-22）：原脚本漏跑 lab_retest_honors + 4 顶层脚本（lab_ablation /
# lab_cost_compare / lab_param_scan / lab_short_symmetry），致 lab_retest_honors.json 停 7/17，
# 顶层 4 文件停 7/17（ss.fx8.store/data/ 上 generated_at=2026-07-17 滞后 5 天）。补 5 步后
# 全量每日刷新；顶层 4 文件走 git deploy（lab/ 子目录走 R2）。
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

# [1/11] lab_simulate 单信号
echo "-> [1/11] lab_simulate 单信号（128 组 × 9 指数）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_simulate.py" 2>&1 | tee -a "$LOG"
RC1=${PIPESTATUS[0]:-1}
if [ "$RC1" -ne 0 ]; then
  echo "⚠ lab_simulate 单信号失败（退出码 ${RC1}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 单信号完成" | tee -a "$LOG"
fi

# [2/11] lab_simulate 融合
echo "-> [2/11] lab_simulate 融合（91 候选 × 9 指数）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_simulate.py" --fusion 2>&1 | tee -a "$LOG"
RC2=${PIPESTATUS[0]:-1}
if [ "$RC2" -ne 0 ]; then
  echo "⚠ lab_simulate 融合失败（退出码 ${RC2}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 融合完成" | tee -a "$LOG"
fi

# [3/11] lab_matrix 单信号矩阵（生成 lab_backtest_{idx}.json，前端策略矩阵视图）
# P1-7：前端 lab.js fetchLabMatrixData() 读 lab_backtest_{idx}.json 做策略矩阵，原脚本漏跑致停滞。
echo "-> [3/11] lab_matrix 单信号矩阵（9 指数，前端策略矩阵 lab_backtest_{idx}.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_matrix.py" 2>&1 | tee -a "$LOG"
RC3=${PIPESTATUS[0]:-1}
if [ "$RC3" -ne 0 ]; then
  echo "⚠ lab_matrix 单信号失败（退出码 ${RC3}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 单信号矩阵完成" | tee -a "$LOG"
fi

# [4/11] lab_matrix 融合矩阵（生成 lab_backtest_fusion_{idx}.json，前端融合矩阵视图）
# P1-7：前端 lab.js fetchLabFusionMatrixData() 读 lab_backtest_fusion_{idx}.json，原脚本漏跑致停滞。
echo "-> [4/11] lab_matrix 融合矩阵（9 指数，前端融合矩阵 lab_backtest_fusion_{idx}.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_matrix.py" --fusion 2>&1 | tee -a "$LOG"
RC4=${PIPESTATUS[0]:-1}
if [ "$RC4" -ne 0 ]; then
  echo "⚠ lab_matrix 融合失败（退出码 ${RC4}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 融合矩阵完成" | tee -a "$LOG"
fi

# [5/11] lab_retest 二次测试
echo "-> [5/11] lab_retest 二次测试（切片）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_retest.py" 2>&1 | tee -a "$LOG"
RC5=${PIPESTATUS[0]:-1}
if [ "$RC5" -ne 0 ]; then
  echo "⚠ lab_retest 失败（退出码 ${RC5}），继续上线已生成产物" | tee -a "$LOG"
else
  echo "✓ retest 完成" | tee -a "$LOG"
fi

# [6/11] lab_retest_honors 荣誉表（生成 lab_retest_honors.json，前端 retest 徽章）
# P1-7b：前端 lab.js fetchLabRetestHonors() 读 lab_retest_honors.json 做 retest 排行徽章，
# 原脚本漏跑致停滞（7/17）。依赖 lab_retest_*.json + lab_sim_*_stats.json（[1][2][5] 已生成）。
echo "-> [6/11] lab_retest_honors 荣誉表（lab_retest_honors.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_retest_honors.py" 2>&1 | tee -a "$LOG"
RC_HONORS=${PIPESTATUS[0]:-1}
if [ "$RC_HONORS" -ne 0 ]; then
  echo "⚠ lab_retest_honors 失败（退出码 ${RC_HONORS}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 荣誉表完成" | tee -a "$LOG"
fi

# [7/11] backtest_strategies 全市场聚合矩阵（生成 lab_backtest.json，前端策略详情默认视图）
# P1-7：前端 lab.js fetchLabData() 读 lab_backtest.json 做策略详情/列表页默认视图，原脚本漏跑
# 致 lab_backtest.json 停 7/10 滞后 11 天。backtest_strategies.py 硬编码写到
# a-stock-data/lab_backtest.json（绝对路径），跑完复制到 static-site/data/lab/ 供 upload_r2 上线。
echo "-> [7/11] backtest_strategies 全市场聚合（lab_backtest.json）..." | tee -a "$LOG"
"$PY" "$REPO/a-stock-data/backtest_strategies.py" 2>&1 | tee -a "$LOG"
RC6=${PIPESTATUS[0]:-1}
if [ "$RC6" -ne 0 ]; then
  echo "⚠ backtest_strategies 失败（退出码 ${RC6}），lab_backtest.json 可能过期" | tee -a "$LOG"
elif [ -f "$REPO/a-stock-data/lab_backtest.json" ]; then
  cp "$REPO/a-stock-data/lab_backtest.json" "$REPO/static-site/data/lab/lab_backtest.json"
  echo "✓ lab_backtest.json 复制到 static-site/data/lab/" | tee -a "$LOG"
else
  echo "⚠ lab_backtest.json 未生成（backtest_strategies.py 未产出）" | tee -a "$LOG"
fi

# [8/11] lab_ablation 信号消融（生成 static-site/data/lab_ablation.json，顶层）
# P1-7b：前端 lab.js fetchLabAblationData() 读 ./data/lab_ablation.json，原脚本漏跑致停滞（7/17）。
echo "-> [8/11] lab_ablation 信号消融（lab_ablation.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_ablation.py" 2>&1 | tee -a "$LOG"
RC_ABL=${PIPESTATUS[0]:-1}
if [ "$RC_ABL" -ne 0 ]; then
  echo "⚠ lab_ablation 失败（退出码 ${RC_ABL}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 信号消融完成" | tee -a "$LOG"
fi

# [9/11] lab_cost_compare 手续费对比（生成 static-site/data/lab_cost_compare.json，顶层）
# P1-7b：前端 lab.js fetchLabCostCompare() 读 ./data/lab_cost_compare.json，原脚本漏跑致停滞（7/17）。
echo "-> [9/11] lab_cost_compare 手续费对比（lab_cost_compare.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_cost_compare.py" 2>&1 | tee -a "$LOG"
RC_CC=${PIPESTATUS[0]:-1}
if [ "$RC_CC" -ne 0 ]; then
  echo "⚠ lab_cost_compare 失败（退出码 ${RC_CC}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 手续费对比完成" | tee -a "$LOG"
fi

# [10/11] lab_param_scan 参数敏感扫描（生成 static-site/data/lab_param_scan.json，顶层）
# P1-7b：前端 lab.js 读 ./data/lab_param_scan.json，原脚本漏跑致停滞（7/17）。
echo "-> [10/11] lab_param_scan 参数敏感扫描（lab_param_scan.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_param_scan.py" 2>&1 | tee -a "$LOG"
RC_PS=${PIPESTATUS[0]:-1}
if [ "$RC_PS" -ne 0 ]; then
  echo "⚠ lab_param_scan 失败（退出码 ${RC_PS}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 参数扫描完成" | tee -a "$LOG"
fi

# [11/11] lab_short_symmetry 多空对称（生成 static-site/data/lab_short_symmetry.json，顶层）
# P1-7b：前端 lab.js 读 ./data/lab_short_symmetry.json，原脚本漏跑致停滞（7/17）。
echo "-> [11/11] lab_short_symmetry 多空对称（lab_short_symmetry.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_short_symmetry.py" 2>&1 | tee -a "$LOG"
RC_SS=${PIPESTATUS[0]:-1}
if [ "$RC_SS" -ne 0 ]; then
  echo "⚠ lab_short_symmetry 失败（退出码 ${RC_SS}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 多空对称完成" | tee -a "$LOG"
fi

# 上线分两路：
# A) lab/ 子目录 65 文件（lab_backtest*.json / lab_sim_*.json / lab_retest_*.json /
#    lab_retest_honors.json）-> upload_r2.py upload-lab 刷 R2（R2 是前端 lab/ 唯一来源）
# B) static-site/data/ 顶层 4 文件（lab_ablation / lab_cost_compare / lab_param_scan /
#    lab_short_symmetry）-> git deploy（commit + push，部署到 ss.fx8.store 等各站）
#
# P1-7 同步：launchd 在 trade-data（运行副本）跑，lab 脚本用 __file__/abspath 写
# $REPO/static-site/data/lab/（trade-data/），但 upload_r2.py 的 ROOT 用 Path.resolve()
# 解析符号链接到 trade/，读 trade/static-site/data/lab/。不同步则 upload_r2 上传 trade/ 旧数据。
# rsync 同步确保 upload_r2 读到 launchd 本次生成的最新数据（手动在 trade/ 跑时 REPO=trade 跳过）。
TRADE_LAB="/Users/linhuichen/code/trade/static-site/data/lab"
TRADE_DATA="/Users/linhuichen/code/trade/static-site/data"
if [ "$REPO" != "/Users/linhuichen/code/trade" ] && [ -d "$TRADE_LAB" ]; then
  # A) 同步 lab/ 子目录 -> upload_r2 读取
  rsync -a "$REPO/static-site/data/lab/" "$TRADE_LAB/"
  echo "✓ 同步 lab/ 子目录 $REPO -> trade/（供 upload_r2 读取）" | tee -a "$LOG"
  # B) 同步顶层 4 文件 -> git deploy 读取
  for f in lab_ablation.json lab_cost_compare.json lab_param_scan.json lab_short_symmetry.json; do
    if [ -f "$REPO/static-site/data/$f" ]; then
      cp "$REPO/static-site/data/$f" "$TRADE_DATA/$f"
    fi
  done
  echo "✓ 同步顶层 lab_*.json $REPO -> trade/（供 git deploy 读取）" | tee -a "$LOG"
fi

# A) upload_r2 刷 R2（lab/ 子目录 65 文件）
echo "-> upload_r2.py upload-lab（刷 R2）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-lab 2>&1 | tee -a "$LOG"
R2_RC=${PIPESTATUS[0]:-1}
if [ "$R2_RC" -ne 0 ]; then
  echo "⚠ upload-lab 失败（退出码 ${R2_RC}），lab R2 可能过期" | tee -a "$LOG"
else
  echo "✓ R2 上传完成" | tee -a "$LOG"
fi

# B) git deploy 顶层 4 文件（static-site/data/lab_*.json）
# 复用 deploy.sh 的 fetch + rebase + push 重试机制（non-fast-forward 时 rebase 后重试一次）。
# lab/ 子目录移出 git（commit 8c7affc6），顶层 4 文件仍 tracked，走 git deploy。
GIT_REPO="/Users/linhuichen/code/trade"
echo "-> git deploy 顶层 lab_*.json（4 文件）..." | tee -a "$LOG"
git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
for f in lab_ablation.json lab_cost_compare.json lab_param_scan.json lab_short_symmetry.json; do
  git -C "$GIT_REPO" add "static-site/data/$f" 2>/dev/null || true
done
# 有变更才 commit（幂等：无变更跳过 commit，但仍 push 推未 push commit）
GIT_DEPLOY_RC=0
if git -C "$GIT_REPO" diff --cached --quiet 2>/dev/null; then
  echo "  顶层 lab_*.json 无变更，跳过 commit" | tee -a "$LOG"
else
  COMMIT_MSG="data update [lab-tl] $(date +%Y-%m-%d_%H:%M)"
  echo "-> git commit: $COMMIT_MSG" | tee -a "$LOG"
  git -C "$GIT_REPO" commit -m "$COMMIT_MSG" 2>&1 | tee -a "$LOG"
  COMMIT_RC=${PIPESTATUS[0]:-1}
  if [ "$COMMIT_RC" -ne 0 ]; then
    echo "⚠ git commit 失败（退出码 ${COMMIT_RC}）" | tee -a "$LOG"
    GIT_DEPLOY_RC=$COMMIT_RC
  fi
fi
# 总是 push（幂等：有未 push commit 就推，无则 up-to-date）
echo "-> git push 顶层 lab_*.json ..." | tee -a "$LOG"
git -C "$GIT_REPO" push origin main 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]:-1}
if [ "$PUSH_RC" -ne 0 ]; then
  # non-fast-forward：fetch 后确认本地是否落后，rebase 后重试一次
  echo "⚠ git push 失败（退出码 ${PUSH_RC}），尝试 fetch + rebase 重试..." | tee -a "$LOG"
  git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
  if git -C "$GIT_REPO" rebase origin/main 2>&1 | tee -a "$LOG"; then
    if git -C "$GIT_REPO" push origin main 2>&1 | tee -a "$LOG"; then
      echo "✓ rebase + 重试 push 成功" | tee -a "$LOG"
    else
      echo "⚠ rebase 后重试 push 仍失败" | tee -a "$LOG"
      GIT_DEPLOY_RC=1
    fi
  else
    git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
    echo "⚠ rebase origin/main 失败，已 abort 保持工作区干净" | tee -a "$LOG"
    GIT_DEPLOY_RC=1
  fi
else
  echo "✓ git push 完成" | tee -a "$LOG"
fi

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
ELAPSED_MIN=$((ELAPSED / 60))
echo "=== update_lab.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 耗时 ${ELAPSED}s（${ELAPSED_MIN}min）===" | tee -a "$LOG"
echo "退出码汇总: sim=$RC1 fusion=$RC2 matrix=$RC3 fusion_matrix=$RC4 retest=$RC5 honors=$RC_HONORS backtest=$RC6 abl=$RC_ABL cc=$RC_CC ps=$RC_PS ss=$RC_SS r2=$R2_RC git_tl=$GIT_DEPLOY_RC" | tee -a "$LOG"

# 刷新 schedule_stats.json（2026-07-24 方案A根治：从 deploy.sh:72 移到此处，在"结束"行后调用，
# gen_stats 能读到完整"开始+结束"对，正确配对当前任务 exit/dur，不再 pending null）
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"
