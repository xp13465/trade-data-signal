#!/bin/bash
# intraday_snapshot.sh - 盘中实时快照采集（launchd 定时，盘中每 10 分钟）
#
# 跑 .venv/bin/python -m app.collector.intraday_snapshot（秒级）：
#   采腾讯9指数实时 + 同花顺行业实时涨跌幅，存 DB + dump static-site/data/intraday_snapshot.json
# 然后 upload_r2 同步该 JSON 到 R2（阶段3：替代 git push），供前端"盘中实时小结"展示。
#   采集在主仓库跑（DB 持久化），upload_r2 直接读 REPO 上传 R2（无需 worktree/git push）。
#
# 进程互斥：
#   - 快照锁 /tmp/trade_intraday_snapshot.lock（--nb 非阻塞）：防快照自身重复，秒级。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git add/commit/push，避免和
#     update_all pipeline 撞 .git/index.lock。阻塞等待 update_all 释放后执行。
#
# 非交易日：默认跳过（不浪费 git commit）。force 模式可绕过（手动补测）。
# 旧串行 update_all.sh 末尾也顺带跑快照但不 push；本脚本独立 push。
#
# 用法：bash scripts/intraday_snapshot.sh [force]
#   force: 绕过交易日闸门，非交易日也跑（补测/校准）
# 日志：data/logs/intraday_snapshot_YYYYMMDD_HHMM.log
# 退出码：快照采集退出码（R2 上传失败也计入）。
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 始终在 trade 仓库(trade-data 不 git init)
export REPO   # 让子 bash -c (commit+push 段) 继承 REPO，trade-data 跑时采集路径用 trade-data
export GIT_REPO   # 让子 bash -c 继承 GIT_REPO，git worktree 操作在 trade 仓库
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/intraday_snapshot_${STAMP}.log"
export LOG   # 2026-07-20: 让子 bash -c (upload_r2 告警段挪进 commit+push 块) 继承 LOG，tee -a 可用

mkdir -p "$LOGDIR"
cd "$REPO"

# 2026-08-28 P0 根治：持锁 watchdog 预检，避免僵死进程永久卡锁致后续 launchd 全部跳过。
# 锁文件存在但持锁进程已死 -> 自动 unlink + 发 SEVERE notify（让用户知道发生过死锁）
# 锁文件存在且持锁进程仍活 -> 保留 with_lock.py --nb 跳过语义（不抢锁）
# 锁文件不存在 -> 透传。
# watchdog 退出码 0=可继续(锁已清理/不存在) 1=锁被活进程持有(应跳过)
if [ -z "${INTRADAY_LOCKED:-}" ]; then
  LOCK_RC=0
  "$PY" "$REPO/scripts/lock_watchdog.py" /tmp/trade_intraday_snapshot.lock || LOCK_RC=$?
  if [ "$LOCK_RC" -ne 0 ]; then
    echo "[lock_watchdog] 锁真实被活进程持有，本次跳过" | tee -a "$LOG" || true
    exit 0
  fi
  exec "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_intraday_snapshot.lock \
    env INTRADAY_LOCKED=1 bash "$0" "$@"
fi

echo "=== intraday_snapshot.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"

if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过快照采集（force 可绕过）" | tee -a "$LOG"
  echo "=== intraday_snapshot.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

[ "$FORCE" = "1" ] && [ "$IS_TRADING" != "1" ] && echo "⚠ force 模式：非交易日强制采集快照（补测）" | tee -a "$LOG"

# 1) 采集快照（存 DB + dump static-site/data/intraday_snapshot.json）
echo "-> 采集盘中快照 ..." | tee -a "$LOG"
"$PY" -m app.collector.intraday_snapshot 2>&1 | tee -a "$LOG"
SNAP_RC=${PIPESTATUS[0]}
if [ "$SNAP_RC" -ne 0 ]; then
  echo "✗ 快照采集失败（退出码 ${SNAP_RC}），写 stderr 告警" | tee -a "$LOG" >&2
  exit "$SNAP_RC"
fi

