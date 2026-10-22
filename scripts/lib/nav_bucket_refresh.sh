#!/usr/bin/env bash
# nav_bucket_refresh.sh — 公募日更 deploy 前的净值桶增量刷新(#278, 2026-10-22 用户拍板方案 A)。
#
# 背景/根因(全文 docs/ops/failed-units-rca-20261022.md「trade-public-fund-daily」行):
#   日更 16:20/17:00 只采净值, nav_bucket 产物一天只在 17:50 全量链(scripts/update_all.sh)
#   重出一次 ⇒ 当日新净值入库 / 同日数值被修正后, deploy 内 check_data_integrity 的 fund_nav
#   (阻断级, 用户 2026-10-13 拍板保留)必 FAIL;自愈探针只认「DB 领先产物」不认「同日不同值」。
#   近 7 天失败 5 天。修复 = **deploy 前先刷新净值桶再校验**(不降 fund_nav 阻断级、不改阈值)。
#
# 口径: 调 scripts/export_fund_nav.py --daily-refresh —— 与 17:50 全量链**同一脚本、同一
#   `_build_payload` 实现**(§5.4⑦ 禁止第二套口径), 只重建「最近 N 天有净值写入的基金」所在桶;
#   桶内逐 code 比对内容未变则不重写 ⇒ 幂等、无新净值时零写入。
#
# 并发/时点:
#   · 进程互斥 = 与 fund_nav_selfheal.sh **同一把锁** /tmp/trade_fund_nav_export.lock
#     (with_lock.py, 等锁超预算 ⇒ 留痕跳过, 不阻塞日更链)。
#   · 17:25-18:35 是 17:50 全量链窗口 ⇒ 跳过刷新(该链自己会在 deploy 前全量重出)。
#
# 退出码(调用方 public_fund_daily.sh 按此判定):
#   0  = 已刷新(或内容无变化, 零写入)
#   10 = 跳过(等锁超预算 / 落在 17:50 全量链窗口), 不是失败, deploy 照常继续
#   1  = 刷新失败 ⇒ **调用方必须阻断 deploy**, 并打印「nav_bucket 刷新失败」原因
#        (防静默继续: 否则 fund_nav 闸门会把「刷新失败」误报成 fund_nav 失败, §5.8 防假绿)
#
# 测试注入(仅供测试, 生产禁设; 见 scripts/tests/test_278_nav_bucket_refresh.py):
#   NAV_REFRESH_NOW=HHMM         覆盖当前时刻(窗口判定)
#   NAV_REFRESH_SKIP_BEGIN/END   覆盖窗口(默认 1725/1835)
#   NAV_REFRESH_EXPORT_CMD=...   覆盖刷新命令(默认 $PY scripts/export_fund_nav.py --daily-refresh)
#   NAV_REFRESH_PY / _WITH_LOCK / _HOOK / _LOCK / _LOCK_WAIT / _TIMEOUT / _LOG / _SKIP_MARK
set -u

_nbr_log() {
  if [ -n "${NAV_REFRESH_LOG:-}" ]; then
    printf '%s\n' "$*" | tee -a "$NAV_REFRESH_LOG"
  else
    printf '%s\n' "$*"
  fi
}

# rc 判据: 是否必须阻断 deploy。0=已刷新 / 10=跳过 ⇒ 不阻断; 其它 ⇒ 阻断(含超时 124)。
nav_bucket_refresh_blocks_deploy() {
  case "${1:-1}" in
    0 | 10) return 1 ;;
    *) return 0 ;;
  esac
}

