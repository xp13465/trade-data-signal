#!/bin/bash
# sync_fund_score_to_d1.sh - 场外基金评分全量同步到 CF D1（#79 方案C step3, 2026-08-22）
#
# 目的: 把本地 public_fund.db fund_score 表【最新 score_date 全量】(≈27418 只)
#       同步到 Cloudflare D1 数据库 trade-fund-score, 供 worker/fund_score.js
#       提供 /api/fund_score 分页/筛选/排序/搜索接口（前端场外基金 tab 全量化）。
# 方法口径: 全量替换（DELETE 后重插），幂等可重跑；只同步最新 score_date 一个分区；
#       JOIN fund_basic 带出扩展字段(fund_company/fund_manager/setup_date/scale/
#       management_fee/custody_fee/purchase_fee/strategy/benchmark_text)，与
#       export_fund_score.py (#79 step1) 字段口径一致。
# 输入: /Users/linhuichen/code/trade-data/data/public_fund.db (fund_score + fund_basic)
# 输出: CF D1 trade-fund-score.fund_score 表（远程，wrangler d1 execute --remote）
# 复现: bash /Users/linhuichen/code/trade-data/scripts/sync_fund_score_to_d1.sh
#       （或主仓库 bash scripts/sync_fund_score_to_d1.sh，REPO 环境变量可覆盖）
#       DRY_RUN=1 ... （只生成导入包不推 D1, 本机可跑: 不预检凭据、不写失败状态）
# 调用方: pf_score_daily.sh / pf_score_weekly.sh 末尾（评分导出后自动同步）
# 注意: 需要 wrangler 已登录（npx wrangler whoami 可验）；D1 database_id 见 wrangler.jsonc。
#
# ── 2026-10-26 一表一文件 · 一次导入（D1 导入提速 + 单语句字节封顶）──────────────
# 与 sync_fund_screener_to_d1.sh 同一改法: 旧版每 80 行一个文件、逐文件 wrangler 调用
#   (6.35 秒/次 × 347 次 ≈ 37 分钟, 其中 D1 真正执行只占 0.19%), 改为整表合成**一个文件
#   一次导入**; 切批从「只按 80 行」改为**按实际 UTF-8 字节**(默认单条 ≤60,000, 官方单语句
#   上限 100,000 字节), 生成完硬断言 max_stmt_bytes < 90,000, 超了生成阶段直接失败。
# 可调环境变量: D1_SPLIT_MODE=legacy 回退旧多文件模式 / D1_MAX_STMT_BYTES /
#   D1_MAX_STMT_BYTES_ASSERT / D1_RETRY_DELAYS="30 90" / D1_RETRY_BUDGET=360 /
#   D1_EXEC_TIMEOUT_SEC=300 / D1_VERIFY_TIMEOUT_SEC=60
#   (详表见 docs/ops/pfscore-d1-single-import-20261026.md)
# 预算为什么是 360s: daily 的墙只有 10 分钟(TimeoutStartUSec=10min, 10-23/10-25 实测
#   16:10 被杀), 预算必须远小于墙 —— 旧默认 1800s 永远用不到(systemd 先杀整组)。
#   单次 `wrangler d1 execute` 另加 300s 上限, 防止进程卡死挂到墙。
# 注意: 一个导入文件 = 一个事务 ⇒ 文件里不写 BEGIN/COMMIT。
#
# ── #275 失败可见化（2026-10-22，根治「39 次失败零告警」）──────────────────────
# 背景：2026-10-01~10-22 云上 wrangler 未登录，本脚本连续 39 次失败且调用方只 echo 一行
#   「失败不阻塞主流程」⇒ D1 fund_score 静默停更 20 天无人知。
# 现在：①同步开始前先 `wrangler whoami` 预检凭据，凭据无效/过期=明确错误（不打印 token）；
#   ②任何失败分支统一走 `_fail()`：写 <REPO>/data/d1_sync_state/sync_fund_score_to_d1.json
#   （连续失败计数，原子写）；③成功走 `_success()` 删除状态文件（清零、无残留）；
#   ④既有巡检 check_failed_units.py（云上 trade-schedule-monitor.timer，15min 一轮）读状态，
#   连续 ≥2 次失败发一条告警（只报一次，防每轮轰炸）。
# 「失败不阻塞评分主流程」保持不变（调用方语义），但**不再静默**。
set -uo pipefail

