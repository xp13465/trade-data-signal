#!/usr/bin/env bash
# verify_backup.sh - R2 备份恢复演练（只读零风险）。
#
# 确保异地备份真能恢复（2026-07-14 曾丢收盘快照，消除"备份不可用"隐患）。
# 流程：
#   1. 从 R2 signal-backup 桶下载最新 backup/<name>_YYYYMMDD.db[.gz]
#      - sentiment + etf_national_team（日频，download-db）
#      - stock_daily（日频，download-db；2026-10-29 才有第一份备份 ⇒ 无 key 时 SKIP，不告警）
#      - public_fund（周频/周日，2.76GiB 大库：download-db 是整对象 GET 进内存，云上 RAM
#        3719MB 必 OOM ⇒ 走 docs/scripts/restore_r2_db_backup.py 6 线程 Range GET 流式拉回）
#      注:只校验 backup/ 日备份(最新可恢复点)。weekly/ monthly/ 是归档层
#      (周/月备份副本,2026-07 新增),不参与每日恢复演练,仅作长期损坏兜底。
#   2. gunzip 解压（若 .gz）
#   3. sqlite3 PRAGMA integrity_check（完整性）
#   4. 关键表 COUNT(*) 抽样，与本地 data/*.db 对比（只读 mode=ro）
#      - 备份表=0 且 本地>0  -> 异常（备份空/损坏）
#      - 备份 > 本地         -> 异常（本地丢数据，07-14 丢快照场景）
#      - public_fund 追加型大表另加容差:备份 < 本地×0.95 -> 异常（备份过旧/被截断）
#   5. 新鲜度（stock_daily / public_fund）:最新备份日期必须 >= 今天-1，否则异常
#      （防"演练通过但备份早就断了"，同时覆盖 #312「台账在、R2 对象没了」）
#   5b.台账 HEAD 对账（public_fund）：台账日期 == 最新 key 日期时，HEAD Content-Length
#      必须 == 台账 gz_size（对象被截断/换过即异常）；无台账或日期不一致 = 前提不成立 SKIP。
#   6. 输出校验报告：PASS / FAIL / SKIP 三态 + 各表行数对比（跳过项在结论行点名，防假绿）
#   7. 失败调 notify.py --severe 告警（复用 backup_db.sh P0-3 模式）
#
# 全程只读，不动真实 data/*.db；临时目录(含 public_fund 演练输出)用完 trap 清理。
#
# 用法：bash scripts/verify_backup.sh
# 环境变量：
#   VERIFY_NOTIFY_DRY_RUN=1        notify.py --dry-run（验证用，不真发邮件）
#   VERIFY_PUBLIC_FUND=auto|1|0    public_fund 周频演练门控（默认 auto=仅周日；1=强制；0=关）
#   VERIFY_PUBLIC_FUND_MIN_KB      空间门限 KiB（默认 4718592 = 4.5GiB）
#   VERIFY_BACKUP_SKIP=1           由 backup_db.sh 判，整段跳过演练（既有开关，不属本脚本）
# 日志：data/logs/verify_backup_YYYYMMDD_HHMM.log
# 退出码：0=通过（含设计内 SKIP）；1=失败（下载/integrity/行数/新鲜度异常）
set -u

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
DBDIR="$REPO/data"
STAMP=$(date +%Y%m%d_%H%M)
# 新鲜度基准日（YYYYMMDD）。单测用 PATH 注入假 date 冻结运行日（L51），不在用例里写死日期。
TODAY=$(date +%Y%m%d)
LOGDIR="$REPO/data/logs"
LOG="$LOGDIR/verify_backup_${STAMP}.log"
TMPDIR=$(mktemp -d /tmp/verify-backup-XXXXXX)
# public_fund 演练输出目录（restore 脚本不自动清理 .gz + .db，共 3.51GiB 峰值）
PF_DIR="$TMPDIR/pf"
# 空间门限：演练峰值 3.51GiB（gz 0.75 + 解压后 2.76）+ 0.7GiB 余量给同期采集/日志
PF_MIN_KB="${VERIFY_PUBLIC_FUND_MIN_KB:-4718592}"

