#!/usr/bin/env bash
# update_lab.sh - 策略实验室自动回测 + 上线（每天 update_all 完成后跑）
#
# 依赖 update_all（17:50）写入当天 index_daily 日线后，lab 才能回测当天。
# update_all 实测约 49 分钟（17:50->18:39），故 launchd 定 19:00，并在脚本内
# 等待 update_all 完成（防撞车 + 防读旧数据缺当天）。
#
# 步骤（12 步）：
#   [1/12]  lab_simulate 单信号（128 组 × 9 指数）
#   [2/12]  lab_simulate --fusion（91 × 9）
#   [3/12]  lab_matrix 单信号矩阵（lab_backtest_{idx}.json，前端策略矩阵视图）
#   [4/12]  lab_matrix --fusion（融合矩阵 lab_backtest_fusion_{idx}.json，前端融合矩阵）
#   [5/12]  lab_retest 二次测试切片（lab_retest_{idx}.json）
#   [6/12]  lab_retest_honors 荣誉表（lab_retest_honors.json，前端 retest 徽章）
#   [7/12]  backtest_strategies 全市场聚合（lab_backtest.json，前端策略详情默认视图）
#   [8/12]  lab_ablation 信号消融（static-site/data/lab_ablation.json，顶层）
#   [9/12]  lab_cost_compare 手续费对比（static-site/data/lab_cost_compare.json，顶层）
#   [10/12] lab_param_scan 参数敏感扫描（static-site/data/lab_param_scan.json，顶层）
#   [11/12] lab_short_symmetry 多空对称（static-site/data/lab_short_symmetry.json，顶层）
#   [11.5/12] simulate_trade --all（static-site/data/trade_sim/ 全品种 JSON + trade_sim_indices.json）
#   [12/12] simulate_trade --html（static-site/trade_sim.html，sh 旧版静态 HTML 兜底入口）
#   -> upload_r2.py upload-lab 刷 R2 上线（lab/ 子目录 65 文件）
#   -> upload_r2.py upload-trade-sim-json 刷 R2 trade_sim JSON（trade_sim/ 子目录 + trade_sim_indices.json）
#   -> git push 顶层 lab_*.json + trade_sim.html（static-site/data/ 4 顶层 + static-site/ 根 trade_sim.html 走 deploy）
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

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
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

# [1/12] lab_simulate 单信号
echo "-> [1/12] lab_simulate 单信号（128 组 × 9 指数）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_simulate.py" 2>&1 | tee -a "$LOG"
RC1=${PIPESTATUS[0]:-1}
if [ "$RC1" -ne 0 ]; then
  echo "⚠ lab_simulate 单信号失败（退出码 ${RC1}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 单信号完成" | tee -a "$LOG"
fi

# [2/12] lab_simulate 融合
echo "-> [2/12] lab_simulate 融合（91 候选 × 9 指数）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_simulate.py" --fusion 2>&1 | tee -a "$LOG"
RC2=${PIPESTATUS[0]:-1}
if [ "$RC2" -ne 0 ]; then
  echo "⚠ lab_simulate 融合失败（退出码 ${RC2}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 融合完成" | tee -a "$LOG"
fi

# [3/12] lab_matrix 单信号矩阵（生成 lab_backtest_{idx}.json，前端策略矩阵视图）
# P1-7：前端 lab.js fetchLabMatrixData() 读 lab_backtest_{idx}.json 做策略矩阵，原脚本漏跑致停滞。
echo "-> [3/12] lab_matrix 单信号矩阵（9 指数，前端策略矩阵 lab_backtest_{idx}.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_matrix.py" 2>&1 | tee -a "$LOG"
RC3=${PIPESTATUS[0]:-1}
if [ "$RC3" -ne 0 ]; then
  echo "⚠ lab_matrix 单信号失败（退出码 ${RC3}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 单信号矩阵完成" | tee -a "$LOG"
fi

# [4/12] lab_matrix 融合矩阵（生成 lab_backtest_fusion_{idx}.json，前端融合矩阵视图）
# P1-7：前端 lab.js fetchLabFusionMatrixData() 读 lab_backtest_fusion_{idx}.json，原脚本漏跑致停滞。
echo "-> [4/12] lab_matrix 融合矩阵（9 指数，前端融合矩阵 lab_backtest_fusion_{idx}.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_matrix.py" --fusion 2>&1 | tee -a "$LOG"
RC4=${PIPESTATUS[0]:-1}
if [ "$RC4" -ne 0 ]; then
  echo "⚠ lab_matrix 融合失败（退出码 ${RC4}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 融合矩阵完成" | tee -a "$LOG"
