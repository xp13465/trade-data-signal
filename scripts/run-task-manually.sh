#!/bin/bash
# run-task-manually.sh —— 应急手动触发单个已停用的本机业务任务(阶段4c 停用后的兜底)
#
# 背景:2026-09-13 阶段4c,本机 35 个业务 launchd 已停用,由云上 systemd timer 接管
#       (避免本机与云上双写 R2)。本脚本用于应急时手动跑单个任务。
#
# 用法:bash scripts/run-task-manually.sh <task-name> [extra-args...]
#   例:bash scripts/run-task-manually.sh update-all force   # force 绕过交易日闸门
#       bash scripts/run-task-manually.sh daily-brief
#
# 环境说明:
#   - REPO/GIT_REPO/PATH 按 launchd 原 plist 设定(trade-data 为主库,trade 为 git 仓)。
#   - PURGE_SECRET 等敏感凭证不在此硬编码,由底层脚本(upload_r2.py/deploy.sh)自身从 .env 加载。
#   - 工作目录统一切到 trade-data(原 plist 绝大多数 WorkingDirectory=.../trade-data;
#     trade-data/scripts 是 symlink 指向 trade/scripts,脚本路径跨两树通用)。
#
# 可用任务名(与 restore-launchd.sh 的 35 个停用 label 一一对应):
#   update-all | backfill-evening | intraday-snapshot | futures-backfill | lhb-backfill
#   rzhb-backfill | etf-national-team | lab-auto | us-stock-morning | overfit-monitor
#   gold-night | nextday-plan | s06-snapshot | turnover-backfill | check-data-gap
#   fapi-daily | daily-brief | daily-summary-supplement | brief-push | fetch-news
#   pf-score-daily | pf-score-weekly | pf-stage0-manager | pf-stage0-nav | pf-stage0-overview
#   pf-stage0-risk | public-fund-daily | public-fund-full | public-fund-quarterly
#   public-fund-estimation | etf-track-index | ab-direction-anchor | self-heal
#   schedule-monitor | kelly-intraday-rerun

set -euo pipefail

REPO="/Users/linhuichen/code/trade-data"
GIT_REPO="/Users/linhuichen/code/trade"
export REPO GIT_REPO
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export TRADE_DIR="/Users/linhuichen/code/trade"   # ab-direction-anchor 用 TRADE_DIR(其余任务用 REPO)

TASK="${1:-}"
shift || true

if [ -z "$TASK" ]; then
  echo "用法: bash scripts/run-task-manually.sh <task-name> [extra-args...]"
  echo "可用任务名见脚本头部注释;常用: update-all / daily-brief / intraday-snapshot / backfill-evening / lab-auto"
  exit 2
fi

# run <脚本绝对路径> [args...] —— 统一在 trade-data 工作目录下执行
run() {
  echo "[manual-run] $*"
  ( cd "$REPO" && "$@" )
}

