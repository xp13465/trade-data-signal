#!/usr/bin/env bash
# pipeline.sh - 单条采集流水线：采集(子集) -> 计算 -> 导出 -> (flock) commit+push
#
# 把原串行 collect 拆成并行流水线，每个 pipeline 独立上线，慢任务不阻塞快核心。
#   core        step metrics,indices,industry_extras  + compute + 全量 export + push（快核心，先上线）
#   width       step mootdx,industry_width,width_history + compute + 全量 export + push（慢宽度，后覆盖）
#   futures     step futures                           + 全量 export + push（独立）
#   stock_daily step stock_daily                       （死端，仅采集备用，不 export 不 push）
#   turnover    step turnover (baostock增量 + cleanup_d3d2 算 a_turnover) + 全量 export + push
#               （慢，baostock 5527 codes 串行 ~10-30min；设 RUN_BAOSTOCK=1 启用 baostock 子步；
#                不阻塞 core——core 先抢 deploy 锁上线，turnover 采完后排号 deploy）
#
# 用法：bash scripts/pipeline.sh <name>
# 交易日闸门由 update_all.sh 统一判断；本脚本不判断 -> 手动跑 = 强制采集（补数据场景）。
# 日志：data/logs/pipeline_<name>_<STAMP>.log
# 退出码：有 push 的以 deploy 为准（公网状态）；stock_daily 以 collect 为准。
set -u

REPO=/Users/linhuichen/code/trade
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
NAME="${1:?usage: pipeline.sh <core|width|futures|stock_daily>}"
LOG="$LOGDIR/pipeline_${NAME}_${STAMP}.log"
LOCK="/tmp/trade_deploy.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

case "$NAME" in
  core)        STEPS="metrics,indices,industry_extras";        DO_COMPUTE=1; DO_EXPORT=1; DO_PUSH=1 ;;
  width)       STEPS="mootdx,industry_width,width_history";    DO_COMPUTE=1; DO_EXPORT=1; DO_PUSH=1 ;;
  futures)     STEPS="futures";                                DO_COMPUTE=0; DO_EXPORT=1; DO_PUSH=1 ;;
  stock_daily) STEPS="stock_daily";                            DO_COMPUTE=0; DO_EXPORT=0; DO_PUSH=0 ;;
  turnover)    STEPS="turnover";                               DO_COMPUTE=0; DO_EXPORT=1; DO_PUSH=1 ;;
  *) echo "✗ 未知 pipeline: $NAME（可选: core|width|futures|stock_daily|turnover）" | tee -a "$LOG"; exit 2 ;;
esac

# turnover pipeline 需跑 baostock（慢），设 RUN_BAOSTOCK=1 启用 runner turnover step 的 baostock 子步。
# 其它 pipeline 不设 -> runner os.environ.get("RUN_BAOSTOCK") 为 None -> baostock 子步跳过（cleanup 仍跑）。
if [ "$NAME" = "turnover" ]; then
  export RUN_BAOSTOCK=1
fi

echo "=== pipeline[$NAME] 开始 $(date '+%Y-%m-%d %H:%M:%S') steps=$STEPS ===" | tee -a "$LOG"

# 1) 采集（子集；collect_runner 内部各 step try/except 兜底，部分失败不中断）
echo "-> [$NAME] 采集 steps=$STEPS ..." | tee -a "$LOG"
"$PY" -c "
from app.collector import runner
runner.run(steps='$STEPS'.split(','))
" 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]:-1}
echo "[$NAME] 采集退出码=$COLLECT_RC（部分失败仍继续，非 0 不阻塞后续）" | tee -a "$LOG"

# 2) 计算（core/width 跑全量 compute；futures 的 accuracy 已在 step 内算；stock_daily 不算）
if [ "$DO_COMPUTE" = "1" ]; then
  echo "-> [$NAME] compute_runner ..." | tee -a "$LOG"
  "$PY" -c "from app.compute import runner; runner.run()" 2>&1 | tee -a "$LOG"
fi

# 3) 导出 + commit + push（with_lock 持 fcntl.flock 串行，避免多 pipeline 并发
#    git index.lock 冲突 / 互相 stage 半截 JSON；macOS 无 flock(1)，用 Python fcntl）
if [ "$DO_EXPORT" = "1" ]; then
  echo "-> [$NAME] 等待 deploy 锁（串行化 git）..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/with_lock.py" "$LOCK" bash "$REPO/scripts/deploy.sh" "$NAME" >> "$LOG" 2>&1
  DEPLOY_RC=$?
  [ "$DEPLOY_RC" -ne 0 ] && echo "✗ [$NAME] deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"
else
  DEPLOY_RC=0
fi

echo "=== pipeline[$NAME] 结束 $(date '+%Y-%m-%d %H:%M:%S') collect=$COLLECT_RC deploy=$DEPLOY_RC ===" | tee -a "$LOG"
if [ "$DO_PUSH" = "1" ]; then exit "$DEPLOY_RC"; else exit "$COLLECT_RC"; fi
