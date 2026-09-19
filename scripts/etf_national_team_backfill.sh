#!/bin/bash
# etf_national_team_backfill.sh - ETF汪汪队当日单采+推送（launchd 20:07 定时）
#
# 问题：etf_national_team.py daily 只调 export_json_files() 写本地 static-site/data/*.json，
#   不 git push -> 最坏 ETF 数据等次日 17:50 update_all 才上线（和 cross_market 数据没上线同类隐患）。
#   本脚本补 deploy.sh 推送，当日采集当日上线。
#
# 只做：python -m app.collector.etf_national_team daily（mootdx OHLC + SSE/SZSE 份额 + 重算信号
#   + 导出 JSON）-> 持 deploy 锁推送（deploy.sh 重新 export 全量 JSON + git push）。
#   等价于 etf_national_team.py daily + deploy.sh，加自身互斥 + 交易日闸门 + caffeinate。
#
# 进程互斥：
#   - etf 锁 /tmp/trade_etf_nt.lock（--nb 非阻塞）：防自身重复并发（python 内 data/etf_national_team.lock
#     也持锁，双层保护：shell 直接调用 / python 直接调用都防并发）。
#   - deploy 锁 /tmp/trade_deploy.lock（阻塞）：串行化 git，与 20:00 backfill / intraday_snapshot /
#     update_all pipeline 共享，避免撞 .git/index.lock。
#
# 非交易日：默认跳过。force 模式可绕过（手动补测）。
#
# 用法：bash scripts/etf_national_team_backfill.sh [force]
# 日志：data/logs/etf_national_team_backfill_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠（caffeinate 跟随脚本 PID，退出自动结束）
if [ "$(uname -s)" = "Darwin" ]; then
    caffeinate -i -w $$ >/dev/null 2>&1 &
fi

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 始终在 trade 仓库(trade-data 不 git init)
export REPO GIT_REPO   # 确保 upload_r2.py 子进程继承 REPO(防缺省回退读 trade 旧库, 同 deploy.sh)
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/etf_national_team_backfill_${STAMP}.log"
LOCK="/tmp/trade_etf_nt.lock"

mkdir -p "$LOGDIR"
cd "$REPO"

# 自包装：首次调用经 with_lock.py --nb 持 etf 锁重跑自己，ETF_NT_LOCKED=1 防递归。
# 锁被占（上一轮还在跑）= stderr 提示 + exit 0 跳过。
if [ -z "${ETF_NT_LOCKED:-}" ]; then
  exec "$PY" "$REPO/scripts/with_lock.py" --nb "$LOCK" \
    env ETF_NT_LOCKED=1 bash "$0" "$@"
fi

echo "=== etf_national_team_backfill.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 交易日闸门（与 update_all.sh / intraday_snapshot.sh / 其他 backfill 同口径）
FORCE=0
[ "${1:-}" = "force" ] && FORCE=1
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown} FORCE=$FORCE" | tee -a "$LOG"
if [ "$IS_TRADING" != "1" ] && [ "$FORCE" != "1" ]; then
  echo "非交易日，跳过ETF汪汪队采集（force 可绕过）" | tee -a "$LOG"
  echo "=== etf_national_team_backfill.sh 结束（非交易日）$(date '+%Y-%m-%d %H:%M:%S') ===" | tee -a "$LOG"
  exit 0
fi

# 1) 采集 ETF 汪汪队当日（mootdx OHLC + SSE/SZSE 份额 + 重算信号）+ 导出 JSON
#    python 内置 data/etf_national_team.lock 防并发；采集器写 DB + dump static-site/data/*.json。
echo "-> 采集 ETF 汪汪队当日 + 导出 JSON ..." | tee -a "$LOG"
"$PY" -m app.collector.etf_national_team daily 2>&1 | tee -a "$LOG"
COLLECT_RC=${PIPESTATUS[0]}
echo "ETF汪汪队采集退出码=$COLLECT_RC" | tee -a "$LOG"
# 2026-07-25: collector crash 时(如 libmini_racer FATAL)不会写 [etf_nt] daily 完成 行,
# gen_schedule_stats 的 etf_nt 模式找不到 DONE -> 启发式标 exit=143(假 SIGTERM),
# 与 shell 脚本正常结束矛盾。补 fallback DONE 行让 gen_stats 解析真实 exit code:
if [ "$COLLECT_RC" -ne 0 ]; then
  echo "[etf_nt] daily 失败 exit=$COLLECT_RC" | tee -a "$LOG"
