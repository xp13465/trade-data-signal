#!/bin/bash
# public_fund_daily.sh - 公募基金日更（launchd 16:30 定时）
#
# 调 python -m app.collector.public_fund daily（日更净值+盘中估算+三指数刷新+估算仓位变化, ~15s）
# + 持 deploy 锁推送 static-site/data/public_fund_*.json
#
# 时点: 每交易日 16:30（主槽，收盘后 1h）+ 17:00（兜槽）。
# akshare fund_open_fund_daily_em 约 16:00-17:00 发布当日净值，16:30 采可能部分，
# 17:00 兜槽补完整。轻量 15s，幂等覆盖重采。
# pipeline_daily 含 fetch_index_daily(三指数baostock ~5s), 确保 fund_index_daily 每日更新,
# _compute_position_estimate 有最新指数算当日预估仓位(2026-08-02 根治: 原不调致算法缺当日r_hs300跳过)。
#
# 进程互斥:
#   - daily 锁 /tmp/trade_public_fund_daily.lock（--nb 非阻塞）: 防自身重复并发
#   - python 内 public_fund.lock: 防 quarterly/full/daily 互相并发（共用，撞锁跳过）
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）: 串行化 git
#
# 预算表(2026-10-29 #352, 内外层成对 L55; 外层 systemd TimeoutStartSec=1860s):
#   pipeline 300s / export(deploy.sh 内 export.py --incremental) 600s / nav_bucket 300s(既有) / 外层 1860s。
#   依据: 16:20 档实测 845-890s(其中 export 463s=52%, pipeline 161.6s, nav_bucket 70s, 其余~195s);
#   最坏路径 300+600+300+195=1395s < 1860s 留梯度。详见 docs/ops/pf-daily-timeout-rca-20261029.md
#   ⚠ 只在本脚本给预算, 不改 deploy.sh 全局默认(17:50 全量链共享, 改默认=行为变更不是预算变更)。
#
# 非交易日: 默认跳过。force 可绕过。
#
# 用法: bash scripts/public_fund_daily.sh [force]
# 日志: data/logs/public_fund_daily_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠
if [ "$(uname -s)" = "Darwin" ]; then
    caffeinate -i -w $$ >/dev/null 2>&1 &
fi

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/public_fund_daily_${STAMP}.log"
LOCK="/tmp/trade_public_fund_daily.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 可移植超时包装(与 scripts/s06_snapshot.sh / check_data_gap_alerts.sh 同一惯用法):
# 云上 Linux 走 coreutils timeout(即真正的 `timeout N`); 本机 mac 无 timeout 走 gtimeout/perl alarm。
# 超时=非零退出, 与「命令自己失败」走同一失败分支(不改失败语义)。
run_to() {
  local t="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$t" "$@"
  else
    perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"
  fi
}

# 自包装: 首次调用经 with_lock.py --nb 持 daily 锁重跑自己，PF_DAILY_LOCKED=1 防递归。
if [ -z "${PF_DAILY_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env PF_DAILY_LOCKED=1 bash "$0" "$@"
fi

echo "=== public_fund_daily.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过公募基金日更（force 可绕过）" | tee -a "$LOG"
  echo "=== public_fund_daily.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 日更采集（fund_open_fund_daily_em ~23738 行 + 估算仓位变化, ~8s）
#    pipeline_daily 不调 export_json_files（只更新 fund_daily_nav 表），需手动 export 推 JSON。
#    预算 300s（实测 161.6s / 24.4s, 余量约 2x）; 被杀=非零退出, 走下面「跳过 export+deploy」既有分支。
echo "-> 采集公募基金日更净值（预算 300s）..." | tee -a "$LOG"
run_to 300 "$PY" -m app.collector.public_fund daily 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "公募基金日更采集退出码=$COLLECT_RC" | tee -a "$LOG"
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_daily] daily 失败 exit=$COLLECT_RC" | tee -a "$LOG"
fi