# #44 日志不可写隐患根治(同 s06_snapshot 先例): 日志目录/文件不可写时(磁盘满/权限),
# 非交互 bash 里 `2>>"$LOG"` 重定向失败会让 notify.py 告警命令根本不执行 → 告警静默跳过。
# 落到 /tmp fallback, 警告打到 stderr。
if ! mkdir -p "$LOGDIR" 2>/dev/null || [ ! -w "$LOGDIR" ] || ! ( : >> "$LOG" ) 2>/dev/null; then
  LOG="/tmp/verify_backup_${STAMP}.log"
  echo "$(date '+%F %T') [verify_backup] 警告: 日志 $LOGDIR/verify_backup_${STAMP}.log 不可写(磁盘满/权限), 改落 fallback $LOG" >&2
fi
# 临时目录用完即清（无论退出码）；不动真实 data/*.db。
# 显式带上 PF_DIR：restore_r2_db_backup.py 不自动清理输出（10-25 留过 6.2G /tmp 致当晚备份
# 因"空间不足"放弃，见 docs/ops/pfdb-r2-backup-20261025.md §7⑤）。
trap 'rm -rf "$PF_DIR" "$TMPDIR"' EXIT

echo "=== verify_backup.sh 开始 $(date '+%Y-%m-%d %H:%M:%S') ===" | tee "$LOG"
echo "临时目录: ${TMPDIR}（只读演练，不动真实 data/*.db）" | tee -a "$LOG"

RC=0

# ---- 0. 判 R2 上 backup/<name>_ 是否存在（分页/截断安全边界：日备份保留 7 天 ≤7 个对象）----
# 输出：最新备份日期 YYYYMMDD / NONE（无对象）/ ERR（LIST 失败，不许当成"无备份"）
# 复习 #338：stock_daily 现阶段 R2 零对象，upload_r2.py download-db 无 key 时 exit 非零
# （upload_r2.py:3462-3463）⇒ 直接下载会被误判成"下载失败"发 severe，必须先预判存在性。
# 注意：必须走 upload_r2 的 BACKUP_BUCKET（signal-backup2/环境 R2_BACKUP_BUCKET）。
# `upload_r2.py list` 子命令默认桶是 signal-data（upload_r2.py:5007），拿它查 backup/ 会
# 永远"无对象" ⇒ 假 SKIP。这里直接调库里的 _list_keys(bucket=BACKUP_BUCKET)，
# 判失败的依据是它自己的失败打印（upload_r2.py:2953「失败 status=」），不重复实现分页。
r2_latest_backup_date() {
  local name="$1" out
  if ! out=$("$PY" - "$REPO/scripts/upload_r2.py" "$name" 2>>"$LOG" <<'PYEOF'
import contextlib
import importlib.util
import io
import re
import sys

_spec = importlib.util.spec_from_file_location("upload_r2_vb", sys.argv[1])
_ur = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ur)
name = sys.argv[2]
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    keys = _ur._list_keys(f"backup/{name}_", bucket=_ur.BACKUP_BUCKET)
if not keys and "失败 status=" in _buf.getvalue():
    print("ERR")          # LIST 失败 ≠ 没有备份
    sys.exit(0)
dates = sorted({m.group(1) for k in keys
                for m in [re.search(r"(\d{8})\.db(?:\.gz)?$", k)] if m}, reverse=True)
print(dates[0] if dates else "NONE")
PYEOF
  ); then
    echo "ERR"
    return 0
  fi
  printf '%s\n' "$out" | tail -1
}

