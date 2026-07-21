#!/usr/bin/env bash
# update_all.sh - 一键更新（并发流水线版）
#
# 把原串行 collect->deploy->check 拆成 4 条并行 pipeline，各自独立
# 采集->计算->导出->commit+push，慢任务（mootdx 5072 只）不阻塞快核心上线：
#   core        快核心（指数/指标/情绪分），分钟级先上线
#   width       慢宽度（mootdx/行业宽度/全市场宽度），完成后覆盖上线
#   futures     独立（期货机构持仓），独立上线
#   stock_daily 后台死端（全 A 股日线备用源），不 export 不 push，不阻塞
# 各 pipeline 的 commit+push 经 flock /tmp/trade_deploy.lock 串行，避免 git index.lock 冲突。
#
# 非交易日：默认跳过采集仅 deploy+check_signals；传 force 绕闸门强制采集（周末补数据/校准）。
# 旧串行版备份：scripts/update_all_serial.sh。
#
# 用法：bash scripts/update_all.sh [force]
#   force: 绕过交易日闸门，非交易日也跑全量 pipeline（补漏跑数据/校准；当日快照采最近交易日值）
# 日志：data/logs/update_all_YYYYMMDD_HHMM.log（汇总，含各 pipeline 交错输出）
#       data/logs/pipeline_<name>_<STAMP>.log（各流水线独立日志）
# 退出码：core pipeline 退出码（核心看板公网状态）。
set -u

# 防止脚本运行期间 mac 休眠（17:50 launchd 触发时若 mac 在睡眠边缘，跑期间不再睡；
# caffeinate -i 防系统空闲睡眠，-w $$ 跟随本脚本 PID，脚本退出 caffeinate 自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/update_all_${STAMP}.log"

mkdir -p "$LOGDIR"
cd "$REPO"

