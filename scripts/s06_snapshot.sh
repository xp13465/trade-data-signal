#!/usr/bin/env bash
# s06_snapshot.sh - S06 降亏动态模式快照每日盘后重生(交易日 20:35 定时, 2026-08-26)
#
# 背景: S06 快照(kelly_mode_s06_state.json)此前仅手动生成, 切全站默认前必须让快照每日
# 盘后自动重生(用户拍板方向, B 级)。本脚本=launchd com.trade.s06-snapshot 的包装:
#   ①gen_kelly_mode_s06_state.py 重生快照(写 $REPO + $GIT_REPO 两树 static-site/data/)
#   ②check_s06_state.py 四断言机检(A1 独立复算/A2 decision_date 防前视/A3 键集/A4 阈值公示单源)
#   ③upload_r2.py upload-data-files 上传 R2 兜底副本 + purge CF edge(§22 N 缓存同步;
#     git/CF Pages 主站渠道随次日 17:50 deploy 追上——快照按信号日期取 effective_mode,
#     超覆盖期 fail-open 不拦截, 慢一天只影响新增日期行, 不影响既有判定)
# 任一段 FAIL → notify.py --severe 告警(--dedup-key 1h 内不重发防轰炸; 发送成功才记 dedup)。
#
# 时点选择依据(§14): 20:35 ——
#   输入 csi1000/hs300-all.json 由 update_all.sh(17:50 启动)统一 deploy 的
#   static-site/export.py 第 8 步生成, 实测 export 完成 ≈18:11、update_all 全链最晚结束
#   19:48(近5日观测 17:56~19:48), 20:35 留 ≥47min 缓冲保证收盘定型数据已就绪;
#   与 20:05 futures / 20:07 etf-national-team 错峰半小时, 早于 20:40 daily-brief 且本任务
#   秒级完成不抢资源; 属既有盘后节奏槽位(15:35/16:00/17:50/20:35/22:00), 不推 main 不写 DB,
#   §14「盘后时点不推 main」约束天然满足。
#   pmset 无需新增唤醒: 既有 wakepoweron=工作日 17:48(为 17:50 update-all 配置), 机器持续
#   活跃至 21:40 overfit-monitor, 20:35 落在活跃区间内。
# 非交易日: 跳过(index 收盘序列不更新, 快照无新日期可追加); 传 force 绕过闸门补跑。
#
# 用法: bash scripts/s06_snapshot.sh [force]
# 日志: data/logs/s06_snapshot_launchd.log(固定名 append, 全站标准开始/结束行供
#   gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读, 同 overfit_monitor 先例)
set -u

# codex008 F5(P3②): 三段命令统一超时包装防挂死(输入文件异常巨大/网络卡住时占住
# launchd 槽位拖垮后续任务)。macOS 无 coreutils timeout, fallback 链:
# timeout → gtimeout(brew coreutils)→ perl alarm-exec(alarm 计时器跨 exec 保留, 等效
# timeout 语义); 超时按非零处理走既有 FAIL 告警链。
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

REPO="${REPO:-/Users/linhuichen/code/trade-data}"
GIT_REPO="${GIT_REPO:-/Users/linhuichen/code/trade}"
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR=$REPO/data/logs
mkdir -p "$LOGDIR"
cd "$REPO"
LOG="$LOGDIR/s06_snapshot_launchd.log"

# 交易日闸门(同 overfit_monitor.sh; 失败 fail-open 默认跑, 防日历源异常静默停更)
if [ "${1:-}" != "force" ]; then
  IS_TRADING=$("$PY" -c "from app.calendar import is_trading_day; print(1 if is_trading_day() else 0)" 2>/dev/null || echo 1)
  if [ "$IS_TRADING" != "1" ]; then
    echo "$(date '+%F %T') 非交易日, 跳过 S06 快照重生" >> "$LOG"
    exit 0
  fi
fi

echo "=== s06_snapshot.sh 开始 $(date '+%F %T') ===" >> "$LOG"

RC_GEN=0; RC_CHK=0; RC_R2=0

# ① 重生快照(两树原子写; 超时 300s 防挂死)
run_to 300 "$PY" scripts/gen_kelly_mode_s06_state.py --repo "$REPO" --git-repo "$GIT_REPO" >> "$LOG" 2>&1
RC_GEN=$?
if [ "$RC_GEN" -ne 0 ]; then
  echo "✗ S06 快照生成失败 rc=${RC_GEN}" >> "$LOG"
else
  # ② 四断言机检(FAIL 即阻断语义: 本链不上线数据, 但必须当场暴露不许静默带病产物留两树;
  #    超时 300s 与 check_data_integrity.check_s06_state_snapshot 同口径。
  #    此处保持严格模式不带 --allow-lag-days: 刚生成完快照 lag=0, 若 lag>0 说明输入
  #    因子与快照错位属真异常, 必须当场暴露; deploy 时序窗口容差只在 integrity 链启用)
  run_to 300 "$PY" scripts/check_s06_state.py --repo "$REPO" --data-repo "$REPO" >> "$LOG" 2>&1
  RC_CHK=$?
  if [ "$RC_CHK" -ne 0 ]; then
    echo "✗ S06 快照机检 FAIL rc=${RC_CHK}(产物可能带病, 告警人工核查)" >> "$LOG"
  else
    # ③ R2 兜底副本即时同步(上传+purge 一条龙; 含网络往返给 600s; 失败不阻断——git 渠道随次日 deploy 追上)
    run_to 600 "$PY" scripts/upload_r2.py upload-data-files kelly_mode_s06_state.json >> "$LOG" 2>&1
    RC_R2=$?
    [ "$RC_R2" -ne 0 ] && echo "⚠ S06 快照 R2 同步失败 rc=${RC_R2}(git 渠道随次日 deploy 追上)" >> "$LOG"
  fi
fi

FINAL_RC=$RC_GEN
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_CHK
[ "$FINAL_RC" -eq 0 ] && FINAL_RC=$RC_R2

if [ "$FINAL_RC" -ne 0 ]; then
  "$PY" scripts/notify.py \
    "[S06] 快照重生链路异常 gen=$RC_GEN check=$RC_CHK r2=$RC_R2 $(date '+%m-%d %H:%M')" \
    "S06 每日重生三段(gen 重生成 / check A1-A4 机检 / r2 R2同步)任一失败, 快照可能过期或带病。<br>日志: $LOG (尾部 50 行)<br>影响: 前端 S06 档超覆盖期 fail-open 不拦截, 静默退化。" \
    --severe --from-prefix "[告警]" \
    --alert-issue "S06 快照重生链路异常" --alert-log "$LOG" \
    --dedup-key s06_snapshot_fail --dedup-window 3600 >> "$LOG" 2>&1
fi

echo "=== s06_snapshot.sh 结束 $(date '+%F %T') 退出码=$FINAL_RC ===" >> "$LOG"
exit "$FINAL_RC"