SCRIPT_SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_SELF_DIR/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
DB="$REPO/data/public_fund.db"
LOG_PREFIX="[sync-d1]"
SCRIPT_NAME="sync_fund_score_to_d1"
STATE_DIR="$REPO/data/d1_sync_state"
BATCH=80   # legacy 多文件模式下每条 INSERT 的行数（single 模式改按字节封顶切批）
DRY_RUN="${DRY_RUN:-}"
# 一表一文件 / 字节封顶 / 重试(2026-10-26); D1_SPLIT_MODE=legacy 回退旧多文件模式
SPLIT_MODE="${D1_SPLIT_MODE:-single}"
MAX_STMT_BYTES="${D1_MAX_STMT_BYTES:-60000}"
ASSERT_MAX_STMT_BYTES="${D1_MAX_STMT_BYTES_ASSERT:-90000}"
RETRY_DELAYS="${D1_RETRY_DELAYS:-30 90}"
# 预算默认 360s(远小于 daily 10min 墙; 旧默认 1800s 永远用不到)。旧名 D1_SYNC_BUDGET_SEC 兼容。
BUDGET_SEC="${D1_RETRY_BUDGET:-${D1_SYNC_BUDGET_SEC:-360}}"
EXEC_TIMEOUT_SEC="${D1_EXEC_TIMEOUT_SEC:-300}"
VERIFY_TIMEOUT_SEC="${D1_VERIFY_TIMEOUT_SEC:-60}"
BUNDLE_FILE="full_import.sql"

case "$SPLIT_MODE" in
  single|legacy) ;;
  *) echo "[sync-d1] FATAL: D1_SPLIT_MODE='$SPLIT_MODE' 非法(只支持 single|legacy)" >&2; exit 2 ;;
esac

if [ "$DRY_RUN" = "1" ]; then
  GEN_DIR="${TMPDIR:-/tmp}/fund-score-d1.$$"
  mkdir -p "$GEN_DIR"
else
  GEN_DIR=$(mktemp -d /tmp/fund-score-d1.XXXXXX)
  trap 'rm -rf "$GEN_DIR"' EXIT
fi

# 失败出口：统一记录状态（供巡检消费）后以 1 退出。
# 状态写失败不盖掉原失败码，但**必须可见**：捕获 record-failure 的摘要转述到本脚本日志
# （2026-10-22 审查缺口 A：旧版 >/dev/null 2>&1 且记录器 rc 恒 0 ⇒ WARN 永不出现 = 静默）。
_fail() {
  local msg="$1" cred="${2:-unknown}" state_out=""
  echo "$LOG_PREFIX ERROR: $msg" >&2
  # DRY_RUN 是本机验证, 不是生产同步 ⇒ 不写失败状态、不污染巡检告警
  if [ "$DRY_RUN" != "1" ]; then
    if ! state_out=$("$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" record-failure \
          --script "$SCRIPT_NAME" --error "$msg" --credential "$cred" \
          --state-dir "$STATE_DIR" 2>&1); then
      echo "$LOG_PREFIX WARN: 失败状态写入失败（巡检会漏报本次失败）: $STATE_DIR" >&2
      # 摘要截断转述（记录器只打异常类型/路径，不打印任何 token）
      echo "$LOG_PREFIX WARN: 原因: $(printf '%s' "$state_out" | tail -n 2 | tr '\n' ' ' | cut -c1-500)" >&2
    fi
  fi
  exit 1
}