# 进程互斥：防止多个 update_all 并发跑（撞 mootdx/stock_daily progress 原子写 +
# 通达信/东财并发限流全 empty 空转）。fcntl.flock 非阻塞独占锁，持不到=已有在跑=跳过。
# 自包装：首次调用经 with_lock.py --nb 持锁重跑自己，UPDATE_ALL_LOCKED=1 防递归。
if [ -z "${UPDATE_ALL_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb --on-skip "$REPO/scripts/on_skip_notify.sh" /tmp/trade_update_all.lock \
    env UPDATE_ALL_LOCKED=1 bash "$0" "$@"
fi

# 记开始时间（锁跳过分支不会到这；末尾算耗时发监控通知）
START_TS=$(date +%s)

echo "=== update_all.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# force 模式：绕过交易日闸门（周末补数据/校准；当日快照采最近交易日值，幂等不误盖）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1

# 交易日闸门（统一判断一次，避免各 pipeline 重复判断；闸门内部已 refresh_trade_dates）
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"

if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过采集，仅 deploy 补推 + check_signals（force 可绕过）" | tee -a "$LOG"
  bash "$REPO/scripts/deploy.sh" 2>&1 | tee -a "$LOG"
  bash "$REPO/scripts/check_signals.sh" 2>&1 | tee -a "$LOG"
  echo "=== update_all.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

[ "$FORCE" = "1" ] && [ "$IS_TRADING" != "1" ] && echo "⚠ force 模式：非交易日强制采集（补数据/校准）" | tee -a "$LOG"

# 交易日：并发启动 pipeline
# core/width/futures/turnover 前台并发（wait 等，turnover 慢但需 export+push 上线，等其完成再发通知）；
# stock_daily 后台（死端不 wait，不阻塞）
echo "-> 并发启动 pipeline: core / width / futures / turnover / stock_daily(后台)" | tee -a "$LOG"
bash "$REPO/scripts/pipeline.sh" core        >> "$LOG" 2>&1 &
PID_CORE=$!
bash "$REPO/scripts/pipeline.sh" width       >> "$LOG" 2>&1 &
PID_WIDTH=$!
bash "$REPO/scripts/pipeline.sh" futures     >> "$LOG" 2>&1 &
PID_FUTURES=$!
bash "$REPO/scripts/pipeline.sh" turnover    >> "$LOG" 2>&1 &
PID_TURNOVER=$!
bash "$REPO/scripts/pipeline.sh" stock_daily >> "$LOG" 2>&1 &
PID_STOCK=$!
echo "  PID: core=$PID_CORE width=$PID_WIDTH futures=$PID_FUTURES turnover=$PID_TURNOVER stock_daily=$PID_STOCK(后台不等)" | tee -a "$LOG"

# 等核心四线（stock_daily 后台不等；turnover 慢但需上线，故 wait）
wait "$PID_CORE";     RC_CORE=$?
wait "$PID_WIDTH";    RC_WIDTH=$?
wait "$PID_FUTURES";  RC_FUTURES=$?
wait "$PID_TURNOVER"; RC_TURNOVER=$?
echo "pipeline 退出码: core=$RC_CORE width=$RC_WIDTH futures=$RC_FUTURES turnover=$RC_TURNOVER (stock_daily PID=$PID_STOCK 仍在后台)" | tee -a "$LOG"

# 信号检测 + 邮件（失败不阻塞，保持原逻辑）
echo "-> check_signals.sh ..." | tee -a "$LOG"
bash "$REPO/scripts/check_signals.sh" 2>&1 | tee -a "$LOG"
SIGNAL_RC=${PIPESTATUS[0]}
[ "$SIGNAL_RC" -ne 0 ] && echo "⚠ check_signals 退出码 ${SIGNAL_RC:-?}(邮件失败或配置缺失,不影响公网部署)" | tee -a "$LOG"

# 盘中实时快照：update_all 末尾顺便刷新（写 DB + dump static-site/data/intraday_snapshot.json）
# 盘中跑会采实时行情；收盘后/非交易日也跑（采最近交易日值，label 自动判"收盘快照"）。
# 不额外 git push（static JSON 本地更新，下次 deploy 自动推送；动态版 /api/ 实时读 DB）。
echo "-> intraday_snapshot 采集 ..." | tee -a "$LOG"
"$PY" -m app.collector.intraday_snapshot >> "$LOG" 2>&1 || \
  echo "⚠ intraday_snapshot 采集失败（不阻塞主流程）" | tee -a "$LOG"

# C6 预警条：算当日预警分入库 score_daily + 导出 static-site/data/alert.json
# 读 DB 最新日算分（约5s），失败不阻塞；alert.json 本地更新，下次 pipeline deploy 推上线
echo "-> 预警分计算（high_alert/low_alert）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_alert.py" >> "$LOG" 2>&1 || \
  echo "⚠ export_alert 失败（不阻塞主流程）" | tee -a "$LOG"

# C7 预警分析快照：预生成 40 个 alert_analyze_{宽基/申万行业}.json 供前端静态读
# 跟随 alert 每日重算（C6 预警分析应每日最新），约5s，失败不阻塞；口径同 export_alert
echo "-> 预警分析快照（alert_analyze 40 宽基+行业）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_alert_analyze.py" >> "$LOG" 2>&1 || \
  echo "⚠ export_alert_analyze 失败（不阻塞主流程）" | tee -a "$LOG"

echo "=== update_all.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
echo "core=$RC_CORE width=$RC_WIDTH futures=$RC_FUTURES turnover=$RC_TURNOVER check_signals=$SIGNAL_RC" | tee -a "$LOG"

# 数据时效断言：校验刚 deploy 的 overview.json/intraday_snapshot.json 是否新鲜。
# overview.date 应 == 最近交易日；intraday_snapshot.collected_at 应在 3h 内（本流程刚采集）。
# 不符 -> SEVERE + 并入通知正文（防"采集/部署静默失败致线上数据陈旧"）。
FRESH_RESULT=$("$PY" - 2>>"$LOG" <<'PYEOF'
import json
from datetime import datetime
from app.calendar import last_trading_day
msgs = []
ltd = last_trading_day()
ov_ok = False
try:
    ov = json.load(open('static-site/data/overview.json'))
    ov_date = ov.get('date')
    ov_ok = (ov_date == ltd)
    msgs.append("overview.date=%s%s" % (ov_date, "(OK)" if ov_ok else "(≠最近交易日%s)" % ltd))
except Exception as e:
    msgs.append("overview.json 解析失败:%s" % e)
snap_ok = False
try:
    snap = json.load(open('static-site/data/intraday_snapshot.json'))
    ca = snap.get('collected_at', '')
    # collected_at 多为 ISO '2026-07-17T15:35:06.171800'，取其日期 == 最近交易日
    try:
        ca_date = datetime.fromisoformat(ca).strftime('%Y%m%d')
    except ValueError:
        ca_date = ca.split(' ')[0]  # 兜 'YYYYMMDD HH:MM:SS' 格式
    snap_ok = (ca_date == ltd)
    msgs.append("intraday_snapshot.collected_at=%s%s" % (ca, "(OK)" if snap_ok else "(日期%s≠最近交易日%s)" % (ca_date, ltd)))
except Exception as e:
    msgs.append("intraday_snapshot 解析失败:%s" % e)
print("FRESH_OK=%d" % (1 if (ov_ok and snap_ok) else 0))
print(" | ".join(msgs))
PYEOF
)
FRESH_OK=$(printf '%s\n' "$FRESH_RESULT" | head -1 | sed 's/^FRESH_OK=//')
FRESH_MSG=$(printf '%s\n' "$FRESH_RESULT" | tail -n +2 | head -1)

# 监控通知：耗时 + 退出码 + 失败 pipeline 明细 + 数据时效 + 日志路径（发邮件 + 严重时写 alerts）
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
ELAPSED_MIN=$((ELAPSED / 60))
SEVERE=0
[ "$ELAPSED" -gt 3600 ] && SEVERE=1
[ "$RC_CORE" -ne 0 ] && SEVERE=1
[ "$FRESH_OK" != "1" ] && SEVERE=1
NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')

# 失败 pipeline 明细（退出码非 0）：名 + rc + 最近一份 pipeline 日志名，并入通知正文
FAILED_DETAILS=""
for _name in core width futures turnover; do
  _rcvar="RC_$(printf '%s' "$_name" | tr '[:lower:]' '[:upper:]')"
  _rc="${!_rcvar:-0}"
  if [ "$_rc" != "0" ]; then
    _plog=$(ls -t "$LOGDIR"/pipeline_${_name}_*.log 2>/dev/null | head -1)
    FAILED_DETAILS="${FAILED_DETAILS}<br>  ✗ ${_name} 失败(rc=${_rc}) 日志:$(basename "${_plog:-无}")"
  fi
done
[ -n "$FAILED_DETAILS" ] && FAILED_DETAILS="<br>失败明细:${FAILED_DETAILS}"

NOTIFY_BODY="update_all 完成<br>耗时：${ELAPSED_MIN} 分钟（${ELAPSED}秒）<br>退出码：core=$RC_CORE width=$RC_WIDTH futures=$RC_FUTURES turnover=$RC_TURNOVER check_signals=$SIGNAL_RC${FAILED_DETAILS}<br>数据时效：$FRESH_MSG<br>日志：$LOG<br>结束时间：$NOW_STR"
if [ "$SEVERE" -eq 1 ]; then
  ISSUE="update_all 严重告警："
  [ "$ELAPSED" -gt 3600 ] && ISSUE="${ISSUE}耗时超1h(${ELAPSED_MIN}分钟) "
  [ "$RC_CORE" -ne 0 ] && ISSUE="${ISSUE}core退出码非0($RC_CORE) "
  [ "$FRESH_OK" != "1" ] && ISSUE="${ISSUE}数据时效异常($FRESH_MSG)"
  "$PY" "$REPO/scripts/notify.py" "[严重]update_all告警" "$NOTIFY_BODY" --severe --alert-issue "$ISSUE" --alert-log "$LOG" || true
else
  "$PY" "$REPO/scripts/notify.py" "[完成]update_all" "$NOTIFY_BODY" || true
fi

# D10 每日收盘情绪速递邮件（summary_history.json 已由 pipeline deploy 生成就绪）。
# 失败不阻塞主流程：调 notify.py 告警，退出码仍以 RC_CORE 为准。
# 非交易日已在上方 exit 0 不会走到这；脚本内部对无数据日期也优雅跳过。
echo "-> daily_summary_email 收盘速递邮件 ..." | tee -a "$LOG"
if "$PY" "$REPO/scripts/daily_summary_email.py" >> "$LOG" 2>&1; then
  echo "  ✓ 收盘速递邮件已处理" | tee -a "$LOG"
else
  _DSE_RC=$?
  echo "⚠ daily_summary_email 失败(不阻塞主流程) rc=$_DSE_RC" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警]收盘速递邮件失败" \
    "daily_summary_email 退出码 $_DSE_RC<br>日志: $LOG" || true
fi

# 每日 DB 热备 + R2 异地备份（update_all 跑完后 DB 已是最新，此时备份最稳）。
# 失败不影响 update_all 退出码（RC_CORE 保持看板状态）。
bash "$REPO/scripts/backup_db.sh" || echo "⚠ backup_db 失败(不影响update_all) rc=$?"

# 退出码以 core 为准（核心看板公网状态）
exit "$RC_CORE"
