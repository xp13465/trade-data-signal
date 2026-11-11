#!/bin/bash
# d1_execute_sql_file - 单文件 SQL 导入 D1(单次调用超时 + 网络类失败重试), 供 sync_fund_*_to_d1.sh 共用。
#
# 用法: source 本文件; 调用 d1_execute_sql_file <db名> <sql文件> [输出文件]
#   成功返回 0; 失败返回 wrangler 的原始非 0 码(**绝不吞**); 单次超时返回 124。
#
# 单次调用超时(2026-10-26 审查 M2):
#   · `wrangler d1 execute` 单次必须有上限(`D1_EXEC_TIMEOUT_SEC`, 默认 300s)。
#     不设上限时, 卡死的进程会一直挂到**调用方的墙**被 SIGTERM 杀 —— daily 的墙现为
#     1800s(30 分钟, 云上 drop-in `timeout-1800.conf`; 10-22 / 10-23 事故当时是 10 分钟),
#     那时整个进程组被杀, 连 EXIT trap 都跑不到(云上两次各留一个 ~25MB 临时目录)。
#     300s 的依据: 25MB 单文件导入生产预期 45~55s(悲观 ≤2 分钟) ⇒ 约 5 倍余量。
#   · 超时(rc=124)按**网络类失败**处理(可重试), 不当 SQL 错误。
#
# 重试口径(2026-10-26 D1 单文件导入改造):
#   · **只重试网络类失败**(fetch failed / 连接断 / 超时 / 5xx 等); 明确的 SQL 错误
#     (SQLITE_TOOBIG / syntax error / no such table|column / constraint failed)不重试,
#     因为同一份 SQL 重放必然同样失败, 只会白等两轮。
#   · 最多重试 2 次, 退避秒数取环境变量 `D1_RETRY_DELAYS`(默认 "30 90")。
#     测试用 `D1_RETRY_DELAYS="0 0"` 即可零等待跑真实分支。
#   · 时间预算 `D1_SYNC_DEADLINE`(epoch 秒, 0/未设 = 不限): **每次尝试前**先查预算
#     (不是只在退避前), 预算用完立刻非 0 返回、不再发起调用; 单次上限还会被剩余预算压小
#     (剩余 20s 时不会再去发一个 300s 的调用)。
#     要打印「已用 Xs / 预算 Ys」需调用方同时给 `D1_BUDGET_START`(epoch)与
#     `D1_BUDGET_TOTAL_SEC`; 没给时退化为只报剩余秒数。
#     预算值由调用方定(single 默认 360s / legacy 默认 3600s, 环境变量 `D1_RETRY_BUDGET`):
#     预算必须覆盖「一张表完整导入」的时间 —— 预算掐断时 `DELETE FROM` 早已生效, 线上表会
#     留半成品(2026-10-26 复审 N1); single 还要远小于调用方的墙(daily 现网 1800s), legacy
#     则要求调用方**同时**把墙提到 ≥6000s。详见两个 sync 脚本的注释。
#   · 重试用尽/预算用尽 ⇒ 返回非 0, 由调用方按既有 `_fail()` 出口记录失败状态(不静默)。
#
# 为什么抽成 lib: 两个同步脚本各写一份重试循环 = 第二份实现静默漂移
#   (§5.4⑦ 同精神); 且本函数只做「调 wrangler + 分类 + 退避」, 不读业务数据,
#   可在测试里用假 npx 打桩走真分支(零真实外发/L50)。

# 明确属于「重放也没用」的 SQL 类错误(小写匹配)。
_D1_SQL_FATAL_RE='sqlite_toobig|statement too long|syntax error|no such (table|column)|constraint failed|has no column named'

_D1_METRICS_HELPER="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/d1_metrics_evidence.py"

# Called once per sync (before command substitutions). FD 9 keeps evidence errors
# visible even when the original caller intentionally discards Wrangler stderr.
d1_metrics_init() {
  exec 9>&2
  D1_METRICS_WARN_FD=9
  D1_METRICS_DIR="${D1_METRICS_DIR:-$REPO/data/d1_metrics_evidence}"
  D1_METRICS_RUN_ID=$("${PY:-python3}" -c 'import uuid; print(uuid.uuid4().hex)') || {
    _d1_metrics_warn; return 0;
  }
  export D1_METRICS_DIR D1_METRICS_RUN_ID D1_METRICS_WARN_FD SCRIPT_NAME
}

_d1_metrics_warn() {
  echo '[d1-evidence] WARN: 本次计数证据不完整；业务返回码保留，不因证据失败重放 SQL' >&${D1_METRICS_WARN_FD:-2}
}

# Metadata only; original command is executed exactly once, with unchanged rc.
# Bounded samples stay in memory; bytes stream to original sinks. SQL/credentials/results
# never enter the persistent evidence file. Standalone callers opt in via run ID.
_d1_observe() {
  local stage="$1" operation="$2" scope="$3" tables="$4" attempt="$5" call_id="$6"
  shift 6
  if [ -z "${D1_METRICS_RUN_ID:-}" ]; then
    "$@"; return $?
  fi
  # The command wrapper samples pipes in bounded memory, so ENOSPC in the evidence
  # directory cannot change Wrangler's rc or accidentally trigger a SQL retry.
  # All observed sites pass the existing timeout wrapper + its seconds first.
  if [ "$1" != "_d1_run_with_timeout" ] || [ ! -r "$_D1_METRICS_HELPER" ]; then
    _d1_metrics_warn
    "$@"; return $?
  fi
  shift
  local seconds="$1"
  shift
  local output_mode=separate
  if [ "${D1_METRICS_MERGED_OUTPUT:-0}" = "1" ]; then
    output_mode=merged
  fi
  "${PY:-python3}" "$_D1_METRICS_HELPER" --run --timeout "$seconds" --output-mode "$output_mode" \
    --call-id "$call_id" --attempt "$attempt" --stage "$stage" --operation "$operation" \
    --scope "$scope" --tables "$tables" -- "$@"
}