# 1.5) ETF 汪汪队盘中预估（AZ54 P1-5, 2026-07-29）：
#      9:35-14:50 跑 intraday-realtime（akshare fund_etf_fund_daily_em 实时市价预估,~1s）
#      15:00+   跑 intraday-close（sina/mootdx 真实收盘价覆盖预估）
#      末日 share_change=NULL -> 前端 lastChgMissing=true 预估触发（复用现有逻辑无需改前端）。
#      原问题：pipeline_intraday_close 只在 15:00 后跑，9:35-14:50 的 17 个盘中时点无 ETF 预估。
#      修复：盘中用 akshare 实时市价写 DB 末日 close（share_change=NULL），15:00+ 收盘价覆盖。
#      失败不阻塞：快照已采+将 push,ETF 预估触发延迟到下一轮或 20:07 backfill 兜底。
HOUR_MIN=$(date +%H%M)
if [ "$HOUR_MIN" -ge "1500" ]; then
  echo "-> 采 ETF 汪汪队当日 close(末日 share_change=NULL 触发预估,15:00 后跑)..." | tee -a "$LOG"
  "$PY" -m app.collector.etf_national_team intraday-close 2>&1 | tee -a "$LOG"
  ETF_RC=${PIPESTATUS[0]}
  [ "$ETF_RC" -ne 0 ] && echo "⚠ ETF intraday-close 失败(退出码 $ETF_RC),不阻塞快照" | tee -a "$LOG"
elif [ "$HOUR_MIN" -ge "0935" ]; then
  echo "-> 采 ETF 汪汪队盘中实时市价预估(akshare,9:35-14:50 跑)..." | tee -a "$LOG"
  "$PY" -m app.collector.etf_national_team intraday-realtime 2>&1 | tee -a "$LOG"
  ETF_RC=${PIPESTATUS[0]}
  [ "$ETF_RC" -ne 0 ] && echo "⚠ ETF intraday-realtime 失败(退出码 $ETF_RC),不阻塞快照" | tee -a "$LOG"
else
  echo "-> 跳过 ETF 预估(盘前 $HOUR_MIN<0935,等 9:35 首触)" | tee -a "$LOG"
fi

# 1.8) 盘中信号邮件 + 导出 notifications.json（B2 优化 2026-07-20：移到 push 块前）
#      原顺序：push 块 -> check_signals -> export_notifications，当轮生成的 notifications.json
#      不进当轮 commit/push，下一轮 rsync 才带进 worktree push -> 滞后 1 轮 10min。
#      修复：check_signals + export_notifications 移到 push 块前，当轮生成 + 当轮 push 无滞后。
#      时序依赖：export_notifications 读 check_signals 写的 signal_notified.json（去重）+
#      signal_daily（intraday_snapshot 采集时已 _recompute_signals 重算），故顺序固定：
#      采集 -> ETF预估 -> check_signals -> export_notifications -> commit+push。
#      intraday_snapshot 已在 collect_and_save 中重算 signal_daily，check_signals 查当日信号
#      发邮件，复用 signal_notified.json 去重（同日同 index_id+signal 只发一次），盘中多次跑
#      （9:35/10:05/...）只发新出现的信号。邮件标题加【盘中实时】+ 正文风险横幅（盘中快照非
#      最终，收盘 17:50 update_all 仍发最终版）。失败不阻塞：快照数据将 push，邮件/notifications
#      失败仅 log 告警。REPO=trade-data 时 check_signals.sh 用 trade-data/scripts/check_signals.py，
#      NOTIFIED_PATH=trade-data/data/signal_notified.json（与 update_all 同路径，去重一致）。
echo "-> check_signals.sh --intraday（盘中信号邮件）..." | tee -a "$LOG"
bash "$REPO/scripts/check_signals.sh" --intraday 2>&1 | tee -a "$LOG"
SIGNAL_RC=${PIPESTATUS[0]}
[ "$SIGNAL_RC" -ne 0 ] && echo "⚠ check_signals 退出码 ${SIGNAL_RC:-?}(邮件失败或配置缺失,不阻塞快照)" | tee -a "$LOG"

# 导出 notifications.json（浏览器通知源，P2-新-W 方案A 根因①修复）
#      check_signals 写完 signal_notified.json 后导出，读 DB 当日信号/预警/恐贪/异动。
#      生成 static-site/data/notifications.json，当轮 rsync 进 worktree push（B2 修复：无滞后）。
#      失败不阻塞：快照数据将 push，notifications.json 滞后下一轮补。
#      cwd=$REPO（trade-data 跑时 ROOT=trade-data 读主库，§9）；与 export_alert 同调用方式。
echo "-> export_notifications.py（浏览器通知源 JSON）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_notifications.py" 2>&1 | tee -a "$LOG" || \
  echo "⚠ export_notifications 失败(不阻塞快照)" | tee -a "$LOG"

