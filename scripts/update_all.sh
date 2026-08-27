#!/usr/bin/env bash
# update_all.sh - 一键更新（并发流水线版）
#
# 把原串行 collect->deploy->check 拆成 4 条并行 pipeline，各自独立采集->计算，
# 慢任务（mootdx 5072 只）不阻塞快核心：
#   core        快核心（指数/指标/情绪分）
#   width       慢宽度（mootdx/行业宽度/全市场宽度）
#   futures     独立（期货机构持仓）
#   stock_daily 后台死端（全 A 股日线备用源），不 export 不 push，不阻塞
#   turnover    慢（baostock 增量 + cleanup 算 a_turnover）
# O1 收敛（2026-08-17 批次A）：deploy 由「每条 pipeline 各跑一遍完整 deploy（4 遍=88min 主因）」
#   收敛为「末尾统一 1 次完整 deploy」——各 pipeline 只采集+计算写入 DB，等全部完成后再统一
#   跑 1 次完整 deploy（覆盖全部 4 pipeline 产物，§22 一致性），配套 ab#39 增量导出提速。
# 各 pipeline 不再各自 commit+push（原 flock /tmp/trade_deploy.lock 串行 git 只用于统一 deploy 与
# 并发 backfill 竞争）。
#
# 非交易日：默认跳过采集仅 deploy 补推数据（不发买卖点信号邮件）；传 force 绕闸门强制采集（周末补数据/校准）。
# 旧串行版备份：scripts/update_all_serial.sh。
#
# 用法：bash scripts/update_all.sh [force]
#   force: 绕过交易日闸门，非交易日也跑全量 pipeline（补漏跑数据/校准；当日快照采最近交易日值）
# 日志：data/logs/update_all_YYYYMMDD_HHMM.log（汇总，含各 pipeline 交错输出）
#       data/logs/pipeline_<name>_<STAMP>.log（各流水线独立日志）
# 退出码：core pipeline 退出码（核心看板公网状态；统一 deploy 失败经 DEPLOY_ALL_RC 触发 SEVERE）。
set -u

# 防止脚本运行期间 mac 休眠（17:50 launchd 触发时若 mac 在睡眠边缘，跑期间不再睡；
# caffeinate -i 防系统空闲睡眠，-w $$ 跟随本脚本 PID，脚本退出 caffeinate 自动结束）
caffeinate -i -w $$ >/dev/null 2>&1 &

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 始终在 trade 仓库(trade-data 不 git init)
export REPO GIT_REPO   # #75 显式导出,确保 upload_r2.py 子进程继承 REPO(防缺省回退读 trade 旧库)
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
  echo "非交易日，跳过采集，仅 deploy 补推数据（不发信号邮件，force 可绕过）" | tee -a "$LOG"
  bash "$REPO/scripts/deploy.sh" 2>&1 | tee -a "$LOG"
  # 非交易日不发买卖点信号邮件：周末/节假日休市没开盘，补采是最近交易日的缺口数据，
  # 此时发信号=用户周末收到周五信号邮件（2026-08-15 用户报）。数据补推由上方 deploy 承担，
  # 信号检测留待交易日主链路（下方 IS_TRADING=1 分支 L90-91）自然补发。
  # 若确需非交易日手动校验信号，用 force 模式（仍会发，供人工校准）。
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

# #11 基金全史净值（export_fund_nav, 弹窗净值走势数据源）——先刷产物再过闸门(fund_nav 时序倒挂修复 2026-08-27)
# 原排在 O1 统一 deploy 之后, 而 deploy 内 check_data_integrity 抽样拿当晚已进新净值的 DB
# 对昨晚产物逐位比对 -> 时序倒挂误拦(17:02/17:58 两连拦实证)。这里整体前置: 先全量重出
# fund_nav 产物, 再让 O1 deploy 过数据完整性闸门; upload-fund-nav 上传环节仍留脚本后段原位不动。
echo "-> 基金全史净值（export_fund_nav, 弹窗净值走势数据源, 先刷产物再过闸门）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_fund_nav.py" >> "$LOG" 2>&1
FUND_NAV_RC=$?
if [ "$FUND_NAV_RC" -ne 0 ]; then
  # 硬闸门(codex review critical, 2026-08-25): 导出失败=fund_nav 产物未刷新, 绝不继续
  # rsync+upload, 防把截断/过期净值发布被前端消费。显式告警写入日志, 不静默吞掉(L44)。
  echo "【CRITICAL】export_fund_nav 失败(退出码 $FUND_NAV_RC), fund_nav 产物未刷新, 硬闸门跳过后续 fund_nav rsync+upload-fund-nav(§22 一致性)" | tee -a "$LOG"
