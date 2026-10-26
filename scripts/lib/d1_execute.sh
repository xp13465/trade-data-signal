#!/bin/bash
# d1_execute_sql_file - 单文件 SQL 导入 D1(带网络类失败重试), 供 sync_fund_*_to_d1.sh 共用。
#
# 用法: source 本文件; 调用 d1_execute_sql_file <db名> <sql文件> [输出文件]
#   成功返回 0; 失败返回 wrangler 的原始非 0 码(**绝不吞**)。
#
# 重试口径(2026-10-26 D1 单文件导入改造):
#   · **只重试网络类失败**(fetch failed / 连接断 / 超时 / 5xx 等); 明确的 SQL 错误
#     (SQLITE_TOOBIG / syntax error / no such table|column / constraint failed)不重试,
#     因为同一份 SQL 重放必然同样失败, 只会白等两轮。
#   · 最多重试 2 次, 退避秒数取环境变量 `D1_RETRY_DELAYS`(默认 "30 90")。
#     测试用 `D1_RETRY_DELAYS="0 0"` 即可零等待跑真实分支。
#   · 每次重试前打印剩余时间预算: `D1_SYNC_DEADLINE`(epoch 秒, 0/未设 = 不限)。
#   · 重试用尽/预算用尽 ⇒ 返回非 0, 由调用方按既有 `_fail()` 出口记录失败状态(不静默)。
#
# 为什么抽成 lib: 两个同步脚本各写一份重试循环 = 第二份实现静默漂移
#   (§5.4⑦ 同精神); 且本函数只做「调 wrangler + 分类 + 退避」, 不读业务数据,
#   可在测试里用假 npx 打桩走真分支(零真实外发/L50)。

# 明确属于「重放也没用」的 SQL 类错误(小写匹配)。
_D1_SQL_FATAL_RE='sqlite_toobig|statement too long|syntax error|no such (table|column)|constraint failed|has no column named'

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
  local n=0 rc=0 delay now remaining

  while true; do
    n=$(( n + 1 ))
    if npx wrangler d1 execute "$db" --remote -y --file="$file" >"$out" 2>&1; then
      if [ "$n" -gt 1 ]; then
        echo "$prefix 重试第 $(( n - 1 )) 次成功(共 $n 次尝试)"
      fi
      return 0
    else
      rc=$?
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
        echo "$prefix 时间预算已用尽, 不再重试; 诊断: $(tail -n 1 "$out" 2>/dev/null | tr -d '\r')" >&2
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