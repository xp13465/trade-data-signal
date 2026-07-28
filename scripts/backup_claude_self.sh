#!/bin/bash
# Claude 自我备份（launchd 每天 03:17 调）
# 备份内容: memory(+MEMORY.md索引) + CLAUDE.md 工作模式 + NOTES.md/TASKS.md 落档
# 产出: ~/.claude/backups/daily/claude-self-YYYYMMDD.tar.gz，保留 30 天滚动
BACKUP_DIR="$HOME/.claude/backups/daily"
mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d)
OUT="$BACKUP_DIR/claude-self-$TS.tar.gz"
MEMORY_DIR="$HOME/.claude/projects/-Users-linhuichen-code-trade/memory"
TRADE_DIR="/Users/linhuichen/code/trade"
tar czf "$OUT" \
  -C "$HOME/.claude/projects/-Users-linhuichen-code-trade" memory \
  -C "$TRADE_DIR" CLAUDE.md NOTES.md TASKS.md 2>/dev/null
# 保留 30 天滚动
find "$BACKUP_DIR" -name 'claude-self-*.tar.gz' -mtime +30 -delete 2>/dev/null
SIZE=$(ls -lh "$OUT" 2>/dev/null | awk '{print $5}')
echo "[$(date '+%F %T')] Claude 自我备份完成: $OUT ($SIZE)"