# ---- 1. 从 R2 下载最新备份到临时目录(失败 60s 后重试 1 次,仍失败才告警)----
# 下载函数:成功返回 0,失败返回 1;设全局 SENT_BACKUP/ETF_BACKUP/STOCK_BACKUP。
# upload_r2.py 内已 5 次指数退避重试(覆盖~15s),这里再加一层 60s 延迟兜底
# 长抖动(如 R2 SSLEOFError 持续 30s+ 才恢复,upload_r2.py 内 5 次重试不够覆盖)。
download_backups() {
  SENT_BACKUP=""
  ETF_BACKUP=""
  STOCK_BACKUP=""
  STOCK_STATUS=""
  local rc=0 st
  if ! SENT_BACKUP=$("$PY" "$REPO/scripts/upload_r2.py" download-db sentiment "$TMPDIR" 2>>"$LOG"); then
    echo "✗ sentiment 下载失败" | tee -a "$LOG"
    rc=1
  fi
  if ! ETF_BACKUP=$("$PY" "$REPO/scripts/upload_r2.py" download-db etf_national_team "$TMPDIR" 2>>"$LOG"); then
    echo "✗ etf_national_team 下载失败" | tee -a "$LOG"
    rc=1
  fi
  # stock_daily（#338）：先判存在性 ⇒ SKIP 是设计内过渡态（不告警不 FAIL）
  st=$(r2_latest_backup_date stock_daily)
  case "$st" in
    ERR)
      echo "✗ stock_daily R2 LIST 失败(无法判定是否有备份)" | tee -a "$LOG"
      rc=1
      ;;
    NONE)
      STOCK_STATUS="SKIP(尚无 stock_daily 备份)"
      echo "⤵ stock_daily: R2 上尚无备份 key，跳过(SKIP，不告警；第一份备份 2026-10-29 21:00)" | tee -a "$LOG"
      ;;
    *)
      if ! STOCK_BACKUP=$("$PY" "$REPO/scripts/upload_r2.py" download-db stock_daily "$TMPDIR" 2>>"$LOG"); then
        echo "✗ stock_daily 下载失败（R2 上有 key(date=$st) 但 GET 失败）" | tee -a "$LOG"
        STOCK_BACKUP=""
        rc=1
      fi
      ;;
  esac
  return $rc
}

echo "-> 从 R2(signal-backup) 下载最新备份 ..." | tee -a "$LOG"
download_backups
DL_RC=$?

# 第1次失败:sleep 60s 后重试 1 次(覆盖 R2 网络抖动/SSLEOFError 瞬时故障)
if [ "$DL_RC" -ne 0 ]; then
  echo "=== 第1次下载失败,60s 后重试 1 次(覆盖 R2 网络抖动)===" | tee -a "$LOG"
  sleep 60
  echo "-> 重试从 R2(signal-backup) 下载最新备份 ..." | tee -a "$LOG"
  download_backups
  DL_RC=$?
fi

