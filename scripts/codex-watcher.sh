#!/bin/bash
# Codex 外部 reviewer 守护进程启动脚本
# 三种启动方式：
#   1. 手动：./scripts/codex-watcher.sh
#   2. cron：crontab -e 追加 * * * * * /Users/linhuichen/code/trade/scripts/codex-watcher.sh
#   3. launchd：(fallback) launchctl bootstrap gui/$(id -u) ...
set -e
cd /Users/linhuichen/code/trade
exec /usr/bin/python3 scripts/agent_inbox_watcher.py >> /dev/null 2>&1
