#!/usr/bin/env bash
# check_r2_consistency.sh - §22 多源(http 层)一致性巡检包装(#160 / D5 P0-1)
#
# 背景(2026-10-05 #160,docs/ops/cloud-healthcheck-20261003/D5-deploy-chain-audit.md P0-1):
#   check_r2_consistency.py 存在但全仓无自动调度点(schedule_monitor.sh 仅注释引用、
#   systemd 无 unit、日志无运行痕迹)——§22「用户在 N 个展示位看到的数据必须统一」
#   的 HTTP 层一致性**零自动校验**,10-02 事故同款(overview 旧版 6 天无人知)若再
#   发生无自动探测。本脚本=云上 trade-r2-consistency.timer 的包装,把审计器接上调度。
#
# 时点选择依据(§14): 23:20 ——
#   当日晚链全部完成(overfit 21:40 / public-fund-full 22:00 / nextday-plan 22:30 /
#   check-data-gap 22:35)后, 两树 static-site/data 与 R2 均为当日终态;
#   位于 23:00 安全窗口内(不推 main 不写 DB);23 点档无其他 trade timer 与 cron
#   (:07/:37 为 hdszf 无关任务,已避开);云上 7x24 常开不涉唤醒。
#
# ⚠️ preflight: 晚链**尚未终态**时跳过本次检查(#160 收口 P1-1, 2026-10-05)。
#   根因: 云上 trade-update-all.timer = Mon..Sat 17:50 **+ Sun 22:30**(错峰档);
#     update-all 实测 112–139min(2026-10-04 周日 22:30:00→00:49:02 = 139min 实证)⇒
#     **周日 23:20 采样点必落在 update-all 半进程中**(export 已写本地 / R2 异步上传
#     r2_upload_async.sh 仍在写)⇒ local≠R2 过渡态 ⇒ 每周日 23:20 假 SEVERE。
#   修法=通用 preflight(非改 timer 时点/非排除周日): systemd `trade-update-all.service`
#     的 **ActiveState ∈ {active, activating}**(= 晚链在跑;oneshot 运行中即 activating,
#     详见 update_all_running() 内注释)时跳过本次检查、写日志、rc=0、**不发告警**。
#     对**任意**晚链意外延后(不只周日档)免疫; 改 timer 时点只在"这一档"生效且需动云上
#     生产 unit(§25 备份+恢复路径); 采样点后移则会撞 02:00/02:17 等深夜档。
#   代价(如实登记): 跳过当次 → 该日一致性**未校验**, 由次日 23:20 覆盖(不变量是持续态,
#     漏一天采样不产生"已确认一致"的假信号, 且不吞故障——update-all 自身失败有独立告警链)。
#   判据可注入(自测用): R2_CONSISTENCY_PREFLIGHT_STUB=active|inactive 强制分支(生产不设)。
#
# 为什么是独立 timer 而非 deploy 链闸门(闸门位置/爆炸半径分析见报告 §2):
#   段1 末尾 R2 上传已异步化(r2_upload_async.sh,2026-10-04)——该时刻 R2 可能正在
#   写、CF purge 未生效,此刻比对必假阳;且卡 deploy = 数据已上 R2 而 min 未推的
#   半完成态(§23.11/main-merge-fail)。独立日巡检:采样点在稳定态、零 deploy 爆炸
#   半径,且覆盖「deploy 根本没跑 / R2 被外部覆盖」的持续态(10-02 类正是持续态)。
#
# 判定/出口: check_r2_consistency.py rc!=0(local/R2直链/CF r2-proxy/主站同源 四源
#   指纹不一致,或某源拉取失败)→ notify --severe(去重 6h);rc=0 静默(仅日志)。
#   **preflight 跳过**(update-all 在跑)也是 rc=0 + 静默, 但日志留 [preflight-skip] 痕。
#   连续 2 天 FAIL 由 notify.py 侧 R7① 升级 critical(见 alert_denoise_rules.py:r7_*)。
#   仅告警不阻断: 本检查不在任何推送链上,不存在"阻断谁"的动作,告警即收敛口。
#   超长任务日志走 systemd journal(unit 不设 StandardOutput append,避 root 属主冲突 ——
#   trade-r2-consistency.sh 自己写同名 *_launchd.log,同 systemd-units §1.4 例外条款)。
#
# 每日跑(不限交易日): 「各源一致」是不变量,任何一天都须成立——周末被外部覆盖
#   同样要抓,故不设交易日闸门。
#
# 用法: bash scripts/check_r2_consistency.sh [force]   # force 保留位(当前无闸门,等价直跑)
# 日志: data/logs/r2_consistency_launchd.log(固定名 append, 标准开始/结束行供
#   gen_schedule_stats standard 模式与 schedule_monitor 漏跑检查直读, 同 check_data_gap 先例)
set -u