_success() {
  [ "$DRY_RUN" = "1" ] && return 0
  "$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" record-success --script "$SCRIPT_NAME" \
    --state-dir "$STATE_DIR" >/dev/null 2>&1 || true
}

if [ ! -f "$DB" ]; then
  _fail "DB 不存在: $DB"
fi

if [ "$DRY_RUN" != "1" ]; then
  # 凭据预检（#275）：把「未登录」这类失败前移到同步开始前，错误语义明确。
  echo "$LOG_PREFIX 凭据预检: wrangler whoami"
  "$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" whoami-check
  _WC=$?
  if [ "$_WC" -eq 1 ]; then
    _fail "wrangler 凭据无效/过期（whoami 失败）。请重新登录: npx wrangler login" invalid
  elif [ "$_WC" -ne 0 ]; then
    _fail "无法验证 wrangler 凭据（whoami 超时/工具缺失），本轮按失败处理" unknown
  fi
fi

cd "$REPO"

echo "$LOG_PREFIX 开始: $(date '+%F %T') db=$DB mode=$SPLIT_MODE batch=$BATCH dry_run=${DRY_RUN:-0}"

# 1) 生成导入包（默认整表一个文件; legacy 模式退回 schema + 分批数据多文件）
#    参数: db 路径 / 生成目录 / legacy 行批 / 脚本目录 / 模式 / 软上限字节 / 硬断言字节 / 包文件名
"$PY" - "$DB" "$GEN_DIR" "$BATCH" "$SCRIPT_SELF_DIR" "$SPLIT_MODE" \
      "$MAX_STMT_BYTES" "$ASSERT_MAX_STMT_BYTES" "$BUNDLE_FILE" <<'PYEOF'
import json, sqlite3, sys
from pathlib import Path

db_path, gen_dir, batch = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
script_dir, split_mode = Path(sys.argv[4]), sys.argv[5]
MAX_STMT_BYTES, ASSERT_MAX_BYTES = int(sys.argv[6]), int(sys.argv[7])
BUNDLE_NAME = sys.argv[8]
sys.path.insert(0, str(script_dir / "lib"))
from d1_sql_bundle import Bundle, BundleTooLargeError  # noqa: E402
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT MAX(score_date) AS d FROM fund_score WHERE composite_score IS NOT NULL"
).fetchone()
latest = row["d"]
if not latest:
    print("[sync-d1-python] ERROR: fund_score 无有效评分", flush=True)
    sys.exit(1)

