#!/bin/bash
set -e
PLIST_SRC="/Users/linhuichen/code/trade/scripts/com.trade.codex-watcher.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.trade.codex-watcher.plist"
LOG_DIR="/tmp/codex-reports"

echo "=== Codex Watcher Launchd 安装 ==="
echo ""
echo "[1/3] 准备目录..."
mkdir -p "$LOG_DIR"

echo "[2/3] 复制 plist 到 LaunchAgents..."
cp "$PLIST_SRC" "$PLIST_DST"
echo "  → $PLIST_DST"

echo "[3/3] 停止旧版服务并加载新服务..."
# 旧服务名可能不同，先尝试停止
/bin/launchctl bootout gui/$(id -u)/com.trade.codex-watcher 2>/dev/null || true
/bin/launchctl bootout gui/$(id -u)/com.trade.agent-inbox 2>/dev/null || true
/bin/launchctl unload "$PLIST_DST" 2>/dev/null || true

# 加载新服务
/bin/launchctl load "$PLIST_DST"
echo "  → 已加载"

echo ""
echo "=== 验证 ==="
/bin/launchctl list | grep "codex-watcher\|agent-inbox"
echo ""
echo "日志: $LOG_DIR/agent-inbox-launchd.log"
echo "状态: /bin/launchctl list | grep codex-watcher"