# ── REPO/GIT_REPO 单点解析(#195 批1):共享 lib(env 优先零改写 > $0 双布局推导 > fail-loud)──
# 去掉写死的 mac 默认值(原靠 unit 的 Environment= 兜住,env 一丢即静默坏);原 export
# 语义保留(下方 export REPO GIT_REPO),python 子进程可见性与迁移前逐字节一致。
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/repo_paths.sh" || { echo "FATAL: repo_paths.sh missing" >&2; exit 2; }
resolve_repo "${BASH_SOURCE[0]}"
export REPO GIT_REPO
PY="${PY:-$REPO/.venv/bin/python}"
LOGDIR="$REPO/data/logs"
mkdir -p "$LOGDIR"
cd "$REPO"
LOG="$LOGDIR/r2_consistency_launchd.log"

run_to() {
  local t="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$t" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$t" "$@"
  else
    perl -e 'alarm shift; exec @ARGV or exit 127' "$t" "$@"
  fi
}

echo "=== check_r2_consistency.sh 开始 $(date '+%F %T') ===" >> "$LOG"

# ---- preflight: 晚链未终态(update-all 在跑)则跳过(见文件头 ⚠️ preflight 段) ----
update_all_running() {
  # 自测桩: 显式注入判据分支, 生产不设(云上是生产, 不许真 start/stop update-all)
  case "${R2_CONSISTENCY_PREFLIGHT_STUB:-}" in
    active)   return 0 ;;
    inactive) return 1 ;;
  esac
  if command -v systemctl >/dev/null 2>&1; then
    # ⚠️ 判据必须看 ActiveState 值本身, **不能用 `is-active --quiet`**(2026-10-05 reviewer P0):
    #   update-all 是 Type=oneshot(RemainAfterExit=no), 运行中 ActiveState=**activating**;
    #   而 systemd v249 的 `is-active` 只把 {active, reloading} 当 good state, **不含
    #   activating** → 对运行中的 oneshot 返回 EXIT_PROGRAM_NOT_RUNNING=**3**(与 inactive 同码)
    #   ⇒ 用 is-active 判「在跑」在生产**恒不成立**(跳过分支=死代码, 周日假 SEVERE 照样发生)。
    #   云上活体实测(2026-10-05, systemd-run 瞬态 oneshot): 窗口内 ActiveState=activating 且
    #   is-active --quiet rc=3 持续成立 —— 两判据必须分开看。
    #   故此处按 ActiveState 文本判, 显式含 activating。
    local _uas
    _uas="$(systemctl show -p ActiveState --value trade-update-all.service 2>/dev/null)"
    case "$_uas" in
      active|activating) return 0 ;;
    esac
    return 1
  fi
  # 非 systemd 环境(本机 mac 开发, 定时任务全在云上): 回退进程名探测
  pgrep -f "update_all.sh" >/dev/null 2>&1 && return 0
  return 1
}

if update_all_running; then
  echo "[preflight-skip] trade-update-all 仍在运行(晚链未终态: export 已写本地 / R2 异步上传滞后, 此刻比对必假阳)" >> "$LOG"
  echo "[preflight-skip] 本次跳过一致性检查, rc=0, 不告警(由次日 23:20 覆盖)" >> "$LOG"
  echo "=== check_r2_consistency.sh 结束 $(date '+%F %T') 退出码=0 ===" >> "$LOG"
  exit 0
fi

# 相对路径走 trade-data/scripts symlink(merge 即生效,与全站任务同哲学)。
# 超时 900s: 全量四源×(9 产物)HTTP 拉取, 大件(concepts 32.6MB / accum_nav 26MB)
# 在云上秒级, 900s 为宽余(含单源 2 次重试的 12s 超时窗口)。
OUT="$(run_to 900 "$PY" scripts/check_r2_consistency.py --quiet 2>&1)"
RC=$?
printf '%s\n' "$OUT" >> "$LOG"

if [ "$RC" -ne 0 ]; then
  # 摘录问题段(=== N 项问题 === 起)进告警正文; HTML 转义 + 换行折成 |(邮件体单段)
  BODY="$(printf '%s\n' "$OUT" | sed -n '/项问题/,$p' | head -12)"
  [ -z "$BODY" ] && BODY="$(printf '%s\n' "$OUT" | tail -8)"
  BODY_ESC="$(printf '%s' "$BODY" | sed 's/&/\&amp;/g; s/</\&lt;/g' | tr '\n' '|')"
  echo "✗ §22 多源一致性校验失败 rc=${RC},发 severe 告警" >> "$LOG"
  "$PY" scripts/notify.py "[告警] §22 三站一致性校验失败" \
    "check_r2_consistency 检出 local / R2直链 / CF r2-proxy / 主站同源 多源不一致或某源拉取失败(rc=${RC})。<br>${BODY_ESC}<br>脚本: scripts/check_r2_consistency.py &nbsp;日志: ${LOG}" \
    --severe --from-prefix "[告警]" --dedup-key r2_consistency_fail --dedup-window 21600 2>&1 | tee -a "$LOG" || true
fi

echo "=== check_r2_consistency.sh 结束 $(date '+%F %T') 退出码=$RC ===" >> "$LOG"
exit "$RC"