# 第2次仍失败:无法演练,告警退出(不跑 integrity/行数)
if [ "$DL_RC" -ne 0 ]; then
  RC=1
  echo "=== 下载失败(60s 重试后仍失败),无法完成演练 ===" | tee -a "$LOG"
  NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
  DRY_FLAG=""
  [ "${VERIFY_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
  BODY="R2 备份下载失败(60s 重试后仍失败),无法完成恢复演练。<br>时间：$NOW_STR<br>日志：$LOG<br>请排查 R2 凭证/网络/signal-backup 桶。"
  [ -f "$REPO/scripts/notify.py" ] && \
    "$PY" "$REPO/scripts/notify.py" "[告警] verify_backup R2下载失败 $(date '+%m-%d %H:%M')" "$BODY" --severe \
      --from-prefix "[告警]" \
      --alert-issue "verify_backup.sh R2下载失败(无法演练恢复)" --alert-log "$LOG" $DRY_FLAG 2>&1 | tee -a "$LOG" || true
  exit 1
fi

# ---- 1b. public_fund 周频大库演练（#324；默认仅周日，避免每周 7 次拉 2.76GiB）----
# 失败/跳过语义：
#   SKIP(非周日 / VERIFY_PUBLIC_FUND=0)  -> 日志 + 结论行点名，不告警
#   SKIP(空间不足 <4.5GiB)               -> 日志 + severe（安全网被关掉要人处理）
#   FAIL(restore/integrity/行数/新鲜度)   -> 汇总到结论 → severe（沿用下方统一失败通道）
run_public_fund_drill() {
  PF_BACKUP=""
  PF_STATUS=""
  LEDGER_STATUS=""
  local mode="${VERIFY_PUBLIC_FUND:-auto}" avail_kb out rc
  case "$mode" in
    0)
      PF_STATUS="SKIP(已关闭 VERIFY_PUBLIC_FUND=0)"
      echo "⤵ public_fund: 已按 VERIFY_PUBLIC_FUND=0 关闭，跳过(SKIP)" | tee -a "$LOG"
      return 0
      ;;
    1) ;;
    auto) ;;
    *)
      echo "⚠ public_fund: VERIFY_PUBLIC_FUND='$mode' 非法(只接受 auto|1|0)，按 auto 处理" | tee -a "$LOG"
      mode="auto"
      ;;
  esac
  if [ "$mode" = "auto" ] && [ "$(date +%u)" != "7" ]; then
    PF_STATUS="SKIP(周频未到:非周日)"
    echo "⤵ public_fund: 周频演练仅周日跑（今天 $(date +%u)），跳过(SKIP)" | tee -a "$LOG"
    return 0
  fi
  avail_kb=$(df -Pk "$TMPDIR" 2>/dev/null | awk 'NR==2 {print $4}')
  if [ -z "${avail_kb:-}" ] || [ "$avail_kb" -lt "$PF_MIN_KB" ]; then
    PF_STATUS="SKIP(空间不足 <$((PF_MIN_KB / 1024))MiB, 可用 ${avail_kb:-?}KiB)"
    echo "⤵ public_fund: 空间不足(可用 ${avail_kb:-?}KiB < 门限 ${PF_MIN_KB}KiB)，跳过(SKIP) —— 这是安全网被关，发告警" | tee -a "$LOG"
    NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
    DRY_FLAG=""
    [ "${VERIFY_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
    BODY="public_fund 周频恢复演练因临时空间不足被跳过，大库(2.76GiB)恢复验证已失效。<br>时间：$NOW_STR<br>可用：${avail_kb:-?}KiB（门限 ${PF_MIN_KB}KiB）<br>日志：$LOG<br>请清理磁盘后手动跑：VERIFY_PUBLIC_FUND=1 bash scripts/verify_backup.sh"
    [ -f "$REPO/scripts/notify.py" ] && \
      "$PY" "$REPO/scripts/notify.py" "[告警] verify_backup public_fund 演练空间不足 $(date '+%m-%d %H:%M')" "$BODY" --severe \
        --from-prefix "[告警]" \
        --alert-issue "verify_backup.sh public_fund 演练空间不足被跳过" --alert-log "$LOG" $DRY_FLAG 2>&1 | tee -a "$LOG" || true
    return 0
  fi
  echo "-> public_fund 周频恢复演练（约 804MB gz / 2.76GiB 解压，6 线程；可用 ${avail_kb}KiB）..." | tee -a "$LOG"
  mkdir -p "$PF_DIR" || { PF_STATUS="FAIL(建临时目录失败 $PF_DIR)"; echo "✗ public_fund: 建临时目录失败" | tee -a "$LOG"; return 1; }
  # 必须显式传 REPO/GIT_REPO：repo_paths.sh 只 assign 不 export(repo_paths.sh:34)，
  # restore 脚本 setdefault("REPO", <git仓>) 会指到 git 仓，而 .env 在 <REPO>/.env / <GIT_REPO>/.env。
  out=$(REPO="$REPO" GIT_REPO="$GIT_REPO" "$PY" "$GIT_REPO/docs/scripts/restore_r2_db_backup.py" \
        --name public_fund --out-dir "$PF_DIR" --threads 6 2>>"$LOG")
  rc=$?
  if [ -f "$PF_DIR/result.json" ]; then
    cp "$PF_DIR/result.json" "$LOGDIR/verify_backup_pf_result_${STAMP}.json" 2>/dev/null \
      && echo "  public_fund result.json 落档: $LOGDIR/verify_backup_pf_result_${STAMP}.json" | tee -a "$LOG"
  fi
  if [ "$rc" -ne 0 ] || ! printf '%s\n' "$out" | grep -q '^RESTORE PASS$'; then
    PF_STATUS="FAIL(restore rc=$rc)"
    echo "✗ public_fund: restore_r2_db_backup.py 失败 rc=${rc}（明细见 result.json）" | tee -a "$LOG"
    return 1
  fi
  PF_BACKUP=$(printf '%s\n' "$out" | tail -1)
  if [ ! -f "$PF_BACKUP" ]; then
    PF_STATUS="FAIL(restore 未产出 .db: $PF_BACKUP)"
    echo "✗ public_fund: restore 未产出 .db" | tee -a "$LOG"
    PF_BACKUP=""
    return 1
  fi
  # ---- 台账 ↔ R2 HEAD 长度对账（#324 断言④）----
  # 依据 upload_r2.py:3304-3310：public_fund 上传成功且源库未被写入时写台账
  # data/.r2_db_backup_state.json = {size, mtime_ns, date, key, gz_size}。
  # 该断言只在「台账日期 == 最新 daily key 日期」时有可比性（否则台账是上一轮）；
  # 无台账/日期不一致 = 前提不成立 ⇒ SKIP 且点名（不是备份坏了，不 FAIL）。
  local ledger="$REPO/data/.r2_db_backup_state.json" rec ldate lgz lkey latest hl hst hlen
  if [ ! -f "$ledger" ]; then
    LEDGER_STATUS="SKIP(无台账 data/.r2_db_backup_state.json)"
  else
    rec=$("$PY" - "$ledger" <<'PYEOF'
import json, sys
try:
    st = (json.load(open(sys.argv[1])).get("public_fund.db") or {})
except Exception:
    st = {}
print("%s|%s|%s" % (st.get("date", ""), st.get("gz_size", ""), st.get("key", "")))
PYEOF
)
    ldate=${rec%%|*}; rec=${rec#*|}; lgz=${rec%%|*}; lkey=${rec#*|}
    if [ -z "$ldate" ] || [ -z "$lgz" ] || [ -z "$lkey" ]; then
      LEDGER_STATUS="SKIP(台账无 public_fund.db 记录或字段不全)"
    else
      latest=$(r2_latest_backup_date public_fund)
      if [ "$latest" = "ERR" ] || [ -z "$latest" ] || [ "$latest" = "NONE" ]; then
        LEDGER_STATUS="FAIL(无法判定最新 key 日期: $latest)"
      elif [ "$ldate" != "$latest" ]; then
        LEDGER_STATUS="SKIP(台账日期 $ldate != 最新 key 日期 $latest)"
      else
        # HEAD 取 Content-Length（不下载 body；s3_head 内部 5 次退避重试，失败返回 0/None）
        hl=$("$PY" - "$REPO/scripts/upload_r2.py" "$lkey" <<'PYEOF'
import importlib.util, sys
_spec = importlib.util.spec_from_file_location("upload_r2_vb", sys.argv[1])
_ur = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_ur)
status, _etag, clen = _ur.s3_head(sys.argv[2], bucket=_ur.BACKUP_BUCKET, with_len=True)
print("%s|%s" % (status, clen if clen is not None else ""))
PYEOF
)
        hst=${hl%%|*}; hlen=${hl#*|}
        if [ "$hst" != "200" ] || [ -z "$hlen" ]; then
          LEDGER_STATUS="FAIL(HEAD $lkey status=$hst)"
        elif [ "$hlen" != "$lgz" ]; then
          LEDGER_STATUS="FAIL(HEAD 长度 $hlen != 台账 gz_size $lgz)"
        else
          LEDGER_STATUS="OK($lkey 长度 $hlen == 台账 gz_size)"
        fi
      fi
    fi
  fi
  echo "  台账 HEAD 对账: $LEDGER_STATUS" | tee -a "$LOG"
  case "$LEDGER_STATUS" in
    FAIL*)
      PF_STATUS="FAIL(台账 HEAD 对账: $LEDGER_STATUS)"
      return 1
      ;;
  esac
  PF_STATUS="OK"
  return 0
}

