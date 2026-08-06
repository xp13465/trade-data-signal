#!/bin/bash
# Claude 自我备份（launchd 每天 03:17 调）
# 备份内容: memory(+MEMORY.md索引) + CLAUDE.md 工作模式 + NOTES.md/TASKS.md 落档
# 产出: ~/.claude/backups/daily/claude-self-YYYYMMDD.tar.gz，保留 30 天滚动
# 云端: 推 R2 signal-backup 私有桶 claude-backup/ 前缀(异地防盘毁,R2 失败不阻塞本地备份)
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
# R2 云端异地备份(本地已成功,R2 是额外云备份,失败不阻塞)
PY="$TRADE_DIR/.venv/bin/python"
UPLOAD_PY="$TRADE_DIR/scripts/upload_r2.py"
if [ -x "$PY" ] && [ -r "$UPLOAD_PY" ]; then
  if "$PY" "$UPLOAD_PY" upload-claude-backup "$OUT" 2>&1; then
    echo "[$(date '+%F %T')] R2 云端备份成功: signal-backup/claude-backup/claude-self-$TS.tar.gz"
  else
    echo "[$(date '+%F %T')] ⚠ R2 云端备份失败(本地备份已成功,不阻塞)" >&2
  fi
else
  echo "[$(date '+%F %T')] ⚠ 跳过 R2 上传($PY 或 $UPLOAD_PY 不存在)" >&2
fi