else
  # export 写 JSON 到 $REPO/static-site/data/(trade-data), 同步到 trade/static-site/data/ 供
  # upload_r2 + deploy(trade 跑时 no-op); 随 export 前置, O1 闸门校验到的就是刚刷新的最新产物
  rsync -a --delete --checksum "$REPO/static-site/data/fund_nav/" "/Users/linhuichen/code/trade/static-site/data/fund_nav/" 2>>"$LOG" || \
    echo "⚠ fund_nav rsync 同步失败, 可能发布不全" | tee -a "$LOG"
fi

# O1 收敛（2026-08-17 批次A）：4 条 pipeline 已各自完成采集+计算写入 DB，
# deploy 从「每条 pipeline 各跑一遍完整 deploy（4 遍=88min 主因）」收敛为「统一 1 次完整 deploy」。
# 此时所有 pipeline 采集已完成，build_board_etf_map/export 读到的 DB 是全量最新，
# 单次完整 deploy 覆盖全部 4 pipeline 产物（§22 一致性：无一 pipeline 产物漏 deploy）。
# 与并发 backfill 脚本共用 deploy.lock 串行化 git（防 index.lock 竞争）。
echo "-> O1 统一 1 次完整 deploy（覆盖全部 pipeline 产物，原 4 遍→1 遍）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/with_lock.py" /tmp/trade_deploy.lock bash "$REPO/scripts/deploy.sh" all >> "$LOG" 2>&1
DEPLOY_ALL_RC=$?
if [ "$DEPLOY_ALL_RC" -ne 0 ]; then
  echo "✗ O1 统一 deploy 失败 (rc=$DEPLOY_ALL_RC)" | tee -a "$LOG"
  # 统一 deploy 失败仍继续后续（信号/快照/预警等不阻塞），但标记 SEVERE（下方 NOTIFY 判断）
else
  echo "✓ O1 统一 deploy 完成" | tee -a "$LOG"
fi

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

# P1-新-C ETF买卖清单：全市场 ETF评分排序 -> etf_score_list_{buy,sell,hold}.json (+ .gz)
# B4 并发改造(2026-07-24):加 --full-market 跑全市场1371只(原62只代表性),
# 跟随 alert 每日重算（买卖清单应每日最新），失败不阻塞；口径同 export_alert
# P0-2 (2026-08-05): 拆 3 JSON (buy/sell/hold) + 懒加载, 原 18MB 单文件 -> buy+sell ~2.6MB + hold 13MB(懒加载)
echo "-> ETF评分清单（etf_score_list --full-market 全市场, 拆 3 JSON）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_etf_score_list.py" --full-market >> "$LOG" 2>&1
SCORE_LIST_RC=$?
if [ "$SCORE_LIST_RC" -ne 0 ]; then
  # 硬闸门(2026-08-25 同款, 用户已确认根治): 导出失败绝不继续 rsync+upload,
  # 防把截断/过期买卖清单发布到 R2。显式告警入日志不静默(L44)。
  echo "【CRITICAL】export_etf_score_list 失败(退出码 $SCORE_LIST_RC), 硬闸门跳过 etf_score_list rsync+upload-etf-score, 防发布截断/过期清单(§22 一致性)" | tee -a "$LOG"
else
# export 写 JSON 到 $REPO/static-site/data/(trade-data), 同步到 trade/static-site/data/ 供 upload_r2 + deploy
# (deploy.sh rsync 在 pipeline 内跑, export 在 pipeline 后跑, 需单独同步; trade 跑时 no-op)
rsync -a --checksum "$REPO/static-site/data/etf_score_list_"* "/Users/linhuichen/code/trade/static-site/data/" 2>>"$LOG" || \
  echo "⚠ etf_score_list rsync 同步失败, 可能发布不全" | tee -a "$LOG"
"$PY" "$REPO/scripts/upload_r2.py" upload-etf-score >> "$LOG" 2>&1 || \
  echo "⚠ upload-etf-score R2上传失败（不阻塞主流程）" | tee -a "$LOG"
fi