run_public_fund_drill
PF_RC=$?

echo "下载完成：" | tee -a "$LOG"
echo "  sentiment:         $SENT_BACKUP" | tee -a "$LOG"
echo "  etf_national_team: $ETF_BACKUP" | tee -a "$LOG"
echo "  stock_daily:       ${STOCK_BACKUP:-${STOCK_STATUS:-未执行}}" | tee -a "$LOG"
echo "  public_fund:       ${PF_BACKUP:-${PF_STATUS:-未执行}}" | tee -a "$LOG"

# 跳过/失败的库（结论行必须点名，防 L49 假绿：只写"全 ok"而实际漏验）
SKIP_NOTES=""
[ -n "${STOCK_STATUS:-}" ] && SKIP_NOTES="${SKIP_NOTES:+$SKIP_NOTES;}stock_daily=${STOCK_STATUS}"
[ -n "${PF_STATUS:-}" ] && [ "$PF_STATUS" != "OK" ] && SKIP_NOTES="${SKIP_NOTES:+$SKIP_NOTES;}public_fund=${PF_STATUS}"
case "${LEDGER_STATUS:-}" in
  SKIP*) SKIP_NOTES="${SKIP_NOTES:+$SKIP_NOTES;}public_fund_ledger=${LEDGER_STATUS}" ;;