cols = [
    # (sql列名, SELECT 表达式)
    ("fund_code", "s.fund_code"),
    ("fund_name", "b.fund_name"), ("fund_type", "b.fund_type"),
    ("fund_company", "b.fund_company"), ("fund_manager", "b.fund_manager"),
    ("setup_date", "b.setup_date"), ("scale", "b.scale"),
    ("management_fee", "b.management_fee"), ("custody_fee", "b.custody_fee"),
    ("purchase_fee", "b.purchase_fee"), ("strategy", "b.strategy"),
    ("benchmark_text", "b.benchmark AS benchmark_text"),  # b.benchmark 文本改名, 不覆盖 s.benchmark
    ("composite_score", "s.composite_score"), ("star_rating", "s.star_rating"),
    ("score_return", "s.score_return"), ("score_risk_adjusted", "s.score_risk_adjusted"),
    ("score_drawdown", "s.score_drawdown"), ("score_stability", "s.score_stability"),
    ("score_scale", "s.score_scale"), ("score_fee", "s.score_fee"),
    ("sharpe", "s.sharpe"), ("sortino", "s.sortino"), ("calmar", "s.calmar"),
    ("information_ratio", "s.information_ratio"), ("alpha", "s.alpha"),
    ("manager_score", "s.manager_score"),
    ("m1_tenure", "s.m1_tenure"), ("m2_scale", "s.m2_scale"),
    ("m3_perf_stability", "s.m3_perf_stability"), ("m4_drawdown", "s.m4_drawdown"),
    ("m5_coherence", "s.m5_coherence"), ("m6_focus", "s.m6_focus"),
    ("kelly_fraction", "s.kelly_fraction"), ("half_kelly_position", "s.half_kelly_position"),
    ("kelly_win_rate", "s.kelly_win_rate"), ("kelly_win_loss_ratio", "s.kelly_win_loss_ratio"),
    ("kelly_tier", "s.kelly_tier"), ("market_adjustment", "s.market_adjustment"),
    ("final_suggestion", "s.final_suggestion"), ("benchmark", "s.benchmark"),
    ("score_method", "s.score_method"), ("data_completeness", "s.data_completeness"),
    ("update_date", "s.update_date"),
]
sel = ", ".join(expr for _, expr in cols)
rows = conn.execute(
    f"SELECT {sel} FROM fund_score s LEFT JOIN fund_basic b ON s.fund_code=b.fund_code "
    "WHERE s.score_date=? AND s.composite_score IS NOT NULL "
    "ORDER BY s.composite_score DESC", (latest,)
).fetchall()
n_int = lambda v: int(v) if v is not None else None
rows = [dict(r) for r in rows]  # sqlite3.Row 不可赋值, 先转 dict
# 空输入为什么不会产出「只有 DELETE、没有 INSERT」的清空包(2026-10-26 审查 L2 结论):
#   ① 上面已按同一谓词 `composite_score IS NOT NULL` 取 MAX(score_date), 取不到就 sys.exit(1);
#   ② 本条查询用**同一个谓词** ⇒ latest 有值时 rows 必非空(这里不存在空行集);
#   ③ 纵深防御: Bundle.add_inserts 收到空行集先抛错、且**不把 DELETE 入队**
#      (scripts/lib/d1_sql_bundle.py) ⇒ 即使 ① 将来被删, 也产不出 DELETE-only 包。
#   因此不在这里再加一个不可达的 `if not rows` 守卫(不可达分支测不到, 只会掩盖真实防线)。
for r in rows:
    # star_rating 从 sqlite 动态类型可能回读 float, 统一转 int 保持与本地一致
    if r["star_rating"] is not None:
        r["star_rating"] = n_int(r["star_rating"])

def sql_lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"

col_list = ", ".join(name for name, _ in cols)

# schema（幂等）+ sync_meta（同步元数据: score_date/rows/synced_at, 供 /api/fund_score 返回数据日期）
schema_stmts = ["""CREATE TABLE IF NOT EXISTS fund_score (
  fund_code TEXT PRIMARY KEY,
  fund_name TEXT, fund_type TEXT,
  fund_company TEXT, fund_manager TEXT, setup_date TEXT, scale REAL,
  management_fee REAL, custody_fee REAL, purchase_fee REAL,
  strategy TEXT, benchmark_text TEXT,
  composite_score REAL, star_rating INTEGER,
  score_return REAL, score_risk_adjusted REAL, score_drawdown REAL,
  score_stability REAL, score_scale REAL, score_fee REAL,
  sharpe REAL, sortino REAL, calmar REAL, information_ratio REAL, alpha REAL,
  manager_score REAL,
  m1_tenure REAL, m2_scale REAL, m3_perf_stability REAL,
  m4_drawdown REAL,
  m5_coherence REAL, m6_focus REAL,
  kelly_fraction REAL, half_kelly_position REAL, kelly_win_rate REAL,
  kelly_win_loss_ratio REAL, kelly_tier TEXT, market_adjustment REAL,
  final_suggestion REAL, benchmark TEXT, score_method TEXT,
  data_completeness REAL, update_date TEXT
);""",
"DROP INDEX IF EXISTS idx_fs_composite;",
"CREATE INDEX idx_fs_composite ON fund_score(composite_score);",
"DROP INDEX IF EXISTS idx_fs_type;",
"CREATE INDEX idx_fs_type ON fund_score(fund_type);",
"""CREATE TABLE IF NOT EXISTS sync_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);"""]
schema = "\n".join(schema_stmts) + "\n"  # legacy 模式落盘用（与旧版逐字节一致）