# #10 ETF弹窗长历史(2026-08-22): ETF 全史日K etf/{code}-all.json (1532只~87MB, ~5s)
# 前端 period tab 懒加载 R2 etf/ 前缀; 跟随 etf_score_list 每日重算后同步导出
echo "-> ETF全史日K（export_etf_hist, 弹窗长历史数据源）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_etf_hist.py" >> "$LOG" 2>&1
ETF_HIST_RC=$?
if [ "$ETF_HIST_RC" -ne 0 ]; then
  # 硬闸门(2026-08-25 同款, 用户已确认根治): 导出失败绝不继续 rsync+upload,
  # 防把截断/过期全史日K发布到 R2。显式告警入日志不静默(L44)。
  echo "【CRITICAL】export_etf_hist 失败(退出码 $ETF_HIST_RC), 硬闸门跳过 etf rsync+upload-etf-hist, 防发布截断/过期日K(§22 一致性)" | tee -a "$LOG"
else
  rsync -a --delete --checksum "$REPO/static-site/data/etf/" "/Users/linhuichen/code/trade/static-site/data/etf/" 2>>"$LOG" || \
    echo "⚠ etf rsync 同步失败, 可能发布不全" | tee -a "$LOG"
  "$PY" "$REPO/scripts/upload_r2.py" upload-etf-hist >> "$LOG" 2>&1 || \
    echo "⚠ upload-etf-hist R2上传失败（不阻塞主流程）" | tee -a "$LOG"
fi

# P2-新-W 浏览器通知源 JSON（根因①修复：收盘全量后导出 notifications.json，覆盖 post_close 场景）
# 读 DB 当日信号/预警/恐贪/异动 + post_close=True 标志（18:00 后），前端弹"收盘速递"通知。
# 失败不阻塞；口径同 export_alert（本地更新，下次 pipeline deploy 推上线）。
echo "-> 浏览器通知源（notifications.json post_close）..." | tee -a "$LOG"
"$PY" "$REPO/scripts/export_notifications.py" >> "$LOG" 2>&1 || \
  echo "⚠ export_notifications 失败（不阻塞主流程）" | tee -a "$LOG"

# 筛选器阶段0: 日更4汇总接口~22s(performance/rating/purchase/manager_em)
# 全量采集(overview/risk/fee/manager自爬/nav 5年净值)挂凌晨launchd, 不进update_all
# (offshore_fund_*.json 定时导出链已停用, 2026-08-22 P2-15 用户确认: 零消费方, #84 手动用 export_offshore_fund.py)
echo "-> 公募基金筛选器日更（stage0-daily 4汇总接口~22s）..." | tee -a "$LOG"
"$PY" -m app.collector.public_fund stage0-daily >> "$LOG" 2>&1 || \
  echo "⚠ stage0-daily 失败（不阻塞主流程）" | tee -a "$LOG"

# 阶段1 评分引擎: 头部2000只评分 + 导出 fund_score*.json + R2 上传
# 全量27409只挂 launchd pf-score-weekly 周日跑, 不进 update_all(2.3h太长阻塞核心)
# 头部2000只~2min(实测, 大部分基金无fund_daily_nav快速返回None), 失败不阻塞主流程
echo "-> 公募基金评分引擎（compute_all_scores top_n=2000 + export）..." | tee -a "$LOG"
"$PY" -c "from app.collector.public_fund import compute_all_scores; compute_all_scores(top_n=2000, resume=True)" >> "$LOG" 2>&1 || \
  echo "⚠ compute_all_scores 失败（不阻塞主流程）" | tee -a "$LOG"
"$PY" "$REPO/scripts/export_fund_score.py" --top-n 2000 >> "$LOG" 2>&1
FUND_SCORE_RC=$?
if [ "$FUND_SCORE_RC" -ne 0 ]; then
  # 硬闸门(2026-08-25 同款, 用户已确认根治): 导出失败绝不继续 rsync+upload,
  # 防把截断/过期评分发布到 R2。显式告警入日志不静默(L44)。
  echo "【CRITICAL】export_fund_score 失败(退出码 $FUND_SCORE_RC), 硬闸门跳过 fund_score rsync+upload-fund-score, 防发布截断/过期评分(§22 一致性)" | tee -a "$LOG"
else
  rsync -a --checksum "$REPO/static-site/data/fund_score"* "/Users/linhuichen/code/trade/static-site/data/" 2>>"$LOG" || \
    echo "⚠ fund_score rsync 同步失败, 可能发布不全" | tee -a "$LOG"
  "$PY" "$REPO/scripts/upload_r2.py" upload-fund-score >> "$LOG" 2>&1 || \
    echo "⚠ upload-fund-score R2上传失败（不阻塞主流程）" | tee -a "$LOG"