# 2) 同步受影响的静态数据 JSON 到 R2（阶段3：去 git push，前端走 R2）
#    原机制：worktree + rsync + git add/commit/push origin HEAD:main（持 deploy 锁串行）。
#    阶段3：改只 R2 上传（upload-index + upload-intraday + purge_cache），前端 Worker /data/->R2 rewrite。
#    static-site/data/ 仍 tracked，R2 故障时可手动 git push 兜底。
#    采集器写 REPO/static-site/data/（trade-data），upload_r2.py 读 REPO（env）直接上传，无需 rsync。
# ALERT_TIME 在告警中引用，外层预算避免 bash -c 引号转义问题。
ALERT_TIME=$(date '+%m-%d %H:%M')
echo "-> 同步 intraday 数据 JSON 到 R2（阶段3：去 git push，前端走 R2）..." | tee -a "${LOG}"

# 2.5) 同步 index/ 到 R2（走势图源 kc50-all.json 等）
#      非阻塞：R2 失败发告警邮件（notify.py --severe），不阻断后续 upload-intraday。
echo "-> 同步 index 到 R2（前端 R2 源）..." | tee -a "$LOG"
if ! "$PY" "$REPO/scripts/upload_r2.py" upload-index 2>&1 | tee -a "$LOG"; then
  echo "✗ upload-index R2 失败，发告警邮件" | tee -a "$LOG"
  FAILED_FILES=$(grep "^FAILED_FILES:" "$LOG" | tail -1 | sed "s/^FAILED_FILES: //") || true
  OK_TOTAL=$(grep "^共上传" "$LOG" | tail -1) || true
  "$PY" "$REPO/scripts/notify.py" "[告警] intraday R2上传失败 ${ALERT_TIME}" "走势图数据源(kc50-all.json等)未推 R2，需手动补刷 R2: bash scripts/upload_r2.py upload-index<br>汇总: ${OK_TOTAL}<br>失败文件: ${FAILED_FILES}" --severe --from-prefix "[告警]" --dedup-key intraday_upload_index_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
fi

# 2.52) 同步 intraday 相关数据到 R2（阶段3：唯一上线渠道，替代 git push）
#       upload-index 已处理 index/，此处上传 intraday 实际更新的小 .json：
#       intraday_snapshot/overview/summary/summary_history/notifications/boot/schedule_stats
#       + a-stock/hk/global/sentiment-3m/6m/1y + etf_national_team-1m/3m/6m/1y。
#       R2 上传失败发告警邮件（notify.py --severe），让 schedule_monitor 发现。
echo "-> 同步 intraday 数据到 R2（upload-intraday）..." | tee -a "$LOG"
if ! "$PY" "$REPO/scripts/upload_r2.py" upload-intraday 2>&1 | tee -a "$LOG"; then
  echo "✗ upload-intraday R2 失败，发告警邮件" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] intraday R2上传失败 ${ALERT_TIME}" "intraday 数据(overview/intraday_snapshot/a-stock等)未推 R2，前端将读旧数据，需手动补刷: bash scripts/upload_r2.py upload-intraday<br>日志: $LOG" --severe --from-prefix "[告警]" --dedup-key intraday_upload_intraday_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
fi