esac

# ---- 2-5. integrity_check + 新鲜度 + 行数对比（python 一次完成，只读 mode=ro）----
# 参数(6 个)：备份sent 备份etf 备份stock 备份pf 本地库目录 data/ 跳过项说明(name=STATUS;...)
# 输出：报告到 stdout，首行 VERIFY_OK=0/1 供 bash 解析
VERIFY_REPORT=$(VERIFY_TODAY="$TODAY" "$PY" - "$SENT_BACKUP" "$ETF_BACKUP" "$STOCK_BACKUP" "$PF_BACKUP" "$DBDIR" "$SKIP_NOTES" 2>>"$LOG" <<'PYEOF'
import datetime
import os
import re
import sqlite3
import sys

backup_sent, backup_etf, backup_stock, backup_pf, dbdir, notes = sys.argv[1:7]
TODAY = os.environ.get("VERIFY_TODAY", "")

# (名称, 备份db, 关键表清单, 行数容差下限)
# 旧两库 ratio=None = 原口径（备份=0 且本地>0 FAIL；备份>本地 FAIL）。
# public_fund ratio=0.95：追加型大表容忍日增，但不容忍差 5% 以上。
#   实测依据（2026-10-28 定值）：本地 mac 库(2026-09-12) vs 云上实测(2026-10-28, 见
#   docs/ops/backup-drill-20261028.md)：45 天行数差 ÷ 45 ≒ 0.06%/天(fund_daily_nav)、
#   1.04%/天(fund_purchase_status/fund_rating)、1.04%/天(fund_performance)、0.05%/天(fund_basic)
#   ⇒ 最大 1.04%/天；5% ≈ 4.8 天天增，而周频 + 新鲜度门(≤今天-1) 最多只落后 1 天 ⇒ 容差足够。
CHECKS = []
for name, bdb, tables, ratio in (
    ("sentiment", backup_sent,
     ["score_daily", "daily_metric", "signal_daily", "index_daily",
      "industry_width_daily", "futures_position", "futures_accuracy", "collect_log"], None),
    ("etf_national_team", backup_etf,
     ["etf_daily", "etf_signal", "etf_holder_quarterly", "national_team_holders"], None),
    ("stock_daily", backup_stock,
     ["baostock_daily_raw", "fapi_daily_raw", "mootdx_daily_raw"], None),
    ("public_fund", backup_pf,
     ["fund_daily_nav", "fund_purchase_status", "fund_performance",
      "fund_rating", "fund_basic"], 0.95),
):
    if bdb:
        CHECKS.append((name, bdb, os.path.join(dbdir, name + ".db"), tables, ratio))

# stock_daily / public_fund 要求"最新备份日期 >= 今天-1"（sentiment/etf 由日频上传即时校验）
FRESH_CHECKS = {"stock_daily", "public_fund"}


def connect_ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def table_count(con, tbl):
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
    except sqlite3.OperationalError:
        return None  # 表不存在


def backup_date(path):
    m = re.search(r"(\d{8})\.db(?:\.gz)?$", os.path.basename(path))
    return m.group(1) if m else None


lines = []
overall_ok = 1 if CHECKS else 0
if not CHECKS:
    lines.append("=== 未取得任何库的备份做校验（全部 SKIP/失败）===")

# --- integrity_check ---
lines.append("=== integrity_check（完整性）===")
for name, bdb, _ldb, _tables, _ratio in CHECKS:
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

# --- 新鲜度 ---
lines.append("")
lines.append("=== 新鲜度（最新备份日期 >= 今天-1）===")
fresh_seen = False
for name, bdb, _ldb, _tables, _ratio in CHECKS:
    if name not in FRESH_CHECKS:
        continue
    fresh_seen = True
    d = backup_date(bdb)
    if not TODAY or not d:
        lines.append(f"  {name}: 无法判定日期（{os.path.basename(bdb)}，TODAY={TODAY or '空'}）  [✗FAIL]")
        overall_ok = 0
        continue
    lag = (datetime.datetime.strptime(TODAY, "%Y%m%d").date()
           - datetime.datetime.strptime(d, "%Y%m%d").date()).days
    ok = lag <= 1
    lines.append(f"  {name}: 最新备份 {d}（落后 {lag} 天）  [{'OK' if ok else '✗FAIL 备份过旧'}]")
    if not ok:
        overall_ok = 0
if not fresh_seen:
    lines.append("  （无 stock_daily / public_fund 备份参与本次演练）")

# --- 行数对比 ---
lines.append("")
lines.append("=== 行数对比（备份 vs 本地，只读）===")
for name, bdb, ldb, tables, ratio in CHECKS:
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
        # 判断：备份=0且本地>0 -> 备份空/损坏；备份>本地 -> 本地丢数据；
        #       public_fund 备份 < 本地×0.95 -> 备份过旧/被截断
        if bcnt == 0 and lcnt > 0:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [✗FAIL 备份空]")
            overall_ok = 0
        elif bcnt > lcnt:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [✗FAIL 本地丢数据]")
            overall_ok = 0
        elif ratio is not None and lcnt > 0 and bcnt < lcnt * ratio:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [✗FAIL 备份过旧/被截断 <本地×{ratio:.2f}]")
            overall_ok = 0
        else:
            lines.append(f"  {tbl:28s} 备份={bcnt}  本地={lcnt}  [OK]")
    bcon.close()
    lcon.close()

# --- 跳过项点名（三态结论；SKIP 不算失败，但不许写成"全 ok"）---
skip_notes = [n.strip() for n in notes.split(";") if n.strip()]
if skip_notes:
    lines.append("")
    lines.append("=== 跳过/失败项 ===")
    for n in skip_notes:
        lines.append(f"  {n}")
        if "=FAIL" in n:
            overall_ok = 0

lines.append("")
covered = ",".join(c[0] for c in CHECKS) if CHECKS else "无"
skip_txt = f"；跳过: {'; '.join(skip_notes)}" if skip_notes else ""
if overall_ok:
    lines.append(f"=== 结论：✓ 通过（integrity 逐库 ok + 关键表行数正常；已覆盖: {covered}{skip_txt}）===")
else:
    lines.append(f"=== 结论：✗ 失败（见上方 FAIL 项；已覆盖: {covered}{skip_txt}）===")

# 首行输出标记供 bash 解析
print(f"VERIFY_OK={overall_ok}")
print("\n".join(lines))
PYEOF
)