fi

# [5/12] lab_retest 二次测试
echo "-> [5/12] lab_retest 二次测试（切片）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_retest.py" 2>&1 | tee -a "$LOG"
RC5=${PIPESTATUS[0]:-1}
if [ "$RC5" -ne 0 ]; then
  echo "⚠ lab_retest 失败（退出码 ${RC5}），继续上线已生成产物" | tee -a "$LOG"
else
  echo "✓ retest 完成" | tee -a "$LOG"
fi

# [6/12] lab_retest_honors 荣誉表（生成 lab_retest_honors.json，前端 retest 徽章）
# P1-7b：前端 lab.js fetchLabRetestHonors() 读 lab_retest_honors.json 做 retest 排行徽章，
# 原脚本漏跑致停滞（7/17）。依赖 lab_retest_*.json + lab_sim_*_stats.json（[1][2][5] 已生成）。
echo "-> [6/12] lab_retest_honors 荣誉表（lab_retest_honors.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_retest_honors.py" 2>&1 | tee -a "$LOG"
RC_HONORS=${PIPESTATUS[0]:-1}
if [ "$RC_HONORS" -ne 0 ]; then
  echo "⚠ lab_retest_honors 失败（退出码 ${RC_HONORS}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 荣誉表完成" | tee -a "$LOG"
fi

# [7/12] backtest_strategies 全市场聚合矩阵（生成 lab_backtest.json，前端策略详情默认视图）
# P1-7：前端 lab.js fetchLabData() 读 lab_backtest.json 做策略详情/列表页默认视图，原脚本漏跑
# 致 lab_backtest.json 停 7/10 滞后 11 天。backtest_strategies.py 硬编码写到
# a-stock-data/lab_backtest.json（绝对路径），跑完复制到 static-site/data/lab/ 供 upload_r2 上线。
echo "-> [7/12] backtest_strategies 全市场聚合（lab_backtest.json）..." | tee -a "$LOG"
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

# [8/12] lab_ablation 信号消融（生成 static-site/data/lab_ablation.json，顶层）
# P1-7b：前端 lab.js fetchLabAblationData() 读 ./data/lab_ablation.json，原脚本漏跑致停滞（7/17）。
echo "-> [8/12] lab_ablation 信号消融（lab_ablation.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_ablation.py" 2>&1 | tee -a "$LOG"
RC_ABL=${PIPESTATUS[0]:-1}
if [ "$RC_ABL" -ne 0 ]; then
  echo "⚠ lab_ablation 失败（退出码 ${RC_ABL}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 信号消融完成" | tee -a "$LOG"
fi

# [9/12] lab_cost_compare 手续费对比（生成 static-site/data/lab_cost_compare.json，顶层）
# P1-7b：前端 lab.js fetchLabCostCompare() 读 ./data/lab_cost_compare.json，原脚本漏跑致停滞（7/17）。
echo "-> [9/12] lab_cost_compare 手续费对比（lab_cost_compare.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_cost_compare.py" 2>&1 | tee -a "$LOG"
RC_CC=${PIPESTATUS[0]:-1}
if [ "$RC_CC" -ne 0 ]; then
  echo "⚠ lab_cost_compare 失败（退出码 ${RC_CC}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 手续费对比完成" | tee -a "$LOG"
fi

# [10/12] lab_param_scan 参数敏感扫描（生成 static-site/data/lab_param_scan.json，顶层）
# P1-7b：前端 lab.js 读 ./data/lab_param_scan.json，原脚本漏跑致停滞（7/17）。
echo "-> [10/12] lab_param_scan 参数敏感扫描（lab_param_scan.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_param_scan.py" 2>&1 | tee -a "$LOG"
RC_PS=${PIPESTATUS[0]:-1}
if [ "$RC_PS" -ne 0 ]; then
  echo "⚠ lab_param_scan 失败（退出码 ${RC_PS}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 参数扫描完成" | tee -a "$LOG"
fi

# [11/12] lab_short_symmetry 多空对称（生成 static-site/data/lab_short_symmetry.json，顶层）
# P1-7b：前端 lab.js 读 ./data/lab_short_symmetry.json，原脚本漏跑致停滞（7/17）。
echo "-> [11/12] lab_short_symmetry 多空对称（lab_short_symmetry.json）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/lab/lab_short_symmetry.py" 2>&1 | tee -a "$LOG"
RC_SS=${PIPESTATUS[0]:-1}
if [ "$RC_SS" -ne 0 ]; then
  echo "⚠ lab_short_symmetry 失败（退出码 ${RC_SS}），继续后续步骤" | tee -a "$LOG"