fi

# 1.5) 采集完第一时间发汪汪队信号通知（20:07采集通常到T-1，check_nt_signals 标题注明数据日期）
#      放 deploy 前：deploy 持锁 git push 较慢，通知不依赖上线数据、只读 DB，先发最快。
#      失败不阻塞（脚本内 try/except，exit 非 0 但不崩）。
if [ "$COLLECT_RC" -eq 0 ]; then
  echo "-> 检测汪汪队信号 + 发邮件通知 ..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/check_nt_signals.py" 2>&1 | tee -a "$LOG"
  NT_NOTIFY_RC=${PIPESTATUS[0]}
  echo "汪汪队通知退出码=$NT_NOTIFY_RC" | tee -a "$LOG"
fi

# 1.6) accum_nav 累计净值(已复权)增量补齐（2026-08-13 根因修复：
#      accum_nav 自 2026-08-08 一次性回填至 20260807 后断更 -> etf_since_return 至今盈亏
#      8/10-12 全 NULL -> check_data_integrity etf_since_return FAIL 卡部署。
#      pipeline 增量扫描近 30 天 accum_nav IS NULL 行逐只补齐，单只失败降级跳过留待下次。
#      必须放 deploy.sh 之前：overview.json 的 etf_since_return 由 export.py 从 DB 生成，
#      先补齐 DB 再 export 才过得了 check_data_integrity 阈值。
#      20:07 主槽 ~25min + 21:30 兜底槽幂等重跑，当日净值当日补齐当日上线。 -->
echo "-> 补齐 ETF 累计净值 accum_nav ..." | tee -a "$LOG"
"$PY" -m app.collector.etf_national_team accum-nav --lookback 30 2>&1 | tee -a "$LOG"
ACCUM_RC=${PIPESTATUS[0]}
echo "accum_nav 补齐退出码=$ACCUM_RC" | tee -a "$LOG"

# 1.7) ETF 全史日K导出（export_etf_hist, 弹窗长历史数据源）——从 17:50 update_all 主链挪到本 20:07
#      采集链（#38 根因修复）: etf_daily 的 T 日 OHLC 要 20:07 daily 采集 + accum-nav 补完后才全，
#      17:50 跑太早会缺 T 日 → 弹窗走势 JSON 停旧日。放 accum-nav 之后（前复权因子 accum_nav 也需最新），
#      deploy.sh 之前（后续 deploy 的 upload-etf-hist 会把刚生成的 etf/{code}-all.json 传 R2）。
#      硬闸门（2026-08-25 同款）：导出失败绝不继续 rsync+upload，防把截断/过期全史日K发布到 R2。
#      前置闸门（2026-09-16 #38 P2）：daily 采集失败（COLLECT_RC != 0）时 etf_daily 停在 T-1 或 partial，
#      直接跳过整个 export_etf_hist 块，防把旧/混合日K发布到 R2。
if [ "$COLLECT_RC" -eq 0 ]; then
  echo "-> ETF全史日K（export_etf_hist, 弹窗长历史数据源, 20:07 补完 etf_daily 后导出）..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/export_etf_hist.py" 2>&1 | tee -a "$LOG"
  ETF_HIST_RC=${PIPESTATUS[0]}
  echo "export_etf_hist 退出码=$ETF_HIST_RC" | tee -a "$LOG"
  if [ "$ETF_HIST_RC" -ne 0 ]; then
    echo "【CRITICAL】export_etf_hist 失败(退出码 $ETF_HIST_RC), 硬闸门跳过 etf rsync+upload-etf-hist, 防发布截断/过期日K(§22 一致性)" | tee -a "$LOG"
  else
    [ "$REPO" = "$GIT_REPO" ] || rsync -a --delete --checksum "$REPO/static-site/data/etf/" "$GIT_REPO/static-site/data/etf/" 2>>"$LOG" || \
      echo "⚠ etf rsync 同步失败, 可能发布不全" | tee -a "$LOG"
    "$PY" "$REPO/scripts/upload_r2.py" upload-etf-hist 2>&1 | tee -a "$LOG" || \
      echo "⚠ upload-etf-hist R2上传失败（不阻塞主流程）" | tee -a "$LOG"
  fi
