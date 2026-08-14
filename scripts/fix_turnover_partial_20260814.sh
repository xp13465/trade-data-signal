#!/usr/bin/env bash
# fix_turnover_partial_20260814.sh - 清理 8-14 baostock 封禁致换手率分布偏样本(4374/5200=84%)
#
# 背景(2026-08-14 reviewer FAIL P2-1):旧代码 17:50 已把 8-14 偏样本写入 daily_metric:
#   a_turnover_mean=2.993(8-13 全量 3.49),MIN_STOCKS_PER_DAY=4000 没拦住(4374>=4000)。
# 新代码覆盖率拦截只防未来日,rebackfill 补码不触发 daily_metric 重算,8-14 偏样本永久残留。
#
# 依赖(代码上线后,见本 commit):cleanup_d3d2 新增 purge-turnover-date 命令 +
#   run_turnover 内部覆盖率<max(4000,0.95×universe) 拦截。
#
# 输入:无(硬编码目标日 20260814)
# 输出:data/sentiment.db 的 daily_metric 8-14 a_turnover_* 行被清理后按覆盖率重算
#
# 复现命令(在 production REPO=/Users/linhuichen/code/trade-data 跑):
#   bash scripts/fix_turnover_partial_20260814.sh
#
# 流程 3 步:
#   1) purge-turnover-date 20260814  删 8-14 偏样本 a_turnover_* 行(保留 source='manual')
#      -> daily_metric 末尾回退到 8-13,下次增量从 8-14 重算
#   2) rebackfill 20260814           补 8-14 缺码(需 baostock 封禁解除,未解除可先跳过)
#   3) run_turnover --full           重算;cleanup 内部覆盖率拦截:8-14 未补全(<95%)跳过、
#      补全后写正确值(幂等,可重复跑)
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
PY="$REPO/.venv/bin/python"
TARGET="${1:-20260814}"   # 默认清理 8-14;可传其他日期复用

echo "=== fix_turnover_partial $TARGET 开始 $(date '+%Y-%m-%d %H:%M:%S') ==="
cd "$REPO" || { echo "!! 无法 cd $REPO"; exit 1; }

# 步骤 1:purge 目标日偏样本 a_turnover_* 行
echo "-> [1/3] purge $TARGET 的 a_turnover_* 偏样本行 ..."
"$PY" -m app.collector.cleanup_d3d2 purge-turnover-date "$TARGET"
echo "   (确认:8-14 a_turnover_mean 行应已删除)"

# 步骤 2:rebackfill 补目标日缺码(baostock 封禁解除后生效;仍 10001011 则退出码 2 但继续)
echo "-> [2/3] rebackfill $TARGET 缺码 ..."
"$PY" -m app.collector.baostock_daily rebackfill "$TARGET" || echo "   (rebackfill 未完整,可稍后重跑;不影响步骤3的拦截)"

# 步骤 3:重算换手率分布(cleanup 内部按 count < max(4000,0.95×universe) 拦截偏样本日)
echo "-> [3/3] run_turnover --full 重算(覆盖率拦截生效) ..."
"$PY" -m app.collector.cleanup_d3d2 turnover --full
echo "   (确认:8-14 若未补全则显示 skipped_partial 跳过;补全则写入全量正确值)"

echo "=== fix_turnover_partial $TARGET 完成 $(date '+%Y-%m-%d %H:%M:%S') ==="
