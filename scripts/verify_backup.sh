#!/usr/bin/env bash
# verify_backup.sh - R2 备份恢复演练（只读零风险）。
#
# 确保异地备份真能恢复（2026-07-14 曾丢收盘快照，消除"备份不可用"隐患）。
# 流程：
#   1. 从 R2 signal-backup 桶下载最新 backup/<name>_YYYYMMDD.db[.gz]
#      （sentiment + etf_national_team 两个 DB）到临时目录
#   2. gunzip 解压（若 .gz）
#   3. sqlite3 PRAGMA integrity_check（完整性）
#   4. 关键表 COUNT(*) 抽样，与本地 data/*.db 对比（只读 mode=ro）
#      - 备份表=0 且 本地>0  -> 异常（备份空/损坏）
#      - 备份 > 本地         -> 异常（本地丢数据，07-14 丢快照场景）
#   5. 输出校验报告：通过/失败 + 各表行数对比
#   6. 失败调 notify.py --severe 告警（复用 backup_db.sh P0-3 模式）
#
# 全程只读，不动真实 data/*.db；临时目录用完 trap 清理。
#
# 用法：bash scripts/verify_backup.sh
# 环境变量：VERIFY_NOTIFY_DRY_RUN=1 时 notify.py --dry-run（验证用，不真发邮件）
# 日志：data/logs/verify_backup_YYYYMMDD_HHMM.log
# 退出码：0=通过；1=失败（下载/integrity/行数异常）
set -u

REPO="${REPO:-/Users/linhuichen/code/trade}"
PY="$REPO/.venv/bin/python"
DBDIR="$REPO/data"
STAMP=$(date +%Y%m%d_%H%M)
LOGDIR="$REPO/data/logs"
LOG="$LOGDIR/verify_backup_${STAMP}.log"
TMPDIR=$(mktemp -d /tmp/verify-backup-XXXXXX)

mkdir -p "$LOGDIR"
# 临时目录用完即清（无论退出码）；不动真实 data/*.db
trap 'rm -rf "$TMPDIR"' EXIT

echo "=== verify_backup.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
echo "临时目录: ${TMPDIR}（只读演练，不动真实 data/*.db）" | tee -a "$LOG"

RC=0

# ---- 1. 从 R2 下载最新备份到临时目录 ----
echo "-> 从 R2(signal-backup) 下载最新备份 ..." | tee -a "$LOG"
SENT_BACKUP=""
ETF_BACKUP=""
if ! SENT_BACKUP=$("$PY" "$REPO/scripts/upload_r2.py" download-db sentiment "$TMPDIR" 2>>"$LOG"); then
  echo "✗ sentiment 下载失败" | tee -a "$LOG"
  RC=1
fi
if ! ETF_BACKUP=$("$PY" "$REPO/scripts/upload_r2.py" download-db etf_national_team "$TMPDIR" 2>>"$LOG"); then
  echo "✗ etf_national_team 下载失败" | tee -a "$LOG"
  RC=1
fi

