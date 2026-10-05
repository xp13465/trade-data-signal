#!/bin/bash
# brief_push_wrapper.sh —— AI 每日速递订阅推送服务定时调度入口。
# 在 daily_brief 生成（20:40 run_daily_brief.sh -> gen_daily_brief.py）之后，20:45 由 launchd
# com.trade.brief-push 触发，跑 brief_push.py 推送给订阅者 + 飞书报告群。
#
# 设计（§23.7 只增不改 + memory daily-brief-range-degrade-contract）：
#   - 独立 wrapper + 独立 launchd，不碰现有 run_daily_brief.sh / com.trade.daily-brief plist。
#   - 非交易日判断在 brief_push.py 内做（复用 trade/app/calendar.py is_trading_day），不在此重复。
#   - 失败不阻塞主流程，退出码恒 0（与 run_daily_brief.sh 同模式）。
#   - daily_brief 未生成（文件缺失）时 brief_push.py 自行报错退出，wrapper 记日志。
#   - P0-2（2026-10-03 云体检 D3 §3-2）：失败时 notify --severe 到用户（含 latest.md），
#     防"订阅推送断了没人知道"——原设计失败仅写日志，退出码恒 0 使 monitor 漏跑/exit 检查
#     全部不触发=永久静默。现只在失败分支加显式信号，成功路径/退出码设计不动。
#
# 用法: bash scripts/brief_push_wrapper.sh [--dry-run]

set -u
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"

LOG="${LOG:-$REPO/data/logs/brief_push.log}"
mkdir -p "$(dirname "$LOG")"

# --dry-run 透传给 notify.py（隔离自测：不真发邮件/飞书；但 notify 的 write_alert
# 不 gate dry_run——失败分支 --alert-issue 下 dry-run 也会写真实 latest.md，
# 测试需 REPO=tmp 隔离，生产手动 --dry-run 失败分支会落真实 alerts 目录）
_NOTIFY_DRY=""
case " $* " in
  *" --dry-run "*) _NOTIFY_DRY="--dry-run";;
esac

echo "[brief_push_wrapper] start $(date '+%Y-%m-%d %H:%M:%S') args: $*" | tee -a "$LOG"
# 注意：wrapper 里 REPO=trade-data，但 brief_push.py 内部用 __file__ resolve 到 trade/scripts，
# daily_brief.json 读 trade/static-site/data/（与 gen_daily_brief.py 双写位置一致）。
if "$PY" "$REPO/scripts/brief_push.py" "$@" >> "$LOG" 2>&1; then
  echo "[brief_push_wrapper] ✓ 完成" | tee -a "$LOG"
else
  rc=$?
  echo "[brief_push_wrapper] ✗ 失败 rc=$rc" | tee -a "$LOG"
  # P0-2（2026-10-03）：失败显式信号。notify 失败不影响本 wrapper 退出码（|| true），
  # 告警仍走 notify 独立通道。dedup 21600(6h) 防同窗口重试/手动重跑轰炸——正常路径
  # 每天最多 0 封，故障日最多 1 封（20:45 一轮），不违反"宁少勿滥"。
  "$PY" "$REPO/scripts/notify.py" \
    "[告警] brief_push 推送失败 rc=$rc" \
    "AI 每日速递订阅推送失败，订阅者将收不到当日速递。详见日志：${LOG}" \
    --severe --from-prefix "[告警]" \
    --alert-issue "brief_push 推送失败" --alert-log "${LOG}" \
    --dedup-key "brief_push_fail" --dedup-window 21600 \
    $_NOTIFY_DRY >> "$LOG" 2>&1 || true
fi
exit 0