# meta（记录同步的 score_date 与行数, 供验证）; 落盘时机见文件末尾
#   (2026-10-26 审查 M3: 挪到全部生成动作之后, 硬断言失败时不留残留)

# 同步元数据（最后写入, 供 worker 返回数据日期/行数）
import datetime as _dt
now_str = _dt.datetime.now().isoformat(timespec="seconds")
meta_stmt = (
    "INSERT INTO sync_meta (key, value) VALUES\n"
    f"('score_date', '{latest}'),\n"
    f"('rows', '{len(rows)}'),\n"
    f"('synced_at', '{now_str}')\n"
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value;"
)

head = f"INSERT INTO fund_score ({col_list}) VALUES"
row_values = ["(" + ", ".join(sql_lit(r[name]) for name, _ in cols) + ")" for r in rows]

if split_mode == "single":
    # 一表一文件: schema → DELETE(第一条数据语句) → 字节封顶的 INSERT → meta
    bundle = Bundle(max_stmt_bytes=MAX_STMT_BYTES, assert_max_bytes=ASSERT_MAX_BYTES)
    for s in schema_stmts:
        bundle.add(s)
    bundle.add_inserts(head, row_values, delete_stmt="DELETE FROM fund_score;")
    bundle.add(meta_stmt)
    # 硬断言先于写盘: 超限 = 直接失败, 绝不留半个包
    try:
        bundle.assert_limits()
    except BundleTooLargeError as e:
        print(f"[sync-d1-python] ERROR: {e}", flush=True)
        sys.exit(3)
    bundle_path = gen_dir / BUNDLE_NAME
    written = bundle.write(bundle_path)
    st = bundle.stats()
    if written != st["total_bytes"]:
        print(f"[sync-d1-python] ERROR: 写盘字节 {written} != 统计 {st['total_bytes']}", flush=True)
        sys.exit(4)
    print(f"[sync-d1-python] mode=single score_date={latest} rows={len(rows)} files=1 "
          f"path={bundle_path} total_bytes={st['total_bytes']} "
          f"statements={st['statements']} max_stmt_bytes={st['max_stmt_bytes']} "
          f"soft_cap={MAX_STMT_BYTES} hard_cap={ASSERT_MAX_BYTES} "
          f"oversize_single_row_stmts={st['oversize_single_row_stmts']}", flush=True)
else:
    # legacy: 旧的多文件逐批模式（回退开关）, 产出与改动前逐字节一致
    (gen_dir / "000_schema.sql").write_text(schema, encoding="utf-8")
    first = True
    files = []
    for i in range(0, len(rows), batch):
        chunk = row_values[i:i + batch]
        vals = ",\n".join(chunk)
        body = ""
        if first:
            body += "DELETE FROM fund_score;\n"
            first = False
        body += f"{head}\n{vals};\n"
        p = gen_dir / f"{len(files)+1:03d}_data.sql"
        p.write_text(body, encoding="utf-8")
        files.append(p)
    (gen_dir / "999_meta.sql").write_text(meta_stmt + "\n", encoding="utf-8")
    print(f"[sync-d1-python] mode=legacy score_date={latest} rows={len(rows)} "
          f"files={len(files)} batch={batch}", flush=True)

# meta.json 放在**全部生成动作之后**写(2026-10-26 审查 M3): 硬断言/写盘失败时
#   生成目录里连 meta.json 都没有 —— 与「超限时一个字节都不写盘」的口径一致
#   (旧版在断言之前写, 超限会残留 meta.json)。它只供调用方读期望行数, 不参与 SQL 内容。
(gen_dir / "meta.json").write_text(
    json.dumps({"score_date": latest, "rows": len(rows)}), encoding="utf-8")
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  if [ $RC -eq 3 ]; then
    _fail "生成失败: 单条 SQL 语句超过硬上限(见上方 ERROR 行, 修复超长行后重跑)"
  fi
  _fail "生成 SQL 失败 rc=$RC"
