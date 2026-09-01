#!/usr/bin/env bash
# run_ab_direction_anchor.sh - 方向锚「开锚 vs 关锚」A/B harness 每日盘后触发脚本
# 目的:盘后(21:15,低价期)为当日 date 生成「关锚」参考并落盘;非交易日不调 API。
# 口径:与 gen_daily_brief 同 provider/model/config;只写 data/ab_direction_anchor.json。
# 输入依赖:REPO(trade-data 部署源树)/ DEEPSEEK_API_KEY(.env)/ static-site data 快照
# 输出:data/ab_direction_anchor.json(本地)+ docs/ai-predict/out/ab_direction_anchor_7d.json(--reconcile 产物)
# 复现:bash scripts/run_ab_direction_anchor.sh
set -uo pipefail

TRADE_DIR="${TRADE_DIR:-/Users/linhuichen/code/trade}"
PY="${PY:-/usr/bin/python3}"

# 交易日判断(与 run_daily_brief.sh 同法):非交易日不触发不调 API
TRADING="$($PY -c "
import sys
sys.path.insert(0, '$TRADE_DIR')
from app.calendar import is_trading_day
import datetime as _dt
print('1' if is_trading_day(_dt.date.today()) else '0')
" 2>/dev/null || echo '1')"

if [ "$TRADING" != "1" ]; then
  echo "[run_ab_direction_anchor] $(date '+%F %T') 非交易日,跳过(A/B 只累积真实交易日)。"
  exit 0
fi

# 7 日上限:已满 7 日不新调 API(留痕提示跑 --reconcile --force)
if [ -f "$TRADE_DIR/data/ab_direction_anchor.json" ]; then
  N="$(python3 -c "
import json
try:
    d=json.load(open('$TRADE_DIR/data/ab_direction_anchor.json'))
    print(len(d))
except Exception:
    print(0)
")"
  if [ "$N" -ge 7 ]; then
    echo "[run_ab_direction_anchor] $(date '+%F %T') 已满 7 日($N 条),不再新调 API,跑 --reconcile --force 出最终结论。"
    "$PY" "$TRADE_DIR/scripts/ab_direction_anchor.py" --reconcile --force
    exit 0
  fi
fi

"$PY" "$TRADE_DIR/scripts/ab_direction_anchor.py"
rc=$?
echo "[run_ab_direction_anchor] $(date '+%F %T') ab_direction_anchor.py exit=$rc"
exit $rc
