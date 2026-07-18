#!/usr/bin/env bash
# uptime_check.sh - 线上可用性探活：curl overview.json 状态码 + 数据时效，异常 notify --severe。
#
# 检查两项：
#   1. HTTP 200 可达（curl 失败/非 200 -> 严重告警）
#   2. 数据时效：overview.date == 最近交易日（过期 -> 严重告警，防"站活着但数据停在几天前"）
#
# 用法：bash scripts/uptime_check.sh
#   SITE_URL=https://sugas.site/data/overview.json bash scripts/uptime_check.sh  # 自定义 URL
# 退出码：0=正常；1=异常（已发严重通知）。
# 日志：data/logs/uptime_YYYYMMDD_HHMM.log
#
# ── UptimeRobot 评估（备选/互补方案）─────────────────────────────────────────
# UptimeRobot 免费版：5 分钟间隔 HTTP 探活，超时/非 2xx 报警（邮件/Telegram）。
#   优点：外部多节点、免费、零运维、站点挂了能及时知道（本地脚本 mac 睡眠就探不到）。
#   缺点：只能 HTTP 状态码，不能查"数据时效"（站活着但数据陈旧它发现不了）；
#         依赖第三方服务 + 仅邮件/webhook 通知。
# 建议：本脚本（数据时效 + 自托管通知）+ UptimeRobot（外部纯可用性）互补。
#       接 UptimeRobot：dashboard 加 HTTP(s) 监控 -> https://sugas.site/data/overview.json，
#       通知渠道配 email/Telegram。无需改本仓库代码。
# ──────────────────────────────────────────────────────────────────────────────
set -u

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
URL="${SITE_URL:-https://sugas.site/data/overview.json}"
DRY_FLAG=""
[ "${UPTIME_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"   # 验证用：不真发邮件（仍写 alerts/latest.md）
STAMP=$(date +%Y%m%d_%H%M)
LOGDIR="$REPO/data/logs"
LOG="$LOGDIR/uptime_${STAMP}.log"
RESP="/tmp/uptime_resp_$$.json"

mkdir -p "$LOGDIR"
NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
echo "=== uptime_check.sh 开始 $NOW_STR URL=$URL ===" | tee "$LOG"

# 1. HTTP 探活
HTTP_CODE=$(curl -s -o "$RESP" -w "%{http_code}" --max-time 20 "$URL" 2>/dev/null)
CURL_RC=$?

ISSUE=""
if [ "$CURL_RC" -ne 0 ]; then
  ISSUE="curl 失败(rc=$CURL_RC)，无法访问 $URL"
elif [ "$HTTP_CODE" != "200" ]; then
  ISSUE="HTTP 状态码 ${HTTP_CODE}（非 200），${URL}"
else
  # 2. 数据时效：overview.date == last_trading_day
  FRESH=$("$PY" - "$RESP" 2>>"$LOG" <<'PYEOF'
import json, sys
from app.calendar import last_trading_day
try:
    d = json.load(open(sys.argv[1]))
    ov = d.get('date')
    ltd = last_trading_day()
    print("OK date=%s" % ov if ov == ltd else "STALE overview.date=%s last_trading_day=%s" % (ov, ltd))
except Exception as e:
    print("ERR 解析失败:%s" % e)
PYEOF
  )
  case "$FRESH" in
    OK*) ISSUE="" ;;
    *)   ISSUE="$FRESH" ;;
  esac
fi

if [ -n "$ISSUE" ]; then
  BODY="线上可用性探活异常<br>时间：$NOW_STR<br>URL：$URL<br>HTTP：${HTTP_CODE:-N/A}（curl rc=${CURL_RC:-N/A}）<br>问题：$ISSUE"
  "$PY" "$REPO/scripts/notify.py" "[严重]线上探活异常" "$BODY" --severe \
    --alert-issue "线上探活异常：$ISSUE" --alert-log "$LOG" $DRY_FLAG || true
  echo "✗ ${ISSUE}（已发严重通知）" | tee -a "$LOG"
  rm -f "$RESP" 2>/dev/null
  echo "=== uptime_check.sh 结束 异常 退出码=1 ===" | tee -a "$LOG"
  exit 1
fi

echo "✓ ${URL} 正常（HTTP ${HTTP_CODE}，${FRESH}）" | tee -a "$LOG"
rm -f "$RESP" 2>/dev/null
echo "=== uptime_check.sh 结束 正常 退出码=0 ===" | tee -a "$LOG"
exit 0