_d1_call_id() {
  "${PY:-python3}" -c 'import uuid; print(uuid.uuid4().hex)'
}

d1_observed_command() {
  local stage="$1" operation="$2" tables="$3" call_id
  shift 3
  call_id=$(_d1_call_id) || call_id=""
  _d1_observe "$stage" "$operation" statement "$tables" 1 "$call_id" "$@"
}

# _d1_run_with_timeout <秒> <命令...> - 带单次超时执行, 超时返回 124(与 coreutils timeout 同码)。
#   · 云上 Linux 用 coreutils `timeout`(它会让命令自成进程组, 超时连带子进程一起收掉);
#   · 本机 mac 默认没有 `timeout` ⇒ 退化为 bash 轮询实现(只影响本机/CI-mac 测试路径,
#     生产云上永远走 coreutils 分支)。退化实现只 kill 直接子进程, 孙进程可能短暂残留。
#   · 秒数 ≤0 = 不限超时(逃生门, 正常不用)。
_d1_run_with_timeout() {
  local secs="$1"
  shift
  if [ "$secs" -le 0 ]; then
    "$@"
    return $?
  fi
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@"
    return $?
  fi
  local pid waited=0
  "$@" &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$waited" -ge "$secs" ]; then
      kill -TERM "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  wait "$pid"
}

d1_execute_sql_file() {
  local db="$1"
  local file="$2"
  local out="${3:-/dev/null}"
  local prefix="${LOG_PREFIX:-[d1]}"
  local deadline="${D1_SYNC_DEADLINE:-0}"
  local delays_str="${D1_RETRY_DELAYS:-30 90}"
  local -a delays
  # shellcheck disable=SC2206  # 有意按空白切分秒数列表
  delays=($delays_str)
  local attempts=$(( ${#delays[@]} + 1 ))
  local call_timeout="${D1_EXEC_TIMEOUT_SEC:-300}"
  local budget_total="${D1_BUDGET_TOTAL_SEC:-0}"
  local started="${D1_BUDGET_START:-0}"
  local n=0 rc=124 delay now remaining attempt_timeout used
  local call_id
  call_id=$(_d1_call_id) || call_id=""

  while true; do
    # 每次尝试前先查预算: 预算不足时连一次调用都不发起(避免明知会超墙还硬跑)
    attempt_timeout="$call_timeout"
    if [ "$deadline" -gt 0 ]; then
      now=$(date +%s)
      remaining=$(( deadline - now ))
      if [ "$remaining" -le 0 ]; then
        if [ "$started" -gt 0 ] && [ "$budget_total" -gt 0 ]; then
          used=$(( now - started ))
          echo "$prefix 时间预算已用尽(已用 ${used}s / 预算 ${budget_total}s), 放弃重试; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
        else
          echo "$prefix 时间预算已用尽, 放弃重试; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
        fi
        return "$rc"
      fi
      # 单次上限不超过剩余预算(剩余 20s 就别再发 300s 的调用)
      if [ "$attempt_timeout" -gt "$remaining" ]; then
        attempt_timeout="$remaining"
      fi
    fi

    n=$(( n + 1 ))
    if D1_METRICS_MERGED_OUTPUT=1 _d1_observe import IMPORT bundle "${D1_METRICS_TABLES:-}" "$n" "$call_id" \
        _d1_run_with_timeout "$attempt_timeout" npx wrangler d1 execute "$db" --remote -y --json --file="$file" >"$out" 2>&1; then
      if [ "$n" -gt 1 ]; then
        echo "$prefix 重试第 $(( n - 1 )) 次成功(共 $n 次尝试)"
      fi
      return 0
    else
      rc=$?
    fi
    if [ "$rc" -eq 124 ]; then
      echo "$prefix 单次调用超时(上限 ${attempt_timeout}s), 按网络类失败处理" >&2
    fi

    if grep -qiE "$_D1_SQL_FATAL_RE" "$out" 2>/dev/null; then
      echo "$prefix 判定为 SQL 类错误(重放无效), 不重试; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
      return "$rc"
    fi

    if [ "$n" -ge "$attempts" ]; then
      echo "$prefix 重试已用尽($attempts 次尝试全部失败), 放弃; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
      return "$rc"
    fi

    delay="${delays[$(( n - 1 ))]}"
    if [ "$deadline" -gt 0 ]; then
      now=$(date +%s)
      remaining=$(( deadline - now ))
      echo "$prefix 网络类失败(第 $n/$attempts 次), 剩余预算 ${remaining}s, ${delay}s 后重试" >&2
      if [ "$remaining" -le 0 ]; then
        if [ "$started" -gt 0 ] && [ "$budget_total" -gt 0 ]; then
          used=$(( now - started ))
          echo "$prefix 时间预算已用尽(已用 ${used}s / 预算 ${budget_total}s), 放弃重试; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
        else
          echo "$prefix 时间预算已用尽, 放弃重试; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
        fi
        return "$rc"
      fi
      # 退避不超过剩余预算, 避免明知超时还硬等
      if [ "$delay" -gt "$remaining" ]; then
        delay="$remaining"
      fi
    else
      echo "$prefix 网络类失败(第 $n/$attempts 次), ${delay}s 后重试" >&2
    fi
    sleep "$delay"
  done
}