fi

# #11 基金弹窗净值走势 R2 上传(2026-08-25): 基金全史净值 fund_nav/{code}.json -> R2 fund_nav/
# 前缀; 前端「净值走势」period tab 懒加载 R2 fund_nav/; 复刻 #10 etf-hist 链路(增量指纹上传,
# 清盘基金序列冻结自然跳过); 当日净值多晚间公布, 入图最新通常为 T-1(走势历史场景无感)
# (2026-08-27 fund_nav 时序倒挂修复: export_fund_nav.py + rsync 已整体前置到 O1 统一 deploy
# 之前「先刷产物再过闸门」; 本处仅保留 upload-fund-nav 上传环节原位不动, FUND_NAV_RC!=0 即
# export 失败时跳过上传 = 硬闸门语义不变)
if [ "$FUND_NAV_RC" -eq 0 ]; then
  "$PY" "$REPO/scripts/upload_r2.py" upload-fund-nav >> "$LOG" 2>&1 || \
    echo "⚠ upload-fund-nav R2上传失败（不阻塞主流程）" | tee -a "$LOG"
fi

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
[ "${DEPLOY_ALL_RC:-0}" -ne 0 ] && SEVERE=1
[ "$FRESH_OK" != "1" ] && SEVERE=1
[ "${FUND_NAV_RC:-0}" -ne 0 ] && SEVERE=1  # P2返修 2026-08-27: 前置导出失败=fund_nav 数据断供(产物不刷新+跳过上传), 升级严重告警
[ "${SCORE_LIST_RC:-0}" -ne 0 ] && SEVERE=1  # 样板抄齐 2026-08-27: 导出失败=买卖清单数据断供(R2 停旧版+跳过上传), 升级严重告警
[ "${ETF_HIST_RC:-0}" -ne 0 ] && SEVERE=1    # 样板抄齐 2026-08-27: 导出失败=ETF全史日K数据断供, 升级严重告警
[ "${FUND_SCORE_RC:-0}" -ne 0 ] && SEVERE=1  # 样板抄齐 2026-08-27: 导出失败=基金评分数据断供, 升级严重告警
NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
# 邮件 subject 统一模板 [类型]关键信息 MM-DD HH:MM（2026-07-20 改造）
MM_DD_HM=$(date '+%m-%d %H:%M')

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

NOTIFY_BODY="update_all 完成<br>耗时：${ELAPSED_MIN} 分钟（${ELAPSED}秒）<br>退出码：core=$RC_CORE width=$RC_WIDTH futures=$RC_FUTURES turnover=$RC_TURNOVER deploy_all=${DEPLOY_ALL_RC:-0} check_signals=$SIGNAL_RC${FAILED_DETAILS}<br>数据时效：$FRESH_MSG<br>日志：$LOG<br>结束时间：$NOW_STR"
if [ "$SEVERE" -eq 1 ]; then
  ISSUE="update_all 严重告警："
  [ "$ELAPSED" -gt 3600 ] && ISSUE="${ISSUE}耗时超1h(${ELAPSED_MIN}分钟) "
  [ "$RC_CORE" -ne 0 ] && ISSUE="${ISSUE}core退出码非0($RC_CORE) "
  [ "${DEPLOY_ALL_RC:-0}" -ne 0 ] && ISSUE="${ISSUE}统一deploy失败(${DEPLOY_ALL_RC}) "
  [ "$FRESH_OK" != "1" ] && ISSUE="${ISSUE}数据时效异常($FRESH_MSG)"
  [ "${FUND_NAV_RC:-0}" -ne 0 ] && ISSUE="${ISSUE}fund_nav导出失败(rc=${FUND_NAV_RC:-0},产物未刷新) "
  [ "${SCORE_LIST_RC:-0}" -ne 0 ] && ISSUE="${ISSUE}etf_score_list导出失败(rc=${SCORE_LIST_RC:-0},产物未刷新) "
  [ "${ETF_HIST_RC:-0}" -ne 0 ] && ISSUE="${ISSUE}etf_hist导出失败(rc=${ETF_HIST_RC:-0},产物未刷新) "
  [ "${FUND_SCORE_RC:-0}" -ne 0 ] && ISSUE="${ISSUE}fund_score导出失败(rc=${FUND_SCORE_RC:-0},产物未刷新) "
  # 防噪 2026-08-27: 复用 notify.py 现成 --dedup-key/--dedup-window(状态文件 data/notify_dedup.json,
  # 发送成功才登记/suppress 静默退0/fail-open; 先例=intraday upload-index R2 失败去重)。
  # key=完整 ISSUE 问题串: 同一问题组合 30min 内只发一次(手动补跑/force 连跑窗口防轰炸),
  # 问题组合变化(rc 或触发项不同)=新 key 正常发送, 不漏报。
  "$PY" "$REPO/scripts/notify.py" "[告警] update_all ${ISSUE} ${MM_DD_HM}" "$NOTIFY_BODY" --severe --from-prefix "[告警]" --alert-issue "$ISSUE" --alert-log "$LOG" --dedup-key "update_all_severe:${ISSUE}" --dedup-window 1800 || true
