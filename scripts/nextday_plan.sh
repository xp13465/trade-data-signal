#!/usr/bin/env bash
# nextday_plan.sh - 次日买入计划生成器 launchd 包装(交易日 22:30 定时, PRD 阶段一 §3/§6)
#
# 背景: 把「T 日盘后选标的 -> T+1 日开盘买入」全流程自动化的第一步 —— 每天 22:30
# 生成次日买入计划(复用 kelly_posrating K=1 top1 同构逻辑), 落盘两树 + R2 + 通知。
# 本脚本=launchd com.trade.nextday-plan 的包装:
#   ①nextday_plan_generator.py 生成计划(读 4 产物 + etf_daily, 复用 kelly_posrating
#     make_passes_fade/_collect_base_pool/_position_cap_kept_keys(K=1), 与回测同构防前视)
#   ②脚本内落盘 data/nextday_plan.json + 两树 static-site/data/ + R2(upload-data-files)
#   ③notify.send 邮件+飞书推送「明日计划」(干跑阶段 AUTO_EXEC_ON=false 不真实下单)
# 任一段 FAIL → notify.py --severe 告警(同 s06_snapshot 先例)。
#
# 时点选择依据(§14 + 时序倒挂根治 2026-09-17):
#   22:30 —— 核心约束 = etf_daily 当日(T)收盘价必须已入库(否则 _prev_close 退化为前日价, 次日
#   买入价时序倒挂)。etf_national_team 20:07 采集对当日数据可能返空, 21:47 第二批 backfill 才
#   补上 T 日收盘价, 故 20:55 后移到 22:30 晚于 21:47。其余源(4 产物 17:50 export / 20:35
#   s06-snapshot)均早于 22:30; 22:30 落 22:00 deploy 后、22:35 check-data-gap 前空档, 秒级完成。
#   不推 main 不写 DB(只写 static-site/data JSON + R2), §14「盘后时点不推 main」约束满足。
#   ⚠️ pmset/唤醒: 22:30 晚于「机器活跃至 21:40 overfit-monitor」窗口, 若机器已睡需 launchd 唤醒
#   (StartCalendarInterval 标准行为)或主控补 pmset 定时唤醒, 上线后验首晚是否漏跑。
# 非交易日: 跳过(闸门同 overfit_monitor.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)。
#   传 force 绕过闸门补跑。
#
# 用法: bash scripts/nextday_plan.sh [force] [--date YYYYMMDD]
#   手动裸跑也安全: REPO/GIT_REPO 缺省兜底且 export 成环境变量。
# 日志: data/logs/nextday_plan_launchd.log(固定名 append, 标准开始/结束行供
#   schedule_monitor 漏跑检查直读, 同 s06_snapshot 先例)
set -u

export REPO="${REPO:-/Users/linhuichen/code/trade-data}"
export GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
LOG="$LOGDIR/nextday_plan_launchd.log"
# #44 日志不可写隐患根治(同 s06_snapshot 先例): LOGDIR 不可创建/不可写或 $LOG 不可追加时,
# 非交互 bash 里 `>> "$LOG"` 重定向失败会让整条命令(含末尾 notify.py 告警)根本不执行 →
# 告警静默跳过。此处显式兜底: 落到 /tmp 保证可写的 fallback, 警告打到 stderr, 不静默吞告警。
if ! mkdir -p "$LOGDIR" 2>/dev/null || [ ! -w "$LOGDIR" ] || ! ( : >> "$LOG" ) 2>/dev/null; then
  LOG="/tmp/nextday_plan_$(date +%s).log"
  echo "$(date '+%F %T') [nextday_plan] 警告: 日志 $LOGDIR/nextday_plan_launchd.log 不可写(磁盘满/权限), 改落 fallback $LOG" >&2
fi
cd "$REPO"

# 交易日闸门(同 overfit_monitor.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)
# 参数: 含 "force" 绕过闸门; 其余参数原样透传给生成器(--date 等)
FORCE=0
GEN_ARGS=()
for _a in "$@"; do
  if [ "$_a" = "force" ]; then FORCE=1; else GEN_ARGS+=("$_a"); fi
done
if [ "$FORCE" -ne 1 ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "$(date '+%F %T') 非交易日, 跳过次日买入计划生成" >> "$LOG"
    exit 0
  fi
fi

echo "=== nextday_plan.sh 开始 $(date '+%F %T') ===" >> "$LOG"

RC=0
if [ "${#GEN_ARGS[@]}" -gt 0 ]; then
  "$PY" scripts/nextday_plan_generator.py "${GEN_ARGS[@]}" >> "$LOG" 2>&1
else
  "$PY" scripts/nextday_plan_generator.py >> "$LOG" 2>&1
fi
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "✗ 次日买入计划生成失败 rc=${RC}" >> "$LOG"
  "$PY" scripts/notify.py \
    "[告警] 次日买入计划生成失败 $(date '+%m-%d %H:%M')" \
    "nextday_plan_generator.py 退出码 ${RC}, 次日买入计划未生成。<br>日志: $LOG(尾部 50 行)<br>影响: 明日无自动买入计划(干跑阶段, 不真实下单); 需人工核查产物(signal_kelly_trades/backtest/s06/loss 是否就绪)。" \
    --severe --from-prefix "[告警]" \
    --alert-issue "次日买入计划生成失败" --alert-log "$LOG" \
    --dedup-key nextday_plan_fail --dedup-window 3600 2>&1 | tee -a "$LOG" || true
fi

echo "=== nextday_plan.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"
