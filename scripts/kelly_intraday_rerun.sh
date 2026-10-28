#!/bin/bash
# kelly_intraday_rerun.sh - 信号凯利盘中增量回测档(launchd 交易日 9:40)
#
# 背景: 交易记录 signal_kelly_trades.json 由全量回测一天一次(17:50 export)生成, 定价=信号次日开盘价;
# 9/7 信号的交易要等 9/8 17:50 才入账。用户已拍板方向 A(报告 §6, docs/kelly/analysis/
# intraday-backtest-rerun-design-20260908.md): 交易日 9:40 开盘后补跑一轮, 用 9/8 真实开盘价
# 提前入账上一交易日信号, 前端独立盘中视图展示。
#
# 核心铁律(报告 §3 方案 A): 盘中补跑只做加法(新增 T 日交易), 绝不覆盖(重算历史)。
# signal_kelly_backtest.py --intraday-rerun <T>(实现细节见脚本内注释):
#   - 只处理 date==T 的 BUY_SIGNALS(隔离 T+1 盘中临时信号);
#   - 价格时间线截断到 <= T(结构性排除 T+1 占位行 accum_nav=1.5/open=1.49/close=NULL);
#   - T+1 真实开盘价 akshare fund_etf_spot_em 注入(数据就绪闸: 取不到真价 -> 脚本退出码 5, 本轮跳过等 17:50);
#   - 产物独立 signal_kelly_trades_intraday.json / signal_kelly_backtest_intraday.json, 不覆盖主档,
#     intraday 元信息 main_pre_date_hash 供 --intraday-verify 对账机检(主档历史漂移 -> FAIL 退出码 3 不发布)。
#
# 排班/竞态(报告 §2/§3):
#   - 交易日 9:40 起跑; 单档限时 3min(perl alarm, macOS 无 timeout 命令), 9:43 前完避开 9:45 intraday-snapshot;
#   - deploy 锁 /tmp/trade_deploy.lock 用 with_lock.py --nb 非阻塞: 锁在位则跳过本轮(留给 17:50 全量);
#   - 非交易日跳过(is_trading_day 闸门);
#   - 失败告警分级(2026-10-12 降噪 + #254 放宽方案 A 2026-10-12 同日上线):
#     数据就绪闸判定统一交 scripts/kelly_intraday_gate_decider.py(读 data/kelly_intraday_gate_report.json):
#       · abort(单日未豁免取不到比例 > R=15%)= exit 5, 刻意正常跳过(17:50 全量兜底)
#         -> WARN(--tier warning, 入 notify 30min 聚合缓冲, 不再即时 SEVERE, 降噪不变);
#       · tolerate(出档, 带根级 intraday.unpriced_codes)= exit 0; 若命中「取不到类」豁免 -> 降级 WARN(7d 去重);
#         零成交类豁免/正常 pass -> 完全静默(仅 ledger/info 留痕);
#         P2b 绝对量闸(2026-10-12 用户拍板「方案 A」): target>=3 且当日目标 100% 零成交 -> 不再静默, WARN
#           (dedup-key kelly_intraday_gate_allzero_volume, 6h 同日窗口; verdict 仍 tolerate, 仍 exit 0);
#           同面豁免命中 -> 降级静默; n<3 的全零成交(如 09-23 n=1 日)保持完全静默(刻意);
#     对账 FAIL(3)/超时(142)/脚本错误 -> SEVERE 直达不变。
#     decider 自身异常 → 回退保险(§23.11 不静默): abort 分支沿用旧内联 WARN 并保持 exit 5;
#       tolerate/pass 分支补 WARN(kelly_intraday_gate_decider_crash) 后照常发布, 不让判定链静默丢失。
#
# 产物链路: static-site/data/signal_kelly_trades_intraday.json + signal_kelly_backtest_intraday.json
# -> upload_r2 upload-data-files 上传 data/ 前缀 + purge(对账 PASS 后)。
# 日志: data/logs/kelly_intraday_rerun_YYYYMMDD_HHMM.log
set -uo pipefail
# 防脚本运行期间 mac 休眠(caffeinate 跟随脚本 PID, 退出自动结束)
if [ "$(uname -s)" = "Darwin" ]; then
    caffeinate -i -w $$ >/dev/null 2>&1 &
fi

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
export REPO GIT_REPO
PY="$REPO/.venv/bin/python"
LOGDIR="$REPO/data/logs"
STAMP=$(date +%Y%m%d_%H%M)
LOG="$LOGDIR/kelly_intraday_rerun_${STAMP}.log"
export LOG
mkdir -p "$LOGDIR"
cd "$REPO"

echo "=== kelly_intraday_rerun.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"