echo "$VERIFY_REPORT" | tee -a "$LOG"

# 解析结果
VERIFY_OK=$(printf '%s\n' "$VERIFY_REPORT" | head -1 | sed 's/^VERIFY_OK=//')

# public_fund 演练产物（gz 0.75GiB + db 2.76GiB）校验完立即清，不等 EXIT trap
rm -rf "$PF_DIR"

# ---- 6. 失败告警 ----
if [ "$VERIFY_OK" != "1" ] || [ "$PF_RC" -ne 0 ]; then
  RC=1
  NOW_STR=$(date '+%Y-%m-%d %H:%M:%S')
  DRY_FLAG=""
  [ "${VERIFY_NOTIFY_DRY_RUN:-0}" = "1" ] && DRY_FLAG="--dry-run"
  BODY="R2 备份恢复演练失败（integrity/行数/新鲜度异常或 public_fund 恢复失败）。<br>时间：$NOW_STR<br>日志：$LOG<br>临时目录：${TMPDIR}（已清理）<br>请排查：备份是否损坏/本地是否丢数据/R2 上传是否正常。"
  echo "-> 发送演练失败告警邮件 ..." | tee -a "$LOG"
  [ -f "$REPO/scripts/notify.py" ] && \
    "$PY" "$REPO/scripts/notify.py" "[告警] verify_backup 校验失败 $(date '+%m-%d %H:%M')" "$BODY" --severe \
      --from-prefix "[告警]" \
      --alert-issue "verify_backup.sh 恢复演练失败(integrity/行数异常)" --alert-log "$LOG" \
      $DRY_FLAG 2>&1 | tee -a "$LOG" || true
fi

echo "=== verify_backup.sh 结束 $(date '+%Y-%m-%d %H:%M:%S') 退出码=$RC ===" | tee -a "$LOG"
exit "$RC"