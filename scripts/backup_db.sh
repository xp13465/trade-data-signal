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
    FAILED_DBS="${FAILED_DBS:-} $name"
    return 1
  fi
}

RC=0
FAILED_DBS=""
backup_one "$DBDIR/sentiment.db"        sentiment       || RC=1
backup_one "$DBDIR/etf_national_team.db" etf_national_team || RC=1

# 保留策略：删 RETAIN_DAYS 天前的 *_*.db 备份（按 mtime）
echo "-> 清理 ${RETAIN_DAYS} 天前的备份 ..." | tee -a "$LOG"
find "$BACKUP_DIR" -maxdepth 1 -name '*_*.db' -mtime "+${RETAIN_DAYS}" -print -delete 2>>"$LOG" \
  | tee -a "$LOG" | sed 's/^/  删除 /'

# 汇总当前备份数
N=$(find "$BACKUP_DIR" -maxdepth 1 -name '*_*.db' 2>/dev/null | wc -l | tr -d ' ')
echo "当前备份数：${N}（${BACKUP_DIR}）" | tee -a "$LOG"

# R2 异地备份（异地防盘毁：本地盘毁则 DB 与本地备份同失，R2 是底线）。
# 失败不影响本地备份退出码（RC 保持本地备份结果）。
if [ -f "$REPO/scripts/upload_r2.py" ]; then
  echo "-> 推 R2 异地备份 ..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/upload_r2.py" upload-db >> "$LOG" 2>&1 \
    || echo "⚠ R2 上传失败(不影响本地备份) rc=$?" | tee -a "$LOG"
else
  echo "⚠ $REPO/scripts/upload_r2.py 不存在，跳过 R2 异地备份" | tee -a "$LOG"
fi

echo "=== backup_db.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"

# 失败邮件告警(P0-3):本地 SQLite 热备失败(退出码非0)时 notify.py 发 severe 邮件
# + 写 data/alerts/latest.md(供下轮 Claude 开工优先排查)。复用 on_skip_notify.sh 模式。
# 环境变量 BACKUP_NOTIFY_DRY_RUN=1 时 --dry-run(验证用,不真发邮件)。
# 注意:R2 上传失败不计入 RC(上方软处理),此处只告警本地备份失败。
if [ "$RC" -ne 0 ] && [ -f "$REPO/scripts/notify.py" ]; then
  NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
  DRY_FLAG=""
  [ "${BACKUP_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
  BODY="SQLite 热备失败，退出码=${RC}。<br>时间：$NOW_STR<br>失败 DB：${FAILED_DBS}<br>日志：$LOG<br>本地备份目录：$BACKUP_DIR<br>请尽快排查（磁盘满 / DB 锁 / 文件损坏）。"
  echo "-> 发送备份失败告警邮件 ..." | tee -a "$LOG"
  "$PY" "$REPO/scripts/notify.py" "[备份失败]backup_db退出码$RC" "$BODY" --severe \
    --alert-issue "backup_db.sh 备份失败(rc=$RC,失败DB=${FAILED_DBS})" \
    --alert-log "$LOG" \
    $DRY_FLAG 2>>"$LOG" || true
fi

exit "$RC"