else
  echo "✓ 多空对称完成" | tee -a "$LOG"
fi

# [11.5/12] simulate_trade --all（生成全品种JSON: trade_sim_{index}_stats.json + _full.json + trade_sim_indices.json）
# 2026-08-09 补：原 update_lab.sh 只跑 --html(HTML兜底)，JSON 模式无调度致 trade_sim JSON 滞后。
# --all 批量生成 167 品种 5 窗口回测 JSON（写 static-site/data/trade_sim/ + trade_sim_indices.json），
# 失败不阻塞(同现有模式)。
echo "-> [11.5/12] simulate_trade --all（全品种JSON回测）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/simulate_trade.py" --all 2>&1 | tee -a "$LOG"
RC_TSJ=${PIPESTATUS[0]:-1}
if [ "$RC_TSJ" -ne 0 ]; then
  echo "⚠ simulate_trade --all 失败（退出码 ${RC_TSJ}），trade_sim JSON 可能过期" | tee -a "$LOG"
else
  echo "✓ trade_sim JSON 全品种生成完成" | tee -a "$LOG"
fi

# [12/12] simulate_trade --html（生成 static-site/trade_sim.html，sh 旧版静态 HTML 兜底入口）
# 2026-07-29 纳入 update_lab.sh：原手动跑，现每日自动重生。
# --output 指定生成 static-site/trade_sim.html（git tracked，走 git deploy）；
# 其他品种 trade_sim_*.html 走 R2（upload-trade-sim），此处只重生 sh 主入口。
# 失败不阻塞：trade_sim.html 过期不影响 lab 主流程（JSON 由 simulate_trade 默认生成，本步骤只补 HTML 兜底）。
echo "-> [12/12] simulate_trade --html（trade_sim.html，sh 旧版静态 HTML）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/simulate_trade.py" --html --output "$REPO/static-site/trade_sim.html" 2>&1 | tee -a "$LOG"
RC_TS=${PIPESTATUS[0]:-1}
if [ "$RC_TS" -ne 0 ]; then
  echo "⚠ simulate_trade --html 失败（退出码 ${RC_TS}），trade_sim.html 可能过期" | tee -a "$LOG"
else
  echo "✓ trade_sim.html 重生完成" | tee -a "$LOG"
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
  # C) 同步 trade_sim.html（sh 旧版静态 HTML，根目录）-> git deploy 读取
  if [ -f "$REPO/static-site/trade_sim.html" ]; then
    cp "$REPO/static-site/trade_sim.html" "/Users/linhuichen/code/trade/static-site/trade_sim.html"
    echo "✓ 同步 trade_sim.html $REPO -> trade/（供 git deploy 读取）" | tee -a "$LOG"
  fi
  # D) 同步 trade_sim/ 子目录 + trade_sim_indices.json -> upload_r2 读取
  #    2026-08-09 补：simulate_trade --all 生成 JSON 需同步到 trade/ 供 upload-trade-sim-json 上传 R2
  rsync -a "$REPO/static-site/data/trade_sim/" "$TRADE_DATA/trade_sim/"
  echo "✓ 同步 trade_sim/ 子目录 $REPO -> trade/（供 upload_r2 读取）" | tee -a "$LOG"
  if [ -f "$REPO/static-site/data/trade_sim_indices.json" ]; then
    cp "$REPO/static-site/data/trade_sim_indices.json" "$TRADE_DATA/trade_sim_indices.json"
  fi
fi

# A) upload_r2 刷 R2（lab/ 子目录 65 文件）
echo "-> upload_r2.py upload-lab（刷 R2）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-lab 2>&1 | tee -a "$LOG"
R2_RC=${PIPESTATUS[0]:-1}
if [ "$R2_RC" -ne 0 ]; then
  echo "⚠ upload-lab 失败（退出码 ${R2_RC}），lab R2 可能过期" | tee -a "$LOG"
  ALERT_TIME=$(date '+%m-%d %H:%M')
  "$PY" "$REPO/scripts/notify.py" \
    "[告警] update_lab R2上传失败 ${ALERT_TIME}" \
    "upload-lab 失败(退出码 ${R2_RC})，lab/ 子目录 R2 可能过期，需手动补刷: bash scripts/upload_r2.py upload-lab<br>日志: $LOG" \
    --severe --from-prefix "[告警]" \
    --dedup-key update_lab_r2_upload_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
else
  echo "✓ R2 上传完成" | tee -a "$LOG"
fi

