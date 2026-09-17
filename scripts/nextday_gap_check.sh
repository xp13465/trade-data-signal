#!/usr/bin/env bash
# nextday_gap_check.sh - 次日买入计划伪跳空二次剔除 定时包装(交易日 9:26, PRD 阶段一 §3/§6)
#
# 背景: nextday_plan_generator.py 在 T 日 22:30 生成次日计划时, 对「次日 open 已入库」的历史回填段
# 能做真伪跳空校验(A1); 但「当日计划」的 T+1 开盘价尚未产生只能跳过。本脚本在 T+1 日 9:26
# (集合竞价 9:25 结束、开盘价已定)拉 akshare 当日真实开盘价做二次剔除, 补齐 A1 当日跳过的缺口。
# 本脚本 = 云上 systemd timer trade-nextday-gap-check 的包装(源 launchd com.trade.nextday-gap-check):
#   ①nextday_gap_check.py 拉执行日开盘价, 对 |gap|>20% 的买入行标 skipped + status_text
#   ②nextday_plan.json 条目加 gap_excluded:true
#   ③落盘两树 + R2(upload-data-files)+ 通知(邮件+飞书)
# 任一段 FAIL → notify.py --severe 告警(同 nextday_plan.sh 先例)。
#
# 时点选择依据(§14):
#   9:26 —— 集合竞价 9:25 结束开盘价已定; 与 intraday-snapshot 9:25 轮次错开 1 分钟(该任务秒级),
#   与 9:40 kelly-intraday-rerun / 9:45 snapshot 不冲突。盘中只写 static-site/data JSON + R2,
#   不推 main 不写 DB(§14 盘中不跑全量 export+deploy, intraday 走 R2 不推 main)。
# 非交易日: 跳过(闸门同 nextday_plan.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)。传 force 绕过。
#
# 用法: bash scripts/nextday_gap_check.sh [force] [--date YYYYMMDD] [--dry-run] [--test-open "code:price"]
#   手动裸跑也安全: REPO/GIT_REPO 缺省兜底且 export 成环境变量。
# 日志: data/logs/nextday_gap_check_launchd.log(固定名 append, 标准开始/结束行供
#   schedule_monitor 漏跑检查直读, 同 nextday_plan.sh 先例)
set -u

export REPO="${REPO:-/Users/linhuichen/code/trade-data}"
export GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
mkdir -p "$LOGDIR"
cd "$REPO"
LOG="$LOGDIR/nextday_gap_check_launchd.log"

# 交易日闸门(同 nextday_plan.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)
# 参数: 含 "force" 绕过闸门; 其余参数原样透传(--date/--dry-run/--test-open 等)
FORCE=0
CHECK_ARGS=()
for _a in "$@"; do
  if [ "$_a" = "force" ]; then FORCE=1; else CHECK_ARGS+=("$_a"); fi
done
if [ "$FORCE" -ne 1 ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "$(date '+%F %T') 非交易日, 跳过伪跳空二次剔除" >> "$LOG"
    exit 0
  fi
fi

echo "=== nextday_gap_check.sh 开始 $(date '+%F %T') ===" >> "$LOG"

RC=0
if [ "${#CHECK_ARGS[@]}" -gt 0 ]; then
  "$PY" scripts/nextday_gap_check.py "${CHECK_ARGS[@]}" >> "$LOG" 2>&1
else
  "$PY" scripts/nextday_gap_check.py >> "$LOG" 2>&1
fi
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "✗ 伪跳空二次剔除失败 rc=${RC}" >> "$LOG"
  "$PY" scripts/notify.py \
    "[告警] 次日买入计划伪跳空校验失败 $(date '+%m-%d %H:%M')" \
    "nextday_gap_check.py 退出码 ${RC}, 伪跳空二次剔除未完成。<br>日志: $LOG(尾部 50 行)<br>影响: 执行日买入行可能未做伪跳空剔除(干跑阶段不真实下单), 需人工核查。注意: 若退出码 2 为开盘价就绪闸 FAIL(akshare 两次取不到), 脚本已标记「伪跳空校验未完成(待人工)」, 本条为包装层兜底重复告警(不同 dedup key 不互吞)。" \
    --severe --from-prefix "[告警]" \
    --alert-issue "次日买入计划伪跳空校验失败" --alert-log "$LOG" \
    --dedup-key nextday_gap_check_fail --dedup-window 3600 >> "$LOG" 2>&1
fi

echo "=== nextday_gap_check.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"
