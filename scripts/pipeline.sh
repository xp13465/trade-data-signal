#!/usr/bin/env bash
# pipeline.sh - 单条采集流水线：采集(子集) -> 计算（O1 后不各自 deploy，统一由 update_all.sh 末尾跑）
#
# 把原串行 collect 拆成并行流水线，各 pipeline 采集+计算写入 DB，慢任务不阻塞快核心。
#   core        step metrics,indices,industry_extras  + compute
#   width       step mootdx,industry_width,width_history + compute
#   futures     step futures
#   stock_daily step stock_daily                       （死端，仅采集备用，不 export 不 push）
#   turnover    step turnover (baostock增量 + cleanup_d3d2 算 a_turnover)（设 RUN_BAOSTOCK=1 启用 baostock 子步）
# O1 收敛（2026-08-17 批次A）：默认 DEPLOY_EACH=0，本 pipeline 不各自跑完整 deploy
#   （完整 export+R2+备份+push 统一由 update_all.sh 末尾 1 次完整 deploy 承担，4 遍→1 遍）。
#   设 DEPLOY_EACH=1 恢复旧行为（单跑 pipeline 需立即上线时用）。
#
# 用法：bash scripts/pipeline.sh <name>
# 交易日闸门由 update_all.sh 统一判断；本脚本不判断 -> 手动跑 = 强制采集（补数据场景）。
# 日志：data/logs/pipeline_<name>_<STAMP>.log
# 退出码：O1 默认以 collect 为准；DEPLOY_EACH=1 时有 push 的以 deploy 为准（公网状态）。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
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
  *) echo "✗ 未知 pipeline: ${NAME}（可选: core|width|futures|stock_daily|turnover）" | tee -a "$LOG"; exit 2 ;;
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
echo "[$NAME] 采集退出码=${COLLECT_RC:-?}(部分失败仍继续,非0不阻塞后续)" | tee -a "$LOG"

# 2) 计算（core/width 跑全量 compute；futures 的 accuracy 已在 step 内算；stock_daily 不算）
if [ "$DO_COMPUTE" = "1" ]; then
  echo "-> [$NAME] compute_runner ..." | tee -a "$LOG"
  "$PY" -c "from app.compute import runner; runner.run()" 2>&1 | tee -a "$LOG"
fi

# 3) 导出 + commit + push（with_lock 持 fcntl.flock 串行，避免多 pipeline 并发
#    git index.lock 冲突 / 互相 stage 半截 JSON；macOS 无 flock(1)，用 Python fcntl）
# O1 收敛（2026-08-17 批次A）：默认 DEPLOY_EACH=0，各 pipeline 只采集+计算，
#   不再各自跑完整 deploy（完整 export+R2+备份+push 统一由 update_all.sh 末尾 1 次完整 deploy 承担，
#   避免 4 遍重复 deploy = 88min 主因）。DEPLOY_EACH=1 可恢复旧行为（单跑 pipeline 需立即上线时用）。
DEPLOY_EACH="${DEPLOY_EACH:-0}"
if [ "$DO_EXPORT" = "1" ] && [ "$DEPLOY_EACH" = "1" ]; then
  echo "-> [$NAME] 等待 deploy 锁（串行化 git）..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/with_lock.py" "$LOCK" bash "$REPO/scripts/deploy.sh" "$NAME" >> "$LOG" 2>&1
  DEPLOY_RC=$?
  [ "$DEPLOY_RC" -ne 0 ] && echo "✗ [$NAME] deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"
elif [ "$DO_EXPORT" = "1" ] && [ "$DEPLOY_EACH" != "1" ]; then
  # O1：本 pipeline 不做 deploy（deploy 统一由 update_all.sh 末尾跑 1 次），只记占位退出码 0
  echo "-> [$NAME] O1 收敛：跳过本 pipeline deploy（统一由 update_all.sh 末尾 1 次完整 deploy 覆盖）" | tee -a "$LOG"
  DEPLOY_RC=0
else
  DEPLOY_RC=0
fi

echo "=== pipeline[$NAME] 结束 $(date '+%Y-%m-%d %H:%M:%S') collect=$COLLECT_RC deploy=$DEPLOY_RC ===" | tee -a "$LOG"
# O1：pipeline 不再以 deploy 退出码为准（deploy 已统一），以采集/计算退出码为准
if [ "$DO_PUSH" = "1" ] && [ "$DEPLOY_EACH" = "1" ]; then exit "$DEPLOY_RC"; else exit "$COLLECT_RC"; fi
