#!/usr/bin/env bash
# backup_db.sh - 每日 SQLite 热备 sentiment.db + etf_national_team.db 到独立路径。
#
# 用 Python sqlite3.Connection.backup()（SQLite 在线 backup API）做热备：
#   - 不锁库、不阻塞读写（WAL 模式下也能拿到一致快照）
#   - 比直接 cp 文件安全（cp 可能拷到半写状态）
#
# 备份路径：默认 data/backups/（已 .gitignore，不进 git）。
#   外置盘：BACKUP_DIR=/Volumes/<盘>/trade_backup bash scripts/backup_db.sh
# 保留：默认 RETAIN_DAYS=14 天，超出自动删（按文件 mtime）。
# 日志：data/logs/backup_db_YYYYMMDD_HHMM.log
#
# 用法：bash scripts/backup_db.sh
# 退出码：0=全部成功；1=部分/全部失败（仍继续跑完所有 DB，最后报）。
set -u

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
DBDIR="$REPO/data"
BACKUP_DIR="${BACKUP_DIR:-$DBDIR/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
STAMP=$(date +%Y%m%d_%H%M)
LOGDIR="$REPO/data/logs"
LOG="$LOGDIR/backup_db_${STAMP}.log"

mkdir -p "$BACKUP_DIR" "$LOGDIR"

echo "=== backup_db.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
echo "BACKUP_DIR=$BACKUP_DIR RETAIN_DAYS=$RETAIN_DAYS" | tee -a "$LOG"

# 备份单个 DB：$1=源 db 路径 $2=备份名（不含扩展）
backup_one() {
  local src="$1" name="$2"
  if [ ! -f "$src" ]; then
    echo "⚠ $src 不存在，跳过" | tee -a "$LOG"
    return 0
  fi
  local out="$BACKUP_DIR/${name}_${STAMP}.db"
  local src_sz
  src_sz=$(stat -f%z "$src" 2>/dev/null || stat -c%s "$src" 2>/dev/null)
  echo "-> .backup $src ($src_sz bytes) -> $out" | tee -a "$LOG"
  if "$PY" - "$src" "$out" 2>>"$LOG" <<'PYEOF'
import sqlite3, sys
src_path, dst_path = sys.argv[1], sys.argv[2]
src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)
try:
    src.backup(dst)           # 在线热备，一致快照
finally:
    dst.close()
    src.close()
PYEOF
  then
    local out_sz
    out_sz=$(stat -f%z "$out" 2>/dev/null || stat -c%s "$out" 2>/dev/null)
    echo "✓ $name 备份完成 ($out_sz bytes)" | tee -a "$LOG"
    return 0
  else
    echo "✗ $name 备份失败" | tee -a "$LOG"
    rm -f "$out" 2>/dev/null
    return 1
  fi
}

RC=0
backup_one "$DBDIR/sentiment.db"        sentiment       || RC=1
backup_one "$DBDIR/etf_national_team.db" etf_national_team || RC=1

# 保留策略：删 RETAIN_DAYS 天前的 *_*.db 备份（按 mtime）
echo "-> 清理 ${RETAIN_DAYS} 天前的备份 ..." | tee -a "$LOG"
find "$BACKUP_DIR" -maxdepth 1 -name '*_*.db' -mtime "+${RETAIN_DAYS}" -print -delete 2>>"$LOG" \
  | tee -a "$LOG" | sed 's/^/  删除 /'

# 汇总当前备份数
N=$(find "$BACKUP_DIR" -maxdepth 1 -name '*_*.db' 2>/dev/null | wc -l | tr -d ' ')
echo "当前备份数：${N}（${BACKUP_DIR}）" | tee -a "$LOG"
echo "=== backup_db.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"
exit "$RC"
