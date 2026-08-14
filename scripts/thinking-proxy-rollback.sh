#!/bin/bash
# thinking-proxy-rollback.sh — 双端一键回退(还原 settings + 停代理)
#
# 用途:代理出问题/需停用时,一键还原到对应 provider 的直连原态。
# 幂等,可重复执行。支持双端:
#   bash scripts/thinking-proxy-rollback.sh            # 还原到 方舟直连(现网默认,无参)
#   bash scripts/thinking-proxy-rollback.sh official    # 还原到 官方直连(api.deepseek.com)
#   bash scripts/thinking-proxy-rollback.sh ark         # 显式还原到 方舟直连
#
# 说明:
#   - 只还原 ~/.claude/settings.json 的 ANTHROPIC_BASE_URL/MODEL 到对应 provider 直连备份,
#     不写 token(备份天然含原 token,还原即保留)。
#   - 停 launchd 代理 + pkill 兜底。
#   - agents frontmatter 的 model(flash/think 别名)不还原(直连下别名会 404,需人工改 inherit,
#     或直接走代理恢复)。回退到直连=放弃 per-role thinking 开关,thinking 默认 ON。

set -u

PROVIDER="${1:-ark}"   # 默认方舟直连
TS=$(date +%Y%m%d-%H%M%S)

# 各 provider 的直连备份(settings.json.bak-*-fallback 或官方直连)
# 方舟直连原态备份:bak-ark-fallback-20260814-094337(方舟 key + ark.cn-beijing.volces.com/api/coding)
# 官方直连备份:  bak-official-direct-20260814(官方 key sk-b0d32*** + api.deepseek.com/anthropic,由 trade-data/.env 生成)
ARK_BAK="$HOME/.claude/settings.json.bak-ark-fallback-20260814-094337"
OFFICIAL_BAK="$HOME/.claude/settings.json.bak-official-direct-20260814"

case "$PROVIDER" in
  ark)
    BAK="$ARK_BAK"; DESC="方舟直连(ark.cn-beijing.volces.com/api/coding)"
    ;;
  official)
    BAK="$OFFICIAL_BAK"; DESC="官方直连(api.deepseek.com/anthropic)"
    ;;
  *)
    echo "未知 provider: $PROVIDER (可用 ark|official)"; exit 1
    ;;
esac

echo "[1/4] 还原 settings 到: $DESC"
if [ -f "$BAK" ]; then
  cp "$BAK" "$HOME/.claude/settings.json"
  echo "  已还原自: $BAK"
  python3 -c "import json;d=json.load(open('$HOME/.claude/settings.json'));print('  BASE_URL:',d['env']['ANTHROPIC_BASE_URL']);print('  MODEL:',d['env']['ANTHROPIC_MODEL'])"
else
  echo "  !! 未找到备份 $BAK ,请人工确认"
fi

echo "[2/4] unload thinking-proxy plist"
PLIST=/Users/linhuichen/code/trade/scripts/com.trade.thinking-proxy.plist
if launchctl list 2>/dev/null | grep -q com.trade.thinking-proxy; then
  launchctl unload "$PLIST" && echo "  unload OK"
else
  echo "  未 load 或已 unload(幂等跳过)"
fi

echo "[3/4] pkill thinking_proxy.py"
if pgrep -f thinking_proxy.py >/dev/null 2>&1; then
  pkill -f thinking_proxy.py && echo "  已停止代理进程"
else
  echo "  无代理进程(幂等跳过)"
fi

echo "[4/4] 说明"
echo "  settings 已还原到 $DESC (token 未动,直连 = thinking 默认 ON)"
echo "  agents model 若保留 flash/think 别名,直连下会 404,需人工改为 inherit:"
echo "    .claude/agents/implementer.md + tester.md     -> model: inherit"
echo "    .claude/agents/reviewer.md + researcher.md    -> model: inherit"
echo "回退完成。如需恢复代理: launchctl load scripts/com.trade.thinking-proxy.plist"
exit 0