# 下载失败：无法演练，直接告警退出（不跑 integrity/行数）
if [ "$RC" -ne 0 ]; then
  echo "=== 下载失败，无法完成演练 ===" | tee -a "$LOG"
  NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
  DRY_FLAG=""
  [ "${VERIFY_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
  BODY="R2 备份下载失败，无法完成恢复演练。<br>时间：$NOW_STR<br>日志：$LOG<br>请排查 R2 凭证/网络/signal-backup 桶。"
  [ -f "$REPO/scripts/notify.py" ] && \
    "$PY" "$REPO/scripts/notify.py" "[备份演练失败]verify_backup下载失败" "$BODY" --severe \
      --alert-issue "verify_backup.sh R2下载失败(无法演练恢复)" --alert-log "$LOG" $DRY_FLAG 2>>"$LOG" || true
  exit 1
fi

echo "下载完成：" | tee -a "$LOG"
echo "  sentiment:         $SENT_BACKUP" | tee -a "$LOG"
echo "  etf_national_team: $ETF_BACKUP" | tee -a "$LOG"

# ---- 2-5. integrity_check + 行数对比（python 一次完成，只读 mode=ro）----
# 参数：备份sentiment 备份etf 本地sentiment 本地etf
# 输出：报告到 stdout，首行 VERIFY_OK=0/1 供 bash 解析
VERIFY_REPORT=$("$PY" - "$SENT_BACKUP" "$ETF_BACKUP" "$DBDIR/sentiment.db" "$DBDIR/etf_national_team.db" 2>>"$LOG" <<'PYEOF'
import sqlite3, sys

backup_sent, backup_etf, local_sent, local_etf = sys.argv[1:5]

# (名称, 备份db, 本地db, 关键表清单)
CHECKS = [
    ("sentiment", backup_sent, local_sent,
     ["score_daily", "daily_metric", "signal_daily", "index_daily",
      "industry_width_daily", "futures_position", "futures_accuracy", "collect_log"]),
    ("etf_national_team", backup_etf, local_etf,
     ["etf_daily", "etf_signal", "etf_holder_quarterly", "national_team_holders"]),
]


def connect_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def table_count(con, tbl):
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
    except sqlite3.OperationalError:
        return None  # 表不存在


lines = []
overall_ok = 1

# --- integrity_check ---
lines.append("=== integrity_check（完整性）===")
for name, bdb, ldb, _ in CHECKS:
    try:
        bcon = connect_ro(bdb)
        ic = bcon.execute("PRAGMA integrity_check").fetchone()[0]
        bcon.close()
    except Exception as e:
        ic = f"ERROR: {e}"
        overall_ok = 0
    flag = "OK" if ic == "ok" else "✗FAIL"
    lines.append(f"  {name}: {ic}  [{flag}]")
    if ic != "ok":
        overall_ok = 0

# --- 行数对比 ---
lines.append("")
lines.append("=== 行数对比（备份 vs 本地，只读）===")
for name, bdb, ldb, tables in CHECKS:
    lines.append(f"--- {name} ---")
    try:
        bcon = connect_ro(bdb)
        lcon = connect_ro(ldb)
    except Exception as e:
        lines.append(f"  ✗ 连接失败: {e}")
        overall_ok = 0
        continue
    for tbl in tables:
        bcnt = table_count(bcon, tbl)
        lcnt = table_count(lcon, tbl)
        if bcnt is None:
            lines.append(f"  {tbl:28s} 备份表缺失  本地={lcnt}  [✗FAIL]")
            overall_ok = 0
            continue
        if lcnt is None:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地表缺失  [✗FAIL]")
            overall_ok = 0
            continue
        # 判断：备份=0且本地>0 -> 备份空/损坏；备份>本地 -> 本地丢数据
        if bcnt == 0 and lcnt > 0:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [✗FAIL 备份空]")
            overall_ok = 0
        elif bcnt > lcnt:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [✗FAIL 本地丢数据]")
            overall_ok = 0
        else:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [OK]")
    bcon.close()
    lcon.close()

lines.append("")
if overall_ok:
    lines.append("=== 结论：✓ 通过（integrity 全 ok + 关键表行数正常）===")
else:
    lines.append("=== 结论：✗ 失败（见上方 FAIL 项）===")

# 首行输出标记供 bash 解析
print(f"VERIFY_OK={overall_ok}")
print("\n".join(lines))
PYEOF
)

echo "$VERIFY_REPORT" | tee -a "$LOG"

# 解析结果
VERIFY_OK=$(printf '%s\n' "$VERIFY_REPORT" | head -1 | sed 's/^VERIFY_OK=//')

# ---- 6. 失败告警 ----
if [ "$VERIFY_OK" != "1" ]; then
  RC=1
  NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
  DRY_FLAG=""
  [ "${VERIFY_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
  BODY="R2 备份恢复演练失败（integrity 或行数对比异常）。<br>时间：$NOW_STR<br>日志：$LOG<br>临时目录：${TMPDIR}（已清理）<br>请排查：备份是否损坏/本地是否丢数据/R2 上传是否正常。"
  echo "-> 发送演练失败告警邮件 ..." | tee -a "$LOG"
  [ -f "$REPO/scripts/notify.py" ] && \
    "$PY" "$REPO/scripts/notify.py" "[备份演练失败]verify_backup异常" "$BODY" --severe \
      --alert-issue "verify_backup.sh 恢复演练失败(integrity/行数异常)" --alert-log "$LOG" \
      $DRY_FLAG 2>>"$LOG" || true
fi

echo "=== verify_backup.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"
exit "$RC"