fi

EXPECT_ROWS=$("$PY" -c "import json;print(json.load(open('$GEN_DIR/meta.json'))['rows'])")

# 待执行的 SQL 文件清单: 默认只有一个整包文件; legacy 模式沿用旧的多文件
if [ "$SPLIT_MODE" = "single" ]; then
  SQL_FILES=("$GEN_DIR/$BUNDLE_FILE")
  if [ ! -f "${SQL_FILES[0]}" ]; then
    _fail "生成产物缺失: ${SQL_FILES[0]}"
  fi
else
  SQL_FILES=("$GEN_DIR"/*.sql)
fi

if [ "$DRY_RUN" = "1" ]; then
  echo "$LOG_PREFIX DRY_RUN 完成: mode=$SPLIT_MODE 生成目录 ${GEN_DIR} 待执行文件数=${#SQL_FILES[@]}(未推 D1)"
  echo "$LOG_PREFIX   验证例: db=/tmp/fscore_test.db; rm -f \$db"
  for f in "${SQL_FILES[@]}"; do
    echo "$LOG_PREFIX     sqlite3 \$db < \"$f\""
  done
  echo "$LOG_PREFIX     sqlite3 \$db 'SELECT COUNT(*) FROM fund_score'   # 期望 ${EXPECT_ROWS}"
  exit 0
fi

# 2) 导入 D1: 默认整表一个文件只调一次(--file 本身是 import 管线); legacy 逐文件
#    网络类失败由 lib/d1_execute.sh 重试(最多 2 次, 30s/90s 退避), SQL 类错误不重试
echo "$LOG_PREFIX 执行计划: mode=$SPLIT_MODE files=${#SQL_FILES[@]} budget=${BUDGET_SEC}s exec_timeout=${EXEC_TIMEOUT_SEC}s"
D1_BUDGET_START=$(date +%s)
D1_SYNC_DEADLINE=$(( D1_BUDGET_START + BUDGET_SEC ))
export D1_SYNC_DEADLINE D1_RETRY_DELAYS="$RETRY_DELAYS" LOG_PREFIX
export D1_BUDGET_START D1_BUDGET_TOTAL_SEC="$BUDGET_SEC" D1_EXEC_TIMEOUT_SEC="$EXEC_TIMEOUT_SEC"
source "$SCRIPT_SELF_DIR/lib/d1_execute.sh" || _fail "d1_execute.sh missing"
for f in "${SQL_FILES[@]}"; do
  echo "$LOG_PREFIX execute $(basename "$f") ($(wc -c < "$f" | tr -d ' ') bytes)"
  _OUT="$GEN_DIR/execute.out"
  if ! d1_execute_sql_file trade-fund-score "$f" "$_OUT"; then
    tail -5 "$_OUT" >&2 || true
    _fail "wrangler d1 execute 失败: $(basename "$f")"
  fi
done

# 3) 验证: D1 侧 count 与本地一致
D1_COUNT=$(_d1_run_with_timeout "$VERIFY_TIMEOUT_SEC" \
  npx wrangler d1 execute trade-fund-score --remote -y --json \
  --command "SELECT COUNT(*) AS n FROM fund_score" 2>/dev/null \
  | "$PY" -c "import json,sys;d=json.load(sys.stdin);print(d[0]['results'][0]['n'])")
echo "$LOG_PREFIX 本地 rows=$EXPECT_ROWS D1 count=$D1_COUNT"
if [ "$D1_COUNT" != "$EXPECT_ROWS" ]; then
  _fail "D1 count 与本地不一致: 本地 $EXPECT_ROWS vs D1 ${D1_COUNT:-读取失败}"
fi
_success
echo "$LOG_PREFIX 完成: $(date '+%F %T') 同步成功且校验一致"