else
  echo "[etf_nt] daily 采集失败 exit=${COLLECT_RC}，跳过 export_etf_hist 防发布旧/混合日K" | tee -a "$LOG"
fi

# 2) 持 deploy 锁推送（串行化 git，阻塞排队；deploy.sh 重新 export 全量 JSON + git push）
#    deploy.sh 幂等：export 生成相同 JSON -> git add 无新变更 -> 跳过 commit -> push up-to-date。
#    无新数据时也安全（仅多跑一次 export.py）。
echo "-> 持 deploy 锁推送（串行化 git，可能排队等 backfill/intraday）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" --block-timeout 3600 /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" etf-national-team 2>&1 | tee -a "$LOG"
DEPLOY_RC=${PIPESTATUS[0]}
[ "$DEPLOY_RC" -ne 0 ] && echo "✗ deploy 失败 (rc=$DEPLOY_RC)" | tee -a "$LOG"

# 2026-07-25 彻底修复 etf_national_team 143 假告警:
# 综合退出码(collector 或 deploy 任一失败即非0) + 最终 DONE 行带真实 exit + duration。
# gen_schedule_stats parse_etf_nt 取最后一个 DONE 行(覆盖 collector 完成行),
# 此处最终 DONE 行让 gen_stats 记录真实 backfill.sh 综合退出码,而非 collector 的 exit=0。
# 覆盖 6824a43c 只覆盖 collector 失败的缺陷: collector 成功+deploy 失败也能正确记录 exit=1。
FINAL_RC=0
[ "$COLLECT_RC" -ne 0 ] && FINAL_RC=$COLLECT_RC
[ "$ACCUM_RC" -ne 0 ] && FINAL_RC=$ACCUM_RC
[ "${ETF_HIST_RC:-0}" -ne 0 ] && FINAL_RC=$ETF_HIST_RC
[ "$DEPLOY_RC" -ne 0 ] && FINAL_RC=$DEPLOY_RC
if [ "$FINAL_RC" -ne 0 ]; then
  # 抓 collector 的 duration(若有完成行),失败也带 duration 便于前端展示
  DUR=$(grep -oE '\[etf_nt\] daily 完成 [0-9]+\.?[0-9]*s' "$LOG" | tail -1 | sed -E 's/.*完成 ([0-9.]+)s.*/\1/')
  if [ -n "$DUR" ]; then
    echo "[etf_nt] daily 完成 ${DUR}s exit=$FINAL_RC" | tee -a "$LOG"
  else
    echo "[etf_nt] daily 失败 exit=$FINAL_RC" | tee -a "$LOG"
  fi
fi

echo "=== etf_national_team_backfill.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') deploy=$DEPLOY_RC ===" | tee -a "$LOG"

# 刷新 schedule_stats.json（2026-07-24 方案A根治：从 deploy.sh:72 移到此处，在"结束"行后调用，
# gen_stats 能读到完整"开始+结束"对，正确配对当前任务 exit/dur，不再 pending null）
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"

# 独立 push schedule_stats.json 到 main（2026-07-30 方案C+R2：gen_stats 后立即 push 绕过 deploy.sh 时序）
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

exit "$FINAL_RC"