case "$TASK" in
  update-all)               run /bin/bash "$REPO/scripts/update_all.sh" "$@" ;;
  backfill-evening)         run /bin/bash "$REPO/scripts/backfill_metrics.sh" "$@" ;;
  intraday-snapshot)        run /bin/bash "$REPO/scripts/intraday_snapshot.sh" "$@" ;;
  futures-backfill)         run /bin/bash "$REPO/scripts/futures_backfill.sh" "$@" ;;
  lhb-backfill)             run /bin/bash "$REPO/scripts/lhb_backfill.sh" "$@" ;;
  rzhb-backfill)            run /bin/bash "$REPO/scripts/rzhb_backfill.sh" "$@" ;;
  etf-national-team)        run /bin/bash "$REPO/scripts/etf_national_team_backfill.sh" "$@" ;;
  lab-auto)                 run /bin/bash "$REPO/scripts/update_lab.sh" "$@" ;;
  us-stock-morning)         run /bin/bash "$REPO/scripts/us_stock_morning.sh" "$@" ;;
  overfit-monitor)          run /bin/bash "$REPO/scripts/overfit_monitor.sh" "$@" ;;
  gold-night)               run /bin/bash "$REPO/scripts/gold_night.sh" "$@" ;;
  nextday-plan)             run /bin/bash "$REPO/scripts/nextday_plan.sh" "$@" ;;
  s06-snapshot)             run /bin/bash "$REPO/scripts/s06_snapshot.sh" "$@" ;;
  turnover-backfill)        run /bin/bash "$REPO/scripts/turnover_backfill.sh" "$@" ;;
  check-data-gap)           run /bin/bash "$REPO/scripts/check_data_gap_alerts.sh" "$@" ;;
  fapi-daily)               run /bin/bash "$GIT_REPO/scripts/fapi_daily_syn.sh" "$@" ;;
  daily-brief)              run /bin/bash "$REPO/scripts/run_daily_brief.sh" --multi "$@" ;;
  daily-summary-supplement) run "$REPO/.venv/bin/python" "$REPO/scripts/daily_summary_email.py" --mode supplement "$@" ;;
  brief-push)               run /bin/bash "$REPO/scripts/brief_push_wrapper.sh" "$@" ;;
  fetch-news)               run "$REPO/.venv/bin/python" "$GIT_REPO/scripts/fetch_news.py" "$@" ;;
  pf-score-daily)           run /bin/bash "$REPO/scripts/pf_score_daily.sh" "$@" ;;
  pf-score-weekly)          run /bin/bash "$REPO/scripts/pf_score_weekly.sh" "$@" ;;
  pf-stage0-manager)        run /bin/bash "$REPO/scripts/stage0_manager.sh" "$@" ;;
  pf-stage0-nav)            run /bin/bash "$REPO/scripts/stage0_nav.sh" "$@" ;;
  pf-stage0-overview)       run /bin/bash "$REPO/scripts/stage0_overview.sh" "$@" ;;
  pf-stage0-risk)           run /bin/bash "$REPO/scripts/stage0_risk.sh" "$@" ;;
  public-fund-daily)        run /bin/bash "$REPO/scripts/public_fund_daily.sh" "$@" ;;
  public-fund-full)         run /bin/bash "$REPO/scripts/public_fund_full.sh" "$@" ;;
  public-fund-quarterly)    run /bin/bash "$REPO/scripts/public_fund_quarterly.sh" "$@" ;;
  public-fund-estimation)   run /bin/bash "$REPO/scripts/public_fund_estimation.sh" "$@" ;;
  etf-track-index)          run "$REPO/.venv/bin/python" "$REPO/scripts/fetch_etf_track_index.py" "$@" ;;
  ab-direction-anchor)      run /bin/bash "$GIT_REPO/scripts/run_ab_direction_anchor.sh" "$@" ;;
  self-heal)                run /bin/bash "$REPO/scripts/self_heal.sh" "$@" ;;
  schedule-monitor)         run /bin/bash "$REPO/scripts/schedule_monitor.sh" "$@" ;;
  kelly-intraday-rerun)     run /bin/bash "$REPO/scripts/kelly_intraday_rerun.sh" "$@" ;;
  list)
    echo "可用任务名(与 restore-launchd.sh 停用的 35 个 label 对应):"
    echo "update-all backfill-evening intraday-snapshot futures-backfill lhb-backfill rzhb-backfill"
    echo "etf-national-team lab-auto us-stock-morning overfit-monitor gold-night nextday-plan s06-snapshot"
    echo "turnover-backfill check-data-gap fapi-daily daily-brief daily-summary-supplement brief-push fetch-news"
    echo "pf-score-daily pf-score-weekly pf-stage0-manager pf-stage0-nav pf-stage0-overview pf-stage0-risk"
    echo "public-fund-daily public-fund-full public-fund-quarterly public-fund-estimation"
    echo "etf-track-index ab-direction-anchor self-heal schedule-monitor kelly-intraday-rerun"
    ;;
  *)
    echo "未知任务: $TASK"
    echo "用法: bash scripts/run-task-manually.sh <task-name> [extra-args...]"
    echo "可用任务名见脚本头部注释,或运行 'bash scripts/run-task-manually.sh list' 列出"
    exit 2
    ;;
esac
