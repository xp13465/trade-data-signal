#!/usr/bin/env bash
# overfit_monitor.sh - 过拟合监控每日打点(交易日 21:40 定时, B 档 2026-08-15)
#
# 交易日 21:40 跑: 重算准确率双口径(回测+实盘)每日打点 + 4 维过拟合指标 + 综合风险分,
# 命中预警(风险分>=60/连续5日攀升/象限退化/样本外衰减/参数尖峰)则 notify.py 发邮件+Telegram+飞书(24h去重)。
#
# 非交易日: 跳过打点(指数/信号数据不更新), 不产生新预警。传 force 绕过闸门强制跑(周末补数据)。
#
# 时点选择(§14): 21:40 避开盘后定时任务(17:50 update_all / 20:05 futures / 20:07 etf /
#   20:30 daily-summary / 20:40 daily-brief / 21:00 backfill-evening / 21:30 etf-national-team / 22:00)。
# 依赖: signal_kelly_trades.json(回测) + signal_daily/index_daily(实盘) + indicators.yaml(指数大类)。
#
# 日志(2026-08-25 监控盲区收尾批改造): 固定 append 到 overfit_monitor_launchd.log
#   (与全站 *_launchd.log 惯例一致; 旧版每次写 STAMP 新文件致上报链无法按固定名解析,
#    打点 rc!=0 无自动消费方=监控盲区; 旧 STAMP 文件保留不动可回溯)。开始/结束行用全站
#   标准格式(=== xxx.sh 开始/结束 ... 退出码=N ===), gen_schedule_stats standard 模式与
#   schedule_monitor 漏跑检查零特殊逻辑直读。
#
# 用法: bash scripts/overfit_monitor.sh [force]
# 日志: data/logs/overfit_monitor_launchd.log
set -u

# 树路径 env 化(P3-D 2026-08-25): 缺省回落现值行为不变; TRADE_REPO 更名 GIT_REPO
# 与全站惯例一致(intraday_snapshot/self_heal/update_all/staticdata_sync/push_schedule_stats)。
REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"   # git 渠道树(mjs 校验的前端源码所在)
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
mkdir -p "$LOGDIR"
cd "$REPO"

# NODE_BIN 探测(launchd PATH 无 nvm; command -v 失败则扫 ~/.nvm 版本目录取最新;
# 双双失败=recent parity 无法执行, 按 FAIL 处理不让盲区静默)
NODE_BIN="$(command -v node 2>/dev/null || true)"
if [ -z "$NODE_BIN" ]; then
  NODE_BIN="$(ls -1 "$HOME"/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
fi

# 交易日闸门(非交易日跳过打点; 传 force 强制跑供周末补数据)
LOG="$LOGDIR/overfit_monitor_launchd.log"
if [ "${1:-}" != "force" ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "$(date '+%F %T') 非交易日, 跳过过拟合监控打点" >> "$LOG"
    exit 0
  fi
fi

echo "==== overfit_monitor 打点开始 $(date '+%F %T') ====" >> "$LOG"
echo "=== overfit_monitor.sh 开始 $(date '+%F %T') ===" >> "$LOG"
# 打点(不打 --dry-run: 正常发送时若触发预警会真发, 但有 dedup 防轰炸)
"$PY" scripts/overfit_monitor.py >> "$LOG" 2>&1
RC=$?
# 打点产物即时 parity 自检(2026-08-24 用户拍板, 与 deploy.sh 1.2.2 同闸门):
# B件套拆分(commit 70163b663)误删主文件 filtered 挂载当时无任何自动链可拦, 病灶次日才暴露。
# 结构模式校验主/ext 键齐(主文件必含 filtered)+generated_at 对齐+compact, FAIL 则 rc 非0,
# 让 monitor_72h/schedule_monitor 监控层当天可见打点产物异常, 不等前端展示错人口。
if [ "$RC" -eq 0 ]; then
  "$PY" scripts/check_overfit_split_parity.py \
    --main "$REPO/static-site/data/overfit_monitor.json" \
    --ext "$REPO/static-site/data/overfit_monitor_ext.json" >> "$LOG" 2>&1
  PARITY_RC=$?
  if [ "$PARITY_RC" -ne 0 ]; then
    echo "==== overfit_monitor 打点产物 parity 结构校验 FAIL rc=$PARITY_RC ====" >> "$LOG"
    RC="$PARITY_RC"
  else
    echo "==== overfit_monitor 打点产物 parity 结构校验 PASS ====" >> "$LOG"
  fi
fi
# 组集一致性自检(2026-08-25 监控盲区收尾批, 与 deploy.sh 1.2.3 同闸门):
# check_overfit_recent_parity.mjs 把 app.js 真实组集函数切片进 vm 沙箱对 recent 明细
# 独立复刻逐点对比(18 断言), 此前从未挂自动链(「校验存在≠校验生效」filtered 键同款教训)。
# 打点成功后立即校验刚产出的 recent 明细, FAIL 则 rc 非0 当天可见。
# node 缺失也记 FAIL(fail-safe): 宁可告警也不静默放过未校验的产物。
if [ "$RC" -eq 0 ]; then
  if [ -n "$NODE_BIN" ] && [ -x "$NODE_BIN" ]; then
    RECENT_JSON="$REPO/static-site/data/overfit_monitor.json" \
      "$NODE_BIN" "$GIT_REPO/scripts/check_overfit_recent_parity.mjs" >> "$LOG" 2>&1
    RECENT_RC=$?
    if [ "$RECENT_RC" -ne 0 ]; then
      echo "==== overfit_monitor 组集一致性校验 FAIL rc=$RECENT_RC ====" >> "$LOG"
      RC="$RECENT_RC"
    else
      echo "==== overfit_monitor 组集一致性校验 PASS ====" >> "$LOG"
    fi
  else
    echo "==== overfit_monitor 组集一致性校验 SKIP-FAIL: 未找到可执行 node(launchd PATH 与 ~/.nvm 均无) ====" >> "$LOG"
    RC=1
  fi
fi
# 记账自刷(P3-C 2026-08-25): 打点+双校验全绿(rc=0)后立即刷新 schedule_stats 并推 R2,
# 此前 overfit 行滞后到次日其他任务触发 gen_schedule_stats 才更新(执行统计少一行/旧值)。
# 调用链与 update_all.sh 收尾同款: 先 gen_schedule_stats.py(standard 模式已含 overfit 行)
# 刷新本地, 再 push_schedule_stats.sh 上传 R2; 刷新失败不阻塞不改变打点 rc(记账非打点职责);
# 打点失败分支不刷——记账如实反映「未跑成」。
if [ "$RC" -eq 0 ]; then
  echo "---- 自刷 schedule_stats 记账 ----" >> "$LOG"
  "$PY" "${REPO}/scripts/gen_schedule_stats.py" >> "$LOG" 2>&1
  GEN_RC=$?
  if [ "$GEN_RC" -ne 0 ]; then
    echo "⚠ gen_schedule_stats.py 失败(rc=${GEN_RC}), 跳过推送待下次任务刷新" >> "$LOG"
  else
    if bash "${REPO}/scripts/push_schedule_stats.sh" >> "$LOG" 2>&1; then
      echo "==== schedule_stats 自刷推送 PASS ====" >> "$LOG"
    else
      echo "⚠ push_schedule_stats 失败(明细见其自身日志), schedule_stats 待下次任务刷新" >> "$LOG"
    fi
  fi
fi
echo "=== overfit_monitor.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
echo "==== overfit_monitor 结束 rc=$RC $(date '+%F %T') ====" >> "$LOG"
exit $RC
