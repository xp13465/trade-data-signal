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
# 调用方: pf_score_daily.sh / pf_score_weekly.sh 末尾（评分导出后自动同步）
# 注意: 需要 wrangler 已登录（npx wrangler whoami 可验）；D1 database_id 见 wrangler.jsonc。
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
GEN_DIR=$(mktemp -d /tmp/fund-score-d1.XXXXXX)
BATCH=80   # 每条 INSERT 的行数（控制单语句体积，D1 单语句建议 <200KB）

trap 'rm -rf "$GEN_DIR"' EXIT

# 失败出口：统一记录状态（供巡检消费）后以 1 退出。写状态失败只 warn，不盖掉原失败码。
_fail() {
  local msg="$1" cred="${2:-unknown}"
  echo "$LOG_PREFIX ERROR: $msg" >&2
  "$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" record-failure --script "$SCRIPT_NAME" \
    --error "$msg" --credential "$cred" --state-dir "$STATE_DIR" >/dev/null 2>&1 \
    || echo "$LOG_PREFIX WARN: 失败状态写入失败（巡检可能看不到本次失败）: $STATE_DIR" >&2
  exit 1
}

_success() {
  "$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" record-success --script "$SCRIPT_NAME" \
    --state-dir "$STATE_DIR" >/dev/null 2>&1 || true
}

if [ ! -f "$DB" ]; then
  _fail "DB 不存在: $DB"
fi

# 凭据预检（#275）：把「未登录」这类失败前移到同步开始前，错误语义明确。
echo "$LOG_PREFIX 凭据预检: wrangler whoami"
"$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" whoami-check
_WC=$?
if [ "$_WC" -eq 1 ]; then
  _fail "wrangler 凭据无效/过期（whoami 失败）。请重新登录: npx wrangler login" invalid
elif [ "$_WC" -ne 0 ]; then
  _fail "无法验证 wrangler 凭据（whoami 超时/工具缺失），本轮按失败处理" unknown
fi

cd "$REPO"

echo "$LOG_PREFIX 开始: $(date '+%F %T') db=$DB batch=$BATCH"

# 1) 生成 schema.sql（幂等建表）+ 分批数据 SQL（python 生成, NULL/引号安全转义）
"$PY" - "$DB" "$GEN_DIR" "$BATCH" <<'PYEOF'
import json, sqlite3, sys
from pathlib import Path

db_path, gen_dir, batch = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
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
schema = f"""CREATE TABLE IF NOT EXISTS fund_score (
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
);
DROP INDEX IF EXISTS idx_fs_composite;
CREATE INDEX idx_fs_composite ON fund_score(composite_score);
DROP INDEX IF EXISTS idx_fs_type;
CREATE INDEX idx_fs_type ON fund_score(fund_type);
CREATE TABLE IF NOT EXISTS sync_meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""
(gen_dir / "000_schema.sql").write_text(schema, encoding="utf-8")

# meta（记录同步的 score_date 与行数, 供验证）
(gen_dir / "meta.json").write_text(
    json.dumps({"score_date": latest, "rows": len(rows)}), encoding="utf-8")

# 数据分批: 先清空再插（全量替换幂等）
first = True
files = []
for i in range(0, len(rows), batch):
    chunk = rows[i:i + batch]
    vals = ",\n".join(
        "(" + ", ".join(sql_lit(r[name]) for name, _ in cols) + ")" for r in chunk)
    body = ""
    if first:
        body += "DELETE FROM fund_score;\n"
        first = False
    body += f"INSERT INTO fund_score ({col_list}) VALUES\n{vals};\n"
    p = gen_dir / f"{len(files)+1:03d}_data.sql"
    p.write_text(body, encoding="utf-8")
    files.append(p)

# 同步元数据（最后写入, 供 worker 返回数据日期/行数）
import datetime as _dt
now_str = _dt.datetime.now().isoformat(timespec="seconds")
meta_sql = (
    "INSERT INTO sync_meta (key, value) VALUES\n"
    f"('score_date', '{latest}'),\n"
    f"('rows', '{len(rows)}'),\n"
    f"('synced_at', '{now_str}')\n"
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value;\n"
)
(gen_dir / "999_meta.sql").write_text(meta_sql, encoding="utf-8")

print(f"[sync-d1-python] score_date={latest} rows={len(rows)} files={len(files)}", flush=True)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  _fail "生成 SQL 失败 rc=$RC"
fi

# 2) 逐文件 wrangler d1 execute --remote（schema 先, 数据后; -y 跳过确认）
EXPECT_ROWS=$("$PY" -c "import json;print(json.load(open('$GEN_DIR/meta.json'))['rows'])")
for f in "$GEN_DIR"/*.sql; do
  echo "$LOG_PREFIX execute $(basename "$f") ($(wc -c < "$f" | tr -d ' ') bytes)"
  # 失败时用**本次**输出诊断（旧版失败后重跑一遍只为打印 tail = 二次执行同一 SQL，已去掉）
  _OUT="$GEN_DIR/execute.out"
  if ! npx wrangler d1 execute trade-fund-score --remote -y --file="$f" > "$_OUT" 2>&1; then
    tail -5 "$_OUT" >&2 || true
    _fail "wrangler d1 execute 失败: $(basename "$f")"
  fi
done

# 3) 验证: D1 侧 count 与本地一致
D1_COUNT=$(npx wrangler d1 execute trade-fund-score --remote -y --json \
  --command "SELECT COUNT(*) AS n FROM fund_score" 2>/dev/null \
  | "$PY" -c "import json,sys;d=json.load(sys.stdin);print(d[0]['results'][0]['n'])")
echo "$LOG_PREFIX 本地 rows=$EXPECT_ROWS D1 count=$D1_COUNT"
if [ "$D1_COUNT" != "$EXPECT_ROWS" ]; then
  _fail "D1 count 与本地不一致: 本地 $EXPECT_ROWS vs D1 ${D1_COUNT:-读取失败}"
fi
_success
echo "$LOG_PREFIX 完成: $(date '+%F %T') 同步成功且校验一致"
