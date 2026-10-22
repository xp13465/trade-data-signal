#!/bin/bash
# sync_fund_screener_to_d1.sh - 公募基金筛选器全市场平表同步到 CF D1（#266 一期, 2026-10-19）
#
# 目的: 把本地 public_fund.db 各表【每只基金最新可用分区】拍平成一张全市场平表
#       `fund_screener`（1 行/只, PK=fund_code）, 同步到 Cloudflare D1 数据库
#       trade-fund-score（与 fund_score 表同库不同表, 供 worker/fund_screener.js
#       提供 /api/fund_screener 服务端筛选/排序/分页/搜索）。**不需要新建 D1 数据库**。
#
# 为什么需要这张表（#266 方案 §1.3 机理 1）:
#   fund_score 的 D1 同步只取 MAX(score_date) 单个分区 ⇒ 周一至周六 D1 只有
#   「按规模降序头部 2000 只」, 周日才全量。筛选器若建在当日分区上, 工作日会静默缩到
#   2000 只。本脚本改为「**每只基金各自最近可用**」口径: 评分字段取该基金最近一次
#   有 composite_score 的分区（周日全量兜住全部, 工作日头部 2000 覆盖到的取当日）,
#   其余各表同样取「该基金最新可用分区」, 合起来行数恒等于 fund_basic 全市场（≥27000）。
#
# 口径（防 §23.6「入样宇宙静默缩水」; 前端逐条公示, purpose-notes「offshore」段）:
#   - 宇宙 = fund_basic 全市场（含债基/货基/QDII/FOF; 与 pending #266 拍板一致）,
#     某字段无数据者**不隐藏**, 该字段为 NULL, 前端按覆盖率显式标注。
#   - 每表取数: 按各表日期列**降序**遍历 + key 首见即留（去重）⇒ 每只基金取到
#     「最新可用分区」; 不做全量 JOIN, 走已有日期索引, 内存与耗时可控。
#   - 同一天多行（fund_manager 一人一行 / fund_industry_alloc 一行业一行）:
#     经理取该日 tenure_days 最大者（主理人, 并列取 manager_name 升序）;
#     行业取该日 weight_pct 最大者（第一大配置行业）, industry_n = 该日行业条数。
#   - setup_years / tenure_years / work_years 为**同步时点派生**（按运行日算, 每日刷新）;
#     原始 setup_date 一并保留供展示。
#   - 行业四列（industry_*）为 **#266 二期维度预留**（一期不做行业筛选, 只落数据供二期
#     直接用 + 供覆盖率标注引用; 见方案 §3.3 二期）。
#
# 输入: $REPO/data/public_fund.db（fund_basic / fund_performance / fund_risk_indicator /
#       fund_score / fund_manager / fund_rating / fund_purchase_status / fund_industry_alloc）
# 输出: CF D1 trade-fund-score.fund_screener（远程, wrangler d1 execute --remote）
#       + trade-fund-score.screener_meta（元数据: 行数/各表口径日期/字段覆盖率 JSON）
# 复现: bash scripts/sync_fund_screener_to_d1.sh          （需 wrangler 已登录; 云上/CF 操作, 授权后跑）
#       DRY_RUN=1 bash scripts/sync_fund_screener_to_d1.sh （只生成 SQL 不推 D1, 本机可跑）
# 调用方: scripts/pf_score_daily.sh 末尾（16:00 后, 避开 17:50; 失败不阻塞评分主流程）
# 幂等: CREATE TABLE IF NOT EXISTS + 全量替换（首个数据文件先 DELETE 再分批 INSERT）,
#       同一 DB 同一运行日下重复跑结果逐行一致（派生年限列随运行日变, 属预期）。
# 注意: BATCH 可用 SCREENER_D1_BATCH 覆盖（默认 80 行/语句, 与 sync_fund_score_to_d1.sh 同档）。
#
# ── #275 失败可见化（2026-10-22，与 sync_fund_score_to_d1.sh 同一机制）──────────
# 本脚本与 fund_score 同步共用同一个 D1 库 + 同一套 wrangler 凭据，凭据失效时同样会
# 静默失败。现在：whoami 预检 + 失败写 <REPO>/data/d1_sync_state/sync_fund_screener_to_d1.json
# + 成功删除状态 + 由 check_failed_units.py 巡检连续 ≥2 次失败告警一次。
# DRY_RUN=1（本机只生成 SQL 不推 D1）**不预检凭据、不写状态**：那不是生产同步，
# 不得污染生产状态/触发告警。
set -uo pipefail

