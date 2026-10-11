#!/usr/bin/env bash
# upload_watchdog.sh — r2_upload_async.sh 看门狗判据「纯函数库」(2026-10-11 抽取)
#
# 为什么抽成库: 低速判据的「窗口取值」与「是否 kill」是可穷举的纯判定, 但它的宿主
#   r2_upload_async.sh 主体会真的发起 R2 上传(§18 L50: 探针一律 static-only, **绝不
#   source/exec 业务脚本主体**)。把判定抽成**无副作用**的纯函数后, 测试只需经 stdin 管道
#   source 本文件即可(与 scripts/lib/repo_paths.sh 同款 pattern), 既覆盖真实代码(不写第二份
#   实现, 免 §5.4⑦ 漂移), 又零外发/零网络。
#
# 背景(2026-10-11 upload-trade-sim 两轮低速误杀根因, 见 docs/ops/watchdog-tradesim-slowkill-20261011.md):
#   · a1 梯度倒置: 低速窗口原先硬编码 300s, 而内层单请求 HTTP 超时(R2_UPLOAD_HTTP_TIMEOUT, 云上
#     .env=600) ⇒ 300 < 600, 内层「600s 超时→丢连接→退避→重试」自愈链永远没机会跑就被外层 kill。
#     停滞判据早做过同款防倒置(#217②, r2_upload_async.sh L112-125), 低速判据漏了 → 本库补齐。
#   · a2 收尾豁免: 8 线程池「只剩最后 1~2 个文件在飞/等响应」时必然 5 分钟零增量(其余线程早空闲,
#     无完成行可产), 此刻杀 = 100% 触发下轮 marker→全量(200MB 级)。收尾阶段不做低速杀
#     (交停滞判据 900s / 硬 7200s 守; ⚠️ 是「不杀低速」不是「永不杀」)。
#
# 用法: r2_upload_async.sh 顶部 `source .../lib/upload_watchdog.sh`(本库只定义函数+常量, 无副作用)。

# 低速判据「批量通道」下限: 批内文件总数 M 必须 > 此值, 低速判据才适用(与 caller 的 sticky-read
# 门槛同源, 单点定义防两处 magic number 漂移)。小通道/对账通道不适用, 靠停滞判据+硬兜底。
R2_LOW_SPEED_MIN_BATCH=10

# r2_low_speed_window <http_timeout_secs> → 低速判据窗口(秒) = max(900, HTTP超时 + 300)
#   与停滞判据同款口径: **不硬编码 900**, 跟随内层单请求超时, 且设 900s 下限。
#   数学校验(防倒置): 内层自愈周期上界 ≈ HTTP超时 + 退避和(≤15s) + 重试后首行打点(≤60s)
#     = HTTP超时 + 75;而 max(900, HTTP+300) 恒 > HTTP+75(HTTP≤625 时窗口=900>HTTP+75;
#     HTTP>625 时窗口=HTTP+300>HTTP+75)⇒ 只要内层还活着(超时→重试→打点回暖)就杀不掉。
#   非法/缺省输入回落 30(与 r2_upload_async.sh 读 R2_UPLOAD_HTTP_TIMEOUT 的回落一致)。
r2_low_speed_window() {
  local http_to="${1:-30}"
  case "$http_to" in ''|*[!0-9]*) http_to=30 ;; esac
  local w=$((http_to + 300))
  [ "$w" -lt 900 ] && w=900
  printf '%s\n' "$w"
}

# r2_parse_progress <token> → "N M"(解析形如 `[N/M]` 的进度 token; N=已完成数, M=批次总数)
#   非法/空输入 → "0 0"(调用方按 0 处理)。抽进库 = 让 N/M 解析也可被测试直接覆盖(免第二份实现)。
r2_parse_progress() {
  local tok="${1:-}" n m
  n="${tok#\[}"        # 去前导 [
  m="${n##*/}"         # 最后一个 / 之后的 M(含尾 ])
  n="${n%%/*}"         # 第一个 / 之前的 N
  m="${m%]}"           # 去尾 ]
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  case "$m" in ''|*[!0-9]*) m=0 ;; esac
  printf '%s %s\n' "$n" "$m"
}

# r2_low_speed_need <window_secs> → 触发 kill 所需的「连续低速采样次数」(窗口/60, 向上取整)
r2_low_speed_need() {
  local window="${1:-900}"
  case "$window" in ''|*[!0-9]*) window=900 ;; esac
  printf '%s\n' $(( (window + 59) / 60 ))
}

# r2_tail_near_complete <batch_total_M> <completed_N> [min_batch]
#   收尾阶段判定: 批量通道(M > min_batch)且只剩最后 ≤2 个文件(N ≥ M-2)。命中返回 0, 否则 1。
#   依据: 杀它=下轮全量(200MB 级), 等它=最多一个内层超时周期; 且 8 线程池收尾必然零增量。
r2_tail_near_complete() {
  local m="${1:-0}" n="${2:-0}" min_batch="${3:-$R2_LOW_SPEED_MIN_BATCH}"
  case "$m" in ''|*[!0-9]*) m=0 ;; esac
  case "$n" in ''|*[!0-9]*) n=0 ;; esac
  case "$min_batch" in ''|*[!0-9]*) min_batch=$R2_LOW_SPEED_MIN_BATCH ;; esac
  [ "$m" -gt "$min_batch" ] || return 1
  [ "$n" -ge $((m - 2)) ] || return 1
  return 0
}

# r2_low_speed_should_kill <low_bad_count> <window_secs> <batch_total_M> <completed_N> [min_batch]
#   低速杀判定: 批量通道(M > min_batch) 且 连续低速采样数 ≥ need 且 **非收尾阶段** ⇒ 应杀(返回 0)。
#   收尾阶段(接近完成)⇒ 豁免(返回 1, 由调用方落日志); 未达窗口/非批量 ⇒ 返回 1。
#   ⚠️ 收尾豁免只放开「低速」这一路: 真停滞由停滞判据(900s mtime)/7200s 硬兜底继续守(红线不许改成永不杀)。
r2_low_speed_should_kill() {
  local bad="${1:-0}" window="${2:-900}" m="${3:-0}" n="${4:-0}" min_batch="${5:-$R2_LOW_SPEED_MIN_BATCH}"
  case "$bad" in ''|*[!0-9]*) bad=0 ;; esac
  case "$m" in ''|*[!0-9]*) m=0 ;; esac
  case "$min_batch" in ''|*[!0-9]*) min_batch=$R2_LOW_SPEED_MIN_BATCH ;; esac
  [ "$m" -gt "$min_batch" ] || return 1                      # 非批量通道: 低速判据不适用
  [ "$bad" -ge "$(r2_low_speed_need "$window")" ] || return 1 # 未达窗口
  if r2_tail_near_complete "$m" "$n" "$min_batch"; then
    return 1                                                 # a2 收尾豁免
  fi
  return 0
}