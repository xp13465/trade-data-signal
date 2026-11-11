#!/bin/bash
# d1_hash_read.sh - 读 D1 表现存 {fund_code: row_hash} + 幂等迁移 row_hash 列(增量同步用)
#
# 背景(2026-11-08, fund_score/fund_screener D1 增量同步): 增量 diff 需要先拿到 D1 现存
#   每行的 row_hash。wrangler d1 execute --remote --json 单次结果可能截断(28k 行),
#   故按 fund_code 升序游标分批 LIMIT 5000 循环, 累积成 JSON 文件供 Python 生成器读。
#
# 依赖: 调用方已 source scripts/lib/d1_execute.sh(用 _d1_run_with_timeout); 或本函数自带的
#   裸 timeout 包裹(未 source 时也能跑)。
# 用法:
#   source scripts/lib/d1_hash_read.sh
#   d1_migrate_row_hash <d1_db> <table>            # 幂等加 row_hash TEXT 列(容忍已存在/表不存在)
#   d1_migrate_column <d1_db> <table> <col> <ddl>   # 幂等加任意列(如 fund_score.score_date, F1)
#   d1_read_hashes <d1_db> <table> <out_json> [batch]   # 批量 SELECT, 写 {fund_code: row_hash}
# 返回: 0 成功; 非 0 失败(调用方按 DRY_RUN/生产 决定 _fail 或兜底)。
#
# DRY_RUN 友好: 调用方在 DRY_RUN 时若本函数失败, 可兜底为空 JSON({}); 生产则 _fail。
# 本函数不写失败状态(那是 _fail 的职责), 只做网络读 + 落盘。

# 单次 wrangler 调用的超时(秒); 读是小查询, 60s 足够(网络抖动由重试在 d1_execute.sh 处理)
_D1_HASH_READ_TIMEOUT="${D1_HASH_READ_TIMEOUT:-90}"
_D1_HASH_BATCH="${D1_HASH_BATCH:-5000}"

d1_migrate_row_hash() {
  local db="$1" table="$2"
  d1_migrate_column "$db" "$table" row_hash "TEXT"
}