# 2.53) 同步 intraday 盘中数据到 staticdata 数据仓库（灾备第2层差异日志/留档）
#       R2 迁移阶段3 后本脚本只 upload_r2 不再 git push，漏了 staticdata 同步
#       -> staticdata 仓库 intraday_snapshot.json 停在昨日 20:35，盘中每 10 分钟
#       新数据 5 小时空窗不落档（违反 §8.1 checklist「写 static-site/data 的生成器
#       必须同时接 ①R2 上传 ②staticdata 同步」）。用户已确认盘中每 10 分钟同步。
#       文件列表与 upload-intraday 清单一致（intraday 盘中实际更新的小 json），
#       非 --all 全量（避免拖慢高频任务+引入无关文件）。staticdata_sync.sh 内部
#       持 /tmp/trade_deploy.lock + best-effort 失败不阻塞，无需额外 try/catch。
#       放 R2 上传成功后（R2 失败也不重复告警）。
#       2026-08-18 修复:STATICDATA_SYNC_NONBLOCK=1 让本调用走 with_lock.py --nb 非阻塞锁。
#       背景:20:35 盘后轮 staticdata 同步曾被 20:07 etf 全量 deploy(持锁 21min)+20:05
#       futures deploy 背靠背占锁卡死 → intraday_snapshot 701s 超 600s 告警。改 skip-if-busy:
#       锁被 deploy 占用则跳过本次同步（灾备缺口由 etf deploy 的 staticdata 全量 rsync 兜底,
#       20:46 那轮 etf deploy 已把 intraday 文件一起 rsync 掉,故跳过显示"无新变更"正常）,
#       不阻塞快照流程。改后 20:35 轮应回到 ~440s。其余调用方(gen_daily_brief/fetch_news)
#       不置此 env,仍走阻塞版,不受影响。
echo "-> 同步 intraday 数据到 staticdata 仓库（灾备留档）..." | tee -a "$LOG"
STATICDATA_SYNC_NONBLOCK=1 bash "$GIT_REPO/scripts/staticdata_sync.sh" intraday \
  intraday_snapshot.json overview.json summary.json summary_history.json \
  notifications.json boot.json schedule_stats.json \
  a-stock-3m.json a-stock-6m.json a-stock-1y.json \
  hk-3m.json hk-6m.json hk-1y.json \
  global-3m.json global-6m.json global-1y.json \
  sentiment-3m.json sentiment-6m.json sentiment-1y.json \
  etf_national_team-1m.json etf_national_team-3m.json \
  etf_national_team-6m.json etf_national_team-1y.json 2>&1 | tee -a "$LOG" || \
  echo "⚠ staticdata 同步失败(不阻塞快照)" | tee -a "$LOG"

# 2.55) A11 异常波动盘中告警（R2同步后；失败不阻塞快照）
#       借鉴 alert_score.py L5 量能异动模式，检测急涨急跌(±3/5/7%)/放量(5日均×2)/突破(20日高低点)。
#       同日同标的去重(data/anomaly_notified.json)，通过 notify.py 发盘中提示邮件。
if ! "$PY" "$REPO/scripts/detect_intraday_anomaly.py" 2>&1 | tee -a "$LOG"; then
  echo "⚠ detect_intraday_anomaly 失败，不阻塞快照" | tee -a "$LOG"
fi

echo "=== intraday_snapshot.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"

# 4) 刷新 schedule_stats.json（在"结束"行写入后调用，确保 gen_stats 看到当前运行配对）
#    原 L124 在 push 前调用太早：当前"结束"行未写，被杀旧 pending_start 冒充 last_run。
#    移到此处：gen_stats 读到当前结束行，正确配对；被杀旧 start 由 next_start 检测判为孤儿。
#    写 REPO static-site/data/schedule_stats.json，下一轮 intraday rsync 进 worktree push（一轮延迟可接受）。
#    deploy.sh L72 收盘后也调，兜底。失败不阻塞退出。
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" | tail -1 || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"

# 5) schedule_stats.json 上传 R2（阶段3：替代 git push，gen_stats 后立即上传无滞后）
#    gen_stats 刷新本地 schedule_stats.json 后，upload-data-files 上传到 R2 + purge_cache。
#    失败不阻塞：下一轮 intraday 或其他任务脚本结尾会再上传。R2 失败发告警邮件与其他脚本一致。
"$PY" "$REPO/scripts/upload_r2.py" upload-data-files schedule_stats.json 2>&1 | tee -a "$LOG" || {
  echo "⚠ schedule_stats R2 上传失败，不阻塞" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] intraday schedule_stats R2上传失败 ${ALERT_TIME}" "schedule_stats R2 上传失败，前端"执行统计"将读旧数据，下一轮 intraday 自动重试。需手动补刷: bash scripts/upload_r2.py upload-data-files schedule_stats.json<br>日志: $LOG" --severe --from-prefix "[告警]" --dedup-key intraday_schedule_stats_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
}

exit 0