else
  "$PY" "$REPO/scripts/notify.py" "[完成] update_all ${ELAPSED_MIN}min ${MM_DD_HM}" "$NOTIFY_BODY" --from-prefix "[完成]" || true
fi

# D10 每日收盘情绪速递邮件 main 模式（T日盘后情绪:恐贪/情绪/涨跌/成交额/板块/冰点）。
# summary_history.json 已由 pipeline deploy 生成就绪;不含期货/汪汪队/公募(那些走 20:30 supplement)。
# 失败不阻塞主流程：调 notify.py 告警，退出码仍以 RC_CORE 为准。
# 非交易日已在上方 exit 0 不会走到这；脚本内部对无数据日期也优雅跳过。
echo "-> daily_summary_email 情绪速递邮件(main) ..." | tee -a "$LOG"
if "$PY" "$REPO/scripts/daily_summary_email.py" --mode main >> "$LOG" 2>&1; then
  echo "  ✓ 情绪速递邮件已处理" | tee -a "$LOG"
else
  _DSE_RC=$?
  echo "⚠ daily_summary_email 失败(不阻塞主流程) rc=$_DSE_RC" | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[告警] 情绪速递邮件失败 ${MM_DD_HM}" \
    "daily_summary_email 退出码 $_DSE_RC<br>日志: $LOG" --from-prefix "[告警]" || true
fi

# daily_brief 每日AI预测（第一阶段后端：单 prompt 主链路 + 双配置开关 + 机检回测 + 合规 + 归档）。
# 【2026-08-11 迁移】调度改独立 launchd plist com.trade.daily-brief 20:40 自动跑
# （config/daily_brief.yaml schedule_enabled=true + ~/Library/LaunchAgents/com.trade.daily-brief.plist）。
# 此处注释 17:50 挂载，避免 17:50 与 20:40 重复跑（一天一次 20:40，避 20:35 intraday-snapshot）。
# run_daily_brief.sh 读 schedule_enabled: true=自动跑;false=拦截。失败不阻塞主流程(内部已降级规则版/minimal,不抛错)。
# 如需改回 17:50 挂载：取消下行注释 + launchctl unload com.trade.daily-brief。
# bash "$REPO/scripts/run_daily_brief.sh" 2>&1 | tee -a "$LOG"

# 每日 DB 热备 + R2 异地备份（update_all 跑完后 DB 已是最新，此时备份最稳）。
# 失败不影响 update_all 退出码（RC_CORE 保持看板状态）。
bash "$REPO/scripts/backup_db.sh" || echo "⚠ backup_db 失败(不影响update_all) rc=$?"

# 刷新 schedule_stats.json（2026-07-24 方案A根治：从 deploy.sh:72 移到此处，在"结束"行后调用，
# gen_stats 能读到完整"开始+结束"对，正确配对当前任务 exit/dur，不再 pending null；
# update_all 不在 gen_schedule_stats 任务清单，但跑完各 pipeline 后兜底刷新一次 stats）
"$PY" "$REPO/scripts/gen_schedule_stats.py" 2>&1 | tee -a "$LOG" \
  || echo "⚠ gen_schedule_stats.py 失败(退出码 $?)，不阻塞" | tee -a "$LOG"

# 独立 push schedule_stats.json 到 main（2026-07-30 方案C+R2：gen_stats 后立即 push 绕过 deploy.sh 时序）
bash "$REPO/scripts/push_schedule_stats.sh" || echo "⚠ push_schedule_stats 失败" | tee -a "$LOG"

# 退出码以 core 为准（核心看板公网状态）
exit "$RC_CORE"