# upload-trade-sim-json: 上传 trade_sim JSON 到 R2（含自动 purge）
# 2026-08-09 补：simulate_trade --all 生成的 JSON 需上传 R2 供前端走势卡/策略实验室读取。
echo "-> upload_r2.py upload-trade-sim-json（刷 R2 trade_sim JSON）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-trade-sim-json 2>&1 | tee -a "$LOG"
R2_TSJ_RC=${PIPESTATUS[0]:-1}
if [ "$R2_TSJ_RC" -ne 0 ]; then
  echo "⚠ upload-trade-sim-json 失败（退出码 ${R2_TSJ_RC}），trade_sim R2 可能过期" | tee -a "$LOG"
  ALERT_TIME=$(date '+%m-%d %H:%M')
  "$PY" "$REPO/scripts/notify.py" \
    "[告警] update_lab trade_sim R2上传失败 ${ALERT_TIME}" \
    "upload-trade-sim-json 失败(退出码 ${R2_TSJ_RC})，trade_sim R2 可能过期，需手动补刷: bash scripts/upload_r2.py upload-trade-sim-json<br>日志: $LOG" \
    --severe --from-prefix "[告警]" \
    --dedup-key update_lab_tradesim_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
else
  echo "✓ trade_sim JSON R2 上传完成" | tee -a "$LOG"
fi

# B) 上传顶层 lab_*.json 到 R2（阶段3：去 git push 数据，前端走 R2）
#    lab/ 子目录已由上面 upload-lab 上传。顶层 4 个 lab_*.json 走 upload-data-files + purge。
#    trade_sim.html 仍走 git push（static-site/ 根目录，非 data/，非 JSON，不走 R2）。
echo "-> 上传顶层 lab_*.json 到 R2（upload-data-files + purge）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-data-files \
  lab_ablation.json lab_cost_compare.json lab_param_scan.json lab_short_symmetry.json 2>&1 | tee -a "$LOG"
LAB_R2_RC=${PIPESTATUS[0]:-1}
if [ "$LAB_R2_RC" -ne 0 ]; then
  echo "⚠ lab_*.json R2 上传失败（退出码 ${LAB_R2_RC}），lab 数据可能过期" | tee -a "$LOG"
  ALERT_TIME=$(date '+%m-%d %H:%M')
  "$PY" "$REPO/scripts/notify.py" \
    "[告警] update_lab lab_json R2上传失败 ${ALERT_TIME}" \
    "lab_*.json R2 上传失败(退出码 ${LAB_R2_RC})，lab 数据可能过期，需手动补刷: bash scripts/upload_r2.py upload-data-files lab_ablation.json lab_cost_compare.json lab_param_scan.json lab_short_symmetry.json<br>日志: $LOG" \
    --severe --from-prefix "[告警]" \
    --dedup-key update_lab_labjson_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
fi

