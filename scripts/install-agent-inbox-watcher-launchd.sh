#!/bin/bash
set -e
PLIST_SRC=$(cd "$(dirname "$0")/.." && pwd)/launchd/com.trade.agent-inbox-watcher.plist
PLIST_DST="$HOME/Library/LaunchAgents/com.trade.agent-inbox-watcher.plist"
LABEL="com.trade.agent-inbox-watcher"

echo "=== Agent Inbox Watcher Launchd 安装 ==="
mkdir -p "$HOME/Library/LaunchAgents"

# 停旧服务(兼容历史 label com.trade.codex-watcher)
/bin/launchctl bootout gui/$(id -u)/"$LABEL" 2>/dev/null || true
/bin/launchctl bootout gui/$(id -u)/com.trade.codex-watcher 2>/dev/null || true
/bin/launchctl unload "$PLIST_DST" 2>/dev/null || true
sleep 1

cp "$PLIST_SRC" "$PLIST_DST"
/bin/launchctl load "$PLIST_DST"

echo ""
/bin/launchctl list | grep "$LABEL" || true
echo "日志: /Users/linhuichen/code/trade-data/data/logs/agent_inbox_watcher_launchd.{log,err}"