# 持锁重入守卫(与 intraday_snapshot.sh 同模式): 首次调用经 with_lock.py --nb 持 deploy 锁
# 重跑自己, KIR_LOCKED=1 防递归。--nb 语义: 锁被活进程占用 -> 不等待, 跳过命令本身 + exit 0。
# 注意: 用 with_lock(flock)判断"活进程持锁"而非 [ -e ] 文件存在判断——flock 随进程退出自动释放,
# 死锁残留文件不拦(否则 deploy 崩溃残留的旧锁文件会让本轮误跳过, 留给 17:50 才补)。
if [ -z "${KIR_LOCKED:-}" ]; then
  "$PY" "$REPO/scripts/with_lock.py" --nb /tmp/trade_deploy.lock \
    env KIR_LOCKED=1 bash "$0" "$@" 2>&1 | tee -a "$LOG"
  KIR_RC=${PIPESTATUS[0]}
  if [ "$KIR_RC" -eq 0 ]; then
    # with_lock --nb 被活进程持锁跳过时不执行命令, 仅 stderr 提示已随上面 tee 进日志
    grep -q "锁.*已\|skip\|被占\|locked" "$LOG" || true
  fi
  echo "=== kelly_intraday_rerun.sh 结束(锁重入段) $(date '+%Y-%m-%d %H:%M:%S') 退出码=$KIR_RC ===" | tee -a "$LOG"
  exit "$KIR_RC"
fi

# ==================== 主体(持锁后) ====================

# 交易日闸门(与 intraday_snapshot.sh 同口径)
IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null)
echo "交易日判断: IS_TRADING=${IS_TRADING:-unknown}" | tee -a "$LOG"
if [ "${IS_TRADING:-0}" != "1" ]; then
  echo "非交易日, 跳过盘中增量回测(留 17:50 全量)" | tee -a "$LOG"
  exit 0
fi

# T = 上一交易日(交易日 9:40 跑, date.today()-1day 取最近交易日; 周一=上周五, 长假=节前最后交易日)
T_DATE=${1:-}
if [ -z "$T_DATE" ]; then
  T_DATE=$("$PY" -c "from datetime import date, timedelta; from app.calendar import last_trading_day; print(last_trading_day(d=date.today()-timedelta(days=1)))" 2>/dev/null)
fi
echo "上一交易日 T=${T_DATE:-?}" | tee -a "$LOG"
if [ -z "$T_DATE" ]; then
  echo "✗ 上一交易日计算失败, 跳过本轮" | tee -a "$LOG" >&2
  exit 1
fi
TODAY=$(date +%Y%m%d)
echo "今日(注入开盘价日) = $TODAY" | tee -a "$LOG"
[ "$TODAY" = "$T_DATE" ] && { echo "✗ T=今日(不应发生, is_trading_day 闸门已过), 跳过" | tee -a "$LOG" >&2; exit 1; }

ALERT_TIME=$(date '+%m-%d %H:%M')
OUTDIR="$REPO/static-site/data"
INTRA_TRADES="$OUTDIR/signal_kelly_trades_intraday.json"
INTRA_STATS="$OUTDIR/signal_kelly_backtest_intraday.json"
MAIN_TRADES="$OUTDIR/signal_kelly_trades.json"

# 1) 盘中增量档(限时 3min; 数据就绪闸/脚本错误 -> 非零退出)
echo "-> 跑盘中增量回测(信号日 T=$T_DATE, 限时 3min)..." | tee -a "$LOG"
perl -e 'alarm shift @ARGV; exec @ARGV' 180 \
  "$PY" "$REPO/scripts/signal_kelly_backtest.py" \
    --intraday-rerun "$T_DATE" \
    --intraday-main "$MAIN_TRADES" \
    --intraday-outdir "$OUTDIR" 2>&1 | tee -a "$LOG"
BK_RC=${PIPESTATUS[0]}
echo "回测退出码=$BK_RC" | tee -a "$LOG"

GATE_REPORT="$REPO/data/kelly_intraday_gate_report.json"
GATE_DECIDER="$REPO/scripts/kelly_intraday_gate_decider.py"

# 1a) 就绪闸判定统一交 decider(#254): 读 gate report -> 落豁免状态/ledger + 按 tier 发告警 + 返回 gate 码。
#     仅当回测「正常返回」(0=出档 / 5=abort) 才走 decider; 142 超时/其他脚本错误不属就绪闸范围。
GATE_RC=$BK_RC
if [ "$BK_RC" -eq 0 ] || [ "$BK_RC" -eq 5 ]; then
  "$PY" "$GATE_DECIDER" --report "$GATE_REPORT" --commit --backtest-rc "$BK_RC" 2>&1 | tee -a "$LOG"
  GATE_RC=${PIPESTATUS[0]}
  echo "就绪闸判定退出码=$GATE_RC(回测退出码=$BK_RC)" | tee -a "$LOG"
  # 回退保险(§23.11 不静默): decider 自身异常(非 0/5 的 gate 码) → 不让判定/告警丢失
  if [ "$GATE_RC" -ne 0 ] && [ "$GATE_RC" -ne 5 ]; then
    if [ "$BK_RC" -eq 5 ]; then
      # abort 分支: 沿用旧内联 WARN(与 2026-10-12 降噪逐字一致: tier=warning + 同 dedup key/window)+ 保持 exit 5
      "$PY" "$REPO/scripts/notify.py" "[告警] 凯利盘中增量回测本轮跳过(数据就绪闸 FAIL, 退出码 ${BK_RC}) ${ALERT_TIME}" \
        "kelly_intraday_rerun 退出码 ${BK_RC}: 数据就绪闸 FAIL(取不到今日真实开盘价), 本轮跳过, 留 17:50 全量兜底。详见日志:<br>$LOG" \
        --tier warning --from-prefix "[告警]" --dedup-key kelly_intraday_rerun_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
      GATE_RC=5
    else
      # tolerate/pass 分支: 回测已出档(产物在), 但 decider 未产出判定 → 补一条 WARN 后照常发布(不阻断)
      "$PY" "$REPO/scripts/notify.py" "[告警] 凯利盘中就绪闸 decider 异常(未产出判定) ${ALERT_TIME}" \
        "回测退出码 0(已出档), 但 kelly_intraday_gate_decider.py 自身异常(退出码 ${GATE_RC}), 就绪闸判定/豁免状态未落。本轮照常发布。详见日志:<br>$LOG" \
        --tier warning --from-prefix "[告警]" --dedup-key kelly_intraday_gate_decider_crash --dedup-window 1800 2>&1 | tee -a "$LOG" || true
      GATE_RC=0
    fi
  fi