# d1_migrate_column <db> <table> <col> <ddl类型> - 幂等 ALTER TABLE ADD COLUMN(2026-11-08 审查 F1)。
#   背景: 生产 D1 fund_score 表是 2026-08-22 老 schema 建成(无 score_date 列), 而新版 INSERT
#   列清单已含 score_date —— CREATE TABLE IF NOT EXISTS 对已有表不生效, 不补列则首跑
#   "no such column: score_date" 确定性失败。任何「新版代码比生产表多一列」都走本函数补列。
d1_migrate_column() {
  local db="$1" table="$2" col="$3" col_ddl="$4"
  # 幂等: ALTER TABLE ADD COLUMN。已存在 → "duplicate column name"(容忍);
  #   表不存在 → "no such table"(容忍, 后续 CREATE TABLE IF NOT EXISTS 会建);
  #   其他错误 → 真失败, 返回非 0。
  local out rc
  out=$(D1_METRICS_STAGE=migration D1_METRICS_OP=ALTER D1_METRICS_TABLE="$table" _d1_hash_run "$db" \
    "ALTER TABLE ${table} ADD COLUMN ${col} ${col_ddl};" 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    if echo "$out" | grep -qiE "duplicate column name|no such table"; then
      echo "[d1-hash] ${table}: ${col} 列已存在或表未建, 跳过迁移(rc=$rc)" >&2
      return 0
    fi
    echo "[d1-hash] ERROR ${table} ALTER ${col} 失败: $(echo "$out" | tail -3 | tr '\n' ' ')" >&2
    return $rc
  fi
  echo "[d1-hash] ${table}: ${col} 列迁移完成(或已存在)" >&2
  return 0
}

d1_read_hashes() {
  local db="$1" table="$2" out_json="$3" batch="${4:-$_D1_HASH_BATCH}"
  : > "$out_json" 2>/dev/null || true
  printf '{' >>"$out_json"
  local last_key="" n=0 first=1
  while true; do
    local sql
    if [ -z "$last_key" ]; then
      sql="SELECT fund_code, row_hash FROM ${table} ORDER BY fund_code LIMIT ${batch}"
    else
      # fund_code > '<last>' —— 单引号转义
      local esc; esc=$(printf '%s' "$last_key" | sed "s/'/''/g")
      sql="SELECT fund_code, row_hash FROM ${table} WHERE fund_code > '${esc}' ORDER BY fund_code LIMIT ${batch}"
    fi
    local raw rc
    raw=$(D1_METRICS_STAGE=hash_prefetch D1_METRICS_OP=SELECT D1_METRICS_TABLE="$table" _d1_hash_run "$db" "$sql" 2>/dev/null)
    rc=$?
    if [ $rc -ne 0 ]; then
      echo "[d1-hash] ERROR ${table} 读哈希失败(batch last_key=$last_key rc=$rc)" >&2
      return $rc
    fi
    # wrangler --json 返回 [{"results":[{"fund_code":"X","row_hash":"abc"}, ...]}]
    # 用 python 解析本批, 输出 "k":"v" 片段追加; 同时拿本批最后 key 与数量
    local parsed
    parsed=$(_d1_hash_py_parse "$raw" "$first") || { rc=$?; return $rc; }
    # parsed 形如: <n>\t<last_key>\t<json-entries>
    local bn blkey entries
    bn=$(printf '%s' "$parsed" | cut -f1)
    blkey=$(printf '%s' "$parsed" | cut -f2)
    entries=$(printf '%s' "$parsed" | cut -f3)
    if [ -n "$entries" ]; then
      [ "$first" = 1 ] || printf ',' >>"$out_json"
      printf '%s' "$entries" >>"$out_json"
      first=0
    fi
    n=$((n + bn))
    last_key="$blkey"
    # 本批 < batch 说明读完
    if [ "$bn" -lt "$batch" ]; then break; fi
    # 防御: 若本批 0 行且未到 batch(理论不会, 但防死循环)
    if [ "$bn" -eq 0 ]; then break; fi
  done
  printf '}\n' >>"$out_json"
  echo "[d1-hash] ${table}: 读到 ${n} 行哈希, 落盘 $out_json" >&2
  return 0
}

# ---- 内部: 跑一次 wrangler d1 execute --remote --json --command ----
_d1_hash_run() {
  local db="$1" cmd="$2"
  # 优先用 d1_execute.sh 的 _d1_run_with_timeout(若已 source); 否则裸 timeout
  if command -v _d1_run_with_timeout >/dev/null 2>&1; then
    d1_observed_command "${D1_METRICS_STAGE:-hash_prefetch}" "${D1_METRICS_OP:-SELECT}" "${D1_METRICS_TABLE:-}" \
      _d1_run_with_timeout "$_D1_HASH_READ_TIMEOUT" \
      npx wrangler d1 execute "$db" --remote -y --json --command "$cmd"
  else
    npx wrangler d1 execute "$db" --remote -y --json --command "$cmd"
  fi
}

# ---- 内部: 用 python 解析 wrangler --json 一批, 输出 "n\tlast_key\tentries" ----
_d1_hash_py_parse() {
  local raw="$1" need_comma_prefix="$2"
  printf '%s' "$raw" | "$PY" -c '
import json, sys
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as e:
    sys.stderr.write("[d1-hash] parse-fail: %s\n" % e)
    sys.exit(2)
# wrangler --json 形如 [{"results":[...]}] 或 {"results":[...]}
if isinstance(data, list):
    data = data[0] if data else {}
results = data.get("results") or []
entries = []
last_key = ""
for r in results:
    code = r.get("fund_code")
    if not code:
        continue
    h = r.get("row_hash") or ""
    # JSON 字符串拼接(k/v 都已转义)
    entries.append("\"%s\":\"%s\"" % (str(code).replace("\"","\\\""), str(h).replace("\"","\\\"")))
    last_key = str(code)
sys.stdout.write("%d\t%s\t%s" % (len(entries), last_key, ",".join(entries)))
'
}