nav_bucket_refresh_run() {
  local now_hhmm="${NAV_REFRESH_NOW:-$(date +%H%M)}"
  local skip_begin="${NAV_REFRESH_SKIP_BEGIN:-1725}"
  local skip_end="${NAV_REFRESH_SKIP_END:-1835}"
  local lock="${NAV_REFRESH_LOCK:-/tmp/trade_fund_nav_export.lock}"
  local lock_wait="${NAV_REFRESH_LOCK_WAIT:-120}"
  local exec_timeout="${NAV_REFRESH_TIMEOUT:-600}"
  local py="${NAV_REFRESH_PY:-${REPO:-}/.venv/bin/python}"
  local hook="${NAV_REFRESH_HOOK:-${REPO:-}/scripts/nav_refresh_lock_timeout_mark.sh}"
  local with_lock="${NAV_REFRESH_WITH_LOCK:-${REPO:-}/scripts/with_lock.py}"
  local mark="${NAV_REFRESH_SKIP_MARK:-${TMPDIR:-/tmp}/trade_nav_refresh_skip.$$}"

  local _v
  for _v in "$lock_wait" "$exec_timeout"; do
    case "$_v" in
      '' | *[!0-9]*)
        _nbr_log "✗ nav_bucket 刷新失败: 预算需为非负整数(等锁=${lock_wait} 工作=${exec_timeout})"
        return 1
        ;;
    esac
  done

  # ① 17:50 全量链窗口跳过(§14 生产稳定: 不与定时链撞车; 该链自己会全量重出 nav_bucket)
  if [ "$now_hhmm" -ge "$skip_begin" ] && [ "$now_hhmm" -le "$skip_end" ]; then
    _nbr_log "→ nav_bucket 刷新跳过: 当前 ${now_hhmm} 落在 17:50 全量链窗口 [${skip_begin},${skip_end}] 内(§14 避撞, 该链随后自行全量重出)"
    return 10
  fi

  # ② 留痕钩子必须先可用: with_lock 在「等锁超时跳过」时**也 exit 0**, 唯一区分手段就是本钩子
  #    写的标记文件; 钩子不可执行 ⇒ 无法区分「跳过」与「成功」⇒ 宁可按失败阻断 deploy(§5.8 不假绿)
  if [ -n "$hook" ] && [ ! -x "$hook" ]; then
    _nbr_log "✗ nav_bucket 刷新失败: 等锁超时留痕钩子不可执行($hook), 无法区分「跳过/成功」, 按失败处理阻断 deploy"
    return 1
  fi

  # ③ 组装刷新命令(默认 = 与 17:50 全量链同一脚本的增量模式)
  local -a cmd
  if [ -n "${NAV_REFRESH_EXPORT_CMD:-}" ]; then
    _nbr_log "  ⚠ 使用 NAV_REFRESH_EXPORT_CMD 覆盖刷新命令(仅测试路径): ${NAV_REFRESH_EXPORT_CMD}"
    cmd=(bash -c "${NAV_REFRESH_EXPORT_CMD}")
  else
    cmd=("$py" "${REPO:-.}/scripts/export_fund_nav.py" --daily-refresh)
  fi

  # ④ 持锁执行(与 fund_nav_selfheal 同锁; 等锁超预算 ⇒ 钩子留痕 + 跳过, 不 --nb 静默成功)
  local start_ts tmp_out rc elapsed
  rm -f "$mark"
  start_ts=$(date +%s)
  tmp_out=$(mktemp)
  NAV_REFRESH_SKIP_MARK="$mark" "$py" "$with_lock" \
    --block-timeout "$lock_wait" --on-timeout "$hook" \
    --exec-timeout "$exec_timeout" \
    "$lock" "${cmd[@]}" >"$tmp_out" 2>&1
  rc=$?
  while IFS= read -r line; do
    _nbr_log "$line"
  done <"$tmp_out"
  rm -f "$tmp_out"
  elapsed=$(( $(date +%s) - start_ts ))

  if [ -f "$mark" ]; then
    rm -f "$mark"
    _nbr_log "→ nav_bucket 刷新跳过: 导出锁被占用 / 等锁超过 ${lock_wait}s(持锁方正重出同一产物), 本次未执行; 交 deploy 闸门按既有规则判定"
    return 10
  fi
  rm -f "$mark"

  if [ "$rc" -ne 0 ]; then
    _nbr_log "✗ nav_bucket 刷新失败: export_fund_nav.py --daily-refresh 退出码=${rc}, 耗时 ${elapsed}s —— 产物未与 DB 对齐, 本次 deploy 阻断(不继续跑完报成功)"
    return 1
  fi
  _nbr_log "✓ nav_bucket 刷新完成, 耗时 ${elapsed}s"
  if [ "$elapsed" -gt 120 ]; then
    _nbr_log "⚠ nav_bucket 刷新耗时 ${elapsed}s 超过 2 分钟目标(需在实施报告标注并给优化)"
  fi
  return 0
}