# C) git push trade_sim.html（static-site/ 根目录，非 data/，阶段3 保留代码 push）
GIT_REPO="/Users/linhuichen/code/trade"
GIT_DEPLOY_RC=0
git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
git -C "$GIT_REPO" add static-site/trade_sim.html 2>/dev/null || true
if git -C "$GIT_REPO" diff --cached --quiet 2>/dev/null; then
  echo "  trade_sim.html 无变更，跳过 commit" | tee -a "$LOG"
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
echo "-> git push trade_sim.html ..." | tee -a "$LOG"
# 2026-08-10 修复: 原 push origin main 推本地 main ref(落后 origin/main 时 non-ff 失败)，
# 改 push origin HEAD:main(推当前分支 tip, 与 deploy.sh L302 一致)。commit 落在当前分支,
# HEAD:main 保证 trade_sim.html 变更到达 main; 本地 main 是否落后无关。
git -C "$GIT_REPO" push origin HEAD:main 2>&1 | tee -a "$LOG"
PUSH_RC=${PIPESTATUS[0]:-1}
if [ "$PUSH_RC" -ne 0 ]; then
  echo "⚠ git push 失败（退出码 ${PUSH_RC}），尝试 fetch + rebase 重试..." | tee -a "$LOG"
  git -C "$GIT_REPO" fetch origin main 2>&1 | tee -a "$LOG" || true
  # stash 全仓库 tracked M + untracked（防 rebase 撞 dirty working tree，复用 deploy.sh 机制）
  STASH_CNT_BEFORE=$(git -C "$GIT_REPO" stash list 2>/dev/null | wc -l | tr -d ' ')
  git -C "$GIT_REPO" stash push --include-untracked -m "update_lab-rebase-$(date +%Y%m%d_%H%M%S)" 2>&1 | tee -a "$LOG" || true
  STASH_CNT_AFTER=$(git -C "$GIT_REPO" stash list 2>/dev/null | wc -l | tr -d ' ')
  LAB_STASHED=0
  if [ "$STASH_CNT_AFTER" -gt "$STASH_CNT_BEFORE" ]; then
    LAB_STASHED=1
    echo "✓ rebase 前已 stash 全仓库 tracked M + untracked 文件（stash@{0}）" | tee -a "$LOG"
  fi
  if git -C "$GIT_REPO" rebase origin/main 2>&1 | tee -a "$LOG"; then
    git -C "$GIT_REPO" push origin HEAD:main 2>&1 | tee -a "$LOG"
    PUSH2_RC=${PIPESTATUS[0]:-1}
    # pop stash（恢复工作区改动，数据文件冲突自动解决，复用 deploy.sh pop_rebase_stash 机制）
    if [ "$LAB_STASHED" = "1" ]; then
      _pop_out=$(git -C "$GIT_REPO" stash pop 2>&1)
      _pop_rc=$?
      echo "$_pop_out" | tee -a "$LOG"
      if [ "$_pop_rc" -ne 0 ]; then
        _conflicted=$(git -C "$GIT_REPO" diff --name-only --diff-filter=U 2>/dev/null)
        if [ -n "$_conflicted" ]; then
          _non_data=""
          for _f in $_conflicted; do
            case "$_f" in
              static-site/data/*.json|static-site/data/feed.xml)
                git -C "$GIT_REPO" checkout --theirs -- "$_f" 2>&1 | tee -a "$LOG"
                git -C "$GIT_REPO" add -- "$_f" 2>&1 | tee -a "$LOG"
                ;;
              *)
                _non_data="$_non_data $_f"
                ;;
            esac
          done
          if [ -z "$_non_data" ]; then
            git -C "$GIT_REPO" stash drop 2>&1 | tee -a "$LOG"
            echo "✓ stash pop 数据文件冲突已自动解决(--theirs)，stash 已 drop" | tee -a "$LOG"
          else
            echo "⚠ stash pop 有非数据文件冲突($_non_data)，保留 stash@{0} 待手动 git stash pop" | tee -a "$LOG"
          fi
        else
          echo "⚠ stash pop 失败(无冲突文件信息)，保留 stash@{0} 待手动处理" | tee -a "$LOG"
        fi
      fi
    fi
    if [ "$PUSH2_RC" -eq 0 ]; then
      echo "✓ rebase + 重试 push 成功" | tee -a "$LOG"
    else
      echo "⚠ rebase 后重试 push 仍失败" | tee -a "$LOG"
      GIT_DEPLOY_RC=1
    fi
  else
    git -C "$GIT_REPO" rebase --abort 2>/dev/null || true
    # rebase 失败也恢复 stash（避免丢工作区改动）
    if [ "$LAB_STASHED" = "1" ]; then
      git -C "$GIT_REPO" stash pop 2>&1 | tee -a "$LOG" || true
    fi
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
echo "退出码汇总: sim=$RC1 fusion=$RC2 matrix=$RC3 fusion_matrix=$RC4 retest=$RC5 honors=$RC_HONORS backtest=$RC6 abl=$RC_ABL cc=$RC_CC ps=$RC_PS ss=$RC_SS tsj=$RC_TSJ ts=$RC_TS r2=$R2_RC tradesim_r2=$R2_TSJ_RC lab_r2=$LAB_R2_RC git_tl=$GIT_DEPLOY_RC" | tee -a "$LOG"

# 刷新 schedule_stats.json（2026-07-24 方案A根治：从 deploy.sh:72 移到此处，在"结束"行后调用，
# gen_stats 能读到完整"开始+结束"对，正确配对当前任务 exit/dur，不再 pending null）
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"

# 独立 push schedule_stats.json 到 main（2026-07-30 方案C+R2：gen_stats 后立即 push 绕过 deploy.sh 时序）
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

# 2026-08-10 修复: git deploy(trade_sim.html push) 失败必须传播非零退出。
# 原脚本末尾为 summary echo, 无论 GIT_DEPLOY_RC 多少都 exit=0, 监控 exit!=0 路径漏报,
# 只靠 log 关键词(error: failed to push)抓(2026-08-10 lab_auto 误报邮件 exit=0 场景)。
# 传播后 schedule_monitor 的 exit!=0 路径也能捕获, 双路径兜底。
if [ "$GIT_DEPLOY_RC" -ne 0 ]; then
  echo "⚠ git deploy(trade_sim.html push) 失败(退出码 ${GIT_DEPLOY_RC})，返回非零退出供监控 exit!=0 捕获" | tee -a "$LOG"
  exit 1
fi
exit 0
