#!/usr/bin/env bash
# 复现脚本:AI 预测板块交互三连修复冒烟(playwright chromium 离线 DOM 冒烟)
# 用途:fix(dbbrief) 方向红涨绿跌分色 + 点击区域收敛 + 反思校准连坐修复 的四断言自测
# 复现: bash docs/ai-predict/scripts/dbbrief_interaction_smoke.sh <static-site目录> <主仓data副本>
#   例:  bash docs/ai-predict/scripts/dbbrief_interaction_smoke.sh \
#          /private/tmp/wt-dbbrief-fix/static-site /Users/linhuichen/code/trade/static-site/data
# 输入依赖: app.js/style.css/i18n.js(被测源) + data/daily_brief.json + daily_brief_history.json(真实数据副本)
# 输出: 终端逐条 PASS/FAIL(20 断言基线 2026-08-27 全 PASS),exit 非0=有 FAIL
# 依赖: node + playwright(chromium),NODE_PATH 缺省回退 ~/node_modules
set -euo pipefail
SRC="${1:?usage: $0 <static-site-dir> <master-data-dir>}"
DATA="${2:?usage: $0 <static-site-dir> <master-data-dir>}"
WORK="$(mktemp -d /tmp/dbbrief-smoke.XXXXXX)"
PORT=8136
trap 'kill $SRV_PID 2>/dev/null || true; rm -rf "$WORK"' EXIT
cp "$SRC/app.js" "$SRC/style.css" "$SRC/i18n.js" "$WORK/"
mkdir -p "$WORK/data"
cp "$DATA/daily_brief.json" "$DATA/daily_brief_history.json" "$WORK/data/"
DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$DIR/dbbrief_interaction_smoke.js" "$WORK/smoke_dbbrief.js"
cp "$DIR/dbbrief_smoke_harness.html" "$WORK/harness.html"
python3 -m http.server "$PORT" --directory "$WORK" >/dev/null 2>&1 &
SRV_PID=$!
sleep 1
NODE_PATH="${NODE_PATH:-$HOME/node_modules}" node "$WORK/smoke_dbbrief.js"