# 2) 导出 5 类 JSON + 3) deploy 推送
# 修复a(2026-08-03): daily 撞锁(python sys.exit(2))或其他失败时, 不 export+deploy,
# 避免推旧数据上线(原 bug: 撞锁 exit0 当成功, 继续 export+deploy 旧 position_estimate.json)
EXPORT_RC=0
DEPLOY_RC=0
NAV_REFRESH_RC=0   # #278 净值桶刷新: 0=已刷新/无变更, 10=锁或窗口跳过(非失败), 其它=失败
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[public_fund_daily] daily 失败/撞锁跳过 exit=$COLLECT_RC, 跳过 export+deploy 避免推旧数据上线" | tee -a "$LOG"
else
  echo "-> 导出 5 类 JSON ..." | tee -a "$LOG"
  "$PY" -m app.collector.public_fund export 2>&1 | tee -a "$LOG"
  EXPORT_RC=${PIPESTATUS[0]}
  echo "导出退出码=$EXPORT_RC" | tee -a "$LOG"
  if [ "$EXPORT_RC" -eq 0 ]; then
    # 2.5) nav_bucket 净值桶增量刷新（#278, 2026-10-22 用户拍板方案 A, 根因见
    #   docs/ops/failed-units-rca-20261022.md「trade-public-fund-daily」行）:
    #   日更早于 17:50 全量链, 当日新净值/同日修正值已入库而 nav_bucket 产物还是旧值 ⇒
    #   deploy 内 fund_nav 闸门(阻断级)必 FAIL。修复 = deploy 前先刷新净值桶再校验;
    #   与 17:50 全量链**同一脚本同一 payload 实现**(export_fund_nav.py --daily-refresh),
    #   只重建最近 7 天有净值写入的基金所在桶, 内容未变不重写(幂等)。
    #   失败语义: 刷新失败 ⇒ 明确阻断本次 deploy(不静默继续, 防把「刷新失败」误报成 fund_nav 失败)。
    #   fund_nav 阻断级 / 校验阈值 / 17:50 全量链行为均不动。
    . "$REPO/scripts/lib/nav_bucket_refresh.sh"
    echo "-> 刷新 nav_bucket 净值桶（增量, 与 17:50 全量链同脚本同口径）..." | tee -a "$LOG"
    NAV_REFRESH_LOG="$LOG" nav_bucket_refresh_run
    NAV_REFRESH_RC=$?
    if nav_bucket_refresh_blocks_deploy "$NAV_REFRESH_RC"; then
      echo "✗ nav_bucket 刷新失败(rc=$NAV_REFRESH_RC) —— 阻断本次 deploy: 净值桶未与 DB 对齐; 若继续, fund_nav 闸门(阻断级)会拦下并把「刷新失败」误报成 fund_nav 失败" | tee -a "$LOG"
    else
      # 推送（deploy.sh public-fund 重新 export + git push + R2 上传; #149 方案① 外层锁去掉,
      # 段1 锁外可并发, 段2 git 内部锁串行）
      echo "-> 推送 deploy public-fund（export+R2 锁外并发, git 段内部锁串行）..." | tee -a "$LOG"
      # 预算(2026-10-29 #352) 只对这条调用链生效, 不改 deploy.sh 全局默认:
      #   EXPORT_TIMEOUT=600 包 deploy.sh 内 export.py --incremental（实测 463s）;
      #   GIT_LOCK_TIMEOUT=420 只覆盖本次等 deploy 锁上限（deploy.sh 全局默认 3600 共享给 17:50 全量链, 不动）。
      EXPORT_TIMEOUT=600 GIT_LOCK_TIMEOUT=420 bash "$REPO/scripts/deploy.sh" public-fund 2>&1 | tee -a "$LOG"
      DEPLOY_RC=${PIPESTATUS[0]}
      [ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"
    fi
  else
    echo "[public_fund_daily] export 失败 exit=$EXPORT_RC, 跳过 deploy" | tee -a "$LOG"
  fi
fi

# 综合退出码
FINAL_RC=0
[ "$COLLECT_RC" -ne 0 ] && FINAL_RC=$COLLECT_RC
[ "$EXPORT_RC" -ne 0 ] && FINAL_RC=$EXPORT_RC
# nav_bucket 刷新失败(非 0 且非 10=跳过)才算失败; 10 只是「锁/窗口跳过」, 不算失败(§5.8 不假绿)
[ "$NAV_REFRESH_RC" -ne 0 ] && [ "$NAV_REFRESH_RC" -ne 10 ] && FINAL_RC=$NAV_REFRESH_RC
[ "$DEPLOY_RC" -ne 0 ] && FINAL_RC=$DEPLOY_RC

echo "=== public_fund_daily.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json + 独立 push
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit "$FINAL_RC"