SCRIPT_SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_SELF_DIR/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
PY="$REPO/.venv/bin/python"
DB="$REPO/data/public_fund.db"
D1_DB="trade-fund-score"
LOG_PREFIX="[sync-screener]"
SCRIPT_NAME="sync_fund_screener_to_d1"
STATE_DIR="$REPO/data/d1_sync_state"
BATCH="${SCREENER_D1_BATCH:-80}"
DRY_RUN="${DRY_RUN:-}"

if [ "$DRY_RUN" = "1" ]; then
  GEN_DIR="${TMPDIR:-/tmp}/fund-screener-d1.$$"
  mkdir -p "$GEN_DIR"
else
  GEN_DIR=$(mktemp -d /tmp/fund-screener-d1.XXXXXX)
  trap 'rm -rf "$GEN_DIR"' EXIT
fi

# 失败出口：非 DRY_RUN 才记录状态（DRY_RUN 是本机验证，不进生产状态）。
# 状态写失败不盖掉原失败码，但**必须可见**：捕获记录器摘要转述到本脚本日志
# （2026-10-22 审查缺口 A：旧版 >/dev/null 2>&1 且记录器 rc 恒 0 ⇒ WARN 永不出现 = 静默）。
_fail() {
  local msg="$1" cred="${2:-unknown}" state_out=""
  echo "$LOG_PREFIX ERROR: $msg" >&2
  if [ "$DRY_RUN" != "1" ]; then
    if ! state_out=$("$PY" "$SCRIPT_SELF_DIR/d1_sync_state.py" record-failure \
          --script "$SCRIPT_NAME" --error "$msg" --credential "$cred" \
          --state-dir "$STATE_DIR" 2>&1); then
      echo "$LOG_PREFIX WARN: 失败状态写入失败（巡检会漏报本次失败）: $STATE_DIR" >&2
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
  # 凭据预检（#275）：未登录/过期在同步开始前就给出明确错误。
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
echo "$LOG_PREFIX 开始: $(date '+%F %T') db=$DB batch=$BATCH dry_run=${DRY_RUN:-0}"

# 1) 生成 schema.sql + 分批数据 SQL（python 生成, NULL/引号安全转义）
"$PY" - "$DB" "$GEN_DIR" "$BATCH" <<'PYEOF'
import datetime as dt
import json
import math
import sqlite3
import sys
from pathlib import Path

db_path, gen_dir, batch = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
RUN_DATE = dt.date.today()


def latest_by_key(sql, key_cols, value_cols):
    """按 sql（必须已含 ORDER BY <日期列> DESC, ...）降序遍历, 每个 key 首见即留。

    首见即留 == 「该 key 的最新可用分区」; 同分区内的偏好由 SQL 的次级排序决定。
    """
    out = {}
    for r in conn.execute(sql):
        # 单列 key 用标量（调用处 perf.get(code) 直取）; 多列 key 用元组（如 (code,'1y')）
        k = r[key_cols[0]] if len(key_cols) == 1 else tuple(r[c] for c in key_cols)
        if k not in out:
            out[k] = {c: r[c] for c in value_cols}
    return out


def years_from_ymd(ymd):
    """'YYYYMMDD' -> 距运行日年数（REAL, 2 位）; 非法/缺失 -> None。"""
    if not ymd:
        return None
    s = str(ymd).strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        d = dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None
    return round((RUN_DATE - d).days / 365.25, 2)


def one(sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return r[0] if r else None


# ---------- 各表取数（每只基金最新可用） ----------
basic = {}
for r in conn.execute(
    "SELECT fund_code, fund_name, fund_type, fund_company, fund_manager, setup_date, "
    "scale, management_fee, custody_fee, purchase_fee, service_fee, strategy, benchmark "
    "FROM fund_basic WHERE fund_code IS NOT NULL AND fund_code != ''"
):
    basic[r["fund_code"]] = dict(r)

perf = latest_by_key(
    "SELECT fund_code, update_date, return_1m, return_3m, return_6m, return_1y, "
    "return_2y, return_3y, return_ytd, return_since_inception "
    "FROM fund_performance ORDER BY update_date DESC",
    ("fund_code",),
    ("update_date", "return_1m", "return_3m", "return_6m", "return_1y", "return_2y",
     "return_3y", "return_ytd", "return_since_inception"),
)

risk = latest_by_key(
    "SELECT fund_code, period, update_date, annual_volatility, max_drawdown "
    "FROM fund_risk_indicator WHERE period IN ('1y','3y') ORDER BY update_date DESC",
    ("fund_code", "period"),
    ("update_date", "annual_volatility", "max_drawdown"),
)

score = latest_by_key(
    "SELECT fund_code, score_date, composite_score, star_rating, score_return, "
    "score_risk_adjusted, score_drawdown, score_stability, score_scale, score_fee, "
    "sharpe, sortino, calmar, information_ratio, alpha, manager_score, m1_tenure, "
    "m2_scale, m3_perf_stability, m4_drawdown, m5_coherence, m6_focus, kelly_fraction, "
    "half_kelly_position, kelly_win_rate, kelly_win_loss_ratio, kelly_tier, "
    "market_adjustment, final_suggestion, score_method, data_completeness, update_date "
    "FROM fund_score WHERE composite_score IS NOT NULL ORDER BY score_date DESC",
    ("fund_code",),
    ("score_date", "composite_score", "star_rating", "score_return", "score_risk_adjusted",
     "score_drawdown", "score_stability", "score_scale", "score_fee", "sharpe", "sortino",
     "calmar", "information_ratio", "alpha", "manager_score", "m1_tenure", "m2_scale",
     "m3_perf_stability", "m4_drawdown", "m5_coherence", "m6_focus", "kelly_fraction",
     "half_kelly_position", "kelly_win_rate", "kelly_win_loss_ratio", "kelly_tier",
     "market_adjustment", "final_suggestion", "score_method", "data_completeness",
     "update_date"),
)

# 经理: 同一日期一人一行 -> 取该日 tenure_days 最大（并列取 manager_name 升序）= 主理人
mgr = latest_by_key(
    "SELECT fund_code, update_date, manager_name, appoint_date, tenure_days, work_days, "
    "managed_scale, best_return FROM fund_manager "
    "ORDER BY update_date DESC, tenure_days DESC, manager_name ASC",
    ("fund_code",),
    ("update_date", "manager_name", "appoint_date", "tenure_days", "work_days",
     "managed_scale", "best_return"),
)

rating = latest_by_key(
    "SELECT fund_code, rating_date, shanghai_securities, cms, jajx, morningstar, "
    "five_star_count FROM fund_rating ORDER BY rating_date DESC",
    ("fund_code",),
    ("rating_date", "shanghai_securities", "cms", "jajx", "morningstar", "five_star_count"),
)

purchase = latest_by_key(
    "SELECT fund_code, update_date, purchase_status, redeem_status, purchase_min, daily_limit "
    "FROM fund_purchase_status ORDER BY update_date DESC",
    ("fund_code",),
    ("update_date", "purchase_status", "redeem_status", "purchase_min", "daily_limit"),
)

# 行业（二期预留）: 该基金最新 report_date 的 weight_pct 最大者 = 第一大配置行业
industry_top = latest_by_key(
    "SELECT fund_code, report_date, industry_name, weight_pct FROM fund_industry_alloc "
    "ORDER BY report_date DESC, weight_pct DESC, industry_name ASC",
    ("fund_code",),
    ("report_date", "industry_name", "weight_pct"),
)
industry_n = {}
for r in conn.execute(
    "SELECT fund_code, report_date, COUNT(*) AS n FROM fund_industry_alloc "
    "GROUP BY fund_code, report_date"
):
    industry_n[(r["fund_code"], r["report_date"])] = r["n"]

# ---------- 拍平到 fund_basic 宇宙 ----------
def n_int(v):
    return int(v) if v is not None else None


rows = []
for code in sorted(basic):
    b = basic[code]
    p = perf.get(code, {})
    r1 = risk.get((code, "1y"), {})
    r3 = risk.get((code, "3y"), {})
    s = score.get(code, {})
    m = mgr.get(code, {})
    rt = rating.get(code, {})
    pu = purchase.get(code, {})
    ind = industry_top.get(code, {})
    tenure_days, work_days = m.get("tenure_days"), m.get("work_days")
    rows.append({
        # 基础（fund_basic）
        "fund_code": code,
        "fund_name": b["fund_name"],
        "fund_type": b["fund_type"],
        "fund_company": b["fund_company"],
        "fund_manager": b["fund_manager"],
        "setup_date": b["setup_date"],
        "setup_years": years_from_ymd(b["setup_date"]),
        "scale": b["scale"],
        "management_fee": b["management_fee"],
        "custody_fee": b["custody_fee"],
        "purchase_fee": b["purchase_fee"],
        "service_fee": b["service_fee"],
        "strategy": b["strategy"],
        "benchmark_text": b["benchmark"],
        # 收益（fund_performance 该基金最新日）
        "return_1m": p.get("return_1m"), "return_3m": p.get("return_3m"),
        "return_6m": p.get("return_6m"), "return_1y": p.get("return_1y"),
        "return_2y": p.get("return_2y"), "return_3y": p.get("return_3y"),
        "return_ytd": p.get("return_ytd"),
        "return_since_inception": p.get("return_since_inception"),
        "perf_date": p.get("update_date"),
        # 风险（fund_risk_indicator 该基金各周期最新日）
        "volatility_1y": r1.get("annual_volatility"),
        "volatility_3y": r3.get("annual_volatility"),
        "max_drawdown_3y": r3.get("max_drawdown"),
        "risk_date": r3.get("update_date") or r1.get("update_date"),
        # 评分（fund_score 该基金最近一次有 composite_score 的分区）
        "score_date": s.get("score_date"),
        "composite_score": s.get("composite_score"),
        "star_rating": n_int(s.get("star_rating")),
        "score_return": s.get("score_return"),
        "score_risk_adjusted": s.get("score_risk_adjusted"),
        "score_drawdown": s.get("score_drawdown"),
        "score_stability": s.get("score_stability"),
        "score_scale": s.get("score_scale"),
        "score_fee": s.get("score_fee"),
        "sharpe": s.get("sharpe"), "sortino": s.get("sortino"),
        "calmar": s.get("calmar"), "information_ratio": s.get("information_ratio"),
        "alpha": s.get("alpha"), "manager_score": s.get("manager_score"),
        "m1_tenure": s.get("m1_tenure"), "m2_scale": s.get("m2_scale"),
        "m3_perf_stability": s.get("m3_perf_stability"),
        "m4_drawdown": s.get("m4_drawdown"), "m5_coherence": s.get("m5_coherence"),
        "m6_focus": s.get("m6_focus"),
        "kelly_fraction": s.get("kelly_fraction"),
        "half_kelly_position": s.get("half_kelly_position"),
        "kelly_win_rate": s.get("kelly_win_rate"),
        "kelly_win_loss_ratio": s.get("kelly_win_loss_ratio"),
        "kelly_tier": s.get("kelly_tier"),
        "market_adjustment": s.get("market_adjustment"),
        "final_suggestion": s.get("final_suggestion"),
        "score_method": s.get("score_method"),
        "data_completeness": s.get("data_completeness"),
        "update_date": s.get("update_date"),
        # 经理（fund_manager 该基金最新日的主理人）
        "manager_name": m.get("manager_name"),
        "manager_appoint_date": m.get("appoint_date"),
        "tenure_years": (round(tenure_days / 365.25, 2) if tenure_days is not None else None),
        "work_years": (round(work_days / 365.25, 2) if work_days is not None else None),
        "manager_scale": m.get("managed_scale"),
        "manager_best_return": m.get("best_return"),
        "manager_date": m.get("update_date"),
        # 评级（fund_rating 该基金最新日）
        "rating_shanghai": rt.get("shanghai_securities"),
        "rating_cms": rt.get("cms"),
        "rating_jajx": rt.get("jajx"),
        "rating_morningstar": rt.get("morningstar"),
        "rating_five_star_count": n_int(rt.get("five_star_count")),
        "rating_date": rt.get("rating_date"),
        # 申赎（fund_purchase_status 该基金最新日）
        "purchase_status": pu.get("purchase_status"),
        "redeem_status": pu.get("redeem_status"),
        "purchase_min": pu.get("purchase_min"),
        "daily_limit": pu.get("daily_limit"),
        "purchase_date": pu.get("update_date"),
        # 行业（二期维度预留）
        "industry_top1": ind.get("industry_name"),
        "industry_top1_weight": ind.get("weight_pct"),
        "industry_n": (industry_n.get((code, ind.get("report_date"))) if ind else None),
        "industry_report_date": ind.get("report_date"),
    })

if not rows:
    print("[sync-screener-python] ERROR: fund_basic 无数据, 无法生成", flush=True)
    sys.exit(1)

COLS = list(rows[0].keys())

# ---------- schema（幂等建表 + 少量索引 + 元数据表） ----------
INT_COLS = {"star_rating", "rating_five_star_count", "industry_n"}
TEXT_COLS = {
    "fund_name", "fund_type", "fund_company", "fund_manager", "setup_date", "strategy",
    "benchmark_text", "perf_date", "risk_date", "score_date", "kelly_tier", "score_method",
    "update_date", "manager_name", "manager_appoint_date", "manager_date", "rating_date",
    "purchase_status", "redeem_status", "purchase_date", "industry_top1",
    "industry_report_date",
}


def d1_type(c):
    if c == "fund_code":
        return "TEXT PRIMARY KEY"
    if c in INT_COLS:
        return "INTEGER"
    if c in TEXT_COLS:
        return "TEXT"
    return "REAL"


schema = "CREATE TABLE IF NOT EXISTS fund_screener (\n  " + ",\n  ".join(
    f"{c} {d1_type(c)}" for c in COLS) + "\n);\n"
# 索引只保留高频排序/分组三列（表小, COUNT/排序无索引也快; 少索引=少写入开销, 同 sync_fund_score_to_d1.sh 风格）
for idx, col in (("idx_fscr_composite", "composite_score"),
                 ("idx_fscr_type", "fund_type"),
                 ("idx_fscr_scale", "scale")):
    schema += f"DROP INDEX IF EXISTS {idx};\nCREATE INDEX {idx} ON fund_screener({col});\n"
schema += ("CREATE TABLE IF NOT EXISTS screener_meta (\n"
           "  key TEXT PRIMARY KEY,\n  value TEXT\n);\n")
(gen_dir / "000_schema.sql").write_text(schema, encoding="utf-8")

# ---------- 覆盖率统计（各字段非空行数; 前端逐条件标注 + 「另有 N 只因缺失被排除」底座） ----------
coverage = {c: sum(1 for r in rows if r[c] is not None) for c in COLS if c != "fund_code"}
meta_payload = {
    "fund_total": len(rows),
    "built_at": dt.datetime.now().isoformat(timespec="seconds"),
    "built_date": RUN_DATE.isoformat(),
    "source_dates": {
        "basic": one("SELECT MAX(update_date) FROM fund_basic"),
        "perf": max((p.get("update_date") or "" for p in perf.values()), default=""),
        "risk": max((risk[k].get("update_date") or "" for k in risk), default=""),
        "score_latest": one(
            "SELECT MAX(score_date) FROM fund_score WHERE composite_score IS NOT NULL"),
        "manager": max((m.get("update_date") or "" for m in mgr.values()), default=""),
        "rating": max((x.get("rating_date") or "" for x in rating.values()), default=""),
        "purchase": max((x.get("update_date") or "" for x in purchase.values()), default=""),
        "industry": max((x.get("report_date") or "" for x in industry_top.values()), default=""),
    },
    "coverage": coverage,
}
(gen_dir / "meta.json").write_text(json.dumps(meta_payload, ensure_ascii=False), encoding="utf-8")


def sql_lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return "NULL"
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


col_list = ", ".join(COLS)
files = []
for i in range(0, len(rows), batch):
    chunk = rows[i:i + batch]
    vals = ",\n".join(
        "(" + ", ".join(sql_lit(r[c]) for c in COLS) + ")" for r in chunk)
    body = ""
    if not files:
        body += "DELETE FROM fund_screener;\n"  # 全量替换（幂等; 同 sync_fund_score_to_d1.sh 模式）
    body += f"INSERT INTO fund_screener ({col_list}) VALUES\n{vals};\n"
    p = gen_dir / f"{len(files)+1:03d}_data.sql"
    p.write_text(body, encoding="utf-8")
    files.append(p)

# 元数据（最后写, 供 worker 返回数据日期/行数/覆盖率）
meta_items = (
    ("fund_total", meta_payload["fund_total"]),
    ("built_at", meta_payload["built_at"]),
    ("built_date", meta_payload["built_date"]),
    ("source_dates", meta_payload["source_dates"]),
    ("coverage", meta_payload["coverage"]),
)
meta_sql = "".join(
    "INSERT INTO screener_meta (key, value) VALUES ('{k}', '{v}') "
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value;\n".format(
        k=k, v=json.dumps(v, ensure_ascii=False).replace("'", "''"))
    for k, v in meta_items
)
(gen_dir / "999_meta.sql").write_text(meta_sql, encoding="utf-8")

max_bytes = max(p.stat().st_size for p in files)
print(f"[sync-screener-python] rows={len(rows)} cols={len(COLS)} files={len(files)} "
      f"batch={batch} max_stmt_bytes={max_bytes} coverage_cols={len(coverage)}", flush=True)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  _fail "生成 SQL 失败 rc=$RC"
fi

EXPECT_ROWS=$("$PY" -c "import json;print(json.load(open('$GEN_DIR/meta.json'))['fund_total'])")

if [ "$DRY_RUN" = "1" ]; then
  echo "$LOG_PREFIX DRY_RUN 完成: 生成目录 ${GEN_DIR}(未推 D1, 本机可验证语法/幂等)"
  echo "$LOG_PREFIX   验证例: db=/tmp/fscr_test.db; rm -f \$db"
  echo "$LOG_PREFIX     for f in ${GEN_DIR}/*.sql; do sqlite3 \$db < \"\$f\"; done"
  echo "$LOG_PREFIX     sqlite3 \$db 'SELECT COUNT(*) FROM fund_screener'   # 期望 ${EXPECT_ROWS}"
  exit 0
fi

# 2) 逐文件 wrangler d1 execute --remote（schema 先, 数据后; -y 跳过确认）
for f in "$GEN_DIR"/*.sql; do
  echo "$LOG_PREFIX execute $(basename "$f") ($(wc -c < "$f" | tr -d ' ') bytes)"
  # 失败时用**本次**输出诊断（旧版失败后重跑一遍只为打印 tail = 二次执行同一 SQL，已去掉）
  _OUT="$GEN_DIR/execute.out"
  if ! npx wrangler d1 execute "$D1_DB" --remote -y --file="$f" > "$_OUT" 2>&1; then
    tail -5 "$_OUT" >&2 || true
    _fail "wrangler d1 execute 失败: $(basename "$f")"
  fi
done

# 3) 验证: D1 侧 count 与本地一致
D1_COUNT=$(npx wrangler d1 execute "$D1_DB" --remote -y --json \
  --command "SELECT COUNT(*) AS n FROM fund_screener" 2>/dev/null \
  | "$PY" -c "import json,sys;d=json.load(sys.stdin);print(d[0]['results'][0]['n'])")
echo "$LOG_PREFIX 本地 rows=$EXPECT_ROWS D1 count=$D1_COUNT"
if [ "$D1_COUNT" != "$EXPECT_ROWS" ]; then
  _fail "D1 count 与本地不一致: 本地 $EXPECT_ROWS vs D1 ${D1_COUNT:-读取失败}"
fi
_success
echo "$LOG_PREFIX 完成: $(date '+%F %T') 同步成功且校验一致"