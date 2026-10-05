#!/usr/bin/env bash
# check_r2_consistency.sh - §22 多源(http 层)一致性巡检包装(#160 / D5 P0-1)
#
# 背景(2026-10-05 #160,docs/ops/cloud-healthcheck-20261003/D5-deploy-chain-audit.md P0-1):
#   check_r2_consistency.py 存在但全仓无自动调度点(schedule_monitor.sh 仅注释引用、
#   systemd 无 unit、日志无运行痕迹)——§22「用户在 N 个展示位看到的数据必须统一」
#   的 HTTP 层一致性**零自动校验**,10-02 事故同款(overview 旧版 6 天无人知)若再
#   发生无自动探测。本脚本=云上 trade-r2-consistency.timer 的包装,把审计器接上调度。
#
# 时点选择依据(§14): 23:20 ——
#   当日晚链全部完成(overfit 21:40 / public-fund-full 22:00 / nextday-plan 22:30 /
#   check-data-gap 22:35)后, 两树 static-site/data 与 R2 均为当日终态;
#   位于 23:00 安全窗口内(不推 main 不写 DB);23 点档无其他 trade timer 与 cron
#   (:07/:37 为 hdszf 无关任务,已避开);云上 7x24 常开不涉唤醒。
#
# 为什么是独立 timer 而非 deploy 链闸门(闸门位置/爆炸半径分析见报告 §2):
#   段1 末尾 R2 上传已异步化(r2_upload_async.sh,2026-10-04)——该时刻 R2 可能正在
#   写、CF purge 未生效,此刻比对必假阳;且卡 deploy = 数据已上 R2 而 min 未推的
#   半完成态(§23.11/main-merge-fail)。独立日巡检:采样点在稳定态、零 deploy 爆炸
#   半径,且覆盖「deploy 根本没跑 / R2 被外部覆盖」的持续态(10-02 类正是持续态)。
#
# 判定/出口: check_r2_consistency.py rc!=0(local/R2直链/CF r2-proxy/主站同源 四源
#   指纹不一致,或某源拉取失败)→ notify --severe(去重 6h);rc=0 静默(仅日志)。
#   仅告警不阻断: 本检查不在任何推送链上,不存在"阻断谁"的动作,告警即收敛口。
#   超长任务日志走 systemd journal(unit 不设 StandardOutput append,避 root 属主冲突 ——
#   trade-r2-consistency.sh 自己写同名 *_launchd.log,同 systemd-units §1.4 例外条款)。
#
# 每日跑(不限交易日): 「各源一致」是不变量,任何一天都须成立——周末被外部覆盖
#   同样要抓,故不设交易日闸门。
#
# 用法: bash scripts/check_r2_consistency.sh [force]   # force 保留位(当前无闸门,等价直跑)
# 日志: data/logs/r2_consistency_launchd.log(固定名 append, 标准开始/结束行供
#   gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读, 同 check_data_gap 先例)
set -u

export REPO="${REPO:-/Users/linhuichen/code/trade-data}"
export GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR="$REPO/data/logs"
mkdir -p "$LOGDIR"
cd "$REPO"
LOG="$LOGDIR/r2_consistency_launchd.log"

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

echo "=== check_r2_consistency.sh 开始 $(date '+%F %T') ===" >> "$LOG"

# 相对路径走 trade-data/scripts symlink(merge 即生效,与全站任务同哲学)。
# 超时 900s: 全量四源×(9 产物)HTTP 拉取, 大件(concepts 32.6MB / accum_nav 26MB)
# 在云上秒级, 900s 为宽余(含单源 2 次重试的 12s 超时窗口)。
OUT="$(run_to 900 "$PY" scripts/check_r2_consistency.py --quiet 2>&1)"
RC=$?
printf '%s\n' "$OUT" >> "$LOG"

if [ "$RC" -ne 0 ]; then
  # 摘录问题段(=== N 项问题 === 起)进告警正文; HTML 转义 + 换行折成 |(邮件体单段)
  BODY="$(printf '%s\n' "$OUT" | sed -n '/项问题/,$p' | head -12)"
  [ -z "$BODY" ] && BODY="$(printf '%s\n' "$OUT" | tail -8)"
  BODY_ESC="$(printf '%s' "$BODY" | sed 's/&/\&amp;/g; s/</\&lt;/g' | tr '\n' '|')"
  echo "✗ §22 多源一致性校验失败 rc=${RC},发 severe 告警" >> "$LOG"
  "$PY" scripts/notify.py "[告警] §22 三站一致性校验失败" \
    "check_r2_consistency 检出 local / R2直链 / CF r2-proxy / 主站同源 多源不一致或某源拉取失败(rc=${RC})。<br>${BODY_ESC}<br>脚本: scripts/check_r2_consistency.py &nbsp;日志: ${LOG}" \
    --severe --from-prefix "[告警]" --dedup-key r2_consistency_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
fi

echo "=== check_r2_consistency.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"