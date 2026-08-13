#!/bin/bash
# thinking-proxy-rollback.sh — 一键回退官方直连 thinking 代理(还原 settings + 停代理 + agents 说明)
#
# 用途:代理出问题/需停用时,一键还原到"官方直连不注入"状态。幂等,可重复执行。
# 回退对象:
#   ① ~/.claude/settings.json 从最近备份还原(ANTHROPIC_BASE_URL 回官方直连 / ANTHROPIC_MODEL 回原值)
#   ② launchctl unload com.trade.thinking-proxy.plist
#   ③ pkill thinking_proxy.py
#   ④ 说明 agents model 需按需还原
# 注意:本脚本不改 ~/.claude/settings.json 的 token(备份天然含原 token,还原即保留)。

set -u

echo "[1/4] 还原 ~/.claude/settings.json(从最近 thinking 备份)"
BAK=$(ls -t ~/.claude/settings.json.bak-thinking-* ~/.claude/settings.json.bak-thinking2-* 2>/dev/null | head -1)
if [ -n "$BAK" ] && [ -f "$BAK" ]; then
  cp "$BAK" ~/.claude/settings.json
  echo "  已还原自: $BAK"
else
  echo "  未找到 settings.json.bak-thinking-* 备份,跳过还原(settings 未改过或备份被清理)"
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
echo "  ~/.claude/settings.json 已还原(ANTHROPIC_BASE_URL 回官方直连 / ANTHROPIC_MODEL 回原值, token 未动)"
echo "  agents model 若已改为 per-role,需人工按需还原:"
echo "    .claude/agents/implementer.md + tester.md     -> model: inherit"
echo "    .claude/agents/reviewer.md + researcher.md    -> model: inherit"
echo "回退完成。"

exit 0