fi

# 1b) 非就绪闸的失败(142 超时 / 3 对账 / 其他脚本错误) -> SEVERE 直达(与放宽前逐字一致)
if [ "$BK_RC" -ne 0 ] && [ "$BK_RC" -ne 5 ]; then
  case "$BK_RC" in
    142) echo "╷ 超时(>3min 限时被杀), 撞 intraday-snapshot 风险, 本轮跳过, 留 17:50 全量" | tee -a "$LOG" >&2;;
    3)  echo "╷ 对账机检 FAIL(产品不应发布)" | tee -a "$LOG" >&2;;
    *)  echo "╷ 回测脚本错误(退出码 ${BK_RC})" | tee -a "$LOG" >&2;;
  esac
  "$PY" "$REPO/scripts/notify.py" "[告警] 凯利盘中增量回测失败(退出码 ${BK_RC}) ${ALERT_TIME}" \
    "kelly_intraday_rerun 退出码 ${BK_RC}。详见日志:<br>$LOG" \
    --severe --from-prefix "[告警]" --dedup-key kelly_intraday_rerun_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  exit "$BK_RC"
fi

# 1c) 就绪闸 abort(单日未豁免取不到比例 > R): 整轮跳过, 留 17:50 全量(告警已由 decider 按降噪档发出)
if [ "$GATE_RC" -eq 5 ]; then
  echo "╷ 数据就绪闸 abort(单日缺口 >R), 本轮跳过, 留 17:50 全量" | tee -a "$LOG"
  exit 5
fi

# 2) 对账机检(§5.4⑦ 同构对账: 结构性 signal_date==T + 主档 pre-T 哈希漂移) 产品到位才允许发布
echo "-> 对账机检(--intraday-verify)..." | tee -a "$LOG"
"$PY" "$REPO/scripts/signal_kelly_backtest.py" \
  --intraday-verify "$INTRA_TRADES" --rerun-date "$T_DATE" --intraday-main "$MAIN_TRADES" 2>&1 | tee -a "$LOG"
VER_RC=${PIPESTATUS[0]}
echo "对账退出码=$VER_RC" | tee -a "$LOG"
if [ "$VER_RC" -ne 0 ]; then
  "$PY" "$REPO/scripts/notify.py" "[告警] 凯利盘中增量档对账 FAIL(退出码 ${VER_RC}) ${ALERT_TIME}" \
    "盘中档已生成但对账机检未过(结构性 signal_date!=T 或主档 pre-T 哈希漂移)。未发布。详见日志:<br>$LOG" \
    --severe --from-prefix "[告警]" --dedup-key kelly_intraday_verify_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  exit "$VER_RC"
fi

# 3) 上传 R2 + purge(对账 PASS 后; 与 intraday-snapshot 的 R2 上传时段错开: 9:40-9:43)
echo "-> 上传盘中档到 R2(upload-data-files + purge)... " | tee -a "$LOG"
if ! env R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=400 "$PY" "$REPO/scripts/upload_r2.py" upload-data-files signal_kelly_trades_intraday.json signal_kelly_backtest_intraday.json 2>&1 | tee -a "$LOG"; then
  echo "✗ 盘中档 R2 上传失败, 发告警邮件" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] 凯利盘中增量档 R2 上传失败 ${ALERT_TIME}" \
    "盘中增量档已生成但对账 PASS 后 R2 上传失败, 前端盘中视图读旧/无。需手动补刷: bash $REPO/scripts/upload_r2.py upload-data-files signal_kelly_trades_intraday.json signal_kelly_backtest_intraday.json<br>日志: $LOG" \
    --severe --from-prefix "[告警]" --dedup-key kelly_intraday_upload_r2_fail --dedup-window 1800 2>&1 | tee -a "$LOG" || true
  exit 1
fi

echo "=== kelly_intraday_rerun.sh 主体完成 $(date '+%Y-%m-%d %H:%M:%S') 退出码=0 ===" | tee -a "$LOG"
exit 0