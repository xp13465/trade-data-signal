#!/usr/bin/env bash
# simtrade_export_publish.sh - 22:55 导出模拟交易账本, 只发布 simtrade.json 一个文件到 R2。
#
# 链路: data/sim_trade.db -> scripts/export_sim_trade.py -> static-site/data/simtrade.json
#       -> upload_r2.py upload-data-files simtrade.json(data/ 前缀, 带 purge)
# 不跑全量 export/deploy: 只动 simtrade.json 一个 key, 不碰其他产物, 不推 main。
#
# 云上由 trade-simtrade-export.timer 调用(22:55, 在 settle 22:50 之后)。
# 手动重跑:
#   REPO=/home/ubuntu/code/trade-data CODE=/home/ubuntu/code/trade-data-signal \
#     bash scripts/simtrade_export_publish.sh
set -u

REPO=${REPO:-/home/ubuntu/code/trade-data}
CODE=${CODE:-/home/ubuntu/code/trade-data-signal}
PY=${PY:-/usr/bin/python3}
DATA="$REPO/static-site/data"
LOG="$REPO/data/logs/simtrade_export.log"
mkdir -p "$(dirname "$LOG")" "$DATA"

echo "[$(date '+%F %T')] simtrade export start" >> "$LOG"
# export 退出码: 0 = ok/missing/empty(正常空态); 2 = 账本 error(损坏/读不了)。
# 非零时不上传、直接 exit 1, 由 systemd 记 failed 触发告警; 线上保留上一份可信 JSON。

if ! "$PY" "$CODE/scripts/export_sim_trade.py" \
    --db "$REPO/data/sim_trade.db" \
    --out "$DATA/simtrade.json" \
    --etf-db "$REPO/data/etf_national_team.db" \
    --log-dir "$REPO/data/logs" >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] export FAILED" >> "$LOG"
  exit 1
fi

if ! env REPO="$REPO" R2_UPLOAD_LOCK_DOMAIN=data R2_UPLOAD_LOCK_TIMEOUT=180 \
    "$PY" "$CODE/scripts/upload_r2.py" upload-data-files simtrade.json >> "$LOG" 2>&1; then
  echo "[$(date '+%F %T')] R2 upload FAILED" >> "$LOG"
  exit 1
fi
echo "[$(date '+%F %T')] done" >> "$LOG"
